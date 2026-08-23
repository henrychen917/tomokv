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
    // PER NODE, matching the fork's tomokv-thread-io / -ex. Per-node is the right unit because the
    // split that matters is the one INSIDE a node, where the io->ex handoff actually happens; with
    // --nodes 2 --spread 4:4 the server runs eight io and eight ex threads in total.
    uint32_t ifid_per_node    = 4;
    uint32_t ex_per_node    = 4;
    // Only used by WbMode::Wb (the 3-stage shape). Zero for 2s and ex-wb, where the sends are issued
    // by a thread that already exists.
    uint32_t wb_per_node    = 0;
    WbMode   wb_mode        = WbMode::Io;
    // 0 means "one node per L3 domain", which is the measured optimum and therefore the default
    // rather than something an operator has to know to ask for.
    uint32_t nodes          = 0;
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
        topo_.discover();
        placement_.build(topo_, cfg.nodes, cfg.shards,
                         cfg.ifid_per_node, cfg.ex_per_node, cfg.wb_per_node);
        placement_.assign_threads();

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

        // ---- threads, grouped BY NODE ---------------------------------------------------------
        // Thread ids are dense and node-major, so a node's io and ex threads are adjacent and land
        // in the same L3 domain when pinned. Every thread still gets a channel from every other
        // regardless of role, because a role change must not require re-wiring the mesh.
        const uint32_t nthreads = placement_.total_threads();
        threads_.resize(nthreads);
        for (uint32_t i = 0; i < nthreads; i++) {
            threads_[i] = std::make_unique<ThreadCtx>();
            threads_[i]->init(i, placement_.role_of(i), nthreads);
        }

        // ---- shards onto their OWN node's workers -----------------------------------------------
        // A node's shards are served by that node's ex threads, so the dispatch hop and the
        // completion pointer stay inside one L3. Cross-node dispatch still happens whenever a key
        // lands elsewhere; Shard::foreign_ops measures exactly how often.
        for (uint32_t n = 0; n < placement_.nnodes(); n++) {
            const Node& node = placement_.node(n);
            if (node.ex.empty()) continue;
            for (size_t k = 0; k < node.shards.size(); k++) {
                const int32_t  sid = node.shards[k];
                const uint32_t tid = node.ex[k % node.ex.size()];
                threads_[tid]->shards().push_back(shards_[sid].get());
                // The reverse mapping is what the DISPATCH path reads. Assigning shards to workers
                // without recording it leaves every op routing to thread 0.
                set_worker_of_shard(sid, tid);
                // Seed the home domain from the node so the first foreign-op comparison is against
                // the INTENDED placement, not wherever it happened to run first.
                shards_[sid]->note_migration(node.domain);
            }
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
