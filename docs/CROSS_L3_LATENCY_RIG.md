# CROSS-L3 IO/EX latency rig

This measurement-only rig predicts the penalty of moving Tomo's IO and EX roles onto different
L3/CCD domains. It inserts a calibrated producer-side wait at the two coherence publications in
one request/reply circuit:

1. after the IO producer writes the real EX ring slot and before it release-publishes `tail`;
2. after the EX producer writes the reply and before it release-publishes the real CDB ready byte.

The wait is a `PAUSE` loop against RDTSCP. A non-zero `tomokv-sim-hop-ns` verifies invariant TSC
and RDTSCP support and calibrates TSC frequency against `CLOCK_MONOTONIC_RAW` once at startup. If
the thread migrates during a wait, the full interval restarts. Unsupported or unstable timing is
a boot error rather than a silently miscalibrated experiment.

## Isolation and the off arm

This is not a production workload feature. At the default `tomokv-sim-hop-ns 0`, startup performs
no calibration and allocates no rig state. Normal IO->EX dispatch and EX->IO completion contain no
test of the knob. The worker recognizes rig messages only inside its pre-existing migration
sentinel arm, which ordinary messages do not enter. Invoking the DEBUG command explicitly creates
the synthetic cycle even for the zero-latency control.

Run the rig on an otherwise idle instance. It refuses dynamic thread mode, key balancing, strict
ordering, an active role flip/migration/resize, or a partially live EX pool.

## Invocation

Start one isolated server for each sweep point. The relevant options are:

```text
./src/redis-server ./tomokv.conf \
  --enable-debug-command yes \
  --tomokv-thread-io 4 \
  --tomokv-thread-ex 4 \
  --tomokv-thread-mode static \
  --tomokv-key-lb 0 \
  --tomokv-strict-order 0 \
  --tomokv-sim-hop-ns 100
```

Attach `perf stat` to the server PID from another shell, then ask Redis to run for a wall-clock
interval. For example, the following command requests 30 seconds:

```text
redis-cli DEBUG TOMO-SIM-HOP 30000
```

Sweep `tomokv-sim-hop-ns` through `0, 50, 100, 200, 400`, restarting between points because the
knob is immutable. The DEBUG argument is milliseconds; it is deliberately wall time rather than a
self-measured cycle budget, so the coordinator owns the `perf stat` event set and interval.

## Workload and output

Before starting the clock, the command allocates and routes a fixed cycle of 32 synthetic
GET/EXISTS-shaped messages with keys `tomo-sim-hop:key:00` through `:31`. There is no `rand()`, key
formatting, allocation, command parsing, or routing hash in the timed loop. The synthetic command
does not access the database; it emits a deterministic integer reply (whose expected RESP bytes are
pre-generated) while retaining the real client header, ring, worker batch, handoff, and CDB
mechanics under measurement.

A healthy reply has this shape:

```text
status=ok
hop_ns=100
requested_ms=30000
elapsed_ms=30000
calibration=invariant-tsc
tsc_hz=<non-zero>
cycle_len=32
cycle_hash=<stable 16-hex value>
operations=<non-zero>
io_to_ex=<same as operations>
ex_to_io=<same as operations>
errors=0
```

`elapsed_ms` may exceed the request by at most one 32-message issue cycle plus the final drain: the
command checks wall time once per fixed cycle and never abandons an in-flight header. Use
`1000 * operations / elapsed_ms` for the command's achieved operations/second, and keep external
`perf stat` attached through the reply so its interval includes that same drain. The zero control
reports `calibration=off` and
`tsc_hz=0`. A healthy sweep keeps `cycle_hash` identical and has
`operations == io_to_ex == ex_to_io`, with `errors=0` at every point. Plot operations/second and
external IPC against the two injected hop delays; compare header-size variants using the same
cycle, duration, placement and perf event set.
