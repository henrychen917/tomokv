# cx-l4prebuild — round 2, 512/768-byte boundaries on v6

Worktree `/home/user/Projects/cx-l4prebuild`, branch `cx-l4prebuild`.
Reference **v6 = d90843b96**. The lane incorporated v6 in `a7255b795`, including
its retired reorder pass, before building these arms. The maintainer runs all
servers, measurements and the iteration gate. This lane builds and runs only
serverless units on CPUs **112–127**.

## Why this round exists

Maintainer results, round 1 candidate `8ba4b3d5a` (>192 B) versus v5,
8 pinned generator instances, same-binary floor ±1.6%, arm spreads ≤2%:

| Cell | PRE → POST rate change | Verdict supplied by maintainer |
| --- | ---: | --- |
| `l4_set_1s_1024` | +3.62% | Real target gain |
| `l4_set_1s_256` | −9.08% (10.20 → 9.29 M/s) | Regression; loses owner-born placement |
| `l4_set_2s_1024` | +0.92% | Neutral |

These are round 1 results, not evidence for either new boundary. The old
`build/tomokv-l4prebuild{,-pad,-pre}` artifacts are historical v5 arms; do not
substitute them into this request.

## Arms and reproduction

| Arm | Binary | Policy |
| --- | --- | --- |
| PRE-v6 | `build/tomokv-l4prebuild-pre-v6` | Untouched `d90843b96`, built from a local archive |
| POST-512 | `build/tomokv-l4prebuild-512` | Prebuild only foreign fused SET/MSET values **>512 B** |
| PAD-512-A | `build/tomokv-l4prebuild-512-pad` | **Kind (A) behaviour twin:** PRE allocation behaviour in POST-512 text/layout |
| POST-768 | `build/tomokv-l4prebuild-768` | Prebuild only foreign fused SET/MSET values **>768 B** |
| PAD-768-A | `build/tomokv-l4prebuild-768-pad` | **Kind (A) behaviour twin:** PRE allocation behaviour in POST-768 text/layout |

`TOMO_L4_PREBUILD_THRESHOLD` is a compile-time constant in
`src/cmd/l4prebuild.cc`. Its unqualified default is now 512 B; that is a candidate
default, not a measured selection. The named Makefile targets explicitly compile
512 and 768. All common release objects and their link order are shared. No
runtime knob, object field, record layout, or owner arena pointer is added.

Each PAD is copied from its matching POST and patched only at the `noipa`
`l4prebuild_policy(uint32_t)` entry to return false (`xor eax,eax; ret`, preserving
CET). The patch disables both SET and MSET construction and MSET's forced
same-shard scatter. All remaining bytes, section sizes and symbol addresses
stay identical to that POST. The candidate's gates remain: PRE/PAD measures
their cost plus placement changes; PAD/POST attributes the allocation policy.
These are **kind A**, with no kind-B arm.

```sh
# Build only; no server or benchmark is executed by this target.
taskset -c 112-119 make -j4 l4prebuild-round2
# All linked production objects are instrumented by the TSAN targets.
taskset -c 120-127 make -j4 build/l4prebuild-unit-512-tsan build/l4prebuild-unit-768-tsan
```

PAD receipts are `build/tomokv-l4prebuild-{512,768}-pad.json`.
Regenerate one independently without executing it:

```sh
taskset -c 112-119 python3 tools/l4prebuild_artifacts.py build/tomokv-l4prebuild-512 build/tomokv-l4prebuild-512-pad --receipt build/tomokv-l4prebuild-512-pad.json
```

## Behaviour and controls

At or below the selected boundary, values remain owner-materialized. The SET
parser retains the original handler; same-shard MSET retains localfast. Above
it, only foreign keys posted by fused IO prebuild header and external payload.
Local keys, 2s, MULTI children and **all MSETNX** retain owner construction.
Mixed MSET requests decide per key. MSETNX still checks existence first.

All installation, admission, SET option decisions, relative expiry evaluation,
and visibility publication stay on the owner. Existing receive-buffer lifetime,
RYOW, single-owner writes and immutable/QSBR replacement are unchanged. SET
allocation failure falls back to its original owner handler; refused posts and
pre-handler denial free any candidate. MSET uses the existing anchor ownership
and abort cleanup. A TTL-bearing SET may replace its header on the owner while
transferring the external payload without recopying it.

The threshold stays out of caller translation units so bisecting it cannot alter
their code generation. This does not by itself prove all inactive code identical
to v6: the required dispatch/cleanup gates and any compiler drift are audited
separately below. A PAD is a control, not a waiver for byte differences.

## Measurement request

Use the **current v6 gate instrument**, calibrated box geometry and OP:BYTES
grammar from `/home/user/Projects/calib/set-cells.txt` and
`/home/user/Projects/calib/l4-cells.txt`. Pin **all six L4 cells to 8 generator
instances**, with the same server/generator CPU maps in every arm. Preserve
the scheduled 32-owner geometry, p8, 512 connections, atomic=1, rl=ov=ro=0,
balancers, key distribution, duration, warmup and command denominator.
Use the maintainer's current pinned rate-cell rungs for h01/h02/h05/h07.
At matched offered load report rate, cycles/op, instructions/op and IPC; do
not replace the box measurement with a loopback cycles diagnostic.

| Cell | Operation/settings | PRE-v6 | POST-512 | PAD-512-A | POST-768 | PAD-768-A |
| --- | --- | --- | --- | --- | --- | --- |
| `l4_set_1s_256` | 1s SET:256, p8 | pending | pending | pending | pending | pending |
| `l4_set_1s_1024` | 1s SET:1024, p8 | pending | pending | pending | pending | pending |
| `l4_set_2s_1024` | 2s SET:1024, p8 | pending | pending | pending | pending | pending |
| `l4_mset_1s_256` | 1s MSET:256, p8 | pending | pending | pending | pending | pending |
| `l4_mset_1s_1024` | 1s MSET:1024, p8 | pending | pending | pending | pending | pending |
| `l4_msetnx_1s_1024` | 1s MSETNX:1024, p8 | pending | pending | pending | pending | pending |
| `h01` | 1s GET p32, ov=0, ro=0 | pending | pending | pending | pending | pending |
| `h02` | 1s SET p32, ov=0, ro=0 | pending | pending | pending | pending | pending |
| `h05` | 1s GET p32, ov=1, ro=0 | pending | pending | pending | pending | pending |
| `h07` | 1s GET p32, ov=1, ro=1 | pending | pending | pending | pending | pending |

On v6, reorder=1 is intentionally a no-op; h07 remains a named control. Use
the v6 harness that accepts the retired knob, rather than the old INFO witness.

For **each** threshold run PRE/POST/POST/PRE, PRE/PAD/PAD/PRE and
PAD/POST/POST/PAD. Pool at least two blocks on the pinned L4 rung, retaining
paired changes and same-binary controls. Record exact commands, all artifact
and instrument digests, CPU maps, matched load, repetitions and spreads in
`MEASURE-RESULT`. Cycles/op = instructions/op / IPC; rate at matched load decides.

**Decision:** recover the 256 B cells to neutral against v6 while preserving a
real 1 KiB fused SET gain and improving the MSET target. Require zero regression
on 2s SET, MSETNX and all four rate controls under the gate's acceptance rules.
POST must move relative to PAD as well as PRE to attribute a policy gain. The
reported ±1.6% SET/approximately ±2% L4 floor is not an acceptance waiver;
spreads >2% need investigation. No round 2 performance result is claimed.

The requested 256/1024 B cells bracket **both** thresholds, so they take the
same policy decisions in POST-512 and POST-768. They can establish recovery
and target retention but cannot identify the break-even size within 513–768 B.
A choice between the boundaries needs the maintainer's subsequent middle-size
cells; an apparent difference on this identical-policy grid is not a size-policy
effect.

## Correctness and byte receipts

No gate rows or EXPECT constants are changed relative to v6: delta **0 quick /
0 full**, so `EXPECT_QUICK=419`, `EXPECT_FULL=435` remain the maintainer's values.
The quick exit begins at `tests/gate.sh:2758` (exit at 2762); all added tests are
standalone unit targets. The maintainer still runs `tests/gate.sh iteration`
and boots both modes at the gate's **16 shards / GATE_RATIO / GATE_CORES**.

The fixture uses 16 shards / eight reserved CPUs, with 6 IO + 2 EX in split
mode. Both boundaries run 1s/2s × read-local 0/1, natively and under TSAN.
The boundary checks exercise 256, 512, 513, 768, 769 and 1024 B through the
actual SET parser and MSET owner phases; check original handlers/localfast,
owner and IO allocation arenas, mixed sizes, duplicate keys, MSETNX, OOM,
SET options/TTL/notifications, atomic=0/1, QSBR and quiesced migration.
The parser forces inbox refusal and owner admission denial. A concurrent
SPSC test checks complete payload publication and exact pointer adoption.
PAD-patched units must fail their positive prebuild witness.

Builds, validation logs, manifests and byte audits are in
`build/l4prebuild-round2/`.

## Final receipts

Product source: `c86c1dd20`; final unit fixture: `66386e99d`. Compiler GCC 13.3.0,
jemalloc, release flags `-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`.
The per-TU compiler budgets are v6's unchanged values. PRE and initial TSAN
builds used 112–119, POST and native units used 120–127; all lane work stayed
inside 112–127. **No server binary, benchmark, or gate was executed.**

| Arm | `.text` bytes | SHA256 |
| --- | ---: | --- |
| PRE-v6 | 3,532,099 | `4f8ff56d96d39a60c614d21ec0fbd28f03bf8dd1f1ff07d4757d0ad60d2c7276` |
| POST-512 | 3,556,371 | `8aed5e9a9e1b51d4a0b81d2954ef53dda155509de1a3751519fe8ee765b0e484` |
| PAD-512-A | 3,556,371 | `efb1014d8c18ed7274b1f871d6cc956e966934d25228fd3bdb76d9bf29b7f2af` |
| POST-768 | 3,556,371 | `2cd0914d7a2a3c7d89747b07c98cf8846dc413e9a87c3d4c6f3c89b189675889` |
| PAD-768-A | 3,556,371 | `a75fb1c01652edd073b133c2eff4c4f6e9fe81c36509c30f20a39ee2388ea980` |

Each POST grows `.text` by 24,272 bytes against v6. **POST-512 and POST-768
have identical sections and symbol tables, and differ in exactly one `.text`
byte**, the comparison immediate in the 14-byte policy function. Every other
text byte matches. The policy bodies are:

```text
512: f30f1efa81ff000200000f97c0c3
768: f30f1efa81ff000300000f97c0c3
```

Each PAD changes only three bytes at file offset 3,570,804, immediately after
the policy's CET landing instruction. Every other byte and every section and
symbol entry matches that arm's POST. Full manifest and cross-boundary proof:
`build/l4prebuild-round2/artifacts.json`; PAD receipts:
`build/tomokv-l4prebuild-{512,768}-pad.json`.

| Check | Result |
| --- | --- |
| `make unit` | All five v6 standalone unit programs pass |
| Boundary units | **8/8**: 512/768 × 1s/2s × read-local 0/1 |
| Fully instrumented boundary TSAN units | **8/8**, no TSAN reports |
| Existing owner-arena unit | **4/4**, both modes and read-local states |
| Atomic survivors | admission, write_latest, mset_arity, rename_overlay, watch_parent pass |
| PAD unit negative controls | Both exit **1** at the positive prebuild witness |
| Inclusive-boundary unit negative controls | Both exit **1** at the exact per-key policy assertion |

Native units run with `taskset -c 120-127`; TSAN units with `taskset -c 112-119`,
`TSAN_OPTIONS=halt_on_error=1:exitcode=66`, and `setarch x86_64 -R`.
GCC emits its existing `atomic_thread_fence` TSAN modelling warnings; no test
output contains a TSAN diagnostic. Neither test tier starts a listener or
initializes io_uring. Parser and concurrent handoff cases run on the unarmed
fixture; armed cases exercise the real store and QSBR retirement paths.

The placement assertions use fresh parser workers/tcaches, since the separate
migration/abort cases intentionally populate an owner's cache with historical
IO-arena blocks. The long parser key keeps header and payload allocation
classes distinct at 513 B. The refusal/admission witnesses and exact allocation
counts are still mandatory; no check was skipped or tolerance widened.

The negative controls are copies of **unit binaries only** in
`build/l4prebuild-round2/`. PAD returns false; the inclusive-boundary control
patches the compare from N to N−1, causing a value exactly N bytes long to
prebuild incorrectly. All four terminate with
`FAIL owner arena: exact per-key prebuild policy`. The expected decisions come
from the fixture's compile-time boundary, independently of the patched policy.

All eight static size locks hold: Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. Gate row delta remains 0.

Validation manifests: `native-results.json`, `tsan-results.json`,
`existing-unit-results.json`, `negative-results.json` in the round 2 directory;
each names the commands, outcomes and corresponding logs. Build logs:
`pre-build.log`, `post-build.log`, `tsan-build.log`, `unit-final-build.log`,
`tsan-final-build.log`. No performance result is inferred from these checks.

## Byte-identity limit against v6 — not a full pass

All **314/314 original string-family function bodies** (143 clean, 171 notify)
are byte-identical, including resolved relocation targets. The broader selected
hot-body audit is **561/576 raw-identical, 564/576 with address displacements
resolved**. This is an object-level audit; it does not assert unchanged absolute
addresses in the linked PRE and POST executables.

| Object group | Audited | Bytes + resolved targets identical |
| --- | ---: | ---: |
| `main.o` | 128 | 128 |
| `t_string.o` + `t_string_notify.o`, selected hot bodies | 24 | 24 |
| `genthread.o` | 113 | 108 |
| `rl2s.o` | 187 | 182 |
| `xshard.o` | 11 | 9 |
| Other selected command/persistence/snapshot bodies | 113 | 113 |

Eight differences are the required fused parser eligibility/refusal hooks and
fused executor rejection cleanup. **Four collateral bodies still differ**:

- `genthread.o`: the split TLS `parse_and_dispatch<true, 0u, ...>` clone.
- `rl2s.o`: `IoLoop::run_loop<true, false, false, true, (unsigned char)1, true>`.
- `xshard.o`: `FlatStore::find_notify` and `FlatStore::erase_notify`.

Exact mangled names, sizes and comparisons are in `bytes.json` / `bytes.log`;
the complete string-family audit is `string-bytes.json`. Reproduce the broad
audit (exit 1 deliberately reports the remaining differences):

```sh
taskset -c 112-119 python3 tools/lbstall_artifacts.py compare build/l4prebuild-round2/pre-v6/build/src build/src build/l4prebuild-round2/bytes.json
```

Thus the literal whole-inactive-path byte-identity requirement is **not fully
satisfied against v6**. The original SET/GET handlers and the one-byte-only
threshold bisect are preserved; passing units and exact-layout PADs do not waive
the four collateral object-level differences. The maintainer must account for
them when judging the candidate. The 512/768 variants themselves introduce no
additional text drift between boundaries.
