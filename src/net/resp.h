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
#include "../base/slice.h"
#include "../exec/op.h"

namespace tomo {

enum class ParseResult { Ok, Incomplete, Error };

// Scans one command from buf[pos, len). On Ok, fills `op` and advances `pos` past the command.
// On Incomplete, leaves pos untouched — more bytes are needed.
inline ParseResult resp_parse(const char* buf, uint32_t len, uint32_t& pos, Op& op,
                              const char** err) {
    const uint32_t start = pos;
    if (pos >= len) return ParseResult::Incomplete;

    auto find_crlf = [&](uint32_t from, uint32_t& out) -> bool {
        for (uint32_t i = from; i + 1 < len; i++)
            if (buf[i] == '\r' && buf[i + 1] == '\n') { out = i; return true; }
        return false;
    };

    if (buf[pos] != '*') {
        // Inline command: whitespace-separated, CRLF-terminated. Kept because every debugging
        // session uses it through nc/telnet and it costs almost nothing.
        uint32_t eol;
        if (!find_crlf(pos, eol)) return ParseResult::Incomplete;
        uint32_t i = pos;
        while (i < eol) {
            while (i < eol && (buf[i] == ' ' || buf[i] == '\t')) i++;
            uint32_t b = i;
            while (i < eol && buf[i] != ' ' && buf[i] != '\t') i++;
            if (i > b && !op.push_arg(Slice(buf + b, i - b))) {
                *err = "ERR out of memory parsing inline command";
                return ParseResult::Error;
            }
        }
        pos = eol + 2;
        return op.argc() ? ParseResult::Ok : ParseResult::Incomplete;  // bare CRLF: ignore
    }

    uint32_t eol;
    if (!find_crlf(pos, eol)) return ParseResult::Incomplete;
    long nargs = std::strtol(buf + pos + 1, nullptr, 10);
    if (nargs <= 0 || nargs > 1024 * 1024) { *err = "ERR invalid multibulk length"; return ParseResult::Error; }
    uint32_t p = eol + 2;

    for (long a = 0; a < nargs; a++) {
        if (p >= len) { pos = start; return ParseResult::Incomplete; }
        if (buf[p] != '$') { *err = "ERR expected '$'"; return ParseResult::Error; }
        if (!find_crlf(p, eol)) { pos = start; return ParseResult::Incomplete; }
        long blen = std::strtol(buf + p + 1, nullptr, 10);
        if (blen < 0 || blen > 512L * 1024 * 1024) { *err = "ERR invalid bulk length"; return ParseResult::Error; }
        const uint32_t bstart = eol + 2;
        if (bstart + blen + 2 > len) { pos = start; return ParseResult::Incomplete; }
        if (!op.push_arg(Slice(buf + bstart, static_cast<uint32_t>(blen)))) {
            *err = "ERR out of memory parsing command";
            return ParseResult::Error;
        }
        p = bstart + static_cast<uint32_t>(blen) + 2;
    }
    pos = p;
    return ParseResult::Ok;
}

// ---- reply formatting. Handlers call these; they append RESP into the op's own buffer. ----------
template <typename Buf> inline void reply_ok(Buf& b)   { b.append("+OK\r\n", 5); }
template <typename Buf> inline void reply_nil(Buf& b)  { b.append("$-1\r\n", 5); }
template <typename Buf> inline void reply_pong(Buf& b) { b.append("+PONG\r\n", 7); }

template <typename Buf> inline void reply_err(Buf& b, const char* msg) {
    b.push_back('-'); b.append(msg, std::strlen(msg)); b.append("\r\n", 2);
}
template <typename Buf> inline void reply_simple(Buf& b, const char* msg) {
    b.push_back('+'); b.append(msg, std::strlen(msg)); b.append("\r\n", 2);
}
template <typename Buf> inline void reply_int(Buf& b, long long v) {
    char* p = b.reserve(24);
    int n = std::snprintf(p, 24, ":%lld\r\n", v);
    b.advance(static_cast<size_t>(n));
}
template <typename Buf> inline void reply_bulk(Buf& b, Slice s) {
    char* p = b.reserve(24);
    int n = std::snprintf(p, 24, "$%u\r\n", s.n);
    b.advance(static_cast<size_t>(n));
    b.append(s.p, s.n);
    b.append("\r\n", 2);
}

}  // namespace tomo
