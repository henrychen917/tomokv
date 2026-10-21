/* wave3: scratch LD_PRELOAD allocation counter for docs/wave3/tools/mkfix_counts_w3.py.
 *
 * Re-creates the allocation half of the mkfix2 lane's (uncommitted, since deleted) scratch
 * interposer: it forwards malloc, calloc, realloc, posix_memalign, aligned_alloc, mallocx and
 * rallocx to the next definition (the server's dynamically linked jemalloc) and, while word 0 of
 * the shared counts file is nonzero, counts calls, requested bytes and exact-size requests of
 * 192/384/768/256/512/1024/1536/16384 bytes per entrypoint, in the runner's layout
 * (word 8 + entry*16 + field). It has no mechanism counters (the lane's instrumented builds are
 * gone; the runner leaves `mechanisms` absent when word 135 is not 2). Never a gate row; the
 * production binary is unmodified. Build: gcc -O2 -shared -fPIC -o mkcount.so mkcount.c -ldl
 */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

enum { E_MALLOC, E_CALLOC, E_REALLOC, E_MEMALIGN, E_ALIGNED, E_MALLOCX, E_RALLOCX };
static volatile uint64_t *counts;
static int init_state; /* 0 = not started, 1 = resolving, 2 = ready */
static void *(*real_malloc)(size_t);
static void *(*real_calloc)(size_t, size_t);
static void *(*real_realloc)(void *, size_t);
static int (*real_memalign)(void **, size_t, size_t);
static void *(*real_aligned)(size_t, size_t);
static void *(*real_mallocx)(size_t, int);
static void *(*real_rallocx)(void *, size_t, int);
static void (*real_free)(void *);
/* dlsym may calloc before the real allocator is known: serve it from a static arena. */
static char boot[4096] __attribute__((aligned(64)));
static size_t boot_used;

static void resolve(void) {
    if (init_state) return;
    init_state = 1;
    real_malloc = dlsym(RTLD_NEXT, "malloc");
    real_calloc = dlsym(RTLD_NEXT, "calloc");
    real_realloc = dlsym(RTLD_NEXT, "realloc");
    real_memalign = dlsym(RTLD_NEXT, "posix_memalign");
    real_aligned = dlsym(RTLD_NEXT, "aligned_alloc");
    real_mallocx = dlsym(RTLD_NEXT, "mallocx");
    real_rallocx = dlsym(RTLD_NEXT, "rallocx");
    real_free = dlsym(RTLD_NEXT, "free");
    const char *path = getenv("MKFIX_COUNTS_FILE");
    if (path) {
        int fd = open(path, O_RDWR);
        if (fd >= 0) {
            void *map = mmap(0, 4096, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
            close(fd);
            if (map != MAP_FAILED) counts = map;
        }
    }
    init_state = 2;
}

static void count(int entry, size_t size) {
    volatile uint64_t *c = counts;
    if (!c || !__atomic_load_n(&c[0], __ATOMIC_RELAXED)) return;
    volatile uint64_t *row = c + 8 + entry * 16;
    __atomic_fetch_add(&row[0], 1, __ATOMIC_RELAXED);
    __atomic_fetch_add(&row[1], size, __ATOMIC_RELAXED);
    static const size_t bins[8] = {192, 384, 768, 256, 512, 1024, 1536, 16384};
    for (int i = 0; i < 8; ++i)
        if (size == bins[i]) __atomic_fetch_add(&row[2 + i], 1, __ATOMIC_RELAXED);
}

static int from_boot(const void *p) { return (const char *)p >= boot && (const char *)p < boot + sizeof boot; }

void *malloc(size_t n) { resolve(); count(E_MALLOC, n); return real_malloc(n); }

void *calloc(size_t a, size_t b) {
    if (init_state == 1) { /* inside dlsym: bump-allocate zeroed bootstrap memory */
        size_t n = (a * b + 15) & ~(size_t)15;
        if (boot_used + n > sizeof boot) return 0;
        void *p = boot + boot_used; boot_used += n; return p;
    }
    resolve(); count(E_CALLOC, a * b); return real_calloc(a, b);
}

void *realloc(void *p, size_t n) {
    resolve(); count(E_REALLOC, n);
    if (from_boot(p)) { void *q = real_malloc(n); if (q) memcpy(q, p, n); return q; }
    return real_realloc(p, n);
}

void free(void *p) {
    if (!p || from_boot(p)) return;
    if (init_state != 2) { if (init_state == 1) return; resolve(); } /* dlsym's own frees leak */
    real_free(p);
}

int posix_memalign(void **out, size_t align, size_t n) {
    resolve(); count(E_MEMALIGN, n); return real_memalign(out, align, n);
}

void *aligned_alloc(size_t align, size_t n) { resolve(); count(E_ALIGNED, n); return real_aligned(align, n); }

void *mallocx(size_t n, int flags) { resolve(); count(E_MALLOCX, n); return real_mallocx(n, flags); }

void *rallocx(void *p, size_t n, int flags) { resolve(); count(E_RALLOCX, n); return real_rallocx(p, n, flags); }
