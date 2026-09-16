#pragma once

#include "workload.h"

#include <sched.h>
#include <set>

namespace tailgen {

struct Config {
    double rate = 10000, duration = 20, warmup = 3;
    size_t threads = 1, conns = 1; // connections PER THREAD
    std::vector<int> cores;
    std::string host = "127.0.0.1", port = "6379";
    uint64_t seed = 1, max_outstanding = 64;
    Spacing spacing = Spacing::poisson;
    std::string mix = "GET:8,BITCOUNT:2";
    KeySpace short_keys = {"memtier-", "", 1, 2000000};
    KeySpace long_keys = {"blocker:memtier-", "", 1, 65536};
    bool help = false;

    int core(size_t thread) const {
        return cores[threads == 1 ? 0 : thread * (cores.size() - 1) / (threads - 1)];
    }
    uint64_t duration_ns() const { return static_cast<uint64_t>(duration * 1e9 + .5); }
    uint64_t warmup_ns() const { return static_cast<uint64_t>(warmup * 1e9 + .5); }
};

inline double real_number(std::string_view text) {
    double value = 0;
    const auto parsed = std::from_chars(text.data(), text.data() + text.size(), value);
    if (text.empty() || parsed.ec != std::errc{} || parsed.ptr != text.data() + text.size() || !std::isfinite(value))
        throw std::invalid_argument("invalid finite number: " + std::string(text));
    return value;
}

inline std::vector<int> core_list(std::string_view list) {
    std::vector<int> result;
    std::set<int> used;
    while (!list.empty()) {
        const size_t comma = list.find(',');
        const std::string_view range = list.substr(0, comma);
        const size_t dash = range.find('-');
        const uint64_t first = unsigned_number(range.substr(0, dash));
        const uint64_t last = dash == std::string_view::npos ? first : unsigned_number(range.substr(dash + 1));
        if (first > last || last >= CPU_SETSIZE) throw std::invalid_argument("invalid CPU range");
        for (uint64_t cpu = first; cpu <= last; ++cpu) {
            if (!used.insert(static_cast<int>(cpu)).second) throw std::invalid_argument("duplicate CPU");
            result.push_back(static_cast<int>(cpu));
        }
        if (comma == std::string_view::npos) break;
        list.remove_prefix(comma + 1);
        if (list.empty()) throw std::invalid_argument("empty CPU entry");
    }
    if (result.empty()) throw std::invalid_argument("empty CPU list");
    return result;
}

inline Config parse_config(int argc, const char* const* argv) {
    Config c;
    std::set<std::string_view> seen;
    for (int i = 1; i < argc; ++i) {
        std::string_view option(argv[i]), value;
        if (option == "--help" || option == "-h") { c.help = true; continue; }
        const size_t equals = option.find('=');
        if (equals != std::string_view::npos) { value = option.substr(equals + 1); option = option.substr(0, equals); }
        else {
            if (++i == argc) throw std::invalid_argument("missing value for " + std::string(option));
            value = argv[i];
        }
        if (!seen.insert(option).second) throw std::invalid_argument("duplicate option: " + std::string(option));
        if (option == "--rate") c.rate = real_number(value);
        else if (option == "--duration") c.duration = real_number(value);
        else if (option == "--warmup") c.warmup = real_number(value);
        else if (option == "--threads") c.threads = unsigned_number(value);
        else if (option == "--conns") c.conns = unsigned_number(value);
        else if (option == "--cores") c.cores = core_list(value);
        else if (option == "--host") c.host = value;
        else if (option == "--port") c.port = value;
        else if (option == "--seed") c.seed = unsigned_number(value);
        else if (option == "--max-outstanding") c.max_outstanding = unsigned_number(value);
        else if (option == "--mix") c.mix = value;
        else if (option == "--short-keys") c.short_keys = KeySpace::parse(value, "memtier-");
        else if (option == "--long-keys") c.long_keys = KeySpace::parse(value, "blocker:memtier-");
        else if (option == "--spacing") {
            if (value == "poisson") c.spacing = Spacing::poisson;
            else if (value == "fixed") c.spacing = Spacing::fixed;
            else throw std::invalid_argument("--spacing must be poisson or fixed");
        } else throw std::invalid_argument("unknown option: " + std::string(option));
    }
    if (c.help) return c;
    if (c.rate < 1e-6 || c.rate > 1e9) throw std::invalid_argument("--rate must be in [0.000001, 1000000000]");
    if (c.duration < 1e-9 || c.duration > 86400 || c.warmup < 0 || c.warmup > 86400)
        throw std::invalid_argument("--duration must be positive and --warmup nonnegative (at most 86400 seconds each)");
    if (!c.threads || c.threads > CPU_SETSIZE || !c.conns || c.conns > UINT32_MAX)
        throw std::invalid_argument("invalid positive --threads/--conns");
    const uint64_t port = unsigned_number(c.port);
    if (!port || port > 65535 || c.host.empty()) throw std::invalid_argument("invalid host/port");
    // Validate the mix before any connection attempt.
    Workload validate(c.mix, c.short_keys, c.long_keys);
    cpu_set_t allowed;
    CPU_ZERO(&allowed);
    if (sched_getaffinity(0, sizeof allowed, &allowed))
        throw std::system_error(errno, std::generic_category(), "sched_getaffinity");
    if (c.cores.empty()) {
        for (int core = 0; core < CPU_SETSIZE; ++core) if (CPU_ISSET(core, &allowed)) c.cores.push_back(core);
    }
    if (c.cores.size() < c.threads) throw std::invalid_argument("need at least one distinct allowed core per thread");
    for (int core : c.cores) if (!CPU_ISSET(core, &allowed))
        throw std::invalid_argument("requested CPU " + std::to_string(core) + " is outside process affinity");
    return c;
}

} // namespace tailgen
