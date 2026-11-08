// fsyncdelay.c -- LD_PRELOAD shim that makes AOF data syncs slow, so that a reply sent
// before its fsync completes becomes visible as a timing difference of about AOFSHIM_DELAY_MS.
//
// Build:  gcc -O2 -shared -fPIC -o fsyncdelay.so fsyncdelay.c -ldl
//
// Environment:
//   AOFSHIM_DELAY_MS  delay per matching sync (default 2000)
//   AOFSHIM_MATCH     substring the synced file's path must contain (default ".incr.")
//                     TomoKV increments are <name>.<n>.incr.tomo, Redis 7.4 uses <name>.<n>.incr.aof;
//                     manifests, base files and directories are deliberately not delayed.
//   AOFSHIM_LOG       optional log file; one line per delayed sync (CLOCK_MONOTONIC ns, the same
//                     clock as Python's time.monotonic_ns()).
//
// Interposed entry points:
//   fsync, fdatasync                    -- TomoKV --net-io epoll (PersistIoEngine::Normal) and Redis
//   io_uring_submit,                    -- TomoKV --net-io uring (PersistIoEngine::Uring): the AOF
//   io_uring_submit_and_get_events,        queues IORING_OP_FSYNC(DATASYNC) linked behind its write;
//   io_uring_submit_and_wait_timeout       if a pending SQE is an FSYNC on a matching file, sleep
//                                          before handing the batch to the kernel.
// Both styles block the calling thread (the AOF writer) for the delay; durability of the batch
// therefore lands >= DELAY after the sync was requested.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <liburing.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

static long g_delay_ms = -1;
static const char* g_match = NULL;
static int g_log_fd = -2;
static pthread_once_t g_once = PTHREAD_ONCE_INIT;

static int (*real_fsync)(int);
static int (*real_fdatasync)(int);
static int (*real_submit)(struct io_uring*);
static int (*real_submit_get_events)(struct io_uring*);
static int (*real_submit_wait_timeout)(struct io_uring*, struct io_uring_cqe**, unsigned,
                                       struct __kernel_timespec*, sigset_t*);

static void init_once(void) {
    const char* d = getenv("AOFSHIM_DELAY_MS");
    g_delay_ms = d && *d ? strtol(d, NULL, 10) : 2000;
    const char* m = getenv("AOFSHIM_MATCH");
    g_match = m && *m ? m : ".incr.";
    const char* l = getenv("AOFSHIM_LOG");
    g_log_fd = l && *l ? open(l, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0644) : -1;
    real_fsync = (int (*)(int))dlsym(RTLD_NEXT, "fsync");
    real_fdatasync = (int (*)(int))dlsym(RTLD_NEXT, "fdatasync");
    real_submit = (int (*)(struct io_uring*))dlsym(RTLD_NEXT, "io_uring_submit");
    real_submit_get_events =
        (int (*)(struct io_uring*))dlsym(RTLD_NEXT, "io_uring_submit_and_get_events");
    real_submit_wait_timeout =
        (int (*)(struct io_uring*, struct io_uring_cqe**, unsigned, struct __kernel_timespec*,
                 sigset_t*))dlsym(RTLD_NEXT, "io_uring_submit_and_wait_timeout");
}

__attribute__((constructor)) static void shim_ctor(void) { pthread_once(&g_once, init_once); }

static uint64_t mono_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec;
}

// Returns 1 and fills `path` when fd names a file whose path contains AOFSHIM_MATCH.
static int fd_matches(int fd, char* path, size_t cap) {
    char link[64];
    snprintf(link, sizeof link, "/proc/self/fd/%d", fd);
    ssize_t n = readlink(link, path, cap - 1);
    if (n <= 0) return 0;
    path[n] = 0;
    return strstr(path, g_match) != NULL;
}

static void sleep_ms(long ms) {
    struct timespec deadline;
    clock_gettime(CLOCK_MONOTONIC, &deadline);
    deadline.tv_sec += ms / 1000;
    deadline.tv_nsec += (ms % 1000) * 1000000L;
    if (deadline.tv_nsec >= 1000000000L) {
        deadline.tv_sec++;
        deadline.tv_nsec -= 1000000000L;
    }
    while (clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &deadline, NULL) == EINTR) {
    }
}

static void log_sync(const char* kind, int fd, const char* path, uint64_t start, uint64_t end) {
    if (g_log_fd < 0) return;
    char line[768];
    int n = snprintf(line, sizeof line, "SYNC kind=%s pid=%d tid=%ld fd=%d start=%llu end=%llu path=%s\n",
                     kind, (int)getpid(), (long)syscall(SYS_gettid), fd, (unsigned long long)start,
                     (unsigned long long)end, path);
    if (n > 0) {
        ssize_t w = write(g_log_fd, line, (size_t)(n < (int)sizeof line ? n : (int)sizeof line - 1));
        (void)w;
    }
}

// A SYNCSTART line lets the driver see a sync in flight (END lines only appear afterwards).
static void log_start(const char* kind, int fd, uint64_t start) {
    if (g_log_fd < 0) return;
    char line[256];
    int n = snprintf(line, sizeof line, "SYNCSTART kind=%s pid=%d tid=%ld fd=%d start=%llu\n", kind,
                     (int)getpid(), (long)syscall(SYS_gettid), fd, (unsigned long long)start);
    if (n > 0) {
        ssize_t w = write(g_log_fd, line, (size_t)(n < (int)sizeof line ? n : (int)sizeof line - 1));
        (void)w;
    }
}

static int delayed_sync(const char* kind, int (*real)(int), int fd) {
    pthread_once(&g_once, init_once);
    char path[512];
    if (!real) {
        errno = ENOSYS;
        return -1;
    }
    if (g_delay_ms <= 0 || !fd_matches(fd, path, sizeof path)) return real(fd);
    const uint64_t start = mono_ns();
    log_start(kind, fd, start);
    sleep_ms(g_delay_ms);
    const int rc = real(fd);
    const int saved = errno;
    log_sync(kind, fd, path, start, mono_ns());
    errno = saved;
    return rc;
}

int fsync(int fd) { return delayed_sync("fsync", real_fsync, fd); }
int fdatasync(int fd) { return delayed_sync("fdatasync", real_fdatasync, fd); }

// Pending, not yet submitted SQEs live in [sq.sqe_head, sq.sqe_tail) (liburing 2.x layout).
static void uring_maybe_delay(struct io_uring* ring) {
    pthread_once(&g_once, init_once);
    if (!ring || g_delay_ms <= 0) return;
    const unsigned shift = (ring->flags & IORING_SETUP_SQE128) ? 1 : 0;
    const unsigned mask = ring->sq.ring_mask;
    char path[512];
    int found_fd = -1;
    for (unsigned head = ring->sq.sqe_head; head != ring->sq.sqe_tail; head++) {
        const struct io_uring_sqe* sqe = &ring->sq.sqes[(head & mask) << shift];
        if (sqe->opcode != IORING_OP_FSYNC) continue;
        if (sqe->flags & IOSQE_FIXED_FILE) continue;  // TomoKV's AOF sync uses a plain fd
        if (fd_matches(sqe->fd, path, sizeof path)) {
            found_fd = sqe->fd;
            break;
        }
    }
    if (found_fd < 0) return;
    const uint64_t start = mono_ns();
    log_start("uring_fsync", found_fd, start);
    sleep_ms(g_delay_ms);
    log_sync("uring_fsync", found_fd, path, start, mono_ns());
}

int io_uring_submit(struct io_uring* ring) {
    uring_maybe_delay(ring);
    if (!real_submit) return -ENOSYS;
    return real_submit(ring);
}

int io_uring_submit_and_get_events(struct io_uring* ring) {
    uring_maybe_delay(ring);
    if (!real_submit_get_events) return -ENOSYS;
    return real_submit_get_events(ring);
}

int io_uring_submit_and_wait_timeout(struct io_uring* ring, struct io_uring_cqe** cqe_ptr,
                                     unsigned wait_nr, struct __kernel_timespec* ts,
                                     sigset_t* sigmask) {
    uring_maybe_delay(ring);
    if (!real_submit_wait_timeout) return -ENOSYS;
    return real_submit_wait_timeout(ring, cqe_ptr, wait_nr, ts, sigmask);
}
