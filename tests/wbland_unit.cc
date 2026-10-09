// Deterministic policy 0/1 witnesses; no worker loops, sockets, or load.
#include <cstdio>
#include <cstdlib>
#include <string>
#include "src/core/config.h"
using namespace tomo;
static const char* selected;
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL wbland %s: %s\n", selected, why); std::exit(1); }
}
void tomo::multi_session_destroy(MultiSession* p) { require(!p, "unexpected MULTI session"); }
static void fill(Client& c, unsigned n, unsigned done) {
    for (unsigned i = 0; i < n; ++i) {
        auto* op = c.rob().acquire<false>(); require(op, "ROB capacity");
        c.rob().publish(); op->state.store(i < done ? OpState::Done : OpState::Issued);
    }
}
static void endpoints() {
    for (unsigned n = 0; n <= 64; ++n) for (unsigned done = 0; done <= n; ++done)
        for (unsigned waits = 0; waits <= wb_rule::kCompleteVisits; ++waits) {
        Client c(-1); fill(c, n, done);
        c.wb_deferrals() = waits;
        require(!wb_rule::defer(c, 0), "zero serves every prefix");
        require(c.wb_deferrals() == waits, "zero bypass leaves count alone");
        const unsigned need = n <= wb_rule::kSmallPipe && waits < wb_rule::kCompleteVisits
                            ? n : (n+1)/2;
        require(wb_rule::defer(c, 1) == (n > 1 && done < need),
                "policy one is exact bounded hybrid");
    }
}
static void exits() {
    Client complete(-1); fill(complete, 64, 64);
    require(!wb_rule::defer(complete, 1), "finished pipe exits under half rule");
    Client staged(-1); staged.fill_buf().append("+OK\r\n", 5);
    require(!wb_rule::defer(staged, 1), "nothing in flight exits under half rule");
    Client c(-1); fill(c, 32, 1);
    auto& op = c.rob().at(0);
    op.zc_ptr = reinterpret_cast<const char*>(1); op.zc_shard = Op::kScatterStateMarker;
    require(!wb_rule::defer(c, 1), "MGET scatter exits under half rule");
    op.zc_ptr = nullptr;
    std::string bytes(kWbufInline-1, 'x'); op.reply.append(bytes.data(), bytes.size());
    require(wb_rule::defer(c, 1), "511 bytes do not open half pipe");
    op.reply.append("x", 1);
    require(!wb_rule::defer(c, 1), "512 bytes open half pipe");
}
static void grammar() {
    require(Config{}.wb_policy == 1 && sizeof(Config) == 624, "default and footprint");
    for (const char* p : {"0", "1"}) {
        Config c; ConfigParseState st;
        require(parse_config_args({"--wb-policy", p}, c, st, 1, "conf") == kConfigParsed &&
                c.wb_policy == std::atoi(p), "numeric file grammar");
        require(parse_config_args({"--wb-policy", "0"}, c, st, 2, "CLI") == kConfigParsed &&
                c.wb_policy == 0, "CLI overrides file");
    }
    for (const char* p : {"-2", "-1", "2", "3", "auto", "1x", "", "+1", "01", "0.5"}) {
        Config c; ConfigParseState st;
        require(parse_config_args({"--wb-policy", p}, c, st, 2, "test") == kConfigError,
                "invalid policy rejected");
    }
    Config c; ConfigParseState st;
    require(parse_config_args({"--wb-policy"}, c, st, 2, "test") == kConfigError,
            "missing policy rejected");
    for (int policy : {-1, 2}) {
        c.wb_policy = policy;
        require(validate_config(c) == kConfigError, "invalid direct Config rejected");
    }
}
static void info() {
    for (int policy : {0, 1}) {
        std::string output;
        wb_rule::info(output, policy, 16, 3);
        require(output == "# Writeback\r\nwb_policy:" + std::to_string(policy) +
                "\r\nwb_small_pipe:16\r\nwb_complete_visits:3\r\n",
                "INFO contains exactly the selected boot policy and bounds");
    }
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    selected = argv[1]; const std::string name = selected;
    if (name == "endpoints") endpoints();
    else if (name == "exits") exits(); else if (name == "grammar") grammar();
    else if (name == "info") info(); else require(false, "known fixture");
    std::printf("PASS wbland %s\n", selected);
}
