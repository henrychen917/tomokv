// Shared metadata extraction for restricted ACL users; no ordinary dispatch code.
#include "acl.h"
#include "command.h"
#include "cmdmeta.h"
#include "../exec/op.h"
#include <new>

namespace tomo {

bool acl_pattern_allowed(const AclSelector& perm, Slice value) {
    for (const std::string& pattern : perm.key_patterns)
        if (command_glob_match(Slice(pattern.data(), static_cast<uint32_t>(pattern.size())), value))
            return true;
    return false;
}

__attribute__((noinline)) AclDeniedReason acl_check_metadata_keys(
    const AclSelector& perm, const CommandSpec& spec, uint32_t argc,
    const void* argument_context, Slice (*argument_at)(const void*, uint32_t),
    uint32_t* denied_arg) {
    // Use precisely the same subcommand resolution and rich key specs as COMMAND GETKEYS.
    // Legacy routing ranges cannot describe timeouts, key counts, or keyless HELP arms.
    // This scratch view borrows argument bytes; it exists only for restricted ACL users.
    Op arguments;
    arguments.spec = &spec;
    for (uint32_t arg = 0; arg < argc; ++arg)
        if (!arguments.push_arg(argument_at(argument_context, arg))) return AclDeniedReason::Key;
    const auto* metadata = command_metadata_resolve(arguments, 0);
    // Unknown/malformed subcommands are rejected by their command parser, as before.
    if (!metadata) return AclDeniedReason::None;
    std::vector<CommandKeyMetadata> keys;
    try {
        command_metadata_collect_keys(arguments, 0, *metadata, keys);
    } catch (const std::bad_alloc&) {
        return AclDeniedReason::Key;  // Never admit unchecked keys on allocation failure.
    }
    for (const auto& key : keys)
        if (!acl_pattern_allowed(perm, argument_at(argument_context, key.argument))) {
            if (denied_arg) *denied_arg = key.argument;
            return AclDeniedReason::Key;
        }
    return AclDeniedReason::None;
}
}  // namespace tomo
