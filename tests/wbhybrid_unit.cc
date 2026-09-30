// Serverless study oracle and single-invocation instruction fixture. Never opens a socket.
#include <cstdio>
#include <cstdlib>
#include <string>
#include "src/core/wb_rule.h"

using namespace tomo;
// The oracle is deliberately independent of the generated production constant.
#ifndef WBHYBRID_EXPECT_SMALL
#define WBHYBRID_EXPECT_SMALL 0
#endif
static constexpr unsigned small = WBHYBRID_EXPECT_SMALL;
static const char* selected;
static void require(bool ok, const char* why) {
    if (!ok) {
        std::fprintf(stderr, "FAIL wbhybrid %s: %s\n", selected, why);
        std::exit(1);
    }
}
void tomo::multi_session_destroy(MultiSession* p) { require(!p, "unexpected MULTI session"); }
static void fill(Client& c, unsigned n, unsigned done) {
    for (unsigned i = 0; i < n; ++i) {
        Op* op = c.rob().acquire<false>(); require(op, "ROB capacity");
        c.rob().publish();
        op->state.store(i < done ? OpState::Done : OpState::Issued, std::memory_order_release);
    }
}
static unsigned threshold(unsigned n) { return n <= small ? n : n/2 + n%2; }
static void table() {
    unsigned cells = 0;
    for (unsigned start : {0u, 61u}) {
        for (unsigned n = 0; n <= 64; ++n) for (unsigned done = 0; done <= n; ++done) {
            Client c(-1); fill(c, start, start); c.rob().drain([](Op&) {});
            fill(c, n, done);
            require(!wb_rule::defer(c, 0), "policy zero bypasses every prefix");
            const bool expected = n > 1 && done < threshold(n);
            if (wb_rule::defer(c, 1) != expected) {
                std::fprintf(stderr, "n=%u done=%u S=%u threshold=%u start=%u\n",
                             n, done, small, threshold(n), start);
                require(false, "piecewise threshold table");
            }
            ++cells;
        }
    }
    std::printf("table_cells=%u policies=0,1 wraps=0,61\n", cells);
}
static void exits() {
    for (unsigned n = 2; n <= 64; ++n) {
        for (bool inflight : {false, true}) {
            Client c(-1); fill(c, n, 0);
            if (inflight) {
                c.fill_buf().append(std::string(512, 's').data(), 512);
                c.swap_buffers(); c.set_send_inflight(true);
                require(wb_rule::defer(c, 1), "submitted bytes excluded");
            }
            c.fill_buf().append(std::string(511, 's').data(), 511);
            require(wb_rule::defer(c, 1), "511 staged bytes defer");
            c.fill_buf().append("s", 1);
            require(!wb_rule::defer(c, 1), "512 staged bytes preempt");
        }
        Client c(-1); fill(c, n, 1); auto& op = c.rob().at(c.rob().flush_id());
        op.reply.append(std::string(511, 'r').data(), 511);
        require(wb_rule::defer(c, 1) == (threshold(n) > 1), "511 reply bytes obey count");
        op.reply.append("r", 1);
        require(!wb_rule::defer(c, 1), "512 reply bytes preempt");
        op.reply.clear(); op.zc_ptr = reinterpret_cast<const char*>(1);
        op.zc_shard = Op::kScatterStateMarker; op.zc_len = UINT32_MAX;
        require(!wb_rule::defer(c, 1), "Done scatter exit serves");
        op.state.store(OpState::Issued, std::memory_order_release);
        require(wb_rule::defer(c, 1), "undone scatter cannot open the pipe");
        op.zc_ptr = nullptr;
    }
}

// ptrace stops exactly at this symbol, counts one defer(), then requires fixture success.
extern "C" __attribute__((noinline, noclone)) bool wbhybrid_defer(Client* c, int policy) {
    return wb_rule::defer(*c, policy);
}
static void trace(const std::string& name) {
    unsigned n = 0, done = 0, bytes = 0, policy = 1, scatter = 0;
    require(std::sscanf(name.c_str(), "trace-%u-%u-%u-%u-%u", &n, &done, &bytes,
                        &policy, &scatter) == 5 && n <= 64 && done <= n,
            "trace fixture grammar");
    Client c(-1); fill(c, n, done);
    if (bytes) c.fill_buf().append(std::string(bytes, 's').data(), bytes);
    if (scatter) {
        require(done > 0, "trace scatter is Done");
        auto& op = c.rob().at(c.rob().flush_id());
        op.zc_ptr = reinterpret_cast<const char*>(1); op.zc_shard = Op::kScatterStateMarker;
    }
    const bool expected = policy != 0 && n > 1 && bytes < 512 && !scatter && done < threshold(n);
    const bool result = wbhybrid_defer(&c, policy);
    require(result == expected, "trace decision");
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    selected = argv[1]; const std::string name = selected;
    if (name == "table") table();
    else if (name == "exits") exits();
    else if (name.starts_with("trace-")) trace(name);
    else require(false, "known fixture");
    std::printf("PASS wbhybrid %s\n", selected);
}
