// D2: deterministic owner turns in the real scatter implementation. No worker,
// listener, injected delay, or mocked collection operation. Compile this same
// fixture against PRE/POST in both namespaces.
#pragma GCC diagnostic ignored "-Wsubobject-linkage"
#include "src/cmd/xshard.cc"
#include <cstdio>
#include <cstdlib>
using namespace tomo;
namespace {
void require(bool yes, const char* why) {
    if (!yes) { std::fprintf(stderr, "FAIL: %s\n", why); std::exit(1); }
}
Slice slice(const std::string& s) { return Slice(s.data(), s.size()); }
struct Request {
    std::vector<std::string> args;
    Op op;
    explicit Request(std::vector<std::string> a) : args(std::move(a)) {
        op.reset();
        for (const auto& s : args) require(op.push_arg(slice(s)), "argument allocation");
        op.spec = command_lookup(op.arg(0));
        require(op.spec != nullptr, "registered command");
    }
    std::string reply() const { return std::string(op.reply.data(), op.reply.size()); }
};
int sid(Server& server, const std::string& key) {
    return server.router().shard_of(FlatStore::hash_key(slice(key)));
}
std::string key_on(Server& server, int target, const char* prefix) {
    for (unsigned i = 0; i < 100000; i++) {
        std::string key = std::string(prefix) + std::to_string(i);
        if (sid(server, key) == target) return key;
    }
    require(false, "find a key on the required shard");
    return {};
}
std::string local(Server& server, std::vector<std::string> args, uint64_t conn = 91,
                  bool local_multi = false) {
    Request r(std::move(args));
    const int shard_id = r.args.size() > 1 ? sid(server, r.args[1]) : 0;
    Shard& shard = server.shard(shard_id);
    shard.set_cached_now_ms(now_realtime_ms(), 0);
    r.op.shard = shard_id;
    r.op.hash = r.args.size() > 1 ? FlatStore::hash_key(r.op.arg(1)) : 0;
    if (local_multi) r.op.mark_local_xshard();
    PlainForeignReadScope scope;
    require(xshard_plain_prepare(server, shard, r.op, conn, scope), "plain preparation");
    r.op.spec->handler(shard, r.op);
    xshard_plain_finish(shard, scope);
    return r.reply();
}

struct Move {
    Server& server;
    Client client{-1};
    Request request;
    ScatterArenaPool pool;
    ScatterState* state;
    uint64_t admission = 0;
    Move(Server& s, std::vector<std::string> args, uint64_t id)
        : server(s), request(std::move(args)) {
        // Keep a registered cut, as a concurrent EXEC does on the default lane.
        require(server.atomic_try_admit(0, admission, true), "activity admission");
        client.set_id(id);
        ScatterDispatch dispatch;
        require(xshard_prepare(server, request.op, pool, 0, id, dispatch) ==
                ScatterPrepare::Ready, "scatter prepared");
        state = dispatch.state;
        state->now_cut_ms = now_realtime_ms();
        require(!state->atomic_group && state->nsub == 2, "atomic-0 two-shard path");
        for (uint32_t i = 0; i < state->nsub; ++i)
            require(turn(state->groups[i].shard) == ScatterTaskResult::Complete, "probe turn");
        require(!finish_phase1(*state, request.op), "probe selected source");
        reset_groups(*state);
        build_groups(*state, state->hop2, state->hop2_count);
        state->phase = 2;
        initialize_owner_completion(*state);
    }
    ScatterTaskResult turn(int shard) {
        return xshard_execute(Task{&client, 0, shard, state}, server.shard(shard),
                              request.op, server.worker_of_shard(shard));
    }
    ~Move() {
        for (unsigned s = 0; s < server.nshards(); ++s)
            server.shard(s).store().atomic_shutdown_release_records();
        xshard_destroy(state, pool, 0);
        pool.reap_deferred();
        server.atomic_retire_group(0, admission);
    }
};
void race(Server& server, std::string verb, bool left, bool to_left, int count) {
    const auto a = key_on(server, 0, "mover-src"), b = key_on(server, 1, "mover-dst");
    require(server.worker_of_shard(0) != server.worker_of_shard(1), "distinct owners");
    local(server, {"DEL", a}); local(server, {"DEL", b});
    const bool pop = verb == "LMPOP" || verb == "ZMPOP";
    const bool set = verb == "SMOVE";
    if (verb == "BLMOVE") verb = "LMOVE";
    if (verb == "BRPOPLPUSH") verb = "RPOPLPUSH";
    std::vector<std::string> seed{set ? "SADD" : verb == "ZMPOP" ? "ZADD" : "RPUSH", a};
    for (int i = 0; i < count; ++i) {
        if (verb == "ZMPOP") seed.push_back(std::to_string(i));
        seed.push_back("v" + std::to_string(i));
    }
    local(server, seed);
    std::vector<std::string> command{verb, a, b};
    if (verb == "LMOVE") command.insert(command.end(), {left ? "LEFT" : "RIGHT", to_left ? "LEFT" : "RIGHT"});
    if (set) command.push_back("v0");
    if (pop) command = {verb, "2", a, b, verb == "ZMPOP" ? (left ? "MIN" : "MAX") : (left ? "LEFT" : "RIGHT"), "COUNT", "3"};
    Move first(server, command, 101), second(server, command, 102);
    // Both phase-one source observations have happened, before either mutation.
    require(first.state->images[0].present && second.state->images[0].present,
            "both contenders reached the same nonempty source");
    std::printf("HIT %s both probes before claims count=%d left=%d to_left=%d\n",
                verb.c_str(), count, left, to_left);
    // A pinned source forces a retained version at the first removal. The
    // second phase must consult the current owner view, not its older cut.
    auto& source = server.shard(0).store();
    const auto hash = FlatStore::hash_key(slice(a));
    require(source.atomic_script_pin(hash, slice(a)), "retain contended source version");
    ScatterTaskResult early = ScatterTaskResult::Defer;
    if (!pop) early = second.turn(1);
    require(first.turn(0) == ScatterTaskResult::Complete, "first source claim");
    require(second.turn(0) == ScatterTaskResult::Complete, "second source claim");
    if (!pop) {
        require(first.turn(1) == ScatterTaskResult::Complete, "first destination");
        if (early == ScatterTaskResult::Defer)
            require(second.turn(1) == ScatterTaskResult::Complete, "deferred destination resumed");
    }
    finish_phase2(*first.state); finish_phase2(*second.state);
    source.atomic_script_unpin(hash, slice(a));
    if (set) {
        require(first.state->final_integer + second.state->final_integer == 1,
                "SMOVE exactly one actual removal and winner");
        require(local(server, {"SMEMBERS", b}) == "*1\r\n$2\r\nv0\r\n", "SMOVE destination conservation");
    } else if (pop) {
        const auto& x = first.state->result->members;
        const auto& y = second.state->result->members;
        std::vector<std::string> got = x; got.insert(got.end(), y.begin(), y.end());
        std::sort(got.begin(), got.end());
        require(got.size() == unsigned(count) && std::adjacent_find(got.begin(), got.end()) == got.end(),
                "pop claims conserve all members without duplicate delivery");
    } else {
        require(early == ScatterTaskResult::Defer, "destination arriving first must defer");
        require(first.state->final_reply == FinalReply::Bulk, "first claimed reply");
        if (count == 1)
            require(second.state->final_reply == FinalReply::Nil, "source miss cannot publish stale guess");
        else {
            require(second.state->final_reply == FinalReply::Bulk, "second claimed reply");
            require(first.state->result->bulk != second.state->result->bulk, "distinct actual claims");
        }
        require(local(server, {"LLEN", b}) == ":" + std::to_string(count) + "\r\n", "list destination conservation");
    }
    require(local(server, {"EXISTS", a}) == ":0\r\n", "source fully consumed");
}
}
int main(int argc, char** argv) {
    require(argc == 3, "mode and family required");
    require(command_registry_init(false), "registry");
    Config cfg;
    cfg.atomic = 0; cfg.shards = 16; cfg.databases = kSingleDatabase ? 1 : 16;
    cfg.even_ifid = 6; cfg.even_ex = 2;
    const bool fused = std::string(argv[1]) == "1s";
    cfg.thread_mode = fused ? ThreadMode::Fused : ThreadMode::Split;
    cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
    cpu_set_t allowed; require(sched_getaffinity(0, sizeof(allowed), &allowed) == 0, "affinity");
    std::string placement;
    unsigned n = 0;
    for (int cpu = 0; cpu < CPU_SETSIZE && n < 8; ++cpu) {
        if (!CPU_ISSET(cpu, &allowed)) continue;
        if (n) placement += ',';
        placement += (fused || n < 6) ? "ifid@" : "ex@";
        placement += std::to_string(cpu); ++n;
    }
    require(n == 8, "eight allowed cores"); cfg.place = placement.c_str();
    Server server;
    require(server.prepare_boot(cfg) && server.init(cfg), "boot geometry");
    command_bind_server(&server);
    std::string error; require(acl_initialize(server, cfg, error), "ACL");
    const std::string verb = argv[2];
    for (bool left : {false, true}) for (bool to_left : {false, true})
        for (int count : {1, 2})
            race(server, verb, left, to_left, verb == "SMOVE" ? 1 :
                 (verb == "LMPOP" || verb == "ZMPOP") ? (count == 1 ? 3 : 6) : count);
    std::puts("PASS moverfix deterministic claims");
}
