// Serverless PS1/PS2/PS14 schedules. No listener, io_uring setup or load generator.
#include "src/core/server.h"
#include "src/cmd/command.h"
#include "src/cmd/debug.h"
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
    CommandSpec spec{"SET", 3, 3, CmdFlags::Write, nullptr, 1, 1, 1};
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
    void frame_state() {
        command_bind_server(&server);
        Shard shard;
        auto query = [&](bool extra = false) {
            Op op;
            op.push_arg(Slice("DEBUG"));
            op.push_arg(Slice("AOF-FRAME-STATE"));
            if (extra) op.push_arg(Slice("1"));
            cmd_debug(shard, op);
            return std::string(op.reply.data(), op.reply.size());
        };
        require(query().starts_with("-ERR DEBUG command not allowed"), "frame observer is DEBUG-gated");
        const_cast<Config&>(server.cfg()).enable_debug_command = DebugCommandMode::Yes;
        require(query() == "*3\r\n:0\r\n:0\r\n:0\r\n", "frame observer reports zero without arming");
        aof.pending_chunks_.store(7);
        aof.posted_sequence_.store(11);
        require(query() == "*3\r\n:0\r\n:7\r\n:11\r\n", "frame observer reads actual counters");
        require(query(true).starts_with("-ERR unknown subcommand"), "frame observer rejects arguments");
        aof.recording_.store(false);
        require(query() == "-ERR appendonly is disabled\r\n", "frame observer rejects AOF-off");
        aof.pending_chunks_.store(0);
        command_bind_server(nullptr);
        std::puts("PASS frame-state: DEBUG permission, zero/live counters, arity, AOF-off");
    }
    void frame_order(bool drain_all, uint32_t committer, bool break_guard) {
        // Drive the actual production writer without a listener, worker, or initialized Ring.
        // Producer 0's fragment, producer 1's fragment/large record, GCMT on either producer.
        char path[] = "build/persistfix/frameorder-XXXXXX";
        aof.fd_ = ::mkstemp(path);
        require(aof.fd_ >= 0, "create disposable frame-order file");
        ::unlink(path);
        aof.nshards_ = 2;
        aof.next_sequence_.assign(2, 0);
        aof.fsync_policy_.store(AppendFsyncPolicy::No);
        ThreadCtx writer;
        Ring ring;
        LoopSignals signals;
        auto group = aof_create_group(aof, {0, 1});
        require(bool(group), "create real group decision");
        group->ticket.store(1);
        auto post = [&](uint32_t producer, uint32_t sequence, uint32_t flags,
                        bool fragment = false) {
            auto chunk = std::make_unique<AofChunk>();
            chunk->sid = static_cast<int32_t>(producer);
            chunk->sequence = sequence;
            chunk->flags = flags;
            chunk->bytes.assign(8, 'L'); // physical-framing unit; no logical replay claim
            if (fragment) { chunk->group = group; chunk->group_fragment_last = true; }
            require(aof.post_chunk(producer, chunk, ring, signals), "post scheduled frame");
        };
        post(0, 0, 0, true);
        post(1, 0, 0, true);
        AofOwnerContext context{committer, &ring, &signals};
        require(aof_commit_group(aof, group, 1, context), "post GCMT after both fragments");
        require(aof.pending_chunks() == 3, "complete group is queued before LargeBegin");
        post(1, 1, AofFrameLargeBegin);
        require(aof.pending_chunks() == 4, "LargeBegin is queued before writer release");
        aof.writer_pass(writer, ring, drain_all);
        require(aof.stream_owner_.large_token() && aof.pending_commits_.size() == 1 &&
                aof.group_dependencies_ready(*group), "ready GCMT and OPEN large record coexist");
        if (break_guard) {
            // Throwaway negative control: bypass writer_pass's large-token guard using an
            // unrelated open token. The exact next assertion must reject the premature GCMT.
            AofStreamOwner unrelated;
            uint32_t budget = 1;
            io_uring_sqe* last_write = nullptr;
            aof.drain_pending_commits(*unrelated.open_token(), budget, ring, last_write);
        }
        require(aof.control_defers() > 0 && aof.groups_committed() == 0,
                "ready GCMT MUST stay outside the open large record");
        // More frames than either writer budget. Feed a bounded producer channel in batches,
        // preserving the live test's source order even across partial/idle drain passes.
        for (uint32_t sequence = 2; sequence <= 273; ++sequence) {
            post(1, sequence, sequence == 273 ? uint32_t{AofFrameLargeEnd} : 0u);
            if (sequence % 32 == 0 || sequence == 273) {
                while (aof.chunk_in_[1].depth()) aof.writer_pass(writer, ring, drain_all);
                if (sequence < 273)
                    require(aof.groups_committed() == 0, "no GCMT in any large-record continuation");
            }
        }
        aof.writer_pass(writer, ring, drain_all);
        require(!aof.failed() && aof.pending_chunks() == 0 && aof.groups_committed() == 1 &&
                aof.stream_owner_.open_token(), "GCMT commits only after LargeEnd");
        std::printf("PASS frame-order: drain_all=%u committer=%u deferrals=%llu\n",
                    drain_all, committer, static_cast<unsigned long long>(aof.control_defers()));
    }
};
}

static_assert(sizeof(Op) == 336 && sizeof(Client) == 1984 && sizeof(ThreadCtx) == 1408);
static_assert(sizeof(Shard) == 1440 && sizeof(FlatStore) == 944 && sizeof(Rob<64>) == 192);
static_assert(sizeof(AtomicEntry) == 144 && sizeof(Config) == 624);

int main(int argc, char** argv) {
    require(argc == 2, "usage: persistfix-unit ack|remote|shutdown|refusal|frameorder|frameorder-no-guard");
    const std::string mode(argv[1]);
    if (mode == "frameorder" || mode == "frameorder-no-guard") {
        { PersistFixTest test; test.frame_state(); }
        for (bool drain_all : {false, true})
            for (uint32_t committer : {0u, 1u}) {
                PersistFixTest test;
                test.frame_order(drain_all, committer, mode == "frameorder-no-guard");
            }
        return 0;
    }
    PersistFixTest test;
    if (mode == "ack") test.ack_window();
    else if (mode == "remote") test.remote_window();
    else if (mode == "shutdown") test.shutdown_window();
    else if (mode == "refusal") test.refusal();
    else require(false, "unknown schedule");
}
