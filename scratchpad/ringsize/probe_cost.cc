// THE COST OF THE FILTER MISS, MEASURED RATHER THAN READ OFF A LISTING.
//
// Sizing the ring to the ROB window quadruples the number of tags a disjoint read may have to
// reject, and the static disassembly cannot price that: the rejected flat form compiles to a
// COMPACT 64-trip loop (eight instructions a trip), so it looks smaller in objdump and costs eight
// times more to run. This driver puts a chosen number of live precise writes in one connection's
// ring and then probes a disjoint key in a loop, so perf can count what a reject actually costs.
//
//   probe_cost <live-writes> <iterations>
//
// The probe key's low sixteen bits are fixed and collide with nothing in the ring, so every
// iteration takes the reject path -- the path an interleaved connection's reads take almost every
// time, and therefore the one whose instruction count this lane has to defend.
#include <cstdint>
#include <cstdio>
#include <cstdlib>

#include "src/net/conn.h"
#include "src/net/rob.h"

using namespace tomo;

namespace {
bool touches(const Op&, uint64_t) { return true; }
// Low sixteen bits 0xBEEF: no live write below can carry that tag.
constexpr uint64_t kProbeBase = 0x0000'0007'0000'BEEFull;
}

int main(int argc, char** argv) {
    const uint32_t live = argc > 1 ? static_cast<uint32_t>(std::atoi(argv[1])) : 19;
    const uint64_t iters = argc > 2 ? std::strtoull(argv[2], nullptr, 10) : 20000000;
    static Rob<kRobWindow> rob;
    if (!rob.prepare_read_local()) std::abort();
    int refused = -1;

    for (uint32_t i = 0; i < live; i++) {
        Op* op = rob.acquire_read_local(0);
        if (!op) { std::fprintf(stderr, "ROB full at %u\n", i); return 2; }
        op->hash = 0xF000'0000'0000'0000ull | (uint64_t{i} << 24) | i;
        rob.mark_current_write();
        if (!rob.refine_current_write_hash(op->hash) && !refused) {
            // A refusal is the capacity fallback firing: unreachable on a ring sized to the window,
            // and on the sixteen-slot ring it is the whole defect. The write STILL EXECUTES -- so
            // this driver still publishes it, exactly as the parser does, and the next acquire
            // turns it into the conservative generation that forces every later read down the
            // exact walk. Measuring the refusal as a `break` would have measured a ring that never
            // received the seventeenth write, which is not a server anyone runs.
            refused = i;
        }
        rob.publish();
    }
    // The parser commits a staged candidate on the NEXT acquire. Spend one frame doing that, so the
    // measured loop below runs against a committed ring rather than a staged one.
    Op* op = rob.acquire_read_local(0);
    if (!op) std::abort();
    op->hash = kProbeBase;
    rob.publish();

    uint64_t conflicts = 0;
    for (uint64_t i = 0; i < iters; i++) {
        // Vary bits ABOVE the tag so the compiler cannot hoist the call while the reject path
        // stays byte-for-byte the one under study.
        const uint64_t h = kProbeBase + ((i & 0xFF) << 20);
        conflicts += rob.read_local_write_conflicts(h, touches) ? 1 : 0;
    }
    std::printf("live=%u iters=%llu conflicts=%llu%s", live,
                static_cast<unsigned long long>(iters),
                static_cast<unsigned long long>(conflicts),
                refused >= 0 ? "" : "\n");
    if (refused >= 0)
        std::printf(" RING FULL at write %d: conservative generation, exact walk forced\n",
                    refused);
    return 0;
}
