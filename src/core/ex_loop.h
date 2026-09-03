// ex_loop.h — the EX stage. Executes ops against the shards it owns; a sender (io in 2s, wb in 3s)
// turns the completions into bytes. Same Channel signalling and LoopSignals units as io/wb loops.
//
//   in   task_in from IO threads         a parsed op to execute
//   out  ready-mask bit / client_in      "you have completed ops to retire" to the FIXED sender
//
// A worker owns no file descriptors, so its "events" are channel entries. It still owns a Ring
// because it needs somewhere to receive wakes.
//
// WAITING IS THE INTERESTING PART. A worker with an empty inbox must not spin a core at 100% — that
// is a real cost at 64 workers and it distorts every utilisation reading a controller might use. It
// also must not sleep so eagerly that it pays a wakeup per op under load. So: spin briefly, then arm
// the blocked flag, re-check, and block. Producers only pay a wake syscall while that flag is armed.
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <deque>
#include <type_traits>
#include "server.h"
#include "signal.h"
#include "genthread_pipeline.h"
#include "read_local.h"
#include "../net/conn.h"
#include "../net/resp.h"
#include "../net/uring.h"
#include "../net/wb.h"
#include "../cmd/command.h"
#include "../cmd/blocking.h"
#include "../cmd/multi.h"
#include "../cmd/notify.h"
#include "../cmd/slowlog.h"
#include "../cmd/xshard.h"
#include "../persist/aof.h"

namespace tomo {

// "Long enough to cover an inter-arrival gap, short enough not to burn a core." A starting point to
// measure, not a result.
inline constexpr uint32_t kExSpinBudget = 2048;

// How many ops are gathered before executing, so their storage prefetches can overlap. Large enough
// that the prefetches have time to land, small enough that the batch stays in L1.
inline constexpr uint32_t kExecBatch = kGenthreadExBatchOps;
inline constexpr uint32_t kActiveExpireChecks = 20;
// Parser-side demotion may reserve one additional point command behind the entire local run.
// Leave that credit outside the pending-read fanout budget so the combined reservation can always
// fit an empty producer lane and therefore cannot retry forever.
inline constexpr uint32_t kReadLocalDemotionBudget = kInboxSlots - 1;
inline constexpr uint32_t kExSchedClasses =
    static_cast<uint32_t>(CommandLengthClass::Count);
inline constexpr uint32_t kExSchedBuckets = kRobWindow * kExSchedClasses;
inline constexpr uint32_t kExSchedBucketWords = (kExSchedBuckets + 63) / 64;
static_assert(kExecBatch <= UINT8_MAX);
static_assert(kExecBatch <= 32);
static_assert(kGenthreadIfidBatchOps <= kExecBatch);
static_assert((kExecBatch & (kExecBatch - 1)) == 0);
static_assert(kExSchedBuckets == 192);

// Constructed only for an armed hash-precise point write whose owner has since enabled eviction.
// Keeping the existing maxmemory admission active but forcing NoEviction makes the IO-side promise
// self-fulfilling: this operation can update its routed key or fail, but cannot delete a different
// key behind a younger local read. The owner restores its live policy before the next task.
class ReadLocalPreciseWriteGuard {
public:
    explicit ReadLocalPreciseWriteGuard(FlatStore& store) : store_(&store) {
        previous_ = store_->script_suspend_eviction();
    }
    ~ReadLocalPreciseWriteGuard() { store_->script_restore_eviction(previous_); }
    ReadLocalPreciseWriteGuard(const ReadLocalPreciseWriteGuard&) = delete;
    ReadLocalPreciseWriteGuard& operator=(const ReadLocalPreciseWriteGuard&) = delete;

private:
    FlatStore* store_ = nullptr;
    MaxmemoryPolicy previous_ = MaxmemoryPolicy::NoEviction;
};

template <bool Enabled>
struct ReadLocalExState;

template <>
struct ReadLocalExState<false> {};

template <>
struct ReadLocalExState<true> {
    struct Impl {
        using DemoteFn = bool (*)(void*, Client*, const Task*,
                                  const ReadLocalFallbackReason*, uint32_t, uint32_t&);

        std::unique_ptr<Task[]> lane;
        // A failed probe can sit behind an earlier bounded demotion wave. Preserve its original
        // reason until that exact ROB op is lowered instead of reclassifying the suffix as Context.
        std::unique_ptr<ReadLocalFallbackReason[]> lane_fallbacks;
        uint32_t lane_head = 0;
        uint32_t lane_tail = 0;
        uint32_t lane_count = 0;
        // Upper-bound owner-task demand for every still-local lane entry. GET contributes one;
        // MGET contributes min(key count, shard count), which bounds its touched-shard fanout.
        // Keeping the sum within the demotion budget makes every task-capacity plan reservable
        // (snapshot pressure may still split it into waves).
        uint32_t lane_demotion_demand = 0;
        bool lane_has_tombstones = false;
        bool point_writes_precise = true;
        bool keymiss_notify_armed = false;
        void* demote_context = nullptr;
        DemoteFn demote = nullptr;
        ReadLocalDeferredQueue deferred;

        void rebind_owned_shards(ThreadCtx& owner) {
            ReadLocalRetireSink* sink = deferred.sink();
            if (!sink) std::abort();
            for (Shard* shard : owner.shards())
                shard->store().rebind_read_local_retire_sink(*sink);
        }
    };

    std::unique_ptr<Impl> impl;
};

using ReadLocalExImpl = ReadLocalExState<true>::Impl;
static_assert(std::is_empty_v<ReadLocalExState<false>>);

template <bool Fused>
class ExLoopT {
public:
    using FusedCompletionFn = void (*)(void*, Client*);

    WbEngine& engine() { return wb_; }
    bool init(Server* srv, ThreadCtx* self, bool dormant = false) {
        srv_ = srv; self_ = self;
        aof_manager_ = srv->aof().configured() ? &srv->aof() : nullptr;
        lru_clock_shift_ = static_cast<uint8_t>(srv->cfg().lru_clock_shift);
        lb_sample_rate_ = srv->key_lb_signals_enabled() ? srv->cfg().lb_sample_rate : 0;
        lb_sample_countdown_ = lb_sample_rate_;
        lb_controller_armed_ = srv->key_lb_signals_enabled();
        age_sample_rate_cached_ = srv->effective_age_sample_rate();
        ex_sched_enabled_ = srv->cfg().ex_sched != 0;
        pipeline_batches_ = Fused && srv->cfg().overlap != 0;
        iofused_ = Fused && srv->cfg().overlap == 1;
        if constexpr (Fused) {
            if (srv->read_local_enabled()) {
                std::unique_ptr<ReadLocalExImpl> impl(new (std::nothrow) ReadLocalExImpl);
                if (!impl) return false;
                impl->lane.reset(new (std::nothrow) Task[kInboxSlots]);
                impl->lane_fallbacks.reset(
                    new (std::nothrow) ReadLocalFallbackReason[kInboxSlots]);
                if (!impl->lane || !impl->lane_fallbacks ||
                    !impl->deferred.init(srv, self)) return false;
                impl->point_writes_precise =
                    srv->cfg().maxmemory == 0 ||
                    srv->cfg().maxmemory_policy == MaxmemoryPolicy::NoEviction;
                read_local_.impl = std::move(impl);
            }
        }
        if (!ring_.init(1024)) return false;
        fused_handoff_ring_ = &ring_;
        wb_.bind(&ring_);
        initialized_ = true;
        if (!dormant) activate();
        return true;
    }

    void activate() {
        if (!initialized_) std::abort();
        self_->set_ring(&ring_);
        self_->set_wb_engine(nullptr);
        blocking_bind_executor(srv_, self_, &ring_);
        for (Shard* shard : self_->shards())
            shard->bind_notify_pending(&notify_keyless_pending_);
    }

    // Fused tenure shares the physical thread with IoLoop. IoLoop remains the published wake
    // endpoint because it owns the only blocking wait; this ring still carries persistence CQEs.
    void activate_fused(Ring* handoff_ring) {
        static_assert(Fused);
        if (!initialized_) std::abort();
        // Buffered schedules put executor-originated task/client handoffs on the network ring.
        // That leaves this private ring with control/persistence SQEs; pipeline 1 can amortize its
        // submit boundary, and pipeline 2 can close N2 over all network work. Pipeline 0 retains
        // its existing ring ownership.
        if (srv_->cfg().overlap != 0 && handoff_ring)
            fused_handoff_ring_ = handoff_ring;
        blocking_bind_executor(srv_, self_, &ring_);
        if (read_local_enabled())
            self_->bind_read_local_retire_sink(*read_local_impl().deferred.sink());
        for (Shard* shard : self_->shards()) {
            shard->bind_notify_pending(&notify_keyless_pending_);
            if (read_local_enabled())
                shard->store().configure_read_local(true, *read_local_impl().deferred.sink());
        }
    }

    void bind_fused_completion(void* context, FusedCompletionFn completion) {
        static_assert(Fused);
        fused_io_context_ = context;
        fused_completion_ = completion;
    }

    void bind_read_local_demotion(void* context, ReadLocalExImpl::DemoteFn demote) {
        static_assert(Fused);
        if (!read_local_enabled() || !context || !demote) std::abort();
        read_local_impl().demote_context = context;
        read_local_impl().demote = demote;
    }

    bool enqueue_local_read(const Task& task) {
        static_assert(Fused);
        if (!read_local_enabled()) return false;
        auto& state = read_local_impl();
        if (!task.client) std::abort();
        const Op& op = task.client->rob().at(task.op_id);
        const uint32_t demand = read_local_task_demotion_demand(op);
        if (state.lane_count == kInboxSlots ||
            demand > kReadLocalDemotionBudget - state.lane_demotion_demand) return false;
        state.lane[state.lane_tail] = task;
        state.lane_fallbacks[state.lane_tail] = ReadLocalFallbackReason::None;
        state.lane_tail = (state.lane_tail + 1) & (kInboxSlots - 1);
        state.lane_count++;
        state.lane_demotion_demand += demand;
        return true;
    }

    bool local_read_lane_has_room(uint32_t demotion_demand = 1) const {
        static_assert(Fused);
        if (!read_local_enabled()) return false;
        const auto& state = read_local_impl();
        return state.lane_count != kInboxSlots &&
               demotion_demand <=
                   kReadLocalDemotionBudget - state.lane_demotion_demand;
    }

    void note_local_read_demoted(const Op& op) {
        static_assert(Fused);
        if (!read_local_enabled()) std::abort();
        release_local_read_demotion_demand(op);
        read_local_impl().lane_has_tombstones = true;
    }

    void preserve_local_read_fallback(Client* client, uint64_t op_id,
                                      ReadLocalFallbackReason reason) {
        static_assert(Fused);
        if (!read_local_enabled() || !client ||
            reason == ReadLocalFallbackReason::None) std::abort();
        auto& lane = read_local_impl();
        for (uint32_t offset = 0; offset < lane.lane_count; offset++) {
            const uint32_t index =
                (lane.lane_head + offset) & (kInboxSlots - 1);
            const Task& task = lane.lane[index];
            if (task.client != client || task.op_id != op_id) continue;
            if (!client->rob().pending_read_local(op_id)) std::abort();
            if (lane.lane_fallbacks[index] == ReadLocalFallbackReason::None)
                lane.lane_fallbacks[index] = reason;
            return;
        }
        std::abort();
    }

    void set_read_local_keymiss_notify(bool armed) {
        static_assert(Fused);
        if (!read_local_enabled()) std::abort();
        read_local_impl().keymiss_notify_armed = armed;
    }

    bool read_local_keymiss_notify_armed() const {
        static_assert(Fused);
        return read_local_enabled() && read_local_impl().keymiss_notify_armed;
    }

    void read_local_shutdown_drain() {
        static_assert(Fused);
        if (read_local_enabled()) (void)read_local_impl().deferred.drain_shutdown();
    }

    // One non-blocking executor batch in the coarse fused rotation. The network loop owns park;
    // this pass is the split executor body without its role loop or independent wait.
    uint32_t fused_pass() {
        static_assert(Fused);
        if (!pipeline_batches_)
            return fused_pass_impl<kGenthreadExBatchOps, true, false>();
        return iofused_
            ? fused_pass_impl<kGenthreadPipelineExBatchOps, true, true, true>()
            : fused_pass_impl<kGenthreadPipelineExBatchOps, true, false>();
    }

    uint32_t fused_baseline_pass() {
        static_assert(Fused);
        return fused_pass_impl<kGenthreadExBatchOps, true, false>();
    }

    // Deep generalized-thread traffic has already drained staged micro-batches at its one mode
    // transition. Keep the steady coarse pass free of empty pipeline-state probes.
    uint32_t fused_coarse_pass() {
        static_assert(Fused);
        return fused_pass_impl<kGenthreadPipelineExBatchOps, true, true, true>();
    }

    uint32_t fused_streams_pass() {
        static_assert(Fused);
        return fused_pass_impl<kGenthreadPipelineExBatchOps, true, false>();
    }

    // Buffered schedules keep control/persistence work in the executor owner but let the fused
    // loop own task gather/prefetch/execute. This has no internal park and never consumes a Task.
    uint32_t fused_pipeline_control() {
        static_assert(Fused);
        return fused_pass_impl<kGenthreadPipelineExBatchOps, false, false>();
    }

    template <uint32_t BatchOps, bool ConsumeTasks, bool CoalesceSubmit,
              bool IofusedPrivateQueue = false>
    uint32_t fused_pass_impl() {
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
        // lb_control_pass below.
        if (lb_rebind_pending_ && srv_->lb_stage() != LbStage::ExDrain)
            read_local_rebind_owned_shards_after_lb();
        const bool lb_frozen = lb_controller_armed_ && srv_->lb_dispatch_paused();
        if (!lb_frozen) refresh_live_config();
        if (maxmemory_enabled_)
            cached_lru_clock_ = static_cast<uint8_t>(
                (static_cast<uint64_t>(cached_now_ms_ / 1000) >> lru_clock_shift_) & 0x1f);

        uint32_t did = drain_local_reads();
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
                    if (xshard_retries_.empty() && ordered_deferred_.empty())
                        did += drain_tasks<BatchOps, IofusedPrivateQueue>(true);
                did += aof_flush_pass();
                did += drain_notify_keyless(self_->sig());
            }
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
                    if (xshard_retries_.empty() && ordered_deferred_.empty())
                        did += snapshot_owner_state_ == SnapshotOwnerState::None
                                   ? drain_tasks<BatchOps, IofusedPrivateQueue>()
                                   : drain_tasks_snapshot<BatchOps, IofusedPrivateQueue>();
            }
            if (__builtin_expect(srv_->blocking_waiters() != 0, false) &&
                cached_now_ms_ >= blocking_beat_ms_) {
                did += blocking_owner_cycle(*srv_, *self_, ring_, cached_now_ms_, true);
                blocking_beat_ms_ = cached_now_ms_ + 10;
            }
            did += aof_flush_pass();
            did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
            did += lb_control_pass();
            lb_bucket_bytes_pass();
        }
        if (read_local_enabled()) did += read_local_impl().deferred.drain_ready();
        if (did) {
            did += drain_notify_keyless(self_->sig());
            fused_submit_boundary<CoalesceSubmit>();
            fused_idle_spins_ = 0;
            return did;
        }
        if constexpr (!ConsumeTasks) return 0;
        if (lb_frozen) return 0;
        if (++fused_idle_spins_ < kExSpinBudget) return 0;
        fused_idle_spins_ = 0;
        did = sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
        if (did) fused_submit_boundary<CoalesceSubmit>();
        return did;
    }

    uint32_t fused_sweep(bool consume_tasks = true) {
        static_assert(Fused);
        if (!consume_tasks) {
            if (lb_controller_armed_ && srv_->lb_dispatch_paused())
                return iofused_
                    ? fused_pass_impl<kGenthreadPipelineExBatchOps, false, true, true>()
                    : fused_pass_impl<kGenthreadPipelineExBatchOps, false, false>();
            if (!pipeline_batches_)
                return fused_sweep_impl<kGenthreadExBatchOps, false, false>();
            return iofused_
                ? fused_sweep_impl<kGenthreadPipelineExBatchOps, false, true, true>()
                : fused_sweep_impl<kGenthreadPipelineExBatchOps, false, false>();
        }
        if (!pipeline_batches_)
            return fused_sweep_impl<kGenthreadExBatchOps, true, false>();
        return iofused_
            ? fused_sweep_impl<kGenthreadPipelineExBatchOps, true, true, true>()
            : fused_sweep_impl<kGenthreadPipelineExBatchOps, true, false>();
    }

    uint32_t fused_baseline_sweep() {
        static_assert(Fused);
        return fused_sweep_impl<kGenthreadExBatchOps, true, false>();
    }

    uint32_t fused_coarse_sweep() {
        static_assert(Fused);
        return fused_sweep_impl<kGenthreadPipelineExBatchOps, true, true, true>();
    }

    uint32_t fused_pipeline_control_sweep() {
        static_assert(Fused);
        return fused_sweep_impl<kGenthreadPipelineExBatchOps, false, false>();
    }

    template <uint32_t BatchOps, bool ConsumeTasks, bool CoalesceSubmit,
              bool IofusedPrivateQueue = false>
    uint32_t fused_sweep_impl() {
        if (lb_controller_armed_ && srv_->lb_dispatch_paused())
            return fused_pass_impl<BatchOps, ConsumeTasks, CoalesceSubmit,
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
        uint32_t did = drain_local_reads() +
            sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
        if (read_local_enabled()) did += read_local_impl().deferred.drain_ready();
        if (did) fused_submit_boundary<CoalesceSubmit>();
        return did;
    }

    void fused_snapshot_start(SnapshotManager* manager) {
        static_assert(Fused);
        begin_snapshot(manager);
    }

    Ring& ring() { return ring_; }

    void run() {
        LoopSignals& sig = self_->sig();
        uint32_t idle_spins = 0;

        while (!self_->stop_flag().load(std::memory_order_relaxed) &&
               self_->role() == Role::Ex) {
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
                    (static_cast<uint64_t>(cached_now_ms_ / 1000) >> lru_clock_shift_) & 0x1f);
            sig.iterations++;

            uint32_t did = 0;
            {
                Span busy(sig.busy_ns);
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
                            did += drain_tasks(true);
                        did += aof_flush_pass();
                        did += drain_notify_keyless(sig);
                    }
                    did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
                    did += flip_control_pass();
                    did += lb_control_pass();
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
                                       ? drain_tasks() : drain_tasks_snapshot();
                    }
                    if (__builtin_expect(srv_->blocking_waiters() != 0, false) &&
                        cached_now_ms_ >= blocking_beat_ms_) {
                        did += blocking_owner_cycle(
                            *srv_, *self_, ring_, cached_now_ms_, true);
                        blocking_beat_ms_ = cached_now_ms_ + 10;
                    }
                    did += aof_flush_pass();
                    did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
                    did += flip_control_pass();
                    did += lb_control_pass();
                    lb_bucket_bytes_pass();
                }
            }
            sig.cpu_ns = thread_cpu_ns();

            // Flush prepared SQEs before looping. Recv re-arms and cross-ring wakes are
            // PREPARED during the work section but only reach the kernel on submit; taking
            // the busy path without submitting strands them in the SQ forever, and the peer
            // that is waiting on that wake never runs.
            if (did) {
                did += drain_notify_keyless(sig);
                ring_.submit_and_reap(); idle_spins = 0; continue;
            }

            // A frozen executor must never fall through to sweep(): sweep owns expiry, MVCC
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
            if (sweep()) { ring_.submit_and_reap(); continue; }

            Span idle(sig.idle_ns);
            self_->arm_blocked();
            if (!self_->any_ex_inbound()) ring_.submit_and_wait(1);
            else                       ring_.submit_and_reap();
            self_->clear_blocked();
        }
    }

private:
    friend class IoLoop;

    bool read_local_enabled() const {
        if constexpr (Fused) return read_local_.impl != nullptr;
        return false;
    }

    ReadLocalExImpl& read_local_impl() {
        static_assert(Fused);
        if (!read_local_.impl) std::abort();
        return *read_local_.impl;
    }

    const ReadLocalExImpl& read_local_impl() const {
        static_assert(Fused);
        if (!read_local_.impl) std::abort();
        return *read_local_.impl;
    }

    bool read_local_point_writes_precise() const {
        return read_local_impl().point_writes_precise;
    }

    void set_read_local_point_writes_precise(bool precise) {
        read_local_impl().point_writes_precise = precise;
    }

    void read_local_rebind_owned_shards_after_lb() {
        if constexpr (Fused) {
            if (read_local_.impl) read_local_.impl->rebind_owned_shards(*self_);
        }
    }

    template <bool CoalesceSubmit>
    void fused_submit_boundary() {
        if constexpr (!CoalesceSubmit) {
            ring_.submit_and_reap();
        } else {
            if (ring_.take_sq_full_submit()) fused_non_submit_rotations_ = 0;
            if (++fused_non_submit_rotations_ >= kGenthreadIoFusedCoalesceRotations) {
                ring_.submit_and_reap();
                fused_non_submit_rotations_ = 0;
            }
        }
    }

    bool pipeline_tasks_allowed() const {
        if (snapshot_blocks_tasks()) return false;
        return !(lb_controller_armed_ && srv_->lb_dispatch_paused() &&
                 srv_->lb_acked(self_->id()));
    }

    Ring& handoff_ring() { return *fused_handoff_ring_; }

    void read_local_clear_reply(Op& op) {
        op.reply.clear();
        op.direct_len = 0;
        op.zc_ptr = nullptr;
        op.zc_len = 0;
        op.zc_shard = -1;
    }

    void compact_local_read_tombstones() {
        if constexpr (!Fused) return;
        auto& state = read_local_impl();
        if (!state.lane_has_tombstones) return;
        uint32_t kept = 0;
        const uint32_t old_count = state.lane_count;
        for (uint32_t offset = 0; offset < old_count; offset++) {
            const uint32_t from =
                (state.lane_head + offset) & (kInboxSlots - 1);
            const Task task = state.lane[from];
            // Test the full generation before touching its Op slot. The fused pass sweeps any
            // parser-created tombstone before WB's corpse-grace reaper can free its Client.
            if (!task.client || !task.client->rob().pending_read_local(task.op_id)) continue;
            const uint32_t to = (state.lane_head + kept) & (kInboxSlots - 1);
            state.lane[to] = task;
            state.lane_fallbacks[to] = state.lane_fallbacks[from];
            kept++;
        }
        state.lane_count = kept;
        state.lane_tail = (state.lane_head + kept) & (kInboxSlots - 1);
        state.lane_has_tombstones = false;
    }

    bool demote_local_read_batch(Client* client, const Task* probed,
                                 const ReadLocalFallbackReason* fallbacks,
                                 uint32_t probed_count, uint32_t& demoted) {
        static_assert(Fused);
        auto& lane = read_local_impl();
        if (!lane.demote || !lane.demote_context) std::abort();
        return lane.demote(
            lane.demote_context, client, probed, fallbacks, probed_count, demoted);
    }

    struct PreparedLocalRead {
        ReadLocalFallbackReason fallback = ReadLocalFallbackReason::None;
        uint32_t keyspace_hits = 0;
        uint32_t keyspace_misses = 0;
    };

    static bool read_local_mget(const Op& op) {
        return op.spec && command_is_read_local_mget(*op.spec);
    }

    uint32_t read_local_task_demotion_demand(const Op& op) const {
        if (!op.read_local()) std::abort();
        return read_local_mget(op)
            ? std::min<uint32_t>(op.argc() - 1, srv_->nshards()) : 1;
    }

    void release_local_read_demotion_demand(const Op& op) {
        auto& lane = read_local_impl();
        const uint32_t demand = read_local_task_demotion_demand(op);
        if (demand > lane.lane_demotion_demand) std::abort();
        lane.lane_demotion_demand -= demand;
    }

    PreparedLocalRead prepare_local_mget(Op& op) {
        static constexpr uint32_t kRetries = 3;
        static constexpr uint32_t kPrefetchKeys = 32;
        static constexpr uint32_t kMaxReadLocalShards = 256;
        const uint32_t key_count = op.argc() - 1;
        if (!key_count || srv_->nshards() > kMaxReadLocalShards) std::abort();

        uint64_t hashes[kPrefetchKeys];
        int32_t shards[kPrefetchKeys];
        const bool cached_routes = key_count <= kPrefetchKeys;
        if (cached_routes) {
            for (uint32_t key = 0; key < key_count; key++) {
                hashes[key] = FlatStore::hash_key(op.arg(key + 1));
                shards[key] = srv_->router().shard_of(hashes[key]);
                srv_->shard(shards[key]).store().read_local_prefetch(hashes[key]);
            }
        }

        for (uint32_t attempt = 0; attempt < kRetries; attempt++) {
            uint64_t states[kMaxReadLocalShards];
            uint64_t touched[kMaxReadLocalShards / 64] = {};
            PreparedLocalRead prepared;
            bool retry = false;
            read_local_clear_reply(op);
            reply_array_header(op.sink(), key_count);

            for (uint32_t key = 0; key < key_count; key++) {
                const Slice name = op.arg(key + 1);
                const uint64_t hash = cached_routes ? hashes[key] : FlatStore::hash_key(name);
                const int32_t shard_id = cached_routes
                    ? shards[key] : srv_->router().shard_of(hash);
                FlatStore& store = srv_->shard(shard_id).store();
                const uint32_t sid = static_cast<uint32_t>(shard_id);
                const uint64_t bit = uint64_t{1} << (sid & 63);
                uint64_t& word = touched[sid >> 6];
                if (!(word & bit)) {
                    const uint64_t state = store.read_local_state_acquire();
                    if (FlatStore::read_local_pending(state)) {
                        read_local_clear_reply(op);
                        return {ReadLocalFallbackReason::AtomicPending};
                    }
                    if (!FlatStore::read_local_state_eligible(state)) {
                        retry = true;
                        break;
                    }
                    states[sid] = state;
                    word |= bit;
                }

                const FlatStore::ReadLocalProbe probe = store.read_local_probe(hash, name);
                if (probe.result == FlatStore::ReadLocalProbeResult::AtomicPending) {
                    read_local_clear_reply(op);
                    return {ReadLocalFallbackReason::AtomicPending};
                }
                if (probe.result == FlatStore::ReadLocalProbeResult::Churn ||
                    probe.state != states[sid]) {
                    retry = true;
                    break;
                }
                if (probe.result == FlatStore::ReadLocalProbeResult::Missing) {
                    // Parser admission excludes an armed keymiss notification, whose owner lookup
                    // may emit an event. With that state ruled out, a validated absent slot has no
                    // lazy-expiry side effect and is an ordinary array nil element.
                    reply_null(op.sink(), op.resp3());
                    prepared.keyspace_misses++;
                    continue;
                }

                const KvObj* object = probe.object;
                if (!object) std::abort();
                const uint8_t flags = object->read_local_flags();
                if (static_cast<Type>(object->type) != Type::String) {
                    read_local_clear_reply(op);
                    return {ReadLocalFallbackReason::Typed};
                }
                if ((flags & KvObjFlags::HasTtl) &&
                    object->read_local_expire_at_ms(flags) <= cached_now_ms_) {
                    // Unlike a plain stable miss, expiry-due needs the owner to perform lazy
                    // expiry and its accounting/notifications, so one such key demotes all MGET.
                    read_local_clear_reply(op);
                    return {ReadLocalFallbackReason::Expired};
                }

                const Enc encoding = static_cast<Enc>(object->enc);
                if (encoding == Enc::Int) {
                    char text[24];
                    const uint32_t length = i64_to_dec(
                        text, object->read_local_int_value(flags));
                    reply_bulk(op.sink(), Slice(text, length));
                } else if (encoding == Enc::Raw || encoding == Enc::Extern) {
                    reply_bulk(op.sink(), object->read_local_str_value(flags));
                } else {
                    read_local_clear_reply(op);
                    return {ReadLocalFallbackReason::Typed};
                }
                prepared.keyspace_hits++;
            }

            // Atomic 0 intentionally promises only per-key independence, so different shard
            // snapshots may include interleaved plain SETs. At atomic 1, every group touching one
            // of these shards publishes a pending record before mutation and holds it through
            // release. Requiring pending==0 on every touched shard, then validating every captured
            // state after the last copy, makes a torn group observation fail closed. The later B+
            // per-key filter is deliberately not part of this shard-conservative gate.
            if (!retry) {
                for (uint32_t sid = 0; sid < srv_->nshards(); sid++) {
                    if (!(touched[sid >> 6] & (uint64_t{1} << (sid & 63)))) continue;
                    if (!srv_->shard(static_cast<int32_t>(sid))
                             .store().read_local_validate(states[sid])) {
                        retry = true;
                        break;
                    }
                }
            }
            if (!retry) return prepared;
            read_local_clear_reply(op);
        }

        // Prefer the actionable atomic reason if a pending record won the final retry race.
        for (uint32_t key = 0; key < key_count; key++) {
            const uint64_t hash = cached_routes
                ? hashes[key] : FlatStore::hash_key(op.arg(key + 1));
            const int32_t shard_id = cached_routes
                ? shards[key] : srv_->router().shard_of(hash);
            const uint64_t state =
                srv_->shard(shard_id).store().read_local_state_acquire();
            if (FlatStore::read_local_pending(state))
                return {ReadLocalFallbackReason::AtomicPending};
        }
        return {ReadLocalFallbackReason::SeqChurn};
    }

    // Build one local reply but do not publish Done. `fallback == None` means the bytes are
    // complete and no FlatStore pointer survives this call. Selective commit below keeps an
    // overlapping younger read behind any operation that needs the owner path.
    PreparedLocalRead prepare_local_read(const Task& task) {
        if (!task.client) std::abort();
        Op& op = task.client->rob().at(task.op_id);
        if (!op.read_local()) std::abort();
        if (read_local_mget(op)) return prepare_local_mget(op);
        if (op.shard < 0) std::abort();
        FlatStore& store = srv_->shard(op.shard).store();
        static constexpr uint32_t kRetries = 3;

        for (uint32_t attempt = 0; attempt < kRetries; attempt++) {
            const FlatStore::ReadLocalProbe probe = store.read_local_probe(op.hash, op.key());
            if (probe.result == FlatStore::ReadLocalProbeResult::AtomicPending) {
                read_local_clear_reply(op);
                return {ReadLocalFallbackReason::AtomicPending};
            }
            if (probe.result == FlatStore::ReadLocalProbeResult::Missing) {
                read_local_clear_reply(op);
                return {ReadLocalFallbackReason::Missing};
            }
            if (probe.result == FlatStore::ReadLocalProbeResult::Churn) continue;

            const KvObj* object = probe.object;
            if (!object) std::abort();
            const uint8_t flags = object->read_local_flags();
            if (static_cast<Type>(object->type) != Type::String) {
                read_local_clear_reply(op);
                return {ReadLocalFallbackReason::Typed};
            }
            if ((flags & KvObjFlags::HasTtl) &&
                object->read_local_expire_at_ms(flags) <= cached_now_ms_) {
                read_local_clear_reply(op);
                return {ReadLocalFallbackReason::Expired};
            }

            read_local_clear_reply(op);
            const Enc encoding = static_cast<Enc>(object->enc);
            if (encoding == Enc::Int) {
                char text[24];
                const uint32_t length = i64_to_dec(
                    text, object->read_local_int_value(flags));
                reply_bulk(op.sink(), Slice(text, length));
            } else if (encoding == Enc::Raw || encoding == Enc::Extern) {
                reply_bulk(op.sink(), object->read_local_str_value(flags));
            } else {
                read_local_clear_reply(op);
                return {ReadLocalFallbackReason::Typed};
            }

            if (!store.read_local_validate(probe.state)) {
                read_local_clear_reply(op);
                continue;
            }
            return {ReadLocalFallbackReason::None, 1, 0};
        }

        read_local_clear_reply(op);
        const uint64_t state = store.read_local_state_acquire();
        if (FlatStore::read_local_pending(state))
            return {ReadLocalFallbackReason::AtomicPending};
        return {ReadLocalFallbackReason::SeqChurn};
    }

    uint32_t drain_local_reads() {
        if constexpr (!Fused) return 0;
        if (!read_local_enabled()) return 0;
        auto& lane = read_local_impl();
        compact_local_read_tombstones();
        if (!lane.lane_count) return 0;
        Task batch[kExecBatch];
        PreparedLocalRead prepared[kExecBatch];
        ReadLocalFallbackReason fallbacks[kExecBatch];
        uint32_t work = 0;
        // Work through each client's lane run in gather/prefetch-sized chunks. A successful chunk
        // can commit immediately. At a fallback, only the intrinsically failing entries and their
        // transitive same-key set move in a ROB-ordered owner wave; unrelated reads remain local.
        while (lane.lane_count) {
            const Task& head = lane.lane[lane.lane_head];
            if (!head.client || !head.client->rob().pending_read_local(head.op_id)) {
                lane.lane_head = (lane.lane_head + 1) & (kInboxSlots - 1);
                lane.lane_count--;
                continue;
            }
            Client* client = head.client;
            uint32_t count = 0;
            while (count < lane.lane_count && count < kExecBatch) {
                const uint32_t index =
                    (lane.lane_head + count) & (kInboxSlots - 1);
                const Task& task = lane.lane[index];
                if (task.client != client ||
                    !client->rob().pending_read_local(task.op_id))
                    break;
                batch[count++] = task;
                fallbacks[count - 1] = lane.lane_fallbacks[index];
            }
            if (!count) std::abort();
            for (uint32_t i = 0; i < count; i++) {
                const Op& op = client->rob().at(batch[i].op_id);
                if (!read_local_mget(op))
                    srv_->shard(op.shard).store().read_local_prefetch(op.hash);
            }
            uint32_t first_fallback = count;
            for (uint32_t i = 0; i < count; i++) {
                const Op& op = client->rob().at(batch[i].op_id);
                if (fallbacks[i] == ReadLocalFallbackReason::None) {
                    bool broad_owner = false;
                    const bool owner_conflict =
                        client->rob().read_local_owner_conflicts_before(
                            batch[i].op_id, [&](const Op& owner) {
                                if (!read_local_commands_overlap(op, owner)) return false;
                                broad_owner |= !read_local_owner_command_is_precise(owner);
                                return true;
                            });
                    if (owner_conflict) {
                        fallbacks[i] = broad_owner
                            ? ReadLocalFallbackReason::ContextRoute
                            : ReadLocalFallbackReason::ContextOwnerKey;
                    }
                }
                if (fallbacks[i] == ReadLocalFallbackReason::None) {
                    prepared[i] = prepare_local_read(batch[i]);
                    fallbacks[i] = prepared[i].fallback;
                } else {
                    prepared[i] = {};
                }
                if (fallbacks[i] != ReadLocalFallbackReason::None &&
                    first_fallback == count) first_fallback = i;
            }

            ReadLocalStats& stats = self_->read_local_stats();
            auto complete_local_prefix = [&](uint32_t completed) {
                for (uint32_t i = 0; i < completed; i++) {
                    Op& op = client->rob().at(batch[i].op_id);
                    stats.keyspace_hits += prepared[i].keyspace_hits;
                    stats.keyspace_misses += prepared[i].keyspace_misses;
                    stats.hits++;
                    if (read_local_mget(op)) stats.mget_local_hits++;
                    self_->note_command(op.spec->id);
                    release_local_read_demotion_demand(op);
                    client->rob().complete_pending_read_local(batch[i].op_id);
                    op.state.store(OpState::Done, std::memory_order_release);
                }
                if (completed) {
                    notify_sender(client);
                    lane.lane_head = (lane.lane_head + completed) & (kInboxSlots - 1);
                    lane.lane_count -= completed;
                    work += completed;
                }
            };

            if (first_fallback != count) {
                // Publish the independent older prefix locally. Only the failing command and the
                // transitive same-key set move owner-side; ROB retirement holds every younger Done
                // reply without imposing a connection-wide execution venue.
                complete_local_prefix(first_fallback);
                for (uint32_t i = first_fallback; i < count; i++)
                    read_local_clear_reply(client->rob().at(batch[i].op_id));
                lane.lane_fallbacks[lane.lane_head] = fallbacks[first_fallback];
                uint32_t demoted = 0;
                if (!demote_local_read_batch(
                        client, batch + first_fallback, fallbacks + first_fallback,
                        count - first_fallback, demoted))
                    break;
                work += demoted;
                continue;
            }

            complete_local_prefix(count);
        }
        compact_local_read_tombstones();
        self_->sig().ops += work;
        return work;
    }

    bool flip_quiesced() const {
        if constexpr (Fused) {
            if (read_local_enabled() &&
                (read_local_impl().lane_count != 0 || !read_local_impl().deferred.empty()))
                return false;
        }
        if (snapshot_owner_state_ != SnapshotOwnerState::None ||
            !self_->ex_inbound_quiesced() || !stale_tasks_.empty() ||
            !stale_releases_.empty() || !atomic_deferred_.empty() ||
            !multi_retries_.empty() || !xshard_retries_.empty() ||
            !ordered_deferred_.empty() || notify_keyless_pending_ ||
            srv_->atomic_inflight() != 0 || srv_->atomic_apply_inflight() != 0) return false;
        for (const auto& queue : snapshot_backlogs_) if (!queue.empty()) return false;
        for (Shard* shard : self_->shards()) {
            if (shard->notify_output_pending()) return false;
            if (aof_manager_ && aof_manager_->recording() && shard->store().aof().has_pending())
                return false;
        }
        return true;
    }

    uint32_t flip_control_pass() {
        const FlipStage stage = srv_->flip_stage();
        if (stage == FlipStage::IoPrepare &&
            srv_->flip_candidate_target(self_->id()) == Role::Ifid &&
            !srv_->flip_acked(self_->id(), stage)) {
            if (!self_->prepare_io_role())
                srv_->flip_note_failure("ERR FLIP could not prepare a new IO listener");
            else if (!self_->prepare_client_capacity(srv_->flip_incoming_clients(self_->id())))
                srv_->flip_note_failure("ERR FLIP could not reserve destination connection state");
            srv_->flip_ack(self_->id(), stage);
            return 1;
        }
        if (stage == FlipStage::ExDrain && !srv_->flip_acked(self_->id(), stage) &&
            flip_quiesced()) {
            srv_->flip_ack(self_->id(), stage);
            return 1;
        }
        if (stage == FlipStage::ExInstall && !srv_->flip_acked(self_->id(), stage)) {
            // ExDrain retired every old lane and IO dispatch remains parked until all ExInstall
            // acknowledgements. Reassign blocks in the existing consumer-local allocation now;
            // no topology object is rebuilt and no producer can observe a half-installed mask.
            if (!self_->remask_task_inbox_quiesced(srv_->placement().ifid_threads(),
                                                    srv_->placement().ex_threads()))
                std::abort();
            for (Shard* shard : self_->shards())
                shard->bind_notify_pending(&notify_keyless_pending_);
            srv_->flip_ack(self_->id(), stage);
            return 1;
        }
        if (stage == FlipStage::Rollback && !srv_->flip_acked(self_->id(), stage)) {
            if (srv_->flip_candidate_target(self_->id()) == Role::Ifid)
                self_->cancel_prepared_io_role();
            srv_->flip_ack(self_->id(), stage);
            return 1;
        }
        return 0;
    }

    uint32_t lb_control_pass() {
        if (!lb_controller_armed_) return 0;
        if (srv_->lb_stage() != LbStage::ExDrain) {
            lb_ack_wake_pending_ = false;
            // A completed mover stage may have changed this loop's shard set. Every owned shard's
            // keyless-notify pending pointer must aim at THIS loop, exactly as FlipStage::ExInstall
            // rebinds after a flip -- the mover's lighter stage protocol shipped without this step,
            // and a moved shard's expired-key events then pinged the OLD owner, whose drain walks
            // only its own shards: active-expiry notifications stranded forever (notify battery,
            // key-lb half, 2/6). Rebinding is a handful of pointer stores and runs only on the
            // first pass after a stage ends.
            if (lb_rebind_pending_) {
                lb_rebind_pending_ = false;
                for (Shard* shard : self_->shards())
                    shard->bind_notify_pending(&notify_keyless_pending_);
                notify_keyless_pending_ = true;   // force one state-checked drain after adoption
            }
            return 0;
        }
        auto wake_coordinator = [&]() {
            Ring* coordinator = srv_->thread(srv_->lb_coordinator()).ring();
            if (coordinator && ring_.msg_to(*coordinator, ur_tag(UrKind::Wake, nullptr))) {
                self_->sig().wakes_sent++;
                lb_ack_wake_pending_ = false;
            } else {
                self_->sig().sqe_starved++;
            }
            return 1u; // retry after submit if the wake SQE was unavailable
        };
        if (lb_ack_wake_pending_) return wake_coordinator();
        if (srv_->lb_acked(self_->id())) return 0;
        if (!flip_quiesced()) return 0;
        srv_->lb_ack(self_->id());
        lb_ack_wake_pending_ = true;
        lb_rebind_pending_ = true;   // membership may change before the stage ends; rebind after
        return wake_coordinator();
    }

    void refresh_live_config() {
        LiveConfigSnapshot snapshot;
        if (!srv_->live_config_snapshot_if_changed(live_config_version_, snapshot)) return;
        const bool enabled = snapshot.maxmemory != 0;
        const uint64_t shard_limit = snapshot.maxmemory / srv_->nshards();
        for (Shard* sh : self_->shards()) {
            sh->configure_maxmemory(enabled, shard_limit, snapshot.policy, snapshot.samples);
            // CLIENT TRACKING and periodic SAVE need the same per-write observation points as
            // keyspace notifications, so they ride the shard mask as synthetic observer bits.
            // notify_record expands those observers over NOTIFY_ALL without adding those class
            // bits here: the operator's configured pub/sub classes therefore remain independent.
            // NOTIFY_NEW and NOTIFY_KEY_MISS stay outside the observer surface: `new` would count
            // or invalidate a mutation twice, and a key miss is not a value change.
            sh->set_notify_mask(snapshot.notify_events |
                                (snapshot.tracking_armed ? NOTIFY_TRACKING : 0u) |
                                (snapshot.save_armed ? NOTIFY_SAVE : 0u));
        }
        maxmemory_enabled_ = enabled;
        slowlog_arm_.slowlog_us = snapshot.slowlog_log_slower_than;
        slowlog_arm_.latency_ms = snapshot.latency_monitor_threshold;
        slowlog_armed_ = slowlog_arm_.armed();
        live_config_version_ = snapshot.version;
    }

    // The pending flag is a HINT, and a hint must never be the only looker: a shard whose binding
    // went stale (any ownership move a future path forgets to rebind) would strand its events
    // behind a flag it can no longer set. The busy path keeps the cheap flag gate; sweep() forces
    // the state walk, so stranded events survive at most until the owner's next idle pass.
    uint32_t drain_notify_keyless(LoopSignals& signals, bool force = false) {
        if (__builtin_expect(!notify_keyless_pending_, true) && !force) return 0;
        notify_keyless_pending_ = false;
        uint32_t work = 0;
        for (Shard* shard : self_->shards()) {
            work += notify_ex_pass_entry(
                *srv_, *shard, self_->id(), *self_, ring_, signals);
            notify_keyless_pending_ |= shard->notify_output_pending();
        }
        return work;
    }

    // Visits only the IO threads that actually have work for us, via the notify mask, rather than
    // polling every possible producer. retire() happens inside the helper, AFTER execution — see
    // exqueue.h on why the retired frontier is separate from head.
    // Mask-independent: the state backstop behind the notify hint, run only when this thread has
    // already concluded it has nothing to do.
    template <uint32_t BatchOps = kGenthreadExBatchOps, bool ConsumeTasks = true,
              bool IofusedPrivateQueue = false>
    uint32_t sweep() {
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
                if (xshard_retries_.empty() && ordered_deferred_.empty())
                    n += snapshot_owner_state_ == SnapshotOwnerState::None
                             ? drain_tasks<BatchOps, IofusedPrivateQueue>(true)
                             : drain_tasks_snapshot<BatchOps, IofusedPrivateQueue>(true);
        }
        n += active_expire_cycle() + atomic_cleanup_cycle(64);
        n += drain_notify_keyless(self_->sig(), /*force=*/true);
        if (__builtin_expect(srv_->blocking_waiters() != 0, false))
            n += blocking_owner_cycle(*srv_, *self_, ring_, cached_now_ms_, true);
        n += aof_flush_pass();
        return n;
    }

    uint32_t aof_flush_pass() {
        if (__builtin_expect(aof_manager_ == nullptr || !aof_manager_->recording(), true)) return 0;
        AofOwnerContext context{self_->id(), &ring_, &self_->sig()};
        uint32_t work = 0;
        for (Shard* shard : self_->shards()) {
            AofProducer& producer = shard->store().aof();
            if (!producer.has_pending()) continue;
            if (producer.flush(context)) work++;
        }
        return work;
    }

    static int64_t realtime_ms() {
        timespec ts{};
        ::clock_gettime(CLOCK_REALTIME, &ts);
        return static_cast<int64_t>(ts.tv_sec) * 1000 + ts.tv_nsec / 1000000;
    }

    uint32_t active_expire_cycle() {
        if (!srv_->active_expire_enabled()) return 0;
        if (snapshot_blocks_tasks()) return 0;
        auto& shards = self_->shards();
        if (shards.empty()) return 0;
        uint32_t removed = 0;
        const uint32_t visits = static_cast<uint32_t>(
            std::min<size_t>(shards.size(), kActiveExpireChecks));
        const uint32_t base = kActiveExpireChecks / visits;
        const uint32_t extra = kActiveExpireChecks % visits;
        for (uint32_t i = 0; i < visits; i++) {
            if (expire_shard_cursor_ >= shards.size()) expire_shard_cursor_ = 0;
            Shard* sh = shards[expire_shard_cursor_++];
            sh->set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
            const uint32_t n = sh->active_expire(base + (i < extra ? 1 : 0));
            if (n) sh->publish_size();
            removed += n;
        }
        return removed;
    }

    uint32_t atomic_cleanup_cycle(uint32_t budget) {
        auto& shards = self_->shards();
        if (shards.empty() || !budget) return 0;
        // Preserve the cutoff-before-floor handshake once for this owner pass, then reuse the exact
        // pair for every owned shard. A stale-low floor is safe; reversing these loads is not.
        const uint64_t cleanup_cutoff = srv_->atomic_snapshot();
        const uint64_t floor = srv_->atomic_read_floor();
        uint32_t work = 0;
        for (size_t visited = 0; visited < shards.size(); visited++) {
            if (atomic_cleanup_cursor_ >= shards.size()) atomic_cleanup_cursor_ = 0;
            Shard* shard = shards[atomic_cleanup_cursor_++];
            if (!shard->store().atomic_has_records()) continue;
            shard->set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
            work += xshard_cleanup_shard_at(*shard, floor, cleanup_cutoff, budget - work);
            if (work >= budget) break;
        }
        return work;
    }

    uint32_t drain_releases(bool unmasked = false) {
        auto take = [&](const BorrowRelease& r) {
            // The IO producer can have sampled the source just before the bucket ownership edge.
            // Recheck before the first FlatStore touch and forward the stale release intact.
            if (forward_stale_release(r)) return;
            srv_->shard(r.shard).store().unborrow(r.ptr);
        };
        return unmasked ? self_->drain_releases_unmasked(take) : self_->drain_releases(take);
    }

    template <uint32_t BatchOps = kGenthreadExBatchOps,
              bool IofusedPrivateQueue = false>
    uint32_t drain_tasks(bool unmasked = false) {
        Task batch[BatchOps];
        uint32_t held = 0;
        auto take = [&](const Task& t) {
            batch[held++] = t;
            if (held == BatchOps) {
                exec_batch<IofusedPrivateQueue>(batch, held);
                held = 0;
            }
        };
        const uint32_t n = unmasked
            ? self_->drain_tasks_unmasked<IofusedPrivateQueue>(take)
            : self_->drain_tasks<IofusedPrivateQueue>(take);
        if (held) exec_batch<IofusedPrivateQueue>(batch, held);
        self_->sig().ops += n;
        return n;
    }

    // Only the ordinary one-owner path participates. Every existing special mechanism is a hard
    // barrier in the gathered sequence: eligible work on either side cannot move across it.
    bool ex_sched_candidate(const Task& task, uint8_t& length) const {
        if (!task.client || task.scatter) return false;
        const Op& op = task.client->rob().at(task.op_id);
        if (!op.spec || op.has_blocking_state()) return false;
        constexpr uint32_t kSpecial =
            CmdFlags::Admin | CmdFlags::ConnLocal | CmdFlags::AllShards | CmdFlags::RandomShard |
            CmdFlags::CursorShard | CmdFlags::ConfigRoute | CmdFlags::ScriptRoute |
            CmdFlags::PubSub | CmdFlags::Blocking | CmdFlags::Transaction |
            CmdFlags::StreamRoute | CmdFlags::SubcmdRoute | CmdFlags::FlipAsync;
        // MultiShard is deliberately absent: a same-owner MGET/MSET local-fast task is ordinary
        // here. A real scatter has task.scatter set and returned above.
        if (op.spec->flags & kSpecial) return false;
        length = static_cast<uint8_t>(command_length_class(*op.spec));
        if (__builtin_expect(length >= kExSchedClasses, false)) return false;
        // There is no O(1) class pointer from an op to an exact parked atomic predecessor. The
        // immutable publish-time hazard bit says an older own atomic group existed; Long is the
        // safe upper bound without a deque scan or persistent scheduler state.
        if (op.atomic_hazard()) length = static_cast<uint8_t>(CommandLengthClass::Long);
        return true;
    }

    struct ExScheduleKey {
        uint8_t rank = 0;
        uint8_t length = 0;
    };

    void ex_schedule_run(Task* tasks, const uint8_t* base_lengths, uint32_t n) {
        if (n < 2) return;
        Client* const only_client = tasks[0].client;
        uint32_t distinct_at = 1;
        while (distinct_at < n && tasks[distinct_at].client == only_client) distinct_at++;
        // Absolute per-connection order leaves no legal permutation in a one-client run.
        if (distinct_at == n) return;

        ExScheduleKey keys[kExecBatch];
        uint8_t min_rank = UINT8_MAX;
        uint8_t max_rank = 0;
        uint8_t first_length = 0;
        bool one_length = true;

        // The gather contract presents each connection's Tasks in increasing op_id order. Sample
        // newest-to-oldest: flush_id only advances, so an older task still receives a strictly
        // lower rank even if IO retires a completed prefix between samples. Adjacent tasks from
        // one connection reuse the head load without any per-connection table. The slow path
        // verifies the contract before reordering; every earlier exit retains FIFO.
        Client* sampled_client = nullptr;
        uint64_t sampled_head = 0;
        for (uint32_t i = n; i-- > 0;) {
            const Task& task = tasks[i];
            if (task.client != sampled_client) {
                sampled_client = task.client;
                sampled_head = sampled_client->rob().flush_id();
            }
            const uint64_t distance = task.op_id - sampled_head;
            // A fresh unfinished task is always in the 64-slot live ROB window. If that invariant
            // is ever broken, preserve today's FIFO instead of collapsing ranks and risking order.
            if (__builtin_expect(distance >= kRobWindow, false)) return;
            keys[i] = ExScheduleKey{static_cast<uint8_t>(distance), base_lengths[i]};
            min_rank = std::min(min_rank, keys[i].rank);
            max_rank = std::max(max_rank, keys[i].rank);
            if (i == n - 1) first_length = keys[i].length;
            else one_length &= keys[i].length == first_length;
        }

        // The measured-law escape is defined on the directly available gathered classes and runs
        // before conservative widening for an invisible predecessor. This is what keeps homogeneous
        // rank-adjacent traffic off the dependency and bucket paths.
        if (one_length && max_rank - min_rank <= 1) return;

        // Effective class is the prefix maximum for each connection in this gathered run. A rank
        // before the first represented task, or a gap in its ids, means an unrepresented blocker;
        // its slot cannot safely be read while IO may recycle it, so Long is the no-state upper
        // bound. Open addressing is at most half full and is reached only after degeneration.
        static constexpr uint32_t kChainSlots = kExecBatch * 2;
        Client* chain_client[kChainSlots];
        uint8_t chain_last[kChainSlots];
        uint64_t chain_occupied = 0;
        for (uint32_t i = 0; i < n; i++) {
            Client* client = tasks[i].client;
            uint64_t hash = static_cast<uint64_t>(reinterpret_cast<uintptr_t>(client));
            hash ^= hash >> 33;
            hash *= uint64_t{0xff51afd7ed558ccdull};
            hash ^= hash >> 33;
            uint32_t slot = static_cast<uint32_t>(hash) & (kChainSlots - 1);
            uint64_t bit = uint64_t{1} << slot;
            while ((chain_occupied & bit) && chain_client[slot] != client) {
                slot = (slot + 1) & (kChainSlots - 1);
                bit = uint64_t{1} << slot;
            }
            if (!(chain_occupied & bit)) {
                chain_occupied |= bit;
                chain_client[slot] = client;
                if (keys[i].rank != 0)
                    keys[i].length = static_cast<uint8_t>(CommandLengthClass::Long);
            } else {
                const uint8_t previous = chain_last[slot];
                // Preserve the existing FIFO if a producer-lane bug ever violates the gather
                // contract. The scheduler must never create a same-connection inversion.
                if (tasks[i].op_id <= tasks[previous].op_id) return;
                keys[i].length = std::max(keys[i].length, keys[previous].length);
                if (tasks[i].op_id != tasks[previous].op_id + 1)
                    keys[i].length = static_cast<uint8_t>(CommandLengthClass::Long);
            }
            chain_last[slot] = static_cast<uint8_t>(i);
        }
        one_length = true;
        for (uint32_t i = 1; i < n; i++) one_length &= keys[i].length == keys[0].length;
        if (one_length && max_rank - min_rank <= 1) return;

        // Stable gather order often already matches the selected bucket order. Avoid scratch
        // setup and two Task copies when the policy would be an identity permutation.
        bool already_ordered = true;
        uint32_t previous_bucket = keys[0].rank * kExSchedClasses + keys[0].length;
        for (uint32_t i = 1; i < n; i++) {
            const uint32_t bucket = keys[i].rank * kExSchedClasses + keys[i].length;
            already_ordered &= bucket >= previous_bucket;
            previous_bucket = bucket;
        }
        if (already_ordered) return;

        uint8_t counts[kExSchedBuckets];
        uint8_t cursors[kExSchedBuckets];
        uint64_t occupied[kExSchedBucketWords] = {};
        for (uint32_t i = 0; i < n; i++) {
            const uint32_t bucket = keys[i].rank * kExSchedClasses + keys[i].length;
            const uint32_t word = bucket >> 6;
            const uint64_t bit = uint64_t{1} << (bucket & 63);
            if (!(occupied[word] & bit)) {
                occupied[word] |= bit;
                counts[bucket] = 0;
            }
            counts[bucket]++;
        }

        uint8_t out = 0;
        for (uint32_t word = 0; word < kExSchedBucketWords; word++) {
            uint64_t bits = occupied[word];
            while (bits) {
                const uint32_t bit = static_cast<uint32_t>(__builtin_ctzll(bits));
                bits &= bits - 1;
                const uint32_t bucket = word * 64 + bit;
                cursors[bucket] = out;
                out = static_cast<uint8_t>(out + counts[bucket]);
            }
        }

        Task ordered[kExecBatch];
        for (uint32_t i = 0; i < n; i++) {
            const uint32_t bucket = keys[i].rank * kExSchedClasses + keys[i].length;
            ordered[cursors[bucket]++] = tasks[i];
        }
        for (uint32_t i = 0; i < n; i++) tasks[i] = ordered[i];
    }

    void ex_schedule_batch(Task* tasks, uint32_t n) {
        uint8_t base_lengths[kExecBatch];
        uint32_t begin = 0;
        while (begin < n) {
            if (!ex_sched_candidate(tasks[begin], base_lengths[begin])) {
                begin++;
                continue;
            }
            uint32_t end = begin + 1;
            while (end < n && ex_sched_candidate(tasks[end], base_lengths[end])) end++;
            ex_schedule_run(tasks + begin, base_lengths + begin, end - begin);
            // The failed candidate at end is a known barrier; consume it without reading its Op a
            // second time, then find the next eligible run.
            begin = end + (end < n);
        }
    }

    enum class SnapshotOwnerState : uint8_t {
        None, Preparing, Prepared, Frozen, Marked, Capturing, Draining
    };

    bool snapshot_blocks_tasks() const {
        if (snapshot_owner_state_ == SnapshotOwnerState::Frozen ||
            snapshot_owner_state_ == SnapshotOwnerState::Marked) return true;
        return snapshot_owner_state_ == SnapshotOwnerState::Capturing &&
               snapshot_manager_ && snapshot_manager_->blocking();
    }

    void begin_snapshot(SnapshotManager* manager) {
        if (!manager || snapshot_owner_state_ != SnapshotOwnerState::None) return;
        snapshot_manager_ = manager;
        snapshot_epoch_ = manager->epoch();
        snapshot_was_cancelled_ = false;
        snapshot_owner_state_ = SnapshotOwnerState::Preparing;
        snapshot_prepare_cursor_ = 0;
        snapshot_progress_cursor_ = 0;
        snapshot_done_shards_.assign(srv_->nshards(), 0);
        snapshot_pending_chunks_.clear();
        snapshot_pending_chunks_.resize(srv_->nshards());
        snapshot_backlogs_.clear();
        snapshot_backlogs_.resize(srv_->nshards());
    }

    template <uint32_t BatchOps = kGenthreadExBatchOps,
              bool IofusedPrivateQueue = false>
    uint32_t snapshot_control_pass() {
        if (snapshot_owner_state_ == SnapshotOwnerState::None) return 0;
        SnapshotManager::Phase phase = snapshot_manager_->phase();
        if (phase == SnapshotManager::Phase::Failed &&
            snapshot_owner_state_ != SnapshotOwnerState::Draining) {
            for (Shard* shard : self_->shards()) shard->store().snapshot_cancel();
            snapshot_pending_chunks_.clear();
            snapshot_was_cancelled_ = true;
            snapshot_owner_state_ = SnapshotOwnerState::Draining;
            return 1;
        }

        if (snapshot_owner_state_ == SnapshotOwnerState::Preparing) {
            auto& shards = self_->shards();
            if (snapshot_prepare_cursor_ < shards.size()) {
                FlatStore::SnapshotWriteResult result = shards[snapshot_prepare_cursor_]
                    ->store().snapshot_prepare(snapshot_epoch_, 0);
                if (result == FlatStore::SnapshotWriteResult::Error) {
                    snapshot_manager_->fail(snapshot_epoch_, "could not prepare shard snapshot");
                    return 1;
                }
                if (result == FlatStore::SnapshotWriteResult::Ready) snapshot_prepare_cursor_++;
                return 1;
            }
            snapshot_owner_state_ = SnapshotOwnerState::Prepared;
            snapshot_manager_->owner_ready(snapshot_epoch_);
            return 1;
        }

        if (snapshot_owner_state_ == SnapshotOwnerState::Prepared &&
            phase == SnapshotManager::Phase::Freeze) {
            // The Mark-time AOF segment switch is positional. Publish every pre-cut owner buffer
            // before acknowledging Freeze so the writer can drain a complete old segment.
            aof_flush_pass();
            snapshot_owner_state_ = SnapshotOwnerState::Frozen;
            snapshot_manager_->owner_frozen(snapshot_epoch_);
            return 1;
        }
        if (snapshot_owner_state_ == SnapshotOwnerState::Frozen &&
            phase == SnapshotManager::Phase::Mark) {
            for (Shard* shard : self_->shards()) {
                if (!shard->store().snapshot_mark(shard->id(), snapshot_manager_->cut_ms())) {
                    snapshot_manager_->fail(snapshot_epoch_, "could not mark shard snapshot epoch");
                    return 1;
                }
            }
            snapshot_owner_state_ = SnapshotOwnerState::Marked;
            snapshot_manager_->owner_marked(snapshot_epoch_);
            return 1;
        }
        if (snapshot_owner_state_ == SnapshotOwnerState::Marked &&
            phase == SnapshotManager::Phase::Capture) {
            snapshot_owner_state_ = SnapshotOwnerState::Capturing;
            return 1;
        }
        if (snapshot_owner_state_ == SnapshotOwnerState::Capturing &&
            phase == SnapshotManager::Phase::Capture) {
            return progress_snapshot_capture();
        }
        if (snapshot_owner_state_ == SnapshotOwnerState::Draining) {
            const uint32_t n = service_snapshot_backlogs<IofusedPrivateQueue>(
                BatchOps, false);
            if (snapshot_backlogs_empty()) {
                if (snapshot_was_cancelled_) snapshot_manager_->owner_cancelled(snapshot_epoch_);
                else                         snapshot_manager_->owner_finished(snapshot_epoch_);
                snapshot_owner_state_ = SnapshotOwnerState::None;
                snapshot_manager_ = nullptr;
            }
            return n;
        }
        return 0;
    }

    uint32_t progress_snapshot_capture() {
        auto& shards = self_->shards();
        if (shards.empty()) {
            snapshot_owner_state_ = SnapshotOwnerState::Draining;
            return 1;
        }
        uint32_t work = 0;
        const uint32_t wanted_sid = snapshot_manager_->save_current_shard();
        for (size_t visits = 0; visits < shards.size(); visits++) {
            if (snapshot_progress_cursor_ >= shards.size()) snapshot_progress_cursor_ = 0;
            Shard* shard = shards[snapshot_progress_cursor_++];
            const uint32_t sid = static_cast<uint32_t>(shard->id());
            if (snapshot_done_shards_[sid]) continue;
            if (snapshot_manager_->blocking() && sid != wanted_sid) continue;

            auto& pending = snapshot_pending_chunks_[sid];
            if (!pending) pending = shard->store().snapshot_take_chunk();
            if (pending) {
                const bool end = (pending->flags & SnapshotFrameEnd) != 0;
                if (!snapshot_manager_->post_chunk(self_->id(), pending, ring_, self_->sig())) return work;
                work++;
                if (end) {
                    shard->store().snapshot_handoff_complete();
                    snapshot_done_shards_[sid] = 1;
                }
            }
            if (!snapshot_done_shards_[sid]) {
                work += shard->store().snapshot_progress(kSnapshotChunkBytes, 256);
                if (shard->store().snapshot_failed()) {
                    snapshot_manager_->fail(snapshot_epoch_, "snapshot type serialization failed");
                    return work + 1;
                }
                if (!pending) pending = shard->store().snapshot_take_chunk();
                if (pending) {
                    const bool end = (pending->flags & SnapshotFrameEnd) != 0;
                    if (!snapshot_manager_->post_chunk(self_->id(), pending, ring_, self_->sig()))
                        return work;
                    work++;
                    if (end) {
                        shard->store().snapshot_handoff_complete();
                        snapshot_done_shards_[sid] = 1;
                    }
                }
            }
            break;  // one shard, one bounded byte/slot budget per executor pass
        }
        bool all_done = true;
        for (Shard* shard : shards)
            all_done &= snapshot_done_shards_[static_cast<uint32_t>(shard->id())] != 0;
        if (all_done) {
            snapshot_owner_state_ = SnapshotOwnerState::Draining;
        }
        return work;
    }

    bool snapshot_backlogs_empty() const {
        for (const auto& queue : snapshot_backlogs_) if (!queue.empty()) return false;
        return true;
    }

    FlatStore::SnapshotWriteResult snapshot_prepare_plain_write(Op& op, Shard& shard) {
        if (!(op.spec->flags & CmdFlags::SubcmdRoute))
            return shard.store().snapshot_prepare_write(op.hash, op.key());

        // A routed container's key position belongs to its selected child, not argv[1].  The
        // registered position is still the common keyed-child position; a short keyless child
        // such as XGROUP HELP has no pre-image to capture.
        const int16_t first_key = op.spec->first_key;
        if (first_key <= 0 || static_cast<uint32_t>(first_key) >= op.argc())
            return FlatStore::SnapshotWriteResult::Ready;
        return shard.store().snapshot_prepare_write(op.hash, op.arg(first_key));
    }

    template <bool IofusedPrivateQueue = false>
    bool execute_snapshot_task(const Task& task, bool capture_writes) {
        // MULTI's tagged task owns its command images outside the public ROB and performs the
        // snapshot pre-image gate per installed transaction key.  Never decode it as a normal op.
        if (multi_task_tagged(task)) return execute<IofusedPrivateQueue>(task);
        if (!task.client) return execute<IofusedPrivateQueue>(task);
        Op& op = task.client->rob().at(task.op_id);
        const int32_t sid = task.shard >= 0 ? task.shard : op.shard;
        Shard& shard = srv_->shard(sid);
        if (op.has_blocking_state()) {
            if (capture_writes) {
                const BlockingSnapshotPrepare result =
                    blocking_snapshot_prepare(task, shard, op);
                if (result == BlockingSnapshotPrepare::Pending) return false;
                if (result == BlockingSnapshotPrepare::Error) {
                    snapshot_manager_->fail(
                        snapshot_epoch_, "snapshot pre-image serialization failed");
                    return false;
                }
            }
            return execute<IofusedPrivateQueue>(task);
        }
        if (capture_writes &&
            (op.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite))) {
            const FlatStore::SnapshotWriteResult result = task.scatter
                ? xshard_snapshot_prepare(task, shard)
                : xshard_is_local(op)
                    ? xshard_local_snapshot_prepare(op, shard)
                    : snapshot_prepare_plain_write(op, shard);
            if (result == FlatStore::SnapshotWriteResult::Pending) return false;
            if (result == FlatStore::SnapshotWriteResult::Error) {
                snapshot_manager_->fail(snapshot_epoch_, "snapshot pre-image serialization failed");
                return false;
            }
        }
        if (!execute<IofusedPrivateQueue>(task)) return false;
        shard.publish_size();
        return true;
    }

    template <bool IofusedPrivateQueue = false>
    void schedule_snapshot_task(const Task& task) {
        if (multi_task_tagged(task)) {
            execute<IofusedPrivateQueue>(task);
            return;
        }
        if (!task.client) {
            execute<IofusedPrivateQueue>(task);
            return;
        }
        // A bounded scatter continuation is still the oldest task on this owner.  Holding later
        // work here preserves the queue-order RYOW argument without installing a conn barrier for
        // KEYS.  Snapshot-gated scatter writes use the same ordering hold while Pending.
        if (!xshard_retries_.empty()) { ordered_deferred_.push_back(task); return; }
        if (task.scatter) {
            if (!execute_snapshot_task<IofusedPrivateQueue>(task, true))
                xshard_retries_.push_back(task);
            return;
        }
        const Op& op = task.client->rob().at(task.op_id);
        const int32_t sid = task.shard >= 0 ? task.shard : op.shard;
        auto& queue = snapshot_backlogs_[static_cast<uint32_t>(sid)];
        if (!queue.empty() || !execute_snapshot_task<IofusedPrivateQueue>(task, true))
            queue.push_back(task);
    }

    template <bool IofusedPrivateQueue = false>
    uint32_t service_snapshot_backlogs(uint32_t budget, bool capture_writes = true) {
        uint32_t n = 0;
        for (Shard* shard : self_->shards()) {
            auto& queue = snapshot_backlogs_[static_cast<uint32_t>(shard->id())];
            while (budget && !queue.empty()) {
                if (!execute_snapshot_task<IofusedPrivateQueue>(
                        queue.front(), capture_writes)) break;
                queue.pop_front(); budget--; n++;
            }
            if (!budget) break;
        }
        return n;
    }

    template <uint32_t BatchOps = kGenthreadExBatchOps,
              bool IofusedPrivateQueue = false>
    uint32_t drain_tasks_snapshot(bool unmasked = false) {
        auto take = [&](const Task& task) {
            schedule_snapshot_task<IofusedPrivateQueue>(task);
        };
        const uint32_t n = unmasked
            ? self_->drain_tasks_unmasked<IofusedPrivateQueue>(take)
            : self_->drain_tasks<IofusedPrivateQueue>(take);
        self_->sig().ops += n;
        // Retire at least as many deferred Tasks as this drain can add, plus one batch of old debt;
        // otherwise a saturated post-capture owner could remain in Draining forever.
        return n + service_snapshot_backlogs<IofusedPrivateQueue>(BatchOps + n);
    }

    // The armed slow-log arm. Out of line and cold-marked so its register pressure and its clock
    // calls never reach the disabled batch loop above.
    //
    // TWO MODES. Normal mode brackets the whole batch with two now_ns() reads. A batch of ONE op
    // gives that op's exact duration, which is every command on an unpipelined connection. A batch
    // of many that overruns cannot be attributed retroactively -- the ops already ran -- so it
    // arms per-op timing for the next kSlowlogEscalateBatches batches instead, and the recurrence
    // is timed exactly. This is the documented divergence from redis, which times every command.
    //
    template <bool IofusedPrivateQueue = false>
    __attribute__((noinline, cold))
    void exec_batch_timed(const Task* batch, uint32_t n) {
        const SlowlogArm arm = slowlog_arm_;
        const int64_t now_ms = cached_now_ms_;
        slowlog_note_batch_timed();

        if (slowlog_state_.escalate_batches || n == 1) {
            if (slowlog_state_.escalate_batches) slowlog_state_.escalate_batches--;
            for (uint32_t i = 0; i < n; i++) {
                // Snapshot argv BEFORE execution. execute() publishes Done, after which the owning
                // IO thread may retire the op and compact the read buffer the Slices point into.
                Client* client = batch[i].client;
                if (client)
                    slowlog_capture(client->rob().at(batch[i].op_id), slowlog_state_.capture);
                const uint64_t started = now_ns();
                const bool ok = execute<IofusedPrivateQueue>(batch[i]);
                const uint64_t elapsed = now_ns() - started;
                // ONE ENTRY PER COMMAND, not per participating shard. A cross-shard op is handed
                // to every owner it touches; all but the last return with the op still Issued.
                // Recording only the owner that published Done means a scatter is attributed to
                // the slice that actually computed the answer -- documented in NOTES-SERVERTAIL.md.
                if (client &&
                    client->rob().at(batch[i].op_id).state.load(std::memory_order_relaxed) ==
                        OpState::Done)
                    slowlog_record_captured(self_->id(), client->id(), slowlog_state_.capture,
                                            elapsed, now_ms, arm);
                if (ok) continue;
                xshard_retries_.push_back(batch[i]);
                for (uint32_t j = i + 1; j < n; j++) ordered_deferred_.push_back(batch[j]);
                return;
            }
            return;
        }

        const uint64_t started = now_ns();
        uint32_t executed = n;
        for (uint32_t i = 0; i < n; i++) {
            if (execute<IofusedPrivateQueue>(batch[i])) continue;
            xshard_retries_.push_back(batch[i]);
            for (uint32_t j = i + 1; j < n; j++) ordered_deferred_.push_back(batch[j]);
            executed = i;
            break;
        }
        const uint64_t elapsed = now_ns() - started;
        // The screen is per-op-average, not whole-batch: a full batch of ordinary commands must
        // not look like one slow command just because there were 32 of them.
        const uint64_t threshold_ns = arm.slowlog_us >= 0
            ? static_cast<uint64_t>(arm.slowlog_us) * 1000
            : UINT64_MAX;
        const uint64_t latency_ns = arm.latency_ms
            ? static_cast<uint64_t>(arm.latency_ms) * 1000000 : UINT64_MAX;
        const uint64_t bar = std::min(threshold_ns, latency_ns);
        if (executed && bar != UINT64_MAX && elapsed / executed >= bar) {
            slowlog_state_.escalate_batches = kSlowlogEscalateBatches;
            slowlog_note_escalation();
        }
    }

    // Prefetch the whole batch's slots, THEN execute. Issuing the loads up front lets their DRAM
    // round trips overlap instead of each op stalling on its own miss in turn.
    void prefetch_exec_batch(const Task* batch, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            if (!batch[i].client) continue;
            const Op& op = batch[i].client->rob().at(batch[i].op_id);
            const int32_t shard = batch[i].shard >= 0 ? batch[i].shard : op.shard;
            // The shipped coarse batch must obey the same resolve -> verify-owner -> store-touch
            // order as pipelined E1. A route can go stale after enqueue; even a prefetch through
            // the old FlatStore is formally an ownership violation under TSAN's model.
            if (shard >= 0 && !batch[i].scatter &&
                srv_->worker_of_shard(shard) == self_->id() &&
                !(op.spec->flags & (CmdFlags::CursorShard | CmdFlags::RandomShard)))
                srv_->shard(shard).store().prefetch(op.hash);
        }
    }

    // Consume a bucket-prefetched homogeneous batch. The interwoven schedule calls this
    // immediately after the prefetch loop; an interleaved schedule reaches it after independent-
    // stream filler.
    template <bool IofusedPrivateQueue = false>
    void exec_batch_prefetched(const Task* batch, uint32_t n) {
        if (!xshard_retries_.empty()) {
            for (uint32_t i = 0; i < n; i++) ordered_deferred_.push_back(batch[i]);
            return;
        }
        // THE ENTIRE DISABLED-FEATURE COST OF SLOWLOG/LATENCY: one predicted-false branch here,
        // once per batch of up to kExecBatch ops. No clock is read and the recorder is not linked
        // into this loop at all. The armed body is out of line in exec_batch_timed().
        if (__builtin_expect(slowlog_armed_, false)) {
            exec_batch_timed<IofusedPrivateQueue>(batch, n);
        } else {
            for (uint32_t i = 0; i < n; i++) {
                if (execute<IofusedPrivateQueue>(batch[i])) continue;
                xshard_retries_.push_back(batch[i]);
                for (uint32_t j = i + 1; j < n; j++) ordered_deferred_.push_back(batch[j]);
                break;
            }
        }
        // One publish per batch, covering every shard this batch touched. Cheaper than tracking
        // which ones changed, and this thread owns all of them.
        for (Shard* sh : self_->shards()) sh->publish_size();
        // Reclamation is owner-batched rather than one posted task per completed group. Visit the
        // owned shards after each atomic batch so their pending-entry lists stay short.
        if (xshard_retries_.empty() && srv_->atomic_work_active()) {
            atomic_cleanup_cycle(256);
        }
    }

    // Run mutation-capable reclamation only after every buffered E2 in the pass. In particular, an
    // A/D sequence must not put cleanup between E1(D) and E2(D), and consecutive modulo chunks use
    // the same rule. The caller still holds every gathered source prefix unretired here.
    void finish_buffered_exec_pass(uint32_t executable_count) {
        if (xshard_retries_.empty() && srv_->atomic_work_active() && executable_count) {
            // The legacy entry supplied 256 cleanup records of service for every batch of at most
            // 128 tasks. Preserve that capacity while paying the owned-shard walk only once.
            atomic_cleanup_cycle(std::max<uint32_t>(256, executable_count * 2));
        }
    }

    // Buffered E2 batches can be much smaller than the shipped coarse drain. Their caller tracks
    // owner-verified shards while E1 already has the route in hand, then publishes that dense set
    // once after the complete multi-chunk EX pass. Keep the ordinary coarse/iofused entry above --
    // including its historical all-owned-shards publication -- unchanged.
    void exec_batch_prefetched_buffered(const Task* batch, uint32_t n) {
        if (!xshard_retries_.empty()) {
            for (uint32_t i = 0; i < n; i++) ordered_deferred_.push_back(batch[i]);
            return;
        }
        if (__builtin_expect(slowlog_armed_, false)) {
            exec_batch_timed(batch, n);
        } else {
            for (uint32_t i = 0; i < n; i++) {
                if (execute(batch[i])) continue;
                xshard_retries_.push_back(batch[i]);
                for (uint32_t j = i + 1; j < n; j++) ordered_deferred_.push_back(batch[j]);
                break;
            }
        }
    }

    // Coarse compatibility: prefetch the whole batch and consume it without an intervening
    // micro-stage.
    template <bool IofusedPrivateQueue = false>
    void exec_batch(Task* batch, uint32_t n) {
        // Deferral first (skip wasted prefetch on the rare retry path), then the opt-in
        // reorder BEFORE prefetch so prefetch order matches execution order.
        if (!xshard_retries_.empty()) {
            for (uint32_t i = 0; i < n; i++) ordered_deferred_.push_back(batch[i]);
            return;
        }
        if (__builtin_expect(ex_sched_enabled_, false)) ex_schedule_batch(batch, n);
        prefetch_exec_batch(batch, n);
        exec_batch_prefetched<IofusedPrivateQueue>(batch, n);
    }

    template <bool IofusedPrivateQueue = false, bool ReadLocalNoEvict = false>
    bool execute(const Task& t) {
        // Forwarding, rather than a request epoch, resolves the route-read/enqueue race.  This check
        // must precede every shard dereference, including tagged MULTI and ownerless cleanup tasks.
        if (forward_stale_task<IofusedPrivateQueue>(t)) return true;
        if (multi_task_tagged(t)) {
            Shard& shard = srv_->shard(t.shard);
            shard.set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
            // PROGRAM ORDER: a transaction fragment must not run past an older same-connection
            // task parked in atomic_deferred_/xshard_retries_ on this shard. This branch used to
            // skip the check entirely, so a pipelined EXEC's child executed before the
            // connection's earlier cross-shard DEL fragment that was deferred here, and the
            // transaction read the pre-DEL world (the seed-19 differ divergence). An ownerless
            // teardown fragment (null client, the WATCH-disconnect path) belongs to no
            // connection and carries no program order -- and has no ROB to consult.
            if (t.client) {
                Op& carrier = t.client->rob().at(t.op_id);
                if (has_parked_predecessor(t, carrier, t.shard)) {
                    atomic_deferred_.push_back(t);
                    return true;
                }
            }
            // The no-touch answer is PER TASK; a MULTI body inherits the transaction owner's.
            if (__builtin_expect(maxmemory_enabled_, false)) {
                const Op& carrier = t.client->rob().at(t.op_id);
                const bool no_touch = carrier.no_touch();
                shard.set_no_touch(no_touch);
                if (no_touch) srv_->climon_note_no_touch();
            }
            AofOwnerContext aof_context{self_->id(), &ring_, &self_->sig()};
            const MultiTaskResult result =
                multi_execute_task(*srv_, t, shard, self_->id(), self_->domain(),
                                   aof_manager_ ? &aof_context : nullptr);
            shard.publish_size();
            if (result == MultiTaskResult::Retry) {
                multi_retries_.push_back(t);
                return true;
            }
            if (result == MultiTaskResult::Final) {
                Op& public_op = t.client->rob().at(t.op_id);
                public_op.state.store(OpState::Done, std::memory_order_release);
                notify_sender(t.client);
            }
            return true;
        }
        if (!t.client) {
            Shard& cleanup = srv_->shard(t.shard);
            cleanup.set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
            // An ownerless cleanup pass belongs to no connection: clear the per-task no-touch
            // answer so a NO-TOUCH client cannot leave it armed for whatever runs next.
            if (__builtin_expect(maxmemory_enabled_, false)) cleanup.set_no_touch(false);
            xshard_cleanup_shard(*srv_, cleanup, 32);
            cleanup.publish_size();
            return true;
        }
        Op& op = t.client->rob().at(t.op_id);
        const int32_t shard_id = t.shard >= 0 ? t.shard : op.shard;
        Shard& sh = srv_->shard(shard_id);
        if constexpr (Fused && !ReadLocalNoEvict) {
            if (__builtin_expect(
                    maxmemory_enabled_ && read_local_enabled() &&
                    op.read_local_precise_write() &&
                    sh.store().maxmemory_policy() != MaxmemoryPolicy::NoEviction,
                    false)) {
                ReadLocalPreciseWriteGuard no_evict(sh.store());
                return execute<IofusedPrivateQueue, true>(t);
            }
        }
        sh.set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
        // CLIENT NO-TOUCH. maxmemory_enabled_ is this loop's own per-pass value, so with the
        // default (maxmemory off) this is one predicted-not-taken test on a register -- and the
        // read path in FlatStore never loads the byte at all, because its && short-circuits.
        if (__builtin_expect(maxmemory_enabled_, false)) {
            const bool no_touch = op.no_touch();
            sh.set_no_touch(no_touch);
            if (no_touch) srv_->climon_note_no_touch();
        }
        if (op.has_blocking_state()) {
            sh.note_execution(self_->domain());
            note_lb_hash(sh, op.hash);
            if constexpr (IofusedPrivateQueue) {
                static_assert(Fused);
                return blocking_execute_iofused(*srv_, *self_, ring_, t, sh, op);
            } else {
                return blocking_execute(*srv_, *self_, ring_, t, sh, op);
            }
        }
        // #77 TRIPWIRE A samples before any scheduler park. The first answer is retained across
        // retries; the debug registry qualifies begin-plain transitions when execution arrives.
        if (__builtin_expect(atomic_tripwire_enabled(), false))
            xshard_tripwire_fragment_begin(t, sh, op);
        if (has_parked_predecessor(t, op, shard_id) ||
            xshard_task_should_defer(*srv_, sh, t, op)) {
            atomic_deferred_.push_back(t);
            return true;
        }
        if (!t.scatter && (op.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite)) &&
            __builtin_expect(sh.has_watches(), false) && !multi_plain_write_ready(sh, op))
            return false;
        // Records the op AND whether it was executed from this shard's home L3 domain. One compare
        // and one increment, no atomics — the shard has a single owner.
        sh.note_execution(self_->domain());

        if (!t.scatter) self_->note_command(op.spec->id);

        if (t.scatter) {
            const ScatterTaskResult result = xshard_execute(t, sh, op, self_->id());
            xshard_watch_finish(t, sh, op, result);
            if (result == ScatterTaskResult::Retry) return false;
            if (lb_sample_rate_) {
                struct LbVisit { ExLoopT* loop; Shard* shard; } visit{this, &sh};
                xshard_visit_task_hashes(t, &visit, [](void* context, uint64_t hash) {
                    auto* visit = static_cast<LbVisit*>(context);
                    visit->loop->note_lb_hash(*visit->shard, hash);
                });
            }
            if (__builtin_expect(sh.has_blocking_waiters(), false))
                blocking_scatter_mutation_published(t, sh, op);
            if (__builtin_expect(aof_manager_ != nullptr, false)) {
                AofOwnerContext context{self_->id(), &ring_, &self_->sig()};
                xshard_aof_emit(t, sh, op, context);
            }
            sh.publish_size();
            const ScatterFinish finished = [&] {
                if constexpr (IofusedPrivateQueue) {
                    static_assert(Fused);
                    return xshard_complete_iofused(*srv_, *self_, ring_, t, op);
                } else {
                    return xshard_complete(*srv_, *self_, ring_, t, op);
                }
            }();
            if (finished == ScatterFinish::Waiting) return true;
            if (finished == ScatterFinish::Retry) return false;
        } else if (__builtin_expect(op.spec->flags & CmdFlags::DenyOom, false) &&
                   !sh.store().budget_admit(op.arg(static_cast<uint32_t>(op.spec->first_key)))) {
            // Growth gate (wrinkle fix 2026-08-25): collection growth mutates behind a stable
            // KvObj and never crosses insert-admission, so an HSET-only workload could blow
            // through maxmemory unbounded. One predicted-false flag test per op when disabled.
            // Scatter tasks bypass it -- their writes replace whole objects through insert-level
            // admission in their owner pass.
            reply_maxmemory_oom(op);
        } else {
            // A null pending-entry list is the sole common-path branch. With no cross-shard window,
            // handlers take their original path with no epoch loads, allocations, or cleanup work.
            if (__builtin_expect(sh.store().atomic_has_records(), false)) {
                const bool execute_handler = xshard_plain_prepare(*srv_, sh, op, t.client->id());
                const bool defer_blocking =
                    __builtin_expect(sh.has_blocking_waiters(), false);
                if (defer_blocking) blocking_defer_plain_publication(true);
                if (execute_handler) op.spec->handler(sh, op);
                xshard_plain_finish(sh);
                if (defer_blocking) {
                    blocking_defer_plain_publication(false);
                    if (execute_handler) blocking_plain_mutation_published(sh, op);
                }
            } else {
                op.spec->handler(sh, op);
            }
        }
        if (!t.scatter) note_lb_hash(sh, op.hash);
        if (!t.scatter && (op.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite)) &&
            __builtin_expect(sh.has_watches(), false))
            multi_plain_write_committed(sh, op);
        if (!t.scatter && __builtin_expect(aof_manager_ != nullptr, false)) {
            AofOwnerContext context{self_->id(), &ring_, &self_->sig()};
            if (op.local_xshard()) xshard_aof_emit_local(sh, op, context);
            else                   aof_record_local_op(sh, op, context);
        }

        // Release pairs with the IO thread's acquire on Done: everything the handler wrote into
        // op.reply becomes visible through this one store.
        op.state.store(OpState::Done, std::memory_order_release);

        // Notify the connection's io thread; the claim flag dedupes a burst into one post.
        // EXECUTOR-ISSUED SENDS ARE A CLOSED DOOR: the exwb mode (executor
        // sends its own completed prefix) was built, measured #1 in zero cells across every size
        // and pipe depth, and deleted 2026-08-24 -- send work rides the scarce ex role, nearly
        // free at p1 and ruinous at p32. Flush-at-head-from-ex was separately built twice and
        // reverted twice before that (fixed sender 8.1-8.5M get_p32 vs 4.1-4.7M with wedges).
        notify_sender(t.client);
        return true;
    }

    template <bool IofusedPrivateQueue = false>
    uint32_t service_xshard_retries() {
        if (xshard_retries_.empty()) return 0;
        const Task task = xshard_retries_.front();
        xshard_retries_.pop_front();
        const bool complete = snapshot_owner_state_ == SnapshotOwnerState::None
            ? execute<IofusedPrivateQueue>(task)
            : execute_snapshot_task<IofusedPrivateQueue>(task, true);
        if (!complete) xshard_retries_.push_back(task);
        return 1;  // one bounded KEYS pass (or one snapshot-gate attempt) per executor iteration
    }

    void note_lb_hash(Shard& shard, uint64_t hash) {
        if (!lb_sample_rate_) return;
        if (--lb_sample_countdown_ != 0) return;
        lb_sample_countdown_ = lb_sample_rate_;
        shard.note_lb_sample(hash);
    }

    void lb_bucket_bytes_pass() {
        if (!lb_sample_rate_ || cached_now_ms_ < lb_bytes_next_ms_) return;
        lb_bytes_next_ms_ = cached_now_ms_ + 10;
        auto& owned = self_->shards();
        if (owned.empty()) return;
        if (lb_bytes_shard_cursor_ >= owned.size()) lb_bytes_shard_cursor_ = 0;
        (void)owned[lb_bytes_shard_cursor_++]->lb_scan_bucket_bytes(64);
    }

    template <bool IofusedPrivateQueue = false>
    uint32_t service_multi_retries() {
        if (multi_retries_.empty()) return 0;
        const Task task = multi_retries_.front();
        multi_retries_.pop_front();
        // execute() requeues an unfinished transaction task on multi_retries_ itself.  Returning
        // true here is work/progress, while ordinary inbox draining remains enabled so every shard
        // participant gets its first turn at the command barrier.
        execute<IofusedPrivateQueue>(task);
        return 1;
    }

    template <bool IofusedPrivateQueue = false>
    uint32_t service_atomic_deferred() {
        if (atomic_deferred_.empty()) return 0;
        const Task task = atomic_deferred_.front();
        atomic_deferred_.pop_front();
        Op& op = task.client->rob().at(task.op_id);
        const int32_t shard_id = task.shard >= 0 ? task.shard : op.shard;
        Shard& shard = srv_->shard(shard_id);
        shard.set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
        if (has_parked_predecessor(task, op, shard_id) ||
            xshard_task_should_defer(*srv_, shard, task, op)) {
            atomic_deferred_.push_back(task);
            // Keep polling the decision without preventing normal inbox drains. At low traffic this
            // also prevents an owner sleeping after another worker publishes the dependency.
            return 1;
        }
        const bool complete = snapshot_owner_state_ == SnapshotOwnerState::None
            ? execute<IofusedPrivateQueue>(task)
            : execute_snapshot_task<IofusedPrivateQueue>(task, true);
        if (!complete) xshard_retries_.push_back(task);
        return 1;
    }

    // PROGRAM ORDER AGAINST EVERY PARKED PREDECESSOR, NOT JUST THE DEFERRED ONES.
    // Both queues hold tasks that have been taken off the inbox but have not finished, and both are
    // serviced ahead of a fresh drain, so a younger task from the same connection can reach a shard
    // before an older one that is sitting in either. xshard_retries_ matters as much as
    // atomic_deferred_ because a bounded KEYS walk lives there between passes: service_atomic_
    // deferred() runs first in the loop, so a younger write parked earlier could install a key
    // behind the walker's cursor and be reported by a listing that must not see it yet.
    // Both deques are empty on any path with no cross-shard atomic window open.
    bool has_parked_predecessor(const Task& task, Op& op, int32_t shard_id) {
        if (__builtin_expect(atomic_deferred_.empty() && xshard_retries_.empty(), true))
            return false;
        return parked_predecessor_in(atomic_deferred_, task, op, shard_id) ||
               parked_predecessor_in(xshard_retries_, task, op, shard_id);
    }

    __attribute__((noinline)) bool parked_predecessor_in(const std::deque<Task>& parked,
                                                         const Task& task, Op& op,
                                                         int32_t shard_id) {
        for (const Task& older : parked) {
            if (older.client != task.client || older.op_id >= task.op_id) continue;
            Op& older_op = older.client->rob().at(older.op_id);
            if (!xshard_tasks_share_key(older, older_op, task, op, shard_id)) continue;
            // Either direction is the scan-ordering hold: a walker held behind an older
            // write, or a younger write held behind a walk that is already in flight.
            if (xshard_task_is_whole_owner(older) || xshard_task_is_whole_owner(task))
                self_->note_atomic_scan_hold();
            return true;
        }
        return false;
    }

    template <uint32_t BatchOps = kGenthreadExBatchOps,
              bool IofusedPrivateQueue = false>
    uint32_t service_ordered_deferred() {
        uint32_t work = 0;
        while (work < BatchOps && !ordered_deferred_.empty() && xshard_retries_.empty()) {
            const Task task = ordered_deferred_.front();
            ordered_deferred_.pop_front();
            if (snapshot_owner_state_ == SnapshotOwnerState::None) {
                if (!execute<IofusedPrivateQueue>(task)) xshard_retries_.push_back(task);
            } else {
                schedule_snapshot_task<IofusedPrivateQueue>(task);
            }
            work++;
        }
        return work;
    }

    int32_t task_shard(const Task& task) const {
        if (task.shard >= 0) return task.shard;
        if (!task.client) return -1;
        return task.client->rob().at(task.op_id).shard;
    }

    template <bool IofusedPrivateQueue = false>
    bool post_forwarded_task(const Task& task, uint32_t target) {
        ThreadCtx& destination = srv_->thread(target);
        if constexpr (IofusedPrivateQueue) {
            static_assert(Fused);
            return destination.post_iofused_task(
                self_->id(), task, handoff_ring(), self_->sig());
        } else {
            return destination.post_task(
                self_->id(), task, handoff_ring(), self_->sig());
        }
    }

    template <bool IofusedPrivateQueue = false>
    bool forward_stale_task(const Task& task) {
        const int32_t sid = task_shard(task);
        if (sid < 0) return false;
        const uint32_t target = srv_->worker_of_shard(sid);
        if (target == self_->id()) return false;
        if (!post_forwarded_task<IofusedPrivateQueue>(task, target))
            stale_tasks_.push_back(task);
        return true;
    }

    bool post_forwarded_release(const BorrowRelease& release, uint32_t target) {
        ThreadCtx& destination = srv_->thread(target);
        return destination.post_release(self_->id(), release, handoff_ring(), self_->sig());
    }

    bool forward_stale_release(const BorrowRelease& release) {
        if (release.shard < 0) std::abort();
        const uint32_t target = srv_->worker_of_shard(release.shard);
        if (target == self_->id()) return false;
        if (!post_forwarded_release(release, target)) stale_releases_.push_back(release);
        return true;
    }

    template <uint32_t BatchOps = kGenthreadExBatchOps,
              bool IofusedPrivateQueue = false>
    uint32_t service_stale_forwards() {
        uint32_t work = 0;
        while (!stale_tasks_.empty() && work < BatchOps) {
            const Task task = stale_tasks_.front();
            const int32_t sid = task_shard(task);
            if (sid < 0) std::abort();
            const uint32_t target = srv_->worker_of_shard(sid);
            if (target == self_->id()) {
                if constexpr (Fused) {
                    // A read-local fallback reached this FIFO after its own or an older group
                    // member's SPSC refusal. Executing it directly would jump the older queued
                    // tasks. Retry the tail publication and leave it stale until room exists.
                    if (read_local_enabled() && task.client &&
                        task.client->rob().at(task.op_id).read_local()) {
                        if (!post_forwarded_task(task, target)) break;
                        stale_tasks_.pop_front();
                        work++;
                        continue;
                    }
                }
                stale_tasks_.pop_front();
                if (!execute<IofusedPrivateQueue>(task)) xshard_retries_.push_back(task);
                work++;
                continue;
            }
            if (!post_forwarded_task<IofusedPrivateQueue>(task, target)) break;
            stale_tasks_.pop_front();
            work++;
        }
        while (!stale_releases_.empty() && work < BatchOps) {
            const BorrowRelease release = stale_releases_.front();
            const uint32_t target = srv_->worker_of_shard(release.shard);
            if (target == self_->id()) {
                stale_releases_.pop_front();
                srv_->shard(release.shard).store().unborrow(release.ptr);
                work++;
                continue;
            }
            if (!post_forwarded_release(release, target)) break;
            stale_releases_.pop_front();
            work++;
        }
        return work;
    }



    // Tell this client's io thread it has completed ops -- it retires the ROB and writes, so it is
    // what needs waking. Deduplicated: a pipelined burst of N completions on one client must not
    // enqueue it N times.
    void notify_sender(Client* c) {
        const uint32_t target = c->ifid_thread();
        if constexpr (Fused) {
            if (target == self_->id()) {
                // Self-owned work was consumed from the same SPSC lane as remote work. Schedule
                // local retirement without a redundant cross-thread post or wake.
                if (!fused_completion_) std::abort();
                fused_completion_(fused_io_context_, c);
                return;
            }
        }
        ThreadCtx& snd = srv_->thread(target);
        // THE READY-MASK PATH (#19/#20 ported): once the sender has assigned this connection a
        // slot, completion signalling is one idempotent bit -- no claim, no channel entry, no
        // pointer in flight. The empty->flagged RMW is the fence; whoever performs it owes the
        // park-wake.
        const uint32_t slot = c->wb_slot();
        if (slot != Client::kNoWbSlot) {
            // FENCE BEFORE THE READ-FIRST CHECK -- defect 5's exact shape, third appearance. Our
            // caller stored Done; ReadyMask::set() begins with a relaxed LOAD of the word, and TSO
            // lets that load run ahead of the store draining. Unfenced, it can read a stale 1 from
            // a signal the sender is consuming RIGHT NOW: we skip our set, the sender's drain reads
            // our op before the Done lands, and nobody ever signals again. Twelve connections were
            // stranded exactly this way at 4 nodes, where cross-CCD coherence stretches the window.
            std::atomic_thread_fence(std::memory_order_seq_cst);
            if (snd.ready().set(slot))
                snd.wake_if_parked(handoff_ring(), self_->sig());
            return;
        }
        // No slot yet: first contact. The claimed post carries the pointer to the sender, which
        // adopts on receipt. Runs once per connection. (An executor is never its own sender.)
        notify_sender_to(c, target);
    }

    void notify_sender_to(Client* c, uint32_t target) {
        bool expected = false;
        if (!c->retire_queued().compare_exchange_strong(expected, true, std::memory_order_acq_rel)) {
            TOMO_FORENSIC(c->n_defers.fetch_add(1, std::memory_order_relaxed));
            return;
        }
        TOMO_FORENSIC(c->n_claims.fetch_add(1, std::memory_order_relaxed));
        ThreadCtx& snd = srv_->thread(target);
        if (!snd.post_client(self_->id(), c, handoff_ring(), self_->sig())) {
            self_->sig().notify_drop++;
            c->retire_queued().store(false, std::memory_order_release);   // retry on a later pass
        }
    }

    void on_cqe(io_uring_cqe* cqe) {
        // Executors issue no sends; the ring exists for wakes.
        if (ur_kind(cqe->user_data) == UrKind::Wake) self_->sig().wakes_recv++;
        else if (ur_kind(cqe->user_data) == UrKind::SnapshotStart)
            begin_snapshot(ur_ptr<SnapshotManager>(cqe->user_data));
    }

    Server*    srv_  = nullptr;
    ThreadCtx* self_ = nullptr;
    Ring       ring_;
    WbEngine   wb_;    // never serves here; kept so the stats plumbing stays uniform across loops
    int64_t    cached_now_ms_ = 0;
    int64_t    blocking_beat_ms_ = 0;
    size_t     expire_shard_cursor_ = 0;
    size_t     atomic_cleanup_cursor_ = 0;
    uint64_t   live_config_version_ = UINT64_MAX;
    AofManager* aof_manager_ = nullptr;
    bool       maxmemory_enabled_ = false;
    bool       ex_sched_enabled_ = false;
    uint8_t    cached_lru_clock_ = 0;
    uint8_t    lru_clock_shift_ = 8;   // latched from cfg at loop start; 1<<N seconds per bucket
    uint32_t   lb_sample_rate_ = 0;
    uint32_t   lb_sample_countdown_ = 0;
    uint32_t   age_sample_rate_cached_ = 0;
    bool       lb_controller_armed_ = false;
    bool       lb_ack_wake_pending_ = false;
    bool       lb_rebind_pending_ = false;   // set at ExDrain ack; rebind owned shards after stage
    int64_t    lb_bytes_next_ms_ = 0;
    size_t     lb_bytes_shard_cursor_ = 0;
    SnapshotManager* snapshot_manager_ = nullptr;
    SnapshotOwnerState snapshot_owner_state_ = SnapshotOwnerState::None;
    uint64_t snapshot_epoch_ = 0;
    bool snapshot_was_cancelled_ = false;
    size_t snapshot_prepare_cursor_ = 0;
    size_t snapshot_progress_cursor_ = 0;
    std::vector<uint8_t> snapshot_done_shards_;
    std::vector<std::unique_ptr<SnapshotChunk>> snapshot_pending_chunks_;
    std::vector<std::deque<Task>> snapshot_backlogs_;
    std::deque<Task> atomic_deferred_;
    std::deque<Task> multi_retries_;
    std::deque<Task> xshard_retries_;
    std::deque<Task> ordered_deferred_;
    // Backpressure cannot turn a stale route into a dropped request/release. These queues contain
    // objects for shards this loop no longer owns and are serviced before ordinary inbox work.
    std::deque<Task> stale_tasks_;
    std::deque<BorrowRelease> stale_releases_;
    bool       notify_keyless_pending_ = false;
    bool       initialized_ = false;
    // Slow-log state at the true cold tail: nothing above it moves. `slowlog_armed_` is the single
    // predicted-false branch exec_batch pays when the feature is off.
    bool         slowlog_armed_ = false;
    SlowlogArm   slowlog_arm_{};
    SlowlogExState slowlog_state_{};
    // Fused-only state stays at the true tail so every split ExLoop field keeps its offset.
    uint32_t fused_idle_spins_ = 0;
    uint32_t fused_non_submit_rotations_ = 0;
    void* fused_io_context_ = nullptr;
    FusedCompletionFn fused_completion_ = nullptr;
    Ring* fused_handoff_ring_ = nullptr;
    // Pipelines 1/2 share the measured 128-task geometry; only pipeline 1 coalesces submissions.
    bool pipeline_batches_ = false;
    bool iofused_ = false;
    [[no_unique_address]] ReadLocalExState<Fused> read_local_;
};

using ExLoop = ExLoopT<false>;
using FusedExLoop = ExLoopT<true>;

// Disabled split executors retain the exact pre-read-local allocation stride.
static_assert(sizeof(ExLoop) == 5848);

}  // namespace tomo
