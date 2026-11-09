// Connection-buffer reclamation policy used by IoLoop::client_buffer_cron.
// Reclamation runs only on that cold cron, never on a request/retire path; forget also runs at
// close and migration.
// Read-buffer relocation requires ROB quiescence and no kernel receive pointer; output
// reclamation also excludes in-flight sends and the caller's OpenSSL plaintext reservation.
#pragma once
#include "conn.h"
#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <unordered_map>
#if defined(TOMO_JEMALLOC)
#include <jemalloc/jemalloc.h>
#elif defined(__GLIBC__)
#include <malloc.h>
#endif

namespace tomo {

// Per-IoLoop peak samples keyed by client id; the connection owner calls visit/forget.
// Sampling and shrinking are local; the relaxed last_purge_ms_ CAS coalesces allocator purges
// across loops, without publishing buffer state. Allocation of a new peak entry can throw;
// failed buffer reallocations retain their old allocations.
class IdleBuffers {
    // Redis 7.4 clientsCronResizeQueryBuffer / clientsCronResizeOutputBuffer:
    // 4 KiB spare, >2 seconds idle, 32 KiB active-query threshold, half-capacity
    // peak comparison, and a five-second output-peak window. Our two 512-byte
    // inline output buffers together provide Redis's 1 KiB minimum.
    struct Peak {
        size_t query_cap = 0, query = 0;
        size_t output_cap[2]{}, output[2]{};
        uint64_t output_reset_ms = 0;
        uint32_t interaction = 0;
    };
    std::unordered_map<uint64_t, Peak> peaks_;
    bool reclaimed_ = false;
    inline static std::atomic<uint64_t> last_purge_ms_{0};

public:
    void forget(uint64_t id) { peaks_.erase(id); }

    // An idle owner produces no later allocation traffic to drive jemalloc decay. Return
    // released burst pages to the OS on the same cold beat, coalesced across IO owners.
    // This changes neither decay settings nor background-thread/arena configuration.
    [[gnu::noinline, gnu::cold]] void purge_reclaimed(uint64_t now_ms) {
        if (!reclaimed_) return;
        uint64_t previous = last_purge_ms_.load(std::memory_order_relaxed);
        if (now_ms - previous < 100 ||
            !last_purge_ms_.compare_exchange_strong(previous, now_ms, std::memory_order_relaxed))
            return;
        reclaimed_ = false;
#if defined(TOMO_JEMALLOC)
        char name[64];
        std::snprintf(name, sizeof(name), "arena.%u.purge", MALLCTL_ARENAS_ALL);
        (void)mallctl(name, nullptr, nullptr, nullptr, 0);
#elif defined(__GLIBC__)
        (void)malloc_trim(0);
#endif
    }

    // Sample peaks and shrink unused allocations on the connection owner's cron pass. The caller
    // supplies receive/OpenSSL pins; ROB quiescence additionally fences worker argv/direct replies.
    // Return true to request cancellation of a pinned receive, leaving its allocation in place.
    // A failed realloc preserves storage; peak-map insertion can throw. No cross-thread publication
    // occurs here. Capacity growth and cursors capture peaks without per-receive/reply peak stores.
    [[gnu::noinline, gnu::cold]] bool visit(Client& c, uint64_t now_ms, bool read_pinned,
                                            bool output_pinned) {
        if (c.closing() || c.dead()) {
            forget(c.id());
            return false;
        }
        if (c.rcap_ == kRbufInitial && c.buf_[0].cap() == kWbufInline &&
            c.buf_[1].cap() == kWbufInline) {
            forget(c.id());
            return false;
        }
        Peak& p = peaks_[c.id()];
        const uint32_t now_s = now_ms / 1000;
        const bool idle = now_s - c.last_interaction_s() > 2;
        const bool new_activity = p.interaction != c.last_interaction_s();
        p.interaction = c.last_interaction_s();
        const size_t rest = c.rlen_ - c.rpos_;
        size_t live_query = rest;
        if (c.multibulk_pending() && c.multibulk_.bulk != UINT64_MAX)
            live_query = std::max<uint64_t>(live_query, c.multibulk_.bulk + 2);
        if (c.rcap_ > p.query_cap) p.query = c.rcap_;  // includes bursts between cron samples
        p.query_cap = c.rcap_;
        size_t target = c.rcap_;
        if (c.rcap_ - rest > 4096) {
            if (idle)
                target = std::max(kRbufInitial, rest);
            else if (c.rcap_ > 32768 && c.rcap_ / 2 > p.query)
                target = std::max({kRbufInitial, live_query, p.query});
        }
        p.query = live_query;
        bool cancel_read = false;
        if (target < c.rcap_ && c.rob_.quiesced()) {
            if (read_pinned)
                cancel_read = true;
            else {
                c.reset_rbuf_at_quiescence();
                char* resized = static_cast<char*>(std::realloc(c.rbuf_, target));
                if (resized) {
                    c.rbuf_ = resized;
                    c.rcap_ = target;
                    p.query_cap = target;
                    reclaimed_ = true;
                }
            }
        }

        if (!p.output_reset_ms) p.output_reset_ms = now_ms;
        for (unsigned i = 0; i < 2; ++i) {
            auto& b = c.buf_[i];
            const bool send = i != c.fill_;
            const size_t used = send ? (c.write_drained() ? 0 : b.size() - c.wsent_) : b.size();
            if (b.cap() > p.output_cap[i]) p.output[i] = b.cap();
            if (new_activity) p.output[i] = std::max(p.output[i], b.size());
            p.output_cap[i] = b.cap();
            // A worker can have a direct pointer into fill storage; a kernel send or OpenSSL
            // retry can pin send storage. All must be absent, independently of recv ownership.
            if (!output_pinned && !c.send_inflight_ && c.rob_.quiesced() && used == 0 &&
                b.cap() > kWbufInline && b.cap() / 2 > p.output[i]) {
                const size_t retain = std::max(kWbufInline, p.output[i] + 1);
                if (retain == kWbufInline)
                    b.shrink_to_inline();
                else {
                    char* resized = static_cast<char*>(std::realloc(b.data_, retain));
                    if (!resized) continue;  // preserve the old allocation on failure
                    b.data_ = resized;
                    b.cap_ = retain;
                    b.len_ = 0;
                }
                reclaimed_ = true;
                if (send) c.wsent_ = 0;  // reset the fully sent buffer's offset after shrinking
                p.output_cap[i] = b.cap();
            }
            if (now_ms - p.output_reset_ms >= 5000) p.output[i] = used;
        }
        if (now_ms - p.output_reset_ms >= 5000) p.output_reset_ms = now_ms;
        return cancel_read;
    }
};
}  // namespace tomo
