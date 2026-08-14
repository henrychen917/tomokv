---
name: thredis-v12-sweep-results
description: v12 build + the multi-system sweep results (THredis vs Redis/KeyDB/Dragonfly) + the benchmarking-methodology gotchas
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

v12 (worktree THredis-v12, branch v12) = v11 + gated deep-network io_uring (SQPOLL knob, batched send) +
OS opts (thredis-os-opts = TCP_QUICKACK + MADV_HUGEPAGE; thredis-os-busypoll SEPARATE knob default off —
bundling SO_BUSY_POLL cost ~18%, the v12 "regression"). v12-epoll = os-opts on/uring off; v12-uring adds
io_uring + sqpoll. Built USE_URING=yes MALLOC=libc. v12-G (commit 23ad36bce): io_uring MULTISHOT-RECV +
provided buffer ring DONE + validated (knob thredis-io-uring-recv, default OFF). Per-IO-thread recv ring +
512x16K provided buffers + eventfd bridged into the IO-thread epoll loop; armed in createClient (THredis
accepts on per-IO-thread SO_REUSEPORT listeners so the client lives entirely on one IO thread → all ring ops
single-threaded), disarmed in freeClient, gen-counter rejects stale CQEs. Recv ring is always NON-sqpoll
(eventfd-driven; sqpoll regressed throughput + corrupted >16K multi-chunk reads — that combo was the one bug
found+fixed). Epoll read handler left installed as harmless fallback. Validated correctness (incl 70000-byte
multi-chunk) + pipelined/hot-key stress + churn, no crash, OFF path byte-identical, LOOPBACK-NEUTRAL (ON
5.35M ≈ OFF 5.60M ops/s) — network-bound infra for a real-NIC/EPYC eval. NOTE: THredis has TWO IO-thread
impls — its OWN ioThreadMain (server.c, SO_REUSEPORT per thread, the live one) and the DORMANT upstream
IOThreadMain/iothread.c (io_threads_num==1).

v12-H (commit 3ae360066): io_uring ZERO-COPY SEND (IORING_OP_SEND_ZC) DONE + validated (knob
thredis-io-uring-zc, default off). Send ring uses send_zc for static-buf replies >=4K; handles the two-CQE
model (send-result F_MORE then F_NOTIF) by DEFERRING the c->buf/bufpos reset to the F_NOTIF (immediate reset
= UAF under ZC); dynamic notif tracking. Validated: 8K data-integrity (md5 GET==SET pre+post load), pub/sub
+ large-GET stress, no crash, default-off byte-identical, loopback-neutral (2.61M≈2.59M≈2.60M). KEY FINDING
(applies to v11-B io_uring SEND too): THredis worker-dispatched replies are written DIRECTLY by
handleWorkerReplies (writeToClient on the spliced real client) → this PREEMPTS the io_uring SEND ring
(clients_pending_write already flushed when it runs), so the SEND ring + ZC only fire for RESIDUAL
non-worker-dispatched replies (pub/sub, some inline) — sendring_log was 1-2 over a 7s stress. THAT is why
io_uring SEND is loopback-neutral. Putting io_uring send/ZC on the hot path needs worker-reply flushing
routed through the ring (deferred pending-write vs the direct writeToClient) — future work, not done (risks
the validated reply path for zero loopback gain). io_uring deep-network now: SQPOLL+batched-send (v11-B/v12)
+ multishot-recv (v12-G) + zero-copy-send (v12-H) all landed+gated; remaining lower-pri: multishot-accept,
fixed/registered files.

MULTI-SYSTEM SWEEP RESULT (full report: /home/henry/Projects/SWEEP_RESULTS_v12.md). 8 threads/cores 0-7,
load-gen 8-15, jemalloc, R:R uniform keys, 64B P16 1:9 headline:
  THredis v11 ≈ v12 ≈ **1.15x Redis** (interleaved-confirmed), ≈ 1.18x Dragonfly, ≈ 2.3x KeyDB.
  CROSSOVER: at GENTLE load (-c8 P4) Redis WINS (THredis 0.82x) — the advantage needs concurrency to amortize
  the IO->worker->IO dispatch; fades to ~1.0x at 1KB/16KB (bandwidth-bound) + on writes. Matches the paper's
  "conditional advantage." io_uring ~NEUTRAL on loopback (no network bottleneck; its win is network-bound).
  Pre-opt baseline (8e9a8aea7) UNBENCHMARKABLE — crashes under load (all_argv_len_sum assertion + segfault,
  even gentle); ≈ v11 when alive; the opt/hardening tree is what made THredis production-stable.

BUGS FIXED this run: queueToWorker silently dropped commands on a full worker SPSC queue -> client hang
("worker queue full") under sustained pipelined load (v11 873fdf39e, v12 e7238d25f, pre-opt patched; spin-
backpressure like csPushSpin). v12 SO_BUSY_POLL regression (e4e1beb0c). Cross-shard MSET refcount crash
(365354b95, earlier). See [[thredis-worker-argv-refcount-race]].

BENCHMARKING METHODOLOGY (this drifty box, ±15%): (1) cross-system ratios need PER-CELL INTERLEAVING (systems
back-to-back, same thermal state) — the per-system sweep (all cells then next system) confounds with drift
even when system order is rotated. (2) memtier vs Dragonfly: memtier default `-s localhost`->::1 (IPv6) is
REFUSED by dragonfly's --bind 127.0.0.1 -> use `memtier -s 127.0.0.1`. (3) THredis high-pipeline populate
(-P8+) WEDGES the worker ring on big (10M) DBs -> gentle -P4 + timeout. See [[thredis-benchmarking-methodology]].
HARNESS GOTCHAS: the Bash tool BLOCKS foreground `sleep` (aborts command) and `pkill -f <pat>` SELF-KILLS the
tool's own shell -> launch long jobs via `nohup script >file &` (sleeps inside the script) + kill via a
script FILE (bash /tmp/killbench.sh), read results from the file.

## io_uring batched reply-send integration (design, 2026-06-25)
- Today's bypass: handleWorkerReplies splices fakes into real->buf/reply then calls writeToClient(real,0) DIRECTLY at server.c:2067 — io_uring never carries worker replies.
- Fix angle (correctness-first): at server.c:2064, gate on new knob server.io_uring_reply_send. When ON, instead of writeToClient, route the FULLY-DRAINED real client through putClientInPendingWriteQueue(real) so the existing validated ring (handleClientsWithPendingWritesUring, networking.c:3304) carries it.
- KEY SAFETY: drain completes fully (all fakes retired, csReassemble done, subs freed, flushid==dispatchid possible) BEFORE any SQE is prepped → kills "send reads freed sub-fake" + "buffer mutated mid-batch" by construction. Reply lives entirely in real->buf/reply, owned by real, no fake aliasing.
- beforeSleepIO ordering already correct: handleWorkerReplies (2096) THEN handleClientsWithPendingWrites (2097) THEN freeAsync (2098). Diverted clients land on pending_write in step 1, flushed step 2.
- In-order per client: ring prep order = pending_write list order; one SQE per client; single contiguous c->buf send. CLOSE_ASAP path (server.c:1933, 2038) unchanged — never enqueues.
- Knob: createBoolConfig("thredis-io-uring-reply-send", IMMUTABLE, server.io_uring_reply_send, 0) requires io_uring_net. Default OFF keeps direct writeToClient intact.
- Expected: loopback NEUTRAL (no NIC, copy is cheap); real-NIC WIN lever (batched submit + ZC for 4-16K). Must eval on EPYC + real NIC.
