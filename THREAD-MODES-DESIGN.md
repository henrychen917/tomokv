# Polymorphic Thread Modes — design (v1)

Threads are not born io/ex/wb — they HOLD A MODE and shift by load. Total threads fixed
(= populated cores or configured N); the balancer moves the MODE MIX, never the count.
CPU-architecture framing: morphable execution units; mode shifts are DVFS-like state
transitions with asymmetric latencies.

## Modes & transitions
| transition | mechanism | cost |
| :-- | :-- | :-- |
| EX-exit | migrate own buckets away (v8d effect-log + drain-fence — EXISTS) | ms, bounded |
| EX-entry | wake + migrate buckets in (same machinery) | ms, bounded |
| WB<->any (3s) | fenced client->wb re-partition | cheap |
| IO-entry | start accepting on own SO_REUSEPORT listener | INSTANT |
| IO-exit | stop accepting; pinned conns drain naturally; HYBRID io-drain + ex-warmup meanwhile | gradual |

## Balancer (micro-arch controller, current-signal only)
Signals: io busy% EWMA, ex queue-depth EWMAs (exist in reshard controller), wb backlog EWMA.
Decision: hysteresis band + settle window (reshard patterns); shift ONE thread per settle.
Knobs: tomokv-io-threads-min/max, tomokv-ex-threads-min/max (0=auto: min 1, max=cores);
static mode (current mandatory counts) remains the default until dynamic proves itself.
Pin modes: 0 pure-float, 1 manual, 2 pure arch-aware, 3 dynamic-float, 4 dynamic-arch-aware
(re-derive placement on shift events).

## Danger zones (from this codebase's history)
- iotid TLS aliasing when a thread changes role (the historic worker-slot crash class):
  mode-scoped identity must swap iotid/worker-id ATOMICALLY at the checkpoint, and
  current_client[]/queues[producer]/freeback[producer] indexing must be valid for BOTH
  roles during the transition window.
- All per-role structures sized for total-N at boot (any thread can hold any role).
- Transitions only at safe checkpoints: EX = post-drain-fence (no in-flight on own shard);
  IO = empty-event-loop pass; WB = post-retire fence.

## V1 scope
1. Unified thread main: `while(1) switch(atomic mode){IO: ioSlice(); EX: exSlice(); WB: wbSlice();}` —
   refactor ioThreadMain/exThreadMain bodies into single-pass slice functions.
2. EX<->WB shifting (3s) + IO-entry / gradual IO-exit (both forks).
3. Balancer v1: ex-queue-depth vs io-busy EWMA ratio, one shift per settle window.
