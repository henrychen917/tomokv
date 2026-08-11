INLINE-COMMAND RING ENTRIES (comm-tax lever 1a). Measured basis: the worker
pipeline alone runs 10.5M ops/s/worker at IPC 3.29 (pure rig); real serving is
2.0M at IPC 1.17 — ~400ns/command of IO<->EX handoff, dominated by ~5-6
cross-core line misses. Today a dispatch is an 8-byte ring entry POINTING at a
fake-client carrier the worker then misses on. DELIVERABLE: a single-line
dispatch fast lane —
1. Grow ring entries to one cache line (64B), tagged: FAST entries carry the
   whole single-key command inline (cmd class, key hash + bucket, key bytes
   inline when they fit (<=~40B) else ptr+len, client id, reply/CDB slot);
   POINTER entries keep today's fake-carrier semantics for everything else
   (multi-key, large keys, atomic shapes, cross-shard groups).
2. The worker executes FAST entries without touching the fake's core lines at
   all until reply write time (the fake remains the reply-side carrier); the
   dispatch side fills the inline entry INSTEAD of writing the fake's hot
   fields for those commands. Net: worker-side touches for a plain GET/SET
   drop from ~5-6 lines to ~2 (entry + reply).
3. Ring geometry: entries widen; keep head/tail split and SPSC protocol
   byte-compatible in SPIRIT (single producer, single consumer, staged tail
   publish) — the ring/queue protections in ./notifyguard.sh are the CONTRACT:
   preserve every protected property (SPSC ownership, staged publish, no
   silent drop on full — the exQueuePush-ignored-return wedge is history that
   must not repeat). If a protected property genuinely cannot survive the
   redesign, STOP and write the conflict into FINDINGS.md instead of reverting
   the protection.
4. Witnesses: tomokv_ring_fast_entries / tomokv_ring_ptr_entries counters so
   the A/B can prove the lane engages and what fraction rides it.
5. Memory: ring footprint grows (2048x64B per lane); note the L2 impact in a
   comment; do not shrink the queue depth to compensate (that changes admission
   behavior) — leave sizing observations to the coordinator's measurement.
HARD RULES: WRITE CODE ONLY — never run make/compile/servers/benchmarks.
Minimal diff for a change this deep: commit in reviewable stages (entry
format+tag, dispatch fill, worker fast-exec, witnesses). Match style.
