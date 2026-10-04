// Serverless shutdown control/owner-hold witness. Only snapshot disk IO is link-wrapped.
#include "src/core/io_loop.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <memory>

using namespace tomo;

static unsigned saves;
static bool real_save;
static uint64_t test_clock_ns;
extern "C" int __real_clock_gettime(clockid_t, timespec*);
extern "C" int __wrap_clock_gettime(clockid_t id, timespec* value) {
    if (id != CLOCK_MONOTONIC || !test_clock_ns) return __real_clock_gettime(id, value);
    value->tv_sec = test_clock_ns / 1'000'000'000;
    value->tv_nsec = test_clock_ns % 1'000'000'000;
    return 0;
}
static SnapshotManager::StartResult next_result = SnapshotManager::StartResult::Started;
static void require(bool ok, const char* assertion) {
    if (!ok) {
        std::fprintf(stderr, "FAIL shutdown: %s\n", assertion);
        std::exit(1);
    }
}
extern "C" SnapshotManager::StartResult real_snapshot_start(
    SnapshotManager*, Server&, ThreadCtx&, Ring&, bool, std::string&, AofManager*,
    const char*, const char*, bool)
    asm("__real__ZN4tomo15SnapshotManager5startERNS_6ServerERNS_9ThreadCtxERNS_4RingEbRNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEEPNS_10AofManagerEPKcSH_b");
extern "C" SnapshotManager::StartResult snapshot_stub(
    SnapshotManager*, Server& server, ThreadCtx&, Ring&, bool blocking, std::string& error,
    AofManager*, const char*, const char*, bool shutdown)
    asm("__wrap__ZN4tomo15SnapshotManager5startERNS_6ServerERNS_9ThreadCtxERNS_4RingEbRNSt7__cxx1112basic_stringIcSt11char_traitsIcESaIcEEEPNS_10AofManagerEPKcSH_b");
extern "C" SnapshotManager::StartResult snapshot_stub(
    SnapshotManager* manager, Server& server, ThreadCtx& writer, Ring& ring,
    bool blocking, std::string& error, AofManager* rewrite,
    const char* directory, const char* filename, bool shutdown) {
    if (real_save)
        return real_snapshot_start(manager, server, writer, ring, blocking, error,
                                   rewrite, directory, filename, shutdown);
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
    Fixture(ThreadMode mode = ThreadMode::Split, const char* directory = ".") {
        Config cfg;
        cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
        cfg.thread_mode = mode; cfg.dir = directory; cfg.net_io = NetIoEngine::Epoll;
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
    static void busy_snapshot(Fixture& f) {
        auto& server = f.server;
        auto& snapshot = server.snapshot();
        f.reset(); server.set_save_schedule(Config{}.save);
        snapshot.phase_.store(SnapshotManager::Phase::Capture);
        snapshot.writer_tid_.store(server.placement().ifid_threads().front());
        real_save = true; // exercise actual admission; it must refuse before touching a ring
        require(f.command({"SHUTDOWN"}).starts_with("-ERR Errors trying to SHUTDOWN."),
                "saving owner refuses recursive shutdown during BGSAVE");
        require(saves == 0 && !server.shutting_down() && snapshot.in_progress(),
                "busy shutdown preserves the in-flight BGSAVE");
        test_clock_ns = 1;
        f.signal(); f.cron();
        require(saves == 0 && (server.live_save_armed_.load() & Server::kSignalShutdown),
                "signal yields to the saving owner with BGSAVE still running");
        test_clock_ns += Server::kShutdownSaveWaitNs;
        f.cron();
        require(!(server.live_save_armed_.load() & Server::kSignalShutdown) &&
                !server.shutting_down() && snapshot.in_progress(),
                "busy shutdown retry is bounded and preserves the running snapshot");
        test_clock_ns = 0;
        f.signal(); f.cron();
        snapshot.phase_.store(SnapshotManager::Phase::Idle);
        real_save = false;
        f.cron();
        require(saves == 1 && server.shutting_down(),
                "BGSAVE completion requires a fresh final save before stopping");
    }

    // No listeners or worker threads: drive the real per-owner snapshot state machines
    // serially through their production progress hook and epoll mailboxes.
    template<bool Fused>
    static void saving_owner(SnapshotManager::Phase stall_phase, bool background = false) {
        using Phase = SnapshotManager::Phase;
        const bool stall = stall_phase != Phase::Idle;
        char path[] = "build/shutdown-owner-XXXXXX";
        require(::mkdtemp(path), "private snapshot directory");
        auto f = std::make_unique<Fixture>(Fused ? ThreadMode::Fused : ThreadMode::Split, path);
        auto& server = f->server;
        auto& writer = server.thread(server.placement().ifid_threads().front());
        g_ring_epoll_mode = true;
        require(f->ring.init(64), "serverless writer mailbox");
        struct Driver {
            std::vector<std::unique_ptr<ExLoopT<Fused>>> owners;
            SnapshotManager* snapshot;
            Phase stall_phase;
            unsigned stalled_passes = 0;
            unsigned passes = 0;
            uint32_t progress() {
                require(++passes <= 4096, "snapshot owner simulation makes bounded progress");
                if (stall_phase != Phase::Idle && snapshot->phase() == stall_phase &&
                    (stall_phase != Phase::Capture || snapshot->frame_count_ != 0)) {
                    require(++stalled_passes <= 4,
                            "shutdown snapshot yields on stalled saving owner");
                    test_clock_ns += Server::kShutdownSaveWaitNs;
                    return 0;
                }
                uint32_t work = 0;
                for (auto& owner : owners) {
                    owner->ring_.for_each_cqe([&](io_uring_cqe* event) { owner->on_cqe(event); });
                    work += owner->snapshot_control_pass();
                }
                return work;
            }
        } driver{{}, &server.snapshot(), stall_phase};
        for (auto tid : server.placement().ex_threads()) {
            auto owner = std::make_unique<ExLoopT<Fused>>();
            owner->srv_ = &server; owner->self_ = &server.thread(tid);
            require(owner->ring_.init(64), "serverless executor mailbox");
            server.thread(tid).set_ring(&owner->ring_);
            driver.owners.push_back(std::move(owner));
        }
        writer.bind_fused_executor_hooks(&driver,
            [](void* value) { return static_cast<Driver*>(value)->progress(); },
            [](void* value, SnapshotManager* snapshot) {
                // The fused writer is also the first executor in placement order.
                static_cast<Driver*>(value)->owners.front()->begin_snapshot(snapshot);
            });
        if (background) {
            std::string error;
            require(real_snapshot_start(&server.snapshot(), server, writer, f->ring, false, error,
                                        nullptr, nullptr, nullptr, false) == SnapshotManager::StartResult::Started,
                    "real BGSAVE enters capture on the future shutdown owner");
            require(server.snapshot().phase() == Phase::Capture,
                    "BGSAVE window is open before shutdown request");
            f->signal(); real_save = true; f->cron(); real_save = false;
            require(server.snapshot().phase() == Phase::Capture && !server.shutting_down(),
                    "shutdown yields without stealing the BGSAVE writer");
            for (unsigned pass = 0; pass < 1024 && server.snapshot().in_progress(); ++pass) {
                driver.progress(); server.snapshot().writer_pass(writer, f->ring, true);
            }
            require(!server.snapshot().in_progress() && !server.shutting_down(),
                    "pre-request BGSAVE completion does not authorize shutdown");
        }
        test_clock_ns = 1; real_save = true;
        std::string reply;
        if (background) f->cron();
        else reply = f->command({"SHUTDOWN"});
        real_save = false; test_clock_ns = 0;
        if (stall) {
            require(driver.stalled_passes != 0 && reply.find("coordination timed out") != std::string::npos &&
                    !server.shutting_down(), "stalled saving owner returns a bounded refusal");
            require(server.snapshot().phase() == SnapshotManager::Phase::Failed,
                    "timed-out epoch remains owned until cancellation is acknowledged");
            if (stall_phase == Phase::Capture)
                require(server.snapshot().frame_count_ != 0, "capture timeout occurs after a real frame write");
            driver.stall_phase = Phase::Idle;
            for (unsigned pass = 0; pass < 128 && server.snapshot().in_progress(); ++pass) {
                driver.progress(); server.snapshot().writer_pass(writer, f->ring, true);
            }
            require(!server.snapshot().in_progress() && !server.snapshot_atomic_barrier_.load(),
                    "saving owner resumes and releases cancelled epoch and barrier");
            real_save = true;
            require(f->command({"SHUTDOWN"}).empty(), "shutdown retry completes after owner resumes");
            real_save = false;
        } else require(reply.empty(), "real snapshot shutdown succeeds on saving owner");
        require(server.shutting_down(), "saving owner stops only after successful finalization");
        std::string error;
        const auto plan = snapshot_read_plan((std::string(path) + "/dump.tomo").c_str(), 16, error);
        require(plan != nullptr,
                "saving owner writes a loadable snapshot without changing its format");
        if (background) require(plan->epoch == 2, "signal saves a fresh epoch after BGSAVE");
        writer.bind_fused_executor_hooks(nullptr, nullptr, nullptr);
        for (auto tid : server.placement().ex_threads()) server.thread(tid).set_ring(nullptr);
        driver.owners.clear(); f.reset();
        std::filesystem::remove_all(path);
        std::printf("shutdown saving owner %s phase=%u %s: PASS\n", Fused ? "1s" : "2s",
                    unsigned(stall_phase), background ? "BGSAVE/signal" : stall ? "timeout/retry" : "completion");
    }
    static void finalize(Server& server) {
        auto& snapshot = server.snapshot();
        snapshot.server_ = &server;
        snapshot.phase_.store(SnapshotManager::Phase::Capture);
        server.set_shutdown_snapshot_active(true);
        require(snapshot.complete_file_success(), "final snapshot completion succeeds");
        require(server.shutting_down() && snapshot.phase() == SnapshotManager::Phase::Idle,
                "successful finalization publishes stop before releasing epoch");
        for (uint32_t tid = 0; tid < server.nthreads(); ++tid)
            require(server.thread(tid).stop_flag(), "successful finalization stops every owner");
    }
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
        Ring unopened;
        std::string error;
        require(real_snapshot_start(&server.snapshot(), server, owner, unopened, true, error,
                                    nullptr, nullptr, nullptr, false) == SnapshotManager::StartResult::Busy,
                "new snapshot refuses held previous epoch before touching a ring");
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
        if (disable_first) {
            require(f->server.shutting_down(), "no-save signal stops without waiting for IO cron");
            continue;
        }
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
    CoreConcurrencyTest::busy_snapshot(*f);
    f->reset();
    CoreConcurrencyTest::shutdown_hold<false>(f->server);
    CoreConcurrencyTest::shutdown_hold<true>(f->server);
    CoreConcurrencyTest::finalize(f->server);
    f.reset();
    using Phase = SnapshotManager::Phase;
    for (auto phase : {Phase::Idle, Phase::Preparing, Phase::Freeze, Phase::Mark, Phase::Capture}) {
        CoreConcurrencyTest::saving_owner<false>(phase);
        CoreConcurrencyTest::saving_owner<true>(phase);
    }
    CoreConcurrencyTest::saving_owner<false>(Phase::Idle, true);
    CoreConcurrencyTest::saving_owner<true>(Phase::Idle, true);
    std::puts("shutdown policy, signal handoff, failure and owner hold: PASS");
}
