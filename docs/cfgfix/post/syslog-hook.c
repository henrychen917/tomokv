
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
static void record(const char *kind, const char *value, int number) {
    const char *path = getenv("CFGFIX_SYSLOG_RECEIPT");
    if (!path) _exit(97);
    int fd = open(path, O_WRONLY | O_CREAT | O_APPEND, 0600);
    if (fd < 0) _exit(98);
    dprintf(fd, "%s\t%s\t%d\n", kind, value, number);
    close(fd);
}
void openlog(const char *ident, int options, int facility) {
    (void)options; record("openlog", ident, facility);
}
void syslog(int priority, const char *format, ...) {
    (void)format; record("syslog", "", priority);
}
void __syslog_chk(int priority, int flag, const char *format, ...) {
    (void)flag; (void)format; record("syslog", "", priority);
}
void closelog(void) { record("closelog", "", 0); }
