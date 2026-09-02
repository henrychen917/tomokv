# Thread modes

`--thread-mode split|fused` selects TomoKV's thread architecture at boot. The default is `split`,
so an existing command line or configuration keeps the same placement, behavior, and controls.
The selected value is reported as `thread_mode` by `INFO Server` and as the immutable
`thread-mode` value by `CONFIG GET`.

`--read-local 0|1` is also boot-only and defaults to `0`. A value of `1` enables the fused local
read lane described below; split mode accepts it as an inert compatibility setting and logs one
notice at boot. Both settings are exposed by `CONFIG GET` and refused by `CONFIG SET`.

## Split

Split mode assigns each physical thread one live role. IO (`ifid`) threads receive, parse, route,
retire, and send; executor (`ex`) threads own shards and execute commands. With no placement knob,
TomoKV makes the same even IO/ex split across the allowed CPUs as before.

Use split when you need `--ratio`, explicit IO/ex role placement, manual `FLIP`, or the automatic
flip controller. It also remains the conservative choice outside the fused architecture bench's
tested core-count and pipeline regimes.

## Fused

Fused mode gives every selected physical thread both an IO loop object and an executor loop object.
One physical thread rotates three coarse streams in this order:

1. maintain connections and parse/route at most 32 operations per connection pass;
2. consume an executor batch of at most 32 operations;
3. collect completions and serve at most 16 connections.

Local commands take the same self SPSC task lane as remote commands and are consumed during the
executor phase. They are not executed inline. This is the coarse three-stream rotation from
`wt-genthread` commits `53bf7f9d1` and `d2af4a487`; the later interleaved schedule is intentionally
not part of the supported mode.

With `--read-local 1`, eligible plain single-key GETs instead enter a parsing-thread-local queue.
That queue is still drained by the thread's executor phase, and replies still retire through the
connection ROB and normal write-back path. Reads with an outstanding connection write, WATCH or
MULTI state, script/scatter context, target-shard atomic work, a typed value, or an expired value
fall back to the ordinary owner-task path.

With no `--place`, fused mode uses every CPU in the process affinity mask. `--place` can select a
subset; its `ifid@CPU` and `ex@CPU` labels are treated only as CPU selectors because every selected
thread has both responsibilities. `--ratio` is rejected because there are no separate role counts.
`--flip-auto` is also rejected, the flip controller does not start, and `FLIP` returns a clear
mode-unavailable error. Existing key load-balancing bucket movers remain available.

## Choosing a mode

The architecture bench found fused strongest through 16 cores: it led the tuned split by 9–21% at
8 cores, and at 16 cores with pipeline 128 it led by 2.4% for GET and 10% for SET. In those regimes
it was 48–103% ahead of Redis 7.4's single-thread baseline. Those are the regimes supporting the
choice; they should not be extrapolated to larger core counts or different workloads without a
separate measurement.

For a workload resembling those tested regimes, start with fused. Choose split when runtime role
reshaping or ratio tuning matters, or when deploying beyond the measured fused envelope.
