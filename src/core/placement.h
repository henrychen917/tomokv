// placement.h — nodes, shard assignment, and the migration primitive.
//
// NODES ARE BACK, ALIGNED TO SHARED L3. A node is a group of shards plus the workers that serve
// them, sized to one last-level-cache domain. This recovers a measured gain: on this box the node
// optimum lands exactly ON the cache boundary — 8 physical cores, one CCX, one 16 MB L3 — and was
// worth +22.3% on set_p16 and +14.2% on mget8 versus one wide node. Writes and multi-key gain most,
// because they cross the boundary with more DIRTY lines per operation than a read does.
//
// BUT A NODE IS A DEFAULT, NOT A FENCE. This is the whole point of the file. Nothing in the dispatch
// path knows about nodes:
//
//     shard = router.shard_of(hash)          // pure function of the key, never changes
//     worker = worker_of_shard[shard]        // ONE atomic load, freely rewritable
//
// A load balancer moves work by storing a different thread id into worker_of_shard[]. Any shard can
// be pointed at any thread, in any node, at any time — pointer handoff anywhere. The Channel mesh
// already supports it: every thread has an inbound channel from every other thread, so a cross-node
// handoff uses exactly the same path as a same-node one and costs the same instructions.
//
// So node placement is initial policy plus a locality signal, and the LB is free to override it when
// load says it should. What node placement must NOT become is an assumption baked into the hot path,
// because then the LB could not override it at all.
//
// WHAT MIGRATION ACTUALLY COSTS. An L3 domain is filled by access, not allocated into. Reassigning a
// shard does not move its memory — it invalidates its residency, and the new owner must re-pull the
// working set through the fabric, where a CCX link saturates near 51 GB/s. Shard::migration_cost_bytes()
// prices it. An LB that treats a move as free will thrash; the fork already produced that failure.
#pragma once
#include <atomic>
#include <cstdint>
#include <vector>
#include "shard.h"
#include "thread.h"
#include "../base/topology.h"

namespace tomo {

struct Node {
    uint32_t              id      = 0;
    uint32_t              domain  = kNoDomain;   // the L3 domain this node is aligned to
    std::vector<int32_t>  shards;                // shard ids homed here
    std::vector<uint32_t> workers;               // thread ids serving this node by default
    std::vector<int>      cpus;                  // cpus in the domain, for pinning
};

class Placement {
public:
    // Builds nodes from the discovered topology. `want_nodes == 0` means "one per L3 domain", which
    // is the measured optimum and should be the default rather than something an operator has to
    // know to ask for.
    //
    // CLAMPED TO THE WORKER COUNT, and that clamp is load-bearing. With 16 L3 domains and 8 workers,
    // an unclamped build gives eight nodes no worker of their own; they all fall back to the same
    // thread, and one worker ends up owning the shards of nine nodes. The fallback keeps every shard
    // owned — an unowned shard would time out every key in its range — but it produces exactly the
    // imbalance node placement exists to avoid. A node with no worker is not a node.
    void build(const Topology& topo, uint32_t want_nodes, uint32_t nshards, uint32_t nworkers) {
        nodes_.clear();
        const uint32_t nd = topo.ndomains() ? topo.ndomains() : 1;
        uint32_t n = want_nodes ? want_nodes : nd;
        if (nworkers && n > nworkers) n = nworkers;
        if (n == 0) n = 1;

        for (uint32_t i = 0; i < n; i++) {
            Node node;
            node.id     = i;
            node.domain = (i < nd) ? i : kNoDomain;
            if (node.domain != kNoDomain) node.cpus = topo.cpus_in(node.domain);
            nodes_.push_back(std::move(node));
        }
        // Shards spread across nodes. Contiguous rather than round-robin so a node owns a
        // contiguous bucket range, which keeps range operations from touching every node.
        const uint32_t per = nshards / n;
        for (uint32_t s = 0; s < nshards; s++) {
            uint32_t ni = per ? (s / per) : 0;
            if (ni >= n) ni = n - 1;
            nodes_[ni].shards.push_back(static_cast<int32_t>(s));
        }
    }

    // Assigns worker threads to nodes and records the initial shard -> worker mapping.
    void assign_workers(const std::vector<uint32_t>& worker_ids) {
        if (nodes_.empty() || worker_ids.empty()) return;
        for (size_t i = 0; i < worker_ids.size(); i++)
            nodes_[i % nodes_.size()].workers.push_back(worker_ids[i]);

        // A node with no worker of its own falls back to the first available worker rather than
        // leaving its shards unowned. Silently unowned shards would make every key in that range
        // time out, which is a far worse failure than a suboptimal placement.
        for (auto& node : nodes_)
            if (node.workers.empty()) node.workers.push_back(worker_ids[0]);
    }

    uint32_t nnodes() const { return static_cast<uint32_t>(nodes_.size()); }
    Node&       node(uint32_t i)       { return nodes_[i]; }
    const Node& node(uint32_t i) const { return nodes_[i]; }

    // Which node a shard is homed in. Linear over nodes, called at setup only, never on the hot path.
    uint32_t node_of_shard(int32_t shard_id) const {
        for (const auto& n : nodes_)
            for (int32_t s : n.shards) if (s == shard_id) return n.id;
        return 0;
    }

    const std::vector<Node>& nodes() const { return nodes_; }

private:
    std::vector<Node> nodes_;
};

// ---------------------------------------------------------------------------------------------
// THE MIGRATION PRIMITIVE.
//
// Moving a shard is a single store into worker_of_shard[]. What makes it correct is not the store —
// it is the ordering around it:
//
//   1. Stop routing new ops to the old owner (the store does this; it is a release).
//   2. WAIT for the old owner to finish what it already has. That is task_in.quiesced(), which
//      tests the RETIRED frontier, not depth() == 0 — head == tail only means "nothing left to
//      pop", and the worker may still be executing what it popped.
//   3. Only then may the new owner touch the shard's store.
//
// Skipping step 2 puts two threads in one FlatStore, which has no locks precisely because that is
// supposed to be impossible. It would corrupt silently rather than crash.
//
// This is written as a documented contract rather than an implementation because the LB that will
// drive it does not exist yet, and a half-built migration path is worse than none.
// ---------------------------------------------------------------------------------------------
struct MigrationPlan {
    int32_t  shard_id   = -1;
    uint32_t from_thread = 0;
    uint32_t to_thread   = 0;
    size_t   cost_bytes  = 0;    // what the new domain must re-pull; Shard::migration_cost_bytes()
};

}  // namespace tomo
