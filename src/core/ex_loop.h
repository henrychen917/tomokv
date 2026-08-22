// ex_loop.h — the EX stage. Consumes ops from its inboxes and executes them against the shards it
// owns. In WbMode::Ex it also issues sends.
//
// NO EVENT LOOP IN THE USUAL SENSE when it is only executing: a worker has no file descriptors of
// its own, so its "events" are inbox entries. It still owns a Ring, because in Ex mode it issues
// sends, and because it needs somewhere to receive cross-thread wakes.
//
// WAITING IS THE INTERESTING PART. A worker with an empty inbox must not spin a core at 100% — that
// is a real cost at 64 workers, and it also blinds any controller reading CPU to decide the io:ex
// split. It also must not sleep so eagerly that it pays a wakeup per op under load. So: spin briefly
// (cheap, covers the common case where the next op is microseconds away), then block on the ring and
// let a producer's msg_ring wake it.
#pragma once
#include <cstdint>
#include "server.h"
#include "../net/conn.h"
#include "../net/uring.h"
#include "../net/wb.h"
#include "../cmd/command.h"

namespace tomo {

// Tuned to "long enough to cover an inter-arrival gap, short enough not to burn a core". A real
// number needs measurement; this is a starting point, not a result.
inline constexpr uint32_t kExSpinBudget = 2048;

class ExLoop {
public:
    bool init(Server* srv, ThreadCtx* self, WbMode mode) {
        srv_ = srv; self_ = self;
        if (!ring_.init(1024)) return false;
        wb_.bind(&ring_, mode);
        return true;
    }

    Ring&       ring()     { return ring_; }
    ReadyQueue& ready_q()  { return ready_; }

    void run() {
        uint32_t idle = 0;
        while (!self_->stop_flag().load(std::memory_order_relaxed)) {
            uint32_t did = drain_inboxes();

            if (wb_.mode() == WbMode::Ex) did += drain_ready();

            // Completions only matter in Ex mode (our own sends) and for wakes.
            ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });

            if (did) { idle = 0; continue; }
            if (++idle < kExSpinBudget) { __builtin_ia32_pause(); continue; }

            // Nothing to do: publish anything queued and block until someone wakes us.
            idle = 0;
            ring_.submit_and_wait(1);
            ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
        }
    }

private:
    uint32_t drain_inboxes() {
        uint32_t n = 0;
        // Round-robin across producers so one busy IO thread cannot starve the others. Starting
        // where we left off rather than at 0 is what makes it fair.
        const uint32_t nin = self_->ninbox();
        for (uint32_t k = 0; k < nin; k++) {
            const uint32_t src = (rr_ + k) % nin;
            auto& q = self_->inbox(src);
            Task t;
            while (q.pop(t)) {
                execute(t);
                q.retire();                    // AFTER execution — see exqueue.h on why this exists
                n++;
                self_->stats().ops_executed++;
            }
        }
        rr_ = (rr_ + 1) % (nin ? nin : 1);
        return n;
    }

    void execute(const Task& t) {
        Op& op = t.client->rob().at(t.op_id);
        Shard& sh = srv_->shard(op.shard);
        sh.stats().ops++;

        op.spec->handler(sh, op);

        // Release: everything the handler wrote into op.reply must be visible to the IO thread that
        // observes Done with an acquire load. This single pair orders the whole handoff back.
        op.state.store(OpState::Done, std::memory_order_release);

        // Wake the owning IO thread. Without this it can sit blocked in submit_and_wait with a
        // completed op nobody will ever retire — the loop has no other reason to run.
        wake_io(t.client->io_thread());
    }

    void wake_io(uint32_t io_thread_id) {
        if (io_thread_id == last_woken_ && ++coalesced_ < 32) return;   // coalesce a burst
        last_woken_ = io_thread_id;
        coalesced_  = 0;
        if (Ring* r = io_rings_ ? io_rings_[io_thread_id] : nullptr)
            ring_.msg_to(*r, ur_tag(UrKind::Wake, nullptr));
    }

    uint32_t drain_ready() {
        uint32_t n = 0;
        Client* c = nullptr;
        while (ready_.pop(c)) {
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

public:
    // Set by the server after every loop exists, so a worker can wake the IO thread that owns a
    // client. An array indexed by thread id rather than a lookup on the hot path.
    void set_io_rings(Ring** rings) { io_rings_ = rings; }

private:
    Server*    srv_  = nullptr;
    ThreadCtx* self_ = nullptr;
    Ring       ring_;
    WbEngine   wb_;
    ReadyQueue ready_;                 // used only in WbMode::Ex
    Ring**     io_rings_ = nullptr;
    uint32_t   rr_ = 0;
    uint32_t   last_woken_ = UINT32_MAX;
    uint32_t   coalesced_ = 0;
};

}  // namespace tomo
