## eoffix

Worktree `/home/user/Projects/cx-eoffix`, branch `cx-eoffix`, base
`ea48a6b2721a1d9e5964ab24a32e8b54df611bd5`. No push. This report is being
completed while the remaining correctness jobs run; pending entries are not passes.

The EOF production change is in `src/core/eof.cc`, with receive, timer and teardown
wiring in `io_loop.h` and `reorder.cc`. The independent AOF deadlock fix is in
`src/persist/aof.cc`. No command algorithm or object layout changes. The normal receive/parser path does not consult EOF state. A FIN creates
an entry in the existing IO-owned deferred-timer vector; an actual `recv(0)`
stops receive admission while the ordinary parser, ROB and writeback drain.
`recv_armed` then represents the EOF admission hold, with no outstanding kernel
buffer pin. The cold close path releases that hold. Migration preflight refuses
the owner-local EOF state; EOF winning an outstanding receive cancellation rolls
back the handoff before draining on the original owner.

Epoll retains RDHUP even when the edge also carries a short positive read. Its
deferred FIN entry forces another receive attempt until actual EOF, without an
extra syscall on an ordinary short read. Blocked list/stream waits use existing cancellation and teardown. Pending
synchronous `DEBUG SLEEP` and `CLIENT TRACKING ON` completions are preserved,
including their buffered command suffix. A truncated final frame is classified with a temporary parser after
ROB quiescence; complete frames continue through ordinary admission. A half-closed
peer whose pending output makes no progress for one second is closed; command
retirement or a change in pending output restarts that grace period. TLS retains
its existing transport shutdown behavior.

| Item | PRE witness | POST result | Mechanism changed | Residual |
|---|---|---|---|---|
| Epoll loses EOF | `pre-fin-complete`: both namespaces fail the missing-teardown assertion; open-peer controls pass. `pre-netio-coalesced`: both public epoll rows fail with the exact closed BRPOPLPUSH client still registered. | `post-native`, `post-first`: native controls and all four public mode/engine legs pass. | Retain RDHUP independently of a short read; use deferred receive/retirement. | Full Tcl ordering results are separate below. |
| Half-close input loss | `pre-half-replies`: data/reply failures in 1s/2s, uring/epoll, databases 1/16. Redis applies and replies to every original 1/32/65/256/4096 frame. | `post-extended-fresh`: all 72 controls pass (64 TomoKV, 8 Redis), including depth 65,536, a truncated final frame, exact reply order, exact applied values, exact-client retirement and a non-reading peer. | Drain buffered commands and replies before normal close; bound stalled output. | The non-reading-peer grace is explicit above. |
| Transaction-AOF timeout | `txn-pre-epoll-cont-14`: row d TimeoutError and 30-second shutdown failure, with failure-only GDB stacks; deterministic `aof-pre-native` fails all four pressure cases and passes all four open-channel controls. | Candidate `aof-post-native` passes all eight native controls; final-arm repetition is pending. | Publish coarse QSBR progress while an AOF producer waits on its full channel; let GCMT use the existing writer-drain hook. | Independent of EOF. Final whole-job loops remain pending. |
| Public regression jobs | Public netio fails PRE; the full PRE Tcl run also fails on tracking order, independently of this patch. | EOF/netio checks pass. Full Tcl, differential and broader job matrices are in progress. | Tests retain all 32 wave-14 EOF cases; the first queues data and FIN while every owned server thread is observably stopped. | Full Tcl tracking failures have also occurred on POST; no assertion or manifest has been weakened. |

**AOF diagnosis.** PRE completed 38 epoll iterations with successful prerequisites;
the original row-d/shutdown failure occurred on clean iteration 23 (nine
`txn-pre-clean-epoll` jobs followed by continuation 14). The loop continued during
stack analysis, yielding 37 AOF/reload passes and one AOF hang; 33 entire jobs
passed and four additional jobs failed their row-b latency bound. One earlier
attempt had a 900-second prerequisite build timeout and is excluded. The final
interrupted continuation is also excluded. Uring completed 50 iterations: all 50
AOF/reload/shutdown legs passed; 38 entire jobs passed and 12 failed their row-b
latency bound. Every failed attempt and observer output is retained.

In `build/gate-run.0yMfb5`, writer LWP 978298 waits in
`ReadLocalDeferredQueue::force_oldest_grace` during immutable INCR replacement.
Producer LWP 978310 waits in `aof_commit_group` posting ticket 691 to its full
channel; the remaining workers are idle. The producer pins the old QSBR epoch,
so the writer cannot finish replacement and drain the channel. SIGTERM cannot
break that cycle. `txn-pre-epoll-cont-14.tar.gz` preserves stacks and the shutdown
receipt. This is a real AOF/QSBR defect, not an unretired-connection inference.

The existing `drain_for_producer` cold backpressure hook now refreshes the
producer's read-local publication, and the GCMT retry calls that hook. Local
capture buffers have been consumed/copied before owner mutation/AOF emission;
queued lane entries do not retain captured store pointers. This uses the same
quiescent publication as `force_oldest_grace`, preserving parked status. The
hook drains persistence only when this producer is the writer. It adds no
reader retry or per-operation publication. The native witness fills the real
64-slot AOF channel and a real 4096-entry retire ring, proves the producer pins
the grace, and requires reclamation before releasing one channel slot. Its
open-channel control requires zero new QSBR publication. Both namespaces and
both engines reject PRE and accept the candidate.

**Tcl attribution.** `pre-tcl-attribution-06` reproduces the rejected trial's
exact "Different clients using different protocols can track the same key"
assertion on PRE. `pre-tcl-attribution-02` and `-05` reproduce the original two
list-fairness assertions. Other retained PRE runs reproduce BCAST and shared
redirection order failures, pubsub PUNSUBSCRIBE failures, and the scripting
50,000-load loop's Tcl timeout. These are attribution receipts, not green full
suite claims. The final full manifest will run three times per engine, both
modes, without competing correctness jobs. No Tcl expectation or manifest was
relaxed. All intermediate POST failures remain in `validation-summary.json`.

PRE's 261 tracked production/third-party files and Makefile match `ea48a6b27`
exactly (`docs/eoffix/pre-source-identity.json`). The rebuilt PRE was produced
after the harness-only commit `bd9aa0d0af`; embedded build identity can therefore
name that commit. The first natural-scheduling attempt also tested the supplied
wave-14 native image `c1ed04ec...`. Its public netio pass is retained, not used as a
negative witness. The forced coalesced-FIN witness uses the rebuilt PRE below.

The CPU planner originally required disjoint server and load cores. Commit
`bd9aa0d0af` adds `GATE_CORRECTNESS_SHARED_CPUS=1`, restricted to selected jobs,
`GATE_PROOF_NO_RATES=1`, identical eight-core masks and no SMT. Default planning
still rejects overlap. All work uses CPUs 0–7, builds use `-j8`, and boots use
`LC_ALL=C` and ports 21900–21999. Ordinary split boots retain 16 shards and 6:2;
each job retains its own explicit geometry overrides, including txnorder's 4:4
split shape. These are partial correctness receipts, not a full iteration receipt.

**Instruction evidence.** Finite serverless scopes enter linked production
bodies. Counts exclude fixture glue, shared libraries, syscalls and synthetic
clock calls. Raw traces and exact per-cell totals are in
`docs/eoffix/instructions/`. No rates, cycles or throughput claims are made.

| Scope | PRE/POST pairs | Delta |
|---|---:|---:|
| GET, SET, INCR, MGET, MSET execution; batch 1/32, 1s/2s, both namespaces, atomic 0/1 | 80 | 0 in every cell |
| Those five commands' parser scopes; batch 1/32, 1s/2s, both namespaces, plus existing armed GET/SET/INCR controls | 52 | 0 in every cell |
| Ordinary epoll event plus short receive; split, fused and R7 fused, both namespaces, batch 1/32 | 12 | 294 → 296 per event |

The epoll discriminator costs **two instructions per event**, or 2/op at batch 1
and 0.0625/op at batch 32 in this finite receive fixture. The zero delta applies
to the command/parser scopes, not to an entire epoll loop. Armed MGET's separate
cut-fence/drain protocol is not represented by this single-parser-call fixture;
its ordinary receive cells explicitly use read-local=0 in both arms.
`tools/eoffix_bind.py` verifies actual entered clone addresses against production;
completed binding receipts are retained before transient probe binaries are
retired to meet the disk budget. See `retired-artifacts.json`.

**Frozen arms.** `docs/eoffix/arms.json` contains sizes and full digests.

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `build/eoffix/pre-rebuilt` | `35874756cda5cc4918fe0b6f6a715c1a0e7f1b87d4b8f4098d041d1c7839314a` |
| POST | `build/eoffix/post/tomokv` | `d44999cd4592475d8ec10701ab5e867bc03b4af4d7b1171b615b99973ae9eb69` |
| POST-layout | `build/eoffix/layout/POST-layout` | `d0e234cac6b75d51a121c335e168b641fbfcd12b82f679e6d88827732c1e6121` |
| PAD-A | `build/eoffix/layout/PAD-A` | `f7b1329bd253d9123a82f720f5565f67be3c981d33e40023897bfed8973ff435` |

PAD is **type A: behavior twin**, PRE behavior in the common POST-layout image.
POST-layout and PAD-A have identical section/symbol layouts and function addresses;
only the five-byte main entry jump differs. Its exact comparison arm is
POST-layout, not the smaller release POST. `.text` sizes: PRE 9,021,623 bytes,
POST 9,035,799 bytes, both layout twins 18,057,063 bytes. `pad-a.json` preserves
link/patch proof. PAD-A fails public netio as PRE does; POST-layout passes netio
and the extended half-close controls.

**Maintainer measurement request.** Run the 14 generic cells plus 2s GET/SET at
p1/p32 on uring and epoll. Compare release PRE/POST, retain a byte-identical null,
and separately compare POST-layout/PAD-A (type A) on those same cells. Matched-load
rate decides regression; cycles/op, instructions/op and IPC explain it. Measurements,
performance load generators and the full iteration are **NOT RUN** here: owner-owned
under the task's runtime authorization. No throughput claim is attached to this diff.

**Gate accounting.** DQ=0, DF=0. The existing netio rows are strengthened at their
existing collection lines before the quick exit; private wave14 EOF jobs remain
partial-only. No row is added or retired. `EXPECT_QUICK=1046` and
`EXPECT_FULL=1063` remain untouched.

**Retained unsuccessful attempts.** The first native PRE attempt lacked the DB0
link's normal Lua definitions; its missing-binary failure is not a witness. The
complete rerun supplies both real negative witnesses. The first extended half-close
attempt reused a previously populated key for the truncated case and failed its
fresh-state precondition on Redis as well as TomoKV; the fresh-key rerun passes all
72 cases. Initial added armed-MGET parser attempts exceeded the inherited fixture's
single-parser-call contract; they remain recorded as failed fixture attempts, not
production defects. The final requested ordinary parser matrix is explicit above.
