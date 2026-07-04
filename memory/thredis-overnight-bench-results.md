---
name: thredis-overnight-bench-results
description: "Overnight 5-system bench + stability + threestage thread-combo sweep (2026-06-27) — numbers, the i4w2 finding, stability verdict"
metadata:
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

Overnight sweep 2026-06-27 (laptop loopback, server c0-7, loadgen c8-15, jemalloc; dragonfly=mimalloc; 3 interleaved
passes/median, T=12s). Full report + raw TSVs in /home/henry/Projects/overnight_sweep/ (REPORT.md, main_labeled.tsv,
combo.tsv, leak.tsv, run.sh). Systems: v11-epoll (THredis), v12-J (THredis-v12 --thredis-io-uring-reply-send),
threestage (THredis-threestage --thredis-uring-threestage), redis (--io-threads 8), dragonfly (--proactor_threads=8).

HEADLINE (64B P16 1:9 MED1M, median ops): v12-J 4.90M ≈ v11 4.65M > redis 4.23M ≈ dfly 4.14M > **threestage(i4w4) 3.17M**.
threestage is slowest in 7/8 cells on loopback w/ **4-6× worse p99** (6.18ms vs 1.1-1.7ms) — the dispatch-bound ROB-hop
tax the thesis predicts. **v12-J ≈ v11 on loopback (geomean 0.992, 4-4 split)** — io_uring reply-send is a loopback wash
(matches [[thredis-v12-sweep-results]] / [[iouring-dbms-paper-guidelines]] GL1: io_uring helps only when I/O-bound).
threestage deficit SHRINKS with value size: -35%(64B) → -25%(1KB) → **-8% PARITY at 16KB** (311k vs redis 336k; tails
converge ~12-13ms) — per-op hop amortizes vs memcpy/bandwidth. cache→DRAM (64B SMALL50k→LARGE5M): v11 wins cache 5.20M
but worst retention (-17.9%) → ties v12-J at DRAM; v12-J retains best (-7.1%). dragonfly most value-size-sensitive (1st
at 64B-write, last ≥1KB). NOTE the 4 non-TS systems are WITHIN the ~15% drift floor at 64B → NOT rankable vs each other.

THREAD-COMBO finding (the user's ask; threestage I/W sweep, each +I ROB threads): **canonical i4w4 is NEVER optimal.**
64B P16: i4w2=5.47M (+48% vs i4w4), i6w2=5.24M >> i4w4=3.70M >> i8w8=1.19M (24thr/8core, 3× oversub = catastrophe).
**Small-pipelined wants FEW workers (w2) + MANY io/ROB** — 2 workers saturate the GET-heavy keyspace; extra workers add
ring/cache churn (i4w6 = 55% of i4w4). Throughput tracks io/ROB count, not worker count. Optimum is WORKLOAD-DEPENDENT:
unpipelined latency (64B P1) → i2w4 (626k @ 0.55ms p99); tail-sensitive P16 → i2w2 (4.49M @ 1.71ms, best tail);
max-QPS → i4w2 (5.47M @ 3.78ms); large values flatten (16KB i4w4 already 98% of best). i4w2's "+20% vs v12-J" is a
thread-count artifact — even tuned, i4w2 p99 3.78ms > v11 1.14ms, so threestage still loses on TAIL at 64B. Genuine TS
wins = 16KB parity + proving worker-count (not architecture) drives the small-value gap. NEVER run i8w8 or i4w6.

STABILITY (all clean): crash=0 across all 120 MAIN + 84 COMBO cells. CHURN reconnect-storm (small keyspace + write-heavy
+ reconnect-interval, the argv-refcount-UAF trigger [[thredis-asan-repro-recipe]]): threestage & v12-J each 80 iters, no
crash, worker-ring live (probe via SET not PING — PING is inline & masks a wedged ring). **ASAN threestage 134 iters
ASAN-clean** (no UAF/heap-corruption in the new ROB code; but detect_leaks=0 so NOT a leak proof). **LEAK (corrected RSS,
real redis-server PID): threestage NO LEAK** — RSS 378→417MB plateaus, 2nd-half +7MB over ~480M ops ≈ 0.015 B/op. v12-J/
v11 leak curves were completing (expected clean). v11-epoll has no ASAN coverage; redis/dragonfly no stability runs.

HARNESS GOTCHAS (cost real time, reuse next sweep): (1) memtier Totals cols: $2=ops $5=AVG.lat $6=p50 $7=p99 (NOT $5=p50).
(2) script launched after `cd` has cmdline "bash run.sh" (RELATIVE) → pkill/pgrep -f with ABS path silently no-ops →
4 zombie runs collided on the port; use `pgrep/pkill -fx 'bash <abspath>'` or exact 'bash run.sh'. (3) backgrounded
`case…esac &` makes $! the bash SUBSHELL pid (~4MB RSS), not the server → RSS leak-sampling read the wrong PID; sample
via `pgrep -x redis-server`. (4) liveness probe must be SET (worker ring), not PING (CMD_FAST inline). (5) dragonfly comm
truncates to 'dragonfly-x86_6' (15 char) → pkill -x dragonfly misses it. (6) gentle -P4 populate (high-P wedges worker
ring). The adversarial-review workflow caught #1/#2/#4/#5 BEFORE the run — do that for every unattended sweep.

VERDICT: threestage is a correct, memory-safe, gated-OFF arch that LOSES on loopback small-value (expected) and reaches
parity at 16KB; its real-NIC/parse-bound payoff is UNTESTED here (loopback structurally can't show it). Next: real-NIC +
EPYC eval (re-run combo sweep there — i8w8/i4w6 cliffs are 8-core artifacts), extend ASAN/CHURN to v12-J & v11.

FOLLOW-UPS (2026-06-27, post-sweep, user-directed):
1. ROB-THREAD COUNT DECOUPLED from io-thread count (commit 7b5da47c6, branch uring-threestage). New knob
   `--thredis-rob-threads R` (0=legacy one-ROB-per-io-thread). R ROB threads each drain a disjoint subset of the
   per-io-thread robqs (ROB r serves io i where (i-1)%R==r), own ring/outstanding per ROB; SPSC + per-client order
   preserved; clamped to [1, io_threads-1] (1 robq/io = SPSC, extra ROBs idle). Validated 4io/4w: R=1/2/3/0 correct
   (0 getbad, deep-pipe errors=0, -P16 c40 no stall/abort, no crash) + ASAN-clean R=1 & R=2 (40 churn iters each).
   **FINDING: FEWER ROB threads WIN on the 8-core laptop — R=1 (one ROB, one io_uring ring batching ALL clients'
   sends into one submit syscall) = 5.05M ops @64B P16 c40 vs coupled R=3 = 3.84M (+33%).** The per-io-thread ROB pool
   was over-provisioned: dedicated send threads steal cores from parse/workers, and one ring already amortizes the
   submit syscall across all fds. So the combo story updates: the earlier "i4w2 best" (4 coupled ROBs) is beaten by
   decoupling to ~1 ROB. TODO: re-run combo×rob-threads matrix (esp. R=1 vs R=2) at realistic sizes + on EPYC.
3. STRICT PIPELINE (user: "do io to worker to rob, communication strictly this way") — branch
   uring-strict-pipeline, worktree /home/henry/Projects/THredis-strict, WIP commit 71a8f9dae. Knob
   thredis-strict-pipeline (default off). FULL refactor: ROB owns reorder+reassemble+RETIRE+send; IO =
   pure ingress (parse/dispatch + push a 'watch' to its ROB at first-in-flight). Solved the hard blocker:
   per-iotid freeback ring is keyed by thread-local iotid, so the ROB retires on its OWN iotid
   (my_io_threads+1+rob_id) + freebackDrainAll range extended. Pieces: ROB active-set (on_robq dedup),
   robSpliceFake (stripped _addReplyToBufferOrList, no pending_write), watch deferred to AFTER
   dispatchid++ (else ROB reads stale dispatchid==flushid and prematurely retires), STALLED-resume
   (markStalled->clients_pending_worker reuse + replyWorking; beforeSleepIO processInputBuffer when ROB
   frees ring space), iotid 0 -> legacy drain, freeClient defers while on_robq. **STATUS: WORKS at P16
   (single SET, 40-key integrity 0 bad, memtier -P16 c40 = 3.5M ops no abort/crash) BUT deep-pipe (>32
   ring-full) HANGS + SEGVs (processCommand on IO thread, re-dispatch racing ROB retire on fakeClients
   ring / freed-client deref in resume snapshot). EAGAIN-resend + done-check-unsent fixes were necessary
   not sufficient. This is the per-iotid retire/close hazard class (shelved v12-K). NOT benchmarked (won't
   present perf from a crashy build). Needs a focused debug session — likely: the IO re-dispatch must not
   reuse a fakeClients slot the ROB is concurrently retiring, OR the resume snapshot derefs a freed
   client. uring-threestage (the shipped, working one) is UNAFFECTED.**
   STRICT NOW WORKS (commits: 23e4380c6 deep-pipe fix, 83729ab7f wedge fix, 0718fb7b3 epoll). Bug A: the
   ring-full stall site missed markStalled (8-space indent vs the replace_all's 12-space) -> deep pipe
   never re-dispatched -> hang. Bug B: P32+reconnect-churn WEDGE — the ROB removed a client from its active
   set the instant it was transiently idle, so deep-pipe+reconnect re-watched every stall/resume cycle ->
   flooded the robq -> the dispatch `while(!robqPush)sched_yield()` spun -> IO wedged. FIX = WATCH-ONCE +
   KEEP-WHILE-LIVE: the ROB keeps a LIVE client watched for the whole connection, removes only on close;
   dispatch pushes the watch ONCE (skip if on_robq). Validated: P16, deep --pipe (single+8 parallel+6/6 under
   ASAN), P16+P32 reconnect churn 25 iters native (flat RSS, no leak/crash). ASAN deep-pipe 0 errors; ASAN
   reconnect-churn dies silently (no ASAN report / no dmesg OOM) = ASAN free-quarantine filling under rapid
   client churn (artifact; native is leak-free). EPOLL ABLATION (knob thredis-rob-epoll): ROB sends via raw
   write() not io_uring (same 3-stage) -> isolates io_uring vs triple-thread. Prelim 64B P16 c40 loopback:
   strict-uring 3.49M, strict-epoll 3.32M (io_uring ~+5%), both < v11-epoll ~5.3M -> on loopback small-value
   the 3-stage HOP costs more than io_uring recovers. The 2x2 (3stage x {uring,epoll}) + v11 baseline is the
   real-NIC eval apparatus.
   PROFILING (perf stat/record, 64B P16 c40, matched configs): the "3-stage slower" was OVERSUBSCRIPTION
   (i4w4 = 9 threads/8 cores). At matched best (strict i4w2+rob1 = 7 threads) strict TIES/edges v11
   (5.6-5.9M vs 5.65M). Per-op: strict 3987 instr/op IPC 1.52 cachemiss 3.51 vs v11 1649 instr/op IPC 0.50
   cachemiss 0.43 -> strict does 2.4x instr + 8x cachemiss but 3x IPC; **v11 is MEMORY-BOUND at 8 cores
   (IPC 0.50, out of headroom); strict has IPC headroom -> the precondition to scale better with cores**.
   v11 barely scales 4->8 cores (+13%) = loopback-saturated. ZERO-COPY writev REVERTED per user ("don't axe
   the batched-submit copy / don't regress algorithmic improvements") -> kept proven copy+coalesce+batched-
   submit, ADDED the 2-pass prefetch the strict ROB was missing (knob thredis-opt-prefetch-io, default off;
   commit e27f0538d). STRICT PERF SWEEP (medians, 3 passes, 64B P16 1:9; strict i4w2+rob1 vs v11 i4w4; cache=
   50k DRAM=5M; report /home/henry/Projects/overnight_sweep/STRICT_PERF_REPORT.txt + strict_perf.tsv):
   64B: s_epoll 5.08M(cache)/4.42M(dram) > v11 4.93/4.19 ≈ s_uring_pf1 4.96/4.24 > s_uring_pf0 4.54/4.00.
   256B: all ~4.0-4.3M (tie). 1KB: v11 1.98/2.10M > strict ~1.7-1.8M (i4w2 worker-bound at big values).
   **KEY ABLATION ANSWER: on loopback the gains are from the TRIPLE-THREAD, NOT io_uring — 3stage+epoll >=
   3stage+uring (io_uring submit/reap = a loopback TAX on tiny sends), and 3stage+epoll BEATS v11 at 64B.**
   io_uring expected to flip to a WIN on a real NIC (expensive send). prefetch helps 64B only (pf1>pf0),
   neutral/neg >=256B -> value-size-gated, left off.
   ROADMAP (user: do on BOTH uring-strict-pipeline AND the stable epoll branch = v12/stable; mask machinery
   byte-identical across branches -> implement once, land on both): #74 depth->1024 (multi-word mask
   uint32_t->uint64_t[16]) + #75 num_cdb->256 scaling w/ worker count (same mask subsystem -> do together,
   MUST skip-empty CDBs in cdbCombinedMask else 256x16 words/drain), #76 restore full command support. NOTE:
   widens the HOTTEST struct -> re-check instr/op + cachemiss/op after, don't regress the base. NOT STARTED.
   INSTR/OP BALLOON ROOT CAUSE (perf record -e instructions, v11 vs strict matched i4w2, both ~5.6M ops):
   strict's 2.4x instr/op (3987 vs 1649) is DOMINATED by JEMALLOC CROSS-THREAD FREE (~17% of strict instr;
   <2% in v11): je_free_with_usize 4.8% + je_malloc_with_usize 4.3% + je_tcache_bin_flush_small 3.5% + zfree
   2.5% + tcache_bin_flush_edatas_lookup 2.4%. CAUSE: moving RETIREMENT (argv/fake free) to the ROB thread
   broke v11's same-thread alloc/free locality — v11 allocs a cmd's argv on the IO thread (parse) + frees on
   the SAME IO thread (retire) = jemalloc tcache HIT; strict allocs on IO/worker but frees on the ROB =
   CROSS-THREAD free -> can't use tcache, must flush bin + return to originating arena. WORST overhead for
   the scaling goal (degrades w/ cores+NUMA). Rest of balloon: ROB drain machinery (robStrictDrainClient+
   handleWorkerReplies+cdbCombinedMask+robq) ~6%. FIX (high leverage, keeps the arch): restore same-thread
   alloc/free locality for retirement — (a) POOL/REUSE the fake argv (no per-req alloc/free; extends v11-A
   operand pooling), OR (b) hand argv back to the owning IO thread to free via a ROB->IO ring (mirrors the
   VALUE freeback). THIS is the #1 3-stage perf optimization. (Commands restored a8e925d15: cross-shard MSET/
   MGET worked after fixing pending_write[ROB_iotid] NULL; sub-fake pool imbalance leak = TODO.)
   MITIGATION EXPERIMENTS (user ideas, strict i4w2 instr/op): jemalloc tuning (background_thread/big tcache/
   narenas) = NO help (3954-3991; narenas:1 + decay0 broke startup); libc = WORSE (4135, 4.84M); MIMALLOC =
   small win (3868 instr/op, 5.85M ops, ~+2% free via LD_PRELOAD=/usr/lib/libmimalloc.so.3 — worth keeping but
   does NOT close the gap to v11's 1649); tcmalloc inconclusive. CONCLUSION: no allocator eliminates the
   cross-thread free (inherent to free-on-a-different-thread). The REAL fix = "don't dealloc, reuse" (POOL the
   fake argv + per-command allocs per fakeClients[slot], retire resets in place, ROB touches no allocator) ->
   removes the ~17% AND scales flat. That's the optimization to build next (extends v11-A operand pooling).
   PRECISE ROOT CAUSE (read the code): v11-A operandPool (networking.c:3984 operandPool[MY_IO_THREADS_MAX+1]
   [OPERAND_POOL_CAP], indexed by THREAD-LOCAL iotid; operandPoolGet at parse line 4195, operandPoolPut at
   retire line 6595). It kills per-req argv alloc/free ONLY when parse+retire are the SAME thread (v11). The
   3-stage SPLITS them: parse gets from operandPool[IO_iotid] -> pool drains -> miss -> MALLOC; retire on the
   ROB puts to operandPool[ROB_iotid=my_io_threads+1+rid] -> pool fills to cap -> overflow -> FREE. = malloc
   on IO thread / free on ROB = the cross-thread balloon. FIX (forked branch uring-strict-pool, worktree
   /home/henry/Projects/THredis-strict-pool, base a8e925d15; plan in its POOLING_PLAN.md): a ROB->IO SPSC
   operand-recycle ring (mirror the VALUE freeback): stamp client owner iotid (or use robq source qi); at ROB
   retire, push the operand robj to recycleRing[owner_iotid] instead of operandPoolPut(thread-local=ROB); the
   IO thread drains it + operandPoolPut into ITS pool (no race) -> parse hits the pool -> no malloc/no cross-
   thread free. Gate: instr/op must drop ~3900->~1650. NOT YET IMPLEMENTED (forked + scoped only). ARCH-MATRIX
   bench running (2-stage{v11,v12-J} vs 3-stage{epoll,uring} x jemalloc/mimalloc, ops + instr/op): /home/henry/
   Projects/overnight_sweep/arch_matrix.tsv.
2. PAYLOAD REALISM (user: "16k is too big"): CONFIRMED via the Twitter cache-traces on-box
   (/home/henry/Projects/cache-trace/samples/2020Mar/clusterNNN; CSV cols ts,key,key_sz,val_sz,client,op,ttl).
   cluster001: mean **356B**, 85.9% in 257-512B, 7.8%<=64B, ~0% >1KB. cluster010: mean 1266B, bimodal 62%<=128B +
   38% 1-4K, ~0% >4K. So real value sizes live in **~64B-2KB, centered sub-1KB**; 16KB was an outlier "where does the
   ROB-hop tax vanish" probe, NOT typical. NEXT sweep should use 64/128/256/512/1024 (drop 16KB to a single tail
   point) and GET-heavy 1:9 (traces are read-heavy). Decision pending: run realistic+rob-threads sweep on laptop now
   vs hold for 7700X/EPYC (real-NIC is the regime that actually tests threestage's value).
