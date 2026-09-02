# Thread modes and pipeline schedules

`--thread-mode 2s|1s` and `--thread-pipeline 0|1|2` select TomoKV's thread architecture and fixed
amortization schedule at boot. The defaults are `2s` and `0`, so an existing command line or
configuration keeps the ordinary separated-loop behavior. `split` and `fused` remain accepted as
aliases for `2s` and `1s`; the new names are the values reported by `INFO Server` and immutable
`CONFIG GET` entries.

| mode | pipeline 0 | pipeline 1 | pipeline 2 |
| --- | --- | --- | --- |
| `2s` | ordinary separated IO/executor loops | `t-iopipe` interwoven WB/IFID schedule | rejected |
| `1s` | coarse generalized-thread rotation | `t-genthread` `iofused` schedule | `t-genthread` `streams` schedule |

Pipeline 2 prints a boot warning identifying it as an experimental research schedule. Unified
pipeline 1 and 2 require `--net-io uring` because their measured schedules share a single explicit
submission boundary. The hidden compatibility knob `--genthread-schedule` accepts only `coarse`,
`iofused`, or `streams` and selects the corresponding `1s` pipeline value.

## 2s: separated threads

Mode `2s` assigns each physical thread one live role. IO (`ifid`) threads receive, parse, route,
retire, and send; executor (`ex`) threads own shards and execute commands. With no placement knob,
TomoKV makes the same even IO/ex split across the allowed CPUs as before.

Pipeline 0 is the unchanged plain-loop baseline. Pipeline 1 is the exact measured `t-iopipe`
schedule: it interweaves bounded WB and IFID batches inside each IO thread while retaining separate
executor threads. Its shallow order, depth-selected natural order, prefetch walks, and submission
boundary are fixed rather than tunable. Pipeline 2 is rejected because the deep streams schedule
requires unified ownership.

Use `2s` when you need `--ratio`, explicit IO/ex role placement, manual `FLIP`, or the automatic
flip controller. It also remains the conservative choice outside the unified architecture bench's
tested core-count and pipeline regimes.

## 1s: unified generalized threads

Mode `1s` gives every selected physical thread both an IO loop object and an executor loop object.
Pipeline 0 rotates three coarse streams in this order:

1. maintain connections and parse/route at most 32 operations per connection pass;
2. consume an executor batch of at most 32 operations;
3. collect completions and serve at most 16 connections.

Local commands take the same self SPSC task lane as remote commands and are consumed during the
executor phase. They are not executed inline. Pipeline 1 selects the fork's exact `iofused`
schedule, which overlaps its WB dependency stream and network work around a 128-operation coarse
executor turn. Pipeline 2 selects the exact deep `streams` schedule: independent IFID, EX, and WB
contexts use its depth gate, one-rotation residual carry, and literal interleave. It is exposed for
research rather than as a production recommendation.

With no `--place`, `1s` uses every CPU in the process affinity mask. `--place` can select a subset;
its `ifid@CPU` and `ex@CPU` labels are treated only as CPU selectors because every selected thread
has both responsibilities. `--ratio` is rejected because there are no separate role counts.
`--flip-auto` is also rejected, the flip controller does not start, and `FLIP` returns a clear
mode-unavailable error. Existing key load-balancing bucket movers remain available.

## Choosing a cell

The architecture bench found unified mode strongest through 16 cores: it led tuned separated mode
by 9–21% at 8 cores, and at 16 cores with pipeline 128 it led by 2.4% for GET and 10% for SET. Those
results should not be extrapolated to larger core counts or different workloads without a separate
measurement.

Use pipeline 0 when the purpose is ordinary operation or a study baseline. Pipelines 1 and 2 are
fixed measurement cells: select them only when the schedule itself is the variable under study.
Choose `2s` when runtime role reshaping or ratio tuning matters, or when deploying beyond the
measured unified envelope.
