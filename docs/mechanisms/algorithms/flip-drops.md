# Flip anchor drops: the three settled change-detectors and the REVERT damping

A captured anchor (see `flip-anchor-and-episode.md`) cannot coexist with a signal that has moved
materially. Three detectors invalidate it — set `anchor_n = 0` and, at the captured split, re-arm a
fresh episode. Each is Schmitt-gated on **settled ticks only** and each (except the floor-exit arm) is
widened by the same power-of-two REVERT damping. All in the anchor-invalidation block of
`tomoFlipController()`, `src/server.c:26101-26221`, with a parallel completed-episode variant at
`:26282-26320`.

## The two Schmitt run counters (`src/server.c:26118-26146`)

Both are advanced only on a **settled tick** — `fo_ticking` is true only when no episode/positioning
is active and the controller is idle and non-idle-workload:

```c
int fo_ticking = !fc->floor_probe_active && !fc->floor_probe_await_settle &&
                 fc->dir == 0 && fc->phase == 0 && fc->revert_steps == 0 &&
                 !fc->walkback_armed && !fc->step_armed && !node_idle;    /* 26121-26123 */
```

Counting only settled ticks is deliberate: a sweep/climb transit moves `lr` by construction, so
counting those would hand the counter to the actuator (`src/server.c:26106-26117`).

### Floor-out run (`floor_out_dir`, `floor_out_run` — `int`)

```c
int fo = (isfinite(fc->lr_ewma) && fabs(fc->lr_ewma) >= gfloor)
             ? (fc->lr_ewma > 0 ? 1 : -1) : 0;                           /* 26119-26120 */
if (!fo_ticking || fo == 0 || fo != fc->floor_out_dir) {
    fc->floor_out_dir = fo_ticking ? fo : 0;
    fc->floor_out_run = (fo_ticking && fo) ? 1 : 0;
} else if (fc->floor_out_run < INT_MAX) fc->floor_out_run++;             /* 26124-26127 */
```

### Anchor-band run (`anchor_out_dir`, `anchor_out_run` — `int`)

```c
int ao = 0;
if (fc->anchor_n > 0 && isfinite(fc->lr_ewma) && isfinite(fc->lr_anchor) && fc->anchor_lr_sigma > 0.0) {
    double dev   = fc->lr_ewma - fc->lr_anchor;
    double aband = 2.0 * fc->anchor_lr_sigma *
                   (double)(1 << (fc->episode_revert_run > 3 ? 3 : fc->episode_revert_run));   /* damping */
    if (fabs(dev) > aband) ao = dev > 0 ? 1 : -1;                        /* 26133-26140 */
}
/* same Schmitt update shape as floor_out above */                      /* 26142-26145 */
```

## The three drops (`src/server.c:26147-26221`)

Evaluated only while `anchor_n > 0`:

### 1. Floor-exit drop

```c
int drop_floor = !isfinite(fc->lr_ewma) || fc->floor_out_run >= FLIP_SUSTAIN;   /* 26157-26158 */
```

The smoothed signal has left the half-step floor for `FLIP_SUSTAIN = 8` **settled** ticks (or `lr` is
non-finite). This is the coarse arm: the floor is the *set* of legal configs, so leaving it means the
optimum itself may have moved.

### 2. Anchor-band drop

```c
int drop_anchor = fc->anchor_out_run >= FLIP_SUSTAIN;                    /* 26182 */
```

`lr` has drifted a sustained `> 2·anchor_lr_sigma · 2^min(episode_revert_run,3)` off the frozen anchor
while still inside the floor — a mix change the floor cannot see. The fine arm inside the floor. Sigma
is `anchor_lr_sigma`, frozen at capture, so the deviation can never widen its own allowance
(`src/server.c:24896-24902`).

### 3. Rate-band drop (the "sat-magnitude" drop)

Despite the `sat`/`u` naming, this arm judges in **throughput**, not in `2·sigma_u`
(`src/server.c:26176-26181`):

```c
int sat_sample_ready = same_split && anchor_idle-state && !floor_probe_active/await_settle &&
                       fc->lr_quiet_run >= FLIP_R_QUIET_N && fc->anchor_rate_run >= FESC_SETTLE_N;  /* 26149-26156 */

/* re-base the magnitude snapshot once after a split crossing, before it can trip: */
if (!drop_floor && sat_sample_ready && fc->anchor_sat_rebase) {
    fc->anchor_u_io = u_io; fc->anchor_u_ex = u_ex; fc->anchor_rate_cap = fc->mean;
    fc->anchor_sat_rebase = 0;                                          /* 26162-26167 */
}
double drop_band = fmax(2.0 * sigma, 0.02 * fc->anchor_rate_cap) *
                   (double)(1 << (fc->episode_revert_run > 3 ? 3 : fc->episode_revert_run));   /* damping */
int drop_sat = sat_sample_ready && !fc->anchor_sat_rebase &&
               (!isfinite(u_io) || !isfinite(u_ex) ||
                fabs(fc->mean - fc->anchor_rate_cap) > drop_band);       /* 26176-26181 */
```

The band is `max(2·sigma, 2%)` of the throughput captured in `anchor_rate_cap`, using the throughput
`sigma`. The `u` operands are used only for the finiteness check and the log line. Reason: the
owner-equation cap pins a saturated side at ~0.985 whose EWMA jitter is microscopic, so a `2·sigma_u`
allowance shrinks to ±0.3 % and ordinary warmup drift would re-arm a sweep every ~15 s with nothing
actionable changed (`src/server.c:26168-26175`).

### Firing

```c
if (drop_floor || drop_anchor || drop_sat) {
    fc->anchor_n = 0; fc->lr_anchor = 0.0; fc->anchor_sat_rebase = 0;    /* UNSET: no stale centre */
    /* clear both Schmitt runs, quiet run, rebase, noise prime ...      (26186-26196) */
    if (same_split && !fc->floor_probe_await_settle) {                   /* re-arm a fresh episode */
        fc->floor_probe_used = 0; fc->floor_probe_best_io = 0; fc->floor_probe_return_blocked = 0;
    }
    if (drop_floor)      { count anchor_drop_floor; fc->episode_revert_run = 0; }   /* MIX moved */
    else if (drop_anchor){ count anchor_drop_floor; fc->episode_revert_run = 0; }   /* mix moved in-floor */
    else                 { count anchor_drop_sat;   /* rate-only: damping NOT reset */ }
}
```

`src/server.c:26183-26220`.

## The `x2`-per-consecutive-same-split-REVERT damping (cap `x8`)

The widening factor on the anchor-band (arm 2) and rate-band (arm 3) allowances is

```text
2 ^ min(episode_revert_run, 3)   =   x1, x2, x4, x8
```

`fc->episode_revert_run` (`int`) is the count of consecutive clean **REVERT** episode finishes at the
same split, maintained in `tmFlipSweepFinish` (`flip-anchor-and-episode.md`):

- REVERT at the same `revert_run_io` ⇒ `episode_revert_run++` (`src/server.c:25415`);
- REVERT at a different split ⇒ reset to 1 with new `revert_run_io` (`src/server.c:25416`);
- KEEP ⇒ `episode_revert_run = 0` (`src/server.c:25411`).

Rationale: N same-verdict re-verifications are evidence the rate motion does **not** move the optimum,
so a monotone warmup tide stops being re-probed (`src/server.c:24887-24892`). The shift is capped at 3
(`x8`) exactly like the trigger's veto backoff (`flip-trigger-and-actuation.md`).

### The REVERT damping is reset by a KEEP or the two "mix moved" drops, NOT by a rate-only drop

| Event | Effect on `episode_revert_run` | Source |
| --- | --- | --- |
| Episode finishes **KEEP** | `= 0` | `src/server.c:25411` |
| Episode finishes **REVERT**, same split | `++` (widen) | `src/server.c:25415` |
| Episode finishes **REVERT**, new split | `= 1` | `src/server.c:25416` |
| **floor-exit** drop | `= 0` | `src/server.c:26206` |
| **anchor-band** drop | `= 0` | `src/server.c:26209` |
| **rate-band** (sat-magnitude) drop | *unchanged* | `src/server.c:26210-26211` (no reset) |

A rate-only drop leaving the damping intact is deliberate: it means "the rate moved but the mix (and
therefore the optimum) has not been shown to move," so successive same-split re-verifications keep
widening the allowance (`src/server.c:26197-26211`).

## Completed-episode variant (`src/server.c:26282-26320`)

After an episode has finished and the controller is again settled and observable
(`sweep_observable = !node_idle && lr_quiet_run >= FLIP_R_QUIET_N && anchor_rate_run >= FESC_SETTLE_N`,
`src/server.c:26267-26269`), `tmFlipSweepWorkloadChanged` runs the same two arms
(`src/server.c:25090-25138`):

- a **normalized floor** arm that telescopes `lr` through the capacity predictor from the (re-based)
  entry coordinates, gated by `floor_out_run >= FLIP_SUSTAIN` (`src/server.c:25099-25107`);
- a **rate-band** arm using `max(2·rate_sigma, 2%)` of `floor_probe_check_rate` with the same
  `2^min(episode_revert_run,3)` damping (`src/server.c:25129-25133`).

A fired detector clears the episode latch and re-arms (`EPISODE-DROP`, `src/server.c:26298-26317`),
with the same `floor-exit ⇒ episode_revert_run = 0` / `sat ⇒ unchanged` split (`:26290-26296`).

## Schmitt gating summary

| Drop | Predicate | Persistence | Damped? |
| --- | --- | --- | --- |
| floor-exit | `\|lr_ewma\| >= gfloor` | `floor_out_run >= 8` settled ticks | no (band is `gfloor`) |
| anchor-band | `\|lr_ewma - lr_anchor\| > 2·anchor_lr_sigma·2^k` | `anchor_out_run >= 8` settled ticks | yes (in the band) |
| rate-band | `\|mean - anchor_rate_cap\| > max(2σ, 2%)·2^k` | `sat_sample_ready` (quiet≥8 AND plateau≥5, same split) | yes (in the band) |

`k = min(episode_revert_run, 3)`; `FLIP_SUSTAIN = 8` (`src/server.c:24990`).

## Invariants

- Every drop drives `anchor_n → 0` and `lr_anchor → 0.0` (UNSET), never a stale centre
  (`src/server.c:26184-26185`).
- Drop persistence uses the **same** `FLIP_SUSTAIN` bar as the ordinary trigger, but on settled ticks
  only — because a completed-episode latch forces the trigger's own `lr_out_run` to 0 exactly where
  the drops are the only remaining actor (`src/server.c:26106-26117`).
- The band-widening sigma (`anchor_lr_sigma`) and the rate reference (`anchor_rate_cap`) are frozen at
  capture, so a deviation can never widen its own allowance (`src/server.c:26104-26105`,
  `:24896-24897`).
- A `same_split` drop re-arms a fresh episode; a sweep move / final walk-back / cache re-settle must
  not re-arm (guarded by `!floor_probe_await_settle`, `src/server.c:26199`).
