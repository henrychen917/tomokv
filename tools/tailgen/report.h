#pragma once

#include "histogram.h"

#include <array>
#include <cstdio>
#include <iomanip>
#include <ostream>
#include <string>

namespace tailgen {

inline void json_histogram(std::ostream& out, const Histogram& histogram) {
    out << "{\"count\":" << histogram.count() << ",\"mean_ms\":" << histogram.mean_ms()
        << ",\"p50_ms\":" << histogram.percentile_ms(50000) << ",\"p90_ms\":" << histogram.percentile_ms(90000)
        << ",\"p99_ms\":" << histogram.percentile_ms(99000) << ",\"p999_ms\":" << histogram.percentile_ms(99900)
        << ",\"p9999_ms\":" << histogram.percentile_ms(99990) << ",\"max_ms\":" << histogram.max_ms() << '}';
}

// Attainment ladder: the share of a class's requests completing at or below
// each fixed latency level (Histogram::count_at_or_below_ms documents the bucket
// rounding). The label is the JSON key and the stderr tag.
struct AttainLevel { const char* label; double ms; };
inline constexpr std::array<AttainLevel, 10> attain_ladder{{
    {"0.05", 0.05}, {"0.1", 0.1}, {"0.2", 0.2}, {"0.5", 0.5}, {"1", 1},
    {"2", 2}, {"5", 5}, {"10", 10}, {"20", 20}, {"50", 50},
}};

// part/total as a percentage TRUNCATED (not rounded) to three decimals, in exact
// integer arithmetic: 100.000 means every request met the level, and decimal
// rounding never lifts a level above what was measured. No samples: 0.000.
inline std::string percent_floor3(uint64_t part, uint64_t total) {
    const uint64_t milli_pct = total ? static_cast<uint64_t>(static_cast<unsigned __int128>(part) * 100000 / total) : 0;
    char text[32];
    std::snprintf(text, sizeof text, "%llu.%03llu", static_cast<unsigned long long>(milli_pct / 1000),
                  static_cast<unsigned long long>(milli_pct % 1000));
    return text;
}

// {"0.05":12.345,...,"50":100.000}: percent of the class at or below each level.
inline void json_attainment(std::ostream& out, const Histogram& histogram) {
    char separator = '{';
    for (const auto& level : attain_ladder) {
        out << separator << '"' << level.label << "\":"
            << percent_floor3(histogram.count_at_or_below_ms(level.ms), histogram.count());
        separator = ',';
    }
    out << '}';
}

// One stderr line per class: "short attain: <=0.05ms=12.345% ... <=50ms=100.000%".
inline void human_attainment(std::ostream& out, const char* name, const Histogram& histogram) {
    out << name << " attain:";
    for (const auto& level : attain_ladder)
        out << " <=" << level.label << "ms=" << percent_floor3(histogram.count_at_or_below_ms(level.ms), histogram.count())
            << '%';
    out << '\n';
}

// This is the harness contract: these eleven top-level fields, unchanged and in
// this order, then "attain_pct" last ({"short","long","combined"} -> ladder).
// Keep diagnostics (including pacing lag, drain and backpressure) on stderr only.
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
        << ",\"window_seconds\":" << window << ",\"attain_pct\":{\"short\":";
    json_attainment(out, short_latency);
    out << ",\"long\":";
    json_attainment(out, long_latency);
    out << ",\"combined\":";
    json_attainment(out, combined);
    out << "}}\n";
}

} // namespace tailgen
