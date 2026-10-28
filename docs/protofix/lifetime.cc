// Quoted argv ownership, retry and retirement under ASAN/UBSAN. No server.
#include "src/net/resp.h"
#include <string>
#include <vector>
using namespace tomo;
static void need(bool ok) { if (!ok) std::abort(); }
static std::vector<std::string> arguments(const Op& op) {
    std::vector<std::string> out;
    for (uint32_t i = 0; i < op.argc(); ++i) out.emplace_back(op.arg(i).p, op.arg(i).n);
    return out;
}
int main() {
    const std::string line = "ECHO prefix\"a b\\x00\\n\"\r\n";
    const std::vector<std::string> want{"ECHO", std::string("prefixa b\0\n", 11)};
    Op op;
    for (unsigned round = 0; round < 100; ++round) {
        auto input = line;
        op.reset(); uint32_t pos = 0, scanned = 0; const char* error = nullptr;
        need(resp_parse_inline(input.data(), input.size(), pos, op, &error, scanned) == ParseResult::Ok);
        need(pos == input.size() && arguments(op) == want);
        std::fill(input.begin(), input.end(), '!');
        op.reply.append(std::string(16384, 'r'));
        need(arguments(op) == want); // Both receive and reply buffers are unrelated.
        op.reset(); pos = 0;
        need(resp_parse(line.data(), line.size(), pos, op, &error) == ParseResult::Ok);
        need(arguments(op) == want); // Dispatch refusal reparses immutable input.
        op.reset(); pos = 0;
        const std::string plain = "GET k\r\n";
        need(resp_parse(plain.data(), plain.size(), pos, op, &error) == ParseResult::Ok);
        need(arguments(op) == std::vector<std::string>{"GET", "k"});
        op.shrink(); need(!op.oversized());
    }
    std::string many = "MGET";
    for (unsigned i = 0; i < 1000; ++i) many += " \"\\x00key\"";
    many += '\n';
    op.reset(); uint32_t pos = 0; const char* error = nullptr;
    need(resp_parse_limited(many.data(), many.size(), pos, op, &error, 10, 16384) == ParseResult::Ok);
    need(op.argc() == 1001);
    std::fill(many.begin(), many.end(), '!');
    for (unsigned i = 1; i < op.argc(); ++i)
        need(std::string(op.arg(i).p, op.arg(i).n) == std::string("\0key", 4));
    op.reset(); pos = 0;
    const std::string bad = "ECHO \"bad\n";
    need(resp_parse(bad.data(), bad.size(), pos, op, &error) == ParseResult::Error);
    need(pos == 0);
    std::puts("PASS owned quoted argv: immutable input, reply growth, 100 retries/reuses, 1001 args, error cleanup");
}
