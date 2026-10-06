#include "info_stats.h"

#include "../core/signal.h"
#include "../core/thread.h"
#include "command.h"

#include <algorithm>
#include <array>
#include <mutex>

namespace tomo {
namespace {

constexpr uint64_t kSampleMinNs = 100000000ull;
constexpr size_t kSampleWindow = 8;

struct InfoStatsState {
    std::mutex mu;
    uint64_t last_sample_ns = 0;
    uint64_t last_operations = 0;
    std::array<uint64_t, kSampleWindow> rates{};
    uint64_t rate_sum = 0;
    uint64_t published_rate = 0;
    uint64_t memory_peak = 0;
    size_t rate_cursor = 0;
    size_t rate_count = 0;
};

InfoStatsState g_info_stats;
thread_local const Op* rejected_reply = nullptr;

// Parse only the bytes already emitted. Array/map headers need no recursion: their
// children follow in wire order. Bulk payloads are skipped, so a value containing
// "-ERR" cannot suppress a later real error. This pays no reset/store on success.
bool has_error(const char* first, size_t first_size, const char* second, size_t second_size) {
    const size_t size = first_size + second_size;
    auto byte = [&](size_t i) { return i < first_size ? first[i] : second[i - first_size]; };
    for (size_t pos = 0; pos < size;) {
        const char kind = byte(pos++);
        if (kind == '-') return true;
        const size_t begin = pos;
        while (pos + 1 < size && !(byte(pos) == '\r' && byte(pos + 1) == '\n')) ++pos;
        if (pos + 1 >= size) return false;
        if (kind == '$' || kind == '!' || kind == '=') {
            if (begin < pos && byte(begin) != '-') {
                size_t length = 0;
                for (size_t i = begin; i < pos; ++i) {
                    if (byte(i) < '0' || byte(i) > '9' || length > size) return false;
                    length = length * 10 + (byte(i) - '0');
                }
                pos += 2;
                if (length > size - pos || size - pos - length < 2) return false;
                pos += length + 2;
                continue;
            }
        }
        pos += 2;
    }
    return false;
}

}  // namespace

RejectedReplyScope::RejectedReplyScope(const Op& op) noexcept : previous_(rejected_reply) {
    rejected_reply = &op;
}
RejectedReplyScope::~RejectedReplyScope() noexcept { rejected_reply = previous_; }
bool RejectedReplyScope::contains(const Op& op) noexcept { return rejected_reply == &op; }

void command_note_error(Op& op, const char* prior, size_t prior_size) noexcept {
    if (!op.spec || RejectedReplyScope::contains(op)) return;
    ThreadCtx* thread = ThreadCtx::command_stats_thread();
    // Serverless command fixtures and explicitly bound admin contexts use the
    // same thread-private counter plane without booting a worker.
    if (!thread) thread = command_local_thread();
    if (!thread) return;
    if (has_error(op.direct, op.direct_len, op.reply.data(), op.reply.size()) ||
        (prior_size && has_error(prior, prior_size, nullptr, 0))) return;
    thread->note_command_failed(op.spec->id);
}

void Op::Sink::begin_error() noexcept { command_note_error(op_); }
void Op::Sink::append_error(const char* text, size_t size) noexcept {
    begin_error();
    append(text, size);
}

uint64_t info_stats_sample_ops(uint64_t operations) {
    const uint64_t sampled_ns = now_ns();
    std::lock_guard<std::mutex> lock(g_info_stats.mu);
    if (!g_info_stats.last_sample_ns) {
        g_info_stats.last_sample_ns = sampled_ns;
        g_info_stats.last_operations = operations;
        return 0;
    }
    const uint64_t elapsed = sampled_ns - g_info_stats.last_sample_ns;
    if (elapsed < kSampleMinNs) return g_info_stats.published_rate;

    const uint64_t delta = operations >= g_info_stats.last_operations
        ? operations - g_info_stats.last_operations : 0;
    const uint64_t rate = static_cast<uint64_t>(
        (static_cast<unsigned __int128>(delta) * 1000000000ull) / elapsed);
    if (g_info_stats.rate_count == kSampleWindow)
        g_info_stats.rate_sum -= g_info_stats.rates[g_info_stats.rate_cursor];
    else
        g_info_stats.rate_count++;
    g_info_stats.rates[g_info_stats.rate_cursor] = rate;
    g_info_stats.rate_sum += rate;
    g_info_stats.rate_cursor = (g_info_stats.rate_cursor + 1) % kSampleWindow;
    g_info_stats.published_rate = g_info_stats.rate_sum / g_info_stats.rate_count;
    g_info_stats.last_sample_ns = sampled_ns;
    g_info_stats.last_operations = operations;
    return g_info_stats.published_rate;
}

uint64_t info_stats_observe_memory(uint64_t used_memory) {
    std::lock_guard<std::mutex> lock(g_info_stats.mu);
    g_info_stats.memory_peak = std::max(g_info_stats.memory_peak, used_memory);
    return g_info_stats.memory_peak;
}

void info_stats_reset(uint64_t operations, uint64_t used_memory) {
    std::lock_guard<std::mutex> lock(g_info_stats.mu);
    g_info_stats.last_sample_ns = now_ns();
    g_info_stats.last_operations = operations;
    g_info_stats.rates.fill(0);
    g_info_stats.rate_sum = 0;
    g_info_stats.published_rate = 0;
    g_info_stats.memory_peak = used_memory;
    g_info_stats.rate_cursor = 0;
    g_info_stats.rate_count = 0;
}

}  // namespace tomo
