---
name: thredis-canonical-forks-and-dfly-port
description: "Canonical forks (pool=main 3s, v12=main 2s, epoll/uring as knobs) + Dragonfly-port verdicts (#1 skip,"
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

Per user 2026-06-28: maintain TWO canonical forks; every shared opt/fix lands on BOTH going forward.
- **3-stage = pool fork** (worktree THredis-strict-pool, branch 3stage-ifid-ex-wb-pool). Strict SUPERSET: tiered operand pool gated by `--thredis-operand-pool-tiered` (pool-off == the plain-strict fork); WB backend epoll/uring via `--thredis-wb-epoll`. The plain-strict fork `3stage-ifid-ex-wb` is now subsumed.
- **2-stage = v12 fork** (THredis-v12, branch 2stage-io-ex-uring). epoll/uring reply-send via `--thredis-io-uring-reply-send` (off == old stable/v11). stable/v11 `2stage-io-ex` subsumed.
- **RULE:** any optimization/fix that applies to both → add to BOTH (pool 3s + v12 2s).

**Dragonfly-port verdicts** (workflow-grounded in THredis code, 2026-06-28; Dragonfly src at /home/henry/Projects/dragonfly-src, helio at helio-src):
- **Pinning — DONE both forks.** helio-style affinity-set-aware: capture the allowed cpu set ONCE (cached, before any thread narrows its own affinity), compact to dense, round-robin pin within it (respects taskset/cgroup). pool `fe459c55a`, v12 `9bd1a1d3c`. Fixes the old `core_idx % NPROC_ONLN` (absolute cores) that floated threads outside a taskset → **the 10/12-thread oversubscribed sweeps were POLLUTED; re-run for clean data.** See [[thredis-threadcfg-sendbound]].
- **#1 command squashing — SKIP (wash).** The cross-CCD `tail` release-store is ALREADY batched (flushExQueues, once per pipeline). getWorkerForCommand = uniform xxh64 → same-worker run-length ≈1.07 → nothing to squash on real/uniform workloads (same dead-end as [[thredis-forwarding-deadend]], run=1.008). Only helps hash-tag-clustered pipelines THredis doesn't target. Don't implement (or gated-off negative result).
- **#3 EX next-op dict-bucket prefetch — REAL small win, TODO both forks.** Current prefetch only warms already-popped fakes; no look-ahead to hide the CURRENT op's bucket DRAM miss. Add `prefetch_dict`/`prefetch_bucket_idx` to client, store in exPrefetchBatch pass-2 (server.c:~9956, bucket math already there), prefetch next D fakes' bucket line in the exec loop (server.c:~10411). Knob `thredis-pf-w-nextop`. Only thing attacking the big-DB cache-miss regime (benches show neither arch hides it). Unproven on this laptop (thermal drift) — validate EPYC + ≥10M-key DRAM, interleaved. Effort S.
- **#4 server.dirty de-contention — DONE both forks (pool `6bda15530`, v12 `4a1c20657`), 2026-06-28.** Sharded `server.dirty` per-thread (`dirty_shard[ifidx]` pool / `[iotid]` v12, cache-line padded, MY_IFID vs MY_IO max). Was 108 write sites (not ~20) → all routed through `markDirty(n)`; `DIRTY_LOCAL` for the call()/in-command deltas; `getDirty()` fold for save-point/INFO/bgsave-snap; `resetDirtyCounter()` re-baselines (server.dirty doubles as fold baseline so the bgsave SUBTRACT at rdb.c:4148 is unchanged). Knob `thredis-opt-perthread-dirty` IMMUTABLE default OFF (= byte-identical). Validated A/B OFF==ON: dataset value-hash identical, counter identical (12501) + resets to 0 on SAVE, write-heavy 5-6M ops/s with counter exact at 30M (torn-++ gone), 0 crashes.
  - **Finding:** in THredis ALL modes (strict AND non-strict), commands execute via `exExecFake`→`cmd->proc` direct — they BYPASS `call()`, so AOF/repl propagation is a pre-existing NON-feature (incr.aof stays empty, changes via the per-shard counter only). So the call()-delta change is logically-correct but inert here; its real exercise is only AOF-replay/loadaof.
  - **Pre-existing bug surfaced (NOT #4, fires in OFF mode too):** `DEBUG LOADAOF` / AOF-base reload aborts `Guru Meditation: Duplicated key found in RDB file #rdb.c:3998` (loadAppendOnlyFiles→rdbLoadRio into the sharded DB double-inserts). RDB/AOF reload into shards is broken — separate task if persistence is ever needed.
  - Also: DEBUG DIGEST returns all-zeros in THredis (traverses main-thread dict; keys live in worker shards) → NOT a valid correctness oracle; use client-read value-hashing instead.
