// Directed production-body schedule; no listeners, workers, ring initialization or load.
// The same object links against the hook-only PRE and POST production objects.
#include "src/core/server.h"
#include "src/cmd/acl.h"
#include "src/cmd/blocking.h"
#include "src/cmd/xshard.h"
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

using namespace tomo;
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL aclkeys-wake: %s\n", why); std::exit(1); }
}
static void fill(Op& op, const std::vector<std::string>& args) {
    for (const auto& value : args)
        require(op.push_arg(Slice(value.data(), value.size())), "retained argv");
    op.spec = command_lookup(op.arg(0));
    require(op.spec != nullptr, "registered command");
}
static std::string bytes(const Op& op) { return {op.reply.data(), op.reply.size()}; }

int main(int argc, char** argv) {
    require(command_registry_init(false), "command registry initialization");
    const bool fused = argc > 1 && std::string(argv[1]) == "fused";
    const bool atomic = argc > 2 && std::string(argv[2]) == "1";
    const std::string scenario = argc > 3 ? argv[3] : "window";
    const bool revoke = scenario.ends_with("-denied");
    const std::string kind = revoke ? scenario.substr(0, scenario.size() - 7) : scenario;
    const bool unblock = kind == "window-unblock";
    const bool window = kind == "window" || unblock;
    require(window || kind == "XREAD" || kind == "BLMOVE" || kind == "BRPOPLPUSH" ||
            kind == "XREADGROUP", "known witness scenario");
    Config cfg;
    cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.thread_mode = fused ? ThreadMode::Fused : ThreadMode::Split;
    cfg.read_local = fused ? 1 : 0;
    cfg.atomic = atomic; cfg.databases = kSingleDatabase ? 1 : 16;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
    cfg.save.clear(); cfg.enable_debug_command = DebugCommandMode::Yes;
    cfg.acl_users = {{"blocked", "on", "nopass", "~block:*", "+@all"}};
    cpu_set_t allowed;
    require(sched_getaffinity(0, sizeof(allowed), &allowed) == 0, "CPU affinity");
    std::string placement;
    unsigned selected = 0;
    for (int cpu = 0; cpu < CPU_SETSIZE && selected < 8; ++cpu) {
        if (!CPU_ISSET(cpu, &allowed)) continue;
        if (selected) placement += ',';
        placement += fused || selected < 6 ? "ifid@" : "ex@";
        placement += std::to_string(cpu);
        ++selected;
    }
    require(selected == 8, "eight assigned CPUs");
    cfg.place = placement.c_str();
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "gate geometry initialization");
    for (uint32_t tid = 0; tid < server.nthreads(); ++tid)
        require(fused ? server.thread(tid).init_task_inbox_local_fused()
                      : server.thread(tid).init_task_inbox_local(
                            server.placement().ifid_threads(), server.placement().ex_threads()),
                "owner task inbox initialization");
    command_bind_server(&server);
    std::string error;
    require(acl_initialize(server, cfg, error), "ACL initialization");
    const uint32_t io = server.placement().ifid_threads().front();
    ThreadCtx& sender = server.thread(io);
    Client client(-1);
    client.set_id(91); client.set_ifid_thread(io); client.set_wb_slot(0);
    uint32_t user = 0;
    require(acl_find_user(Slice("blocked", 7), user), "blocked ACL user");
    client.set_acl_user_idx(user);
    Ring unused_ring;
    ScatterArenaPool pool;
    const auto debug = [&](std::vector<std::string> args) {
        Op request;
        fill(request, args);
        command_set_local_context(&client, &sender);
        request.spec->handler(server.shard(0), request);
        command_set_local_context(nullptr, nullptr);
        return bytes(request);
    };
    const auto command = [&](const std::vector<std::string>& args, unsigned key_arg = 1) {
        Op request;
        fill(request, args);
        request.hash = FlatStore::hash_key(request.arg(key_arg));
        request.shard = server.router().shard_of(request.hash);
        auto& shard = server.shard(request.shard);
        auto& thread = server.thread(server.worker_of_shard(request.shard));
        blocking_bind_executor(&server, &thread, &unused_ring);
        request.spec->handler(shard, request);
        return bytes(request);
    };
    require(debug({"DEBUG", "aclkeys-unknown"}) ==
            "-ERR unknown subcommand or wrong number of arguments for 'debug' command\r\n",
            "existing DEBUG fallback text is unchanged");
    require(debug({"DEBUG", "XREAD-REGISTRATION-HOLD", "3"}) ==
            "-ERR value is not an integer or out of range\r\n", "reject invalid DEBUG stage");
    require(debug({"DEBUG", "XREAD-REGISTRATION-HOLD", window ? "1" : "0"}) == "+OK\r\n",
            "set DEBUG latch");
    const std::string key = "block:aclkeys";
    std::vector<std::string> read{"XREAD", "BLOCK", "0", "STREAMS", key, "0"};
    std::vector<std::string> add{"XADD", key, "1-0", "field", "value"};
    const bool move = kind == "BLMOVE" || kind == "BRPOPLPUSH";
    if (move) {
        std::string destination;
        const auto source_owner = server.worker_of_shard(server.router().shard_of(
            FlatStore::hash_key(Slice(key.data(), key.size()))));
        for (unsigned attempt = 0; attempt < 1000; ++attempt) {
            auto candidate = "block:destination:" + std::to_string(attempt);
            if (server.worker_of_shard(server.router().shard_of(FlatStore::hash_key(
                    Slice(candidate.data(), candidate.size())))) != source_owner) {
                destination = std::move(candidate); break;
            }
        }
        require(!destination.empty(), "move destination belongs to another owner");
        read = kind == "BLMOVE" ? std::vector<std::string>{kind, key, destination, "LEFT", "RIGHT", "0"}
                                : std::vector<std::string>{kind, key, destination, "0"};
        add = {"LPUSH", key, "value"};
    } else if (kind == "XREADGROUP") {
        require(command({"XGROUP", "CREATE", key, "group", "0", "MKSTREAM"}, 2) == "+OK\r\n",
                "consumer group creation");
        read = {"XREADGROUP", "GROUP", "group", "consumer", "BLOCK", "0", "STREAMS", key, ">"};
    }
    Op* op = client.rob().acquire();
    require(op != nullptr, "ROB acquisition");
    fill(*op, read);
    require(acl_check_queued(user, *op->spec, read) == AclDeniedReason::None,
            "initial command permission is admitted");
    BlockingDispatch dispatch;
    require(blocking_prepare(server, client, *op, 0, dispatch) == BlockingPrepare::Ready,
            "blocking prepare");
    require(dispatch.nshards == 1, "single-key registration wave");
    const int32_t sid = blocking_dispatch_shard(dispatch, 0);
    Shard& shard = server.shard(sid);
    ThreadCtx& owner = server.thread(server.worker_of_shard(sid));
    const auto execute = [&](const Task& task) {
        return fused ? blocking_execute_iofused(server, owner, unused_ring, task, shard, *op)
                     : blocking_execute(server, owner, unused_ring, task, shard, *op);
    };
    const auto resume = [&]() {
        return fused ? blocking_resume_move_iofused(server, sender, unused_ring, client, pool)
                     : blocking_resume_move(server, sender, unused_ring, client, pool);
    };
    client.set_blocked(true); client.barrier_acquire(BarrierOwner::Blocking);
    op->attach_blocking_state(dispatch.state);
    op->state.store(OpState::Issued);
    client.rob().publish();
    blocking_start(dispatch.state, 1);
    const Task probe{&client, 0, sid, reinterpret_cast<ScatterState*>(dispatch.state)};
    require(execute(probe), "empty initial probe");
    std::vector<Task> registrations;
    owner.drain_tasks([&](const Task& task) { registrations.push_back(task); });
    require(registrations.size() == 1, "actual registration task was posted");
    const Task registration = registrations.front();
    if (window) {
        require(!execute(registration),
                "owner registration really held");
        require(debug({"DEBUG", "XREAD-REGISTRATION-HOLD"}) == ":1\r\n", "registration stage observed");
        require(client.blocked() && !shard.has_blocking_waiters(), "published blocked flag precedes waiter");
    } else {
        require(execute(registration),
                "registration completes");
        require(client.blocked() && shard.has_blocking_waiters(), "real owner waiter is parked");
    }
    require(!sender.ready().any(), "no premature completion before XADD");
    // A single-thread ACL reload changes this existing user's permissions after
    // admission, without introducing IO loops/listeners into the owner schedule.
    if (revoke) {
        cfg.acl_users = {{"blocked", "on", "nopass", "~outside:*", "+@all"}};
        acl_shutdown();
        require(acl_initialize(server, cfg, error), "revoke retained key permission");
        uint32_t reloaded = UINT32_MAX;
        require(acl_find_user(Slice("blocked", 7), reloaded) && reloaded == user,
                "ACL reload preserves the witness user index");
        require(acl_check_queued(user, *op->spec, read) == AclDeniedReason::Key,
                "revoked key really fails permission checking");
    }
    require(command(add) == (move ? ":1\r\n" : "$3\r\n1-0\r\n"), "real waking write");
    bool notified = false;
    bool early_notification = false;
    if (window) {
        require(!sender.ready().any(), "XADD found no registered waiter");
        require(debug({"DEBUG", "XREAD-REGISTRATION-HOLD", "2"}) == "+OK\r\n", "advance registration");
        require(!execute(registration),
                "registration sees data and retains its last Task");
        require(debug({"DEBUG", "XREAD-REGISTRATION-HOLD"}) == ":2\r\n", "last Task stage observed");
        early_notification = sender.ready().take(0) == 1;
        require(!resume(),
                "IO cannot resume while an owner Task still refers to the op");
        require(debug({"DEBUG", "XREAD-REGISTRATION-HOLD"}) == ":3\r\n", "IO rejection stage observed");
        require(!sender.ready().any(), "IO has drained the notification");
        if (unblock) {
            require(blocking_request_unblock(client, true), "request unblock while the Task is held");
            require(!blocking_cancel_client(server, sender, unused_ring, client),
                    "the held owner Task retains cancellation responsibility");
        }
        require(debug({"DEBUG", "XREAD-REGISTRATION-HOLD", "0"}) == "+OK\r\n", "release last Task");
        require(execute(registration), "last Task departs");
        notified = sender.ready().take(0) == 1;
        std::printf("aclkeys-wake mode=%s atomic=%d db=%u registration=1 last_task=2 io_rejected=3 early_notification=%d final_notification=%d\n",
                    fused ? "fused" : "split", atomic, cfg.databases, early_notification, notified);
    } else {
        notified = sender.ready().take(0) == 1;
        std::printf("aclkeys-wake mode=%s atomic=%d db=%u command=%s parked=1 final_notification=%d\n",
                    fused ? "fused" : "split", atomic, cfg.databases, kind.c_str(), notified);
    }

    // Explicit manual IO visit permits cleanup on PRE too. This is not evidence of a wake;
    // only the production ready-mask publication above satisfies the assertion below.
    if (kind == "XREADGROUP" || unblock) {
        require(op->state.load() == OpState::Done, "direct completion on its owner");
        blocking_retire(server, client, *op, sender);
    } else {
        require(resume(), "resume scatter on explicit IO visit");
        unsigned fragments = 0;
        bool finished = false;
        for (unsigned pass = 0; !finished && pass < 16; ++pass) {
            for (uint32_t tid = 0; tid < server.nthreads(); ++tid) {
                server.thread(tid).drain_tasks([&](const Task& task) {
                    require(xshard_execute(task, server.shard(task.shard), *op, tid) == ScatterTaskResult::Complete,
                            "stream scatter gather");
                    const auto result = xshard_complete(server, server.thread(tid), unused_ring, task, *op);
                    if (result == ScatterFinish::Final) finished = true;
                    else if (result == ScatterFinish::CommitQueued)
                        xshard_queue_commit(server, server.thread(tid), task);
                    else require(result == ScatterFinish::Waiting, "scatter phase completion");
                    ++fragments;
                });
                xshard_flush_commits(server, server.thread(tid), unused_ring, &finished,
                    [](void* context, Client*) { *static_cast<bool*>(context) = true; });
            }
        }
        require(finished && (move ? fragments >= 2 : fragments == 1), "complete scatter owner wave");
        op->state.store(OpState::Done);
        xshard_retire(server, sender, unused_ring, client, *op, pool, io, nullptr, nullptr, nullptr);
    }
    const char* expected = revoke ? "-NOPERM No permissions to access a key\r\n" :
        unblock ? "-UNBLOCKED client unblocked via CLIENT UNBLOCK\r\n" : move ? "$5\r\nvalue\r\n" :
        "*1\r\n*2\r\n$13\r\nblock:aclkeys\r\n*1\r\n*2\r\n$3\r\n1-0\r\n*2\r\n$5\r\nfield\r\n$5\r\nvalue\r\n";
    require(bytes(*op) == expected, "exact admitted/revoked blocking reply");
    require(!client.blocked() && !client.scatter_barrier(), "blocking lifecycle retired");
    blocking_bind_executor(nullptr, nullptr, nullptr);
    require(notified, "last Task did not renew the consumed IO notification");
    if (window) require(!early_notification, "resume was notified before the last owner Task left");
    acl_shutdown();
    std::puts("PASS aclkeys-wake");
}
