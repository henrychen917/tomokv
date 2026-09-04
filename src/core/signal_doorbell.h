// Process-wide sticky shutdown doorbell.
//
// eventfd accepts only an eight-byte counter write.  A signal contributes one logical event by
// writing uint64_t{1}; workers deliberately never drain the shared fd, so readiness remains true
// until every independently registered ring/epoll waiter has observed shutdown.
#pragma once

#include <cerrno>
#include <csignal>
#include <cstdint>
#include <sys/eventfd.h>
#include <unistd.h>

namespace tomo {

inline volatile sig_atomic_t g_signal_doorbell_fd = -1;

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

inline void signal_doorbell_notify() {
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

}  // namespace tomo
