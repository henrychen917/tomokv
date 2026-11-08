## aofblock

S1 patch against `7595a6705`, branch `cx-aofblock`. No push. Correctness boots use
`LC_ALL=C`, CPUs 56–83 and ports 25800–25899. The complete external analysis and
`phase_b.py`, `fsyncdelay.c`, and the reproduction's result summaries were read.

Implemented: blocking completion ownership and the bounded final AOF shutdown
wait. Confirmed but left for the owner's design decision: EXEC with publication
or subscription and FUNCTION registry mutations. Their code is unchanged.

### Blocking completion ownership

The proposed Free comparison is necessary, but is not sufficient on its own.
The production diff is one changed CAS initializer plus three cancellation lines.

| Path / invariant | Current-tree evidence |
|---|---|
| Actual initial state | `src/exec/op.h:103` resets Free. The only production Issued store is the temporary withheld-EXEC shutdown marker, `src/core/shutdown.cc:160`; blocking dispatch does not store Issued. |
| Exactly one reply producer | `src/cmd/blocking.inc:990` claims a timeout from Parked; group removal, wake selection, probe completion and registration use phase CASes at `1026`, `1142`, `1209`, `1248–1280`. Registration OOM claims Registering at `759`. A failed claim does not compose a second reply. |
| Last active task vs registry wake | `blocking_task_done:525` uses the final active_tasks fetch_sub. `blocking_publish_completion:722` publishes Completed, then tests active_tasks. Both can offer the same completed Op; `src/persist/aof.cc:3032` now claims Free→AofWait exactly once. An offer observing AofWait or Done returns handled without another enqueue/notify. |
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

### Other S1 causes: confirmed; design for owner decision

The marker-driven preloaded-gate test is `tools/aofblock_order.py`, with
`tools/aofblock_fsyncdelay.c`. It holds fsync 1, verifies an independent PING is
braked by the older send target, issues the subject, releases fsync 1, observes
fsync 2 held, and observes PING released. A subject reply at that point is early.
Masked arming is retried on a fresh server, bounded at eight attempts; exhaustion
fails. No tolerance is widened and no unarmed case passes.

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

### Correctness receipts

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
* Full final-POST row receipts and final `make -q` status will be appended below.
* The broad run's existing `txnorder FIFO live fairness` row has latency-bound
  failures while unit compilation/control work overlapped it. Preserve that failure;
  there is no claim that unchanged instructions imply unchanged latency/layout merit.

### Measurement request (owner runs, no performance claim)

Arms in this worktree:

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `build/aofblock/PRE` | `8aa098c9bcd9ea02d161ee450096010ebc4175d7986afca6f6eb55a7af5cc3d2` |
| POST | `build/aofblock/POST` | `5a233f162bc19c4040afd23dd81aad981a261fdc5fc548a335bcafed6446f3c2` |
| PAD-A | `build/aofblock/PAD-A` | `971677cbfbb0f847d772a0455223c190f52c69ed0ed3982758e37fb431fe06e8` |
| release negative control | `/home/user/Projects/bins/readability-pre-5c363128/tomokv` | `0de6bbdea50caf4f90f797c4e52a4e86be30e2c554fb544f257f5148bf4016cd` |

**PAD kind A: behaviour twin = PRE behavior with exact POST text size/layout.**
`tools/aofblock_artifacts.py pad` patches only the two blocking claim constants,
the two added cancellation calls and the shutdown-extension branch in a copy of
POST. It verifies unchanged ELF sections/symbols and every other byte. Details
are in `docs/aofblock/pad.json`. PRE .text is 9,251,911 bytes; POST and PAD-A are
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

The FIFO fairness row also needs a quiet-box verdict if the lane's contended
latency-bound result remains red. The maintainer owns full iteration, merit and
landing count/fixture updates.
