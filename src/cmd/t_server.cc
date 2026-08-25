// t_server.cc — Redis client/tool compatibility, introspection, and cross-shard keyspace commands.
//
// Connection-local handlers use a thread-local context bound for the duration of the synchronous
// IO-thread call. Client metadata lives in a cold, locked catalog here rather than enlarging the
// 1984-byte Client. Store handlers still receive only (Shard&, Op&) and never touch a socket.
#include "command.h"
#include "../base/alloc.h"
#include "../core/server.h"
#include "../core/thread.h"
#include "../exec/op.h"
#include "../net/conn.h"
#include "../net/resp.h"
#include "../store/kvobj.h"
#include "../store/eviction.h"
#include "../snapshot/snapshot.h"

#include <algorithm>
#include <cctype>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <limits>
#include <mutex>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

namespace tomo {
namespace {

constexpr const char* kVersion = "0.1-cpp";
constexpr uint64_t kScanInnerMask = (uint64_t{1} << 56) - 1;
constexpr uint64_t kMaxInnerCursor = (uint64_t{1} << 33) - 1;

Server* g_server = nullptr;
thread_local Client* g_client = nullptr;
thread_local ThreadCtx* g_thread = nullptr;
uint64_t g_started_monotonic_ns = 0;

bool eq_icase(Slice s, const char* lit) {
    const size_t n = std::strlen(lit);
    if (s.n != n) return false;
    for (size_t i = 0; i < n; i++) {
        unsigned char a = static_cast<unsigned char>(s.p[i]);
        unsigned char b = static_cast<unsigned char>(lit[i]);
        if (a >= 'a' && a <= 'z') a -= 'a' - 'A';
        if (b >= 'a' && b <= 'z') b -= 'a' - 'A';
        if (a != b) return false;
    }
    return true;
}

bool parse_u64(Slice s, uint64_t& out) {
    if (!s.n) return false;
    uint64_t value = 0;
    for (uint32_t i = 0; i < s.n; i++) {
        const char ch = s.p[i];
        if (ch < '0' || ch > '9') return false;
        const uint32_t digit = static_cast<uint32_t>(ch - '0');
        if (value > (std::numeric_limits<uint64_t>::max() - digit) / 10) return false;
        value = value * 10 + digit;
    }
    out = value;
    return true;
}

std::string lower_name(const char* name) {
    std::string out(name);
    for (char& ch : out)
        if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch + ('a' - 'A'));
    return out;
}

// Redis-style glob subset including '*', '?', escapes, and byte ranges/classes. Work is bounded by
// the pattern and candidate lengths for each key examined by SCAN.
bool glob_match(const char* pat, size_t pn, const char* text, size_t tn, bool nocase = false) {
    while (pn) {
        switch (*pat) {
            case '*': {
                while (pn && *pat == '*') { pat++; pn--; }
                if (!pn) return true;
                for (size_t i = 0; i <= tn; i++)
                    if (glob_match(pat, pn, text + i, tn - i, nocase)) return true;
                return false;
            }
            case '?':
                if (!tn) return false;
                pat++; pn--; text++; tn--;
                break;
            case '[': {
                if (!tn) return false;
                pat++; pn--;
                bool negate = false, matched = false;
                if (pn && (*pat == '^' || *pat == '!')) { negate = true; pat++; pn--; }
                unsigned char want = static_cast<unsigned char>(*text);
                if (nocase) want = static_cast<unsigned char>(std::tolower(want));
                while (pn && *pat != ']') {
                    unsigned char lo = static_cast<unsigned char>(*pat++); pn--;
                    if (lo == '\\' && pn) { lo = static_cast<unsigned char>(*pat++); pn--; }
                    unsigned char hi = lo;
                    if (pn >= 2 && *pat == '-' && pat[1] != ']') {
                        pat++; pn--;
                        hi = static_cast<unsigned char>(*pat++); pn--;
                        if (hi == '\\' && pn) { hi = static_cast<unsigned char>(*pat++); pn--; }
                    }
                    if (nocase) {
                        lo = static_cast<unsigned char>(std::tolower(lo));
                        hi = static_cast<unsigned char>(std::tolower(hi));
                    }
                    if (lo > hi) std::swap(lo, hi);
                    if (want >= lo && want <= hi) matched = true;
                }
                if (!pn || *pat != ']') return false;
                pat++; pn--;
                if (matched == negate) return false;
                text++; tn--;
                break;
            }
            case '\\':
                if (pn > 1) { pat++; pn--; }
                [[fallthrough]];
            default: {
                if (!tn) return false;
                unsigned char a = static_cast<unsigned char>(*pat);
                unsigned char b = static_cast<unsigned char>(*text);
                if (nocase) { a = static_cast<unsigned char>(std::tolower(a));
                              b = static_cast<unsigned char>(std::tolower(b)); }
                if (a != b) return false;
                pat++; pn--; text++; tn--;
                break;
            }
        }
    }
    return tn == 0;
}

bool glob_match(Slice pat, Slice text, bool nocase = false) {
    return glob_match(pat.p, pat.n, text.p, text.n, nocase);
}

void appendf(std::string& out, const char* fmt, ...) {
    char stack[512];
    va_list ap;
    va_start(ap, fmt);
    va_list copy;
    va_copy(copy, ap);
    int n = std::vsnprintf(stack, sizeof(stack), fmt, ap);
    va_end(ap);
    if (n < 0) { va_end(copy); return; }
    if (static_cast<size_t>(n) < sizeof(stack)) out.append(stack, static_cast<size_t>(n));
    else {
        std::vector<char> buf(static_cast<size_t>(n) + 1);
        std::vsnprintf(buf.data(), buf.size(), fmt, copy);
        out.append(buf.data(), static_cast<size_t>(n));
    }
    va_end(copy);
}

struct ClientMeta {
    uint64_t id = 0;
    std::string addr;
    std::string name;
    std::string lib_name;
    std::string lib_ver;
    uint32_t db = 0;
};

std::mutex g_clients_mu;
std::unordered_map<Client*, ClientMeta> g_clients;

bool valid_client_text(Slice value) {
    for (uint32_t i = 0; i < value.n; i++) {
        const unsigned char ch = static_cast<unsigned char>(value.p[i]);
        if (ch <= ' ' || ch == 127) return false;
    }
    return true;
}

ClientMeta current_meta() {
    std::lock_guard<std::mutex> lock(g_clients_mu);
    auto it = g_clients.find(g_client);
    if (it != g_clients.end()) return it->second;
    ClientMeta fallback;
    if (g_client) fallback.id = g_client->id();
    fallback.addr = "unknown:0";
    return fallback;
}

void append_client_line(std::string& out, const ClientMeta& meta) {
    appendf(out, "id=%llu addr=%s name=%s db=%u lib-name=%s lib-ver=%s\n",
            static_cast<unsigned long long>(meta.id), meta.addr.c_str(), meta.name.c_str(), meta.db,
            meta.lib_name.c_str(), meta.lib_ver.c_str());
}

enum class ConfigKind : uint8_t { String, Bool, Unsigned, Bytes, Policy };
struct ConfigValue {
    const char* name;
    ConfigKind kind;
    std::string value;
};

std::mutex g_config_mu;
std::vector<ConfigValue> g_config;

void add_config(const char* name, ConfigKind kind, uint64_t value) {
    g_config.push_back(ConfigValue{name, kind, std::to_string(value)});
}

void init_config(const Config& cfg) {
    std::lock_guard<std::mutex> lock(g_config_mu);
    g_config.clear();
    g_config.push_back({"save", ConfigKind::String, ""});
    g_config.push_back({"dir", ConfigKind::String, (cfg.dir && *cfg.dir) ? cfg.dir : "."});
    g_config.push_back({"dbfilename", ConfigKind::String,
                        (cfg.dbfilename && *cfg.dbfilename) ? cfg.dbfilename : "dump.tomo"});
    g_config.push_back({"appendonly", ConfigKind::Bool, "no"});
    add_config("maxmemory", ConfigKind::Bytes, cfg.maxmemory);
    g_config.push_back({"maxmemory-policy", ConfigKind::Policy,
                        maxmemory_policy_name(cfg.maxmemory_policy)});
    add_config("maxmemory-samples", ConfigKind::Unsigned, cfg.maxmemory_samples);
    add_config("timeout", ConfigKind::Unsigned, 0);
    add_config("databases", ConfigKind::Unsigned, 1);
    add_config("proto-max-bulk-len", ConfigKind::Bytes, 512ull * 1024 * 1024);
    add_config("zc-min", ConfigKind::Unsigned, cfg.zc_min);
    add_config("atomic", ConfigKind::Unsigned, cfg.atomic);
    add_config("atomic-window", ConfigKind::Unsigned, cfg.atomic_window);
    add_config("hash-max-compact-entries", ConfigKind::Unsigned, cfg.type_limits.hash.max_entries);
    add_config("hash-max-compact-value", ConfigKind::Unsigned, cfg.type_limits.hash.max_value);
    add_config("list-max-compact-entries", ConfigKind::Unsigned, cfg.type_limits.list.max_entries);
    add_config("list-max-compact-value", ConfigKind::Unsigned, cfg.type_limits.list.max_value);
    add_config("set-max-compact-entries", ConfigKind::Unsigned, cfg.type_limits.set.max_entries);
    add_config("set-max-compact-value", ConfigKind::Unsigned, cfg.type_limits.set.max_value);
    add_config("zset-max-compact-entries", ConfigKind::Unsigned, cfg.type_limits.zset.max_entries);
    add_config("zset-max-compact-value", ConfigKind::Unsigned, cfg.type_limits.zset.max_value);
}

ConfigValue* find_config(Slice name) {
    for (ConfigValue& item : g_config)
        if (eq_icase(name, item.name)) return &item;
    return nullptr;
}

bool parse_bytes(Slice input, uint64_t& value) {
    uint32_t digits = 0;
    while (digits < input.n && input.p[digits] >= '0' && input.p[digits] <= '9') digits++;
    if (!digits) return false;
    if (!parse_u64(Slice(input.p, digits), value)) return false;
    uint64_t factor = 1;
    Slice suffix(input.p + digits, input.n - digits);
    if (suffix.n) {
        if (eq_icase(suffix, "K") || eq_icase(suffix, "KB")) factor = 1024;
        else if (eq_icase(suffix, "M") || eq_icase(suffix, "MB")) factor = 1024ull * 1024;
        else if (eq_icase(suffix, "G") || eq_icase(suffix, "GB")) factor = 1024ull * 1024 * 1024;
        else return false;
    }
    if (value > std::numeric_limits<uint64_t>::max() / factor) return false;
    value *= factor;
    return true;
}

bool normalize_config(const ConfigValue& entry, Slice input, std::string& out) {
    switch (entry.kind) {
        case ConfigKind::String:
            out.assign(input.p, input.n);
            return true;
        case ConfigKind::Bool:
            if (eq_icase(input, "yes")) { out = "yes"; return true; }
            if (eq_icase(input, "no")) { out = "no"; return true; }
            return false;
        case ConfigKind::Unsigned: {
            uint64_t value = 0;
            if (!parse_u64(input, value)) return false;
            if ((std::strstr(entry.name, "compact") || !std::strcmp(entry.name, "zc-min")) &&
                value > UINT32_MAX) return false;
            if (!std::strcmp(entry.name, "maxmemory-samples") && (value == 0 || value > 64))
                return false;
            if (!std::strcmp(entry.name, "atomic") && value > 1) return false;
            if (!std::strcmp(entry.name, "atomic-window") && value > UINT32_MAX) return false;
            out = std::to_string(value);
            return true;
        }
        case ConfigKind::Bytes: {
            uint64_t value = 0;
            if (!parse_bytes(input, value)) return false;
            out = std::to_string(value);
            return true;
        }
        case ConfigKind::Policy: {
            static const char* policies[] = {"noeviction", "allkeys-lru", "allkeys-lfu",
                "allkeys-random", "volatile-lru", "volatile-lfu", "volatile-random", "volatile-ttl"};
            for (const char* policy : policies)
                if (eq_icase(input, policy)) { out = policy; return true; }
            return false;
        }
    }
    return false;
}

bool collect_config_updates(Op& op,
                            std::vector<std::pair<ConfigValue*, std::string>>& updates) {
    if (op.argc() < 4 || (op.argc() & 1u) != 0) { reply_syntax(op.sink()); return false; }
    for (uint32_t i = 2; i < op.argc(); i += 2) {
        ConfigValue* item = find_config(op.arg(i));
        if (!item) {
            std::string msg = "ERR Unknown option or number of arguments for CONFIG SET - '";
            msg.append(op.arg(i).p, op.arg(i).n); msg.push_back('\'');
            reply_err(op.sink(), msg.c_str()); return false;
        }
        if (!std::strcmp(item->name, "dir") || !std::strcmp(item->name, "dbfilename")) {
            reply_err(op.sink(), "ERR parameter is immutable at runtime"); return false;
        }
        std::string value;
        if (!normalize_config(*item, op.arg(i + 1), value)) {
            std::string msg = "ERR Invalid argument '";
            msg.append(op.arg(i + 1).p, op.arg(i + 1).n);
            msg += "' for CONFIG SET '"; msg += item->name; msg.push_back('\'');
            reply_err(op.sink(), msg.c_str()); return false;
        }
        updates.emplace_back(item, std::move(value));
    }
    return true;
}

void snapshot_command(Op& op, bool blocking) {
    if (!g_server) { reply_err(op.sink(), "ERR snapshot subsystem is unavailable"); return; }
    const SnapshotIoContext context = snapshot_io_context();
    if (!context.thread || !context.ring) {
        reply_err(op.sink(), "ERR snapshot command has no IO owner");
        return;
    }
    std::string error;
    const SnapshotManager::StartResult result = g_server->snapshot().start(
        *g_server, *context.thread, *context.ring, blocking, error);
    if (result == SnapshotManager::StartResult::Busy) {
        reply_err(op.sink(), "ERR Background save already in progress");
    } else if (result == SnapshotManager::StartResult::Failed) {
        std::string message = "ERR ";
        message += error.empty() ? "snapshot failed" : error;
        reply_err(op.sink(), message.c_str());
    } else if (blocking) {
        reply_ok(op.sink());
    } else {
        reply_simple(op.sink(), "Background saving started");
    }
}

void cmd_save(Shard&, Op& op) { snapshot_command(op, true); }
void cmd_bgsave(Shard&, Op& op) { snapshot_command(op, false); }
void cmd_lastsave(Shard&, Op& op) {
    reply_int(op.sink(), g_server ? static_cast<long long>(g_server->snapshot().last_save_time()) : 0);
}

void cmd_ping(Shard&, Op& op) {
    if (op.argc() == 2) reply_bulk(op.sink(), op.arg(1));
    else reply_pong(op.sink());
}

void cmd_echo(Shard&, Op& op) { reply_bulk(op.sink(), op.arg(1)); }

void cmd_auth(Shard&, Op& op) {
    (void)op;
    reply_err(op.sink(), "ERR AUTH <password> called without any password configured for the default user. Are you sure your configuration is correct?");
}

void cmd_hello(Shard&, Op& op) {
    if (op.argc() == 2) {
        uint64_t version = 0;
        if (!parse_u64(op.arg(1), version)) {
            reply_err(op.sink(), "ERR Protocol version is not an integer or out of range");
            return;
        }
        if (version != 2) {
            reply_err(op.sink(), "NOPROTO unsupported protocol version");
            return;
        }
    }
    auto sink = op.sink();
    reply_array_header(sink, 14);
    reply_bulk(sink, Slice("server", 6)); reply_bulk(sink, Slice("redis", 5));
    reply_bulk(sink, Slice("version", 7)); reply_bulk(sink, Slice(kVersion, std::strlen(kVersion)));
    reply_bulk(sink, Slice("proto", 5)); reply_int(sink, 2);
    reply_bulk(sink, Slice("id", 2)); reply_int(sink, g_client ? static_cast<long long>(g_client->id()) : 0);
    reply_bulk(sink, Slice("mode", 4)); reply_bulk(sink, Slice("standalone", 10));
    reply_bulk(sink, Slice("role", 4)); reply_bulk(sink, Slice("master", 6));
    reply_bulk(sink, Slice("modules", 7)); reply_array_header(sink, 0);
}

void cmd_select(Shard&, Op& op) {
    uint64_t db = 0;
    if (!parse_u64(op.arg(1), db) || db != 0) {
        reply_err(op.sink(), "ERR this server supports a single keyspace; only SELECT 0 is valid");
        return;
    }
    if (g_client) g_client->session().db_index = 0;
    {
        std::lock_guard<std::mutex> lock(g_clients_mu);
        auto it = g_clients.find(g_client);
        if (it != g_clients.end()) it->second.db = 0;
    }
    reply_ok(op.sink());
}

void cmd_reset(Shard&, Op& op) {
    if (g_client) g_client->session().db_index = 0;
    {
        std::lock_guard<std::mutex> lock(g_clients_mu);
        auto it = g_clients.find(g_client);
        if (it != g_clients.end()) {
            it->second.name.clear(); it->second.lib_name.clear(); it->second.lib_ver.clear();
            it->second.db = 0;
        }
    }
    reply_simple(op.sink(), "RESET");
}

void cmd_client(Shard&, Op& op) {
    const Slice sub = op.arg(1);
    if (eq_icase(sub, "ID") && op.argc() == 2) {
        reply_int(op.sink(), g_client ? static_cast<long long>(g_client->id()) : 0);
    } else if (eq_icase(sub, "SETNAME") && op.argc() == 3) {
        if (!valid_client_text(op.arg(2))) {
            reply_err(op.sink(), "ERR Client names cannot contain spaces, newlines or special characters.");
            return;
        }
        std::lock_guard<std::mutex> lock(g_clients_mu);
        auto it = g_clients.find(g_client);
        if (it != g_clients.end()) it->second.name.assign(op.arg(2).p, op.arg(2).n);
        reply_ok(op.sink());
    } else if (eq_icase(sub, "GETNAME") && op.argc() == 2) {
        ClientMeta meta = current_meta();
        if (meta.name.empty()) reply_nil(op.sink());
        else reply_bulk(op.sink(), Slice(meta.name.data(), meta.name.size()));
    } else if (eq_icase(sub, "SETINFO") && op.argc() == 4) {
        if (!valid_client_text(op.arg(3)) && op.arg(3).n != 0) {
            reply_err(op.sink(), "ERR lib-name/lib-ver cannot contain spaces, newlines or special characters.");
            return;
        }
        std::lock_guard<std::mutex> lock(g_clients_mu);
        auto it = g_clients.find(g_client);
        if (it == g_clients.end()) { reply_err(op.sink(), "ERR client metadata unavailable"); return; }
        if (eq_icase(op.arg(2), "LIB-NAME")) it->second.lib_name.assign(op.arg(3).p, op.arg(3).n);
        else if (eq_icase(op.arg(2), "LIB-VER")) it->second.lib_ver.assign(op.arg(3).p, op.arg(3).n);
        else { reply_err(op.sink(), "ERR Unrecognized option or bad number of arguments for CLIENT SETINFO"); return; }
        reply_ok(op.sink());
    } else if (eq_icase(sub, "INFO") && op.argc() == 2) {
        ClientMeta meta = current_meta();
        std::string body;
        append_client_line(body, meta);
        reply_bulk(op.sink(), Slice(body.data(), body.size()));
    } else if (eq_icase(sub, "LIST") && op.argc() == 2) {
        std::string body;
        {
            std::lock_guard<std::mutex> lock(g_clients_mu);
            for (const auto& item : g_clients) append_client_line(body, item.second);
        }
        reply_bulk(op.sink(), Slice(body.data(), body.size()));
    } else if (eq_icase(sub, "NO-EVICT") && op.argc() == 3 &&
               (eq_icase(op.arg(2), "ON") || eq_icase(op.arg(2), "OFF"))) {
        reply_ok(op.sink());
    } else {
        reply_syntax(op.sink());
    }
}

void reply_command_flags(Op::Sink& sink, const CommandSpec& spec) {
    uint32_t count = 0;
    if (spec.flags & CmdFlags::Write) count++;
    if (spec.flags & CmdFlags::Readonly) count++;
    if (spec.flags & CmdFlags::Admin) count++;
    if (spec.flags & CmdFlags::ConnLocal) count++;
    reply_array_header(sink, count);
    if (spec.flags & CmdFlags::Write) reply_bulk(sink, Slice("write", 5));
    if (spec.flags & CmdFlags::Readonly) reply_bulk(sink, Slice("readonly", 8));
    if (spec.flags & CmdFlags::Admin) reply_bulk(sink, Slice("admin", 5));
    if (spec.flags & CmdFlags::ConnLocal) reply_bulk(sink, Slice("fast", 4));
}

void reply_command_info(Op::Sink& sink, const CommandSpec* spec) {
    if (!spec) { reply_nil(sink); return; }
    reply_array_header(sink, 10);
    const std::string name = lower_name(spec->name);
    reply_bulk(sink, Slice(name.data(), name.size()));
    const int64_t arity = spec->max_arity == spec->min_arity ? spec->min_arity : -spec->min_arity;
    reply_int(sink, arity);
    reply_command_flags(sink, *spec);
    reply_int(sink, spec->first_key);
    reply_int(sink, spec->last_key);
    reply_int(sink, spec->key_step);
    reply_array_header(sink, 0); // ACL categories
    reply_array_header(sink, 0); // tips
    reply_array_header(sink, 0); // key specs (legacy key positions above are authoritative here)
    reply_array_header(sink, 0); // subcommands
}

const char* command_group(const CommandSpec& spec) {
    if (spec.flags & CmdFlags::Admin) return "server";
    if (spec.flags & CmdFlags::ConnLocal) return "connection";
    return "generic";
}

void reply_command_docs(Op::Sink& sink, const CommandSpec& spec) {
    // A RESP2 map is a flat array. These four fields are enough for redis-cli's live help parser.
    reply_array_header(sink, 8);
    reply_bulk(sink, Slice("summary", 7));
    std::string summary = std::string("tomokv compatible ") + lower_name(spec.name) + " command";
    reply_bulk(sink, Slice(summary.data(), summary.size()));
    reply_bulk(sink, Slice("since", 5)); reply_bulk(sink, Slice("0.1.0", 5));
    reply_bulk(sink, Slice("group", 5));
    const char* group = command_group(spec); reply_bulk(sink, Slice(group, std::strlen(group)));
    reply_bulk(sink, Slice("complexity", 10));
    const char* complexity = "O(1) or proportional to returned work";
    reply_bulk(sink, Slice(complexity, std::strlen(complexity)));
}

void cmd_command(Shard&, Op& op) {
    auto sink = op.sink();
    if (op.argc() == 1) {
        const uint32_t count = command_registry_size();
        reply_array_header(sink, count);
        for (uint32_t i = 0; i < count; i++) reply_command_info(sink, command_registry_at(i));
        return;
    }
    if (eq_icase(op.arg(1), "COUNT") && op.argc() == 2) {
        reply_int(sink, command_registry_size());
        return;
    }
    if (eq_icase(op.arg(1), "INFO")) {
        if (op.argc() == 2) {
            const uint32_t count = command_registry_size();
            reply_array_header(sink, count);
            for (uint32_t i = 0; i < count; i++) reply_command_info(sink, command_registry_at(i));
            return;
        }
        reply_array_header(sink, op.argc() - 2);
        for (uint32_t i = 2; i < op.argc(); i++)
            reply_command_info(sink, command_lookup(op.arg(i)));
        return;
    }
    if (eq_icase(op.arg(1), "DOCS")) {
        std::vector<const CommandSpec*> specs;
        if (op.argc() == 2) {
            for (uint32_t i = 0; i < command_registry_size(); i++) specs.push_back(command_registry_at(i));
        } else {
            for (uint32_t i = 2; i < op.argc(); i++)
                if (const CommandSpec* spec = command_lookup(op.arg(i))) specs.push_back(spec);
        }
        reply_array_header(sink, specs.size() * 2);
        for (const CommandSpec* spec : specs) {
            const std::string name = lower_name(spec->name);
            reply_bulk(sink, Slice(name.data(), name.size()));
            reply_command_docs(sink, *spec);
        }
        return;
    }
    reply_err(sink, "ERR unknown subcommand or wrong number of arguments for 'command'. Try COMMAND HELP.");
}

void cmd_config(Shard& sh, Op& op) {
    if (eq_icase(op.arg(1), "GET") && op.argc() == 3) {
        std::vector<std::pair<std::string, std::string>> matches;
        {
            std::lock_guard<std::mutex> lock(g_config_mu);
            for (const ConfigValue& item : g_config) {
                Slice name(item.name, std::strlen(item.name));
                if (glob_match(op.arg(2), name, true)) matches.emplace_back(item.name, item.value);
            }
        }
        auto sink = op.sink();
        reply_array_header(sink, matches.size() * 2);
        for (const auto& item : matches) {
            reply_bulk(sink, Slice(item.first.data(), item.first.size()));
            reply_bulk(sink, Slice(item.second.data(), item.second.size()));
        }
        return;
    }
    if (eq_icase(op.arg(1), "SET")) {
        std::vector<std::pair<ConfigValue*, std::string>> updates;
        {
            std::lock_guard<std::mutex> lock(g_config_mu);
            // IO validated before fan-out, so failure here can only mean internal table corruption.
            if (!collect_config_updates(op, updates)) return;
            if (sh.id() == 0)
                for (auto& update : updates) update.first->value = update.second;
        }

        // Eviction config is process-global (odd/even snapshot read by owners each pass); publish
        // it once from shard 0's task rather than per shard.
        if (sh.id() == 0 && g_server) {
            MaxmemoryConfigSnapshot desired = g_server->maxmemory_config_snapshot();
            bool set_memory = false, set_policy = false, set_samples = false;
            for (const auto& update : updates) {
                const Slice text(update.second.data(),
                                 static_cast<uint32_t>(update.second.size()));
                if (!std::strcmp(update.first->name, "maxmemory")) {
                    parse_u64(text, desired.maxmemory); set_memory = true;
                } else if (!std::strcmp(update.first->name, "maxmemory-policy")) {
                    parse_maxmemory_policy(text.sv(), desired.policy); set_policy = true;
                } else if (!std::strcmp(update.first->name, "maxmemory-samples")) {
                    uint64_t samples = 0;
                    parse_u64(text, samples);
                    desired.samples = static_cast<uint32_t>(samples); set_samples = true;
                }
            }
            if (set_memory || set_policy || set_samples)
                g_server->set_maxmemory_config(desired.maxmemory, desired.policy, desired.samples,
                                               set_memory, set_policy, set_samples);
            for (const auto& update : updates) {
                uint64_t value = 0;
                if (!parse_u64(Slice(update.second.data(), update.second.size()), value)) continue;
                if (!std::strcmp(update.first->name, "atomic"))
                    g_server->set_atomic_enabled(value != 0);
                else if (!std::strcmp(update.first->name, "atomic-window"))
                    g_server->set_atomic_window(static_cast<uint32_t>(value));
            }
        }

        TypeLimits limits = sh.type_limits();
        for (const auto& update : updates) {
            uint64_t value = 0;
            if (!parse_u64(Slice(update.second.data(), update.second.size()), value)) continue;
            const uint32_t v = static_cast<uint32_t>(value);
            if (!std::strcmp(update.first->name, "zc-min")) sh.set_zc_min(v);
            else if (!std::strcmp(update.first->name, "hash-max-compact-entries")) limits.hash.max_entries = v;
            else if (!std::strcmp(update.first->name, "hash-max-compact-value")) limits.hash.max_value = v;
            else if (!std::strcmp(update.first->name, "list-max-compact-entries")) limits.list.max_entries = v;
            else if (!std::strcmp(update.first->name, "list-max-compact-value")) limits.list.max_value = v;
            else if (!std::strcmp(update.first->name, "set-max-compact-entries")) limits.set.max_entries = v;
            else if (!std::strcmp(update.first->name, "set-max-compact-value")) limits.set.max_value = v;
            else if (!std::strcmp(update.first->name, "zset-max-compact-entries")) limits.zset.max_entries = v;
            else if (!std::strcmp(update.first->name, "zset-max-compact-value")) limits.zset.max_value = v;
        }
        sh.set_type_limits(limits);
        return;
    }
    reply_syntax(op.sink());
}

bool info_section(Op& op, const char* wanted) {
    return op.argc() == 1 || eq_icase(op.arg(1), "ALL") || eq_icase(op.arg(1), "DEFAULT") ||
           eq_icase(op.arg(1), wanted);
}

void cmd_info(Shard&, Op& op) {
    std::string body;
    uint64_t keys = 0, expires = 0, obj_bytes = 0, hits = 0, misses = 0, expired = 0,
             evicted = 0;
    uint64_t total_ops = 0, connections = 0, rejected = 0;
    uint64_t atomic_predecessor_reads = 0, atomic_chain_max = 0,
             atomic_promotions = 0, atomic_records_freed = 0,
             atomic_entries = 0, atomic_pending_entries = 0,
             atomic_cleanup_fast = 0, atomic_cleanup_slow = 0,
             atomic_localfast = 0;
    if (g_server) {
        for (uint32_t i = 0; i < g_server->nshards(); i++) {
            const Shard& sh = g_server->shard(static_cast<int32_t>(i));
            keys += sh.published_size(); expires += sh.published_expires();
            obj_bytes += sh.published_obj_bytes();
            hits += sh.stats().hits; misses += sh.stats().misses; expired += sh.stats().expired;
            evicted += sh.published_evicted();
            atomic_predecessor_reads += sh.stats().atomic_predecessor_reads;
            atomic_chain_max = std::max(atomic_chain_max, sh.stats().atomic_chain_max);
            atomic_promotions += sh.stats().atomic_promotions;
            atomic_records_freed += sh.stats().atomic_records_freed;
            atomic_entries += sh.stats().atomic_entries;
            atomic_pending_entries += sh.store().atomic_pending_entries();
            atomic_cleanup_fast += sh.store().atomic_cleanup_fast();
            atomic_cleanup_slow += sh.store().atomic_cleanup_slow();
        }
        for (uint32_t t = 0; t < g_server->nthreads(); t++) {
            for (uint32_t id = 0; id < command_registry_size(); id++)
                total_ops += g_server->thread(t).command_calls(id);
            connections += g_server->thread(t).sig().accepts;
            rejected += g_server->thread(t).sig().accept_err;
            atomic_localfast += g_server->thread(t).atomic_localfast();
        }
    }
    uint64_t connected = 0;
    { std::lock_guard<std::mutex> lock(g_clients_mu); connected = g_clients.size(); }

    if (info_section(op, "SERVER")) {
        const uint64_t uptime = g_started_monotonic_ns ? (now_ns() - g_started_monotonic_ns) / 1000000000ull : 0;
        appendf(body, "# Server\r\nredis_version:%s\r\ntomokv_version:%s\r\nredis_mode:standalone\r\n"
                      "arch_bits:%zu\r\nmultiplexing_api:io_uring\r\nuptime_in_seconds:%llu\r\n",
                kVersion, kVersion, sizeof(void*) * 8,
                static_cast<unsigned long long>(uptime));
    }
    if (info_section(op, "CLIENTS")) {
        appendf(body, "# Clients\r\nconnected_clients:%llu\r\nblocked_clients:0\r\ntracking_clients:0\r\n",
                static_cast<unsigned long long>(connected));
    }
    if (info_section(op, "MEMORY")) {
        size_t allocated = 0, resident = 0;
#if defined(TOMO_JEMALLOC)
        uint64_t epoch = 1; size_t epoch_size = sizeof(epoch);
        mallctl("epoch", &epoch, &epoch_size, &epoch, sizeof(epoch));
        size_t sz = sizeof(allocated); mallctl("stats.allocated", &allocated, &sz, nullptr, 0);
        sz = sizeof(resident); mallctl("stats.resident", &resident, &sz, nullptr, 0);
#endif
        appendf(body, "# Memory\r\nused_memory:%llu\r\nused_memory_dataset:%llu\r\n"
                      "used_memory_rss:%llu\r\nused_memory_peak:%llu\r\n"
                      "mem_allocator:%s\r\nallocator_allocated:%llu\r\nallocator_resident:%llu\r\n",
                static_cast<unsigned long long>(obj_bytes), static_cast<unsigned long long>(obj_bytes),
                static_cast<unsigned long long>(resident), static_cast<unsigned long long>(obj_bytes),
                alloc_backend(), static_cast<unsigned long long>(allocated),
                static_cast<unsigned long long>(resident));
    }
    if (info_section(op, "PERSISTENCE")) {
        uint64_t preimages = 0;
        if (g_server)
            for (uint32_t i = 0; i < g_server->nshards(); i++)
                preimages += g_server->shard(static_cast<int32_t>(i)).store().snapshot_preimages();
        appendf(body,
                "# Persistence\r\nrdb_bgsave_in_progress:%u\r\nrdb_last_save_time:%lld\r\n"
                "snapshot_preimages:%llu\r\n",
                g_server && g_server->snapshot().in_progress() ? 1u : 0u,
                static_cast<long long>(g_server ? g_server->snapshot().last_save_time() : 0),
                static_cast<unsigned long long>(preimages));
    }
    if (info_section(op, "STATS")) {
        appendf(body, "# Stats\r\ntotal_connections_received:%llu\r\nrejected_connections:%llu\r\n"
                      "total_commands_processed:%llu\r\nkeyspace_hits:%llu\r\nkeyspace_misses:%llu\r\n"
                      "expired_keys:%llu\r\nevicted_keys:%llu\r\ninstantaneous_ops_per_sec:0\r\n"
                      "total_net_input_bytes:0\r\ntotal_net_output_bytes:0\r\n"
                      "atomic_groups:%llu\r\natomic_inflight:%llu\r\n"
                      "atomic_predecessor_reads:%llu\r\natomic_chain_max:%llu\r\n"
                      "atomic_cleanup_fast:%llu\r\natomic_cleanup_slow:%llu\r\n"
                      "atomic_promotions:%llu\r\natomic_window_stalls:%llu\r\n"
                      "atomic_records_freed:%llu\r\natomic_entries:%llu\r\n"
                      "atomic_pending_entries:%llu\r\natomic_localfast:%llu\r\n"
                      "atomic_credit_pool:%u\r\natomic_credit_debt:%u\r\n",
                static_cast<unsigned long long>(connections), static_cast<unsigned long long>(rejected),
                static_cast<unsigned long long>(total_ops), static_cast<unsigned long long>(hits),
                static_cast<unsigned long long>(misses), static_cast<unsigned long long>(expired),
                static_cast<unsigned long long>(evicted),
                static_cast<unsigned long long>(g_server ? g_server->atomic_groups() : 0),
                static_cast<unsigned long long>(g_server ? g_server->atomic_inflight() : 0),
                static_cast<unsigned long long>(atomic_predecessor_reads),
                static_cast<unsigned long long>(atomic_chain_max),
                static_cast<unsigned long long>(atomic_cleanup_fast),
                static_cast<unsigned long long>(atomic_cleanup_slow),
                static_cast<unsigned long long>(atomic_promotions),
                static_cast<unsigned long long>(g_server ? g_server->atomic_window_stalls() : 0),
                static_cast<unsigned long long>(atomic_records_freed),
                static_cast<unsigned long long>(atomic_entries),
                static_cast<unsigned long long>(atomic_pending_entries),
                static_cast<unsigned long long>(atomic_localfast),
                g_server ? g_server->atomic_credit_pool() : 0,
                g_server ? g_server->atomic_credit_debt() : 0);
    }
    if (info_section(op, "COMMANDSTATS")) {
        body += "# Commandstats\r\n";
        for (uint32_t id = 0; id < command_registry_size(); id++) {
            uint64_t calls = 0;
            for (uint32_t t = 0; g_server && t < g_server->nthreads(); t++)
                calls += g_server->thread(t).command_calls(id);
            if (!calls) continue;
            const std::string name = lower_name(command_registry_at(id)->name);
            appendf(body, "cmdstat_%s:calls=%llu,usec=0,usec_per_call=0.00,rejected_calls=0,failed_calls=0\r\n",
                    name.c_str(), static_cast<unsigned long long>(calls));
        }
    }
    if (info_section(op, "KEYSPACE")) {
        body += "# Keyspace\r\n";
        appendf(body, "db0:keys=%llu,expires=%llu,avg_ttl=0\r\n",
                static_cast<unsigned long long>(keys), static_cast<unsigned long long>(expires));
    }
    reply_bulk(op.sink(), Slice(body.data(), body.size()));
}

void cmd_dbsize(Shard&, Op& op) {
    if (op.argc() == 2 && !eq_icase(op.arg(1), "NOW")) {
        reply_err(op.sink(), "ERR unknown DBSIZE option");
        return;
    }
    uint64_t keys = 0;
    if (g_server) for (uint32_t i = 0; i < g_server->nshards(); i++)
        keys += g_server->shard(static_cast<int32_t>(i)).published_size();
    reply_int(op.sink(), static_cast<long long>(keys));
}

// publish_size after clear: publications otherwise happen only at executor batch boundaries, so an
// idle shard would advertise its pre-flush count forever (DBSIZE stuck at stale totals).
void cmd_flush(Shard& sh, Op&) {
    if (sh.store().snapshot_active()) {
        // The scatter snapshot gate has serialized every frozen pre-image before this handler is
        // reached.  Keep the frozen table allocation/cursor alive for the capture walker: clear()
        // frees both tables, which was the pre-existing FLUSH-under-capture bug.  Logical erases
        // retain the table geometry and leave ordinary tombstones for traversal to cross safely.
        sh.store().clear_during_snapshot();
    } else {
        sh.store().clear();
    }
    sh.publish_size();
}

void cmd_randomkey(Shard& sh, Op& op) {
    KvObj* obj = sh.store().random_live(op.hash);
    if (!obj) reply_nil(op.sink());
    else reply_bulk(op.sink(), obj->key());
}

const char* object_type(const KvObj* obj) {
    switch (static_cast<Type>(obj->type)) {
        case Type::String: return "string";
        case Type::Hash: return "hash";
        case Type::List: return "list";
        case Type::Set: return "set";
        case Type::Zset: return "zset";
    }
    return "none";
}

void cmd_scan(Shard& sh, Op& op) {
    uint64_t outer = 0;
    if (!parse_u64(op.arg(1), outer)) {
        reply_err(op.sink(), "ERR invalid cursor"); return;
    }
    const uint32_t shard_id = static_cast<uint32_t>(outer >> 56);
    uint64_t inner = outer & kScanInnerMask;
    if (!g_server || shard_id >= g_server->nshards() || shard_id != static_cast<uint32_t>(sh.id()) ||
        inner > kMaxInnerCursor) {
        reply_err(op.sink(), "ERR invalid cursor"); return;
    }
    Slice match("*", 1), type;
    uint32_t count = 10;
    for (uint32_t i = 2; i < op.argc();) {
        if (eq_icase(op.arg(i), "MATCH") && i + 1 < op.argc()) {
            match = op.arg(i + 1); i += 2;
        } else if (eq_icase(op.arg(i), "COUNT") && i + 1 < op.argc()) {
            uint64_t parsed = 0;
            if (!parse_u64(op.arg(i + 1), parsed) || parsed == 0 || parsed > UINT32_MAX) {
                reply_syntax(op.sink()); return;
            }
            count = static_cast<uint32_t>(parsed); i += 2;
        } else if (eq_icase(op.arg(i), "TYPE") && i + 1 < op.argc()) {
            type = op.arg(i + 1);
            if (!(eq_icase(type, "STRING") || eq_icase(type, "HASH") || eq_icase(type, "LIST") ||
                  eq_icase(type, "SET") || eq_icase(type, "ZSET") || eq_icase(type, "NONE"))) {
                reply_syntax(op.sink()); return;
            }
            i += 2;
        } else { reply_syntax(op.sink()); return; }
    }

    std::vector<Slice> keys;
    keys.reserve(std::min<uint32_t>(count, 1024));
    inner = sh.store().scan(inner, count, [&](KvObj* obj) {
        if (type.n && !eq_icase(type, object_type(obj))) return;
        if (glob_match(match, obj->key())) keys.push_back(obj->key());
    });
    uint64_t next = 0;
    if (inner) next = (static_cast<uint64_t>(shard_id) << 56) | inner;
    else if (shard_id + 1 < g_server->nshards()) next = static_cast<uint64_t>(shard_id + 1) << 56;

    char cursor[24];
    const uint32_t cursor_len = u64_to_dec(cursor, next);
    auto sink = op.sink();
    reply_array_header(sink, 2);
    reply_bulk(sink, Slice(cursor, cursor_len));
    reply_array_header(sink, keys.size());
    for (Slice key : keys) reply_bulk(sink, key);
}

static const CommandSpec kTable[] = {
    // name       min max flags                                                    handler        first last step
    {"PING",       1,  2, CmdFlags::ConnLocal,                                    cmd_ping,       0,  0, 0},
    {"SAVE",       1,  1, CmdFlags::ConnLocal | CmdFlags::Admin,                  cmd_save,       0,  0, 0},
    {"BGSAVE",     1,  2, CmdFlags::ConnLocal | CmdFlags::Admin,                  cmd_bgsave,     0,  0, 0},
    {"LASTSAVE",   1,  1, CmdFlags::ConnLocal | CmdFlags::Admin,                  cmd_lastsave,   0,  0, 0},
    {"ECHO",       2,  2, CmdFlags::ConnLocal,                                    cmd_echo,       0,  0, 0},
    {"AUTH",       2,  3, CmdFlags::ConnLocal,                                    cmd_auth,       0,  0, 0},
    {"HELLO",      1,  2, CmdFlags::ConnLocal,                                    cmd_hello,      0,  0, 0},
    {"RESET",      1,  1, CmdFlags::ConnLocal,                                    cmd_reset,      0,  0, 0},
    {"CLIENT",     2, -1, CmdFlags::ConnLocal | CmdFlags::Admin,                  cmd_client,     0,  0, 0},
    {"COMMAND",    1, -1, CmdFlags::ConnLocal | CmdFlags::Admin,                  cmd_command,    0,  0, 0},
    {"CONFIG",     2, -1, CmdFlags::Admin | CmdFlags::ConfigRoute,                cmd_config,     0,  0, 0},
    {"INFO",       1,  2, CmdFlags::ConnLocal | CmdFlags::Admin,                  cmd_info,       0,  0, 0},
    {"SELECT",     2,  2, CmdFlags::ConnLocal,                                    cmd_select,     0,  0, 0},
        {"DBSIZE",     1,  2, CmdFlags::Admin | CmdFlags::ConfigRoute,                cmd_dbsize,     0,  0, 0},
    {"FLUSHALL",   1,  2, CmdFlags::Write | CmdFlags::Admin | CmdFlags::AllShards,cmd_flush,      0,  0, 0},
    {"FLUSHDB",    1,  2, CmdFlags::Write | CmdFlags::Admin | CmdFlags::AllShards,cmd_flush,      0,  0, 0},
    {"RANDOMKEY",  1,  1, CmdFlags::Readonly | CmdFlags::RandomShard,             cmd_randomkey,  0,  0, 0},
    {"SCAN",       2, -1, CmdFlags::Readonly | CmdFlags::CursorShard,             cmd_scan,       0,  0, 0},
    {"KEYS",       2,  2, CmdFlags::Readonly | CmdFlags::Admin | CmdFlags::MultiShard,cmd_xshard_only,0,0,0},
    {"SORT",       2, -1, CmdFlags::Write | CmdFlags::DenyOom | CmdFlags::MultiShard,cmd_xshard_only,1,1,1},
};

}  // namespace

void command_bind_server(Server* server) {
    g_server = server;
    scripting_bind_server(server);
    g_started_monotonic_ns = now_ns();
    if (server) init_config(server->cfg());
}

void command_set_local_context(Client* client, ThreadCtx* thread) {
    g_client = client;
    g_thread = thread;
}

void command_client_connected(Client* client, const char* addr) {
    if (!client) return;
    ClientMeta meta;
    meta.id = client->id();
    meta.addr = addr ? addr : "unknown:0";
    std::lock_guard<std::mutex> lock(g_clients_mu);
    g_clients[client] = std::move(meta);
}

void command_client_disconnected(Client* client) {
    std::lock_guard<std::mutex> lock(g_clients_mu);
    g_clients.erase(client);
}

bool command_prepare_scan_route(Server& server, Op& op) {
    if (op.spec->flags & CmdFlags::ScriptRoute)
        return command_prepare_script_route(server, op);
    uint64_t cursor = 0;
    if (!parse_u64(op.arg(1), cursor) || (cursor & kScanInnerMask) > kMaxInnerCursor) {
        reply_err(op.sink(), "ERR invalid cursor"); return false;
    }
    const uint32_t shard = static_cast<uint32_t>(cursor >> 56);
    if (shard >= server.nshards()) { reply_err(op.sink(), "ERR invalid cursor"); return false; }
    op.hash = cursor;
    op.shard = static_cast<int32_t>(shard);
    return true;
}

bool command_validate_all_shards(Op& op) {
    if (op.argc() == 1) return true;
    if (op.argc() == 2 && (eq_icase(op.arg(1), "ASYNC") || eq_icase(op.arg(1), "SYNC"))) return true;
    reply_syntax(op.sink());
    return false;
}

bool command_config_routes_all_shards(Op& op) {
    // The conditional-scatter route: CONFIG SET fans out; DBSIZE NOW (owner request 2026-08-25)
    // is the exact-on-demand variant -- each owner counts its own store at execution time, so the
    // reply reflects everything already dispatched ahead of it on every shard, with none of the
    // batch-boundary publication lag the plain DBSIZE reads.
    if (op.cmd_name().eq_icase("dbsize")) return op.argc() == 2 && eq_icase(op.arg(1), "NOW");
    return op.argc() >= 2 && eq_icase(op.arg(1), "SET");
}

bool command_validate_config_set(Op& op) {
    if (op.cmd_name().eq_icase("dbsize")) return true;   // DBSIZE NOW needs no further validation
    std::lock_guard<std::mutex> lock(g_config_mu);
    std::vector<std::pair<ConfigValue*, std::string>> updates;
    return collect_config_updates(op, updates);
}

CommandTable server_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
