// Independently implemented HDR-compatible indexing: 1 ns..1 s, two significant
// decimal digits (128 subdivisions per power of two). No Redis source is used.
// Request writers touch only their physical executor's cache-aligned store.
// Readers merge under each store's lock; keys/shards never name these stores,
// so shard migration has no histogram ownership to transfer.
#include "latency_tracking.h"
#include "cmdmeta.h"
#include "command.h"
#include "slowlog.h"
#include "../core/server.h"
#include "../exec/op.h"
#include "../core/thread.h"
#include "../net/resp.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <bit>
#include <cmath>
#include <cstdio>
#include <map>
#include <memory>
#include <mutex>

namespace tomo {
namespace {
constexpr uint64_t kMaximum = 1000000000;
constexpr size_t kBins = 3072;

struct Histogram {
    std::array<uint64_t, kBins> bins{};
    uint64_t calls = 0;
    static size_t index(uint64_t ns) {
        const unsigned shift = std::bit_width(ns) > 8 ? std::bit_width(ns) - 8 : 0;
        return (shift << 7) + (ns >> shift);
    }
    static uint64_t low(size_t i) {
        if (i < 256) return i;
        return uint64_t{128 + (i & 127)} << ((i >> 7) - 1);
    }
    static uint64_t high(size_t i) {
        return low(i) + (i < 256 ? 0 : (uint64_t{1} << ((i >> 7) - 1)) - 1);
    }
    void add(uint64_t ns) { ++bins[index(std::clamp(ns, uint64_t{1}, kMaximum))]; ++calls; }
    void merge(const Histogram& other) {
        calls += other.calls;
        for (size_t i = 0; i < kBins; ++i) bins[i] += other.bins[i];
    }
    uint64_t percentile(double p) const {
        const uint64_t rank = std::max(uint64_t{1}, uint64_t(p * double(calls) / 100 + .5));
        uint64_t n = 0;
        for (size_t i = 0; i < kBins; ++i) {
            n += bins[i];
            if (n >= rank) return p == 0 ? low(i) : high(i);
        }
        return 0;
    }
    std::vector<std::pair<uint64_t, uint64_t>> cdf() const {
        std::vector<std::pair<uint64_t, uint64_t>> out;
        uint64_t cumulative = 0, previous = 0;
        size_t i = 0;
        for (uint64_t boundary = 1024; cumulative < calls; boundary *= 2) {
            const size_t last = std::min(index(boundary), kBins - 1);
            while (i <= last) cumulative += bins[i++];
            if (cumulative != previous) out.emplace_back(high(last) / 1000, cumulative);
            previous = cumulative;
        }
        return out;
    }
};
using Histograms = std::map<uint32_t, Histogram>;
struct alignas(64) ExecutorHistograms {
    std::mutex mutex;
    Histograms values;
};
struct Slot { alignas(64) std::atomic<ExecutorHistograms*> value{nullptr}; };
std::array<Slot, kMaxThreads> stores{};
struct Cleanup {
    ~Cleanup() { for (auto& slot : stores) delete slot.value.load(std::memory_order_relaxed); }
} cleanup;

ExecutorHistograms& store(uint32_t executor) {
    auto& slot = stores.at(executor).value;
    auto* value = slot.load(std::memory_order_acquire);
    if (!value) {
        auto fresh = std::make_unique<ExecutorHistograms>();
        value = fresh.get();
        // Only this executor creates its store; readers never construct one.
        slot.store(fresh.release(), std::memory_order_release);
    }
    return *value;
}
Histograms collect() {
    Histograms result;
    for (auto& slot : stores) {
        auto* value = slot.value.load(std::memory_order_acquire);
        if (!value) continue;
        std::lock_guard lock(value->mutex);
        for (const auto& [id, histogram] : value->values) result[id].merge(histogram);
    }
    return result;
}
void reply_histogram(Op& op, uint32_t id, const Histogram& histogram) {
    const auto* metadata = command_metadata_at(id);
    reply_bulk(op.sink(), command_metadata_name(*metadata));
    reply_map_header(op.sink(), 2, op.resp3());
    reply_bulk(op.sink(), Slice("calls"));
    reply_int(op.sink(), histogram.calls);
    reply_bulk(op.sink(), Slice("histogram_usec"));
    const auto cdf = histogram.cdf();
    reply_map_header(op.sink(), cdf.size(), op.resp3());
    for (const auto& [bucket, count] : cdf) {
        reply_int(op.sink(), bucket);
        reply_int(op.sink(), count);
    }
}
} // namespace

namespace {
void record_tracked(uint32_t executor, uint64_t client, const Op& op, uint64_t ns,
                    int64_t ms, const SlowlogArm& arm, bool exact) {
    // Disabling CONFIG SET must not insert itself after disabling the feature.
    if (auto* server = command_server(); server && server->latency_tracking())
        latency_tracking_record(executor, op, ns);
    slowlog_record(executor, client, op, ns, ms, arm, exact);
}
}
thread_local constinit SlowlogRecorder slowlog_recorder = slowlog_record;
void latency_tracking_bind(bool enabled, uint32_t* escalation) {
    slowlog_recorder = enabled ? record_tracked : slowlog_record;
    if (escalation) {
        if (enabled) *escalation = UINT32_MAX;
        else if (*escalation > kSlowlogEscalateBatches) *escalation = 0;
    }
}

uint64_t latency_tracking_start() {
    return slowlog_recorder != slowlog_record ? now_ns() : 0;
}
void latency_tracking_finish(uint32_t executor, const Op& op, uint64_t started) {
    if (started) {
        const uint64_t duration = now_ns() - started;
        if (auto* server = command_server(); server && server->latency_tracking())
            latency_tracking_record(executor, op, duration);
    }
}

void latency_tracking_record(uint32_t executor, const Op& op, uint64_t duration_ns) {
    if (executor >= stores.size() || !op.spec) return;
    const auto* metadata = op.argc() > 1 ? command_metadata_subcommand(*op.spec, op.arg(1)) : nullptr;
    if (!metadata) metadata = command_metadata_for(*op.spec);
    if (!metadata) return;
    auto& local = store(executor);
    std::lock_guard lock(local.mutex);
    // Redis's timer produces integral microseconds before conversion to nanoseconds.
    local.values[command_metadata_index(*metadata)].add((duration_ns / 1000) * 1000);
}

void latency_tracking_histogram(Op& op) {
    const auto all = collect();
    std::vector<std::pair<uint32_t, const Histogram*>> selected;
    if (op.argc() == 2) {
        for (const auto& [id, histogram] : all) selected.emplace_back(id, &histogram);
    } else for (uint32_t arg = 2; arg < op.argc(); ++arg) {
        const auto* requested = command_metadata_lookup(op.arg(arg));
        if (!requested) continue;
        const auto name = command_metadata_name(*requested);
        for (const auto& [id, histogram] : all) {
            const auto candidate = command_metadata_name(*command_metadata_at(id));
            if (candidate.sv() == name.sv() ||
                (candidate.n > name.n && candidate.p[name.n] == '|' &&
                 candidate.sv().substr(0, name.n) == name.sv()))
                selected.emplace_back(id, &histogram);
        }
    }
    reply_map_header(op.sink(), selected.size(), op.resp3());
    for (const auto& [id, histogram] : selected) reply_histogram(op, id, *histogram);
}

void latency_tracking_info(std::string& out, const std::vector<double>& percentiles, bool enabled) {
    out += "# Latencystats\r\n";
    if (!enabled) return;
    for (const auto& [id, histogram] : collect()) {
        const auto name = command_metadata_name(*command_metadata_at(id));
        out += "latency_percentiles_usec_";
        out.append(name.p, name.n);
        out += ':';
        for (size_t i = 0; i < percentiles.size(); ++i) {
            if (i) out += ',';
            char key[128], value[128];
            int n = std::snprintf(key, sizeof(key), "%f", percentiles[i]);
            while (n > 0 && key[n - 1] == '0') --n;
            if (n > 0 && key[n - 1] == '.') --n;
            out += 'p';
            out.append(key, n);
            std::snprintf(value, sizeof(value), "=%.3f", double(histogram.percentile(percentiles[i])) / 1000);
            out += value;
        }
        out += "\r\n";
    }
}

void latency_tracking_reset() {
    for (auto& slot : stores) {
        auto* value = slot.value.load(std::memory_order_acquire);
        if (!value) continue;
        std::lock_guard lock(value->mutex);
        value->values.clear();
    }
}
uint64_t latency_tracking_allocated_histograms() {
    uint64_t count = 0;
    for (auto& slot : stores) {
        auto* value = slot.value.load(std::memory_order_acquire);
        if (!value) continue;
        std::lock_guard lock(value->mutex);
        count += value->values.size();
    }
    return count;
}
} // namespace tomo
