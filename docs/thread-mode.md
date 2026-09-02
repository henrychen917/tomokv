# Thread modes and overlap schedules

`--thread-mode 2s|1s` and `--overlap 0|1|2` select TomoKV's thread architecture and fixed
amortization schedule at boot. The defaults are `2s` and `0`, so an existing command line or
configuration keeps the ordinary separated-loop behavior. `split` and `fused` remain accepted as
aliases for `2s` and `1s`; the new names are the values reported by `INFO Server` and immutable
`CONFIG GET` entries. `CONFIG GET overlap` is canonical. For one compatibility release,
`INFO Server` also emits the old `thread_pipeline` field beside `overlap`.

`--read-local 0|1` is also boot-only and defaults to `0`. A value of `1` arms the local read lane
described below only for `1s` overlap 0. Every other legal mode/overlap cell accepts the setting but
keeps reads on the ordinary owner-task path and logs one notice at boot. The setting is exposed by
`CONFIG GET` and refused by `CONFIG SET`.

| mode | overlap 0 | overlap 1 | overlap 2 |
| --- | --- | --- | --- |
| `2s` | ordinary separated IO/executor loops | `t-iopipe` interwoven WB/IFID schedule | rejected |
| `1s` | coarse generalized-thread rotation | `t-genthread` `iofused` schedule | `t-genthread` `streams` schedule |

Overlap 2 prints a boot warning identifying it as an experimental research schedule. Unified
overlap 1 and 2 require `--net-io uring` because their measured schedules share a single explicit
submission boundary. The shipped `--thread-pipeline` spelling remains a numeric alias for
`--overlap`. The compatibility knob `--genthread-schedule` accepts only `coarse`, `iofused`, or
`streams` and selects the corresponding `1s` overlap value.

## 2s: separated threads

Mode `2s` assigns each physical thread one live role. IO (`ifid`) threads receive, parse, route,
retire, and send; executor (`ex`) threads own shards and execute commands. With no placement knob,
TomoKV makes the same even IO/ex split across the allowed CPUs as before.

Overlap 0 is the unchanged plain-loop baseline. Overlap 1 is the exact measured `t-iopipe`
schedule: it interweaves bounded WB and IFID batches inside each IO thread while retaining separate
executor threads. Its shallow order, depth-selected natural order, prefetch walks, and submission
boundary are fixed rather than tunable. Overlap 2 is rejected because the deep streams schedule
requires unified ownership.

Use `2s` when you need `--ratio`, explicit IO/ex role placement, manual `FLIP`, or the automatic
flip controller. It also remains the conservative choice outside the unified architecture bench's
tested core-count and overlap regimes.

## 1s: unified generalized threads

Mode `1s` gives every selected physical thread both an IO loop object and an executor loop object.
Overlap 0 rotates three coarse streams in this order:

1. maintain connections and parse/route at most 32 operations per connection pass;
2. consume an executor batch of at most 32 operations;
3. collect completions and serve at most 16 connections.

With `--read-local 0`, local commands take the same self SPSC task lane as remote commands and are
consumed during the executor phase; they are not executed inline. With `--read-local 1`, eligible
plain single-key GETs instead enter a parsing-thread-local queue. The overlap-0 executor phase
drains that queue immediately after parsing, in the same coarse rotation, and replies still retire
through the connection ROB and normal write-back path. Parsing never waits for that local queue to
retire: a later same-hash write first moves the connection's not-yet-executed local batch to ordinary
owner queues, then publishes behind it; conservative writes do the same without a hash precheck.
Reads with an outstanding same-hash connection write (or a conservatively overflowed
write ring), WATCH or MULTI state, script/scatter context, target-shard atomic work, a missing or
typed value, an expired value, sequence churn, or a full local lane fall back to the ordinary
owner-task path.

Overlap 1 selects the fork's exact `iofused` schedule, which overlaps its WB dependency stream and
network work around a 128-operation coarse executor turn. Overlap 2 selects the exact deep
`streams` schedule: independent IFID, EX, and WB contexts use its depth gate, one-rotation residual
carry, and literal interleave. Read-local is not woven into either schedule in this version, so
enabling its knob there retains the task path. Overlap 2 is exposed for research rather than as a
production recommendation.

With no `--place`, `1s` uses every CPU in the process affinity mask. `--place` can select a subset;
its `ifid@CPU` and `ex@CPU` labels are treated only as CPU selectors because every selected thread
has both responsibilities. `--ratio` is rejected because there are no separate role counts.
`--flip-auto` is also rejected, the flip controller does not start, and `FLIP` returns a clear
mode-unavailable error. Existing key load-balancing bucket movers remain available.

## Choosing a cell

The architecture bench found unified mode strongest through 16 cores: it led tuned separated mode
by 9–21% at 8 cores, and at 16 cores with a client request-pipeline depth of 128 it led by 2.4% for
GET and 10% for SET. Those results should not be extrapolated to larger core counts or different
workloads without a separate measurement.

Use overlap 0 when the purpose is ordinary operation or a study baseline. Overlaps 1 and 2 are
fixed measurement cells: select them only when the schedule itself is the variable under study.
Choose `2s` when runtime role reshaping or ratio tuning matters, or when deploying beyond the
measured unified envelope.
