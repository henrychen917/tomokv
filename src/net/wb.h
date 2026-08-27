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
#include "tls.h"
#include "uring.h"
#include "../core/signal.h"

namespace tomo {

// THE LOCK BUG note above is preserved as history: WbGuard died with the multi-sender designs
// (exwb, then 3s). In pure 2s exactly one thread -- the connection's io thread -- ever touches the
// send side, so there is nothing to lock and no object to re-derive. If a future flip ever puts
// two servers on one connection, resurrect the guard from git history, not from memory.

// Per-thread send engine. Every loop that sends owns one and calls the same two methods.
class WbEngine {
public:
    using ReleaseFn = void (*)(void*, int32_t, const char*);
    using RetireFn = void (*)(void*, Client&, Op&);
    using LimitFn = bool (*)(void*, Client&);

    void bind(Ring* ring, void* release_ctx = nullptr, ReleaseFn release_fn = nullptr,
              void* retire_ctx = nullptr, RetireFn retire_fn = nullptr,
              const std::atomic<bool>* limit_armed = nullptr,
              void* limit_ctx = nullptr, LimitFn limit_fn = nullptr,
              const uint32_t* cached_now_s = nullptr, LoopSignals* tls_signals = nullptr) {
        ring_ = ring;
        release_ctx_ = release_ctx;
        release_fn_ = release_fn;
        retire_ctx_ = retire_ctx;
        retire_fn_ = retire_fn;
        limit_armed_ = limit_armed;
        limit_ctx_ = limit_ctx;
        limit_fn_ = limit_fn;
        cached_now_s_ = cached_now_s;
        tls_signals_ = tls_signals;
    }

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
        if (__builtin_expect(limit_armed_ &&
                             limit_armed_->load(std::memory_order_relaxed), false))
            return serve_impl<true, false>(c);
        return serve_impl<false, false>(c);
    }

    // kTLS uses the ordinary plaintext staging and send path. This separate instantiation only
    // enforces/counts the pre-existing TLS no-borrow contract; plaintext clients pay no mode test.
    bool serve_ktls(Client& c) {
        if (__builtin_expect(limit_armed_ &&
                             limit_armed_->load(std::memory_order_relaxed), false))
            return serve_impl<true, true>(c);
        return serve_impl<false, true>(c);
    }

    // TLS is a separate write-back variant selected by the IO owner. Plain serve()/pump() above
    // remain untouched and are the only instantiated path when tls-port is zero.
    bool serve_tls(Client& c, TlsConn& tls) {
        if (__builtin_expect(limit_armed_ &&
                             limit_armed_->load(std::memory_order_relaxed), false))
            return serve_tls_impl<true>(c, tls);
        return serve_tls_impl<false>(c, tls);
    }

    // CLIENT REPLY OFF/SKIP (Lane F). Cold: reached only from the climon object when the reply
    // armed bit is set, never from serve(), so the send engine's hot template pair is untouched.
    //
    // PER-OP, and that is the point. Suppression cannot be decided per connection: a pipelined
    // `CLIENT REPLY SKIP; PING; PING` retires all three in ONE drain, and a per-connection
    // decision would swallow both PONGs. The mark is made by the io thread's armed gate before
    // dispatch, so each op carries its own answer here.
    //
    // Special command state MUST still be surrendered through retire_fn_ even when the bytes are
    // dropped, or scatter/blocking/MULTI/notification state leaks and cross-shard groups never
    // complete. A borrowed value that survives retire_fn_ is returned to its owning shard instead
    // of being sent. Direct-reply bytes live in the fill buffer's spare capacity and are simply
    // never committed.
    __attribute__((noinline, cold))
    bool serve_suppressing(Client& c) {
        stats_.serves++;
        Client& conn = c;
        conn.start_obuf_tracking();
        const uint32_t retired = c.rob().drain([&](Op& op) {
            if (op.zc_ptr) {
                if (retire_fn_) retire_fn_(retire_ctx_, conn, op);
            }
            if (op.reply_skip()) {
                if (op.zc_ptr && op.zc_shard >= 0 && release_fn_)
                    release_fn_(release_ctx_, op.zc_shard, op.zc_ptr);
                return;
            }
            if (op.zc_ptr) {
                conn.seal_fill_segment();
                conn.append_buf_segment(op.direct, op.direct_len,
                                        op.reply.data(), op.reply.size());
                conn.append_borrow_segment(op.zc_ptr, op.zc_len, op.zc_shard);
                conn.append_static_segment(kCrlf, sizeof(kCrlf));
                return;
            }
            // A suppressed op ahead of this one may have left uncommitted direct bytes at the
            // fill frontier; this op's direct region was handed out at the same offset only if
            // nothing was staged, so committing here stays correct.
            if (conn.has_pending_segments()) {
                conn.append_buf_segment(op.direct, op.direct_len,
                                        op.reply.data(), op.reply.size());
            } else {
                if (op.direct_len) conn.commit_fill(op.direct_len);
                if (!op.reply.empty()) conn.append_fill(op.reply.data(), op.reply.size());
            }
        });
        bool did = retired != 0;
        if (limit_fn_ && limit_fn_(limit_ctx_, c)) {
            stats_.retired += retired;
            return true;
        }
        if (!conn.nothing_to_write()) did |= pump(c);
        stats_.retired += retired;
        return did;
    }

    // Try to push whatever this client has buffered. Safe to call spuriously: if nothing is pending
    // or a send is already outstanding it does nothing. Returns true if a send was submitted.
    bool pump(Client& c) {
        if (c.send_inflight()) return false;               // preserve one-send-per-socket ordering

        Client& conn = c;
        // A legacy contiguous send may predate the first borrowed reply. It remains the wire head
        // until drained; the segment queue starts strictly after it.
        const size_t legacy_total = conn.send_buf().size();
        const size_t legacy_sent  = conn.wsent();
        if (legacy_sent < legacy_total)
            return submit_legacy(c, legacy_total, legacy_sent);

        if (conn.has_pending_segments()) {
            bool has_borrow = false;
            uint32_t total = 0;
            const uint32_t niov = conn.build_segment_iov(has_borrow, total);
            if (!niov) return false;

            io_uring_sqe* s = ring_->sqe();
            if (!s) { stats_.sqe_starved++; return false; }
            io_uring_prep_sendmsg(s, conn.fd(), conn.send_msg(), MSG_NOSIGNAL);
            s->user_data = ur_tag(UrKind::Send, &c);
            ring_->note_pending();

            conn.set_segmented_send(true);
            conn.set_send_requested(total);
            conn.set_send_inflight(true);
            stats_.sends_submitted++;
            if (has_borrow) stats_.zc_sends++;
            return true;
        }

        // Nothing outstanding, so if the send buffer is fully written we may promote the fill
        // buffer. This is the ONLY point at which the two swap, and it is safe precisely because
        // send_inflight is false here.
        if (conn.write_drained() && conn.has_pending_fill()) conn.swap_buffers();

        const size_t total = conn.send_buf().size();
        const size_t sent  = conn.wsent();
        return sent < total ? submit_legacy(c, total, sent) : false;
    }

    bool pump_tls(Client& c, TlsConn& tls) {
        if (c.send_inflight()) return false;

        // Ciphertext already materialized by OpenSSL is always the wire head. Its CQE advances only
        // the external BIO cursor; it never advances Client's plaintext segment/wsent frontiers.
        const char* cipher = nullptr;
        const int cipher_bytes = tls.peek_output(cipher);
        if (cipher_bytes > 0)
            return submit_tls_cipher(c, cipher, static_cast<uint32_t>(cipher_bytes));
        if (!tls.connected()) return false;

        Client& conn = c;
        const char* plain = nullptr;
        size_t plain_bytes = 0;
        bool segmented = false;

        const size_t legacy_total = conn.send_buf().size();
        const size_t legacy_sent = conn.wsent();
        if (legacy_sent < legacy_total) {
            plain = conn.send_buf().data() + legacy_sent;
            plain_bytes = legacy_total - legacy_sent;
        } else if (conn.has_pending_segments()) {
            bool has_borrow = false;
            uint32_t total = 0;
            const uint32_t niov = conn.build_segment_iov(has_borrow, total);
            if (!niov) return false;
            // Both producers are gated before this point. Keep this defensive assertion close to
            // encryption: a future producer must not silently resurrect borrowed TLS output.
            if (has_borrow) std::abort();
            plain = static_cast<const char*>(conn.send_msg()->msg_iov[0].iov_base);
            plain_bytes = conn.send_msg()->msg_iov[0].iov_len;
            segmented = true;
        } else {
            if (conn.write_drained() && conn.has_pending_fill()) conn.swap_buffers();
            const size_t total = conn.send_buf().size();
            const size_t sent = conn.wsent();
            if (sent >= total) return false;
            plain = conn.send_buf().data() + sent;
            plain_bytes = total - sent;
        }

        if (tls.has_pinned_plain()) {
            const char* pinned = nullptr;
            size_t pinned_bytes = 0;
            tls.pinned_plain(pinned, pinned_bytes);
            // The retry contract is byte-identical. The client frontier cannot move on WANT_*.
            if (pinned != plain || pinned_bytes > plain_bytes) std::abort();
            plain = pinned;
            plain_bytes = pinned_bytes;
        }

        const TlsIoResult encrypted = tls.write_plain(plain, plain_bytes);
        if (encrypted.op == TlsOp::Progress) {
            const uint32_t plain_accepted = encrypted.bytes;
            if (segmented) {
                (void)conn.consume_segments(plain_accepted,
                    [&](int32_t shard, const char* ptr) { release(shard, ptr); });
            } else {
                conn.commit_write(plain_accepted);
            }
            stats_.tls_plaintext_bytes += plain_accepted;
            if (tls_signals_) tls_signals_->tls_plaintext_output_bytes += plain_accepted;
        } else if (encrypted.op == TlsOp::WantWrite) {
            stats_.tls_want_write++;
            if (tls_signals_) tls_signals_->tls_want_write++;
        } else if (encrypted.op == TlsOp::WantRead) {
            stats_.tls_want_read++;
            if (tls_signals_) tls_signals_->tls_want_read++;
        }
        if (tls.failed()) {
            if (!tls.last_error().empty())
                std::fprintf(stderr, "TLS client %llu: %s\n",
                             static_cast<unsigned long long>(c.id()),
                             tls.last_error().c_str());
            return false;
        }

        cipher = nullptr;
        const int ready = tls.peek_output(cipher);
        if (ready > 0) return submit_tls_cipher(c, cipher, static_cast<uint32_t>(ready));
        return encrypted.op == TlsOp::Progress;
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
                if (conn.segmented_send()) {
                    stats_.zc_bytes += conn.consume_segments(static_cast<uint32_t>(res),
                        [&](int32_t shard, const char* ptr) { release(shard, ptr); });
                } else {
                    conn.commit_write(static_cast<uint32_t>(res));
                }
                stats_.bytes_sent += static_cast<uint64_t>(res);
                if (cached_now_s_) c.set_last_interaction_s(*cached_now_s_);
                if (static_cast<uint32_t>(res) < conn.send_requested()) stats_.short_writes++;
                const bool drained = conn.segmented_send()
                    ? !conn.has_pending_segments()
                    : conn.write_drained();
                if (drained) {
                    stats_.sends_completed++;
                    // More replies may have accumulated in the fill buffer while this send was in
                    // flight; resubmit so they go out rather than waiting for an unrelated event.
                    if (conn.has_pending_fill() || conn.has_pending_segments()) resubmit = true;
                } else {
                    // This includes a short write and a full 16-iovec window with more queued
                    // segments. Both resume from the queue's (head index, byte offset) frontier.
                    resubmit = true;
                }
            }
        }
        if (resubmit) pump(c);
        return true;
    }

    bool on_tls_send_complete(Client& c, TlsConn& tls, int res) {
        c.set_send_inflight(false);
        bool resubmit = false;
        if (res < 0) {
            if (res == -EAGAIN || res == -EINTR) resubmit = true;
            else if (c.closing()) {
                // A rejected handshake or an abrupt peer can make the alert/close_notify flight
                // lose its race with socket teardown.  The connection is already doomed and no
                // application reply is being lost, so drain the memory BIO instead of reporting a
                // false data-path send error or keeping close_client waiting on unsendable bytes.
                const char* pending = nullptr;
                int bytes = 0;
                while ((bytes = tls.peek_output(pending)) > 0)
                    if (!tls.consume_output(static_cast<uint32_t>(bytes))) break;
                return true;
            } else { stats_.send_errors++; return false; }
        } else if (res == 0) {
            if (c.closing()) {
                const char* pending = nullptr;
                int bytes = 0;
                while ((bytes = tls.peek_output(pending)) > 0)
                    if (!tls.consume_output(static_cast<uint32_t>(bytes))) break;
                return true;
            }
            stats_.send_errors++;
            return false;
        } else {
            const uint32_t cipher_sent = static_cast<uint32_t>(res);
            if (!tls.consume_output(cipher_sent)) {
                stats_.send_errors++;
                return false;
            }
            stats_.bytes_sent += cipher_sent;
            stats_.tls_ciphertext_bytes += cipher_sent;
            if (tls_signals_) tls_signals_->tls_ciphertext_output_bytes += cipher_sent;
            if (cached_now_s_) c.set_last_interaction_s(*cached_now_s_);
            if (cipher_sent < c.send_requested()) stats_.short_writes++;
            else stats_.sends_completed++;
            resubmit = true;
        }
        if (resubmit) pump_tls(c, tls);
        return !tls.failed();
    }

    // A closed connection cannot send remaining segments. If a sendmsg is still in flight its
    // iovecs remain pinned until the CQE; otherwise every BORROW is returned immediately.
    void teardown(Client& c) {
        if (c.send_inflight()) return;
        c.release_all_segments([&](int32_t shard, const char* ptr) { release(shard, ptr); });
    }

    // Dead clients still receive their send CQE during the deferred-free window. Consume whatever
    // reached the wire, then release both the completed and unsent BORROW segments exactly once.
    void on_dead_send_complete(Client& c, int res) {
        c.set_send_inflight(false);
        if (res > 0) {
            if (c.segmented_send()) {
                stats_.zc_bytes += c.consume_segments(static_cast<uint32_t>(res),
                    [&](int32_t shard, const char* ptr) { release(shard, ptr); });
            } else {
                c.commit_write(static_cast<uint32_t>(res));
            }
            stats_.bytes_sent += static_cast<uint64_t>(res);
        }
        teardown(c);
    }

    void on_dead_tls_send_complete(Client& c, TlsConn& tls, int res) {
        c.set_send_inflight(false);
        if (res > 0) {
            const uint32_t cipher_sent = static_cast<uint32_t>(res);
            if (tls.consume_output(cipher_sent)) {
                stats_.bytes_sent += cipher_sent;
                stats_.tls_ciphertext_bytes += cipher_sent;
                if (tls_signals_) tls_signals_->tls_ciphertext_output_bytes += cipher_sent;
            }
        }
        teardown(c);
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
        uint64_t zc_sends        = 0;   // sendmsg submissions whose iovecs include a BORROW
        uint64_t zc_bytes        = 0;   // borrowed value bytes reported complete by the kernel
        uint64_t zc_releases     = 0;   // BORROW segments returned on completion or teardown
        uint64_t zc_suppressed_tls = 0; // borrows copied+released before TLS encryption
        uint64_t tls_plaintext_bytes = 0;
        uint64_t tls_ciphertext_bytes = 0;
        uint64_t tls_want_read = 0;
        uint64_t tls_want_write = 0;
    };
    Stats& stats() { return stats_; }
    void note_zc_suppressed_tls() {
        stats_.zc_suppressed_tls++;
        if (tls_signals_) tls_signals_->tls_zc_suppressed++;
    }

private:
    template <bool TrackOutput, bool TlsNoBorrow>
    bool serve_impl(Client& c) {
        TOMO_FORENSIC(c.n_serves.fetch_add(1, std::memory_order_relaxed));
        stats_.serves++;
        Client& conn = c;
        if constexpr (TrackOutput) conn.start_obuf_tracking();
        const uint32_t retired = c.rob().drain([&](Op& op) {
            if constexpr (TlsNoBorrow) {
                if (op.no_borrow()) note_zc_suppressed_tls();
            }
            // Cross-shard completion publishes descriptors/state, not bytes.  The connection's IO
            // owner turns those into the final ordered reply here, before the generic staging path
            // inspects the (possibly repurposed) zero-copy fields.
            // Plain commands have no sidecar and take exactly the pre-notify zc_ptr branch. Special
            // command state, borrowed values, and armed notification batches all already use this
            // field, so their retirement hook nests behind that existing test.
            if (op.zc_ptr) {
                if (retire_fn_) retire_fn_(retire_ctx_, conn, op);
            }
            if (op.zc_ptr) {
                // Anything already staged is older than this op. Once sealed, every subsequent
                // reply uses segments until the queue drains, so no fill-buffer append can jump a
                // borrowed value that is only partially written.
                conn.seal_fill_segment();
                conn.append_buf_segment(op.direct, op.direct_len,
                                        op.reply.data(), op.reply.size());
                if constexpr (TlsNoBorrow) {
                    conn.append_buf_segment(op.zc_ptr, op.zc_len);
                    release(op.zc_shard, op.zc_ptr);
                    note_zc_suppressed_tls();
                } else {
                    conn.append_borrow_segment(op.zc_ptr, op.zc_len, op.zc_shard);
                }
                conn.append_static_segment(kCrlf, sizeof(kCrlf));
                if (op.direct_len) stats_.direct++;
                return;
            }

            // Direct bytes are already in the fill buffer; publishing the length is the whole
            // "copy". A reply that outgrew the region spilled to op.reply -- emit it AFTER the
            // direct part so the RESP stream stays in order.
            if (conn.has_pending_segments()) {
                conn.append_buf_segment(op.direct, op.direct_len,
                                        op.reply.data(), op.reply.size());
                if (op.direct_len) stats_.direct++;
            } else {
                if (op.direct_len) {
                    if constexpr (TrackOutput) conn.commit_fill(op.direct_len);
                    else conn.fill_buf().commit_raw(op.direct_len);
                    stats_.direct++;
                }
                if (!op.reply.empty()) {
                    if constexpr (TrackOutput) conn.append_fill(op.reply.data(), op.reply.size());
                    else conn.fill_buf().append(op.reply.data(), op.reply.size());
                }
            }
        });
        bool did = retired != 0;
        if constexpr (TrackOutput) {
            if (limit_fn_ && limit_fn_(limit_ctx_, c)) {
                stats_.retired += retired;
                if (!retired) stats_.serves_empty++;
                return true;
            }
        }
        if (!conn.nothing_to_write()) did |= pump(c);
        stats_.retired += retired;
        // A serve that retires nothing: the POLLING paths (flush_ready, the backstop) finding
        // nothing, which is expected and cheap.
        if (!retired) stats_.serves_empty++;
        return did;
    }

    template <bool TrackOutput>
    bool serve_tls_impl(Client& c, TlsConn& tls) {
        TOMO_FORENSIC(c.n_serves.fetch_add(1, std::memory_order_relaxed));
        stats_.serves++;
        Client& conn = c;
        if constexpr (TrackOutput) conn.start_obuf_tracking();
        const uint32_t retired = c.rob().drain([&](Op& op) {
            if (op.no_borrow()) note_zc_suppressed_tls();
            if (op.zc_ptr && retire_fn_) retire_fn_(retire_ctx_, conn, op);
            if (op.zc_ptr) {
                conn.seal_fill_segment();
                conn.append_buf_segment(op.direct, op.direct_len,
                                        op.reply.data(), op.reply.size());
                conn.append_buf_segment(op.zc_ptr, op.zc_len);
                conn.append_static_segment(kCrlf, sizeof(kCrlf));
                release(op.zc_shard, op.zc_ptr);
                note_zc_suppressed_tls();
                if (op.direct_len) stats_.direct++;
                return;
            }
            if (conn.has_pending_segments()) {
                conn.append_buf_segment(op.direct, op.direct_len,
                                        op.reply.data(), op.reply.size());
                if (op.direct_len) stats_.direct++;
            } else {
                if (op.direct_len) {
                    if constexpr (TrackOutput) conn.commit_fill(op.direct_len);
                    else conn.fill_buf().commit_raw(op.direct_len);
                    stats_.direct++;
                }
                if (!op.reply.empty()) {
                    if constexpr (TrackOutput) conn.append_fill(op.reply.data(), op.reply.size());
                    else conn.fill_buf().append(op.reply.data(), op.reply.size());
                }
            }
        });
        bool did = retired != 0;
        if constexpr (TrackOutput) {
            if (limit_fn_ && limit_fn_(limit_ctx_, c)) {
                stats_.retired += retired;
                if (!retired) stats_.serves_empty++;
                return true;
            }
        }
        if (!conn.nothing_to_write() || tls.output_pending()) did |= pump_tls(c, tls);
        stats_.retired += retired;
        if (!retired) stats_.serves_empty++;
        return did;
    }
    bool submit_legacy(Client& c, size_t total, size_t sent) {
        static constexpr size_t kMaxSendBytes = 0x7ffff000u;
        const size_t request = std::min(total - sent, kMaxSendBytes);
        io_uring_sqe* s = ring_->sqe();
        if (!s) { stats_.sqe_starved++; return false; }
        io_uring_prep_send(s, c.fd(), c.send_buf().data() + sent, request, MSG_NOSIGNAL);
        s->user_data = ur_tag(UrKind::Send, &c);
        ring_->note_pending();

        c.set_segmented_send(false);
        c.set_send_requested(static_cast<uint32_t>(request));
        c.set_send_inflight(true);
        stats_.sends_submitted++;
        return true;
    }

    bool submit_tls_cipher(Client& c, const char* cipher, uint32_t bytes) {
        io_uring_sqe* s = ring_->sqe();
        if (!s) { stats_.sqe_starved++; return false; }
        io_uring_prep_send(s, c.fd(), cipher, bytes, MSG_NOSIGNAL);
        s->user_data = ur_tag(UrKind::TlsSend, &c);
        ring_->note_pending();
        c.set_send_requested(bytes);
        c.set_send_inflight(true);
        stats_.sends_submitted++;
        return true;
    }

    void release(int32_t shard, const char* ptr) {
        stats_.zc_releases++;
        if (release_fn_) release_fn_(release_ctx_, shard, ptr);
    }

    inline static constexpr char kCrlf[2] = {'\r', '\n'};
    Ring*  ring_ = nullptr;
    void*  release_ctx_ = nullptr;
    ReleaseFn release_fn_ = nullptr;
    void*  retire_ctx_ = nullptr;
    RetireFn retire_fn_ = nullptr;
    const std::atomic<bool>* limit_armed_ = nullptr;
    void*  limit_ctx_ = nullptr;
    LimitFn limit_fn_ = nullptr;
    const uint32_t* cached_now_s_ = nullptr;
    LoopSignals* tls_signals_ = nullptr;
    Stats  stats_;
};

}  // namespace tomo
