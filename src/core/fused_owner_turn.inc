// Included in ExLoopT. Two bounded extra opportunities per fused rotation;
// never a new admission, FIFO hand-off, batch, or execution protocol.
    bool fused_owner_ready() const {
        return fused_owner_bells[self_->id()].runnable.load(std::memory_order_relaxed);
    }
    template <bool Reordered = false>
    __attribute__((noinline)) uint32_t fused_owner_turn() {
        static_assert(Fused);
        // Take BEFORE servicing: a concurrent arrival after the take remains
        // set for the next boundary. Reusing the complete pass preserves LB,
        // snapshots, read-local publication and cross-shard commit flushing.
        if (!fused_owner_bells[self_->id()].runnable.exchange(false, std::memory_order_acquire))
            return 0;
        ++exec1s_counters[self_->id()].extra_passes;
        if constexpr (Reordered) return r7_fused_baseline_pass();
        else return fused_baseline_pass();
    }
    void ring_fused_owner() {
        if constexpr (Fused)
            if (srv_->thread_mode() == ThreadMode::Fused)
                fused_owner_bells[self_->id()].runnable.store(true, std::memory_order_release);
    }
