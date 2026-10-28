// Bounded parser instruction and ownership witness. No server or worker threads.
#include "src/net/resp.h"
#include <array>
#include <string>
using namespace tomo;
[[gnu::noinline]] void scope_begin() { asm volatile("" ::: "memory"); }
[[gnu::noinline]] void scope_end() { asm volatile("" ::: "memory"); }
namespace tomo {
[[gnu::noinline]] void protofix_parse_scope(const std::string& input, Op* ops, unsigned batch) {
    uint32_t pos = 0;
    const char* err = nullptr;
    for (unsigned i = 0; i < batch; ++i) {
        ops[i].reset();
        if (resp_parse(input.data(), input.size(), pos, ops[i], &err) != ParseResult::Ok) std::abort();
    }
    if (pos != input.size()) std::abort();
}
}
int main(int argc, char** argv) {
    if (argc != 6) return 2;
    const std::string command = argv[1], protocol = argv[2];
    const unsigned batch = std::stoul(argv[3]);
    if (batch > 32) return 2;
    std::array<Op, 32> ops;
    std::string frame;
    if (protocol == "inline") frame = command + " key" + (command == "SET" ? " value" : "") + "\r\n";
    else {
        frame = command == "SET" ? "*3\r\n" : "*2\r\n";
        frame += "$" + std::to_string(command.size()) + "\r\n" + command + "\r\n$3\r\nkey\r\n";
        if (command == "SET") frame += "$5\r\nvalue\r\n";
    }
    std::string wire;
    for (unsigned i = 0; i < batch; ++i) wire += frame;
    scope_begin();
    protofix_parse_scope(wire, ops.data(), batch);
    scope_end();
    for (unsigned i = 0; i < batch; ++i) {
        if (ops[i].oversized() || ops[i].argc() != (command == "SET" ? 3u : 2u) ||
            std::string(ops[i].arg(0).p, ops[i].arg(0).n) != command ||
            std::string(ops[i].arg(1).p, ops[i].arg(1).n) != "key") return 1;
    }
    std::puts("PASS bounded allocation-free parser scope");
}
