#include <execinfo.h>
#include <unistd.h>
#include <cstdio>
extern "C" char __executable_start;
// flipfix5 DIAGNOSTIC: print the abort-time stack as executable offsets, then exit 134.
extern "C" [[noreturn]] void __wrap_abort() {
    void* frames[64];
    const int n = backtrace(frames, 64);
    std::fprintf(stderr, "FF5 abort-stack:");
    for (int i = 0; i < n; i++)
        std::fprintf(stderr, "%s0x%lx", i ? "," : "",
                     static_cast<unsigned long>(static_cast<char*>(frames[i]) - &__executable_start));
    std::fprintf(stderr, "\n");
    std::fflush(stderr);
    backtrace_symbols_fd(frames, n, 2);
    _exit(134);
}
