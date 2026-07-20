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
| `xshard_corruption.sh` | **Cross-shard data-integrity gate.** Heavy cross-shard churn (RENAMENX/COPY/SMOVE/LMOVE/SINTERCARD/ZINTERCARD) + concurrent memtier load, then verifies 200 untouched canary keys are byte-exact. `VERDICT: PASS` = 0 corrupt. Env: `PORT`, `REDIS_CLI`, `MEMTIER`, `IO_THREADS`, `EX_THREADS`. |
| `xshard_intercard.sh` | **SINTERCARD/ZINTERCARD count-correctness** over cross-shard keys — every LIMIT/disjoint/ordering/3-set edge; asserts SINTER and SINTERCARD agree. |
| `mass_kill_stall.sh` | **Mass-hard-kill teardown-stall metric.** Under cross-shard churn + a kill-9 storm, measures PING recovery time per trial. Current design: transient stall, always recovers (worst a few s); a `WEDGED` trial is a real regression. This is the before/after metric for the non-blocking-dispatch refactor. |

### Self-contained gates (portable, hang-proof)
`xshard_corruption.sh`, `xshard_intercard.sh`, and `mass_kill_stall.sh` boot their own server from
`./src/redis-server`, run to a `VERDICT:`, and exit non-zero on failure — run them straight from a
built tree (`bash harness/xshard_corruption.sh`) with no setup. They obey three **hang-proof rules**
that every stress harness here MUST follow (a bare `wait` once turned a transient stall into a
43-hour false "wedge"):
1. **Never a bare `wait`.** A script that backgrounds the server with `&` and then calls `wait` with
   no args blocks on the *server* job forever. Capture churn/load PIDs and `wait "$P1" "$P2" ...`.
2. **`timeout -s KILL` every client** (and `pkill -9` orphans in an EXIT trap) so a stalled server
   can never freeze the harness — and remember `timeout … cmd & MPID=$!` makes `$MPID` the *wrapper*;
   also `pkill` the child by pattern, or the orphaned child runs on.
3. **Force-kill the server by PID** at the end; don't rely on `wait` to reap it.

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
