// server.h — process-wide shared state. Everything here is either immutable after boot or
// explicitly synchronised; nothing in it is written on the hot path.
//
// THAT IS THE RULE, and it is worth stating because it is easy to violate by accident. A counter
// bumped per command from a struct every thread shares is a shared-line write on the hot path, and
// at this thread count it shows up immediately. Per-command counters live in Shard::Stats or
// ThreadCtx::Stats, both of which are single-writer; INFO sums them on request.
#pragma once
#include <atomic>
#include <cstdint>
#include <memory>
#include <vector>
#include "shard.h"
#include "thread.h"

namespace tomo {

struct Config {
    // Geometry. Defaults follow the measured node rule: one node per last-level-cache domain
    // (8 physical cores on Bergamo = 1 CCX = 1 L3). See the architecture notes, 1.2.
    uint32_t io_threads     = 4;
    uint32_t ex_threads     = 4;
    uint32_t shards         = 8;      // shards >= ex_threads; a worker may run several
    uint16_t port           = 6379;
    const char* bind_addr   = "127.0.0.1";

    // Placement. Pinning is relative to the process's ALLOWED cpu set, so taskset confines both the
    // process and its topology grouping — that property is what lets independent benchmark lanes
    // share one box, and it was a real bug when it was absent (threads silently floated).
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
        shards_.resize(cfg.shards);
        const uint32_t per = kNumBuckets / cfg.shards;
        for (uint32_t i = 0; i < cfg.shards; i++) {
            const uint32_t b0 = i * per;
            const uint32_t b1 = (i + 1 == cfg.shards) ? kNumBuckets : (i + 1) * per;
            shards_[i] = std::make_unique<Shard>();
            shards_[i]->init(static_cast<int32_t>(i), b0, b1);
        }
        router_.build_uniform(static_cast<int32_t>(cfg.shards));

        threads_.resize(cfg.io_threads + cfg.ex_threads);
        for (uint32_t i = 0; i < threads_.size(); i++) {
            threads_[i] = std::make_unique<ThreadCtx>();
            threads_[i]->init(i, i < cfg.io_threads ? Role::Io : Role::Ex,
                              static_cast<uint32_t>(threads_.size()));
        }
        // Round-robin shards onto workers. Deliberately a plain assignment rather than a policy:
        // rebalancing is the flip controller's job later, and it moves SHARDS, never keys.
        for (uint32_t s = 0; s < cfg.shards; s++) {
            ThreadCtx& w = *threads_[cfg.io_threads + (s % cfg.ex_threads)];
            w.shards().push_back(shards_[s].get());
        }
        return true;
    }

    const Config& cfg() const { return cfg_; }
    Router&       router()    { return router_; }
    Shard&        shard(int32_t i) { return *shards_[i]; }
    ThreadCtx&    thread(uint32_t i) { return *threads_[i]; }
    uint32_t      nthreads() const { return static_cast<uint32_t>(threads_.size()); }

    // Which worker thread currently executes a shard. Read on the dispatch path, written only when
    // shards are reassigned, so it is atomic rather than locked.
    uint32_t worker_of_shard(int32_t shard_id) const {
        return shard_owner_[shard_id].load(std::memory_order_acquire);
    }
    void set_worker_of_shard(int32_t shard_id, uint32_t thread_id) {
        shard_owner_[shard_id].store(thread_id, std::memory_order_release);
    }

    std::atomic<uint64_t>& next_client_id() { return next_client_id_; }
    std::atomic<bool>&     shutting_down()  { return shutting_down_; }

private:
    Config cfg_;
    Router router_;
    std::vector<std::unique_ptr<Shard>>     shards_;
    std::vector<std::unique_ptr<ThreadCtx>> threads_;

    std::atomic<uint32_t> shard_owner_[256] = {};
    std::atomic<uint64_t> next_client_id_{1};
    std::atomic<bool>     shutting_down_{false};
};

}  // namespace tomo
