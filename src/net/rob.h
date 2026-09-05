// rob.h — the reorder buffer. One per connection.
//
// THE PROBLEM IT SOLVES. A pipelined client sends GET a, GET b, GET c on one socket. Those keys can
// live on three different workers, which finish in any order. The protocol requires the replies in
// the order sent. So we need out-of-order execution with in-order retirement — a reorder buffer, and
// the name is not an analogy: dispatch_id is the issue pointer, flush_id is the commit pointer, and
// a slot retires only when every older slot has retired.
//
//   dispatch_id  next id to issue     — advanced at parse
//   flush_id     next id to retire    — advanced at retire (both by the connection's io thread)
//   slot(id)     id & mask
//   in_flight    dispatch_id - flush_id
//
//   dispatch_id == flush_id is the universal quiescence fence. Nothing is in flight, so the
//   connection can be closed, migrated, or have its buffers recycled. Every teardown path tests
//   exactly this and nothing else.
//
// ============================================================================================
// WHAT CROSSES THREADS, in pure 2s: the io thread owns BOTH counters (it parses and it retires).
// The executor only ever touches individual Op slots — reached through chunk pointers published
// with release/acquire, contents ordered by the Op's own state handshake (Issued/Done). The two
// counters stay atomics anyway: on x86 the same-thread case degrades to ordinary loads and stores
// (zero cost), and dispatch_id == flush_id is the quiescence fence a future connection MIGRATION
// between io threads must read from the other side — demoting them buys nothing and closes a door.
//
// READ-BUFFER PINNING STILL FALLS OUT. argv Slices point into the connection's read buffer. Because
// retirement is strictly in order, the oldest live op is always slot(flush_id) — so every byte
// before that op's rbuf_off is dead. No refcounting, no generation numbers.
//
// SLOTS ARE CHUNKED, NOT INLINE AND NOT SCATTERED. An ExecContext is ~328 bytes; held by value a
// 64-slot ROB is ~21KB resident per connection whether it ever pipelines or not. The first pointer
// version fixed that with one heap Op per slot — and measured a −3% SET p32 regression, because 64
// scattered allocations lost the sequential locality the drain used to get from the inline array
// for free. So: contexts materialize in CONTIGUOUS CHUNKS of eight, on the first touch of any slot
// in the chunk. A p1 connection holds one chunk (~2.6KB), a 32-deep pipeliner four, and the drain
// walks sequential memory within every chunk. Each context recycles in place forever ("flushed"
// logically at retire — state goes Free — never returned to the allocator until the connection
// dies); steady-state allocator traffic is zero, and jemalloc needs no pool in front of it.
#pragma once
#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <new>
#include "../exec/op.h"

namespace tomo {

// Allocated only for connections served by the boot-armed fused read-local lane. The connection's
// IO owner is the sole reader/writer; the ROB ids carried beside hashes are generations, not
// cross-thread publications. Retirement is therefore lazy: flush_id advancing past an entry is
// its removal fence, and stale entries may only cause an allowed false-positive conflict.
struct ReadLocalRobState {
    static constexpr uint32_t kWriteRingCapacity = 16;
    static constexpr uint32_t kMaxPreciseKeysetKeys = kWriteRingCapacity;
    static_assert((kWriteRingCapacity & (kWriteRingCapacity - 1)) == 0);
    static_assert(kWriteRingCapacity <= 16, "keyset slot bitmap width");

    static constexpr uint64_t keyset_filter(uint64_t hash) {
        return (uint64_t{1} << (hash & 63)) |
               (uint64_t{1} << ((hash >> 32) & 63));
    }

    enum class PendingWrite : uint8_t { None, Hash, Keyset, Overflow };

    struct WriteKey {
        uint64_t hash = 0;
        uint64_t op_id = 0;
    };

    uint64_t pending_hash = 0;
    uint64_t pending_op_id = 0;
    uint64_t overflow_through = 0;
    uint8_t write_head = 0;
    uint8_t write_count = 0;
    uint16_t write_keyset_slots = 0;
    PendingWrite pending_write = PendingWrite::None;
    bool overflow = false;
    // A local MGET is one command-wide latest-read fence. No younger frame may receive a read cut
    // until this id either completes locally or is irrevocably transferred to the owner path.
    uint64_t local_mget_fence_id = UINT64_MAX;
    // Keep the pure/short-ring controls and the first common entries on the leading cache lines.
    WriteKey write_ring[kWriteRingCapacity]{};
};
static_assert(alignof(ReadLocalRobState) >= 2, "read-local sidecar pointer uses its low bit");

// Superset summary of every key hash that one connection's still-pending local reads may touch.
// The armed parser ORs a read's keyset in when it marks the slot pending; the words are cleared
// only when the pending bitmap drains to zero and are rewritten only from a walk of the complete
// pending set. Membership is therefore never lost while a read is pending: a miss PROVES that no
// pending read shares the probed hash, a hit merely means "run the exact demotion plan". Same
// hash-conservative contract as the RYOW write ring (a real 64-bit collision may take the owner
// path). Two bits per key across four words: ~8 pending GETs give well under 1% false hits.
struct ReadLocalPendingFilter {
    static constexpr uint32_t kWords = 4;
    static_assert((kWords & (kWords - 1)) == 0);

    static constexpr uint32_t word_of(uint64_t hash) {
        return static_cast<uint32_t>((hash >> 6) & (kWords - 1));
    }
    void add(uint64_t hash) {
        words[word_of(hash)] |= ReadLocalRobState::keyset_filter(hash);
    }
    bool may_contain(uint64_t hash) const {
        const uint64_t bits = ReadLocalRobState::keyset_filter(hash);
        return (words[word_of(hash)] & bits) == bits;
    }
    void merge(const ReadLocalPendingFilter& other) {
        for (uint32_t i = 0; i < kWords; i++) words[i] |= other.words[i];
    }
    void clear() {
        for (uint32_t i = 0; i < kWords; i++) words[i] = 0;
    }

    uint64_t words[kWords] = {};
};
static_assert(sizeof(ReadLocalPendingFilter) == 32, "fills the Rob's spare flush_-line tail");

template <uint32_t Capacity>
class Rob {
    static_assert((Capacity & (Capacity - 1)) == 0, "capacity must be a power of two");
    static_assert(Capacity <= 64, "read-local slot accounting uses one footprint-free word");
    static constexpr uint32_t kMask = Capacity - 1;

public:
    // ---- producer side (the parser / io thread) ------------------------------------------------
    uint64_t dispatch_id() const { return dispatch_.load(std::memory_order_relaxed); }
    uint64_t flush_id()    const { return flush_.load(std::memory_order_acquire); }

    uint32_t in_flight() const { return static_cast<uint32_t>(dispatch_id() - flush_id()); }
    bool     full()      const { return in_flight() >= Capacity; }
    bool     quiesced()  const { return dispatch_id() == flush_id(); }

    // Claim the next slot to fill. Null when the window is full — the caller must stop parsing and
    // let the sender drain. That backpressure is what bounds memory under a client that pipelines
    // without reading, and dropping it is how a server OOMs on one misbehaving connection.
    // Materialization happens HERE and only here — the parser is the sole allocator, so workers
    // and the sender only ever dereference slots that a publish made real.
    // `Codes` GATES THE CODED REPLY BY THREAD MODE, at compile time. Both call sites (io_loop's
    // parse loop) sit inside an `if constexpr (Fused)` arm, so this is a constant store of 1 or 0,
    // not a branch.
    //
    // WHY 2s IS OFF. Coded replies are a measured win in fused (SET -2.4%, DEL -3.2% cycles/op on
    // the quiet box) and a measured LOSS on the split GET cell (-1.4%, reproduced on both runs of
    // an ABBA pair), which is a main command and therefore blocks a both-modes merge under the
    // zero-regression rule. With Codes=false no 2s op is ever armed, Sink::code() always declines,
    // op.reply_code_ stays 0 for the life of every 2s op, and the split path executes exactly the
    // bytes it executed before -- the retire guards are all `if (op.reply_code_)` and none can be
    // taken. The coded blocks remain in the shared machine code (WbEngine is not templated on
    // thread mode); they are unreachable in 2s rather than absent.
    template <bool Codes = false>
    Op* acquire(uint8_t route_flags = 0) {
        if (full()) return nullptr;
        Op* op = slot(static_cast<uint32_t>(dispatch_id()) & kMask, true);
        op->reset(route_flags);
        op->reply_code_ok_ = Codes ? 1 : 0;
        return op;
    }

    // The armed coarse parser owns the local-read slot bitmap and write generations. Resolve the
    // preceding candidate before recycling a position; ordinary acquire() above stays baseline.
    //
    // SHAPE, not policy: this body performs exactly what the single-function version performed, in
    // the same order. The write-generation resolution moved behind a noinline call because with it
    // inline the function reached 917 bytes and GCC declined to inline it into the (very large)
    // parse loop -- so every armed frame paid a call and a register-allocation barrier to discover
    // that no write generation was live. acquire() next door, which is the same shape minus that
    // machinery, inlines at every one of its call sites.
    __attribute__((always_inline)) Op* acquire_read_local(uint8_t route_flags = 0) {
        if (__builtin_expect(read_local_state_active(), false)) resolve_read_local_write();
        // One dispatch load serves the window test and the slot index. Only this connection's io
        // thread stores dispatch_ (see the header note), and nothing between the two uses stores
        // it, so the second load the previous shape performed could only return the same value.
        const uint64_t dispatch = dispatch_.load(std::memory_order_relaxed);
        if (static_cast<uint32_t>(dispatch - flush_id()) >= Capacity) return nullptr;
        const uint32_t index = static_cast<uint32_t>(dispatch) & kMask;
        const uint64_t keep = ~(uint64_t{1} << index);
        read_local_pending_slots_ &= keep;
        read_local_owner_slots_ &= keep;
        Op* op = slot(index, true);
        op->reset_read_local(route_flags);
        // Read-local is a FUSED-only path, so this arm is unconditional for the same reason
        // acquire<true>() is: only 1s reaches here.
        op->reply_code_ok_ = 1;
        return op;
    }

    // Cold half of acquire_read_local: a write generation is live, so the staged candidate from the
    // previous frame must be resolved into the ring (or into an overflow generation) before this
    // position is recycled.
    __attribute__((noinline)) void resolve_read_local_write() {
        ReadLocalRobState& state = read_local_state_required();
        read_local_resolve_pending(state);
        read_local_try_deactivate(state);
    }

    // Publish the slot claimed by acquire(). RELEASE: everything written into the slot must be
    // visible to the consumer before it can observe the new dispatch_id. Separate from acquire()
    // because the parser may abandon a half-built op without advancing the ROB.
    void publish() { dispatch_.store(dispatch_id() + 1, std::memory_order_release); }

    // Undo the last publish(). Only legal while the op is still un-dispatched, i.e. no worker can
    // have marked it Done -- which is exactly the refused-dispatch path. Safe even if a sender has
    // already observed the higher dispatch_: it can only have seen the slot as not-Done and stopped,
    // because retirement never touches an op that is not Done.
    void unpublish() { dispatch_.store(dispatch_id() - 1, std::memory_order_release); }

    // The enabled parser marks a slot while its Task still belongs to the local lane. The fused
    // executor clears it only after the read has completed locally or has entered an ordinary
    // owner queue. Thus a later write can distinguish work that still needs venue demotion from an
    // already-executed read without adding any hook to ordinary publish or retirement.
    // `keys` must cover every hash read_local_command_touches_hash() can report for this op: the
    // demotion planner's pre-check treats a filter miss as proof that no pending read overlaps.
    // `op_id` must be the current dispatch id -- the caller has just loaded it to name the op it
    // is about to publish (io_loop.h, the read-local accept arm), so the load is not repeated here.
    __attribute__((always_inline)) void mark_current_read_local(
            uint64_t op_id, const ReadLocalPendingFilter& keys) {
        mark_current_read_local_slot(op_id);
        read_local_pending_filter_.merge(keys);
    }

    // Point form. A marked read that is not an MGET reports exactly one hash to every predicate
    // that consults this filter: read_local_command_touches_hash() takes its non-MGET/non-precise-
    // MSET branch for such an op and compares op.hash alone, and the keyset overlap predicates use
    // read.hash alone. Merging a four-word summary whose other three words the caller had just
    // zeroed set the identical bits at three times the traffic.
    __attribute__((always_inline)) void mark_current_read_local_hash(
            uint64_t op_id, uint64_t hash) {
        mark_current_read_local_slot(op_id);
        read_local_pending_filter_.add(hash);
    }

    // False proves that no still-pending local read may touch `hash`; true only means "walk".
    bool read_local_pending_may_touch(uint64_t hash) const {
        return read_local_pending_filter_.may_contain(hash);
    }
    const ReadLocalPendingFilter& read_local_pending_filter() const {
        return read_local_pending_filter_;
    }
    // Legal only with a summary just computed over EVERY currently pending read (the planner's
    // complete walk); it restores exactness after false hits without touching the ordinary path.
    void reset_read_local_pending_filter(const ReadLocalPendingFilter& exact) {
        read_local_pending_filter_ = exact;
    }

    void arm_current_local_mget_fence() {
        read_local_state_activate();
        ReadLocalRobState& state = read_local_state_required();
        if (state.local_mget_fence_id != UINT64_MAX) std::abort();
        state.local_mget_fence_id = dispatch_id();
    }

    bool local_mget_fence_pending() {
        if (!read_local_state_active()) return false;
        ReadLocalRobState& state = read_local_state_required();
        if (state.local_mget_fence_id == UINT64_MAX) return false;
        if (read_local_id_active(
                state.local_mget_fence_id, dispatch_id(), flush_id())) return true;
        state.local_mget_fence_id = UINT64_MAX;
        read_local_try_deactivate(state);
        return false;
    }

    bool pending_read_local(uint64_t op_id) const {
        const uint64_t dispatch = dispatch_id();
        const uint64_t flush = flush_id();
        return read_local_id_active(op_id, dispatch, flush) &&
               (read_local_pending_slots_ &
                (uint64_t{1} << (static_cast<uint32_t>(op_id) & kMask))) != 0;
    }

    bool has_pending_read_local() const { return read_local_pending_slots_ != 0; }

    // Chunk forms for the fused local drain. One dispatch/flush snapshot serves a whole same-client
    // chunk: flush can only pass Done ops and no lane op is Done before this thread publishes it,
    // while dispatch only grows and every lane op published below it, so a snapshot taken once per
    // chunk classifies each entry exactly as a fresh pair would. The mask clear retires the chunk's
    // completed prefix with one store; the ids of in-flight ops are distinct modulo the window.
    bool pending_read_local(uint64_t op_id, uint64_t dispatch, uint64_t flush) const {
        return read_local_id_active(op_id, dispatch, flush) &&
               (read_local_pending_slots_ &
                (uint64_t{1} << (static_cast<uint32_t>(op_id) & kMask))) != 0;
    }
    static uint64_t read_local_slot_bit(uint64_t op_id) {
        return uint64_t{1} << (static_cast<uint32_t>(op_id) & kMask);
    }
    // Retires through the same clear-on-empty rule as the per-op form: when the drained chunk was
    // the whole pending set the summary restarts from zero (the contract stated in fcab80884; the
    // chunk form had dropped it, so the filter only ever grew in read-heavy streams and the first
    // write of every batch paid the exact walk — AUDIT-MARKDIET.md section 4).
    void complete_pending_read_local_mask(uint64_t bits) {
        if ((read_local_pending_slots_ & bits) != bits) std::abort();
        read_local_retire_pending_bit(bits);
    }
    // Owner-map emptiness is chunk-stable inside the drain: only this thread's parser and
    // demotion add owner slots and neither runs while a chunk executes.
    bool has_read_local_owner() const { return read_local_owner_slots_ != 0; }

    uint32_t collect_pending_read_local(uint64_t hash, bool hash_only, uint64_t* ids,
                                        uint32_t capacity) const {
        if (!read_local_pending_slots_) return 0;
        const uint64_t flush = flush_id();
        const uint32_t begin = static_cast<uint32_t>(flush) & kMask;
        const uint64_t generation = flush & ~uint64_t{kMask};
        uint64_t high = read_local_pending_slots_ & (UINT64_MAX << begin);
        const uint64_t low_mask = begin ? (uint64_t{1} << begin) - 1 : 0;
        uint64_t low = read_local_pending_slots_ & low_mask;
        uint32_t count = 0;
        // Enumerate set bits in logical ROB order across a possible slot-zero wrap.
        auto append = [&](uint64_t bits, uint64_t base) {
            while (bits) {
                const uint32_t index = static_cast<uint32_t>(__builtin_ctzll(bits));
                bits &= bits - 1;
                const uint64_t id = base | index;
                if (hash_only && at(id).hash != hash) continue;
                if (count == capacity) std::abort();
                ids[count++] = id;
            }
        };
        append(high, generation);
        append(low, generation + Capacity);
        return count;
    }

    void complete_pending_read_local(uint64_t op_id) {
        const uint64_t bit = uint64_t{1} << (static_cast<uint32_t>(op_id) & kMask);
        if (!(read_local_pending_slots_ & bit)) std::abort();
        read_local_retire_pending_bit(bit);
        read_local_clear_mget_fence(op_id);
    }

    void publish_pending_read_local_to_owner(uint64_t op_id) {
        const uint64_t bit = uint64_t{1} << (static_cast<uint32_t>(op_id) & kMask);
        if (!(read_local_pending_slots_ & bit) || (read_local_owner_slots_ & bit))
            std::abort();
        read_local_retire_pending_bit(bit);
        read_local_owner_slots_ |= bit;
        read_local_clear_mget_fence(op_id);
    }

    // Test only unfinished owner work that is older than `before_id`. Parser callers pass the
    // current dispatch id; EX callers pass the local task's id so a younger demotion cannot fence
    // an older read. The predicate supplies GET/MGET keyset overlap without teaching the ROB how
    // commands encode keys.
    // NOT split the way acquire_read_local and read_local_write_conflicts are. This one is
    // instantiated once per predicate lambda -- about a dozen times across the parser and the fused
    // drain, most of them cold -- so forcing its shell inline duplicated it at every site: +2613
    // bytes of fused parse and +1367 of fused drain, for 0.13 points MORE instructions per read.
    // Measured, not assumed: scratchpad/robdiet/bisect.csv, arm D against arm C.
    template <typename Match>
    bool read_local_owner_conflicts_before(uint64_t before_id, Match&& match) {
        if (!read_local_owner_slots_) return false;
        // Use one dispatch/flush snapshot both to prune the bitmap and to reconstruct wrapped IDs.
        // The sender may advance flush concurrently; mixing two snapshots could otherwise interpret
        // a just-retired low slot as belonging to the next ROB generation.
        const uint64_t dispatch = dispatch_id();
        const uint64_t flush = flush_id();
        read_local_owner_slots_ &= active_slots_mask(dispatch, flush);
        uint64_t active = read_local_owner_slots_;
        if (!active) return false;
        const uint64_t before_distance = before_id - flush;
        if (before_distance > dispatch - flush) std::abort();
        const uint32_t begin = static_cast<uint32_t>(flush) & kMask;
        const uint64_t generation = flush & ~uint64_t{kMask};
        uint64_t high = active & (UINT64_MAX << begin);
        const uint64_t low_mask = begin ? (uint64_t{1} << begin) - 1 : 0;
        uint64_t low = active & low_mask;
        bool conflict = false;
        auto inspect = [&](uint64_t bits, uint64_t base) {
            while (bits) {
                const uint32_t index = static_cast<uint32_t>(__builtin_ctzll(bits));
                bits &= bits - 1;
                const uint64_t id = base | index;
                const Op& op = at(id);
                if (op.state.load(std::memory_order_acquire) == OpState::Done) {
                    read_local_owner_slots_ &= ~(uint64_t{1} << index);
                    continue;
                }
                if (id - flush < before_distance && match(op)) conflict = true;
            }
        };
        inspect(high, generation);
        inspect(low, generation + Capacity);
        return conflict;
    }

    // Mark an owner-routed read (or the precise point operation that forced its demotion). Younger
    // reads consult this slot only when their keysets overlap; ROB retirement alone orders replies.
    void extend_current_read_local_owner() {
        read_local_owner_slots_ |=
            uint64_t{1} << (static_cast<uint32_t>(dispatch_id()) & kMask);
    }

    // Stage a conservative write record before the parser enters ACL/special lowering. The next
    // armed acquire is the commit point: an advanced dispatch id means this op published, while an
    // unchanged id means dispatch was abandoned (including publish + refused-post + unpublish).
    // Every write starts conservative. After arity and routing are known, ordinary point writes
    // and bounded blind keysets may refine it; all other special/multi-key writes leave it broad.
    void mark_current_write() {
        read_local_state_activate();
        ReadLocalRobState& state = read_local_state_required();
        if (state.pending_write != ReadLocalRobState::PendingWrite::None) std::abort();
        read_local_prune(state);
        state.pending_op_id = dispatch_id();
        state.pending_hash = 0;
        state.pending_write = ReadLocalRobState::PendingWrite::Overflow;
    }

    bool refine_current_write_hash(uint64_t hash) {
        ReadLocalRobState& state = read_local_state_required();
        if (state.pending_write != ReadLocalRobState::PendingWrite::Overflow ||
            state.pending_op_id != dispatch_id())
            std::abort();
        // Once overflowed, every subsequently published write extends the conservative generation
        // until that whole run drains. Do not start tracking precise hashes again in its middle.
        if (state.overflow ||
            state.write_count == ReadLocalRobState::kWriteRingCapacity)
            return false;
        state.pending_hash = hash;
        state.pending_write = ReadLocalRobState::PendingWrite::Hash;
        return true;
    }

    // A bounded precise multi-key write occupies one ring slot, just like a point write. Its live
    // ROB op owns the immutable key argv used by the conflict predicate, while the stored filter
    // rejects almost every disjoint probe without rescanning argv. Wider keysets stay Overflow.
    bool refine_current_write_keyset(uint64_t filter, uint32_t key_count) {
        ReadLocalRobState& state = read_local_state_required();
        if (state.pending_write != ReadLocalRobState::PendingWrite::Overflow ||
            state.pending_op_id != dispatch_id())
            std::abort();
        if (!key_count || key_count > ReadLocalRobState::kMaxPreciseKeysetKeys || !filter)
            return false;
        if (state.overflow ||
            state.write_count == ReadLocalRobState::kWriteRingCapacity)
            return false;
        state.pending_hash = filter;
        state.pending_write = ReadLocalRobState::PendingWrite::Keyset;
        return true;
    }

    // Hash collisions deliberately conflict. Empty is the pure-GET fast path: it avoids even the
    // flush frontier load -- and that emptiness test is this shell, which stays inline. It was
    // already the merged function's first line, but the merged function was 612 bytes and out of
    // line, so a pure GET paid a call to be told that nothing was pending.
    template <typename KeysetTouchesHash>
    __attribute__((always_inline)) bool read_local_write_conflicts(
            uint64_t hash, KeysetTouchesHash&& keyset_touches_hash) {
        if (!read_local_state_active()) return false;
        return read_local_write_conflicts_pending(
            hash, static_cast<KeysetTouchesHash&&>(keyset_touches_hash));
    }

    // A write generation is live: prune the retired FIFO prefix, then scan at most sixteen write
    // descriptors (normally one to four). Hash entries compare directly; exact keyset entries ask
    // the caller to inspect their still-live ROB argv. Overflow remains conservative until every
    // write published during that overflow generation has retired. Unchanged from the merged form.
    template <typename KeysetTouchesHash>
    __attribute__((noinline)) bool read_local_write_conflicts_pending(
            uint64_t hash, KeysetTouchesHash&& keyset_touches_hash) {
        ReadLocalRobState& state = read_local_state_required();
        const bool has_keysets =
            state.pending_write == ReadLocalRobState::PendingWrite::Keyset ||
            state.write_keyset_slots != 0;
        const uint64_t probe_filter = has_keysets
            ? ReadLocalRobState::keyset_filter(hash) : 0;
        // acquire_read_local normally resolves this first. Preserve the no-false-negative contract
        // if a future armed caller probes without acquiring through that door.
        if (state.pending_write == ReadLocalRobState::PendingWrite::Overflow) return true;
        if (state.pending_write == ReadLocalRobState::PendingWrite::Hash &&
            state.pending_hash == hash)
            return true;
        if (state.pending_write == ReadLocalRobState::PendingWrite::Keyset) {
            if ((state.pending_hash & probe_filter) == probe_filter &&
                keyset_touches_hash(at(state.pending_op_id), hash))
                return true;
        }
        if (!state.overflow && state.write_count == 0) {
            read_local_try_deactivate(state);
            return false;
        }
        read_local_prune(state);
        if (state.overflow) return true;
        if (state.write_count == 0) {
            read_local_try_deactivate(state);
            return false;
        }
        for (uint32_t i = 0; i < state.write_count; i++) {
            const uint32_t at =
                (static_cast<uint32_t>(state.write_head) + i) &
                (ReadLocalRobState::kWriteRingCapacity - 1);
            if (state.write_keyset_slots & (uint16_t{1} << at)) {
                if ((state.write_ring[at].hash & probe_filter) == probe_filter &&
                    keyset_touches_hash(this->at(state.write_ring[at].op_id), hash))
                    return true;
            } else if (state.write_ring[at].hash == hash) {
                return true;
            }
        }
        return false;
    }

    // Boot-only, before the connection is visible to any loop or kernel registration.
    bool prepare_read_local() {
        if (read_local_state_) return true;
        ReadLocalRobState* state = new (std::nothrow) ReadLocalRobState;
        if (!state) return false;
        const uintptr_t ptr = reinterpret_cast<uintptr_t>(state);
        if (ptr & kReadLocalStateInactive) std::abort();
        read_local_state_ = ptr | kReadLocalStateInactive;
        return true;
    }

    // ---- consumer side (whichever stage sends) -------------------------------------------------
    // Retire every completed op from the head, in order, handing each reply to `sink`. Stops at the
    // first op still running — a later op finishing early must wait, which is the whole point.
    template <typename Sink>
    uint32_t drain(Sink&& sink) {
        const uint64_t d = dispatch_.load(std::memory_order_acquire);
        uint64_t f = flush_.load(std::memory_order_relaxed);
        uint32_t n = 0;
        while (f != d) {
            Op& op = *slot(static_cast<uint32_t>(f) & kMask, false);
            if (op.state.load(std::memory_order_acquire) != OpState::Done) break;
            sink(op);                                   // the acquire above orders the reply bytes
            if (op.oversized()) op.shrink();            // bounded retention: bursts do not pin heap
            op.state.store(OpState::Free, std::memory_order_relaxed);
            f++;
            n++;
        }
        // One release store for the whole batch rather than one per op: the producer only needs to
        // learn the final position, and each store would otherwise bounce the line.
        if (n) flush_.store(f, std::memory_order_release);
        return n;
    }

    // Slot access for the worker side, which addresses ops by id rather than by pointer so a stale
    // pointer can never outlive a recycle.
    Op& at(uint64_t id) { return *slot(static_cast<uint32_t>(id) & kMask, false); }
    const Op& at(uint64_t id) const { return const_cast<Rob*>(this)->at(id); }

    ~Rob() {
        for (uint32_t i = 0; i < kChunks; i++) delete[] chunks_[i];
        delete read_local_state_ptr();
    }

private:
    static constexpr uint32_t kChunkOps = 8;
    static constexpr uint32_t kChunks   = Capacity / kChunkOps;
    static_assert(Capacity % kChunkOps == 0);

    // may_grow is true only from acquire() — the parser. Everyone else dereferences ground the
    // parser already materialized.
    __attribute__((always_inline)) Op* slot(uint32_t idx, bool may_grow) {
        Op*& ch = chunks_[idx / kChunkOps];
        if (!ch && may_grow) ch = new Op[kChunkOps];
        return &ch[idx % kChunkOps];
    }

    static constexpr uint64_t capacity_slots_mask() {
        if constexpr (Capacity == 64) return UINT64_MAX;
        else return (uint64_t{1} << Capacity) - 1;
    }

    static uint64_t active_slots_mask(uint64_t dispatch, uint64_t flush) {
        const uint32_t count = static_cast<uint32_t>(dispatch - flush);
        if (!count) return 0;
        if (count >= Capacity) return capacity_slots_mask();
        const uint32_t begin = static_cast<uint32_t>(flush) & kMask;
        const uint64_t run = (uint64_t{1} << count) - 1;
        uint64_t mask = run << begin;
        if (begin + count > Capacity) mask |= run >> (Capacity - begin);
        return mask & capacity_slots_mask();
    }

    static constexpr uintptr_t kReadLocalStateInactive = 1;

    ReadLocalRobState* read_local_state_ptr() const {
        return reinterpret_cast<ReadLocalRobState*>(
            read_local_state_ & ~kReadLocalStateInactive);
    }
    bool read_local_state_active() const {
        return read_local_state_ != 0 &&
               (read_local_state_ & kReadLocalStateInactive) == 0;
    }
    void read_local_state_activate() {
        if (!read_local_state_) std::abort();
        read_local_state_ &= ~kReadLocalStateInactive;
    }
    ReadLocalRobState& read_local_state_required() {
        ReadLocalRobState* state = read_local_state_ptr();
        if (!state) std::abort();
        return *state;
    }
    const ReadLocalRobState& read_local_state_required() const {
        const ReadLocalRobState* state = read_local_state_ptr();
        if (!state) std::abort();
        return *state;
    }
    void read_local_try_deactivate(const ReadLocalRobState& state) {
        if (!state.overflow && state.write_count == 0 &&
            state.pending_write == ReadLocalRobState::PendingWrite::None &&
            state.local_mget_fence_id == UINT64_MAX)
            read_local_state_ |= kReadLocalStateInactive;
    }

    // Slot half shared by both mark_current_read_local forms.
    __attribute__((always_inline)) void mark_current_read_local_slot(uint64_t op_id) {
        const uint64_t bit = uint64_t{1} << (static_cast<uint32_t>(op_id) & kMask);
        if (read_local_owner_slots_ & bit) std::abort();
        read_local_pending_slots_ |= bit;
    }

    void read_local_clear_mget_fence(uint64_t op_id) {
        if (!read_local_state_active()) return;
        ReadLocalRobState& state = read_local_state_required();
        if (state.local_mget_fence_id != op_id) return;
        state.local_mget_fence_id = UINT64_MAX;
        read_local_try_deactivate(state);
    }

    static bool read_local_id_active(uint64_t op_id, uint64_t dispatch, uint64_t flush) {
        return op_id - flush < dispatch - flush;
    }

    void read_local_prune(ReadLocalRobState& state) {
        if (!state.overflow && state.write_count == 0) return;
        read_local_prune(state, dispatch_id(), flush_id());
    }

    static void read_local_prune(ReadLocalRobState& state, uint64_t dispatch, uint64_t flush) {
        if (state.overflow) {
            if (read_local_id_active(state.overflow_through, dispatch, flush)) return;
            state.overflow = false;
            state.write_head = 0;
            state.write_count = 0;
            state.write_keyset_slots = 0;
            return;
        }
        while (state.write_count &&
               !read_local_id_active(
                   state.write_ring[state.write_head].op_id, dispatch, flush)) {
            state.write_keyset_slots &=
                static_cast<uint16_t>(~(uint16_t{1} << state.write_head));
            state.write_head = static_cast<uint8_t>(
                (state.write_head + 1) & (ReadLocalRobState::kWriteRingCapacity - 1));
            state.write_count--;
        }
        if (!state.write_count) {
            state.write_head = 0;
            state.write_keyset_slots = 0;
        }
    }

    void read_local_resolve_pending(ReadLocalRobState& state) {
        using PendingWrite = ReadLocalRobState::PendingWrite;
        if (state.pending_write == PendingWrite::None) return;
        const uint64_t dispatch = dispatch_id();
        const uint64_t flush = flush_id();
        const uint64_t op_id = state.pending_op_id;
        const PendingWrite pending = state.pending_write;
        const uint64_t hash = state.pending_hash;
        state.pending_write = PendingWrite::None;

        // The op either never published / was unpublished, or published and already retired before
        // another frame on this connection could be considered. Neither can constrain that frame.
        if (!read_local_id_active(op_id, dispatch, flush)) return;

        read_local_prune(state, dispatch, flush);
        if (state.overflow || pending == PendingWrite::Overflow) {
            state.overflow = true;
            state.overflow_through = op_id;
            state.write_head = 0;
            state.write_count = 0;
            state.write_keyset_slots = 0;
            return;
        }

        if (state.write_count == ReadLocalRobState::kWriteRingCapacity) {
            state.overflow = true;
            state.overflow_through = op_id;
            state.write_head = 0;
            state.write_count = 0;
            state.write_keyset_slots = 0;
            return;
        }
        const uint32_t tail =
            (static_cast<uint32_t>(state.write_head) + state.write_count) &
            (ReadLocalRobState::kWriteRingCapacity - 1);
        state.write_ring[tail] = ReadLocalRobState::WriteKey{hash, op_id};
        if (pending == PendingWrite::Keyset)
            state.write_keyset_slots |= uint16_t{1} << tail;
        else
            state.write_keyset_slots &= static_cast<uint16_t>(~(uint16_t{1} << tail));
        state.write_count++;
    }

    Op* chunks_[kChunks] = {};
    // Separate cache lines: the producer writes dispatch_ while the consumer writes flush_, and
    // sharing a line would make every publish invalidate the consumer's copy and vice versa.
    alignas(64) std::atomic<uint64_t> dispatch_{0};
    alignas(64) std::atomic<uint64_t> flush_{0};
    // Venue-pending and owner-tail bitmaps distinguish work that a write must still demote from
    // work already sequenced on ordinary owner queues. The sidecar pointer's low alignment bit
    // means no write generation is active, so pure GETs do not dereference heap state. All three
    // words remain inside flush_'s established trailing padding.
    uint64_t read_local_pending_slots_ = 0;
    uint64_t read_local_owner_slots_ = 0;
    uintptr_t read_local_state_ = 0;
    // Superset of the pending reads' key hashes (see ReadLocalPendingFilter). It completes flush_'s
    // cache line: the parser that marks/probes it already owns that line for the bitmaps above.
    ReadLocalPendingFilter read_local_pending_filter_;

    // Removing a pending read never shrinks the filter (superset stays valid); an empty pending set
    // is the one point where the summary can be reset for free.
    void read_local_retire_pending_bit(uint64_t bit) {
        read_local_pending_slots_ &= ~bit;
        if (!read_local_pending_slots_) read_local_pending_filter_.clear();
    }
};

// The bitmaps, tagged sidecar pointer and pending-key filter deliberately occupy the pre-existing
// tail of flush_'s cache line. Locking the complete ROB keeps future accounting from silently
// growing every client.
static_assert(sizeof(Rob<64>) == 192, "Rob<64> layout changed");

}  // namespace tomo
