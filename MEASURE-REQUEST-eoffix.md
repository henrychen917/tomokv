## eoffix

Worktree `/home/user/Projects/cx-eoffix`, branch `cx-eoffix`, base
`ea48a6b2721a1d9e5964ab24a32e8b54df611bd5`. No push. This report is being
completed while the remaining correctness jobs run; pending entries are not passes.

The `final-*` candidate below was superseded during cleanup review: an EOF-state
allocation failure could retain the synthetic receive hold used during handoff
rollback. `eof-oom-before` fails that exact assertion in both namespaces;
`eof-oom-after` passes after clearing the hold in the cold allocation-error path.
The `complete-*` arms are frozen and pass the directed EOF/AOF checks; the broader final proof is running. Earlier successful
runs are retained as intermediate evidence, including all twelve Tcl legs and
the complete epoll differential matrix; they are not passes for the new arm.

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
| Epoll loses EOF | `pre-fin-complete`: both namespaces fail the missing-teardown assertion; open-peer controls pass. `pre-netio-coalesced`: both public epoll rows fail with the exact closed BRPOPLPUSH client still registered. | `complete-eof-aof`: native controls and all four public mode/engine legs pass, 101 checks per netio leg. | Retain RDHUP independently of a short read; use deferred receive/retirement. | Full Tcl ordering results are separate below. |
| Half-close input loss | `pre-half-replies`: data/reply failures in 1s/2s, uring/epoll, databases 1/16. Redis applies and replies to every original 1/32/65/256/4096 frame. | `complete-eof-aof`: all 90 controls pass (80 TomoKV, 10 Redis), including depth 65,536, a truncated final frame, exact reply order, applied values, client retirement, a non-reading peer and two synchronous-control prefixes. | Drain buffered commands and replies before normal close; bound stalled output. | The non-reading-peer grace is explicit above. |
| Transaction-AOF timeout | `txn-pre-epoll-cont-14`: row d TimeoutError and 30-second shutdown failure, with failure-only GDB stacks; deterministic `pre-aof-progress-complete` fails all eight pressure/self-writer cases and passes all four open-channel controls. | `complete-eof-aof` passes all 12 native controls; final whole-job repetition is pending. | Publish coarse QSBR progress while an AOF producer waits on its full channel; let GCMT use the existing writer-drain hook. | Independent of EOF. Final whole-job loops remain pending. |
| Public regression jobs | Public netio fails PRE; the full PRE Tcl run also fails on tracking order, independently of this patch. | EOF/netio checks pass. All 12 earlier Tcl legs passed; the replacement-arm Tcl, differential and broader job matrices are in progress. | Tests retain all 32 wave-14 EOF cases; the first queues data and FIN while every owned server thread is observably stopped. | Intermediate POST tracking failures are retained separately; no assertion or manifest has been weakened. |

PRE data-loss examples from `pre-half-replies` (both database namespaces):

| Mode / engine | Sent INCR frames | Applied in db1 | Applied in db16 |
|---|---:|---:|---:|
| 1s / uring | 256 | 64 | 64 |
| 2s / uring | 256 | 64 | 64 |
| 1s / epoll | 4096 | 64 | 64 |
| 2s / epoll | 256 | 64 | 64 |

Redis applies and replies to every original depth 1/32/65/256/4096 case.
PRE also loses replies at smaller depths and fails exact-client retirement on
multiple epoll legs; the raw receipt distinguishes those from missing writes.
The final 90-case run checks every reply and final value, including depth 65,536,
in all eight TomoKV mode/engine/namespace legs and the oracle leg.

**AOF diagnosis.** PRE completed 38 epoll iterations with successful prerequisites;
the original row-d/shutdown failure occurred on clean iteration 23 (nine
`txn-pre-clean-epoll` jobs followed by continuation 14). The loop continued during
stack analysis, yielding 37 AOF/reload passes and one AOF hang; 33 entire jobs
passed and four additional jobs failed their row-b latency bound. One earlier
attempt had a 900-second prerequisite build timeout and is excluded. The final
interrupted continuation is also excluded. Uring completed 50 iterations: all 50
AOF/reload/shutdown legs passed; 38 entire jobs passed and 12 failed their row-b
latency bound. Every failed attempt and observer output is retained.

In `build/gate-run.0yMfb5`, owner LWP 978298 waits in
`ReadLocalDeferredQueue::force_oldest_grace` during immutable INCR replacement.
LWP 978310 waits in `aof_commit_group` posting ticket 691 to its full
channel; the remaining workers are idle. Fused placement assigns the AOF writer
to the last thread (t7); creation order maps that worker to LWP 978310. The
writer waits on its own channel without invoking the existing persistence drain.
Its pinned QSBR epoch also obstructs owner reclamation. SIGTERM cannot break
this progress failure. `txn-pre-epoll-cont-14.tar.gz` preserves stacks and the shutdown
receipt. This is a real AOF/QSBR defect, not an unretired-connection inference.

The existing `drain_for_producer` cold backpressure hook now refreshes the
producer's read-local publication, and the GCMT retry calls that hook. Local
capture buffers have been consumed/copied before owner mutation/AOF emission;
queued lane entries do not retain captured store pointers. This uses the same
quiescent publication as `force_oldest_grace`, preserving parked status. The
hook drains persistence only when this producer is the writer. It adds no
reader retry or per-operation publication. The QSBR native witness fills the real
64-slot AOF channel and a real 4096-entry retire ring, proves the producer pins
the grace, and requires reclamation before releasing one channel slot. Its
open-channel control requires zero new QSBR publication. Both namespaces and
both ring engines reject PRE and accept the candidate. A separate self-writer
control disables read-local, fills the writer's own channel, and requires the
actual GCMT retry to drain all 64 physical frames. This independently checks the
missing writer-progress call. These serverless physical-frame controls use
normal persistence IO; whole gate jobs cover actual uring persistence.

**Tcl attribution.** `pre-tcl-attribution-06` reproduces the rejected trial's
exact "Different clients using different protocols can track the same key"
assertion on PRE. `pre-tcl-attribution-02` and `-05` reproduce the original two
list-fairness assertions. Other retained PRE runs reproduce BCAST and shared
redirection order failures, pubsub PUNSUBSCRIBE failures, and the scripting
50,000-load loop's Tcl timeout. These are attribution receipts, not green full
suite claims. The earlier candidate passed the full manifest three times per engine in both modes: all
12 legs, 39 files per leg, serially on CPUs 0–7. See
`final-tcl-{epoll,uring}-{1,2,3}.json` and their raw archives. Replacement-arm repeats are in progress. No Tcl expectation or manifest was
relaxed. All intermediate POST failures remain in `validation-summary.json`.

**Differential proof.** The earlier candidate passes epoll with the standard seeds 7/19/20/23/24:
split atomic 0/1, fused read-local atomic 0/1, and mode equivalence. The four
differential parts report 235/239/231/235 passing rows and zero failures; mode
equivalence also passes. The original geometry-specific skips remain explicit
in the logs. See `final-differ-epoll.json` and its raw archive. Its uring run was
stopped after the allocation-error finding and is recorded as interrupted.
Both engines are queued for the replacement arm.

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

**Instruction evidence (final release SHA `4129a20c7571e5c1894cbfb2bf6d338e546b3c6f63aa0a692a9f9c10b97cf501`).** Finite serverless scopes enter linked production
bodies. Counts exclude fixture glue, shared libraries, syscalls and synthetic
clock calls. Raw traces and exact per-cell totals are in
`docs/eoffix/instructions/`; `instruction-comparison-final.json` and `.md` retain
every paired cell. No rates, cycles or throughput claims are made.

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

**Final frozen arms.** `docs/eoffix/arms-final.json` contains sizes and full digests.

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `build/eoffix/pre-rebuilt` | `35874756cda5cc4918fe0b6f6a715c1a0e7f1b87d4b8f4098d041d1c7839314a` |
| POST | `build/eoffix/post-complete/tomokv` | `4129a20c7571e5c1894cbfb2bf6d338e546b3c6f63aa0a692a9f9c10b97cf501` |
| POST-layout | `build/eoffix/layout-complete/POST-layout` | `962a727251beab9c84ae6d288bc726b2b2a873aed1663b00fc698e3a19f3ac38` |
| PAD-A | `build/eoffix/layout-complete/PAD-A` | `000ed013b20f8f6b0614f39ffda7f6ea823494a3df03ac44b8e7d9c40a874171` |

PAD is **type A: behavior twin**, PRE behavior in the common POST-layout image.
POST-layout and PAD-A have identical section/symbol layouts and function addresses;
only the five-byte main entry jump differs. Its exact comparison arm is
POST-layout, not the smaller release POST. `.text` sizes: PRE 9,021,623 bytes,
POST 9,035,879 bytes, both layout twins 18,057,127 bytes. `pad-a-complete.json`
preserves link/patch proof. Final POST-layout passes public netio and all 90 half-close controls; PAD-A
fails both public netio rows on the exact coalesced BRPOPLPUSH retirement
assertion, while its uring legs pass, matching PRE.

The earlier `arms.json` and every intermediate receipt remain retained. Obsolete
layout/native binaries were retired with digests in `retired-artifacts.json` to
meet the disk cap. Final arms, rebuilt PRE, the PRE native AOF control, complete
build recipes and all raw evidence remain available.

**Maintainer measurement request.** Run the 18 cells in `docs/eoffix/cells-uring.txt` and
`cells-epoll.txt`: generic14 `h05 h06 p8g p8s d1g_l0 d1s_l0 m8g_l0 v1g_l0
d128g_l0 d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`, plus 2s GET/SET
p1/p32 `h53 h54 h21 h22`. `measurement-cells.json` records exact source and
cell-file digests; the gate parser accepts all 18 cells per engine. Compare release PRE/POST, retain a byte-identical null,
and separately compare POST-layout/PAD-A (type A) on those same cells. Matched-load
rate decides regression; cycles/op, instructions/op and IPC explain it. Measurements,
performance load generators and the full iteration are **NOT RUN** here: owner-owned
under the task's runtime authorization. No throughput claim is attached to this diff.

**Build and harness proof.** Final `make all` plus all 55
`job_production_units` targets and its additional mdbqsbr, blockfix cost and
blockfix2 targets pass (`complete-build.json`). Final `make -q` freshness and
`python3 tests/gates_test.py` are queued after the remaining jobs. Earlier
freshness and 14 + 77 harness tests passed; those receipts remain retained.

**Gate accounting.** DQ=0, DF=0. The existing netio rows are strengthened at their
existing collection lines before the quick exit; private wave14 EOF jobs remain
partial-only. The netio collection remains at line 6568, before the quick exit at line
6839. The partial-only AOF job has no public collection line. No row is added
or retired. `EXPECT_QUICK=1046` and
`EXPECT_FULL=1063` remain untouched.

**Retained unsuccessful attempts.** The first native PRE attempt lacked the DB0
link's normal Lua definitions; its missing-binary failure is not a witness. The
complete rerun supplies both real negative witnesses. The first extended half-close
attempt reused a previously populated key for the truncated case and failed its
fresh-state precondition on Redis as well as TomoKV; the fresh-key rerun passes all
72 cases. Initial added armed-MGET parser attempts exceeded the inherited fixture's
single-parser-call contract; they remain recorded as failed fixture attempts, not
production defects. The final requested ordinary parser matrix is explicit above.

The exploratory 99-case half-close run exposed premature cancellation of
`DEBUG SLEEP`; that mechanism was corrected before the final arms. Its additional
`CLIENT PAUSE` prefix also failed on Redis (one control reply, zero suffix
increments), so that newly proposed expectation was rejected. The final 90 cases
retain every original EOF case and add only oracle-confirmed controls. The
rejected 99-case receipt remains available; no original gate assertion was removed.

`clientfix.py` now honors the selected `GATE_NET_IO` in its owned server boots;
its prior implementation silently used uring even in an epoll job invocation.
This changes no assertion or public row count. The final clientfix jobs will
therefore record actual boots on both engines.

The `atomic_floor` job now uses the existing `txn_proof_boot` helper so its
400-roll pipeline-order check honors `GATE_TXN_FUSED=1`. Its default split
behavior and public count are unchanged. The existing partial `NO_RATES`
switch omits the throughput floor and records that row as NOT RUN; no load
generator runs in this lane.

The final AOF coverage also selects the existing rootcore functions, segments,
WAITAOF and MISCONF jobs, plus `infofix_compat-loadaof`; their own mode/engine
matrices and assertions are unchanged.
