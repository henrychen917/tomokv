// reorder.h -- continuous owner-local short/long FIFOs, shared by both thread modes.
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

// Only the ordinary one-owner path participates. Every existing special mechanism is a hard
// barrier in the incoming sequence: both queues drain before it may execute.
inline bool candidate(const Task& task, uint8_t& length) {
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
    // safe upper bound without a deque scan or a per-connection scheduler table.
    if (op.atomic_hazard()) length = static_cast<uint8_t>(CommandLengthClass::Long);
    return true;
}

// R7's candidate service ratio matches the deciding 8:2 short/long mix. This is a
// candidate constant, NOT a measured optimum. Only --reorder 0|1 is exposed.
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
public:
    explicit ShadowDispatch(Client& client) {
        auto& rob = client.rob();
        for (uint64_t id = rob.flush_id(), end = rob.dispatch_id(); id < end; ++id) {
            const Op& op = rob.at(id);
            if (op.state.load(std::memory_order_acquire) == OpState::Done) continue;
            uint8_t length;
            Task task(&client, id, -1, nullptr);
            if (candidate(task, length) &&
                length == static_cast<uint8_t>(CommandLengthClass::Long)) newest_ = id;
        }
    }
    void stamp(Task& task) {
        uint8_t length;
        if (!candidate(task, length)) return;
        if (length == static_cast<uint8_t>(CommandLengthClass::Long)) {
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
    ExReorderQueues() = default;
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
    static constexpr uint32_t None = UINT32_MAX;
    static constexpr uint32_t TableSize = 2 * Capacity;
    struct Node {
        Task task;
        uint32_t older, newer, next_conn, connection;
        uint32_t prev_ready = None, next_ready = None;
        uint8_t length, rank;
    };
    union Slot { Node node; uint32_t next_free; Slot() {} ~Slot() {} } slots_[Capacity];
    struct Connection { Client* client = nullptr; uint32_t tail = None; } connections_[TableSize];
    uint32_t ready_head_[3] = {None, None, None};
    uint32_t ready_tail_[3] = {None, None, None};
    uint32_t oldest_ = None, newest_ = None, free_ = None, used_ = 0, count_ = 0;
    uint32_t priority_left_ = BatchOps;

    Node& node(uint32_t i) { return slots_[i].node; }
    static uint32_t hash(Client* client) {
        const auto p = reinterpret_cast<uintptr_t>(client);
        return ((p >> 6) ^ (p >> 17)) & (TableSize - 1);
    }
    uint32_t connection(Client* client) {
        uint32_t empty = None;
        for (uint32_t i = hash(client), n = 0; n < TableSize; ++n, i = (i + 1) & (TableSize - 1)) {
            auto& c = connections_[i];
            if (c.tail != None && c.client == client) return i;
            if (c.tail == None && empty == None) empty = i;
            if (!c.client) break;
        }
        if (empty == None) std::abort();
        connections_[empty].client = client;
        return empty;
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
        const uint32_t c = connection(task.client);
        uint32_t i;
        if (free_ != None) { i = free_; free_ = slots_[i].next_free; }
        else { i = used_++; if (i >= Capacity) std::abort(); }
        Node& n = *new (&slots_[i].node) Node{task, newest_, None, None, c, None, None, length, 0};
        // Done may precede retirement. Clear at admission, and again between output
        // batches, so slow IO retirement never keeps a completed long's shadow armed.
        if (shadow_bit(n.task) && !shadow_pending(n.task)) n.task.shard = -1;
        if (newest_ != None) node(newest_).newer = i;
        else oldest_ = i;
        newest_ = i;
        const uint32_t previous = connections_[c].tail;
        if (previous == None) ready_append(i, rank(n));
        else {
            if (node(previous).task.op_id >= task.op_id) std::abort();
            node(previous).next_conn = i;
        }
        connections_[c].tail = i;
        ++count_;
    }
    void refresh_shadows() {
        // Only pending tasks pin their Clients. Never retain/dereference emitted
        // tasks after a callback can publish Done and destroy the connection.
        for (uint32_t i = oldest_; i != None; i = node(i).newer) {
            Node& n = node(i);
            if (!shadow_bit(n.task) || shadow_pending(n.task)) continue;
            n.task.shard = -1;
            if (n.rank == 2 && (n.prev_ready != None || ready_head_[2] == i)) {
                ready_remove(i);
                ready_append(i, 0);
            }
        }
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
                ready_append(selected.next_conn, rank(node(selected.next_conn)));
            else connections_[selected.connection].tail = None;
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
    ShadowReorderQueues() = default;
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
