// The two sizes this lane moves, printed rather than asserted, so the memory bill in the report is
// a measured number and not arithmetic. Everything else the lane must not move (Op, Client,
// ThreadCtx, Shard, FlatStore, AtomicEntry, Config, Rob<64>) is locked by a static_assert in its
// own header, so a successful build of the server IS the proof for those.
#include <cstdio>
#include "src/net/rob.h"
int main() {
    std::printf("sizeof(tomo::ReadLocalRobState) = %zu\n", sizeof(tomo::ReadLocalRobState));
    std::printf("alignof(tomo::ReadLocalRobState) = %zu\n", alignof(tomo::ReadLocalRobState));
    std::printf("sizeof(tomo::Rob<64>)            = %zu\n", sizeof(tomo::Rob<64>));
    std::printf("kWriteRingCapacity               = %u\n",
                tomo::ReadLocalRobState::kWriteRingCapacity);
    std::printf("kMaxPreciseKeysetKeys            = %u\n",
                tomo::ReadLocalRobState::kMaxPreciseKeysetKeys);
    std::printf("offsetof-ish: write_tags bytes   = %zu\n",
                sizeof(tomo::ReadLocalRobState{}.write_tags));
    std::printf("write_ring bytes                 = %zu\n",
                sizeof(tomo::ReadLocalRobState{}.write_ring));
    return 0;
}
