// thread.h — one server thread, the role it is currently playing, and its inbound channels.
//
// ROLE IS STATE, NOT TYPE. A thread is an IO thread or a worker because of a field, not because of
// its class. That is deliberate: the io:ex split is a runtime decision and the optimal split differs
// by workload (measured: ~16:1 io:ex at p1, scaling as 16:1/depth as pipelining deepens). Encoding
// the role in the type system would make the one thing we most need to change at runtime the one
// thing we cannot.
//
// EVERY THREAD HAS THE SAME TWO INBOUND CHANNELS, whatever its role. What arrives on them differs;
// their shape, units and wake semantics do not. That uniformity is what lets a flip/LB controller
// read all three loops through one interface instead of special-casing each:
//
//   task_in_[p]     from producer p    IO -> EX   a parsed op to execute
//   client_in_[p]   from producer p    EX -> IO   "you have completed ops to retire"
//                                      IO -> EX   "you have bytes to send"      (WbMode::Ex)
//                                      IO -> WB   "you have bytes to send"      (WbMode::Wb)
//
// client_in_ is unambiguous despite serving three directions, because a thread has exactly one role
// at a time: an IO thread's client_in_ is always retire-work, a WB thread's is always send-work.
//
// One channel PER PRODUCER, which is what keeps each ring genuinely SPSC. The alternative is one
// MPSC inbox per consumer, costing an atomic RMW per push from every producer; the fork measured
// this handoff as instruction volume rather than stalls, so removing the RMW is the direct lever.
//
//   TODO(flip): converting Ex -> Io must first drain every inbox and hand its shards to another
//   worker; converting Io -> Ex must first migrate its connections and reach rob.quiesced() on each.
//   A conversion that loses or duplicates a thread breaks pool accounting — a real P0 in the fork.
#pragma once
#include <atomic>
#include <cstdint>
#include <memory>
#include <vector>
#include "shard.h"
#include "signal.h"
#include "../base/topology.h"

namespace tomo {

class Client;
class Ring;

inline constexpr uint32_t kMaxThreads = 128;
inline constexpr uint32_t kInboxSlots = 1024;

enum class Role : uint8_t { Idle = 0, Io = 1, Ex = 2, Wb = 3 };

// What travels on task_in_. A handle rather than a raw Op*: the worker resolves it through the
// client's ROB, so a recycled slot cannot be reached through a stale pointer. The client itself
// cannot be torn down while any op is in flight — that is the quiescence fence.
struct Task {
    Client*  client = nullptr;
    uint64_t op_id  = 0;
};

using TaskChan   = Channel<Task, kInboxSlots>;
using ClientChan = Channel<Client*, kInboxSlots>;

class ThreadCtx {
public:
    ThreadCtx() = default;
    ThreadCtx(const ThreadCtx&) = delete;
    ThreadCtx& operator=(const ThreadCtx&) = delete;

    // `nthreads` is the TOTAL thread count, not the io count: any thread can become a producer
    // through a role change. Sized to the live count rather than kMaxThreads — a fixed 128-wide
    // array would be megabytes per thread, nearly all of it untouched.
    void init(uint32_t id, Role r, uint32_t nthreads) {
        id_ = id;
        role_.store(r, std::memory_order_relaxed);
        nchan_     = nthreads;
        task_in_   = std::make_unique<TaskChan[]>(nthreads);
        client_in_ = std::make_unique<ClientChan[]>(nthreads);
    }

    uint32_t id()   const { return id_; }
    Role     role() const { return role_.load(std::memory_order_acquire); }
    uint32_t nchan() const { return nchan_; }

    // Where this thread actually runs. Latched once the thread is pinned and running, because
    // sched_getcpu() before that answers about the wrong cpu. A worker passes domain() to
    // Shard::note_execution so the shard can tell local work from foreign work; that ratio is the
    // signal a later flip/LB controller acts on.
    void latch_placement(const Topology& topo) {
        cpu_    = sched_getcpu();
        domain_ = topo.domain_of(cpu_);
    }
    int      cpu()    const { return cpu_; }
    uint32_t domain() const { return domain_; }

    TaskChan&   task_in(uint32_t producer)   { return task_in_[producer]; }
    ClientChan& client_in(uint32_t producer) { return client_in_[producer]; }

    // ---- posting (producer side) ---------------------------------------------------------------
    // Push AND flag, in that order. Flagging before the push would let the consumer take the bit,
    // find an empty queue, and clear it while the item is still in flight.
    bool post_task(uint32_t from, const Task& t, Ring& my_ring, LoopSignals& sig) {
        if (!task_in_[from].push(t, sig)) return false;
        // Publish the bit FIRST, wake only if we are the producer that raised it. Order matters more
        // than it looks -- see Channel::push/wake.
        if (task_notify_.set(from)) task_in_[from].wake(my_ring, sig, ring());
        return true;
    }
    bool post_client(uint32_t from, Client* c, Ring& my_ring, LoopSignals& sig) {
        if (!client_in_[from].push(c, sig)) return false;
        if (client_notify_.set(from)) client_in_[from].wake(my_ring, sig, ring());
        return true;
    }

    // ---- draining (consumer side) ---------------------------------------------------------------
    // Visits only FLAGGED producers, so cost tracks active producers rather than possible ones. The
    // bits are TAKEN before the channels are drained -- see NotifyMask on why the reverse order
    // loses a push that lands mid-drain.
    template <typename Fn>
    uint32_t drain_tasks(Fn&& fn) {
        uint32_t n = 0;
        for (uint32_t w = 0; w < NotifyMask::kWords; w++) {
            uint64_t bits = task_notify_.take(w);
            while (bits) {
                const uint32_t b = static_cast<uint32_t>(__builtin_ctzll(bits));
                bits &= bits - 1;
                const uint32_t p = w * 64 + b;
                if (p >= nchan_) continue;
                Task t;
                while (task_in_[p].recv(t)) { fn(t); task_in_[p].retire(); n++; }
            }
        }
        return n;
    }

    template <typename Fn>
    uint32_t drain_clients(Fn&& fn) {
        uint32_t n = 0;
        for (uint32_t w = 0; w < NotifyMask::kWords; w++) {
            uint64_t bits = client_notify_.take(w);
            while (bits) {
                const uint32_t b = static_cast<uint32_t>(__builtin_ctzll(bits));
                bits &= bits - 1;
                const uint32_t p = w * 64 + b;
                if (p >= nchan_) continue;
                Client* c = nullptr;
                while (client_in_[p].recv(c)) { fn(c); client_in_[p].retire(); n++; }
            }
        }
        return n;
    }

    // The ring peers poke to wake this thread. Published once at startup, read by producers.
    void  set_ring(Ring* r) { ring_.store(r, std::memory_order_release); }
    Ring* ring() const      { return ring_.load(std::memory_order_acquire); }

    std::vector<Shard*>&  shards()  { return shards_; }    // Ex role
    std::vector<Client*>& clients() { return clients_; }   // Io role

    // The single reporting surface. Every loop fills the same fields in the same units, so a
    // controller compares like with like — the failure mode behind every balancer defect in the
    // fork was comparing two quantities that were not the same kind of thing.
    LoopSignals& sig() { return sig_; }

    // Sample inbound pressure. Called once per loop iteration so depth_sum/depth_samples form a
    // time-average rather than a spot reading, which is too noisy to control on.
    void sample_depth() {
        uint64_t d = 0;
        for (uint32_t i = 0; i < nchan_; i++) d += task_in_[i].depth() + client_in_[i].depth();
        sig_.depth_sum += d;
        sig_.depth_samples++;
    }

    // Arm/disarm every inbound channel around a block. Producers only pay a wake syscall while
    // these are armed. ALWAYS re-check the channels after arming and before actually blocking:
    // a producer that pushed just before the flag was set would not have woken us.
    void arm_blocked() {
        for (uint32_t i = 0; i < nchan_; i++) { task_in_[i].arm_blocked(); client_in_[i].arm_blocked(); }
        // The other half of the Dekker pair. Declaring intent to block is a store; the any_inbound()
        // that follows is a load of a different location. Without this fence the CPU may hoist that
        // load above the store, and a producer that ran in between sees blocked_ == false while we
        // see an empty mask. Sleep path only -- it costs nothing where it runs.
        std::atomic_thread_fence(std::memory_order_seq_cst);
    }
    void clear_blocked() {
        for (uint32_t i = 0; i < nchan_; i++) { task_in_[i].clear_blocked(); client_in_[i].clear_blocked(); }
    }
    // Two loads instead of a scan of every channel. Used to re-check after arming the blocked flag.
    // Asked ONLY on the way to sleep, which is why it can afford to be thorough. The mask is the fast
    // "where do I look" hint for the drain path; here we also look at the queues themselves, because
    // the queue push is the release store the blocked_ protocol was designed to pair with. Checking
    // both means no reasoning about mask staleness can cost us a wakeup -- and a scan of a handful of
    // channels is free for a thread that by definition has nothing else to do.
    bool any_inbound() const {
        if (task_notify_.any() || client_notify_.any()) return true;
        for (uint32_t i = 0; i < nchan_; i++)
            if (task_in_[i].depth() || client_in_[i].depth()) return true;
        return false;
    }

    std::atomic<bool>& stop_flag() { return stop_; }

private:
    uint32_t          id_ = 0;
    std::atomic<Role> role_{Role::Idle};
    std::atomic<bool> stop_{false};
    std::atomic<Ring*> ring_{nullptr};

    int      cpu_    = -1;
    uint32_t domain_ = kNoDomain;

    std::unique_ptr<TaskChan[]>   task_in_;
    std::unique_ptr<ClientChan[]> client_in_;
    NotifyMask task_notify_;      // "which producers have ops for me"
    NotifyMask client_notify_;    // "which producers have clients for me"
    uint32_t nchan_ = 0;

    std::vector<Shard*>  shards_;
    std::vector<Client*> clients_;
    LoopSignals          sig_;
};

}  // namespace tomo
