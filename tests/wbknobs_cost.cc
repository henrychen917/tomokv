// Same reply fixtures and ptrace boundary as wb_rule_codes.cc, with runtime
// cache loads included. PRE compiles against the frozen merge-base headers.
#define main unused_completion_main
#include "tests/wb_rule_completion_unit.cc"
#undef main
#ifdef WBKNOBS_PRE
struct CostCache { uint8_t policy, small_pipe, complete_visits; };
#else
using CostCache = wb_rule::Settings;
#endif
extern "C" __attribute__((noinline, noclone)) bool wbknobs_defer(Client* c, const CostCache* cache) {
#ifdef WBKNOBS_PRE
    return wb_rule::defer(*c, cache->policy);
#else
    return wb_rule::defer(*c, *cache);
#endif
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    selected = argv[1];
    unsigned n = 8, done = 0, bytes = 0, policy = 1, scatter = 0, waits = 0, shape = 0;
    if (std::string(selected).starts_with("codes-")) {
        require(std::sscanf(selected, "codes-%u-%u-%u", &done, &waits, &shape) == 3 &&
                done <= 2 && waits <= 3 && shape >= 1 && shape <= 3, "coded fixture grammar");
    } else {
        require(std::sscanf(selected, "trace-%u-%u-%u-%u-%u-%u", &n, &done, &bytes,
                           &policy, &scatter, &waits) == 6 && n <= 64 && done <= n,
                "trace grammar");
    }
    Client c(-1); fill(c, n, done); count(c, waits);
    if (bytes) c.fill_buf().append(std::string(bytes, 's').data(), bytes);
    if (scatter) {
        require(done, "scatter Done"); auto& op = c.rob().at(c.rob().flush_id());
        op.zc_ptr = reinterpret_cast<const char*>(1); op.zc_shard = Op::kScatterStateMarker;
    }
    for (unsigned i = 0; i < done; ++i) {
        auto& op = c.rob().at(c.rob().flush_id() + i);
        if (shape == 1) op.reply_code_ = static_cast<uint8_t>(ReplyCode::Ok);
        else if (shape == 2) op.reply.append(std::string(71, 'g').data(), 71);
        else if (shape == 3) { op.reply_code_ = static_cast<uint8_t>(ReplyCode::Int); op.reply_ival_ = 12345; }
    }
    const CostCache cache{static_cast<uint8_t>(policy), 16, 3};
    require(wbknobs_defer(&c, &cache) == (policy && n > 1 && bytes < 512 && !scatter &&
            done < threshold(n, waits)), "runtime-cache trace decision");
    std::printf("PASS wb-completion %s\n", selected);
}
