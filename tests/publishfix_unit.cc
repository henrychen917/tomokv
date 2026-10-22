// Re-enter the real publication bracket at its vulnerable load/decrement boundary.
// Every linked object is built with TOMO_PUBLISHFIX_TEST; production has no hook.
#include "src/core/server.h"
#include <cstdio>
#include <cstdlib>

using tomo::Server;
namespace {
unsigned peers;
void require(bool yes, const char* reason) {
    if (!yes) {
        std::fprintf(stderr, "FAIL publishfix: %s\n", reason);
        std::exit(1);
    }
}
bool overlapping(unsigned count) {
    Server server;
    peers = count - 1;
    Server::test_after_drawn = [](Server& s) {
        Server::test_after_drawn = nullptr;
        for (unsigned i = 0; i < peers; ++i) {
            require(s.atomic_commit_reserve() == i + 2, "peer draws after A loaded drawn=1");
            s.atomic_commit_publish();
            require(s.atomic_snapshot() == 0, "peer cannot publish while A holds the bracket");
        }
    };
    require(server.atomic_commit_reserve() == 1, "A draws ticket 1");
    const auto windows = server.atomic_commit_windows();
    server.atomic_commit_publish();
    require(!Server::test_after_drawn, "one-shot hook actually ran");
    require(server.atomic_commit_windows() == windows + peers, "every non-last window opened");
    std::printf("committers=%u safe=%llu drawn=%llu windows=%llu\n", count,
                (unsigned long long)server.atomic_snapshot(),
                (unsigned long long)server.atomic_commit_drawn(),
                (unsigned long long)(server.atomic_commit_windows() - windows));
    return server.atomic_snapshot() == server.atomic_commit_drawn();
}
void handoff() {
    Server server;
    Server::test_after_drawn = [](Server& s) {
        Server::test_after_drawn = nullptr;
        require(s.atomic_commit_reserve() == 2, "next holder draws ticket 2");
    };
    require(server.atomic_commit_reserve() == 1, "handoff A draws ticket 1");
    server.atomic_commit_publish();
    require(server.atomic_snapshot() == 0, "undecided holder must stay invisible");
    require(server.atomic_commit_windows() == 1, "handoff window opened");
    server.atomic_commit_publish();
    require(server.atomic_snapshot() == 2, "last holder publishes both tickets");
    std::puts("handoff safe=2 drawn=2 windows=1");
}
}
int main() {
    const bool two = overlapping(2), three = overlapping(3);
    handoff();
    require(two && three, "a quiescent bracket publishes every drawn ticket");
    std::puts("PASS publishfix");
}
