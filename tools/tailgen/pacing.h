#pragma once

#include <cerrno>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <system_error>
#include <time.h>

namespace tailgen {

inline uint64_t now_ns() {
    timespec ts{};
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) throw std::system_error(errno, std::generic_category(), "clock_gettime");
    return static_cast<uint64_t>(ts.tv_sec) * 1'000'000'000 + ts.tv_nsec;
}

inline void sleep_until(uint64_t deadline) {
    const timespec ts{static_cast<time_t>(deadline / 1'000'000'000),
                      static_cast<long>(deadline % 1'000'000'000)};
    int error;
    do { error = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &ts, nullptr); }
    while (error == EINTR);
    if (error) throw std::system_error(error, std::generic_category(), "clock_nanosleep");
}

inline void spin_hint() {
#if defined(__x86_64__) || defined(__i386__)
    __builtin_ia32_pause();
#elif defined(__aarch64__)
    asm volatile("yield");
#endif
}

// Explicit SplitMix64 and rejection sampling, independent of STL distribution
// implementations. Arrivals and command/key choices use separate RNG streams.
class Random {
public:
    explicit Random(uint64_t seed) : state_(seed) {}
    uint64_t next() {
        uint64_t z = (state_ += 0x9e3779b97f4a7c15ULL);
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
        return z ^ (z >> 31);
    }
    uint64_t bounded(uint64_t n) {
        if (!n) throw std::invalid_argument("empty random range");
        const uint64_t threshold = -n % n;
        for (;;) { const uint64_t x = next(); if (x >= threshold) return x % n; }
    }
    double open_unit() { return (static_cast<double>(next() >> 12) + 0.5) * 0x1p-52; }
private:
    uint64_t state_;
};

enum class Spacing { poisson, fixed };

class Arrivals {
public:
    Arrivals(double total_rate, size_t threads, size_t thread, Spacing spacing, uint64_t seed)
        : random_(seed + 0x9e3779b97f4a7c15ULL * (thread + 1)), spacing_(spacing),
          interval_(1e9L * threads / total_rate),
          elapsed_(spacing == Spacing::fixed ? -interval_ + 1e9L * (thread + 1) / total_rate : 0) {
        if (!std::isfinite(total_rate) || total_rate <= 0 || !threads || thread >= threads)
            throw std::invalid_argument("invalid arrival process");
    }
    uint64_t next_offset_ns() {
        elapsed_ += spacing_ == Spacing::fixed ? interval_ : -std::log(random_.open_unit()) * interval_;
        return static_cast<uint64_t>(elapsed_ + 0.5L);
    }
private:
    Random random_;
    Spacing spacing_;
    long double interval_, elapsed_;
};

// A worker must keep servicing replies while it waits: sleeping with in-flight
// requests would add generator delay to their latency. The idle case uses an
// absolute nanosleep, waking 60 us early; the remainder spins with service().
// service() returns true only when no network work can arrive until the send.
template <class Service>
uint64_t pace_until(uint64_t deadline, Service&& service) {
    constexpr uint64_t spin_ns = 60'000;
    for (;;) {
        uint64_t now = now_ns();
        if (now >= deadline) return now;
        const bool idle = service(deadline);
        now = now_ns();
        if (idle && now < deadline && deadline - now > spin_ns)
            sleep_until(deadline - spin_ns);
        else
            spin_hint();
    }
}

} // namespace tailgen
