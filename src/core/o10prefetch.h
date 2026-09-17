// O10: issue storage hints during the existing armed parser's key walks.
#pragma once
#include "config.h"
#include "../store/flatstore.h"

namespace tomo {

// One decision per parse pass. O1 uses the same fused parser for overlap 0 and 1;
// its old private-queue template is no longer a live selector. Split-local's coarse
// parser also has fused reader capability, so check actual placement here.
// Keep this predicate patchable without moving any text for the kind-A control.
__attribute__((noipa)) inline bool o10_prefetch_enabled(ThreadMode mode, bool overlap) {
    return mode == ThreadMode::Fused && overlap;
}

#ifdef TOMO_O10_PREFETCH_TEST
void o10_prefetch_test_issue(uintptr_t address);
#endif

// Only the read-local-armed parser calls this: topology words have atomic
// publication and the IO tenure already participates in rotation QSBR. Plain
// owner-only prefetch() would race resize on foreign shards. No slot or record
// is loaded, and no pointer survives this hint. Sampling base and mask separately
// can combine two resize generations; integer address arithmetic avoids an
// out-of-bounds C++ pointer expression, and the x86 read-prefetch cannot fault.
// A stale hint can be wasted. It grants no read/write admission and adds no
// sequence check, reader retry, allocation, or per-operation scheduling state.
inline void FlatStore::prefetch_from_io(uint64_t hash) const {
    const uint32_t home = static_cast<uint32_t>(mix64(hash));
    for (int table = 0; table < 2; table++) {
        const uintptr_t base = reinterpret_cast<uintptr_t>(
            __atomic_load_n(&tab_[table], __ATOMIC_ACQUIRE));
        if (!base) continue;
        const uint32_t mask = __atomic_load_n(&mask_[table], __ATOMIC_ACQUIRE);
        const uintptr_t address = base + static_cast<uintptr_t>(home & mask) * sizeof(uint64_t);
        __builtin_prefetch(reinterpret_cast<const void*>(address), 0, 1);
#ifdef TOMO_O10_PREFETCH_TEST
        o10_prefetch_test_issue(address);
#endif
    }
}

} // namespace tomo
