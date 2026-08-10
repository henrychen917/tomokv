CONTEXT (measured on this box, single-CCD):
- The async pipeline fully absorbs cross-L3 VISIBILITY latency (delayed-visibility rig: flat
  throughput 100-400ns at p32 with 5M deferrals; -1.5% at p1 with 90% of dispatches gated).
- Therefore multi-CCD's surviving costs are (a) the CONSUMER'S SYNCHRONOUS TOUCH of message
  lines inside the pop/drain loops (cheap ~50cyc from shared L3 today, 3-4x pricier cross-CCX),
  and (b) line-transfer VOLUME (2.08B cross-core fills/15s measured; reply path is the largest
  single bucket).
- Two prior per-key fast paths FAILED because their predicate was a costly blind per-key guess.
  The topology predicate is a static boot-time bit (does the target worker share my L3?) — free
  and exact. In-node keeps the current path byte-identical; cross-node gets heavier treatment.
DELIVERABLES (two commits):
1. EMULATION: knob tomokv-sim-xnode (0=off default, no alloc, no hot branch) — when on, the
   PRODUCER CLFLUSHOPTs the ring-entry line (and optionally the carried header line) after its
   release-store publish, forcing the consumer's first touch to pay a memory-class load. This
   emulates the cross-CCX touch cost on single-CCD hardware. Engagement counter (lines flushed).
2. CROSS-NODE PREFETCH PATH: gated by a per-worker topology bit (on this box, driven by a test
   knob tomokv-sim-xnode-mask so cells can mark workers "remote"): the WORKER's pop loop, while
   executing entry N, issues prefetches for entries N+1..N+k's ring lines and their carried
   fake-client header line; symmetrically the IO drain prefetches the next CDB lines while
   consuming the current one. Extend the existing exPrefetchBatch state-machine pattern — do not
   add a new synchronous stage or any wait. In-node (bit clear) paths must be byte-identical to
   today. Engagement counter (message-prefetches issued).
The coordinator will A/B: baseline vs flush-on, then flush-on vs flush-on+prefetch — if prefetch
recovers the flush-induced loss, the owner's cross-node design is validated pre-hardware.
