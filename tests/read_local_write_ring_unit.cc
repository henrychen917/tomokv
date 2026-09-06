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
// THE RING IS SIZED TO THE ROB WINDOW, so capacity overflow is unreachable: the live entries name
// distinct ids inside a window at most kRobWindow wide, and both insert sites prune to that set
// immediately before testing capacity. Case 10 is the assertion of that -- a reorder buffer
// saturated with precise writes, every one of which must keep an exact ring slot. The conservative
// generation that a full ring used to start is still ordinary traffic through the other door (a
// write that never refines: a wide multi-key write, or a point write under an evicting maxmemory
// policy), and cases 7, 8 and 11 drive it there, case 11 for four ring capacities in a row.
//
// DELIBERATELY BROKEN VARIANTS MUST FAIL THIS TEST, AND THE UNMUTATED TREE MUST PASS IT. A table
// where every mutation fails proves nothing unless the control passes, so scratchpad/ringsize/
// mutate.sh runs the unmutated tree first and then these six, and each line below is what it
// actually prints:
//   M1  ring back to sixteen slots            -> refused at compile time, by BOTH the sidecar
//                                                sizeof lock and the Rob's structural assert
//   M1b same, sizeof lock removed             -> still refused, by the structural assert alone
//   M1c same, both locks removed              -> cases 2, 10 and 12
//   M2  sweep stops after the first live group-> cases 10, 12 and both precise soaks, the soaks
//                                                reporting "missed live write"
//   M2b group walk skips every other group    -> case 10 and both precise soaks
//   M3  a conservative generation stops
//       forcing the exact walk                -> cases 7, 8, 11 and the conservative soak
//   M4  tag store dropped on ring insert
//       (the base lane's own mutation)        -> cases 1, 4, 5, 10, 12 and both precise soaks
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
    // ARM ON DEMAND (DESIGN-RINGDIET.md). A connection records its in-flight writes only after a
    // LOCAL READ has armed it, and the production door to arming is the write-conflict probe
    // itself. A fresh connection has nothing in flight, so arming through that door costs no
    // transient and every case below drives the ring exactly as it did when the sidecar was built
    // for every connection at accept. Construct with `false` to test the unarmed contract.
    explicit Frames(bool armed = true) {
        rob_.set_read_local_arm_stats(&stats_);
        if (armed) arm();
    }

    // One probe with no window position of its own: the first one arms the connection.
    void arm() { (void)rob_.read_local_write_conflicts(0x1ull, touches); }

    // 1 = unarmed, 2 = armed with pre-arming writes still in flight, 0 = armed and recording.
    uint32_t arm_state() const { return rob_.read_local_arm_state(); }
    const ReadLocalArmStats& stats() const { return stats_; }

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

    // A write frame that stages a hazard and never refines it: the parser's wide multi-key write,
    // and its ordinary point write under an evicting maxmemory policy. It takes no ring slot and no
    // tag can describe it, so it must become a conservative generation that fences every later read
    // until it retires. Since the ring now covers the whole ROB window this is the ONLY door left
    // to that machinery, which is exactly why the tests below drive it through here.
    void write_conservative(uint64_t hash) {
        Op* op = rob_.acquire_read_local(0);
        if (!op) std::abort();
        op->hash = hash;
        const uint64_t id = rob_.dispatch_id();
        rob_.mark_current_write();
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
    ReadLocalArmStats stats_{};
    Rob<kRobWindow> rob_;
    std::deque<Write> live_;
    std::vector<bool> precise_;
};

// Two hashes that differ but share the low 16 bits the filter compares.
constexpr uint64_t kKeyA      = 0x0000'0001'ABCD'1234ull;
constexpr uint64_t kTagTwinA  = 0x0000'0002'5678'1234ull;   // same tag as kKeyA, different key
constexpr uint64_t kKeyB      = 0x0000'0003'0F0F'9999ull;
constexpr uint64_t kKeyC      = 0x0000'0004'1357'2468ull;   // a third disjoint key

// ---- 1. RYOW: a read of a key with a live write to it must be fenced, at every ring position ---
void test_ryow_same_key() {
    bool ok = true;
    for (uint32_t ahead = 0; ahead + 2 <= kRobWindow; ahead++) {
        Frames f;
        f.write(kKeyA);
        // Bury it under `ahead` further live writes to unrelated keys, so the entry under test
        // sits at every distance from the ring head across the sweep.
        for (uint32_t i = 0; i < ahead; i++) f.write(0x5000'0000'0000'0000ull + i);
        if (!f.live_write(kKeyA)) std::abort();
        if (!f.read(kKeyA)) { ok = false; break; }
    }
    note("RYOW: live same-key write fences the read at every ring depth (to the ROB window)", ok);
}

// ---- 2. HOIST: a read of a key no live write touches must NOT be fenced -----------------------
void test_hoist_different_key() {
    Frames f;
    bool ok = true;
    for (uint32_t i = 0; i + 1 < kRobWindow; i++)
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
    f.write_conservative(0x9000'0000'0000'0000ull);
    bool ok = f.read(kKeyB);            // conservative generation: every read is fenced, by design
    f.retire_all();
    ok = ok && !f.read(kKeyB);          // generation drained: precision comes back
    note("a conservative generation fences every read and recovers on retirement", ok);
}

// ---- 8. an abandoned write must not cancel a live conservative generation -------------------
// The regression this pins: the staged candidate and the overflow generation share one "no tag can
// describe this" bit, and an earlier draft cleared it when the candidate turned out never to have
// published -- silently telling every later read that the overflow generation was gone.
void test_overflow_survives_abandoned_write() {
    Frames f;
    f.write_conservative(0xA000'0000'0000'0000ull); // a hazard no tag can describe
    f.write_abandoned(kKeyA);                       // staged, then never published
    bool ok = f.read(kKeyB);                        // the generation is still live: still fenced
    note("an abandoned write does not cancel a live conservative generation", ok);
}

// ---- 10. the ring covers the whole ROB window, so capacity overflow never happens -------------
// THE CASE THIS LANE EXISTS FOR. Saturate the reorder buffer with precise point writes -- one per
// window position but the one the probing read needs -- and require that EVERY one of them kept an
// exact ring slot. refine_current_write_hash() refusing even once would show up here twice over: as
// a false from all_precise(), and as the disjoint read being fenced by the conservative generation
// that refusal starts. Against a sixteen-slot ring this case fails on both counts.
void test_ring_covers_the_rob_window() {
    Frames f;
    bool ok = true;
    const uint32_t writes = kRobWindow - 1;             // the read below needs the last position
    for (uint32_t i = 0; i < writes; i++)
        f.write(0xF000'0000'0000'0000ull | (uint64_t{i} << 24) | i);
    if (!f.all_precise()) ok = false;                   // no write was ever refused for capacity
    if (f.read(kKeyB)) ok = false;                      // and so no read is fenced by a wall
    // RYOW still holds for every one of them, at every distance from the ring head. These probes
    // take no window position of their own, which is why they can all run against a full ROB.
    for (uint32_t i = 0; i < writes && ok; i++)
        if (!f.probe_without_acquire(0xF000'0000'0000'0000ull | (uint64_t{i} << 24) | i))
            ok = false;
    char extra[64];
    std::snprintf(extra, sizeof extra, "(%u live writes)", writes);
    note("a ROB saturated with precise writes never overflows the ring", ok, extra);
}

// ---- 11. drive far past the ring capacity through the door that is still open ------------------
// Capacity overflow is unreachable now, but the conservative generation it used to start is not
// dead code: every write that cannot refine -- a wide multi-key write, or a point write under an
// evicting maxmemory policy -- is one. Run four ring capacities of them, with precise writes and
// retirements interleaved so the FIFO wraps repeatedly, and require the fence to hold throughout
// and to lift once the last one drains.
void test_conservative_run_past_capacity() {
    Frames f;
    bool ok = true;
    for (uint32_t i = 0; i < 4 * ReadLocalRobState::kWriteRingCapacity && ok; i++) {
        f.write_conservative(0xB000'0000'0000'0000ull | (uint64_t{i} << 24) | i);
        if (i % 3 == 0) f.write(0xC000'0000'0000'0000ull | (uint64_t{i} << 24) | i);
        if (!f.read(kKeyB)) ok = false;                 // a generation is live: fenced
        if (f.in_flight() > kRobWindow - 8) f.retire(f.in_flight() / 2);
    }
    f.retire_all();
    ok = ok && !f.read(kKeyB);                          // fully drained: precision comes back
    note("a conservative run four times the ring capacity fences throughout and recovers", ok);
}

// ---- 12. the tag mirror describes every window position, not just the first sixteen ------------
void test_tag_collision_deep_in_the_ring() {
    Frames f;
    for (uint32_t i = 0; i < 40; i++) f.write(0xD000'0000'0000'0000ull | (uint64_t{i} << 20));
    f.write(kTagTwinA);                                 // decoy past the old capacity
    f.write(kKeyA);                                     // and the real write past it too
    for (uint32_t i = 0; i < 8; i++) f.write(0xE000'0000'0000'0000ull | (uint64_t{i} << 20));
    const bool ok = f.read(kKeyA) && !f.read(kKeyB);
    note("a same-key write past the old sixteen-slot ring is still found, its tag twin still not",
         ok);
}

// ==============================================================================================
// ARM ON DEMAND (DESIGN-RINGDIET.md). The ring is sized to the ROB window and therefore records
// EVERY write -- including on a connection where no read will ever consult the record. Cases 13
// to 17 are the directed test for the fix: a connection records nothing until a local read arms
// it, the writes it published before that arming are fenced wholesale until they retire, and the
// fence is one-shot -- it is never extended by the writes that arrive after arming, or an
// interleaved connection would never be served locally again.
// ----------------------------------------------------------------------------------------------

// ---- 13. an unarmed connection does ZERO ring bookkeeping -------------------------------------
// The first proof obligation, stated as the counters INFO reports: a pure-write connection commits
// no descriptor and never even allocates the 1216-byte sidecar the ring lives in.
void test_unarmed_records_nothing() {
    Frames f(false);
    bool ok = true;
    for (uint32_t i = 0; i < kRobWindow - 1; i++)
        f.write(0x2000'0000'0000'0000ull | (uint64_t{i} << 24) | i);
    if (f.arm_state() != 1) ok = false;                  // still unarmed
    if (f.stats().arms != 0) ok = false;
    if (f.stats().sidecars != 0) ok = false;             // no sidecar: nothing to write into
    if (f.stats().write_ring_records != 0) ok = false;   // and nothing written
    char extra[96];
    std::snprintf(extra, sizeof extra, "(%u writes, %llu records, %llu sidecars)",
                  kRobWindow - 1,
                  static_cast<unsigned long long>(f.stats().write_ring_records),
                  static_cast<unsigned long long>(f.stats().sidecars));
    note("a connection no read has armed does zero ring bookkeeping", ok, extra);
}

// ---- 14. a read arriving with unarmed writes in flight is DEMOTED, never served ---------------
// The safety half. Nothing describes those writes, so the read cannot be cleared against them --
// on its own key (RYOW, which may never bend) or on any other (the transient is conservative).
void test_unarmed_write_demotes_the_arming_read() {
    bool ok = true;
    {   // same key: the RYOW case
        Frames f(false);
        f.write(kKeyA);
        if (!f.read(kKeyA)) ok = false;
        if (f.arm_state() != 2) ok = false;              // armed, transient live
    }
    {   // a disjoint key is demoted too: no descriptor exists to clear it against
        Frames f(false);
        f.write(kKeyA);
        if (!f.read(kKeyB)) ok = false;
    }
    {   // and a write buried under a full window of unarmed writes is still fenced
        Frames f(false);
        f.write(kKeyA);
        for (uint32_t i = 0; i + 3 < kRobWindow; i++)
            f.write(0x3000'0000'0000'0000ull | (uint64_t{i} << 24) | i);
        if (!f.read(kKeyA)) ok = false;
    }
    note("a read that arrives with unarmed writes in flight is demoted, never served stale", ok);
}

// ---- 15. the transient is bounded by ONE ROB drain and then it is over ------------------------
void test_arm_transient_is_bounded() {
    Frames f(false);
    bool ok = true;
    const uint32_t pre = 8;
    for (uint32_t i = 0; i < pre; i++)
        f.write(0x4000'0000'0000'0000ull | (uint64_t{i} << 24) | i);
    // Every read published while any pre-arming write is still in flight is demoted. The bound is
    // structural: those reads share the ROB window with the writes that fence them.
    uint32_t demoted = 0;
    while (f.in_flight() < kRobWindow) {
        if (f.read(kKeyB)) demoted++;
        else { ok = false; break; }                      // must not be served while they are live
    }
    if (demoted > kRobWindow - pre) ok = false;
    f.retire_all();                                      // the pre-arming generation drains
    if (f.read(kKeyB)) ok = false;                       // and precision comes back
    if (f.arm_state() != 0) ok = false;
    char extra[80];
    std::snprintf(extra, sizeof extra, "(%u demoted, bound %u)", demoted, kRobWindow - pre);
    note("the arming transient is bounded by one ROB drain and then lifts", ok, extra);
}

// ---- 16. THE CASE THIS LANE EXISTS FOR: the fence is never extended ---------------------------
// The obvious implementation reuses the ring's conservative OVERFLOW generation for the transient.
// That is wrong, and silently so: an overflow generation is extended by every write published
// while it is live, so on a 1:1 connection -- which always has a write in flight -- it would never
// end, and not one read would ever be served locally again. The transient's fence is fixed at
// arming; writes that arrive after it take ordinary ring slots underneath it.
void test_arm_fence_is_not_extended_by_later_writes() {
    Frames f(false);
    bool ok = true;
    f.write(kKeyA);                                      // unarmed: recorded nowhere
    if (!f.read(kKeyB)) ok = false;                      // arms, and is fenced by the transient
    f.write(kKeyC);                                      // armed: this one DOES take a ring slot
    if (!f.read(kKeyB)) ok = false;                      // pre-arming write still live: fenced
    f.retire_all();                                      // ... and now it is not
    // Steady state, with writes in flight throughout: disjoint reads are served, same-key reads
    // are fenced, and neither answer depends on the transient any more.
    for (uint32_t round = 0; round < 32 && ok; round++) {
        f.write(kKeyC);
        if (f.read(kKeyB)) ok = false;                   // disjoint: 100% local service
        if (!f.read(kKeyC)) ok = false;                  // same key: exactly fenced
        f.retire(f.in_flight());
    }
    if (f.arm_state() != 0) ok = false;
    if (f.stats().write_ring_records == 0) ok = false;    // the armed writes really were recorded
    if (f.stats().sidecars != 1) ok = false;              // allocated once, at the first armed write
    char extra[96];
    std::snprintf(extra, sizeof extra, "(%llu records, %llu arms)",
                  static_cast<unsigned long long>(f.stats().write_ring_records),
                  static_cast<unsigned long long>(f.stats().arms));
    note("the arming fence is one-shot: an interleaved connection returns to full local service",
         ok, extra);
}

// ---- 17. arming costs one sidecar per connection, and only for connections that need one -------
void test_sidecar_is_paid_only_by_read_write_connections() {
    bool ok = true;
    {   Frames f(false);                                  // pure writes
        for (uint32_t i = 0; i < 16; i++) f.write(0x5100'0000'0000'0000ull | i);
        if (f.stats().sidecars != 0 || f.stats().arms != 0) ok = false;
    }
    {   Frames f(false);                                  // pure reads
        for (uint32_t i = 0; i < 16; i++)
            if (f.read(0x5200'0000'0000'0000ull | i)) ok = false;
        if (f.stats().sidecars != 0) ok = false;          // armed, but nothing to record
        if (f.stats().arms != 1) ok = false;
    }
    {   Frames f(false);                                  // reads and writes
        (void)f.read(kKeyB);
        f.write(kKeyA);
        if (f.stats().sidecars != 1) ok = false;          // born at the first ARMED write
        // The staged candidate commits at the NEXT armed acquire -- that is the ring's commit
        // point, not the write frame itself -- so drive one more frame before counting records.
        (void)f.read(kKeyC);
        if (f.stats().write_ring_records != 1) ok = false;
        if (!f.probe_without_acquire(kKeyA)) ok = false;   // and the descriptor is the real one
    }
    note("only a connection that both reads and writes ever allocates a RYOW sidecar", ok);
}

// ---- 9. randomised soak against the live-write reference model --------------------------------
// `depth_cap` sets how deep the ROB is allowed to run and `conservative_pct` how often a write
// arrives through the door that takes no ring slot. With none of those every write keeps its own
// precise entry and both verdicts must occur -- at any depth now, which is the point of running one
// arm at the full window. With most of them the connection lives inside a conservative generation,
// where the invariant still holds but nothing is expected to be hoisted.
void test_soak(uint32_t depth_cap, uint32_t conservative_pct, bool expect_hoists,
               const char* label, bool armed = true) {
    std::mt19937_64 rng(20260905);
    // A small key space with many low-16-bit collisions: every key is 0x1000...0000 + (i<<48) + i,
    // so keys i and j collide in the tag whenever (i & 0xFFFF) == (j & 0xFFFF) -- and half the
    // space is built to do exactly that.
    auto key = [](uint32_t i) -> uint64_t {
        return 0x1000'0000'0000'0000ull | (uint64_t{i} << 48) | uint64_t{i % 24};
    };
    Frames f(armed);
    bool ok = true;
    uint64_t reads = 0, fenced = 0, hoisted = 0;
    for (uint32_t step = 0; step < 200000 && ok; step++) {
        const uint32_t roll = static_cast<uint32_t>(rng() % 100);
        if (f.in_flight() >= depth_cap) {
            f.retire(1 + static_cast<uint32_t>(rng() % 8));
            continue;
        }
        if (roll < 40) {
            const uint64_t h = key(static_cast<uint32_t>(rng() % 48));
            if (rng() % 100 < conservative_pct) f.write_conservative(h);
            else f.write(h);
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
    test_ring_covers_the_rob_window();
    test_conservative_run_past_capacity();
    test_tag_collision_deep_in_the_ring();
    test_unarmed_records_nothing();
    test_unarmed_write_demotes_the_arming_read();
    test_arm_transient_is_bounded();
    test_arm_fence_is_not_extended_by_later_writes();
    test_sidecar_is_paid_only_by_read_write_connections();
    test_soak(12, 0, true, "soak shallow precise ring: 200k frames, no live write ever missed");
    test_soak(kRobWindow - 2, 0, true,
              "soak precise ring at the full ROB window: 200k frames, no live write ever missed");
    test_soak(kRobWindow - 2, 70, false,
              "soak conservative regime: 200k frames, no live same-key write ever missed");
    test_soak(kRobWindow - 2, 0, true,
              "soak from UNARMED: 200k frames across the arming transition, none served stale",
              false);
    std::printf("read_local write ring unit: %s\n", failures ? "FAIL" : "ok");
    return failures ? 1 : 0;
}
