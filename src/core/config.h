// Boot configuration values, shared value parsers and the configuration-file loader.
// Included by main.cc, server.h and CONFIG handlers; there is no fixed inclusion point.
// CLI and file directives share parse_config_args; live CONFIG uses these value helpers
// where applicable. Config borrows string storage and owns its vectors; parsers require
// exclusive access and do not publish to workers. LiveConfigMailbox handles publication.
//
// Defaults, units and sentinel meanings below follow each parser. Redis-named settings
// use their own grammar, so 0 does not always disable a feature and -1 is not always auto.
// String/path/list knobs have no numeric 0 or -1 sentinel; enum knobs accept only the
// listed words. Internal fields are identified separately from user-facing knobs.
//
// Compile-time bounds live with their consumers: kRobWindow in net/rob.h,
// kEmbedThreshold in store/kvobj.h, ValueSlot::kInline in cmd/scatter_engine.inc,
// and kCommonBytes in cmd/xshard.h. Op and Client have fixed 336/1984-byte layouts.

#pragma once

#include <cstdint>
#include <array>
#include <climits>
#include <cctype>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <cerrno>
#include <charconv>
#include <cmath>
#include <limits>
#include <locale.h>
#include <string>
#include <utility>
#include <vector>

#include "wb_rule.h"
#include "client_hz.h"
#include "version.h"
#include "../base/slice.h"       // Slice (notify flag parsing)
#include "../cmd/notify.h"       // parse_notify_flags
#include "../store/eviction.h"   // MaxmemoryPolicy + parse_maxmemory_policy
#include "../store/typeval.h"    // TypeLimits (compact-encoding limits)
#include "../store/flatstore.h"  // HashKind + g_hash_kind (the only symbols needed from it)

namespace tomo {

inline bool cfg_parse_u32(const char* s, uint32_t& out);
inline bool cfg_parse_u64(const char* s, uint64_t& out);

inline bool cfg_split_args(const char* line, std::vector<std::string>& out);

// Immutable process-setting metadata used by boot and CONFIG normalization. Pointers
// refer to static strings; mutable values live in process_config_values, indexed by
// Config::process_config_id. Defaults need no sidecar. Boot or the serialized CONFIG
// writer must own access to that vector; this metadata provides no synchronization.
struct ProcessConfigSpec {
    const char* name;
    const char* value;
    const char* choices;  // null: string; "integer": signed int; otherwise comma-separated enum
    bool immutable;
    bool hidden = false;
};
// Process defaults and units: daemonize=no and syslog-enabled=no are yes/no switches;
// logfile="", pidfile="", syslog-ident="redis" are strings/paths; syslog-facility=local0,
// loglevel=notice and supervised=no are enums whose accepted words are in choices.
// Their 0/-1 strings are not sentinels. key-load-delay defaults to 0 microseconds (off);
// negative -N selects a one-microsecond delay with probability 1/N, so -1 always delays.
inline constexpr ProcessConfigSpec /* TOMO_TOOL_BIND process_configs */ process_configs[] = {
    {"daemonize", "no", "yes, no", true},
    {"logfile", "", nullptr, true},
    {"syslog-enabled", "no", "yes, no", true},
    {"syslog-ident", "redis", nullptr, true},
    {"syslog-facility", "local0",
     "user, local0, local1, local2, local3, local4, local5, local6, local7", true},
    {"loglevel", "notice", "debug, verbose, notice, warning, nothing", false},
    {"pidfile", "", nullptr, true},
    {"supervised", "no", "upstart, systemd, auto, no", true},
    {"key-load-delay", "0", "integer", false, true},
};
inline constexpr size_t kProcessConfigCount = std::size(process_configs);
inline std::vector<std::array<std::string, kProcessConfigCount>> process_config_values;
inline int cfg_process_find(Slice name) {
    for (size_t i = 0; i < kProcessConfigCount; ++i)
        if (name.eq_icase(process_configs[i].name)) return static_cast<int>(i);
    return -1;
}
inline bool cfg_process_normalize(int index, Slice input, std::string& out, std::string& error) {
    const auto& spec = process_configs[index];
    if (!spec.choices) {
        out.assign(input.p, strnlen(input.p, input.n));
        return true;
    }
    if (std::strcmp(spec.choices, "integer")) input.n = strnlen(input.p, input.n);
    if (!std::strcmp(spec.choices, "integer")) {
        // Redis string2ll accepts only canonical decimal, including a minus
        // sign but excluding +, leading zeroes, whitespace and embedded NUL.
        int64_t value = 0;
        auto parsed = std::from_chars(input.p, input.p + input.n, value);
        if (!input.n || parsed.ec != std::errc{} || parsed.ptr != input.p + input.n ||
            std::to_string(value) != input.sv()) {
            error = "argument couldn't be parsed into an integer";
            return false;
        }
        if (value < INT_MIN || value > INT_MAX) {
            error = "argument must be between -2147483648 and 2147483647 inclusive";
            return false;
        }
        out = std::to_string(value);
        return true;
    }
    const std::string choices(spec.choices);
    for (size_t begin = 0; begin < choices.size();) {
        const size_t end = choices.find(", ", begin);
        const std::string choice =
            choices.substr(begin, end == std::string::npos ? end : end - begin);
        if (input.eq_icase(choice.c_str())) {
            out = choice;
            return true;
        }
        if (end == std::string::npos) break;
        begin = end + 2;
    }
    error = !std::strcmp(spec.choices, "yes, no")
                ? "argument must be 'yes' or 'no'"
                : std::string("argument(s) must be one of the following: ") + spec.choices;
    return false;
}

// Parse space-separated percentile values without sorting or deduplication. An empty
// default vector owns no memory; callers choose implicit defaults separately.
__attribute__((noipa)) inline bool cfg_latency_percentiles(Slice input, std::vector<double>& out,
                                                           const char*& error) {
    out.clear();
    if (!input.n) return true;
    size_t start = 0;
    do {
        size_t end = start;
        while (end < input.n && input.p[end] != ' ') ++end;
        std::string token(input.p + start, end - start);
        char* tail = nullptr;
        errno = 0;
        const double value = std::strtod(token.c_str(), &tail);
        if (token.empty() || std::isspace(static_cast<unsigned char>(token[0])) ||
            tail != token.data() + token.size() || std::isnan(value) || errno == EINVAL ||
            (errno == ERANGE && (value == 0 || std::isinf(value)))) {
            error = "Invalid latency-tracking-info-percentiles parameters";
            return false;
        }
        if (value < 0 || value > 100) {
            error = "latency-tracking-info-percentiles parameters should sit between [0.0,100.0]";
            return false;
        }
        out.push_back(value);
        start = end + 1;
    } while (start <= input.n);
    return true;
}

__attribute__((noipa)) inline std::string cfg_latency_percentiles_string(
    const std::vector<double>& values) {
    std::string out;
    for (double value : values) {
        char text[128];
        int n = std::snprintf(text, sizeof(text), "%f", value);
        while (n > 0 && text[n - 1] == '0') --n;
        if (n > 0 && text[n - 1] == '.') --n;
        if (!out.empty()) out += ' ';
        out.append(text, n);
    }
    return out;
}

// Owned scalar limits: defaults are 0 bytes hard/soft and 0 seconds. Zero bytes disables
// that byte limit; zero seconds allows no positive soft-limit grace period. -1 is invalid.
// The enclosing snapshot supplies synchronization; this value type publishes nothing.
struct ClientBufferLimit {
    uint64_t hard_bytes = 0;
    uint64_t soft_bytes = 0;
    uint32_t soft_seconds = 0;
};

// Owned per-class limits (hard bytes, soft bytes, seconds): normal=(0,0,0),
// replica=(256 MiB,64 MiB,60), pubsub=(32 MiB,8 MiB,60). Zero/-1 follow
// ClientBufferLimit. The replica entry is configuration compatibility state.
struct ClientOutputBufferLimits {
    ClientBufferLimit normal{};
    ClientBufferLimit replica{256ull * 1024 * 1024, 64ull * 1024 * 1024, 60};
    ClientBufferLimit pubsub{32ull * 1024 * 1024, 8ull * 1024 * 1024, 60};
};

inline bool cfg_eq_icase(const char* a, const char* b) {
    if (!a || !b) return false;
    while (*a && *b) {
        unsigned char ac = static_cast<unsigned char>(*a++);
        unsigned char bc = static_cast<unsigned char>(*b++);
        if (ac >= 'A' && ac <= 'Z') ac = static_cast<unsigned char>(ac + ('a' - 'A'));
        if (bc >= 'A' && bc <= 'Z') bc = static_cast<unsigned char>(bc + ('a' - 'A'));
        if (ac != bc) return false;
    }
    return *a == *b;
}

// Redis memory grammar: bare bytes (or B), decimal K/M/G, binary KB/MB/GB. Boot and
// CONFIG SET share this length-aware implementation, so RESP bulk input needs no
// temporary NUL-terminated copy.
inline bool cfg_memory_suffix(const char* input, size_t length, const char* expected) {
    const size_t expected_length = std::strlen(expected);
    if (length != expected_length) return false;
    for (size_t i = 0; i < length; i++) {
        unsigned char actual = static_cast<unsigned char>(input[i]);
        unsigned char wanted = static_cast<unsigned char>(expected[i]);
        if (actual >= 'A' && actual <= 'Z') actual += static_cast<unsigned char>('a' - 'A');
        if (wanted >= 'A' && wanted <= 'Z') wanted += static_cast<unsigned char>('a' - 'A');
        if (actual != wanted) return false;
    }
    return true;
}

inline bool cfg_parse_memory(const char* input, size_t length, uint64_t& out) {
    if (!input) return false;
    // memtoull is a C-string parser, including for CONFIG SET's SDS argument.
    if (const void* nul = std::memchr(input, 0, length))
        length = static_cast<const char*>(nul) - input;
    if (length && *input == '-') return false;
    size_t digits = 0;
    while (digits < length && input[digits] >= '0' && input[digits] <= '9') digits++;
    if (digits >= 128) return false;  // Redis memtoull numeric buffer bound
    uint64_t value = 0;
    bool saturated = false;
    for (size_t i = 0; i < digits; i++) {
        const uint32_t digit = static_cast<uint32_t>(input[i] - '0');
        if (!saturated) {
            if (value > (UINT64_MAX - digit) / 10) {
                value = UINT64_MAX;
                saturated = true;
            } else {
                value = value * 10 + digit;
            }
        }
    }
    const char* suffix = input + digits;
    const size_t suffix_length = length - digits;
    uint64_t mul = 1;
    if (!suffix_length || cfg_memory_suffix(suffix, suffix_length, "b"))
        mul = 1;
    else if (cfg_memory_suffix(suffix, suffix_length, "k"))
        mul = 1000;
    else if (cfg_memory_suffix(suffix, suffix_length, "kb"))
        mul = 1024;
    else if (cfg_memory_suffix(suffix, suffix_length, "m"))
        mul = 1000ull * 1000;
    else if (cfg_memory_suffix(suffix, suffix_length, "mb"))
        mul = 1024ull * 1024;
    else if (cfg_memory_suffix(suffix, suffix_length, "g"))
        mul = 1000ull * 1000 * 1000;
    else if (cfg_memory_suffix(suffix, suffix_length, "gb"))
        mul = 1024ull * 1024 * 1024;
    else
        return false;
    // Redis preserves strtoull's ULLONG_MAX saturation and then performs the unsigned multiply.
    // The wrap for an overflowing suffixed value is odd but observable CONFIG behavior.
    out = value * mul;
    return true;
}

inline bool cfg_parse_memory(const char* input, uint64_t& out) {
    return input && cfg_parse_memory(input, std::strlen(input), out);
}

inline bool cfg_parse_query_buffer_limit(const char* input, size_t length, uint64_t& out,
                                         const char*& error) {
    // Redis memory parsing consumes a C string, including empty-number-to-zero behavior.
    // The query-buffer range check below rejects zero even when the grammar accepts it.
    if (const void* nul = std::memchr(input, 0, length))
        length = static_cast<const char*>(nul) - input;
    const bool zero =
        !length || cfg_memory_suffix(input, length, "b") || cfg_memory_suffix(input, length, "k") ||
        cfg_memory_suffix(input, length, "kb") || cfg_memory_suffix(input, length, "m") ||
        cfg_memory_suffix(input, length, "mb") || cfg_memory_suffix(input, length, "g") ||
        cfg_memory_suffix(input, length, "gb");
    if (zero)
        out = 0;
    else if (!cfg_parse_memory(input, length, out)) {
        error = "argument must be a memory value";
        return false;
    }
    if (out < 1024 * 1024 || out > LONG_MAX) {
        static_assert(LONG_MAX == 9223372036854775807LL);
        error = "argument must be between 1048576 and 9223372036854775807 inclusive";
        return false;
    }
    return true;
}

inline bool cfg_parse_unixsocketperm(const char* input, uint16_t& out) {
    if (!input) return false;
    char* end = nullptr;
    errno = 0;
    const long value = std::strtol(input, &end, 8);
    if (errno || *end || value < 0 || value > 0777) return false;
    out = static_cast<uint16_t>(value);
    return true;
}

// Value-only schedule clause: seconds and change count; the default schedule is in
// Config::save. Parsed seconds must be positive; changes=0 is accepted and -1 is
// rejected for either unsigned value. The owning vector controls lifetime.
struct SaveClause {
    uint64_t seconds = 0;
    uint64_t changes = 0;
};

inline constexpr uint64_t kProtoMinBulkLen = 1024ull * 1024;
// Redis's configuration range is signed long. The independent 32-bit receive-cursor
// bound still rejects a frame that cannot be represented by this server's Slice ABI.
inline constexpr uint64_t kProtoMaxBulkLenSupported = LONG_MAX;
// String values and argv Slices are 32-bit. This is the largest bulk whose value and
// RESP envelope both fit that representation. String-growing commands (APPEND,
// SETRANGE, SETBIT, BITFIELD) stop here even if the configured limit is larger,
// rather than narrowing a 64-bit length before allocation.
inline constexpr uint64_t kProtoMaxBulkLenRepresentable = UINT32_MAX - 64ull * 1024;

inline bool cfg_parse_save_schedule(const char* input, size_t length,
                                    std::vector<SaveClause>& out) {
    out.clear();
    if (!length) return true;
    if (!input || std::isspace(static_cast<unsigned char>(input[0])) ||
        std::isspace(static_cast<unsigned char>(input[length - 1])))
        return false;
    std::vector<uint64_t> values;
    size_t pos = 0;
    while (pos < length) {
        const size_t begin = pos;
        while (pos < length && !std::isspace(static_cast<unsigned char>(input[pos]))) pos++;
        uint64_t value = 0;
        if (begin == pos || !cfg_parse_u64(std::string(input + begin, pos - begin).c_str(), value))
            return false;
        values.push_back(value);
        while (pos < length && std::isspace(static_cast<unsigned char>(input[pos]))) pos++;
    }
    if (values.empty() || (values.size() & 1u)) return false;
    out.reserve(values.size() / 2);
    for (size_t i = 0; i < values.size(); i += 2) {
        if (values[i] == 0) return false;
        out.push_back(SaveClause{values[i], values[i + 1]});
    }
    return true;
}

inline std::string cfg_save_schedule_string(const std::vector<SaveClause>& clauses) {
    std::string out;
    for (const SaveClause& clause : clauses) {
        if (!out.empty()) out.push_back(' ');
        out += std::to_string(clause.seconds);
        out.push_back(' ');
        out += std::to_string(clause.changes);
    }
    return out;
}

inline bool cfg_parse_client_output_buffer_limit(const char* const* args, size_t count,
                                                 ClientOutputBufferLimits& limits,
                                                 const char*& error) {
    if (!count || count % 4) {
        error = "Wrong number of arguments in buffer limit configuration.";
        return false;
    }
    ClientOutputBufferLimits scratch = limits;
    for (size_t i = 0; i < count; i += 4) {
        ClientBufferLimit* target = nullptr;
        if (cfg_eq_icase(args[i], "normal"))
            target = &scratch.normal;
        else if (cfg_eq_icase(args[i], "slave") || cfg_eq_icase(args[i], "replica"))
            target = &scratch.replica;
        else if (cfg_eq_icase(args[i], "pubsub"))
            target = &scratch.pubsub;
        if (!target || cfg_eq_icase(args[i], "master")) {
            error = "Invalid client class specified in buffer limit configuration.";
            return false;
        }
        uint64_t hard = 0, soft = 0;
        uint32_t seconds = 0;
        if (!cfg_parse_memory(args[i + 1], hard) || !cfg_parse_memory(args[i + 2], soft) ||
            !cfg_parse_u32(args[i + 3], seconds) || seconds > INT_MAX) {
            error = "Error in hard, soft or soft_seconds setting in buffer limit configuration.";
            return false;
        }
        *target = ClientBufferLimit{hard, soft, seconds};
    }
    limits = scratch;
    error = nullptr;
    return true;
}

inline std::string cfg_client_output_buffer_limit_string(const ClientOutputBufferLimits& limits) {
    return "normal " + std::to_string(limits.normal.hard_bytes) + " " +
           std::to_string(limits.normal.soft_bytes) + " " +
           std::to_string(limits.normal.soft_seconds) + " slave " +
           std::to_string(limits.replica.hard_bytes) + " " +
           std::to_string(limits.replica.soft_bytes) + " " +
           std::to_string(limits.replica.soft_seconds) + " pubsub " +
           std::to_string(limits.pubsub.hard_bytes) + " " +
           std::to_string(limits.pubsub.soft_bytes) + " " +
           std::to_string(limits.pubsub.soft_seconds);
}

enum class DebugCommandMode : uint8_t { No = 0, Yes = 1, Local = 2 };
enum class AppendFsyncPolicy : uint8_t { Always = 0, Everysec = 1, No = 2 };
// One boot-latched persistence engine governs both AOF and snapshot file data/sync operations.
// Uring is native; epoll networking derives the syscall persistence engine (there is no ring).
enum class PersistIoEngine : uint8_t { Normal = 0, Uring = 1 };
// Boot-latched network engine for every IO thread: uring by default, or epoll where
// io_uring is unavailable or unwanted. This choice also selects persistence IO.
enum class NetIoEngine : uint8_t { Uring = 0, Epoll = 1 };
// Boot-latched loop architecture: 2s uses dedicated IO and executor threads; 1s gives
// every selected physical thread both loop objects. split/fused are accepted aliases.
enum class ThreadMode : uint8_t { Split = 0, Fused = 1 };
enum class TlsAuthClients : uint8_t { Yes = 0, No = 1, Optional = 2 };

// Owned scalar encoding settings with static name/alias metadata. Boot or the serialized
// CONFIG writer updates values; apply translates them to owner-local TypeLimits without
// publication. Public ranges saturate at the uint32 representation limit. parse returns
// false for invalid input; it does not promise to preserve its output on failure.
struct EncodingConfig {
    enum Key : uint32_t {
        HashEntries,
        HashValue,
        ListSize,
        SetEntries,
        SetValue,
        ZsetEntries,
        ZsetValue,
        SetIntsetEntries,
        Count
    };
    struct Setting {
        const char* name;
        const char* alias;
        bool memory;
        const char* tomo_alias;
    };
    static constexpr Setting /* TOMO_TOOL_BIND settings */ settings[Count] = {
        {"hash-max-listpack-entries", "hash-max-ziplist-entries", false,
         "hash-max-compact-entries"},
        {"hash-max-listpack-value", "hash-max-ziplist-value", true, "hash-max-compact-value"},
        {"list-max-listpack-size", "list-max-ziplist-size", false, nullptr},
        {"set-max-listpack-entries", nullptr, false, nullptr},
        {"set-max-listpack-value", nullptr, false, nullptr},
        {"zset-max-listpack-entries", "zset-max-ziplist-entries", false,
         "zset-max-compact-entries"},
        {"zset-max-listpack-value", "zset-max-ziplist-value", true, "zset-max-compact-value"},
        {"set-max-intset-entries", nullptr, false, nullptr},
    };
    // Defaults in Key order: hash 512 entries/64 bytes; list -2 (8 KiB payload budget);
    // set 128 entries/64 bytes; zset 128 entries/64 bytes; intset 512 entries.
    // Zero disables the corresponding compact limit except ListSize, where 0 permits one
    // element. ListSize -1 selects 4 KiB; other keys reject -1. Negative list values
    // select byte budgets (below -5 clamps to 64 KiB); positives count elements.
    int64_t values[Count] = {512, 64, -2, 128, 64, 128, 64, 512};

    static int find(Slice name) {
        for (uint32_t i = 0; i < Count; i++)
            if (name.eq_icase(settings[i].name) ||
                (settings[i].alias && name.eq_icase(settings[i].alias)) || legacy(i, name))
                return i;
        return -1;
    }
    static bool legacy(uint32_t key, Slice name) {
        return key < Count && settings[key].tomo_alias && name.eq_icase(settings[key].tomo_alias);
    }
    static bool parse(uint32_t key, Slice input, int64_t& out, bool legacy = false);
    static void apply(TypeLimits& limits, uint32_t key, int64_t value) {
        if (key == ListSize) {
            limits.list = list_compact_limit(static_cast<int32_t>(value));
            return;
        }
        const uint32_t bound = value > UINT32_MAX ? UINT32_MAX : static_cast<uint32_t>(value);
        switch (key) {
            case HashEntries:
                limits.hash.max_entries = bound;
                break;
            case HashValue:
                limits.hash.max_value = bound;
                break;
            case SetEntries:
                limits.set.max_entries = bound;
                break;
            case SetValue:
                limits.set.max_value = bound;
                break;
            // Redis intsetMaxEntries caps the public size_t setting at 1G entries.
            case SetIntsetEntries:
                limits.set_intset_max_entries = bound < (1u << 30) ? bound : (1u << 30);
                break;
            case ZsetEntries:
                limits.zset.max_entries = bound;
                break;
            case ZsetValue:
                limits.zset.max_value = bound;
                break;
            default:
                break;
        }
    }
    TypeLimits type_limits() const {
        TypeLimits limits;
        for (uint32_t i = 0; i < Count; i++) apply(limits, i, values[i]);
        return limits;
    }
};

// Redis's signal policy is a set of flags. Its CONFIG value is split on literal
// spaces (empty tokens are invalid), and its canonical order is fixed.
enum ShutdownFlags : uint8_t {
    ShutdownSaveFlag = 1,
    ShutdownNoSaveFlag = 2,
    ShutdownNowFlag = 4,
    ShutdownForceFlag = 8
};
__attribute__((noipa)) inline bool cfg_shutdown_flags(Slice input, uint8_t& flags,
                                                      const char*& error) {
    flags = 0;
    static constexpr const char* names[] = {"default", "save", "nosave", "now", "force"};
    static constexpr uint8_t values[] = {0, 1, 2, 4, 8};
    for (uint32_t begin = 0;;) {
        uint32_t end = begin;
        while (end < input.n && input.p[end] != ' ') ++end;
        const std::string word(input.p + begin, end - begin);
        bool found = false;
        for (unsigned i = 0; i < 5; ++i) {
            if (!::strcasecmp(word.c_str(), names[i])) {
                flags |= values[i];
                found = true;
                break;
            }
        }
        if (!found) {
            error = "argument(s) must be one of the following: default, save, nosave, now, force";
            return false;
        }
        if (end == input.n) break;
        begin = end + 1;
    }
    if ((flags & (ShutdownSaveFlag | ShutdownNoSaveFlag)) ==
        (ShutdownSaveFlag | ShutdownNoSaveFlag)) {
        error = "shutdown options SAVE and NOSAVE can't be used simultaneously";
        return false;
    }
    return true;
}
__attribute__((noipa)) inline std::string cfg_shutdown_string(uint8_t flags) {
    if (!flags) return "default";
    std::string result;
    static constexpr const char* names[] = {"save", "nosave", "now", "force"};
    for (unsigned i = 0; i < 4; ++i)
        if (flags & (1u << i)) {
            if (!result.empty()) result += ' ';
            result += names[i];
        }
    return result;
}

// Owns boot values and vectors; const char* fields borrow argv or the completed token
// store for their full use lifetime. process_config_id refers to process-wide cold
// storage, not a uniquely owned allocation. Boot parsing is exclusive; live changes
// require CONFIG serialization and explicit Server publication. No synchronization
// is provided by this type, and copying it does not extend borrowed-string lifetimes.
struct Config {
    // Boot placement string; default null derives placement from ratio/allowed CPUs.
    const char* place = nullptr;
    // IO thread count from --ratio; default 0 means unset internally. Explicit ratios
    // require positive IO and EX counts; -1 has no auto meaning and cannot form a valid shape.
    uint32_t even_ifid = 0;
    // EX thread count from --ratio; default 0 means unset internally; same rules as even_ifid.
    uint32_t even_ex = 0;
    // Boot shard:executor_tid map; default null assigns homes; an explicit empty map is invalid.
    const char* shard_home = nullptr;
    // Internal representation of the --shards -1 sentinel.
    static constexpr uint32_t kShardsAuto = UINT32_MAX;
    // Shard count; default -1/auto resolves to min(8 * executors, 256) before recovery.
    // 0 is invalid; explicit values are 1..256.
    uint32_t shards = kShardsAuto;
    // Boot affinity switch; default true. --no-pin (or file pin no) disables pinning.
    // There is no numeric argument or 0/-1 sentinel.
    bool pin_threads = true;
    // Boot key-balancing switch; default 1, 0 disables its signals/windows, -1 invalid.
    // The shared controller is allocated only if either balancer is enabled.
    uint32_t key_lb = 1;
    // Boot client-balancing switch; default 1, 0 disables its signals/windows, -1 invalid.
    uint32_t client_lb = 1;
    // Boot automatic role-split switch; default 0/off, 1 enables, -1 invalid; unavailable
    // in 1s. Only its controller arms fingerprint sampling; trigger bands learn quiet jitter.
    uint32_t flip_auto = 0;
    // TCP port number; default 6379, 0 disables the plaintext listener, -1 invalid.
    uint16_t port = 6379;
    // Boot UNIX socket mode in octal; default 0, 0 skips chmod, -1 invalid; maximum 0777.
    uint16_t unixsocketperm = 0;
    // Listener address string; default "127.0.0.1".
    const char* bind_addr = "127.0.0.1";
    // Boot UNIX listener path; default null/empty disables it.
    const char* unixsocket = nullptr;
    // Live connection count limit; default 10000, 0 and -1 invalid.
    uint32_t maxclients = 10000;
    // Live idle timeout in seconds; default 0/off, -1 invalid.
    uint32_t timeout = 0;
    // Seconds for newly accepted TCP clients; default 300, 0 disables, -1 invalid.
    uint32_t tcp_keepalive = 300;
    // Boot listen(2) queue length; default 511, 0 is passed to listen, -1 invalid.
    uint32_t tcp_backlog = 511;
    // Boot network-engine enum; default uring; accepts uring or epoll.
    NetIoEngine net_io = NetIoEngine::Uring;
    // Internal sidecar handle; default 0 selects static process defaults without allocation.
    uint32_t process_config_id = 0;
    // Live per-class byte/time limits; defaults and 0/-1 rules are in ClientOutputBufferLimits.
    ClientOutputBufferLimits client_output_buffer_limits;
    // Live password bytes; default null/empty disables password authentication.
    const char* requirepass = nullptr;
    // Live yes/no switch; default yes (1). no (0) disables non-loopback protection;
    // numeric strings 0 and -1 are not accepted by the boot parser.
    uint32_t protected_mode = 1;
    // Boot enum; default no; accepts no, yes or local.
    DebugCommandMode enable_debug_command = DebugCommandMode::No;
    // Boot ACL path; default null/empty disables ACL LOAD/SAVE.
    const char* aclfile = nullptr;
    // ACL channel default enum; default resetchannels (0), alternative allchannels (1).
    // Numeric 0 and -1 are not accepted spellings.
    uint32_t acl_pubsub_allchannels = 0;
    // Live per-IO ACL log capacity in entries; default 128, 0 retains none, -1 invalid.
    uint64_t acllog_max_len = 128;
    // Owned repeatable user-name/rules token lists; default empty (no file user directives).
    std::vector<std::vector<std::string>> acl_users;
    // Boot persistence directory; default "."; must be nonempty.
    const char* dir = ".";
    // Boot snapshot filename; default "dump.tomo"; nonempty plain filename required.
    const char* dbfilename = "dump.tomo";
    // Live (seconds, changes) schedule; default (3600,1), (300,100), (60,10000).
    // Empty disables mutation observers/cron; seconds=0 is invalid, changes=0 is accepted,
    // -1 is invalid for either unsigned count. Repeated clauses append within one source.
    std::vector<SaveClause> save{{3600, 1}, {300, 100}, {60, 10000}};
    // AOF yes/no switch; default no. Numeric 0/-1 are invalid spellings.
    bool appendonly = false;
    // AOF sync-policy enum; default everysec; accepts always, everysec or no.
    AppendFsyncPolicy appendfsync = AppendFsyncPolicy::Everysec;
    // Boot mode enum; default 2s/split; also accepts 1s/fused.
    ThreadMode thread_mode = ThreadMode::Split;
    // Boot GET/MGET local-read switch; default 0/off, 1 enables in 1s or shard-less 2s IO,
    // -1 invalid. Armed writes use immutable replacement and QSBR; local replies copy.
    uint32_t read_local = 0;
    // AOF base filename; default "appendonly.aof"; nonempty plain name required.
    const char* appendfilename = "appendonly.aof";
    // AOF directory name; default "appendonlydir"; nonempty plain name required.
    const char* appenddirname = "appendonlydir";
    // Live growth percentage; default 100, 0 disables automatic rewriting, -1 invalid.
    uint32_t auto_aof_rewrite_percentage = 100;
    // Live rewrite minimum in bytes; default 64 MiB, 0 removes this size floor, -1 invalid.
    uint64_t auto_aof_rewrite_min_size = 64ull * 1024 * 1024;
    // Live AOF timestamp yes/no switch; default no; numeric 0/-1 invalid.
    bool aof_timestamp_enabled = false;
    // AOF recovery yes/no policy; default yes; CONFIG changes apply on the next load.
    // Numeric 0/-1 are invalid spellings.
    bool aof_load_truncated = true;
    // Live SIGINT policy flags; default 0 (default policy); accepts default/save/nosave/now/force.
    // Numeric strings 0/-1 are invalid. Accessed through atomic_ref during signal handling.
    uint8_t shutdown_on_sigint = 0;
    // Live SIGTERM flags; default 0; same word grammar and 0/-1 rules as shutdown_on_sigint.
    uint8_t shutdown_on_sigterm = 0;
    // Logical database count; default 16, 0 and -1 invalid; range 1..256.
    uint32_t databases = 16;
    // Live request bulk bound in bytes; default 512 MiB, 0/-1 invalid; range 1 MiB..LONG_MAX.
    // The independent 32-bit Slice/receive-cursor representation still bounds actual frames.
    uint64_t proto_max_bulk_len = 512ull * 1024 * 1024;
    // Live owner-GET borrow threshold in bytes; default 16384, 0 disables, -1 invalid.
    // Multi-key gather uses min(zc-min, ValueSlot::kInline); local-read replies always copy.
    uint32_t zc_min = 16384;
    // Live eviction budget in bytes; default 0 disables eviction-path work, -1 invalid.
    uint64_t maxmemory = 0;
    // Live eviction-policy enum; default noeviction; parse_maxmemory_policy lists accepted names.
    MaxmemoryPolicy maxmemory_policy = MaxmemoryPolicy::NoEviction;
    // Live eviction sample count; default 5, 0/-1 invalid; range 1..64.
    uint32_t maxmemory_samples = 5;
    // Live cross-shard write-group switch; default 0, 1 enables, -1 invalid.
    // Zero leaves EXEC/scripts/read cuts active. Credits derive as min(16 * shards, 1024).
    uint32_t atomic = 0;
    // Live owned collection limits; defaults/units/sentinels are in EncodingConfig.
    // The Lua instruction bound lives in scripting.cc; unused interpreters allocate nothing.
    EncodingConfig encodings;
    // Live notification flag string, stored as bits; default empty/0 disables notifications.
    // Numeric strings 0/-1 are not notification flags.
    uint32_t notify_events = 0;
    // Boot fused shadow-priority switch; default 0 uses allocation-free FIFO, 1 enables,
    // -1 invalid. Split mode resolves either accepted value to 0.
    uint32_t reorder = 0;
    // Live remembered-key count per IO owner; default 1000000, 0 unlimited, -1 invalid.
    // The table allocates only when a connection enables tracking.
    uint64_t tracking_table_max_keys = 1000000;
    // Boot TLS port number; default 0 disables TLS (no SSL_CTX or BIO registry), -1 invalid.
    uint16_t tls_port = 0;
    // Boot certificate path; default null; required when TLS is enabled.
    const char* tls_cert_file = nullptr;
    // Boot private-key path; default null; required when TLS is enabled.
    const char* tls_key_file = nullptr;
    // Boot CA certificate path; default null; one CA file/directory is required for client auth.
    const char* tls_ca_cert_file = nullptr;
    // Boot CA directory path; default null; alternative to tls_ca_cert_file.
    const char* tls_ca_cert_dir = nullptr;
    // Boot client-auth enum; default yes; accepts yes, no or optional.
    TlsAuthClients tls_auth_clients = TlsAuthClients::Yes;
    // Boot TLS protocol list; default null leaves protocol selection to TLS setup.
    const char* tls_protocols = nullptr;
    // Boot TLS cipher list; default null leaves cipher selection to TLS setup.
    const char* tls_ciphers = nullptr;
    // Boot TLS 1.3 suite list; default null leaves suite selection to TLS setup.
    const char* tls_ciphersuites = nullptr;
    // Boot yes/no switch; default no; numeric 0/-1 are invalid spellings.
    bool tls_prefer_server_ciphers = false;
    // Boot HLL sparse promotion limit in bytes; default 3000, 0 permits no sparse growth, -1 invalid.
    uint32_t hll_sparse_max_bytes = 3000;
    // Live slow-log threshold in microseconds; default 10000, 0 logs all, -1 disables.
    int64_t slowlog_log_slower_than = 10000;
    // Live slow-log ring capacity in entries; default 128, 0 retains none, -1 invalid.
    uint64_t slowlog_max_len = 128;
    // Live latency-monitor threshold in milliseconds; default 0/off, -1 invalid.
    uint32_t latency_monitor_threshold = 0;
    // Live histogram yes/no switch; default no; numeric 0/-1 invalid.
    // This default differs from Redis 7.4's yes.
    bool latency_tracking = false;
    // Internal flag; default false selects implicit percentiles; true permits an explicit empty list.
    bool latency_percentiles_explicit = false;
    // Borrowed boot configuration path; default null makes CONFIG REWRITE report no destination.
    const char* conf_path = nullptr;
    // Boot writeback selector; default 1 (composite half rule), 0 flushes all, -1 invalid.
    int32_t wb_policy = wb_rule::default_policy();
    // Live query buffer bound in bytes; default 1 GiB, 0/-1 invalid; range 1 MiB..LONG_MAX.
    uint64_t client_query_buffer_limit = 1024ull * 1024 * 1024;
    // Live node roll-over budgets: default 4096 bytes and 100 entries.
    // Zero disables the corresponding limit; -1 invalid for both uint32 values.
    StreamLimits stream_limits;
    // Boot planner damping level; default -1 derives damping, 0 disables damping,
    // positive values set a level (dimensionless, up to INT32_MAX).
    int32_t key_lb_damping = -1;
    // Boot small-pipeline threshold in operations; default 16, 0 uses the half rule,
    // -1 invalid; range 0..kRobWindow.
    uint32_t wb_small_pipe = wb_rule::kSmallPipe;
    // Boot completion-visit bound; default 3, 0 unbounded, -1 invalid; range 0..255.
    uint32_t wb_complete_visits = wb_rule::kCompleteVisits;
    // Internal borrowed-password byte count; default 0 falls back to strlen for C-string callers.
    uint32_t requirepass_size = 0;
    // Live client-cron frequency in Hz; default 10, 0 clamps to 1, -1 invalid.
    // Accepted 0..INT_MAX is clamped to 1..500 by ClientHz::parse.
    uint32_t hz = ClientHz::kDefault;
    // Live yes/no switch; default yes (1), no (0) disables dynamic frequency scaling.
    // Numeric 0/-1 are invalid spellings.
    uint32_t dynamic_hz = 1;
    // Live locale name; default empty string selects the environment LC_COLLATE.
    const char* locale_collate = "";
    // Owned live percentile list in percent; implicit default 50, 99, 99.9.
    // Explicit empty list suppresses percentile output; 0 is a valid percentile, -1 invalid.
    std::vector<double> latency_tracking_info_percentiles;
};
static_assert(sizeof(Config) == 624, "Config footprint changed; update the documented accounting");

inline const char* cfg_process_value(const Config& cfg, size_t index) {
    return cfg.process_config_id
               ? process_config_values.at(cfg.process_config_id - 1)[index].c_str()
               : process_configs[index].value;
}
inline void cfg_process_store(Config& cfg, size_t index, std::string value) {
    if (!cfg.process_config_id) {
        if (value == process_configs[index].value) return;
        std::array<std::string, kProcessConfigCount> values;
        for (size_t i = 0; i < kProcessConfigCount; ++i) values[i] = process_configs[i].value;
        process_config_values.push_back(std::move(values));
        cfg.process_config_id = process_config_values.size();
    }
    process_config_values.at(cfg.process_config_id - 1)[index] = std::move(value);
}

inline Slice cfg_requirepass(const Config& cfg) {
    const char* password = cfg.requirepass ? cfg.requirepass : "";
    return Slice(password, cfg.requirepass_size ? cfg.requirepass_size : std::strlen(password));
}

// Boot-latched shadow-scheduling capability; the offline layout twin disables it.
bool reorder_available();

// Cold boot selection shared by the executable and serverless fixtures. Split IO
// flushes independently, so shadow priority is enabled only in fused mode.
inline int32_t reorder_for_mode(int32_t requested, ThreadMode mode) {
    return mode == ThreadMode::Fused ? requested : 0;
}

inline constexpr uint32_t cfg_default_shards(uint32_t executors) {
    return executors >= 32 ? 256 : 8 * executors;
}

// epoll owns no io_uring ring and therefore uses syscall persistence IO.
inline PersistIoEngine persistence_engine(const Config& cfg) {
    return cfg.net_io == NetIoEngine::Epoll ? PersistIoEngine::Normal : PersistIoEngine::Uring;
}

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

// Signed scalar grammar accepts an optional sign and the full int64 range, including -1.
inline bool cfg_parse_i64(const char* s, int64_t& out) {
    if (!s || !*s) return false;
    const bool negative = *s == '-';
    const char* p = (negative || *s == '+') ? s + 1 : s;
    if (!*p) return false;
    uint64_t v = 0;
    for (; *p; p++) {
        if (*p < '0' || *p > '9') return false;
        const uint32_t digit = static_cast<uint32_t>(*p - '0');
        if (v > (UINT64_MAX - digit) / 10) return false;
        v = v * 10 + digit;
    }
    const uint64_t limit = negative ? (uint64_t{1} << 63) : (uint64_t{1} << 63) - 1;
    if (v > limit) return false;
    // INT64_MIN has no positive counterpart. Avoid negating it: even rejected values such as
    // INT64_MIN must not execute undefined behavior.
    out = negative ? (v == (uint64_t{1} << 63) ? std::numeric_limits<int64_t>::min()
                                               : -static_cast<int64_t>(v))
                   : static_cast<int64_t>(v);
    return true;
}

// Redis string2ll's canonical decimal grammar. Keep this separate from the
// permissive parser used by save schedules and Tomo-only numeric controls.
inline bool cfg_parse_integer(Slice s, int64_t& out) {
    if (!s.n) return false;
    const uint32_t start = s.p[0] == '-' ? 1 : 0;
    if (start == s.n || s.p[start] < '0' || s.p[start] > '9' ||
        (s.p[start] == '0' && (start || s.n != 1)))
        return false;
    const auto parsed = std::from_chars(s.p, s.p + s.n, out);
    return parsed.ec == std::errc{} && parsed.ptr == s.p + s.n;
}

inline bool cfg_parse_redis_i64(Slice s, int64_t& out) { return s.p && cfg_parse_integer(s, out); }

template <class T>
inline bool cfg_parse_redis_unsigned(Slice s, T& out) {
    int64_t value = 0;
    if (!cfg_parse_redis_i64(s, value) || value < 0 ||
        static_cast<uint64_t>(value) > std::numeric_limits<T>::max())
        return false;
    out = static_cast<T>(value);
    return true;
}

// These consumers have a locked uint32 ABI. Redis itself permits signed-64-bit ceilings;
// keep its integer/memory grammar and diagnostic form, but report our supported bound honestly.
inline bool cfg_parse_u32_limit(Slice input, bool memory, uint32_t& out, const char*& error) {
    const std::string text(input.p, input.n);
    int64_t integer = 0;
    const bool canonical = cfg_parse_i64(text.c_str(), integer) && std::to_string(integer) == text;
    uint64_t value = 0;
    if (canonical) {
        value = static_cast<uint64_t>(integer);
    } else if (memory) {
        // Redis also accepts an empty memory value or a bare suffix as zero.
        if (!input.n || cfg_memory_suffix(input.p, input.n, "b") ||
            cfg_memory_suffix(input.p, input.n, "k") || cfg_memory_suffix(input.p, input.n, "kb") ||
            cfg_memory_suffix(input.p, input.n, "m") || cfg_memory_suffix(input.p, input.n, "mb") ||
            cfg_memory_suffix(input.p, input.n, "g") || cfg_memory_suffix(input.p, input.n, "gb")) {
            value = 0;
        } else if (!cfg_parse_memory(input.p, input.n, value)) {
            error = "argument must be a memory value";
            return false;
        }
    } else {
        error = "argument couldn't be parsed into an integer";
        return false;
    }
    if (value > UINT32_MAX) {
        error = "argument must be between 0 and 4294967295 inclusive";
        return false;
    }
    out = static_cast<uint32_t>(value);
    return true;
}

inline bool EncodingConfig::parse(uint32_t key, Slice input, int64_t& out, bool legacy) {
    if (key >= Count) return false;
    // TomoKV aliases accept bare uint32 decimals, including leading zeroes. Redis spellings
    // use the full reference range and grammar below; both paths share storage.
    if (legacy) {
        if (!input.n) return false;
        uint64_t value = 0;
        for (uint32_t i = 0; i < input.n; i++) {
            if (input.p[i] < '0' || input.p[i] > '9') return false;
            value = value * 10 + static_cast<uint32_t>(input.p[i] - '0');
            if (value > UINT32_MAX) return false;
        }
        out = static_cast<int64_t>(value);
        return true;
    }
    if (settings[key].memory) {
        uint64_t bytes = 0;
        // Redis memtoull also accepts a bare unit (and the empty string) as zero.
        // Preserve that grammar here without broadening unrelated TomoKV controls.
        if (!input.n || cfg_memory_suffix(input.p, input.n, "b") ||
            cfg_memory_suffix(input.p, input.n, "k") || cfg_memory_suffix(input.p, input.n, "kb") ||
            cfg_memory_suffix(input.p, input.n, "m") || cfg_memory_suffix(input.p, input.n, "mb") ||
            cfg_memory_suffix(input.p, input.n, "g") || cfg_memory_suffix(input.p, input.n, "gb"))
            bytes = 0;
        else if (!cfg_parse_memory(input.p, input.n, bytes))
            return false;
        if (bytes > static_cast<uint64_t>(LONG_MAX)) return false;
        out = static_cast<int64_t>(bytes);
        return true;
    }
    // Redis integer spellings require canonical decimal, unlike cfg_parse_i64.
    if (!input.n || input.p[0] == '+') return false;
    const std::string text(input.p, input.n);
    if (!cfg_parse_i64(text.c_str(), out) || std::to_string(out) != text) return false;
    return key == ListSize ? out >= INT_MIN && out <= INT_MAX : out >= 0 && out <= LONG_MAX;
}

// Boot-owned source precedence, shared across directives in one parse. --ratio and
// --place are mutually exclusive within a source; a later source replaces the earlier
// choice. No pointers, publication or synchronization; parsing errors may leave progress.
struct ConfigParseState {
    int ratio_source = 0;  // 0 = unset, 1 = conf, 2 = cli
    int place_source = 0;
    int save_source = 0;
};

// Keep this boot-only conversion out of the already large parser/IO translation unit.
__attribute__((noipa)) inline bool cfg_parse_key_lb_damping(const char* value, int32_t& out) {
    int64_t level;
    if (!cfg_parse_i64(value, level) || level < -1 || level > INT32_MAX ||
        std::to_string(level) != value)
        return false;
    out = static_cast<int32_t>(level);
    return true;
}

enum : int { kConfigParsed = 0, kConfigError = 1, kConfigHelp = 2 };

// Parse one boot token stream (without argv[0]) into cfg under exclusive caller access.
// source is 1 for file directives or 2 for CLI; st carries precedence across calls.
// args and optional lengths must align, and borrowed token storage must outlive cfg.
// Writes cfg, process sidecars and the global hash choice without worker publication.
// Returns Parsed/Help/Error and prints diagnostics; earlier options are not rolled back.
// Most allocation failures propagate; the user-directive branch converts bad_alloc to Error.
inline int /* TOMO_TOOL_BIND parse_config_args */ parse_config_args(
    const std::vector<const char*>& args, Config& cfg, ConfigParseState& st, int source,
    const char* prog, const std::vector<size_t>* lengths = nullptr,
    std::FILE* diagnostics = stderr) {
    // Phase 1: walk tokens with length-aware value access and source precedence.
    const int argc = static_cast<int>(args.size());
    for (int i = 0; i < argc; i++) {
        auto next = [&](const char* d) { return (i + 1 < argc) ? args[++i] : d; };
        auto value_slice = [&](const char* value) {
            return Slice(value, value ? (lengths ? (*lengths)[i] : std::strlen(value)) : 0);
        };
        auto next_integer = [&] { return value_slice(next(nullptr)); };
        const char* a = args[i];
        // Phase 2: dispatch process and encoding settings through their shared metadata.
        const int process =
            !std::strncmp(a, "--", 2) ? cfg_process_find(Slice(a + 2, std::strlen(a + 2))) : -1;
        if (process >= 0) {
            const char* value = next(nullptr);
            std::string normalized, error;
            if (!value || !cfg_process_normalize(process, value_slice(value), normalized, error)) {
                std::fprintf(diagnostics, "%s: %s\n", a,
                             value ? error.c_str() : "wrong number of arguments");
                return kConfigError;
            }
            cfg_process_store(cfg, process, std::move(normalized));
            continue;
        }
        const int encoding =
            !std::strncmp(a, "--", 2) ? EncodingConfig::find(Slice(a + 2, std::strlen(a + 2))) : -1;
        if (encoding >= 0) {
            const char* value = next(nullptr);
            int64_t parsed = 0;
            if (!value || !EncodingConfig::parse(
                              encoding, value_slice(value), parsed,
                              EncodingConfig::legacy(encoding, Slice(a + 2, std::strlen(a + 2))))) {
                std::fprintf(diagnostics, "%s has an invalid encoding limit\n", a);
                return kConfigError;
            }
            cfg.encodings.values[encoding] = parsed;
            continue;
        }
        // Phase 3: apply network, security and observability options in parser order.
        if (!std::strcmp(a, "--port")) {
            uint32_t value = 0;
            if (!cfg_parse_redis_unsigned(next_integer(), value) || value > UINT16_MAX) {
                std::fprintf(diagnostics, "--port must be between 0 and %u\n", UINT16_MAX);
                return kConfigError;
            }
            cfg.port = static_cast<uint16_t>(value);
        } else if (!std::strcmp(a, "--tls-port")) {
            uint32_t value = 0;
            if (!cfg_parse_redis_unsigned(next_integer(), value) || value > UINT16_MAX) {
                std::fprintf(diagnostics, "--tls-port must be between 0 and %u\n", UINT16_MAX);
                return kConfigError;
            }
            cfg.tls_port = static_cast<uint16_t>(value);
        } else if (!std::strcmp(a, "--tls-cert-file"))
            cfg.tls_cert_file = next("");
        else if (!std::strcmp(a, "--tls-key-file"))
            cfg.tls_key_file = next("");
        else if (!std::strcmp(a, "--tls-ca-cert-file"))
            cfg.tls_ca_cert_file = next("");
        else if (!std::strcmp(a, "--tls-ca-cert-dir"))
            cfg.tls_ca_cert_dir = next("");
        else if (!std::strcmp(a, "--tls-auth-clients")) {
            const char* value = next(nullptr);
            if (cfg_eq_icase(value, "yes"))
                cfg.tls_auth_clients = TlsAuthClients::Yes;
            else if (cfg_eq_icase(value, "no"))
                cfg.tls_auth_clients = TlsAuthClients::No;
            else if (cfg_eq_icase(value, "optional"))
                cfg.tls_auth_clients = TlsAuthClients::Optional;
            else {
                std::fprintf(diagnostics, "--tls-auth-clients wants yes, no or optional\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--tls-protocols"))
            cfg.tls_protocols = next("");
        else if (!std::strcmp(a, "--tls-ciphers"))
            cfg.tls_ciphers = next("");
        else if (!std::strcmp(a, "--tls-ciphersuites"))
            cfg.tls_ciphersuites = next("");
        else if (!std::strcmp(a, "--tls-prefer-server-ciphers")) {
            const char* value = next(nullptr);
            if (cfg_eq_icase(value, "yes"))
                cfg.tls_prefer_server_ciphers = true;
            else if (cfg_eq_icase(value, "no"))
                cfg.tls_prefer_server_ciphers = false;
            else {
                std::fprintf(diagnostics, "--tls-prefer-server-ciphers wants yes or no\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--bind"))
            cfg.bind_addr = next("127.0.0.1");
        else if (!std::strcmp(a, "--unixsocket"))
            cfg.unixsocket = next("");
        else if (!std::strcmp(a, "--unixsocketperm")) {
            if (!cfg_parse_unixsocketperm(next(nullptr), cfg.unixsocketperm)) {
                std::fprintf(diagnostics,
                             "--unixsocketperm wants an octal mode between 0 and 777\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--maxclients")) {
            if (!cfg_parse_redis_unsigned(next_integer(), cfg.maxclients) || cfg.maxclients == 0) {
                std::fprintf(diagnostics, "--maxclients must be between 1 and %u\n", UINT32_MAX);
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--timeout")) {
            if (!cfg_parse_redis_unsigned(next_integer(), cfg.timeout) || cfg.timeout > INT_MAX) {
                std::fprintf(diagnostics, "--timeout must be between 0 and %d\n", INT_MAX);
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--hz")) {
            const char* value = next(nullptr);
            const char* error = "wrong number of arguments";
            if (!value || !ClientHz::parse(value_slice(value), cfg.hz, error)) {
                std::fprintf(diagnostics, "--hz: %s\n", error);
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--dynamic-hz")) {
            const char* value = next(nullptr);
            if (cfg_eq_icase(value, "yes"))
                cfg.dynamic_hz = 1;
            else if (cfg_eq_icase(value, "no"))
                cfg.dynamic_hz = 0;
            else {
                std::fprintf(diagnostics, "--dynamic-hz: argument must be 'yes' or 'no'\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--tcp-keepalive")) {
            if (!cfg_parse_redis_unsigned(next_integer(), cfg.tcp_keepalive) ||
                cfg.tcp_keepalive > INT_MAX) {
                std::fprintf(diagnostics, "--tcp-keepalive must be between 0 and %d\n", INT_MAX);
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--tcp-backlog")) {
            if (!cfg_parse_redis_unsigned(next_integer(), cfg.tcp_backlog) ||
                cfg.tcp_backlog > INT_MAX) {
                std::fprintf(diagnostics, "--tcp-backlog must be between 0 and %d\n", INT_MAX);
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--client-output-buffer-limit")) {
            const int begin = i + 1;
            int end = begin;
            while (end < argc && (source == 1 || std::strncmp(args[end], "--", 2) != 0)) end++;
            std::vector<std::string> words;
            for (int arg = begin; arg < end; arg++) {
                const char* p = args[arg];
                while (*p) {
                    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
                    const char* start = p;
                    while (*p && *p != ' ' && *p != '\t' && *p != '\r' && *p != '\n') p++;
                    if (p != start) words.emplace_back(start, static_cast<size_t>(p - start));
                }
            }
            std::vector<const char*> values;
            values.reserve(words.size());
            for (const std::string& word : words) values.push_back(word.c_str());
            // The parser stages internally and commits only on success; no outer copy needed.
            const char* error = nullptr;
            if (!cfg_parse_client_output_buffer_limit(values.data(), values.size(),
                                                      cfg.client_output_buffer_limits, error)) {
                std::fprintf(diagnostics, "--client-output-buffer-limit: %s\n", error);
                return kConfigError;
            }
            i = end - 1;
        } else if (!std::strcmp(a, "--requirepass")) {
            const char* value = next(nullptr);
            if (!value) {
                std::fprintf(diagnostics, "wrong number of arguments\n");
                return kConfigError;
            }
            cfg.requirepass = value;
            cfg.requirepass_size = lengths ? (*lengths)[i] : std::strlen(value);
        } else if (!std::strcmp(a, "--aclfile"))
            cfg.aclfile = next("");
        else if (!std::strcmp(a, "--user")) {
            const int begin = i + 1;
            int end = begin;
            while (end < argc && (source == 1 || std::strncmp(args[end], "--", 2) != 0)) end++;
            if (end - begin < 1) {
                std::fprintf(diagnostics, "--user requires a username\n");
                return kConfigError;
            }
            std::vector<std::string> definition;
            try {
                for (int arg = begin; arg < end; arg++)
                    definition.emplace_back(args[arg],
                                            lengths ? (*lengths)[arg] : std::strlen(args[arg]));
                cfg.acl_users.push_back(std::move(definition));
            } catch (const std::bad_alloc&) {
                std::fprintf(diagnostics, "out of memory parsing --user\n");
                return kConfigError;
            }
            i = end - 1;
        } else if (!std::strcmp(a, "--acl-pubsub-default")) {
            const char* value = next(nullptr);
            if (value && cfg_eq_icase(value, "allchannels"))
                cfg.acl_pubsub_allchannels = 1;
            else if (value && cfg_eq_icase(value, "resetchannels"))
                cfg.acl_pubsub_allchannels = 0;
            else {
                std::fprintf(diagnostics,
                             "--acl-pubsub-default wants allchannels or resetchannels\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--acllog-max-len")) {
            if (!cfg_parse_redis_unsigned(next_integer(), cfg.acllog_max_len)) {
                std::fprintf(diagnostics, "--acllog-max-len wants an unsigned integer\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--slowlog-log-slower-than")) {
            if (!cfg_parse_redis_i64(next_integer(), cfg.slowlog_log_slower_than) ||
                cfg.slowlog_log_slower_than < -1) {
                std::fprintf(diagnostics,
                             "--slowlog-log-slower-than wants microseconds, -1 to disable\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--slowlog-max-len")) {
            if (!cfg_parse_redis_unsigned(next_integer(), cfg.slowlog_max_len)) {
                std::fprintf(diagnostics, "--slowlog-max-len wants an unsigned integer\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--latency-tracking")) {
            const char* value = next(nullptr);
            if (cfg_eq_icase(value, "yes"))
                cfg.latency_tracking = true;
            else if (cfg_eq_icase(value, "no"))
                cfg.latency_tracking = false;
            else {
                std::fprintf(diagnostics, "%s: argument must be 'yes' or 'no'\n", a);
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--latency-tracking-info-percentiles")) {
            const int begin = i + 1;
            int end = begin;
            while (end < argc && (source == 1 || std::strncmp(args[end], "--", 2))) ++end;
            std::vector<std::string> tokens;
            if (end == begin + 1 && args[begin][0]) {
                if (!cfg_split_args(args[begin], tokens)) {
                    std::fprintf(diagnostics,
                                 "%s: Invalid latency-tracking-info-percentiles parameters\n", a);
                    return kConfigError;
                }
            } else
                for (int j = begin; j < end; ++j)
                    tokens.emplace_back(args[j], lengths ? (*lengths)[j] : std::strlen(args[j]));
            if (tokens.size() == 1 && tokens[0].empty()) tokens.clear();
            cfg.latency_tracking_info_percentiles.clear();
            for (const auto& token : tokens) {
                std::vector<double> one;
                const char* error = nullptr;
                if (!cfg_latency_percentiles(Slice(token.data(), token.size()), one, error) ||
                    one.size() != 1) {
                    std::fprintf(
                        diagnostics, "%s: %s\n", a,
                        error ? error : "Invalid latency-tracking-info-percentiles parameters");
                    return kConfigError;
                }
                cfg.latency_tracking_info_percentiles.push_back(one[0]);
            }
            cfg.latency_percentiles_explicit = true;
            i = end - 1;
        } else if (!std::strcmp(a, "--latency-monitor-threshold")) {
            const char* value = next("");
            const char* error = nullptr;
            if (!cfg_parse_u32_limit(value_slice(value), false, cfg.latency_monitor_threshold,
                                     error)) {
                std::fprintf(diagnostics, "%s: %s\n", a, error);
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--protected-mode")) {
            const char* value = next(nullptr);
            if (cfg_eq_icase(value, "yes"))
                cfg.protected_mode = 1;
            else if (cfg_eq_icase(value, "no"))
                cfg.protected_mode = 0;
            else {
                std::fprintf(diagnostics, "--protected-mode wants yes or no\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--enable-debug-command")) {
            const char* value = next(nullptr);
            if (value && !std::strcmp(value, "no"))
                cfg.enable_debug_command = DebugCommandMode::No;
            else if (value && !std::strcmp(value, "yes"))
                cfg.enable_debug_command = DebugCommandMode::Yes;
            else if (value && !std::strcmp(value, "local"))
                cfg.enable_debug_command = DebugCommandMode::Local;
            else {
                std::fprintf(diagnostics, "--enable-debug-command wants no, yes or local\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--thread-mode")) {
            const char* value = next(nullptr);
            if (value && (!std::strcmp(value, "2s") || !std::strcmp(value, "split")))
                cfg.thread_mode = ThreadMode::Split;
            else if (value && (!std::strcmp(value, "1s") || !std::strcmp(value, "fused")))
                cfg.thread_mode = ThreadMode::Fused;
            else {
                std::fprintf(diagnostics,
                             "--thread-mode wants 2s or 1s (split/fused are aliases)\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--read-local")) {
            if (!cfg_parse_u32(next(nullptr), cfg.read_local) || cfg.read_local > 1) {
                std::fprintf(diagnostics, "--read-local wants 0 or 1\n");
                return kConfigError;
            }
        }
        // Phase 4: resolve placement and execution controls, then persistence and data limits.
        // Role counts span the whole server; placement spreads them across L3 domains.
        else if (!std::strcmp(a, "--ratio")) {
            if (st.place_source == source) {
                std::fprintf(diagnostics, "--ratio and --place are mutually exclusive\n");
                return kConfigError;
            }
            if (st.place_source) {
                cfg.place = nullptr;
                st.place_source = 0;
            }
            st.ratio_source = source;
            const char* v = next("");
            unsigned a2 = 0, b = 0, c = 0;
            const int got = std::sscanf(v, "%u:%u:%u", &a2, &b, &c);
            if (got != 2 || a2 == 0 || b == 0) {
                std::fprintf(
                    diagnostics,
                    "--ratio wants global ifid:ex (e.g. 30:34); 3s was deleted 2026-08-24\n");
                return kConfigError;
            }
            cfg.even_ifid = a2;
            cfg.even_ex = b;
        } else if (!std::strcmp(a, "--shards")) {
            // Accept a complete uint32 decimal or exactly -1; partial numeric strings are invalid.
            const char* value = next(nullptr);
            if (value && !std::strcmp(value, "-1"))
                cfg.shards = Config::kShardsAuto;
            else if (!cfg_parse_u32(value, cfg.shards) || cfg.shards == 0 || cfg.shards > 256) {
                std::fprintf(diagnostics, "--shards wants -1 (auto) or 1..256\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--reorder")) {
            const char* value = next(nullptr);
            if (!cfg_parse_u32(value, cfg.reorder) || cfg.reorder > 1) {
                std::fprintf(diagnostics, "--reorder wants 0 or 1\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--wb-policy")) {
            const char* value = next(nullptr);
            if (!value || (std::strcmp(value, "0") && std::strcmp(value, "1"))) {
                std::fprintf(diagnostics, "--wb-policy wants 0 or 1\n");
                return kConfigError;
            }
            cfg.wb_policy = std::atoi(value);
        } else if (!std::strcmp(a, "--wb-small-pipe") || !std::strcmp(a, "--wb-complete-visits")) {
            const bool small = !std::strcmp(a, "--wb-small-pipe");
            const char* value = next(nullptr);
            const char* error = nullptr;
            uint32_t parsed = 0;
            const unsigned limit = small ? kRobWindow : UINT8_MAX;
            if (!value || !cfg_parse_u32_limit(value_slice(value), false, parsed, error) ||
                parsed > limit) {
                std::fprintf(diagnostics, "%s wants an integer in 0..%u\n", a, limit);
                return kConfigError;
            }
            (small ? cfg.wb_small_pipe : cfg.wb_complete_visits) = parsed;
        } else if (!std::strcmp(a, "--key-lb")) {
            if (!cfg_parse_u32(next(nullptr), cfg.key_lb) || cfg.key_lb > 1) {
                std::fprintf(diagnostics, "--key-lb wants 0 or 1\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--key-lb-damping")) {
            if (!cfg_parse_key_lb_damping(next(nullptr), cfg.key_lb_damping)) {
                std::fprintf(diagnostics, "--key-lb-damping wants -1, 0 or a positive integer\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--client-lb")) {
            if (!cfg_parse_u32(next(nullptr), cfg.client_lb) || cfg.client_lb > 1) {
                std::fprintf(diagnostics, "--client-lb wants 0 or 1\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--flip-auto")) {
            if (!cfg_parse_u32(next(nullptr), cfg.flip_auto) || cfg.flip_auto > 1) {
                std::fprintf(diagnostics, "--flip-auto wants 0 or 1\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--maxmemory")) {
            if (!cfg_parse_memory(next(nullptr), cfg.maxmemory)) {
                std::fprintf(diagnostics, "--maxmemory wants a Redis memory value (0 disables)\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--maxmemory-policy")) {
            const char* value = next(nullptr);
            if (!value || !parse_maxmemory_policy(value, cfg.maxmemory_policy)) {
                std::fprintf(diagnostics, "--maxmemory-policy wants a Redis maxmemory policy\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--maxmemory-samples")) {
            if (!cfg_parse_redis_unsigned(next_integer(), cfg.maxmemory_samples) ||
                cfg.maxmemory_samples == 0 || cfg.maxmemory_samples > 64) {
                std::fprintf(diagnostics, "--maxmemory-samples must be between 1 and 64\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--notify-keyspace-events")) {
            const char* value = next(nullptr);
            const Slice input(value ? value : "", value ? std::strlen(value) : 0);
            uint32_t parsed = 0;
            if (!value || !parse_notify_flags(input, parsed)) {
                std::fprintf(diagnostics, "--notify-keyspace-events contains an invalid flag\n");
                return kConfigError;
            }
            cfg.notify_events = parsed;
        } else if (!std::strcmp(a, "--tracking-table-max-keys")) {
            if (!cfg_parse_redis_unsigned(next_integer(), cfg.tracking_table_max_keys)) {
                std::fprintf(diagnostics,
                             "--tracking-table-max-keys wants an unsigned key count\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--save")) {
            const int begin = i + 1;
            int end = begin;
            while (end < argc && (source == 1 || std::strncmp(args[end], "--", 2) != 0)) end++;
            if (begin == end) {
                std::fprintf(diagnostics, "--save wants an empty value or seconds/changes pairs\n");
                return kConfigError;
            }
            std::string flat;
            for (int arg = begin; arg < end; arg++) {
                if (!flat.empty()) flat.push_back(' ');
                flat += args[arg];
            }
            std::vector<SaveClause> parsed;
            if (!cfg_parse_save_schedule(flat.data(), flat.size(), parsed)) {
                std::fprintf(diagnostics, "Invalid save parameters\n");
                return kConfigError;
            }
            if (st.save_source != source) {
                cfg.save.clear();
                st.save_source = source;
            }
            // An explicit empty value resets the accumulated schedule. Non-empty repeated clauses
            // append within one source, matching repeated redis.conf `save` directives.
            if (flat.empty())
                cfg.save.clear();
            else
                cfg.save.insert(cfg.save.end(), parsed.begin(), parsed.end());
            i = end - 1;
        } else if (!std::strcmp(a, "--databases")) {
            uint32_t value = 0;
            if (!cfg_parse_redis_unsigned(next_integer(), value) || (value < 1 || value > 256)) {
                std::fprintf(diagnostics, "--databases must be between 1 and 256\n");
                return kConfigError;
            }
            cfg.databases = value;
        } else if (!std::strcmp(a, "--client-query-buffer-limit")) {
            const char* input = next(nullptr);
            const char* error = "argument must be a memory value";
            if (!input || !cfg_parse_query_buffer_limit(input, std::strlen(input),
                                                        cfg.client_query_buffer_limit, error)) {
                std::fprintf(diagnostics, "--client-query-buffer-limit: %s\n", error);
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--locale-collate")) {
            cfg.locale_collate = next(nullptr);
            if (!cfg.locale_collate) return kConfigError;
        } else if (!std::strcmp(a, "--proto-max-bulk-len")) {
            uint64_t value = 0;
            if (!cfg_parse_memory(next(nullptr), value) || value < kProtoMinBulkLen ||
                value > kProtoMaxBulkLenSupported) {
                std::fprintf(diagnostics,
                             "--proto-max-bulk-len must be between %llu and %llu bytes\n",
                             static_cast<unsigned long long>(kProtoMinBulkLen),
                             static_cast<unsigned long long>(kProtoMaxBulkLenSupported));
                return kConfigError;
            }
            cfg.proto_max_bulk_len = value;
        } else if (!std::strcmp(a, "--dir"))
            cfg.dir = next(".");
        else if (!std::strcmp(a, "--dbfilename"))
            cfg.dbfilename = next("dump.tomo");
        else if (!std::strcmp(a, "--shutdown-on-sigint") ||
                 !std::strcmp(a, "--shutdown-on-sigterm")) {
            const char* value = next(nullptr);
            std::string words = value ? value : "";
            while (i + 1 < argc && (source == 1 || std::strncmp(args[i + 1], "--", 2))) {
                words += ' ';
                words += args[++i];
            }
            uint8_t flags = 0;
            const char* error = nullptr;
            if (!cfg_shutdown_flags(Slice(words.data(), words.size()), flags, error)) {
                std::fprintf(diagnostics, "%s: %s\n", a, error);
                return kConfigError;
            }
            (!std::strcmp(a, "--shutdown-on-sigint") ? cfg.shutdown_on_sigint
                                                     : cfg.shutdown_on_sigterm) = flags;
        } else if (!std::strcmp(a, "--appendonly")) {
            const char* value = next(nullptr);
            if (cfg_eq_icase(value, "yes"))
                cfg.appendonly = true;
            else if (cfg_eq_icase(value, "no"))
                cfg.appendonly = false;
            else {
                std::fprintf(diagnostics, "--appendonly wants yes or no\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--appendfsync")) {
            const char* value = next(nullptr);
            if (cfg_eq_icase(value, "always"))
                cfg.appendfsync = AppendFsyncPolicy::Always;
            else if (cfg_eq_icase(value, "everysec"))
                cfg.appendfsync = AppendFsyncPolicy::Everysec;
            else if (cfg_eq_icase(value, "no"))
                cfg.appendfsync = AppendFsyncPolicy::No;
            else {
                std::fprintf(diagnostics, "--appendfsync wants always, everysec or no\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--net-io")) {
            const char* value = next(nullptr);
            if (cfg_eq_icase(value, "uring"))
                cfg.net_io = NetIoEngine::Uring;
            else if (cfg_eq_icase(value, "epoll"))
                cfg.net_io = NetIoEngine::Epoll;
            else {
                std::fprintf(diagnostics, "--net-io wants uring or epoll\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--appendfilename"))
            cfg.appendfilename = next("appendonly.aof");
        else if (!std::strcmp(a, "--appenddirname"))
            cfg.appenddirname = next("appendonlydir");
        else if (!std::strcmp(a, "--auto-aof-rewrite-percentage")) {
            if (!cfg_parse_redis_unsigned(next_integer(), cfg.auto_aof_rewrite_percentage) ||
                cfg.auto_aof_rewrite_percentage > INT_MAX) {
                std::fprintf(diagnostics,
                             "--auto-aof-rewrite-percentage wants an unsigned integer\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--auto-aof-rewrite-min-size")) {
            if (!cfg_parse_memory(next(nullptr), cfg.auto_aof_rewrite_min_size) ||
                cfg.auto_aof_rewrite_min_size > INT64_MAX) {
                std::fprintf(diagnostics, "--auto-aof-rewrite-min-size wants a byte count\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--aof-use-rdb-preamble")) {
            const char* value = next(nullptr);
            if (!cfg_eq_icase(value, "yes")) {
                std::fprintf(
                    diagnostics,
                    "aof-use-rdb-preamble no is unsupported: the AOF base file is a TomoKV snapshot\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--aof-timestamp-enabled")) {
            const char* value = next(nullptr);
            if (cfg_eq_icase(value, "yes"))
                cfg.aof_timestamp_enabled = true;
            else if (cfg_eq_icase(value, "no"))
                cfg.aof_timestamp_enabled = false;
            else {
                std::fprintf(diagnostics, "--aof-timestamp-enabled wants yes or no\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--aof-load-truncated")) {
            const char* value = next(nullptr);
            if (cfg_eq_icase(value, "yes"))
                cfg.aof_load_truncated = true;
            else if (cfg_eq_icase(value, "no"))
                cfg.aof_load_truncated = false;
            else {
                std::fprintf(diagnostics, "--aof-load-truncated wants yes or no\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--hll-sparse-max-bytes")) {
            uint64_t value = 0;
            if (!cfg_parse_memory(next(nullptr), value) || value > UINT32_MAX) {
                std::fprintf(diagnostics,
                             "--hll-sparse-max-bytes wants a byte count between 0 and %u\n",
                             UINT32_MAX);
                return kConfigError;
            }
            cfg.hll_sparse_max_bytes = static_cast<uint32_t>(value);
        } else if (!std::strcmp(a, "--stream-node-max-bytes") ||
                   !std::strcmp(a, "--stream-node-max-entries")) {
            const bool memory = !std::strcmp(a, "--stream-node-max-bytes");
            const char* value = next(nullptr);
            const char* error = "missing argument";
            uint32_t& limit =
                memory ? cfg.stream_limits.node_max_bytes : cfg.stream_limits.node_max_entries;
            if (!value || !cfg_parse_u32_limit(value_slice(value), memory, limit, error)) {
                std::fprintf(diagnostics, "%s: %s\n", a, error);
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--zc-min")) {
            const char* v = next(nullptr);
            if (!cfg_parse_u32(v, cfg.zc_min)) {
                std::fprintf(
                    diagnostics,
                    "--zc-min wants a uint32 byte count (0 disables; 16384 suggested when enabled)\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--atomic")) {
            if (!cfg_parse_u32(next(nullptr), cfg.atomic) || cfg.atomic > 1) {
                std::fprintf(diagnostics, "--atomic wants 0 or 1\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--shard-home"))
            cfg.shard_home = next("");
        else if (!std::strcmp(a, "--no-pin"))
            cfg.pin_threads = false;
        else if (!std::strcmp(a, "--hash")) {
            const char* h = next("mix64");
            if (!std::strcmp(h, "mix64"))
                g_hash_kind = HashKind::Mix64Seeded;
            else if (!std::strcmp(h, "siphash"))
                g_hash_kind = HashKind::SipHash12;
            else {
                std::fprintf(diagnostics, "--hash must be mix64 | siphash\n");
                return kConfigError;
            }
        } else if (!std::strcmp(a, "--place")) {
            if (st.ratio_source == source) {
                std::fprintf(diagnostics, "--ratio and --place are mutually exclusive\n");
                return kConfigError;
            }
            if (st.ratio_source) {
                cfg.even_ifid = cfg.even_ex = 0;
                st.ratio_source = 0;
            }
            st.place_source = source;
            cfg.place = next("");
        } else if (!std::strcmp(a, "--help")) {
            // Phase 5: report help or reject an unmatched option.
            std::printf(
                "usage: %s [conf-file] [--port N] [--bind A] [--unixsocket PATH]\n"
                "       [--shards N] [--zc-min N] [--no-pin]\n"
                "  conf file: `name value` per line, # comments; same names as the flags\n"
                "  without the leading --; `pin no` spells --no-pin. CLI flags override the\n"
                "  file. See tomokv.conf in the repo root for the annotated full set.\n"
                "  threading: --thread-mode 2s|1s --read-local 0|1 (defaults 2s, 0)\n"
                "             (split/fused are mode aliases)\n"
                "    --reorder 0|1 (default 0) fused off/on shadow priority; 2s stays FIFO\n"
                "    --wb-policy 0|1 (default 1) flush-all|composite half\n"
                "    --wb-small-pipe 0..64 (default 16; 0 = half rule)\n"
                "    --wb-complete-visits 0..255 (default 3; 0 = unbounded)\n"
                "  placement (default derived from allowed CPUs):\n"
                "    --ratio io:ex               global counts, split mode only\n"
                "    --place role@cpu,...        explicit CPUs; roles are ifid, ex\n"
                "    --shards -1|N               default auto: min(8*executors, 256)\n"
                "    --shard-home shard:tid,...  complete shard-to-executor map; allows empty fillers\n"
                "  load balancing: --key-lb 0|1 --client-lb 0|1 (both default 1)\n"
                "  key planner: --key-lb-damping -1|0|N (default -1, 0 = PRE policy)\n"
                "  flip controller: --flip-auto 0|1\n"
                "    --zc-min N                  owner GET borrows at >= N bytes (0=off; local reads copy)\n"
                "  cache: --maxmemory BYTES --maxmemory-policy POLICY\n"
                "         --maxmemory-samples N (1..64, default 5)\n"
                "  limits: --maxclients N --timeout SECONDS --tcp-keepalive SECONDS\n"
                "  client cron: --hz N (0..2147483647, clamped to 1..500) --dynamic-hz yes|no\n"
                "          --tcp-backlog N --client-output-buffer-limit CLASS HARD SOFT SECONDS ...\n"
                "          --unixsocket PATH --unixsocketperm OCTAL\n"
                "  network engine: --net-io uring|epoll (boot-only; default uring)\n"
                "  TLS: --tls-port N --tls-cert-file PATH --tls-key-file PATH\n"
                "       --tls-ca-cert-file PATH --tls-ca-cert-dir PATH\n"
                "       --tls-auth-clients yes|no|optional --tls-protocols LIST\n"
                "       --tls-ciphers LIST --tls-ciphersuites LIST\n"
                "       --tls-prefer-server-ciphers yes|no\n"
                "  notifications: --notify-keyspace-events FLAGS (default empty/off)\n"
                "  client-side caching: --tracking-table-max-keys N "
                "(default 1000000, 0=unlimited)\n"
                "  persistence: --dir PATH --dbfilename NAME\n"
                "    --save SECONDS CHANGES (repeatable; --save \"\" disables)\n"
                "    --appendonly yes|no --appendfsync always|everysec|no\n"
                "    --appendfilename NAME --appenddirname NAME\n"
                "    --auto-aof-rewrite-percentage N --auto-aof-rewrite-min-size BYTES\n"
                "    --aof-use-rdb-preamble yes --aof-timestamp-enabled yes|no\n"
                "    --aof-load-truncated yes|no (boot-only recovery policy)\n"
                "  compatibility: --databases N --proto-max-bulk-len BYTES --client-query-buffer-limit BYTES\n"
                "  security: --requirepass PASSWORD --protected-mode 0|1|yes|no\n"
                "            --enable-debug-command no|yes|local --aclfile PATH\n"
                "            --user NAME RULE... --acl-pubsub-default allchannels|resetchannels\n"
                "            --acllog-max-len N\n"
                "  observability: --slowlog-log-slower-than US (default 10000; -1 off)\n"
                "            --slowlog-max-len N (default 128)\n"
                "            --latency-monitor-threshold MS (default 0 = off)\n"
                "            --latency-tracking yes|no (default no; Redis defaults yes)\n"
                "            --latency-tracking-info-percentiles P... (default 50 99 99.9)\n"
                "  atomics: --atomic 0|1 (default 0)\n"
                "  encodings: --hash-max-listpack-entries N --hash-max-listpack-value BYTES\n"
                "    --list-max-listpack-size N (-1..-5: 4..64 KiB; >=0: entry count; default -2)\n"
                "    --set-max-listpack-entries N --set-max-listpack-value N\n"
                "    --set-max-intset-entries N (default 512; 0 disables intsets)\n"
                "    --zset-max-listpack-entries N --zset-max-listpack-value BYTES\n"
                "    (ziplist and hash/zset compact aliases accepted)\n"
                "  HyperLogLog: --hll-sparse-max-bytes BYTES (boot-only; default 3000)\n"
                "  streams: --stream-node-max-bytes N --stream-node-max-entries N\n"
                "  misc: --hash mix64|siphash\n"
                "  (--mode/--wb/--nodes died with 3s, 2026-08)\n",
                prog);
            return kConfigHelp;
        } else {
            std::fprintf(diagnostics, "unknown argument '%s' (see --help)\n", a);
            return kConfigError;
        }
    }
    return kConfigParsed;
}

// Validate the combined boot configuration once after all sources, before starting workers.
// Borrows cfg read-only; checks cross-option constraints and temporarily creates/frees a
// locale object, without publishing state. Returns Parsed or the first Error with a
// stderr diagnostic; numeric field validation also relies on the individual parsers.
inline int /* TOMO_TOOL_BIND validate_config */ validate_config(const Config& cfg) {
    if (cfg.wb_small_pipe > kRobWindow || cfg.wb_complete_visits > UINT8_MAX) {
        std::fprintf(stderr, "--wb-small-pipe wants 0..64; --wb-complete-visits wants 0..255\n");
        return kConfigError;
    }
    if (cfg.wb_policy < 0 || cfg.wb_policy > 1) {
        std::fprintf(stderr, "--wb-policy wants 0 or 1\n");
        return kConfigError;
    }
    if (cfg.key_lb > 1 || cfg.client_lb > 1) {
        std::fprintf(stderr, "--key-lb and --client-lb want 0 or 1\n");
        return kConfigError;
    }
    if (cfg.shard_home && !*cfg.shard_home) {
        std::fprintf(stderr, "--shard-home must contain shard:thread pairs\n");
        return kConfigError;
    }
    if (cfg.reorder > 1) {
        std::fprintf(stderr, "--reorder wants 0 or 1\n");
        return kConfigError;
    }
    if (cfg.thread_mode == ThreadMode::Fused && (cfg.even_ifid || cfg.even_ex)) {
        std::fprintf(
            stderr,
            "--ratio is unavailable with --thread-mode 1s: every thread handles networking and execution\n");
        return kConfigError;
    }
    if (cfg.thread_mode == ThreadMode::Fused && cfg.flip_auto) {
        std::fprintf(stderr, "--flip-auto is unavailable with --thread-mode 1s\n");
        return kConfigError;
    }
    if (cfg.databases < 1 || cfg.databases > 256) {
        std::fprintf(stderr, "databases must be between 1 and 256\n");
        return kConfigError;
    }
    if (cfg.proto_max_bulk_len < kProtoMinBulkLen ||
        cfg.proto_max_bulk_len > kProtoMaxBulkLenSupported) {
        std::fprintf(stderr, "proto-max-bulk-len is outside the supported range\n");
        return kConfigError;
    }
    locale_t collate = newlocale(LC_COLLATE_MASK, cfg.locale_collate, nullptr);
    if (!collate) {
        std::fprintf(stderr, "Invalid locale name for locale-collate\n");
        return kConfigError;
    }
    freelocale(collate);
    if (cfg.port && cfg.tls_port && cfg.port == cfg.tls_port) {
        std::fprintf(stderr, "port and tls-port must be different listeners\n");
        return kConfigError;
    }
    if (cfg.tls_port) {
        if (!cfg.tls_cert_file || !*cfg.tls_cert_file) {
            std::fprintf(stderr, "tls-port requires tls-cert-file\n");
            return kConfigError;
        }
        if (!cfg.tls_key_file || !*cfg.tls_key_file) {
            std::fprintf(stderr, "tls-port requires tls-key-file\n");
            return kConfigError;
        }
        if (cfg.tls_auth_clients != TlsAuthClients::No &&
            (!cfg.tls_ca_cert_file || !*cfg.tls_ca_cert_file) &&
            (!cfg.tls_ca_cert_dir || !*cfg.tls_ca_cert_dir)) {
            std::fprintf(
                stderr,
                "tls-auth-clients yes or optional requires tls-ca-cert-file or tls-ca-cert-dir\n");
            return kConfigError;
        }
    }
    if (cfg.aclfile && *cfg.aclfile && !cfg.acl_users.empty()) {
        std::fprintf(
            stderr,
            "Configuring Redis with users defined in redis.conf and at the same setting an ACL file path is invalid. This setup is very likely to lead to configuration errors and security holes, please define either an ACL file or declare users directly in your redis.conf, but not both.\n");
        return kConfigError;
    }
    if (cfg.shards != Config::kShardsAuto && (cfg.shards == 0 || cfg.shards > 256)) {
        std::fprintf(stderr, "shards must be between 1 and 256\n");
        return kConfigError;
    }
    if (!cfg.dir || !*cfg.dir || !cfg.dbfilename || !*cfg.dbfilename ||
        std::strchr(cfg.dbfilename, '/')) {
        std::fprintf(stderr, "--dir must be non-empty and --dbfilename must be a plain filename\n");
        return kConfigError;
    }
    if (!cfg.appendfilename || !*cfg.appendfilename || std::strchr(cfg.appendfilename, '/') ||
        !cfg.appenddirname || !*cfg.appenddirname || std::strchr(cfg.appenddirname, '/')) {
        std::fprintf(stderr, "--appendfilename and --appenddirname must be plain names\n");
        return kConfigError;
    }
    return kConfigParsed;
}

inline bool cfg_is_hex_digit(char c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}

inline uint8_t cfg_hex_digit(char c) {
    if (c >= '0' && c <= '9') return static_cast<uint8_t>(c - '0');
    if (c >= 'a' && c <= 'f') return static_cast<uint8_t>(c - 'a' + 10);
    return static_cast<uint8_t>(c - 'A' + 10);
}

// Redis sdssplitargs grammar, used by config.c: double quotes recognize C-style escapes and
// \xHH, single quotes recognize only \', and a closing quote must end the token. Quotes may start
// after an unquoted prefix (`>"pass phrase"` is one ACL rule). A '#' has no special meaning here:
// config.c treats it as a comment only when it is the first character of the trimmed line.
// Append decoded tokens to caller-owned out; requires a NUL-terminated line and exclusive
// access to out (boot parsing or a serialized CONFIG caller). No borrowed token survives.
// False means malformed quoting and may leave preceding tokens appended; allocation
// exceptions propagate. No worker publication or back-pressure protocol is involved.
inline bool cfg_split_args(const char* line, std::vector<std::string>& out) {
    const char* p = line;
    while (true) {
        while (*p && std::isspace(static_cast<unsigned char>(*p))) p++;
        if (!*p) return true;

        std::string current;
        bool in_double = false;
        bool in_single = false;
        bool done = false;
        while (!done) {
            if (in_double) {
                if (*p == '\\' && p[1] == 'x' && cfg_is_hex_digit(p[2]) && cfg_is_hex_digit(p[3])) {
                    current.push_back(
                        static_cast<char>((cfg_hex_digit(p[2]) << 4) | cfg_hex_digit(p[3])));
                    p += 3;
                } else if (*p == '\\' && p[1]) {
                    p++;
                    char c = *p;
                    if (*p == 'n')
                        c = '\n';
                    else if (*p == 'r')
                        c = '\r';
                    else if (*p == 't')
                        c = '\t';
                    else if (*p == 'b')
                        c = '\b';
                    else if (*p == 'a')
                        c = '\a';
                    current.push_back(c);
                } else if (*p == '"') {
                    if (p[1] && !std::isspace(static_cast<unsigned char>(p[1]))) return false;
                    done = true;
                } else if (!*p) {
                    return false;
                } else {
                    current.push_back(*p);
                }
            } else if (in_single) {
                if (*p == '\\' && p[1] == '\'') {
                    p++;
                    current.push_back('\'');
                } else if (*p == '\'') {
                    if (p[1] && !std::isspace(static_cast<unsigned char>(p[1]))) return false;
                    done = true;
                } else if (!*p) {
                    return false;
                } else {
                    current.push_back(*p);
                }
            } else {
                switch (*p) {
                    case ' ':
                    case '\n':
                    case '\r':
                    case '\t':
                    case '\0':
                        done = true;
                        break;
                    case '"':
                        in_double = true;
                        break;
                    case '\'':
                        in_single = true;
                        break;
                    default:
                        current.push_back(*p);
                        break;
                }
            }
            if (*p) p++;
        }
        out.push_back(std::move(current));
    }
}

struct ConfigFileLine {
    int number;
    std::string text;
};

inline void config_file_error(int number, const char* line, const char* error) {
    std::fprintf(stderr,
                 "\n*** FATAL CONFIG FILE ERROR (Redis %s) ***\n"
                 "Reading the configuration file, at line %d\n>>> '%s'\n%s\n",
                 kRedisCompatVersion, number, line, error);
}

// Read boot directives into caller-owned store, optionally appending source lines and
// end offsets. Run before workers, with exclusive access to all outputs. A line
// argument beginning with -- remains a value; pin yes/no maps to --no-pin.
// Complete storage before parsing, then keep it stable for Config's borrowed pointers.
// Returns false with a diagnostic on open/read/grammar errors; earlier output remains.
// Allocation exceptions propagate; the file handle is not guarded against exceptions.
inline bool load_conf_file(const char* path, std::vector<std::string>& store,
                           std::vector<size_t>* line_ends = nullptr,
                           std::vector<ConfigFileLine>* lines = nullptr) {
    std::FILE* f = std::fopen(path, "r");
    if (!f) {
        std::fprintf(stderr, "cannot open conf file '%s'\n", path);
        return false;
    }
    // Redis concatenates 1024-byte fgets chunks as C strings before splitting
    // on LF. A chunk boundary is never a directive boundary. Preserve its raw
    // NUL behavior too: the rest of that chunk (possibly including LF) vanishes.
    std::string contents;
    char chunk[1025];
    while (std::fgets(chunk, sizeof(chunk), f)) contents += chunk;
    const bool read_error = std::ferror(f);
    std::fclose(f);
    if (read_error) {
        std::fprintf(stderr, "cannot read conf file '%s'\n", path);
        return false;
    }
    int lineno = 0;
    bool ok = true;
    size_t offset = 0;
    while (ok && offset < contents.size()) {
        const size_t end = contents.find('\n', offset);
        std::string physical =
            contents.substr(offset, end == std::string::npos ? end : end - offset);
        offset = end == std::string::npos ? contents.size() : end + 1;
        char* line = physical.data();
        lineno++;
        size_t length = std::strlen(line);
        while (length && std::strchr(" \t\r\n", line[length - 1])) line[--length] = 0;
        const char* first = line;
        while (*first && std::strchr(" \t\r\n", *first)) first++;
        if (*first == '#' || !*first) continue;
        std::vector<std::string> words;
        if (!cfg_split_args(first, words)) {
            config_file_error(lineno, first, "Unbalanced quotes in configuration line");
            ok = false;
            continue;
        }
        if (words.empty()) continue;
        for (char& c : words[0])
            if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
        // CLI-only: Redis has no such directive, and a file must never exit successfully.
        if (words[0] == "help") {
            config_file_error(lineno, first, "Bad directive or wrong number of arguments");
            ok = false;
            continue;
        }
        if (words[0] == "pin") {
            if (words.size() != 2 || (words[1] != "yes" && words[1] != "no")) {
                config_file_error(lineno, first, "pin wants yes|no");
                ok = false;
            } else if (words[1] == "no") {
                store.emplace_back("--no-pin");
                if (line_ends) line_ends->push_back(store.size());
                if (lines) lines->push_back({lineno, first});
            }
            continue;
        }
        // Preserve each directive's arity before flattening storage. An omitted value is
        // different from an explicit empty string, and cannot consume the next line.
        const bool valueless = words[0] == "no-pin" || words[0] == "help";
        const bool variadic =
            words[0] == "user" || words[0] == "save" || words[0] == "client-output-buffer-limit" ||
            words[0] == "shutdown-on-sigint" || words[0] == "shutdown-on-sigterm" ||
            words[0] == "latency-tracking-info-percentiles";
        if ((valueless && words.size() != 1) ||
            (!valueless && ((words.size() < 2 && words[0] != "latency-tracking-info-percentiles") ||
                            (!variadic && words.size() != 2)))) {
            config_file_error(lineno, first, "wrong number of arguments");
            ok = false;
            continue;
        }
        store.emplace_back("--" + words[0]);
        for (size_t w = 1; w < words.size(); w++) store.emplace_back(words[w]);
        if (line_ends) line_ends->push_back(store.size());
        if (lines) lines->push_back({lineno, first});
    }
    return ok;
}

// Parse physical directives individually while retaining decoded byte lengths.
// ConfigParseState spans lines for repeated save/user clauses and CLI precedence.
// The completed string store must remain stable throughout Config's borrowed-pointer use.
__attribute__((noipa)) inline int parse_config_file(
    const std::vector<std::string>& store, const std::vector<size_t>& line_ends, Config& cfg,
    ConfigParseState& st, const char* prog, const std::vector<ConfigFileLine>* lines = nullptr) {
    size_t begin = 0;
    size_t line_index = 0;
    for (size_t end : line_ends) {
        std::vector<const char*> args;
        std::vector<size_t> lengths;
        for (size_t i = begin; i < end; i++) {
            args.push_back(store[i].c_str());
            lengths.push_back(store[i].size());
        }
        // Retain the parser's specific reason behind Redis's file/line diagnostic.
        char* reason = nullptr;
        size_t size = 0;
        std::FILE* diagnostics = ::open_memstream(&reason, &size);
        if (!diagnostics) return kConfigError;
        const int rc = parse_config_args(args, cfg, st, 1, prog, &lengths, diagnostics);
        std::fclose(diagnostics);
        if (rc != kConfigParsed) {
            // Redis prints the setter's reason alone: drop the CLI-shaped "--name: " prefix.
            std::string text = reason && *reason ? reason : "Invalid configuration\n";
            const std::string prefix = std::string(args.empty() ? "" : args[0]) + ": ";
            if (text.compare(0, prefix.size(), prefix) == 0) text.erase(0, prefix.size());
            while (!text.empty() && text.back() == '\n') text.pop_back();
            if (lines)
                config_file_error((*lines)[line_index].number, (*lines)[line_index].text.c_str(),
                                  text.c_str());
            else if (reason)
                std::fputs(reason, stderr);
        }
        std::free(reason);
        if (rc != kConfigParsed) return rc;
        begin = end;
        ++line_index;
    }
    return kConfigParsed;
}

}  // namespace tomo
