// op.h — one in-flight command. This is the execution context, and it is the ring slot of the ROB.
//
// GENERALITY BEYOND STRINGS comes from the reply representation, not from a type hierarchy: the
// worker writes RESP bytes straight into the Op's own buffer. A command that returns a hash, a
// range, or a nested array writes exactly the same way a GET does, so adding types later needs no
// change here. Nothing in Op knows what a value is.
//
// LIFETIME, which is the subtle part. argv entries are Slices INTO the connection's read buffer —
// that is what makes parsing zero-copy. So the read buffer must stay pinned until this Op retires.
// The ROB gives that for free: the buffer is pinned until flush_id passes the last Op referencing
// it. Getting this wrong is the same shape as the fork's worker-argv refcount race, where a worker
// touched argv after the owning thread had recycled it.
//
// OWNERSHIP HANDOFF. Exactly one field crosses threads: `state`. The IO thread publishes an Op with
// a release store of Issued; the worker consumes it, fills `reply`, and publishes Done with a
// release store; the IO thread observes Done with an acquire load and only then reads `reply`.
// Everything else is touched by one thread at a time, ordered by that single pair.
#pragma once
#include <atomic>
#include <cstdint>
#include <cstring>
#include <string_view>
#include "../base/slice.h"

namespace tomo {

struct CommandSpec;
class  Client;

enum class OpState : uint8_t {
    Free   = 0,   // slot is reusable
    Issued = 1,   // IO published it; the owning worker may take it
    Done   = 2,   // worker finished; reply is complete and safe to read
};

// Most commands are 2-3 arguments (GET k / SET k v / DEL k). Spill only for the multi-key forms.
inline constexpr uint32_t kInlineArgv = 8;

// A GET reply for a 64-byte value is ~72 bytes, so 112 inline keeps the common case allocation-
// free. 112, not 128: the direct-reply fields below took 16 bytes, and paying them out of the
// inline reply keeps sizeof(Op) at 336 -- the 128 version measured -3.7% at 64c p32, where the
// server sits on the DRAM wall and ROB footprint is the price of everything.
inline constexpr size_t kInlineReply = 112;

class Op {
public:
    Op() = default;
    ~Op() { std::free(argv_heap_); }
    Op(const Op&) = delete;
    Op& operator=(const Op&) = delete;

    // ---- built by the IO thread while parsing ------------------------------------------------
    void reset() {
        argc_ = 0;
        spec  = nullptr;
        shard = -1;
        reply.clear();
        direct = nullptr;
        direct_cap = direct_len = 0;
        state.store(OpState::Free, std::memory_order_relaxed);
    }

    bool push_arg(Slice s) {
        if (argc_ < kInlineArgv) { argv_inline_[argc_++] = s; return true; }
        const uint32_t need = argc_ + 1;
        if (need > argv_cap_) {
            uint32_t ncap = argv_cap_ ? argv_cap_ * 2 : kInlineArgv * 2;
            while (ncap < need) ncap *= 2;
            auto* n = static_cast<Slice*>(std::realloc(argv_heap_, ncap * sizeof(Slice)));
            if (!n) return false;
            if (!argv_heap_) std::memcpy(n, argv_inline_, kInlineArgv * sizeof(Slice));
            argv_heap_ = n;
            argv_cap_  = ncap;
        }
        argv_heap_[argc_++] = s;
        return true;
    }

    uint32_t argc() const { return argc_; }
    Slice arg(uint32_t i) const { return argv_heap_ ? argv_heap_[i] : argv_inline_[i]; }
    Slice cmd_name() const { return argc_ ? arg(0) : Slice{}; }
    Slice key() const { return argc_ > 1 ? arg(1) : Slice{}; }   // v1: key is always argv[1]

    // Recycles heap growth so one MSET-1000 does not permanently inflate every ring slot.
    void shrink() {
        if (argv_heap_) { std::free(argv_heap_); argv_heap_ = nullptr; argv_cap_ = 0; }
        reply.shrink_to_inline();
    }

    // ---- fields --------------------------------------------------------------------------------
    const CommandSpec* spec  = nullptr;
    int32_t            shard = -1;          // resolved by the router before publishing
    uint64_t           hash  = 0;           // computed once by IO, reused by the worker

    // Offset into the connection's read buffer where this op's arguments begin. Because the ROB
    // retires strictly in order, the oldest live op's rbuf_off is the low-water mark below which
    // every byte is dead — that is how the read buffer gets compacted without refcounting the
    // Slices that point into it. See Rob::pinned_rbuf_off().
    uint32_t rbuf_off = 0;
    uint8_t  db       = 0;              // session snapshot at parse -- handlers never see Session

    SmallBuf<kInlineReply> reply;           // worker writes RESP here (the spill/general sink)

    // DIRECT REPLY (owner's c->buf trick, both postures). When io dispatches an op that is the ROB
    // HEAD of a connection with an EMPTY fill buffer, it points `direct` at that buffer's storage.
    // The worker then formats RESP bytes straight into their final destination and only records the
    // length here; the SENDER publishes the length into the buffer at in-order retire (commit_raw).
    // The bytes cross threads under the same Done release/acquire as everything else; the buffer's
    // SIZE is only ever written by the sender, so no new sharing is introduced. Nothing can move or
    // grow the buffer in the window: there are no prior unretired ops (head) and no staged bytes
    // (empty), so no append and no fill/send swap can occur before our own retire.
    // Replies that do not fit fall back to `reply` mid-op; retire emits direct bytes first, then the
    // spill, preserving RESP order. This is NOT exwb: the send syscall stays with the sender.
    char*    direct     = nullptr;
    uint32_t direct_cap = 0;
    uint32_t direct_len = 0;

    // The only cross-thread field. Acquire/release on this orders everything else.
    std::atomic<OpState> state{OpState::Free};

    // The handler-facing reply sink: prefers the direct region while the whole reply fits, spills
    // to op.reply otherwise. Same interface as SmallBuf, so the resp.h helpers take either.
    class Sink {
    public:
        explicit Sink(Op& o) : op_(o) {}
        char* reserve(size_t n) {
            if (op_.direct && op_.reply.empty() &&
                op_.direct_len + n <= op_.direct_cap) {
                last_direct_ = true;
                return op_.direct + op_.direct_len;
            }
            last_direct_ = false;
            return op_.reply.reserve(n);
        }
        void advance(size_t n) {
            if (last_direct_) op_.direct_len += static_cast<uint32_t>(n);
            else              op_.reply.advance(n);
        }
        void append(const char* s, size_t n) { char* p = reserve(n); std::memcpy(p, s, n); advance(n); }
        void append(std::string_view s) { append(s.data(), s.size()); }
        void push_back(char ch) { char* p = reserve(1); *p = ch; advance(1); }
    private:
        Op&  op_;
        bool last_direct_ = false;
    };
    Sink sink() { return Sink(*this); }

private:
    Slice    argv_inline_[kInlineArgv];
    Slice*   argv_heap_ = nullptr;
    uint32_t argv_cap_  = 0;
    uint32_t argc_      = 0;
};

}  // namespace tomo
