// Preemption injector for a correctness race: spin SPIN_US, sleep SLEEP_US, forever.
// Pinned by the caller (taskset) to one server CPU. Measures nothing.
#define _GNU_SOURCE
#include <stdlib.h>
#include <time.h>

static long now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1000000000L + t.tv_nsec;
}

int main(int argc, char** argv) {
    const long spin = (argc > 1 ? atol(argv[1]) : 20) * 1000L;
    const long nap = (argc > 2 ? atol(argv[2]) : 30) * 1000L;
    const struct timespec sleep_for = {0, nap};
    for (;;) {
        const long until = now_ns() + spin;
        while (now_ns() < until) {}
        nanosleep(&sleep_for, NULL);
    }
}
