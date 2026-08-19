# flip m1 — the workload-detecting model controller (owner design, 2026-08-19)

Owner: *"have a static table of what each command needs for ex to process relative to each
other as well as pipe or batch amount signal from io. see if we can make a significantly more
accurate controller with those signals."* And: measured steady-state throughput is only
comparable when the workload holds still — on live traffic a throughput delta confounds shape
with workload drift, so the objective-measuring hill-climb (flip-u1-universal.md) is demoted
to a suite-side judge; it does not run in the server. r8 stays the shipping `auto`, untouched.

## Offline validation (done, 2026-08-19 — SP/m1_offline_fit.py)

Model: per node, T(io) = min(io/c_io, ex/c_ex). Fit (c_io, c_ex) per workload to the
flip_landing static refs (3-4 shapes per workload, 11 workloads):

* Picks: 9/11 EXACT vs discovered best, 11/11 within ±1, every pick ≥0.95× best
  (mean 0.993, min 0.951). r8's landings on the same cells: 3/11 exact, mean 0.894, min 0.696.
* Fit rmse 0.3-5.8% — two numbers explain each whole shape-throughput curve.
* SEPARABILITY (the table premise): ex cost is command-keyed and pipe-invariant
  (GET 0.95/0.76/0.75us across p1/p16/p32; SET 1.35/1.33/1.32us). io cost is pipe-keyed and
  command-invariant (~12us p1 -> 1.7us p16 -> 1.3us p32; GET-vs-SET within 5% at every pipe).
* COMPOSITION: mix19 fitted ex 0.82us vs table-weighted 0.9xGET+0.1xSET = 0.817us (<1%).
  Observed mix x table = mix cost; no per-mix calibration.
* Cross-instrument: fitted io p16 1.67-1.71us vs 1.76us from perf time-splits; ex GET 0.76us
  matches bound-cell derivation; uring p1 io 12.1us < epoll 13.4us matches +4.4% uring p1.

Seed table (16c EPYC, d32, cache-resident; per-op us):
  ex: GET 0.76, SET 1.33, MGET8 8.4, MSET8 10.1, ZRANGE(64) 4.3
  io(pipe): p1 ~11.8 (uring) / 13.4 (epoll), p16 ~1.7, p32 ~1.3  [interpolate log-linear in
  batch depth; MGET8/MSET8 carry an io surcharge — fitted 14.0/11.3 at their pipe — so the io
  table needs a per-command bytes/args term, phase 2]

## Architecture

1. SIGNALS (io side, within the 3% law):
   * per-io-thread command-class counters (one increment at dispatch; classes = table rows +
     OTHER bucket),
   * batch-depth EWMA: commands consumed per drain pass per io thread (the pipe signal),
   * optional bytes-in/out per class (phase 2, for the per-byte io term).
2. TABLE: per-command ex cost + io cost curve keyed by batch depth. Sources, in order:
   (a) seed constants from this doc; (b) `make caltable` auto-calibration battery (bound-cell
   micro-runs, emits the table; gate spot-checks freshness); (c) sampled live self-measurement
   — rdtsc on 1/256 ex commands, EWMA per class (per-op timing on EVERY command was the
   measured reorder tax; 1/256 sampling is noise). (c) absorbs value sizes, DRAM-bound cost
   inflation, and every ex-side code change — the owner's stated maintenance downside.

   CONFIG-AWARENESS (owner: "config aware, workload aware"): workload-aware = the detection
   side (mix + batch depth, observed); config-aware = the table VALUES are bound to the
   running config while the STRUCTURE is universal. Boot-knowable axes are columns: backend
   (uring/epoll io anchors, measured 11.8 vs 13.4us at p1), atomics (write surcharge column:
   measured ON tax ~30% deep-pipe / ~6% p1 / 0% reads), stage structure (2s fused-io column
   vs 3s ifid+wb columns — same lattice math, K roles). Continuous axes (value size, DRAM-
   boundedness, NIC interrupt load, future hardware) are never hand-enumerated: source (c)
   collapses them all into measured service times of the current config — and the io side is
   self-measured the same way (rdtsc-sampled ~1/64 drain passes -> io us/op), so on a NIC box
   the anchors retire and the controller runs entirely on measured costs. One lookup function
   (role, class, nkeys, depth) is the only place config axes exist.
3. TARGET: per node at the 4Hz tick: mix vector m (node-local, decayed), batch depth p ->
   c_ex = sum(m_i * ex_i), c_io = io(p) [+ bytes term] -> io* = N * c_io_rate/(...) i.e.
   io*/ex* = c_io/c_ex; round both ways, pick the better under min(); clamp to lattice.
4. HYSTERESIS: actuate only when the computed target differs from current by >=1 step for a
   sustained run of ticks (reuse u1a sigma machinery on the INPUT signals — mix/depth noise —
   so the threshold is measured, not a machine constant). Zero moves while the target is
   stable = thrash-clean by construction.
5. SHADOW MODE FIRST (this round): compute + trace only ([m1-trace nX] mix= depth= c_io=
   c_ex= target=ioT/exT current=ioC/exC), DEBUG TOMO-M1TRACE <0|1>, INFO gauges. r8 decides;
   m1 predicts. Validation = run the 11 cells, compare m1's logged target vs discovered best
   (offline says 11/11 gate-green) and vs r8's landing, live.
6. ACTUATION (next round, new mode `tomokv-thread-mode model`): computed target drives the
   EXISTING actuator (tmFlipDo staged conversions). r8's decision stack untouched.
7. STALE-TABLE ALARM: load signals demoted, not deleted — computed-balanced but one stage's
   queue/occupancy persistently pegged while the other idles => table wrong: log + INFO flag;
   in sampling mode it self-corrects. The load signal never overrides the computed target
   silently (single authority; no dual-controller thrash).
8. 3s: three-stage min() with wb cost keyed by reply bytes/op — same machinery, K roles.

## Comparison record (owner asked: load-only vs workload-detecting)

Load-only (r8): no table, no maintenance, handles unknown commands — but the signal ALIASES
mixes (p16 GET vs p16 MSET both read "busy everywhere", optima io11 vs io8), needs a
machine-specific mapping (broke on every hardware change), searches with transients, and its
equilibrium is not the throughput optimum (measured: mean 0.894, min 0.696).
Workload-detecting (m1): computes the target directly (no search, instant retarget on mix
change, thrash-clean), disambiguates what load aliases, composes mixes linearly, per-node
mixes -> per-node splits, extends to 3s; costs: the table (auto-calibrated or self-sampled),
an OTHER bucket for unknown commands (live-sampled), and model risk where stages couple
(min() ignores overlap — measured residual 0.3-5.8% on these cells; value-size term phase 2).
