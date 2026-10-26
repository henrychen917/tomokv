#pragma once
// Owner-local claim index. Nodes live in immutable-after-publication claim slots.
#include <array>
#include <atomic>
#include "../base/tomo_assert.h"
#include <cstdint>
#include <cstdlib>
#include <vector>
namespace tomo {
class Client;
struct TxnWaiter;
struct TxnKeyQueue;
struct TxnReservation {
        const void* token = nullptr;
        std::atomic<uint64_t>* epoch = nullptr;
        std::atomic<bool>* aborted = nullptr;
        std::atomic<uint32_t>* refs = nullptr;
        Client* writer = nullptr;
        uint64_t writer_generation = 0;
        bool mutates = false;
        // Does this reservation make another unit WAIT?
        //
        // A reservation from the EXEC validate path carries an ORDERING claim: the transaction has
        // validated its WATCH on this key, so no foreign write may commit ahead of its decision.
        // A writer therefore has to wait for it, and that wait is bounded because the transaction
        // is already fanned out and decides on its own.
        //
        // A reservation from the atomic-group WRITE path carries no such claim. It exists only to
        // defer THIS group's watcher-dirtying to its own commit decision. Making it exclusive --
        // one slot per key, everybody else waits -- turned it into a cross-shard lock taken in
        // arbitrary order, and two groups that each hold a key the other needs is a wait-for cycle
        // with no timeout and no detector: tests/watchlive.py wedged 6/6 on it. Group reservations
        // now coexist on a key (the map holds a list) and block nobody.
        bool blocking = false;
        uint8_t unit_kind = 0; // 1 EXEC, 2 read-dependent group
        uint8_t unit_mode = 0; // TxnClaimMode
        uint8_t entry_kind = 0; // 0 validation/dirty deferral, 1 claim, 2 writer, 3 waiter
        // A swap-containing EXEC can write the same physical key while it names
        // different logical databases. Keep the identities at each write, not
        // the mapping at reservation retirement. WATCH state is cold/heap-owned.
        std::array<uint64_t, 4> dirty_databases{};
};

struct TxnWaiter {
    TxnWaiter *prev = nullptr, *next = nullptr;
    TxnWaiter *wprev = nullptr, *wnext = nullptr;
    TxnReservation entry;
    TxnKeyQueue* queue = nullptr;
    bool waiting = false;
    TxnWaiter() = default;
    // Claim vectors are built/capped before publication. Copies are new claims,
    // never another owner of a linked node (retire_claims is such a copy).
    TxnWaiter(const TxnWaiter&) {}
    TxnWaiter& operator=(const TxnWaiter&) { TOMO_ASSERT(!queue); return *this; }
    TxnWaiter(TxnWaiter&& other) noexcept { TOMO_ASSERT(!other.queue); }
    TxnWaiter& operator=(TxnWaiter&& other) noexcept { TOMO_ASSERT(!queue && !other.queue); return *this; }
    ~TxnWaiter() { TOMO_ASSERT_SALT(!queue, 1); }
};
struct TxnHeld : TxnReservation {
    TxnWaiter* handle = nullptr;
    TxnHeld(const TxnReservation& r, TxnWaiter* node = nullptr) : TxnReservation(r), handle(node) {}
};
struct TxnKeyQueue {
    std::vector<TxnHeld> held;
    TxnWaiter *head = nullptr, *tail = nullptr;
    TxnWaiter *whead = nullptr, *wtail = nullptr;
    std::vector<TxnReservation> marks;
    uint32_t waiters = 0;
    bool empty() const { return held.empty() && !head && marks.empty(); }
    size_t size() const { return held.size() + waiters + marks.size(); }
    const TxnReservation& front() const {
        return !held.empty() ? held.front() : head ? head->entry : marks.front();
    }
};
} // namespace tomo
