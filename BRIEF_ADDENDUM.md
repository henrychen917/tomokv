PIN-TRANSFER SITES (verified; handle explicitly): at 4 sites the dispatch pin is
transferred from the head fake to the csGroup — search `snapshot_pinned = 1`
(server.c ~12543, ~13229, ~13932, ~14005), each paired with
`head->tomo_read_snapshot_pinned = 0; /* group owns the matching exit */`.
The group's exit runs in csReassemble (`if (g->snapshot_pinned) { ...
flatQsbrRegionExit(); }`) and on the group-teardown/CLOSE_ASAP drain path.
With generation-counted pins, the recorded (slot, generation) token must move
with the ownership transfer: either carry the generation on the csGroup next to
snapshot_pinned, or keep the accounting keyed off the head fake's stored
generation since the group release path still has g->head. Every enter must be
matched by exactly one decrement of the SAME (slot, generation) regardless of
which owner (fake or group) performs the release. All release paths run on the
fake's owning io thread (verified: all three tomoReleaseReadSnapshot call sites
and csReassemble run inside the io thread's reply-drain walk), so producer-side
updates are same-thread; only flatBatchReady reads cross-thread.
