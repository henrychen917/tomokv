# Flip signal: the productive-work ratio `lr = ln(u_io/u_ex)`

The single decision signal for the auto-flip controller since 2026-08-10. Everything downstream
(the trigger floor, the anchor deadzone, the per-tick quiet test, the k-jump distance, the anchor
drops) is defined on this one quantity. All code is in `tomoFlipController()` and its helpers in
`src/server.c`; the signal fields live in `flipCtlState` (`src/server.c:24761-24911`).

This document treats the code as authoritative. Where the source contradicts the task framing or
`loadbalance-flip.md`, the code reading is given and the divergence is called out under
[Notes where code differs from the brief](#notes-where-code-differs-from-the-brief).

## What is measured, and from which counters

Two per-role "productive work fraction of wall time" numbers, each in `[0,1]`:

```text
u_io = EWMA( sum(delta IO tm_work_us) / (wall_us * live_nonmain_io) ), capped at 1
u_ex = EWMA( sum(delta EX tm_busy_us) / (wall_us * live_ex)         ), capped at 1
```

- `u_io` is fed by the IO owner's `tmIoSignal.tm_work_us` (`unsigned int`, wrap-safe cumulative),
  which brackets the io_uring CQ reap + `beforeSleepIO` prefix and the post-poll/enter fired-callback
  tail. Poll/enter sleep is *outside* the bracket, so spinning on an empty socket set cannot raise
  `u_io`. Accumulated in `ioSlice()` at `src/server.c:23103` from `aeProcessEventsIO`'s
  `accounting.work_us`; the bracket itself is `src/ae.c:560-571` (prefix) and `src/ae.c:704-737`
  (tail). Field declared `src/server.c:757-760`.
- `u_ex` is fed by the worker's `exThread.tm_busy_us` (`unsigned int`, wrap-safe), the first-pop →
  work-pass-end busy interval. Accumulated at `src/server.c:22302`. Field declared
  `src/server.h:2649-2653`.

Both counters are owner-written plain integers and read racily by the 4 Hz controller with unsigned
deltas — no atomic synchronization (`src/server.c:649-653`, `src/server.h:2617-2620`).

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
| `fc_prev_io_work_us[TM_MAXNODE][TOMO_IO_THREADS_MAX+1]` | `uint32_t` | `u_io` numerator |
| `fc_prev_ex_work_us[TM_MAXNODE][TOMO_EX_THREADS_MAX+1]` | `uint32_t` | `u_ex` numerator |
| `fc_prev_io_idle_us` / `fc_prev_io_wait_us` / `fc_prev_io_stall_us` | `uint32_t` | legacy occupancy / INFO |
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
work (`src/server.c:25739-25741` for IO, `src/server.c:25690-25692` for EX):

```c
uint32_t cwork = tm_io_sig[t].tm_work_us;
uint32_t dwork = cwork - fc_prev_io_work_us[node][t];   /* unsigned wrap-safe */
fc_prev_io_work_us[node][t] = cwork;
```

`dwork` is added into `io_work_delta_sum` only for slots currently live in the IO role
(`src/server.c:25742-25757`); `db` into `ex_work_delta_sum` only for slots in EX mode
(`src/server.c:25710-25717`). Node 0's IO slot 0 (main) is excluded from the IO loop, which starts
at `t = 1` (`src/server.c:25724`).

**First-visit fold-out.** On the first visit to a node (`!work_sample_primed`) the deltas reach back
to process start, so both sums are zeroed and no work sample is published this tick
(`src/server.c:25761-25764`).

### Raw fractions, the cap, and the smoothing EWMA

`io_occ_cnt` counts the live non-main IO owners; `w_live` counts the live EX workers.

```text
io_work_u_mean = io_work_delta_sum / (node_wall_ms * 1000 * io_occ_cnt)   (src/server.c:25778-25781)
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

### The decision operands and the log-ratio

The only decision operands are selected and re-capped (`src/server.c:25892-25900`):

```c
double u_io = fc->io_work_u_smooth;   /* == u_io_work */
double u_ex = fc->ex_work_u_smooth;   /* == u_ex_work */
if (u_io > 1.0) u_io = 1.0;
if (u_ex > 1.0) u_ex = 1.0;
double io_sat = u_io, ex_sat = u_ex;   /* 25986: NOTHING else augments them */
```

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
| `io_work_u_smooth`, `ex_work_u_smooth` | `double` | the two capped productive-work EWMAs = `u_io`, `u_ex` |
| `lr_ewma` | `double` | EWMA of `log(u_io/u_ex)`; the decision signal |
| `lr_init` | `int` | 1 once `lr_ewma` seeded from the first loaded sample |
| `lr_quiet_run` | `int` | consecutive ticks the EWMA step stayed `< FLIP_R_QUIET`; caps at 1000 |
| `lr_prev_tick` | `double` | stored, **not read** by the current controller (quietness uses the local `lr_before`) |
| `mean`, `var` | `double` | throughput EWMA + variance |
| `io_occ_smooth`, `ex_occ_smooth` | `int` | legacy integer-truncated occupancy EWMAs (diagnostics / worker-only modes) |
| `u_io_mean`/`u_io_var`, `u_ex_mean`/`u_ex_var` | `double` | per-role noise EWMAs (observability) |
| `lr_mean`, `lr_var` | `double` | settled-tick `lr` noise; `sqrt(lr_var)` frozen at capture |
| `sat_smooth` | `double` | EWMA of `max(u_io,u_ex)`; the server-bound gate input |

## Key constants

`FESC_ALPHA = 0.25` (`src/server.c:24917`), `FLIP_R_QUIET = 0.02` (`src/server.c:24997`),
`FLIP_R_QUIET_N = 8` (`src/server.c:24998`). The productive-work signal is the only signal; the
old `tomokv-flip-signal` knob and `FLIP_SIG_*` modes were deleted 2026-08-10, and `wsig` is a
compile-time `const int 0` (`src/server.c:25014-25016`, `src/server.c:25635-25639`).

## Invariants

- `u_io, u_ex ∈ [0,1]` by construction (cap at raw-mean time and again at operand select); `ratio ∈
  [1e-3, 1e3]`; `lr` is always finite (NaN/inf replaced by 0). `src/server.c:25782`, `:25836`,
  `:25898-25900`, `:26035-26037`.
- Owner-written counters are advanced-baselined for **every** node-owned slot even in the opposite
  role, so a role transition never injects a work spike (`src/server.c:25687-25692`,
  `:25726-25741`).
- One field (`lr_ewma`) carries the signal for the anchor, the deadzone, the quiet test, the START
  gate, and the same-wave latch — deliberately, so it is structurally impossible to anchor one
  quantity while testing another for quietness (`src/server.c:24823-24833`).

## Notes where code differs from the brief

1. **Not integer-EWMA.** The task describes "the EXACT integer-EWMA math" for `u_io`/`u_ex`. In code
   the productive-work operands `io_work_u_smooth`/`ex_work_u_smooth` and `lr_ewma` are **`double`**
   EWMAs at `FESC_ALPHA = 0.25` (`src/server.c:25783`, `:25837`, `:26063`). The integer-truncated
   EWMA (`x += (int)(FESC_ALPHA*(mean - x))`) applies only to the **legacy occupancy** fields
   `io_occ_smooth`/`ex_occ_smooth` (`src/server.c:25775`, `:25831`), which are diagnostics / retained
   worker-only-mode operands and do **not** feed `lr`.
2. **`u_io` source is `tm_work_us`, not `tm_idle_us`.** The task says `u_io`/`u_ex` accumulate "from
   `tm_busy_us`/`tm_idle_us`". `u_ex` does use EX `tm_busy_us` (`src/server.c:25690`). But `u_io` uses
   IO `tm_work_us` (`src/server.c:25739`); `tm_idle_us` feeds only the legacy occupancy path and the
   `node_idle` test (`src/server.c:25729-25731`, `:25803`). IO `tm_busy_us` (a sampled CPU-time
   diagnostic, `src/server.c:23113-23118`) is not read in the controller's per-node loop at all.
3. These match `loadbalance-flip.md`'s "Productive-work signal" section, which also documents the
   `wsig=0` productive-ratio path and the `q_io`/queue-depth quantities being INFO-only. The
   config-comment claims of selectable signal modes are a documented comment/code discrepancy
   (`loadbalance-flip.md` discrepancy #1, #3, #4).
