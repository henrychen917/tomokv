// read_local_ring_unit.cc -- server-less unit test for ReadLocalRetireRing, the index/batch
// bookkeeping under the fused owner's deferred-reclaim (QSBR) ring. Build and run with `make unit`.
//
// The ring's contract is the whole safety argument for deferred frees, so it is checked against a
// per-entry reference model: every pushed entry is individually stamped with the epoch of the seal
// that covered it, and an entry may be released only when the floor is strictly above its stamp.
//   - drain_below must release EXACTLY the reference set while the batch ring is not full
//     (per-batch stamps are then a pure re-encoding of per-entry stamps);
//   - with the batch ring full (folding), it must release a SUBSET of the reference set, in FIFO
//     order, and everything eventually (a fold can only delay, never free early);
//   - unsealed entries are never released by drain_below; drain_all releases everything.
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <deque>
#include <random>
#include <vector>

#include "src/core/read_local.h"

using namespace tomo;

namespace {

[[noreturn]] void fail(const char* message, uint64_t a = 0, uint64_t b = 0) {
    std::fprintf(stderr, "read_local ring unit: %s (%llu, %llu)\n", message,
                 static_cast<unsigned long long>(a), static_cast<unsigned long long>(b));
    std::exit(1);
}

struct Reference {
    struct Item { uint32_t slot; uint64_t stamp; bool sealed; };
    std::deque<Item> items;
    void push(uint32_t slot) { items.push_back({slot, 0, false}); }
    void seal(uint64_t stamp) {
        for (Item& item : items) if (!item.sealed) { item.sealed = true; item.stamp = stamp; }
    }
    // Slots the per-entry rule would release, oldest first.
    std::vector<uint32_t> releasable(uint64_t floor) const {
        std::vector<uint32_t> out;
        for (const Item& item : items) {
            if (!item.sealed || item.stamp >= floor) break;
            out.push_back(item.slot);
        }
        return out;
    }
    void pop(uint32_t n) { items.erase(items.begin(), items.begin() + n); }
};

void expect_slots(const std::vector<uint32_t>& got, const std::vector<uint32_t>& want,
                  const char* what) {
    if (got.size() != want.size()) fail(what, got.size(), want.size());
    for (size_t i = 0; i < got.size(); i++)
        if (got[i] != want[i]) fail(what, got[i], want[i]);
}

// Basic FIFO, stamp boundary, unsealed protection, shutdown drain.
void test_basic() {
    ReadLocalRetireRing ring;
    if (!ring.empty() || ring.full() || ring.has_sealed()) fail("fresh ring state");
    for (uint32_t i = 0; i < 10; i++)
        if (ring.push() != i) fail("push returns sequential slots", i);
    if (ring.count != 10 || ring.unsealed != 10) fail("count after push", ring.count, ring.unsealed);

    std::vector<uint32_t> got;
    auto collect = [&](uint32_t slot) { got.push_back(slot); };
    if (ring.drain_below(UINT64_MAX, collect) != 0 || !got.empty()) fail("unsealed never drained");

    if (ring.seal(100) != 10 || ring.unsealed != 0 || !ring.has_sealed()) fail("seal count");
    if (ring.head_stamp() != 100) fail("head stamp", ring.head_stamp());
    if (ring.seal(101) != 0) fail("empty seal is a no-op");
    if (ring.drain_below(100, collect) != 0 || !got.empty()) fail("floor == stamp keeps batch");
    if (ring.drain_below(101, collect) != 10) fail("floor > stamp releases batch");
    for (uint32_t i = 0; i < 10; i++) if (got[i] != i) fail("FIFO order", got[i], i);
    if (!ring.empty() || ring.has_sealed()) fail("empty after drain");

    for (uint32_t i = 0; i < 5; i++) ring.push();
    ring.seal(200);
    for (uint32_t i = 0; i < 3; i++) ring.push();
    got.clear();
    if (ring.drain_all(collect) != 8 || got.size() != 8) fail("drain_all releases sealed+unsealed");
    for (uint32_t i = 0; i < 8; i++) if (got[i] != 10 + i) fail("drain_all order", got[i], 10 + i);
    if (!ring.empty() || ring.unsealed || ring.has_sealed()) fail("state after drain_all");
}

// Two batches, partial release, then the rest.
void test_two_batches() {
    ReadLocalRetireRing ring;
    for (uint32_t i = 0; i < 4; i++) ring.push();
    ring.seal(10);
    for (uint32_t i = 0; i < 6; i++) ring.push();
    ring.seal(20);
    std::vector<uint32_t> got;
    auto collect = [&](uint32_t slot) { got.push_back(slot); };
    if (ring.drain_below(15, collect) != 4) fail("first batch only");
    if (ring.count != 6 || ring.head_stamp() != 20) fail("second batch intact", ring.count);
    if (ring.drain_below(20, collect) != 0) fail("floor == second stamp keeps it");
    if (ring.drain_below(21, collect) != 6) fail("second batch released");
    expect_slots(got, {0, 1, 2, 3, 4, 5, 6, 7, 8, 9}, "two-batch order");
}

// Full entry ring, wraparound of both indices, exact match with the reference model.
void test_wraparound_and_full() {
    ReadLocalRetireRing ring;
    Reference ref;
    uint64_t epoch = 1;
    uint32_t next_slot = 0;
    std::mt19937_64 rng(7);
    std::vector<uint32_t> got;
    for (uint32_t round = 0; round < 2000; round++) {
        const uint32_t pushes = static_cast<uint32_t>(rng() % 64);
        for (uint32_t i = 0; i < pushes && !ring.full(); i++) {
            const uint32_t slot = ring.push();
            if (slot != next_slot) fail("slot sequence", slot, next_slot);
            next_slot = (next_slot + 1) & (ReadLocalRetireRing::kCapacity - 1);
            ref.push(slot);
        }
        if (rng() % 3 == 0) { ring.seal(epoch); ref.seal(epoch); epoch++; }
        if (rng() % 2 == 0) {
            // Random floor in the recent past; sometimes exactly a stamp value.
            const uint64_t floor = epoch > 5 ? epoch - (rng() % 5) : 0;
            const std::vector<uint32_t> want = ref.releasable(floor);
            got.clear();
            const uint32_t drained = ring.drain_below(floor, [&](uint32_t s) { got.push_back(s); });
            if (drained != got.size()) fail("drain count vs callbacks", drained, got.size());
            expect_slots(got, want, "random drain matches per-entry reference");
            ref.pop(static_cast<uint32_t>(want.size()));
        }
        if (ring.count != ref.items.size()) fail("count tracks reference", ring.count, ref.items.size());
    }
    // Fill to capacity, then release everything through sealed batches.
    while (!ring.full()) { ref.push(ring.push()); }
    if (ring.count != ReadLocalRetireRing::kCapacity) fail("full count");
    ring.seal(epoch); ref.seal(epoch); epoch++;
    got.clear();
    const std::vector<uint32_t> want = ref.releasable(epoch);
    if (ring.drain_below(epoch, [&](uint32_t s) { got.push_back(s); }) != want.size())
        fail("full ring drains completely", got.size(), want.size());
    expect_slots(got, want, "full ring order");
    if (!ring.empty()) fail("empty after full drain");
}

// Batch ring overflow: folding may only delay entries, never release them early, and must keep
// FIFO order and eventual release.
void test_batch_fold() {
    ReadLocalRetireRing ring;
    Reference ref;
    uint64_t epoch = 1000;
    // kBatchCapacity single-entry batches fill the batch ring.
    for (uint32_t i = 0; i < ReadLocalRetireRing::kBatchCapacity; i++) {
        ref.push(ring.push());
        ring.seal(epoch); ref.seal(epoch); epoch++;
    }
    if (ring.batch_count != ReadLocalRetireRing::kBatchCapacity) fail("batch ring full");
    // Three more seals fold into the newest batch.
    for (uint32_t i = 0; i < 3; i++) {
        ref.push(ring.push()); ref.push(ring.push());
        ring.seal(epoch); ref.seal(epoch); epoch++;
    }
    if (ring.batch_count != ReadLocalRetireRing::kBatchCapacity) fail("fold keeps batch count");
    const uint64_t newest_stamp = epoch - 1;
    // Floor above the pre-fold stamp of the newest original batch but below the folded stamp: the
    // reference would release that batch's single entry; the folded ring must NOT (delay only).
    std::vector<uint32_t> got;
    const uint64_t mid_floor = 1000 + ReadLocalRetireRing::kBatchCapacity;   // > last original stamp
    const std::vector<uint32_t> want = ref.releasable(mid_floor);
    ring.drain_below(mid_floor, [&](uint32_t s) { got.push_back(s); });
    if (got.size() > want.size()) fail("fold released early", got.size(), want.size());
    if (got.size() != ReadLocalRetireRing::kBatchCapacity - 1)
        fail("all unfolded batches released", got.size());
    for (size_t i = 0; i < got.size(); i++) if (got[i] != want[i]) fail("fold order", got[i], want[i]);
    ref.pop(static_cast<uint32_t>(got.size()));
    got.clear();
    if (ring.drain_below(newest_stamp, [&](uint32_t s) { got.push_back(s); }) != 0)
        fail("folded batch waits for the newer stamp");
    if (ring.drain_below(newest_stamp + 1, [&](uint32_t s) { got.push_back(s); }) != 7)
        fail("folded batch releases as one", got.size());
    std::vector<uint32_t> rest;
    for (const Reference::Item& item : ref.items) rest.push_back(item.slot);
    expect_slots(got, rest, "folded batch order");
    if (!ring.empty() || ring.has_sealed()) fail("empty after fold drain");
}

}  // namespace

int main() {
    test_basic();
    test_two_batches();
    test_wraparound_and_full();
    test_batch_fold();
    std::printf("read_local ring unit: ok\n");
    return 0;
}
