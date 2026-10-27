// An EXEC reservation refuses an actual registry serve. No workers or sockets.
#define main atomic_survivors_unused_main
#include "tests/atomic_survivors_unit.cc"
#undef main

int main(int argc, char** argv) {
    require(argc == 2, "mode argument");
    require(command_registry_init(false), "commands");
    Config cfg; cfg.databases = kSingleDatabase ? 1 : 16; cfg.shards = 16;
    cfg.thread_mode = std::string(argv[1]) == "1s" ? ThreadMode::Fused : ThreadMode::Split;
    cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
    Server server; require(server.prepare_boot(cfg) && server.init(cfg), "serverless owners");
    command_bind_server(&server);
    const auto key = key_on(server, 0, "refused-");
    require(local(server, {"LPUSH", key, "value"}) == ":1\r\n", "ready list");
    auto& shard = server.shard(0);
    Client holder(-1); holder.set_id(9001);
    std::unique_ptr<MultiExecState> exec(allocate_state(server, holder, 0, MultiStateKind::Execute));
    require(bool(exec), "EXEC state");
    exec->decision.age_ns = 1;
    txn_add_claim(exec->claims[0], slice(key), TxnClaimMode::Write);
    Shard::WatchReservation reservation{exec.get(), &exec->decision.epoch,
        &exec->decision.aborted, &exec->watch_refs, &holder, 0, false, true};
    reservation.unit_kind = 1;
    require(shard.watch_place_unit(exec->claims[0], reservation), "EXEC placed its key claim");
    exec->decision.phase.store(TxnPhase::Executing);
    exec->execution_noted[0] |= 8;
    require(!shard.watch_write_ready(slice(key)), "EXEC actually refuses the serve");
    Client waiter(-1); waiter.set_id(9002);
    Op* op = waiter.rob().acquire<false>(); require(op, "waiter ROB");
    const std::vector<std::string> args{"BLPOP", key, "0"};
    for (const auto& arg : args)
        require(op->push_arg(slice(arg)), "argument");
    op->spec = command_lookup(op->arg(0));
    op->state.store(OpState::Issued); waiter.rob().publish();
    auto* state = new BlockingState;
    state->server = &server; state->client = &waiter; state->op_id = 0;
    state->kind = BlockingKind::Blpop; state->phase.store(BlockingPhase::Parked);
    // Hold a registration task so completion cannot publish to an absent IO loop.
    state->active_tasks.store(1);
    BlockingKey k; k.key = key; k.hash = FlatStore::hash_key(slice(key)); k.shard = 0;
    state->keys.push_back(k);
    auto* registry = blocking_registry_get(shard, true);
    require(registry && registry->add(shard, *state, 0), "registered waiter");
    auto& self = server.thread(server.worker_of_shard(0)); Ring ring;
    registry->publish(shard, k.hash, slice(key), shard.now_ms(), self, ring);
    require(state->phase.load() == BlockingPhase::Parked && !op->replied(), "refused, still parked");
    require(shard.blocking_waiters() == 1 && state->refs.load() == 2,
            "refused serve retains its registry entry and lifetime pin");
    require(shard.take_blocking_dirty(), "refused serve rearms dirty probe");
    exec->decision.epoch.store(server.atomic_commit());
    shard.watch_finish_unit(exec->claims[0], exec.get());
    require(shard.watch_write_ready(slice(key)), "EXEC released the key");
    registry->sweep(shard, shard.now_ms(), true, self, ring);
    require(state->phase.load() == BlockingPhase::Completed, "same waiter served on retry");
    require(std::string(op->reply.data(), op->reply.size()) ==
        "*2\r\n$" + std::to_string(key.size()) + "\r\n" + key + "\r\n$5\r\nvalue\r\n", "exact BLPOP reply");
    require(shard.blocking_waiters() == 0 && state->refs.load() == 1, "successful serve drops alias once");
    blocking_state_release(state); release_records(server);
    command_bind_server(nullptr);
    std::puts("PASS BLOCK-SERVE-REFUSED-DROP");
}
