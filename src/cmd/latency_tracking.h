// LAT-HIST-1: cold, owner-private Redis 7.4 command latency histograms.
#pragma once
#include <cstdint>
#include <string>
#include <vector>

namespace tomo {
class Op;
struct Config;

void latency_tracking_record(uint32_t executor, const Op& op, uint64_t duration_ns);
void latency_tracking_histogram(Op& op);
void latency_tracking_info(std::string& out, const std::vector<double>& percentiles, bool enabled);
void latency_tracking_reset();
uint64_t latency_tracking_allocated_histograms();
} // namespace tomo
