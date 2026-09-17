# tailgen

A standalone C++20 open-loop RESP load generator for server tail latency.
Each pinned worker owns its connections, independently schedules arrivals at
`--rate / --threads`, and submits one command per arrival, round-robin across
its connections. A reply never grants permission for the next send.

## Build and serverless units

From the repository root:

```sh
taskset -c 112-127 make -j8 tailgen build/tailgen-unit
taskset -c 112-127 make -j8 tailgen-unit
```

This builds `build/tailgen` and runs `build/tailgen-unit`, with compilation
finished before the pacing checks. `tailgen-unit-asan` builds/runs the same
units with address and undefined-behavior sanitizers. The binary uses Linux
sockets, epoll, clocks, and pthreads. Compiler and math runtimes are linked
statically; its only dynamic runtime dependencies are libc/pthread and the
system loader. There are no Redis client, histogram, jemalloc, or io_uring
dependencies. `make all` continues to build the server separately.

The units compare histogram quantiles with an exact sort of 1,000,000 samples;
check incremental RESP framing, binary bulk payloads, errors, and malformed
inputs; force partial writes/EAGAIN through a socketpair with 200 outstanding
requests; check FIFO/class/warmup metadata, the saturation interval union,
deterministic workloads, CLI validation, and the exact JSON contract. On one
allowed core they pace 100,000 arrivals at 200,000/s **for each spacing mode**,
requiring mean inter-arrival within 1% of 5 us and no observed gap over 2 ms.
They also check the exponential distribution and fixed-worker phase offsets.
Timing failures fail the unit run; there is no retry or skipped assertion.
The tests open no TCP listener and require no server.

## Exact t01 invocation (maintainer, scheduled box only)

Use t01's already-running server at `127.0.0.1:6379` (1s, read-local off,
overlap on, reorder off, atomic on), with the population from
`tests/abba_workloads.py`: 2,000,000 short keys with 64-byte values and 65,536
`blocker:` keys with 256 KiB values (16 GiB total). Both balancers retain their default on state. This tool does not populate or configure
the server. Adjust host/port when the maintainer's target uses another endpoint.

```sh
taskset -c 84-111 ./build/tailgen \
  --host 127.0.0.1 --port 6379 \
  --rate 717000 --threads 16 --conns 32 --cores 84-111 \
  --mix 'GET:8,BITCOUNT:2' --spacing poisson --seed 1 \
  --short-keys 'memtier-{1..2000000}' \
  --long-keys 'blocker:memtier-{1..65536}' \
  --warmup 3 --duration 20 --max-outstanding 64 \
  > build/t01-tailgen.json 2> build/t01-tailgen.log
```

`--conns` is **per thread**: 32 × 16 = **512 connections**, with 44,812.5
arrivals/s per worker. The 16 workers are spread across the ordered 28-core
list, including both endpoints: 84, 85, 87, 89, 91, 93, 94, 96, 98, 100, 102,
103, 105, 107, 109, 111. The actual mapping is printed to stderr. Supply exactly
16 cores to choose each worker's core explicitly. Omitted `--cores` uses the
process affinity mask; duplicate/disallowed cores and oversubscribed lists fail.

## Options and commands

`--help` prints every option and default to stderr without connecting. Both
`--option value` and `--option=value` work. Seconds and rates accept decimals.
`--duration` is the measurement window, **in addition to** `--warmup`.
`--warmup 0` disables warmup; `--max-outstanding 0` disables the time witness.

Mix weights are nonnegative integers; zero-weight commands are omitted and
at least one weight must be positive. Supported commands/classes are:

| Mix entry | Class | Key/value |
| --- | --- | --- |
| `GET:8` | short | Uniform random short key |
| `SET 64:1` | short | Uniform random short key; 64 `x` bytes |
| `BITCOUNT:2` | long | Uniform random long key |
| `PING:1` | short | No key |

For example, `--mix 'GET:7,SET 64:1,BITCOUNT:2'`. `SET 0` sends an empty
value. Key options accept a quoted `prefix{first..last}suffix` pattern or a
positive count, which selects `memtier-1..N` / `blocker:memtier-1..K`.
Quote braces so the shell passes the pattern intact. The defaults match the
current populations, including `LONG_KEYS=65536`; override the long range if
the harness uses another population.

The PRNG, integer key selection, weighted choices, and per-thread arrival
streams are deterministic for a seed and configuration. Network timings and
OS scheduling remain measured quantities. Fixed spacing staggers worker phases
by `1 / total_rate`, so workers do not send synchronized groups. Poisson workers
use independent exponential inter-arrivals with fractional nanoseconds carried
forward; command/key draws cannot perturb arrival draws.

## Pacing and latency boundaries

All deadlines use `CLOCK_MONOTONIC`. An idle worker uses absolute
`clock_nanosleep` until 60 us before its deadline, then spins. While requests
are outstanding it polls/parses replies during the wait, keeping receive-side
sleep out of latency. Long idle waits are split at most every 50 ms only for
cancellation; each sleep still targets the absolute deadline minus 60 us.
There is no token refill or periodic arrival tick. Late arrivals keep their
original schedule and are issued individually as soon as possible; the worker
does not reset the process to the current time. Requests are prepared before
waiting, and the event loop preserves partially serviced epoll batches.

Latency starts immediately before the first nonblocking send attempt and ends
when that command's complete RESP reply is parsed. The start includes local
queueing if the kernel cannot accept the command immediately; unsent suffixes
remain ordered and do not stop later arrivals. TCP_NODELAY is enabled. Integer,
simple string, bulk string (including nil/empty), and error replies are parsed
incrementally. Each connection pairs completed replies with its request FIFO.
Server errors, malformed/unsolicited replies, disconnects, a latency over
100 s, or a 100 s final drain timeout fail with nonzero exit and **no JSON**.

All workers share one window after their connections are established. A
sample belongs to the measurement if its **send attempt** falls in
`[warmup_end, warmup_end + duration)`. All those replies are drained and
included, even if they finish after the window, avoiding a censored slow tail.
Warmup replies never enter latency histograms. Sends stop at the window end;
any scheduled arrivals the worker could not issue by then are counted in the
stderr diagnostics.

`rate = (short_count + long_count) / window_seconds` is the achieved rate of
the completely replied measurement send cohort. Drain time does not extend
that denominator. For overloaded runs this differs from wall-window reply
throughput: stderr separately reports replies completed inside the window
(including earlier warmup sends), pending work at its end, and drain duration.
Keep that distinction when checking capacity.

The log-linear histogram has 1 us buckets through 2,047 us, then 1,024 buckets
per power-of-two interval through 100 s. Quantiles use nearest rank and the
bucket's upper bound: error is at most `1 us + latency / 1024` (about 0.1%).
Mean and maximum use original nanoseconds. No coordinated-omission correction
or synthetic samples are applied. An empty class reports count and all
statistics as zero.

## Saturation witness

`outstanding_max` is the largest outstanding count on **one connection**
during the measurement window, including queued sends and warmup backlog that
is still pending. `over_max_outstanding_fraction` is the fraction of that wall
window when **any connection on any worker** has strictly more than
`--max-outstanding` requests outstanding. Each worker records transitions;
the final result merges the clipped time intervals by union, without averaging
across workers or double-counting overlap. The threshold is an observer and
never caps the FIFO or delays arrivals. Zero disables interval allocation and
reports a zero fraction; maximum outstanding is still counted. A nonzero
fraction is evidence of queue accumulation and helps distinguish a server
tail from an overloaded cell. Zero alone does not prove headroom: also inspect
achieved rate, pending work, queued bytes, drain time, and pacing lag on stderr.

Pacing diagnostics report mean/p99.9/max schedule lag, the largest worker send
gap, omitted arrivals, and local queued bytes. A descheduled or CPU-limited
generator can still catch up in a burst; these observations expose that case.
Server tail conclusions require a scheduled, quiet-box run with the generator
keeping up. Unit timing validates the pacer alone; no end-to-end tail claim is
made from a serverless test.

## Output contract

Stdout contains one JSON object with exactly these top-level keys:

```json
{"rate":0,"latency_ms":0,"p999_ms":0,"long_p999_ms":0,"short_count":0,"long_count":0,"short":{},"long":{},"outstanding_max":0,"over_max_outstanding_fraction":0,"window_seconds":20}
```

`latency_ms` is the combined mean; `p999_ms` is **short** p99.9.
Each `short`/`long` object contains `count`, `mean_ms`, `p50_ms`, `p90_ms`,
`p99_ms`, `p999_ms`, `p9999_ms`, and `max_ms`. Human summaries include all
requested percentiles for short, long, and combined on stderr. Preserve the
stderr log alongside JSON when judging tails.
