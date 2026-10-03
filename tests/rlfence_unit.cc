// RL1: serverless tests of the production ROB, with retirement deliberately withheld.
// No listener, worker loop or simulated replacement for the fence implementation.
#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include <string_view>
#include "src/net/conn.h"
#include "src/net/rob.h"

namespace {
using namespace tomo;
using Ring = Rob<kRobWindow>;
enum class Site { Op, Owner, Mask };

void require(bool ok, const char* message) {
    if (!ok) {
        std::fprintf(stderr, "FAIL rlfence: %s\n", message);
        std::exit(1);
    }
}

bool touches(const Op& op, uint64_t hash) { return op.hash == hash; }

void advance(Ring& rob, unsigned count) {
    for (unsigned i = 0; i < count; ++i) {
        Op* op = rob.acquire_read_local();
        require(op != nullptr, "advance acquires a slot");
        rob.publish();
        op->state.store(OpState::Done, std::memory_order_release);
        require(rob.drain([](Op&) {}) == 1, "advance retires one slot");
    }
}

uint64_t enqueue(Ring& rob, uint64_t hash, bool mget) {
    Op* op = rob.acquire_read_local();
    require(op != nullptr, "local read acquires a slot");
    op->hash = hash;
    op->mark_read_local();
    const uint64_t id = rob.dispatch_id();
    rob.mark_current_read_local_hash(id, hash);
    if (mget) rob.arm_current_local_mget_fence();
    op->state.store(OpState::Issued, std::memory_order_release);
    rob.publish();
    return id;
}

void complete(Ring& rob, Site site, uint64_t id) {
    switch (site) {
        case Site::Op: rob.complete_pending_read_local(id); break;
        case Site::Owner: rob.publish_pending_read_local_to_owner(id); break;
        case Site::Mask: rob.complete_pending_read_local_mask(Ring::read_local_slot_bit(id)); break;
    }
}

void symmetry() {
    // Exercise every physical slot in two ROB generations, including bit 63 and wrap to zero.
    // Direct bitmap fixtures also cover partial chunks; the parser normally drains older GETs
    // before accepting an MGET, but the completion API must preserve an uncovered fence.
    for (unsigned offset = 0; offset < 2 * kRobWindow; ++offset) {
        for (Site site : {Site::Op, Site::Owner, Site::Mask}) {
            Ring rob;
            advance(rob, offset);
            const uint64_t point = enqueue(rob, 11, false);
            const uint64_t mget = enqueue(rob, 22, true);
            require(rob.local_mget_fence_pending(), "fence was armed");
            rob.complete_pending_read_local_mask(0);
            require(rob.local_mget_fence_pending(), "empty mask preserves the armed fence");
            complete(rob, site, point);
            require(rob.local_mget_fence_pending() && rob.pending_read_local(mget) &&
                        rob.pending_read_local_count() == 1 && rob.read_local_pending_may_touch(22),
                    "all three sites preserve an uncovered MGET fence and pending key");
            complete(rob, site, mget);
            require(!rob.local_mget_fence_pending(),
                    "all three completion sites clear the covered MGET fence before retirement");
            require(!rob.has_pending_read_local() && !rob.read_local_pending_may_touch(22),
                    "all three completion sites clear the empty pending filter");
            require(rob.has_read_local_owner() == (site == Site::Owner),
                    "only owner publication adds owner slots");
            require(rob.flush_id() == offset && rob.in_flight() == 2,
                    "symmetry witness withheld ROB retirement");
            const uint64_t next = enqueue(rob, 33, true);
            require(rob.local_mget_fence_pending(), "next MGET rearms before retirement");
            complete(rob, site, next);
            require(!rob.local_mget_fence_pending(), "rearmed fence also clears");
        }
        Ring rob;
        advance(rob, offset);
        const uint64_t point = enqueue(rob, 11, false);
        const uint64_t mget = enqueue(rob, 22, true);
        rob.complete_pending_read_local_mask(Ring::read_local_slot_bit(point) |
                                             Ring::read_local_slot_bit(mget));
        require(!rob.local_mget_fence_pending() && !rob.has_pending_read_local(),
                "mixed chunk clears its covered MGET fence");
        // No fence is armed here; in particular bit 63 must not manufacture one from the sentinel.
        const uint64_t plain = enqueue(rob, 33, false);
        rob.complete_pending_read_local_mask(Ring::read_local_slot_bit(plain));
        require(!rob.local_mget_fence_pending(), "point-only completion leaves the sentinel clear");
    }
    std::puts("PASS rlfence symmetry (3 sites, 128 slot positions, partial/mixed/empty masks)");
}

void pipeline(unsigned count) {
    Ring rob;
    advance(rob, 53);  // p32 crosses the physical wrap while flush stays fixed.
    require(!rob.read_local_write_conflicts(22, touches) && rob.read_local_arm_state() == 0,
            "pipeline starts on an armed connection");
    Op* write = rob.acquire_read_local();
    require(write != nullptr, "older write acquires a slot");
    write->hash = 11;
    rob.mark_current_write();
    require(rob.refine_current_write_hash(11), "older write has a precise RYOW descriptor");
    write->state.store(OpState::Issued, std::memory_order_release);
    rob.publish();
    unsigned hits = 0;
    for (; hits < count && !rob.local_mget_fence_pending(); ++hits) {
        const uint64_t id = enqueue(rob, 22, true);
        require(!rob.read_local_write_conflicts(22, touches), "disjoint MGET stays eligible");
        require(rob.local_mget_fence_pending(), "each pipelined MGET actually arms the fence");
        rob.complete_pending_read_local_mask(Ring::read_local_slot_bit(id));
        rob.at(id).state.store(OpState::Done, std::memory_order_release);
        require(rob.read_local_write_conflicts(11, touches),
                "clearing the MGET fence preserves the older same-key RYOW hazard");
    }
    std::printf("rlfence pipeline N=%u lane_completions=%u retired=%llu\n", count, hits,
                static_cast<unsigned long long>(rob.flush_id() - 53));
    require(hits == count, "N MGETs complete locally before any ROB retirement");
    require(rob.drain([](Op&) {}) == 0 && rob.flush_id() == 53,
            "unfinished older write prevents every reply retirement");
    write->state.store(OpState::Done, std::memory_order_release);
    require(rob.drain([](Op&) {}) == count + 1, "all completed operations retire in order");
    require(!rob.read_local_write_conflicts(11, touches), "RYOW hazard ends only after retirement");
}
}  // namespace

int main(int argc, char** argv) {
    static_assert(sizeof(Ring) == 192);
    // The optional pipeline selection makes the old-code 1-vs-N witness visible independently
    // of the earlier symmetry failure; it changes no production behavior.
    require(argc == 1 || (argc == 2 && std::string_view(argv[1]) == "pipeline"),
            "usage: rlfence-unit [pipeline]");
    if (argc == 1) symmetry();
    pipeline(8);
    pipeline(32);
    std::puts("PASS rlfence (completion symmetry, pipelined MGET, RYOW, Rob<64>=192)");
}
