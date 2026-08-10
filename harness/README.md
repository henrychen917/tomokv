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
| `loadgen/cload.c` | **Fast deterministic C load generator** (raw-socket RESP + deep pipelining + N threads) that **saturates** the server and **targets one worker's keys** via an embedded bit-exact xxh64. Modes GET/SET/BITCOUNT/mixed. `gcc -O3 -o cload cload.c -lpthread`. A fixed seed gives every client a reproducible command/key stream; `-d` is a monotonic wall-clock scoring window. |
| `bench_hop_sweep.sh` | Cross-L3 delayed-visibility measurement driver. It gates a pre-connected `cload`, attaches `perf stat` to a coordinator-supplied server PID, and writes throughput/IPC curve inputs for hop values 0/50/100/200/400. It never starts or stops a server unless the caller explicitly supplies a lifecycle hook. |
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

## Cross-L3 delayed-visibility sweep

Build `harness/loadgen/cload` separately, then let the coordinator boot and populate the server.
For one already-running server configured with `tomokv-sim-hop-ns 100`, run a 30-second scored
window as follows (the hop value is metadata and must match the server configuration):

```sh
./harness/bench_hop_sweep.sh \
  --duration 30 --variant header-base --hops 100 \
  --server-pid "$SERVER_PID" --port 7800 \
  --threads 8 --pipeline 64 --command get
```

The simulation knob is immutable, so a complete sweep needs a coordinator-owned restart hook:

```sh
./harness/bench_hop_sweep.sh \
  --duration 30 --variant header-base \
  --hops 0,50,100,200,400 --rounds 3 \
  --prepare ./coordinator/prepare-hop \
  --port 7800 --threads 8 --pipeline 64 --command get
```

The executable hook receives `HOP_NS VARIANT ROUND PID_FILE`. It must start the intended binary
with that hop value, wait until it is ready, populate outside the scored window, and write the
server PID to the fresh per-point `PID_FILE` supplied by the driver. The driver itself contains no
`redis-server` or shutdown command and never sends a nonzero signal to the supplied server PID.
Run the same sweep with `--variant header-shrunk` against the shrink binary; join the two TSVs on
`hop_ns,round,workload_id` to price the header change at equal injected latency.

`cload` finishes connection/key-pool setup before printing `CLOAD_READY`. The driver then starts
`perf stat -p SERVER_PID` with counters disabled, waits for perf's control-FD enable acknowledgement,
and only then releases the start gate. It disables the counters after the same wall-clock duration.
Each client follows a fixed per-thread key order, and mixed mode uses a fixed-seed integer sequence
(`--seed`, default 1), never `rand()` or a time/address seed. At the deadline, it stops issuing,
drains the already-issued pipeline with a bounded socket timeout, and reports only batches
completed within the scoring window as `scored_ops`. Raw load and perf records plus a joinable
`curve.tsv` are retained in the output directory. Use `--no-perf` only when a higher-level
coordinator attached perf before invoking this driver.

Healthy stdout is machine-readable:

```text
HOP_POINT variant=header-base hop_ns=100 round=1 healthy=yes ops_per_sec=6139882.400 ipc=1.428571 load_rc=0 perf_rc=0
HOP_SWEEP_RESULT variant=header-base healthy=yes curve=hop-results-header-base-.../curve.tsv
```

The corresponding `CLOAD_HEALTH` record must have `healthy=yes`, zero errors, and
`outstanding=0`; the curve row must have numeric cycles, instructions, and IPC when perf is
enabled. Throughput is `scored_ops / duration`, IPC is `instructions / cycles`, and the useful
comparisons are throughput and IPC relative to hop 0 plus the shrunk/base throughput ratio at the
same hop.

## Caveats
Hardcoded `127.0.0.1:7800` and `/tmp/hot.txt` in several scripts; tune per run. Built against
`THredis-opt-v8`.
