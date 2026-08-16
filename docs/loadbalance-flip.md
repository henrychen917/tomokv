# Load balancing: flip controller, key-LB, and client-LB

This document describes the implementation in the current tree.  It treats executable branches and data accesses as authoritative; known comment/code disagreements are collected in [Comment/code discrepancies](#commentcode-discrepancies).

When `tomokv-thread-wb` is positive or AUTO-derived, WB is a separate fixed-role pool. The existing controller continues to convert IO and EX only; it never changes WB count, placement, client assignment, or producer lanes. Three-role flipping is a known follow-up, not part of this release. See [Boot-selectable write-back stage](writeback-stage.md#flip-boundary-and-known-follow-up).

## What the three mechanisms move

| Mechanism | What it changes | Actual control surface | Invocation | Source |
| --- | --- | --- | --- | --- |
| Flip controller | Converts one or more provisioned threads between EX and IO roles while preserving the provisioned pool size; its two physical moves are EX-to-IO (`grow-front`) and IO-to-EX (`grow-back`). | There is no registered `tomokv-flip` configuration item.  Automatic actuation is selected by immutable `tomokv-thread-mode auto`; `static` keeps the starting split. | Main-thread cron calls `tomoFlipController()` every 250 ms, and the function returns immediately unless `server.thread_auto` is true and flip headroom exists. | `src/config.c:3212-3219`, `src/server.h:1525-1531`, `src/server.c:2951-2955`, `src/server.c:25570-25574` |
| Key-LB | Moves ownership of a contiguous bucket range between adjacent EX workers in the same logical node. | Modifiable integer `tomokv-key-lb`, range `0..INT_MAX`, default `20000`, stored as `server.reshard_min_ops`; zero disables the controller. | Main-thread cron calls `reshardAutoTune()` every 1,000 ms. | `src/config.c:3292`, `src/server.h:4121-4123`, `src/server.c:2943-2947`, `src/server.c:17004-17015` |
| Client-LB | Moves eligible live client connections between IO owners without changing their sockets or protocol state. | Modifiable boolean `tomokv-client-lb`, default `1`, stored as `server.tm_client_lb`. | Main-thread cron calls `tmClientBalanceCron()` every 1,000 ms. | `src/config.c:3311`, `src/server.h:3304-3305`, `src/server.c:2945-2948`, `src/server.c:24030-24083`, `src/server.c:24227-24259` |

The three decisions are separate but share actuators: a flip can invoke the bucket cutover machinery and a one-shot client backfill, while key-LB invokes the same bucket cutover machinery and continuous client-LB invokes the same connection mailbox/handoff machinery used by grow-back evacuation. `src/server.c:23572-23615`, `src/server.c:23705-23717`, `src/server.c:23964-24020`, `src/server.c:24310-24582`

## Operator surface as implemented

- `tomokv-thread-mode` is an immutable enum with `auto=0` and `static=1`, defaulting to `auto`; initialization sets `server.thread_auto = (server.thread_mode == TOMO_THREAD_MODE_AUTO)` and leaves the poly-thread execution model enabled in both modes. `src/server.h:1525-1531`, `src/config.c:170-175`, `src/config.c:3219`, `src/server.c:5614-5625`
- `tomokv-thread-io` and `tomokv-thread-ex` are immutable starting counts per logical node; boot may derive one from `tomokv-cores-per-node`, rejects a non-positive resolved side, and sets the provisioned global totals to `nodes * per-node count`. `src/config.c:3209-3210`, `src/config.c:3243-3244`, `src/server.c:5717-5776`
- `tomokv-thread-wb` is immutable: `0` keeps the two-stage path, positive `N` creates that many fixed WB threads per node, and `-1` uses the physical-core-budget remainder. It is deliberately absent from `tomoThreadMode`, so no flip checkpoint can adopt WB.
- No config entry named `tomokv-flip`, `tomokv-flip-signal`, or `tomokv-flip-rebalance` is created in the load-balancing/config block; the productive-work signal is hardcoded and flip-time client backfill is derived as `server.tm_flip_rebalance = server.thread_auto`. `src/config.c:3212-3311`, `src/server.c:5621-5625`, `src/server.c:25014-25016`, `src/server.c:25631-25641`
- `tomokv-key-lb=N` supplies the key-LB mean-load floor, and `tomokv-reshard-fence-timeout=N` supplies a separate modifiable cutover watchdog in milliseconds, with range `0..INT_MAX`, default `10000`, and zero meaning no timeout. `src/config.c:3292-3303`, `src/server.h:4121-4123`
- `tomokv-client-lb` gates only new continuous rebalance requests; the IO-loop migration service continues to run, so changing the knob to false does not cancel a request or handoff already in progress. `src/server.c:24029-24034`, `src/server.c:4406-4417`
- Neither `reshardAutoTune()` nor `tmClientBalanceCron()` tests `server.thread_auto`, so key-LB and continuous client-LB remain eligible in static thread mode when their own gates pass. `src/server.c:16797-16825`, `src/server.c:24030-24042`
- Grow-back's connection-drain deadline is a separate fixed `10000` ms assignment, not `tomokv-reshard-fence-timeout`. `src/server.c:23664-23670`

## Shared topology and state

### Provisioned versus live roles

The only thread-role values are `TOMO_MODE_UNSET=-1`, `TOMO_MODE_IO=1`, and `TOMO_MODE_EX=2`; zero is intentionally not a role. `src/server.h:2498-2525`

Each `polyThreadCtx` stores its fixed `ex` and `io` bindings, fixed `io_slot` and `ex_slot` identities, owner-private `io_listening`, atomic `mode` and `target_mode`, and its `pthread_t`.  The owner changes `mode` only at a between-slice checkpoint; the control plane normally publishes `target_mode`, with the grow-back IO owner as the explicit exception after it drains its clients. `src/server.h:3042-3080`

For eligible single-node auto configurations, initialization remaps the pool to one base IO identity plus `pool-1` EX-capable convertible contexts, then births the highest contexts in IO mode to reproduce the requested starting split; static and multi-node configurations keep their ordinary provisioning. `src/server.c:5782-5831`, `src/server.c:22878-22912`

The provisioned `server.num_workers` is immutable after initialization, while atomic `num_workers_live`, `io_threads_live`, `tm_node_wlive[16]`, and `tm_node_iolive[16]` describe the current consuming roles; the per-node live EX set is maintained as a prefix by converting the highest live worker first. `src/server.h:3220-3247`, `src/server.c:6036-6053`, `src/server.c:27351-27358`

Worker `w` maps to `w/ex_per_node`; a base IO slot maps by `io_slot/io_per_node`; and a growth IO slot inherits the node of its fixed EX binding. `src/server.c:24698-24710`

Growth capacity is initially `ex_threads-1`, capped so `io_threads + tm_ngrow_io` does not exceed `TOMO_IO_THREADS_MAX`. `src/server.c:5832-5839`

### Flip gate and actuator state

| State | Fields and ownership | Source |
| --- | --- | --- |
| Global claim | Atomic `server.tm_flip_ctx` is `NULL` when idle, a private marker between claim and publication, and the converting `polyThreadCtx *` after publication.  The winning path publishes the plain `tm_flip_target` and `tm_flip_phase` through this edge. | `src/server.c:90-100`, `src/server.h:3248-3257` |
| Grow-back arbitration | Atomic `tm_flip_gb_state` uses `IDLE`, `DRAINING`, `COMMITTED`, `CANCEL_REQUESTED`, and `ROLLED_BACK`; `tm_flip_abort_ms`, `tm_flip_aborted_node`, and `tm_flip_aborted` carry deadline/abort state. | `src/server.c:106-114`, `src/server.h:3258-3273` |
| Live-accounting/cutover bridge | `tm_flip_wslot` identifies the revived EX slot; `tm_mig_flip_action` tells reshard teardown whether to finish an EX-to-IO flip; `tm_relevel_pending` requests deterministic bucket correction; atomic `reshard_done_seq` is the controller's reshard-quiescence observation. | `src/server.h:3274-3282`, `src/server.h:3292-3293`, `src/server.h:3362-3371` |
| Pool shape | `tm_ngrow_io`, `tm_boot_io_live`, `tm_boot_w_live`, `tm_pool_symmetric`, `tm_flip_rebalance`, and `tm_client_lb` hold growth capacity, boot live counts, remap status, derived flip backfill, and the independent continuous-client gate. | `src/server.h:3292-3305` |

`tmFlipTryClaim()` performs a strong `NULL -> marker` CAS with success order `acq_rel` and failure order `acquire`; a real context and final `NULL` are release-stored, and readers acquire-load.  `tmFlipRelease()` resets the plain target/phase state before reopening the gate and invokes the accounting rollback hook first. `src/server.c:116-150`

### Per-node `flipCtlState`

The main-thread-owned `fctl[16]` array holds one `flipCtlState` per logical node. `src/server.c:24761-24912`

| Field group | Actual members | Source |
| --- | --- | --- |
| Throughput distribution | `mean`, `var`, `ops_prev`, `ops_prev_ms`, `primed`. | `src/server.c:24762-24765` |
| Climb and measurement | `dir`, `phase`, `wait`, `warm_ticks`, `meas_ticks`, `settle_run`, `rs_prev`, `rs_quiet`, `warm_prev`, `ref_ops`, `ref_ms`, `before`, `last_dir`, `step_moves`, `step_done`, `step_armed`, `revert_dir`, `revert_retry`, `refuse_run`. | `src/server.c:24766-24788` |
| Veto and total saturation | `veto_run`, `start_io`, `veto_lr`, `sat_smooth`. | `src/server.c:24789-24806` |
| Role observations | `io_occ_smooth`, `ex_occ_smooth`, `io_wait_u_smooth`, `io_work_u_smooth`, `ex_work_u_smooth`, `u_io_mean`, `u_io_var`, `u_ex_mean`, `u_ex_var`, `u_noise_primed`. | `src/server.c:24806-24820` |
| Ratio and frozen anchor | `just_settled`, `lr_ewma`, `lr_init`, `lr_prev_tick`, `lr_quiet_run`, `anchor_n`, `lr_anchor`, captured U/rate/split members, `anchor_sat_rebase`, and the anchor rate-plateau members. | `src/server.c:24821-24853` |
| Directional floor episode | The `floor_probe_*` flags, entry/legal/target/best split fields, plan/visit/direction fields, movement and check snapshots, and `floor_probe_candidates[]`. | `src/server.c:24854-24880` |
| Drop damping | `lr_out_dir/run`, `floor_out_dir/run`, `episode_revert_run`, `revert_run_io`, `lr_mean/var`, frozen `anchor_lr_sigma`, and `anchor_out_dir/run`. | `src/server.c:24882-24902` |
| Hill-climb result | `idle_stable`, `best_rate`, `best_dist`, `coast_used`, `revert_steps`, `walkback_armed`. | `src/server.c:24903-24911` |

`revert_dir`, `revert_retry`, and `lr_prev_tick` remain stored members but do not drive the current controller: the first pair is only cleared on a new step, and quietness compares the local pre-update `lr_ewma` with its new value. `src/server.c:24786-24787`, `src/server.c:24835-24836`, `src/server.c:26062-26066`, `src/server.c:27050-27056`, `src/server.c:27303-27315`

### Signal structures

The LB-relevant `tmIoSignal` members are plain `busy_ewma_q4`, `tm_idle_us`, `tm_wait_us`, `tm_busy_us`, `rob`, `pend_write`, `tm_work_us`, `tm_ring_stall_us`, `tm_drain_bytes`, and `tm_read_events`, plus atomic `pinned_nonmig`; slots are cache-line aligned, owner-written, and—with the exception of the declared atomic—read racily by control-plane code. `tm_idle_us` feeds the IO demand occupancy, `tm_work_us` feeds productive direction, and `tm_busy_us` is a trace/INFO CPU diagnostic. `src/server.c:649-774`

The LB-relevant `exThread` members are atomic `ops_total` and `loop_seq`, plain `lb_grp_ops[]`, `tm_qdepth_ewma_q4`, `tm_idle_us`, and `tm_busy_us`, plus atomic `lb_fine_win` and plain `lb_fine_ops[]`. `src/server.h:2591-2612`, `src/server.h:2617-2653`, `src/server.h:2702-2712`

### Key-LB and cutover state

Routing has 16,384 buckets; a key maps to `xxh64(key) & 16383`, `server.ex_bucket_table[bucket]` gives the owner worker, and `server.ex_bucket_end[]` records contiguous worker-range ends. `src/server.h:1560-1571`, `src/server.h:3377-3381`, `src/server.c:9550-9555`

Each `exThread` contains atomic `ops_total`, plain `lb_grp_ops[256]`, atomic `lb_fine_win`, and plain `lb_fine_ops[64]`; the geometry is 256 coarse groups of 64 buckets, and the fine word encodes `(length << 32) | low_bucket`, with zero length disarmed. `src/server.h:1578-1598`, `src/server.h:2591-2606`, `src/server.h:2702-2712`

Controller-owned key-LB state uses `mig_load_ewma[]`, `mig_load_ewma_fast[]`, `mig_last_ops[]`, `mig_ewma_primed`, `mig_hot_streak[]`, `mig_peak_pre`, and `mig_settle`; lazy profile storage is `mig_grp_ewma/last/rows` plus `mig_fine_ewma/last/grp/warm/rows`, and `mig_trig` stores gate counters and the last signal snapshot. `src/server.c:16189-16219`, `src/server.c:16247-16287`

The per-plan `migProfile` carries `row`, optional `fine`, `fine_sum`, `fine_g`, and uniform fallback `uni`; separate diffusion state is exactly `mig_diff_peak`, `mig_diff_settle`, and `mig_diff_streak[]`, while its candidate boundary/direction are recomputed as locals. `src/server.c:16289-16303`, `src/server.c:16717-16745`

The shared migration record contains atomic `migration_active`; atomic generation and phase; plain `[lo,hi)`, `src`, and `dst`; per-producer atomic fence acknowledgements; and atomic `fence_gen`. `src/server.h:3382-3399`

### Client-LB mailbox state

Every IO-capable slot has a `tmMigMailbox` containing a mutex-protected destination `inbox`, atomic exact `inbox_n`, notifier, atomic `req_pending` and packed `req_data`, owner-only `migrating_out`, atomic `io_exiting`, and plain listener-exit/batch fields. `src/server.h:3096-3136`

Mailboxes are held in a static array indexed by IO identity; initialization allocates the lists/notifier and registers the notifier on the slot's event loop. `src/server.c:22757-22778`, `src/server.c:24603-24648`

### Per-node observability

Multi-node configurations (`tomokv-nodes > 1`) publish each node's live role counts through `INFO`:
`tomokv_node_<n>_io_live` is the node's live IO count (`tm_node_iolive[n]`) and
`tomokv_node_<n>_ex_live` is its live bucket-owning worker count (`tm_node_wlive[n]`); the block is
omitted single-node, where the global `io_threads_live` / `num_workers_live` already describe the
whole pool. `DEBUG TOMO-NODEOF <key>` reports the node index a key routes to through the real
`exIndexForKey` routing path (requires the debug command to be enabled at boot, e.g.
`--enable-debug-command local`). These are direct reads of controller state — no derived arithmetic —
so they are safe to poll while the controllers are actuating. `src/server.c:19897`, `src/debug.c:992`

## Flip controller

### Entry gates and sample scope

`tomoFlipController()` returns before sampling unless automatic mode is on, EX storage exists, at least one growth slot exists, `migration_active` is false by acquire load, no flip is active, and positive wall time elapsed. Static mode has a separate observation-only 4 Hz sampler for the two EX INFO saturations; it never writes controller state or actuates. `src/server.c:27706-27770`, `src/server.c:28368-28411`

At this quiescent entry the controller acquire-loads and checks `io_threads_live + num_workers_live == io_threads + num_workers`; a mismatch is only a rate-limited warning globally, although an active floor episode later refuses another move when either global or episode-local conservation fails. `src/server.c:25589-25629`, `src/server.c:26082-26099`

Single-node throughput uses `getNumCommands()`, which counts client-visible commands; multi-node throughput sums relaxed `ops_total` over the node's provisioned worker slots, and that fallback is explicitly worker-count-biased for scattered multi-key commands. `src/server.c:25652-25677`

The controller snapshots every node-owned IO/EX cumulative work counter even when its context currently has the opposite role, then includes only contexts currently live in the sampled role; the first visit establishes counter baselines and folds zero productive work. `src/server.c:25679-25718`, `src/server.c:25719-25764`

Node zero's main IO identity is excluded from the IO signal loop, which starts at slot 1, but is added back to the IO role count used by the capacity geometry. `src/server.c:25719-25758`, `src/server.c:26070-26080`

### Productive-work signal

IO owners accumulate plain 32-bit `tm_work_us` from `aeProcessEventsIO().work_us`. EX owners keep two plain 32-bit clocks: `tm_busy_us` retains first-pop-to-pass-end raw demand occupancy, while `tm_productive_us` is the direction-ratio numerator. The controller snapshots both with wrap-safe unsigned deltas; only the productive delta enters `u_ex`, while raw occupancy feeds demand/capacity consumers. `src/server.c:20866-20962`, `src/server.h:2647-2667`, `src/server.c:28508-28544`

The IO work interval comprises the IO-uring reap plus `beforeSleepIO` prefix and the post-poll/enter fired-callback tail; epoll wait is accounted separately, while IO-uring's indivisible enter cannot separate sleeping from taskwork. Each EX productive interval starts at the existing successful-pop phase marker and ends after its CDB result bytes and queue-retirement frontiers are release-published. Useful batch preparation and prefetch are inside; freeback/reclaim prefixes, PAUSE-only idle rounds, and lane/mask scans with no pop stay outside. The first aggregate reuses its raw stamp as the legacy pass-start stamp, and productive raw deltas are converted once per pass. `src/server.c:23453-24140`, `src/server.c:24180-24198`

For one node sample, the raw role fractions are:

```text
raw_io = sum(delta_io_work_us) / (wall_us * live_nonmain_io)
raw_ex = sum(delta_ex_productive_us) / (wall_us * live_ex)
```

Each value is capped above at `1.0`, then the stored role value is updated as `smooth += 0.25 * (raw - smooth)`. The busy-occupancy EX fraction is filtered identically into `ex_raw_u_smooth` for the CLI/SRV gate and large-pool capacity wall. INFO exposes the paired EWMAs as `tomokv_ex_sat_raw` and `tomokv_ex_sat_productive`, plus the cumulative `tomokv_ex_busy_us` and `tomokv_ex_productive_us` counters. `src/server.c:20904-20962`, `src/server.c:28674-28690`

On genuinely work-bound P1 GET, the aggregate contains useful execution nearly end to end, so productive and raw EX saturation are expected to remain close and the substitution is approximately identity. Wide sparse/scattered batches are expected to separate the values; exporting both is the sanity check rather than a workload-specific assertion.

The two productive direction operands are `u_io_work=io_work_u_smooth` and `u_ex_work=ex_work_u_smooth`, selected as `u_io/u_ex`; `io_sat=u_io` and the logged `ex_sat=u_ex`. The two demand operands are `u_io_occ=io_occ_smooth/100` and raw EX occupancy `ex_demand_sat=ex_raw_u_smooth`. IO reply backlog, EX queue depth, IO ring-stall time, CPU time, and command rate augment neither signal class; maximum EX queue depth remains part of idle detection. `src/server.c:28735-28815`

The directional signal is:

```text
ratio = max(u_io, 0.001) / max(u_ex, 0.001)
lr    = log(ratio)
```

A non-finite `lr` is replaced by zero; on non-idle, primed work samples, `lr_ewma` is seeded or updated with alpha `0.25`, and an actual EWMA step below `0.02` increments `lr_quiet_run`. `src/server.c:26027-26067`

The separate actuation-worth gate folds `max(u_io_occ,ex_demand_sat)` into `sat_smooth` with alpha `0.25` and sets `server_bound` when the result is at least `0.75`; a false gate clears the ordinary outside-band run and prevents a new climb. Both operands are occupancy-kind demand. Productive IO is excluded because its io_uring bracket cannot see enter-internal DEFER_TASKRUN completion work; productive EX is excluded because execution density determines direction rather than total demand. `src/server.c:28793-28811`, `src/server.c:30113-30118`

Instantaneous throughput is the operation delta divided by actual elapsed milliseconds.  A tick is idle only when `inst <= 0`, maximum EX queue EWMA depth is below `1/16`, and mean IO occupancy is zero; the first positive rate seeds the estimator, non-idle ticks update `mean` and `var` with alpha `0.25`, and `sigma = sqrt(max(var,1))`. `src/server.c:25786-25806`

The one-thread productive-ratio quantum and its floor are:

```text
ni      = live_nonmain_io + (node == 0 ? 1 : 0)
ne      = live_ex
gstep   = log((ni + 1) / ni) + (ne > 1 ? log(ne / (ne - 1)) : 1)

### Large-pool directional episodes (2026-08-15)

On configured per-node pools **larger than 16 threads** the one-thread-per-settle-window climb is
replaced by a geometric episode (`FLIP_EPISODE_POOL_CUTOFF`): each step covers half the remaining
signal-derived distance; the walk stops early when the starvation ratio reaches the balance band or
when the next step would cross the self-derived worker wall (`ceil(ex_live * ex_demand_sat * 1.5)`, using raw EX occupancy — never
observe the crater past the wall just to learn it is there). The keep/revert verdict is taken from a
**settled** measurement at the stopping split, never from mid-walk samples the walk itself depressed
(the standing law: a signal the actuator moves cannot police the actuator), and a reverted episode
re-arms only on a real rate (>3%) or ex-demand (>0.1) change. Pools of 16 or fewer threads take the
original path verbatim. Measured: a 64-thread pool that previously sawtoothed io 32↔63 forever at
~2.0M ops/s now converges io60/ex4 at 3.2–3.5M and holds. INFO:
`tomokv_flip_episode_early_stops`, `tomokv_flip_episode_wall_stops`.
gfloor  = gstep / 2
```

`ni` and `ne` are clamped to at least one before this calculation. `src/server.c:25060-25071`, `src/server.c:26070-26080`

### Frozen anchor and damped episode drops

Anchor capture requires the controller to be idle with no walkback, `abs(lr_ewma) < gfloor`, at least eight quiet-ratio ticks, at least five throughput-plateau ticks, and the current split to be the intended measured best. `src/server.c:24917-24923`, `src/server.c:24997-24998`, `src/server.c:26798-26810`, `src/server.c:26857-26876`

Capture freezes `lr_anchor`, `u_io`, `u_ex`, throughput, the exact IO/EX split, and `sqrt(lr_var)`; no running-mean fold changes `lr_anchor` afterward. `src/server.c:26859-26882`

Three settled change detectors can invalidate that anchor and re-arm an episode:

1. Floor exit requires eight settled ticks with `abs(lr_ewma) >= gfloor`. `src/server.c:26118-26127`, `src/server.c:26157-26158`
2. Fine anchor exit requires eight settled ticks beyond `2 * anchor_lr_sigma * 2^min(episode_revert_run,3)`. `src/server.c:26128-26145`, `src/server.c:26182-26183`
3. The so-called saturation-magnitude drop is actually a throughput test after a split-local rebase: `abs(mean-anchor_rate_cap) > max(2*sigma, 0.02*anchor_rate_cap) * 2^min(episode_revert_run,3)`; current U values are used only for finiteness checks and logging in this branch. `src/server.c:26147-26181`

A floor episode that returns to the same split increments `episode_revert_run`; successive same-split reverts therefore widen the fine-anchor and rate-drop allowances by powers of two up to eight.  A KEEP, floor drop, or fine-anchor drop resets that damping, while a rate-only drop does not. `src/server.c:25384-25425`, `src/server.c:26197-26211`

### Directional in-floor episode

Once a frozen anchor is fully settled inside the floor and no episode has been used, the controller starts `tmFlipSweepBegin()` and marks the entry split measured. `src/server.c:26857-26895`, `src/server.c:25199-25235`

The helper initially calculates a capacity-admitted range, but then clears that candidate set.  It chooses one direction from the sign of `lr_ewma` (`lr<0` means grow-back, otherwise grow-front), reverses only when the first neighbor is illegal, and initially admits just that neighbor. `src/server.c:25165-25203`

Candidate byte values mean absent `0`, unvisited `1`, measured `2`, and structurally blocked `3`. `src/server.c:24877-24880`

Each candidate uses the normal warmup and 16-tick measurement judge.  A significant gain extends the frontier by exactly one split in the same direction, while one non-significant near-noise result can spend the single coast allowance.  A candidate displaces the episode best only by the full significance band (except that the standing best may refresh its own higher measurement), so a within-noise neighbor does not win; final positioning returns to that ratified best. `src/server.c:26404-26503`, `src/server.c:26608-26677`

Eight refused attempts classify a candidate as structurally blocked.  Returning to the measured best has a retry bound equal to the width of the already-derived legal window, and a failed return does not promote the split where movement stopped. `src/server.c:25286-25348`, `src/server.c:25471-25497`, `src/server.c:27007-27018`

An active episode abandons on five idle or below-1000-rate ticks, a non-positive measurement, or a throughput change outside the per-transfer `3^k` load-shift bound; ratio-derived workload-change policing is intentionally absent while the episode is moving. `src/server.c:26246-26281`, `src/server.c:26503-26510`, `src/server.c:26566-26580`

### Ordinary directional trigger

When no climb or episode owns the node, direction is the sign of `lr_ewma`: positive requests grow-front and negative requests grow-back.  A request exists only outside `gfloor` and, when an anchor exists, outside `log(1.03)` around that anchor. `src/server.c:27106-27114`, `src/server.c:27164-27173`

At phase zero, `node_idle` or `mean<1000` pauses and clears the ordinary workload/episode latches; an already-active floor episode instead waits for its separate five-tick abandonment test. `src/server.c:26251-26264`, `src/server.c:26739-26763`

The same-direction Schmitt run must reach `8 << min(veto_run,3)`, producing requirements of 8, 16, 32, or 64 controller ticks.  After at least two net-zero climbs, a new signal within one current `gstep` of the stored `veto_lr` is suppressed as the same wave. `src/server.c:27175-27187`, `src/server.c:27232-27245`

A completed floor episode or a blocked final return clears the ordinary trigger until the episode's settled drop/re-arm path releases that ownership. `src/server.c:26282-26320`, `src/server.c:26836-26854`, `src/server.c:27222-27231`

Starting also requires the server-bound gate, direction-specific role headroom, eight quiet-ratio ticks, and five `idle_stable` ticks; `idle_stable` increments only while `abs(mean-inst) < min(2*sigma, 0.10*mean)`. `src/server.c:25808-25816`, `src/server.c:26765-26787`, `src/server.c:27262-27304`

Grow-front headroom is `w_live>1`.  Grow-back requires at least two non-main live IO contexts and at least one grown IO context above the base count. `src/server.c:25808-25816`

### k-jump, warmup, measure, and walkback

The actual phases are `0` for idle/decision or repositioning, `1` for warmup, `2` for measurement, and `3` for completing a multi-transfer step. `src/server.c:24767-24769`, `src/server.c:26339-26402`

`tmFlipStepMoves()` caps grow-front at `w_live-1` and grow-back at `min(grown_io_live, live_nonmain_io-1)`.  If `lr_ewma * direction > 0`, it selects `floor(abs(lr_ewma)/gstep)` clamped to `[1,cap]`; once the signal no longer agrees with the climb direction, it selects one move. `src/server.c:25530-25557`

Phase 3 serializes those `k` physical transfers through the single actuator gate and judges throughput only after the landed group.  A refusal after a landed prefix measures exactly that prefix; an abort after a prefix schedules the exact inverse count to restore the pre-step split. `src/server.c:26339-26402`

Phase 1 enters measurement immediately when `mean > best_rate + max(2*sigma, 0.02*best_rate)`.  Otherwise, `abs(lr_ewma) > 0.69` takes the fast path after five plateau ticks or 12 warm ticks; the near path requires five plateau and five reshard-quiet ticks, or reaches the 48-tick cap. `src/server.c:24917-24922`, `src/server.c:26404-26460`

Phase 2 samples 16 ticks and computes a direct rate from its `ref_ops/ref_ms` window.  A rate ratio beyond `3^k` relative to `best_rate` is treated as an offered-load change: the controller rebases at the current split and ends the climb instead of attributing the change to the role move. `src/server.c:24922`, `src/server.c:25009-25012`, `src/server.c:26499-26503`, `src/server.c:26539-26595`

Every measured rate above `best_rate` becomes the plain argmax, but continuing the climb requires improvement beyond `max(2*sigma, 0.02*best_rate)`.  One non-significant step may coast; the next miss walks back `best_dist` transfers to the measured argmax. `src/server.c:26512-26538`, `src/server.c:26679-26736`

Finishing at the climb's starting IO count increments `veto_run`; finishing at a different split resets it. `src/server.c:26822-26834`

### Grow-front: EX to IO

Single-node grow-front claims the highest live worker `num_workers_live-1`; multi-node grow-front claims `node*ex_per_node + tm_node_wlive[node]-1`.  Both require at least two live EX workers in scope. `src/server.c:23618-23625`, `src/server.c:27351-27358`

The worker path requires a dormant IO binding, current EX mode, growth headroom, and no active bucket migration.  It selects the worker's whole contiguous bucket range and destination `w-1`. `src/server.c:23572-23586`

After selecting the range, main release-decrements the global and per-node live EX counts and records an outstanding accounting transaction.  A zero-width range then skips resharding and directly publishes the IO target; a nonempty range sets `tm_mig_flip_action=2`, which defers target publication until reshard teardown. `src/server.c:23510-23615`, `src/server.c:16102-16140`

At the EX-to-IO checkpoint the owner refuses an active migration involving its shard, drains EX work until 50 ms of quiet, asserts that it owns no buckets or keys, changes its TLS identity, prepares the IO backend/listener, and release-stores `mode=IO`; listener entry failure retargets the context to EX. `src/server.c:23193-23328`, `src/server.c:23406-23420`

`tmFlipTick()` acquire-observes IO adoption, release-increments the IO live counts, optionally runs the derived one-shot client backfill, transfers key-LB EWMA state to the absorbing neighbor, marks relevel pending, and releases the flip claim.  If role entry or cutover failed, it rolls the outstanding EX accounting back and flags the controller's probe as aborted. `src/server.c:23689-23734`, `src/server.c:17088-17104`

### Grow-back: IO to EX

Single-node grow-back selects `io_threads_live-1`; multi-node grow-back scans all growth bindings and selects the numerically highest IO-mode slot whose EX binding belongs to the requested node. `src/server.c:23681-23686`, `src/server.c:27360-27374`

The arm path refuses an active bucket migration, a context without an EX binding, a non-IO mode, a busy/exiting mailbox, the absence of another non-main IO destination, or relaxed `pinned_nonmig != 0`. `src/server.c:23630-23663`

It release-stores grow-back state `DRAINING`, records target EX, phase zero, a 10-second deadline, and the EX slot, release-publishes the context, then posts an `IOEXIT` request and wakes the owner. `src/server.c:23664-23678`

The IO owner leaves the accept group, keeps enrolling migratable clients, and hands clients to currently least-loaded destinations, including same-pass in-flight placements.  Handoff waits for `dispatchid==flushid`, no pending replies, no pending/partial write, and IO-uring readiness when applicable. `src/server.c:23905-23915`, `src/server.c:24153-24165`, `src/server.c:24331-24429`

When all source clients and outgoing migrations are gone, the owner CASes `DRAINING -> COMMITTED` with success `acq_rel` and failure `acquire`; only the winning commit release-stores `target_mode=EX`. `src/server.c:24431-24487`

The IO-to-EX checkpoint requires that the listener has left and the client list is empty, expels or refuses a nonempty inbox, clears `io_exiting`, installs EX identity/state, drains stale work, and release-stores `mode=EX`. `src/server.c:23329-23414`

Main then publishes the paired accounting move with release RMWs: IO live `-1`, EX live `+1`, globally and per node. `src/server.c:23561-23570`, `src/server.c:23791-23802`

The revived worker is seeded from the upper half of worker `w-1`'s range when that source has at least two buckets; otherwise it remains empty but live.  After a successful seed cutover, key-LB state is kicked and deterministic relevel is requested. `src/server.c:23804-23854`

If phase zero passes the deadline, main CASes `DRAINING -> CANCEL_REQUESTED`, sends a cancel request, and waits in phase 3.  The owner rejoins the accept group and release-publishes `ROLLED_BACK`; main requires that state and IO mode before flagging an aborted probe and releasing the claim. `src/server.c:23738-23789`, `src/server.c:24336-24365`

The `COMMITTED` and `CANCEL_REQUESTED` CASes are mutually exclusive; after commit there is no second deadline while main waits for EX adoption. `src/server.c:23764-23779`, `src/server.c:24461-24487`

## Key-LB

### Accounting and sampling

Workers relaxed-increment `ops_total` by the number of popped queue entries before distinguishing ordinary commands, cross-shard sub-fakes, and sentinel entries; the helper is a relaxed load followed by relaxed store, not an atomic read-modify-write. `src/server.h:1618-1622`, `src/server.c:21955-21975`, `src/server.c:22042-22053`, `src/server.c:22096-22149`

After an ordinary `exExecFake`, only a fake with `argc>=2` increments its plain coarse group counter, relaxed-loads the fine-window selector, and conditionally increments a plain fine bucket counter.  Cross-shard sub-fakes take an earlier `continue`, so they affect `ops_total` but not the group/fine profile. `src/server.c:22144-22205`, `src/server.c:22208-22230`

The main thread reads the plain group/fine counters concurrently and forms unsigned deltas; only publication/reading of `lb_fine_win` is atomic and relaxed. `src/server.c:16357-16410`, `src/server.c:16899-16912`, `src/server.c:22224-22229`

When key-LB is off or EX state is absent, `reshardAutoTune()` disarms every fine window and frees only the four fine-controller allocations.  It does not free coarse arrays or reset the existing EWMAs, snapshots, streaks, peak, settle, or diffusion state. `src/server.c:16189-16219`, `src/server.c:16717-16720`, `src/server.c:16797-16808`

The enabled path returns while a migration or flip is active and acquire-loads `num_workers_live`, requiring at least two live workers. `src/server.c:16810-16825`

Slow alpha is `clamp(previous_mean / (4 * reshard_min_ops), 0.05, 0.25)` and fast alpha is `min(0.95, 2*slow_alpha)`, which is at most `0.5` because of the slow cap. `src/server.c:16832-16849`, `src/server.c:16915`

For each live worker, the sampled value is `relaxed_load(ops_total) - last_ops`; there is no elapsed-time division.  Slow/fast EWMAs fold this raw invocation delta, and the largest slow value is the hot candidate. `src/server.c:16882-16898`

Therefore `tomokv-key-lb` is compared with operations accumulated since the prior sampled invocation, not a normalized rate; the nominal 1-second cron only makes it approximately operations per second when no gate skips invocations. `src/server.c:2943-2947`, `src/server.c:16810-16818`, `src/server.c:16888-16895`, `src/server.c:16959`

The first overall sample seeds the load state and returns.  On later samples the controller advances its tick count, decrements each non-hot worker's streak by one, and services `tm_relevel_pending` before entering the statistical trigger. `src/server.c:16915-16927`

### Coarse/fine profile

Coarse EWMA/snapshot rows and fine EWMA/snapshot/group/warm rows are allocated lazily; coarse allocation failure leaves uniform-density planning, while fine state is committed only if all four fine allocations succeed. `src/server.c:16851-16880`

`migFineTick()` first folds a previously armed fine window, then finds each live worker's hottest owned coarse group.  It arms a group only when `top >= max(4 * group_sum / number_of_groups, 0.05 * group_sum)`. `src/server.c:16348-16385`

An armed incumbent group is retained when it remains above that bar and a challenger is below `1.25 * incumbent`; changing/disarming the window uses a relaxed store, refreshes raw snapshots, zeros its fine EWMA row, and sets the warm flag so the next fold seeds rather than blends. `src/server.c:16386-16410`

### Outlier trigger and planner

After priming, the controller computes global slow/fast means and population variances over all live worker slots, not separate per-node distributions. `src/server.c:16824-16825`, `src/server.c:16851-16898`, `src/server.c:16934-16947`

With `W` live workers, `k = min(2, 0.8*sqrt(W-1))`; each fire bar is `mean + max(k*sqrt(variance/W), 0.25*mean)`, using the corresponding slow or fast distribution, and the slow release bar lies halfway from mean to the slow fire bar. `src/server.c:16929-16955`

If `mean < reshard_min_ops`, the controller clears only peak/settle and returns without clearing the hot streak.  If `hot <= release_bar`, it clears peak/settle, decrements the hot streak once, invokes diffusion, and returns; values inside `(release_bar, hot_bar]` preserve the hot streak. `src/server.c:16956-16972`

The outlier must be strictly above both slow and fast fire bars, must pass the `hot <= 0.85*previous_peak` progress condition when a previous peak exists, and must sustain for `K=max(3,ceil(1/alpha))`; because alpha is at most `0.25`, actual `K` is at least four. `src/server.c:16515-16520`, `src/server.c:16973-16997`

Reaching `K` consumes the streak before endpoint/planning checks.  The destination is the cooler adjacent live worker in the same logical node and must be strictly below the global mean. `src/server.c:16985-17015`

`migPlanChunk()` trusts the hot worker's measured coarse profile only when its owned-group sum is at least half `Lh`; otherwise it assumes uniform density.  A warmed overlapping fine group is rescaled to its coarse group rate, and other buckets in a group remain uniform. `src/server.c:16302-16325`, `src/server.c:16467-16499`

The planner scans inward from the shared boundary, never taking the source's last bucket, targets moved load `(Lh-Lc)/2`, and selects the prefix or suffix minimizing `max(Lh-moved,Lc+moved)`. `src/server.c:16451-16508`

It requires predicted peak improvement of at least `0.25*(hot_bar-mean)`.  If the fine plan fails, a coarse-only shadow plan distinguishes a fine-resolution veto from a refusal that group resolution would also produce; the code does not identify an individual key. `src/server.c:16509-16512`, `src/server.c:17017-17066`

A successful right-neighbor plan moves a suffix and a successful left-neighbor plan moves a prefix, then calls `reshardArm()` and `reshardBeginCutover()`, records the previous peak, and sets settle to `(int)(1/alpha)+1`. `src/server.c:17068-17085`

### Relevel and diffusion paths

`tm_relevel_pending` preempts the statistical trigger.  Relevel counts exact table ownership per node, compares each boundary with an even target, tolerates deviations from `-63` through `+63`, keeps at least one bucket on the source, arms at most one range per tick, and clears the pending flag when no arm succeeds. `src/server.c:16639-16706`, `src/server.c:16925-16927`

Diffusion runs from the balanced branch or when no sufficiently cool outlier neighbor exists.  It chooses the steepest same-node adjacent pair satisfying `difference > 0.25*global_mean` and `higher > 0.35*global_mean`, sustains that boundary for `K`, and uses the uniform chunk formula `(Lh-Lc)/(2*Lh) * range_width`, floored at 16 buckets and capped near half the source. `src/server.c:16720-16765`, `src/server.c:16960-16966`, `src/server.c:17013-17015`

Neither relevel nor diffusion invokes the fine planner or its hot-key veto. `src/server.c:16646-16692`, `src/server.c:16745-16764`, `src/server.c:17017-17066`

### Shared bucket cutover protocol

`reshardArm()` serializes publishers with `atomic_exchange(mig_arm_lock,1,acq_rel)`, acquire-checks flush and migration gates, rejects a resize conflict, and validates that source and destination are adjacent and that `[lo,hi)` is a boundary-aligned subset wholly owned by the source.  It refuses to empty the source unless a role flip is active. `src/server.c:15525-15592`

The arm also rejects different physical DB pointers, so successful automatic moves change ownership inside one shared physical kvstore rather than copying keys. `src/server.c:15593-15604`

Arm publication writes plain range/endpoints, release-stores `MIG_COPYING`, release-increments generation and arm sequence, then release-stores `migration_active=1` last. `src/server.c:15606-15622`

`reshardBeginCutover()` CAS-arms the main-thread coordinator from `CO_IDLE` to `CO_WAIT_CONVERGE`; the main before-sleep path drives the state machine rather than creating a detached coordinator. `src/server.c:16147-16181`, `src/server.c:4438-4448`

The coordinator closes atomic admission, waits for atomic lifecycle references, clears fence acknowledgements, advances `fence_gen`, and release-publishes `MIG_DRAINING`.  Commands whose key specification intersects the migrating range are then parked before fake-ring admission. `src/server.c:15865-15950`, `src/server.c:8329-8336`, `src/server.c:15674-15711`

Every live producer must push a generation-tagged drain sentinel and the source worker must execute it before release-storing that producer's acknowledgement; a non-live producer instead proves `retired==tail`, and the coordinator acquire-loads those proofs. `src/server.c:15626-15641`, `src/server.c:15990-16009`, `src/server.c:22096-22105`

After all proofs, main writes the ordinary bucket-table bytes and range end, release-stores `MIG_FLIPPED`, advances generation, publishes `MIG_DONE`, and waits for three destination loop-heartbeat advances before release-storing `migration_active=0` last. `src/server.c:16047-16119`

Either fence timeout aborts without changing ownership, but the common teardown still relaxed-increments `reshard_done_seq`. `src/server.c:15905-15927`, `src/server.c:16011-16040`, `src/server.c:16120-16127`

## Client-LB

### Signal and continuous trigger

Each IO identity's plain `busy_ewma_q4` is an events-per-event-loop-pass measure.  Every `ioSlice()` updates it as `B += (((events << 4) - B) >> 3)`, and `tmIoThreadBusy()` returns the raw Q4 integer without dividing by 16. `src/server.c:649-669`, `src/server.c:23086-23142`, `src/server.c:23947-23952`

Connection load is the racy `listLength(server.clients[id])`; the main thread also reads `busy_ewma_q4` without atomic synchronization, so both inputs are heuristics rather than synchronized snapshots. `src/server.c:23937-23952`

Eligible IO destinations start at id 1, excluding main, and must have a context whose mode acquire-loads as IO and whose `io_exiting` relaxed-load is false. `src/server.c:23918-23934`

For each logical node on each cron invocation, the continuous trigger does the following:

1. It returns globally when `tm_client_lb` is false, gathers live IO ids, filters source-side measurement to the current node, and skips a node with fewer than two measured IO ids. `src/server.c:24030-24042`
2. It sums raw Q4 busy and connection counts, skips when `total_connections < n`, and uses busy values only when `total_busy > n`; otherwise it uses connection counts. `src/server.c:24043-24050`
3. It selects the first strict maximum.  When `maximum <= 1.25*mean`, it resets only that selected id's streak and stops processing the node. `src/server.c:24051-24056`
4. It increments that id's streak and proceeds when the value reaches three, resetting it immediately before later feasibility checks. `src/server.c:24056-24059`
5. It requires at least two current source connections.  Busy mode estimates `int((hot-mean)/(hot/nc))`; count mode uses `int(hot-mean)`; it then integer-divides by two, caps at `max(1,nc/3)`, rejects zero, and leaves at least one source connection. `src/server.c:24059-24071`
6. It chooses the globally least-loaded eligible IO destination by connection count, excluding the source, then rejects a busy source mailbox, nonempty outgoing list, or exiting source before release-publishing one request. `src/server.c:24072-24083`, `src/server.c:24106-24118`

The three-tick streak is not consecutive per source: streaks belonging to non-current maxima are not reset, and disabled/skipped invocations do not clear the static streak array. `src/server.c:24029-24056`

Integer damping happens after truncation, so a computed excess of one becomes zero at `count /= 2`. `src/server.c:24059-24071`

The trigger does not identify a hot connection; the source walks its client list and selects the first requested number that satisfy migratability. `src/server.c:24318-24330`

### Request publication and handoff

A request packs count in bits 32-63, `destination+1` in bits 16-31, `then_ex` in bit 8, and kind in bits 0-7.  The publisher relaxed-stores `req_data` and then release-stores `req_pending=1`; the source acquire-loads pending, relaxed-loads the payload, and release-clears pending. `src/server.c:22761-22778`, `src/server.c:24310-24317`

This edge prevents mixed request fields but is not a CAS claim or a queue: two publishers may both observe no pending request and overwrite the packed request. `src/server.h:3112-3118`, `src/server.c:22761-22778`

A client is migratable only when it has a connection, is not cutover/admission parked, uses the TCP connection type, has none of the enumerated closing/protected/transaction/blocking/pubsub/replication/tracking/debug/internal flags, has no watched keys, and has no subscription dictionaries. `src/server.c:23875-23902`

Starting migration sets `CLIENT_MIGRATING`, pauses input through the active backend, and appends the client to owner-only `migrating_out`. `src/server.c:24121-24129`

Handoff waits for exact quiescence: `dispatchid==flushid`, no pending replies, no `CLIENT_PENDING_WRITE`, `sentlen==0`, and IO-uring migration readiness when attached. `src/server.c:23905-23915`

For a normal rebalance, the latched destination remains fixed while valid; if it becomes invalid, the source falls back to the globally least-loaded eligible IO owner, and with no fallback it aborts and resumes the client. `src/server.c:24381-24429`

The source unbinds the connection, removes the client from its list/index, assigns `c->tid=destination`, appends it under the destination inbox mutex, release-updates `inbox_n`, and wakes the destination. `src/server.c:24227-24259`

The destination acquire-checks `inbox_n`, pops under the mutex, release-updates the count, rebinds the connection to its event loop, links the client into its list/index, clears `CLIENT_MIGRATING`, and resumes the selected backend. `src/server.c:24539-24582`, `src/networking.c:103-119`

Between source removal and destination linking, an inbox client appears in no `server.clients[]` list and is temporarily absent from connection-load samples. `src/server.c:24235-24259`, `src/server.c:24539-24582`

### Flip-time one-shot backfill

After grow-front publishes the new IO role, it calls `tmRebalanceOntoNewIo(new_id)` only when derived `tm_flip_rebalance` is true. `src/server.c:23705-23717`

The one-shot path filters sources to the new IO identity's logical node, requires at least two IO identities and at least one connection per identity in aggregate, and selects busy versus connection-count mode with the same `total_busy > n` rule. `src/server.c:23964-23983`

For every non-new, over-target source with at least two connections and an idle migration mailbox, busy mode estimates `(busy-busy_target)/(busy/nc)` while count mode uses `nc-floor(total_connections/n)`; it clamps the request to retain one source connection and posts a fixed-destination request to the new IO identity. `src/server.c:23983-24020`

This backfill has no half-excess damping and is a one-shot completion action; later continuous correction, when enabled, comes through `tmClientBalanceCron()`. `src/server.c:23705-23717`, `src/server.c:23964-24020`, `src/server.c:24030-24083`

## Cross-mechanism invariants and interactions

- A flip claim is process-global and `migration_active` is process-global, so node-local controllers decide independently but all role conversions and bucket migrations serialize physically. `src/server.c:116-150`, `src/server.c:25570-25574`, `src/server.c:27337-27343`
- Grow-front leaves at least one EX worker; grow-back consumes only grown IO bindings and leaves another non-main IO destination for client evacuation. `src/server.c:25541-25557`, `src/server.c:25808-25816`
- Grow-front delists EX before its bucket migration and completes or rolls back the paired accounting transaction; grow-back publishes IO-minus/EX-plus together only after EX adoption. `src/server.c:23510-23570`, `src/server.c:23689-23734`, `src/server.c:23791-23802`
- EX-to-IO adoption requires zero owned buckets/keys, while IO-to-EX adoption requires the listener gone, zero owned clients, and an empty or expellable inbox. `src/server.c:23223-23328`, `src/server.c:23329-23414`
- Key-LB returns while a flip is active, and the flip controller returns while key migration is active; `reshardArm()` supplies the final common serialization and range-validity gate. `src/server.c:16810-16818`, `src/server.c:25570-25574`, `src/server.c:15553-15592`
- A completed role move marks bucket relevel pending, but `tomokv-key-lb=0` returns before servicing that flag, so disabling key-LB also disables the deterministic post-flip relevel pass. `src/server.c:16797-16808`, `src/server.c:16925-16927`, `src/server.c:23713-23717`, `src/server.c:23851-23852`
- Grow-back evacuation and continuous client-LB share `tmMigMailbox`, quiescence, handoff, and inbox adoption; the client-LB knob does not disable that infrastructure because grow-back still requires it. `src/server.h:3096-3136`, `src/server.c:23875-24582`

## Comment/code discrepancies

These are implementation discrepancies, not alternative behavior:

1. The config comments describe selectable flip-signal modes, but no such config is created and the controller hardcodes productive ratio with `wsig=0`. `src/config.c:3220-3242`, `src/server.c:25014-25016`, `src/server.c:25631-25641`
2. The load-balancing config header says each lever is separately switchable, but flip-time backfill has no knob and is derived from automatic thread mode. `src/config.c:3255-3261`, `src/config.c:3304-3310`, `src/server.c:5621-5625`
3. The flip preamble describes busy-percent/PID behavior, no fixed operating point, and exponential probe backoff; the code uses productive work, target ratio `1`, fixed saturation/band/timing constants, and explicitly states that old backoff/convergence members were deleted and their behaviors are not implemented. `src/server.c:24682-24688`, `src/server.c:24745-24774`, `src/server.c:24917-25012`, `src/server.c:27106-27114`
4. Several nearby comments describe backlog-augmented `io_sat/ex_sat`; the direction assignment is bare capped productive U on both sides, `q_io` is observational, EX depth affects only idle detection/observability, and IO zero-event plus raw EX occupancy are isolated to demand/capacity decisions. `src/server.c:28735-28815`
5. Comments describe an exhaustive in-floor sweep plus both neighbors; the implementation clears the admitted set and starts a single directional, gain-extended episode. `src/server.c:24925-24930`, `src/server.c:25140-25203`
6. `FLIP_SUSTAIN` is defined twice with the same value `8`. `src/server.c:24990-24995`, `src/server.c:25005-25008`
7. The key-LB cron comment names deleted `tomokv-reshard-auto`; the registered knob is `tomokv-key-lb`. `src/server.c:2943-2946`, `src/config.c:3292`
8. The key-LB field/config comments call the threshold operations per second and say zero means no machinery/allocations; code compares an unnormalized per-invocation delta, cron still calls the function, embedded worker counters still execute, and the off path frees only fine controller allocations. `src/config.c:3292`, `src/server.h:4121-4123`, `src/server.c:16797-16808`, `src/server.c:16888-16895`, `src/server.c:16959`, `src/server.c:22214-22230`
9. The coarse-profile comment says group counting is unconditional, but it occurs only for an ordinary fake with `argc>=2` after the cross-shard early branch. `src/server.c:16210-16214`, `src/server.c:22144-22205`, `src/server.c:22224-22230`
10. The reshard entry comment says it spawns a detached coordinator; the function only CAS-arms a state machine driven from main-thread `beforeSleep`. `src/server.c:16147-16155`, `src/server.c:4438-4448`
11. Continuous client-LB comments say balancing is within-node, but only source measurement is node-filtered; destination choice and fallback gather globally, so the handoff can cross logical nodes. `src/server.c:24023-24028`, `src/server.c:24037-24042`, `src/server.c:24072-24083`, `src/server.c:24106-24118`, `src/server.c:24410-24429`
12. The continuous-client header says it is gated by `tm_flip_rebalance`, but its first branch checks the independent `tm_client_lb` field. `src/server.c:24023-24034`
13. Grow-back comments/logs say round-robin or even connection evacuation; the implemented IO-exit path chooses least current connection count plus same-pass in-flight placements. `src/server.c:23630-23636`, `src/server.c:23672-23677`, `src/server.c:24106-24118`, `src/server.c:24403-24409`
14. “Sustain 3 ticks” is not a consecutive-source invariant because streaks for other hot ids are retained. `src/server.c:24025-24028`, `src/server.c:24051-24059`
15. `reshard_done_seq` is described as completed bucket moves, but abort teardown increments it without changing ownership. `src/server.h:3279-3282`, `src/server.c:15905-15927`, `src/server.c:16011-16040`, `src/server.c:16120-16127`
16. A cutover comment says every bucket-table reader is gated by a phase/generation acquire, but the direct routing helpers read the table plainly; the normal dispatch caller reaches the phase-acquire hold only after a relaxed `migration_active` test. `src/server.c:16051-16057`, `src/server.c:8334-8336`, `src/server.c:9539-9555`
17. The `tm_flip_rebalance` field comment says default `1`, but initialization derives it from thread mode, making it false in static mode. `src/server.h:3304`, `src/server.c:5620-5625`
18. The grow-front backfill comment says skipped sources are re-picked on the controller's next tick, but the only call is the one-shot grow-front completion call; any later balancing belongs to the independent continuous controller. `src/server.c:23705-23717`, `src/server.c:23964-24020`, `src/server.c:24030-24083`
19. Key-LB header comments say group counters are summed across workers and groups are moved, but the main planner reads the hot worker's row and can choose an arbitrary bucket prefix/suffix rather than a 64-bucket multiple. `src/server.h:1572-1580`, `src/server.c:16467-16512`
20. Key-LB observability comments say every controller exit gate is counted, but active migration, active flip, too few workers, initial priming, relevel preemption, and arm failure return without a dedicated gate counter; relevel/diffusion arms also do not increment the statistical `fire` counter. `src/server.c:16768-16825`, `src/server.c:16915-16927`, `src/server.c:17068-17085`, `src/server.c:17145-17163`
21. The convergence comment describes detecting a genuinely worse new imbalance, but `mig_peak_pre` is a scalar with no worker/boundary identity and the implemented progress gate only compares the current hot value with `0.85*mig_peak_pre`. `src/server.c:16195-16202`, `src/server.c:16957-16980`
22. Connection-migration comments equate its fence with the stateful-command ring fence, but migration additionally requires empty reply state, no pending/partial write, and IO-uring readiness. `src/server.h:3082-3088`, `src/server.c:8210-8218`, `src/server.c:23905-23915`
23. The single-node symmetric-pool log claims reachability down to total IO count one, but the floor-episode code treats node-zero `io1 -> io2` as non-reversible and grow-back requires another non-main IO receiver. `src/server.c:5825-5830`, `src/server.c:25154-25160`, `src/server.c:23650-23652`
24. `io_threads_live` is commented as describing a dense global IO-slot prefix, but multi-node grow-front can make growth slots globally sparse; the multi-node grow-back code consequently scans all growth bindings instead of indexing by that count. `src/server.h:3246-3247`, `src/server.c:22887-22896`, `src/server.c:27351-27374`
25. A saturation example labels `0.93` client-bound, but the implemented smoothed server-bound threshold is `0.75`. `src/server.c:24941-24966`, `src/server.c:25995-26019`

## File/line map

| Area | Primary implementation |
| --- | --- |
| Configuration and derived gates | `src/config.c:3212-3311`, `src/server.c:5614-5625`, `src/server.c:5717-5839` |
| Cron scheduling | `src/server.c:2943-2955` |
| Thread roles and `polyThreadCtx` | `src/server.h:2498-2525`, `src/server.h:3042-3080` |
| Server flip/live-count fields | `src/server.h:3220-3305`, `src/server.h:3362-3399` |
| Flip claim protocol | `src/server.c:90-150` |
| Role checkpoints | `src/server.c:23193-23420` |
| Live accounting and grow-front/back actuators | `src/server.c:23510-23855`, `src/server.c:27351-27374` |
| Connection signals, placement, continuous LB, and backfill | `src/server.c:23875-24118` |
| Connection mailbox service and handoff | `src/server.c:24121-24582` |
| IO productive-work accounting bracket | `src/ae.c:544-738`, `src/server.c:23086-23143` |
| EX productive/raw accounting brackets | `src/server.c:23453-24198`, `src/server.h:2647-2667` |
| Flip controller state/constants/helpers | `src/server.c:24761-25568` |
| Flip sampling, anchor, episode, and hill climb | `src/server.c:25570-27327` |
| Key-LB state and profile planner | `src/server.c:16189-16520` |
| Relevel and diffusion | `src/server.c:16639-16765` |
| `reshardAutoTune()` | `src/server.c:16768-17104` |
| Bucket routing/migration structures | `src/server.h:1560-1598`, `src/server.h:3377-3399` |
| Bucket arm, drain fence, and cutover | `src/server.c:15525-16181` |

## Mechanisms

- [Flip signal](mechanisms/algorithms/flip-signal.md)
- [Flip trigger and actuation](mechanisms/algorithms/flip-trigger-and-actuation.md)
- [Flip anchor and episode](mechanisms/algorithms/flip-anchor-and-episode.md)
- [Flip drops](mechanisms/algorithms/flip-drops.md)
- [Flip judge](mechanisms/algorithms/flip-judge.md)
- [Key load balancing](mechanisms/algorithms/key-lb.md)
- [Client load balancing](mechanisms/algorithms/client-lb.md)
- [Owner lock](mechanisms/communication/owner-lock.md)
