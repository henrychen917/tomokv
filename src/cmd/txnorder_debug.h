#pragma once
// Opt-in correctness build only. Production has no registry, allocation,
// locking or retirement instruction for this falsifier.
#ifdef TOMO_TXNORDER_DEBUG
#include <cstdio>
#include <cstdlib>
#include <mutex>
#include <unordered_map>
namespace tomo {
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
#endif
