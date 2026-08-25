// config.h — every runtime knob in one place: the Config struct, the CLI grammar that fills it,
// and the conf-file loader. One parser serves both the command line and tomokv.conf (a conf line
// is translated to the equivalent --flag tokens), so a knob's spelling, validation, and default
// exist exactly once. t_server.cc's CONFIG SET/GET table (init_config) is built FROM this struct,
// which makes it the third consumer of the same source of truth.
//
// House rules for knobs (owner): numeric where possible; 0 = off and off allocates nothing;
// -1 = auto; thresholds self-derive. A field in Config that nothing reads is a lie — delete it.
//
// COMPILE-TIME tunables live elsewhere on purpose (changing them is a rebuild + re-validation,
// not an operational act). The complete list, so nothing hides:
//   kRobWindow        64      net/conn.h      max in-flight ops per connection (ROB size)
//   kEmbedThreshold   192     store/kvobj.h   value bytes embedded in the key's block
//   ValueSlot::kInline 1024   cmd/xshard.cc   gather slot capacity; pairs with zc-min as the
//                                             unified copy-vs-borrow cutover (min of the two)
//   kCommonBytes      16KiB   cmd/xshard.h    pooled scatter arena block size
//   sizeof(Op)==336, sizeof(Client)==1984     footprint locks (static_assert, do not move)

#pragma once

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include "../store/eviction.h"   // MaxmemoryPolicy + parse_maxmemory_policy
#include "../store/typeval.h"    // TypeLimits (compact-encoding limits)
#include "../store/flatstore.h"  // HashKind + g_hash_kind

namespace tomo {

struct Config {
    // ---- placement (boot-only) -------------------------------------------------------------
    const char* node_cpus   = nullptr;   // operator-declared topology; null = self-discover
    const char* place       = nullptr;   // complete role@cpu list; null = --ratio / default
    // Whole-server role counts for even placement (--ratio). All zero = unset. Unlike the per-node
    // fields above these express any global shape, and they are what a flip controller would vary.
    uint32_t even_ifid      = 0;
    uint32_t even_ex        = 0;
    const char* shard_home  = nullptr;   // optional complete shard:ex_tid map
    // Shards should outnumber workers: a shard is the unit of migration, so more shards gives the
    // LB finer granularity. Too many and each one's working set stops being worth its own table.
    uint32_t shards         = 16;
    // Pinning is relative to the process's ALLOWED cpu set, so taskset confines both the process and
    // its topology grouping — that property is what lets independent benchmark lanes share one box,
    // and its absence was a real bug (threads silently floated instead of erroring).
    bool     pin_threads    = true;

    // ---- network (boot-only) ---------------------------------------------------------------
    uint16_t port           = 6379;
    const char* bind_addr   = "127.0.0.1";
    const char* unixsocket  = nullptr;

    // ---- persistence (dir/dbfilename also live via CONFIG SET) ------------------------------
    const char* dir         = ".";
    const char* dbfilename  = "dump.tomo";
    const char* load_path   = nullptr;   // boot-only: load a dump before serving

    // ---- data path (live via CONFIG SET) ----------------------------------------------------
    uint32_t zc_min         = 16384;     // zero-copy GET replies at >= this value length.
                                         // DEFAULT ON (owner: hardcode a consistent gain): -4.1%
                                         // server cycles at d16K on the wire-walled NIC, +20-24%
                                         // class on unwalled wires per the fork's history. 0 = off.
                                         // Also the multi-key gather cutover: min(zc-min, kInline).
    uint64_t maxmemory      = 0;         // bytes; zero removes all eviction-path work.
    MaxmemoryPolicy maxmemory_policy = MaxmemoryPolicy::NoEviction;
    uint32_t maxmemory_samples = 5;
    // LRU bucket = (1 << lru_clock_shift) seconds; 5 clock bits give 32 buckets, so the window
    // before ages alias is 32 << shift seconds. Default 8 = 256s buckets / ~2h16m window: zero
    // header bytes and right for cache-realistic timescales. Shrink it (e.g. 6 = 64s / ~34min)
    // for fast-shifting working sets; for real cache duty allkeys-lfu discriminates with no clock
    // at all and is the recommended default.               (boot-only)
    uint32_t lru_clock_shift = 8;

    // ---- atomics (both live via CONFIG SET) --------------------------------------------------
    uint32_t atomic          = 0;        // epoch-MVCC atomic multi-key lane (MSET/MSETNX/DEL/
                                         // UNLINK write groups; MGET/EXISTS/TOUCH snapshot reads).
                                         // 0 = fully off: no allocation, plain paths byte-identical.
    // In-flight atomic write groups; 0 = unlimited; -1 (the default) = AUTO, resolved at boot to
    // min(16 * shards, 1024). Measured three-point law (2026-08-26, MSET-8 p32 ks=100k): the
    // optimum is 256 at 8c/16sh, 1024 at 32c/64sh AND 64c/128sh; larger windows flood the
    // per-shard pending scans (8c at 1024 collapses 40x), unlimited loses ~25% at 32c+ and the
    // default-256 left 2.3x on the table at 64c (796k -> 2.74M). A memory/backpressure valve,
    // not an ordering device -- tickets are drawn at the publish, so no frontier exists.
    static constexpr uint32_t kAtomicWindowAuto = UINT32_MAX;
    uint32_t atomic_window   = kAtomicWindowAuto;
    TypeLimits type_limits;              // 8 compact-encoding limits, all live via CONFIG SET
};

// ---- tiny local parsers (const char* flavors; the Slice flavors in the .cc files are separate) --

inline bool cfg_parse_u32(const char* s, uint32_t& out) {
    if (!s || !*s) return false;
    uint64_t v = 0;
    for (const char* p = s; *p; p++) {
        if (*p < '0' || *p > '9') return false;
        v = v * 10 + static_cast<uint64_t>(*p - '0');
        if (v > UINT32_MAX) return false;
    }
    out = static_cast<uint32_t>(v);
    return true;
}

inline bool cfg_parse_u64(const char* s, uint64_t& out) {
    if (!s || !*s) return false;
    uint64_t v = 0;
    for (const char* p = s; *p; p++) {
        if (*p < '0' || *p > '9') return false;
        const uint32_t digit = static_cast<uint32_t>(*p - '0');
        if (v > (UINT64_MAX - digit) / 10) return false;
        v = v * 10 + digit;
    }
    out = v;
    return true;
}

// Cross-source state: --ratio and --place are mutually exclusive WITHIN a source; across sources
// the later one (CLI over conf) silently replaces the earlier, which is what "base conf, per-run
// shape override" bench scripts want.
struct ConfigParseState {
    int ratio_source = 0;   // 0 = unset, 1 = conf, 2 = cli
    int place_source = 0;
};

enum : int { kConfigParsed = 0, kConfigError = 1, kConfigHelp = 2 };

// Parses one token stream (no argv[0]) into cfg. `source` is 1 for the conf file, 2 for the CLI.
// Prints its own error messages; the caller adds file context on conf failures.
inline int parse_config_args(const std::vector<const char*>& args, Config& cfg,
                             ConfigParseState& st, int source, const char* prog) {
    const int argc = static_cast<int>(args.size());
    for (int i = 0; i < argc; i++) {
        auto next = [&](const char* d) { return (i + 1 < argc) ? args[++i] : d; };
        const char* a = args[i];
        if      (!std::strcmp(a, "--port"))       cfg.port = static_cast<uint16_t>(std::atoi(next("6379")));
        else if (!std::strcmp(a, "--bind"))       cfg.bind_addr = next("127.0.0.1");
        else if (!std::strcmp(a, "--unixsocket")) cfg.unixsocket = next("");
        // WHOLE-SERVER role counts, evenly spread across L3 domains by the server itself.
        // This is the runtime replacement for authoring --place strings offline, and the knob a
        // flip controller will drive: counts in, placement out, no per-node arithmetic.
        else if (!std::strcmp(a, "--ratio")) {
            if (st.place_source == source) {
                std::fprintf(stderr, "--ratio and --place are mutually exclusive\n");
                return kConfigError;
            }
            if (st.place_source) { cfg.place = nullptr; st.place_source = 0; }
            st.ratio_source = source;
            const char* v = next("");
            unsigned a2 = 0, b = 0, c = 0;
            const int got = std::sscanf(v, "%u:%u:%u", &a2, &b, &c);
            if (got != 2 || a2 == 0 || b == 0) {
                std::fprintf(stderr, "--ratio wants global ifid:ex (e.g. 30:34); 3s was deleted 2026-08-24\n");
                return kConfigError;
            }
            cfg.even_ifid = a2; cfg.even_ex = b;
        }
        else if (!std::strcmp(a, "--shards"))     cfg.shards = static_cast<uint32_t>(std::atoi(next("16")));
        else if (!std::strcmp(a, "--lru-clock-shift")) {
            uint64_t shift = 0;
            if (!cfg_parse_u64(next(nullptr), shift) || shift > 16) {
                std::fprintf(stderr, "--lru-clock-shift wants 0..16 (bucket = 1<<N seconds)\n");
                return kConfigError;
            }
            cfg.lru_clock_shift = static_cast<uint32_t>(shift);
        }
        else if (!std::strcmp(a, "--maxmemory")) {
            if (!cfg_parse_u64(next(nullptr), cfg.maxmemory)) {
                std::fprintf(stderr, "--maxmemory wants a uint64 byte count (0 disables)\n");
                return kConfigError;
            }
        }
        else if (!std::strcmp(a, "--maxmemory-policy")) {
            const char* value = next(nullptr);
            if (!value || !parse_maxmemory_policy(value, cfg.maxmemory_policy)) {
                std::fprintf(stderr, "--maxmemory-policy wants a Redis maxmemory policy\n");
                return kConfigError;
            }
        }
        else if (!std::strcmp(a, "--maxmemory-samples")) {
            if (!cfg_parse_u32(next(nullptr), cfg.maxmemory_samples) ||
                cfg.maxmemory_samples == 0 || cfg.maxmemory_samples > 64) {
                std::fprintf(stderr, "--maxmemory-samples must be between 1 and 64\n");
                return kConfigError;
            }
        }
        else if (!std::strcmp(a, "--dir"))        cfg.dir = next(".");
        else if (!std::strcmp(a, "--dbfilename")) cfg.dbfilename = next("dump.tomo");
        else if (!std::strcmp(a, "--load"))       cfg.load_path = next("");
        else if (!std::strcmp(a, "--hash-max-compact-entries")) {
            if (!cfg_parse_u32(next(nullptr), cfg.type_limits.hash.max_entries)) return kConfigError;
        }
        else if (!std::strcmp(a, "--hash-max-compact-value")) {
            if (!cfg_parse_u32(next(nullptr), cfg.type_limits.hash.max_value)) return kConfigError;
        }
        else if (!std::strcmp(a, "--list-max-compact-entries")) {
            if (!cfg_parse_u32(next(nullptr), cfg.type_limits.list.max_entries)) return kConfigError;
        }
        else if (!std::strcmp(a, "--list-max-compact-value")) {
            if (!cfg_parse_u32(next(nullptr), cfg.type_limits.list.max_value)) return kConfigError;
        }
        else if (!std::strcmp(a, "--set-max-compact-entries")) {
            if (!cfg_parse_u32(next(nullptr), cfg.type_limits.set.max_entries)) return kConfigError;
        }
        else if (!std::strcmp(a, "--set-max-compact-value")) {
            if (!cfg_parse_u32(next(nullptr), cfg.type_limits.set.max_value)) return kConfigError;
        }
        else if (!std::strcmp(a, "--zset-max-compact-entries")) {
            if (!cfg_parse_u32(next(nullptr), cfg.type_limits.zset.max_entries)) return kConfigError;
        }
        else if (!std::strcmp(a, "--zset-max-compact-value")) {
            if (!cfg_parse_u32(next(nullptr), cfg.type_limits.zset.max_value)) return kConfigError;
        }
        else if (!std::strcmp(a, "--zc-min")) {
            const char* v = next(nullptr);
            if (!cfg_parse_u32(v, cfg.zc_min)) {
                std::fprintf(stderr, "--zc-min wants a uint32 byte count (0 disables; 16384 suggested when enabled)\n");
                return kConfigError;
            }
        }
        else if (!std::strcmp(a, "--atomic")) {
            if (!cfg_parse_u32(next(nullptr), cfg.atomic) || cfg.atomic > 1) {
                std::fprintf(stderr, "--atomic wants 0 or 1\n");
                return kConfigError;
            }
        }
        else if (!std::strcmp(a, "--atomic-window")) {
            const char* v = next(nullptr);
            if (v && !std::strcmp(v, "-1")) cfg.atomic_window = Config::kAtomicWindowAuto;
            else if (!cfg_parse_u32(v, cfg.atomic_window)) {
                std::fprintf(stderr, "--atomic-window wants a uint32, 0 = unlimited, -1 = auto\n");
                return kConfigError;
            }
        }
        else if (!std::strcmp(a, "--shard-home")) cfg.shard_home = next("");
        else if (!std::strcmp(a, "--no-pin"))     cfg.pin_threads = false;
        else if (!std::strcmp(a, "--hash")) {
            const char* h = next("mix64");
            if      (!std::strcmp(h, "mix64"))   g_hash_kind = HashKind::Mix64Seeded;
            else if (!std::strcmp(h, "siphash")) g_hash_kind = HashKind::SipHash12;
            else { std::fprintf(stderr, "--hash must be mix64 | siphash\n"); return kConfigError; }
        }
        else if (!std::strcmp(a, "--l3-domains")) {
            // Operator-declared topology: comma-separated per-domain cpu lists, '-' for ranges,
            // '+' to glue disjoint ranges into one domain. "--l3-domains 0-3,4-7" = two declared
            // domains on one CCX -- a shape discovery would never produce, which is the point.
            // (Renamed from --node-cpus 2026-08-25: "nodes" as a server structure died with the
            // fork; this declares L3 LOCALITY DOMAINS for placement spread, nothing more.)
            cfg.node_cpus = next("");
        }
        else if (!std::strcmp(a, "--place")) {
            if (st.ratio_source == source) {
                std::fprintf(stderr, "--ratio and --place are mutually exclusive\n");
                return kConfigError;
            }
            if (st.ratio_source) { cfg.even_ifid = cfg.even_ex = 0; st.ratio_source = 0; }
            st.place_source = source;
            cfg.place = next("");
        }
        else if (!std::strcmp(a, "--help")) {
            std::printf("usage: %s [conf-file] [--conf FILE] [--port N] [--bind A] [--unixsocket PATH]\n"
                        "       [--shards N] [--zc-min N] [--no-pin]\n"
                        "  conf file: `name value` per line, # comments; same names as the flags\n"
                        "  without the leading --; `pin no` spells --no-pin. CLI flags override the\n"
                        "  file. See tomokv.conf in the repo root for the annotated full set.\n"
                        "  placement (pure 2s; default = even io/ex split over all allowed cpus):\n"
                        "    --ratio io:ex               GLOBAL counts, spread evenly over L3 domains\n"
                        "    --place role@cpu,...        explicit per-thread; roles are ifid, ex\n"
                        "    --l3-domains LIST           declared L3 topology, ranges joined by +\n"
                        "    --shard-home shard:tid,...  complete shard-to-executor map\n"
                        "    --zc-min N                  zero-copy GET replies for values >= N (0=off)\n"
                        "  cache: --maxmemory BYTES --maxmemory-policy POLICY (allkeys-lfu\n"
                        "         recommended for cache duty) --lru-clock-shift N (bucket=1<<N s)\n"
                        "         --maxmemory-samples N (1..64, default 5)\n"
                        "  persistence: --dir PATH --dbfilename NAME --load PATH\n"
                        "  atomics: --atomic 0|1 --atomic-window N (default 256; 0=unlimited)\n"
                        "  compact encodings: --{hash,list,set,zset}-max-compact-{entries,value} N\n"
                        "  misc: --hash mix64|siphash\n"
                        "  (pure 2s is the only server; --mode/--wb/--nodes died with 3s, 2026-08)\n",
                        prog);
            return kConfigHelp;
        }
        else {
            std::fprintf(stderr, "unknown argument '%s' (see --help)\n", a);
            return kConfigError;
        }
    }
    return kConfigParsed;
}

// Post-parse validation shared by every source combination. Call once, after all token streams.
inline int validate_config(const Config& cfg) {
    if (cfg.shards == 0 || cfg.shards > 256) {
        std::fprintf(stderr, "shards must be between 1 and 256\n");
        return kConfigError;
    }
    if (!cfg.dir || !*cfg.dir || !cfg.dbfilename || !*cfg.dbfilename ||
        std::strchr(cfg.dbfilename, '/')) {
        std::fprintf(stderr, "--dir must be non-empty and --dbfilename must be a plain filename\n");
        return kConfigError;
    }
    return kConfigParsed;
}

// Conf-file loader: translates `name value...` lines into the exact --flag token stream the CLI
// parser consumes, so the file cannot drift from the flag grammar. `pin yes|no` maps to the
// valueless --no-pin. Token storage lives in `store` (must outlive parsing — Config keeps
// const char* views into it).
inline bool load_conf_file(const char* path, std::vector<std::string>& store) {
    std::FILE* f = std::fopen(path, "r");
    if (!f) {
        std::fprintf(stderr, "cannot open conf file '%s'\n", path);
        return false;
    }
    char line[4096];
    int lineno = 0;
    bool ok = true;
    while (ok && std::fgets(line, sizeof(line), f)) {
        lineno++;
        if (char* hash = std::strchr(line, '#')) *hash = '\0';
        std::vector<std::string> words;
        for (char* p = std::strtok(line, " \t\r\n"); p; p = std::strtok(nullptr, " \t\r\n"))
            words.emplace_back(p);
        if (words.empty()) continue;
        if (words[0] == "pin") {
            if (words.size() != 2 || (words[1] != "yes" && words[1] != "no")) {
                std::fprintf(stderr, "%s:%d: pin wants yes|no\n", path, lineno);
                ok = false;
            } else if (words[1] == "no") {
                store.emplace_back("--no-pin");
            }
            continue;
        }
        store.emplace_back("--" + words[0]);
        for (size_t w = 1; w < words.size(); w++) store.emplace_back(words[w]);
    }
    std::fclose(f);
    return ok;
}

}  // namespace tomo
