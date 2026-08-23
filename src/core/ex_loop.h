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

// EX-WB'S CLIENT CONTEXT (owner design). In ex-wb the designated executor-sender OWNS the reply
// side of its connections, so it holds them the way redis's client holds its output machinery: a
// per-connection struct binding the Client to its ConnOut, kept in the executor's own list. The
// consequence is that DISCOVERY BECOMES ITERATION: every loop pass the executor walks what it owns
// and serves any connection whose head is ready, instead of waiting for a channel message to tell
// it where to look. The deduped notify stays — but demoted to a park-wake, not the data path.
struct ExClient {
    Client*  c   = nullptr;
    ConnOut* out = nullptr;    // cached: the half this thread owns; saves the hop through Client
};

class ExLoop {
public:
    WbEngine& engine() { return wb_; }
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
                if (wb_.mode() == WbMode::Ex) {
                    did += drain_send_requests();
                    did += serve_ready();
                    // The Law-2 backstop the mask port dropped: every K iterations, walk the OWNED
                    // list and serve by ROB STATE, ignoring the mask entirely. A signal scheme may
                    // be fast; the state is what is true. K trades straggler latency (K iterations,
                    // microseconds busy) against iteration cost; it never runs per op.
                    if (++owned_sweep_tick_ >= kOwnedSweepEvery) {
                        owned_sweep_tick_ = 0;
                        did += sweep_owned_state();
                    }
                }
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
    // Visits only the IO threads that actually have work for us, via the notify mask, rather than
    // polling every possible producer. retire() happens inside the helper, AFTER execution — see
    // exqueue.h on why the retired frontier is separate from head.
    uint32_t drain_tasks(bool unmasked = false) {
        Task batch[kExecBatch];
        uint32_t held = 0;
        auto take = [&](const Task& t) {
            batch[held++] = t;
            if (held == kExecBatch) { exec_batch(batch, held); held = 0; }
        };
        const uint32_t n = unmasked ? self_->drain_tasks_unmasked(take) : self_->drain_tasks(take);
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

        // Both remote-sender modes notify the connection's FIXED sender: the designated executor
        // in ex-wb, the dedicated wb thread in 3s. The claim flag dedupes a burst into one post.
        //
        // OPPORTUNISTIC FLUSH-AT-HEAD (any executor flushes when it completes the head, io sweeps
        // as backstop -- the fork's exwb shape) was built here twice and REVERTED twice, with the
        // interleaved wire A/B as the record: fixed sender 8.1-8.5M get_p32 / 722k get_p1, per-op
        // flush 4.1M, batch-end flush 4.7M with a get_p1 wedge and a crawling SET fill. The fork
        // made that design work with per-client ready-bit machinery this tree does not have yet;
        // without it the head-hint misses constantly and the recovery clock is io's 50ms park.
        // Port the ready-mask first; do not re-attempt this with notifies.
        notify_sender(t.client);
    }



    // Tell this client's SENDER it has completed ops. The sender — io in 2-stage, an executor in
    // ex-wb, a write-back thread in 3-stage — is what retires the ROB and writes, so it is what
    // needs waking. Deduplicated: a pipelined burst of N completions on one client must not enqueue
    // that client N times.
    void notify_sender(Client* c) {
        const uint32_t target = c->sender_thread();
        ThreadCtx& snd = srv_->thread(target);
        // THE READY-MASK PATH (#19/#20 ported): once the sender has assigned this connection a
        // slot, completion signalling is one idempotent bit -- no claim, no channel entry, no
        // pointer in flight. The empty->flagged RMW is the fence; whoever performs it owes the
        // park-wake. A worker completing work for ITS OWN connections sets its own bit and its own
        // serve pass finds it -- no wake needed, the thread is by definition awake.
        const uint32_t slot = c->wb_slot();
        if (slot != Client::kNoWbSlot) {
            // FENCE BEFORE THE READ-FIRST CHECK -- defect 5's exact shape, third appearance. Our
            // caller stored Done; ReadyMask::set() begins with a relaxed LOAD of the word, and TSO
            // lets that load run ahead of the store draining. Unfenced, it can read a stale 1 from
            // a signal the sender is consuming RIGHT NOW: we skip our set, the sender's drain reads
            // our op before the Done lands, and nobody ever signals again. Twelve connections were
            // stranded exactly this way at 4 nodes, where cross-CCD coherence stretches the window.
            std::atomic_thread_fence(std::memory_order_seq_cst);
            if (snd.ready().set(slot) && target != self_->id())
                snd.wake_if_parked(ring_, self_->sig());
            return;
        }
        // No slot yet: first contact. For OUR OWN connection we adopt right here -- the channel post
        // exists to carry the pointer across threads, and there is no gap to cross. For someone
        // else's, the claimed post carries it to them; they adopt on receipt. Either way this path
        // runs once per connection.
        if (target == self_->id()) { adopt(c); snd.ready().set(c->wb_slot()); return; }
        notify_sender_to(c, target);
    }

    void notify_sender_to(Client* c, uint32_t target) {
        bool expected = false;
        if (!c->retire_queued().compare_exchange_strong(expected, true, std::memory_order_acq_rel)) {
            TOMO_FORENSIC(c->wb().n_defers.fetch_add(1, std::memory_order_relaxed));
            return;
        }
        TOMO_FORENSIC(c->wb().n_claims.fetch_add(1, std::memory_order_relaxed));
        ThreadCtx& snd = srv_->thread(target);
        if (!snd.post_client(self_->id(), c, ring_, self_->sig())) {
            self_->sig().notify_drop++;
            c->retire_queued().store(false, std::memory_order_release);   // retry on a later pass
        }
    }

    // Mask-driven serve: exactly the slots workers flagged, instead of iterating every owned
    // connection. Take-then-serve; the serve sequence stays clear+fence+serve (defect-5 StoreLoad
    // discipline) because a mask-serve races the same workers a channel-serve did.
    uint32_t serve_ready() {
        uint32_t did = 0;
        for (uint32_t w = 0; w < ReadyMask::kWords; w++) {
            uint64_t bits = self_->ready().take(w);
            while (bits) {
                const uint32_t b = static_cast<uint32_t>(__builtin_ctzll(bits));
                bits &= bits - 1;
                Client* c = self_->wb_slot_client(w * 64 + b);
                if (!c || c->dead()) continue;
                // A closing conn is released only once DRAINED -- until then it must be SERVED like
                // any other, or its in-flight replies never retire and io waits on a quiesce that
                // cannot come. (Same rule as io's budget FIFO: only corpses are skippable.)
                if (c->closing() && c->rob().quiesced() && c->out().nothing_to_write()) {
                    release_owned(c); continue;
                }
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

    void adopt(Client* c) {
        c->set_ex_adopted(true);
        owned_.push_back(ExClient{c, &c->out()});
        c->set_wb_slot(self_->assign_wb_slot(c));
    }

    // Serve every owned connection whose ROB HEAD is retirable, straight from state. This is what
    // catches a lost mask signal; it must exist for the mask to be allowed its fast path.
    uint32_t sweep_owned_state() {
        uint32_t did = 0;
        for (size_t i = 0; i < owned_.size(); i++) {
            Client* c = owned_[i].c;
            if (!c || c->dead() || c->closing()) continue;
            Rob<kRobWindow>& rob = owned_[i].out->rob();
            if (rob.quiesced()) continue;
            if (rob.at(rob.flush_id()).state.load(std::memory_order_acquire) != OpState::Done)
                continue;
            c->retire_queued().store(false, std::memory_order_release);
            std::atomic_thread_fence(std::memory_order_seq_cst);
            if (wb_.serve(*c, [&] {
                    ThreadCtx& io = srv_->thread(c->ifid_thread());
                    io.post_client(self_->id(), c, ring_, self_->sig());
                })) did++;
        }
        return did;
    }

    // The sender's half of the teardown handshake. io refuses to free while our slot still maps a
    // bit to this pointer; we let go the moment we see closing, and the store of kNoWbSlot is the
    // release io is waiting on. After this we never touch the client again.
    void release_owned(Client* c) {
        self_->release_wb_slot(c->wb_slot());
        c->set_wb_slot(Client::kNoWbSlot);
        // The close request travelled here as a CLAIMED post, and io's release gate requires the
        // claim clear -- leave it set and the free blocks forever. Clearing it is also the last
        // store this thread ever makes through this pointer.
        c->retire_queued().store(false, std::memory_order_release);
        c->set_ex_adopted(false);
        for (size_t i = 0; i < owned_.size(); i++)
            if (owned_[i].c == c) { owned_[i] = owned_.back(); owned_.pop_back(); break; }
    }

    // WbMode::Ex only: IO staged ordered bytes and handed us the client to write them.
    // Both inbound kinds, ignoring the mask entirely.
    uint32_t sweep() { return drain_tasks(true) + drain_send_requests(true) + serve_ready(); }

    uint32_t drain_send_requests(bool unmasked = false) {
        auto take = [&](Client* c) {
            // First contact from a connection assigned to us: adopt -- assign a ready-mask slot so
            // every later completion is one bit instead of a channel entry.
            if (wb_.mode() == WbMode::Ex) {
                if (c->closing() && c->rob().quiesced() && c->out().nothing_to_write()) {
                    release_owned(c); return;              // io asked us to let go, and it is drained
                }
                if (!c->closing() && !c->ex_adopted()) adopt(c);
            }
            // Clear BEFORE serving. Clearing after lets a worker that finishes an op mid-serve see
            // queued == true, skip the enqueue, and strand that reply until something unrelated
            // re-queues the client.
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
        return unmasked ? self_->drain_clients_unmasked(take) : self_->drain_clients(take);
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
    std::vector<ExClient> owned_;      // ex-wb: the connections whose reply side this thread owns
    static constexpr uint32_t kOwnedSweepEvery = 64;
    uint32_t owned_sweep_tick_ = 0;
};

}  // namespace tomo
