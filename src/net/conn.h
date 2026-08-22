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

    // Space to recv() into, growing if needed. Returns nullptr when the soft cap is reached, which
    // is the signal to stop reading and let the ROB drain.
    char* read_space(size_t want, size_t& out_avail) {
        if (rlen_ + want > rcap_) {
            if (rcap_ >= kRbufSoftCap) { out_avail = 0; return nullptr; }
            size_t ncap = rcap_ * 2;
            while (ncap < rlen_ + want) ncap *= 2;
            char* n = static_cast<char*>(std::realloc(rbuf_, ncap));
            if (!n) { out_avail = 0; return nullptr; }
            rbuf_ = n;
            rcap_ = ncap;
        }
        out_avail = rcap_ - rlen_;
        return rbuf_ + rlen_;
    }
    void commit_read(size_t n) { rlen_ += static_cast<uint32_t>(n); }

    // Safe ONLY at a quiescence point — see the header comment. Preserves any partially received
    // command at the tail, because that tail has no Slices pointing at it yet.
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

    // ---- write side ----------------------------------------------------------------------------
    SmallBuf<kWbufInline>& wbuf() { return wbuf_; }
    uint32_t wsent() const { return wsent_; }
    void     commit_write(uint32_t n) { wsent_ += n; }
    bool     write_drained() const { return wsent_ >= wbuf_.size(); }
    void     reset_wbuf() { wbuf_.clear(); wsent_ = 0; }

private:
    int       fd_   = -1;
    char*     rbuf_ = nullptr;
    uint32_t  rlen_ = 0;      // bytes received
    uint32_t  rpos_ = 0;      // bytes parsed
    size_t    rcap_ = 0;

    SmallBuf<kWbufInline> wbuf_;
    uint32_t  wsent_ = 0;
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

    uint64_t id() const { return id_; }
    void set_id(uint64_t v) { id_ = v; }

    // A connection may only be closed or migrated when nothing is in flight; otherwise a worker is
    // still holding a Task that resolves through this client's ROB. One test, everywhere.
    bool safe_to_release() const { return rob_.quiesced(); }

    bool closing() const { return closing_; }
    void mark_closing() { closing_ = true; }

    WbLink& wb() { return wb_; }

    // Set by a worker before it tells the owning IO thread this client has ops to retire; cleared by
    // that IO thread when it picks the client up. Without it, a pipelined burst of N completions
    // enqueues the same client N times and the retire channel fills with duplicates.
    std::atomic<bool>& retire_queued() { return retire_queued_; }

private:
    Conn            conn_;
    Rob<kRobWindow> rob_;
    WbLink          wb_;
    std::atomic<bool> retire_queued_{false};
    uint64_t        id_ = 0;
    uint32_t        io_thread_ = 0;
    bool            closing_ = false;
};

}  // namespace tomo
