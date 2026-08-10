THREAD NAMING (small, mechanical): every thread this fork spawns must carry a
role-identifying name visible to perf/top/pidstat (pthread_setname_np, 15-char
cap). Today the poly threads all show as "redis-server", which forces
whole-process profiling and breaks per-role IPC attribution (top -H shows
bio_* named but IO/EX threads anonymous).
DELIVERABLE:
1. In polyThreadMain (src/server.c), set the name at thread start from the
   role: IO slots -> "tomo-io<N>" (N = io slot index), EX workers ->
   "tomo-ex<N>" (N = worker id). On a FLIP role conversion (the thread-mode
   actuator converting IO<->EX), RE-SET the name at the conversion point so
   the name tracks the live role.
2. Main thread -> "tomo-main" (setproctitle already covers the process name;
   do not fight it — pthread name only).
3. Any other fork-spawned helper threads (uring poller if built, etc.):
   name by role the same way.
4. Zero hot-path cost: naming happens at spawn/conversion only.
5. Grep tools/ for scripts that match thread names (comm truncation trap:
   15 chars) and list any that would need updating in the commit message —
   do NOT modify tools.
HARD RULES: WRITE CODE ONLY — never run make/compile, never boot a server,
never benchmark. ./notifyguard.sh invariants — revert none. Minimal diff.
git add -A + commit with WHAT/mechanism/observable.
