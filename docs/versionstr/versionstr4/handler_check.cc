// Direct calls into the linked production command objects. No Server, listener,
// worker thread, or io_uring instance is started by this receipt executable.
#include "src/cmd/command.h"
#include "src/core/shard.h"
#include "src/exec/op.h"
#include <cstdio>
#include <cstdlib>
#include <string>

static void require(bool ok, const char* message) {
    if (!ok) { std::fprintf(stderr, "FAIL: %s\n", message); std::exit(1); }
}

static std::string run(const char* command, const char* argument) {
    tomo::Shard shard;
    tomo::Op op;
    require(op.push_arg(tomo::Slice(command)), "command argument");
    require(op.push_arg(tomo::Slice(argument)), "second argument");
    op.spec = tomo::command_lookup(op.cmd_name());
    require(op.spec != nullptr, "registered production handler");
    op.spec->handler(shard, op);
    return std::string(op.reply.data(), op.reply.size());
}

int main(int argc, char** argv) {
    require(argc == 1 || argc == 3, "optional compatibility and product expectations");
    const std::string compat = argc == 3 ? argv[1] : "7.4.10";
    const std::string product = argc == 3 ? argv[2] : "1.0-cpp";
    require(tomo::command_registry_init(false), "command registry");
    const std::string info = run("INFO", "SERVER");
    require(info.starts_with("$"), "INFO bulk reply");
    require(info.find("# Server\r\nredis_version:" + compat +
                      "\r\ntomokv_version:" + product +
                      "\r\nredis_mode:standalone\r\n") != std::string::npos,
            "INFO exact identity, field order and CRLF");
    std::printf("INFO SERVER redis_version=%s tomokv_version=%s\n",
                compat.c_str(), product.c_str());
    for (const char* protocol : {"2", "3"}) {
        const std::string hello = run("HELLO", protocol);
        require(hello.starts_with(*protocol == '2' ? "*14\r\n" : "%7\r\n"),
                "HELLO RESP2 array / RESP3 map");
        const std::string field = "$7\r\nversion\r\n$" + std::to_string(compat.size()) +
                                  "\r\n" + compat + "\r\n$5\r\nproto\r\n:" +
                                  protocol + "\r\n";
        require(hello.find(field) != std::string::npos, "HELLO exact version and protocol");
        std::printf("HELLO %s version=%s\n", protocol, compat.c_str());
    }
    std::puts("PASS: production handlers; no server started");
}
