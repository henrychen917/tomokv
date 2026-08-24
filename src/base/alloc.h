// alloc.h — the allocation layer. Thin on purpose.
//
// ALLOCATION COUNT IS THE LEVER, not allocator cleverness. A bespoke tiered size-class pool was
// built in the fork and DELETED: the measured win came from making fewer allocations, and the pool
// added machinery without adding that. Meanwhile jemalloc alone was the single largest lever
// measured on the fork at +30-54%. So this file does two things and nothing more: it uses jemalloc
// properly, and it exposes the size class so callers can avoid allocating at all.
//
// THE THREE JEMALLOC CALLS THAT MATTER
//
//   nallocx(n)          the size class n WILL land in, computed WITHOUT allocating.
//   mallocx(n, flags)   allocate with arena/tcache control.
//   sdallocx(p, n, f)   SIZED free. Ordinary free() must first look up how big the block was;
//                       sdallocx is told, so it skips that lookup entirely. Every KvObj free knows
//                       its own size, so this is free performance we would otherwise leave behind.
//
// WHY THE SIZE CLASS IS THE INTERESTING ONE. Asking for 88 bytes gets 96 — the extra 8 are already
// paid for. Exposing that turns "same-size overwrite" into "same-size-CLASS overwrite", which is a
// much wider fast path: a SET whose value grew by a few bytes still needs no allocation. And because
// good_size() is a pure deterministic function of the request, the capacity does not have to be
// STORED on the object; it is recomputed. That keeps KvObj's header at 8 bytes.
//
// PER-WORKER ARENAS. A shard is owned by one worker, values never cross threads, and the owner frees
// what it allocated — so each worker can have its own arena with no cross-thread free on the hot
// path. The one exception is shard migration, where the new owner eventually frees objects the old
// one allocated; jemalloc handles that correctly, just off its fastest path, and migrations are rare
// by design (they are priced, see shard.h).
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdlib>

#if defined(TOMO_JEMALLOC)
#include <jemalloc/jemalloc.h>
#endif

namespace tomo {

// ---- size classes --------------------------------------------------------------------------
// Must be DETERMINISTIC and identical for a given request everywhere in the process, because the
// capacity of a KvObj is recomputed from it rather than stored.
// PURE ARITHMETIC on every build. nallocx was 5.6% of SET-cell cycles: kvobj accounting calls
// good_size several times per op, and each was a PLT call into jemalloc. This closed-form is
// byte-identical to jemalloc's class table (8, 16-spaced to 128, then four classes per power of
// two, page-group rule included) for every size we ever request; boot verifies that claim against
// nallocx across 1..64KiB and refuses to start on the first mismatch (sanity-gate rule), so a
// jemalloc config change can never silently under-report capacity.
inline size_t good_size(size_t n) {
    if (n == 0) return 0;
    if (n <= 8) return 8;
    if (n <= 128) return (n + 15) & ~size_t(15);
    const int k = 63 - __builtin_clzll(static_cast<unsigned long long>(n - 1));   // floor(log2(n-1))
    const size_t step = size_t(1) << (k - 2);                                     // group / 4
    return (n + step - 1) & ~(step - 1);
}

#if defined(TOMO_JEMALLOC)
inline bool good_size_matches_allocator(size_t upto = 65536) {
    for (size_t n = 1; n <= upto; n++)
        if (good_size(n) != nallocx(n, 0)) return false;
    return true;
}
#else
inline bool good_size_matches_allocator(size_t = 65536) { return true; }
#endif

// ---- allocate / free -------------------------------------------------------------------------
inline void* alloc_raw(size_t n) {
#if defined(TOMO_JEMALLOC)
    return n ? mallocx(n, 0) : nullptr;
#else
    return std::malloc(n);
#endif
}

// SIZED free. `n` must be the size that was REQUESTED (not the rounded class) — jemalloc derives the
// class itself. Passing a wrong size is undefined behaviour, which is why every caller here derives
// it from the same function that built the object.
inline void free_sized(void* p, size_t n) {
    if (!p) return;
#if defined(TOMO_JEMALLOC)
    sdallocx(p, n, 0);
#else
    (void)n;
    std::free(p);
#endif
}

inline void free_raw(void* p) {
    if (!p) return;
#if defined(TOMO_JEMALLOC)
    dallocx(p, 0);
#else
    std::free(p);
#endif
}

// ---- per-thread arena --------------------------------------------------------------------------
// Called once by each worker after pinning. Without jemalloc this is a no-op and everything still
// works, just without arena isolation.
inline bool bind_thread_arena() {
#if defined(TOMO_JEMALLOC)
    unsigned arena = 0;
    size_t sz = sizeof(arena);
    if (mallctl("arenas.create", &arena, &sz, nullptr, 0) != 0) return false;
    if (mallctl("thread.arena", nullptr, nullptr, &arena, sizeof(arena)) != 0) return false;
    return true;
#else
    return false;
#endif
}

inline const char* alloc_backend() {
#if defined(TOMO_JEMALLOC)
    return "jemalloc";
#else
    return "libc-malloc";
#endif
}

}  // namespace tomo
