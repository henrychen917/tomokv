// shutdown_report.h — the end-of-run accounting both boot modes print. One home, so the split
// (main.cc) and fused (genthread.cc) paths cannot drift again: the fused path used to print no
// per-thread, wb, tls or epoll evidence at all, and the two copies of the `stuck:` walk had
// already diverged in spelling.
//
// Everything here runs after every loop thread has been joined: LoopSignals, WbEngine::Stats and
// the per-thread client lists are read with no writer alive, and every Client still present in
// clients() is a live object (reap_dead() runs on each loop's exit path before it returns).
//
// The `stuck:` line is asserted verbatim by tests/gate.sh
// ("stuck: live_conns=0 rob_not_quiesced=0 unsent_bytes_pending=0"); do not reword it.
#pragma once

#include <atomic>
#include <cstdint>
#include <cstdio>

#include "server.h"

namespace tomo {

// Per-thread breakdown. The aggregate hides the thing you actually need: whether a stage is
// saturated, starved, or spending its life in the kernel waiting to be told there is work.
inline void shutdown_report_threads(Server& srv) {
    const bool fused = srv.thread_mode() == ThreadMode::Fused;
    std::printf("\n%-6s %-4s %12s %10s %9s %9s %9s %9s %8s\n",
                "thread", "role", "ops", "iters", "busy_ms", "idle_ms", "cpu_ms", "wake_tx",
                "wake_rx");
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        const LoopSignals& s = srv.thread(i).sig();
        const Role r = srv.thread(i).role();
        const char* role = fused ? "uni" : r == Role::Ifid ? "io" : r == Role::Ex ? "ex" : "idle";
        std::printf("t%-5u %-4s %12llu %10llu %9.1f %9.1f %9.1f %9llu %8llu\n", i, role,
                    static_cast<unsigned long long>(s.ops),
                    static_cast<unsigned long long>(s.iterations),
                    s.busy_ns / 1e6, s.idle_ns / 1e6, s.cpu_ns / 1e6,
                    static_cast<unsigned long long>(s.wakes_sent),
                    static_cast<unsigned long long>(s.wakes_recv));
    }
}

// Folds one loop family's WbEngine stats into `w`. Called once per loop vector (io and ex, or io
// and fused executors); both loop types expose engine().stats().
template <class Loops>
inline void shutdown_accumulate_wb(WbEngine::Stats& w, Loops& loops) {
    for (auto& loop : loops) {
        const WbEngine::Stats& x = loop.engine().stats();
        w.sends_submitted += x.sends_submitted; w.sends_completed += x.sends_completed;
        w.short_writes    += x.short_writes;    w.send_errors     += x.send_errors;
        w.peer_aborts     += x.peer_aborts;
        w.bytes_sent      += x.bytes_sent;      w.retired         += x.retired;
        w.direct          += x.direct;
        w.zc_sends        += x.zc_sends;        w.zc_bytes        += x.zc_bytes;
        w.zc_releases     += x.zc_releases;
        w.serves          += x.serves;          w.serves_empty    += x.serves_empty;
    }
}

// WHERE DID THE REPLIES GO. dispatched==executed only proves the STORE finished its work; it
// says nothing about whether the answer reached the socket. These levels localise a stall to one
// hop: retired < executed means replies are stranded in the ROB (the sender was never told).
// retired == executed with bytes_sent short means they are staged but unsent (the pump was never
// re-triggered). Both looked identical from outside before this existed.
inline void shutdown_report_wb(const WbEngine::Stats& w) {
    std::printf("wb: retired=%llu direct=%llu sends=%llu/%llu short=%llu err=%llu"
                " peer_aborts=%llu bytes=%llu"
                " zc_sends=%llu zc_bytes=%llu zc_releases=%llu serves=%llu empty=%llu\n",
                static_cast<unsigned long long>(w.retired),
                static_cast<unsigned long long>(w.direct),
                static_cast<unsigned long long>(w.sends_completed),
                static_cast<unsigned long long>(w.sends_submitted),
                static_cast<unsigned long long>(w.short_writes),
                static_cast<unsigned long long>(w.send_errors),
                static_cast<unsigned long long>(w.peer_aborts),
                static_cast<unsigned long long>(w.bytes_sent),
                static_cast<unsigned long long>(w.zc_sends),
                static_cast<unsigned long long>(w.zc_bytes),
                static_cast<unsigned long long>(w.zc_releases),
                static_cast<unsigned long long>(w.serves),
                static_cast<unsigned long long>(w.serves_empty));
}

inline void shutdown_report_tls(Server& srv) {
    uint64_t accepts = 0, started = 0, completed = 0, failed = 0, freed = 0, want_read = 0,
             want_write = 0, cipher_in = 0, plain_in = 0, cipher_out = 0, plain_out = 0,
             zc_suppressed = 0, ktls_active = 0, ktls_fallback = 0;
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        const LoopSignals& s = srv.thread(i).sig();
        accepts += s.tls_accepts;
        started += s.tls_handshakes_started;
        completed += s.tls_handshakes_completed;
        failed += s.tls_handshakes_failed;
        freed += s.tls_connections_freed;
        want_read += s.tls_want_read;
        want_write += s.tls_want_write;
        cipher_in += s.tls_ciphertext_input_bytes;
        plain_in += s.tls_plaintext_input_bytes;
        cipher_out += s.tls_ciphertext_output_bytes;
        plain_out += s.tls_plaintext_output_bytes;
        zc_suppressed += s.tls_zc_suppressed;
        ktls_active += s.tls_ktls_active;
        ktls_fallback += s.tls_ktls_fallback;
    }
    std::printf("tls: accepts=%llu handshakes=%llu/%llu failed=%llu freed=%llu"
                " want_read=%llu want_write=%llu cipher_in=%llu plain_in=%llu"
                " cipher_out=%llu plain_out=%llu zc_suppressed=%llu"
                " ktls_active=%llu ktls_fallback=%llu\n",
                static_cast<unsigned long long>(accepts),
                static_cast<unsigned long long>(completed),
                static_cast<unsigned long long>(started),
                static_cast<unsigned long long>(failed),
                static_cast<unsigned long long>(freed),
                static_cast<unsigned long long>(want_read),
                static_cast<unsigned long long>(want_write),
                static_cast<unsigned long long>(cipher_in),
                static_cast<unsigned long long>(plain_in),
                static_cast<unsigned long long>(cipher_out),
                static_cast<unsigned long long>(plain_out),
                static_cast<unsigned long long>(zc_suppressed),
                static_cast<unsigned long long>(ktls_active),
                static_cast<unsigned long long>(ktls_fallback));
}

// And the smoking gun: connections still holding work at shutdown, by WHICH kind.
inline void shutdown_report_stuck(Server& srv) {
    uint64_t stuck_rob = 0, stuck_wr = 0, live = 0;
    uint64_t st_done = 0, st_issued = 0, st_free = 0, st_flag = 0;
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        for (Client* c : srv.thread(i).clients()) {
            if (!c) continue;
            live++;
            if (!c->rob().quiesced()) {
                stuck_rob++;
                // THE DEDUP FLAG ON A STRANDED CLIENT. retire_queued is the whole notification
                // protocol: a worker claims the client by CASing it false->true and then posts it
                // to the sender, and the sender clears it before serving. So on a client whose
                // replies are Done and unretired there are exactly two stories, and this bit tells
                // them apart:
                //   true  -> someone claimed it and the post never took effect (claim leaked)
                //   false -> nobody was holding a claim, so the notification was simply never made
                if (c->retire_queued().load(std::memory_order_acquire)) st_flag++;
#ifdef TOMO_WEDGE_FORENSICS
                std::printf("  stranded conn: claims=%u defers=%u serves=%u inflight=%u flag=%d\n",
                            c->n_claims.load(std::memory_order_relaxed),
                            c->n_defers.load(std::memory_order_relaxed),
                            c->n_serves.load(std::memory_order_relaxed),
                            c->rob().in_flight(),
                            static_cast<int>(c->retire_queued().load(std::memory_order_acquire)));
#endif
                // WHICH KIND OF STRANDED. The counts above prove ops were dispatched and never
                // retired; they cannot say why. The state of each un-retired slot does:
                //   Done   -> it executed and the sender was never told  (a lost-notification bug)
                //   Issued -> it never executed at all                   (a lost-dispatch bug)
                // Those need opposite fixes, so guessing between them is how you fix the wrong one.
                for (uint64_t id = c->rob().flush_id(), end = c->rob().dispatch_id(); id != end;
                     id++) {
                    switch (c->rob().at(id).state.load(std::memory_order_acquire)) {
                        case OpState::Done:   st_done++;   break;
                        case OpState::Issued: st_issued++; break;
                        default:              st_free++;   break;
                    }
                }
            }
            if (!c->nothing_to_write()) stuck_wr++;
        }
    }
    std::printf("stuck: live_conns=%llu rob_not_quiesced=%llu unsent_bytes_pending=%llu"
                " | slots done=%llu issued=%llu free=%llu flag_set=%llu\n",
                static_cast<unsigned long long>(live),
                static_cast<unsigned long long>(stuck_rob),
                static_cast<unsigned long long>(stuck_wr),
                static_cast<unsigned long long>(st_done),
                static_cast<unsigned long long>(st_issued),
                static_cast<unsigned long long>(st_free),
                static_cast<unsigned long long>(st_flag));
}

inline void shutdown_report_epoll(Server& srv) {
    if (srv.cfg().net_io != NetIoEngine::Epoll) return;
    uint64_t events = 0, recvs = 0;
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        events += srv.thread(i).sig().epoll_events;
        recvs += srv.thread(i).sig().epoll_recvs;
    }
    std::printf("epoll: events=%llu recvs=%llu\n", static_cast<unsigned long long>(events),
                static_cast<unsigned long long>(recvs));
}

// Accept/wake totals for the final `shutdown:` line; each mode adds its own work counters.
struct ShutdownTotals {
    uint64_t accepts = 0, accept_err = 0, accept_rearm = 0, sqe_starved = 0, notify_drop = 0;
};

inline ShutdownTotals shutdown_totals(Server& srv) {
    ShutdownTotals t;
    for (uint32_t i = 0; i < srv.nthreads(); i++) {
        const LoopSignals& s = srv.thread(i).sig();
        t.accepts += s.accepts;
        t.accept_err += s.accept_err;
        t.accept_rearm += s.accept_rearm;
        t.sqe_starved += s.sqe_starved;
        t.notify_drop += s.notify_drop;
    }
    return t;
}

}  // namespace tomo
