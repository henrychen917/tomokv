// R8: a gathered batch cooperatively advances long BITCOUNTs. No continuation escapes the
// owner's batch, so FLIP, shard transfer, snapshot control and QSBR maintenance never inherit one.
#pragma once
#include <algorithm>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <new>
#include "genthread_pipeline.h"
#include "thread.h"
#include "orthog.h"
#include "shard.h"
#include "../net/conn.h"
#include "../net/resp.h"
#include "../cmd/command.h"

namespace tomo {

inline uint64_t bitmap_popcount(const uint8_t* bytes, size_t length) {
    uint64_t count = 0;
    while (length >= sizeof(uint64_t)) {
        uint64_t word;
        std::memcpy(&word, bytes, sizeof(word));
        count += static_cast<uint64_t>(__builtin_popcountll(word));
        bytes += sizeof(word);
        length -= sizeof(word);
    }
    while (length--) count += static_cast<uint64_t>(__builtin_popcount(*bytes++));
    return count;
}

struct BitcountReply {
    void operator()(Shard&, Op& op, Slice value, size_t offset, size_t length,
                    uint64_t edges = 0) const {
        reply_int(op.sink(), static_cast<long long>(edges + bitmap_popcount(
            reinterpret_cast<const uint8_t*>(value.p) + offset, length)));
    }
};

// Only large external strings suspend. Integer/inline views can name handler-stack storage;
// the structural minimum below is greater than either representation. The borrow is registered
// under the WHOLE value's pointer, even for a range starting in its middle. It pins exactly the
// version selected by normal owner admission + plain_read_cut/RYOW resolution, before that
// scope closes. Replacement, expiry, eviction and MVCC reclamation use the existing retention
// protocol. Subsequent slices never find the key again or change the selected read cut.
class BitcountSlice {
public:
    explicit BitcountSlice(uint32_t pieces = 1) : pieces_(std::max<uint32_t>(1, pieces)) {}
    ~BitcountSlice() { if (store_) store_->unborrow(base_); }
    BitcountSlice(const BitcountSlice&) = delete;
    BitcountSlice& operator=(const BitcountSlice&) = delete;

    bool pending() const { return store_ != nullptr; }
    void pieces(uint32_t n) { pieces_ = std::max<uint32_t>(1, n); }

    void operator()(Shard& shard, Op& op, Slice value, size_t offset, size_t length,
                    uint64_t edges = 0) {
        constexpr size_t line = kGenthreadCacheLineBytes;
        // Divide this command among the available batch turns; no window/size knob. The floor
        // protects pointer lifetime, not a claim that 256-byte slices have earned their cost.
        quantum_ = (std::max<size_t>(kEmbedThreshold + 1,
                                    (length + pieces_ - 1) / pieces_) + line - 1) / line * line;
        if (length <= quantum_) {
            BitcountReply{}(shard, op, value, offset, length, edges);
            return;
        }
        try { shard.store().borrow(value.p); }
        catch (const std::bad_alloc&) {
            // Optional scheduling storage cannot turn a valid read into an OOM error.
            BitcountReply{}(shard, op, value, offset, length, edges);
            return;
        }
        store_ = &shard.store();
        base_ = value.p;
        cursor_ = reinterpret_cast<const uint8_t*>(value.p) + offset;
        remaining_ = length;
        count_ = edges;
        op_ = &op;
        step();
    }

    // Returns true only after formatting the sole reply and releasing the borrow. Done remains
    // the executor's publication; the unfinished ROB slot keeps argv and the Client alive.
    bool step(bool finish = false) {
        if (!pending()) std::abort();
        const size_t take = finish ? remaining_ : std::min(remaining_, quantum_);
        count_ += bitmap_popcount(cursor_, take);
        cursor_ += take;
        remaining_ -= take;
        if (remaining_) return false;
        reply_int(op_->sink(), static_cast<long long>(count_));
        store_->unborrow(base_);
        store_ = nullptr;
        return true;
    }

private:
    FlatStore* store_ = nullptr;
    Op* op_ = nullptr;
    const char* base_ = nullptr;
    const uint8_t* cursor_ = nullptr;
    size_t remaining_ = 0;
    size_t quantum_ = 0;
    uint64_t count_ = 0;
    uint32_t pieces_ = 1;
};

// The same BITCOUNT parser/masks as the synchronous handler; defined in t_string.cc.
void bitcount_slice_begin(Shard& shard, Op& op, BitcountSlice& slice);

// Specials, atomic groups (including same-owner lowering), notifications, and all other long
// handlers are barriers. EXEC/script child BITCOUNTs keep their ordinary synchronous handler.
// No half-applied mutation or active plain-read scope is ever held while another task runs.
enum class SplitKind : uint8_t { Barrier, Ordinary, Bitcount };
inline SplitKind ex_split_kind(const Task& task) {
    if (!task.client || task.scatter) return SplitKind::Barrier;
    const Op& op = task.client->rob().at(task.op_id);
    if (!op.spec || op.has_blocking_state()) return SplitKind::Barrier;
    constexpr uint32_t special =
        CmdFlags::Admin | CmdFlags::ConnLocal | CmdFlags::AllShards | CmdFlags::RandomShard |
        CmdFlags::CursorShard | CmdFlags::ConfigRoute | CmdFlags::ScriptRoute |
        CmdFlags::PubSub | CmdFlags::Blocking | CmdFlags::Transaction | CmdFlags::MultiShard |
        CmdFlags::StreamRoute | CmdFlags::SubcmdRoute | CmdFlags::FlipAsync |
        CmdFlags::NotifySelected | CmdFlags::SnapshotWrite;
    if (op.spec->flags & special) return SplitKind::Barrier;
    if (op.spec->flags & CmdFlags::SliceBitcount) return SplitKind::Bitcount;
    return command_length_class(*op.spec) == CommandLengthClass::Long
        ? SplitKind::Barrier : SplitKind::Ordinary;
}

// A scan of immutable published metadata, behind one boot-latched branch per batch. A batch
// without a covered blocker followed by another connection takes the unchanged execution loop.
// No ROB ranks, counters, handler indirection or scratch allocation enter that loop.
__attribute__((noinline)) inline bool ex_split_possible(const Task* tasks, uint32_t n) {
    Client* blocker = nullptr;
    for (uint32_t i = 0; i < n; i++) {
        const SplitKind kind = ex_split_kind(tasks[i]);
        if (kind == SplitKind::Barrier) { blocker = nullptr; continue; }
        if (blocker && tasks[i].client != blocker) return true;
        if (kind == SplitKind::Bitcount) blocker = tasks[i].client;
    }
    return false;
}

// Begin uses normal execute() for admission/forwarding/parking, but can suppress Done for a
// sliced BITCOUNT. Complete publishes that deferred Done. Retry takes the untouched FIFO suffix.
// All callbacks are compile-time callables; the original ordinary-command loop is unchanged.
template <typename Begin, typename Complete, typename Retry, typename Yield>
__attribute__((noinline)) ReorderResult ex_split_batch(
        const Task* tasks, uint32_t n, Begin&& begin, Complete&& complete, Retry&& retry,
        Yield&& yield) {
    constexpr uint32_t capacity = kGenthreadPipelineExBatchOps;
    static_assert(kGenthreadExBatchOps <= capacity);
    if (n > capacity) std::abort();
    ReorderResult result;
    BitcountSlice slices[capacity];
    bool done[capacity] = {};
    SplitKind kinds[capacity];
    // Capture metadata BEFORE any Done: IO may recycle completed slots during this call.
    for (uint32_t i = 0; i < n; i++) kinds[i] = ex_split_kind(tasks[i]);
    for (uint32_t first = 0; first < n;) {
        uint32_t end = first;
        while (end < n && kinds[end] != SplitKind::Barrier) end++;
        if (end == first) end++;
        uint32_t remaining = end - first;
        uint32_t active = 0;
        bool multi = false;
        for (uint32_t i = first + 1; i < end; i++)
            multi |= tasks[i].client != tasks[first].client;
        result.multi_client_runs += multi;
        while (remaining) {
            for (uint32_t i = first; i < end; i++) {
                if (done[i]) continue;
                // Same-connection order is stronger than reply order: its next task cannot even
                // ENTER admission until the preceding sliced read is complete. Existing parked
                // predecessor checks still protect tasks execute() moves to an atomic queue.
                bool own_predecessor = false;
                for (uint32_t j = first; j < i; j++)
                    own_predecessor |= !done[j] && tasks[j].client == tasks[i].client;
                if (own_predecessor) continue;
                if (slices[i].pending()) {
                    // Once only this connection remains, there is no useful yield left. Finish
                    // its suffix in one scan instead of paying empty scheduler turns.
                    bool peer = false;
                    for (uint32_t j = first; j < end; j++)
                        peer |= !done[j] && tasks[j].client != tasks[i].client;
                    if (!slices[i].step(!peer)) continue;
                    active--;
                    complete(tasks[i]);
                } else {
                    bool peer_after = false;
                    for (uint32_t j = i + 1; j < end; j++)
                        peer_after |= !done[j] && tasks[j].client != tasks[i].client;
                    BitcountSlice* slice = kinds[i] == SplitKind::Bitcount && (peer_after || active)
                        ? &slices[i] : nullptr;
                    if (slice) slice->pieces(end - first);
                    if (!begin(tasks[i], slice)) {
                        // A retry is a FIFO barrier. Complete all pinned reads before yielding
                        // the batch, then preserve every still-unstarted Task exactly once.
                        for (uint32_t j = first; j < end; j++) if (slices[j].pending()) {
                            slices[j].step(true);
                            complete(tasks[j]);
                            done[j] = true;
                        }
                        for (uint32_t j = first; j < n; j++)
                            if (!done[j]) retry(tasks[j]);
                        return result;
                    }
                    if (slice && slice->pending()) {
                        result.sliced_commands++;
                        active++;
                        continue;
                    }
                }
                done[i] = true;
                remaining--;
            }
            if (active) {
                // Publish peer completion notifications BEFORE resuming the long scans. Leaving
                // them in the usual batch coalescer would keep a sleeping split IO waiting for
                // the full command anyway. This is an existing sender wake, never executor WB.
                yield();
                result.slice_yields++;
            }
        }
        first = end;
    }
    return result;
}

} // namespace tomo
