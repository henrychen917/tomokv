// PRE library writes the AOF; POST library must parse and replay it. No server is started.
#include "src/core/server.h"
#include <fcntl.h>
#include <unistd.h>

using namespace tomo;
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL map format: %s\n", why); std::exit(1); }
}
static_assert(sizeof(DatabaseMap::Map) == 260);
static_assert(sizeof(std::array<uint8_t, 256>) == 256);

namespace tomo {
struct PersistFixTest {
    Server server;
    void write(const char* path, bool grouped) {
        AofManager& aof = server.aof();
        aof.server_ = &server;
        aof.configured_ = true;
        aof.engine_ = PersistIoEngine::Normal;
        aof.nthreads_ = aof.nshards_ = 1;
        aof.writer_tid_ = 0;
        aof.chunk_in_ = std::make_unique<AofManager::ChunkChan[]>(1);
        aof.next_sequence_.assign(1, 0);
        aof.recording_.store(true);
        aof.fsync_policy_.store(AppendFsyncPolicy::No);
        aof.auto_rewrite_percentage_.store(0);
        aof.fd_ = ::open(path, O_CREAT | O_EXCL | O_RDWR | O_CLOEXEC, 0600);
        require(aof.fd_ >= 0 && aof.write_header_normal(), "create and write real AOF header");
        ThreadCtx writer;
        Ring ring;
        LoopSignals signals;
        AofOwnerContext context{0, &ring, &signals};
        AofProducer producer;
        producer.init(&aof, 0, 0);
        DatabaseMap::Map map;
        std::swap(map[0], map[1]);
        map.epoch = 0xdeadbeef; // This in-memory field MUST NOT enter the payload.
        if (grouped) {
            auto group = aof_create_group(aof, {0});
            require(group && producer.begin_group(group), "begin real group");
            require(producer.record_group_database_map(map.data()), "serialize grouped mapping");
            group->ticket.store(1);
            require(producer.finish_group() && producer.flush(context), "post real group fragment");
            require(aof_commit_group(aof, group, 1, context), "post real group commit");
        } else {
            require(producer.record_database_map(map.data()) && producer.flush(context),
                    "serialize and post plain mapping");
        }
        for (unsigned i = 0; aof.pending_chunks() && i < 16; ++i)
            aof.writer_pass(writer, ring, true);
        require(!aof.failed() && !aof.pending_chunks() && aof.records_written() > 0,
                "writer completed nonempty file");
        require(!grouped || aof.groups_committed() == 1, "group really committed");
        require(::fdatasync(aof.fd_) == 0, "sync fixture");
        std::printf("PASS PRE write: grouped=%u payload=256 sizeof(Map)=260\n", grouped);
    }
    void read(const char* path) {
        bool exists = false;
        std::string warning, error;
        auto plan = aof_read_plan(path, 1, false, exists, warning, error);
        require(plan && exists && warning.empty(), error.c_str());
        require(plan->sections.size() == 1 && !plan->sections[0].empty(), "nonempty replay stream");
        const auto& record = plan->sections[0];
        require(snapshot_get_u64(record.data() + 16) == 256 && record.size() == 40 + 256,
                "exact mapping payload excludes epoch");
        Shard shard;
        shard.init_private(&server, 0, TypeLimits{}, StreamLimits{});
        require(aof_load_shard(*plan, server, shard, error), error.c_str());
        {
            DatabaseMap::Read restored(server.databases());
            for (unsigned i = 0; i < 256; ++i)
                require(restored[i] == (i < 2 ? 1 - i : i), "replayed every map byte");
        }
        // A regression which serializes sizeof(Map) must fail the replay contract.
        auto& corrupt = plan->sections[0];
        corrupt.resize(40 + 260);
        snapshot_put_u64(corrupt.data() + 16, 260);
        error.clear();
        require(!aof_load_shard(*plan, server, shard, error) &&
                    error == "invalid AOF database mapping", "260-byte negative control rejected");
        std::puts("PASS POST replay: all 256 bytes restored; 260-byte payload rejected");
    }
};
}

int main(int argc, char** argv) {
    require(argc == 3, "usage: map-format-unit write|write-group|read path");
    PersistFixTest test;
    const std::string command(argv[1]);
    if (command == "write" || command == "write-group") test.write(argv[2], command == "write-group");
    else if (command == "read") test.read(argv[2]);
    else require(false, "unknown command");
}
