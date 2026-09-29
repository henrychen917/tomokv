// One captured FIFO visit: bytes OR a contiguous Done fraction, chosen by the IO owner.
#pragma once
#include <cstdio>
#include <string>
#include <type_traits>
#include "../net/conn.h"

namespace tomo::wb_rule {
inline constexpr unsigned scale = 256;

// Cold artifact selector, patched only by tools/wbland_artifacts.py. Low byte:
// default policy + 1. Bit 8: unmeasured split-AUTO probe. Bit 31: PAD A (half rule).
// Production is zero: AUTO in fused, the landed half rule in split pending measurement.
__attribute__((noinline, noclone)) inline uint32_t build_arm() {
    uint32_t word;
    asm volatile("mov $0, %0" : "=a"(word));
    return word;
}
inline int default_policy() { return int(build_arm() & 255) - 1; }
inline bool adaptive(int policy, bool fused, uint32_t arm = build_arm()) {
    return policy == -1 && (fused || (arm & (1u << 8))) && !(arm & (1u << 31));
}

// pol2-k1's window: freeze W=max(1, owned connections) for each complete block;
// combine the current and previous blocks by duration, then hold f for the next W
// passes. Two blocks provide the measured smoothing/history. Ownership changes
// affect only the next block. No decision before two blocks; a new IO tenure resets.
struct Window {
    size_t remaining = 1, width = 1;
    uint64_t wall_start = 0, idle_start = 0, previous_wall = 0, previous_idle = 0;
    uint64_t windows = 0;
    unsigned busy = 0;
    bool seeded = false, previous_valid = false;

    __attribute__((noinline)) bool close(uint64_t wall, uint64_t idle, size_t owned) {
        width = std::max<size_t>(1, owned);
        remaining = width;
        if (!seeded) {
            wall_start = wall; idle_start = idle; seeded = true;
            return false;
        }
        const uint64_t elapsed = wall - wall_start, asleep = idle - idle_start;
        wall_start = wall; idle_start = idle;
        if (!elapsed) return false;
        if (asleep > elapsed) std::abort(); // existing accounting contract
        ++windows;
        const bool ready = previous_valid;
        if (ready) {
            const unsigned __int128 total = (unsigned __int128)elapsed + previous_wall;
            const unsigned __int128 rest = (unsigned __int128)asleep + previous_idle;
            busy = unsigned((total - rest) * scale / total);
        }
        previous_wall = elapsed; previous_idle = asleep; previous_valid = true;
        return ready;
    }
    bool due() { return --remaining == 0; }
};

// INFO sees only beat publications, never the owner stack. One packet makes the
// dial/busy/active fields coherent without a reader retry or seqlock. Counters are
// independent diagnostic snapshots. Fixed policies allocate no publication rows.
struct alignas(64) Published {
    std::atomic<uint64_t> packet{0}, windows{0}, width{0};
};
struct State {
    const bool dynamic;
    unsigned fraction;
    Window window;

    explicit State(int policy, bool fused, uint32_t arm = build_arm())
        : dynamic(adaptive(policy, fused, arm)),
          fraction((arm & (1u << 31)) ? 128 : dynamic || policy == 0 ? 0 : 128) {}

    // Already-paid pass cut and idle signal; only local countdown/dial writes.
    void pass(uint64_t wall, uint64_t idle, size_t owned) {
        if (dynamic && window.due() && window.close(wall, idle, owned))
            fraction = window.busy;
    }
    void publish(Published* out, bool active = true) const {
        if (!out) return;
        const uint64_t packet = uint64_t(window.busy) | uint64_t(fraction) << 9 |
                                uint64_t(active) << 18;
        out->windows.store(window.windows, std::memory_order_relaxed);
        out->width.store(window.width, std::memory_order_relaxed);
        out->packet.store(packet, std::memory_order_relaxed);
    }
};

inline void info(std::string& body, int policy, bool fused, const Published* rows,
                 unsigned threads) {
    const uint32_t arm = build_arm();
    const State state(policy, fused, arm);
    char line[256];
    std::snprintf(line, sizeof line, "# Writeback\r\nwb_policy:%d\r\nwb_adaptive:%u\r\n"
        "wb_fixed_f256:%d\r\nwb_split_probe:%u\r\nwb_pad:%u\r\n", policy,
        unsigned(state.dynamic), state.dynamic ? -1 : int(state.fraction),
        unsigned(bool(arm & (1u << 8))), unsigned(bool(arm & (1u << 31))));
    body += line;
    for (unsigned tid = 0; rows && tid < threads; ++tid) {
        const auto& row = rows[tid];
        const uint64_t packet = row.packet.load(std::memory_order_relaxed);
        std::snprintf(line, sizeof line, "wb_thread_%u:active=%u,busy256=%u,f256=%u,"
            "window_passes=%llu,windows=%llu\r\n", tid, unsigned((packet >> 18) & 1),
            unsigned(packet & 511), unsigned((packet >> 9) & 511),
            (unsigned long long)row.width.load(std::memory_order_relaxed),
            (unsigned long long)row.windows.load(std::memory_order_relaxed));
        body += line;
    }
}

// IO-owned sizes only; exclude submitted send/segment bytes from the next batch.
// buffered_output_bytes() already walks the existing segment queue, without a
// byte counter or allocation. Its send remainder equals send_buf().size()-wsent()
// at every valid writeback frontier, as in the measured arm's accessor.
template <class Connection>
inline size_t staged_bytes(Connection& c) {
    return c.send_inflight() ? c.fill_buf().size() : c.buffered_output_bytes();
}

template <class Operation>
inline size_t code_bytes(const Operation& op) {
    switch (static_cast<ReplyCode>(op.reply_code_)) {
    case ReplyCode::Ok: case ReplyCode::Nil: case ReplyCode::NullArray: return 5;
    case ReplyCode::Pong: return 7;
    case ReplyCode::EmptyStr: return 6;
    case ReplyCode::NullResp3: return 3;
    case ReplyCode::True: case ReplyCode::False: return 4;
    case ReplyCode::Int: {
        int64_t v = op.reply_ival_;
        size_t n = 4; // colon, one digit, CRLF
        if (v < 0) { ++n; v = -v; }
        while (v >= 10) { v /= 10; ++n; }
        return n;
    }
    default: return 0;
    }
}

template <class Operation>
inline size_t reply_bytes(const Operation& op) {
    // Caller has acquired Done. Never read reply lengths from an executing op.
    // Negative zc_shard encodes a retire hook/state, not a borrowed value. Its
    // eventual output is unknown here: do not count zc_len as payload in that case.
    return op.reply.size() + (op.reply_code_ ? code_bytes(op) : op.direct_len) +
           (op.zc_ptr && op.zc_shard >= 0 ? size_t(op.zc_len) + 2 : 0);
}

template <class Connection>
inline bool defer(Connection& c, unsigned fraction = 128) {
    if (fraction == 0) return false; // policy 0 and AUTO's exact idle endpoint
    auto& rob = c.rob();
    const unsigned n = rob.in_flight();
    if (n <= 1) return false; // staged-only, pubsub, and p1 use ordinary serve
    size_t bytes = staged_bytes(c);
    if (bytes >= kWbufInline) return false;
    const auto head = rob.flush_id();
    const unsigned threshold = (n * fraction + scale - 1) / scale;
    unsigned prefix = 0;
    // Both counters belong to IO, but Done can have holes. Neither head/tail nor
    // the threshold slot alone proves a contiguous prefix. At most ROB slots,
    // with early exit once either threshold is satisfied; retirement stays in WB.
    while (prefix < threshold) {
        const auto& op = rob.at(head + prefix);
        if (op.state.load(std::memory_order_acquire) != OpState::Done) break;
        // Separate measured candidate: assembly stays in ordinary WB, in ROB order.
        // A Done scatter's byte size is unknown here; do not traverse its sub-ops.
        if (op.zc_ptr && op.zc_shard == Op::kScatterStateMarker) return false;
        bytes += reply_bytes(op);
        if (bytes >= kWbufInline) return false;
        ++prefix;
    }
    if (prefix >= threshold) return false;
    return true;
}
// Both modes use the same acquire walk and FIFO lifetime rule. Coded preserves
// each caller's existing encoder capability; it is not a policy selector.
struct Phase2 {
    // Overlap retains its existing stack scratch and send boundaries. The caller
    // carries one captured visit count across chunks; callbacks cannot extend it.
    template <class Loop, class Batch>
    static inline uint32_t gather(Loop& loop, Batch& batch, size_t& left) {
        if (left == SIZE_MAX) left = loop.pending_serve_.size();
        while (left && batch.count < batch.clients.size() && !loop.pending_serve_.empty()) {
            --left;
            Client* client = loop.pending_serve_.front();
            loop.pending_serve_.pop_front();
            if (!client->dead() && defer(*client, loop.wb_policy_ ? loop.wb_policy_->fraction : 128)) {
                loop.pending_serve_.push_back(client);
                continue;
            }
            client->set_serve_pending(false);
            if (!client->dead()) {
                batch.clients[batch.count] = client;
                batch.submit_allowed[batch.count++] = true;
            }
        }
        return batch.count;
    }
    template <bool HasTls, bool kEp, class Loop, bool Coded = true>
    __attribute__((always_inline)) static inline uint32_t serve(Loop& loop) {
        using ServerType = std::remove_pointer_t<decltype(loop.srv_)>;
        uint32_t work = 0;
        uint32_t served = 0;
        const size_t ready_now = loop.pending_serve_.size();
        const size_t serve_budget = ready_now;
        size_t visits = 0;
        while (served < serve_budget && visits < ready_now && !loop.pending_serve_.empty()) {
            Client* c = loop.pending_serve_.front();
            loop.pending_serve_.pop_front();
            ++visits;
            if (!c->dead() && defer(*c, loop.wb_policy_ ? loop.wb_policy_->fraction : 128)) {
                // Keep the lifetime pin; a younger eligible connection may pass this head.
                loop.pending_serve_.push_back(c);
                continue;
            }
            c->set_serve_pending(false);
            // Closing conns MUST still be served -- their ROB has to drain before quiesce can let
            // loop.close_client finish. Only corpses (freed-pending) are skippable.
            if (c->dead()) continue;
            served++;
            // CLIENT REPLY OFF/SKIP. ONE predicted-false test per SERVED CONNECTION -- not per
            // operation: a p32 batch amortises it over 32 replies. The suppressed drain lives in
            // the cold object and discards bytes instead of staging them.
            if (__builtin_expect((loop.climon_armed_cached_ & ServerType::kClimonReply) != 0, false) &&
                loop.climon_reply_suppressed(c)) {
                work += loop.climon_serve_suppressed(c);
                if constexpr (kEp) if (loop.wb_.take_send_failure()) loop.epoll_close_now(c);
                continue;
            }
            if constexpr (HasTls) {
                if (auto* tls = loop.tls_engine(c)) {
                    if (loop.wb_.template serve_tls<kEp, false, Coded>(*c, *tls)) work++;
                    if (tls->socket_userspace() && tls->has_pinned_plain())
                        loop.template arm_tls_socket_poll<kEp>(c, tls->wanted());
                    if (tls->failed()) loop.close_client(c, tls->output_pending() || c->send_inflight());
                } else if (auto* slot = loop.tls_slot_conn(c); slot && slot->ktls()) {
                    if (loop.wb_.template serve_ktls<kEp, false, Coded>(*c)) work++;
                } else if (loop.wb_.template serve<kEp, false, Coded>(*c)) {
                    work++;
                }
            } else if (loop.wb_.template serve<kEp, false, Coded>(*c)) {
                work++;
            }
            // A synchronous send has no CQE to report a fatal errno through, so the engine latches
            // it and the decision to tear the connection down is taken here instead. Consuming it
            // per served connection is deliberate: a bit left set would close the NEXT one.
            if constexpr (kEp) if (loop.wb_.take_send_failure()) loop.epoll_close_now(c);
        }
        work += served;
        if (!loop.pending_serve_.empty()) ++work; // deferred entries must get another phase
        return work;
    }
};
} // namespace tomo::wb_rule
