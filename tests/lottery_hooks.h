// Included ONLY by tools/lottery_build.py's copied witness tree.
// No holds, sleeps, clock changes, release gates, or production layout additions.
#pragma once
#include <atomic>
#include <cstdio>
#include <cstdint>
#include <mutex>
#include <string>
#include <ctime>
#include <unistd.h>
#include <fcntl.h>

namespace tomo::lottery {
inline std::atomic<uint64_t> armed{0};
// Call-site order. Records are written in mutex order, which can lag the
// observed action; the reducer orders by this stamp, taken at the call site
// before the mutex: a "before X" event stamps before X, an "after X" one after.
inline std::atomic<uint64_t> clock{0};
inline uint64_t stamp() { return clock.fetch_add(1, std::memory_order_seq_cst) + 1; }
inline std::mutex mutex;
inline FILE* output = nullptr;
inline uint64_t sequence = 0;
inline bool overflow = false;
// Bounded diagnostic storage, not an oracle tolerance. Overflow invalidates the attempt.
inline constexpr uint64_t max_events = 4000000;
inline constexpr uint64_t bit(unsigned w) { return uint64_t{1} << w; }
inline bool enabled(uint64_t mask) { return armed.load(std::memory_order_relaxed) & mask; }
inline uint64_t ptr(const void* p) { return reinterpret_cast<uintptr_t>(p); }

inline void event(uint64_t mask, const char* kind, uint64_t id=0, uint64_t a=0,
                  uint64_t b=0, uint64_t c=0, uint64_t d=0) {
    if (!enabled(mask)) return;
    const uint64_t at = stamp();
    std::lock_guard<std::mutex> lock(mutex);
    if (!output || !enabled(mask)) return;
    if (sequence == max_events) { overflow = true; return; }
    timespec now{};
    clock_gettime(CLOCK_MONOTONIC, &now);
    const uint64_t ns = uint64_t(now.tv_sec)*1000000000 + now.tv_nsec;
    clock_gettime(CLOCK_REALTIME, &now);
    const uint64_t ms = uint64_t(now.tv_sec)*1000 + now.tv_nsec/1000000;
    if (std::fprintf(output, "%llu %s %llu %llu %llu %llu %llu %llu %llu %llu\n",
                     (unsigned long long)++sequence, kind, (unsigned long long)id,
                     (unsigned long long)a, (unsigned long long)b, (unsigned long long)c,
                     (unsigned long long)d, (unsigned long long)ns,
                     (unsigned long long)ms, (unsigned long long)at) < 0) overflow = true;
}

inline bool start(uint64_t mask, const std::string& path) {
    std::lock_guard<std::mutex> lock(mutex);
    if (output || !mask) return false;
    const int fd = ::open(path.c_str(), O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC, 0600);
    if (fd < 0) return false;
    output = ::fdopen(fd, "w");
    if (!output) { ::close(fd); return false; }
    sequence = 0; overflow = false;
    std::fprintf(output, "LOTTERY2 %d %llu\n", int(::getpid()), (unsigned long long)mask);
    armed.store(mask, std::memory_order_release);
    return true;
}

inline bool stop() {
    std::lock_guard<std::mutex> lock(mutex);
    armed.store(0, std::memory_order_release);
    if (!output) return false;
    bool ok = !overflow && !std::ferror(output);
    if (std::fprintf(output, "END %llu %d\n", (unsigned long long)sequence,
                     int(ok)) < 0) ok = false;
    if (std::fclose(output)) ok = false;
    output = nullptr;
    return ok;
}

struct Scope {
    uint64_t mask; const char* end; uint64_t id, a;
    Scope(uint64_t m, const char* begin, const char* finish, uint64_t i,
          uint64_t x=0, uint64_t y=0, uint64_t z=0, uint64_t w=0)
        : mask(m), end(finish), id(i), a(x) { event(m, begin, i, x, y, z, w); }
    ~Scope() { event(mask, end, id, a); }
};
}
