// alloc.h — allocation, sized deallocation and per-thread jemalloc arena binding.
// Included by store/object headers, read-local reclamation, worker startup and INFO code;
// no translation-unit-specific include point is required.
// Callers own returned blocks and provide the matching request size when freeing them.
//
// Exposing allocator size classes lets callers reuse capacity without storing it in each object.
// The helpers provide allocator access; object pools and reclamation belong to their callers.
//
// THE THREE JEMALLOC CALLS THAT MATTER
//
//   nallocx(n)          the size class n WILL land in, computed WITHOUT allocating.
//   mallocx(n, flags)   allocate with arena/tcache control.
//   sdallocx(p, n, f)   SIZED free. Ordinary free() must first look up how big the block was;
//                       sdallocx is told, so it skips that lookup entirely. Every KvObj free knows
//                       its own size, so the caller can supply it directly.
//
// WHY THE SIZE CLASS IS THE INTERESTING ONE. Asking for 88 bytes gets 96 — the extra 8 are already
// paid for. Exposing that turns "same-size overwrite" into "same-size-CLASS overwrite", which is a
// much wider fast path: a SET whose value grew by a few bytes still needs no allocation. And because
// good_size() is a pure deterministic function of the request, the capacity does not have to be
// STORED on the object; it is recomputed. That keeps KvObj's header at 8 bytes.
//
// Worker startup binds a thread-local arena. Allocation ownership is not enforced here: fused
// dispatch prebuilds large SET values for a foreign owner (l4prebuild.cc), and migration and
// post-join shutdown hand objects across threads. Those objects can be freed directly or through
// deferred reclamation on another thread. jemalloc supports remote frees; callers still enforce
// object lifetimes.
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
// Arithmetic avoids an allocator call for each KvObj capacity/accounting query. The size classes
// are 8, then multiples of 16 through 128, then four classes per power of two (including page
// groups). main checks 1..64 KiB against nallocx and refuses startup on a mismatch; that check does
// not establish agreement above its tested range. Inputs must leave room for rounding in size_t.
inline size_t good_size(size_t n) {
    if (n == 0) return 0;
    if (n <= 8) return 8;
    if (n <= 128) return (n + 15) & ~size_t(15);
    const int k = 63 - __builtin_clzll(static_cast<unsigned long long>(n - 1));  // floor(log2(n-1))
    const size_t step = size_t(1) << (k - 2);                                    // group / 4
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

// Sized free: n must match the allocation request, which KvObj callers already round to a class.
// jemalloc derives the class from n. Passing a size from a different class is invalid; derive it
// from the same layout/rounding calculation that reserved the block.
inline void free_sized(void* p, size_t n) {
    if (!p) return;
#if defined(TOMO_JEMALLOC)
    sdallocx(p, n, 0);
#else
    (void)n;
    std::free(p);
#endif
}

// ---- per-thread arena --------------------------------------------------------------------------
// Worker startup calls after pinning to bind the calling thread's arena. Returns false on either
// mallctl failure, or without jemalloc; it does not roll back an arena already created.
// Production callers ignore the result; failure only loses arena isolation.
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
