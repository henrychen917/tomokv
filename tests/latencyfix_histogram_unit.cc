// Deterministic numeric agreement with Redis's HDR dependency. No server or clocks.
#include "src/cmd/latency_tracking.cc"
extern "C" {
#include "hdr_histogram.h"
}
#include <cstdlib>
#include <cstdio>
extern "C" {
void* zmalloc(size_t n) { return std::malloc(n); }
void* zcalloc_num(size_t n, size_t size) { return std::calloc(n, size); }
void* zrealloc(void* p, size_t n) { return std::realloc(p, n); }
void zfree(void* p) { std::free(p); }
}
int main() {
    for (unsigned shape = 0; shape < 4; ++shape) {
        tomo::Histogram actual;
        hdr_histogram* oracle = nullptr;
        if (hdr_init(1, 1000000000, 2, &oracle)) return 1;
        uint64_t random = 1;
        for (unsigned i = 0; i < 10000; ++i) {
            random = random * 6364136223846793005ULL + 1442695040888963407ULL;
            uint64_t value = shape == 0 ? i : shape == 1 ? random % 2000000000 :
                             shape == 2 ? (uint64_t{1} << (i % 31)) : 1000000000;
            value = std::clamp(value, uint64_t{1}, uint64_t{1000000000});
            actual.add(value);
            if (!hdr_record_value(oracle, value)) return 2;
        }
        for (unsigned p = 0; p <= 100000; ++p) {
            const double percentile = double(p) / 1000;
            const uint64_t expected = hdr_value_at_percentile(oracle, percentile);
            if (actual.percentile(percentile) != expected) {
                std::fprintf(stderr, "percentile shape=%u p=%f actual=%llu expected=%llu\n",
                    shape, percentile, (unsigned long long)actual.percentile(percentile),
                    (unsigned long long)expected);
                return 3;
            }
        }
        std::vector<std::pair<uint64_t, uint64_t>> expected;
        hdr_iter iterator;
        hdr_iter_log_init(&iterator, oracle, 1024, 2);
        int64_t previous = 0;
        while (hdr_iter_next(&iterator)) {
            if (iterator.cumulative_count > previous)
                expected.emplace_back(iterator.highest_equivalent_value / 1000,
                                      iterator.cumulative_count);
            previous = iterator.cumulative_count;
        }
        if (actual.cdf() != expected) {
            std::fprintf(stderr, "CDF shape=%u differs\n", shape);
            for (const auto& [key, count] : actual.cdf())
                std::fprintf(stderr, "actual %llu %llu\n", (unsigned long long)key, (unsigned long long)count);
            for (const auto& [key, count] : expected)
                std::fprintf(stderr, "oracle %llu %llu\n", (unsigned long long)key, (unsigned long long)count);
            return 4;
        }
        hdr_close(oracle);
    }
    std::puts("PASS four distributions, 400004 quantile checks and exact HDR CDFs");
}
