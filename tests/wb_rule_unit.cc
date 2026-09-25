// Serverless c12 clause witnesses. The real Client/ROB covers values and wrap;
// the instrumented specialization observes every read and the acquire argument.
#include <array>
#include <cstdio>
#include <cstdlib>
#include <string>
#include "src/core/wb_rule.h"
#include "src/net/resp.h"

using namespace tomo;
static const char* selected;
static void require(bool value, const char* message) {
    if (!value) {
        std::fprintf(stderr, "FAIL wb-rule %s: %s\n", selected, message);
        std::exit(1);
    }
}
// These policy-only fixtures never create a MULTI session.
void tomo::multi_session_destroy(MultiSession* p) { require(!p, "unexpected MULTI session"); }
static void fill(Client& c, unsigned n, unsigned prefix) {
    for (unsigned i = 0; i < n; ++i) {
        Op* op = c.rob().acquire<false>();
        require(op, "ROB capacity");
        c.rob().publish();
        op->state.store(i < prefix ? OpState::Done : OpState::Issued,
                        std::memory_order_release);
    }
}
static void fraction() {
    // Every boundary, every prefix, including odd ceil rounding and real 63 -> 0 wrap.
    for (unsigned n = 1; n <= 64; ++n) for (unsigned prefix = 0; prefix <= n; ++prefix) {
        Client c(-1);
        fill(c, 61, 61); c.rob().drain([](Op&) {});
        fill(c, n, prefix);
        const bool expected = n > 1 && prefix < (n / 2 + n % 2);
        require(wb_rule::defer(c) == expected, "ceil half for every n=1..64 and prefix");
    }
}
static void staged() {
    for (unsigned source = 0; source < 3; ++source)
        for (size_t bytes : {kWbufInline - 1, kWbufInline, kWbufInline + 1, 2*kWbufInline + 9}) {
            Client c(-1); fill(c, 32, 0);
            std::string payload(bytes, 's');
            if (source == 0) c.fill_buf().append(payload.data(), bytes);
            if (source == 1) {
                c.fill_buf().append(payload.data(), bytes); c.swap_buffers();
                // Also pin the remaining-byte subtraction, not just the full send size.
                c.send_buf().append("gone", 4); c.commit_write(4);
            }
            if (source == 2) c.append_buf_segment(payload.data(), bytes);
            require(wb_rule::staged_bytes(c) == bytes, "staged fill/send remainder/segments");
            require(wb_rule::defer(c) == (bytes < kWbufInline), "staged byte threshold");
        }
    Client c(-1); fill(c, 32, 0);
    std::string half(kWbufInline/2, 'x');
    c.fill_buf().append(half.data(), half.size()); c.swap_buffers();
    c.append_buf_segment(half.data(), half.size()-1); c.fill_buf().append("x", 1);
    require(!wb_rule::defer(c), "staging sources sum at threshold");
}
static void submitted() {
    for (bool segments : {false, true}) {
        Client c(-1); fill(c, 32, 1);
        std::string payload(kWbufInline, 'x');
        if (segments) c.append_buf_segment(payload.data(), payload.size());
        else { c.fill_buf().append(payload.data(), payload.size()); c.swap_buffers(); }
        c.set_send_inflight(true);
        require(wb_rule::staged_bytes(c) == 0 && wb_rule::defer(c), "submitted bytes excluded");
        c.fill_buf().append(payload.data(), payload.size());
        require(!wb_rule::defer(c), "new fill counts during send");
    }
}
static void reply_bytes() {
    for (unsigned source = 0; source < 3; ++source)
        for (size_t bytes : {kWbufInline - 1, kWbufInline, kWbufInline + 1, 2*kWbufInline + 9}) {
            Client c(-1); fill(c, 32, 1);
            Op& op = c.rob().at(c.rob().flush_id());
            std::string payload(bytes, 'x');
            if (source == 0) op.reply.append(payload.data(), bytes);
            if (source == 1) { op.direct = c.reserve_fill(bytes); op.direct_len = bytes; }
            if (source == 2) { op.zc_ptr = payload.data(); op.zc_len = bytes-2; op.zc_shard = 0; }
            require(wb_rule::reply_bytes(op) == bytes, "spill/direct/borrow including CRLF");
            require(wb_rule::defer(c) == (bytes < kWbufInline), "Done prefix byte threshold");
        }
    Client c(-1); fill(c, 32, 2);
    std::string half(kWbufInline/2, 'x');
    c.rob().at(0).reply.append(half.data(), half.size());
    c.rob().at(1).reply.append(half.data(), half.size());
    require(!wb_rule::defer(c), "Done prefix bytes accumulate across slots");
}
static void holes() {
    for (unsigned hole : {0u, 1u, 15u}) {
        Client c(-1); fill(c, 32, 32);
        c.rob().at(hole).state.store(OpState::Issued, std::memory_order_release);
        std::string payload(2*kWbufInline, 'x');
        c.rob().at(hole+1).reply.append(payload.data(), payload.size());
        require(wb_rule::defer(c), "first hole stops fraction and bytes");
    }
}
static void markers() {
    for (int marker : {Op::kScatterStateMarker, Op::kMultiStateMarker,
                       Op::kBlockingStateMarker, -1}) {
        Client c(-1); fill(c, 8, 1);
        Op& op = c.rob().at(0);
        op.zc_ptr = reinterpret_cast<const char*>(1);
        op.zc_shard = marker; op.zc_len = UINT32_MAX;
        require(wb_rule::reply_bytes(op) == 0, "retire-state poison is not payload");
        require(wb_rule::defer(c), "one scatter ROB slot cannot open p8 fraction");
        for (unsigned i = 1; i < 4; ++i) c.rob().at(i).state.store(OpState::Done);
        require(!wb_rule::defer(c), "four command slots open p8 half");
    }
}
static void codes() {
    for (unsigned code = 1; code <= 9; ++code)
        for (int32_t value : {0, 9, 10, -1, INT32_MIN, INT32_MAX}) {
            Op op; op.reply_code_ = code; op.reply_ival_ = value;
            char bytes[kReplyCodeMax];
            require(wb_rule::reply_bytes(op) == format_reply_code(bytes, code, value),
                    "coded lengths match production encoder");
        }
}

// A read-observing specialization of the SAME policy, with no production hooks.
// Even a read whose value would be discarded must be preceded by acquiring Done.
template <class T> struct Watched {
    bool* acquired;
    T value{};
    operator T() const { require(*acquired, "reply field read before Done acquire"); return value; }
    explicit operator ReplyCode() const requires (!std::is_same_v<T, const char*>) {
        return static_cast<ReplyCode>(static_cast<T>(*this));
    }
};
struct ObservedOp {
    mutable bool acquired = false;
    struct State {
        ObservedOp* op;
        OpState value = OpState::Issued;
        OpState load(std::memory_order order) const {
            require(order == std::memory_order_acquire, "Done load must acquire");
            op->acquired = value == OpState::Done;
            return value;
        }
    } state{this};
    struct Reply {
        bool* acquired;
        size_t size() const { require(*acquired, "reply field read before Done acquire"); return 0; }
    } reply{&acquired};
    Watched<uint8_t> reply_code_{&acquired};
    Watched<int32_t> reply_ival_{&acquired};
    Watched<uint32_t> direct_len{&acquired}, zc_len{&acquired};
    Watched<const char*> zc_ptr{&acquired};
    Watched<int32_t> zc_shard{&acquired, -1};
};
struct ObservedClient {
    struct Rob {
        unsigned n = 32, probes = 0;
        std::array<ObservedOp, 64> ops;
        unsigned in_flight() const { return n; }
        unsigned flush_id() const { return 0; }
        ObservedOp& at(unsigned i) { ++probes; require(i < n, "walk stays in flight"); return ops[i]; }
    } ring;
    unsigned staged_reads = 0;
    auto& rob() { return ring; }
    bool send_inflight() { ++staged_reads; return false; }
    struct Fill { size_t size() const { return 0; } } fill;
    Fill& fill_buf() { return fill; }
    size_t buffered_output_bytes() { ++staged_reads; return 0; }
};
static void acquire() {
    ObservedClient c;
    c.ring.ops[0].state.value = OpState::Done;
    require(wb_rule::defer(c) && c.ring.probes == 2, "walk ends at first Issued");
    c.ring.probes = 0;
    for (auto& op : c.ring.ops) { op.acquired = false; op.state.value = OpState::Done; }
    require(!wb_rule::defer(c) && c.ring.probes == 16, "walk exits at successful fraction");
}
static void fastpath() {
    for (unsigned n : {0u, 1u}) {
        ObservedClient c; c.ring.n = n;
        require(!wb_rule::defer(c), "nothing-in-flight/p1 ordinary serve");
        require(c.staged_reads == 0 && c.ring.probes == 0, "fast path reads no staging or slots");
    }
}
int main(int argc, char** argv) {
    require(argc == 2, "usage: wb-rule-unit CASE"); selected = argv[1];
    const std::string name = selected;
    if (name == "fraction") fraction(); else if (name == "staged") staged();
    else if (name == "submitted") submitted(); else if (name == "bytes") reply_bytes();
    else if (name == "holes") holes(); else if (name == "markers") markers();
    else if (name == "codes") codes(); else if (name == "acquire") acquire();
    else if (name == "fastpath") fastpath(); else require(false, "unknown case");
    std::printf("PASS wb-rule %s\n", selected);
}
