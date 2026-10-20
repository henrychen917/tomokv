// NET1 serverless witnesses. No listener, worker, ring, or load generator is started.
#define TOMO_NETCAP_TEST
#include "src/core/io_loop.h"
#include <string>
#include <cstdio>
#include <cstdlib>

namespace tomo { uint64_t netcap_scan_bytes = 0; }
namespace {
void check(bool ok, const char* message) {
    if (!ok) { std::fprintf(stderr, "FAIL netcap: %s\n", message); std::exit(1); }
}
void* watched_buffer = nullptr;
unsigned buffer_frees = 0;

void inline_limit() {
    const std::string input(1024 * 1024, 'x');
    for (bool preauth : {false, true}) {
        tomo::Op op; uint32_t pos = 0; const char* error = nullptr;
        const auto result = preauth
            ? tomo::resp_parse_limited(input.data(), input.size(), pos, op, &error, 10, 16384)
            : tomo::resp_parse(input.data(), input.size(), pos, op, &error);
        check(result == tomo::ParseResult::Error, "NET1: 1 MiB unterminated inline rejected");
        check(error && std::string(error) == "ERR Protocol error: too big inline request",
              "NET1: exact Redis inline error before and after AUTH");
    }
}
#ifndef TOMO_NETCAP_OLD
void scan() {
    using namespace tomo;
    Client c(-1); size_t avail = 0;
    check(c.read_space(65537, avail, true) && avail >= 65537, "scan fixture allocation");
    std::memset(c.rbuf(), 'x', 65535);
    c.rbuf()[65535] = '\r'; c.rbuf()[65536] = '\n';
    netcap_scan_bytes = 0;
    Op op; const char* error = nullptr;
    for (uint32_t length = 1; length <= 65536; ++length) {
        c.commit_read(1);
        for (int retry = 0; retry != 3; ++retry) {
            uint32_t pos = c.rpos();
            check(resp_parse_inline(c.rbuf(), c.rlen(), pos, op, &error, c.inline_scanned()) ==
                      ParseResult::Incomplete && pos == 0,
                  "legal incomplete boundary stays open");
        }
    }
    c.commit_read(1); uint32_t pos = 0;
    check(resp_parse_inline(c.rbuf(), c.rlen(), pos, op, &error, c.inline_scanned()) == ParseResult::Ok,
          "split CRLF completes boundary inline");
    check(netcap_scan_bytes == 65537, "NET1: every byte scanned once for LF despite retries");
    check(pos == 65537 && op.argc() == 1 && op.arg(0).n == 65535, "boundary argument intact");
    op.reset(); pos = 0;
    check(resp_parse_inline(c.rbuf(), c.rlen(), pos, op, &error, c.inline_scanned()) == ParseResult::Ok,
          "complete inline can be reparsed after dispatch backpressure");

    Client compact(-1);
    std::memcpy(compact.rbuf(), "PING\r\npartial\r", 14); compact.commit_read(14);
    compact.advance_parse(6); pos = compact.rpos(); op.reset();
    check(resp_parse_inline(compact.rbuf(), compact.rlen(), pos, op, &error,
                            compact.inline_scanned()) == ParseResult::Incomplete, "partial after earlier command");
    const auto before = netcap_scan_bytes;
    compact.reset_rbuf_at_quiescence();
    compact.rbuf()[compact.rlen()] = '\n'; compact.commit_read(1); pos = 0;
    check(resp_parse_inline(compact.rbuf(), compact.rlen(), pos, op, &error,
                            compact.inline_scanned()) == ParseResult::Ok && op.arg(0) == Slice("partial", 7),
          "scan cursor survives compaction");
    check(netcap_scan_bytes == before + 1, "compaction preserves scanned prefix");
    compact.advance_parse(pos);
    check(compact.inline_scanned() == 0, "consuming frame resets inline cursor");
}
void buffers() {
    using namespace tomo;
    Client c(-1); size_t avail = 0;
    char* dst = c.read_space(2 * 1024 * 1024, avail, true, 512ull << 20, 1 << 20);
    check(dst && avail == (1 << 20) + 1 && c.rcap() == avail,
          "NET1: query cap bounds allocation including one overflow byte");
    dst[0] = '*'; c.commit_read(1 << 20);
    check(!c.query_buffer_exceeded(1 << 20), "query limit equality is legal");
    check(c.read_space(16384, avail, false, 512ull << 20, 1 << 20) && avail == 1,
          "last overflow byte offered without growth");
    c.commit_read(1);
    check(c.query_buffer_exceeded(1 << 20), "NET1: query limit overflow detected");
    check(!c.read_space(16384, avail, true, 512ull << 20, 1 << 20) && !avail,
          "full query buffer never offers zero-length recv");
    c.advance_parse(10);
    check(!c.query_buffer_exceeded(1 << 20), "parsed pinned bytes excluded from pending input");
    check(c.query_buffer_exceeded(1 << 20, 10), "queued MULTI argv included in limit");
    Client inline_c(-1);
    dst = inline_c.read_space(16384, avail, true); dst[0] = 'x'; inline_c.commit_read(1);
    check(inline_c.read_space(1 << 20, avail, true) && inline_c.rcap() == 65537 && avail == 65536,
          "NET1: epoll and TLS buffering stops at inline frontier");
}
void frontier() {
    using namespace tomo;
    constexpr uint64_t limit = 1 << 20;
    Client c(-1);
    auto append = [&](std::string_view bytes) {
        size_t avail = 0;
        char* dst = c.read_space(std::max<size_t>(kRbufInitial, bytes.size()), avail,
                                 true, 512ull << 20, limit);
        check(dst && avail >= bytes.size(), "N4: receive offer includes the saved prefix");
        std::memcpy(dst, bytes.data(), bytes.size());
        c.commit_read(bytes.size());
    };
    auto parse = [&] {
        Op op; const char* error = nullptr; uint32_t pos = c.rpos();
        const auto result = c.multibulk_pending()
            ? c.resume_multibulk(pos, op, &error, 1024 * 1024, 512ull << 20)
            : resp_parse_t<false, true>(c.rbuf(), c.rlen(), pos, op, &error,
                                        0, 0, &c.multibulk_frontier());
        check(result == ParseResult::Incomplete, "N4: fixture really suspends the parser");
        c.suspend_multibulk();
    };
    std::string prefix = "*200000\r\n";
    for (unsigned i = 0; i != 149795; ++i) prefix += "$1\r\na\r\n";
    check(prefix.size() == limit - 2, "N4: exact partial-header fixture");
    append(prefix);
    check(!c.query_buffer_exceeded(limit), "N4: initial read below limit");
    parse();
    check(c.multibulk_frontier().completed == 149795 &&
          c.multibulk_frontier().next == prefix.size(),
          "N4: completed-prefix frontier actually opened");
    check(!c.query_buffer_exceeded(limit, limit),
          "N4: completed argv excluded even when queued MULTI equals the limit");
    append("$1");
    check(!c.query_buffer_exceeded(limit, limit - 2),
          "N4: incomplete header counted, equality legal");
    check(c.query_buffer_exceeded(limit, limit - 1),
          "N4: queued MULTI plus incomplete header exceeds limit");
    parse();
    append("\r\n");
    check(!c.query_buffer_exceeded(limit), "N4: partial header crosses retained-frame limit");
    parse();
    check(c.multibulk_frontier().bulk == 1 &&
          c.multibulk_frontier().next == c.rlen(),
          "N4: decoded header trimmed before its payload arrives");
    append("a\r");
    parse();
    check(c.query_buffer_exceeded(1), "N4: incomplete payload and terminator still count");
    append("\n");
    parse();
    check(!c.query_buffer_exceeded(0), "N4: completed payload trimmed on earlier parse pass");
    check(!std::memcmp(c.rbuf(), prefix.data(), prefix.size()),
          "N4: pinned argv bytes never rewritten or discarded");

    Client payload(-1); size_t avail = 0;
    const std::string header = "*2\r\n$4\r\nECHO\r\n$2097152\r\n";
    std::memcpy(payload.rbuf(), header.data(), header.size()); payload.commit_read(header.size());
    Op op; const char* error = nullptr; uint32_t pos = 0;
    check(resp_parse_t<false, true>(payload.rbuf(), payload.rlen(), pos, op, &error,
                                   0, 0, &payload.multibulk_frontier()) == ParseResult::Incomplete,
          "N4: payload fixture suspends after decoded header");
    payload.suspend_multibulk();
    char* dst = payload.read_space(limit + 1, avail, true, 512ull << 20, limit);
    check(dst && avail == limit + 1, "N4: payload cap allows exactly one overflow byte");
    std::memset(dst, 'x', limit + 1); payload.commit_read(limit);
    check(!payload.query_buffer_exceeded(limit), "N4: unparsed payload equality is legal");
    payload.commit_read(1);
    check(payload.query_buffer_exceeded(limit), "N4: unparsed payload overflow closes");

    Client unread(-1);
    dst = unread.read_space(limit + 8, avail, true);
    check(dst && avail >= limit + 8, "N4: unparsed fixture allocation");
    std::memcpy(dst, prefix.data(), prefix.size());
    std::memcpy(dst + prefix.size(), "$1\r\na\r\n", 7);
    unread.commit_read(prefix.size() + 7);
    check(unread.query_buffer_exceeded(limit),
          "N4: newly read prefixes count until parsing, never trim before checking");
}
void grammar() {
    using namespace tomo;
    Config cfg; ConfigParseState state;
    check(cfg.client_query_buffer_limit == 1073741824, "Redis 1gb query limit default");
    check(parse_config_args({"--client-query-buffer-limit", "2m"}, cfg, state, 1, "unit") == kConfigParsed &&
          cfg.client_query_buffer_limit == 2000000, "CLI query limit accepts decimal memory suffix");
    uint64_t value; const char* error = nullptr;
    for (const auto& [input, expected] : {
            std::pair{"1mb", 1048576ull}, {"2M", 2000000ull}, {"1GB", 1073741824ull},
            {"001048576B", 1048576ull}, {"9223372036854775807", 9223372036854775807ull}})
        check(cfg_parse_query_buffer_limit(input, std::strlen(input), value, error) && value == expected,
              "Redis memory grammar accepted");
    for (const char* input : {"0", "1048575", "1m", "9223372036854775808", "", "mb"})
        check(!cfg_parse_query_buffer_limit(input, std::strlen(input), value, error) &&
              std::string(error) == "argument must be between 1048576 and 9223372036854775807 inclusive",
              "query limit rejects unsupported range with Redis text");
    for (const char* input : {"-1", "1.5mb", "1MiB", "+1048576", " 1mb"})
        check(!cfg_parse_query_buffer_limit(input, std::strlen(input), value, error) &&
              std::string(error) == "argument must be a memory value", "Redis memory grammar error");
    for (const char* input : {"0", "-1", "1m", "bad"}) {
        Config invalid; ConfigParseState invalid_state;
        check(parse_config_args({"--client-query-buffer-limit", input}, invalid, invalid_state, 1, "unit") == kConfigError,
              "CLI query limit rejects invalid values before boot");
    }
}
void framing() {
    using namespace tomo;
    for (const auto& [input, expected] : {
             std::pair{"*x\r\n", "ERR Protocol error: invalid multibulk length"},
             {"*1\r\n!\r\n", "ERR Protocol error: expected '$', got '!'"},
             {"*1\r\n$x\r\n", "ERR Protocol error: invalid bulk length"}}) {
        Op op; uint32_t pos = 0; const char* error = nullptr;
        check(resp_parse(input, std::strlen(input), pos, op, &error) == ParseResult::Error &&
              error && std::string(error) == expected, "Redis framing error text");
    }
    for (unsigned byte = 0; byte != 256; ++byte) {
        if (byte == '$') continue;
        const char input[] = {'*', '1', '\r', '\n', static_cast<char>(byte), '\r', '\n'};
        Op op; uint32_t pos = 0; const char* error = nullptr;
        if (byte == 0) {
            check(resp_parse(input, sizeof(input), pos, op, &error) == ParseResult::Incomplete,
                  "Redis count-line search stops at NUL before the CR");
            continue;
        }
        check(resp_parse(input, sizeof(input), pos, op, &error) == ParseResult::Error,
              "every non-dollar bulk prefix rejected");
        std::string expected = "-ERR Protocol error: expected '$', got '";
        expected += byte == '\r' || byte == '\n' ? ' ' : static_cast<char>(byte);
        expected += "'\r\n";
        check(std::string(op.reply.data(), op.reply.size()) == expected,
              "binary offending byte preserved and CR/LF sanitized in framing error");
    }
}
#endif
}
extern "C" void __real_free(void*);
extern "C" void __wrap_free(void* p) {
    if (p && p == watched_buffer) ++buffer_frees;
    __real_free(p);
}
#ifndef TOMO_NETCAP_OLD
namespace tomo {
// Existing serverless private-implementation fixture access. Link separately from netcmd-unit.
struct NetcmdRegression {
    static std::string command(Shard& shard, std::initializer_list<const char*> args) {
        Op op;
        for (const char* arg : args) check(op.push_arg(Slice(arg, std::strlen(arg))), "config argv");
        op.spec = command_lookup(op.cmd_name());
        check(op.spec != nullptr, "config command exists");
        op.spec->handler(shard, op);
        return std::string(op.reply.data(), op.reply.size());
    }
    static void config() {
        Server server; ThreadCtx self; IoLoop loop;
        server.live_config_version_.store(2);
        server.live_config_committed_ = server.capture_live_config(2);
        server.live_config_mailboxes_ = std::make_unique<LiveConfigMailbox[]>(1);
        server.live_config_mailboxes_[0].init(server.live_config_committed_);
        server.shards_.push_back(std::make_unique<Shard>());
        Shard& shard = *server.shards_[0];
        shard.init_private(&server, 0, TypeLimits{}, StreamLimits{});
        command_bind_server(&server);
        loop.srv_ = &server; loop.self_ = &self;
        auto get = [&] { return command(shard, {"CONFIG", "GET", "client-query-buffer-limit"}); };
        check(get() == "*2\r\n$25\r\nclient-query-buffer-limit\r\n$10\r\n1073741824\r\n", "CONFIG query limit default");
        check(command(shard, {"CONFIG", "SET", "client-query-buffer-limit", "2mb"}).empty(), "CONFIG query limit accepted");
        loop.refresh_notify_config();
        check(loop.client_query_buffer_limit_ == 2097152, "NET1: CONFIG SET reaches IO committed snapshot");
        check(get() == "*2\r\n$25\r\nclient-query-buffer-limit\r\n$7\r\n2097152\r\n", "CONFIG query limit normalized GET");
        const auto before = get();
        const auto rejected = command(shard, {"CONFIG", "SET", "client-query-buffer-limit", "0"});
        check(rejected == "-ERR CONFIG SET failed (possibly related to argument 'client-query-buffer-limit') - argument must be between 1048576 and 9223372036854775807 inclusive\r\n",
              "CONFIG query limit exact range error");
        check(get() == before, "rejected CONFIG SET leaves published value intact");
        check(command(shard, {"CONFIG", "GET", "proto-max-inline"}) == "*0\r\n", "Redis has no proto-max-inline knob");
        Client queued(-1); MultiExecState* dispatch = nullptr;
        auto multi = [&](std::initializer_list<const char*> args) {
            Op op;
            for (const char* arg : args) check(op.push_arg(Slice(arg, std::strlen(arg))), "MULTI argv");
            op.spec = command_lookup(op.cmd_name());
            check(multi_handle_io(server, queued, op, 0, dispatch) == MultiIoAction::LocalDone,
                  "serverless MULTI transition handled locally");
        };
        multi({"MULTI"}); multi({"ECHO", "abc"});
        check(multi_session_query_bytes(queued) == 7 + 2 * sizeof(void*),
              "query limit counts queued payload and Redis argv pointer allowance");
        check(multi_session_memory(queued) == 7, "existing CLIENT memory reporting unchanged");
        multi({"DISCARD"});
        check(multi_session_query_bytes(queued) == 0, "discard clears queued query accounting");
        command_bind_server(nullptr);
    }
    static void inline_close() {
        Server server; ThreadCtx self; IoLoop loop;
        loop.srv_ = &server; loop.self_ = &self;
        Client* c = new Client(-1); c->set_id(2);
        size_t avail = 0;
        check(c->read_space(1 << 20, avail, true) && avail >= (1 << 20), "inline close fixture allocation");
        std::memset(c->rbuf(), 'x', 1 << 20); c->commit_read(1 << 20);
        watched_buffer = c->rbuf(); buffer_frees = 0; server.client_accepted();
        check(loop.parse_and_dispatch<false, 0>(c) == IoLoop::DispatchResult::Error && c->closing(),
              "NET1: real IO parser schedules inline close");
        check(c->rob().drain([](Op& op) {
            check(std::string(op.reply.data(), op.reply.size()) == "-ERR Protocol error: too big inline request\r\n",
                  "real IO parser queues exact Redis inline error");
        }) == 1, "one inline error retires in order");
        // Stand in for completion of the error reply's send; no socket or ring is started.
        loop.pending_serve_.clear(); c->set_serve_pending(false);
        loop.close_client(c); loop.reap_dead(); loop.reap_dead();
        check(buffer_frees == 1, "NET1: inline rejection frees its receive buffer");
        watched_buffer = nullptr;
    }
    static void teardown() {
        Server server; ThreadCtx self; IoLoop loop;
        loop.srv_ = &server; loop.self_ = &self;
        Client* c = new Client(-1); c->set_id(1);
        size_t avail = 0;
        check(c->read_space(65537, avail, true), "teardown fixture grew receive buffer");
        watched_buffer = c->rbuf(); buffer_frees = 0;
        server.client_accepted();
        // A recv CQE and an in-flight argv both fence reclamation, independently.
        c->set_recv_armed(true);
        Op* op = c->rob().acquire(); check(op, "teardown fixture operation"); c->rob().publish();
        loop.close_client(c);
        loop.reap_dead(); loop.reap_dead();
        check(!buffer_frees && !c->dead(), "in-flight recv and argv keep buffer alive");
        c->set_recv_armed(false); loop.close_client(c);
        check(!buffer_frees && !c->dead(), "argv still pins receive buffer after recv completion");
        op->state.store(OpState::Done); c->rob().drain([](Op&) {});
        loop.close_client(c);
        check(c->dead() && server.live_clients() == 0, "quiescent close releases connection");
        loop.reap_dead(); check(!buffer_frees, "deferred lifetime is respected");
        loop.reap_dead();
        check(buffer_frees == 1, "NET1: closed client receive buffer freed exactly once");
        watched_buffer = nullptr;
    }
};
}
#endif
int main(int argc, char** argv) {
    check(tomo::command_registry_init(false), "command registry initialized");
    const std::string which = argc > 1 ? argv[1] : "all";
    if (which == "all" || which == "inline") inline_limit();
#ifndef TOMO_NETCAP_OLD
    if (which == "all" || which == "scan") scan();
    if (which == "all" || which == "buffers") buffers();
    if (which == "all" || which == "frontier") frontier();
    if (which == "all" || which == "grammar") grammar();
    if (which == "all" || which == "framing") framing();
    if (which == "all" || which == "teardown") tomo::NetcmdRegression::teardown();
    if (which == "all" || which == "config") tomo::NetcmdRegression::config();
    if (which == "all" || which == "inline-close") tomo::NetcmdRegression::inline_close();
    std::printf("layouts Op=%zu Client=%zu ThreadCtx=%zu Shard=%zu FlatStore=%zu Rob=%zu AtomicEntry=%zu Config=%zu\n",
        sizeof(tomo::Op), sizeof(tomo::Client), sizeof(tomo::ThreadCtx), sizeof(tomo::Shard),
        sizeof(tomo::FlatStore), sizeof(tomo::Rob<64>), sizeof(tomo::AtomicEntry), sizeof(tomo::Config));
#endif
    std::printf("PASS netcap %s\n", which.c_str());
}
