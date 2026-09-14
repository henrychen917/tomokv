// R2 is selected at boot or an EX role entry, outside the FIFO hot loops. R7's
// strict no-op audit showed that sharing armed definitions in these headers changes
// GCC's unit-wide inlining choices even with reorder disabled. Keep the original
// bodies and names in ex_loop.h/io_loop.h/genthread.cc, and the armed definitions here.
//
// These control envelopes deliberately mirror the original loops. Keep ownership,
// retry, snapshot, fairness and recv/callback/retire fixes in both copies. The R2
// changes remain at the two gathered-batch seams: prefetch screens static classes,
// and only a mixed batch enters the scheduler. tests/reorder_noop.py compares all
// 217 original hot bodies, including the shared parsers, rather than trusting a
// source-only zero-cost claim. No field, per-thread selector or per-op state is added.
#include "genthread.h"
#include "fused_boot_gate.h"
#include "shutdown_report.h"
#include "../net/unix_listener.h"
#include "ex_loop.h"
#include "io_loop.h"
#include "reorder.h"

namespace tomo {

void command_bind_server_selected(Server* server) {
    command_bind_server(server);
    if (!server || !server->cfg().reorder) return;
    // main calls this before ACL setup, recovery workers, or listeners. Registry
    // accessors expose const pointers for runtime readers, but their backing rows
    // are mutable boot-owned vectors. Stamp every variant before any Op can name
    // one; the hot-verb pointers already refer to these same rows. No new storage.
    // Keeping this walk out of commands.cc also preserves its off-arm jump tables
    // and constant pools; source-only screening did not preserve the linked code.
    const auto stamp = [](const CommandSpec* spec) {
        const_cast<CommandSpec*>(spec)->set_length_class(command_length_class(*spec));
    };
    const uint32_t count = command_registry_size();
    for (uint32_t id = 0; id < count; id++) {
        const CommandSpec* spec = command_registry_at(id);
        const CommandSpec* notify = command_notify_variant(spec);
        const CommandSpec* tls = command_tls_variant(spec);
        const CommandSpec* tls_notify = command_tls_variant(notify);
        stamp(spec);
        if (notify != spec) stamp(notify);
        if (tls != spec) stamp(tls);
        if (tls_notify != notify) stamp(tls_notify);
    }
}

template <bool Fused>
uint32_t ExLoopT<Fused>::r2_fused_pass() {
    static_assert(Fused);
    if (!pipeline_batches_)
        return r2_fused_pass_impl<kGenthreadExBatchOps, true, false>();
    return iofused_
        ? r2_fused_pass_impl<kGenthreadPipelineExBatchOps, true, true, true>()
        : r2_fused_pass_impl<kGenthreadPipelineExBatchOps, true, false>();
}

template <bool Fused>
uint32_t ExLoopT<Fused>::r2_fused_baseline_pass() {
    static_assert(Fused);
    if (srv_->thread_mode() == ThreadMode::Split) return split_read_local_pass();
    if (read_local_enabled())
        return r2_fused_pass_impl<kGenthreadExBatchOps, true, false, false, true>();
    return r2_fused_pass_impl<kGenthreadExBatchOps, true, false>();
}

template <bool Fused>
uint32_t ExLoopT<Fused>::r2_fused_coarse_pass() {
    static_assert(Fused);
    return r2_fused_pass_impl<kGenthreadPipelineExBatchOps, true, true, true>();
}

template <bool Fused>
template <typename Filler>
uint32_t ExLoopT<Fused>::r2_fused_three_way_pass(Filler&& filler) {
    static_assert(Fused);
    using Fn = std::remove_reference_t<Filler>;
    return r2_fused_pass_impl<kGenthreadPipelineExBatchOps, true, true, true, false, Fn>(
        &filler);
}

template <bool Fused>
uint32_t ExLoopT<Fused>::r2_fused_pipeline_control() {
    static_assert(Fused);
    return r2_fused_pass_impl<kGenthreadPipelineExBatchOps, false, false>();
}

template <bool Fused>
template <uint32_t BatchOps, bool ConsumeTasks, bool CoalesceSubmit,
          bool IofusedPrivateQueue, bool InterleaveLocalReads,
          typename Filler>
uint32_t ExLoopT<Fused>::r2_fused_pass_impl(Filler* filler) {
    Server::ClientWorkScope client_work(*srv_, self_->id());
    constexpr bool HasFiller = !std::is_void_v<Filler>;
    [[maybe_unused]] bool filler_used = false;
    auto finish_filler = [&] {
        if constexpr (HasFiller) {
            if (!filler) std::abort();
            if (!filler_used) {
                (*filler)();
                filler_used = true;
            }
        }
    };
    struct RotationBoundary {
        bool enabled;
        ThreadCtx* self;
        Server* server;
        ~RotationBoundary() {
            if (enabled) self->publish_read_local_tick(server->read_local_epoch());
        }
    } rotation_boundary{read_local_enabled(), self_, srv_};
    cached_now_ms_ = realtime_ms();
    // A completed LB stage may have changed this owner's shard vector. Armed retirement sinks
    // must follow ownership before any work; the literal baseline notification block remains in
    // lb_control_pass below. Since the ownership edge itself now rebinds
    // (Server::adopt_read_local_retire_sink) this is a no-op standing check, kept because a
    // no-op is the cheapest proof that the eager rebind ran.
    if (lb_rebind_pending_ && srv_->lb_stage() != LbStage::ExDrain)
        read_local_rebind_owned_shards_after_lb();
#ifdef TOMO_RL_CACHE_DEBUG
    if constexpr (Fused)
        if (read_local_enabled())
            srv_->debug_assert_read_local_sinks_follow_ownership(self_->id());
#endif
    const bool lb_frozen = lb_controller_armed_ && srv_->lb_dispatch_paused();
    if (!lb_frozen) refresh_live_config();
    if (maxmemory_enabled_)
        cached_lru_clock_ = static_cast<uint8_t>(
            (static_cast<uint64_t>(cached_now_ms_ / 1000) >> kLruClockShift) & 0x1f);

    // The WB batch captured its AOF gate before entering this call. Only a clean fresh-task
    // turn may put that WB work into an EX prefetch gap: executing older retry/deferred debt
    // first could make a newly Done prefix eligible for the already-gated batch. Exceptional
    // control state therefore consumes WB immediately and continues in the ordinary coarse EX
    // order. The saturated steady path has all five queues empty and reaches the split below.
    if constexpr (HasFiller) {
        if (lb_frozen || snapshot_owner_state_ != SnapshotOwnerState::None ||
            !stale_tasks_.empty() || !multi_retries_.empty() ||
            !atomic_deferred_.empty() || !xshard_retries_.empty() ||
            !ordered_deferred_.empty())
            finish_filler();
    }

    [[maybe_unused]] bool owner_work_remains = false;
    bool fairlane_turn = false;
    if constexpr (InterleaveLocalReads) {
        static_assert(Fused && ConsumeTasks);
        static_assert(BatchOps == kReadLocalOwnerTaskChunkOps);
        if (!read_local_enabled()) std::abort();
        // Exceptional debt keeps its established total order. The ordinary saturated turn is
        // the only place that caps fresh owner work before WB.
        fairlane_turn = !lb_frozen && !fairlane_owner_debt_pending();
        if (fairlane_turn) {
            compact_local_read_tombstones();
            fairlane_turn = read_local_impl().lane_count != 0;
        }
    }
    uint32_t did = 0;
    if (fairlane_turn) {
        // EARLY: reads parsed by the preceding IFID phase get the first execution/reply slots.
        did += drain_local_reads_bounded(kReadLocalDrainChunkOps);
    } else {
        // Coarse overlap consumes every local capture inside this call. On a clean
        // three-way turn WB runs later at the owner prefetch seam; on an exceptional turn
        // it already ran above. Neither WB nor owner mutation runs inside a local chunk,
        // so no foreign pointer survives into either or across RotationBoundary's tick.
        did += drain_local_reads();
    }
    if (lb_frozen) {
        if (!srv_->lb_acked(self_->id())) {
            did += service_stale_forwards<BatchOps, IofusedPrivateQueue>();
            did += drain_releases(true);
            did += service_multi_retries<IofusedPrivateQueue>();
            did += service_atomic_deferred<IofusedPrivateQueue>();
            did += service_xshard_retries<IofusedPrivateQueue>();
            if (xshard_retries_.empty())
                did += service_ordered_deferred<BatchOps, IofusedPrivateQueue>();
            if constexpr (ConsumeTasks)
                if (xshard_retries_.empty() && ordered_deferred_.empty()) {
                    if constexpr (HasFiller)
                        did += r2_drain_tasks_with_filler<BatchOps, IofusedPrivateQueue>(
                            true, *filler, filler_used);
                    else
                        did += r2_drain_tasks<BatchOps, IofusedPrivateQueue>(true);
                }
            flush_xshard_commits();
            did += aof_flush_pass();
            did += drain_notify_keyless(self_->sig());
        }
        finish_filler();
        did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
        did += lb_control_pass();
    } else {
        did += snapshot_control_pass<BatchOps, IofusedPrivateQueue>();
        did += service_stale_forwards<BatchOps, IofusedPrivateQueue>();
        did += drain_releases();
        if (!snapshot_blocks_tasks()) {
            did += service_multi_retries<IofusedPrivateQueue>();
            did += service_atomic_deferred<IofusedPrivateQueue>();
            did += service_xshard_retries<IofusedPrivateQueue>();
            if (xshard_retries_.empty())
                did += service_ordered_deferred<BatchOps, IofusedPrivateQueue>();
            if constexpr (ConsumeTasks)
                if (xshard_retries_.empty() && ordered_deferred_.empty()) {
                    if (snapshot_owner_state_ == SnapshotOwnerState::None) {
                        if constexpr (HasFiller)
                            did += r2_drain_tasks_with_filler<BatchOps, IofusedPrivateQueue>(
                                false, *filler, filler_used);
                        else {
                            if (fairlane_turn)
                                did += r2_drain_tasks_read_local_interleaved<
                                    IofusedPrivateQueue>(false, owner_work_remains);
                            else
                                did += r2_drain_tasks<BatchOps, IofusedPrivateQueue>();
                        }
                    } else {
                        did += drain_tasks_snapshot<BatchOps, IofusedPrivateQueue>();
                    }
                }
        }
        finish_filler();
        flush_xshard_commits();
        if (__builtin_expect(srv_->blocking_waiters() != 0, false) &&
            cached_now_ms_ >= blocking_beat_ms_) {
            did += blocking_owner_cycle(*srv_, *self_, ring_, cached_now_ms_, true);
            blocking_beat_ms_ = cached_now_ms_ + 10;
        }
        did += aof_flush_pass();
        did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
    }
    if (fairlane_turn) {
        owner_work_remains |= fairlane_owner_debt_pending();
        if (!owner_work_remains) did += drain_local_read_tail();
        // Parser-created tombstones must not cross the WB corpse-grace boundary.
        compact_local_read_tombstones();
    }
    if (read_local_enabled()) {
        did += read_local_impl().deferred.drain_ready();
        // One rotation of the lane-admission pressure window has elapsed.
        if (__builtin_expect(read_local_impl().lane_pressure != 0, false))
            read_local_impl().lane_pressure--;
        // Adopt the test lane cap, if one is set. ONE relaxed load per ROTATION of a
        // read-mostly word that production never writes (so it stays shared-clean in every
        // core's L1), against ~1000 ops per rotation, and the store happens only when the
        // value actually changes -- the admission path itself keeps reading a plain uint16 on
        // a line it already owns. 0 means derive, which is what production always sees.
        const uint32_t cap = srv_->debug_read_local_lane_cap();
        const uint16_t want = cap == 0 ? static_cast<uint16_t>(kInboxSlots)
                                       : static_cast<uint16_t>(std::min<uint32_t>(
                                             cap, kInboxSlots));
        if (__builtin_expect(read_local_impl().lane_admit_cap != want, false))
            read_local_impl().lane_admit_cap = want;
    }
    if (!lb_frozen) did += owner_control_tail();
    if (did) {
        fused_submit_boundary<CoalesceSubmit>();
        fused_idle_spins_ = 0;
        return did;
    }
    if constexpr (!ConsumeTasks) return 0;
    if (lb_frozen) return 0;
    if (++fused_idle_spins_ < kExSpinBudget) return 0;
    fused_idle_spins_ = 0;
    if constexpr (InterleaveLocalReads) {
        did = fairlane_turn
            ? r2_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue, true>()
            : r2_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
    } else {
        did = r2_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
    }
    if (did) fused_submit_boundary<CoalesceSubmit>();
    return did;
}

template <bool Fused>
uint32_t ExLoopT<Fused>::r2_fused_sweep(bool consume_tasks) {
    static_assert(Fused);
    if (!consume_tasks) {
        if (lb_controller_armed_ && srv_->lb_dispatch_paused())
            return iofused_
                ? r2_fused_pass_impl<kGenthreadPipelineExBatchOps, false, true, true>()
                : r2_fused_pass_impl<kGenthreadPipelineExBatchOps, false, false>();
        if (!pipeline_batches_)
            return r2_fused_sweep_impl<kGenthreadExBatchOps, false, false>();
        return iofused_
            ? r2_fused_sweep_impl<kGenthreadPipelineExBatchOps, false, true, true>()
            : r2_fused_sweep_impl<kGenthreadPipelineExBatchOps, false, false>();
    }
    if (!pipeline_batches_)
        return r2_fused_sweep_impl<kGenthreadExBatchOps, true, false>();
    return iofused_
        ? r2_fused_sweep_impl<kGenthreadPipelineExBatchOps, true, true, true>()
        : r2_fused_sweep_impl<kGenthreadPipelineExBatchOps, true, false>();
}

template <bool Fused>
uint32_t ExLoopT<Fused>::r2_fused_baseline_sweep() {
    static_assert(Fused);
    if (srv_->thread_mode() == ThreadMode::Split) return split_read_local_pass();
    if (read_local_enabled())
        return r2_fused_sweep_impl<kGenthreadExBatchOps, true, false, false, true>();
    return r2_fused_sweep_impl<kGenthreadExBatchOps, true, false>();
}

template <bool Fused>
uint32_t ExLoopT<Fused>::r2_fused_coarse_sweep() {
    static_assert(Fused);
    return r2_fused_sweep_impl<kGenthreadPipelineExBatchOps, true, true, true>();
}

template <bool Fused>
uint32_t ExLoopT<Fused>::r2_fused_pipeline_control_sweep() {
    static_assert(Fused);
    return r2_fused_sweep_impl<kGenthreadPipelineExBatchOps, false, false>();
}

template <bool Fused>
template <uint32_t BatchOps, bool ConsumeTasks, bool CoalesceSubmit,
          bool IofusedPrivateQueue, bool InterleaveLocalReads>
uint32_t ExLoopT<Fused>::r2_fused_sweep_impl() {
    if (lb_controller_armed_ && srv_->lb_dispatch_paused())
        return r2_fused_pass_impl<BatchOps, ConsumeTasks, CoalesceSubmit,
                               IofusedPrivateQueue>();
    struct RotationBoundary {
        bool enabled;
        ThreadCtx* self;
        Server* server;
        ~RotationBoundary() {
            if (enabled) self->publish_read_local_tick(server->read_local_epoch());
        }
    } rotation_boundary{read_local_enabled(), self_, srv_};
    cached_now_ms_ = realtime_ms();
    if (lb_rebind_pending_) read_local_rebind_owned_shards_after_lb();
    uint32_t did = 0;
    if constexpr (InterleaveLocalReads) {
        if (!read_local_enabled()) std::abort();
        if (fairlane_owner_debt_pending()) {
            did += drain_local_reads() +
                r2_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
        } else {
            compact_local_read_tombstones();
            if (read_local_impl().lane_count) {
                did += drain_local_reads_bounded(kReadLocalDrainChunkOps);
                did += r2_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue, true>();
            } else {
                did += r2_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
            }
        }
    } else {
        did += drain_local_reads() +
            r2_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
    }
    if (read_local_enabled()) did += read_local_impl().deferred.drain_ready();
    if (did) fused_submit_boundary<CoalesceSubmit>();
    return did;
}

template <bool Fused>
void ExLoopT<Fused>::r2_run() {
    if constexpr (Fused) {
        // Only RL2S instantiates the owner loop with the fused-capable executor. Its lane
        // was drained before role conversion; owner commands use no local-read captures.
        if (!read_local_enabled() || read_local_impl().lane_count != 0) std::abort();
        self_->publish_read_local_parked(srv_->read_local_epoch());
        // A preceding shard-less IO tenure may have consumed this CONFIG version without
        // applying it to shards. Reapply once ownership is installed and dispatch resumes.
        live_config_version_ = UINT64_MAX;
    }
    LoopSignals& sig = self_->sig();
    uint32_t idle_spins = 0;

    while (!self_->stop_flag().load(std::memory_order_relaxed) &&
           self_->role() == Role::Ex) {
#ifdef TOMO_RL_CACHE_DEBUG
        if constexpr (Fused)
            srv_->debug_assert_read_local_sinks_follow_ownership(self_->id());
#endif
        cached_now_ms_ = realtime_ms();
        const bool flip_frozen = srv_->flip_stage() >= FlipStage::ExDrain;
        const bool lb_frozen = lb_controller_armed_ && srv_->lb_dispatch_paused();
        const bool placement_frozen = flip_frozen || lb_frozen;
        // refresh_live_config() walks this owner's shard vector. The coordinator may rewrite
        // those vectors after ExDrain acknowledgement, so a frozen executor must not even run
        // the otherwise-cold configuration refresh path.
        if (!placement_frozen) refresh_live_config();
        if (maxmemory_enabled_)
            cached_lru_clock_ = static_cast<uint8_t>(
                (static_cast<uint64_t>(cached_now_ms_ / 1000) >> kLruClockShift) & 0x1f);
        sig.iterations++;

        uint32_t did = 0;
        uint64_t pass_ns = 0;
        {
            Server::ClientWorkScope client_work(*srv_, self_->id());
            Span busy(pass_ns);
            if (self_->sample_depth(busy.start_ns() / 1000)) {
                const uint32_t age_rate = srv_->effective_age_sample_rate();
                if (age_rate != age_sample_rate_cached_) {
                    age_sample_rate_cached_ = age_rate;
                    self_->sig().configure_age_sampling(age_rate);
                }
            }
            if (placement_frozen) {
                // Once ExDrain is acknowledged this loop is a hard safe point: no expiry,
                // cleanup, waiter walk, or task can reacquire a moved FlatStore before FLIP
                // publishes ExInstall. The coordinator may rewrite owner entries immediately
                // after observing the acknowledgement.
                const bool acknowledged = flip_frozen
                    ? srv_->flip_acked(self_->id(), FlipStage::ExDrain)
                    : srv_->lb_acked(self_->id());
                if (!acknowledged) {
                    did += service_stale_forwards();
                    did += drain_releases(true);
                    did += service_multi_retries();
                    did += service_atomic_deferred();
                    did += service_xshard_retries();
                    if (xshard_retries_.empty()) did += service_ordered_deferred();
                    if (xshard_retries_.empty() && ordered_deferred_.empty())
                        did += r2_drain_tasks(true);
                    flush_xshard_commits();
                    did += aof_flush_pass();
                    did += drain_notify_keyless(sig);
                    if constexpr (Fused)
                        did += read_local_impl().deferred.drain_ready();
                }
                did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
                did += lb_control_pass();
                did += flip_control_pass();
            } else {
                did += snapshot_control_pass();
                did += service_stale_forwards();
                did += drain_releases();
                if (!snapshot_blocks_tasks()) {
                    did += service_multi_retries();
                    did += service_atomic_deferred();
                    did += service_xshard_retries();
                    if (xshard_retries_.empty()) did += service_ordered_deferred();
                    if (xshard_retries_.empty() && ordered_deferred_.empty())
                        did += snapshot_owner_state_ == SnapshotOwnerState::None
                                   ? r2_drain_tasks() : drain_tasks_snapshot();
                }
                flush_xshard_commits();
                if (__builtin_expect(srv_->blocking_waiters() != 0, false) &&
                    cached_now_ms_ >= blocking_beat_ms_) {
                    did += blocking_owner_cycle(
                        *srv_, *self_, ring_, cached_now_ms_, true);
                    blocking_beat_ms_ = cached_now_ms_ + 10;
                }
                did += aof_flush_pass();
                did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
                if constexpr (Fused)
                    did += read_local_impl().deferred.drain_ready();
                did += owner_control_tail();
            }
        }
        // A pass that found nothing -- every drain and control pass came back empty -- is
        // polling, not work. Book it as idle so busy_ns means WORK: the FLIP placement model
        // reads the roles' busy shares, and an executor spinning its 2048-pass budget between
        // task batches would otherwise report the polling as demand (measured on 8-key
        // MGET/MSET at 2:2 of 4: ex 97% "busy", three quarters of its passes empty; the model
        // read io = 0.73 of a 0.47 workload). One local and one branch per pass.
        if (did) sig.busy_ns += pass_ns; else sig.idle_ns += pass_ns;
        sig.cpu_ns = thread_cpu_ns();

        // Flush prepared SQEs before looping. Recv re-arms and cross-ring wakes are
        // PREPARED during the work section but only reach the kernel on submit; taking
        // the busy path without submitting strands them in the SQ forever, and the peer
        // that is waiting on that wake never runs.
        if (did) {
            ring_.submit_and_reap(); idle_spins = 0; continue;
        }

        // A frozen executor must never fall through to r2_sweep(): sweep owns expiry, MVCC
        // cleanup and blocking-waiter walks, any of which can touch a shard after ExDrain's
        // acknowledgement. Before the acknowledgement keep polling internal retry debt; after
        // it, sleep only on the ring the coordinator wakes at every stage publication.
        if (placement_frozen) {
            const bool acknowledged = flip_frozen
                ? srv_->flip_acked(self_->id(), FlipStage::ExDrain)
                : srv_->lb_acked(self_->id());
            if (!acknowledged) {
                __builtin_ia32_pause();
                continue;
            }
            Span idle(sig.idle_ns);
            self_->arm_blocked();
            ring_.submit_and_wait(1);
            self_->clear_blocked();
            continue;
        }

        if (++idle_spins < kExSpinBudget) { sig.spins++; __builtin_ia32_pause(); continue; }
        idle_spins = 0;

        // Mask-independent sweep before parking. The mask is a hint for the hot path; it must
        // not be the only thing that can find queued work, or one lost bit wedges a connection
        // forever. Runs only when this thread has already concluded it has nothing to do.
        if (r2_sweep()) { ring_.submit_and_reap(); continue; }

        Span idle(sig.idle_ns);
        self_->arm_blocked();
        if (!self_->any_ex_inbound()) ring_.submit_and_wait(1);
        else                       ring_.submit_and_reap();
        self_->clear_blocked();
    }
}

template <bool Fused>
template <uint32_t BatchOps, bool ConsumeTasks,
          bool IofusedPrivateQueue, bool InterleaveLocalReads>
uint32_t ExLoopT<Fused>::r2_sweep() {
    Server::ClientWorkScope client_work(*srv_, self_->id());
    [[maybe_unused]] bool owner_work_remains = false;
    uint32_t n = snapshot_control_pass<BatchOps, IofusedPrivateQueue>() +
                 service_stale_forwards<BatchOps, IofusedPrivateQueue>() +
                 drain_releases(true);
    if (!snapshot_blocks_tasks()) {
        n += service_multi_retries<IofusedPrivateQueue>();
        n += service_atomic_deferred<IofusedPrivateQueue>();
        n += service_xshard_retries<IofusedPrivateQueue>();
        if (xshard_retries_.empty())
            n += service_ordered_deferred<BatchOps, IofusedPrivateQueue>();
        if constexpr (ConsumeTasks)
            if (xshard_retries_.empty() && ordered_deferred_.empty()) {
                if (snapshot_owner_state_ == SnapshotOwnerState::None) {
                    if constexpr (InterleaveLocalReads)
                        n += r2_drain_tasks_read_local_interleaved<IofusedPrivateQueue>(
                            true, owner_work_remains);
                    else
                        n += r2_drain_tasks<BatchOps, IofusedPrivateQueue>(true);
                } else {
                    n += drain_tasks_snapshot<BatchOps, IofusedPrivateQueue>(true);
                }
            }
    }
    if constexpr (InterleaveLocalReads) {
        owner_work_remains |= fairlane_owner_debt_pending();
        if (!owner_work_remains) n += drain_local_read_tail();
        compact_local_read_tombstones();
    }
    flush_xshard_commits();
    n += active_expire_cycle() + atomic_cleanup_cycle(64);
    n += drain_notify_keyless(self_->sig(), /*force=*/true);
    if (__builtin_expect(srv_->blocking_waiters() != 0, false))
        n += blocking_owner_cycle(*srv_, *self_, ring_, cached_now_ms_, true);
    n += aof_flush_pass();
    // Normally flush_xshard_commits empties the queue synchronously. The DEBUG hold can
    // retain it across passes; both split and fused idle paths consult this sweep before
    // parking, so keep polling until the control connection releases the latch.
    if (__builtin_expect(xshard_commit_pending_, false)) n++;
    return n;
}

template <bool Fused>
template <bool IofusedPrivateQueue>
uint32_t ExLoopT<Fused>::r2_drain_tasks_read_local_interleaved(bool unmasked,
                                            bool& owner_work_remains) {
    Task batch[kReadLocalOwnerTaskChunkOps];
    uint32_t held = 0;
    uint32_t local_work = 0;
    auto take = [&](const Task& task) {
        batch[held++] = task;
        if (held != kReadLocalOwnerTaskChunkOps) return false;
        r2_exec_batch<IofusedPrivateQueue>(batch, held);
        held = 0;
        return true;
    };
    auto local_turn = [&] {
        // A local read must not run between a last-owner install and this batch's epoch
        // publication. This boundary still batches every group in the preceding owner chunk.
        flush_xshard_commits();
        for (uint32_t chunk = 0;
             chunk < kReadLocalMaxChunksBetweenOwnerBatches; chunk++)
            local_work += drain_local_reads_bounded(kReadLocalDrainChunkOps);
    };
    const uint32_t n = self_->drain_task_producer_chunks<IofusedPrivateQueue>(
        kReadLocalOwnerTaskChunkOps, take, local_turn, unmasked);
    if (held) {
        r2_exec_batch<IofusedPrivateQueue>(batch, held);
        local_turn();
    }
    owner_work_remains = self_->notified_task_depth_capped(1) != 0 ||
        fairlane_owner_debt_pending();
    self_->sig().ops += n;
    return n + local_work;
}

template <bool Fused>
template <uint32_t BatchOps,
          bool IofusedPrivateQueue>
uint32_t ExLoopT<Fused>::r2_drain_tasks(bool unmasked) {
    Task batch[BatchOps];
    uint32_t held = 0;
    auto take = [&](const Task& t) {
        batch[held++] = t;
        if (held == BatchOps) {
            r2_exec_batch<IofusedPrivateQueue>(batch, held);
            held = 0;
        }
    };
    const uint32_t n = unmasked
        ? self_->drain_tasks_unmasked<IofusedPrivateQueue>(take)
        : self_->drain_tasks<IofusedPrivateQueue>(take);
    if (held) r2_exec_batch<IofusedPrivateQueue>(batch, held);
    self_->sig().ops += n;
    return n;
}

template <bool Fused>
template <uint32_t BatchOps, bool IofusedPrivateQueue, typename Filler>
uint32_t ExLoopT<Fused>::r2_drain_tasks_with_filler(bool unmasked, Filler& filler, bool& filler_used) {
    Task batch[BatchOps];
    uint32_t held = 0;
    auto execute_batch = [&] {
        if (!held) return;
        if (!filler_used && xshard_retries_.empty()) {
            r2_prefetch_and_reorder_batch(batch, held);
            filler();
            filler_used = true;
            exec_batch_prefetched<IofusedPrivateQueue>(batch, held);
        } else {
            r2_exec_batch<IofusedPrivateQueue>(batch, held);
        }
        held = 0;
    };
    auto take = [&](const Task& task) {
        batch[held++] = task;
        if (held == BatchOps) execute_batch();
    };
    const uint32_t n = unmasked
        ? self_->drain_tasks_unmasked<IofusedPrivateQueue>(take)
        : self_->drain_tasks<IofusedPrivateQueue>(take);
    execute_batch();
    self_->sig().ops += n;
    return n;
}

template <bool Fused>
template <bool ScreenReorder>
bool ExLoopT<Fused>::r2_prefetch_exec_batch(const Task* batch, uint32_t n) {
    // The disabled instantiation contains no screen; the armed one seeds in this walk.
    // The armed uniform arm reuses the original per-task flag test with a different mask.
    using Screen = std::conditional_t<ScreenReorder, r2::ExReorderScreen, std::nullptr_t>;
    [[maybe_unused]] Screen screen{};
    for (uint32_t i = 0; i < n; i++) {
        if (!batch[i].client) continue;
        const Op& op = batch[i].client->rob().at(batch[i].op_id);
        const int32_t shard = batch[i].shard >= 0 ? batch[i].shard : op.shard;
        // The shipped coarse batch must obey the same resolve -> verify-owner -> store-touch
        // order as pipelined E1. A route can go stale after enqueue; even a prefetch through
        // the old FlatStore is formally an ownership violation under TSAN's model.
        if (shard >= 0 && !batch[i].scatter &&
            srv_->worker_of_shard(shard) == self_->id()) {
            const uint32_t flags = op.spec->flags;
            if constexpr (ScreenReorder) {
                if (screen.prefetch(flags)) srv_->shard(shard).store().prefetch(op.hash);
            } else {
                if (!(flags & r2::ExReorderScreen::kPrefetchSkip))
                    srv_->shard(shard).store().prefetch(op.hash);
            }
        }
    }
    if constexpr (ScreenReorder) return screen.mixed();
    else return false;
}

template <bool Fused>
template <size_t BatchOps>
void ExLoopT<Fused>::r2_prefetch_and_reorder_batch(Task (&batch)[BatchOps], uint32_t n) {
    if (__builtin_expect(reorder_enabled_ && n > 1, false)) {
        // All hints still precede execution and each bucket is hinted once. Screening at
        // this existing walk removes the scheduler's separate class scan from uniform
        // batches. Stale routes excluded by prefetch need no scheduling on this owner;
        // execute still forwards them before any store access. No filler or execution is
        // moved across this boundary. Only mixed batches touch the scheduler/stats sidecar.
        if (__builtin_expect(r2_prefetch_exec_batch<true>(batch, n), false))
            srv_->mode_schedule_stats(self_->id()).note_reorder(n, r2::ex_schedule_batch(batch, n));
    } else {
        r2_prefetch_exec_batch(batch, n);
    }
}

template <bool Fused>
template <bool IofusedPrivateQueue, size_t BatchOps>
void ExLoopT<Fused>::r2_exec_batch(Task (&batch)[BatchOps], uint32_t n) {
    // Deferral first, then one prefetch pass which also screens armed batches for a static
    // cost mix. A uniform batch never calls the scheduler, regardless of its ROB ranks.
    if (!xshard_retries_.empty()) {
        for (uint32_t i = 0; i < n; i++) ordered_deferred_.push_back(batch[i]);
        return;
    }
    r2_prefetch_and_reorder_batch(batch, n);
    exec_batch_prefetched<IofusedPrivateQueue>(batch, n);
}

template <bool HasUnix, bool HasTls, bool kEp, bool Fused,
          uint8_t Pipeline, bool SplitLocal>
void IoLoop::r2_run_loop() {
    static_assert(Pipeline <= 1);
    if constexpr (Fused && Pipeline == 1 && !SplitLocal) {
        // Fused overlap uses the occupancy-gated schedule on the fixed producer lanes.
        r2_run_fused_iofused_loop<HasUnix, HasTls, kEp, true>();
        return;
    }
    static_assert(!SplitLocal || Fused);
    constexpr bool IoPipe = (!Fused || SplitLocal) && Pipeline == 1;
    if constexpr (Fused) {
        if (srv_->read_local_enabled()) {
            // A split EX tenure is permanently parked: it never probes the local lane.
            // Resume BEFORE sampling the epoch, as at the existing network-wait boundary.
            if (ThreadCtx::read_local_publication_parked(self_->read_local_publication()))
                self_->resume_read_local_tick();
            self_->publish_read_local_tick(srv_->read_local_epoch());
            self_->set_read_local_lane_active(true);
        }
    }
    if constexpr (!kEp) {
        if (listen_fd_ >= 0) arm_accept(UrKind::Accept);
        if constexpr (HasTls) arm_accept(UrKind::TlsAccept);
        if constexpr (HasUnix) if (unix_listen_fd_ >= 0) arm_accept(UrKind::UnixAccept);
    }
    LoopSignals& sig = self_->sig();
    while (!self_->stop_flag().load(std::memory_order_relaxed) &&
           self_->role() == Role::Ifid) {
        refresh_notify_config();
        // ONE relaxed load per io batch. Per-batch checks are free; this is what buys the
        // per-operation hooks their zero-cost-when-off property.
        if (__builtin_expect(srv_->climon_armed() != climon_armed_cached_, false))
            climon_refresh_armed();
        const bool pause_armed = climon_pause_armed();
        const bool client_cron_armed = !srv_->flip_dispatch_paused() &&
                                       srv_->client_cron_armed();
        const bool client_lb_signal_armed = client_lb_signal_armed_;
        const bool lb_controller_armed = lb_controller_armed_;
        // Placement's dense role vectors are mutated only under FLIP's global dispatch
        // barrier. Do not consult them from an IO pass while that cold transaction is live.
        const bool save_cron_armed = !srv_->flip_dispatch_paused() &&
                                     srv_->save_cron_writer(self_->id());
        const bool client_cron_newly_armed = client_cron_armed && !client_cron_was_armed_;
        if (!client_cron_armed && __builtin_expect(client_cron_was_armed_, false)) {
            // Turning the last client cron consumer off also retires output accounting once.
            // The disabled write-back specialization then has no per-serve cleanup branch.
            for (Client* c : self_->clients()) c->stop_obuf_tracking();
        }
        client_cron_was_armed_ = client_cron_armed;
        sig.iterations++;
        reap_dead();               // free clients dead for a full iteration -- see close_client
        scatter_pool_.reap_deferred();

        uint32_t did = 0;
        bool submitted = false;
        bool natural_order = false;
        if constexpr (IoPipe)
            natural_order = iopipe_depth_gate_.loop_boundary(sig.ops);
        {
            Span busy(sig.busy_ns);
            // The work-span clock is already sampled once for this pass. Reuse that cut for
            // every monotonic millisecond consumer instead of issuing separate clock_gettime
            // reads for pause, cron and WAIT. A pass is microseconds; their public granularity
            // is milliseconds or seconds.
            bool pass_time_cached = pause_armed || client_cron_armed || save_cron_armed ||
                                    client_lb_signal_armed || lb_controller_armed ||
                                    !deferred_timers_.empty();
            if (__builtin_expect(pass_time_cached, true)) {
                cached_now_ms_ = busy.start_ns() / 1000000ull;
                cached_now_s_ = static_cast<uint32_t>(cached_now_ms_ / 1000);
            }
            if (__builtin_expect(pause_armed &&
                                 cached_now_ms_ >= climon_pause_deadline_ms_, false))
                climon_release_pause();
            if (client_cron_newly_armed) {
                for (Client* c : self_->clients()) c->set_last_interaction_s(cached_now_s_);
                client_cron_beat_ms_ = cached_now_ms_;
            }
            if (self_->sample_depth(busy.start_ns() / 1000)) {
                // CLOCK_THREAD_CPUTIME_ID can require a real syscall. cpu_ns is diagnostic
                // only (the placement controller deliberately uses busy/idle), so sample it
                // on the existing 100us signal beat instead of every hot pass.
                sig.cpu_ns = thread_cpu_ns();
                refresh_age_sampling();
                if (age_signals_armed_) sample_rob_head_age(sig.cached_now_us);
            }
            // A dropped accept re-arm means the server stops taking connections entirely, so it
            // is retried every pass until it lands.
            if constexpr (!kEp) {
                if (accept_pending_) arm_accept(UrKind::Accept);
                if constexpr (HasTls) if (tls_accept_pending_) arm_accept(UrKind::TlsAccept);
                if constexpr (HasUnix)
                    if (unix_accept_pending_) arm_accept(UrKind::UnixAccept);
            }
            if constexpr (!IoPipe) {
                // In epoll mode this drains the doorbell mailbox instead of a CQ ring; the tag
                // stream, and therefore this switch, is identical. See uring.h.
                did += ring_.for_each_cqe(
                    [&](io_uring_cqe* cqe) {
                        on_cqe<HasTls, kEp, Fused, Pipeline>(cqe);
                    });
                if constexpr (kEp)
                    did += epoll_pass<HasUnix, HasTls, Fused, Pipeline>(0);
            }
            did += service_client_migrations<kEp>();
            did += drain_client_transfers<kEp>();
            did += scatter_pool_.refresh_snapshot_floor(*srv_, self_->id());
            if constexpr (HasUnix) did += flush_handoffs();
            did += multi_owner_pass_entry(*this);
            if (srv_->aof().writer_is(self_->id()))
                did += srv_->aof().writer_pass(*self_, ring_);
            if (srv_->snapshot().writer_is(self_->id()))
                did += srv_->snapshot().writer_pass(*self_, ring_);
            if (__builtin_expect(!deferred_timers_.empty(), false)) {
                // CQ processing above may have created the first timer after the prologue.
                if (!pass_time_cached) {
                    cached_now_ms_ = busy.start_ns() / 1000000ull;
                    cached_now_s_ = static_cast<uint32_t>(cached_now_ms_ / 1000);
                    pass_time_cached = true;
                }
                did += deferred_timer_pass(cached_now_ms_);
            }
            did += flush_borrow_releases();
            if constexpr (IoPipe) {
                if (__builtin_expect(!routing_forward_.empty(), false))
                    client_routing_cleanup_pass();
                did += pipeline_pass<HasUnix, HasTls, kEp, SplitLocal>(
                    false, natural_order, submitted);
            } else if constexpr (Fused) {
                if (__builtin_expect(!routing_forward_.empty(), false))
                    client_routing_cleanup_pass();
                did += r2_flush_ready<HasTls, kEp, true, HasUnix>();
            } else {
                did += collect_retire_work<HasUnix, kEp>();
                if (__builtin_expect(!routing_forward_.empty(), false))
                    client_routing_cleanup_pass();
                did += r2_flush_ready<HasTls, kEp>();
            }
            did += flip_control_pass<kEp>();
            if (__builtin_expect(client_lb_signal_armed &&
                                 cached_now_ms_ >= lb_client_signal_beat_ms_, false)) {
                did += lb_client_signal_pass();
                lb_client_signal_beat_ms_ = cached_now_ms_ + 1000;
            }
            did += lb_control_pass();
            if (__builtin_expect(lb_controller_armed &&
                                 cached_now_ms_ >= lb_controller_beat_ms_, false)) {
                lb_controller_beat_ms_ = cached_now_ms_ + srv_->lb_tick_ms();
                if (srv_->lb_cron_writer(self_->id()) &&
                    srv_->lb_controller_tick(self_->id(), cached_now_ms_))
                    lb_schedule_wake_all();
                did++;
            }
            did += lb_wake_all_pass();
            if (__builtin_expect(client_cron_armed &&
                                 cached_now_ms_ >= client_cron_beat_ms_, false)) {
                did += client_cron_pass();
                client_cron_beat_ms_ = cached_now_ms_ + 100;
            }
            if (__builtin_expect(save_cron_armed &&
                                 cached_now_ms_ >= save_cron_beat_ms_, false)) {
                did += srv_->save_cron_pass(*self_, ring_);
                save_cron_beat_ms_ = cached_now_ms_ + 1000;
            }
        }
        // Flush prepared SQEs before looping. Recv re-arms and cross-ring wakes are
        // PREPARED during the work section but only reach the kernel on submit; taking
        // the busy path without submitting strands them in the SQ forever, and the peer
        // that is waiting on that wake never runs.
        if (did) {
            if constexpr (IoPipe) {
                if (!submitted || ring_.sq_ready()) ring_.submit_and_reap();
            } else {
                ring_.submit_and_reap();
            }
            continue;
        }

        // Nothing to do: declare intent to block, re-check (a producer may have pushed between
        // the last drain and the flag being set), then wait.
        // Mask-independent sweep before parking. The mask is a hint for the hot path; it must
        // not be the only thing that can find queued work, or one lost bit wedges a connection
        // forever. Runs only when this thread has already concluded it has nothing to do.
        uint32_t sweep_work = 0;
        if constexpr (IoPipe)
            sweep_work = pipeline_sweep<HasUnix, HasTls, kEp, SplitLocal>(
                natural_order, submitted);
        else
            sweep_work = r2_sweep<HasUnix, HasTls, kEp, Fused>();
        if (sweep_work) {
            if constexpr (IoPipe) {
                if (!submitted || ring_.sq_ready()) ring_.submit_and_reap();
            } else {
                ring_.submit_and_reap();
            }
            continue;
        }

        Span idle(sig.idle_ns);
        if constexpr (Fused) {
            if (__builtin_expect(srv_->read_local_enabled(), false))
                self_->publish_read_local_parked(srv_->read_local_epoch());
        }
        self_->arm_blocked();
        if constexpr (kEp) {
            // The park. Same 50ms ceiling as the ring wait, and for the same reason: the stop
            // flag is only re-read at the top of the loop, so an unbounded block would make
            // shutdown depend on a connection arriving.
            if constexpr (Fused) {
                if (!self_->any_fused_inbound())
                    epoll_pass<HasUnix, HasTls, !SplitLocal, Pipeline>(50);
            } else if (!self_->any_io_inbound()) {
                epoll_pass<HasUnix, HasTls, false, Pipeline>(50);
            }
        } else {
            if constexpr (Fused) {
                if (!self_->any_fused_inbound()) ring_.submit_and_wait(1);
                else                            ring_.submit_and_reap();
            } else {
                if (!self_->any_io_inbound()) ring_.submit_and_wait(1);
                else                         ring_.submit_and_reap();
            }
        }
        if constexpr (Fused) {
            // Become active conservatively before sampling the epoch. With the retirement RMW
            // and grace scan in the same seq-cst order, a reclaimer either sees this old tick
            // and waits or completed while we were parked; the epoch sample then acquires that
            // unlink before any later foreign slot probe.
            if (__builtin_expect(srv_->read_local_enabled(), false)) {
                self_->resume_read_local_tick();
                self_->publish_read_local_tick(srv_->read_local_epoch());
            }
        }
        self_->clear_blocked();
    }
    if constexpr (Fused) {
        // The read loop is over for this tenure. Teardown may take longer than another
        // owner's bounded retire queue can tolerate, but it performs no foreign store probe.
        if (srv_->read_local_enabled()) {
            self_->set_read_local_lane_active(false);
            self_->publish_read_local_parked(srv_->read_local_epoch());
        }
    }
    // A close requested by the last pass's read/send path has no later flush_ready to drain it,
    // and an undrained entry would show up as a live connection in the shutdown accounting.
    if constexpr (kEp) {
        while (!epoll_closes_.empty()) {
            Client* victim = epoll_closes_.back();
            epoll_closes_.pop_back();
            epoll_close_now(victim);
        }
    }
    if (srv_->aof().writer_is(self_->id()))
        srv_->aof().writer_shutdown(*self_, ring_);
    // The normal loop deliberately keeps a dead Client for two prologues so stale channel
    // entries cannot race its delete. At process shutdown all producers have observed the
    // shared stop flag and this IO owner is quiescent; finish those two deterministic grace
    // steps so TlsConn/SSL/BIO ownership is released before shutdown accounting is printed.
    reap_dead();
    reap_dead();
}

template <bool HasUnix, bool HasTls, bool kEp, bool ThreeWay>
void IoLoop::r2_run_fused_iofused_loop() {
    if (srv_->read_local_enabled()) {
        if (ThreadCtx::read_local_publication_parked(self_->read_local_publication()))
            self_->resume_read_local_tick();
        self_->publish_read_local_tick(srv_->read_local_epoch());
        self_->set_read_local_lane_active(true);
    }
    if constexpr (!kEp) {
        if (listen_fd_ >= 0) arm_accept(UrKind::Accept);
        if constexpr (HasTls) arm_accept(UrKind::TlsAccept);
        if constexpr (HasUnix)
            if (unix_listen_fd_ >= 0) arm_accept(UrKind::UnixAccept);
    }
    LoopSignals& sig = self_->sig();
    WbPipelineBatch wb_batch;
    uint32_t non_send_rotations = 0;
    bool three_way_gate_open = false;

    while (!self_->stop_flag().load(std::memory_order_relaxed) &&
           self_->role() == Role::Ifid) {
        refresh_notify_config();
        if (__builtin_expect(srv_->climon_armed() != climon_armed_cached_, false))
            climon_refresh_armed();
        const bool pause_armed = climon_pause_armed();
        const bool client_cron_armed = !srv_->flip_dispatch_paused() &&
                                       srv_->client_cron_armed();
        const bool client_lb_signal_armed = client_lb_signal_armed_;
        const bool lb_controller_armed = lb_controller_armed_;
        const bool save_cron_armed = !srv_->flip_dispatch_paused() &&
                                     srv_->save_cron_writer(self_->id());
        const bool client_cron_newly_armed =
            client_cron_armed && !client_cron_was_armed_;
        if (!client_cron_armed && __builtin_expect(client_cron_was_armed_, false))
            for (Client* c : self_->clients()) c->stop_obuf_tracking();
        client_cron_was_armed_ = client_cron_armed;
        sig.iterations++;
        reap_dead();
        scatter_pool_.reap_deferred();

        uint32_t did = 0;
        {
            Span busy(sig.busy_ns);
            bool pass_time_cached = pause_armed || client_cron_armed || save_cron_armed ||
                                    client_lb_signal_armed || lb_controller_armed ||
                                    !deferred_timers_.empty();
            if (__builtin_expect(pass_time_cached, true)) {
                cached_now_ms_ = busy.start_ns() / 1000000ull;
                cached_now_s_ = static_cast<uint32_t>(cached_now_ms_ / 1000);
            }
            if (__builtin_expect(pause_armed &&
                                 cached_now_ms_ >= climon_pause_deadline_ms_, false))
                climon_release_pause();
            if (client_cron_newly_armed) {
                for (Client* c : self_->clients())
                    c->set_last_interaction_s(cached_now_s_);
                client_cron_beat_ms_ = cached_now_ms_;
            }
            if (self_->sample_depth(busy.start_ns() / 1000)) {
                sig.cpu_ns = thread_cpu_ns();
                refresh_age_sampling();
                if (age_signals_armed_) sample_rob_head_age(sig.cached_now_us);
            }
            if constexpr (!kEp) {
                if (accept_pending_) arm_accept(UrKind::Accept);
                if constexpr (HasTls)
                    if (tls_accept_pending_) arm_accept(UrKind::TlsAccept);
                if constexpr (HasUnix)
                    if (unix_accept_pending_) arm_accept(UrKind::UnixAccept);
            }
            did += service_client_migrations<kEp>();
            did += drain_client_transfers<kEp>();
            did += scatter_pool_.refresh_snapshot_floor(*srv_, self_->id());
            if constexpr (HasUnix) did += flush_handoffs();
            did += multi_owner_pass_entry_iofused(*this);
            if (srv_->aof().writer_is(self_->id()))
                did += srv_->aof().writer_pass(*self_, ring_);
            if (srv_->snapshot().writer_is(self_->id()))
                did += srv_->snapshot().writer_pass(*self_, ring_);
            if (__builtin_expect(!deferred_timers_.empty(), false)) {
                if (!pass_time_cached) {
                    cached_now_ms_ = busy.start_ns() / 1000000ull;
                    cached_now_s_ = static_cast<uint32_t>(cached_now_ms_ / 1000);
                    pass_time_cached = true;
                }
                did += deferred_timer_pass(cached_now_ms_);
            }
            did += flush_borrow_releases();
            if (__builtin_expect(!routing_forward_.empty(), false))
                client_routing_cleanup_pass();

            // N0 is the rotation's only completion harvest. Receive parsing and SEND follow-up
            // remain in the explicit IFID/WB body below.
            did += ring_.for_each_cqe([&](io_uring_cqe* cqe) {
                on_cqe<HasTls, kEp, true, 1>(cqe);
            });
            if constexpr (kEp)
                did += epoll_pass<HasUnix, HasTls, true, 1>(0);
            if constexpr (ThreeWay)
                did += r2_genthread_three_way_pass<HasUnix, HasTls, kEp>(
                    wb_batch, three_way_gate_open);
            else
                did += r2_genthread_iofused_pass<HasUnix, HasTls, kEp>(wb_batch);

            did += flip_control_pass<kEp>();
            if (__builtin_expect(client_lb_signal_armed &&
                                 cached_now_ms_ >= lb_client_signal_beat_ms_, false)) {
                did += lb_client_signal_pass();
                lb_client_signal_beat_ms_ = cached_now_ms_ + 1000;
            }
            did += lb_control_pass();
            if (__builtin_expect(lb_controller_armed &&
                                 cached_now_ms_ >= lb_controller_beat_ms_, false)) {
                lb_controller_beat_ms_ = cached_now_ms_ + srv_->lb_tick_ms();
                if (srv_->lb_cron_writer(self_->id()) &&
                    srv_->lb_controller_tick(self_->id(), cached_now_ms_))
                    lb_schedule_wake_all();
                did++;
            }
            did += lb_wake_all_pass();
            if (__builtin_expect(client_cron_armed &&
                                 cached_now_ms_ >= client_cron_beat_ms_, false)) {
                did += client_cron_pass();
                client_cron_beat_ms_ = cached_now_ms_ + 100;
            }
            if (__builtin_expect(save_cron_armed &&
                                 cached_now_ms_ >= save_cron_beat_ms_, false)) {
                did += srv_->save_cron_pass(*self_, ring_);
                save_cron_beat_ms_ = cached_now_ms_ + 1000;
            }
        }

        if (ring_.take_sq_full_submit()) non_send_rotations = 0;
        if (ring_.send_pending()) {
            ring_.submit_and_reap<true>();
            non_send_rotations = 0;
            continue;
        }
        if (did) {
            if (++non_send_rotations >= kGenthreadIoFusedCoalesceRotations) {
                ring_.submit_and_reap<true>();
                non_send_rotations = 0;
            }
            continue;
        }

        if constexpr (ThreeWay) three_way_gate_open = false;
        const uint32_t sweep_work =
            r2_genthread_iofused_sweep<HasUnix, HasTls, kEp>();
        if (sweep_work) {
            if (ring_.take_sq_full_submit()) non_send_rotations = 0;
            if (ring_.send_pending() ||
                ++non_send_rotations >= kGenthreadIoFusedCoalesceRotations) {
                ring_.submit_and_reap<true>();
                non_send_rotations = 0;
            }
            continue;
        }

        Span idle(sig.idle_ns);
        // All local captures were consumed by the pass/sweep above. An idle fused thread
        // must stop holding back another owner's bounded retire ring, just as in overlap 0.
        if (__builtin_expect(srv_->read_local_enabled(), false))
            self_->publish_read_local_parked(srv_->read_local_epoch());
        self_->arm_blocked();
        if constexpr (kEp) {
            if (!self_->any_fused_inbound())
                epoll_pass<HasUnix, HasTls, true, 1>(50);
        } else {
            if (!self_->any_fused_inbound()) ring_.submit_and_wait<true>(1);
            else                            ring_.submit_and_reap<true>();
        }
        non_send_rotations = 0;
        // Clear the parked bit BEFORE sampling the epoch, in the same seq-cst order as
        // the grace scan. The next pass may then capture foreign objects safely.
        if (__builtin_expect(srv_->read_local_enabled(), false)) {
            self_->resume_read_local_tick();
            self_->publish_read_local_tick(srv_->read_local_epoch());
        }
        self_->clear_blocked();
    }

    if (srv_->read_local_enabled()) {
        self_->set_read_local_lane_active(false);
        self_->publish_read_local_parked(srv_->read_local_epoch());
    }
    if constexpr (kEp) {
        while (!epoll_closes_.empty()) {
            Client* victim = epoll_closes_.back();
            epoll_closes_.pop_back();
            epoll_close_now(victim);
        }
    }
    clear_ifid_queue();
    if (srv_->aof().writer_is(self_->id()))
        srv_->aof().writer_shutdown(*self_, ring_);
    reap_dead();
    reap_dead();
}

template <bool HasUnix, bool HasTls, bool kEp, bool Fused>
uint32_t IoLoop::r2_sweep() {
    uint32_t work = 0;
    if constexpr (HasUnix) work += flush_handoffs();
    if constexpr (Fused) {
        work += service_client_migrations<kEp>() + drain_client_transfers<kEp>(true) +
                flush_borrow_releases() +
                r2_flush_ready<HasTls, kEp, true, HasUnix, true>();
    } else {
        work += service_client_migrations<kEp>() + drain_client_transfers<kEp>(true) +
                flush_borrow_releases() + collect_retire_work<HasUnix, kEp>(true) +
                r2_flush_ready<HasTls, kEp>();
    }
    if (__builtin_expect(!routing_forward_.empty(), false))
        client_routing_cleanup_pass();
    if (srv_->snapshot().writer_is(self_->id()))
        work += srv_->snapshot().writer_pass(*self_, ring_, true);
    if (srv_->aof().writer_is(self_->id()))
        work += srv_->aof().writer_pass(*self_, ring_, true);
    return work;
}

template <bool HasUnix, bool HasTls, bool kEp>
uint32_t IoLoop::r2_genthread_iofused_pass(WbPipelineBatch& batch) {
    if (batch.count || active_wb_context_) std::abort();
    active_wb_context_ = &batch;

    uint32_t work = collect_retire_work<HasUnix, kEp, true>();
    if (!pending_serve_.empty()) {
        AofManager& aof = srv_->aof();
        if (!aof_gate_target_) aof_gate_target_ = aof.posted_sequence();
        if (!aof.reply_gate_ready(aof_gate_target_)) {
            aof.register_send_gate_wait(self_->id());
        } else {
            aof_gate_target_ = 0;
            while (batch.count < kGenthreadPipelineWbBatchConns &&
                   !pending_serve_.empty()) {
                Client* client = pending_serve_.front();
                pending_serve_.pop_front();
                client->set_serve_pending(false);
                if (!client->dead()) {
                    batch.clients[batch.count] = client;
                    batch.count++;
                }
            }
        }
    } else {
        aof_gate_target_ = 0;
    }

    for (uint32_t i = 0; i < batch.count; i++) {
        Client* client = batch.clients[i];
        if (!client || client->dead()) continue;
        Rob<kRobWindow>& rob = client->rob();
        const uint64_t first = rob.flush_id();
        const uint64_t last = rob.dispatch_id();
        const uint64_t count = std::min<uint64_t>(
            last - first, kGenthreadWbPrefetchOpsPerConn);
        for (uint64_t off = 0; off < count; off++)
            __builtin_prefetch(&rob.at(first + off).state, 0, 3);
    }
    for (uint32_t i = 0; i < batch.count; i++) {
        Client* client = batch.clients[i];
        if (!client || client->dead()) continue;
        Rob<kRobWindow>& rob = client->rob();
        const uint64_t first = rob.flush_id();
        const uint64_t last = rob.dispatch_id();
        const uint64_t count = std::min<uint64_t>(
            last - first, kGenthreadWbPrefetchOpsPerConn);
        for (uint64_t off = 0; off < count; off++) {
            Op& op = rob.at(first + off);
            if (op.state.load(std::memory_order_acquire) != OpState::Done) break;
            if (!op.zc_ptr || op.zc_shard < 0 || !op.zc_len) continue;
            const uint32_t bytes = std::min(
                op.zc_len, kGenthreadWbBorrowPrefetchBytes);
            for (uint32_t pos = 0; pos < bytes; pos += kGenthreadCacheLineBytes)
                __builtin_prefetch(op.zc_ptr + pos, 0, 1);
        }
    }

    work += batch.count;
    work += genthread_ifid_batch<HasTls, kEp>();
    if (__builtin_expect(pubsub_pass_pending_, false)) work += pubsub_pass_flush();

    for (uint32_t i = 0; i < batch.count; i++) {
        Client*& submit_client = batch.clients[i];
        Client* client = submit_client;
        if (!client || client->dead()) continue;
        if (__builtin_expect(
                (climon_armed_cached_ & Server::kClimonReply) != 0, false) &&
            climon_reply_suppressed(client)) {
            bool submit_allowed;
            (void)climon_prepare_suppressed(client, submit_allowed);
            if (!submit_allowed) submit_client = nullptr;
            continue;
        }
        if constexpr (HasTls) {
            if (TlsConn* tls = tls_engine(client))
                (void)wb_.prepare_pipeline_tls<kEp, true>(*client, *tls);
            else if (TlsConn* slot = tls_slot_conn(client); slot && slot->ktls())
                (void)wb_.prepare_pipeline_ktls<kEp, true>(*client);
            else
                (void)wb_.prepare_pipeline<kEp, true>(*client);
        } else {
            (void)wb_.prepare_pipeline<kEp, true>(*client);
        }
    }
    for (uint32_t i = 0; i < batch.count; i++) {
        Client* client = batch.clients[i];
        if (!client || client->dead()) continue;
        bool retry_plain_submit = false;
        if constexpr (HasTls) {
            if (TlsConn* tls = tls_engine(client)) {
                (void)wb_.pump_tls<kEp, true>(*client, *tls);
                if (tls->socket_userspace() && tls->has_pinned_plain())
                    arm_tls_socket_poll<kEp>(client, tls->wanted());
                if (tls->failed())
                    close_client(client,
                                 tls->output_pending() || client->send_inflight());
            } else if (TlsConn* slot = tls_slot_conn(client); slot && slot->ktls()) {
                const bool sent = wb_.pump<kEp, true>(*client);
                retry_plain_submit = !kEp && !sent &&
                    !client->send_inflight() && !client->nothing_to_write();
            } else {
                const bool sent = wb_.pump<kEp, true>(*client);
                retry_plain_submit = !kEp && !sent &&
                    !client->send_inflight() && !client->nothing_to_write();
            }
        } else {
            const bool sent = wb_.pump<kEp, true>(*client);
            retry_plain_submit = !kEp && !sent &&
                !client->send_inflight() && !client->nothing_to_write();
        }
        if constexpr (kEp)
            if (wb_.take_send_failure()) epoll_close_now(client);
        if (retry_plain_submit && !client->dead()) {
            self_->sig().sqe_starved++;
            enqueue_serve(client);
        }
        if (!client->dead() && client->in_active()) enqueue_ifid(client);
    }
    batch.count = 0;
    active_wb_context_ = nullptr;

    work += fused_executor_->r2_fused_coarse_pass();
    return work;
}

template <bool HasUnix, bool HasTls, bool kEp>
uint32_t IoLoop::r2_genthread_three_way_pass(WbPipelineBatch& batch, bool& gate_open) {
    srv_->mode_schedule_stats(self_->id()).note_overlap(OverlapSchedule::Fused, gate_open);
    if (batch.count || active_wb_context_) std::abort();
    LoopSignals& sig = self_->sig();
    uint32_t occupancy = 0;
    auto note_ops_since = [&](uint64_t before) {
        const uint64_t delta = sig.ops >= before ? sig.ops - before : 0;
        occupancy = std::max<uint32_t>(
            occupancy, static_cast<uint32_t>(std::min<uint64_t>(delta, UINT32_MAX)));
    };

    if (!gate_open) {
        uint32_t work = 0;
        uint64_t before = sig.ops;
        work += genthread_ifid_batch<HasTls, kEp>();
        note_ops_since(before);

        before = sig.ops;
        work += fused_executor_->r2_fused_coarse_pass();
        note_ops_since(before);

        work += collect_retire_work<HasUnix, kEp, true>();
        uint32_t wb_occupancy = 0;
        work += genthread_wb_batch<HasTls, kEp, true>(&wb_occupancy);
        occupancy = std::max(occupancy, wb_occupancy);
        gate_open = occupancy >= kGenthreadThreeWayMinBatchOccupancy;
        return work;
    }

    active_wb_context_ = &batch;
    uint32_t work = collect_retire_work<HasUnix, kEp, true>();
    if (!pending_serve_.empty()) {
        AofManager& aof = srv_->aof();
        if (!aof_gate_target_) aof_gate_target_ = aof.posted_sequence();
        if (!aof.reply_gate_ready(aof_gate_target_)) {
            aof.register_send_gate_wait(self_->id());
        } else {
            aof_gate_target_ = 0;
            while (batch.count < kGenthreadPipelineWbBatchConns &&
                   !pending_serve_.empty()) {
                Client* client = pending_serve_.front();
                pending_serve_.pop_front();
                client->set_serve_pending(false);
                if (!client->dead()) batch.clients[batch.count++] = client;
            }
        }
    } else {
        aof_gate_target_ = 0;
    }

    for (uint32_t i = 0; i < batch.count; i++) {
        Client* client = batch.clients[i];
        if (!client || client->dead()) continue;
        Rob<kRobWindow>& rob = client->rob();
        const uint64_t first = rob.flush_id();
        const uint64_t last = rob.dispatch_id();
        const uint64_t count = std::min<uint64_t>(
            last - first, kGenthreadWbPrefetchOpsPerConn);
        for (uint64_t off = 0; off < count; off++)
            __builtin_prefetch(&rob.at(first + off).state, 0, 3);
    }
    for (uint32_t i = 0; i < batch.count; i++) {
        Client* client = batch.clients[i];
        if (!client || client->dead()) continue;
        Rob<kRobWindow>& rob = client->rob();
        const uint64_t first = rob.flush_id();
        const uint64_t last = rob.dispatch_id();
        const uint64_t count = std::min<uint64_t>(
            last - first, kGenthreadWbPrefetchOpsPerConn);
        for (uint64_t off = 0; off < count; off++) {
            Op& op = rob.at(first + off);
            if (op.state.load(std::memory_order_acquire) != OpState::Done) break;
            if (!op.zc_ptr || op.zc_shard < 0 || !op.zc_len) continue;
            const uint32_t bytes = std::min(
                op.zc_len, kGenthreadWbBorrowPrefetchBytes);
            for (uint32_t pos = 0; pos < bytes; pos += kGenthreadCacheLineBytes)
                __builtin_prefetch(op.zc_ptr + pos, 0, 1);
        }
    }

    const uint32_t wb_occupancy = batch.count;
    occupancy = std::max(occupancy, wb_occupancy);
    work += wb_occupancy;
    const uint64_t before_ifid = sig.ops;
    work += genthread_ifid_batch<HasTls, kEp>();
    note_ops_since(before_ifid);
    if (__builtin_expect(pubsub_pass_pending_, false)) work += pubsub_pass_flush();

    bool wb_filled = false;
    auto wb_filler = [&] {
        if (wb_filled) std::abort();
        wb_filled = true;
        for (uint32_t i = 0; i < batch.count; i++) {
            Client*& submit_client = batch.clients[i];
            Client* client = submit_client;
            if (!client || client->dead()) continue;
            if (__builtin_expect(
                    (climon_armed_cached_ & Server::kClimonReply) != 0, false) &&
                climon_reply_suppressed(client)) {
                bool submit_allowed;
                (void)climon_prepare_suppressed(client, submit_allowed);
                if (!submit_allowed) submit_client = nullptr;
                continue;
            }
            if constexpr (HasTls) {
                if (TlsConn* tls = tls_engine(client))
                    (void)wb_.prepare_pipeline_tls<kEp, true>(*client, *tls);
                else if (TlsConn* slot = tls_slot_conn(client); slot && slot->ktls())
                    (void)wb_.prepare_pipeline_ktls<kEp, true>(*client);
                else
                    (void)wb_.prepare_pipeline<kEp, true>(*client);
            } else {
                (void)wb_.prepare_pipeline<kEp, true>(*client);
            }
        }
        for (uint32_t i = 0; i < batch.count; i++) {
            Client* client = batch.clients[i];
            if (!client || client->dead()) continue;
            bool retry_plain_submit = false;
            if constexpr (HasTls) {
                if (TlsConn* tls = tls_engine(client)) {
                    (void)wb_.pump_tls<kEp, true>(*client, *tls);
                    if (tls->socket_userspace() && tls->has_pinned_plain())
                        arm_tls_socket_poll<kEp>(client, tls->wanted());
                    if (tls->failed())
                        close_client(client,
                                     tls->output_pending() || client->send_inflight());
                } else if (TlsConn* slot = tls_slot_conn(client); slot && slot->ktls()) {
                    const bool sent = wb_.pump<kEp, true>(*client);
                    retry_plain_submit = !kEp && !sent &&
                        !client->send_inflight() && !client->nothing_to_write();
                } else {
                    const bool sent = wb_.pump<kEp, true>(*client);
                    retry_plain_submit = !kEp && !sent &&
                        !client->send_inflight() && !client->nothing_to_write();
                }
            } else {
                const bool sent = wb_.pump<kEp, true>(*client);
                retry_plain_submit = !kEp && !sent &&
                    !client->send_inflight() && !client->nothing_to_write();
            }
            if constexpr (kEp)
                if (wb_.take_send_failure()) epoll_close_now(client);
            if (retry_plain_submit && !client->dead()) {
                self_->sig().sqe_starved++;
                enqueue_serve(client);
            }
            if (!client->dead() && client->in_active()) enqueue_ifid(client);
        }
        batch.count = 0;
        active_wb_context_ = nullptr;
    };

    const uint64_t before_ex = sig.ops;
    work += fused_executor_->r2_fused_three_way_pass(wb_filler);
    note_ops_since(before_ex);
    if (!wb_filled || batch.count || active_wb_context_) std::abort();

    gate_open = occupancy >= kGenthreadThreeWayMinBatchOccupancy;
    return work;
}

template <bool HasUnix, bool HasTls, bool kEp>
uint32_t IoLoop::r2_genthread_iofused_sweep() {
    uint32_t work = 0;
    if constexpr (HasUnix) work += flush_handoffs();
    work += service_client_migrations<kEp>() + drain_client_transfers<kEp>(true) +
            flush_borrow_releases();
    work += genthread_ifid_batch<HasTls, kEp>();
    work += fused_executor_->r2_fused_coarse_sweep();
    work += collect_retire_work<HasUnix, kEp, true>(true) +
            genthread_wb_batch<HasTls, kEp>();
    if (__builtin_expect(!routing_forward_.empty(), false))
        client_routing_cleanup_pass();
    if (srv_->snapshot().writer_is(self_->id()))
        work += srv_->snapshot().writer_pass(*self_, ring_, true);
    if (srv_->aof().writer_is(self_->id()))
        work += srv_->aof().writer_pass(*self_, ring_, true);
    return work;
}

template <bool HasTls, bool kEp, bool Fused, bool HasUnix,
          bool SweepPass>
uint32_t IoLoop::r2_flush_ready() {
    uint32_t work = 0;
    backstop_pass_ = (++flush_tick_ >= kFlushBackstopEvery);
    if (backstop_pass_) flush_tick_ = 0;

    // PHASE 1 -- the read side, every active conn, BEFORE any serving. At 2048 conns the old
    // interleaved pass collapsed loop iterations 7.5x: each pass walked ~100 conns doing serve
    // and send work while drained recvs sat un-armed, sockets backed up, and arrivals went
    // bursty (113k park/wake round-trips where 22k belonged). Arming first keeps the arrival
    // stream flowing no matter how deep the reply backlog is -- which is exactly the property
    // that made 3s hold flat (-3.7%) at the conn count where 2s lost 21%.
    for (size_t idx = 0; idx < active_.size();) {
        Client* c = active_.at(idx);
        Client& conn = *c;
        DispatchResult dispatch_result = DispatchResult::Progress;
        TlsConn* tls = nullptr;
        if constexpr (HasTls) tls = tls_engine(c);
        if (backstop_pass_ && !c->serve_pending()) enqueue_serve(c);

        if constexpr (HasTls) {
            if (tls) {
                // BIO_nwrite0 pins the input-ring frontier until the recv CQE commits it.
                // SSL_write and opposite-direction BIO reads are proven safe while pinned,
                // but SSL_read/SSL_accept consume the same direction and can move that
                // frontier. Only the recv completion may drive inbound TLS while armed.
                if (!c->closing() && !c->recv_armed()) (void)drive_tls<kEp, Fused>(c);
                else if (tls->userspace()) {
                    (void)wb_.pump_tls<kEp>(*c, *tls);
                    if (tls->socket_userspace() && tls->has_pinned_plain())
                        arm_tls_socket_poll<kEp>(c, tls->wanted());
                }
                // A successful fd handshake can switch transport under drive_tls().
                tls = tls_engine(c);
                if constexpr (kEp) if (wb_.take_send_failure()) epoll_request_close(c);
            }
        }

        // Reset only when the ROB is quiescent AND no recv is outstanding — see conn.h. Then
        // re-arm, in that order.
        if (c->scatter_barrier()) {
            if (c->blocked() &&
                blocking_resume_move(*srv_, *self_, ring_, *c, scatter_pool_)) {
                enqueue_serve(c);
                work++;
            }
            // TEST HOOK (DEBUG BARRIER-HOLD) release, BEFORE the quiescence backstop so a
            // cleared latch and the backstop can both land in the same pass. Guarded on the
            // connection's own bit first, so production pays one byte test inside an arm that
            // already only runs when a barrier is set -- the server-wide load never happens.
            if (__builtin_expect(c->barrier_held_by(BarrierOwner::Debug), false) &&
                !srv_->debug_barrier_hold_armed())
                c->barrier_release(BarrierOwner::Debug);
            // With nothing in flight every production owner has completed by definition, so
            // this releases all of them at once. It is the backstop for the four owners
            // (WAIT, EXEC, pub/sub, CLIENT fan-out) that have no owner-scoped release site.
            if (c->rob().quiesced()) c->barrier_release_quiesced();
        }
        if (c->atomic_backpressure() && srv_->atomic_can_admit(self_->id()) &&
            scatter_pool_.can_register_snapshot())
            c->set_atomic_backpressure(false);
        // Success, pre-commit rollback, and synchronous validation refusal all end by publishing
        // Idle. The flag travels with a migrated Client, so this runs on whichever IO owns it
        // after the FLIP and retries the still-unconsumed frame in the re-parse below.
        if (c->flip_backpressure() && !srv_->flip_dispatch_paused())
            c->set_flip_backpressure(false);
        // Under epoll the second half of this guard is vacuous and would be actively
        // harmful: recv_armed_ means "an edge is owed", not "the kernel holds a pointer into
        // this buffer" (nothing ever does under this engine), so testing it would make the
        // steady state -- armed and quiet -- the one state in which the append-only read
        // buffer never resets, and a long-lived connection would grow to the soft cap and
        // stall there. Quiescence alone is the real precondition, and it still holds.
        if (c->rob().quiesced() && (kEp || !conn.recv_armed()))
            conn.reset_rbuf_at_quiescence();
        // Fill from the socket BEFORE the re-parse below, so bytes that arrived while the ROB
        // window was full are parsed in the same pass that freed the slots.
        if constexpr (kEp) {
            // A CLOSING CONNECTION OWES NO EDGE. Under io_uring this is automatic: arm_recv
            // refuses to re-arm a closing connection, so recv_armed_ falls to false as soon as
            // the outstanding recv completes and safe_to_release() opens. Under epoll nothing
            // completes -- the flag says "an edge is owed", and for a socket being torn down
            // that is simply false. Leaving it set makes safe_to_release() refuse forever, and
            // the connection is never released.
            //
            // The path that exposed this is CLIENT KILL on SELF, which reaches its victim
            // through mark_closing() rather than close_client() (the reply has to go out
            // first), so nothing else would ever clear the flag: the reply was delivered and
            // the socket then stayed open indefinitely. tests/climon.py's
            // "KILL self close-after-reply" is the regression cover.
            if (c->closing()) c->set_recv_armed(false);
            if (!c->closing()) {
                if constexpr (HasTls) {
                    if (tls) arm_tls_recv<kEp, Fused>(c);
                    else arm_recv<kEp>(c);
                } else {
                    arm_recv<kEp>(c);
                }
                if constexpr (HasTls) if (tls) {
                    (void)drive_tls<kEp, Fused>(c);
                    tls = tls_engine(c);
                }
                if (wb_.take_send_failure()) epoll_request_close(c);
            }
        }

        // Re-parse the buffered remainder. parse_and_dispatch stops when the ROB window fills
        // and is otherwise only driven by recv completions, so a client that sent a whole
        // pipeline in ONE write would get `window` replies and then hang. Retiring frees slots,
        // which is what makes the rest parseable.
        if (!c->closing() && conn.rpos() < conn.rlen() && !c->scatter_barrier() &&
            !c->parse_backpressure()) {
            // A CLIENT PAUSE hold deliberately leaves the parsed frame at rpos. Counting that
            // as work would spin the ring at 100% until the deadline instead of parking it,
            // so while a pause is live the pass reports progress only if the cursor moved.
            // With no pause armed the accounting is byte-for-byte the pre-lane behaviour --
            // one predicted-false test per active connection per pass. The dispatch variant
            // stays keyed on c->is_tls() (the kTLS handoff's contract), not the slot pointer.
            if (__builtin_expect(climon_pause_armed(), false)) {
                const uint32_t rpos_before = conn.rpos();
                if constexpr (HasTls) {
                    if (c->is_tls())
                        dispatch_result = parse_and_dispatch<
                            true, Fused ? kGenthreadIfidBatchOps : 0>(c);
                    else
                        dispatch_result = parse_and_dispatch<
                            false, Fused ? kGenthreadIfidBatchOps : 0>(c);
                } else {
                    dispatch_result = parse_and_dispatch<
                        false, Fused ? kGenthreadIfidBatchOps : 0>(c);
                }
                if (conn.rpos() != rpos_before) work++;
            } else {
                if constexpr (HasTls) {
                    if (c->is_tls())
                        dispatch_result = parse_and_dispatch<
                            true, Fused ? kGenthreadIfidBatchOps : 0>(c);
                    else
                        dispatch_result = parse_and_dispatch<
                            false, Fused ? kGenthreadIfidBatchOps : 0>(c);
                } else {
                    dispatch_result = parse_and_dispatch<
                        false, Fused ? kGenthreadIfidBatchOps : 0>(c);
                }
                if (__builtin_expect(
                        dispatch_result != DispatchResult::NeedInput, true))
                    work++;
            }
        }

        if constexpr (!kEp) {
            if constexpr (HasTls) {
                if (tls && tls->memory_bio()) arm_tls_recv<kEp, Fused>(c);
                else if (!tls) arm_recv<kEp>(c);
            } else {
                arm_recv<kEp>(c);
            }
        }

        // Progress marker: a full window with unparsed bytes (or an unarmed recv) means this
        // conn must stay active so later passes retry once retiring frees slots. We are our own
        // sender, so no poke protocol is needed -- the flush_ready pass IS the retry.
        const bool stuck = (conn.rpos() < conn.rlen() && c->rob().full()) ||
                           (!conn.recv_armed() && !c->closing());

        // NeedInput parks only the read side: the partial bytes stay buffered and a recv is
        // already armed. Unresolved local reads never hold parsing; conflicts reroute them.
        const bool more_input = conn.rpos() < conn.rlen() &&
                                dispatch_result != DispatchResult::NeedInput;
        const bool tls_output = tls && (tls->output_pending() || c->send_inflight());
        const bool done = c->rob().quiesced() && !more_input && !stuck &&
                          !c->serve_pending() && c->nothing_to_write() && !tls_output;
        // A close reached from inside the body (drive_tls, and under epoll the read/send
        // paths) may already have removed this client from the set and swapped an unvisited
        // one into its slot. Re-check identity before deciding, and do not advance past a slot
        // whose occupant changed -- the loop bound shrinks with every removal, so this
        // terminates.
        if (idx >= active_.size() || active_.at(idx) != c) continue;
        if (done && !c->closing()) { c->set_in_active(false); active_.erase_at(idx); }
        else if (c->closing() && !tls_output && c->safe_to_release()) {
            // Pub/sub teardown is asynchronous. Keep the client in place while home IOs
            // acknowledge removal; erase+reinsert would turn one closing subscriber into a
            // same-pass spin.
            if (!pubsub_disconnect_ready(c)) { idx++; }
            else { c->set_in_active(false); active_.erase_at(idx); close_client(c); }
        } else idx++;
    }
    // The epoll engine's deferred closes. A synchronous recv/send discovers a dead peer several
    // frames inside the walk above; closing it THERE would mutate the set under the walk, so
    // the sites queue instead and the teardown happens here, between phases, where nothing is
    // iterating. Duplicates are harmless -- close_client is idempotent on an already-dead
    // client and simply retries one whose quiescence fence has not opened yet.
    if constexpr (kEp) {
        while (!epoll_closes_.empty()) {
            Client* victim = epoll_closes_.back();
            epoll_closes_.pop_back();
            epoll_close_now(victim);
        }
    }

    // The fused loop rotates whole streams: finish the bounded IFID phase above, execute one
    // batch, collect its local self-lane completions, then enter the existing write-back phase.
    if constexpr (Fused) {
        work += SweepPass ? fused_executor_->r2_fused_baseline_sweep()
                          : fused_executor_->r2_fused_baseline_pass();
        work += collect_retire_work<HasUnix, kEp>(SweepPass);
    }

    // PUB/SUB PASS BOUNDARY -- between parsing and serving, on purpose. Everything this pass
    // parsed is resolved and appended to its subscribers' buffers HERE, so PHASE 2 sends one
    // coalesced write per subscriber instead of one per message. Off/unarmed servers pay one
    // predicted branch on a bool; all the machinery is out-of-line and cold.
    if (__builtin_expect(pubsub_pass_pending_, false)) work += pubsub_pass_flush();

    // PHASE 2 -- serve AT MOST kServeBudget conns from the FIFO. Bounding the pass is the
    // fourth application of the same law (per-pass work scales with what the pass does, not
    // with connection count): the leftovers stay queued, did > 0 keeps the loop from parking,
    // and FIFO order is arrival-order fairness across connections. Under overload the queue is
    // the latency -- which is the correct place for overload to live; throughput stays at peak.
    if (!pending_serve_.empty()) {
        AofManager& aof = srv_->aof();
        if (!aof_gate_target_) aof_gate_target_ = aof.posted_sequence();
        if (!aof.reply_gate_ready(aof_gate_target_)) {
            aof.register_send_gate_wait(self_->id());
            return work;
        }
        aof_gate_target_ = 0;
    } else {
        aof_gate_target_ = 0;
    }
    uint32_t served = 0;
    constexpr uint32_t serve_budget = Fused ? kGenthreadWbBatchConns : kServeBudget;
    while (served < serve_budget && !pending_serve_.empty()) {
        Client* c = pending_serve_.front();
        pending_serve_.pop_front();
        c->set_serve_pending(false);
        // Closing conns MUST still be served -- their ROB has to drain before quiesce can let
        // close_client finish. Only corpses (freed-pending) are skippable.
        if (c->dead()) continue;
        served++;
        // CLIENT REPLY OFF/SKIP. ONE predicted-false test per SERVED CONNECTION -- not per
        // operation: a p32 batch amortises it over 32 replies. The suppressed drain lives in
        // the cold object and discards bytes instead of staging them.
        if (__builtin_expect((climon_armed_cached_ & Server::kClimonReply) != 0, false) &&
            climon_reply_suppressed(c)) {
            work += climon_serve_suppressed(c);
            if constexpr (kEp) if (wb_.take_send_failure()) epoll_close_now(c);
            continue;
        }
        if constexpr (HasTls) {
            if (TlsConn* tls = tls_engine(c)) {
                if (wb_.serve_tls<kEp, false, Fused>(*c, *tls)) work++;
                if (tls->socket_userspace() && tls->has_pinned_plain())
                    arm_tls_socket_poll<kEp>(c, tls->wanted());
                if (tls->failed()) close_client(c, tls->output_pending() || c->send_inflight());
            } else if (TlsConn* slot = tls_slot_conn(c); slot && slot->ktls()) {
                if (wb_.serve_ktls<kEp, false, Fused>(*c)) work++;
            } else if (wb_.serve<kEp, false, Fused>(*c)) {
                work++;
            }
        } else if (wb_.serve<kEp, false, Fused>(*c)) {
            work++;
        }
        // A synchronous send has no CQE to report a fatal errno through, so the engine latches
        // it and the decision to tear the connection down is taken here instead. Consuming it
        // per served connection is deliberate: a bit left set would close the NEXT one.
        if constexpr (kEp) if (wb_.take_send_failure()) epoll_close_now(c);
    }
    work += served;
    return work;
}

template void ExLoopT<false>::r2_run();
template void ExLoopT<true>::r2_run();

namespace {

void pin_fused_thread(int cpu) {
    if (cpu < 0) return;
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
}

}  // namespace

void IoLoop::run_fused_reordered() {
    if (!fused_executor_) std::abort();
    const bool has_unix = unix_listen_fd_ >= 0 ||
                          (srv_->cfg().unixsocket && *srv_->cfg().unixsocket);
    auto run_pipeline = [&](auto pipeline_tag) {
        constexpr uint8_t Pipeline = decltype(pipeline_tag)::value;
        if (epoll_) {
            if (tls_context_) {
                if (has_unix) r2_run_loop<true, true, true, true, Pipeline>();
                else r2_run_loop<false, true, true, true, Pipeline>();
            } else {
                if (has_unix) r2_run_loop<true, false, true, true, Pipeline>();
                else r2_run_loop<false, false, true, true, Pipeline>();
            }
            return;
        }
        if (tls_context_) {
            if (has_unix) r2_run_loop<true, true, false, true, Pipeline>();
            else r2_run_loop<false, true, false, true, Pipeline>();
        } else {
            if (has_unix) r2_run_loop<true, false, false, true, Pipeline>();
            else r2_run_loop<false, false, false, true, Pipeline>();
        }
    };
    switch (srv_->cfg().overlap) {
        case 0: run_pipeline(std::integral_constant<uint8_t, 0>{}); break;
        case 1: run_pipeline(std::integral_constant<uint8_t, 1>{}); break;
        default: std::abort();
    }
}

int run_fused_server_reordered(Server& srv, const SnapshotLoadPlan* aof_base_plan,
                     const std::vector<std::unique_ptr<AofReplayPlan>>& aof_plans,
                     const SnapshotLoadPlan* load_plan, TlsContext* tls_context,
                     LateUnixListener& unix_listener,
                     ShutdownReportFinalLine& final_report) {
    const Config& cfg = srv.cfg();
    const uint32_t nthreads = srv.nthreads();
    std::printf("tomokv-cpp: %u unified threads, %u shard(s), thread-mode=1s,"
                " overlap=%u, %s, alloc=%s\n", nthreads, cfg.shards,
                cfg.overlap,
                cfg.net_io == NetIoEngine::Epoll ? "epoll" : "io_uring", alloc_backend());
    for (const ThreadPlacement& placement : srv.placement().threads())
        std::printf("  thread t%u: role=unified cpu=%d L3=%u shards=%zu send=self\n",
                    placement.id, placement.cpu, placement.domain,
                    srv.thread(placement.id).shards().size());
    std::fflush(stdout);

    std::vector<std::thread> pool;
    std::vector<IoLoop> ios(nthreads);
    std::vector<FusedExLoop> executors(nthreads);
    // ONE boot gate. The ad-hoc mutex/cv gate this replaced needed a separate `runners_stopped`
    // counter so a thread that saw shutdown while parked still reported at the gate (without it a
    // SIGTERM during a long snapshot recovery hung main forever). FusedBootGate keeps that property as a
    // first-class `gave_up` arrival, and every wait/advance also takes the stop edge, so the two
    // predicates cannot disagree.
    FusedBootGate boot(nthreads);
    // Identical to placement().ifid_threads().front() whenever a unixsocket is configured, but
    // read from the server so the LB's unix_owner_tid_ and the actual attach point cannot drift.
    const uint32_t unix_owner = srv.unix_owner_tid();
    auto report_graceful_shutdown = [&] {
        if (srv.read_local_enabled()) {
            // Joined fused readers cannot run another grace callback. Empty their private
            // retirement queues and disarm every store hook before taking the immutable report;
            // the subsequent atomic-record drain may detach more than a bounded callback list.
            for (FusedExLoop& executor : executors) executor.read_local_shutdown_drain();
            for (uint32_t sid = 0; sid < srv.nshards(); sid++)
                srv.shard(static_cast<int32_t>(sid)).store().configure_read_local(false, {});
        }
        // All owners and readers are quiescent. Release pending-entry references before IoLoop
        // destruction, then return their deferred ScatterState arenas to the correct IO-owned
        // pools. Server normally outlives those pools, so leaving this to FlatStore destructors
        // would leak the retained arenas.
        for (uint32_t sid = 0; sid < srv.nshards(); sid++)
            srv.shard(static_cast<int32_t>(sid)).store().atomic_shutdown_release_records();
        for (IoLoop& io : ios) io.reap_atomic_deferred();
        ShutdownReport report = collect_shutdown_report(srv, ios);
        print_shutdown_report_human(report);
        final_report.arm(std::move(report));
        acl_shutdown();
    };

    for (uint32_t tid = 0; tid < nthreads; tid++)
        pool.emplace_back([&, tid] {
            if (cfg.pin_threads) pin_fused_thread(srv.placement().cpu_of_thread(tid));
            ThreadCtx& self = srv.thread(tid);
            self.latch_placement(srv.topo());
            bind_thread_arena();
            bool ok = self.init_task_inbox_local_fused();
            if (ok) ok = executors[tid].init(&srv, &self, true);
            std::string local_error;
            if (ok && aof_base_plan)
                ok = snapshot_load_owned(*aof_base_plan, srv, self, local_error);
            if (ok && !aof_plans.empty()) {
                for (const auto& plan : aof_plans) {
                    if (!aof_load_owned(*plan, srv, self, local_error)) {
                        ok = false;
                        break;
                    }
                }
            } else if (ok && load_plan) {
                ok = snapshot_load_owned(*load_plan, srv, self, local_error);
            }
            if (ok)
                ok = ios[tid].init(&srv, &self, cfg.bind_addr, cfg.port, -1,
                                   tls_context, true);
            if (ok)
                self.bind_io_role_hooks(
                    &ios[tid],
                    [](void* p) { return static_cast<IoLoop*>(p)->prepare_activation(); },
                    [](void* p) { static_cast<IoLoop*>(p)->cancel_prepared_activation(); });
            if (ok)
                self.bind_client_registration_hooks(
                    [](void* p, Client* client) {
                        return static_cast<IoLoop*>(p)->prepare_client_registration(client);
                    },
                    [](void* p, Client* client) {
                        static_cast<IoLoop*>(p)->cancel_client_registration(client);
                    });
            if (ok)
                self.bind_client_capacity_hook(
                    [](void* p, uint32_t incoming) {
                        return static_cast<IoLoop*>(p)->prepare_client_transfer_capacity(incoming);
                    });
            if (ok) {
                executors[tid].activate_fused(&ios[tid].ring());
                ios[tid].bind_fused_executor(&executors[tid]);
                if (cfg.overlap == 0)
                    executors[tid].bind_fused_completion(
                        &ios[tid],
                        [](void* p, Client* client) {
                            static_cast<IoLoop*>(p)->fused_executor_completion<false>(client);
                        });
                else
                    executors[tid].bind_fused_completion(
                        &ios[tid],
                        [](void* p, Client* client) {
                            static_cast<IoLoop*>(p)->fused_executor_completion<true>(client);
                        });
                if (srv.read_local_enabled())
                    executors[tid].bind_read_local_demotion(
                        &ios[tid],
                        [](void* p, Client* client, const uint64_t* probed,
                           const ReadLocalFallbackReason* fallbacks,
                           uint32_t probed_count, uint32_t& demoted) {
                            return static_cast<IoLoop*>(p)->fused_demote_local_read_batch(
                                client, probed, fallbacks, probed_count, demoted);
                        });
                if (cfg.overlap == 0)
                    self.bind_fused_executor_hooks(
                        &executors[tid],
                        [](void* p) {
                            return static_cast<FusedExLoop*>(p)->r2_fused_baseline_pass();
                        },
                        [](void* p, SnapshotManager* manager) {
                            static_cast<FusedExLoop*>(p)->fused_snapshot_start(manager);
                        });
                else
                    self.bind_fused_executor_hooks(
                        &executors[tid],
                        [](void* p) {
                            // Snapshot's blocking progress loop has no WB filler to interleave.
                            // Use the private-lane coarse turn; the main overlap loop supplies
                            // the three-way callback only at its ordinary batch seam.
                            return static_cast<FusedExLoop*>(p)->r2_fused_coarse_pass();
                        },
                        [](void* p, SnapshotManager* manager) {
                            static_cast<FusedExLoop*>(p)->fused_snapshot_start(manager);
                        });
            }
            if (!boot.arrive_loaded(tid, ok, local_error)) return;
            if (!boot.wait_until_ready(tid, self.stop_flag())) return;
            if (!ios[tid].activate()) {
                boot.give_up(tid, "unified listener activation failed");
                return;
            }
            // arrive_ready() returns false on the stop edge: a worker can leave wait_until_ready(),
            // spend time arming its listeners, and come back after main already saw a signal. That
            // arrival is recorded as gave_up so main's wait still sees every thread report.
            if (!boot.arrive_ready(tid)) return;
            if (!boot.wait_until_running(tid, self.stop_flag())) return;
            self.publish_ready_role(Role::Ifid);
            ios[tid].run_fused_reordered();
            if (srv.read_local_enabled())
                self.publish_read_local_parked(srv.read_local_epoch());
            self.publish_ready_role(Role::Idle);
        });

    auto stop_workers = [&] {
        for (uint32_t tid = 0; tid < nthreads; tid++)
            srv.thread(tid).stop_flag().store(true, std::memory_order_relaxed);
        boot.stop();
        for (std::thread& worker : pool)
            if (worker.joinable()) worker.join();
    };
    if (!boot.wait_loaded(srv.shutting_down())) {
        stop_workers();
        const std::string error = boot.error();
        if (!error.empty()) std::fprintf(stderr, "persistence load failed: %s\n", error.c_str());
        const bool interrupted = srv.shutting_down().load(std::memory_order_relaxed);
        if (interrupted) report_graceful_shutdown();
        return interrupted ? 0 : 1;
    }
    srv.set_loading(false);
    if (srv.shutting_down().load(std::memory_order_relaxed)) {
        stop_workers();
        report_graceful_shutdown();
        return 0;
    }

    auto probe_listener = [&](uint32_t port, bool tls) {
        if (!port) return true;
        const int probe = IoLoop::make_reuseport_listener(
            cfg.bind_addr, port, cfg.tcp_backlog, tls);
        if (probe < 0) return false;
        ::close(probe);
        return true;
    };
    const bool port_ok = probe_listener(cfg.port, false);
    const bool tls_port_ok = port_ok && probe_listener(cfg.tls_port, true);
    if (!port_ok || !tls_port_ok) {
        std::perror(port_ok ? "bind tls-port" : "bind");
        stop_workers();
        return 1;
    }
    std::string unix_error;
    if (!unix_listener.open(cfg.tcp_backlog, unix_error)) {
        std::fprintf(stderr, "%s\n", unix_error.c_str());
        stop_workers();
        return 1;
    }
    if (unix_listener.fd() >= 0) {
        if (!ios[unix_owner].attach_listener(unix_listener.fd())) {
            std::fprintf(stderr, "unix listener attach failed on t%u\n", unix_owner);
            stop_workers();
            return 1;
        }
        (void)unix_listener.release_fd();
    }
    if (!boot.advance_ready(srv.shutting_down()) ||
        !boot.wait_ready(srv.shutting_down()) ||
        !boot.advance_running(srv.shutting_down())) {
        stop_workers();
        const std::string error = boot.error();
        if (!error.empty()) std::fprintf(stderr, "unified boot failed: %s\n", error.c_str());
        const bool interrupted = srv.shutting_down().load(std::memory_order_relaxed);
        if (interrupted) report_graceful_shutdown();
        return interrupted ? 0 : 1;
    }

    // Reached only when advance_running() succeeded, i.e. no stop edge was taken; the old
    // `if (!stopping)` guard around these lines is now the gate's own postcondition.
    if (cfg.port) std::printf("listening on %s:%u\n", cfg.bind_addr, cfg.port);
    if (cfg.tls_port) std::printf("listening with TLS on %s:%u\n", cfg.bind_addr, cfg.tls_port);
    if (unix_listener.bound()) std::printf("listening on unix:%s\n", cfg.unixsocket);
    std::fflush(stdout);

    for (std::thread& worker : pool) worker.join();
    // The unix socket file is unlinked by its RAII owner in main, for every return path.
    report_graceful_shutdown();
    return 0;
}


int run_fused_server_selected(Server& srv, const SnapshotLoadPlan* aof_base_plan,
                     const std::vector<std::unique_ptr<AofReplayPlan>>& aof_plans,
                     const SnapshotLoadPlan* load_plan, TlsContext* tls_context,
                     LateUnixListener& unix_listener,
                     ShutdownReportFinalLine& final_report) {
    // Even a callback choice in genthread.cc perturbs its parser inlining; keep
    // the one process-wide choice outside that original translation unit.
    if (srv.cfg().reorder)
        return run_fused_server_reordered(srv, aof_base_plan, aof_plans, load_plan,
                                          tls_context, unix_listener, final_report);
    return run_fused_server(srv, aof_base_plan, aof_plans, load_plan,
                            tls_context, unix_listener, final_report);
}
}  // namespace tomo
