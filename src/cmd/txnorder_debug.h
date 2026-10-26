#pragma once
// Opt-in correctness build only. Production has no registry, allocation,
// locking or retirement instruction for this falsifier.
#ifdef TOMO_TXNORDER_DEBUG
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <unordered_map>
namespace tomo {
// Counts actual registry-entry examinations, including failed comparisons.
// Read deltas divided by completed EXECs; absent from release builds and INFO.
inline std::atomic<uint64_t> registry_visits{0};
#define TOMO_TXN_REGISTRY_VISIT() (::tomo::registry_visits.fetch_add(1, std::memory_order_relaxed))
struct TxnWriterDebug {
    std::mutex mutex;
    std::unordered_map<const void*, unsigned> marks;
};
inline TxnWriterDebug& txn_writer_debug() {
    static TxnWriterDebug state;
    return state;
}
inline void txn_debug_writer_mark(const void* token, int delta) {
    auto& state = txn_writer_debug();
    std::lock_guard guard(state.mutex);
    if (delta > 0) state.marks[token] += static_cast<unsigned>(delta);
    else {
        auto it = state.marks.find(token);
        if (it == state.marks.end() || it->second < static_cast<unsigned>(-delta)) std::abort();
        it->second -= static_cast<unsigned>(-delta);
        if (!it->second) state.marks.erase(it);
    }
}
inline void txn_debug_writer_retire(const void* token) {
    auto& state = txn_writer_debug();
    std::lock_guard guard(state.mutex);
    if (state.marks.contains(token)) {
        std::fputs("txnorder: writer marks leaked at op retirement\n", stderr);
        std::abort();
    }
}
} // namespace tomo
#else
#define TOMO_TXN_REGISTRY_VISIT() ((void)0)
#endif
