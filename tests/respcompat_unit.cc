// NET13/14/15/16: production parser, no listener, ring, workers or timing loops.
#define TOMO_NETCAP_TEST
#include "src/net/resp.h"
#include <string>
#include <vector>

namespace tomo { uint64_t netcap_scan_bytes = 0; }
using tomo::ParseResult;
using namespace std::string_literals;
static unsigned checks = 0, failures = 0;
static void check(bool ok, const std::string& label) {
    ++checks;
    if (!ok) { ++failures; std::fprintf(stderr, "FAIL %s\n", label.c_str()); }
}
static void parse(const std::string& input, ParseResult want, const char* error = nullptr,
                  const std::vector<std::string>& args = {}, uint64_t max_bulk = 0) {
    // The extra prefix exercises nonzero receive-buffer offsets as well as zero.
    for (const std::string& prefix : {std::string{}, std::string{"already consumed"}}) {
        const auto data = prefix + input;
        tomo::Op op; uint32_t pos = prefix.size(); const char* err = nullptr;
        const auto got = max_bulk
            ? tomo::resp_parse_limited(data.data(), data.size(), pos, op, &err, 1024 * 1024, max_bulk)
            : tomo::resp_parse(data.data(), data.size(), pos, op, &err);
        const auto label = input.substr(0, 40);
        check(got == want, "result " + label);
        if (error) {
            if (op.reply.empty() && err) tomo::reply_err(op.reply, err);
            check(std::string(op.reply.data(), op.reply.size()) == std::string("-") + error + "\r\n",
                  "exact error " + label);
        }
        if (want == ParseResult::Ok || want == ParseResult::Empty) {
            check(pos == data.size(), "consumed exactly " + label);
            check(op.argc() == args.size(), "argc " + label);
            for (unsigned i = 0; i < args.size() && i < op.argc(); ++i)
                check(std::string(op.arg(i).p, op.arg(i).n) == args[i], "argv " + label);
        } else check(pos == prefix.size(), "failed/incomplete cursor " + label);
        check(data == prefix + input, "immutable receive bytes " + label);
    }
}
int main() {
    constexpr auto invalid_array = "ERR Protocol error: invalid multibulk length";
    constexpr auto invalid_bulk = "ERR Protocol error: invalid bulk length";
    constexpr auto quotes = "ERR Protocol error: unbalanced quotes in request";
    for (const char* field : {"", "00", "01", "-0", "-01", "+1", " 1", "1 ", "x",
            "2147483648", "9223372036854775808", "-9223372036854775809", "18446744073709551616"})
        parse(std::string("*") + field + "\r\n", ParseResult::Error, invalid_array);
    for (const char* field : {"0", "-1", "-2", "-2147483649", "-9223372036854775808"})
        parse(std::string("*") + field + "\r\n", ParseResult::Empty);
    for (const char* field : {"", "00", "04", "-0", "-1", "-2", "-01", "+1", " 1", "1 ", "x",
            "536870913", "9223372036854775808", "18446744073709551616"})
        parse(std::string("*1\r\n$") + field + "\r\n", ParseResult::Error, invalid_bulk);
    parse("*1\r\n$0\r\n\r\n", ParseResult::Ok, nullptr, {""});
    parse("*2\r\n$4\r\nECHO\r\n$3\r\na\0b\r\n"s, ParseResult::Ok, nullptr, {"ECHO", "a\0b"s});
    const std::string ping = "*1\r\n$4\r\nPING\r\n";
    parse(ping, ParseResult::Ok, nullptr, {"PING"});
    parse("*1\rX$4\rYPINGzz", ParseResult::Ok, nullptr, {"PING"});
    for (size_t i = 0; i < ping.size(); ++i) parse(ping.substr(0, i), ParseResult::Incomplete);
    for (const char* incomplete : {"*x", "*01", "*-1\r", "*2147483648\r", "*2147483647\r\n",
            "*1048577\r\n", "*1\r\n!", "*1\r\n!\r", "*1\r\n$-1", "*1\r\n$x\r"})
        parse(incomplete, ParseResult::Incomplete);
    parse("*1\r\n\0\r\n"s, ParseResult::Incomplete);
    parse("*1\r\n$9223372036854775807\r\n", ParseResult::Incomplete, nullptr, {}, INT64_MAX);
    parse("*1\r\n$18446744073709551616\r\n", ParseResult::Error, invalid_bulk, {}, INT64_MAX);
    for (unsigned byte = 1; byte < 256; ++byte) {
        if (byte == '$') continue;
        const std::string msg = std::string("ERR Protocol error: expected '$', got '") +
            (byte == '\r' || byte == '\n' ? ' ' : static_cast<char>(byte)) + "'";
        parse(std::string("*1\r\n") + static_cast<char>(byte) + "\r\n", ParseResult::Error, msg.c_str());
    }
    for (bool bulk : {false, true}) {
        const std::string prefix = bulk ? "*1\r\n$" : "*";
        const auto large = prefix + std::string(65535, '0');
        parse(large, ParseResult::Incomplete);
        parse(large + '0', ParseResult::Error, bulk ? "ERR Protocol error: too big bulk count string"
                                                  : "ERR Protocol error: too big mbulk count string");
        parse(large + "\r", ParseResult::Incomplete);
        parse(large + "\r\n", ParseResult::Error, bulk ? invalid_bulk : invalid_array);
    }
    for (const char* input : {"PING\n", "PING\r\n", " PING\t\r\n"})
        parse(input, ParseResult::Ok, nullptr, {"PING"});
    for (const char* input : {"\n", "\r\n", " \t\n"}) parse(input, ParseResult::Empty);
    for (const char* input : {"ECHO \"a\n", "ECHO 'a\r\n", "ECHO \"a\"x\n", "ECHO 'a'x\n",
                              "ECHO \"a\\\"\n", "ECHO 'a\\'\n"})
        parse(input, ParseResult::Error, quotes);
    parse(std::string(65536, 'x'), ParseResult::Incomplete);
    parse(std::string(65537, 'x'), ParseResult::Error, "ERR Protocol error: too big inline request");
    parse("PING\0\n"s, ParseResult::Incomplete);
    // Scan cursor: one-byte arrivals plus repeated parse refusals are linear.
    const std::string line = std::string(65535, 'x') + "\r\n";
    uint32_t scanned = 0, pos = 0; const char* err = nullptr; tomo::Op op;
    tomo::netcap_scan_bytes = 0;
    for (uint32_t len = 1; len < line.size(); ++len)
        for (unsigned repeat = 0; repeat < 3; ++repeat)
            check(tomo::resp_parse_inline(line.data(), len, pos, op, &err, scanned) == ParseResult::Incomplete,
                  "fragmented inline remains incomplete");
    check(tomo::resp_parse_inline(line.data(), line.size(), pos, op, &err, scanned) == ParseResult::Ok,
          "fragmented CRLF completes");
    check(tomo::netcap_scan_bytes == line.size() && scanned == 0, "linear LF scan and cursor reset");
    op.reset(); pos = 0;
    check(tomo::resp_parse_inline(line.data(), line.size(), pos, op, &err, scanned) == ParseResult::Ok &&
          op.arg(0).n == 65535, "retry keeps pinned input and argv intact");
    std::printf("respcompat: %u checks, %u failures\n", checks, failures);
    return failures ? 1 : 0;
}
