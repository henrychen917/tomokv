---
name: thredis-bench-suite-comparison
description: "bench_suite cross-system comparison harness ($J/bench_suite): how to run it (sweep_run.sh+watchdog+analyze), the 5 box-specific harness fixes needed to get valid rows on the 7700X, and the fair-comparison decisions (fixed keycount, enforce=0, perf event set)."
metadata:
  type: reference
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Codex-built comparison harness at `$J/bench_suite` (compares tomokv/redis/dragonfly/garnet via
memtier/zipf/ycsb/traces). Runs the real matrix; produces per-cell CSV rows with ops/s + ipreq + ipc.
Baselines on box: Dragonfly v1.39 `/shared/Projects/dragonfly-bin/dragonfly`, stock Redis
`/shared/Projects/redis/src/redis-server`, YCSB `/shared/Projects/YCSB` (+ java21, mvn, redis module,
setsid — gate jar needs `make_ycsb_gate.sh`). TomoKV binary = the finalmerge fork.

# How to run (this session's driver scripts, all in $J)
- `sweep_run.sh` — priority-ordered segments, ONE `runner.sh` invocation each, streams to
  `$J/SWEEP/<seg>/<run>/results.csv`. 8GB DB, atomic=off (fair), memtier→zipf→ycsb. Writes
  `SWEEP/sweep.pid`. Segments: s1 headline d32 get_set (cross-system money shot) → s2 io/ex static
  sweep (TOMOKV_STATIC_IO=1..7) → s3 d1024 → s4/s5 mget_mset → s6 zipf → s7 ycsb.
- `watchdog.sh` — tracks sweep.pid; if newest-CSV-rows + sweep-log-mtime + newest-cell-dir all static
  for STALL_S=900s, `pkill -9 -x` the hung server/driver so bench fails→retries→advances. MUST kill
  `redis-tomobench` too (TomoKV's alias comm) not just redis-server — see [[thredis-ab-harness-traps]].
- `monitor.sh` — one oversight interval: exits (notifying) on segment-done / failure-spike(>=6) /
  watchdog-wedge / sweep-end / 25min. Re-arm each notification.
- `analyze_sweep.sh` — merges all segment CSVs → master.csv + cross-system pivot + io/ex curve + flags.

# The 5 box-specific harness fixes (all "harness bug → fix + continue", none server bugs)
1. **Stale memtier-lifecycle** — codex's zero-warmup source change stales the built binary; the driver
   rejects it. Rebuild: `rm -rf build/memtier-lifecycle && bash make_memtier_lifecycle.sh` (it
   fail-closes if the dir exists). zipf REUSES this binary (memtier Zipfian `Z`); no separate gate.
2. **Boot argv-proof impossible** — Redis rewrites argv via setproctitle() at startup, so
   `/proc/PID/cmdline` = `redis-server host:port` and the `--tomokv-thread-io 4` grep finds 0.
   FIXED (tomokv.sh `tomokv_assert_boot_argv`): if no `--` tokens survive, SKIP argv proof, defer to
   the live CONFIG readback (which proves the io4/ex4 boot split via the applied-split log grep).
3. **perf capture too strict** — 3 PMU events UNSUPPORTED on this 7700X: **LLC-loads, LLC-load-misses,
   stalled-cycles-backend** (perf keeps the process alive but never creates a perf_event fd). Codex
   made perf/controller NON-FATAL (cells go PARTIAL, throughput always recorded) AND reclassified
   live-without-fd collectors at the attach deadline as unavailable→NA + skip them in the enable
   barrier. Result: the 12 supported events (incl instructions+cycles) work → **ipreq+ipc numeric**.
   ipreq=instructions/driver_completed_ops (TomoKV INFO commandstats omits EX-worker exec → driver
   count is the fallback denominator). converge_time/stable_throughput still land NA (trajectory
   sampler needs more than the window gives) — flip cost is DERIVABLE as auto-overall vs static-best.
4. **LOAD PROOF too strict** — harness loads a FIXED keycount `8GB/(value+46)` (~110M keys at d32,
   system-agnostic = FAIR identical workload) then failed if used_memory outside ±35%. Real KV
   overhead varies 2x (TomoKV ~109B/key→12GB at d32, Redis more, Dragonfly less) so no window works.
   FIX = `LOAD_ENFORCE_MEMORY_TARGET=0`: drops only the memory-WINDOW gate (load.sh:100); the
   dbsize==keycount correctness check (load.sh:54, guards the [[thredis-hitrate-benching-trap]]) stays
   enforced; real used_memory recorded as a warning. Fixed keycount + report per-system memory = the
   defensible standard.
5. **watchdog missed redis-tomobench** (fix 4 above under watchdog.sh).
6b. **STATIC idle EX workers busy-poll** — in thread-mode static (no flip, can't park), idle EX
   workers spin, so the server's OWN idle load1 ≈ ex_count: io1/ex7 idles at load ~7 → ANY fixed
   quiet ceiling ≤7 can never open and every cell INVALIDs (io7/ex1 passed, io1/ex7 failed 4/4 —
   diagnostic pattern; AUTO parks so it passes). FIX: per-split `QUIET_LOAD_MAX = ex + 2.5`.
   Also NEVER edit a running bash script (it reads incrementally — swap a new file at a segment
   boundary instead, killing the old wrapper's pgid).
6. **quiet-box guard too strict** (guards.sh wait_quiet_box): default `QUIET_LOAD_MAX=1.00`/120s
   requires the 1-min load avg ≤1.0 before each cell measures, but after a heavy 8GB load the avg
   decays `~8·e^(-t/60)` → reaches 1.0 only at ~125s (past the 120s timeout) → the first cell of each
   server group INVALIDs ("quiet-box guard timed out"). FIX = `QUIET_LOAD_MAX=2.5 QUIET_WAIT_TIMEOUT_S=200`
   (reaches 2.5 at ~70s; a lagging 1-min avg that decays away in the first seconds doesn't pollute a
   300s window). ALSO: my own heavy investigation bursts (python+find over the tree) spike load and
   fail the currently-settling cell — MONITOR LIGHT (grep/wc, not python-over-CSVs) and analyze only
   at run end / during loads. And NEVER `pkill -f sweep_run.sh` — it self-matches my own shell
   ([[thredis-selfmatch-and-lock-traps]]); kill by comm (`pkill -x`) or pid.
- The auto flip WORKS: p1→io7 (the "7-1 wins at p1", tomokv ~4.4x redis p1 GET), p32→io5; reconverge
  ~15s of the 300s window (order-dependence negligible). LANDED config is in the auto_state jsonl NOT
  the CSV column (analyze_sweep.sh reads it from jsonl).

# Config truths
- AUTO boots io4/ex4 balanced then the flip converges (idle→io1/ex7; p32→io5; p1→io7). 0s warmup
  (measure flip cost). `TOMOKV_STATIC_IO=N` forces a static split for the io/ex sweep.
- Overrides: SYSTEMS_/PIPELINES_/DATASIZES_/FAMILIES_/DRIVERS_/TOMOKV_MODES_OVERRIDE,
  SINGLE_RATIOS_/MULTI_RATIOS_/TOMOKV_ATOMIC_OVERRIDE. Load-once per reboot-key
  (system,threads,mode,atomic,io/ex,datasize).
- Box = 7700X, 61GB RAM, perf_event_paranoid=-1. One-server-one-bench via flock thredis.boxlock.
- SANE numbers seen: TomoKV auto d32 p32 GET 8.4M ops/s, SET 5.58M (8GB DRAM) vs 6.26M (150MB cache) =
  −11% DRAM penalty. ipreq~8067 ipc~1.27 at 150MB. Re-verify all on EPYC.
