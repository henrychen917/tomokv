// Finite socketpair receive pass. Calls production-linked bodies, no server.
#include "src/core/io_loop.h"
#include <cstdio>
#include <cstdlib>
#include <sys/socket.h>
using namespace tomo;
#if TOMO_SINGLE_DATABASE
#define NSM "8tomo_db0"
#else
#define NSM "4tomo"
#endif
extern "C" unsigned split_pass(void*, int)
    asm("_ZN" NSM "6IoLoop10epoll_passILb0ELb0ELb0EEEji");
extern "C" unsigned fused_pass(void*, int)
    asm("_ZN" NSM "6IoLoop10epoll_passILb0ELb0ELb1EEEji");
extern "C" unsigned r7_pass(void*, int)
    asm("_ZN" NSM "6IoLoop13r7_epoll_passILb0ELb0ELb1EEEji");
extern "C" void receive(void*, Client*)
    asm("_ZN" NSM "6IoLoop10epoll_recvEPNS_6ClientE");
[[gnu::noinline]] void scope_begin() { asm volatile("" ::: "memory"); }
[[gnu::noinline]] void scope_end() { asm volatile("" ::: "memory"); }
namespace tomo {
struct CoreConcurrencyTest {
    static void need(bool value) { if (!value) std::abort(); }
    static void run(const std::string& command, const std::string& mode, unsigned batch) {
        Server server; ThreadCtx self; self.init(0, Role::Ifid, 1, 0, 0);
        IoLoop loop; loop.srv_ = &server; loop.self_ = &self;
        int pair[2]; need(socketpair(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK, 0, pair) == 0);
        Client client(pair[0]); client.set_ifid_thread(0); client.set_recv_armed(true);
        need(loop.ep_.init() && loop.ep_.add(pair[0], EPOLLIN | EPOLLOUT | EPOLLRDHUP | EPOLLET,
                                           ur_tag(UrKind::Recv, &client)));
        std::string wire;
        for (unsigned i = 0; i < batch; ++i) wire += "*1\r\n$4\r\nPING\r\n";
        need(write(pair[1], wire.data(), wire.size()) == static_cast<ssize_t>(wire.size()));
        scope_begin();
        const unsigned events = command == "EPOLL-R7" ? r7_pass(&loop, 0)
            : mode == "1s" ? fused_pass(&loop, 0) : split_pass(&loop, 0);
        receive(&loop, &client);
        scope_end();
        need(events == 1 && client.rlen() == wire.size() && client.recv_armed());
        need(loop.ep_.wait(0) == 0 && !client.closing());
        close(pair[0]); close(pair[1]);
        std::puts("PASS finite open-peer receive");
    }
};
}
int main(int argc, char** argv) {
    if (argc != 6) return 2;
    CoreConcurrencyTest::run(argv[1], argv[2], std::stoul(argv[3]));
}
