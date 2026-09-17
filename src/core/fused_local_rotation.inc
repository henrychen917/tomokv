// Included inside ExLoopT. O11 uses the current ordinary 1s IO rotation:
// PARSE -> [owner prefetch -> LANE -> OWNER] -> retire/send -> next PARSE.
// The brackets stay inside the existing executor/QSBR/AOF envelope. Nothing is
// retained across a pass, and the source task prefix retires only after OWNER.
// Quanta derive from the shipped read-local fairness geometry, with no new knob.

// Called only at boot for 1s + read-local + overlap. The kind-A PAD changes this
// one return value in a copy of POST; it selects the complete PRE schedule while
// keeping every text address/size, O6 prefetch and L4 prebuild intact.
__attribute__((noipa)) static bool fused_local_rotation_policy() { return true; }

template <bool IofusedPrivateQueue, size_t Capacity>
uint32_t exec_batch_local_read_gap(Task (&batch)[Capacity], uint32_t held) {
    static_assert(Fused);
    static_assert(Capacity == kReadLocalOwnerTaskChunkOps);
    if (!held) return 0;
    if (!xshard_retries_.empty()) {
        // A preceding chunk discovered undecided owner debt. Keep its complete
        // deferred suffix; do not insert a new lane turn inside that suffix.
        exec_batch<IofusedPrivateQueue>(batch, held);
        return 0;
    }
    // Publish any preceding last-owner install before probing local reads.
    // Both prefetch helpers verify ownership and retain no store/slot pointer.
    flush_xshard_commits();
    if (overlap_prefetch_enabled(held)) prefetch_overlap_batch(batch, held);
    else                               prefetch_exec_batch(batch, held);

    // LANE: the existing bounded capture/copy/demotion path. Every foreign
    // capture dies before owner mutation or the pass's QSBR tick. A demotion
    // may post new work, but cannot invalidate a retained owner value: none exists.
    const uint32_t local = drain_local_reads_bounded(kReadLocalDrainChunkOps);
    if (local)
        srv_->mode_schedule_stats(self_->id()).note_overlap(OverlapSchedule::Fused, true);

    // OWNER: keep O6's whole-batch execution, exact slowlog handling, atomic
    // publication and dispatch-time parking. Pure reads use the ordinary tail.
    exec_batch_prefetched<IofusedPrivateQueue>(batch, held);
    return local;
}
