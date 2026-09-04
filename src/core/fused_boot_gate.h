// One boot-only rendezvous for the fused runtime.
//
// The gate's public phase is monotonic: Loaded -> Ready -> Running (or Stopping).  Per-worker
// state makes every arrival and gave-up edge once-only, so a stop racing either rendezvous cannot
// leave main waiting for a counter that the worker will never increment.
#pragma once

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdlib>
#include <mutex>
#include <string>
#include <vector>

namespace tomo {

class FusedBootGate {
public:
    enum class Phase : uint8_t { Loaded, Ready, Running, Stopping };

    explicit FusedBootGate(uint32_t workers)
        : workers_(workers), worker_state_(workers, WorkerState::Loading) {}

    bool arrive_loaded(uint32_t tid, bool ok, const std::string& error) {
        std::lock_guard<std::mutex> lock(mu_);
        check_tid(tid);
        if (worker_state_[tid] != WorkerState::Loading) std::abort();
        loaded_++;
        if (ok && phase_ != Phase::Stopping) {
            worker_state_[tid] = WorkerState::Loaded;
        } else {
            mark_gave_up_locked(tid);
            if (!ok) fail_locked(error.empty() ? "unified thread initialization failed" : error);
        }
        cv_.notify_all();
        return worker_state_[tid] == WorkerState::Loaded;
    }

    bool wait_until_ready(uint32_t tid, const std::atomic<bool>& stop) {
        std::unique_lock<std::mutex> lock(mu_);
        check_tid(tid);
        if (worker_state_[tid] != WorkerState::Loaded) std::abort();
        if (!wait_for_phase_locked(lock, Phase::Ready, stop)) {
            mark_gave_up_locked(tid);
            cv_.notify_all();
            return false;
        }
        return true;
    }

    bool arrive_ready(uint32_t tid) {
        std::lock_guard<std::mutex> lock(mu_);
        check_tid(tid);
        if (worker_state_[tid] != WorkerState::Loaded) std::abort();
        // A worker can leave wait_until_ready(), spend time arming its listeners, and return after
        // main has observed a signal and moved the gate to Stopping. That is an ordinary stop edge,
        // not an impossible transition.
        if (phase_ == Phase::Stopping) {
            mark_gave_up_locked(tid);
            cv_.notify_all();
            return false;
        }
        if (phase_ != Phase::Ready) std::abort();
        worker_state_[tid] = WorkerState::Ready;
        ready_++;
        cv_.notify_all();
        return true;
    }

    bool wait_until_running(uint32_t tid, const std::atomic<bool>& stop) {
        std::unique_lock<std::mutex> lock(mu_);
        check_tid(tid);
        if (worker_state_[tid] != WorkerState::Ready) std::abort();
        if (!wait_for_phase_locked(lock, Phase::Running, stop)) {
            mark_gave_up_locked(tid);
            cv_.notify_all();
            return false;
        }
        worker_state_[tid] = WorkerState::Running;
        return true;
    }

    void give_up(uint32_t tid, const std::string& error) {
        std::lock_guard<std::mutex> lock(mu_);
        check_tid(tid);
        mark_gave_up_locked(tid);
        fail_locked(error);
        cv_.notify_all();
    }

    bool wait_loaded(const std::atomic<bool>& stop) {
        std::unique_lock<std::mutex> lock(mu_);
        wait_main_locked(lock, [&] { return loaded_ == workers_; }, stop);
        return loaded_ == workers_ && !failed_ && phase_ != Phase::Stopping &&
               !stop.load(std::memory_order_relaxed);
    }

    bool advance_ready(const std::atomic<bool>& stop) {
        std::lock_guard<std::mutex> lock(mu_);
        if (stop.load(std::memory_order_relaxed)) {
            phase_ = Phase::Stopping;
            cv_.notify_all();
            return false;
        }
        if (phase_ != Phase::Loaded || loaded_ != workers_ || failed_) return false;
        phase_ = Phase::Ready;
        cv_.notify_all();
        return true;
    }

    bool wait_ready(const std::atomic<bool>& stop) {
        std::unique_lock<std::mutex> lock(mu_);
        wait_main_locked(lock, [&] { return ready_ + gave_up_ == workers_; }, stop);
        return ready_ == workers_ && !failed_ && phase_ == Phase::Ready &&
               !stop.load(std::memory_order_relaxed);
    }

    bool advance_running(const std::atomic<bool>& stop) {
        std::lock_guard<std::mutex> lock(mu_);
        if (stop.load(std::memory_order_relaxed)) {
            phase_ = Phase::Stopping;
            cv_.notify_all();
            return false;
        }
        if (phase_ != Phase::Ready || ready_ != workers_ || failed_) return false;
        phase_ = Phase::Running;
        cv_.notify_all();
        return true;
    }

    void stop() {
        std::lock_guard<std::mutex> lock(mu_);
        phase_ = Phase::Stopping;
        cv_.notify_all();
    }

    uint32_t gave_up() const {
        std::lock_guard<std::mutex> lock(mu_);
        return gave_up_;
    }

    std::string error() const {
        std::lock_guard<std::mutex> lock(mu_);
        return error_;
    }

private:
    enum class WorkerState : uint8_t { Loading, Loaded, Ready, Running, GaveUp };

    static constexpr auto kStopPoll = std::chrono::milliseconds(10);

    void check_tid(uint32_t tid) const {
        if (tid >= workers_) std::abort();
    }

    void mark_gave_up_locked(uint32_t tid) {
        if (worker_state_[tid] == WorkerState::GaveUp ||
            worker_state_[tid] == WorkerState::Running) return;
        worker_state_[tid] = WorkerState::GaveUp;
        gave_up_++;
    }

    void fail_locked(const std::string& error) {
        failed_ = true;
        if (error_.empty()) error_ = error.empty() ? "unified boot failed" : error;
    }

    bool wait_for_phase_locked(std::unique_lock<std::mutex>& lock, Phase target,
                               const std::atomic<bool>& stop) {
        while (phase_ != Phase::Stopping &&
               static_cast<uint8_t>(phase_) < static_cast<uint8_t>(target) &&
               !stop.load(std::memory_order_relaxed)) {
            cv_.wait_for(lock, kStopPoll);
        }
        return phase_ != Phase::Stopping && !stop.load(std::memory_order_relaxed) &&
               static_cast<uint8_t>(phase_) >= static_cast<uint8_t>(target);
    }

    template <typename Predicate>
    void wait_main_locked(std::unique_lock<std::mutex>& lock, Predicate done,
                          const std::atomic<bool>& stop) {
        while (!done() && phase_ != Phase::Stopping &&
               !stop.load(std::memory_order_relaxed)) {
            cv_.wait_for(lock, kStopPoll);
        }
    }

    const uint32_t workers_;
    mutable std::mutex mu_;
    std::condition_variable cv_;
    std::vector<WorkerState> worker_state_;
    Phase phase_ = Phase::Loaded;
    uint32_t loaded_ = 0;
    uint32_t ready_ = 0;
    uint32_t gave_up_ = 0;
    bool failed_ = false;
    std::string error_;
};

}  // namespace tomo
