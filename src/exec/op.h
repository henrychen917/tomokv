// In-flight command and reply storage shared by parser, executor and ROB headers.
// An Op owns its argument array and reply buffer, but argv slices usually borrow the connection's
// read buffer. The ROB pins those bytes through retirement. MULTI's heap child Ops and the
// stack-local Ops used by scripts and MULTI are never ROB slots; callers manage their lifetimes.
// Ownership handoff: IO fills an unpublished slot; Task publication hands its mutable fields
// to the executing owner, whose release Done hands them back before IO's acquire and retirement.
// Apart from state, no field may be written while another thread reads it. While an owner runs
// the Op, others may read only state and parser-published immutable metadata
// (see ShadowDispatch::length); special completion protocols are described below.
// The connection owner retires replies in order and sends them. Borrowed values and tagged state have separate cleanup
// hooks; reset/destruction alone do not release those resources. sizeof(Op) is locked at 336 bytes.
#pragma once
#include <atomic>
#include <cstdint>
#include <cstring>
#include <string_view>
#include "../base/slice.h"
#include "../cmd/txnorder_debug.h"

namespace tomo {

struct CommandSpec;
class Client;
struct ScatterState;
struct BlockingState;

enum class OpState : uint8_t {
    Free = 0,     // slot is reusable
    Issued = 1,   // shutdown drain sentinel; runtime dispatch does not store Issued
    Done = 2,     // worker finished; reply is complete and safe to read
    AofWait = 3,  // owner finished; persistence still owns the completion
};

// Most commands are 2-3 arguments (GET k / SET k v / DEL k). Spill only for the multi-key forms.
inline constexpr uint32_t kInlineArgv = 8;

// A GET reply for a 64-byte value is about 72 bytes, fitting the 96-byte inline buffer.
// The inline capacity budgets room for direct-reply and borrowed-value descriptors within
// the 336-byte Op stride. See docs/decisions/readability-a6.md for the footprint measurement.
inline constexpr size_t kInlineReply = 96;

// Coded replies carry a predetermined result or an executor-computed integer. For armed ROB
// slots, the connection owner formats these at retirement with format_reply_code() in net/resp.h;
// the executor need not write the final reply bytes. Reads carrying value bytes use the byte sink.
// Code arming belongs to the ROB, so child/script Ops keep replies their callers can parse.
enum class ReplyCode : uint8_t {
    None = 0,
    Ok = 1,         // "+OK\r\n"
    Nil = 2,        // "$-1\r\n"      RESP2 null bulk
    Pong = 3,       // "+PONG\r\n"
    NullArray = 4,  // "*-1\r\n"      RESP2 null array
    EmptyStr = 5,   // "$0\r\n\r\n"
    NullResp3 = 6,  // "_\r\n"        RESP3 null
    True = 7,       // "#t\r\n"
    False = 8,      // "#f\r\n"
    Int = 9,        // ":<reply_ival_>\r\n"
};

// Longest coded reply: ":-2147483648\r\n" is 14. Reserving one constant keeps the owner's
// materialise to a single capacity test with no per-code arithmetic.
inline constexpr uint32_t kReplyCodeMax = 16;

// The parser initializes an unpublished slot. Its completer writes the reply and publishes
// Done with release: the routed shard owner for an ordinary Task, or the connection owner for
// connection-local commands, local errors and read-local hits. Scatter, blocking, MULTI,
// pub/sub, script-escalation and persistence paths own their completion protocols until Done.
// The connection owner acquires Done before retirement/reuse. Argument slices, direct buffers and
// borrowed/tagged zc_ptr state must outlive their consumers; Op owns only its argv allocation and
// SmallBuf. push_arg returns false on allocation failure; SmallBuf::grow does not check malloc's
// result, so reply allocation failure is not handled. reset requires a reusable slot with all
// external resources already released.
class Op {
public:
    static constexpr int32_t kScatterStateMarker = -2;
    static constexpr int32_t kLocalXshardMarker = -3;
    static constexpr int32_t kBlockingStateMarker = -4;
    static constexpr int32_t kMultiStateMarker = -5;
    // A scatter whose final RESP/code is already in this Op. Its state still needs the
    // ordinary IO retire hook, but WB can count the reply without walking the arena.
    static constexpr int32_t kScatterReplyMarker = -6;
    Op() = default;
    ~Op() { std::free(argv_heap_); }
    Op(const Op&) = delete;
    Op& operator=(const Op&) = delete;

    // ---- built by the IO thread while parsing ------------------------------------------------
    // `Codes` MUST match the ROB's arming (Rob::acquire<Codes>). When it is false this op can
    // never carry a code -- Sink::code() declines on reply_code_ok_, which acquire<false> also
    // leaves alone -- so reply_code_ and reply_ival_ keep the zero they were constructed with and
    // re-zeroing them is pure per-op work on the io thread's parse path, in the mode that gets no
    // benefit from it. Defaults to true so the heap child Ops in multi.inc, which call reset()
    // directly and are never acquired, keep the unconditional clear.
    template <bool Codes = true>
    void reset(uint8_t route_flags = 0) {
        argc_ = 0;
        spec = nullptr;
        shard = -1;
        read_cut_lo = 0;
        route_flags_ = route_flags;
        if constexpr (Codes) {
            reply_code_ = 0;
            reply_ival_ = 0;
        }
        reply.clear();
        direct = nullptr;
        direct_cap = direct_len = 0;
        zc_ptr = nullptr;
        zc_len = 0;
        zc_shard = -1;
        state.store(OpState::Free, std::memory_order_relaxed);
    }

    // Bit 7 overlaps Client::kBlocked; connection bit 6 is unused. The armed coarse parser
    // clears both read-local classification bits before classifying the slot; ordinary ROB
    // acquisition uses reset() without this read-local flag sanitization.
    void reset_read_local(uint8_t route_flags = 0) {
        reset<true>(static_cast<uint8_t>(
            route_flags & static_cast<uint8_t>(~(kReadLocal | kReadLocalPreciseWrite))));
    }

    bool push_arg(Slice s) {
        if (!argv_heap_ && argc_ < kInlineArgv) {
            argv_inline_[argc_++] = s;
            return true;
        }
        const uint32_t need = argc_ + 1;
        if (need > argv_cap_) {
            uint32_t new_capacity = argv_cap_ ? argv_cap_ * 2 : kInlineArgv * 2;
            while (new_capacity < need) new_capacity *= 2;
            auto* new_argv =
                static_cast<Slice*>(std::realloc(argv_heap_, new_capacity * sizeof(Slice)));
            if (!new_argv) return false;
            if (!argv_heap_) std::memcpy(new_argv, argv_inline_, kInlineArgv * sizeof(Slice));
            argv_heap_ = new_argv;
            argv_cap_ = new_capacity;
        }
        argv_heap_[argc_++] = s;
        return true;
    }

    uint32_t argc() const { return argc_; }
    Slice arg(uint32_t i) const { return argv_heap_ ? argv_heap_[i] : argv_inline_[i]; }
    Slice cmd_name() const { return argc_ ? arg(0) : Slice{}; }
    Slice key() const {
        return argc_ > 1 ? arg(1) : Slice{};
    }  // point-key accessor; routed subcommands may differ

    // Recycles heap growth so one MSET-1000 or one 64MB reply does not permanently inflate every
    // ring slot. Called from Rob::drain at retire, gated so the common case (inline argv, inline
    // reply) pays one predictable branch and frees nothing.
    static constexpr size_t kShrinkKeep =
        4096;  // reply heap above this is a burst, not a working size
    void shrink() {
        if (argv_heap_) {
            std::free(argv_heap_);
            argv_heap_ = nullptr;
            argv_cap_ = 0;
        }
        reply.shrink_to_inline();
    }
    bool oversized() const { return argv_heap_ != nullptr || reply.cap() > kShrinkKeep; }

    // ---- fields --------------------------------------------------------------------------------
    const CommandSpec* spec = nullptr;
    int32_t shard = -1;  // resolved by the router before publishing

    // IO stamps read-only operations at prepare so GET and multi-key reads on one connection
    // use cuts in program order. Sampling a plain read only at execution could make an earlier
    // GET newer than a following MGET pinned before a foreign commit. Writes use the newest
    // view because a stale update base can lose an intervening write.
    //
    // Only the low 32 bits are kept, filling the four-byte alignment hole after shard within
    // the fixed 336-byte Op. read_cut() reconstructs the
    // most recent congruent sequence at/before now; exact reconstruction requires less than
    // 2^32 intervening commits. This helper does not enforce that age bound or saturate older
    // stamps. A bound over the full dispatch-to-execution lifetime is not established here.
    uint32_t read_cut_lo = 0;
    uint64_t hash = 0;  // computed once by IO, reused by the worker

    // Offset into the connection's read buffer where this op's arguments begin. Because the ROB
    // retires strictly in order, the oldest live op's rbuf_off is the low-water mark below which
    // every byte is dead — that is how the read buffer gets compacted without refcounting the
    // Slices that point into it.
    uint32_t rbuf_off = 0;

    // IO knows whether this command was issued behind an unfinished cross-shard atomic group on
    // the same connection. Capture that fact before publish so executors can skip the owner-local
    // pending lookup without reading a remote Client cache line. The bit shares route_flags_
    // before SmallBuf within the 336-byte footprint.
    void mark_atomic_hazard() { route_flags_ |= kAtomicHazard; }
    bool atomic_hazard() const { return route_flags_ & kAtomicHazard; }
    void mark_no_borrow() { route_flags_ |= kNoBorrow; }
    bool no_borrow() const { return route_flags_ & kNoBorrow; }
    void mark_resp3() { route_flags_ |= kResp3; }
    bool resp3() const { return route_flags_ & kResp3; }
    // CLIENT REPLY OFF/SKIP. Marked by the io thread's armed gate, honoured by the cold
    // suppressing serve variant. Bit 3 is unused in Client::connection_flags_, so reset's
    // wholesale byte copy leaves reply-skip clear; only the IO armed gate sets it.
    // Keep Op-only bits 0, 1, 3, 5 and 6 unused in connection_flags_.
    void mark_reply_skip() { route_flags_ |= kReplySkip; }
    void clear_reply_skip() { route_flags_ &= static_cast<uint8_t>(~kReplySkip); }
    bool reply_skip() const { return route_flags_ & kReplySkip; }
    // CLIENT NO-TOUCH, captured from the connection flag byte by reset(). Read only by ExLoop,
    // and only when maxmemory is enabled.
    bool no_touch() const { return route_flags_ & kNoTouch; }
    // Bit 5 is reserved for a read cut and is not set in Client::connection_flags_. An
    // unstamped operation therefore uses the newest view after reset() copies those flags.
    void set_read_cut(uint64_t cut) {
        read_cut_lo = static_cast<uint32_t>(cut);
        route_flags_ |= kReadCut;
    }
    bool has_read_cut() const { return route_flags_ & kReadCut; }
    // `now` must be a sequence value observed no earlier than the stamp, which every caller has
    // because commit sequences only move forward and the stamp happened on this connection's IO
    // thread before dispatch.
    uint64_t read_cut(uint64_t now) const {
        uint64_t cut = (now & ~uint64_t{0xFFFFFFFF}) | read_cut_lo;
        if (cut > now) cut -= uint64_t{1} << 32;
        return cut;
    }
    // Fused read-local bookkeeping uses bit 6, cleared by reset_read_local() above.
    void mark_read_local() { route_flags_ |= kReadLocal; }
    bool read_local() const { return route_flags_ & kReadLocal; }
    // A precise write promises that it cannot mutate outside its declared point/keyset. If an
    // evicting maxmemory policy becomes live after IO made that classification, the owner uses
    // this immutable stamp to suspend eviction for this operation. Bit 7 is Client's blocked
    // flag; reset_read_local() masks the captured connection value before armed code reuses it.
    void mark_read_local_precise_write() { route_flags_ |= kReadLocalPreciseWrite; }
    bool read_local_precise_write() const { return route_flags_ & kReadLocalPreciseWrite; }
    uint8_t route_flags_ = 0;

    // The code shares the four-byte flag region before pointer-aligned SmallBuf, within the
    // 336-byte stride. Nonzero selects a reply the connection owner formats at retirement.
    uint8_t reply_code_ = 0;

    // WHO MAY CARRY A CODE. Only an Op the ROB handed out, because only those retire through
    // WbEngine::serve, which is the one place that knows how to turn a code back into bytes.
    //
    // The tree has Ops that never go near that path and whose reply bytes are read back by other
    // code: MULTI builds a heap child Op per queued command and splices its reply into the public
    // op's buffer (multi.inc make_child_op / set_state_reply), and redis.call() runs into a
    // stack-local Op whose bytes Lua parses back into a Lua value (scripting.cc). Those are
    // reset() but never acquired, so they default to unarmed and use byte replies. reset()
    // must not touch the arming. Rob::acquire<true>() and acquire_read_local() arm on every
    // acquisition; acquire<false>() leaves split slots unarmed. A borrowed-MGET splice
    // disarms its Op for the rest of that operation.
    uint8_t reply_code_ok_ = 0;
    uint8_t db = 0;  // logical database captured at parse time

    SmallBuf<kInlineReply> reply;  // worker writes RESP here (the spill/general sink)

    // DIRECT REPLY (owner's c->buf trick, both postures). When io dispatches an op that is the ROB
    // HEAD of a connection with an EMPTY fill buffer, it points `direct` at that buffer's storage.
    // The worker then formats RESP bytes straight into their final destination and only records the
    // length here; the SENDER publishes the length into the buffer at in-order retire (commit_raw).
    // The bytes cross threads under the same Done release/acquire as everything else; the buffer's
    // SIZE is only ever written by the sender, so no new sharing is introduced. Nothing can move or
    // grow the buffer in the window: there are no prior unretired ops (head) and no staged bytes
    // (empty), so no append and no fill/send swap can occur before our own retire.
    // Replies that do not fit fall back to `reply` mid-op; retire emits direct bytes first, then the
    // spill, preserving RESP order. The connection owner performs the send syscall.
    char* direct = nullptr;
    uint32_t direct_cap = 0;
    uint32_t direct_len = 0;

    // A borrowed GET value is published with Done exactly like reply bytes. The pointer names
    // FlatStore-owned memory; the shard id is the return address for the eventual io->ex release.
    // No Client or socket state crosses to the executor through this descriptor.
    const char* zc_ptr = nullptr;
    uint32_t zc_len = 0;
    int32_t zc_shard = -1;

    // The mutable field accessed concurrently. Release Done (or AofWait) publishes every
    // write the completer made to this Op, including flags/descriptors, before an acquiring
    // observer; IO must acquire Done before retirement.
    std::atomic<OpState> state{OpState::Free};
    uint8_t physical_db = 0;   // immutable routing namespace for this operation
    uint8_t secondary_db = 0;  // COPY/MOVE destination, captured with physical_db
    uint8_t target_db = 0;     // destination's logical name

    void set_arg_namespace(uint32_t i, uint8_t ns) {
        (argv_heap_ ? argv_heap_[i] : argv_inline_[i]).set_namespace(ns);
    }
    void replace_arg(uint32_t i, Slice value) {
        (argv_heap_ ? argv_heap_[i] : argv_inline_[i]) = value;
    }

    // The integer that goes with ReplyCode::Int -- a value the executor computed, not a format.
    // It occupies the four-byte-aligned field at 188 before the argv header at 192. Integers
    // outside the int32 range use byte replies, preserving the numeric result without growing Op.
    int32_t reply_ival_ = 0;

    // Contract: a handler's temporary, non-owning view of one Op; the caller exclusively owns
    // reply construction. reserve/advance must stay paired on this Sink and within reserved
    // capacity. Direct storage is used until spill; SmallBuf owns spill allocation. Source bytes
    // must not overlap the destination. Sink publishes nothing: the enclosing completion path
    // releases Done. code() refuses unarmed/nonempty replies so callers can emit bytes instead.
    class Sink {
    public:
        explicit Sink(Op& o) : op_(o) {}
        char* reserve(size_t n) {
            if (op_.direct && op_.reply.empty() && op_.direct_len + n <= op_.direct_cap) {
                last_direct_ = true;
                return op_.direct + op_.direct_len;
            }
            last_direct_ = false;
            return op_.reply.reserve(n);
        }
        void advance(size_t n) {
            if (last_direct_)
                op_.direct_len += static_cast<uint32_t>(n);
            else
                op_.reply.advance(n);
        }
        // Runtime-length append: values, members, error texts -- every reply a handler builds from
        // bytes whose length it did not know at compile time. reserve() returns either the
        // connection's direct region or op.reply's storage, and neither can alias a handler's
        // source bytes, so the no-overlap contract holds. Small runtime copies use bytes_copy;
        // larger copies use memcpy. Fixed replies take the array overload below. The archived
        // instruction-count comparison is in docs/decisions/readability-a6.md.
        void append(const char* s, size_t n) {
            char* p = reserve(n);
            if (__builtin_expect(n > kInlineByteCopyMax, false))
                std::memcpy(p, s, n);
            else
                bytes_copy(p, s, n);
            advance(n);
        }
        void append(std::string_view s) { append(s.data(), s.size()); }
        // Array references preserve literal length at compile time, allowing short RESP replies
        // to inline their copy. The 16-byte bound leaves larger texts on the runtime append path.
        // Both overloads append the same bytes, excluding the terminating NUL.
        template <size_t N>
        __attribute__((always_inline)) void append(const char (&lit)[N]) {
            static_assert(N >= 1, "append() takes a string literal");
            if constexpr (N - 1 <= kInlineLiteralMax) {
                char* p = reserve(N - 1);
                __builtin_memcpy(p, lit, N - 1);
                advance(N - 1);
            } else {
                append(static_cast<const char*>(lit), N - 1);
            }
        }
        void push_back(char ch) {
            char* p = reserve(1);
            *p = ch;
            advance(1);
        }

        // CODED REPLY. Records "the reply is this" instead of writing its bytes. Returns false
        // when this sink is not empty, so the caller must format bytes. That
        // is what keeps composition safe: EXEC writes its array header first, so every element
        // reply inside it sees a non-empty sink and takes the byte path, and the coded form can
        // only ever stand for a WHOLE reply.
        //
        // Setting a code DISARMS the direct region. A code is materialised at the fill buffer's
        // frontier at retire, and direct bytes live at that same offset; disarming means any
        // append that follows spills to op.reply, which retire emits AFTER the coded bytes. So
        // "code, then more bytes" and "bytes only" both keep RESP order, and the direct region
        // loses nothing -- the owner is writing into that very buffer either way.
        __attribute__((always_inline)) bool code(ReplyCode c, int32_t v = 0) {
            // Arming has its own unhinted branch: fused acquisitions arm each time, split
            // slots stay unarmed, and borrowed-MGET assembly may disarm mid-op. Combining
            // it with the unlikely nonempty test would bias all modes toward
            // the same answer. Keep the layout/branch decision in the decision log.
            if (!op_.reply_code_ok_) return false;
            if (__builtin_expect(op_.reply_code_ != 0 || op_.direct_len != 0 || !op_.reply.empty(),
                                 false))
                return false;
            op_.reply_code_ = static_cast<uint8_t>(c);
            op_.reply_ival_ = v;
            op_.direct = nullptr;
            return true;
        }

    private:
        Op& op_;
        bool last_direct_ = false;
    };
    Sink sink() { return Sink(*this); }

    // "Has a handler already written a reply?" BOTH regions have to be consulted. A short reply
    // lands in the direct region and leaves `reply` empty, so `reply.empty()` alone reads as
    // "nothing written yet" and a caller that then emits its own fallback error puts TWO replies
    // on the wire, permanently shifting every later reply on that connection.
    bool replied() const { return !reply.empty() || direct_len != 0 || reply_code_ != 0; }

    // THE reply reset. Every caller that discards a half-written reply to put an error in its
    // place must drop the code too, or the discarded reply survives as five bytes the handler
    // no longer believes it wrote. One method so a future reset site cannot forget the field.
    void clear_reply() {
        reply.clear();
        direct_len = 0;
        reply_code_ = 0;
        reply_ival_ = 0;
    }

    bool has_scatter_state() const {
        return zc_ptr != nullptr &&
               (zc_shard == kScatterStateMarker || zc_shard == kScatterReplyMarker);
    }
    ScatterState* scatter_state() const {
        return has_scatter_state() ? reinterpret_cast<ScatterState*>(const_cast<char*>(zc_ptr))
                                   : nullptr;
    }
    void attach_scatter_state(ScatterState* state_) {
        zc_ptr = reinterpret_cast<const char*>(state_);
        zc_len = 0;
        zc_shard = kScatterStateMarker;
    }
    void detach_scatter_state() {
        zc_ptr = nullptr;
        zc_len = 0;
        zc_shard = -1;
    }
    void mark_local_xshard() {
        zc_ptr = nullptr;
        zc_len = 0;  // snapshot write-gate cursor
        zc_shard = kLocalXshardMarker;
    }
    bool local_xshard() const { return zc_shard == kLocalXshardMarker; }
    void attach_multi_state(void* state_) {
        zc_ptr = static_cast<const char*>(state_);
        zc_len = 0;
        zc_shard = kMultiStateMarker;
    }
    bool has_multi_state() const { return zc_ptr != nullptr && zc_shard == kMultiStateMarker; }
    void* multi_state() const { return has_multi_state() ? const_cast<char*>(zc_ptr) : nullptr; }

    bool has_blocking_state() const {
        return zc_ptr != nullptr && zc_shard == kBlockingStateMarker;
    }
    BlockingState* blocking_state() const {
        return has_blocking_state() ? reinterpret_cast<BlockingState*>(const_cast<char*>(zc_ptr))
                                    : nullptr;
    }
    void attach_blocking_state(BlockingState* state_) {
        zc_ptr = reinterpret_cast<const char*>(state_);
        zc_len = 0;
        zc_shard = kBlockingStateMarker;
    }
    void detach_blocking_state() {
        zc_ptr = nullptr;
        zc_len = 0;
        zc_shard = -1;
    }

    // Notifications have two local slots: the ordinary non-borrow pointer and
    // the local-crossing marker plus pointer. The route marker is immutable
    // through attachment and abort; AOF, Rule-P and snapshot consumers still
    // need it after handlers emit their first event.
    bool has_notify_state() const {
        return zc_ptr != nullptr && (zc_shard == -1 || zc_shard == kLocalXshardMarker);
    }
    void attach_notify_state(void* state_) {
        zc_ptr = static_cast<const char*>(state_);
        zc_len = 0;
        if (!local_xshard()) zc_shard = -1;
    }
    void detach_notify_state() {
        zc_ptr = nullptr;
        zc_len = 0;
        if (!local_xshard()) zc_shard = -1;
    }
    void* notify_state() const { return has_notify_state() ? const_cast<char*>(zc_ptr) : nullptr; }

private:
    // The cold inline decoder stores Slices and their decoded bytes in one malloc block
    // at argv_heap_; shrink() and ~Op release both with the single argv free.
    friend struct RespInlineDecoder;
    static constexpr uint8_t kAtomicHazard = 1u << 0;
    static constexpr uint8_t kNoBorrow = 1u << 1;
    static constexpr uint8_t kResp3 = 1u << 2;
    static constexpr uint8_t kReplySkip = 1u << 3;
    static constexpr uint8_t kNoTouch = 1u << 4;
    static constexpr uint8_t kReadCut = 1u << 5;
    static constexpr uint8_t kReadLocal = 1u << 6;
    static constexpr uint8_t kReadLocalPreciseWrite = 1u << 7;
    // The hot pair is argc_ (reset/incremented by parsing, checked by execution) and argv_heap_
    // (tested by push_arg, every arg access, and oversized at retirement even when it is null).
    // The 16-byte argv header sits beside the first argument slots. At a 64-aligned base a GET's
    // header and two slots occupy 192..239; Op itself is only 8-aligned, so cache-line placement
    // depends on its address. argv_cap_ fills the header's four-byte alignment gap, keeping the
    // inline Slice array and the complete Op within the 336-byte stride.
    Slice* argv_heap_ = nullptr;
    uint32_t argv_cap_ = 0;
    uint32_t argc_ = 0;
    Slice argv_inline_[kInlineArgv];
};

// Layout contract: the ROB uses a 336-byte Op stride. New fields must fit that budget.
// Historical footprint evidence is archived in docs/decisions/readability-a6.md.
static_assert(sizeof(Op) == 336, "Op grew: pay for it inside the struct or re-run the 64c A/B");

}  // namespace tomo
