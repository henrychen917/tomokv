---
name: thredis-one-server-one-bench
description: "OWNER RULE — at most ONE redis server and ONE bench generator on the box at any time; violations already corrupted runs (SO_REUSEPORT splits, osc overlap, compile-during-bench)"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**Owner, 2026-08-09:** "just to make sure only ever run 1 server 1 bench at a time."

**Why it needs enforcement, not intent:** this box has already produced corrupted verdicts from
overlap — SO_REUSEPORT silently SPLITS connections between two servers on one port (the
certified-a-binary-it-never-ran class), a stale server contaminated the m3way window, and a rogue
compile overlapped the osc baseline. See [[thredis-selfmatch-and-lock-traps]],
[[thredis-box-noise-truth]].

**How to apply:** every harness boots at most one server and one memtier, serialised by chaining,
and `tmp/boxguard.sh` runs as a persistent watchdog: it logs and ALERTS (never kills) whenever
2+ redis-servers coexist, or a memtier targets a port with no matching single server, or a compiler
runs while a bench is live — with offender cmdlines for attribution. New harnesses should also take
the shared flock (`flock /shared/Projects/.claude/jobs/thredis.boxlock`) around their server+bench
span so two queues can never interleave.

## CODEX AGENTS COUNT AS BOX LOAD — the controller sweep needs a QUIET box (2026-08-12)

Codex agents are "API-bound" but they BURN CPU in bursts, and enough of them saturate the box.
Caught hard: ran the controller_sweep full-cert rerun with 8 codex agents live (README doc
agents + harness builder) — LOAD AVERAGE 16 on a 16-core box. Result: anti-thrash-p32 flips=8,
long-hold-p32 flips=6, AUTO==STATIC-p32 auto 10.6% BELOW static — all "FAIL", read at first as a
merge regression. It was CONTENTION. The tell: the p1 controller cells ALL PASSED (latency-bound,
timing-insensitive) while only the p32 cells failed (they measure per-role busy/idle MICROSECONDS
to compute the flip signal — the one thing contention corrupts directly). Rules:
- **The controller sweep (and any per-role-timing measurement) requires a codex-QUIET box: no
  `codex exec` running AND 1-min loadavg < 3.** Gate the run on `pgrep -f "^codex exec"` == 0
  and `/proc/loadavg` < 3 before booting.
- **Interleaved A/B/A/B perf batteries are ROBUST to this** — contention hits both arms per rep,
  so the relative A-vs-B delta (what drives merge decisions) survives; only ABSOLUTE-signal
  measurements (controller sweep, per-role occupancy) are corrupted. So tonight's merge batteries
  stand; the controller verdict had to be re-run quiet.
- Lingering finished codex processes count too: a doc agent that already wrote its file often
  does NOT exit (the codex-first delegation trap) — kill by cwd once its deliverable exists.

## LONG SESSIONS ACCUMULATE ROGUE DRIVERS — sweep before trusting ANY number (2026-08-12)

A single long session (this one, fd085c8e, spanning many turns + compactions) had left **dozens** of
background drivers/Monitors/soak-loops alive from earlier turns: `night3.sh` + a "wait-for-quiet then
launch final block" watcher, `devmerge_validate2.sh` (runs its OWN controller sweeps on devmerge — a
DIRECT port-7973 collision with my merge-cert), `chain10.sh`, `satacc.sh`, ~10 `ugrep --line-buffered`
Monitors, and many `bash -c 'while/until … sleep' ` waiters. They were mostly idle/blocked (1-min load
looked fine at the instant of a spot-check) but the LAUNCHERS periodically fired benchmarks. This
silently contaminated an entire flip merge-cert investigation: baseline `AUTO==STATIC-p32=3.14M` (below
the whole static curve — physically impossible), `long-hold-p32` reading 0 then 18, etc. All discarded.
- **Before ANY absolute-timing measurement in a long session, sweep the jobdir for leftover drivers**:
  `pgrep -f jobs/<id>/tmp/.*\.sh` (kill every driver except boxguard), `pgrep -f 'ugrep.*line-buffered'`
  (stale Monitors), and `bash -c` shells whose cmdline has `until|while.*sleep|setsid|nohup.*launch`.
  Kill by **exact PID and process-GROUP** (`kill -9 -$pgid`) so their spawned server/memtier children
  die too. NEVER kill the `claude …--session-id` / `bg-pty-host` procs (your own session).
- **A low instantaneous loadavg does NOT mean clean** — the rogue launchers are event-driven (fire on
  "build quiet"), so a build you start can TRIGGER one mid-measurement. Prove cleanliness with a
  loadavg SIDECAR logged across the whole run (peak 1-min), not a single before-check.
- The "respawning sweep" you chase is usually the pgrep **self-match** (your kill command contains
  `controller_sweep.sh`) — verify with the listening socket + `bash <path>/x.sh` argv, not `pgrep -f`.
  See [[thredis-selfmatch-and-lock-traps]].
