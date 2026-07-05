# SELF-IMPROVEMENT LOOP — FINAL REPORT (2026-07-05/06, ~14h autonomous)

## KEEPS (all pushed, per improve branch — NOTHING merged to canonical)
**2s-improve-dev** (7): P3 parse hoists; W3-T2 inline getKeysFreeResult; W3-T3 flag-chain collapse
(all flat+simpler); **AE-1 adaptive drain +2.61% P1** (knob tomokv-io-drain-spin; latency floor
0.0707->0.0687ms); pin-gate BUGFIX; MULTI/WATCH gate [FLAGGED user-decision]; ex0 BUGFIX.
**3s-improve-dev** (6): P3/W3-T2/W3-T3 ports; **AE-1 port +4.66% P1 AND +3.30% GET512** (3s gains
more); pin-gate + MULTI-gate ports.
**2s-auto-improve-dev**: canonical v1.6-bugfix merge + all 7 static keeps; VALIDATED (equivalence
flat-to-better, 4/4 shifts incl fixed io-exit, ex0 serves, conservation exact).
**3s-auto-improve-dev**: 6 picks; strict + shifts smoke clean.
**2s-auto-threads-dev (canonical)**: v1.6 conn-migration + 5 wedge/hygiene fixes (separate stream,
already reviewed pattern).

## BUGS FOUND (the loop's biggest value)
1. **MULTI/EXEC CRITICAL silent data loss** (pre-existing, all sharded configs): EXEC executes
   against the empty decoy db — writes ACK'd then invisible; WATCH CAS never fires. 3 fix options
   in selfimprove/multibug_report.md. Gate (option 1) applied on improve branches. **USER DECISION.**
2. **io4/ex0 EXISTS segfault + wedge + rehash race** (pre-existing in shipped stable — my config
   overhaul made ex=0 reachable without dispatch gates). FIXED on improve branches (num_workers
   gates + ex0-only execute mutex). **CHERRY-PICK DECISION for stable/3-stage.**
3. **pin-gate inverted** (mine): NUMA bind ran only in MANUAL mode, opposite of every doc. FIXED on
   improve branches. **CHERRY-PICK DECISION for stable/3-stage.**
4. **3 v1.6 wedge bugs** (inbox-wedge, listener-brick, epoll-park-wedge): FIXED + pushed to
   canonical 2s-auto-threads-dev.
5. OBJECT ENCODING empty under sharding (documented; needs key-position-aware dispatch).

## REVERTS (evidence-backed, mechanisms preserved)
P5 input-bytes gate (-0.78% MIX); E2 release reshape (flat); E5 nextop hoist (-1.0%);
P1 pcmd freelist (flat/-0.87% — jemalloc tcache); P2 intern-cmd-ptr (flat — cmd ID off critical
path); E1 struct-pf (+0.47% consistent, sub-bar); AE-2 lazy-epollout (-0.41% — loopback
memcpy-bound); SPSC dirty bitmap (wash at nw=4); fused-bulk (byte-exact, worker-side unmeasurable);
beforeSleep bundle (-2.35% x2 unexplained — protocol); 3s wb-early-out (-3% — fires rarely at
saturation).

## THREADRIPPER LIST (re-measure on multi-CCD/real-NIC)
E1 struct-pf (cross-core, +0.47% even on 1-CCD); P2 intern-cmd-ptr (io-bound topologies);
decref-bounce; AE-2 lazy-epollout (real NIC); SPSC bitmap (nw>=16); fused-bulk (WB/io-bound);
wb-early-out (multi-CDB + idle conns); + prior list (prefetch stages, de-contention, num_cdb).

## LESSONS (doctrine-grade)
32B io4ex4 is dispatch/express-lane bound — 5 independent shave classes flat there; jemalloc removes
the allocator lever; syscall/latency-floor class = the only proven movers on loopback; box-serial
discipline + hard timeouts mandatory (2 agent stalls recovered clean); adversarial pre-verification
of mechanisms saved box time (tcache call exactly right).
