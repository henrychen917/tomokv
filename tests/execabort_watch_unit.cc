// Exercise production WATCH/MULTI/EXEC and the ordinary SET reservation guard.
// No sockets, workers, IO rings, loading service, or test hooks. Link the SAME
// witness object with PRE/POST production objects to falsify the fix in isolation.
#include "src/core/server.h"
#include "src/cmd/acl.h"
#include "src/cmd/multi.h"
#include "src/cmd/xshard.h"
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

using namespace tomo;
namespace {
void require(bool yes, const char* why) {
    if (!yes) { std::fprintf(stderr, "FAIL execabort-watch: %s\n", why); std::exit(1); }
}
struct Request {
    std::vector<std::string> args;
    Op op;
    explicit Request(std::vector<std::string> values) : args(std::move(values)) {
        op.reset();
        for (const auto& value : args)
            require(op.push_arg(Slice(value.data(), value.size())), "argument allocation");
        op.spec = command_lookup(op.arg(0));
        require(op.spec, "registered command");
    }
    std::string reply() const { return {op.reply.data(), op.reply.size()}; }
};

struct Fixture {
    std::string placement;
    Server server;
    Client client{-1};
    std::vector<MultiExecState*> deferred;
    uint32_t io = 0;
    explicit Fixture(bool fused, int atomic) {
        Config cfg;
        cfg.shards = 16; cfg.even_ifid = 6; cfg.even_ex = 2;
        cfg.thread_mode = fused ? ThreadMode::Fused : ThreadMode::Split;
        cfg.atomic = atomic; cfg.databases = kSingleDatabase ? 1 : 2;
        cfg.key_lb = cfg.client_lb = cfg.flip_auto = 0;
        cfg.save.clear();
        cpu_set_t allowed;
        require(sched_getaffinity(0, sizeof(allowed), &allowed) == 0, "read permitted cores");
        unsigned selected = 0;
        for (int cpu = 0; cpu < CPU_SETSIZE && selected < 8; ++cpu) {
            if (!CPU_ISSET(cpu, &allowed)) continue;
            if (selected) placement += ',';
            placement += (fused || selected < 6) ? "ifid@" : "ex@";
            placement += std::to_string(cpu);
            ++selected;
        }
        require(selected == 8, "eight permitted cores");
        cfg.place = placement.c_str();
        require(server.prepare_boot(cfg) && server.init(cfg), "16-shard, eight-worker geometry");
        io = server.placement().ifid_threads().front();
        client.set_id(91);
        require(client.rob().acquire(), "transaction carrier");
        command_bind_server(&server);
        std::string error;
        require(acl_initialize(server, cfg, error), "default ACL");
    }
    std::string multi(std::vector<std::string> args) {
        Request request(std::move(args));
        MultiExecState* state = nullptr;
        const auto action = multi_handle_io(server, client, request.op, io, state);
        if (action == MultiIoAction::LocalDone) return request.reply();
        require(action == MultiIoAction::Dispatch && state, "transaction dispatch");
        // All dispatched commands here are WATCH or an empty/queue-error EXEC;
        // none can install records, so no owner record sentinel is needed.
        request.op.attach_multi_state(state);
        client.rob().at(0).spec = request.op.spec;
        client.atomic_group_started();
        multi_dispatch_started(client, state);
        std::vector<int32_t> remaining;
        for (uint32_t i = 0; i < multi_dispatch_count(state); ++i)
            remaining.push_back(multi_dispatch_shard(state, i));
        for (unsigned pass = 0; !remaining.empty() && pass < 1024; ++pass) {
            for (size_t i = 0; i < remaining.size();) {
                const int32_t sid = remaining[i];
                const auto result = multi_execute_task(server,
                    multi_make_task(&client, 0, sid, state), server.shard(sid),
                    server.worker_of_shard(sid), 0, nullptr);
                if (result == MultiTaskResult::Retry) ++i;
                else remaining.erase(remaining.begin() + i);
            }
        }
        require(remaining.empty(), "EXEC must reply within the owner-phase bound");
        multi_retire(client, request.op, deferred);
        return request.reply();
    }
    unsigned watches() {
        unsigned count = 0;
        for (unsigned s = 0; s < server.nshards(); ++s) count += server.shard(s).has_watches();
        return count;
    }
    uint64_t waits() {
        uint64_t count = 0;
        for (unsigned s = 0; s < server.nshards(); ++s)
            count += server.shard(s).stats().watch_reservation_waits;
        return count;
    }
    bool set(unsigned& denied) {
        Request request({"SET", "execabort:watched", "after"});
        request.op.hash = FlatStore::hash_key(request.op.arg(1));
        request.op.shard = server.router().shard_of(request.op.hash);
        auto& shard = server.shard(request.op.shard);
        require(shard.store().find(request.op.hash, request.op.arg(1)) == nullptr,
                "EXECABORT did not apply the queued SET");
        for (denied = 0; denied < 1024; ++denied) {
            // This is the executor's production dispatch guard. Never bypass it
            // to make the PRE arm progress, or weaken a blocked write to success.
            if (!multi_plain_write_ready(shard, request.op)) continue;
            PlainForeignReadScope scope;
            require(xshard_plain_prepare(server, shard, request.op, client.id(), scope),
                    "ordinary SET preparation");
            request.op.spec->handler(shard, request.op);
            xshard_plain_finish(shard, scope);
            require(request.reply() == "+OK\r\n", "later SET replies OK");
            return true;
        }
        return false;
    }
};
}

int main(int argc, char** argv) {
    require(argc >= 2 && argc <= 4,
            "usage: execabort-watch-unit 1s|2s [armed|no-watch|no-error|no-arm] [0|1]");
    const std::string mode = argv[1], selection = argc >= 3 ? argv[2] : "armed";
    const std::string control = selection == "armed" ? "" : selection;
    const std::string atomic_selection = argc == 4 ? argv[3] : "both";
    require(mode == "1s" || mode == "2s", "known mode");
    require(control.empty() || control == "no-watch" || control == "no-error" || control == "no-arm",
            "known control");
    require(atomic_selection == "both" || atomic_selection == "0" || atomic_selection == "1",
            "known atomic arm");
    require(command_registry_init(false), "command registry");
    for (int atomic : {0, 1}) {
        if (atomic_selection != "both" && atomic_selection != std::to_string(atomic)) continue;
        Fixture fixture(mode == "1s", atomic);
        const bool watched = control != "no-watch" && control != "no-arm";
        if (watched)
            require(fixture.multi({"WATCH", "execabort:watched"}) == "+OK\r\n", "WATCH reply");
        if (control != "no-watch")
            require(fixture.watches() > 0, "WATCH window never armed");
        require(fixture.multi({"MULTI"}) == "+OK\r\n", "MULTI reply");
        if (control != "no-error") {
            require(fixture.multi({"SET", "execabort:watched", "discarded"}) == "+QUEUED\r\n",
                    "valid command queued before the error");
            require(fixture.multi({"SAVE"}) == "-ERR Command not allowed inside a transaction\r\n",
                    "ordinary queue-time error, independent of loading");
        }
        require(fixture.multi({"EXEC"}) == (control == "no-error" ? "*0\r\n" :
                    "-EXECABORT Transaction discarded because of previous errors.\r\n"), "EXEC reply");
        const uint64_t before = fixture.waits();
        unsigned denied = 0;
        const bool completed = fixture.set(denied);
        std::printf("%s execabort-watch db=%s mode=%s atomic=%d control=%s "
                    "watch_armed=%d exec_reply=%s later_set=%s denied=%u "
                    "waits_before=%llu waits_after=%llu deferred=%zu\n",
                    completed ? "PASS" : "FAIL", kSingleDatabase ? "db0" : "namespaced",
                    mode.c_str(), atomic, control.empty() ? "armed" : control.c_str(), watched,
                    control == "no-error" ? "empty-array" : "EXECABORT", completed ? "OK" : "blocked",
                    denied, static_cast<unsigned long long>(before),
                    static_cast<unsigned long long>(fixture.waits()), fixture.deferred.size());
        require(completed, "later SET still blocked after 1024 dispatch attempts");
        multi_reap_deferred(fixture.deferred);
        require(fixture.deferred.empty() && fixture.watches() == 0,
                "WATCH reservations and parent references released");
    }
}
