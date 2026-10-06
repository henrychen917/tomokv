// Reuse the atomics fixture to stop real owner phases before their commit ticket.
// No listener, worker, ring, timer, or load generator is started.
#define main ccfix2_unused_atomic_main
#include "atomic_survivors_unit.cc"
#undef main

int main(int argc, char** argv) {
    require(argc == 2 || argc == 3, "ccfix2-atomic-unit armed|no-arm [1s|2s]");
    const bool arm = std::string(argv[1]) == "armed";
    require(command_registry_init(false), "registry");
    Config cfg;
    cfg.thread_mode = argc == 3 && std::string(argv[2]) == "1s"
        ? ThreadMode::Fused : ThreadMode::Split;
    cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
    cfg.save.clear();
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "gate geometry");
    command_bind_server(&server);
    server.pubsub_active_channel_added(); // subscriber witness, without any socket
    for (uint32_t i = 0; i < server.nshards(); ++i)
        server.shard(i).set_notify_mask(NOTIFY_KEYEVENT | NOTIFY_KEY_MISS);

    for (const char* verb : {"COPY", "SINTERSTORE", "BITOP"}) {
        const std::string stem = std::string("ccfix2:") + verb;
        const auto a = key_on(server, 0, (stem + ":a:").c_str());
        const auto b = key_on(server, 1, (stem + ":b:").c_str());
        const auto dest = key_on(server, 2, (stem + ":dst:").c_str());
        ScatterRun writer(server, {"MSET", a, "private", b, "private"});
        if (arm) {
            for (uint32_t i = 0; i < writer.state->nsub; ++i) {
                const int s = writer.state->groups[i].shard;
                require(xshard_execute(Task{&writer.client, 0, s, writer.state},
                    server.shard(s), writer.request.op, server.worker_of_shard(s)) ==
                    ScatterTaskResult::Complete, "install undecided writer record");
            }
        }
        require(writer.state->epoch.load() == 0, "writer remains undecided");
        for (const auto& key : {a, b}) {
            auto& store = server.shard(sid(server, key)).store();
            require(store.atomic_has_records() && store.atomic_has_record(
                FlatStore::hash_key(slice(key)), slice(key)), "pending record is on the source key");
            require(store.atomic_resolve(FlatStore::hash_key(slice(key)), slice(key),
                server.atomic_snapshot()) == nullptr, "foreign source is missing at reader cut");
        }
        std::vector<std::string> args;
        const std::string name = verb;
        if (name == "COPY") args = {name, a, dest};
        else if (name == "BITOP") args = {name, "OR", dest, a, b};
        else args = {name, dest, a, b};
        ScatterRun reader(server, args);
        reader.state->origin_conn_id = 778;
        reader.request.op.spec = command_notify_variant(reader.request.op.spec);
        reader.request.op.attach_scatter_state(reader.state);
        const uint64_t fired = server.notify_events_fired();
        for (uint32_t i = 0; i < reader.state->nsub; ++i) {
            const int s = reader.state->groups[i].shard;
            require(xshard_execute(Task{&reader.client, 0, s, reader.state},
                server.shard(s), reader.request.op, server.worker_of_shard(s)) ==
                ScatterTaskResult::Complete, "read real gather fragment");
        }
        const uint64_t expected = name == "COPY" ? 1 : 2;
        require(server.notify_events_fired() - fired == expected,
                "exact pending-source keymiss count (Redis read-lookup count)");
        auto* batch = reader.state->notify.exchange(nullptr);
        require(batch && batch->total == expected, "exact notification batch size");
        for (uint32_t i = 0; i < batch->inline_size; ++i) {
            require(batch->inline_records[i].event == NotifyEventId::Keymiss,
                    "each recorded event is keymiss");
            const Slice key = batch->inline_records[i].key;
            require(key.key_mem_eq(slice(a)) || key.key_mem_eq(slice(b)),
                    "missing destination never emits keymiss");
        }
        notify_discard_batch(batch);
        reader.request.op.detach_scatter_state();
        std::printf("PASS %s pending-source keymiss=%llu\n", verb,
                    (unsigned long long)expected);
    }
    ThreadCtx& thread = server.thread(0);
    ThreadCtx::bind_command_stats_thread(&thread);
    std::string acl_error;
    require(acl_initialize(server, cfg, acl_error), "default ACL initialized");
    const auto get = command_lookup(Slice("GET", 3))->id;
    const auto exec = command_lookup(Slice("EXEC", 4))->id;
    const auto eval = command_lookup(Slice("EVAL", 4))->id;
    require(local(server, {"LPUSH", "ccfix2:wrongtype", "v"}) == ":1\r\n", "seed wrong type");
    Client transaction{-1};
    transaction.set_id(91);
    require(multi_io(server, transaction, {"MULTI"}) == "+OK\r\n", "MULTI starts");
    require(multi_io(server, transaction, {"GET", "ccfix2:wrongtype"}) == "+QUEUED\r\n",
            "GET queued");
    require(multi_io(server, transaction, {"EXEC"}).starts_with("*1\r\n-WRONGTYPE"),
            "EXEC returns failing member");
    require(thread.command_failed_calls(get) == 1 && thread.command_failed_calls(exec) == 0,
            "member failure belongs to GET, not EXEC");
    require(multi_io(server, transaction, {"EXEC"}) == "-ERR EXEC without MULTI\r\n",
            "EXEC own error");
    require(thread.command_failed_calls(exec) == 1, "EXEC own error belongs to EXEC");
    Client aborted{-1};
    aborted.set_id(92);
    require(multi_io(server, aborted, {"MULTI"}) == "+OK\r\n", "abort MULTI starts");
    require(multi_io(server, aborted, {"GET", "ccfix2:wrongtype"}) == "+QUEUED\r\n",
            "abort member queued");
    multi_mark_queue_error(aborted);
    require(multi_io(server, aborted, {"EXEC"}).starts_with("-EXECABORT"),
            "queued error aborts EXEC");
    require(thread.command_failed_calls(exec) == 2 && thread.command_failed_calls(get) == 1,
            "EXECABORT belongs to EXEC; unexecuted member has no failed call");
    require(local(server, {"EVAL", "return {{err='ERR one'},{err='ERR two'}}",
            "0"}) == "*2\r\n-ERR one\r\n-ERR two\r\n", "multiple script error elements");
    require(thread.command_failed_calls(eval) == 1, "one failed call for multiple script errors");
    // The local() fixture routes by argv[1], which is a script rather than a key
    // for EVAL. Give this real handler its declared key's shard, as dispatch does.
    Request nested({"EVAL", "return redis.pcall('GET',KEYS[1])", "1", "ccfix2:wrongtype"});
    nested.op.spec->handler(server.shard(sid(server, "ccfix2:wrongtype")), nested.op);
    require(nested.reply().starts_with("-WRONGTYPE"), "returned nested error");
    require(thread.command_failed_calls(get) == 2 && thread.command_failed_calls(eval) == 2,
            "returned script error counts on the nested command and EVAL");
    ThreadCtx::bind_command_stats_thread(nullptr);
    std::puts("PASS EXEC and nested script error attribution");
}
