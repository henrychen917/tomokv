// ST4.13: inspect actual allocations, not just sizeof or intra-object offsets.
#include "src/core/io_loop.h"
#include <cstdio>
#include <memory>
#include <vector>
using namespace tomo;
static unsigned failures = 0;
static void check(bool good, const char* label, unsigned overlaps) {
    std::printf("%s placement %s: cross-object shared lines=%u\n", good ? "PASS" : "FAIL", label, overlaps);
    failures += !good;
}
template<class T> static void adjacent(const char* name) {
    std::vector<T> rows(16);
    unsigned overlaps = 0;
    for (unsigned i = 1; i < rows.size(); ++i) {
        auto first = reinterpret_cast<uintptr_t>(&rows[i]);
        auto previous_end = reinterpret_cast<uintptr_t>(&rows[i-1]) + sizeof(T) - 1;
        overlaps += first / 64 == previous_end / 64;
    }
    check(!overlaps, name, overlaps);
}
int main() {
    adjacent<IoLoop>("IoLoop vector");
    adjacent<ExLoop>("ExLoop vector");
    adjacent<FusedExLoop>("FusedExLoop vector");
    std::vector<std::unique_ptr<StoreSizeState>> states;
    unsigned overlaps = 0;
    for (unsigned i = 0; i < 16; ++i) states.push_back(std::make_unique<StoreSizeState>());
    for (unsigned i = 0; i < states.size(); ++i) for (unsigned j = i+1; j < states.size(); ++j) {
        auto a = reinterpret_cast<uintptr_t>(states[i].get());
        auto b = reinterpret_cast<uintptr_t>(states[j].get());
        overlaps += a / 64 == b / 64;
    }
    check(!overlaps, "StoreSizeState heap", overlaps);
    Rob<64> rob;
    unsigned straddles = 0;
    for (unsigned i = 0; i < 64; ++i) {
        Op* op = rob.acquire();
        for (auto& arg : op->argv) {
            auto a = reinterpret_cast<uintptr_t>(&arg);
            straddles += a / 64 != (a + sizeof(arg) - 1) / 64;
        }
        rob.publish();
    }
    check(!straddles, "ROB inline argv slices", straddles);
    return failures ? 1 : 0;
}
