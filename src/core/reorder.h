// reorder.h -- fused owner-local shadow priority and sampled AUTO policy.
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <new>
#include <type_traits>
#include "genthread_pipeline.h"
#include "thread.h"
#include "orthog.h"
#include "../net/conn.h"
#include "../cmd/command.h"

namespace tomo::r7 {

inline constexpr uint32_t kExSchedClasses =
    static_cast<uint32_t>(CommandLengthClass::Count);
inline constexpr uint32_t kExReorderSpecial =
    CmdFlags::Admin | CmdFlags::ConnLocal | CmdFlags::AllShards | CmdFlags::RandomShard |
    CmdFlags::CursorShard | CmdFlags::ConfigRoute | CmdFlags::ScriptRoute |
    CmdFlags::PubSub | CmdFlags::Blocking | CmdFlags::Transaction |
    CmdFlags::StreamRoute | CmdFlags::SubcmdRoute | CmdFlags::FlipAsync;

// Only the ordinary one-owner path participates. Every existing special mechanism is a hard
// barrier in the incoming sequence: queued ordinary work drains before it executes.
inline bool candidate(const Task& task, uint8_t& length) {
    if (!task.client || task.scatter) return false;
    const Op& op = task.client->rob().at(task.op_id);
    if (!op.spec || op.has_blocking_state()) return false;
    // MultiShard is deliberately absent: a same-owner MGET/MSET local-fast task is ordinary
    // here. A real scatter has task.scatter set and returned above.
    if (op.spec->flags & kExReorderSpecial) return false;
    length = static_cast<uint8_t>(command_length_class(*op.spec));
    if (__builtin_expect(length >= kExSchedClasses, false)) return false;
    // There is no O(1) class pointer from an op to an exact parked atomic predecessor. The
    // immutable publish-time hazard bit says an older own atomic group existed; Long is the
    // safe upper bound without a deque scan or a per-connection scheduler table.
    if (op.atomic_hazard()) length = static_cast<uint8_t>(CommandLengthClass::Long);
    return true;
}

// R7's candidate service ratio matches the deciding 8:2 short/long mix. This is a
// inherited fairness constant, NOT a measured optimum. No ratio knob is exposed.
inline constexpr uint32_t kExReorderShortQuota = 4;

// The kind-A control changes only this out-of-line predicate. It leaves R7 enabled.
bool shadow_available();

// Ordinary tasks already use a negative shard to mean "resolve Op::shard". Keep that
// meaning and carry SHADOW plus the distance to the preceding long in the otherwise
// unused negative payload. Scatter/transaction/blocking tasks are never stamped.
// A live ROB contains at most 64 slots, so six distance bits suffice. Nothing in Op,
// Client, Rob, the inbox stride, or a shard's ownership state grows.
inline constexpr uint32_t kShadow = 1;
inline bool shadow_bit(const Task& task) {
    return task.shard < 0 && (static_cast<uint32_t>(~task.shard) & kShadow);
}
inline uint64_t shadow_id(const Task& task) {
    return task.op_id - (static_cast<uint32_t>(~task.shard) >> 1);
}
inline bool shadow_pending(const Task& task) {
    if (!shadow_bit(task)) return false;
    const uint64_t id = shadow_id(task);
    auto& rob = task.client->rob();
    if (id < rob.flush_id()) return false;
    // Read ONLY the atomic state of a predecessor, never its recycled spec/argv.
    // Recheck retirement if IO recycled it between the first load and the state load.
    // There is no spin/retry and no reader-side synchronization protocol.
    return rob.at(id).state.load(std::memory_order_acquire) != OpState::Done &&
           id >= rob.flush_id();
}

// One instance per armed parse pass, on the connection's IO thread. IO owns ROB
// recycling, so this bounded entry scan can safely read immutable command specs.
// Reconstructing the newest in-flight long at the pass boundary needs no persistent
// Client sidecar and automatically follows client migration. The per-op stamp captures
// its OWN preceding long: a later long cannot unshadow already dispatched operations.
class ShadowDispatch {
    uint64_t newest_ = UINT64_MAX;
    static bool length(const Op& op, uint8_t& result) {
        // Only parser-published immutable metadata may be read while another
        // executor runs this op. candidate() also reads reply-state markers and
        // route_flags_ (GET can set no-borrow in that byte), so it is NOT safe here.
        // LONG means the registered command class; atomic_hazard still retains
        // R7's conservative Long execution rank, independently of the shadow hint.
        if (!op.spec || (op.spec->flags & kExReorderSpecial)) return false;
        result = static_cast<uint8_t>(command_length_class(*op.spec));
        return result < kExSchedClasses;
    }
public:
    explicit ShadowDispatch(Client& client, uint64_t before = UINT64_MAX) {
        TOMO_R7_PATH();
        auto& rob = client.rob();
        const uint64_t first = rob.flush_id();
        for (uint64_t end = std::min(before, rob.dispatch_id()); end > first;) {
            const uint64_t id = --end;
            const Op& op = rob.at(id);
            if (op.state.load(std::memory_order_acquire) == OpState::Done) continue;
            uint8_t kind;
            if (length(op, kind) && kind == static_cast<uint8_t>(CommandLengthClass::Long)) {
                newest_ = id;
                break;
            }
        }
    }
    void stamp(Task& task) {
        TOMO_R7_PATH();
        uint8_t kind;
        if (!task.client || task.scatter || !length(task.client->rob().at(task.op_id), kind)) return;
        if (kind == static_cast<uint8_t>(CommandLengthClass::Long)) {
            newest_ = task.op_id;
        } else if (newest_ < task.op_id) {
            const uint64_t distance = task.op_id - newest_;
            // A predecessor can retire during this parse pass. Outside the live window
            // it has certainly completed; do not encode a wrapped distance.
            if (distance < kRobWindow)
                task.shard = ~static_cast<int32_t>((distance << 1) | kShadow);
        }
    }
};

// A pending local read can be lowered AFTER a later ordinary op was dispatched.
// Reconstruct only its older prefix on its IO owner, never use a younger Long.
inline Task shadow_demoted_task(Client* client, uint64_t id) {
    TOMO_R7_PATH();
    Task task(client, id, -1, nullptr);
    ShadowDispatch dispatch(*client, id);
    dispatch.stamp(task);
    return task;
}

struct QueueSample {
    uint32_t depth = 0, shorts = 0, longs = 0, behind = 0;
};

// The owner is the sole consumer while this runs. The existing acquire-tail
// observer pins queued handles without consuming them or reading a running Op.
// A bounded prefix sample visits the same producer order as drain_tasks.
// Shorts counted here are live ROB heads: their own pipe cannot hide a predecessor.
struct InboxProbe {
    static QueueSample sample(ThreadCtx& owner) {
        TOMO_R7_PATH();
        QueueSample result;
        uint32_t budget = 2 * kGenthreadExBatchOps;
        bool have_long = false;
        for (uint32_t p = 0; p < owner.nchan_; ++p) {
            result.depth += owner.task_in_->depth(p);
            if (!budget) continue;
            budget -= owner.task_in_->observe_prefix(p, budget, [&](const Task& task) {
                uint8_t length;
                if (!candidate(task, length)) have_long = false; // hard barrier
                else if (length == static_cast<uint8_t>(CommandLengthClass::Long)) {
                    ++result.longs;
                    have_long = true;
                } else {
                    ++result.shorts;
                    result.behind += have_long && task.op_id == task.client->rob().flush_id();
                }
            });
        }
        return result;
    }
};

// One window of the existing signal beat, with one sample per gather slot.
// Thresholds are observations, not a core count, rate, time budget or tuned mix:
// (1) current depth must reach the window's mean depth; (2) displaced short heads
// must outnumber Longs over the window; (3) the current sample must still witness
// a short head behind a Long. A missing witness disengages on this very tick.
class AutoPolicy {
    static constexpr uint32_t Window = kGenthreadExBatchOps;
    QueueSample window_[Window]{};
    uint64_t depth_ = 0, longs_ = 0, behind_ = 0;
    uint32_t next_ = 0, samples_ = 0;
    bool engaged_ = false;
public:
    bool engaged() const { return engaged_; }
    uint32_t depth_threshold() const {
        return samples_ ? static_cast<uint32_t>((depth_ + samples_ - 1) / samples_) : 0;
    }
    bool observe(QueueSample sample) {
        TOMO_R7_PATH();
        const auto old = window_[next_];
        depth_ = depth_ - old.depth + sample.depth;
        longs_ = longs_ - old.longs + sample.longs;
        behind_ = behind_ - old.behind + sample.behind;
        window_[next_] = sample;
        next_ = (next_ + 1) % Window;
        samples_ = std::min(samples_ + 1, Window);
        engaged_ = samples_ == Window && sample.behind &&
                   sample.depth >= depth_threshold() && behind_ > longs_;
        return engaged_;
    }
    void tick(ThreadCtx& owner, ModeScheduleStats& stats) {
        TOMO_R7_PATH();
        const bool was_engaged = engaged_;
        observe(InboxProbe::sample(owner));
        const uint64_t old = stats.reorder_auto.load(std::memory_order_relaxed);
        const uint64_t ticks = std::min((old >> 32) + 1, uint64_t{UINT32_MAX});
        const uint64_t engagements = std::min(((old >> 1) & 0x7fffffffull) +
            (engaged_ && !was_engaged), 0x7fffffffull);
        stats.reorder_auto.store((ticks << 32) | (engagements << 1) | engaged_,
                                  std::memory_order_relaxed);
    }
};

// Stack lifetime is one armed fused IO tenure. No pointers, tasks or per-shard
// state survive a role boundary. INFO reads only the separate atomic diagnostic.
class PolicyScope {
    ModeScheduleStats& stats_;
public:
    AutoPolicy policy;
    explicit PolicyScope(ModeScheduleStats& stats) : stats_(stats) {
        TOMO_R7_PATH();
        if (stats_.reorder_policy) std::abort();
        stats_.reorder_policy = &policy;
    }
    ~PolicyScope() {
        stats_.reorder_policy = nullptr;
        stats_.reorder_auto.store(stats_.reorder_auto.load(std::memory_order_relaxed) & ~1ull,
                                  std::memory_order_relaxed);
    }
};

inline bool priority_enabled(const ModeScheduleStats& stats, int32_t requested) {
    TOMO_R7_PATH();
    if (requested != -1) return requested != 0;
    const auto* policy = static_cast<const AutoPolicy*>(stats.reorder_policy);
    return policy && policy->engaged();
}

// These queues live for ONE inbox drain, across its gathered batches. finish() is mandatory
// before local-read service, snapshot/control work, LB acknowledgement, or returning to IO.
// Thus no queued Task survives a shard/role ownership edge, and no new migration sidecar exists.
// At most one batch of debt survives an admission; a second batch supplies the lookahead.
//
// A short entry must be a live ROB head. Any invisible predecessor (including an earlier
// batch, a gap, or an undecided atomic group) conservatively makes the entry long. Long FIFO
// entries also remember the short-tail frontier at admission: service MUST consume that prefix
// before selecting the long entry, even when its ratio turn is due. This is necessary because
// a long successor may follow its own short head. Both rules together preserve connection
// order without consulting recycled predecessors or maintaining a per-connection hash table.
// The frontier can postpone a ratio turn, but newly admitted shorts cannot extend its debt.
//
// Queue cursors, the service quota and this dependency frontier are the mechanism's bookkeeping;
// there are no per-op clocks, atomic updates, allocations, telemetry counters or Client/Op fields.
// Costs and the conservative non-head classification still require S4 measurement.
template <size_t BatchOps>
class ExReorderQueues {
    static_assert(BatchOps == kGenthreadExBatchOps ||
                  BatchOps == kGenthreadPipelineExBatchOps);
    static constexpr uint32_t Capacity = 2 * BatchOps;
    static_assert((Capacity & (Capacity - 1)) == 0);
    static_assert(std::is_trivially_destructible_v<Task>);

    // Default-constructing Task arrays would clear every unused slot at every drain. Activate
    // only the occupied union member; Task has no destructor work when a ring slot is reused.
    union Slot {
        Task task;
        Slot() {}
        ~Slot() {}
    };
    Slot short_tasks_[Capacity];
    Slot long_tasks_[Capacity];
    uint64_t long_frontier_[Capacity];
    uint64_t short_head_ = 0, short_tail_ = 0;
    uint64_t long_head_ = 0, long_tail_ = 0;
    uint32_t short_quota_ = kExReorderShortQuota;

    static uint32_t slot(uint64_t cursor) { return cursor & (Capacity - 1); }

    void append(const Task& task, uint8_t length) {
        if (__builtin_expect(size() == Capacity, false)) std::abort();
        const bool is_short = length < static_cast<uint8_t>(CommandLengthClass::Long) &&
                              task.op_id == task.client->rob().flush_id();
        if (is_short) {
            new (&short_tasks_[slot(short_tail_)].task) Task(task);
            short_tail_++;
        } else {
            const uint32_t at = slot(long_tail_);
            new (&long_tasks_[at].task) Task(task);
            long_frontier_[at] = short_tail_;
            long_tail_++;
        }
    }

    ReorderResult take(Task* output, uint32_t n) {
        if (__builtin_expect(n > size(), false)) std::abort();
        ReorderResult result;
        for (uint32_t i = 0; i < n; i++) {
            const bool have_short = short_head_ != short_tail_;
            const bool have_long = long_head_ != long_tail_;
            const uint32_t at = slot(long_head_);
            if (have_short && have_long && !result.multi_client_runs)
                result.multi_client_runs =
                    short_tasks_[slot(short_head_)].task.client != long_tasks_[at].task.client;
            if (have_short && (!have_long || short_quota_ ||
                               short_head_ < long_frontier_[at])) {
                // This exact queue pick passes a still-pending earlier long entry. A coarse
                // class mix alone is not a permutation witness (quota/dependency can keep FIFO).
                if (have_long && short_head_ >= long_frontier_[at])
                    result.permuted_runs = 1;
                output[i] = short_tasks_[slot(short_head_++)].task;
                if (short_quota_) short_quota_--;
            } else {
                output[i] = long_tasks_[at].task;
                long_head_++;
                short_quota_ = kExReorderShortQuota;
            }
        }
        return result;
    }

    template <typename Emit>
    void emit_queued(uint32_t n, Emit& emit) {
        Task output[BatchOps];
        const ReorderResult result = take(output, n);
        // The callback can publish Done and let IO recycle/free completed slots and Clients.
        // All classification and witness reads precede it; afterward only cursors remain live.
        emit(output, n, result);
    }

public:
    ExReorderQueues() { TOMO_R7_PATH(); }
    ExReorderQueues(const ExReorderQueues&) = delete;
    ExReorderQueues& operator=(const ExReorderQueues&) = delete;
    ~ExReorderQueues() { if (size()) std::abort(); }

    uint32_t size() const {
        return static_cast<uint32_t>((short_tail_ - short_head_) + (long_tail_ - long_head_));
    }

    template <typename Emit>
    void finish(Emit& emit) {
        while (size()) emit_queued(std::min<uint32_t>(BatchOps, size()), emit);
        short_quota_ = kExReorderShortQuota;
    }

    // Admission is a batch decision. Empty-queue one-client and homogeneous coarse-class runs
    // retain their original Task span: no queue entries, head loads or ratio picks. When debt
    // exists, the same input must join the queues so it cannot jump a queued own predecessor.
    template <typename Emit>
    void submit(const Task* tasks, uint32_t n, Emit& emit) {
        if (__builtin_expect(n > BatchOps, false)) std::abort();
        if (!n) return;
        if (!size()) {
            uint32_t same_client = 1;
            while (same_client < n && tasks[same_client].client == tasks[0].client)
                same_client++;
            if (same_client == n) {
                emit(tasks, n, ReorderResult{});
                return;
            }
        }
        uint8_t lengths[BatchOps];
        uint32_t begin = 0;
        while (begin < n) {
            if (!r7::candidate(tasks[begin], lengths[begin])) {
                finish(emit);
                emit(tasks + begin, 1, ReorderResult{});
                begin++;
                continue;
            }
            uint32_t end = begin + 1;
            bool one_client = true, one_class = true;
            const bool first_long = lengths[begin] ==
                static_cast<uint8_t>(CommandLengthClass::Long);
            while (end < n && r7::candidate(tasks[end], lengths[end])) {
                one_client &= tasks[end].client == tasks[begin].client;
                one_class &= (lengths[end] == static_cast<uint8_t>(CommandLengthClass::Long)) ==
                             first_long;
                end++;
            }
            if (!size() && (one_client || one_class)) {
                emit(tasks + begin, end - begin,
                     ReorderResult{static_cast<uint32_t>(!one_client), 0});
            } else {
                for (uint32_t i = begin; i < end; i++) append(tasks[i], lengths[i]);
                if (size() > BatchOps) emit_queued(size() - BatchOps, emit);
            }
            // The first failed candidate is a barrier. Drain before it without inspecting its
            // Op again; never retain a borrowed Op pointer across a callback publishing Done.
            if (end < n) {
                finish(emit);
                emit(tasks + end, 1, ReorderResult{});
            }
            begin = end + (end < n);
        }
    }
};

// Shadow policy: only the front of each connection is eligible, in one of three
// ready FIFOs: unshadowed short, long, shadowed short. Successors become eligible
// in output order; this preserves write/RYOW order even for L s L on one owner.
// All scratch dies at finish(), exactly like the inherited two-queue scheduler.
//
// Fairness uses R7's one-batch carry and its ratio, not a clock or a new knob.
// Give a newly opened scope B priority picks (so the entire three-pipe example
// follows the requested priority order), then force the oldest queued task after
// each Q=4 priority picks. The oldest is always a connection head. With C=2B live
// slots, an admitted task has <=C-1 older tasks; later arrivals cannot get ahead
// of it on forced turns. It is selected within K=B+C*(Q+1) picks, including its
// own pick: 352 at B=32, 1408 at B=128. Admission is bounded by C as in R7.
// This is a pick bound, not a wall-time promise about long handlers/atomic waits.
template <size_t BatchOps>
class ShadowReorderQueues {
    static_assert(BatchOps == kGenthreadExBatchOps ||
                  BatchOps == kGenthreadPipelineExBatchOps);
    static constexpr uint32_t Capacity = 2 * BatchOps;
    using Index = uint16_t;
    static constexpr Index None = UINT16_MAX;
    static_assert(Capacity < None);
    static constexpr uint32_t TableSize = 2 * Capacity;
    struct Node {
        Task task;
        Index older, newer, next_conn, hash_next;
        Index prev_ready = None, next_ready = None;
        uint8_t length, rank;
    };
    union Slot { Node node; Index next_free; Slot() {} ~Slot() {} } slots_[Capacity];
    // Buckets name LIVE connection tails. Erasing a final head unlinks its tail;
    // drain duration/client churn cannot fill this table with tombstones.
    Index connections_[TableSize];
    Index ready_head_[3] = {None, None, None};
    Index ready_tail_[3] = {None, None, None};
    Index oldest_ = None, newest_ = None, free_ = None, used_ = 0, count_ = 0;
    uint32_t priority_left_ = BatchOps;
    bool table_initialized_ = false;

    Node& node(uint32_t i) { return slots_[i].node; }
    static uint32_t hash(Client* client) {
        const auto p = reinterpret_cast<uintptr_t>(client);
        return ((p >> 6) ^ (p >> 17)) & (TableSize - 1);
    }
    Index* connection(Client* client) {
        Index* link = &connections_[hash(client)];
        while (*link != None && node(*link).task.client != client)
            link = &node(*link).hash_next;
        return link;
    }
    void ready_append(uint32_t i, uint8_t rank) {
        Node& n = node(i);
        n.rank = rank;
        n.prev_ready = ready_tail_[rank];
        n.next_ready = None;
        if (n.prev_ready == None) ready_head_[rank] = i;
        else node(n.prev_ready).next_ready = i;
        ready_tail_[rank] = i;
    }
    void ready_remove(uint32_t i) {
        Node& n = node(i);
        if (n.prev_ready == None) ready_head_[n.rank] = n.next_ready;
        else node(n.prev_ready).next_ready = n.next_ready;
        if (n.next_ready == None) ready_tail_[n.rank] = n.prev_ready;
        else node(n.next_ready).prev_ready = n.prev_ready;
    }
    uint8_t rank(const Node& n) const {
        return n.length == static_cast<uint8_t>(CommandLengthClass::Long) ? 1 :
               shadow_bit(n.task) ? 2 : 0;
    }
    void append(const Task& task, uint8_t length) {
        if (count_ == Capacity) std::abort();
        Index* link = connection(task.client);
        const Index previous = *link;
        Index i;
        if (free_ != None) { i = free_; free_ = slots_[i].next_free; }
        else { i = used_++; if (i >= Capacity) std::abort(); }
        Node& n = *new (&slots_[i].node) Node{task, newest_, None, None,
            previous == None ? None : node(previous).hash_next, None, None, length, 0};
        if (newest_ != None) node(newest_).newer = i;
        else oldest_ = i;
        newest_ = i;
        if (previous == None) ready_append(i, rank(n));
        // Preserve the admitted owner order. A read-local demotion may legally
        // lower an older read after a later independent op; its existing hazard
        // protocol decides that order, not a new ROB-id sort/assertion here.
        else node(previous).next_conn = i;
        *link = i;
        ++count_;
    }
    void refresh_shadows() {
        // Only eligible shadow heads can affect this pick. Followers get one
        // completion check when activated, not one check at every batch boundary.
        for (uint32_t i = ready_head_[2]; i != None;) {
            Node& n = node(i);
            const uint32_t next = n.next_ready;
            if (!shadow_pending(n.task)) {
                n.task.shard = -1;
                ready_remove(i);
                ready_append(i, 0);
            }
            i = next;
        }
    }
    void activate(uint32_t i) {
        Node& n = node(i);
        if (shadow_bit(n.task) && !shadow_pending(n.task)) n.task.shard = -1;
        ready_append(i, rank(n));
    }
    template <typename Emit>
    void emit_queued(uint32_t n, Emit& emit) {
        if (n > count_ || n > BatchOps) std::abort();
        refresh_shadows();
        Task output[BatchOps];
        ReorderResult witness;
        for (uint32_t out = 0; out < n; ++out) {
            uint32_t i;
            if (!priority_left_) {
                i = oldest_;
                priority_left_ = kExReorderShortQuota;
            } else {
                i = ready_head_[0] != None ? ready_head_[0] :
                    ready_head_[1] != None ? ready_head_[1] : ready_head_[2];
                --priority_left_;
            }
            if (i == None) std::abort();
            Node& selected = node(i);
            if (i != oldest_) witness = ReorderResult{1, 1};
            output[out] = selected.task;
            ready_remove(i);
            if (selected.next_conn != None)
                activate(selected.next_conn);
            else *connection(selected.task.client) = selected.hash_next;
            if (selected.older == None) oldest_ = selected.newer;
            else node(selected.older).newer = selected.newer;
            if (selected.newer == None) newest_ = selected.older;
            else node(selected.newer).older = selected.older;
            slots_[i].next_free = free_;
            free_ = i;
            --count_;
        }
        emit(output, n, witness);
    }
public:
    static constexpr uint32_t kMaxWaitPicks = BatchOps + Capacity * (kExReorderShortQuota + 1);
    ShadowReorderQueues() { TOMO_R7_PATH(); }
    ShadowReorderQueues(const ShadowReorderQueues&) = delete;
    ShadowReorderQueues& operator=(const ShadowReorderQueues&) = delete;
    ~ShadowReorderQueues() { if (size()) std::abort(); }
    uint32_t size() const { return count_; }
    template <typename Emit>
    void finish(Emit& emit) {
        while (size()) emit_queued(std::min<uint32_t>(BatchOps, size()), emit);
        priority_left_ = BatchOps;
    }
    template <typename Emit>
    void submit(const Task* tasks, uint32_t n, Emit& emit) {
        if (n > BatchOps) std::abort();
        uint32_t begin = 0;
        while (begin < n) {
            uint8_t lengths[BatchOps];
            if (!candidate(tasks[begin], lengths[begin])) {
                finish(emit);
                emit(tasks + begin++, 1, ReorderResult{});
                continue;
            }
            uint32_t end = begin + 1;
            bool one_client = true, homogeneous = !shadow_bit(tasks[begin]);
            const bool first_long = lengths[begin] == static_cast<uint8_t>(CommandLengthClass::Long);
            while (end < n && candidate(tasks[end], lengths[end])) {
                one_client &= tasks[end].client == tasks[begin].client;
                homogeneous &= !shadow_bit(tasks[end]) &&
                    (lengths[end] == static_cast<uint8_t>(CommandLengthClass::Long)) == first_long;
                ++end;
            }
            if (!size() && (one_client || homogeneous)) {
                emit(tasks + begin, end - begin, ReorderResult{});
            } else {
                // Preserve homogeneous/single-client bypass: even the connection
                // index is uninitialized scratch until a mixed run needs it.
                if (!table_initialized_) {
                    std::fill_n(connections_, TableSize, None);
                    table_initialized_ = true;
                }
                for (uint32_t i = begin; i < end; ++i) append(tasks[i], lengths[i]);
                if (size() > BatchOps) emit_queued(size() - BatchOps, emit);
            }
            if (end < n) {
                finish(emit);
                emit(tasks + end, 1, ReorderResult{});
            }
            begin = end + (end < n);
        }
    }
};

// Bounded contexts (read-local fairness quanta and existing deferred-work batches) must finish
// before their caller services the next phase. They use the same queues and policy, just with
// one admission. Keep every byte of scratch behind the boot-latched enable branch when off.
template <size_t BatchOps, bool Shadow = false>
__attribute__((noinline)) ReorderResult ex_schedule_batch(Task (&tasks)[BatchOps], uint32_t n) {
    if (__builtin_expect(n > BatchOps, false)) std::abort();
    std::conditional_t<Shadow, ShadowReorderQueues<BatchOps>, ExReorderQueues<BatchOps>> queues;
    uint32_t count = 0;
    ReorderResult result;
    auto emit = [&](const Task* selected, uint32_t size, ReorderResult witness) {
        result.multi_client_runs += witness.multi_client_runs;
        result.permuted_runs += witness.permuted_runs;
        if (__builtin_expect(size > n - count, false)) std::abort();
        // submit() has admitted every source entry in this output prefix before calling us.
        // A queued emission can therefore replace it now without touching an unscanned suffix
        // or barrier. Bypassed spans already occupy their final position and need no Task copy.
        if (selected != tasks + count)
            for (uint32_t i = 0; i < size; i++) tasks[count + i] = selected[i];
        count += size;
    };
    queues.submit(tasks, n, emit);
    queues.finish(emit);
    if (count != n) std::abort();
    return result;
}

}  // namespace tomo::r7
