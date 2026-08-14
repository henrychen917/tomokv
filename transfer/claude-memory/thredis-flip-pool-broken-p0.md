---
name: thredis-flip-pool-broken-p0
description: "P0 — the role-conversion path does not conserve threads; two independent detections, pre-existing"
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**THE ROLE-CONVERSION PATH DOES NOT CONSERVE THREADS.** Found 2026-08-08, two independent ways:

1. **A thread LOST.** Live server under `tomokv-atomic yes` + `--tomokv-thread-mode auto`, 9:1
   MGET8:MSET8 ks=10000, 200 conns p32, printing its own guard every 2s:
   `[flip-ctl] POOL BROKEN: io_threads_live=5 + num_workers_live=2 = 7, configured 8
   (io_threads=1 num_workers=7)`. Auto rewrites to a symmetric pool (io1/ex7); the controller had
   converted 4 workers to IO, so workers should read 3, not 2. One worker vanished mid-conversion.
2. **A thread GAINED.** preflight `controller_sweep`, `2-balancer | conservation | FAIL |
   obs=tasks 10 -> 11 | exp=exact (conversion, not creation)`.

**PRE-EXISTING, not caused by the atomics or the flip fork:** it fires on `tomokv-flip-signal 0`,
which is bit-identical to the shipping controller. The atomic write path merely provokes it by making
the EX side heavy enough to drive conversions that GET/SET benchmarks never trigger. Symptom rate:
**7 of 11 atomic+auto boots failed** (probe ConnectionRefused/Timeout, DEBUG TOMO-IOLOAD empty,
throughput INVALID), spread evenly across all four trigger modes.

**Why it is worse than "misclimb and wedge" (#100):** the guard's own comment says a pool one thread
short "would converge CORRECTLY, to the optimum of a budget that does not exist, and every symptom
would look like a tuning problem." Every previous flip investigation may have been reading a tuning
symptom of this.

**HYPOTHESIS TESTED AND REFUTED — do not re-run it.** I suspected the lost thread left its
SO_REUSEPORT listener armed with nobody accepting (the exact failure documented at server.c:629 for
the scripting case, fixed there with a listener scram "the same primitive IO-EXIT uses"), which would
also explain why no benchmark caught it — memtier opens all connections BEFORE any flip. Built
tmp/flipconn.sh + tmp/newconn_probe.py: flip the config, then open 200 fresh connections. Result over
4 boots: **200/200 served, 0 blackholed, 0 refused, POOL BROKEN never fired.** So the grow-front path
(EX->IO, driven by p1 GET) is clean. **Look at GROW-BACK (IO->EX), which is what the EX-bound atomic
mix drives.**

**HARNESS RULE this cost us:** tmp/atomauto.sh `rm -rf`'d the server dir at the end of every
iteration, deleting the log of every FAILED iteration before it could be read. Any repro harness must
retain logs for failed iterations at minimum.

# CORRECTION 2026-08-09 — the battery-probe "pool=5/5" was NEVER this bug

The flipaccept ABAB probe signature (pool=5/5, cfg "-", all four visits NO-SETTLE at half rate)
that got filed as a second sighting of this P0 is a HARNESS bug, closed: `boot(){ local io=$1
ex=$((8-io)) ... }` — bash expands ALL of `local`'s arguments BEFORE assigning any local, so
$((8-io)) read the CALLER'S global io, which the anystart loop leaves at 7 ⇒ the probe block's
`boot 4` requested `--tomokv-thread-ex 1` and the server correctly provisioned a 5-thread pool
(boot log literally says "5 threads provisioned ... boot split io 4 / ex 1"; `config get` showed
the symmetric-pool rewrite io=1/ex=4). Proof: `io=7; f(){ local io=$1 ex=$((8-io)); }; f 4` ⇒
ex=1. Anystart cells were immune only because their caller's global io equaled $1. Every
battery's ABAB block ever run measured a 5-thread server. Fixed: two `local` statements.
**Findings 1 and 2 above (guard-firing loss under atomic+auto, balancer 10→11) remain REAL,
pre-existing, and open — grow-back is still the suspect.** The two must not be conflated again;
the guard line (`POOL BROKEN: ... = 7, configured 8`) names the configured total — a
harness-underprovisioned pool reads `configured 5` and is not this P0.
Related: [[thredis-session-2026-08-08-overnight]], [[thredis-flip-controller-frozen]],
[[thredis-sweep-abandon-livelock]], [[thredis-selfmatch-and-lock-traps]].
