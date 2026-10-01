cleanup-flipsettle — 2026-09-30

The shared settling learning reset now has one private implementation. The controller transitions and their site-specific store order are preserved. **The candidate is NOT byte-identical to PRE and is not ready to land without the mainline PAD-controlled null.** Builds and serverless proofs passed. All live batteries, gate results and performance results below are **PENDING MAINLINE**. No server, load generator, benchmark, gate, performance measurement or push was run by this lane.

Worktree: `/home/user/Projects/cx-cleanup-flipsettle`, branch `cx-cleanup-flipsettle`. Launch HEAD and `origin/cpp` both resolved to **37eeb5e90be9997805cfe2456021ad07dc0c18f9**. PRE was built and copied before the first source edit. Production change: `f01fac2bc`; subsequent commits add tests, proof tooling and this report. Everything built or executed by the lane was pinned to **112–127**, with `make -j16` for Makefile builds. The 461-row / zero-gating-FAIL reference result is the owner's launch evidence, not a gate result obtained here.

**Diagnosis and scope.** Rechecked against the frozen reference, the three repeated sequences are `src/core/flipctl.cc:672–679`, `:1229–1236`, and `:1261–1268`. The latter two moved three lines from the supplied audit. `enter_settling()` changes phase first and clears the rate window afterward (`:670–682`). WaitingFlip assigns `after_flip_` before the conditional learning reset and clears the window for every successful destination (`:1227–1240`). Disarm releases sampling rate zero before the learning reset, then sets its latch and clears the window (`:1255–1272`). Calling `enter_settling()` unconditionally at completion would incorrectly turn Seeking into Settling.

POST's implementation is `src/core/flipctl.cc:669`, declared private at `src/core/flipctl.h:353`. Its only call sites are `flipctl.cc:684`, `:1234`, and `:1259`. Phase assignment, the release disarm store, the disarm latch, rate-window resets, locking and return boundaries remain at their original sites and in their original order. The helper uses ordinary `inline` source structure; there are no new compiler budget settings or forced-inline attributes. The related but differently ordered `start_maneuver()` reset is outside this cleanup.

This is **live duplicated behavior**, not dead code, a constant-return defect, or an unwired contract. Fingerprint collection produces both sample counts at `flipctl.cc:321–329`; Settling consumes its anchor count at `:1277`. Settling produces the rate accumulators at `:1267–1276`, and `anchor()` consumes them at `:1097–1104`. The signal rate reaches owners through `server.h:504–506`. Tick callers include `main.cc:609` and `core/rl2s.cc:325`, through `server.h:503`. Their translation units, command/report callers and all other production objects were audited in both namespaces. The false returns at these edges mean no new flip was issued; their state mutations are exercised by the tests.

History independently supports the contract: `99369aa750` introduced the completion/disarm resets; `b5258d6204` introduced `enter_settling()`; `601d65d4ae` connects the seek/refusal paths. Raw blame and commit records are under `build/cleanup-flipsettle/frozen/`. No additional correctness-law conflict was found in the touched paths. This is not an audit of all existing database paths. No ownership, migration, read-local, QSBR, atomicity, RYOW, reply-ordering, sampling-policy or configuration mechanism was changed.

**Exact reset table.** `L` below is the eight-item shared sequence: detector reset, both signature counts, and all five `anchor_learning_rate_*` fields. The test seeds counts to 11 and 13; jitter/sum/min/max/sample-count to 0.125 / 17001 / 17002 / 17003 / 19; an anchored detector with nonzero learning noise and distance; signal rate 23; rate-window timestamp 29; and a valid previous subwindow.

| Actual controller edge | PRE ordered effects | POST ordered effects | Preserved boundary |
|---|---|---|---|
| Seeking reading → `settle()` → `enter_settling()` | Phase=Settling; L; timestamp=0; previous-valid=false | Phase=Settling; helper(L); timestamp=0; previous-valid=false | Signal stays 23; disabled latch stays false; the real seek records its reading and clears `seek_` |
| Successful WaitingFlip → Settling | Phase=`after_flip_`; conditional L; timestamp=0; previous-valid=false | Phase=`after_flip_`; conditional helper(L); timestamp=0; previous-valid=false | Signal stays 23; disabled latch stays false |
| Successful WaitingFlip → **Seeking** | Phase=Seeking; **no L**; timestamp=0; previous-valid=false | Identical; helper is not called | All eight learning items retain their seeded state; signal stays 23; disabled latch stays false |
| Settling, sampling still armed → disarm | Release-store signal=0; L; disabled=true; timestamp=0; previous-valid=false | Release-store signal=0; helper(L); disabled=true; timestamp=0; previous-valid=false | Phase remains Settling |

Each fixture is fresh. Seeking uses the real `seek_after_reading()`/argmax/settle path. Completion supplies the actuator's completed counter and target role count to the real `tick()`; it does not run an ownership transaction. Disarm also uses the real tick and mutex. The detector's public state and subsequent deterministic observations are compared exactly, without a tolerance. A byte mask checks preservation of every other controller member; only documented transition effects are excluded, and those are checked separately. Existing live FLIP batteries remain necessary for actuator behavior.

**Build and identity evidence.** All paths in the following tables are relative to this worktree. Arm directories contain `tomokv`, all 42 normal objects, all 42 db0 objects, `inventory.json`, `SHA256SUMS`, and `proof/` with raw `objdump -drwC`, `readelf -hSWl`, symbol listings, executable-section dumps and relocation-section dumps. Relocation records also retain target name, section, value, size, type and addend. No instruction normalization is used for the byte verdict.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE, exact launch source | `build/cleanup-flipsettle/PRE/tomokv` | `4ccaf6cbab4e3d685c47f94140249c7725ed3444d7bbb34999d1f8e331bb9d92` |
| POST, this production change | `build/cleanup-flipsettle/POST/tomokv` | `0e609387b66e21e69e636ad99be0e31d95457c14b6a47ea2e4edc204aa17b7e9` |
| PAD **(A), behavior twin** | `build/cleanup-flipsettle/PAD-A/tomokv` | `1890fcad89944ccc46cb29c205cda77f0b921a64aa0847b52c74f529af82358f` |

| Size in bytes | PRE | POST | PAD-A |
|---|---:|---:|---:|
| Linked `.text` | 7,576,545 | 7,576,513 | 7,576,513 |
| All linked executable sections | 7,586,377 | 7,586,345 | 7,586,345 |
| Normal `flipctl.o` `.text` | 34,617 | 34,601 | 34,601 |
| db0 `flipctl.o` `.text` | 34,617 | 34,601 | 34,601 |

The audit covers **8,530 executable object sections**. Executable bytes and relocation targets match for 82/84 objects; only the two controller objects change executable bytes. Each controller has 20 executable sections: its `.text` changes, while its executable `.text.*` sections retain their bytes. All 84 objects and the final linked executable were compared, not just selected functions.

The stronger combined byte/relocation/symbol audit reports **72/85 identical files**, explicitly FAIL overall (`identity-first.json`). Besides the two controller objects and linked ELF, ten caller objects change only local, zero-size assembly marker names generated with GCC `%=`; their executable bytes, target relocations and function addresses remain unchanged. Those markers include existing `tomo_multidb2_pad_*` labels; they are not this cleanup's PAD. Their raw name differences remain in the report instead of being normalized into identity.

In both namespaces `settle()` changes 267→251 bytes: GCC reschedules the initial vector-pointer loads/comparison, selects a short branch and changes loop padding. `tick()` also reverses one `cmp`'s operands before a `jne` (one ModRM byte, `c6`→`f0`, per namespace); it retains the equality decision but **does not retain its bytes**. Subsequent linked code addresses and relocation displacements move. Ordinary alternate helper placements were checked under `build/cleanup-flipsettle/helper-*`; they did not recover identity. The retained production structure is the small `.cc` helper, with unchanged compiler flags.

| Linked `settle()` | PRE address / size | POST address / size | PAD-A address / size |
|---|---|---|---|
| `tomo_db0` | `0x2e4030` / 267 | `0x2e4030` / 251 | `0x2e4030` / 251 |
| `tomo` | `0x670fc0` / 267 | `0x670fb0` / 251 | `0x670fb0` / 251 |

PAD-A is independently built from the archived **PRE source and PRE compile commands**, not from an R7 PAD or a copy relabelled from POST. Unmodified PRE assembly first round-trips with identical executable sections, target relocations and executable symbols in both controller objects. Then exactly the first `.p2align 4` / `.p2align 3` pair inside each generated `settle()` is removed. The assembler re-encodes branches and relocations; all PRE instructions, reset stores and conditions remain. No alternative reset is handwritten. All other objects come from PRE. This shrinks each body to POST's size, rather than appending a NOP footer.

`PAD-A/layout.json` verifies **all 8,799 linked function addresses and sizes**, plus every executable section's address, offset, size and alignment, match POST. The complete executable difference between PAD and POST is **132 bytes**: 65 inside each `settle()` body and one comparison byte inside each `tick()`. PAD retains PRE's instruction ordering inside the changed bodies; this is not a claim of matching every internal instruction address. The original and modified assembly are retained in `PAD-source/`. PRE/PAD and PAD/POST raw comparison reports are `identity-PRE-PAD.json` and `identity-PAD-POST.json`; both correctly fail strict identity. No kind-B control is required for a total `.text` change of only 32 bytes.

Compiler: GCC **13.3.0-6ubuntu2~24.04.1**, default release flags `-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, jemalloc enabled, with the existing per-TU flags unmodified. PRE and POST used the same absolute workspace and relative source/output paths. `frozen/reproducibility.json` confirms the same 84 compile commands and one link command. `frozen/inputs.json` and `reference.tar` were saved before editing; only the two controller files and Makefile's two test-dependency lists differ among frozen production inputs. `resolved-dependencies.json` records 722 resolved files; external dependency timestamps predate the PRE freeze. Compiler, assembler, linker and library hashes, versions, environment, build logs and raw bytes are retained. The resolved system-dependency hashes were inventoried after building, with their timestamp check recorded explicitly.

Both final builds passed without warnings. `POST/final-build.log` includes the complete production rebuild and existing model/unit targets; the final `build/tomokv` compares byte-for-byte with saved POST. All existing footprint and offset assertions compiled in both namespaces: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624.

**Assertions and controls.** `tests/flipsettle_checks.inc` extends the existing `core concurrency route` case. PRE, POST and PAD-A each pass all four transitions in normal namespace databases=1 and databases=4, and db0 databases=1: **36 transition traces**, identical across arms. `controls/positive-results.json` binds the six test executables and trace equality. The common assertions cover all unrelated controller storage as well as the reset and transition state.

Each entry below names the exact field in `FAIL flipsettle <site>: <assertion>`. `seek`, `waiting`, `nonsettling`, and `disarm` are actual fixture selectors. Every listed negative witness returned exactly 1 with its intended diagnostic, rather than merely crashing. `controls/results.json` gives every command, expected diagnostic and result; individual logs and generated mutant sources/binaries remain beside it.

| Assertion | Expected at seek / waiting / disarm | Expected at nonsettling | Throwaway control and observed result |
|---|---|---|---|
| `shift_detector_` | Exact reset state and subsequent detector behavior | Seeded detector preserved | `omit-shift_detector_` fails each reset site; `widen-shift_detector_` fails nonsettling |
| `anchor_signature_samples_` | 0 | 11 | Omit reset: 3 exact failures; inject reset at nonsettling: exact failure |
| `maneuver_signature_samples_` | 0 | 13 | Same four field-specific failures |
| `anchor_learning_rate_jitter_` | 0 | 0.125 | Same four field-specific failures |
| `anchor_learning_rate_sum_` | 0 | 17001 | Same four field-specific failures |
| `anchor_learning_rate_min_` | 0 | 17002 | Same four field-specific failures |
| `anchor_learning_rate_max_` | 0 | 17003 | Same four field-specific failures |
| `anchor_learning_rate_samples_` | 0 | 19 | Same four field-specific failures |
| `phase` | Settling, no new flip issued | Seeking, no new flip issued | Omit enter phase; omit waiting phase; corrupt disarm phase; replace completion with unconditional `enter_settling()`: all 4 fail phase |
| `rate_window_ms_` | 0 | 0 | Omit timestamp resets: all 4 sites fail |
| `previous_subwindow_valid_` | false | false | Omit invalidation: all 4 sites fail |
| `sampling-disarmed` | 23 / 23 / **0** | 23 | Remove disarm release store: disarm fails; add store at other edges: other 3 fail |
| `anchor_sampling_disabled_` | false / false / true | false | Remove disarm latch or add it at another edge: all 4 fail |
| `seek-record` | Seek cleared, original reading retained, exact new `(6,16384)` reading | Not applicable | Remove the real seek's `record()` call: seek fails |
| `unrelated-state` | All other controller bytes preserved | All other controller bytes preserved | Add `anchor_rate_=0` at each applicable edge: all 4 fail |
| `detector-seed` | Learning, noise and anchored distance must have been exercised | Same requirement | Remove all three seed observations: all 4 fail before testing a reset; no skipped/unentered window |

Result: **61/61 exact negative witnesses across 32 throwaway builds**, including 24 reset omissions (8 items × 3 reset sites), 8 nonsettling preservation controls, and all phase/window/sampling/preservation/arming controls. Logs: `controls-final.log`, `controls/results.json`, `controls/build.log`. The fixture arming is deterministic on fresh state, with no sleeps or widened tolerance. Existing live stable-hold bounded re-arming remains unchanged.

The exact ELF checker also rejects `byte-control/one-executable-byte-changed.DO-NOT-RUN`, copied from PRE with one `.text` byte XORed. Both executable-section metadata/hash and the actual byte comparison detect it. Receipt: `byte-control/negative-control.json`. The corrupted artifact is nonexecutable and **was never run**.

The existing `flipctl-unit` passed against PRE and POST, including its 12/12 rate rows and existing detector/model checks. The extended existing serverless `route` case passed (`POST/route-final.log`). Gate ASAN/TSAN builds, `flipctl.py` stable-hold/shift campaign, FLIP under load, shutdown invariants, both live thread modes and database configurations are **PENDING MAINLINE**. All newly added assertions are serverless; the live batteries are unchanged.

Safe replay commands, from this worktree:

```sh
taskset -c 112-127 make -j16 all build/flipctl-unit build/signalacct-core-unit
taskset -c 112-127 build/flipctl-unit
taskset -c 112-127 build/signalacct-core-unit route
taskset -c 112-127 python3 tools/flipsettle_controls.py
taskset -c 112-127 python3 tools/flipsettle_artifacts.py negative-control build/cleanup-flipsettle/PRE/tomokv build/cleanup-flipsettle/byte-control
# Expected exit 1: this candidate is not byte-identical.
taskset -c 112-127 python3 tools/flipsettle_artifacts.py compare build/cleanup-flipsettle/PRE build/cleanup-flipsettle/POST build/cleanup-flipsettle/identity-first.json
```

PAD reconstruction, also offline, is `taskset -c 112-127 python3 tools/flipsettle_artifacts.py pad build/cleanup-flipsettle/PRE build/cleanup-flipsettle/POST build/cleanup-flipsettle/frozen/reference.tar build/cleanup-flipsettle/PAD-A`. Snapshot each arm with the tool's `snapshot ARM_DIRECTORY` subcommand to regenerate raw dumps.

**Gate row arithmetic.** No gate script was changed or added, and the gate still uses its existing grep commands. New checks run inside the existing route emission at `tests/gate.sh:1254`, above the actual quick exit at **:2858** (not the older :2808 anchor). Model unit emission is :1209; live controller emission is :870; saturated FLIP is :1958; shutdown is :1970, also before the quick exit. Delta: quick **+0**, full **+0**. Constants remain **EXPECT_QUICK=441**, **EXPECT_FULL=461**. Unit assertions and mutation invocations are not new gate rows. An owner-run source gate command is `bash tests/gate.sh iteration --reference-binary "$PWD/build/cleanup-flipsettle/PRE/tomokv"`; its ordinary performance geometry does not replace the specific null contract below.

**Frozen mainline measurement contract.** Compare exactly PRE/POST, PRE/PAD-A, and PAD-A/POST. Keep both mode and database arms explicit. No performance win is required; every cell must meet stable-reference parity. Landing remains conditional on the mainline result.

The exact launch `tests/headline_cells.txt` is copied to `frozen/tests/headline_cells.txt`, SHA-256 **d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350**. Launch load metadata is `frozen/tests/gate_measurements.json`, SHA-256 **e54dd9ba11efc5a989c62191c5875af8fcf19e04ac1d2bc0d417b53432634587**. `frozen/h01-h64-plans.json` retains each exact source line and digest, 64-byte payload, and its launch load plan (or the explicit absence of one). The base guard set is **h01 through h64 inclusive**, 512 total connections, GET/SET × p1/p32 × both modes × read-local/overlap/reorder combinations. No existing cell was edited. The launch notes' **14 generic null-cell IDs were not specified** in the inventory; their exact mainline selection is **PENDING MAINLINE**, not silently invented or substituted for the full named guard inventory.

Use `--shards 16`; reviewed 8 physical server cores, **6 IO + 2 EX for 2s**, eight fused workers for 1s; read-local 0/1; databases 1/4. Keep the frozen workload's 512 connections and 64-byte payload and establish the productive-role plateau with sufficient independent load workers at **both p1 and p32**. Do not interpret a single-connection run as saturation, or reuse a load pin from a different geometry. Measure at matched offered loads and retain rate, cycles/op, instructions/op, IPC, p99 and p99.9 (and any existing cell-specific tail metric), with `cycles/op = instructions/op / IPC`.

Additional feature profiles use the exact pure-command shapes of 2s cells **h17,h18,h25,h26,h49,h50,h57,h58** (GET/SET, p32/p1, read-local 0/1, overlap=0, reorder=0, atomic=1), separately for databases **1 and 4**. Give each profile its own identifier such as `seek-h17-db4`; do not overwrite an h cell. Cover these regimes separately:

| Regime | Explicit controller posture / witness | PRE metrics | POST metrics | PAD-A metrics |
|---|---|---|---|---|
| Neutral: disabled | `--flip-auto 0`; no controller work | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Neutral: stable and sampling disarmed | `--flip-auto 1`, reached Anchored and sampling=0; stable hold completes without extra work/oscillation | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Exercised path / potential benefit: seek→settle | Actual seek reaches the settling edge in the scored workload | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Exercised path / potential benefit: successful WaitingFlip→settle | Completion counter and destination prove the edge occurred | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Possible deficit: repeated shifts/disarm/retrigger | Fresh shifted/forced campaigns repeatedly exercise disarm and retrigger; trace progress required | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |

Each metrics entry means the full cycles/instructions/IPC/rate/tail tuple above, not just throughput. For 1s use the corresponding **h01,h02,h09,h10,h33,h34,h41,h42** shapes in databases 1/4: the controller is unavailable/disabled by design, so the required regime is neutral; a claimed fused seek event would be a test error. Preserve the supplied stable-hold/shift and FLIP load/shutdown batteries. Require actual window/transition witnesses; for a live unentered window re-arm on fresh state within the battery's bounded budget and then FAIL, never SKIP. Fixed-input controller traces are already identical serverlessly; live stationary-controller and repeated-shift observations remain pending.

For every independently validated cell, before collecting POST, freeze `epsilon_cyc[cell]`, `epsilon_rate[cell]`, `epsilon_tail[cell]`, stable-reference binary SHA, instrument digest, payload, worker/pin/load plan, geometry and window. Require:

```text
abs(100 * (B_cycles_per_op / A_cycles_per_op - 1)) <= epsilon_cyc[cell]
100 * (1 - B_rate / A_rate)                      <= epsilon_rate[cell]
100 * (B_tail / A_tail - 1)                      <= epsilon_tail[cell]
```

Apply all three tests separately to PRE/POST, PRE/PAD-A and PAD-A/POST and each relevant tail. No averaging across cells or widening a band after observing POST. Gains also must stay within the two-sided cycles null for this refactor. Reject missing plateau, mismatched loads, unentered regimes or invalid noisy controls. Report the neutral, exercised and possible-deficit regimes separately; the code-size reduction is not a measured benefit.

**Instrument limitation requiring mainline work.** The latest retained nullrefresh5 campaign inspected was `/home/user/Projects/cx-nullrefresh/build/nullrefresh5-mainline-20260929T224208Z`. Its instrument fingerprint is **cc6c06bde1ce7939b7f001489fde7287476c4086929f51badf774811d087dd36**; manifest-file SHA-256 **ce0967f2e8b932367c3da15f276eec21b561cb8d7ddc11ca31b954671378f683**. All 23 instrument files were checked against that manifest and copied under `frozen/nullrefresh5-instrument/`. Frozen campaign SHA-256: **5ba88a7fb6a8dc337567c180decfe559e4bc124562c4f8b96a2702b4cb27f23c**. Its stable null binary is **ef52de792f72ab8dae240fcd8194e1f14aa94b3828dc7e512eea7256b50c1133**, built from the nullrefresh5 reference **9c4717da03b9340377926277f8eb99cea9f5ab5a**. This differs from the required cleanup PRE and is named explicitly.

At inspection that campaign's null verdict was **PARTIAL**, and there was no `holdout-resolution.json`. Thus no independently validated per-cell resolution can honestly be reported as available. Its geometry is 32 server cores / 16:16, not this request's 8 cores / 6:2. Launch `gate_measurements.json` has an ABBA ratio only for 32 cores and lacks the p1 h33/h49 load-floor entries. The frozen runner also forces flip-auto=0 in split and derives shards from worker count (`tests/abbagate.py:1420–1423`), and provides no database/transition-regime profile for this task. In particular its ordinary eight-core fused launch would use 64 shards, not 16.

Mainline must bind a supported explicit geometry/regime plan, validate its null and independent holdout, and freeze the resulting digest and per-cell resolution **before candidate measurements**. A changed instrument needs fresh validation; existing 32-core epsilons cannot certify the requested 8-core profiles. The report does not provide a guessed ABBA invocation that would silently run a different geometry. Once the instrument is ready, its exact cells/arms/pass conditions are those above; until then the PAD null and landing are **PENDING MAINLINE**. No instrument or tolerances were changed by this lane.

`sha256sum build/tomokv`:

```text
0e609387b66e21e69e636ad99be0e31d95457c14b6a47ea2e4edc204aa17b7e9  build/tomokv
```

`git diff 37eeb5e90 (launch origin/cpp) --stat`:

```text
 MEASURE-REQUEST-cleanup-flipsettle.md | 159 ++++++++++++++++++++++
 Makefile                              |   4 +-
 src/core/flipctl.cc                   |  31 ++---
 src/core/flipctl.h                    |   1 +
 tests/core_concurrency_unit.cc        |   5 +-
 tests/flipsettle_checks.inc           | 172 ++++++++++++++++++++++++
 tools/flipsettle_artifacts.py         | 244 ++++++++++++++++++++++++++++++++++
 tools/flipsettle_controls.py          | 183 +++++++++++++++++++++++++
 8 files changed, 776 insertions(+), 23 deletions(-)
```

Artifact manifest: `build/cleanup-flipsettle/ARTIFACT-SHA256SUMS`. Live correctness, measurements, receipt approval, gate and merge belong to mainline; there is no claim that this lane has passed those pending steps.
