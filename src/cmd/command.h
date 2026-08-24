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
};

struct CommandTable {
    const CommandSpec* specs;
    size_t             size;
};

// Every family owns its table; the registry calls all five even while four are empty foundations.
CommandTable string_command_table();
CommandTable hash_command_table();
CommandTable list_command_table();
CommandTable set_command_table();
CommandTable zset_command_table();

// Built once before threads start. Lookup hashes the uppercase-normalized bytes into an open-
// addressed table; the load factor is capped at 1/2 so ordinary command names land in one probe.
bool command_registry_init();
const CommandSpec* command_lookup(Slice name);
bool command_arity_ok(const CommandSpec& spec, uint32_t argc);

class Server;
// Lets the connection-local admin commands read published per-shard counters.
void command_bind_server(Server* s);

}  // namespace tomo
