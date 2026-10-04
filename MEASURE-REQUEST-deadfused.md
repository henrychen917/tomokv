# Lane deadfused — committed cleanup, mainline null pending

The requested dead scheduling/study surfaces are removed on `cx-deadfused`.
The production build and the relevant serverless proofs pass. **Landing still
requires the mainline comparisons and correctness gate below. No performance
result is claimed.** No server, load generator, or gate was started by this lane.
All compilation used `taskset -c 112-127 make -j16`; units and ELF inspection
were also pinned to 112–127. Nothing was pushed.

The first action fetched and fast-forwarded `origin/cpp`: worktree launch
`12fe9f8ad` → cleanup baseline `cd02ecbab1502775f1c170e806971d1f7bbc3ee9`.
Tag **`deadfused-pre-cleanup-cd02ecbab`** protects that baseline. Category commits
are separate; no gaterows landing was assumed. The final production source is
`493bb5b55`; artifact receipts are committed in `d16e22fc1`.

The item disposition and anchors follow. PRE anchors refer to the tagged
baseline; POST anchors refer to this worktree.

| Items | What was wrong in PRE | Change and proof route |
|---|---|---|
| EX11 | `ex_loop.h:184–185,373–676,902–912,3164–3184`: hard-false selectors, uncalled coarse/three-way/pipeline entries, Filler instantiations, submission coalescing, dead handoff alternative | Remove the family, its fields, Filler parameters/bodies in FIFO and R7, the dead pipeline/coalescing constants, and `Ring::take_sq_full_submit` plus its write-only latch. `activate_fused()` binds only the existing owner ring; `handoff_ring()` returns that ring directly. The live baseline entries remain at `ex_loop.h:357,513`. R7 was regenerated with `tests/r7shadow_sync.py --write`. Entire candidate requires the null route, not an identity claim. |
| EX12 | `ex_loop.h:3180–3184`: 128 notification entries although production batches contain at most 32 tasks | `kNotifyBatchMax=kGenthreadExBatchOps`, now 32, at `ex_loop.h:2948`. Retain the full-record safety flush. Serverless 32/33-entry witness and early-flush negative control pass; the mainline MGET8/MSET8 assertion arm is built. |
| EX13 | `ex_loop.h:2483–2510`: unused buffered execute/finish helpers, including the private-queue forwarding trap | Delete both helpers. Neither had a function body in the PRE production symbol inventory. |
| EX14 | `thread.h:686–742`: unused gather-without-retirement / retire-lanes pair | Delete both. PRE symbol inventory is empty for these methods; ThreadCtx size and existing offset locks still compile. |
| EX15 / RL4 | `ex_loop.h:1155–1304`: two-attempt loop with an unconditional assembly jump around the retry; `thread.h:188`, `t_server.cc:2638`: structurally zero retry counter/INFO row | Replace with one capture followed by owner demotion on failure (`ex_loop.h:1015–1143`). Remove the assembly label, retry test hook, counter, INFO aggregation/reset/output. Update `read_local_lane.py`, `bplus.py`, the seeded INFO fixture, and topology fixture in the same commit (`c2ff961ed`). The retry-restored negative control now makes an extra actual capture in the fixture, outside production code; probe counts catch it. |
| EX19 | `atomic_admission.h:14,34–42,64`, `server.h:2648`: uncalled reporting/reconfiguration interface and overwritten 256 initializer | Delete `set_window()`, `Server::atomic_window()`, now-unused credit `window()`, and the 256 initializer. Retain `debt()`: `Server::atomic_credit_debt()` (`server.h:3180`) calls it and INFO emits it (`t_server.cc:2326,2443`). Keep the credit accounting and concurrent admission tests; retire only reconfiguration tests for the removed API. Credits remain 8 bytes. |
| RL2 | `ex_loop.h:53,71,1949–1951`: constant claimed dead by the report, but this merged baseline actually uses it to run one local quantum | Delete the constant/assertion and spell the single `drain_local_reads_bounded` call directly (`ex_loop.h:1791`). No scheduling ratio changes. |
| RL8 | `flatstore.h:88–98,3460–3479`: unbuilt reclaim-prefetch `-D` arm | Delete macro/default/validation/constexpr and disabled prefetch block. The sized free remains. |
| WB13 | `wb.h:222–281`: three unused `prepare_pipeline*` entries | Delete entries and TLS fixture arm 3. Preserve ordinary prepare APIs and their submit-allowed contract. All 720 remaining writeback cases pass. |
| CT15 | `flipctl.h:263`: unused double in a report returned by value | Delete it. Report size drops 360→352; all eight required layout locks remain intact. Controller unit and exact INFO wire fixture pass. |

The two-FIFO reorder implementation and `ex_schedule_batch` remain. Its two
legacy queue-size assertions retain the same accepted values (32 or 128), using
literal 128 for the existing unit geometry after deleting the dead production
preset name. No RO7/RO8 mechanism or phantom metadata row was removed. KEEP
constants remain. EX17's separate `retired_reorder_padding_` byte remains; the
requested EX25 fused size lock was added.

The notification bound is about **tasks, not keys**. The only remaining
`NotifyBatchScope` is inside `exec_batch_prefetched` (`ex_loop.h:2243–2275`),
and its live callers gather/emit at most 32 tasks. Each ordinary task can append
one remote notification; local completions append none. A scatter fragment that
queues a commit returns before notification (`ex_loop.h:2461–2467`). Its commit
notifications are drained by `flush_xshard_commits` (`ex_loop.h:2738`) after the
execution scope has closed. Eight keys therefore do not require eight slots per
executed task. Reclamation is also outside that scope. The 33rd-entry safety
path is retained and tested. Actual MGET8/MSET8 p32 traffic with atomic commits
is still an explicit mainline proof obligation, not a completed live result.

| Size, in both namespaces | PRE | POST | Delta |
|---|---:|---:|---:|
| ExLoop | 5856 | 5848 | −8 |
| FusedExLoop | 6632 | 5856 | −776 |
| ReadLocalStats | 328 | 320 | −8 |
| ReadLocalThreadState | 384 | 376 | −8 |
| FlipctlReport | 360 | 352 | −8 |
| INFO StatBaseline | 488 | 480 | −8 |

`static_assert(sizeof(ExLoop)==5848)` and the new
`static_assert(sizeof(FusedExLoop)==5856)` are at `ex_loop.h:2990–2991`.
[layout.json](docs/deadfused/layout.json) records GDB type inspection of PRE and
POST, without starting either binary, including both `tomo` and `tomo_db0`.
The eight required sizes remain **336 / 1984 / 1408 / 1440 / 944 / 192 / 144 /
624** for Op / Client / ThreadCtx / Shard / FlatStore / Rob<64> / AtomicEntry /
Config. Ring remains 328, IoLoop 7144, FlipController 1752; Server remains
108672 in `tomo` and 108288 in `tomo_db0`. No owner/reader protocol or ownership
critical section was changed.

The cycles/op argument is deliberately a null argument. Uncalled template
entry deletion removes zero executed loads, stores, branches, allocations, or
RFOs per operation. The smaller notification array removes 768 bytes of
per-fused-owner storage and constructor clearing, with the same live record
loads/stores and fences. The hardwired ring removes an indirection where the
handoff accessor is evaluated, and the unread SQ-full latch removes a store on
a full-SQ flush; these are not one-per-command effects. The single MGET capture
removes the explicit demotion jump/retry scaffolding on failed captures; the
successful-read algorithm is unchanged. The retired INFO row removes one
counter's aggregation/reset/formatting work per INFO operation. Counter/report
layout changes and compiler decisions can affect placement and cache lines.
**No per-op RFO reduction or throughput gain has been measured.** Report rate
at matched offered load, cycles/op, instructions/op and IPC together:
`cycles/op = instructions/op / IPC`. Do not use instruction counts alone or
idle-spin counts to accept this cleanup.

| Static receipt | PRE | POST | Verdict |
|---|---:|---:|---|
| `.text` bytes | 7,729,345 | 7,728,961 | −384; bytes differ |
| Defined function-table entries | 10,240 | 10,242 | Compiler output changes; fewer source lines do not imply fewer emitted bodies |
| Uncalled deleted-method inventory | No emitted bodies for all ten inventoried names | Deleted | Absence proof only |
| Final documentation-only rebuild | Earlier POST | Final POST | Executable sections and entire function address/size table identical |

[identity.json](docs/deadfused/identity/identity.json) contains literal section
hashes/addresses, with compressed complete function and section tables beside
it. The intermediate scheduler build has its own receipt. **PRE→POST is not
byte-identical.** No relocation-masked disassembly is represented as literal
identity. This applies to the combined cleanup; no category is exempted from
the mainline null on the strength of a source-only deletion.

PAD-A is **kind A: PRE observable command/INFO behavior at POST's layout**.
The scheduling changes remove unreachable behavior, so their live command
behavior is already shared. The externally visible difference is the removed
zero INFO row. `tools/deadfused_artifacts.py pad` restores that row as a literal
zero in a copied format string, using two same-width cmd_info address loads
(one per production namespace). It appends a read-only PT_LOAD by repurposing
a PT_NOTE slot; it adds no executable section and changes no function or
existing section address, size, or alignment. No patch label or retry arm is
added to production. The ASAN unit twin demonstrates that the restored format
is mapped and actually emitted; the unmodified unit fails that same assertion.

[PAD proof](docs/deadfused/pad-a/proof.json) records **10,242/10,242 identical
function entries**, equal complete section tables, the two planned instruction
retargets plus one program-header change, and restoration of every other
original byte. Missing-retarget, moved-symbol and unrelated-byte controls are
all rejected. The unit twin has the same independent controls.

This is a **null-only twin**, with no independent hot-path treatment. It does
not reconstruct PRE's instruction schedule or PRE's larger object sizes; that
would contradict the selected POST layout. It cannot attribute a speedup to a
mechanism or excuse a regression as placement. Any result outside the
predeclared two-sided null requires reworking the source/layout or reverting
the affected category, then rebuilding and remeasuring. No PAD-B is supplied.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/deadfused/PRE` | `bb7b05bfbf0face9d2c6bdbbe76297048ac9bcbf60b929f488c7819193a8f900` |
| POST | `build/deadfused/POST` | `78a4c8355a1bccb65cbfdbbf0b46c176583d3556a1beeb5d10607755501f2297` |
| PAD-A | `build/deadfused/PAD-A` | `742fcc9774a0fb2901948f592810fb1cf356626e0f82e3a5621518f9acb10bed` |
| POST-NOTIFY-BOUND | `build/deadfused/POST-NOTIFY-BOUND` | `036c4a012fe8e44a9c369c785b49bc14c0fae22a3f7eaa79d195ebc37e80aa64` |

`build/tomokv` is POST. The overflow-aborting arm is diagnostic only: it replaces
just the overflow flush at `ex_loop.h:2776` with abort in a throwaway source
copy. Its exact overlay is [notify-bound.patch](docs/deadfused/notify-bound.patch).
Do not use its performance to judge the cleanup.

| Verification run on 112–127 | Result / receipt |
|---|---|
| Production, both compiled database variants | Build passes; `final-build.log.gz` |
| Atomic admission accounting/concurrency | `waits-unit.log`: PASS |
| Flip controller state machine | `flipctl-unit.log`: PASS |
| Flip report exact wire fixture | `flipreport-unit.log`: PASS |
| Plain/kTLS/userspace TLS writeback | `writeback-unit.log`: 720 cases PASS; removed arm was test-only |
| Real topology demotion and arm-transient witnesses, 1s and 2s, ASAN/UBSAN | `rltopo-1s.log`, `rltopo-2s.log`: PASS, including designated failing controls |
| Notification record, both modes | `notify-bound-unit.log`: 32 held, 33rd flushes, tail published; forced early flush rejected |
| INFO aggregate/reset/increment/saturation | `info-unit.log`: 38 surviving counters, databases 1 and 4; retired retry row absent |
| PAD INFO fixture | `info-pad-unit.log`: exactly one PRE zero retry row, database counts 1 and 2 in the general runtime; both production namespaces also covered by the ELF retarget inventory |
| Python lane/fence replays | `python-checks.log`: transient, delayed-drain, p8/p32 held-fence pass; old fence, never-opened window and stale RYOW controls fail at their designated assertions |
| Reorder differ | Self-checks pass; a missing POST symbol raises even in report-only mode. Signature correspondence removes only false coalescing and void filler arguments; it does not normalize changed instructions. |
| R7 generator / shell syntax / whitespace | Current envelopes, `bash -n tests/gate.sh`, `git diff --check` pass |

An initial build exposed one more obsolete `set_window` test; that removed-API
race was retired, and the repaired build/tests above passed. A Python CLI help
probe treated `--help` as a hostname and failed at name resolution before any
connection; subsequent Python checks used mocked serverless replays only.

Reproduce the offline receipts and focused checks from this worktree:

```sh
taskset -c 112-127 make -j16 all build/waits-unit build/flipctl-unit build/netcmd-unit build/rltopo-unit build/core-concurrency-unit
taskset -c 112-127 python3 tests/deadfused_checks.py
taskset -c 112-127 python3 tests/r7shadow_sync.py
taskset -c 112-127 build/waits-unit
taskset -c 112-127 build/flipctl-unit
taskset -c 112-127 build/netcmd-unit output
taskset -c 112-127 build/rltopo-unit 1s
taskset -c 112-127 build/rltopo-unit 2s
taskset -c 112-127 build/core-concurrency-unit deadfused-notify
taskset -c 112-127 build/core-concurrency-unit lanefull-info
taskset -c 112-127 build/core-concurrency-unit flipreport-wire
taskset -c 112-127 python3 tools/deadfused_artifacts.py compare build/deadfused/PRE build/deadfused/POST build/deadfused/recheck
taskset -c 112-127 python3 tools/deadfused_artifacts.py pad build/deadfused/POST build/deadfused/PAD-A build/deadfused/pad-recheck
```

The two existing topology gate rows remain at `tests/gate.sh:1290–1299`, before
the quick exit at **3039**. Writeback still runs under its existing netcmd output
row; removing an internal template arm is not a gate-row retirement. The new
notification/PAD-specific selections are manual serverless witnesses, not new
gate emissions. `reorder_noop.py` is not directly invoked by this launch's gate;
its historical default count of 169 has not been broadened to make this
non-identical cleanup pass. R7 source sync is regenerated locally, without
relying on gaterows3. **Row delta: quick +0, full +0. EXPECT_QUICK=473 and
EXPECT_FULL=490 remain untouched.**
`tests/fixtures/nullrefresh-ledger-labels.json` is unchanged. The live lane and
B+ consumers and the seeded INFO fixture changed in the INFO deletion commit;
none may silently parse a missing retry counter as zero.

The following is the **mainline-only measurement request; NOT RUN**.

Use `/home/user/Projects/cx-final`'s gate instrument and current trusted null /
confirmation policy. Freeze the instrument digest, exact binary hashes,
geometry, offered load, valid calibration/plateau evidence and per-cell
rate/cycles/tail bands before scoring POST. Compare **PRE↔POST, PRE↔PAD-A,
PAD-A↔POST**, with identical workload input and offered loads, interleaved
ABBA/BAAB visits. Also compare the integrated candidate to the newest headline
at landing; if mainline has advanced, merge/rebuild the arms and receipts on
that exact source before crediting an integration result.

The exact mainline **14-cell** null file is
[generic-merit-cells.txt](docs/deadfused/generic-merit-cells.txt), SHA-256
`de0e56e4696f780543c5adea21aa7d7283c12fa22110be6064370a69a2a68dc6`:
`h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`.
Preserve its pins, depth-1 exemption, 20-second windows, 2M keys, 512 total
connections, 64-byte values except v1g's 1024, uring, atomic=1, overlap=1,
reorder=0, default balancers and disabled save. Use server cores 0–31 and load
cores 32–111, no SMT; retain the gate's 256-shard headline geometry and h05's
eight load instances. Do not substitute the correctness geometry for these
frozen cells.

For example, the maintainer can run one comparison as follows, then repeat
with PRE/PAD-A and PAD-A/POST using distinct output directories:

```sh
cd /home/user/Projects/cx-final
deadfused_lane=/home/user/Projects/cx-deadfused
python3 tests/abbagate.py --subset full --build-reference 0 \
  --cells "$deadfused_lane/docs/deadfused/generic-merit-cells.txt" \
  --reference-binary "$deadfused_lane/build/deadfused/PRE" \
  --candidate-binary "$deadfused_lane/build/deadfused/POST" \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --ports 7951-7958 --port 7951 \
  --output "$deadfused_lane/build/deadfused/mainline-pre-post"
```

[feature-cells.txt](docs/deadfused/feature-cells.txt) contains 32 additional
parse-validated definitions: split controls
`h17,h18,h21,h22,h25,h26,h29,h30,h49,h50,h57,h58`; sixteen
`df_{1s,2s}_l{0,1}_o{0,1}_{mget,mset}32` cells; four
`df_{1s,2s}_l1_o{0,1}_mix8_128` cells. These use the existing eight-key MGET/MSET
and MIX8 workloads, atomic=1, reorder=0 and 512 connections. Calibrate valid
pins separately; no absent pin is silently replaced by a guessed rung.

| Required regime | Cells / actual state to witness | Decision |
|---|---|---|
| Neutral | 14-cell null and split GET/SET controls; stationary owners; read-local-off arms explicitly included | Every pair stays inside the predeclared two-sided rate/cycles/tail null; no gain required |
| Exercised cleanup | Sixteen p32 MGET8/MSET8 cells, both modes, overlap 0/1, read-local 0/1, atomic=1 | Null plus correct replies and progress; run POST-NOTIFY-BOUND separately on these shapes and require no abort, nonzero commands and atomic commit activity for writes |
| Possible deficit | Four MIX8 p128 cells; read-local armed, atomic=1; separately repeat with actual key/client moves and forced FLIP progress at correctness geometry | Null, untorn replies/RYOW, bounded drain and completed movement; require demotion/movement witnesses, bounded fresh-state rearming, then FAIL if the intended window never opens |

The feature/deficit correctness geometry is **8 physical server cores,
16 shards, 6 IO + 2 EX for 2s**, and eight fused workers for 1s. Keep measurements
at the headline geometry separate from repetitions at correctness geometry;
calibration does not transfer between them. For movement/FLIP use the existing
gate batteries' directed schedules and external drivers. The cell file alone
does not inject a FLIP or guarantee a conflict; mainline must retain those
witnesses rather than labelling unentered traffic as exercised. Run both
`--databases 1` and a multi-database boot for the correctness gate and INFO
compatibility fixtures. At minimum preserve the ordinary `tests/gate.sh iteration` mode/read-local/atomic coverage on POST.
The PAD intentionally retains the old INFO schema, so do not feed it to POST
assertions that require that row to be absent; its dedicated INFO fixture
checks the restored schema instead.

For each cell and regime report PRE, POST and PAD-A rate, cycles/op, instr/op,
IPC, p99/p99.9, within-arm spread, validity and trust. Rate-capped diagnostics
must use a common achieved load; idle-spin-heavy whole-server instruction
counts cannot resolve a small per-op improvement. Keep invalid/noisy visits
and use the standing confirmation policy. Do not average a losing cell into
another cell's gain or widen a band after observing POST. The overflow-aborting
arm supplies correctness evidence only. An abort rejects EX12; a missing
window rejects the test; any persistent out-of-null result rejects the cleanup
as currently built. Append raw paths, hashes and the decision to
`MEASURE-RESULT-deadfused.md` before landing.

| Requested comparison | Rate / cycles/op / IPC / instr/op / tails |
|---|---|
| PRE vs POST, 14 null cells and three regimes | PENDING MAINLINE |
| PRE vs PAD-A, same cells/regimes | PENDING MAINLINE |
| PAD-A vs POST, same cells/regimes | PENDING MAINLINE |
| MGET8/MSET8 overflow-aborting diagnostic | PENDING MAINLINE |
| Integrated candidate vs newest headline; iteration gate | PENDING MAINLINE |

The cleanup-only diff from the post-merge launch baseline follows. The literal
pre-fetch launch diff (`git diff 12fe9f8ad --stat`), which also includes the
required upstream merge, is recorded separately in
[diff-from-launch.stat](docs/deadfused/diff-from-launch.stat).

```text
 MEASURE-REQUEST-deadfused.md                       | 362 +++++++++++
 docs/deadfused/SHA256SUMS                          |   6 +
 docs/deadfused/arms.json                           |  26 +
 docs/deadfused/bound-build.log.gz                  | Bin 0 -> 1491 bytes
 docs/deadfused/cell-parse.log                      |   2 +
 .../comment-identity/POST-functions.tsv.gz         | Bin 0 -> 151644 bytes
 .../comment-identity/POST-sections.tsv.gz          | Bin 0 -> 740 bytes
 .../comment-identity/PRE-functions.tsv.gz          | Bin 0 -> 151644 bytes
 .../deadfused/comment-identity/PRE-sections.tsv.gz | Bin 0 -> 740 bytes
 docs/deadfused/comment-identity/identity.json      | 130 ++++
 docs/deadfused/diff-from-launch.stat               | 214 +++++++
 docs/deadfused/feature-cells.txt                   |  33 +
 docs/deadfused/final-build.log.gz                  | Bin 0 -> 1408 bytes
 docs/deadfused/flipctl-unit.log                    |  23 +
 docs/deadfused/flipreport-unit.log                 | 707 +++++++++++++++++++++
 docs/deadfused/generic-merit-cells.txt             |  14 +
 docs/deadfused/identity/POST-functions.tsv.gz      | Bin 0 -> 151644 bytes
 docs/deadfused/identity/POST-sections.tsv.gz       | Bin 0 -> 740 bytes
 docs/deadfused/identity/PRE-functions.tsv.gz       | Bin 0 -> 151683 bytes
 docs/deadfused/identity/PRE-sections.tsv.gz        | Bin 0 -> 738 bytes
 docs/deadfused/identity/identity.json              | 130 ++++
 docs/deadfused/info-pad-unit.log                   |   2 +
 docs/deadfused/info-unit.log                       |   3 +
 docs/deadfused/layout.json                         | 128 ++++
 docs/deadfused/notify-bound-unit.log               |   3 +
 docs/deadfused/notify-bound.patch                  |  11 +
 docs/deadfused/pad-a/PAD-A-functions.tsv.gz        | Bin 0 -> 151644 bytes
 docs/deadfused/pad-a/PAD-A-sections.tsv.gz         | Bin 0 -> 740 bytes
 docs/deadfused/pad-a/POST-functions.tsv.gz         | Bin 0 -> 151644 bytes
 docs/deadfused/pad-a/POST-sections.tsv.gz          | Bin 0 -> 740 bytes
 docs/deadfused/pad-a/negative-controls.json        |  17 +
 docs/deadfused/pad-a/planned-retargets.json        |  37 ++
 docs/deadfused/pad-a/proof.json                    |  39 ++
 docs/deadfused/post-build-repaired.log.gz          | Bin 0 -> 1392 bytes
 docs/deadfused/pre-build.log.gz                    | Bin 0 -> 1408 bytes
 docs/deadfused/python-checks.log                   |  30 +
 docs/deadfused/r7-sync.log                         |   1 +
 docs/deadfused/rltopo-1s.log                       |  92 +++
 docs/deadfused/rltopo-2s.log                       |  92 +++
 docs/deadfused/scheduler-build.log.gz              | Bin 0 -> 1408 bytes
 .../scheduler-identity/POST-functions.tsv.gz       | Bin 0 -> 151555 bytes
 .../scheduler-identity/POST-sections.tsv.gz        | Bin 0 -> 744 bytes
 .../scheduler-identity/PRE-functions.tsv.gz        | Bin 0 -> 151683 bytes
 .../scheduler-identity/PRE-sections.tsv.gz         | Bin 0 -> 738 bytes
 docs/deadfused/scheduler-identity/identity.json    | 130 ++++
 docs/deadfused/source-receipt.json                 |  14 +
 docs/deadfused/unit-negative-controls.json         |  10 +
 docs/deadfused/unit-pad/PAD-A-functions.tsv.gz     | Bin 0 -> 113809 bytes
 docs/deadfused/unit-pad/PAD-A-sections.tsv.gz      | Bin 0 -> 770 bytes
 docs/deadfused/unit-pad/POST-functions.tsv.gz      | Bin 0 -> 113809 bytes
 docs/deadfused/unit-pad/POST-sections.tsv.gz       | Bin 0 -> 770 bytes
 docs/deadfused/unit-pad/negative-controls.json     |  17 +
 docs/deadfused/unit-pad/planned-retargets.json     |  28 +
 docs/deadfused/unit-pad/proof.json                 |  39 ++
 docs/deadfused/waits-unit.log                      |   1 +
 docs/deadfused/writeback-unit.log                  |   3 +
 src/cmd/t_server.cc                                |   6 -
 src/core/atomic_admission.h                        |  15 +-
 src/core/ex_loop.h                                 | 515 ++++-----------
 src/core/flipctl.h                                 |   1 -
 src/core/genthread.cc                              |   2 +-
 src/core/genthread_pipeline.h                      |  12 +-
 src/core/reorder.cc                                | 111 +---
 src/core/reorder.h                                 |   4 +-
 src/core/rl2s.cc                                   |   2 +-
 src/core/server.h                                  |   3 -
 src/core/thread.h                                  |  73 +--
 src/net/uring.h                                    |  13 -
 src/net/wb.h                                       |  24 -
 src/store/flatstore.h                              |  28 +-
 tests/bplus.py                                     |   6 +-
 tests/core_concurrency_unit.cc                     |  52 +-
 tests/deadfused_checks.py                          |  50 ++
 tests/l4prebuild_unit.cc                           |   1 -
 tests/lanefull_checks.inc                          |  25 +-
 tests/multidb_boundary_unit.cc                     |   2 +-
 tests/overlap_prefetch_unit.cc                     |   1 -
 tests/r7shadow_sync.py                             |   2 +-
 tests/read_local_lane.py                           |   8 +-
 tests/reorder_engagement_unit.cc                   |   1 -
 tests/reorder_noop.py                              |  23 +-
 tests/rltopo_unit.cc                               |  12 +-
 tests/tlsserve_checks.inc                          |  14 +-
 tests/waits_unit.cc                                |  34 +-
 tests/wb_rule_phase_unit.cc                        |   1 -
 tools/deadfused_artifacts.py                       | 182 ++++++
 86 files changed, 2873 insertions(+), 694 deletions(-)
```
