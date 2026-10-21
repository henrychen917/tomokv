// NT4.2 serverless frontier witness. PRE uses its real stateless parser; a
// poisoned completed header makes replay observable without a timing bound.
#include "src/net/conn.h"
#include <cstdio>
#include <random>
#include <string>
#include <vector>

namespace tomo { void multi_session_destroy(MultiSession*) {} }
using namespace tomo;
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL respresume: %s\n", why); std::exit(1); }
}
static ParseResult parse(Client& c, Op& op, uint32_t& p, const char** err,
                         bool limited = false) {
    op.reset(); p = c.rpos();
#ifdef TOMO_RESPRESUME_PRE
    return limited ? resp_parse_limited(c.rbuf(), c.rlen(), p, op, err, 10, 16384)
                   : resp_parse(c.rbuf(), c.rlen(), p, op, err);
#else
    ParseResult r;
    if (c.multibulk_pending()) r = c.resume_multibulk(p, op, err,
        limited ? 10 : 1024 * 1024, limited ? 16384 : 512ull * 1024 * 1024);
    else if (p < c.rlen() && c.rbuf()[p] != '*')
        r = resp_parse_inline(c.rbuf(), c.rlen(), p, op, err, c.inline_scanned());
    else if (limited)
        r = resp_parse_t<true, true>(c.rbuf(), c.rlen(), p, op, err, 10, 16384,
                                     &c.multibulk_frontier());
    else r = resp_parse_t<false, true>(c.rbuf(), c.rlen(), p, op, err, 0, 0,
                                       &c.multibulk_frontier());
    if (r == ParseResult::Incomplete && p < c.rlen() && c.rbuf()[p] == '*')
        c.suspend_multibulk();
    return r;
#endif
}
static void append(Client& c, const std::string& bytes) {
    size_t avail;
    char* dst = c.read_space(bytes.size() + 2048, avail, true);
    require(dst && avail >= bytes.size(), "receive allocation");
    std::memcpy(dst, bytes.data(), bytes.size()); c.commit_read(bytes.size());
}
static std::string bulk(const std::string& s) {
    return "$" + std::to_string(s.size()) + "\r\n" + s + "\r\n";
}
static std::string frame(const std::vector<std::string>& args) {
    std::string out = "*" + std::to_string(args.size()) + "\r\n";
    for (const auto& arg : args) out += bulk(arg);
    return out;
}
static std::vector<std::string> argv(const Op& op) {
    std::vector<std::string> out;
    for (uint32_t i = 0; i < op.argc(); ++i) out.emplace_back(op.arg(i).p, op.arg(i).n);
    return out;
}
static void once() {
    Client c(-1); Op op; const char* err = nullptr; uint32_t p;
    // First consume a frame, forcing the suspended next frame to have a nonzero
    // base. Then poison a completed header and compact it while no Op is live.
    append(c, frame({"PING"}));
    require(parse(c, op, p, &err) == ParseResult::Ok, "prefix frame");
    c.advance_parse(p);
    const uint32_t base = c.rpos();
    append(c, "*3\r\n$4\r\nMSET\r\n$1\r\nk\r\n$32768\r\n");
    require(parse(c, op, p, &err) == ParseResult::Incomplete, "arm partial payload");
    c.rbuf()[base + 4] = '!'; // Already parsed header; payload remains untouched.
    c.reset_rbuf_at_quiescence();
    c.set_ifid_thread(7); // Same ownership edge used by FLIP/client-LB/rollback.
    append(c, std::string(32768, 'v') + "\r\n"); // grow/rebase after suspension
    require(parse(c, op, p, &err) == ParseResult::Ok,
            "completed argument header was replayed after compaction/migration");
    require(argv(op) == std::vector<std::string>{"MSET", "k", std::string(32768, 'v')},
            "offset argv survives compaction, growth and ownership transfer");
    c.advance_parse(p);
    c.reset_rbuf_at_quiescence();
    append(c, frame({"PING"}));
    require(parse(c, op, p, &err) == ParseResult::Ok && argv(op)[0] == "PING",
            "completed frontier does not leak into next frame");
    std::puts("PASS once: completed header poison, compaction, growth, owner edge, reset");
}
static void fragmented(const std::string& wire, const std::vector<size_t>& cuts) {
    Op whole; uint32_t end = 0; const char* whole_error = nullptr;
    const auto want = resp_parse(wire.data(), wire.size(), end, whole, &whole_error);
    Client c(-1); Op op; const char* err = nullptr; uint32_t p = 0;
    size_t previous = 0;
    auto got = ParseResult::Incomplete;
    for (size_t cut : cuts) {
        append(c, wire.substr(previous, cut - previous)); previous = cut;
        got = parse(c, op, p, &err);
        if (got != ParseResult::Incomplete) break;
        require(p == c.rpos(), "incomplete consumes no bytes");
        // Re-entry without input must not disturb the frontier.
        require(parse(c, op, p, &err) == ParseResult::Incomplete, "no-input retry");
        c.reset_rbuf_at_quiescence();
    }
    require(got == want, "whole/split parse result");
    if (want == ParseResult::Ok) require(argv(op) == argv(whole) && p == end, "whole/split argv");
    if (want == ParseResult::Error)
        require(err && whole_error && std::string(err) == whole_error, "whole/split error bytes");
}
static void corpus() {
    std::vector<std::string> small = {frame({}), frame({"PING"}), frame({"ECHO", ""}),
        frame({"SET", "k", std::string("a\r\n\0b", 5)}), "PING\r\n", "\r\n", "*1\rX$4\rYPINGzz"};
    for (const std::string header : {"", "00", "-0", "+1", "-1", "x", "2147483648"}) {
        small.push_back("*" + header + "\r\n");
        for (unsigned a = 0; a < 4; ++a) {
            std::string wire = "*4\r\n";
            for (unsigned i = 0; i < a; ++i) wire += bulk("a");
            small.push_back(wire + "$" + header + "\r\n");
            small.push_back(wire + "!\r\n");
        }
    }
    for (const auto& wire : small) {
        for (size_t i = 1; i < wire.size(); ++i) fragmented(wire, {i, wire.size()});
        std::vector<size_t> cuts;
        for (size_t i = 1; i <= wire.size(); ++i) cuts.push_back(i);
        fragmented(wire, cuts);
    }
    for (uint32_t n : {1u, 2u, 10u, 1023u, 1024u, 1025u, (1u<<20)-1, 1u<<20, (1u<<20)+1}) {
        std::string wire = "*" + std::to_string(n) + "\r\n";
        for (uint32_t i = 0; i < n; ++i) wire += bulk(i % 2 ? "" : "a");
        for (unsigned seed : {7, 19, 20, 23}) {
            std::mt19937 rng(seed); std::vector<size_t> cuts;
            for (size_t i = 0; i < wire.size();) {
                i = std::min(wire.size(), i + 1 + rng() % 65536); cuts.push_back(i);
            }
            fragmented(wire, cuts);
        }
    }
    for (size_t n : {0, 1, 16383, 16384, 16385, 32767, 32768, 32769}) {
        const auto wire = frame({"SET", "k", std::string(n, 'v')});
        fragmented(wire, {1, 4, wire.size() - 2, wire.size() - 1, wire.size()});
    }
    std::puts("PASS corpus: every small split; large seeds 7/19/20/23; 1Mi boundaries");
}
static void limits() {
    for (bool preauth : {false, true}) {
        Client c(-1); Op op; const char* err = nullptr; uint32_t p;
        append(c, "*2\r\n$4\r\nECHO\r\n$16385\r");
        require(parse(c, op, p, &err, preauth) == ParseResult::Incomplete, "arm limited header");
        append(c, "\n" + std::string(16385, 'v') + "\r\n");
        require(parse(c, op, p, &err, preauth) == (preauth ? ParseResult::Error : ParseResult::Ok),
                "pre-AUTH bulk limit across reads");
        c.mark_closing();
#ifndef TOMO_RESPRESUME_PRE
        require(!c.multibulk_pending(), "close discards frontier");
#endif
    }
    Client c(-1); Op op; const char* err = nullptr; uint32_t p;
    append(c, "*11\r"); require(parse(c, op, p, &err, true) == ParseResult::Incomplete, "preauth count partial");
    append(c, "\n"); require(parse(c, op, p, &err, true) == ParseResult::Error, "preauth count bound");
    std::puts("PASS limits: pre-AUTH count/bulk bounds and close reset");
}
int main(int argc, char** args) {
    const std::string which = argc > 1 ? args[1] : "all";
    if (which == "all" || which == "once") once();
    if (which == "all" || which == "corpus") corpus();
    if (which == "all" || which == "limits") limits();
}
