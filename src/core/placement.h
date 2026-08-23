// placement.h — per-thread role/cpu placement and the shard migration contract.
//
// THREAD IS THE LOCALITY UNIT. Each dense thread id has one role, one cpu and therefore one L3
// domain. There is deliberately no node layer between a thread and those facts: SMT siblings,
// cross-CCX layouts and deliberately asymmetric experiments all fit the same representation.
//
// The legacy node/spread interface is only a lowering rule. It still creates the same node-major
// role and cpu sequence as before, then discards the temporary grouping. From that point onward the
// server cannot tell whether placement came from --place or from --nodes/--spread, which prevents
// the two front-ends from acquiring subtly different routing or launch behaviour.
#pragma once
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "shard.h"
#include "thread.h"
#include "../base/topology.h"

namespace tomo {

inline constexpr uint32_t kNoThread = UINT32_MAX;

struct ThreadPlacement {
    uint32_t id          = 0;
    Role     role        = Role::Idle;
    int      cpu         = -1;
    uint32_t domain      = kNoDomain;
    uint32_t send_target = kNoThread;  // self in 2s; an ex/wb tid in exwb/3s
};

class Placement {
public:
    // Preserve the old CLI's exact lowering: node-major ids, role-major within each node, and cpus
    // selected in domain order (wrapping only when a node has more threads than allowed cpus).
    bool build_legacy(const Topology& topo, uint32_t want_nodes, uint32_t nshards,
                      uint32_t ifid_per_node, uint32_t ex_per_node, uint32_t wb_per_node) {
        clear();
        const uint32_t nd = topo.ndomains() ? topo.ndomains() : 1;
        uint32_t n = want_nodes ? want_nodes : nd;
        if (n > nd) n = nd;                     // never more nodes than L3 domains
        if (n == 0) n = 1;
        if (nshards < n) n = nshards ? nshards : 1;   // every node must own at least one shard
        const uint64_t total = static_cast<uint64_t>(n) *
                               (ifid_per_node + ex_per_node + wb_per_node);
        if (total > kMaxThreads) {
            std::fprintf(stderr, "placement: %llu threads exceeds the %u-thread channel limit\n",
                         static_cast<unsigned long long>(total), kMaxThreads);
            return false;
        }
        for (uint32_t i = 0; i < n; i++) {
            const uint32_t domain = i % nd;
            const std::vector<int>& cpus = topo.cpus_in(domain);
            uint32_t slot = 0;
            for (uint32_t k = 0; k < ifid_per_node; k++) append(Role::Ifid, pick(cpus, slot++), domain);
            for (uint32_t k = 0; k < ex_per_node; k++) append(Role::Ex, pick(cpus, slot++), domain);
            for (uint32_t k = 0; k < wb_per_node; k++) append(Role::Wb, pick(cpus, slot++), domain);
        }
        return true;
    }

    // --place is intentionally a small, strict language. Boot configuration should fail at the
    // first typo instead of accepting a partial placement and letting unpinned threads float.
    bool build_explicit(const Topology& topo, const char* spec) {
        clear();
        if (!spec || !*spec) {
            std::fprintf(stderr, "--place must contain role@cpu entries\n");
            return false;
        }
        const char* p = spec;
        while (*p) {
            Role role = Role::Idle;
            if (!std::strncmp(p, "ifid@", 5)) {
                role = Role::Ifid; p += 5;
            } else if (!std::strncmp(p, "ex@", 3)) {
                role = Role::Ex; p += 3;
            } else if (!std::strncmp(p, "wb@", 3)) {
                role = Role::Wb; p += 3;
            } else {
                std::fprintf(stderr, "--place: expected ifid@cpu, ex@cpu, or wb@cpu near '%s'\n", p);
                return false;
            }
            if (*p < '0' || *p > '9') {
                std::fprintf(stderr, "--place: expected a non-negative cpu near '%s'\n", p);
                return false;
            }
            char* end = nullptr;
            const long cpu = std::strtol(p, &end, 10);
            if (cpu < 0 || cpu >= CPU_SETSIZE || (*end != ',' && *end != '\0')) {
                std::fprintf(stderr, "--place: invalid cpu near '%s'\n", p);
                return false;
            }
            const uint32_t domain = topo.domain_of(static_cast<int>(cpu));
            if (domain == kNoDomain) {
                std::fprintf(stderr, "--place: cpu %ld is outside the affinity mask\n", cpu);
                return false;
            }
            if (threads_.size() == kMaxThreads) {
                std::fprintf(stderr, "--place exceeds the %u-thread channel limit\n", kMaxThreads);
                return false;
            }
            append(role, static_cast<int>(cpu), domain);
            if (*end == '\0') break;
            p = end + 1;
            if (!*p) {
                std::fprintf(stderr, "--place: trailing comma\n");
                return false;
            }
        }
        return true;
    }

    uint32_t total_threads() const { return static_cast<uint32_t>(threads_.size()); }

    ThreadPlacement&       thread(uint32_t tid)       { return threads_[tid]; }
    const ThreadPlacement& thread(uint32_t tid) const { return threads_[tid]; }
    const std::vector<ThreadPlacement>& threads() const { return threads_; }
    const std::vector<uint32_t>& ifid_threads() const { return ifid_; }
    const std::vector<uint32_t>& ex_threads()   const { return ex_; }
    const std::vector<uint32_t>& wb_threads()   const { return wb_; }

    Role role_of(uint32_t tid) const { return threads_[tid].role; }
    int cpu_of_thread(uint32_t tid) const { return threads_[tid].cpu; }
    uint32_t domain_of_thread(uint32_t tid) const { return threads_[tid].domain; }

private:
    void clear() {
        threads_.clear();
        ifid_.clear();
        ex_.clear();
        wb_.clear();
    }

    void append(Role role, int cpu, uint32_t domain) {
        const uint32_t tid = static_cast<uint32_t>(threads_.size());
        threads_.push_back(ThreadPlacement{tid, role, cpu, domain, kNoThread});
        (role == Role::Ifid ? ifid_ : role == Role::Ex ? ex_ : wb_).push_back(tid);
    }

    static int pick(const std::vector<int>& cpus, uint32_t slot) {
        return cpus.empty() ? -1 : cpus[slot % cpus.size()];
    }

    std::vector<ThreadPlacement> threads_;
    std::vector<uint32_t> ifid_;
    std::vector<uint32_t> ex_;
    std::vector<uint32_t> wb_;
};

// ---------------------------------------------------------------------------------------------
// THE MIGRATION CONTRACT. Moving a shard is a single store into worker_of_shard[]. What makes it
// correct is the ordering around it:
//
//   1. Stop routing new ops to the old owner (the store does this; it is a release).
//   2. WAIT for the old owner to finish what it already has — task_in.quiesced(), which tests the
//      RETIRED frontier. head == tail only means "nothing left to pop"; the worker may still be
//      executing what it popped.
//   3. Only then may the new owner touch the shard's store.
//
// Skipping step 2 puts two threads in one FlatStore, which has no locks precisely because that is
// supposed to be impossible — it would corrupt silently rather than crash.
//
// Written as a contract rather than an implementation because there is no LB yet and a half-built
// migration path is worse than none.
// ---------------------------------------------------------------------------------------------
struct MigrationPlan {
    int32_t  shard_id    = -1;
    uint32_t from_thread = 0;
    uint32_t to_thread   = 0;
    size_t   cost_bytes  = 0;    // what the new domain must re-pull; Shard::migration_cost_bytes()
};

}  // namespace tomo
