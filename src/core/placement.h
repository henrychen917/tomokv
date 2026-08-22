// placement.h — nodes, thread assignment, shard homing, and the migration contract.
//
// A NODE IS A COMPLETE UNIT: its own io threads, its own ex threads, its own shards, all pinned into
// ONE shared-L3 domain. That is the whole point and it is what the previous version was missing — it
// homed shards on nodes but let io threads land anywhere, so the io->ex handoff crossed L3 domains
// on nearly every operation, which is exactly the traffic a node exists to keep local.
//
// WHAT THE NODE BUYS. The dispatch hop moves a Task into a worker's inbox and the completion moves a
// pointer back; both are cache-line transfers between two threads. Inside one L3 those stay in that
// cache. Across domains they cross the fabric, where a CCX link saturates near 51 GB/s and a single
// core can already pull 50. On this box, sizing a node to exactly one L3 domain (8 physical cores,
// one CCX, 16 MB) was worth +22.3% on set_p16 and +14.2% on mget8 versus one wide node, with the
// optimum landing ON the cache boundary rather than near it.
//
// STILL NOT A FENCE. Routing is unchanged: shard = f(key), worker = worker_of_shard[shard], one
// atomic load. A key owned by node A can be dispatched by an io thread in node B — that costs the
// cross-domain hop, and the foreign_ops counter on the shard measures exactly how often it happens.
// A later LB moves work by storing a different thread id; nothing here forecloses that.
//
// SPREAD IS PER NODE, matching the fork's `tomokv-thread-io`/`-ex`, so --spread 4:4 --nodes 2 means
// eight io and eight ex threads in total. Per-node is the right unit because the split that matters
// is the one inside a node, where the handoff actually happens.
#pragma once
#include <atomic>
#include <cstdint>
#include <vector>
#include "shard.h"
#include "thread.h"
#include "../base/topology.h"

namespace tomo {

struct Node {
    uint32_t              id     = 0;
    uint32_t              domain = kNoDomain;   // the L3 domain this node is pinned into
    std::vector<int32_t>  shards;               // shard ids homed here
    std::vector<uint32_t> io;                   // io thread ids in this node
    std::vector<uint32_t> ex;                   // ex thread ids in this node
    std::vector<uint32_t> wb;                   // wb thread ids in this node (3s only)
    std::vector<int>      cpus;                 // cpus of the domain, for pinning
};

class Placement {
public:
    // `want_nodes == 0` means one node per L3 domain, which is the measured optimum and therefore
    // the default rather than something an operator has to know to ask for.
    //
    // CLAMPED BY BOTH the domain count and the thread budget: a node needs at least one io and one
    // ex thread of its own, so more nodes than we can staff would leave some with none. A node with
    // no threads is not a node, and silently creating one produces shards nobody serves.
    void build(const Topology& topo, uint32_t want_nodes, uint32_t nshards,
               uint32_t io_per_node, uint32_t ex_per_node, uint32_t wb_per_node) {
        nodes_.clear();
        const uint32_t nd = topo.ndomains() ? topo.ndomains() : 1;
        uint32_t n = want_nodes ? want_nodes : nd;
        if (n > nd) n = nd;                     // never more nodes than L3 domains
        if (n == 0) n = 1;
        if (nshards < n) n = nshards ? nshards : 1;   // every node must own at least one shard

        io_per_node_ = io_per_node ? io_per_node : 1;
        ex_per_node_ = ex_per_node ? ex_per_node : 1;
        wb_per_node_ = wb_per_node;
        nnodes_      = n;

        for (uint32_t i = 0; i < n; i++) {
            Node node;
            node.id     = i;
            node.domain = i % nd;
            node.cpus   = topo.cpus_in(node.domain);
            nodes_.push_back(std::move(node));
        }
        // Contiguous shard ranges per node, so a node owns a contiguous bucket range and a scan does
        // not have to touch every node.
        const uint32_t per = nshards / n;
        for (uint32_t s = 0; s < nshards; s++) {
            uint32_t ni = per ? (s / per) : 0;
            if (ni >= n) ni = n - 1;
            nodes_[ni].shards.push_back(static_cast<int32_t>(s));
        }
    }

    // Thread ids are dense and grouped BY NODE, so a node's io and ex threads are adjacent and land
    // in the same domain when pinned:
    //     node0: io... ex... wb...   node1: io... ex... wb...   ...
    // Grouping by node rather than by role is what keeps a node's handoff inside one L3.
    void assign_threads() {
        uint32_t tid = 0;
        for (auto& node : nodes_) {
            for (uint32_t k = 0; k < io_per_node_; k++) node.io.push_back(tid++);
            for (uint32_t k = 0; k < ex_per_node_; k++) node.ex.push_back(tid++);
            for (uint32_t k = 0; k < wb_per_node_; k++) node.wb.push_back(tid++);
        }
        total_threads_ = tid;
    }

    uint32_t nnodes()        const { return nnodes_; }
    uint32_t total_threads() const { return total_threads_; }
    uint32_t io_per_node()   const { return io_per_node_; }
    uint32_t ex_per_node()   const { return ex_per_node_; }
    uint32_t wb_per_node()   const { return wb_per_node_; }

    Node&       node(uint32_t i)       { return nodes_[i]; }
    const Node& node(uint32_t i) const { return nodes_[i]; }
    const std::vector<Node>& nodes() const { return nodes_; }

    // Role of a thread id, derived from the same dense layout assign_threads() built.
    Role role_of(uint32_t tid) const {
        for (const auto& n : nodes_) {
            for (uint32_t t : n.io) if (t == tid) return Role::Io;
            for (uint32_t t : n.ex) if (t == tid) return Role::Ex;
            for (uint32_t t : n.wb) if (t == tid) return Role::Wb;
        }
        return Role::Idle;
    }

    uint32_t node_of_thread(uint32_t tid) const {
        for (const auto& n : nodes_) {
            for (uint32_t t : n.io) if (t == tid) return n.id;
            for (uint32_t t : n.ex) if (t == tid) return n.id;
            for (uint32_t t : n.wb) if (t == tid) return n.id;
        }
        return 0;
    }

    // Which cpu a thread should pin to. Threads of a node take distinct cpus from that node's domain
    // so they share its L3 without sharing a core.
    int cpu_of_thread(uint32_t tid) const {
        for (const auto& n : nodes_) {
            uint32_t slot = 0;
            for (uint32_t t : n.io) { if (t == tid) return pick(n, slot); slot++; }
            for (uint32_t t : n.ex) { if (t == tid) return pick(n, slot); slot++; }
            for (uint32_t t : n.wb) { if (t == tid) return pick(n, slot); slot++; }
        }
        return -1;
    }

private:
    static int pick(const Node& n, uint32_t slot) {
        return n.cpus.empty() ? -1 : n.cpus[slot % n.cpus.size()];
    }

    std::vector<Node> nodes_;
    uint32_t nnodes_        = 0;
    uint32_t io_per_node_   = 1;
    uint32_t ex_per_node_   = 1;
    uint32_t wb_per_node_   = 0;
    uint32_t total_threads_ = 0;
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
