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
#include "server.h"
#include "signal.h"
#include "genthread_pipeline.h"
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

class ExLoop {
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
        if (!ring_.init(1024)) return false;
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

    // Generalized-thread tenure shares the physical thread with IoLoop. IoLoop remains the
    // published wake endpoint because it owns the blocking network wait; this executor keeps its
    // ring only as the source for cross-ring messages and persistence work.
    void activate_fused() {
        if (!initialized_) std::abort();
        blocking_bind_executor(srv_, self_, &ring_);
        for (Shard* shard : self_->shards())
            shard->bind_notify_pending(&notify_keyless_pending_);
    }

    void bind_fused_completion(void* context, FusedCompletionFn completion) {
        fused_io_context_ = context;
        fused_completion_ = completion;
    }

    // Cold progress callers (snapshot coordination and the pre-park sweep) first drain any arm-3
    // buffers in sequence order, then use the complete coarse executor pass as a backstop.
    uint32_t fused_pass() {
        const uint32_t staged = drain_pipeline_now();
        return staged + fused_pass_impl(true);
    }

    // Arm 3 keeps control/persistence work in the executor owner but lets the static schedule own
    // task gather/prefetch/execute.  This has no internal park and never consumes a Task.
    uint32_t fused_pipeline_control() { return fused_pass_impl(false); }

    // One non-blocking executor turn, called between passes of the fused network loop. This is the
    // ExLoop normal body without its role loop or park: the owning IoLoop performs the sole wait.
    uint32_t fused_pass_impl(bool consume_tasks) {
        cached_now_ms_ = realtime_ms();
        const bool lb_frozen = lb_controller_armed_ && srv_->lb_dispatch_paused();
        if (!lb_frozen) refresh_live_config();
        if (maxmemory_enabled_)
            cached_lru_clock_ = static_cast<uint8_t>(
                (static_cast<uint64_t>(cached_now_ms_ / 1000) >> lru_clock_shift_) & 0x1f);

        uint32_t did = 0;
        if (lb_frozen) {
            if (!srv_->lb_acked(self_->id())) {
                did += service_stale_forwards();
                did += drain_releases(true);
                did += service_multi_retries();
                did += service_atomic_deferred();
                did += service_xshard_retries();
                if (xshard_retries_.empty()) did += service_ordered_deferred();
                if (consume_tasks && xshard_retries_.empty() && ordered_deferred_.empty())
                    did += drain_tasks(true);
                did += aof_flush_pass();
                did += drain_notify_keyless(self_->sig());
            }
            did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
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
                if (consume_tasks && xshard_retries_.empty() && ordered_deferred_.empty())
                    did += snapshot_owner_state_ == SnapshotOwnerState::None
                               ? drain_tasks() : drain_tasks_snapshot();
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
        if (did) {
            did += drain_notify_keyless(self_->sig());
            ring_.submit_and_reap();
            fused_idle_spins_ = 0;
            return did;
        }
        if (!consume_tasks) return 0;
        if (lb_frozen) return 0;
        if (++fused_idle_spins_ < kExSpinBudget) return 0;
        fused_idle_spins_ = 0;
        did = sweep();
        if (did) ring_.submit_and_reap();
        return did;
    }

    uint32_t fused_sweep() {
        // Once an LB ExDrain acknowledgement is visible this owner is a hard safe point. IoLoop's
        // mask-independent pre-park backstop must not re-enter expiry/cleanup behind that ack.
        if (lb_controller_armed_ && srv_->lb_dispatch_paused()) return fused_pass();
        cached_now_ms_ = realtime_ms();
        const uint32_t did = drain_pipeline_now() + sweep();
        if (did) ring_.submit_and_reap();
        return did;
    }

    // ---- arm-3 EX micro-stages ---------------------------------------------------------------
    uint32_t pipeline_input_prefetch() {
        return self_->read_ahead_task_inputs(1, [&](const Task& task) {
            if (task.client) __builtin_prefetch(&task.client->rob().at(task.op_id), 0, 2);
        });
    }

    uint32_t pipeline_fill(bool unmasked = false) {
        if (!pipeline_tasks_allowed() || !xshard_retries_.empty() ||
            !ordered_deferred_.empty()) return 0;
        // Snapshot continuations retain their established owner-local scheduling machinery; the
        // ordinary hot state is the only one split across the bucket/object stages.
        if (snapshot_owner_state_ != SnapshotOwnerState::None)
            return drain_tasks_snapshot(unmasked);
        ExPipelineBatch* batch = empty_pipeline_batch();
        if (!batch) return 0;
        batch->count = self_->gather_tasks_bounded(
            batch->tasks.data(), batch->producers.data(), kGenthreadExBatchOps, unmasked);
        if (!batch->count) return 0;
        batch->sequence = next_pipeline_sequence_++;
        batch->state = ExPipelineState::Filled;
        return batch->count;
    }

    uint32_t pipeline_bucket_prefetch() {
        ExPipelineBatch* batch = oldest_pipeline_batch(ExPipelineState::Filled);
        if (!batch) return 0;
        prefetch_exec_batch(batch->tasks.data(), batch->count);
        batch->state = ExPipelineState::BucketPrefetched;
        return batch->count;
    }

    uint32_t pipeline_object_prefetch() {
        ExPipelineBatch* batch = oldest_pipeline_batch(ExPipelineState::BucketPrefetched);
        if (!batch) return 0;
        for (uint32_t i = 0; i < batch->count; i++) {
            const Task& task = batch->tasks[i];
            if (!task.client || task.scatter) continue;
            const Op& op = task.client->rob().at(task.op_id);
            const int32_t shard = task.shard >= 0 ? task.shard : op.shard;
            if (shard >= 0 &&
                !(op.spec->flags & (CmdFlags::CursorShard | CmdFlags::RandomShard)))
                srv_->shard(shard).store().prefetch_object(op.hash);
        }
        batch->state = ExPipelineState::Ready;
        return batch->count;
    }

    uint32_t pipeline_execute() {
        if (!pipeline_tasks_allowed()) return 0;
        ExPipelineBatch* batch = oldest_pipeline_batch(ExPipelineState::Ready);
        if (!batch) return 0;
        if (snapshot_owner_state_ == SnapshotOwnerState::None)
            exec_batch_prefetched(batch->tasks.data(), batch->count);
        else
            for (uint32_t i = 0; i < batch->count; i++) schedule_snapshot_task(batch->tasks[i]);
        self_->retire_gathered_tasks(batch->producers.data(), batch->count);
        self_->sig().ops += batch->count;
        const uint32_t n = batch->count;
        batch->count = 0;
        batch->state = ExPipelineState::Empty;
        // Remote completions prepared MSG_RING wakes on the executor-owned ring.  In arm 2 the
        // enclosing fused pass submitted that ring after drain_tasks(); arm 3 executes after the
        // control pass, so EX.EXECUTE itself must publish those prepared wakes before the owner can
        // park.  Local completions use the direct callback and make this a harmless empty submit.
        ring_.submit_and_reap();
        return n;
    }

    void fused_snapshot_start(SnapshotManager* manager) { begin_snapshot(manager); }

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
                self_->sample_depth(busy.start_ns() / 1000);
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
    enum class ExPipelineState : uint8_t { Empty, Filled, BucketPrefetched, Ready };
    struct ExPipelineBatch {
        std::array<Task, kGenthreadExBatchOps> tasks{};
        std::array<uint32_t, kGenthreadExBatchOps> producers{};
        uint64_t sequence = 0;
        uint32_t count = 0;
        ExPipelineState state = ExPipelineState::Empty;
    };

    bool pipeline_tasks_allowed() const {
        if (snapshot_blocks_tasks()) return false;
        return !(lb_controller_armed_ && srv_->lb_dispatch_paused() &&
                 srv_->lb_acked(self_->id()));
    }

    ExPipelineBatch* empty_pipeline_batch() {
        for (ExPipelineBatch& batch : pipeline_batches_)
            if (batch.state == ExPipelineState::Empty) return &batch;
        return nullptr;
    }

    ExPipelineBatch* oldest_pipeline_batch(ExPipelineState state) {
        ExPipelineBatch* oldest = nullptr;
        for (ExPipelineBatch& batch : pipeline_batches_)
            if (batch.state == state && (!oldest || batch.sequence < oldest->sequence))
                oldest = &batch;
        return oldest;
    }

    ExPipelineBatch* oldest_pipeline_batch() {
        ExPipelineBatch* oldest = nullptr;
        for (ExPipelineBatch& batch : pipeline_batches_)
            if (batch.state != ExPipelineState::Empty &&
                (!oldest || batch.sequence < oldest->sequence)) oldest = &batch;
        return oldest;
    }

    uint32_t drain_pipeline_now() {
        if (!pipeline_tasks_allowed()) return 0;
        uint32_t work = 0;
        while (ExPipelineBatch* batch = oldest_pipeline_batch()) {
            if (batch->state == ExPipelineState::Filled) {
                prefetch_exec_batch(batch->tasks.data(), batch->count);
                batch->state = ExPipelineState::BucketPrefetched;
            }
            if (batch->state == ExPipelineState::BucketPrefetched) {
                for (uint32_t i = 0; i < batch->count; i++) {
                    const Task& task = batch->tasks[i];
                    if (!task.client || task.scatter) continue;
                    const Op& op = task.client->rob().at(task.op_id);
                    const int32_t shard = task.shard >= 0 ? task.shard : op.shard;
                    if (shard >= 0 &&
                        !(op.spec->flags & (CmdFlags::CursorShard | CmdFlags::RandomShard)))
                        srv_->shard(shard).store().prefetch_object(op.hash);
                }
                batch->state = ExPipelineState::Ready;
            }
            if (snapshot_owner_state_ == SnapshotOwnerState::None)
                exec_batch_prefetched(batch->tasks.data(), batch->count);
            else
                for (uint32_t i = 0; i < batch->count; i++)
                    schedule_snapshot_task(batch->tasks[i]);
            self_->retire_gathered_tasks(batch->producers.data(), batch->count);
            self_->sig().ops += batch->count;
            work += batch->count;
            batch->count = 0;
            batch->state = ExPipelineState::Empty;
        }
        if (work) ring_.submit_and_reap();
        return work;
    }

    bool flip_quiesced() const {
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
    uint32_t sweep() {
        uint32_t n = snapshot_control_pass() + service_stale_forwards() + drain_releases(true);
        if (!snapshot_blocks_tasks()) {
            n += service_multi_retries();
            n += service_atomic_deferred();
            n += service_xshard_retries();
            if (xshard_retries_.empty()) n += service_ordered_deferred();
            if (xshard_retries_.empty() && ordered_deferred_.empty())
                n += snapshot_owner_state_ == SnapshotOwnerState::None
                         ? drain_tasks(true) : drain_tasks_snapshot(true);
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

    uint32_t drain_tasks(bool unmasked = false) {
        Task batch[kExecBatch];
        uint32_t held = 0;
        auto take = [&](const Task& t) {
            batch[held++] = t;
            if (held == kExecBatch) { exec_batch(batch, held); held = 0; }
        };
        const uint32_t n = unmasked ? self_->drain_tasks_unmasked(take)
                                    : self_->drain_tasks(take);
        if (held) exec_batch(batch, held);
        self_->sig().ops += n;
        return n;
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
            const uint32_t n = service_snapshot_backlogs(kExecBatch, false);
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

    bool execute_snapshot_task(const Task& task, bool capture_writes) {
        // MULTI's tagged task owns its command images outside the public ROB and performs the
        // snapshot pre-image gate per installed transaction key.  Never decode it as a normal op.
        if (multi_task_tagged(task)) return execute(task);
        if (!task.client) return execute(task);
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
            return execute(task);
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
        if (!execute(task)) return false;
        shard.publish_size();
        return true;
    }

    void schedule_snapshot_task(const Task& task) {
        if (multi_task_tagged(task)) { execute(task); return; }
        if (!task.client) { execute(task); return; }
        // A bounded scatter continuation is still the oldest task on this owner.  Holding later
        // work here preserves the queue-order RYOW argument without installing a conn barrier for
        // KEYS.  Snapshot-gated scatter writes use the same ordering hold while Pending.
        if (!xshard_retries_.empty()) { ordered_deferred_.push_back(task); return; }
        if (task.scatter) {
            if (!execute_snapshot_task(task, true)) xshard_retries_.push_back(task);
            return;
        }
        const Op& op = task.client->rob().at(task.op_id);
        const int32_t sid = task.shard >= 0 ? task.shard : op.shard;
        auto& queue = snapshot_backlogs_[static_cast<uint32_t>(sid)];
        if (!queue.empty() || !execute_snapshot_task(task, true)) queue.push_back(task);
    }

    uint32_t service_snapshot_backlogs(uint32_t budget, bool capture_writes = true) {
        uint32_t n = 0;
        for (Shard* shard : self_->shards()) {
            auto& queue = snapshot_backlogs_[static_cast<uint32_t>(shard->id())];
            while (budget && !queue.empty()) {
                if (!execute_snapshot_task(queue.front(), capture_writes)) break;
                queue.pop_front(); budget--; n++;
            }
            if (!budget) break;
        }
        return n;
    }

    uint32_t drain_tasks_snapshot(bool unmasked = false) {
        auto take = [&](const Task& task) { schedule_snapshot_task(task); };
        const uint32_t n = unmasked ? self_->drain_tasks_unmasked(take)
                                    : self_->drain_tasks(take);
        self_->sig().ops += n;
        // Retire at least as many deferred Tasks as this drain can add, plus one batch of old debt;
        // otherwise a saturated post-capture owner could remain in Draining forever.
        return n + service_snapshot_backlogs(kExecBatch + n);
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
                const bool ok = execute(batch[i]);
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
            if (execute(batch[i])) continue;
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

    void prefetch_exec_batch(const Task* batch, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            if (!batch[i].client) continue;
            const Op& op = batch[i].client->rob().at(batch[i].op_id);
            const int32_t shard = batch[i].shard >= 0 ? batch[i].shard : op.shard;
            if (shard >= 0 && !batch[i].scatter &&
                !(op.spec->flags & (CmdFlags::CursorShard | CmdFlags::RandomShard)))
                srv_->shard(shard).store().prefetch(op.hash);
        }
    }

    // Consume a bucket-prefetched homogeneous batch.  Arm 2 calls this immediately after the
    // prefetch loop; arm 3 reaches it later through the static schedule.
    void exec_batch_prefetched(const Task* batch, uint32_t n) {
        if (!xshard_retries_.empty()) {
            for (uint32_t i = 0; i < n; i++) ordered_deferred_.push_back(batch[i]);
            return;
        }
        // THE ENTIRE DISABLED-FEATURE COST OF SLOWLOG/LATENCY: one predicted-false branch here,
        // once per batch of up to kExecBatch ops. No clock is read and the recorder is not linked
        // into this loop at all. The armed body is out of line in exec_batch_timed().
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
        // One publish per batch, covering every shard this batch touched. Cheaper than tracking
        // which ones changed, and this thread owns all of them.
        for (Shard* sh : self_->shards()) sh->publish_size();
        // Reclamation is owner-batched rather than one posted task per completed group. Visit the
        // owned shards after each atomic batch so their pending-entry lists stay short.
        if (xshard_retries_.empty() && srv_->atomic_work_active()) {
            atomic_cleanup_cycle(256);
        }
    }

    // Coarse arm compatibility: prefetch the whole batch and consume it without an intervening
    // micro-stage.  The same two tight loops are reused by both experimental commits.
    void exec_batch(const Task* batch, uint32_t n) {
        prefetch_exec_batch(batch, n);
        exec_batch_prefetched(batch, n);
    }

    bool execute(const Task& t) {
        // Forwarding, rather than a request epoch, resolves the route-read/enqueue race.  This check
        // must precede every shard dereference, including tagged MULTI and ownerless cleanup tasks.
        if (forward_stale_task(t)) return true;
        if (multi_task_tagged(t)) {
            Shard& shard = srv_->shard(t.shard);
            shard.set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
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
            return blocking_execute(*srv_, *self_, ring_, t, sh, op);
        }
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
                struct LbVisit { ExLoop* loop; Shard* shard; } visit{this, &sh};
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
            const ScatterFinish finished = xshard_complete(*srv_, *self_, ring_, t, op);
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

    uint32_t service_xshard_retries() {
        if (xshard_retries_.empty()) return 0;
        const Task task = xshard_retries_.front();
        xshard_retries_.pop_front();
        const bool complete = snapshot_owner_state_ == SnapshotOwnerState::None
            ? execute(task) : execute_snapshot_task(task, true);
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

    uint32_t service_multi_retries() {
        if (multi_retries_.empty()) return 0;
        const Task task = multi_retries_.front();
        multi_retries_.pop_front();
        // execute() requeues an unfinished transaction task on multi_retries_ itself.  Returning
        // true here is work/progress, while ordinary inbox draining remains enabled so every shard
        // participant gets its first turn at the command barrier.
        execute(task);
        return 1;
    }

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
            ? execute(task) : execute_snapshot_task(task, true);
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

    uint32_t service_ordered_deferred() {
        uint32_t work = 0;
        while (work < kExecBatch && !ordered_deferred_.empty() && xshard_retries_.empty()) {
            const Task task = ordered_deferred_.front();
            ordered_deferred_.pop_front();
            if (snapshot_owner_state_ == SnapshotOwnerState::None) {
                if (!execute(task)) xshard_retries_.push_back(task);
            } else {
                schedule_snapshot_task(task);
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

    bool post_forwarded_task(const Task& task, uint32_t target) {
        ThreadCtx& destination = srv_->thread(target);
        return destination.post_task(self_->id(), task, ring_, self_->sig());
    }

    bool forward_stale_task(const Task& task) {
        const int32_t sid = task_shard(task);
        if (sid < 0) return false;
        const uint32_t target = srv_->worker_of_shard(sid);
        if (target == self_->id()) return false;
        if (!post_forwarded_task(task, target)) stale_tasks_.push_back(task);
        return true;
    }

    bool post_forwarded_release(const BorrowRelease& release, uint32_t target) {
        ThreadCtx& destination = srv_->thread(target);
        return destination.post_release(self_->id(), release, ring_, self_->sig());
    }

    bool forward_stale_release(const BorrowRelease& release) {
        if (release.shard < 0) std::abort();
        const uint32_t target = srv_->worker_of_shard(release.shard);
        if (target == self_->id()) return false;
        if (!post_forwarded_release(release, target)) stale_releases_.push_back(release);
        return true;
    }

    uint32_t service_stale_forwards() {
        uint32_t work = 0;
        while (!stale_tasks_.empty() && work < kExecBatch) {
            const Task task = stale_tasks_.front();
            const int32_t sid = task_shard(task);
            if (sid < 0) std::abort();
            const uint32_t target = srv_->worker_of_shard(sid);
            if (target == self_->id()) {
                stale_tasks_.pop_front();
                if (!execute(task)) xshard_retries_.push_back(task);
                work++;
                continue;
            }
            if (!post_forwarded_task(task, target)) break;
            stale_tasks_.pop_front();
            work++;
        }
        while (!stale_releases_.empty() && work < kExecBatch) {
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
        if (target == self_->id()) {
            // Queue-consumed self work completes in the executor phase. The callback schedules
            // retirement on the same physical thread without a redundant cross-thread wake.
            if (!fused_completion_) std::abort();
            fused_completion_(fused_io_context_, c);
            return;
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
                snd.wake_if_parked(ring_, self_->sig());
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
        if (!snd.post_client(self_->id(), c, ring_, self_->sig())) {
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
    uint8_t    cached_lru_clock_ = 0;
    uint8_t    lru_clock_shift_ = 8;   // latched from cfg at loop start; 1<<N seconds per bucket
    uint32_t   lb_sample_rate_ = 0;
    uint32_t   lb_sample_countdown_ = 0;
    bool       lb_controller_armed_ = false;
    bool       lb_ack_wake_pending_ = false;
    bool       lb_rebind_pending_ = false;   // set at ExDrain ack; rebind owned shards after stage
    int64_t    lb_bytes_next_ms_ = 0;
    size_t     lb_bytes_shard_cursor_ = 0;
    uint32_t   fused_idle_spins_ = 0;
    void*      fused_io_context_ = nullptr;
    FusedCompletionFn fused_completion_ = nullptr;
    std::array<ExPipelineBatch, kGenthreadExBuffers> pipeline_batches_{};
    uint64_t next_pipeline_sequence_ = 1;
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
};

}  // namespace tomo
