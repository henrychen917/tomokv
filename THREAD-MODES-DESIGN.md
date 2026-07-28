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
Knobs (AS SHIPPED 2026-07-27): the min/max bounds are no longer user knobs — they are derived
from the node budget (min 1 of each role, max cores-per-node - 1). The one policy knob is
`tomokv-thread-mode auto|static`; `tomokv-thread-io`/`-ex` give the starting split in both modes.
Pin modes (AS SHIPPED): `float`, `ccd` (default), `numa`, `static`. The design's "dynamic-float /
dynamic-arch-aware" (re-derive placement on shift events) is NOT implemented — a converted thread
keeps the core it was pinned to.

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

## V1 status (steps 1-3 landed, 2s fork)
Legal transitions are SPARE-ONLY: PARKED->IO (step 2, instant listener join),
PARKED->EX and EX->PARKED (step 3, migration-backed on the v8d effect-log engine;
go-live/delist keyed to the bucket-table FLIP via num_workers_live, spare slot
pre-allocated via num_workers_alloc, parked shard asserted EMPTY). Rejected until
built: IO-exit (gradual conn drain) — so IO->PARKED and any direct IO<->EX swap
refuse at both the config layer and the poly checkpoint; WB is unreachable in the
2s fork (modeshift value 3 is repurposed as the explicit park verb). Non-spare
threads never shift. Driver: CONFIG SET tomokv-modeshift-test (balancer pending).
