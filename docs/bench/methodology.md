# Benchmark methodology — 2026-08-13 comparison sweep

Single-socket 8-core Zen 4 desktop (single CCD, 61 GB RAM), exclusive use (lock + watchdog), noise
floor ±2%. Systems: TomoKV @ stable `3b4715889` (8 threads), stock Redis (single-threaded, its
architecture), Dragonfly v1.39 (`proactor_threads=8`), all default-tuned, `appendonly no`, no
snapshots. Driver: memtier 8 threads × 25 conns = 200 connections.

- **Fixed keyspace:** every system loads the identical keycount = 8 GB ÷ (value + 46 B); per-system
  resident memory is recorded, not equalized (TomoKV 12.0 GB at 32 B values).
- **Flip cost included:** TomoKV `auto` boots io4/ex4 with **zero warmup**; convergence happens
  inside the measured window. Static cells 120 s, cross-system cells 300 s.
- **Counters:** ipreq = instructions / completed op; IPC per cell from hardware counters.
- Caveats: sustained-SET is ~18% under burst-SET (write-path reclamation backlog, open issue);
  p50/p99 columns NA this run; Dragonfly torn result is defaults-only, re-verify stricter modes;
  single-CCD box — EPYC/multi-CCD validation pending.
