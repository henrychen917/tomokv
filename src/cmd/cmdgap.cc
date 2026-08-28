// cmdgap.cc — small, local commands found by the live Redis 7.4 COMMAND inventory.
//
// ASKING/READONLY/READWRITE are cluster connection controls. In a standalone Redis server they
// all return the same cluster-disabled error, so they remain entirely IO-local here and do not
// introduce cluster state. RESTORE-ASKING only bypasses cluster slot checks; with no cluster
// layer, its complete behavior is the existing RESTORE owner handler.
#include "command.h"
#include "serialize.h"
#include "../exec/op.h"
#include "../net/resp.h"

namespace tomo {
namespace {

void cmd_cluster_disabled(Shard&, Op& op) {
    reply_err(op.sink(), "ERR This instance has cluster support disabled");
}

static const CommandSpec kTable[] = {
    // name             min max flags                                      handler
    //                                                               first last step notify
    {"ASKING",           1,  1, CmdFlags::ConnLocal,                       cmd_cluster_disabled, 0, 0, 0},
    {"READONLY",         1,  1, CmdFlags::ConnLocal,                       cmd_cluster_disabled, 0, 0, 0},
    {"READWRITE",        1,  1, CmdFlags::ConnLocal,                       cmd_cluster_disabled, 0, 0, 0},
    {"RESTORE-ASKING",   4, -1, CmdFlags::Write | CmdFlags::DenyOom,
                                                        cmd_restore, 1, 1, 1, cmd_restore_notify},
};

}  // namespace

CommandTable cmdgap_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
