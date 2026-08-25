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
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <memory>
#include <vector>
#include "shard.h"
#include "thread.h"
#include "placement.h"
#include "config.h"        // struct Config: every runtime knob, one home
#include "../base/topology.h"
#include "../net/conn.h"   // kRobWindow: one source of truth for the window size
#include "../net/wb.h"
#include "../cmd/command.h"
#include "../snapshot/snapshot.h"

namespace tomo {

struct MaxmemoryConfigSnapshot {
    uint64_t version;
    uint64_t maxmemory;
    MaxmemoryPolicy policy;
    uint32_t samples;
};

class Server {
public:
    static constexpr uint64_t kAtomicEnabledBit = uint64_t{1} << 63;

    Server() = default;
    Server(const Server&) = delete;
    Server& operator=(const Server&) = delete;

    bool init(const Config& cfg) {
        cfg_ = cfg;
        if (cfg.shards == 0 || cfg.shards > 256) {
            std::fprintf(stderr, "shards must be between 1 and 256\n");
            return false;
        }
        if (cfg.maxmemory_samples == 0 || cfg.maxmemory_samples > 64) {
            std::fprintf(stderr, "maxmemory-samples must be between 1 and 64\n");
            return false;
        }
        live_maxmemory_.store(cfg.maxmemory, std::memory_order_relaxed);
        live_maxmemory_policy_.store(static_cast<uint8_t>(cfg.maxmemory_policy),
                                     std::memory_order_relaxed);
        live_maxmemory_samples_.store(cfg.maxmemory_samples, std::memory_order_relaxed);
        atomic_activity_.store(cfg.atomic ? kAtomicEnabledBit : 0,
                               std::memory_order_relaxed);
        live_atomic_window_.store(cfg.atomic_window, std::memory_order_relaxed);
        live_config_version_.store(2, std::memory_order_release);  // even versions are stable
        // Declared topology is a legacy lowering input and therefore cannot accompany --place.
        // A declaration that fails to parse or names cpus outside the affinity mask fails the BOOT,
        // loudly: silently falling back to discovery would measure a different layout.
        if (cfg.place && cfg.node_cpus && *cfg.node_cpus) {
            std::fprintf(stderr, "fatal: --place and --node-cpus are mutually exclusive\n");
            return false;
        }
        if (cfg.node_cpus && *cfg.node_cpus) {
            if (!topo_.declare(cfg.node_cpus)) {
                std::fprintf(stderr, "fatal: --l3-domains '%s' invalid\n", cfg.node_cpus);
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
            shards_[i]->bind_atomic_state(&commit_seq_, &atomic_activity_);
        }
        router_.build_uniform(static_cast<int32_t>(cfg.shards));

        // ---- threads ---------------------------------------------------------------------------
        // Every front-end has already lowered to dense per-thread entries. Every thread still gets
        // a channel from every other regardless of role, because a role change must not require
        // re-wiring the mesh.
        const uint32_t nthreads = placement_.total_threads();
        for (uint32_t i = 0; i < kMaxThreads; i++) executor_slots_[i] = UINT8_MAX;
        for (uint32_t slot = 0; slot < placement_.ex_threads().size(); slot++)
            executor_slots_[placement_.ex_threads()[slot]] = static_cast<uint8_t>(slot);
        threads_.resize(nthreads);
        for (uint32_t i = 0; i < nthreads; i++) {
            threads_[i] = std::make_unique<ThreadCtx>();
            threads_[i]->init(i, placement_.role_of(i), nthreads);
            threads_[i]->init_command_counts(command_registry_size());
        }
        for (uint32_t i = 0; i < nthreads; i++)
            atomic_read_floors_[i].store(UINT64_MAX, std::memory_order_relaxed);
        for (uint32_t i = 0; i < nthreads; i++)
            atomic_snapshot_completions_[i].store(0, std::memory_order_relaxed);

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
    uint32_t executor_slot(uint32_t thread_id) const {
        return thread_id < kMaxThreads ? executor_slots_[thread_id] : UINT8_MAX;
    }

    std::atomic<uint64_t>& next_client_id() { return next_client_id_; }
    std::atomic<bool>&     shutting_down()  { return shutting_down_; }

    uint64_t atomic_mode_state() const {
        return atomic_activity_.load(std::memory_order_acquire);
    }
    bool atomic_enabled() const { return atomic_mode_state() & kAtomicEnabledBit; }
    bool atomic_work_active() const { return (atomic_mode_state() & ~kAtomicEnabledBit) != 0; }
    uint32_t atomic_window() const {
        return live_atomic_window_.load(std::memory_order_acquire);
    }
    void set_atomic_enabled(bool enabled) {
        if (enabled) atomic_activity_.fetch_or(kAtomicEnabledBit, std::memory_order_release);
        else atomic_activity_.fetch_and(~kAtomicEnabledBit, std::memory_order_release);
    }
    void set_atomic_window(uint32_t window) {
        live_atomic_window_.store(window, std::memory_order_release);
    }
    bool atomic_tracking_active() const {
        return atomic_mode_state() != 0;
    }
    bool atomic_can_admit() const {
        const uint32_t window = atomic_window();
        return !window || atomic_inflight_.load(std::memory_order_acquire) < window;
    }
    bool atomic_try_admit() {
        const uint32_t window = atomic_window();
        uint64_t current = atomic_inflight_.load(std::memory_order_relaxed);
        for (;;) {
            if (window && current >= window) {
                atomic_window_stalls_.fetch_add(1, std::memory_order_relaxed);
                return false;
            }
            if (atomic_inflight_.compare_exchange_weak(
                    current, current + 1, std::memory_order_acq_rel,
                    std::memory_order_relaxed)) {
                atomic_groups_.fetch_add(1, std::memory_order_relaxed);
                atomic_activity_.fetch_add(1, std::memory_order_release);
                return true;
            }
        }
    }
    void atomic_retire_group() {
        atomic_inflight_.fetch_sub(1, std::memory_order_release);
        atomic_activity_.fetch_sub(1, std::memory_order_release);
    }
    uint64_t atomic_commit() {
        return commit_seq_.fetch_add(1, std::memory_order_seq_cst) + 1;
    }
    uint64_t atomic_snapshot() const { return commit_seq_.load(std::memory_order_seq_cst); }
    void publish_atomic_read_floor(uint32_t thread, uint64_t floor) {
        atomic_read_floors_[thread].store(floor, std::memory_order_seq_cst);
    }
    void note_atomic_snapshot_complete(uint32_t thread) {
        atomic_snapshot_completions_[thread].fetch_add(1, std::memory_order_release);
    }
    uint64_t atomic_snapshot_completions(uint32_t thread) const {
        return atomic_snapshot_completions_[thread].load(std::memory_order_acquire);
    }
    uint64_t atomic_read_floor() const {
        // Lifetime invariant: promotion frees only versions whose tickets are strictly below this
        // minimum and no newer than its pre-floor commit cutoff. Readers publish the successor of
        // their inclusive cut, so the winner at that cut is eligible to become the sole physical
        // representation. Snapshot registration publishes then confirms commit_seq; these
        // seq_cst operations ensure a cleanup that missed the
        // publication has an older cutoff. Thus no active IO snapshot can later dereference a
        // freed loser. UINT64_MAX means no registered reader constrains the floor.
        uint64_t floor = UINT64_MAX;
        for (uint32_t i = 0; i < nthreads(); i++)
            floor = std::min(floor,
                             atomic_read_floors_[i].load(std::memory_order_seq_cst));
        return floor;
    }
    uint64_t atomic_groups() const { return atomic_groups_.load(std::memory_order_relaxed); }
    uint64_t atomic_inflight() const { return atomic_inflight_.load(std::memory_order_relaxed); }
    uint64_t atomic_window_stalls() const {
        return atomic_window_stalls_.load(std::memory_order_relaxed);
    }

    MaxmemoryConfigSnapshot maxmemory_config_snapshot() const {
        // CONFIG writers make version odd around a change. Executors take this coherent snapshot
        // once per pass; no atomic reaches an individual operation or store lookup.
        for (;;) {
            MaxmemoryConfigSnapshot snapshot;
            snapshot.version = live_config_version_.load(std::memory_order_acquire);
            if (snapshot.version & 1) continue;
            snapshot.maxmemory = live_maxmemory_.load(std::memory_order_relaxed);
            snapshot.policy = static_cast<MaxmemoryPolicy>(
                live_maxmemory_policy_.load(std::memory_order_relaxed));
            snapshot.samples = live_maxmemory_samples_.load(std::memory_order_relaxed);
            if (live_config_version_.load(std::memory_order_acquire) == snapshot.version)
                return snapshot;
        }
    }
    bool maxmemory_config_snapshot_if_changed(uint64_t known_version,
                                              MaxmemoryConfigSnapshot& snapshot) const {
        // The unchanged per-pass case is one acquire load. Field loads and the retry loop exist
        // only after CONFIG has published a different stable version.
        const uint64_t version = live_config_version_.load(std::memory_order_acquire);
        if (version == known_version) return false;
        snapshot = maxmemory_config_snapshot();
        return snapshot.version != known_version;
    }
    void set_maxmemory(uint64_t value) {
        set_maxmemory_config(value, MaxmemoryPolicy::NoEviction, 0, true, false, false);
    }
    void set_maxmemory_policy(MaxmemoryPolicy value) {
        set_maxmemory_config(0, value, 0, false, true, false);
    }
    void set_maxmemory_samples(uint32_t value) {
        set_maxmemory_config(0, MaxmemoryPolicy::NoEviction, value, false, false, true);
    }
    void set_maxmemory_config(uint64_t memory, MaxmemoryPolicy policy, uint32_t samples,
                              bool set_memory = true, bool set_policy = true,
                              bool set_samples = true) {
        const uint64_t write_version = begin_live_config_update();
        if (set_memory) live_maxmemory_.store(memory, std::memory_order_relaxed);
        if (set_policy)
            live_maxmemory_policy_.store(static_cast<uint8_t>(policy), std::memory_order_relaxed);
        if (set_samples) live_maxmemory_samples_.store(samples, std::memory_order_relaxed);
        end_live_config_update(write_version);
    }

private:
    uint64_t begin_live_config_update() {
        uint64_t version = live_config_version_.load(std::memory_order_acquire);
        for (;;) {
            if (version & 1) {
                version = live_config_version_.load(std::memory_order_acquire);
                continue;
            }
            if (live_config_version_.compare_exchange_weak(
                    version, version + 1, std::memory_order_acq_rel, std::memory_order_acquire))
                return version + 1;
        }
    }
    void end_live_config_update(uint64_t write_version) {
        live_config_version_.store(write_version + 1, std::memory_order_release);
    }

    Config    cfg_;
    Topology  topo_;
    Placement placement_;
    Router    router_;
    std::vector<std::unique_ptr<Shard>>     shards_;
    std::vector<std::unique_ptr<ThreadCtx>> threads_;
    SnapshotManager snapshot_;

    std::atomic<uint32_t> shard_owner_[256] = {};
    uint8_t executor_slots_[kMaxThreads] = {};
    std::atomic<uint64_t> next_client_id_{1};
    std::atomic<bool>     shutting_down_{false};
    std::atomic<uint64_t> live_config_version_{0};
    std::atomic<uint64_t> live_maxmemory_{0};
    std::atomic<uint8_t>  live_maxmemory_policy_{
        static_cast<uint8_t>(MaxmemoryPolicy::NoEviction)};
    std::atomic<uint32_t> live_maxmemory_samples_{5};
    std::atomic<uint32_t> live_atomic_window_{256};
    std::atomic<uint64_t> commit_seq_{0};
    std::atomic<uint64_t> atomic_inflight_{0};
    std::atomic<uint64_t> atomic_groups_{0};
    std::atomic<uint64_t> atomic_window_stalls_{0};
    // Enabled is the high bit; every admitted group and live record contributes one low-bit unit.
    // Dispatch therefore decides OFF/ON/draining with one acquire load and one predictable test.
    std::atomic<uint64_t> atomic_activity_{0};
    std::atomic<uint64_t> atomic_read_floors_[kMaxThreads] = {};
    std::atomic<uint64_t> atomic_snapshot_completions_[kMaxThreads] = {};
};

}  // namespace tomo
