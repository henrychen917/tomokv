// conn.h — Client: one connection, one struct, one owner.
//
// UNIFIED (owner order, 2026-08-24, after the pure-2s ruling). The ConnIn/ConnOut split — with an
// alignas(64) firewall between the halves — existed so the parsing thread (ifid) and a remote
// sending thread (wb/exwb) could not false-share. In pure 2s ONE io thread owns both halves for
// the connection's whole life, so the split bought padding and a pointer hop for a hazard that no
// longer exists. The layout rule inverts: pack the io thread's recv+send scalars TIGHT (they are
// touched together every pass), and give the only genuinely cross-thread fields — the two atomics
// the EXECUTOR signals through — their own line at the tail.
//
// What ex touches, and nothing else: ROB slots (Op state/reply/direct region — Rob manages its own
// cross-thread layout), the bytes of rbuf via argv Slices (heap data, not this struct), the direct-
// reply region inside buf_[] (data bytes, published by the op's Done), and the two atomics at the
// tail (retire_queued_, wb_slot_). Every scalar above them is single-writer io state.
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
#include "rob.h"
#include "../base/slice.h"

#ifdef TOMO_WEDGE_FORENSICS
#define TOMO_FORENSIC(x) do { x; } while (0)
#else
#define TOMO_FORENSIC(x) do { } while (0)
#endif

namespace tomo {

inline constexpr uint32_t kRobWindow    = 64;          // max in-flight ops per connection
inline constexpr size_t   kRbufInitial  = 16 * 1024;
inline constexpr size_t   kRbufSoftCap  = 1 * 1024 * 1024;  // stop BUFFERING BACKLOG past this
// The parser accepts redis-compatible bulks (512MB). A single command must therefore be allowed to
// exceed the soft cap, or a 2MB SET stalls its connection forever: the parser reports Incomplete,
// read_space refuses to grow, and neither side can ever make progress -- a silent wedge with no
// error, found by the perfected-checkpoint audit. The soft cap bounds BACKLOG (many buffered
// commands); one oversized in-flight command may grow to the protocol bound. Memory tracks bytes
// actually received, and reset_rbuf_at_quiescence sheds the growth after the command completes.
inline constexpr size_t   kRbufHardCap  = 512ull * 1024 * 1024 + 64 * 1024;  // parser bound + slack
// Item 4: 512B inline, heap beyond. Two 16KB inline buffers made every connection carry 32KB of
// worst-case staging whether it ever pipelined or not; SmallBuf grows on demand and clear() keeps
// the allocation, so a busy connection pays ONE grow to its working size and idles at 1KB + that.
inline constexpr size_t   kWbufInline   = 512;

// Item 6: connection-lived execution-side state -- the third lifetime. Session-mutating commands
// are ConnLocal and run on the io thread, single-threaded per connection; handlers never see it,
// they see the snapshot the parser stamps into each op.
struct Session {
    uint32_t db_index = 0;
};

class Client {
public:
    explicit Client(int fd) : fd_(fd) {
        rbuf_ = static_cast<char*>(std::malloc(kRbufInitial));
        rcap_ = kRbufInitial;
    }
    ~Client() { std::free(rbuf_); }
    Client(const Client&) = delete;
    Client& operator=(const Client&) = delete;

    int  fd() const { return fd_; }

    // ---- read side -----------------------------------------------------------------------------
    char*    rbuf()      { return rbuf_; }
    uint32_t rlen() const { return rlen_; }
    uint32_t rpos() const { return rpos_; }
    void     advance_parse(uint32_t n) { rpos_ += n; }

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

    char* read_space(size_t want, size_t& out_avail, bool may_grow) {
        size_t avail = rcap_ - rlen_;
        // Past the soft cap, growth continues ONLY while the entire buffer is one incomplete
        // command (rpos_ == 0 after the quiescence reset: nothing parsed, nothing in flight --
        // which is also what makes may_grow true). Backlog never grows past the soft cap.
        const size_t cap = (rpos_ == 0) ? kRbufHardCap : kRbufSoftCap;
        if (avail < want && may_grow && rcap_ < cap) {
            size_t ncap = rcap_ * 2;
            while (ncap < rlen_ + want && ncap < cap) ncap *= 2;
            if (ncap > cap) ncap = cap;
            char* n = static_cast<char*>(std::realloc(rbuf_, ncap));
            if (n) { rbuf_ = n; rcap_ = ncap; avail = rcap_ - rlen_; }
        }
        if (avail < kMinRecv) { out_avail = 0; return nullptr; }
        out_avail = avail;
        return rbuf_ + rlen_;
    }
    void commit_read(size_t n) { rlen_ += static_cast<uint32_t>(n); }

    // Exactly one recv may be outstanding, and while it is, the kernel holds a RAW POINTER into
    // this buffer. Nothing may move or reallocate it until that recv completes — see
    // reset_rbuf_at_quiescence().
    bool recv_armed() const { return recv_armed_; }
    void set_recv_armed(bool v) { recv_armed_ = v; }

    // Safe ONLY when the ROB is quiescent AND no recv is in flight. Both conditions matter and they
    // are different: quiescence means no Slice into this buffer is still referenced by an op, while
    // !recv_armed means the KERNEL is not holding a pointer into it. Violating the second corrupts
    // the heap — the recv lands at a stale offset, or into freed memory if the realloc below runs.
    // Preserves any partially received command at the tail, which has no Slices pointing at it yet.
    void reset_rbuf_at_quiescence() {
        const uint32_t rest = rlen_ - rpos_;
        if (rest && rpos_) std::memmove(rbuf_, rbuf_ + rpos_, rest);
        rlen_ = rest;
        rpos_ = 0;
        // Shed an oversized command's growth -- but ONLY once the buffer is EMPTY. Shrinking with
        // rest > 0 truncates the allocation underneath rlen_, and the next recv lands past the end
        // of a 16KB block. That exact bug shipped for ~20 minutes: the hard-cap growth fix armed
        // this previously-unreachable branch, and a 2MB SET died with EFAULT mid-stream.
        if (rlen_ == 0 && rcap_ > kRbufSoftCap) {
            char* n = static_cast<char*>(std::realloc(rbuf_, kRbufInitial));
            if (n) { rbuf_ = n; rcap_ = kRbufInitial; }
        }
    }

    // ---- the ROB -------------------------------------------------------------------------------
    Rob<kRobWindow>& rob() { return rob_; }

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

    bool     has_pending_fill() const { return buf_[fill_].size() > 0; }
    uint32_t wsent() const { return wsent_; }
    void     commit_write(uint32_t n) { wsent_ += n; }
    bool     write_drained() const { return wsent_ >= buf_[fill_ ^ 1].size(); }

    // Promote the fill buffer to be the send buffer. Only legal when no send is outstanding, which
    // is the caller's invariant (send_inflight()).
    void swap_buffers() {
        buf_[fill_ ^ 1].clear();      // old send buffer is fully written; recycle it as the next fill
        fill_ ^= 1;
        wsent_ = 0;
    }
    bool nothing_to_write() const { return buf_[fill_].size() == 0 && write_drained(); }

    // Exactly ONE send may be outstanding per connection. Two concurrent sends on one socket can
    // complete out of order and interleave bytes, which corrupts the stream in a way that looks
    // like a protocol bug anywhere but here.
    bool send_inflight() const { return send_inflight_; }
    void set_send_inflight(bool v) { send_inflight_ = v; }

    // ---- io-thread bookkeeping -----------------------------------------------------------------
    uint64_t id() const { return id_; }
    void set_id(uint64_t v) { id_ = v; }
    uint32_t ifid_thread() const { return ifid_thread_; }
    void set_ifid_thread(uint32_t t) { ifid_thread_ = t; }
    Session& session() { return session_; }

    // Torn down but not yet freed: still legal to READ (it sits on the io thread's deferred-free
    // list for one loop iteration), but no longer part of any working set.
    bool dead() const { return dead_; }
    void mark_dead() { dead_ = true; }
    bool closing() const { return closing_; }
    void mark_closing() { closing_ = true; }

    // Membership in its io thread's active set, as a FLAG rather than a search; and whether this
    // conn's ready bit fired since io last served it. Plain bools — one thread.
    bool serve_pending() const { return serve_pending_; }
    void set_serve_pending(bool v) { serve_pending_ = v; }
    bool in_active() const { return in_active_; }
    void set_in_active(bool v) { in_active_ = v; }

    // ---- the ONLY cross-thread fields ----------------------------------------------------------
    // A connection may be freed only when (a) nothing is in flight through its ROB AND (b) no
    // Client* naming it can still surface from a notification channel. (b) is what the ASAN
    // use-after-free proved: a worker posts the client for retirement, io serves it through
    // flush_ready instead, the ROB quiesces, the peer disconnects, close frees the client -- and
    // io then drains its channel into freed memory. The claim flag covers every CLAIMED post: it is
    // set before posting and cleared only when the consumer takes the entry, and after quiescence
    // no new claim can ever be made (no op will complete again), so requiring it false here is
    // race-free.
    bool safe_to_release() {
        return rob_.quiesced() &&
               !retire_queued_.load(std::memory_order_acquire);
    }

    // Set by a worker before it tells the owning IO thread this client has ops to retire; cleared by
    // that IO thread when it picks the client up. Without it, a pipelined burst of N completions
    // enqueues the same client N times and the retire channel fills with duplicates.
    std::atomic<bool>& retire_queued() { return retire_queued_; }

    // The io thread's ready-mask slot for this connection. Written by io (assign at accept,
    // kNoWbSlot at close), read by every worker deciding how to signal completion. A stale read
    // falls back to the channel path, which is always correct -- so relaxed is enough.
    static constexpr uint32_t kNoWbSlot = UINT32_MAX;
    uint32_t wb_slot() const { return wb_slot_.load(std::memory_order_relaxed); }
    void set_wb_slot(uint32_t s) { wb_slot_.store(s, std::memory_order_release); }

#ifdef TOMO_WEDGE_FORENSICS
    // FORENSICS for the stranded-reply class: claims (worker won the CAS), defers (lost it),
    // serves (io actually served). serves < claims on a stranded client names the dropped link.
    std::atomic<uint32_t> n_claims{0};
    std::atomic<uint32_t> n_defers{0};
    std::atomic<uint32_t> n_serves{0};
#endif

private:
    // --- io-hot scalars, packed: touched together on every pass ---------------------------------
    int       fd_   = -1;
    uint32_t  rlen_ = 0;          // bytes received
    uint32_t  rpos_ = 0;          // bytes parsed
    char*     rbuf_ = nullptr;
    size_t    rcap_ = 0;
    uint32_t  fill_  = 0;         // index of the buffer replies append to
    uint32_t  wsent_ = 0;         // bytes of the SEND buffer already written
    bool      recv_armed_    = false;
    bool      send_inflight_ = false;
    bool      serve_pending_ = false;
    bool      in_active_     = false;
    bool      closing_       = false;
    bool      dead_          = false;

    // --- cold io state --------------------------------------------------------------------------
    uint64_t  id_ = 0;
    uint32_t  ifid_thread_ = 0;
    Session   session_;

    // --- the ROB (manages its own cross-thread layout) ------------------------------------------
    Rob<kRobWindow> rob_;

    // --- write buffers (ex writes the direct-reply DATA region inside; header fields io-only) ---
    SmallBuf<kWbufInline> buf_[2];

    // --- executor-facing atomics, on their own line ---------------------------------------------
    alignas(64) std::atomic<bool>     retire_queued_{false};
    std::atomic<uint32_t> wb_slot_{kNoWbSlot};
};

}  // namespace tomo
