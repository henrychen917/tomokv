// cmdmeta.h -- cold Redis command/subcommand introspection metadata.
//
// CommandSpec is the dispatch row and must stay compact.  This side table is built once at boot
// and is touched only by COMMAND/ACL introspection and COMMAND GETKEYS*.  Pipe-qualified
// subcommands live here without becoming executable top-level dispatch names.
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

#include "../base/slice.h"

namespace tomo {

class Op;
struct CommandSpec;
struct CommandMetadata;

struct CommandKeyMetadata {
    uint32_t argument = 0;
    uint16_t flags = 0;
};

enum class CommandMetadataKeysResult : uint8_t {
    Success,
    InvalidArguments,
    NoKeyArguments,
};

// Allocate the dense top-level command-id index. The generated immutable metadata itself is
// static storage; this vector is the only startup allocation added by the feature.
bool command_metadata_init(const CommandSpec* specs, size_t count);

const CommandMetadata* command_metadata_for(const CommandSpec& spec);
const CommandMetadata* command_metadata_lookup(Slice name);
const CommandMetadata* command_metadata_resolve(Op& op, uint32_t command_argument);
uint32_t command_metadata_size();
const CommandMetadata* command_metadata_at(uint32_t index);

Slice command_metadata_name(const CommandMetadata& metadata);
int16_t command_metadata_arity(const CommandMetadata& metadata);
uint64_t command_metadata_categories(const CommandMetadata& metadata);
bool command_metadata_is_subcommand(const CommandMetadata& metadata);
bool command_metadata_arity_ok(const CommandMetadata& metadata, uint32_t argc);

// Append one complete 10-field COMMAND INFO row, including rich flags, ACL categories, tips,
// key specifications, and nested subcommands. A null metadata pointer appends protocol-native
// null. This is intentionally out of line in the cold feature translation unit.
void command_metadata_reply_info(Op& op, const CommandMetadata* metadata);

// Extract keys and their Redis key-spec intent. `command_argument` identifies the full command's
// name within op.argv (2 for COMMAND GETKEYS*). The returned argument indexes address op.argv.
CommandMetadataKeysResult command_metadata_collect_keys(
    Op& op, uint32_t command_argument, const CommandMetadata& metadata,
    std::vector<CommandKeyMetadata>& keys);

uint32_t command_metadata_key_flag_count();
const char* command_metadata_key_flag_name(uint32_t index);

}  // namespace tomo
