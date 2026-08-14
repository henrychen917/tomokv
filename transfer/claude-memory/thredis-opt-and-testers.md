---
name: thredis-opt-and-testers
description: "THredis-opt perf-optimization tree, the stress tester, and the SET..EX UAF stability fix"
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

After stabilizing THredis (see [[thredis-worker-argv-refcount-race]], [[thredis-iotid-worker-slot-fix]]), three trees exist under `/home/henry/Projects`:
- **THredis/** — pristine baseline (git clone, commit 8e9a8aea7). CRASHES under churn (the original bug). Don't modify (user's reference).
- **THredis-stable/** — frozen "good" version with the crash fixes. + the SET..EX stability fix (below) was ported in.
- **THredis-opt/** — copy of stable + three perf optimizations: **#3 SPSC index caching** (cached_head/cached_tail in workerQueue), **#6 coalesced reply-ready signal** (one fetch_or per parent per worker batch), **#7 read-run value forwarding** (consecutive same-key CMD_READONLY ops reuse the looked-up value via a thread-local hint in lookupKeyReadWithFlags + workerExecFake/run-detection in workerThreadMain; non-volatile gate so lazy expiry isn't bypassed). All marked //ee451.

**Stability fix (ported to BOTH stable and opt):** `rewriteClientCommandArgument` (networking.c ~5298/5304) had a use-after-free — it `decrRefCount(oldval)` then read `getStringObjectLen(oldval)` in the THredis `update_pcmd` resync block. Fires on `SET key val EX <n>` (the EX->PXAT argv rewrite) on the worker path. Fixed by capturing `oldlen` before the free. User policy: port ONLY stability fixes (not perf opts #3/#6/#7) into the frozen tree.

**Perf verdict (this hardware = Intel Ultra X9 388H laptop, power-throttled, hybrid):** opt is TIED-to-marginally-faster vs stable (within ~±10% thermal noise) on uniform AND Gaussian hot-key memtier. The SipHash hint already captured the expensive lookup cost; #3/#6/#7 shave cross-core/atomic costs that aren't the bottleneck on a throttled laptop. **The paper's real target is Threadripper/EPYC** (many cores, multi-CCD/NUMA) where these cross-core/atomic optimizations should matter more. Re-bench there with `/tmp/ab_optfinal.sh`.

**Testers** (build with bundled hiredis: `gcc -O2 -pthread -I THredis-opt/deps -o X X.c THredis-opt/deps/hiredis/libhiredis.a`):
- `src/redis-pipeline-testv3.c` — user's deterministic per-command-class tester, DISJOINT per-client keys (exact-value oracle). Throttled by a 200ms TEST_DELAY_US.
- `/home/henry/Projects/thredis-stress.c` — new high-throughput adversarial tester. Tests SHARED/hot keys with INVARIANT oracles (race-independent): INCR counters final==issued (WAW); self-identifying values "K=<id>;..." so a GET of key K must return id K (catches torn/RAW/cross-key/reply-misalignment); deterministic private-key forwarding/RYW/alignment; chaos (churn+large values). 26M checks, 0 fails on opt. Caught the SET..EX UAF on first run.
- `/home/henry/Projects/run-correctness.sh` — full suite: stress + v3 + memtier mixed/churn + memtier Gaussian hot-key.

**memtier hot-key recipe:** `--key-pattern=G:G --key-median=<M> --key-stddev=<S>` (small S = few hot keys).
