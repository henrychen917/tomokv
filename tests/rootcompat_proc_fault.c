/* Fault injection only: make the main-thread /proc stat unreadable. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>

static int denied(const char *path) {
    if (!strncmp(path, "/proc/self/task/", 16) && strstr(path, "/stat")) {
        fputs("rootcompat: denied proc stat\n", stderr);
        errno = EACCES;
        return 1;
    }
    return 0;
}
FILE *fopen(const char *path, const char *mode) {
    if (denied(path)) return NULL;
    return ((FILE *(*)(const char *, const char *))dlsym(RTLD_NEXT, "fopen"))(path, mode);
}
FILE *fopen64(const char *path, const char *mode) {
    if (denied(path)) return NULL;
    return ((FILE *(*)(const char *, const char *))dlsym(RTLD_NEXT, "fopen64"))(path, mode);
}
