# uring-threestage — 3-stage io_uring reply pipeline (fork off v12-J, K shelved)

Worktree: /home/henry/Projects/THredis-threestage, branch uring-threestage (base = v12-J f5a8285c9).
Knob: thredis-uring-threestage (server.uring_threestage, IMMUTABLE, default 0). DONE (server.h + config.c, builds).

## ARCHITECTURE (user's model)
Stage 1 — IO thread: recv + parse + dispatch + STALLED-resume (UNCHANGED, stays on the IO thread).
Stage 2 — workers: execute fake, build reply into fake->buf, set reply_cdb bit (UNCHANGED).
Stage 3 — ROB/submit thread, ONE per IO thread: in flushid order, reassemble each client's contiguous ready
  prefix onto real->buf, submit ONE io_uring send chain on the ROB thread's ring, reap CQEs in a TIGHT loop,
  retire (advance flushid, commandProcessed, clear cdb bit, replyWorking--).
WHY a dedicated thread (not workers): the v12-K failure was a reap-CADENCE problem — workers busy executing only
reap between batches, so in-flight sends back up and throughput collapses. A ROB thread loops tightly => reaps
continuously => flushid advances promptly. WHY one-per-IO-thread: that thread is the SOLE submitter for that
iotid's connections => single submitter per fd => in-order trivially holds => NO wds_busy token (the big
simplification over v12-K; drops the riskiest code). v12-J (IO thread does parse+send) already works + is the
fallback; the ROB thread's benefit is freeing the IO thread for pure parsing (measure on EPYC; loopback ~neutral).

## THE 5 CROSS-THREAD HAZARDS + RESOLUTION
1. HANDOFF IO->ROB (which clients have reply work): the IO thread dispatch (server.c:4999) already adds the
   client to clients_pending_worker[iotid]. Make clients_pending_worker[iotid] a SPSC handoff: IO thread is the
   sole producer (append at dispatch, dedup via a CLIENT flag so a client is enqueued once), ROB thread is the
   sole consumer (drain + remove + clear the dedup flag when fully drained: flushid==dispatchid). The adlist is
   NOT concurrency-safe -> replace with a per-iotid lock-free SPSC ring of client* (reuse the workerQueue
   structure: client *jobs[]). IO pushes, ROB pops into a ROB-private active-set; ROB re-checks the active-set
   each loop; drops a client when flushid==dispatchid AND no new pushes; dedup flag closes the re-enqueue race
   (lock-with-recheck: ROB clears flag then re-checks mask/dispatchid; IO sets flag via atomic_exchange before push).
2. STALLED-RESUME ROB->IO (the deadlock trap): when the ROB advances flushid freeing a ring slot AND the client
   is CLIENT_PIPELINE_STALLED, the IO thread must re-drive processInputBuffer (re-dispatch) — that is PARSING and
   MUST run on the IO thread, never the ROB thread. ROB pushes the client to a per-iotid reverse SPSC resumeq;
   the IO thread drains resumeq each loop (in beforeSleepIO or the accept-loop) and calls processInputBuffer.
   MISS THIS and pipelined clients deadlock (client waits for reply; IO thread never re-dispatches).
3. BUFFER LIFETIME (real->buf): the ROB thread OWNS the output path (reassemble into real->buf + send + reap);
   the IO thread must NOT touch real->buf/bufpos for a client with a ROB send in flight. Track per-client
   ts_inflight (sends submitted-not-reaped). Retire (flushid++/commandProcessed/buf reset) only on the send CQE
   (plain SEND: CQE == buffer copied out == free). The recv slot reuse is gated by flushid (dispatch stalls at
   dispatchid-flushid==depth), so advancing flushid only at CQE keeps the slot un-reused while the kernel reads.
4. flushid / dispatchid CROSS-THREAD: ROB is the SOLE writer of flushid (release-store); IO reads it (dispatch
   ring-full check) via __atomic_load ACQUIRE (x86: plain mov, byte-identical). IO is the sole writer of
   dispatchid; ROB reads it ACQUIRE. Single-writer each => safe.
5. CLOSE: the ROB thread (its own iotid) has no clients_to_close drainer and must not freeClientAsync. On a send
   error, set ts_close_needed + hand to the IO thread (the IO thread frees it). freeClient defers while
   ts_inflight>0 (mirror v12-J/K). Bump a per-client gen on free; ROB send user_data carries gen; reject stale CQEs.

## REUSE FROM v12-G/H/J/K
- The io_uring send ring setup (plain ring, NOT DeferTR — DeferTR needs frequent get_events which the v12-K
  experience showed is fragile; plain ring lets the kernel progress sends + post CQEs independently). One ring
  per ROB thread.
- io_uring_get_events + io_uring_for_each_cqe reap loop (per v12-K, get_events IS needed to observe completions).
- The contiguous-ready-prefix reassembly = exactly handleWorkerReplies' drain loop (server.c ~2006), minus the
  STALLED-resume (hazard 2). Reuse AddReplyFromClient/csReassemble for the splice; IOSQE_IO_HARDLINK chain +
  MSG_WAITALL for the send (or just one coalesced send of real->buf after splicing all ready slots — SIMPLER:
  splice the whole ready prefix into real->buf like handleWorkerReplies does, then ONE send of real->buf).
  ^ KEY SIMPLIFICATION: handleWorkerReplies already coalesces all ready slots into ONE real->buf; so the ROB
  just does ONE io_uring_prep_send of [real->buf+sentlen, bufpos-sentlen] (no hardlink chain needed — it's one
  send per drain pass per client). Even simpler than v12-K's per-slot chain.
- freeClient ts_inflight-defer + gen (from v12-K).
- Exclude: cross-shard heads/subs, reply-list overflow, replica/master/monitor -> these stay on the IO-thread
  legacy drain (the ROB thread skips them; the IO thread still runs handleWorkerReplies for ineligible clients,
  OR — simpler first cut — ineligible clients are sent by the ROB thread via plain writeToClient fallback).

## BUILD PLAN (gated default-OFF; each step build + validate; v12-J is the working fallback)
1. ioThreadArgs: add pthread_t rob_tid + workerQueue robq + workerQueue resumeq + the per-iotid ROB ring state.
   Client: add ts_inflight/ts_gen/ts_close_needed/on_robq (reuse the v12-K field names if convenient).
2. initIOThreads: when threestage, spawn rob_tid running robThreadMain(t). robThreadMain: set a private iotid,
   build the ROB io_uring ring, tight loop { drain robq->active-set; for each active client: splice ready prefix
   (handleWorkerReplies drain, no resume) + ONE io_uring_prep_send + submit; reap CQEs (get_events) -> retire +
   flushid++ + if STALLED push resumeq; drop fully-drained clients }.
3. dispatch (server.c:4999): push to robq (dedup) when threestage on (in ADDITION to / INSTEAD of
   clients_pending_worker). beforeSleepIO (IO thread): when threestage, SKIP handleWorkerReplies (ROB owns it) +
   drain resumeq (processInputBuffer for each).
4. freeClient: defer while ts_inflight>0; gen bump; ts_close_needed handback.
GATES (TIMEOUT-guard everything; pkill-self-kill + kill-0 hazards): G1 hang/determinism (the 1000-cmd pipe +
pipelined memtier MUST complete, not hang — this is the bar v12-K failed), G2 ASAN churn, G3 slow-reader, G4
perf vs v12-J. Promote only if it beats v12-J on EPYC/real-NIC.

## STATUS: foundation knob added + builds. NEXT: implement steps 1-4 (focused), then gates.
