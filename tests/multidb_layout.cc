// Compile against PRE and both POST variants, then inspect the exported array.
// No main, initialization, server or measurement is needed for this layout audit.
#include "src/core/server.h"

namespace tomo {
struct CoreConcurrencyTest {
    static constexpr auto layout() {
        return std::to_array<uint64_t>({
            sizeof(Slice), sizeof(Op), sizeof(Client), sizeof(ThreadCtx), sizeof(Shard),
            sizeof(FlatStore), sizeof(Rob<64>), sizeof(AtomicEntry), sizeof(Config),
            sizeof(Server), sizeof(SnapshotManager),
            offsetof(Server, cfg_), offsetof(Server, placement_), offsetof(Server, router_),
            offsetof(Server, threads_), offsetof(Server, aof_), offsetof(Server, snapshot_),
            offsetof(Server, flipctl_), offsetof(Server, shard_owner_),
            offsetof(Server, flip_stage_), offsetof(Server, lb_stage_),
        });
    }
};
}
extern "C" { extern const auto multidb_layout_values = tomo::CoreConcurrencyTest::layout(); }
