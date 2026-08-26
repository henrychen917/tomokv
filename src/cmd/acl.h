// acl.h -- ACL data model and narrow single-TU entry points. Bodies live in acl.inc.
#pragma once

#include <array>
#include <atomic>
#include <cstdint>
#include <string>
#include <vector>

namespace tomo {

class Client;
class IoLoop;
class Shard;
class Op;
class Server;
struct CommandSpec;
struct Config;
struct LoopSignals;
struct MultiQueuedCommand;
struct Slice;

inline constexpr uint32_t kAclDefaultUser = 0;
inline constexpr uint32_t kAclCommandWords = 4;
inline constexpr uint32_t kAclFutureCommandBit = 255;

enum AclPermFlags : uint32_t {
    AclAllKeys = 1u << 0,
    AclAllCommands = 1u << 1,
    AclAllChannels = 1u << 2,
};

enum AclUserFlags : uint32_t {
    AclUserEnabled = 1u << 0,
    AclUserDisabled = 1u << 1,
    AclUserNoPass = 1u << 2,
    AclUserSanitize = 1u << 3,
    AclUserSkipSanitize = 1u << 4,
};

struct AclPerm {
    uint64_t allowed_commands[kAclCommandWords] = {};
    uint32_t flags = 0;
    std::vector<std::string> key_patterns;
    std::vector<std::string> channel_patterns;
    std::vector<std::string> command_rules;
};

struct AclUser {
    std::string name;
    std::atomic<const AclPerm*> perm{nullptr};
    std::vector<std::array<uint64_t, 4>> passwords;
    uint32_t flags = AclUserDisabled;
    uint32_t index = 0;
};

enum class AclDeniedReason : uint8_t { None, Command, Key, Channel };

bool acl_initialize(Server& server, const Config& config, std::string& error);
void acl_update_default_requirepass(Server& server, Slice password);
bool acl_authenticate(Slice username, Slice password, uint32_t& user_index);
bool acl_default_nopass();
const char* acl_username(uint32_t user_index);
void acl_set_pubsub_default(bool allchannels);

// One guarded Wave-A/ACL dispatch call above subscriber-mode handling. True means a complete reply
// was published locally. `unauthenticated` and `acl_active` are bits from one per-pass latch.
bool acl_dispatch_entry(IoLoop& loop, Client& client, Op& op, uint32_t consumed,
                        bool unauthenticated, bool acl_active);
void acl_command_entry(IoLoop& loop, Client& client, Op& op);
void acl_broadcast_user_change(IoLoop& loop, uint32_t user_index,
                               const AclPerm* permissions, bool deleted);

bool acl_pubsub_channel_entry(Client& client, Op& op, bool pattern, LoopSignals& signals);
AclDeniedReason acl_check_queued(uint32_t user_index, const MultiQueuedCommand& command);
void acl_recheck_blocking(Client& client, Op& op, LoopSignals& signals);

void cmd_acl(Shard& shard, Op& op);

}  // namespace tomo
