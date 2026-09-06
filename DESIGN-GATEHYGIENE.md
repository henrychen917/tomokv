# Gate hygiene: the rows that assert a timing or statistical property

Branch `t-gatehygiene`, from `ceb6b02f8` (train 13).

Three full-gate rows reddened intermittently on a correct build. None of them had a wrong
mechanism; each asserted a **timing or statistical** property alongside (or instead of) the
mechanism it exists to protect, and so measured the box rather than the server. The finals depend
on a gate that is trustworthy, which means a red row has to mean a defect.

The rule this lane applies:

> A row may *use* timing to deliver a mechanism. It may not *assert* timing unless the assertion
> is still true on an arbitrarily slow machine, or the row states and enforces the precondition
> that makes it true and refuses to be judged when that precondition is unmet.

---

## 1. `tests/atomic_ryow.py` — "cross-key atomics on one connection overlap"

### The defect

One `note()` bundled two different kinds of claim:

```python
note("cross-key atomics on one connection overlap",
     overlap_ok and stall_after > stall_before and pipe_rate > serial_rate * 1.10, ...)
```

* `overlap_ok and stall_after > stall_before` is a **mechanism** claim. 24 cross-key atomic groups
  pipelined on one connection are all admitted and answered `OK`, and `atomic_window_stalls`
  *moves* — which is only possible if a younger group was in flight while an older one was still
  deciding. The regression this section exists for (a return of the full connection barrier) makes
  `stall_after == stall_before` on any build at any speed.
* `pipe_rate > serial_rate * 1.10` is a **performance** claim. It is false on a correct build
  whenever the two arms are not slowed by the same factor.

The full gate runs this file a second time under ASAN. The sanitizer does not slow the pipelined
arm and the serial arm equally, and the ratio inverts: the gate measured **pipe 21,005/s against
serial 24,202/s** and reddened the row while every correctness check in that same run passed. The
same build passed 4 of 4 standalone.

### The fix

The two claims are two `note()`s. The mechanism half runs on **every** tier. The rate half runs
only when the caller says the server is a release build — `tests/gate.sh` passes
`--no-rate-assertions` on its ASAN row (`tests/gate.sh:1246`).

An **explicit flag**, not a sniffed `GATE_TIER` environment variable: a battery run by hand then
does what it was told rather than what it guessed about its server. When the flag is present the
row prints `SKIP` with the reason **and the measured rates**, so the number stays in the log on
both tiers.

---

## 2. `tests/flipctl.py` — "stable hold"

### The defect

```python
raise AssertionError("controller moved during stable hold: %r" % row)
```

The row asserts that the automatic FLIP controller does not move during a 30 s hold. It failed
about **one full-gate run in five** on the shipped controller, always straight after the long
torture and ASAN phase, and passed **6 of 6 interleaved** on both the shipped controller and the
redesign in a quiet window. So the trigger is the gate's own sequence, not the controller.

The row's claim is about the **controller**, and it is only about the controller if the offered
load really was stationary. The row assumed that instead of measuring it, and had no way to tell a
real move from a driver artefact after the fact — the failure text was one `INFO FLIPCTL` dict with
no trigger reason and no history.

### The fix (test side only — the controller is untouched; a separate lane owns it)

The row now **states its precondition and enforces it**.

* The driver counts **its own** completed commands (one single-element counter per worker), not the
  server's `total_commands`, which also counts this script's `INFO` polls.
* Each attempt spends `PRE_HOLD_SECONDS` (8 s) measuring that rate and replays the controller's own
  anchored rate rule over the trace — `rate_rule_fires()` mirrors `sample_anchored_rate()` plus the
  surge/collapse streaks in `src/core/flipctl.cc`: adjacent one-second tick windows average into
  one reading, a reading is out of band when it leaves `reference * (1 ± band)` where `band` is the
  band the controller itself reports (`flipctl_rate_band`), and a maneuver needs **two consecutive**
  out-of-band readings. Only a stationary pre-hold window opens the assertion window.
* **A move while the load is provably stationary still FAILS**, and the failure now carries
  `flipctl_last_trigger`, the controller's own `DEBUG FLIPCTL` dump taken **at the move**, the
  driver's per-second rates, and the per-second live-split trace — so a real move is
  distinguishable from a driver artefact in the log, without re-running anything.
* A hold whose load left that band is **re-rolled**, up to 3 attempts inside a wall budget, and then
  **SKIPPED** with every number printed. A row must not go red for something the driver did on a box
  that was busy elsewhere.

The surge phase's counters are re-read at the end of the hold instead of being assumed to sit at
their boot values: a re-rolled hold may legitimately have spent a rate trigger on the driver's own
wobble, and the surge phase's claim is about the **delta** the surge produces.

`tests/gate.sh` gives the row 480 s rather than 300 s. The typical run is unchanged; the worst case
adds three re-rolls and their re-anchor waits.

---

## 3. `tests/evict_battery.py` — the survival rows

### Verified present on this base

Commit `61c0a0416` ("evict battery: make the two survival rows deterministic, and name the property
that made them flake") is in `ceb6b02f8`. Both survival rows are exact assertions and both state
the property they prove:

* `lruclock` pins `maxmemory-samples 64` for the section (`tests/evict_battery.py:227`) **and says
  why that is a pure gain under LRU and would be the opposite under LFU** — sampling a candidate
  under LRU only reads its clock byte, sampling one under LFU *decrements* its counter
  (`flatstore.h choose_victim`), because five header bits leave no room for a wall-clock decay.
* `lfu` deliberately does **not** pin it, carries a `DO NOT "fix" a flake here with CONFIG SET
  maxmemory-samples 64` comment with the measurement behind it (4/20 survivors at samples=64 with
  burst reads, against 17-20 at the default 5), and instead made the row deterministic by reading
  the hot set **through** the pressure rather than in a burst before each fill.
* Each survival row is now paired with a directly-asserted bound that names the mechanism: the hot
  median `OBJECT FREQ >= 8` against a cold ceiling of 6 (`:185`), and `untouched < re-read` with an
  absolute companion (`:301`).

### The other sampling rows in the same file, given the same treatment

Neither is a gate row today (the gate runs only the `lfu` and `lruclock` sections), but both
asserted a count out of a sampled victim choice:

* `lru` — `check("allkeys-lru: plateau near ceiling (<10k of 14k offered)", dbsize() < 10000)` used a
  constant somebody measured once, and sat next to `check("allkeys-lru: writes keep landing past
  limit", True)` — literally the constant `True`, a row that could not fail. Replaced by an
  **identity** (`live + evicted == offered`, exact: `fill()` does not tolerate OOM, nothing carries
  a TTL, no key is written twice) plus a plateau bound **derived from `MM`** rather than observed.
* `vttl` — `soon < late` is already the right *form* (relative, no magic constant, inverts outright
  if the policy stops preferring the nearest expiry). What it lacked was the non-vacuity companion:
  if the pressure never reached the `soon` bucket both counts would sit at 50 and the comparison
  would be deciding on noise. Added `soon < 50`.

---
