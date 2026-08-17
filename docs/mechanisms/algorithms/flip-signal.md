# Flip signal: the backend-faithful direction ratio `lr = ln(u_io/u_ex)`

The single direction signal for the auto-flip controller since 2026-08-10. Every direction-coordinate
consumer (the trigger floor, anchor deadzone, per-tick quiet test, k-jump distance, balance stop, and
anchor drops) is defined on this one quantity. The separate CLI/SRV classifier uses two occupancy-kind
demand operands. All code is in `tomoFlipController()` and its helpers in
`src/server.c`; the signal fields live in `flipCtlState` (`src/server.c:24761-24911`).

This document treats the code as authoritative. Where the source contradicts the task framing or
`loadbalance-flip.md`, the code reading is given and the divergence is called out under
[Notes where code differs from the brief](#notes-where-code-differs-from-the-brief).

## What is measured, and from which counters

EX direction is always productive execution density. IO direction selects the measurement source
that is faithful for the immutable network backend; the resulting operands are capped in `[0,1]`:

```text
u_io_work = EWMA( sum(delta IO tm_work_us) / (wall_us * live_nonmain_io) ), capped at 1
cpu_sat   =       sum(delta IO tm_busy_us) / (wall_us * live_nonmain_io)
u_io_occ  = EWMA(1 - zero-event-episode_us / wall_us)
u_io      = server.io_uring != 0 ? min(cpu_sat, 1) * u_io_occ : u_io_work
u_ex_work = EWMA( sum(delta EX tm_productive_us) / (wall_us * live_ex)   ), capped at 1
u_ex      = u_ex_work
r         = u_io / u_ex
```

- `u_io_work` is fed by the IO owner's `tmIoSignal.tm_work_us` (`unsigned int`, wrap-safe cumulative),
  which brackets the io_uring CQ reap + `beforeSleepIO` prefix and the post-poll/enter fired-callback
  tail. Poll/enter sleep is *outside* the bracket, so spinning on an empty socket set cannot raise
  `u_io_work`. Accumulated in `ioSlice()` from `aeProcessEventsIO`'s
  `accounting.work_us`; the bracket itself is `src/ae.c:560-571` (prefix) and `src/ae.c:704-737`
  (tail).
- `cpu_sat` is the unsmoothed per-tick fraction from the IO owner's `tm_busy_us` thread-CPU clock.
  It is capped at `1.0` when selected for uring, then multiplied by `u_io_occ` so empty-ring spin
  cannot masquerade as useful IO pressure. Under epoll it remains an observable only.
- `u_ex_work` is fed by the worker's `exThread.tm_productive_us` (`unsigned int`, wrap-safe). Each
  non-empty aggregate is timed from the successful-pop phase marker through CDB-ready and
  queue-retirement publication. Useful batch preparation/prefetch are inside; empty scans,
  freeback/reclaim prefixes, and idle PAUSE rounds are outside. The first aggregate reuses its
  raw stamp as the legacy pass start, and the accumulated raw ticks are converted once per pass
  (`src/server.c:23911-24140`, `src/server.c:24180-24198`).
- `exThread.tm_busy_us` retains first-pop → pass-end occupancy. It is sampled and smoothed beside
  the productive clock as raw EX demand for the CLI/SRV classifier and large-pool worker wall, and
  is also exported for A/B and INFO. It never enters `lr`.

The two **demand operands** are occupancy fractions, also in `[0,1]`:

```text
u_io_occ      = io_occ_smooth / 100
ex_demand_sat = ex_raw_u_smooth
demand_total  = max(u_io_occ, ex_demand_sat)
```

- `u_io_occ` is the complement of IO zero-event time. `ioSlice()` opens an idle episode when
  `ne == 0`, folds a still-open episode every 16 ms so an always-idle thread continues to accrue
  idle time, and closes it when work returns. The controller converts each live owner's wrap-safe
  `tm_idle_us` delta to occupied percent, averages the node, and applies the existing integer EWMA.
  This remains faithful under both backends: an idle uring busy-poller still reports zero events and
  accrues idle time, while a loaded owner does not.
- `ex_demand_sat` is the capped double EWMA of first-pop → pass-end `tm_busy_us` divided by the
  same node wall/live-worker denominator. It is also the large-pool worker-capacity observation.

The productive IO bracket is not a complete direction measure under io_uring. With
`IORING_SETUP_DEFER_TASKRUN`, completion taskwork can execute inside the indivisible
`io_uring_enter` span outside `u_io_work`. Fliptrace measured the following productive-bracket
coverage relative to scheduled IO CPU:

| workload | backend | `u_io_work / cpu_sat` coverage |
| --- | --- | ---: |
| p1 GET | io_uring | about 12% (`12.1% / 100.3%`) |
| MGET8 | io_uring | about 88% |
| p1 GET | epoll | about 96% |

The missing uring share is enter-internal taskwork; MGET8 retains more visible userspace
parse/reply work than p1. Consequently epoll keeps `u_io_work`, while uring selects
`min(cpu_sat,1) * u_io_occ`. This is a measurement-source branch, not a policy branch: target,
anchor, band, floor, demand gate, hysteresis, jump, and judge consume the selected `u_io` without
backend-specific rules.

These cumulative work/occupancy/CPU counters are owner-written plain integers and read racily by the
4 Hz controller with unsigned deltas — no atomic synchronization.

## Per-tick accumulation (`tomoFlipController`, `src/server.c:25570-26080`)

### Entry gates and wall time

The function returns before sampling unless (`src/server.c:25570-25587`):

- `server.thread_auto` is set and `server.exThreads` exists;
- `server.tm_ngrow_io > 0` (there is flip headroom);
- `server.migration_active` is false (acquire load);
- `tmFlipActive()` is false (no flip in flight);
- positive wall time elapsed since the last tick (`wall_ms > 0`).

Cron cadence is `run_with_period(250) tomoFlipController()` — ~4 Hz (`src/server.c:2955`).

### Per-node wall and the `fc_prev_*` delta arrays

Static, function-scoped snapshot arrays hold each node's previous cumulative counter values
(`src/server.c:25577-25583`):

| Array | Type | Feeds |
| --- | --- | --- |
| `fc_prev_io_work_us[TM_MAXNODE][TOMO_IO_THREADS_MAX+1]` | `uint32_t` | epoll `u_io` source and trace numerator |
| `fc_prev_io_busy_us[TM_MAXNODE][TOMO_IO_THREADS_MAX+1]` | `uint32_t` | uring `u_io` source and trace numerator |
| `fc_prev_ex_work_us[TM_MAXNODE][TOMO_EX_THREADS_MAX+1]` | `uint32_t` | `u_ex` numerator |
| `fc_prev_ex_raw_us[TM_MAXNODE][TOMO_EX_THREADS_MAX+1]` | `uint32_t` | raw EX demand/capacity occupancy |
| `fc_prev_io_idle_us` | `uint32_t` | `u_io_occ` demand occupancy |
| `fc_prev_io_wait_us` / `fc_prev_io_stall_us` | `uint32_t` | diagnostics |
| `fc_prev_ex_idle_us` | `uint32_t` | legacy EX occupancy |
| `fc_prev_busy_wall[TM_MAXNODE]` | `mstime_t` | this node's wall span |

Because a node body may be skipped when an earlier node starts a flip, each node keeps its **own**
wall span rather than the controller-entry `wall_ms` (`src/server.c:25645-25650`):

```text
work_sample_primed = (fc_prev_busy_wall[node] != 0)
node_wall_ms       = work_sample_primed ? (now - fc_prev_busy_wall[node]) : wall_ms
fc_prev_busy_wall[node] = now
```

The delta idiom is a wrap-safe unsigned subtract that advances the baseline **for every node-owned
slot even while it is serving the opposite role**, so a later role re-entry does not inherit stale
work:

```c
uint32_t cwork = tm_io_sig[t].tm_work_us;
uint32_t dwork = cwork - fc_prev_io_work_us[node][t];   /* unsigned wrap-safe */
fc_prev_io_work_us[node][t] = cwork;
```

`dwork` and the matching `tm_busy_us` CPU delta are added only for slots currently live in the IO
role; the productive `db` enters `ex_work_delta_sum` only for slots in EX mode, while the matching
raw delta enters `ex_raw_delta_sum`. `tmIoBusyBegin()` separately re-baselines the producer's thread
CPU clock at each IO role entry, preventing CPU from the previous EX episode from entering
`cpu_sat`. Node 0's IO slot 0 (main) is excluded from the IO loop, which starts at `t = 1`.

**First-visit fold-out.** On the first visit to a node (`!work_sample_primed`) the deltas reach back
to process start, so the productive, raw EX, and CPU sums are zeroed and no such sample is published
that tick.

### Raw fractions, the cap, and the smoothing EWMA

`io_occ_cnt` counts the live non-main IO owners; `w_live` counts the live EX workers.

```text
io_work_u_mean = io_work_delta_sum / (node_wall_ms * 1000 * io_occ_cnt)   (src/server.c:25778-25781)
cpu_sat        = io_cpu_delta_sum  / (node_wall_ms * 1000 * io_occ_cnt)
ex_work_u_mean = ex_work_delta_sum / (node_wall_ms * 1000 * w_live)       (src/server.c:25832-25834)
```

Each raw mean is **capped above at 1.0** before smoothing (`src/server.c:25782`, `src/server.c:25836`),
then folded into a **double-precision** EWMA at `FESC_ALPHA = 0.25` (`src/server.c:24917`):

```c
if (io_work_u_mean > 1.0) io_work_u_mean = 1.0;
fc->io_work_u_smooth += FESC_ALPHA * (io_work_u_mean - fc->io_work_u_smooth);   /* 25782-25783 */
...
if (ex_work_u_mean > 1.0) ex_work_u_mean = 1.0;
fc->ex_work_u_smooth += FESC_ALPHA * (ex_work_u_mean - fc->ex_work_u_smooth);   /* 25836-25837 */
```

`fc->io_work_u_smooth` and `fc->ex_work_u_smooth` are `double` (`src/server.c:24814-24815`). If a node
is skipped (`io_occ_cnt == 0` or not primed) the raw mean falls back to the current smoothed value, so
the EWMA holds rather than collapsing (`src/server.c:25778-25781`, `src/server.c:25832-25835`).

### The direction operands and the log-ratio

The direction operands are selected and re-capped. Only the IO measurement source branches on the
backend:

```c
double u_io_occ = (double)fc->io_occ_smooth / 100.0;
double u_io_work = fc->io_work_u_smooth;
double u_ex_work = fc->ex_work_u_smooth;
double cpu_sat = (double)io_cpu_delta_sum / (node_wall_ms * 1000.0 * io_occ_cnt);
double u_io = server.io_uring != 0
    ? fmin(cpu_sat, 1.0) * u_io_occ
    : u_io_work;
double u_ex = u_ex_work;
if (u_io > 1.0) u_io = 1.0;
if (u_ex > 1.0) u_ex = 1.0;
double io_sat = u_io;
double ex_dir_sat = u_ex;              /* nothing else augments the ratio */
```

The separate CLI/SRV gate names both occupancy-kind demand operands:

```c
double u_io_occ = (double)fc->io_occ_smooth / 100.0;
double ex_demand_sat = fc->ex_raw_u_smooth;
double demand_total = fmax(u_io_occ, ex_demand_sat);
```

`demand_total` feeds only the CLI/SRV classifier. `ex_demand_sat` also feeds the large-pool worker
wall and its failed-episode re-arm check. Under uring, the `u_io_occ` measurement is additionally an
idle-spin mask on the CPU direction source; the gate verdict and `ex_demand_sat` still have no path
into `ratio`, the balance band, or floor. Conversely, neither productive operand feeds
`demand_total`.

### CLI/SRV verdict hysteresis

`sat_smooth` is the `FESC_ALPHA` EWMA of `demand_total`. A tick at or above
`FLIP_BOUND_SAT = 0.75` is server-bound and resets `cli_run` to zero. A sub-threshold tick always
holds actuation (`out = 0`) and increments the per-node `cli_run`, capped at the existing
`FLIP_SUSTAIN`. While `cli_run < FLIP_SUSTAIN`, the low verdict is transient: the controller leaves
`lr_out_dir`, `lr_out_run`, the anchor, and episode state untouched, so the same walk can resume when
demand recovers. When `cli_run` reaches `FLIP_SUSTAIN`, the verdict is sustained client-bound and
the controller performs the previous CLI action: it holds and clears `lr_out_dir`/`lr_out_run`.

This distinction was added after the 2026-08-16 fliptrace showed a bimodal verdict: mean
`demand_total` was `0.918` on SRV ticks and `0.625` on CLI ticks. The low population included
post-move re-baseline rows such as `io=3 ex=4`, where `tot` fell from about `0.70` to `0.63` for a
few consecutive ticks. Those short dips are long enough to cross the EWMA threshold, but not long
enough to establish genuinely client-limited demand. Reusing `FLIP_SUSTAIN` (two EWMA time
constants) adds no new tuning constant; an idle/client-limited interval still reaches the same hard
reset. Fliptrace prints `cli_run=N`, allowing transient CLI rows (`N < FLIP_SUSTAIN`) to be
distinguished from the sustained verdict.

The directional signal floors **both** sides before dividing so the log is always finite
(`src/server.c:26035-26037`):

```c
double ratio = fmax(u_io, 1e-3) / fmax(u_ex, 1e-3);   /* bounds ratio to [1e-3, 1e3] */
double lr    = log(ratio);
if (!isfinite(lr)) lr = 0.0;                            /* belt and braces: never poison the EWMA */
```

Flooring both sides (not just the denominator) is deliberate: an idle tick drives `u` to 0, and
protecting only the denominator produced `log(0) = -inf → NaN`, which is absorbing and silently
disabled the actuator for the process lifetime (`src/server.c:26027-26034`).

### The signal EWMA and the quiet counter

`lr` is folded into `fc->lr_ewma` (`double`, `src/server.c:24832`) only on non-idle, work-primed
ticks (`src/server.c:26038-26068`):

- First loaded sample seeds it and sets `lr_init`, but leaves `anchor_n == 0` so a cold outside-floor
  boot can still climb (`src/server.c:26039-26043`).
- A poisoned `lr_ewma`/`lr_anchor` self-heals by re-seeding and unsetting the anchor
  (`src/server.c:26044-26053`).
- Normal update measures the step the EWMA **actually takes this tick** — compare before vs after,
  not against a stale `prev_tick` (`src/server.c:26062-26063`):

```c
double lr_before = fc->lr_ewma;
fc->lr_ewma += FESC_ALPHA * (lr - fc->lr_ewma);            /* alpha 0.25 */
if (fc->lr_init && fabs(fc->lr_ewma - lr_before) < FLIP_R_QUIET)   /* FLIP_R_QUIET = 0.02 */
    { if (fc->lr_quiet_run < 1000) fc->lr_quiet_run++; }
else fc->lr_quiet_run = 0;
```

`fc->lr_quiet_run` (`int`) is the "ratio holding still" counter that gates both anchor capture and a
climb START (see `flip-trigger-and-actuation.md`, `flip-anchor-and-episode.md`).

### Reverted-probe ownership and durable re-arm

The owner's thrash definition is deliberately narrow: **movement after stabilization under an
unchanged workload is the only thrash**. Exploration before stabilization is useful work; a probe
that finds and adopts a better split is useful work. A completed probe that returns to its entry
split is different: it measured that excursion and rejected it, so the episode owns the workload at
that config. Repeating the same measurement because `lr` wiggled spends migrations without gaining
knowledge.

The 2026-08-17 240-second MGET8/node-8 discrimination exposed that exact failure. Auto made 93 moves
in `[0,120]` and another 67 in `[120,240]` (4.2 moves/node/minute in minutes 3-4), remained scattered
at `[5,5,5,2,4,5,5,5]`, and delivered 1.595M steady-state against 1.844M at static io5/ex3
(-13.5%). The floor counters attributed the movement to 64 in-floor sweeps: 56 REVERTs and only 3
KEEPs, or approximately one sweep per node every 30 seconds forever. In contrast, p32 SET/node-2
ran two sweeps total, both REVERTed, then made no moves for more than 120 seconds and beat its static
reference by 7.1%. The useful initial-probe path already latched in that case; governance therefore
applies only after REVERT and does not gate initial probes or KEEP outcomes.

On a clean REVERT, `tmFlipSweepFinish()` preserves the settled sweep-entry
`floor_probe_entry_lr` as the owned signal level, increments `episode_revert_run` when the final
`io` still equals `revert_run_io`, and clears `episode_rearm_run`. Once the normal post-return settle
window ends, the re-arm counter advances only on consecutive loaded ticks satisfying:

```text
abs(lr_ewma - floor_probe_entry_lr) > live gstep
```

The required run deliberately mirrors the existing climb `veto_run` escalation:

```c
need = FLIP_SUSTAIN << min(episode_revert_run, 3);   /* 16, 32, 64 ticks after REVERT 1, 2, 3+ */
```

Any in-band or idle tick resets the countdown. Floor, fine-anchor, and rate-drop observations may
still invalidate their representational baselines, but they cannot release a same-config REVERT
episode before this owned-lr run completes. A real config change releases ownership immediately and
resets the same-config revert sequence. A KEEP also resets both governance counters, so a workload
where probing helps retains the prior re-probe behavior. No new cadence or threshold constant is
introduced: the distance is the existing live `gstep`, persistence is `FLIP_SUSTAIN`, and the capped
doubling is the existing veto-backoff shape.

Fliptrace exposes `owned`, `owned_lr`, `reverts`, and `rearm_countdown`. The countdown is the number
of additional consecutive departure ticks required; it is zero when ownership is inactive or has
already released.

### The idle test and the throughput estimator

A tick is idle only when all three hold (`src/server.c:25803`):

```text
node_idle = (inst <= 0) && (qd_max < 1/16) && (io_occ_mean == 0)
```

where `inst` is the instantaneous rate `(node_ops - ops_prev)*1000/(now - ops_prev_ms)`
(`src/server.c:25790-25791`), `qd_max` is the max EX queue-depth EWMA over the node's workers, and
`io_occ_mean` is the legacy IO occupancy. Idle ticks freeze `mean`/`var`; the first positive rate
seeds them; non-idle ticks fold at `FESC_ALPHA`; `sigma = sqrt(max(var,1))`
(`src/server.c:25804-25806`). This throughput estimator is the scale for the drops and the judge, not
part of `lr` itself.

## Per-role and per-signal noise estimators

On non-idle primed ticks the controller also maintains matched EWMA(mean, squared deviation)
estimators for `u_io`, `u_ex`, and `lr_ewma` (`src/server.c:24818-24819`, `src/server.c:24894`,
folded at `src/server.c:26225-26241`). `sqrt(lr_var)` snapshotted at anchor capture becomes
`anchor_lr_sigma`, the anchor band's sigma (see `flip-drops.md`). `u_io_var`/`u_ex_var` remain
maintained for observability only — their sigmas gate no drop, because the cap compresses them below
the box's ordinary drift (`src/server.c:25901-25904`).

## State variables (all in `flipCtlState`, one per node in `fctl[TM_MAXNODE]`)

| Field | Type | Meaning |
| --- | --- | --- |
| `io_work_u_smooth`, `ex_work_u_smooth` | `double` | capped productive-work EWMAs; epoll source for `u_io`, unconditional source for `u_ex` |
| `ex_raw_u_smooth` | `double` | identically filtered raw EX demand for the bound gate/capacity wall and INFO |
| `lr_ewma` | `double` | EWMA of `log(u_io/u_ex)`; the decision signal |
| `lr_init` | `int` | 1 once `lr_ewma` seeded from the first loaded sample |
| `lr_quiet_run` | `int` | consecutive ticks the EWMA step stayed `< FLIP_R_QUIET`; caps at 1000 |
| `lr_prev_tick` | `double` | stored, **not read** by the current controller (quietness uses the local `lr_before`) |
| `mean`, `var` | `double` | throughput EWMA + variance |
| `io_occ_smooth` | `int` | integer-EWMA zero-event IO occupancy; demand operand and uring idle-spin mask |
| `ex_occ_smooth` | `int` | legacy EX no-work occupancy diagnostic |
| `u_io_mean`/`u_io_var`, `u_ex_mean`/`u_ex_var` | `double` | per-role noise EWMAs (observability) |
| `lr_mean`, `lr_var` | `double` | settled-tick `lr` noise; `sqrt(lr_var)` frozen at capture |
| `sat_smooth` | `double` | EWMA of `max(u_io_occ,ex_raw_u_smooth)`; the server-bound gate input |
| `cli_run` | `int` | consecutive sub-threshold verdict ticks, capped at `FLIP_SUSTAIN` |
| `floor_probe_entry_lr` | `double` | settled sweep-entry `lr`; preserved as the owned level after a clean REVERT |
| `episode_revert_run`, `revert_run_io` | `int` | consecutive same-config REVERTs and their owned split |
| `episode_rearm_run` | `int` | consecutive ticks more than one live `gstep` from the owned level |

## Key constants

`FESC_ALPHA = 0.25` (`src/server.c:24917`), `FLIP_BOUND_SAT = 0.75`,
`FLIP_SUSTAIN = 8`, `FLIP_R_QUIET = 0.02` (`src/server.c:24997`), and
`FLIP_R_QUIET_N = 8` (`src/server.c:24998`). The bound-verdict counter deliberately reuses the same
`FLIP_SUSTAIN` as the Schmitt gate. The backend-faithful ratio is the only direction signal; the old
`tomokv-flip-signal` knob and `FLIP_SIG_*` modes were deleted 2026-08-10, and `wsig` is a compile-time
`const int 0` (`src/server.c:25014-25016`, `src/server.c:25635-25639`).

## Invariants

- `u_io, u_ex ∈ [0,1]` by construction (cap at raw-mean time and again at operand select); `ratio ∈
  [1e-3, 1e3]`; `lr` is always finite (NaN/inf replaced by 0). `src/server.c:25782`, `:25836`,
  `:25898-25900`, `:26035-26037`.
- Owner-written counters are advanced-baselined for **every** node-owned slot even in the opposite
  role, so a role transition never injects a work spike (`src/server.c:25687-25692`,
  `:25726-25741`).
- Direction policy and the demand verdict remain disjoint. Epoll uses `u_io_work`; uring uses
  `min(cpu_sat,1) * u_io_occ`; both divide by `u_ex_work`. `demand_total` remains
  `max(u_io_occ,ex_demand_sat)`, and neither that result nor `ex_demand_sat` reaches `r`.
- One field (`lr_ewma`) carries the signal for the anchor, the deadzone, the quiet test, the START
  gate, and the same-wave latch — deliberately, so it is structurally impossible to anchor one
  quantity while testing another for quietness (`src/server.c:24823-24833`).

## Notes where code differs from the brief

1. **Not integer-EWMA.** The task describes "the EXACT integer-EWMA math" for `u_io`/`u_ex`. In code
   the productive-work operands `io_work_u_smooth`/`ex_work_u_smooth` and `lr_ewma` are **`double`**
   EWMAs at `FESC_ALPHA = 0.25` (`src/server.c:25783`, `:25837`, `:26063`). The integer-truncated
   EWMA (`x += (int)(FESC_ALPHA*(mean - x))`) applies to the occupancy fields
   `io_occ_smooth`/`ex_occ_smooth`. `io_occ_smooth` feeds the CLI/SRV demand gate and, under uring,
   masks idle-spin CPU in `u_io`; `ex_occ_smooth` does not feed `lr`.
2. **Raw EX occupancy is actionable only as demand/capacity.** `tm_busy_us` and
   `ex_raw_u_smooth` feed `tomokv_ex_busy_us` / `tomokv_ex_sat_raw`, the CLI/SRV classifier, and the
   large-pool worker wall/re-arm check. `tm_productive_us` and `ex_work_u_smooth` feed
   `tomokv_ex_productive_us` / `tomokv_ex_sat_productive` and every direction coordinate. Static mode
   maintains the same capped 0.25-EWMA for INFO without enabling actuation (`src/server.c:27706-27770`).
3. `loadbalance-flip.md`'s productive-only IO direction description predates the uring source
   correction. Its `wsig=0` and INFO-only `q_io`/queue-depth statements still hold, but this document
   and the owner equation in `server.c` are authoritative for the backend-specific IO operand.

## 2026-08-16 uring direction correction and falsifier re-run

The former uring operand understated IO direction after flicker was damped: MGET8 held at io4/ex4
with `u_io_work~0.67`, `u_ex~0.66`, and therefore `r~1`, despite the CPU-faithful IO reading being
about `0.88`. The selected uring operand now gives `r~0.88/0.66~1.33` at io4; at io5 the measured
ratio is about `1.09`, inside the `gstep/2~0.27` granularity floor, so io5 is the expected optimum.
For p1, the corrected ratio remains much greater than 1 until io6-7. Its initial `lr` becomes about
`ln(1.0/0.062)=2.8`, so the existing distance law selects a roughly five-thread calculated target
instead of a one-thread walk.

The original `r~=1` static falsifier was calibrated for productive IO and EX operands: p32 GET and
MGET8 were expected near 1 at io4/ex4. Under uring those statics must now be interpreted with the
CPU-times-occupancy IO operand; epoll retains the original productive expectation. The coordinator's
`tools/preflight/flip_landing.sh` cells `L1`, `L2`, `L3_p1_uring`, and `L4_p1_epoll`, including the
p32 static controls, are the falsifier re-run named beside the target equation in `server.c`.
