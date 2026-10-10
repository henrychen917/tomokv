## perfex

Worktree `/home/user/Projects/cx-perfex`, branch `cx-perfex`; no push.
PRE: `5146b78ee89b64748dd46db970efa8086f653fa0` after the required initial
fetch/merge (already current). Production fixes: `97411ff12`, `43b454f87`.
**Proof in progress; this is not a merge/gate/performance approval.**

The early, self-contained pfconfirm compatibility commit for perfio is
`d867a1073` (`pfconfirm: runnable on the current tree`), following the requested
merge of `cx-pfconfirm`. Its 28 serverless tests pass. It removes the retired
`--overlap` argv, sets cells to ov=0, pins the PRE headline by default, supplies
`--databases 1` unless srv= overrides it, and shares `--port` with quiet screening.
Caps, verdict rules, workloads and guards remain unchanged.

| Arm | Binary | SHA-256 |
|---|---|---|
| Built PRE | `build/perfex/pre/tomokv` | `bafacf2dc91dc3e16e53724bcd7733f6119be9447636d7d5094b85d1b809e48e` |
| Mainline PRE headline | `/home/user/Projects/bench-bins/tomokv-headline-5146b78ee` | `29637fabb42ed4ac9c5b663572c75aa3ae7f6d2745befbc3134a9c59cb5a01fc` |
| POST | `build/tomokv` | pending final build |

### Findings and rows

| Finding | PRE result (before production edits) | POST | Files / new row |
|---|---|---|---|
| EX4.2 / ST4.2 / PFKEYSPA.1 | At fixed realtime, 16/16 unrelated batches advance avg_ttl in both split and fused | pending | `src/cmd/storesize.cc`, `src/core/ex_loop.h`; `perfex TTL sampler beat (1s)` and `(2s)` |
| EX4.12 | CPU clock reachable on sample_depth(false) in all four linked executor run bodies | pending | `src/core/ex_loop.h`; `perfex clock binary regression` |
| EX4.13 | All six ordinary linked drain bodies call memset before receiving a task | pending | `src/core/ex_loop.h`; `perfex batch binary regression` |

PRE failing output is retained in `docs/perfex/pre-{clock,batch,sampler-1s,sampler-2s}.log`.
The sampler regression uses an isolated LD_PRELOAD realtime fixture. A production
PTTL result proves the frozen clock actually opened the window before checking
that unrelated GET batches leave avg_ttl unchanged. Explicit clock steps then
prove refresh with active expiry disabled, accuracy (128 windows within 10% of
the known exact mean), rotating coverage of all shards, exact key/expiry counts,
DBSIZE, and zero avg_ttl after PERSIST. The fixture adds no production hook.
An earlier wall-time fixture was discarded because it could not reliably open
its sub-millisecond window; no tolerance was widened and no case was skipped.

Only the monitoring sample moves to the existing owner beat: inspect at most
eight owned shards and sample at most one volatile shard (16 index slots) per
beat. Active expiry, index maintenance, batch count/bytes/expires/evicted and
hash-field TTL attention publication remain unchanged. The sampler respects
owner freezes and snapshot blocking, uses cached time, and holds no shard pointer
across ownership changes. Its owner-vector cursor occupies existing padding;
per-store index cursors still travel with their stores. No new shared atomic.

The CPU-time sample now shares sample_depth's existing 100 us beat. Consumers:
`src/cmd/lbsignals.cc` copies it to per-thread DEBUG LBSIGNALS rows and sums role
rollups; `src/core/shutdown_report.h` snapshots and emits final text/JSON reports.
The placement/demand model in `src/core/server.h` uses busy/idle, not cpu_ns.
These consumers retain monotone cumulative diagnostics, now sampled like IO and
fused IO (not a per-pass value).

Task itself is unchanged. C++20 byte-array storage and construct_at copy each
received slot; existing batch lengths gate every read. The ordinary and
read-local interleaved drains reuse trivially destructible slots. The separate
`Task posts[256]` arrays in `src/cmd/scatter_engine.inc` (AT4.7), and the opt-in R7
queue's scratch array, remain outside this change.

### Counts and ledger

Merged base: EXPECT_QUICK=511, EXPECT_FULL=528. The two binary rows in
job_perfex_units and the two live rows in job_perfex_live are collected before
the quick-tier exit: **DQ=4, DF=4; 511+4=515, 528+4=532**. Arithmetic is documented
above the unchanged constants. The source inventory and label fixture both have
532 rows with no missing/extra labels. The raw ledger validator necessarily
refuses EXPECT_FULL=528 until the maintainer changes the constant. Its refusal
is retained; neither the constants nor the checker are weakened.

### Merit commands (mainline schedules the quiet box)

The full 0-111 commands below are requests, not coding-lane executions. All lane
execution is pinned under taskset -c 112-127; server/listener ports are 25100-25124.

```
PRE=/home/user/Projects/cx-perfex/build/perfex/pre/tomokv
POST=/home/user/Projects/cx-perfex/build/tomokv
REF=/home/user/Projects/bench-bins/tomokv-headline-5146b78ee

# Functional only; both arms must report SMOKE_OK. Choose new output directories.
taskset -c 112-127 docs/pfconfirm/run.sh --smoke --only PFKEYSPA.1 --binary "$PRE" --sha256 "$(sha256sum "$PRE" | cut -d' ' -f1)" --port 25120 --output docs/perfex/pfconfirm-smoke-pre-quiet
taskset -c 112-127 docs/pfconfirm/run.sh --smoke --only PFKEYSPA.1 --binary "$POST" --sha256 "$(sha256sum "$POST" | cut -d' ' -f1)" --port 25120 --output docs/perfex/pfconfirm-smoke-post

# Full confirmation: PRE CONFIRMED, POST NOT CONFIRMED; preserve all cells/caps/verdict rules.
taskset -c 0-111 docs/pfconfirm/run.sh --only PFKEYSPA.1 --binary "$PRE" --sha256 "$(sha256sum "$PRE" | cut -d' ' -f1)" --port 25000 --output docs/perfex/pfconfirm-full-pre
taskset -c 0-111 docs/pfconfirm/run.sh --only PFKEYSPA.1 --binary "$POST" --sha256 "$(sha256sum "$POST" | cut -d' ' -f1)" --port 25000 --output docs/perfex/pfconfirm-full-post

# Zero main-command regression required in every selected generic cell.
taskset -c 0-111 python3 tests/abbagate.py --cells /tmp/claude-1000/generic_merit_cells.txt --only h05,h06,p8g,p8s,d1g_l0,d1s_l0,d32s_l1,d8s_l1,d32g_l1,x9_32_l1,x9_32_l0,m8g_l0,v1g_l0,d128g_l0 --candidate-binary "$POST" --reference-binary "$REF" --build-reference 0 --server-cores 0-31 --load-cores 32-111 --load-smt '' --ports 25010-25019 --output build/perfex/generic-merit
# Isolate split executor gains at GET/SET p8/p32; unchanged abbagate verdict rules.
taskset -c 0-111 python3 tests/abbagate.py --cells docs/perfex/split-cells.txt --candidate-binary "$POST" --reference-binary "$REF" --build-reference 0 --server-cores 0-31 --load-cores 32-111 --load-smt '' --ports 25020-25029 --output build/perfex/split-merit

# Short executor-only perf stat; 64,000 offered ops/s in both arms, plus idle second.
taskset -c 112-127 python3 docs/perfex/perf_stat.py --binary "$PRE" --sha256 "$(sha256sum "$PRE" | cut -d' ' -f1)" --port 25110 --output docs/perfex/perf-stat-pre
taskset -c 112-127 python3 docs/perfex/perf_stat.py --binary "$POST" --sha256 "$(sha256sum "$POST" | cut -d' ' -f1)" --port 25110 --output docs/perfex/perf-stat-post

# TTL behavior, original ttls cell (20M keys); identical population in both arms.
taskset -c 112-127 python3 tests/abbagate.py --cells tests/ttl_cells.txt --only ttls --candidate-binary "$POST" --reference-binary "$PRE" --build-reference 0 --server-cores 112-119 --load-cores 120-127 --load-smt '' --ports 25112-25119 --output docs/perfex/ttl-local
# Full geometry: compare INFO active_expire_reap_lag_ms_max and expired_keys delta / window_seconds.
taskset -c 0-111 python3 tests/abbagate.py --cells tests/ttl_cells.txt --only ttls --candidate-binary "$POST" --reference-binary "$PRE" --build-reference 0 --server-cores 0-31 --load-cores 32-111 --load-smt '' --ports 25030-25039 --output build/perfex/ttl-full
```

Both generic and split cell files parse with --list-cells; retained JSON is in
`docs/perfex/{generic,split}-cells.json`. Split shapes are explicitly databases 1.
Rate at the same offered load decides merit; cycles/op, instructions/op and IPC
explain it. perf_stat.py retains the PMU/command endpoint envelope, so those short
ratios are diagnostics rather than an ABBA verdict.

### Smoke and measurement evidence

PRE pfconfirm smoke was **REFUSED before boot** by the unchanged quiet screen:
16.70 selected-core CPU-seconds > 0.48-second budget in 20 seconds. Receipt:
`docs/perfex/pfconfirm-smoke-pre/`. An earlier invocation with too narrow a parent
affinity was also refused before boot and is retained separately. No performance
claim is inferred from either attempt. POST smoke, perf-stat and TTL receipts pending.

| Shape | PRE cycles/op | POST cycles/op | PRE instructions/op | POST instructions/op | IPC PRE / POST |
|---|---:|---:|---:|---:|---|
| GET p8, 64K offered | pending | pending | pending | pending | pending |
| SET p8, 64K offered | pending | pending | pending | pending | pending |
| GET p32, 64K offered | pending | pending | pending | pending | pending |
| SET p32, 64K offered | pending | pending | pending | pending | pending |
| Idle, executor cycles/s | pending | pending | — | — | — |

| TTL ttls | PRE | POST |
|---|---:|---:|
| active_expire_reap_lag_ms_max | pending | pending |
| expired_keys/s | pending | pending |

### Correctness/build/identity proof

Pending final build, production targets/freshness checks, source merge, focused
differential matrix (edgetime, hexpire, infofix; seeds 7/19/20/23; atomic 0/1;
split 6:2 and armed fused), INFO/storesize checks and byte/layout audit.
PRE make -j16 BUILD_ROOT=build/perfex/pre all passed. The first POST compile caught
a private-helper access and was corrected by using the existing public count
publication API, preserving the hash-field attention flag without a header change.
The first gates_test run under build contention timed out 14 scheduler fixtures;
it will be rerun after compilation. Clauses await their production-unit build.

Expected changed body families: ordinary drain/receive lambdas (construct received
Task slots), executor run (CPU beat), owner-control tail and its inline callers
(millisecond monitoring hook), publish_size (remove monitoring walk), monitoring
sampler (field attention stays with batch publication), and cold initialization
of the padding cursor. Every unrelated hot body must remain identical; final
per-namespace tables and complete changed-body reasons pending.
