// Per-connection protocol state, read storage, reply buffers and send segments used by IoLoop
// and WbEngine. One IO owner parses and sends at a time; migration changes ownership after the
// relevant protocol/transport drains. Pack receive/send scalars together and keep per-operation
// output/atomic-group counters off the executor-facing completion-routing cache line.
//
// Workers access ROB Op state/replies, argv slices into rbuf_, and reserved direct-reply bytes in
// buf_[]. Op::state's release Done store publishes reply bytes to the acquire in Rob::drain.
// Completion routing uses retire_queued_, wb_slot_, ifid_thread_ and id_; WATCH additionally uses
// its reference/generation/dirty atomics. The IO owner maintains buffer headers and cursors.
//
// ============================================================================================
// THE READ BUFFER MUST NEVER MOVE LIVE BYTES. This is the subtle one.
//
// argv Slices point INTO the read buffer — that is what makes parsing zero-copy. Compaction, the
// obvious way to reclaim space, memmoves the live region to offset 0. Doing that while ops are in
// flight silently invalidates every Slice a worker is about to read, on another thread. It would
// produce corrupted keys and wrong replies, intermittently, under pipelining only — close to the
// worst bug shape there is.
//
// So the buffer is APPEND-ONLY while anything is in flight, and is reset only at a quiescence
// point, where by definition no Slice into it survives. Growth is bounded by refusing to read more
// when the buffer is large and not draining; the ROB window already caps in-flight ops, so this
// converges rather than deadlocks.
//
// The alternative — copying argv into each Op — costs a memcpy per argument on the hot path, which
// is exactly the allocation/copy volume the design is trying to avoid.
// ============================================================================================
#pragma once
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <atomic>
#include <algorithm>
#include <limits>
#include <utility>
#include <sys/socket.h>
#include <sys/uio.h>
#include "rob.h"
#include "resp.h"
#include "../base/slice.h"

namespace tomo {

namespace r7 {
class ShadowLongIndex;
}
class Client;
struct MultiSession;
void multi_session_destroy(MultiSession* session);

// kRobWindow is defined by net/rob.h (included above), beside the ring that is sized from it.
inline constexpr size_t kRbufInitial = 16 * 1024;
inline constexpr size_t kRbufSoftCap = 1 * 1024 * 1024;  // stop BUFFERING BACKLOG past this
// The soft cap bounds buffered backlog. The live query-buffer limit and the inline
// protocol bound additionally constrain incomplete requests. Growth requires ROB quiescence.
inline constexpr size_t kRbufHardCap = UINT32_MAX;
// Each output buffer has 512 inline bytes and grows on demand. clear() keeps the allocation,
// so a connection retains its working capacity rather than carrying 32 KiB of inline staging.
inline constexpr size_t kWbufInline = 512;
// Largest single send the kernel accepts (Linux MAX_RW_COUNT); a CQE res is an int. Caps every
// legacy send request and the segment iovec window alike.
inline constexpr uint32_t kMaxSendBytes = 0x7ffff000u;

// Connection-lived database selection. ConnLocal session commands run on the IO owner, and
// the parser captures the selected database into each Op for handlers. No synchronization lives
// in Session; its caller supplies connection ownership.
struct Session {
    uint32_t db_index = 0;
};

// Independent mechanisms hold bits in the parse barrier; each release clears its own claim.
// Blocking dispatch requires an empty ROB and ends parsing, so no older/younger op surrounds it;
// the other barrier-producing dispatches also stop the parse pass. Separate owner bits preserve
// outstanding claims even if those dispatch guards change or a debug hold overlaps quiescence.
// The mask is one byte, and testing whether any claim remains is a comparison against zero.
// A new owner needs a distinct bit acquired where it parks the connection, not another owner's bit.
enum class BarrierOwner : uint8_t {
    Scatter = 1u << 0,   // two-hop store / all-shards fan-out; io_loop.h nonblocking_dispatch
    Blocking = 1u << 1,  // BLPOP-family, and the move scatter blocking_resume_move converts it into
    Wait = 1u << 2,      // deferred WAIT parked on its own deadline
    Exec = 1u << 3,      // EXEC fan-out; multi.inc
    PubSub = 1u << 4,    // (P|S)(UN)SUBSCRIBE transition awaiting its channel homes
    Climon = 1u << 5,    // CLIENT UNBLOCK (remote owner), CLIENT LIST / CLIENT KILL fan-out
    Sleep = 1u << 6,     // deferred DEBUG SLEEP connection timer
    // Client is footprint-locked. Seven production bits are assigned; an eighth production owner
    // needs a real layout decision, not a wider field.
    //
    // Test-only, and deliberately NOT released by the quiescence backstop -- it exists to hold the
    // barrier PAST ROB quiescence, which is the state no production sequence can currently produce
    // and the one the owner-scoped release must survive. Armed only by DEBUG BARRIER-HOLD.
    Debug = 1u << 7,
};

enum class SegmentKind : uint8_t { Buf = 0, Borrow = 1, Static = 2 };

// Queue element describing owned Buf bytes, a shard Borrow, or externally-lived Static bytes.
// SegmentQueue frees Buf storage and invokes its caller's release callback for consumed Borrows;
// copying this descriptor does not transfer or duplicate the underlying lifetime obligation.
struct ReplySegment {
    SegmentKind kind = SegmentKind::Static;
    const char* ptr = nullptr;
    uint32_t len = 0;
    int32_t shard = -1;
};

// Metadata stays inline for the common [header, value, CRLF] case. BUF payloads own independent
// blocks because queue growth and continued retirement must never move bytes named by an in-flight
// sendmsg. BORROW and STATIC payloads are non-owning under their respective lifetime protocols.
// The connection owner serializes mutation. consume/release_all/truncate return Borrows through
// the supplied callback; destruction alone frees Buf storage and metadata, not Borrow references.
// Callers must preserve in-flight iovec payloads. Growth uses unchecked malloc, with no recoverable
// allocation-failure result; this queue supplies neither locking nor back-pressure.
template <uint32_t Inline, size_t MaxSegmentBytes = UINT32_MAX>
class SegmentQueue {
    static_assert(MaxSegmentBytes > 0 && MaxSegmentBytes <= UINT32_MAX);

public:
    SegmentQueue() = default;
    ~SegmentQueue() {
        clear_without_releases();
        if (segs_ != inline_) std::free(segs_);
    }
    SegmentQueue(const SegmentQueue&) = delete;
    SegmentQueue& operator=(const SegmentQueue&) = delete;

    bool empty() const { return size_ == 0; }
    // Cold FLIP drain only: owned socket bytes may survive a role transition;
    // borrowed storage still names an executor and must be released first.
    bool has_borrow() const {
        for (uint32_t i = 0; i < size_; ++i)
            if (segs_[head_ + i].kind == SegmentKind::Borrow) return true;
        return false;
    }
    uint32_t size() const { return size_; }
    uint64_t byte_size() const {
        uint64_t bytes = 0;
        for (uint32_t i = 0; i < size_; i++) {
            const ReplySegment& segment = segs_[head_ + i];
            bytes += segment.len - (i == 0 ? offset_ : 0);
        }
        return bytes;
    }

    void append_buf(const char* ptr, size_t len) {
        while (len) {
            const size_t take = std::min(len, MaxSegmentBytes);
            char* copy = static_cast<char*>(std::malloc(take));
            std::memcpy(copy, ptr, take);
            push(ReplySegment{SegmentKind::Buf, copy, static_cast<uint32_t>(take), -1});
            ptr += take;
            len -= take;
        }
    }

    void append_buf(const char* a, size_t an, const char* b, size_t bn) {
        // Each segment has a 32-bit length, even when a whole collection reply is larger.
        if (an > MaxSegmentBytes || bn > MaxSegmentBytes - an) {
            append_buf(a, an);
            append_buf(b, bn);
            return;
        }
        const size_t total = an + bn;
        if (!total) return;
        char* copy = static_cast<char*>(std::malloc(total));
        if (an) std::memcpy(copy, a, an);
        if (bn) std::memcpy(copy + an, b, bn);
        push(ReplySegment{SegmentKind::Buf, copy, static_cast<uint32_t>(total), -1});
    }

    void append_borrow(const char* ptr, uint32_t len, int32_t shard) {
        push(ReplySegment{SegmentKind::Borrow, ptr, len, shard});
    }
    void append_static(const char* ptr, uint32_t len) {
        push(ReplySegment{SegmentKind::Static, ptr, len, -1});
    }

    uint32_t build_iov(iovec* out, uint32_t cap, uint32_t byte_cap, bool& has_borrow,
                       uint32_t& bytes) const {
        uint32_t n = 0;
        bytes = 0;
        has_borrow = false;
        for (uint32_t i = 0; i < size_ && n < cap && bytes < byte_cap; i++) {
            const ReplySegment& s = segs_[head_ + i];
            const uint32_t off = i == 0 ? offset_ : 0;
            if (off >= s.len) continue;
            const uint32_t len = std::min(s.len - off, byte_cap - bytes);
            out[n].iov_base = const_cast<char*>(s.ptr + off);
            out[n].iov_len = len;
            has_borrow |= s.kind == SegmentKind::Borrow;
            bytes += len;
            n++;
        }
        return n;
    }

    template <typename ReleaseFn>
    uint64_t consume(uint32_t bytes, ReleaseFn&& release) {
        uint64_t borrowed = 0;
        while (bytes && size_) {
            ReplySegment& s = segs_[head_];
            const uint32_t avail = s.len - offset_;
            const uint32_t take = std::min(bytes, avail);
            if (s.kind == SegmentKind::Borrow) borrowed += take;
            offset_ += take;
            bytes -= take;
            if (offset_ != s.len) break;
            if (s.kind == SegmentKind::Borrow) release(s.shard, s.ptr);
            pop_front();
        }
        return borrowed;
    }

    template <typename ReleaseFn>
    void release_all(ReleaseFn&& release) {
        for (uint32_t i = 0; i < size_; i++) {
            ReplySegment& s = segs_[head_ + i];
            if (s.kind == SegmentKind::Borrow)
                release(s.shard, s.ptr);
            else if (s.kind == SegmentKind::Buf)
                std::free(const_cast<char*>(s.ptr));
        }
        head_ = size_ = offset_ = 0;
    }

    // Drop segments from the TAIL back to `keep` entries; returns the bytes removed. Only ever
    // applied to segments appended since the last pump: the iovec window is built from the head
    // at pump time and pump never runs while a send is in flight, so nothing appended afterwards
    // can be named by the kernel. A partially sent head is by definition older than any such
    // segment -- the abort is the invariant, not a code path.
    template <typename ReleaseFn>
    uint64_t truncate(uint32_t keep, ReleaseFn&& release) {
        uint64_t bytes = 0;
        while (size_ > keep) {
            ReplySegment& s = segs_[head_ + size_ - 1];
            if (size_ == 1 && offset_) std::abort();
            bytes += s.len;
            if (s.kind == SegmentKind::Borrow)
                release(s.shard, s.ptr);
            else if (s.kind == SegmentKind::Buf)
                std::free(const_cast<char*>(s.ptr));
            size_--;
        }
        if (!size_) head_ = offset_ = 0;
        return bytes;
    }

private:
    void push(const ReplySegment& s) {
        if (head_ + size_ == cap_) make_tail_room();
        segs_[head_ + size_++] = s;
    }

    void make_tail_room() {
        if (head_) {
            std::memmove(segs_, segs_ + head_, size_ * sizeof(ReplySegment));
            head_ = 0;
            return;
        }
        const uint32_t ncap = cap_ * 2;
        auto* next = static_cast<ReplySegment*>(std::malloc(ncap * sizeof(ReplySegment)));
        std::memcpy(next, segs_, size_ * sizeof(ReplySegment));
        if (segs_ != inline_) std::free(segs_);
        segs_ = next;
        cap_ = ncap;
    }

    void pop_front() {
        ReplySegment& s = segs_[head_];
        if (s.kind == SegmentKind::Buf) std::free(const_cast<char*>(s.ptr));
        head_++;
        size_--;
        offset_ = 0;
        if (!size_) head_ = 0;
    }

    void clear_without_releases() {
        for (uint32_t i = 0; i < size_; i++) {
            ReplySegment& s = segs_[head_ + i];
            if (s.kind == SegmentKind::Buf) std::free(const_cast<char*>(s.ptr));
        }
        head_ = size_ = offset_ = 0;
    }

private:
    ReplySegment inline_[Inline];
    ReplySegment* segs_ = inline_;
    uint32_t head_ = 0;  // segment index at the wire frontier
    uint32_t size_ = 0;
    uint32_t cap_ = Inline;
    uint32_t offset_ = 0;  // byte offset within head_; only the head may be partial
};

// Owns receive storage, ROB chunks, output buffers/segments and its MultiSession; fd close and
// TLS-slot destruction belong to IoLoop. The IO owner mutates cursors; joined shutdown may
// drain/reclaim remaining clients after issuer cancellation. Dispatched workers
// hold pinned argv/direct-reply ranges and publish completion through Op::state. set_ifid_thread
// release-publishes an ownership change, paired with ifid_thread's acquire. ROB capacity and
// read_space enforce input back-pressure; safe_to_release also waits for IO, retire posts and WATCH
// references. Construction's malloc is unchecked; buffer-growth failure retains existing storage.
class Client {
public:
    explicit Client(int fd) : fd_(fd) {
        rbuf_ = static_cast<char*>(std::malloc(kRbufInitial));
        rcap_ = kRbufInitial;
    }
    ~Client() {
        multi_session_destroy(multi_session_);
        std::free(rbuf_);
    }
    Client(const Client&) = delete;
    Client& operator=(const Client&) = delete;

    int fd() const { return fd_; }
    int replace_fd(int replacement) {
        const int previous = fd_;
        fd_ = replacement;
        return previous;
    }

    // ---- read side -----------------------------------------------------------------------------
    char* rbuf() { return rbuf_; }
    uint32_t rlen() const { return rlen_; }
    uint32_t rpos() const { return rpos_; }
    size_t rcap() const { return rcap_; }
    void advance_parse(uint32_t n) {
        rpos_ += n;
        inline_scanned_ = 0;
    }
    uint32_t& inline_scanned() { return inline_scanned_; }
    bool multibulk_pending() const { return inline_scanned_ & kRespMultibulkPending; }
    RespFrontier& multibulk_frontier() { return multibulk_; }
    void suspend_multibulk() { inline_scanned_ = kRespMultibulkPending; }
    [[gnu::noinline, gnu::cold]] ParseResult resume_multibulk(uint32_t& pos, Op& op,
                                                              const char** err,
                                                              uint64_t max_multibulk,
                                                              uint64_t max_bulk) {
        const auto result =
            resp_resume(rbuf_, rlen_, pos, op, err, max_multibulk, max_bulk, multibulk_);
        if (result != ParseResult::Incomplete) {
            inline_scanned_ = 0;
            multibulk_.finish();
        }
        return result;
    }
    uint32_t query_buffer_pos() const {
        // Redis trims qb_pos after each input pass, including decoded headers
        // and completed arguments of an incomplete multibulk. Our argv slices
        // pin that prefix; account as if trimmed without moving any bytes.
        return rpos_ + (__builtin_expect(multibulk_pending(), false) ? multibulk_.next : 0);
    }
    bool query_buffer_exceeded(uint64_t limit, uint64_t queued = 0) const {
        // The retained frame is a conservative bound. Consult the saved parser
        // frontier only when that bound would close the connection.
        return queued > limit || (__builtin_expect(rlen_ - rpos_ > limit - queued, false) &&
                                  rlen_ - query_buffer_pos() > limit - queued);
    }

    // Space to recv() into. Returns nullptr to mean "do not read right now".
    //
    // GROWING IS ONLY LEGAL WHEN NOTHING IS IN FLIGHT, and that is the whole subtlety. realloc MOVES
    // the buffer, and every in-flight op's argv Slices point into it — so a grow while ops are
    // outstanding leaves workers reading freed memory. It presents as a key that hashed correctly at
    // parse time but reads as zeros in the handler, which looks like a store bug and is not one.
    // (Guarding only the memmove in reset_rbuf_at_quiescence is NOT enough; realloc moves it too.)
    //
    // So when we cannot grow, we return the free tail if it is big enough to be worth a recv, and
    // otherwise nothing at all — the ROB drains, quiescence arrives, the buffer resets, and reading
    // resumes. That is backpressure, not a stall.
    static constexpr size_t kMinRecv = 2048;

    // Offer writable tail bytes to the connection owner. may_grow requires ROB quiescence and
    // no outstanding kernel pointer into rbuf_; the caller enforces those fences. Query/inline
    // limits bound the offer, with one overflow-detection byte. A failed realloc retains storage;
    // insufficient tail returns nullptr/out_avail=0 for a later retry. No input is published here.
    template <bool kFrontier>
    [[gnu::always_inline]] char* read_space_impl(size_t want, size_t& out_avail, bool may_grow,
                                                 uint64_t query_limit, uint64_t queued) {
        size_t avail = rcap_ - rlen_;
        // Past the soft cap, growth continues ONLY while the entire buffer is one incomplete
        // command (rpos_ == 0 after the quiescence reset: nothing parsed, nothing in flight --
        // which is also what makes may_grow true). Backlog never grows past the soft cap.
        // Offer one byte beyond the limit to distinguish equality (legal) from overflow.
        // Parsed bytes still pinned by workers are not pending input. Queued MULTI argv is.
        const uint64_t remaining = queued < query_limit ? query_limit - queued : 0;
        size_t hard_cap = std::min<uint64_t>(
            kRbufHardCap, (kFrontier ? query_buffer_pos() : rpos_) + remaining + 1);
        // epoll/TLS drain reads before parsing. Stop them at the inline frontier so a
        // continuously readable peer cannot postpone the protocol error until the qbuf cap.
        if (rpos_ < rlen_ && rbuf_[rpos_] != '*')
            hard_cap = std::min<size_t>(hard_cap, uint64_t(rpos_) + kProtoInlineMaxSize + 1);
        const size_t cap = (rpos_ == 0) ? hard_cap : std::min(hard_cap, kRbufSoftCap);
        if (avail < want && may_grow && rcap_ < cap) {
            size_t ncap = rcap_ * 2;
            while (ncap < rlen_ + want && ncap < cap) ncap *= 2;
            if constexpr (kFrontier) {
                if (ncap > cap) ncap = cap;
            } else {
                // Reuse the growth-clamp comparison. Equality also needs a
                // refinement: the conservative cap may have stopped doubling.
                if (__builtin_expect(ncap >= cap, false))
                    return read_space_refined(want, out_avail, may_grow, query_limit, queued);
            }
            char* n = static_cast<char*>(std::realloc(rbuf_, ncap));
            if (n) {
                rbuf_ = n;
                rcap_ = ncap;
                avail = rcap_ - rlen_;
            }
        }
        if constexpr (kFrontier) {
            avail = std::min(avail, hard_cap > rlen_ ? hard_cap - rlen_ : 0);
        } else {
            // Reuse the receive-offer clamp comparison, before reading any
            // frontier state. Equality matters both for growth suppressed by
            // the conservative cap and for the final short-receive exception.
            if (__builtin_expect(hard_cap <= rcap_, false))
                return read_space_refined(want, out_avail, may_grow, query_limit, queued);
        }
        if (!avail || (avail < kMinRecv && rlen_ + avail != hard_cap)) {
            out_avail = 0;
            return nullptr;
        }
        out_avail = avail;
        return rbuf_ + rlen_;
    }
    [[gnu::noinline, gnu::cold]] char* read_space_refined(size_t want, size_t& out_avail,
                                                          bool may_grow, uint64_t query_limit,
                                                          uint64_t queued) {
        return read_space_impl<true>(want, out_avail, may_grow, query_limit, queued);
    }
    char* read_space(size_t want, size_t& out_avail, bool may_grow,
                     [[maybe_unused]] uint64_t proto_max_bulk_len = 512ull * 1024 * 1024,
                     uint64_t query_limit = 1024ull * 1024 * 1024, uint64_t queued = 0) {
        return read_space_impl<false>(want, out_avail, may_grow, query_limit, queued);
    }
    void commit_read(size_t n) { rlen_ += static_cast<uint32_t>(n); }
    uint32_t last_interaction_s() const { return last_interaction_s_; }
    void set_last_interaction_s(uint32_t value) { last_interaction_s_ = value; }

    // Exactly one recv may be outstanding, and while it is, the kernel holds a RAW POINTER into
    // this buffer. Nothing may move or reallocate it until that recv completes — see
    // reset_rbuf_at_quiescence().
    bool recv_armed() const { return recv_armed_; }
    void set_recv_armed(bool v) { recv_armed_ = v; }

    // Requires ROB quiescence and no kernel receive pointer into rbuf_. These are distinct fences:
    // the former releases argv slices, the latter prevents recv writing into moved/freed storage.
    // recv_armed denotes that pointer for plaintext/kTLS io_uring receives; epoll readiness and
    // userspace TLS BIO/poll state do not themselves pin rbuf_ (see client_buffer_cron).
    // Preserve the partial command and frame-relative frontier: saved argv contains offsets,
    // not Slices into the allocation moved here. The caller provides both fences.
    void reset_rbuf_at_quiescence() {
        const uint32_t rest = rlen_ - rpos_;
        if (rest && rpos_) std::memmove(rbuf_, rbuf_ + rpos_, rest);
        rlen_ = rest;
        rpos_ = 0;
    }

    // ---- the ROB -------------------------------------------------------------------------------
    Rob<kRobWindow>& rob() { return rob_; }
    const Rob<kRobWindow>& rob() const { return rob_; }

    // ---- write side: DOUBLE BUFFERED, and that is a correctness requirement ------------------
    //
    // A send in flight hands the kernel a raw pointer into the write buffer. Appending a reply to
    // that same buffer can grow it, and growing means malloc + memcpy + FREE OF THE OLD BLOCK — the
    // block the kernel is still reading from. It presents as occasional corrupted or missing replies
    // under pipelining only, because it needs a reply to land while a send is outstanding. Exactly
    // the same shape as the recv-buffer realloc bug, on the other side of the connection.
    //
    // So: replies always append to the FILL buffer, sends always read the SEND buffer, and the two
    // swap only at a point where no send is outstanding. Neither buffer is ever touched by both
    // sides at once, which makes the bug impossible rather than unlikely.
    SmallBuf<kWbufInline>& fill_buf() { return buf_[fill_]; }
    SmallBuf<kWbufInline>& send_buf() { return buf_[fill_ ^ 1]; }
    void append_fill(const char* ptr, size_t len) {
        fill_buf().append(ptr, len);
        if (obuf_tracking_) obuf_bytes_ += len;
    }
    void commit_fill(size_t len) {
        fill_buf().commit_raw(len);
        if (obuf_tracking_) obuf_bytes_ += len;
    }
    // Writable cursor at the fill frontier, published with commit_fill(). The coded-reply path
    // renders into this instead of formatting a temporary and memcpy-ing it in. Safe on exactly
    // the terms append_fill is: only the owner calls it, and a live Op::direct region can only
    // belong to the op at the head of this very drain (see the direct-reply note in io_loop).
    char* reserve_fill(size_t len) { return fill_buf().reserve(len); }

    bool has_pending_fill() const { return buf_[fill_].size() > 0; }
    uint64_t wsent() const { return wsent_; }
    void commit_write(size_t n) {
        wsent_ += n;
        if (obuf_tracking_) {
            if (n > obuf_bytes_) std::abort();
            obuf_bytes_ -= n;
        }
    }
    bool write_drained() const { return wsent_ >= buf_[fill_ ^ 1].size(); }

    // Promote the fill buffer to be the send buffer. Only legal when no send is outstanding, which
    // is the caller's invariant (send_inflight()).
    void swap_buffers() {
        buf_[fill_ ^ 1].clear();  // old send buffer is fully written; recycle it as the next fill
        fill_ ^= 1;
        wsent_ = 0;
    }
    bool nothing_to_write() const {
        return buf_[fill_].size() == 0 && write_drained() && segments_.empty();
    }
    uint64_t buffered_output_bytes() const {
        const size_t send_size = buf_[fill_ ^ 1].size();
        const uint64_t send_remaining = send_size > wsent_ ? send_size - wsent_ : 0;
        return buf_[fill_].size() + send_remaining + segments_.byte_size();
    }
    uint32_t output_list_length() const { return segments_.size(); }

    // Seal ordinary staged bytes before the first borrowed reply. Clearing the fill buffer after
    // copying leaves the existing send buffer untouched, so an older send already in flight stays
    // ahead of every new segment.
    void seal_fill_segment() {
        SmallBuf<kWbufInline>& b = fill_buf();
        if (!b.empty()) {
            segments_.append_buf(b.data(), b.size());
            b.clear();
        }
    }
    void append_buf_segment(const char* ptr, size_t len) {
        segments_.append_buf(ptr, len);
        if (obuf_tracking_) obuf_bytes_ += len;
    }
    void append_buf_segment(const char* a, size_t an, const char* b, size_t bn) {
        segments_.append_buf(a, an, b, bn);
        if (obuf_tracking_) obuf_bytes_ += an + bn;
    }
    void append_borrow_segment(const char* ptr, uint32_t len, int32_t shard) {
        segments_.append_borrow(ptr, len, shard);
        if (obuf_tracking_) obuf_bytes_ += len;
    }
    void append_static_segment(const char* ptr, uint32_t len) {
        segments_.append_static(ptr, len);
        if (obuf_tracking_) obuf_bytes_ += len;
    }
    bool has_pending_segments() const { return !segments_.empty(); }

    // ---- OUT-OF-BAND FRAMES ---------------------------------------------------------------
    // Pub/sub deliveries, tracking invalidations and MONITOR feed lines are WHOLE frames produced
    // by something other than this connection's op stream. Two rules govern where they may land:
    //
    // 1. Do not append a frame to a live Op's reply. For a copying reply op.reply is its tail,
    //    but for a borrowed reply it is its head: serve emits [direct+reply][borrow][CRLF], and
    //    a borrowed GET's sink contains just $<len>\r\n. Appending there places the push between
    //    header and payload, desynchronizing plaintext or TLS by the push length. It also races
    //    a worker appending to the same SmallBuf, whose grow frees the block being written.
    //
    // 2. NEVER OVER A LIVE DIRECT-REPLY REGION. `Op::direct` is a raw pointer into fill_buf()'s
    //    SPARE CAPACITY, handed out only when the ROB is idle and the fill buffer is empty. An
    //    append_fill while it is live overwrites the bytes a worker is formatting, can grow (free)
    //    the block underneath it, and leaves retire's commit_fill publishing the wrong offset.
    //
    // Both are satisfied by one test at the point the send engine releases a frame: while younger
    // ops are still in flight, route through the SEGMENT queue, which owns its own block and never
    // touches fill_buf. seal_fill_segment() first, because pump drains the whole segment queue
    // strictly BEFORE it promotes the fill buffer -- so older staged bytes must move into the
    // queue's tail or the frame would jump ahead of them. A quiesced connection with an empty queue
    // (the idle subscriber, which is the hot pub/sub case) uses a plain fill append.
    //
    // The op stream and this channel then interleave only at frame boundaries: retire stages each
    // op's bytes in one uninterrupted run, and a frame appended here sits entirely before the next
    // one. WbEngine::defer_oob parks a newly produced frame until every earlier-issued reply has
    // been staged; a parked blocking command is the deliberate latency-bounded exception.
    // Returns TRUE when this append had to take the segment channel. The callers count only direct
    // production-time appends here; frames parked by WbEngine have their own disjoint counter.
    bool append_oob(const char* a, size_t an, const char* b = nullptr, size_t bn = 0) {
        if (segments_.empty() && rob_.quiesced()) {
            append_fill(a, an);
            if (bn) append_fill(b, bn);
            return false;
        }
        seal_fill_segment();
        append_buf_segment(a, an, b, bn);
        return true;
    }
    uint32_t build_segment_iov(bool& has_borrow, uint32_t& bytes) {
        const uint32_t n =
            segments_.build_iov(send_iov_, kMaxSendIov, kMaxSendBytes, has_borrow, bytes);
        std::memset(&send_msg_, 0, sizeof(send_msg_));
        send_msg_.msg_iov = send_iov_;
        send_msg_.msg_iovlen = n;
        return n;
    }
    msghdr* send_msg() { return &send_msg_; }
    template <typename ReleaseFn>
    uint64_t consume_segments(uint32_t bytes, ReleaseFn&& release) {
        const uint64_t borrowed = segments_.consume(bytes, std::forward<ReleaseFn>(release));
        if (obuf_tracking_) {
            if (bytes > obuf_bytes_) std::abort();
            obuf_bytes_ -= bytes;
        }
        return borrowed;
    }
    template <typename ReleaseFn>
    void release_all_segments(ReleaseFn&& release) {
        segments_.release_all(std::forward<ReleaseFn>(release));
        obuf_bytes_ = 0;
    }
    // Take back segments a retire hook staged for an op whose reply is being suppressed. See
    // SegmentQueue::truncate for why only just-appended segments may ever be removed.
    template <typename ReleaseFn>
    void truncate_segments(uint32_t keep, ReleaseFn&& release) {
        const uint64_t bytes = segments_.truncate(keep, std::forward<ReleaseFn>(release));
        if (obuf_tracking_) {
            if (bytes > obuf_bytes_) std::abort();
            obuf_bytes_ -= bytes;
        }
    }

    uint64_t obuf_bytes() const { return obuf_bytes_; }
    void start_obuf_tracking() {
        if (obuf_tracking_) return;
        obuf_bytes_ = fill_buf().size() + (send_buf().size() - wsent_) + segments_.byte_size();
        obuf_tracking_ = true;
    }
    void stop_obuf_tracking() {
        if (!obuf_tracking_) return;
        obuf_tracking_ = false;
        obuf_bytes_ = 0;
        obuf_soft_since_s_ = 0;
    }
    uint32_t obuf_soft_since_s() const { return obuf_soft_since_s_; }
    void set_obuf_soft_since_s(uint32_t value) { obuf_soft_since_s_ = value; }

    // Exactly ONE send may be outstanding per connection. Two concurrent sends on one socket can
    // complete out of order and interleave bytes, which corrupts the stream in a way that looks
    // like a protocol bug anywhere but here.
    bool send_inflight() const { return send_inflight_; }
    void set_send_inflight(bool v) { send_inflight_ = v; }
    bool segmented_send() const { return segmented_send_; }
    void set_segmented_send(bool v) { segmented_send_ = v; }
    uint32_t send_requested() const { return send_requested_; }
    void set_send_requested(uint32_t n) { send_requested_ = n; }

    // ---- io-thread bookkeeping -----------------------------------------------------------------
    uint64_t id() const { return id_; }
    void set_id(uint64_t v) { id_ = v; }
    // This release/acquire store is the connection ownership edge. Registration and queue
    // membership follow it; neither is allowed to stand in for it.
    uint32_t ifid_thread() const { return ifid_thread_.load(std::memory_order_acquire); }
    // The same Client (including the offset frontier) crosses this ownership
    // edge. Resetting a live frontier here would replay its completed arguments.
    // FLIP, client-LB, R7 adoption and rollback all use this edge; none replaces
    // the unconsumed frame. No IO-local pointer is retained by the parser.
    void set_ifid_thread(uint32_t t) { ifid_thread_.store(t, std::memory_order_release); }
    Session& session() { return session_; }
    const Session& session() const { return session_; }

    // Torn down but not yet freed: still legal to READ while outstanding CQEs retire (it sits on
    // the io thread's deferred-free list), but no longer part of any working set.
    bool dead() const { return dead_; }
    void mark_dead() {
        dead_ = true;
        inline_scanned_ = 0;
        multibulk_.finish();
    }
    bool closing() const { return closing_; }
    void mark_closing() {
        closing_ = true;
        inline_scanned_ = 0;
        multibulk_.finish();
    }

    // Membership in its io thread's active set, as a FLAG rather than a search; and whether this
    // conn's ready bit fired since io last served it. Plain bools — one thread.
    // IO-owned across the pending-serve FIFO lifetime, including tail rotations.
    uint8_t& wb_deferrals() { return wb_deferrals_; }
    static constexpr size_t wb_deferrals_offset();
    static constexpr size_t wb_rob_offset();
    bool serve_pending() const { return serve_pending_; }
    void set_serve_pending(bool v) { serve_pending_ = v; }
    // An in-flight all-shards scatter (FLUSHALL/FLUSHDB/CONFIG SET fan-out) is a parse barrier:
    // commands behind it on this conn must observe post-scatter state (ConnLocal readers like
    // DBSIZE/INFO execute at parse time, so without the barrier they snapshot early and a
    // pipelined FLUSHALL;DBSIZE answers the pre-flush count). Set only on successful publish;
    // cleared at ROB quiescence — the scatter is necessarily the newest op, since nothing parses
    // behind it. Same-client read-your-own-writes hazard: a sanctioned stall.
    //
    // The parse loop tests the one-byte owner mask against zero; see BarrierOwner.
    bool scatter_barrier() const { return barrier_owners_ != 0; }
    bool barrier_held_by(BarrierOwner who) const {
        return (barrier_owners_ & static_cast<uint8_t>(who)) != 0;
    }
    void barrier_acquire(BarrierOwner who) {
        barrier_owners_ = static_cast<uint8_t>(barrier_owners_ | static_cast<uint8_t>(who));
    }
    // Drops one owner's claim. Returns TRUE when this release was the last one — i.e. when the
    // connection is actually released. False means another owner still holds the barrier;
    // callers count that overlap so tests can witness a release that must keep parsing parked.
    bool barrier_release(BarrierOwner who) {
        barrier_owners_ = static_cast<uint8_t>(barrier_owners_ & ~static_cast<uint8_t>(who));
        return barrier_owners_ == 0;
    }
    // The backstop, at ROB quiescence: with nothing in flight every PRODUCTION owner has completed
    // by definition, so quiescence releases them all in one store. Only the injected test owner is
    // exempt, and only because holding past quiescence is the whole point of it.
    void barrier_release_quiesced() {
        barrier_owners_ =
            static_cast<uint8_t>(barrier_owners_ & static_cast<uint8_t>(BarrierOwner::Debug));
    }
    // Parse backpressure is deliberately distinct from the semantic scatter barrier. Each owner
    // parks this connection's unconsumed head frame without publishing a ROB slot, and clears only
    // its own reason. The byte is a mask because atomic admission and FLIP can overlap.
    bool parse_backpressure() const { return parse_backpressure_ != 0; }
    bool atomic_backpressure() const { return parse_backpressure_ & kAtomicBackpressure; }
    void set_atomic_backpressure(bool v) {
        if (v)
            parse_backpressure_ |= kAtomicBackpressure;
        else
            parse_backpressure_ &= static_cast<uint8_t>(~kAtomicBackpressure);
    }
    bool flip_backpressure() const { return parse_backpressure_ & kFlipBackpressure; }
    void set_flip_backpressure(bool v) {
        if (v)
            parse_backpressure_ |= kFlipBackpressure;
        else
            parse_backpressure_ &= static_cast<uint8_t>(~kFlipBackpressure);
    }
    bool subscriber_mode() const { return subscriber_mode_; }
    void set_subscriber_mode(bool v) { subscriber_mode_ = v; }
    bool blocked() const { return connection_flags_ & kBlocked; }
    void set_blocked(bool value) {
        if (value)
            connection_flags_ |= kBlocked;
        else
            connection_flags_ &= static_cast<uint8_t>(~kBlocked);
    }
    bool resp3() const { return connection_flags_ & kResp3; }
    void set_resp3(bool value) {
        if (value)
            connection_flags_ |= kResp3;
        else
            connection_flags_ &= static_cast<uint8_t>(~kResp3);
    }
    // CLIENT NO-TOUCH uses bit 4 of the connection byte passed through op_route_flags(). Op's
    // routing-bit assignments leave that bit available, keeping the footprint and flag load shared.
    bool no_touch() const { return connection_flags_ & kNoTouch; }
    void set_no_touch(bool value) {
        if (value)
            connection_flags_ |= kNoTouch;
        else
            connection_flags_ &= static_cast<uint8_t>(~kNoTouch);
    }
    // Bit 2 deliberately matches Op::route_flags_'s Resp3 assignment. Passing the byte through
    // Op::reset folds protocol capture into the ROB's flags store: RESP2 pays one load,
    // no mask and no branch. The armed coarse parser masks kBlocked before reusing its bit for a
    // hash-precise write stamp; ordinary acquisitions continue to ignore that high bit.
    uint8_t op_route_flags() const { return connection_flags_; }
    static constexpr size_t connection_flags_offset();
    // The IO owner captures the atomic-group status into Op before dispatch. Executor admission
    // uses that snapshot, keeping per-operation Client atomic bookkeeping off its shared tail line.
    bool has_atomic_group_io() const { return atomic_groups_io_ != 0; }
    void atomic_group_started() { ++atomic_groups_io_; }
    void atomic_group_finished() {
        if (!atomic_groups_io_) std::abort();
        --atomic_groups_io_;
    }
    bool in_active() const { return in_active_; }
    void set_in_active(bool v) { in_active_ = v; }
    // MULTI/WATCH state is allocated on first use. Its handle and WATCH atomics fit inside the
    // executor-facing tail of the 1984-byte Client; multi_session_destroy owns final cleanup.
    MultiSession* multi_session() const { return multi_session_; }
    void set_multi_session(MultiSession* state) { multi_session_ = state; }
    uint64_t watch_generation() const { return watch_generation_.load(std::memory_order_acquire); }
    uint64_t next_watch_generation() {
        return watch_generation_.fetch_add(1, std::memory_order_acq_rel) + 1;
    }
    bool watch_dirty() const { return watch_dirty_.load(std::memory_order_acquire); }
    void set_watch_dirty() { watch_dirty_.store(true, std::memory_order_release); }
    void clear_watch_dirty() { watch_dirty_.store(false, std::memory_order_release); }
    bool authenticated() const { return authenticated_; }
    void set_authenticated(bool value) { authenticated_ = value; }
    uint32_t acl_user_idx() const { return acl_user_idx_; }
    void set_acl_user_idx(uint32_t value) { acl_user_idx_ = value; }
    static constexpr size_t acl_user_idx_offset();
    void watch_ref() { watched_refs_.fetch_add(1, std::memory_order_relaxed); }
    void watch_unref() {
        if (watched_refs_.fetch_sub(1, std::memory_order_acq_rel) == 0) std::abort();
    }
    // ---- cross-thread lifetime fences ---------------------------------------------------------
    // Release requires ROB quiescence, no outstanding recv/send, no claimed retire-channel post,
    // and no WATCH references. A worker may post Client* before IO retires it through flush_ready;
    // quiescence alone cannot make that queued pointer disappear. retire_queued_ is claimed before
    // posting and cleared when the consumer takes the entry. After the final completion there is
    // no new completion claim, so checking the claim with acquire closes that lifetime window.
    bool safe_to_release() {
        return rob_.quiesced() && !recv_armed_ &&
               !send_inflight_ &&  // the KERNEL holds no pointer into us
               !retire_queued_.load(std::memory_order_acquire) &&
               watched_refs_.load(std::memory_order_acquire) == 0;
    }
    bool migration_protocol_idle() const {
        // Ordinary unread input and admission/FLIP backpressure move with the Client.
        return rob_.quiesced() && !send_inflight_ && !serve_pending_ &&
               !retire_queued_.load(std::memory_order_acquire) &&
               watched_refs_.load(std::memory_order_acquire) == 0 && barrier_owners_ == 0 &&
               atomic_groups_io_ == 0 && !blocked() && multi_session_ == nullptr &&
               nothing_to_write();
    }
    // FLIP alone may carry durable session/WATCH state after the global drains.
    // Definitions live beside MultiSession; LB uses its separate, stricter migration predicate.
    bool flip_migration_protocol_idle() const;
    bool flip_session_pending() const;
    bool flip_execution_idle() const;
    bool flip_stationary_idle() const;
    bool flip_borrowed_output() const;
    bool flip_held_output_idle() const;
    bool flip_drain_idle() const {
        // Global dispatch is paused, but connections which remain on this IO may retain durable
        // owner-local modes (subscriptions, WATCH/MULTI session metadata, tracking). Only work
        // which can still touch an executor, ROB pointer, output borrow, or barrier must drain.
        return rob_.quiesced() && !send_inflight_ && !serve_pending_ &&
               !retire_queued_.load(std::memory_order_acquire) && barrier_owners_ == 0 &&
               atomic_groups_io_ == 0 && !blocked() && nothing_to_write();
    }

    // Set by a worker before it tells the owning IO thread this client has ops to retire; cleared by
    // that IO thread when it picks the client up. Without it, a pipelined burst of N completions
    // enqueues the same client N times and the retire channel fills with duplicates.
    std::atomic<bool>& retire_queued() { return retire_queued_; }

    // The io thread's ready-mask slot for this connection. Written by io (assign at accept,
    // kNoWbSlot at close), read by every worker deciding how to signal completion. A stale read
    // falls back to the channel path, which is always correct -- so relaxed is enough.
    static constexpr uint32_t kNoWbSlot = UINT32_MAX;
    static constexpr uint32_t kWbMigrationInstalling = UINT32_MAX - 1;
    uint32_t wb_slot() const { return wb_slot_.load(std::memory_order_relaxed); }
    void set_wb_slot(uint32_t s) { wb_slot_.store(s, std::memory_order_release); }

    // The IO owner's out-of-line TLS state is named by a four-byte slot at offset 1980.
    // Offset 12 belongs to last_interaction_s_; the static_asserts lock these layout assignments.
    static constexpr uint32_t kNoTlsSlot = UINT32_MAX;
    bool is_tls() const { return tls_slot_ != kNoTlsSlot; }
    uint32_t tls_slot() const { return tls_slot_; }
    void set_tls_slot(uint32_t slot) { tls_slot_ = slot; }
    static constexpr size_t tls_slot_offset();
    // Layout probes for the coherence lock below the class (see the static_asserts there).
    static constexpr size_t executor_line_offset();
    static constexpr size_t wb_slot_offset();
    static constexpr size_t ifid_thread_offset();
    static constexpr size_t id_offset();
    static constexpr size_t obuf_bytes_offset();
    static constexpr size_t atomic_groups_io_offset();
    static constexpr size_t inline_scanned_offset();

private:
    friend class IdleBuffers;
    // --- io-hot scalars, packed: touched together on every pass ---------------------------------
    friend class r7::ShadowLongIndex;
    int fd_ = -1;
    uint32_t rlen_ = 0;                // bytes received
    uint32_t rpos_ = 0;                // bytes parsed
    uint32_t last_interaction_s_ = 0;  // monotonic whole seconds; occupies the rbuf_ alignment hole
    char* rbuf_ = nullptr;
    size_t rcap_ = 0;
    // wsent_ accumulates across resubmits of one send buffer. Output limits may allow more than
    // 4 GiB of queued replies, so it is 64-bit: wrapping would make write_drained false and resend
    // an earlier offset. fill_ is a one-byte 0/1 index; offsets 32..47 hold the cursors/flags without
    // widening the IO-hot line. Individual sends still obey kMaxSendBytes.
    uint64_t wsent_ = 0;  // bytes of the SEND buffer already written
    uint8_t fill_ = 0;    // index of the buffer replies append to
    bool recv_armed_ = false;
    bool send_inflight_ = false;
    bool segmented_send_ = false;
    uint32_t send_requested_ = 0;
    bool serve_pending_ = false;
    bool in_active_ = false;
    bool closing_ = false;
    bool dead_ = false;
    // One-byte BarrierOwner mask in the packed 48..55 flag run. connection_flags_ is locked at
    // offset 55; widening this mask can displace it and grow the aligned Client. The seven
    // production claims and the debug hold use all eight bits.
    uint8_t barrier_owners_ = 0;
    static constexpr uint8_t kAtomicBackpressure = 1u << 0;
    static constexpr uint8_t kFlipBackpressure = 1u << 1;
    uint8_t parse_backpressure_ = 0;
    bool subscriber_mode_ = false;  // IO-owned; inside the packed flag run
    // Blocked, RESP3 and NO-TOUCH share one byte in the full 48..55 flag run. Keeping them
    // together preserves the placement of following fields in the 64-byte-aligned Client.
    static constexpr uint8_t kBlocked = 1u << 7;
    static constexpr uint8_t kResp3 = 1u << 2;
    static constexpr uint8_t kNoTouch = 1u << 4;
    uint8_t connection_flags_ = 0;
    // Output accounting is rewritten on every reply append while a client output limit is armed.
    // It sits here, on the io-private hot line, so that write never invalidates the executor-
    // facing completion-routing line containing wb_slot_.
    uint64_t obuf_bytes_ = 0;  // 56..63: fill + unsent send + segment bytes

    // --- io-owner bookkeeping (line 1: parser/session state and dispatch/retire counters) -------
    // The per-connection atomic-group count moves at dispatch and retire of every atomic
    // multi-key command, io-side only. Same rule as obuf_bytes_: io's per-op writes stay off the
    // line executors read on every completion.
    uint32_t atomic_groups_io_ = 0;  // 64..67
    Session session_;                // 68..71
    uint8_t wb_deferrals_ = 0;       // 72: IO-only padding before ROB
    uint32_t inline_scanned_ = 0;    // 76..79: cursor relative to rpos_; IO-only padding
    // R7-only IO state in the 80..127 alignment area. Deliberately
    // uninitialized here: the armed parser initializes at dispatch_id == 0.
    // These words have no initialization store on ordinary Client construction.
    uint64_t r7_long_slots_;
    uint64_t r7_long_newest_;
    RespFrontier multibulk_;  // 96..127: IO-only alignment hole

    // --- the ROB (manages its own cross-thread layout) ------------------------------------------
    Rob<kRobWindow> rob_;

    // --- write buffers (ex writes the direct-reply DATA region inside; header fields io-only) ---
    SmallBuf<kWbufInline> buf_[2];

    // sendmsg reads both the iovec array and msghdr asynchronously, so both live with the Client.
    static constexpr uint32_t kMaxSendIov = 16;
    SegmentQueue<8> segments_;
    iovec send_iov_[kMaxSendIov] = {};
    msghdr send_msg_ = {};

    // --- executor-facing completion routing and cold shared state ------------------------------
    // notify_sender reads ifid_thread_ and wb_slot_ to route completions; id_ identifies clients
    // for cross-shard work. Co-locate those fields on one shared line. WATCH/reference atomics and
    // retire_queued_ can also change here; output append and atomic-group counters instead occupy
    // IO-private lines above. The static_asserts pin the separation of those per-op IO writes.
    alignas(64) std::atomic<bool> retire_queued_{false};  // 1920
    std::atomic<uint32_t> wb_slot_{kNoWbSlot};            // 1924
    std::atomic<uint32_t> ifid_thread_{0};                // 1928
    MultiSession* multi_session_ = nullptr;               // 1936
    std::atomic<uint64_t> watch_generation_{0};           // 1944
    std::atomic<uint32_t> watched_refs_{0};               // 1952
    std::atomic<bool> watch_dirty_{false};                // 1956
    uint64_t id_ = 0;                                     // 1960
    uint32_t obuf_soft_since_s_ = 0;  // 1968: cron-written only; 0 = not continuously over soft
    bool obuf_tracking_ = false;      // 1972: flips once per arm/disarm, never per append
    bool authenticated_ = false;      // 1973: requirepass state
    uint32_t acl_user_idx_ = 0;       // 1976: ACL user handle
    uint32_t tls_slot_ = kNoTlsSlot;  // 1980: out-of-line TlsConn handle
};

constexpr size_t Client::wb_deferrals_offset() { return offsetof(Client, wb_deferrals_); }
constexpr size_t Client::wb_rob_offset() { return offsetof(Client, rob_); }
static_assert(Client::wb_deferrals_offset() == 72);
static_assert(Client::wb_rob_offset() == 128);
static_assert(Client::wb_deferrals_offset() / 64 == 1);
constexpr size_t Client::acl_user_idx_offset() { return offsetof(Client, acl_user_idx_); }
static_assert(Client::acl_user_idx_offset() + sizeof(uint32_t) <= sizeof(Client));
constexpr size_t Client::connection_flags_offset() { return offsetof(Client, connection_flags_); }
static_assert(Client::connection_flags_offset() == 55,
              "connection flags moved: re-run the declaration-order Client mirror probe");
constexpr size_t Client::tls_slot_offset() { return offsetof(Client, tls_slot_); }
static_assert(Client::tls_slot_offset() == 1980,
              "TLS slot moved: re-run the declaration-order Client mirror probe");

// Completion-routing fields ifid_thread_, wb_slot_ and id_ share one 64-byte line. Per-append
// obuf_bytes_ and per-atomic-command atomic_groups_io_ occupy IO-private lines so those writes
// do not invalidate the routing line that executors read. The assertions lock both placements.
constexpr size_t Client::executor_line_offset() { return offsetof(Client, retire_queued_); }
constexpr size_t Client::wb_slot_offset() { return offsetof(Client, wb_slot_); }
constexpr size_t Client::ifid_thread_offset() { return offsetof(Client, ifid_thread_); }
constexpr size_t Client::id_offset() { return offsetof(Client, id_); }
constexpr size_t Client::obuf_bytes_offset() { return offsetof(Client, obuf_bytes_); }
constexpr size_t Client::atomic_groups_io_offset() { return offsetof(Client, atomic_groups_io_); }
constexpr size_t Client::inline_scanned_offset() { return offsetof(Client, inline_scanned_); }
static_assert(Client::inline_scanned_offset() == 76, "Inline cursor must consume IO-only padding");
static_assert(Client::executor_line_offset() % 64 == 0, "executor-facing line must start a line");
static_assert(Client::wb_slot_offset() / 64 == Client::executor_line_offset() / 64,
              "wb_slot_ left the executor-facing line");
static_assert(Client::ifid_thread_offset() / 64 == Client::executor_line_offset() / 64,
              "ifid_thread_ left the executor-facing line");
static_assert(Client::id_offset() / 64 == Client::executor_line_offset() / 64,
              "id_ left the executor-facing line");
static_assert(Client::obuf_bytes_offset() / 64 == 0,
              "obuf_bytes_ is written per append: it belongs on the io-hot line");
static_assert(Client::atomic_groups_io_offset() / 64 == 1,
              "atomic_groups_io_ is written per atomic op: it belongs on io-only line 1");

// Client is resident per connection and its IO-hot head is layout-sensitive. The 1984-byte lock
// includes persistent zero-copy send state (segment queue, iovec window, msghdr) required across
// send CQEs; layout changes require a separate review of cache placement and idle memory.
static_assert(sizeof(Client) == 1984, "Client grew: re-check the io-hot line packing and idle RSS");

}  // namespace tomo
