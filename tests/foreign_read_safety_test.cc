#include <array>
#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include <limits>

#define TOMO_FOREIGN_READ_SAFETY_TEST
#include "src/store/foreign_read_safety.h"

using tomo::ForeignReadSafety;

namespace {

[[noreturn]] void fail(const char* message) {
    std::fprintf(stderr, "foreign-read-safety unit: %s\n", message);
    std::exit(1);
}

void require(bool condition, const char* message) {
    if (!condition) fail(message);
}

void add(ForeignReadSafety& safety, std::initializer_list<uint64_t> hashes) {
    const uint64_t* begin = hashes.begin();
    safety.add_span(static_cast<uint32_t>(hashes.size()),
                    [begin](uint32_t index) { return begin[index]; });
}

void close_refs(ForeignReadSafety& safety, std::initializer_list<uint64_t> hashes) {
    const uint64_t* begin = hashes.begin();
    safety.close_span(static_cast<uint32_t>(hashes.size()),
                      [begin](uint32_t index) { return begin[index]; });
}

struct CollisionSet {
    uint64_t first = 0;
    uint64_t second = 0;
    uint64_t third = 0;
};

CollisionSet find_three_fingerprints_in_one_cell() {
    struct Seen {
        std::array<uint64_t, 3> hashes{};
        std::array<uint32_t, 3> fingerprints{};
        uint32_t count = 0;
    };
    std::array<Seen, ForeignReadSafety::kCellCount> seen{};
    for (uint64_t hash = 1; hash != 20000000; hash++) {
        const uint32_t cell = ForeignReadSafety::cell_index(hash);
        const uint32_t fingerprint = ForeignReadSafety::fingerprint(hash);
        Seen& bucket = seen[cell];
        bool duplicate = false;
        for (uint32_t i = 0; i < bucket.count; i++)
            duplicate |= bucket.fingerprints[i] == fingerprint;
        if (duplicate) continue;
        bucket.hashes[bucket.count] = hash;
        bucket.fingerprints[bucket.count] = fingerprint;
        if (++bucket.count == 3)
            return CollisionSet{bucket.hashes[0], bucket.hashes[1], bucket.hashes[2]};
    }
    fail("could not synthesize three distinct fingerprints in one filter cell");
}

uint64_t find_hash_in_another_cell(uint64_t hash) {
    const uint32_t excluded = ForeignReadSafety::cell_index(hash);
    for (uint64_t candidate = 1; candidate != 1000000; candidate++)
        if (ForeignReadSafety::cell_index(candidate) != excluded) return candidate;
    fail("could not synthesize a hash in another filter cell");
}

void require_empty(const ForeignReadSafety& safety, const char* message) {
    require(safety.unsafe_total_refs() == 0, message);
    require(safety.occupied_cells() == 0, message);
    require(safety.wildcard_cells() == 0, message);
    require(safety.saturated_cells() == 0, message);
    require(safety.poison_refs() == 0, message);
}

}  // namespace

static_assert(ForeignReadSafety::kCellCount == 4096);
static_assert(alignof(ForeignReadSafety) == 64);
static_assert(sizeof(ForeignReadSafety) == 49216,
              "4096 cells, 4096 touch epochs, three owner witnesses, cacheline rounded");

int main() {
    const CollisionSet collision = find_three_fingerprints_in_one_cell();
    const uint64_t other = find_hash_in_another_cell(collision.first);
    require(ForeignReadSafety::cell_index(collision.first) ==
                ForeignReadSafety::cell_index(collision.second) &&
            ForeignReadSafety::cell_index(collision.first) ==
                ForeignReadSafety::cell_index(collision.third),
            "collision synthesizer returned different cells");
    require(ForeignReadSafety::fingerprint(collision.first) !=
                ForeignReadSafety::fingerprint(collision.second) &&
            ForeignReadSafety::fingerprint(collision.first) !=
                ForeignReadSafety::fingerprint(collision.third) &&
            ForeignReadSafety::fingerprint(collision.second) !=
                ForeignReadSafety::fingerprint(collision.third),
            "collision synthesizer returned duplicate fingerprints");

    ForeignReadSafety duplicate_refs;
    require_empty(duplicate_refs, "fresh filter is not empty");
    require(!duplicate_refs.might_contain(collision.first), "fresh filter false-positive");
    add(duplicate_refs, {collision.first, collision.first});
    require(duplicate_refs.unsafe_total_refs() == 2 &&
                duplicate_refs.occupied_cells() == 1 &&
                duplicate_refs.wildcard_cells() == 0 &&
                duplicate_refs.might_contain(collision.first),
            "same-fingerprint references did not merge exactly");
    close_refs(duplicate_refs, {collision.first});
    require(duplicate_refs.unsafe_total_refs() == 1 &&
                duplicate_refs.might_contain(collision.first),
            "first overlapping close exposed a still-live key");
    close_refs(duplicate_refs, {collision.first});
    require_empty(duplicate_refs, "same-fingerprint bucket did not drain");

    ForeignReadSafety independent;
    add(independent, {collision.first, other});
    require(independent.unsafe_total_refs() == 2 && independent.occupied_cells() == 2,
            "independent cells did not occupy independently");
    close_refs(independent, {collision.first});
    require(!independent.might_contain(collision.first) && independent.might_contain(other) &&
                independent.unsafe_total_refs() == 1 && independent.occupied_cells() == 1,
            "closing one independent cell disturbed another");
    close_refs(independent, {other});
    require_empty(independent, "independent cells did not drain");

    ForeignReadSafety wildcard;
    add(wildcard, {collision.first, collision.second});
    require(wildcard.unsafe_total_refs() == 2 && wildcard.occupied_cells() == 1 &&
                wildcard.wildcard_cells() == 1 &&
                wildcard.might_contain(collision.first) &&
                wildcard.might_contain(collision.second) &&
                wildcard.might_contain(collision.third),
            "different fingerprints did not publish one wildcard bucket");
    close_refs(wildcard, {collision.second});
    require(wildcard.unsafe_total_refs() == 1 && wildcard.wildcard_cells() == 1 &&
                wildcard.might_contain(collision.first) &&
                wildcard.might_contain(collision.third),
            "wildcard did not remain sticky while the bucket was occupied");
    close_refs(wildcard, {collision.first});
    require_empty(wildcard, "wildcard bucket did not clear at exact drain");

    ForeignReadSafety poison;
    add(poison, {collision.first});
    poison.poison_open();
    poison.poison_open();
    require(poison.unsafe_total_refs() == 1 && poison.poison_refs() == 2 &&
                poison.occupied_cells() == ForeignReadSafety::kCellCount &&
                poison.wildcard_cells() == ForeignReadSafety::kCellCount &&
                poison.might_contain(collision.first) && poison.might_contain(other),
            "nested poison did not fail every cell closed");
    poison.poison_close();
    require(poison.poison_refs() == 1 && poison.might_contain(other),
            "inner poison close exposed the shard");
    poison.poison_close();
    require(poison.poison_refs() == 0 && poison.unsafe_total_refs() == 1 &&
                poison.occupied_cells() == 1 && poison.wildcard_cells() == 1 &&
                poison.might_contain(collision.first) &&
                poison.might_contain(collision.third),
            "final poison close lost the surviving sticky bucket");
    close_refs(poison, {collision.first});
    require_empty(poison, "poison plus exact reference did not drain");

    ForeignReadSafety saturated;
    saturated.test_set_cell(collision.first, ForeignReadSafety::kCountMask - 1);
    saturated.test_set_unsafe_total_refs(0);
    add(saturated, {collision.first});
    require(saturated.unsafe_total_refs() == 1 && saturated.saturated_cells() == 1 &&
                saturated.occupied_cells() == 1 && saturated.wildcard_cells() == 1 &&
                (saturated.test_cell(collision.first) & ForeignReadSafety::kCountMask) ==
                    ForeignReadSafety::kCountMask &&
                saturated.might_contain(collision.third),
            "count saturation did not become fail-closed wildcard");
    close_refs(saturated, {collision.first});
    require_empty(saturated, "saturated cell did not rebuild at exact-total zero drain");

    ForeignReadSafety overflow;
    overflow.test_set_unsafe_total_refs(std::numeric_limits<uint64_t>::max() - 1);
    uint32_t callback_calls = 0;
    overflow.add_span(2, [&](uint32_t) {
        callback_calls++;
        return collision.first;
    });
    require(callback_calls == 0 && overflow.permanently_poisoned() &&
                overflow.unsafe_total_refs() == std::numeric_limits<uint64_t>::max() &&
                overflow.poison_refs() == std::numeric_limits<uint64_t>::max() &&
                overflow.occupied_cells() == ForeignReadSafety::kCellCount &&
                overflow.wildcard_cells() == ForeignReadSafety::kCellCount &&
                overflow.saturated_cells() == ForeignReadSafety::kCellCount &&
                overflow.might_contain(collision.first) && overflow.might_contain(other),
            "total overflow did not publish permanent shard poison");
    close_refs(overflow, {collision.first});
    require(overflow.permanently_poisoned() && overflow.might_contain(other),
            "close escaped permanent overflow poison");

    // Touch epochs: the counting field gates, the epoch validates a multi-key window. Every add and
    // every close of a bucket advances it exactly once; unrelated buckets never move.
    ForeignReadSafety epochs;
    require(epochs.cell_epoch(collision.first) == 0 && epochs.cell_epoch(other) == 0,
            "fresh filter has nonzero touch epochs");
    add(epochs, {collision.first});
    require(epochs.cell_epoch(collision.first) == 1 && epochs.cell_epoch(other) == 0 &&
                epochs.cell_epoch(collision.third) == 1,
            "add did not touch exactly the target bucket once");
    close_refs(epochs, {collision.first});
    require(epochs.cell_epoch(collision.first) == 2 && epochs.cell_epoch(other) == 0 &&
                !epochs.might_contain(collision.first),
            "0 -> 1 -> 0 did not leave a +2 witness (ABA would be invisible to the count)");
    add(epochs, {collision.first, collision.second});
    require(epochs.cell_epoch(collision.first) == 4 && epochs.wildcard_cells() == 1,
            "two adds into one wildcard bucket did not touch it twice");
    close_refs(epochs, {collision.second, collision.first});
    require(epochs.cell_epoch(collision.first) == 6 && epochs.cell_epoch(other) == 0,
            "closes did not touch the bucket once each");
    require_empty(epochs, "epoch filter did not drain");
    add(epochs, {other});
    require(epochs.cell_epoch(collision.first) == 6 && epochs.cell_epoch(other) == 1,
            "an unrelated bucket's add moved another bucket's epoch");
    close_refs(epochs, {other});

    // Poison touches every bucket on open and on final close; nested opens touch nothing.
    ForeignReadSafety poison_epochs;
    poison_epochs.poison_open();
    require(poison_epochs.cell_epoch(collision.first) == 1 && poison_epochs.cell_epoch(other) == 1,
            "poison open did not touch every bucket");
    poison_epochs.poison_open();
    require(poison_epochs.cell_epoch(other) == 1, "nested poison open touched buckets");
    poison_epochs.poison_close();
    require(poison_epochs.cell_epoch(other) == 1, "inner poison close touched buckets");
    poison_epochs.poison_close();
    require(poison_epochs.cell_epoch(collision.first) == 2 && poison_epochs.cell_epoch(other) == 2,
            "final poison close did not touch every bucket");
    require_empty(poison_epochs, "poison epochs filter did not drain");

    // Saturated-drain rebuild and permanent poison touch every bucket too.
    ForeignReadSafety rebuild_epochs;
    rebuild_epochs.test_set_cell(collision.first, ForeignReadSafety::kCountMask - 1);
    rebuild_epochs.test_set_unsafe_total_refs(0);
    add(rebuild_epochs, {collision.first});
    require(rebuild_epochs.cell_epoch(collision.first) == 1 && rebuild_epochs.cell_epoch(other) == 0,
            "saturating add did not touch exactly its bucket");
    close_refs(rebuild_epochs, {collision.first});
    require(rebuild_epochs.cell_epoch(collision.first) == 3 && rebuild_epochs.cell_epoch(other) == 1,
            "exact-drain rebuild did not touch every bucket");
    require_empty(rebuild_epochs, "rebuild epochs filter did not drain");
    rebuild_epochs.test_set_cell_epoch(other, UINT32_MAX);
    add(rebuild_epochs, {other});
    require(rebuild_epochs.cell_epoch(other) == 0, "epoch wrap did not stay a plain modular step");
    close_refs(rebuild_epochs, {other});
    rebuild_epochs.fail_closed_permanently();
    require(rebuild_epochs.cell_epoch(collision.first) == 4 && rebuild_epochs.cell_epoch(other) == 2,
            "permanent poison did not touch every bucket");

    std::puts("foreign-read-safety unit: PASS");
    return 0;
}
