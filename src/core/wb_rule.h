// One writeback policy in both modes: bounded small-pipe completion OR bytes OR half.
#pragma once
#include <cstdio>
#include <ratio>
#include <string>
#include <type_traits>
#include "../net/conn.h"

namespace tomo::wb_rule {
// MEASURED default S=16, not derived from a batch size or reply size. Constants ledger
// addendum 12, S=16 KEEP (2026-10-02); PLAN-SERIAL 2026-10-01 16:54 and
// 2026-10-02 06:54: p8 saturation, p8@512K attainment, floor-0.4 bursts.
// See MEASURE-REQUEST-wbhybrid.md: no honest derivation from existing sizings.
inline constexpr unsigned kSmallPipe = 16;
// MEASURED default D=3. Constants ledger addendum 12, D=3 DERIVE-BY-MEASUREMENT
// (2026-10-02); PLAN-SERIAL 06:54 D-curve row 3: p8 GET/SET/rl-SET
// +9.4/+10.4/+6.6%, with floor-0.4 p99/p999 inside the same-binary band.
inline constexpr unsigned kCompleteVisits = 3;
// Boot-latched in IoLoop padding; no allocation or per-visit configuration lookup.
struct Settings {
    uint8_t policy = 1;
    uint8_t small_pipe = kSmallPipe;
    uint8_t complete_visits = kCompleteVisits;
};
// Dimensionless POLICY fraction, not a byte/count/time bound. Competition record
// section 39 (2026-09-23/24), w4-c12: parse 32 / EX 32 / composite 1/2.
inline constexpr std::ratio<1, 2> kPolicyFraction{};

// Cold artifact selector: only the default 0/1 policy, no detector/probe bits.
// tools/wbland_artifacts.py patches this immediate for the frozen pol0 arm.
__attribute__((noinline, noclone)) inline int default_policy() {
    int policy;
    asm volatile("mov $1, %0" : "=a"(policy));
    return policy;
}

inline void info(std::string& body, int policy, unsigned small_pipe, unsigned complete_visits) {
    char line[128];
    std::snprintf(line, sizeof line,
                  "# Writeback\r\nwb_policy:%d\r\nwb_small_pipe:%u\r\nwb_complete_visits:%u\r\n",
                  policy, small_pipe, complete_visits);
    body += line;
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
inline bool defer(Connection& c, const Settings& cfg) {
    int policy = cfg.policy;
    if (policy == 0) return false; // LATENCY: every ready head on every captured pass
    auto& rob = c.rob();
    const unsigned n = rob.in_flight();
    if (n <= 1) return false; // staged-only, pubsub, and p1 use ordinary serve
    size_t bytes = staged_bytes(c);
    if (bytes >= kWbufInline) return false;
    const auto head = rob.flush_id();
    const unsigned small_pipe = cfg.small_pipe, complete_visits = cfg.complete_visits;
    // Keep this per-visit predicate off the encoder's register set. A live
    // register here spills once per integer reply; one stack byte keeps all
    // additional work at the visit boundary (locked by code-costs receipts).
    // D=0 completes without counting. Only the bounded predicate survives the
    // walk, so neither knob needs a live register through integer reply sizing.
    const volatile bool complete = n <= small_pipe && c.wb_deferrals() < complete_visits;
    const unsigned threshold = (complete || (complete_visits == 0 && n <= small_pipe))
        ? n : (n * kPolicyFraction.num + kPolicyFraction.den - 1) / kPolicyFraction.den;
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
    // One byte update per deferred visit, never per operation. The predicate
    // caps the count at D: half-rule and unbounded deferrals add zero, never wrap.
    c.wb_deferrals() += complete;
    return true;
}
template <class Connection>
inline bool defer(Connection& c, int policy = 1, unsigned small_pipe = kSmallPipe,
                  unsigned complete_visits = kCompleteVisits) {
    const Settings cfg{static_cast<uint8_t>(policy), static_cast<uint8_t>(small_pipe),
                       static_cast<uint8_t>(complete_visits)};
    return defer(c, cfg);
}
// Both modes use the same acquire walk and FIFO lifetime rule. Coded preserves
// each caller's existing encoder capability; it is not a policy selector.
struct Phase2 {
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
            if (!c->dead() && defer(*c, loop.wb_config_)) {
                // Keep the lifetime pin; a younger eligible connection may pass this head.
                loop.pending_serve_.push_back(c);
                continue;
            }
            c->wb_deferrals() = 0; // served or dead: leaving the FIFO
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
