// Bounded production AOF/QSBR cycle. No server, listener, or synthetic queue.
#include "src/core/read_local.h"
#include <array>
#include <csignal>
#include <cstdio>
#include <cstdlib>
#include <thread>
#include <unistd.h>

using namespace tomo;
static void need(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL eoffix AOF: %s\n", why); std::_Exit(1); }
}
static void deadline(int) {
    constexpr char message[] = "FAIL eoffix AOF: full AOF channel and pinned QSBR ring did not make progress\n";
    const ssize_t written = ::write(STDERR_FILENO, message, sizeof(message)-1);
    (void)written;
    std::_Exit(1);
}

namespace tomo {
struct CoreConcurrencyTest {
    static void participants(Server& server, bool read_local = true) {
        server.read_local_state_ = std::make_unique<ReadLocalServerState>();
        server.cfg_.read_local = read_local;
        for (unsigned i = 0; i != 2; ++i) {
            auto thread = std::make_unique<ThreadCtx>();
            need(thread->init_read_local_state(), "allocate real QSBR participant");
            thread->publish_read_local_parked(server.read_local_epoch());
            server.threads_.push_back(std::move(thread));
        }
    }
};

struct PersistFixTest {
    static void self_writer() {
        Server server;
        CoreConcurrencyTest::participants(server, false);
        AofManager& aof = server.aof();
        aof.server_ = &server;
        aof.configured_ = true;
        aof.engine_ = PersistIoEngine::Normal;
        aof.nthreads_ = 2;
        aof.nshards_ = 1;
        aof.writer_tid_ = 0;
        aof.next_sequence_.assign(1, 0);
        aof.chunk_in_ = std::make_unique<AofManager::ChunkChan[]>(2);
        aof.fsync_policy_.store(AppendFsyncPolicy::No);
        aof.auto_rewrite_percentage_.store(0);
        aof.recording_.store(true);
        char path[] = "build/eoffix/self-writer-XXXXXX";
        aof.fd_ = ::mkstemp(path);
        need(aof.fd_ >= 0, "create private AOF frame file");
        ::unlink(path);
        Ring ring;
        need(ring.init(64), "initialize writer completion ring");
        aof.writer_ring_.store(&ring);
        LoopSignals signals;
        for (uint32_t i = 0; i != 64; ++i) {
            auto chunk = std::make_unique<AofChunk>();
            chunk->sid = 0;
            chunk->sequence = i;
            chunk->bytes.assign(8, 'L');
            need(aof.post_chunk(0, chunk, ring, signals), "fill writer's own real channel");
        }
        need(aof.chunk_in_[0].depth() == 64 && !aof.chunk_in_[0].producer_free_slots(),
             "writer's own channel is full before GCMT");
        auto group = aof_create_group(aof, {0});
        AofOwnerContext context{0, &ring, &signals};
        need(group && aof_commit_group(aof, group, 1, context), "writer drains its channel while posting GCMT");
        need(signals.full_events > 0 && aof.next_sequence_[0] == 64 && !aof.failed(),
             "actual backpressure drained every queued frame without reentering execution");
        AofChunk* chunk = nullptr;
        while (aof.chunk_in_[0].recv(chunk)) { delete chunk; aof.chunk_in_[0].retire(); }
        aof.pending_chunks_.store(0);
        aof.recording_.store(false);
        aof.writer_ring_.store(nullptr);
        std::puts("PASS eoffix AOF self-writer");
    }

    static void run(bool pressure) {
        Server server;
        CoreConcurrencyTest::participants(server);
        AofManager& aof = server.aof();
        aof.server_ = &server;
        aof.configured_ = true;
        aof.engine_ = PersistIoEngine::Normal;
        aof.nthreads_ = 2;
        aof.writer_tid_ = 0;
        aof.chunk_in_ = std::make_unique<AofManager::ChunkChan[]>(2);
        aof.recording_.store(true);
        Ring ring;
        need(ring.init(64), "initialize producer completion ring");
        LoopSignals signals;
        ReadLocalDeferredQueue retired;
        need(retired.init(&server, &server.thread(0)), "allocate real retire ring");
        std::array<unsigned char, ReadLocalDeferredQueue::kCapacity+1> payload{};
        uint32_t reclaimed = 0;
        auto reclaim = [](void* owner, void*, size_t) { ++*static_cast<uint32_t*>(owner); };
        const uint64_t stamp = server.read_local_epoch();
        server.thread(1).publish_read_local_tick(stamp);
        for (unsigned i = 0; i != ReadLocalDeferredQueue::kCapacity; ++i)
            retired.defer(&reclaimed, &payload[i], 0, reclaim);
        need(retired.size() == 4096 && retired.drain_ready() == 0 && reclaimed == 0,
             "full sealed retire ring is pinned by the producer");
        uint32_t hint = 1;
        need(server.read_local_grace_floor(stamp, hint) == stamp,
             "producer's active epoch really blocks reclamation");
        if (pressure) {
            for (unsigned i = 0; i != 64; ++i) {
                auto chunk = std::make_unique<AofChunk>();
                need(aof.post_chunk(1, chunk, ring, signals), "fill real AOF producer channel");
            }
            need(aof.chunk_in_[1].depth() == 64 && !aof.chunk_in_[1].producer_free_slots(),
                 "every AOF channel slot is occupied before commit");
        }
        std::thread writer;
        if (pressure) writer = std::thread([&] {
            // This is the captured writer's order: the owner replacement must
            // finish a real capacity grace before it can drain the AOF channel.
            retired.defer(&reclaimed, &payload.back(), 0, reclaim);
            need(reclaimed == 4096, "capacity grace reclaimed the pinned batch");
            AofChunk* chunk = nullptr;
            need(aof.chunk_in_[1].recv(chunk), "writer can now release one AOF slot");
            delete chunk;
            aof.chunk_in_[1].retire();
        });
        auto group = aof_create_group(aof, {0, 1}, 0);
        AofOwnerContext context{1, &ring, &signals};
        need(group && aof_commit_group(aof, group, 1, context), "GCMT post completed");
        if (pressure) {
            writer.join();
            need(signals.full_events > 0, "the actual GCMT post encountered backpressure");
            need(server.thread(1).read_local_publication() > stamp,
                 "the blocked producer crossed the retirement epoch");
        } else {
            need(signals.full_events == 0 && server.thread(1).read_local_publication() == stamp,
                 "uncontended commit does not add a QSBR publication");
        }
        AofChunk* chunk = nullptr;
        while (aof.chunk_in_[1].recv(chunk)) { delete chunk; aof.chunk_in_[1].retire(); }
        aof.pending_chunks_.store(0);
        aof.recording_.store(false);
        for (unsigned i = 0; i != 2; ++i)
            server.thread(i).publish_read_local_parked(server.read_local_epoch());
        retired.drain_shutdown();
        std::printf("PASS eoffix AOF pressure=%u\n", pressure);
    }
};
}

int main(int argc, char** argv) {
    need(argc == 3, "usage: eoffix-aof epoll|uring open|pressure|writer");
    g_ring_epoll_mode = std::string(argv[1]) == "epoll";
    std::signal(SIGALRM, deadline);
    ::alarm(5);
    if (std::string(argv[2]) == "writer") PersistFixTest::self_writer();
    else PersistFixTest::run(std::string(argv[2]) == "pressure");
    ::alarm(0);
}
