#ifndef __MONOTONIC_H
#define __MONOTONIC_H
/* The monotonic clock is an always increasing clock source.  It is unrelated to
 * the actual time of day and should only be used for relative timings.  The
 * monotonic clock is also not guaranteed to be chronologically precise; there
 * may be slight skew/shift from a precise clock.
 *
 * Depending on system architecture, the monotonic time may be able to be
 * retrieved much faster than a normal clock source by using an instruction
 * counter on the CPU.  On x86 architectures (for example), the RDTSC
 * instruction is a very fast clock source for this purpose.
 */

#include "fmacros.h"
#include <stdint.h>
#include <unistd.h>

/* A counter in micro-seconds.  The 'monotime' type is provided for variables
 * holding a monotonic time.  This will help distinguish & document that the
 * variable is associated with the monotonic clock and should not be confused
 * with other types of time.*/
typedef uint64_t monotime;

/* Retrieve counter of micro-seconds relative to an arbitrary point in time.  */
extern monotime (*getMonotonicUs)(void);

typedef enum monotonic_clock_type {
    MONOTONIC_CLOCK_POSIX,
    MONOTONIC_CLOCK_HW,
} monotonic_clock_type;

/* Call once at startup to initialize the monotonic clock.  Though this only
 * needs to be called once, it may be called additional times without impact.
 * Returns a printable string indicating the type of clock initialized.
 * (The returned string is static and doesn't need to be freed.)  */
const char *monotonicInit(void);

/* Return a string indicating the type of monotonic clock being used. */
const char *monotonicInfoString(void);

/* Return the type of monotonic clock being used. */
monotonic_clock_type monotonicGetType(void);

/* High-resolution clock used by the opt-in cross-L3 visibility simulator.
 *
 * This is deliberately separate from getMonotonicUs(): sub-microsecond hop
 * delays cannot survive that interface's conversion to whole microseconds.
 * monotonicRawClockInit() validates that x86 advertises an invariant TSC and
 * calibrates it against CLOCK_MONOTONIC_RAW. It is called only when the
 * simulator is enabled, so a normal boot performs no calibration or raw-clock
 * reads. The ordered read prevents message loads from crossing the visibility
 * deadline check; it is timing only, not a replacement for queue/CDB
 * acquire/release ordering. */
int monotonicRawClockInit(void);
uint64_t monotonicRawClock(void);
uint64_t monotonicRawClockTicksFromNs(uint64_t nanoseconds);
uint64_t monotonicRawClockHz(void);

/* Functions to measure elapsed time.  Example:
 *     monotime myTimer;
 *     elapsedStart(&myTimer);
 *     while (elapsedMs(myTimer) < 10) {} // loops for 10ms
 */
static inline void elapsedStart(monotime *start_time) {
    *start_time = getMonotonicUs();
}

static inline uint64_t elapsedUs(monotime start_time) {
    return getMonotonicUs() - start_time;
}

static inline uint64_t elapsedMs(monotime start_time) {
    return elapsedUs(start_time) / 1000;
}

#endif
