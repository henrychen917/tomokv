// wb_loop.h — the dedicated write-back stage (WbMode::Wb, the 3-stage shape). Same Channel
// signalling and same LoopSignals units as the IO and EX loops (see signal.h).
//
//   in   client_in from IO threads      "you have bytes to write"
//
// THIS FILE IS SHORT ON PURPOSE. Every piece of send logic lives in WbEngine, shared with the IO and
// EX loops; a dedicated write-back thread is a scheduling choice, not a different implementation. If
// this file ever grows its own send path, the abstraction has failed and the three modes have
// quietly become three implementations that will drift apart.
//
// WHAT THIS THREAD OWNS: the send side of connections handed to it, and nothing else. It does not
// parse, does not execute, does not touch the ROB. Bytes arrive already ordered in the client's
// write buffer, because the owning IO thread retired them in ROB order before handing the client on.
//
// THE EXPECTED RESULT IS THAT THIS LOSES, and it is built anyway so that is measured rather than
// asserted. p1 throughput is (threads that ISSUE SENDS) x ~90k, so dedicating threads to sending
// buys send width a second time out of a fixed budget instead of getting it free from io threads
// that already receive. The fork also found this shape crashed on a real NIC through a lock
// asymmetry that WbGuard now makes structurally impossible — so it is the mode most worth re-testing
// on the wire.
#pragma once
#include <cstdint>
#include "server.h"
#include "signal.h"
#include "../net/conn.h"
#include "../net/uring.h"
#include "../net/wb.h"

namespace tomo {

inline constexpr uint32_t kWbSpinBudget = 1024;

class WbLoop {
public:
    bool init(Server* srv, ThreadCtx* self) {
        srv_ = srv; self_ = self;
        if (!ring_.init(2048)) return false;
        self_->set_ring(&ring_);
        wb_.bind(&ring_, WbMode::Wb);
        return true;
    }

    Ring&     ring()   { return ring_; }
    WbEngine& engine() { return wb_; }

    void run() {
        LoopSignals& sig = self_->sig();
        uint32_t idle_spins = 0;

        while (!self_->stop_flag().load(std::memory_order_relaxed)) {
            sig.iterations++;
            self_->sample_depth();

            uint32_t did = 0;
            {
                Span busy(sig.busy_ns);
                did += drain_send_requests();
                did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
            }
            sig.cpu_ns = thread_cpu_ns();

            // Flush prepared SQEs before looping. Recv re-arms and cross-ring wakes are
            // PREPARED during the work section but only reach the kernel on submit; taking
            // the busy path without submitting strands them in the SQ forever, and the peer
            // that is waiting on that wake never runs.
            if (did) { ring_.submit_and_reap(); idle_spins = 0; continue; }

            if (++idle_spins < kWbSpinBudget) { sig.spins++; __builtin_ia32_pause(); continue; }
            idle_spins = 0;

            Span idle(sig.idle_ns);
            self_->arm_blocked();
            if (!self_->any_inbound()) ring_.submit_and_wait(1);
            else                       ring_.submit_and_reap();
            self_->clear_blocked();
        }
    }

private:
    uint32_t drain_send_requests() {
        const uint32_t n = self_->drain_clients([&](Client* c) {
            // Clear BEFORE pumping — see the identical note in ex_loop.h. Clearing after strands
            // bytes staged during the pump.
            c->wb().queued.store(false, std::memory_order_release);
            wb_.pump(*c, c->wb());
        });
        self_->sig().ops += n;
        return n;
    }

    void on_cqe(io_uring_cqe* cqe) {
        switch (ur_kind(cqe->user_data)) {
            case UrKind::Send: {
                Client* c = ur_ptr<Client>(cqe->user_data);
                wb_.on_send_complete(*c, c->wb(), cqe->res);
                break;
            }
            case UrKind::Wake: self_->sig().wakes_recv++; break;
            default: break;
        }
    }

    Server*    srv_  = nullptr;
    ThreadCtx* self_ = nullptr;
    Ring       ring_;
    WbEngine   wb_;
};

}  // namespace tomo
