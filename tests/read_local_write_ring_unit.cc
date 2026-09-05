// read_local_write_ring_unit.cc -- server-less unit test for the ROB's armed RYOW write ring and
// the inline tag filter in front of it. Build and run with `make unit`.
//
// WHAT IS UNDER TEST. On a fused read-local connection the parser asks, for every read frame,
// whether an older write frame on the SAME connection may still be in flight to the same key:
//
//     rob.read_local_write_conflicts(hash, touches)
//
// True demotes the read to the owner queue behind that write; false lets it execute locally out of
// order. The owner's ruling is that reordering a read across a write on one connection is
// forbidden ONLY on explicit key conflict, so both answers are load-bearing:
//
//   RYOW (must never weaken): a write that is PUBLISHED and NOT YET RETIRED must be reported.
//                             A false negative here lets a read pass a write to its own key and
//                             return the pre-write value -- the one invariant that may not bend.
//   HOIST (the payoff):       a read whose key no live write touches must NOT be reported, or the
//                             optimisation buys nothing: every read would demote.
//
// The filter in front of the ring compares the low 16 bits of the hash. Equal hashes have equal
// tags, so a tag MISS proves no ring entry holds the hash -- that is the whole no-false-negative
// argument, and case 3 below is its adversarial half: two different keys whose tags collide must
// still resolve correctly through the exact walk.
//
// A DELIBERATELY BROKEN VARIANT MUST FAIL THIS TEST. Dropping the tag store in
// Rob::read_local_resolve_pending (`read_local_write_tags_[tail] = ...`) leaves the filter unable
// to see the write it just committed; cases 1, 4, 5 and the soak then report "missed live write"
// and the binary exits 1. Verified by building exactly that mutation.
#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <random>
#include <vector>

#include "src/net/conn.h"
#include "src/net/rob.h"

using namespace tomo;

namespace {

int failures = 0;

void note(const char* name, bool ok, const char* extra = "") {
    std::printf("  %s %s%s%s\n", ok ? "ok  " : "FAIL", name, *extra ? " " : "", extra);
    if (!ok) failures++;
}

// The point-op form of read_local_command_touches_hash (read_local.h): a non-MGET, non-MSET op
// reports exactly its own hash. Keeping it local keeps this test free of the command registry.
bool touches(const Op& op, uint64_t hash) { return op.hash == hash; }

// One connection's parser, driven frame by frame exactly as io_loop.h drives it.
class Frames {
public:
    Frames() { if (!rob_.prepare_read_local()) std::abort(); }

    // A write frame: acquire (which commits the PREVIOUS frame's staged candidate), stage, refine
    // to a precise point hash, publish. Mirrors the ordinary-point-write arm of the parser.
    void write(uint64_t hash) {
        Op* op = rob_.acquire_read_local(0);
        if (!op) std::abort();
        op->hash = hash;
        const uint64_t id = rob_.dispatch_id();
        rob_.mark_current_write();
        precise_.push_back(rob_.refine_current_write_hash(hash));
        rob_.publish();
        live_.push_back({id, hash});
    }

    // A write frame that never publishes: staged, then abandoned (the parser's refused-dispatch
    // and ACL-denial paths). Nothing executes, so nothing may be read back -- but the staged
    // candidate must not leak into the ring or leave the exact path forced on forever.
    void write_abandoned(uint64_t hash) {
        Op* op = rob_.acquire_read_local(0);
        if (!op) std::abort();
        op->hash = hash;
        rob_.mark_current_write();
        (void)rob_.refine_current_write_hash(hash);
        // no publish()
    }

    // A read frame. Returns the parser's verdict for this key.
    bool read(uint64_t hash) {
        Op* op = rob_.acquire_read_local(0);
        if (!op) std::abort();
        op->hash = hash;
        const bool conflict = rob_.read_local_write_conflicts(hash, touches);
        rob_.publish();
        return conflict;
    }

    // A probe with no acquire in front of it: the defensive contract stated in
    // read_local_write_conflicts_pending, exercised so it cannot rot.
    bool probe_without_acquire(uint64_t hash) {
        return rob_.read_local_write_conflicts(hash, touches);
    }

    // Retire the oldest `n` frames in order, as the sender does.
    void retire(uint32_t n) {
        for (uint32_t i = 0; i < n; i++) {
            const uint64_t id = rob_.flush_id();
            if (id == rob_.dispatch_id()) std::abort();
            rob_.at(id).state.store(OpState::Done, std::memory_order_release);
            if (rob_.drain([](Op&) {}) != 1) std::abort();
            while (!live_.empty() && live_.front().id <= id) live_.pop_front();
        }
    }

    void retire_all() { retire(rob_.in_flight()); }

    // Live == published and not yet retired: exactly the set RYOW must fence.
    bool live_write(uint64_t hash) const {
        for (const Write& w : live_) if (w.hash == hash) return true;
        return false;
    }
    uint32_t in_flight() const { return rob_.in_flight(); }
    bool all_precise() const {
        for (bool p : precise_) if (!p) return false;
        return true;
    }
    void clear_precise() { precise_.clear(); }

private:
    struct Write { uint64_t id; uint64_t hash; };
    Rob<kRobWindow> rob_;
    std::deque<Write> live_;
    std::vector<bool> precise_;
};

// Two hashes that differ but share the low 16 bits the filter compares.
constexpr uint64_t kKeyA      = 0x0000'0001'ABCD'1234ull;
constexpr uint64_t kTagTwinA  = 0x0000'0002'5678'1234ull;   // same tag as kKeyA, different key
constexpr uint64_t kKeyB      = 0x0000'0003'0F0F'9999ull;

// ---- 1. RYOW: a read of a key with a live write to it must be fenced, at every ring position ---
void test_ryow_same_key() {
    bool ok = true;
    for (uint32_t ahead = 0; ahead < ReadLocalRobState::kWriteRingCapacity; ahead++) {
        Frames f;
        f.write(kKeyA);
        // Bury it under `ahead` further live writes to unrelated keys, so the entry under test
        // sits at every distance from the ring head across the sweep.
        for (uint32_t i = 0; i < ahead; i++) f.write(0x5000'0000'0000'0000ull + i);
        if (!f.live_write(kKeyA)) std::abort();
        if (!f.read(kKeyA)) { ok = false; break; }
    }
    note("RYOW: live same-key write fences the read at every ring depth", ok);
}

// ---- 2. HOIST: a read of a key no live write touches must NOT be fenced -----------------------
void test_hoist_different_key() {
    Frames f;
    bool ok = true;
    for (uint32_t i = 0; i < ReadLocalRobState::kWriteRingCapacity; i++)
        f.write(0x7000'0000'0000'0000ull + i);
    if (!f.all_precise()) ok = false;                 // the ring recorded exact hashes, not a wall
    if (f.read(kKeyB)) ok = false;                    // disjoint key: free to execute out of order
    note("HOIST: disjoint read is not fenced by a full ring of precise writes", ok);
}

// ---- 3. tag collision: different keys, same low 16 bits -> exact walk must still say no --------
void test_tag_collision_rejects() {
    Frames f;
    f.write(kTagTwinA);
    bool ok = !f.read(kKeyA);
    note("tag collision on a different key does not fence the read", ok);
}

// ---- 4. tag collision must not mask the real thing --------------------------------------------
void test_tag_collision_with_real_write() {
    bool ok = true;
    {   // decoy first, then the real write
        Frames f;
        f.write(kTagTwinA);
        f.write(kKeyA);
        if (!f.read(kKeyA)) ok = false;
    }
    {   // real write first, then the decoy
        Frames f;
        f.write(kKeyA);
        f.write(kTagTwinA);
        if (!f.read(kKeyA)) ok = false;
    }
    note("a tag-colliding decoy never hides a live same-key write", ok);
}

// ---- 5. retirement is the removal fence -------------------------------------------------------
void test_retire_clears() {
    Frames f;
    f.write(kKeyA);
    bool ok = f.read(kKeyA);            // still in flight: fenced
    f.retire_all();                     // the write executed and its reply went out
    ok = ok && !f.read(kKeyA);          // now the store holds it; no fence, no demotion
    note("a retired write stops fencing (and the filter slot is released)", ok);
}

// ---- 6. an abandoned staged write commits nothing ---------------------------------------------
void test_abandoned_write() {
    Frames f;
    f.write_abandoned(kKeyA);
    // The staged candidate is still parked here: conservative TRUE is the documented contract.
    bool ok = f.probe_without_acquire(kKeyA);
    // The next acquire is the commit point, and an unadvanced dispatch id means "never published".
    ok = ok && !f.read(kKeyA) && !f.read(kKeyB);
    note("an abandoned write frame fences nothing after its commit point", ok);
}

// ---- 7. overflow stays conservative, and recovers ---------------------------------------------
void test_overflow_conservative() {
    Frames f;
    for (uint32_t i = 0; i <= ReadLocalRobState::kWriteRingCapacity; i++)
        f.write(0x9000'0000'0000'0000ull + i);
    bool ok = f.read(kKeyB);            // ring overflowed: every read is fenced, by design
    f.retire_all();
    ok = ok && !f.read(kKeyB);          // generation drained: precision comes back
    note("ring overflow fences conservatively and recovers on retirement", ok);
}

// ---- 8. an abandoned write must not cancel a live conservative generation -------------------
// The regression this pins: the staged candidate and the overflow generation share one "no tag can
// describe this" bit, and an earlier draft cleared it when the candidate turned out never to have
// published -- silently telling every later read that the overflow generation was gone.
void test_overflow_survives_abandoned_write() {
    Frames f;
    for (uint32_t i = 0; i <= ReadLocalRobState::kWriteRingCapacity; i++)
        f.write(0xA000'0000'0000'0000ull + i);      // ring overflows: hashes are discarded
    f.write_abandoned(kKeyA);                       // staged, then never published
    bool ok = f.read(kKeyB);                        // the generation is still live: still fenced
    note("an abandoned write does not cancel a live overflow generation", ok);
}

// ---- 9. randomised soak against the live-write reference model --------------------------------
// `depth_cap` decides which regime the soak runs in: below the ring capacity every write keeps its
// own precise entry and both verdicts must occur, while a cap above it drives the conservative
// overflow generation, where the invariant still holds but nothing is expected to be hoisted.
void test_soak(uint32_t depth_cap, bool expect_hoists, const char* label) {
    std::mt19937_64 rng(20260905);
    // A small key space with many low-16-bit collisions: every key is 0x1000...0000 + (i<<48) + i,
    // so keys i and j collide in the tag whenever (i & 0xFFFF) == (j & 0xFFFF) -- and half the
    // space is built to do exactly that.
    auto key = [](uint32_t i) -> uint64_t {
        return 0x1000'0000'0000'0000ull | (uint64_t{i} << 48) | uint64_t{i % 24};
    };
    Frames f;
    bool ok = true;
    uint64_t reads = 0, fenced = 0, hoisted = 0;
    for (uint32_t step = 0; step < 200000 && ok; step++) {
        const uint32_t roll = static_cast<uint32_t>(rng() % 100);
        if (f.in_flight() >= depth_cap) {
            f.retire(1 + static_cast<uint32_t>(rng() % 8));
            continue;
        }
        if (roll < 40) {
            f.write(key(static_cast<uint32_t>(rng() % 48)));
        } else if (roll < 90) {
            const uint64_t h = key(static_cast<uint32_t>(rng() % 48));
            const bool conflict = f.read(h);
            reads++;
            fenced += conflict;
            hoisted += !conflict;
            // THE INVARIANT. A live write to this key must always fence. The converse is not
            // asserted: a conservative extra fence is legal (overflow, tag-independent broad
            // generations), it only costs throughput.
            if (!conflict && f.live_write(h)) {
                note("soak", false, "missed live write");
                ok = false;
            }
        } else {
            const uint32_t n = 1 + static_cast<uint32_t>(rng() % 4);
            f.retire(std::min<uint32_t>(n, f.in_flight()));
        }
    }
    char extra[128];
    std::snprintf(extra, sizeof extra, "(%llu reads, %llu fenced, %llu hoisted)",
                  static_cast<unsigned long long>(reads),
                  static_cast<unsigned long long>(fenced),
                  static_cast<unsigned long long>(hoisted));
    // A soak that never fenced proves nothing about RYOW; in the precise regime one that never
    // hoisted proves nothing about the optimisation either.
    if (ok && (fenced == 0 || (expect_hoists && hoisted == 0))) {
        note(label, false, "vacuous: an outcome the regime requires never occurred");
        ok = false;
    }
    if (ok) note(label, true, extra);
}

}  // namespace

int main() {
    test_ryow_same_key();
    test_hoist_different_key();
    test_tag_collision_rejects();
    test_tag_collision_with_real_write();
    test_retire_clears();
    test_abandoned_write();
    test_overflow_conservative();
    test_overflow_survives_abandoned_write();
    test_soak(12, true, "soak precise ring: 200k frames, no live same-key write ever missed");
    test_soak(kRobWindow - 2, false,
              "soak overflow regime: 200k frames, no live same-key write ever missed");
    std::printf("read_local write ring unit: %s\n", failures ? "FAIL" : "ok");
    return failures ? 1 : 0;
}
