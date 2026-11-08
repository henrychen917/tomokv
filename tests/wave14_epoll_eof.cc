// Deterministic native receipt for a short read sharing its edge with EOF.
// Socketpair only: no server threads, load generator, or elapsed-time verdict.
#include "src/core/io_loop.h"
#include <cstdio>
#include <cstdlib>
#include <new>
#include <sys/socket.h>
#include <unistd.h>

namespace {
bool fail_next_allocation = false;
}
__attribute__((noinline)) void* operator new(std::size_t size) {
    if (fail_next_allocation) {
        fail_next_allocation = false;
        throw std::bad_alloc();
    }
    if (void* result = std::malloc(size ? size : 1)) return result;
    throw std::bad_alloc();
}
__attribute__((noinline)) void operator delete(void* pointer) noexcept { std::free(pointer); }
__attribute__((noinline)) void operator delete(void* pointer, std::size_t) noexcept {
    std::free(pointer);
}

namespace tomo {
struct NetcmdRegression {
    static void need(bool value, const char* what) {
        if (!value) {
            std::fprintf(stderr, "FAIL: %s\n", what);
            std::exit(1);
        }
    }
    template <bool Fused>
    static void edge(bool eof) {
        Server server;
        ThreadCtx self;
        self.init(0, Role::Ifid, 1, 0, 0);
        IoLoop loop;
        loop.srv_ = &server;
        loop.self_ = &self;
        int pair[2];
        need(::socketpair(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK, 0, pair) == 0,
             "socketpair created");
        Client client(pair[0]);
        client.set_ifid_thread(0);
        client.set_blocked(true);
        client.set_recv_armed(true);
        need(loop.ep_.init() && loop.ep_.add(pair[0], EPOLLIN | EPOLLOUT | EPOLLRDHUP | EPOLLET,
                                             ur_tag(UrKind::Recv, &client)),
             "private epoll registration");
        constexpr char payload[] = "BRPOPLPUSH a b 0\r\nBRPOPLPUSH a b 0\r\n";
        need(::write(pair[1], payload, sizeof(payload) - 1) == sizeof(payload) - 1,
             "short payload queued before readiness observation");
        if (eof) need(::shutdown(pair[1], SHUT_WR) == 0, "EOF queued before readiness observation");
        need(loop.epoll_pass<false, false, Fused>(0) == 1, "exactly one readiness event observed");
        const auto flags = loop.ep_.event(0).events;
        need((flags & EPOLLIN) && bool(flags & EPOLLRDHUP) == eof,
             "payload and requested EOF share the observed edge");
        loop.arm_recv<true>(&client);
        need(client.rlen() == sizeof(payload) - 1, "short read consumed every queued byte");
        need(loop.ep_.wait(0) == 0, "no replacement edge is available");
        if (eof) {
#ifdef TOMO_EOFFIX
            need(loop.receive_eof_pending(&client), "coalesced FIN retained after short read");
            client.set_blocked(
                false);  // Exercise draining separately from live blocking cancellation.
            need(!loop.receive_eof_pass(0, 0), "buffered input is not discarded at FIN");
            loop.arm_recv<true>(&client);
            need(loop.deferred_timers_[0].kind == IoLoop::DeferredTimerKind::ReceiveEof &&
                     client.recv_armed(),
                 "actual EOF stops receive admission until input drains");
            need(client.rlen() == sizeof(payload) - 1 && !client.closing(),
                 "all buffered input remains available to the ordinary parser");
            client.set_blocked(true);
            loop.deferred_timers_.push_back(IoLoop::DeferredTimer{
                &client, 0, 1, 0, {}, IoLoop::DeferredTimerKind::DebugSleepOk});
            need(!loop.receive_eof_pass(0, 1) && !client.closing(),
                 "EOF cannot cancel a pending synchronous control command");
            need(client.rlen() == sizeof(payload) - 1 && client.recv_armed(),
                 "control wait retains its complete buffered suffix and EOF hold");
            loop.deferred_timers_.pop_back();
            client.set_blocked(false);
#else
            need(loop.epoll_closes_.size() == 1 && loop.epoll_closes_[0] == &client,
                 "coalesced EOF queues the parked client for teardown");
#endif
        } else {
            need(loop.epoll_closes_.empty() && client.recv_armed(),
                 "an open peer remains armed and is not closed");
        }
        ::close(pair[0]);
        ::close(pair[1]);
        std::printf("PASS epoll coalesced EOF mode=%s eof=%u\n", Fused ? "1s" : "2s", eof);
    }
#ifdef TOMO_EOFFIX
    static void allocation_failure() {
        IoLoop loop;
        // Queue the error close so this finite fixture can inspect its admission
        // fence without constructing a live IO owner. The synthetic hold models
        // recv(0) winning an io_uring handoff cancellation.
        loop.epoll_ = true;
        int pair[2];
        need(::socketpair(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK, 0, pair) == 0,
             "allocation-failure socketpair created");
        Client client(pair[0]);
        client.set_recv_armed(true);
        need(loop.deferred_timers_.capacity() == 0, "EOF insertion must allocate");
        fail_next_allocation = true;
        loop.receive_fin(&client, true);
        need(!fail_next_allocation, "EOF-state allocation actually failed");
        need(loop.epoll_closes_.size() == 1 && loop.epoll_closes_[0] == &client,
             "allocation failure requests normal teardown");
        need(!client.recv_armed(), "failed EOF admission releases its synthetic receive hold");
        need(!loop.receive_eof_pending(&client), "failed insertion leaves no EOF state");
        ::close(pair[0]);
        ::close(pair[1]);
        std::puts("PASS EOF allocation failure releases synthetic receive hold");
    }
#endif
};
}
int main() {
    tomo::NetcmdRegression::edge<false>(false);
    tomo::NetcmdRegression::edge<true>(false);
    tomo::NetcmdRegression::edge<false>(true);
    tomo::NetcmdRegression::edge<true>(true);
#ifdef TOMO_EOFFIX
    tomo::NetcmdRegression::allocation_failure();
#endif
}
