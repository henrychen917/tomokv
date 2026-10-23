// Process-wide shutdown doorbell: a save request wake, then a sticky terminal wake.
//
// eventfd accepts only an eight-byte counter write.  A signal contributes one logical event by
// writing uint64_t{1}. Only the elected save owner consumes a nonterminal request before doing
// the save, including a publisher's late write after a failed request ended. A separate terminal
// latch restores any stop edge caught by that drain, so all workers still observe shutdown.
#pragma once

#include <atomic>
#include <cerrno>
#include <climits>
#include <csignal>
#include <cstdint>
#include <poll.h>
#include <sys/eventfd.h>
#include <unistd.h>

namespace tomo {

inline volatile sig_atomic_t g_signal_doorbell_fd = -1;
inline std::atomic<bool> g_signal_doorbell_terminal{false};
static_assert(std::atomic<bool>::is_always_lock_free);

class SignalDoorbell {
public:
    SignalDoorbell() = default;
    SignalDoorbell(const SignalDoorbell&) = delete;
    SignalDoorbell& operator=(const SignalDoorbell&) = delete;

    ~SignalDoorbell() {
        if (fd_ < 0) return;
        if (g_signal_doorbell_fd == fd_) g_signal_doorbell_fd = -1;
        ::close(fd_);
    }

    bool init() {
        if (fd_ >= 0) return false;
        fd_ = ::eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC);
        if (fd_ < 0) return false;
        g_signal_doorbell_terminal.store(false, std::memory_order_relaxed);
        g_signal_doorbell_fd = fd_;
        return true;
    }

    int fd() const { return fd_; }

private:
    int fd_ = -1;
};

inline int signal_doorbell_fd() {
    return static_cast<int>(g_signal_doorbell_fd);
}

inline void signal_doorbell_request_notify() {
    const int saved_errno = errno;
    const int fd = signal_doorbell_fd();
    if (fd >= 0) {
        const uint64_t one = 1;
        ssize_t result;
        do {
            result = ::write(fd, &one, sizeof(one));
        } while (result < 0 && errno == EINTR);
        // EAGAIN means the sticky counter is already saturated/readable, which is success for a
        // terminal notification. Other failures cannot be reported safely from a signal handler.
    }
    errno = saved_errno;
}

inline void signal_doorbell_notify() {
    g_signal_doorbell_terminal.store(true, std::memory_order_release);
    signal_doorbell_request_notify();
}

inline void signal_doorbell_consume_request() {
    const int fd = signal_doorbell_fd();
    if (fd < 0) return;
    uint64_t count;
    while (::read(fd, &count, sizeof(count)) == static_cast<ssize_t>(sizeof(count))) {}
    // A terminal publisher before/during the drain is restored. A publisher after this load
    // supplies its own write, closing the other side of the race without consuming a stop.
    if (g_signal_doorbell_terminal.load(std::memory_order_acquire))
        signal_doorbell_request_notify();
}

// Wait without consuming the sticky event. Every worker ring and the main controller therefore
// observe the same terminal edge independently. The clamp avoids poll(2)'s signed timeout wrap
// for a deliberately huge configured controller interval.
inline bool signal_doorbell_wait(uint32_t timeout_ms) {
    const int fd = signal_doorbell_fd();
    pollfd event{fd, POLLIN, 0};
    const int timeout = timeout_ms > static_cast<uint32_t>(INT_MAX)
                            ? INT_MAX
                            : static_cast<int>(timeout_ms);
    int result;
    do {
        result = ::poll(fd >= 0 ? &event : nullptr, fd >= 0 ? 1 : 0, timeout);
    } while (result < 0 && errno == EINTR);
    return result > 0;
}

}  // namespace tomo
