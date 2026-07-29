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

## Status (2s fork, AS SHIPPED 2026-07-28)
THERE ARE EXACTLY TWO TRANSITIONS, and they are each other's inverse:

- **GROW-FRONT, EX->IO** ("front flip back"): migrate the converting worker's whole bucket
  range to its node-internal neighbour on the v8d effect-log engine, delist it
  (`num_workers_live--`) before the arm, and after the migration's teardown hand the thread the
  IO role. Its checkpoint drains straggler queues to quiet, asserts it owns ZERO buckets, then
  takes the io identity and `listen()`s its pre-bound dormant socket into the REUSEPORT group.
  `io_threads_live++` when the new mode is published.
- **GROW-BACK, IO->EX** ("back flip front"): the io thread runs IO-EXIT — leaves the accept
  group, migrates every conn out load-aware — and when its last conn is gone it requests the EX
  role from its own service-out tail (only that thread can observe that edge). Its checkpoint
  re-validates the exit, takes the worker identity, and the controller then seeds it half of its
  neighbour's range; `num_workers_live++` at that seed FLIP.

Both changes complete in ONE checkpoint. There is no resting mode between the roles and no
reserve thread: the pool is always exactly `io_threads + num_workers`, and a flip only moves the
boundary. WB is unreachable in the 2s fork (no WB slice).

The PARKED mode and its spare thread were DELETED 2026-07-28 (owner ruling). PARKED had been the
enum's zero value, so `tomoThreadMode` now starts at 1 and 0 is an invalid mode that trips an
assert at the checkpoint — see the enum comment in server.h.

Drivers: the auto flip controller (`tomokv-thread-mode auto`), or `DEBUG TOMO-MODESHIFT`
7/8 (single-node grow front/back) and 70+n/80+n (per-node) by hand.
