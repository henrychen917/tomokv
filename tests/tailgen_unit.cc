// Serverless tests: no TCP listener and no external load generator.
#include "tools/tailgen/histogram.h"
#include "tools/tailgen/pacing.h"
#include "tools/tailgen/resp.h"
#include "tools/tailgen/config.h"
#include "tools/tailgen/connection.h"
#include "tools/tailgen/outstanding.h"
#include "tools/tailgen/report.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <sched.h>
#include <sstream>
#include <string>
#include <vector>

namespace {
using namespace tailgen;
void require(bool ok, const char* message) {
    if (!ok) { std::fprintf(stderr, "tailgen-unit: FAIL: %s\n", message); std::exit(1); }
}
template <class F> void rejects(F&& f, const char* message) {
    bool rejected = false;
    try { f(); } catch (const std::exception&) { rejected = true; }
    require(rejected, message);
}

void histogram() {
    Histogram whole, left, right;
    require(whole.percentile_ms(99900) == 0 && whole.mean_ms() == 0 && whole.max_ms() == 0,
            "empty histogram");
    Random rng(41);
    std::vector<uint64_t> exact;
    exact.reserve(1'000'000);
    long double sum = 0;
    for (unsigned i = 0; i < 1'000'000; ++i) {
        // Exercise every octave, microsecond rounding, zero, and the range edge.
        uint64_t ns = i % 2 ? rng.bounded(2'048'000) :
            std::min(Histogram::max_ns, (uint64_t{1} << rng.bounded(37)) + rng.bounded(1000));
        if (i == 0) ns = 0;
        if (i == 1) ns = Histogram::max_ns;
        exact.push_back(ns);
        sum += ns;
        whole.record(ns);
        (i % 2 ? left : right).record(ns);
    }
    std::sort(exact.begin(), exact.end());
    left.merge(right);
    require(whole.count() == exact.size() && left.count() == exact.size(), "histogram counts/merge");
    require(std::abs(whole.mean_ms() - static_cast<double>(sum / exact.size() / 1e6L)) < 1e-9,
            "histogram mean retains nanoseconds");
    require(whole.max_ms() == 100000 && left.max_ms() == whole.max_ms(), "histogram maximum");
    for (uint32_t p : {0, 1, 1000, 10000, 50000, 90000, 99000, 99900, 99990, 100000}) {
        const size_t rank = std::max<size_t>(1, (exact.size() * p + 99999) / 100000);
        const double reference_us = static_cast<double>(exact[rank - 1]) / 1000;
        const double got_us = whole.percentile_ms(p) * 1000;
        require(got_us + 1e-7 >= reference_us, "quantile underestimates exact nearest-rank sample");
        require(got_us - reference_us <= 1 + reference_us / 1024 + 1e-7,
                "quantile exceeds documented log-linear error");
        require(left.percentile_ms(p) == whole.percentile_ms(p), "merged quantile");
    }
    for (uint64_t us = 0; us < 2048; ++us) {
        Histogram one;
        one.record(us * 1000);
        require(one.percentile_ms(50000) == static_cast<double>(us) / 1000, "one-us resolution");
    }
    rejects([&] { whole.record(Histogram::max_ns + 1); }, "histogram overflow must fail");
    std::fprintf(stderr, "histogram: 1000000 samples vs exact sort PASS\n");
}

void parser() {
    const std::vector<std::string> frames = {
        "+OK\r\n", ":-9223372036854775808\r\n", ":+9223372036854775807\r\n",
        "$-1\r\n", "$0\r\n\r\n", std::string("$5\r\na\0\r\nb\r\n", 11),
        "-ERR wrong type\r\n", "$262144\r\n" + std::string(262144, '\xff') + "\r\n"
    };
    for (const auto& frame : frames) {
        // Every two-part split on short frames; every-byte streaming also covers
        // the entire large payload without a quadratic fixture.
        if (frame.size() < 100) for (size_t split = 0; split <= frame.size(); ++split) {
            RespParser p;
            size_t done = 0, errors = 0;
            auto reply = [&](bool error, std::string_view) { ++done; errors += error; };
            p.feed(std::string_view(frame).substr(0, split), reply);
            require(done == (split == frame.size() ? 1u : 0u), "partial frame completed early");
            p.feed(std::string_view(frame).substr(split), reply);
            require(done == 1 && p.at_boundary(), "split frame did not complete once");
            require(errors == (frame.front() == '-' ? 1u : 0u), "error reply classification");
        }
    }
    std::string stream;
    for (const auto& frame : frames) stream += frame;
    for (size_t chunk : {1u, 2u, 3u, 7u, 4096u, 300000u}) {
        RespParser p;
        size_t done = 0;
        for (size_t pos = 0; pos < stream.size(); pos += chunk)
            p.feed(std::string_view(stream).substr(pos, chunk), [&](bool, std::string_view) { ++done; });
        require(done == frames.size() && p.at_boundary(), "coalesced/streamed replies");
    }
    for (const char* bad : {"+OK\n", "+OK\rx", ":\r\n", ":--1\r\n", ":+-1\r\n",
                            ":9223372036854775808\r\n", "$-2\r\n", "$1\r\naX\n",
                            "$0\r\n\rx", "*1\r\n", ":12x\r\n"}) {
        rejects([&] { RespParser p; p.feed(bad, [](bool, std::string_view) {}); }, "malformed RESP accepted");
    }
    std::fprintf(stderr, "RESP: partial, coalesced, binary, nil, errors, malformed PASS\n");
}

void pacing() {
    // Honor taskset, then pin this single test thread to one allowed CPU.
    cpu_set_t allowed;
    CPU_ZERO(&allowed);
    require(sched_getaffinity(0, sizeof allowed, &allowed) == 0, "read pacing affinity");
    int core = 0;
    while (core < CPU_SETSIZE && !CPU_ISSET(core, &allowed)) ++core;
    require(core < CPU_SETSIZE, "no allowed pacing core");
    cpu_set_t one;
    CPU_ZERO(&one);
    CPU_SET(core, &one);
    require(sched_setaffinity(0, sizeof one, &one) == 0, "pin pacing test");

    for (Spacing spacing : {Spacing::poisson, Spacing::fixed}) {
        Arrivals arrivals(200000, 1, 0, spacing, 17), duplicate(200000, 1, 0, spacing, 17);
        const uint64_t start = now_ns() + 2'000'000;
        uint64_t first = 0, previous = 0, maximum_gap = 0, last_offset = 0;
        long double interval_sum = 0, interval_squares = 0;
        size_t serviced = 0;
        for (size_t i = 0; i < 100000; ++i) {
            const uint64_t offset = arrivals.next_offset_ns();
            require(offset == duplicate.next_offset_ns(), "arrival seed reproducibility");
            require(offset >= last_offset, "arrival schedule moved backwards");
            const long double interval = offset - last_offset;
            interval_sum += interval;
            interval_squares += interval * interval;
            last_offset = offset;
            const uint64_t actual = pace_until(start + offset, [&](uint64_t) { ++serviced; return true; });
            require(actual >= start + offset, "pacer returned before deadline");
            if (!i) first = actual;
            else maximum_gap = std::max(maximum_gap, actual - previous);
            previous = actual;
        }
        const double mean_ns = static_cast<double>(previous - first) / 99999;
        std::fprintf(stderr, "pacing %s core %d: 100000 arrivals, mean %.3f us, max gap %.3f us\n",
                     spacing == Spacing::poisson ? "poisson" : "fixed", core, mean_ns / 1000,
                     static_cast<double>(maximum_gap) / 1000);
        require(std::abs(mean_ns / 5000 - 1) < .01, "pacing mean outside 1 percent");
        require(maximum_gap <= 2'000'000, "pacing gap exceeds 2 ms (no retry or skipped assertion)");
        require(serviced > 0, "pacer never serviced replies");
        const long double planned_mean = interval_sum / 100000;
        const long double cv = std::sqrt(std::max(0.0L, interval_squares / 100000 - planned_mean * planned_mean)) / planned_mean;
        require(spacing == Spacing::poisson ? std::abs(cv - 1) < .03 : cv == 0,
                "Poisson must have exponential inter-arrivals; fixed must be evenly spaced");
    }
    // Multiple fixed workers must be phase-offset, not synchronized bursts.
    for (size_t t = 0; t < 16; ++t) {
        Arrivals fixed(200000, 16, t, Spacing::fixed, 3);
        require(fixed.next_offset_ns() == 5000 * (t + 1), "fixed worker phase");
        require(fixed.next_offset_ns() == 5000 * (t + 17), "fixed worker period");
    }
    std::fprintf(stderr, "pacing: PASS\n");
}

void workload() {
    auto short_keys = KeySpace::parse("memtier-{1..11}", "unused");
    auto long_keys = KeySpace::parse("blocker:memtier-{1..3}", "unused");
    Workload mix("GET:8,BITCOUNT:2", short_keys, long_keys);
    Random first(99), second(99);
    size_t long_count = 0;
    std::vector<bool> short_seen(11), long_seen(3);
    for (size_t i = 0; i < 100000; ++i) {
        std::string a, b;
        const auto kind = mix.render(first, a);
        require(mix.render(second, b) == kind && a == b, "seeded commands/keys differ");
        long_count += kind == CommandClass::long_op;
        if (kind == CommandClass::short_op) {
            require(a.starts_with("*2\r\n$3\r\nGET\r\n"), "GET framing");
            for (unsigned key = 1; key <= 11; ++key)
                if (a.ends_with("memtier-" + std::to_string(key) + "\r\n")) short_seen[key - 1] = true;
        } else {
            require(a.starts_with("*2\r\n$8\r\nBITCOUNT\r\n"), "BITCOUNT framing");
            for (unsigned key = 1; key <= 3; ++key)
                if (a.ends_with("blocker:memtier-" + std::to_string(key) + "\r\n")) long_seen[key - 1] = true;
        }
    }
    require(long_count > 19500 && long_count < 20500, "8:2 weighted mixture");
    require(std::all_of(short_seen.begin(), short_seen.end(), [](bool x) { return x; }) &&
            std::all_of(long_seen.begin(), long_seen.end(), [](bool x) { return x; }), "key endpoints reached");
    std::string request;
    Workload set("SET 3:1", KeySpace::parse("memtier-{1..1}", ""), long_keys);
    require(set.render(first, request) == CommandClass::short_op &&
            request == "*3\r\n$3\r\nSET\r\n$9\r\nmemtier-1\r\n$3\r\nxxx\r\n", "SET payload/frame");
    Workload ping("GET:0,PING:1", short_keys, long_keys);
    require(ping.render(first, request) == CommandClass::short_op && request == "*1\r\n$4\r\nPING\r\n", "PING/zero weight");
    for (const char* bad : {"GET:0", "GET:1,", "SET:1", "SET -1:1", "GET:nan", "BOGUS:1",
                            "GET:18446744073709551615,PING:1"})
        rejects([&] { Workload invalid(bad, short_keys, long_keys); }, "invalid mix accepted");
    for (const char* bad : {"0", "memtier-{2..1}", "memtier-{1..N}", "a{1..2}{3..4}", "a{1..2"})
        rejects([&] { KeySpace::parse(bad, ""); }, "invalid key range accepted");
    const auto numeric = KeySpace::parse("2000000", "memtier-");
    require(numeric.first == 1 && numeric.count == 2000000 && numeric.prefix == "memtier-", "numeric key count");
    for (const char* bad : {"--bogus=1", "--rate=0", "--warmup=-1", "--duration=nan", "--port=65536",
                            "--threads=0", "--conns=0", "--seed=-1", "--spacing=tick", "--mix=GET:0"}) {
        const char* argv[] = {"tailgen", bad};
        rejects([&] { parse_config(2, argv); }, "invalid CLI accepted");
    }
    const char* argv[] = {"tailgen", "--rate=717000", "--warmup", "0", "--mix", "PING:1", "--max-outstanding=0"};
    const auto config = parse_config(7, argv);
    require(config.rate == 717000 && config.warmup == 0 && config.max_outstanding == 0, "CLI values/defaults");
    require(core_list("112,114-116") == std::vector<int>({112, 114, 115, 116}), "core list expansion");
    for (const char* bad : {"1,1", "2-1", "1,", "1024", ""})
        rejects([&] { core_list(bad); }, "invalid core list accepted");
    std::fprintf(stderr, "workload/CLI: deterministic mix, key ranges, command framing, validation PASS\n");
}

void outstanding() {
    Outstanding a(2, 2, 100, 200), b(1, 1, 100, 200);
    a.add(0, 80); a.add(0, 81); a.add(0, 90); // over before warmup ends
    a.complete(0, 120); // [100,120)
    a.add(1, 130); a.add(1, 131); a.add(1, 140);
    a.add(0, 150); // both connections over: one continuous [140,190)
    a.complete(1, 160); a.complete(0, 190);
    b.add(0, 100); b.add(0, 110); b.complete(0, 145); // overlaps two intervals
    b.add(0, 195); b.complete(0, 220); // clip drain at 200
    std::vector<Interval> all = a.finish();
    const auto& more = b.finish();
    all.insert(all.end(), more.begin(), more.end());
    require(union_ns(all) == 95, "union must be [100,190) + [195,200), not a sum/average");
    require(a.maximum() == 3 && b.maximum() == 2, "per-connection peak in measurement window");
    Outstanding disabled(1, 0, 100, 200);
    for (unsigned i = 0; i < 1000; ++i) disabled.add(0, 150);
    require(disabled.total() == 1000 && disabled.maximum() == 1000 && disabled.finish().empty(),
            "zero threshold disables observer without bounding outstanding");
    Outstanding warm(1, 64, 100, 200);
    for (unsigned i = 0; i < 200; ++i) warm.add(0, 10);
    for (unsigned i = 0; i < 198; ++i) warm.complete(0, 20);
    require(warm.finish().empty() && warm.maximum() == 2, "exclude warmup peak; capture unchanged boundary backlog");
    std::fprintf(stderr, "outstanding: unbounded, warmup/drain clipping, global interval union PASS\n");
}

void connections() {
    int sockets[2];
    require(socketpair(AF_UNIX, SOCK_STREAM | SOCK_NONBLOCK | SOCK_CLOEXEC, 0, sockets) == 0, "socketpair");
    Connection connection{File(sockets[0])};
    File peer(sockets[1]);
    int small = 1024;
    require(setsockopt(connection.fd(), SOL_SOCKET, SO_SNDBUF, &small, sizeof small) == 0, "small send buffer");
    // This is a socket stream fixture, not a server. Force partial writes and
    // EAGAIN, then compare every drained byte and each reply's FIFO metadata.
    std::string expected;
    for (uint64_t i = 0; i < 200; ++i) {
        const std::string bytes(4096, static_cast<char>('a' + i % 26));
        expected += bytes;
        connection.submit(bytes, {i, i % 2 ? CommandClass::long_op : CommandClass::short_op, i >= 10});
    }
    require(connection.outstanding() == 200 && connection.wants_write() && connection.queued_bytes() > 0,
            "fixture must actually open socket-backpressure window beyond 64 outstanding");
    std::string received;
    char buffer[8192];
    for (unsigned round = 0; round < 10000 && (connection.wants_write() || received.size() != expected.size()); ++round) {
        const ssize_t n = recv(peer.get(), buffer, sizeof buffer, MSG_DONTWAIT);
        if (n > 0) received.append(buffer, static_cast<size_t>(n));
        else require(n < 0 && (errno == EAGAIN || errno == EWOULDBLOCK), "fixture recv");
        connection.write_ready();
    }
    require(received == expected && !connection.queued_bytes(), "partial writes changed/lost/duplicated stream bytes");
    size_t replies = 0;
    auto completed = [&](Request request, uint64_t stamp, bool error, std::string_view) {
        require(request.sent_ns == replies && stamp > request.sent_ns && !error, "FIFO request/timestamp matching");
        require(request.kind == (replies % 2 ? CommandClass::long_op : CommandClass::short_op) &&
                request.measured == (replies >= 10), "class/warmup metadata pairing");
        ++replies;
    };
    require(send(peer.get(), "$3\r\na", 5, MSG_NOSIGNAL) == 5, "fixture partial bulk send");
    connection.read_ready(completed);
    require(!replies && connection.outstanding() == 200, "partial bulk prematurely reduced outstanding");
    require(send(peer.get(), "bc\r\n", 4, MSG_NOSIGNAL) == 4, "fixture bulk completion");
    connection.read_ready(completed);
    std::string responses;
    for (size_t i = 1; i < 200; ++i) responses += i % 2 ? ":7\r\n" : "+OK\r\n";
    require(send(peer.get(), responses.data(), responses.size(), MSG_NOSIGNAL) == static_cast<ssize_t>(responses.size()),
            "fixture coalesced replies");
    connection.read_ready(completed);
    require(replies == 200 && !connection.outstanding(), "all replies retire independently");
    require(send(peer.get(), "+OK\r\n", 5, MSG_NOSIGNAL) == 5, "fixture unsolicited reply");
    rejects([&] { connection.read_ready(completed); }, "unsolicited reply must fail");
    peer = File();
    rejects([&] { connection.read_ready(completed); }, "EOF must fail");
    std::fprintf(stderr, "connection: forced partial writes/EAGAIN, >64 in flight, FIFO, partial reads, EOF PASS\n");
}

void json_contract() {
    Histogram short_latency, long_latency;
    short_latency.record(1000); short_latency.record(3000); long_latency.record(2000);
    std::ostringstream out;
    write_json(out, short_latency, long_latency, 2'000'000'000, 65, .25);
    // Independent tiny oracle, including units, the eleven keys, and the
    // distinction between short p99.9, combined mean and measurement rate.
    const char* expected = R"({"rate":1.5,"latency_ms":0.002,"p999_ms":0.003,"long_p999_ms":0.002,"short_count":2,"long_count":1,"short":{"count":2,"mean_ms":0.002,"p50_ms":0.001,"p90_ms":0.003,"p99_ms":0.003,"p999_ms":0.003,"p9999_ms":0.003,"max_ms":0.003},"long":{"count":1,"mean_ms":0.002,"p50_ms":0.002,"p90_ms":0.002,"p99_ms":0.002,"p999_ms":0.002,"p9999_ms":0.002,"max_ms":0.002},"outstanding_max":65,"over_max_outstanding_fraction":0.25,"window_seconds":2})";
    require(out.str() == std::string(expected) + '\n', "JSON harness contract");
    std::fprintf(stderr, "JSON: exact schema, units, sample counts, cohort rate PASS\n");
}
} // namespace

int main() {
    try { histogram(); parser(); workload(); outstanding(); connections(); json_contract(); pacing(); }
    catch (const std::exception& e) { std::fprintf(stderr, "tailgen-unit: FAIL: %s\n", e.what()); return 1; }
    std::fprintf(stderr, "tailgen-unit: PASS\n");
}
