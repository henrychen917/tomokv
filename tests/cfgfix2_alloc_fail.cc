// cfgfix2 SO5.1 witness: fail one ObjectIdleClock allocation on one owner of several.
//
// Test-only LD_PRELOAD object; the production executable is unchanged. It interposes the
// nothrow operator new that ObjectIdleClock uses and counts only calls whose return address
// lies in the clock construction functions (CFGFIX2_FAIL_RANGES, load-relative hex ranges).
// While the marker file CFGFIX2_FAIL_ARM exists, the third such call on the owner pinned to
// CFGFIX2_FAIL_CPU returns nullptr, after CFGFIX2_FAIL_OWNERS owners (that one included) have
// each made at least three: the other owners hold partial or complete clocks at that moment.
// A missed window is a failure (exit 92), never a skip. Every clock allocation and its release
// are appended to CFGFIX2_FAIL_RECEIPT, so the test can prove each one was undone.
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <link.h>
#include <new>
#include <sched.h>
#include <time.h>
#include <unistd.h>

namespace {
struct Range { uintptr_t first, last; };
Range ranges[16];
unsigned range_count;
uintptr_t base;
int receipt = -1, target = -1, owners = 0;
const char* marker;
bool ready;
std::atomic<unsigned> calls[CPU_SETSIZE];
std::atomic<bool> fired{false};
std::atomic_flag table_lock = ATOMIC_FLAG_INIT;
constexpr unsigned kTracked = 1u << 20;
void* tracked[kTracked];
unsigned used;
std::atomic<unsigned> live{0};  // tracked count; frees skip the table while it is zero

void event(char kind, const void* p, int cpu, unsigned long detail) {
    char line[96];
    const int n = std::snprintf(line, sizeof(line), "%c %p %d %lu\n", kind, p, cpu, detail);
    if (::write(receipt, line, n) != n) ::_exit(96);
}

bool selected(uintptr_t pc) {
    if (!ready || ::access(marker, F_OK)) return false;
    pc -= base;
    for (unsigned i = 0; i < range_count; ++i)
        if (pc >= ranges[i].first && pc < ranges[i].last) return true;
    return false;
}

void untrack(void* p) {
    if (!ready || !p || !live.load(std::memory_order_acquire)) return;
    while (table_lock.test_and_set(std::memory_order_acquire)) {}
    for (unsigned i = 0; i < used; ++i)
        if (tracked[i] == p) {
            tracked[i] = tracked[--used];
            live.store(used, std::memory_order_release);
            event('-', p, ::sched_getcpu(), 0);
            break;
        }
    table_lock.clear(std::memory_order_release);
}

__attribute__((constructor)) void initialize() {
    marker = std::getenv("CFGFIX2_FAIL_ARM");
    const char* path = std::getenv("CFGFIX2_FAIL_RECEIPT");
    const char* spec = std::getenv("CFGFIX2_FAIL_RANGES");
    const char* cpu = std::getenv("CFGFIX2_FAIL_CPU");
    const char* count = std::getenv("CFGFIX2_FAIL_OWNERS");
    if (!marker || !path || !spec || !cpu || !count) ::_exit(95);
    target = std::atoi(cpu);
    owners = std::atoi(count);
    while (*spec) {
        if (range_count == 16) ::_exit(94);
        char* end = nullptr;
        ranges[range_count].first = std::strtoull(spec, &end, 16);
        if (*end != '-') ::_exit(94);
        ranges[range_count++].last = std::strtoull(end + 1, &end, 16);
        spec = *end == ',' ? end + 1 : end;
    }
    dl_iterate_phdr([](dl_phdr_info* info, size_t, void*) {
        if (!info->dlpi_name[0]) { base = info->dlpi_addr; return 1; }
        return 0;
    }, nullptr);
    receipt = ::open(path, O_CREAT | O_APPEND | O_WRONLY | O_CLOEXEC, 0600);
    if (receipt < 0 || target < 0 || owners < 1) ::_exit(93);
    ready = true;
}
}  // namespace

void* operator new(std::size_t size, const std::nothrow_t&) noexcept {
    const auto pc = reinterpret_cast<uintptr_t>(__builtin_return_address(0));
    if (!selected(pc)) return std::malloc(size);
    const int cpu = ::sched_getcpu();
    const unsigned call = calls[cpu].fetch_add(1) + 1;
    if (cpu == target && call == 3 && !fired.exchange(true)) {
        unsigned seen = 0;
        for (unsigned attempt = 0; attempt < 5000; ++attempt) {
            seen = 0;
            for (auto& c : calls) seen += c.load() >= 3;
            if (seen >= static_cast<unsigned>(owners)) break;
            const timespec delay{0, 1000000};
            ::nanosleep(&delay, nullptr);
        }
        if (seen < static_cast<unsigned>(owners)) { event('!', nullptr, cpu, seen); ::_exit(92); }
        event('F', reinterpret_cast<void*>(pc - base), cpu, seen);
        return nullptr;
    }
    void* p = std::malloc(size);
    if (!p) return nullptr;
    while (table_lock.test_and_set(std::memory_order_acquire)) {}
    if (used == kTracked) ::_exit(91);
    tracked[used++] = p;
    live.store(used, std::memory_order_release);
    event('+', p, cpu, size);
    table_lock.clear(std::memory_order_release);
    return p;
}

void operator delete(void* p) noexcept { untrack(p); std::free(p); }
void operator delete(void* p, std::size_t) noexcept { untrack(p); std::free(p); }
