// server_tail.h — the introspection tail: OBJECT/MEMORY plus the CONFIG and COMMAND subcommands
// that the compatibility surface was still missing.
//
// Only the pieces t_server.cc has to call are declared here. Everything else is file-local: this
// translation unit is cold by construction and nothing in it may appear on the GET/SET path.
#pragma once
#include <cstdint>
#include "../base/slice.h"

namespace tomo {

class Op;
class Shard;
struct CommandSpec;

enum class WaitCommandResult : uint8_t { Error, Immediate, Unsatisfied };

// Validate WAIT's integer surface.  Unsatisfied means this standalone, replica-less server must
// defer the reply for timeout_ms (zero means forever); MULTI calls the ordinary handler and turns
// the same result into its required immediate integer element.
WaitCommandResult server_tail_prepare_wait(Op& op, uint64_t& timeout_ms);

// CONFIG subcommands owned by this file. Each returns false when `op` names a subcommand it does
// not handle, leaving the caller's own dispatch (GET/SET) and error reply untouched.
bool server_tail_config_subcommand(Op& op);

// COMMAND subcommands owned by this file: LIST / GETKEYS / GETKEYSANDFLAGS / HELP.
bool server_tail_command_subcommand(Op& op);

// Shared with t_server.cc's CONFIG SET fan-out decision.
bool server_tail_config_routes_all_shards(Op& op);
// Executed on every shard owner for CONFIG RESETSTAT.
void server_tail_config_resetstat_owner(Shard& shard);

// The redis-name encoding of one stored object, e.g. "listpack" / "intset" / "embstr".
const char* server_tail_encoding_name(const void* object);

}  // namespace tomo
