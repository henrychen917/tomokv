# Flip trigger and actuation: the Schmitt gate, the granularity floor, and the k-jump

The ordinary-pressure trigger decides *whether* and *which way* to start a climb, and the k-jump
decides *how many* one-thread transfers make the first step. All in `tomoFlipController()` and
`tmFlipStepMoves()` in `src/server.c`. Direction and magnitude both derive from `lr_ewma` (see
`flip-signal.md`); throughput only vetoes afterward (see `flip-anchor-and-episode.md`).

## The one-thread granularity quantum `gstep` and the floor `gfloor`

Recomputed from the current live split on **every** tick (`src/server.c:26076-26080`):

```c
int ni = io_live_node + (node == 0 ? 1 : 0);   /* add main back to the ROLE count on node 0 */
if (ni < 1) ni = 1;
int ne = w_live > 0 ? w_live : 1;
double gstep  = tmFlipGstepAt(ni, ne, fc->lr_ewma, wsig);   /* wsig is compile-time 0 */
double gfloor = gstep / 2.0;
```

`tmFlipGstepAt` (`src/server.c:25062-25072`), with `wsig == 0`:

```c
static double tmFlipGstepAt(int ni, int ne, double lr, int wsig) {
    if (ni < 1) ni = 1;
    if (ne < 1) ne = 1;
    /* wsig==0 (the only shipped path): */
    return log((double)(ni + 1) / (double)ni) +
           ((ne > 1) ? log((double)ne / (double)(ne - 1)) : 1.0);
}
```

So

```text
gstep  = ln((ni+1)/ni) + ( ne>1 ? ln(ne/(ne-1)) : 1.0 )
gfloor = gstep / 2
```

- `ni`/`ne` are clamped to ≥ 1 before the log.
- **The `ne == 1` widening.** When only one EX worker remains, the exact term `ln(ne/(ne-1))`
  would be `ln(1/0) = +inf`; the code substitutes the literal `1.0` (one nat). This makes `gstep ≥ 1`
  and `gfloor ≥ 0.5`, so almost any `|lr|` reads as inside the floor — a grow-front that would strand
  the last EX worker is effectively refused by the floor test rather than by an actuator error.
- `ni` counts main back in on node 0 even though the IO signal loop skips slot 0: `io4/ex4` must price
  `ln(5/4)+ln(4/3)` (floor 0.255), not the poly-slot-only `ln(4/3)+ln(4/3)`
  (`src/server.c:26070-26075`). Worked values from the source comment (`src/server.c:27122-27123`):
  `N=8 → step 0.511, floor 0.255`; `N=24 → 0.167/0.084`; `N=64 → 0.063/0.031`.

The same per-tick `gstep`/`gfloor` drives the trigger floor, the k-jump distance, the anchor
invalidation, and the in-floor episode enumeration (`src/server.c:26070-26075`).

## The ordinary trigger (`src/server.c:27106-27245`)

### Direction, floor, and band

Direction always comes from the **target `r = 1`** (the sign of `lr_ewma`), never from which side of
the anchor the signal sits (`src/server.c:27150-27173`):

```c
double band = log1p(FLIP_R_BAND);                  /* log1p(0.03) ; src/server.c:27114 */
int beyond_floor = (fabs(fc->lr_ewma) >= gfloor);  /* 27164 */
int beyond_band  = (fc->anchor_n == 0) ||
                   fabs(fc->lr_ewma - fc->lr_anchor) > band;   /* 27170-27171 */
int out = 0;
if (beyond_floor && beyond_band)
    out = (fc->lr_ewma > 0.0) ? +1 : -1;           /* +1 grow-front / -1 grow-back ; 27172-27173 */
```

- A request exists only **outside the half-step floor** and, when an anchor is set, **outside
  `log(1.03)` around that anchor**. With `anchor_n == 0` (unset) the band test passes automatically,
  so any actionable outside-floor magnitude reaches sustain — including the interval between `gfloor`
  and `FLIP_R_FAR = 0.69` (`src/server.c:27165-27169`).
- `r > 1` ⇒ IO is the more saturated stage ⇒ grow-front (`+1`) — which also moves `r` back toward 1.

### The Schmitt sustain (`FLIP_SUSTAIN`, with veto backoff)

`out` must persist a **consecutive same-direction run** before it can fire (`src/server.c:27186-27245`):

```c
if (out != 0 && out == fc->lr_out_dir) fc->lr_out_run++;
else { fc->lr_out_dir = out; fc->lr_out_run = out ? 1 : 0; }        /* 27186-27187 */

if (!server_bound) { out = 0; fc->lr_out_dir = 0; fc->lr_out_run = 0; }   /* client-bound: hold; 27221 */
if ((fc->floor_probe_used || fc->floor_probe_return_blocked) && !fc->floor_probe_active) {
    out = 0; fc->lr_out_dir = 0; fc->lr_out_run = 0;                /* a completed episode owns the node; 27226-27231 */
}

int need = FLIP_SUSTAIN << (fc->veto_run > 3 ? 3 : fc->veto_run);   /* 8<<min(veto_run,3) = 8/16/32/64 ; 27233 */
int same_wave = (fc->veto_run >= 2 && fabs(fc->lr_ewma - fc->veto_lr) <= gstep);   /* 27240 */
if (fc->lr_out_run >= need && !same_wave) {
    if      (out > 0 && can_front) want = +1;
    else if (out < 0 && can_back)  want = -1;                       /* 27241-27244 */
}
```

- **`FLIP_SUSTAIN = 8`** controller ticks (~2 s = 2 EWMA time constants) at the base
  (`src/server.c:24990`; the macro is defined twice with the same value, `src/server.c:25006` —
  `loadbalance-flip.md` discrepancy #6). The actuator moves the signal, so acting on the first
  out-of-band tick would chase the post-flip transient.
- **Veto backoff.** `fc->veto_run` (`int`, capped 8) counts consecutive net-zero climbs from the same
  operating point; `need` doubles for each up to a cap of 3 shifts → **8, 16, 32, 64** ticks. A climb
  that ends back at its start config increments it (`src/server.c:26822-26834`); a productive climb, a
  re-baseline, or an idle/load change resets it.
- **Same-wave latch.** After ≥ 2 net-zero probes, a new signal within one `gstep` of the stored
  `fc->veto_lr` (`double`, the `lr_ewma` that pulled the last vetoed trigger) is suppressed outright as
  the same periodic wave (`src/server.c:27234-27240`).

### The server-bound gate

`server_bound` is the `!server_bound → hold` gate above (`src/server.c:26019`):

```c
double sat_total = fmax(io_sat, ex_sat);                       /* 26001 */
fc->sat_smooth  += FESC_ALPHA * (sat_total - fc->sat_smooth);  /* smoothed like every input ; 26018 */
int server_bound = (fc->sat_smooth >= FLIP_BOUND_SAT);         /* FLIP_BOUND_SAT = 0.75 ; 26019 */
```

Below `0.75` no stage is saturated, so the client or the round trip is the constraint and no flip can
win — hold. `FLIP_BOUND_SAT = 0.75` (`src/server.c:24941`, lowered from 0.95 once the signal became
occupancy rather than CPU time).

### Start stability gates

Even after `want != 0`, a climb starts only once **both** the ratio and the mean have settled
(`src/server.c:27282-27298`):

```c
if (fc->lr_quiet_run < FLIP_R_QUIET_N) { ... continue; }   /* ratio still moving ; FLIP_R_QUIET_N = 8 */
if (fc->idle_stable   < FESC_SETTLE_N) { ... continue; }   /* mean not caught up ; FESC_SETTLE_N = 5 */
```

`fc->idle_stable` (`int`) increments only while `fabs(mean - inst) < fmin(2*sigma, 0.10*mean)` — an
**AND** of an absolute-noise and a relative bound, so a workload transition (mean far above `inst`)
cannot pass (`src/server.c:26786-26787`).

### Direction-specific role headroom

`can_front`/`can_back` are hard liveness invariants, not tuning (`src/server.c:25808-25816`):

```text
can_front = (w_live > 1)                                 /* grow-front must leave one live EX worker */
can_back  = (io_live_node >= 2) &&
            (numa==1 ? io_threads_live > io_threads       /* at least one grown IO thread above base */
                     : io_live_node   > io_per_node)      /* and another non-main IO destination */
```

## The k-jump: distance step size (`tmFlipStepMoves`, `src/server.c:25541-25558`)

```c
static int tmFlipStepMoves(flipCtlState *fc, double gstep, int dir,
                           int w_live, int io_live, int grown_io_live) {
    int cap;
    if (dir > 0) cap = w_live - 1;                       /* grow-front: leave one EX worker */
    else { int io_cap = io_live - 1;                     /* grow-back: leave one live poly IO dest */
           cap = grown_io_live < io_cap ? grown_io_live : io_cap; }   /* and consume only grown IO */
    if (cap < 1) return 0;

    int moves = 1;
    if (fc->lr_ewma * (double)dir > 0.0 && isfinite(gstep) && gstep > 0.0) {
        double whole_moves = floor(fabs(fc->lr_ewma) / gstep);
        moves = whole_moves < 1.0 ? 1 : (whole_moves > (double)cap ? cap : (int)whole_moves);
    }
    return moves;
}
```

So, while the signal still agrees with the climb direction (`lr_ewma * dir > 0`):

```text
k = clamp( floor(|lr_ewma| / gstep), 1, cap )
```

Once the signal no longer agrees with the direction, `k = 1` (the one-thread look-ahead endgame).
`cap` is the direction-specific live cap; `moves <= 0` at the START/mid-climb sites aborts the step
(`src/server.c:27302`, `:25550`). The caller recomputes this for every new measured step; `step_moves`
is stored only while the step is being judged so an exact revert is possible, never reused as the next
step's magnitude (`src/server.c:25538`).

## Actuation

### START (`src/server.c:27300-27321`)

```c
int moves = tmFlipStepMoves(fc, gstep, want, w_live, io_live_node, grown_io_live_node);
if (moves <= 0) continue;
if (tmFlipDo(node, want, &err)) {                 /* arms ONE transfer (returns on ARM, not completion) */
    fc->best_rate = fc->before; fc->best_dist = 0; fc->revert_steps = 0; fc->walkback_armed = 0;
    fc->coast_used = 0;
    fc->last_dir = want; fc->dir = want;
    fc->step_moves = moves; fc->step_done = 0; fc->step_armed = 1;
    fc->start_io = ni;              /* net-zero detector baseline */
    fc->veto_lr  = fc->lr_ewma;     /* same-wave latch */
    fc->lr_out_run = 0; fc->lr_out_dir = 0;   /* the next climb must re-earn its sustain */
    fc->phase = 3;
    break;                          /* the first transfer owns the migration gate */
}
```

`tmFlipDo` dispatches `tomoGrowFront`/`tomoGrowBack` (numa 1) or the node-scoped variants (numa > 1)
(`src/server.c:25020-25023`).

### Phase 3: serialize the k transfers (`src/server.c:26349-26402`)

A distance step is *k serialized uses of the one-thread actuator*. No throughput judgement occurs
between transfers; each is armed only after the previous transfer's complete `-1/+1` role pair lands.
Handling of the tail:

- A later transfer that **aborts** reverses exactly the landed prefix to restore the pre-step split
  (`src/server.c:26350-26372`).
- A later transfer merely **refused** shrinks `k` to the landed prefix and judges that
  (`src/server.c:26378-26398`).
- After all `k` land, `tmFlipStepMeasure()` enters the warmup/measure phases (`src/server.c:26401`,
  defn `src/server.c:25563-25568`).

The phases are `0` idle/decision/reposition, `1` warmup, `2` measure, `3` finish-a-multi-transfer-step
(`src/server.c:24767-24768`). Warmup and measure are covered in `flip-anchor-and-episode.md`.

## Phase flow summary

```text
PHASE 0  pressure trigger (above): want != 0, gates pass -> tmFlipDo, phase = 3
PHASE 3  serialize k one-thread transfers through the single migration gate -> tmFlipStepMeasure -> phase 1
PHASE 1  adaptive warmup: EARLY-MEASURE if mean > best + max(2σ,2%); else rate-plateau (+ reshard-quiet
         near target), FESC_WARM_FAST=12 far / FESC_WARM_CAP=48 cap -> phase 2   (src/server.c:26404-26461)
PHASE 2  measure 16 ticks (FESC_MEAS_N), compute rate; keep / coast / overshoot-walkback  (26499-26737)
```

## Constants used here

| Macro | Value | Source |
| --- | --- | --- |
| `FLIP_SUSTAIN` | 8 | `src/server.c:24990` (and `:25006`, dup) |
| `FLIP_R_BAND` | 0.03 | `src/server.c:24969` |
| `FLIP_R_FAR` | 0.69 | `src/server.c:24967` |
| `FLIP_R_QUIET` / `FLIP_R_QUIET_N` | 0.02 / 8 | `src/server.c:24997-24998` |
| `FLIP_BOUND_SAT` | 0.75 | `src/server.c:24941` |
| `FLIP_COAST` | 1 | `src/server.c:24999` |
| `FLIP_LOAD_SHIFT` | 3.0 | `src/server.c:25009` |
| `FESC_ALPHA` | 0.25 | `src/server.c:24917` |
| `FESC_SETTLE_N` | 5 | `src/server.c:24918` |
| `FESC_WARM_FAST` / `FESC_WARM_CAP` | 12 / 48 | `src/server.c:24919-24921` |
| `FESC_MEAS_N` | 16 | `src/server.c:24922` |
| `FESC_WAIT_BASE` | 8 | `src/server.c:24923` |
| `FLIP_WAIT_KEEP` / `FLIP_WAIT_REVERT` | 4 / 12 | `src/server.c:24996`, `:25005` |

## Invariants

- Direction is always `sign(lr_ewma)` (target `r = 1`); the anchor decides only *whether*, never
  *which way* (`src/server.c:27150-27173`).
- A trigger needs `FLIP_SUSTAIN << min(veto_run,3)` consecutive same-direction out-of-band ticks and
  a passing `server_bound` gate and both settle gates (`src/server.c:27233-27298`).
- The k-jump never violates role liveness: `cap = w_live-1` (front) or `min(grown_io_live,
  io_live-1)` (back); `moves == 0` refuses the step (`src/server.c:25543-25550`).
- Every transfer of a k-step is armed only after the previous `-1/+1` pair lands; the pool
  conservation invariant `io_threads_live + num_workers_live == io_threads + num_workers` is checked
  each quiescent tick (`src/server.c:25613-25628`).
