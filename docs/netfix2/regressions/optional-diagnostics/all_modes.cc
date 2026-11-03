#include <sys/wait.h>
// Deterministic native receipt for a short read sharing its edge with EOF.
// Socketpair only: no server threads, load generator, or elapsed-time verdict.
#include "src/core/io_loop.h"
#include <cstdio>
#include <cstdlib>
#include <sys/socket.h>
#include <unistd.h>

namespace tomo {
struct NetcmdRegression {
    static void need(bool value, const char* what) {
        if (!value) { std::fprintf(stderr, "FAIL: %s\n", what); std::exit(1); }
    }
    template<bool Fused> static void edge(bool eof) {
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
             ur_tag(UrKind::Recv, &client)), "private epoll registration");
        constexpr char payload[] = "BRPOPLPUSH a b 0\r\nBRPOPLPUSH a b 0\r\n";
        need(::write(pair[1], payload, sizeof(payload)-1) == sizeof(payload)-1,
             "short payload queued before readiness observation");
        if (eof) need(::shutdown(pair[1], SHUT_WR) == 0, "EOF queued before readiness observation");
        need(loop.epoll_pass<false, false, Fused>(0) == 1, "exactly one readiness event observed");
        const auto flags = loop.ep_.event(0).events;
        need((flags & EPOLLIN) && bool(flags & EPOLLRDHUP) == eof,
             "payload and requested EOF share the observed edge");
        loop.arm_recv<true>(&client);
        need(client.rlen() == sizeof(payload)-1, "short read consumed every queued byte");
        need(loop.ep_.wait(0) == 0, "no replacement edge is available");
        if (eof) {
            need(loop.epoll_closes_.size() == 1 && loop.epoll_closes_[0] == &client,
                 "coalesced EOF queues the parked client for teardown");
        } else {
            need(loop.epoll_closes_.empty() && client.recv_armed(),
                 "an open peer remains armed and is not closed");
        }
        ::close(pair[0]);
        ::close(pair[1]);
        std::printf("PASS epoll coalesced EOF mode=%s eof=%u\n", Fused ? "1s" : "2s", eof);
    }
};
}

int main() {
    void (*cases[])() = {
        [] { tomo::NetcmdRegression::edge<false>(false); },
        [] { tomo::NetcmdRegression::edge<true>(false); },
        [] { tomo::NetcmdRegression::edge<false>(true); },
        [] { tomo::NetcmdRegression::edge<true>(true); }
    };
    bool failed = false;
    for (auto test : cases) {
        const pid_t child = ::fork();
        if (child < 0) return 2;
        if (!child) { test(); std::exit(0); }
        int status = 0;
        if (::waitpid(child, &status, 0) != child) return 2;
        failed |= !WIFEXITED(status) || WEXITSTATUS(status) != 0;
    }
    return failed ? 1 : 0;
}
