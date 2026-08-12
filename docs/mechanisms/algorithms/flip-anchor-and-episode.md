# Flip anchor and the directional in-floor episode

Once the productive-work signal has settled strictly inside the granularity floor, the controller
captures a **frozen anchor** (retry hysteresis) and runs one **directional episode**: a single-
direction momentum walk over neighbouring splits, judged by throughput, that returns to the measured
argmax. All in `tomoFlipController()` and the `tmFlipSweep*` helpers in `src/server.c`. The floor and
`gstep` are defined in `flip-trigger-and-actuation.md`; the throughput estimator in `flip-signal.md`.

## The frozen anchor

### Capture conditions (`src/server.c:26859-26877`)

```c
int signal_settled   = (fc->lr_quiet_run >= FLIP_R_QUIET_N);      /* 8 quiet-ratio ticks */
int rate_settled     = (fc->anchor_rate_run >= FESC_SETTLE_N);    /* 5 throughput-plateau ticks */
int anchor_idle      = (fc->dir == 0 && fc->phase == 0 && fc->revert_steps == 0);
int inside_floor     = fabs(fc->lr_ewma) < gfloor;
int settled_in_floor = anchor_idle && inside_floor && signal_settled && rate_settled;   /* 26810 */
int at_intended_best = (fc->floor_probe_best_io == 0 || fc->floor_probe_best_io == ni);
if (settled_in_floor && fc->anchor_n == 0 && at_intended_best) { /* capture */ }
```

All at once: idle controller, signal strictly inside `gfloor`, ≥ 8 quiet-ratio ticks (`FLIP_R_QUIET_N`),
≥ 5 throughput-plateau ticks (`FESC_SETTLE_N`), and the current split is the intended measured best.
`fc->anchor_rate_run` is advanced by the shared plateau estimator `tmFlipRatePlateauUpdate` — a tick
counts as plateau when `fabs(mean - anchor_rate_prev) < sigma` (`src/server.c:25028-25036`, folded at
`:26242-26243`).

### What capture freezes (`src/server.c:26860-26870`)

```c
fc->lr_anchor       = fc->lr_ewma;                          /* the retry-band centre */
fc->anchor_n        = 1;
fc->anchor_u_io     = u_io;   fc->anchor_u_ex = u_ex;       /* magnitude snapshots (log/rebase only) */
fc->anchor_rate_cap = fc->mean;                             /* the rate the sat-drop judges against */
fc->anchor_lr_sigma = sqrt(fc->lr_var > 0.0 ? fc->lr_var : 0.0);   /* the anchor band's sigma, FROZEN */
fc->anchor_out_dir  = 0;   fc->anchor_out_run = 0;
fc->anchor_io_live  = ni;  fc->anchor_ex_live = ne;         /* the exact role split at capture */
fc->anchor_sat_rebase = 0;
```

**No running-mean fold.** The anchor updates only by explicit re-capture (a drop → fresh settle, or a
sweep finishing at a new split re-seeks with `anchor_n` reset). A folding/tracking anchor is exactly
how the original band trigger froze itself shut, so the fold is deleted by design
(`src/server.c:26878-26882`).

The anchor is the deadzone centre for the ordinary trigger's `beyond_band` test
(`src/server.c:27170-27171`); its invalidation ("drops") is documented in `flip-drops.md`.

### Anchor state variables

| Field | Type | Meaning |
| --- | --- | --- |
| `anchor_n` | `int` | 0 = UNSET (no hysteresis vote); 1 = captured (never folded higher) |
| `lr_anchor` | `double` | frozen `lr` = deadzone centre |
| `anchor_u_io`, `anchor_u_ex` | `double` | frozen role magnitudes (log + rebase only) |
| `anchor_rate_cap` | `double` | frozen throughput; the sat-drop's reference |
| `anchor_lr_sigma` | `double` | `sqrt(lr_var)` frozen at capture; the anchor-band sigma |
| `anchor_io_live`, `anchor_ex_live` | `int` | exact split at capture (same-split test) |
| `anchor_sat_rebase` | `int` | 1 ⇒ re-base the magnitude snapshot after a split crossing before comparing again |

## The directional in-floor episode

### Entry (`src/server.c:26887-26897`)

```c
if (settled_in_floor && fc->anchor_n > 0 && !fc->floor_probe_used) {
    int base_io = (nnodes == 1) ? server.io_threads : server.io_per_node;
    tmFlipSweepBegin(fc, node, ni, ne, base_io, wsig, u_io, u_ex);
    int next = tmFlipSweepNextCandidate(fc, ni);
    if (next != 0) tmFlipSweepTarget(fc, ni, next, 0);
    else tmFlipSweepFinish(fc, node, ni);       /* structural one-config edge */
}
```

A fully settled anchor with no episode used yet begins one episode and marks the entry split
measured.

### `tmFlipSweepBegin`: the walk is one direction only (`src/server.c:25147-25249`)

The helper first computes a **capacity-admitted set** — every split whose capacity-predicted `lr` is
strictly inside its own half-`gstep` floor — but then **clears that
set** (`memset` at `src/server.c:25192`) and keeps it only for the START log. The actual walk is the
momentum law inside the floor:

```c
int ep_dir = (isfinite(fc->lr_ewma) && fc->lr_ewma < 0.0) ? -1 : +1;   /* heavier side ; 25193 */
int first  = ni + ep_dir;
if (first < legal_lo || first > legal_hi) { ep_dir = -ep_dir; first = ni + ep_dir; }   /* reverse if illegal */
if (first >= legal_lo && first <= legal_hi && first != ni)
    fc->floor_probe_candidates[first] = 1;                              /* admit ONLY that neighbour */
```

- **Direction** = the sign of `lr_ewma` (`lr < 0` ⇒ grow-back, else grow-front — the heavier side is
  where adding a thread helps). It reverses only when the first neighbour is illegal, and initially
  admits just that one neighbour (`src/server.c:25193-25197`).
- **`legal_lo`/`legal_hi`** preserve at least one EX worker (`legal_hi = pool - 1`) and start at the
  base IO count. Node 0's single-IO base is special-cased: `io1 → io2` is not reversible (main never
  receives evacuated conns), so a one-IO node-0 sweep is pinned to `legal_hi = 1`; a `≥2`-IO node-0
  base raises `legal_lo` to 2 (`src/server.c:25151-25163`).
- The entry itself is recorded as **measurement number one**: `floor_probe_candidates[ni] = 2`
  (`src/server.c:25202`).

**Candidate byte encoding** (`unsigned char floor_probe_candidates[TOMO_IO_THREADS_MAX+1]`,
`src/server.c:24877-24880`): `0` absent, `1` unvisited, `2` measured, `3` structurally blocked. The
byte set is the *hard* bound — later signal samples cannot grow it, so every status-1 config reaches
exactly one terminal state.

Begin also seeds `best_rate = mean`, `best_dist = 0`, `coast_used = 0`, `entry_lr/entry_io/entry_ex`,
and `scan_dir = ep_dir` (`src/server.c:25204-25235`).

### Per-candidate judge (Phase 2, `src/server.c:26597-26677`)

Each candidate uses the same warmup + 16-tick measurement as the ordinary climb, then:

```c
double prior_best = fc->best_rate;
double sweep_band = fmax(2.0 * sigma, 0.02 * prior_best);
int significant = after > prior_best + sweep_band;                        /* 2σ / 2% ; 26613-26614 */
int improved    = significant ||
                  (ni == fc->floor_probe_best_io && after > prior_best);  /* ratification hysteresis ; 26621-26622 */
if (improved) { fc->floor_probe_best_io = ni; tmFlipAcceptBestRate(fc, after); }
else          { fc->best_dist = abs(ni - fc->floor_probe_best_io); }
if (significant) {                                                        /* extend the frontier ONE step */
    int nxt = ni + fc->floor_probe_scan_dir;
    if (nxt in [legal_lo, legal_hi] && candidates[nxt] == 0) { candidates[nxt] = 1; planned++; }
}
```

- **A significant gain extends the frontier by exactly one split in the same direction**
  (`src/server.c:26632-26639`). Non-significant steps extend nothing.
- **Coast / overshoot** (`src/server.c:26641-26650`): `GAIN` resets coast; a within-band shortfall
  spends coast up to `FLIP_COAST = 1`; a larger shortfall is `OVERSHOOT`. So the walk ends within
  `COAST + 1` of the peak — the same bound as the out-of-floor climb.
- **Tie policy — ratification hysteresis** (`src/server.c:26615-26622`): displacing the standing best
  requires beating it by the **full** `sweep_band`; a within-noise reading cannot hand the final
  position to a near-tie neighbour. Ties keep the incumbent (flat-topped curves hold still). The one
  exception is a config refreshing **its own** standing measurement without the band, so that pair
  stays coherent.

After each visit the candidate byte is set to `2`, `visited` is incremented, and the next candidate
(or the measured best, as `final`) is targeted (`src/server.c:26652-26677`).

### Deterministic no-repeat order (`tmFlipSweepNextCandidate`, `src/server.c:25254-25268`)

Walk outward below entry first (in `scan_dir < 0`), then cross already-measured configs and walk
upward, with a defensive full-range fallback for a sparse admitted set. A byte changes `1 → 2` only
after Phase 2 (or `1 → 3` after a bounded structural refusal), so transit and transient refusal never
consume a visit.

### Final positioning, KEEP vs REVERT (`tmFlipSweepFinish`, `src/server.c:25384-25458`)

Return to the measured argmax via `tmFlipSweepReturnToBest` → `tmFlipSweepTarget(..., final=1)` →
walk-back (`src/server.c:25460-25469`). Two merit outcomes:

- **KEEP**: the measured argmax is a *different* split and it was reached; resets `episode_revert_run`
  to 0 and `veto_run` to 0 (`src/server.c:25406-25411`, `:25425`).
- **REVERT**: the measured argmax is the entry and the return home completed; if the finish split
  equals `revert_run_io` then `episode_revert_run++`, else it resets `revert_run_io`/
  `episode_revert_run = 1` (`src/server.c:25412-25417`). This counter is the drop-damping shift
  (see `flip-drops.md`).

Finish then **re-bases** the episode coordinates onto the finished split (`entry_io = current_io`,
`entry_lr = lr_ewma`, recompute `entry_gfloor`) so the completed-episode workload-change test
telescopes over a zero-length path (`src/server.c:25427-25441`). It sets `floor_probe_used = 1` and
`floor_probe_await_settle = 1` unless this was a fresh-episode recovery (`src/server.c:25442-25445`).

### Return retry and structural blocking

- **Return retry bound** = the width of the already-derived legal window (`tmFlipSweepReturnRetryLimit`,
  `src/server.c:25290-25293`). Over-limit → `tmFlipSweepReturnBlocked` clears the latch but retains the
  measured destination; a full settle window re-arms the return (`RETURN-REARM`,
  `src/server.c:26840-26855`). A failed return never promotes the split where movement stopped
  (`src/server.c:25350-25378`).
- **Structural blocking**: a candidate refused `FLIP_SUSTAIN = 8` times is marked byte `3`
  (`tmFlipSweepSkipBlocked`, `src/server.c:25475-25497`; refusal counting at `:26923`, `:27011`).

### Abandonment (`tmFlipSweepAbandon`, `src/server.c:25502-25528`)

An active episode abandons — retaining positioning state until it has returned to the measured best —
on any of:

- 5 idle-or-`mean<1000` ticks (`floor_probe_idle_run >= FESC_SETTLE_N`, `src/server.c:26251-26265`);
- a non-positive measurement (`after <= 0` in Phase 2, `src/server.c:26503-26510`);
- a throughput ratio past the per-transfer `FLIP_LOAD_SHIFT^k` load-shift bound
  (`src/server.c:26566-26580`).

**Ratio-derived workload-change policing is intentionally absent while the episode is moving**: a sweep
moves the config, which moves `lr`, so `lr` cannot police the sweep. The only during-sweep tests are
rate-based (`src/server.c:26270-26281`). The completed-episode re-arm path is the exception where the
`lr`-equivalent test runs (`tmFlipSweepWorkloadChanged`, `src/server.c:25090-25138`; caller
`:26282-26320`) — see `flip-drops.md`.

## Episode state variables (`flipCtlState`, `src/server.c:24854-24911`)

| Field | Type | Meaning |
| --- | --- | --- |
| `floor_probe_used` | `int` | episode latch (settled-episode consumed for this workload) |
| `floor_probe_active` | `int` | enumeration/positioning in progress |
| `floor_probe_revert_pending` | `int` | current move is the final return positioning |
| `floor_probe_await_settle` | `int` | keep self-induced signal moves from re-arming the episode |
| `floor_probe_abandon_pending` / `_return_blocked` | `int` | abandonment / blocked-return sub-states |
| `floor_probe_entry_io/_ex/_lr/_gfloor` | `int`/`double` | episode entry coordinates (re-based at finish) |
| `floor_probe_legal_lo/_hi` | `int` | legal split window |
| `floor_probe_target_io`, `floor_probe_best_io` | `int` | current target; measured argmax |
| `floor_probe_scan_dir` | `int` | the single episode direction |
| `floor_probe_candidates[TOMO_IO_THREADS_MAX+1]` | `unsigned char` | 0/1/2/3 byte set (the hard bound) |
| `floor_probe_visited`, `floor_probe_planned` | `int` | progress counters |
| `best_rate` | `double` | best measured rate this episode (walk-back target) |
| `best_dist` | `int` | one-thread transfers since best |
| `coast_used` | `int` | non-improving steps spent (bounded by `FLIP_COAST`) |
| `revert_steps`, `walkback_armed` | `int` | reposition transfers left / one in flight |
| `episode_revert_run`, `revert_run_io` | `int` | same-split REVERT damping shift + its split |

## Invariants

- The anchor is a frozen snapshot; it changes only by explicit re-capture, never by fold
  (`src/server.c:26878-26882`).
- The episode is **one direction, one step per significant gain**, walking back to the measured
  argmax; it is core-count independent because `gstep` shrinks as counts grow, so a larger machine
  admits fewer lattice points rather than a longer sweep (`src/server.c:25140-25146`,
  `:25178-25187`).
- Exploration is bounded to `COAST + 1` non-significant steps → no ratchet
  (`src/server.c:26629-26650`).
- Ties keep the incumbent split (ratification hysteresis), so a flat-topped throughput curve does not
  drift (`src/server.c:26615-26622`).
- The candidate byte set is closed at `tmFlipSweepBegin`; later samples cannot grow it
  (`src/server.c:25140-25143`).

## Note vs the brief / `loadbalance-flip.md`

The task and the config comments describe an *exhaustive* in-floor sweep over the admitted set plus
both neighbours. The shipped code computes that admitted set only for the START log and then clears it,
running a **single directional, gain-extended** episode with one initial neighbour
(`src/server.c:25165-25203`). This matches `loadbalance-flip.md`'s "Directional in-floor episode"
section and its discrepancy #5.
