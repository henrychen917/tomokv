// blockrace finding (a): the blocking-completion offer decision is an unprotected store->load pair
// on two atomics (blocking_publish_completion stores phase=Completed then loads active_tasks;
// blocking_task_done decrements active_tasks then loads phase). Two deterministic schedules drive
// the second offerer through a test-only hook (TOMO_BLOCKING_COMPLETION_UNIT) placed between the
// phase store and the participant decision. Both FAIL on the pre-fix code and PASS on the fix.
//   Schedule A (two offers -> recycle): the second offerer publishes the pop, the slot is recycled
//     by a later pipelined command, and the publisher then force-completes that later command with
//     the pop's reply -- a wrong reply.
//   Schedule B (no offer -> hang): neither offerer publishes, so the popped element is never set
//     Done and the client hangs forever.
// No server, no worker threads, no sockets. See round6-read/blocking-completion-races-analysis.md.
#define TOMO_BLOCKING_COMPLETION_UNIT
#define main atomic_survivors_unused_main
#include "tests/atomic_survivors_unit.cc"
#undef main

namespace {

// Flags recorded by the hook so the post-return assertion can name the symptom.
bool g_b_published = false;  // did the second offerer publish the pop (op became Done) in the hook?
bool g_recycled = false;     // did we model the IO retiring the pop and a later command reusing it?

BlockingState* make_waiter(Server& server, Client& waiter, const std::string& key,
                           const std::vector<std::string>& args) {
    Op* op = waiter.rob().acquire<false>();
    require(op, "waiter ROB slot");
    for (const auto& a : args) require(op->push_arg(slice(a)), "argument");
    op->spec = command_lookup(op->arg(0));
    op->state.store(OpState::Issued);
    waiter.rob().publish();
    auto* state = new BlockingState;
    state->server = &server;
    state->client = &waiter;
    state->op_id = 0;
    state->kind = BlockingKind::Blpop;
    BlockingKey k;
    k.key = key;
    k.hash = FlatStore::hash_key(slice(key));
    k.shard = 0;
    state->keys.push_back(k);
    return state;
}

// Compose the BLPOP array reply the owner's run_direct would have written before publishing.
void compose_blpop_reply(Op& op, const std::string& key, const std::string& value) {
    op.clear_reply();
    reply_array_header(op.sink(), 2);
    reply_bulk(op.sink(), slice(key));
    reply_bulk(op.sink(), slice(value));
}

// Schedule A: two offers reach a recycled ROB slot.
void schedule_two_offer(Server& server, ThreadCtx& self, Ring& ring, const std::string& key) {
    Client waiter(-1);
    waiter.set_id(7001);
    BlockingState* state = make_waiter(server, waiter, key, {"BLPOP", key, "0"});
    Op& op0 = waiter.rob().at(0);
    compose_blpop_reply(op0, key, "value");
    // One outstanding owner task B; the registry publisher A is about to complete the pop.
    state->active_tasks.store(1);
    state->phase.store(BlockingPhase::Claimed);
    g_b_published = g_recycled = false;

    blocking_completion_unit_hook = [](BlockingState& s, ThreadCtx& owner, Ring& r) {
        // The hook fires after A stored phase=Completed and before A's participant decision.
        // Run the second offerer B (the outstanding owner task).
        blocking_task_done(s, owner, r);
        Op& slot = s.client->rob().at(s.op_id);
        g_b_published = slot.state.load() == OpState::Done;
        if (g_b_published) {
            // Pre-fix: B published the pop. Model the IO retiring op0 and the client pipelining a
            // LATER command (GET) into the same id&63 slot. rob().at(op_id) now names that op.
            slot.reset();
            require(slot.push_arg(slice("GET")), "recycled arg");
            require(slot.push_arg(slice("later-key")), "recycled arg");
            slot.spec = command_lookup(slot.arg(0));
            slot.state.store(OpState::Issued);  // a fresh, unexecuted later command
            g_recycled = true;
        }
    };
    blocking_publish_completion(*state, self, ring);
    blocking_completion_unit_hook = nullptr;

    Op& slot = waiter.rob().at(0);
    if (g_b_published) {
        // The publisher A resumed after the recycle and acted on rob().at(op_id): it marked the
        // later GET Done, delivering the BLPOP completion to a command that never executed.
        const bool later_forced = g_recycled && slot.state.load() == OpState::Done;
        std::fprintf(stderr,
                     "FAIL BLOCKRACE-A-TWO-OFFER: second offerer published the pop while the "
                     "registry publisher was still live; recycled later command force-completed=%d "
                     "(wrong reply to a later pipelined command)\n",
                     later_forced);
        std::exit(1);
    }
    require(slot.state.load() == OpState::Done, "the fix completes op0 exactly once");
    require(std::string(slot.reply.data(), slot.reply.size()) ==
                "*2\r\n$" + std::to_string(key.size()) + "\r\n" + key + "\r\n$5\r\nvalue\r\n",
            "op0 keeps the exact BLPOP reply");
    require(state->active_tasks.load() == 0, "plain counts return active_tasks to zero");
    blocking_state_release(state);
    std::puts("PASS BLOCKRACE-A-TWO-OFFER");
}

// Schedule B: no offer -> the popped element is never published and the client hangs.
void schedule_no_offer(Server& server, ThreadCtx& self, Ring& ring, const std::string& key) {
    Client waiter(-1);
    waiter.set_id(7002);
    BlockingState* state = make_waiter(server, waiter, key, {"BLPOP", key, "0"});
    Op& op0 = waiter.rob().at(0);
    compose_blpop_reply(op0, key, "value");  // element popped, reply composed
    state->active_tasks.store(1);             // outstanding owner task B
    state->phase.store(BlockingPhase::Claimed);

    blocking_completion_unit_hook = [](BlockingState& s, ThreadCtx& owner, Ring& r) {
        // Fires after A's phase.store(Completed). A's count tells us which code is running:
        //   pre-fix:  active_tasks == 1  (A did not count itself; two independent words decide)
        //   fix:      active_tasks == 2  (A counted itself before the store; one RMW decides)
        const uint32_t counted = s.active_tasks.load(std::memory_order_acquire);
        if (counted == 1) {
            // Pre-fix two-word code. Model the x86-TSO (0,0) store-buffer window named in the
            // analysis: A's plain phase.store sits in its store buffer (invisible to B) and B's
            // locked decrement is not yet visible to A's upcoming plain active_tasks.load. A
            // shadow count keeps active_tasks != 0 for A's load (B's decrement hidden); B is not
            // the last participant and declines without publishing. Neither offerer publishes.
            s.active_tasks.fetch_add(1, std::memory_order_acq_rel);
            s.phase.store(BlockingPhase::Claimed, std::memory_order_release);
            blocking_task_done(s, owner, r);  // B: declines (not last)
            s.phase.store(BlockingPhase::Completed, std::memory_order_release);
            // shadow left in place -> A's load sees active_tasks != 0 and A defers.
        } else {
            // The fix: A is already a counted participant, so B simply is not the last one and
            // defers; A's own task_done is the final participant and publishes exactly once.
            blocking_task_done(s, owner, r);
        }
    };
    blocking_publish_completion(*state, self, ring);
    blocking_completion_unit_hook = nullptr;
    const bool shadow_held = state->active_tasks.load() != 0;
    state->active_tasks.store(0);  // drop any modelled shadow before teardown

    Op& slot = waiter.rob().at(0);
    if (slot.state.load() != OpState::Done) {
        require(slot.replied(), "the element was popped and its reply composed");
        std::fprintf(stderr,
                     "FAIL BLOCKRACE-B-NO-OFFER: phase=Completed and reply composed but op never "
                     "set Done (active_tasks residue=%d); the store->load pair permits a (0,0) "
                     "interleaving in which neither offerer publishes and the client hangs\n",
                     shadow_held);
        std::exit(1);
    }
    require(state->active_tasks.load() == 0, "plain counts return active_tasks to zero");
    blocking_state_release(state);
    std::puts("PASS BLOCKRACE-B-NO-OFFER");
}

}  // namespace

int main(int argc, char** argv) {
    require(argc == 2 || argc == 3, "usage: blockrace-unit <1s|2s> [two-offer|no-offer|both]");
    require(command_registry_init(false), "commands");
    const std::string which = argc == 3 ? argv[2] : "both";
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
    const std::string key = key_on(server, 0, "race-");
    if (which == "two-offer" || which == "both") schedule_two_offer(server, self, ring, key);
    if (which == "no-offer" || which == "both") schedule_no_offer(server, self, ring, key);
    release_records(server);
    command_bind_server(nullptr);
    std::puts("PASS BLOCKRACE-UNIT");
    return 0;
}
