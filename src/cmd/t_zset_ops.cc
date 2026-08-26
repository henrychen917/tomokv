// t_zset_ops.cc -- registry ownership for sorted-set multi-key operations.
//
// Execution is lowered by xshard.cc even when every key maps to one owner. This keeps one parser
// and one image/merge implementation for local and cross-shard forms.
#include "command.h"

namespace tomo {
namespace {

static const CommandSpec kTable[] = {
    {"ZUNION",      3, -1, CmdFlags::Readonly | CmdFlags::MultiShard,
                     cmd_xshard_only, 2, -1, 1},
    {"ZINTER",      3, -1, CmdFlags::Readonly | CmdFlags::MultiShard,
                     cmd_xshard_only, 2, -1, 1},
    {"ZDIFF",       3, -1, CmdFlags::Readonly | CmdFlags::MultiShard,
                     cmd_xshard_only, 2, -1, 1},
    {"ZUNIONSTORE", 4, -1, CmdFlags::Write | CmdFlags::DenyOom | CmdFlags::MultiShard,
                     cmd_xshard_only, 1, -1, 1},
    {"ZINTERSTORE", 4, -1, CmdFlags::Write | CmdFlags::DenyOom | CmdFlags::MultiShard,
                     cmd_xshard_only, 1, -1, 1},
    {"ZDIFFSTORE",  4, -1, CmdFlags::Write | CmdFlags::DenyOom | CmdFlags::MultiShard,
                     cmd_xshard_only, 1, -1, 1},
    {"ZINTERCARD",  3, -1, CmdFlags::Readonly | CmdFlags::MultiShard,
                     cmd_xshard_only, 2, -1, 1},
};

}  // namespace

CommandTable zset_ops_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
