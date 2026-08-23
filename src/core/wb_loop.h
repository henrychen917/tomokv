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
// WHAT THIS THREAD OWNS: the ENTIRE reply side of the connections handed to it. It retires the ROB
// in order, stages the bytes, and writes them. It does not parse and does not execute.
//
// That division is the point. If io retired and merely handed bytes over, the only thing moving
// between modes would be the send syscall, and a "3-stage" measured that way would not be
// 3-stage — reply assembly and buffer staging would still be io's work. With the ROB drained here,
// everything after execution leaves the io thread together.
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
                did += serve_ready();
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

            // Mask-independent sweep before parking. The mask is a hint for the hot path; it must
            // not be the only thing that can find queued work, or one lost bit wedges a connection
            // forever. Runs only when this thread has already concluded it has nothing to do.
            if (sweep()) { ring_.submit_and_reap(); continue; }

            Span idle(sig.idle_ns);
            self_->arm_blocked();
            if (!self_->any_inbound()) ring_.submit_and_wait(1);
            else                       ring_.submit_and_reap();
            self_->clear_blocked();
        }
    }

private:
    uint32_t sweep() { return drain_send_requests(true) + serve_ready(); }

    // Identical to the ex-wb sender's mask serve -- 3s differs only in having no execute duty.
    uint32_t serve_ready() {
        uint32_t did = 0;
        for (uint32_t w = 0; w < ReadyMask::kWords; w++) {
            uint64_t bits = self_->ready().take(w);
            while (bits) {
                const uint32_t b = static_cast<uint32_t>(__builtin_ctzll(bits));
                bits &= bits - 1;
                Client* c = self_->wb_slot_client(w * 64 + b);
                if (!c || c->dead()) continue;
                if (c->closing()) { release_owned(c); continue; }
                c->retire_queued().store(false, std::memory_order_release);
                std::atomic_thread_fence(std::memory_order_seq_cst);
                if (wb_.serve(*c, [&] {
                        ThreadCtx& io = srv_->thread(c->ifid_thread());
                        io.post_client(self_->id(), c, ring_, self_->sig());
                    })) did++;
            }
        }
        return did;
    }

    void release_owned(Client* c) {
        self_->release_wb_slot(c->wb_slot());
        c->set_wb_slot(Client::kNoWbSlot);
        // The close request travelled here as a CLAIMED post, and io's release gate requires the
        // claim clear -- leave it set and the free blocks forever. Clearing it is also the last
        // store this thread ever makes through this pointer.
        c->retire_queued().store(false, std::memory_order_release);
    }

    uint32_t drain_send_requests(bool unmasked = false) {
        auto take = [&](Client* c) {
            if (c->closing()) { release_owned(c); return; }       // io asked us to let go
            if (c->wb_slot() == Client::kNoWbSlot)                 // first contact: adopt
                c->set_wb_slot(self_->assign_wb_slot(c));
            // Clear BEFORE serving — see the identical note in ex_loop.h.
            c->retire_queued().store(false, std::memory_order_release);
            c->wb().queued.store(false, std::memory_order_release);
            // THE CLEAR MUST LAND BEFORE THE DRAIN READS, and a release store does not guarantee
            // that. store(release) followed by the loads inside serve() is a StoreLoad pair, the one
            // reordering x86 permits, so the CPU may sink this clear past the drain. The window that
            // opens is precise and fatal: a worker finishes an op, CASes, still sees the flag set,
            // defers without posting; the drain runs before that op is Done and retires nothing; then
            // the clear lands, with no claim outstanding and nobody left to notify. The reply is
            // stranded forever.
            //
            // Found because a diagnostic counter hid it: fetch_add is a LOCKed RMW on x86, i.e. a full
            // fence, so the instrumented build was accidentally correct and the clean one wedged.
            std::atomic_thread_fence(std::memory_order_seq_cst);
            wb_.serve(*c, [&] {
                ThreadCtx& io = srv_->thread(c->ifid_thread());
                io.post_client(self_->id(), c, ring_, self_->sig());
            });
        };
        const uint32_t n = unmasked ? self_->drain_clients_unmasked(take) : self_->drain_clients(take);
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
