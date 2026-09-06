// Counts library memcpy/memmove calls made by the server, so a per-op copy count can be taken
// against a replay of known length. Only calls that go through the PLT are visible -- an inlined
// __builtin_memcpy or the tree's own bytes_copy is not a call and is deliberately not counted.
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <signal.h>
#include <unistd.h>

static __thread int in_hook = 0;
static unsigned long long n_memcpy = 0, n_bytes = 0;
static unsigned long long n_small = 0;   // <= 16 bytes: the fixed-reply shape

void* memcpy(void* d, const void* s, size_t n) {
    if (!in_hook) { __atomic_add_fetch(&n_memcpy, 1, __ATOMIC_RELAXED);
                    __atomic_add_fetch(&n_bytes, n, __ATOMIC_RELAXED);
                    if (n <= 16) __atomic_add_fetch(&n_small, 1, __ATOMIC_RELAXED); }
    char* dd = (char*)d; const char* ss = (const char*)s;
    for (size_t i = 0; i < n; i++) dd[i] = ss[i];
    return d;
}

static void dump(int sig) {
    (void)sig;
    in_hook = 1;
    char buf[256];
    int k = snprintf(buf, sizeof buf, "INTERPOSE memcpy_calls=%llu small16=%llu bytes=%llu\n",
                     n_memcpy, n_small, n_bytes);
    ssize_t w = write(2, buf, k); (void)w;
    in_hook = 0;
    _exit(0);
}

__attribute__((constructor)) static void init(void) {
    struct sigaction sa; memset(&sa, 0, sizeof sa);
    sa.sa_handler = dump;
    sigaction(SIGUSR2, &sa, NULL);
}
