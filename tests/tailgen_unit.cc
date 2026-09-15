// Serverless tests: no TCP listener and no external load generator.
#include "tools/tailgen/histogram.h"
#include "tools/tailgen/pacing.h"
#include "tools/tailgen/resp.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <sched.h>
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
        size_t serviced = 0;
        for (size_t i = 0; i < 100000; ++i) {
            const uint64_t offset = arrivals.next_offset_ns();
            require(offset == duplicate.next_offset_ns(), "arrival seed reproducibility");
            require(offset >= last_offset, "arrival schedule moved backwards");
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
    }
    // Multiple fixed workers must be phase-offset, not synchronized bursts.
    for (size_t t = 0; t < 16; ++t) {
        Arrivals fixed(200000, 16, t, Spacing::fixed, 3);
        require(fixed.next_offset_ns() == 5000 * (t + 1), "fixed worker phase");
        require(fixed.next_offset_ns() == 5000 * (t + 17), "fixed worker period");
    }
    std::fprintf(stderr, "pacing: PASS\n");
}
} // namespace

int main() {
    try { histogram(); parser(); pacing(); }
    catch (const std::exception& e) { std::fprintf(stderr, "tailgen-unit: FAIL: %s\n", e.what()); return 1; }
    std::fprintf(stderr, "tailgen-unit: PASS\n");
}
