// EXEC refinement telemetry. Owner-written, read only after worker join.
// Keep cold observations outside all footprint-locked hot structures.
#pragma once
#include <array>
#include <atomic>
#include <cstdint>
#include <cstdio>
namespace tomo {
struct alignas(64) Exec1sCounters {
    uint64_t clients_live = 0, clients_peak = 0;
    uint64_t io_enters = 0, ex_enters = 0;
    uint64_t io_waits = 0, ex_waits = 0;
    uint64_t owner_passes = 0, extra_passes = 0;
    uint64_t eager_collapses = 0, wb_exec_holds = 0;
    uint64_t blind_clear = 0, record_visits = 0;
};
inline std::array<Exec1sCounters, 128> exec1s_counters{};
// Scheduling hints contain no shard/client pointer and survive ownership moves
// harmlessly. The ordinary pass remains the liveness backstop.
struct alignas(64) FusedOwnerBell { std::atomic<bool> runnable{false}; };
inline std::array<FusedOwnerBell, 128> fused_owner_bells{};
// Each ring has one issuer. Adjacent thread IDs must not share counter lines.
struct alignas(64) Exec1sRingCounters { uint64_t enters = 0, waits = 0; };
inline std::array<Exec1sRingCounters, 256> exec1s_ring_counters{};
inline void exec1s_print(const Exec1sCounters& c, bool json) {
    if (json) std::printf("\"exec1s\":{");
    else std::printf("exec1s ");
#define TOMO_EXEC1S_FIELD(field, label) \
    std::printf(json ? "\"" label "\":%llu," : label "=%llu ", \
                static_cast<unsigned long long>(c.field))
    TOMO_EXEC1S_FIELD(clients_live, "clients_live"); TOMO_EXEC1S_FIELD(clients_peak, "clients_peak");
    TOMO_EXEC1S_FIELD(io_enters, "io_enters"); TOMO_EXEC1S_FIELD(ex_enters, "ex_enters");
    TOMO_EXEC1S_FIELD(io_waits, "io_waits"); TOMO_EXEC1S_FIELD(ex_waits, "ex_waits");
    TOMO_EXEC1S_FIELD(owner_passes, "owner_passes"); TOMO_EXEC1S_FIELD(extra_passes, "extra_passes");
    TOMO_EXEC1S_FIELD(eager_collapses, "eager_collapses"); TOMO_EXEC1S_FIELD(wb_exec_holds, "wb_exec_holds");
    TOMO_EXEC1S_FIELD(blind_clear, "blind_clear");
#undef TOMO_EXEC1S_FIELD
    std::printf(json ? "\"record_visits\":%llu}," : "record_visits=%llu\n",
                static_cast<unsigned long long>(c.record_visits));
}
#ifdef TOMO_EXEC1S_DEBUG
inline thread_local Exec1sCounters* exec1s_debug_counter = nullptr;
struct Exec1sVisitScope {
    Exec1sCounters* old = exec1s_debug_counter;
    explicit Exec1sVisitScope(uint32_t tid) { exec1s_debug_counter = &exec1s_counters[tid]; }
    ~Exec1sVisitScope() { exec1s_debug_counter = old; }
};
#define TOMO_EXEC1S_VISIT() do { if (::tomo::exec1s_debug_counter) \
    ++::tomo::exec1s_debug_counter->record_visits; } while (0)
#else
#define TOMO_EXEC1S_VISIT() ((void)0)
#endif
} // namespace tomo
