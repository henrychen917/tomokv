// command.h — the command table.
//
// A command is data, not a class. The dispatch path does one lookup and one indirect call; adding a
// type later means adding rows, not changing the machinery. Handlers write RESP straight into
// op.reply, so nothing here knows what a value is.
//
// KEY POSITION IS METADATA, not a parse-time discovery. The IO thread must know which arguments are
// keys BEFORE it can route, because routing happens before execution. v1 covers only single-key
// commands (first_key == 1); the multi-key forms need the key range so a command can be split
// across shards and reassembled, which is why the fields exist now rather than being added later.
#pragma once
#include <cstddef>
#include <cstdint>
#include "../base/slice.h"

namespace tomo {

class Shard;
class Op;

struct CmdFlags {
    static constexpr uint32_t Write     = 1u << 0;   // mutates the keyspace
    static constexpr uint32_t Readonly  = 1u << 1;
    static constexpr uint32_t Admin     = 1u << 2;
    static constexpr uint32_t ConnLocal = 1u << 3;   // answered on the IO thread; never dispatched
    static constexpr uint32_t AllShards = 1u << 4;   // one public op, one owner task per shard
    static constexpr uint32_t RandomShard = 1u << 5; // keyless op routed by the IO thread's PRNG
    static constexpr uint32_t CursorShard = 1u << 6; // shard id is encoded in argv[1]'s cursor
    static constexpr uint32_t ConfigRoute = 1u << 7; // GET is IO-local; SET fans out as control work
    // Growth commands, gated by the pre-execution maxmemory check (redis DENYOOM): if the shard is
    // over budget and eviction cannot bring it under, the command is refused with the exact OOM
    // reply BEFORE its handler runs. DEL/expiry/read commands stay ungated so an over-budget shard
    // can always be drained.
    static constexpr uint32_t DenyOom = 1u << 8;
    static constexpr uint32_t MultiShard = 1u << 9;  // command-specific scatter/gather lowering
    // Logically read-only command with a physical value update that needs snapshot pre-image
    // capture. PFCOUNT uses this for Redis's cached-cardinality bytes; it remains reported as
    // readonly and is not maxmemory admission gated.
    static constexpr uint32_t SnapshotWrite = 1u << 10;
    // EVAL/EVALSHA discover their declared KEYS range from argv[2]. Validation and routing happen
    // on IO; the resulting ordinary task executes the interpreter on exactly one shard owner.
    static constexpr uint32_t ScriptRoute = 1u << 11;
    static constexpr uint32_t PubSub = 1u << 12;       // IO-owned async command; never touches a shard
    // A blocking collection command is lowered before ordinary scatter routing.  Its issued ROB
    // slot is also a connection parse barrier until an owner supplies data or a timeout reply.
    static constexpr uint32_t Blocking = 1u << 13;
    static constexpr uint32_t Transaction = 1u << 14; // MULTI/EXEC/WATCH controls, IO-owned
};

using CmdHandler = void (*)(Shard&, Op&);

struct CommandSpec {
    const char* name;
    // Inclusive counts, including the command itself. max_arity == -1 means unbounded. Keeping both
    // bounds in the row avoids type handlers growing their own subtly different arity parsers.
    int32_t     min_arity;
    int32_t     max_arity;
    uint32_t    flags;
    CmdHandler  handler;

    // Key range within argv: [first_key, last_key] stepping by key_step.
    // last_key == -1 means "to the end of argv" (MGET, DEL, ...).
    int16_t     first_key;
    int16_t     last_key;
    int16_t     key_step;

    // Dense boot-assigned id. Family tables leave this zero; commands.cc copies their rows into
    // registry-owned storage and assigns the final value before any server thread starts.
    uint16_t    id = 0;
};

struct CommandTable {
    const CommandSpec* specs;
    size_t             size;
};

// Every family owns its table; the registry calls every type table plus the server/admin table.
CommandTable string_command_table();
CommandTable hash_command_table();
CommandTable list_command_table();
CommandTable set_command_table();
CommandTable zset_command_table();
CommandTable server_command_table();
CommandTable scripting_command_table();

// Built once before threads start. Lookup hashes the uppercase-normalized bytes into an open-
// addressed table; the load factor is capped at 1/2 so ordinary command names land in one probe.
bool command_registry_init();
const CommandSpec* command_lookup(Slice name);
bool command_arity_ok(const CommandSpec& spec, uint32_t argc);
uint32_t command_registry_size();
const CommandSpec* command_registry_at(uint32_t id);

class Server;
class Client;
class ThreadCtx;
struct Op;
void reply_maxmemory_oom(Op& op);  // defined in t_string.cc, tomo:: linkage
// Lets the connection-local admin commands read published per-shard counters.
void command_bind_server(Server* s);

// ConnLocal handlers retain the small, uniform CmdHandler ABI. IO binds this thread-local context
// only around the synchronous handler call; executors never see a Client or a socket.
void command_set_local_context(Client* client, ThreadCtx* thread);

// CLIENT LIST metadata is kept out of Client so its 1984-byte footprint remains locked.
void command_client_connected(Client* client, const char* addr);
void command_client_disconnected(Client* client);
void command_client_set_shard_subscriptions(Client* client, uint32_t count);

// The IO-side pub/sub matcher shares the Redis-compatible glob implementation used by SCAN.
bool command_glob_match(Slice pattern, Slice text);

// Special routing helpers. Validation writes a complete error reply into op on failure.
bool command_prepare_scan_route(Server& server, Op& op);
bool command_validate_all_shards(Op& op);
bool command_config_routes_all_shards(Op& op);
bool command_validate_config_set(Op& op);
bool command_prepare_script_route(Server& server, Op& op);
bool command_script_key_range(const Op& op, uint32_t& first, uint32_t& count);
void scripting_bind_server(Server* server);

// Registry placeholder for commands whose implementation is the multi-shard lowering itself.
// Reaching it as an ordinary single-shard handler is an internal routing error.
void cmd_xshard_only(Shard& shard, Op& op);

}  // namespace tomo
