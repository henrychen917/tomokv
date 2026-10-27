// Independently implemented HDR-compatible indexing: 1 ns..1 s, two significant
// decimal digits (128 subdivisions per power of two). No Redis source is used.
// Request writers touch only their physical executor's cache-aligned store.
// Readers merge under each store's lock; keys/shards never name these stores,
// so shard migration has no histogram ownership to transfer.
#include "latency_tracking.h"
#include "cmdmeta.h"
#include "command.h"
#include "slowlog.h"
#include "blocking.h"
#include "multi.h"
#include "xshard.h"
#include "../core/server.h"
#include "../core/ex_loop.h"
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
        const uint64_t rank = std::max(uint64_t{1}, uint64_t((p / 100) * double(calls) + .5));
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
    std::map<const Op*, uint64_t> pending;
    // Nested Ops are stack objects. Keep metadata and duration, never their
    // addresses, until the outer script's accepted attempt retires.
    std::map<const Op*, std::vector<std::pair<uint32_t, uint64_t>>> script_children;
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
// A slice begun before the last disabling CONFIG cannot be resurrected by a
// subsequent yes. This is cold tracking state, outside every locked layout.
std::atomic<uint64_t> disabled_cut_ns{0};
void record_generation(uint32_t executor, const Op& op, uint64_t ns, uint64_t cut);
#ifdef TOMO_LATENCY_SCAN_WITNESS
uint64_t latency_scan_slots = 0;
inline void note_latency_slot() { ++latency_scan_slots; }
#else
inline void note_latency_slot() {}
#endif
Histograms collect() {
    Histograms result;
    for (auto& slot : stores) {
        note_latency_slot();
        auto* value = slot.value.load(std::memory_order_acquire);
        if (!value) continue;
        std::lock_guard lock(value->mutex);
        for (const auto& [id, histogram] : value->values) result[id].merge(histogram);
    }
    return result;
}
void retire_script_children(ExecutorHistograms& local, const Op& op) {
    const auto row = local.script_children.find(&op);
    if (row == local.script_children.end()) return;
    for (const auto& [id, ns] : row->second) local.values[id].add((ns / 1000) * 1000);
    local.script_children.erase(row);
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
                    int64_t ms, const SlowlogArm& arm, bool exact, uint64_t started) {
    // Disabling CONFIG SET must not insert itself after disabling the feature.
    if (!op.has_scatter_state() && !op.has_multi_state() && !op.has_blocking_state())
        if (auto* server = command_server(); server && server->latency_tracking()) {
            const uint64_t cut = disabled_cut_ns.load(std::memory_order_acquire);
            // A delayed callback cannot reconstruct its beginning from a new
            // clock read minus the old duration: no/yes may occupy that gap.
            if (started > cut) record_generation(executor, op, ns, cut);
        }
    slowlog_record(executor, client, op, ns, ms, arm, exact, started);
}
}
namespace {
ScatterTaskResult execute_scatter(const Task& task, Shard& shard, Op& op, uint32_t executor) {
    const uint64_t started = now_ns();
    const auto result = xshard_execute(task, shard, op, executor);
    latency_tracking_part(executor, op, started);
    return result;
}
ScatterTaskResult execute_watched(const Task& task, Shard& shard, Op& op, uint32_t executor) {
    const uint64_t started = now_ns();
    const auto result = watch_execute_scatter(task, shard, op, executor);
    latency_tracking_part(executor, op, started);
    return result;
}
void retire_scatter(Server& server, ThreadCtx& self, Ring& ring, Client& client, Op& op,
                    ScatterArenaPool& pool, uint32_t owner_io, void* context,
                    void (*release)(void*, int32_t, const char*), void (*suppressed)(void*)) {
    latency_tracking_retire(self.id(), op);
    xshard_retire(server, self, ring, client, op, pool, owner_io, context, release, suppressed);
}
void retire_blocking(Server& server, Client& client, Op& op, ThreadCtx& self) {
    latency_tracking_retire(self.id(), op);
    blocking_retire(server, client, op, self);
}
void retire_multi(IoLoop& loop, Client& client, Op& op) {
    latency_tracking_retire(client.ifid_thread(), op);
    multi_retire_entry(loop, client, op);
}
}
thread_local constinit LatencyScatterExecutor latency_xshard_execute = xshard_execute;
thread_local constinit LatencyScatterExecutor latency_watch_execute = watch_execute_scatter;
thread_local constinit LatencyScatterRetirer latency_xshard_retire = xshard_retire;
thread_local constinit LatencyBlockingRetirer latency_blocking_retire = blocking_retire;
thread_local constinit LatencyMultiRetirer latency_multi_retire = multi_retire_entry;
thread_local constinit SlowlogRecorder slowlog_recorder = slowlog_record;
void latency_tracking_bind(bool enabled, uint32_t* escalation) {
    slowlog_recorder = enabled ? record_tracked : slowlog_record;
    latency_xshard_execute = enabled ? execute_scatter : xshard_execute;
    latency_watch_execute = enabled ? execute_watched : watch_execute_scatter;
    latency_xshard_retire = enabled ? retire_scatter : xshard_retire;
    latency_blocking_retire = enabled ? retire_blocking : blocking_retire;
    latency_multi_retire = enabled ? retire_multi : multi_retire_entry;
    if (escalation) {
        if (enabled) *escalation = UINT32_MAX;
        else if (*escalation > kSlowlogEscalateBatches) *escalation = 0;
    }
}

namespace {
thread_local LatencyTrackingPart* active_part = nullptr;
}
LatencyTrackingPart::LatencyTrackingPart(uint32_t owner, const Op* command)
    : executor(owner), op(command), started(0), previous(active_part) {
    if (command && previous && previous->op == command) previous->finish();
    if (command) started = latency_tracking_start();
    active_part = this;
}
LatencyTrackingPart::~LatencyTrackingPart() {
    finish();
    active_part = previous;
}
void LatencyTrackingPart::finish() {
    if (started) {
        const uint64_t begin = started;
        started = 0;
        latency_tracking_part(executor, *op, begin);
    }
}
void latency_tracking_pause(const Op& op) {
    // A direct wake may nest inside the initial probe of the SAME operation.
    // Stop every matching slice before its completion can release the Op.
    for (auto* part = active_part; part; part = part->previous)
        if (part->op == &op) part->finish();
}
void latency_tracking_part(uint32_t executor, const Op& op, uint64_t started) {
    if (!started) return;
    // CONFIG's shard-0 handler owns the enabling sample, including repeated yes.
    // Its other fragments can observe different configuration generations.
    if (op.cmd_name().eq_icase("config") && op.argc() > 3 && op.arg(1).eq_icase("set"))
        for (uint32_t i = 2; i + 1 < op.argc(); i += 2)
            if (op.arg(i).eq_icase("latency-tracking") && op.arg(i + 1).eq_icase("yes"))
                return;
    const uint64_t duration = now_ns() - started;
    if (auto* server = command_server(); !server || !server->latency_tracking()) return;
    auto& local = store(executor);
    std::lock_guard lock(local.mutex);
    if (auto* server = command_server(); !server || !server->latency_tracking()) return;
    if (started <= disabled_cut_ns.load(std::memory_order_acquire)) return;
    local.pending[&op] += duration;
}
void latency_tracking_retire(uint32_t executor, const Op& op) {
    // CONFIG's off transition clears every pending slice before returning.
    // Disabled command hooks must never walk the physical executor slots.
    if (auto* server = command_server(); !server || !server->latency_tracking()) return;
    const uint64_t cut = disabled_cut_ns.load(std::memory_order_acquire);
    uint64_t duration = 0;
    bool found = false;
    // All participants have published completion before ROB retirement. Histogram
    // writes remain owner-private; only a resumable command's private slices join here.
    for (auto& slot : stores) {
        note_latency_slot();
        auto* local = slot.value.load(std::memory_order_acquire);
        if (!local) continue;
        std::lock_guard lock(local->mutex);
        if (auto* server = command_server(); server && server->latency_tracking())
            retire_script_children(*local, op);
        else local->script_children.erase(&op);
        const auto row = local->pending.find(&op);
        if (row == local->pending.end()) continue;
        duration += row->second;
        found = true;
        local->pending.erase(row);
    }
    if (found) record_generation(executor, op, duration, cut);
}
void latency_tracking_retry(const Op& previous, const Op& next) {
    // Disabling tracking clears all pending slices. The default-off retry path
    // must not scan every physical executor's empty histogram slot.
    if (auto* server = command_server(); !server || !server->latency_tracking()) return;
    // Both attempts represent the same logical child. The old owners have all
    // joined; new owners may already accumulate slices, but only IO can retire
    // the replacement. Reuse the node so a retry needs no extra allocation.
    for (auto& slot : stores) {
        note_latency_slot();
        auto* local = slot.value.load(std::memory_order_acquire);
        if (!local) continue;
        std::lock_guard lock(local->mutex);
        auto node = local->pending.extract(&previous);
        if (node.empty()) continue;
        node.key() = &next;
        auto inserted = local->pending.insert(std::move(node));
        if (!inserted.inserted) inserted.position->second += inserted.node.mapped();
    }
}
void latency_tracking_forget(const Op& op) {
    // CONFIG's off transition clears every pending slice before returning.
    // Disabled command hooks must never walk the physical executor slots.
    if (auto* server = command_server(); !server || !server->latency_tracking()) return;
    for (auto& slot : stores) {
        note_latency_slot();
        auto* local = slot.value.load(std::memory_order_acquire);
        if (!local) continue;
        std::lock_guard lock(local->mutex);
        local->pending.erase(&op);
        local->script_children.erase(&op);
    }
}
void latency_tracking_forget_client(Client& client) {
    // CONFIG's off transition clears every pending slice before returning.
    // Disabled command hooks must never walk the physical executor slots.
    if (auto* server = command_server(); !server || !server->latency_tracking()) return;
    for (auto& slot : stores) {
        note_latency_slot();
        auto* local = slot.value.load(std::memory_order_acquire);
        if (!local) continue;
        std::lock_guard lock(local->mutex);
        for (uint32_t i = 0; i < kRobWindow; ++i) {
            local->pending.erase(&client.rob().at(i));
            local->script_children.erase(&client.rob().at(i));
        }
    }
}
void latency_tracking_discard_pending() {
    disabled_cut_ns.store(now_ns(), std::memory_order_release);
    for (auto& slot : stores) {
        note_latency_slot();
        auto* local = slot.value.load(std::memory_order_acquire);
        if (!local) continue;
        std::lock_guard lock(local->mutex);
        local->pending.clear();
        local->script_children.clear();
    }
}

void latency_tracking_script_begin(const Op& parent) {
    if (auto* server = command_server(); !server || !server->latency_tracking()) return;
    // OCC certification can replay even disjoint scripts. Only the last
    // activation's nested calls belong to the externally visible execution;
    // the parent's active slices still include all retry work.
    for (auto& slot : stores) {
        note_latency_slot();
        auto* local = slot.value.load(std::memory_order_acquire);
        if (!local) continue;
        std::lock_guard lock(local->mutex);
        local->script_children.erase(&parent);
    }
}
void latency_tracking_script_part(uint32_t executor, const Op& parent,
                                  const Op& child, uint64_t started) {
    if (!started) return;
    const uint64_t duration = now_ns() - started;
    if (auto* server = command_server(); !server || !server->latency_tracking()) return;
    const auto* metadata = command_metadata_resolve(const_cast<Op&>(child), 0);
    if (!metadata || !command_metadata_arity_ok(*metadata, child.argc())) return;
    auto& local = store(executor);
    std::lock_guard lock(local.mutex);
    if (auto* server = command_server(); !server || !server->latency_tracking()) return;
    if (started <= disabled_cut_ns.load(std::memory_order_acquire)) return;
    local.script_children[&parent].emplace_back(command_metadata_index(*metadata), duration);
}

uint64_t latency_tracking_start() {
    return slowlog_recorder != slowlog_record ? now_ns() : 0;
}
void latency_tracking_finish(uint32_t executor, const Op& op, uint64_t started) {
    if (started) {
        const uint64_t duration = now_ns() - started;
        const uint64_t cut = disabled_cut_ns.load(std::memory_order_acquire);
        if (started > cut) record_generation(executor, op, duration, cut);
    }
}

namespace {
void record_generation(uint32_t executor, const Op& op, uint64_t duration_ns, uint64_t cut) {
    if (auto* server = command_server(); !server || !server->latency_tracking()) return;
    if (executor >= stores.size() || !op.spec) return;
    // The metadata resolver only reads Op; its existing API predates const use.
    // Unknown container children are rejected commands, not parent executions.
    const auto* metadata = command_metadata_resolve(const_cast<Op&>(op), 0);
    if (!metadata || !command_metadata_arity_ok(*metadata, op.argc())) return;
    auto& local = store(executor);
    std::lock_guard lock(local.mutex);
    if (auto* server = command_server(); !server || !server->latency_tracking()) return;
    if (cut != disabled_cut_ns.load(std::memory_order_acquire)) return;
    retire_script_children(local, op);
    // Redis's timer produces integral microseconds before conversion to nanoseconds.
    local.values[command_metadata_index(*metadata)].add((duration_ns / 1000) * 1000);
}

} // namespace
void latency_tracking_record(uint32_t executor, const Op& op, uint64_t duration_ns) {
    record_generation(executor, op, duration_ns,
                      disabled_cut_ns.load(std::memory_order_acquire));
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
        note_latency_slot();
        auto* value = slot.value.load(std::memory_order_acquire);
        if (!value) continue;
        std::lock_guard lock(value->mutex);
        value->values.clear();
    }
}
uint64_t latency_tracking_allocated_histograms() {
    uint64_t count = 0;
    for (auto& slot : stores) {
        note_latency_slot();
        auto* value = slot.value.load(std::memory_order_acquire);
        if (!value) continue;
        std::lock_guard lock(value->mutex);
        count += value->values.size();
    }
    return count;
}

// Instantiate tracked executor bodies only here. Keeping them out of the normal
// executor translation units preserves their off-path inlining decisions.
template<bool Fused>
template<bool IofusedPrivateQueue, bool ReadLocalNoEvict>
bool ExLoopT<Fused>::execute_latency(const Task& t) {
    constexpr bool Timed = true;
    constexpr bool LatencyTracking = true;
#include "../core/ex_execute.inc"
}
template<bool Fused>
template<bool IofusedPrivateQueue>
void ExLoopT<Fused>::exec_batch_latency(ExLoopT* loop, const Task* batch, uint32_t n) {
    Server::ClientWorkScope client_work(*loop->srv_, loop->self_->id());
    const SlowlogArm arm = loop->slowlog_arm_;
    slowlog_note_batch_timed();
    loop->flush_xshard_commits_timed();
    for (uint32_t i = 0; i < n; ++i) {
        Client* client = batch[i].client;
        SlowlogTiming timing(client ? &client->rob().at(batch[i].op_id) : nullptr,
            client ? client->id() : 0, loop->self_->id(), now_ns(),
            loop->cached_now_ms_, arm);
        const bool okay = loop->template execute_latency<IofusedPrivateQueue>(batch[i]);
        loop->flush_xshard_commits_timed();
        if (okay) continue;
        loop->xshard_retries_.push_back(batch[i]);
        for (uint32_t j = i + 1; j < n; ++j) loop->ordered_deferred_.push_back(batch[j]);
        return;
    }
}
template<bool Fused>
template<bool IofusedPrivateQueue>
bool ExLoopT<Fused>::execute_resumed_latency(const Task& task) {
    Client* client = task.client;
    SlowlogTiming timing(client ? &client->rob().at(task.op_id) : nullptr,
                         client ? client->id() : 0, self_->id(), now_ns(),
                         cached_now_ms_, slowlog_arm_);
    const bool result = execute_latency<IofusedPrivateQueue>(task);
    flush_xshard_commits_timed();
    return result;
}
template void ExLoopT<false>::exec_batch_latency<false>(ExLoopT*, const Task*, uint32_t);
template void ExLoopT<true>::exec_batch_latency<false>(ExLoopT*, const Task*, uint32_t);
template void ExLoopT<true>::exec_batch_latency<true>(ExLoopT*, const Task*, uint32_t);
template bool ExLoopT<false>::execute_resumed_latency<false>(const Task&);
template bool ExLoopT<true>::execute_resumed_latency<false>(const Task&);
template bool ExLoopT<true>::execute_resumed_latency<true>(const Task&);
} // namespace tomo
