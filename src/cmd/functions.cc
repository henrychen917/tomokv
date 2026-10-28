// functions.cc — the FUNCTION library (Redis 7 functions, Lua engine) plus FCALL / FCALL_RO.
//
// SPLIT WITH scripting.cc. The interpreter — one persistent lua_State per executor thread, its
// sandbox, the undo log, the eviction guard, the RESP converter — belongs to scripting.cc and is
// reached through the narrow seam in scripting.h. This file owns the *library registry*: process-
// wide control-plane state (like ACL users), a cold-path mutex, and a generation counter. Executor
// threads never touch that map on the hot side of a call: each thread synchronizes library
// revisions after a registry change and answers FCALL out of a Lua registry table. Unchanged
// libraries keep their closures and mutable upvalues. State is still per executor; process-wide
// state also needs the scatter commit/retry protocol (docs/scriptfix/single-state-design.md).
//
// The Lua amalgamation is compiled exactly once, in scripting.cc. This translation unit includes
// only the vendored public headers and links against those definitions.
#include "command.h"
#include "notify.h"
#include "scripting.h"

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <mutex>
#include <new>
#include <string>
#include <type_traits>
#include <vector>

#include "../core/server.h"
#include "../core/shard.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include "../snapshot/format.h"

extern "C" {
#include "../../third_party/lua/lua.h"
#include "../../third_party/lua/lauxlib.h"
}

namespace tomo {
namespace {

constexpr uint32_t kLibraryMaxBytes = 1024 * 1024;
constexpr const char* kFunctionChunkName = "@user_function";
constexpr const char* kRegistryFunctions = "tomo_functions";
constexpr const char* kRegistryGeneration = "tomo_fn_generation";
constexpr const char* kRegistryRevisions = "tomo_fn_revisions";
constexpr char kDumpMagic[8] = {'T', 'O', 'M', 'O', 'F', 'U', 'N', '1'};

// Redis 7 function flags. no-writes implies OOM admission; allow-oom permits writes
// over the cap. Replica/cluster-specific flags have no additional effect on this
// single-node server (there is no stale-replica or cluster state).
constexpr uint32_t kFlagNoWrites       = 1u << 0;
constexpr uint32_t kFlagAllowOom       = 1u << 1;
constexpr uint32_t kFlagAllowStale     = 1u << 2;
constexpr uint32_t kFlagNoCluster      = 1u << 3;
constexpr uint32_t kFlagAllowCrossSlot = 1u << 4;

struct FlagName { const char* name; uint32_t bit; };
constexpr FlagName kFlagNames[] = {
    {"no-writes", kFlagNoWrites},
    {"allow-oom", kFlagAllowOom},
    {"allow-stale", kFlagAllowStale},
    {"no-cluster", kFlagNoCluster},
    {"allow-cross-slot-keys", kFlagAllowCrossSlot},
};

std::atomic<uint64_t> g_calls{0};
std::atomic<uint64_t> g_thread_rebuilds{0};
std::atomic<uint64_t> g_ro_rejections{0};

struct FunctionDef {
    std::string name;
    std::string description;
    bool        has_description = false;
    uint32_t    flags = 0;
};

struct LibraryDef {
    std::string name;
    std::string code;
    std::vector<FunctionDef> functions;   // sorted by name: FUNCTION LIST must be deterministic
    uint64_t revision = 0;               // identity changes even for REPLACE of identical source
};

// Function identifiers are ASCII case-insensitive; retain the registered spelling
// for introspection and diagnostic tags.
std::string function_key(std::string_view name) {
    std::string result(name);
    for (char& ch : result) if (ch >= 'A' && ch <= 'Z') ch += 'a' - 'A';
    return result;
}

bool valid_function_name(std::string_view name) {
    return !name.empty() && std::all_of(name.begin(), name.end(), [](unsigned char ch) {
        return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
               (ch >= '0' && ch <= '9') || ch == '_';
    });
}

constexpr const char* kNameError = "Library names can only contain letters, numbers, or "
                                  "underscores(_) and must be at least one character long";

// ---- reply helpers ---------------------------------------------------------------------------

void reply_text_error(Op& op, std::string_view kind, std::string_view detail) {
    auto sink = op.sink();
    sink.push_back('-');
    sink.append(kind.data(), kind.size());
    if (!detail.empty()) { sink.push_back(' '); sink.append(detail.data(), detail.size()); }
    sink.append("\r\n", 2);
}

void reply_err_string(Op& op, const std::string& message) {
    reply_text_error(op, "ERR", message);
}

void reply_wrong_args(Op& op, const char* sub) {
    char text[96];
    std::snprintf(text, sizeof(text), "wrong number of arguments for 'function|%s' command", sub);
    reply_text_error(op, "ERR", text);
}

void reply_bulk_string(Op& op, const std::string& value) {
    reply_bulk(op.sink(), Slice(value.data(), static_cast<uint32_t>(value.size())));
}

// ---- the process-wide library registry ---------------------------------------------------------

enum class AddResult { Ok, LibraryExists, FunctionExists, Oom };

class FunctionRegistry {
public:
    uint64_t generation() const { return generation_.load(std::memory_order_acquire); }

    // Adds one library. `replace` allows overwriting a library of the same name. Function-name
    // collisions are global across libraries, exactly as Redis defines them. On a collision
    // `detail` receives the offending library / function name.
    AddResult add(LibraryDef&& library, bool replace, std::string& detail) {
        std::lock_guard<std::mutex> lock(mu_);
        return add_locked(std::move(library), replace, detail);
    }

    bool remove(Slice name) {
        std::lock_guard<std::mutex> lock(mu_);
        const auto it = libraries_.find(std::string(name.p, name.n));
        if (it == libraries_.end()) return false;
        libraries_.erase(it);
        bump();
        return true;
    }

    void flush() {
        std::lock_guard<std::mutex> lock(mu_);
        libraries_.clear();
        ++flush_generation_;
        bump();
    }

    // Replaces the whole set atomically (FUNCTION RESTORE): either every library in `incoming`
    // lands or the registry is untouched.
    AddResult replace_all(std::vector<LibraryDef>&& incoming, bool flush_first, bool replace,
                          std::string& detail) {
        std::lock_guard<std::mutex> lock(mu_);
        std::map<std::string, LibraryDef> saved;
        try { saved = libraries_; }
        catch (const std::bad_alloc&) { return AddResult::Oom; }
        if (flush_first) libraries_.clear();
        for (LibraryDef& library : incoming) {
            const AddResult result = add_locked(std::move(library), replace, detail,
                                                /*defer_bump=*/true);
            if (result != AddResult::Ok) {
                libraries_ = std::move(saved);
                return result;
            }
        }
        bump();
        return AddResult::Ok;
    }

    // Copies every library out for a per-thread materialization pass, together with the
    // generation the copy was taken at (read under the same lock, so the stamp cannot race ahead
    // of the contents it describes).
    bool snapshot(std::vector<LibraryDef>& out, uint64_t& stamp,
                  uint64_t* flush_generation = nullptr) const {
        try {
            std::lock_guard<std::mutex> lock(mu_);
            out.clear();
            out.reserve(libraries_.size());
            for (const auto& entry : libraries_) out.push_back(entry.second);
            stamp = generation_.load(std::memory_order_relaxed);
            if (flush_generation) *flush_generation = flush_generation_;
            return true;
        } catch (const std::bad_alloc&) {
            return false;
        }
    }

    bool list(Slice library_name, bool by_name, std::vector<LibraryDef>& out) const {
        try {
            std::lock_guard<std::mutex> lock(mu_);
            out.clear();
            out.reserve(libraries_.size());
            for (const auto& entry : libraries_) {
                if (!by_name || command_glob_match(library_name,
                        Slice(entry.first.data(), entry.first.size()), true))
                    out.push_back(entry.second);
            }
            return true;
        } catch (const std::bad_alloc&) {
            return false;
        }
    }

    void counts(uint64_t& libraries, uint64_t& functions) const {
        std::lock_guard<std::mutex> lock(mu_);
        libraries = libraries_.size();
        functions = 0;
        for (const auto& entry : libraries_) functions += entry.second.functions.size();
    }

    bool writes(Slice name, bool unknown) const {
        std::lock_guard<std::mutex> lock(mu_);
        for (const auto& entry : libraries_)
            for (const FunctionDef& function : entry.second.functions)
                if (function_key(std::string_view(name.p, name.n)) == function_key(function.name))
                    return !(function.flags & kFlagNoWrites);
        return unknown;
    }

private:
    void bump() { generation_.fetch_add(1, std::memory_order_release); }

    AddResult add_locked(LibraryDef&& library, bool replace, std::string& detail,
                         bool defer_bump = false) {
        const auto existing = libraries_.find(library.name);
        if (existing != libraries_.end() && !replace) {
            detail = library.name;
            return AddResult::LibraryExists;
        }
        for (const auto& entry : libraries_) {
            if (entry.first == library.name) continue;
            for (const FunctionDef& theirs : entry.second.functions)
                for (const FunctionDef& mine : library.functions)
                    if (function_key(theirs.name) == function_key(mine.name)) {
                        detail = mine.name;
                        return AddResult::FunctionExists;
                    }
        }
        try {
            library.revision = generation_.load(std::memory_order_relaxed) + 1;
            libraries_[library.name] = std::move(library);
        } catch (const std::bad_alloc&) {
            return AddResult::Oom;
        }
        if (!defer_bump) bump();
        return AddResult::Ok;
    }

    mutable std::mutex mu_;
    std::map<std::string, LibraryDef> libraries_;
    std::atomic<uint64_t> generation_{0};
    uint64_t flush_generation_ = 0; // guarded by mu_; published with the library snapshot
};

FunctionRegistry g_functions;

// ---- the registration sandbox ------------------------------------------------------------------

struct RegisterSink {
    std::vector<FunctionDef>* defs = nullptr;   // metadata harvest (FUNCTION LOAD)
    bool store_callbacks = false;               // materialize into kRegistryFunctions
};

int fn_missing_index(lua_State* state) {
    const char* key = lua_type(state, 2) == LUA_TSTRING ? lua_tostring(state, 2) : "?";
    return luaL_error(state, "Script attempted to access nonexistent global variable '%s'", key);
}

bool field_to_string(lua_State* state, int index, std::string& out) {
    const int type = lua_type(state, index);
    if (type != LUA_TSTRING && type != LUA_TNUMBER) return false;
    size_t length = 0;
    const char* text = lua_tolstring(state, index, &length);
    out.assign(text, length);
    return true;
}

bool parse_flag_table(lua_State* state, int index, uint32_t& flags, const char*& error) {
    flags = 0;
    lua_pushnil(state);
    while (lua_next(state, index)) {
        if (lua_type(state, -1) != LUA_TSTRING) { lua_pop(state, 2); error = "unknown flag given"; return false; }
        const char* text = lua_tostring(state, -1);
        bool known = false;
        for (const FlagName& flag : kFlagNames)
            if (!std::strcmp(text, flag.name)) { flags |= flag.bit; known = true; break; }
        lua_pop(state, 1);
        if (!known) { lua_pop(state, 1); error = "unknown flag given"; return false; }
    }
    return true;
}

// redis.register_function, in both the positional and the named-argument form. Errors are raised
// as Lua errors; the caller's lua_pcall turns them into "Error registering functions: ..." with
// the exact Redis wording.
//
// They carry NO `user_function:N:` position prefix — Redis raises them from C, where luaL_error's
// luaL_where would add one — so this raises a bare string instead of calling luaL_error.
int register_error(lua_State* state, const char* message) {
    lua_pushstring(state, message);
    return lua_error(state);
}

int fn_register(lua_State* state) {
    auto* sink = static_cast<RegisterSink*>(lua_touserdata(state, lua_upvalueindex(1)));
    if (!sink || (!sink->defs && !sink->store_callbacks))
        return register_error(state, "redis.register_function can only be called on FUNCTION LOAD command");

    std::string name;
    std::string description;
    bool has_description = false;
    uint32_t flags = 0;
    int callback_index = 0;
    const int argc = lua_gettop(state);

    if (argc == 1) {
        if (!lua_istable(state, 1))
            return register_error(state, "calling redis.register_function with a single argument is "
                                     "only applicable to Lua table (representing named "
                                     "arguments).");
        // Named argument labels are case-insensitive. Normalize into a private
        // table, leaving the caller's iteration keys (including numbers) intact.
        lua_newtable(state);
        const int named = lua_gettop(state);
        lua_pushnil(state);
        while (lua_next(state, 1)) {
            if (!lua_isstring(state, -2)) {
                lua_pop(state, 2);
                return register_error(state, "named argument key given to redis.register_function is not a string");
            }
            lua_pushvalue(state, -2);
            const std::string key = function_key(lua_tostring(state, -1));
            lua_pop(state, 1);
            if (key != "function_name" && key != "callback" &&
                key != "flags" && key != "description") {
                lua_pop(state, 2);
                return register_error(state, "unknown argument given to redis.register_function");
            }
            lua_pushvalue(state, -1);
            lua_setfield(state, named, key.c_str());
            lua_pop(state, 1);
        }

        lua_getfield(state, named, "function_name");
        if (lua_isnil(state, -1))
            return register_error(state, "redis.register_function must get a function name argument");
        if (!field_to_string(state, -1, name))
            return register_error(state, "function_name argument given to redis.register_function "
                                     "must be a string");
        lua_pop(state, 1);

        lua_getfield(state, named, "callback");
        if (lua_isnil(state, -1))
            return register_error(state, "redis.register_function must get a callback argument");
        if (!lua_isfunction(state, -1))
            return register_error(state, "callback argument given to redis.register_function must be "
                                     "a function");
        callback_index = lua_gettop(state);

        lua_getfield(state, named, "flags");
        if (!lua_isnil(state, -1)) {
            if (!lua_istable(state, -1))
                return register_error(state, "flags argument to redis.register_function must be a "
                                         "table representing function flags");
            const char* flag_error = nullptr;
            if (!parse_flag_table(state, lua_gettop(state), flags, flag_error))
                return register_error(state, flag_error);
        }
        lua_pop(state, 1);

        lua_getfield(state, named, "description");
        if (!lua_isnil(state, -1)) {
            if (!field_to_string(state, -1, description))
                return register_error(state, "description argument given to redis.register_function "
                                         "must be a string");
            has_description = true;
        }
        lua_pop(state, 1);
    } else if (argc == 2) {
        if (!field_to_string(state, 1, name))
            return register_error(state, "first argument to redis.register_function must be a string");
        if (!lua_isfunction(state, 2))
            return register_error(state, "second argument to redis.register_function must be a function");
        callback_index = 2;
    } else {
        return register_error(state, "wrong number of arguments to redis.register_function");
    }

    if (!valid_function_name(name)) return register_error(state, kNameError);
    const std::string lookup = function_key(name);

    if (sink->defs) {
        for (const FunctionDef& existing : *sink->defs)
            if (existing.name == name)
                return register_error(state, "Function already exists in the library");
        FunctionDef def;
        def.name = name;
        def.description = description;
        def.has_description = has_description;
        def.flags = flags;
        sink->defs->push_back(std::move(def));
    }

    if (sink->store_callbacks) {
        lua_getfield(state, LUA_REGISTRYINDEX, kRegistryFunctions);
        lua_pushlstring(state, lookup.data(), lookup.size());
        lua_createtable(state, 0, 3);
        lua_pushlstring(state, name.data(), name.size());
        lua_setfield(state, -2, "name");
        lua_pushvalue(state, callback_index);
        lua_setfield(state, -2, "cb");
        lua_pushnumber(state, static_cast<lua_Number>(flags));
        lua_setfield(state, -2, "flags");
        lua_rawset(state, -3);
        lua_pop(state, 1);
    }
    return 0;
}

void get_global_raw(lua_State* state, const char* name) {
    lua_pushvalue(state, LUA_GLOBALSINDEX);
    lua_pushstring(state, name);
    lua_rawget(state, -2);
    lua_remove(state, -2);
}

// Compiles and runs one library body. `redis` is swapped for a registration-only table for the
// duration, so a body that calls redis.call fails with the same message Redis produces. The
// callbacks it registers resolve `redis` from _G when they later run, and therefore see the real
// table with call/pcall/setresp.
bool run_library_body(lua_State* state, Slice code, RegisterSink& sink,
                      bool& compile_failed, std::string& error) {
    compile_failed = false;
    const int base = lua_gettop(state);
    // Lua 5.1 only skips a leading '#' line in luaL_loadfile, never in luaL_loadbuffer, so the
    // shebang has to go before compilation. Blank it IN PLACE (same byte count) rather than
    // slicing it off: every line number Lua reports then matches the source the operator sent,
    // which is what makes "user_function:2:" agree with Redis.
    std::string body;
    try { body.assign(code.p, code.n); }
    catch (const std::bad_alloc&) { error = "ERR out of memory"; return false; }
    for (size_t i = 0; i < body.size() && body[i] != '\n'; i++) body[i] = ' ';
    if (luaL_loadbuffer(state, body.data(), body.size(), kFunctionChunkName) != 0) {
        size_t length = 0;
        const char* text = lua_tolstring(state, -1, &length);
        error = script_clean_error(text ? text : "compile error", text ? length : 13);
        lua_settop(state, base);
        compile_failed = true;
        return false;
    }
    const int chunk = lua_gettop(state);

    // Each library gets an environment proxy. During registration it contains
    // only redis; afterwards it resolves through the frozen runtime globals.
    // Already-created callbacks inherit this same proxy, including callbacks
    // that close over the registration table (whose permission is revoked).
    lua_newtable(state);
    const int environment = lua_gettop(state);
    auto* registration = new (lua_newuserdata(state, sizeof(RegisterSink))) RegisterSink(sink);
    const int registration_index = lua_gettop(state);
    lua_newtable(state);
    lua_pushvalue(state, registration_index);
    lua_pushcclosure(state, fn_register, 1);
    lua_setfield(state, -2, "register_function");
    get_global_raw(state, "redis");
    for (const char* field : {"log", "LOG_DEBUG", "LOG_VERBOSE", "LOG_NOTICE", "LOG_WARNING",
                              "REDIS_VERSION", "REDIS_VERSION_NUM"}) {
        lua_getfield(state, -1, field);
        lua_setfield(state, -3, field);
    }
    lua_pop(state, 1);
    lua_createtable(state, 0, 1);
    lua_pushcfunction(state, fn_missing_index);
    lua_setfield(state, -2, "__index");
    lua_enablereadonlytable(state, -1, 1);
    lua_setmetatable(state, -2);
    lua_enablereadonlytable(state, -1, 1);
    lua_setfield(state, environment, "redis");
    lua_newtable(state);
    const int environment_meta = lua_gettop(state);
    lua_pushcfunction(state, fn_missing_index);
    lua_setfield(state, environment_meta, "__index");
    lua_pushvalue(state, environment_meta);
    lua_setmetatable(state, environment);
    lua_enablereadonlytable(state, environment_meta, 1);
    lua_enablereadonlytable(state, environment, 1);
    lua_pushvalue(state, environment);
    lua_setfenv(state, chunk);
    lua_pushvalue(state, chunk);
    const int status = script_pcall_library(state);
    *registration = RegisterSink{};
    lua_enablereadonlytable(state, environment, 0);
    lua_pushnil(state);
    lua_setfield(state, environment, "redis");
    lua_enablereadonlytable(state, environment, 1);
    lua_enablereadonlytable(state, environment_meta, 0);
    lua_pushvalue(state, LUA_GLOBALSINDEX);
    lua_setfield(state, environment_meta, "__index");
    lua_enablereadonlytable(state, environment_meta, 1);

    if (status != 0) {
        size_t length = 0;
        std::string message;
        if (lua_istable(state, -1)) {
            lua_pushliteral(state, "err");
            lua_rawget(state, -2);
            if (lua_isstring(state, -1)) {
                const char* text = lua_tolstring(state, -1, &length);
                message = script_clean_error(text, length);
            }
            lua_pop(state, 1);
        }
        if (message.empty()) {
            const char* text = lua_tolstring(state, -1, &length);
            message = "ERR " + script_clean_error(text ? text : "runtime error",
                                                  text ? length : 13);
        }
        error = message;
        lua_settop(state, base);
        return false;
    }
    lua_settop(state, base);
    return true;
}

// ---- shebang parsing ----------------------------------------------------------------------------

bool parse_library_header(Slice source, std::string& engine, std::string& name,
                          std::string& error) {
    if (source.n < 2 || source.p[0] != '#' || source.p[1] != '!') {
        error = "Missing library metadata";
        return false;
    }
    uint32_t end = 0;
    while (end < source.n && source.p[end] && source.p[end] != '\n') end++;
    if (end == source.n || source.p[end] != '\n') {
        error = "Invalid library metadata";
        return false;
    }
    const std::string header(source.p, end);
    std::vector<std::string> fields;
    if (!cfg_split_args(header.c_str(), fields) || fields.empty()) {
        error = "Invalid library metadata";
        return false;
    }
    engine = fields[0].substr(2);
    bool named = false;
    for (size_t i = 1; i < fields.size(); ++i) {
        const auto& field = fields[i];
        if (field.size() >= 5 && Slice(field.data(), 5).eq_icase("name=")) {
            if (named) {
                error = "Invalid metadata value, name argument was given multiple times";
                return false;
            }
            name = field.substr(5);
            named = true;
        } else {
            error = "Invalid metadata value given: " + script_clean_error(field.c_str(), std::strlen(field.c_str()));
            return false;
        }
    }
    if (!named) { error = "Library name was not given"; return false; }
    if (!valid_function_name(name)) { error = kNameError; return false; }
    if (function_key(engine) != "lua") {
        error = "Engine '" + script_clean_error(engine.data(), engine.size()) + "' not found";
        return false;
    }
    return true;
}

// Validates one library source off the executor threads and harvests its registration metadata.
bool compile_library(Slice source, LibraryDef& library, std::string& error) {
    if (source.n > kLibraryMaxBytes) {
        error = "library payload exceeds the 1 MiB limit";
        return false;
    }
    std::string engine;
    if (!parse_library_header(source, engine, library.name, error)) return false;

    lua_State* state = script_new_sandbox_state();
    if (!state) { error = "out of memory"; return false; }
    RegisterSink sink;
    sink.defs = &library.functions;
    bool compile_failed = false;
    std::string body_error;
    const bool ok = run_library_body(state, source, sink, compile_failed, body_error);
    lua_close(state);
    if (!ok) {
        error = compile_failed ? "Error compiling function: " + body_error
                               : "Error registering functions: " + body_error;
        return false;
    }
    if (library.functions.empty()) { error = "No functions registered"; return false; }
    std::sort(library.functions.begin(), library.functions.end(),
              [](const FunctionDef& a, const FunctionDef& b) { return a.name < b.name; });
    try {
        library.code.assign(source.p, source.n);
    } catch (const std::bad_alloc&) {
        error = "out of memory";
        return false;
    }
    return true;
}

// ---- per-thread materialization ------------------------------------------------------------------

// Registry stamps are opaque eight-byte strings, not Lua doubles: revisions must remain exact
// beyond 2^53. They never cross the wire or escape to Lua code.
void push_revision(lua_State* state, uint64_t revision) {
    lua_pushlstring(state, reinterpret_cast<const char*>(&revision), sizeof(revision));
}

bool matches_revision(lua_State* state, int index, uint64_t revision) {
    if (lua_type(state, index) != LUA_TSTRING) return false;
    size_t length = 0;
    const char* bytes = lua_tolstring(state, index, &length);
    return length == sizeof(revision) && !std::memcmp(bytes, &revision, sizeof(revision));
}

// Publish a new name/revision index after a registry mutation, retaining callbacks for every
// unchanged library. Stage the entire index so a failed materialization cannot destroy existing
// closure state. SCRIPT FLUSH only drops EVAL chunks and never invalidates these registry roots.
bool function_thread_sync(lua_State* state, std::string& error) {
    const uint64_t current = g_functions.generation();
    lua_getfield(state, LUA_REGISTRYINDEX, kRegistryGeneration);
    const bool synced = matches_revision(state, -1, current);
    lua_pop(state, 1);
    if (synced) return true;

    std::vector<LibraryDef> libraries;
    uint64_t stamp = 0, flush_generation = 0;
    if (!g_functions.snapshot(libraries, stamp, &flush_generation)) { error = "out of memory"; return false; }

    const int base = lua_gettop(state);
    lua_getfield(state, LUA_REGISTRYINDEX, kRegistryFunctions);
    const int previous_functions = lua_gettop(state);
    lua_getfield(state, LUA_REGISTRYINDEX, kRegistryRevisions);
    const int previous_revisions = lua_gettop(state);
    lua_newtable(state);
    const int functions = lua_gettop(state);
    lua_pushvalue(state, functions);
    lua_setfield(state, LUA_REGISTRYINDEX, kRegistryFunctions);
    lua_newtable(state);
    const int revisions = lua_gettop(state);
    RegisterSink sink;
    sink.store_callbacks = true;
    for (const LibraryDef& library : libraries) {
        bool reuse = false;
        if (lua_istable(state, previous_revisions)) {
            lua_pushlstring(state, library.name.data(), library.name.size());
            lua_rawget(state, previous_revisions);
            reuse = matches_revision(state, -1, library.revision);
            lua_pop(state, 1);
        }
        if (reuse) {
            for (const FunctionDef& fn : library.functions) {
                lua_pushlstring(state, fn.name.data(), fn.name.size());
                lua_pushvalue(state, -1);
                lua_rawget(state, previous_functions);
                lua_rawset(state, functions);
            }
        } else {
            bool compile_failed = false;
            std::string body_error;
            const Slice code(library.code.data(), static_cast<uint32_t>(library.code.size()));
            if (!run_library_body(state, code, sink, compile_failed, body_error)) {
                error = "Error materializing library " + library.name + ": " + body_error;
                lua_pushvalue(state, previous_functions);
                lua_setfield(state, LUA_REGISTRYINDEX, kRegistryFunctions);
                lua_settop(state, base);
                return false;
            }
        }
        lua_pushlstring(state, library.name.data(), library.name.size());
        push_revision(state, library.revision);
        lua_rawset(state, revisions);
    }
    lua_pushvalue(state, revisions);
    lua_setfield(state, LUA_REGISTRYINDEX, kRegistryRevisions);
    push_revision(state, stamp);
    lua_setfield(state, LUA_REGISTRYINDEX, kRegistryGeneration);
    script_sync_function_helpers(state, flush_generation);
    lua_settop(state, base);
    g_thread_rebuilds.fetch_add(1, std::memory_order_relaxed);
    return true;
}

// ---- FCALL --------------------------------------------------------------------------------------

template <bool kNotify, bool kReadonly, typename Prepare>
bool invoke_fcall(Shard& shard, Op& op, Prepare&& prepare) {
    uint32_t key_first = 0, key_count = 0;
    if (!command_script_key_range(op, key_first, key_count)) {
        reply_text_error(op, "ERR", "invalid function key declaration");
        return true;
    }
    lua_State* state = script_thread_state();
    if (!state) { reply_text_error(op, "ERR", "out of memory"); return true; }
    std::string error;
    if (!function_thread_sync(state, error)) { reply_err_string(op, error); return true; }

    const Slice name = op.arg(1);
    const std::string lookup = function_key(std::string_view(name.p, name.n));
    lua_getfield(state, LUA_REGISTRYINDEX, kRegistryFunctions);
    lua_pushlstring(state, lookup.data(), lookup.size());
    lua_rawget(state, -2);
    if (!lua_istable(state, -1)) {
        lua_settop(state, 0);
        reply_text_error(op, "ERR", "Function not found");
        return true;
    }
    lua_getfield(state, -1, "name");
    size_t registered_length = 0;
    const char* registered_name = lua_tolstring(state, -1, &registered_length);
    const std::string registered(registered_name, registered_length);
    lua_pop(state, 1);
    lua_getfield(state, -1, "flags");
    const uint32_t flags = static_cast<uint32_t>(lua_tonumber(state, -1));
    lua_pop(state, 1);
    lua_getfield(state, -1, "cb");
    lua_replace(state, -3);      // callback takes the function-table slot
    lua_pop(state, 1);           // drop the entry table; the callback is now on top

    // A library can be replaced between IO admission and owner execution. Check
    // the selected callback's flags again before an AOF-error admission takes effect.
    if (__builtin_expect(shard.server() && shard.server()->aof().failed(), false) &&
        !(flags & kFlagNoWrites)) {
        lua_settop(state, 0);
        shard.server()->aof().reply_write_error(op);
        return true;
    }

    if (!(flags & (kFlagAllowOom | kFlagNoWrites)) &&
        !FunctionMemoryScope::admit(shard, key_count ? op.arg(key_first) : Slice{})) {
        lua_settop(state, 0);
        reply_maxmemory_oom(op);
        return true;
    }

    if (kReadonly && !(flags & kFlagNoWrites)) {
        lua_settop(state, 0);
        g_ro_rejections.fetch_add(1, std::memory_order_relaxed);
        reply_text_error(op, "ERR",
                         "Can not execute a script with write flag using *_ro command.");
        return true;
    }

    auto invoke = [&] {
        ScriptInvocation call;
        call.key_first = key_first;
        call.key_count = key_count;
        call.style = ScriptArgStyle::Params;
        // no-writes makes the function read-only for EVERY caller, not only FCALL_RO (Redis 7).
        call.readonly = kReadonly || (flags & kFlagNoWrites) != 0;
        call.notify = kNotify;
        call.chunk = "user_function";
        call.tag = Slice(registered.data(), registered.size());
        g_calls.fetch_add(1, std::memory_order_relaxed);
        script_execute(shard, op, call);
    };
    if constexpr (std::is_same_v<Prepare, std::nullptr_t>) {
        invoke();
    } else {
        // EXEC must prepare its private version under the same admission that
        // governs the callback. Keep this lookup/callback pair intact: a second
        // lookup could see different flags after a concurrent library update.
        FunctionMemoryScope memory_scope(shard.store(), true);
        if (!prepare()) { lua_settop(state, 0); return false; }
        invoke();
    }
    return true;
}

template <bool kNotify, bool kReadonly>
void cmd_fcall(Shard& shard, Op& op) {
    (void)invoke_fcall<kNotify, kReadonly>(shard, op, nullptr);
}

// ---- FUNCTION -------------------------------------------------------------------------------------

void reply_function_entry(Op& op, const LibraryDef& library, bool with_code) {
    const bool resp3 = op.resp3();
    reply_map_header(op.sink(), with_code ? 4 : 3, resp3);
    reply_bulk(op.sink(), Slice("library_name", 12));
    reply_bulk_string(op, library.name);
    reply_bulk(op.sink(), Slice("engine", 6));
    reply_bulk(op.sink(), Slice("LUA", 3));
    reply_bulk(op.sink(), Slice("functions", 9));
    reply_array_header(op.sink(), library.functions.size());
    for (const FunctionDef& fn : library.functions) {
        reply_map_header(op.sink(), 3, resp3);
        reply_bulk(op.sink(), Slice("name", 4));
        reply_bulk_string(op, fn.name);
        reply_bulk(op.sink(), Slice("description", 11));
        if (fn.has_description) reply_bulk_string(op, fn.description);
        else reply_null(op.sink(), resp3);
        reply_bulk(op.sink(), Slice("flags", 5));
        uint32_t count = 0;
        for (const FlagName& flag : kFlagNames) if (fn.flags & flag.bit) count++;
        reply_set_header(op.sink(), count, resp3);
        for (const FlagName& flag : kFlagNames)
            if (fn.flags & flag.bit) reply_simple(op.sink(), flag.name);
    }
    if (with_code) {
        reply_bulk(op.sink(), Slice("library_code", 12));
        reply_bulk_string(op, library.code);
    }
}

void function_list(Op& op) {
    Slice library_name;
    bool by_name = false;
    bool with_code = false;
    for (uint32_t i = 2; i < op.argc(); i++) {
        if (!with_code && op.arg(i).eq_icase("withcode")) { with_code = true; continue; }
        if (!by_name && op.arg(i).eq_icase("libraryname")) {
            if (i + 1 >= op.argc()) {
                reply_text_error(op, "ERR", "library name argument was not given");
                return;
            }
            library_name = op.arg(++i);
            by_name = true;
            continue;
        }
        char text[128];
        std::snprintf(text, sizeof(text), "Unknown argument %.*s",
                      static_cast<int>(std::min<uint32_t>(op.arg(i).n, 64)), op.arg(i).p);
        reply_err_string(op, script_clean_error(text, std::strlen(text)));
        return;
    }
    std::vector<LibraryDef> libraries;
    if (!g_functions.list(library_name, by_name, libraries)) {
        reply_text_error(op, "ERR", "out of memory");
        return;
    }
    reply_array_header(op.sink(), libraries.size());
    for (const LibraryDef& library : libraries) reply_function_entry(op, library, with_code);
}

void reply_function_stats(Op& op) {
    uint64_t libraries = 0, functions = 0;
    g_functions.counts(libraries, functions);
    const bool resp3 = op.resp3();
    reply_map_header(op.sink(), 2, resp3);
    reply_bulk(op.sink(), Slice("running_script", 14));
    reply_null(op.sink(), resp3);
    reply_bulk(op.sink(), Slice("engines", 7));
    reply_map_header(op.sink(), 1, resp3);
    reply_bulk(op.sink(), Slice("LUA", 3));
    reply_map_header(op.sink(), 2, resp3);
    reply_bulk(op.sink(), Slice("libraries_count", 15));
    reply_int(op.sink(), static_cast<long long>(libraries));
    reply_bulk(op.sink(), Slice("functions_count", 15));
    reply_int(op.sink(), static_cast<long long>(functions));
}

// ---- DUMP / RESTORE -------------------------------------------------------------------------------
// OUR OWN FRAME, not Redis's RDB-function payload: magic, version, one length-prefixed source blob
// per library, FNV-1a-64 trailer. Cross-server interchange with Redis is explicitly out of scope
// (documented); the round trip that matters is ours to ours, and rebuilding from source means a
// restored library is validated by the same path a LOAD takes.

void put_u32(std::string& out, uint32_t value) {
    uint8_t bytes[4];
    snapshot_put_u32(bytes, value);
    out.append(reinterpret_cast<const char*>(bytes), 4);
}

void function_dump(Op& op) {
    std::vector<LibraryDef> libraries;
    uint64_t stamp = 0;
    if (!g_functions.snapshot(libraries, stamp)) {
        reply_text_error(op, "ERR", "out of memory");
        return;
    }
    std::string payload(kDumpMagic, sizeof(kDumpMagic));
    put_u32(payload, static_cast<uint32_t>(libraries.size()));
    for (const LibraryDef& library : libraries) {
        put_u32(payload, static_cast<uint32_t>(library.code.size()));
        payload.append(library.code);
    }
    const uint64_t checksum = snapshot_checksum(
        reinterpret_cast<const uint8_t*>(payload.data()), payload.size());
    uint8_t trailer[8];
    snapshot_put_u64(trailer, checksum);
    payload.append(reinterpret_cast<const char*>(trailer), 8);
    reply_bulk_string(op, payload);
}

bool decode_dump(Slice payload, std::vector<std::string>& sources) {
    if (payload.n < sizeof(kDumpMagic) + 4 + 8) return false;
    if (std::memcmp(payload.p, kDumpMagic, sizeof(kDumpMagic)) != 0) return false;
    const auto* bytes = reinterpret_cast<const uint8_t*>(payload.p);
    const uint64_t stored = snapshot_get_u64(bytes + payload.n - 8);
    if (snapshot_checksum(bytes, payload.n - 8) != stored) return false;
    uint32_t pos = sizeof(kDumpMagic);
    const uint32_t count = snapshot_get_u32(bytes + pos);
    pos += 4;
    // Every source needs at least its four-byte length. Bound reserve by this frame's bytes,
    // not a library-count ceiling absent from LOAD/DUMP, and reject impossible counts before
    // allocating. Every structurally valid dump this server emits remains restorable.
    if (count > (payload.n - 8 - pos) / 4) return false;
    try {
        sources.clear();
        sources.reserve(count);
        for (uint32_t i = 0; i < count; i++) {
            if (payload.n - 8 - pos < 4) return false;
            const uint32_t length = snapshot_get_u32(bytes + pos);
            pos += 4;
            if (length > payload.n - 8 - pos) return false;
            sources.emplace_back(payload.p + pos, length);
            pos += length;
        }
    } catch (const std::bad_alloc&) {
        return false;
    }
    return pos == payload.n - 8;
}

void function_restore(Op& op) {
    bool flush_first = false;
    bool replace = false;
    if (op.argc() == 4) {
        if (op.arg(3).eq_icase("flush")) flush_first = true;
        else if (op.arg(3).eq_icase("replace")) replace = true;
        else if (!op.arg(3).eq_icase("append")) {
            reply_text_error(op, "ERR", "Wrong restore policy given, value should be either "
                                        "FLUSH, APPEND or REPLACE.");
            return;
        }
    }
    std::vector<std::string> sources;
    if (!decode_dump(op.arg(2), sources)) {
        reply_text_error(op, "ERR", "DUMP payload version or checksum are wrong");
        return;
    }
    std::vector<LibraryDef> incoming;
    for (const std::string& source : sources) {
        LibraryDef library;
        std::string error;
        if (!compile_library(Slice(source.data(), static_cast<uint32_t>(source.size())),
                             library, error)) {
            reply_err_string(op, error);
            return;
        }
        incoming.push_back(std::move(library));
    }
    std::string detail;
    switch (g_functions.replace_all(std::move(incoming), flush_first, replace, detail)) {
        case AddResult::Ok: reply_ok(op.sink()); return;
        // Redis quotes the library name for LOAD and leaves it bare for RESTORE. Both shapes are
        // reproduced here rather than unified.
        case AddResult::LibraryExists:
            reply_err_string(op, "Library " + detail + " already exists"); return;
        case AddResult::FunctionExists:
            reply_err_string(op, "Function " + detail + " already exists"); return;
        case AddResult::Oom:
            reply_text_error(op, "ERR", "out of memory"); return;
    }
}

// Our own wording: the subcommand set is ours and the Redis help block is source we do not copy.
void reply_function_help(Op& op) {
    static constexpr const char* lines[] = {
        "FUNCTION <subcommand> [<arg> [value] [opt] ...]. Subcommands are:",
        "LOAD [REPLACE] <library code>",
        "    Register a library from source whose first line is `#!lua name=<library>`.",
        "DELETE <library name>",
        "    Drop one library and every function it registered.",
        "LIST [LIBRARYNAME <name>] [WITHCODE]",
        "    Report libraries, their functions, descriptions and flags; WITHCODE adds sources.",
        "STATS",
        "    Report the running script (always nil here) and per-engine library/function counts.",
        "KILL",
        "    Terminate the running function. Functions are bounded by an instruction limit and",
        "    always terminate on their own, so this reports NOTBUSY.",
        "FLUSH [ASYNC|SYNC]",
        "    Drop every library. Both modes are synchronous here.",
        "DUMP",
        "    Serialize every library into a self-describing payload (TomoKV's own frame).",
        "RESTORE <payload> [FLUSH|APPEND|REPLACE]",
        "    Reload libraries from a payload produced by FUNCTION DUMP on this server.",
        "HELP",
        "    Print this help.",
    };
    reply_array_header(op.sink(), sizeof(lines) / sizeof(lines[0]));
    for (const char* line : lines) reply_simple(op.sink(), line);
}

void cmd_function(Shard&, Op& op) {
    const Slice subcommand = op.arg(1);
    if (subcommand.eq_icase("load")) {
        if (op.argc() < 3) { reply_wrong_args(op, "load"); return; }
        bool replace = false;
        uint32_t code_arg = 2;
        for (; code_arg + 1 < op.argc(); ++code_arg) {
            if (!op.arg(code_arg).eq_icase("replace")) {
                const Slice option = op.arg(code_arg);
                reply_err_string(op, "Unknown option given: " +
                    script_clean_error(option.p, option.n));
                return;
            }
            replace = true;
        }
        LibraryDef library;
        std::string error;
        if (!compile_library(op.arg(code_arg), library, error)) {
            reply_err_string(op, error);
            return;
        }
        const std::string name = library.name;
        std::string detail;
        switch (g_functions.add(std::move(library), replace, detail)) {
            case AddResult::Ok: reply_bulk_string(op, name); return;
            case AddResult::LibraryExists:
                reply_err_string(op, "Library '" + detail + "' already exists"); return;
            case AddResult::FunctionExists:
                reply_err_string(op, "Function " + detail + " already exists"); return;
            case AddResult::Oom:
                reply_text_error(op, "ERR", "out of memory"); return;
        }
        return;
    }
    if (subcommand.eq_icase("delete")) {
        if (op.argc() != 3) { reply_wrong_args(op, "delete"); return; }
        if (!g_functions.remove(op.arg(2))) {
            reply_text_error(op, "ERR", "Library not found");
            return;
        }
        reply_ok(op.sink());
        return;
    }
    if (subcommand.eq_icase("flush")) {
        if (op.argc() > 3) { reply_err_string(op, "unknown subcommand or wrong number of arguments for '" +
            script_clean_error(subcommand.p, subcommand.n) + "'. Try FUNCTION HELP."); return; }
        if (op.argc() == 3 &&
            !(op.arg(2).eq_icase("sync") || op.arg(2).eq_icase("async"))) {
            reply_text_error(op, "ERR", "FUNCTION FLUSH only supports SYNC|ASYNC option");
            return;
        }
        g_functions.flush();
        reply_ok(op.sink());
        return;
    }
    if (subcommand.eq_icase("list")) { function_list(op); return; }
    if (subcommand.eq_icase("stats")) {
        if (op.argc() != 2) { reply_wrong_args(op, "stats"); return; }
        reply_function_stats(op);
        return;
    }
    if (subcommand.eq_icase("dump")) {
        if (op.argc() != 2) { reply_wrong_args(op, "dump"); return; }
        function_dump(op);
        return;
    }
    if (subcommand.eq_icase("restore")) {
        if (op.argc() > 4) { reply_err_string(op, "unknown subcommand or wrong number of arguments for '" +
            script_clean_error(subcommand.p, subcommand.n) + "'. Try FUNCTION HELP."); return; }
        if (op.argc() < 3) { reply_wrong_args(op, "restore"); return; }
        function_restore(op);
        return;
    }
    if (subcommand.eq_icase("kill")) {
        if (op.argc() != 2) { reply_wrong_args(op, "kill"); return; }
        reply_text_error(op, "NOTBUSY", "No scripts in execution right now.");
        return;
    }
    if (subcommand.eq_icase("help")) {
        if (op.argc() != 2) { reply_wrong_args(op, "help"); return; }
        reply_function_help(op);
        return;
    }
    command_reply_subcommand_error(op, "FUNCTION");
}

static const CommandSpec kTable[] = {
    // name       min max flags                                       handler      first last step
    {"FCALL",      3, -1, CmdFlags::Write | CmdFlags::CursorShard | CmdFlags::ScriptRoute |
                              CmdFlags::MultiShard,
                cmd_fcall<false, false>, 3, -1, 1, notify_handler<cmd_fcall<true, false>>},
    {"FCALL_RO",   3, -1, CmdFlags::Readonly | CmdFlags::CursorShard | CmdFlags::ScriptRoute |
                              CmdFlags::MultiShard,
                cmd_fcall<false, true>, 3, -1, 1, notify_handler<cmd_fcall<true, true>>},
    {"FUNCTION",   2, -1, CmdFlags::ConnLocal | CmdFlags::OrderedLocal | CmdFlags::Admin,
                cmd_function,  0,  0, 0},
};

}  // namespace

FunctionStats function_stats() {
    FunctionStats stats;
    g_functions.counts(stats.libraries, stats.functions);
    stats.generation = g_functions.generation();
    stats.calls = g_calls.load(std::memory_order_relaxed);
    stats.thread_rebuilds = g_thread_rebuilds.load(std::memory_order_relaxed);
    stats.ro_rejections = g_ro_rejections.load(std::memory_order_relaxed);
    return stats;
}

bool function_is_fcall(const Op& op) {
    return op.spec && std::strncmp(op.spec->name, "FCALL", 5) == 0;
}

bool function_metadata_write(const Op& op) {
    const bool fallback = op.spec && (op.spec->flags & CmdFlags::Write);
    return op.argc() > 1 ? g_functions.writes(op.arg(1), fallback) : fallback;
}

bool function_execute_exec(Shard& shard, Op& op, void* context,
                           bool (*prepare)(void*)) {
    auto before_callback = [&] { return prepare(context); };
    const bool notify = (op.spec->flags & CmdFlags::NotifySelected) != 0;
    const bool readonly = op.cmd_name().eq_icase("fcall_ro");
    if (readonly) return notify
        ? invoke_fcall<true, true>(shard, op, before_callback)
        : invoke_fcall<false, true>(shard, op, before_callback);
    return notify
        ? invoke_fcall<true, false>(shard, op, before_callback)
        : invoke_fcall<false, false>(shard, op, before_callback);
}

CommandTable functions_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
