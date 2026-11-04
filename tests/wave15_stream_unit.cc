// Freeze the atomic decision/dirty-notification gap, without worker timing.
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
    const auto key = key_on(server, 0, "deleted-");
    auto& shard = server.shard(0);
    shard.set_cached_now_ms(now_realtime_ms(), 0);
    Request create({"XGROUP", "CREATE", key, "g", "$", "MKSTREAM"});
    create.op.hash = FlatStore::hash_key(slice(key)); create.op.shard = 0;
    create.op.spec->handler(shard, create.op);
    require(create.reply() == "+OK\r\n", "seed stream group");
    Client waiter(-1); waiter.set_id(9002);
    Op* op = waiter.rob().acquire<false>(); require(op, "waiter ROB");
    const std::vector<std::string> args{
        "XREADGROUP", "GROUP", "g", "c", "BLOCK", "0", "STREAMS", key, ">"};
    for (const auto& arg : args) require(op->push_arg(slice(arg)), "argument");
    op->spec = command_lookup(op->arg(0));
    op->state.store(OpState::Issued); waiter.rob().publish();
    auto* state = new BlockingState;
    state->server = &server; state->client = &waiter; state->op_id = 0;
    state->kind = BlockingKind::Xreadgroup; state->phase.store(BlockingPhase::Parked);
    state->stream_group = "g"; state->stream_consumer = "c";
    // Keep the completion in the fixture instead of notifying an absent IO loop.
    state->active_tasks.store(1);
    BlockingKey k; k.key = key; k.hash = create.op.hash; k.shard = 0;
    state->keys.push_back(k);
    auto* registry = blocking_registry_get(shard, true);
    require(registry && registry->add(shard, *state, 0), "registered group waiter");
    Client holder(-1); holder.set_id(91);
    std::unique_ptr<MultiExecState> parent(
        fixture_allocate_state(server, holder, 0, MultiStateKind::Execute));
    require(bool(parent), "real decision owner");
    parent->record_refs.store(1);
    parent->decision.phase.store(TxnPhase::Executing);
    void* entry = nullptr; KvObj* deleted = nullptr;
    require(shard.store().atomic_prepare_transaction(slice(key), k.hash, 91,
        &parent->decision.epoch, &parent->record_refs, &parent->decision.aborted,
        nullptr, entry), "prepare atomic deletion");
    shard.store().atomic_install_transaction(k.hash, slice(key), entry, deleted);
    shard.store().atomic_finish_plain();
    require(shard.store().find(k.hash, slice(key)) != nullptr, "undecided delete retains old view");
    shard.take_blocking_dirty();
    parent->decision.epoch.store(server.atomic_commit(), std::memory_order_release);
    require(shard.store().atomic_has_records() && !shard.store().find(k.hash, slice(key)),
        "committed deletion visible before its owner notification");
    require(!shard.take_blocking_dirty(), "notification gap actually armed");
    auto& self = server.thread(server.worker_of_shard(0)); Ring ring;
    blocking_bind_executor(&server, &self, &ring);
    // The executor calls this before entering XGROUP CREATE's plain view.
    blocking_plain_mutation_published(shard, create.op);
    require(state->phase.load() == BlockingPhase::Completed && op->replied(),
        "decided deletion must finish its waiter before CREATE can replace it");
    require(std::string(op->reply.data(), op->reply.size()).starts_with("-NOGROUP "),
        "old waiter receives exact error class");
    require(shard.blocking_waiters() == 0 && state->refs.load() == 1,
        "old group registration released once");
    blocking_state_release(state); release_records(server);
    blocking_bind_executor(nullptr, nullptr, nullptr); command_bind_server(nullptr);
    std::puts("PASS atomic deletion before delayed owner notification");
}
