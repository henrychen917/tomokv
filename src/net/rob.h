// rob.h — the reorder buffer. One per connection.
//
// THE PROBLEM IT SOLVES. A pipelined client sends GET a, GET b, GET c on one socket. Those keys can
// live on three different workers, which finish in any order. The protocol requires the replies to
// come back in the order sent. So we need out-of-order execution with in-order retirement — which
// is a reorder buffer, and naming it that is not an analogy: dispatch_id is the issue pointer,
// flush_id is the commit pointer, and a slot is retired only when every older slot has retired.
//
//   dispatch_id  next id to issue           (moves as the parser produces ops)
//   flush_id     next id to retire          (moves as completed ops are emitted, strictly in order)
//   slot(id)     id & mask                  (the ring is power-of-two)
//   in_flight    dispatch_id - flush_id
//
//   dispatch_id == flush_id  is the universal quiescence fence. Nothing is in flight, so the
//   connection can be closed, migrated between IO threads, or have its buffers recycled safely.
//   Every teardown path should test exactly this and nothing else.
//
// READ-BUFFER PINNING FALLS OUT FOR FREE. argv Slices point into the connection's read buffer. Since
// retirement is strictly in order, the oldest live op is always slot(flush_id) — so every byte
// before that op's rbuf_off is dead and the buffer can be compacted up to it. No refcounting, no
// generation numbers. This is the structural answer to the fork's worker-argv-after-recycle race.
#pragma once
#include <cstdint>
#include "../exec/op.h"

namespace tomo {

template <uint32_t Capacity>
class Rob {
    static_assert((Capacity & (Capacity - 1)) == 0, "capacity must be a power of two");
    static constexpr uint32_t kMask = Capacity - 1;

public:
    uint32_t in_flight() const { return dispatch_id_ - flush_id_; }
    bool     full()      const { return in_flight() >= Capacity; }
    bool     quiesced()  const { return dispatch_id_ == flush_id_; }

    uint64_t dispatch_id() const { return dispatch_id_; }
    uint64_t flush_id()    const { return flush_id_; }

    // Claim the next slot to fill. Returns nullptr when the window is full — the caller must stop
    // parsing and let replies drain. That backpressure is what bounds memory under a client that
    // pipelines without reading, and dropping it is how a server OOMs on one misbehaving connection.
    Op* acquire() {
        if (full()) return nullptr;
        Op* op = &slots_[dispatch_id_ & kMask];
        op->reset();
        return op;
    }

    // Publish the slot claimed by acquire(). Separated from acquire() because the parser may fail
    // partway through building an op and must be able to abandon it without advancing the ROB.
    void publish() { dispatch_id_++; }

    // Retire every completed op from the head, in order, handing each reply to `sink`. Stops at the
    // first op still running — a later op finishing early must wait, which is the whole point.
    // Returns the number retired.
    template <typename Sink>
    uint32_t drain(Sink&& sink) {
        uint32_t n = 0;
        while (flush_id_ != dispatch_id_) {
            Op& op = slots_[flush_id_ & kMask];
            if (op.state.load(std::memory_order_acquire) != OpState::Done) break;
            sink(op);                                   // acquire above orders the reply bytes
            op.state.store(OpState::Free, std::memory_order_relaxed);
            flush_id_++;
            n++;
        }
        return n;
    }

    // The oldest live op's offset into the read buffer; everything before it is dead. Returns
    // UINT32_MAX when quiesced, meaning the whole buffer is reclaimable.
    uint32_t pinned_rbuf_off() const {
        if (quiesced()) return UINT32_MAX;
        return slots_[flush_id_ & kMask].rbuf_off;
    }

    // Slot access for the worker side, which addresses ops by id rather than by pointer so a stale
    // pointer can never outlive a recycle.
    Op& at(uint64_t id) { return slots_[id & kMask]; }

private:
    Op       slots_[Capacity];
    uint64_t dispatch_id_ = 0;
    uint64_t flush_id_    = 0;
};

}  // namespace tomo
