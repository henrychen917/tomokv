---
name: thredis-v12k-sendback
description: "v12-K worker-direct in-order io_uring send-back — design, verdict, build state, and the remaining protocol increments + ASAN gates"
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

GOAL (user: "VERY promising if done correctly"): eliminate the CDB-notify -> IO-thread-drain ->
writeToClient reply hop. Workers execute + commit (in dispatch order) + send replies directly via per-worker
io_uring rings; the IO thread becomes recv-only for eligible clients. Maps Tomasulo commit/retirement onto
io_uring rings. Validated by the Jasny VLDB'26 paper [[iouring-dbms-paper-guidelines]] (ring-per-thread +
DeferTR is the REQUIRED design; THredis is better-positioned than PostgreSQL — exclusive per-worker rings).

DESIGN VERDICT (workflow w6277w2qe synthesis; full text /tmp/.../tasks/w6277w2qe.output + design detail
tool-results/bq7ijh78s.txt): CONDITIONALLY FEASIBLE, build gated DEFAULT-OFF, do NOT block on it; ship v12-J
first (done). Loopback win predicted ~0 (64B dispatch-bound, io_uring neutral on loopback); real payoff =
EPYC + real NIC + large values. RISKIEST PART = deferred-retirement/slot-reuse lifetime under churn (the exact
class behind both prior crashes). Promote only if Gate-4 real-NIC beats v12-J.

PROTOCOL (head-ownership token, NOT per-connection affinity — Design 3's affinity demand REJECTED; per-key
hash routing preserved): one atomic per real client `wds_busy` (combined token + single-outstanding; I merged
the synthesis's separate commit_owner+wds_inflight into ONE for less bug surface). A worker, right after it
OR-sets a fake's reply_cdb bit (server.c:10411-10433), CAS(wds_busy 0->1); winner is sole committer. It scans
the CONTIGUOUS ready prefix [flushid, sent_upto) over reply_cdb (same FIFO break as handleWorkerReplies
server.c:2006), builds ONE IOSQE_IO_HARDLINK send chain to the fd on ITS OWN ring (wdsRingOf), records the
pass, submits, holds wds_busy. The SAME worker reaps its ring CQEs at loop top (next to freebackDrainAll
server.c:10214): in-order (hardlink) -> per CQE clear that slot's cdb bit (atomicFetchAnd), commandProcessed,
advance flushid (release-store; the ONE writer while busy), wds_inflight--; when flushid==sent_upto clear
wds_busy + re-scan. WIRE ORDER = single committer walks flushid order + IOSQE_IO_HARDLINK intra-chain + single
pass in flight per fd. user_data = (gen<<48)|client_ptr (x86 ptr fits 48 bits); reaper drops gen mismatch.
5 INVARIANTS (miss one = crash/corrupt under churn): B retire on send CQE not cdb-bit (plain SEND copies ->
CQE=buffer-free; NO ZC in first cut); F gen-tagged user_data; C freeClient defers while wds_inflight>0, reset
wds_busy only at 0, bump wds_gen on free; L EAGAIN/partial never blocks worker loop -> hand back to IO-thread
writeToClient; X exclude cross-shard(csgroup/csparent)/reply-list-overflow/replica/master/monitor/closing.

BUILD STATE (branch v12, NOT pushed):
- v12-J (commit f5a8285c9): SHIPPED — knob thredis-io-uring-reply-send routes worker replies through the
  io_uring SEND ring (IO thread stays sole fd-writer). Validated: sendring fires 0->4 (bypass FIXED),
  correct, no crash, loopback-neutral. The safe "ship now" path.
- v12-K (1/3) foundation (commit 05f1160c4): knob thredis-worker-direct-send; client fields wds_busy/wds_gen/
  wds_sent_upto/wds_inflight (init in createClient); per-worker ring wdsRings[]+wdsEnsureRing (SINGLE_ISSUER|
  CLAMP|DEFER_TASKRUN, plain fallback) in networking.c; wired in workerThreadMain. Validated: 4 rings ready,
  correct, no crash, OFF byte-identical. Rings created but protocol NOT wired (legacy drain still serves).
- v12-K (2/3 prep, commit 5c0bedf32): client fields wds_aborted + wds_close_needed; server.c liburing include;
  fields init. Builds clean, no-op when off. FULL IMPLEMENTATION SPEC (drafted wdsTryCommit/wdsReap functions +
  the 3 resolved cross-thread HAZARDS + exact wiring + 4 gates) is in /home/henry/Projects/V12K_PROTOCOL_PLAN.md
  — next turn writes the protocol from it. RESOLVED HAZARDS: (a) redisAtomic is EMPTY (atomicvar.h:65) → use GCC
  __atomic builtins on plain uint32_t (NOT C11 atomic_*); (b) freeClientAsync uses per-iotid clients_to_close →
  CANNOT call from a worker (no drainer for worker iotid) → error path sets wds_close_needed, the IO thread frees;
  (c) MSG_WAITALL on sends → completes full or errors (no partial-resume double-send); (d) commandProcessed worker-
  safety (slot-stats) to ASAN-verify. clients_pending_worker add at server.c:4999 (IO fallback works).
- REMAINING: (2/3) wdsTryCommit at signal point (server.c needs #include <liburing.h> under HAVE_LIBURING for
  io_uring_get_sqe/prep_send/IOSQE_IO_HARDLINK/submit); (3/3) wdsReap at loop top + handleWorkerReplies SKIP of
  wds-busy clients + freeClient defer (networking.c:2505-2527) + partial/EAGAIN handback. THEN Gates: (1)
  pipeline-order determinism knob ON vs OFF byte-identical reply streams; (2) ASAN churn (connect/pipeline/
  disconnect storm, jemalloc, the [[thredis-asan-repro-recipe]]) — THE gate for the freed-client-CQE/slot-reuse
  UAF class; (3) slow-reader back-pressure (no shard livelock); (4) perf interleaved vs v12-J (expect neutral
  on laptop). Keep DEFAULT-OFF; gate off + document if any gate fails.

PIVOT-2 (2026-06-26, user: "forget version k, work on three stage"): v12-K (worker-direct) is SHELVED. The
work is now "uring-threestage" — a FORK off v12-J in a new worktree /home/henry/Projects/THredis-threestage
(branch uring-threestage, base f5a8285c9). Knob thredis-uring-threestage added (builds). 3-stage io_uring
pipeline: IO thread parses (+STALLED-resume), workers execute+set CDB bit, a dedicated ROB/submit thread PER IO
thread reorders+io_uring-sends+reaps in a TIGHT loop (fixes the v12-K reap-cadence hang). ONE ROB thread/iotid =
sole submitter per fd => NO token (drops v12-K's riskiest code). KEY SIMPLIFICATION: handleWorkerReplies already
coalesces a client's ready slots into ONE real->buf, so the ROB thread does ONE io_uring_prep_send per drain
pass (no hardlink chain). Full design + 5 resolved cross-thread hazards (handoff SPSC, STALLED-resume reverse
SPSC, buffer lifetime, flushid/dispatchid single-writer, close handback) + build plan in
/home/henry/Projects/THredis-threestage/THREESTAGE_DESIGN.md. v12-J stays the working fallback (loopback-NEUTRAL
+4% within noise — its value is correctness/architecture + the real-NIC regime, NOT a loopback win).

THREESTAGE VALIDATED + DONE (2026-06-26, commit e6b8ca676 on branch uring-threestage; Chunk 2 wired). CORRECT:
passes the v12-K killer gate — 50 SET/GET 0 bad, deep single-conn pipeline (3000 SET+3000 GET) errors=0 + sampled
keys 0 bad, memtier -P16 -c40 8s COMPLETES (no abort/hang), no crash; OFF byte-correct. Two stall bugs found via
TS_ROB_DBG instrumentation + FIXED (both = the deep-pipeline/concurrent stall that also explains v12-K's class of
failure): (1) LEAKED SQE — io_uring_get_sqe() advances the SQ tail; the NOSEND `continue` left it unprepped ->
io_uring_submit dispatched it as IORING_OP_NOP (res=0/user_data=0) -> reap's robOutstanding-- for the phantom CQE
desynced the count -> reap gate skipped while real CQEs pending -> ts_inflight stuck=1 -> hang. Fix: check
send-eligibility BEFORE reserving the SQE. (2) RACING writeToClient — AddReplyFromClient -> _prepareClientToWrite
queues real on clients_pending_write; handleClientsWithPendingWrites() runs RIGHT AFTER handleWorkerReplies() in
beforeSleepIO and writeToClient(real)'d the same buf, racing the ROB's io_uring send + zeroing bufpos -> ROB sent
nothing (nosend=99) -> reply lost -> all conns stall pending=16 (memtier aborts). Fix: unlink real from the IO
thread's clients_pending_write[iotid] in the threestage branch so the ROB is the SOLE sender (drove nosend 99->0).
PERF VERDICT: loopback ON 3.79M vs OFF 5.88M ops/s (64B P16 1:9 c40, interleaved 3 reps <2% var) = **-36%**, robust
not drift. EXPECTED + matches the thesis: on loopback w/ tiny replies the SPSC handoff + cross-thread cache traffic
on real->buf + ROB submit/reap syscalls + IO-thread spin-wait (skip~333k) are pure overhead; io_uring send-back
only pays on a REAL NIC / larger values / parse-bound. So threestage is a correct, shippable (gated-OFF) arch whose
WIN MUST BE SHOWN ON THE 7700X (LA)/EPYC w/ a real NIC — NOT loopback. TS_ROB_DBG env gates zero-overhead ROB
counters (send/full/partial/eagain/err/nosend/exhaust/fallback/stale/skip + per-ROB outstanding) for that bring-up.

[SHELVED] PIVOT (2026-06-26): the worker-direct protocol was FULLY IMPLEMENTED (commit-token + hardlink chain + CQE
retirement + IO-thread token-gate + re-scan) but HANGS under deep pipeline — a fundamental REAP-CADENCE problem:
a worker busy executing batches only reaps its own sends between batches, so in-flight sends back up to
~pipeline-depth + throughput collapses (NOT deadlock/corruption — single cmds correct, flushid advances slowly).
Confirmed with BOTH DEFER_TASKRUN and plain ring (so it's cadence, not ring setup). Empirical gates caught what
the adversarial logic-review couldn't (also caught: DEFER_TASKRUN needs io_uring_get_events to reap). User's FIX
= a dedicated ROB/SUBMIT THREAD per IO thread (3-stage: IO-parse -> workers-execute+set-CDB -> ROB-thread
reorder+io_uring-send+reap in a tight loop). KEY: one ROB thread/iotid = sole submitter per fd => DROP the whole
wds_busy token/CAS/recheck machinery (the riskiest code) => the ROB thread ~= the existing handleWorkerReplies
drain on its own thread with io_uring batched sends. Frees the IO thread for pure parsing (the benefit vs v12-J,
which does parse+send both on the IO thread + already WORKS). The worker-direct code is UNCOMMITTED (hangs — do
NOT commit). Full pivot design in /home/henry/Projects/V12K_PROTOCOL_PLAN.md. Also: "IO-thread-free" was a
mislabel — IO thread STILL parses; only send+reorder move off (user correction). v12-J stays the shippable win.

SEPARATE FINDING: the full io_uring stack (v12-G multishot recv) WEDGES on sustained 16KB-value populate —
dbsize stuck 4-19K vs 200K for epoll/redis (recv buffer-ring exhaustion / re-arm under sustained large multi-
chunk writes). Gated/experimental so not blocking default, but v12-G recv needs a buffer-sizing/ENOBUFS fix
before the 16KB io_uring A/B is valid. A/B clean numbers: 64B uring 0.93x epoll, 1KB 0.95x (loopback tax).
