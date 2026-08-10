P0 WEDGE ROOT CAUSE (proven by gdb at wedge + INFO timelines; do not re-derive):
Cross-shard atomic READS take a QSBR pin at dispatch (src/server.c ~8104:
flatQsbrRegionEnter() + commit_seq snapshot into fake->tomo_read_snapshot, flag
tomo_read_snapshot_pinned) released only at reassembly (tomoReleaseReadSnapshot,
~3774). These pins DEPTH-NEST into the io thread's flatExtern epoch
(flat_extern_depth TLS): only depth 0->1 publishes an odd epoch and only
depth->0 publishes even. Under pipelined load some group pin is ALWAYS
outstanding, so the slot's tm_io_sig[s].flat_epoch stays at ONE odd value for
the whole run; flatBatchReady's clause (ii) ("epoch unchanged since close")
then blocks EVERY closed batch: flat_batches_pending grows 55K+, retire/prune
callbacks never fire, version bags deepen, atomic write completions starve,
tomokv_atomic_inflight pins at the window. The epoch scheme itself is correct
for INLINE regions (EVAL/SAVE/etc.) — the defect is only that long-lived
overlapping GROUP pins collapse into one eternal region.

DELIVERABLE — GENERATION-COUNTED GROUP PINS (fix A):
Separate dispatch-lifetime group pins from the inline-region epoch machinery.
1. Global monotone close generation: bump an atomic counter in flatBatchClose
   (one fetch_add per batch close — off the per-op hot path). Each flatBatch
   records the generation AT ITS CLOSE.
2. Per io slot s, outstanding-pin accounting by generation: at the ~8104
   dispatch-pin site, DO NOT call flatQsbrRegionEnter for the group pin.
   Instead read the current close generation g (relaxed), store it on the fake
   (new field next to tomo_read_snapshot; client core layout asserts —
   offsetof(client, exec_tail)==320 — must keep passing), and increment a
   per-slot ring counter pin_out[s][g & MASK]. tomoReleaseReadSnapshot
   decrements the same slot/gen it recorded. Dispatch and reassembly both run
   on the fake's owning io thread (same thread), but flatBatchReady reads the
   counters from OTHER threads: make the counters _Atomic, relaxed RMW,
   acquire loads on the reader side.
3. Per-slot lazily-advanced floor: oldest generation with outstanding pins
   (advance while count[floor & MASK]==0 && floor < cur_gen). flatBatchReady's
   group-pin clause for a batch closed at generation B on slot s:
   BLOCKED iff floor(s) <= B. (A pin taken AFTER the close observed a table
   the batch's values were already unlinked from — same argument the epoch
   scheme's "bit clear" case already makes.)
4. Ring width: pick a power of two (e.g. 4096). On wrap pressure
   (cur_gen - floor >= width) FAIL SAFE: treat every batch as blocked and
   count the event (never free early — spurious blocking is acceptable, early
   free is a UAF).
5. The inline-region epoch machinery (flatExternEnter/Exit, flat_extern_depth,
   FLAT_EXTERN_REGION) stays byte-identical for its remaining callers.
6. Observability: keep flatIoPinnedCount()/tomokv_flat_io_pinned meaningful
   (inline regions + slots with outstanding group pins); add
   tomokv_flat_pin_backlog (cur_gen - min over slots of floor) or an
   equivalent witness proving the new accounting engages and drains.
7. Teardown: every path that frees or recycles a pinned fake must route
   through tomoReleaseReadSnapshot exactly once (it already must today — keep
   that invariant; the flag guard makes it idempotent).
CORRECTNESS BAR: a batch must NEVER be freed while any pin whose recorded
generation <= that batch's close generation is outstanding on any slot.
