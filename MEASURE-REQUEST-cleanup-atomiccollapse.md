Implemented and committed on `cx-cleanup-atomiccollapse`. **Landing remains PENDING MAINLINE:** PRE and POST executable code differs. Kind-A and kind-B controls have verified behavior mappings and exact target code/layout matches; no performance result or gain is claimed.

Reference: `37eeb5e90be9997805cfe2456021ad07dc0c18f9`, the launch-time `origin/cpp`. The worktree was clean at that commit. PRE was built and copied before any tracked source edit. Production factoring is commit `73ea5184f`; the completed code/proof commits end at `3eace5570` before this report. No push, server boot, load generator, benchmark, gate, or performance measurement was run. Builds used `taskset -c 112-127`, `make -j16`; serverless executions used `112-119` within that permitted range.

All artifact paths below are relative to `/home/user/Projects/cx-cleanup-atomiccollapse`. The complete artifact root is `build/atomiccollapse/`.

The verified launch diagnosis is `src/store/flatstore_atomic.inc:1514-1900` and `:1903-2292`, with shutdown promotion at `:2294` and its collapse call at `:2299`. The destructor disarms at `src/store/flatstore.h:722` before promotion at `:723`. The earlier audit's anchors were not copied without checking. `PRE/freeze/original.diff` retains the raw source difference. After removing the unarmed entry dispatch, substituting the three operation names, and normalizing whitespace plus the redundant braces around the armed single-statement retirement loop, all **3,164 source tokens match**, including comments. `PRE/freeze/normalized.diff` is empty; `normalization.json` describes every normalization.

The authoritative implementation is now `src/store/flatstore_atomic.inc:1527`, `template<bool ReadLocal> atomic_collapse_impl`. Its three local `constexpr` member-function constants select detached-value retirement, entry reclamation, and physical exchange. The existing wrappers remain at `:1514` and `:1520`; the original live dispatch remains in the first wrapper. `always_inline` retains those wrappers as the emitted call boundaries. It does not change any compiler inlining budget. No per-object mode test, per-retirement mode test, new knob, field, clearing pass, or allocation mechanism was added.

`tools/atomiccollapse_artifacts.py factor` checks the wrappers and each selector, then expands the shared body for each mode and compares its tokens with the frozen original body. Both expansion diffs under `PAD-A/` are empty. This covers floor/cutoff inequalities, snapshot refusal, undecided/aborted selection, intent activity, connection-order repair and winner choice, expiry conversion, accounting, capacity/reserve failures, physical exchanges, loser deduplication, unlinking, group references and cleanup order. Source before and after the replaced region must match exactly. The only other Makefile change adds the test include as a dependency. No unrelated helper was renamed and no layout/epoch/TTL/pool/protocol change was made.

The launch-time helper distinction needs precision. `retire_detached_obj_read_local` (`:1477`) submits a value to QSBR; direct retirement (`:1483`) can immediately recycle its storage. Those are observably different and the pinned-reader control catches the wrong selection. `atomic_free_entry_read_local` (`:968`) repeats the publication guard and then calls `atomic_free_entry` (`:949`); the direct helper also checks that guard. `atomic_exchange_physical` (`:1342`) already dispatches to the armed exchange (`:1263`) when enabled. Therefore changing only the latter two armed selections is behaviorally equivalent at this reference. Their runtime controls pass, and the independent source-selector checker rejects them. They are not falsely reported as lifetime failures or used as permission to delete the guards. No constant-return function or purportedly dead safety branch was removed; both compile-time mode choices remain instantiated and exercised.

**Build and code identity evidence.** GCC is Ubuntu `13.3.0-6ubuntu2~24.04.1`; defaults are `-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, with the existing per-TU flags unchanged. PRE and POST used the same worktree, relative source/output paths, dependencies, compiler and link order. `PRE/freeze/` retains the source archive, exact fresh build plan, compiler target/options, toolchain hashes, linked-library hashes, original Makefile, gate, headline cells and load-plan JSON. Compiler/library hashes were rechecked unchanged. Final release build log: `checks/final-release-build.log`; PRE log: `PRE/build.log`. Earlier exploratory/test-compilation logs are retained but are not the final build verdict.

The inventory is **84 production objects: all 42 normal plus all 42 db0 objects from the Makefile**, not a selection of hot functions. Forty-nine contain emitted FlatStore methods; ten emit collapse code, covering both arms and both `tomo`/`tomo_db0` namespaces. Each arm has raw `objdump -drwC` and `readelf -W -h -l -S -r -s` output, compressed without assembly normalization, plus a separate binary dump of every SHF_EXECINSTR section, including empty `.text`, every executable `.text.*`, and the executable's PLT/init/fini sections. Manifests retain ELF section addresses/alignment, function symbols/sizes/addresses, and relocation types, addends and complete target identities. The checker compares raw section byte strings; no displacement, opcode or instruction is erased. For final images it additionally compares all allocated sections except the build ID, including exception/unwind and dynamic-link data.

| Arm (`build/atomiccollapse/ARM/tomokv`) | Complete-file SHA-256 | File bytes | Linked `.text` bytes |
|---|---|---:|---:|
| PRE | `83934ad12d5390759ecdbf84bff604d8f8ff54de71b6d13387133e659fee7dbf` | 177,052,952 | 7,576,545 |
| POST | `1664c1526517ff092e26d637d05754a83cc93cca3385c209085c77db29ac5cbe` | 176,958,632 | 7,562,033 |
| PAD-A | `ead0315f2d03c9b4a27067c17d0bef5f7cab1ea7ce7f55eb59535cca0779773c` | 176,954,984 | 7,562,033 |
| PAD-B | `b3669bd326484093ed4752e1be50ece907b8433f247a477d19077ecd22ea75e3` | 177,053,168 | 7,576,545 |

| Comparison | Executable section bytes, relocations and symbols/addresses | Final allocated data | Verdict |
|---|---|---|---|
| PRE / POST | 74 of 84 objects match raw executable sections; ten differ; final executable differs | Differs | **NOT code-identical** |
| POST / PAD-A | All 84 objects and final executable match | Matches | PASS, code/layout identity |
| PRE / PAD-B | All 84 objects and final executable match | Matches | PASS, code/layout identity |
| Archived POST / final working build | All 84 objects and final executable match | Matches | PASS |

These are executable-code/layout identities, not claims that complete ELF files are equal: debug information and build IDs differ, as the full-file hashes show. PRE contains 8,536 audited executable sections including the linked image; POST has 8,585. Final symbol/address inventories contain 10,335 and 10,324 functions respectively. Raw artifacts and comparisons are in each arm's `dumps/`, `comparison.json`, `PAD-A/comparison.json`, `PAD-B/comparison.json`, and `final-working-build.json`.

The changed objects and total executable-section size deltas are recorded below. Full added/removed/resized symbols and differing sections are in `codegen-differences.json`.

| Object | Executable-byte delta | Object-local resized functions |
|---|---:|---:|
| `db0/src/cmd/xshard.o` | -121 | 5 |
| `db0/src/core/genthread.o` | -545 | 9 |
| `db0/src/core/reorder.o` | -222 | 4 |
| `db0/src/core/rl2s.o` | -750 | 7 |
| `db0/src/main.o` | -570 | 6 |
| `src/cmd/xshard.o` | +212 | 6 |
| `src/core/genthread.o` | -307 | 10 |
| `src/core/reorder.o` | -481 | 8 |
| `src/core/rl2s.o` | -822 | 6 |
| `src/main.o` | -436 | 6 |

Moving the bodies into the template changes GCC's outlining/inlining and COMDAT emission, including code in the parser/owner-loop TUs. This is real codegen movement, not just renamed symbols or debug lines. Existing compiler budgets were left intact. The linked `.text` shrinks by **14,512 bytes**; that is not a measured gain. The behavior controls below independently isolate the compiler-context/layout change. No producer stores or RFOs were intentionally removed; there is no claimed coherence benefit.

**PAD-A is kind A, behavior twin:** two complete bodies extracted mechanically from frozen PRE, selected as a whole by `if constexpr (ReadLocal)` inside the candidate template/wrapper context. It does not use the candidate's operation selectors. Source: `PAD-A/generated-flatstore_atomic.inc`; compiled copy: `PAD-A/probe/src/store/flatstore_atomic.inc`. The full 84-object and linked-image comparisons prove that it has PRE behavior with POST executable size, addresses, alignment and layout. This is a separately compiled control, not an R7 PAD or a renamed copy of POST.

**PAD-B is kind B, inverse control:** the candidate shared body is expanded mechanically with each constant operation choice and put back into the PRE wrappers. Source: `PAD-A/generated-inverse-flatstore_atomic.inc`; compiled copy: `PAD-B/probe/src/store/flatstore_atomic.inc`. Its behavior is the candidate's, with PRE's executable size/layout restored. Full comparison matches PRE. This control is supplied because the text change exceeds a few hundred bytes. Neither control relies on a footer of NOPs. Both use identical compiler flags, relative source names and dependencies; their build directories only change debug provenance. Generated input hashes match the files actually compiled. The generated copies stay under ignored `build/`; production has one handwritten implementation.

For example, the linked unarmed/armed collapse entry addresses are `0x80350`/`0x7e7c0` in PRE's db0 namespace and `0x891c0`/`0x87800` in POST. Normal-namespace addresses are `0x3fe7a0`/`0x3fcbf0` in PRE and `0x403c80`/`0x402000` in POST. PAD-A matches POST and PAD-B matches PRE at every function, not only these four.

The byte checker's negative control copies PRE and flips exactly one executable `.text` byte. It reports 84/85 matching artifacts and rejects identity. That corrupted artifact has never been executed. `byte-negative/negative.json` and `byte-negative.log` retain the result. Separate source controls swap the wrapper selection and the free-entry selector; each fails its exact checker assertion (`source-controls/results.json`).

**Correctness evidence.** The existing `atomic-survivors-unit admission` row includes `tests/atomiccollapse_checks.inc`; no gate row was added. State-only fixtures cover both thread modes, read-local off/on, normal databases 1 and 3 (including namespace 2), and the separately compiled db0 namespace. They retain real transaction entries, actual epoch decisions, actual snapshot marking, the production QSBR queue and participant publications, and actual reclamation callbacks. No worker loop or listener is started.

The unarmed fixture first checks that ordinary construction has no atomic/read-local state. It then explicitly prepares a disabled test sink so a wrong selector produces a named sink assertion. This observation setup does not add any production allocation when read-local is off. A held participant publication and retained old value prove that an armed value reaches the queue and cannot reach its reuse pool until the reader pin releases. Direct reclamation is checked separately. Duplicate predecessor ownership is a synthetic fixture attacking the defensive deduplication; it is not a claim that production normally publishes duplicate ownership. Both the unique worklist and the armed sink detect the corresponding mutation.

Every mechanism assertion names its state and failure. Allocation refusal sweeps four scratch-allocation points on fresh fixtures, then requires success within twelve attempts. Snapshot-active, pinned-reader and allocation-failure windows have explicit no-entry controls. No assertion is waived, skipped, or given a wider tolerance when its state is absent. Existing storage rollback covers table-allocation refusal and rehash as well. Winner checks cover cross-connection tickets, same-connection program order, aborted entries, an undecided boundary, expiry/tombstones and exact RESP replies. Counts, byte gauges, activity, group refs and connection-list unlinking are asserted.

| Serverless check | Result | Artifact |
|---|---|---|
| All 16 existing survivor selections | PASS | `checks/survivor-results.json` and `survivor-*.log` |
| Extended fixture against frozen PRE bodies | PASS | `checks/survivor-PRE.log` |
| Extended fixture in db0 | PASS | `checks/survivor-db0.log` |
| Extended fixture under fully instrumented ASAN/UBSAN, leak detection enabled | PASS | `checks/survivor-ASAN-collapse.log` |
| Original PRE collapse bodies under the same sanitizer fixture | PASS | `checks/asan-pre-collapse_all.log` |
| Core concurrency snapshot, lifetime, route (all implementation TUs ASAN/UBSAN) | PASS | `checks/results.json`, `core-*.log` |
| Storage rollback, rehash, intents | PASS | `checks/results.json`, `storage-*.log` |
| Multidb serverless owners | PASS | `checks/multidb-owners.log` |
| Both namespace layout locks | PASS | `checks/layouts.json` |
| 22 mutation failures plus two runtime-equivalent/source-invalid helper controls | PASS, 24/24 expected results | `controls/results.json` |

The layout values remain `Op 336`, `Client 1984`, `ThreadCtx 1408`, `Shard 1440`, `FlatStore 944`, `Rob<64> 192`, `AtomicEntry 144`, `Config 624` in both namespaces. Existing offset assertions compile unchanged. The standalone existing layout probe warns about `offsetof` on non-standard-layout `Server`; no assertion was changed to suppress it.

The negative controls are generated copies of production source. `controls/manifest.json` records each exact removed/bypassed expression, source/test hashes, compiler command and selected case. Every binary SHA and exit is recorded in `controls/results.json`. All tests below were actually run on permitted cores.

| Control | Exercised case | Exact failure / expected outcome | Result |
|---|---|---|---|
| `floor` | `boundaries` | `floor equality: epoch equal to floor retained`; exit 1 | PASS |
| `cutoff` | `boundaries` | `cleanup cutoff equality: eligible prefix reclaimed`; exit 1 | PASS |
| `undecided` | `boundaries` | `undecided boundary: linked suffix and its owner reference retained`; exit 1 | PASS |
| `winner` | `winners` | `collapse winner: exact logical value/tombstone`; exit 1 | PASS |
| `program-order` | `winners` | `collapse winner: exact logical value/tombstone`; exit 1 | PASS |
| `aborted-winner` | `winners` | `collapse winner: exact logical value/tombstone`; exit 1 | PASS |
| `deduplicate` | `winners` | `duplicate loser: unique worklist contains one owned payload`; exit 1 | PASS |
| `allocation` | `allocation` | `allocation refusal: all entries, ownership, accounting and retire state preserved`; exit 1 | PASS |
| `snapshot` | `snapshot_teardown` | `snapshot refusal: eligible entry retained without reclamation`; exit 1 | PASS |
| `unlink` | `boundaries` | `undecided boundary: linked suffix and its owner reference retained`; exit 1 | PASS |
| `accounting` | `winners` | `collapse accounting: records/promotions/version bytes/live bytes exact, no underflow`; exit 1 | PASS |
| `intent` | `intent` | `intent collapse: freeing last version preserves live reservation and activity`; exit 1 | PASS |
| `expiry` | `winners` | `collapse accounting: records/promotions/version bytes/live bytes exact, no underflow`; exit 1 | PASS |
| `armed-direct` | `pinned` | `armed pinned: loser must reach QSBR sink before any storage reuse`; exit 1 | PASS |
| `unarmed-sink` | `pinned` | `unarmed collapse: read-local sink must not be called`; exit 1 | PASS |
| `fast-path` | `pinned` | `pinned collapse: committed fast path entered`; exit 1 | PASS |
| `teardown` | `snapshot_teardown` | `teardown: undecided record aborted and directly reclaimed after disarm, no sink callback`; exit 1 | PASS |
| `early-grace` | `pinned` | `armed pinned: actual reclaim callback blocked and immutable reader bytes intact`; exit 1 | PASS |
| `unentered-pin` | `pinned` | `armed pinned: actual reclaim callback blocked and immutable reader bytes intact`; exit 1 | PASS |
| `unentered-snapshot` | `snapshot_teardown` | `snapshot refusal: capture really active`; exit 1 | PASS |
| `unentered-allocation` | `allocation` | `allocation window: all four scratch allocations refused, then success`; exit 1 | PASS |
| `free-alias` | `all` | Runtime PASS; source checker rejects the wrong selector | PASS |
| `exchange-dispatch` | `all` | Runtime PASS; source checker rejects the wrong selector | PASS |
| `deduplicate-armed` | `winners` | `duplicate loser: each payload retired exactly once`; exit 1 | PASS |

The final direct-duplicate assertion is stronger than the first fixture version: a pool byte counter alone did not catch the removed `unique()`. The unique-worklist assertion now catches it directly, and a separate armed-first control reaches the sink's duplicate-payload assertion. Thus both retirement arms have a failing duplicate control.

The survivor test's existing custom malloc/free allocator also needed matching nothrow new/delete overloads for sanitizer use; otherwise ASAN supplied nothrow new and correctly reported an allocation/deallocation mismatch at read-local teardown. The test allocator was fixed without disabling any sanitizer check. All sixteen existing release selections still pass, including WATCH allocation-failure coverage.

**Remaining diagnostic failure:** the legacy `admission` portion of the optional all-TU JE=0 sanitizer driver times out before entering the new collapse suite. POST first hit a 90-second deadline; bounded reproduction then timed out at 10 seconds with both the original PRE collapse bodies and POST (exit 124). `checks/asan-admission-diagnostic.json` records both binaries and commands. The new `collapse_all` selection passes on both sanitizer binaries. The legacy timeout is not diagnosed or labeled PASS; it is outside this mechanical cleanup and needs mainline follow-up. This is narrower evidence than a complete historical PRE sanitizer build: the PRE-body driver links the same fully instrumented non-xshard objects, while compiling the original collapse bodies in its real xshard TU. No confirmed correctness-law violation was found in the factored source; that does not certify the unrun live paths.

**Mainline handoff.** Every live boot/battery, ownership churn, live ASAN run, gate and measurement is **PENDING MAINLINE**. Retain the existing rows: core concurrency at `tests/gate.sh:1246`, storage at `:1301`, multidb owners at `:1330`, survivors at `:1344`, atomic torn/window at `:1502` and RYOW at `:1506`, AOF atomic-group recovery at `:2086`, live ASAN at `:2383-2405`, and armed block-cache churn/ownership at `:2486-2510`. Single-owner writes, eager retire-sink handoff, immutable replacement/QSBR, reply ordering and RYOW were not redesigned.

The emission line for the extended admission row is `tests/gate.sh:1356`, reached through the unchanged sixteen-name loop at `:1349`. It is before the quick-tier block at `:2854` (exit at `:2858`). Row delta is **0 quick, 0 full**: `441 + 0 = 441`, `461 + 0 = 461`. `EXPECT_QUICK` and `EXPECT_FULL` and the entire gate file are byte-identical to reference. The stated 461/0 reference gate is the maintainer's launch baseline, not a gate run by this lane.

The original `tests/headline_cells.txt` is frozen byte-for-byte, SHA-256 `d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350`. The base guard remains **h01-h64**, including their 512 total connections, GET/SET, p1/p32, both modes and all read-local/overlap/reorder combinations. Launch load plans and payload code are retained; no existing cell was changed. The explicit initial fourteen-cell generic subset requested here is `h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h63,h64`; its exact existing lines are in `generic14.cells.txt`. This subset does not replace the full h01-h64 guard.

`mainline-cells.json` gives the separate feature requests: `ca-n01..32` neutral atomic=0 GET/SET; `ca-e01..48` exercised atomic=1 MGET/MSET/EXEC; `ca-d01..48` possible-deficit same-key groups, held readers and snapshot/expiry pressure. They cross 1s/2s, read-local 0/1, databases 1/3 and p1/p32. Each uses 512 total connections, 64-byte values, eight keys per multi-key group, sixteen shards, and the reviewed eight-core 6:2 split in 2s; ordinary neutral cells retain the two-million-key population. These are measurement requests, not new gate emissions. MGET collapse requires a separately accounted, fixed writer stream; EXEC and pressure schedules need supported workload adapters and entry witnesses. Their exact schedules, offered loads and worker floors must be independently validated and frozen by mainline before POST. This lane did not silently substitute generic MGET traffic for an exercised collapse regime.

The copied nullrefresh instrument fingerprint is `cc6c06bde1ce7939b7f001489fde7287476c4086929f51badf774811d087dd36` (23 dependency files); its manifest file SHA is `ce0967f2e8b932367c3da15f276eec21b561cb8d7ddc11ca31b954671378f683`. All 23 source hashes were verified and copied under `instrument/source/`. That campaign's stable executable is `ef52de792f72ab8dae240fcd8194e1f14aa94b3828dc7e512eea7256b50c1133`; this cleanup requests stable reference **37eeb5e90 / PRE `83934ad12d5390759ecdbf84bff604d8f8ff54de71b6d13387133e659fee7dbf`**. The inspected campaign has a PARTIAL null-collection result and no holdout-resolution artifact at the inspected location. PARTIAL is an expected null-collector label, not by itself evidence of failure. A validated per-cell resolution/holdout receipt still has to be supplied before this candidate is measured.

The instrument mismatches must be resolved explicitly: its retained calibration is for 32 server cores/16:16, and its launcher computes 64 shards for an eight-core fused run (`instrument/source/tests/abbagate.py:1440`). It also treats depth one as saturation-exempt. Those facts cannot certify the requested sixteen-shard geometry or the required productive-role plateau at p1. Do not transplant the old worker floors or claim that selecting eight CPUs fixes all three conditions. Mainline must supply the independently validated instrument/geometry and freeze its digest, stable SHA and per-cell cycles/rate/tail resolution before candidate data. The requested epsilon fields are deliberately unset/PENDING in the JSON; no tolerance was guessed or widened.

Measure PRE/POST, PRE/PAD-A and PAD-A/POST, plus the supplied inverse-control PRE/PAD-B and PAD-B/POST comparisons. The verified code/layout identities discharge code differences for PAD-A/POST and PRE/PAD-B; PRE versus the POST layout still requires the mainline-controlled null. For **each** cell, at matched offered loads, require:

- `abs(100*(B_cycles/A_cycles - 1)) <= epsilon_cyc[cell]` (two-sided).
- `100*(1 - B_rate/A_rate) <= epsilon_rate[cell]`.
- `100*(B_tail/A_tail - 1) <= epsilon_tail[cell]`, separately for the relevant tails.
- Stable-reference parity at that cell's independently validated resolution; enough connections/load workers to prove the productive-role plateau at both p1 and p32. No single-connection saturation claim.

Fix all bands before POST, retain every block/cell, and fail any losing cell without averaging or widening. Report cycles/op, instr/op and IPC together (`cycles/op = instr/op / IPC`), rate and relevant p99/p99.9 tails. A gain is not required. The required PRE/POST result table is currently:

| Regime | PRE cycles/instructions/IPC, rate, tails | POST cycles/instructions/IPC, rate, tails | Verdict |
|---|---|---|---|
| Neutral atomic=0 GET/SET and unchanged generic guard | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| Exercised collapse / potential benefit: MGET/MSET/EXEC | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE; no gain required |
| Possible deficit: same-key groups, held readers, snapshot/expiry | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |

Mainline's exact server launch contract for each requested feature cell is below; the validated instrument must record these effective arguments and its frozen generator/load plan. This is not a replacement measurement harness and was not executed:

```bash
# Set ARM to one of the four absolute paths in binaries.json; select the JSON cell's values.
extra=()
if [ "$MODE" = 2s ]; then extra=(--ratio 6:2); fi
taskset -c 0-7 "$ARM" --bind 127.0.0.1 --port 8700 \
  --thread-mode "$MODE" --shards 16 "${extra[@]}" \
  --atomic "$ATOMIC" --read-local "$RL" --databases "$DB" \
  --overlap "$OV" --reorder "$RO" --flip-auto 0 --key-lb 1 --client-lb 1 \
  --save '' --appendonly no --enable-debug-command yes
```

The existing source-certifying gate entry point, for the maintainer's scheduled run, is:

```bash
cd /home/user/Projects/cx-cleanup-atomiccollapse
tests/gate.sh iteration --server-cores 0-7 --server-smt '' \
  --load-cores 8-111 --load-smt '' --ports 8700-8799 \
  --reference-binary "$PWD/build/atomiccollapse/PRE/tomokv"
```

That command builds the candidate from this source. Adding `--candidate-binary "$PWD/build/atomiccollapse/POST/tomokv"` instead tests the exact archived arm, but the gate explicitly withholds the source receipt for external candidates (`tests/gate.sh:1176`). Neither invocation waives the instrument mismatches or turns stock ABBA output into the required calibrated null. Live commands and measurements remain PENDING MAINLINE. All new negative controls in this lane are serverless; their binaries are already built. Reproduce them, and the raw proof, without starting a server:

```bash
taskset -c 112-127 python3 tests/atomiccollapse_controls.py generate
taskset -c 112-127 make -C build/atomiccollapse/controls -j16
taskset -c 112-127 python3 tests/atomiccollapse_controls.py run
taskset -c 112-119 ./build/atomic-survivors-unit admission
taskset -c 112-127 python3 tools/atomiccollapse_artifacts.py factor \
  37eeb5e90 src/store/flatstore_atomic.inc build/atomiccollapse/PAD-A
# PRE/POST must return 1; it is intentionally not asserted identical.
taskset -c 112-127 python3 tools/atomiccollapse_artifacts.py compare \
  build/atomiccollapse/PRE build/atomiccollapse/POST build/atomiccollapse/comparison.json
taskset -c 112-127 python3 tools/atomiccollapse_artifacts.py compare \
  build/atomiccollapse/POST build/atomiccollapse/PAD-A build/atomiccollapse/PAD-A/comparison.json
taskset -c 112-127 python3 tools/atomiccollapse_artifacts.py compare \
  build/atomiccollapse/PRE build/atomiccollapse/PAD-B build/atomiccollapse/PAD-B/comparison.json
```

The artifact manifest has 36,192 entries, including section/relocation dumps, complete arm/object hashes, proof results and test binaries. `build/atomiccollapse/ARTIFACT-SHA256SUMS` SHA-256 is `25c63cecc887c84adccf1b701f78286a4303a66e93ad24565c7b08a492738c5c`. All 36,192 entries passed `sha256sum -c` (exit 0); verification log: `build/atomiccollapse/verify-artifacts.log`. Regenerating proof artifacts changes provenance timestamps/logs; re-freeze the manifest deliberately if reproducing them.

Requested final executable identity:

```text
$ sha256sum build/tomokv
1664c1526517ff092e26d637d05754a83cc93cca3385c209085c77db29ac5cbe  build/tomokv
```

Requested diff against `37eeb5e90` (launch `origin/cpp`), including this report:

```text
 MEASURE-REQUEST-cleanup-atomiccollapse.md | 203 ++++++++++++++
 Makefile                                  |   1 +
 src/store/flatstore_atomic.inc            | 429 ++----------------------------
 tests/atomic_survivors_unit.cc            |  18 +-
 tests/atomiccollapse_checks.inc           | 306 +++++++++++++++++++++
 tests/atomiccollapse_controls.py          | 184 +++++++++++++
 tools/atomiccollapse_artifacts.py         | 304 +++++++++++++++++++++
 7 files changed, 1043 insertions(+), 402 deletions(-)
```
