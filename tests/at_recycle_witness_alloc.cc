#include "at_recycle_witness.h"
#include <csignal>
#include <cstdlib>
extern "C" void* __real_mallocx(size_t, int);
extern "C" void __real_sdallocx(void*, size_t, int);
extern "C" void* __wrap_mallocx(size_t n, int flags) {
    ++at_recycle::allocations.mallocx;
    return __real_mallocx(n, flags);
}
extern "C" void __wrap_sdallocx(void* p, size_t n, int flags) {
    ++at_recycle::allocations.sdallocx;
    __real_sdallocx(p, n, flags);
}
namespace {
void snapshot(int) { at_recycle::request.fetch_add(1, std::memory_order_release); }
struct Install {
    Install() {
        struct sigaction action{};
        action.sa_handler = snapshot; sigemptyset(&action.sa_mask); action.sa_flags = SA_RESTART;
        if (sigaction(SIGUSR2, &action, nullptr) != 0) std::abort();
    }
} install;
}
