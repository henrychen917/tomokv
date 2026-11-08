// FlatStore owns each shard's open-addressed keyspace, expiry indexes, snapshot cursor,
// borrow registry and owner-local MVCC state. It is included through shard.h and directly
// by store/command helpers and fixtures; definitions stay in each including translation unit.
// flatstore_atomic.inc, flatstore_flush.inc and flatstore_random.inc supply class members.
//
// The shard owner serializes mutations. Unarmed accesses use ordinary slot loads/stores;
// armed foreign probes acquire-load slots and topology, while writers release-publish
// replacement string objects and defer reclamation through the bound QSBR sink. Foreign
// readers must hold their caller's QSBR lifetime and validate the captured topology.
// Collection payloads and atomic header metadata have separate mutation rules; the whole
// KvObj is not immutable. try_overwrite_read_local rejects in-place string overwrite.
//
// Resizing moves eight-byte slot words, not the objects they name. Mutations and owner
// maintenance migrate bounded batches; lookups search both tables without advancing rehash.
// Armed resize admission reserves its retirement record before publishing the new table;
// the final step hands off the old table without waiting for object-ring capacity. QSBR
// may delay freeing it. Snapshot capture temporarily retains the old table's slot layout.
//
//   tab_[0]  current table; new keys are inserted here.
//   tab_[1]  old table during rehash, or frozen slot layout during snapshot capture.
//
// Replacement must remove an old-table copy before publishing the new current-table copy,
// and erase searches both tables, or deleting the replacement can resurrect the old value.
// Rehash briefly publishes the destination before tombstoning the source; armed probes
// validate that multi-slot move through ReadLocalTableGuard.
//
// Slot encoding: [63:49] hash tag, [48] tombstone/pre-image mark, [47:0] KvObj pointer.
// Boot probes the allocator's address width; make_word asserts that each packed pointer
// fits. Zero is EMPTY and stops a probe. A nonzero pointer names an object; a nonzero word
// with a zero pointer is a reusable tombstone and does not stop probing.
//
// The router consumes low hash bits. Reusing them directly as a table index would restrict
// keys in a shard to a small set of homes and produce long probe runs. slot_start mixes the
// hash again before masking. Hash tags reject mismatches before loading key bytes.
#pragma once
#include "../core/exec1s.h"
#include <algorithm>
#include <atomic>
#include "../base/tomo_assert.h"
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>
#include "../base/alloc.h"
#include "../core/atomic_tripwire.h"
#include "eviction.h"
#include "../cmd/notify.h"
#include "../cmd/client_pause.h"
#include "kv_block_cache.h"
#include "kvobj.h"
#include "object_idle.h"
#include "atomic_mvcc.h"
#include "foreign_read_safety.h"
#include "read_local_reclaim.h"
#include "../snapshot/format.h"
#include "../persist/aof.h"

namespace tomo {

// Owner-maintained monitoring sidecar, allocated/freed by FlatStore's storesize helpers.
// The sampling cursor is ordinary owner state; avg_deadline and field_ttl_attention use
// relaxed atomic stores/loads for monitoring, not object-lifetime publication. Cold clear
// resets the sample. No object pointers are owned here.
struct StoreSizeState {
    uint64_t sample_cursor = 0;
    std::atomic<uint64_t> avg_deadline{0};
    std::atomic<bool> field_ttl_attention{false};
};

// Allocation-failure injection, compiled when NDEBUG is absent. Each table allocation
// checks a relaxed atomic counter; probes without allocation do not consult it. This
// includes allocations initiated by commands as well as startup and maintenance.
#ifndef NDEBUG
inline std::atomic<uint32_t> g_flatstore_table_alloc_failures{0};

inline void flatstore_debug_fail_table_allocations(uint32_t count) {
    g_flatstore_table_alloc_failures.store(count, std::memory_order_relaxed);
}

inline bool flatstore_debug_consume_table_alloc_failure() {
    uint32_t remaining = g_flatstore_table_alloc_failures.load(std::memory_order_relaxed);
    while (remaining) {
        if (g_flatstore_table_alloc_failures.compare_exchange_weak(remaining, remaining - 1,
                                                                   std::memory_order_relaxed))
            return true;
    }
    return false;
}
#endif

inline void* flatstore_table_calloc(size_t count, size_t width) {
#ifndef NDEBUG
    if (flatstore_debug_consume_table_alloc_failure()) return nullptr;
#endif
    return std::calloc(count, width);
}

struct ScatterState;
uint64_t xshard_atomic_key_hash(const ScatterState* state, uint32_t ordered_index);
Slice xshard_atomic_key_slice(const ScatterState* state, uint32_t ordered_index);

inline uint64_t mix64(uint64_t h);

// Owner-local expiry attention index: owns two hash arrays and byte-state sidecars, not
// keys or object pointers. Replacement therefore does not invalidate a stored hash.
// Callers serialize access; this class supplies no cross-thread publication or locking.
// Allocation failure returns false from insert; a hash identifies possible expiry work,
// so callers still check the resident object's deadline and handle stale registrations.
//
// Growth normally migrates kMigrateSlotsPerOp slots per insert/sample into table 1;
// finish_migration can drain the remainder when insert's occupancy backstop is reached.
// Sampling counts empty slots against its budget and preserves a cursor between calls.
// A zero population releases larger/migrating tables; a minimum-size table keeps its
// buffer and clears 16 state bytes, avoiding allocation for small recurring populations.
class ExpireIndex {
public:
    ExpireIndex() = default;
    ~ExpireIndex() {
        std::free(hashes_[0]);
        std::free(sidecars_[0]);
        std::free(hashes_[1]);
        std::free(sidecars_[1]);
    }
    ExpireIndex(const ExpireIndex&) = delete;
    ExpireIndex& operator=(const ExpireIndex&) = delete;

    uint32_t size() const { return live_[0] + live_[1]; }
    // A move in flight is PENDING WORK for the owner, not a quiet background state: half the
    // index is parked in the old table, and an owner that sleeps on a barren sampling pass stops
    // expiring until the next command wakes it.
    bool migrating() const { return cap_[1] != 0; }
    size_t memory_bytes() const {
        return static_cast<size_t>((static_cast<uint64_t>(cap_[0]) + cap_[1]) *
                                   (sizeof(uint64_t) + sizeof(uint8_t)));
    }
    void clear() {
        release(0);
        release(1);
        cursor_ = 0;
        migrate_ = 0;
    }

    // The deadline argument carries no index state; insert_raw ignores it.
    bool insert(uint64_t hash, int64_t deadline = kNoTtlDeadline) {
        if (rehashing()) {
            migrate(kMigrateSlotsPerOp);
            // Occupancy backstop: finish the move before an insertion exhausts the destination.
            // The ordinary path advances kMigrateSlotsPerOp slots before testing this bound.
            if (rehashing() && (static_cast<uint64_t>(live_[1]) + tombs_[1] + 1) * 100 >=
                                   static_cast<uint64_t>(cap_[1]) * 70)
                finish_migration();
        }
        if (!cap_[0] && !allocate(0, kMinCap)) return false;
        if (!rehashing() && (static_cast<uint64_t>(live_[0]) + tombs_[0] + 1) * 100 >=
                                static_cast<uint64_t>(cap_[0]) * 70) {
            uint64_t wanted = cap_[0];
            if (static_cast<uint64_t>(live_[0]) * 2 >= cap_[0]) {
                if (wanted > std::numeric_limits<size_t>::max() / uint64_t{2}) return false;
                wanted *= uint64_t{2};
            }
            if (!begin_rehash(static_cast<size_t>(wanted))) return false;
            migrate(kMigrateSlotsPerOp);
        }
        // A deadline re-registered while the move is in flight must leave the old table, or live_
        // double-counts it until the migration catches up.
        if (rehashing()) (void)erase_in(0, hash);
        return insert_raw(rehashing() ? 1 : 0, hash, deadline);
    }

    // Erasing from an index with nothing LIVE in it is a PROVEN no-op, not an approximation:
    // erase_in() only ever clears a kLive slot, and it changes nothing else. So this guard is
    // exact, and it is the only skip that is. Do NOT make the erase conditional on "the key has a
    // deadline" instead -- see track_expire() for the expiry-count invariant.
    bool erase(uint64_t hash) {
        if (size() == 0) return false;
        bool removed = erase_in(1, hash);
        if (!removed) removed = erase_in(0, hash);
        if (removed && size() == 0) collapse_empty();
        return removed;
    }

    template <typename Fn>
    uint32_t sample(uint32_t budget, Fn&& fn) {
        // Sampling is the pass that still runs when writes have stopped, so it is also what
        // guarantees a migration finishes rather than sitting half-done forever.
        if (rehashing()) migrate(kMigrateSlotsPerOp);
        uint32_t checked = 0;
        // Capacities are re-read every iteration: fn() may erase the last live deadline, and that
        // releases the tables underneath this loop.
        while (checked < budget) {
            // Slots below migrate_ have already been moved out; sampling them would spend the
            // budget on a region that cannot hold a deadline, and a barren pass is exactly what
            // makes an idle owner park instead of expiring.
            const size_t old_left = cap_[0] - migrate_;
            const size_t total = old_left + cap_[1];
            if (!total || size() == 0) break;
            if (cursor_ >= total) cursor_ = 0;
            const size_t pos = cursor_++;
            checked++;
            if (pos < old_left) {
                const size_t slot = migrate_ + pos;
                if (states(0)[slot] == kLive) fn(hashes_[0][slot]);
            } else if (states(1)[pos - old_left] == kLive) {
                fn(hashes_[1][pos - old_left]);
            }
        }
        return checked;
    }

    // Instantiated only by the cold monitoring sampler.
    template <typename Fn>
    void sample_readonly(uint64_t& cursor, uint32_t budget, Fn&& fn) const;

    // Best-effort random live hash selection. Both the random probes and sparse-table cursor
    // fallback are bounded; callers count a miss as part of their sampling budget.
    bool random_hash(uint64_t random, uint32_t attempts, uint64_t& out) {
        if (size() == 0) return false;
        for (uint32_t i = 0; i < attempts; i++)
            for (int table_index = 0; table_index < 2; table_index++) {
                if (!cap_[table_index] || !live_[table_index]) continue;
                const size_t pos = static_cast<size_t>(mix64(random + i * 2 + table_index)) &
                                   (cap_[table_index] - 1);
                if (states(table_index)[pos] == kLive) {
                    out = hashes_[table_index][pos];
                    return true;
                }
            }
        for (uint32_t i = 0; i < attempts; i++) {
            const size_t old_left = cap_[0] - migrate_;
            const size_t total = old_left + cap_[1];
            if (!total) return false;
            if (cursor_ >= total) cursor_ = 0;
            const size_t pos = cursor_++;
            if (pos < old_left) {
                const size_t slot = migrate_ + pos;
                if (states(0)[slot] == kLive) {
                    out = hashes_[0][slot];
                    return true;
                }
            } else if (states(1)[pos - old_left] == kLive) {
                out = hashes_[1][pos - old_left];
                return true;
            }
        }
        return false;
    }

private:
    static constexpr uint8_t kEmpty = 0;
    static constexpr uint8_t kLive = 1;
    static constexpr uint8_t kTomb = 2;
    static constexpr size_t kMinCap = 16;
    // Old slots moved per operation. Same reasoning (and same number) as
    // FlatStore::kRehashSlotsPerOp: large enough that the move finishes long before the new table
    // needs one of its own, small enough that no single operation visibly stalls.
    static constexpr uint32_t kMigrateSlotsPerOp = 8;

    bool rehashing() const { return cap_[1] != 0; }

    uint8_t* states(int t) const {
        if (!sidecars_[t]) return nullptr;
        auto* bytes = sidecars_[t];
        return bytes;
    }

    void release(int t) {
        std::free(hashes_[t]);
        std::free(sidecars_[t]);
        hashes_[t] = nullptr;
        sidecars_[t] = nullptr;
        cap_[t] = 0;
        live_[t] = tombs_[t] = 0;
    }

    // Use calloc as FlatStore::alloc_table does so large tables can use demand-zero pages;
    // eagerly writing the whole sidecar would put capacity-sized work on one operation.
    bool allocate(int t, size_t cap) {
        auto* hashes = static_cast<uint64_t*>(flatstore_table_calloc(cap, sizeof(uint64_t)));
        auto* sidecar = static_cast<uint8_t*>(flatstore_table_calloc(cap, sizeof(uint8_t)));
        if (!hashes || !sidecar) {
            std::free(hashes);
            std::free(sidecar);
            return false;
        }
        std::free(hashes_[t]);
        std::free(sidecars_[t]);
        hashes_[t] = hashes;
        sidecars_[t] = sidecar;
        cap_[t] = cap;
        live_[t] = tombs_[t] = 0;
        return true;
    }

    __attribute__((noinline, cold)) void collapse_empty() {
        if (!rehashing() && cap_[0] <= kMinCap) {
            std::memset(states(0), kEmpty, cap_[0]);
            tombs_[0] = 0;
            cursor_ = 0;
            return;
        }
        release(0);
        release(1);
        cursor_ = 0;
        migrate_ = 0;
    }

    bool begin_rehash(size_t cap) {
        if (!allocate(1, cap)) return false;
        migrate_ = 0;
        return true;
    }

    // Moved slots remain tombstones: erase_in still probes the old table, and kEmpty would
    // break its probe chains. A missed removal would leave INFO expires overstated after PERSIST.
    void migrate(uint32_t slots) {
        while (slots && migrate_ < cap_[0]) {
            const size_t pos = migrate_++;
            slots--;
            if (states(0)[pos] != kLive) continue;
            states(0)[pos] = kTomb;
            live_[0]--;
            tombs_[0]++;
            // Cannot fail: the destination was sized for every live entry plus headroom.
            (void)insert_raw(1, hashes_[0][pos], kNoTtlDeadline);
        }
        if (migrate_ >= cap_[0]) finish_migration();
    }

    void finish_migration() {
        while (migrate_ < cap_[0]) {
            const size_t pos = migrate_++;
            if (states(0)[pos] != kLive) continue;
            states(0)[pos] = kTomb;
            live_[0]--;
            tombs_[0]++;
            (void)insert_raw(1, hashes_[0][pos], kNoTtlDeadline);
        }
        std::free(hashes_[0]);
        std::free(sidecars_[0]);
        hashes_[0] = hashes_[1];
        sidecars_[0] = sidecars_[1];
        cap_[0] = cap_[1];
        live_[0] = live_[1];
        tombs_[0] = tombs_[1];
        hashes_[1] = nullptr;
        sidecars_[1] = nullptr;
        cap_[1] = 0;
        live_[1] = tombs_[1] = 0;
        migrate_ = 0;
        cursor_ = 0;
    }

    size_t start(int t, uint64_t hash) const {
        return static_cast<size_t>(mix64(hash)) & (cap_[t] - 1);
    }

    bool insert_raw(int t, uint64_t hash, int64_t) {
        const size_t cap = cap_[t];
        if (!cap) return false;
        size_t pos = start(t, hash);
        size_t first_tomb = cap;
        for (size_t probes = 0; probes < cap; probes++) {
            if (states(t)[pos] == kEmpty) {
                if (first_tomb != cap) {
                    pos = first_tomb;
                    tombs_[t]--;
                }
                hashes_[t][pos] = hash;
                states(t)[pos] = kLive;
                live_[t]++;
                return true;
            }
            if (states(t)[pos] == kTomb) {
                if (first_tomb == cap) first_tomb = pos;
            } else if (hashes_[t][pos] == hash) {
                return true;
            }
            pos = (pos + 1) & (cap - 1);
        }
        return false;
    }

    bool erase_in(int t, uint64_t hash) {
        const size_t cap = cap_[t];
        if (!cap) return false;
        size_t pos = start(t, hash);
        for (size_t probes = 0; probes < cap; probes++) {
            if (states(t)[pos] == kEmpty) return false;
            if (states(t)[pos] == kLive && hashes_[t][pos] == hash) {
                states(t)[pos] = kTomb;
                live_[t]--;
                tombs_[t]++;
                return true;
            }
            pos = (pos + 1) & (cap - 1);
        }
        return false;
    }

    uint64_t* hashes_[2] = {nullptr, nullptr};
    uint8_t* sidecars_[2] = {nullptr, nullptr};
    size_t cap_[2] = {0, 0};
    uint32_t live_[2] = {0, 0};
    uint32_t tombs_[2] = {0, 0};
    size_t cursor_ = 0;   // sampling cursor over the concatenation of both tables
    size_t migrate_ = 0;  // next old-table slot to move while a migration is in flight
};
static_assert(sizeof(ExpireIndex) == 80, "ExpireIndex layout drift");
// 64-bit finalizer (murmur3 fmix64). Cheap, and it decorrelates the index bits from the router's.
// ---- hash hardening ---------------------------------------------------------------------------
// Collisions are a CORRECTNESS non-event (find_in compares full key bytes after the tag filter)
// but a deterministic public hash is a DoS surface: craft keys sharing the low 14 bits and one
// thread does all the work; craft keys sharing slot_start and the probe runs the clustering
// pathology on purpose. Two layers, both keyed at boot from the kernel:
//   - the default mix64 path folds a random seed, killing offline precomputation for free;
//   - --hash siphash switches to SipHash-1-2 (redis's choice since 4.0), the principled PRF
//     answer for adversarial deployments.
// The kind is a boot-time enum read through one perfectly-predicted branch -- not a function
// pointer, which would tax every hash with an indirect call.
enum class HashKind : uint8_t { Mix64Seeded = 0, SipHash12 = 1 };
inline HashKind g_hash_kind = HashKind::Mix64Seeded;
inline uint64_t g_hash_seed = 0;  // selected during startup, including persistence metadata
inline uint64_t g_sip_k0 = 0, g_sip_k1 = 0;

inline uint64_t rotl64(uint64_t x, int b) { return (x << b) | (x >> (64 - b)); }

// SipHash-1-2, reference-faithful, little-endian loads via memcpy.
inline uint64_t siphash12(const char* p, size_t n) {
    uint64_t v0 = 0x736f6d6570736575ULL ^ g_sip_k0;
    uint64_t v1 = 0x646f72616e646f6dULL ^ g_sip_k1;
    uint64_t v2 = 0x6c7967656e657261ULL ^ g_sip_k0;
    uint64_t v3 = 0x7465646279746573ULL ^ g_sip_k1;
    auto round = [&] {
        v0 += v1;
        v1 = rotl64(v1, 13);
        v1 ^= v0;
        v0 = rotl64(v0, 32);
        v2 += v3;
        v3 = rotl64(v3, 16);
        v3 ^= v2;
        v0 += v3;
        v3 = rotl64(v3, 21);
        v3 ^= v0;
        v2 += v1;
        v1 = rotl64(v1, 17);
        v1 ^= v2;
        v2 = rotl64(v2, 32);
    };
    const size_t end = n & ~size_t(7);
    for (size_t i = 0; i < end; i += 8) {
        uint64_t m;
        std::memcpy(&m, p + i, 8);
        v3 ^= m;
        round();
        v0 ^= m;
    }
    uint64_t b = static_cast<uint64_t>(n) << 56;
    for (size_t i = end; i < n; i++)
        b |= static_cast<uint64_t>(static_cast<unsigned char>(p[i])) << (8 * (i - end));
    v3 ^= b;
    round();
    v0 ^= b;
    v2 ^= 0xff;
    round();
    round();
    return v0 ^ v1 ^ v2 ^ v3;
}

inline uint64_t mix64(uint64_t h) {
    h ^= h >> 33;
    h *= 0xff51afd7ed558ccdULL;
    h ^= h >> 33;
    h *= 0xc4ceb9fe1a85ec53ULL;
    h ^= h >> 33;
    return h;
}

// ---- reverse-binary SCAN cursors ---------------------------------------------------------------
// THE guarantee every SCAN family member owes: an element present for the WHOLE iteration is
// returned at least once, no matter how many times the table was resized underneath it. A cursor
// that is a raw slot number cannot keep that promise -- doubling the table moves a key from a slot
// AHEAD of the cursor to one BEHIND it, and the key is silently never emitted.
//
// Reverse-binary traversal needs one property of the table homes:
// the home index is `hash & (2^k - 1)`, so a key's home in the small table is its home in the big
// table with the extra high bits masked off. Count the cursor in BIT-REVERSED order and the high
// bits therefore move FASTEST, which makes every family of homes that share the small table's low
// bits a contiguous block of the visiting order. A resize can then only move a key between homes
// that are on the same side of the cursor -- both already visited, or both still to come.
//
// The counter is: set every bit ABOVE the mask, reverse, add one, reverse back. The carry runs
// downward through the high bits and the result is again inside the mask, so any cursor a client
// hands back is self-correcting, and the walk ends at exactly 0 after one full cycle.
inline uint64_t scan_cursor_reverse_bits(uint64_t v) {
    v = ((v & 0x5555555555555555ULL) << 1) | ((v >> 1) & 0x5555555555555555ULL);
    v = ((v & 0x3333333333333333ULL) << 2) | ((v >> 2) & 0x3333333333333333ULL);
    v = ((v & 0x0f0f0f0f0f0f0f0fULL) << 4) | ((v >> 4) & 0x0f0f0f0f0f0f0f0fULL);
    v = ((v & 0x00ff00ff00ff00ffULL) << 8) | ((v >> 8) & 0x00ff00ff00ff00ffULL);
    v = ((v & 0x0000ffff0000ffffULL) << 16) | ((v >> 16) & 0x0000ffff0000ffffULL);
    return (v << 32) | (v >> 32);
}

inline uint64_t scan_cursor_next(uint64_t cursor, uint64_t mask) {
    cursor |= ~mask;
    cursor = scan_cursor_reverse_bits(cursor);
    cursor++;
    return scan_cursor_reverse_bits(cursor);
}

// The SCAN command's walker declares kExpiresVisited. Redis 7.4's scanGenericCommand deletes
// every elapsed key of the batch it visits, so that walker keeps the deletion even when the
// owner's retire ring must first reclaim (FlatStore::scan_visit). Every other walker keeps the
// no-wait capacity guard.
template <typename Fn>
inline constexpr bool kScanExpiresVisited = requires { requires Fn::kExpiresVisited; };

class /* TOMO_TOOL_BIND FlatStore */ FlatStore;
struct FlatStoreLayoutLock;

// FlatStore owns this extended pending-state allocation while the read-local lane is prepared.
// AtomicPendingState is first (asserted below), allowing atomic_pending_ to address either
// allocation shape without changing FlatStore offsets. The owner mutates counters, filter and
// retire binding; foreign probes acquire-load probe_sequence and the filter's atomic cells.
// The sink borrows owner resources; resize_retirement owns a reserved table-retirement record.
// Unarmed atomic_ensure_pending allocates the smaller AtomicPendingState; preparation may fail.
struct ReadLocalStoreState {
    AtomicPendingState atomic;
    // `probe_sequence` is the one table word: it changes for topology moves and atomic physical
    // exchanges, never for an ordinary immutable one-slot SET, so plain writes publish nothing
    // beyond their slot store. Point probes validate against it; local MGET validates a group-free
    // participant against it and a pending participant against the per-key cell epochs in
    // `foreign_reads`.
    std::atomic<uint64_t> probe_sequence{0};
    ReadLocalRetireSink retire_sink{};
    std::unique_ptr<ResizeRetirement> resize_retirement;
    uint32_t table_mutation_depth = 0;
    uint32_t pending_count = 0;
    ForeignReadSafety foreign_reads{};
};
static_assert(std::is_standard_layout_v<ReadLocalStoreState>);
static_assert(offsetof(ReadLocalStoreState, atomic) == 0);

// Hash-field TTLs, defined in src/cmd/t_hash_ttl.cc. The store owns the ATTENTION (which keys carry
// field deadlines, and the bounded cycle that revisits them); the hash lane owns the reap itself,
// because only it knows the two hash representations. Returns true when no live field is left and
// the caller must delete the key; `reaped` counts fields removed.
bool hash_ttl_active_reap(FlatStore& store, KvObj* object, int64_t now_ms, uint32_t& reaped);

// Shard-owned keyspace. Command and maintenance paths run under shard ownership; boot,
// persistence replay and post-join cleanup access it without concurrent request execution.
// The table owns installed objects, MVCC entries retain displaced predecessors, and borrows
// or QSBR retirement can extend storage lifetime after logical removal. Foreign read-local
// callers use the capture API under their caller-provided QSBR lifetime, not owner lookup.
// Armed slot publication uses release stores paired with acquire loads; topology changes
// also use ReadLocalTableGuard. The owner must prepare snapshots/atomic capacity before
// those install passes. Allocation/admission can fail; retirement may wait for the sink,
// whereas ordinary lookup leaves expired objects resident if retirement has no capacity.
class FlatStore {
public:
    static constexpr uint64_t kPtrMask = (1ULL << 48) - 1;
    static constexpr uint64_t kTombBit = 1ULL << 48;
    static constexpr int kLoadPct = 70;
    static constexpr uint32_t kMinCap = 64;

    // OLD slots examined per operation. Large enough that a rehash finishes well before the table
    // needs another, small enough that no single operation visibly stalls. Bounded per op is the
    // entire point.
    static constexpr uint32_t kRehashSlotsPerOp = 8;

    // Eight slot bytes at the 70% target load cost 11.43 bytes per live key. Accounting rounds
    // that stable-state estimate to 12; transient dual tables, tombstones and allocator metadata
    // are deliberately outside the maxmemory model: charging those costs would make enforcement
    // depend on resize history rather than maintained object/key counters. This is a stable
    // logical cache budget, not an RSS ceiling.
    static constexpr size_t kSlotOverheadPerKey = 12;
    static constexpr uint32_t kEvictionsPerOp = 16;
    static constexpr uint32_t kSampleProbeAttempts = 16;

    enum class InsertResult : uint8_t { Inserted, MaxmemoryOom, Failed };
    enum class OverwriteResult : uint8_t { Updated, NotPossible, MaxmemoryOom };
    enum class ReadLocalProbeResult : uint8_t { Hit, Missing, AtomicPending, Churn };

    // Non-owning probe result. Hit pointers require the caller's QSBR lifetime; the result
    // and state describe validation/fallback, not a transfer of the object's ownership.
    struct ReadLocalProbe {
        ReadLocalProbeResult result = ReadLocalProbeResult::Churn;
        const KvObj* object = nullptr;
        uint64_t state = 0;
    };

    // Stack-local result of the batch prefetch walk. `slot` identifies the exact word whose
    // acquire load produced `object`; execute must never dereference it, because doing so would
    // reload a concurrent replacement and defeat capture-at-prefetch. Rotation QSBR keeps both
    // pointers allocated until the fused pass returns. Keep this a trivial, uninitialized aggregate:
    // hot-path capture arrays assign every consumed entry, so default member stores would be waste.
    struct ReadLocalPrefetchCapture {
        ReadLocalProbeResult result;
        const uint64_t* slot;
        const KvObj* object;
        uint64_t state;
    };

    // Non-owning topology snapshot for a foreign probe. Acquire-load all fields and validate
    // the generation before indexing; QSBR must keep the referenced slot allocation alive.
    struct ReadLocalTable {
        uint64_t* slots = nullptr;
        uint32_t cap = 0;
        uint32_t mask = 0;
    };
    // Pair of borrowed table views; read_local_snapshot_topology fills and validates both.
    struct ReadLocalTopology {
        ReadLocalTable tables[2];
    };

    // Layout of the read-local table word. Bit 0 is open while a table mutation is being
    // published; bit 1 is the whole-shard pending marker (any prepared atomic entry, also the
    // fail-closed witness); bits 2..63 are an ABA-resistant generation advanced when the outer
    // table bracket closes.
    static constexpr uint64_t kReadLocalTableMutationBit = uint64_t{1} << 0;
    static constexpr uint64_t kReadLocalPendingBit = uint64_t{1} << 1;
    static constexpr uint32_t kReadLocalGenerationShift = 2;
    static constexpr uint64_t kReadLocalGenerationMask =
        std::numeric_limits<uint64_t>::max() >> kReadLocalGenerationShift;

    // Owner-scoped, nestable topology bracket; moving the guard transfers its closing duty.
    // The outer begin release-stores the mutation bit then uses an acq_rel fence; the outer
    // end release-stores the next generation. Unarmed guards do nothing; imbalance aborts.
    class ReadLocalTableGuard {
    public:
        explicit ReadLocalTableGuard(FlatStore& store, bool active = true)
            : store_(active ? &store : nullptr) {
            if (store_) store_->read_local_table_mutation_begin();
        }
        ~ReadLocalTableGuard() {
            if (store_) store_->read_local_table_mutation_end();
        }
        ReadLocalTableGuard(const ReadLocalTableGuard&) = delete;
        ReadLocalTableGuard& operator=(const ReadLocalTableGuard&) = delete;
        ReadLocalTableGuard(ReadLocalTableGuard&& other) noexcept : store_(other.store_) {
            other.store_ = nullptr;
        }
        ReadLocalTableGuard& operator=(ReadLocalTableGuard&&) = delete;

    private:
        FlatStore* store_;
    };

    // Owner-scoped key exclusion, borrowing the store and hash until destruction. Opening
    // publishes the filter inside a table bracket; closing releases its matching reference.
    // Unarmed guards do nothing; moving transfers the closing duty without allocation.
    class ForeignReadKeyGuard {
    public:
        ForeignReadKeyGuard(FlatStore& store, uint64_t hash)
            : store_(store.read_local_enabled_ ? &store : nullptr), hash_(hash) {
            if (store_) store_->foreign_read_scope_open(hash_);
        }
        ~ForeignReadKeyGuard() {
            if (store_) store_->foreign_read_scope_close(hash_);
        }
        ForeignReadKeyGuard(const ForeignReadKeyGuard&) = delete;
        ForeignReadKeyGuard& operator=(const ForeignReadKeyGuard&) = delete;
        ForeignReadKeyGuard(ForeignReadKeyGuard&& other) noexcept
            : store_(other.store_), hash_(other.hash_) {
            other.store_ = nullptr;
        }
        ForeignReadKeyGuard& operator=(ForeignReadKeyGuard&&) = delete;

    private:
        FlatStore* store_ = nullptr;
        uint64_t hash_ = 0;
    };

    // Owner-scoped whole-shard exclusion for writes that cannot enumerate their keys.
    // Opening brackets filter poison publication; destruction closes the matching reference.
    // The store is borrowed; inactive/unarmed guards do nothing and moves transfer closure.
    class ForeignReadPoisonGuard {
    public:
        explicit ForeignReadPoisonGuard(FlatStore& store, bool active = true)
            : store_(active && store.read_local_enabled_ ? &store : nullptr) {
            if (store_) store_->foreign_read_poison_open();
        }
        ~ForeignReadPoisonGuard() {
            if (store_) store_->foreign_read_poison_close();
        }
        ForeignReadPoisonGuard(const ForeignReadPoisonGuard&) = delete;
        ForeignReadPoisonGuard& operator=(const ForeignReadPoisonGuard&) = delete;
        ForeignReadPoisonGuard(ForeignReadPoisonGuard&& other) noexcept : store_(other.store_) {
            other.store_ = nullptr;
        }
        ForeignReadPoisonGuard& operator=(ForeignReadPoisonGuard&&) = delete;

    private:
        FlatStore* store_ = nullptr;
    };

    // KvObj allocations use alloc_raw(), so probe that exact backend before any shard is built.
    // A platform/allocator that can only supply wider virtual addresses cannot safely use the
    // packed slot format and must be rejected at boot rather than losing pointer bits later.
    static bool pointer_encoding_supported() {
        constexpr size_t kProbeBytes = 64;
        void* probe = alloc_raw(kProbeBytes);
        if (!probe) return false;
        const bool fits = (reinterpret_cast<uint64_t>(probe) & ~kPtrMask) == 0;
        free_sized(probe, kProbeBytes);
        return fits;
    }

    explicit FlatStore(uint32_t initial_cap = 1024) {
        std::construct_at(reinterpret_cast<std::atomic<ObjectIdleClock*>*>(reader_owner_gap_ + 12),
                          nullptr);
        const uint32_t cap = round_pow2(initial_cap);
        if (!cap || !alloc_table(0, cap)) throw std::bad_alloc();
        if (!init_storesize()) {
            std::free(tab_[0]);
            throw std::bad_alloc();
        }
    }
    ~FlatStore() {
        // At process teardown no reader survives. Collapse pending entries first so the ordinary
        // table destructor below remains the unique owner of each promoted winner.
        read_local_enabled_ =
            false;  // shutdown promotion/free is direct; no callback may outlive us
        atomic_promote_all_for_shutdown();
        expires_.clear();
        if (snapshot_new_tab_) std::free(snapshot_new_tab_);
        for (int t = 0; t < 2; t++)
            if (tab_[t]) {
                for (uint32_t i = 0; i < cap_[t]; i++)
                    if (KvObj* o = ptr_of(tab_[t][i])) kvobj_free(o);
                std::free(tab_[t]);
            }
        // Retired objects no longer appear in either table. They remain here only because an io
        // thread may still be handing their value bytes to the kernel.
        for (const Borrow& b : borrows_)
            if (b.retired) kvobj_free(b.retired);
        destroy_storesize();
        delete object_idle_slot()->load(std::memory_order_relaxed);
        std::destroy_at(object_idle_slot());
    }
    FlatStore(const FlatStore&) = delete;
    FlatStore& operator=(const FlatStore&) = delete;

    // Boot-only allocation, before persistence replay or any foreign probe can exist.
    bool prepare_read_local() {
        if (!ensure_read_local_store_state()) return false;
        // Persistence replay may leave a resize in flight before the lane is armed. Reserve
        // its completion record at boot as well as at every later resize admission.
        return prepare_resize_retirement();
    }

    // Enabled is boot-latched. The sink may be rebound only at a quiesced fused ownership handoff;
    // false keeps the old store path and every installed writer hook predicted cold.
    void configure_read_local(bool enabled, ReadLocalRetireSink sink) {
        if (enabled && (!sink.defer || !sink.block_cache)) std::abort();
        // Persistence loading finishes before the fused executor arms this store. Prepared atomic
        // records cannot be retroactively marked in their entry headers, so fail closed if that
        // boot invariant ever changes instead of publishing a false zero-pending state.
        if (enabled && atomic_pending_entries() != 0) std::abort();
        ReadLocalStoreState* state = read_local_store_state();
        if (enabled && !state) std::abort();
        if (state) state->retire_sink = sink;
        read_local_enabled_ = enabled;
    }
    void rebind_read_local_retire_sink(ReadLocalRetireSink sink) {
        if (!read_local_enabled_ || !sink.defer || !sink.block_cache) std::abort();
        // Called only after the old owner has acknowledged an empty task/read/retire frontier and
        // before the new owner executes store work. Advance the table generation at that ownership
        // edge so a foreign copy cannot validate across two retire domains. Foreign probes never
        // read the sink; keeping the boot-latched enabled byte untouched avoids a true-to-true data
        // race at LB resume.
        ReadLocalTableGuard ownership_change(*this);
        read_local_store_state_required().retire_sink = sink;
    }
    bool read_local_enabled() const { return read_local_enabled_; }
    bool read_retirement_available() const {
        if (!read_local_enabled_) return true;
        const auto& sink = read_local_store_state_required().retire_sink;
        return !sink.available || sink.available(sink.context);
    }
#ifdef TOMO_RL_CACHE_DEBUG
    // Debug builds only: lets Server assert that this store's sink still names its CURRENT owner.
    const ReadLocalRetireSink& read_local_retire_sink_debug() const {
        return read_local_store_state_required().retire_sink;
    }
#endif

    uint64_t read_local_state_acquire() const {
        return read_local_store_state_required().probe_sequence.load(std::memory_order_acquire);
    }
    static bool read_local_table_mutating(uint64_t state) {
        return (state & kReadLocalTableMutationBit) != 0;
    }
    static uint32_t read_local_pending(uint64_t state) {
        return (state & kReadLocalPendingBit) ? 1u : 0u;
    }
    static uint64_t read_local_generation(uint64_t state) {
        return state >> kReadLocalGenerationShift;
    }
    // Wrap publishes this permanent fail-closed value rather than an equal "stable" generation.
    static bool read_local_generation_poisoned(uint64_t state) {
        return read_local_generation(state) == kReadLocalGenerationMask;
    }
    static bool read_local_state_eligible(uint64_t state) {
        return !read_local_table_mutating(state) && !read_local_generation_poisoned(state);
    }
    // Equal table generation regardless of the independent pending hint; callers compare two words
    // they have already proven even.
    static bool read_local_generation_equal(uint64_t first, uint64_t second) {
        return read_local_generation(first) == read_local_generation(second);
    }
    [[nodiscard]] ReadLocalTableGuard read_local_table_guard() {
        return ReadLocalTableGuard(*this);
    }

    bool foreign_read_key_unsafe(uint64_t state, uint64_t hash) const {
        // Pending is also the cheap empty-filter hint. It stays latched if filter bookkeeping ever
        // permanently poisons, so short-circuiting here cannot turn that fail-closed state into a
        // false negative after the last enumerable entry drains.
        if (!read_local_pending(state)) return false;
        return read_local_store_state_required().foreign_reads.might_contain(hash);
    }
    bool foreign_read_key_unsafe(uint64_t hash) const {
        const uint64_t state = read_local_state_acquire();
        return foreign_read_key_unsafe(state, hash);
    }
    // Multi-key window validator. Load it only for a key whose shard word carries the pending bit,
    // and only to compare against a later load of the same cell. Called only on the armed lane.
    uint32_t foreign_read_cell_epoch(uint64_t hash) const {
        return read_local_store_state_required().foreign_reads.cell_epoch(hash);
    }
    static uint32_t foreign_read_filter_index(uint64_t hash) {
        return ForeignReadSafety::cell_index(hash);
    }
    static uint32_t foreign_read_filter_fingerprint(uint64_t hash) {
        return ForeignReadSafety::fingerprint(hash);
    }
    uint64_t foreign_read_unsafe_refs() const {
        const ReadLocalStoreState* state = read_local_store_state();
        return state ? state->foreign_reads.unsafe_total_refs() : 0;
    }
    uint64_t foreign_read_occupied_cells() const {
        const ReadLocalStoreState* state = read_local_store_state();
        return state ? state->foreign_reads.occupied_cells() : 0;
    }
    uint64_t foreign_read_wildcard_cells() const {
        const ReadLocalStoreState* state = read_local_store_state();
        return state ? state->foreign_reads.wildcard_cells() : 0;
    }
    uint64_t foreign_read_saturated_cells() const {
        const ReadLocalStoreState* state = read_local_store_state();
        return state ? state->foreign_reads.saturated_cells() : 0;
    }
    bool foreign_read_poisoned() const {
        const ReadLocalStoreState* state = read_local_store_state();
        return state && state->foreign_reads.poison_refs() != 0;
    }
    [[nodiscard]] ForeignReadKeyGuard foreign_read_key_guard(uint64_t hash) {
        return ForeignReadKeyGuard(*this, hash);
    }
    [[nodiscard]] ForeignReadPoisonGuard foreign_read_poison_guard(bool active = true) {
        return ForeignReadPoisonGuard(*this, active);
    }

    // Same-owner group/script paths retain their enumerated hashes through finish. Duplicate
    // occurrences are intentional and must be closed symmetrically.
    template <typename HashAt>
    void foreign_read_scope_open_span(uint32_t count, HashAt&& hash_at) {
        if (!read_local_enabled_) return;
        // Unlike an AtomicEntry, this scoped path may mutate through an ordinary immutable slot
        // replacement. Complete a brief sequence handshake around filter publication so a point
        // reader that already observed a negative cell cannot validate across the later handler.
        ReadLocalTableGuard publication(*this);
        ReadLocalStoreState& state = read_local_store_state_required();
        state.foreign_reads.add_span(count, std::forward<HashAt>(hash_at));
        foreign_read_pending_witness_open(state);
    }

    template <typename HashAt>
    void foreign_read_scope_close_span(uint32_t count, HashAt&& hash_at) {
        if (!read_local_enabled_) return;
        ReadLocalStoreState& state = read_local_store_state_required();
        state.foreign_reads.close_span(count, std::forward<HashAt>(hash_at));
        foreign_read_pending_witness_close(state);
    }

    void foreign_read_scope_open(uint64_t hash) {
        foreign_read_scope_open_span(1, [&](uint32_t) { return hash; });
    }

    void foreign_read_scope_close(uint64_t hash) {
        foreign_read_scope_close_span(1, [&](uint32_t) { return hash; });
    }

    // An enumerator that cannot name every key publishes a whole-shard wildcard. The caller must
    // retain and close this scope after declining or completing the write.
    void foreign_read_unenumerable_open() {
        if (read_local_enabled_) foreign_read_poison_open();
    }
    void foreign_read_unenumerable_close() {
        if (read_local_enabled_) foreign_read_poison_close();
    }

    // Unit-test view of the same capture consumed by the production read-local lane.
    ReadLocalProbe read_local_probe(uint64_t hash, Slice key) const {
        const auto capture = read_local_prefetch_capture(hash, key);
        return {capture.result, capture.object, capture.state};
    }

#ifdef TOMO_PROBEADAPTER_TEST
    // Serverless entry witness, including disabled and unsafe-key early returns.
    // Static test state adds no field, store allocation, or release instruction.
    // The captured hook below witnesses the later topology-check window.
    inline static void (*test_read_local_capture_entered)(const FlatStore&) = nullptr;
#endif

    bool read_local_validate(uint64_t state) const {
        return read_local_enabled_ && read_local_state_eligible(state) &&
               read_local_probe_sequence_equal(read_local_state_acquire(), state);
    }

    void read_local_prefetch(uint64_t hash) const {
        if (__builtin_expect(!read_local_enabled_, false)) return;
        const uint64_t state = read_local_state_acquire();
        if (!read_local_state_eligible(state)) return;
        ReadLocalTopology topology;
        if (!read_local_snapshot_topology(state, topology)) return;
        for (const ReadLocalTable& table : topology.tables) {
            if (!table.slots || !table.cap) continue;
            const uint32_t slot = static_cast<uint32_t>(mix64(hash)) & table.mask;
            __builtin_prefetch(table.slots + slot, 0, 1);
        }
    }

    // Capture one foreign lookup for ExLoopT's local-read batch under its QSBR lifetime.
    // Acquire-load topology and slot words, then validate the generation before returning
    // borrowed pointers. Disabled/changed topology returns Churn; an unsafe key returns
    // AtomicPending for owner fallback. This function makes one attempt and does not retire.
    ReadLocalPrefetchCapture read_local_prefetch_capture(uint64_t hash, Slice key) const {
#ifdef TOMO_PROBEADAPTER_TEST
        if (test_read_local_capture_entered) test_read_local_capture_entered(*this);
#endif
        if (__builtin_expect(!read_local_enabled_, false))
            return {ReadLocalProbeResult::Churn, nullptr, nullptr, 0};
        const uint64_t state = read_local_state_acquire();
        if (foreign_read_key_unsafe(state, hash))
            return {ReadLocalProbeResult::AtomicPending, nullptr, nullptr, state};
        if (!read_local_state_eligible(state))
            return {ReadLocalProbeResult::Churn, nullptr, nullptr, state};

        ReadLocalTopology topology;
        if (!read_local_snapshot_topology(state, topology)) {
            const uint64_t changed = read_local_state_acquire();
            return {foreign_read_key_unsafe(changed, hash) ? ReadLocalProbeResult::AtomicPending
                                                           : ReadLocalProbeResult::Churn,
                    nullptr, nullptr, changed};
        }

        const uint64_t* slot = nullptr;
        const KvObj* object = read_local_capture_in(topology.tables[0], hash, key, slot);
        if (!object) {
            const uint64_t* old_slot = nullptr;
            object = read_local_capture_in(topology.tables[1], hash, key, old_slot);
            // Keep the current table's empty stopper when there is no old table. During a rehash,
            // the old-table match/stopper is the last word that decided the complete lookup.
            if (old_slot) slot = old_slot;
        }
#if defined(TOMO_CORE_CONCURRENCY_TEST) || defined(TOMO_PROBEADAPTER_TEST)
        if (test_read_local_captured) test_read_local_captured(*this);
#endif
        const uint64_t final_state = read_local_state_acquire();
        if (!read_local_probe_sequence_equal(final_state, state)) {
            return {foreign_read_key_unsafe(final_state, hash) ? ReadLocalProbeResult::AtomicPending
                                                               : ReadLocalProbeResult::Churn,
                    nullptr, nullptr, final_state};
        }
        if (object) read_local_prefetch_object(object);
        return {object ? ReadLocalProbeResult::Hit : ReadLocalProbeResult::Missing, slot, object,
                state};
    }

#if defined(TOMO_CORE_CONCURRENCY_TEST) || defined(TOMO_PROBEADAPTER_TEST)
    // Deterministic topology interleaving, absent from release code and object layouts.
    inline static void (*test_read_local_captured)(const FlatStore&) = nullptr;
#endif

    bool rehashing() const { return tab_[1] != nullptr; }
    // Owner-only observation: DEBUG REHASH-STATE runs on shard 0's owner, so these real
    // migration counters need neither cross-thread sampling nor new per-step instrumentation.
    struct RehashProgress {
        uint32_t current_capacity, old_capacity, cursor, old_live;
    };
    RehashProgress rehash_progress() const { return {cap_[0], cap_[1], rehash_pos_, live_[1]}; }
    uint32_t size() const { return live_[0] + live_[1]; }
    uint64_t capacity() const { return static_cast<uint64_t>(cap_[0]) + cap_[1]; }
    size_t object_bytes() const { return obj_bytes_ + atomic_version_bytes_; }
    uint32_t expire_count() const { return expires_.size(); }
    // Cold batch-boundary publication. No key/TTL mutation publishes counters.
    [[gnu::noinline, gnu::cold]] bool init_storesize();
    [[gnu::noinline]] void publish_keyspace_sample() const noexcept;
    bool published_field_ttl_attention() const noexcept;
    uint64_t published_avg_deadline(uint8_t physical = 0) const;
    uint64_t published_database_counts(uint8_t physical) const;
    [[gnu::noinline]] void publish_database_counts() const noexcept;
    // Hashes in this shard carrying at least one field deadline. THE gate for the whole hash-field
    // TTL feature: a shard that has never seen HEXPIRE reads zero here and every hash command pays
    // one predicted-false test, with all field-TTL machinery out of line behind it.
    uint32_t field_expire_count() const { return field_ttl_gate_; }
    // Registration is idempotent and keyed by key hash only, exactly like expires_. A stale entry
    // (key replaced, deleted, or persisted) is harmless: the cycle drops it on its next visit.
    void note_field_ttl(uint64_t h) {
        // A missed registration must not disarm logical expiry. Keep the lazy-access gate
        // sticky until FLUSH if the attention index could not allocate its entry.
        if (!field_expires_.insert(h)) field_ttl_index_incomplete_ = true;
        refresh_field_ttl_gate();
    }
    // A positive count means a hash field was collected on an access path,
    // not merely filtered out of a reply. INFO reports it as expired_hash_fields.
    void note_field_expired(uint32_t n) { field_expired_ += n; }
    // Re-arms type-specific attention for an imported image, including atomic COPY/RENAME APPLY.
    // The type guard keeps hash-field machinery behind the hash-only branch.
    void note_loaded_object(uint64_t h, const KvObj* o) {
        if (static_cast<Type>(o->type) == Type::String) return;
        // Imported images (COPY/RESTORE/*STORE/RENAME) create collections
        // without going through their native push handlers. Signal here, at
        // installation, so wake coverage follows the type rather than a list
        // of commands. Native pushes already signal behind their waiter gate.
        if (static_cast<Type>(o->type) == Type::List || static_cast<Type>(o->type) == Type::Zset ||
            static_cast<Type>(o->type) == Type::Stream) {
            if (blocking_key_created) blocking_key_created(this, o->key());
            return;
        }
        if (static_cast<Type>(o->type) != Type::Hash) return;
        if (static_cast<Enc>(o->enc) == Enc::Compact) return;
        if (static_cast<const HashVal*>(o->external_ptr())->ttls) note_field_ttl(h);
    }
    void bind_aof(AofManager* manager, int32_t sid, uint32_t next_sequence) {
        aof_.init(manager, sid, next_sequence);
    }
    AofProducer& aof() { return aof_; }
    const AofProducer& aof() const { return aof_; }
    // AOF group fragments describe the private candidate installed by this owner before its
    // cross-shard visibility ticket is published. Logical find() must hide that candidate; this
    // owner-only tap intentionally reads the newest physical representation instead.
    KvObj* aof_physical(uint64_t hash, Slice key) const {
        if (KvObj* object = find_in(0, hash, key)) return object;
        return rehashing() ? find_in(1, hash, key) : nullptr;
    }
    size_t accounted_bytes() const {
        const size_t keys = size();
        const size_t objects = obj_bytes_ + atomic_version_bytes_;
        if (keys > (std::numeric_limits<size_t>::max() - objects) / kSlotOverheadPerKey)
            return std::numeric_limits<size_t>::max();
        return objects + static_cast<uint64_t>(keys) * kSlotOverheadPerKey;
    }

// ==== epoch-MVCC atomics (see src/store/flatstore_atomic.inc) ====
#include "flatstore_atomic.inc"

    enum class SnapshotWriteResult : uint8_t { Ready, Pending, Error };
    enum class EraseEvent : uint8_t { Del, Evicted, None };

    // Phase 1 of the cut barrier.  Existing incremental rehashing is completed in its ordinary
    // bounded steps; only then is a fresh post-cut table allocated.  Resize remains suppressed
    // while prepared, so the owner can keep serving until the later freeze barrier without making
    // this allocation stale.  snapshot_mark() is then only a pointer swap at the epoch boundary.
    SnapshotWriteResult snapshot_prepare(uint64_t epoch, int64_t cut_ms) {
        if (snapshot_active_) return SnapshotWriteResult::Error;
        if (rehashing()) {
            rehash_step();
            return SnapshotWriteResult::Pending;
        }
        if (snapshot_prepared_) return SnapshotWriteResult::Ready;
        if (read_local_enabled_ && !prepare_resize_retirement()) return SnapshotWriteResult::Error;
        // A completed snapshot leaves its fresh table installed. Doubling cap_[0] on every
        // cut therefore grows an idle store forever. Reserve twice the ordinary live-set
        // capacity instead, bounded above by twice cap_[0]. Do not shrink here: until Mark,
        // prepared inserts (including atomic reservations) may still fill the current table.
        // Keeping at least cap_[0] makes their admission bound safe for the merge.
        uint64_t sized = kMinCap;
        while ((static_cast<uint64_t>(live_[0]) + 1) * 100 >= sized * kLoadPct) sized *= 2;
        uint64_t wanted = std::max<uint64_t>(cap_[0], std::min<uint64_t>(sized, cap_[0]) * 2);
        if (wanted > UINT32_MAX) return SnapshotWriteResult::Error;
        const uint32_t cap = round_pow2(static_cast<uint32_t>(wanted));
        if (!cap) return SnapshotWriteResult::Error;
        auto* fresh = static_cast<uint64_t*>(flatstore_table_calloc(cap, sizeof(uint64_t)));
        if (!fresh) return SnapshotWriteResult::Error;
        snapshot_new_tab_ = fresh;
        snapshot_new_cap_ = cap;
        snapshot_epoch_ = epoch;
        snapshot_cut_ms_ = cut_ms;
        snapshot_prepared_ = true;
        return SnapshotWriteResult::Ready;
    }

    // Phase 2 of the cut barrier: no owner is executing an operation while these swaps run.  The
    // old table becomes the immutable-layout snapshot table (values may change only after their
    // pre-image has been serialized), and all new keys land in the fresh current table.
    bool snapshot_mark(int32_t shard_id, int64_t cut_ms) {
        if (__builtin_expect(read_local_enabled_, false))
            return snapshot_mark_read_local(shard_id, cut_ms);
        if (!snapshot_prepared_ || snapshot_active_ || rehashing()) return false;
        tab_[1] = tab_[0];
        cap_[1] = cap_[0];
        mask_[1] = mask_[0];
        live_[1] = live_[0];
        tombs_[1] = tombs_[0];
        tab_[0] = snapshot_new_tab_;
        cap_[0] = snapshot_new_cap_;
        mask_[0] = cap_[0] - 1;
        live_[0] = tombs_[0] = 0;
        snapshot_new_tab_ = nullptr;
        snapshot_new_cap_ = 0;
        snapshot_prepared_ = false;
        rehash_pos_ = 0;
        snapshot_active_ = true;
        snapshot_shard_id_ = shard_id;
        snapshot_cut_ms_ = cut_ms;
        snapshot_pos_ = 0;
        snapshot_sequence_ = 0;
        snapshot_failed_ = false;
        snapshot_finished_ = false;
        snapshot_build_ = make_snapshot_chunk(SnapshotFrameBegin);
        snapshot_ready_.reset();
        snapshot_record_ = {};
        return snapshot_build_ != nullptr;
    }

    bool snapshot_active() const { return snapshot_active_; }
    bool snapshot_failed() const { return snapshot_failed_; }

    uint64_t snapshot_preimages() const { return snapshot_preimages_; }

    // Owner write gate: a slot behind the traversal cursor is already dumped. A slot ahead
    // is serialized incrementally and marked with kTombBit; traversal clears the mark and
    // skips the post-cut value. Pending keeps the caller from mutating that object yet.
    SnapshotWriteResult snapshot_prepare_write(uint64_t h, Slice key) {
        if (__builtin_expect(read_local_enabled_, false))
            return snapshot_prepare_write_read_local(h, key);
        if (!snapshot_active_) return SnapshotWriteResult::Ready;
        if (snapshot_failed_) return SnapshotWriteResult::Error;
        if (find_in(0, h, key)) return SnapshotWriteResult::Ready;  // born/moved after the cut
        uint32_t slot = 0;
        KvObj* object = find_slot_in(1, h, key, slot);
        if (!object || slot < snapshot_pos_ || (tab_[1][slot] & kTombBit))
            return SnapshotWriteResult::Ready;
        if (deadline_elapsed(h, object, snapshot_cut_ms_)) {
            tab_[1][slot] |= kTombBit;  // absent at the cut; traversal must skip it
            return SnapshotWriteResult::Ready;
        }
        if (snapshot_record_.active) return SnapshotWriteResult::Pending;
        if (!snapshot_start_record(object, slot, true)) return SnapshotWriteResult::Error;
        snapshot_preimages_++;  // counts pre-images started by writes ahead of traversal
        return SnapshotWriteResult::Pending;
    }

    // CPU work on the owner, bounded by both bytes and examined slots.  It never writes a file.
    uint32_t snapshot_progress(uint32_t byte_budget, uint32_t slot_budget) {
        if (__builtin_expect(read_local_enabled_, false))
            return snapshot_progress_read_local(byte_budget, slot_budget);
        if (!snapshot_active_ || snapshot_failed_ || snapshot_ready_) return 0;
        uint32_t work = 0;
        while (byte_budget && !snapshot_ready_ && !snapshot_failed_) {
            if (snapshot_record_.active) {
                const uint32_t before = byte_budget;
                snapshot_progress_record(byte_budget);
                work += before - byte_budget;
                if (snapshot_record_.active || snapshot_ready_) break;
                continue;
            }
            if (snapshot_pos_ >= cap_[1]) {
                snapshot_finish_stream();
                break;
            }
            if (!slot_budget) break;
            const uint32_t slot = snapshot_pos_;
            const uint64_t word = tab_[1][slot];
            KvObj* object = ptr_of(word);
            slot_budget--;
            work++;
            if (!object) {
                snapshot_pos_++;
                continue;
            }
            if (word & kTombBit) {
                tab_[1][slot] = word & ~kTombBit;
                snapshot_pos_++;
                continue;
            }
            if (deadline_elapsed(hash_key(object->key()), object, snapshot_cut_ms_)) {
                snapshot_pos_++;
                continue;
            }
            if (!snapshot_start_record(object, slot, false)) break;
        }
        return work;
    }

    std::unique_ptr<SnapshotChunk> snapshot_take_chunk() { return std::move(snapshot_ready_); }

    void snapshot_handoff_complete() {
        if (!snapshot_finished_) return;
        snapshot_active_ = false;
        snapshot_shard_id_ = -1;
        snapshot_build_.reset();
        snapshot_ready_.reset();
        snapshot_record_ = {};
        // tab_[1] becomes an ordinary old table. Subsequent operations merge it with the bounded
        // rehash step; successful post-cut inserts are capacity-gated so the destination
        // can hold the complete logical set.
    }

    void snapshot_cancel() {
        if (snapshot_new_tab_) std::free(snapshot_new_tab_);
        snapshot_new_tab_ = nullptr;
        snapshot_new_cap_ = 0;
        snapshot_prepared_ = false;
        snapshot_active_ = false;
        snapshot_failed_ = false;
        snapshot_finished_ = false;
        snapshot_build_.reset();
        snapshot_ready_.reset();
        snapshot_record_ = {};
        snapshot_shard_id_ = -1;
        // Any pre-image marks still live in tab_[1] are harmless to normal lookup and are cleared
        // as the ordinary rehash moves those slot words back through make_word().
    }

    // What a migration of this shard would cost the NEW domain to re-pull through the fabric. Not a
    // copy cost — nothing is copied — but an L3 domain is filled by access, so a shard that moves
    // has to be read back in on the other side.
    size_t resident_estimate() const {
        return static_cast<size_t>((static_cast<uint64_t>(cap_[0]) + cap_[1]) * sizeof(uint64_t)) +
               obj_bytes_ + atomic_version_bytes_ + pending_bytes_ + expires_.memory_bytes() +
               field_expires_.memory_bytes();
    }

    // Collection values grow and shrink behind a stable KvObj header. The shard owner brackets
    // such a mutation with kvobj_size() samples and reports the delta here so later erase/rehash
    // subtracts the same footprint that is currently charged. Single-owner: no atomic or lock.
    void note_object_size_change(size_t before, size_t after) {
        if (after >= before)
            obj_bytes_ += after - before;
        else
            obj_bytes_ -= before - after;
    }

    KvObj* find(uint64_t h, Slice key) {
        // Lookup must not inherit a resize's QSBR retirement wait. Both tables remain searchable;
        // mutations and owner maintenance advance rehashing, including its final table retirement.
        KvObj* found = nullptr;
        if (__builtin_expect(atomic_pending_ != nullptr, false) &&
            __builtin_expect(atomic_pending_->live != 0, false)) {
            found = atomic_resolve(h, key, atomic_read_epoch_);
        } else {
            if (KvObj* o = find_in(0, h, key)) found = live_or_expire(0, h, key, o);
            if (rehashing()) {
                if (!found)
                    if (KvObj* o = find_in(1, h, key)) found = live_or_expire(1, h, key, o);
            }
        }
        // The entire disabled-feature read tax: one predicted branch, no metadata write.
        // CLIENT NO-TOUCH rides INSIDE that branch -- with maxmemory off (the default) the
        // no-touch byte is never even loaded, because && short-circuits.
        if (__builtin_expect(maxmemory_enabled_ && !no_touch_, false) && found) touch(found);
        return found;
    }

    KvObj* find_notify(uint64_t h, Slice key, FlatNotifySink* sink) {
        KvObj* candidate = find_in(0, h, key);
        if (!candidate && rehashing()) candidate = find_in(1, h, key);
        const bool expired = candidate && deadline_elapsed(h, candidate, cached_now_ms_) &&
                             !(snapshot_active_ && candidate == find_in(1, h, key));
        if (expired && !client_pause_expiry_held() && !notify_read_resolves_versions() &&
            read_retirement_available())
            notify_emit(sink, NOTIFY_EXPIRED, NotifyEventId::Expired, candidate->key());
        KvObj* found = find(h, key);
        if (!found) notify_emit(sink, NOTIFY_KEY_MISS, NotifyEventId::Keymiss, key);
        return found;
    }

    // Notification-only cold query. The version-aware find is a logical read:
    // it neither deletes a foreign candidate nor reaps an expired predecessor.
    // Match find's live-version predicate exactly: script intents alone leave
    // physical expiry enabled. Unrelated keys use the resolver while versions live.
    __attribute__((noinline)) bool notify_read_resolves_versions() const {
        return atomic_pending_ && atomic_pending_->live != 0;
    }

    // Same-size-CLASS overwrite, allocation-free. Asking for 88 bytes gets 96, so a value that grew
    // or shrank a little still fits what was already paid for. The test is equality of CLASS rather
    // than "new <= old" because good_size() is recomputed from the header — letting the real
    // allocation and the implied one diverge would silently break the resident estimate.
    OverwriteResult try_overwrite(uint64_t h, Slice key, Slice val) {
        if (__builtin_expect(read_local_enabled_, false))
            return try_overwrite_read_local(h, key, val);
        KvObj* o = find_without_touch(h, key);
        if (!o) return OverwriteResult::NotPossible;
        if (o->encoding() != Enc::Raw) return OverwriteResult::NotPossible;
        if (o->flags & KvObjFlags::HasTtl) return OverwriteResult::NotPossible;  // SET clears TTL
        if (val.n > kEmbedThreshold) return OverwriteResult::NotPossible;        // becomes Extern
        const size_t want = kvobj_alloc_size(o->key().identity(), val.n, false, Enc::Raw);
        if (good_size(want) != kvobj_capacity(o)) return OverwriteResult::NotPossible;

        // In-place overwrite is the one mutation that would change bytes without retiring their
        // allocation. With no outstanding borrows this is one predicted branch and no lookup.
        if (outstanding_borrows_ && is_borrowed(o->str_data())) return OverwriteResult::NotPossible;

        // The entire disabled-feature write tax is this branch. When enabled, the target key is
        // protected while make_room_for() evicts other candidates.
        if (__builtin_expect(maxmemory_enabled_, false)) {
            if (!make_room_for(key, good_size(want))) return OverwriteResult::MaxmemoryOom;
            touch(o);
        }

        // Same length means the same class and footprint, so the accounting delta is zero.
        if (val.n == kvobj_read_local_raw_length(o)) {
            std::memcpy(o->val_ptr(), val.p, val.n);
            return OverwriteResult::Updated;
        }
        obj_bytes_ -= kvobj_size(o);
        o->store_raw_length_relaxed(val.n);
        std::memcpy(o->val_ptr(), val.p, val.n);
        obj_bytes_ += kvobj_size(o);
        return OverwriteResult::Updated;
    }

    OverwriteResult try_overwrite_notify(uint64_t h, Slice key, Slice val, FlatNotifySink*) {
        return try_overwrite(h, key, val);
    }

    // Armed SET builds a fresh string block, release-publishes it on insertion, and retires
    // the displaced block through QSBR so foreign readers cannot see partially written bytes.
    // Inline values use the owner's post-grace cache, then alloc_raw on a miss. Extern values
    // keep their independent allocation and use kvobj_new_string. Unarmed writes also use
    // kvobj_new_string, behind the read_local_enabled_ branch.
    KvObj* make_set_string(Slice key, Slice value, int64_t expire_at_ms = -1,
                           bool reserve_ttl_slot = false) {
        if (__builtin_expect(read_local_enabled_, false) && value.n <= kEmbedThreshold) {
            const bool has_ttl_slot = reserve_ttl_slot || expire_at_ms >= 0;
            const size_t allocation =
                good_size(kvobj_alloc_size(key.identity(), value.n, has_ttl_slot, Enc::Raw));
            void* memory = read_local_cache_take(allocation);
            if (!memory) {
                memory = alloc_raw(allocation);
            }
            if (!memory) {
                // The allocator refused. The cache is holding physical memory nothing needs;
                // hand it back and ask exactly once more before reporting OOM.
                read_local_cache_release_all();
                memory = alloc_raw(allocation);
            }
            return memory
                       ? kvobj_init_raw_string(memory, key, value, expire_at_ms, reserve_ttl_slot)
                       : nullptr;
        }
        return kvobj_new_string(key, value, expire_at_ms, reserve_ttl_slot);
    }

    KvObj* make_set_int(Slice key, int64_t value, int64_t expire_at_ms = -1,
                        bool reserve_ttl_slot = false) {
        if (__builtin_expect(read_local_enabled_, false)) {
            const bool has_ttl_slot = reserve_ttl_slot || expire_at_ms >= 0;
            const size_t allocation =
                good_size(kvobj_alloc_size(key.identity(), 0, has_ttl_slot, Enc::Int));
            void* memory = read_local_cache_take(allocation);
            if (!memory) {
                memory = alloc_raw(allocation);
            }
            if (!memory) {
                read_local_cache_release_all();
                memory = alloc_raw(allocation);
            }
            return memory ? kvobj_init_int(memory, key, value, expire_at_ms, reserve_ttl_slot)
                          : nullptr;
        }
        return kvobj_new_int(key, value, expire_at_ms, reserve_ttl_slot);
    }

    // Discard an unpublished replacement without a grace period. Callers retain ownership
    // when insertion fails (allocation/admission refusal); return the block to the allocator
    // rather than retaining it in the cache under memory pressure.
    void discard_set_value(KvObj* object) {
        if (!object) return;
        kvobj_free(object);
    }

    // Called by GET on the shard owner before publishing the Op. Pointer identity is sufficient:
    // an allocation cannot be reused while it is either table-owned or retained as `retired`.
    void borrow(const char* ptr) {
        const uint32_t at = borrow_find(ptr);
        if (at != kNoBorrow) {
            borrows_[at].refs++;
            outstanding_borrows_++;
            return;
        }
        borrows_.push_back(Borrow{ptr, 1, nullptr});
        // Publish the count only after push_back succeeds. A failed registry growth must not leave
        // an unreturnable phantom borrow behind (cross-shard MGET can recover as an OOM reply).
        borrow_index_added(ptr, static_cast<uint32_t>(borrows_.size() - 1));
        outstanding_borrows_++;
    }

    // Called only by the shard owner after an io-thread release crosses back through its channel.
    // The last reference is also the point at which a logically removed object may be destroyed.
    void unborrow(const char* ptr) {
        const uint32_t at = borrow_find(ptr);
        if (at == kNoBorrow) return;
        Borrow& b = borrows_[at];
        if (b.refs == 0 || outstanding_borrows_ == 0) return;
        b.refs--;
        outstanding_borrows_--;
        if (b.refs) return;
        if (b.retired) {
            const size_t capacity = kvobj_capacity(b.retired);
            pending_bytes_ -= capacity + kvobj_external_bytes(b.retired);
            free_retired_obj_now(b.retired, capacity);
        }
        borrow_index_dropped(ptr);
        const uint32_t last = static_cast<uint32_t>(borrows_.size() - 1);
        if (at != last) {
            borrows_[at] = borrows_[last];
            // The moved entry keeps its identity but changes slot; relabel BEFORE pop_back, while
            // borrows_[last] is still readable for the pointer comparison inside the index.
            borrow_index_put(borrows_[at].ptr, at);
        }
        borrows_.pop_back();
        if (borrows_.empty()) borrow_index_release();
    }

    uint32_t outstanding_borrows() const { return outstanding_borrows_; }

    void set_cached_now_ms(int64_t now_ms) { cached_now_ms_ = now_ms; }
    void set_cached_lru_clock(uint8_t clock) { cached_lru_clock_ = clock; }
    // Lifetime high-water mark for successful active reaps.  The deadline is known logical here;
    // still reject a negative value defensively so a retained-but-persisted slot cannot report a
    // multi-billion-millisecond lag.  Four bytes are enough for almost 50 days and larger stalls
    // saturate instead of wrapping.
    void note_active_expire_reap(int64_t deadline_ms) {
        if (deadline_ms < 0 || cached_now_ms_ <= deadline_ms) return;
        const uint64_t lag = static_cast<uint64_t>(cached_now_ms_ - deadline_ms);
        const uint32_t bounded = lag > std::numeric_limits<uint32_t>::max()
                                     ? std::numeric_limits<uint32_t>::max()
                                     : static_cast<uint32_t>(lag);
        if (bounded > active_expire_reap_lag_ms_max_) active_expire_reap_lag_ms_max_ = bounded;
    }
    uint32_t active_expire_reap_lag_ms_max() const { return active_expire_reap_lag_ms_max_; }
    // Owner-thread scratch: the current task's CLIENT NO-TOUCH answer. Written only when
    // maxmemory is enabled, so it costs nothing in the default configuration.
    bool no_touch() const { return no_touch_; }
    void set_no_touch(bool value) { no_touch_ = value; }

    // OBJECT IDLETIME/FREQ report the same five-bit eviction metadata the victim chooser reads, so
    // they need the policy, the arming flag and the clock that gives the bits their meaning. All
    // three are owner-thread reads of owner-thread state; nothing here is on the lookup path.
    MaxmemoryPolicy maxmemory_policy() const { return maxmemory_policy_; }
    bool maxmemory_enabled() const { return maxmemory_enabled_; }
    uint8_t published_lru_clock() const { return cached_lru_clock_; }
    // OBJECT must not count as an access: reporting idle time through find() would reset the very
    // metadata being reported. Redis solves the same problem with LOOKUP_NOTOUCH.
    KvObj* find_no_touch(uint64_t h, Slice key) { return find_without_touch(h, key); }
    // MEMORY USAGE asks what an entry costs, not whether it is readable. Redis answers it from a
    // raw dictionary lookup with no expire check, so an elapsed-but-unreaped key still reports its
    // footprint -- which is the honest answer, since those bytes are still resident.
    KvObj* find_resident(uint64_t h, Slice key) const {
        if (KvObj* object = find_in(0, h, key)) return object;
        return rehashing() ? find_in(1, h, key) : nullptr;
    }
    // Owner-only deadline accessor. Each immutable object version carries its own deadline.
    int64_t deadline(uint64_t, const KvObj* object) const {
        if (!object || !object->has_ttl_slot()) return kNoTtlDeadline;
        const int64_t inline_deadline = object->expire_at_ms();
        return inline_deadline;
    }
    bool deadline_elapsed(uint64_t h, const KvObj* object, int64_t now_ms) const {
        const int64_t at = deadline(h, object);
        return at >= 0 && at < now_ms;  // Redis keyIsExpired(): now > at; live at now == at
    }
    // The deadline WATCH pins on an armed key. Redis probes the key with LOOKUP_NOTOUCH and does
    // not reap it, so an elapsed-but-unreaped key must stay physically counted here too. A key that
    // is ALREADY past its deadline when WATCH runs is redis's `wk->expired`: its later removal is
    // not a change the transaction should see, so it captures -1 exactly like a TTL-free key.
    int64_t watch_deadline(uint64_t h, Slice key) const {
        const KvObj* object = find_resident(h, key);
        if (!object) return -1;
        const int64_t at = deadline(h, object);
        return at >= cached_now_ms_ ? at : -1;
    }
    void bind_expired_counter(uint64_t* counter) { expired_counter_ = counter; }
    void bind_evicted_counter(uint64_t* counter) { evicted_counter_ = counter; }
    // Table rebuilds started. Cold (once per resize, never on the hot path) and it exists so a
    // SCAN-correctness test can PROVE the hazard it guards actually occurred: a run in which this
    // does not move has not exercised resize-during-iteration at all, and its "0 keys missed"
    // would be vacuous.
    void bind_rehash_counter(uint64_t* counter) { rehash_counter_ = counter; }
    // The slot has a real atomic lifetime in reserved, eight-byte-aligned storage.
    // Shard migration moves the store and its already-bound QSBR sink together.
    std::atomic<ObjectIdleClock*>* object_idle_slot() const {
        return std::launder(reinterpret_cast<std::atomic<ObjectIdleClock*>*>(
            const_cast<char*>(reader_owner_gap_) + 12));
    }
    [[gnu::noinline]] void note_object_access(const KvObj* object, int64_t now_ms) const {
        if (auto* clock = object_idle_slot()->load(std::memory_order_acquire))
            clock->touch(object, now_ms);
    }
    [[gnu::noinline]] uint32_t object_idle_seconds(const KvObj* object) const {
        auto* clock = object_idle_slot()->load(std::memory_order_acquire);
        return clock ? clock->idle(object, cached_now_ms_) : 0;
    }
    [[gnu::noinline]] bool object_idle_install(uint64_t hash, const KvObj* object) {
        auto* clock = object_idle_slot()->load(std::memory_order_acquire);
        if (!clock) return true;
        uint32_t stamp = ObjectIdleClock::clock(cached_now_ms_);
        if (no_touch_) {
            auto* old = find_resident(hash, object->key());
            if (old && !deadline_elapsed(hash, old, cached_now_ms_))
                stamp = clock->timestamp(old, stamp);
        }
        return clock->install(object, stamp, obj_bytes_);
    }
    [[gnu::noinline]] size_t object_idle_allocation_bytes(const KvObj* object) const {
        const auto* clock = object_idle_slot()->load(std::memory_order_relaxed);
        return clock ? clock->allocation_bytes(object) : 0;
    }
    static void reclaim_object_idle(void* owner, void* payload, size_t bytes) {
        // The owner drains its retire ring before shard migration or teardown.
        // Keep the charge until the last foreign reader has passed its grace.
        delete static_cast<ObjectIdleClock*>(payload);
        static_cast<FlatStore*>(owner)->obj_bytes_ -= bytes;
    }
    // False when enabling cannot allocate/populate the clock. Nothing escapes: the partial
    // clock is freed here and the slot stays empty, so OBJECT IDLETIME reads 0 for this store.
    // Eviction is unaffected: the victim chooser reads the five-bit LRU meta, not this clock.
    [[gnu::noinline, gnu::cold]] bool /* TOMO_TOOL_BIND configure_object_idle */
    configure_object_idle(bool enabled) {
        auto* current = object_idle_slot()->load(std::memory_order_relaxed);
        if (enabled == (current != nullptr)) return true;
        if (enabled) {
            std::unique_ptr<ObjectIdleClock> fresh(new (std::nothrow) ObjectIdleClock);
            if (!fresh) return false;
            size_t bytes = sizeof(ObjectIdleClock);
            const auto now = ObjectIdleClock::clock(cached_now_ms_);
            bool complete = true;
            for_each([&](KvObj* object) {
                if (complete) complete = fresh->install(object, now, bytes);
            });
            if (!complete) return false;
            obj_bytes_ += bytes;
            object_idle_slot()->store(fresh.release(), std::memory_order_release);
        } else {
            auto* retired = object_idle_slot()->exchange(nullptr, std::memory_order_acq_rel);
            const size_t bytes = retired->allocated_bytes();
            if (read_local_enabled_)
                read_local_store_state_required().retire_sink.retire(this, retired, bytes,
                                                                     reclaim_object_idle);
            else
                reclaim_object_idle(this, retired, bytes);
        }
        return true;
    }
    // Returns the idle clock's allocation result. The limit and policy always apply: enabling
    // never aborts and never refuses; a failed clock leaves OBJECT IDLETIME at 0 for this store.
    bool configure_maxmemory(bool enabled, uint64_t shard_limit, MaxmemoryPolicy policy,
                             uint32_t samples) {
        const bool clock = configure_object_idle(enabled);
        maxmemory_enabled_ = enabled;
        maxmemory_limit_ = shard_limit;
        maxmemory_policy_ = policy;
        maxmemory_samples_ = samples == 0 ? 1 : (samples > 64 ? 64 : samples);
        return clock;
    }

    // An atomic script can roll back every declared key, but an eviction victim is deliberately
    // outside that declaration. Keep maxmemory admission enabled while making it non-evicting for
    // the duration of the one owner task, so a failed script cannot leave an unrelated victim
    // behind. The owner restores the live policy before it takes another task.
    MaxmemoryPolicy script_suspend_eviction() {
        const MaxmemoryPolicy previous = maxmemory_policy_;
        if (maxmemory_enabled_) maxmemory_policy_ = MaxmemoryPolicy::NoEviction;
        return previous;
    }
    void script_restore_eviction(MaxmemoryPolicy policy) { maxmemory_policy_ = policy; }
    // Owner-task scope only: keep accounting/eviction metadata enabled while an admitted
    // FUNCTION may grow beyond the configured cap. No new state or per-operation branch.
    uint64_t script_exchange_memory_limit(uint64_t limit) {
        const uint64_t previous = maxmemory_limit_;
        maxmemory_limit_ = limit;
        return previous;
    }

    enum class TtlResult : uint8_t { Missing, NoChange, Updated, Oom, MaxmemoryOom };

    TtlResult set_expire(uint64_t h, Slice key, int64_t expire_at_ms) {
        if (__builtin_expect(read_local_enabled_, false))
            return set_expire_read_local(h, key, expire_at_ms);
        KvObj* old = find(h, key);
        if (!old) return TtlResult::Missing;
        if (old->has_ttl_slot()) {
            if constexpr (!kSingleDatabase) storesize_deadline(old, expire_at_ms);
            old->set_expire_at_ms(expire_at_ms);
            (void)track_expire(h, old);
            return TtlResult::Updated;
        }
        return rewrite_expire(h, old, expire_at_ms);
    }

    TtlResult set_expire_notify(uint64_t h, Slice key, int64_t expire_at_ms, FlatNotifySink* sink) {
        if (__builtin_expect(read_local_enabled_, false))
            return set_expire_notify_read_local(h, key, expire_at_ms, sink);
        KvObj* old = find_notify(h, key, sink);
        if (!old) return TtlResult::Missing;
        if (old->has_ttl_slot()) {
            if constexpr (!kSingleDatabase) storesize_deadline(old, expire_at_ms);
            old->set_expire_at_ms(expire_at_ms);
            (void)track_expire(h, old);
            return TtlResult::Updated;
        }
        return rewrite_expire(h, old, expire_at_ms);
    }

    TtlResult persist(uint64_t h, Slice key) {
        KvObj* old = find(h, key);
        if (!old) return TtlResult::Missing;
        if (deadline(h, old) < 0) return TtlResult::NoChange;
        if (__builtin_expect(read_local_enabled_, false))
            return rewrite_expire_read_local(h, old, kNoTtlDeadline);
        if constexpr (!kSingleDatabase) storesize_deadline(old, kNoTtlDeadline);
        old->set_expire_at_ms(kNoTtlDeadline);
        untrack_expire(h);
        return TtlResult::Updated;
    }

    TtlResult persist_notify(uint64_t h, Slice key, FlatNotifySink* sink) {
        KvObj* old = find_notify(h, key, sink);
        if (!old) return TtlResult::Missing;
        if (deadline(h, old) < 0) return TtlResult::NoChange;
        if (__builtin_expect(read_local_enabled_, false))
            return rewrite_expire_read_local(h, old, kNoTtlDeadline);
        if constexpr (!kSingleDatabase) storesize_deadline(old, kNoTtlDeadline);
        old->set_expire_at_ms(kNoTtlDeadline);
        untrack_expire(h);
        return TtlResult::Updated;
    }

    // Returns a WORK count, while `budget` bounds examined expire-index slots. The count is the
    // number of expired keys removed, plus resize/retirement-capacity debt and sidecar work: half the
    // index is then parked in the old table, and an owner that treats a barren sampling pass as
    // "nothing to do" parks with those deadlines unsampled until the next command wakes it.
    // Finding an object from its full hash follows only that hash's FlatStore probe run; it never
    // scans the table or keyspace.
    uint32_t active_expire(uint32_t budget) {
        // Expiry after the cut is a post-cut deletion.  Leaving the object physically present lets
        // traversal serialize its absolute deadline; find() still reports it logically absent.
        if (snapshot_active_) return 0;
        const bool resizing = rehashing();
        if (resizing) rehash_step();
        // Count structural work even without TTL keys, including the final step. Idle owners
        // must revisit an unfinished resize instead of parking until another command arrives.
        uint32_t removed = resizing ? 1 : 0;
        // Pause expiry, not the resize progress needed by already admitted work.
        if (client_pause_expiry_held()) return removed;
        expires_.sample(budget, [&](uint64_t h) {
            KvObj* o = find_hash_in(0, h);
            if (!o && rehashing()) o = find_hash_in(1, h);
            if (!o || !o->has_ttl_slot()) {
                untrack_expire(h);  // stale tracker after a replacement or collision
                return;
            }
            if (atomic_has_record(h, o->key())) return;  // promotion resolves the winning TTL
            const int64_t at = deadline(h, o);
            if (at < 0) {
                untrack_expire(h);
                return;
            }
            if (at >= cached_now_ms_) return;  // Redis active expiry reaps only once now > at
            if (!read_retirement_available()) {
                removed++;
                return;
            }
            const Slice key = o->key();
            notify_flat_store_emit(this, NOTIFY_EXPIRED, NotifyEventId::Expired, key);
            (void)aof_.record_delete(key);
            if (erase_in(0, h, key) || (rehashing() && erase_in(1, h, key))) {
                removed++;
                note_active_expire_reap(at);
                if (expired_counter_) (*expired_counter_)++;
            }
        });
        if (__builtin_expect(field_expires_.size() != 0, false))
            removed += active_expire_fields(budget);
        if (__builtin_expect(expires_.migrating() || field_expires_.migrating(), false)) removed++;
        return removed;
    }

    // Hash-field deadlines ride the SAME attention mechanism as key deadlines: a per-shard index of
    // key hashes, a persistent cursor, and a slot budget that counts empty slots so a pass can never
    // degenerate into a keyspace walk. Reaping is the ex thread touching its own shard, so it is
    // legal here for exactly the reason active_expire() is.
    uint32_t active_expire_fields(uint32_t budget) {
        if (snapshot_active_) return 0;
        uint32_t removed = 0;
        field_expires_.sample(budget, [&](uint64_t h) {
            KvObj* o = find_any_hash_in(0, h);
            if (!o && rehashing()) o = find_any_hash_in(1, h);
            if (!o || static_cast<Type>(o->type) != Type::Hash ||
                static_cast<Enc>(o->enc) == Enc::Compact ||
                !static_cast<const HashVal*>(o->external_ptr())->ttls) {
                // Key gone, replaced, re-typed, or every field TTL removed. Self-healing here is
                // what lets registration stay a cheap unconditional insert on the write path.
                field_expires_.erase(h);
                refresh_field_ttl_gate();
                return;
            }
            if (atomic_has_record(h, o->key())) return;
            if (!read_retirement_available()) {
                removed++;
                return;
            }
            uint32_t reaped = 0;
            const size_t before = kvobj_size(o);
            const bool empty = hash_ttl_active_reap(*this, o, cached_now_ms_, reaped);
            if (!reaped && !empty) return;
            const Slice key = o->key();
            notify_flat_store_emit(this, NOTIFY_HASH, NotifyEventId::Hexpired, key);
            field_expired_ += reaped;
            // Reaping already shrank the object, including when the last field disappeared.
            // erase_in() will subtract only the remaining footprint.
            note_object_size_change(before, kvobj_size(o));
            if (!empty) {
                (void)aof_.record_post_image_buffered(*this, h, key);
                removed += reaped;
                return;
            }
            (void)aof_.record_delete(key);
            notify_flat_store_emit(this, NOTIFY_GENERIC, NotifyEventId::Del, key);
            if (erase_in(0, h, key) || (rehashing() && erase_in(1, h, key))) removed += reaped;
            field_expires_.erase(h);
            refresh_field_ttl_gate();
        });
        return removed;
    }
    uint64_t field_expired() const { return field_expired_; }

    // Pre-execution budget gate for growth commands (CmdFlags::DenyOom), redis-style: over-budget
    // shards evict (policy permitting) until under, else the command is refused. The mutation is
    // NOT sized -- like redis, one op may overshoot and the next gated op pays it back. Suspended
    // during capture for the same reason admission is (victims are not pre-imaged).
    bool budget_admit(Slice protected_key) {
        if (!__builtin_expect(maxmemory_enabled_, false)) return true;
        return budget_admit_over_limit(protected_key);
    }
    // Stream-retirement context belongs to the armed eviction path. Keep its
    // register saves behind the maxmemory gate for ordinary writes.
    [[gnu::noinline, gnu::cold]] bool budget_admit_over_limit(Slice protected_key) {
        if (snapshot_active_) return true;
        // NOT make_room_for: projected_bytes subtracts the protected key's own size (replacement
        // semantics), so the very key being grown always "fits". The gate asks the raw question:
        // is the shard over budget NOW; evict others, never the op's key; else refuse.
        if (accounted_bytes() <= maxmemory_limit_) return true;
        if (maxmemory_policy_ == MaxmemoryPolicy::NoEviction) return refuse_over_budget();
        uint32_t budget = kEvictionsPerOp;
        while (budget-- && accounted_bytes() > maxmemory_limit_) {
            KvObj* victim = choose_victim(protected_key);
            if (!victim) return refuse_over_budget();
            const uint64_t hash = hash_key(victim->key());
            const Slice key = victim->key();
            (void)aof_.record_delete(key);
            const uint32_t before = size();
            const bool live = erase(hash, key);
            if (size() == before) return refuse_over_budget();
            if (live && evicted_counter_) (*evicted_counter_)++;
        }
        if (accounted_bytes() <= maxmemory_limit_) return true;
        return refuse_over_budget();
    }

    // Cold owner maintenance, separate from per-command admission.
    uint32_t evict_over_limit();

    // Owner insertion/replacement; takes ownership of o on Inserted and retires displaced
    // objects. The caller supplies matching hash/key and any required snapshot pre-image.
    // Armed calls delegate to release publication/QSBR. Failed leaves o with the caller;
    // MaxmemoryOom reports admission refusal, which may already have evicted other keys.
    InsertResult insert(uint64_t h, KvObj* o) {
        if (__builtin_expect(read_local_enabled_, false)) return insert_read_local(h, o);
        const bool capturing = rehashing() && snapshot_active_;
        if (rehashing()) {
            if (!capturing) rehash_step();
        } else {
            if (!maybe_start_grow()) return InsertResult::Failed;
        }
        // A full prepared table refuses new keys instead of resizing the table reserved for
        // the snapshot cut. Replacements preserve its cardinality.
        if (static_cast<uint64_t>(live_[0]) + tombs_[0] + 1 >= cap_[0] && snapshot_prepared_ &&
            !find_in(0, h, o->key()))
            return InsertResult::Failed;
        if (capturing) {
            const bool exists = find_in(0, h, o->key()) || find_in(1, h, o->key());
            // The fresh table is deliberately overprovisioned at the cut.  Refuse only genuinely
            // new keys once the complete logical set would no longer fit; replacements preserve
            // cardinality.  This is an ordinary insert failure, never snapshot corruption.
            // Count current-table tombstones as promised destination slots too.  Otherwise a
            // churn-heavy capture could leave enough logical capacity but no EMPTY terminating
            // slot, and the post-capture merge would be unable to place a frozen pointer.
            if (!exists && static_cast<uint64_t>(live_[0]) + tombs_[0] + live_[1] + 1 >= cap_[0])
                return InsertResult::Failed;
        }
        // Disabled maxmemory pays one predicted branch and does no metadata write or accounting
        // work. Enabled admission is bounded to kEvictionsPerOp victim deletions.  Admission is
        // SUSPENDED while a capture is active: make_room_for deletes sampled victims, and the
        // snapshot write-gate pre-images only the incoming command's key — an evicted, unvisited
        // frozen victim would vanish from the dump.
        if (__builtin_expect(maxmemory_enabled_, false)) {
            if (!snapshot_active_ &&
                !make_room_for(o->key(), kvobj_size(o) + object_idle_allocation_bytes(o)))
                return InsertResult::MaxmemoryOom;
            if (!object_idle_install(h, o)) return InsertResult::Failed;
            if (!snapshot_active_) {
                if (o->eviction_meta() == 0) initialize_meta(o);
            }
        }
        // Evict any copy still in the old table FIRST, or it outlives a later delete of the new one
        // and the key resurrects — see the header.
        if (rehashing()) {
            bool expired = false;
            if (erase_in(1, h, o->key(), &expired, o) && expired && expired_counter_)
                (*expired_counter_)++;
        }
        return insert_into(0, h, o, true) ? InsertResult::Inserted : InsertResult::Failed;
    }

    InsertResult insert_notify(uint64_t h, KvObj* o, FlatNotifySink* sink) {
        KvObj* candidate = find_in(0, h, o->key());
        if (!candidate && rehashing()) candidate = find_in(1, h, o->key());
        const bool expired = candidate && deadline_elapsed(h, candidate, cached_now_ms_);
        const bool report_new = !candidate || expired;
        if (expired) notify_emit(sink, NOTIFY_EXPIRED, NotifyEventId::Expired, candidate->key());
        const InsertResult result = insert(h, o);
        if (result == InsertResult::Inserted && report_new)
            notify_emit(sink, NOTIFY_NEW, NotifyEventId::New, o->key());
        return result;
    }

    bool erase(uint64_t h, Slice key) {
        if (__builtin_expect(read_local_enabled_, false)) return erase_read_local(h, key);
        if (rehashing() && !snapshot_active_) rehash_step();
        bool expired = false;
        if (erase_in(0, h, key, &expired)) {
            maybe_start_shrink();
            if (expired && expired_counter_) (*expired_counter_)++;
            return !expired;
        }
        if (rehashing() && erase_in(1, h, key, &expired)) {
            maybe_start_shrink();
            if (expired && expired_counter_) (*expired_counter_)++;
            return !expired;
        }
        return false;
    }

    // Redis dbDelete removes a resident regardless of its deadline. STORE and
    // FLUSH use this owner-only path: no expiry event, AOF DEL, or expiry count.
    // erase_in retains the ordinary snapshot/QSBR retirement rules.
    bool erase_resident(uint64_t h, Slice key) {
        if (erase_in(0, h, key) || (rehashing() && erase_in(1, h, key))) {
            maybe_start_shrink();
            return true;
        }
        return false;
    }

    bool erase_notify(uint64_t h, Slice key, FlatNotifySink* sink,
                      EraseEvent event = EraseEvent::Del) {
        KvObj* candidate = find_in(0, h, key);
        if (!candidate && rehashing()) candidate = find_in(1, h, key);
        if (candidate) {
            const bool expired = deadline_elapsed(h, candidate, cached_now_ms_);
            if (expired)
                notify_emit(sink, NOTIFY_EXPIRED, NotifyEventId::Expired, candidate->key());
            else if (event == EraseEvent::Del)
                notify_emit(sink, NOTIFY_GENERIC, NotifyEventId::Del, candidate->key());
            else if (event == EraseEvent::Evicted)
                notify_emit(sink, NOTIFY_EVICTED, NotifyEventId::Evicted, candidate->key());
        }
        return erase(h, key);
    }

    template <typename Fn>
    void for_each(Fn&& fn) const {
        for (int t = 0; t < 2; t++)
            if (tab_[t])
                for (uint32_t i = 0; i < cap_[t]; i++)
                    if (KvObj* o = ptr_of(tab_[t][i])) fn(o);
    }

    // FLUSH is intentionally proportional to the table capacity it discards. Borrowed string
    // values move to the borrow retirement list, so a send already in flight remains valid.
    void clear() {
        if constexpr (kSingleDatabase) {
            // A new volatile population must never inherit the flushed sample.
            StoreSizeState* state;
            std::memcpy(&state, reader_owner_gap_ + 4, sizeof(state));
            state->sample_cursor = 0;
            state->avg_deadline.store(0, std::memory_order_relaxed);
        } else
            storesize_clear();
        if (__builtin_expect(read_local_enabled_, false)) {
            clear_read_local();
            return;
        }
        // Allocate the small replacement (clear_capacity()) before touching either live table. If
        // that cold allocation fails, retain and zero table 0 after retiring its objects; FLUSH
        // still has a valid empty table and never exposes a half-demoted state.
        uint64_t* fresh = allocate_table(clear_capacity());
        expires_.clear();
        for (int t = 0; t < 2; t++) {
            if (!tab_[t]) continue;
            for (uint32_t i = 0; i < cap_[t]; i++)
                if (KvObj* o = ptr_of(tab_[t][i])) retire_obj(o);
            if (t == 0 && !fresh) {
                std::memset(tab_[0], 0,
                            static_cast<size_t>(static_cast<uint64_t>(cap_[0]) * sizeof(uint64_t)));
                live_[0] = tombs_[0] = 0;
                continue;
            }
            std::free(tab_[t]);
            tab_[t] = nullptr;
            cap_[t] = mask_[t] = live_[t] = tombs_[t] = 0;
        }
        field_expires_.clear();
        field_ttl_gate_ = 0;
        field_ttl_index_incomplete_ = false;
        rehash_pos_ = 0;
        if (fresh) install_empty_table(0, fresh, clear_capacity());
    }

    // FLUSH after its scatter gate has prepared every frozen pre-image.  Preserve both table
    // allocations and their slot numbering until the capture walker releases its cursor; turn all
    // live entries into ordinary tombstones instead of freeing the tables as clear() does.
    void clear_during_snapshot() {
        if constexpr (kSingleDatabase) {
            // Capture retains table slots, but the monitoring population is gone.
            StoreSizeState* state;
            std::memcpy(&state, reader_owner_gap_ + 4, sizeof(state));
            state->sample_cursor = 0;
            state->avg_deadline.store(0, std::memory_order_relaxed);
        } else
            storesize_clear();
        if (__builtin_expect(read_local_enabled_, false)) {
            clear_during_snapshot_read_local();
            return;
        }
        expires_.clear();
        for (int t = 0; t < 2; t++) {
            if (!tab_[t]) continue;
            for (uint32_t i = 0; i < cap_[t]; i++) {
                if (KvObj* object = ptr_of(tab_[t][i])) {
                    retire_obj(object);
                    tab_[t][i] = kTombBit;
                    live_[t]--;
                    tombs_[t]++;
                }
            }
        }
        field_expires_.clear();
        field_ttl_gate_ = 0;
        field_ttl_index_incomplete_ = false;
    }

#include "flatstore_random.inc"

    // The cursor is a bit-reversed HOME index (see scan_cursor_next above), not a physical slot and
    // not a table selector -- there is nothing left in it that a resize can invalidate. One step
    // covers a whole logical home bucket, which under linear probing is the run of non-EMPTY slots
    // starting at that home, so a key's probe displacement no longer decides whether it is seen.
    // While a rehash is draining, the step covers the smaller table's home AND every home in the
    // larger table that expands from it before the cursor moves, exactly as Redis does.
    // COUNT keeps its Redis meaning -- HOMES visited per call, so a call still yields about COUNT
    // entries at our load factor. A second, looser budget of 10*COUNT examined SLOTS limits
    // additional home visits when
    // tombstones stretch the probe runs; it is the same pair of budgets SSCAN documents.
    // `expire_on_visit` distinguishes the two legitimate walkers. SCAN/KEYS keep redis semantics:
    // a visited dead key is logically expired on the spot (event, AOF delete, erase). ACCOUNTING
    // walks (the LB bucket-byte census) must pass false: they run from the executor loop at census
    // cadence, not inside any logical operation. Expiring there could physically delete a
    // key between MGET fan-out fragments, outside their pinned cut, and tear the logical read.
    template <typename Fn>
    uint64_t scan(uint64_t cursor, uint32_t count, Fn&& fn, bool expire_on_visit = true) {
        if (!tab_[0]) return 0;
        const uint64_t slot_budget = static_cast<uint64_t>(count) * 10;
        uint32_t homes = 0;
        uint64_t slots = 0;
        do {
            if (!rehashing()) {
                slots +=
                    scan_home(0, static_cast<uint32_t>(cursor) & mask_[0], fn, expire_on_visit);
                homes++;
                cursor = scan_cursor_next(cursor, mask_[0]);
            } else if (mask_[0] == mask_[1]) {
                // Same-size rebuild (tombstone reclaim): identical homes, so one visit each.
                const uint32_t home = static_cast<uint32_t>(cursor) & mask_[0];
                slots += scan_home(0, home, fn, expire_on_visit);  // separate statements: both
                slots += scan_home(1, home, fn, expire_on_visit);  // emit, order must be defined
                homes += 2;
                cursor = scan_cursor_next(cursor, mask_[0]);
            } else {
                const int small = cap_[0] < cap_[1] ? 0 : 1;  // grow puts the old table in 1,
                const int large = small ^ 1;                  // shrink puts it in 0
                const uint64_t small_mask = mask_[small];
                const uint64_t large_mask = mask_[large];
                slots += scan_home(small, static_cast<uint32_t>(cursor & small_mask), fn,
                                   expire_on_visit);
                homes++;
                do {
                    slots += scan_home(large, static_cast<uint32_t>(cursor & large_mask), fn,
                                       expire_on_visit);
                    homes++;
                    cursor = scan_cursor_next(cursor, large_mask);
                } while (cursor & (small_mask ^ large_mask));
            }
        } while (cursor && homes < count && slots < slot_budget);
        return cursor;
    }

    // Warm the slots this key will probe, for a whole batch before any of it executes, so the DRAM
    // round trips overlap. A plain prefetch pass, not an AMAC-style interleaved state machine.
    void prefetch(uint64_t h) const {
        if (tab_[0]) __builtin_prefetch(&tab_[0][slot_start(0, h)], 0, 3);
        if (tab_[1]) __builtin_prefetch(&tab_[1][slot_start(1, h)], 0, 3);
    }

    // One hash for the whole server: the router takes its bucket from the low bits and FlatStore
    // mixes for its index, so both must agree and it lives here. Word-at-a-time, because FNV-1a
    // costs one DEPENDENT multiply per byte and a 20-character key is then a 20-long chain.
    static uint64_t hash_key(Slice k) {
        if (g_hash_kind == HashKind::SipHash12)
            return siphash12(k.p, k.n) ^ (uint64_t{k.ns} * 0x9e3779b97f4a7c15ULL);
        return hash_key_mix(k);
    }

    static uint64_t hash_key_mix(Slice k) {
        const uint8_t* p = reinterpret_cast<const uint8_t*>(k.p);
        uint32_t n = k.n;
        uint64_t h = (0x9e3779b97f4a7c15ULL ^ (k.identity() * 0xff51afd7ed558ccdULL)) ^ g_hash_seed;
        auto rd8 = [](const uint8_t* q) {
            uint64_t v;
            std::memcpy(&v, q, 8);
            return v;
        };
        auto rd4 = [](const uint8_t* q) {
            uint32_t v;
            std::memcpy(&v, q, 4);
            return v;
        };
        while (n >= 8) {
            h = mix64(h ^ rd8(p));
            p += 8;
            n -= 8;
        }
        if (n >= 4) {
            h = mix64(h ^ ((static_cast<uint64_t>(rd4(p)) << 32) | rd4(p + n - 4)));
        } else if (n) {
            uint64_t t = p[0];
            t = (t << 16) | (static_cast<uint64_t>(p[n >> 1]) << 8) | p[n - 1];
            h = mix64(h ^ t);
        }
        return mix64(h);
    }

private:
    [[gnu::noinline, gnu::cold]] void destroy_storesize();
    StoreSizeState* storesize_state() const;
    void publish_field_ttl_attention() const noexcept;
    void storesize_replace(const KvObj* before, const KvObj* after);
    void storesize_deadline(const KvObj* object, int64_t deadline);
    void storesize_clear();
    void refresh_field_ttl_gate() {
        // Once registration was lost, the count is no longer exact until FLUSH. Preserve a
        // positive gate without reporting an artificial UINT32_MAX population through INFO.
        field_ttl_gate_ = std::max(field_expires_.size(), uint32_t{field_ttl_index_incomplete_});
    }
    static constexpr uint32_t kSnapshotRecordTag = 0x44434552;  // "RECD", little endian
    static constexpr uint32_t kSnapshotRecordHeader = 32;

    // Key-expiry tracker registration. The index is hash-only: an entry states that this hash may
    // carry a deadline, so registration is driven by LOGICAL volatility and a retained-but-
    // persisted slot must not leave one behind.
    bool track_expire(uint64_t hash, KvObj* object) {
        if (!object) return true;
        const int64_t at = object->expire_at_ms();
        if (at >= 0) {
            if (expires_.insert(hash, at)) return true;
            return false;
        }
        // An empty index needs no erase or call into ExpireIndex. Otherwise even a slotless
        // replacement must erase the hash: SET k v EX 10 followed by SET k v clears TTL.
        // INFO keyspace expires is expires_.size(), and tests/expireindex.py checks exact counts.
        // active_expire tolerates stale hash registrations when reaping, but those stale entries
        // would over-report the count until sampled. A physical TTL slot alone is not volatility.
        if (expires_.size() == 0) return true;
        expires_.erase(hash);
        return true;
    }

    void untrack_expire(uint64_t hash) { expires_.erase(hash); }

    // Owner-local resumable serializer state. value borrows the object until the write gate
    // or traversal finishes this record; header bytes and offsets belong to the cursor.
    // Hook/allocation errors set snapshot_failed_; budget or ready-chunk pressure pauses work.
    struct SnapshotRecordState {
        bool active = false;
        bool preimage = false;
        uint32_t slot = 0;
        uint8_t header[kSnapshotRecordHeader] = {};
        uint32_t header_offset = 0;
        uint32_t key_offset = 0;
        SnapshotSaveCursor value;
        SnapshotTypeHooks hooks{};
    };

    std::unique_ptr<SnapshotChunk> make_snapshot_chunk(uint32_t flags) {
        try {
            auto chunk = std::make_unique<SnapshotChunk>();
            chunk->sid = snapshot_shard_id_;
            chunk->sequence = snapshot_sequence_++;
            chunk->flags = flags;
            chunk->bytes.reserve(kSnapshotChunkBytes);
            return chunk;
        } catch (const std::bad_alloc&) {
            snapshot_failed_ = true;
            return nullptr;
        }
    }

    void snapshot_seal(uint32_t flags) {
        if (!snapshot_build_ || snapshot_ready_) return;
        snapshot_build_->flags |= flags;
        snapshot_ready_ = std::move(snapshot_build_);
    }

    uint32_t snapshot_emit(const uint8_t* source, uint32_t length, uint32_t& budget) {
        uint32_t emitted = 0;
        while (length && budget && !snapshot_ready_ && !snapshot_failed_) {
            if (!snapshot_build_) snapshot_build_ = make_snapshot_chunk(0);
            if (!snapshot_build_) break;
            const uint32_t room =
                kSnapshotChunkBytes - static_cast<uint32_t>(snapshot_build_->bytes.size());
            const uint32_t take = std::min({length, budget, room});
            try {
                snapshot_build_->bytes.insert(snapshot_build_->bytes.end(), source, source + take);
            } catch (const std::bad_alloc&) {
                snapshot_failed_ = true;
                break;
            }
            source += take;
            length -= take;
            budget -= take;
            emitted += take;
            if (snapshot_build_->bytes.size() == kSnapshotChunkBytes) snapshot_seal(0);
        }
        return emitted;
    }

    bool snapshot_start_record(const KvObj* object, uint32_t slot, bool preimage) {
        SnapshotRecordState state;
        state.active = true;
        state.preimage = preimage;
        state.slot = slot;
        state.hooks = snapshot_type_hooks(static_cast<Type>(object->type));
        uint8_t encoding = 0;
        const SnapshotHookStatus status = state.hooks.begin_save(*object, state.value, encoding);
        if (status != SnapshotHookStatus::Ok) {
            snapshot_failed_ = true;
            return false;
        }
        snapshot_put_u32(state.header + 0, kSnapshotRecordTag);
        state.header[4] = object->type;
        state.header[5] = encoding;
        state.header[6] = object->key_namespace();
        state.header[7] = 0;
        snapshot_put_u32(state.header + 8, object->klen());
        snapshot_put_u32(state.header + 12, 0);
        snapshot_put_u64(state.header + 16, state.value.total);
        snapshot_put_u64(state.header + 24, static_cast<uint64_t>(object->expire_at_ms()));
        snapshot_record_ = state;
        return true;
    }

    // Owner-side continuation for snapshot_progress: emit header, key and value into the
    // owned chunk without file I/O. The active record must keep its borrowed object stable.
    // Budget exhaustion or a ready chunk pauses at saved offsets; invalid state, hook failure
    // or allocation failure sets snapshot_failed_. Completion marks the pre-image or advances
    // the cursor. Armed stores delegate to the release-store variant below.
    void snapshot_progress_record(uint32_t& budget) {
        if (__builtin_expect(read_local_enabled_, false)) {
            snapshot_progress_record_read_local(budget);
            return;
        }
        SnapshotRecordState& state = snapshot_record_;
        const KvObj* object = state.value.object;
        if (!state.active || !object) {
            snapshot_failed_ = true;
            return;
        }

        if (state.header_offset < kSnapshotRecordHeader) {
            const uint32_t emitted_bytes =
                snapshot_emit(state.header + state.header_offset,
                              kSnapshotRecordHeader - state.header_offset, budget);
            state.header_offset += emitted_bytes;
            if (state.header_offset != kSnapshotRecordHeader || snapshot_ready_) return;
        }
        if (state.key_offset < object->klen()) {
            const uint32_t emitted_bytes = snapshot_emit(
                reinterpret_cast<const uint8_t*>(object->key_ptr()) + state.key_offset,
                object->klen() - state.key_offset, budget);
            state.key_offset += emitted_bytes;
            if (state.key_offset != object->klen() || snapshot_ready_) return;
        }
        while (state.value.offset < state.value.total && budget && !snapshot_ready_) {
            if (!snapshot_build_) snapshot_build_ = make_snapshot_chunk(0);
            if (!snapshot_build_) return;
            const size_t room = kSnapshotChunkBytes - snapshot_build_->bytes.size();
            const size_t capacity = std::min<size_t>(room, budget);
            const size_t old_size = snapshot_build_->bytes.size();
            try {
                snapshot_build_->bytes.resize(old_size + capacity);
            } catch (const std::bad_alloc&) {
                snapshot_failed_ = true;
                return;
            }
            size_t written = 0;
            const SnapshotHookStatus status = state.hooks.read_save(
                state.value, snapshot_build_->bytes.data() + old_size, capacity, written);
            if (status != SnapshotHookStatus::Ok || written > capacity ||
                (written == 0 && state.value.offset < state.value.total)) {
                snapshot_build_->bytes.resize(old_size);
                snapshot_failed_ = true;
                return;
            }
            snapshot_build_->bytes.resize(old_size + written);
            budget -= static_cast<uint32_t>(written);
            if (snapshot_build_->bytes.size() == kSnapshotChunkBytes) snapshot_seal(0);
        }
        if (state.value.offset != state.value.total || snapshot_ready_) return;

        const bool preimage = state.preimage;
        const uint32_t slot = state.slot;
        snapshot_record_ = {};
        if (preimage)
            tab_[1][slot] |= kTombBit;
        else
            snapshot_pos_++;
    }

    void snapshot_finish_stream() {
        if (snapshot_finished_ || snapshot_ready_ || snapshot_record_.active) return;
        if (!snapshot_build_) snapshot_build_ = make_snapshot_chunk(0);
        if (!snapshot_build_) return;
        snapshot_seal(SnapshotFrameEnd);
        snapshot_finished_ = true;
    }

    // Owner-local wire borrow: ptr identifies bytes sent by IO; refs counts outstanding
    // releases. retired takes ownership after removal until unborrow drops the last ref.
    // The owner processes IO releases; this record itself provides no atomic publication.
    struct Borrow {
        const char* ptr;
        uint32_t refs;
        KvObj* retired;
    };

    // borrows_ owns the reference registry; borrow, unborrow, overwrite checks and retirement
    // find entries by pointer identity. Repeated linear scans would make K registrations
    // quadratic and each lookup proportional to outstanding borrows.
    // borrow_idx_ optionally maps pointers to vector slots. borrows_ remains authoritative;
    // an unavailable/full index falls back to scanning. Below kBorrowIndexMin, no index is
    // built. Rebuild failure keeps a valid old index until insertion either succeeds or drops it.
    static constexpr uint32_t kNoBorrow = 0xffffffffu;  // also the empty-slot sentinel
    static constexpr uint32_t kBorrowTomb = 0xfffffffeu;
    static constexpr uint32_t kBorrowIndexMin = 32;

    static size_t borrow_hash(const char* ptr) {
        return static_cast<size_t>(mix64(static_cast<uint64_t>(reinterpret_cast<uintptr_t>(ptr))));
    }

    uint32_t borrow_find(const char* ptr) const {
        if (borrow_idx_.empty()) {
            for (uint32_t i = 0; i < borrows_.size(); i++)
                if (borrows_[i].ptr == ptr) return i;
            return kNoBorrow;
        }
        const size_t mask = borrow_idx_.size() - 1;
        size_t pos = borrow_hash(ptr) & mask;
        for (size_t probes = 0; probes <= mask; probes++) {
            const uint32_t v = borrow_idx_[pos];
            if (v == kNoBorrow) return kNoBorrow;
            if (v != kBorrowTomb && borrows_[v].ptr == ptr) return v;
            pos = (pos + 1) & mask;
        }
        return kNoBorrow;
    }

    void borrow_index_release() {
        std::vector<uint32_t>().swap(borrow_idx_);
        borrow_tombs_ = 0;
    }

    void borrow_index_put(const char* ptr, uint32_t at) {
        if (borrow_idx_.empty()) return;
        const size_t cap = borrow_idx_.size();
        const size_t mask = cap - 1;
        size_t pos = borrow_hash(ptr) & mask;
        size_t first_tomb = cap;
        for (size_t probes = 0; probes < cap; probes++) {
            const uint32_t v = borrow_idx_[pos];
            if (v == kNoBorrow) {
                if (first_tomb != cap) {
                    pos = first_tomb;
                    borrow_tombs_--;
                }
                borrow_idx_[pos] = at;
                return;
            }
            if (v == kBorrowTomb) {
                if (first_tomb == cap) first_tomb = pos;
            } else if (borrows_[v].ptr == ptr) {
                borrow_idx_[pos] = at;
                return;
            }
            pos = (pos + 1) & mask;
        }
        borrow_index_release();  // full: cannot happen at the 70% rebuild trigger
    }

    void borrow_index_dropped(const char* ptr) {
        if (borrow_idx_.empty()) return;
        const size_t mask = borrow_idx_.size() - 1;
        size_t pos = borrow_hash(ptr) & mask;
        for (size_t probes = 0; probes <= mask; probes++) {
            const uint32_t v = borrow_idx_[pos];
            if (v == kNoBorrow) return;
            if (v != kBorrowTomb && borrows_[v].ptr == ptr) {
                borrow_idx_[pos] = kBorrowTomb;
                borrow_tombs_++;
                return;
            }
            pos = (pos + 1) & mask;
        }
    }

    bool borrow_index_rebuild() {
        uint64_t cap = 64;
        const uint64_t occupancy = static_cast<uint64_t>(borrows_.size());
        if (occupancy > UINT64_MAX / uint64_t{200}) return false;
        const uint64_t wanted = occupancy * uint64_t{200};
        for (;;) {  // land near 35% loaded
            if (cap > UINT64_MAX / uint64_t{70}) return false;
            if (cap * uint64_t{70} >= wanted) break;
            if (cap > static_cast<uint64_t>(borrow_idx_.max_size()) / 2) {
                return false;
            }
            cap *= uint64_t{2};
        }
        std::vector<uint32_t> fresh;
        try {
            fresh.assign(static_cast<size_t>(cap), kNoBorrow);
        } catch (const std::bad_alloc&) {
            return false;
        }
        const size_t mask = fresh.size() - 1;
        for (uint32_t i = 0; i < borrows_.size(); i++) {
            size_t pos = borrow_hash(borrows_[i].ptr) & mask;
            while (fresh[pos] != kNoBorrow) pos = (pos + 1) & mask;
            fresh[pos] = i;
        }
        borrow_idx_.swap(fresh);
        borrow_tombs_ = 0;
        return true;
    }

    void borrow_index_added(const char* ptr, uint32_t at) {
        if (borrow_idx_.empty()) {
            if (borrows_.size() < kBorrowIndexMin) return;  // short scan beats a hash
            (void)borrow_index_rebuild();                   // allocation failure stays scan mode
            return;
        }
        if ((static_cast<uint64_t>(borrows_.size()) + borrow_tombs_) * 100 >=
            static_cast<uint64_t>(borrow_idx_.size()) * 70) {
            if (borrow_index_rebuild()) return;
            // The old index remains valid on allocation failure and still has the trigger's 30%
            // headroom. Add this borrow there; borrow_index_put() falls back to scan mode if a
            // pathological tombstone layout nevertheless leaves no usable slot.
        }
        borrow_index_put(ptr, at);
    }

    static uint32_t round_pow2(uint32_t v) {
        uint32_t p = kMinCap;
        while (p < v) {
            const uint64_t next = static_cast<uint64_t>(p) * 2;
            if (next > UINT32_MAX) return 0;
            p = static_cast<uint32_t>(next);
        }
        return p;
    }
    static uint16_t tag_of(uint64_t h) { return static_cast<uint16_t>((h >> 49) & 0x7fff); }
    static uint16_t tag_of_word(uint64_t w) { return static_cast<uint16_t>((w >> 49) & 0x7fff); }
    static KvObj* ptr_of(uint64_t w) { return reinterpret_cast<KvObj*>(w & kPtrMask); }
    static uint64_t /* TOMO_TOOL_BIND make_word */ make_word(uint16_t tag, KvObj* o) {
        const uint64_t pointer = reinterpret_cast<uint64_t>(o);
        TOMO_ASSERT((pointer & ~kPtrMask) == 0 &&
                    "KvObj pointer exceeds FlatStore's 48-bit encoding");
        return (static_cast<uint64_t>(tag) << 49) | pointer;
    }
    uint32_t slot_start(int t, uint64_t h) const {
        return static_cast<uint32_t>(mix64(h)) & mask_[t];
    }

    KvObj* find_without_touch(uint64_t h, Slice key) {
        // Like find(), this lookup never moves slots or retires a rehash table. This also preserves
        // the positional frozen image in tab_[1] during snapshot capture.
        if (KvObj* o = find_in(0, h, key)) return live_or_expire(0, h, key, o);
        if (rehashing())
            if (KvObj* o = find_in(1, h, key)) return live_or_expire(1, h, key, o);
        return nullptr;
    }

    uint64_t next_random() {
        // xorshift64*: shard-owner-only state used by cold random sampling paths.
        uint64_t x = random_state_;
        x ^= x >> 12;
        x ^= x << 25;
        x ^= x >> 27;
        random_state_ = x;
        return x * 2685821657736338717ULL;
    }

    uint8_t lru_clock() const { return cached_lru_clock_; }

    void initialize_meta(KvObj* o) {
        if (__builtin_expect(read_local_enabled_, false)) {
            initialize_meta_read_local(o);
            return;
        }
        if (maxmemory_policy_is_lru(maxmemory_policy_)) {
            o->set_eviction_meta(lru_clock());
        } else if (maxmemory_policy_is_lfu(maxmemory_policy_)) {
            o->set_eviction_meta(5);
        }
    }

    void touch(KvObj* o) {
        if (no_touch_) return;
        if (__builtin_expect(read_local_enabled_, false)) {
            touch_read_local(o);
            return;
        }
        note_object_access(o, cached_now_ms_);
        if (maxmemory_policy_is_lru(maxmemory_policy_)) {
            o->set_eviction_meta(lru_clock());
            return;
        }
        if (!maxmemory_policy_is_lfu(maxmemory_policy_)) return;

        uint8_t count = o->eviction_meta();
        if (count == 0) count = 5;
        // Redis-style logarithmic increment with its default factor 10, compressed to five bits.
        const uint32_t base = count > 5 ? static_cast<uint32_t>(count - 5) : 0;
        const uint32_t denominator = base * 10 + 1;
        if (count < 31 && next_random() % denominator == 0) count++;
        o->set_eviction_meta(count);
    }

    KvObj* random_allkeys_candidate() {
        const uint64_t total_cap = static_cast<uint64_t>(cap_[0]) + cap_[1];
        if (total_cap == 0 || size() == 0) return nullptr;
        for (uint32_t attempt = 0; attempt < kSampleProbeAttempts; attempt++) {
            uint64_t pos = next_random() % total_cap;
            const int table = pos < cap_[0] ? 0 : 1;
            if (table == 1) pos -= cap_[0];
            if (KvObj* o = ptr_of(tab_[table][pos])) return o;
        }
        // Sparse-table backstop. It remains bounded and advances between calls rather than
        // restarting at slot zero and repeatedly missing the same empty prefix.
        for (uint32_t attempt = 0; attempt < kSampleProbeAttempts; attempt++) {
            if (sample_cursor_ >= total_cap) sample_cursor_ = 0;
            uint64_t pos = sample_cursor_++;
            const int table = pos < cap_[0] ? 0 : 1;
            if (table == 1) pos -= cap_[0];
            if (KvObj* o = ptr_of(tab_[table][pos])) return o;
        }
        return nullptr;
    }

    KvObj* random_volatile_candidate() {
        uint64_t hash = 0;
        if (!expires_.random_hash(next_random(), kSampleProbeAttempts, hash)) return nullptr;
        KvObj* o = find_hash_in(0, hash);
        if (!o && rehashing()) o = find_hash_in(1, hash);
        if (o && deadline(hash, o) < 0) {
            untrack_expire(hash);
            return nullptr;
        }
        return o;
    }

    // Owner-side bounded eviction sample; returns a borrowed resident pointer or nullptr.
    // configure_maxmemory bounds maxmemory_samples_ to 1..64 for seen[]. ProtectKey skips the
    // incoming key; pending versions/script intents are ineligible. LFU sampling ages metadata;
    // a selected victim emits an expiry/eviction notification here, before the caller deletes it.
    // Armed stores delegate to atomic metadata updates. Sampling uses stack workspace;
    // notification callbacks are outside that allocation/back-pressure guarantee.
    template <bool ProtectKey = true>
    KvObj* choose_victim(Slice protected_key) {
        if (__builtin_expect(read_local_enabled_, false))
            return choose_victim_read_local<ProtectKey>(protected_key);
        KvObj* best = nullptr;
        KvObj* seen[64];
        uint32_t seen_count = 0;
        uint64_t best_score = 0;
        for (uint32_t i = 0; i < maxmemory_samples_; i++) {
            KvObj* candidate = maxmemory_policy_is_volatile(maxmemory_policy_)
                                   ? random_volatile_candidate()
                                   : random_allkeys_candidate();
            if (!candidate) continue;
            if constexpr (ProtectKey)
                if (candidate->key().key_eq(protected_key)) continue;
            if (atomic_needs_version(hash_key(candidate->key()), candidate->key())) continue;
            bool duplicate = false;
            for (uint32_t j = 0; j < seen_count; j++)
                if (seen[j] == candidate) {
                    duplicate = true;
                    break;
                }
            if (duplicate) continue;
            seen[seen_count++] = candidate;

            uint64_t score = 0;
            switch (maxmemory_policy_) {
                case MaxmemoryPolicy::AllKeysRandom:
                case MaxmemoryPolicy::VolatileRandom:
                    score = next_random();
                    break;
                case MaxmemoryPolicy::AllKeysLru:
                case MaxmemoryPolicy::VolatileLru: {
                    const uint8_t age =
                        static_cast<uint8_t>((lru_clock() - candidate->eviction_meta()) & 0x1f);
                    score =
                        (static_cast<uint64_t>(age) << 56) | (next_random() & ((1ULL << 56) - 1));
                    break;
                }
                case MaxmemoryPolicy::AllKeysLfu:
                case MaxmemoryPolicy::VolatileLfu: {
                    // With only five free header bits, sampling is also the bounded aging event:
                    // one count is forgotten whenever a key competes for eviction.
                    uint8_t count = candidate->eviction_meta();
                    if (count) candidate->set_eviction_meta(--count);
                    score = (static_cast<uint64_t>(31 - count) << 56) |
                            (next_random() & ((1ULL << 56) - 1));
                    break;
                }
                case MaxmemoryPolicy::VolatileTtl:
                    score = std::numeric_limits<uint64_t>::max() -
                            static_cast<uint64_t>(deadline(hash_key(candidate->key()), candidate));
                    break;
                case MaxmemoryPolicy::NoEviction:
                    return nullptr;
            }
            if (!best || score > best_score) {
                best = candidate;
                best_score = score;
            }
        }
        if (best) {
            const bool expired = deadline_elapsed(hash_key(best->key()), best, cached_now_ms_);
            notify_flat_store_emit(this, expired ? NOTIFY_EXPIRED : NOTIFY_EVICTED,
                                   expired ? NotifyEventId::Expired : NotifyEventId::Evicted,
                                   best->key());
        }
        return best;
    }

    size_t projected_bytes(Slice key, size_t incoming_bytes) const {
        const uint64_t hash = hash_key(key);
        KvObj* old = find_in(0, hash, key);
        if (!old && rehashing()) old = find_in(1, hash, key);

        size_t used = accounted_bytes();
        if (old) {
            const size_t old_bytes = kvobj_size(old);
            used = used >= old_bytes ? used - old_bytes : 0;
        } else if (used > std::numeric_limits<size_t>::max() - kSlotOverheadPerKey) {
            return std::numeric_limits<size_t>::max();
        } else {
            used += kSlotOverheadPerKey;
        }
        if (incoming_bytes > std::numeric_limits<size_t>::max() - used)
            return std::numeric_limits<size_t>::max();
        return used + incoming_bytes;
    }

    // Admission refusal releases the armed owner's block cache before returning false.
    // Successful eviction keeps that bounded cache available for subsequent writes; trimming
    // on each over-budget write would force fresh allocations and a cache walk each time.
    bool refuse_over_budget() {
        read_local_cache_trim_on_pressure();
        return false;
    }

    bool make_room_for(Slice protected_key, size_t incoming_bytes) {
        // Every caller, including same-class overwrite, must preserve unvisited pre-images.
        if (snapshot_active_) return true;
        if (projected_bytes(protected_key, incoming_bytes) <= maxmemory_limit_) return true;
        if (maxmemory_policy_ == MaxmemoryPolicy::NoEviction) return refuse_over_budget();

        uint32_t budget = kEvictionsPerOp;
        while (budget-- && projected_bytes(protected_key, incoming_bytes) > maxmemory_limit_) {
            KvObj* victim = choose_victim(protected_key);
            if (!victim) return refuse_over_budget();
            const uint64_t hash = hash_key(victim->key());
            const Slice key = victim->key();
            (void)aof_.record_delete(key);
            const uint32_t before = size();
            const bool live = erase(hash, key);
            if (size() == before) return refuse_over_budget();
            if (live && evicted_counter_) (*evicted_counter_)++;
        }
        if (projected_bytes(protected_key, incoming_bytes) <= maxmemory_limit_) return true;
        return refuse_over_budget();
    }

    static uint64_t* allocate_table(uint32_t cap) {
        return static_cast<uint64_t*>(flatstore_table_calloc(cap, sizeof(uint64_t)));  // EMPTY == 0
    }

    // FLUSH's replacement table. A prepared snapshot suppresses every resize until the cut,
    // refusing new keys only when the current table is full. Keep the replacement below the
    // prepared destination's capacity so those keys still fit in the post-capture merge.
    // clear() changes neither input, so it may ask again before installing.
    uint32_t clear_capacity() const {
        return snapshot_prepared_ ? std::min<uint32_t>(snapshot_new_cap_ / 2, 1024) : 1024;
    }

    void install_empty_table(int t, uint64_t* table, uint32_t cap) {
        if (__builtin_expect(read_local_enabled_, false)) {
            install_empty_table_read_local(t, table, cap);
            return;
        }
        tab_[t] = table;
        cap_[t] = cap;
        mask_[t] = cap - 1;
        live_[t] = 0;
        tombs_[t] = 0;
    }

    bool alloc_table(int t, uint32_t cap) {
        uint64_t* fresh = allocate_table(cap);
        if (!fresh) return false;
        std::free(tab_[t]);
        install_empty_table(t, fresh, cap);
        return true;
    }

    // Emit every key whose HOME slot is `home`, wherever linear probing actually put it. Those keys
    // all sit in the run of non-EMPTY words starting at `home`: an insert probes forward from the
    // home and stops at the first EMPTY, and nothing ever writes EMPTY back over an occupied word
    // (erase and rehash leave tombstones; whole-table clear discards the population), so a key
    // cannot be separated from its
    // home. Returns slots examined, charged against COUNT, and never zero -- an empty home must
    // still cost the caller one unit or a sparse table would walk itself out in a single call.
    template <typename Fn>
    uint32_t scan_home(int t, uint32_t home, Fn& fn, bool expire_on_visit) {
        uint32_t examined = 0;
        uint32_t i = home;
        for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
            const uint64_t w = tab_[t][i];
            if (w == 0) break;  // EMPTY — the only stop
            examined++;
            KvObj* o = ptr_of(w);
            if (o) {
                const uint64_t h = hash_key(o->key());
                if (slot_start(t, h) == home) scan_visit(t, h, o, fn, expire_on_visit);
            }
            i = (i + 1) & mask_[t];
        }
        return examined ? examined : 1;
    }

    // Per-key scan visitation. A walker
    // with expire_on_visit=false sees the dead entry as-is: accounting walks must have no
    // logical side effects (see the scan() comment).
    template <typename Fn>
    void scan_visit(int t, uint64_t h, KvObj* o, Fn& fn, bool expire_on_visit) {
        if (!expire_on_visit) {
            fn(o);
            return;
        }
        if (deadline_elapsed(h, o, cached_now_ms_)) {
            // An epoch record, not this physical candidate, owns logical expiry and pointer
            // lifetime. The walker callback resolves it at its registered cut.
            if (atomic_has_record(h, o->key())) {
                fn(o);
                return;
            }
            if (client_pause_expiry_held()) return;
            // During capture the frozen table is the cut, not a normal mutable scan source.
            // Report the key logically absent but leave its slot for snapshot traversal, just
            // like find()/active_expire().  KEYS uses this bounded scan while capture runs.
            if (snapshot_active_ && t == 1) return;
            // Logical expiry remains absent while a reader holds up reclamation.
            // A scan must not enter the full retire ring's grace-period wait; the
            // SCAN command alone deletes what it visits, as Redis does.
            if constexpr (!kScanExpiresVisited<std::remove_cvref_t<Fn>>)
                if (!read_retirement_available()) return;
            notify_flat_store_emit(this, NOTIFY_EXPIRED, NotifyEventId::Expired, o->key());
            (void)aof_.record_delete(o->key());
            erase_in(t, h, o->key());
            if (expired_counter_) (*expired_counter_)++;
            return;
        }
        fn(o);
    }

    KvObj* find_in(int t, uint64_t h, Slice key) const {
        if (!tab_[t]) return nullptr;
        const uint16_t tag = tag_of(h);
        uint32_t i = slot_start(t, h);
        for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
            const uint64_t w = tab_[t][i];
            if (w == 0) return nullptr;  // EMPTY — the only stop
            KvObj* o = ptr_of(w);
            if (o && tag_of_word(w) == tag && o->key().key_eq(key)) return o;
            i = (i + 1) & mask_[t];
        }
        return nullptr;
    }

    KvObj* find_slot_in(int t, uint64_t h, Slice key, uint32_t& slot) const {
        if (!tab_[t]) return nullptr;
        const uint16_t tag = tag_of(h);
        uint32_t i = slot_start(t, h);
        for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
            const uint64_t w = tab_[t][i];
            if (w == 0) return nullptr;
            KvObj* o = ptr_of(w);
            if (o && tag_of_word(w) == tag && o->key().key_eq(key)) {
                slot = i;
                return o;
            }
            i = (i + 1) & mask_[t];
        }
        return nullptr;
    }

    KvObj* find_hash_in(int t, uint64_t h) const {
        if (!tab_[t]) return nullptr;
        const uint16_t tag = tag_of(h);
        uint32_t i = slot_start(t, h);
        for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
            const uint64_t w = tab_[t][i];
            if (w == 0) return nullptr;
            KvObj* o = ptr_of(w);
            // The slot flag is a byte on the object line the hash would read anyway; testing it
            // first spares a full key hash on every slotless key that merely shares the 15-bit
            // tag. The flag describes physical storage: a retained slot may hold -1. Check
            // logical volatility with deadline only after the full hash confirms identity.
            if (o && tag_of_word(w) == tag && o->has_ttl_slot() && hash_key(o->key()) == h &&
                deadline(h, o) >= 0)
                return o;
            i = (i + 1) & mask_[t];
        }
        return nullptr;
    }

    // Probe by full hash without find_hash_in's key-TTL filter. The field-TTL attention index
    // also tracks hashes without key deadlines; filtering them out would deregister valid
    // field-expiry work and incorrectly reduce hash_field_expires to zero.
    KvObj* find_any_hash_in(int t, uint64_t h) const {
        if (!tab_[t]) return nullptr;
        const uint16_t tag = tag_of(h);
        uint32_t i = slot_start(t, h);
        for (uint32_t probes = 0; probes <= cap_[t]; probes++) {
            const uint64_t w = tab_[t][i];
            if (w == 0) return nullptr;
            KvObj* o = ptr_of(w);
            if (o && tag_of_word(w) == tag && hash_key(o->key()) == h) return o;
            i = (i + 1) & mask_[t];
        }
        return nullptr;
    }

    KvObj* live_or_expire(int t, uint64_t h, Slice key, KvObj* o) {
        // This is the non-expiring-key tax: one flags branch after the ordinary lookup. No clock
        // read occurs here; the executor refreshed cached_now_ms_ once for its executed batch.
        if (!o->has_ttl_slot()) return o;
        const int64_t at = deadline(h, o);
        if (at < 0 || at >= cached_now_ms_) return o;  // Redis: still live at now == at
        return expire_found(t, h, key);
    }

    // Keep maintenance-only checks out of the non-expiring lookup's inline
    // body and register allocation. No pause clock is read for a live key.
    [[gnu::noinline]] inline KvObj* expire_found(int t, uint64_t h, Slice key);

    // `fresh` means a newly published object: charge its bytes and (re)register its deadline.
    // The one false caller is rehash_step(), moving an object that is already charged and already
    // indexed -- the slot word moves, nothing else does.
    bool insert_into(int t, uint64_t h, KvObj* o, bool fresh);

    static void notify_emit(FlatNotifySink* sink, uint32_t cls, NotifyEventId event, Slice key);

    bool erase_in(int t, uint64_t h, Slice key, bool* was_expired = nullptr,
                  const KvObj* replacement = nullptr);

    TtlResult rewrite_expire(uint64_t h, KvObj* old, int64_t expire_at_ms);

    OverwriteResult try_overwrite_read_local(uint64_t, Slice, Slice);

    bool snapshot_mark_read_local(int32_t shard_id, int64_t cut_ms);

    SnapshotWriteResult snapshot_prepare_write_read_local(uint64_t h, Slice key);

    uint32_t snapshot_progress_read_local(uint32_t byte_budget, uint32_t slot_budget);

    // Owner-side armed serializer continuation, with snapshot_progress_record's object and
    // budget preconditions. A ready chunk pauses emission; invalid state, hook or allocation
    // failure sets snapshot_failed_. On completion a pre-image mark uses a release slot store;
    // otherwise the owner cursor advances. It does not transfer object ownership.
    void snapshot_progress_record_read_local(uint32_t& budget);

    TtlResult set_expire_read_local(uint64_t h, Slice key, int64_t expire_at_ms);

    TtlResult set_expire_notify_read_local(uint64_t h, Slice key, int64_t expire_at_ms,
                                           FlatNotifySink* sink);

    InsertResult insert_read_local(uint64_t h, KvObj* o);

    bool erase_read_local(uint64_t h, Slice key);

    void clear_read_local();

    void clear_during_snapshot_read_local();

    void initialize_meta_read_local(KvObj* o);

    void touch_read_local(KvObj* o);

    // Armed owner eviction sample; same 1..64 sample bound, key/version exclusions and borrowed
    // result as choose_victim. LFU aging uses set_eviction_meta_atomic: a relaxed load and
    // release store preserve layout bits. Selection emits a notification; the caller owns deletion.
    // No candidate or NoEviction returns nullptr. Sampling uses stack workspace; notification
    // callbacks are outside that allocation/back-pressure guarantee.
    template <bool ProtectKey = true>
    KvObj* choose_victim_read_local(Slice protected_key);

    void install_empty_table_read_local(int t, uint64_t* table, uint32_t cap);

    bool insert_into_read_local(int t, uint64_t h, KvObj* o, bool track_expire);

    bool erase_in_read_local(int t, uint64_t h, Slice key, bool* was_expired = nullptr,
                             const KvObj* replacement = nullptr);

    TtlResult rewrite_expire_read_local(uint64_t h, KvObj* old, int64_t expire_at_ms);

    // kvobj_external_bytes() is out of line and switches on type. One byte of the header (already
    // hot: the key compare loaded it) decides whether anything lives outside the block, so test it
    // here and pay the call only for Enc::Extern. Same value as kvobj_size(o) - kvobj_capacity(o).
    static size_t read_local_external_bytes(const KvObj* object);

    // Logical retirement, before QSBR destruction: only the external
    // stream type arm signals blocked group readers. String retirement retains
    // its ordinary encoding test and adds no waiter test or callback.
    size_t retiring_external_bytes(const KvObj* object, const KvObj* replacement = nullptr);

    // Decode the header ONCE, exactly as unarmed retire_obj() does: the size class computed for
    // accounting is also the sized-free length. It travels to the reclaim callback as the ring's
    // auxiliary word, so the free after the grace period does not re-derive it from a header that
    // has gone cold. Retired layout bits stay fixed; eviction-meta updates preserve them,
    // so the allocation class cannot change between retire and reclaim.
    void retire_obj_read_local(KvObj* object, const KvObj* replacement = nullptr);

    bool start_rehash_read_local(uint32_t newcap);

    void rehash_step_read_local();

    bool prepare_resize_retirement();

    template <typename T>
    void read_local_topology_store(T* location, T value);

    // Release-publish the object pointer; foreign slot loads use acquire and QSBR protects
    // its lifetime. Multi-slot/table moves also need the topology bracket. The *_read_local
    // callers dispatch through read_local_enabled_, so this helper omits another latch check;
    // a release store would also be safe on an unarmed table.
    static void read_local_slot_store(uint64_t* location, uint64_t value);

    static uint64_t read_local_slot_load(const uint64_t* location);

    static bool read_local_probe_sequence_equal(uint64_t first, uint64_t second);

    bool read_local_snapshot_topology(uint64_t state, ReadLocalTopology& topology) const;

    const KvObj* read_local_capture_in(const ReadLocalTable& table, uint64_t hash, Slice key,
                                       const uint64_t*& captured_slot) const;

    static void read_local_prefetch_object(const KvObj* object);

    void write_eviction_meta_read_local(KvObj* object, uint8_t meta);

    void write_object_flags_read_local(KvObj* object, uint8_t flags);

    static void read_local_reclaim_table(void*, void* payload, size_t);

    // Post-grace callback on the retire sink's owner. capacity is the retire-time allocation
    // class carried in the ring's auxiliary word. Foreign QSBR readers have released the
    // pointer; outstanding wire borrows can still retain it. Try the owner's block cache,
    // then let destroy_retired_obj preserve any wire borrow or destroy the block.
    static void read_local_reclaim_object(void* owner, void* payload, size_t capacity);

    static void read_local_reclaim_atomic_object(void* owner, void* payload, size_t capacity);

    void retire_table_read_local(uint64_t* table);

    void read_local_table_mutation_begin();

    void read_local_table_mutation_end();

    // Ownership supplies the only writer, so the table word needs no locked RMW. The acq_rel fence
    // after the release odd-store keeps that marker before later data stores; the final release
    // store publishes the incremented even generation. Wrap becomes permanently fail-closed.
    static void read_local_advance_generation(std::atomic<uint64_t>& sequence, bool ending);

    void read_local_pending_publish(AtomicEntry& entry);

    void read_local_pending_unpublish(AtomicEntry& entry);

    void foreign_read_pending_witness_open(ReadLocalStoreState& state);

    void foreign_read_pending_witness_close(ReadLocalStoreState& state);

    void foreign_read_poison_open();

    void foreign_read_poison_close();

    bool is_borrowed(const char* ptr) const;

    // `capacity` is the allocation size captured when the owner retired the object.
    void free_retired_obj_now(KvObj* object, size_t capacity);

    // Post-grace destruction. Only the rare borrowed path needs the full footprint again, and it
    // rebuilds it from the retire-time capacity plus the external block (== kvobj_size).
    void destroy_retired_obj(KvObj* object, size_t capacity);

    // Logical removal updates the live-store footprint immediately. Physical destruction is the
    // common case and pays one branch; registry work exists only while some wire borrow is live.
    // The header is decoded once: the class computed for accounting is the sized-free length.
    // Keep replacement context inside the external-value branch. Outlining this
    // wrapper passes an otherwise unused extra argument for inline integers.
    void retire_obj(KvObj* o);
    [[gnu::always_inline]] void retire_obj(KvObj* o, const KvObj* replacement);

    // ---- incremental resize -----------------------------------------------------------------
    bool maybe_start_grow();

    void maybe_start_shrink();

    // Demote the current table to the old slot and install a fresh one. NOTHING is copied here —
    // that is the whole point; the slot-word migration is spread across later operations.
    bool start_rehash(uint32_t newcap);

    // Move a bounded number of slot words during mutations/owner maintenance, never lookup.
    // Armed completion hands off a preallocated retirement record without waiting for grace.
    void rehash_step();

    friend struct FlatStoreLayoutLock;
    friend class AofProducer;
#ifdef TOMO_STORE_REGRESSION_TEST
    friend struct FlatStoreRegressionTest;
#endif

    // Reader topology is separated from two ranges of frequently written owner state.
    // Foreign captures load atomic_pending_ to reach probe_sequence/filter, plus tab_/cap_/
    // mask_ and read_local_enabled_. Owner insert/delete updates live_, tombs_, rehash_pos_
    // and accounting; atomic operations update version bytes, scratch vectors and read context.
    // Sharing these words on a cache line would invalidate a foreign reader's topology loads.
    //
    // FlatStoreLayoutLock asserts at least 64 bytes between the named reader and owner
    // ranges. Offset separation holds for any allocation base; a compact range by itself
    // need not fit one cache line at every alignment. Fields outside those ranges, including
    // field_ttl_gate_, are not covered by the separation proof.
    //
    // atomic_pending_ is allocated lazily for unarmed MVCC and prepared before read-local
    // arming. The allocation remains as a pool after entries drain. Armed foreign probes
    // read this pointer; atomic_ensure_pending, ensure_read_local_store_state and shutdown
    // manage its lifetime, separately from per-operation atomic accounting.
    AtomicPendingState* atomic_pending_ = nullptr;
    uint64_t* tab_[2] = {nullptr, nullptr};
    // Capacities are power-of-two and intentionally stop at 2^31: slot/probe indices are uint32_t
    // and insert_into's tombstone sentinel is int32_t. A requested next doubling (2^32 slots,
    // already 32 GiB for one shard's slot words) returns InsertResult::Failed before any swap.
    // Tables beyond four billion slots are therefore outside this store's representation rather
    // than a legitimate reason to widen these hot fields.
    uint32_t cap_[2] = {0, 0};
    uint32_t mask_[2] = {0, 0};
    // Set during arming and cleared after foreign readers stop. The capture API tests this
    // before loading topology. The extended armed state lives in the pending-state sidecar.
    bool read_local_enabled_ = false;
    // Sticky on field-index allocation failure until clear; ordinary hash access consults
    // the derived field_ttl_gate_ rather than this bookkeeping byte.
    bool field_ttl_index_incomplete_ = false;

    // Configuration, snapshot preparation and counter bindings separate the main owner
    // counters from topology. These fields are outside the asserted owner counter range;
    // field_ttl_gate_ can change during key work and is not read-mostly.
    bool maxmemory_enabled_ = false;
    MaxmemoryPolicy maxmemory_policy_ = MaxmemoryPolicy::NoEviction;
    // Hash-field TTL access gate, kept near lookup topology. refresh_field_ttl_gate updates
    // it after attention changes; an incomplete index keeps it positive until clear.
    uint32_t field_ttl_gate_ = 0;
    uint32_t maxmemory_samples_ = 5;
    int32_t snapshot_shard_id_ = -1;
    uint64_t maxmemory_limit_ = 0;
    uint64_t* snapshot_new_tab_ = nullptr;
    uint64_t* evicted_counter_ = nullptr;
    uint64_t* rehash_counter_ = nullptr;
    uint64_t snapshot_epoch_ = 0;
    int64_t snapshot_cut_ms_ = 0;
    uint32_t snapshot_new_cap_ = 0;
    // Reserved separator storage keeps FlatStore at 944 bytes and the named ranges apart.
    // Bytes 4..11 hold the storesize pointer via memcpy; bytes 12..19 hold the constructed,
    // aligned atomic ObjectIdleClock pointer used by acquire/release publication.
    // Preserve these occupied bytes and FlatStoreLayoutLock when assigning spare storage.
    char reader_owner_gap_[28] = {};

    // Owner mutation counters: the range through borrow_tombs_ is 48 bytes. The offset
    // asserts separate this range from foreign topology regardless of base alignment.
    uint32_t live_[2] = {0, 0};
    uint32_t tombs_[2] = {0, 0};
    uint32_t rehash_pos_ = 0;
    uint32_t active_expire_reap_lag_ms_max_ = 0;
    size_t obj_bytes_ = 0;
    size_t pending_bytes_ = 0;
    uint32_t outstanding_borrows_ = 0;
    uint32_t borrow_tombs_ = 0;
    // The live snapshot cursor is owner-written under ordinary write traffic, so it belongs on this
    // side of the split even though the rest of the capture's scalars are latched once and sit in
    // the separator above.
    uint32_t snapshot_pos_ = 0;
    uint32_t snapshot_sequence_ = 0;
    // Owner clock, expiry binding and snapshot gates occupy a compact 64-byte window beside
    // the mutation counters so inserts can read them without touching cold sidecars.
    int64_t cached_now_ms_ = 0;
    uint8_t cached_lru_clock_ = 0;
    bool no_touch_ = false;  // per-task, owner-written; see set_no_touch
    // Owner snapshot state; lookup searches tab_[0] then tab_[1]. During capture these
    // represent the post-cut table and frozen slot layout respectively. Armed access still
    // uses the slot/topology publication protocol; snapshot cursor fields are owner-local.
    bool snapshot_prepared_ = false;
    bool snapshot_active_ = false;
    bool snapshot_failed_ = false;
    bool snapshot_finished_ = false;
    uint64_t* expired_counter_ = nullptr;
    uint64_t random_state_ = 0x9e3779b97f4a7c15ULL;
    uint64_t sample_cursor_ = 0;
    uint64_t snapshot_preimages_ = 0;  // pre-images emitted ahead of the cursor (write-gate fired)
    std::vector<Borrow> borrows_;
    std::vector<uint32_t> borrow_idx_;  // empty == scan mode; see kBorrowIndexMin
    ExpireIndex expires_;
    SnapshotRecordState snapshot_record_;
    std::unique_ptr<SnapshotChunk> snapshot_build_;
    std::unique_ptr<SnapshotChunk> snapshot_ready_;
    AofProducer aof_;
    // Cold hash-field attention follows the hot clock, maxmemory and snapshot fields to keep
    // their offsets compact. Its index allocates on the first registration, not construction.
    ExpireIndex field_expires_;
    uint64_t field_expired_ = 0;
};

#include "flatstore_impl.h"

// THE READER/OWNER LINE SPLIT, pinned in offsets so nothing about it depends on where a Shard
// happens to land in memory. `new Shard` promises 16-byte alignment, not 64, and the store sits at
// ShardLayoutLock::store_offset inside it; both are free to change. Two bytes whose OFFSETS differ
// by at least 64 are on different lines for every possible base address, which is the only form of
// this guarantee that a static_assert can actually make.
struct FlatStoreLayoutLock {
    // Every byte a foreign reader loads out of FlatStore on the GET path, and nothing else.
    // atomic_pending_ is the FIRST of them: read_local_probe() cannot reach probe_sequence, the
    // read-local filter without loading it; foreign probes do not access the retire sink.
    static constexpr size_t reader_first = offsetof(FlatStore, atomic_pending_);
    static constexpr size_t reader_last = offsetof(FlatStore, read_local_enabled_);
    // Every byte the owner writes on the ordinary insert-a-new-key / DEL path.
    static constexpr size_t owner_first = offsetof(FlatStore, live_);
    static constexpr size_t owner_last = offsetof(FlatStore, borrow_tombs_) + 3;
    // Every byte the owner writes on the ATOMIC path, declared ahead of the reader block:
    // atomic_version_bytes_ is the first word of the object, the three collapse scratch vectors and
    // the seen-key vector follow, and the per-operation read context closes the range.
    static constexpr size_t atomic_owner_first = offsetof(FlatStore, atomic_version_bytes_);
    static constexpr size_t atomic_owner_last =
        offsetof(FlatStore, atomic_read_origin_conn_id_) + 7;
    // First word of the bind-once separator that buys the distance below it.
    static constexpr size_t atomic_separator_first = offsetof(FlatStore, atomic_ticket_fn_);
    static constexpr size_t line = 64;
    static constexpr size_t gap_bytes = sizeof(FlatStore::reader_owner_gap_);
    static_assert((offsetof(FlatStore, reader_owner_gap_) + 12) %
                      alignof(std::atomic<ObjectIdleClock*>) ==
                  0);
};

// The named reader range is separated from the owner counter range below and the atomic
// owner range above for every base address. Keep the range endpoints current when adding
// fields: these assertions do not infer access patterns or cover fields outside the ranges.
static_assert(FlatStoreLayoutLock::owner_first - FlatStoreLayoutLock::reader_last >=
                  FlatStoreLayoutLock::line,
              "owner-written counters may share a cache line with the reader topology words");
static_assert(FlatStoreLayoutLock::reader_first - FlatStoreLayoutLock::atomic_owner_last >=
                  FlatStoreLayoutLock::line,
              "atomic accounting words may share a cache line with the reader's probe words");
// These bounds keep each named range shorter than a cache line. Actual line occupancy
// also depends on the range's starting address; separation above is base-independent.
static_assert(FlatStoreLayoutLock::reader_last - FlatStoreLayoutLock::reader_first <
                  FlatStoreLayoutLock::line,
              "reader topology block no longer fits one line");
static_assert(FlatStoreLayoutLock::owner_last - FlatStoreLayoutLock::owner_first <
                  FlatStoreLayoutLock::line,
              "owner counter block no longer fits one line");
// The distance above is bought entirely by the bind-once bindings, which start where the atomic
// owner block ends. An owner-written field appended to that block would extend it PAST the assert's
// named last word and stay invisible to it; this is what refuses that edit. Widening the separator
// with more bind-once state is fine — move atomic_separator_first onto the new first field.
static_assert(FlatStoreLayoutLock::atomic_separator_first ==
                  FlatStoreLayoutLock::atomic_owner_last + 1,
              "a field slipped in between the atomic owner block and its read-mostly separator");
// The gap is padding on purpose; if a future field shrinks it below the line, say so here.
static_assert(FlatStoreLayoutLock::gap_bytes == 28);

// Read-local sidecars preserve the unarmed FlatStore footprint checked by atomic_torn.
static_assert(sizeof(FlatStore) == 944);

// Owner-scoped accounting bracket, borrowing a store and object. Samples kvobj_size on
// entry and reports the growth/shrink delta once on finish/destruction; no publication or
// allocation occurs here. Finish before deleting a mutated object, then cancel if needed:
// erase subtracts its current size, and reporting a delta after deletion would dereference
// freed storage. Missing growth accounting can underflow obj_bytes_ at later removal.
class ObjectSizeTracker {
public:
    ObjectSizeTracker(FlatStore& store, KvObj* object)
        : store_(store), object_(object), before_(object ? kvobj_size(object) : 0) {}
    ~ObjectSizeTracker() { finish(); }
    ObjectSizeTracker(const ObjectSizeTracker&) = delete;
    ObjectSizeTracker& operator=(const ObjectSizeTracker&) = delete;

    void finish() {
        if (!object_) return;
        store_.note_object_size_change(before_, kvobj_size(object_));
        object_ = nullptr;
    }

    // For paths that erase the object inside the bracket: the store already subtracted the full
    // current size in erase(); reporting a delta on top would double-count.
    void cancel() { object_ = nullptr; }

private:
    FlatStore& store_;
    KvObj* object_;
    size_t before_;
};

}  // namespace tomo
