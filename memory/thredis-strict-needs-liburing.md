---
name: thredis-strict-needs-liburing
description: THredis strict-pipeline/3-stage REQUIRES USE_URING=yes build; without liburing it silently hangs (now guarded)
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

THredis `thredis-strict-pipeline` and `thredis-uring-threestage` (the 3-stage ifid/ex/wb forks) **must be built with `make USE_URING=yes`** (defines HAVE_LIBURING, links `-luring`). liburing 2.14 is installed on this box.

**Why:** the entire write-back (wb) thread — `wbThreadMain`/`wbRun`/`wbDrainClient` + the dispatch "watch" push — lives under `#ifdef HAVE_LIBURING`. A plain `make -j4` (no USE_URING) compiles the WB out, so strict mode silently falls back to a WB-less legacy drain that **hangs the first connection on each ifid thread** (~N-1 single-command-per-connection hangs; masked under pipelining + steady-state load, so memtier/benches never catch it). This is exactly the "37% reply race" chased on 2026-06-27 — it was a BUILD artifact, not an algorithm bug.

**How to apply:** always build the 3-stage forks with `taskset -c 8-11 make USE_URING=yes -j4`; verify `ldd src/redis-server | grep uring`. As of 2026-06-27 `initIfidThreads` has a guard (commit f3e90ed4c on branch 3stage-ifid-ex-wb) that `exit(1)`s with a FATAL message if strict/threestage is enabled without HAVE_LIBURING — wrong builds now fail fast. The 3-stage reply path itself is CORRECT under USE_URING=yes (validated 0/50 single-INCR hangs on both io_uring and epoll WB backends). Guard + the io→ifid/worker→ex/ROB→wb rename still need propagating to the sibling 3-stage forks (3stage-ifid-ex-wb-pool, 3stage-wb-sendonly). See [[thredis-v12-sweep-results]], [[thredis-asan-repro-recipe]].
