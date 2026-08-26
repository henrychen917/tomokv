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
#include <array>
#include <atomic>
#include <cstdint>
#include <climits>
#include <memory>
#include <sys/resource.h>
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
#include "../persist/aof.h"

namespace tomo {

struct LiveConfigSnapshot {
    uint64_t version;
    uint64_t maxmemory;
    MaxmemoryPolicy policy;
    uint32_t samples;
    uint32_t notify_events;
};

struct ClientLimitsConfigSnapshot {
    uint64_t version = 0;
    uint32_t timeout = 0;
    ClientBufferLimit normal{};
    ClientBufferLimit pubsub{};
};

struct AuthConfigSnapshot {
    bool required;
    std::array<uint64_t, 4> password_hash;
};

class Server {
public:
    static constexpr uint64_t kAtomicEnabledBit = uint64_t{1} << 63;

    Server() = default;
    Server(const Server&) = delete;
    Server& operator=(const Server&) = delete;

    bool init(const Config& cfg, const AofReplayPlan* aof_replay = nullptr) {
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
        live_maxclients_.store(cfg.maxclients, std::memory_order_relaxed);
        live_timeout_.store(cfg.timeout, std::memory_order_relaxed);
        live_tcp_keepalive_.store(cfg.tcp_keepalive, std::memory_order_relaxed);
        store_client_output_buffer_limits(cfg.client_output_buffer_limits);
        refresh_client_cron_armed();
        security_flags_.store(cfg.requirepass && *cfg.requirepass ? kSecurityAuth : 0,
                              std::memory_order_relaxed);
        protected_mode_.store(cfg.protected_mode != 0, std::memory_order_relaxed);
        live_notify_events_.store(cfg.notify_events, std::memory_order_relaxed);
        atomic_activity_.store(cfg.atomic ? kAtomicEnabledBit : 0,
                               std::memory_order_relaxed);
        // AUTO resolves against the shard count: the measured three-point optimum (see config.h).
        const uint32_t resolved_window = cfg.atomic_window == Config::kAtomicWindowAuto
            ? std::min<uint32_t>(16u * cfg.shards, 1024u)
            : cfg.atomic_window;
        cfg_.atomic_window = resolved_window;
        live_atomic_window_.store(resolved_window, std::memory_order_relaxed);
        atomic_credit_pool_.store(resolved_window, std::memory_order_relaxed);
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
        if (!adjust_open_files_limit()) return false;
        check_tcp_backlog_settings();
        // Shard maps are resolved exactly once at boot; parsing never leaks onto a request path.
        if (!placement_.assign_shard_homes(cfg.shards, cfg.shard_home)) return false;

        // ---- shards: bucket ranges, fixed for the life of the process ----------------------------
        shards_.resize(cfg.shards);
        const uint32_t per = kNumBuckets / cfg.shards;
        for (uint32_t i = 0; i < cfg.shards; i++) {
            const uint32_t b0 = i * per;
            const uint32_t b1 = (i + 1 == cfg.shards) ? kNumBuckets : (i + 1) * per;
            shards_[i] = std::make_unique<Shard>();
            shards_[i]->init(this, static_cast<int32_t>(i), b0, b1, cfg.zc_min, cfg.type_limits,
                             cfg.stream_limits);
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
                       cfg.dir, cfg.dbfilename, cfg.persist_io);
        aof_.init(*this, cfg, nthreads, cfg.shards,
                  placement_.ifid_threads().back(), aof_replay);
        for (uint32_t sid = 0; sid < cfg.shards; sid++) {
            const uint32_t sequence = aof_replay && aof_replay->next_sequence.size() == cfg.shards
                ? aof_replay->next_sequence[sid] : 0;
            shards_[sid]->store().bind_aof(cfg.appendonly ? &aof_ : nullptr,
                                           static_cast<int32_t>(sid), sequence);
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
    SnapshotManager& snapshot()         { return snapshot_; }
    const SnapshotManager& snapshot() const { return snapshot_; }
    AofManager& aof() { return aof_; }
    const AofManager& aof() const { return aof_; }
    const ThreadCtx& thread(uint32_t i) const { return *threads_[i]; }

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

    uint32_t maxclients() const { return live_maxclients_.load(std::memory_order_relaxed); }
    void set_maxclients(uint32_t value) {
        live_maxclients_.store(value, std::memory_order_relaxed);
    }
    uint64_t live_clients() const { return live_clients_.load(std::memory_order_relaxed); }
    void client_accepted() { live_clients_.fetch_add(1, std::memory_order_relaxed); }
    void client_released() {
        if (live_clients_.fetch_sub(1, std::memory_order_relaxed) == 0) std::abort();
    }
    void note_rejected_conn() { rejected_conns_.fetch_add(1, std::memory_order_relaxed); }
    uint64_t rejected_conns() const { return rejected_conns_.load(std::memory_order_relaxed); }

    uint32_t tcp_keepalive() const {
        return live_tcp_keepalive_.load(std::memory_order_relaxed);
    }
    void set_tcp_keepalive(uint32_t value) {
        live_tcp_keepalive_.store(value, std::memory_order_relaxed);
    }
    uint32_t timeout() const { return live_timeout_.load(std::memory_order_relaxed); }
    bool client_cron_armed() const {
        return client_cron_armed_.load(std::memory_order_relaxed);
    }
    const std::atomic<bool>* client_cron_armed_ptr() const { return &client_cron_armed_; }
    const std::atomic<bool>* client_obuf_armed_ptr() const {
        return &client_obuf_armed_;
    }
    bool client_obuf_armed() const {
        return client_obuf_armed_.load(std::memory_order_relaxed);
    }
    void set_timeout(uint32_t value) {
        const uint64_t version = begin_live_config_update();
        live_timeout_.store(value, std::memory_order_relaxed);
        refresh_client_cron_armed();
        end_live_config_update(version);
    }

    ClientLimitsConfigSnapshot client_limits_snapshot() const {
        for (;;) {
            ClientLimitsConfigSnapshot out;
            out.version = live_config_version_.load(std::memory_order_acquire);
            if (out.version & 1) continue;
            out.timeout = live_timeout_.load(std::memory_order_relaxed);
            out.normal.hard_bytes = live_obuf_normal_hard_.load(std::memory_order_relaxed);
            out.normal.soft_bytes = live_obuf_normal_soft_.load(std::memory_order_relaxed);
            out.normal.soft_seconds = live_obuf_normal_seconds_.load(std::memory_order_relaxed);
            out.pubsub.hard_bytes = live_obuf_pubsub_hard_.load(std::memory_order_relaxed);
            out.pubsub.soft_bytes = live_obuf_pubsub_soft_.load(std::memory_order_relaxed);
            out.pubsub.soft_seconds = live_obuf_pubsub_seconds_.load(std::memory_order_relaxed);
            if (live_config_version_.load(std::memory_order_acquire) == out.version) return out;
        }
    }
    void set_client_output_buffer_limits(const ClientOutputBufferLimits& limits) {
        const uint64_t version = begin_live_config_update();
        store_client_output_buffer_limits(limits);
        refresh_client_cron_armed();
        end_live_config_update(version);
    }
    void note_client_output_buffer_limit_disconnect() {
        client_output_buffer_limit_disconnections_.fetch_add(1, std::memory_order_relaxed);
    }
    uint64_t client_output_buffer_limit_disconnections() const {
        return client_output_buffer_limit_disconnections_.load(std::memory_order_relaxed);
    }

    void blocking_client_parked() {
        blocked_clients_.fetch_add(1, std::memory_order_relaxed);
    }
    void blocking_client_unparked() {
        blocked_clients_.fetch_sub(1, std::memory_order_relaxed);
    }
    uint64_t blocked_clients() const {
        return blocked_clients_.load(std::memory_order_relaxed);
    }
    void blocking_waiter_added() {
        blocking_waiters_.fetch_add(1, std::memory_order_relaxed);
    }
    void blocking_waiter_removed() {
        blocking_waiters_.fetch_sub(1, std::memory_order_relaxed);
    }
    uint64_t blocking_waiters() const {
        return blocking_waiters_.load(std::memory_order_relaxed);
    }

    // The disabled AUTH fast path is one acquire load plus one predicted-not-taken branch in the
    // IO parser. Password bytes remain in the cold CONFIG table; only AUTH and live CONFIG changes
    // ever take its lock.
    static constexpr uint8_t kSecurityAuth = 1u << 0;
    static constexpr uint8_t kSecurityAcl = 1u << 1;
    uint8_t security_flags() const { return security_flags_.load(std::memory_order_acquire); }
    bool requirepass_enabled() const { return (security_flags() & kSecurityAuth) != 0; }
    bool acl_active() const { return (security_flags() & kSecurityAcl) != 0; }
    AuthConfigSnapshot auth_config_snapshot() const {
        for (;;) {
            const uint64_t version = live_config_version_.load(std::memory_order_acquire);
            if (version & 1) continue;
            AuthConfigSnapshot snapshot;
            snapshot.required = (security_flags_.load(std::memory_order_relaxed) &
                                 kSecurityAuth) != 0;
            for (uint32_t i = 0; i < snapshot.password_hash.size(); i++)
                snapshot.password_hash[i] = live_requirepass_hash_[i].load(
                    std::memory_order_relaxed);
            if (live_config_version_.load(std::memory_order_acquire) == version) return snapshot;
        }
    }
    void set_auth_config(bool required, const std::array<uint64_t, 4>& password_hash) {
        const uint64_t write_version = begin_live_config_update();
        for (uint32_t i = 0; i < password_hash.size(); i++)
            live_requirepass_hash_[i].store(password_hash[i], std::memory_order_relaxed);
        uint8_t flags = security_flags_.load(std::memory_order_relaxed);
        flags = required ? static_cast<uint8_t>(flags | kSecurityAuth)
                         : static_cast<uint8_t>(flags & ~kSecurityAuth);
        security_flags_.store(flags, std::memory_order_relaxed);
        end_live_config_update(write_version);
    }
    void set_acl_active(bool active) {
        acl_active_desired_.store(active, std::memory_order_release);
        if (!active && acl_kill_broadcasts_.load(std::memory_order_acquire) != 0) return;
        const uint64_t write_version = begin_live_config_update();
        uint8_t flags = security_flags_.load(std::memory_order_relaxed);
        flags = active ? static_cast<uint8_t>(flags | kSecurityAcl)
                       : static_cast<uint8_t>(flags & ~kSecurityAcl);
        security_flags_.store(flags, std::memory_order_relaxed);
        end_live_config_update(write_version);
    }
    void acl_kill_broadcast_started(uint32_t targets) {
        acl_kill_broadcasts_.fetch_add(targets, std::memory_order_acq_rel);
    }
    void acl_kill_broadcast_finished() {
        if (acl_kill_broadcasts_.fetch_sub(1, std::memory_order_acq_rel) != 1) return;
        if (!acl_active_desired_.load(std::memory_order_acquire)) set_acl_active(false);
    }
    bool protected_mode() const {
        return protected_mode_.load(std::memory_order_acquire);
    }
    void set_protected_mode(bool enabled) {
        protected_mode_.store(enabled, std::memory_order_release);
    }
    bool active_expire_enabled() const {
        return active_expire_enabled_.load(std::memory_order_relaxed);
    }
    void set_active_expire_enabled(bool enabled) {
        active_expire_enabled_.store(enabled, std::memory_order_relaxed);
    }
    void note_auth_failure() { auth_failures_.fetch_add(1, std::memory_order_relaxed); }
    uint64_t auth_failures() const { return auth_failures_.load(std::memory_order_relaxed); }
    void acl_perm_retired() { acl_perm_retired_.fetch_add(1, std::memory_order_relaxed); }
    uint64_t acl_perm_retired_count() const {
        return acl_perm_retired_.load(std::memory_order_relaxed);
    }
    void acl_pubsub_client_killed() {
        acl_pubsub_clients_killed_.fetch_add(1, std::memory_order_relaxed);
    }
    uint64_t acl_pubsub_clients_killed() const {
        return acl_pubsub_clients_killed_.load(std::memory_order_relaxed);
    }
    void note_rejected_connection() {
        rejected_connections_.fetch_add(1, std::memory_order_relaxed);
    }
    uint64_t rejected_connections() const {
        return rejected_connections_.load(std::memory_order_relaxed);
    }

    uint64_t atomic_mode_state() const {
        return atomic_activity_.load(std::memory_order_acquire);
    }
    bool atomic_enabled() const { return atomic_mode_state() & kAtomicEnabledBit; }
    bool atomic_work_active() const { return (atomic_mode_state() & ~kAtomicEnabledBit) != 0; }
    uint32_t atomic_window() const {
        return live_atomic_window_.load(std::memory_order_acquire);
    }
    void set_atomic_enabled(bool enabled) {
        if (enabled) {
            atomic_reconfigure_credits(atomic_window());
            atomic_activity_.fetch_or(kAtomicEnabledBit, std::memory_order_release);
        } else {
            atomic_activity_.fetch_and(~kAtomicEnabledBit, std::memory_order_release);
            atomic_reconfigure_credits(atomic_window());
        }
    }
    void set_atomic_window(uint32_t window) {
        atomic_reconfigure_credits(window);
    }
    bool atomic_tracking_active() const {
        return atomic_mode_state() != 0;
    }
    bool atomic_can_admit(uint32_t owner_io, bool force = false) const {
        if (snapshot_atomic_barrier_.load(std::memory_order_acquire)) return false;
        if (!force && !(atomic_mode_state() & kAtomicEnabledBit)) return true;
        const uint64_t generation = atomic_credit_generation_.load(std::memory_order_acquire);
        if (generation & 1) return false;
        const uint32_t window = atomic_window();
        if (!window) return true;
        const AtomicAdmissionLease& lease = thread(owner_io).atomic_admission_lease();
        return (lease.generation == generation && lease.available != 0) ||
               atomic_credit_pool_.load(std::memory_order_acquire) != 0;
    }
    bool atomic_try_admit(uint32_t owner_io, uint64_t& admitted_generation,
                          bool force = false) {
        admitted_generation = 0;
        if (snapshot_atomic_barrier_.load(std::memory_order_acquire)) return false;
        if (!force && !(atomic_mode_state() & kAtomicEnabledBit)) return false;
        AtomicAdmissionLease& lease = thread(owner_io).atomic_admission_lease();
        const uint64_t generation = atomic_credit_generation_.load(std::memory_order_acquire);
        if (generation & 1) return false;
        const uint32_t window = atomic_window();
        if (lease.generation != generation) {
            lease.generation = generation;
            lease.available = 0; // the reconfiguration reset the global pool without old leases
        }
        if (window && lease.available == 0) {
            atomic_credit_ops_.fetch_add(1, std::memory_order_acq_rel);
            if (atomic_credit_generation_.load(std::memory_order_acquire) != generation) {
                atomic_credit_ops_.fetch_sub(1, std::memory_order_release);
                return false;
            }
            uint32_t available = atomic_credit_pool_.load(std::memory_order_relaxed);
            bool borrowed = false;
            while (available) {
                const uint32_t take = std::min<uint32_t>(available, kAtomicLeaseBatch);
                if (atomic_credit_pool_.compare_exchange_weak(
                        available, available - take, std::memory_order_acq_rel,
                        std::memory_order_relaxed)) {
                    lease.available = take;
                    borrowed = true;
                    break;
                }
            }
            atomic_credit_ops_.fetch_sub(1, std::memory_order_release);
            if (!borrowed) {
                atomic_window_stalls_.fetch_add(1, std::memory_order_relaxed);
                return false;
            }
        }
        if (window) lease.available--;
        const bool first = lease.active++ == 0;
        lease.published_active.store(lease.active, std::memory_order_release);
        if (first) atomic_activity_.fetch_add(1, std::memory_order_release);
        if (snapshot_atomic_barrier_.load(std::memory_order_acquire) ||
            atomic_credit_generation_.load(std::memory_order_acquire) != generation ||
            (!force && !(atomic_mode_state() & kAtomicEnabledBit))) {
            lease.active--;
            lease.published_active.store(lease.active, std::memory_order_release);
            if (first) atomic_activity_.fetch_sub(1, std::memory_order_release);
            atomic_release_admission_credit(lease, generation);
            return false;
        }
        thread(owner_io).note_atomic_group();
        admitted_generation = generation;
        return true;
    }
    void set_snapshot_atomic_barrier(bool enabled) {
        snapshot_atomic_barrier_.store(enabled, std::memory_order_release);
    }
    void atomic_retire_group(uint32_t owner_io, uint64_t admitted_generation) {
        AtomicAdmissionLease& lease = thread(owner_io).atomic_admission_lease();
        if (!lease.active) std::abort();
        lease.active--;
        lease.published_active.store(lease.active, std::memory_order_release);

        atomic_release_admission_credit(lease, admitted_generation);

        if (lease.active == 0) {
            atomic_activity_.fetch_sub(1, std::memory_order_release);
            // An idle IO must not strand its lease while a hot peer is window-stalled. The config
            // generation plus credit_ops handshake makes returning this batch race-free.
            const uint64_t generation = atomic_credit_generation_.load(std::memory_order_acquire);
            if (atomic_window() && !(generation & 1) && lease.generation == generation &&
                lease.available) {
                const uint32_t returned = lease.available;
                atomic_credit_ops_.fetch_add(1, std::memory_order_acq_rel);
                if (atomic_credit_generation_.load(std::memory_order_acquire) == generation) {
                    atomic_credit_pool_.fetch_add(returned, std::memory_order_release);
                    lease.available = 0;
                }
                atomic_credit_ops_.fetch_sub(1, std::memory_order_release);
            }
        }
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
        // Only IO threads register read cuts. Executor slots are initialized to MAX and never
        // publish, so scanning them merely repeats work in every owner cleanup pass.
        for (uint32_t i : placement_.ifid_threads())
            floor = std::min(floor,
                             atomic_read_floors_[i].load(std::memory_order_seq_cst));
        return floor;
    }
    uint64_t atomic_groups() const {
        uint64_t groups = 0;
        for (uint32_t io : placement_.ifid_threads()) groups += thread(io).atomic_groups();
        return groups;
    }
    uint64_t atomic_inflight() const {
        uint64_t inflight = 0;
        for (uint32_t io : placement_.ifid_threads())
            inflight += thread(io).atomic_admission_lease().published_active.load(
                std::memory_order_acquire);
        return inflight;
    }
    uint64_t atomic_window_stalls() const {
        return atomic_window_stalls_.load(std::memory_order_relaxed);
    }
    uint32_t atomic_credit_pool() const {
        return atomic_credit_pool_.load(std::memory_order_acquire);
    }
    uint32_t atomic_credit_debt() const {
        return atomic_credit_debt_.load(std::memory_order_acquire);
    }

    LiveConfigSnapshot live_config_snapshot() const {
        // CONFIG writers make version odd around a change. Executors take this coherent snapshot
        // once per pass; no atomic reaches an individual operation or store lookup.
        for (;;) {
            LiveConfigSnapshot snapshot;
            snapshot.version = live_config_version_.load(std::memory_order_acquire);
            if (snapshot.version & 1) continue;
            snapshot.maxmemory = live_maxmemory_.load(std::memory_order_relaxed);
            snapshot.policy = static_cast<MaxmemoryPolicy>(
                live_maxmemory_policy_.load(std::memory_order_relaxed));
            snapshot.samples = live_maxmemory_samples_.load(std::memory_order_relaxed);
            snapshot.notify_events = live_notify_events_.load(std::memory_order_relaxed);
            if (live_config_version_.load(std::memory_order_acquire) == snapshot.version)
                return snapshot;
        }
    }
    bool live_config_snapshot_if_changed(uint64_t known_version,
                                         LiveConfigSnapshot& snapshot) const {
        // The unchanged per-pass case is one acquire load. Field loads and the retry loop exist
        // only after CONFIG has published a different stable version.
        const uint64_t version = live_config_version_.load(std::memory_order_acquire);
        if (version == known_version) return false;
        snapshot = live_config_snapshot();
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
    void set_notify_events(uint32_t value) {
        const uint64_t write_version = begin_live_config_update();
        live_notify_events_.store(value, std::memory_order_relaxed);
        end_live_config_update(write_version);
    }

    bool pubsub_any_subscribers() const {
        return pubsub_active_channels_.load(std::memory_order_relaxed) != 0 ||
               pubsub_pattern_subscriptions_.load(std::memory_order_relaxed) != 0;
    }
    bool pubsub_any_shard_subscribers() const {
        return pubsub_shard_channels_.load(std::memory_order_relaxed) != 0;
    }
    void notify_event_fired() { notify_events_fired_.fetch_add(1, std::memory_order_relaxed); }
    void notify_event_dropped(uint64_t count = 1) {
        notify_events_dropped_.fetch_add(count, std::memory_order_relaxed);
    }
    uint64_t notify_events_fired() const {
        return notify_events_fired_.load(std::memory_order_relaxed);
    }
    uint64_t notify_events_dropped() const {
        return notify_events_dropped_.load(std::memory_order_relaxed);
    }
    void client_scatter_started() {
        client_scatter_requests_.fetch_add(1, std::memory_order_relaxed);
    }
    void client_scatter_io_replied() {
        client_scatter_io_responses_.fetch_add(1, std::memory_order_relaxed);
    }
    uint64_t client_scatter_requests() const {
        return client_scatter_requests_.load(std::memory_order_relaxed);
    }
    uint64_t client_scatter_io_responses() const {
        return client_scatter_io_responses_.load(std::memory_order_relaxed);
    }

    // Pub/sub is IO-owned. These atomics are reporting/lifetime gauges only and are never read or
    // written by the plain key-command path.
    void pubsub_event_created() { pubsub_inflight_.fetch_add(1, std::memory_order_relaxed); }
    void pubsub_event_retired() {
        if (pubsub_inflight_.fetch_sub(1, std::memory_order_relaxed) == 0) std::abort();
    }
    // Fanout reporting. `blobs` is a lifetime gauge that must drain to zero (the refcount proof);
    // `deliveries / delivery_batches` is the batching proof -- a ratio of 1.0 means the scatter
    // machinery is posting one event per delivery again, which is the thing this design removed.
    void pubsub_blob_created() { pubsub_blobs_.fetch_add(1, std::memory_order_relaxed); }
    void pubsub_blob_retired() {
        if (pubsub_blobs_.fetch_sub(1, std::memory_order_relaxed) == 0) std::abort();
    }
    void pubsub_deliveries_added(uint64_t n) {
        pubsub_deliveries_.fetch_add(n, std::memory_order_relaxed);
    }
    void pubsub_delivery_batch_posted() {
        pubsub_delivery_batches_.fetch_add(1, std::memory_order_relaxed);
    }
    uint64_t pubsub_blobs() const { return pubsub_blobs_.load(std::memory_order_relaxed); }
    uint64_t pubsub_deliveries() const {
        return pubsub_deliveries_.load(std::memory_order_relaxed);
    }
    uint64_t pubsub_delivery_batches() const {
        return pubsub_delivery_batches_.load(std::memory_order_relaxed);
    }
    bool pubsub_notification_reserve(uint64_t count, uint64_t limit) {
        uint64_t current = pubsub_inflight_.load(std::memory_order_relaxed);
        while (count <= limit && current <= limit - count) {
            if (pubsub_inflight_.compare_exchange_weak(
                    current, current + count, std::memory_order_relaxed,
                    std::memory_order_relaxed)) return true;
        }
        return false;
    }
    void pubsub_notification_retire(uint64_t count) {
        const uint64_t previous = pubsub_inflight_.fetch_sub(count, std::memory_order_relaxed);
        if (previous < count) std::abort();
    }
    void pubsub_pending_started() { pubsub_pending_.fetch_add(1, std::memory_order_relaxed); }
    void pubsub_pending_finished() {
        if (pubsub_pending_.fetch_sub(1, std::memory_order_relaxed) == 0) std::abort();
    }
    void pubsub_home_entry_added() { pubsub_home_entries_.fetch_add(1, std::memory_order_relaxed); }
    void pubsub_home_entry_removed() {
        if (pubsub_home_entries_.fetch_sub(1, std::memory_order_relaxed) == 0) std::abort();
    }
    void pubsub_active_channel_added(bool shard = false) {
        (shard ? pubsub_shard_channels_ : pubsub_active_channels_)
            .fetch_add(1, std::memory_order_relaxed);
    }
    void pubsub_active_channel_removed(bool shard = false) {
        auto& value = shard ? pubsub_shard_channels_ : pubsub_active_channels_;
        if (value.fetch_sub(1, std::memory_order_relaxed) == 0) std::abort();
    }
    void pubsub_subscription_added(bool pattern, bool shard = false) {
        (shard ? pubsub_shard_subscriptions_
               : (pattern ? pubsub_pattern_subscriptions_ : pubsub_subscriptions_))
            .fetch_add(1, std::memory_order_relaxed);
    }
    void pubsub_subscription_removed(bool pattern, bool shard = false) {
        auto& value = shard ? pubsub_shard_subscriptions_
                            : (pattern ? pubsub_pattern_subscriptions_ : pubsub_subscriptions_);
        if (value.fetch_sub(1, std::memory_order_relaxed) == 0) std::abort();
    }
    uint64_t pubsub_inflight() const { return pubsub_inflight_.load(std::memory_order_relaxed); }
    uint64_t pubsub_pending() const { return pubsub_pending_.load(std::memory_order_relaxed); }
    uint64_t pubsub_home_entries() const {
        return pubsub_home_entries_.load(std::memory_order_relaxed);
    }
    uint64_t pubsub_active_channels() const {
        return pubsub_active_channels_.load(std::memory_order_relaxed);
    }
    uint64_t pubsub_subscriptions() const {
        return pubsub_subscriptions_.load(std::memory_order_relaxed);
    }
    uint64_t pubsub_pattern_subscriptions() const {
        return pubsub_pattern_subscriptions_.load(std::memory_order_relaxed);
    }
    uint64_t pubsub_shard_channels() const {
        return pubsub_shard_channels_.load(std::memory_order_relaxed);
    }
    uint64_t pubsub_shard_subscriptions() const {
        return pubsub_shard_subscriptions_.load(std::memory_order_relaxed);
    }

private:
    static constexpr uint32_t kAtomicLeaseBatch = 8;

    bool adjust_open_files_limit() {
        rlimit limit{};
        if (::getrlimit(RLIMIT_NOFILE, &limit) != 0) {
            std::perror("getrlimit(RLIMIT_NOFILE)");
            return false;
        }
        const uint64_t reserve = 32 + placement_.ifid_threads().size() * 2;
        const uint64_t wanted = static_cast<uint64_t>(cfg_.maxclients) + reserve;
        if (limit.rlim_cur < wanted) {
            rlimit raised = limit;
            raised.rlim_cur = static_cast<rlim_t>(std::min<uint64_t>(wanted, limit.rlim_max));
            if (::setrlimit(RLIMIT_NOFILE, &raised) == 0)
                (void)::getrlimit(RLIMIT_NOFILE, &limit);
        }
        if (limit.rlim_cur >= wanted) return true;
        if (limit.rlim_cur <= reserve) {
            std::fprintf(stderr,
                "Your current 'ulimit -n' of %llu is not enough for the server to start. "
                "Please increase your open file limit to at least %llu. Exiting.\n",
                static_cast<unsigned long long>(limit.rlim_cur),
                static_cast<unsigned long long>(wanted));
            return false;
        }
        const uint32_t reduced = static_cast<uint32_t>(std::min<uint64_t>(
            limit.rlim_cur - reserve, UINT32_MAX));
        cfg_.maxclients = reduced;
        live_maxclients_.store(reduced, std::memory_order_relaxed);
        std::fprintf(stderr,
            "Current maximum open files is %llu. maxclients has been reduced to %u to compensate "
            "for low ulimit. If you need higher maxclients increase 'ulimit -n'.\n",
            static_cast<unsigned long long>(limit.rlim_cur), reduced);
        return true;
    }

    void check_tcp_backlog_settings() const {
        std::FILE* file = std::fopen("/proc/sys/net/core/somaxconn", "r");
        if (!file) return;
        int somaxconn = 0;
        const bool read = std::fscanf(file, "%d", &somaxconn) == 1;
        std::fclose(file);
        if (read && somaxconn < static_cast<int>(cfg_.tcp_backlog))
            std::fprintf(stderr,
                "WARNING: The TCP backlog setting of %u cannot be enforced because "
                "/proc/sys/net/core/somaxconn is set to the lower value of %d.\n",
                cfg_.tcp_backlog, somaxconn);
    }

    void store_client_output_buffer_limits(const ClientOutputBufferLimits& limits) {
        live_obuf_normal_hard_.store(limits.normal.hard_bytes, std::memory_order_relaxed);
        live_obuf_normal_soft_.store(limits.normal.soft_bytes, std::memory_order_relaxed);
        live_obuf_normal_seconds_.store(limits.normal.soft_seconds, std::memory_order_relaxed);
        live_obuf_replica_hard_.store(limits.replica.hard_bytes, std::memory_order_relaxed);
        live_obuf_replica_soft_.store(limits.replica.soft_bytes, std::memory_order_relaxed);
        live_obuf_replica_seconds_.store(limits.replica.soft_seconds, std::memory_order_relaxed);
        live_obuf_pubsub_hard_.store(limits.pubsub.hard_bytes, std::memory_order_relaxed);
        live_obuf_pubsub_soft_.store(limits.pubsub.soft_bytes, std::memory_order_relaxed);
        live_obuf_pubsub_seconds_.store(limits.pubsub.soft_seconds, std::memory_order_relaxed);
    }

    void refresh_client_cron_armed() {
        const bool normal = live_obuf_normal_hard_.load(std::memory_order_relaxed) != 0 ||
                            live_obuf_normal_soft_.load(std::memory_order_relaxed) != 0;
        const bool pubsub = live_obuf_pubsub_hard_.load(std::memory_order_relaxed) != 0 ||
                            live_obuf_pubsub_soft_.load(std::memory_order_relaxed) != 0;
        client_obuf_armed_.store(normal || pubsub, std::memory_order_release);
        client_cron_armed_.store(live_timeout_.load(std::memory_order_relaxed) != 0 ||
                                 normal || pubsub, std::memory_order_release);
    }

    void atomic_release_admission_credit(AtomicAdmissionLease& lease,
                                         uint64_t admitted_generation) {
        uint64_t generation = atomic_credit_generation_.load(std::memory_order_acquire);
        while (generation & 1) {
            __builtin_ia32_pause();
            generation = atomic_credit_generation_.load(std::memory_order_acquire);
        }
        if (!atomic_window()) return;
        if (admitted_generation == generation && lease.generation == generation) {
            lease.available++;
            return;
        }
        if (admitted_generation == generation) return;
        uint32_t carry = lease.reconfig_carry.load(std::memory_order_relaxed);
        while (carry && !lease.reconfig_carry.compare_exchange_weak(
                              carry, carry - 1, std::memory_order_acq_rel,
                              std::memory_order_relaxed)) {}
        if (carry) atomic_return_reconfigured_credit(generation);
    }

    void atomic_return_reconfigured_credit(uint64_t generation) {
        atomic_credit_ops_.fetch_add(1, std::memory_order_acq_rel);
        if (atomic_credit_generation_.load(std::memory_order_acquire) == generation) {
            uint32_t debt = atomic_credit_debt_.load(std::memory_order_relaxed);
            while (debt && !atomic_credit_debt_.compare_exchange_weak(
                               debt, debt - 1, std::memory_order_acq_rel,
                               std::memory_order_relaxed)) {}
            if (!debt) atomic_credit_pool_.fetch_add(1, std::memory_order_release);
        }
        atomic_credit_ops_.fetch_sub(1, std::memory_order_release);
    }

    void atomic_reconfigure_credits(uint32_t window) {
        // Odd generations close admission while CONFIG takes an exact active-group snapshot.
        // Borrow/return operations announce themselves so the rebuilt pool cannot race a credit
        // mutation. IO-local available batches are intentionally discarded by the generation
        // change; only published active groups survive into the new accounting epoch.
        uint64_t generation = atomic_credit_generation_.load(std::memory_order_acquire);
        for (;;) {
            if (generation & 1) {
                generation = atomic_credit_generation_.load(std::memory_order_acquire);
                continue;
            }
            if (atomic_credit_generation_.compare_exchange_weak(
                    generation, generation + 1, std::memory_order_acq_rel,
                    std::memory_order_acquire))
                break;
        }
        while (atomic_credit_ops_.load(std::memory_order_acquire) != 0)
            __builtin_ia32_pause();

        uint64_t active = 0;
        for (uint32_t io : placement_.ifid_threads()) {
            AtomicAdmissionLease& lease = thread(io).atomic_admission_lease();
            const uint32_t live = lease.published_active.load(std::memory_order_acquire);
            lease.reconfig_carry.store(live, std::memory_order_release);
            active += live;
        }
        live_atomic_window_.store(window, std::memory_order_release);
        const uint64_t bounded = std::min<uint64_t>(active, UINT32_MAX);
        atomic_credit_pool_.store(
            window && bounded < window ? window - static_cast<uint32_t>(bounded) : 0,
            std::memory_order_release);
        atomic_credit_debt_.store(
            window && bounded > window ? static_cast<uint32_t>(bounded - window) : 0,
            std::memory_order_release);
        atomic_credit_generation_.store(generation + 2, std::memory_order_release);
    }

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
    AofManager aof_;
    // Declared after AOF so its destructor runs first and can detach an active rewrite callback.
    SnapshotManager snapshot_;

    std::atomic<uint32_t> shard_owner_[256] = {};
    uint8_t executor_slots_[kMaxThreads] = {};
    std::atomic<uint64_t> next_client_id_{1};
    std::atomic<bool>     shutting_down_{false};
    std::atomic<uint64_t> live_clients_{0};
    std::atomic<uint64_t> rejected_conns_{0};
    std::atomic<uint64_t> client_output_buffer_limit_disconnections_{0};
    std::atomic<uint64_t> blocked_clients_{0};
    std::atomic<uint64_t> blocking_waiters_{0};
    std::atomic<uint64_t> live_config_version_{0};
    std::atomic<uint64_t> live_maxmemory_{0};
    std::atomic<uint8_t>  live_maxmemory_policy_{
        static_cast<uint8_t>(MaxmemoryPolicy::NoEviction)};
    std::atomic<uint32_t> live_maxmemory_samples_{5};
    std::atomic<uint32_t> live_maxclients_{10000};
    std::atomic<uint32_t> live_timeout_{0};
    std::atomic<uint32_t> live_tcp_keepalive_{300};
    std::atomic<bool> client_cron_armed_{true};
    std::atomic<bool> client_obuf_armed_{true};
    std::atomic<uint64_t> live_obuf_normal_hard_{0};
    std::atomic<uint64_t> live_obuf_normal_soft_{0};
    std::atomic<uint32_t> live_obuf_normal_seconds_{0};
    std::atomic<uint64_t> live_obuf_replica_hard_{256ull * 1024 * 1024};
    std::atomic<uint64_t> live_obuf_replica_soft_{64ull * 1024 * 1024};
    std::atomic<uint32_t> live_obuf_replica_seconds_{60};
    std::atomic<uint64_t> live_obuf_pubsub_hard_{32ull * 1024 * 1024};
    std::atomic<uint64_t> live_obuf_pubsub_soft_{8ull * 1024 * 1024};
    std::atomic<uint32_t> live_obuf_pubsub_seconds_{60};
    std::atomic<uint32_t> live_notify_events_{0};
    std::atomic<uint32_t> live_atomic_window_{256};
    std::atomic<uint64_t> commit_seq_{0};
    std::atomic<bool> snapshot_atomic_barrier_{false};
    std::atomic<uint64_t> atomic_window_stalls_{0};
    std::atomic<uint64_t> atomic_credit_generation_{2};
    std::atomic<uint32_t> atomic_credit_pool_{0};
    std::atomic<uint32_t> atomic_credit_debt_{0};
    std::atomic<uint32_t> atomic_credit_ops_{0};
    // Enabled is the high bit; every admitted group and live record contributes one low-bit unit.
    // Dispatch therefore decides OFF/ON/draining with one acquire load and one predictable test.
    std::atomic<uint64_t> atomic_activity_{0};
    std::atomic<uint64_t> atomic_read_floors_[kMaxThreads] = {};
    std::atomic<uint64_t> atomic_snapshot_completions_[kMaxThreads] = {};
    std::atomic<uint64_t> pubsub_inflight_{0};
    std::atomic<uint64_t> pubsub_blobs_{0};
    std::atomic<uint64_t> pubsub_deliveries_{0};
    std::atomic<uint64_t> pubsub_delivery_batches_{0};
    std::atomic<uint64_t> pubsub_pending_{0};
    std::atomic<uint64_t> pubsub_home_entries_{0};
    std::atomic<uint64_t> pubsub_active_channels_{0};
    std::atomic<uint64_t> pubsub_subscriptions_{0};
    std::atomic<uint64_t> pubsub_pattern_subscriptions_{0};
    std::atomic<uint64_t> pubsub_shard_channels_{0};
    std::atomic<uint64_t> pubsub_shard_subscriptions_{0};
    // Security and DEBUG state is cold and appended after every pre-existing hot atomic so this
    // feature cannot reshuffle cache-line sharing in dispatch, atomic admission, or pub/sub.
    std::atomic<uint8_t> security_flags_{0};
    std::atomic<uint32_t> acl_kill_broadcasts_{0};
    std::atomic<bool> acl_active_desired_{false};
    std::atomic<uint64_t> live_requirepass_hash_[4] = {};
    std::atomic<bool> protected_mode_{true};
    std::atomic<bool> active_expire_enabled_{true};
    std::atomic<uint64_t> auth_failures_{0};
    std::atomic<uint64_t> acl_perm_retired_{0};
    std::atomic<uint64_t> acl_pubsub_clients_killed_{0};
    std::atomic<uint64_t> rejected_connections_{0};
    std::atomic<uint64_t> notify_events_fired_{0};
    std::atomic<uint64_t> notify_events_dropped_{0};
    // Cold observability for proving CLIENT catalog work reached every IO owner.
    std::atomic<uint64_t> client_scatter_requests_{0};
    std::atomic<uint64_t> client_scatter_io_responses_{0};
};

}  // namespace tomo
