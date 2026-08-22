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
    }
    void clear_blocked() {
        for (uint32_t i = 0; i < nchan_; i++) { task_in_[i].clear_blocked(); client_in_[i].clear_blocked(); }
    }
    bool any_inbound() const {
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
    uint32_t nchan_ = 0;

    std::vector<Shard*>  shards_;
    std::vector<Client*> clients_;
    LoopSignals          sig_;
};

}  // namespace tomo
