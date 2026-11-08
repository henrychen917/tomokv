// Deterministic FIFO schedules through production owner gates, no worker loop.
#define TOMO_TXNORDER_EPISODES_LIBRARY
#include "tests/txnorder_episodes.cc"

namespace {
struct FifoUnit : EpisodeUnit {
    std::string key;
    FifoUnit(Server& s, uint64_t version, const std::string& k, bool whole = false,
             bool grouped = false)
        : EpisodeUnit(s, grouped), key(k) {
        age(version);
        if (whole)
            exec->claims[0].push_back(TxnClaim{});
        else
            claim(0, key, TxnClaimMode::Write);
        auto& slot = exec->claims[0][0];
        Shard::WatchReservation r{
            token(), &epoch(), &aborted(), grouped ? &group.watch_refs : &exec->watch_refs,
            &client, 0,        false,      false};
        r.unit_kind = grouped ? 2 : 1;
        r.entry_kind = 3;
        r.unit_mode = static_cast<uint8_t>(TxnClaimMode::Write);
        require(s.shard(0).watch_append_reservation(slot.key, r, &slot.waiter), "real waiter mark");
    }
};

void fifo_order(Server& server, bool many) {
    auto& shard = server.shard(0);
    const auto key = key_on(server, 0, "fifo-order-");
    FifoUnit u1(server, now_ns() - 1, key);
    Request w({"INCR", key});
    w.op.hash = FlatStore::hash_key(slice(key));
    const auto waits = server.txn_counter(TxnCounter::FifoWaits);
    require(!multi_plain_write_probe(shard, w.op), "F1 older waiter FIFO-refuses W");
    const uint64_t stamp = shard.watch_writer_stamp(slice(key), &w.op);
    require(stamp >= u1.exec->decision.age_ns && stamp != 0, "F1 observed episode age");
    require(server.txn_counter(TxnCounter::FifoWaits) > waits, "FIFO actually refused");
    std::vector<std::unique_ptr<FifoUnit>> later;
    for (unsigned i = 0, n = many ? 1000 : 1; i < n; ++i)
        later.push_back(std::make_unique<FifoUnit>(server, stamp + i + 1, key));
    require(!later.front()->place(0), "F2 younger U2 waits on live writer episode");
    require(!multi_plain_write_probe(shard, w.op), "F6 writer waits before S_F decides");
    u1.finish();  // Exactly one member of S_F(W).
    const auto marks = server.txn_counter(TxnCounter::WriterMarks);
    const auto passes = server.txn_counter(TxnCounter::FifoPasses);
    require(multi_plain_write_probe(shard, w.op), "F2 W ready while U2 still waits");
    require(shard.watch_writer_stamp(slice(key), &w.op) == stamp, "F3 first probe preserves stamp");
    require(multi_plain_write_probe(shard, w.op), "F3 second dispatch probe passes");
    require(shard.watch_writer_stamp(slice(key), &w.op) == stamp,
            "F3 second probe preserves stamp");
    require(multi_plain_write_ready(shard, w.op), "F3 final execution gate passes");
    require(!shard.watch_writer_stamp(slice(key), &w.op), "F3 final gate removes episode");
    require(server.txn_counter(TxnCounter::WriterMarks) == marks, "F3 never re-episodes");
    require(server.txn_counter(TxnCounter::FifoPasses) == passes + 1, "one passing episode");
    later.front()->exec->place_blockers[0].clear();
    require(later.front()->place(0), "F2 U2 places after writer");
}

void exclusions(Server& server) {
    auto& sh = server.shard(0);
    const auto key = key_on(server, 0, "fifo-exclusions-");
    local(server, {"LPUSH", key, "value"});
    FifoUnit waiting(server, 1, key);
    Request writer({"INCR", key});
    writer.op.hash = FlatStore::hash_key(slice(key));
    require(!multi_plain_write_probe(sh, writer.op), "F4 FIFO positive control");
    sh.watch_writer_forget(&writer.op);
    require(sh.watch_write_ready(slice(key)), "F4 serve/registration original predicate");
    require(sh.watch_group_write_ready(slice(key)), "F4 blind group ignores waiter");
    require(sh.watch_txn_write_ready(slice(key), *waiting.exec),
            "F4 EXEC write falsifier ignores waiter");
    Client watcher{-1};
    watcher.set_id(8200);
    require(sh.watch_add(slice(key), &watcher, watcher.watch_generation()),
            "F4 actual WATCH registration passes");
    require(!watcher.watch_dirty(), "WATCH clean before committed dirtying");
    sh.watch_write_committed(slice(key));
    require(watcher.watch_dirty(), "F4 commit dirtying still fires beside waiter");
    sh.watch_remove(slice(key), &watcher, watcher.watch_generation());
    Client consumer{-1};
    consumer.set_id(8201);
    Op* op = consumer.rob().acquire();
    require(op, "serve ROB slot");
    std::vector<std::string> args{"BLPOP", key, "0"};
    for (const auto& arg : args) require(op->push_arg(slice(arg)), "serve argv");
    op->spec = command_lookup(op->arg(0));
    BlockingState serve;
    serve.server = &server;
    serve.client = &consumer;
    serve.op_id = 0;
    serve.selected = 0;
    serve.kind = BlockingKind::Blpop;
    serve.keys.push_back({0, key, FlatStore::hash_key(slice(key)), 0});
    serve.active_tasks.store(1);
    Ring ring;
    require(blocking_run_direct(serve, sh, server.thread(server.worker_of_shard(0)), ring),
            "F4 actual BLPOP serve ignores waiter");
    require(local(server, {"LLEN", key}) == ":0\r\n", "actual serve removes value");
    Request r({"MSET", key, "1"});
    ShardGroup group{};
    group.shard = 0;
    group.count = 1;
    KeyRef ref{};
    ref.arg = 1;
    ref.hash = FlatStore::hash_key(slice(key));
    uint32_t order = 0;
    ScatterState state;
    state.server = &server;
    state.groups = &group;
    state.nsub = 1;
    state.keys = &ref;
    state.key_order = &order;
    state.key_count = 1;
    state.kind = Kind::Mset;
    state.multi_child = true;
    Task task{&consumer, 0, 0, &state};
    require(txn_scatter_write_ready(task, sh, r.op), "F4 actual EXEC child gate");
    state.multi_child = false;
    state.atomic_group = true;
    require(txn_scatter_write_ready(task, sh, r.op), "F4 actual blind group gate");
    state.atomic_group = false;
    state.kind = Kind::Script;
    require(txn_scatter_write_ready(task, sh, r.op) && !state.aborted.load(),
            "F4 script APPLY not cancelled by FIFO");
    state.groups = nullptr;
    state.keys = nullptr;
    state.key_order = nullptr;
    // D-F3: a placed, unstarted claim remains passable.
    waiting.finish();
    EpisodeUnit placed(server);
    placed.claim(0, key, TxnClaimMode::Write);
    require(placed.place(0) && multi_plain_write_ready(sh, writer.op),
            "D-F3 unstarted claim is not FIFO");
    placed.finish();
    // D-F3 also applies when this very writer previously saw the EXEC waiting.
    // FIFO refusal is a waiter-state predicate, not an arrival-to-commit order.
    FifoUnit transitioning(server, now_ns() - 1, key);
    require(!multi_plain_write_probe(sh, writer.op),
            "D-F3 transition first observes a real FIFO refusal");
    require(transitioning.place(0), "D-F3 older waiter becomes a placed claim");
    require(!(transitioning.exec->execution_noted[0] & 8u), "D-F3 claim is genuinely unstarted");
    require(multi_plain_write_probe(sh, writer.op) && multi_plain_write_ready(sh, writer.op),
            "D-F3 previously refused writer may pass the placed unstarted EXEC");
}

void defaults(Server& server) {
    auto& sh = server.shard(0);
    const auto key = key_on(server, 0, "fifo-whole-");
    FifoUnit whole(server, 1, key, true);
    Request writer({"SET", key, "1"});
    writer.op.hash = FlatStore::hash_key(slice(key));
    require(multi_plain_write_ready(sh, writer.op), "F5 keyed writer ignores whole-shard waiter");
    Request flush({"FLUSHDB"});
    require(!sh.watch_fifo_all_write_ready(&flush.op), "F5 FLUSH waits on whole-shard waiter");
    whole.finish();
    require(sh.watch_fifo_all_write_ready(&flush.op),
            "F5 decided whole-shard waiter releases FLUSH");
    FifoUnit group(server, 1, key, false, true);
    require(multi_plain_write_ready(sh, writer.op), "D-F2 kind-2 waiter does not FIFO-block");
    FifoUnit exec(server, 2, key);
    require(!multi_plain_write_probe(sh, writer.op), "D-F2 EXEC behind group still FIFO-blocks");
    sh.watch_writer_forget(&writer.op);
}

// D4′ uses the very same age-ordered claim queue as EXEC. The script
// window is only optimistic-slot admission; an escalated script takes no slot.
void script_order(Server& server) {
    auto& shard = server.shard(0);
    for (bool script_first : {false, true}) {
        const auto key =
            key_on(server, 0, script_first ? "fifo-script-first-" : "fifo-exec-first-");
        FifoUnit older(server, 1, key, false, script_first);
        FifoUnit younger(server, 2, key, false, !script_first);
        (script_first ? older : younger).group.kind = Kind::Script;
        auto* queue = older.exec->claims[0][0].waiter.queue;
        require(queue == younger.exec->claims[0][0].waiter.queue,
                "F10 EXEC and escalated script share a physical-key queue");
        require(queue->head->entry.token == older.token(), "F10 common arrival order");
        require(!younger.place(0), "F10 younger EXEC/script cannot overtake older waiter");
        require(older.place(0), "F10 oldest EXEC/script places");
        older.phase().store(TxnPhase::Executing);
        older.exec->execution_noted[0] |= 8;
        require(!younger.place(0), "F10 younger waits through older execution");
        older.finish();
        require(younger.place(0), "F10 decision releases next EXEC/script");
        younger.finish();
    }
    const auto key = key_on(server, 0, "fifo-script-writer-");
    FifoUnit exec(server, 1, key);
    Request writer({"INCR", key});
    writer.op.hash = FlatStore::hash_key(slice(key));
    require(!multi_plain_write_probe(shard, writer.op), "F10 writer waits for EXEC");
    const auto stamp = shard.watch_writer_stamp(slice(key), &writer.op);
    FifoUnit script(server, stamp + 1, key, false, true);
    script.group.kind = Kind::Script;
    require(!script.place(0), "F10 younger script respects writer episode");
    exec.finish();
    require(multi_plain_write_probe(shard, writer.op) && multi_plain_write_ready(shard, writer.op),
            "F10 writer progresses before younger script");
    require(script.place(0), "F10 script progresses after writer");
}

void lifetimes(Server& server) {
    auto& sh = server.shard(0);
    const auto key = key_on(server, 0, "fifo-refs-");
    FifoUnit unit(server, 1, key);
    const auto refs = unit.exec->watch_refs.load();
    Request writer({"SET", key, "1"});
    writer.op.hash = FlatStore::hash_key(slice(key));
    for (int i = 0; i < 8; ++i)
        require(!multi_plain_write_probe(sh, writer.op), "F8 repeated FIFO refusal");
    require(unit.exec->watch_refs.load() == refs, "F8 indexed FIFO adds no lifetime pin");
    sh.watch_writer_forget(&writer.op);
    require(unit.exec->watch_refs.load() == refs, "F8 forget preserves only queue pin");
    require(!multi_plain_write_probe(sh, writer.op), "F8 new episode");
    unit.finish();
    require(multi_plain_write_ready(sh, writer.op), "F8 pass after finish");
    require(unit.exec->watch_refs.load() == 0, "F8 teardown releases all pins");
}

void promotions(Server& server) {
    auto& sh = server.shard(0);
    const auto key = key_on(server, 0, "fifo-promote-");
    FifoUnit older(server, 1, key);
    Client a{-1}, b{-1};
    Op* first = a.rob().acquire();
    Op* writer = b.rob().acquire();
    require(first && writer, "F9 two parked ROB tasks");
    first->shard = writer->shard = 0;
    a.rob().publish();
    b.rob().publish();
    const auto stamp = now_ns();
    require(sh.watch_writer_mark(slice(key), writer, false, stamp), "F9 writer episode");
    FifoUnit younger(server, stamp + 1, key);
    std::deque<Task> parked{{&a, 0, 0, nullptr}, {&b, 0, 0, nullptr}};
    MultiRetryPromoter promoter{&parked, [](void*, MultiOwnerRetryNode&) {},
                                [](void* context, const void* token, int32_t sid) {
                                    txn_promote_deferred_writer(
                                        *static_cast<std::deque<Task>*>(context), token, sid);
                                }};
    older.epoch().store(server.atomic_commit());
    sh.watch_finish_unit(older.exec->claims[0], older.token(), &promoter);
    require(parked.front().client == &b && parked.back().client == &a,
            "F9 retired unit promotes real deferred writer");
    sh.watch_writer_forget(writer);
    // The strengthened falsifier must also catch an unstarted placed claim.
    younger.finish();
    EpisodeUnit illegal(server);
    illegal.claim(0, key, TxnClaimMode::Write);
    illegal.age(stamp + 1);
    require(illegal.place(0), "falsifier injects placed claim before mark");
    const auto before = server.txn_counter(TxnCounter::OrderViolations);
    require(sh.watch_writer_mark(slice(key), writer, false, stamp), "inject impossible older mark");
    sh.watch_writer_check(slice(key), false, stamp);
    require(server.txn_counter(TxnCounter::OrderViolations) == before + 1,
            "B4 detects younger unstarted claim");
    sh.watch_writer_forget(writer);
}
}

int main(int argc, char** argv) {
    require(argc == 5, "F1..F10 mode atomic engine");
    require(command_registry_init(false), "registry");
    Config cfg;
    cfg.databases = 1;
    cfg.shards = 16;
    cfg.even_ifid = 6;
    cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
    cfg.atomic = std::atoi(argv[3]);
    cfg.thread_mode = std::string(argv[2]) == "1s" ? ThreadMode::Fused : ThreadMode::Split;
    cfg.net_io = std::string(argv[4]) == "epoll" ? NetIoEngine::Epoll : NetIoEngine::Uring;
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "serverless owner geometry");
    command_bind_server(&server);
    const std::string name = argv[1];
    if (name == "F1" || name == "F2" || name == "F3")
        fifo_order(server, false);
    else if (name == "F4")
        exclusions(server);
    else if (name == "F5")
        defaults(server);
    else if (name == "F6")
        fifo_order(server, true);
    else if (name == "F7") {
        for (int shape = 1; shape <= 7; ++shape) exhaustive(server, shape);
        txnorder_checks(server, "txnorder_f2");
    } else if (name == "F8")
        lifetimes(server);
    else if (name == "F9")
        promotions(server);
    else if (name == "F10")
        script_order(server);
    else
        require(false, "known FIFO case");
    release_records(server);
    std::printf("PASS %s %s a%s %s\n", argv[1], argv[2], argv[3], argv[4]);
}
