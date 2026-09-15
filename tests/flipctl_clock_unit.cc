// Drive the production rate sampler with real command counters and synthetic
// monotonic timestamps. No threads, clocks to wait on, sockets, or gate rows.
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include "src/core/server.h"

namespace tomo {
struct CoreConcurrencyTest {
    static void require(bool condition, const char* message) {
        if (!condition) {
            std::fprintf(stderr, "FAIL flipctl clock: %s\n", message);
            std::exit(1);
        }
    }
    static void run() {
        Server server;
        server.threads_.push_back(std::make_unique<ThreadCtx>());
        FlipController controller;
        require(controller.init(true, 1), "controller allocation");
        uint64_t stamp = 1'000'000'100'000;
        double rate = 0;
        require(!controller.sample_anchored_rate(server, stamp, rate), "fresh window arms");
        const auto complete = [&](uint32_t count) {
            for (uint32_t i = 0; i < count; ++i) server.thread(0).note_command(0);
        };
        // Exactly 6000/s, with boundaries moving through fractional milliseconds.
        // A millisecond-truncating mutant reports a different rate and must fail.
        for (unsigned i = 0; i < 16; ++i) {
            const uint32_t count = i % 2 ? 6006 : 6003;
            complete(count);
            stamp += uint64_t(count) * 1'000'000'000 / 6000;
            const bool sampled = controller.sample_anchored_rate(server, stamp, rate);
            require(sampled == (i != 0), "exact two-subwindow arming");
            if (sampled)
                require(std::abs(rate - 6000) < 1e-8,
                        "constant load changed when a millisecond boundary moved");
        }
        require(!controller.sample_anchored_rate(server, stamp, rate),
                "zero elapsed time cannot provide a sample");
        // Keep the production band and two-window confirmation strict. A genuine
        // sustained 0.2% increase must still exceed the learned quiet-load band.
        const double band = controller.automatic_rate_band(0, 6000);
        for (unsigned i = 0; i < 2; ++i) {
            complete(6012);
            stamp += 1'000'000'000;
            require(controller.sample_anchored_rate(server, stamp, rate), "step sampled");
            require(rate > 6000 * (1 + band), "real rate step must remain trigger evidence");
        }
        std::puts("PASS flipctl clock: stationary fractional-ms windows and sustained real step");
    }
};
}  // namespace tomo

int main() { tomo::CoreConcurrencyTest::run(); }
