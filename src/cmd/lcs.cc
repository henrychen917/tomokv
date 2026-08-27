// lcs.cc — the LCS dynamic program, its option grammar, and its reply shapes.
//
// Reply shapes were established by byte-probing a vanilla redis 7.4 binary; no redis source was
// read. Note the two non-obvious ones:
//   - matches are emitted from the END of both strings backwards, not in reading order;
//   - MINMATCHLEN filters the emitted runs but does NOT change the reported `len`.
//
// THE SIZE HAZARD IS REAL AND IS NOT PAPERED OVER. The table is n*m cells. Redis refuses the
// command when the product overflows what it can index, and we refuse at the same boundary so the
// differ stays exact; below it, both servers simply burn the CPU.
#include "lcs.h"

#include "command.h"
#include "../base/slice.h"
#include "../exec/op.h"
#include "../net/resp.h"

#include <cstring>
#include <new>

namespace tomo {
namespace {

bool parse_u64(Slice s, uint64_t& out) {
    if (!s.n) return false;
    // Canonical decimal, as redis's string2ll: a leading zero is only legal as the whole number,
    // so "MINMATCHLEN 05" is an integer error rather than a filter of 5.
    if (s.p[0] == '0' && s.n != 1) return false;
    uint64_t value = 0;
    for (uint32_t i = 0; i < s.n; i++) {
        const char ch = s.p[i];
        if (ch < '0' || ch > '9') return false;
        const uint64_t digit = static_cast<uint64_t>(ch - '0');
        // Bound at INT64_MAX, not UINT64_MAX: redis parses this argument as a signed long long.
        if (value > (static_cast<uint64_t>(INT64_MAX) - digit) / 10) return false;
        value = value * 10 + digit;
    }
    out = value;
    return true;
}

// MINMATCHLEN accepts a negative value and treats it as no filter, exactly as redis does. The
// magnitude still has to be a canonical decimal, and "-0" is not one.
bool parse_minmatchlen(Slice s, uint64_t& out) {
    // The magnitude is a signed 64-bit integer on redis, so anything past INT64_MAX is an integer
    // error rather than a very large filter.
    if (s.n > 19) return false;
    if (s.n && s.p[0] == '-') {
        uint64_t ignored = 0;
        if (s.n == 2 && s.p[1] == '0') return false;
        if (!parse_u64(Slice(s.p + 1, s.n - 1), ignored)) return false;
        out = 0;
        return true;
    }
    return parse_u64(s, out);
}

}  // namespace

bool lcs_parse_options(Op& op, LcsOptions& out) {
    out = LcsOptions{};
    for (uint32_t i = 3; i < op.argc(); i++) {
        if (op.arg(i).eq_icase("len")) {
            out.len = true;
        } else if (op.arg(i).eq_icase("idx")) {
            out.idx = true;
        } else if (op.arg(i).eq_icase("withmatchlen")) {
            out.withmatchlen = true;
        } else if (op.arg(i).eq_icase("minmatchlen")) {
            if (i + 1 >= op.argc()) { reply_syntax(op.sink()); return false; }
            if (!parse_minmatchlen(op.arg(i + 1), out.minmatchlen)) {
                reply_err(op.sink(), "ERR value is not an integer or out of range");
                return false;
            }
            i++;
        } else {
            reply_syntax(op.sink());
            return false;
        }
    }
    if (out.len && out.idx) {
        reply_err(op.sink(),
                  "ERR If you want both the length and indexes, please just use IDX.");
        return false;
    }
    return true;
}

bool lcs_compute(const std::string& a, const std::string& b, const LcsOptions& options,
                 LcsResult& out, const char*& error) {
    out = LcsResult{};
    error = nullptr;
    const size_t n = a.size(), m = b.size();
    if (n == 0 || m == 0) return true;
    // Redis refuses inputs whose product cannot be indexed rather than thrashing; matching the
    // boundary keeps the differ exact on the refusal as well as on the answer.
    if (n > UINT32_MAX / (m ? m : 1)) {
        error = "ERR String too long for LCS";
        return false;
    }

    // (n+1) x (m+1) of uint32_t. The traceback needs the whole table, so there is no two-row trick
    // available for the IDX forms; LEN-only could use one, but keeping a single code path means
    // the answer can never differ between the forms.
    const size_t rows = n + 1, cols = m + 1;
    if (rows > SIZE_MAX / cols || rows * cols > SIZE_MAX / sizeof(uint32_t)) {
        error = "ERR String too long for LCS";
        return false;
    }
    uint32_t* table = nullptr;
    try {
        table = new uint32_t[rows * cols]();
    } catch (const std::bad_alloc&) {
        error = "ERR Insufficient memory, failed allocating transient memory for LCS";
        return false;
    }
    auto at = [&](size_t i, size_t j) -> uint32_t& { return table[i * cols + j]; };

    for (size_t i = 1; i <= n; i++)
        for (size_t j = 1; j <= m; j++)
            at(i, j) = (a[i - 1] == b[j - 1])
                ? at(i - 1, j - 1) + 1
                : (at(i - 1, j) >= at(i, j - 1) ? at(i - 1, j) : at(i, j - 1));

    out.length = at(n, m);

    // Traceback from the bottom-right corner. Emitting as we walk gives redis's ordering for free:
    // the first reported match is the one nearest the end of both strings.
    const bool want_value = !options.len && !options.idx;
    std::string reversed;
    if (want_value) reversed.reserve(out.length);
    size_t i = n, j = m;
    uint32_t run_end_a = 0, run_end_b = 0, run = 0;
    auto flush_run = [&]() {
        if (!run) return;
        if (options.idx && run >= options.minmatchlen) {
            LcsMatch match;
            match.a_end = run_end_a;
            match.b_end = run_end_b;
            match.a_start = run_end_a + 1 - run;
            match.b_start = run_end_b + 1 - run;
            match.length = run;
            out.matches.push_back(match);
        }
        run = 0;
    };
    while (i > 0 && j > 0) {
        if (a[i - 1] == b[j - 1]) {
            if (want_value) reversed.push_back(a[i - 1]);
            if (!run) { run_end_a = static_cast<uint32_t>(i - 1); run_end_b = static_cast<uint32_t>(j - 1); }
            run++;
            i--; j--;
            continue;
        }
        flush_run();
        if (at(i - 1, j) > at(i, j - 1)) i--;
        else j--;
    }
    flush_run();
    delete[] table;

    if (want_value) {
        out.value.assign(reversed.rbegin(), reversed.rend());
    }
    return true;
}

void lcs_reply(Op& op, const LcsOptions& options, const LcsResult& result) {
    auto sink = op.sink();
    if (options.idx) {
        reply_map_header(sink, 2, op.resp3());
        reply_bulk(sink, Slice("matches", 7));
        reply_array_header(sink, result.matches.size());
        for (const LcsMatch& match : result.matches) {
            reply_array_header(sink, options.withmatchlen ? 3 : 2);
            reply_array_header(sink, 2);
            reply_int(sink, match.a_start);
            reply_int(sink, match.a_end);
            reply_array_header(sink, 2);
            reply_int(sink, match.b_start);
            reply_int(sink, match.b_end);
            if (options.withmatchlen) reply_int(sink, match.length);
        }
        reply_bulk(sink, Slice("len", 3));
        reply_int(sink, static_cast<long long>(result.length));
        return;
    }
    if (options.len) { reply_int(sink, static_cast<long long>(result.length)); return; }
    reply_bulk(sink, Slice(result.value.data(), static_cast<uint32_t>(result.value.size())));
}

namespace {
static const CommandSpec kTable[] = {
    // Two string keys, read-only, lowered by the scatter engine exactly like the other two-key
    // reads. min_arity 3 is `LCS k1 k2`; the trailing options are unbounded.
    {"LCS", 3, -1, CmdFlags::Readonly | CmdFlags::MultiShard, cmd_xshard_only, 1, 2, 1},
};
}  // namespace

CommandTable lcs_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
