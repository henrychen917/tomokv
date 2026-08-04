# Flip controller: rate-balance saturation, and a computed target instead of a search

Status: SPEC, not implemented. Supersedes the pressure term in task #74 and removes the
throughput hill-climb that #74 is a bug in.

## 0. Why

Today `io_sat = io_busy_mean/75` is **utilization only**, `ex_sat = max(busy/75, qd/(8·POP))` is
utilization **or** backlog, and `imbalance = io_sat − ex_sat` is trusted only to pick a *direction*.
Magnitude comes from a throughput hill-climb against `best_rate`, which never re-baselines — see
#74, where a climb started mid-workload-transition latched a peak from the departing load, walked
back, and pinned the deadzone so the actuator could never fire again.

Two independent defects, one cause: **utilization saturates at 1.0 and then carries no more
information.** A thread 100% busy keeping up is indistinguishable from one 100% busy and falling
behind 3×. Because the signal cannot express "how far behind", magnitude had to come from
somewhere else, and the somewhere else was a search with a latch in it.

A rate-balance signal does not saturate, so the target can be **computed** and the search deleted.

## 1. Roles

Every stage is a queueing station. `r ∈ {IFID, EX, WB}`:

| role | intake | output |
|---|---|---|
| IFID | commands parsed off the socket | commands dispatched to a worker |
| EX   | commands pushed to `exQueue`   | commands retired |
| WB   | replies ready to send          | replies written to the socket |

The stations are a chain, which gives two identities for free — and two consistency assertions:

```
C_IFID ≡ A_EX          C_EX ≡ A_WB
```

so the instrumentation is 4 counters, not 6.

**2-stage vs 3-stage.** In the 3-stage fork IFID and WB are separate thread roles and this applies
directly as a 3-way split. In this (2-stage) tree one thread does both, so they are measured
separately but sized together — see §5.

## 2. Per-tick measurement

Window `Δt` (one controller tick, 250 ms). Per role, per node:

```
A_r   items entering r during Δt
C_r   items completed by r during Δt
Q_r   standing queue depth at tick start
U_r   mean utilization of r's threads   = Σ busy_µs / (N_r · Δt_µs)   ∈ [0,1]
N_r   threads currently in role r
```

`U_r` already exists on both sides (`tm_busy_us`, published once per pass — same mechanism, no new
cost model).

## 3. The equation

Measured per-thread capacity, self-calibrating, no constants:

```
μ̂_r = C_r / (U_r · N_r)          items per thread-second at 100% busy
```

Work presented in the window is arrivals plus what was already owed:

```
S_r = (A_r + Q_r) / (μ̂_r · N_r · Δt)
```

Substituting `μ̂_r`:

```
┌──────────────────────────────┐
│  S_r = (A_r + Q_r) · U_r / C_r │
└──────────────────────────────┘
```

Three counters and a utilization. Dimensionless, comparable across roles, **unbounded above**.

### Sanity table (the reason it is better)

| situation | A | C | Q | U | S | utilization would say |
|---|---|---|---|---|---|---|
| idle | 100 | 100 | 0 | 0.10 | **0.10** | 0.10 |
| at capacity, keeping up | 100 | 100 | 0 | 1.0 | **1.00** | 1.00 |
| standing 8-deep queue | 100 | 100 | 8 | 1.0 | **1.08** | 1.00 |
| open-loop overload | 140 | 100 | 40 | 1.0 | **1.80** | 1.00 ← blind |
| closed-loop, bad config | 100 | 100 | 50 | 1.0 | **1.50** | 1.00 ← blind |

The last row is the one that matters for us. **Nearly all our benching is closed-loop** (memtier,
fixed conns × pipeline): arrivals are gated by completions, so `A/C → 1` at equilibrium *by
construction*, in a good config and a bad one alike. A pure `λ/μ` ratio would read balanced and
tell us nothing — this is almost certainly why throughput crept in as the driver. The `+Q` term is
what restores discrimination there, because a bad config shows up as **standing backlog** at the
same throughput. Under open-loop or a real client fleet the ratio term carries it instead. One
equation covers both regimes; neither term alone does.

## 4. Target allocation — computed, not searched

Demand in thread-equivalents, then proportional allocation:

```
D_r  = S_r · N_r
N_r* = clamp( round( N_total · D_r / Σ_s D_s ),  1,  N_total − (roles−1) )
```

`S_r = 1.0` means "exactly saturated", so `D_r` is literally "thread-seconds of demand per second".
Equalizing `S` across roles is the definition of a balanced pipeline, and proportional allocation
achieves it in one step. **This is the whole point: no `best_rate`, no probe, no walk-back.**

Capacity is not perfectly linear in `N` (contention, NUMA, cache), so the target is a *direction
with a magnitude*, not a jump — see the control law.

## 5. The IO split (IFID vs WB)

IFID and WB contend for the same thread-seconds in 2-stage, so their demands **add**:

```
S_IO = S_IFID + S_WB          D_IO = S_IO · N_IO
```

and the 2-way io/ex allocation of §4 runs on `D_IO` vs `D_EX`.

Keep the split even though it is not separately actuable here, because it is the *diagnosis*:

- `S_WB ≫ S_IFID` → send-bound. Matches the measured behaviour that more WB threads scale 3-stage
  **up** on large values while 2-stage scales **down** with threads.
- `S_IFID ≫ S_WB` → dispatch-bound, the small-value regime.

In 2-stage both point to the same actuator (add an IO thread, it serves both halves). In 3-stage
they point at *different* actuators, and the same numbers size WB directly. Logging the split now
means the 3-stage port needs no new signal work.

## 6. Control law

Replaces START/GAIN/COAST/OVERSHOOT/walk-back/deadzone-raise entirely.

```
every tick:
    if Σ C_r == 0: return                        # idle guard (existing node_idle)
    if flip in flight: return                    # existing CAS gate
    for r: S_r = (A_r + Q_r) · U_r / C_r
           S_r = ewma(S_r, α)                    # α = FESC_ALPHA (0.25), same as today
    compute N_r* per §4
    e_r = N_r* − N_r
    r_hi = argmax e_r ;  r_lo = argmin e_r

    if max(e) ≥ 1 + h:                           # h = 0.25 dead band, anti-chatter at the
        sustain++                                #     rounding boundary
    else:
        sustain = 0

    if sustain ≥ M:                              # M = 3 ticks, Schmitt
        flip ONE thread r_lo → r_hi
        sustain = 0
        wait FLIP_WAIT_KEEP ticks                # existing post-flip transient wait
```

Properties, stated so they can be tested:

- **Self-rebaselining.** A load change moves `A`, `C`, `Q`; `S` follows within the EWMA horizon;
  the target moves; the controller follows. There is no latched peak, so #74's failure mode is not
  representable.
- **No lockout.** Nothing raises a deadzone. Hysteresis is `h` + `M` on a *physical* quantity,
  not a widening band around a searched optimum. The controller cannot disable its own actuator.
- **Bounded motion.** One thread per `M+WAIT` ticks, and the target is recomputed from scratch
  each tick, so overshoot self-corrects on the next tick instead of needing a walk-back.
- **Maps to the stated intent** ("flip till stable, flip back once up thresh"): stable is
  `max|e| < 1+h`; the flip-back is automatic and needs no separate rule.

## 7. Instrumentation

New, all monotonic per-thread counters, published once per tick alongside the existing
`tm_busy_us`:

| counter | role | note |
|---|---|---|
| `n_cmd_parsed`    | IFID | A_IFID |
| `n_cmd_dispatched`| IFID | C_IFID ≡ A_EX |
| `n_cmd_retired`   | EX   | C_EX ≡ A_WB — `exQueue.retired` already tracks this |
| `n_reply_written` | WB   | C_WB |
| `busy_ifid_us` / `busy_wb_us` | IO | **split** the existing `tm_busy_us`, not a new probe |
| `Q_WB` | WB | reply backlog (count or bytes) |

`Q_EX` already exists (`qd_max`). Net: 4 new counters, one existing busy counter split, one new
depth.

**Cost.** These are per-command increments on the hot path, so: thread-local, non-atomic,
plain `++` on a cacheline the owning thread already writes, published once per tick by the same
release-store mechanism `tm_busy_us` uses. No shared counters, no RMW. This must land inside the
**≤3% always-on budget**; measure it with the LB knob off vs on before keeping it, and if the
increments alone cost more than that, sample every Nth command rather than accepting the tax.

## 8. Migration and validation

1. Land the counters and **log** `S_r` per role beside the current `io_sat`/`ex_sat` — decide
   nothing yet. One run tells us whether `S` and the old signal even agree in sign.
2. Verify the pipeline identities hold (`C_IFID == A_EX`, `C_EX == A_WB`) as a correctness assert;
   a mismatch means commands are being lost or double-counted.
3. Only then switch the decision over, behind the existing thread-mode knob.
4. Acceptance is the three cells that #74 currently fails — `AUTO==STATIC-p1`, `SHIFT-exward`,
   convergence — plus the p1/p32 static curves the cell measures for itself. A fix must show
   `S` re-baselining across the stimulus change, which is exactly what `best_rate` never did.
5. Per the three-regime rule: check predicted-benefit (send-bound, large values), neutral
   (small-value dispatch-bound), and predicted-deficit regimes and decide from the *pattern*.
   Winning everywhere would mean the stated mechanism is not what is producing the win.

## 9. Open questions for the owner

- `h` and `M` are the only two tuning constants left. Both are anti-chatter, not policy. Candidates
  for self-derivation from the observed noise in `S` (`h ∝ σ_S`), which would leave the controller
  with **zero** hand-set numbers.
- Whether `Q_WB` should be counted in replies or bytes. Bytes is the honest unit for a send-bound
  stage; replies is cheaper. Start with replies, revisit if the split diagnosis looks wrong at
  16–64 KB values.
- 2-stage cannot size IFID and WB independently. If the split shows they routinely disagree, that
  is a concrete argument for the 3-stage line rather than a controller change.
