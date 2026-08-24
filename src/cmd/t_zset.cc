#include "command.h"
#include <array>

namespace tomo {
CommandTable zset_command_table() {
    static const std::array<CommandSpec, 0> kTable{};
    return {kTable.data(), kTable.size()};
}
}  // namespace tomo
