// The measured window4 c12 policy: one captured FIFO visit, bytes OR half a Done prefix.
#pragma once
#include <ratio>
#include <type_traits>
#include "../net/conn.h"

namespace tomo::wb_rule {
// Dimensionless POLICY fraction, not a byte/count/time bound. Competition record
// section 39 (2026-09-23/24), w4-c12: parse 32 / EX 32 / composite 1/2.
inline constexpr std::ratio<1, 2> kPolicyFraction{};

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
inline bool defer(Connection& c) {
    auto& rob = c.rob();
    const unsigned n = rob.in_flight();
    if (n <= 1) return false; // staged-only, pubsub, and p1 use ordinary serve
    size_t bytes = staged_bytes(c);
    if (bytes >= kWbufInline) return false;
    const auto head = rob.flush_id();
    const unsigned threshold = (n * kPolicyFraction.num + kPolicyFraction.den - 1) / kPolicyFraction.den;
    unsigned prefix = 0;
    // Both counters belong to IO, but Done can have holes. Neither head/tail nor
    // the threshold slot alone proves a contiguous prefix. At most ROB slots,
    // with early exit once either threshold is satisfied; retirement stays in WB.
    while (prefix < threshold) {
        const auto& op = rob.at(head + prefix);
        if (op.state.load(std::memory_order_acquire) != OpState::Done) break;
        bytes += reply_bytes(op);
        if (bytes >= kWbufInline) return false;
        ++prefix;
    }
    if (prefix >= threshold) return false;
    return true;
}
// Only the fused call site instantiates this walk. Keeping its local state here
// leaves split PHASE 2's original loop and compiler input intact.
struct Phase2 {
    template <bool HasTls, bool kEp, class Loop>
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
            if (!c->dead() && defer(*c)) {
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
                    if (loop.wb_.template serve_tls<kEp, false, true>(*c, *tls)) work++;
                    if (tls->socket_userspace() && tls->has_pinned_plain())
                        loop.template arm_tls_socket_poll<kEp>(c, tls->wanted());
                    if (tls->failed()) loop.close_client(c, tls->output_pending() || c->send_inflight());
                } else if (auto* slot = loop.tls_slot_conn(c); slot && slot->ktls()) {
                    if (loop.wb_.template serve_ktls<kEp, false, true>(*c)) work++;
                } else if (loop.wb_.template serve<kEp, false, true>(*c)) {
                    work++;
                }
            } else if (loop.wb_.template serve<kEp, false, true>(*c)) {
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
