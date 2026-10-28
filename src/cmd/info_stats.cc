#include "info_stats.h"
#include "scripting.h"

#include "../core/server.h"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <limits>
#include <fstream>
#include <mutex>
#include <sstream>
#include <string>
#include <sys/random.h>
#include <sys/resource.h>
#include <link.h>
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
        totals[1] += thread.sig().net_input_bytes.load(std::memory_order_relaxed);
        totals[2] += thread.sig().net_output_bytes.load(std::memory_order_relaxed);
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

void info_stats_memory_fields(std::string& body, uint64_t allocated, uint64_t resident) {
    std::vector<std::pair<std::string, std::string>> config;
    command_config_snapshot(config);
    const char* maxmemory = "0";
    const char* policy = "noeviction";
    for (const auto& item : config) {
        if (item.first == "maxmemory") maxmemory = item.second.c_str();
        if (item.first == "maxmemory-policy") policy = item.second.c_str();
    }
    // Compare jemalloc resident/allocated on the same process-wide basis. The
    // dataset-only admission budget is not an allocator fragmentation denominator.
#if TOMO_SINGLE_DATABASE
    char fields[192];
    const int count = std::snprintf(fields, sizeof(fields),
        "maxmemory:%s\r\nmaxmemory_policy:%s\r\nmem_fragmentation_ratio:%.2f\r\n",
        maxmemory, policy, allocated && resident ? double(resident) / double(allocated) : 1.0);
#else
    const auto scripting = script_stats();
    const auto functions = function_stats();
    char fields[384];
    const int count = std::snprintf(fields, sizeof(fields),
        "number_of_cached_scripts:%llu\r\nnumber_of_functions:%llu\r\n"
        "number_of_libraries:%llu\r\n"
        "maxmemory:%s\r\nmaxmemory_policy:%s\r\nmem_fragmentation_ratio:%.2f\r\n",
        static_cast<unsigned long long>(scripting.cached_scripts),
        static_cast<unsigned long long>(functions.functions),
        static_cast<unsigned long long>(functions.libraries),
        maxmemory, policy, allocated && resident ? double(resident) / double(allocated) : 1.0);
#endif
    if (count > 0 && static_cast<size_t>(count) < sizeof(fields)) body.append(fields, count);
}

const char* info_run_id() { return g_run_id.data(); }
const char* info_executable() { return g_executable.c_str(); }
const char* info_config_file() { return g_config_file.c_str(); }

void info_stats_cpu_fields(std::string& body) {
    rusage self{}, children{};
    if (getrusage(RUSAGE_SELF, &self) || getrusage(RUSAGE_CHILDREN, &children)) std::abort();
    const auto seconds = [](timeval t) { return double(t.tv_sec) + double(t.tv_usec) / 1000000; };
    // INFO runs on a connection owner. RUSAGE_THREAD here would report that
    // worker, not the process's main thread. Linux exposes the latter by TID.
    std::ifstream file("/proc/self/task/" + std::to_string(getpid()) + "/stat");
    std::string line, ignored;
    std::getline(file, line);
    const auto end = line.rfind(')');
    if (end == std::string::npos) std::abort();
    std::istringstream fields(line.substr(end + 2));
    for (unsigned i = 0; i < 11; ++i) fields >> ignored;
    uint64_t user = 0, system = 0;
    fields >> user >> system;
    const long ticks = sysconf(_SC_CLK_TCK);
    if (!fields || ticks <= 0) std::abort();
    char out[512];
    const int size = std::snprintf(out, sizeof(out),
        "# CPU\r\nused_cpu_sys:%.6f\r\nused_cpu_user:%.6f\r\n"
        "used_cpu_sys_children:%.6f\r\nused_cpu_user_children:%.6f\r\n"
        "used_cpu_sys_main_thread:%.6f\r\nused_cpu_user_main_thread:%.6f\r\n",
        seconds(self.ru_stime), seconds(self.ru_utime),
        seconds(children.ru_stime), seconds(children.ru_utime),
        double(system) / ticks, double(user) / ticks);
    body.append(out, size);
}

void info_stats_build_fields(std::string& body) {
    // Redis's field names identify this executable, never the oracle's build.
#ifndef TOMO_INFO_GIT_SHA1
#define TOMO_INFO_GIT_SHA1 "00000000"
#define TOMO_INFO_GIT_DIRTY "0"
#endif
    body += "redis_git_sha1:" TOMO_INFO_GIT_SHA1 "\r\nredis_git_dirty:" TOMO_INFO_GIT_DIRTY "\r\nredis_build_id:";
    std::string id;
    dl_iterate_phdr([](dl_phdr_info* image, size_t, void* context) {
        if (image->dlpi_name && *image->dlpi_name) return 0;
        auto& id = *static_cast<std::string*>(context);
        for (unsigned i = 0; i < image->dlpi_phnum; ++i) {
            const auto& segment = image->dlpi_phdr[i];
            if (segment.p_type != PT_NOTE) continue;
            const auto* p = reinterpret_cast<const unsigned char*>(image->dlpi_addr + segment.p_vaddr);
            const auto* end = p + segment.p_memsz;
            while (size_t(end - p) >= sizeof(ElfW(Nhdr))) {
                const auto* note = reinterpret_cast<const ElfW(Nhdr)*>(p);
                const size_t name = (size_t(note->n_namesz) + 3) & ~size_t{3};
                const size_t data = (size_t(note->n_descsz) + 3) & ~size_t{3};
                if (sizeof(*note) + name + data > size_t(end - p)) break;
                if (note->n_type == NT_GNU_BUILD_ID && note->n_namesz == 4 &&
                    !std::memcmp(p + sizeof(*note), "GNU", 4)) {
                    // Redis exposes an unpadded 64-bit hexadecimal build identity.
                    // Use this executable's build-id prefix, never the oracle's ID.
                    const auto* bytes = p + sizeof(*note) + name;
                    uint64_t identity = 0;
                    for (unsigned j = 0; j < std::min(note->n_descsz, 8u); ++j)
                        identity = (identity << 8) | bytes[j];
                    char hex[17];
                    std::snprintf(hex, sizeof(hex), "%llx",
                                  static_cast<unsigned long long>(identity));
                    id = hex;
                    return 1;
                }
                p += sizeof(*note) + name + data;
            }
        }
        return 1;
    }, &id);
    body += id.empty() ? "0" : id;
    body += "\r\n";
}

}  // namespace tomo
