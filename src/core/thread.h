// thread.h — one server thread, and the role it is currently playing.
//
// ROLE IS STATE, NOT TYPE. A thread is an IO thread or a worker because of a field, not because of
// its class. That is deliberate: the whole point of the flip controller is that the io:ex split is
// a runtime decision, and the optimal split differs by workload (measured: ~16:1 io:ex at p1,
// scaling as 16:1/depth as pipelining deepens). Encoding the role in the type system would make the
// one thing we most need to change at runtime the one thing we cannot.
//
// WHAT EACH ROLE OWNS
//   Io : a set of connections. Parses, routes, publishes ops, drains ROBs, writes replies.
//   Ex : a set of SHARDS. Consumes ops from its inboxes, executes against its own FlatStore.
//
// Nothing is owned by both. A role change therefore means handing over a set — connections or
// shards — and that is only safe at a quiescence point. The conversion protocol is deliberately not
// implemented yet; the struct is shaped so it can be, and the constraint is written down here
// rather than discovered later:
//
//   TODO(flip): converting Ex -> Io must first drain every inbox and hand its shards to another
//   worker; converting Io -> Ex must first migrate its connections and reach rob.quiesced() on each.
//   A conversion that loses or duplicates a thread breaks pool accounting — that was a real P0 in
//   the fork, where role conversion lost or gained a thread outright.
#pragma once
#include <atomic>
#include <cstdint>
#include <memory>
#include <vector>
#include "shard.h"
#include "../exec/exqueue.h"

namespace tomo {

class Client;

inline constexpr uint32_t kMaxThreads   = 128;
inline constexpr uint32_t kInboxSlots   = 1024;   // per (io, ex) ring

enum class Role : uint8_t { Idle = 0, Io = 1, Ex = 2 };

// What travels through an inbox. A handle rather than a raw Op*: the worker resolves it through the
// client's ROB, so a slot that has been recycled cannot be reached through a stale pointer. The
// client itself cannot be torn down while any op is in flight — that is the quiescence fence.
struct Task {
    Client*  client = nullptr;
    uint64_t op_id  = 0;
};

class ThreadCtx {
public:
    ThreadCtx() = default;
    ThreadCtx(const ThreadCtx&) = delete;
    ThreadCtx& operator=(const ThreadCtx&) = delete;

    // `nthreads` sizes the inbox array. It must be the TOTAL thread count, not the io count: any
    // thread can become an IO thread through a role change, so any thread may produce into this
    // worker's inboxes.
    //
    // MEMORY SCALES AS O(threads^2) AND THAT IS THE COST OF SPSC. Each ring is ~16 KB, so a fixed
    // 128-wide array would be 2.1 MB per thread and ~270 MB at 128 threads — nearly all of it
    // untouched. Sizing to the live thread count instead makes a 16-thread server 256 KB per thread.
    // If we ever run wide enough for this to bite, the fix is a smaller ring, not an MPSC inbox:
    // MPSC costs an atomic RMW per push from every producer, and the fork measured this handoff as
    // instruction volume rather than stalls.
    void init(uint32_t id, Role r, uint32_t nthreads) {
        id_ = id;
        role_.store(r, std::memory_order_relaxed);
        ninbox_ = nthreads;
        inbox_  = std::make_unique<ExQueue<Task, kInboxSlots>[]>(nthreads);
    }

    uint32_t id()   const { return id_; }
    Role     role() const { return role_.load(std::memory_order_acquire); }

    // ---- Ex side -------------------------------------------------------------------------------
    // One inbox per producing IO thread makes every ring genuinely SPSC. The alternative — a single
    // MPSC inbox per worker — costs an atomic RMW per push from every producer, and the fork
    // measured this handoff as instruction volume rather than stalls, so removing the RMW is the
    // direct lever.
    ExQueue<Task, kInboxSlots>& inbox(uint32_t io_thread_id) { return inbox_[io_thread_id]; }
    uint32_t ninbox() const { return ninbox_; }

    std::vector<Shard*>& shards() { return shards_; }

    // ---- Io side -------------------------------------------------------------------------------
    std::vector<Client*>& clients() { return clients_; }

    // ---- both ----------------------------------------------------------------------------------
    struct Stats {
        uint64_t ops_dispatched = 0;   // Io: published to a worker
        uint64_t ops_executed   = 0;   // Ex: taken from an inbox and run
        uint64_t replies_sent   = 0;
        uint64_t queue_full     = 0;   // push() refused; backpressure fired
        uint64_t loop_spins     = 0;
    };
    Stats& stats() { return stats_; }

    std::atomic<bool>& stop_flag() { return stop_; }

private:
    uint32_t          id_ = 0;
    std::atomic<Role> role_{Role::Idle};
    std::atomic<bool> stop_{false};

    // Allocated once at init to the live thread count and never resized, so a role change can
    // never reallocate a queue another thread is pushing into.
    std::unique_ptr<ExQueue<Task, kInboxSlots>[]> inbox_;
    uint32_t ninbox_ = 0;

    std::vector<Shard*>  shards_;    // Ex role
    std::vector<Client*> clients_;   // Io role
    Stats stats_;
};

}  // namespace tomo
