PREFETCH KNOB RESTRUCTURE (owner decision). Target shape — exactly two knobs,
symmetric semantics: 0 = off, 1 = on, 2 = on + cross-node detection:
  tomokv-prefetch-ex  (exists today as 0-3 level ladder, default 3)
  tomokv-prefetch-io  (exists today as tomokv-io-prefetch, 0-8 but used as a boolean)
1. EX side: collapse the level ladder. 1 = today's level-3 storage prefetch
   exactly (the shipped, validated config; its DB-size self-gate stays). The
   intermediate levels 1-2 were sweep artifacts — delete their arms
   (hardcode-or-delete). Default stays ON (1). Mode 2 = everything mode 1 does
   PLUS the consumer-side cross-node MESSAGE prefetch: while executing entry N
   the worker prefetches entries N+1..k's ring lines and their carried fake
   header line, but ONLY for entries whose PRODUCING io slot is in another
   node. That machinery was already implemented to spec on branch codex-cxxnode
   (consumer-side message prefetch behind a mask) — port its mechanism, but
   replace the test mask with the real topology table below.
2. IO side: rename tomokv-io-prefetch -> tomokv-prefetch-io, range 0-2.
   1 = today's behavior (the reorder-emit next-run ring-tail write warm).
   Mode 2 = 1 PLUS reply-side cross-node prefetch: in the reply drain, before
   consuming a CDB completion from a worker in ANOTHER node, prefetch that
   reply's buffer line(s). (Owner: "same for io side too especially for
   fetching reply buf from memory".)
3. Topology table: boot-time per-pair bitmap cross_node[io_slot][worker]
   derived from the existing tmNodeOfIoSlot()/tmNodeOfWorker() mapping
   (tomokv-nodes/tomokv-pin-mode define node membership). Recompute on flip
   role conversions (the conversion checkpoint already re-derives identity).
   On a 1-node config every entry is false and mode 2 must be BEHAVIORALLY
   IDENTICAL to mode 1 (gate before any new work; zero new hot-path cost).
4. Witnesses: engagement counters per new mechanism
   (tomokv_prefetch_ex_xnode_issued, tomokv_prefetch_io_xnode_issued) so a
   multi-node cell can prove mode 2 fired; both must read 0 on 1-node boots.
5. Old spellings: tomokv-io-prefetch name DELETED (boot must refuse unknown
   directive); prefetch-ex values 4+ out of range; update
   tools/preflight/knob_matrix.sh cells for both knobs to the new shape.
HARD RULES: WRITE CODE ONLY — never run make/compile, never boot a server,
never benchmark. ./notifyguard.sh invariants — revert none. No new knobs
beyond these two; thresholds self-derive. Minimal diff, match style.
git add -A + commit(s) with WHAT/mechanism/observable.
