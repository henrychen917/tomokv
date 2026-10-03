// Serverless simulation using the production membership/forwarding mask, no owner threads.
#include "src/core/climon_mask.h"
#include <cstdio>
#include <cstdlib>
#include <initializer_list>

using tomo::ClimonIoMask;

static void require(bool ok, const char* assertion) {
    if (!ok) {
        std::fprintf(stderr, "FAIL climon mask: %s\n", assertion);
        std::exit(1);
    }
}

int main() {
    for (const char* lane : {"tracking", "monitor"}) {
        for (uint32_t low = 0; low < 64; ++low) {
            for (bool clear_high : {true, false}) {
                std::atomic<uint64_t> words[2]{};
                const uint32_t high = low + 64;
                auto set = [&](uint32_t owner, bool present) {
                    ClimonIoMask::set(words[0], words[1], owner, present);
                };
                auto load = [&] { return ClimonIoMask::load(words[0], words[1]); };
                require(!load(), "fresh mask is empty");
                set(low, true);
                require(!load().contains(high), "low owner does not arm owner i+64");
                set(high, true);
                require(load().contains(low) && load().contains(high), "both owners armed");
                // Disconnect, TRACKING OFF and migration refresh all use this same clear.
                set(clear_high ? high : low, false);
                require(load().contains(clear_high ? low : high),
                        "disarm retains the other owner at distance 64");
                require(!load().contains(clear_high ? high : low), "disarmed owner absent");
                set(clear_high ? low : high, false);
                require(!load(), "last owner disarms the mask");

                ClimonIoMask posted;
                posted.add(low);
                require(!posted.contains(high), "migration forwards to owner i+64");
                posted.add(high);
                require(posted.contains(low) && posted.contains(high), "forwarding deduplicates both owners");
            }
        }
        std::printf("climon mask %s: PASS (64 owner pairs, both disarm directions)\n", lane);
    }
}
