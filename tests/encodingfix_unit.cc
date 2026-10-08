// Real collection/CONFIG handlers and INFO accounting, without workers or a listener.
#include "netcmd_unit.h"
#include "src/core/server.h"
#include <iostream>

namespace tomo {
// Reuse the existing private-fixture friendship; this is a separate unit executable.
struct NetcmdRegression {
    Server server;
    explicit NetcmdRegression(unsigned atomic) {
        server.cfg_.atomic = atomic;
        server.set_atomic_enabled(atomic != 0);
        server.live_config_version_.store(2);
        server.live_config_committed_ = server.capture_live_config(2);
        server.live_config_mailboxes_ = std::make_unique<LiveConfigMailbox[]>(1);
        server.live_config_mailboxes_[0].init(server.live_config_committed_);
        server.shards_.push_back(std::make_unique<Shard>());
        server.shards_[0]->init_private(&server, 0, server.cfg_.encodings.type_limits(),
                                       server.cfg_.stream_limits);
        command_bind_server(&server);
    }
    ~NetcmdRegression() { command_bind_server(nullptr); }
    std::string run(const std::vector<std::string>& values) {
        Op op;
        for (const auto& value : values) check(op.push_arg(Slice(value)), "trace argument");
        op.spec = command_lookup(op.cmd_name());
        check(op.spec, "trace command exists");
        if (op.spec->first_key > 0) op.hash = FlatStore::hash_key(op.arg(op.spec->first_key));
        op.shard = 0;
        op.mark_no_borrow();
        auto& shard = server.shard(0);
        shard.publish_size();
        op.spec->handler(shard, op);
        // Owner CONFIG fragments are empty on success; the scatter coordinator emits OK.
        if (values.size() >= 2 && values[0] == "CONFIG" && values[1] == "SET" && !op.reply.size())
            return "+OK\r\n";
        return std::string(op.reply.data(), op.reply.size());
    }
};
}

static std::string bulk(const std::string& s) {
    return "$" + std::to_string(s.size()) + "\r\n" + s + "\r\n";
}
static void encoding(tomo::NetcmdRegression& fixture, const char* key, const char* expected) {
    const auto actual = fixture.run({"OBJECT", "ENCODING", key});
    if (actual != bulk(expected)) std::cerr << key << ": " << actual << "expected " << expected << '\n';
    check(actual == bulk(expected), "exact collection encoding");
}
static void knob(tomo::NetcmdRegression& fixture) {
    const std::string name = "set-max-intset-entries";
    check(fixture.run({"CONFIG", "GET", name}) == "*2\r\n" + bulk(name) + bulk("512"),
          "Redis default intset limit");
    for (const char* value : {"0", "7", "9223372036854775807", "512"}) {
        check(fixture.run({"CONFIG", "SET", name, value}) == "+OK\r\n", "intset SET accepted");
        check(fixture.run({"CONFIG", "GET", name}) == "*2\r\n" + bulk(name) + bulk(value),
              "full public integer round trip");
        const auto owner_limit = []<class Limits>(const Limits& limits) {
            if constexpr (requires { limits.set_intset_max_entries; }) return limits.set_intset_max_entries;
            else return 128u; // PRE control: the missing knob must fail the same witness.
        }(fixture.server.shard(0).type_limits());
        check(owner_limit == std::min<uint64_t>(std::stoull(value), 1u << 30), "owner limit changed");
    }
    for (const char* value : {"-1", "+1", "01", "-0", "1kb", "", "9223372036854775808"}) {
        check(fixture.run({"CONFIG", "SET", name, value}).starts_with("-ERR"), "invalid grammar rejected");
        check(fixture.run({"CONFIG", "GET", name}) == "*2\r\n" + bulk(name) + bulk("512"),
              "invalid SET preserved value");
    }
}
static void precedence(tomo::NetcmdRegression& f) {
    check(f.run({"CONFIG", "SET", "set-max-intset-entries", "3",
                 "set-max-listpack-entries", "5", "set-max-listpack-value", "8"}) == "+OK\r\n",
          "non-default thresholds");
    check(f.run({"SADD", "grow", "0", "1", "2"}) == ":3\r\n", "integer set seeded");
    encoding(f, "grow", "intset");
    check(f.run({"SADD", "grow", "3"}) == ":1\r\n", "integer limit crossed");
    encoding(f, "grow", "hashtable");
    check(f.run({"SREM", "grow", "3"}) == ":1\r\n", "boundary member removed");
    encoding(f, "grow", "hashtable");
    check(f.run({"SADD", "fresh", "0", "1", "2", "3"}) == ":4\r\n", "fresh size hint");
    encoding(f, "fresh", "listpack");
    check(f.run({"SADD", "mixed", "0", "1"}) == ":2\r\n", "mixed seed");
    encoding(f, "mixed", "intset");
    check(f.run({"SADD", "mixed", "x"}) == ":1\r\n", "string transition");
    encoding(f, "mixed", "listpack");
    check(f.run({"SADD", "wide", "9223372036854775807", "1"}) == ":2\r\n", "wide integer seed");
    check(f.run({"SREM", "wide", "9223372036854775807"}) == ":1\r\n", "wide integer removed");
    check(f.run({"SADD", "wide", "x"}) == ":1\r\n", "remaining integers fit listpack");
    encoding(f, "wide", "listpack");
    check(f.run({"SREM", "mixed", "x"}) == ":1\r\n", "string removed");
    encoding(f, "mixed", "listpack");
    check(f.run({"SADD", "hint", "1"}) == ":1\r\n", "hint seed");
    check(f.run({"SADD", "hint", "1", "1", "1", "1"}) == ":0\r\n", "duplicate hint");
    encoding(f, "hint", "hashtable");
    check(f.run({"CONFIG", "SET", "set-max-intset-entries", "0"}) == "+OK\r\n", "disable intsets");
    check(f.run({"SADD", "zero", "1"}) == ":1\r\n", "zero intset limit insertion");
    encoding(f, "zero", "listpack");
    check(f.run({"CONFIG", "SET", "set-max-listpack-entries", "0"}) == "+OK\r\n", "disable listpacks");
    check(f.run({"SADD", "off", "1"}) == ":1\r\n", "both compact forms disabled");
    encoding(f, "off", "hashtable");
}
int main(int argc, char** argv) {
    check(argc >= 2, "knob, precedence or trace mode required");
    check(tomo::command_registry_init(false), "command registry initialized");
    const std::string mode = argv[1];
    if (mode == "trace") {
        tomo::NetcmdRegression f(argc > 2 ? std::stoul(argv[2]) : 0);
        std::string line;
        while (std::getline(std::cin, line)) {
            check(!line.empty() && line[0] == '*', "RESP command array");
            std::vector<std::string> args;
            const unsigned count = std::stoul(line.substr(1));
            for (unsigned i = 0; i < count; ++i) {
                check(bool(std::getline(std::cin, line)) && line[0] == '$', "RESP bulk header");
                const auto n = std::stoul(line.substr(1));
                std::string value(n, '\0'); std::cin.read(value.data(), n);
                char crlf[2]; std::cin.read(crlf, 2);
                check(bool(std::cin) && crlf[0] == '\r' && crlf[1] == '\n', "complete RESP bulk");
                args.push_back(std::move(value));
            }
            std::cout << f.run(args) << std::flush;
        }
        return 0;
    }
    for (unsigned atomic : {0u, 1u}) {
        tomo::NetcmdRegression f(atomic);
        if (mode == "knob") knob(f);
        else { check(mode == "precedence", "known unit mode"); precedence(f); }
    }
    std::printf("PASS encodingfix %s: atomic=0,1; no server started\n", mode.c_str());
}
