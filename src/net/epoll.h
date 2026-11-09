// epoll.h — the second network event engine, selected at boot by --net-io epoll.
//
// IoLoop uses this readiness engine when --net-io selects epoll. io_uring remains the default
// with a ring per thread and DEFER_TASKRUN; epoll also supports environments where older or
// hardened kernels, seccomp-blocked containers, or hypervisors prevent io_uring_setup.
//
// The engine controls how an IO thread waits for and consumes network readiness. Routing,
// shard ownership, ROB retirement order and reply structure share the parse -> route -> retire ->
// stage -> write pipeline. IoLoop::run selects a template instantiation at boot; helpers also
// retain engine state for transport-specific operations.
//
// THE THREE SHAPE DIFFERENCES, stated once here because every subtlety below follows from them:
//   1. io_uring COMPLETES operations; epoll only REPORTS READINESS. So under epoll the io thread
//      issues recv/send/accept itself, synchronously, and the "completion" is the syscall's return
//      value fed to the same accounting the CQE result feeds.
//   2. io_uring holds a pointer into our buffers while a recv/send is in flight. epoll never does.
//      Read-buffer relocation still requires ROB quiescence. Output relocation also respects
//      OpenSSL retry reservations. Closing clients still wait for safe_to_release's operation,
//      retire-post and WATCH lifetime fences.
//   3. epoll has no cross-thread doorbell of its own. io_uring has msg_ring. See uring.h for the
//      eventfd mailbox that implements the same executor/channel wake interface.
//
// EDGE TRIGGERED, ARMED ONCE PER OWNERSHIP TENURE, NEVER HOT-PATH RE-ARMED. A connection is added
// when an IO thread acquires ownership and normally remains registered until ::close(). Runtime
// migration uses a reversible registration hand-off: at an event-loop boundary the
// destination pre-registers the fd while the old owner registers a duplicated descriptor for the
// same socket, then removes its original entry before the connection-owner edge. Destination and
// backup events are ignored during preparation. Commit closes the backup; rollback makes that
// already-registered duplicate the Client's fd and closes the original. Thus every ADD/dup is a
// reversible preflight operation, never a post-commit or rollback connection-loss point.
// Edge triggering retains the standard obligation: read/write until EAGAIN, and if we stop early
// (no read space, ROB full) remember that ourselves rather than expecting another edge. Client's
// recv_armed_ carries exactly that memory under this engine -- true means "we reached EAGAIN, an
// edge is owed", false means "there may be more, retry without waiting".
#pragma once
#include <sys/epoll.h>
#include <sys/eventfd.h>
#include <unistd.h>
#include <fcntl.h>
#include <cerrno>
#include <cstdint>
#include <cstdio>

namespace tomo {

// Owns an epoll descriptor and its last event batch for one IoLoop. The loop owns batch access;
// migration preparation can add/delete destination registrations from the source IO through
// ThreadCtx hooks. These call kernel epoll_ctl; this wrapper supplies no lock. Separate sets
// preserve SO_REUSEPORT accept distribution. init/add/del return failure; wait maps nonpositive
// syscall results, including EINTR, to an empty batch. shutdown closes the descriptor after use.
class EpollSet {
public:
    static constexpr int kMaxEvents = 256;

    EpollSet() = default;
    ~EpollSet() { shutdown(); }
    EpollSet(const EpollSet&) = delete;
    EpollSet& operator=(const EpollSet&) = delete;

    bool init() {
        fd_ = ::epoll_create1(EPOLL_CLOEXEC);
        if (fd_ < 0) {
            std::perror("epoll_create1");
            return false;
        }
        return true;
    }
    void shutdown() {
        if (fd_ >= 0) {
            ::close(fd_);
            fd_ = -1;
        }
        n_ = 0;
    }
    bool add(int target, uint32_t events, uint64_t tag) {
        epoll_event ev{};
        ev.events = events;
        ev.data.u64 = tag;
        return ::epoll_ctl(fd_, EPOLL_CTL_ADD, target, &ev) == 0;
    }
    // Migration uses explicit removal. Normal teardown relies on close(fd), which removes the
    // registration atomically with the resource it names.
    bool del(int target) { return ::epoll_ctl(fd_, EPOLL_CTL_DEL, target, nullptr) == 0; }
    // Blocking (or, with timeout_ms == 0, polling) wait. EINTR is reported as zero events rather
    // than as an error: the loop's next pass re-reads its stop flag, which is how shutdown lands.
    int wait(int timeout_ms) {
        const int n = ::epoll_wait(fd_, events_, kMaxEvents, timeout_ms);
        n_ = n > 0 ? n : 0;
        return n_;
    }
    const epoll_event& event(int i) const { return events_[i]; }

private:
    int fd_ = -1;
    int n_ = 0;
    epoll_event events_[kMaxEvents];
};

// Epoll requires O_NONBLOCK because the IO thread issues recv/send/accept itself; blocking would
// park every connection it owns. TLS socket BIO handshakes also require nonblocking descriptors.
inline bool set_nonblocking(int fd) {
    const int flags = ::fcntl(fd, F_GETFL, 0);
    if (flags < 0) return false;
    return ::fcntl(fd, F_SETFL, flags | O_NONBLOCK) == 0;
}

}  // namespace tomo
