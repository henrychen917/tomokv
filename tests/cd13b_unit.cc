// RESP-through-pipes fixture: production parser, handlers and both scatter owner phases.
// No listener, socket, IO ring, worker thread, timer loop or benchmark is started.
// Include the selected arm's xshard source to drive its private phase boundary directly.
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#include "src/cmd/xshard.cc"
#include <iostream>

using namespace tomo;
// ObjectImage's new policy flag consumes padding; the image and every old field keep their
// PRE layout. These assertions compile against PRE and POST, in both database namespaces.
static_assert(sizeof(ObjectImage) == 48);
static_assert(offsetof(ObjectImage, entries) == 8);
static_assert(offsetof(ObjectImage, expire_at_ms) == 16);
static_assert(offsetof(ObjectImage, payload) == 24);
namespace {
void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL cd13b: %s\n", why); std::exit(1); }
}
struct Fixture {
    Server server;
    Client client{-1};
    ScatterArenaPool pool;
    std::string placement;
    bool resp3, notify, late;
    Fixture(bool fused, int atomic, bool protocol, bool notifications, bool late_copy)
        : resp3(protocol), notify(notifications), late(late_copy) {
        Config cfg;
        cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
        cfg.thread_mode = fused ? ThreadMode::Fused : ThreadMode::Split;
        cfg.atomic = atomic; cfg.databases = kSingleDatabase ? 1 : 16;
        cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
        cfg.maxmemory = 1ull << 30; cfg.maxmemory_policy = MaxmemoryPolicy::AllKeysLfu;
        cfg.save.clear(); cfg.enable_debug_command = DebugCommandMode::Yes;
        cfg.notify_events = notifications ? (NOTIFY_KEYSPACE | NOTIFY_ZSET | NOTIFY_GENERIC) : 0;
        cpu_set_t allowed;
        require(sched_getaffinity(0, sizeof(allowed), &allowed) == 0, "read CPU affinity");
        unsigned count = 0;
        for (int cpu = 0; cpu < CPU_SETSIZE && count < 8; ++cpu) {
            if (!CPU_ISSET(cpu, &allowed)) continue;
            if (count) placement += ',';
            placement += fused || count < 6 ? "ifid@" : "ex@";
            placement += std::to_string(cpu); ++count;
        }
        require(count == 8, "eight CPUs required");
        cfg.place = placement.c_str();
        require(command_registry_init(fused), "command registry");
        require(server.prepare_boot(cfg) && server.init(cfg), "serverless owner geometry");
        command_bind_server(&server);
        client.set_id(777);
    }
    void release_records() {
        for (uint32_t sid = 0; sid < server.nshards(); ++sid)
            xshard_cleanup_shard_at(server.shard(sid), UINT64_MAX, UINT64_MAX, UINT32_MAX);
    }
    void configure(Shard& shard) {
        const auto snapshot = server.live_config_snapshot(server.worker_of_shard(shard.id()));
        shard.configure_maxmemory(snapshot.maxmemory != 0, snapshot.maxmemory / server.nshards(),
                                  snapshot.policy, snapshot.samples);
    }
    void owner_phase(ScatterState& state, Op& op) {
        for (uint32_t i = 0; i < state.nsub; ++i) {
            const int sid = state.groups[i].shard;
            const auto tid = server.worker_of_shard(sid);
            configure(server.shard(sid));
            server.shard(sid).set_cached_now_ms(now_realtime_ms(), 0);
            require(xshard_execute(Task{&client, 0, sid, &state}, server.shard(sid), op, tid) ==
                    ScatterTaskResult::Complete, "owner phase completed without retries");
            if (state.phase == 2 && state.atomic_apply) complete_owner_record_wave(state, tid);
        }
    }
    void geo_store(Op& op) {
        ScatterDispatch dispatch;
        require(xshard_prepare(server, op, pool, 0, client.id(), dispatch) ==
                ScatterPrepare::Ready, "GEO scatter prepared");
        auto& state = *dispatch.state;
        state.now_cut_ms = now_realtime_ms();
        require(state.two_hop && state.nsub > 0 && state.key_count == 2, "two GEO key records");
        // Hop one reads only the source. The destination is first visited in the apply hop.
        const auto a = state.keys[0].shard, b = state.keys[1].shard;
        require(a != b && server.worker_of_shard(a) != server.worker_of_shard(b),
                "GEO keys must have distinct owner threads");
        owner_phase(state, op);
        require(!finish_phase1(state, op), "GEO coordinator produced second hop");
        const auto& key = state.keys[0];
        auto& destination = server.shard(key.shard);
        if (late) {
            auto* previous = destination.store().find_resident(key.hash, op.arg(key.arg));
            require(previous, "late metadata witness has a destination");
            // Exact owner-side window: change metadata AFTER the coordinator constructed its
            // image. Any copy from the gathered image/coordinator must fail the check below.
            previous->set_eviction_meta(17);
        }
        reset_groups(state);
        build_groups(state, state.hop2, state.hop2_count);
        state.phase = 2;
        initialize_owner_completion(state);
        owner_phase(state, op);
        finish_phase2(state);
        require(!state.aborted.load(), "GEO apply not aborted");
        if (state.atomic_apply) state.epoch.store(server.atomic_commit(), std::memory_order_release);
        assemble_final(client, op, state, nullptr, nullptr, nullptr);
        release_records();
        if (late) {
            auto* installed = destination.store().find_resident(key.hash, op.arg(key.arg));
            require(installed && installed->eviction_meta() == 17,
                    "install must copy current owner metadata after coordinator image creation");
        }
        notify_discard_batch(state.notify.exchange(nullptr));
        xshard_destroy(&state, pool, 0);
        pool.reap_deferred();
    }
    std::string run(const std::string& frame) {
        Op op;
        uint32_t pos = 0;
        const char* error = nullptr;
        require(resp_parse(frame.data(), frame.size(), pos, op, &error) == ParseResult::Ok &&
                pos == frame.size(), "complete production RESP parse");
        op.spec = command_lookup(op.arg(0));
        require(op.spec, "known fixture command");
        if (notify) op.spec = command_notify_variant(op.spec);
        if (resp3) op.mark_resp3();
        if (op.cmd_name().eq_icase("georadius") || op.cmd_name().eq_icase("geosearchstore")) {
            geo_store(op);
        } else if (op.cmd_name().eq_icase("config") && op.arg(1).eq_icase("set")) {
            ScatterDispatch dispatch;
            require(xshard_prepare(server, op, pool, 0, client.id(), dispatch) ==
                    ScatterPrepare::Ready, "CONFIG scatter prepared");
            auto& state = *dispatch.state;
            state.now_cut_ms = now_realtime_ms();
            owner_phase(state, op);
            assemble_final(client, op, state, nullptr, nullptr, nullptr);
            xshard_destroy(&state, pool, 0); pool.reap_deferred();
        } else {
            int16_t first = op.spec->first_key;
            if (op.cmd_name().eq_icase("object")) first = 2;
            if (first > 0) op.hash = FlatStore::hash_key(op.arg(first));
            const auto sid = first > 0 ? server.router().shard_of(op.hash) : 0;
            auto& shard = server.shard(sid);
            configure(shard);
            shard.set_cached_now_ms(now_realtime_ms(), 0);
            op.shard = sid;
            op.spec->handler(shard, op);
        }
        return {op.reply.data(), op.reply.size()};
    }
};
bool read_frame(std::string& frame) {
    std::string line;
    if (!std::getline(std::cin, line)) return false;
    require(line.size() >= 3 && line.front() == '*' && line.back() == '\r', "RESP array");
    frame = line + '\n';
    const auto count = std::stoul(line.substr(1));
    for (size_t i = 0; i < count; ++i) {
        require(bool(std::getline(std::cin, line)) && line.front() == '$' && line.back() == '\r', "RESP bulk");
        frame += line + '\n';
        const auto size = std::stoul(line.substr(1));
        std::string body(size + 2, '\0');
        require(bool(std::cin.read(body.data(), body.size())) && body.substr(size) == "\r\n", "RESP bulk body");
        frame += body;
    }
    return true;
}
}
int main(int argc, char** argv) {
    require(argc == 6, "fused atomic resp3 notify late-copy arguments required");
    Fixture fixture(std::atoi(argv[1]), std::atoi(argv[2]), std::atoi(argv[3]),
                    std::atoi(argv[4]), std::atoi(argv[5]));
    std::string frame;
    while (read_frame(frame)) {
        const auto reply = fixture.run(frame);
        std::cout.write(reply.data(), reply.size()); std::cout.flush();
    }
}
