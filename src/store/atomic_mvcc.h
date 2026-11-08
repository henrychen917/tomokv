// atomic_mvcc.h — free-standing epoch-MVCC records and helpers used by FlatStore.
//
// Included normally by flatstore.h. Records and pools are manipulated under store ownership;
// shared group decisions use atomics. FlatStore's ordinary MVCC members are included inside its
// class from flatstore_atomic.inc; range-record implementations are in flush.cc.
#pragma once
#include <atomic>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include "kv_block_cache.h"
#include "kvobj.h"

namespace tomo {

struct ScatterState;

// FlatStore owns this record allocation and its trailing parked-value slots/key storage. The
// shard owner links, installs and collapses records; post-join teardown also releases them.
// group and decision/ref pointers refer to separately retained unit state. atomic_epoch acquires
// group_epoch; plain links/slots provide no cross-thread publication. Prepare can fail before
// installation; count must not exceed capacity, and release must balance the group's references.
struct AtomicEntry {
    AtomicEntry* next = nullptr;
    AtomicEntry* prev = nullptr;
    AtomicEntry* conn_next = nullptr;
    AtomicEntry* conn_prev = nullptr;
    AtomicEntry* pool_next = nullptr;
    ScatterState* group = nullptr;
    std::atomic<uint64_t>* group_epoch = nullptr;
    std::atomic<uint32_t>* group_refs = nullptr;
    std::atomic<bool>* group_aborted = nullptr;
    uint32_t* owner_refs = nullptr;
    uint64_t origin_conn_id = 0;
    uint64_t epoch = 0;  // plain pseudo-entry; groups use group_epoch
    uint64_t plain_hash = 0;
    uint64_t membership = 0;
    size_t allocation = 0;
    uint32_t begin = 0;  // key_order span in ScatterState
    uint32_t count = 0;  // installed prefix of the span
    uint32_t capacity = 0;
    uint32_t key_len = 0;
    bool linked = false;
    // Set after prepare publishes every key occurrence in the foreign-read safety filter (and the
    // whole-shard pending witness). It remains set through install, linking and collapse.
    bool foreign_read_unsafe_published = false;
    // DEL/UNLINK groups own packed key bytes in this allocation instead of one empty KvObj per
    // key. The flag fits in the locked 144-byte header.
    bool copied_group_keys = false;
    uint8_t key_ns = 0;
    bool namespace_range = false;
    bool range_all = false;
    uint16_t range_padding = 0;  // permits a combined store for tail initialization

    KvObj** parked() { return reinterpret_cast<KvObj**>(this + 1); }
    KvObj* const* parked() const { return reinterpret_cast<KvObj* const*>(this + 1); }
    char* plain_key_data() { return reinterpret_cast<char*>(parked() + capacity); }
    const char* plain_key_data() const {
        return reinterpret_cast<const char*>(parked() + capacity);
    }
    uint32_t* group_key_offsets() { return reinterpret_cast<uint32_t*>(parked() + capacity); }
    const uint32_t* group_key_offsets() const {
        return reinterpret_cast<const uint32_t*>(parked() + capacity);
    }
    char* group_key_data() { return reinterpret_cast<char*>(group_key_offsets() + capacity); }
    const char* group_key_data() const {
        return reinterpret_cast<const char*>(group_key_offsets() + capacity);
    }
    bool plain() const { return group == nullptr; }
};

// The foreign-read lifetime marker occupies tail padding. Atomic entries are pooled by
// allocation class, so growing the header would change both the disabled allocation path and its
// cache geometry.
static_assert(sizeof(AtomicEntry) == 144);

// Owner-local protection installed while a cross-owner script is staged.  It deliberately lives
// beside the cold MVCC list rather than in KvObj. Script PIN and unit-intent paths allocate it
// lazily; trailing key bytes do not borrow the IO request buffer. The shard owner maintains refs
// and links, with post-join cleanup for abandoned pins. Allocation failure is returned by the
// pin helpers; list publication is owner-local, with release updates to the activity counters.
struct AtomicScriptIntent {
    uint32_t key_ns = 0;
    uint32_t kind = 0;  // 0: script PIN; 1: unit key; 2: unit shard
    AtomicScriptIntent* next = nullptr;
    uint64_t hash = 0;
    uint32_t refs = 0;
    uint32_t key_len = 0;
    char* key_data() { return reinterpret_cast<char*>(this + 1); }
    const char* key_data() const { return reinterpret_cast<const char*>(this + 1); }
};
static_assert(sizeof(AtomicScriptIntent) == 32);
static_assert(offsetof(AtomicScriptIntent, kind) == 4);
static_assert(offsetof(AtomicScriptIntent, next) == 8);
static_assert(offsetof(AtomicScriptIntent, hash) == 16);
static_assert(offsetof(AtomicScriptIntent, refs) == 24);
static_assert(offsetof(AtomicScriptIntent, key_len) == 28);

// Prefix allocated before kind-1/2 intents by atomic_unit_pin; kind-0 PIN nodes have no prefix.
// The prefix preserves AtomicScriptIntent's offsets and key-matching predicates for both kinds.
// Borrows a transaction/group and its atomic decisions; the command layer must retain them.
// For group units atomic_free_unit_intent finishes watch claims and retire claims on the intent's
// shard, then release-decrements watch_refs. The shard owner accesses the prefix;
// atomic_intent_unit requires the prefixed allocation and does not validate that precondition.
struct UnitRef {
    enum class Kind : uint8_t { Txn, Group };
    std::atomic<uint64_t>* epoch = nullptr;
    std::atomic<bool>* aborted = nullptr;
    const void* unit = nullptr;
    Kind unit_kind = Kind::Txn;
    uint64_t age_ns = 0;
    uint32_t age_io = 0;
    uint32_t age_seq = 0;
};
static_assert(sizeof(UnitRef) % alignof(AtomicScriptIntent) == 0);
inline UnitRef& atomic_intent_unit(AtomicScriptIntent& intent) {
    return *(reinterpret_cast<UnitRef*>(&intent) - 1);
}
inline const UnitRef& atomic_intent_unit(const AtomicScriptIntent& intent) {
    return *(reinterpret_cast<const UnitRef*>(&intent) - 1);
}
void atomic_cancel_unit_record(AtomicEntry&);
void atomic_cancel_unit_intent(AtomicScriptIntent&);
void atomic_shutdown_unit_intent(AtomicScriptIntent&);
// Out-of-line destruction keeps unit-specific reference release outside the owner unpin walk.
void atomic_free_unit_intent(UnitRef*);

// FlatStore owns the pending lists, intent list and size-class pools. The shard owner mutates
// plain bookkeeping; shutdown drains it after workers join. Foreign read-local probes inspect
// the read_local_extended discriminator, initialized before arming and left fixed thereafter.
// Allocation failure is handled by FlatStore's prepare helpers, not this aggregate; no queue
// wait or publication barrier is implemented here.
struct AtomicPendingState {
    // Owner-local free-list overlay on a reclaimed value block; not a live KvObj at the same time.
    struct FreeValue {
        FreeValue* next;
        size_t allocation;
    };
    static constexpr uint32_t kPoolClasses = KvBlockCache::kClasses;
    AtomicEntry* head = nullptr;
    AtomicEntry* tail = nullptr;
    AtomicEntry* conn_heads[64] = {};
    uint32_t live = 0;
    // Keep the plain GET/SET no-record/no-intent check confined to live and this adjacent word:
    // atomic_has_records must not gain a second cache-line touch for script intents. Other pending
    // state belongs to active version/intent paths.
    uint32_t script_intent_count = 0;
    AtomicScriptIntent* script_intents = nullptr;
    AtomicEntry* free_entries[kPoolClasses] = {};
    FreeValue* free_values[kPoolClasses] = {};
    uint32_t cached_entries = 0;
    // Read-local uses an extended allocation whose first member is this state. The discriminator
    // shares the four-byte gap before cleanup_fast with the flags/counts below; offsets are locked.
    bool read_local_extended = false;
    // Owner-task-only: an install span has physical candidates but is not linked yet. Eviction
    // cannot resolve their ownership until publication. Stored in the gap before cleanup_fast.
    bool group_installing = false;
    // Modulo-256 grouped-record count. finish_group_install updates it with group_installing;
    // range installs increment it alone, and atomic_unlink_conn decrements it alone.
    uint8_t group_records = 0;
    // FLUSH-only count, saturated at 255. A saturated release recounts before
    // publishing a smaller value, so arbitrarily many live ranges cannot wrap.
    uint8_t ranges = 0;
    uint64_t cleanup_fast = 0;
    uint64_t cleanup_slow = 0;
    size_t cached_entry_bytes = 0;
    size_t cached_value_bytes = 0;

    __attribute__((always_inline)) void finish_group_install() {
        // These two bytes are owner-only. Never widen this update over
        // read_local_extended: foreign readers inspect that immutable byte.
        uint16_t flags;
        auto* flags_at =
            reinterpret_cast<char*>(this) + offsetof(AtomicPendingState, group_installing);
        std::memcpy(&flags, flags_at, sizeof(flags));
        flags += 0xffu;  // installed flag 1 -> 0, group count +1 modulo 256
        std::memcpy(flags_at, &flags, sizeof(flags));
    }
};

static_assert(sizeof(AtomicPendingState) == 1352);
static_assert(std::endian::native == std::endian::little);
static_assert(offsetof(AtomicPendingState, group_installing) ==
              offsetof(AtomicPendingState, read_local_extended) + 1);
static_assert(offsetof(AtomicPendingState, group_records) ==
              offsetof(AtomicPendingState, read_local_extended) + 2);

static_assert(offsetof(AtomicPendingState, read_local_extended) == 1316);
static_assert(offsetof(AtomicPendingState, ranges) == 1319);

// Process-wide range-operation counters, separate for each compiled database namespace. Command
// decision and owner paths update atomics; INFO samples them. Relaxed operations supply counts, not a fence
// or an internally consistent snapshot of all fields. They own no per-store memory.
struct AtomicFlushCounters {
    std::atomic<uint64_t> units{0}, range_reads{0}, post_versions{0};
    std::atomic<uint64_t> script_conflicts{0}, collapses{0}, slow_collapses{0};
    std::atomic<uint64_t> slow_work{0};
};
inline AtomicFlushCounters atomic_flush_counters;
// Keep the cold clock helper outside the scatter translation unit to isolate its inlining
// budget from ordinary-command expiry work.
int64_t atomic_flush_now_ms();
[[gnu::cold, gnu::noinline]] bool atomic_flush_covers(const AtomicEntry&, Slice);
inline bool atomic_range_covers(const AtomicEntry& entry, Slice key) {
    return entry.namespace_range && (entry.range_all || entry.key_ns == key.ns);
}

// Borrowed resolver result for the store owner: value is not retained or freed by this wrapper.
// matched means some range or key record matched. physical is true when nothing matched or the
// physical candidate won; an invisible range-only match returns the physical object with physical
// false. Only value is read by current callers.
struct AtomicResolved {
    KvObj* value = nullptr;
    bool matched = false;
    bool physical = true;
};

// Owner-local scratch for one key's collapse. Keys and object/record pointers borrow storage
// retained by FlatStore until the collapse transfers or retires it. No independent publication
// or cleanup occurs here; the caller maintains those lifetimes through the entire walk.
struct AtomicCollapseKey {
    uint64_t hash = 0;
    Slice key;
    KvObj* base = nullptr;
    AtomicEntry* previous = nullptr;
    KvObj* winner = nullptr;
    KvObj* physical = nullptr;
    KvObj* physical_loser = nullptr;
    AtomicEntry* boundary = nullptr;
    uint32_t boundary_index = 0;
    uint64_t winner_epoch = 0;
    bool winner_set = false;
    // Program-order repair state for this key, carried along the collapse walk. `prev_epoch` is
    // the EFFECTIVE epoch assigned to the previous record for the key and `prev_conn_id` is the
    // connection that owned it; a following record from the same connection may never rank below
    // it, because one connection's records reach an owner in the order the client sent them.
    uint64_t prev_conn_id = 0;
    uint64_t prev_epoch = 0;
    bool prev_set = false;
};

// Owner-local scratch index into the collapse-key vector; zero marks an unoccupied slot.
struct AtomicCollapseSlot {
    uint64_t hash = 0;
    uint32_t index = 0;  // collapse_keys_ index + 1; zero is empty
};

// Owner-local duplicate-key scratch; the Slice borrows record key bytes for the traversal.
struct AtomicSeenKey {
    uint64_t hash;
    Slice key;
};

// An applied script and a conflicting writer arbitrate on its shared decision
// word. The abort sentinel is never a visible version, including in newest-write
// contexts whose cut is UINT64_MAX. No reader retries or waits on that decision.
inline constexpr uint64_t kAtomicCancelledEpoch = UINT64_MAX;
static uint64_t atomic_epoch(const AtomicEntry& entry) {
    const uint64_t epoch =
        entry.group_epoch ? entry.group_epoch->load(std::memory_order_acquire) : entry.epoch;
    return epoch == kAtomicCancelledEpoch ? 0 : epoch;
}

static uint64_t atomic_membership_bit(uint64_t hash) { return uint64_t{1} << (hash & 63); }

// One definition, shared with the owner's block cache so the two size-class tables cannot drift.
static uint32_t atomic_pool_class(size_t allocation) { return kv_block_class(allocation); }

}  // namespace tomo
