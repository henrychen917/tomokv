// Exhaustive decisions and real FIFO gather lifetime; no socket, clock or worker.
#include <array>
#include <deque>
#include <cstdio>
#include <cstdlib>
#include <string>
#include "src/core/wb_rule.h"

using namespace tomo;
static constexpr unsigned delay = wb_rule::kCompleteVisits, small = wb_rule::kSmallPipe;
static constexpr unsigned wait_limit = delay;
static_assert(small == 16 && delay == 3, "measured production constants changed");
static const char* selected;
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL wb-completion %s: %s\n", selected, why); std::exit(1); }
}
void tomo::multi_session_destroy(MultiSession* p) { require(!p, "unexpected MULTI"); }
static void count(Client& c, unsigned value) {
    c.wb_deferrals() = value;
}
static unsigned count(Client& c) {
    return c.wb_deferrals();
}
static bool completion(unsigned n, unsigned waits) {
    return n <= small && waits < delay;
}
static unsigned threshold(unsigned n, unsigned waits) {
    return completion(n, waits) ? n : n / 2 + n % 2;
}
static void fill(Client& c, unsigned n, unsigned done) {
    for (unsigned i = 0; i < n; ++i) {
        Op* op = c.rob().acquire<false>(); require(op, "ROB capacity"); c.rob().publish();
        op->state.store(i < done ? OpState::Done : OpState::Issued, std::memory_order_release);
    }
}
static void finish(Client& c) {
    for (unsigned i = 0; i < c.rob().in_flight(); ++i)
        c.rob().at(c.rob().flush_id() + i).state.store(OpState::Done, std::memory_order_release);
    c.rob().drain([](Op&) {});
}
static void table() {
    unsigned cells = 0;
    for (unsigned start : {0u, 61u}) for (unsigned n = 0; n <= 64; ++n)
        for (unsigned ready = 0; ready <= n; ++ready) for (unsigned waits = 0; waits <= wait_limit; ++waits) {
            const unsigned done = n - ready;
            Client c(-1); fill(c, start, start); finish(c); fill(c, n, done); count(c, waits);
            require(!wb_rule::defer(c, 0), "policy zero bypass");
            const bool expected = n > 1 && done < threshold(n, waits);
            if (wb_rule::defer(c, 1) != expected) {
                std::fprintf(stderr, "n=%u Done=%u count=%u D=%u S=%u start=%u\n",
                             n, done, waits, delay, small, start);
                require(false, "bounded decision table");
            }
            require(count(c) == waits + unsigned(expected && completion(n, waits)),
                    "count only completion deferrals; saturated without wrap");
            ++cells;
        }
    std::printf("table_cells=%u policies=0,1 wraps=0,61 counts=0..%u\n", cells, wait_limit);
}
static void knobs() {
    // Independent integer oracle; sweep every prefix, both ROB placements, and
    // counter boundaries. The same runtime call must distinguish S=0 and D=0.
    for (unsigned s : {0u, 1u, 2u, 8u, 16u, 17u, 64u})
        for (unsigned d : {0u, 1u, 3u, 255u})
        for (unsigned start : {0u, 61u}) for (unsigned n = 0; n <= 64; ++n)
        for (unsigned done = 0; done <= n; ++done)
        for (unsigned waits : {0u, 1u, 2u, 3u, 254u, 255u}) {
            Client c(-1); fill(c, start, start); finish(c); fill(c, n, done); count(c, waits);
            const bool completing = n <= s && (d == 0 || waits < d);
            const bool expected = n > 1 && done < (completing ? n : n / 2 + n % 2);
            require(!wb_rule::defer(c, 0, s, d) && count(c) == waits, "knobs preserve policy zero");
            require(wb_rule::defer(c, 1, s, d) == expected, "runtime knob decision table");
            require(count(c) == waits + unsigned(expected && completing && d != 0),
                    "runtime count saturates or stays untouched when unbounded");
        }
}
static void exits() {
    for (unsigned n = 2; n <= 64; ++n) for (unsigned waits = 0; waits <= wait_limit; ++waits) {
        Client c(-1); fill(c, n, 1); count(c, waits);
        auto& op = c.rob().at(c.rob().flush_id());
        op.reply.append(std::string(511, 'x').data(), 511);
        require(wb_rule::defer(c) == (threshold(n, waits) > 1), "511 bytes obey count");
        count(c, waits); op.reply.append("x", 1);
        require(!wb_rule::defer(c), "512 Done bytes exit");
        op.reply.clear(); op.zc_ptr = reinterpret_cast<const char*>(1);
        op.zc_shard = Op::kScatterStateMarker; op.zc_len = UINT32_MAX;
        require(!wb_rule::defer(c), "Done scatter exit");
        op.state.store(OpState::Issued, std::memory_order_release);
        require(wb_rule::defer(c), "Issued scatter cannot exit");
        op.zc_ptr = nullptr;
        for (bool sending : {false, true}) {
            Client b(-1); fill(b, n, 0); count(b, waits);
            if (sending) {
                b.fill_buf().append(std::string(512, 's').data(), 512);
                b.swap_buffers(); b.set_send_inflight(true);
                require(wb_rule::defer(b), "submitted bytes excluded");
            }
            b.fill_buf().append(std::string(511, 's').data(), 511);
            require(wb_rule::defer(b), "511 staged bytes defer");
            b.fill_buf().append("s", 1);
            require(!wb_rule::defer(b), "512 staged bytes exit");
        }
        // A Done slot after a hole must not turn into a contiguous prefix.
        Client hole(-1); fill(hole, n, n); count(hole, waits);
        hole.rob().at(hole.rob().flush_id()).state.store(OpState::Issued, std::memory_order_release);
        require(wb_rule::defer(hole), "head hole blocks every threshold");
    }
}
struct ServerStub {
    static constexpr unsigned kClimonReply = 1;
    struct Config { int wb_policy = 1; } config;
    const Config& cfg() { return config; }
};
struct WbStub {
    unsigned calls = 0;
    template <bool, bool, bool> bool serve(Client&) { ++calls; return false; }
};
struct Loop {
    std::deque<Client*> pending_serve_; ServerStub server; ServerStub* srv_ = &server;
    unsigned climon_armed_cached_ = 0; WbStub wb_;
    wb_rule::Settings wb_config_;
    bool climon_reply_suppressed(Client*) { return false; }
    unsigned climon_serve_suppressed(Client*) { return 0; }
};
struct Batch { std::array<Client*, 1> clients{}; std::array<bool, 1> submit_allowed{}; unsigned count = 0; };
static bool serve_path;
static bool visit(Loop& loop) {
    if (serve_path) {
        const unsigned before = loop.wb_.calls;
        wb_rule::Phase2::serve<false, false>(loop);
        return loop.wb_.calls != before;
    }
    size_t left = SIZE_MAX; Batch batch;
    return wb_rule::Phase2::gather(loop, batch, left) != 0;
}
static void enqueue(Loop& loop, Client& c) { c.set_serve_pending(true); loop.pending_serve_.push_back(&c); }
static void lifetime() {
    for (unsigned remaining = wait_limit + 1; remaining; --remaining) for (int exit = 0; exit < 6; ++exit) {
        const unsigned waits = remaining - 1;
        Loop loop; Client c(-1); count(c, waits);
        fill(c, exit == 1 ? 1 : 8, exit == 1 ? 0 : 8);
        if (exit == 2) c.fill_buf().append(std::string(512, 's').data(), 512);
        if (exit == 3) { auto& op = c.rob().at(c.rob().flush_id());
            op.zc_ptr = reinterpret_cast<const char*>(1); op.zc_shard = Op::kScatterStateMarker; }
        if (exit == 4) loop.wb_config_.policy = 0;
        if (exit == 5) c.mark_dead();
        enqueue(loop, c); require(visit(loop) == (exit != 5), "serve/dead exit");
        require(!c.serve_pending() && loop.pending_serve_.empty(), "FIFO pin released");
        // Test behavior on the NEXT pipe before inspecting the reset byte: the
        // no-reset mutant must fail the real complete-again decision.
        if (exit != 5) {
            if (exit == 3) c.rob().at(c.rob().flush_id()).zc_ptr = nullptr;
            finish(c); c.fill_buf().clear(); fill(c, 8, 4);
            loop.wb_config_.policy = 1; enqueue(loop, c);
            require(!visit(loop), "served connection completes again next pipe");
        } else require(count(c) == 0, "dead exit resets count");
    }
    Loop loop; Client slow(-1), younger(-1); fill(slow, 8, 4); fill(younger, 1, 1);
    enqueue(loop, slow); enqueue(loop, younger);
    require(visit(loop), "younger eligible connection passes deferred head");
    {
        require(loop.pending_serve_.size() == 1 && loop.pending_serve_.front() == &slow,
                "captured visit rotates only once");
        for (unsigned i = 1; i < delay; ++i) require(!visit(loop), "D further visits");
        require(visit(loop) && count(slow) == 0, "fallback visit serves and resets");
    }
    {
        Loop stalled; Client c(-1); fill(c, 8, 0); enqueue(stalled, c);
        for (unsigned i = 0; i < 1024; ++i) {
            require(!visit(stalled), "unfinished head stays queued");
            require(count(c) == (i + 1 < delay ? i + 1 : delay), "every visit saturates at D");
        }
        require(count(c) == delay, "saturation cannot wrap after 1024 visits");
    }
}
static void knob_lifetime() {
    for (unsigned s : {0u, 8u, 64u}) for (unsigned d : {0u, 1u, 3u, 255u}) {
        Loop loop;
        loop.wb_config_.small_pipe = s; loop.wb_config_.complete_visits = d;
        Client c(-1); fill(c, 8, 4); enqueue(loop, c);
        const unsigned visits = s == 0 ? 0 : d == 0 ? 1024 : d;
        for (unsigned i = 0; i < visits; ++i) {
            require(!visit(loop), "runtime completion defers exactly D visits");
            require(c.serve_pending() && loop.pending_serve_.size() == 1,
                    "runtime completion retains one FIFO pin");
            require(count(c) == (d ? i + 1 : 0), "D=0 never increments or wraps");
        }
        if (d || !s) require(visit(loop), "runtime half threshold admits after D visits");
        else {
            finish(c); fill(c, 8, 8);
            require(visit(loop), "unbounded completion admits a finished pipe");
        }
        require(!c.serve_pending() && count(c) == 0, "runtime admission resets count and pin");
    }
}
extern "C" __attribute__((noinline, noclone)) bool wb_completion_defer(Client* c, int policy) {
    return wb_rule::defer(*c, policy);
}
static void trace(const std::string& name) {
    unsigned n, done, bytes, policy, scatter, waits;
    require(std::sscanf(name.c_str(), "trace-%u-%u-%u-%u-%u-%u", &n, &done, &bytes,
        &policy, &scatter, &waits) == 6 && n <= 64 && done <= n, "trace grammar");
    Client c(-1); fill(c, n, done); count(c, waits);
    if (bytes) c.fill_buf().append(std::string(bytes, 's').data(), bytes);
    if (scatter) { require(done, "scatter Done"); auto& op = c.rob().at(c.rob().flush_id());
        op.zc_ptr = reinterpret_cast<const char*>(1); op.zc_shard = Op::kScatterStateMarker; }
    require(wb_completion_defer(&c, policy) == (policy && n > 1 && bytes < 512 && !scatter &&
        done < threshold(n, waits)), "trace decision");
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    selected = argv[1]; const std::string name = selected;
    if (name == "table") table();
    else if (name == "knobs") knobs();
    else if (name == "exits") exits();
    else if (name == "lifetime" || name == "lifetime-serve") {
        serve_path = name == "lifetime-serve"; lifetime();
    }
    else if (name == "knob-lifetime" || name == "knob-lifetime-serve") {
        serve_path = name == "knob-lifetime-serve"; knob_lifetime();
    }
    else if (name.starts_with("trace-")) trace(name);
    else require(false, "known fixture");
    std::printf("PASS wb-completion %s\n", selected);
    return 0;
}
