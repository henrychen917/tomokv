// Deterministic pol2-k1 witnesses; no clocks, worker loops, sockets, or load.
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
static void sample(wb_rule::State& state, unsigned busy, unsigned owned = 16) {
    state.pass(0, 0, owned);
    for (unsigned p = 1; p <= 2 * owned; ++p)
        state.pass(p * 256, p * (256-busy), owned);
}
static void endpoints() {
    for (unsigned n = 0; n <= 64; ++n) for (unsigned done = 0; done <= n; ++done) {
        Client c(-1); fill(c, n, done);
        wb_rule::State zero(0, true), half(1, true), full(-1, true), cold(-1, true);
        sample(full, 256); sample(cold, 0);
        require(!wb_rule::defer(c, zero.fraction) && !wb_rule::defer(c, cold.fraction),
                "zero serves every prefix");
        require(wb_rule::defer(c, half.fraction) == (n > 1 && done < (n+1)/2),
                "policy one is exact landed half");
        require(wb_rule::defer(c, full.fraction) == (n > 1 && done < n),
                "saturated AUTO uses whole contiguous pipe");
    }
}
static void trickle() {
    wb_rule::State s(-1, true);
    // A trickle spends one out of 256 duration units busy, unlike the old SWITCH
    // witness's nearly-saturated one idle ns per block. Exercise every boundary.
    s.pass(0, 0, 16);
    for (unsigned p = 1; p <= 192; ++p) {
        s.pass(p * 256, p * 255, 16);
        require(s.fraction <= 1, "trickle fraction stays near zero");
    }
    require(s.fraction == 1 && s.window.windows == 12, "trickle window signal observed");
}
static void saturated() {
    wb_rule::State s(-1, true); sample(s, 256);
    require(s.fraction == 256 && s.window.windows == 2, "two busy blocks reach one");
    wb_rule::State tiny(-1, true);
    tiny.pass(0, 0, 1); tiny.pass(1000000000, 0, 1); tiny.pass(2000000000, 1, 1);
    require(tiny.fraction == 255, "fraction floors busy before complement rounding");
}
static void ramp() {
    wb_rule::State s(-1, true);
    uint64_t wall = 0, idle = 0;
    s.pass(wall, idle, 16);
    unsigned previous_block = 0, blocks = 0, last = 0;
    for (unsigned load : {0u, 32u, 64u, 128u, 192u, 256u, 192u, 128u, 64u, 32u, 0u}) {
        const bool rising = load >= previous_block;
        for (unsigned repeat = 0; repeat < 2; ++repeat) {
            const unsigned held = s.fraction;
            // Uneven individual passes alternate around the block's exact load.
            // A windowless mutant visibly flaps within each block even if its
            // long-run aggregate happens to match this ramp's offered demand.
            const unsigned amplitude = std::min(load, 256-load);
            for (unsigned p = 0; p < 16; ++p) {
                const unsigned pass_busy = p % 2 ? load-amplitude : load+amplitude;
                wall += 256; idle += 256-pass_busy;
                s.pass(wall, idle, 16);
                if (p < 15) require(s.fraction == held, "ramp holds dial between full block boundaries");
            }
            ++blocks;
            const unsigned expected = blocks < 2 ? 0 : (previous_block+load)/2;
            require(s.fraction == expected, "ramp uses two completed weighted blocks");
            require(rising ? s.fraction >= last : s.fraction <= last,
                    "ramp moves monotonically with block load");
            previous_block = load; last = s.fraction;
        }
        require(s.fraction == load, "linear ramp reaches each requested busy fraction");
    }
    require(s.window.windows == 22 && s.fraction == 0, "ramp returns to idle after 22 blocks");
    std::printf("RAMP blocks=%llu f256=%u\n", (unsigned long long)s.window.windows, s.fraction);
}
static void window() {
    wb_rule::State s(-1, true);
    s.pass(0, 0, 8);
    for (unsigned i = 1; i < 8; ++i) s.pass(i, 0, 1);
    require(s.window.windows == 0 && s.window.width == 8, "ownership cannot shorten current block");
    s.pass(8, 0, 32);
    require(s.window.windows == 1 && s.window.width == 32, "next block uses current ownership");
    for (unsigned i = 1; i <= 32; ++i) s.pass(8+i, i, 32);
    require(s.fraction == 51, "two blocks weighted by duration rather than mean of fractions");
    wb_rule::State empty(-1, true);
    empty.pass(10, 0, 0); empty.pass(20, 0, 0); empty.pass(30, 0, 0);
    require(empty.window.width == 1 && empty.fraction == 256, "empty owner has one-pass block");
    wb_rule::State next(-1, true);
    next.pass(100, 99, 1);
    require(next.fraction == 0 && !next.window.previous_valid, "new tenure resets history");
    next.pass(100, 99, 1);
    require(next.window.windows == 0, "zero-duration block cannot claim a measurement");
    // Products/sums at the boundary need 128-bit arithmetic, not floating point.
    wb_rule::State wide(-1, true);
    constexpr uint64_t span = UINT64_MAX/3;
    wide.pass(0, 0, 1); wide.pass(span, span/2, 1); wide.pass(2*span, span, 1);
    require(wide.fraction == 128, "large wall durations preserve linear fraction");
}
static void fixed() {
    for (bool fused : {false, true}) for (int policy : {0, 1}) {
        wb_rule::State s(policy, fused); sample(s, 256);
        require(!s.dynamic && !s.window.seeded && s.window.windows == 0,
                "fixed policy does not run detector");
        require(s.fraction == (policy == 0 ? 0u : 128u), "fixed policy pins its fraction");
    }
    wb_rule::State split(-1, false); sample(split, 256);
    require(!split.dynamic && split.fraction == 128, "split AUTO retains measured half rule");
    wb_rule::State probe(-1, false, 1u << 8); sample(probe, 256);
    require(probe.dynamic && probe.fraction == 256, "split probe uses same detector");
    wb_rule::State pad(-1, true, 1u << 31); sample(pad, 256);
    require(!pad.dynamic && pad.fraction == 128, "PAD A is half-rule behavior twin");
}
static void exits() {
    wb_rule::State s(-1, true); sample(s, 256);
    Client complete(-1); fill(complete, 64, 64);
    require(!wb_rule::defer(complete, s.fraction), "finished pipe exits at busy endpoint");
    Client staged(-1); staged.fill_buf().append("+OK\r\n", 5);
    require(!wb_rule::defer(staged, s.fraction), "nothing in flight exits at busy endpoint");
    Client c(-1); fill(c, 32, 1);
    auto& op = c.rob().at(0);
    op.zc_ptr = reinterpret_cast<const char*>(1); op.zc_shard = Op::kScatterStateMarker;
    require(!wb_rule::defer(c, s.fraction), "MGET scatter exits at busy endpoint");
    op.zc_ptr = nullptr;
    std::string bytes(kWbufInline-1, 'x'); op.reply.append(bytes.data(), bytes.size());
    require(wb_rule::defer(c, s.fraction), "511 bytes do not open busy pipe");
    op.reply.append("x", 1);
    require(!wb_rule::defer(c, s.fraction), "512 bytes open busy pipe");
}
static void grammar() {
    require(Config{}.wb_policy == -1 && sizeof(Config) == 624, "default and footprint");
    for (const char* p : {"-1", "0", "1"}) {
        Config c; ConfigParseState st;
        require(parse_config_args({"--wb-policy", p}, c, st, 1, "conf") == kConfigParsed &&
                c.wb_policy == std::atoi(p), "numeric file grammar");
        require(parse_config_args({"--wb-policy", "0"}, c, st, 2, "CLI") == kConfigParsed &&
                c.wb_policy == 0, "CLI overrides file");
    }
    for (const char* p : {"-2", "2", "3", "auto", "1x", "", "+1", "01", "0.5"}) {
        Config c; ConfigParseState st;
        require(parse_config_args({"--wb-policy", p}, c, st, 2, "test") == kConfigError,
                "invalid policy rejected");
    }
    Config c; ConfigParseState st;
    require(parse_config_args({"--wb-policy"}, c, st, 2, "test") == kConfigError,
            "missing policy rejected");
    c.wb_policy = 2;
    require(validate_config(c) == kConfigError, "invalid direct Config rejected");
}
static void publication() {
    wb_rule::State s(-1, true); wb_rule::Published row;
    s.publish(&row); const auto before = row.packet.load(); sample(s, 256);
    require(row.packet.load() == before && row.windows.load() == 0,
            "pass never publishes shared diagnostics");
    s.publish(&row); std::string output; wb_rule::info(output, -1, true, &row, 1);
    require(output.find("wb_adaptive:1") != std::string::npos &&
            output.find("active=1,busy256=256,f256=256,window_passes=16,windows=2") != std::string::npos,
            "INFO observes active linear dial and full windows");
    s.publish(&row, false);
    require((row.packet.load() & (1ull << 18)) == 0, "exit clears active publication");
    output.clear(); wb_rule::info(output, -1, false, nullptr, 8);
    require(output.find("wb_adaptive:0\r\nwb_fixed_f256:128") != std::string::npos &&
            output.find("wb_thread_") == std::string::npos, "INFO exposes split fallback");
}
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    selected = argv[1]; const std::string name = selected;
    if (name == "endpoints") endpoints(); else if (name == "trickle") trickle();
    else if (name == "saturated") saturated(); else if (name == "ramp") ramp();
    else if (name == "window") window(); else if (name == "fixed") fixed();
    else if (name == "exits") exits(); else if (name == "grammar") grammar();
    else if (name == "publication") publication(); else require(false, "known fixture");
    std::printf("PASS wbland %s\n", selected);
}
