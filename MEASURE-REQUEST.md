# cx-l4prebuild — round 3, finalize the 512 B default

Worktree `/home/user/Projects/cx-l4prebuild`, branch `cx-l4prebuild`.
Reference **v6 = d90843b96**. The maintainer selected **strictly >512 B**;
`make` and the gate's ordinary build now produce that policy in **build/tomokv**.
The default policy is defined once in `src/cmd/l4prebuild.cc`, beside the
measurement table. Make reads that boundary into the unit's separate placement
comparison; the unit never calls the production policy to decide its expected
result. Named boundary variants and the round-2 aggregate target are retired;
a subsequent bisect changes only the constant in that source and rebuilds.

## Supplied box results and decision

PRE -> POST rate changes, 8 pinned generator instances, floor +/-1.6–2%.
Round-2 arms were delivered in `3d155061c`, against v6; the 192 B historical
arm `8ba4b3d5a` used v5/v6 references. These are maintainer measurements,
not new measurements by this lane.

| Cell | >192 B, historical rounds | >512 B vs v6 | >768 B vs v6 |
| --- | ---: | ---: | ---: |
| `l4_set_1s_1024` | +3.6 to +5.1% | **+5.9%** | +4.4% |
| `l4_set_1s_256` | −9.0 to −9.5% | +0.6% | −0.9% |
| `l4_set_2s_1024` | −0.5 to +0.9% | −0.6% | +0.2% |
| `l4_mset_1s_1024` | +3.0 to +3.5% | **+2.7%** | +5.3% |
| `l4_mset_1s_256` | −13.6 to −17.7% | −1.9% | −0.9% |
| `l4_msetnx_1s_1024` | +1.6 / −1.8% | **−3.0%, pooling pending** | +0.8% |

512 B preserves the owner-born placement benefit at 256 B and the target
1 KiB gain. It also admits 513–768 B values; no performance gain for that
middle range has been measured here. MSETNX still checks existence and
materializes on the owner. Its −3.0% result is unresolved: no pooled verdict
has been appended to the brief or supplied as `MEASURE-RESULT`.

The brief's **16:03 mainline update** supplied the 768 B MSET results and a
new decision rule: keep **512 B unless the pooled 512 B MSETNX read stays
at or below −3%; then switch to 768 B**. No pooled result is supplied yet.
This delivery therefore keeps 512 B. A one-line edit of the source constant
rebuilds both production and unit expectations for either selection.

The round-2 binaries differ in only one `.text` byte, the boundary immediate;
their 256/1024 B policy decisions and MSETNX code are identical. Consequently
a different MSETNX rate between those arms cannot establish a size-policy
effect. Preserve pooled paired controls and the byte-audit limitations below.
This finalization changes no compiler budgets or dispatch/execute codegen.

## Delivered arms and reproduction

| Arm | Binary | Policy |
| --- | --- | --- |
| PRE-v6 | `build/tomokv-l4prebuild-pre-v6` | Untouched `d90843b96`, retained from the local round-2 archive |
| POST | `build/tomokv` | Default build: foreign fused SET/MSET values **>512 B** prebuilt on IO |
| PAD-A | `build/tomokv-pad` | **Kind (A) behaviour twin:** PRE allocation behaviour with POST's text size and layout |

PAD is copied from POST. Only the `noipa` `l4prebuild_policy(uint32_t)` entry
is patched to return false, preserving CET. This disables SET and MSET
prebuild and MSET's forced same-shard scatter. All other bytes, section sizes
and symbol addresses must match POST. The candidate's eligibility checks
remain in PAD: PRE/PAD measures their cost plus code placement; PAD/POST
isolates the allocation policy. No kind-B arm is requested.

```sh
# Builds only; these targets never execute a server.
taskset -c 112-119 make -j4 all build/tomokv-pad build/l4prebuild-unit
taskset -c 120-127 make -j4 build/l4prebuild-unit-tsan
# Serverless tests; inherit the caller's reserved CPU affinity.
taskset -c 112-119 make unit l4prebuild-unit owner-arena-unit
taskset -c 120-127 make l4prebuild-unit-tsan
```

An edit to `TOMO_L4_PREBUILD_THRESHOLD` in `src/cmd/l4prebuild.cc` rebuilds
only its isolated production object before relinking POST and recreating PAD.
192/768 remain possible via this constant; no boundary target or runtime knob
is retained. Make extracts the selected value into
`TOMO_L4_PREBUILD_TEST_BOUNDARY`, so the native and TSAN fixtures rebuild
their separate comparison oracle from the same source definition.
`src/cmd/t_string.cc` is a prerequisite for both native and TSAN policy objects.

## Behaviour and correctness

At or below 512 B, SET retains the original owner handler and MSET retains
owner materialization/localfast. Above 512 B only foreign keys in fused mode
prebuild header and external payload on IO. Local keys, split mode, MULTI
children and **all MSETNX** remain owner-materialized; mixed MSETs decide
per key. Eligibility is based on the owner at dispatch, with no stored owner
arena pointer or new structure to migrate.

Installation, admission, SET options, relative expiry and visibility
publication remain on the owner. Immutable replacement, QSBR, single-owner
writes, RYOW and receive-buffer lifetimes retain their existing contracts.
Refused posts, owner denial, allocation failure, abort and notification paths
retain the tested cleanup. No runtime option or layout field is added.

The serverless fixture uses 16 shards/eight reserved CPUs (6 IO + 2 EX in
split mode), covering both modes with read-local off/armed. It checks the
256/512/513/768/769/1024 B boundaries, original SET handlers/MSET localfast,
header and payload arenas, mixed sizes, duplicate keys, MSETNX existence
checks, OOM, SET options/TTL/notifications, atomic=0/1, parser refusal/owner
admission, QSBR, quiesced migration and concurrent SPSC handoff. PAD-disabled
and inclusive-boundary mutant unit binaries must fail the positive placement
witness. No listener or io_uring instance is started by these units.

Gate row delta is **0 quick / 0 full**. `tests/gate.sh` and its EXPECT values
are unchanged. The maintainer runs `tests/gate.sh iteration` and boots both
modes at **16 shards / GATE_RATIO / GATE_CORES**. This lane runs no server,
benchmark, load generator, loopback diagnostic or gate.

## Measurement request

Use the current v6-compatible gate instrument and OP:BYTES grammar from
`/home/user/Projects/calib/set-cells.txt` and
`/home/user/Projects/calib/l4-cells.txt`. Pin all six L4 cells to **8 generator
instances**, keeping server/generator CPU maps identical across PRE, POST and
PAD. Preserve the scheduled 32-owner geometry, p8, 512 connections, atomic=1,
rl=ov=ro=0, balancers, key distribution, warmup, duration and denominator.
Use the current pinned rate-cell rungs for h01/h02/h05/h07.

| Cell | Settings | Final POST/PAD verification |
| --- | --- | --- |
| `l4_set_1s_256` | 1s SET:256, p8 | pending |
| `l4_set_1s_1024` | 1s SET:1024, p8 | pending |
| `l4_set_2s_1024` | 2s SET:1024, p8 | pending |
| `l4_mset_1s_256` | 1s MSET:256, p8 | pending |
| `l4_mset_1s_1024` | 1s MSET:1024, p8 | pending |
| `l4_msetnx_1s_1024` | 1s MSETNX:1024, p8 | **pool the flagged control** |
| `h01` | 1s GET p32, ov=0, ro=0 | pending |
| `h02` | 1s SET p32, ov=0, ro=0 | pending |
| `h05` | 1s GET p32, ov=1, ro=0 | pending |
| `h07` | 1s GET p32, ov=1, ro=1 | pending |

On v6, reorder=1 is an intentional no-op; use the current harness that accepts
it, not the obsolete INFO witness. For each cell run PRE/POST/POST/PRE,
PRE/PAD/PAD/PRE and PAD/POST/POST/PAD; pool at least two blocks on the pinned
L4 rung, retaining paired changes and same-binary controls. Record exact
commands, binary/instrument hashes, CPU maps, offered load, repetitions and
spreads in `MEASURE-RESULT`.

**Verdict:** rate at matched offered load decides; report cycles/op,
instructions/op and IPC together (cycles/op = instructions/op / IPC).
Keep the 1 KiB fused SET/MSET gains, with zero regression on the 256 B cells,
2s SET, MSETNX and h01/h02/h05/h07 under the gate's acceptance rules. POST
must improve relative to PAD as well as PRE to attribute the gain to prebuild.
The floor is not a regression waiver; spreads >2% need investigation.

## Build, validation and byte receipts

Product/default-test source commit: **73b1204ce**. GCC 13.3.0, jemalloc,
release `-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, with
v6's existing per-TU compiler budgets unchanged. Builds and tests completed
on CPUs 112–119 (release/native) and 120–127 (fully instrumented TSAN).
All receipts and logs are in `build/l4prebuild-round3/`.

| Arm | `.text` bytes | SHA256 |
| --- | ---: | --- |
| PRE-v6 | 3,532,099 | `4f8ff56d96d39a60c614d21ec0fbd28f03bf8dd1f1ff07d4757d0ad60d2c7276` |
| POST, default 512 B | 3,556,371 | `56c07a1b9a553fd39d92c8b8579021577660a07fb1635372b7ad0a5eb43237fa` |
| PAD-A | 3,556,371 | `bd3e72a7f828995c1b522f1e87540a334015bcda4ac03ea3f324e9fb28fa32d5` |

**The final default is the measured round-2 POST-512 in executable code and
data:** all 4,467 function symbols have identical addresses/sizes, and every
allocated section has identical bytes/addresses/sizes except the GNU build ID.
The original POST-512 hash is
`8aed5e9a9e1b51d4a0b81d2954ef53dda155509de1a3751519fe8ee765b0e484`;
`default-vs-measured-512.json` records the comparison. Debug metadata and the
build ID changed after source comments/default build paths were updated.

PAD differs from the default POST in exactly three bytes at file offset
3,570,804, immediately after the policy's CET entry. Every other byte, every
section entry and every symbol entry is identical. The policy body is
`f30f1efa81ff000200000f97c0c3` (strictly >512 B). Receipt:
`build/tomokv-pad.json`. Both POST and PAD have 24,272 more `.text` bytes than
v6; finalization adds no text or layout change to the measured 512 B arm.

| Validation | Result |
| --- | --- |
| Default policy unit, 1s/2s × read-local 0/1 | **4/4 pass** |
| Fully instrumented TSAN default policy unit, same matrix | **4/4 pass**, no TSAN diagnostics |
| `make unit` | All five standalone programs pass |
| Existing owner-arena unit, same matrix | **4/4 pass** |
| Atomic survivors | admission, write_latest, mset_arity, rename_overlay, watch_parent pass |
| PAD-disabled unit negative control | Exit **1** at the required positive placement witness |
| Inclusive-boundary unit negative control (>511 instead of >512) | Exit **1** at the exact per-key policy assertion |

The two deliberately broken controls are copies of the **unit binary only**,
under `build/l4prebuild-round3/`; each reports
`FAIL owner arena: exact per-key prebuild policy`. No check was skipped and no
tolerance was widened. `native-results.json` and `tsan-results.json` record
commands, CPU affinity, expected/actual exits and logs; the TSAN receipt also
records the instrumented unit digest. TSAN runs use
`TSAN_OPTIONS=halt_on_error=1:exitcode=66` and `setarch x86_64 -R`.
GCC emits its existing `atomic_thread_fence` TSAN modelling warnings during
compilation; the four runs contain no TSAN reports.

All eight compiled size locks hold: Op 336, Client 1984, ThreadCtx 1408,
Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624.
`EXPECT_QUICK=419`, `EXPECT_FULL=435` remain unchanged; the quick-tier exit
starts at `tests/gate.sh:2758` and exits at line 2762. No gate rows were added
or retired. `artifacts.json` records binaries, compiler, layouts and log hashes;
build logs are `release-build.log` and `tsan-build.log`.

## Byte-identity limit against v6

The fresh object audit is exactly the round-2 result: **314/314 original
string-family bodies match byte-for-byte**, including resolved relocation
targets and `xshard_make_atomic_string`. The broader selected hot-body audit
is **561/576 raw-identical, 564/576 with address displacements resolved**:

| Object group | Audited | Bytes + resolved targets identical |
| --- | ---: | ---: |
| `main.o` | 128 | 128 |
| `t_string.o` + `t_string_notify.o`, selected hot bodies | 24 | 24 |
| `genthread.o` | 113 | 108 |
| `rl2s.o` | 187 | 182 |
| `xshard.o` | 11 | 9 |
| Other selected command/persistence/snapshot bodies | 113 | 113 |

Eight differences are required fused parser hooks and executor rejection
cleanup. Four collateral differences remain from round 2:

- `genthread.o`: split TLS `parse_and_dispatch<true, 0u, ...>` clone.
- `rl2s.o`: `IoLoop::run_loop<true, false, false, true, (unsigned char)1, true>`.
- `xshard.o`: `FlatStore::find_notify` and `FlatStore::erase_notify`.

The selected-body audit does not cover the full shared scatter bodies:
`xshard_prepare` changed from 17,002 to 18,137 bytes and `xshard_execute` from
22,576 to 22,694 bytes for the MSET policy. MSETNX uses this shared machinery,
so unchanged allocation semantics do **not** establish whole-path byte
identity or clear its flagged performance result. The literal whole-inactive-
path byte-identity requirement against v6 is **not fully satisfied**. The final
default adds no further codegen drift to the measured arm, but this limitation
and the pending MSETNX pooling must remain visible to mainline.

Receipts: `bytes.json`, `bytes.log`, `string-bytes.json`. Reproduce the selected
audit below; exit **1** intentionally reports the documented differences:

```sh
taskset -c 112-119 python3 tools/lbstall_artifacts.py compare build/l4prebuild-round2/pre-v6/build/src build/src build/l4prebuild-round3/bytes.json
```
