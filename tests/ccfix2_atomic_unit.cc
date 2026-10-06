// Reuse the atomics fixture to stop real owner phases before their commit ticket.
// No listener, worker, ring, timer, or load generator is started.
#define main ccfix2_unused_atomic_main
#include "atomic_survivors_unit.cc"
#undef main

int main(int argc, char** argv) {
    require(argc == 2, "ccfix2-atomic-unit armed|no-arm");
    const bool arm = std::string(argv[1]) == "armed";
    require(command_registry_init(false), "registry");
    Config cfg;
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
}
