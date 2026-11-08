// parkwake F3 witness helper (LD_PRELOAD, test boots only). Under --net-io epoll persistence uses
// the syscall engine, so this reaches every AOF write and sync:
//   PARKWAKE_WRITE_DELAY_US  sleep before each write/pwrite/writev/pwritev to a REGULAR file
//                            (sockets and pipes untouched), default 10000;
//   PARKWAKE_SYNC_DELAY_US   sleep before each fsync/fdatasync, default 0.
// With appendfsync everysec the IOs' reply gate then holds already-Done replies while the
// executors spin out their 2,048-pass budget: the DatabaseExDrain window of F3.
#define _GNU_SOURCE
#include <dlfcn.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/uio.h>
#include <time.h>
#include <unistd.h>

static void parkwake_sleep(const char* name, long fallback) {
    const char* text = getenv(name);
    long us = text ? atol(text) : fallback;
    if (us <= 0) return;
    struct timespec ts = {us / 1000000, (us % 1000000) * 1000};
    while (nanosleep(&ts, &ts) != 0) {
    }
}

static int parkwake_regular(int fd) {
    struct stat st;
    return fstat(fd, &st) == 0 && S_ISREG(st.st_mode);
}

#define PARKWAKE_REAL(type, name, args) \
    static type(*real) args;            \
    if (!real) real = (type(*) args)dlsym(RTLD_NEXT, name)

ssize_t write(int fd, const void* buf, size_t n) {
    PARKWAKE_REAL(ssize_t, "write", (int, const void*, size_t));
    if (parkwake_regular(fd)) parkwake_sleep("PARKWAKE_WRITE_DELAY_US", 10000);
    return real(fd, buf, n);
}

ssize_t pwrite(int fd, const void* buf, size_t n, off_t off) {
    PARKWAKE_REAL(ssize_t, "pwrite", (int, const void*, size_t, off_t));
    if (parkwake_regular(fd)) parkwake_sleep("PARKWAKE_WRITE_DELAY_US", 10000);
    return real(fd, buf, n, off);
}

ssize_t pwrite64(int fd, const void* buf, size_t n, off_t off) {
    PARKWAKE_REAL(ssize_t, "pwrite64", (int, const void*, size_t, off_t));
    if (parkwake_regular(fd)) parkwake_sleep("PARKWAKE_WRITE_DELAY_US", 10000);
    return real(fd, buf, n, off);
}

ssize_t writev(int fd, const struct iovec* iov, int cnt) {
    PARKWAKE_REAL(ssize_t, "writev", (int, const struct iovec*, int));
    if (parkwake_regular(fd)) parkwake_sleep("PARKWAKE_WRITE_DELAY_US", 10000);
    return real(fd, iov, cnt);
}

ssize_t pwritev(int fd, const struct iovec* iov, int cnt, off_t off) {
    PARKWAKE_REAL(ssize_t, "pwritev", (int, const struct iovec*, int, off_t));
    if (parkwake_regular(fd)) parkwake_sleep("PARKWAKE_WRITE_DELAY_US", 10000);
    return real(fd, iov, cnt, off);
}

int fdatasync(int fd) {
    PARKWAKE_REAL(int, "fdatasync", (int));
    parkwake_sleep("PARKWAKE_SYNC_DELAY_US", 0);
    return real(fd);
}

int fsync(int fd) {
    PARKWAKE_REAL(int, "fsync", (int));
    parkwake_sleep("PARKWAKE_SYNC_DELAY_US", 0);
    return real(fd);
}
