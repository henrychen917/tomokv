// wb_loop.h — the dedicated write-back stage (WbMode::Wb, the 3-stage shape).
//
// THIS FILE IS SHORT ON PURPOSE. Every piece of send logic lives in WbEngine, shared with the IO and
// EX loops; a dedicated write-back thread is a scheduling choice, not a different implementation. If
// this file ever starts growing its own send path, the abstraction has failed and the three modes
// have quietly become three implementations that will drift apart.
//
// WHAT THIS THREAD OWNS: the send side of connections it is handed, and nothing else. It does not
// parse, does not execute, does not touch the ROB. Bytes arrive already ordered in the client's
// write buffer — the owning IO thread retired them in ROB order before handing the client over.
//
// THE EXPECTED RESULT IS THAT THIS LOSES, and it is built anyway so that is measured rather than
// asserted. p1 throughput is (threads that ISSUE SENDS) x ~90k, so moving sends onto dedicated
// threads buys send width a second time out of a fixed budget instead of getting it free from io
// threads that already receive. The fork also found this shape crashed on a real NIC through the
// lock asymmetry that WbGuard now makes structurally impossible — so this is the mode most worth
// re-testing on the wire.
#pragma once
#include <cstdint>
#include "server.h"
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
        wb_.bind(&ring_, WbMode::Wb);
        return true;
    }

    Ring&       ring()    { return ring_; }
    ReadyQueue& ready_q() { return ready_; }
    WbEngine&   engine()  { return wb_; }

    void run() {
        uint32_t idle = 0;
        while (!self_->stop_flag().load(std::memory_order_relaxed)) {
            uint32_t did = drain_ready();

            ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });

            if (did) { idle = 0; continue; }
            if (++idle < kWbSpinBudget) { __builtin_ia32_pause(); continue; }
            idle = 0;
            ring_.submit_and_wait(1);
            ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
        }
    }

private:
    uint32_t drain_ready() {
        uint32_t n = 0;
        Client* c = nullptr;
        while (ready_.pop(c)) {
            // Clear `queued` BEFORE pumping. If it were cleared after, a producer staging more bytes
            // during the pump would see queued == true, skip the enqueue, and those bytes would sit
            // unsent until some unrelated event happened to re-queue the client — a stall that only
            // appears under load and looks like a lost reply.
            c->wb().queued.store(false, std::memory_order_release);
            wb_.pump(*c, c->wb());
            n++;
        }
        return n;
    }

    void on_cqe(io_uring_cqe* cqe) {
        if (ur_kind(cqe->user_data) == UrKind::Send) {
            Client* c = ur_ptr<Client>(cqe->user_data);
            wb_.on_send_complete(*c, c->wb(), cqe->res);
        }
    }

    Server*    srv_  = nullptr;
    ThreadCtx* self_ = nullptr;
    Ring       ring_;
    WbEngine   wb_;
    ReadyQueue ready_;
};

}  // namespace tomo
