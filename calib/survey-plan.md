# TomoKV / Redis 7.4 breadth survey

These are maintainer commands, to run **serially on a quiet box**. The lane only
runs authorized short validity checks on CPUs 48–63, with ports 20200–20299. No gate rows or
production sources change. Redis reference: `/home/user/Projects/redis74/src/redis-server`,
confirmed `7.4.10` (`f103d127`, jemalloc 5.3.0).

## Build and serverless verification

From `/home/user/Projects/cx-surveyfix` (or the integrated checkout):

```sh
taskset -c 48-63 make -j8
taskset -c 48-63 c++ -std=c++20 -O2 -Wall -Wextra -pthread calib/survey-client.cc -o build/survey-client
taskset -c 48-63 build/survey-client --selftest
taskset -c 48-63 python3 tests/gates_test.py
taskset -c 48-63 python3 calib/survey.py --selftest
taskset -c 48-63 python3 calib/survey-cmds.py --selftest
taskset -c 48-63 python3 calib/survey-latency.py --selftest
taskset -c 48-63 python3 calib/survey-memory.py --selftest
taskset -c 48-63 python3 calib/survey-persist.py --selftest
taskset -c 48-63 python3 calib/survey-scale.py --selftest
taskset -c 48-63 make -q
```

Python uses the standard library. The throughput driver also uses the installed
`memtier_benchmark` 2.5.1. Its drained HDR decoder is shared with
`tests/abba_workloads.py`; there is no change to that gate module. Every run pins
the binary hashes, exact argv, command scripts, CPU sets and reference version.
Full and first-pass results go under the already ignored `.gate-history/surveytools/`, keeping `build/` small. All output directories must be new. No resume, overwrite, retries to obtain a
passing result, port-based killing, or unowned shutdown is performed.

## Full survey

The following Bash array is used unchanged by all five commands. These commands
use server cores **0–31**, load/orchestration cores **32–111**, port **20400**,
TomoKV `--databases 1 --atomic 1 --shards 256`, and `--ratio 24:8` for 2s.
Key/client balancing and automatic flip are off, matching the calibration
instruments' fixed-role comparison. Redis gets the same CPU mask; its single
command-execution thread is not described as using all 32 cores. Redis's threaded
read option is explicitly enabled for both io-thread settings.

```sh
common=(--candidate "$PWD/build/tomokv"
        --redis /home/user/Projects/redis74/src/redis-server
        --client "$PWD/build/survey-client"
        --server-cores 0-31 --load-cores 32-111 --ratio 24:8
        --shards 256 --port 20400 --keys 1024 --connections 512)

taskset -c 32-111 python3 calib/survey-cmds.py "${common[@]}" \
  --variants 1s-rl0,1s-rl1,2s-rl0,2s-rl1 --redis-threads 1,4 \
  --families all --pipelines 1,32 --seconds 15 --blocks 3 --output .gate-history/surveytools/full-cmds

taskset -c 32-111 python3 calib/survey-latency.py "${common[@]}" \
  --variants 2s-rl0 --redis-threads 4 --fractions .25,.5,.75 \
  --calibration-connections 256,512,1024 --calibration-seconds 5 \
  --seconds 15 --blocks 3 --output .gate-history/surveytools/full-latency

taskset -c 32-111 python3 calib/survey-memory.py "${common[@]}" \
  --variants 2s-rl0 --redis-threads 4 --populations 1000000,10000000 \
  --shapes all --settle 5 --blocks 3 --output .gate-history/surveytools/full-memory

taskset -c 32-111 python3 calib/survey-persist.py "${common[@]}" \
  --variants 2s-rl0 --redis-threads 4 --persistence off,everysec,always,bgsave \
  --seconds 10 --always-seconds 3 --blocks 3 --output .gate-history/surveytools/full-persist

taskset -c 32-111 python3 calib/survey-scale.py "${common[@]}" \
  --variants 2s-rl0 --redis-threads 4 --connection-counts 50,500,5000,10000 \
  --value-sizes 16,1024,16384,262144 --seconds 15 --blocks 3 --output .gate-history/surveytools/full-scale
```

All tools accept the four TomoKV variants and Redis io-threads 1/4. Only the
command survey crosses all eight pairs by default; the other dimensions use the
paper read-local-0 baseline against Redis4. Add variants there if the first pass
identifies a reason to expand the matrix.

Planning estimates, **not measured timings**, include fresh-boot/preload costs:

| Tool | Timed visits / full run | Estimated full duration |
| --- | ---: | ---: |
| commands | 86 cells × 8 pairs × 4 visits × 3 blocks = 8,256 | 36–45 hours |
| latency | 15 cells × 4 visits × 3 blocks = 180, plus 15 calibration boots | 50–75 minutes |
| memory | 16 cells × 4 visits × 3 blocks = 192 | 2–5 hours; preload dependent |
| persistence | 8 cells × 4 visits × 3 blocks = 96 | 15–25 minutes |
| scale | 16 cells × 4 visits × 3 blocks = 192 | 50–70 minutes |

Time is approximately `visits × (window + boot + seed + teardown)`. Memory has
two settles per visit instead of a throughput window. The 10k-member sorted-set
preloads and 10M-key images are the largest uncertainty. Do not overlap tools.

## Reduced first pass remaining: approximately 4–5 hours

Memory, persistence and scale completed VALID on 2026-11-01; do not repeat them
for this repair. Commands and latency remain. Use the frozen headline binary
`tomokv-headline-105c5818cc` (the on-disk name includes the final `c`) and the
rebuilt survey client. Run the following Bash commands serially on a quiet box.
The result directories must not already exist.

```sh
first=(--candidate /home/user/Projects/bench-bins/tomokv-headline-105c5818cc
       --redis /home/user/Projects/redis74/src/redis-server
       --client "$PWD/build/survey-client"
       --server-cores 0-31 --load-cores 32-111 --ratio 24:8
       --shards 256 --port 20400 --keys 64 --connections 64 --blocks 1)

taskset -c 32-111 python3 calib/survey-cmds.py "${first[@]}" \
  --variants 1s-rl0,1s-rl1,2s-rl0,2s-rl1 --redis-threads 1,4 \
  --families all --pipelines 1,32 --seconds 4 \
  --output .gate-history/surveyfix/first-cmds

taskset -c 32-111 python3 calib/survey-latency.py "${first[@]}" \
  --variants 1s-rl0,2s-rl0 --redis-threads 4 --commands all \
  --connections 512 --keys 1024 --fractions .25,.5,.75 \
  --calibration-connections 256,512,1024 --calibration-seconds 3 \
  --max-lag-ms 20 --seconds 5 \
  --output .gate-history/surveyfix/first-latency
```

Commands retain all 43 command/shape combinations, both pipelines, all four
TomoKV variants and both Redis thread counts: **2,752 timed visits**, estimated
3.4–4.2 hours including fresh boots and preloads. Latency retains all five
workloads, all three fractions and both read-local-0 modes: **120 timed visits**
plus 15 calibration boots, estimated 20–35 minutes including observation
compression. These are planning estimates, not measured durations. This is a
gap-finding pass; paper numbers still need longer windows and three blocks.
A calibration that lacks the existing 2% plateau or is generator limited remains
INVALID; no rate reduction, retry or relaxed deadline is applied automatically.

## Short pacing validity check (lane CPUs only)

This uses the real capacity calibration and full 25%, 50%, 75% fractions,
512 connections and 1,024 keys. **Do not add `--smoke`**: that legacy option
reduces offered load to 1% and cannot prove this repair. The four server CPUs
and twelve load CPUs are entirely inside the authorized lane allocation.
These are tool-validity runs; do not quote their rates. The allocation needs
headroom for per-request TCP work: a closed-loop p32 calibration uses far fewer
packets than the open-loop stream at the same command rate. An eight-load-core
attempt saturated in kernel TCP processing and did not prove the pacing fix.

```sh
short=(--candidate /home/user/Projects/bench-bins/tomokv-headline-105c5818cc
       --redis /home/user/Projects/redis74/src/redis-server
       --client "$PWD/build/survey-client"
       --server-cores 48-51 --load-cores 52-63 --ratio 3:1
       --shards 256 --port 20200 --blocks 1 --seconds 2
       --variants 1s-rl0,2s-rl0 --redis-threads 4)

taskset -c 48-63 python3 calib/survey-latency.py "${short[@]}" \
  --commands GET --keys 1024 --connections 512 --fractions .25,.5,.75 \
  --calibration-connections 256,512,1024 --calibration-seconds 3 --max-lag-ms 20 \
  --output .gate-history/surveyfix/validity-latency-final

taskset -c 48-63 python3 calib/survey-cmds.py "${short[@]}" \
  --families strings --pipelines 1 --keys 64 --connections 64 \
  --output .gate-history/surveyfix/validity-cmds
```

The latency check targets the original GET failure, across all fractions and
both TomoKV modes (24 visits). `--commands all` expands it to all five workloads
(120 visits), requiring a valid capacity plateau for every workload. A short
shared-box calibration may correctly stop before timed cells; retain that
INVALID result and adjust the calibration rungs in a new, explicitly named run.
The command check covers eight string cells, including memtier and native
multi-key requests, with both TomoKV modes. Record the verdicts, lag maxima,
accounting checks and sidecar differences, then delete these short-run outputs.

## Workloads and client choice

Each arm gets a fresh deterministic image over fixed-width 15-byte keys.
Memtier's numeric key IDs start at 100000000000, matching the native loader.
Strings use repeated `x`, hash fields `f00000`… with one-byte `0` values, and
collection members `m00000`…. Every response during native load is parsed and
validated; memtier completions use its drained HDR count, checked exactly against
INFO, plus a zero-miss check and the independent reply sidecar.

| Family | Commands | Timed engine |
| --- | --- | --- |
| strings | GET, SET, INCR, APPEND, GETRANGE, SETRANGE | memtier `--command` |
| strings | MGET 8, MSET 8 | native, eight distinct key namespaces |
| hashes | HSET, HGET, HMGET 8, HGETALL 10/100, HINCRBY | memtier `--command` |
| lists | LPUSH, LRANGE 0 9 / 0 99, LINDEX | memtier `--command` |
| lists | RPOP | native, with LPUSH refill |
| sets | SADD, SISMEMBER, SMEMBERS 10/100 | memtier `--command` |
| sets | SINTER of two 10-member sets | native, two distinct key namespaces |
| sorted sets | ZADD, ZINCRBY, ZRANGE 0 9 WITHSCORES, ZRANGEBYSCORE 0 9, ZRANK, each at 100/10,000 members | memtier `--command` |
| streams | XADD, XRANGE COUNT 10, XREADGROUP COUNT 10 + XACK | native, explicit IDs and coupled commands |
| bitmap/HLL | SETBIT, BITCOUNT, PFADD, PFCOUNT | memtier `--command` |
| geo | GEOADD, GEOSEARCH FROMMEMBER BYRADIUS 1 km | memtier `--command` |

HGETALL and SMEMBERS timing does not enforce collection order. The sidecar
compares raw bytes and logs order differences without normalization. SINTER uses
identical sets, so its intersection is exactly ten members. GEO uses one point
at longitude 121.5, latitude 25.0. GETRANGE returns the first ten bytes; SETRANGE
overwrites byte zero without growth. ZRANK queries the midpoint member.

These are bounded, specified shapes, not every possible command distribution:

- SET/HSET overwrite existing values; SADD, ZADD, GEOADD, SETBIT and PFADD repeat
  existing members/scores/bits. Their no-change reply is validated. They do not
  claim new-member insertion capacity. ZINCRBY/INCR/HINCRBY mutate counters.
- APPEND adds one byte; LPUSH grows lists for the timed window. Every arm starts
  from the same image, but faster arms grow more. This is visible workload
  evolution, not a steady-state size comparison.
- RPOP has a LPUSH refill before every pop. Only RPOP is a primary operation;
  both commands are counted and their wall time is included. The latency
  LPUSH/RPOP mix counts both commands. Lists start with 100 elements.
- XADD measures creation of a one-entry stream with explicit ID `1-0`, preceded
  by a counted auxiliary DEL reset. XRANGE reads ten fixed entries. XREADGROUP
  replays ten entries using an auxiliary XGROUP SETID, then XACKs all ten IDs.
  Each connection has disjoint stream keys. These controlled stream shapes make
  replay and byte comparison deterministic; reset overhead is explicit.
- Native pipeline is a number of **cycles**. Most cycles contain one command;
  coupled list/stream/mix cycles contain the documented commands. JSON includes
  primary commands/s, cycles, total commands/s, and counts by command, so no
  auxiliary command or eight-key command is silently called an extra operation.
- Persistence uses native for SET and its coupled 1:1 GET/SET cycle, identically
  in every persistence arm. Both servers disable automatic AOF rewrite. BGSAVE
  requires at least two successful saves wholly inside the load interval.
- Scale uses memtier where the table applies; 256 KiB SET uses native because a
  literal memtier command exceeds Linux's per-argument size limit.

## Evidence and validity

Each cell/pair/block is **Redis, TomoKV, TomoKV, Redis**, with fresh servers and
identical preload and client configuration each visit. Every visit prints one
status line and writes `record.json`; `records.jsonl` is append-only. A failed
visit is retained and stops the campaign with exit 1 and an INVALID summary
that includes `cell=`, `arm=` and a JSON-escaped `reason=` on the same line.
Calibration and sidecar failures identify their phase and arm as well.
`ratios.json` holds each block's mean TomoKV / mean Redis ratio and both arm
spreads. A spread above 2% or a generator worker at 95% CPU marks the ratio
uninterpretable. VALID is the instrument's execution/accounting verdict, not a
claim that an uninterpretable ratio is a server-capacity result. Histograms are
retained per visit; percentiles are never averaged across visits.

Native load fully drains every submitted request and requires every worker and
connection to complete work. It rejects error replies, malformed or wrong
replies, missing observations, lost cycles and counter resets. Every timed
command's INFO delta must equal the number of completed replies exactly.
Redis's XGROUP subcommand counters and TomoKV's aggregate XGROUP counter are
mapped explicitly. Errors, rejections, evictions, expiration and TomoKV ordering
violations must have zero deltas. Unrelated commands inside the interval fail.

Memtier's final JSON Count may differ from its drained histogram by at most
`connections × pipeline`, the gate's finite outstanding-work bound. The **HDR
completion count must equal INFO exactly**. No percentage tolerance is used.
Client/server CPU masks and per-worker CPU samples are retained. There is no
automatic retry of unstable or failed arms.

The latency tool calibrates Redis4 at increasing closed-loop p32 connection
counts. The last two rungs must be within the box's 2% validity boundary and must not be generator limited;
the smaller rate is frozen as the capacity basis. No plateau means INVALID,
with the evidence retained; increase the rungs on a new run. All arms use exactly
25%, 50% and 75% of that rate. Scheduled deadlines continue independently of
response time, including when earlier replies on that connection are pending.
Each pinned worker owns a contiguous connection-ID interval and services those
deadlines in order, preserving the original global schedule. This avoids
interleaving every worker across every short send interval. It
waits with nanosecond-resolution `epoll_pwait2` (1 ns timer slack), and checks
for due sends during long reply batches. Key placeholder offsets are prepared
once per script, and dense histogram counters preserve the previous bucket
boundaries and exact maxima without per-reply tree lookups. It sends immediately and subscribes
to EPOLLOUT only on backpressure. Each command's sent timestamp is recorded
when its first byte is accepted by `send`; EAGAIN waits therefore contribute
to send lag. Linux/glibc must provide `epoll_pwait2`. Every deadline must eventually complete, with at most 20 ms
generator lag; a slow server is retained as invalid offered-load evidence, not
silently sampled at a lower rate.

Latency reports scheduled-to-completion p50/p99/p99.9/max and separate send-to-
completion RTT and send lag. Successful reply checks avoid constructing error diagnostics. Native histograms have a 1 ns floor and HDR-style
three-significant-digit buckets (less than 0.1% relative bucket width), with exact
maximum. Every native latency observation is retained losslessly in gzip files:
little-endian uint64 quadruples `(connection_id, scheduled_ns, sent_ns,
completion_ns)`, times relative to `client_epoch_ns`. There is no sampling,
truncation, or synthetic coordinated-omission correction. Each fixed-load worker
preallocates and touches its exact observation array before readiness; raw file
writes and close checks happen after its timed drain. This requires temporary
client RAM of `32 × scheduled primary operations` bytes per visit, and prevents
filesystem stalls from blocking send deadlines. Failed workers retain their
completed observation prefix. Memtier retains its
full HDR; its maximum is an upper equivalent bucket value.

Memory reports gross and empty-boot-subtracted used_memory and `/proc/PID/status`
RSS per live key, plus INFO RSS, after settle and after deleting exactly the first
half of the image. The second denominator is **N/2**. TTL is 86,400 seconds;
expiration/eviction invalidates the image. No allocator purge is requested.
Persistence loss is `100 × (1 - mode_rate/off_rate)` for the same server,
workload and block; latency tails remain per visit. Off is mandatory for that
calculation. Disk/CPU profiling and restart durability claims are outside this
instrument's scope.

The behaviour sidecar runs separate fresh sample boots during each campaign,
outside timed intervals. The command tool samples the entire selected catalogue,
including commands omitted from its reduced smoke timing matrix. It retains
base64 raw RESP replies in `behaviour-samples.jsonl`, and both sides of each
mismatch in `behaviour-differences.jsonl`. Order and generated-ID differences
are flags for review, not automatically correctness defects. No fix is attempted.

## Smoke and storage

These smoke commands use 2-second windows, one ABBA block, ports below 32768,
and only CPUs 48–63. They are functional tests; do not quote their rates. Memory
uses 32/128 keys; scaling uses 4/8/16/32 connections while retaining every value
size. Latency smoke exercises calibration and pacing at 1% of its preliminary
calibration rate, without asserting server capacity on a shared box.

```sh
taskset -c 48-63 python3 calib/survey-cmds.py --port 20200 --smoke --variants 2s-rl0 --redis-threads 4 --output build/smoke-cmds
taskset -c 48-63 python3 calib/survey-latency.py --port 20200 --smoke --output build/smoke-latency
taskset -c 48-63 python3 calib/survey-memory.py --port 20200 --smoke --output build/smoke-memory
taskset -c 48-63 python3 calib/survey-persist.py --port 20200 --smoke --output build/smoke-persist
taskset -c 48-63 python3 calib/survey-scale.py --port 20200 --smoke --output build/smoke-scale
# Exercise all four TomoKV geometries and both Redis thread counts on GET:
taskset -c 48-63 python3 calib/survey-cmds.py --port 20200 --smoke --families strings --output build/smoke-geometries
```

Build artifacts are about 0.9 GiB. Preload is streamed, never materialized as a
disk image. A per-boot 12 GiB persistence-data watchdog aborts an oversized run;
the owned data directory is removed after every server exit, including failures.
Full latency observations are result evidence, not preload data: budget up to
`32 × total completed primary operations` bytes before gzip. For example, one
million observations/second for 15 seconds is 480 MB before compression per
visit. Use a separate results volume or shorter windows if needed, preserving
every observation. Archive completed results before starting the next tool if
the whole worktree, including retained observations, must stay below 15 GiB in total. Delete smoke output only after
recording the summary and any behaviour differences; no smoke preload persists.
