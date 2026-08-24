#include "command.h"
#include "../snapshot/format.h"
#include <array>

namespace tomo {
namespace {
SnapshotHookStatus unsupported_begin(const KvObj&, SnapshotSaveCursor&, uint8_t&) {
    // TODO(type-set): serialize Compact and expanded hashtable members logically.
    return SnapshotHookStatus::Unsupported;
}
SnapshotHookStatus unsupported_read(SnapshotSaveCursor&, uint8_t*, size_t, size_t& n) {
    n = 0; return SnapshotHookStatus::Unsupported;
}
SnapshotHookStatus unsupported_load(Slice, uint8_t, int64_t, Slice, KvObj*& result) {
    result = nullptr; return SnapshotHookStatus::Unsupported;
}
}  // namespace
SnapshotTypeHooks set_snapshot_hooks() {
    return {unsupported_begin, unsupported_read, unsupported_load};
}
CommandTable set_command_table() {
    static const std::array<CommandSpec, 0> kTable{};
    return {kTable.data(), kTable.size()};
}
}  // namespace tomo
