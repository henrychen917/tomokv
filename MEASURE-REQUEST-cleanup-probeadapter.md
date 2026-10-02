cleanup-probeadapter — shared capture adapter, production executable identity

Worktree `/home/user/Projects/cx-cleanup-probeadapter`, branch `cx-cleanup-probeadapter`. **Production code identity PASS:** all 84 production objects and the linked executable have identical executable bytes/layouts, allocated relocation targets, symbol addresses and entry point. No PAD or measured null is required for these frozen arms. Whole ELF files are not all identical; the non-executable differences are explained below. No server, load generator, benchmark, gate, performance measurement or push was run. All builds and serverless checks used `taskset -c 112-127`; make builds used `-j16`. Live results remain **PENDING MAINLINE**.

**Reference and scope.** The clean lane launched at staging commit `5b3d9c4292bf8b332d493beb485266ecc5a289aa`. Launch `origin/cpp` was already eight commits ahead, at `2a9e484035960b0ba5925824cc581148c359c0f8`. The first mutation was `git merge --ff-only origin/cpp`, which succeeded. Following the launch ruling, PRE is this merged launch reference, not the older staging commit. `build/cleanup-probeadapter/freeze/` retains both SHAs, the clean launch status, history, full reference source archive, compiler inputs, cell bytes and plans. The executable was built and archived before the adapter edit. The original unit binaries were also built and archived before their source changed.

Implementation commit: `05524932d`. Completed proof/control tooling: `534a08cdf`. The final report commit changes documentation only. The staging diff below includes inherited readreply work; the separate launch-reference diff identifies this lane's one change.

**Rechecked diagnosis and callers.** At launch, `src/store/flatstore.h:900` contained the independent probe protocol, with its two private-walk calls at `:916` and `:917`; the private duplicate started at `:3271`. Production capture started at `:946`, and its walk at `:3302`. The old audit's db0 caller line 56 had moved to 63. These are test-coverage duplicates of an existing production mechanism, not evidence that production lacked capture, topology validation or immutable-object prefetch.

| Historical probe consumer | Launch anchor | POST witnessed caller |
|---|---|---|
| Rehash foreign read | `tests/rehash_waits_unit.cc:144` | `:145` |
| Multidb prebuilt TTL replacement | `tests/multidb_unit.cc:77` | `:78` |
| Multidb namespace identity, the second site | `tests/multidb_unit.cc:156` | `:157` |
| Separately compiled db0 identity | `tests/multidb_db0_unit.cc:63` | `:66` |

All four now call the same test witness helper, which calls the production adapter. The adapter's actual direct test callers are `tests/probeadapter_checks.h:66` and `:117` (stable states and forced transition). Its definition is `src/store/flatstore.h:901`; its only action is to project capture's `result/object/state` at `:902-903`. The private duplicate has no remaining callers and was deleted. Its `key_mem_eq` rationale moved beside `read_local_capture_in` at `:3271`; the comparison and probe bound are unchanged.

For completeness, all capture consumers are recorded too. The three production sites are `src/core/ex_loop.h:1209` (MGET), `:1324` (point read) and `:1496` (prefetch batch). The new adapter calls capture at `src/store/flatstore.h:902`. Existing direct test consumers remain at `tests/rehash_waits_unit.cc:227` and `tests/rltopo_unit.cc:254`; the shared checks additionally call it at `tests/probeadapter_checks.h:64` and `:120`. Full inventories are `callers-PRE.txt` and `callers-POST.txt` under the artifact root.

History supports this classification: `fd88494a5` introduced reclamation-safe foreign probes; `7d4dcabfa` introduced capture consumption and retained the exact slot, immutable object and publication state. The enabled-state producer is `configure_read_local` at `src/store/flatstore.h:750`, and the production consumers above still use capture. The disabled `Churn/null/0` result is a deliberate fail-closed contract, not a constant-return defect or a never-wired mechanism. The defect addressed here is coverage drift from maintaining a second test lookup implementation. No live contract evidence was deleted as purported dead code. `history-evidence.txt` retains the commit evidence.

**Remaining design conflict.** Production still uses live topology sequence validation: capture at `src/store/flatstore.h:949-980`, the pointer/capacity snapshot at `:3259-3268`, and odd/even publication at `:3381-3396`. This conflicts with the supplied no-seqlock law. These checks protect pointer/capacity pairing and torn-read safety and were preserved exactly.

The audit's old claim of a live two-attempt MGET retry does not describe launch machine behavior. The source still declares two attempts at `src/core/ex_loop.h:1155` and a loop at `:1177`, but the unconditional assembly jump at `:1291-1294` demotes before another release attempt. Only the existing test build can bypass that jump to restore retries. History `70a4ae41c` documents the earlier demotion change. Launch readreply also removed the point-read retry loop. This lane neither restores retries nor claims that production now satisfies the no-seqlock law. No additional ownership, QSBR, in-place overwrite, RYOW, atomicity or reply-order change is made.

**Executable proof.** Artifact root: `build/cleanup-probeadapter/`. PRE and POST use identical source/output paths, GCC 13.3.0, compiler/assembler/linker identities, flags and dependencies except the intended `flatstore.h` edit. `input-parity.json` verifies this and confirms that the archived POST still matches all final production build products. The Makefile change only declares the shared test header dependency; all production command lines compare byte-for-byte. Both normal and db0 objects are inventoried: 42 each, with 33 in each namespace including FlatStore. The proof conservatively compares all 84, including the 18 without that dependency.

The source spacer preserves the pointer-encoding assertion's embedded `__LINE__` at `src/store/flatstore.h:2259`. It prevents changing release assertion instructions while deleting the unused probe body. It adds no machine padding. The test-only entry hook and existing capture-stage hook are absent from release symbols and executable code; no field or allocation was added. Existing size/offset assertions remain. Both namespaces compile with `Op 336`, `Client 1984`, `ThreadCtx 1408`, `Shard 1440`, `FlatStore 944`, `Rob<64> 192`, `AtomicEntry 144`, and `Config 624`.

| Arm | Executable path | SHA-256 |
|---|---|---|
| PRE, launch `2a9e48403` | `build/cleanup-probeadapter/PRE/artifacts/tomokv` | `d58f558420293e717af0f38f6b0488853659164b37d56978aedfdb8ce93d6105` |
| POST, shared adapter | `build/cleanup-probeadapter/POST/artifacts/tomokv` | `ab44f3f0bffcdd97f8e3c4cdc9f83df956bd0b8e3eb2e4981ae08ad6cf9acafe` |
| PAD | Not required by the successful executable identity proof | No existing R7 PAD is claimed as this cleanup's control |

`production-comparison.json` compares raw bytes in every SHF_EXECINSTR section, including `.text`, every executable `.text.*`, and linked initialization/PLT/finalization sections. It checks allocated data, relocation types/offsets/addends/resolved symbol identities, allocated symbol addresses/attributes, ELF entry and program headers. Totals: **85 artifacts, 8,594 executable sections, 19,664,449 executable bytes, 201,688 relocation records and 46,771 symbol records**. All pass. Linked `.text` is **7,564,433 bytes** in both arms; entry is **`0x4dc10`**. The six linked executable sections all match exactly.

This is not normalized assembly or instruction-count evidence. Each arm retains raw section dumps, `objdump -drw`, `readelf -W -h -l -S -s -r`, `nm -anSC`, relocation/address JSON and file SHA-256 manifests under `PRE/` and `POST/`. Only 20/85 complete ELF files match. Differences in the others are DWARF, DWARF relocations, build IDs and `.strtab`. GCC renumbered 138 zero-size local assembly marker labels across the inventory, including 41 in the executable; their addresses and attributes match exactly. Function names/addresses, raw executable bytes and allocated relocation targets do not change. The inherited checker permits only those existing `tomo_multidb2_pad_*`/`tomo_rltopo_demote_*` marker-name changes, not function or target changes.

Five copied-artifact controls separately corrupt one `.text` byte, one executable `.text.*` byte, an allocated relocation addend, a function address and the ELF entry point. All five are rejected with the expected error (`elf-controls/results.json`). Corrupted artifacts are marked `NEVER-RUN`, mode 0600, and were never executed. Seven source controls also reject removing prefetch, changing disabled state, changing key comparison, changing the probe bound, dropping projected state, restoring the obsolete-walk marker, or shifting the release assertion line (`source-controls.json`). `source-proof.json` proves the production capture body is verbatim apart from test-only hooks and the capture walk differs only in its rationale comment.

**Serverless evidence.** The existing batteries now share `tests/probeadapter_checks.h`; no independent lookup oracle remains in committed test code. Stable states compare every projected field with capture and separately assert semantic expectations. The transition uses two fresh stores, one through the adapter and one through capture. Each triggers a real 64-to-128 grow after slot capture and before final validation, within 128 insertions. Entry, changed topology and exact Churn/null/current-state are mandatory; neither a skipped window nor a widened tolerance can pass. Existing rehash foreign reads also traverse actual old/new tables under the pinned retirement fixture.

| Check | Result | Artifact |
|---|---|---|
| PRE production and original unit builds | PASS | `PRE-build.log`, `PRE-units-build.log` |
| POST production and extended unit builds | PASS | `POST-build.log` |
| PRE rehash retirement, multidb, core route/snapshot, storage rehash/flags | PASS, 6 selections | `checks/PRE-results.json` |
| POST same six selections plus rehash maintenance | PASS, 7 selections | `checks/POST-results.json` |
| Shared fixture under ASAN/UBSAN, namespaces 0 and 3, leak detection enabled | PASS | `checks/asan-command.json`, `checks/asan-run.log` |
| Positive generated controls, rehash/multidb/db0 | PASS, 3 drivers | `controls/results.json` |
| Semantic/entry/window negative controls | PASS, 70 expected failures | `controls/results.json` |
| Raw executable, relocation, address and entry checker controls | PASS, 5 rejections | `elf-controls/results.json` |
| Source invariant controls | PASS, 7 rejections | `source-controls.json` |

Storage flags ran the TSan binary with `setarch x86_64 -R`. GCC's existing `atomic_thread_fence` TSan warnings occur in PRE and POST; neither runtime check failed. Core route/snapshot use the fully instrumented existing ASAN/UBSAN objects. The shared fixture also links those objects for its sanitizer run. Original and changed unit binaries, including both multidb test objects, are retained under `PRE-tests/` and `POST-tests/` with hashes. Test binaries are expected to change and are not included in the production identity verdict.

Every new C++ assertion has a directed failing control. The following 22 controls each ran in the rehash, normal multidb and separately compiled db0 driver (66 failures total). Labels below are the exact failure suffixes; the logs also name the exercised state.

| Exercised state/assertion | Throwaway removed/bypassed mechanism | Expected observed failure |
|---|---|---|
| Capture entry, including disabled | `legacy`, `no-entry` | `capture entered exactly once` |
| Hit walk entry | `no-walk` | `exact capture walk count` |
| Hit object/state projection | `drop-object`, `drop-state` | `exact result/object/state projection` |
| Disabled Churn/null/0 | `disabled-state` | `exact semantic result/object/state` |
| Disabled must not walk | `disabled-missing` | `exact capture walk count` |
| Known Hit | `hit-missing` | `exact semantic result/object/state` |
| Known Missing | `missing-hit` | `exact semantic result/object/state` |
| Unsafe-key AtomicPending | `pending-churn` | `exact semantic result/object/state` |
| Unsafe-key must not walk | `pending-missing` | `exact capture walk count` |
| Odd topology Churn | `accept-odd` | `exact semantic result/object/state` |
| Deciding slot retained | `drop-slot` | `capture retains deciding slot only after a walk` |
| Capture invalidated by real grow | `accept-invalid` | `invalid topology returns Churn/null/current state` |
| Resize actually entered | `no-transition` | `real resize entered within 128 insertions` |
| Transition capture entry | `no-transition-entry` | `capture entered and walked exactly once` |
| Fresh transition twins agree exactly | `different-twin-generation` | `exact result/object/state projection across fresh twins` |
| Unsafe-key window entered | `no-pending-window` | `unsafe-key window entered` |
| Odd topology window entered | `no-odd-window` | `odd topology window entered` |
| Fixture allocation/admission | `no-preparation`, `no-hit-insertion`, `no-grow-insertion` | `read-local preparation succeeds`, `known Hit insertion succeeds`, `bounded grow insertion succeeds` |

The remaining four controls enable the frozen PRE independent probe only when each historical caller is reached. All fail `capture entered exactly once` with their exact labels: `rehash foreign`, `multidb prebuilt TTL`, `multidb identity`, and `db0 identity`. Earlier fixture states pass before these targeted failures. Thus matching lookup values cannot substitute for entering production capture. The legacy body is mechanically extracted from frozen PRE into ignored `controls/source/` only; it is never retained as an oracle or compiled into a release arm. All controls are serverless, so no new live control is left unbuilt.

**Gate arithmetic and live handoff.** This lane does not edit `tests/gate.sh`, its constants, or its load plans. The gate file equals the launch copy, SHA-256 `7e9c48db8ff07e3ead9e4eb933667d126761fe73dcef19c618a87a06b9006a08`. Relevant success-emission lines are core route/snapshot `:1254`, storage rehash/flags `:1330`, multidb serverless owners `:1349`, retirement `:1446`, and all four read-only resize mode/read-local rows `:1469`. They are all before the quick exit at `:2875`. Cases were extended inside existing batteries: **quick delta 0, full delta 0; 446 + 0 = 446, 463 + 0 = 463**. These are maintainer-owned expected counts, not a claimed gate run.

Both 1s/2s boots, databases=1/>1 live behavior, live resize rows, the complete gate and any performance runs are **PENDING MAINLINE**. For a scheduled source-certifying run, the existing entry point is:

```bash
cd /home/user/Projects/cx-cleanup-probeadapter
tests/gate.sh iteration --server-cores 0-7 --server-smt '' \
  --load-cores 8-111 --load-smt '' --ports 8700-8799 \
  --reference-binary "$PWD/build/cleanup-probeadapter/PRE/artifacts/tomokv"
```

Using `--candidate-binary "$PWD/build/cleanup-probeadapter/POST/artifacts/tomokv"` instead selects the exact archived arm but follows the gate's external-candidate receipt rules. Neither command was run here.

**Frozen measurement contract.** Executable identity discharges the performance-null requirement for these arms; there is no expected production benefit and no measured gain claim. The complete launch `tests/headline_cells.txt` is frozen, SHA-256 `d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350`; the load-plan file is `883634597e70a073c6f7c011524924723a90f77dbed328a1334b4fad26e96afb`. Source archives and `freeze/launch-plans/` retain payload/load implementation bytes. Base guards remain **h01-h64**, 512 connections, GET/SET, p1/p32, both modes and all existing read-local/overlap/reorder combinations. `freeze/guard64.cells.txt` and `freeze/generic14.cells.txt` preserve original line bytes. The launch ruling's generic fourteen are `h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h63,h64`; they do not redefine the full guard.

The separately appended `mainline-cells.json` requests 80 feature cells without editing any headline cell: `pa001-016` neutral fixed-table GET, `pa017-048` exercised rehash GET/MGET, `pa049-080` possible-deficit expiry/rehash GET/MGET. Each family crosses 1s/2s, read-local 0/1, databases 1/3, p1/p32, 512 connections, 64-byte values, and eight keys for MGET. Read-local=0 is the companion control, not claimed local-capture entry. Geometry is 16 shards, server cores 0-7, 2s ratio 6:2, load cores 8-111, atomic/overlap/reorder/key-LB/client-LB=1 and flip-auto=0. Rehash and expiry entry, writer schedules, offered loads, worker plateaus and per-cell epsilon values require independent validation/freeze if mainline elects to measure; the JSON marks those pending rather than inventing calibrated values.

The inspected nullrefresh/nullpublish campaign instrument has fingerprint **`ef5bb5a313f566a67f70b583708bc087da217c9ec5162a3974bb3483b61617dc`**, manifest SHA **`409e9ebbb74775454708663b712339789f0ea55d84ab3da2dabe4343b3084b9d`**, and stable executable SHA **`49e69e30d1d3d46f46f8e5f96dad17885511e905c98fba4a3d530814885cf1a7`**. All 25 dependency hashes were verified and copied under `freeze/instrument/source/`; its manifest, freeze and campaign are retained. The inspected `nullpublish-mainline-20261001T040445Z` has no holdout-resolution artifact. Its campaign requests 32 server cores and is not proof of this task's eight-core/16-shard geometry. **Per-cell independently validated resolution is PENDING MAINLINE**, not silently inferred from that fingerprint. This does not block the completed byte-identity route.

If rebuilding/rebasing breaks identity, freeze the valid instrument digest, its stable reference SHA and each cell's resolution before candidate data. Supply a separate **kind-A PAD behavior twin: PRE behavior with POST text size/layout and the same function address table**. Add kind B, POST behavior restored to PRE text size, for a text change exceeding a few hundred bytes. NOP footers or an unrelated R7 PAD do not establish that mapping. No nonidentical rebuild is covered by this lane's identity claim.

For any required PRE/POST, PRE/PAD-A and PAD-A/POST comparison, use matched offered loads and independently established productive-role plateaus at both p1 and p32, never a single-connection saturation assertion. Every cell must meet stable-reference parity and:

- `abs(100 * (B_cycles / A_cycles - 1)) <= epsilon_cyc[cell]` (two-sided).
- `100 * (1 - B_rate / A_rate) <= epsilon_rate[cell]`.
- `100 * (B_tail / A_tail - 1) <= epsilon_tail[cell]`, separately for each relevant tail.

Fix the bands before POST, retain individual cells and do not average away losses or widen tolerances. Report cycles/op, instr/op and IPC together (`cycles/op = instr/op / IPC`), rate and p99/p99.9. Exact feature server arguments for mainline, with variables selected from the frozen cell request, are:

```bash
extra=()
if [ "$MODE" = 2s ]; then extra=(--ratio 6:2); fi
taskset -c 0-7 "$ARM" --bind 127.0.0.1 --port 8700 \
  --thread-mode "$MODE" --shards 16 "${extra[@]}" \
  --read-local "$RL" --databases "$DB" --atomic 1 --overlap 1 --reorder 1 \
  --wb-policy 1 --flip-auto 0 --key-lb 1 --client-lb 1 \
  --save '' --appendonly no --enable-debug-command yes
# For each corresponding live read-only battery after the server is ready:
BATTERY_MODE=split
if [ "$MODE" = 1s ]; then BATTERY_MODE=fused; fi
python3 tests/rehash_readonly.py 127.0.0.1 8700 "$BATTERY_MODE" "$RL"
```

| Regime | PRE cycles/instr/IPC, rate, tails | POST cycles/instr/IPC, rate, tails | Verdict for frozen arms |
|---|---|---|---|
| Production benefit from test adaptation | PENDING MAINLINE; unmeasured | PENDING MAINLINE; unmeasured | None expected; identical production code |
| Neutral fixed-table GET | PENDING MAINLINE; unmeasured | PENDING MAINLINE; unmeasured | Performance null discharged by code identity |
| Exercised read-local GET/MGET during rehash | PENDING MAINLINE; unmeasured | PENDING MAINLINE; unmeasured | Performance null discharged by code identity; live correctness pending |
| Possible deficit: expiry/rehash churn | PENDING MAINLINE; unmeasured | PENDING MAINLINE; unmeasured | Performance null discharged by code identity; live correctness pending |

Serverless proof reproduction, without starting a server:

```bash
taskset -c 112-127 make -j16 all build/rehash-waits-unit build/multidb-unit \
  build/core-concurrency-unit build/store-regression build/store-regression-tsan
taskset -c 112-127 ./build/rehash-waits-unit retirement
taskset -c 112-127 ./build/multidb-unit
taskset -c 112-127 python3 tools/probeadapter_proof.py source
taskset -c 112-127 python3 tools/probeadapter_proof.py generate
taskset -c 112-127 make -C build/cleanup-probeadapter/controls/source -f controls.mk -j16
taskset -c 112-127 python3 tools/probeadapter_proof.py run-controls
taskset -c 112-127 python3 tools/ttlstate_proof.py compare \
  build/cleanup-probeadapter/PRE build/cleanup-probeadapter/POST \
  --output build/cleanup-probeadapter/production-comparison.json
taskset -c 112-127 python3 tools/probeadapter_proof.py elf-controls
```

The final artifact manifest contains **19,006 files**. `build/cleanup-probeadapter/ARTIFACT-SHA256SUMS` has SHA-256 **`ca2a5df090d85702178d500e328f006f47fc00193a1d714486251c70d6c9ecee`**; all entries passed `sha256sum -c` (log `verify-artifacts.log`). Re-running generators changes retained proof provenance; deliberately re-freeze the manifest when doing so.

Requested executable hash:

```text
$ sha256sum build/tomokv
ab44f3f0bffcdd97f8e3c4cdc9f83df956bd0b8e3eb2e4981ae08ad6cf9acafe  build/tomokv
```

Requested staging diff, including the inherited launch merge and this report:

```text
 MEASURE-REQUEST-cleanup-probeadapter.md | 193 +++++++++++++++++
 MEASURE-REQUEST-cleanup-readreply.md    | 371 ++++++++++++++++++++++++++++++++
 Makefile                                |   1 +
 src/core/ex_loop.h                      |  63 +++---
 src/store/flatstore.h                   |  84 +++-----
 tests/gate.sh                           |   2 +-
 tests/gate_measurements.json            |   8 +-
 tests/multidb_db0_unit.cc               |   5 +-
 tests/multidb_unit.cc                   |  15 +-
 tests/probeadapter_checks.h             | 160 ++++++++++++++
 tests/rehash_waits_unit.cc              |   6 +-
 tests/rltopo_unit.cc                    | 148 ++++++++++++-
 tools/probeadapter_proof.py             | 311 ++++++++++++++++++++++++++
 tools/readreply_proof.py                | 369 +++++++++++++++++++++++++++++++
 14 files changed, 1635 insertions(+), 101 deletions(-)
```

Lane-only diff against verified launch `origin/cpp` `2a9e48403`, including this report:

```text
 MEASURE-REQUEST-cleanup-probeadapter.md | 193 ++++++++++++++++++++
 Makefile                                |   1 +
 src/store/flatstore.h                   |  84 ++++-----
 tests/multidb_db0_unit.cc               |   5 +-
 tests/multidb_unit.cc                   |  15 +-
 tests/probeadapter_checks.h             | 160 ++++++++++++++++
 tests/rehash_waits_unit.cc              |   6 +-
 tools/probeadapter_proof.py             | 311 ++++++++++++++++++++++++++++++++
 8 files changed, 720 insertions(+), 55 deletions(-)
```
