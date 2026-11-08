// Executor scheduling, shard maintenance, local reads, and completion notification.
// Included by the runtime TUs (main.cc, genthread.cc, rl2s.cc, reorder.cc) and through io_loop.h;
// latency_tracking.cc also supplies cold member definitions. ex_execute.inc supplies task bodies
// and ex_txn_chain.inc supplies transaction retry members at fixed points inside ExLoopT.
//
// Each active executor alone writes its owned shards. Routing is rechecked before store access,
// and no owner work follows an ExDrain acknowledgement until ownership is installed. Read-local
// captures stay within a QSBR rotation and use copy/validate/demote without reader retries.
// Release Done publishes replies to the connection's IO owner, which retires and sends them.
// Ready masks are hints: idle sweeps inspect queue state before the blocked-flag/recheck/wait
// handshake. The executor ring carries wakeups and persistence work, not socket sends.
#pragma once
#include "../cmd/txn_retry_queue.h"
#include "atomic_parked.h"
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

// Bound empty polling before the mask-independent sweep and blocked-flag handshake.
inline constexpr uint32_t kExSpinBudget = 2048;

// How many ops are gathered before executing, so their storage prefetches can overlap. Large enough
// that the prefetches have time to land, small enough that the batch stays in L1.
inline constexpr uint32_t kExecBatch = kGenthreadExBatchOps;
inline constexpr uint32_t kReadLocalPrefetchKeys = 32;
inline constexpr uint32_t kActiveExpireChecks = 20;
// The armed coarse rotation alternates these two equal quanta. One owner quantum per captured
// producer bounds the stretch before WB by active producers rather than by queued depth, while the
// local quantum matches the most one parse invocation can append for a connection.
inline constexpr uint32_t kReadLocalDrainChunkOps = kGenthreadIfidBatchOps;
inline constexpr uint32_t kReadLocalOwnerTaskChunkOps = kGenthreadExBatchOps;
// Parser-side demotion may reserve one additional point command behind the entire local run.
// Leave that credit outside the pending-read fanout budget so the combined reservation can always
// fit an empty producer lane and therefore cannot retry forever.
inline constexpr uint32_t kReadLocalDemotionBudget = kInboxSlots - 1;
// Lane ADMISSION pressure window. A LANE-FULL deferral arms this many fused rotations
// during which the parser bounds every connection to kInboxSlots / active connections in flight.
// It decays by one per rotation and is re-armed only by the next lane-full event -- never by the
// quota's own deferrals (the actuator must not police itself) -- so under sustained oversubscription
// one rotation in (this + 1) lets the lane prove the pressure again, and once aggregate demand has
// stayed under the lane for this many rotations the bound is UINT32_MAX and the steady state pays
// one predicted byte test per parse pass and nothing per op.
inline constexpr uint8_t kReadLocalLanePressureRotations = 8;
static_assert(kExecBatch <= UINT8_MAX);
static_assert(kExecBatch <= 32);
static_assert(kGenthreadIfidBatchOps <= kExecBatch);
static_assert(kReadLocalDrainChunkOps == kExecBatch);
static_assert(kReadLocalOwnerTaskChunkOps == kExecBatch);
static_assert((kExecBatch & (kExecBatch - 1)) == 0);

// Contract: the shard owner borrows a store for one declared-key-precise write when read-local
// is armed. Suspend eviction but keep maxmemory admission: the operation updates only its declared
// keys or fails, and cannot evict behind a younger local read. Destruction restores the policy
// before the next task. No ownership transfer or cross-thread publication occurs.
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

// The false specialization owns no storage. The true specialization owns optional per-thread
// lane/reclamation state; only its physical thread may access the implementation.
template <bool Enabled>
struct ReadLocalExState;

template <>
struct ReadLocalExState<false> {};

// Contract: init creates Impl only when read-local is enabled. The owning thread destroys it
// after lane/reclamation shutdown; disabled operation allocates nothing. Server, ThreadCtx and
// demotion context are borrowed. This wrapper provides no cross-thread synchronization.
template <>
struct ReadLocalExState<true> {
    // Owns the bounded lane, fallback array and deferred reclamation queue. The local parser
    // enqueues ROB handles and the same thread drains them. Demotion credits bound worst-case
    // owner fanout; raw callbacks/Client handles stay live until completion or demotion. Shard
    // retire sinks must follow ownership before this thread accesses a moved store.
    struct Impl {
        using DemoteFn = bool (*)(void*, Client*, const uint64_t*, const ReadLocalFallbackReason*,
                                  uint32_t, uint32_t&);

        // Borrowed ROB handle, valid until local completion/demotion removes it. A 16-byte
        // entry needs no shard/scatter fields; demotion builds owner Tasks from the op id.
        struct LaneEntry {
            Client* client;
            uint64_t op_id;
        };
        static_assert(sizeof(LaneEntry) == 16);

        std::unique_ptr<LaneEntry[]> lane;
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
        // Rotations left in the lane-admission pressure window; see kReadLocalLanePressureRotations.
        uint8_t lane_pressure = 0;
        bool lane_has_tombstones = false;
        bool point_writes_precise = true;
        bool keymiss_notify_armed = false;
        uint8_t reserved_schedule[2] = {};  // preserve the demotion-state offsets
        // Admission limit only: physical storage and index masking remain kInboxSlots. The
        // default is kInboxSlots; each rotation adopts any DEBUG READ-LOCAL-LANE-CAP override.
        // This uint16 shares the first cache line with the lane cursors (offset 38), so admission
        // reads no additional line. A reduced cap lets a test fill the lane in one parse pass,
        // before draining races it; lowering the cap cannot overrun physical storage.
        uint16_t lane_admit_cap = static_cast<uint16_t>(kInboxSlots);
        void* demote_context = nullptr;
        DemoteFn demote = nullptr;
        ReadLocalDeferredQueue deferred;

        void rebind_owned_shards(ThreadCtx& owner) {
            ReadLocalRetireSink* sink = deferred.sink();
            if (!sink) std::abort();
            for (Shard* shard : owner.shards()) shard->store().rebind_read_local_retire_sink(*sink);
        }
    };

    std::unique_ptr<Impl> impl;
};

using ReadLocalExImpl = ReadLocalExState<true>::Impl;
static_assert(std::is_empty_v<ReadLocalExState<false>>);

// Stack-only captures borrow immutable objects and table words within the current QSBR
// rotation. Consumers validate before completing; no captured pointer may escape the rotation.
template <uint32_t Capacity>
struct ReadLocalCaptureBuffer {
    FlatStore::ReadLocalPrefetchCapture entries[Capacity];
};

// Contract: one physical thread owns the ring, retry queues, caches and optional local-read
// lane. Server/ThreadCtx and queued Client/ROB handles are borrowed; their lifetimes must cover
// all pending work. Fused=false serves split owners. Fused=true supports fused owners and the
// split read-local runtime: its IO tenure must not service shards. Init precedes activation;
// placement acknowledgements delimit every shard/vector access. Task queues publish across
// threads; reply completion uses release Done and a fenced notification. Refused posts retain
// work for later passes, never spin in place or drop it. Init reports resource failure; invalid
// ownership/accounting aborts, and allocation failures are handled only where explicitly caught.
// Path-bound/generated methods and their definition order are part of the source-tool interface.
template <bool Fused>
class /* TOMO_TOOL_BIND ExLoopT */ ExLoopT {
public:
    using FusedCompletionFn = void (*)(void*, Client*);

    // Bind the pinned physical thread's executor before entering its loop. Optional local-read
    // allocation, ring initialization or database-wake registration can return false. Earlier
    // bindings may already exist on failure; this is not a transactional initializer. A dormant
    // executor waits for explicit activation before publishing its ring as the thread endpoint.
    bool init(Server* srv, ThreadCtx* self, bool dormant = false) {
        srv_ = srv;
        self_ = self;
        srv_->bind_owner_notify_pending(self_->id(), &notify_keyless_pending_);
        aof_manager_ = srv->aof().configured() ? &srv->aof() : nullptr;
        cfgfix_register_executor(srv, self->id(), this, [](void* opaque, int action) {
            auto& loop = *static_cast<ExLoopT*>(opaque);
            if (action == 2) {
                loop.aof_flush_pass();
                for (Shard* shard : loop.self_->shards())
                    if (shard->store().aof().has_pending()) return false;
                return !loop.srv_->aof().completions_pending(loop.self_->id());
            }
            loop.aof_manager_ = action == 1 ? &loop.srv_->aof() : nullptr;
            return true;
        });
        // Multiplication by an odd word is injective modulo 2^64. Every thread
        // therefore starts at a distinct nonzero xorshift state, including 0.
        foreign_touch_random_ = (static_cast<uint64_t>(self->id()) + 1) * 0x9e3779b97f4a7c15ULL;
        lb_sample_rate_ = srv->key_lb_signals_enabled() ? srv->lb_sample_rate() : 0;
        lb_sample_countdown_ = lb_sample_rate_;
        lb_controller_armed_ = srv->key_lb_signals_enabled();
        age_sample_rate_cached_ = srv->effective_age_sample_rate();
        if constexpr (Fused) {
            if (srv->read_local_enabled()) {
                std::unique_ptr<ReadLocalExImpl> impl(new (std::nothrow) ReadLocalExImpl);
                if (!impl) return false;
                impl->lane.reset(new (std::nothrow) ReadLocalExImpl::LaneEntry[kInboxSlots]);
                impl->lane_fallbacks.reset(new (std::nothrow) ReadLocalFallbackReason[kInboxSlots]);
                if (!impl->lane || !impl->lane_fallbacks || !impl->deferred.init(srv, self))
                    return false;
                impl->point_writes_precise =
                    srv->cfg().maxmemory == 0 ||
                    srv->cfg().maxmemory_policy == MaxmemoryPolicy::NoEviction;
                read_local_.impl = std::move(impl);
            }
        }
        if constexpr (Fused) {
            if (srv_->thread_mode() == ThreadMode::Fused) ring_.track_owned_completions();
        }
        if (!ring_.init(1024)) return false;
        ring_.bind_entry_counters(self_->id(), true);
        if (!srv_->databases().watch_wake(self_->id(), ring_)) return false;
        initialized_ = true;
        if (!dormant) activate();
        return true;
    }

    void activate() {
        if (!initialized_) std::abort();
        self_->set_ring(&ring_);
        self_->set_wb_engine(nullptr);
        blocking_bind_executor(srv_, self_, &ring_);
        for (Shard* shard : self_->shards()) shard->bind_notify_pending(&notify_keyless_pending_);
    }

    // Fused tenure shares the physical thread with IoLoop. IoLoop remains the published wake
    // endpoint because it owns the only blocking wait; this ring still carries persistence CQEs.
    void activate_fused() {
        static_assert(Fused);
        if (!initialized_) std::abort();
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

    // The armed parser is the only producer and calls this immediately after its own
    // local_read_lane_has_room(demand) verdict on the same op, with nothing that can consume lane
    // room in between (only demand releases can run there). It already holds the Op, its MGET
    // classification and its demotion demand, so this is the four lane stores and nothing else.
    __attribute__((always_inline)) void enqueue_local_read(Client* client, uint64_t op_id,
                                                           uint32_t demand) {
        static_assert(Fused);
        auto& state = *read_local_.impl;
        state.lane[state.lane_tail] = {client, op_id};
        state.lane_fallbacks[state.lane_tail] = ReadLocalFallbackReason::None;
        state.lane_tail = (state.lane_tail + 1) & (kInboxSlots - 1);
        state.lane_count++;
        state.lane_demotion_demand += demand;
    }

    bool local_read_lane_has_room(uint32_t demotion_demand = 1) const {
        static_assert(Fused);
        if (!read_local_enabled()) return false;
        const auto& state = read_local_impl();
        // `<` rather than `!=` because lane_admit_cap may be below the ring size under a test
        // cap; with the production value (kInboxSlots) the two are identical, since lane_count is
        // never allowed past it.
        return state.lane_count < state.lane_admit_cap &&
               demotion_demand <= kReadLocalDemotionBudget - state.lane_demotion_demand;
    }

    // LANE ADMISSION. The parser asks once per parse pass how many lane slots (pending
    // local reads) one connection may hold. Unbounded while the lane is not under pressure -- below
    // kInboxSlots of aggregate demand per rotation. Under pressure it is the lane divided among the
    // connections competing for it, which by construction keeps the sum of admitted local reads
    // within the lane, so the lane-full deferral -- whose victims are whichever connections the
    // rotation parsed last -- stops firing and every connection progresses every rotation. Both
    // terms self-derive: live connections from the active set, observed depth from the lane-full
    // events that arm the window. No knob.
    uint32_t read_local_lane_quota(size_t live_connections) const {
        static_assert(Fused);
        // Same disabled-state shape as local_read_lane_has_room(): no impl means no lane and no
        // bound (the parser only asks when the server's read-local is on, which is what creates
        // the impl at init; this is the one test that call already paid, not a second one).
        if (!read_local_enabled()) return UINT32_MAX;
        const auto& state = *read_local_.impl;
        if (__builtin_expect(state.lane_pressure == 0, true)) return UINT32_MAX;
        return std::max<uint32_t>(
            1, state.lane_admit_cap / static_cast<uint32_t>(std::max<size_t>(1, live_connections)));
    }

    // Parser-side pressure hint on the same first cache line as lane cursors/demotion demand.
    // Test it before evaluating read_local_lane_quota(active_.size()): C++ eagerly evaluates
    // arguments, so testing only inside quota would load the separate active-set line even when
    // pressure is off. The hint changes admission fairness, not correctness. Cache observations
    // motivating the argument gate are archived in docs/decisions/readability-a6.md.
    bool read_local_lane_under_pressure() const {
        static_assert(Fused);
        if (!read_local_enabled()) return false;
        return read_local_.impl->lane_pressure != 0;
    }

    // A lane-full deferral arms the pressure window; fused_pass_impl decays it once per rotation.
    void note_local_read_lane_full() {
        static_assert(Fused);
        if (!read_local_enabled()) return;
        read_local_.impl->lane_pressure = kReadLocalLanePressureRotations;
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
        if (!read_local_enabled() || !client || reason == ReadLocalFallbackReason::None)
            std::abort();
        auto& lane = read_local_impl();
        for (uint32_t offset = 0; offset < lane.lane_count; offset++) {
            const uint32_t index = (lane.lane_head + offset) & (kInboxSlots - 1);
            const auto& task = lane.lane[index];
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

    /* TOMO_TOOL_FUNCTION fused_baseline_pass */
    uint32_t /* TOMO_TOOL_BIND fused_baseline_pass */ fused_baseline_pass() {
        static_assert(Fused);
        if (srv_->thread_mode() == ThreadMode::Split) return split_read_local_pass();
        if (read_local_enabled()) return fused_pass_impl<kGenthreadExBatchOps, true, false, true>();
        return fused_pass_impl<kGenthreadExBatchOps, true>();
    }

#include "fused_owner_turn.inc"

    // Contract: run one owner turn on the fused physical thread. ConsumeTasks selects inbox
    // service; IofusedPrivateQueue selects fixed fused lanes; InterleaveLocalReads alternates
    // bounded local/owner chunks. Require initialized callbacks and stable ownership until the
    // control tail. Captures die before the seq_cst QSBR tick at scope exit. Retry/forward/AOF
    // queues retain blocked work; return value is work/needed polling, not completed replies.
    // ExDrain skips shard work after acknowledgement, and this turn never blocks on the ring.
    /* TOMO_TOOL_FUNCTION fused_pass_impl */
    template <uint32_t BatchOps, bool ConsumeTasks, bool IofusedPrivateQueue = false,
              bool InterleaveLocalReads = false>
    uint32_t /* TOMO_TOOL_BIND fused_pass_impl */ fused_pass_impl() {
        // Phase 1: bind the rotation lifetime, refresh clocks, and check ownership barriers.
        ++exec1s_counters[self_->id()].owner_passes;
        Server::ClientWorkScope client_work(*srv_, self_->id());
        // Borrows this thread/server until scope exit and seq_cst-publishes quiescence only
        // after nested drains have consumed every foreign capture; no Client lifetime is owned.
        struct RotationBoundary {
            bool enabled;
            ThreadCtx* self;
            Server* server;
            ~RotationBoundary() {
                if (enabled) self->publish_read_local_tick(server->read_local_epoch());
            }
        } rotation_boundary{read_local_enabled(), self_, srv_};
        cached_now_ms_ = realtime_ms();
        // LB can change this owner's shard vector. Retirement sinks must follow that ownership
        // before any work. Server::adopt_read_local_retire_sink binds at the ownership edge;
        // this pass reaffirms the binding. lb_control_pass also rebinds notification sinks.
        if (lb_rebind_pending_ && srv_->lb_stage() != LbStage::ExDrain)
            read_local_rebind_owned_shards_after_lb();
#ifdef TOMO_RL_CACHE_DEBUG
        if constexpr (Fused)
            if (read_local_enabled())
                srv_->debug_assert_read_local_sinks_follow_ownership(self_->id());
#endif
        const bool lb_frozen = lb_controller_armed_ && srv_->lb_stage() == LbStage::ExDrain;
        if (!lb_frozen) refresh_live_config();
        if (maxmemory_enabled_)
            cached_lru_clock_ = static_cast<uint8_t>(
                (static_cast<uint64_t>(cached_now_ms_ / 1000) >> kLruClockShift) & 0x1f);

        [[maybe_unused]] bool owner_work_remains = false;
        bool fairlane_turn = false;
        if constexpr (InterleaveLocalReads) {
            static_assert(Fused && ConsumeTasks);
            static_assert(BatchOps == kReadLocalOwnerTaskChunkOps);
            if (!read_local_enabled()) std::abort();
            // Retry, migration and snapshot debt keep their required order. Only a turn free
            // of that debt caps fresh owner work before writeback.
            fairlane_turn = !lb_frozen && !fairlane_owner_debt_pending();
            if (fairlane_turn) {
                compact_local_read_tombstones();
                fairlane_turn = read_local_impl().lane_count != 0;
            }
        }
        // Phase 2: drain local captures, then service frozen or runnable owner work in order.
        uint32_t did = 0;
        if (fairlane_turn) {
            // EARLY: reads parsed by the preceding IFID phase get the first execution/reply slots.
            did += drain_local_reads_bounded(kReadLocalDrainChunkOps);
        } else {
            // Consume every local capture before owner work or the rotation's QSBR tick.
            did += drain_local_reads();
        }
        if (lb_frozen) {
            if (!srv_->lb_acked(self_->id())) {
                did += service_stale_forwards<BatchOps, IofusedPrivateQueue>();
                did += drain_releases(true);
                if (__builtin_expect(notify_retries_pending(), false))
                    did += service_notify_retries();
                did += service_multi_retries<IofusedPrivateQueue>();
                did += service_atomic_deferred<IofusedPrivateQueue>();
                did += service_xshard_retries<IofusedPrivateQueue>();
                if (xshard_retries_.empty())
                    did += service_ordered_deferred<BatchOps, IofusedPrivateQueue>();
                if constexpr (ConsumeTasks)
                    if (xshard_retries_.empty() && ordered_deferred_.empty()) {
                        did +=
                            /* TOMO_TOOL_BIND drain_tasks */ drain_tasks<BatchOps,
                                                                         IofusedPrivateQueue>(true);
                    }
                flush_xshard_commits();
                did += aof_flush_pass();
                did += drain_notify_keyless(self_->sig());
            }
            did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
            did += lb_control_pass();
        } else {
            did += snapshot_control_pass<BatchOps, IofusedPrivateQueue>();
            did += service_stale_forwards<BatchOps, IofusedPrivateQueue>();
            did += drain_releases();
            if (__builtin_expect(notify_retries_pending(), false)) did += service_notify_retries();
            if (!snapshot_blocks_tasks()) {
                did += service_multi_retries<IofusedPrivateQueue>();
                did += service_atomic_deferred<IofusedPrivateQueue>();
                did += service_xshard_retries<IofusedPrivateQueue>();
                if (xshard_retries_.empty())
                    did += service_ordered_deferred<BatchOps, IofusedPrivateQueue>();
                if constexpr (ConsumeTasks)
                    if (xshard_retries_.empty() && ordered_deferred_.empty()) {
                        if (snapshot_owner_state_ == SnapshotOwnerState::None) {
                            if (fairlane_turn)
                                did += /* TOMO_TOOL_BIND drain_tasks_read_local_interleaved */
                                    drain_tasks_read_local_interleaved<IofusedPrivateQueue>(
                                        false, owner_work_remains);
                            else
                                did += drain_tasks<BatchOps, IofusedPrivateQueue>();
                        } else {
                            did += drain_tasks_snapshot<BatchOps, IofusedPrivateQueue>();
                        }
                    }
            }
            flush_xshard_commits();
            if (__builtin_expect(srv_->blocking_waiters() != 0, false) &&
                !shutdown_snapshot_blocks_tasks() && cached_now_ms_ >= blocking_beat_ms_) {
                did += blocking_owner_cycle(*srv_, *self_, ring_, cached_now_ms_, true);
                blocking_beat_ms_ = cached_now_ms_ + 10;
            }
            did += aof_flush_pass();
            did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
        }
        // Phase 3: finish local tails and reclamation before acknowledging control work.
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
            // Adopt the debug cap with one relaxed load per rotation, storing only on change.
            // Admission reads the thread-local uint16. Zero derives the physical lane capacity.
            const uint32_t cap = srv_->debug_read_local_lane_cap();
            const uint16_t want = cap == 0
                                      ? static_cast<uint16_t>(kInboxSlots)
                                      : static_cast<uint16_t>(std::min<uint32_t>(cap, kInboxSlots));
            if (__builtin_expect(read_local_impl().lane_admit_cap != want, false))
                read_local_impl().lane_admit_cap = want;
        }
        if (!lb_frozen) did += owner_control_tail();
        // Incoming deferred task work and outstanding IO do not require any
        // owner task to have progressed first. Keep the fused loop active until
        // those CQEs can be reaped on its next pass.
        if (ring_.completion_service_needed()) {
            ring_.submit_and_reap();
            ++did;
        }
        // Phase 4: account for progress, then audit queue state after bounded idle spinning.
        if (did) {
            fused_idle_spins_ = 0;
            return did;
        }
        if constexpr (!ConsumeTasks) return 0;
        if (lb_frozen) return 0;
        if (++fused_idle_spins_ < kExSpinBudget) return 0;
        fused_idle_spins_ = 0;
        if constexpr (InterleaveLocalReads) {
            did = fairlane_turn ? sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue, true>()
                                : sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
        } else {
            did = sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
        }
        if (ring_.completion_service_needed()) {
            ring_.submit_and_reap();
            ++did;
        }
        return did;
    }

    /* TOMO_TOOL_FUNCTION fused_baseline_sweep */
    uint32_t /* TOMO_TOOL_BIND fused_baseline_sweep */ fused_baseline_sweep() {
        static_assert(Fused);
        if (srv_->thread_mode() == ThreadMode::Split) return split_read_local_pass();
        if (read_local_enabled())
            return fused_sweep_impl<kGenthreadExBatchOps, true, false, true>();
        return fused_sweep_impl<kGenthreadExBatchOps, true>();
    }

    // Fused-thread idle audit: drain captures and queue state under one QSBR rotation. A paused
    // LB stage delegates to the ordinary pass, which respects ExDrain. Interleaving is legal only
    // with an armed lane; pending persistence work keeps the caller active. Does not wait.
    /* TOMO_TOOL_FUNCTION fused_sweep_impl */
    template <uint32_t BatchOps, bool ConsumeTasks, bool IofusedPrivateQueue = false,
              bool InterleaveLocalReads = false>
    uint32_t /* TOMO_TOOL_BIND fused_sweep_impl */ fused_sweep_impl() {
        ++exec1s_counters[self_->id()].owner_passes;
        if (lb_controller_armed_ && srv_->lb_dispatch_paused())
            return fused_pass_impl<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
        // Borrows this thread/server until scope exit and seq_cst-publishes quiescence only
        // after nested drains have consumed every foreign capture; no Client lifetime is owned.
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
                did += drain_local_reads() + sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
            } else {
                compact_local_read_tombstones();
                if (read_local_impl().lane_count) {
                    did += drain_local_reads_bounded(kReadLocalDrainChunkOps);
                    did += sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue, true>();
                } else {
                    did += sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
                }
            }
        } else {
            did += drain_local_reads() + sweep<BatchOps, ConsumeTasks, IofusedPrivateQueue>();
        }
        if (read_local_enabled()) did += read_local_impl().deferred.drain_ready();
        if (ring_.completion_service_needed()) {
            ring_.submit_and_reap();
            ++did;
        }
        return did;
    }

    void fused_snapshot_start(SnapshotManager* manager) {
        static_assert(Fused);
        begin_snapshot(manager);
    }

    Ring& ring() { return ring_; }

    // Defined with the split read-local runtime in rl2s.cc. The IO role never services owner
    // tasks or shard housekeeping, even while FLIP installs its future EX shard vector.
    uint32_t split_read_local_pass();

    // Contract: the pinned thread runs its active EX tenure until stop or role change. Require
    // successful init/activation and, for a fused-capable split owner, an empty local-read lane.
    // Owns queue draining, shard maintenance, ring submission and blocked-flag publication;
    // DatabaseWorkScope brackets database-map access. No store/vector access follows ExDrain
    // acknowledgement. Refused work remains queued, idle sweeps ignore hints, and parking uses
    // arm/recheck/wait so a racing producer cannot strand work. Completion is release-published
    // by task paths; this loop sends no replies and reports no recoverable loop-level error.
    void /* TOMO_TOOL_BIND run */ run() {
        // Phase 1: bind owner-only configuration hooks and initialize role-tenure state.
        const MemoryConfigBinding memory_config_binding(this);
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
        Server::DebugSleepWorker sleep_worker(srv_->debug_sleep_coordinator(), self_->id());

        while (!self_->stop_flag().load(std::memory_order_relaxed) && self_->role() == Role::Ex) {
            srv_->debug_sleep_poll(self_->id());
            Server::DatabaseWorkScope database_work(*srv_, self_->id());
#ifdef TOMO_MDBQSBR_TEST
            if (DatabaseMapTestHooks::loop_pass) {
                DatabaseMapTestHooks::loop_pass(*srv_, *self_, 2);
                continue;
            }
#endif
#ifdef TOMO_RL_CACHE_DEBUG
            if constexpr (Fused) srv_->debug_assert_read_local_sinks_follow_ownership(self_->id());
#endif
            // Phase 2: sample placement barriers before touching owned shard state.
            const bool flip_frozen = srv_->flip_stage() >= FlipStage::ExDrain;
            const bool lb_frozen = lb_controller_armed_ && srv_->lb_stage() == LbStage::ExDrain;
            const bool placement_frozen = flip_frozen || lb_frozen;
            // refresh_live_config() walks this owner's shard vector. The coordinator may rewrite
            // those vectors after ExDrain acknowledgement, so a frozen executor must not even run
            // the otherwise-cold configuration refresh path.
            if (!placement_frozen) refresh_live_config();
            sig.iterations++;
            ++exec1s_counters[self_->id()].owner_passes;

            uint32_t did = 0;
            uint64_t pass_ns = 0;
            {
                Server::ClientWorkScope client_work(*srv_, self_->id());
                Span busy(pass_ns);
                if (self_->sample_depth(busy.start_ns() / 1000)) {
                    // Same 100us diagnostic beat as IO; the CPU clock can be a
                    // syscall. Keep it out of ordinary passes and reply submission.
                    sig.cpu_ns = thread_cpu_ns();
                    const uint32_t age_rate = srv_->effective_age_sample_rate();
                    if (age_rate != age_sample_rate_cached_) {
                        age_sample_rate_cached_ = age_rate;
                        self_->sig().configure_age_sampling(age_rate);
                    }
                }
                // The pass clock serves deferred work, local reads and housekeeping.
                // Fresh inbox batches re-cut after dequeue: even a vDSO read can be
                // followed by preemption before a newly arrived request is popped.
                cached_now_ms_ = realtime_ms();
                if (maxmemory_enabled_)
                    cached_lru_clock_ = static_cast<uint8_t>(
                        (static_cast<uint64_t>(cached_now_ms_ / 1000) >> kLruClockShift) & 0x1f);
                // Phase 3: drain prerequisite debt, then tasks and maintenance if permitted.
                if (placement_frozen) {
                    // Once ExDrain is acknowledged this loop is a hard safe point: no expiry,
                    // cleanup, waiter walk, or task can reacquire a moved FlatStore before FLIP
                    // publishes ExInstall. The coordinator may rewrite owner entries immediately
                    // after observing the acknowledgement.
                    const bool acknowledged =
                        flip_frozen ? srv_->flip_acked(self_->id(), FlipStage::ExDrain)
                                    : srv_->lb_acked(self_->id());
                    if (!acknowledged) {
                        did += service_stale_forwards();
                        did += drain_releases(true);
                        if (__builtin_expect(notify_retries_pending(), false))
                            did += service_notify_retries();
                        did += service_multi_retries();
                        did += service_atomic_deferred();
                        did += service_xshard_retries();
                        if (xshard_retries_.empty()) did += service_ordered_deferred();
                        if (xshard_retries_.empty() && ordered_deferred_.empty())
                            did += drain_tasks(true);
                        flush_xshard_commits();
                        did += aof_flush_pass();
                        did += drain_notify_keyless(sig);
                        if constexpr (Fused) did += read_local_impl().deferred.drain_ready();
                    }
                    did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
                    did += lb_control_pass();
                    did += flip_control_pass();
                } else {
                    did += snapshot_control_pass();
                    did += service_stale_forwards();
                    did += drain_releases();
                    if (__builtin_expect(notify_retries_pending(), false))
                        did += service_notify_retries();
                    if (!snapshot_blocks_tasks()) {
                        did += service_multi_retries();
                        did += service_atomic_deferred();
                        did += service_xshard_retries();
                        if (xshard_retries_.empty()) did += service_ordered_deferred();
                        if (xshard_retries_.empty() && ordered_deferred_.empty())
                            did += snapshot_owner_state_ == SnapshotOwnerState::None
                                       ? drain_tasks()
                                       : drain_tasks_snapshot();
                    }
                    flush_xshard_commits();
                    if (__builtin_expect(srv_->blocking_waiters() != 0, false) &&
                        !shutdown_snapshot_blocks_tasks() && cached_now_ms_ >= blocking_beat_ms_) {
                        did += blocking_owner_cycle(*srv_, *self_, ring_, cached_now_ms_, true);
                        blocking_beat_ms_ = cached_now_ms_ + 10;
                    }
                    did += aof_flush_pass();
                    did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
                    if constexpr (Fused) did += read_local_impl().deferred.drain_ready();
                    did += owner_control_tail();
                }
            }
            // Phase 4: charge empty polling to idle time, then submit prepared ring work.
            // FLIP derives demand from role busy shares; counting empty spin passes as busy
            // would make the idle-spin budget look like executor demand.
            if (did)
                sig.busy_ns += pass_ns;
            else
                sig.idle_ns += pass_ns;

            // Flush prepared SQEs before looping. Recv re-arms and cross-ring wakes are
            // PREPARED during the work section but only reach the kernel on submit; taking
            // the busy path without submitting strands them in the SQ forever, and the peer
            // that is waiting on that wake never runs.
            if (did) {
                ring_.submit_and_reap();
                idle_spins = 0;
                continue;
            }

            // Phase 5: respect the frozen safe point or audit all queues before parking.
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
                database_work.park();
                ring_.submit_and_wait(1, kParkNetMs, srv_->databases().wake_fd(self_->id()));
                database_work.resume();
                if (ring_.wake_fd() >= 0) srv_->databases().consume_wake(self_->id(), ring_);
                self_->clear_blocked();
                continue;
            }

            if (++idle_spins < kExSpinBudget) {
                sig.spins++;
                __builtin_ia32_pause();
                continue;
            }
            idle_spins = 0;

            // Mask-independent sweep before parking. The mask is a hint for the hot path; it must
            // not be the only thing that can find queued work, or one lost bit wedges a connection
            // forever. Runs only when this thread has already concluded it has nothing to do.
            if (sweep()) {
                ring_.submit_and_reap();
                continue;
            }

            Span idle(sig.idle_ns);
            self_->arm_blocked();
            // A producer that marks one of this owner's shards dirty just before arm_blocked
            // may have lost its conditional wake. Re-check after the seq_cst fence; a set flag
            // means service it now, not at the 50 ms timeout. Cold: gated on a blocked client.
            const bool blocking_owed = __builtin_expect(srv_->blocking_waiters() != 0, false) &&
                                       blocking_owner_dirty_pending(*self_);
            if (!blocking_owed && !self_->any_ex_inbound()) {
                database_work.park();
                ring_.submit_and_wait(1, kParkNetMs, srv_->databases().wake_fd(self_->id()));
                database_work.resume();
                if (ring_.wake_fd() >= 0) srv_->databases().consume_wake(self_->id(), ring_);
            } else
                ring_.submit_and_reap();
            self_->clear_blocked();
        }
    }

private:
    friend class IoLoop;
    friend struct CoreConcurrencyTest;
    friend struct TxnChainTest;
#ifdef TOMO_CORE_CONCURRENCY_TEST
    inline static void (*test_after_done_)(Client*) = nullptr;
    inline static void (*test_after_drain_ack_)() = nullptr;
    // Test seam between sampling the control stage and testing its first action.
    inline static void (*test_after_stage_sample_)(uint32_t, FlipStage) = nullptr;
    inline static bool test_live_epoch_ack_test_ = false;
    inline static void (*test_local_read_copied_)() = nullptr;
    inline static uint32_t test_local_get_reply_attempts_ = 0;
#endif

    bool read_local_enabled() const {
        if constexpr (Fused) return read_local_.impl != nullptr;
        return false;
    }

    bool fairlane_owner_debt_pending() const {
        return srv_->flip_dispatch_paused() ||
               (lb_controller_armed_ && srv_->lb_dispatch_paused()) ||
               snapshot_owner_state_ != SnapshotOwnerState::None || !stale_tasks_.empty() ||
               !stale_releases_.empty() || !multi_retries_.empty() || !atomic_deferred_.empty() ||
               !xshard_retries_.empty() || !ordered_deferred_.empty();
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

    bool read_local_point_writes_precise() const { return read_local_impl().point_writes_precise; }

    void set_read_local_point_writes_precise(bool precise) {
        read_local_impl().point_writes_precise = precise;
    }

    void read_local_rebind_owned_shards_after_lb() {
        if constexpr (Fused) {
            if (read_local_.impl) read_local_.impl->rebind_owned_shards(*self_);
        }
    }

    Ring& handoff_ring() { return ring_; }

    void read_local_clear_reply(Op& op) {
        op.clear_reply();  // bytes AND the reply code
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
            const uint32_t from = (state.lane_head + offset) & (kInboxSlots - 1);
            const ReadLocalExImpl::LaneEntry task = state.lane[from];
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

    bool demote_local_read_batch(Client* client, const uint64_t* probed,
                                 const ReadLocalFallbackReason* fallbacks, uint32_t probed_count,
                                 uint32_t& demoted) {
        static_assert(Fused);
        auto& lane = read_local_impl();
        if (!lane.demote || !lane.demote_context) std::abort();
        return lane.demote(lane.demote_context, client, probed, fallbacks, probed_count, demoted);
    }

    // Value-only result of one local attempt. Reply bytes remain private in Op until the caller
    // commits a successful prefix; fallback carries no borrowed object/table pointer.
    struct PreparedLocalRead {
        ReadLocalFallbackReason fallback = ReadLocalFallbackReason::None;
        uint32_t keyspace_hits = 0;
        uint32_t keyspace_misses = 0;
    };

    static bool read_local_mget(const Op& op) {
        return op.spec && command_is_read_local_mget(*op.spec);
    }

    static void read_local_reply_string(Op& op, const KvObj* object, uint8_t stable_flags) {
        reply_bulk(op.sink(), object->read_local_str_value(stable_flags));
    }

    uint32_t read_local_task_demotion_demand(const Op& op) const {
        if (!op.read_local()) std::abort();
        return read_local_mget(op) ? std::min<uint32_t>(op.argc() - 1, srv_->nshards()) : 1;
    }

    void release_local_read_demotion_demand(const Op& op) {
        auto& lane = read_local_impl();
        const uint32_t demand = read_local_task_demotion_demand(op);
        if (demand > lane.lane_demotion_demand) std::abort();
        lane.lane_demotion_demand -= demand;
    }

    // Command-wide window validator for a local MGET. With the per-key filter armed, every queried
    // cell is snapshotted before the first value load and re-read exactly once after the complete
    // reply is private. Atomic exchanges still bracket the table word for point GET, but an exchange
    // of an unrelated key cannot move this key's epoch. Each probe retains its stable-topology
    // handshake; immutable replacement plus rotation QSBR then makes a second per-key table-word
    // validation redundant. Above the bounded route cache, every touched shard uses generation
    // validation and each key probe validates separately. This stack object owns only sampled
    // words; the caller must keep all captures inside the current QSBR rotation.
    struct LocalMgetWindow {
        static constexpr uint32_t kMaxShards = 256;
        static constexpr uint32_t kMaxEpochKeys = 128;
        uint64_t states[kMaxShards];
        uint32_t epochs[kMaxEpochKeys];
        bool use_epochs = false;
    };

    static bool local_mget_touched(const uint64_t* touched, uint32_t sid) {
        return (touched[sid >> 6] & (uint64_t{1} << (sid & 63))) != 0;
    }

    // All window loads precede every value load. Returns None when the window is open.
    ReadLocalFallbackReason local_mget_window_open(LocalMgetWindow& window, const uint64_t* touched,
                                                   const uint64_t* hashes, const int32_t* shards,
                                                   uint32_t key_count, bool cached_routes) const {
        window.use_epochs = cached_routes;
        for (uint32_t sid = 0; sid < srv_->nshards(); sid++) {
            if (!local_mget_touched(touched, sid)) continue;
            const uint64_t state =
                srv_->shard(static_cast<int32_t>(sid)).store().read_local_state_acquire();
            if (FlatStore::read_local_generation_poisoned(state))
                return ReadLocalFallbackReason::Generation;
            window.states[sid] = state;
            // The filter-on path lets each probe perform the topology handshake. The generation
            // control must be even now so an equal even word later proves no bracket ran between.
            if (!window.use_epochs && FlatStore::read_local_table_mutating(state))
                return ReadLocalFallbackReason::SeqChurn;
        }
        if (!window.use_epochs) return ReadLocalFallbackReason::None;
        for (uint32_t key = 0; key < key_count; key++) {
            window.epochs[key] =
                srv_->shard(shards[key]).store().foreign_read_cell_epoch(hashes[key]);
        }
        return ReadLocalFallbackReason::None;
    }

    // All window loads follow every value load. Returns None when every participant is unchanged.
    ReadLocalFallbackReason local_mget_window_close(const LocalMgetWindow& window,
                                                    const uint64_t* touched, const uint64_t* hashes,
                                                    const int32_t* shards,
                                                    uint32_t key_count) const {
        // Keep the value loads before this single validation. A changed window demotes the
        // command to its owners; it never starts another local attempt. Free on x86.
#ifdef TOMO_CORE_CONCURRENCY_TEST
        if (test_local_read_copied_) test_local_read_copied_();
#endif
        std::atomic_thread_fence(std::memory_order_acquire);
        if (!window.use_epochs) {
            for (uint32_t sid = 0; sid < srv_->nshards(); sid++) {
                if (!local_mget_touched(touched, sid)) continue;
                const uint64_t after =
                    srv_->shard(static_cast<int32_t>(sid)).store().read_local_state_acquire();
                if (!FlatStore::read_local_state_eligible(after))
                    return ReadLocalFallbackReason::SeqChurn;
                // A group that published its filter but installed nothing leaves the generation
                // equal and only raises the pending bit; the command linearizes before it.
                if (!FlatStore::read_local_generation_equal(window.states[sid], after))
                    return ReadLocalFallbackReason::Generation;
            }
            return ReadLocalFallbackReason::None;
        }
        for (uint32_t key = 0; key < key_count; key++) {
            if (srv_->shard(shards[key]).store().foreign_read_cell_epoch(hashes[key]) !=
                window.epochs[key])
                return ReadLocalFallbackReason::Generation;
        }
        return ReadLocalFallbackReason::None;
    }

    // Attribute a failed single attempt to an explicit atomic conflict if one is now visible;
    // otherwise retain its topology/window reason for the ordinary owner demotion counter.
    ReadLocalFallbackReason local_mget_final_reason(const Op& op, const uint64_t* hashes,
                                                    const int32_t* shards, uint32_t key_count,
                                                    bool cached_routes,
                                                    ReadLocalFallbackReason transient) const {
        for (uint32_t key = 0; key < key_count; key++) {
            const uint64_t hash =
                cached_routes ? hashes[key] : FlatStore::hash_key(op.arg(key + 1));
            const int32_t shard_id = cached_routes ? shards[key] : srv_->router().shard_of(hash);
            const FlatStore& store = srv_->shard(shard_id).store();
            const uint64_t state = store.read_local_state_acquire();
            if (store.foreign_read_key_unsafe(state, hash))
                return ReadLocalFallbackReason::AtomicPending;
        }
        return transient;
    }

    // What note_local_read_access() records for a lane-served read. Not the MaxmemoryPolicy enum:
    // every policy that keys on nothing a read changes collapses to None here, so the cold helper
    // dispatches on one byte instead of re-deriving the classification per key.
    static constexpr uint8_t kForeignTouchNone = 0;
    static constexpr uint8_t kForeignTouchLru = 1;
    static constexpr uint8_t kForeignTouchLfu = 2;

    // Account for a successful lane-served access while maxmemory is enabled, honoring CLIENT
    // NO-TOUCH. LFU/LRU must see local-read heat or they can evict a key that is hot only on this
    // lane; the no-touch counter must distinguish deliberate suppression from no observation.
    // Callers gate on maxmemory_enabled_, so disabled reads need not load policy or clock state.
    // This cold helper borrows an immutable object within the current QSBR rotation.
    //
    // The arithmetic below is FlatStore::touch()'s, with the two differences foreignness forces:
    // the logarithmic-increment dice are this thread's own (the store's PRNG belongs to its owner
    // and is not safe to advance from here), and the meta write is one unretried CAS
    // (KvObj::touch_eviction_meta_foreign) rather than the owner's load/store pair, so a lost race
    // costs one approximate touch -- which LRU and LFU tolerate by construction -- and can never
    // corrupt a layout bit. Store-rare by construction: LRU writes only when the key's bucket is
    // stale (once per 256 seconds per key) and LFU only when the
    // increment actually fires, so the foreign RFO into the owner's line is the exception rather
    // than the per-read rule.
    __attribute__((noinline, cold)) void note_local_read_access(const Op& op, const KvObj* object,
                                                                uint8_t flags) {
        if (op.no_touch()) {
            srv_->climon_note_no_touch();
            return;
        }
        const uint64_t idle_hash = FlatStore::hash_key(object->key());
        srv_->shard(srv_->router().shard_of(idle_hash))
            .store()
            .note_object_access(object, cached_now_ms_);
        KvObj* touched = const_cast<KvObj*>(object);
        const uint8_t meta = static_cast<uint8_t>(flags >> 3);
        if (foreign_touch_policy_ == kForeignTouchLru) {
            if (meta != cached_lru_clock_)
                touched->touch_eviction_meta_foreign(flags, cached_lru_clock_);
            return;
        }
        // Random/TTL/noeviction key on nothing a read changes, so there is nothing to record --
        // but the NO-TOUCH count above still has to happen, exactly as it does on the owner.
        if (foreign_touch_policy_ != kForeignTouchLfu) return;
        uint8_t count = meta ? meta : 5;
        const uint32_t base = count > 5 ? static_cast<uint32_t>(count - 5) : 0;
        const uint32_t denominator = base * 10 + 1;
        uint64_t x = foreign_touch_random_;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        foreign_touch_random_ = x;
        if (count < 31 && (x * 2685821657736338717ULL) % denominator == 0) count++;
        if (count != meta) touched->touch_eviction_meta_foreign(flags, count);
    }

    // DEBUG ATOMIC-FANOUT-DEFER holds a local MGET after its command clock is pinned but before
    // any value load. This synchronous lane has no fragment to park, so the test stalls here.
    // Keys can then cross a wall-clock deadline while the pinned cut remains fixed, exposing a
    // torn expiry decision if per-key clocks are used. A per-pass thread-local flag gates this
    // cold helper; unarmed reads perform no debug atomic load (see LiveConfigSnapshot).
    __attribute__((noinline, cold)) void debug_fanout_stall_local() {
        Server::debug_stall_us(debug_fanout_defer_us_);
    }

    // Contract: the local-read thread builds a private MGET reply within its current QSBR
    // rotation. Require at least one key and at most kMaxShards shards (otherwise abort).
    // Pin one command clock, capture immutable values, and validate the complete window once.
    // No Done is published and no store pointer escapes. Any conflict, type, expiry or window
    // failure clears the reply and returns a reason for owner demotion; there is no local retry.
    // Reply allocation uses the ordinary Sink/SmallBuf failure policy.
    PreparedLocalRead prepare_captured_local_mget(Op& op) {
        // Phase 1: resolve the touched shards and pin the command-wide expiry cut.
        const uint32_t key_count = op.argc() - 1;
        if (!key_count || srv_->nshards() > LocalMgetWindow::kMaxShards) std::abort();

        uint64_t route_hashes[LocalMgetWindow::kMaxEpochKeys];
        int32_t route_shards[LocalMgetWindow::kMaxEpochKeys];
        const bool cached_routes = key_count <= LocalMgetWindow::kMaxEpochKeys;
        uint64_t touched[LocalMgetWindow::kMaxShards / 64] = {};
        for (uint32_t key = 0; key < key_count; key++) {
            const uint64_t hash = FlatStore::hash_key(op.arg(key + 1));
            const int32_t shard_id = srv_->router().shard_of(hash);
            touched[static_cast<uint32_t>(shard_id) >> 6] |=
                uint64_t{1} << (static_cast<uint32_t>(shard_id) & 63);
            if (cached_routes) {
                route_hashes[key] = hash;
                route_shards[key] = shard_id;
            }
        }
        const int64_t command_now_ms = cached_now_ms_;
        if (__builtin_expect(debug_fanout_defer_us_ != 0, false)) debug_fanout_stall_local();

        // Phase 2: open the validation window and capture/copy bounded key batches.
        LocalMgetWindow window;
        PreparedLocalRead prepared;
        read_local_clear_reply(op);

        ReadLocalFallbackReason transient = local_mget_window_open(
            window, touched, route_hashes, route_shards, key_count, cached_routes);
        bool demote = transient != ReadLocalFallbackReason::None;
        if (!demote) reply_array_header(op.sink(), key_count);

        for (uint32_t first = 0; first < key_count && !demote; first += kReadLocalPrefetchKeys) {
            const uint32_t count = std::min<uint32_t>(key_count - first, kReadLocalPrefetchKeys);
            uint64_t hashes[kReadLocalPrefetchKeys];
            int32_t shards[kReadLocalPrefetchKeys];
            ReadLocalCaptureBuffer<kReadLocalPrefetchKeys> captures;

            // I0 warms every home word in this bounded window. C0 then performs the complete
            // key-verified walk and prefetches the exact object's value before E0 copies it.
            for (uint32_t offset = 0; offset < count; offset++) {
                if (cached_routes) {
                    hashes[offset] = route_hashes[first + offset];
                    shards[offset] = route_shards[first + offset];
                } else {
                    hashes[offset] = FlatStore::hash_key(op.arg(first + offset + 1));
                    shards[offset] = srv_->router().shard_of(hashes[offset]);
                }
                srv_->shard(shards[offset]).store().read_local_prefetch(hashes[offset]);
            }
            for (uint32_t offset = 0; offset < count; offset++) {
                captures.entries[offset] =
                    srv_->shard(shards[offset])
                        .store()
                        .read_local_prefetch_capture(hashes[offset], op.arg(first + offset + 1));
            }

            for (uint32_t offset = 0; offset < count && !demote; offset++) {
                const int32_t shard_id = shards[offset];
                FlatStore& store = srv_->shard(shard_id).store();
                const FlatStore::ReadLocalPrefetchCapture& capture = captures.entries[offset];
                if (capture.result == FlatStore::ReadLocalProbeResult::AtomicPending) {
                    read_local_clear_reply(op);
                    return {ReadLocalFallbackReason::AtomicPending};
                }
                if (capture.result == FlatStore::ReadLocalProbeResult::Churn) {
                    transient = ReadLocalFallbackReason::SeqChurn;
                    demote = true;
                    break;
                }
                if (capture.result == FlatStore::ReadLocalProbeResult::Missing) {
                    reply_null(op.sink(), op.resp3());
                    prepared.keyspace_misses++;
                    if (!window.use_epochs && !store.read_local_validate(capture.state)) {
                        transient = ReadLocalFallbackReason::SeqChurn;
                        demote = true;
                    }
                    continue;
                }

                const KvObj* object = capture.object;
                if (!capture.slot || !object) std::abort();
                const uint8_t flags = object->read_local_flags();
                if (static_cast<Type>(object->type) != Type::String) {
                    read_local_clear_reply(op);
                    return {ReadLocalFallbackReason::Typed};
                }
                if (flags & KvObjFlags::HasTtl) {
                    const int64_t deadline = object->read_local_expire_at_ms(flags);
                    if (deadline >= 0 && deadline < command_now_ms) {  // Redis: now > at
                        read_local_clear_reply(op);
                        return {ReadLocalFallbackReason::Expired};
                    }
                }

                const Enc encoding = object->encoding();
                if (encoding == Enc::Int) {
                    char text[24];
                    const uint32_t length = i64_to_dec(text, object->read_local_int_value(flags));
                    reply_bulk(op.sink(), Slice(text, length));
                } else if (encoding == Enc::Raw || encoding == Enc::Extern) {
                    read_local_reply_string(op, object, flags);
                } else {
                    read_local_clear_reply(op);
                    return {ReadLocalFallbackReason::Typed};
                }
                prepared.keyspace_hits++;
                // Account only for a key this pass accepted, before demotion.
                if (!window.use_epochs && !store.read_local_validate(capture.state)) {
                    transient = ReadLocalFallbackReason::SeqChurn;
                    demote = true;
                } else if (__builtin_expect(maxmemory_enabled_, false)) {
                    note_local_read_access(op, object, flags);
                }
            }
        }

        // Phase 3: validate the whole copied reply once, or clear it for owner demotion.
        // C0 performs each probe's topology validation. This one outer close then validates
        // every queried cell across the complete multi-shard capture/copy interval.
        if (!demote) {
            transient =
                local_mget_window_close(window, touched, route_hashes, route_shards, key_count);
            demote = transient != ReadLocalFallbackReason::None;
        }
        if (!demote) return prepared;
        read_local_clear_reply(op);
        // Topology churn or a changed atomic window demotes to the owner after one capture.
        return {local_mget_final_reason(op, route_hashes, route_shards, key_count, cached_routes,
                                        transient)};
    }

    // Contract: the local-read thread builds one private reply in the current QSBR rotation;
    // it publishes no Done. A point read requires its home store and optionally one capture;
    // MGET requires no capture and uses its own window. None means complete copied bytes with
    // no retained FlatStore pointer. Failure clears bytes and returns an owner-demotion reason,
    // never retries locally. The caller's ordered prefix commit preserves same-key dependencies.
    // Reply allocation follows Sink/SmallBuf; caller-owned captures die before the rotation tick.
    PreparedLocalRead prepare_local_read(
        Op& op, FlatStore* home, bool mget,
        const FlatStore::ReadLocalPrefetchCapture* captured = nullptr) {
        if (mget) {
            if (captured) std::abort();
            return prepare_captured_local_mget(op);
        }
        FlatStore& store = *home;
        ReadLocalCaptureBuffer<1> local_capture;
        // A mixed GET/MGET chunk executes in program order. Its point reads capture here so a
        // later GET can never retain a version older than the preceding MGET returned.
        if (!captured) {
            store.read_local_prefetch(op.hash);
            local_capture.entries[0] = store.read_local_prefetch_capture(op.hash, op.key());
            captured = &local_capture.entries[0];
        }

        const FlatStore::ReadLocalProbeResult result = captured->result;
        const KvObj* object = captured->object;
        const uint64_t probe_state = captured->state;
        if (result == FlatStore::ReadLocalProbeResult::AtomicPending) {
            read_local_clear_reply(op);
            return {ReadLocalFallbackReason::AtomicPending};
        }
        if (result == FlatStore::ReadLocalProbeResult::Missing) {
            read_local_clear_reply(op);
            // The same permission as local MGET: only the notify-aware owner may
            // emit keymiss. Keep this check on the miss edge so GET hits
            // do not pay another notification test. The per-pass bit is shared
            // with MGET's parse-time ContextKeymissNotify gate.
            if (read_local_keymiss_notify_armed())
                return {ReadLocalFallbackReason::ContextKeymissNotify};
            if (store.read_local_validate(probe_state)) {
                reply_null(op.sink(), op.resp3());
                return {ReadLocalFallbackReason::None, 0, 1};
            }
        } else if (result != FlatStore::ReadLocalProbeResult::Churn) {
            if (!object) std::abort();
            // Keep the observed word's address as part of the snapshot, but consume only the
            // decoded immutable object. Loading through slot here would chase a newer version.
            if (!captured->slot) std::abort();
            const uint8_t flags = object->read_local_flags();
            if (static_cast<Type>(object->type) != Type::String) {
                read_local_clear_reply(op);
                return {ReadLocalFallbackReason::Typed};
            }
            if (flags & KvObjFlags::HasTtl) {
                const int64_t deadline = object->read_local_expire_at_ms(flags);
                if (deadline >= 0 && deadline < cached_now_ms_) {  // Redis: now > at
                    read_local_clear_reply(op);
                    return {ReadLocalFallbackReason::Expired};
                }
            }

#ifdef TOMO_CORE_CONCURRENCY_TEST
            ++test_local_get_reply_attempts_;
#endif
            read_local_clear_reply(op);
            const Enc encoding = object->encoding();
            if (encoding == Enc::Int) {
                char text[24];
                const uint32_t length = i64_to_dec(text, object->read_local_int_value(flags));
                reply_bulk(op.sink(), Slice(text, length));
            } else if (encoding == Enc::Raw || encoding == Enc::Extern) {
                read_local_reply_string(op, object, flags);
            } else {
                read_local_clear_reply(op);
                return {ReadLocalFallbackReason::Typed};
            }

#ifdef TOMO_CORE_CONCURRENCY_TEST
            if (test_local_read_copied_) test_local_read_copied_();
#endif
            if (store.read_local_validate(probe_state)) {
                // One predicted-not-taken test on the same per-pass byte the owner path tests,
                // after the validate that makes this read final. See note_local_read_access().
                if (__builtin_expect(maxmemory_enabled_, false))
                    note_local_read_access(op, object, flags);
                return {ReadLocalFallbackReason::None, 1, 0};
            }
        }

        // Both a failed capture and a failed final validation demote through the same cleanup.
        read_local_clear_reply(op);
        const uint64_t state = store.read_local_state_acquire();
        if (store.foreign_read_key_unsafe(state, op.hash))
            return {ReadLocalFallbackReason::AtomicPending};
        return {ReadLocalFallbackReason::SeqChurn};
    }

    // Consume at most `op_budget` lane entries in same-client gather quanta. The fair-lane
    // scheduler owns tombstone compaction around the complete rotation so an interleave does not
    // turn each 32-operation chunk into a scan of the 1024-entry lane.
    template <bool YieldToOwner = false>
    uint32_t drain_local_reads_bounded(uint32_t op_budget) {
        if constexpr (!Fused) {
            return 0;
        } else {
            if (!read_local_enabled() || !op_budget) return 0;
            return drain_local_reads_bounded_impl<YieldToOwner>(op_budget);
        }
    }

    // Contract: the armed local-read thread consumes at most op_budget lane entries in
    // same-client chunks. Require live ROB handles, bound demotion callback, and a current QSBR
    // rotation. Captures are stack-only. Completed prefixes clear pending bits/credits before
    // release Done; failed commands and their transitive same-key dependents transfer to owners.
    // Demotion refusal leaves the suffix queued. YieldToOwner checks debt at chunk boundaries;
    // tombstone removal does not release a Client and must precede writeback corpse reclamation.
    template <bool YieldToOwner>
    uint32_t drain_local_reads_bounded_impl(uint32_t op_budget) {
        static_assert(Fused);
        // Phase 1: allocate stack scratch and establish bounded drain/yield accounting.
        auto& lane = read_local_impl();
        if (!lane.lane_count) return 0;
        // One record per chunk entry. Gather resolves the Op, its home store and its MGET class
        // exactly once; every later pass reads them from here instead of walking the ROB again.
        // Borrows Op/store pointers only on this thread's stack. No capture or Client/ROB
        // handle may outlive the rotation's QSBR tick; fallback and completion consume them.
        struct LocalReadChunk {
            Op* ops[kReadLocalDrainChunkOps];
            FlatStore* stores[kReadLocalDrainChunkOps];  // null for an MGET (multi-store)
            uint64_t op_ids[kReadLocalDrainChunkOps];
            ReadLocalFallbackReason fallbacks[kReadLocalDrainChunkOps];
        } chunk;
        static_assert(kReadLocalDrainChunkOps <= 32, "mget_mask is one 32-bit word");
        ReadLocalCaptureBuffer<kReadLocalDrainChunkOps> captures;
        const uint32_t nshards = srv_->nshards();
        ReadLocalStats& stats = self_->read_local_stats();
        uint32_t work = 0;
        uint32_t consumed = 0;
        auto discard_tombstone_heads = [&] {
            while (lane.lane_count) {
                const auto& head = lane.lane[lane.lane_head];
                if (head.client && head.client->rob().pending_read_local(head.op_id)) break;
                lane.lane_head = (lane.lane_head + 1) & (kInboxSlots - 1);
                lane.lane_count--;
            }
        };
        auto owner_turn_pending = [&] {
            if constexpr (YieldToOwner) {
                if (!consumed || consumed % kReadLocalDrainChunkOps) return false;
                return fairlane_owner_debt_pending() || self_->notified_task_depth_capped(1) != 0;
            }
            return false;
        };
        // Work through each client's lane run in gather/prefetch-sized chunks. A successful chunk
        // can commit immediately. At a fallback, only the intrinsically failing entries and their
        // transitive same-key set move in a ROB-ordered owner wave; unrelated reads remain local.
        discard_tombstone_heads();
        while (lane.lane_count && consumed < op_budget) {
            const auto& head = lane.lane[lane.lane_head];
            Client* client = head.client;
            auto& rob = client->rob();
            uint32_t count = 0;
            uint32_t capacity = std::min<uint32_t>(kReadLocalDrainChunkOps, op_budget - consumed);
            if constexpr (YieldToOwner)
                capacity = std::min<uint32_t>(
                    capacity, kReadLocalDrainChunkOps - consumed % kReadLocalDrainChunkOps);
            // Phase 2: gather one same-client chunk without crossing a ROB generation.
            // Gather: one ROB frontier snapshot for the whole same-client run (see
            // Rob::pending_read_local(id, dispatch, flush)), and each entry's Op, home store and
            // MGET class resolved here once. bit i of mget_mask marks an MGET entry.
            const uint64_t dispatch = rob.dispatch_id();
            const uint64_t flush = rob.flush_id();
            uint32_t mget_mask = 0;
            while (count < lane.lane_count && count < capacity) {
                const uint32_t index = (lane.lane_head + count) & (kInboxSlots - 1);
                const auto& task = lane.lane[index];
                if (task.client != client || !rob.pending_read_local(task.op_id, dispatch, flush))
                    break;
                Op& op = rob.at(task.op_id);
                const bool mget = read_local_mget(op);
                if (!mget && op.shard < 0) std::abort();
                chunk.ops[count] = &op;
                chunk.stores[count] = mget ? nullptr : &srv_->shard(op.shard).store();
                chunk.op_ids[count] = task.op_id;
                chunk.fallbacks[count] = lane.lane_fallbacks[index];
                mget_mask |= uint32_t{mget} << count;
                count++;
            }
            if (!count) std::abort();
            consumed += count;

            // Pure point chunks retain the widest I0/C0/E0 overlap. A mixed chunk captures and
            // consumes each command in program order below: MGET captures its own window, so
            // pre-capturing a following GET could otherwise let that later command regress.
            if (__builtin_expect(srv_->climon_armed() & Server::kClimonTracking, false))
                for (uint32_t i = 0; i < count; ++i) tracking_observe_local(*srv_, *chunk.ops[i]);
            const bool point_capture_batch = mget_mask == 0;
            if (point_capture_batch) {
                // Prefetch the chunk's home slots, then capture decoded immutable objects
                // and prefetch their value bytes before reply construction.
                for (uint32_t i = 0; i < count; i++)
                    chunk.stores[i]->read_local_prefetch(chunk.ops[i]->hash);
                for (uint32_t i = 0; i < count; i++) {
                    const Op& op = *chunk.ops[i];
                    captures.entries[i] =
                        chunk.stores[i]->read_local_prefetch_capture(op.hash, op.key());
                }
            }

            // Phase 3: build private replies and find the first dependent/failing command.
            // E0. The owner-map recheck is decided once per chunk: only this thread's parser and
            // demotion add owner slots, and neither runs inside a chunk, so an empty map stays
            // empty for every entry. Prefix keyspace counters accumulate only while no fallback
            // has been seen, which is exactly the prefix complete_local_prefix publishes.
            const bool owner_fence = rob.has_read_local_owner();
            uint32_t first_fallback = count;
            uint32_t prefix_keyspace_hits = 0;
            uint32_t prefix_keyspace_misses = 0;
            uint32_t prefix_mget_hits = 0;
            uint32_t prefix_demand = 0;
            uint64_t prefix_bits = 0;
            for (uint32_t i = 0; i < count; i++) {
                Op& op = *chunk.ops[i];
                const bool mget = ((mget_mask >> i) & 1u) != 0;
                if (owner_fence && chunk.fallbacks[i] == ReadLocalFallbackReason::None) {
                    bool broad_owner = false;
                    const bool owner_conflict = rob.read_local_owner_conflicts_before(
                        chunk.op_ids[i], [&](const Op& owner) {
                            if (!read_local_commands_overlap(op, owner)) return false;
                            broad_owner |= !read_local_owner_command_is_precise(owner);
                            return true;
                        });
                    if (owner_conflict) {
                        chunk.fallbacks[i] = broad_owner ? ReadLocalFallbackReason::ContextRoute
                                                         : ReadLocalFallbackReason::ContextOwnerKey;
                    }
                }
                if (chunk.fallbacks[i] == ReadLocalFallbackReason::None) {
                    PreparedLocalRead prepared;
                    if (point_capture_batch) {
                        prepared =
                            prepare_local_read(op, chunk.stores[i], false, &captures.entries[i]);
                    } else {
                        prepared = prepare_local_read(op, chunk.stores[i], mget);
                    }
                    chunk.fallbacks[i] = prepared.fallback;
                    if (first_fallback == count &&
                        prepared.fallback == ReadLocalFallbackReason::None) {
                        prefix_keyspace_hits += prepared.keyspace_hits;
                        prefix_keyspace_misses += prepared.keyspace_misses;
                        prefix_mget_hits += mget;
                        prefix_demand += mget ? std::min<uint32_t>(op.argc() - 1, nshards) : 1;
                        prefix_bits |= Rob<kRobWindow>::read_local_slot_bit(chunk.op_ids[i]);
                    }
                }
                if (chunk.fallbacks[i] != ReadLocalFallbackReason::None && first_fallback == count)
                    first_fallback = i;
            }

            // Completion is chunk-aggregated: one pending-mask clear, one demand release and one
            // add per statistic instead of six read-modify-writes per op; the prefix accumulators
            // above describe exactly the entries `completed` names. The pending bits are cleared
            // before any release Done publication. note_command and Done remain per operation.
            auto complete_local_prefix = [&](uint32_t completed) {
                if (!completed) return;
                rob.complete_pending_read_local_mask(prefix_bits);
                if (prefix_demand > lane.lane_demotion_demand) std::abort();
                lane.lane_demotion_demand -= prefix_demand;
                stats.hits += completed;
                stats.keyspace_hits += prefix_keyspace_hits;
                stats.keyspace_misses += prefix_keyspace_misses;
                stats.mget_local_hits += prefix_mget_hits;
                for (uint32_t i = 0; i < completed; i++) {
                    Op& op = *chunk.ops[i];
                    self_->note_command(op.spec->id);
                    op.state.store(OpState::Done, std::memory_order_release);
                }
                notify_sender(client);
                lane.lane_head = (lane.lane_head + completed) & (kInboxSlots - 1);
                lane.lane_count -= completed;
                work += completed;
            };

            // Phase 4: publish the independent prefix and demote or retain the suffix.
            if (first_fallback != count) {
                // Publish the independent older prefix locally. Only the failing command and the
                // transitive same-key set move owner-side; ROB retirement holds every younger Done
                // reply without imposing a connection-wide execution venue.
                complete_local_prefix(first_fallback);
                for (uint32_t i = first_fallback; i < count; i++)
                    read_local_clear_reply(*chunk.ops[i]);
                lane.lane_fallbacks[lane.lane_head] = chunk.fallbacks[first_fallback];
                uint32_t demoted = 0;
                if (!demote_local_read_batch(client, chunk.op_ids + first_fallback,
                                             chunk.fallbacks + first_fallback,
                                             count - first_fallback, demoted))
                    break;
                work += demoted;
                discard_tombstone_heads();
                if (owner_turn_pending()) break;
                continue;
            }

            complete_local_prefix(count);
            discard_tombstone_heads();
            if (owner_turn_pending()) break;
        }
        self_->sig().ops += work;
        return work;
    }

    uint32_t drain_local_reads() {
        if constexpr (!Fused) return 0;
        if (!read_local_enabled()) return 0;
        compact_local_read_tombstones();
        const uint32_t work = drain_local_reads_bounded(UINT32_MAX);
        compact_local_read_tombstones();
        return work;
    }

    bool flip_quiesced() const {
        if (aof_manager_ && aof_manager_->completions_pending(self_->id())) return false;
        if constexpr (Fused) {
            if (read_local_enabled() &&
                (read_local_impl().lane_count != 0 || !read_local_impl().deferred.empty()))
                return false;
        }
        if (snapshot_owner_state_ != SnapshotOwnerState::None || !self_->ex_inbound_quiesced() ||
            !stale_tasks_.empty() || !stale_releases_.empty() || !atomic_deferred_.empty() ||
            !multi_retries_.empty() || !xshard_retries_.empty() || !ordered_deferred_.empty() ||
            xshard_commit_pending_ || notify_keyless_pending_ ||
            !srv_->notify_retries(self_->id()).empty() || srv_->atomic_inflight() != 0 ||
            srv_->atomic_apply_inflight() != 0)
            return false;
        for (const auto& queue : snapshot_backlogs_)
            if (!queue.empty()) return false;
        for (Shard* shard : self_->shards()) {
            if (shard->notify_output_pending()) return false;
            if (aof_manager_ && aof_manager_->recording() && shard->store().aof().has_pending())
                return false;
        }
        return true;
    }

    uint32_t owner_control_tail() {
        // A stage may start after the loop's initial freeze sample. Finish EVERY
        // owner access before a control pass can acknowledge ExDrain: the coordinator
        // may transfer shards and rewrite this vector immediately after that store.
        uint32_t work = 0;
        // Busy owners must get the same maintenance as idle sweeps. Reuse the pass's cached
        // clock, at most once per distinct millisecond (a clock adjustment cannot postpone it).
        const uint32_t now = static_cast<uint32_t>(cached_now_ms_);
        if (now != expire_beat_ms_) {
            expire_beat_ms_ = now;
            work += active_expire_cycle();
            if (maxmemory_enabled_) work += eviction_cycle();
            if constexpr (kSingleDatabase) keyspace_sample_cycle();
        }
        if constexpr (Fused)
            if (read_local_enabled() && read_local_impl().deferred.resize_pending()) work++;
        work += drain_notify_keyless(self_->sig());
        lb_bucket_bytes_pass();
        work += lb_control_pass();
        if constexpr (!Fused)
            work += flip_control_pass();
        else if (srv_->thread_mode() == ThreadMode::Split)
            work += flip_control_pass();
        return work;
    }

    // Every stage action below tests Server::flip_stage_owed(), never flip_acked() alone: the stage
    // was sampled at the top of this pass and may belong to a FLIP that has since finished.
    bool flip_owed(FlipStage stage) const {
#ifdef TOMO_CORE_CONCURRENCY_TEST
        // Negative control: consult acknowledgement without validating the live epoch.
        if (test_live_epoch_ack_test_) return !srv_->flip_acked(self_->id(), stage);
#endif
        if (__builtin_expect(srv_->debug_flip_stage_hold_us() != 0, false))
            debug_flip_stage_hold(stage);
        return srv_->flip_stage_owed(self_->id(), stage);
    }

    // DEBUG FLIP-STAGE-HOLD: bounded spin; only ExInstall that this executor already acknowledged.
    __attribute__((noinline, cold)) void debug_flip_stage_hold(FlipStage stage) const {
        if (stage != FlipStage::ExInstall || !srv_->flip_acked(self_->id(), stage)) return;
        const uint64_t epoch = srv_->flip_epoch();
        const uint64_t deadline =
            now_ns() + static_cast<uint64_t>(srv_->debug_flip_stage_hold_us()) * 1000ull;
        while (srv_->flip_epoch() == epoch && now_ns() < deadline) __builtin_ia32_pause();
    }

    // Owner-thread stage driver. A sampled stage is actionable only while flip_owed confirms
    // its live epoch. ExDrain acknowledgement transfers permission to rewrite shard ownership;
    // the caller must finish all owner work first. Preparation failure is reported to FLIP,
    // remask failure aborts, and a drain awaiting remote retirement keeps the loop polling.
    uint32_t flip_control_pass() {
        const FlipStage stage = srv_->flip_stage();
#ifdef TOMO_CORE_CONCURRENCY_TEST
        if (test_after_stage_sample_) test_after_stage_sample_(self_->id(), stage);
#endif
        if constexpr (!kSingleDatabase) {
            if (stage == FlipStage::DatabaseExDrain) {
                // Check quiescence only for a live boundary epoch. An acknowledged or stale
                // sample returns work so the frozen loop continues servicing stage changes.
                if (!flip_owed(stage)) return 1;
                if (flip_quiesced()) srv_->flip_ack(self_->id(), stage);
                // Spin while the acknowledgement is owed, as FLIP and LB drains do. Its remote
                // predicates (atomic_inflight() leaves only when an IO retires the reply, read-
                // local grace, notify output) signal nothing to this executor: a park would sleep
                // to its timeout while every IO holds every client's frames (SWAPDB).
                return 1;
            }
        }
        if (stage == FlipStage::IoDrain && flip_owed(stage)) {
            // The coordinator wakes every live FLIP pass. Those CQ completions
            // can keep resetting idle_spins, starving sweep() after the last
            // EXEC retired. IoDrain waits for that state's record refs. Run the
            // bounded owner cleanup here, before any ExDrain ack;
            // no owner work is permitted after that safe point.
            return atomic_cleanup_cycle(64);
        }
        if (stage == FlipStage::IoPrepare &&
            srv_->flip_candidate_target(self_->id()) == Role::Ifid && flip_owed(stage)) {
            if (!self_->prepare_io_role())
                srv_->flip_note_failure("ERR FLIP could not prepare a new IO listener");
            else if (!self_->prepare_client_capacity(srv_->flip_incoming_clients(self_->id())))
                srv_->flip_note_failure("ERR FLIP could not reserve destination connection state");
            srv_->flip_ack(self_->id(), stage);
            return 1;
        }
        if (stage == FlipStage::ExDrain && flip_owed(stage) && flip_quiesced()) {
            srv_->flip_ack(self_->id(), stage);
#ifdef TOMO_CORE_CONCURRENCY_TEST
            if (test_after_drain_ack_) test_after_drain_ack_();
#endif
            return 1;
        }
        if (stage == FlipStage::ExInstall && flip_owed(stage)) {
            // ExDrain retired every old lane and IO dispatch remains parked until all ExInstall
            // acknowledgements. Reassign blocks in the consumer-local allocation here;
            // no topology object is rebuilt and no producer can observe a half-installed mask.
            if (!self_->remask_task_inbox_quiesced(srv_->placement().ifid_threads(),
                                                   srv_->placement().ex_threads()))
                std::abort();
            for (Shard* shard : self_->shards())
                shard->bind_notify_pending(&notify_keyless_pending_);
            srv_->flip_ack(self_->id(), stage);
            return 1;
        }
        if (stage == FlipStage::Rollback && flip_owed(stage)) {
            if (srv_->flip_candidate_target(self_->id()) == Role::Ifid)
                self_->cancel_prepared_io_role();
            srv_->flip_ack(self_->id(), stage);
            return 1;
        }
        return 0;
    }

    // Owner-thread load-balancing barrier. Acknowledge only after every local lifetime is
    // quiescent, then retry coordinator notification if the ring lacks an SQE. On adoption,
    // bind notification pointers to this owner and force a state walk. Retirement sinks follow
    // the ownership edge and are checked before owner work; the caller must not touch shards
    // after this function publishes the ExDrain acknowledgement.
    uint32_t lb_control_pass() {
        if (!lb_controller_armed_) return 0;
        if (srv_->lb_stage() != LbStage::ExDrain) {
            lb_ack_wake_pending_ = false;
            // Each owned shard's keyless-notify pointer must target this loop after migration.
            // Pointing at the previous owner strands expiry notifications because that owner's
            // drain no longer visits the shard. Rebind once on the first pass after adoption;
            // the forced drain below also observes events produced before this rebind.
            if (lb_rebind_pending_) {
                lb_rebind_pending_ = false;
                for (Shard* shard : self_->shards())
                    shard->bind_notify_pending(&notify_keyless_pending_);
                notify_keyless_pending_ = true;  // force one state-checked drain after adoption
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
            return 1u;  // retry after submit if the wake SQE was unavailable
        };
        if (lb_ack_wake_pending_) return wake_coordinator();
        if (srv_->lb_acked(self_->id())) return 0;
        if (!flip_quiesced()) return 0;
        srv_->lb_ack(self_->id());
#ifdef TOMO_CORE_CONCURRENCY_TEST
        if (test_after_drain_ack_) test_after_drain_ack_();
#endif
        lb_ack_wake_pending_ = true;
        lb_rebind_pending_ = true;  // membership may change before the stage ends; rebind after
        return wake_coordinator();
    }

    template <bool OwnsShards = true>
    void refresh_live_config() {
        LiveConfigSnapshot snapshot;
        if (!srv_->live_config_snapshot_if_changed(self_->id(), live_config_version_, snapshot))
            return;
        const bool enabled = snapshot.maxmemory != 0;
        if constexpr (OwnsShards) {
            const uint64_t shard_limit = snapshot.maxmemory / srv_->nshards();
            for (Shard* sh : self_->shards()) {
                if (!sh->configure_maxmemory(enabled, shard_limit, snapshot.policy,
                                             snapshot.samples))
                    report_idle_clock_unavailable(*sh);
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
        }
        maxmemory_enabled_ = enabled;
        foreign_touch_policy_ = !enabled                                   ? kForeignTouchNone
                                : maxmemory_policy_is_lru(snapshot.policy) ? kForeignTouchLru
                                : maxmemory_policy_is_lfu(snapshot.policy) ? kForeignTouchLfu
                                                                           : kForeignTouchNone;
        slowlog_arm_.slowlog_us = snapshot.slowlog_log_slower_than;
        slowlog_arm_.latency_ms = snapshot.latency_monitor_threshold;
        slowlog_arm_.latency_tracking = snapshot.latency_tracking;
        latency_tracking_bind(snapshot.latency_tracking);
        timed_batch_<false> =
            snapshot.latency_tracking ? exec_batch_latency<false> : exec_batch_timed<false>;
        if constexpr (Fused)
            timed_batch_<true> =
                snapshot.latency_tracking ? exec_batch_latency<true> : exec_batch_timed<true>;
        slowlog_armed_ = slowlog_arm_.armed();
        debug_fanout_defer_us_ = snapshot.debug_fanout_defer_us;
        live_config_version_ = snapshot.version;
        if constexpr (OwnsShards) srv_->tracking_config_applied(self_->id(), snapshot.version);
    }

    // CONFIG SET maxmemory/-policy/-samples: called by this owner's own CONFIG fragment, after the
    // CONFIG's single publication (see cmd_config). refresh_live_config() alone would apply the new
    // limit only at this owner's next pass entry, and the barrier could reply +OK while this pass
    // still admitted, refused or evicted under the old one. Applies exactly the maxmemory part of
    // that refresh, from the latest committed copy, to every store this owner holds and to its
    // owner-local caches, so later fragments of any order converge on the last publication.
    // live_config_version_ is untouched: the next pass entry still performs its full refresh.
    [[gnu::cold, gnu::noinline]] void apply_memory_config() {
        const LiveConfigSnapshot snapshot = srv_->live_config_snapshot(self_->id());
        const bool enabled = snapshot.maxmemory != 0;
        const uint64_t shard_limit = snapshot.maxmemory / srv_->nshards();
        for (Shard* sh : self_->shards())
            if (!sh->configure_maxmemory(enabled, shard_limit, snapshot.policy, snapshot.samples))
                report_idle_clock_unavailable(*sh);
        maxmemory_enabled_ = enabled;
        foreign_touch_policy_ = !enabled                                   ? kForeignTouchNone
                                : maxmemory_policy_is_lru(snapshot.policy) ? kForeignTouchLru
                                : maxmemory_policy_is_lfu(snapshot.policy) ? kForeignTouchLfu
                                                                           : kForeignTouchNone;
        // The pass entry computes this clock only while enabled; later tasks of this pass stamp it.
        if (enabled)
            cached_lru_clock_ = static_cast<uint8_t>(
                (static_cast<uint64_t>(cached_now_ms_ / 1000) >> kLruClockShift) & 0x1f);
        // A fused thread parses with this executor's read-local promise; keep it with the owner.
        if constexpr (Fused)
            if (read_local_enabled())
                set_read_local_point_writes_precise(!enabled ||
                                                    snapshot.policy == MaxmemoryPolicy::NoEviction);
    }

    // A failed idle-clock allocation cannot refuse anything here: keep the limit (eviction uses
    // the five-bit LRU meta) and report that this store's OBJECT IDLETIME is degraded to 0.
    [[gnu::cold, gnu::noinline]] static void report_idle_clock_unavailable(const Shard& sh) {
        std::fprintf(stderr,
                     "WARNING: maxmemory idle clock allocation failed for shard %u; "
                     "OBJECT IDLETIME reports 0 for its keys\n",
                     static_cast<unsigned>(sh.id()));
    }

    // Contract: this physical thread borrows the executor for one loop tenure and installs its
    // CONFIG maxmemory callback in TLS. Destruction restores the previous hook, including nested
    // scopes. The executor outlives the binding; no allocation or cross-thread publication occurs.
    class MemoryConfigBinding {
    public:
        explicit MemoryConfigBinding(ExLoopT* loop) : previous_(owner_memory_config_hook) {
            owner_memory_config_hook = OwnerMemoryConfigHook{
                loop, [](void* owner) { static_cast<ExLoopT*>(owner)->apply_memory_config(); }};
        }
        ~MemoryConfigBinding() { owner_memory_config_hook = previous_; }
        MemoryConfigBinding(const MemoryConfigBinding&) = delete;
        MemoryConfigBinding& operator=(const MemoryConfigBinding&) = delete;

    private:
        OwnerMemoryConfigHook previous_;
    };

    // The pending flag is a HINT, and a hint must never be the only looker: a shard whose binding
    // went stale (any ownership move a future path forgets to rebind) would strand its events
    // behind a flag it can no longer set. The busy path keeps the cheap flag gate; sweep() forces
    // the state walk, so stranded events survive at most until the owner's next idle pass.
    uint32_t drain_notify_keyless(LoopSignals& signals, bool force = false) {
        if (__builtin_expect(!notify_keyless_pending_, true) && !force) return 0;
        notify_keyless_pending_ = false;
        uint32_t work = 0;
        for (Shard* shard : self_->shards()) {
            work += notify_ex_pass_entry(*srv_, *shard, self_->id(), *self_, ring_, signals);
            notify_keyless_pending_ |= shard->notify_output_pending();
        }
        return work;
    }

    // Contract: idle owner-thread audit, called only while placement permits shard access.
    // Inspect inbox state without the notify mask, after older retry/forward/release work.
    // Drain helpers retire queue entries after callbacks, independently of the pop frontier.
    // Maintenance and forced notification walks provide liveness when a hint is absent.
    // Returns work/needed polling; retained commits or queues must keep the caller active.
    /* TOMO_TOOL_FUNCTION sweep */
    template <uint32_t BatchOps = kGenthreadExBatchOps, bool ConsumeTasks = true,
              bool IofusedPrivateQueue = false, bool InterleaveLocalReads = false>
    uint32_t /* TOMO_TOOL_BIND sweep */ sweep() {
        Server::ClientWorkScope client_work(*srv_, self_->id());
        [[maybe_unused]] bool owner_work_remains = false;
        uint32_t n = snapshot_control_pass<BatchOps, IofusedPrivateQueue>() +
                     service_stale_forwards<BatchOps, IofusedPrivateQueue>() + drain_releases(true);
        if (__builtin_expect(notify_retries_pending(), false)) n += service_notify_retries();
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
                            n += drain_tasks<BatchOps, IofusedPrivateQueue>(true);
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
        if (__builtin_expect(srv_->blocking_waiters() != 0, false) &&
            !shutdown_snapshot_blocks_tasks())
            n += blocking_owner_cycle(*srv_, *self_, ring_, cached_now_ms_, true);
        n += aof_flush_pass();
        // Normally flush_xshard_commits empties the queue synchronously. The DEBUG hold can
        // retain it across passes; both split and fused idle paths consult this sweep before
        // parking, so keep polling until the control connection releases the latch.
        if (__builtin_expect(xshard_commit_pending_, false)) n++;
        return n;
    }

    uint32_t aof_flush_pass() {
        if (__builtin_expect(aof_manager_ == nullptr, true)) return 0;
        aof_manager_->debug_ack_window(self_->id(), ring_);
        AofOwnerContext context{self_->id(), &ring_, &self_->sig()};
        uint32_t work = 0;
        bool all_posted = true;
        for (Shard* shard : self_->shards()) {
            AofProducer& producer = shard->store().aof();
            if (!producer.has_pending()) continue;
            // A full channel is retryable. Retain completion ownership until *all* records
            // have posted, including plain records staged behind an undecided atomic group.
            const bool flushed = producer.flush(context);
            all_posted &= flushed && !producer.has_pending();
            if (flushed || aof_manager_->recording()) work++;
        }
        work += aof_manager_->finish_completions(
            self_->id(), all_posted, this,
            [](void* p, Client* client) { static_cast<ExLoopT*>(p)->notify_sender(client); });
        return work;
    }

    static int64_t realtime_ms() {
        timespec ts{};
        ::clock_gettime(CLOCK_REALTIME, &ts);
        return static_cast<int64_t>(ts.tv_sec) * 1000 + ts.tv_nsec / 1000000;
    }

    void refresh_command_clock() {
        cached_now_ms_ = realtime_ms();
        if (maxmemory_enabled_)
            cached_lru_clock_ = static_cast<uint8_t>(
                (static_cast<uint64_t>(cached_now_ms_ / 1000) >> kLruClockShift) & 0x1f);
    }

    // Monitoring is independent of active expiry and ordinary command batches.
    // Bound both the cheap search and the expensive probes: inspect at most
    // eight owned shards, sampling at most one volatile shard per owner beat.
    // This numeric cursor names no shard-owned state and tolerates a new owner
    // vector after migration; each store keeps its own expiry-index cursor.
    __attribute__((noinline)) void keyspace_sample_cycle() {
        if (snapshot_blocks_tasks()) return;
        auto& shards = self_->shards();
        const uint32_t visits = static_cast<uint32_t>(std::min<size_t>(shards.size(), 8));
        for (uint32_t i = 0; i < visits; ++i) {
            if (keyspace_shard_cursor_ >= shards.size()) keyspace_shard_cursor_ = 0;
            Shard* shard = shards[keyspace_shard_cursor_++];
            if (!shard->store().expire_count()) continue;
            shard->set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
            shard->store().publish_keyspace_sample();
            break;
        }
    }

    [[gnu::noinline]] uint32_t eviction_cycle() {
        if (snapshot_blocks_tasks()) return 0;
        uint32_t removed = 0;
        for (Shard* sh : self_->shards()) {
            sh->set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
            const uint32_t n = sh->store().evict_over_limit();
            if (n) sh->publish_size();
            removed += n;
        }
        return removed;
    }

    uint32_t active_expire_cycle() {
        if (!srv_->active_expire_enabled()) return 0;
        if (snapshot_blocks_tasks()) return 0;
        auto& shards = self_->shards();
        if (shards.empty()) return 0;
        uint32_t removed = 0;
        const uint32_t visits =
            static_cast<uint32_t>(std::min<size_t>(shards.size(), kActiveExpireChecks));
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
        // With more shards than this pass's visit budget, the last busy command may have
        // started a resize outside the sampled slice. Do not let an otherwise empty sweep
        // park before the round-robin cursor reaches that shard.
        if (!removed && visits < shards.size())
            for (Shard* shard : shards)
                if (shard->store().rehashing() && !shard->store().snapshot_active()) return 1;
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

    // The armed coarse scheduler gives every captured producer one owner-task quantum. This keeps
    // WB distance independent of a producer's queued depth and gives a continuously busy remote IO
    // lane service every rotation. ThreadCtx preserves recv -> callback -> retire for each Task and
    // invokes the local hook only after the Task completing a full execution batch is retired.
    template <bool IofusedPrivateQueue = false>
    uint32_t drain_tasks_read_local_interleaved(bool unmasked, bool& owner_work_remains) {
        // A byte array supplies implicit-lifetime array storage in C++20.
        // Only received slots contain Tasks; their trivial lifetime may be
        // replaced when a full batch is reused. Empty polls initialize nothing.
        static_assert(std::is_trivially_copyable_v<Task> && std::is_trivially_destructible_v<Task>);
        alignas(Task) std::byte storage[sizeof(Task) * kReadLocalOwnerTaskChunkOps];
        auto& batch = *reinterpret_cast<Task(*)[kReadLocalOwnerTaskChunkOps]>(storage);
        uint32_t held = 0;
        uint32_t local_work = 0;
        auto take = [&](const Task& task) {
            std::construct_at(&batch[held++], task);
            if (held != kReadLocalOwnerTaskChunkOps) return false;
            exec_batch<IofusedPrivateQueue>(batch, held);
            held = 0;
            return true;
        };
        auto local_turn = [&] {
            // A local read must not run between a last-owner install and this batch's epoch
            // publication. This boundary still batches every group in the preceding owner chunk.
            flush_xshard_commits();
            local_work += drain_local_reads_bounded(kReadLocalDrainChunkOps);
        };
        const uint32_t n = self_->drain_task_producer_chunks<IofusedPrivateQueue>(
            kReadLocalOwnerTaskChunkOps, take, local_turn, unmasked);
        if (held) {
            exec_batch<IofusedPrivateQueue>(batch, held);
            local_turn();
        }
        owner_work_remains =
            self_->notified_task_depth_capped(1) != 0 || fairlane_owner_debt_pending();
        self_->sig().ops += n;
        return n + local_work;
    }

    // With captured owner work exhausted, consume further bounded local-read chunks. Recheck
    // owner hints at each boundary to yield to newly visible writers. The unmasked idle audit
    // remains the liveness backstop for a lost or racing hint.
    uint32_t drain_local_read_tail() {
        if (fairlane_owner_debt_pending() || self_->notified_task_depth_capped(1)) return 0;
        // Keep one scratch batch live across the pure-read tail. The bounded drain rechecks owner
        // work after every scheduling chunk, so the fast path does not pay stack setup per chunk.
        return drain_local_reads_bounded<true>(UINT32_MAX);
    }

    template <uint32_t BatchOps = kGenthreadExBatchOps, bool IofusedPrivateQueue = false>
    uint32_t drain_tasks(bool unmasked = false) {
        static_assert(std::is_trivially_copyable_v<Task> && std::is_trivially_destructible_v<Task>);
        alignas(Task) std::byte storage[sizeof(Task) * BatchOps];
        auto& batch = *reinterpret_cast<Task(*)[BatchOps]>(storage);
        uint32_t held = 0;
        auto take = [&](const Task& t) {
            std::construct_at(&batch[held++], t);
            if (held == BatchOps) {
                exec_batch<IofusedPrivateQueue>(batch, held);
                held = 0;
            }
        };
        const uint32_t n = unmasked ? self_->drain_tasks_unmasked<IofusedPrivateQueue>(take)
                                    : self_->drain_tasks<IofusedPrivateQueue>(take);
        if (held) exec_batch<IofusedPrivateQueue>(batch, held);
        self_->sig().ops += n;
        return n;
    }

    enum class SnapshotOwnerState : uint8_t {
        None,
        Preparing,
        Prepared,
        Frozen,
        Marked,
        ShutdownHeld,
        Capturing,
        Draining
    };

    bool snapshot_blocks_tasks() const {
        if (snapshot_owner_state_ == SnapshotOwnerState::Frozen ||
            snapshot_owner_state_ == SnapshotOwnerState::Marked ||
            snapshot_owner_state_ == SnapshotOwnerState::ShutdownHeld)
            return true;
        return snapshot_owner_state_ == SnapshotOwnerState::Capturing && snapshot_manager_ &&
               snapshot_manager_->blocking();
    }

    // Parked blocking operations and self-directed stale tasks can mutate outside
    // the ordinary inbox drain. They owe the final shutdown cut the same hold.
    bool shutdown_snapshot_blocks_tasks() const {
        return snapshot_blocks_tasks() && srv_->shutdown_snapshot_active();
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

    // Contract: the shard owner advances one snapshot phase while its manager/epoch remain
    // live. Owned vectors track per-shard chunks and post-cut task backlogs. Manager callbacks
    // publish prepare/freeze/mark/finish acknowledgements; local state gates mutation between
    // them. Serialization failure marks the manager failed and cancels captures before backlog
    // draining. A successful shutdown capture holds post-cut tasks until stop; failed shutdown
    // releases them. Returns progress and preserves unfinished work for the next pass.
    template <uint32_t BatchOps = kGenthreadExBatchOps, bool IofusedPrivateQueue = false>
    uint32_t snapshot_control_pass() {
        // Phase 1: handle shutdown holds and cancellation before advancing capture state.
        if (snapshot_owner_state_ == SnapshotOwnerState::None) return 0;
        // A shutdown snapshot counts capture completion without executing post-cut backlogs.
        // Success stops us before releasing this hold; failure releases it and resumes service.
        if (snapshot_owner_state_ == SnapshotOwnerState::ShutdownHeld) {
            if (srv_->shutdown_snapshot_active()) return 0;
            const uint32_t n = service_snapshot_backlogs<IofusedPrivateQueue>(BatchOps, false);
            if (snapshot_backlogs_empty()) {
                snapshot_owner_state_ = SnapshotOwnerState::None;
                snapshot_manager_ = nullptr;  // owner_finished was already counted on entry
                srv_->shutdown_snapshot_release();
            }
            return n;
        }
        SnapshotManager::Phase phase = snapshot_manager_->phase();
        if (phase == SnapshotManager::Phase::Failed &&
            snapshot_owner_state_ != SnapshotOwnerState::Draining) {
            for (Shard* shard : self_->shards()) shard->store().snapshot_cancel();
            snapshot_pending_chunks_.clear();
            snapshot_was_cancelled_ = true;
            snapshot_owner_state_ = SnapshotOwnerState::Draining;
            return 1;
        }

        // Phase 2: prepare stores, then acknowledge the freeze and shared snapshot cut.
        if (snapshot_owner_state_ == SnapshotOwnerState::Preparing) {
            auto& shards = self_->shards();
            if (snapshot_prepare_cursor_ < shards.size()) {
                FlatStore::SnapshotWriteResult result =
                    shards[snapshot_prepare_cursor_]->store().snapshot_prepare(snapshot_epoch_, 0);
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
        // Phase 3: capture bounded chunks, then discharge post-cut backlogs when permitted.
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
            const uint32_t n = service_snapshot_backlogs<IofusedPrivateQueue>(BatchOps, false);
            if (snapshot_backlogs_empty()) {
                if (snapshot_was_cancelled_)
                    snapshot_manager_->owner_cancelled(snapshot_epoch_);
                else
                    snapshot_manager_->owner_finished(snapshot_epoch_);
                snapshot_owner_state_ = SnapshotOwnerState::None;
                snapshot_manager_ = nullptr;
            }
            return n;
        }
        return 0;
    }

    void snapshot_capture_finished() {
        // Do this on the final-chunk pass, before its caller checks admission.
        // Going through Draining even for one turn admits Ready post-cut writes
        // whose acknowledged values cannot appear in the final snapshot.
        if (srv_->shutdown_snapshot_active()) {
            snapshot_owner_state_ = SnapshotOwnerState::ShutdownHeld;
            srv_->shutdown_snapshot_hold();
            snapshot_manager_->owner_finished(snapshot_epoch_);
        } else {
            snapshot_owner_state_ = SnapshotOwnerState::Draining;
        }
    }

    // Contract: the capturing owner advances at most one eligible shard per pass. Require a
    // live snapshot_manager_ and per-shard vectors initialized by begin_snapshot. The owner
    // holds each chunk until post_chunk accepts it, then records end-frame handoff. Full output
    // leaves the chunk pending; serialization failure fails the manager. Once all shards finish,
    // transition to backlog draining or the shutdown hold before admitting more tasks.
    uint32_t progress_snapshot_capture() {
        auto& shards = self_->shards();
        if (shards.empty()) {
            snapshot_capture_finished();
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
                if (!snapshot_manager_->post_chunk(self_->id(), pending, ring_, self_->sig()))
                    return work;
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
            snapshot_capture_finished();
        }
        return work;
    }

    bool snapshot_backlogs_empty() const {
        for (const auto& queue : snapshot_backlogs_)
            if (!queue.empty()) return false;
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
        // Pre-image preparation and backlog ownership belong to the current owner too.
        // execute()'s forwarding guard runs too late for this wrapper.
        if (forward_stale_task<IofusedPrivateQueue>(task)) return true;
        // MULTI's tagged task owns its command images outside the public ROB and performs the
        // snapshot pre-image gate per installed transaction key.  Never decode it as a normal op.
        if (multi_task_tagged(task)) return execute_resumed<IofusedPrivateQueue>(task);
        if (!task.client) return execute_resumed<IofusedPrivateQueue>(task);
        Op& op = task.client->rob().at(task.op_id);
        const int32_t sid = task.shard >= 0 ? task.shard : op.shard;
        Shard& shard = srv_->shard(sid);
        if (op.has_blocking_state()) {
            if (capture_writes) {
                const BlockingSnapshotPrepare result = blocking_snapshot_prepare(task, shard, op);
                if (result == BlockingSnapshotPrepare::Pending) return false;
                if (result == BlockingSnapshotPrepare::Error) {
                    snapshot_manager_->fail(snapshot_epoch_,
                                            "snapshot pre-image serialization failed");
                    return false;
                }
            }
            return execute_resumed<IofusedPrivateQueue>(task);
        }
        if (capture_writes && (op.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite))) {
            const FlatStore::SnapshotWriteResult result =
                task.scatter          ? xshard_snapshot_prepare(task, shard)
                : xshard_is_local(op) ? xshard_local_snapshot_prepare(op, shard)
                                      : snapshot_prepare_plain_write(op, shard);
            if (result == FlatStore::SnapshotWriteResult::Pending) return false;
            if (result == FlatStore::SnapshotWriteResult::Error) {
                snapshot_manager_->fail(snapshot_epoch_, "snapshot pre-image serialization failed");
                return false;
            }
        }
        if (!execute_resumed<IofusedPrivateQueue>(task)) return false;
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
        if (!xshard_retries_.empty()) {
            ordered_deferred_.push_back(task);
            return;
        }
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
                if (!execute_snapshot_task<IofusedPrivateQueue>(queue.front(), capture_writes))
                    break;
                queue.pop_front();
                budget--;
                n++;
            }
            if (!budget) break;
        }
        return n;
    }

    template <uint32_t BatchOps = kGenthreadExBatchOps, bool IofusedPrivateQueue = false>
    uint32_t drain_tasks_snapshot(bool unmasked = false) {
        // Bound each producer to one quantum. During capture, atomic_collapse cannot clean
        // pending MVCC entries, so hot-key write walks grow until snapshot_control_pass advances
        // capture between drains. An always-refilled lane must not monopolize the owner and
        // starve that progress, other producers or EXEC/WATCH/group retries. A capped lane is
        // re-flagged for the next pass. Owners without a snapshot use ordinary unbounded drains.
        auto take = [&](const Task& task) {
            refresh_command_clock();
            schedule_snapshot_task<IofusedPrivateQueue>(task);
        };
        const uint32_t n =
            unmasked ? self_->drain_tasks_unmasked_capped<IofusedPrivateQueue, BatchOps>(take)
                     : self_->drain_tasks_capped<IofusedPrivateQueue, BatchOps>(take);
        self_->sig().ops += n;
        // Retire at least as many deferred Tasks as this drain can add, plus one batch of old debt;
        // otherwise a saturated post-capture owner could remain in Draining forever.
        return n + service_snapshot_backlogs<IofusedPrivateQueue>(BatchOps + n);
    }

    // Keep exact-operation lifetime bookkeeping out of the batch-average arm.
    // It must not change the pipelined fast loop's register allocation.
    template <bool IofusedPrivateQueue = false>
    __attribute__((noinline, cold)) void exec_batch_exact(const Task* batch, uint32_t n,
                                                          const SlowlogArm& arm, int64_t now_ms) {
        if (slowlog_state_.escalate_batches) slowlog_state_.escalate_batches--;
        for (uint32_t i = 0; i < n; i++) {
            Client* client = batch[i].client;
            const uint64_t started = now_ns();
            SlowlogTiming timing(client ? &client->rob().at(batch[i].op_id) : nullptr,
                                 client ? client->id() : 0, self_->id(), started, now_ms, arm);
            const bool ok = execute_timed<IofusedPrivateQueue>(batch[i]);
            // The last owner records after the commit, before publishing Done.
            // Fast operations copy no argv and acquire no identity reference.
            flush_xshard_commits_timed();
            if (ok) continue;
            xshard_retries_.push_back(batch[i]);
            for (uint32_t j = i + 1; j < n; j++) ordered_deferred_.push_back(batch[j]);
            return;
        }
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
    __attribute__((noinline, cold)) static void exec_batch_timed(ExLoopT* loop, const Task* batch,
                                                                 uint32_t n) {
        Server::ClientWorkScope client_work(*loop->srv_, loop->self_->id());
        const SlowlogArm arm = loop->slowlog_arm_;
        const int64_t now_ms = loop->cached_now_ms_;
        slowlog_note_batch_timed();
        // Earlier service queues in this outer pass are not part of this batch's timing sample.
        loop->flush_xshard_commits();

        if (loop->slowlog_state_.escalate_batches || n == 1) {
            loop->template exec_batch_exact<IofusedPrivateQueue>(batch, n, arm, now_ms);
            return;
        }

        const uint64_t started = now_ns();
        uint32_t executed = n;
        for (uint32_t i = 0; i < n; i++) {
            if (loop->template execute<IofusedPrivateQueue>(batch[i])) continue;
            loop->xshard_retries_.push_back(batch[i]);
            for (uint32_t j = i + 1; j < n; j++) loop->ordered_deferred_.push_back(batch[j]);
            executed = i;
            break;
        }
        loop->flush_xshard_commits();
        const uint64_t elapsed = now_ns() - started;
        // The screen is per-op-average, not whole-batch: a full batch of ordinary commands must
        // not look like one slow command just because there were 32 of them.
        const uint64_t threshold_ns =
            arm.slowlog_us >= 0 ? static_cast<uint64_t>(arm.slowlog_us) * 1000 : UINT64_MAX;
        const uint64_t latency_ns =
            arm.latency_ms ? static_cast<uint64_t>(arm.latency_ms) * 1000000 : UINT64_MAX;
        const uint64_t bar = std::min(threshold_ns, latency_ns);
        if (executed && bar != UINT64_MAX && elapsed / executed >= bar) {
            loop->slowlog_state_.escalate_batches = kSlowlogEscalateBatches;
            slowlog_note_escalation();
        }
    }

    // The noinline/flatten boundary preserves nested bucket prefetches under release optimization
    // (compiler evidence is in docs/decisions/readability-a6.md). One call handles the whole batch;
    // execution, timing and suffix deferral keep that order. Ownership checks must match execution:
    // even a hint must not inspect a stale owner's mutable table. No store/slot pointer escapes.
    __attribute__((noinline, flatten)) void prefetch_owner_batch(const Task* batch, uint32_t n) {
#ifdef TOMO_OWNER_PREFETCH_WITNESS
        TOMO_OWNER_PREFETCH_WITNESS();
#endif
        for (uint32_t i = 0; i < n; i++) {
            if (!batch[i].client) continue;
            const Op& op = batch[i].client->rob().at(batch[i].op_id);
            const int32_t shard = batch[i].shard >= 0 ? batch[i].shard : op.shard;
            if (shard >= 0 && !batch[i].scatter && srv_->worker_of_shard(shard) == self_->id() &&
                !(op.spec->flags & (CmdFlags::CursorShard | CmdFlags::RandomShard)))
                srv_->shard(shard).store().prefetch(op.hash);
        }
    }

    // Prefetch multi-operation batches only in fused placement. Fused is a capability, so split
    // read-local owners must also test placement. Singletons and exact slowlog escalation skip
    // the walk. Selection needs no per-operation state or additional storage.
    bool owner_prefetch_enabled(uint32_t n) const {
        return (Fused && srv_->thread_mode() == ThreadMode::Fused) && n > 1 &&
               (!slowlog_armed_ || !slowlog_state_.escalate_batches);
    }

    // Consume a complete prefetched batch in its selected order. Both ordinary drain and
    // R7 submit whole batches here; completion notification ends before the
    // per-batch shard-size publication and atomic cleanup below.
    template <bool IofusedPrivateQueue = false>
    void exec_batch_prefetched(const Task* batch, uint32_t n) {
        if (!xshard_retries_.empty()) {
            for (uint32_t i = 0; i < n; i++) ordered_deferred_.push_back(batch[i]);
            return;
        }
        // All tasks in this batch were dequeued before this sample. Keep it
        // fixed throughout each command/script; MULTI and scatter retain their
        // operation-wide pins. Later local reads inherit this newer pass value.
        refresh_command_clock();
        {
            // Completion notification is coalesced over this loop and flushed when the scope
            // closes -- before the publish and reclamation work below, so the io is not made to
            // wait on either.
            NotifyBatchScope notify_batch(this);
            // THE ENTIRE DISABLED-FEATURE COST OF SLOWLOG/LATENCY: one predicted-false branch
            // here, once per batch of up to kExecBatch ops. No clock is read and the recorder is
            // not linked into this loop at all. The armed body is out of line in
            // exec_batch_timed().
            if (__builtin_expect(slowlog_armed_, false)) {
                timed_batch_<IofusedPrivateQueue>(this, batch, n);
            } else {
                for (uint32_t i = 0; i < n; i++) {
                    if (execute<IofusedPrivateQueue>(batch[i])) continue;
                    xshard_retries_.push_back(batch[i]);
                    for (uint32_t j = i + 1; j < n; j++) ordered_deferred_.push_back(batch[j]);
                    break;
                }
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

    // Whole-batch prefetch follows the gathered FIFO order.
    template <bool IofusedPrivateQueue = false, size_t BatchOps>
    void exec_batch(Task (&batch)[BatchOps], uint32_t n) {
        // Deferral first: skip wasted prefetch on the rare retry path.
        if (!xshard_retries_.empty()) {
            for (uint32_t i = 0; i < n; i++) ordered_deferred_.push_back(batch[i]);
            return;
        }
        if (__builtin_expect(owner_prefetch_enabled(n), false)) {
            prefetch_owner_batch(batch, n);
            exec_batch_prefetched<IofusedPrivateQueue>(batch, n);
            return;
        }
        exec_batch_prefetched<IofusedPrivateQueue>(batch, n);
    }

    // Execute/transfer one Task on its current owner; see ex_execute.inc for the full contract
    // and phases. true includes queued/parked work; false requires caller-owned retry and suffix
    // ordering. The ordinary specialization has no timing instrumentation; Done uses release.
    template <bool IofusedPrivateQueue = false, bool ReadLocalNoEvict = false>
    bool execute(const Task& t) {
        constexpr bool Timed = false;
        constexpr bool LatencyTracking = false;
#include "ex_execute.inc"
    }

    // Same ownership, retry and release-Done contract as execute. This cold specialization
    // completes exact slowlog timing before handing completion to persistence or the IO owner.
    template <bool IofusedPrivateQueue = false, bool ReadLocalNoEvict = false>
    __attribute__((noinline, cold)) bool execute_timed(const Task& t) {
        constexpr bool Timed = true;
        constexpr bool LatencyTracking = false;
#include "ex_execute.inc"
    }

    template <bool IofusedPrivateQueue = false, bool ReadLocalNoEvict = false>
    __attribute__((noinline, cold)) bool execute_latency(const Task& t);
    template <bool IofusedPrivateQueue = false>
    __attribute__((noinline, cold)) static void exec_batch_latency(ExLoopT* loop, const Task* batch,
                                                                   uint32_t n);
    using TimedBatch = void (*)(ExLoopT*, const Task*, uint32_t);
    template <bool IofusedPrivateQueue>
    static inline thread_local constinit
        __attribute__((tls_model("local-exec"))) TimedBatch timed_batch_ =
            exec_batch_timed<IofusedPrivateQueue>;

    template <bool IofusedPrivateQueue = false>
    __attribute__((noinline, cold)) bool execute_resumed_latency(const Task& task);
    template <bool IofusedPrivateQueue = false>
    __attribute__((always_inline)) bool execute_resumed(const Task& task) {
        if (__builtin_expect(slowlog_arm_.latency_tracking, false))
            return execute_resumed_latency<IofusedPrivateQueue>(task);
        return execute<IofusedPrivateQueue>(task);
    }

    template <bool IofusedPrivateQueue = false>
    __attribute__((noinline)) uint32_t service_xshard_retries() {
        if (xshard_retries_.empty()) return 0;
        const Task task = xshard_retries_.front();
        xshard_retries_.pop_front();
        const bool complete = snapshot_owner_state_ == SnapshotOwnerState::None
                                  ? execute_resumed<IofusedPrivateQueue>(task)
                                  : execute_snapshot_task<IofusedPrivateQueue>(task, true);
        if (!complete) xshard_retries_.push_back(task);
        return 1;  // one bounded KEYS pass (or one snapshot-gate attempt) per executor iteration
    }

    void note_lb_hash(Shard& shard, uint64_t hash) {
        if (!lb_sample_rate_) return;
        if (--lb_sample_countdown_ != 0) return;
        lb_sample_countdown_ = lb_sample_rate_;
        shard.note_lb_sample(hash, lb_sample_rate_);
    }

    void lb_bucket_bytes_pass() {
        if (!lb_sample_rate_ || cached_now_ms_ < lb_bytes_next_ms_) return;
        lb_bytes_next_ms_ = cached_now_ms_ + 10;
        const uint32_t rate = srv_->lb_sample_rate();
        if (rate != lb_sample_rate_) {
            lb_sample_rate_ = rate;
            lb_sample_countdown_ = rate;
        }
        auto& owned = self_->shards();
        if (owned.empty()) return;
        if (lb_bytes_shard_cursor_ >= owned.size()) lb_bytes_shard_cursor_ = 0;
        (void)owned[lb_bytes_shard_cursor_++]->lb_scan_bucket_bytes(64);
    }

    // Four two-key EXECs amortize a prefix collapse against eight-record walks.
    // Only transaction completion reaches this helper; ordinary command paths
    // do not acquire a cleanup clock/floor or update per-operation cleanup state.
    __attribute__((noinline)) void reclaim_multi_prefix(Shard& shard) {
        if (shard.store().atomic_live_records() < 8) return;
        const uint64_t cutoff = srv_->atomic_snapshot();  // must precede floor
        const uint64_t floor = srv_->atomic_read_floor();
        if (xshard_cleanup_shard_at(shard, floor, cutoff, 8))
            ++exec1s_counters[self_->id()].eager_collapses;
    }

    // Keep completion bookkeeping inside the transaction branch without
    // extending its result's live range across calls in ordinary dispatch.
    __attribute__((noinline)) MultiTaskResult finish_multi_store(Shard& shard,
                                                                 MultiTaskResult result) {
        if (result == MultiTaskResult::Complete || result == MultiTaskResult::Final)
            reclaim_multi_prefix(shard);
        // Expiry/object-byte statistics may change while the key count stays fixed.
        shard.publish_size();
        return result;
    }

    __attribute__((noinline)) MultiTaskResult execute_multi_unit(
        const Task& task, Shard& shard, void (*promote)(void*, MultiOwnerRetryNode&)) {
        AofOwnerContext context{self_->id(), &ring_, &self_->sig()};
        const MultiRetryPromoter promoter{
            this, promote, [](void* loop, const void* token, int32_t sid) {
                static_cast<ExLoopT*>(loop)->promote_deferred_writer(token, sid);
            }};
#ifdef TOMO_EXEC1S_DEBUG
        Exec1sVisitScope visits(self_->id());
#endif
        return multi_execute_task(*srv_, task, shard, self_->id(), self_->domain(),
                                  aof_manager_ ? &context : nullptr, &promoter);
    }

    __attribute__((noinline)) void queue_fast_multi_retry(const Task& task) {
        multi_retries_.enqueue(multi_owner_retry_node(task), task, true);
        ring_fused_owner();
    }
    __attribute__((noinline)) void queue_multi_retry(const Task& task) {
        multi_retries_.enqueue(multi_owner_retry_node(task), task, false);
    }
    void promote_deferred_writer(const void* token, int32_t sid) {
        if (atomic_deferred_.promote_writer(token, sid))
            srv_->note_txn(self_->id(), TxnCounter::WriterPromotions);
    }
    void promote_multi_retry(MultiOwnerRetryNode& node) {
        multi_retries_.make_runnable(node);
        ring_fused_owner();
    }

#include "ex_txn_chain.inc"

    template <bool IofusedPrivateQueue = false>
    uint32_t service_multi_retries() {
        if (multi_retries_.empty()) return 0;
        // Snapshot the fast prefix and reserve this pass's rotation head. Promotions and
        // demotions append behind it, so new readiness cannot extend the captured prefix.
        const bool nested = multi_retries_.chaining;
        multi_retries_.chaining = true;
        const uint32_t fast = multi_retries_.fast_count;
        const bool rotate = multi_retries_.rotation_head != nullptr;
        Task rotation{};
        if (rotate) rotation = multi_retries_.pop(false);
        for (uint32_t i = 0; i < fast && multi_retries_.fast_head; ++i) {
            service_txn_boundary<IofusedPrivateQueue>();
            if (!multi_retries_.fast_head) break;
            const Task task = multi_retries_.pop(true);
            srv_->note_txn(self_->id(), TxnCounter::FastPolls);
            execute_resumed<IofusedPrivateQueue>(task);
        }
        // Always advance the rotation too: a fast waiter may depend on it.
        if (rotate) execute_resumed<IofusedPrivateQueue>(rotation);
        multi_retries_.chaining = nested;
        return fast + rotate + service_multi_chain<IofusedPrivateQueue>();
    }

    // Owner-only bounded poll of each connection's oldest parked operation. Remove its indexes
    // before resuming execution can retire the Client/ROB; equal-op siblings rotate while held.
    // Count held heads as work because remote decisions do not necessarily wake this executor.
    // A failed execution transfers to xshard_retries_; younger same-key tasks cannot pass it.
    template <bool IofusedPrivateQueue = false>
    uint32_t service_atomic_deferred() {
        if (atomic_deferred_.empty()) return 0;
        // One oldest operation per connection per pass, bounded by the ordinary
        // owner batch. Followers cannot advance before this head's predecessor
        // publishes its decision. Do not walk or rotate through those followers.
        const uint32_t budget = std::min<size_t>(kExecBatch, atomic_deferred_.connections());
        uint32_t work = 0;
        while (work < budget && !atomic_deferred_.empty()) {
            const Task task = atomic_deferred_.oldest();
            ++exec1s_counters[self_->id()].parked_polls;
            ++work;
            Op& op = task.client->rob().at(task.op_id);
            const int32_t shard_id = task.shard >= 0 ? task.shard : op.shard;
            Shard& shard = srv_->shard(shard_id);
            shard.set_cached_now_ms(cached_now_ms_, cached_lru_clock_);
            if (has_parked_predecessor(task, op, shard_id) ||
                xshard_task_should_defer(*srv_, shard, task, op)) {
                atomic_deferred_.rotate_oldest();
                continue;
            }
            atomic_deferred_.pop_oldest();
            const bool complete = snapshot_owner_state_ == SnapshotOwnerState::None
                                      ? execute_resumed<IofusedPrivateQueue>(task)
                                      : execute_snapshot_task<IofusedPrivateQueue>(task, true);
            if (!complete) xshard_retries_.push_back(task);
        }
        // Count held heads as work so a remote decision cannot leave us asleep.
        return work;
    }

    // PROGRAM ORDER AGAINST EVERY PARKED PREDECESSOR, NOT JUST THE DEFERRED ONES.
    // Both queues hold tasks that have been taken off the inbox but have not finished, and both are
    // serviced ahead of a fresh drain, so a younger task from the same connection can reach a shard
    // before an older one that is sitting in either. xshard_retries_ matters as much as
    // atomic_deferred_ because a bounded KEYS walk lives there between passes: service_atomic_
    // deferred() runs first in the loop, so a younger write parked earlier could install a key
    // behind the walker's cursor and be reported by a listing that must not see it yet.
    // Both indexes are empty on any path with no cross-shard atomic window open.
    __attribute__((always_inline)) bool has_parked_predecessor(const Task& task, Op& op,
                                                               int32_t shard_id) {
        if (__builtin_expect(atomic_deferred_.empty() && xshard_retries_.empty(), true))
            return false;
        return parked_predecessor_in(atomic_deferred_, task, op, shard_id) ||
               parked_predecessor_in(xshard_retries_, task, op, shard_id);
    }

    __attribute__((noinline)) bool parked_predecessor_in(const AtomicParkedTasks& parked,
                                                         const Task& task, Op& op,
                                                         int32_t shard_id) {
        return parked.older(task.client, task.op_id, [&](const Task& older) {
            ++exec1s_counters[self_->id()].parked_visits;
            Op& older_op = older.client->rob().at(older.op_id);
            if (!xshard_tasks_share_key(older, older_op, task, op, shard_id)) return false;
            // Either direction is the scan-ordering hold: a walker held behind an older
            // write, or a younger write held behind a walk that is already in flight.
            if (xshard_task_is_whole_owner(older) || xshard_task_is_whole_owner(task))
                self_->note_atomic_scan_hold();
            return true;
        });
    }

    template <uint32_t BatchOps = kGenthreadExBatchOps, bool IofusedPrivateQueue = false>
    uint32_t service_ordered_deferred() {
        uint32_t work = 0;
        while (work < BatchOps && !ordered_deferred_.empty() && xshard_retries_.empty()) {
            const Task task = ordered_deferred_.front();
            ordered_deferred_.pop_front();
            if (snapshot_owner_state_ == SnapshotOwnerState::None) {
                if (!execute_resumed<IofusedPrivateQueue>(task)) xshard_retries_.push_back(task);
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
            return destination.post_iofused_task(self_->id(), task, handoff_ring(), self_->sig());
        } else {
            return destination.post_task(self_->id(), task, handoff_ring(), self_->sig());
        }
    }

    template <bool IofusedPrivateQueue = false>
    __attribute__((always_inline)) bool forward_stale_task(const Task& task) {
        const int32_t sid = task_shard(task);
        if (sid < 0) return false;
        const uint32_t target = srv_->worker_of_shard(sid);
        if (target == self_->id()) return false;
        if (!post_forwarded_task<IofusedPrivateQueue>(task, target)) stale_tasks_.push_back(task);
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

    // Owner-thread retry of refused forwarding, bounded by BatchOps across Tasks and releases.
    // Re-read each route before touching a store. A full destination preserves FIFO debt; a local
    // read fallback must republish at the inbox tail so it cannot pass earlier refused siblings.
    // Pop ownership only after successful handoff or before local execution; never drop a borrow
    // release. Shutdown snapshot holds prevent local task mutation until released.
    template <uint32_t BatchOps = kGenthreadExBatchOps, bool IofusedPrivateQueue = false>
    uint32_t service_stale_forwards() {
        uint32_t work = 0;
        while (!stale_tasks_.empty() && work < BatchOps) {
            const Task task = stale_tasks_.front();
            const int32_t sid = task_shard(task);
            if (sid < 0) std::abort();
            const uint32_t target = srv_->worker_of_shard(sid);
            if (target == self_->id()) {
                if (shutdown_snapshot_blocks_tasks()) break;
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
                if (!execute_resumed<IofusedPrivateQueue>(task)) xshard_retries_.push_back(task);
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
    __attribute__((noinline)) void flush_xshard_commits() { flush_xshard_commits_impl<false>(); }
    __attribute__((always_inline)) void flush_xshard_commits_timed() {
        flush_xshard_commits_impl<true>();
    }
    template <bool Timed>
    __attribute__((always_inline)) void flush_xshard_commits_impl() {
        if (__builtin_expect(!xshard_commit_pending_, true)) return;
        // Keep both the queue and its pending-work bit armed. The owner continues servicing
        // CONFIG and foreign work, and cannot park while the test holds these decisions open.
        if (__builtin_expect(srv_->debug_atomic_commit_hold(), false)) return;
        Server::ClientWorkScope client_work(*srv_, self_->id());
        const auto flush = [] {
            if constexpr (Timed)
                return xshard_flush_commits_timed;
            else
                return xshard_flush_commits;
        }();
        flush(*srv_, *self_, ring_, this, [](void* context, Client* client) {
            static_cast<ExLoopT*>(context)->notify_sender(client);
        });
        xshard_commit_pending_ = false;
    }

    // Tell this client's io thread it has completed ops -- it retires the ROB and writes, so it is
    // what needs waking. Deduplicated: a pipelined burst of N completions on one client must not
    // enqueue it N times.
    __attribute__((always_inline)) void notify_sender(Client* c) {
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
        // A ready-slot assignment lets completion signal an idempotent bit with no Client
        // pointer in flight. The empty-to-flagged RMW orders the park check; the thread that
        // creates that edge owes the conditional wake.
        const uint32_t slot = c->wb_slot();
        if (slot != Client::kNoWbSlot) {
            // INSIDE AN EXECUTOR BATCH: record and return. The fence, the read-first set and the
            // wake decision are paid once per batch in flush_notify_batch(). A batch of one op
            // degrades to exactly the sequence below it.
            if (__builtin_expect(notify_batch_open_, true)) {
                if (__builtin_expect(notify_batch_n_ == kNotifyBatchMax, false))
                    flush_notify_batch();
                notify_batch_[notify_batch_n_++] = NotifyEntry{target, slot};
                return;
            }
            ThreadCtx& snd = srv_->thread(target);
            // Fence Done before ReadyMask::set's relaxed read-first check. TSO otherwise lets
            // that load precede the store draining: it can see a stale set bit while the sender
            // consumes the previous signal, skip our set, and leave the sender seeing no Done
            // and no future notification. The seq_cst fence closes that store/load window.
            std::atomic_thread_fence(std::memory_order_seq_cst);
            if (snd.ready().set(slot)) snd.wake_if_parked(handoff_ring(), self_->sig());
            return;
        }
        // No ready slot: use the claimed channel post. This remains the completion route
        // for a connection while the sender's ready-slot table is full.
        notify_sender_to(c, target);
    }

    void notify_sender_to(Client* c, uint32_t target) {
        bool expected = false;
        if (!c->retire_queued().compare_exchange_strong(expected, true,
                                                        std::memory_order_acq_rel)) {
            return;
        }
        ThreadCtx& snd = srv_->thread(target);
        if (!snd.post_client(self_->id(), c, handoff_ring(), self_->sig())) {
            self_->sig().notify_drop++;
            srv_->defer_completion_notice(self_->id(), c);  // keep the claim; reposted per pass
        }
    }

    // Reposts the completion notices a full EX->IO channel refused (Server::notify_retries).
    // Counted as work while any is queued: never park on one, never spin in place on a full
    // channel (two fused threads could each wait on the other's). The IO cannot park on a
    // non-empty channel, so a repost succeeds once it drains.
    __attribute__((noinline, cold)) uint32_t service_notify_retries() {
        auto& queue = srv_->notify_retries(self_->id());
        size_t kept = 0;
        for (Client* c : queue) {
            ThreadCtx& sender = srv_->thread(c->ifid_thread());
            if (!sender.post_client(self_->id(), c, handoff_ring(), self_->sig()))
                queue[kept++] = c;
        }
        queue.resize(kept);
        return 1;
    }
    bool notify_retries_pending() { return !srv_->notify_retries(self_->id()).empty(); }

    // Batch end (or a full record): ONE fence covering every Done store of the batch, then the
    // same read-first set per recorded client run that the per-op path performs, then one wake
    // decision per io that saw an empty->flagged edge. Deciding the wake once per io AFTER all of
    // its RMWs is equivalent to deciding it per edge: every RMW is a full barrier ahead of the
    // parked_ load, so the Dekker pair with ThreadCtx::arm_blocked closes for each edge on its
    // own. The wake is never memoised across flushes -- a cached "already
    // woke this io" could straddle a park/unpark cycle of the consumer and miss its second park.
    void flush_notify_batch() {
        const uint32_t n = notify_batch_n_;
        if (!n) return;
        notify_batch_n_ = 0;
        std::atomic_thread_fence(std::memory_order_seq_cst);
        constexpr uint32_t kEdgeWords = (kMaxThreads + 63) / 64;
        uint64_t edged[kEdgeWords] = {};
        uint32_t prev_io = UINT32_MAX;
        uint32_t prev_slot = UINT32_MAX;
        for (uint32_t i = 0; i < n; i++) {
            const NotifyEntry e = notify_batch_[i];
            // A connection's completions arrive in runs, so the adjacent skip removes nearly
            // every repeat; a non-adjacent repeat costs one L1-hit load and is idempotent.
            if (e.io == prev_io && e.slot == prev_slot) continue;
            prev_io = e.io;
            prev_slot = e.slot;
            if (srv_->thread(e.io).ready().set(e.slot))
                edged[e.io >> 6] |= uint64_t{1} << (e.io & 63);
        }
        for (uint32_t w = 0; w < kEdgeWords; w++) {
            uint64_t bits = edged[w];
            while (bits) {
                const uint32_t b = static_cast<uint32_t>(__builtin_ctzll(bits));
                bits &= bits - 1;
                srv_->thread(w * 64 + b).wake_if_parked(handoff_ring(), self_->sig());
            }
        }
    }

    // Contract: same-thread scope borrowing the executor's completion record. Destruction
    // restores the enclosing open state and flushes with a seq_cst fence before ready-bit
    // publication/wakes. Nested scopes may flush early; records hold ids, never Client pointers.
    // The executor must outlive the scope. Full records flush in place instead of allocating.
    struct NotifyBatchScope {
        ExLoopT* loop;
        bool was_open;
        explicit NotifyBatchScope(ExLoopT* l) : loop(l), was_open(l->notify_batch_open_) {
            loop->notify_batch_open_ = true;
        }
        ~NotifyBatchScope() {
            loop->notify_batch_open_ = was_open;
            loop->flush_notify_batch();
        }
        NotifyBatchScope(const NotifyBatchScope&) = delete;
        NotifyBatchScope& operator=(const NotifyBatchScope&) = delete;
    };

    void on_cqe(io_uring_cqe* cqe) {
        // Dispatch wake, snapshot-start, database and shutdown events; executors issue no sends.
        if (ur_kind(cqe->user_data) == UrKind::Wake)
            self_->sig().wakes_recv++;
        else if (ur_kind(cqe->user_data) == UrKind::SnapshotStart)
            begin_snapshot(ur_ptr<SnapshotManager>(cqe->user_data));
        else if (ur_kind(cqe->user_data) == UrKind::DatabaseWake)
            srv_->databases().consume_wake(self_->id(), ring_);
        else if (ur_kind(cqe->user_data) == UrKind::Shutdown) {
            if (!self_->stop_flag().load(std::memory_order_relaxed)) ring_.rearm_shutdown_poll();
        }
    }

    Server* srv_ = nullptr;
    ThreadCtx* self_ = nullptr;
    Ring ring_;
    int64_t cached_now_ms_ = 0;
    int64_t blocking_beat_ms_ = 0;
    size_t expire_shard_cursor_ = 0;
    size_t atomic_cleanup_cursor_ = 0;
    uint64_t live_config_version_ = UINT64_MAX;
    AofManager* aof_manager_ = nullptr;
    bool maxmemory_enabled_ = false;
    uint8_t retired_reorder_padding_ = 0;  // preserve cached_lru_clock_ and later offsets
    uint8_t cached_lru_clock_ = 0;
    uint32_t lb_sample_rate_ = 0;
    uint32_t lb_sample_countdown_ = 0;
    uint32_t age_sample_rate_cached_ = 0;
    bool lb_controller_armed_ = false;
    bool lb_ack_wake_pending_ = false;
    bool lb_rebind_pending_ = false;  // set at ExDrain ack; rebind owned shards after stage
    // These policy/debug values fill the alignment region before the following int64. They
    // are latched with live configuration and used behind maxmemory/debug arming gates.
    uint8_t foreign_touch_policy_ = kForeignTouchNone;  // see note_local_read_access()
    // TEST HOOK (DEBUG ATOMIC-FANOUT-DEFER), read-local half; production 0. See
    // debug_fanout_stall_local().
    uint32_t debug_fanout_defer_us_ = 0;
    int64_t lb_bytes_next_ms_ = 0;
    size_t lb_bytes_shard_cursor_ = 0;
    // LFU logarithmic-increment dice for a lane-served read, per thread: the store's PRNG belongs
    // to its owner and must not be advanced by a foreign reader.
    uint64_t foreign_touch_random_ = 0x9e3779b97f4a7c15ULL;
    SnapshotManager* snapshot_manager_ = nullptr;
    SnapshotOwnerState snapshot_owner_state_ = SnapshotOwnerState::None;
    uint32_t expire_beat_ms_ = 0;  // occupies the alignment region before snapshot_epoch_
    uint64_t snapshot_epoch_ = 0;
    bool snapshot_was_cancelled_ = false;
    uint32_t keyspace_shard_cursor_ = 0;  // shares the snapshot control-state header
    size_t snapshot_prepare_cursor_ = 0;
    size_t snapshot_progress_cursor_ = 0;
    std::vector<uint8_t> snapshot_done_shards_;
    std::vector<std::unique_ptr<SnapshotChunk>> snapshot_pending_chunks_;
    std::vector<std::deque<Task>> snapshot_backlogs_;
    AtomicParkedTasks atomic_deferred_;
    TxnRetryQueues multi_retries_;
    AtomicParkedTasks xshard_retries_;
    std::deque<Task> ordered_deferred_;
    // Backpressure cannot turn a stale route into a dropped request/release. These queues contain
    // objects for shards this loop no longer owns and are serviced before ordinary inbox work.
    std::deque<Task> stale_tasks_;
    std::deque<BorrowRelease> stale_releases_;
    bool notify_keyless_pending_ = false;
    bool initialized_ = false;
    // Cold slowlog state: slowlog_armed_ gates timing once per batch when the feature is off.
    bool slowlog_armed_ = false;
    SlowlogArm slowlog_arm_{};
    SlowlogExState slowlog_state_{};
    // Completion callbacks are used only by fused-capable executors; common fields precede them.
    uint32_t fused_idle_spins_ = 0;
    void* fused_io_context_ = nullptr;
    FusedCompletionFn fused_completion_ = nullptr;
    // An empty commit queue needs only the boundary flag test; ordinary commands do not touch
    // the TLS commit list.
    bool xshard_commit_pending_ = false;
    // Per-batch completion notification. While a batch is open, the slot
    // path of notify_sender records (io, slot) here instead of fencing and setting per op; the
    // batch end pays ONE seq_cst fence, one ReadyMask::set per recorded client run and one wake
    // decision per io that saw an empty->flagged edge. Sized to this loop's largest batch; the
    // record never holds more than one entry per executed task, and a full record flushes in
    // place regardless. (io, slot), never Client*: the flush may run a whole batch after the Done
    // store, and a connection is only guaranteed allocated until the io's second reap prologue
    // after close.
    // Thread-owned completion identity, copied into the batch record. It deliberately owns no
    // Client reference: the IO owner can retire/reap a Client before this batch flushes.
    struct NotifyEntry {
        uint32_t io;
        uint32_t slot;
    };
    static constexpr uint32_t kNotifyBatchMax = kGenthreadExBatchOps;
    bool notify_batch_open_ = false;
    uint32_t notify_batch_n_ = 0;
    NotifyEntry notify_batch_[kNotifyBatchMax] = {};
    [[no_unique_address]] ReadLocalExState<Fused> read_local_;
    // Explicit tail padding is part of the executor layout contract.
    uint32_t multi_retry_layout_pad_ = 0;  // preserves following offsets
public:
    // R7 bodies are isolated from the FIFO translation units.
    // clang-format off
// BEGIN R7 GENERATED ENVELOPES
    uint32_t  r7_fused_baseline_pass();
    template <uint32_t BatchOps, bool ConsumeTasks, bool IofusedPrivateQueue = false,
                  bool InterleaveLocalReads = false>
        uint32_t  r7_fused_pass_impl();
    uint32_t  r7_fused_baseline_sweep();
    template <uint32_t BatchOps, bool ConsumeTasks, bool IofusedPrivateQueue = false,
                  bool InterleaveLocalReads = false>
        uint32_t  r7_fused_sweep_impl();
    template <uint32_t BatchOps = kGenthreadExBatchOps, bool ConsumeTasks = true,
                  bool IofusedPrivateQueue = false, bool InterleaveLocalReads = false>
        uint32_t  r7_sweep();
// END R7 GENERATED ENVELOPES
    // clang-format on
    template <uint32_t BatchOps = kGenthreadExBatchOps, bool IofusedPrivateQueue = false>
    __attribute__((noinline)) uint32_t r7_drain_tasks(bool unmasked = false);
    template <bool Shadow, uint32_t BatchOps, bool IofusedPrivateQueue>
    uint32_t r7_drain_tasks_impl(bool unmasked);
};

using ExLoop = ExLoopT<false>;
template <>
uint32_t ExLoopT<true>::split_read_local_pass();
using FusedExLoop = ExLoopT<true>;

// Layout contract: both modes carry 32 notification entries. The fused-capable executor's
// additional state is one eight-byte read-local implementation pointer. Historical layout
// comparisons are archived in docs/decisions/readability-a6.md; these assertions define the size.

static_assert(sizeof(ExLoop) == 5856);
static_assert(sizeof(FusedExLoop) == 5864);

}  // namespace tomo
