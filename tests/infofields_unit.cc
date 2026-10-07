// Serverless checks of the production cron arithmetic. No Server is constructed.
// Function sections let the linker discard boot/server collection entry points.
#include "../src/cmd/info_stats.cc"

#include <cassert>
#include <cstdio>

int main() {
    using namespace tomo;
    constexpr uint64_t tick = 100000000;
    info_stats_reset(0, 12);
    g_info_stats.last_sample_ns = 1000000000;
    uint64_t now = g_info_stats.last_sample_ns;
    std::array<uint64_t, 3> totals{};
    for (unsigned i = 1; i <= 16; ++i) {
        now += tick;
        totals[0] += 100;
        totals[1] += 2048;
        totals[2] += 4096;
        sample(now, totals, 4096);
        const auto rates = info_stats_rates();
        assert(rates[0] == 1000 * i / 16);
        assert(rates[1] == 20480 * i / 16);
        assert(rates[2] == 40960 * i / 16);
    }
    const auto samples = g_info_stats.samples;
    const auto last = g_info_stats.last_sample_ns;
    for (unsigned i = 0; i < 100; ++i) {
        assert(info_stats_rates()[0] == 1000);
        assert(g_info_stats.samples == samples);
        assert(g_info_stats.last_sample_ns == last);
    }
    for (unsigned i = 1; i <= 16; ++i) {
        sample(now += tick, totals, 12);
        assert(info_stats_rates()[0] == 1000 * (16 - i) / 16);
    }
    assert(info_stats_observe_memory(12) == 4096);
    info_stats_reset(totals[0], 12, totals[1], totals[2]);
    assert((info_stats_rates() == std::array<uint64_t, 3>{}));
    assert(info_stats_observe_memory(12) == 12);
    sample(g_info_stats.last_sample_ns + tick, totals, 12);
    assert(info_stats_rates()[0] == 0);
    // Counter reset/wrap cannot underflow into a giant reported rate.
    sample(g_info_stats.last_sample_ns + tick, {}, 12);
    assert((info_stats_rates() == std::array<uint64_t, 3>{}));
    // Actual elapsed time, not an assumed 100 ms, determines a delayed sample.
    sample(g_info_stats.last_sample_ns + 2 * tick, {200, 0, 0}, 12);
    assert(info_stats_rates()[0] == 62);
    std::puts("INFOFIELDS cron arithmetic: PASS (warm-up, decay, read-only INFO, peak, reset, elapsed)");
}
