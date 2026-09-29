// Offline replay and finite instruction receipts. No sockets, workers or wall clock.
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <memory>
#include <sstream>
#include <string>
#include "src/core/wb_rule.h"
#include "src/core/signalacct.h"
#include "build/wbland2/reference.h"

using namespace tomo;
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL wbland2 replay: %s\n", why); std::exit(1); }
}
struct Clock {
    static inline uint64_t value = 0;
    static uint64_t now() { return value; }
};
struct Replay {
    LoopSignals current_signal, study_signal;
    IoTenure<Clock> current_clock{current_signal};
    wbland2_study_clock::IoTenure<Clock> study_clock{study_signal};
    wb_rule::State candidate{-1, true, 0}, cut_gated{-1, true, 0};
    wbmode::State reference{2, 0x103}; // actual pol2-k1 arm, not study AUTO (-1)
    wbland1::State previous{-1, true, 0};
    uint64_t next_cut = 0, last_wall = 0, last_idle = 0;

    void finish() {
        const auto a = current_clock.finish(true, false);
        const auto b = study_clock.finish(true, false);
        require(a.busy_ns == b.busy_ns && a.idle_ns == b.idle_ns &&
                a.begin_ns == b.begin_ns && a.end_ns == b.end_ns,
                "eager and 100us accounting conserve the same tenure");
    }
};

extern "C" __attribute__((noinline)) void wbland2_cost_tick(wb_rule::State* s) {
    s->pass(100000, 0, 16);
}
extern "C" __attribute__((noinline)) void wbland1_cost_tick(wbland1::State* s) {
    s->pass(100000, 0, 16);
}
extern "C" __attribute__((noinline)) void pol2_cost_tick(wbmode::State* s) {
    s->pass(100000, 0, 16);
}
template<class S, class Fn> static void cost(S& s, Fn tick, bool close, bool fixed) {
    s.window.seeded = s.window.previous_valid = true;
    s.window.wall_start = 99000; s.window.previous_wall = 1000;
    s.window.remaining = close ? 1 : 16; s.fraction = 128;
    tick(&s);
    require(s.fraction == (close && !fixed ? 256u : 128u), "cost path executed");
}
static int costs(const std::string& name) {
    const bool fixed = name.find("fixed") != std::string::npos;
    const bool close = name.find("close") != std::string::npos;
    if (name.starts_with("post-")) {
        wb_rule::State s(fixed ? 1 : -1, true, 0); cost(s, wbland2_cost_tick, close, fixed);
    } else if (name.starts_with("pre-")) {
        wbland1::State s(fixed ? 1 : -1, true, 0); cost(s, wbland1_cost_tick, close, fixed);
    } else if (name.starts_with("pol2-")) {
        wbmode::State s(fixed ? 1 : 2, 0x103); cost(s, pol2_cost_tick, close, fixed);
    } else return 2;
    std::printf("PASS cost %s\n", name.c_str());
    return 0;
}

int main(int argc, char** argv) {
    if (argc == 2) return costs(argv[1]);
    if (argc != 3 && argc != 4) return 2;
    const bool mutate = argc == 4 && std::string(argv[3]) == "--cut-gated";
    if (argc == 4 && !mutate) return 2;
    std::ifstream input(argv[1]); std::ofstream output(argv[2]);
    require(input.good() && output.good(), "trace and sequence files open");
    output << "tenure,wall_ns,idle_ns,owned,f256,pol2_f256,wbland1_f256,cut_gated_f256\n";
    std::unique_ptr<Replay> s;
    uint64_t rows = 0, tenures = 0, current_id = 0, counter_diffs = 0, gated_diffs = 0;
    uint64_t first_diff = 0, first_wall = 0, windows = 0, transitions = 0;
    unsigned first_good = 0, first_bad = 0, last_fraction = 0;
    bool saw_zero = false, saw_full = false;
    std::string line;
    while (std::getline(input, line)) {
        if (line.empty() || line[0] == '#' || line.starts_with("tenure,")) continue;
        std::replace(line.begin(), line.end(), ',', ' ');
        std::istringstream row(line);
        uint64_t id, wall, idle, owned; std::string extra;
        require(bool(row >> id >> wall >> idle >> owned) && !(row >> extra), "four integer trace columns");
        require(++rows <= 1000000 && owned <= 1000000, "bounded trace");
        if (!s || id != current_id) {
            if (s) { s->finish(); windows += s->candidate.window.windows; }
            require(!s || id > current_id, "ordered tenure identifiers");
            require(idle == 0, "tenure starts with zero relative idle");
            Clock::value = wall; s = std::make_unique<Replay>(); current_id = id; ++tenures;
            s->last_wall = wall; last_fraction = 0;
        }
        require(wall >= s->last_wall && idle >= s->last_idle &&
                idle - s->last_idle <= wall - s->last_wall, "valid wall and idle increments");
        Clock::value = wall;
        s->current_signal.idle_ns = s->study_signal.idle_ns = idle;
        const auto now = s->current_clock.pass(), study_now = s->study_clock.pass();
        require(now == wall && study_now == wall, "both tenure clocks return every pass timestamp");
        const bool cut = wall >= s->next_cut;
        if (cut) s->next_cut = wall + 100000;
        // Real wbland1 and pol2 hooks are unconditional. Only this deliberate
        // mutant gates detector calls on the accounting publication interval.
        if (!mutate || cut) s->candidate.pass(now, idle, owned);
        s->reference.pass(study_now, idle, owned);
        s->previous.pass(now, idle, owned);
        if (cut) s->cut_gated.pass(now, idle, owned);
        require(s->candidate.fraction == s->reference.fraction,
                "candidate f sequence equals pinned pol2-k1 on every pass");
        require(s->previous.fraction == s->reference.fraction,
                "original wbland1 f sequence also equals pinned pol2-k1");
        const auto& a = s->candidate.window; const auto& b = s->reference.window;
        if (!mutate) require(a.remaining == b.remaining && a.width == b.width && a.windows == b.windows &&
                a.busy == b.busy && a.saturated == b.saturated &&
                a.wall_start == b.wall_start && a.idle_start == b.idle_start &&
                a.previous_wall == b.previous_wall && a.previous_idle == b.previous_idle &&
                a.seeded == b.seeded && a.previous_valid == b.previous_valid,
                "complete candidate window state equals pinned pol2-k1");
        counter_diffs += s->current_signal.busy_ns != s->study_signal.busy_ns;
        if (s->cut_gated.fraction != s->reference.fraction) {
            if (!gated_diffs) {
                first_diff = rows; first_wall = wall;
                first_good = s->reference.fraction; first_bad = s->cut_gated.fraction;
            }
            ++gated_diffs;
        }
        transitions += s->candidate.fraction != last_fraction;
        last_fraction = s->candidate.fraction;
        saw_zero |= last_fraction == 0; saw_full |= last_fraction == 256;
        output << id << ',' << wall << ',' << idle << ',' << owned << ',' << last_fraction << ','
               << s->reference.fraction << ',' << s->previous.fraction << ',' << s->cut_gated.fraction << '\n';
        s->last_wall = wall; s->last_idle = idle;
    }
    require(s != nullptr, "nonempty recorded trace");
    s->finish(); windows += s->candidate.window.windows;
    require(counter_diffs && gated_diffs && transitions >= 4 && windows >= 4,
            "trace exercises publication delay, window decisions and cut-gated divergence");
    output.close(); require(output.good(), "complete sequence written");
    std::printf("PASS wbland2 replay: rows=%llu tenures=%llu windows=%llu transitions=%llu "
                "candidate_mismatches=0 wbland1_mismatches=0 busy_counter_differences=%llu "
                "cut_gated_differences=%llu idle_endpoint=%u full_endpoint=%u\n",
                (unsigned long long)rows, (unsigned long long)tenures, (unsigned long long)windows,
                (unsigned long long)transitions, (unsigned long long)counter_diffs,
                (unsigned long long)gated_diffs, saw_zero, saw_full);
    std::printf("CONTROL first_difference_row=%llu wall_ns=%llu pol2_f256=%u cut_gated_f256=%u\n",
                (unsigned long long)first_diff, (unsigned long long)first_wall, first_good, first_bad);
}
