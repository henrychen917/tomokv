#pragma once

#include <algorithm>
#include <array>
#include <bit>
#include <cstdint>
#include <stdexcept>

namespace tailgen {

// HDR-style log-linear buckets: one microsecond through 2047 us, then 1024
// buckets per octave. Quantiles are upper bounds (error <= 1 us + value/1024).
// The sum and maximum retain the original nanoseconds, without quantization.
class Histogram {
public:
    static constexpr uint64_t max_ns = 100'000'000'000ULL;
    static constexpr uint64_t max_us = max_ns / 1000;

    void record(uint64_t ns) {
        if (ns > max_ns) throw std::runtime_error("latency exceeds histogram's 100 s range");
        ++bins_[index((ns + 999) / 1000)];
        ++count_;
        sum_ns_ += ns;
        maximum_ns_ = std::max(maximum_ns_, ns);
    }
    void merge(const Histogram& other) {
        for (size_t i = 0; i < bins_.size(); ++i) bins_[i] += other.bins_[i];
        count_ += other.count_;
        sum_ns_ += other.sum_ns_;
        maximum_ns_ = std::max(maximum_ns_, other.maximum_ns_);
    }
    uint64_t count() const { return count_; }
    double mean_ms() const { return count_ ? static_cast<double>(sum_ns_ / count_ / 1e6L) : 0; }
    double max_ms() const { return static_cast<double>(maximum_ns_) / 1e6; }

    // Integer percentile parts per 100000 avoid floating-point rank errors:
    // p50=50000, p99.9=99900, p99.99=99990. Nearest-rank convention.
    double percentile_ms(uint32_t parts) const {
        if (parts > 100000) throw std::invalid_argument("percentile outside [0, 100000]");
        if (!count_) return 0;
        const uint64_t rank = std::max<uint64_t>(1,
            count_ / 100000 * parts + (count_ % 100000 * parts + 99999) / 100000);
        uint64_t seen = 0;
        for (size_t i = 0; i < bins_.size(); ++i) {
            seen += bins_[i];
            if (seen >= rank) return static_cast<double>(upper(i)) / 1000;
        }
        throw std::logic_error("histogram count mismatch");
    }

private:
    static size_t index(uint64_t us) {
        if (us < 2048) return us;
        const unsigned shift = std::bit_width(us) - 11;
        return (shift + 1) * 1024 + (us >> shift) - 1024;
    }
    static uint64_t upper(size_t index) {
        if (index < 2048) return index;
        const unsigned shift = index / 1024 - 1;
        return std::min(max_us, ((1024 + index % 1024 + 1) << shift) - 1);
    }
    std::array<uint64_t, 18 * 1024> bins_{};
    uint64_t count_ = 0;
    long double sum_ns_ = 0;
    uint64_t maximum_ns_ = 0;
};

} // namespace tailgen
