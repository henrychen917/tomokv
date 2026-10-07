// Serverless SAVE/worker-supervisor schedules. No listener, worker loop, or load generator.
#include "src/core/io_loop.h"
#include <filesystem>
#include <fstream>
#include <functional>
#include <memory>

using namespace tomo;
static thread_local uint64_t clock_ns = 0, clock_step = 0;
static thread_local std::function<void()> clock_hook;
static std::function<void()> sync_hook;
extern "C" int __real_fdatasync(int);
extern "C" int __wrap_fdatasync(int fd) {
    if (sync_hook) sync_hook();
    return __real_fdatasync(fd);
}
extern "C" int __real_clock_gettime(clockid_t, timespec*);
extern "C" int __wrap_clock_gettime(clockid_t id, timespec* out) {
    if (id != CLOCK_MONOTONIC || !clock_ns) return __real_clock_gettime(id, out);
    clock_ns += clock_step;
    if (clock_hook) clock_hook();
    out->tv_sec = clock_ns / 1'000'000'000;
    out->tv_nsec = clock_ns % 1'000'000'000;
    return 0;
}
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL shutsave: %s\n", why); std::exit(1); }
}
static std::string bytes(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}

namespace tomo {
struct PersistFixTest {
    static void rewriting(Server& server, bool active) { server.aof().rewrite_in_progress_.store(active); }
};
struct CoreConcurrencyTest {
    using Phase = SnapshotManager::Phase;
    using Lifetime = DatabaseMap::WorkerLifetime;

    static void phase(Server& server, Phase value) { server.snapshot().phase_.store(value); }

    static void join(bool persistence, bool hang, bool rewrite) {
        Server server;
        auto& map = server.databases();
        require(map.bind_workers(8, &server), "eight supervisor participants");
        std::vector<std::unique_ptr<Lifetime>> lives;
        for (unsigned i = 0; i < 8; ++i) lives.push_back(std::make_unique<Lifetime>(map, i));
        std::vector<std::thread> workers(8); // no threads: drive lifetime edges explicitly
        if (persistence) {
            if (rewrite) PersistFixTest::rewriting(server, true);
            else phase(server, Phase::Capture);
        }
        server.finish_shutdown();
        clock_ns = 100'000'000'000ull;
        clock_step = 1'000'000'000;
        const uint64_t start = clock_ns;
        // Release finalization at seven seconds, and its worker stack at eight.
        // The grace must not shrink back to 2.7 s when the phase becomes Idle.
        clock_hook = [&] {
            const auto elapsed = clock_ns - start;
            require(elapsed <= 12'000'000'000ull, "watchdog is bounded even for a hung save");
            if (!hang && elapsed >= 7'000'000'000ull) {
                phase(server, Phase::Idle);
                PersistFixTest::rewriting(server, false);
            }
            if (!hang && elapsed >= 8'000'000'000ull) lives.clear();
        };
        map.join_workers(server, workers);
        require(!hang && clock_ns - start >= 8'000'000'000ull &&
                clock_ns - start <= 10'000'000'000ull,
                "save finishes after old grace but within ten seconds");
        clock_hook = {}; clock_step = clock_ns = 0;
        std::printf("shutsave join %s: PASS (8 s virtual completion, old bound 2700 ms)\n",
                    rewrite ? "rewrite" : "snapshot");
    }

    static void retire(bool hang) {
        Server server;
        auto& map = server.databases();
        require(map.bind_workers(8, &server), "eight retirement participants");
        clock_ns = 100'000'000'000ull;
        require(map.swap(0, 1) && map.swap(0, 1), "retired map before SAVE begins");
        map.monitor(server); // arm live supervision before the long command
        phase(server, Phase::Capture);
        clock_ns += hang ? 11'000'000'000ull : 3'000'000'000ull;
        map.monitor(server);
        require(!hang && map.reclamation_pending(), "SAVE does not forge a database acknowledgement");
        phase(server, Phase::Idle);
        clock_ns += 50'000'000;
        map.monitor(server); // leaving SAVE gets an ordinary opportunity to acknowledge
        for (unsigned i = 1; i < 8; ++i) map.quiescent(server, i);
        map.quiescent(server, 0);
        require(!map.reclamation_pending(), "real acknowledgements reclaim the retained map");
        clock_ns = 0;
        std::puts("shutsave live retirement: PASS (no early free, real acknowledgements)");
    }

    static void boundary() {
        Server server;
        require(server.databases().bind_workers(8, &server), "boundary participants");
        Client client(-1);
        clock_ns = 100'000'000'000ull;
        for (auto current : {Phase::Preparing, Phase::Freeze, Phase::Mark, Phase::Capture, Phase::Failed}) {
            phase(server, current);
            require(!server.database_boundary_begin(client, 0, 1) &&
                    server.flip_stage() == FlipStage::Idle,
                    "SWAPDB cannot arm a namespace-drain timer during a snapshot");
            clock_ns += 4'000'000'000ull;
            server.databases().monitor(server);
        }
        phase(server, Phase::Idle);
        require(!server.database_boundary_begin(client, 0, 1) &&
                server.flip_stage() == FlipStage::DatabaseIoDrain,
                "SWAPDB arms its drain after snapshot completion");
        server.database_boundary_end(client, 1);
        clock_ns = 0;
        std::puts("shutsave namespace boundary: PASS (snapshot exclusion, admission after completion)");
    }

    template<bool Fused>
    static void save(const std::string& action, unsigned keys, bool background,
                     Phase stop_phase = Phase::Capture, bool uring = false, bool finalizing = false) {
        char directory[] = "build/shutsave/owner-XXXXXX";
        require(::mkdtemp(directory), "fresh snapshot directory");
        const std::string path = std::string(directory) + "/dump.tomo";
        auto server = std::make_unique<Server>();
        Config cfg;
        cfg.shards = 16; cfg.databases = 16; cfg.atomic = 1;
        cfg.even_ifid = 6; cfg.even_ex = 2;
        cfg.thread_mode = Fused ? ThreadMode::Fused : ThreadMode::Split;
        cfg.net_io = uring ? NetIoEngine::Uring : NetIoEngine::Epoll; cfg.dir = directory;
        cfg.key_lb = cfg.client_lb = 0;
        require(server->prepare_boot(cfg) && server->init(cfg), "real 16-database fixture");
        server->set_save_schedule({});
        command_bind_server(server.get());
        g_ring_epoll_mode = !uring;
        Ring ring;
        require(ring.init(64), "serverless snapshot mailbox");
        auto& writer = server->thread(server->placement().ifid_threads().front());
        snapshot_bind_io(&writer, &ring);
        std::vector<std::unique_ptr<Lifetime>> lives;
        for (unsigned i = 0; i < server->nthreads(); ++i)
            lives.push_back(std::make_unique<Lifetime>(server->databases(), i));
        std::vector<std::thread> workers(server->nthreads());
        struct Driver {
            Server& server;
            std::vector<std::thread>& workers;
            std::vector<std::unique_ptr<ExLoopT<Fused>>> owners;
            std::string action;
            Phase stop_phase;
            bool armed = false, fired = false;
            unsigned passes = 0;
            void stop() {
                fired = true;
                if (action == "sigterm") {
                    if (!server.request_signal_shutdown()) server.finish_shutdown();
                } else {
                    Op op;
                    require(op.push_arg(Slice("SHUTDOWN", 8)), "shutdown argv");
                    if (action == "nosave") require(op.push_arg(Slice("NOSAVE", 6)), "nosave argv");
                    op.spec = command_lookup(op.cmd_name());
                    require(op.spec != nullptr, "registered shutdown handler");
                    op.spec->handler(server.shard(0), op);
                    require(op.reply.size() == 0, "shutdown command has no error reply");
                }
                require(server.shutting_down(), "terminal stop published inside real SAVE");
            }
            uint32_t progress() {
                require(++passes < 2'000'000, "bounded production snapshot progress");
                auto& snapshot = server.snapshot();
                if (fired && server.shutting_down()) {
                    // PRE still asks stopped executors for work. Model main's real
                    // supervisor while all participants remain on that SAVE stack.
                    clock_ns = 100'000'000'000ull;
                    clock_step = 1'000'000'000;
                    server.databases().join_workers(server, workers);
                    require(false, "stopped SAVE returned to producer progress");
                }
                if (armed && !fired && snapshot.phase() == stop_phase &&
                    (stop_phase != Phase::Capture || snapshot.frame_count_ != 0)) {
                    stop();
                    return 0; // no producer work after terminal stop
                }
                uint32_t work = 0;
                for (auto& owner : owners) {
                    owner->ring_.for_each_cqe([&](io_uring_cqe* cqe) { owner->on_cqe(cqe); });
                    work += owner->snapshot_control_pass();
                    owner->ring_.submit_and_reap();
                }
                return work;
            }
        } driver{*server, workers, {}, action, stop_phase};
        for (auto tid : server->placement().ex_threads()) {
            auto owner = std::make_unique<ExLoopT<Fused>>();
            owner->srv_ = server.get(); owner->self_ = &server->thread(tid);
            require(owner->ring_.init(64), "owner snapshot mailbox");
            server->thread(tid).set_ring(&owner->ring_);
            driver.owners.push_back(std::move(owner));
        }
        writer.bind_fused_executor_hooks(&driver,
            [](void* p) { return static_cast<Driver*>(p)->progress(); },
            [](void* p, SnapshotManager* snapshot) {
                static_cast<Driver*>(p)->owners.front()->begin_snapshot(snapshot);
            });
        std::string error;
        require(server->snapshot().start(*server, writer, ring, true, error) ==
                SnapshotManager::StartResult::Started, "valid baseline snapshot");
        const std::string baseline = bytes(path);
        require(snapshot_read_plan(path.c_str(), 16, error) != nullptr, "baseline file validates");
        // Use actual registered SET handlers and owning shards, without server dispatch.
        std::string value(4096, 'x');
        uint64_t rng = 7;
        for (unsigned i = 0; i < keys; ++i) {
            for (auto& byte : value) { rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17; byte = rng; }
            const std::string key = "shutsave:" + std::to_string(i);
            Op op;
            require(op.push_arg(Slice("SET", 3)) && op.push_arg(Slice(key.data(), key.size())) &&
                    op.push_arg(Slice(value.data(), value.size())), "dataset argv");
            op.spec = command_lookup(op.cmd_name());
            op.hash = FlatStore::hash_key(op.arg(1));
            op.shard = server->router().shard_of(op.hash);
            op.spec->handler(server->shard(op.shard), op);
            require(std::string(op.reply.data(), op.reply.size()) == "+OK\r\n", "dataset SET succeeds");
        }
        std::thread supervisor;
        std::atomic<bool> release_sync{false};
        if (finalizing) {
            // Park the actual file-finalization call while a real supervisor
            // thread executes join_workers. Only its clock is virtual; the
            // image, fdatasync, rename, footer validation and lifetime edges are real.
            sync_hook = [&] {
                require(server->snapshot().phase() == Phase::Capture &&
                        server->snapshot().ended_shards_ == 16,
                        "BGSAVE finalization window has all real shard frames");
                driver.stop();
                supervisor = std::thread([&] {
                    clock_ns = 100'000'000'000ull; clock_step = 250'000'000;
                    clock_hook = [&] {
                        if (clock_ns >= 108'000'000'000ull) {
                            clock_step = 0;
                            release_sync.store(true, std::memory_order_release);
                        }
                    };
                    server->databases().join_workers(*server, workers);
                    require(clock_ns == 108'000'000'000ull, "finalization outlives the old worker grace");
                });
                while (!release_sync.load(std::memory_order_acquire)) std::this_thread::yield();
            };
        }
        driver.armed = !finalizing;
        const auto result = server->snapshot().start(*server, writer, ring, !background, error);
        if (background) {
            require(result == SnapshotManager::StartResult::Started, "real BGSAVE starts");
            while (finalizing ? server->snapshot().in_progress() : !driver.fired) {
                driver.progress();
                if (!driver.fired) {
                    server->snapshot().writer_pass(writer, ring, true);
                    ring.submit_and_reap();
                    server->snapshot().pump_io_completions(writer, ring);
                }
            }
        } else {
            require(result == SnapshotManager::StartResult::Failed &&
                    error == "snapshot cancelled by shutdown", "SAVE yields to terminal shutdown");
            require(server->snapshot().cancelled_owners_.load() == 0,
                    "shutdown never demands cancellation acknowledgements from stopped owners");
            require(server->snapshot().io_inflight_ == 0,
                    "cancelled SAVE reaps its own kernel requests before returning");
        }
        sync_hook = {};
        require(driver.fired, "stop window actually opened");
        if (finalizing) require(std::filesystem::file_size(path) > uint64_t(keys) * 4096,
                               "completed snapshot includes the full dataset");
        else require(bytes(path) == baseline, "abandonment preserves the valid previous snapshot");
        lives.clear();
        if (supervisor.joinable()) supervisor.join();
        else server->databases().join_workers(*server, workers);
        writer.bind_fused_executor_hooks(nullptr, nullptr, nullptr);
        for (auto tid : server->placement().ex_threads()) server->thread(tid).set_ring(nullptr);
        driver.owners.clear();
        server.reset();
        snapshot_bind_io(nullptr, nullptr); command_bind_server(nullptr);
        require(snapshot_read_plan(path.c_str(), 16, error) != nullptr, "post-shutdown file validates");
        for (const auto& entry : std::filesystem::directory_iterator(directory))
            require(entry.path().filename() == "dump.tomo", "abandoned temporary file is removed");
        std::filesystem::remove_all(directory);
        std::printf("shutsave %s %s %s %s phase=%u value_bytes=%llu: PASS (window witnessed, valid snapshot)\n",
                    Fused ? "1s" : "2s", uring ? "uring" : "normal",
                    finalizing ? "BGSAVE-finalization" : background ? "BGSAVE" : "SAVE", action.c_str(),
                    unsigned(stop_phase), static_cast<unsigned long long>(keys) * 4096);
    }
};
}

int main(int argc, char** argv) {
    static_assert(sizeof(Op) == 336 && sizeof(Client) == 1984 && sizeof(ThreadCtx) == 1408);
    static_assert(sizeof(Shard) == 1440 && sizeof(FlatStore) == 944 && sizeof(Rob<64>) == 192);
    static_assert(sizeof(AtomicEntry) == 144 && sizeof(Config) == 624);
    require(argc >= 2, "select join, rewrite, hang, hung-worker, retire, retire-hang, save, or bgsave");
    const std::string selection = argv[1];
    if (selection == "join" || selection == "rewrite" || selection == "hang" || selection == "hung-worker")
        CoreConcurrencyTest::join(selection != "hung-worker", selection == "hang" || selection == "hung-worker",
                                  selection == "rewrite");
    else if (selection == "retire" || selection == "retire-hang")
        CoreConcurrencyTest::retire(selection == "retire-hang");
    else if (selection == "boundary") CoreConcurrencyTest::boundary();
    else {
        require(selection == "save" || selection == "bgsave" || selection == "finalize", "known selection");
        require(argc >= 4, "save/bgsave requires mode and action");
        require(command_registry_init(false), "command registry");
        const unsigned keys = argc > 4 ? std::stoul(argv[4]) : 131072;
        const auto phase = argc > 5 ? static_cast<SnapshotManager::Phase>(std::stoul(argv[5]))
                                    : SnapshotManager::Phase::Capture;
        const bool uring = argc > 6 && std::string(argv[6]) == "uring";
        require(!uring || selection == "save", "uring fixture exercises blocking SAVE's real CQE drain");
        if (std::string(argv[2]) == "1s") CoreConcurrencyTest::save<true>(argv[3], keys, selection != "save", phase, uring, selection == "finalize");
        else CoreConcurrencyTest::save<false>(argv[3], keys, selection != "save", phase, uring, selection == "finalize");
    }
}
