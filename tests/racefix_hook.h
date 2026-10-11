// Test-only SV4.10 schedule. Included only in the copied witness source tree.
#pragma once
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <thread>
#include <sys/syscall.h>
#include <unistd.h>
#include "src/exec/op.h"
#include "src/net/resp.h"

namespace tomo::racefix_test {
inline std::atomic<long> chosen_tid{0};
inline std::atomic<uint32_t> chosen_worker{UINT32_MAX};
// 0 idle, 1 armed, 2 parked holding zero, 3 stale store completed, 4 suppressed.
inline std::atomic<uint32_t> stage{0}, captured{UINT32_MAX};
inline std::atomic<bool> released{false}, suppress{false};
inline std::atomic<uint64_t> serial{0}, parked_at{0}, other_arm_at{0}, final_at{0};

inline bool before_store(uint32_t armed) {
    if (armed || syscall(SYS_gettid) != chosen_tid.load(std::memory_order_acquire) ||
        stage.load(std::memory_order_acquire) != 1) return false;
    captured.store(armed, std::memory_order_relaxed);
    parked_at.store(serial.fetch_add(1) + 1, std::memory_order_relaxed);
    stage.store(2, std::memory_order_release);
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
    while (!released.load(std::memory_order_acquire)) {
        if (std::chrono::steady_clock::now() >= deadline) std::_Exit(89);
        std::this_thread::yield();
    }
    if (suppress.load(std::memory_order_relaxed)) {
        final_at.store(serial.fetch_add(1) + 1, std::memory_order_relaxed);
        stage.store(4, std::memory_order_release);
        return true;  // Negative control: omit only this chosen stale store.
    }
    return false;
}

inline void after_store(uint32_t armed) {
    const auto order = serial.fetch_add(1) + 1;
    if (armed && stage.load(std::memory_order_acquire) == 2)
        other_arm_at.store(order, std::memory_order_release);
    if (!armed && syscall(SYS_gettid) == chosen_tid.load(std::memory_order_acquire) &&
        stage.load(std::memory_order_acquire) == 2) {
        final_at.store(order, std::memory_order_relaxed);
        stage.store(3, std::memory_order_release);
    }
}

template<class Server>
inline void command(Server& server, uint32_t worker, Op& op) {
    auto sink = op.sink();
    if (op.argc() == 4 && op.arg(2).eq_icase("arm") &&
        (op.arg(3).eq_icase("store") || op.arg(3).eq_icase("suppress"))) {
        if (stage.load(std::memory_order_acquire) != 0) {
            reply_err(sink, "ERR hook requires a fresh server");
            return;
        }
        chosen_worker.store(worker, std::memory_order_relaxed);
        suppress.store(op.arg(3).eq_icase("suppress"), std::memory_order_relaxed);
        chosen_tid.store(syscall(SYS_gettid), std::memory_order_release);
        stage.store(1, std::memory_order_release);
        reply_ok(sink);
    } else if (op.argc() == 3 && op.arg(2).eq_icase("release")) {
        // This control edge must never refresh the production armed word.
        released.store(true, std::memory_order_release);
        reply_ok(sink);
    } else if (op.argc() == 3 && op.arg(2).eq_icase("status")) {
        const auto state = stage.load(std::memory_order_acquire);
        reply_array_header(sink, 9);
        reply_int(sink, state);
        reply_int(sink, captured.load(std::memory_order_relaxed));
        reply_int(sink, chosen_worker.load(std::memory_order_relaxed));
        reply_int(sink, parked_at.load(std::memory_order_relaxed));
        reply_int(sink, other_arm_at.load(std::memory_order_acquire));
        reply_int(sink, final_at.load(std::memory_order_relaxed));
        reply_int(sink, server.climon_monitors());
        reply_int(sink, server.climon_armed());
        reply_int(sink, chosen_tid.load(std::memory_order_relaxed));
    } else {
        reply_err(sink, "ERR racefix-climon requires arm store|suppress, status or release");
    }
}
}  // namespace tomo::racefix_test
