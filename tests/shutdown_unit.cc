// Serverless shutdown control/owner-hold witness. Only snapshot disk IO is link-wrapped.
#include "src/core/io_loop.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>

using namespace tomo;

static unsigned saves;
static SnapshotManager::StartResult next_result = SnapshotManager::StartResult::Started;
static void require(bool ok, const char* assertion) {
    if (!ok) {
        std::fprintf(stderr, "FAIL shutdown: %s\n", assertion);
        std::exit(1);
    }
}
extern "C" SnapshotManager::StartResult snapshot_stub(
    SnapshotManager*, Server& server, ThreadCtx&, Ring&, bool blocking, std::string& error,
    AofManager*, const char*, const char*, bool shutdown)
    asm("__wrap__ZN4tomo15SnapshotManager5startERNS_6ServerERNS_9ThreadCtxERNS_4RingEbRNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEEPNS_10AofManagerEPKcSH_b");
extern "C" SnapshotManager::StartResult snapshot_stub(
    SnapshotManager*, Server& server, ThreadCtx&, Ring&, bool blocking, std::string& error,
    AofManager*, const char*, const char*, bool shutdown) {
    ++saves;
    require(blocking && shutdown, "final save is blocking and holds post-cut writes");
    require(!server.shutting_down(), "snapshot starts before global stop");
    for (uint32_t i = 0; i < server.nthreads(); ++i)
        require(!server.thread(i).stop_flag(), "all owners alive when final save starts");
    if (next_result == SnapshotManager::StartResult::Started) server.finish_shutdown();
    else error = "injected snapshot refusal";
    return next_result;
}

struct Fixture {
    Server server;
    Ring ring; // never initialized: no io_uring, network, or owner loop
    Fixture() {
        Config cfg;
        cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
        cfg.key_lb = cfg.client_lb = 0;
        require(server.prepare_boot(cfg) && server.init(cfg), "16-shard 6:2 fixture");
        command_bind_server(&server);
        reset();
    }
    void reset() {
        saves = 0; next_result = SnapshotManager::StartResult::Started;
        server.shutting_down().store(false);
        for (uint32_t i = 0; i < server.nthreads(); ++i) server.thread(i).stop_flag().store(false);
        server.set_shutdown_snapshot_active(false);
        snapshot_bind_io(&server.thread(server.placement().ifid_threads().front()), &ring);
    }
    std::string command(std::initializer_list<const char*> words) {
        Op op;
        for (auto word : words) require(op.push_arg(Slice(word, std::strlen(word))), "argv allocation");
        op.spec = command_lookup(op.cmd_name());
        require(op.spec != nullptr, "SHUTDOWN is registered");
        op.spec->handler(server.shard(0), op);
        return {op.reply.data(), op.reply.size()};
    }
    void signal() {
        // The production signal handler's request/fallback sequence, without sending a signal.
        if (!server.request_signal_shutdown()) server.finish_shutdown();
    }
    void cron() {
        const auto io = server.placement().ifid_threads().front();
        require(server.save_cron_writer(io), "signal arms cron even with save disabled");
        server.save_cron_pass(server.thread(io), ring);
    }
};

namespace tomo {
struct CoreConcurrencyTest {
    template<bool Fused>
    static void shutdown_hold(Server& server) {
        auto loop = std::make_unique<ExLoopT<Fused>>();
        ThreadCtx owner;
        loop->srv_ = &server; loop->self_ = &owner;
        loop->snapshot_manager_ = &server.snapshot();
        using State = typename ExLoopT<Fused>::SnapshotOwnerState;
        loop->snapshot_owner_state_ = State::Draining;
        server.set_shutdown_snapshot_active(true);
        loop->snapshot_control_pass();
        require(server.shutdown_snapshot_holds() == 1, "held owner prevents admission of another snapshot");
        require(loop->snapshot_owner_state_ == State::ShutdownHeld && loop->snapshot_blocks_tasks(),
                "post-cut tasks held until final fsync");
        require(loop->snapshot_control_pass() == 0 && loop->snapshot_blocks_tasks(),
                "shutdown hold persists before fsync");
        server.set_shutdown_snapshot_active(false); // failed save must resume ordinary service
        loop->snapshot_control_pass();
        require(server.shutdown_snapshot_holds() == 0, "released owner permits a new snapshot");
        require(loop->snapshot_owner_state_ == State::None && !loop->snapshot_blocks_tasks(),
                "failed save releases post-cut tasks");
    }
};
}

int main() {
    static_assert(sizeof(Op) == 336 && sizeof(Client) == 1984 && sizeof(ThreadCtx) == 1408);
    static_assert(sizeof(Shard) == 1440 && sizeof(FlatStore) == 944 && sizeof(Rob<64>) == 192);
    static_assert(sizeof(AtomicEntry) == 144 && sizeof(Config) == 624);
    require(command_registry_init(false), "command registry");
    auto f = std::make_unique<Fixture>();
    require(f->command({"SHUTDOWN"}).empty(), "successful SHUTDOWN has no reply");
    require(saves == 1 && f->server.shutting_down(), "default SHUTDOWN saves before stop");
    f->reset();
    f->command({"SHUTDOWN", "NOSAVE"});
    require(saves == 0 && f->server.shutting_down(), "NOSAVE overrides configured save");
    f->reset(); f->server.set_save_schedule({});
    f->command({"SHUTDOWN"});
    require(saves == 0 && f->server.shutting_down(), "empty save schedule skips save");
    f->reset(); f->command({"SHUTDOWN", "SAVE"});
    require(saves == 1 && f->server.shutting_down(), "SAVE overrides empty schedule");
    f->reset(); f->server.set_save_schedule(Config{}.save);
    f->signal();
    require(!f->server.shutting_down(), "signal leaves owners alive for final save");
    f->cron();
    require(saves == 1 && f->server.shutting_down(), "signal saves through IO cron before stop");
    for (bool disable_first : {true, false}) {
        f->reset(); f->server.set_save_schedule(Config{}.save);
        if (disable_first) f->server.set_save_schedule({});
        f->signal();
        if (!disable_first) f->server.set_save_schedule({});
        f->cron();
        require(saves == 0 && f->server.shutting_down(), "CONFIG save cannot erase signal request");
    }
    for (auto failure : {SnapshotManager::StartResult::Failed, SnapshotManager::StartResult::Busy}) {
        f->reset(); f->server.set_save_schedule(Config{}.save); next_result = failure;
        require(f->command({"SHUTDOWN"}).starts_with("-ERR Errors trying to SHUTDOWN."),
                "snapshot refusal replies with shutdown error");
        require(saves == 1 && !f->server.shutting_down(), "snapshot refusal leaves server alive");
    }
    f->reset(); next_result = SnapshotManager::StartResult::Failed;
    f->signal(); f->cron();
    require(saves == 1 && !f->server.shutting_down(), "signal save failure leaves server alive");
    f->reset();
    CoreConcurrencyTest::shutdown_hold<false>(f->server);
    CoreConcurrencyTest::shutdown_hold<true>(f->server);
    std::puts("shutdown policy, signal handoff, failure and owner hold: PASS");
}
