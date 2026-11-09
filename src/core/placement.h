// CPU/role placement vectors and initial shard homes, shared by Server and boot support.
// Threads use dense ids distinct from CPU numbers. With SMT pairing enabled, validated
// reciprocal sysfs siblings form a scheduling unit with one role; FLIP moves the pair together.
// Runtime mutation of role vectors requires FLIP quiescence so readers need no per-access
// mutex. Shard migration separately fences old-owner work and publishes one committed route
// change.

#pragma once
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <utility>
#include <vector>
#include "shard.h"
#include "thread.h"
#include "../base/topology.h"

namespace tomo {

inline constexpr uint32_t kNoThread = UINT32_MAX;

struct ThreadPlacement {
    uint32_t id = 0;
    Role role = Role::Idle;
    int cpu = -1;
    uint32_t domain = kNoDomain;
};

// Contract: Server owns the topology-derived thread, role, shard-home and SMT-peer vectors.
// Boot builders require exclusive access; runtime set_runtime_role requires FLIP global
// quiescence and reserved role-vector capacity. Methods add no atomic publication: the caller's
// stage protocol publishes mutations. Index accessors require valid dense ids. Builders report
// invalid inputs as false, may leave partial state on failure, and generally propagate
// allocation exceptions; reserve_runtime_roles catches allocation failure and returns false.
class Placement {
public:
    // FUSED PLACEMENT. Every selected CPU owns clients and may own shards. The two dense views
    // intentionally contain the same tids: connection fanout consumes ifid_threads(),
    // while shard/snapshot fanout consumes ex_threads(). Explicit role labels remain accepted as
    // CPU selectors, but have no runtime meaning in this mode.
    bool build_fused(const Topology& topo, const char* spec);

    // Spread whole-server IO/EX counts across L3 domains using integer quotas, allowing shapes
    // such as 15:2. Within each domain append IO threads then EX threads. Unequal domain
    // capacities require quota redistribution. Runtime FLIP uses the same topology facts to
    // choose role conversions; there is no intermediate node layer.
    // Contract: Server boot (and standalone fixtures) supplies topology/counts with exclusive
    // access. Clear prior placement, distribute quotas, then append dense threads; SMT mode
    // delegates to build_even_smt. Capacity/shape failures print diagnostics and return false.
    // Vector allocation can throw; no worker state is published by this builder.
    bool build_even(const Topology& topo, uint32_t n_ifid, uint32_t n_ex, bool smt_mode = false);

    // --place is intentionally a small, strict language. Boot configuration should fail at the
    // first typo instead of accepting a partial placement and letting unpinned threads float.
    // Contract: Boot parsing with exclusive Placement access. Clear prior state and parse the
    // complete role@cpu list against the allowed topology. Syntax, CPU or channel-limit
    // failures return false with diagnostics and can leave a parsed prefix; callers must reject
    // the failed placement. Vector allocation can throw, and this method does not publish
    // runtime roles.
    bool build_explicit(const Topology& topo, const char* spec);

    // A manual topology map is complete: shard IDs name dense executor thread IDs, not CPUs.
    // Executors omitted from the map remain valid empty fillers. Runtime migration still uses
    // the ordinary ownership transaction; this map selects only initial ownership.
    // Contract: Boot callers provide the completed executor view and exclusive access. Produce
    // a full shard-id to dense-thread-id map, defaulting to round-robin. Reject
    // missing/duplicate/out of-range entries or non-executor targets; failed explicit parsing
    // can leave partial state. Allocation can throw; runtime shard ownership is installed
    // separately.
    bool assign_shard_homes(uint32_t nshards, const char* spec = nullptr);

    uint32_t total_threads() const;

    ThreadPlacement& thread(uint32_t tid);
    const ThreadPlacement& thread(uint32_t tid) const;
    const std::vector<ThreadPlacement>& threads() const;
    const std::vector<uint32_t>& ifid_threads() const;
    const std::vector<uint32_t>& ex_threads() const;
    bool is_executor(uint32_t tid) const;

    // Resolve cpu siblings to dense thread ids after either placement frontend has run. Pair mode
    // is a boot contract, not a best effort: a selected cpu with an absent sibling, a non-pair
    // sysfs topology, or two sibling threads assigned different roles rejects the shape.
    // Contract: Boot callers provide a completed placement and exclusive access. Fill dense
    // peer ids after validating unique selected CPUs, reciprocal two-thread sysfs pairs and
    // equal roles. Disabled mode fills no-peer sentinels. Invalid topology returns false with
    // diagnostics where provided; allocation can throw. There is no concurrent publication in
    // this method.
    bool configure_smt_units(const Topology& topo, bool enabled);

    uint32_t smt_peer(uint32_t tid) const;

    bool reserve_runtime_roles(uint32_t total);

    // Invoked only under FLIP's global quiescence barrier. Hot fan-out readers are paused while
    // these dense vectors change, so runtime role publication does not put a mutex on their paths.
    void set_runtime_role(uint32_t tid, Role role);

    Role role_of(uint32_t tid) const;
    int cpu_of_thread(uint32_t tid) const;
    uint32_t domain_of_thread(uint32_t tid) const;
    uint32_t shard_home(uint32_t sid) const;

private:
    // Contract: build_even delegates here after clearing state, with exclusive access. Collect
    // complete same-domain reciprocal SMT pairs, distribute IO/EX pair quotas and append both
    // siblings with the same role. Counts must be even and fit topology/channel limits. Invalid
    // shapes return false with diagnostics; temporary/vector allocation exceptions propagate.
    bool build_even_smt(const Topology& topo, uint32_t n_ifid, uint32_t n_ex);

    void clear();

    void append(Role role, int cpu, uint32_t domain);

    static bool parse_u32(const char*& p, uint32_t& out);

    static bool parse_pair(const char*& p, uint32_t& left, uint32_t& right);

    std::vector<ThreadPlacement> threads_;
    std::vector<uint32_t> ifid_;
    std::vector<uint32_t> ex_;
    std::vector<uint32_t> shard_home_;
    std::vector<uint32_t> smt_peer_;
};

#include "placement_impl.h"

// ---------------------------------------------------------------------------------------------
// THE MIGRATION CONTRACT. Moving a physical shard rewrites the EX-owner bits of its bucket range
// behind Router's transfer descriptor. What makes it correct is the ordering around it:
//
//   1. Bring the old owner to an execution safe point. task_in.quiesced() tests the RETIRED
//      frontier; head == tail alone is insufficient because a popped task may still be executing.
//   2. Publish PREPARING, rewrite all entries while routing still resolves to the old owner, and
//      settle owner-local bookkeeping while both loops remain quiescent.
//   3. Publish COMMITTED once. Only then may the new owner touch the shard's store. A producer that
//      had already read the old route is forwarded by the old owner before shard access.
//
// Skipping step 2 puts two threads in one FlatStore, which has no locks precisely because that is
// supposed to be impossible — it would corrupt silently rather than crash.
// ---------------------------------------------------------------------------------------------
struct MigrationPlan {
    int32_t shard_id = -1;
    uint32_t from_thread = 0;
    uint32_t to_thread = 0;
    size_t cost_bytes = 0;  // what the new domain must re-pull; Shard::migration_cost_bytes()
};

}  // namespace tomo
