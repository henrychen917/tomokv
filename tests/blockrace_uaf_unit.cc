// blockrace finding (b): blocking_publish_completion / blocking_task_done / blocking_finish_cancelled
// read *state.server and state.client AFTER op.state.exchange(Done). In 2s mode the IO thread can
// retire the op and delete the BlockingState in between, so the executor reads freed memory. This
// unit makes that deterministic with a test-only hook (TOMO_BLOCKING_UAF_UNIT) placed right after
// the Done exchange and before the post-Done read: the executor pauses there, a second (IO) thread
// drops the last ref and frees the state, then the executor resumes and performs the read. Built
// under ASAN, the PRE code reports a heap-use-after-free READ; the fix (capture server/client before
// publishing Done) reads the captured locals and is clean. The hook compiles out of production.
#define TOMO_BLOCKING_UAF_UNIT
#define main atomic_survivors_unused_main
#include "tests/atomic_survivors_unit.cc"
#undef main

#include <thread>

namespace {

// Control block kept OUTSIDE the BlockingState, so signalling never touches the freed object.
std::atomic<int> g_exec_paused_after_done{0};  // executor reached the post-Done hook
std::atomic<int> g_io_freed_state{0};          // IO thread has deleted the BlockingState
BlockingState* g_state_for_io = nullptr;

void uaf_pause_after_done(BlockingState&) {
    // Executor is now past op.state.exchange(Done) and about to read state.server/state.client.
    g_exec_paused_after_done.store(1, std::memory_order_release);
    while (g_io_freed_state.load(std::memory_order_acquire) == 0) {
    }
    // The BlockingState has been freed by the IO thread. The PRE code now dereferences the freed
    // state to build the blocking_notify_sender arguments -> heap-use-after-free READ.
}

}  // namespace

int main(int argc, char** argv) {
    require(argc == 2, "mode argument (1s|2s)");
    require(command_registry_init(false), "commands");
    Config cfg;
    cfg.databases = kSingleDatabase ? 1 : 16;
    cfg.shards = 16;
    cfg.thread_mode = std::string(argv[1]) == "1s" ? ThreadMode::Fused : ThreadMode::Split;
    cfg.even_ifid = 6;
    cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "serverless owners");
    command_bind_server(&server);
    auto& self = server.thread(server.worker_of_shard(0));
    Ring ring;
    const std::string key = key_on(server, 0, "uaf-");

    Client waiter(-1);
    waiter.set_id(7101);
    Op* op = waiter.rob().acquire<false>();
    require(op, "waiter ROB slot");
    // push_arg borrows the Slice, so the argument bytes must outlive the Op.
    const std::vector<std::string> args{"BLPOP", key, "0"};
    for (const auto& a : args) require(op->push_arg(slice(a)), "argument");
    op->spec = command_lookup(op->arg(0));
    // A pop served on arrival has a composed reply and is Issued, with no registry alias (refs==1),
    // so the first retire frees the state immediately -- the widest (b) window.
    reply_array_header(op->sink(), 2);
    reply_bulk(op->sink(), slice(key));
    reply_bulk(op->sink(), slice("value"));
    op->state.store(OpState::Issued);
    waiter.rob().publish();

    // The BlockingState the executor completes and the IO retires: one shared ref (the Op's).
    auto* state = new BlockingState;
    state->server = &server;
    state->client = &waiter;
    state->op_id = 0;
    state->kind = BlockingKind::Blpop;
    state->refs.store(1);
    state->active_tasks.store(0);  // served on arrival: no outstanding owner task
    state->phase.store(BlockingPhase::Claimed);
    BlockingKey k;
    k.key = key;
    k.hash = FlatStore::hash_key(slice(key));
    k.shard = 0;
    state->keys.push_back(k);
    g_state_for_io = state;

    blocking_uaf_after_done_hook = uaf_pause_after_done;

    // IO thread: once the executor is paused after Done, drop the last ref and free the state,
    // exactly as blocking_retire -> blocking_state_release does when the IO retires the op.
    std::thread io([] {
        while (g_exec_paused_after_done.load(std::memory_order_acquire) == 0) {
        }
        blocking_state_release(g_state_for_io);  // refs 1 -> 0 -> delete BlockingState
        g_io_freed_state.store(1, std::memory_order_release);
    });

    // Executor thread: publish the completion. The hook fires after the Done exchange.
    std::thread ex([&] { blocking_publish_completion(*state, self, ring); });

    ex.join();
    io.join();
    blocking_uaf_after_done_hook = nullptr;

    // Reached only when the read used captured locals (the fix): no UAF. ASAN aborts the PRE build
    // before here.
    command_bind_server(nullptr);
    std::puts("PASS BLOCKRACE-UAF-NO-READ-AFTER-FREE");
    return 0;
}
