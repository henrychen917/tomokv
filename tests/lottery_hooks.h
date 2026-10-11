// Included ONLY by tools/lottery_build.py's copied witness tree.
// No holds, sleeps, clock changes, release gates, or production layout additions.
#pragma once
#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <ctime>
#include <fcntl.h>
#include <mutex>
#include <set>
#include <string>
#include <unistd.h>
#include <vector>

// Deliberately outside namespace tomo: the -Dtomo=tomo_db0 objects share one arm.
namespace lottery {
struct Record { const char* kind; uint64_t id, a, b, c, d, ns, ms, seq; };

inline std::atomic<uint64_t> armed{0};
// Call-site order. The reducer orders records by this stamp, taken at the
// call site: a "before X" record stamps before X, an "after X" record after.
inline std::atomic<uint64_t> clock{0};
inline std::atomic<uint64_t> recorded{0};
inline std::atomic<uint64_t> writers{0};
inline std::atomic<bool> overflow{false};
// Registry, name interning and arm/stop only. Never taken on a recording
// path after a thread's first record: records go to that thread's buffer.
inline std::mutex mutex;
inline std::vector<std::vector<Record>*> buffers;
inline std::set<std::string> names;
inline FILE* output = nullptr;
inline uint64_t armed_mask = 0;
// Bounded diagnostic storage, not an oracle tolerance. Overflow invalidates the attempt.
inline constexpr uint64_t max_events = 4000000;

inline constexpr uint64_t bit(unsigned w) { return uint64_t{1} << w; }
inline bool enabled(uint64_t mask) { return armed.load(std::memory_order_relaxed) & mask; }
inline uint64_t ptr(const void* p) { return reinterpret_cast<uintptr_t>(p); }
inline uint64_t stamp() { return clock.fetch_add(1, std::memory_order_seq_cst) + 1; }

inline std::vector<Record>& local() {
    thread_local std::vector<Record>* mine = nullptr;
    if (!mine) {
        mine = new std::vector<Record>();  // server threads are long-lived; never freed
        std::lock_guard<std::mutex> lock(mutex);
        buffers.push_back(mine);
    }
    return *mine;
}

inline void event(uint64_t mask, const char* kind, uint64_t id=0, uint64_t a=0,
                  uint64_t b=0, uint64_t c=0, uint64_t d=0) {
    if (!enabled(mask)) return;
    // Announce, then re-check: stop() disarms first and waits for announced writers.
    writers.fetch_add(1, std::memory_order_seq_cst);
    if (armed.load(std::memory_order_seq_cst) & mask) {
        const uint64_t at = stamp();
        if (recorded.fetch_add(1, std::memory_order_relaxed) >= max_events) {
            overflow.store(true, std::memory_order_relaxed);
        } else {
            timespec now{};
            clock_gettime(CLOCK_MONOTONIC, &now);
            const uint64_t ns = uint64_t(now.tv_sec)*1000000000 + now.tv_nsec;
            clock_gettime(CLOCK_REALTIME, &now);
            const uint64_t ms = uint64_t(now.tv_sec)*1000 + now.tv_nsec/1000000;
            local().push_back(Record{kind, id, a, b, c, d, ns, ms, at});
        }
    }
    writers.fetch_sub(1, std::memory_order_seq_cst);
}

inline void mark(const std::string& name) {
    const char* kind;
    {
        std::lock_guard<std::mutex> lock(mutex);
        kind = names.insert(name).first->c_str();  // node-stable for the process lifetime
    }
    event(~uint64_t{0}, kind);
}

inline bool start(uint64_t mask, const std::string& path) {
    std::lock_guard<std::mutex> lock(mutex);
    if (output || !mask || armed.load(std::memory_order_seq_cst)) return false;
    const int fd = ::open(path.c_str(), O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC, 0600);
    if (fd < 0) return false;
    output = ::fdopen(fd, "w");
    if (!output) { ::close(fd); return false; }
    for (auto* buffer : buffers) buffer->clear();
    clock.store(0, std::memory_order_seq_cst);
    recorded.store(0, std::memory_order_seq_cst);
    overflow.store(false, std::memory_order_seq_cst);
    armed_mask = mask;
    armed.store(mask, std::memory_order_seq_cst);
    return true;
}

// Disarm, wait out in-flight writers, then write every record in stamp order.
inline bool stop() {
    armed.store(0, std::memory_order_seq_cst);
    while (writers.load(std::memory_order_seq_cst) != 0) {}
    std::lock_guard<std::mutex> lock(mutex);
    if (!output) return false;
    std::vector<Record> all;
    size_t total = 0;
    for (auto* buffer : buffers) total += buffer->size();
    all.reserve(total);
    for (auto* buffer : buffers) {
        all.insert(all.end(), buffer->begin(), buffer->end());
        std::vector<Record>().swap(*buffer);
    }
    std::sort(all.begin(), all.end(),
              [](const Record& x, const Record& y) { return x.seq < y.seq; });
    bool ok = !overflow.load(std::memory_order_seq_cst);
    if (std::fprintf(output, "LOTTERY2 %d %llu\n", int(::getpid()),
                     (unsigned long long)armed_mask) < 0) ok = false;
    uint64_t sequence = 0;
    for (const Record& r : all)
        if (std::fprintf(output, "%llu %s %llu %llu %llu %llu %llu %llu %llu %llu\n",
                         (unsigned long long)++sequence, r.kind, (unsigned long long)r.id,
                         (unsigned long long)r.a, (unsigned long long)r.b,
                         (unsigned long long)r.c, (unsigned long long)r.d,
                         (unsigned long long)r.ns, (unsigned long long)r.ms,
                         (unsigned long long)r.seq) < 0) ok = false;
    if (std::ferror(output)) ok = false;
    if (std::fprintf(output, "END %llu %d\n", (unsigned long long)sequence, int(ok)) < 0)
        ok = false;
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
