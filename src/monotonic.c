#include "monotonic.h"
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <time.h>
#include "redisassert.h"
#include <string.h>

/* The function pointer for clock retrieval.  */
monotime (*getMonotonicUs)(void) = NULL;
monotonic_raw (*getMonotonicRaw)(void) = NULL;
monotime (*monotonicRawToUs)(monotonic_raw delta) = NULL;

static char monotonic_info_string[32];
static monotonic_raw mono_rawUnitsPerMicrosecond = 1;


/* Using the processor clock (aka TSC on x86) can provide improved performance
 * throughout Redis wherever the monotonic clock is used.  The processor clock
 * is significantly faster than calling 'clock_getting' (POSIX).  While this is
 * generally safe on modern systems, this link provides additional information
 * about use of the x86 TSC: http://oliveryang.net/2015/09/pitfalls-of-TSC-usage
 *
 * On ARM aarch64 systems, the hardware clock is enabled by default because the
 * ARM Generic Timer is architecturally guaranteed to be available and monotonic
 * on all ARMv8-A processors (see the “The Generic Timer in AArch64 state”
 * section of the Arm Architecture Reference Manual for Armv8-A).
 *
 * To use the processor clock on other architectures, either uncomment this line,
 * or build with
 *   CFLAGS="-DUSE_PROCESSOR_CLOCK"
#define USE_PROCESSOR_CLOCK
 */

#if (defined(USE_PROCESSOR_CLOCK) && defined(__x86_64__) && defined(__linux__)) || \
    defined(__aarch64__) || \
    (defined(USE_PROCESSOR_CLOCK) && defined(__riscv) && defined(__linux__))
static uint64_t mono_ticksPerMicrosecond = 0;
static uint64_t mono_ticksReciprocal = 0;

/* Convert a hardware-counter value by reciprocal multiplication.  Let d be
 * mono_ticksPerMicrosecond and M=floor(2^64/d), computed once at init.  For
 * every 64-bit tick value t,
 *
 *     t/d - 1 < t*M/2^64 <= t/d.
 *
 * Thus the high half of t*M is either floor(t/d) or one less.  In the latter
 * case the remainder is at least d, so the final comparison corrects it.
 * The result is exactly t/d (0 us error over the full 64-bit counter range),
 * while the runtime path is multiply + shift + multiply/compare, with no
 * 64-bit divide. */
static inline monotime monotonicTicksToUs(uint64_t ticks) {
    uint64_t quotient = (uint64_t)(((__uint128_t)ticks * mono_ticksReciprocal) >> 64);
    uint64_t remainder = ticks - quotient * mono_ticksPerMicrosecond;
    return quotient + (remainder >= mono_ticksPerMicrosecond);
}

static monotime monotonicRawToUs_hw(monotonic_raw delta) {
    return monotonicTicksToUs(delta);
}

static void monotonicSetHardwareFrequency(uint64_t ticks_per_microsecond) {
    assert(ticks_per_microsecond != 0);
    mono_ticksPerMicrosecond = ticks_per_microsecond;
    mono_rawUnitsPerMicrosecond = ticks_per_microsecond;
    /* 2^64 does not fit the reciprocal word for d=1.  UINT64_MAX gives an
     * initial quotient one low for every nonzero input, which the same
     * remainder correction fixes. */
    mono_ticksReciprocal = ticks_per_microsecond == 1
        ? UINT64_MAX
        : (uint64_t)(((__uint128_t)1 << 64) / ticks_per_microsecond);
}
#endif


#if defined(USE_PROCESSOR_CLOCK) && defined(__x86_64__) && defined(__linux__)
#include <regex.h>
#include <x86intrin.h>

static monotonic_raw getMonotonicRaw_x86(void) {
    return __rdtsc();
}

static monotime getMonotonicUs_x86(void) {
    return monotonicTicksToUs(getMonotonicRaw_x86());
}

static void monotonicInit_x86linux(void) {
    const int bufflen = 256;
    char buf[bufflen];
    regex_t cpuGhzRegex, constTscRegex;
    const size_t nmatch = 2;
    regmatch_t pmatch[nmatch];
    int constantTsc = 0;
    int rc;

    /* Determine the number of TSC ticks in a micro-second.  This is
     * a constant value matching the standard speed of the processor.
     * On modern processors, this speed remains constant even though
     * the actual clock speed varies dynamically for each core.  */
    rc = regcomp(&cpuGhzRegex, "^model name\\s+:.*@ ([0-9.]+)GHz", REG_EXTENDED);
    assert(rc == 0);

    /* Also check that the constant_tsc flag is present.  (It should be
     * unless this is a really old CPU.  */
    rc = regcomp(&constTscRegex, "^flags\\s+:.* constant_tsc", REG_EXTENDED);
    assert(rc == 0);

    FILE *cpuinfo = fopen("/proc/cpuinfo", "r");
    if (cpuinfo != NULL) {
        while (fgets(buf, bufflen, cpuinfo) != NULL) {
            if (regexec(&cpuGhzRegex, buf, nmatch, pmatch, 0) == 0) {
                buf[pmatch[1].rm_eo] = '\0';
                double ghz = atof(&buf[pmatch[1].rm_so]);
                uint64_t ticks_per_microsecond = (uint64_t)(ghz * 1000);
                if (ticks_per_microsecond != 0)
                    monotonicSetHardwareFrequency(ticks_per_microsecond);
                break;
            }
        }
        while (fgets(buf, bufflen, cpuinfo) != NULL) {
            if (regexec(&constTscRegex, buf, nmatch, pmatch, 0) == 0) {
                constantTsc = 1;
                break;
            }
        }

        fclose(cpuinfo);
    }
    regfree(&cpuGhzRegex);
    regfree(&constTscRegex);

    if (mono_ticksPerMicrosecond == 0) {
        fprintf(stderr, "monotonic: x86 linux, unable to determine clock rate\n");
        return;
    }
    if (!constantTsc) {
        fprintf(stderr, "monotonic: x86 linux, 'constant_tsc' flag not present\n");
        return;
    }

    snprintf(monotonic_info_string, sizeof(monotonic_info_string),
            "X86 TSC @ %llu ticks/us", (unsigned long long)mono_ticksPerMicrosecond);
    getMonotonicUs = getMonotonicUs_x86;
    getMonotonicRaw = getMonotonicRaw_x86;
    monotonicRawToUs = monotonicRawToUs_hw;
}
#endif

#if defined(__aarch64__)
/* Read the clock value.
 * CNTVCT_EL0 is a system counter register, that provides the monotonic
 * timestamp as a 64-bit count value. */
static inline uint64_t __cntvct(void) {
    uint64_t virtual_timer_value;
    __asm__ volatile("mrs %0, cntvct_el0" : "=r"(virtual_timer_value));
    return virtual_timer_value;
}

/* Read the Count-timer Frequency.
 * CNTFRQ_EL0 is a system counter register that provides the frequency (in Hz)
 * needed to convert ticks to microseconds. Together with CNTVCT_EL0, this enables
 * high-performance monotonic time measurement without system calls. */
static inline uint32_t cntfrq_hz(void) {
    uint64_t virtual_freq_value;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(virtual_freq_value));
    return (uint32_t)virtual_freq_value;    /* top 32 bits are reserved */
}

static monotonic_raw getMonotonicRaw_aarch64(void) {
    return __cntvct();
}

static monotime getMonotonicUs_aarch64(void) {
    return monotonicTicksToUs(getMonotonicRaw_aarch64());
}

static void monotonicInit_aarch64(void) {
    uint64_t ticks_per_microsecond = (uint64_t)cntfrq_hz() / 1000 / 1000;
    if (ticks_per_microsecond != 0)
        monotonicSetHardwareFrequency(ticks_per_microsecond);
    if (mono_ticksPerMicrosecond == 0) {
        fprintf(stderr, "monotonic: aarch64, unable to determine clock rate\n");
        return;
    }

    snprintf(monotonic_info_string, sizeof(monotonic_info_string),
            "ARM CNTVCT @ %llu ticks/us", (unsigned long long)mono_ticksPerMicrosecond);
    getMonotonicUs = getMonotonicUs_aarch64;
    getMonotonicRaw = getMonotonicRaw_aarch64;
    monotonicRawToUs = monotonicRawToUs_hw;
}
#endif


#if defined(USE_PROCESSOR_CLOCK) && defined(__riscv) && defined(__linux__)
static inline uint64_t read_mtime(void) {
    uint64_t val;
    asm volatile("csrr %0, time" : "=r"(val));
    return val;
}

static monotonic_raw getMonotonicRaw_riscv(void) {
    return read_mtime();
}

/* Read RISC-V timebase-frequency, which may be stored as either a 64-bit
 * or 32-bit big-endian integer in the device tree.  */
static uint64_t get_timebase_frequency(void) {
    uint64_t freq = 0;
    FILE *fp = fopen("/proc/device-tree/cpus/timebase-frequency", "rb");
    if (!fp)
        return 0;

    uint8_t buf[8] = {0};
    size_t cnt = fread(buf, 1, sizeof(buf), fp);
    fclose(fp);

    if (cnt == 8) {
        uint64_t be64 = 0;
        memcpy(&be64, buf, sizeof(be64));
        /* Convert be64 from big-endian to little-endian.  */
        freq = __builtin_bswap64(be64);
    } else if (cnt == 4) {
        uint32_t be32 = 0;
        memcpy(&be32, buf, sizeof(be32));
        /* Convert be32 from big-endian to little-endian.  */
        freq = __builtin_bswap32(be32);
    } else {
        /* Unable to read timebase-frequency.  */
        return 0;
    }

    return freq;
}

static monotime getMonotonicUs_riscv(void) {
    return monotonicTicksToUs(getMonotonicRaw_riscv());
}

static void monotonicInit_riscv(void) {
    uint64_t ticks_per_microsecond = get_timebase_frequency() / 1000 / 1000;
    if (ticks_per_microsecond != 0)
        monotonicSetHardwareFrequency(ticks_per_microsecond);
    if (mono_ticksPerMicrosecond == 0) {
        fprintf(stderr, "monotonic: riscv, unable to determine clock rate\n");
        return;
    }
    snprintf(monotonic_info_string, sizeof(monotonic_info_string),
            "RISC-V mtime @ %llu ticks/us", (unsigned long long)mono_ticksPerMicrosecond);
    getMonotonicUs = getMonotonicUs_riscv;
    getMonotonicRaw = getMonotonicRaw_riscv;
    monotonicRawToUs = monotonicRawToUs_hw;
}
#endif

static monotime getMonotonicUs_posix(void) {
    /* clock_gettime() is specified in POSIX.1b (1993).  Even so, some systems
     * did not support this until much later.  CLOCK_MONOTONIC is technically
     * optional and may not be supported - but it appears to be universal.
     * If this is not supported, provide a system-specific alternate version.  */
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ((uint64_t)ts.tv_sec) * 1000000 + ts.tv_nsec / 1000;
}

static monotonic_raw getMonotonicRaw_posix(void) {
    return getMonotonicUs_posix();
}

static monotime monotonicRawToUs_posix(monotonic_raw delta) {
    return delta;
}

static void monotonicInit_posix(void) {
    /* Ensure that CLOCK_MONOTONIC is supported.  This should be supported
     * on any reasonably current OS.  If the assertion below fails, provide
     * an appropriate alternate implementation.  */
    struct timespec ts;
    int rc = clock_gettime(CLOCK_MONOTONIC, &ts);
    assert(rc == 0);

    snprintf(monotonic_info_string, sizeof(monotonic_info_string),
            "POSIX clock_gettime");
    mono_rawUnitsPerMicrosecond = 1;
    getMonotonicUs = getMonotonicUs_posix;
    getMonotonicRaw = getMonotonicRaw_posix;
    monotonicRawToUs = monotonicRawToUs_posix;
}

monotonic_raw monotonicUsToRaw(monotime us) {
    return us * mono_rawUnitsPerMicrosecond;
}


const char * monotonicInit(void) {
    #if defined(USE_PROCESSOR_CLOCK) && defined(__x86_64__) && defined(__linux__)
    if (getMonotonicUs == NULL) monotonicInit_x86linux();
    #endif

    #if defined(__aarch64__)
    if (getMonotonicUs == NULL) monotonicInit_aarch64();
    #endif

    #if defined(USE_PROCESSOR_CLOCK) && defined(__riscv) && defined(__linux__)
    if (getMonotonicUs == NULL) monotonicInit_riscv();
    #endif

    if (getMonotonicUs == NULL) monotonicInit_posix();

    return monotonic_info_string;
}

const char *monotonicInfoString(void) {
    return monotonic_info_string;
}

monotonic_clock_type monotonicGetType(void) {
    if (getMonotonicUs == getMonotonicUs_posix)
        return MONOTONIC_CLOCK_POSIX;
    return MONOTONIC_CLOCK_HW;
}
