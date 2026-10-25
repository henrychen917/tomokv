#define _GNU_SOURCE
/* Diagnostic-only preload: preserve the production executable and print the
 * otherwise silent abort call stack. Never used for passing gate evidence. */
#include <execinfo.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/syscall.h>
#include <unistd.h>

static void trace_abort(int signal_number) {
    void *frames[96];
    const int count = backtrace(frames, 96);
    dprintf(STDERR_FILENO, "WAVE7_ABORT pid=%ld tid=%ld signal=%d\n",
            (long)getpid(), (long)syscall(SYS_gettid), signal_number);
    backtrace_symbols_fd(frames, count, STDERR_FILENO);
    struct sigaction action = {.sa_handler = SIG_DFL};
    sigemptyset(&action.sa_mask);
    sigaction(SIGABRT, &action, NULL);
    sigset_t unblocked;
    sigemptyset(&unblocked);
    sigaddset(&unblocked, SIGABRT);
    sigprocmask(SIG_UNBLOCK, &unblocked, NULL);
    syscall(SYS_tgkill, getpid(), syscall(SYS_gettid), SIGABRT);
    _exit(134);
}

__attribute__((constructor)) static void install_abort_trace(void) {
    void *frame;
    (void)backtrace(&frame, 1); /* Resolve unwinder before an exceptional path. */
    struct sigaction action = {.sa_handler = trace_abort};
    sigemptyset(&action.sa_mask);
    sigaction(SIGABRT, &action, NULL);
}

__attribute__((noreturn)) void abort(void) {
    trace_abort(SIGABRT);
    __builtin_unreachable();
}
