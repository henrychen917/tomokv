// resp.h — RESP2 request parsing and reply formatting.
//
// Patterned on the protocol as documented and as implemented in redis-7.2 / valkey (BSD-3). Nothing
// here is copied from our own Redis 8.6.2 fork, which carries RSALv2/SSPLv1 and would contaminate
// the licence of this tree.
//
// The parser produces Slices INTO the read buffer and never copies. That is the point, and it is
// also why Conn's read buffer is append-only while ops are in flight — see conn.h.
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

namespace tomo {

enum class ParseResult { Ok, Incomplete, Error, Empty };

// Redis 7.4's PROTO_INLINE_MAX_SIZE is a fixed protocol bound, not a CONFIG knob.
inline constexpr uint32_t kProtoInlineMaxSize = 64 * 1024;

// Only validate quoting here: decoding quoted/escaped argv needs separately owned
// storage, outside this error-path change. Never rewrite pinned input or borrow the
// reply buffer for argv: dispatch can retry, and the executor owns reply storage.
__attribute__((noinline, cold)) inline bool resp_inline_quotes_valid(const char* p, const char* end) {
    char quote = 0;
    for (; p != end && *p; ++p) {
        const char c = *p;
        if (quote) {
            if (c == '\\' && p + 1 != end && p[1] &&
                (quote == '"' || p[1] == '\'')) { ++p; continue; }
            if (c == quote) {
                quote = 0;
                if (p + 1 != end && p[1] && !std::isspace(static_cast<unsigned char>(p[1])))
                    return false;
            }
        } else if (c == '"' || c == '\'') {
            quote = c;
        }
    }
    return quote == 0;
}

// `scanned` is relative to the unconsumed request, so quiescent buffer compaction and
// connection migration preserve it. Scan for LF, trimming an optional CR. No bytes
// are copied or changed: argv can still point into the append-only receive buffer.
inline ParseResult resp_parse_inline(const char* buf, uint32_t len, uint32_t& pos,
                                      Op& op, const char** err, uint32_t& scanned) {
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
    scanned = 0; // A dispatch refusal may parse this complete frame again.
    if (!resp_inline_quotes_valid(buf + pos, buf + eol)) {
        *err = "ERR Protocol error: unbalanced quotes in request";
        return ParseResult::Error;
    }
    i = pos;
    while (i < eol) {
        while (i < eol && (buf[i] == ' ' || buf[i] == '\t')) ++i;
        const uint32_t begin = i;
        while (i < eol && buf[i] != ' ' && buf[i] != '\t') ++i;
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
    message[sizeof(message) - 3] = actual == '\r' || actual == '\n' ? ' ' : actual;
    // Redis preserves even a NUL offending byte in this error. Its wire length cannot
    // be recovered with strlen; stage this cold error using the known literal size.
    op.reply.append("-");
    op.reply.append(message, sizeof(message) - 1);
    op.reply.append("\r\n");
    return message;
}

// Redis waits for the first CR and one following byte before validating a count.
// In particular, malformed digits without CR are incomplete until the 64 KiB
// bound (including the '*'/'$' prefix); a CR at the very end is still incomplete.
// Redis's search stops at NUL and does not check that the byte after CR is LF.
__attribute__((noinline, cold)) inline ParseResult resp_count_line(
        const char* buf, uint32_t len, uint32_t start, uint32_t& end,
        bool multibulk, const char** err) {
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

__attribute__((noinline, cold)) inline ParseResult resp_length_slow(
        const char* buf, uint32_t len, uint32_t& pos, uint64_t maxv,
        uint64_t& out, bool multibulk, const char** err) {
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
        *err = invalid; return ParseResult::Error;
    }
    const auto parsed = std::from_chars(buf + pos, buf + end, value);
    if (parsed.ec != std::errc{} || parsed.ptr != buf + end ||
        (multibulk ? value > INT32_MAX : value < 0)) {
        *err = invalid; return ParseResult::Error;
    }
    // Keep the ordinary parser's original immediate bound. Counts above 1 Mi
    // take this cold continuation, up to Redis's INT_MAX; no eager argv reserve.
    if (multibulk && maxv == 1024 * 1024) maxv = INT32_MAX;
    if (value > 0 && static_cast<uint64_t>(value) > maxv) {
        *err = invalid; return ParseResult::Error;
    }
    out = value > 0 ? static_cast<uint64_t>(value) : 0;
    pos = end + 2;
    return ParseResult::Ok;
}

__attribute__((noinline, cold)) inline ParseResult resp_bulk_prefix_error(
        const char* buf, uint32_t len, uint32_t pos, Op& op, const char** err) {
    uint32_t end;
    const auto line = resp_count_line(buf, len, pos, end, false, err);
    if (line != ParseResult::Ok) return line;
    *err = resp_expected_bulk_error(buf[pos], op);
    return ParseResult::Error;
}

// An exceptional header finishes the entire request here, never returning into
// the ordinary parser's argument loop. The already parsed argv prefix is kept:
// resetting Op would discard the connection flags captured by ROB acquisition.
// Only receive-buffer slices are replayed; no receive byte is copied or changed.
[[gnu::cold, gnu::noinline]] inline ParseResult resp_parse_slow(
        const char* buf, uint32_t len, uint32_t& pos, Op& op, const char** err,
        uint64_t max_multibulk, uint64_t max_bulk) {
    uint32_t p = pos + 1;
    uint64_t nargs = 0;
    auto r = resp_length_slow(buf, len, p, max_multibulk, nargs, true, err);
    if (r != ParseResult::Ok) return r;
    if (nargs == 0) { pos = p; return ParseResult::Empty; }
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
[[gnu::cold, gnu::noinline]] inline ParseResult resp_parse_unlimited_slow(
        const char* buf, uint32_t len, uint32_t& pos, Op& op, const char** err) {
    return resp_parse_slow(buf, len, pos, op, err, 1024 * 1024, 512ull * 1024 * 1024);
}

// Read decimal digits terminated by CRLF, advancing `pos` past the CRLF.
//
// strtol was doing this, and strtol is a general-purpose parser: it skips leading whitespace,
// accepts signs, honours a base argument and consults the locale — none of which a RESP length
// field may contain. It also cannot tell "no digits yet" from "not a number", so it silently
// returned 0 for a truncated header instead of asking for more bytes. This reads exactly what the
// protocol allows and distinguishes Incomplete from Error, which the old code could not.
//
// Returns Ok / Incomplete / Error. Bounded by `maxv` so a hostile length cannot overflow.
inline ParseResult parse_len_crlf(const char* buf, uint32_t len, uint32_t& pos,
                                  uint64_t maxv, uint64_t& out) {
    uint32_t i = pos;
    if (i >= len) return ParseResult::Incomplete;
    // Peel the first digit so its existing range check rejects zero as well as
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

// Scans one command from buf[pos, len). On Ok, fills `op` and advances `pos` past the command.
// On Incomplete, leaves pos untouched — more bytes are needed.
//
// The limits are a TEMPLATE variant, not runtime parameters: carrying them as arguments through
// the hottest loop in the server (they were briefly defaulted parameters for the unauthenticated
// pre-AUTH limits) cost +83 instructions/op on loopback and −5.1% on the wire p128 GET cell —
// register-carried limits defeat the immediate-folding the comparisons had always compiled to.
// The unlimited instantiation folds the constants exactly as the original code did; only the
// pre-AUTH path (predicted-false at the call site) pays for real arguments.
template <bool kLimited>
inline ParseResult resp_parse_t(const char* buf, uint32_t len, uint32_t& pos, Op& op,
                                const char** err, uint64_t max_multibulk, uint64_t max_bulk) {
    if constexpr (!kLimited) {
        max_multibulk = 1024 * 1024;
        max_bulk = 512ull * 1024 * 1024;
    }
    const uint32_t start = pos;
    if (pos >= len) return ParseResult::Incomplete;

    if (buf[pos] != '*') {
        uint32_t scanned = 0; // Stateless callers; IoLoop supplies Client's saved cursor.
        return resp_parse_inline(buf, len, pos, op, err, scanned);
    }

    uint32_t p = pos + 1;                      // past '*'
    uint64_t nargs = 0;
    ParseResult r = parse_len_crlf(buf, len, p, max_multibulk, nargs);
    if (r == ParseResult::Incomplete) return ParseResult::Incomplete;
    if (r == ParseResult::Error) {
        if constexpr (!kLimited) return resp_parse_unlimited_slow(buf, len, pos, op, err);
        else return resp_parse_slow(buf, len, pos, op, err, max_multibulk, max_bulk);
    }

    for (uint64_t a = 0; a < nargs; a++) {
        if (p >= len) { pos = start; return ParseResult::Incomplete; }
        if (buf[p] != '$') {
            if constexpr (!kLimited) return resp_parse_unlimited_slow(buf, len, pos, op, err);
            else return resp_parse_slow(buf, len, pos, op, err, max_multibulk, max_bulk);
        }
        p++;
        uint64_t blen = 0;
        // The common constant is unchanged. Larger configured limits use the
        // signed, overflow-checked cold decoder once this small bound is crossed.
        r = parse_len_crlf(buf, len, p, max_bulk < 512ull * 1024 * 1024
                                      ? max_bulk : 512ull * 1024 * 1024, blen);
        if (r == ParseResult::Incomplete) { pos = start; return ParseResult::Incomplete; }
        if (r == ParseResult::Error) {
            if constexpr (!kLimited) return resp_parse_unlimited_slow(buf, len, pos, op, err);
            else return resp_parse_slow(buf, len, pos, op, err, max_multibulk, max_bulk);
        }
        if (p + blen + 2 > len) { pos = start; return ParseResult::Incomplete; }
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
                                      const char** err, uint64_t max_multibulk,
                                      uint64_t max_bulk) {
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
    do { tmp[n++] = static_cast<char>('0' + (v % 10)); v /= 10; } while (v);
    for (uint32_t i = 0; i < n; i++) dst[i] = tmp[n - 1 - i];
    return n;
}
inline uint32_t i64_to_dec(char* dst, int64_t v) {
    if (v < 0) { *dst = '-'; return 1 + u64_to_dec(dst + 1, static_cast<uint64_t>(-(v + 1)) + 1); }
    return u64_to_dec(dst, static_cast<uint64_t>(v));
}

// ---- reply formatting. Handlers call these; they append RESP into the op's own buffer. ----------
// The one-argument append() below is the LITERAL overload (src/exec/op.h, src/base/slice.h): the
// length stays a compile-time constant all the way to the store, so a fixed reply costs a store
// instead of a call to the out-of-line append plus a call to memcpy. Same bytes as before, NUL
// excluded. Only replies that fit in a machine word or two are written this way; the longer error
// texts below keep the explicit length and the out-of-line path.
//
// CODED REPLIES. Where the sink is an Op::Sink (the executor's), a fixed reply records a ReplyCode
// and writes NO bytes; the connection's owner formats it at retire. Where it is a plain SmallBuf
// (pub/sub frames, MONITOR lines, script sub-buffers -- all already owner-side) there is no code
// to set and the literal append below is used unchanged. The `requires` test is what makes one
// helper serve both, so no call site changes and no reply text is written twice.
//
// b.code() returns false on a non-empty sink, which is how a fixed reply nested inside a larger
// one (an EXEC element after its array header) falls back to bytes and stays in order.
#define TOMO_CODED_REPLY(sink, codeexpr)                                          \
    if constexpr (requires { sink.code(codeexpr); }) { if (sink.code(codeexpr)) return; }

// always_inline ON THE FIXED-REPLY HELPERS. Adding the coded attempt grew these bodies just
// enough to cross GCC's inlining threshold, and the loss was not the four instructions of the
// attempt -- it was that cmd_get stopped inlining reply_null and started CALLING it, which
// measured +22 instructions per 2s GET-miss on a deterministic replay. These are all one store
// plus a capacity test; they were inlined before this branch and must stay inlined. reply_int is
// deliberately NOT in this list: it carries the digit loop and was already out of line in base,
// so forcing it would change base's own decision.
template <typename Buf> __attribute__((always_inline)) inline void reply_ok(Buf&& b)   {
    TOMO_CODED_REPLY(b, ReplyCode::Ok)
    b.append("+OK\r\n");
}
template <typename Buf> __attribute__((always_inline)) inline void reply_nil(Buf&& b)  {
    TOMO_CODED_REPLY(b, ReplyCode::Nil)
    b.append("$-1\r\n");
}
template <typename Buf> __attribute__((always_inline)) inline void reply_pong(Buf&& b) {
    TOMO_CODED_REPLY(b, ReplyCode::Pong)
    b.append("+PONG\r\n");
}
template <typename Buf> __attribute__((always_inline)) inline void reply_null_array(Buf&& b) {
    TOMO_CODED_REPLY(b, ReplyCode::NullArray)
    b.append("*-1\r\n");
}
template <typename Buf> __attribute__((always_inline)) inline void reply_emptystr(Buf&& b) {
    TOMO_CODED_REPLY(b, ReplyCode::EmptyStr)
    b.append("$0\r\n\r\n");
}
template <typename Buf> inline void reply_wrongtype(Buf&& b) {
    b.append("-WRONGTYPE Operation against a key holding the wrong kind of value\r\n", 68);
}
template <typename Buf> inline void reply_syntax(Buf&& b) {
    b.append("-ERR syntax error\r\n", 19);
}
template <typename Buf> inline void reply_outofrange(Buf&& b) {
    // Redis's getRangeLongFromObject names the bounds it enforces; every caller of this helper
    // (SRANDMEMBER / ZRANDMEMBER / HRANDFIELD counts) is one of those sites.
    static constexpr char kMsg[] =
        "-ERR value is out of range, value must between "
        "-9223372036854775807 and 9223372036854775807\r\n";
    b.append(kMsg, sizeof(kMsg) - 1);
}

// RESP simple strings/errors cannot carry line delimiters, even when the source is a bulk.
template <typename Buf> inline void reply_line_text(Buf&& b, const char* text, size_t len) {
    size_t start = 0;
    for (size_t i = 0; i < len; ++i) {
        if (text[i] != '\r' && text[i] != '\n') continue;
        b.append(text + start, i - start);
        b.push_back(' ');
        start = i + 1;
    }
    if (start < len) b.append(text + start, len - start);
}
template <typename Buf> inline void reply_err(Buf&& b, const char* msg) {
    b.push_back('-'); reply_line_text(b, msg, std::strlen(msg)); b.append("\r\n", 2);
}
template <typename Buf> inline void reply_simple(Buf&& b, const char* msg) {
    b.push_back('+'); b.append(msg, std::strlen(msg)); b.append("\r\n", 2);
}
// AN INTEGER IS A VALUE, NOT A FORMAT. DEL's count, EXISTS's count, SETNX's 0/1, INCR's new
// value, LPUSH/SADD/HSET's length -- the executor computes the number, the owner renders the
// digits. Outside int32 the code path is declined (the hole in Op holds four bytes, not eight) and
// the digits are formatted here exactly as before; the wire bytes are identical either way.
template <typename Buf> inline void reply_int(Buf&& b, long long v) {
    if constexpr (requires { b.code(ReplyCode::Int, int32_t{0}); }) {
        if (__builtin_expect(v >= -2147483648LL && v <= 2147483647LL, true) &&
            b.code(ReplyCode::Int, static_cast<int32_t>(v)))
            return;
    }
    char* p = b.reserve(24);
    char* q = p;
    *q++ = ':';
    q += i64_to_dec(q, v);
    *q++ = '\r'; *q++ = '\n';
    b.advance(static_cast<size_t>(q - p));
}

template <typename Buf> inline void reply_array_header(Buf&& b, uint64_t n) {
    char* p = b.reserve(24);
    char* q = p;
    *q++ = '*';
    q += u64_to_dec(q, n);
    *q++ = '\r'; *q++ = '\n';
    b.advance(static_cast<size_t>(q - p));
}

template <typename Buf> inline void reply_bulk_header(Buf&& b, uint32_t len) {
    char* p = b.reserve(24);
    char* q = p;
    *q++ = '$';
    q += u64_to_dec(q, len);
    *q++ = '\r'; *q++ = '\n';
    b.advance(static_cast<size_t>(q - p));
}

// ONE reserve, ONE memcpy, no snprintf and no re-entry into the buffer. The previous version did a
// reserve plus three appends, and each append re-checked capacity — for a reply whose total size is
// known exactly before a byte is written.
template <typename Buf> inline void reply_bulk(Buf&& b, Slice s) {
    char* p = b.reserve(24 + static_cast<size_t>(s.n) + 2);
    char* q = p;
    *q++ = '$';
    q += u64_to_dec(q, s.n);
    *q++ = '\r'; *q++ = '\n';
    std::memcpy(q, s.p, s.n); q += s.n;
    *q++ = '\r'; *q++ = '\n';
    b.advance(static_cast<size_t>(q - p));
}

// THE canonical double text lives in src/base/numeric.h: redis renders the RESP2 bulk score and
// the RESP3 "," from one d2string, and the parsers that must accept exactly what it can produce
// belong beside it. This header keeps only the RESP framing.

// THE OWNER'S SIDE. Renders a coded reply into dst, which must have kReplyCodeMax writable bytes.
// Runs on the connection's own thread at retire, writing into that thread's own fill buffer -- so
// these bytes are produced and consumed by one core, which is the point of the code.
//
// SHAPE MATTERS HERE, and the obvious shape was wrong. Written as a switch over ReplyCode this
// became an out-of-line call with a jump table (`notrack jmp *%rax`) and a stack canary -- an
// indirect branch and a frame, to replace a five-byte memcpy. That is not a saving. A fixed reply
// is a CONSTANT, so it is a table: one 16-byte load-store at a computed index, no branch, no call,
// and the length comes from the same cache line as the bytes. Writing all 16 bytes is safe and
// deliberate -- every caller reserves kReplyCodeMax -- and it keeps the store width constant.
struct FixedReply {
    char     bytes[16];
    uint32_t len;
};

// Indexed by ReplyCode. Slot 0 (None) is unreachable: every caller tests reply_code_ != 0 first,
// which inlining folds away. Its zero length is a fail-quiet, not a design.
inline constexpr FixedReply kFixedReplies[] = {
    {{0},                 0},   // None -- unreachable
    {"+OK\r\n",           5},
    {"$-1\r\n",           5},
    {"+PONG\r\n",         7},
    {"*-1\r\n",           5},
    {"$0\r\n\r\n",        6},
    {"_\r\n",             3},
    {"#t\r\n",            4},
    {"#f\r\n",            4},
    {{0},                 0},   // Int -- handled below, never read from this table
};

// Digits straight into the destination, no scratch array -- an array here is what pulled a stack
// protector into the hot path. Two passes over at most ten digits, both branch-predictable.
inline uint32_t u32_to_dec_direct(char* dst, uint32_t v) {
    uint32_t n = 1;
    for (uint32_t t = v; t >= 10; t /= 10) n++;
    for (uint32_t i = n; i-- > 0; ) { dst[i] = static_cast<char>('0' + v % 10); v /= 10; }
    return n;
}

// The digits, deliberately OUT OF LINE. Inlined, this loop put 30-odd instructions into the per-op
// retire lambda at every one of its twenty-odd instantiations; the lambda is the io thread's
// hottest code and every op walks past those bytes whether or not it formats an integer.
// ":-2147483648\r\n" is 14 bytes, inside kReplyCodeMax.
__attribute__((noinline))
inline uint32_t format_reply_code_int(char* dst, int32_t ival) {
    char* q = dst;
    *q++ = ':';
    uint32_t mag;
    if (ival < 0) { *q++ = '-'; mag = static_cast<uint32_t>(-static_cast<int64_t>(ival)); }
    else          { mag = static_cast<uint32_t>(ival); }
    q += u32_to_dec_direct(q, mag);
    *q++ = '\r'; *q++ = '\n';
    return static_cast<uint32_t>(q - dst);
}

// always_inline, and measured both ways. Left to its own judgement GCC emitted a CALL at all
// twenty-odd retire sites, so a five-byte reply paid a call to avoid a five-byte memcpy. Inlined
// WITH the digits it bloated the retire lambda instead. This shape is the one that is small: the
// fixed reply -- which is every SET, the reply this change exists for -- becomes a table index, a
// 16-byte load-store and a length load, and an integer reply pays one call, exactly as it paid one
// memcpy call before.
__attribute__((always_inline))
inline uint32_t format_reply_code(char* dst, uint8_t code, int32_t ival) {
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
// NOINLINE, and callers guard it with op.reply_code_ themselves. Inlined it dragged
// SmallBuf::reserve's grow path -- malloc, memcpy, free -- into WbEngine's per-op retire lambda,
// which is the io thread's hottest code; the lambda went 186 -> 263 instructions and the split GET
// cell paid for all of it while using none of it.
__attribute__((noinline))
inline void op_materialise_code(Op& op) {
    if (op.reply_code_ == 0) return;
    char* p = op.reply.reserve(kReplyCodeMax);
    op.reply.advance(format_reply_code(p, op.reply_code_, op.reply_ival_));
    op.reply_code_ = 0;
}

// RESP2 has no native double: redis sends this same text as a bulk string.
template <typename Buf> inline void reply_double(Buf&& b, double value) {
    char text[kDoubleTextMax];
    const uint32_t length = redis_double_text(text, sizeof(text), value);
    reply_bulk(b, Slice(text, length));
}

}  // namespace tomo

// RESP3 is reply-only. Keeping its protocol-selecting builders in a feature header leaves the
// request parser and the established RESP2 reply_bulk/reply_int implementations untouched.
#include "resp3.h"
