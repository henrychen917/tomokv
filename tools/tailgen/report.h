#pragma once

#include "histogram.h"

#include <iomanip>
#include <ostream>

namespace tailgen {

inline void json_histogram(std::ostream& out, const Histogram& histogram) {
    out << "{\"count\":" << histogram.count() << ",\"mean_ms\":" << histogram.mean_ms()
        << ",\"p50_ms\":" << histogram.percentile_ms(50000) << ",\"p90_ms\":" << histogram.percentile_ms(90000)
        << ",\"p99_ms\":" << histogram.percentile_ms(99000) << ",\"p999_ms\":" << histogram.percentile_ms(99900)
        << ",\"p9999_ms\":" << histogram.percentile_ms(99990) << ",\"max_ms\":" << histogram.max_ms() << '}';
}

// This is the harness contract: exactly these eleven top-level fields. Keep
// diagnostics (including pacing lag, drain and backpressure) on stderr only.
inline void write_json(std::ostream& out, const Histogram& short_latency, const Histogram& long_latency,
                       uint64_t window_ns, uint64_t outstanding_max, double over_fraction) {
    Histogram combined = short_latency;
    combined.merge(long_latency);
    const double window = static_cast<double>(window_ns) / 1e9;
    out << std::setprecision(12) << "{\"rate\":" << static_cast<double>(combined.count()) / window
        << ",\"latency_ms\":" << combined.mean_ms() << ",\"p999_ms\":" << short_latency.percentile_ms(99900)
        << ",\"long_p999_ms\":" << long_latency.percentile_ms(99900)
        << ",\"short_count\":" << short_latency.count() << ",\"long_count\":" << long_latency.count() << ",\"short\":";
    json_histogram(out, short_latency);
    out << ",\"long\":";
    json_histogram(out, long_latency);
    out << ",\"outstanding_max\":" << outstanding_max << ",\"over_max_outstanding_fraction\":" << over_fraction
        << ",\"window_seconds\":" << window << "}\n";
}

} // namespace tailgen
