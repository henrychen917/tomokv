// server.h — process-wide shared state. Everything here is either immutable after boot or
// explicitly synchronised; nothing in it is written on the hot path.
//
// THAT IS THE RULE, and it is worth stating because it is easy to violate by accident. A counter
// bumped per command from a struct every thread shares is a shared-line write on the hot path, and
// at this thread count it shows up immediately. Per-command counters live in Shard::Stats or
// LoopSignals, both single-writer; INFO sums them on request.
//
// THE ONE MUTABLE HOT-PATH STRUCTURE is shard_owner_: shard id -> thread id, one atomic load per
// dispatch. That indirection is deliberate and it is what makes pointer-handoff load balancing
// possible later — an LB moves a shard by storing a different thread id, with no data movement and
// no change to routing. See placement.h for the ordering contract that makes such a move safe.
#pragma once
#include <atomic>
#include <cstdint>
#include <memory>
#include <vector>
#include "shard.h"
#include "thread.h"
#include "placement.h"
#include "../base/topology.h"
#include "../net/conn.h"   // kRobWindow: one source of truth for the window size
#include "../net/wb.h"     // WbMode

namespace tomo {

struct Config {
    // Legacy sugar is per node: --nodes 2 --spread 4:4 lowers to eight ifid and eight ex entries in
    // the same per-thread placement table that --place builds directly.
    uint32_t ifid_per_node    = 4;
    uint32_t ex_per_node    = 4;
    // Only used by WbMode::Wb (the 3-stage shape). Zero for 2s and ex-wb, where the sends are issued
    // by a thread that already exists.
    uint32_t wb_per_node    = 0;
    WbMode   wb_mode        = WbMode::Io;
    // 0 means "one node per L3 domain", which is the measured optimum and therefore the default
    // rather than something an operator has to know to ask for.
    uint32_t nodes          = 0;
    const char* node_cpus   = nullptr;   // operator-declared topology; null = self-discover
    const char* place       = nullptr;   // complete role@cpu list; null = lower legacy knobs
    // Shards should outnumber workers: a shard is the unit of migration, so more shards gives the
    // LB finer granularity. Too many and each one's working set stops being worth its own table.
    uint32_t shards         = 16;
    uint16_t port           = 6379;
    const char* bind_addr   = "127.0.0.1";

    // Pinning is relative to the process's ALLOWED cpu set, so taskset confines both the process and
    // its topology grouping — that property is what lets independent benchmark lanes share one box,
    // and its absence was a real bug (threads silently floated instead of erroring).
    bool     pin_threads    = true;

    uint32_t rob_window     = kRobWindow;
    uint32_t embed_threshold = 192;   // re-measure against this allocation shape, not the fork's
};

class Server {
public:
    Server() = default;
    Server(const Server&) = delete;
    Server& operator=(const Server&) = delete;

    bool init(const Config& cfg) {
        cfg_ = cfg;
        // Declared topology wins over discovery -- the operator is saying "build exactly these
        // nodes", including shapes discovery would never produce (cross-CCX nodes, SMT pairs,
        // deliberate mis-placement). A declaration that fails to parse or names cpus outside the
        // affinity mask fails the BOOT, loudly: a topology experiment silently falling back to
        // auto-discovery would measure the wrong thing and report it as a result.
        if (cfg.place && cfg.node_cpus && *cfg.node_cpus) {
            std::fprintf(stderr, "fatal: --place and --node-cpus are mutually exclusive\n");
            return false;
        }
        if (cfg.node_cpus && *cfg.node_cpus) {
            if (!topo_.declare(cfg.node_cpus)) {
                std::fprintf(stderr, "fatal: --node-cpus '%s' invalid\n", cfg.node_cpus);
                return false;
            }
        } else {
            if (!topo_.discover()) {
                std::fprintf(stderr, "fatal: could not discover any allowed cpu\n");
                return false;
            }
        }
        const bool placed = cfg.place
            ? placement_.build_explicit(topo_, cfg.place)
            : placement_.build_legacy(topo_, cfg.nodes, cfg.shards,
                                      cfg.ifid_per_node, cfg.ex_per_node, cfg.wb_per_node);
        if (!placed) return false;
        if (placement_.ifid_threads().empty() || placement_.ex_threads().empty()) {
            std::fprintf(stderr, "placement needs at least one ifid and one ex thread\n");
            return false;
        }
        if (cfg.wb_mode == WbMode::Wb && placement_.wb_threads().empty()) {
            std::fprintf(stderr, "3s placement needs at least one wb thread\n");
            return false;
        }
        if (cfg.wb_mode != WbMode::Wb && !placement_.wb_threads().empty()) {
            std::fprintf(stderr, "wb threads are only meaningful with --mode 3s\n");
            return false;
        }

        // Sender selection is boot-time placement state. Keeping the tid directly on each ifid
        // avoids topology walks when an IO loop starts and makes legacy and explicit placement use
        // the identical launch path.
        const std::vector<uint32_t>& senders = cfg.wb_mode == WbMode::Ex
            ? placement_.ex_threads() : placement_.wb_threads();
        for (size_t k = 0; k < placement_.ifid_threads().size(); k++) {
            const uint32_t tid = placement_.ifid_threads()[k];
            placement_.thread(tid).send_target = cfg.wb_mode == WbMode::Io
                ? tid : senders[k % senders.size()];
        }

        // ---- shards: bucket ranges, fixed for the life of the process ----------------------------
        shards_.resize(cfg.shards);
        const uint32_t per = kNumBuckets / cfg.shards;
        for (uint32_t i = 0; i < cfg.shards; i++) {
            const uint32_t b0 = i * per;
            const uint32_t b1 = (i + 1 == cfg.shards) ? kNumBuckets : (i + 1) * per;
            shards_[i] = std::make_unique<Shard>();
            shards_[i]->init(static_cast<int32_t>(i), b0, b1);
        }
        router_.build_uniform(static_cast<int32_t>(cfg.shards));

        // ---- threads ---------------------------------------------------------------------------
        // Every front-end has already lowered to dense per-thread entries. Every thread still gets
        // a channel from every other regardless of role, because a role change must not require
        // re-wiring the mesh.
        const uint32_t nthreads = placement_.total_threads();
        threads_.resize(nthreads);
        for (uint32_t i = 0; i < nthreads; i++) {
            threads_[i] = std::make_unique<ThreadCtx>();
            threads_[i]->init(i, placement_.role_of(i), nthreads);
        }

        // ---- shards directly onto workers ------------------------------------------------------
        // Locality resolution stops at the individual EX thread. There is no contiguous node range:
        // the default is one flat round-robin across every executor in thread-id order.
        const std::vector<uint32_t>& executors = placement_.ex_threads();
        for (uint32_t sid = 0; sid < cfg.shards; sid++) {
            const uint32_t tid = executors[sid % executors.size()];
            threads_[tid]->shards().push_back(shards_[sid].get());
            // The reverse mapping is the ONE load on dispatch and the ONE release store used by a
            // future migration. Do not mirror ownership in another synchronised structure.
            set_worker_of_shard(static_cast<int32_t>(sid), tid);
            // Seed residency from this exact thread's cpu domain, so note_execution compares at
            // thread resolution even when adjacent tids live in different L3 domains.
            shards_[sid]->note_migration(placement_.domain_of_thread(tid));
        }
        return true;
    }

    const Config&    cfg()        const { return cfg_; }
    const Topology&  topo()       const { return topo_; }
    Placement&       placement()        { return placement_; }
    Router&          router()           { return router_; }
    Shard&           shard(int32_t i)   { return *shards_[i]; }
    ThreadCtx&       thread(uint32_t i) { return *threads_[i]; }
    uint32_t         nthreads()   const { return static_cast<uint32_t>(threads_.size()); }
    uint32_t         nshards()    const { return static_cast<uint32_t>(shards_.size()); }

    // One atomic load on the dispatch path; one atomic store is how an LB moves work.
    uint32_t worker_of_shard(int32_t shard_id) const {
        return shard_owner_[shard_id].load(std::memory_order_acquire);
    }
    void set_worker_of_shard(int32_t shard_id, uint32_t thread_id) {
        shard_owner_[shard_id].store(thread_id, std::memory_order_release);
    }

    std::atomic<uint64_t>& next_client_id() { return next_client_id_; }
    std::atomic<bool>&     shutting_down()  { return shutting_down_; }

private:
    Config    cfg_;
    Topology  topo_;
    Placement placement_;
    Router    router_;
    std::vector<std::unique_ptr<Shard>>     shards_;
    std::vector<std::unique_ptr<ThreadCtx>> threads_;

    std::atomic<uint32_t> shard_owner_[256] = {};
    std::atomic<uint64_t> next_client_id_{1};
    std::atomic<bool>     shutting_down_{false};
};

}  // namespace tomo
