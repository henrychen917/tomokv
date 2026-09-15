// Deterministic, serverless regressions for SURVIVING.md's src/core concurrency findings.
// No listener, executor loop, benchmark, sleeps, or probabilistic arming. The fixture has
// the gate's 16 shards / 6 IO + 2 EX geometry; transfer rows also exercise fused ownership.
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#include <sched.h>

#include "src/core/io_loop.h"

namespace tomo {
struct CoreConcurrencyTest {
    static void require(bool ok, const char* message) {
        if (!ok) {
            std::fprintf(stderr, "FAIL core concurrency: %s\n", message);
            // A negative control can fail while the executor is deliberately parked.
            // Do not run static condition-variable destructors with that waiter alive.
            std::_Exit(1);
        }
    }
    static Slice slice(const std::string& text) {
        return {text.data(), static_cast<uint32_t>(text.size())};
    }

    template <bool Fused = false>
    struct Fixture {
        Server server;
        ExLoopT<Fused> loops[8];
        IoLoop io;
        uint32_t source = Fused ? 0 : 6;
        uint32_t destination = Fused ? 1 : 7;
        uint32_t io_id = Fused ? 7 : 0;
        Fixture(bool load_balance = true) {
            cpu_set_t cpus;
            CPU_ZERO(&cpus);
            require(sched_getaffinity(0, sizeof(cpus), &cpus) == 0, "affinity unavailable");
            std::string domain;
            uint32_t count = 0;
            for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; cpu++) {
                if (!CPU_ISSET(cpu, &cpus)) continue;
                if (count++) domain += '+';
                domain += std::to_string(cpu);
            }
            require(count == 8, "regression fixture requires eight allowed CPUs (no skip)");
            require(server.topo_.declare(domain.c_str()), "declare fixture topology");
            if constexpr (Fused)
                require(server.placement_.build_fused(server.topo_, nullptr), "fused placement");
            else
                require(server.placement_.build_even(server.topo_, 6, 2), "6:2 placement");
            require(server.placement_.reserve_runtime_roles(8), "reserve placement roles");
            Config config;
            config.shards = 16;
            config.thread_mode = Fused ? ThreadMode::Fused : ThreadMode::Split;
            config.flip_auto = 0;
            config.key_lb = config.client_lb = load_balance ? 1 : 0;
            config.save.clear();
            require(server.init(config), "initialize in-memory fixture");
            require(server.nshards() == 16 && server.nthreads() == 8, "fixture geometry");
            for (uint32_t tid = 0; tid < 8; tid++) {
                ThreadCtx& thread = server.thread(tid);
                require(Fused ? thread.init_task_inbox_local_fused()
                              : thread.init_task_inbox_local(server.placement().ifid_threads(),
                                                             server.placement().ex_threads()),
                        "initialize task lanes");
                auto& loop = loops[tid];
                loop.srv_ = &server;
                loop.self_ = &thread;
                loop.fused_handoff_ring_ = &loop.ring_;
                loop.cached_now_ms_ = 1000;
                loop.lb_controller_armed_ = true;
                server.bind_owner_notify_pending(tid, &loop.notify_keyless_pending_);
                loop.refresh_live_config();
            }
            io.srv_ = &server;
            io.self_ = &server.thread(io_id);
            io.lb_controller_armed_ = true;
        }
        int32_t sid() { return server.thread(source).shards().front()->id(); }
        std::string key(int32_t shard) {
            for (uint32_t i = 0; i < 100000; i++) {
                std::string name = "core-regression-" + std::to_string(i);
                if (server.router().shard_of(FlatStore::hash_key(slice(name))) == shard)
                    return name;
            }
            require(false, "could not synthesize shard key");
            return {};
        }
        void client(Client& client) {
            client.set_id(1);
            client.set_ifid_thread(io_id);
            client.set_wb_slot(server.thread(io_id).assign_wb_slot(&client));
        }
        void move(int32_t shard, bool range) {
            require(server.reserve_shard_capacity(destination, 1), "reserve incoming shard");
            Shard& physical = server.shard(shard);
            require(range ? server.transfer_bucket_range_quiesced(
                                physical.bucket_begin(), physical.bucket_end(), source, destination)
                          : server.transfer_shard_quiesced(shard, source, destination),
                    "ownership transfer must fire");
            require(server.worker_of_shard(shard) == destination, "destination owns shard");
        }
    };

    static Op& prepare(Client& client, std::initializer_list<Slice> args, Server& server) {
        Op* op = client.rob().acquire<false>();
        require(op != nullptr, "ROB acquisition");
        for (Slice arg : args) require(op->push_arg(arg), "append argument");
        op->spec = command_lookup(op->arg(0));
        require(op->spec != nullptr, "registered command");
        op->hash = FlatStore::hash_key(op->arg(1));
        op->shard = server.router().shard_of(op->hash);
        op->state.store(OpState::Issued, std::memory_order_release);
        return *op;
    }
    template <bool Fused>
    static std::string command(Fixture<Fused>& f, Client& client,
                               std::initializer_list<Slice> args) {
        Op& op = prepare(client, args, f.server);
        const uint64_t id = client.rob().dispatch_id();
        client.rob().publish();
        require(f.loops[f.server.worker_of_shard(op.shard)].execute(Task{&client, id, -1, nullptr}),
                "command execution");
        std::string reply;
        require(client.rob().drain([&](Op& done) {
                    reply.assign(done.reply.data(), done.reply.size());
                }) == 1, "command completed exactly once");
        return reply;
    }

    static void watch_disconnect() {
        Fixture f;
        f.server.set_maxmemory_config(16 * 1024 * 1024, MaxmemoryPolicy::AllKeysLfu, 5);
        auto& owner = f.loops[f.source];
        owner.refresh_live_config();
        require(owner.maxmemory_enabled_, "positive maxmemory armed");
        const int32_t sid = f.sid();
        const std::string key = f.key(sid);
        Client client(-1);
        f.client(client);
        Op& op = prepare(client, {Slice("WATCH"), slice(key)}, f.server);
        MultiExecState* state = nullptr;
        require(multi_handle_io(f.server, client, op, f.io_id, state) == MultiIoAction::Dispatch &&
                    state && multi_dispatch_count(state) == 1, "WATCH owner fragment prepared");
        op.attach_multi_state(state);
        client.atomic_group_started();
        client.rob().publish();
        multi_dispatch_started(client, state);
        require(owner.execute(multi_make_task(&client, 0, sid, state)), "WATCH executed");
        std::vector<MultiExecState*> deferred;
        require(client.rob().drain([&](Op& done) { multi_retire(client, done, deferred); }) == 1,
                "WATCH replied successfully");
        require(deferred.empty() && f.server.shard(sid).has_watches(), "WATCH registration exists");
        require(!client.safe_to_release(), "watcher reference pins disconnected client");
        state = multi_prepare_close(f.server, client, f.io_id);
        require(state && multi_dispatch_count(state) == 1, "disconnect cleanup prepared");
        multi_internal_dispatch_started(state);
        const Task cleanup = multi_make_task(nullptr, UINT64_MAX, sid, state);
        require(multi_task_tagged(cleanup) && cleanup.client == nullptr, "null tagged task armed");
        require(owner.execute(cleanup), "null tagged cleanup executed");
        require(!f.server.shard(sid).has_watches() && client.safe_to_release(),
                "cleanup removed watcher and released client");
    }

    static void scheduler() {
        Fixture<true> f;
        Client clients[4] = {Client(-1), Client(-1), Client(-1), Client(-1)};
        std::vector<Task> tasks;
        const std::string key = f.key(f.sid());
        for (uint32_t i = 0; i < kGenthreadPipelineExBatchOps; i++) {
            Client& client = clients[i % 4];
            f.client(client);
            Op& op = prepare(client, {Slice(i % 3 ? "GET" : "STRLEN"), slice(key)}, f.server);
            (void)op;
            tasks.emplace_back(&client, client.rob().dispatch_id(), -1, nullptr);
            client.rob().publish();
        }
        require(tasks.size() == 128 && tasks.size() > kExecBatch, "oversized fused batch armed");
        for (const Task& task : tasks) {
            uint8_t length = 255;
            require(ex_sched_candidate(task, length), "every gathered task eligible");
        }
        Task batch[kGenthreadPipelineExBatchOps];
        std::copy(tasks.begin(), tasks.end(), batch);
        ex_schedule_batch(batch, static_cast<uint32_t>(tasks.size()));
        std::copy(std::begin(batch), std::end(batch), tasks.begin());
        uint64_t next[4] = {};
        for (const Task& task : tasks) {
            const size_t client = task.client - clients;
            require(client < 4 && task.op_id == next[client]++, "scheduler preserves client order");
        }
        for (uint64_t count : next) require(count == 32, "scheduler conserves every task");
        // The original overrun occurs before the single-client shortcut too.
        Client one(-1);
        tasks.clear();
        for (uint32_t i = 0; i < 64; i++) {
            prepare(one, {Slice("GET"), slice(key)}, f.server);
            tasks.emplace_back(&one, one.rob().dispatch_id(), -1, nullptr);
            one.rob().publish();
        }
        std::copy(tasks.begin(), tasks.end(), batch);
        ex_schedule_batch(batch, 64);
        std::copy(std::begin(batch), std::begin(batch) + 64, tasks.begin());
        for (uint32_t i = 0; i < 64; i++) require(tasks[i].op_id == i, "one-client FIFO shortcut");
    }

    inline static std::mutex pause_mutex;
    inline static std::condition_variable pause_cv;
    inline static bool done_hook_entered = false, done_hook_release = false;
    static void hold_done(Client*) {
        std::unique_lock lock(pause_mutex);
        done_hook_entered = true;
        pause_cv.notify_all();
        require(pause_cv.wait_for(lock, std::chrono::seconds(10), [] { return done_hook_release; }),
                "bounded Done hook release");
    }
    static void lifetime() {
        Fixture f;
        Client* client = new Client(-1);
        f.client(*client);
        f.server.client_accepted();
        const std::string key = f.key(f.sid());
        prepare(*client, {Slice("SET"), slice(key), Slice("new")}, f.server);
        client->rob().publish();
        ExLoop::test_after_done_ = hold_done;
        std::thread worker([&] { require(f.loops[f.source].execute(Task{client, 0, -1, nullptr}),
                                        "paused executor completed"); });
        {
            std::unique_lock lock(pause_mutex);
            require(pause_cv.wait_for(lock, std::chrono::seconds(10), [] { return done_hook_entered; }),
                    "executor reached post-Done/pre-notification window");
        }
        require(client->rob().drain([](Op&) {}) == 1 && client->safe_to_release(),
                "IO backstop retired Done before notification");
        require(f.server.client_work_epoch(f.source) & 1, "executor lifetime scope is active");
        client->mark_closing();
        f.io.close_client(client);
        for (uint32_t i = 0; i < 4; i++) f.io.reap_dead();
        require(f.io.dead_next_.empty() && f.io.dead_ready_.empty() &&
                    f.server.live_clients() == 1 && !client->dead(),
                "close/reap held client across more than two IO iterations");
        {
            std::lock_guard lock(pause_mutex);
            done_hook_release = true;
        }
        pause_cv.notify_all();
        worker.join();
        ExLoop::test_after_done_ = nullptr;
        require(!(f.server.client_work_epoch(f.source) & 1), "executor tail finished");
        // Another pass can already be active: reclamation waits for the captured scope,
        // never for all executors to become idle simultaneously.
        Server::ClientWorkScope next_pass(f.server, f.source);
        f.io.close_client(client);
        require(f.server.live_clients() == 0 && f.io.dead_next_.size() == 1,
                "client released once captured executor scope ends");
        f.io.reap_dead();
        f.io.reap_dead();
        require(f.io.dead_ready_.empty(), "corpse reclaimed after channel grace");
    }

    inline static ExLoop* ack_loop = nullptr;
    inline static bool ack_entered = false;
    static void after_ack() {
        ack_entered = true;
        require(ack_loop->srv_->flip_acked(ack_loop->self_->id(), FlipStage::ExDrain),
                "ExDrain acknowledgement visible");
        require(ack_loop->lb_bytes_next_ms_ > ack_loop->cached_now_ms_,
                "due census finished BEFORE acknowledgement");
        // Model the coordinator replacing the vector at this exact safe point. Any
        // later census/shard walk in this tail now fails deterministically.
        ack_loop->self_->shards().assign(1, nullptr);
    }
    static void drain_ack() {
        Fixture f;
        auto& loop = f.loops[f.source];
        loop.lb_sample_rate_ = f.server.lb_sample_rate();
        require(loop.lb_sample_rate_ && loop.lb_bytes_next_ms_ <= loop.cached_now_ms_,
                "census due on ordinary loop entry");
        auto owned = loop.self_->shards();
        f.server.flip_epoch_.store(1);
        f.server.flip_stage_.store(FlipStage::ExDrain, std::memory_order_release);
        ack_loop = &loop;
        ExLoop::test_after_drain_ack_ = after_ack;
        require(loop.owner_control_tail() != 0 && ack_entered, "mid-pass ExDrain fired");
        ExLoop::test_after_drain_ack_ = nullptr;
        loop.self_->shards() = owned;
        f.server.flip_stage_.store(FlipStage::Idle, std::memory_order_release);
    }

    static void route_order() {
        Fixture f;
        Client client(-1);
        f.client(client);
        const int32_t sid = f.sid();
        const std::string key = f.key(sid);
        require(command(f, client, {Slice("SET"), slice(key), Slice("old")}) == "+OK\r\n",
                "seed old value");
        Op& set = prepare(client, {Slice("SET"), slice(key), Slice("new")}, f.server);
        const uint32_t sampled_owner = f.server.worker_of_shard(set.shard);
        Task unpublished{&client, client.rob().dispatch_id(), -1, nullptr};
        require(sampled_owner == f.source && f.server.thread(sampled_owner).ex_inbound_quiesced(),
                "IO holds routed task while owner inbox is empty");
        f.server.lb_epoch_.store(1);
        f.server.lb_start_shard_drain();
        require(f.server.lb_stage() == LbStage::IoDrain && f.server.lb_dispatch_paused(),
                "producer barrier starts before executor barrier");
        for (uint32_t tid : f.server.placement().ifid_threads())
            if (tid != f.io_id) f.server.lb_ack(tid);
        require(!f.server.lb_begin_ex_drain(), "unpublished producer prevents ownership move");
        client.rob().publish();
        require(f.server.thread(sampled_owner).post_task_quiet(
                    f.io_id, unpublished, f.server.thread(f.io_id).sig()), "publish old-route SET");
        f.server.lb_ack(f.io_id);
        require(f.server.lb_begin_ex_drain(), "all IO passed publication barrier");
        require(!f.loops[f.source].flip_quiesced(), "published old-route task prevents EX ack");
        require(f.loops[f.source].drain_tasks(true) == 1, "old owner executes SET before move");
        for (uint32_t tid : f.server.placement().ex_threads()) {
            require(f.loops[tid].flip_quiesced(), "executor fully drained");
            f.server.lb_ack(tid);
        }
        require(f.server.lb_all_ex_acked(), "both executor acknowledgements fired");
        f.move(sid, false);
        f.server.lb_stage_.store(LbStage::Idle, std::memory_order_release);
        require(client.rob().drain([](Op&) {}) == 1, "SET reply retired");
        require(command(f, client, {Slice("GET"), slice(key)}) == "$3\r\nnew\r\n",
                "following GET observes SET across ownership change");
    }

    template <bool Fused, bool DestinationAck>
    static void lb_continuous_arrivals() {
        Fixture<Fused> f;
        Client client(-1);
        f.client(client);
        // Drive the parser specialization used by stack3's active-client retry pass.
        // Arrivals enter the real buffer; no socket/ring or writeback loop is started.
        client.set_recv_armed(true);
        f.server.thread(f.io_id).clients().push_back(&client);
        command_client_connected(&client, "unit", "unit", false, 1);
        f.io.climon_track_client(&client);
        f.io.mark_active(&client);
        const uint32_t destination = Fused ? 0 : 1;
        f.server.lb_client_move_ = {client.id(), f.io_id, destination, 1};
        f.server.lb_coordinator_ = f.io_id;
        f.server.lb_epoch_.store(1);
        f.server.lb_deadline_ns_.store(now_ns() + LbAutotune::kMoveTimeoutNs);
        f.server.lb_stage_.store(LbStage::ClientDrain, std::memory_order_release);
        if constexpr (DestinationAck) f.server.lb_ack(destination);
        constexpr char request[] = "*1\r\n$4\r\nPING\r\n";
        uint32_t arrivals = 0;
        {
            // O1 removed v3's pending-IFID fence. Instead hold a real executor completion
            // after its reply retired: the ROB is empty but the Client lifetime fence is live.
            Op* completed = client.rob().acquire<false>();
            require(completed != nullptr, "publish completion before client drain");
            client.rob().publish();
            Server::ClientWorkScope unfinished(f.server, f.source);
            completed->state.store(OpState::Done, std::memory_order_release);
            require(client.rob().drain([](Op&) {}) == 1, "retire reply before executor scope ends");
            for (unsigned pass = 0; pass < 4 && f.server.lb_stage() == LbStage::ClientDrain; pass++) {
                std::memcpy(client.rbuf() + client.rlen(), request, sizeof(request) - 1);
                client.commit_read(sizeof(request) - 1);
                arrivals++;
                require(f.io.parse_and_dispatch<false, Fused ? kGenthreadIfidBatchOps : 0>(
                            &client) == IoLoop::DispatchResult::Progress,
                        "production parser visits held input");
                require(client.rpos() == 0 && client.rob().quiesced() && client.in_active() &&
                            client.migration_protocol_idle(),
                        "LB holds already-read input with EMPTY ROB on the active client");
                std::string error;
                require(!f.io.client_transfer_ready(&client, destination, error) &&
                            error == "connection has an unfinished executor completion",
                        "readiness rejects the actual outstanding executor lifetime fence");
                require(f.io.lb_control_pass() != 0, "pending control tail reports work");
            }
            require(!f.server.lb_timed_out(), "pass bound fires before five-second guard");
            require(f.server.lb_stage() == LbStage::Idle && f.server.lb_client_refused() == 1,
                    "busy move MUST be refused within four passes of continuous arrivals");
            require(arrivals == 1, "busy move refuses on the FIRST tail, even without destination ACK");
            std::string error;
            require(!f.io.client_transfer_ready(&client, destination, error) &&
                        error == "connection has an unfinished executor completion",
                    "refusal never weakens the lifetime fence");
        }
        require(f.server.lb_policy_->stall.refused[static_cast<size_t>(LbStallReason::Executor)] == 1,
                "diagnostic identifies the outstanding executor predicate");
#ifdef TOMO_LB_STALL_DEBUG
        require(f.server.lb_policy_->stall.parked_passes >= 1 &&
                    f.server.lb_policy_->stall.parked_bytes_max >= sizeof(request) - 1,
                "debug accounting saw the actual parked input");
        std::string info;
        f.server.lb_stall_info(info);
        require(info.find("tomokv_lbstall_debug:1\r\n") != std::string::npos &&
                    info.find("tomokv_lbstall_executor:1\r\n") != std::string::npos,
                "INFO exposes the armed diagnostic and refusing predicate");
#endif
        require(f.io.parse_and_dispatch<false, Fused ? kGenthreadIfidBatchOps : 0>(
                    &client) == IoLoop::DispatchResult::Progress &&
                    client.rpos() == client.rlen(), "refusal resumes the SAME buffered frames");
        uint32_t replies = 0;
        client.rob().drain([&](Op& op) {
            require(op.reply_code_ == static_cast<uint8_t>(ReplyCode::Pong) ||
                        std::string(op.reply.data(), op.reply.size()) == "+PONG\r\n",
                    "held request has its correct ordered reply");
            replies++;
        });
        require(replies == arrivals, "every held frame answered exactly once");
        client.set_recv_armed(false);
        command_client_disconnected(&client);
        f.server.thread(f.io_id).clients().clear();
    }

    static void lb_destination_and_executor() {
        Fixture f;
        Client client(-1);
        f.client(client);
        f.server.thread(f.io_id).clients().push_back(&client);
        command_client_connected(&client, "unit", "unit", false, 1);
        f.io.climon_track_client(&client);
        auto request = [&](uint64_t epoch) {
            f.server.lb_epoch_.store(epoch);
            f.server.lb_client_move_ = {client.id(), f.io_id, 1, 1};
            f.server.lb_coordinator_ = f.io_id;
            f.server.lb_deadline_ns_.store(now_ns() + LbAutotune::kMoveTimeoutNs);
            f.server.lb_stage_.store(LbStage::ClientDrain, std::memory_order_release);
        };
        request(1);
        std::string error;
        require(f.io.client_transfer_ready(&client, 1, error), "idle client is a valid candidate");
        // Destination never acknowledges. Even a ready source must get its traffic back.
        for (uint32_t pass = 1; pass <= LbStallState::kPassLimit; pass++) {
            require(f.io.lb_control_pass() != 0, "pending drain cannot sleep between passes");
            require((f.server.lb_stage() == LbStage::Idle) == (pass == LbStallState::kPassLimit),
                    "destination acknowledgement wait has an exact pass bound");
        }
        request(2);
        Op* completed = client.rob().acquire<false>();
        require(completed != nullptr, "publish a fresh completion to reset the lifetime snapshot");
        client.rob().publish();
        {
            Server::ClientWorkScope unfinished(f.server, f.source);
            completed->state.store(OpState::Done, std::memory_order_release);
            require(client.rob().drain([](Op&) {}) == 1, "retire Done while its executor still holds Client");
            require(client.migration_protocol_idle(), "executor-only fence with empty ROB");
            require(!f.io.client_transfer_ready(&client, 1, error), "unfinished scope really armed");
            require(f.io.lb_control_pass() != 0 && f.server.lb_stage() == LbStage::Idle,
                    "unfinished executor refuses move without waiving its lifetime fence");
        }
        require(f.io.client_transfer_ready(&client, 1, error), "ending the scope permits transfer");
        request(3);
        require(f.server.lb_client_move_started(client.id(), 1), "quiescent candidate starts");
        require(!f.server.lb_refuse_stalled(3, LbStallReason::PassLimit) &&
                    f.server.lb_stage() == LbStage::ClientMoving,
                "bounded refusal cannot revoke an in-flight kernel-pointer handoff");
        f.server.lb_client_move_cancelled(client.id());
        require(f.server.lb_policy_->stall.refused[static_cast<size_t>(LbStallReason::Executor)] == 1,
                "executor-only refusal has its own diagnostic");
        command_client_disconnected(&client);
        f.server.thread(f.io_id).clients().clear();
    }

    template <bool Fused>
    static void lb_shard_budget() {
        Fixture<Fused> f;
        Client client(-1);
        f.client(client);
        const int32_t sid = f.sid();
        const std::string key = f.key(sid);
        Op& set = prepare(client, {Slice("SET"), slice(key), Slice("held")}, f.server);
        const Task task{&client, client.rob().dispatch_id(), -1, nullptr};
        client.rob().publish();
        require(f.server.thread(f.source).post_task_quiet(f.io_id, task, f.io.self_->sig()),
                "publish real old-route SET");
        f.server.lb_epoch_.store(1);
        f.server.lb_coordinator_ = f.io_id;
        f.server.lb_shard_moves_ = {{static_cast<uint32_t>(sid), f.source, f.destination, 1, 0}};
        f.server.lb_deadline_ns_.store(now_ns() + LbAutotune::kMoveTimeoutNs);
        f.server.lb_start_shard_drain();
        require(f.io.lb_control_pass() && f.server.lb_stage() == LbStage::IoDrain,
                "unacknowledged producers hold the publication fence");
        for (uint32_t tid : f.server.placement().ifid_threads()) f.server.lb_ack(tid);
        require(f.io.lb_control_pass() && f.server.lb_stage() == LbStage::ExDrain,
                "second pass opens executor drain only after all producers publish");
        require(!f.loops[f.source].flip_quiesced() && !f.server.lb_all_ex_acked(),
                "real unpublished completion prevents executor quiescence");
        require(f.io.lb_control_pass() && f.server.lb_stage() == LbStage::Idle,
                "third pass refuses: changing drain stage must not reset the budget");
        require(f.server.worker_of_shard(sid) == f.source && set.state == OpState::Issued,
                "refusal preserves owner and queued SET");
        require(f.loops[f.source].drain_tasks(true) == 1, "original owner resumes its queued SET");
        require(client.rob().drain([](Op&) {}) == 1, "queued SET retires exactly once");
        require(command(f, client, {Slice("GET"), slice(key)}) == "$4\r\nheld\r\n",
                "RYOW survives a refused shard move");

        // Fresh epoch, clean queues: a normal two-tail move still commits.
        f.server.lb_epoch_.store(2);
        f.server.lb_deadline_ns_.store(now_ns() + LbAutotune::kMoveTimeoutNs);
        f.server.lb_start_shard_drain();
        for (uint32_t tid : f.server.placement().ifid_threads()) f.server.lb_ack(tid);
        require(f.io.lb_control_pass() && f.server.lb_stage() == LbStage::ExDrain,
                "fresh movement gets its own publication budget");
        for (uint32_t tid : f.server.placement().ex_threads()) {
            require(f.loops[tid].flip_quiesced(), "control executor is quiescent");
            f.server.lb_ack(tid);
        }
        require(f.io.lb_control_pass() && f.server.lb_stage() == LbStage::Idle &&
                    f.server.worker_of_shard(sid) == f.destination && f.server.lb_bucket_moves() == 1,
                "ready shard plan commits within the bound");
        require(command(f, client, {Slice("GET"), slice(key)}) == "$4\r\nheld\r\n",
                "RYOW survives a committed shard move");
        // A stalled coordinator must not pin other live IOs until its timeout check runs.
        f.server.lb_epoch_.store(3);
        f.server.lb_coordinator_ = f.io_id == 0 ? 1 : 0;
        f.server.lb_start_shard_drain();
        for (uint32_t pass = 0; pass < LbStallState::kPassLimit; pass++)
            require(f.io.lb_control_pass() != 0, "non-coordinator keeps making bounded passes");
        require(f.server.lb_stage() == LbStage::Idle &&
                    f.server.worker_of_shard(sid) == f.destination,
                "a live non-coordinator can refuse without waiting for the coordinator");
    }

    static void lb_commit_refusal_race() {
        Fixture f;
        const uint32_t sid = static_cast<uint32_t>(f.sid());
        require(f.server.reserve_shard_capacity(f.destination, 1), "pre-reserve test transfer");
        f.server.lb_epoch_.store(1);
        f.server.lb_shard_moves_ = {{sid, f.source, f.destination, 1, 0}};
        f.server.lb_stage_.store(LbStage::ExDrain, std::memory_order_release);
        for (uint32_t tid : f.server.placement().ex_threads()) f.server.lb_ack(tid);
        std::atomic<uint32_t> entered{0};
        bool committed = false, refused = false;
        auto barrier = [&] {
            entered.fetch_add(1);
            while (entered.load() < 2) std::this_thread::yield();
        };
        std::thread mover([&] { barrier(); committed = f.server.lb_commit_shard_plan(1); });
        std::thread canceller([&] {
            barrier(); refused = f.server.lb_refuse_stalled(1, LbStallReason::PassLimit);
        });
        mover.join(); canceller.join();
        require(committed != refused && f.server.lb_stage() == LbStage::Idle,
                "commit and bounded refusal have exactly one winner");
        require(f.server.worker_of_shard(sid) == (committed ? f.destination : f.source),
                "dispatch resumes only after the winning ownership decision");
        require(!f.server.lb_refuse_stalled(0, LbStallReason::PassLimit),
                "stale movement cannot cancel another epoch");
    }

    static void lb_stalls() {
        lb_continuous_arrivals<true, true>();
        lb_continuous_arrivals<true, false>();
        lb_continuous_arrivals<false, true>();
        lb_continuous_arrivals<false, false>();
        lb_destination_and_executor();
        lb_shard_budget<false>();
        lb_shard_budget<true>();
        lb_commit_refusal_race();
        Fixture off(false);
        require(!off.server.lb_policy_, "LB=0 allocates no policy or stall accounting");
        for (unsigned pass = 0; pass < 8; pass++)
            require(off.io.lb_control_pass() == 0 && !off.server.lb_policy_,
                    "stable control tails allocate and account nothing");
    }

    static void snapshot_forward() {
        Fixture f;
        Client client(-1);
        f.client(client);
        const int32_t sid = f.sid();
        const std::string key = f.key(sid);
        require(command(f, client, {Slice("SET"), slice(key), Slice("before-cut")}) == "+OK\r\n",
                "seed snapshot preimage");
        prepare(client, {Slice("SET"), slice(key), Slice("after-cut")}, f.server);
        Task stale{&client, client.rob().dispatch_id(), -1, nullptr};
        client.rob().publish();
        f.move(sid, false);
        FlatStore& store = f.server.shard(sid).store();
        require(store.snapshot_prepare(1, 1000) == FlatStore::SnapshotWriteResult::Ready &&
                    store.snapshot_mark(sid, 1000), "snapshot capture active after move");
        auto& old = f.loops[f.source];
        old.snapshot_backlogs_.resize(16);
        old.schedule_snapshot_task(stale);
        require(old.snapshot_backlogs_[sid].empty() && store.snapshot_preimages() == 0,
                "former owner neither captures foreign preimage nor retains foreign backlog");
        std::vector<Task> forwarded;
        f.server.thread(f.destination).drain_tasks_unmasked(
            [&](const Task& task) { forwarded.push_back(task); });
        require(forwarded.size() == 1 && forwarded[0].op_id == stale.op_id,
                "stale task forwarded exactly once");
        auto& owner = f.loops[f.destination];
        owner.snapshot_backlogs_.resize(16);
        owner.schedule_snapshot_task(forwarded[0]);
        require(owner.snapshot_backlogs_[sid].size() == 1 && store.snapshot_preimages() == 1,
                "current owner entered Pending preimage backlog");
        // Complete the active preimage without walking any other slot.
        store.snapshot_progress(1 << 20, 0);
        require(owner.service_snapshot_backlogs(32) == 1 && owner.snapshot_backlogs_[sid].empty(),
                "current owner services and completes its snapshot backlog");
        require(client.rob().drain([](Op&) {}) == 1, "forwarded SET completes");
        store.snapshot_cancel();
        require(command(f, client, {Slice("GET"), slice(key)}) == "$9\r\nafter-cut\r\n",
                "forwarded snapshot write visible");
    }

    template <bool Fused>
    static void transfer_config(bool range) {
        Fixture<Fused> f;
        const int32_t sid = f.sid();
        auto& old = f.loops[f.source];
        auto& owner = f.loops[f.destination];
        f.server.set_maxmemory_config(16, MaxmemoryPolicy::NoEviction, 7);
        owner.refresh_live_config();
        require(owner.live_config_version_ != old.live_config_version_ &&
                    !f.server.shard(sid).store().maxmemory_enabled(),
                "source store retains V while destination cached V+1");
        const uint64_t version = owner.live_config_version_;
        f.move(sid, range);
        require(owner.live_config_version_ == version, "destination version unchanged by move");
        owner.refresh_live_config();
        require(f.server.shard(sid).store().maxmemory_enabled(), "incoming store enabled maxmemory");
        Client client(-1);
        f.client(client);
        const std::string key = f.key(sid);
        const std::string reply = command(f, client, {Slice("SET"), slice(key), Slice("too-large")});
        require(reply.find("OOM") != std::string::npos && f.server.shard(sid).store().size() == 0,
                "incoming store enforces the published memory limit");
    }
    template <bool Fused>
    static void transfer_notify(bool range) {
        Fixture<Fused> f;
        const int32_t sid = f.sid();
        auto& old = f.loops[f.source];
        auto& owner = f.loops[f.destination];
        f.server.shard(sid).bind_notify_pending(&old.notify_keyless_pending_);
        f.move(sid, range);
        // Simulate the first resumed task before either loop has reached its rebind tail.
        old.notify_keyless_pending_ = owner.notify_keyless_pending_ = false;
        f.server.shard(sid).notify_output_created();
        require(owner.notify_keyless_pending_ && !old.notify_keyless_pending_,
                "moved shard hints its new owner before any resumed control pass");
    }
};
} // namespace tomo

int main(int argc, char** argv) {
    using T = tomo::CoreConcurrencyTest;
    T::require(argc == 2, "select one regression row");
    T::require(tomo::command_registry_init(false), "command registry initialization");
    const std::string row = argv[1];
    if (row == "watch") T::watch_disconnect();
    else if (row == "scheduler") T::scheduler();
    else if (row == "lifetime") T::lifetime();
    else if (row == "drain") T::drain_ack();
    else if (row == "route") { T::route_order(); T::lb_stalls(); }
    else if (row == "lbstall") T::lb_stalls();
    else if (row == "snapshot") T::snapshot_forward();
    else if (row == "config") {
        for (bool range : {false, true}) { T::transfer_config<false>(range); T::transfer_config<true>(range); }
    } else if (row == "notify") {
        for (bool range : {false, true}) { T::transfer_notify<false>(range); T::transfer_notify<true>(range); }
    } else T::require(false, "unknown regression row");
    std::printf("PASS core concurrency %s (state assertions fired)\n", argv[1]);
}
