# cx-l4prebuild — foreign external values built on fused IO

Worktree `/home/user/Projects/cx-l4prebuild`, branch `cx-l4prebuild`.
PRE: `e4ec4dfcedb2f3b35feda8bcbfbce753b3a491a1` (v5).
This is an unmeasured candidate. The maintainer schedules all server runs, measurements,
and `tests/gate.sh iteration`; this lane runs only pinned builds and serverless units.

## Arms

| Arm | Binary | Meaning |
| --- | --- | --- |
| PRE | `build/tomokv-l4prebuild-pre` | Untouched v5, built before edits |
| POST | `build/tomokv-l4prebuild` | Foreign external SET/MSET prebuild, boundary 192 bytes |
| PAD-A | `build/tomokv-l4prebuild-pad` | **Kind (A), behaviour twin:** PRE allocation behaviour with POST's exact text size/layout |

PAD-A is a copy of POST with only the entry of the out-of-line, `noipa`
`l4prebuild_policy(uint32_t)` patched to `xor eax,eax; ret` (CET landing preserved).
It disables both SET and MSET prebuilding, including the foreign same-shard MSET
scatter selection. All ELF section sizes, symbol addresses, and other bytes remain
POST's. It retains the candidate's eligibility gates; measure PRE/PAD to price those
and changed code placement. POST/PAD isolates the allocation/copy policy. No runtime
configuration knob, record-layout change, or owner arena pointer was introduced.
There is no kind-B arm.

Reproduce PAD without executing either server:

```sh
taskset -c 112-127 python3 tools/l4prebuild_artifacts.py \
  build/tomokv-l4prebuild build/tomokv-l4prebuild-pad \
  --receipt build/l4prebuild-proof/pad.json
```

## What changes

Only posting IO in **1s**, for a **foreign owner** and a value **strictly larger than
192 bytes**, constructs the external string header and payload. All installation,
admission, conditional SET decisions, relative expiry evaluation, and visibility
publication remain on the executing owner. The receive-buffer arguments stay pinned
for AOF, notifications, and command lifetime exactly as before.

SET selects an alternate CommandSpec only after successful construction. The alternate
handler shares the original SET option parser. Failed NX/XX, invalid options, elapsed
absolute deadlines, and insertion errors reclaim the candidate. A TTL-bearing SET may
replace only the small header after the owner decides its TTL reservation; it transfers
the external payload without recopying it. IO allocation failure falls back to the
original owner handler, preserving option/error precedence. A refused queue post frees
the unpublished candidate. Owner admission/prepare denial frees it before publishing
Done; ordinary reply retirement keeps its original implementation.

MSET uses `KeyRef::key_anchor/stable_object` and the existing abort/unpublished cleanup.
Mixed commands prebuild only their qualifying keys. A foreign same-shard MSET with an
eligible value uses a one-fragment scatter to carry ownership. Atomic-off MSET also
consumes the candidate. **MSETNX always materializes after owner existence checks.**
Local keys, embedded values, 2s, and MULTI children retain owner materialization.
The origin-client argument identifies top-level IO preparation; owner/transaction
callers of `xshard_prepare` do not opt in merely by invoking that helper.

The boundary is `TOMO_L4_PREBUILD_THRESHOLD` in `src/cmd/l4prebuild.cc`, default 192,
with a static assertion that it is at least `kEmbedThreshold`. For a 256/512/768/1024
bisect, change that definition and rebuild once, or rebuild with the corresponding
`-DTOMO_L4_PREBUILD_THRESHOLD=N`. The comparison is `value_bytes > N`.
Preserve each resulting binary separately and regenerate its PAD from that POST.

## Measurements requested — every iteration

Use the gate's own calibrated instrument and frozen generator at matched offered
load, preserving generator count, pins, duration, warmup, balancers, key distribution,
command denominators, and overload/engagement checks across all arms. The L4 cells
use the scheduled **32-owner** box geometry, p8, 512 connections, atomic=1, rl=ov=ro=0.
Use **OP:BYTES** from `/home/user/Projects/calib/set-cells.txt` and
`/home/user/Projects/calib/l4-cells.txt`; do not silently substitute the default
64-byte SET or a loopback cycles diagnostic.

| Cell | Exact operation / settings | PRE | POST | PAD-A |
| --- | --- | --- | --- | --- |
| `l4_set_1s_1024` | 1s SET:1024, p8 | pending | pending | pending |
| `l4_set_1s_256` | 1s SET:256, p8 | pending | pending | pending |
| `l4_mset_1s_1024` | 1s MSET:1024, p8 | pending | pending | pending |
| `l4_mset_1s_256` | 1s MSET:256, p8 | pending | pending | pending |
| `l4_set_2s_1024` | 2s SET:1024, p8 | pending | pending | pending |
| `h01` | 1s GET p32, overlap=0, reorder=0 | pending | pending | pending |
| `h02` | 1s SET p32, overlap=0, reorder=0 | pending | pending | pending |
| `h05` | 1s GET p32, overlap=1, reorder=0 | pending | pending | pending |
| `h07` | 1s GET p32, overlap=1, reorder=1 | pending | pending | pending |

Run PRE/POST/POST/PRE and PRE/PAD/PAD/PRE blocks, plus PAD/POST/POST/PAD for
attribution. Report rate and paired relative change, cycles/op, instructions/op,
and IPC for every arm/cell; cycles/op = instructions/op / IPC. Keep the offered
load and generator rung matched. Record command lines, instrument/generator digests,
CPU mappings, repetitions, and identical-arm spread in `MEASURE-RESULT`.

**Decision:** the 1 KiB fused SET and MSET rates must improve, with zero regression
on the 256-byte cells, 2s control, and `h01,h02,h05,h07` under the gate's existing
acceptance rules. POST must move relative to PAD as well as PRE to attribute a gain
to prebuilding. If 256 bytes loses, bisect the compile-time boundary; if no boundary
holds the controls, delete the candidate. Do not infer a win from instructions alone
or waive an identical-arm spread over 2% as noise. No performance claim is made here.

## Correctness and scope of evidence

The maintainer runs the full iteration gate in both modes, including armed read-local
legs. Reproduce correctness rows at **16 shards / GATE_RATIO / GATE_CORES**, not the
32-owner measurement geometry. The lane's serverless fixtures use 16 shards on eight
CPUs, with 6 IO + 2 EX in split mode.

No gate row or EXPECT constant is edited. New checks are a standalone unit target.
Row delta is **0 quick / 0 full**: `EXPECT_QUICK=419`, `EXPECT_FULL=436` remain unchanged;
`tests/gate.sh:2743` begins the quick exit (return at line 2747).

Validation receipts and artifact manifest are appended below after the final build.
The byte audit distinguishes unchanged handlers from required dispatch/cleanup edits
and any compiler drift; byte differences are not treated as a proof of zero regression.

## Final receipts

Product source commit: `e028a8204`; GCC 13.3.0, jemalloc, release flags
`-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, with the baseline's
unchanged per-TU GCC budgets. A forced final release build used CPUs 112–119;
TSAN compilation used 120–127. Unit execution stayed within 112–127.
The server binaries were **never executed**.

| Arm | `.text` bytes | SHA256 |
| --- | ---: | --- |
| PRE | 3,535,747 | `813ef9e7597f211aea4351f34370db9d70709f1336b1e095112685a36f3bc78a` |
| POST | 3,559,459 | `995f231027d7dc7fdcab0422983f3a262682eca1dd382295b1f283c6678e3382` |
| PAD-A | 3,559,459 | `b9324dd228226b8a54c18c017b8f220406acb69a843d1905b627bfc8144eafa5` |

POST grows `.text` by 23,712 bytes. PAD-A changes only three bytes starting at
file offset 3,573,892. Every other byte, every section size, and every symbol
address matches POST. `build/l4prebuild-proof/artifacts.json` and `pad.json`
record the complete manifest. The same patch on the unit binary exits **1** with
`FAIL owner arena: exact per-key prebuild policy`; the positive unit requires the
foreign 193-byte candidate to exist independently of the policy function's answer.
See `pad-negative.log` and `unit-pad.json`.

All eight compile-time size locks hold: Op 336, Client 1984, ThreadCtx 1408,
Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624.

| Check | Result |
| --- | --- |
| `make unit` | All six standalone unit programs pass |
| `l4prebuild-unit` | 4/4: 1s/2s × read-local 0/1 |
| Fully instrumented `l4prebuild-unit-tsan` | 4/4, no TSAN reports; run with `setarch x86_64 -R` |
| Existing `owner-arena-unit` | 4/4: both modes and read-local states |
| Atomic survivors | admission, write_latest, mset_arity, rename_overlay, watch_parent all pass |
| Kind-A unit negative control | Fails on missing IO candidate, as required |

The new unit checks mixed local/foreign keys and size boundaries, header **and**
payload arenas, exact pointer adoption, duplicate-key last-write semantics, MSETNX
existence, IO header/payload OOM with a free ledger, all SET option forms against
the original handler (including notification arming and physical TTL reservation),
atomic=0/1, live QSBR retirement, and quiesced shard/range handoff. The actual parser
fills the owner inbox to force refusal, verifies the IO allocation is freed, and
retries the same frame. It also drives the real executor's pre-handler maxmemory
denial and verifies reclamation before Done. A separate 512-operation SPSC test
runs the IO producer and executing owner concurrently, checking complete payload
publication, exact object adoption, and release/acquire reply retirement under TSAN.
Parser and concurrent-handoff cases use the unarmed fixture; armed cases exercise
the real store/retirement mechanisms. All work is bounded and serverless.

Logs: `build/l4prebuild-proof/{final-build,prebuild-unit-build,tsan-build}.log`,
`unit-{1s,2s}-{0,1}.log`, `tsan-{1s,2s}-{0,1}.log`, `owner-{1s,2s}-{0,1}.log`,
and `atomic-*.log`.

## Byte-identity limitation — not a full pass

The isolated feature TU restores **all 314 original string-object function bodies**
(143 clean, 171 notification) byte-for-byte, including resolved relocation targets.
The ordinary `main.o` audit is **128/128** identical. The broader selected hot-body
audit is **443/463 raw-identical, 446/463 with address displacements resolved**.

| Object | Audited | Bytes + resolved targets identical |
| --- | ---: | ---: |
| `main.o` | 128 | 128 |
| `t_string.o` | 11 | 11 |
| `t_string_notify.o` | 13 | 13 |
| `genthread.o` | 113 | 106 |
| `rl2s.o` | 187 | 179 |
| `xshard.o` | 11 | 9 |

Eight differing bodies contain required fused parser eligibility/refusal hooks or
fused executor rejection cleanup. **Nine collateral bodies still differ**: one
TLS parser clone and two producer-drain lambdas in `genthread.o`; three WB serve
lambdas and one TLS CQE handler in `rl2s.o`; and notify find/erase helpers in
`xshard.o`. Exact mangled names, PRE/POST sizes, byte checks, and relocation checks
are in `build/l4prebuild-proof/bytes.json` (readable listing in `bytes.log`).

Thus the literal whole-inactive-path byte-identity requirement remains **unmet**;
this is not waived by passing correctness units or by the exact-layout PAD. The
original SET/GET handlers and ordinary split hot bodies are preserved, but the
broader code-generation exceptions must be resolved or explicitly judged by the
maintainer before accepting this candidate. Rate measurements remain outstanding.
