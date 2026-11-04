// DEBUG SLEEP: a process-wide pause at IO/executor pass boundaries. No per-command gate.
#pragma once
#include <algorithm>
#include <atomic>
#include <bitset>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <mutex>

namespace tomo {

class Client;
class Op;
class Server;
class Shard;

template <unsigned Workers, unsigned WaitMs> class DebugSleepCoordinator {
    using Clock = std::chrono::steady_clock;
    using Lock = std::unique_lock<std::mutex>;
public:
    // Cold configuration rendezvous. Reuses the already-present pass-boundary
    // pending check, so ordinary commands acquire no new branch or load.
    // The callback runs on each physical issuer after every worker has parked.
    // No callback may depend on normal command execution during this interval.
    // `announce` runs on the caller right after the request is published: members reach their
    // pass-boundary check only when they run, so it must ring the parked ones.
    bool exclusive(unsigned origin, unsigned participants, void* context, void (*action)(void*, unsigned),
                   void (*announce)(void*, unsigned) = nullptr, void* announce_context = nullptr) {
        Lock lock(mutex_);
        if (pending() || origin >= Workers || !workers_.test(origin) ||
            workers_.count() != participants) return false;
        Control control{this, context, action, {}, {}, {}};
        Control* empty = nullptr;
        if (!control_.compare_exchange_strong(empty, &control)) return false;
        control.members = workers_;
        ++generation_;
        arrived_.reset();
        deadline_ = Clock::now() + std::chrono::seconds(5);
        interrupted_.store(false, std::memory_order_relaxed);
        pending_.store(true, std::memory_order_release);
        if (announce) announce(announce_context, origin);
        control_park(lock, origin, control);
        while ((control.departed & arrived_) != arrived_) changed_.wait(lock);
        control_.store(nullptr, std::memory_order_release);
        return control.started;
    }
    // Role changes leave/re-enter this membership before touching their next pass.
    class Worker {
    public:
        Worker(DebugSleepCoordinator& pause, unsigned tid) : pause_(pause), tid_(tid) {
            Lock lock(pause_.mutex_);
            pause_.workers_.set(tid_);
        }
        ~Worker() {
            Lock lock(pause_.mutex_);
            pause_.workers_.reset(tid_);
            pause_.arrived_.reset(tid_);
            pause_.changed_.notify_all();
        }
    private:
        DebugSleepCoordinator& pause_;
        unsigned tid_;
    };

    bool pending() const { return pending_.load(std::memory_order_acquire); }
    void interrupt() { interrupted_.store(true, std::memory_order_relaxed); }

    // Zero means another sleep owns the rendezvous: the caller retains its unconsumed request.
    uint64_t start(uint64_t us) {
        Lock lock(mutex_);
        if (pending()) return 0;
        if (Control* control = control_.load(std::memory_order_acquire);
                control && control->owner == this) return 0;
        duration_ = std::chrono::microseconds(us);
        arrived_.reset();
        ++generation_;
        const uint64_t ticket = ++ticket_;
        phase_ = Phase::Collect;
        deadline_ = Clock::now() + kCollectWindow;
        unmanaged_ = workers_.none();
        if (unmanaged_) { phase_ = Phase::Sleep; deadline_ = sleep_deadline(Clock::now()); }
        interrupted_.store(false, std::memory_order_relaxed);
        pending_.store(true, std::memory_order_release);
        return ticket;
    }

    bool complete(uint64_t ticket) {
        if (completed_.load(std::memory_order_acquire) >= ticket) return true;
        // In-memory command fixtures have no live loop members. The same deadline applies;
        // completion remains deferred, without inventing phantom workers to acknowledge it.
        Lock lock(mutex_);
        if (unmanaged_ && Clock::now() >= deadline_) finish();
        return completed_.load(std::memory_order_acquire) >= ticket;
    }

    __attribute__((noinline)) void park(unsigned tid) {
        Lock lock(mutex_);
        if (!pending()) return;
        if (Control* control = control_.load(std::memory_order_acquire);
                control && control->owner == this) {
            control_park(lock, tid, *control);
            return;
        }
        if (phase_ == Phase::Retry) {
            if (Clock::now() < deadline_) return;
            phase_ = Phase::Collect;
            arrived_.reset();
            deadline_ = Clock::now() + kCollectWindow;
        }
        const uint64_t generation = generation_;
        arrived_.set(tid);
        changed_.notify_all();
        while (pending() && generation == generation_) {
            if (interrupted_.load(std::memory_order_relaxed)) { finish(); break; }
            const auto now = Clock::now();
            if (phase_ == Phase::Collect && (arrived_ & workers_) == workers_) {
                phase_ = Phase::Sleep;
                deadline_ = sleep_deadline(now); // duration begins only after every worker stops
                changed_.notify_all();
            }
            if (now >= deadline_) {
                if (phase_ == Phase::Sleep) finish();
                else {
                    // An in-progress synchronous admin operation may need another worker's
                    // maintenance. Release this attempt so those dependencies can complete;
                    // retain the request and retry on fresh pass boundaries. Never time out OK.
                    phase_ = Phase::Retry;
                    deadline_ = now + kRetryWindow;
                    ++generation_;
                    arrived_.reset();
                    changed_.notify_all();
                }
                break;
            }
            changed_.wait_until(lock, std::min(deadline_, now + kSignalPoll));
        }
    }

private:
    struct Control {
        DebugSleepCoordinator* owner;
        void* context;
        void (*action)(void*, unsigned);
        std::bitset<Workers> completed, departed, members;
        bool started = false;
    };
    inline static std::atomic<Control*> control_{nullptr};
    void control_park(Lock& lock, unsigned tid, Control& control) {
        arrived_.set(tid);
        changed_.notify_all();
        while (pending() && !control.started) {
            if ((arrived_ & control.members) == control.members) {
                control.started = true;
                changed_.notify_all();
                break;
            }
            if (interrupted_.load(std::memory_order_relaxed) || Clock::now() >= deadline_) {
                // Nothing has run: failure releases every parked worker and
                // leaves the caller's prepared resources available to unwind.
                pending_.store(false, std::memory_order_release);
                changed_.notify_all();
                break;
            }
            changed_.wait_until(lock, std::min(deadline_, Clock::now() + kSignalPoll));
        }
        if (!control.started) {
            control.departed.set(tid); changed_.notify_all(); return;
        }
        lock.unlock();
        control.action(control.context, tid);
        lock.lock();
        control.completed.set(tid);
        if ((control.completed & control.members) == control.members) {
            pending_.store(false, std::memory_order_release);
            changed_.notify_all();
        }
        while (pending()) changed_.wait(lock);
        control.departed.set(tid);
        changed_.notify_all();
    }
    enum class Phase { Collect, Sleep, Retry };
    // These bound coordination and signal observation, never the requested sleep duration.
    static constexpr auto kCollectWindow = std::chrono::milliseconds(2 * WaitMs);
    static constexpr auto kRetryWindow = std::chrono::milliseconds(WaitMs);
    static constexpr auto kSignalPoll = kRetryWindow;
    Clock::time_point sleep_deadline(Clock::time_point now) const {
        const auto room = std::chrono::duration_cast<std::chrono::microseconds>(Clock::time_point::max() - now);
        return duration_ >= room ? Clock::time_point::max() : now + duration_;
    }
    void finish() {
        completed_.store(ticket_, std::memory_order_release);
        pending_.store(false, std::memory_order_release);
        ++generation_;
        arrived_.reset();
        changed_.notify_all();
    }
    std::atomic<bool> pending_{false}, interrupted_{false};
    std::atomic<uint64_t> completed_{0};
    std::mutex mutex_;
    std::condition_variable changed_;
    std::bitset<Workers> workers_, arrived_;
    uint64_t ticket_ = 0, generation_ = 0;
    bool unmanaged_ = false;
    Phase phase_ = Phase::Collect;
    Clock::time_point deadline_{};
    std::chrono::microseconds duration_{};
};

enum class DebugSleepResult : uint8_t { NotSleep, Handled, Deferred };

// Returns NotSleep for every DEBUG form except exact `DEBUG SLEEP seconds`. Handled means the
// helper wrote an immediate reply (permission/zero); Deferred returns a positive delay in us,
// truncated to microseconds just as Redis 7.4's strtod -> long long -> nanosleep path does.
DebugSleepResult debug_sleep_prepare(Server& server, Client& client, Op& op,
                                     uint64_t& delay_us);

// Keep the EXEC-only coordination out of the ordinary scatter-gather translation unit.
bool debug_sleep_exec(Server& server, Shard& shard, std::atomic<long long>& state,
                      uint32_t owner_thread_id);

}  // namespace tomo
