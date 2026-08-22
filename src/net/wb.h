// wb.h — write-back: turning completed replies into bytes on a socket.
//
// THE SEND LOGIC IS THE SAME IN ALL THREE MODES. What differs is only WHICH THREAD runs it. So the
// logic lives here once and each loop calls it; the modes are a scheduling decision, not three
// implementations.
//
//   WbMode::Io   2-stage.   The IO thread that owns the connection also sends.       (default)
//   WbMode::Ex   ex-wb.     The executor sends its own completed prefix.
//   WbMode::Wb   3-stage.   A dedicated write-back thread owns the send side.
//
// The fork measured Io as the winner and the reason generalises: p1 throughput is
// (threads that ISSUE SENDS) x ~90k, and a 2-stage server buys send width once because its io
// threads both receive and send, while Ex and Wb must buy it a second time out of the same thread
// budget. That is a property of the architecture rather than of the implementation, so the other two
// modes are kept as measurable alternatives, not as expected wins.
//
// ============================================================================================
// THE LOCK BUG THIS FILE EXISTS TO PREVENT
//
// In the fork, lock and unlock each independently re-derived the write-back object from the client:
//
//     tomoWbLockClient(c)   { wc = clientTail(c)->wb; ...lock(wc); }
//     tomoWbUnlockClient(c) { wc = clientTail(c)->wb; unlock(wc); assert(before > 0); }
//
// If that expression yielded a different object between the two calls, unlock released a mutex it
// never held and decremented a counter lock never incremented. It crashed on the 25GbE NIC and was
// NOT reproducible on loopback — the worst possible shape.
//
// WbGuard resolves the target ONCE, in its constructor, and uses that captured pointer in its
// destructor. Re-derivation is impossible, so the entire bug class is gone by construction rather
// than by discipline.
// ============================================================================================
#pragma once
#include <atomic>
#include <cstdint>
#include <mutex>
#include "conn.h"
#include "uring.h"

namespace tomo {

enum class WbMode : uint8_t { Io = 0, Ex = 1, Wb = 2 };

// RAII. Resolves once, releases what it resolved. See the header comment.
class WbGuard {
public:
    WbGuard(WbLink& link, WbMode mode)
        : link_(&link), locked_(mode != WbMode::Io) {
        if (locked_) link_->m.lock();
    }
    ~WbGuard() { if (locked_) link_->m.unlock(); }
    WbGuard(const WbGuard&) = delete;
    WbGuard& operator=(const WbGuard&) = delete;

    WbLink& link() { return *link_; }

private:
    WbLink* const link_;     // captured once; const so it cannot be re-pointed
    const bool    locked_;
};

// Per-thread send engine. Every loop that sends owns one and calls the same two methods.
class WbEngine {
public:
    void bind(Ring* ring, WbMode mode) { ring_ = ring; mode_ = mode; }

    WbMode mode() const { return mode_; }
    Ring&  ring()       { return *ring_; }

    // Try to push whatever this client has buffered. Safe to call spuriously: if nothing is pending
    // or a send is already outstanding it does nothing. Returns true if a send was submitted.
    bool pump(Client& c, WbLink& link) {
        WbGuard g(link, mode_);
        if (g.link().send_inflight) return false;          // preserve one-send-per-socket ordering

        Conn& conn = c.conn();
        const size_t total = conn.wbuf().size();
        const size_t sent  = conn.wsent();
        if (sent >= total) return false;                   // nothing to do

        io_uring_sqe* s = ring_->sqe();
        if (!s) return false;
        io_uring_prep_send(s, conn.fd(), conn.wbuf().data() + sent, total - sent, MSG_NOSIGNAL);
        s->user_data = ur_tag(UrKind::Send, &c);
        ring_->note_pending();

        g.link().send_inflight = true;
        stats_.sends_submitted++;
        return true;
    }

    // Completion handler. `res` is the CQE result: bytes written, or negative errno.
    // Returns false when the connection should be torn down.
    bool on_send_complete(Client& c, WbLink& link, int res) {
        bool resubmit = false;
        {
            WbGuard g(link, mode_);
            g.link().send_inflight = false;

            if (res < 0) {
                if (res == -EAGAIN || res == -EINTR) { resubmit = true; }
                else { stats_.send_errors++; return false; }
            } else {
                Conn& conn = c.conn();
                conn.commit_write(static_cast<uint32_t>(res));
                stats_.bytes_sent += static_cast<uint64_t>(res);
                if (conn.write_drained()) {
                    conn.reset_wbuf();
                    stats_.sends_completed++;
                } else {
                    // Short write. Not an error and not rare under load — the remainder must go out
                    // before anything else is appended, or the stream reorders.
                    resubmit = true;
                    stats_.short_writes++;
                }
            }
        }
        if (resubmit) pump(c, link);
        return true;
    }

    struct Stats {
        uint64_t sends_submitted = 0;
        uint64_t sends_completed = 0;
        uint64_t short_writes    = 0;
        uint64_t send_errors     = 0;
        uint64_t bytes_sent      = 0;
        uint64_t handoffs        = 0;   // clients passed to another thread's ready queue
    };
    Stats& stats() { return stats_; }

private:
    Ring*  ring_ = nullptr;
    WbMode mode_ = WbMode::Io;
    Stats  stats_;
};

}  // namespace tomo
