---
name: thredis-flat-reclaim-capacity
description: FLATSTORE default-on had an OOM-class reclaim-capacity leak under high write rate; fixed by moving QSBR frees to the owning worker (same jemalloc arena) — also +40% p1 SET
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**2026-07-24 — FLATSTORE (default-on) leaked to OOM under sustained high-rate writes; fixed.**
Found by the competitive sweep: tomo's p32 SET / p32 mix / dram / hot cells all read **0.00 ops** with
`-nan` latency while the server was still alive and its internal op counter advanced (~5M/s) — a
WEDGE, not a crash (no assert/segfault). The flip-ctl cron interval stretched 5s → 8 → 14 → 29 → 52 →
97s = main-thread starvation. Diagnosis discipline: the 0.00 tripped the sanity-gate; never reason
from it — stop and repro.

**ROOT CAUSE — reclaim CAPACITY, not correctness.** Every flat overwrite/delete QSBR-retires the old
kvobj; the frees ran on the MAIN thread (beforeSleep → flatReclaimAll). At ~5M overwrites/s that is
~15M frees/s of CROSS-ARENA work on an already-saturated thread, so retires outrun reclaim:
RSS **233MB → 6 → 12 → 19 → 25 → 32 → 38GB in 180s** (~213MB/s) → swap/OOM → main starves → wedge.
Proof it was capacity and not a lost grace: **RSS dropped 38→32GB the instant load stopped**.
Rate-dependent: p1 SET at 580k/s was FLAT (fine); only the 5M/s pipelined cells blew up. Reproduced
identically with thread-modes OFF (static, 54GB/90s) ⇒ nothing to do with the flip controller.

**FAILED FIX (do not retry): bio/lazyfree offload.** Handing ready batches to `bioCreateLazyFreeJob`
made it WORSE (13GB at +30s vs 6GB inline) — bio threads are pinned on the same saturated cores 0-7
and it is *still* a cross-arena free; it only removed the inline backpressure.

**THE FIX — per-worker, same-arena reclaim.** In this sharded design a key's values are allocated AND
retired by the SAME owning worker, so the worker-side free hits jemalloc's thread cache:
- `__thread flatRetireNode **flat_local_sink` (flatstore.h/.c): a worker points it at its own
  retire-list head at the top of every exSlice pass; `flatRetire` pushes there with **no atomics**
  (was a CAS onto a per-table shared Treiber stack — contended across workers).
- `exThread.flat_retire_local` / `flat_batches_local` (server.h): worker-private.
- `flatWorkerReclaim(worker)` in exSlice closes the list into a batch and frees its own graced
  batches. Grace rule UNCHANGED (every live worker's loop_seq ≥ snap + FLAT_QSBR_MARGIN).
- Non-worker threads (main, bio) keep sink==NULL → shared stack → main reclaim (low rate, fine).
- Helpers factored and shared by both paths: flatBatchClose / flatBatchReady / flatBatchFree /
  flatDrainReadyBatches.

**RESULT:** RSS **flat at 228MB** through a 240s p32-SET storm (was 38GB), and it's FASTER:
p32 SET 5.02M → **5.47M**, p1 SET 580k → **810k (+40%)** (removing the contended shared-stack CAS).

**DESIGN NOTE — main must NOT adopt a non-live worker's local list.** An earlier draft did; it is
RACY (main's steal interleaves with a push from a non-live worker still entering exSlice to drain
stragglers ⇒ lost node whose ->next dangles onto a freed one ⇒ double free). Adoption is also
unnecessary: a PARKED worker runs no exSlice so executes no commands and creates no new retires; a
converted EX→IO worker still reaches exSlice to drain stragglers so it keeps draining itself. The
residual is therefore BOUNDED (one pass of retires + ≤2 un-graced batches), freed on resume. Keeping
the list strictly worker-private is what makes the hot path atomic-free.

**SHIPPED: origin/2s-numa-shared-kv-dev @4ef904d07 (2026-07-25).** Final design after a 20-agent
adversarial review found 2 CRITICAL UAFs in the first cut:
- The grace must cover **every non-worker thread**, not just main. Clients are pinned to the io
  thread that ACCEPTED them (per-thread SO_REUSEPORT listeners), so SAVE / DEBUG DIGEST / DEBUG
  RELOAD execute inline on that io thread — an `iotid == 0` gate is inert exactly where the walks
  happen. Now a per-io-identity `tm_io_sig[t].in_flat` REGION flag.
- Use a FLAG, never a beforeSleep COUNTER: a counter cannot advance while the thread is inside a long
  command, so it pins the grace and stalls reclaim forever (== the OOM wedge, re-created).
- Region markers (not whole-phase): `call()`, performEvictions, activeExpireCycle, prepareForShutdown
  AND the deferred finishShutdown path. Whole-phase marking of main costs 17%; region-scoped 0.2%.
- Workers never execute `call()` (exExecFake runs cmd->proc directly) => guard is free on the hot path.
- False sharing of the new worker fields with loop_seq/in_flat_section is now enforced by a build-time
  `_Static_assert` — a first "just move them to the end of the struct" attempt did NOT separate them.
FINAL: p32 SET 5.42M (physical-shard 5.2M), p32 GET 7.97M, RSS flat 223-228MB through a 240s storm,
correctness 15/15, ASAN clean, 7-min hostile stress (72 grow-front/70 grow-back) clean.
NOT VALIDATED on multi-CCD/NUMA: remote-flag reads in flatBatchReady + tcache-drain magnitude are
single-CCD (7700X) results; re-measure on the Threadripper target.

**HARNESS TRAPS HIT THIS SESSION (all produce FALSE 'validated'):** rebuilding the binary while a
benchmark runs from it; a test script never chmod +x (silently skipped); chained waiters using
`pgrep -f <script>` that match their OWN command line and deadlock; server logfiles APPEND, so a
previous run's crash markers read as this run's failure (check by pid/timestamp); and a sloppy
comment edit that swallowed `flatReclaimAll(); flatResizeCoordinate();` — compiled clean, disabled
reclaim AND resize, panicked at the initial 262144 slots. Only the end-to-end run caught the last one.

**LESSON (generalizable):** a QSBR/RCU reclaimer must run where it has both the CYCLES and the right
ALLOCATOR ARENA. Centralizing frees on one thread is an OOM-class scalability bug that only appears
above some op-rate threshold — and it will look like a hang/wedge, not a leak, because the server
stays responsive until it swaps. See [[thredis-flatstore]] and [[thredis-flip-controller-momentum]].
