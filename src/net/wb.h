// wb.h — write-back: turning completed replies into bytes on a socket.
//
// THE SEND LOGIC IS THE SAME FOR EVERY SENDER. Which thread runs it is a PER-CONNECTION property:
// Client::sender_thread(), assigned at accept (today: the accepting io thread itself, or its
// placement-paired wb — reproducing the old 2s/3s exactly), re-assignable later only through a
// quiesce fence. There is no server-wide mode; "2s" and "3s" are postures of one server, W=0 or
// W>0 in --ratio.
//
// (Executor-issued sends (exwb) existed and were DELETED
// 2026-08-24: #1 in zero measured cells. Send work rides the scarce ex role: nearly free at p1,
// ruinous at p32. The p1 width law explains its old small-size p1 second places, and 2s dominates
// those anyway.)
//
// The width law (2026-08-24): p1 throughput = min(recv lanes, send lanes) x per-lane rate; a 2s io
// thread is both lanes at once, so 2s buys width ~twice as cheaply and owns p1. 3s protects ex from
// send work and wins high-core high-pipe (64c p32) and overload.
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

// RAII. Resolves once, releases what it resolved. See the header comment.
//
// WHO NEEDS THE LOCK, derived from what the serving thread OWNS at that moment:
//   Io  (2s)   owns the whole client -- no other server can exist.           NO LOCK
//   Wb  (3s)   owns ConnOut alone, STATICALLY -- one fixed sender, and nothing else ever
//              touches the send side (io never serves it, ex only notifies). NO LOCK
// The Wb elision is not an optimisation gamble; it is the same fact that makes Io lock-free,
// arrived at statically instead of by identity. (The deleted exwb mode was the one genuinely
// multi-server shape; WbProto::Shared remains as the tag a future flip stamps when a connection
// really does have more than one server.)
class WbGuard {
public:
    // Item 5: the lock decision is the CONNECTION's protocol, not the binary's mode. Today every
    // connection has exactly one sender for life (Owned or Fixed), so no serve anywhere takes a
    // lock; Shared is the tag a flip will stamp -- at the quiescence fence -- on the day a
    // connection genuinely has more than one server.
    WbGuard(WbLink& link, WbProto proto)
        : link_(&link), locked_(proto == WbProto::Shared) {
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
    void bind(Ring* ring) { ring_ = ring; }

    Ring&  ring()       { return *ring_; }

    // THE WHOLE REPLY SIDE, in one call, run by whichever stage owns sending for this client.
    //
    // Retire completed ops IN ORDER, stage their bytes, and write. All three belong together and all
    // three belong to the sender: if the io thread retired and merely handed bytes over, only the
    // send syscall would move between modes and an "ex-wb" measured that way would not be ex-wb.
    //
    // WHO MAY CALL. In Io mode, only the owning io thread -- no lock exists or is needed. In Wb mode,
    // only the connection's dedicated sender. In EX MODE, ANYONE: the executor that just completed
    // the head flushes it inline, and the owning io thread sweeps as the backstop -- so the whole
    // serve (drain + stage + send), not just the pump, runs under the connection's WbLink lock. The
    // ROB stays SPSC because the lock makes "exactly one consumer at any instant" true dynamically,
    // which is the same invariant a fixed consumer provides statically.
    //
    // Returns true if it did anything, so a caller can tell progress from an empty poll.
    template <typename NotifyIo>
    bool serve(Client& c, NotifyIo&& notify_io) {
        WbGuard g(c.wb(), c.proto());
        return serve_locked(c, notify_io);
    }

    // The executor's opportunistic entry: never blocks. If the lock is busy, someone is already
    // draining this connection -- and if OUR op's Done landed after their drain passed its slot, the
    // reply has "slipped". Slips are HARMLESS by design, not by luck: the caller notifies the owning
    // io thread on a false return, and io's backstop pass retires anything a race left behind. That
    // backstop is what lets the head-check be a cheap hint instead of a fenced protocol -- the
    // alternative is the Dekker discipline that cost this codebase five commits.
    template <typename NotifyIo>
    bool try_serve(Client& c, NotifyIo&& notify_io) {
        if (c.proto() == WbProto::Shared) {              // the only multi-server protocol
            if (!c.wb().m.try_lock()) return false;
            const bool did = serve_locked(c, notify_io);
            c.wb().m.unlock();
            (void)did;
            return true;
        }
        serve_locked(c, notify_io);
        return true;
    }

    // Lock-assumed core of serve(). Callers hold the WbLink lock (or are in Io mode, where no other
    // server can exist).
    template <typename NotifyIo>
    bool serve_locked(Client& c, NotifyIo&& notify_io) {
        TOMO_FORENSIC(c.wb().n_serves.fetch_add(1, std::memory_order_relaxed));
        stats_.serves++;
        ConnOut& conn = c.out();
        const uint32_t retired = c.rob().drain([&](Op& op) {
            conn.fill_buf().append(op.reply.data(), op.reply.size());
        });
        bool did = retired != 0;
        if (!conn.nothing_to_write()) did |= pump_locked(c, c.wb());

        // Poke the io thread only if it told us it was stuck. Retiring may have freed a ROB slot or
        // unpinned the read buffer, and io cannot discover that on its own without polling.
        // Per-conn: for a SELF-SERVED conn the serving thread IS io -- the flag is its own, and the
        // flush_ready pass that called us re-evaluates stuck-ness right after, so the load would
        // answer a question the caller is about to answer better.
        if (!c.sender_is_io() && retired && c.needs_io_wake().load(std::memory_order_acquire)) {
            c.needs_io_wake().store(false, std::memory_order_release);
            notify_io();
        }
        stats_.retired += retired;
        // A serve that retires nothing. For a delegated conn this is a wake the sender could not
        // act on; for a self-served one it is mostly the POLLING paths (io's flush_ready pass, the
        // backstop) finding nothing, which is expected and cheap -- interpret per shape.
        if (!retired) stats_.serves_empty++;
        return did;
    }

    // Try to push whatever this client has buffered. Safe to call spuriously: if nothing is pending
    // or a send is already outstanding it does nothing. Returns true if a send was submitted.
    bool pump(Client& c, WbLink& link) {
        WbGuard g(link, c.proto());
        return pump_locked(c, g.link());
    }

    bool pump_locked(Client& c, WbLink& link) {
        if (link.send_inflight) return false;              // preserve one-send-per-socket ordering

        ConnOut& conn = c.out();
        // Nothing outstanding, so if the send buffer is fully written we may promote the fill
        // buffer. This is the ONLY point at which the two swap, and it is safe precisely because
        // send_inflight is false here.
        if (conn.write_drained() && conn.has_pending_fill()) conn.swap_buffers();

        const size_t total = conn.send_buf().size();
        const size_t sent  = conn.wsent();
        if (sent >= total) return false;                   // nothing to do

        io_uring_sqe* s = ring_->sqe();
        if (!s) { stats_.sqe_starved++; return false; }
        io_uring_prep_send(s, conn.fd(), conn.send_buf().data() + sent, total - sent, MSG_NOSIGNAL);
        s->user_data = ur_tag(UrKind::Send, &c);
        ring_->note_pending();

        link.send_inflight = true;
        stats_.sends_submitted++;
        return true;
    }

    // Completion handler. `res` is the CQE result: bytes written, or negative errno.
    // Returns false when the connection should be torn down.
    bool on_send_complete(Client& c, WbLink& link, int res) {
        bool resubmit = false;
        {
            WbGuard g(link, c.proto());
            g.link().send_inflight = false;

            if (res < 0) {
                if (res == -EAGAIN || res == -EINTR) { resubmit = true; }
                else { stats_.send_errors++; return false; }
            } else {
                ConnOut& conn = c.out();
                conn.commit_write(static_cast<uint32_t>(res));
                stats_.bytes_sent += static_cast<uint64_t>(res);
                if (conn.write_drained()) {
                    stats_.sends_completed++;
                    // More replies may have accumulated in the fill buffer while this send was in
                    // flight; resubmit so they go out rather than waiting for an unrelated event.
                    if (conn.has_pending_fill()) resubmit = true;
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
        uint64_t sqe_starved     = 0;   // pump could not get an SQE; bytes stay staged
        uint64_t serves          = 0;
        uint64_t serves_empty    = 0;   // serve() retired nothing: a wake with no head-ready
        uint64_t bytes_sent      = 0;
        uint64_t retired         = 0;   // ops retired from ROBs by this sender
        uint64_t handoffs        = 0;   // clients passed to another thread's ready queue
    };
    Stats& stats() { return stats_; }

private:
    Ring*  ring_ = nullptr;
    Stats  stats_;
};

}  // namespace tomo
