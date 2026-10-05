// Published monitoring statistics. All producer work runs on the shard owner;
// INFO/DBSIZE readers load atomics once, without locks, retries or key walks.
#include "../core/server.h"

namespace tomo {

// Cold routing only. A kind-A copied-ELF control returns false here to restore
// PRE's census routes with exactly the candidate's text size and addresses.
__attribute__((noipa)) bool storesize_published_route() { return true; }

void FlatStore::destroy_storesize() { delete storesize_state(); }

bool FlatStore::init_storesize() {
    auto* state = new (std::nothrow) StoreSizeState;
    std::memcpy(reader_owner_gap_ + 4, &state, sizeof(state));
    return state != nullptr;
}

uint64_t FlatStore::published_avg_deadline() const {
    const auto* storesize_ = storesize_state();
    return storesize_ ? storesize_->avg_deadline.load(std::memory_order_relaxed) : 0;
}

} // namespace tomo
