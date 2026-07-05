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

## WAVE-6 ADDENDUM (extended phase, 2026-07-06)
NEW KEEPS: **AE-1b reply-progress drain refresh (+2.70% P1, all reps ahead; +0.46% P16)** [2s;
port to 3s/autos pending]. SIX CORRECTNESS FIXES both static forks (pushed): HFE effect-capture
tombstones; DRAINING-window lazy-expire suppression (reshard TTL-conservation smoked); RP-1
RUNTIME gates (CONFIG SET appendonly/maxmemory + SYNC/PSYNC now refused under sharding); pool PUT
alloc cap + non-greedy grow (3s RSS hazard); uring EINTR/handshake/multishot-cancel fixes;
dead-code sweep (ae_uring.c, v12-K wds remnants). NEW PRE-EXISTING FINDS: ex0+SYNC crash in
clientsCron (documented); ZC synchronous notif wait = event-loop stall on real NIC (EPYC bring-up:
keep io_uring_zc OFF). INSIGHT for autothreads AE-1 port: drain passes DILUTE io-busy% (balancer
signal interplay documented in wave6_findings.json).
PENDING AT WRITE: AE-1b + wave-6 fix propagation to auto forks; 3s AE-1b port.

## PROPAGATION COMPLETE (final state)
AE-1b: 2s KEPT (+2.70% P1) c0a0a42ac; 3s KEPT (+7.3% P1 median) 96f886ecf; 2s-auto picked 12357b4f2.
Wave-6 fixes propagated to both autos (2s-auto tip 12357b4f2 incl. correct wds-preservation — the
v12-K code is LIVE v1.6 lineage there; 3s tips incl. 3s-appropriate wds deletion w/ loud boot abort).
ALL FOUR improve branches level and pushed. 3s-auto AE-1b: pending pick (bench-validated on 3s
static — safe pick for user or next session).
