// PRE-compatible witness: S2 keeps admission/apply credits, so ExDrain cannot
// reach ClientPrepare even when the connection stays on a surviving IO.
#include "src/core/io_loop.h"
#include <cstdio>
#include <memory>
#include <sched.h>
using namespace tomo;
namespace tomo {
struct CoreConcurrencyTest {
    static void need(bool ok, const char* what) {
        if (!ok) { std::fprintf(stderr, "FAIL flipfix6 S2: %s\n", what); std::abort(); }
    }
    static int run(unsigned atomic, bool converting) {
        Server server;
        cpu_set_t cpus; CPU_ZERO(&cpus);
        need(sched_getaffinity(0, sizeof(cpus), &cpus) == 0, "affinity");
        std::string domain; unsigned count = 0;
        for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; ++cpu) if (CPU_ISSET(cpu, &cpus)) {
            if (count++) domain += '+';
            domain += std::to_string(cpu);
        }
        need(count == 8 && server.topo_.declare(domain.c_str()), "eight CPUs");
        need(server.placement_.build_even(server.topo_, 6, 2), "6:2 placement");
        need(server.placement_.reserve_runtime_roles(8), "roles");
        Config cfg; cfg.databases = TOMO_SINGLE_DATABASE ? 1 : 16;
        cfg.shards = 16; cfg.atomic = atomic; cfg.read_local = 0;
        cfg.thread_mode = ThreadMode::Split; cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
        cfg.save.clear(); need(server.init(cfg), "server state");
        command_bind_server(&server);
        auto loops = std::make_unique<ExLoopT<false>[]>(8);
        for (unsigned tid = 0; tid < 8; ++tid) {
            auto& thread = server.thread(tid);
            need(thread.init_task_inbox_local(server.placement().ifid_threads(),
                                              server.placement().ex_threads()), "inbox");
            loops[tid].srv_ = &server; loops[tid].self_ = &thread;
        }
        std::string error;
        need(server.flip_begin(5, 3, 0, error), "begin real FLIP");
        unsigned source = 1;
        for (unsigned tid = 1; tid < 6; ++tid)
            if ((server.flip_candidate_target(tid) == Role::Ex) == converting) { source = tid; break; }
        need((server.flip_candidate_target(source) == Role::Ex) == converting, "source role");
        Client client(-1); client.set_id(7); client.set_ifid_thread(source);
        server.thread(source).add_client(&client); server.client_accepted();
        IoLoop io; io.srv_ = &server; io.self_ = &server.thread(source);
        auto prepare = [&](std::initializer_list<Slice> args, MultiIoAction want) {
            Op op; op.reset(); for (auto arg : args) need(op.push_arg(arg), "argument");
            op.spec = command_lookup(op.arg(0)); need(op.spec, "command");
            MultiExecState* state = nullptr;
            need(multi_handle_io(server, client, op, source, state) == want, "prepared command");
            return state;
        };
        prepare({Slice("MULTI")}, MultiIoAction::LocalDone);
        prepare({Slice("INCR"), Slice("flipfix6:s2")}, MultiIoAction::LocalDone);
        auto* pending = prepare({Slice("EXEC")}, MultiIoAction::Dispatch);
        need(pending && prepare({Slice("EXEC")}, MultiIoAction::Dispatch) == pending,
             "same prepared unpublished state persists");
        need(client.rob().quiesced() && io.flip_io_drained(), "S2 passes IoDrain");
        need(server.atomic_inflight() == 1 && server.atomic_apply_inflight() == 1,
             "S2 holds one admission credit and one open apply interval");
        server.flip_set_stage(FlipStage::ExDrain);
        for (auto tid : server.placement().ex_threads()) {
            need(server.thread(tid).ex_inbound_quiesced(), "no owner task published");
            need(!loops[tid].flip_quiesced(), "S2 alone blocks executor quiescence");
            loops[tid].flip_control_pass();
            need(!server.flip_acked(tid, FlipStage::ExDrain), "ExDrain cannot acknowledge S2");
        }
        std::printf("ARMED flipfix6 S2 db%u atomic%u %s: IoDrain=1 inflight=1 apply=1 ExDrain=0\n",
                    cfg.databases, atomic, converting ? "converting" : "surviving");
        // Control: original-IO abandonment releases both credits. No other
        // executor readiness condition changes; the same pass now acknowledges.
        need(!multi_prepare_close(server, client, source), "abandon without WATCH cleanup");
        need(server.atomic_inflight() == 0 && server.atomic_apply_inflight() == 0,
             "abandon released both credits");
        for (auto tid : server.placement().ex_threads()) {
            need(loops[tid].flip_quiesced(), "only S2 prevented quiescence");
            loops[tid].flip_control_pass();
            need(server.flip_acked(tid, FlipStage::ExDrain), "control acknowledges after abandonment");
        }
        server.flip_refuse_active();
        server.thread(source).remove_client(&client); server.client_released();
        command_bind_server(nullptr);
        std::puts("PASS flipfix6 S2 executor-fence witness and abandonment control");
        return 0;
    }
};
}
int main(int argc, char** argv) {
    if (argc != 3 || !command_registry_init(false)) return 2;
    return CoreConcurrencyTest::run(std::stoul(argv[1]), std::string(argv[2]) == "converting");
}
