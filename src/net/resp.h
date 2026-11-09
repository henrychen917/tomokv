// RESP2 request parsing and reply formatting shared by transport, command and persistence code.
// Parsing requires caller-owned Op/frontier state and stable input bytes; ordinary arguments
// borrow the input buffer, while quoted inline arguments own decoded bytes in Op's argv block.
// Reply helpers write a caller-owned sink or record a code for later formatting. resp3.h is
// included after these builders to supply protocol-selecting overloads.
//
// Patterned on the protocol as documented and as implemented in redis-7.2 / valkey (BSD-3). Nothing
// here is copied from our own Redis 8.6.2 fork, which carries RSALv2/SSPLv1 and would contaminate
// the licence of this tree.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <charconv>
#include <cstdlib>
#include <cmath>
#include "../base/numeric.h"
#include "../base/slice.h"
#include "../exec/op.h"
#include "errorstats.h"

namespace tomo {

// RESP line payloads are caller text, even when they originated as bulk strings.
// Formatted errors trim terminal CR/LF before mapping; Redis's safe-SDS errors
// and safe status replies map every CR/LF, including terminal ones.
template <bool Trim = true, typename Buf>
inline void reply_line_text(Buf&& b, const char* text, size_t len) {
    if constexpr (Trim)
        while (len && (text[len - 1] == '\r' || text[len - 1] == '\n')) --len;
    size_t start = 0;
    for (size_t i = 0; i < len; ++i) {
        if (text[i] != '\r' && text[i] != '\n') continue;
        b.append(text + start, i - start);
        b.push_back(' ');
        start = i + 1;
    }
    if (start < len) b.append(text + start, len - start);
}
template <typename Buf>
[[gnu::cold, gnu::noinline]]
void reply_err_unaccounted(Buf&& b, const char* msg, size_t len, bool trim = true) {
    b.push_back('-');
    if (trim)
        reply_line_text(b, msg, len);
    else
        reply_line_text<false>(b, msg, len);
    b.append("\r\n", 2);
}
template <typename Buf>
[[gnu::cold, gnu::noinline]]
void reply_err(Buf&& b, const char* msg, size_t len, bool trim = true) {
    error_stats_record(msg, len, trim);
    reply_err_unaccounted(b, msg, len, trim);
}
template <typename Buf>
inline void reply_err(Buf&& b, const char* msg) {
    error_stats_record(msg, std::strlen(msg));
    b.push_back('-');
    reply_line_text(b, msg, std::strlen(msg));
    b.append("\r\n", 2);
}
template <typename Buf>
[[gnu::cold, gnu::noinline]]
void reply_simple(Buf&& b, const char* msg, size_t len) {
    b.push_back('+');
    reply_line_text<false>(b, msg, len);
    b.append("\r\n", 2);
}
template <typename Buf>
inline void reply_simple(Buf&& b, const char* msg) {
    reply_simple(b, msg, std::strlen(msg));
}

enum class ParseResult { Ok, Incomplete, Error, Empty };

// Redis 7.4's PROTO_INLINE_MAX_SIZE is a fixed protocol bound, not a CONFIG knob.
inline constexpr uint32_t kProtoInlineMaxSize = 64 * 1024;

// Detect quotes that require the allocating decoder. Backslashes outside quotes are literal bytes.
__attribute__((noinline, cold)) inline bool resp_inline_plain(const char* p, const char* end) {
    for (; p != end && *p; ++p)
        if (*p == '"' || *p == '\'') return false;
    return true;
}

// Stateless quoted-inline decoder used by resp_parse_inline. The caller exclusively owns Op
// and output storage; split borrows input, and decode transfers one malloc block to Op on success.
// No state is published to other threads here; syntax/allocation failures become ParseResult::Error.
struct RespInlineDecoder {
    static bool space(unsigned char c) { return c == ' ' || (c >= '\t' && c <= '\r'); }
    static int hex(unsigned char c) {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return c - 'a' + 10;
        if (c >= 'A' && c <= 'F') return c - 'A' + 10;
        return -1;
    }

    // Validate/count with null outputs, then decode into the caller's args/bytes block on a
    // second pass. decode supplies argc Slice slots and at least end-p payload bytes. Input and
    // reply storage are untouched. Args are immutable after parsing: executors and the read-local
    // conflict predicate can read a live op's argv concurrently, so commands that build another
    // argv use a separate Op (e.g. EXEC).
    // The parsing caller serializes these local writes; malformed quotes return false, possibly
    // after partial output. There is no allocation, publication or waiting in this routine.
    [[gnu::cold, gnu::noinline]] static bool split(const char* p, const char* end, Slice* args,
                                                   char* bytes, uint32_t& argc) {
        argc = 0;
        uint32_t written = 0;
        while (p != end) {
            while (p != end && space(*p)) ++p;
            if (p == end) break;
            const uint32_t begin = written;
            char quote = 0;
            for (;;) {
                if (p == end) {
                    if (quote) return false;
                    break;
                }
                char c = *p++;
                if (quote) {
                    if (c == quote) {
                        if (p != end && !space(*p)) return false;
                        break;
                    }
                    if (c == '\\' && p != end) {
                        if (quote == '"') {
                            c = *p++;
                            if (c == 'x' && end - p >= 2 && hex(p[0]) >= 0 && hex(p[1]) >= 0) {
                                c = static_cast<char>(hex(p[0]) * 16 + hex(p[1]));
                                p += 2;
                            } else
                                switch (c) {
                                    case 'n':
                                        c = '\n';
                                        break;
                                    case 'r':
                                        c = '\r';
                                        break;
                                    case 't':
                                        c = '\t';
                                        break;
                                    case 'b':
                                        c = '\b';
                                        break;
                                    case 'a':
                                        c = '\a';
                                        break;
                                }
                        } else if (*p == '\'')
                            c = *p++;
                    }
                } else {
                    if (c == ' ' || c == '\t' || c == '\r' || c == '\n') break;
                    if (c == '"' || c == '\'') {
                        quote = c;
                        continue;
                    }
                }
                if (bytes) bytes[written] = c;
                ++written;
            }
            if (args) args[argc] = Slice(bytes + begin, written - begin);
            ++argc;
        }
        return true;
    }

    [[gnu::cold, gnu::noinline]] static ParseResult decode(const char* p, const char* end, Op& op,
                                                           const char** err) {
        uint32_t argc;
        if (!split(p, end, nullptr, nullptr, argc)) {
            *err = "ERR Protocol error: unbalanced quotes in request";
            return ParseResult::Error;
        }
        auto* args = static_cast<Slice*>(std::malloc(size_t(argc) * sizeof(Slice) + (end - p)));
        if (!args) {
            *err = "ERR out of memory parsing inline command";
            return ParseResult::Error;
        }
        split(p, end, args, reinterpret_cast<char*>(args + argc), argc);
        std::free(op.argv_heap_);
        op.argv_heap_ = args;
        op.argv_cap_ = op.argc_ = argc;
        return argc ? ParseResult::Ok : ParseResult::Empty;
    }
};

// `scanned` is relative to the unconsumed request, so quiescent buffer compaction and
// connection migration preserve it. Scan for LF, trimming an optional CR. No bytes
// are copied or changed: argv can still point into the append-only receive buffer.
inline ParseResult resp_parse_inline(const char* buf, uint32_t len, uint32_t& pos, Op& op,
                                     const char** err, uint32_t& scanned) {
    const uint32_t available = len - pos;
    uint32_t i = scanned;
    for (; i < available; ++i) {
#ifdef TOMO_NETCAP_TEST
        extern uint64_t netcap_scan_bytes;
        ++netcap_scan_bytes;
#endif
        if (buf[pos + i] == '\n' || buf[pos + i] == '\0') break;
    }
    if (i == available || buf[pos + i] == '\0') {
        scanned = i;
        if (available > kProtoInlineMaxSize) {
            *err = "ERR Protocol error: too big inline request";
            return ParseResult::Error;
        }
        return ParseResult::Incomplete;
    }
    const uint32_t next = pos + i + 1;
    const uint32_t eol = pos + i - (i && buf[pos + i - 1] == '\r');
    scanned = 0;  // A dispatch refusal may parse this complete frame again.
    if (!resp_inline_plain(buf + pos, buf + eol)) {
        const auto result = RespInlineDecoder::decode(buf + pos, buf + eol, op, err);
        if (result != ParseResult::Error) pos = next;
        return result;
    }
    i = pos;
    while (i < eol) {
        while (i < eol && RespInlineDecoder::space(buf[i])) ++i;
        const uint32_t begin = i;
        while (i < eol && buf[i] != ' ' && buf[i] != '\t' && buf[i] != '\r') ++i;
        if (i > begin && !op.push_arg(Slice(buf + begin, i - begin))) {
            *err = "ERR out of memory parsing inline command";
            return ParseResult::Error;
        }
    }
    pos = next;
    return op.argc() ? ParseResult::Ok : ParseResult::Empty;
}

[[gnu::cold, gnu::noinline]] inline const char* resp_expected_bulk_error(char actual, Op& op) {
    // Used immediately by the owning parser; thread-local storage avoids changing Op
    // or carrying a formatting buffer through every ordinary RESP parse.
    thread_local char message[] = "ERR Protocol error: expected '$', got '?'";
    message[sizeof(message) - 3] = actual;
    // Redis preserves even a NUL offending byte in this error. Its wire length cannot
    // be recovered with strlen; stage this cold error using the known literal size.
    reply_err(op.reply, message, sizeof(message) - 1);
    return message;
}

// Redis waits for the first CR and one following byte before validating a count.
// In particular, malformed digits without CR are incomplete until the 64 KiB
// bound (including the '*'/'$' prefix); a CR at the very end is still incomplete.
// Redis's search stops at NUL and does not check that the byte after CR is LF.
__attribute__((noinline, cold)) inline ParseResult resp_count_line(const char* buf, uint32_t len,
                                                                   uint32_t start, uint32_t& end,
                                                                   bool multibulk,
                                                                   const char** err) {
    end = start;
    while (end < len && buf[end] && buf[end] != '\r') ++end;
    if (end == len || !buf[end]) {
        if (len - start <= kProtoInlineMaxSize) return ParseResult::Incomplete;
        *err = multibulk ? "ERR Protocol error: too big mbulk count string"
                         : "ERR Protocol error: too big bulk count string";
        return ParseResult::Error;
    }
    return end + 1 < len ? ParseResult::Ok : ParseResult::Incomplete;
}

__attribute__((noinline, cold)) inline ParseResult resp_length_slow(const char* buf, uint32_t len,
                                                                    uint32_t& pos, uint64_t maxv,
                                                                    uint64_t& out, bool multibulk,
                                                                    const char** err) {
    uint32_t end;
    const auto line = resp_count_line(buf, len, pos - 1, end, multibulk, err);
    if (line != ParseResult::Ok) return line;
    const char* invalid = multibulk ? "ERR Protocol error: invalid multibulk length"
                                    : "ERR Protocol error: invalid bulk length";
    const uint32_t first = pos + (pos < end && buf[pos] == '-');
    int64_t value = 0;
    // from_chars supplies signed overflow checking; the first-digit rule supplies
    // string2ll's stricter grammar (no +, whitespace, -0 or redundant zeroes).
    const bool zero = end == pos + 1 && buf[pos] == '0';
    if (!zero && (first >= end || buf[first] < '1' || buf[first] > '9')) {
        *err = invalid;
        return ParseResult::Error;
    }
    const auto parsed = std::from_chars(buf + pos, buf + end, value);
    if (parsed.ec != std::errc{} || parsed.ptr != buf + end ||
        (multibulk ? value > INT32_MAX : value < 0)) {
        *err = invalid;
        return ParseResult::Error;
    }
    // The ordinary parser uses an immediate bound of 1 Mi. Larger counts
    // take this cold continuation, up to Redis's INT_MAX; no eager argv reserve.
    if (multibulk && maxv == 1024 * 1024) maxv = INT32_MAX;
    if (value > 0 && static_cast<uint64_t>(value) > maxv) {
        *err = invalid;
        return ParseResult::Error;
    }
    out = value > 0 ? static_cast<uint64_t>(value) : 0;
    pos = end + 2;
    return ParseResult::Ok;
}

__attribute__((noinline, cold)) inline ParseResult resp_bulk_prefix_error(const char* buf,
                                                                          uint32_t len,
                                                                          uint32_t pos, Op& op,
                                                                          const char** err) {
    uint32_t end;
    const auto line = resp_count_line(buf, len, pos, end, false, err);
    if (line != ParseResult::Ok) return line;
    *err = resp_expected_bulk_error(buf[pos], op);
    return ParseResult::Error;
}

// The pre-AUTH fast bound uses 10 / 16384. On its error exit,
// distinguish a valid-but-unauthenticated length from invalid syntax/overflow
// or the configured bulk ceiling, which Redis checks first. Reuse the strict
// decoder on at most ten headers; completed payloads are only stepped over.
// This error-only helper leaves the ordinary parser and resumable frontier interfaces separate.
[[gnu::cold, gnu::noinline]] inline const char* resp_preauth_error(const char* buf, uint32_t len,
                                                                   uint32_t start,
                                                                   uint64_t max_bulk,
                                                                   const char* original) {
    if (start >= len || buf[start] != '*') return original;
    uint32_t p = start + 1;
    uint64_t count = 0;
    const char* error = original;
    auto result = resp_length_slow(buf, len, p, INT32_MAX, count, true, &error);
    if (result == ParseResult::Error) return error;
    if (result != ParseResult::Ok) return original;
    if (count > 10) return "ERR Protocol error: unauthenticated multibulk length";
    for (uint64_t a = 0; a < count; ++a) {
        if (p >= len || buf[p] != '$') return original;
        ++p;
        uint64_t bulk = 0;
        result = resp_length_slow(buf, len, p, max_bulk, bulk, false, &error);
        if (result == ParseResult::Error) return error;
        if (result != ParseResult::Ok) return original;
        if (bulk > 16384) return "ERR Protocol error: unauthenticated bulk length";
        if (uint64_t(p) + bulk + 2 > len) return original;
        p += static_cast<uint32_t>(bulk) + 2;
    }
    return original;
}

// An exceptional header finishes the entire request here, never returning into
// the ordinary parser's argument loop. The already parsed argv prefix is kept:
// resetting Op would discard the connection flags captured by ROB acquisition.
// Only receive-buffer slices are replayed; no receive byte is copied or changed.
[[gnu::cold, gnu::noinline]] inline ParseResult resp_parse_slow(const char* buf, uint32_t len,
                                                                uint32_t& pos, Op& op,
                                                                const char** err,
                                                                uint64_t max_multibulk,
                                                                uint64_t max_bulk) {
    uint32_t p = pos + 1;
    uint64_t nargs = 0;
    auto r = resp_length_slow(buf, len, p, max_multibulk, nargs, true, err);
    if (r != ParseResult::Ok) return r;
    if (nargs == 0) {
        pos = p;
        return ParseResult::Empty;
    }
    const uint32_t parsed = op.argc();
    for (uint64_t a = 0; a < nargs; ++a) {
        if (p >= len) return ParseResult::Incomplete;
        if (buf[p] != '$') return resp_bulk_prefix_error(buf, len, p, op, err);
        ++p;
        uint64_t blen = 0;
        r = resp_length_slow(buf, len, p, max_bulk, blen, false, err);
        if (r != ParseResult::Ok) return r;
        if (p + blen + 2 > len) return ParseResult::Incomplete;
        if (a >= parsed && !op.push_arg(Slice(buf + p, static_cast<uint32_t>(blen)))) {
            *err = "ERR out of memory parsing command";
            return ParseResult::Error;
        }
        p += static_cast<uint32_t>(blen) + 2;
    }
    pos = p;
    return ParseResult::Ok;
}

// Keep constant-limit arguments out of the ordinary parser's calling convention.
// This wrapper and its extra call exist only on the exceptional exit.
[[gnu::cold, gnu::noinline]] inline ParseResult resp_parse_unlimited_slow(const char* buf,
                                                                          uint32_t len,
                                                                          uint32_t& pos, Op& op,
                                                                          const char** err) {
    return resp_parse_slow(buf, len, pos, op, err, 1024 * 1024, 512ull * 1024 * 1024);
}

// Read positive decimal digits followed by CRLF and advance pos on Ok. The fast grammar excludes
// signs, leading zeroes, whitespace, base selection and locale rules. Empty/truncated input is
// Incomplete; zero, negatives and exceptional syntax go through resp_length_slow at the call site.
// The maxv check prevents overflow provided maxv <= (UINT64_MAX - 9) / 10. Bulk-length callers
// cap this fast bound at 512 MiB and let resp_length_slow apply a larger configured limit.
inline ParseResult parse_len_crlf(const char* buf, uint32_t len, uint32_t& pos, uint64_t maxv,
                                  uint64_t& out) {
    uint32_t i = pos;
    if (i >= len) return ParseResult::Incomplete;
    // Peel the first digit so its range check rejects zero as well as
    // nondigits. Later digits keep the '0'..'9' check. The cold parser handles
    // lone zero, negatives, incomplete malformed headers and exact error text.
    const char first = buf[i];
    if (first < '1' || first > '9') return ParseResult::Error;
    uint64_t v = static_cast<uint64_t>(first - '0');
    if (v > maxv) return ParseResult::Error;
    ++i;
    while (i < len) {
        const char c = buf[i];
        if (c == '\r') {
            if (i + 1 >= len) return ParseResult::Incomplete;
            if (buf[i + 1] != '\n') return ParseResult::Error;
            pos = i + 2;
            out = v;
            return ParseResult::Ok;
        }
        if (c < '0' || c > '9') return ParseResult::Error;
        v = v * 10 + static_cast<uint64_t>(c - '0');
        if (v > maxv) return ParseResult::Error;
        i++;
    }
    return ParseResult::Incomplete;
}

// Incomplete multibulks retain an argv frontier. All positions are
// relative to the unconsumed frame, including saved arguments: neither realloc
// nor quiescent compaction nor an IO-owner transfer can invalidate them. The
// active bit shares Client's inline cursor; its consume store resets
// both protocols, without adding stores to complete-frame dispatch.
inline constexpr uint32_t kRespMultibulkPending = uint32_t{1} << 31;
// Owns a realloc-grown array of frame-relative argument offsets, not receive bytes. The parsing
// caller serializes access and must not shallow-copy this owning object. push returns false on
// allocation failure with prior storage intact; finish resets progress and frees capacity over 512.
// There is no cross-thread publication inside this type; Client migration transfers its state.
struct RespFrontier {
    struct Arg {
        uint32_t offset, length;
    };
    Arg* args = nullptr;
    uint32_t capacity = 0;
    uint32_t expected = 0;
    uint32_t completed = 0;
    uint32_t next = 0;
    uint64_t bulk = UINT64_MAX;  // known length: next names its payload, else '$'

    ~RespFrontier() { std::free(args); }
    bool push(uint32_t offset, uint32_t length) {
        if (completed == capacity) {
            const uint32_t cap = capacity ? capacity * 2 : 16;
            auto* grown = static_cast<Arg*>(std::realloc(args, size_t(cap) * sizeof(Arg)));
            if (!grown) return false;
            args = grown;
            capacity = cap;
        }
        args[completed++] = {offset, length};
        return true;
    }
    void finish() {
        expected = completed = next = 0;
        bulk = UINT64_MAX;
        // As with Op::shrink, release burst argv growth at completion/close.
        if (capacity > 512) {
            std::free(args);
            args = nullptr;
            capacity = 0;
        }
    }
};
static_assert(sizeof(RespFrontier) == 32);

[[gnu::cold, gnu::noinline]] inline ParseResult resp_suspend(RespFrontier& saved, const char* frame,
                                                             Op& op, const char** err,
                                                             uint32_t expected, uint32_t next,
                                                             uint64_t bulk = UINT64_MAX) {
    saved.expected = expected;
    saved.completed = 0;
    saved.next = next;
    saved.bulk = bulk;
    for (uint32_t a = 0; a < op.argc(); ++a) {
        const Slice arg = op.arg(a);
        if (!saved.push(static_cast<uint32_t>(arg.p - frame), arg.n)) {
            *err = "ERR out of memory parsing command";
            return ParseResult::Error;
        }
    }
    return ParseResult::Incomplete;
}

// Exceptional headers continue at the current argument, never replaying the
// prefix. Complete frames still build Op directly and never touch the frontier.
[[gnu::cold, gnu::noinline]] inline ParseResult resp_parse_tail(const char* buf, uint32_t len,
                                                                uint32_t& pos, Op& op,
                                                                const char** err, uint64_t max_bulk,
                                                                RespFrontier& saved, uint32_t nargs,
                                                                uint32_t p) {
    while (op.argc() < nargs) {
        const uint32_t header = p;
        uint64_t bulk = 0;
        auto r = ParseResult::Incomplete;
        if (p < len) {
            if (buf[p] != '$')
                r = resp_bulk_prefix_error(buf, len, p, op, err);
            else {
                ++p;
                // parse_len_crlf's bound is its only overflow guard and configured limits
                // reach LONG_MAX: as on the complete-frame path, larger headers continue
                // in the signed, overflow-checked decoder.
                r = parse_len_crlf(
                    buf, len, p, max_bulk < 512ull * 1024 * 1024 ? max_bulk : 512ull * 1024 * 1024,
                    bulk);
                if (r == ParseResult::Error)
                    r = resp_length_slow(buf, len, p, max_bulk, bulk, false, err);
            }
        }
        if (r == ParseResult::Error) return r;
        if (r == ParseResult::Incomplete)
            return resp_suspend(saved, buf + pos, op, err, nargs, header - pos);
        if (uint64_t(p) + bulk + 2 > len)
            return resp_suspend(saved, buf + pos, op, err, nargs, p - pos, bulk);
        if (!op.push_arg(Slice(buf + p, static_cast<uint32_t>(bulk)))) {
            *err = "ERR out of memory parsing command";
            return ParseResult::Error;
        }
        p += static_cast<uint32_t>(bulk) + 2;
    }
    pos = p;
    return ParseResult::Ok;
}

[[gnu::cold, gnu::noinline]] inline ParseResult resp_parse_start(
    const char* buf, uint32_t len, uint32_t& pos, Op& op, const char** err, uint64_t max_multibulk,
    uint64_t max_bulk, RespFrontier& saved) {
    uint32_t p = pos + 1;
    uint64_t nargs = 0;
    const auto r = resp_length_slow(buf, len, p, max_multibulk, nargs, true, err);
    if (r == ParseResult::Incomplete) return resp_suspend(saved, buf + pos, op, err, 0, 0);
    if (r == ParseResult::Error) return r;
    if (!nargs) {
        pos = p;
        return ParseResult::Empty;
    }
    return resp_parse_tail(buf, len, pos, op, err, max_bulk, saved, static_cast<uint32_t>(nargs),
                           p);
}

// Resume a frame on the caller that owns Op, saved and the receive buffer. saved offsets refer
// to buf+pos; Op must be reset before materializing argv. Completion borrows buffer slices and
// advances pos; Incomplete retains progress without advancing pos, Error reports syntax/OOM.
// The caller pins input through consumer use and performs any later cross-thread publication.
[[gnu::cold, gnu::noinline]] inline ParseResult resp_resume(const char* buf, uint32_t len,
                                                            uint32_t& pos, Op& op, const char** err,
                                                            uint64_t max_multibulk,
                                                            uint64_t max_bulk,
                                                            RespFrontier& saved) {
    if (!saved.expected)
        return resp_parse_start(buf, len, pos, op, err, max_multibulk, max_bulk, saved);
    const char* frame = buf + pos;
    const uint32_t available = len - pos;
    while (saved.completed < saved.expected) {
        uint32_t p = saved.next;
        if (saved.bulk == UINT64_MAX) {
            if (p == available) return ParseResult::Incomplete;
            ParseResult r;
            uint64_t bulk = 0;
            if (frame[p] != '$')
                r = resp_bulk_prefix_error(frame, available, p, op, err);
            else {
                ++p;
                // Same overflow bound as resp_parse_tail above.
                r = parse_len_crlf(
                    frame, available, p,
                    max_bulk < 512ull * 1024 * 1024 ? max_bulk : 512ull * 1024 * 1024, bulk);
                if (r == ParseResult::Error)
                    r = resp_length_slow(frame, available, p, max_bulk, bulk, false, err);
            }
            if (r != ParseResult::Ok) return r;
            saved.next = p;
            saved.bulk = bulk;
        }
        if (uint64_t(p) + saved.bulk + 2 > available) return ParseResult::Incomplete;
        if (!saved.push(p, static_cast<uint32_t>(saved.bulk))) {
            *err = "ERR out of memory parsing command";
            return ParseResult::Error;
        }
        saved.next = p + static_cast<uint32_t>(saved.bulk) + 2;
        saved.bulk = UINT64_MAX;
    }
    // ROB acquire reset the scratch Op. Materialize each saved slice only once,
    // when the whole frame is available and the receive allocation is pinned.
    for (uint32_t a = 0; a < saved.completed; ++a) {
        const auto arg = saved.args[a];
        if (!op.push_arg(Slice(frame + arg.offset, arg.length))) {
            *err = "ERR out of memory parsing command";
            return ParseResult::Error;
        }
    }
    pos += saved.next;
    return ParseResult::Ok;
}

// Parse one request for a caller with exclusive Op/frontier access and stable buf[pos,len).
// Op starts with an empty argv; kResume requires a nonnull saved frontier and a multibulk frame.
// Ok/Empty advance pos; Incomplete preserves pos for more input (and saves progress in kResume).
// Error reports malformed input or allocation failure. Borrowed argument bytes must remain pinned
// until consumers finish; this routine performs no cross-thread publication or waiting.
// kLimited selects caller-supplied limits; the other instantiation folds the 1 Mi / 512 MiB fast
// bounds as constants. Exceptional counts use the cold decoder's compatibility limits.
template <bool kLimited, bool kResume = false>
inline ParseResult resp_parse_t(const char* buf, uint32_t len, uint32_t& pos, Op& op,
                                const char** err, uint64_t max_multibulk, uint64_t max_bulk,
                                RespFrontier* saved = nullptr) {
    if constexpr (!kLimited) {
        max_multibulk = 1024 * 1024;
        max_bulk = 512ull * 1024 * 1024;
    }
    const uint32_t start = pos;
    if (pos >= len) return ParseResult::Incomplete;

    if constexpr (!kResume)
        if (buf[pos] != '*') {
            uint32_t scanned = 0;  // Stateless callers; IoLoop supplies Client's saved cursor.
            return resp_parse_inline(buf, len, pos, op, err, scanned);
        }

    uint32_t p = pos + 1;  // past '*'
    uint64_t nargs = 0;
    ParseResult r = parse_len_crlf(buf, len, p, max_multibulk, nargs);
    if (r == ParseResult::Incomplete) {
        if constexpr (kResume) return resp_suspend(*saved, buf + start, op, err, 0, 0);
        return ParseResult::Incomplete;
    }
    if (r == ParseResult::Error) {
        if constexpr (kResume)
            return resp_parse_start(buf, len, pos, op, err, max_multibulk, max_bulk, *saved);
        if constexpr (!kLimited)
            return resp_parse_unlimited_slow(buf, len, pos, op, err);
        else
            return resp_parse_slow(buf, len, pos, op, err, max_multibulk, max_bulk);
    }

    for (uint64_t a = 0; a < nargs; a++) {
        if (p >= len) {
            if constexpr (kResume)
                return resp_suspend(*saved, buf + start, op, err, nargs, p - start);
            pos = start;
            return ParseResult::Incomplete;
        }
        if (buf[p] != '$') {
            if constexpr (kResume)
                return resp_parse_tail(buf, len, pos, op, err, max_bulk, *saved, nargs, p);
            if constexpr (!kLimited)
                return resp_parse_unlimited_slow(buf, len, pos, op, err);
            else
                return resp_parse_slow(buf, len, pos, op, err, max_multibulk, max_bulk);
        }
        p++;
        uint64_t blen = 0;
        // The fast bound is 512 MiB. Larger configured limits use the
        // signed, overflow-checked cold decoder once this small bound is crossed.
        r = parse_len_crlf(buf, len, p,
                           max_bulk < 512ull * 1024 * 1024 ? max_bulk : 512ull * 1024 * 1024, blen);
        if (r == ParseResult::Incomplete) {
            if constexpr (kResume)
                return resp_suspend(*saved, buf + start, op, err, nargs, p - 1 - start);
            pos = start;
            return ParseResult::Incomplete;
        }
        if (r == ParseResult::Error) {
            if constexpr (kResume)
                return resp_parse_tail(buf, len, pos, op, err, max_bulk, *saved, nargs, p - 1);
            if constexpr (!kLimited)
                return resp_parse_unlimited_slow(buf, len, pos, op, err);
            else
                return resp_parse_slow(buf, len, pos, op, err, max_multibulk, max_bulk);
        }
        if (p + blen + 2 > len) {
            if constexpr (kResume)
                return resp_suspend(*saved, buf + start, op, err, nargs, p - start, blen);
            pos = start;
            return ParseResult::Incomplete;
        }
        if (!op.push_arg(Slice(buf + p, static_cast<uint32_t>(blen)))) {
            *err = "ERR out of memory parsing command";
            return ParseResult::Error;
        }
        p += static_cast<uint32_t>(blen) + 2;
    }
    pos = p;
    return ParseResult::Ok;
}

inline ParseResult resp_parse(const char* buf, uint32_t len, uint32_t& pos, Op& op,
                              const char** err) {
    return resp_parse_t<false>(buf, len, pos, op, err, 0, 0);
}

inline ParseResult resp_parse_limited(const char* buf, uint32_t len, uint32_t& pos, Op& op,
                                      const char** err, uint64_t max_multibulk, uint64_t max_bulk) {
    return resp_parse_t<true>(buf, len, pos, op, err, max_multibulk, max_bulk);
}

// ---- integer formatting -------------------------------------------------------------------------
// snprintf parses a format string at RUNTIME, every call. On the reply path that is a formatting
// interpreter running millions of times a second to emit at most 20 digits. These write digits
// directly, backwards into a scratch and then copied forward, which needs no division-by-10 chain
// longer than the number actually has.
inline uint32_t u64_to_dec(char* dst, uint64_t v) {
    char tmp[20];
    uint32_t n = 0;
    do {
        tmp[n++] = static_cast<char>('0' + (v % 10));
        v /= 10;
    } while (v);
    for (uint32_t i = 0; i < n; i++) dst[i] = tmp[n - 1 - i];
    return n;
}
inline uint32_t i64_to_dec(char* dst, int64_t v) {
    if (v < 0) {
        *dst = '-';
        return 1 + u64_to_dec(dst + 1, static_cast<uint64_t>(-(v + 1)) + 1);
    }
    return u64_to_dec(dst, static_cast<uint64_t>(v));
}

// ---- reply formatting. Handlers call these; they append RESP into the op's own buffer. ----------
// The one-argument append() below is the LITERAL overload (src/exec/op.h, src/base/slice.h): the
// length remains a compile-time constant, excluding the terminating NUL, so the builder can emit
// stores without an out-of-line append/memcpy pair. Replies that fit in a machine word or two
// use this overload; the longer error
// texts below keep the explicit length and the out-of-line path.
//
// CODED REPLIES. Where the sink is an Op::Sink (the executor's), a fixed reply records a ReplyCode
// and writes NO bytes; the connection's owner formats it at retire. Where it is a plain SmallBuf
// (pub/sub frames, MONITOR lines, script sub-buffers), it appends bytes to the caller's buffer.
// The requires test selects between these sink interfaces; a successful code store returns before
// the literal append, so the helper does not emit the reply twice.
//
// b.code() returns false on a non-empty sink, which is how a fixed reply nested inside a larger
// one (an EXEC element after its array header) falls back to bytes and stays in order.
#define TOMO_CODED_REPLY(sink, codeexpr)               \
    if constexpr (requires { sink.code(codeexpr); }) { \
        if (sink.code(codeexpr)) return;               \
    }

// Force inlining of the small fixed-reply helpers so a coded attempt does not turn a compact
// reply store/capacity check into a call (including reply_null from cmd_get). reply_int retains
// the compiler's separate inlining decision because it also carries a digit loop.
template <typename Buf>
__attribute__((always_inline)) inline void reply_ok(Buf&& b) {
    TOMO_CODED_REPLY(b, ReplyCode::Ok)
    b.append("+OK\r\n");
}
template <typename Buf>
__attribute__((always_inline)) inline void reply_nil(Buf&& b) {
    TOMO_CODED_REPLY(b, ReplyCode::Nil)
    b.append("$-1\r\n");
}
template <typename Buf>
__attribute__((always_inline)) inline void reply_pong(Buf&& b) {
    TOMO_CODED_REPLY(b, ReplyCode::Pong)
    b.append("+PONG\r\n");
}
template <typename Buf>
__attribute__((always_inline)) inline void reply_null_array(Buf&& b) {
    TOMO_CODED_REPLY(b, ReplyCode::NullArray)
    b.append("*-1\r\n");
}
template <typename Buf>
__attribute__((always_inline)) inline void reply_emptystr(Buf&& b) {
    TOMO_CODED_REPLY(b, ReplyCode::EmptyStr)
    b.append("$0\r\n\r\n");
}
template <typename Buf>
inline void reply_wrongtype(Buf&& b) {
    error_stats_record("WRONGTYPE ", 10);
    b.append("-WRONGTYPE Operation against a key holding the wrong kind of value\r\n", 68);
}
template <typename Buf>
inline void reply_syntax(Buf&& b) {
    error_stats_record("ERR ", 4);
    b.append("-ERR syntax error\r\n", 19);
}
template <typename Buf>
inline void reply_outofrange(Buf&& b) {
    error_stats_record("ERR ", 4);
    // Redis's getRangeLongFromObject names the bounds it enforces; every caller of this helper
    // (SRANDMEMBER / ZRANDMEMBER / HRANDFIELD counts) is one of those sites.
    static constexpr char kMsg[] =
        "-ERR value is out of range, value must between "
        "-9223372036854775807 and 9223372036854775807\r\n";
    b.append(kMsg, sizeof(kMsg) - 1);
}

// DEL/EXISTS counts, SETNX's 0/1, INCR's value and LPUSH/SADD/HSET lengths can travel as values
// for the connection owner to render. Op's coded-integer payload is four bytes; values outside
// int32 and sinks that reject the code render decimal bytes here with the same wire grammar.
template <typename Buf>
inline void reply_int(Buf&& b, long long v) {
    if constexpr (requires { b.code(ReplyCode::Int, int32_t{0}); }) {
        if (__builtin_expect(v >= -2147483648LL && v <= 2147483647LL, true) &&
            b.code(ReplyCode::Int, static_cast<int32_t>(v)))
            return;
    }
    char* p = b.reserve(24);
    char* q = p;
    *q++ = ':';
    q += i64_to_dec(q, v);
    *q++ = '\r';
    *q++ = '\n';
    b.advance(static_cast<size_t>(q - p));
}

template <typename Buf>
inline void reply_array_header(Buf&& b, uint64_t n) {
    char* p = b.reserve(24);
    char* q = p;
    *q++ = '*';
    q += u64_to_dec(q, n);
    *q++ = '\r';
    *q++ = '\n';
    b.advance(static_cast<size_t>(q - p));
}

template <typename Buf>
inline void reply_bulk_header(Buf&& b, uint32_t len) {
    char* p = b.reserve(24);
    char* q = p;
    *q++ = '$';
    q += u64_to_dec(q, len);
    *q++ = '\r';
    *q++ = '\n';
    b.advance(static_cast<size_t>(q - p));
}

// Reserve header/payload/trailer space together, copy the payload once and commit the full reply.
// Its size is known before writing, so separate appends and repeated capacity checks are unnecessary.
template <typename Buf>
inline void reply_bulk(Buf&& b, Slice s) {
    char* p = b.reserve(24 + static_cast<size_t>(s.n) + 2);
    char* q = p;
    *q++ = '$';
    q += u64_to_dec(q, s.n);
    *q++ = '\r';
    *q++ = '\n';
    std::memcpy(q, s.p, s.n);
    q += s.n;
    *q++ = '\r';
    *q++ = '\n';
    b.advance(static_cast<size_t>(q - p));
}

// THE canonical double text lives in src/base/numeric.h: redis renders the RESP2 bulk score and
// the RESP3 "," from one d2string, and the parsers that must accept exactly what it can produce
// belong beside it. This header keeps only the RESP framing.

// Fixed replies pair 16 bytes with their wire length. format_reply_code copies all 16 bytes
// at a computed index, so callers reserve kReplyCodeMax even for shorter replies. This keeps the
// copy width constant and the length beside the bytes, without a switch/jump-table dispatch.
// Retirement formats into the connection owner's fill storage; op_materialise_code uses the
// same table during retirement when a coded reply must first become bytes in op.reply (WbEngine
// segment staging and assemble_mget's borrowed flush).
struct FixedReply {
    char bytes[16];
    uint32_t len;
};

// Indexed by ReplyCode. Slot 0 (None) is unreachable: every caller tests reply_code_ != 0 first,
// which inlining folds away. Its zero length is a fail-quiet, not a design.
inline constexpr FixedReply kFixedReplies[] = {
    {{0}, 0},  // None -- unreachable
    {"+OK\r\n", 5}, {"$-1\r\n", 5}, {"+PONG\r\n", 7}, {"*-1\r\n", 5}, {"$0\r\n\r\n", 6},
    {"_\r\n", 3},   {"#t\r\n", 4},  {"#f\r\n", 4},    {{0}, 0},  // Int -- handled below, never read from this table
};

// Write digits directly into the destination to avoid scratch storage and its stack-protector
// cost. The two passes count then fill at most ten decimal digits.
inline uint32_t u32_to_dec_direct(char* dst, uint32_t v) {
    uint32_t n = 1;
    for (uint32_t t = v; t >= 10; t /= 10) n++;
    for (uint32_t i = n; i-- > 0;) {
        dst[i] = static_cast<char>('0' + v % 10);
        v /= 10;
    }
    return n;
}

// Keep the digit loop out of each instantiated per-op retire lambda, which handles fixed and
// integer replies alike. ":-2147483648\r\n" is 14 bytes, inside kReplyCodeMax.
__attribute__((noinline)) inline uint32_t format_reply_code_int(char* dst, int32_t ival) {
    char* q = dst;
    *q++ = ':';
    uint32_t mag;
    if (ival < 0) {
        *q++ = '-';
        mag = static_cast<uint32_t>(-static_cast<int64_t>(ival));
    } else {
        mag = static_cast<uint32_t>(ival);
    }
    q += u32_to_dec_direct(q, mag);
    *q++ = '\r';
    *q++ = '\n';
    return static_cast<uint32_t>(q - dst);
}

// Inline the fixed-reply table copy and call the out-of-line integer formatter when needed.
// dst must provide kReplyCodeMax writable bytes and code must identify a valid ReplyCode.
// This keeps fixed replies such as SET's OK compact without duplicating the digit loop at each
// retire site. The caller owns dst; no publication or bounds check occurs here.
__attribute__((always_inline)) inline uint32_t format_reply_code(char* dst, uint8_t code,
                                                                 int32_t ival) {
    if (code != static_cast<uint8_t>(ReplyCode::Int)) {
        const FixedReply& f = kFixedReplies[code];
        __builtin_memcpy(dst, f.bytes, sizeof(f.bytes));
        return f.len;
    }
    return format_reply_code_int(dst, ival);
}

// For the few paths that SPLICE an op's reply bytes mid-flight instead of retiring them (the
// borrowed-value flush inside assemble_mget). Turns a code back into the bytes it stands for, in
// order, so the splice sees a normal byte buffer. A no-op for the ordinary reply.
// Keep this out of line so SmallBuf::reserve's malloc/memcpy/free growth path does not expand
// WbEngine's per-op retire lambda. The function checks reply_code_ before reserving storage;
// callers may also guard it when their surrounding work is conditional on a coded reply.
__attribute__((noinline)) inline void op_materialise_code(Op& op) {
    if (op.reply_code_ == 0) return;
    char* p = op.reply.reserve(kReplyCodeMax);
    op.reply.advance(format_reply_code(p, op.reply_code_, op.reply_ival_));
    op.reply_code_ = 0;
}

// RESP2 has no native double: redis sends this same text as a bulk string.
template <typename Buf>
inline void reply_double(Buf&& b, double value) {
    char text[kDoubleTextMax];
    const uint32_t length = redis_double_text(text, sizeof(text), value);
    reply_bulk(b, Slice(text, length));
}

}  // namespace tomo

// RESP3 supplies reply-only protocol-selecting overloads after the RESP2 builders they call.
#include "resp3.h"
