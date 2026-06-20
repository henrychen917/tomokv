# THredis evaluation harness

Load generators, correctness oracles, and benchmark drivers built while developing the
cross-shard (v6/v7) and online-resharding / load-balancing (v8) features. Everything here drives a
running `redis-server` from the THredis tree; start it with `--enable-debug-command local` (the
`DEBUG RESHARD ...` control surface is used heavily) and, for cross-shard tests,
`--thredis-opt-cross-shard yes`.

## Layout

| Path | What it is |
|------|------------|
| `keys.py` | **Bit-exact replica of THredis's seedless xxh64** (`server.c`), so a key can be mapped to its bucket/worker *off the server*. Foundational for worker-targeted load and key placement. Verified against `DEBUG RESHARD FIND` (`python3 keys.py 7800`). |
| `loadgen/cload.c` | **Fast C load generator** (raw-socket RESP + deep pipelining + N threads) that **saturates** the server and **targets one worker's keys** via an embedded bit-exact xxh64. Modes GET/SET/BITCOUNT/mixed. `gcc -O3 -o cload cload.c -lpthread`. This is the saturating client; the Python gens are client-bound. |
| `loadgen/get_loadgen.py` | Pipelined GET load (reads a key list from `/tmp/hot.txt`). |
| `loadgen/bitcount_loadgen.py` | Worker-CPU-heavy load (BITCOUNT over large values). |
| `loadgen/single_key_skew.py` | Hammers a few hot keys — unbalanceable skew (exercises the LB no-progress guard). |
| `validation/cmd_pre_post_migration.py` | Runs **all command families** (strings/bits/hash/list/set/zset/TTL/cross-shard), migrates the keys to another worker, and re-verifies **identical results pre and post** + that a TTL key is **not resurrected**. |
| `validation/mkey_oracle*.c` | Cross-shard MGET/MSET/DEL/EXISTS correctness oracle (compares against a single-key ground truth). |
| `validation/stress.c`, `trace_replay.c` | Churn/stress + CacheLib/Twitter trace replay. |
| `bench/feature_sweep.sh` | Cross-shard fan-out throughput, EWMA efficacy, migration overhead. |
| `bench/place_keys_on_worker.py` | Place N keys (chosen via `keys.py`) onto one target worker to create controlled worker-skew. |
| `CROSS_SHARD_DESIGN.md` | Cross-shard scatter-gather design write-up. |

## Methodology notes (learned the hard way)

- **Worker-targeted skew:** hash sharding scatters keys, so to overload *one* worker you must pick
  keys by hash — `keys.py` / `place_keys_on_worker.py` do this. `memtier` can't (it generates keys
  by pattern), so worker-skew tests use these Python tools.
- **RPS metric:** `DEBUG RESHARD OPS` returns the sum of per-worker monotonic op counters. Poll +
  diff it for throughput — the standard `instantaneous_ops_per_sec` does **not** count
  worker-dispatched commands (reads ~0 under load).
- **3-window migration measurement:** sample RPS *pre / during / post* a single migration to separate
  the migration's cost (measured ≈0 — it runs concurrently at full RPS, zero-downtime) from the
  load-balancer's *benefit* (workload-dependent).
- **Regime matters:** simple GET/SET is **IO-dispatch-bound** unless `myiothreads > myworkerthreads`
  (per the paper); the EWMA load-balancer only raises throughput in the **worker-bound** regime.
- **Load-gen ceiling:** these Python generators can become **client-bound** (~1.5M ops/s on this
  box). For saturating throughput numbers use `memtier_benchmark` or a hiredis-based C generator.

## Caveats
Hardcoded `127.0.0.1:7800` and `/tmp/hot.txt` in several scripts; tune per run. Built against
`THredis-opt-v8`.
