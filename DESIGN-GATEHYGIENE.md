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
## 4. Audit — every other assertion of this class in `tests/`

Swept all 125 files under `tests/` plus `gate.sh`. "MECHANISM" means the timing or statistics only
*deliver* the mechanism and the assertion is still true on an arbitrarily slow machine. "PERF" means
the assertion is false when the box is slow or loaded even though the code is correct.

**None of these were changed by this lane.** They are listed so the next lane can pick them up in
priority order; the three above were the ones actually reddening runs.

### The one structural finding: what runs twice

`tests/gate.sh` runs exactly **five** batteries in the release tier and again under ASAN. An ASAN
re-run is where a ratio inverts (the sanitizer does not slow both arms of a ratio equally, and it
inflates every allocation footprint):

| battery | release | ASAN | exposure |
| --- | --- | --- | --- |
| `torture.py` | `:375` | `:1233` | mild — only `landed > 0` (`:117`) |
| `ryow.py` | `:377` | `:1235` | none — no timing or statistical assertion |
| `atomic_torn.py` | `:402` | `:1237` | **highest unmitigated risk** — five race-window-hit rows |
| `atomic_ryow.py` | `:404` | `:1246` | **fixed by this lane** (`--no-rate-assertions`) |
| `zc.py` | `:1286` | `:1291` | none |

`atomic_torn.py` is the one to do next. `:877` (`atomic_window_stalls` must advance out of a
64-frame burst against a 2-deep window) and `:940` (`atomic_inflight` must be seen `<= 3` within 3 s
and then stay there across a 0.4 s poll) are the two most likely to invert under ASAN. `:695`,
`:696`, `:697` are race-window-hit gates whose cold path the file itself already gives a 1.5 s retry
loop.

### Class A — rate assertions

| file:line | assertion | verdict |
| --- | --- | --- |
| `atomic_ryow.py:256` | `pipe_rate > serial_rate * 1.10` | PERF — **fixed**, now behind `--no-rate-assertions` |
| `borrow_registry.py:261` | `growth <= 1.05` | PERF — 5% budget on a wall-clock ns/op ratio |
| `borrow_registry.py:263` | `control <= 1.05` | PERF — the file's own skip path at `:247` exists because this fires on environment drift |
| `borrow_registry.py:265` | `borrow_ref > plain_ref * 1.5` | PERF — and *not* covered by that skip, so it scores even when the instrument was disowned |
| `expireindex.py:179` | `growth <= 8.0` | PERF — ratio of two `perf_counter_ns` medians |
| `expireindex.py:224` | `ratio <= 1.25` | PERF — tightest ratio bound in the tree, on two DEL timings µs apart |
| `infofix.py:273,285` | `instantaneous_ops_per_sec == 0` | PERF — a sampled EWMA asserted to be exactly zero |
| `infofix.py:282` | `instantaneous_ops_per_sec > 0` after a burst | PERF — the burst must land inside the sampler's live window |
| `xacct.py:117` | `stream_ratio < 4.0` | PERF — 4x budget on a sub-µs op |
| `xacct.py:166` | `multi_ratio < 15.0` | PERF — empirical, not proved |
| `xmove.py:231` | `ratio < 5.0` | PERF — asserts O(1) by timing rather than by a counter |
| `xshard_dispatch_scale.sh:123` | `se > 0 and be > 0` | PERF — a *sign* test on a difference of two medians |
| `xshard_dispatch_scale.sh:127` | `ratio <= limit` | PERF — ratio of differences of medians across two boots |
| `gate.sh:919` | `MM_RATE >= 120000` | PERF — but deliberately a 5x-margin **floor** (healthy ~600k, the regression class lands under 70k) and documented as such. Keep. |
| `gate.sh:1395,1397` | `d >= -3.0` vs `gate_refs.txt` | PERF — NIC cells against refs the file itself flags as pinned on a different kernel |

### Class B — duration assertions

Safe lower bounds (MECHANISM — a slower box only overshoots): `blocking.py:143`,
`blockmulti.py:212`, `climon2.py:377`, `debug.py:108`, `evict_battery.py:256,280`,
`expwide.py:255,366,413,503`, `lbsignals.py:91,147,157,208` (60 s ceilings), `spinprobe.py:200`,
`stream.py:253`.

Ceilings that are performance claims:

| file:line | assertion | note |
| --- | --- | --- |
| `blocking.py:138,153` | `elapsed <= 0.75` | the 0.10 floor is the mechanism; 0.75 fails if the executor heartbeat is delayed |
| `blockmulti.py:137,165` | `elapsed < 0.25` | proves "non-blocking" by wall clock instead of by a counter |
| `blockmulti.py:190` | `elapsed < 0.10` | 100 ms for one satisfied `WAIT 0 500` |
| `blockmulti.py:200` | `elapsed <= 0.90` | observed ceiling |
| `blockmulti.py:229` | `elapsed < 0.25` | `WAIT` inside EXEC |
| `bplus.py:366` | `COMMIT_CHECKPOINT_BUDGET` 0.60 s | called "deterministic budget"; it is wall clock |
| `climon2.py:305` | `len(lines) >= 4` from `drain(0.6)` | a count out of a fixed window |
| `climon2.py:373` | `read_ms < 250` | a slow GET reads as a pause bug |
| `climon2.py:390` | `released_ms < 2000` | window spans two sleeps and two admin round trips |
| `execatomic.py:289`, `execiso.py:372` | `elapsed < HOLD_US / 4e6` | the *unarmed* control must finish in a quarter of the park budget |
| `limits.py:284` | `elapsed <= 3.5` | observed reaper-latency ceiling |
| `netio.py:218` | `worst < 25 ms` | a p100 doorbell-wake bound; one descheduled io thread in 20 rounds fails it |
| `read_local_lane.py:147` | `slow < 20.0 s` | generous, still a ceiling |
| `slowlog.py:154,263` | `< 400 ms` / `< 400` | the floors are mechanism, the ceilings are measured bounds |

### Class C — counts from sampling

| file:line | assertion | note |
| --- | --- | --- |
| `edgetime.py:707,750,753` | exact 8/8 present, 0 nils in 200 rolls, inverted repro detector | PERF — one unlucky roll flips the verdict |
| `evict_battery.py:202,209,212,234,236,283,319,325,328` | the lfu/lruclock survival, FREQ-band and lane-hit-rate rows | PERF by shape, but **each is now deterministic by construction and states its bound** (`61c0a0416`; see section 3) |
| `evict_battery.py:134` | `live < CEILING * 5 // 4` | MECHANISM after this lane — the gap is 8.4k vs 14k offered |
| `evict_battery.py:160,162` | `soon < 50`, `soon < late` | PERF by shape; relative, with the non-vacuity companion added by this lane |
| `expireindex.py:243` | `live >= n * 0.9` | 90% threshold on a population racing its own 3 s TTLs |
| `expireindex.py:250` | `moved >= n * 0.99` | the active/lazy reap split is sampled; 0.99 came from observation |
| `lru_slow.sh:55` | `hot > cold` | pure victim-sampling comparison, no non-vacuity floor |
| `multi_exec.py:391` | `reads > 100 and commits > 10` | op-count floors out of a fixed wall-clock window |
| `notify.py:499` | eviction must notify within 64 SETs | depends on the sampler picking a victim in 64 tries |
| `read_local_lane.py:162,174` | `>= 0.95 * gets` lane hit rate | the file's own header warns the lane loses a rate race against the drain |
| `session_monotonic.py:243` | `len(span) >= 2` | a geometry precondition drawn from the kernel's per-boot hash seed |
| `snap_cut_battery.py:248,250` | `writes > 10000`, `reads > 200` | absolute counts from a fixed-duration storm; an ASAN box cannot reach them |
| `stream.py:312,328` | byte deltas and `per_stream < 512` | inverts outright under ASAN redzones |
| `torture.py:117` | `landed > 0` | MECHANISM — only a total loss fails it |

### Class D — scheduling outcomes

The densest file is `flipctl.py` itself (14 rows). Beyond the stable hold this lane fixed, the
remaining ones are the `wait_for(..., 30/60/90)` bounds where the timeout *is* the discriminating
property (`:301`, `:339`, `:465`, `:476`, `:499`), the two `sleep(8)` "settled and held" windows
(`:483`, `:502`), the exactly-one-trigger claims (`:312`, `:465`), the ramp row (`:293`) and the
off-rail anchor (`:315`). `:268` (an idle server starts no maneuver) is a genuine mechanism check.

Race-window-hit gates — rows that fail when scheduling luck did **not** open the window they need,
i.e. the vacuity guard is itself a timing assertion:

`aof_frame_order.py:213`, `atomic_torn.py:695,696,697,877,940`, `edgetime.py:710`,
`execatomic.py:246`, `execiso.py:292,346`, `expwide.py:365,412`, `flip_under_load.py:291`,
`multi_exec.py:391`, `multirace.py:443,467`, `multires.py:298`, `read_local_lane.py:160`,
`session_monotonic.py:316,325`, `snap_cut_battery.py:258`, `snap_typed_race.py:237`,
`watchlive_gate.sh:115,120`, `gate.sh:871` (three FLIPs must each APPLY under memtier saturation —
the exact outcome `flip_under_load.py` counts as a legal refusal).

Budget-style scheduling rows: `debug.py:101,118,126` (300 ms), `lbsignals.py:106,138,139,153,156,160`
(counter-moved-by-at-most-N and counter-did-not-change while load ran), `spinprobe.py:184,224,271`
(no role change in a quiet window; <=64 loop iterations per idle second; <=24 iterations attributed
to one parked partial frame — its own 3-attempt retry loop at `:241` exists because it is
scheduling-sensitive).

Genuine mechanism checks in this class: `debug.py:191,193`, `differ_gate.sh:263`,
`lbsignals.py:101`, `multirace.py:474`, `notify.py:188,520,596`, `snap_typed_race.py:227`,
`xacct.py:163`.

### Clean

The six `.cc` unit tests (`flipctl_unit`, `cmdlookup_unit`, `read_local_ring_unit`,
`read_local_write_ring_unit`, `foreign_read_safety_test`, `config_parser_test`) use no clock, no
threads and no sampling. `benchfeat.py`, `broaden_bench.cc` and `matrix.sh` are pure reporters and
assert nothing on a measured quantity.

---

## 5. Row count

Unchanged: `EXPECT_QUICK=324`, `EXPECT_FULL=340`. No row was added or retired — `atomic_ryow.py`
splits one `note()` into two *inside* one battery, which is one gate row either way, and the
flipctl stable hold is one sub-assertion of one gate row.
