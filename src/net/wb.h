// wb.h — write-back: turning completed replies into bytes on a socket.
//
// PURE 2s (owner ruling 2026-08-24): the io thread that owns a connection is its only sender,
// for life. The 3s posture (dedicated wb threads) was measured and deleted -- its one win was
// +2-4% at 64c p32 (deep pipe + ex-scarce, the split tax amortized), and it lost everything
// else: p1 -22..-35%, p32<=32c -8%, overload -8% with double the tail, large values tied at the
// wire wall with worse tail. The depth sweep (p1..p32: -33% -> +4%, crossover ~p16-32) is the
// architecture story: the split's per-op tax (extra kernel transitions, Client/sock line
// migration, one hop) amortizes with batching, and only then can decoupled edges convert saved
// cores into ex. One base is worth more than that corner.
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
#include "conn.h"
#include "uring.h"

namespace tomo {

// THE LOCK BUG note above is preserved as history: WbGuard died with the multi-sender designs
// (exwb, then 3s). In pure 2s exactly one thread -- the connection's io thread -- ever touches the
// send side, so there is nothing to lock and no object to re-derive. If a future flip ever puts
// two servers on one connection, resurrect the guard from git history, not from memory.

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
    // serve (drain + stage + send) is one io-thread-local pass. The
    // ROB stays SPSC because the lock makes "exactly one consumer at any instant" true dynamically,
    // Retire completed ops IN ORDER, stage their bytes, and write. Owned and run only by the
    // connection's io thread. Returns true if it did anything, so a caller can tell progress from
    // an empty poll.
    bool serve(Client& c) {
        TOMO_FORENSIC(c.n_serves.fetch_add(1, std::memory_order_relaxed));
        stats_.serves++;
        Client& conn = c;
        const uint32_t retired = c.rob().drain([&](Op& op) {
            // Direct bytes are already in the fill buffer; publishing the length is the whole
            // "copy". A reply that outgrew the region spilled to op.reply -- emit it AFTER the
            // direct part so the RESP stream stays in order.
            if (op.direct_len) { conn.fill_buf().commit_raw(op.direct_len); stats_.direct++; }
            if (!op.reply.empty()) conn.fill_buf().append(op.reply.data(), op.reply.size());
        });
        bool did = retired != 0;
        if (!conn.nothing_to_write()) did |= pump(c);
        stats_.retired += retired;
        // A serve that retires nothing: the POLLING paths (flush_ready, the backstop) finding
        // nothing, which is expected and cheap.
        if (!retired) stats_.serves_empty++;
        return did;
    }

    // Try to push whatever this client has buffered. Safe to call spuriously: if nothing is pending
    // or a send is already outstanding it does nothing. Returns true if a send was submitted.
    bool pump(Client& c) {
        if (c.send_inflight()) return false;               // preserve one-send-per-socket ordering

        Client& conn = c;
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

        c.set_send_inflight(true);
        stats_.sends_submitted++;
        return true;
    }

    // Completion handler. `res` is the CQE result: bytes written, or negative errno.
    // Returns false when the connection should be torn down.
    bool on_send_complete(Client& c, int res) {
        bool resubmit = false;
        {
            c.set_send_inflight(false);

            if (res < 0) {
                if (res == -EAGAIN || res == -EINTR) { resubmit = true; }
                else { stats_.send_errors++; return false; }
            } else {
                Client& conn = c;
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
        if (resubmit) pump(c);
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
        uint64_t direct          = 0;   // replies formatted in place by the worker (c->buf trick)
        uint64_t handoffs        = 0;   // clients passed to another thread's ready queue
    };
    Stats& stats() { return stats_; }

private:
    Ring*  ring_ = nullptr;
    Stats  stats_;
};

}  // namespace tomo
