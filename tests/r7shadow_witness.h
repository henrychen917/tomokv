// Force-included only in the instrumented serverless test and its reorder TU.
// No production object includes this file. No tracking allocation of its own.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <new>

namespace r7_witness {
inline uint64_t paths = 0, allocations = 0;
inline uint64_t heap_calls = 0, heap_bytes = 0, heap_trace = 14695981039346656037ull;
inline bool track_heap = false;
inline void allocation(size_t n, size_t alignment) {
    if (!track_heap) return;
    ++heap_calls;
    heap_bytes += n;
    heap_trace = ((heap_trace ^ n) * 1099511628211ull ^ alignment) * 1099511628211ull;
}
}
#define TOMO_R7_PATH() (++::r7_witness::paths)
#define TOMO_R7_ALLOC() (++::r7_witness::allocations)

#ifdef TOMO_R7_WITNESS_MAIN
void* operator new(size_t n) {
    r7_witness::allocation(n, 0);
    if (void* p = std::malloc(n ? n : 1)) return p;
    throw std::bad_alloc();
}
void* operator new[](size_t n) { return ::operator new(n); }
void* operator new(size_t n, std::align_val_t alignment) {
    const size_t a = static_cast<size_t>(alignment);
    r7_witness::allocation(n, a);
    void* p = nullptr;
    if (posix_memalign(&p, a, n ? n : 1) == 0) return p;
    throw std::bad_alloc();
}
void* operator new[](size_t n, std::align_val_t a) { return ::operator new(n, a); }
void* operator new(size_t n, const std::nothrow_t&) noexcept {
    try { return ::operator new(n); } catch (...) { return nullptr; }
}
void* operator new[](size_t n, const std::nothrow_t& t) noexcept { return ::operator new(n, t); }
void* operator new(size_t n, std::align_val_t a, const std::nothrow_t&) noexcept {
    try { return ::operator new(n, a); } catch (...) { return nullptr; }
}
void* operator new[](size_t n, std::align_val_t a, const std::nothrow_t& t) noexcept {
    return ::operator new(n, a, t);
}
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, size_t) noexcept { std::free(p); }
void operator delete[](void* p, size_t) noexcept { std::free(p); }
void operator delete(void* p, std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p, std::align_val_t) noexcept { std::free(p); }
void operator delete(void* p, size_t, std::align_val_t) noexcept { std::free(p); }
void operator delete[](void* p, size_t, std::align_val_t) noexcept { std::free(p); }
void operator delete(void* p, const std::nothrow_t&) noexcept { std::free(p); }
void operator delete[](void* p, const std::nothrow_t&) noexcept { std::free(p); }
void operator delete(void* p, std::align_val_t, const std::nothrow_t&) noexcept { std::free(p); }
void operator delete[](void* p, std::align_val_t, const std::nothrow_t&) noexcept { std::free(p); }
#endif
