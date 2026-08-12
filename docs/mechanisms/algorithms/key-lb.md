# Key-LB: the hot-BUCKET detector and bucket-range cutover

Key-LB moves ownership of a contiguous bucket range from a hot EX worker to a cooler adjacent
same-node neighbour. It never divides load — a bucket flip **relocates** load — so its hardest job is
telling a **hot bucket** (moveable) from a **hot key** (unmoveable). All in `reshardAutoTune()` and
helpers in `src/server.c`. Routing itself is untouched: a key maps to `xxh64(key) & 16383`, and
`server.ex_bucket_table[bucket]` (one byte load) gives the owner.

Cron: `run_with_period(1000) reshardAutoTune()` — 1 Hz, main thread (`src/server.c:2946`).
Knob: `tomokv-key-lb` → `server.reshard_min_ops` (`int`, default 20000, range `0..INT_MAX`, `0` = off;
`config.c:3292`). The comment names a deleted `tomokv-reshard-auto`; the registered knob is
`tomokv-key-lb` (`loadbalance-flip.md` discrepancy #7).

## Piggybacked signal — the ≤ 3 % budget

The detector reads two owner-written, single-writer, **non-atomic** counter families incremented on the
worker exec path (`src/server.c:22224-22230`), only for an ordinary fake with `argc >= 2` (cross-shard
sub-fakes take an earlier `continue`, so they never reach here — `src/server.c:22205`):

```c
if (fake->argc >= 2) {
    unsigned bkt = (unsigned)fake->tomo_bkt;
    worker->lb_grp_ops[TOMO_LB_GROUP(bkt)]++;                                   /* coarse: one L1 inc */
    uint64_t win = atomic_load_explicit(&worker->lb_fine_win, memory_order_relaxed);
    unsigned fo = bkt - (uint32_t)win;
    if (fo < (uint32_t)(win >> 32)) worker->lb_fine_ops[fo]++;                  /* fine: only if armed */
}
```

- `exThread.lb_grp_ops[TOMO_LB_GROUPS]` — `uint32_t[256]`, one counter per **coarse group** of
  `TOMO_LB_GROUP_BUCKETS = 16384/256 = 64` buckets. Always-on cost: one L1 increment per single-key op
  (`src/server.h:2606`, macros `src/server.h:1578-1580`).
- `exThread.lb_fine_ops[TOMO_LB_GROUP_BUCKETS]` — `uint32_t[64]`, the **armed per-bucket window**, plus
  `_Atomic uint64_t lb_fine_win` packing `(length << 32) | low_bucket` (0 length = disarmed). When
  disarmed this is one relaxed 64-bit load off a hot line plus a never-taken branch
  (`src/server.h:2711-2712`, `src/server.h:1598`).

This is the ≤ 3 % always-on-machinery budget (owner rule, `config.c:3260-3261`): the always-on working
set is the 1 KB group array, not the 64 KB a full 16384-counter table would cost; the 64-bucket window
is armed only where per-bucket resolution can change an answer.

## Sampling and the dual-rate EWMA (`src/server.c:16824-16916`)

```c
int W = atomic_load(&server.num_workers_live);   if (W < 2) return;             /* 16824-16825 */
double alpha = mig_prev_rate_mean / (4.0 * (double)server.reshard_min_ops);
if (alpha < 0.05) alpha = 0.05;   if (alpha > 0.25) alpha = 0.25;               /* 16846-16848 */
double alpha_fast = alpha * 2.0 > 0.95 ? 0.95 : alpha * 2.0;                    /* <= 0.5 (slow cap) */
...
uint64_t ops  = tomoRelaxedRead(server.exThreads[w].ops_total);
uint64_t rate = ops - mig_last_ops[w];                                          /* per-invocation delta */
mig_last_ops[w] = ops;
mig_load_ewma[w]      = primed ? alpha*rate      + (1-alpha)*mig_load_ewma[w]      : rate;   /* 16892 */
mig_load_ewma_fast[w] = primed ? alpha_fast*rate + (1-alpha_fast)*mig_load_ewma_fast[w] : rate;
```

- `rate` is `ops_total - mig_last_ops[w]` — the delta of **invocations since the last sample**, with
  **no elapsed-time division** (`src/server.c:16888-16890`). So `tomokv-key-lb` is compared against
  operations accumulated since the prior sampled invocation, not a normalized rate; the nominal 1 s
  cron only makes it approximately ops/sec when no gate skips invocations (`loadbalance-flip.md`
  discrepancy #8).
- `alpha` self-derives from the workload's own throughput but is **clamped to `[0.05, 0.25]`** so the
  filter always filters (`> 0.25` is a passthrough, `src/server.c:16836-16843`). `mig_prev_rate_mean`
  is last tick's mean, fed forward (`src/server.c:16915`).
- The hot candidate is `argmax` of the **slow** EWMA (`src/server.c:16898`).

Gates before the trigger: `migration_active` (`src/server.c:16810`), `tmFlipActive()`
(`src/server.c:16818`), `num_workers_live >= 2`. Off / no-EX path frees only the four fine-window
allocations and disarms every window; it does **not** free coarse arrays or reset EWMAs/streaks/peak/
settle/diffusion state (`src/server.c:16797-16808`). The first overall sample seeds and returns
(`mig_ewma_primed`, `src/server.c:16917`).

## The coarse/fine profile (`migFineTick`, `src/server.c:16348-16420`)

Level 1 (coarse) rows fold each worker's per-group deltas at the same `alpha`
(`src/server.c:16903-16913`). Level 2 (`migFineTick`) first folds the previously armed window, then
re-points each live worker's window at its hottest owned group. **Arming rule** — a window arms only
when the top group is genuinely concentrated (`src/server.c:16383-16385`):

```text
bar = max( 4 * group_sum / nGroups , 0.05 * group_sum )
arm gtop  iff  group_sum > 0 && top >= bar
```

An armed incumbent is kept (stickiness) when it stays above the bar and a challenger is below `1.25 ×`
it (`src/server.c:16394-16396`). Re-pointing publishes the window first, snapshots raw counters after,
and warm-flags the next fold as a seed (`src/server.c:16401-16408`).

## The outlier trigger (`src/server.c:16929-16997`)

Global slow/fast means and **population variances** over all live worker slots (not per-node):

```c
double k = 0.8 * sqrt((double)(W - 1));  if (k > 2.0) k = 2.0;                  /* 16942-16943 */
double margin = k * sqrt(var / W), floor_m = 0.25 * mean;
hot_bar = mean + (margin > floor_m ? margin : floor_m);                        /* fire bar ; 16944-16945 */
double release_bar = mean + 0.5 * (hot_bar - mean);                            /* Schmitt release ; 16954 */
```

- `k = min(2, 0.8·sqrt(W-1))` — a one-hot vector's max z-score is `sqrt(W-1)`, so a fixed `k` is
  unreachable at small `W`; the `0.25·mean` relative floor stops sigma-collapse on uniform load.
- Both slow and fast distributions get their own bars (`hot_bar`, `hot_bar_fast`).

Exit ladder:

| Gate | Condition | Action | Source |
| --- | --- | --- | --- |
| quiet | `mean < reshard_min_ops` | clear peak/settle, return (streak **kept**) | `src/server.c:16959` |
| balanced | `hotv <= release_bar` | clear peak/settle, decay streak, run diffusion | `src/server.c:16960-16966` |
| band | `hotv <= hot_bar` | hold (streak preserved) | `src/server.c:16968-16971` |
| settle | `mig_settle > 0` | cool down `(int)(1/alpha)+1` ticks | `src/server.c:16975` |
| no-progress | `mig_peak_pre > 0 && hotv > 0.85·mig_peak_pre` | stop chasing | `src/server.c:16978-16979` |
| fastcold | `mig_load_ewma_fast[hot] <= hot_bar_fast` | return, streak **kept** (the `mig_hot_streak[hot]=0` reset at `:16994` is unreachable — the identical guard at `:16983` returns first) | `src/server.c:16983` |
| sustain | `++mig_hot_streak[hot] < K` | not yet | `src/server.c:16995` |

`K = migSustainK(alpha) = max(3, ceil(1/alpha))` — because `alpha <= 0.25`, `K >= 4`
(`src/server.c:16517-16521`, `:16993`). Reaching `K` **consumes** the streak before endpoint/planning
checks (`src/server.c:16996`), so a refused plan re-earns `K` ticks — the backoff for an unbalanceable
hotspot.

Destination = the cooler adjacent live worker in the **same logical node**, strictly below the global
mean (`src/server.c:16999-17015`).

## The planner and the hot-key veto (`migPlanChunk`, `src/server.c:16451-16513`)

Two standard rules, in order:

1. **Split by load, not by size.** Walk the hot shard inward from the shared boundary accumulating
   *measured* per-bucket rate (`migBucketRate`, `src/server.c:16320-16326`), targeting moved load
   `target = 0.5·(Lh - Lc)`, choosing the prefix/suffix that minimises `max(Lh-moved, Lc+moved)`
   (`src/server.c:16501-16509`). The measured profile is trusted only if it accounts for ≥ half the
   shard's rate; otherwise it falls back to uniform density (`src/server.c:16472-16480`). Never takes
   the source's last bucket (`cap = hrange - 1`, `src/server.c:16462`).
2. **Only move if it strictly improves the maximum.** `need_gain = 0.25·(hot_bar - mean)`
   (`src/server.c:17032`); return 0 if `Lh - best_pred < need_gain` (`src/server.c:16511`).

**Hot-key ≠ hot-bucket.** Fed only per-group counts, the accumulator is piecewise-linear and a split
arbitrarily close to `target` always exists, so rule 2 can never fire on a hot key. The armed 64-bucket
window makes the accumulator a **step** function: a lone hot bucket contributes nothing until the scan
reaches it and everything after, so the V's minimum sits just short of it (no gain) or just past it
(the neighbour becomes the new peak) — that is the hot-key signature, and it is what makes the veto
engage (`src/server.c:16439-16445`). On a veto, a **shadow plan** at group-only resolution
distinguishes a fine-resolution veto (`unbal_fine`) from one group resolution would also produce
(`unbal_grp`) — the anti-vacuous check (`src/server.c:17044-17055`).

## Arming the cutover (`src/server.c:17068-17086`)

```c
if (B == hot + 1) { lo = hot_hi - chunk; hi = hot_hi; }        /* right neighbour: move a SUFFIX */
else              { lo = hot_lo;         hi = hot_lo + chunk; } /* left  neighbour: move a PREFIX */
if (reshardArm(lo, hi, hot, B)) {
    reshardBeginCutover();
    mig_peak_pre = hotv;
    mig_settle   = (int)(1.0 / alpha) + 1;                      /* self-derived settle = EWMA τ */
}
```

`reshardArm` serializes publishers, validates adjacency + boundary-aligned subset ownership, refuses to
empty the source (unless a role flip is active), rejects different physical DB pointers (ownership moves
inside one shared kvstore — no key copy), and publishes `migration_active` last (`src/server.c:15525-15622`).
`reshardBeginCutover` CAS-arms the main-thread coordinator (`src/server.c:16147-16181`). The completed
move is not a `reshardKickAfterFlip`; it does not reset the EWMA, so the no-progress guard can judge the
next tick (`src/server.c:17083-17084`).

## Relevel and diffusion (the non-veto paths)

- **`tm_relevel_pending` preempts** the statistical trigger (`src/server.c:16927`). `reshardRelevelTick`
  counts exact per-node table ownership, compares each boundary with an even target, tolerates
  `[-63, +63]` deviation, keeps ≥ 1 bucket on the source, arms at most one range/tick, and clears the
  flag when nothing arms (`src/server.c:16646-16707`). Set after a role flip (`flip-*` docs).
- **`reshardDiffusionPass`** runs from the balanced branch (bimodal skews that read as "balanced").
  Picks the steepest same-node adjacent pair with `hi-lo > 0.25·mean && hi > 0.35·mean`, sustains `K`,
  moves `(Lh-Lc)/(2·Lh)·range_width` buckets floored at 16 and capped near half the source
  (`src/server.c:16720-16766`).

Neither relevel nor diffusion invokes the fine planner or its hot-key veto (`loadbalance-flip.md`
"Relevel and diffusion paths").

## State variables (`src/server.c:16189-16303`)

| Field | Type | Meaning |
| --- | --- | --- |
| `mig_load_ewma[]`, `mig_load_ewma_fast[]` | `double[TOMO_EX_THREADS_MAX]` | slow / fast per-worker load EWMA |
| `mig_last_ops[]` | `uint64_t[]` | previous `ops_total` per worker |
| `mig_hot_streak[]` | `uint16_t[]` | consecutive-outlier counter (AIMD decay) |
| `mig_peak_pre`, `mig_settle` | `double`, `int` | no-progress reference; post-move cooldown |
| `mig_grp_ewma/last`, `mig_grp_rows` | `float*`/`uint32_t*`/`int` | lazily-allocated coarse profile |
| `mig_fine_ewma/last/grp/warm`, `mig_fine_rows` | pointers/`int` | lazily-allocated armed windows |
| `mig_ewma_primed` | `int` | first-sample seed latch |
| `mig_diff_peak/settle/streak[]` | `double`/`int`/`uint16_t[]` | independent diffusion state |
| `mig_trig` | struct | per-gate counters + last-tick signal snapshot (DEBUG RESHARD TRIGGER) |

## Invariants

- Ownership moves inside one shared physical kvstore (adjacency + boundary-aligned subset + same DB
  pointer), never a key copy (`src/server.c:15593-15604`).
- Key-LB returns while a flip or a migration is active; a flip returns while a migration is active;
  `reshardArm` is the final common serialization + range-validity gate (`src/server.c:16810-16818`,
  `:15553-15592`).
- The always-on data-path cost is one L1 increment per single-key op (coarse) plus a never-taken branch
  when the fine window is disarmed (≤ 3 % budget) (`src/server.c:22224-22230`, `config.c:3260-3261`).
- The consumed sustain streak provides `K`-tick backoff before an unbalanceable hotspot is re-tested
  (`src/server.c:16996`).
- The veto's discriminating counter is proven by a group-resolution shadow plan, not assumed
  (`src/server.c:17044-17055`).
