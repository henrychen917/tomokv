// Direct production writer-pass budget witness. No listener, worker, initialized ring, or timing.
#include "src/core/server.h"
#include <fcntl.h>
#include <unistd.h>

using namespace tomo;
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL budget witness: %s\n", why); std::exit(1); }
}

namespace tomo {
struct PersistFixTest {
    Server server;
    void run(PersistIoEngine engine, bool drain_all, uint32_t normal_budget) {
        AofManager& aof = server.aof();
        aof.server_ = &server;
        aof.configured_ = true;
        aof.engine_ = engine;
        aof.nthreads_ = aof.nshards_ = 8;
        aof.writer_tid_ = 0;
        aof.chunk_in_ = std::make_unique<AofManager::ChunkChan[]>(8);
        aof.recording_.store(true);
        aof.fsync_policy_.store(AppendFsyncPolicy::No);
        aof.auto_rewrite_percentage_.store(0);
        aof.fd_ = ::open("/dev/null", O_WRONLY | O_CLOEXEC);
        require(aof.fd_ >= 0, "open inert descriptor");
        ThreadCtx writer;
        Ring ring;
        LoopSignals signals;
        auto group = aof_create_group(aof, {0});
        require(group && !aof.group_dependencies_ready(*group), "hold an undecided dependency");
        // GCMT admission consumes the actual writer budget but cannot write while this
        // dependency is absent. This isolates the scheduler from kernel IO availability.
        constexpr uint32_t queued = 8 * 48;
        for (uint32_t producer = 0; producer < 8; ++producer) {
            for (uint32_t i = 0; i < 48; ++i) {
                auto chunk = std::make_unique<AofChunk>();
                chunk->group = group;
                chunk->group_commit = true;
                require(aof.post_chunk(producer, chunk, ring, signals), "enqueue every witness chunk");
            }
        }
        require(aof.pending_chunks() == queued && aof.pending_commits_.empty(), "window actually armed");
        const uint32_t expected = std::min(queued,
            drain_all || engine == PersistIoEngine::Uring ? 256u : normal_budget);
        const uint32_t consumed = aof.writer_pass(writer, ring, drain_all);
        std::printf("engine=%s drain_all=%u queued=%u consumed=%u expected=%u\n",
                    engine == PersistIoEngine::Uring ? "uring" : "epoll", drain_all,
                    queued, consumed, expected);
        require(consumed == expected && aof.pending_commits_.size() == expected,
                "production pass must consume exactly its engine-specific budget");
        require(!aof.failed() && aof.pending_chunks() == queued && aof.records_written() == 0,
                "all chunks retained; scheduler witness makes no IO/recovery claim");
    }
};
}

int main(int argc, char** argv) {
    require(argc == 2, "usage: aof-budget-unit expected-normal-budget");
    const uint32_t budget = std::strtoul(argv[1], nullptr, 10);
    require(budget > 0, "positive expected budget");
    for (auto engine : {PersistIoEngine::Normal, PersistIoEngine::Uring})
        for (bool drain : {false, true}) {
            PersistFixTest test;
            test.run(engine, drain, budget);
        }
}
