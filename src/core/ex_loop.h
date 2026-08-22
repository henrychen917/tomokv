// ex_loop.h — the EX stage. Executes ops against the shards it owns, and in WbMode::Ex also issues
// sends. Same Channel signalling and same LoopSignals units as the IO and WB loops (see signal.h).
//
//   in   task_in from IO threads         a parsed op to execute
//   out  client_in of the owning IO      "you have completed ops to retire"
//   in   client_in from IO threads       "you have bytes to write"      (WbMode::Ex only)
//
// A worker owns no file descriptors when it is only executing, so its "events" are channel entries.
// It still owns a Ring, because in Ex mode it issues sends and because it needs somewhere to receive
// wakes.
//
// WAITING IS THE INTERESTING PART. A worker with an empty inbox must not spin a core at 100% — that
// is a real cost at 64 workers and it distorts every utilisation reading a controller might use. It
// also must not sleep so eagerly that it pays a wakeup per op under load. So: spin briefly, then arm
// the blocked flag, re-check, and block. Producers only pay a wake syscall while that flag is armed.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include "server.h"
#include "signal.h"
#include "../net/conn.h"
#include "../net/uring.h"
#include "../net/wb.h"
#include "../cmd/command.h"

namespace tomo {

// "Long enough to cover an inter-arrival gap, short enough not to burn a core." A starting point to
// measure, not a result.
inline constexpr uint32_t kExSpinBudget = 2048;

// How many ops are gathered before executing, so their storage prefetches can overlap. Large enough
// that the prefetches have time to land, small enough that the batch stays in L1.
inline constexpr uint32_t kExecBatch = 32;

class ExLoop {
public:
    bool init(Server* srv, ThreadCtx* self, WbMode mode) {
        srv_ = srv; self_ = self;
        if (!ring_.init(1024)) return false;
        self_->set_ring(&ring_);
        wb_.bind(&ring_, mode);
        return true;
    }

    Ring& ring() { return ring_; }

    void run() {
        LoopSignals& sig = self_->sig();
        uint32_t idle_spins = 0;

        while (!self_->stop_flag().load(std::memory_order_relaxed)) {
            sig.iterations++;
            self_->sample_depth();

            uint32_t did = 0;
            {
                Span busy(sig.busy_ns);
                did += drain_tasks();
                if (wb_.mode() == WbMode::Ex) did += drain_send_requests();
                did += ring_.for_each_cqe([&](io_uring_cqe* cqe) { on_cqe(cqe); });
            }
            sig.cpu_ns = thread_cpu_ns();

            // Flush prepared SQEs before looping. Recv re-arms and cross-ring wakes are
            // PREPARED during the work section but only reach the kernel on submit; taking
            // the busy path without submitting strands them in the SQ forever, and the peer
            // that is waiting on that wake never runs.
            if (did) { ring_.submit_and_reap(); idle_spins = 0; continue; }

            if (++idle_spins < kExSpinBudget) { sig.spins++; __builtin_ia32_pause(); continue; }
            idle_spins = 0;

            Span idle(sig.idle_ns);
            self_->arm_blocked();
            if (!self_->any_inbound()) ring_.submit_and_wait(1);
            else                       ring_.submit_and_reap();
            self_->clear_blocked();
        }
    }

private:
    // Visits only the IO threads that actually have work for us, via the notify mask, rather than
    // polling every possible producer. retire() happens inside the helper, AFTER execution — see
    // exqueue.h on why the retired frontier is separate from head.
    uint32_t drain_tasks() {
        Task batch[kExecBatch];
        uint32_t held = 0;
        const uint32_t n = self_->drain_tasks([&](const Task& t) {
            batch[held++] = t;
            if (held == kExecBatch) { exec_batch(batch, held); held = 0; }
        });
        if (held) exec_batch(batch, held);
        self_->sig().ops += n;
        return n;
    }

    // Prefetch the whole batch's slots, THEN execute. Issuing the loads up front lets their DRAM
    // round trips overlap instead of each op stalling on its own miss in turn.
    void exec_batch(const Task* batch, uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            const Op& op = batch[i].client->rob().at(batch[i].op_id);
            if (op.shard >= 0) srv_->shard(op.shard).store().prefetch(op.hash);
        }
        for (uint32_t i = 0; i < n; i++) execute(batch[i]);
        // One publish per batch, covering every shard this batch touched. Cheaper than tracking
        // which ones changed, and this thread owns all of them.
        for (Shard* sh : self_->shards()) sh->publish_size();
    }

    void execute(const Task& t) {
        Op& op = t.client->rob().at(t.op_id);
        Shard& sh = srv_->shard(op.shard);
        // Records the op AND whether it was executed from this shard's home L3 domain. One compare
        // and one increment, no atomics — the shard has a single owner.
        sh.note_execution(self_->domain());

        op.spec->handler(sh, op);

        // Release pairs with the IO thread's acquire on Done: everything the handler wrote into
        // op.reply becomes visible through this one store.
        op.state.store(OpState::Done, std::memory_order_release);

        notify_sender(t.client);
    }

    // Tell this client's SENDER it has completed ops. The sender — io in 2-stage, an executor in
    // ex-wb, a write-back thread in 3-stage — is what retires the ROB and writes, so it is what
    // needs waking. Deduplicated: a pipelined burst of N completions on one client must not enqueue
    // that client N times.
    void notify_sender(Client* c) {
        bool expected = false;
        if (!c->retire_queued().compare_exchange_strong(expected, true, std::memory_order_acq_rel))
            return;
        ThreadCtx& snd = srv_->thread(c->sender_thread());
        if (!snd.post_client(self_->id(), c, ring_, self_->sig()))
            c->retire_queued().store(false, std::memory_order_release);   // retry on a later pass
    }

    // WbMode::Ex only: IO staged ordered bytes and handed us the client to write them.
    uint32_t drain_send_requests() {
        return self_->drain_clients([&](Client* c) {
            // Clear BEFORE serving. Clearing after lets a worker that finishes an op mid-serve see
            // queued == true, skip the enqueue, and strand that reply until something unrelated
            // re-queues the client.
            c->retire_queued().store(false, std::memory_order_release);
            c->wb().queued.store(false, std::memory_order_release);
            wb_.serve(*c, [&] {
                ThreadCtx& io = srv_->thread(c->io_thread());
                io.post_client(self_->id(), c, ring_, self_->sig());
            });
        });
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
