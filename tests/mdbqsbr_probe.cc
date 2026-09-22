// Offline disassembly witnesses; no server or measurement is executed.
#include "src/core/server.h"
using namespace tomo;
extern "C" __attribute__((noipa)) uint64_t mdbqsbr_read(
        const DatabaseMap& owner, uint8_t first, uint8_t second) {
    DatabaseMap::Read read(owner);
    return uint64_t(read[first]) | (uint64_t(read[second]) << 8) |
           (uint64_t(read.epoch()) << 16);
}
#ifndef TOMO_MDBQSBR_PRE
extern "C" __attribute__((noipa)) void mdbqsbr_scope(Server& server, uint32_t tid) {
    Server::DatabaseWorkScope scope(server, tid);
}
#endif
static_assert(sizeof(Op) == 336 && sizeof(Client) == 1984 && sizeof(ThreadCtx) == 1408);
static_assert(sizeof(Shard) == 1440 && sizeof(FlatStore) == 944 && sizeof(Rob<64>) == 192);
static_assert(sizeof(AtomicEntry) == 144 && sizeof(Config) == 624 && sizeof(DatabaseMap) == 120);
