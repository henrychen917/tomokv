// AT15: real MULTI/EXEC bodies, without sockets, rings, workers or a listener.
// No sockets, workers, IO rings, loading service, or test hooks. Link the SAME
// witness object with PRE/POST production objects to falsify the fix in isolation.
#include "src/core/server.h"
#include "src/cmd/acl.h"
#include "src/cmd/multi.h"
#include "src/cmd/xshard.h"
#include "src/cmd/cmdmeta.h"
#include <chrono>
#include <thread>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

using namespace tomo;
namespace {
void require(bool yes, const char* why) {
    if (!yes) { std::fprintf(stderr, "FAIL at15: %s\n", why); std::exit(1); }
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
        cfg.enable_debug_command = DebugCommandMode::Yes;
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
    unsigned retries = 0;
    std::string multi(std::vector<std::string> args) {
        Request request(std::move(args));
        MultiExecState* state = nullptr;
        const auto action = multi_handle_io(server, client, request.op, io, state);
        if (action == MultiIoAction::LocalDone) return request.reply();
        require(action == MultiIoAction::Dispatch && state, "transaction dispatch");
        // These read/admin children never install key records, so no owner record sentinel
        // is needed. Real production objects drive every queue, owner phase and retirement.
        request.op.attach_multi_state(state);
        client.rob().at(0).spec = request.op.spec;
        client.atomic_group_started();
        multi_dispatch_started(client, state);
        std::vector<int32_t> remaining;
        for (uint32_t i = 0; i < multi_dispatch_count(state); ++i)
            remaining.push_back(multi_dispatch_shard(state, i));
        const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(5);
        retries = 0;
        while (!remaining.empty() && std::chrono::steady_clock::now() < deadline) {
            for (size_t i = 0; i < remaining.size();) {
                const int32_t sid = remaining[i];
                const auto result = multi_execute_task(server,
                    multi_make_task(&client, 0, sid, state), server.shard(sid),
                    server.worker_of_shard(sid), 0, nullptr);
                if (result == MultiTaskResult::Retry) { ++i; ++retries; }
                else remaining.erase(remaining.begin() + i);
            }
        }
        require(remaining.empty(), "EXEC must reply within the owner-phase bound");
        command_set_local_context(&client, &server.thread(io));
        multi_retire(client, request.op, deferred);
        command_set_local_context(nullptr, nullptr);
        multi_reap_deferred(deferred);
        require(deferred.empty(), "read/admin EXEC releases all state");
        return request.reply();
    }
};

std::string bulk(std::string body, bool resp3 = false) {
    if (resp3) body = "txt:" + body;
    return std::string(resp3 ? "=" : "$") + std::to_string(body.size()) + "\r\n" + body + "\r\n";
}
std::string exec_bulk(const std::string& wire, bool resp3) {
    const std::string prefix = resp3 ? "*1\r\n=" : "*1\r\n$";
    require(wire.starts_with(prefix), "INFO must be one bulk/verbatim element inside EXEC");
    const auto end = wire.find("\r\n", prefix.size());
    require(end != std::string::npos, "INFO length line");
    const auto length = std::stoull(wire.substr(prefix.size(), end - prefix.size()));
    const auto start = end + 2;
    require(wire.size() == start + length + 2 && wire.ends_with("\r\n"), "exact INFO frame length");
    auto body = wire.substr(start, length);
    if (resp3) {
        require(body.starts_with("txt:"), "INFO verbatim format");
        body.erase(0, 4);
    }
    return body;
}
void begin(Fixture& f) { require(f.multi({"MULTI"}) == "+OK\r\n", "MULTI reply"); }
void queue(Fixture& f, std::vector<std::string> args) {
    require(f.multi(std::move(args)) == "+QUEUED\r\n", "queued reply");
}
void check(Fixture& f, bool resp3, const std::string& only) {
    if (only.empty() || only == "info") {
        for (const char* section : {"", "server", "all", "default", "keyspace", "clients", "memory",
                "persistence", "stats", "commandstats", "flipctl", "writeback", "lb", "no-such-section"}) {
            begin(f);
            std::vector<std::string> args{"INFO"};
            if (*section) args.emplace_back(section);
            queue(f, args);
            const auto body = exec_bulk(f.multi({"EXEC"}), resp3);
            if (!*section || std::string(section) == "all" || std::string(section) == "default")
                require(body.find("# Server\r\n") != std::string::npos &&
                        body.find("# Keyspace\r\n") != std::string::npos, "default/all INFO sections");
            if (std::string(section) == "server")
                require(body.starts_with("# Server\r\n") && body.find("# Keyspace") == std::string::npos,
                        "INFO server section selection");
            if (std::string(section) == "keyspace") require(body == "# Keyspace\r\n", "empty keyspace");
            if (std::string(section) == "no-such-section") require(body.empty(), "unknown INFO section");
        }
        begin(f); queue(f, {"INFO", "server", "keyspace"});
        const auto body = exec_bulk(f.multi({"EXEC"}), resp3);
        require(body.find("# Server\r\n") != std::string::npos && body.find("# Keyspace\r\n") != std::string::npos,
                "multiple INFO sections");
    }
    if (only.empty() || only == "sleep") {
        begin(f); queue(f, {"DEBUG", "SLEEP", "0"});
        require(f.multi({"EXEC"}) == "*1\r\n+OK\r\n", "DEBUG SLEEP 0 EXEC element");
        begin(f); queue(f, {"DEBUG", "SLEEP", "0.01"});
        const auto start = std::chrono::steady_clock::now();
        require(f.multi({"EXEC"}) == "*1\r\n+OK\r\n", "DEBUG SLEEP positive EXEC element");
        require(f.retries && std::chrono::steady_clock::now() - start >= std::chrono::milliseconds(10),
                "positive SLEEP actually parked until its deadline");
    }
    if (only.empty() || only == "controls") {
        begin(f);
        require(f.multi({"MULTI"}) == "-ERR MULTI calls can not be nested\r\n", "nested MULTI exact error");
        require(f.multi({"WATCH", "at15:key"}) == "-ERR WATCH inside MULTI is not allowed\r\n", "WATCH exact error");
        queue(f, {"PING"});
        require(f.multi({"EXEC"}) == "*1\r\n+PONG\r\n", "control errors do not dirty EXEC");
        for (const char* name : {"SAVE", "SUBSCRIBE"}) {
            begin(f);
            const auto args = std::string(name) == "SAVE" ? std::vector<std::string>{name}
                : std::vector<std::string>{name, "at15:channel"};
            require(f.multi(args) == "-ERR Command not allowed inside a transaction\r\n",
                    "metadata SAVE / group-5 subscription policy exact refusal");
            require(f.multi({"EXEC"}) == "-EXECABORT Transaction discarded because of previous errors.\r\n",
                    "refusal dirties EXEC");
        }
    }
    if (only.empty() || only == "config") {
        begin(f);
        queue(f, {"CONFIG", "GET", "maxmemory"});
        queue(f, {"CONFIG", "SET", "maxmemory", "123456"});
        queue(f, {"CONFIG", "GET", "maxmemory"});
        queue(f, {"CONFIG", "SET", "maxmemory", "0"});
        const std::string pair = resp3 ? "%1\r\n" : "*2\r\n";
        require(f.multi({"EXEC"}) == "*4\r\n" + pair + bulk("maxmemory") + bulk("0") +
                "+OK\r\n" + pair + bulk("maxmemory") + bulk("123456") + "+OK\r\n",
                "CONFIG GET/SET executes in transaction order");
        begin(f); queue(f, {"CONFIG", "RESETSTAT"}); queue(f, {"DEBUG", "BORROWCOUNT"});
        require(f.multi({"EXEC"}) == "*2\r\n+OK\r\n:0\r\n", "admin/scatter reply shape");
    }
}
}
int main(int argc, char** argv) {
    require(argc >= 2 && argc <= 3, "usage: at15-unit 1s|2s [info|sleep|controls|config]");
    const std::string mode = argv[1], only = argc == 3 ? argv[2] : "";
    require(mode == "1s" || mode == "2s", "thread mode");
    require(command_registry_init(false), "registry");
    // Redis 7.4 generated metadata, not route flags or the audit's command-name guesses.
    for (const char* name : {"INFO", "DEBUG", "SUBSCRIBE", "SSUBSCRIBE", "MULTI", "WATCH", "SAVE", "FLIP"}) {
        Request request({name});
        const bool expected = std::string(name) == "SAVE" || std::string(name) == "FLIP";
        command_metadata_reply_info(request.op, command_metadata_for(*request.op.spec));
        require((request.reply().find("+no_multi\r\n") != std::string::npos) == expected,
                "generated no_multi flag");
    }
    for (int atomic : {0, 1}) for (bool resp3 : {false, true}) {
        Fixture f(mode == "1s", atomic);
        if (resp3) f.client.set_resp3(true);
        check(f, resp3, only);
        std::printf("PASS at15 db=%s mode=%s atomic=%d resp=%d case=%s\n",
                    kSingleDatabase ? "db0" : "namespaced", mode.c_str(), atomic,
                    resp3 ? 3 : 2, only.empty() ? "all" : only.c_str());
    }
}
