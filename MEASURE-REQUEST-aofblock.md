## aofblock

S1 patch against `7595a6705`, branch `cx-aofblock`. No push. Correctness boots use
`LC_ALL=C`, CPUs 56–83 and ports 25800–25899. The complete external analysis and
`phase_b.py`, `fsyncdelay.c`, and the reproduction's result summaries were read.

Implemented: blocking completion ownership and the bounded final AOF shutdown
wait. Confirmed but left for the owner's design decision: EXEC with publication
or subscription and FUNCTION registry mutations. Their code is unchanged.

Final state (takeover after the content-filter stop, 2026-11-08):

* The production code is bdf0e528af + 56a21e5541 + 42b6405018 (Makefile).
  `src/` and the Makefile are identical from bab542a664 to the branch tip.
* The unreviewed WIP 6a84de0e69 was reverted (bab542a664); the reasons are below.
* The rows are unchanged: **+36 quick / +36 full, so EXPECT_QUICK 1248 and
  EXPECT_FULL 1265**.
* The merit arms are in `/home/user/Projects/bins/`, with SHA-256 under
  "Measurement request".
* Final receipts are under "Final receipts", and what was not run is under "NOT RUN".

### Blocking completion ownership

The proposed Free comparison is necessary, but is not sufficient on its own.
The production diff is one changed CAS initializer plus three cancellation lines.

| Path / invariant | Current-tree evidence |
|---|---|
| Actual initial state | `src/exec/op.h:103` resets Free. The only production Issued store is the temporary withheld-EXEC shutdown marker, `src/core/shutdown.cc:161`; blocking dispatch does not store Issued. |
| Exactly one reply producer | `src/cmd/blocking.inc:990` claims a timeout from Parked; group removal, wake selection, probe completion and registration use phase CASes at `1026`, `1142`, `1209`, `1248–1280`. Registration OOM claims Registering at `759`. A failed claim does not compose a second reply. |
| Last active task vs registry wake | `blocking_task_done:525` uses the final active_tasks fetch_sub. `blocking_publish_completion:722` publishes Completed, then tests active_tasks. Both can offer the same completed Op; for overlapping offers `src/persist/aof.cc:3032` now claims Free→AofWait exactly once. An offer observing AofWait or Done returns handled without another enqueue/notify. The decision itself is a store→load pair that predates this lane; see "Open for the owner: blocking completion offer races". |
| Cancellation after a mutation | `blocking_task_done:527` can see cancel_requested after the pop and select `blocking_finish_cancelled`. That function's old load-AofWait / exchange-Done pair had a TOCTOU against another offerer. Its owner-side completion now goes through the same AOF claim at `blocking.inc:515`. This is why the one-liner alone is unsafe. |
| Cancellation without an owner | `blocking_cancel_client:1886–1892` permits the null-self path only for exclusively handed-over MoveRequested/RemapRequested, with zero active tasks. It cannot race a direct pop or an AOF completion. |
| Timeout / wrong type / OOM / missing group | The owner-side helpers `blocking.inc:739–763`, timeout claim `990–995`, and group-removed completion `1026–1042` converge on the same publication function. Only the selected phase owner writes the reply. |
| Cleanup during AofWait | `blocking_cancel_client:1873` requests cancellation and wakes registry owners; it does not force Done. `honour_cancel:1060–1070` only claims a live phase. Registry removal `1083–1088` drops its alias reference. The Op retains its separate reference through `blocking_retire:1910–1948`. `src/net/rob.h:761` refuses to retire anything but Done. |
| Exclusive IO move/remap exits | `blocking.inc:1719–1741` and `1784–1817` require the owner hand-off / zero active task barrier. These are pre-mutation routing, timeout, ACL and error exits; the transferred BLMOVE/BRPOPLPUSH mutation still uses scatter completion. They have one IO completer and never own a pending AOF entry. |
| Exactly one durability release | `aof.cc:3115–3122` detaches the completion batch before storing Done and notifying, so reentrant retirement cannot invalidate a still-linked queue entry. |

No indefinite empty-record wait is introduced. `defer_completion` is limited to
Always and write/snapshot-write/multi operations. `finish_completions:3060–3104`
publishes a producer's existing generation and snapshots remote generations once;
it does not require a new record for an error or timeout. `ex_loop.h:1902–1921`
services completion queues even when there is no staged record. A zero target is
ready immediately; a nonzero target waits for its finite publication/durability
dependencies. AOF failure under Always is fatal, not an unfinishable success queue.
Read-only XREAD and pre-dispatch syntax errors retain their existing behavior.

`tests/persistfix_unit.cc` adds a Free-state competing-offerer schedule: exactly
one queue owns the Op, an unpublished dependency and an undurable target hold it,
AofWait/Done duplicates are absorbed, and the eventual notification fires once.
The existing counted persistence-unit row now includes this case. The live rows
also exercise timeout, wrong type, CLIENT UNBLOCK and disconnect cleanup. The
ACK_WINDOW hook runs at `ex_loop.h:1904`, after command completion offered its
receipt and before producer posting, so cancellation in that held POST window
really occurs while the Op is in AofWait.

### WIP 6a84de0e69: reverted by bab542a664

The lane stopped on a false content-filter flag. Its retry wrapper then
committed unreviewed edits to `src/cmd/blocking.inc` and
`tests/blockfix2_unit.cc` as 6a84de0e69. Verdict: **reverted with a new commit, not kept**.
After the revert, `src/` and `tests/` are byte-identical to 1552561cb0.

What it addressed. The lane's final lifetime review found that the decision to
offer a completion is not race-free. `blocking_publish_completion` stores
Completed (`blocking.inc:724`) and then loads active_tasks (`:729`).
`blocking_task_done` decrements active_tasks (`:525`) and then loads the phase
(`:526`). The WIP replaced this with a ready bit inside active_tasks. It counted
every registry visit as a participant, gave every offer to the last
participant, and added a RemapPending phase so that remap hand-off follows the
same rule. It also captured `server`/`client` before publishing Done. The race
is real; it is described with a smaller design below.

Why it was reverted:

| Question | Finding |
|---|---|
| Within this S1 scope? | Not the durability defect. The race exists unchanged in 7595a6705 and in the release binary, where `exchange(Done)` is the claim. The AOF fix neither introduces it nor widens it. Under `appendfsync always` the first offer's Done waits for an fsync, so a late second offer is, if anything, less likely. It is a separate S1-class finding. Under the owner's 10-09 rule it is flagged, not fixed, and under the 10-11 rule a protocol change is the owner's decision. |
| Correct and complete? | No. `src/cmd/flip_liveness.inc:188-189` still requires `active_tasks == 0` for a MoveRequested waiter. With the WIP every MoveRequested state carries the ready bit, so `Client::flip_stationary_idle()` could never be true for it. Suppose a FLIP has acknowledged IoDrain and then receives a MoveRequested hand-off for a client that stays. Its ClientInstall acknowledgement still requires `flip_io_drained()` (`io_loop.h:2574`), so it could no longer drain, and `flip_blocked_dispatch_allowed()` keeps that move from resuming until Idle. |
| Tested? | No. The transcript shows no build after the edits, and the unit hook covers one schedule. Keeping it would also have invalidated the xshard.o symbol and instruction proofs: blocking.inc is compiled inside xshard.cc under a pinned inline budget. |
| Lost wake or stranded waiter after a remap? | None, with or without the WIP. A remap that still finds a pending alias or task is retried, because a blocked client never leaves its IO's active set (`io_loop.h:4997-5007`): it is re-polled every IO pass and at least every 50 ms by the park net (`park_net.h:27`). A re-parked move scatter (`scatter_engine.inc:4394/4417/4530`) re-parks instead of completing, so a RemapRequested Op never owns a pending AOF entry. |

### Open for the owner: blocking completion offer races

These are pre-existing. They were found by code review and **not reproduced**,
and no code change is included.

| Finding | Where (final tree) | Consequence | With `appendfsync always` |
|---|---|---|---|
| (a) Offer decision is a store→load pair on two atomics (a Dekker pattern) | `blocking.inc:724/729` against `:525/526`; `honour_cancel` CAS then load at `:1065-1069` | **Two offers:** a delayed second offer can arrive after the IO retired the Op, and then completes whatever Op `rob().at(op_id)` names: a wrong reply. **No offer:** the C++ model permits it, and on x86 the publisher's plain store can sit in its store buffer while the task's locked decrement and phase load run. The popped element then stays in an unpublished reply and the client hangs. `honour_cancel` uses a locked CAS, so on x86 only its double offer applies. | Reachable. The deferred path only narrows the late-offer window. |
| (b) BlockingState is read after Done | `blocking.inc:539-540`, `:735-736`, `:518-520` | `*state.server` and `state.client` are read after the IO may have retired the Op and freed the state. A pop served on arrival has no registry alias, and the timeout sweep drops its alias (`:994`) before publishing (`:995`). The MovePending branch (`:546-547`) and the scatter engine (`scatter_engine.inc:4542-4543`) already capture these before publication. | Not reachable for deferred completions: `finish_completions` stores Done and notifies with a captured Client. |

Smaller candidate fix, cold blocking code only:

* For (a), count each offerer as a participant, exactly as `blocking_request_move`
  (`:713-720`) already does for MovePending: `fetch_add(1)` before storing
  Completed or Cancelled, then finish through `blocking_task_done`. The single
  final `fetch_sub` on one word picks exactly one offerer, and its release
  sequence makes the phase store visible to that offerer. No new bit is needed,
  so `flip_liveness.inc:189` and `blocking_namespace_quiesced` stay unchanged.
* For (b), capture `server` and `client` before publishing Done, as the
  MovePending branch does.
* Before landing: a deterministic unit schedule with a hook between the phase
  store and the participant decision (the WIP's `TOMO_BLOCKING_COMPLETION_UNIT`
  hook is a starting point), the blocking rows, a re-derived xshard inline
  budget, and a fresh symbol and instruction audit.

### Counted crash witnesses and landing count

`tests/aofblock.py` owns every listener and fresh crash-image directory through the
existing persistfix identity checks. It selects a non-writer owner and an independent
IO thread; it fails if the hook never opens or opens on the wrong owner. No shim is
used in counted rows. Each row first kills inside the hand-off window and verifies
the old crash image, then releases a fresh held mutation, waits for its exact reply,
kills immediately, and verifies recovery did not lose or redeliver that mutation.
For XREADGROUP the assertion includes one PEL delivery and no delivery to a new
consumer. Seed writes are acknowledged before arming the window.

Nine cases × two thread modes × two engines = **+36 quick / +36 full**:
BLPOP on arrival and wake, BRPOP, BLMPOP, BZPOPMIN, BZPOPMAX, BZMPOP, XREADGROUP
BLOCK on arrival and wake. `job_aofblock` is declared at `tests/gate.sh:5668`, and
its engine jobs are collected at **line 7440**, before the quick exit at **7500**.
The landing counts should be **EXPECT_QUICK 1248** (1212 + 36) and
**EXPECT_FULL 1265** (1229 + 36). Neither constant nor the reviewed fixture was
edited. The 36 source-declared labels are in `docs/aofblock/new-labels.json`.

All 36 release rows fail for the intended reason: an acknowledged mutation was
rolled back after the in-window SIGKILL, not a boot/arming failure. See
`docs/aofblock/release-rows.json` and `build/gate-run.xNRTsk`. The final compiler-pinned POST passes
**36/36**, including cancellation/disconnect while AofWait holds the Op
(`build/gate-run.45LLwe`, `docs/aofblock/post-rows.json`). The exact-layout PAD-A also fails all 36 rows
(`build/gate-run.4LKkhW`), and restores the slow-shutdown abort.

Final re-run (takeover, final `tests/aofblock.py`, gate job interface):

* Final POST e25f8b6f: **36/36 PASS** (`build/gate-run.oh0PLx`,
  `docs/aofblock/final-post-rows.json`).
* Release binary 0de6bbde: **36/36 FAIL**, every one with "acknowledged mutation
  was rolled back by in-window SIGKILL" (`build/gate-run.iQHMq9`,
  `docs/aofblock/final-release-rows.json`).

The lane's earlier release run predates 42b6405018, which added the
cancel-during-AofWait checks to the rows; this re-run uses the final row code.

### Other S1 causes: confirmed; design for owner decision

The marker-driven preloaded-gate test is `tools/aofblock_order.py`, with
`tools/aofblock_fsyncdelay.c`. It holds fsync 1, verifies an independent PING is
braked by the older send target, issues the subject, releases fsync 1, observes
fsync 2 held, and observes PING released. A subject reply at that point is early.
Masked arming is retried on a fresh server, bounded at eight attempts; exhaustion
fails. No tolerance is widened and no unarmed case passes. The tool also runs
the nine blocking cases of the counted rows, reusing `tests/aofblock.py`'s
`plan()`. There it is the analysis's preloaded-gate reproduction of the fixed
defect: PRE must be early and POST must hold the reply until fsync 2. Before
arming, those cases wait for a plain SET under `always`, so no setup record
can shift the sync numbering. Results are under "Final receipts".

PRE confirmed every case in both 1s and 2s under epoll (14/14):

| Operation | Result with subject fsync held |
|---|---|
| EXEC with SET + PUBLISH | Early EXEC reply |
| EXEC with SET + SPUBLISH | Early EXEC reply |
| EXEC with SET + SUBSCRIBE | Early EXEC reply |
| FUNCTION LOAD | Early library-name reply |
| FUNCTION DELETE | Early OK |
| FUNCTION FLUSH | Early OK |
| FUNCTION RESTORE | Early OK |

Receipts: `docs/aofblock/other-s1-confirmations.json`. The external release was
also reproduced; the final complete 14-case matrix used `build/aofblock/PRE`.
The uring submit shim also delays reaping the previous sync, so it is not a valid
discriminator for this stale-target schedule. Those ordering results are explicitly
epoll-only, not evidence of absence under uring.

EXEC: `multi_execute.inc:243–314` emits/commits the AOF group before finalized;
`327–347` waits for all owner tasks then queues an IO continuation instead of
returning Final when has_publication is set. Consequently the ordinary executor
AOF-completion call is bypassed. `multi.inc:3106` and `3141` directly publish Done
from the IO after subscription/publication work. A bare defer_completion call at
those stores is insufficient: split IO has no `ExLoop::aof_flush_pass` to drain
that producer's completion queue. Holding only the final reply also allows the
publication side effect to escape before the transaction is durable.

A small local_ack/requeue guard was investigated, but is not landed: the existing
retry node is an execution/rebuild continuation, counts requeue as runnable work,
and would continuously spin the IO throughout a slow fsync. It does not add the
needed persistence wake, stop/drain and continuation lifetime protocol. This is
not treated as an acceptable release fix merely because it delays one test reply.

Proposed EXEC design: after all owner references retire and receipt publication
is complete, retain the finalized MultiExecState as a *durability continuation*.
Use the existing client receipt (`AofManager::local_ack`, `aof.cc:2262`) as the
condition, register the owning IO's existing AOF wake bit, then recheck before
parking. Once durable, enqueue its existing IO continuation exactly once; only
then perform pub/sub effects and eventually Done. Cancellation/close must keep
the state and Client pinned until the queued continuation or shutdown drain
consumes them. Writer failure must use the existing Always failure path. The new
state belongs in cold multi/AOF storage, leaving the fixed object layouts and
ordinary command dispatch unchanged. Add a durability-held continuation unit and
a counted no-shim group hand-off witness before landing it.

FUNCTION: `functions.cc:1087` appends the full registry journal while holding its
mutex, before publishing the generation. It executes as OrderedLocal/ConnLocal;
the shared parser invokes the handler at `src/core/io_loop.h:4214` and
publishes Done at `4225` after the void handler returns. Its journal
already attaches the connection's sequence. Setting AofWait inside the handler is
therefore overwritten by the common IO completion. Blocking that IO until sync
can obstruct unrelated reads and is unacceptable.

Proposed FUNCTION design: a cold asynchronous OrderedLocal completion seam that
returns/retains an unfinished Op after the journal mutation, carrying its client
receipt into the same persistence-woken IO continuation. The function state may
publish normally, but the reply/ROB slot remains held until local_ack. Cover LOAD,
DELETE, FLUSH and RESTORE, errors/no-op mutations, disconnect, runtime AOF policy
changes, and shutdown with an outstanding receipt. This needs parser/IO lifetime
work beyond the three source files of this S1 patch. No FUNCTION or multi source
change or counted claim of a fix is included; the owner decides these designs.

### Slow final fsync shutdown

The ordinary worker-join grace ignored the final sync. At the gate's eight-thread
geometry it is 2700 ms, rather than the analysis's four-thread 1500 ms.
`AofManager::writer_shutdown:3288` performs the final sync and leaves recording
true until the close at `3297`. `DatabaseMap::join_workers:355–363` now latches the
existing 10-second persistence grace (`Server::kShutdownSaveWaitNs`) while AOF is
recording. It logs once after the ordinary grace is exceeded. AOF activity does
not reset the deadline. This is a bounded wait, not removal of shutdown supervision.

The shim delayed the final sync by 3500 ms. Release aborted with SIGABRT; POST
waited, logged `bound_ms=10000`, exited 0 and recovered the acknowledged key.
All four 1s/2s × epoll/uring combinations passed their expected verdicts; see
`docs/aofblock/shutdown-results.json`. PAD-A again aborts. The virtual-clock
`shutsave-unit aof` exits after eight seconds; `aof-hang` aborts at ten seconds,
proving the extension is bounded. These shim checks remain outside counted rows.
Final re-run on the final arms: POST exits 0 after 3.52 s and PAD-A aborts
(SIGABRT) in all four 1s/2s × epoll/uring combinations
(`docs/aofblock/final-ordering-existing.json`).

### Hot instruction proof

`tools/aofblock_artifacts.py audit RELEASE POST OUTPUT` audits all 12,864 physical
function bodies, including both namespaces and IO/executor/scatter envelopes.
It retains opcodes, registers, immediates, instruction widths, member offsets and
internal branch locations. It normalizes verified relocation displacements,
compares complete renamed CSWTCH table bytes, and checks every destination of
bounded local switch tables. Anonymous inline-assembly labels resolve to the
containing function and exact offset. No opcode or branch change is masked.

Release→POST: **12,856 identical functions, six changed cold functions, two
INFO build-metadata-only differences, zero unexpected changes**. The six are
blocking_finish_cancelled ×2, AofManager::defer_completion ×2, and join_workers
plus its cold exception body. The latter two are the explicitly requested
shutdown fix. The blocking-only branch in defer_completion changes its expected
value; ordinary write completions retain the same instructions. Source comments
outside changed lines were not edited. All layout locks still compile.

The added cold cancellation code increased GCC's initial xshard IPA size by 16
in each namespace. Without compensating its existing inline budget, unrelated
inlining moved. The Makefile raises only those two existing budgets by 16:
168538→168554 and 172012→172028. `docs/aofblock/inline-budget.json` records the
137220→137236 and 136920→136936 initial-size evidence. The resulting whole-binary
proof is in `docs/aofblock/symbols-summary.json` and its eight detailed diffs.

Final arms (takeover). The same audit was re-run release→POST e25f8b6f and
PRE 8aa098c9→POST e25f8b6f. Both give **12,856 identical functions, the same
six changed cold functions, two INFO metadata-only functions and zero
unexpected changes** (`docs/aofblock/final-arms.json`). The lane deleted the
raw `-fdump-ipa-inline` dumps after recording them, so the untracked
`docs/aofblock/inline-dump-receipts.json` pointed at files that no longer
exist. It also mixed in obsolete intermediate builds, so it was deleted.
`inline-budget.json` remains the receipt, and the audit outcome confirms the budget.

The existing `tools/exec1s_scope.py` / `tests/txnorder_command_scope.cc` serverless
fixture also traced a fixed batch of one command: five commands × both modes ×
both namespaces, plus MSET atomic 0 as well as 1 = **24 matched cases / 48 traces**.
Every total and per-function count is exactly equal, not just lower. This is
instruction counting, not a throughput workload. PRE links the original xshard,
AOF and multidb objects in production link order; other unchanged objects are
shared with POST. Link receipts and counts are in `docs/aofblock/instruction-*`
and `docs/aofblock/instructions-*`. AOF is disabled in this bounded fixture;
the binary audit covers the unchanged ordinary branches of the AOF-enabled path.

| Command (ordinary namespace) | 1s PRE = POST | 2s PRE = POST |
|---|---:|---:|
| GET | 935 | 1555 |
| SET | 1022 | 1642 |
| MGET | 10098 | 10098 |
| MSET atomic 0 | 10479 | 10297 |
| MSET atomic 1 | 16567 | 16235 |
| INCR | 1476 | 2096 |

### Correctness receipts (lane)

Build: `LC_ALL=C taskset -c 56-83 make -j28 all` plus the persistence/shutdown
units. Selected `tests/gate.sh quick` jobs use `GATE_PROOF_NO_RATES=1` and the
job interface, not the complete quick/iteration pipeline. No ABBA, NIC test,
throughput benchmark, or full iteration was run.

* `python3 tests/gates_test.py`: **83/83 pass**, including the additional blocking
  unit's failure propagation; its nested persistfix identity tests also pass 14/14.
* The actual label-fixture unittest was run and correctly refuses the owner-owned
  stale fixture/counts: 12 tests, two failures and one error. No EXPECT/fixture edit
  was made. An explicitly labeled in-memory landing projection with the 36 literal
  labels and full count 1265 passes all 12 controls. It is not a substitute green
  receipt for the unchanged files.
* Release and PAD-A: each **36/36 new rows fail** with the rollback witness.
* The lane's broad run had two FAILs. `txnorder FIFO live fairness` hit its
  latency bounds while a second gate run shared CPUs 72-79 with it. The
  `eoffix_aof` family could not start, because `EOFFIX_AOF_DIRECTORY` (prebuilt
  native AOF arms) was unset. The final run below addresses both.

### Final receipts (takeover, 2026-11-08)

Every command was pinned to CPUs 56-83 (`taskset`, `make -j28`), every server
ran with `LC_ALL=C`, and all ports were in 25800-25899. Gate jobs used
`GATE_PROOF_NO_RATES=1 GATE_ONLY_JOBS=... tests/gate.sh quick
--candidate-binary build/aofblock/final/POST`; the server and load CPUs are
named in each row. The only overlap: `tests/gates_test.py`, which uses stubs and
no servers, ran on CPUs 72-83 alongside the PRE ordering matrix and the
release-row run on CPUs 56-67. Everything else ran alone.

| Receipt | Result | Evidence |
|---|---|---|
| Final build at bab542a664 | `make -j28 all` rc 0 (59 s, full rebuild) | `build/tomokv` = POST e25f8b6f |
| `make -q all` at the end (after the gate prerequisites and units) | **rc 0**, up to date | `docs/aofblock/final-make-q.log` |
| 36 counted rows, final POST (server 56-71, load 72-83) | **36/36 PASS** | `docs/aofblock/final-post-rows.json` |
| 36 counted rows, release binary (server 56-63, load 64-67) | **36/36 FAIL**, all with the rollback witness | `docs/aofblock/final-release-rows.json` |
| Existing persistence/AOF/blocking/blockfix/multi/function rows (the lane's regression job list minus `aofblock-*` and `eoffix_aof`), final POST | **496/496 ok**: 478 on the first run and 18 on re-run. This includes `txnorder FIFO live fairness`, ok in 989 s on uncontended CPUs. | `docs/aofblock/final-broad-rows.json` (`broad`) |
| Extra blocking/remap/FLIP/script/multidb rows (the lane's extra list), final POST, `GATE_NET_IO=epoll` | **137/137 ok**: 129 on the first run and 8 on re-run | `docs/aofblock/final-broad-rows.json` (`extra`) |
| `shutsave-unit aof` / `aof-hang` (no gate row runs these) | PASS (8 s virtual completion) / bounded abort at 10 s (rc 134) | `docs/aofblock/final-unit-aof-shutdown*.log` |
| `python3 tests/gates_test.py` | **83/83 OK** (228 s, CPUs 72-83) | `docs/aofblock/final-gates-test.log` |
| Label-fixture unittest | Refuses as designed: 12 tests, 2 failures, 1 error. Exactly the 36 aofblock labels are missing (declarations 1265, fixture and EXPECT_FULL 1229). No EXPECT or fixture edit. | `docs/aofblock/final-label-fixture-unittest.log` |
| Ordering tool, 9 blocking cases × 1s/2s, epoll | PRE **early 36/36**; POST **held until fsync 2 in 54/54**; 0 re-arms; plus 8 smoke runs that agree | `docs/aofblock/final-ordering-blocking.json` |
| Ordering tool, EXEC/FUNCTION × 1s/2s on POST | still **early 14/14**, as expected for these open causes (1-3 bounded re-arms on EXEC cases) | `docs/aofblock/final-ordering-existing.json` |
| Slow final fsync (3.5 s), 1s/2s × epoll/uring | POST exit 0 in 4/4; PAD-A SIGABRT in 4/4 | `docs/aofblock/final-ordering-existing.json` |
| Symbol audit release→POST and PRE→POST | 12,856 equal, 6 changed (expected), 2 INFO, 0 unexpected | `docs/aofblock/final-arms.json` |

Re-runs: all 26 first-run FAILs had one harness cause. Unit-backed jobs look for
their unit binaries, or for a bound sibling file such as
`<candidate>.blockfix-cost.sha256`, next to `--candidate-binary`, and
`build/aofblock/final/POST` has no siblings (for example "taskset: failed to
execute build/aofblock/final/txnorder-episodes"). The affected jobs were
blockfix2, blockfix_registry, txnorder2, txnorder_wake and moverfix. They were
re-run with `--candidate-binary build/tomokv`, which is byte-identical
(e25f8b6f) and sits next to the freshly built units, and all 26 rows passed.
No row was dropped or relabelled. For the maintainer: point the candidate at
`build/tomokv` for unit-backed jobs.

### Measurement request (owner runs, no performance claim)

Final arms (copies in `/home/user/Projects/bins/`; provenance in `docs/aofblock/final-arms.json`):

| Arm | Path | SHA-256 | Source / INFO |
|---|---|---|---|
| PRE | `/home/user/Projects/bins/aofblock-PRE-8aa098c9` | `8aa098c9bcd9ea02d161ee450096010ebc4175d7986afca6f6eb55a7af5cc3d2` | base 7595a6705a, clean |
| POST | `/home/user/Projects/bins/aofblock-POST-e25f8b6f` | `e25f8b6f3f1f71cb2699853920a640683524fbc1df0b57b21cf4c2663c6f5a35` | bab542a664, clean (same src/Makefile as the tip) |
| PAD-A | `/home/user/Projects/bins/aofblock-PADA-6e1042a2` | `6e1042a219ea5ba1567ebe26dc5cdff5408d385b146de4f5c6c2a79f7c1b008b` | `tools/aofblock_artifacts.py pad` on POST e25f8b6f |
| release negative control | `/home/user/Projects/bins/readability-pre-5c363128/tomokv` | `0de6bbdea50caf4f90f797c4e52a4e86be30e2c554fb544f257f5148bf4016cd` | 5c363128 |

Use these arms rather than the lane's `build/aofblock/{POST,PAD-A}` (5a233f16, 971677cb).
Every loaded section is identical to those; only the INFO `redis_git_sha1`/`redis_git_dirty`
text differs. The lane's POST was built from an uncommitted tree (`bdf0e528`, dirty 1), so it
was rebuilt from the final commit. The release binary and PRE are also identical
in every loaded section apart from build-id and INFO, and PRE matches a separate
rebuild from `git archive 7595a6705a`.

**PAD kind A: behaviour twin = PRE behavior with exact POST text size/layout.**
`tools/aofblock_artifacts.py pad` patches only the two blocking claim constants,
the two added cancellation calls and the shutdown-extension branch in a copy of
POST. It verifies unchanged ELF sections/symbols and every other byte. The five
patches are listed in `docs/aofblock/final-arms.json`; the lane's own run is in
`docs/aofblock/pad.json`. PRE .text is 9,251,911 bytes; POST and PAD-A are
9,252,279 (+368). PAD-A is deliberately defective and is only a local control.

Measure the gate's existing matched-load ABBA cells for GET, SET, MGET, MSET and
INCR in both 1s and 2s, at the gate's 16-shard / eight-core geometry and ordinary
AOF-off settings. Include the existing appendfsync-always correctness-sensitive
write cells if the instrument has them. Keep offered load, payloads, pipeline
and pinning identical across PRE/POST/PAD-A. Report rate, cycles/op, instr/op and
IPC per cell; rate at matched offered load is the verdict. The S1 fix must retain
main-command performance. PAD-A moving with POST identifies a layout artifact;
POST moving while PAD-A stays at PRE identifies a behavior effect. Repeat any
identical-arm spread above ±2% as contention/bug, not noise. Do not interpret
PRE's premature blocking acknowledgements as useful higher throughput.

The lane's red FIFO fairness row came from two gate runs sharing CPUs. On
uncontended CPUs 56-83 the final POST passes it (989 s). A quiet-box run inside
the full iteration remains the maintainer's verdict. The maintainer owns full
iteration, merit and landing count/fixture updates.

### NOT RUN

* No throughput benchmark, ABBA, NIC cell, perf gate, full quick tier or full
  iteration. These belong to the maintainer, as do the EXPECT and label-fixture
  updates (1248 / 1265 and the 36 labels in `docs/aofblock/new-labels.json`).
* `eoffix_aof` (nine EOF/QSBR native-arm rows) was not run. It needs prebuilt
  arms in `EOFFIX_AOF_DIRECTORY`, and their builder `tools/eoffix_aof.py` is
  archived and absent from this tree. That code is unrelated to this patch.
* The 36 rows were not re-run on the final PAD-A. The lane's run of the final row
  script on its PAD-A failed 36/36 (`build/gate-run.4LKkhW`), and the final PAD-A
  differs from it only in the INFO text.
* The serverless instruction census (`tools/exec1s_scope.py`) was not re-run. Its
  inputs are code-identical to the final arms, and the whole-binary audit was re-run.
* Ordering tests ran on epoll only; the uring shim is not discriminating. No
  ASAN/TSAN builds, Redis TCL suite or Redis differential were run for this patch.
* The blocking completion offer races were not reproduced, and no fix is
  included. EXEC with PUBLISH/SPUBLISH/SUBSCRIBE and FUNCTION
  LOAD/DELETE/FLUSH/RESTORE remain early (confirmed again on the final POST) and
  await the owner's design decision.

### Combined landing (2026-11-09)

This branch lands together with two other branches, merged on top of the aofblock tip fdbb19ba8e so that one gate covers all three:
- t6wound (70560daf72), a test-only change: tests/at412.py opens T6's wound deterministically with existing DEBUG scheduling hooks (0/240 missed openings in 5 complete runs per binary; the missing-window controls still fail). The two previous landing gates, for this branch and for readability-p2, each failed only at412 T6, whose probabilistic wound guard missed about 30% of attempts, so the row failed about half the time by chance.
- readability-p2 (eb55eb3dff): readability phase 2 (lanes A7-A10) plus readability-p2fix. Comment-only; its production binary is IDENTICAL to the frozen release.
Rows: +36 quick / +36 full, from aofblock only (EXPECT 1248/1265); the other two add none.
- blockrace (e94a8b9c2d), an S1 fix: the blocking completion offer races, which could give a later command a pop's reply or hang a client, and the BlockingState read after Done (a use-after-free). All three were reproduced deterministically on PRE before the fix: two-offer FAIL 4/4, no-offer FAIL 4/4, ASAN heap-use-after-free. After the fix: PASS 4/4, PASS 4/4, ASAN clean. Cold blocking.inc only, plain participant counts; FLIP drain is not wedged; the hot paths are instruction-identical. Its merit (ABBA against its PRE) runs in this bench phase before this landing's gate.
Rows: now +38 quick / +38 full (aofblock +36, blockrace +2), so EXPECT becomes 1250/1267.
