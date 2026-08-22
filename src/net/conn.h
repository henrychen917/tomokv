// conn.h — Conn (the socket) and Client (the protocol + reorder buffer).
//
// SPLIT ON PURPOSE. Conn is fd, buffers, and event registration; Client is parse state and the ROB.
// They separate because a connection can migrate between IO threads for load balancing, and because
// the ROB's lifetime is governed by in-flight ops rather than by the socket.
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
#include <mutex>
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
inline constexpr size_t   kRbufSoftCap  = 1 * 1024 * 1024;  // stop reading past this until drained
inline constexpr size_t   kWbufInline   = 16 * 1024;

class Conn {
public:
    explicit Conn(int fd) : fd_(fd) {
        rbuf_ = static_cast<char*>(std::malloc(kRbufInitial));
        rcap_ = kRbufInitial;
    }
    ~Conn() { std::free(rbuf_); }
    Conn(const Conn&) = delete;
    Conn& operator=(const Conn&) = delete;

    int  fd() const { return fd_; }
    void set_fd(int fd) { fd_ = fd; }

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
        if (avail < want && may_grow && rcap_ < kRbufSoftCap) {
            size_t ncap = rcap_ * 2;
            while (ncap < rlen_ + want && ncap < kRbufSoftCap) ncap *= 2;
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
        if (rcap_ > kRbufSoftCap) {          // shed one huge request's growth
            char* n = static_cast<char*>(std::realloc(rbuf_, kRbufInitial));
            if (n) { rbuf_ = n; rcap_ = kRbufInitial; }
        }
    }

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
    // is the caller's invariant (WbLink::send_inflight).
    void swap_buffers() {
        buf_[fill_ ^ 1].clear();      // old send buffer is fully written; recycle it as the next fill
        fill_ ^= 1;
        wsent_ = 0;
    }
    bool nothing_to_write() const { return buf_[fill_].size() == 0 && write_drained(); }

private:
    int       fd_   = -1;
    char*     rbuf_ = nullptr;
    uint32_t  rlen_ = 0;      // bytes received
    uint32_t  rpos_ = 0;      // bytes parsed
    size_t    rcap_ = 0;

    SmallBuf<kWbufInline> buf_[2];
    uint32_t  fill_  = 0;         // index of the buffer replies append to
    uint32_t  wsent_ = 0;         // bytes of the SEND buffer already written
    bool      recv_armed_ = false;
};

// Per-client send-side state. Defined here rather than in wb.h because Client owns it and wb.h
// already depends on this file. Only wb.h touches the contents.
struct WbLink {
    // Contended only when the sender is not the connection's IO thread — i.e. in Ex and Wb modes.
    // In Io mode WbGuard never touches it, so the shipping path pays nothing for its existence.
    std::mutex m;

    // Exactly ONE send may be outstanding per connection. Two concurrent sends on one socket can
    // complete out of order and interleave bytes, which corrupts the stream in a way that looks
    // like a protocol bug anywhere but here.
    bool send_inflight = false;

    // Already sitting in some ready queue; keeps a client from being enqueued twice.
    std::atomic<bool> queued{false};

    // FORENSICS for the stranded-reply class. Every stranded op is a notification that was owed and
    // never delivered, and these three say which link of the chain dropped it:
    //   claims  -- a worker won the CAS and became responsible for posting this client
    //   defers  -- a worker lost the CAS and deferred to whoever holds the claim
    //   serves  -- the sender actually ran serve() on it
    // serves < claims on a stranded client means a claim was made and never turned into a serve.
    // OFF BY DEFAULT. n_defers fires on every deferred notify -- two orders of magnitude more often
    // than n_claims -- so leaving these compiled in puts an atomic RMW on the hot path to serve a
    // diagnostic that has already done its job. Build with -DTOMO_WEDGE_FORENSICS to get them back.
#ifdef TOMO_WEDGE_FORENSICS
    std::atomic<uint32_t> n_claims{0};
    std::atomic<uint32_t> n_defers{0};
    std::atomic<uint32_t> n_serves{0};
#endif
};

class Client {
public:
    explicit Client(int fd) : conn_(fd) {}
    Client(const Client&) = delete;
    Client& operator=(const Client&) = delete;

    Conn&            conn() { return conn_; }
    Rob<kRobWindow>& rob()  { return rob_; }

    uint32_t io_thread() const { return io_thread_; }
    void set_io_thread(uint32_t t) { io_thread_ = t; }

    // Which thread retires this client's ROB and issues its sends. In 2-stage that IS the io
    // thread; in ex-wb it is an executor, in 3-stage a dedicated write-back thread. Everything on
    // the reply side belongs to this thread and nothing else touches the write buffer.
    uint32_t sender_thread() const { return sender_thread_; }
    void set_sender_thread(uint32_t t) { sender_thread_ = t; }
    bool sender_is_io() const { return sender_thread_ == io_thread_; }

    // Set by the io thread when it CANNOT make progress until the ROB advances — the window is full
    // or the read buffer has no room. The sender checks it after retiring and pokes io only then,
    // so the common case costs no cross-thread message at all. Without it the io thread can sit
    // with a full window and no recv armed, waiting for an event that never comes.
    std::atomic<bool>& needs_io_wake() { return needs_io_wake_; }

    uint64_t id() const { return id_; }
    void set_id(uint64_t v) { id_ = v; }

    // A connection may only be closed or migrated when nothing is in flight; otherwise a worker is
    // still holding a Task that resolves through this client's ROB. One test, everywhere.
    bool safe_to_release() const { return rob_.quiesced(); }

    bool closing() const { return closing_; }
    void mark_closing() { closing_ = true; }

    WbLink& wb() { return wb_; }

    // Membership in its io thread's active set, as a FLAG rather than a search. The set was a
    // vector with a linear scan, so marking a client active cost one pointer compare per client
    // already in it — on every operation. At ~85 clients per io thread that is 85 compares per op
    // to answer a question the client can answer about itself in one load.
    bool in_active() const { return in_active_; }
    void set_in_active(bool v) { in_active_ = v; }

    // Set by a worker before it tells the owning IO thread this client has ops to retire; cleared by
    // that IO thread when it picks the client up. Without it, a pipelined burst of N completions
    // enqueues the same client N times and the retire channel fills with duplicates.
    std::atomic<bool>& retire_queued() { return retire_queued_; }

private:
    Conn            conn_;
    Rob<kRobWindow> rob_;
    WbLink          wb_;
    std::atomic<bool> retire_queued_{false};
    std::atomic<bool> needs_io_wake_{false};
    uint32_t          sender_thread_ = 0;
    bool              in_active_ = false;
    uint64_t        id_ = 0;
    uint32_t        io_thread_ = 0;
    bool            closing_ = false;
};

}  // namespace tomo
