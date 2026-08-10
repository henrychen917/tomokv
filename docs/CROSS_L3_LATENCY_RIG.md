# CROSS-L3 IO/EX latency rig

This measurement-only rig predicts the penalty of placing Tomo's IO and EX roles on different
L3/CCD domains. It applies delayed visibility to normal workload traffic at both coherence
boundaries. Producers publish immediately and keep working.

1. Every IO→EX ring entry has a timestamp in a simulator-only sidecar. After acquiring the queue
   tail, the worker consumes only the visible FIFO prefix. An immature head remains advertised and
   the worker rotates to other lanes, so visible work is not held behind a simulated wait.
2. Every EX→IO CDB completion has a matching sidecar timestamp written before the ready-byte
   release. After acquiring the ready byte, the IO drain leaves an immature completion pending and
   continues draining other ready clients.

A batched tail publication gives every entry a descriptor for the same publication timestamp; the
ring and CDB layouts covered by the notification invariants are unchanged.

## Clock and migration guard

A non-zero `tomokv-sim-hop-ns` verifies invariant TSC and RDTSCP support and calibrates TSC
frequency against `CLOCK_MONOTONIC_RAW` once at startup. Consumer visibility samples bracket the
timestamp read with RDTSCP. If the scheduler migrates the consumer during a sample, that entry is
conservatively treated as not visible for the current pass; no thread spins to reconstruct the
interval. Unsupported or unstable timing is a boot error rather than a silently miscalibrated
experiment.

## Off arm

At the default `tomokv-sim-hop-ns 0`, `redis-server` contains no simulator queue/CDB hot-path hook,
per-entry sidecar allocation, or TSC calibration. A non-zero setting re-executes the separately
compiled `redis-server-sim` specialization before server threads, clients, or rings are created.
The simulator binary refuses a zero setting. Config-from-stdin cannot be replayed across that
re-exec, so use a config file or command-line options for a non-zero point.

## Running a sweep

Run the same real workload against a fresh isolated server for every point. For example:

```text
./src/redis-server ./tomokv.conf \
  --tomokv-thread-io 4 \
  --tomokv-thread-ex 4 \
  --tomokv-thread-mode static \
  --tomokv-sim-hop-ns 100
```

Sweep `tomokv-sim-hop-ns` through values such as `0, 50, 100, 200, 400`, restarting between points
because the knob is immutable. The coordinator owns the workload interval, placement, and external
performance counters; there is no synthetic DEBUG workload.

## Engagement witness

`INFO stats` exposes cumulative counts of entries that a consumer deferred at least once:

```text
tomokv_sim_hop_io_to_ex_deferred:<count>
tomokv_sim_hop_ex_to_io_deferred:<count>
```

Record counter deltas over the same interval as the workload. Both deltas must be non-zero at every
non-zero sweep point. A flat performance curve can be meaningful only when these counters move; a
flat curve with a flat or zero counter is a vacuous measurement. The zero control reports both
counters as zero.
