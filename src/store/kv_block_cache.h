// kv_block_cache.h — the physical owner's post-grace KvObj block cache.
// Included by atomic_mvcc.h and the core reclamation queue. A published read-local string must
// be replaced rather than overwritten; its displaced storage becomes reusable after QSBR grace.
// The accepting queue's physical owner keeps freed blocks across shards, and a shard handoff
// rebinds future accesses to the destination owner's cache. Already queued retirements remain
// with their accepting queue. Cached memory is unreachable by readers before any FreeBlock write.
//
// A per-owner cache shares its head array and byte gauge across the owner's shards, matching
// jemalloc's thread-local reuse scope. It owns no live KvObj and does not shorten reader lifetimes.
#pragma once
#include <atomic>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include "../base/alloc.h"
#include "kvobj.h"
#include "read_local_reclaim.h"
#ifdef TOMO_RL_CACHE_DEBUG
#include <cstdio>
#include <unordered_set>
#include <unistd.h>
#include <sys/syscall.h>
#endif

namespace tomo {

// Size-class index for a good_size()-rounded allocation. Injective over good_size outputs, which
// is what lets a class head hold exactly one request size and a take() skip any header decode.
// AtomicPendingState's value/entry pools use the same table through atomic_pool_class().
inline uint32_t kv_block_class(size_t allocation) {
    if (allocation <= 8) return 0;
    if (allocation <= 128) return static_cast<uint32_t>(allocation / 16);
    const int k = 63 - __builtin_clzll(static_cast<unsigned long long>(allocation - 1));
    const size_t step = size_t{1} << (k - 2);
    const uint32_t quarter = static_cast<uint32_t>(allocation / step);
    return 9u + 4u * static_cast<uint32_t>(k - 7) + (quarter - 5u);
}

// The accepting physical owner alone calls take/put during operation; post-join shutdown also
// calls release_all. No list synchronization is provided. put takes ownership only on success,
// after reader grace, and requires a class-rounded block of the stated size; rejection leaves
// freeing to the caller. take transfers a cached block or returns null. Corrupt counts/classes
// and an immediate duplicate put abort. Relaxed byte-gauge stores allow concurrent INFO samples,
// but do not publish list contents. Call release_all before destroying this aggregate.
struct KvBlockCache {
    // The list node is written OVER the retired object; a block is either a live KvObj or a node,
    // never both. 16 bytes, so any class this cache accepts can hold one.
    struct FreeBlock {
        FreeBlock* next;
        size_t allocation;
    };

    // Classes through 112 KiB, the same span the shard pools accept. Larger blocks fall through
    // to the allocator, including large collection headers or strings with huge keys.
    static constexpr uint32_t kClasses = 48;

    // Per-class admission allows one retire ring's worth of blocks. The total byte ceiling is
    // ring capacity times the string embed threshold: 4096 * 192 = 768 KiB per owner cache. It is
    // an aggregate admission bound, not a claim that every eligible block is at most 192 bytes.
    // The store passes this bound for a nonempty shard, or zero for an empty shard. A tiny keyspace
    // may retain more cached bytes than its live objects; rejecting put does not trim residents.
    // Explicit release paths return those blocks to the allocator.
    static constexpr uint32_t kMaxNodesPerClass = kReadLocalRetireRingCapacity;
    static constexpr size_t kMaxBytes =
        static_cast<size_t>(kReadLocalRetireRingCapacity) * kEmbedThreshold;

    static bool eligible(size_t allocation) { return allocation >= sizeof(FreeBlock); }

#ifdef TOMO_RL_CACHE_DEBUG
    // DEBUG-BUILD INVARIANTS (not compiled into the shipped binary).
    //
    // The two laws this cache rests on are (1) it is owner-private -- one thread, no lock -- and
    // (2) a block is resident exactly once. Both are violated silently: a cross-thread splice or a
    // double return corrupts the list, and the damage only surfaces at some LATER take() as a wild
    // head. These checks name the violation at the instant it happens, with the block address and
    // both thread ids, instead of leaving a segfault three hundred operations downstream.
    long dbg_owner_tid = 0;
    std::unordered_set<void*> dbg_resident;

    // `fatal` is false for release_all only: the graceful-shutdown path legitimately drains every
    // owner's queue from the main thread AFTER pool.join(), so that one crossing is single-threaded
    // by construction. It is still reported because the same entry point is reachable from
    // FLUSH and from maxmemory pressure, where a crossing would NOT be benign.
    void dbg_check_owner(const char* op, bool fatal = true) {
        const long tid = static_cast<long>(::syscall(SYS_gettid));
        if (!dbg_owner_tid) {
            dbg_owner_tid = tid;
            return;
        }
        if (dbg_owner_tid != tid) {
            std::fprintf(stderr, "\nRLCACHE-%s owner: %s on cache %p from tid %ld, owner tid %ld\n",
                         fatal ? "VIOLATION" : "CROSSING", op, static_cast<void*>(this), tid,
                         dbg_owner_tid);
            std::fflush(stderr);
            if (fatal) std::abort();
        }
    }
    void dbg_enter(void* memory, size_t allocation, uint32_t cls) {
        if (!dbg_resident.insert(memory).second) {
            std::fprintf(stderr,
                         "\nRLCACHE-VIOLATION double-put: block %p allocation %zu class %u already "
                         "resident (cache %p, class_nodes %u, bytes %zu)\n",
                         memory, allocation, cls, static_cast<void*>(this), class_nodes[cls],
                         bytes.load(std::memory_order_relaxed));
            std::fflush(stderr);
            std::abort();
        }
    }
    void dbg_leave(void* memory, size_t allocation, uint32_t cls) {
        if (dbg_resident.erase(memory) != 1) {
            std::fprintf(
                stderr,
                "\nRLCACHE-VIOLATION take-of-nonresident: block %p allocation %zu class %u "
                "(cache %p, class_nodes %u, bytes %zu)\n",
                memory, allocation, cls, static_cast<void*>(this), class_nodes[cls],
                bytes.load(std::memory_order_relaxed));
            std::fflush(stderr);
            std::abort();
        }
    }
    // The list a class actually holds must match its counter, and every block on it must carry
    // the class's own request size. A clobbered `next` is caught HERE, on the operation after the
    // write that clobbered it, rather than when it is finally dereferenced.
    uint64_t dbg_walk_countdown = 0;
    // Sample the O(list length) walk once per 1024 calls to limit diagnostic interference with
    // reclamation timing. O(1) residency checks remain on each operation.
    void dbg_walk(uint32_t cls, size_t allocation, const char* op) {
        if (dbg_walk_countdown--) return;
        dbg_walk_countdown = 1023;
        uint32_t seen = 0;
        for (FreeBlock* b = heads[cls]; b; b = b->next) {
            if (!dbg_resident.count(b)) {
                std::fprintf(stderr,
                             "\nRLCACHE-VIOLATION %s: class %u list holds non-resident block %p at "
                             "depth %u (cache %p)\n",
                             op, cls, static_cast<void*>(b), seen, static_cast<void*>(this));
                std::fflush(stderr);
                std::abort();
            }
            if (b->allocation != allocation) {
                std::fprintf(
                    stderr,
                    "\nRLCACHE-VIOLATION %s: class %u block %p carries allocation %zu, class "
                    "size %zu, depth %u (cache %p)\n",
                    op, cls, static_cast<void*>(b), b->allocation, allocation, seen,
                    static_cast<void*>(this));
                std::fflush(stderr);
                std::abort();
            }
            if (++seen > class_nodes[cls]) {
                std::fprintf(stderr,
                             "\nRLCACHE-VIOLATION %s: class %u list longer than its counter %u "
                             "(cycle or lost update; cache %p)\n",
                             op, cls, class_nodes[cls], static_cast<void*>(this));
                std::fflush(stderr);
                std::abort();
            }
        }
        if (seen != class_nodes[cls]) {
            std::fprintf(
                stderr,
                "\nRLCACHE-VIOLATION %s: class %u list length %u != counter %u (cache %p)\n", op,
                cls, seen, class_nodes[cls], static_cast<void*>(this));
            std::fflush(stderr);
            std::abort();
        }
    }
#endif

    // `allocation` is already good_size()-rounded by the caller, so the class identifies exactly
    // one request size and the returned block needs no header decode. Returns null on a miss; the
    // caller can then allocate through alloc_raw.
    void* take(size_t allocation) {
        const uint32_t cls = kv_block_class(allocation);
        if (cls >= kClasses) return nullptr;
#ifdef TOMO_RL_CACHE_DEBUG
        dbg_check_owner("take");
        dbg_walk(cls, allocation, "take-entry");
#endif
        FreeBlock* block = heads[cls];
        if (!block) return nullptr;
        const size_t cached_bytes = bytes.load(std::memory_order_relaxed);
        if (block->allocation != allocation || !class_nodes[cls] || cached_bytes < allocation)
            std::abort();
#ifdef TOMO_RL_CACHE_DEBUG
        dbg_leave(block, allocation, cls);
#endif
        heads[cls] = block->next;
        class_nodes[cls]--;
        bytes.store(cached_bytes - allocation, std::memory_order_relaxed);
        return block;
    }

    // Post-grace return. `ceiling` is the caller's own admission clause (see kMaxBytes above);
    // false leaves ownership with the caller, which must free or otherwise retain the block.
    bool put(void* memory, size_t allocation, size_t ceiling) {
        if (!eligible(allocation)) return false;
        const uint32_t cls = kv_block_class(allocation);
        if (cls >= kClasses || class_nodes[cls] == kMaxNodesPerClass) return false;
        const size_t limit = ceiling < kMaxBytes ? ceiling : kMaxBytes;
        const size_t cached_bytes = bytes.load(std::memory_order_relaxed);
        if (allocation > limit - (cached_bytes < limit ? cached_bytes : limit)) return false;
        // An immediate double-return would splice the list into a self-loop, which take() would
        // notice later when class_nodes reaches zero with a non-null head. Detect that duplicate
        // immediately on reclamation, before writing the intrusive node.
        if (heads[cls] == memory) std::abort();
#ifdef TOMO_RL_CACHE_DEBUG
        dbg_check_owner("put");
        dbg_walk(cls, allocation, "put-entry");
        dbg_enter(memory, allocation, cls);
#endif
        auto* block = reinterpret_cast<FreeBlock*>(memory);
        block->next = heads[cls];
        block->allocation = allocation;
        heads[cls] = block;
        class_nodes[cls]++;
        bytes.store(cached_bytes + allocation, std::memory_order_relaxed);
        return true;
    }

    // Return all cached blocks on the physical owner, or during teardown after workers join.
    void release_all() {
#ifdef TOMO_RL_CACHE_DEBUG
        dbg_check_owner("release_all", false);
#endif
        if (!bytes.load(std::memory_order_relaxed)) return;
        for (uint32_t cls = 0; cls < kClasses; cls++) {
            while (FreeBlock* block = heads[cls]) {
                heads[cls] = block->next;
#ifdef TOMO_RL_CACHE_DEBUG
                dbg_leave(block, block->allocation, cls);
#endif
                free_sized(block, block->allocation);
            }
            class_nodes[cls] = 0;
        }
        bytes.store(0, std::memory_order_relaxed);
    }

    FreeBlock* heads[kClasses] = {};
    uint32_t class_nodes[kClasses] = {};
    // Only the owner writes; INFO may sample concurrently. No atomic RMW is needed.
    std::atomic<size_t> bytes{0};
};

}  // namespace tomo
