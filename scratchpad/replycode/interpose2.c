// As interpose.c, but ATTRIBUTES each memcpy to its call site so a copy-count delta can be shown
// to come from the reply path rather than from somewhere else.
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>

#define NSLOT 4096
static struct { void* ra; unsigned long long n; unsigned long long bytes; } tab[NSLOT];
static __thread int in_hook = 0;

void* memcpy(void* d, const void* s, size_t n) {
    if (!in_hook) {
        void* ra = __builtin_return_address(0);
        unsigned long h = ((unsigned long)ra >> 2) & (NSLOT - 1);
        for (unsigned i = 0; i < NSLOT; i++) {
            unsigned long k = (h + i) & (NSLOT - 1);
            void* cur = __atomic_load_n(&tab[k].ra, __ATOMIC_RELAXED);
            if (cur == ra) { __atomic_add_fetch(&tab[k].n, 1, __ATOMIC_RELAXED);
                             __atomic_add_fetch(&tab[k].bytes, n, __ATOMIC_RELAXED); break; }
            if (cur == 0) { void* exp = 0;
                if (__atomic_compare_exchange_n(&tab[k].ra, &exp, ra, 0, __ATOMIC_RELAXED, __ATOMIC_RELAXED)
                    || tab[k].ra == ra) {
                    __atomic_add_fetch(&tab[k].n, 1, __ATOMIC_RELAXED);
                    __atomic_add_fetch(&tab[k].bytes, n, __ATOMIC_RELAXED); }
                break; }
        }
    }
    char* dd = (char*)d; const char* ss = (const char*)s;
    for (size_t i = 0; i < n; i++) dd[i] = ss[i];
    return d;
}

static void dump(int sig) {
    (void)sig; in_hook = 1;
    char buf[128];
    for (int k = 0; k < NSLOT; k++) {
        if (!tab[k].ra || !tab[k].n) continue;
        int m = snprintf(buf, sizeof buf, "RA %p %llu %llu\n", tab[k].ra, tab[k].n, tab[k].bytes);
        ssize_t w = write(2, buf, m); (void)w;
    }
    ssize_t w = write(2, "RA-END\n", 7); (void)w;
    in_hook = 0; _exit(0);
}
__attribute__((constructor)) static void init(void) {
    struct sigaction sa; memset(&sa, 0, sizeof sa); sa.sa_handler = dump;
    sigaction(SIGUSR2, &sa, NULL);
}
