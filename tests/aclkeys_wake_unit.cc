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
    const bool fused = argc > 1 && std::string(argv[1]) == "fused";
    const bool atomic = argc > 2 && std::string(argv[2]) == "1";
    Config cfg;
    cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.thread_mode = fused ? ThreadMode::Fused : ThreadMode::Split;
    cfg.atomic = atomic; cfg.databases = kSingleDatabase ? 1 : 16;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
    cfg.save.clear(); cfg.enable_debug_command = DebugCommandMode::Yes;
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
    command_bind_server(&server);
    std::string error;
    require(acl_initialize(server, cfg, error), "ACL initialization");
    const uint32_t io = server.placement().ifid_threads().front();
    ThreadCtx& sender = server.thread(io);
    Client client(-1);
    client.set_id(91); client.set_ifid_thread(io); client.set_wb_slot(0);
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
    require(debug({"DEBUG", "XREAD-REGISTRATION-HOLD", "1"}) == "+OK\r\n", "arm DEBUG latch");
    const std::vector<std::string> read{"XREAD", "BLOCK", "0", "STREAMS", "block:aclkeys", "0"};
    Op* op = client.rob().acquire();
    require(op != nullptr, "ROB acquisition");
    fill(*op, read);
    BlockingDispatch dispatch;
    require(blocking_prepare(server, client, *op, 0, dispatch) == BlockingPrepare::Ready,
            "blocking prepare");
    require(dispatch.nshards == 1, "single-key registration wave");
    const int32_t sid = blocking_dispatch_shard(dispatch, 0);
    Shard& shard = server.shard(sid);
    ThreadCtx& owner = server.thread(server.worker_of_shard(sid));
    client.set_blocked(true); client.barrier_acquire(BarrierOwner::Blocking);
    op->attach_blocking_state(dispatch.state);
    op->state.store(OpState::Issued);
    client.rob().publish();
    blocking_start(dispatch.state, 1);
    const Task probe{&client, 0, sid, reinterpret_cast<ScatterState*>(dispatch.state)};
    require(blocking_execute(server, owner, unused_ring, probe, shard, *op), "empty initial probe");
    std::vector<Task> registrations;
    owner.drain_tasks([&](const Task& task) { registrations.push_back(task); });
    require(registrations.size() == 1, "actual registration task was posted");
    const Task registration = registrations.front();
    require(!blocking_execute(server, owner, unused_ring, registration, shard, *op),
            "owner registration really held");
    require(debug({"DEBUG", "XREAD-REGISTRATION-HOLD"}) == ":1\r\n", "registration stage observed");
    require(client.blocked() && !shard.has_blocking_waiters(), "published blocked flag precedes waiter");
    require(!sender.ready().any(), "no premature completion before XADD");

    const std::vector<std::string> add{"XADD", "block:aclkeys", "1-0", "field", "value"};
    Op write;
    fill(write, add);
    write.hash = FlatStore::hash_key(write.key()); write.shard = sid;
    blocking_bind_executor(&server, &owner, &unused_ring);
    write.spec->handler(shard, write);
    require(bytes(write) == "$3\r\n1-0\r\n", "real XADD during the registration hold");
    require(!sender.ready().any(), "XADD found no registered waiter");
    require(debug({"DEBUG", "XREAD-REGISTRATION-HOLD", "2"}) == "+OK\r\n", "advance registration");
    require(!blocking_execute(server, owner, unused_ring, registration, shard, *op),
            "registration sees data and retains its last Task");
    require(debug({"DEBUG", "XREAD-REGISTRATION-HOLD"}) == ":2\r\n", "last Task stage observed");
    require(sender.ready().take(0) == 1, "first resume notification really published and consumed");
    require(!blocking_resume_move(server, sender, unused_ring, client, pool),
            "IO cannot resume while an owner Task still refers to the op");
    require(debug({"DEBUG", "XREAD-REGISTRATION-HOLD"}) == ":3\r\n", "IO rejection stage observed");
    require(!sender.ready().any(), "IO has drained the notification");
    require(debug({"DEBUG", "XREAD-REGISTRATION-HOLD", "0"}) == "+OK\r\n", "release last Task");
    require(blocking_execute(server, owner, unused_ring, registration, shard, *op), "last Task departs");
    const bool notified = sender.ready().take(0) == 1;
    std::printf("aclkeys-wake mode=%s atomic=%d db=%u registration=1 last_task=2 io_rejected=3 final_notification=%d\n",
                fused ? "fused" : "split", atomic, cfg.databases, notified);

    // Explicit manual IO visit permits cleanup on PRE too. This is not evidence of a wake;
    // only the production ready-mask publication above satisfies the assertion below.
    require(blocking_resume_move(server, sender, unused_ring, client, pool), "resume scatter on explicit IO visit");
    unsigned fragments = 0;
    for (uint32_t tid = 0; tid < server.nthreads(); ++tid) {
        server.thread(tid).drain_tasks([&](const Task& task) {
            require(xshard_execute(task, server.shard(task.shard), *op, tid) == ScatterTaskResult::Complete,
                    "stream scatter gather");
            require(xshard_complete(server, server.thread(tid), unused_ring, task, *op) == ScatterFinish::Final,
                    "single-fragment scatter completion");
            ++fragments;
        });
    }
    require(fragments == 1, "exactly one scatter fragment");
    op->state.store(OpState::Done);
    xshard_retire(server, sender, unused_ring, client, *op, pool, io, nullptr, nullptr, nullptr);
    require(bytes(*op) == "*1\r\n*2\r\n$13\r\nblock:aclkeys\r\n*1\r\n*2\r\n$3\r\n1-0\r\n*2\r\n$5\r\nfield\r\n$5\r\nvalue\r\n",
            "exact XREAD reply");
    require(!client.blocked() && !client.scatter_barrier(), "blocking lifecycle retired");
    blocking_bind_executor(nullptr, nullptr, nullptr);
    require(notified, "last Task did not renew the consumed IO notification");
    std::puts("PASS aclkeys-wake");
}
