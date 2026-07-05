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

## V1 status (steps 1-3 landed, 2s fork)
Legal transitions are SPARE-ONLY: PARKED->IO (step 2, instant listener join),
PARKED->EX and EX->PARKED (step 3, migration-backed on the v8d effect-log engine;
go-live/delist keyed to the bucket-table FLIP via num_workers_live, spare slot
pre-allocated via num_workers_alloc, parked shard asserted EMPTY). Rejected until
built: IO-exit (gradual conn drain) — so IO->PARKED and any direct IO<->EX swap
refuse at both the config layer and the poly checkpoint; WB is unreachable in the
2s fork (modeshift value 3 is repurposed as the explicit park verb). Non-spare
threads never shift. Driver: CONFIG SET tomokv-modeshift-test (balancer pending).

## Balancer pressure signals (user spec, step 4)
Shift decisions read PRESSURE, not guesses — each signal a cheap current-value/EWMA, micro-arch style:

| signal | source | Tomasulo analog |
| :-- | :-- | :-- |
| ingress queue backlog | epoll-ready count + unparsed querybuf bytes per io thread | fetch-queue occupancy |
| worker queue backlog | SPSC queue depths (head-tail), EWMA per worker (reshard controller has these) | reservation-station occupancy |
| reply ROB occupancy | per-conn in-flight (dispatchid - flushid) aggregated per io thread | ROB occupancy |
| socket write backlog | clients_pending_write length + pending reply bytes (+ kernel sndbuf if cheap) | retire/writeback pressure |
| per-role CPU idle/spin ratio | idle-episode ticks vs busy slices per thread (adaptive-spin state already tracks episodes) | port utilization |
| p99 command latency | sampled latency ring / hdr histogram (guardrail, not a trigger) | pipeline stall indicator |

Decision shape: shift TOWARD the role with sustained high pressure ONLY when a donor role shows
headroom (high idle/spin ratio + low backlog) — pressure differential with hysteresis band + settle
window, one shift per window. p99 latency is the GUARDRAIL: if p99 degrades during/after a transition,
back off and extend settle (transitions are DVFS-like states; the balancer must respect their costs:
EX shifts = migration ms, IO-exit = gradual drain). All signals current-value or leaky EWMA — no
history accumulation, shifts re-evaluate on a dime.
