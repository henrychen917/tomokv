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
#include "../net/wb.h"
#include "../snapshot/snapshot.h"

namespace tomo {

struct Config {
    const char* node_cpus   = nullptr;   // operator-declared topology; null = self-discover
    const char* place       = nullptr;   // complete role@cpu list; null = --ratio / default
    // Whole-server role counts for even placement (--ratio). All zero = unset. Unlike the per-node
    // fields above these express any global shape, and they are what a flip controller would vary.
    uint32_t even_ifid      = 0;
    uint32_t even_ex        = 0;
    const char* shard_home  = nullptr;   // optional complete shard:ex_tid map
    // Shards should outnumber workers: a shard is the unit of migration, so more shards gives the
    // LB finer granularity. Too many and each one's working set stops being worth its own table.
    uint32_t shards         = 16;
    uint16_t port           = 6379;
    const char* bind_addr   = "127.0.0.1";
    const char* dir         = ".";
    const char* dbfilename  = "dump.tomo";
    const char* load_path   = nullptr;

    // Pinning is relative to the process's ALLOWED cpu set, so taskset confines both the process and
    // its topology grouping — that property is what lets independent benchmark lanes share one box,
    // and its absence was a real bug (threads silently floated instead of erroring).
    bool     pin_threads    = true;

    uint32_t rob_window     = kRobWindow;
    uint32_t embed_threshold = 192;   // re-measure against this allocation shape, not the fork's
    uint32_t zc_min         = 16384;     // zero-copy GET replies at >= this value length.
                                         // DEFAULT ON (owner: hardcode a consistent gain): -4.1%
                                         // server cycles at d16K on the wire-walled NIC, +20-24%
                                         // class on unwalled wires per the fork's history. 0 = off.
    TypeLimits type_limits;
};

class Server {
public:
    Server() = default;
    Server(const Server&) = delete;
    Server& operator=(const Server&) = delete;

    bool init(const Config& cfg) {
        cfg_ = cfg;
        if (cfg.shards == 0 || cfg.shards > 256) {
            std::fprintf(stderr, "shards must be between 1 and 256\n");
            return false;
        }
        // Declared topology is a legacy lowering input and therefore cannot accompany --place.
        // A declaration that fails to parse or names cpus outside the affinity mask fails the BOOT,
        // loudly: silently falling back to discovery would measure a different layout.
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
        // Default shape: an even io/ex split of every allowed cpu, io taking the odd one out --
        // the measured 2s center (4:4-class) generalized to any core count.
        uint32_t di = cfg.even_ifid, de = cfg.even_ex;
        if (!cfg.place && !(di | de)) {
            uint32_t n = 0;
            for (uint32_t d = 0; d < topo_.ndomains(); d++)
                n += static_cast<uint32_t>(topo_.cpus_in(d).size());
            di = n - n / 2; de = n / 2;
        }
        const bool placed = cfg.place
            ? placement_.build_explicit(topo_, cfg.place)
            : placement_.build_even(topo_, di, de);
        if (!placed) return false;
        if (placement_.ifid_threads().empty() || placement_.ex_threads().empty()) {
            std::fprintf(stderr, "placement needs at least one ifid and one ex thread\n");
            return false;
        }
        // Shard maps are resolved exactly once at boot; parsing never leaks onto a request path.
        if (!placement_.assign_shard_homes(cfg.shards, cfg.shard_home)) return false;

        // ---- shards: bucket ranges, fixed for the life of the process ----------------------------
        shards_.resize(cfg.shards);
        const uint32_t per = kNumBuckets / cfg.shards;
        for (uint32_t i = 0; i < cfg.shards; i++) {
            const uint32_t b0 = i * per;
            const uint32_t b1 = (i + 1 == cfg.shards) ? kNumBuckets : (i + 1) * per;
            shards_[i] = std::make_unique<Shard>();
            shards_[i]->init(static_cast<int32_t>(i), b0, b1, cfg.zc_min, cfg.type_limits);
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
        for (uint32_t sid = 0; sid < cfg.shards; sid++) {
            const uint32_t tid = placement_.shard_home(sid);
            threads_[tid]->shards().push_back(shards_[sid].get());
            // The reverse mapping is the ONE load on dispatch and the ONE release store used by a
            // future migration. Do not mirror ownership in another synchronised structure.
            set_worker_of_shard(static_cast<int32_t>(sid), tid);
            // Seed residency from this exact thread's cpu domain, so note_execution compares at
            // thread resolution even when adjacent tids live in different L3 domains.
            shards_[sid]->note_migration(placement_.domain_of_thread(tid));
        }
        snapshot_.init(nthreads, cfg.shards,
                       static_cast<uint32_t>(placement_.ex_threads().size()),
                       cfg.dir, cfg.dbfilename);
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
    SnapshotManager& snapshot()         { return snapshot_; }
    const SnapshotManager& snapshot() const { return snapshot_; }

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
    SnapshotManager snapshot_;

    std::atomic<uint32_t> shard_owner_[256] = {};
    std::atomic<uint64_t> next_client_id_{1};
    std::atomic<bool>     shutting_down_{false};
};

}  // namespace tomo
