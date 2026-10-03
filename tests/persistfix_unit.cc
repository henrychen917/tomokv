// Serverless PS1/PS2/PS14 schedules. No listener, io_uring setup or load generator.
#include "src/core/server.h"
#include "src/cmd/command.h"
#include <chrono>
#include <fcntl.h>
#include <thread>
#include <unistd.h>

using namespace tomo;
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL persistfix: %s\n", why); std::exit(1); }
}
static std::atomic<bool> waited{false};

namespace tomo {
struct PersistFixTest {
    Server server;
    AofManager& aof = server.aof();
    CommandSpec spec{};
    unsigned notifications = 0;

    PersistFixTest() {
        aof.server_ = &server;
        aof.configured_ = true;
        aof.engine_ = PersistIoEngine::Normal;
        aof.nthreads_ = 2;
        aof.writer_tid_ = 0;
        aof.chunk_in_ = std::make_unique<AofManager::ChunkChan[]>(2);
        aof.recording_.store(true);
        aof.fsync_policy_.store(AppendFsyncPolicy::Always);
        aof.auto_rewrite_percentage_.store(0);
        spec.flags = CmdFlags::Write;
    }
    void complete(Op& op) {
        op.spec = &spec;
        op.state.store(OpState::Issued);
        if (!aof.defer_completion(0, op, nullptr)) {
            op.state.store(OpState::Done, std::memory_order_release);
            ++notifications;
        }
    }
    void pass(bool posted) {
        aof.finish_completions(0, posted, this, [](void* p, Client*) {
            ++static_cast<PersistFixTest*>(p)->notifications;
        });
    }
    void ack_window() {
        Op op;
        complete(op);
        // An IO episode which latched zero can already serve. Done itself must
        // remain unavailable, both before post and after post but before fsync.
        require(aof.reply_gate_ready(0), "stale IO target window entered");
        pass(false);
        require(op.state.load() != OpState::Done && notifications == 0,
                "acknowledgement cannot precede post");
        aof.posted_sequence_.store(1);
        aof.written_sequence_.store(1);
        pass(true);
        require(op.state.load() != OpState::Done && aof.send_gate_waits() > 0,
                "acknowledgement cannot precede fsync");
        aof.durable_sequence_.store(1);
        pass(true);
        require(op.state.load() == OpState::Done && notifications == 1,
                "durable batch releases exactly one completion");
        std::puts("PASS persistfix ack-window: stale target, unposted, posted, durable");
    }
    void remote_window() {
        Op op;
        op.attach_scatter_state(reinterpret_cast<ScatterState*>(uintptr_t{1}));
        aof.chunk_in_[1].buffered.store(7);
        complete(op);
        pass(true);
        require(op.state.load() != OpState::Done,
                "remote fragment must post before final completion");
        aof.chunk_in_[1].published.store(7);
        aof.posted_sequence_.store(2);
        aof.written_sequence_.store(2);
        pass(true);
        require(op.state.load() != OpState::Done, "remote fragment must become durable");
        aof.durable_sequence_.store(2);
        pass(true);
        require(op.state.load() == OpState::Done && notifications == 1,
                "remote posted generation releases completion");
        op.detach_scatter_state();
        std::puts("PASS persistfix remote-window: final owner waits for buffered remote fragment");
    }
    void shutdown_window() {
        char path[] = "build/persistfix/shutdown-XXXXXX";
        aof.fd_ = ::mkstemp(path);
        require(aof.fd_ >= 0, "create disposable shutdown file");
        ::unlink(path);
        aof.chunk_in_[0].stopped.store(true);
        ThreadCtx writer;
        Ring ring;
        waited.store(false);
        PersistFixHooks::shutdown_wait = [] { waited.store(true, std::memory_order_release); };
        std::thread closer([&] { aof.writer_shutdown(writer, ring); });
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        while (!waited.load(std::memory_order_acquire) && aof.recording() &&
               std::chrono::steady_clock::now() < deadline) std::this_thread::yield();
        const bool held = waited.load() && aof.recording();
        aof.chunk_in_[1].stopped.store(true, std::memory_order_release);
        closer.join();
        PersistFixHooks::shutdown_wait = nullptr;
        require(held, "writer cannot close before producers stop posting");
        const auto report = aof.persistence_report();
        require(!report.recording && !report.failed && !report.drain_gave_up &&
                report.producers_stopped == 2 && report.pending_chunks == 0,
                "shutdown persistence witness is clean after barrier");
        std::puts("PASS persistfix shutdown-window: writer waited, all producers stopped, file closed");
    }
    void refusal() {
        aof.recording_.store(false);
        auto chunk = std::make_unique<AofChunk>();
        Ring ring;
        LoopSignals signals;
        require(!aof.post_chunk(1, chunk, ring, signals) && chunk,
                "refused chunk stays owned by producer");
        require(aof.persistence_report().refused == 1,
                "refused post appears in persistence report");
        std::puts("PASS persistfix refusal: retained chunk, counter and log line");
    }
};
}

static_assert(sizeof(Op) == 336 && sizeof(Client) == 1984 && sizeof(ThreadCtx) == 1408);
static_assert(sizeof(Shard) == 1440 && sizeof(FlatStore) == 944 && sizeof(Rob<64>) == 192);
static_assert(sizeof(AtomicEntry) == 144 && sizeof(Config) == 624);

int main(int argc, char** argv) {
    require(argc == 2, "usage: persistfix-unit ack|remote|shutdown|refusal");
    PersistFixTest test;
    const std::string mode(argv[1]);
    if (mode == "ack") test.ack_window();
    else if (mode == "remote") test.remote_window();
    else if (mode == "shutdown") test.shutdown_window();
    else if (mode == "refusal") test.refusal();
    else require(false, "unknown schedule");
}
