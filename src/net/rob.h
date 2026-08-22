// rob.h — the reorder buffer. One per connection.
//
// THE PROBLEM IT SOLVES. A pipelined client sends GET a, GET b, GET c on one socket. Those keys can
// live on three different workers, which finish in any order. The protocol requires the replies in
// the order sent. So we need out-of-order execution with in-order retirement — a reorder buffer, and
// the name is not an analogy: dispatch_id is the issue pointer, flush_id is the commit pointer, and
// a slot retires only when every older slot has retired.
//
//   dispatch_id  next id to issue     — advanced by the PARSER (an io thread)
//   flush_id     next id to retire    — advanced by the SENDER (io, ex or wb, depending on mode)
//   slot(id)     id & mask
//   in_flight    dispatch_id - flush_id
//
//   dispatch_id == flush_id is the universal quiescence fence. Nothing is in flight, so the
//   connection can be closed, migrated, or have its buffers recycled. Every teardown path tests
//   exactly this and nothing else.
//
// ============================================================================================
// THE TWO ENDS CAN BE DIFFERENT THREADS, and that is the point of the 3-stage and ex-wb modes.
//
//   producer (io)     fills a slot, then RELEASES dispatch_id
//   consumer (sender) ACQUIRES dispatch_id, reads the slot, then RELEASES flush_id
//   producer          ACQUIRES flush_id to learn which slots are free again
//
// That is a plain SPSC handshake on two counters, which is why they are atomics rather than plain
// integers. In 2-stage mode both ends are the same thread and the atomics degrade to ordinary loads
// and stores on x86 — the mode costs nothing when unused.
//
// WHY IT MATTERS THAT THE SENDER RETIRES. If the io thread retires and merely hands the bytes to a
// sender, the only thing that actually moves between modes is the send syscall — everything else
// still runs on io, so an "ex-wb" measured that way is not ex-wb. With the sender draining the ROB,
// reply assembly, buffer staging and the write all leave the io thread together, which is the
// design the fork's 3-stage actually had.
//
// READ-BUFFER PINNING STILL FALLS OUT. argv Slices point into the connection's read buffer. Because
// retirement is strictly in order, the oldest live op is always slot(flush_id) — so every byte
// before that op's rbuf_off is dead. No refcounting, no generation numbers.
#pragma once
#include <atomic>
#include <cstdint>
#include "../exec/op.h"

namespace tomo {

template <uint32_t Capacity>
class Rob {
    static_assert((Capacity & (Capacity - 1)) == 0, "capacity must be a power of two");
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
    Op* acquire() {
        if (full()) return nullptr;
        Op* op = &slots_[dispatch_id() & kMask];
        op->reset();
        return op;
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

    // ---- consumer side (whichever stage sends) -------------------------------------------------
    // Retire every completed op from the head, in order, handing each reply to `sink`. Stops at the
    // first op still running — a later op finishing early must wait, which is the whole point.
    template <typename Sink>
    uint32_t drain(Sink&& sink) {
        const uint64_t d = dispatch_.load(std::memory_order_acquire);
        uint64_t f = flush_.load(std::memory_order_relaxed);
        uint32_t n = 0;
        while (f != d) {
            Op& op = slots_[f & kMask];
            if (op.state.load(std::memory_order_acquire) != OpState::Done) break;
            sink(op);                                   // the acquire above orders the reply bytes
            op.state.store(OpState::Free, std::memory_order_relaxed);
            f++;
            n++;
        }
        // One release store for the whole batch rather than one per op: the producer only needs to
        // learn the final position, and each store would otherwise bounce the line.
        if (n) flush_.store(f, std::memory_order_release);
        return n;
    }

    // The oldest live op's offset into the read buffer; everything before it is dead. UINT32_MAX
    // when quiesced, meaning the whole buffer is reclaimable.
    uint32_t pinned_rbuf_off() const {
        if (quiesced()) return UINT32_MAX;
        return slots_[flush_id() & kMask].rbuf_off;
    }

    // Slot access for the worker side, which addresses ops by id rather than by pointer so a stale
    // pointer can never outlive a recycle.
    Op& at(uint64_t id) { return slots_[id & kMask]; }

private:
    Op slots_[Capacity];
    // Separate cache lines: the producer writes dispatch_ while the consumer writes flush_, and
    // sharing a line would make every publish invalidate the consumer's copy and vice versa.
    alignas(64) std::atomic<uint64_t> dispatch_{0};
    alignas(64) std::atomic<uint64_t> flush_{0};
};

}  // namespace tomo
