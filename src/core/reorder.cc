// R7 role bodies are isolated so the FIFO compiler input stays unchanged.
// tests/r7shadow_sync.py checks the copied envelopes against the current mainline methods.
#include "genthread.h"
#include "fused_boot_gate.h"
#include "shutdown_report.h"
#include "../net/unix_listener.h"
#include "ex_loop.h"
#include "io_loop.h"
#include "reorder.h"

namespace tomo {
// A cold capability predicate also supplies the exact-layout kind-A PAD control.
// Only boot and INFO call it. The PAD changes this body to return false.
__attribute__((noipa)) bool reorder_available() { return true; }
namespace r7 {
__attribute__((noipa)) bool shadow_available() { return true; }
}

void append_reorder_info(std::string& body, const ModeScheduleStats* stats, uint32_t nthreads) {
    TOMO_R7_PATH();
    uint64_t batches = 0, multi = 0, permutations = 0;
    uint32_t max_batch = 0;
    if (stats) for (uint32_t tid = 0; tid < nthreads; tid++) {
        const auto& s = stats[tid];
        batches += s.reorder_batches.load(std::memory_order_relaxed);
        multi += s.reorder_multi_client_runs.load(std::memory_order_relaxed);
        permutations += s.reorder_permuted_runs.load(std::memory_order_relaxed);
        max_batch = std::max(max_batch, s.reorder_max_batch.load(std::memory_order_relaxed));
    }
    char row[512];
    const int n = std::snprintf(row, sizeof(row),
        "reorder_batches:%llu\r\nreorder_multi_client_runs:%llu\r\n"
        "reorder_permuted_runs:%llu\r\nreorder_max_batch:%u\r\nreorder_shadow:%u\r\n",
        static_cast<unsigned long long>(batches), static_cast<unsigned long long>(multi),
        static_cast<unsigned long long>(permutations), max_batch, r7::shadow_available());
    if (n < 0 || static_cast<size_t>(n) >= sizeof(row)) std::abort();
    body.append(row, static_cast<size_t>(n));
}

template <bool Fused>
template <uint32_t BatchOps, bool IofusedPrivateQueue, typename Filler>
__attribute__((noinline))
uint32_t ExLoopT<Fused>::r7_drain_tasks(bool unmasked, Filler* filler,
                               bool* filler_used) {
    TOMO_R7_PATH();
    if (!r7::priority_enabled(srv_->cfg().reorder)) {
        if constexpr (std::is_void_v<Filler>)
            return drain_tasks<BatchOps, IofusedPrivateQueue>(unmasked);
        else return drain_tasks_with_filler<BatchOps, IofusedPrivateQueue>(unmasked, *filler, *filler_used);
    }
    if (r7::shadow_available())
        return r7_drain_tasks_impl<true, BatchOps, IofusedPrivateQueue>(unmasked, filler, filler_used);
    return r7_drain_tasks_impl<false, BatchOps, IofusedPrivateQueue>(unmasked, filler, filler_used);
}

template <bool Fused>
template <bool Shadow, uint32_t BatchOps, bool IofusedPrivateQueue, typename Filler>
uint32_t ExLoopT<Fused>::r7_drain_tasks_impl(bool unmasked, Filler* filler,
                                          bool* filler_used) {
    TOMO_R7_PATH();
    std::conditional_t<Shadow, r7::ShadowReorderQueues<BatchOps>, r7::ExReorderQueues<BatchOps>> queues;
    Task batch[BatchOps];
    uint32_t held = 0;
    auto emit = [&](const Task* selected, uint32_t count, ReorderResult witness) {
        srv_->mode_schedule_stats(self_->id()).note_reorder(count, witness);
        if (!xshard_retries_.empty()) {
            for (uint32_t i = 0; i < count; i++) ordered_deferred_.push_back(selected[i]);
            return;
        }
        if (overlap_prefetch_enabled(count)) prefetch_overlap_batch(selected, count);
        else prefetch_exec_batch(selected, count);
        if constexpr (!std::is_void_v<Filler>) {
            if (!*filler_used) {
                (*filler)();
                *filler_used = true;
            }
        }
        exec_batch_prefetched<IofusedPrivateQueue>(selected, count);
    };
    auto take = [&](const Task& task) {
        batch[held++] = task;
        if (held == BatchOps) {
            queues.submit(batch, held, emit);
            held = 0;
        }
    };
    const uint32_t n = unmasked
        ? self_->drain_tasks_unmasked<IofusedPrivateQueue>(take)
        : self_->drain_tasks<IofusedPrivateQueue>(take);
    if (held) queues.submit(batch, held, emit);
    queues.finish(emit);
    self_->sig().ops += n;
    return n;
}

template <bool Fused>
template <uint32_t BatchOps, bool IofusedPrivateQueue, typename Filler>
uint32_t ExLoopT<Fused>::r7_drain_tasks_with_filler(bool unmasked, Filler& filler,
                                                  bool& filler_used) {
    TOMO_R7_PATH();
    return r7_drain_tasks<BatchOps, IofusedPrivateQueue>(unmasked, &filler, &filler_used);
}

// BEGIN R7 GENERATED ENVELOPES
class IoLoop::r7_ReadLocalDemotionPlan {
private:
    enum class ReadKind : uint8_t { Ordinary, Scatter, Error };

    struct Storage {
        uint64_t ids[kRobWindow];
        ScatterState* scatter[kRobWindow];
        uint16_t scatter_tasks[kRobWindow];
        ReadKind kinds[kRobWindow];
        ReadLocalFallbackReason reasons[kRobWindow];
        uint32_t owners[kMaxThreads];
        uint32_t remaining[kMaxThreads];
    };

public:
    r7_ReadLocalDemotionPlan() = default;
    ~r7_ReadLocalDemotionPlan() { cancel(); }
    r7_ReadLocalDemotionPlan(const r7_ReadLocalDemotionPlan&) = delete;
    r7_ReadLocalDemotionPlan& operator=(const r7_ReadLocalDemotionPlan&) = delete;

    bool prepare(IoLoop& loop, Client* client, uint64_t hash,
                 bool require_hash_match, int32_t reserve_shard = -1,
                 ReadLocalFallbackReason reason =
                     ReadLocalFallbackReason::ContextOwnerKey,
                 bool reserve_current_without_reads = false,
                 const uint64_t* fallback_ids = nullptr,
                 const ReadLocalFallbackReason* fallback_reasons = nullptr,
                 uint32_t fallback_count = 0,
                 const Op* intersect_command = nullptr,
                 bool intersect_filter_miss = false) {
        if (loop_ || !client) std::abort();
        if (reason == ReadLocalFallbackReason::None) std::abort();
        if ((fallback_ids == nullptr) != (fallback_reasons == nullptr) ||
            (fallback_count != 0) != (fallback_ids != nullptr) ||
            (fallback_count && intersect_command) ||
            (intersect_filter_miss && !intersect_command)) std::abort();
        Rob<kRobWindow>& rob = client->rob();
        const bool reserve_current =
            reserve_current_without_reads && reserve_shard >= 0;
        // A caller that already walked a complete precise keyset may pass its authoritative
        // pending-filter miss. Consume it before reloading the same filter; hit/unknown remains
        // false and takes the unchanged exact-selection path below.
        if (!reserve_current && !fallback_count && intersect_filter_miss) return true;
        // Current intersect callers also passed a known hit when they reach the exact path.
        // Unknown remains safe without this shortcut: collecting an empty set returns below.
        if (!intersect_command && !rob.has_pending_read_local() && !reserve_current)
            return true;
        // Superset pre-check (ReadLocalPendingFilter, rob.h): the filter holds every key hash
        // any still-pending local read of this connection can touch, so a miss PROVES that no
        // pending read shares the point hash / any declared key of the exact command. The
        // ordinary disjoint write returns here without allocating or walking anything; a hit
        // runs the unchanged exact plan below. EX seeds are selected by id, and a reserved
        // current op needs the plan regardless of reads, so neither consults the filter.
        if (!reserve_current && !fallback_count && !intersect_command &&
            require_hash_match && !rob.read_local_pending_may_touch(hash)) return true;
        // Select on the stack; Storage is only paid for once a read is actually demoted or
        // the current op must be reserved.
        uint64_t ids[kRobWindow];
        ReadLocalFallbackReason reasons[kRobWindow];
        bool selected[kRobWindow] = {};
        const uint32_t pending =
            rob.collect_pending_read_local(0, false, ids, kRobWindow);
        for (uint32_t i = 0; i < pending; i++) reasons[i] = reason;
        bool selective = false;
        bool any_selected = false;
        // The key-walking modes visit every pending read, so they also recompute the exact
        // pending-key filter and hand it back: false hits never accumulate.
        ReadLocalPendingFilter exact;
        bool exact_known = false;
        if (pending && fallback_count) {
            selective = true;
            for (uint32_t seed = 0; seed < fallback_count; seed++) {
                if (fallback_reasons[seed] == ReadLocalFallbackReason::None) continue;
                bool found = false;
                for (uint32_t i = 0; i < pending; i++) {
                    if (ids[i] != fallback_ids[seed]) continue;
                    selected[i] = true;
                    any_selected = true;
                    reasons[i] = fallback_reasons[seed];
                    found = true;
                    break;
                }
                if (!found) std::abort();
            }
        } else if (pending && intersect_command) {
            selective = true;
            exact_known = true;
            for (uint32_t i = 0; i < pending; i++) {
                selected[i] = read_local_commands_overlap_precise_keyset_collect(
                    rob.at(ids[i]), *intersect_command, exact);
                any_selected |= selected[i];
            }
        } else if (pending && require_hash_match) {
            selective = true;
            exact_known = true;
            for (uint32_t i = 0; i < pending; i++) {
                selected[i] = read_local_command_touches_hash_collect(
                    rob.at(ids[i]), hash, exact);
                any_selected |= selected[i];
            }
        }
        if (exact_known) rob.reset_read_local_pending_filter(exact);
        if (selective && any_selected) {
            // MGET makes key overlap a graph rather than a single hash. Close every selective
            // parser or EX seed transitively: if a selected MGET touches an otherwise unrelated
            // key, its older/later local read of that key must join the same owner wave too.
            // With nothing selected the closure is the identity, so it is skipped.
            bool changed;
            do {
                changed = false;
                for (uint32_t i = 0; i < pending; i++) {
                    if (selected[i]) continue;
                    const Op& candidate = rob.at(ids[i]);
                    for (uint32_t prior = 0; prior < pending; prior++) {
                        if (!selected[prior] ||
                            !read_local_commands_overlap(
                                candidate, rob.at(ids[prior]))) continue;
                        selected[i] = true;
                        reasons[i] = ReadLocalFallbackReason::ContextOwnerKey;
                        changed = true;
                        break;
                    }
                }
            } while (changed);
        }
        uint32_t count = pending;
        if (selective) {
            uint32_t out = 0;
            for (uint32_t i = 0; i < pending; i++) {
                if (!selected[i]) continue;
                ids[out] = ids[i];
                reasons[out] = reasons[i];
                out++;
            }
            count = out;
        }
        if (!count && !reserve_current) return true;
        storage_.reset(new (std::nothrow) Storage);
        if (!storage_) return false;
        count_ = count;
        for (uint32_t i = 0; i < count_; i++) {
            storage_->ids[i] = ids[i];
            storage_->reasons[i] = reasons[i];
        }

        loop_ = &loop;
        client_ = client;
        for (uint32_t i = 0; i < count_; i++) {
            storage_->kinds[i] = ReadKind::Ordinary;
            storage_->scatter[i] = nullptr;
            storage_->scatter_tasks[i] = 0;
        }
        for (uint32_t i = 0; i < count_; i++) {
            Op& op = rob.at(storage_->ids[i]);
            if (read_local_mget(op)) {
                read_local_clear_reply(op);
                ScatterDispatch dispatch;
                const ScatterPrepare prepared = xshard_prepare(
                    *loop.srv_, op, loop.scatter_pool_, loop.self_->id(),
                    client->id(), dispatch, false, client);
                if (prepared == ScatterPrepare::Backpressure) {
                    // A local run can contain more cross-shard reads than the existing
                    // snapshot window admits concurrently. Publish the already prepared ROB
                    // prefix as one ordered wave and leave this op plus the exact selected
                    // remainder tagged in the local lane. The next EX pass demotes only entries
                    // that overlap the unfinished owner wave; parser callers reparse their
                    // unconsumed current frame after the same prefix commit.
                    if (i) {
                        const uint32_t selected_count = count_;
                        partial_begin_ = i;
                        partial_count_ = selected_count - i;
                        count_ = i;
                        partial_ = true;
                        break;
                    }
                    cancel();
                    return false;
                }
                if (prepared == ScatterPrepare::Error) {
                    storage_->kinds[i] = ReadKind::Error;
                    continue;
                }
                if (prepared == ScatterPrepare::Ready) {
                    storage_->kinds[i] = ReadKind::Scatter;
                    storage_->scatter[i] = dispatch.state;
                    storage_->scatter_tasks[i] = dispatch.nshards;
                    for (uint32_t task = 0; task < dispatch.nshards; task++) {
                        const int32_t shard = xshard_dispatch_shard(dispatch, task);
                        if (shard < 0) std::abort();
                        add_owner(loop.srv_->worker_of_shard(shard));
                    }
                    continue;
                }
            }
            if (op.shard < 0) std::abort();
            add_owner(loop.srv_->worker_of_shard(op.shard));
        }
        if (!partial_ && reserve_shard >= 0) {
            reserved_current_worker_ = static_cast<int32_t>(
                loop.srv_->worker_of_shard(reserve_shard));
            add_owner(static_cast<uint32_t>(reserved_current_worker_));
        }

        uint32_t reserved = 0;
        for (; reserved < nowners_; reserved++) {
            if (!loop.srv_->thread(storage_->owners[reserved]).reserve_task_slots(
                    loop.self_->id(), storage_->remaining[reserved]))
                break;
        }
        if (reserved != nowners_) {
            for (uint32_t i = 0; i < reserved; i++)
                loop.srv_->thread(storage_->owners[i]).cancel_task_reservation(
                    loop.self_->id(), storage_->remaining[i]);
            discard_prepared_reads();
            clear();
            return false;
        }
        reservations_live_ = true;
        return true;
    }

    bool active() const { return loop_ != nullptr; }
    bool current_reserved() const { return reserved_current_worker_ >= 0; }
    bool partial() const { return partial_; }
    uint32_t read_count() const { return count_; }

    void commit_reads() {
        if (!loop_) return;
        Rob<kRobWindow>& rob = client_->rob();
        bool completed_locally = false;
        for (uint32_t i = 0; i < count_; i++) {
            Op& op = rob.at(storage_->ids[i]);
            if (storage_->kinds[i] == ReadKind::Error) {
                rob.complete_pending_read_local(storage_->ids[i]);
                op.state.store(OpState::Done, std::memory_order_release);
                completed_locally = true;
                continue;
            }
            if (storage_->kinds[i] == ReadKind::Scatter) {
                ScatterState* state = storage_->scatter[i];
                if (!state || !storage_->scatter_tasks[i]) std::abort();
                ScatterDispatch dispatch;
                dispatch.state = state;
                dispatch.nshards = storage_->scatter_tasks[i];
                op.attach_scatter_state(state);
                storage_->scatter[i] = nullptr;  // the Op/IO retirement path owns it now
                loop_->self_->note_command(op.spec->id);
                for (uint32_t task = 0; task < dispatch.nshards; task++) {
                    const int32_t shard = xshard_dispatch_shard(dispatch, task);
                    const uint32_t worker = loop_->srv_->worker_of_shard(shard);
                    loop_->srv_->thread(worker).post_task_reserved_quiet(
                        loop_->self_->id(),
                        Task{client_, storage_->ids[i], shard, state},
                        loop_->self_->sig());
                    consume(worker);
                    loop_->touch_worker(worker);
                }
            } else {
                const uint32_t worker = loop_->srv_->worker_of_shard(op.shard);
                loop_->srv_->thread(worker).post_task_reserved_quiet(
                    loop_->self_->id(),
                    r7::shadow_demoted_task(client_, storage_->ids[i]),
                    loop_->self_->sig());
                consume(worker);
                loop_->touch_worker(worker);
            }
            rob.publish_pending_read_local_to_owner(storage_->ids[i]);
        }
        // A partial plan's suffix is still local. Publish its exact fallback tags only after
        // the prepared prefix is irrevocable; cancel/backpressure before commit must leave the
        // lane untouched so a later EX pass can probe it normally.
        for (uint32_t i = 0; i < partial_count_; i++) {
            const uint32_t pending = partial_begin_ + i;
            loop_->fused_executor_->preserve_local_read_fallback(
                client_, storage_->ids[pending], storage_->reasons[pending]);
        }
        if (count_) {
            ReadLocalStats& stats = loop_->self_->read_local_stats();
            for (uint32_t i = 0; i < count_; i++) {
                loop_->fused_executor_->note_local_read_demoted(
                    rob.at(storage_->ids[i]));
                stats.note_fallback(
                    storage_->reasons[i], read_local_mget(rob.at(storage_->ids[i])));
            }
        }
        if (completed_locally) {
            // Error lowering can finish an MGET locally; release its fence through the
            // ordinary completion wake in both O1 modes.
            loop_->fused_executor_completion<false>(client_);
        }
        count_ = 0;  // every prepared scatter/marker is now owned by its published Op
        if (reserved_current_worker_ < 0) {
            for (uint32_t i = 0; i < nowners_; i++)
                if (storage_->remaining[i]) std::abort();
            clear();
        }
    }

    void post_current(const Task& task, uint32_t worker) {
        if (!loop_ || reserved_current_worker_ != static_cast<int32_t>(worker))
            std::abort();
        loop_->srv_->thread(worker).post_task_reserved_quiet(
            loop_->self_->id(), task, loop_->self_->sig());
        consume(worker);
        loop_->touch_worker(worker);
        for (uint32_t i = 0; i < nowners_; i++)
            if (storage_->remaining[i]) std::abort();
        clear();
    }

private:
    void add_owner(uint32_t worker) {
        uint32_t at = 0;
        while (at != nowners_ && storage_->owners[at] != worker) at++;
        if (at == nowners_) {
            if (nowners_ == kMaxThreads) std::abort();
            storage_->owners[nowners_] = worker;
            storage_->remaining[nowners_] = 0;
            nowners_++;
        }
        storage_->remaining[at]++;
    }

    void consume(uint32_t worker) {
        uint32_t at = 0;
        while (at != nowners_ && storage_->owners[at] != worker) at++;
        if (at == nowners_ || !storage_->remaining[at]) std::abort();
        storage_->remaining[at]--;
    }

    void discard_prepared_reads() {
        if (!loop_ || !client_) return;
        Rob<kRobWindow>& rob = client_->rob();
        for (uint32_t i = 0; i < count_; i++) {
            Op& op = rob.at(storage_->ids[i]);
            if (storage_->scatter[i]) {
                xshard_abandon_unpublished(storage_->scatter[i], loop_->scatter_pool_,
                                           loop_->self_->id());
                storage_->scatter[i] = nullptr;
            }
            if (read_local_mget(op)) read_local_clear_reply(op);
        }
    }

    void cancel() {
        if (!loop_) return;
        if (reservations_live_)
            for (uint32_t i = 0; i < nowners_; i++)
                if (storage_->remaining[i])
                    loop_->srv_->thread(storage_->owners[i]).cancel_task_reservation(
                        loop_->self_->id(), storage_->remaining[i]);
        discard_prepared_reads();
        clear();
    }

    void clear() {
        loop_ = nullptr;
        client_ = nullptr;
        count_ = nowners_ = 0;
        partial_begin_ = partial_count_ = 0;
        reserved_current_worker_ = -1;
        reservations_live_ = false;
        partial_ = false;
        storage_.reset();
    }

    IoLoop* loop_ = nullptr;
    Client* client_ = nullptr;
    std::unique_ptr<Storage> storage_;
    uint32_t count_ = 0;
    uint32_t nowners_ = 0;
    uint32_t partial_begin_ = 0;
    uint32_t partial_count_ = 0;
    int32_t reserved_current_worker_ = -1;
    bool reservations_live_ = false;
    bool partial_ = false;
};

template <bool Fused>
uint32_t ExLoopT<Fused>::r7_fused_baseline_pass() {
    TOMO_R7_PATH();
    static_assert(Fused);
    if (srv_->thread_mode() == ThreadMode::Split) return split_read_local_pass();
    if (read_local_enabled())
        return r7_fused_pass_impl<kGenthreadExBatchOps, true, false, false, true>();
    return r7_fused_pass_impl<kGenthreadExBatchOps, true, false>();
}

template <bool Fused>
template <uint32_t BatchOps, bool ConsumeTasks, bool CoalesceSubmit,
          bool IofusedPrivateQueue, bool InterleaveLocalReads,
          typename Filler>
uint32_t ExLoopT<Fused>::r7_fused_pass_impl(Filler* filler) {
    TOMO_R7_PATH();
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
                        did += r7_drain_tasks_with_filler<BatchOps, IofusedPrivateQueue>(
                            true, *filler, filler_used);
                    else
                        did += r7_drain_tasks<BatchOps, IofusedPrivateQueue>(true);
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
                            did += r7_drain_tasks_with_filler<BatchOps, IofusedPrivateQueue>(
                                false, *filler, filler_used);
                        else {
                            if (fairlane_turn)
                                did += drain_tasks_read_local_interleaved<
                                    IofusedPrivateQueue>(false, owner_work_remains);
                            else
                                did += r7_drain_tasks<BatchOps, IofusedPrivateQueue>();
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
            ? r7_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue, true>()
            : r7_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
    } else {
        did = r7_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
    }
    if (did) fused_submit_boundary<CoalesceSubmit>();
    return did;
}

template <bool Fused>
uint32_t ExLoopT<Fused>::r7_fused_baseline_sweep() {
    TOMO_R7_PATH();
    static_assert(Fused);
    if (srv_->thread_mode() == ThreadMode::Split) return split_read_local_pass();
    if (read_local_enabled())
        return r7_fused_sweep_impl<kGenthreadExBatchOps, true, false, false, true>();
    return r7_fused_sweep_impl<kGenthreadExBatchOps, true, false>();
}

template <bool Fused>
template <uint32_t BatchOps, bool ConsumeTasks, bool CoalesceSubmit,
          bool IofusedPrivateQueue, bool InterleaveLocalReads>
uint32_t ExLoopT<Fused>::r7_fused_sweep_impl() {
    TOMO_R7_PATH();
    if (lb_controller_armed_ && srv_->lb_dispatch_paused())
        return r7_fused_pass_impl<BatchOps, ConsumeTasks, CoalesceSubmit,
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
                r7_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
        } else {
            compact_local_read_tombstones();
            if (read_local_impl().lane_count) {
                did += drain_local_reads_bounded(kReadLocalDrainChunkOps);
                did += r7_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue, true>();
            } else {
                did += r7_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
            }
        }
    } else {
        did += drain_local_reads() +
            r7_sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
    }
    if (read_local_enabled()) did += read_local_impl().deferred.drain_ready();
    if (did) fused_submit_boundary<CoalesceSubmit>();
    return did;
}

template <bool Fused>
template <uint32_t BatchOps, bool ConsumeTasks,
          bool IofusedPrivateQueue, bool InterleaveLocalReads>
uint32_t ExLoopT<Fused>::r7_sweep() {
    TOMO_R7_PATH();
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
                        n += drain_tasks_read_local_interleaved<IofusedPrivateQueue>(
                            true, owner_work_remains);
                    else
                        n += r7_drain_tasks<BatchOps, IofusedPrivateQueue>(true);
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

template <bool HasUnix, bool HasTls, bool kEp, bool Fused,
          uint8_t Pipeline, bool SplitLocal>
void IoLoop::r7_run_loop() {
    TOMO_R7_PATH();
    static_assert(Pipeline <= 1);
    // O1's 1s on/off arms instantiate the same baseline loop and producer transport.
    static_assert(!Fused || SplitLocal || Pipeline == 0);
    static_assert(!SplitLocal || Fused);
    LoopSignals& sig = self_->sig();
    IoTenure tenure(sig);
    // Bind once at armed fused IO role entry.
    if constexpr (Fused) if (srv_->read_local_enabled() && r7::shadow_available())
        fused_executor_->bind_read_local_demotion(this,
            [](void* p, Client* client, const uint64_t* probed,
               const ReadLocalFallbackReason* fallbacks, uint32_t count, uint32_t& demoted) {
                return static_cast<IoLoop*>(p)->r7_fused_demote_local_read_batch(
                    client, probed, fallbacks, count, demoted);
            });

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
    // The disarmed specialization is empty. No depth history or cursor is allocated or
    // initialized by overlap 0, including when an EX thread activates an IO role after FLIP.
    [[maybe_unused]] IoPipeLoopState<IoPipe> pipe;
    if constexpr (IoPipe) pipe.depth.reset(sig.ops);
    while (!self_->stop_flag().load(std::memory_order_relaxed) &&
           self_->role() == Role::Ifid) {
        const uint64_t pass_ns = tenure.pass();
        Server::DatabaseWorkScope database_work(*srv_, self_->id());
#ifdef TOMO_MDBQSBR_TEST
        if (DatabaseMapTestHooks::loop_pass) {
            DatabaseMapTestHooks::loop_pass(*srv_, *self_, 1);
            continue;
        }
#endif
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
            natural_order = pipe.depth.loop_boundary(sig.ops);
        {
            // The pass-boundary clock is already sampled. Reuse that same cut for
            // every monotonic millisecond consumer instead of issuing separate clock_gettime
            // reads for pause, cron and WAIT. A pass is microseconds; their public granularity
            // is milliseconds or seconds.
            bool pass_time_cached = pause_armed || client_cron_armed || save_cron_armed ||
                                    client_lb_signal_armed || lb_controller_armed ||
                                    !deferred_timers_.empty();
            if (__builtin_expect(pass_time_cached, true)) {
                cached_now_ms_ = pass_ns / 1000000ull;
                cached_now_s_ = static_cast<uint32_t>(cached_now_ms_ / 1000);
            }
            if (__builtin_expect(pause_armed &&
                                 cached_now_ms_ >= climon_pause_deadline_ms_, false))
                climon_release_pause();
            if (client_cron_newly_armed) {
                for (Client* c : self_->clients()) c->set_last_interaction_s(cached_now_s_);
                client_cron_beat_ms_ = cached_now_ms_;
            }
            if (self_->sample_depth(pass_ns / 1000)) {
                // CLOCK_THREAD_CPUTIME_ID can require a real syscall. cpu_ns is diagnostic
                // only (model demand uses wall-idle; physical placement uses busy/idle), so sample it
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
                        r7_on_cqe<HasTls, kEp, Fused, Pipeline>(cqe);
                    });
                if constexpr (kEp)
                    did += r7_epoll_pass<HasUnix, HasTls, Fused, Pipeline>(0);
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
                    cached_now_ms_ = pass_ns / 1000000ull;
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
                    false, natural_order, submitted, pipe.cursor);
            } else if constexpr (Fused) {
                if (__builtin_expect(!routing_forward_.empty(), false))
                    client_routing_cleanup_pass();
                did += r7_flush_ready<HasTls, kEp, true, HasUnix, false, SplitLocal>();
            } else {
                did += collect_retire_work<HasUnix, kEp>();
                if (__builtin_expect(!routing_forward_.empty(), false))
                    client_routing_cleanup_pass();
                did += r7_flush_ready<HasTls, kEp>();
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
                if (!submitted || ring_.sq_ready()) {
                    ring_.submit_and_reap();
#ifdef TOMO_SIGNALACCT_WITNESS
                    tenure.did_submit();
#endif
                }
            } else {
                ring_.submit_and_reap();
#ifdef TOMO_SIGNALACCT_WITNESS
                tenure.did_submit();
#endif
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
                natural_order, submitted, pipe.cursor);
        else
            sweep_work = r7_sweep<HasUnix, HasTls, kEp, Fused, SplitLocal>();
        if (sweep_work) {
            if constexpr (IoPipe) {
                if (!submitted || ring_.sq_ready()) {
                    ring_.submit_and_reap();
#ifdef TOMO_SIGNALACCT_WITNESS
                    tenure.sweep_submit();
#endif
                }
            } else {
                ring_.submit_and_reap();
#ifdef TOMO_SIGNALACCT_WITNESS
                tenure.sweep_submit();
#endif
            }
            continue;
        }

        // Preserve the established classification: publication, inbound recheck,
        // epoll callbacks, the wait and resume/clear are ALL inside this idle span.
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
                if (!self_->any_fused_inbound()) {
#ifdef TOMO_SIGNALACCT_WITNESS
                    tenure.park();
#endif
                    r7_epoll_pass<HasUnix, HasTls, !SplitLocal, Pipeline>(50);
                }
            } else if (!self_->any_io_inbound()) {
#ifdef TOMO_SIGNALACCT_WITNESS
                tenure.park();
#endif
                r7_epoll_pass<HasUnix, HasTls, false, Pipeline>(50);
            }
        } else {
            if constexpr (Fused) {
                if (!self_->any_fused_inbound()) {
#ifdef TOMO_SIGNALACCT_WITNESS
                    tenure.park();
#endif
                    ring_.submit_and_wait(1);
                } else                            ring_.submit_and_reap();
            } else {
                if (!self_->any_io_inbound()) {
#ifdef TOMO_SIGNALACCT_WITNESS
                    tenure.park();
#endif
                    ring_.submit_and_wait(1);
                } else                         ring_.submit_and_reap();
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
    const auto io_tenure = tenure.finish(self_->role() != Role::Ifid,
        self_->stop_flag().load(std::memory_order_relaxed));
    if constexpr (Fused) {
        // The read loop is over for this tenure. Teardown may take longer than another
        // owner's bounded retire queue can tolerate, but it performs no foreign store probe.
        if (srv_->read_local_enabled()) {
            self_->set_read_local_lane_active(false);
            self_->publish_read_local_parked(srv_->read_local_epoch());
        }
    }
    // Append after the read-local park: diagnostic allocation must not pin QSBR.
    srv_->record_io_tenure(self_->id(), io_tenure);
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

template <bool HasUnix, bool HasTls, bool kEp, bool Fused, bool SplitLocal>
uint32_t IoLoop::r7_sweep() {
    TOMO_R7_PATH();
    uint32_t work = 0;
    if constexpr (HasUnix) work += flush_handoffs();
    if constexpr (Fused) {
        work += service_client_migrations<kEp>() + drain_client_transfers<kEp>(true) +
                flush_borrow_releases() +
                r7_flush_ready<HasTls, kEp, true, HasUnix, true, SplitLocal>();
    } else {
        work += service_client_migrations<kEp>() + drain_client_transfers<kEp>(true) +
                flush_borrow_releases() + collect_retire_work<HasUnix, kEp>(true) +
                r7_flush_ready<HasTls, kEp>();
    }
    if (__builtin_expect(!routing_forward_.empty(), false))
        client_routing_cleanup_pass();
    if (srv_->snapshot().writer_is(self_->id()))
        work += srv_->snapshot().writer_pass(*self_, ring_, true);
    if (srv_->aof().writer_is(self_->id()))
        work += srv_->aof().writer_pass(*self_, ring_, true);
    return work;
}

template <bool HasTls, bool kEp, bool Fused, bool HasUnix,
          bool SweepPass, bool SplitLocal>
uint32_t IoLoop::r7_flush_ready() {
    TOMO_R7_PATH();
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
                if (!c->closing() && !c->recv_armed()) (void)r7_drive_tls<kEp, Fused>(c);
                else if (tls->userspace()) {
                    (void)wb_.pump_tls<kEp>(*c, *tls);
                    if (tls->socket_userspace() && tls->has_pinned_plain())
                        arm_tls_socket_poll<kEp>(c, tls->wanted());
                }
                // A successful fd handshake can switch transport under r7_drive_tls().
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
        if (c->flip_backpressure() && (!srv_->flip_dispatch_paused() ||
            (!kSingleDatabase && multidb_dispatch_allowed(*srv_, *c))))
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
                    if (tls) r7_arm_tls_recv<kEp, Fused>(c);
                    else arm_recv<kEp>(c);
                } else {
                    arm_recv<kEp>(c);
                }
                if constexpr (HasTls) if (tls) {
                    (void)r7_drive_tls<kEp, Fused>(c);
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
                        dispatch_result = r7_parse_and_dispatch<
                            true, Fused ? kGenthreadIfidBatchOps : 0>(c);
                    else
                        dispatch_result = r7_parse_and_dispatch<
                            false, Fused ? kGenthreadIfidBatchOps : 0>(c);
                } else {
                    dispatch_result = r7_parse_and_dispatch<
                        false, Fused ? kGenthreadIfidBatchOps : 0>(c);
                }
                if (conn.rpos() != rpos_before) work++;
            } else {
                if constexpr (HasTls) {
                    if (c->is_tls())
                        dispatch_result = r7_parse_and_dispatch<
                            true, Fused ? kGenthreadIfidBatchOps : 0>(c);
                    else
                        dispatch_result = r7_parse_and_dispatch<
                            false, Fused ? kGenthreadIfidBatchOps : 0>(c);
                } else {
                    dispatch_result = r7_parse_and_dispatch<
                        false, Fused ? kGenthreadIfidBatchOps : 0>(c);
                }
                if (__builtin_expect(
                        dispatch_result != DispatchResult::NeedInput, true))
                    work++;
            }
        }

        if constexpr (!kEp) {
            if constexpr (HasTls) {
                if (tls && tls->memory_bio()) r7_arm_tls_recv<kEp, Fused>(c);
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
            // Both teardown fences need other workers to finish their current passes.
            // Defer in place: close_client's erase+reinsert retry would revisit this client
            // forever while this pass holds its own DatabaseWorkScope/ClientWorkScope,
            // so two closing IOs could each prevent the other's captured epoch from ending.
            if (!pubsub_disconnect_ready(c) || !client_executor_quiesced(c)) { idx++; }
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
        work += SweepPass ? fused_executor_->r7_fused_baseline_sweep()
                          : fused_executor_->r7_fused_baseline_pass();
        work += collect_retire_work<HasUnix, kEp>(SweepPass);
    }

    // PUB/SUB PASS BOUNDARY -- between parsing and serving, on purpose. Everything this pass
    // parsed is resolved and appended to its subscribers' buffers HERE, so PHASE 2 sends one
    // coalesced write per subscriber instead of one per message. Off/unarmed servers pay one
    // predicted branch on a bool; all the machinery is out-of-line and cold.
    if (__builtin_expect(pubsub_pass_pending_, false)) work += pubsub_pass_flush();

    // PHASE 2 -- both modes visit the captured FIFO once under the composite rule.
    if (!pending_serve_.empty()) {
        AofManager& aof = srv_->aof();
        if (__builtin_expect(aof.configured(), false)) {
            if (!aof_gate_target_) aof_gate_target_ = aof.posted_sequence();
            if (!aof.reply_gate_ready(aof_gate_target_)) {
                aof.register_send_gate_wait(self_->id());
                return work;
            }
        }
        aof_gate_target_ = 0;
    } else {
        aof_gate_target_ = 0;
    }
    return work + wb_rule::Phase2::serve<HasTls, kEp, IoLoop, Fused>(*this);
}

template <bool kEp, bool Fused, uint8_t Pipeline>
void IoLoop::r7_admit_fd(int fd, UrKind kind) {
    TOMO_R7_PATH();
    if (accepts_paused()) { ::close(fd); return; }
    const bool unix_socket = kind == UrKind::UnixAccept;
    const bool tls_socket = kind == UrKind::TlsAccept;
    self_->sig().accepts++;
    if (tls_socket) self_->sig().tls_accepts++;
    else self_->sig().plain_accepts++;
    if (srv_->live_clients() >= srv_->maxclients()) {
        static constexpr char kErr[] = "-ERR max number of clients reached\r\n";
        if (!tls_socket) {
            const ssize_t sent = ::send(fd, kErr, sizeof(kErr) - 1,
                                        MSG_NOSIGNAL | MSG_DONTWAIT);
            if (sent > 0) self_->sig().net_output_bytes += static_cast<uint64_t>(sent);
        }
        ::close(fd);
        srv_->note_rejected_conn();
        return;
    }
    if (__builtin_expect(srv_->protected_mode() && !srv_->requirepass_enabled() &&
                         !peer_is_local(fd, unix_socket), false)) {
        static constexpr char kDenied[] =
            "-DENIED Redis is running in protected mode because protected mode is enabled and no password is set for the default user. In this mode connections are only accepted from the loopback interface. If you want to connect from external computers to Redis you may adopt one of the following solutions: 1) Just disable protected mode sending the command 'CONFIG SET protected-mode no' from the loopback interface by connecting to Redis from the same host the server is running, however MAKE SURE Redis is not publicly accessible from internet if you do so. Use CONFIG REWRITE to make this change permanent. 2) Alternatively you can just disable the protected mode by editing the Redis configuration file, and setting the protected mode option to 'no', and then restarting the server. 3) If you started the server manually just for testing, restart it with the '--protected-mode no' option. 4) Set up an authentication password for the default user. NOTE: You only need to do one of the above things in order for the server to start accepting connections from the outside.\r\n";
        if (!tls_socket) {
            const ssize_t sent = ::send(fd, kDenied, sizeof(kDenied) - 1,
                                        MSG_NOSIGNAL | MSG_DONTWAIT);
            if (sent > 0) self_->sig().net_output_bytes += static_cast<uint64_t>(sent);
        }
        ::close(fd);
        srv_->note_rejected_connection();
        return;
    }
    auto* c = new (std::nothrow) Client(fd);
    if (!c) {
        ::close(fd);
        self_->sig().accept_err++;
        return;
    }
    // NOTHING READ-LOCAL IS ALLOCATED HERE ANY MORE. The RYOW write-ring
    // sidecar used to be built at accept for every connection on an armed boot, so a pure-read
    // or idle connection carried 1216 bytes (a 1280-byte jemalloc class) it could never use.
    // It is now built on the first write of a connection a local read has ARMED, from that
    // connection's own IO thread; an allocation failure there falls back to the unarmed
    // contract instead of rejecting a connection that is already established.
    if (tls_socket && !attach_tls(c)) {
        delete c;
        ::close(fd);
        self_->sig().accept_err++;
        return;
    }
    srv_->client_accepted();
    c->set_authenticated(!srv_->requirepass_enabled());
    c->set_acl_user_idx(kAclDefaultUser);
    c->set_id(srv_->next_client_id().fetch_add(1, std::memory_order_relaxed));
    if (unix_socket) {
        const auto& ios = srv_->placement().ifid_threads();
        const uint32_t target = ios[unix_rr_++ % ios.size()];
        c->set_ifid_thread(target);
        if (target == self_->id()) r7_adopt_client<kEp, Fused, Pipeline>(c, true);
        else if (!srv_->thread(target).post_client(self_->id(), c, ring_, self_->sig()))
            pending_handoffs_.push_back(c);
    } else {
        c->set_ifid_thread(self_->id());
        r7_adopt_client<kEp, Fused, Pipeline>(c, false, tls_socket);
    }
}

template <bool kEp, bool Fused, uint8_t Pipeline>
void IoLoop::r7_adopt_client(Client* c, bool unix_socket, bool tls_socket) {
    TOMO_R7_PATH();
    // ARMED ONCE FOR THIS OWNERSHIP TENURE. Both directions are edge triggered. Normal teardown
    // still lets ::close() deregister; migration alone pre-registers destination + rollback
    // interests and removes the old tenure's original registration around the owner edge.
    // Registration belongs here rather than at accept because an AF_UNIX connection can be
    // accepted by one IO thread and owned by another.
    if constexpr (kEp) {
        if (!set_nonblocking(c->fd()) ||
            !ep_.add(c->fd(), EPOLLIN | EPOLLOUT | EPOLLRDHUP | EPOLLET,
                     ur_tag(UrKind::Recv, c))) {
            std::fprintf(stderr, "epoll registration failed for client fd %d\n", c->fd());
            self_->sig().accept_err++;
            self_->add_client(c);
            c->set_wb_slot(self_->assign_wb_slot(c));
            close_client(c);
            return;
        }
    }
    if (!unix_socket) {
        int one = 1;
        setsockopt(c->fd(), IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));
        const uint32_t interval = srv_->tcp_keepalive();
        if (interval) {
            setsockopt(c->fd(), SOL_SOCKET, SO_KEEPALIVE, &one, sizeof(one));
            const int idle = static_cast<int>(interval);
            const int intvl = std::max(1, idle / 3);
            const int count = 3;
            setsockopt(c->fd(), IPPROTO_TCP, TCP_KEEPIDLE, &idle, sizeof(idle));
            setsockopt(c->fd(), IPPROTO_TCP, TCP_KEEPINTVL, &intvl, sizeof(intvl));
            setsockopt(c->fd(), IPPROTO_TCP, TCP_KEEPCNT, &count, sizeof(count));
        }
    }
    c->set_last_interaction_s(cached_now_s_ ? cached_now_s_
                                            : static_cast<uint32_t>(now_ns() / 1000000000ull));
    c->set_ifid_thread(self_->id());
    // The armed lane's cold counters belong to whichever thread owns the connection; this is
    // the one place ownership is taken (accept, AF_UNIX handoff, and migration rollback all
    // arrive here), and the migration edge re-points it for the destination.
    c->rob().set_read_local_arm_stats(self_->read_local_arm_stats_or_null());
    // The ready-mask slot is assigned immediately: WE are the sender, for life.
    c->set_wb_slot(self_->assign_wb_slot(c));
    self_->add_client(c);
    const std::string addr = socket_address(c->fd(), unix_socket, true);
    const std::string laddr = socket_address(c->fd(), unix_socket, false);
    const uint64_t accepted_ms = cached_now_ms_ ? cached_now_ms_ : now_ns() / 1000000ull;
    command_client_connected(c, addr.c_str(), laddr.c_str(), unix_socket, accepted_ms);
    climon_track_client(c);
    if (tls_socket) {
        TlsConn* tls = tls_slot_conn(c);
        if (tls && tls->fd_handshake()) {
            (void)r7_drive_tls<kEp, Fused, Pipeline>(c);
            if (!c->closing() && tls->ktls()) arm_recv<kEp>(c);
            else if (!c->closing() && tls->memory_userspace())
                r7_arm_tls_recv<kEp, Fused, Pipeline>(c);
        } else {
            r7_arm_tls_recv<kEp, Fused, Pipeline>(c);
        }
    } else arm_recv<kEp>(c);
    // Reachability, not optimism: if that arm starved for an SQE, nothing else names this
    // conn -- it would sit accepted and silent forever (audit finding). The active set's
    // phase-1 re-arms it until the recv lands; one wasted visit if the arm succeeded.
    mark_active_known<Fused && Pipeline != 0>(c);
}

template <bool kEp, bool Fused, uint8_t Pipeline>
void IoLoop::r7_arm_tls_recv(Client* c) {
    TOMO_R7_PATH();
    if (c->recv_armed() || c->closing()) return;
    TlsConn* tls = tls_engine(c);
    if (!tls || !tls->memory_bio()) return;
    // Any engine output is submitted before another socket read. This is the memory-BIO
    // flush-before-read rule that prevents WANT_READ from hiding a required write.
    if (tls->output_pending()) {
        (void)wb_.pump_tls<kEp, Fused && Pipeline == 1>(*c, *tls);
        if (tls->output_pending()) return;
    }
    // Ciphertext or decrypted plaintext already inside the engine must be drained before a
    // new zero-copy BIO reservation is pinned. Otherwise a ROB-full pipeline can arm an empty
    // socket recv while its next complete command is already waiting in OpenSSL, deadlocking
    // a request/response client until it happens to send unrelated bytes.
    if (tls->input_pending()) return;
    char* dst = nullptr;
    const int avail = tls->reserve_input(dst, kRecvChunk);
    if (avail <= 0) return;
    if constexpr (kEp) {
        const ssize_t n = ::recv(c->fd(), dst, static_cast<size_t>(avail), MSG_DONTWAIT);
        if (n > 0) {
            self_->sig().epoll_recvs++;
            r7_on_tls_recv<kEp, Fused, Pipeline>(c, static_cast<int>(n));
            return;
        }
        tls->abandon_input();
        if (n == 0) { epoll_request_close(c); return; }
        if (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) {
            c->set_recv_armed(true);
            return;
        }
        epoll_request_close(c);
        return;
    } else {
        io_uring_sqe* s = ring_.sqe();
        if (!s) {
            tls->abandon_input();
            self_->sig().sqe_starved++;
            return;
        }
        io_uring_prep_recv(s, c->fd(), dst, static_cast<unsigned>(avail), 0);
        s->user_data = ur_tag(UrKind::TlsRecv, c);
        ring_.note_pending();
        c->set_recv_armed(true);
    }
}

template <bool kEp, bool Fused, uint8_t Pipeline>
bool IoLoop::r7_drive_tls(Client* c) {
    TOMO_R7_PATH();
    TlsConn* tls = tls_slot_conn(c);
    if (!tls) return false;
    if (tls->ktls()) return true;

    if (tls->handshaking() && tls->fd_handshake()) {
        const TlsOp result = tls->handshake();
        if (result == TlsOp::WantRead || result == TlsOp::WantWrite) {
            if (result == TlsOp::WantRead) self_->sig().tls_want_read++;
            else self_->sig().tls_want_write++;
            arm_tls_socket_poll<kEp>(c, result);
            return true;
        }
        if (result == TlsOp::Progress) {
            self_->sig().tls_handshakes_completed++;
            if (tls->ktls()) self_->sig().tls_ktls_active++;
            else self_->sig().tls_ktls_fallback++;
        } else {
            self_->sig().tls_handshakes_failed++;
            if (!tls->last_error().empty())
                std::fprintf(stderr, "TLS client %llu: %s\n",
                             static_cast<unsigned long long>(c->id()),
                             tls->last_error().c_str());
            close_client(c);
            return false;
        }
        if (tls->ktls()) return true;
    }

    if (tls->socket_userspace() && tls->has_pinned_plain()) {
        (void)wb_.pump_tls<kEp, Fused && Pipeline == 1>(*c, *tls);
        if (tls->has_pinned_plain()) {
            arm_tls_socket_poll<kEp>(c, tls->wanted());
            return true;
        }
    }

    if (tls->output_pending() || c->send_inflight()) {
        (void)wb_.pump_tls<kEp, Fused && Pipeline == 1>(*c, *tls);
        return !tls->failed();
    }

    if (tls->handshaking()) {
        const TlsOp result = tls->handshake();
        if (result == TlsOp::WantRead) self_->sig().tls_want_read++;
        else if (result == TlsOp::WantWrite) self_->sig().tls_want_write++;
        else if (result == TlsOp::Progress) {
            self_->sig().tls_handshakes_completed++;
            self_->sig().tls_ktls_fallback++;
        }
        (void)wb_.pump_tls<kEp, Fused && Pipeline == 1>(
            *c, *tls);  // alerts and handshake flights are flushed first
        if (result == TlsOp::Error || result == TlsOp::GracefulEof) {
            self_->sig().tls_handshakes_failed++;
            if (!tls->last_error().empty())
                std::fprintf(stderr, "TLS client %llu: %s\n",
                             static_cast<unsigned long long>(c->id()),
                             tls->last_error().c_str());
            close_client(c, tls->output_pending() || c->send_inflight());
            return false;
        }
        if (!tls->connected() || tls->output_pending() || c->send_inflight()) return true;
    }

    [[maybe_unused]] bool decrypted = false;
    while (tls->connected()) {
        size_t avail = 0;
        bool may_grow = c->rob().quiesced();
        char* dst = c->read_space(
            kRecvChunk, avail, may_grow, proto_max_bulk_len_);
        if (!dst) break;
        const TlsIoResult result = tls->read_plain(dst, avail);
        if (result.op == TlsOp::Progress) {
            // Only decrypted bytes enter the RESP buffer. Ciphertext counts are committed to
            // the BIO in on_tls_recv and can never reach this cursor.
            c->commit_read(result.bytes);
            self_->sig().tls_plaintext_input_bytes += result.bytes;
            decrypted = true;
            if (tls->output_pending()) {
                (void)wb_.pump_tls<kEp, Fused && Pipeline == 1>(*c, *tls);
                break;
            }
            continue;
        }
        if (result.op == TlsOp::WantRead) {
            self_->sig().tls_want_read++;
            if (tls->socket_userspace()) arm_tls_socket_poll<kEp>(c, result.op);
        }
        else if (result.op == TlsOp::WantWrite) {
            self_->sig().tls_want_write++;
            if (tls->socket_userspace()) arm_tls_socket_poll<kEp>(c, result.op);
            else (void)wb_.pump_tls<kEp, Fused && Pipeline == 1>(*c, *tls);
        } else if (result.op == TlsOp::GracefulEof) {
            (void)tls->shutdown();
            (void)wb_.pump_tls<kEp, Fused && Pipeline == 1>(*c, *tls);
            close_client(c, tls->output_pending() || c->send_inflight());
            return false;
        } else {
            if (!tls->last_error().empty())
                std::fprintf(stderr, "TLS client %llu: %s\n",
                             static_cast<unsigned long long>(c->id()),
                             tls->last_error().c_str());
            (void)wb_.pump_tls<kEp, Fused && Pipeline == 1>(*c, *tls);
            close_client(c, tls->output_pending() || c->send_inflight());
            return false;
        }
        break;
    }
    if constexpr (Pipeline == 0) {
        if (decrypted || c->rpos() < c->rlen())
            r7_parse_and_dispatch<true, Fused ? kGenthreadIfidBatchOps : 0>(c);
    }
    return !tls->failed();
}

template <bool kEp, bool Fused, uint8_t Pipeline>
uint32_t IoLoop::r7_epoll_accept(UrKind kind) {
    TOMO_R7_PATH();
    if (accepts_paused()) return 0;
    const int listener = kind == UrKind::UnixAccept ? unix_listen_fd_ :
                         kind == UrKind::TlsAccept ? tls_listen_fd_ : listen_fd_;
    if (listener < 0) return 0;
    uint32_t taken = 0;
    for (;;) {
        const int fd = ::accept4(listener, nullptr, nullptr, SOCK_NONBLOCK | SOCK_CLOEXEC);
        if (fd < 0) {
            if (errno == EINTR) continue;
            if (errno != EAGAIN && errno != EWOULDBLOCK) self_->sig().accept_err++;
            return taken;
        }
        taken++;
        r7_admit_fd<kEp, Fused, Pipeline>(fd, kind);
    }
}

template <bool HasUnix, bool HasTls, bool Fused, uint8_t Pipeline>
uint32_t IoLoop::r7_epoll_pass(int timeout_ms) {
    TOMO_R7_PATH();
    const int n = ep_.wait(timeout_ms);
    if (n <= 0) return 0;
    self_->sig().epoll_events += static_cast<uint64_t>(n);
    uint32_t work = 0;
    for (int i = 0; i < n; i++) {
        const epoll_event& ev = ep_.event(i);
        switch (ur_kind(ev.data.u64)) {
            case UrKind::Accept:
                work += r7_epoll_accept<true, Fused, Pipeline>(UrKind::Accept); break;
            case UrKind::TlsAccept:
                if constexpr (HasTls)
                    work += r7_epoll_accept<true, Fused, Pipeline>(UrKind::TlsAccept);
                break;
            case UrKind::UnixAccept:
                if constexpr (HasUnix)
                    work += r7_epoll_accept<true, Fused, Pipeline>(UrKind::UnixAccept);
                break;
            case UrKind::Wake:
                // The doorbell. Draining it here rather than at the park keeps the level-
                // triggered registration from re-reporting the same wake every pass.
                //
                // work++ IS LOAD-BEARING, and it is not accounting. The bell and its payload
                // are separate: a peer pushes its tag into the mailbox and THEN writes the
                // eventfd, and the mailbox is drained by ring_.for_each_cqe() one step earlier
                // in this pass. A peer that lands in the window between those two steps leaves
                // us holding a rung bell with its payload still queued -- and if this pass then
                // reported no work, the loop would park and the payload would wait out the
                // whole 50 ms ceiling. Counting the bell as work sends the loop round again,
                // where for_each_cqe picks the tag up immediately. Exactly the shape of the
                // ~3.9 ms-per-operation reading DEFER_TASKRUN once produced on the other engine.
                ring_.drain_wake_fd();
                self_->sig().wakes_recv++;
                work++;
                break;
            case UrKind::DatabaseWake:
                srv_->databases().consume_wake(self_->id(), ring_);
                work++;
                break;
            case UrKind::Shutdown:
                // Sticky and shared: never drain it, or this loop could steal the terminal
                // edge from another ring/epoll set. The signal handler published stop first.
                work++;
                break;
            case UrKind::Recv: {
                Client* c = ur_ptr<Client>(ev.data.u64);
                // During FLIP preflight the fd may already be registered here while source
                // ownership is still live. Do not touch even a flag until the owner edge.
                if (!c || c->ifid_thread() != self_->id() || c->dead() ||
                    c->wb_slot() == Client::kWbMigrationInstalling ||
                    find_client_migration(c)) break;
                // EPOLLERR/EPOLLHUP are folded into the read side on purpose: the recv that
                // follows returns 0 or the real errno, and close_client is then reached through
                // the one path that already knows how to tear a connection down.
                if (ev.events & (EPOLLIN | EPOLLERR | EPOLLHUP | EPOLLRDHUP))
                    c->set_recv_armed(false);
                if (ev.events & (EPOLLOUT | EPOLLERR | EPOLLHUP)) enqueue_serve(c);
                // A TLS connection parked on WANT_READ/WANT_WRITE recorded that want on its
                // TlsConn (arm_tls_socket_poll has nothing to submit under this engine, since
                // both directions are already armed). This edge is the answer to whichever want
                // is outstanding, so retire BOTH and let drive_tls re-record what it still
                // needs -- the same converge-by-retry the poll CQE gives the uring engine. A
                // want left recorded would make arm_tls_socket_poll a no-op forever and park
                // the handshake.
                if constexpr (HasTls) {
                    if (TlsConn* tls = tls_slot_conn(c)) {
                        tls->set_poll_armed(TlsOp::WantRead, false);
                        tls->set_poll_armed(TlsOp::WantWrite, false);
                        c->set_recv_armed(false);
                    }
                }
                mark_active_known<Fused && Pipeline != 0>(c);
                work++;
                break;
            }
            default: break;
        }
    }
    return work;
}

template <bool HasTls, bool kEp, bool SplitLocal>
uint32_t IoLoop::r7_ifid_parse_hash(IfidBatch& batch) {
    TOMO_R7_PATH();
    uint32_t work = 0;
    backstop_pass_ = (++flush_tick_ >= kIoPipeWbBackstopTurns);
    if (backstop_pass_) flush_tick_ = 0;

    // The read side is one bounded batch before this rotation's retirement/send. Arming first
    // keeps the arrival stream flowing independently of the reply backlog.
    for (uint32_t batch_index = 0; batch_index < batch.count; batch_index++) {
        Client* c = batch.clients[batch_index];
        if (c->dead() || !c->in_active()) continue;
        Client& conn = *c;
        DispatchResult dispatch_result = DispatchResult::Progress;
        TlsConn* tls = nullptr;
        if constexpr (HasTls) tls = tls_engine(c);
        if (backstop_pass_ && !c->serve_pending()) enqueue_serve(c);

        if constexpr (HasTls) {
            if (tls) {
                // Only the recv completion may drive inbound TLS while its BIO input frontier
                // is pinned. Pipeline callbacks decrypt but defer parsing to this stage.
                if (!c->closing() && !c->recv_armed())
                    (void)r7_drive_tls<kEp, false, 1>(c);
                else if (tls->userspace()) {
                    (void)wb_.pump_tls<kEp>(*c, *tls);
                    if (tls->socket_userspace() && tls->has_pinned_plain())
                        arm_tls_socket_poll<kEp>(c, tls->wanted());
                }
                tls = tls_engine(c);
                if constexpr (kEp)
                    if (wb_.take_send_failure()) epoll_request_close(c);
            }
        }

        if (c->scatter_barrier()) {
            if (c->blocked() &&
                blocking_resume_move(*srv_, *self_, ring_, *c, scatter_pool_)) {
                enqueue_serve(c);
                work++;
            }
            if (__builtin_expect(c->barrier_held_by(BarrierOwner::Debug), false) &&
                !srv_->debug_barrier_hold_armed())
                c->barrier_release(BarrierOwner::Debug);
            if (c->rob().quiesced()) c->barrier_release_quiesced();
        }
        if (c->atomic_backpressure() && srv_->atomic_can_admit(self_->id()) &&
            scatter_pool_.can_register_snapshot())
            c->set_atomic_backpressure(false);
        if (c->flip_backpressure() && (!srv_->flip_dispatch_paused() ||
            (!kSingleDatabase && multidb_dispatch_allowed(*srv_, *c))))
            c->set_flip_backpressure(false);
        if (c->rob().quiesced() && (kEp || !conn.recv_armed()))
            conn.reset_rbuf_at_quiescence();

        if constexpr (kEp) {
            if (c->closing()) c->set_recv_armed(false);
            if (!c->closing()) {
                if constexpr (HasTls) {
                    if (tls) r7_arm_tls_recv<kEp, false, 1>(c);
                    else arm_recv<kEp>(c);
                } else {
                    arm_recv<kEp>(c);
                }
                if constexpr (HasTls) if (tls) {
                    (void)r7_drive_tls<kEp, false, 1>(c);
                    tls = tls_engine(c);
                }
                if (wb_.take_send_failure()) epoll_request_close(c);
            }
        }

        if (!c->closing() && conn.rpos() < conn.rlen() && !c->scatter_barrier() &&
            !c->parse_backpressure()) {
            // The pause accounting and transport choice are the ordinary diet-era parse path;
            // only deferred IFID.POST is schedule-specific. The ROB itself bounds parsing.
            if (__builtin_expect(climon_pause_armed(), false)) {
                const uint32_t rpos_before = conn.rpos();
                if constexpr (HasTls) {
                    if (c->is_tls())
                        dispatch_result = r7_parse_and_dispatch<true, 0, true, false, false, false, SplitLocal>(c);
                    else
                        dispatch_result = r7_parse_and_dispatch<false, 0, true, false, false, false, SplitLocal>(c);
                } else {
                    dispatch_result = r7_parse_and_dispatch<false, 0, true, false, false, false, SplitLocal>(c);
                }
                if (conn.rpos() != rpos_before) work++;
            } else {
                if constexpr (HasTls) {
                    if (c->is_tls())
                        dispatch_result = r7_parse_and_dispatch<true, 0, true, false, false, false, SplitLocal>(c);
                    else
                        dispatch_result = r7_parse_and_dispatch<false, 0, true, false, false, false, SplitLocal>(c);
                } else {
                    dispatch_result = r7_parse_and_dispatch<false, 0, true, false, false, false, SplitLocal>(c);
                }
                if (__builtin_expect(dispatch_result != DispatchResult::NeedInput, true))
                    work++;
            }
        }

        if constexpr (!kEp) {
            if constexpr (HasTls) {
                if (tls && tls->memory_bio()) r7_arm_tls_recv<kEp, false, 1>(c);
                else if (!tls) arm_recv<kEp>(c);
            } else {
                arm_recv<kEp>(c);
            }
        }

        const bool stuck = (conn.rpos() < conn.rlen() && c->rob().full()) ||
                           (!conn.recv_armed() && !c->closing());
        const bool more_input = conn.rpos() < conn.rlen() &&
                                dispatch_result != DispatchResult::NeedInput;
        const bool tls_output = tls && (tls->output_pending() || c->send_inflight());
        const bool done = c->rob().quiesced() && !more_input && !stuck &&
                          !c->serve_pending() && c->nothing_to_write() && !tls_output;
        // Batch entries remain readable through the existing corpse grace; membership is the
        // authoritative check before mutating the active set.
        if (c->dead() || !c->in_active()) continue;
        if (done && !c->closing()) {
            c->set_in_active(false);
            active_.erase(c);
        } else if (c->closing() && !tls_output && c->safe_to_release()) {
            if (pubsub_disconnect_ready(c)) {
                c->set_in_active(false);
                active_.erase(c);
                close_client(c);
            }
        }
    }

    if constexpr (kEp) {
        while (!epoll_closes_.empty()) {
            Client* victim = epoll_closes_.back();
            epoll_closes_.pop_back();
            epoll_close_now(victim);
        }
    }
    // The IO role drains only its local-read lane. All writes and demotions still use
    // the ordinary split owner inbox; publish QSBR only after every capture is consumed.
    if constexpr (SplitLocal) work += fused_executor_->split_read_local_pass();
    return work;
}

template <bool HasUnix, bool HasTls, bool kEp>
uint32_t IoLoop::r7_ifid_rx(IfidBatch& batch, size_t& cursor) {
    TOMO_R7_PATH();
    uint32_t work = ring_.for_each_cqe(
        [&](io_uring_cqe* cqe) { r7_on_cqe<HasTls, kEp, false, 1>(cqe); });
    if constexpr (kEp) work += r7_epoll_pass<HasUnix, HasTls, false, 1>(0);
    if (batch.count) std::abort();
    const size_t available = active_.size();
    if (!available) { cursor = 0; return work; }
    if (cursor >= available) cursor = 0;
    const size_t visits = std::min<size_t>(available, kIoPipeIfidBatchClients);
    for (size_t i = 0; i < visits; i++) {
        Client* client = active_.at(cursor);
        if (++cursor == available) cursor = 0;
        if (!client->dead()) batch.clients[batch.count++] = client;
    }
    return work;
}

template <bool kEp, bool Fused, uint8_t Pipeline>
void IoLoop::r7_on_accept(io_uring_cqe* cqe, UrKind kind) {
    TOMO_R7_PATH();
    const uint64_t generation = reinterpret_cast<uintptr_t>(ur_ptr<void>(cqe->user_data));
    if (generation != accept_generation_ || self_->role() != Role::Ifid) {
        if (cqe->res >= 0) ::close(cqe->res);
        if (!(cqe->flags & IORING_CQE_F_MORE)) accept_armed_ref(kind) = false;
        return;
    }
    if (cqe->res < 0) {
        // Do not swallow this silently: a failing accept with no trace is indistinguishable from
        // a hung server, which is exactly how the 1024-connection failure presented.
        self_->sig().accept_err++;
        rearm_accept(cqe, kind);
        return;
    }
    if (accepts_paused()) {
        ::close(cqe->res);
        rearm_accept(cqe, kind);
        return;
    }
    r7_admit_fd<kEp, Fused, Pipeline>(cqe->res, kind);
    rearm_accept(cqe, kind);
}

template <bool HasTls, bool kEp, bool Fused, uint8_t Pipeline>
void IoLoop::r7_on_cqe(io_uring_cqe* cqe) {
    TOMO_R7_PATH();
    constexpr bool ImmediateSendProgress = !(Fused && Pipeline != 0);
    if constexpr (!HasTls) {
        // Keep the tls-port=0 completion dispatch byte-for-byte shaped like the base switch.
        switch (ur_kind(cqe->user_data)) {
            case UrKind::Accept:
                r7_on_accept<kEp, Fused, Pipeline>(cqe, UrKind::Accept); break;
            case UrKind::UnixAccept:
                r7_on_accept<kEp, Fused, Pipeline>(cqe, UrKind::UnixAccept); break;
            case UrKind::Recv:
                r7_on_recv<false, kEp, Fused, Pipeline>(
                    ur_ptr<Client>(cqe->user_data), cqe->res);
                break;
            case UrKind::Send:
                on_plain_send_cqe<kEp, ImmediateSendProgress,
                                  Fused && Pipeline == 1>(cqe); break;
            case UrKind::Wake: self_->sig().wakes_recv++; break;
            case UrKind::DatabaseWake:
                srv_->databases().consume_wake(self_->id(), ring_); break;
            case UrKind::Shutdown: break;
            case UrKind::SnapshotStart:
                if constexpr (Fused)
                    fused_executor_->fused_snapshot_start(
                        ur_ptr<SnapshotManager>(cqe->user_data));
                break;
            case UrKind::AofIo:
                srv_->aof().on_io_complete(*self_, ring_, ur_ptr<void>(cqe->user_data),
                                           cqe->res); break;
            case UrKind::SnapshotIo:
                srv_->snapshot().on_io_complete(*self_, ring_, ur_ptr<void>(cqe->user_data),
                                                cqe->res); break;
            case UrKind::Close: break;
            case UrKind::MigrateCancel: break;
            case UrKind::TlsReadPoll: break;
            case UrKind::TlsWritePoll: break;
            default: break;
        }
    } else {
        switch (ur_kind(cqe->user_data)) {
            case UrKind::Accept:
                r7_on_accept<kEp, Fused, Pipeline>(cqe, UrKind::Accept); break;
            case UrKind::TlsAccept:
                r7_on_accept<kEp, Fused, Pipeline>(cqe, UrKind::TlsAccept); break;
            case UrKind::UnixAccept:
                r7_on_accept<kEp, Fused, Pipeline>(cqe, UrKind::UnixAccept); break;
            case UrKind::Recv:
                r7_on_recv<true, kEp, Fused, Pipeline>(
                    ur_ptr<Client>(cqe->user_data), cqe->res);
                break;
            case UrKind::TlsRecv:
                r7_on_tls_recv<kEp, Fused, Pipeline>(
                    ur_ptr<Client>(cqe->user_data), cqe->res);
                break;
            case UrKind::Send:
                on_plain_send_cqe<kEp, ImmediateSendProgress,
                                  Fused && Pipeline == 1>(cqe); break;
            case UrKind::TlsSend:
                on_tls_send_cqe<kEp, ImmediateSendProgress,
                                Fused && Pipeline == 1>(cqe); break;
            case UrKind::TlsReadPoll:
                r7_on_tls_socket_poll<kEp, Fused, Pipeline>(
                    ur_ptr<Client>(cqe->user_data), cqe->res, TlsOp::WantRead); break;
            case UrKind::TlsWritePoll:
                r7_on_tls_socket_poll<kEp, Fused, Pipeline>(
                    ur_ptr<Client>(cqe->user_data), cqe->res, TlsOp::WantWrite); break;
            case UrKind::Wake: self_->sig().wakes_recv++; break;
            case UrKind::DatabaseWake:
                srv_->databases().consume_wake(self_->id(), ring_); break;
            case UrKind::Shutdown: break;
            case UrKind::SnapshotStart:
                if constexpr (Fused)
                    fused_executor_->fused_snapshot_start(
                        ur_ptr<SnapshotManager>(cqe->user_data));
                break;
            case UrKind::AofIo:
                srv_->aof().on_io_complete(*self_, ring_, ur_ptr<void>(cqe->user_data),
                                           cqe->res); break;
            case UrKind::SnapshotIo:
                srv_->snapshot().on_io_complete(*self_, ring_, ur_ptr<void>(cqe->user_data),
                                                cqe->res); break;
            case UrKind::Close: break;
            case UrKind::MigrateCancel: break;
        }
    }
}

template <bool HasTls, bool kEp, bool Fused, uint8_t Pipeline>
void IoLoop::r7_on_recv(Client* c, int res) {
    TOMO_R7_PATH();
    c->set_recv_armed(false);       // the kernel has released its pointer
    if (res > 0) self_->sig().net_input_bytes += static_cast<uint64_t>(res);
    if (find_client_migration(c)) {
        // The original Recv CQE, not the cancel CQE, is the old-ring pointer fence. Preserve
        // bytes which won the race with cancellation but do not parse them on the losing owner.
        if (res > 0) {
            c->commit_read(static_cast<size_t>(res));
            (void)finish_client_transfer<kEp>(c);
        } else if (res == -ECANCELED) {
            (void)finish_client_transfer<kEp>(c);
        } else {
            cancel_client_transfer<kEp>(c);
            close_client(c);
        }
        return;
    }
    // A send error can close the fd while this recv is still owned by io_uring. The Client stays
    // alive until this CQE arrives, but it is a corpse: positive bytes must not resurrect it by
    // parsing and dispatching new Tasks after the teardown quiescence fence.
    if (c->dead()) return;
    if (res <= 0) { close_client(c); return; }
    c->commit_read(static_cast<size_t>(res));
    c->set_last_interaction_s(cached_now_s_);
    if constexpr (Pipeline == 0) {
        if constexpr (HasTls) {
            if (c->is_tls())
                r7_parse_and_dispatch<true, Fused ? kGenthreadIfidBatchOps : 0>(c);
            else
                r7_parse_and_dispatch<false, Fused ? kGenthreadIfidBatchOps : 0>(c);
        } else {
            r7_parse_and_dispatch<false, Fused ? kGenthreadIfidBatchOps : 0>(c);
        }
    }
    // Deliberately NOT re-armed here. r7_flush_ready() re-arms AFTER it may have reset the read
    // buffer; arming first would leave the kernel holding a pointer that the reset then moves.
    mark_active_known<Fused && Pipeline != 0>(c);
}

template <bool kEp, bool Fused, uint8_t Pipeline>
void IoLoop::r7_on_tls_recv(Client* c, int res) {
    TOMO_R7_PATH();
    c->set_recv_armed(false);
    if (res > 0) self_->sig().net_input_bytes += static_cast<uint64_t>(res);
    TlsConn* tls = tls_engine(c);
    if (!tls) { close_client(c); return; }
    if (c->dead()) { tls->abandon_input(); return; }
    if (res <= 0) {
        tls->abandon_input();
        close_client(c);
        return;
    }
    if (!tls->commit_input(static_cast<size_t>(res))) {
        std::fprintf(stderr, "TLS client %llu: ciphertext BIO commit rejected %d bytes\n",
                     static_cast<unsigned long long>(c->id()), res);
        close_client(c);
        return;
    }
    self_->sig().tls_ciphertext_input_bytes += static_cast<uint64_t>(res);
    c->set_last_interaction_s(cached_now_s_);
    (void)r7_drive_tls<kEp, Fused, Pipeline>(c);
    mark_active_known<Fused && Pipeline != 0>(c);
}

template <bool kEp, bool Fused, uint8_t Pipeline>
void IoLoop::r7_on_tls_socket_poll(Client* c, int res, TlsOp wanted) {
    TOMO_R7_PATH();
    TlsConn* tls = tls_slot_conn(c);
    if (!tls) { close_client(c); return; }
    tls->set_poll_armed(wanted, false);
    c->set_recv_armed(tls->any_poll_armed());
    if (c->dead()) return;
    if (c->closing() || res < 0) { close_client(c); return; }
    (void)r7_drive_tls<kEp, Fused, Pipeline>(c);
    mark_active_known<Fused && Pipeline != 0>(c);
}

template <bool NoBorrow, uint32_t BatchOps, bool IoPipe,
          bool TargetedIfid,
          bool SuppressOrdinaryActiveMark,
          bool IofusedPrivateQueue, bool SplitLocal>
IoLoop::DispatchResult IoLoop::r7_parse_and_dispatch(Client* c) {
    // PAD A delegates to the inherited parser before any shadow scratch or scan.
    if (!r7::shadow_available())
        return parse_and_dispatch<NoBorrow, BatchOps, IoPipe, TargetedIfid,
            SuppressOrdinaryActiveMark, IofusedPrivateQueue, SplitLocal>(c);
    r7::ShadowDispatch shadow_dispatch(*c);

    TOMO_R7_PATH();
    // Split readers and fused overlap need the same ROB hazards, MGET fence,
    // admission, and demotion protocol as the baseline fused reader.
    static constexpr bool Fused = SplitLocal || IofusedPrivateQueue || (
        BatchOps == kGenthreadIfidBatchOps &&
        !IoPipe && !TargetedIfid && !SuppressOrdinaryActiveMark);
    [[maybe_unused]] const bool read_local_enabled =
        Fused && __builtin_expect(srv_->read_local_enabled(), false);
    Client& conn = *c;
    Rob<kRobWindow>& rob = c->rob();
    LoopSignals& sig = self_->sig();
    const uint32_t pass_rpos = conn.rpos();
    const char* const pass_rbuf = conn.rbuf();
    const uint32_t pass_rlen = conn.rlen();
    const uint32_t self_id = self_->id();
    auto task_free_slots = [&](ThreadCtx& owner) {
        if constexpr (IofusedPrivateQueue) {
            return owner.iofused_task_free_slots(self_id);
        } else {
            return owner.task_free_slots(self_id);
        }
    };
    auto post_task_quiet = [&](ThreadCtx& owner, const Task& task) {
        if constexpr (IofusedPrivateQueue) {
            return owner.post_iofused_task_quiet(self_id, task, sig);
        } else {
            return owner.post_task_quiet(self_id, task, sig);
        }
    };
    auto post_tasks_quiet = [&](ThreadCtx& owner, const Task* tasks, uint32_t count) {
        if constexpr (IofusedPrivateQueue) {
            return owner.post_iofused_tasks_quiet(self_id, tasks, count, sig);
        } else {
            return owner.post_tasks_quiet(self_id, tasks, count, sig);
        }
    };
    DispatchResult result = DispatchResult::Progress;
    bool head_candidate = true;   // only the pass's FIRST dispatch can be the direct head
    const uint8_t security_flags = srv_->security_flags();
    const bool auth_required = (security_flags & Server::kSecurityAuth) != 0;
    const bool acl_active = (security_flags & Server::kSecurityAcl) != 0;
    const bool notify_armed = notify_armed_;
    const uint64_t pass_max_bulk_len = proto_max_bulk_len_;
    const bool default_bulk_limit = pass_max_bulk_len == 512ull * 1024 * 1024;
    // IoDrain waits for this whole parse/post pass before opening ExDrain. A task whose
    // owner was sampled here therefore reaches that owner before it can acknowledge.
    const bool lb_pause_this_pass = lb_controller_armed_ &&
        srv_->lb_should_pause(self_id, c->id());
    if (__builtin_expect(lb_pause_this_pass, false)) {
#ifdef TOMO_LB_STALL_DEBUG
        srv_->lb_debug_park(self_id, pass_rlen - pass_rpos);
#endif
        flip_fingerprint_finish_pass();
        return result;
    }
    // ONE epoch for the whole parse pass, not one per op. Monotonicity needs the stamps to be
    // non-decreasing along the connection, not distinct: every op this pass parses may share
    // the pass's cut, and the next pass's cut is >= this one because the sequence only moves
    // forward. The freshness floor survives the fold -- the pass starts after the bytes it
    // parses arrived, so no read is ever older than its own arrival, which is what keeps the
    // disjoint-window case (a writer's reply fully precedes the reader's send) correct.
    // With --atomic 0 the tracking word is never written by anyone, so this is one L1 hit on a
    // shared-clean line, the sequence load never happens, and the per-op test is never taken.
    const bool atomic_tracking = srv_->atomic_tracking_active();
    const uint64_t pass_read_cut = atomic_tracking ? srv_->atomic_snapshot() : 0;
    uint64_t batch_start_ops = 0;
    [[maybe_unused]] bool read_local_batch = false;
    // LANE ADMISSION: how many lane slots (pending local reads) this connection may
    // hold during this pass. UINT32_MAX unless the thread's local-read lane is under pressure,
    // in which case it is the lane divided among the active connections
    // (ExLoop::read_local_lane_quota). The pressure byte is tested FIRST and on its own,
    // because active_.size() would otherwise be evaluated eagerly on every pass and active_
    // lives on an IoLoop cache line this pass never otherwise touches -- see
    // read_local_lane_under_pressure(). Steady state: one byte test per pass on a line the pass
    // already owns; the per-op compare below is a popcount against a register.
    [[maybe_unused]] uint32_t read_local_quota = UINT32_MAX;
    if constexpr (Fused)
        if (read_local_enabled &&
            __builtin_expect(fused_executor_->read_local_lane_under_pressure(), false))
            read_local_quota = fused_executor_->read_local_lane_quota(active_.size());
    if constexpr (BatchOps != 0) batch_start_ops = sig.ops;
    // Split O1 needs no per-op schedule budget. This IO thread owns both parsing and
    // retirement, and no WB stage runs inside this parse pass: acquire() already stops at
    // the 64-slot ROB boundary. Local/error completions publish Done; they do not retire.
    if constexpr (IoPipe) static_assert(kRobWindow == 64, "re-audit O1's ROB-bounded parse quantum");
    for (;;) {
        if constexpr (BatchOps != 0)
            if (sig.ops - batch_start_ops >= BatchOps) break;
        // The coordinator's own connection already holds the unfinished FLIP head. Do not
        // parse behind it. Other connections may still parse the FLIP report/control command
        // below so live-vs-target remains observable while the dispatch barrier is active.
        if (__builtin_expect(srv_->flip_dispatch_paused() && c == flip_client_, false)) break;
        if (c->scatter_barrier() || c->parse_backpressure()) break;
        if constexpr (Fused)
            if (read_local_enabled && rob.local_mget_fence_pending()) break;
        Op* op;
        if constexpr (Fused) {
            op = read_local_enabled
                ? rob.acquire_read_local(conn.op_route_flags())
                : rob.acquire<!IofusedPrivateQueue>(conn.op_route_flags());
            // Preserve the old unarmed overlap parser's byte replies. acquire_read_local
            // above uses the existing coded fused arm; overlap WB already handles codes.
        } else {
            op = rob.acquire<false>(conn.op_route_flags());   // 2s keeps the byte path
        }
        if (!op) break;                    // window full: backpressure; let replies drain first
        using DemotionPlan = std::conditional_t<
            Fused, r7_ReadLocalDemotionPlan, EmptyReadLocalDemotionPlan>;
        [[maybe_unused]] DemotionPlan read_local_demotion;
        [[maybe_unused]] bool read_local_owner_conflict = false;
        [[maybe_unused]] ReadLocalFallbackReason read_local_owner_conflict_reason =
            ReadLocalFallbackReason::None;
        [[maybe_unused]] ReadLocalFallbackReason read_local_fallback_reason =
            ReadLocalFallbackReason::None;
        [[maybe_unused]] bool extend_read_local_batch = false;
        [[maybe_unused]] bool read_local_mget_candidate = false;
        [[maybe_unused]] bool read_local_write_hazard = false;
        [[maybe_unused]] bool read_local_eligible_decided = false;
        [[maybe_unused]] bool read_local_eligible = false;
        [[maybe_unused]] bool read_local_commit_at_ordinary = false;
        [[maybe_unused]] bool read_local_commit_before_lowering = false;
        [[maybe_unused]] bool read_local_point_prehashed = false;
        // Keys a local read hands to Rob::mark_current_read_local: every MGET key hashed by
        // the eligibility walk below (no second hashing pass). A point read reports exactly
        // one hash and reaches mark_current_read_local_hash() without building a summary.
        [[maybe_unused]] ReadLocalPendingFilter read_local_pending_keys{};
        // Owner-task demand this read would need if demoted: GET one, MGET its touched-shard
        // bound. Computed once here; the lane room gate and the lane append both consume it.
        [[maybe_unused]] uint32_t read_local_lane_demand = 1;
        uint32_t pos = conn.rpos();
        const char* err = nullptr;
        op->rbuf_off = pos;
        // The authenticated/common path takes the constant-folded parser; only pre-AUTH
        // connections (predicted false) pay real limit arguments. See resp.h for the
        // +83 instr/op lesson behind this split.
        bool security_check = auth_required && !conn.authenticated();
        ParseResult pr;
        if (__builtin_expect(security_check, false)) {
            pr = resp_parse_limited(
                pass_rbuf, pass_rlen, pos, *op, &err, 10, 16384);
        } else if (__builtin_expect(default_bulk_limit, true)) {
            pr = resp_parse(pass_rbuf, pass_rlen, pos, *op, &err);
        } else {
            pr = resp_parse_limited(pass_rbuf, pass_rlen, pos, *op, &err,
                                    1024 * 1024, pass_max_bulk_len);
        }
        security_check |= acl_active;

        if (pr == ParseResult::Empty) {
            conn.advance_parse(pos - conn.rpos());
            continue;
        }
        if (pr == ParseResult::Incomplete) {
            if (pass_rlen == UINT32_MAX) {
                finish_locally(c, *op, "ERR command exceeds receive buffer limit");
                conn.advance_parse(pass_rlen - conn.rpos());
                c->mark_closing();
                result = DispatchResult::Error;
                break;
            }
            // No complete frame was consumed in this pass. The buffered tail is deliberately
            // left in place; only a new recv/readability completion may make it actionable.
            if (conn.rpos() == pass_rpos) result = DispatchResult::NeedInput;
            break;
        }
        if (pr == ParseResult::Error) {
            finish_locally(c, *op, err ? err : "ERR protocol error");
            conn.advance_parse(pass_rlen - conn.rpos());
            c->mark_closing();
            result = DispatchResult::Error;
            break;
        }
        // The parse cursor is deliberately NOT advanced here. It advances only once this op is
        // certain to be answered — see the dispatch-refusal path below for why.
        const uint32_t consumed = pos - conn.rpos();

        const CommandSpec* spec = command_lookup(op->cmd_name());
        if (!spec) {
            conn.advance_parse(consumed);
            // Redis names the command and echoes the first arguments; client libraries and
            // humans both read this line to tell a typo from an unsupported command. The
            // shape is exact: each argument is quoted and followed by one space, the argument
            // list stops once it reaches 128 bytes, and the argument that crosses that line
            // is truncated to the remaining budget (so the trailing space is always there,
            // even with no arguments at all).
            char message[512];
            const Slice name = op->cmd_name();
            int used = std::snprintf(message, sizeof(message),
                                     "ERR unknown command '%.*s', with args beginning with: ",
                                     static_cast<int>(name.n), name.p);
            if (used < 0 || static_cast<size_t>(used) >= sizeof(message))
                used = static_cast<int>(sizeof(message)) - 1;
            const int args_begin = used;
            for (uint32_t i = 1; i < op->argc(); i++) {
                const int args_len = used - args_begin;
                if (args_len >= 128) break;
                const int budget = 128 - args_len;
                const int room = static_cast<int>(sizeof(message)) - used;
                const int wrote = std::snprintf(
                    message + used, static_cast<size_t>(room), "'%.*s' ",
                    static_cast<int>(std::min<uint32_t>(op->arg(i).n,
                                                        static_cast<uint32_t>(budget))),
                    op->arg(i).p);
                if (wrote < 0 || wrote >= room) { used = static_cast<int>(sizeof(message)) - 1; break; }
                used += wrote;
            }
            finish_locally(c, *op, message); continue;
        }
        if (!command_arity_ok(*spec, op->argc())) {
            // Routed containers and SLOWLOG keep a broad container bound in the registry so
            // malformed requests are rejected before ACL and MULTI. On this already-taken
            // cold error path, recover Redis's more specific subcommand name/grammar.
            const bool container_reply = command_reply_container_outer_arity(*op, *spec);
            conn.advance_parse(consumed);
            if (container_reply) {
                finish_prebuilt(c, *op);
                continue;
            }
            char message[128];
            char command[64];
            const size_t name_len = std::min(std::strlen(spec->name), sizeof(command) - 1);
            for (size_t i = 0; i < name_len; i++) {
                const char ch = spec->name[i];
                command[i] = (ch >= 'A' && ch <= 'Z') ? static_cast<char>(ch + ('a' - 'A')) : ch;
            }
            command[name_len] = '\0';
            std::snprintf(message, sizeof(message),
                          "ERR wrong number of arguments for '%s' command", command);
            finish_locally(c, *op, message); continue;
        }
        if ((spec->flags & CmdFlags::SubcmdRoute) &&
            command_reply_container_subcommand_arity(*op, *spec)) {
            // A known child has its own generated arity and Redis checks that before ACL and
            // MULTI. Unknown children deliberately continue: on an unauthenticated connection
            // XGROUP x is parent-arity-valid and must reach NOAUTH.
            conn.advance_parse(consumed);
            finish_prebuilt(c, *op);
            continue;
        }
        if constexpr (Fused) {
            // A consecutive GET can reuse the first member's stable connection gates. Any
            // other frame ends the run but keeps parsing; later writes demote only conflicting
            // unresolved reads instead of turning the run into a connection-wide hold.
            if (read_local_enabled && read_local_batch) {
                extend_read_local_batch =
                    (spec->flags & CmdFlags::ReadLocalEligible) &&
                    !command_is_read_local_mget(*spec) &&
                    conn.multi_session() == nullptr &&
                    rob.pending_read_local_count() < read_local_quota &&
                    fused_executor_->local_read_lane_has_room();
                if (!extend_read_local_batch) read_local_batch = false;
            }
        }
        // THE SOLE DISABLED-STATE FEATURE DECISION on an ordinary operation. The executor
        // receives a spec whose handler pointer is already the clean or armed specialization;
        // no notification mask load reaches its execute path.
        //
        // Lane F rides this ONE branch rather than adding its own. notify_armed_ is the union
        // of "keyspace notifications configured" and "some CLIENT/MONITOR/TRACKING feature is
        // armed" (see climon_refresh_armed), so with everything off the emitted code is
        // byte-for-byte the pre-lane sequence: one predicted-not-taken test, then the tls
        // variant select and the spec store. The armed side pays a cold out-of-line call.
        if (__builtin_expect(notify_armed, false)) {
            spec = command_notify_variant(spec);
            if constexpr (NoBorrow) spec = command_tls_variant(spec);
            op->spec = spec;
        } else {
            if constexpr (NoBorrow) spec = command_tls_variant(spec);
            op->spec = spec;
        }
        // One immutable map for ALL keys, before any route/hash/RYOW work.
        // The separately compiled DB-0 runtime emits none of this lane.
        if constexpr (!kSingleDatabase) {
            // An IO that already acknowledged a database drain may receive
            // more input (or accept a new client). Do not capture the old map
            // while paused: the swap could finish before the later dispatch
            // check, letting an old physical stamp through the new Idle stage.
            // Starting from Idle is safe: a new boundary needs this pass's
            // tail acknowledgement before it can publish its map.
            if (srv_->flip_dispatch_paused() && !(spec->flags & CmdFlags::FlipAsync) &&
                !multidb_dispatch_allowed(*srv_, *c)) {
                c->set_flip_backpressure(true);
                break;
            }
            multidb_stamp(*srv_, *op, conn.session().db_index);
        }
        if constexpr (Fused) {
            if (read_local_enabled) {
                constexpr uint32_t kWriteHazards =
                    CmdFlags::Write | CmdFlags::SnapshotWrite |
                    CmdFlags::Transaction | CmdFlags::ScriptRoute;
                constexpr uint32_t kNonPointRoutes =
                    CmdFlags::AllShards | CmdFlags::RandomShard |
                    CmdFlags::CursorShard | CmdFlags::ConfigRoute |
                    CmdFlags::MultiShard | CmdFlags::ScriptRoute |
                    CmdFlags::Blocking | CmdFlags::Transaction |
                    CmdFlags::StreamRoute | CmdFlags::SubcmdRoute;
                constexpr uint32_t kReplaySensitiveClimon =
                    Server::kClimonMonitor | Server::kClimonTracking |
                    Server::kClimonReply;
                const bool write_hazard = (spec->flags & kWriteHazards) != 0;
                read_local_write_hazard = write_hazard;
                const bool point_route =
                    (spec->flags & kNonPointRoutes) == 0 &&
                    spec->first_key > 0 && spec->last_key == spec->first_key &&
                    spec->key_step == 1;
                if (point_route) {
                    op->hash = FlatStore::hash_key(
                        op->arg(static_cast<uint32_t>(spec->first_key)));
                    op->shard = srv_->router().shard_of(op->hash);
                    read_local_point_prehashed = true;
                }
                auto classify_owner_conflict = [&](auto&& overlaps) {
                    bool broad = false;
                    const bool conflict = rob.read_local_owner_conflicts_before(
                        rob.dispatch_id(), [&](const Op& owner) {
                            if (!overlaps(owner)) return false;
                            broad |= !read_local_owner_command_is_precise(owner);
                            return true;
                        });
                    return !conflict ? ReadLocalFallbackReason::None
                        : broad ? ReadLocalFallbackReason::ContextRoute
                                : ReadLocalFallbackReason::ContextOwnerKey;
                };
                auto owner_conflict_for_hash = [&](uint64_t hash) {
                    return classify_owner_conflict([&](const Op& owner) {
                        return read_local_owner_command_touches_hash(owner, hash);
                    });
                };
                auto owner_conflict_for_command = [&]() {
                    return classify_owner_conflict([&](const Op& owner) {
                        return read_local_commands_overlap(*op, owner);
                    });
                };

                if (write_hazard) {
                    // Stage every historical v1 hazard before the stateful climon gate. A
                    // syntactic one-key owner route or blind MSET keyset can be refined now
                    // that arity is proved. Other multi-key writes remain conservative.
                    rob.mark_current_write();
                    const bool ordinary_point_write =
                        point_route &&
                        (spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite)) != 0 &&
                        !(spec->flags & CmdFlags::ConnLocal);
                    if (ordinary_point_write) {
                        if (climon_armed_cached_ & kReplaySensitiveClimon) {
                            read_local_owner_conflict_reason =
                                owner_conflict_for_hash(op->hash);
                            read_local_owner_conflict = read_local_owner_conflict_reason !=
                                ReadLocalFallbackReason::None;
                        }
                        const bool reserve_owner_fenced_current =
                            read_local_owner_conflict &&
                            (climon_armed_cached_ & kReplaySensitiveClimon) != 0;
                        // An evicting maxmemory policy makes the write conservative, but it is
                        // still an ordinary one-owner route. Reserve that current append along
                        // with the demoted reads so the post-climon sequence remains infallible.
                        //
                        // TWO DIFFERENT QUESTIONS, ONE ANSWER USED FOR BOTH UNTIL NOW.
                        // "Which keys does this write touch" is answered by the eviction
                        // policy alone: with eviction off, an ordinary point write touches
                        // op->hash and nothing else, whatever the ROB's RYOW ring can hold.
                        // "Can the ring record this hash for LATER reads to be checked
                        // against" is a capacity question, and refine_current_write_hash
                        // answers no once sixteen writes are already in flight. Conjoining
                        // them made a full ring turn every further write into a demote-EVERY-
                        // pending-read wave: at 59% writes and pipeline 32 the ring overflows
                        // permanently and every single read on the connection is lowered to
                        // the owner queue (measured: 164000 of 164000 reads, INFO
                        // read_local_fallback_inflight_write). The selection below now asks
                        // only the keys question, which is the owner's rule verbatim -- a read
                        // is held back on explicit key conflict and on nothing else. Nothing
                        // is weakened: require_hash_match=true is already what an unfilled
                        // ring passes here on every ordinary point write.
                        const bool point_write_exact =
                            fused_executor_->read_local_point_writes_precise();
                        // Still gated: with an evicting policy the write may touch keys it
                        // never names, so it must stay a conservative ring generation and no
                        // later read may be cleared against its hash alone.
                        if (point_write_exact) {
                            (void)rob.refine_current_write_hash(op->hash);
                            op->mark_read_local_precise_write();
                        }
                        // DEMOTION-PLAN GATE. prepare() returns true
                        // without building a plan -- loop_ stays null, so active() is false
                        // and commit_reads() is its `if (!loop_) return;` no-op -- unless the
                        // current append must be reserved or a still-pending local read may
                        // overlap this write. Both predicates are single inline loads that
                        // prepare() itself performs first; deciding them here skips the
                        // 12-argument out-of-line call and its abort prologue on the common
                        // disjoint / no-pending-read point write. This is the exact negation
                        // of prepare()'s two true-early-outs for this call site (no intersect
                        // command, no fallback seeds, no filter miss): behaviour identical,
                        // measured -108 instr/op and -23 cyc/op on the armed SET at 1T.
                        const bool needs_demotion_plan =
                            (reserve_owner_fenced_current && op->shard >= 0) ||
                            (rob.has_pending_read_local() &&
                             (!point_write_exact ||
                              rob.read_local_pending_may_touch(op->hash)));
                        if (needs_demotion_plan &&
                            !read_local_demotion.prepare(
                                *this, c, op->hash, point_write_exact, op->shard,
                                ReadLocalFallbackReason::InflightWrite,
                                reserve_owner_fenced_current))
                            break;
                        read_local_commit_at_ordinary = true;
                    } else if (read_local_command_is_precise_mset(*op) &&
                               fused_executor_->read_local_point_writes_precise()) {
                        const uint32_t key_count = (op->argc() - 1) / 2;
                        bool intersect_filter_miss = false;
                        uint64_t filter = 0;
                        if (key_count <= ReadLocalRobState::kMaxPreciseKeysetKeys) {
                            const bool pending_reads = rob.has_pending_read_local();
                            bool pending_filter_hit = false;
                            for (uint32_t arg = 1; arg < op->argc(); arg += 2) {
                                const uint64_t hash = FlatStore::hash_key(op->arg(arg));
                                filter |= ReadLocalRobState::keyset_filter(hash);
                                if (pending_reads && !pending_filter_hit)
                                    pending_filter_hit =
                                        rob.read_local_pending_may_touch(hash);
                            }
                            intersect_filter_miss =
                                !pending_reads || !pending_filter_hit;
                        }
                        const bool keyset_precise =
                            rob.refine_current_write_keyset(filter, key_count);
                        if (keyset_precise) op->mark_read_local_precise_write();
                        if (!read_local_demotion.prepare(
                                *this, c, 0, false, -1,
                                ReadLocalFallbackReason::InflightWrite, false,
                                nullptr, nullptr, 0,
                                keyset_precise ? op : nullptr,
                                keyset_precise && intersect_filter_miss))
                            break;
                        read_local_commit_before_lowering = true;
                    } else if (!read_local_demotion.prepare(
                                   *this, c, 0, false, -1,
                                   ReadLocalFallbackReason::InflightWrite)) {
                        break;
                    } else {
                        read_local_commit_before_lowering = true;
                    }
                } else if ((spec->flags & CmdFlags::ReadLocalEligible) != 0) {
                    const bool mget = command_is_read_local_mget(*spec);
                    read_local_mget_candidate = mget;
                    // MGET owns a one-command latest-read boundary in both outcomes: local
                    // success publishes its freshly copied vector, while demotion resolves the
                    // whole command at this pass's pinned cut. Do not let an older local GET
                    // from the same pass complete at a newer world and then follow it with an
                    // MGET fallback at the older cut. Leave this frame unconsumed; after the
                    // existing local lane resolves, reparsing samples a fresh pass cut.
                    if (mget && rob.has_pending_read_local()) break;
                    if (!mget && !point_route) std::abort();
                    if (mget) {
                        op->hash = FlatStore::hash_key(op->arg(1));
                        op->shard = srv_->router().shard_of(op->hash);
                        read_local_point_prehashed = true;
                        read_local_lane_demand =
                            std::min<uint32_t>(op->argc() - 1, srv_->nshards());
                    }
                    read_local_owner_conflict_reason = owner_conflict_for_command();
                    read_local_owner_conflict = read_local_owner_conflict_reason !=
                        ReadLocalFallbackReason::None;
                    bool write_conflict = false;
                    bool mget_atomic_pending = false;
                    if (mget) {
                        // Sample only the pending-key filter here. An open group outlives the
                        // parse-to-execute gap, so that sample predicts the executor's answer;
                        // the table-mutation bit is one ~200 ns exchange bracket that has
                        // closed long before the executor reads, and sampling it on every
                        // touched shard rejected about 11% of MGETs for nothing the executor's
                        // own probe/validate would not have caught (mget_fallback_seq_churn).
                        for (uint32_t arg = 1; arg < op->argc(); arg++) {
                            const uint64_t hash = arg == 1
                                ? op->hash : FlatStore::hash_key(op->arg(arg));
                            const int32_t shard = arg == 1
                                ? op->shard : srv_->router().shard_of(hash);
                            read_local_pending_keys.add(hash);
                            write_conflict |= rob.read_local_write_conflicts(
                                hash, read_local_command_touches_hash);
                            mget_atomic_pending |=
                                srv_->shard(shard).store().foreign_read_key_unsafe(hash);
                        }
                    } else {
                        write_conflict = rob.read_local_write_conflicts(
                            op->hash, read_local_command_touches_hash);
                    }
                    read_local_eligible = extend_read_local_batch &&
                        !write_conflict && !read_local_owner_conflict;
                    if (extend_read_local_batch &&
                        (write_conflict || read_local_owner_conflict)) {
                        read_local_fallback_reason = write_conflict
                            ? read_local_write_fallback_reason(rob)
                            : read_local_owner_conflict_reason;
                        read_local_batch = false;
                    }
                    if (!extend_read_local_batch) {
                        read_local_eligible = true;
                        if (multi_session_watch_size(conn) != 0) {
                            read_local_fallback_reason =
                                ReadLocalFallbackReason::Watch;
                            read_local_eligible = false;
                        } else if (c->blocked() || c->subscriber_mode()) {
                            read_local_fallback_reason =
                                ReadLocalFallbackReason::ContextConnectionState;
                            read_local_eligible = false;
                        } else if (op->has_scatter_state() ||
                                   (spec->flags &
                                    (CmdFlags::ScriptRoute | CmdFlags::AllShards)) ||
                                   (!mget && (spec->flags & CmdFlags::MultiShard))) {
                            read_local_fallback_reason =
                                ReadLocalFallbackReason::ContextRoute;
                            read_local_eligible = false;
                        } else if (write_conflict) {
                            read_local_fallback_reason =
                                read_local_write_fallback_reason(rob);
                            read_local_eligible = false;
                        } else if (read_local_owner_conflict) {
                            read_local_fallback_reason = read_local_owner_conflict_reason;
                            read_local_eligible = false;
                        } else if (mget &&
                                   fused_executor_->read_local_keymiss_notify_armed()) {
                            // A notify-aware owner lookup can emit keymiss. Local MGET serves
                            // stable misses as nil, so keep the whole command on the unchanged
                            // owner/scatter path while key-miss notifications are configured.
                            read_local_fallback_reason =
                                ReadLocalFallbackReason::ContextKeymissNotify;
                            read_local_eligible = false;
                        } else {
                            bool atomic_pending = mget_atomic_pending;
                            bool seq_churn = false;
                            if (!mget) {
                                const uint64_t state = srv_->shard(op->shard)
                                                           .store()
                                                           .read_local_state_acquire();
                                atomic_pending =
                                    srv_->shard(op->shard)
                                        .store()
                                        .foreign_read_key_unsafe(state, op->hash);
                                seq_churn = !FlatStore::read_local_state_eligible(state);
                            }
                            if (atomic_pending) {
                                read_local_fallback_reason =
                                    ReadLocalFallbackReason::AtomicPending;
                                read_local_eligible = false;
                            } else if (seq_churn) {
                                read_local_fallback_reason =
                                    ReadLocalFallbackReason::SeqChurn;
                                read_local_eligible = false;
                            } else if (rob.pending_read_local_count() >= read_local_quota) {
                                // LANE ADMISSION, fair share: the lane is under
                                // pressure and this connection already holds its share of
                                // it. DEFER -- see the lane-full arm below for the shape.
                                // Deliberately does NOT re-arm the pressure window: a signal
                                // the actuator itself produces cannot police the actuator
                                // (measured: at the lane boundary the window fed by its own
                                // quota deferrals stayed armed forever and deferred 0.8% of
                                // reads where the lane itself refused 0.00008%). Only a real
                                // lane-full event arms it, so the lane proves pressure again
                                // every kReadLocalLanePressureRotations rotations.
                                self_->read_local_stats().defer_quota++;
                                break;
                            } else if (!fused_executor_->local_read_lane_has_room(
                                           read_local_lane_demand)) {
                                // LANE ADMISSION, lane full: DEFER, never demote.
                                // Nothing about this frame has been published -- the ROB
                                // slot is acquired but not published, no lane entry, no
                                // pending bit, no owner slot -- so leaving the bytes at rpos
                                // and ending the pass is the same shape as the MGET
                                // admission fence above. The pass reports Progress, so
                                // more_input keeps the connection in active_ and the next
                                // flush_ready re-parses it after this thread's own EX pass
                                // has drained the lane. The active set supplies that next
                                // visit in both O1 modes; no separate IFID queue is needed.
                                // The former alternative, demoting the read to its shard
                                // owner as an ordinary task, was the seed of the p128 and
                                // 2048-connection pure-read collapse: 7/8 of those tasks
                                // were cross-thread, every pending owner task suppresses the
                                // receiving thread's lane tail-drain, its lane keeps a
                                // residue and fills sooner, and the demotions feed back. A
                                // read whose data is right here now waits one rotation
                                // instead. The deferral arms the pressure window, so the
                                // next rotation divides the lane fairly (quota arm above)
                                // instead of refusing whichever connections it parses last.
                                self_->read_local_stats().defer_lane_full++;
                                fused_executor_->note_local_read_lane_full();
                                break;
                            }
                        }
                    }
                    read_local_eligible_decided = true;
                    if (!read_local_eligible) {
                        if (read_local_fallback_reason ==
                            ReadLocalFallbackReason::None) std::abort();
                        // Keep the owner-routed read visible only to younger overlapping keys.
                        // Disjoint reads may execute locally; ROB retirement orders replies.
                        rob.extend_current_read_local_owner();
                        if (mget) {
                            // The MGET admission fence above reparses instead of reaching here
                            // with any older pending local read, so the intersect set is empty.
                            if (!read_local_demotion.prepare(
                                    *this, c, 0, false, -1,
                                    ReadLocalFallbackReason::ContextOwnerKey,
                                    false, nullptr, nullptr, 0, op, true))
                                break;
                            read_local_commit_before_lowering = true;
                        } else {
                            const bool reserve_owner_fenced_current =
                                read_local_owner_conflict &&
                                (climon_armed_cached_ & kReplaySensitiveClimon) != 0;
                            if (!read_local_demotion.prepare(
                                    *this, c, op->hash, true, op->shard,
                                    ReadLocalFallbackReason::ContextOwnerKey,
                                    reserve_owner_fenced_current))
                                break;
                            read_local_commit_at_ordinary = true;
                        }
                    }
                } else if (!(spec->flags & CmdFlags::ConnLocal)) {
                    read_local_owner_conflict_reason = point_route
                        ? owner_conflict_for_hash(op->hash)
                        : classify_owner_conflict([](const Op&) { return true; });
                    read_local_owner_conflict = read_local_owner_conflict_reason !=
                        ReadLocalFallbackReason::None;
                    if (read_local_owner_conflict)
                        rob.extend_current_read_local_owner();
                    const bool reserve_owner_fenced_current =
                        read_local_owner_conflict && point_route &&
                        (climon_armed_cached_ & kReplaySensitiveClimon) != 0;
                    if (!read_local_demotion.prepare(
                            *this, c, point_route ? op->hash : 0,
                            point_route, point_route ? op->shard : -1,
                            point_route ? ReadLocalFallbackReason::ContextOwnerKey
                                        : ReadLocalFallbackReason::ContextRoute,
                            reserve_owner_fenced_current))
                        break;
                    if (point_route) read_local_commit_at_ordinary = true;
                    else read_local_commit_before_lowering = true;
                }
            }
        }
        if constexpr (Fused) {
            if (read_local_enabled && read_local_demotion.active() &&
                read_local_demotion.partial()) {
                if (__builtin_expect(srv_->flip_dispatch_paused(), false) &&
                    !(spec->flags & CmdFlags::FlipAsync) &&
                    !(!kSingleDatabase && multidb_dispatch_allowed(*srv_, *c))) {
                    c->set_flip_backpressure(true);
                    break;
                }
                // Only older, already-admitted reads are published here. The current frame is
                // still unconsumed, the FLIP fence above admitted publication, and it has not
                // crossed MONITOR/tracking or ACL, so it can be reparsed after the bounded wave
                // without replaying stateful hooks.
                read_local_demotion.commit_reads();
                break;
            }
        }
        if (__builtin_expect(notify_armed, false) &&
            __builtin_expect(climon_armed_gate(c, *op), false)) break;
        if (__builtin_expect(security_check, false) &&
            acl_dispatch_entry(*this, conn, *op, consumed, security_flags)) continue;
        if (__builtin_expect(srv_->flip_dispatch_paused(), false) &&
            !(spec->flags & CmdFlags::FlipAsync) &&
            !(!kSingleDatabase && multidb_dispatch_allowed(*srv_, *c))) {
            // No ordinary request may create IO-local fanout or executor work after the first
            // drain acknowledgement. Leave the frame unconsumed and unpublished: TCP framing
            // keeps younger frames behind it without a ROB barrier, while FlipAsync commands
            // at the head of other connections remain reachable throughout the pause.
            c->set_flip_backpressure(true);
            break;
        }
        if constexpr (Fused) {
            // This must follow the per-frame FLIP gate above: demotion itself publishes owner
            // Tasks. Non-point routes may touch any key, so move every unresolved local read
            // before any of their lowering paths can publish.
            if (read_local_enabled && read_local_commit_before_lowering) {
                if (read_local_demotion.active() && !read_local_write_hazard) {
                    rob.extend_current_read_local_owner();
                }
                read_local_demotion.commit_reads();
            }
        }
        if (__builtin_expect((spec->flags & CmdFlags::Transaction) != 0, false) ||
            __builtin_expect(conn.multi_session() != nullptr, false)) {
            if constexpr (Fused) {
                if (read_local_enabled &&
                    __builtin_expect((spec->flags & CmdFlags::ReadLocalEligible) &&
                                     multi_session_active(conn), false))
                    self_->read_local_stats().note_fallback(
                        ReadLocalFallbackReason::Multi,
                        command_is_read_local_mget(*spec));
            }
            if constexpr (IofusedPrivateQueue) {
                if (multi_dispatch_entry_iofused(*this, conn, *op, consumed)) continue;
            } else {
                if (multi_dispatch_entry(*this, conn, *op, consumed)) continue;
            }
        }
        const bool config_scatter = (spec->flags & CmdFlags::ConfigRoute) &&
                                    command_config_routes_all_shards(*op);

        // RESP2 enters subscribed mode after its first subscription acknowledgement. Only the
        // Redis subscriber command set is legal until the last subscription is removed.
        const bool subscriber_mode = __builtin_expect(c->subscriber_mode(), false);
        if (subscriber_mode) {
            if (op->cmd_name().eq_icase("reset")) {
                conn.advance_parse(consumed);
                self_->note_command(spec->id);
                flip_fingerprint_note(*spec, *op);
                climon_reset_client(c, *op);
                pubsub_start_reset(c, *op);
                sig.ops++;
                mark_active_known<TargetedIfid>(c);
                break;
            }
            if (op->resp3()) goto subscriber_checks_done;
            const bool subscription_control =
                op->cmd_name().eq_icase("subscribe") ||
                op->cmd_name().eq_icase("unsubscribe") ||
                op->cmd_name().eq_icase("psubscribe") ||
                op->cmd_name().eq_icase("punsubscribe") ||
                op->cmd_name().eq_icase("ssubscribe") ||
                op->cmd_name().eq_icase("sunsubscribe");
            if (op->cmd_name().eq_icase("ping")) {
                conn.advance_parse(consumed);
                self_->note_command(spec->id);
                flip_fingerprint_note(*spec, *op);
                pubsub_reply_ping(*op);
                finish_prebuilt(c, *op);
                continue;
            }
            if (!subscription_control && !op->cmd_name().eq_icase("quit")) {
                conn.advance_parse(consumed);
                self_->note_command(spec->id);
                flip_fingerprint_note(*spec, *op);
                pubsub_reply_restricted(*op);
                finish_prebuilt(c, *op);
                continue;
            }
        }
subscriber_checks_done:
        if (spec->flags & CmdFlags::PubSub) {
            conn.advance_parse(consumed);
            self_->note_command(spec->id);
            flip_fingerprint_note(*spec, *op);
            const PubSubStartResult result = pubsub_start_command(c, *op);
            if (result == PubSubStartResult::Async) {
                sig.ops++;
                mark_active_known<TargetedIfid>(c);
                if (__builtin_expect(c->scatter_barrier(), false)) break;
                continue;
            }
            finish_prebuilt(c, *op);
            // A CLIENT subcommand may have just armed or disarmed this lane, invalidating
            // the pass-local armed cache above. Ending the pass is the cheapest correct
            // answer: the next one re-reads it. One predicted-false test on a branch GET and
            // SET never enter.
            if (__builtin_expect(climon_armed_dirty_, false)) {
                climon_armed_dirty_ = false;
                break;
            }
            continue;
        }

        // Connection-local commands never reach a worker — the cheapest class, and the one most
        // easily wasted by routing it anyway.
        if ((spec->flags & CmdFlags::ConnLocal) ||
            ((spec->flags & CmdFlags::ConfigRoute) && !config_scatter)) {
            // SCRIPT/FUNCTION read and mutate state that in-flight EVAL/EVALSHA/FCALL
            // activations produce or consume, so they observe same-connection program order
            // through the ROB-head barrier the blocking lowering already uses. Everything
            // else keeps the parse-time answer. The barrier break runs FIRST so a barred op
            // retries from scratch before any lane hook fires.
            if (__builtin_expect((spec->flags & CmdFlags::OrderedLocal) != 0, false) &&
                rob.in_flight() != 0) break;
            if (__builtin_expect((spec->flags & CmdFlags::FlipAsync) != 0, false) &&
                op->argc() == 3) {
                auto parse_count = [](Slice input, uint32_t& value) {
                    if (!input.n) return false;
                    uint64_t parsed = 0;
                    for (uint32_t i = 0; i < input.n; i++) {
                        if (input.p[i] < '0' || input.p[i] > '9') return false;
                        parsed = parsed * 10 + static_cast<uint32_t>(input.p[i] - '0');
                        if (parsed > UINT32_MAX) return false;
                    }
                    value = static_cast<uint32_t>(parsed);
                    return true;
                };
                uint32_t target_io = 0, target_ex = 0;
                std::string error;
                bool started = parse_count(op->arg(1), target_io) &&
                               parse_count(op->arg(2), target_ex);
                if (!started) {
                    error = "ERR FLIP io and ex must be unsigned integers";
                    srv_->flip_note_refused();
                } else
                    started = srv_->flip_begin(target_io, target_ex, self_id, error);
                conn.advance_parse(consumed);
                self_->note_command(spec->id);
                flip_fingerprint_note(*spec, *op);
                if (!started || srv_->flip_stage() == FlipStage::Idle) {
                    if (started) reply_ok(op->sink());
                    else reply_err(op->sink(), error.c_str());
                    op->state.store(OpState::Done, std::memory_order_release);
                    rob.publish();
                    enqueue_serve(c);
                    mark_active_known<TargetedIfid>(c);
                    continue;
                }
                flip_client_ = c;
                flip_op_id_ = rob.dispatch_id();
                flip_epoch_local_ = srv_->flip_epoch();
                rob.publish();              // sole unfinished op on the coordinator connection
                mark_active_known<TargetedIfid>(c);
                break;
            }
            // DEBUG SLEEP parks only this connection. The unfinished ROB slot preserves
            // pipeline order while this IO thread continues serving unrelated clients (and,
            // in 1s, continues owning shards). All other DEBUG forms fall through unchanged.
            if (__builtin_expect((spec->flags & CmdFlags::DebugSleep) != 0, false)) {
                if (op->argc() == 2 && op->arg(1).eq_icase("rehash-state")) {
                    // This diagnostic reads mutable table counters. ConfigRoute normally
                    // executes on the connection's IO thread, even though it passes shard 0
                    // to the handler. Dispatch to the real owner instead, using the ordinary
                    // queue/forwarding/publication path below. No read performs maintenance.
                    op->hash = 0;
                    op->shard = 0;
                    goto ordinary_shard_ready;
                }
                uint64_t delay_ms = 0;
                const uint64_t slow_started =
                    __builtin_expect(slowlog_armed_, false) ? now_ns() : 0;
                DebugSleepResult sleep =
                    debug_sleep_prepare(*srv_, *c, *op, delay_ms);
                if (sleep != DebugSleepResult::NotSleep) {
                    if (sleep == DebugSleepResult::Deferred &&
                        deferred_timer_start(c, rob.dispatch_id(),
                                             DeferredTimerKind::DebugSleepOk, delay_ms,
                                             slow_started, slowlog_arm_)) {
                        conn.advance_parse(consumed);
                        self_->note_command(spec->id);
                        flip_fingerprint_note(*spec, *op);
                        rob.publish();
                        c->set_blocked(true);
                        // As with WAIT, retirement releases the barrier only after the timer's
                        // reply has been staged and the ROB becomes quiescent.
                        barrier_arm(c, BarrierOwner::Sleep);
                        mark_active_known<TargetedIfid>(c);
                        break;
                    }
                    if (sleep == DebugSleepResult::Deferred)
                        reply_err(op->sink(), "ERR out of memory");
                    if (__builtin_expect(slowlog_armed_, false)) {
                        timespec wall{};
                        ::clock_gettime(CLOCK_REALTIME, &wall);
                        slowlog_record(self_id, c->id(), *op, now_ns() - slow_started,
                                       static_cast<int64_t>(wall.tv_sec) * 1000 +
                                           wall.tv_nsec / 1000000,
                                       slowlog_arm_, true);
                    }
                    conn.advance_parse(consumed);
                    self_->note_command(spec->id);
                    flip_fingerprint_note(*spec, *op);
                    op->state.store(OpState::Done, std::memory_order_release);
                    rob.publish();
                    enqueue_serve(c);
                    mark_active_known<TargetedIfid>(c);
                    continue;
                }
            }
            // An unsatisfied WAIT has no shard work, but Redis keeps the connection parked
            // until its deadline (zero means forever). Publish an unfinished ROB slot and let
            // this connection's IO owner complete it. MULTI does not enter this branch: its
            // IoLocal child calls cmd_wait at retirement and receives :0 immediately.
            if (__builtin_expect((spec->flags & CmdFlags::DeferredLocal) != 0, false)) {
                uint64_t timeout_ms = 0;
                const WaitCommandResult wait = server_tail_prepare_wait(*op, timeout_ms);
                if (wait == WaitCommandResult::Unsatisfied) {
                    if (!deferred_timer_start(c, rob.dispatch_id(),
                                              DeferredTimerKind::WaitZero, timeout_ms, 0,
                                              SlowlogArm{})) {
                        reply_err(op->sink(), "ERR out of memory");
                    } else {
                        conn.advance_parse(consumed);
                        self_->note_command(spec->id);
                        flip_fingerprint_note(*spec, *op);
                        rob.publish();
                        c->set_blocked(true);
                        // Released by the quiescence backstop, not here: a parked WAIT's own
                        // completion (deferred_timer_pass) fires before its op retires, and
                        // dropping the barrier there would let younger frames parse ahead of
                        // the WAIT reply's staging. Owner bit named so the release is
                        // attributable; the release site is deliberately unchanged.
                        barrier_arm(c, BarrierOwner::Wait);
                        mark_active_known<TargetedIfid>(c);
                        break;
                    }
                } else if (wait == WaitCommandResult::Immediate) {
                    reply_int(op->sink(), 0);
                }
                // Error already carries its exact validation reply. Immediate already carries
                // :0. Both retire through the ordinary local completion path below.
                conn.advance_parse(consumed);
                self_->note_command(spec->id);
                flip_fingerprint_note(*spec, *op);
                op->state.store(OpState::Done, std::memory_order_release);
                rob.publish();
                enqueue_serve(c);
                mark_active_known<TargetedIfid>(c);
                continue;
            }
            // RESET clears this lane's connection state (monitor mode, tracking registration,
            // CLIENT REPLY mode) before the ordinary handler writes +RESET. One predicted-
            // false flag test on a word the dispatcher already holds, on an already-cold
            // command class -- no name comparison, and nothing on the ordinary path.
            if (__builtin_expect((spec->flags & CmdFlags::Climon) != 0, false))
                climon_reset_client(c, *op);
            conn.advance_parse(consumed);
            self_->note_command(spec->id);
            flip_fingerprint_note(*spec, *op);
            command_set_local_context(c, self_);
            snapshot_bind_io(self_, &ring_);
            const bool acl_command = __builtin_expect(op->cmd_name().eq_icase("acl"), false);
            const uint64_t slow_started =
                __builtin_expect(slowlog_armed_, false) ? now_ns() : 0;
            if (acl_command)
                acl_command_entry(*this, conn, *op);
            else
                spec->handler(srv_->shard(0), *op);
            if (__builtin_expect(slowlog_armed_, false)) {
                timespec wall{};
                ::clock_gettime(CLOCK_REALTIME, &wall);
                slowlog_record(self_id, c->id(), *op, now_ns() - slow_started,
                               static_cast<int64_t>(wall.tv_sec) * 1000 +
                                   wall.tv_nsec / 1000000,
                               slowlog_arm_, true);
            }
            snapshot_bind_io(nullptr, nullptr);
            command_set_local_context(nullptr, nullptr);
            op->state.store(OpState::Done, std::memory_order_release);
            rob.publish();
            enqueue_serve(c);
            mark_active_known<TargetedIfid>(c);
            if (c->closing()) { result = DispatchResult::Closed; break; }
            if (acl_command) break;
            if (op->cmd_name().eq_icase("select") || op->cmd_name().eq_icase("reset")) break;
            if (__builtin_expect(climon_armed_dirty_, false)) {
                climon_armed_dirty_ = false;
                break;
            }
            continue;
        }

        // This command only needs an owner-local same-connection pending lookup when an older
        // cross-shard atomic group was already in flight. Set the immutable bit before the
        // current group increments the count, so a group never treats itself as a predecessor.
        if (c->has_atomic_group_io()) op->mark_atomic_hazard();
        // PIN THE READ CUT IN PROGRAM ORDER. Same-connection ops are prepared here, in the
        // order the client sent them, so a cut taken no later than here is monotone along the
        // connection for free -- which is exactly the property "a later reply may not be older
        // than an earlier one" needs and that sampling at EXECUTION cannot give. Writes are
        // excluded on purpose (see Op::read_cut_lo). Off, this is one predicted-not-taken
        // test; on, it is one store into a line reset() already dirtied.
        // Blocking commands are excluded as well, and not for cost: a parked one is
        // re-prepared by blocking_resume_move() long after its arrival, so a cut pinned at
        // first dispatch would make the resumed read answer from before the write that woke
        // it. They need no cut anyway -- a blocking command is a whole-connection barrier
        // (it waits to be ROB head and stops the parse pass), so nothing younger on this
        // connection is even prepared until it has finished.
        if (__builtin_expect(atomic_tracking, false) &&
            !(spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite |
                             CmdFlags::Blocking)))
            op->set_read_cut(pass_read_cut);

        if (spec->flags & CmdFlags::Blocking) {
            // XREAD is registered as blocking so the ordinary GET/SET branch remains
            // byte-for-byte the established hot gate. Its immediate form skips this lowering.
            if ((spec->flags & CmdFlags::StreamRoute) && !blocking_wants_dispatch(*op))
                goto nonblocking_dispatch;
            // A blocking command is a connection barrier, including against older frames.
            // Waiting to issue it until the ROB head preserves same-connection program order
            // without teaching the owner registry about younger operations.
            if (rob.in_flight() != 0) break;
            BlockingDispatch dispatch;
            const BlockingPrepare prepared = blocking_prepare(
                *srv_, *c, *op, rob.dispatch_id(), dispatch);
            if (prepared == BlockingPrepare::Error) {
                conn.advance_parse(consumed);
                finish_prebuilt(c, *op);
                continue;
            }
            uint32_t needed[kMaxThreads] = {};
            for (uint32_t i = 0; i < dispatch.nshards; i++) {
                const int32_t sid = blocking_dispatch_shard(dispatch, i);
                needed[srv_->worker_of_shard(sid)]++;
            }
            bool room = true;
            for (uint32_t tid = 0; tid < srv_->nthreads(); tid++) {
                if (needed[tid] &&
                    task_free_slots(srv_->thread(tid)) < needed[tid]) {
                    room = false;
                    break;
                }
            }
            if (!room) {
                blocking_destroy_unpublished(dispatch.state);
                break;
            }
            const uint64_t op_id = rob.dispatch_id();
            op->attach_blocking_state(dispatch.state);
            blocking_start(dispatch.state, dispatch.nshards);
            rob.publish();
            for (uint32_t i = 0; i < dispatch.nshards; i++) {
                const int32_t sid = blocking_dispatch_shard(dispatch, i);
                const uint32_t tid = srv_->worker_of_shard(sid);
                ThreadCtx& owner = srv_->thread(tid);
                const Task task{c, op_id, sid,
                                reinterpret_cast<ScatterState*>(dispatch.state)};
                if (!post_task_quiet(owner, task)) std::abort();
                if (!touched_[tid]) {
                    touched_[tid] = true;
                    touched_list_[ntouched_++] = tid;
                }
            }
            self_->note_command(spec->id);
            flip_fingerprint_note(*spec, *op);
            conn.advance_parse(consumed);
            sig.ops++;
            c->set_blocked(true);
            // The Blocking owner spans the WHOLE parked lifetime, including the move scatter
            // blocking_resume_move() converts this op into: that conversion reuses the ROB
            // slot and inherits this claim rather than taking a second one, so exactly one
            // acquire is matched by exactly one release in blocking_retire() OR
            // blocking_scatter_retire(), whichever of the two exits runs.
            barrier_arm(c, BarrierOwner::Blocking);
            // TEST HOOK (DEBUG BARRIER-HOLD): pin a SECOND owner on this connection so the
            // blocking release has something to fail to drop. The geometry it manufactures is
            // unreachable in production -- which is exactly why it has to be injected.
            //
            // Armed THROUGH barrier_arm on purpose, so this is the positive control for
            // barrier_owner_overlaps as well: with the latch on, every blocking dispatch adds
            // exactly one overlap, which is what proves the counter can count. The production
            // assertion (overlaps == 0) is then read from a phase where the latch is off, and
            // means something, instead of being a number nothing was ever able to move.
            if (__builtin_expect(srv_->debug_barrier_hold_armed(), false))
                barrier_arm(c, BarrierOwner::Debug);
            mark_active_known<TargetedIfid>(c);
            break;
        }

nonblocking_dispatch:
        // Ordinary single-key commands never enter the scatter engine. Keep xshard_prepare's
        // own classification guard for its other callers, but avoid paying the cross-TU call
        // just to discover that GET/SET have none of the three scatter-routing flags.
        if constexpr (Fused)
            if (read_local_enabled && read_local_mget_candidate && read_local_eligible)
                goto ordinary_dispatch;
        if (!(spec->flags & (CmdFlags::AllShards | CmdFlags::MultiShard |
                            CmdFlags::ConfigRoute))) goto ordinary_dispatch;
        {
        ScatterDispatch scatter_dispatch;
        const ScatterPrepare scatter_prepared =
            xshard_prepare(*srv_, *op, scatter_pool_, self_id, c->id(), scatter_dispatch,
                           false, c);
        if (scatter_prepared == ScatterPrepare::Error) {
            conn.advance_parse(consumed);
            finish_prebuilt(c, *op);
            if constexpr (Fused)
                if (read_local_enabled && read_local_mget_candidate &&
                    read_local_fallback_reason != ReadLocalFallbackReason::None)
                    self_->read_local_stats().note_fallback(
                        read_local_fallback_reason, true);
            continue;
        }
        if (scatter_prepared == ScatterPrepare::Backpressure) {
            // Leave this frame unconsumed and retry it when a window slot retires. TCP framing
            // naturally keeps younger frames behind it; no ROB-quiescence barrier is needed.
            c->set_atomic_backpressure(true);
            break;
        }
        if (scatter_prepared == ScatterPrepare::Ready) {
            // SAME-CONNECTION PROGRAM ORDER ACROSS A SECOND WAVE OF TASKS.
            //
            // A barriered scatter is exactly the set of commands that publish a SECOND wave of
            // owner tasks from an EX thread rather than from here: a two-hop store's phase-2
            // destination install (publish_phase2), an LMPOP/ZMPOP retry, the cross-owner
            // script apply wave. Those tasks enter the destination owner through the EX
            // producer's inbox channel, while this connection's ordinary ops entered through
            // THIS io thread's channel -- and ThreadCtx::drain_tasks visits channels in
            // producer-id order, so nothing orders the two. A phase-2 install could therefore
            // execute BEFORE an older op of the same connection that was still sitting in our
            // channel, and that older op then answered from after a store it precedes.
            // Measured: `ZDIFFSTORE d 2 a b` answering :1 with the very next `ZCARD d`
            // answering :2, and a `DEL` of a destination landing after a younger store.
            //
            // The barrier the dispatch sets below already keeps YOUNGER ops out; this keeps
            // older ones from still being in. Same lowering the blocking path uses: wait for
            // the ROB head, leave the frame unconsumed, and re-parse once the connection
            // quiesces. Read-only and single-wave scatters (MGET, MSET/DEL groups, a direct
            // RENAME) are not barriered and do not pay it -- they post every task from here.
            if (scatter_dispatch.barrier && rob.in_flight() != 0) {
                xshard_abandon_unpublished(scatter_dispatch.state, scatter_pool_, self_id);
                break;
            }
            // Read-only/plain scatters keep the compact V3 dispatch arm. Constructing route and
            // bundle arrays for MGET added work without helping its already-cheap individual
            // queue stores. Atomic writes take the bundled arm below, where fan-out dominates.
            if (!scatter_dispatch.atomic_write) {
                // The demand array is a zero-on-entry member and the participant list is
                // uninitialised stack, so neither the 512-byte zero-init nor the walk over
                // every configured thread happens here. A 2-key cross-shard read touches two
                // owners whether the server runs 4 threads or 128.
                uint32_t* const needed = dispatch_needed_;
                uint32_t participants[kMaxThreads];
                uint32_t nparticipants = 0;
                for (uint32_t i = 0; i < scatter_dispatch.nshards; i++) {
                    const int32_t sid = xshard_dispatch_shard(scatter_dispatch, i);
                    const uint32_t tid = srv_->worker_of_shard(sid);
                    if (needed[tid]++ == 0) participants[nparticipants++] = tid;
                }
                bool room = true;
                for (uint32_t p = 0; p < nparticipants; p++) {
                    const uint32_t tid = participants[p];
                    if (task_free_slots(srv_->thread(tid)) < needed[tid]) {
                        room = false;
                        break;
                    }
                }
                // Restore the zero-on-entry invariant before EVERY exit from this arm.
                for (uint32_t p = 0; p < nparticipants; p++) needed[participants[p]] = 0;
                if (!room) {
                    xshard_abandon_unpublished(
                        scatter_dispatch.state, scatter_pool_, self_id);
                    break;
                }
                const uint64_t op_id = rob.dispatch_id();
                op->attach_scatter_state(scatter_dispatch.state);
                rob.publish();
                for (uint32_t i = 0; i < scatter_dispatch.nshards; i++) {
                    const int32_t sid = xshard_dispatch_shard(scatter_dispatch, i);
                    const uint32_t tid = srv_->worker_of_shard(sid);
                    ThreadCtx& owner = srv_->thread(tid);
                    const Task task{c, op_id, sid, scatter_dispatch.state};
                    if (!post_task_quiet(owner, task)) std::abort();
                    if (!touched_[tid]) {
                        touched_[tid] = true;
                        touched_list_[ntouched_++] = tid;
                    }
                }
                self_->note_command(spec->id);
                flip_fingerprint_note(*spec, *op);
                conn.advance_parse(consumed);
                sig.ops++;
                if constexpr (Fused)
                    if (read_local_enabled && read_local_mget_candidate &&
                        read_local_fallback_reason != ReadLocalFallbackReason::None)
                        self_->read_local_stats().note_fallback(
                            read_local_fallback_reason, true);
                head_candidate = false;
                if (scatter_dispatch.barrier) barrier_arm(c, BarrierOwner::Scatter);
                mark_active_known<TargetedIfid>(c);
                continue;
            }

            uint32_t needed[kMaxThreads] = {};
            uint32_t participants[kMaxThreads];
            uint16_t routed_owner[256];
            int32_t routed_shard[256];
            uint32_t nparticipants = 0;
            for (uint32_t i = 0; i < scatter_dispatch.nshards; i++) {
                const int32_t sid = xshard_dispatch_shard(scatter_dispatch, i);
                const uint32_t tid = srv_->worker_of_shard(sid);
                routed_shard[i] = sid;
                routed_owner[i] = static_cast<uint16_t>(tid);
                if (needed[tid]++ == 0) participants[nparticipants++] = tid;
            }
            bool room = true;
            for (uint32_t p = 0; p < nparticipants; p++) {
                const uint32_t tid = participants[p];
                if (task_free_slots(srv_->thread(tid)) < needed[tid]) {
                    room = false; break;
                }
            }
            if (!room) {
                xshard_abandon_unpublished(scatter_dispatch.state, scatter_pool_, self_id);
                break;
            }
            const uint64_t op_id = rob.dispatch_id();
            op->attach_scatter_state(scatter_dispatch.state);
            c->atomic_group_started();
            rob.publish();
            Task posts[256];
            uint16_t participant_begin[kMaxThreads];
            uint32_t cursor = 0;
            for (uint32_t p = 0; p < nparticipants; p++) {
                const uint32_t tid = participants[p];
                participant_begin[p] = static_cast<uint16_t>(cursor);
                cursor += needed[tid];
                needed[tid] = participant_begin[p]; // reuse as the fill cursor
            }
            for (uint32_t i = 0; i < scatter_dispatch.nshards; i++) {
                const uint32_t tid = routed_owner[i];
                posts[needed[tid]++] = Task{
                    c, op_id, routed_shard[i], scatter_dispatch.state};
            }
            if (cursor != scatter_dispatch.nshards) std::abort();
            for (uint32_t p = 0; p < nparticipants; p++) {
                const uint32_t tid = participants[p];
                const uint32_t begin = participant_begin[p];
                const uint32_t end = p + 1 < nparticipants
                    ? participant_begin[p + 1] : scatter_dispatch.nshards;
                ThreadCtx& owner = srv_->thread(tid);
                // Capacity was checked before any push. Publish all of this group's tasks for
                // one executor with one queue-tail store; the parse-pass notify remains folded.
                if (!post_tasks_quiet(owner, posts + begin, end - begin)) std::abort();
                if (!touched_[tid]) { touched_[tid] = true; touched_list_[ntouched_++] = tid; }
            }
            self_->note_command(spec->id); // one public command, not one count per shard task
            flip_fingerprint_note(*spec, *op);
            conn.advance_parse(consumed);
            sig.ops++;
            head_candidate = false;
            if (scatter_dispatch.barrier) barrier_arm(c, BarrierOwner::Scatter);
            mark_active_known<TargetedIfid>(c);
            continue;
        }
        }

ordinary_dispatch:
        // The ordinary key position is registry metadata. Container children and the other
        // special routes refine it in the existing CursorShard hook below.
        if (spec->flags & CmdFlags::CursorShard) {
            if (!command_prepare_scan_route(*srv_, *op)) {
                conn.advance_parse(consumed);
                finish_prebuilt(c, *op);
                continue;
            }
        } else if (spec->flags & CmdFlags::RandomShard) {
            uint64_t random = next_random();
            uint32_t start = static_cast<uint32_t>(random % srv_->nshards());
            uint32_t chosen = start;
            for (uint32_t n = 0; n < srv_->nshards(); n++) {
                const uint32_t candidate = (start + n) % srv_->nshards();
                if (srv_->shard(static_cast<int32_t>(candidate)).published_size()) {
                    chosen = candidate; break;
                }
            }
            op->hash = random;
            op->shard = static_cast<int32_t>(chosen);
        } else {
            if (!read_local_point_prehashed) {
                op->hash = FlatStore::hash_key(
                    op->arg(static_cast<uint32_t>(spec->first_key)));
                op->shard = srv_->router().shard_of(op->hash);
            }
        }

ordinary_shard_ready:
        if constexpr (Fused) {
            if (read_local_enabled && read_local_commit_at_ordinary) {
                // prepare() reserved the selected reads and this operation before any stateful
                // parser hook. Publish the reads first; the retained current credit makes the
                // ordinary owner append below infallible and preserves SPSC FIFO.
                if (read_local_demotion.active() && !read_local_write_hazard) {
                    rob.extend_current_read_local_owner();
                }
                read_local_demotion.commit_reads();
            }
            if (read_local_enabled &&
                __builtin_expect(spec->flags & CmdFlags::ReadLocalEligible, false)) {
                if (!read_local_eligible_decided) std::abort();
                if (read_local_eligible) {
                    if (head_candidate) {
                        head_candidate = false;
                        if (rob.in_flight() == 0 && c->nothing_to_write()) {
                            SmallBuf<kWbufInline>& fb = c->fill_buf();
                            op->direct = fb.data();
                            op->direct_cap = static_cast<uint32_t>(fb.cap());
                        }
                    }
                    const uint64_t op_id = rob.dispatch_id();
                    op->mark_read_local();
                    // Every hash read_local_command_touches_hash(*op, .) can match must enter
                    // the pending filter here (GET: op->hash; MGET: the keys hashed above).
                    // A point read reports exactly one, so it sets that word directly instead
                    // of merging a summary whose other three words it had just zeroed.
                    if (read_local_mget_candidate)
                        rob.mark_current_read_local(op_id, read_local_pending_keys);
                    else
                        rob.mark_current_read_local_hash(op_id, op->hash);
                    if (read_local_mget_candidate)
                        rob.arm_current_local_mget_fence();
                    rob.publish();
                    // Room was proved by local_read_lane_has_room(read_local_lane_demand)
                    // above for this very op (run extension at the top of the frame, run head
                    // in the gate chain); nothing between there and here consumes lane room.
                    fused_executor_->enqueue_local_read(c, op_id, read_local_lane_demand);
                    conn.advance_parse(consumed);
                    sig.ops++;
                    flip_fingerprint_note(*spec, *op);
                    mark_active_known<TargetedIfid>(c);
                    read_local_batch = !read_local_mget_candidate;
                    // Fill at most the existing fused IFID quantum; intervening ordinary frames
                    // simply end this run. MGET holds a one-command cut fence until local
                    // validation or irrevocable owner demotion, so stop this parse pass now.
                    if (read_local_mget_candidate) break;
                    continue;
                }
            }
        }

        const uint32_t worker_id = srv_->worker_of_shard(op->shard);
        ThreadCtx& worker = srv_->thread(worker_id);
        if constexpr (Fused && !SplitLocal) {
            if (spec->id == g_hot_command_specs.set->id && op->arg(2).n > kEmbedThreshold &&
                worker_id != self_id &&
                srv_->thread_mode() == ThreadMode::Fused)
                l4prebuild_prepare_set(*op);
        }

        // PUBLISH BEFORE DISPATCH. The old order posted the task first and published after, which
        // left a window of two instructions in which a worker could receive the task, execute it,
        // mark it Done and notify the sender -- all while dispatch_ still excluded the op. The
        // sender then woke, drained a ROB that did not yet contain the op, retired nothing, and
        // went back to sleep having spent its one notification. Nothing ever notified again, so
        // the reply sat Done in the ROB forever.
        //
        // It cost 3 lost replies in 87 million and wedged the connection permanently. Invisible in
        // 2-stage, where io is the sender and re-drains its own active set unprompted; it was
        // FATAL in the deleted remote-sender modes, and the ordering is kept because it is
        // simply correct: publish, then tell.
        // DIRECT-REPLY eligibility (owner's c->buf trick): this op is the ROB head and the
        // fill buffer is empty, so its bytes can be formatted in place by the worker. True for
        // every op at depth 1 and for the head of each fresh batch at depth. Evaluated ONLY for
        // the first dispatch of the pass: later ops cannot be head, and the in_flight() read
        // touches flush_, a line the sender writes -- checked per op it became a per-op
        // cross-thread load and cost -2..-4% at p32 for a candidate that can never qualify.
        if (head_candidate) {
            head_candidate = false;
            if (rob.in_flight() == 0 && c->nothing_to_write()) {
                SmallBuf<kWbufInline>& fb = c->fill_buf();
                op->direct     = fb.data();
                op->direct_cap = static_cast<uint32_t>(fb.cap());
            }
        }
        Task t{c, rob.dispatch_id(), -1, nullptr};
            shadow_dispatch.stamp(t);
        rob.publish();
        bool posted = false;
        if constexpr (Fused) {
            if (read_local_enabled && read_local_demotion.current_reserved()) {
                read_local_demotion.post_current(t, worker_id);
                posted = true;
            }
        }
        if (!posted && !post_task_quiet(worker, t)) {
            rob.unpublish();          // a refused push must leave NO trace -- including in the ROB
            if constexpr (Fused && !SplitLocal) l4prebuild_discard_set(*op);
            // A REFUSED PUSH MUST LEAVE NO TRACE. Advancing the parse cursor before this point
            // consumed the command's bytes while publishing no op, so the client waited forever
            // for a reply that would never be produced and the connection wedged. This is not an
            // edge case: with enough io threads feeding few workers the inbox fills routinely,
            // and it hung a benchmark within seconds at io6/ex2. Leaving the cursor untouched
            // means the command is simply re-parsed on a later pass, once retiring has freed
            // inbox space.
            break;
        }
        if constexpr (Fused) {
            // Count only after the owner task is irrevocably queued. A refused SPSC push
            // unpublishes and reparses this frame; charging before it would double-count and
            // could report a fallback for a retry that later takes the local lane.
            if (read_local_enabled &&
                read_local_fallback_reason != ReadLocalFallbackReason::None)
                self_->read_local_stats().note_fallback(
                    read_local_fallback_reason, read_local_mget_candidate);
        }
        conn.advance_parse(consumed);
        sig.ops++;
        flip_fingerprint_note(*spec, *op);
        touch_worker(worker_id);
        // Unified pipeline 1 entered with a live active client and its batch tail decides once
        // whether input/backpressure requires another IFID visit. Repeating the same active
        // and queue-dedupe checks for every op was pure per-op work; the other schedules retain
        // their existing mark here.
        if constexpr (!SuppressOrdinaryActiveMark)
            mark_active_known<TargetedIfid>(c);
    }
    if constexpr (!IoPipe) {
        // Item 2: one notify per worker per parse pass, not per op. The pushes above are already
        // visible in the queues; this publishes the "look here" bit and pays the wake decision
        // once. The pipelined schedule deliberately folds the same set across its whole IFID
        // batch and publishes it at IFID.POST.
        for (uint32_t i = 0; i < ntouched_; i++) {
            const uint32_t wkr = touched_list_[i];
            touched_[wkr] = false;
            srv_->thread(wkr).flush_task_notify(self_id, ring_, sig);
        }
        ntouched_ = 0;
    }
    flip_fingerprint_finish_pass();
    return result;
}

bool IoLoop::r7_fused_demote_local_read_batch(Client* client, const uint64_t* probed,
                                   const ReadLocalFallbackReason* fallbacks,
                                   uint32_t probed_count, uint32_t& demoted) {
    if (!r7::shadow_available())
        return fused_demote_local_read_batch(client, probed, fallbacks, probed_count, demoted);

    TOMO_R7_PATH();
    r7_ReadLocalDemotionPlan plan;
    if (!plan.prepare(
            *this, client, 0, false, -1,
            ReadLocalFallbackReason::ContextOwnerKey, false,
            probed, fallbacks, probed_count)) return false;
    demoted = plan.read_count();
    if (!demoted) std::abort();
    plan.commit_reads();
    (void)flush_ifid_posts();
    return true;
}

void IoLoop::run_fused_reordered() {
    if (!fused_executor_) std::abort();
    const bool has_unix = unix_listen_fd_ >= 0 ||
                          (srv_->cfg().unixsocket && *srv_->cfg().unixsocket);
    auto run_pipeline = [&](auto pipeline_tag) {
        constexpr uint8_t Pipeline = decltype(pipeline_tag)::value;
        if (epoll_) {
            if (tls_context_) {
                if (has_unix) r7_run_loop<true, true, true, true, Pipeline>();
                else r7_run_loop<false, true, true, true, Pipeline>();
            } else {
                if (has_unix) r7_run_loop<true, false, true, true, Pipeline>();
                else r7_run_loop<false, false, true, true, Pipeline>();
            }
            return;
        }
        if (tls_context_) {
            if (has_unix) r7_run_loop<true, true, false, true, Pipeline>();
            else r7_run_loop<false, true, false, true, Pipeline>();
        } else {
            if (has_unix) r7_run_loop<true, false, false, true, Pipeline>();
            else r7_run_loop<false, false, false, true, Pipeline>();
        }
    };
    // Reuse O1's ordinary fused outer loop, transport, completion hooks and submit boundary.
    // O6 warms each eligible whole owner batch unconditionally in fused placement;
    // selecting Pipeline 0 here must not turn off that independent executor mechanism.
    run_pipeline(std::integral_constant<uint8_t, 0>{});
}

namespace {
void pin_fused_thread(int cpu) {
    if (cpu < 0) return;
    cpu_set_t set;
    CPU_ZERO(&set);
    CPU_SET(cpu, &set);
    pthread_setaffinity_np(pthread_self(), sizeof(set), &set);
}
}

static int run_fused_server_reordered(Server& srv, const SnapshotLoadPlan* aof_base_plan,
                     const std::vector<std::unique_ptr<AofReplayPlan>>& aof_plans,
                     const SnapshotLoadPlan* load_plan, TlsContext* tls_context,
                     LateUnixListener& unix_listener,
                     ShutdownReportFinalLine& final_report) {
    const Config& cfg = srv.cfg();
    const uint32_t nthreads = srv.nthreads();
    std::printf("tomokv-cpp: %u unified threads, %u shard(s), thread-mode=1s,"
                " overlap=%u (executor prefetch; ordinary IO), %s, alloc=%s\n", nthreads, cfg.shards,
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
            DatabaseMap::WorkerLifetime database_worker(srv.databases(), tid);
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
                executors[tid].bind_fused_completion(
                    &ios[tid],
                    [](void* p, Client* client) {
                        static_cast<IoLoop*>(p)->fused_executor_completion<false>(client);
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
                self.bind_fused_executor_hooks(
                    &executors[tid],
                    [](void* p) {
                        return static_cast<FusedExLoop*>(p)->fused_baseline_pass();
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
        srv.databases().join_workers(srv, pool);
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
    if (!unix_listener.open(cfg.tcp_backlog, unix_error, cfg.unixsocketperm)) {
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

    srv.databases().join_workers(srv, pool);
    // The unix socket file is unlinked by its RAII owner in main, for every return path.
    report_graceful_shutdown();
    return 0;
}
// END R7 GENERATED ENVELOPES

void IoLoop::run_split_read_local() {
    // ExLoopT<true> is also the split read-local executor; it does not imply 1s.
    return run_split_read_local_baseline();
}

int run_fused_server_selected(Server& srv, const SnapshotLoadPlan* aof_base_plan,
                     const std::vector<std::unique_ptr<AofReplayPlan>>& aof_plans,
                     const SnapshotLoadPlan* load_plan, TlsContext* tls_context,
                     LateUnixListener& unix_listener,
                     ShutdownReportFinalLine& final_report) {
    // One boot choice. The original fused TU sees no R7 bodies, callbacks, or selectors;
    // even a callback-only choice there changes its unit-wide inlining budget.
    if (srv.cfg().reorder)
        return run_fused_server_reordered(srv, aof_base_plan, aof_plans, load_plan,
                                          tls_context, unix_listener, final_report);
    return run_fused_server(srv, aof_base_plan, aof_plans, load_plan,
                            tls_context, unix_listener, final_report);
}
} // namespace tomo
