# FLUSH merit instruments

## flushmerit

Harness-only lane, worktree `/home/user/Projects/cx-flushmerit`, branch
`cx-flushmerit`, production base `e2b2379262ecc28e6fc3508526ba3403a98d68be`.
No production source, Makefile, gate row, EXPECT_QUICK or EXPECT_FULL changes.
DQ=0, DF=0. No push. The three new serverless self-tests run through the existing
`tests/gates_test.py` invocation in the ABBA harness self-test row.

Read before implementation: `/home/user/Projects/calib/exec-merit.py`,
`/home/user/Projects/calib/script-storm-merit.py`, and
`git show cx-flushfix2:MEASURE-REQUEST-flushfix2.md` (Implementation and Owner's
merit run). Those existing merit files are outside this checkout; the new
`calib/` directory is self-contained, apart from the optional existing
`tests/abba_profile.py` profiler.

### Instruments and interpretation

- `calib/flush-latency-merit.py`: FLUSHALL SYNC/ASYNC, 0/1M/10M DB-0 keys,
  16-byte keys and 64-byte values, no TTLs. Both modes, atomic 0/1, databases
  1/16; read-local 1 in fused and 0 in split. DEBUG SHARDS establishes exact
  per-shard quotas, then a temporary RESP spool replays pipelined MSET (256 keys
  per command, 16 commands per batch). TomoKV has no DEBUG POPULATE implementation.
  Every trial reseeds outside the timer and independently verifies DBSIZE before
  FLUSH; it verifies zero DBSIZE and no residual keyspace afterward. Successful
  MSET replies, exact population/expiry counts and one value per shard are checked.
  The spool is deleted on exit. RSS comes from the owned PID's VmRSS immediately
  before seed, after seed and after FLUSH reply; signed RSS differences are
  retained, including allocator retention. Optional `--rss-settle` adds a separate
  delayed sample without extending command latency. Nothing calls MEMORY PURGE.
- `calib/flush-writer-wait.py`: 16 SET writers, pipeline 1, nominal FLUSHALL
  deadlines every 100 ms. **same-key** means all writers cycle the same 16 keys
  in the same order, one key on every shard. **disjoint-key** gives each writer
  its own shard's key. **no-flush** uses the disjoint writer schedule without
  FLUSH. FLUSHALL overlaps every key in both writer schedules. Every SET gets
  a unique 64-byte writer/sequence token. Final values must be acknowledged
  writes or a flush that are maximal in the observed start/end partial order;
  size and expiry counts must agree exactly. Client RTT is an **upper bound on
  claim wait, never pure claim wait**. Scheduled-to-completion latency and send
  lag expose delayed offers. Flush RTT, actual timestamps, pre-flush DBSIZE and
  RSS are retained separately from the writer distribution.
- `calib/mget-under-exec-merit.py`: 64 MGET connections, pipeline 8; eight EXEC
  writers, one transaction in flight each, MULTI/SET x8/EXEC. Eight fixed keys
  use shards 0,2,4,6,9,11,13,15. Their owner counts must be balanced: two owners
  at split 6:2, all eight at split 24:8, eight distinct owners at fused 32 cores.
  Every transaction writes one unique 64-byte token to all eight keys. Every
  MGET must contain eight equal tokens; after drain, observed tokens must belong
  to acknowledged transactions and final state must be a maximal final writer
  transaction. Both modes and database images, atomic 1, read-local 0.
  `atomic_entries` is cumulative, so the witness requires an increase PLUS a
  positive `atomic_pending_entries` sample during the active window. It also
  requires a positive `atomic_predecessor_reads` delta. Missing evidence fails;
  no debug hooks, sleeps in server code or skipped windows manufacture it.

All tools use fresh owned boots, explicit server/load CPU affinity, 16 shards,
key/client LB off, automatic FLIP off, persistence off and LC_ALL=C. Split uses
all requested server CPUs at a scaled 6:2 ratio: **24:8 on cores 0–31**. Two arms
run ABBA; a third inserts CC in the middle, giving **ABCCBA**, equal replication
and equal mean temporal position. Blocks are interleaved across cells. Only
owned PIDs are stopped, successful runs drain every client first, occupied ports refuse startup,
and binary SHA-256s must remain unchanged. Any invalid arm makes the campaign
invalid; there is no candidate-only success rule.

Writer and MGET tools first run short unpaced calibration windows on **every
selected cell and arm**, choose half the minimum achieved client rate (separate
reader/transaction rates for MGET), then validate that fixed offer on every cell
and arm. The chosen offers and all calibration results are recorded. This is
achieved generator+server capacity, not a claim of server saturation. The
measured ABBA blocks never retune the offers. Missing scheduled operations,
less than 99% completed within the offered interval, excessive drain, or p99
send lag above 20 ms invalidate a paced run. The flush loop never skips a
10 Hz deadline; falling behind a whole period fails. Failed windows remain
available for diagnosis and cannot silently become successful merit rows.

INFO before/after values and deltas retain flush units, range reads, post
versions, script conflicts, collapses, slow collapses, predecessor reads and
transaction wait counters. Absent PRE counters are **null**, never fabricated
zeros. Disappearing/reset counters, expirations, evictions, transport/error
counters or order violations fail. Counter capability must remain consistent
within an arm. These binaries expose wait **counts**, not an owner-side wait
histogram; `claim_wait_duration_histogram` is explicitly null.

`observations.json` preserves every individual flush latency and its three RSS
observations. `worker-N.json` holds client histograms with exact sample counts
and **1 microsecond upper-edge buckets**: pooled quantiles round upward by less
than 1 microsecond. Flush quantiles retain raw nanosecond observations. Every
run has `record.json`; `records.json` retains the full ABBA ordering;
`summary.json` pools distributions by cell/arm and reports median/min/max rates
per arm. Reader MGET commands/s and committed writer transactions/s are separate.
`summary.txt` and the final stdout line are one queue verdict, including valid
run counts and SMOKE_ONLY/MERIT. No rates are printed for smoke runs.

MGET `--profile` requires the gate's grouped per-server-thread PMCs and stores
`cpu-profile.json` with cycles, instructions, IPC, timing offsets and approximate
cycles/RESP-command and instructions/RESP-command. The denominator is MGET
commands plus ten RESP commands per successful transaction. These are combined
server costs, including observer/interval overhang, not reader-only attribution;
the inherited profile metadata explicitly calls the intervals approximate.
Unavailable/multiplexed counters fail that requested profile, rather than being
reported as zero. The ordinary gate's existing cells remain the instrument for
main-command regressions.

### Exact maintainer queue commands

Run sequentially on the maintainer's quiet allocation. These commands have
**not** been run by this lane. All output directories must be new. The three
frozen binaries were SHA-256 checked without starting them:

| Arm | Binary under `/home/user/Projects/` | SHA-256 |
|---|---|---|
| A, PRE | `bins/flushfix2-pre-e1f756b4` | `e1f756b465273991a42b350986645a2660700bee6d71404b9630182789528d3e` |
| B, POST | `bins/flushfix2-post-7389c241` | `7389c241a63ed94d17a03c447c90bba6ae1dde422f0fe6a9edb728006d13bad8` |
| C, PAD-A | `bins/flushfix2-pad-2f7c9591` | `2f7c9591acc21effb52787cc75194f9d6f9426e63e36538027c7f264d0b0832e` |

PAD-A is **(A) behaviour twin**: PRE FLUSH routing/behaviour with the candidate's
ELF text size, function addresses and section layout, as specified by flushfix2.
It is not an inverse control. The commands label it `--third-kind behaviour-twin`.

From this worktree, define the common shell array once:

```bash
cd /home/user/Projects/cx-flushmerit
arms=(--reference /home/user/Projects/bins/flushfix2-pre-e1f756b4
      --candidate /home/user/Projects/bins/flushfix2-post-7389c241
      --third /home/user/Projects/bins/flushfix2-pad-2f7c9591
      --third-kind behaviour-twin
      --server-cores 0-31 --load-cores 32-111 --ratio 24:8 --blocks 3)
```

Separate population commands make the long reseeding jobs independently
queueable. With three blocks, `--trials 100` rounds to **102 flushes per arm and
cell**, and `--empty-trials 1000` to **1002 per arm and cell**, equal per visit.
No timed interval includes the reseed. Planning estimates below are deliberately
broad, **not measurements or extrapolated smoke rates**; the populated commands
are dominated by writing the requested data repeatedly.

```bash
taskset -c 0-111 python3 calib/flush-latency-merit.py "${arms[@]}" \
  --port 20110 --populations 0 --empty-trials 1000 \
  --output build/flushmerit-merit/empty

taskset -c 0-111 python3 calib/flush-latency-merit.py "${arms[@]}" \
  --port 20110 --populations 1000000 --trials 100 \
  --output build/flushmerit-merit/1m

taskset -c 0-111 python3 calib/flush-latency-merit.py "${arms[@]}" \
  --port 20110 --populations 10000000 --trials 100 \
  --output build/flushmerit-merit/10m

taskset -c 0-111 python3 calib/flush-writer-wait.py "${arms[@]}" \
  --port 20111 --secs 30 --calibration-secs 3 --load-fraction 0.5 \
  --output build/flushmerit-merit/writer

taskset -c 0-111 python3 calib/mget-under-exec-merit.py "${arms[@]}" \
  --port 20112 --secs 30 --calibration-secs 3 --load-fraction 0.5 --profile \
  --output build/flushmerit-merit/mget-exec
```

| Command | Scheduled work | Planning duration |
|---|---|---|
| Empty FLUSH | 288 fresh boots; 48,096 timed flushes | 10–30 minutes |
| 1M FLUSH | 288 boots; 4,896 reseeds/flushes; 4.896 billion inserted keys | 3–12 hours |
| 10M FLUSH | 288 boots; 4,896 reseeds/flushes; 48.96 billion inserted keys | 20–80 hours |
| Writer | 864 measured 30-second windows, plus 288 three-second calibration/validation windows | 8–10 hours |
| MGET/EXEC | 72 measured 30-second windows, plus 24 three-second calibration/validation windows | 45–60 minutes |

The latency matrix totals **53.856 billion inserted keys**. The duration ranges
include allowance for sequential Python seeding, exact shard routing, fresh
boots and evidence serialization; long flush completion can extend them.

To inspect flushfix2's populated slow-collapse risk, additionally queue the
same writer command with `--population 1000000` and a new output directory:

```bash
taskset -c 0-111 python3 calib/flush-writer-wait.py "${arms[@]}" \
  --port 20111 --secs 30 --calibration-secs 3 --load-fraction 0.5 \
  --population 1000000 --output build/flushmerit-merit/writer-first-flush-1m
```

Allow **9–14 hours**. This seeds once before each boot's load window: only the
first flush is deliberately populated, and each actual flush size is retained.
It does **not** claim to hold 1M keys present at every 10 Hz event. A candidate
unable to sustain that cadence or matched offer produces invalid evidence with
its raw observations retained. A zero slow-collapse delta is not evidence about
that path; requeue a fresh workload/design witness if that window is required.
Owner-side pure claim-wait duration remains **NOT AVAILABLE** in the supplied
production counters. This harness-only lane cannot add the missing server timer.

### Verification receipts

The committed machine-readable receipt is `docs/flushmerit/proof.json`; raw
logs, manifests, worker observations and profile files remain under
`build/flushmerit/`. The receipt deliberately contains no rates. Final checks:

| Proof | Result |
|---|---|
| `taskset -c 0-15 python3 tests/gates_test.py` | **PASS, 76 tests**; final log `build/flushmerit/gates-test-final.log` |
| Each of the three tools with `--selftest` | **PASS**; `build/flushmerit/selftests-final.log` |
| Latency smoke, full mode/atomic/database/SYNC-ASYNC matrix, populations 0/10k | **VALID, 128/128 runs** |
| Optional third-arm latency smoke (same base executable in A/B/C) | **VALID, 6/6 runs**, ABCCBA |
| Writer split/atomic-1/db1/SYNC, all three schedules | **VALID, 12/12 runs** |
| Writer fused/atomic-0/db16/ASYNC, all three schedules, initially 10k keys | **VALID, 12/12 runs** |
| MGET/EXEC, both modes and database settings, including `--profile` | **VALID, 16/16 runs**; every live/predecessor witness positive; 16 complete PMC profiles |
| Per-arm summary counts vs individual observations/completions | **PASS** |
| `taskset -c 0-15 make -q all` | **0** after the base build and after all harness changes |
| `git diff e2b237926 -- src Makefile tests/gate.sh` | **Empty** |
| `git diff --check e2b237926` | **PASS** |
| Build footprint | About **1.5G**, below the 10G budget |

The smoke executable was built from unchanged e2b237926 production sources
before the first harness commit, using `taskset -c 0-15 make -j8 all`. Its SHA-256
is `c6c6459edec2e85276832b93f2523f51ad1f81d2cdf5777b73b1f1af4bdfc3d2`.
All smoke servers used cores 0–7, loads 8–15, ports 20100–20103, one block and
2-second load/calibration windows. These were **smoke only**, not measurements.
No real flushfix2 PRE/POST/PAD server was started.

Exact successful smoke invocations (the named directories now exist):

```bash
smoke=(--reference build/tomokv --candidate build/tomokv
       --server-cores 0-7 --load-cores 8-15 --blocks 1 --smoke)

taskset -c 0-15 python3 calib/flush-latency-merit.py "${smoke[@]}" \
  --port 20100 --populations 0,10000 --trials 2 --empty-trials 2 \
  --output build/flushmerit/verified-latency-smoke

taskset -c 0-15 python3 calib/flush-latency-merit.py "${smoke[@]}" \
  --port 20103 --third build/tomokv --third-kind behaviour-twin \
  --modes 2s --databases 1 --atomics 1 --flushes SYNC \
  --populations 10000 --trials 2 --empty-trials 2 \
  --output build/flushmerit/third-arm-smoke

taskset -c 0-15 python3 calib/flush-writer-wait.py "${smoke[@]}" \
  --port 20101 --secs 2 --calibration-secs 2 \
  --modes 2s --databases 1 --atomics 1 --flushes SYNC \
  --output build/flushmerit/isolated-writer-smoke

taskset -c 0-15 python3 calib/flush-writer-wait.py "${smoke[@]}" \
  --port 20101 --secs 2 --calibration-secs 2 --population 10000 \
  --modes 1s --databases 16 --atomics 0 --flushes ASYNC \
  --output build/flushmerit/verified-writer-fused-smoke

taskset -c 0-15 python3 calib/mget-under-exec-merit.py "${smoke[@]}" \
  --port 20102 --secs 2 --calibration-secs 2 --profile \
  --output build/flushmerit/isolated-mget-profile-smoke
```

Final queue lines include:

```text
flush_latency: status=VALID kind=SMOKE_ONLY valid=128/128 runs=128 DQ=0 DF=0
flush_latency: status=VALID kind=SMOKE_ONLY valid=6/6 runs=6 DQ=0 DF=0
flush_writer_wait: status=VALID kind=SMOKE_ONLY valid=12/12 runs=12 DQ=0 DF=0
mget_under_exec: status=VALID kind=SMOKE_ONLY valid=16/16 runs=16 DQ=0 DF=0
```

Earlier failed/superseded attempts are preserved in the receipt and build
artifacts. One harness-suite run overlapping smoke work hit its existing
single-slot scheduler fixture timeout; overlapping writer/MGET attempts also
failed the offered-completion or send-lag guard. Isolated fresh runs passed
without changing those guards. The initial even-shard MGET smoke was superseded
because its split keys aliased one executor; final owner-balanced geometry is
checked by serverless negative controls and the actual boot routes. These
histories are not erased or counted as successful final evidence.

Real merit measurements and `tests/gate.sh iteration`: **NOT RUN**, reserved for
the maintainer. Pure owner-side claim-wait duration: **NOT AVAILABLE** from these
binaries, which expose counts only. No claim about flushfix2 performance or
correctness is made by these base-versus-base smoke checks.
