// scripting.cc — EVAL/EVALSHA and the process-wide SHA1 script cache.
//
// Routing validates the declared KEYS range on IO. Execution is one ordinary task on that shard's
// owner, so Lua and every redis.call handler obey the ownership law without locks around a shard.
// The cache is the only cross-thread scripting object and is protected independently of shard data.
#include "command.h"

#include <algorithm>
#include <array>
#include <charconv>
#include <climits>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <mutex>
#include <new>
#include <string>
#include <string_view>
#include <unordered_map>
#include <utility>
#include <vector>

#include "../core/server.h"
#include "../core/shard.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include "../snapshot/format.h"
#include "../store/kvobj.h"

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wimplicit-fallthrough"
extern "C" {
#include "../../third_party/lua/lua_amalgamation.c"
}
#pragma GCC diagnostic pop

// Private Lua source macros must not escape into the surrounding C++ translation unit.
#undef getline
#undef next

namespace tomo {
namespace {

constexpr uint32_t kScriptMaxBytes = 1024 * 1024;
constexpr uint64_t kInstructionLimit = 100000;
constexpr int kHookInterval = 1000;
constexpr uint32_t kReplyMaxDepth = 32;
constexpr uint32_t kReplyMaxElements = 100000;

Server* g_script_server = nullptr;
char g_hook_context_key;

uint32_t rotl32(uint32_t value, uint32_t bits) {
    return (value << bits) | (value >> (32 - bits));
}

std::string sha1_hex(Slice input) {
    uint32_t h0 = 0x67452301u, h1 = 0xefcdab89u, h2 = 0x98badcfeu,
             h3 = 0x10325476u, h4 = 0xc3d2e1f0u;
    const uint64_t bit_length = static_cast<uint64_t>(input.n) * 8;
    const size_t padded = (static_cast<size_t>(input.n) + 9 + 63) & ~size_t{63};
    std::vector<uint8_t> bytes(padded, 0);
    if (input.n) std::memcpy(bytes.data(), input.p, input.n);
    bytes[input.n] = 0x80;
    for (uint32_t i = 0; i < 8; i++)
        bytes[padded - 1 - i] = static_cast<uint8_t>(bit_length >> (i * 8));

    for (size_t block = 0; block < padded; block += 64) {
        uint32_t words[80];
        for (uint32_t i = 0; i < 16; i++) {
            const uint8_t* p = bytes.data() + block + i * 4;
            words[i] = (static_cast<uint32_t>(p[0]) << 24) |
                       (static_cast<uint32_t>(p[1]) << 16) |
                       (static_cast<uint32_t>(p[2]) << 8) | p[3];
        }
        for (uint32_t i = 16; i < 80; i++)
            words[i] = rotl32(words[i - 3] ^ words[i - 8] ^ words[i - 14] ^ words[i - 16], 1);
        uint32_t a = h0, b = h1, c = h2, d = h3, e = h4;
        for (uint32_t i = 0; i < 80; i++) {
            uint32_t f, k;
            if (i < 20) { f = (b & c) | ((~b) & d); k = 0x5a827999u; }
            else if (i < 40) { f = b ^ c ^ d; k = 0x6ed9eba1u; }
            else if (i < 60) { f = (b & c) | (b & d) | (c & d); k = 0x8f1bbcdcu; }
            else { f = b ^ c ^ d; k = 0xca62c1d6u; }
            const uint32_t next = rotl32(a, 5) + f + e + k + words[i];
            e = d; d = c; c = rotl32(b, 30); b = a; a = next;
        }
        h0 += a; h1 += b; h2 += c; h3 += d; h4 += e;
    }
    const uint32_t digest[5] = {h0, h1, h2, h3, h4};
    static constexpr char hex[] = "0123456789abcdef";
    std::string result(40, '0');
    for (uint32_t i = 0; i < 20; i++) {
        const uint8_t byte = static_cast<uint8_t>(digest[i / 4] >> (24 - (i % 4) * 8));
        result[i * 2] = hex[byte >> 4];
        result[i * 2 + 1] = hex[byte & 15];
    }
    return result;
}

class ScriptCache {
public:
    bool store(Slice body, std::string& sha) {
        try {
            sha = sha1_hex(body);
            std::string source(body.p, body.n);
            std::lock_guard<std::mutex> lock(mu_);
            scripts_.insert_or_assign(sha, std::move(source));
            return true;
        } catch (const std::bad_alloc&) {
            return false;
        }
    }

    bool find(Slice sha, std::string& source) const {
        try {
            std::lock_guard<std::mutex> lock(mu_);
            const auto it = scripts_.find(std::string(sha.p, sha.n));
            if (it == scripts_.end()) return false;
            source = it->second;
            return true;
        } catch (const std::bad_alloc&) {
            return false;
        }
    }

    bool exists(Slice sha) const {
        try {
            std::lock_guard<std::mutex> lock(mu_);
            return scripts_.find(std::string(sha.p, sha.n)) != scripts_.end();
        } catch (const std::bad_alloc&) {
            return false;
        }
    }

    void flush() {
        std::lock_guard<std::mutex> lock(mu_);
        scripts_.clear();
    }

private:
    mutable std::mutex mu_;
    std::unordered_map<std::string, std::string> scripts_;
};

ScriptCache g_scripts;

bool parse_nonnegative(Slice value, uint32_t& result, bool& negative) {
    negative = false;
    if (!value.n) return false;
    uint32_t pos = 0;
    if (value.p[0] == '-') { negative = true; pos = 1; }
    if (pos == value.n) return false;
    uint64_t parsed = 0;
    for (; pos < value.n; pos++) {
        const uint8_t c = static_cast<uint8_t>(value.p[pos]);
        if (c < '0' || c > '9') return false;
        parsed = parsed * 10 + (c - '0');
        if (parsed > UINT32_MAX) return false;
    }
    result = static_cast<uint32_t>(parsed);
    return true;
}

void reply_text_error(Op& op, std::string_view kind, std::string_view detail) {
    auto sink = op.sink();
    sink.push_back('-');
    sink.append(kind.data(), kind.size());
    if (!detail.empty()) { sink.push_back(' '); sink.append(detail.data(), detail.size()); }
    sink.append("\r\n", 2);
}

std::string clean_error(const char* text, size_t length) {
    const size_t take = std::min<size_t>(length, 2048);
    std::string result;
    result.reserve(take);
    for (size_t i = 0; i < take; i++) {
        const char ch = text[i];
        result.push_back(ch == '\r' || ch == '\n' || ch == '\0' ? ' ' : ch);
    }
    return result;
}

bool validate_source(Slice source, std::string& error) {
    if (source.n > kScriptMaxBytes) {
        error = "script exceeds the 1 MiB limit";
        return false;
    }
    if (source.n && static_cast<uint8_t>(source.p[0]) == 0x1b) {
        error = "binary chunks are not allowed";
        return false;
    }
    lua_State* state = luaL_newstate();
    if (!state) { error = "out of memory"; return false; }
    const int status = luaL_loadbuffer(state, source.p, source.n, "user_script");
    if (status != 0) {
        size_t length = 0;
        const char* detail = lua_tolstring(state, -1, &length);
        error = clean_error(detail ? detail : "compile error", detail ? length : 13);
    }
    lua_close(state);
    return status == 0;
}

struct UndoEntry {
    std::string key;
    uint64_t hash = 0;
    KvObj* original = nullptr;
};

class ScriptUndo {
public:
    ~ScriptUndo() {
        for (UndoEntry& entry : entries_) if (entry.original) kvobj_free(entry.original);
    }

    bool capture(Shard& shard, const Op& op, uint32_t first, uint32_t count) {
        try { entries_.reserve(count); }
        catch (const std::bad_alloc&) { return false; }
        for (uint32_t i = 0; i < count; i++) {
            const Slice key = op.arg(first + i);
            bool duplicate = false;
            for (const UndoEntry& prior : entries_)
                duplicate |= Slice(prior.key.data(), static_cast<uint32_t>(prior.key.size())) == key;
            if (duplicate) continue;
            UndoEntry entry;
            try { entry.key.assign(key.p, key.n); }
            catch (const std::bad_alloc&) { return false; }
            entry.hash = FlatStore::hash_key(key);
            KvObj* current = shard.store().find(entry.hash, key);
            if (current && !clone_object(shard, *current, key, entry.original)) return false;
            try { entries_.push_back(std::move(entry)); }
            catch (const std::bad_alloc&) {
                if (entry.original) kvobj_free(entry.original);
                return false;
            }
        }
        return true;
    }

    bool rollback(Shard& shard) {
        for (UndoEntry& entry : entries_) {
            const Slice key(entry.key.data(), static_cast<uint32_t>(entry.key.size()));
            shard.store().erase(entry.hash, key);
        }
        for (UndoEntry& entry : entries_) {
            if (!entry.original) continue;
            if (shard.store().insert(entry.hash, entry.original) != FlatStore::InsertResult::Inserted)
                return false;
            entry.original = nullptr;
        }
        return true;
    }

private:
    static bool clone_object(Shard& shard, KvObj& object, Slice key, KvObj*& result) {
        const Type type = static_cast<Type>(object.type);
        const SnapshotTypeHooks& hooks = snapshot_type_hooks(type);
        SnapshotSaveCursor cursor;
        uint8_t encoding = 0;
        if (!hooks.begin_save || !hooks.read_save || !hooks.load ||
            hooks.begin_save(object, cursor, encoding) != SnapshotHookStatus::Ok ||
            cursor.total > UINT32_MAX) return false;
        std::vector<uint8_t> payload;
        try { payload.resize(static_cast<size_t>(cursor.total)); }
        catch (const std::bad_alloc&) { return false; }
        while (cursor.offset < cursor.total) {
            size_t written = 0;
            if (hooks.read_save(cursor, payload.data() + cursor.offset,
                                payload.size() - static_cast<size_t>(cursor.offset), written) !=
                    SnapshotHookStatus::Ok || !written) return false;
        }
        const Slice bytes(reinterpret_cast<const char*>(payload.data()),
                          static_cast<uint32_t>(payload.size()));
        return hooks.load(key, encoding, object.expire_at_ms(), bytes,
                          shard.type_limits(), result) == SnapshotHookStatus::Ok && result;
    }

    std::vector<UndoEntry> entries_;
};

class ScriptEvictionGuard {
public:
    ScriptEvictionGuard(Shard& shard, bool active) : store_(active ? &shard.store() : nullptr) {
        if (store_) previous_ = store_->script_suspend_eviction();
    }
    ~ScriptEvictionGuard() { if (store_) store_->script_restore_eviction(previous_); }
    ScriptEvictionGuard(const ScriptEvictionGuard&) = delete;
    ScriptEvictionGuard& operator=(const ScriptEvictionGuard&) = delete;
private:
    FlatStore* store_ = nullptr;
    MaxmemoryPolicy previous_ = MaxmemoryPolicy::NoEviction;
};

struct ScriptContext {
    Shard* shard = nullptr;
    Op* parent = nullptr;
    uint32_t key_first = 0;
    uint32_t key_count = 0;
    uint64_t instructions = 0;
    bool timed_out = false;
};

// Persistent per-thread engine. Building luaL_newstate + the sandbox + recompiling the source on
// EVERY call measured 53.8k EVALSHA/s at p50 18.9 ms against vanilla redis's 550k/s (~18 µs of
// per-call construction). Scripts execute on shard-owner executors, so one state per thread needs
// no locks: sandbox and compiled chunks are built once; a call rebinds only the context slot and
// the KEYS/ARGV tables. The sandbox closures capture a pointer to `current` (stable for the life
// of the state), never a per-call context address.
struct LuaEngine {
    lua_State* state = nullptr;
    ScriptContext* current = nullptr;   // per-call slot; closures and the hook read through this
    uint64_t flush_generation = 0;      // mirrors g_script_flushes when the state was (re)built
    ~LuaEngine() {
        if (state) lua_close(state);
    }
};
thread_local LuaEngine t_lua_engine;
std::atomic<uint64_t> g_script_flushes{0};

ScriptContext* lua_context(lua_State* state) {
    lua_pushlightuserdata(state, &g_hook_context_key);
    lua_gettable(state, LUA_REGISTRYINDEX);
    auto* slot = static_cast<ScriptContext**>(lua_touserdata(state, -1));
    lua_pop(state, 1);
    return slot ? *slot : nullptr;
}

void instruction_hook(lua_State* state, lua_Debug*) {
    ScriptContext* context = lua_context(state);
    if (!context) return;
    context->instructions += kHookInterval;
    if (context->instructions > kInstructionLimit) {
        context->timed_out = true;
        luaL_error(state, "script exceeded the %llu instruction limit",
                   static_cast<unsigned long long>(kInstructionLimit));
    }
}

bool command_name_is(const CommandSpec& spec, const char* expected) {
    return std::strcmp(spec.name, expected) == 0;
}

bool script_name_whitelisted(const CommandSpec& spec) {
    // Deliberately explicit: command-table shape alone does not prove determinism (SPOP and
    // HRANDFIELD are both single-key). New commands remain unavailable until this list is audited.
    static constexpr const char* allowed[] = {
        "APPEND", "BITCOUNT", "BITPOS", "DECR", "DECRBY", "DEL", "EXISTS",
        "GET", "GETBIT", "GETRANGE", "GETSET",
        "HDEL", "HEXISTS", "HGET", "HGETALL", "HINCRBY", "HINCRBYFLOAT", "HKEYS",
        "HLEN", "HMGET", "HSET", "HSETNX", "HSTRLEN", "HVALS",
        "INCR", "INCRBY", "INCRBYFLOAT",
        "LINDEX", "LINSERT", "LLEN", "LPOP", "LPOS", "LPUSH", "LPUSHX", "LRANGE",
        "LREM", "LSET", "LTRIM",
        "PFADD", "PERSIST", "RPOP", "RPUSH", "RPUSHX",
        "SADD", "SCARD", "SISMEMBER", "SMEMBERS", "SMISMEMBER", "SREM",
        "SET", "SETBIT", "SETNX", "SETRANGE", "STRLEN", "TOUCH", "TYPE", "UNLINK",
        "ZADD", "ZCARD", "ZCOUNT", "ZINCRBY", "ZLEXCOUNT", "ZPOPMAX", "ZPOPMIN",
        "ZRANGE", "ZRANGEBYLEX", "ZRANGEBYSCORE", "ZRANK", "ZREM", "ZREMRANGEBYLEX",
        "ZREMRANGEBYRANK", "ZREMRANGEBYSCORE", "ZREVRANGE", "ZREVRANGEBYLEX",
        "ZREVRANGEBYSCORE", "ZREVRANK", "ZSCORE",
    };
    for (const char* name : allowed) if (command_name_is(spec, name)) return true;
    return false;
}

bool script_command_allowed(const CommandSpec& spec, uint32_t argc) {
    const uint32_t forbidden = CmdFlags::Admin | CmdFlags::ConnLocal | CmdFlags::AllShards |
        CmdFlags::RandomShard | CmdFlags::CursorShard | CmdFlags::ConfigRoute |
        CmdFlags::ScriptRoute;
    if ((spec.flags & forbidden) || !script_name_whitelisted(spec)) return false;
    if (spec.flags & CmdFlags::MultiShard) {
        return argc == 2 && (command_name_is(spec, "DEL") || command_name_is(spec, "UNLINK") ||
                            command_name_is(spec, "EXISTS") || command_name_is(spec, "TOUCH"));
    }
    if (spec.first_key <= 0 || spec.last_key != spec.first_key || spec.key_step != 1) return false;
    return true;
}

bool key_declared(const ScriptContext& context, Slice key) {
    for (uint32_t i = 0; i < context.key_count; i++)
        if (context.parent->arg(context.key_first + i) == key) return true;
    return false;
}

bool parse_decimal_line(const char* data, size_t size, size_t& pos, int64_t& value) {
    const size_t begin = pos;
    while (pos + 1 < size && !(data[pos] == '\r' && data[pos + 1] == '\n')) pos++;
    if (pos + 1 >= size || pos == begin) return false;
    const auto converted = std::from_chars(data + begin, data + pos, value);
    if (converted.ec != std::errc{} || converted.ptr != data + pos) return false;
    pos += 2;
    return true;
}

bool push_resp_value(lua_State* state, const char* data, size_t size, size_t& pos,
                     uint32_t depth, bool top, bool& server_error, std::string& error) {
    if (pos >= size || depth > kReplyMaxDepth) { error = "invalid nested command reply"; return false; }
    const char marker = data[pos++];
    if (marker == '+' || marker == '-') {
        const size_t begin = pos;
        while (pos + 1 < size && !(data[pos] == '\r' && data[pos + 1] == '\n')) pos++;
        if (pos + 1 >= size) { error = "invalid nested command reply"; return false; }
        const size_t length = pos - begin;
        pos += 2;
        if (marker == '-' && top) {
            server_error = true;
            error.assign(data + begin, length);
            return true;
        }
        lua_createtable(state, 0, 1);
        lua_pushlstring(state, data + begin, length);
        lua_setfield(state, -2, marker == '+' ? "ok" : "err");
        return true;
    }
    if (marker == ':') {
        int64_t value = 0;
        if (!parse_decimal_line(data, size, pos, value)) {
            error = "invalid integer command reply"; return false;
        }
        lua_pushnumber(state, static_cast<lua_Number>(value));
        return true;
    }
    if (marker == '$') {
        int64_t length = 0;
        if (!parse_decimal_line(data, size, pos, length) || length < -1) {
            error = "invalid bulk command reply"; return false;
        }
        if (length == -1) { lua_pushboolean(state, 0); return true; }
        if (static_cast<uint64_t>(length) > size - pos ||
            static_cast<uint64_t>(length) + 2 > size - pos ||
            data[pos + length] != '\r' || data[pos + length + 1] != '\n') {
            error = "truncated bulk command reply"; return false;
        }
        lua_pushlstring(state, data + pos, static_cast<size_t>(length));
        pos += static_cast<size_t>(length) + 2;
        return true;
    }
    if (marker == '*') {
        int64_t count = 0;
        if (!parse_decimal_line(data, size, pos, count) || count < -1 ||
            count > static_cast<int64_t>(kReplyMaxElements)) {
            error = "invalid array command reply"; return false;
        }
        if (count == -1) { lua_pushboolean(state, 0); return true; }
        lua_createtable(state, static_cast<int>(count), 0);
        for (int64_t i = 0; i < count; i++) {
            bool child_error = false;
            if (!push_resp_value(state, data, size, pos, depth + 1, false, child_error, error))
                return false;
            lua_rawseti(state, -2, static_cast<int>(i + 1));
        }
        return true;
    }
    error = "unsupported nested command reply";
    return false;
}

int redis_dispatch(lua_State* state, bool protected_call) {
    auto* slot = static_cast<ScriptContext**>(lua_touserdata(state, lua_upvalueindex(1)));
    ScriptContext* context = slot ? *slot : nullptr;
    char deferred_error[2100] = {};
    bool failed = false;
    {
        const int argc = lua_gettop(state);
        Op nested;
        if (!context || argc < 1) {
            std::snprintf(deferred_error, sizeof(deferred_error), "ERR redis.call requires a command name");
            failed = true;
        } else {
            for (int i = 1; i <= argc && !failed; i++) {
                const int type = lua_type(state, i);
                if (type != LUA_TSTRING && type != LUA_TNUMBER) {
                    std::snprintf(deferred_error, sizeof(deferred_error),
                                  "ERR Lua redis() command arguments must be strings or integers");
                    failed = true;
                    break;
                }
                size_t length = 0;
                const char* value = lua_tolstring(state, i, &length);
                if (length > UINT32_MAX || !nested.push_arg(
                        Slice(value, static_cast<uint32_t>(length)))) {
                    std::snprintf(deferred_error, sizeof(deferred_error), "ERR out of memory");
                    failed = true;
                }
            }
        }

        const CommandSpec* spec = failed ? nullptr : command_lookup(nested.cmd_name());
        if (!failed && (!spec || !command_arity_ok(*spec, nested.argc()))) {
            std::snprintf(deferred_error, sizeof(deferred_error),
                          spec ? "ERR wrong number of arguments for command from script"
                               : "ERR Unknown Redis command called from script");
            failed = true;
        }
        if (!failed && !script_command_allowed(*spec, nested.argc())) {
            std::snprintf(deferred_error, sizeof(deferred_error),
                          "ERR command '%s' is not allowed from scripts", spec->name);
            failed = true;
        }
        if (!failed) {
            const uint32_t key_arg = static_cast<uint32_t>(spec->first_key);
            const Slice key = nested.arg(key_arg);
            if (!key_declared(*context, key)) {
                std::snprintf(deferred_error, sizeof(deferred_error),
                              "ERR Script attempted to access an undeclared key");
                failed = true;
            } else {
                nested.spec = spec;
                nested.db = context->parent->db;
                nested.hash = FlatStore::hash_key(key);
                nested.shard = context->shard->id();
                if ((spec->flags & CmdFlags::DenyOom) &&
                    !context->shard->store().budget_admit(key)) {
                    reply_maxmemory_oom(nested);
                } else {
                    spec->handler(*context->shard, nested);
                }
                if (nested.zc_ptr) {
                    try {
                        std::string borrowed(nested.zc_ptr, nested.zc_len);
                        context->shard->store().unborrow(nested.zc_ptr);
                        nested.zc_ptr = nullptr;
                        lua_pushlstring(state, borrowed.data(), borrowed.size());
                    } catch (const std::bad_alloc&) {
                        context->shard->store().unborrow(nested.zc_ptr);
                        nested.zc_ptr = nullptr;
                        std::snprintf(deferred_error, sizeof(deferred_error), "ERR out of memory");
                        failed = true;
                    }
                } else {
                    size_t pos = 0;
                    bool server_error = false;
                    std::string parse_error;
                    if (!push_resp_value(state, nested.reply.data(), nested.reply.size(), pos, 0,
                                         true, server_error, parse_error) ||
                        (!server_error && pos != nested.reply.size())) {
                        std::snprintf(deferred_error, sizeof(deferred_error), "ERR %s",
                                      parse_error.empty() ? "invalid nested command reply"
                                                          : parse_error.c_str());
                        failed = true;
                    } else if (server_error) {
                        const std::string safe = clean_error(parse_error.data(), parse_error.size());
                        std::snprintf(deferred_error, sizeof(deferred_error), "%s", safe.c_str());
                        failed = true;
                    }
                }
            }
        }
    }

    if (!failed) return 1;
    if (protected_call) {
        lua_createtable(state, 0, 1);
        lua_pushstring(state, deferred_error);
        lua_setfield(state, -2, "err");
        return 1;
    }
    return luaL_error(state, "%s", deferred_error);
}

int redis_call(lua_State* state) { return redis_dispatch(state, false); }
int redis_pcall(lua_State* state) { return redis_dispatch(state, true); }

void remove_global(lua_State* state, const char* name) {
    lua_pushnil(state);
    lua_setglobal(state, name);
}

// State reuse must not let one script's globals leak into the next call, so undeclared global
// writes and reads are errors (redis semantics; redis rejects both on its own reused
// interpreter). rawset can still bypass this, exactly as it can in redis — scripts are an
// admin-trust surface.
int protected_global_newindex(lua_State* state) {
    return luaL_error(state, "Script attempted to create global variable '%s'",
                      lua_tostring(state, 2));
}

int protected_global_index(lua_State* state) {
    return luaL_error(state, "Script attempted to access nonexistent global variable '%s'",
                      lua_tostring(state, 2));
}

// Installs `name` into the globals table bypassing the protection metatable; the value to
// install must be on top of the stack.
void set_global_raw(lua_State* state, const char* name) {
    lua_pushvalue(state, LUA_GLOBALSINDEX);
    lua_insert(state, -2);
    lua_pushstring(state, name);
    lua_insert(state, -2);
    lua_rawset(state, -3);
    lua_pop(state, 1);
}

void open_library(lua_State* state, lua_CFunction open, const char* name) {
    lua_pushcfunction(state, open);
    lua_pushstring(state, name);
    lua_call(state, 1, 0);
}

// Built ONCE per thread state: libraries, strips, the redis table (closures over the stable
// per-state context slot), the hook registry entry, and — last — the globals protection.
void create_sandbox_static(lua_State* state, ScriptContext** slot) {
    open_library(state, luaopen_base, "");
    open_library(state, luaopen_table, LUA_TABLIBNAME);
    open_library(state, luaopen_string, LUA_STRLIBNAME);
    open_library(state, luaopen_math, LUA_MATHLIBNAME);
    remove_global(state, "dofile");
    remove_global(state, "load");
    remove_global(state, "loadfile");
    remove_global(state, "loadstring");
    remove_global(state, "print");
    remove_global(state, "newproxy");
    remove_global(state, "collectgarbage");
    remove_global(state, "coroutine");
    lua_getglobal(state, "string");
    lua_pushnil(state); lua_setfield(state, -2, "dump");
    lua_pop(state, 1);
    lua_getglobal(state, "math");
    lua_pushnil(state); lua_setfield(state, -2, "random");
    lua_pushnil(state); lua_setfield(state, -2, "randomseed");
    lua_pop(state, 1);

    lua_createtable(state, 0, 2);
    lua_pushlightuserdata(state, slot);
    lua_pushcclosure(state, redis_call, 1);
    lua_setfield(state, -2, "call");
    lua_pushlightuserdata(state, slot);
    lua_pushcclosure(state, redis_pcall, 1);
    lua_setfield(state, -2, "pcall");
    lua_setglobal(state, "redis");

    lua_pushlightuserdata(state, &g_hook_context_key);
    lua_pushlightuserdata(state, slot);
    lua_settable(state, LUA_REGISTRYINDEX);

    // Globals protection LAST, so the setup writes above bypass nothing. KEYS/ARGV are installed
    // per call via set_global_raw.
    lua_pushvalue(state, LUA_GLOBALSINDEX);
    lua_createtable(state, 0, 2);
    lua_pushcfunction(state, protected_global_newindex);
    lua_setfield(state, -2, "__newindex");
    lua_pushcfunction(state, protected_global_index);
    lua_setfield(state, -2, "__index");
    lua_setmetatable(state, -2);
    lua_pop(state, 1);
}

// Rebuilt per call: only the tables whose contents depend on the op.
void bind_call_tables(lua_State* state, ScriptContext& context) {
    lua_createtable(state, static_cast<int>(context.key_count), 0);
    for (uint32_t i = 0; i < context.key_count; i++) {
        const Slice key = context.parent->arg(context.key_first + i);
        lua_pushlstring(state, key.p, key.n);
        lua_rawseti(state, -2, static_cast<int>(i + 1));
    }
    set_global_raw(state, "KEYS");

    const uint32_t argv_first = context.key_first + context.key_count;
    const uint32_t argv_count = context.parent->argc() - argv_first;
    lua_createtable(state, static_cast<int>(argv_count), 0);
    for (uint32_t i = 0; i < argv_count; i++) {
        const Slice value = context.parent->arg(argv_first + i);
        lua_pushlstring(state, value.p, value.n);
        lua_rawseti(state, -2, static_cast<int>(i + 1));
    }
    set_global_raw(state, "ARGV");
}

bool append_lua_result(lua_State* state, int index, SmallBuf<kInlineReply>& output,
                       uint32_t depth, uint32_t& elements, std::string& error) {
    if (depth > kReplyMaxDepth) { error = "script reply nesting is too deep"; return false; }
    index = index < 0 ? lua_gettop(state) + index + 1 : index;
    const int type = lua_type(state, index);
    if (type == LUA_TNIL || (type == LUA_TBOOLEAN && !lua_toboolean(state, index))) {
        reply_nil(output);
        return true;
    }
    if (type == LUA_TBOOLEAN) { reply_int(output, 1); return true; }
    if (type == LUA_TNUMBER) {
        const lua_Number number = lua_tonumber(state, index);
        if (!std::isfinite(number) || number < static_cast<lua_Number>(LLONG_MIN) ||
            number > static_cast<lua_Number>(LLONG_MAX)) {
            error = "script returned a non-integer number"; return false;
        }
        reply_int(output, static_cast<long long>(number));
        return true;
    }
    if (type == LUA_TSTRING) {
        size_t length = 0;
        const char* value = lua_tolstring(state, index, &length);
        if (length > UINT32_MAX) { error = "script reply is too large"; return false; }
        reply_bulk(output, Slice(value, static_cast<uint32_t>(length)));
        return true;
    }
    if (type != LUA_TTABLE) { error = "script returned an unsupported Lua type"; return false; }

    lua_getfield(state, index, "err");
    if (!lua_isnil(state, -1)) {
        size_t length = 0;
        const char* value = lua_tolstring(state, -1, &length);
        if (!value) { lua_pop(state, 1); error = "invalid redis error table"; return false; }
        output.push_back('-'); output.append(value, length); output.append("\r\n", 2);
        lua_pop(state, 1);
        return true;
    }
    lua_pop(state, 1);
    lua_getfield(state, index, "ok");
    if (!lua_isnil(state, -1)) {
        size_t length = 0;
        const char* value = lua_tolstring(state, -1, &length);
        if (!value) { lua_pop(state, 1); error = "invalid redis status table"; return false; }
        output.push_back('+'); output.append(value, length); output.append("\r\n", 2);
        lua_pop(state, 1);
        return true;
    }
    lua_pop(state, 1);

    uint32_t count = 0;
    for (;;) {
        if (++elements > kReplyMaxElements) { error = "script reply has too many elements"; return false; }
        lua_rawgeti(state, index, static_cast<int>(count + 1));
        const bool stop = lua_isnil(state, -1);
        lua_pop(state, 1);
        if (stop) break;
        count++;
    }
    reply_array_header(output, count);
    for (uint32_t i = 0; i < count; i++) {
        lua_rawgeti(state, index, static_cast<int>(i + 1));
        const bool ok = append_lua_result(state, -1, output, depth + 1, elements, error);
        lua_pop(state, 1);
        if (!ok) return false;
    }
    return true;
}

void run_eval(Shard& shard, Op& op, Slice source, bool cache_source, Slice sha_hint) {
    if (source.n > kScriptMaxBytes) {
        reply_text_error(op, "ERR", "script exceeds the 1 MiB limit");
        return;
    }
    if (source.n && static_cast<uint8_t>(source.p[0]) == 0x1b) {
        reply_text_error(op, "ERR", "Error compiling script: binary chunks are not allowed");
        return;
    }
    uint32_t key_first = 0, key_count = 0;
    if (!command_script_key_range(op, key_first, key_count)) {
        reply_text_error(op, "ERR", "invalid script key declaration");
        return;
    }

    LuaEngine& engine = t_lua_engine;
    if (engine.state &&
        engine.flush_generation != g_script_flushes.load(std::memory_order_acquire)) {
        // SCRIPT FLUSH invalidates every thread's compiled-chunk cache; rebuilding the whole
        // state is the simple correct form and FLUSH is admin-cold.
        lua_close(engine.state);
        engine.state = nullptr;
    }
    if (!engine.state) {
        engine.state = luaL_newstate();
        if (!engine.state) { reply_text_error(op, "ERR", "out of memory"); return; }
        engine.flush_generation = g_script_flushes.load(std::memory_order_acquire);
        create_sandbox_static(engine.state, &engine.current);
        lua_newtable(engine.state);
        lua_setfield(engine.state, LUA_REGISTRYINDEX, "tomo_chunks");
    }
    lua_State* state = engine.state;
    ScriptContext context{&shard, &op, key_first, key_count};
    engine.current = &context;

    // Fetch the compiled chunk by sha, compiling at most once per thread per script.
    std::string sha_storage;
    Slice sha = sha_hint;
    if (!sha.n) {
        sha_storage = sha1_hex(source);
        sha = Slice(sha_storage.data(), static_cast<uint32_t>(sha_storage.size()));
    }
    lua_getfield(state, LUA_REGISTRYINDEX, "tomo_chunks");
    lua_pushlstring(state, sha.p, sha.n);
    lua_rawget(state, -2);
    if (lua_isnil(state, -1)) {
        lua_pop(state, 1);
        const int compiled = luaL_loadbuffer(state, source.p, source.n, "user_script");
        if (compiled != 0) {
            size_t length = 0;
            const char* text = lua_tolstring(state, -1, &length);
            const std::string error =
                clean_error(text ? text : "compile error", text ? length : 13);
            lua_settop(state, 0);
            engine.current = nullptr;
            reply_text_error(op, "ERR", std::string("Error compiling script: ") + error);
            return;
        }
        lua_pushlstring(state, sha.p, sha.n);
        lua_pushvalue(state, -2);
        lua_rawset(state, -4);
    }
    lua_remove(state, -2);   // drop the chunk table, leaving the function on top
    if (cache_source) {
        std::string ignored;
        if (!g_scripts.store(source, ignored)) {
            lua_settop(state, 0);
            engine.current = nullptr;
            reply_text_error(op, "ERR", "out of memory caching script");
            return;
        }
    }

    ScriptUndo undo;
    const bool atomic = g_script_server && g_script_server->atomic_enabled();
    if (atomic && !undo.capture(shard, op, key_first, key_count)) {
        lua_settop(state, 0);
        engine.current = nullptr;
        reply_text_error(op, "ERR", "out of memory preparing atomic script");
        return;
    }
    ScriptEvictionGuard eviction_guard(shard, atomic);

    bind_call_tables(state, context);
    lua_sethook(state, instruction_hook, LUA_MASKCOUNT, kHookInterval);
    const int status = lua_pcall(state, 0, 1, 0);
    lua_sethook(state, nullptr, 0, 0);
    if (status != 0) {
        size_t length = 0;
        const char* text = lua_tolstring(state, -1, &length);
        const std::string error = clean_error(text ? text : "runtime error", text ? length : 13);
        lua_settop(state, 0);
        engine.current = nullptr;
        const bool restored = !atomic || undo.rollback(shard);
        if (!restored) reply_text_error(op, "ERR", "atomic script rollback failed");
        else if (context.timed_out)
            reply_text_error(op, "BUSY", "script exceeded the 100000 instruction limit");
        else reply_text_error(op, "ERR", std::string("Error running script: ") + error);
        return;
    }

    SmallBuf<kInlineReply> result;
    std::string conversion_error;
    uint32_t elements = 0;
    const bool converted = append_lua_result(
        state, -1, result, 0, elements, conversion_error);
    lua_settop(state, 0);
    engine.current = nullptr;
    if (!converted) {
        const bool restored = !atomic || undo.rollback(shard);
        reply_text_error(op, "ERR", restored
            ? std::string("Error running script: ") + conversion_error
            : "atomic script rollback failed");
        return;
    }
    op.sink().append(result.data(), result.size());
}

void cmd_eval(Shard& shard, Op& op) {
    if (op.cmd_name().eq_icase("eval")) {
        run_eval(shard, op, op.arg(1), true, Slice());
        return;
    }
    std::string source;
    if (!g_scripts.find(op.arg(1), source)) {
        reply_text_error(op, "NOSCRIPT", "No matching script. Please use EVAL.");
        return;
    }
    run_eval(shard, op, Slice(source.data(), static_cast<uint32_t>(source.size())), false,
             op.arg(1));
}

void cmd_script(Shard&, Op& op) {
    const Slice subcommand = op.arg(1);
    if (subcommand.eq_icase("load")) {
        if (op.argc() != 3) {
            reply_text_error(op, "ERR", "wrong number of arguments for 'script|load' command");
            return;
        }
        std::string compile_error;
        if (!validate_source(op.arg(2), compile_error)) {
            reply_text_error(op, "ERR", std::string("Error compiling script: ") + compile_error);
            return;
        }
        std::string sha;
        if (!g_scripts.store(op.arg(2), sha)) {
            reply_text_error(op, "ERR", "out of memory caching script");
            return;
        }
        reply_bulk(op.sink(), Slice(sha.data(), static_cast<uint32_t>(sha.size())));
        return;
    }
    if (subcommand.eq_icase("exists")) {
        if (op.argc() < 3) {
            reply_text_error(op, "ERR", "wrong number of arguments for 'script|exists' command");
            return;
        }
        reply_array_header(op.sink(), op.argc() - 2);
        for (uint32_t i = 2; i < op.argc(); i++) reply_int(op.sink(), g_scripts.exists(op.arg(i)));
        return;
    }
    if (subcommand.eq_icase("flush")) {
        if (op.argc() > 3 || (op.argc() == 3 &&
            !(op.arg(2).eq_icase("sync") || op.arg(2).eq_icase("async")))) {
            reply_syntax(op.sink());
            return;
        }
        g_scripts.flush();
        g_script_flushes.fetch_add(1, std::memory_order_release);
        reply_ok(op.sink());
        return;
    }
    reply_text_error(op, "ERR", "Unknown subcommand or wrong number of arguments for 'script'");
}

static const CommandSpec kTable[] = {
    // name       min max flags                                      handler     first last step
    {"EVAL",       3, -1, CmdFlags::Write | CmdFlags::CursorShard | CmdFlags::ScriptRoute,
                                                                    cmd_eval,      3, -1, 1},
    {"EVALSHA",    3, -1, CmdFlags::Write | CmdFlags::CursorShard | CmdFlags::ScriptRoute,
                                                                    cmd_eval,      3, -1, 1},
    {"SCRIPT",     2, -1, CmdFlags::ConnLocal | CmdFlags::Admin,    cmd_script,    0,  0, 0},
};

}  // namespace

void scripting_bind_server(Server* server) { g_script_server = server; }

bool command_script_key_range(const Op& op, uint32_t& first, uint32_t& count) {
    first = 3;
    count = 0;
    if (op.argc() < 3) return false;
    bool negative = false;
    if (!parse_nonnegative(op.arg(2), count, negative) || negative) return false;
    return count <= op.argc() - first;
}

bool command_prepare_script_route(Server& server, Op& op) {
    uint32_t first = 0, count = 0;
    bool negative = false;
    if (!parse_nonnegative(op.arg(2), count, negative)) {
        reply_text_error(op, "ERR", "value is not an integer or out of range");
        return false;
    }
    if (negative) {
        reply_text_error(op, "ERR", "Number of keys can't be negative");
        return false;
    }
    first = 3;
    if (count > op.argc() - first) {
        reply_text_error(op, "ERR", "Number of keys can't be greater than number of args");
        return false;
    }
    if (!count) {
        op.hash = 0;
        op.shard = 0;
        op.mark_local_xshard();
        return true;
    }
    op.hash = FlatStore::hash_key(op.arg(first));
    op.shard = server.router().shard_of(op.hash);
    for (uint32_t i = 1; i < count; i++) {
        const uint64_t hash = FlatStore::hash_key(op.arg(first + i));
        if (server.router().shard_of(hash) != op.shard) {
            reply_text_error(op, "CROSSSLOT", "Keys in request don't hash to the same slot");
            return false;
        }
    }
    op.mark_local_xshard();
    return true;
}

CommandTable scripting_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
