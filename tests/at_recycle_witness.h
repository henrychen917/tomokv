// UNScored only. tools/at_recycle_artifacts.py injects this into a build/ source mirror.
// Production sources/binaries do not include this file, allocate these counters or sample them.
#pragma once
#define TOMO_AT_RECYCLE_WITNESS_ENABLED
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <sys/syscall.h>
#include <unistd.h>
namespace at_recycle {
inline std::atomic<unsigned> request{0};
static_assert(std::atomic<unsigned>::is_always_lock_free);
struct Allocations { uint64_t mallocx = 0, sdallocx = 0; };
inline thread_local Allocations allocations;
struct Counters {
    uint64_t takes = 0, hits = 0, misses = 0, outside_takes = 0, admitted = 0;
    uint64_t collection = 0, encoding = 0, borrowed = 0;
    uint64_t undersize = 0, outside_classes = 0, class_full = 0, empty = 0, bytes_full = 0;
    uint64_t fresh = 0, fresh_failed = 0;
    unsigned last_request = 0;
    template<class Cache> void dump(const Cache& cache, const char* event) {
        const auto alloc = allocations;
        // One complete line per cache. Only the owner (or main after pool.join) reads the lists.
        flockfile(stderr);
        std::fprintf(stderr, "AT_RECYCLE {\"event\":\"%s\",\"ticket\":%u,\"tid\":%ld,\"cache\":\"%p\","
          "\"takes\":%llu,\"hits\":%llu,\"misses\":%llu,\"outside_takes\":%llu,\"admitted\":%llu,"
          "\"collection\":%llu,\"encoding\":%llu,\"borrowed\":%llu,\"undersize\":%llu,"
          "\"outside_classes\":%llu,\"class_full\":%llu,\"empty\":%llu,\"bytes_full\":%llu,"
          "\"fresh\":%llu,\"fresh_failed\":%llu,\"thread_mallocx\":%llu,\"thread_sdallocx\":%llu,"
          "\"cache_bytes\":%zu,\"classes\":[",
          event, last_request, static_cast<long>(syscall(SYS_gettid)), static_cast<const void*>(&cache),
          (unsigned long long)takes, (unsigned long long)hits, (unsigned long long)misses,
          (unsigned long long)outside_takes,
          (unsigned long long)admitted, (unsigned long long)collection, (unsigned long long)encoding,
          (unsigned long long)borrowed, (unsigned long long)undersize, (unsigned long long)outside_classes,
          (unsigned long long)class_full, (unsigned long long)empty, (unsigned long long)bytes_full,
          (unsigned long long)fresh, (unsigned long long)fresh_failed,
          (unsigned long long)alloc.mallocx, (unsigned long long)alloc.sdallocx, cache.bytes);
        for (unsigned cls = 0; cls < Cache::kClasses; ++cls) {
            size_t bytes = 0;
            for (auto* b = cache.heads[cls]; b; b = b->next) bytes += b->allocation;
            std::fprintf(stderr, "%s[%u,%u,%zu]", cls ? "," : "", cls, cache.class_nodes[cls], bytes);
        }
        std::fputs("]}\n", stderr); funlockfile(stderr);
    }
    template<class Cache> void observe(const Cache& cache) {
        const auto ticket = request.load(std::memory_order_acquire);
        if (ticket == last_request) return;
        last_request = ticket; dump(cache, "owner-boundary");
    }
};
}
