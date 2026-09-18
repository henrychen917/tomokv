// Real command/store identity checks without listeners, rings, or worker loops.
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#include "src/cmd/xshard.cc"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "src/core/server.h"
#include "src/cmd/multidb.h"
#include "src/cmd/cmdmeta.h"

using namespace tomo;
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL multidb: %s\n", why); std::exit(1); }
}
static std::string run(Server& server, Shard& shard, uint8_t db,
                       std::initializer_list<std::string> args, bool prebuild = false) {
    Op op;
    for (const auto& arg : args) require(op.push_arg(Slice(arg)), "push argument");
    op.spec = command_lookup(op.cmd_name());
    require(op.spec, "registered command");
    multidb_stamp(server, op, db);
    op.hash = FlatStore::hash_key(op.key());
    op.shard = shard.id();
    op.mark_no_borrow();
    if (prebuild) {
        const auto* original = op.spec;
        l4prebuild_prepare_set(op);
        require(op.spec != original && op.zc_ptr, "large SET actually selects L4 prebuild");
        const auto* candidate = reinterpret_cast<const KvObj*>(op.zc_ptr);
        require(candidate->encoding() == Enc::Extern && !candidate->has_ttl_slot() &&
                candidate->key().key_eq(op.key()), "prebuilt candidate identity and TTL layout");
    }
    op.spec->handler(shard, op);
    if (prebuild) require(!op.zc_ptr, "owner consumed prebuilt SET candidate");
    return std::string(op.reply.data(), op.reply.size());
}

// A long DB-0 key only tests KeyExt by length. The L4 TTL reheader must also
// write klen_ext when a short (even empty) key needs KeyExt solely for its DB.
static void prebuilt_ttl(bool armed) {
    struct Cache { KvBlockCache blocks; ~Cache() { blocks.release_all(); } } cache;
    Server server;
    Shard shard;
    shard.init(nullptr, 0, 0, kNumBuckets, 0, TypeLimits{}, StreamLimits{});
    shard.set_cached_now_ms(1000);
    if (armed) {
        require(shard.store().prepare_read_local(), "prebuild read-local allocation");
        shard.store().configure_read_local(true, {nullptr,
            [](void*, void* owner, void* p, size_t n, ReadLocalRetireSink::ReclaimFn reclaim) {
                reclaim(owner, p, n);
            }, &cache.blocks});
    }
    const std::string value(1024, 'v'), updated(1024, 'u');
    for (uint8_t db : {1, 15, 255, 0}) for (unsigned length : {1, 0, 254, 255, 307}) {
        const std::string key(length, 'k');
        const Slice identity(key.data(), key.size(), db);
        const auto hash = FlatStore::hash_key(identity);
        auto check = [&](const std::string& expected, int64_t deadline, bool slot) {
            auto* object = shard.store().find(hash, identity);
            require(object && object->key().key_eq(identity), "prebuilt TTL replacement keeps exact key identity");
            require(object->key_namespace() == db && object->klen() == length &&
                    bool(object->flags & KvObjFlags::KeyExt) == (db != 0 || length >= 255),
                    "prebuilt TTL replacement decodes namespace and extended length");
            require(object->encoding() == Enc::Extern && object->has_ttl_slot() == slot &&
                    shard.store().deadline(hash, object) == deadline,
                    "prebuilt TTL replacement retains Extern encoding and deadline");
            require(run(server, shard, db, {"GET", key}) == "$1024\r\n" + expected + "\r\n",
                    "prebuilt TTL GET exact bytes");
            require(run(server, shard, db, {"STRLEN", key}) == ":1024\r\n",
                    "prebuilt TTL STRLEN");
            const int64_t ttl = deadline < 0 ? -1 : deadline - 1000;
            require(run(server, shard, db, {"PTTL", key}) == ":" + std::to_string(ttl) + "\r\n",
                    "prebuilt TTL PTTL");
            if (armed) {
                const auto probe = shard.store().read_local_probe(hash, identity);
                require(probe.result == FlatStore::ReadLocalProbeResult::Hit && probe.object == object,
                        "prebuilt replacement remains readable in read-local lane");
            }
        };
        std::printf("L4 TTL case: read-local=%d db=%u key-bytes=%u value-bytes=1024\n",
                    armed, db, length);
        std::fflush(stdout);
        require(run(server, shard, db, {"SET", key, value, "EX", "60"}, true) == "+OK\r\n",
                "prebuilt SET EX reply");
        check(value, 61000, true);
        require(run(server, shard, db, {"SET", key, updated, "KEEPTTL"}, true) == "+OK\r\n",
                "prebuilt KEEPTTL reply");
        check(updated, 61000, true);
        require(run(server, shard, db, {"PERSIST", key}) == ":1\r\n", "prebuilt PERSIST reply");
        check(updated, -1, true);
        require(run(server, shard, db, {"SET", key, value, "KEEPTTL"}, true) == "+OK\r\n",
                "prebuilt KEEPTTL reserves persisted slot");
        check(value, -1, true);
        for (const char* expire : {"EXPIRE", "PEXPIRE", "GETEX"}) {
            require(run(server, shard, db, {"SET", key, value}, true) == "+OK\r\n",
                    "prebuilt SET removes old TTL slot");
            check(value, -1, false);
            if (std::strcmp(expire, "GETEX") == 0) {
                require(run(server, shard, db, {expire, key, "PX", "60000"}) ==
                        "$1024\r\n" + value + "\r\n", "GETEX adds TTL to prebuilt value");
            } else {
                require(run(server, shard, db, {expire, key,
                        std::strcmp(expire, "EXPIRE") == 0 ? "60" : "60000"}) == ":1\r\n",
                        "EXPIRE/PEXPIRE adds TTL to prebuilt value");
            }
            check(value, 61000, true);
        }
        require(run(server, shard, db, {"GETEX", key, "PERSIST"}) ==
                "$1024\r\n" + value + "\r\n", "GETEX PERSIST preserves value");
        check(value, -1, true);
    }
    std::printf("PASS multidb L4 TTL transitions (read-local %d)\n", armed);
}
static void layout_and_store(bool armed) {
    static_assert(sizeof(Slice) == 16);
    static_assert(sizeof(Op) == 336);
    static_assert(sizeof(Client) == 1984);
    static_assert(sizeof(ThreadCtx) == 1408);
    static_assert(sizeof(Shard) == 1440);
    static_assert(sizeof(FlatStore) == 944);
    static_assert(sizeof(Config) == 624);
    static_assert(sizeof(Rob<64>) == 192);
    static_assert(sizeof(AtomicEntry) == 144);
    struct Cache { KvBlockCache blocks; ~Cache() { blocks.release_all(); } } cache;
    Server server;
    Shard shard;
    shard.init(nullptr, 0, 0, kNumBuckets, 0, TypeLimits{}, StreamLimits{});
    shard.set_cached_now_ms(1000);
    if (armed) {
        require(shard.store().prepare_read_local(), "read-local allocation");
        // No concurrent readers in this fixture; each owner replacement has an immediate grace period.
        shard.store().configure_read_local(true, {nullptr,
            [](void*, void* owner, void* p, size_t n, ReadLocalRetireSink::ReclaimFn reclaim) {
                reclaim(owner, p, n);
            }, &cache.blocks});
    }
    for (const std::string& key : {std::string{}, std::string("k"),
            std::string("\0\xffkey", 5), std::string(254, 'k'), std::string(255, 'k'),
            std::string(256, 'k')}) {
        for (uint8_t db : {0, 1, 15, 255}) {
            require(run(server, shard, db, {"SET", key, "db" + std::to_string(db)}) == "+OK\r\n",
                    "SET namespace");
        }
        for (uint8_t db : {0, 1, 15, 255}) {
            const std::string value = "db" + std::to_string(db);
            require(run(server, shard, db, {"GET", key}) ==
                    "$" + std::to_string(value.size()) + "\r\n" + value + "\r\n",
                    "GET exact namespace, including binary/extended keys");
            Slice composite(key.data(), key.size(), db);
            KvObj* object = shard.store().find(FlatStore::hash_key(composite), composite);
            require(object && object->key().key_eq(composite), "stored composite identity");
            require(object->key_namespace() == db, "physical namespace in record");
            if (armed) {
                const auto probe = shard.store().read_local_probe(FlatStore::hash_key(composite), composite);
                require(probe.result == FlatStore::ReadLocalProbeResult::Hit && probe.object == object,
                        "foreign read resolves exact namespace without a retry");
            }
            require(object->has_ttl_slot() == false, "no namespace TTL alias");
            require(kvobj_request_size(object) == sizeof(KvObj) + key.size() + value.size() +
                    ((db || key.size() >= 255) ? 4 : 0), "exact DB 0 allocation layout");
        }
    }
    require(run(server, shard, 1, {"HSET", "hash", "field", "one"}) == ":1\r\n", "hash db1");
    require(run(server, shard, 0, {"HSET", "hash", "field", "zero"}) == ":1\r\n", "hash db0");
    require(run(server, shard, 1, {"HGET", "hash", "field"}) == "$3\r\none\r\n", "hash identity");
    require(run(server, shard, 1, {"SADD", "set", "member"}) == ":1\r\n", "set db1");
    require(run(server, shard, 0, {"SISMEMBER", "set", "member"}) == ":0\r\n", "set isolation");
    require(run(server, shard, 1, {"SISMEMBER", "set", "member"}) == ":1\r\n", "member is a value");
    multidb_flush(shard, 1);
    require(run(server, shard, 1, {"GET", "k"}) == "$-1\r\n", "namespace flush");
    require(run(server, shard, 0, {"GET", "k"}) == "$3\r\ndb0\r\n", "flush preserves db0");
    require(server.databases().swap(0, 15), "mapping swap");
    require(run(server, shard, 0, {"GET", "k"}) == "$4\r\ndb15\r\n", "logical mapping");
    require(run(server, shard, 15, {"GET", "k"}) == "$3\r\ndb0\r\n", "inverse mapping");
    // DBSIZE must neither hide nor reap an elapsed physical record. This is the
    // precondition used by edgetime and expwide, including while WATCH is armed.
    shard.store().clear();
    require(run(server, shard, 1, {"SET", "elapsed", "value", "PX", "1"}) == "+OK\r\n",
            "expired size seed");
    shard.set_cached_now_ms(1002);
    require(multidb_size(shard, 1, UINT64_MAX) == 1 && shard.store().size() == 1,
            "DBSIZE retains elapsed physical record");
    DatabaseStatsTable stats{};
    multidb_stats(shard, stats);
    require(stats[1].keys == 1 && stats[1].expires == 1 && shard.store().size() == 1,
            "INFO retains elapsed physical record");
    require(run(server, shard, 1, {"GET", "elapsed"}) == "$-1\r\n" && shard.store().size() == 0,
            "GET alone reaps elapsed record");
    std::printf("PASS multidb namespace identity and layout (read-local %d)\n", armed);
}

struct Request {
    std::vector<std::string> args;
    Op op;
    Request(Server& server, uint8_t db, std::initializer_list<std::string> a) : args(a) {
        for (const auto& arg : args) require(op.push_arg(Slice(arg)), "request argument");
        op.spec = command_lookup(op.cmd_name());
        require(op.spec, "request command");
        multidb_stamp(server, op, db);
    }
    std::string reply() { return {op.reply.data(), op.reply.size()}; }
};
static void records_done(Server& server) {
    for (unsigned s = 0; s < server.nshards(); ++s)
        server.shard(s).store().atomic_shutdown_release_records();
}
static void diagnostic_hook(Server& server) {
    server.set_debug_atomic_fanout_defer(600000);
    ScatterArenaPool pool;
    for (const char* command : {"INFO", "DBSIZE"}) {
        Request request(server, 0, {command});
        ScatterDispatch dispatch;
        require(xshard_prepare(server, request.op, pool, 0, 71, dispatch) == ScatterPrepare::Ready,
                "diagnostic scatter prepared");
        require((dispatch.state->debug_fanout_deadline != 0) == (std::string(command) == "DBSIZE"),
                "INFO cannot delay the pinned-window witness; data census still arms");
        xshard_abandon_unpublished(dispatch.state, pool, 0);
    }
    server.set_debug_atomic_fanout_defer(0);
}
static std::string local(Server& server, uint8_t db, std::initializer_list<std::string> args) {
    Request r(server, db, args);
    std::vector<CommandKeyMetadata> keys;
    command_metadata_collect_keys(r.op, 0, *command_metadata_resolve(r.op, 0), keys);
    require(!keys.empty(), "local command has a key");
    r.op.hash = FlatStore::hash_key(r.op.arg(keys[0].argument));
    r.op.shard = server.router().shard_of(r.op.hash);
    Shard& shard = server.shard(r.op.shard);
    const bool write = r.op.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite);
    if (write) require(multi_plain_write_ready(shard, r.op), "plain WATCH readiness");
    PlainForeignReadScope scope;
    require(xshard_plain_prepare(server, shard, r.op, 71, scope), "plain owner preparation");
    r.op.spec->handler(shard, r.op);
    xshard_plain_finish(shard, scope);
    if (write) multi_plain_write_committed(shard, r.op);
    return r.reply();
}
static std::string scatter(Server& server, uint8_t db,
                           std::initializer_list<std::string> args, bool atomic = true) {
    Client client(-1); client.set_id(71);
    Request r(server, db, args);
    ScatterArenaPool pool;
    ScatterDispatch dispatch;
    const auto prepared = xshard_prepare(server, r.op, pool, 0, client.id(), dispatch, atomic);
    if (prepared == ScatterPrepare::Error) return r.reply();
    require(prepared == ScatterPrepare::Ready, "scatter owner preparation");
    ScatterState& state = *dispatch.state;
    state.now_cut_ms = now_realtime_ms();
    bool final = false;
    for (unsigned pass = 0; !final && pass < 1000; ++pass) {
        const unsigned count = state.nsub;
        std::vector<bool> completed(count, false);
        bool advanced = false;
        for (unsigned retry = 0; !final && !advanced && retry < 1000; ++retry) {
            bool parked[kMaxThreads]{};
            for (unsigned i = 0; i < count && !final && !advanced; ++i) {
                if (completed[i]) continue;
                const int s = state.groups[i].shard;
                const auto owner = server.worker_of_shard(s);
                if (parked[owner]) continue;
                auto result = xshard_execute(Task{&client, 0, s, &state}, server.shard(s),
                    r.op, owner);
                if (result == ScatterTaskResult::Retry) { parked[owner] = true; continue; }
                if (result == ScatterTaskResult::Defer) continue;
                completed[i] = true;
                auto finish = xshard_multi_child_complete(state, r.op, server.worker_of_shard(s));
                final = finish == MultiChildFinish::Final;
                advanced = finish == MultiChildFinish::PhaseAdvanced;
            }
        }
        require(final || advanced, "scatter phases made bounded progress");
    }
    require(final, "scatter completed");
    if (state.atomic_group && !state.aborted.load()) state.epoch.store(server.atomic_commit());
    assemble_final(client, r.op, state, nullptr, nullptr, nullptr);
    records_done(server);
    xshard_destroy(&state, pool, 0);
    pool.reap_deferred();
    return r.reply();
}
static std::string transaction(Server& server, Client& client,
                               std::initializer_list<std::string> args) {
    Request r(server, client.session().db_index, args);
    MultiExecState* state = nullptr;
    auto action = multi_handle_io(server, client, r.op, 0, state);
    const bool boundary = action == MultiIoAction::Backpressure && server.database_boundary_active();
    const auto before_epoch = server.databases().capture().epoch;
    if (boundary) {
        // This driver has no outstanding IO/owner work. The dedicated boundary
        // unit exercises both real control tails and delayed old-epoch pipelines.
        server.flip_set_stage(FlipStage::DatabaseRun);
        action = multi_handle_io(server, client, r.op, 0, state);
    }
    if (action == MultiIoAction::LocalDone) return r.reply();
    require(action == MultiIoAction::Dispatch && state, "transaction preparation");
    state->now_cut_ms = now_realtime_ms();
    for (auto& command : state->commands)
        if (command->scatter) command->scatter->now_cut_ms = state->now_cut_ms;
    initialize_multi_owner_record_refs(*state);
    multi_dispatch_started(client, state);
    Op* carrier = client.rob().acquire();
    require(carrier, "transaction ROB carrier");
    carrier->spec = r.op.spec;
    std::vector<bool> done(state->shards.size(), false);
    unsigned remaining = done.size();
    for (unsigned pass = 0; remaining && pass < 1000; ++pass) {
        for (unsigned i = 0; i < done.size(); ++i) {
            if (done[i]) continue;
            const int s = state->shards[i];
            auto result = multi_execute_task(server, multi_make_task(&client, 0, s, state),
                server.shard(s), server.worker_of_shard(s), 0, nullptr);
            require(server.databases().capture().epoch == before_epoch || state->epoch.load() != 0,
                    "map publication shares the MVCC decision");
            if (result != MultiTaskResult::Retry) { done[i] = true; --remaining; }
        }
    }
    require(!remaining, "transaction phases made bounded progress");
    r.op.attach_multi_state(state);
    client.atomic_group_started();
    records_done(server);
    command_set_local_context(&client, &server.thread(0));
    std::vector<MultiExecState*> deferred;
    multi_retire(client, r.op, deferred);
    command_set_local_context(nullptr, nullptr);
    require(deferred.empty(), "transaction record retirement");
    if (boundary) server.database_boundary_end(client, client.rob().dispatch_id());
    return r.reply();
}

static void persistence(Server& server) {
    records_done(server);
    // Distinct types, a binary key, and a deadline must survive the complete
    // nonidentity mapping left by standalone and transactional swaps above.
    require(local(server, 3, {"HSET", "persist-hash", "field", "value"}) == ":1\r\n", "persist hash");
    require(local(server, 4, {"RPUSH", "persist-list", "a", "b"}) == ":2\r\n", "persist list");
    require(local(server, 5, {"SADD", "persist-set", "a", "b"}) == ":2\r\n", "persist set");
    require(local(server, 6, {"ZADD", "persist-zset", "1", "a", "2", "b"}) == ":2\r\n", "persist zset");
    require(local(server, 15, {"SET", std::string("binary\0key", 10), "ttl", "PX", "600000"}) ==
            "+OK\r\n", "persist binary key and TTL");
    const auto dataset = [&] {
        std::vector<std::string> rows;
        const auto mapping = server.databases().capture();
        for (unsigned sid = 0; sid < server.nshards(); ++sid)
            server.shard(sid).store().for_each([&](KvObj* object) {
                ObjectImage image;
                require(serialize_object(object, image), "serialize complete dataset");
                const Slice key = object->key();
                uint8_t header[24]{};
                unsigned logical = 0;
                while (mapping[logical] != key.ns) ++logical;
                header[0] = logical;
                header[1] = uint8_t(image.type); header[2] = image.encoding;
                snapshot_put_u32(header + 4, key.n);
                snapshot_put_u32(header + 8, image.entries);
                snapshot_put_u64(header + 16, image.expire_at_ms);
                std::string row(reinterpret_cast<char*>(header), sizeof(header));
                row.append(key.p, key.n);
                row.append(reinterpret_cast<const char*>(image.payload.data()), image.payload.size());
                rows.push_back(std::move(row));
            });
        std::sort(rows.begin(), rows.end());
        return rows;
    };
    const auto expected = dataset();
    SnapshotLoadPlan snapshot;
    snapshot.shard_count = server.nshards();
    snapshot.sections.resize(server.nshards());
    snapshot.database_map = server.databases().capture();
    const auto cut = now_realtime_ms();
    for (unsigned sid = 0; sid < server.nshards(); ++sid) {
        auto& store = server.shard(sid).store();
        FlatStore::SnapshotWriteResult prepared = FlatStore::SnapshotWriteResult::Pending;
        for (unsigned pass = 0; prepared == FlatStore::SnapshotWriteResult::Pending && pass < 10000; ++pass)
            prepared = store.snapshot_prepare(1, cut);
        require(prepared == FlatStore::SnapshotWriteResult::Ready && store.snapshot_mark(sid, cut),
                "snapshot namespace capture prepared");
        for (unsigned pass = 0; store.snapshot_active() && pass < 10000; ++pass) {
            store.snapshot_progress(65536, 65536);
            if (auto chunk = store.snapshot_take_chunk()) {
                snapshot.sections[sid].insert(snapshot.sections[sid].end(),
                    chunk->bytes.begin(), chunk->bytes.end());
                store.snapshot_handoff_complete();
            }
        }
        require(!store.snapshot_active() && !store.snapshot_failed(), "snapshot capture completed");
    }
    AofReplayPlan aof;
    aof.sections.resize(server.nshards());
    unsigned namespaces = 0;
    // Feed the real AOF loader matching native records. The gate separately exercises
    // AofProducer, the on-disk frames/checksums, and both file recovery paths end to end.
    for (unsigned sid = 0; sid < server.nshards(); ++sid) {
        const auto& input = snapshot.sections[sid];
        auto& output = aof.sections[sid];
        for (size_t at = 0; at < input.size();) {
            const uint8_t* record = input.data() + at;
            require(snapshot_get_u32(record) == 0x44434552, "native snapshot record tag");
            const auto key_len = snapshot_get_u32(record + 8);
            const auto size = key_len + snapshot_get_u64(record + 16);
            require(at + 32 + size <= input.size(), "snapshot record bounds");
            if (record[6]) ++namespaces;
            uint8_t header[40]{};
            snapshot_put_u32(header, 0x43524f41);
            header[4] = static_cast<uint8_t>(AofRecordKind::GroupPut);
            header[5] = record[4]; header[6] = record[5]; header[7] = 1;
            snapshot_put_u32(header + 8, key_len);
            snapshot_put_u32(header + 12, 40u | (uint32_t(record[6]) << 16));
            std::memcpy(header + 16, record + 16, 16);
            snapshot_put_u64(header + 32, 44);
            output.insert(output.end(), header, header + 40);
            output.insert(output.end(), record + 32, record + 32 + size);
            at += 32 + size;
        }
    }
    require(namespaces > 0, "snapshot actually serialized nonzero namespaces");
    uint8_t mapping_header[40]{};
    snapshot_put_u32(mapping_header, 0x43524f41);
    mapping_header[7] = 1;
    snapshot_put_u32(mapping_header + 12, 40);
    snapshot_put_u64(mapping_header + 16, 256);
    snapshot_put_u64(mapping_header + 24, uint64_t(-1));
    const auto append_map = [&](const DatabaseMap::Map& map, uint64_t group) {
        mapping_header[4] = static_cast<uint8_t>(group ? AofRecordKind::GroupDatabaseMap : AofRecordKind::DatabaseMap);
        snapshot_put_u64(mapping_header + 32, group);
        aof.sections[0].insert(aof.sections[0].end(), mapping_header, mapping_header + 40);
        aof.sections[0].insert(aof.sections[0].end(), map.begin(), map.end());
    };
    DatabaseMap identity;
    append_map(identity.capture(), 0);
    auto aborted_map = snapshot.database_map;
    std::swap(aborted_map[0], aborted_map[15]);
    append_map(snapshot.database_map, 44);
    append_map(aborted_map, 43);  // last on disk, but no commit marker
    std::string error;
    for (unsigned sid = 0; sid < server.nshards(); ++sid) server.shard(sid).store().clear();
    for (unsigned sid = 0; sid < server.nshards(); ++sid)
        require(snapshot_load_shard(snapshot, server, server.shard(sid), error), "snapshot namespace load");
    require(local(server, 0, {"GET", "k"}) == "$3\r\none\r\n", "snapshot db0 mapped value");
    require(local(server, 2, {"GET", "k"}) == "$4\r\nzero\r\n", "snapshot db2 value");
    require(dataset() == expected, "snapshot complete logical dataset, types, binary keys and TTL");
    for (unsigned sid = 0; sid < server.nshards(); ++sid) server.shard(sid).store().clear();
    require(server.databases().swap(0, 1), "disturb mapping before AOF restore");
    for (unsigned sid = 0; sid < server.nshards(); ++sid)
        require(aof_load_shard(aof, server, server.shard(sid), error), "uncommitted AOF load");
    require(dataset().empty() && server.databases().capture() == identity.capture(),
            "missing commit marker hides both data and map");
    aof.committed_groups.insert(44);
    for (unsigned sid = 0; sid < server.nshards(); ++sid)
        require(aof_load_shard(aof, server, server.shard(sid), error), "AOF namespace load");
    require(local(server, 0, {"GET", "k"}) == "$3\r\none\r\n", "AOF restores mapping");
    require(local(server, 2, {"GET", "k"}) == "$4\r\nzero\r\n", "AOF db2 value");
    require(dataset() == expected, "AOF complete dataset and committed map; aborted later map ignored");
    std::puts("PASS multidb native snapshot records and AOF namespace/map replay");
}
static void owners() {
    Config cfg; cfg.databases = 16;
    cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
    cfg.key_lb = cfg.client_lb = 0; cfg.flip_auto = 0;
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "16 shards / 6 IO / 2 owners");
    command_bind_server(&server);
    diagnostic_hook(server);
    std::string error;
    require(acl_initialize(server, cfg, error), "ACL initialize");
    for (unsigned s = 0; s < server.nshards(); ++s)
        server.shard(s).set_cached_now_ms(now_realtime_ms(), 0);
    Client client(-1); client.set_id(71);
    require(local(server, 0, {"SET", "k", "zero"}) == "+OK\r\n", "initial db0");
    require(local(server, 1, {"SET", "k", "one"}) == "+OK\r\n", "initial db1");
    Request before(server, 0, {"GET", "k"});
    Request select(server, 0, {"SELECT", "1"});
    multidb_select(&server, &client, select.op);
    require(client.session().db_index == 1 && before.op.arg(1).ns == 0,
            "SELECT preserves earlier parsed identity");
    require(transaction(server, client, {"MULTI"}) == "+OK\r\n", "MULTI");
    require(transaction(server, client, {"GET", "k"}) == "+QUEUED\r\n", "queued old db");
    require(transaction(server, client, {"SELECT", "0"}) == "+QUEUED\r\n", "queued SELECT");
    require(client.session().db_index == 1, "SELECT does not execute at queue time");
    require(transaction(server, client, {"GET", "k"}) == "+QUEUED\r\n", "queued new db");
    require(transaction(server, client, {"EXEC"}) ==
            "*3\r\n$3\r\none\r\n+OK\r\n$4\r\nzero\r\n", "EXEC namespace sequence");
    require(client.session().db_index == 0, "SELECT commits connection DB at EXEC");
    require(local(server, 1, {"EVAL", "return redis.call('GET',KEYS[1])", "1", "k"}) ==
            "$3\r\none\r\n", "script bridge preserves namespace");
    require(scatter(server, 0, {"MOVE", "k", "1"}) == ":0\r\n", "MOVE NX conflict");
    require(scatter(server, 0, {"MOVE", "absent", "2"}) == ":0\r\n", "MOVE absent source");
    require(scatter(server, 0, {"MOVE", "absent", "2147483648"}) ==
            "-ERR value is out of range, value must between -2147483648 and 2147483647\r\n",
            "MOVE validates destination integer width before lookup");
    require(scatter(server, 0, {"MOVE", "k", "2"}) == ":1\r\n", "MOVE namespace transfer");
    require(local(server, 0, {"GET", "k"}) == "$-1\r\n", "MOVE removed source");
    require(local(server, 2, {"GET", "k"}) == "$4\r\nzero\r\n", "MOVE destination value");
    require(scatter(server, 2, {"COPY", "k", "k", "DB", "0"}) == ":1\r\n",
            "COPY same bytes across databases");
    require(scatter(server, 1, {"SWAPDB", "0", "1"}) == "+OK\r\n", "all-owner SWAPDB");
    require(local(server, 0, {"GET", "k"}) == "$3\r\none\r\n", "SWAPDB first mapping");
    require(local(server, 1, {"GET", "k"}) == "$4\r\nzero\r\n", "SWAPDB second mapping");
    require(transaction(server, client, {"WATCH", "k"}) == "+OK\r\n", "WATCH logical DB");
    require(local(server, 1, {"SET", "k", "elsewhere"}) == "+OK\r\n", "other DB writer");
    require(transaction(server, client, {"MULTI"}) == "+OK\r\n", "watched MULTI");
    require(transaction(server, client, {"GET", "k"}) == "+QUEUED\r\n", "watched GET");
    require(transaction(server, client, {"EXEC"}) == "*1\r\n$3\r\none\r\n",
            "other database cannot dirty WATCH");
    require(transaction(server, client, {"WATCH", "k"}) == "+OK\r\n", "WATCH before swaps");
    require(scatter(server, 0, {"SWAPDB", "0", "1"}) == "+OK\r\n", "swap forward");
    require(scatter(server, 0, {"SWAPDB", "0", "1"}) == "+OK\r\n", "swap back");
    require(transaction(server, client, {"MULTI"}) == "+OK\r\n", "swapped MULTI");
    require(transaction(server, client, {"GET", "k"}) == "+QUEUED\r\n", "swapped GET");
    require(transaction(server, client, {"EXEC"}) == "*-1\r\n", "WATCH sees swap-back generation");
    require(transaction(server, client, {"WATCH", "never-created"}) == "+OK\r\n", "WATCH absent");
    require(scatter(server, 0, {"SWAPDB", "0", "1"}) == "+OK\r\n", "absent WATCH swap");
    require(transaction(server, client, {"MULTI"}) == "+OK\r\n", "absent WATCH MULTI");
    require(transaction(server, client, {"GET", "never-created"}) == "+QUEUED\r\n", "absent WATCH GET");
    require(transaction(server, client, {"EXEC"}) == "*1\r\n$-1\r\n",
            "absent in both namespaces preserves WATCH");
    require(transaction(server, client, {"WATCH", "never-created"}) == "+OK\r\n", "WATCH alias before swap");
    require(scatter(server, 0, {"SWAPDB", "0", "1"}) == "+OK\r\n", "WATCH alias swap back");
    require(local(server, 1, {"SET", "never-created", "other"}) == "+OK\r\n", "inactive WATCH alias write");
    require(transaction(server, client, {"MULTI"}) == "+OK\r\n", "inactive WATCH alias MULTI");
    require(transaction(server, client, {"GET", "never-created"}) == "+QUEUED\r\n", "inactive WATCH alias GET");
    require(transaction(server, client, {"EXEC"}) == "*1\r\n$-1\r\n",
            "writes in another logical DB do not dirty aliases");
    require(transaction(server, client, {"WATCH", "later-created"}) == "+OK\r\n", "WATCH future active alias");
    require(scatter(server, 0, {"SWAPDB", "0", "1"}) == "+OK\r\n", "activate different WATCH alias");
    require(local(server, 0, {"SET", "later-created", "ours"}) == "+OK\r\n", "active WATCH alias write");
    require(transaction(server, client, {"MULTI"}) == "+OK\r\n", "active WATCH alias MULTI");
    require(transaction(server, client, {"GET", "later-created"}) == "+QUEUED\r\n", "active WATCH alias GET");
    require(transaction(server, client, {"EXEC"}) == "*-1\r\n", "WATCH follows logical DB after absent swap");
    require(local(server, 0, {"DEL", "later-created"}) == ":1\r\n", "alias write cleanup");
    require(scatter(server, 0, {"SWAPDB", "0", "1"}) == "+OK\r\n", "restore mapping after alias checks");
    require(scatter(server, 0, {"SWAPDB", "bad", "0"}) == "-ERR invalid first DB index\r\n",
            "SWAPDB first index grammar");
    require(scatter(server, 0, {"SWAPDB", "0", "bad"}) == "-ERR invalid second DB index\r\n",
            "SWAPDB second index grammar");
    require(scatter(server, 0, {"SWAPDB", "0", "16"}) == "-ERR DB index is out of range\r\n",
            "SWAPDB configured range");
    require(scatter(server, 1, {"FLUSHDB"}) == "+OK\r\n", "scoped FLUSHDB");
    require(local(server, 0, {"GET", "k"}) == "$3\r\none\r\n", "FLUSHDB isolation");
    require(scatter(server, 1, {"DBSIZE"}) == ":0\r\n", "scoped empty DBSIZE");
    require(scatter(server, 0, {"DBSIZE"}) == ":1\r\n", "scoped DBSIZE");
    require(scatter(server, 0, {"KEYS", "*"}) == "*1\r\n$1\r\nk\r\n", "scoped KEYS");
    require(scatter(server, 0, {"RANDOMKEY"}) == "$1\r\nk\r\n", "scoped RANDOMKEY");
    require(scatter(server, 1, {"RANDOMKEY"}) == "$-1\r\n", "empty RANDOMKEY");
    const auto keyspace = scatter(server, 0, {"INFO", "keyspace"});
    require(keyspace.find("db0:keys=1,expires=0,avg_ttl=0\r\n") != std::string::npos &&
            keyspace.find("db2:keys=1,expires=0,avg_ttl=0\r\n") != std::string::npos &&
            keyspace.find("db1:") == std::string::npos, "INFO uses logical nonempty DBs");
    for (bool atomic : {false, true}) {
        server.set_atomic_enabled(atomic);
        for (bool same_shard : {false, true}) {
            std::string key;
            for (unsigned i = 0; i < 100000; ++i) {
                key = "move-owner:" + std::to_string(i);
                const auto a = server.router().shard_of(FlatStore::hash_key(Slice(key.data(), key.size(), 7)));
                const auto b = server.router().shard_of(FlatStore::hash_key(Slice(key.data(), key.size(), 8)));
                if ((a == b) == same_shard) break;
                if (i == 99999) require(false, "MOVE geometry never armed");
            }
            require(local(server, 7, {"SET", key, "moved", "PX", "600000"}) == "+OK\r\n", "MOVE source");
            require(scatter(server, 7, {"MOVE", key, "8"}, atomic) == ":1\r\n", "MOVE owner geometry");
            require(local(server, 8, {"GET", key}) == "$5\r\nmoved\r\n", "MOVE value across owners");
            const auto ttl = local(server, 8, {"PTTL", key});
            require(ttl.front() == ':' && std::stoll(ttl.substr(1)) > 0 &&
                    std::stoll(ttl.substr(1)) <= 600000, "MOVE preserves TTL");
            require(local(server, 8, {"DEL", key}) == ":1\r\n", "MOVE cleanup");
        }
    }
    server.set_atomic_enabled(true);
    Client watcher(-1), mover(-1);
    watcher.set_id(81); mover.set_id(82);
    watcher.session().db_index = 10; mover.session().db_index = 9;
    require(local(server, 9, {"SET", "watched-move", "value"}) == "+OK\r\n", "watched MOVE source");
    require(transaction(server, watcher, {"WATCH", "watched-move"}) == "+OK\r\n", "WATCH destination");
    require(transaction(server, mover, {"MULTI"}) == "+OK\r\n", "MOVE MULTI");
    require(transaction(server, mover, {"MOVE", "watched-move", "10"}) == "+QUEUED\r\n", "MOVE queued");
    require(transaction(server, mover, {"EXEC"}) == "*1\r\n:1\r\n", "MOVE EXEC");
    require(transaction(server, watcher, {"MULTI"}) == "+OK\r\n", "destination WATCH MULTI");
    require(transaction(server, watcher, {"GET", "watched-move"}) == "+QUEUED\r\n", "destination WATCH GET");
    require(transaction(server, watcher, {"EXEC"}) == "*-1\r\n", "MOVE dirties destination WATCH");
    Client swapping(-1); swapping.set_id(83); swapping.session().db_index = 11;
    require(local(server, 11, {"SET", "tx-swap", "old"}) == "+OK\r\n", "transaction swap source");
    require(local(server, 12, {"SET", "tx-swap", "other"}) == "+OK\r\n", "transaction swap peer");
    require(transaction(server, swapping, {"MULTI"}) == "+OK\r\n", "swap MULTI");
    require(transaction(server, swapping, {"SET", "tx-swap", "before"}) == "+QUEUED\r\n", "pre-swap SET");
    require(transaction(server, swapping, {"SWAPDB", "11", "12"}) == "+QUEUED\r\n", "queued SWAPDB");
    require(transaction(server, swapping, {"GET", "tx-swap"}) == "+QUEUED\r\n", "read new map");
    require(transaction(server, swapping, {"SELECT", "12"}) == "+QUEUED\r\n", "queued SELECT after swap");
    require(transaction(server, swapping, {"GET", "tx-swap"}) == "+QUEUED\r\n", "read own pre-swap write");
    require(transaction(server, swapping, {"SET", "tx-swap", "after"}) == "+QUEUED\r\n", "post-swap SET");
    require(transaction(server, swapping, {"MOVE", "tx-swap", "13"}) == "+QUEUED\r\n", "MOVE after swap");
    require(transaction(server, swapping, {"SWAPDB", "12", "13"}) == "+QUEUED\r\n", "second queued swap");
    require(transaction(server, swapping, {"GET", "tx-swap"}) == "+QUEUED\r\n", "read moved value");
    require(transaction(server, swapping, {"EXEC"}) ==
            "*9\r\n+OK\r\n+OK\r\n$5\r\nother\r\n+OK\r\n$6\r\nbefore\r\n+OK\r\n:1\r\n+OK\r\n$5\r\nafter\r\n",
            "SWAPDB/SELECT/MOVE share one untorn EXEC array");
    require(swapping.session().db_index == 12 && local(server, 12, {"GET", "tx-swap"}) == "$5\r\nafter\r\n",
            "transaction publishes final mapping and selected DB");
    const auto committed_epoch = server.databases().capture().epoch;
    require(transaction(server, swapping, {"WATCH", "tx-swap"}) == "+OK\r\n", "WATCH before aborted swap");
    require(local(server, 12, {"SET", "tx-swap", "changed"}) == "+OK\r\n", "dirty transaction watch");
    require(transaction(server, swapping, {"MULTI"}) == "+OK\r\n", "aborted swap MULTI");
    require(transaction(server, swapping, {"SWAPDB", "12", "13"}) == "+QUEUED\r\n", "aborted queued swap");
    require(transaction(server, swapping, {"EXEC"}) == "*-1\r\n", "WATCH abort hides map");
    require(server.databases().capture().epoch == committed_epoch, "aborted swap publishes no epoch");
    Client transient_watcher(-1), transient_writer(-1);
    transient_watcher.set_id(91); transient_watcher.session().db_index = 14;
    transient_writer.set_id(92); transient_writer.session().db_index = 13;
    require(local(server, 13, {"SET", "transient-swap", "value"}) == "+OK\r\n", "transient source");
    require(transaction(server, transient_watcher, {"WATCH", "transient-swap"}) == "+OK\r\n", "WATCH transient destination");
    require(transaction(server, transient_writer, {"MULTI"}) == "+OK\r\n", "transient MULTI");
    require(transaction(server, transient_writer, {"SWAPDB", "13", "14"}) == "+QUEUED\r\n", "transient swap in");
    require(transaction(server, transient_writer, {"SELECT", "14"}) == "+QUEUED\r\n", "transient SELECT");
    require(transaction(server, transient_writer, {"DEL", "transient-swap"}) == "+QUEUED\r\n", "transient removal");
    require(transaction(server, transient_writer, {"SWAPDB", "13", "14"}) == "+QUEUED\r\n", "transient swap back");
    require(transaction(server, transient_writer, {"EXEC"}) == "*4\r\n+OK\r\n+OK\r\n:1\r\n+OK\r\n", "transient EXEC");
    require(transaction(server, transient_watcher, {"MULTI"}) == "+OK\r\n", "transient watcher MULTI");
    require(transaction(server, transient_watcher, {"GET", "transient-swap"}) == "+QUEUED\r\n", "transient watcher GET");
    require(transaction(server, transient_watcher, {"EXEC"}) == "*-1\r\n", "WATCH remembers a key swapped in, deleted, and swapped back");
    // A write must dirty the database it named THEN, even if both namespaces
    // are empty when the final swap executes. The other absent WATCH stays clean.
    transient_writer.session().db_index = 13;
    Client original_watcher(-1); original_watcher.set_id(93); original_watcher.session().db_index = 13;
    require(transaction(server, original_watcher, {"WATCH", "vanished-before-swap"}) == "+OK\r\n", "WATCH original logical DB");
    require(transaction(server, transient_watcher, {"WATCH", "vanished-before-swap"}) == "+OK\r\n", "WATCH untouched destination");
    require(transaction(server, transient_writer, {"MULTI"}) == "+OK\r\n", "vanishing MULTI");
    require(transaction(server, transient_writer, {"SET", "vanished-before-swap", "v"}) == "+QUEUED\r\n", "vanishing SET");
    require(transaction(server, transient_writer, {"DEL", "vanished-before-swap"}) == "+QUEUED\r\n", "vanishing DEL");
    require(transaction(server, transient_writer, {"SWAPDB", "13", "14"}) == "+QUEUED\r\n", "vanishing SWAP");
    require(transaction(server, transient_writer, {"EXEC"}) == "*3\r\n+OK\r\n:1\r\n+OK\r\n", "vanishing EXEC");
    for (Client* watching : {&original_watcher, &transient_watcher}) {
        require(transaction(server, *watching, {"MULTI"}) == "+OK\r\n", "vanishing watcher MULTI");
        require(transaction(server, *watching, {"GET", "vanished-before-swap"}) == "+QUEUED\r\n", "vanishing watcher GET");
        require(transaction(server, *watching, {"EXEC"}) ==
            (watching == &original_watcher ? "*-1\r\n" : "*1\r\n$-1\r\n"), "WATCH uses write-time logical identity");
    }
    persistence(server);
    records_done(server);
    command_bind_server(nullptr);
    std::puts("PASS multidb owner phases, SELECT, MOVE, COPY, SWAPDB and WATCH");
}
void multidb_db0_unit();
int main() {
    multidb_db0_unit();
    require(command_registry_init(false), "registry initialization");
    require(Config{}.databases == 1, "single-database boot default");
    for (const char* count : {"1", "16", "256"}) {
        Config cfg; ConfigParseState state;
        require(parse_config_args({"--databases", count}, cfg, state, 8, "unit") == kConfigParsed &&
                cfg.databases == std::stoul(count), "database count parser");
    }
    layout_and_store(false);
    layout_and_store(true);
    prebuilt_ttl(false);
    prebuilt_ttl(true);
    owners();
}
