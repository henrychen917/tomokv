// Production R7 inbox drain: real queues, ROBs, owner dispatch and handlers.
// No listener, io_uring setup, worker loop or timing assertion.
// Read-local-armed 2s deliberately uses ExLoopT<true>, just like rl2s.cc: that template
// parameter is a reader capability, not evidence that placement is fused.
#include <array>
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <string>
#include <vector>
#include <sched.h>
#include "src/core/ex_loop.h"
#include "src/core/io_loop.h"
#include "src/core/reorder.h"

namespace tomo {
struct CoreConcurrencyTest {
    static void require(bool ok, const char* message) {
        if (!ok) {
            std::fprintf(stderr, "FAIL R7 engagement: %s\n", message);
            std::_Exit(1);
        }
    }
    static Slice slice(const std::string& s) {
        return {s.data(), static_cast<uint32_t>(s.size())};
    }

    template <bool ReadLocal>
    struct Fixture {
        Server server;
        ExLoopT<ReadLocal> loop;
        uint32_t owner;
        uint64_t key_serial = 0;
        Fixture(ThreadMode mode, uint32_t overlap, int32_t reorder, uint32_t databases = 1)
            : owner(mode == ThreadMode::Fused ? 0 : 6) {
            cpu_set_t cpus;
            CPU_ZERO(&cpus);
            require(sched_getaffinity(0, sizeof(cpus), &cpus) == 0, "read test affinity");
            std::string domain;
            uint32_t count = 0;
            for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; cpu++) {
                if (!CPU_ISSET(cpu, &cpus)) continue;
                if (count++) domain += '+';
                domain += std::to_string(cpu);
            }
            require(count == 8, "eight allowed CPUs required, no skip");
            require(server.topo_.declare(domain.c_str()), "declare fixture topology");
            require(mode == ThreadMode::Fused
                        ? server.placement_.build_fused(server.topo_, nullptr)
                        : server.placement_.build_even(server.topo_, 6, 2), "place fixture");
            require(server.placement_.reserve_runtime_roles(8), "reserve fixture roles");
            Config config;
            config.databases = databases;
            config.thread_mode = mode;
            config.shards = 16;
            config.overlap = overlap;
            // Pass the raw knob through production initialization. Pre-resolving it
            // here hid boot/allocation defects from the previous split witness.
            config.reorder = reorder;
            config.read_local = ReadLocal;
            config.atomic = config.key_lb = config.client_lb = 1;
            config.save.clear();
            require(server.init(config), "initialize in-memory fixture");
            require(server.nthreads() == 8 && server.nshards() == 16, "gate geometry");
            loop.srv_ = &server;
            loop.self_ = &server.thread(owner);
            require(mode == ThreadMode::Fused ? loop.self_->init_task_inbox_local_fused()
                        : loop.self_->init_task_inbox_local(server.placement().ifid_threads(),
                                                           server.placement().ex_threads()),
                    "allocate the production task inbox");
            loop.fused_handoff_ring_ = &loop.ring_;
            loop.cached_now_ms_ = 1000;
            if constexpr (ReadLocal) {
            loop.read_local_.impl = std::make_unique<ReadLocalExImpl>();
            loop.read_local_impl().lane = std::make_unique<ReadLocalExImpl::LaneEntry[]>(kInboxSlots);
            loop.read_local_impl().lane_fallbacks = std::make_unique<ReadLocalFallbackReason[]>(kInboxSlots);
            auto& deferred = loop.read_local_impl().deferred;
            require(deferred.init(&server, loop.self_), "owner QSBR queue");
            for (Shard* sh : loop.self_->shards())
                sh->store().configure_read_local(true, *deferred.sink());
            }
            server.bind_owner_notify_pending(owner, &loop.notify_keyless_pending_);
            loop.refresh_live_config();
            loop.slowlog_armed_ = false;
            if constexpr (ReadLocal) if (mode == ThreadMode::Fused)
                loop.bind_fused_completion(nullptr, [](void*, Client*) {});
            require(loop.read_local_enabled() == ReadLocal && server.atomic_enabled(), "requested owner paths");
            require((server.mode_schedule_stats() != nullptr) == (overlap != 0 || server.cfg().reorder != 0),
                    "both disabled mechanisms allocate no witness sidecar");
        }
        ~Fixture() {
            if constexpr (ReadLocal) {
                loop.read_local_impl().deferred.drain_shutdown();
                for (Shard* sh : loop.self_->shards()) sh->store().configure_read_local(false, {});
            }
        }
        int32_t sid() const { return server.thread(owner).shards().front()->id(); }
        std::string key(uint8_t ns = 0) {
            for (uint32_t tries = 0; tries < 100000; tries++) {
                std::string s = "overlap-prefetch-" + std::to_string(key_serial++);
                if (server.router().shard_of(FlatStore::hash_key(
                        Slice(s.data(), s.size(), ns))) == sid()) return s;
            }
            require(false, "bounded owner key search");
            return {};
        }
        void client(Client& c, uint64_t id) {
            c.set_id(id);
            const uint32_t io = server.thread_mode() == ThreadMode::Fused ? owner : 0;
            c.set_ifid_thread(io);
            c.set_wb_slot(server.thread(io).assign_wb_slot(&c));
        }
        Task prepare(Client& c, std::initializer_list<Slice> args) {
            Op* op = c.rob().acquire<false>();
            require(op != nullptr, "acquire ROB slot");
            for (Slice arg : args) require(op->push_arg(arg), "append argument");
            op->spec = command_lookup(op->arg(0));
            require(op->spec != nullptr, "registered command");
            op->hash = FlatStore::hash_key(op->arg(1));
            op->shard = sid();
            op->state.store(OpState::Issued, std::memory_order_release);
            Task task{&c, c.rob().dispatch_id(), -1, nullptr};
            c.rob().publish();
            return task;
        }
        uint64_t passes() const {
            const auto* stats = server.mode_schedule_stats();
            return stats ? stats[owner].overlap_passes.load() : 0;
        }
        void witness(uint32_t n, uint64_t before) {
            if (!server.cfg().overlap) return;
            const auto& stats = server.mode_schedule_stats(owner);
            const bool warmed = server.thread_mode() == ThreadMode::Fused && n > 1;
            require(stats.overlap_passes.load() == before + (warmed ? 1 : 0),
                    "this batch must witness exactly its own prefetch, no inherited activity");
            require(stats.overlap_interleaved_passes.load() == 0,
                    "whole-batch prefetch must never claim split interleaving");
            if (server.thread_mode() == ThreadMode::Split) {
                require(stats.overlap_schedule.load() == OverlapSchedule::None &&
                            stats.overlap_passes.load() == 0, "2s owner must not claim fused overlap");
            } else if (n > 1) {
                require(stats.overlap_schedule.load() == OverlapSchedule::Fused,
                        "actual fused prefetch witness");
            }
        }
    };

    inline static std::vector<uint64_t> observed;
    static void record(Shard&, Op& op) {
        observed.push_back(op.hash);
        op.reply.append("+OK\r\n", 5);
    }
    template <bool ReadLocal>
    static void run(ThreadMode mode, uint32_t overlap, int32_t requested, bool expect_available) {
        require(reorder_available() == expect_available, "binary capability differs from expected arm");
        Fixture<ReadLocal> f(mode, overlap, requested);
        const int32_t reorder = f.server.cfg().reorder;
        CommandSpec short_op = *command_lookup(Slice("GET"));
        CommandSpec long_op = *command_lookup(Slice("BITCOUNT"));
        short_op.handler = short_op.handler_notify = record;
        long_op.handler = long_op.handler_notify = record;
        constexpr uint32_t count = 64;
        std::vector<std::unique_ptr<Client>> clients;
        std::vector<Task> tasks;
        for (uint32_t i = 0; i < count; i++) {
            clients.push_back(std::make_unique<Client>(-1));
            auto& c = *clients.back();
            f.client(c, i + 1);
            Task task = f.prepare(c, {Slice(i % 2 ? "GET" : "BITCOUNT"), Slice("probe")});
            Op& op = c.rob().at(task.op_id);
            op.spec = i % 2 ? &short_op : &long_op;
            op.hash = i; // Stable handler-order identity; neither handler reads the store.
            tasks.push_back(task);
            require(f.loop.self_->post_task_quiet(0, task, f.server.thread(0).sig()),
                    "publish all 64 owner tasks, spanning two gathers");
        }
        observed.clear();
        const uint64_t before = f.passes();
        const uint32_t drained = reorder ? f.loop.template r7_drain_tasks<>(true) : f.loop.template drain_tasks<>(true);
        require(drained == count && observed.size() == count, "drain lost work or carry");
        std::vector<uint64_t> expected;
        if (reorder && r7::shadow_available()) {
            for (uint32_t i = 1; i < count; i += 2) expected.push_back(i);
            for (uint32_t i = 0; i < count; i += 2) expected.push_back(i);
            const auto& stats = f.server.mode_schedule_stats(f.owner);
            require(stats.reorder_batches.load() == 2 && stats.reorder_permuted_runs.load() > 0,
                    "fresh production shadow drain did not engage");
        } else if (reorder) {
            // Independent service oracle: four short heads then one older long head.
            uint32_t short_head = 1, long_head = 0;
            while (long_head < count) {
                for (uint32_t n = 0; n < 4 && short_head < count; n++, short_head += 2)
                    expected.push_back(short_head);
                expected.push_back(long_head);
                long_head += 2;
            }
            const auto& stats = f.server.mode_schedule_stats(f.owner);
            require(stats.reorder_batches.load() == 2 && stats.reorder_permuted_runs.load() > 0,
                    "fresh production drain did not engage the two queues");
        } else {
            for (uint32_t i = 0; i < count; i++) expected.push_back(i);
        }
        require(observed == expected, "production handler order disagrees with shadow/R7/FIFO oracle");
        require(f.loop.xshard_retries_.empty() && f.loop.ordered_deferred_.empty(), "unexpected retry debt");
        if (overlap && mode == ThreadMode::Fused)
            require(f.passes() == before + 2, "both emitted gathers retain O6 prefetch");
        for (const auto& task : tasks) {
            Op& op = task.client->rob().at(task.op_id);
            require(op.state.load() == OpState::Done, "all ROB slots completed");
            require(task.client->rob().drain([](Op&) {}) == 1, "ready prefix retires");
        }
        std::printf("PASS R7 production drain %s read-local=%u overlap=%u requested=%d effective=%d: "
                    "64 handlers, %s, empty carry\n",
                    mode == ThreadMode::Fused ? "1s" : "2s", ReadLocal, overlap, requested, reorder,
                    reorder ? (r7::shadow_available() ? "shadow priority" : "R7 4:1") : "FIFO");
    }

    template <bool ReadLocal>
    static void shadow_pipes(ThreadMode mode, uint32_t overlap, uint32_t requested) {
        Fixture<ReadLocal> f(mode, overlap, requested);
        const uint32_t reorder = f.server.cfg().reorder;
        IoLoop io;
        io.srv_ = &f.server;
        io.self_ = &f.server.thread(mode == ThreadMode::Fused ? f.owner : 0);
        if constexpr (ReadLocal) io.fused_executor_ = &f.loop;
        // Writes exercise the owner scheduler with read-local armed as well. Clean
        // GETs may legitimately take the read-local lane outside these queues.
        CommandSpec short_op = *command_lookup(Slice("SET"));
        CommandSpec long_op = *command_lookup(Slice("BITCOUNT"));
        short_op.handler = short_op.handler_notify = record;
        long_op.handler = long_op.handler_notify = record;
        const std::string key = f.key();
        std::vector<std::unique_ptr<Client>> clients;
        uint32_t total = 0;
        for (const std::string pattern : {"sssLss", "Lssss", "sssLs"}) {
            clients.push_back(std::make_unique<Client>(-1));
            Client& c = *clients.back();
            f.client(c, clients.size());
            std::string wire;
            for (char ch : pattern) {
                const std::string cmd = ch == 'L' ? "BITCOUNT" : "SET";
                wire += std::string(ch == 'L' ? "*2\r\n$" : "*3\r\n$") +
                        std::to_string(cmd.size()) + "\r\n" + cmd + "\r\n$" +
                        std::to_string(key.size()) + "\r\n" + key + "\r\n";
                if (ch != 'L') wire += "$1\r\nv\r\n";
            }
            std::memcpy(c.rbuf(), wire.data(), wire.size());
            c.commit_read(wire.size());
            auto parse = [&]<uint32_t B, bool SplitLocal>() {
                if (reorder)
                    return io.r7_parse_and_dispatch<false, B, SplitLocal, false, false, false, SplitLocal>(&c);
                return io.parse_and_dispatch<false, B, SplitLocal, false, false, false, SplitLocal>(&c);
            };
            const auto result = mode == ThreadMode::Fused
                ? parse.template operator()<kGenthreadIfidBatchOps, false>()
                : ReadLocal ? parse.template operator()<0, true>() : parse.template operator()<0, false>();
            require(result == IoLoop::DispatchResult::Progress && c.rpos() == c.rlen() &&
                        c.rob().in_flight() == pattern.size(), "real parser did not dispatch the entire pipe");
            for (uint32_t id = 0; id < pattern.size(); ++id) {
                Op& op = c.rob().at(id);
                op.spec = pattern[id] == 'L' ? &long_op : &short_op;
                op.hash = total++;
            }
        }
        std::vector<Task> queued;
        f.loop.self_->drain_tasks_unmasked([&](const Task& t) { queued.push_back(t); });
        require(queued.size() == total, "parser bypassed the production inbox");
        uint32_t shadows = 0;
        for (const auto& t : queued) {
            shadows += r7::shadow_bit(t);
            require(f.loop.task_shard(t) == f.sid(), "shadow payload changed shard routing");
            require(f.loop.self_->post_task_quiet(0, t, io.self_->sig()), "requeue parsed tasks");
        }
        const bool shadow = reorder && r7::shadow_available();
        require(shadows == (shadow ? 7u : 0u), "dispatch shadow stamp count/PAD/FIFO witness");
        observed.clear();
        const uint32_t drained = reorder ? f.loop.template r7_drain_tasks<>(true)
                                           : f.loop.template drain_tasks<>(true);
        require(drained == total && observed.size() == total, "production three-pipe drain lost work");
        const std::vector<uint64_t> expected = shadow
            ? std::vector<uint64_t>{0,11,1,12,2,13,6,3,14,7,4,15,8,5,9,10}
            : reorder ? std::vector<uint64_t>{0,11,1,2,3,4,5,6,7,8,9,10,12,13,14,15}
                        : std::vector<uint64_t>{0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15};
        require(observed == expected, "actual parser-to-handler three-pipe order disagrees");
        for (auto& c : clients)
            require(c->rob().drain([](Op&) {}) == c->rob().dispatch_id(), "RESP prefix did not retire in order");
        std::printf("PASS production parser + three pipes %s read-local=%u overlap=%u reorder=%u shadow=%u\n",
                    mode == ThreadMode::Fused ? "1s" : "2s", ReadLocal, overlap, requested, shadow);
    }

    static void database_dispatch(int32_t requested) {
        Fixture<false> f(ThreadMode::Fused, 0, requested, kSingleDatabase ? 1 : 16);
        command_bind_server(&f.server);
        IoLoop io;
        io.srv_ = &f.server;
        io.self_ = &f.server.thread(f.owner);
        Client client(-1), boundary(-1);
        f.client(client, 1);
        constexpr uint8_t logical = kSingleDatabase ? 0 : 3;
        constexpr uint8_t physical = kSingleDatabase ? 0 : 5;
        if constexpr (!kSingleDatabase)
            require(f.server.databases().swap(logical, 9), "initial nonidentity database map");
        // Both identities must reach the initialized fixture owner. A deliberately
        // missing stamp then fails the identity assertion, not a foreign-inbox fault.
        std::string key;
        for (uint32_t i = 0; i < 100000; ++i) {
            const std::string candidate = "reorder-database-" + std::to_string(i);
            if (f.server.router().shard_of(FlatStore::hash_key(slice(candidate))) == f.sid() &&
                f.server.router().shard_of(FlatStore::hash_key(
                    Slice(candidate.data(), candidate.size(), physical))) == f.sid()) {
                key = candidate;
                break;
            }
        }
        require(!key.empty(), "bounded database key search");
        const std::string wire = "*2\r\n$6\r\nSELECT\r\n$1\r\n" + std::to_string(logical) +
            "\r\n*2\r\n$8\r\nBITCOUNT\r\n$" + std::to_string(key.size()) + "\r\n" + key +
            "\r\n*3\r\n$3\r\nSET\r\n$" + std::to_string(key.size()) + "\r\n" + key +
            "\r\n$1\r\nv\r\n";
        std::memcpy(client.rbuf(), wire.data(), wire.size());
        client.commit_read(wire.size());
        auto parse = [&] {
            return f.server.cfg().reorder
                ? io.r7_parse_and_dispatch<false, kGenthreadIfidBatchOps>(&client)
                : io.parse_and_dispatch<false, kGenthreadIfidBatchOps>(&client);
        };
        require(parse() == IoLoop::DispatchResult::Progress &&
                    client.session().db_index == logical && client.rob().dispatch_id() == 1 &&
                    client.rpos() < client.rlen(), "SELECT ends the current parser pass");
        require(client.rob().drain([](Op&) {}) == 1, "SELECT retires before its following pipe");
        if constexpr (!kSingleDatabase) {
            require(!f.server.database_boundary_begin(boundary, f.owner, 0),
                    "fresh SWAPDB boundary must open");
            const uint32_t before = client.rpos();
            (void)parse();
            require(client.flip_backpressure() && client.rpos() == before &&
                        client.rob().dispatch_id() == 1 && client.rob().quiesced(),
                    "armed parser dispatched inside the SWAPDB boundary");
            require(f.server.databases().swap(logical, physical), "publish changed physical database");
            f.server.database_boundary_end(boundary, 0);
            client.set_flip_backpressure(false);
        }
        require(parse() == IoLoop::DispatchResult::Progress && client.rpos() == client.rlen(),
                "database pipe did not resume after the boundary");
        std::vector<Task> queued;
        f.loop.self_->drain_tasks_unmasked([&](const Task& task) { queued.push_back(task); });
        require(queued.size() == 2, "database-stamped tasks missed their expected owner");
        for (const auto& task : queued) {
            const Op& op = client.rob().at(task.op_id);
            require(op.db == logical && op.physical_db == physical && op.arg(1).ns == physical &&
                        op.shard == f.sid() && op.hash == FlatStore::hash_key(Slice(key.data(), key.size(), physical)),
                    "database stamp/hash/shard must use the post-boundary map");
            require(f.loop.self_->post_task_quiet(f.owner, task, io.self_->sig()), "requeue database pipe");
        }
        require(r7::shadow_pending(queued[1]) == (f.server.cfg().reorder && r7::shadow_available()),
                "database stamping lost the same-pipe Long shadow");
        require((f.server.cfg().reorder ? f.loop.r7_drain_tasks<>(true) : f.loop.drain_tasks<>(true)) == 2,
                "database pipe did not execute");
        std::string replies;
        const auto retired = client.rob().drain([&](Op& op) {
            op_materialise_code(op);
            replies.append(op.reply.data(), op.reply.size());
        });
        if (retired != 2 || replies != ":0\r\n+OK\r\n")
            std::fprintf(stderr, "database pipe requested=%d retired=%u replies=%s\n",
                         requested, static_cast<unsigned>(retired), replies.c_str());
        require(retired == 2 && replies == ":0\r\n+OK\r\n", "database pipe replies/retirement");
        command_bind_server(nullptr);
        std::printf("PASS reorder database parser %s requested=%d: SELECT, boundary, stamp, shadow, replies\n",
                    kSingleDatabase ? "db0" : "multidb", requested);
    }

    static void automatic_inbox() {
        Fixture<true> f(ThreadMode::Fused, 0, -1);
        // The all-policy PAD deliberately resolves the request before creating state.
        if (!reorder_available()) {
            require(f.server.cfg().reorder == 0 && !f.server.mode_schedule_stats(),
                    "PAD allocated AUTO state");
            return;
        }
        auto& stats = f.server.mode_schedule_stats(f.owner);
        r7::PolicyScope scope(stats);
        CommandSpec short_op = *command_lookup(Slice("GET"));
        CommandSpec long_op = *command_lookup(Slice("BITCOUNT"));
        short_op.handler = short_op.handler_notify = record;
        long_op.handler = long_op.handler_notify = record;
        constexpr uint32_t count = 2 * kGenthreadExBatchOps;
        std::vector<std::unique_ptr<Client>> clients;
        for (uint32_t i = 0; i < count; ++i) clients.push_back(std::make_unique<Client>(-1));
        for (uint32_t i = 0; i < clients.size(); ++i) {
            f.client(*clients[i], i + 1);
            Task task = f.prepare(*clients[i], {Slice(i ? "GET" : "BITCOUNT"), Slice("probe")});
            auto& op = clients[i]->rob().at(task.op_id);
            op.spec = i ? &short_op : &long_op;
            op.hash = i;
            require(f.loop.self_->post_task_quiet(0, task, f.server.thread(0).sig()), "AUTO queue setup");
        }
        const auto sample = r7::InboxProbe::sample(*f.loop.self_);
        require(sample.depth == count && sample.shorts == count - 1 && sample.longs == 1 && sample.behind == count - 1,
                "AUTO owner probe did not observe the actual queued HOL window");
        require(!r7::priority_enabled(stats, -1), "AUTO engaged without a sampled window");
        for (uint32_t i = 0; i < kGenthreadExBatchOps; ++i) {
            require(f.loop.self_->sample_depth(1000 + 100 * i), "existing signal tick missing");
            scope.policy.tick(*f.loop.self_, stats);
            require(!f.loop.self_->sample_depth(1050 + 100 * i), "signal sampled per pass instead of per tick");
        }
        require(r7::priority_enabled(stats, -1) && (stats.reorder_auto.load() & 1) &&
                    ((stats.reorder_auto.load() >> 1) & 0x7fffffff) == 1,
                "production AUTO did not engage");
        observed.clear();
        std::vector<uint64_t> priority;
        // The inherited oldest-task fairness turn follows one gather of priority
        // picks. With two gathers this Long must run before the remaining shorts.
        for (uint32_t i = 1; i <= kGenthreadExBatchOps; ++i) priority.push_back(i);
        priority.push_back(0);
        for (uint32_t i = kGenthreadExBatchOps + 1; i < count; ++i) priority.push_back(i);
        require(f.loop.r7_drain_tasks<>(true) == count && observed == priority,
                "AUTO engagement did not select the actual shadow scheduler");
        scope.policy.tick(*f.loop.self_, stats);
        require(!r7::priority_enabled(stats, -1) && !(stats.reorder_auto.load() & 1),
                "empty owner inbox did not disengage AUTO");
        for (auto& c : clients) require(c->rob().drain([](Op&) {}) == 1, "AUTO reply retirement");
        // Re-arm the same real mixed queue while the policy is disarmed. Before another
        // sampled window the wrapper MUST delegate to the unchanged FIFO drain.
        for (uint32_t i = 0; i < clients.size(); ++i) {
            Task task = f.prepare(*clients[i], {Slice(i ? "GET" : "BITCOUNT"), Slice("probe")});
            auto& op = clients[i]->rob().at(task.op_id);
            op.spec = i ? &short_op : &long_op;
            op.hash = i;
            require(f.loop.self_->post_task_quiet(0, task, f.server.thread(0).sig()), "AUTO disarmed queue");
        }
        observed.clear();
        std::vector<uint64_t> fifo;
        for (uint32_t i = 0; i < count; ++i) fifo.push_back(i);
        require(f.loop.r7_drain_tasks<>(true) == count && observed == fifo,
                "AUTO disarmed path retained reordering");
        for (auto& c : clients) require(c->rob().drain([](Op&) {}) == 1, "AUTO FIFO retirement");
        std::puts("PASS production AUTO probe, existing tick, priority engagement and FIFO disengagement");
    }

    static void shadow_foreign_passes() {
        Fixture<false> f(ThreadMode::Fused, 0, 1);
        ThreadCtx& foreign = f.server.thread(1);
        require(foreign.init_task_inbox_local_fused(), "foreign fixture inbox");
        const int32_t foreign_sid = foreign.shards().front()->id();
        std::string foreign_key;
        for (uint32_t i = 0; i < 100000; ++i) {
            const std::string key = "shadow-foreign-" + std::to_string(i);
            if (f.server.router().shard_of(FlatStore::hash_key(slice(key))) == foreign_sid) {
                foreign_key = key;
                break;
            }
        }
        require(!foreign_key.empty(), "bounded foreign-key search");
        const std::string local_key = f.key();
        Client c(-1);
        f.client(c, 1);
        IoLoop io;
        io.srv_ = &f.server;
        io.self_ = &f.server.thread(0);
        auto parse = [&](const char* command, const std::string& key) {
            const std::string cmd = command;
            const std::string wire = "*2\r\n$" + std::to_string(cmd.size()) + "\r\n" + cmd +
                "\r\n$" + std::to_string(key.size()) + "\r\n" + key + "\r\n";
            std::memcpy(c.rbuf() + c.rlen(), wire.data(), wire.size());
            c.commit_read(wire.size());
            require((f.server.cfg().reorder ? io.r7_parse_and_dispatch<false, kGenthreadIfidBatchOps>(&c) : io.parse_and_dispatch<false, kGenthreadIfidBatchOps>(&c)) == IoLoop::DispatchResult::Progress &&
                        c.rpos() == c.rlen(), "real parser pass did not dispatch");
        };
        parse("BITCOUNT", local_key);
        parse("GET", foreign_key); // Separate parse pass AND a different executor.
        Task long_task, short_task;
        require(f.loop.self_->drain_tasks_unmasked([&](const Task& t) { long_task = t; }) == 1 &&
                foreign.drain_tasks_unmasked([&](const Task& t) { short_task = t; }) == 1,
                "both owner queues must contain their actual task");
        require(long_task.op_id == 0 && short_task.op_id == 1 &&
                    r7::shadow_pending(short_task) == (reorder_available() && r7::shadow_available()),
                "foreign long was lost across the parse boundary");
        c.rob().at(0).state.store(OpState::Done, std::memory_order_release);
        require(c.rob().flush_id() == 0 && !r7::shadow_pending(short_task),
                "foreign completion did not clear before IO retirement");
        parse("GET", foreign_key);
        Task cleared;
        require(foreign.drain_tasks_unmasked([&](const Task& t) { cleared = t; }) == 1 &&
                    !r7::shadow_bit(cleared), "next parser pass kept a completed long");
        c.rob().at(1).state.store(OpState::Done, std::memory_order_release);
        c.rob().at(2).state.store(OpState::Done, std::memory_order_release);
        require(c.rob().drain([](Op&) {}) == 3, "foreign tasks did not retire in RESP order");
        std::printf("PASS production shadow across parser passes and executor owners; shadow=%u\n",
                    (reorder_available() && r7::shadow_available()));
    }

    static void shadow_demotions(ThreadMode mode) {
        Fixture<true> f(mode, 1, 1);
        const bool armed = f.server.cfg().reorder != 0;
        const bool shadow = armed && r7::shadow_available();
        IoLoop io;
        io.srv_ = &f.server;
        io.self_ = &f.server.thread(mode == ThreadMode::Fused ? f.owner : 0);
        io.fused_executor_ = &f.loop;
        const std::string key = f.key();
        const std::string read_key = f.key(); // Disjoint from the owner-queued BITCOUNT key.
        Client a(-1), b(-1);
        f.client(a, 1); f.client(b, 2);
        auto frame = [&](const char* command, bool write = false) {
            const std::string cmd = command;
            const std::string& target = cmd == "GET" ? read_key : key;
            return std::string(write ? "*3\r\n$" : "*2\r\n$") + std::to_string(cmd.size()) +
                "\r\n" + cmd + "\r\n$" + std::to_string(target.size()) + "\r\n" + target +
                (write ? "\r\n$1\r\nv\r\n" : "\r\n");
        };
        const std::string wire = frame("BITCOUNT") + frame("GET") + frame("BITCOUNT");
        std::memcpy(a.rbuf(), wire.data(), wire.size()); a.commit_read(wire.size());
        const auto parsed = mode == ThreadMode::Fused
            ? (armed ? io.r7_parse_and_dispatch<false, kGenthreadIfidBatchOps>(&a) : io.parse_and_dispatch<false, kGenthreadIfidBatchOps>(&a))
            : io.parse_and_dispatch<false, 0, true, false, false, false, true>(&a);
        require(parsed == IoLoop::DispatchResult::Progress && a.rob().dispatch_id() == 3 &&
                    a.rob().pending_read_local(1), "clean GET did not enter the real local lane");
        const uint64_t id = 1;
        const ReadLocalFallbackReason reason = ReadLocalFallbackReason::ContextOwnerKey;
        uint32_t demoted = 0;
        require((armed ? io.r7_fused_demote_local_read_batch(&a, &id, &reason, 1, demoted) : io.fused_demote_local_read_batch(&a, &id, &reason, 1, demoted)) && demoted == 1,
                "actual local-read demotion did not post exactly one task");
        const std::string write = frame("SET", true);
        std::memcpy(b.rbuf(), write.data(), write.size()); b.commit_read(write.size());
        if (armed) io.r7_parse_and_dispatch<false, kGenthreadIfidBatchOps>(&b);
        else if (mode == ThreadMode::Fused) io.parse_and_dispatch<false, kGenthreadIfidBatchOps>(&b);
        else io.parse_and_dispatch<false, 0, true, false, false, false, true>(&b);
        std::vector<Task> tasks;
        require(f.loop.self_->drain_tasks_unmasked([&](const Task& t) { tasks.push_back(t); }) == 4,
                "demotion fixture owner wave missing");
        require(tasks[0].op_id == 0 && tasks[1].op_id == 2 && tasks[2].op_id == 1 &&
                    tasks[2].client == &a, "late older-read dispatch window did not open");
        require(r7::shadow_bit(tasks[2]) == shadow, "demoted read lost shadow hint");
        if (shadow)
            require(r7::shadow_id(tasks[2]) == 0 && r7::shadow_pending(tasks[2]),
                    "demotion captured a younger Long instead of its own preceding Long");
        CommandSpec short_op = *command_lookup(Slice("GET"));
        CommandSpec long_op = *command_lookup(Slice("BITCOUNT"));
        short_op.handler = short_op.handler_notify = record;
        long_op.handler = long_op.handler_notify = record;
        for (const auto& t : tasks) {
            Op& op = t.client->rob().at(t.op_id);
            op.spec = t.client == &a && t.op_id != 1 ? &long_op : &short_op;
            op.hash = t.client == &a ? t.op_id : 3;
            require(f.loop.self_->post_task_quiet(io.self_->id(), t, io.self_->sig()), "requeue demotion wave");
        }
        observed.clear();
        require((armed ? f.loop.r7_drain_tasks<>(true) : f.loop.drain_tasks<>(true)) == 4 &&
                    observed == (armed ? std::vector<uint64_t>{3,0,2,1} : std::vector<uint64_t>{0,2,1,3}),
                "scheduler changed established owner order for a late local read");
        f.loop.compact_local_read_tombstones();
        require(a.rob().drain([](Op&) {}) == 3 && b.rob().drain([](Op&) {}) == 1,
                "late read did not retire in RESP order");
        std::printf("PASS production read-local demotion %s: older blocker stamp, late owner order, shadow=%u\n",
                    mode == ThreadMode::Fused ? "1s" : "2s", shadow);
    }
};
} // namespace tomo

int main(int argc, char** argv) {
    using T = tomo::CoreConcurrencyTest;
    T::require(argc == 3 && (std::string(argv[1]) == "on" || std::string(argv[1]) == "off") &&
                   (std::string(argv[2]) == "shadow" || std::string(argv[2]) == "r7"),
               "supply independently expected capabilities: on|off shadow|r7");
    T::require(tomo::r7::shadow_available() == (std::string(argv[2]) == "shadow"), "shadow capability");
    T::require(tomo::command_registry_init(false), "command registry");
    for (auto mode : {tomo::ThreadMode::Fused, tomo::ThreadMode::Split})
        for (uint32_t overlap : {0u, 1u})
            for (uint32_t reorder : {0u, 1u})
                T::run<true>(mode, overlap, reorder, std::string(argv[1]) == "on");
    for (uint32_t overlap : {0u, 1u})
        for (uint32_t reorder : {0u, 1u})
            T::run<false>(tomo::ThreadMode::Split, overlap, reorder, std::string(argv[1]) == "on");
    for (auto mode : {tomo::ThreadMode::Fused, tomo::ThreadMode::Split})
        for (uint32_t overlap : {0u, 1u})
            for (uint32_t reorder : {0u, 1u}) T::shadow_pipes<true>(mode, overlap, reorder);
    for (uint32_t overlap : {0u, 1u})
        for (uint32_t reorder : {0u, 1u}) T::shadow_pipes<false>(tomo::ThreadMode::Split, overlap, reorder);
    T::run<true>(tomo::ThreadMode::Split, 0, -1, std::string(argv[1]) == "on");
    T::run<false>(tomo::ThreadMode::Split, 0, -1, std::string(argv[1]) == "on");
    T::automatic_inbox();
    T::shadow_foreign_passes();
    T::shadow_demotions(tomo::ThreadMode::Fused);
    T::shadow_demotions(tomo::ThreadMode::Split);
    for (int32_t requested : {0, 1, -1}) T::database_dispatch(requested);
    return 0;
}
