#include "info_stats.h"

#include "../core/server.h"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <mutex>
#include <string>
#include <sys/random.h>
#include <unistd.h>

namespace tomo {
namespace {

constexpr size_t kSampleWindow = 16;

struct InfoStatsState {
    std::mutex mu;
    uint64_t last_sample_ns = 0;
    std::array<uint64_t, 3> last{};
    std::array<std::array<uint64_t, kSampleWindow>, 3> samples{};
    std::array<uint64_t, 3> rates{};
    uint64_t memory_peak = 0;
    size_t cursor = 0;
};

InfoStatsState g_info_stats;
std::array<char, 41> g_run_id{};
std::string g_executable;
std::string g_config_file;

uint64_t used_memory(Server& server) {
    uint64_t objects = 0, keys = 0;
    for (uint32_t i = 0; i < server.nshards(); ++i) {
        const Shard& shard = server.shard(static_cast<int32_t>(i));
        objects += shard.published_obj_bytes();
        keys += shard.published_size();
    }
    constexpr uint64_t overhead = FlatStore::kSlotOverheadPerKey;
    if (keys > (std::numeric_limits<uint64_t>::max() - objects) / overhead)
        return std::numeric_limits<uint64_t>::max();
    return objects + keys * overhead;
}

// Called with the cold mutex held. Startup/reset retain all sixteen zero slots,
// so the arithmetic mean has Redis's warm-up and decay, independent of INFO polls.
void sample(uint64_t sampled_ns, const std::array<uint64_t, 3>& totals, uint64_t memory) {
    const uint64_t elapsed = sampled_ns - g_info_stats.last_sample_ns;
    if (!elapsed) return;
    for (size_t metric = 0; metric < totals.size(); ++metric) {
        const uint64_t delta = totals[metric] >= g_info_stats.last[metric]
            ? totals[metric] - g_info_stats.last[metric] : 0;
        auto& samples = g_info_stats.samples[metric];
        samples[g_info_stats.cursor] = static_cast<uint64_t>(
            (static_cast<unsigned __int128>(delta) * 1000000000ull) / elapsed);
        unsigned __int128 sum = 0;
        for (uint64_t value : samples) sum += value;
        g_info_stats.rates[metric] = static_cast<uint64_t>(sum / kSampleWindow);
    }
    g_info_stats.cursor = (g_info_stats.cursor + 1) % kSampleWindow;
    g_info_stats.last_sample_ns = sampled_ns;
    g_info_stats.last = totals;
    g_info_stats.memory_peak = std::max(g_info_stats.memory_peak, memory);
}

}  // namespace

void info_stats_init(Server* server) {
    // command_bind_server runs once, before workers start. RESETSTAT must never
    // change identity, even when the server was booted without a configuration file.
    if (!g_run_id[0]) {
        std::array<unsigned char, 20> random{};
        size_t filled = 0;
        while (filled < random.size()) {
            const ssize_t count = ::getrandom(random.data() + filled, random.size() - filled, 0);
            if (count < 0 && errno == EINTR) continue;
            if (count <= 0) { std::perror("INFO run_id getrandom"); std::abort(); }
            filled += static_cast<size_t>(count);
        }
        constexpr char hex[] = "0123456789abcdef";
        for (size_t i = 0; i < random.size(); ++i) {
            g_run_id[i * 2] = hex[random[i] >> 4];
            g_run_id[i * 2 + 1] = hex[random[i] & 15];
        }
        if (char* path = ::realpath("/proc/self/exe", nullptr)) {
            g_executable = path;
            std::free(path);
        } else { std::perror("INFO executable realpath"); std::abort(); }
        if (server && server->cfg().conf_path) {
            if (char* path = ::realpath(server->cfg().conf_path, nullptr)) {
                g_config_file = path;
                std::free(path);
            } else {
                std::perror("INFO config_file realpath");
                std::abort();
            }
        }
    }
    info_stats_reset(0, server ? used_memory(*server) : 0);
}

void info_stats_tick(Server& server) {
    std::lock_guard<std::mutex> lock(g_info_stats.mu);
    const uint64_t sampled_ns = now_ns();
    std::array<uint64_t, 3> totals{};
    for (uint32_t t = 0; t < server.nthreads(); ++t) {
        ThreadCtx& thread = server.thread(t);
        totals[0] += thread.total_commands();
        totals[1] += thread.sig().net_input_bytes;
        totals[2] += thread.sig().net_output_bytes;
    }
    sample(sampled_ns, totals, used_memory(server));
}

std::array<uint64_t, 3> info_stats_rates() {
    std::lock_guard<std::mutex> lock(g_info_stats.mu);
    return g_info_stats.rates;
}

uint64_t info_stats_observe_memory(uint64_t memory) {
    std::lock_guard<std::mutex> lock(g_info_stats.mu);
    g_info_stats.memory_peak = std::max(g_info_stats.memory_peak, memory);
    return g_info_stats.memory_peak;
}

void info_stats_reset(uint64_t operations, uint64_t memory, uint64_t input, uint64_t output) {
    std::lock_guard<std::mutex> lock(g_info_stats.mu);
    g_info_stats.last_sample_ns = now_ns();
    g_info_stats.last = {operations, input, output};
    g_info_stats.samples = {};
    g_info_stats.rates = {};
    g_info_stats.memory_peak = memory;
    g_info_stats.cursor = 0;
}

const char* info_run_id() { return g_run_id.data(); }
const char* info_executable() { return g_executable.c_str(); }
const char* info_config_file() { return g_config_file.c_str(); }

}  // namespace tomo
