// The measured window4 c12 policy: one captured FIFO visit, bytes OR half a Done prefix.
#pragma once
#include <ratio>
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
} // namespace tomo::wb_rule
