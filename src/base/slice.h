// slice.h — the two byte types everything else is built from.
//
// Slice  : a non-owning (ptr, len) view. Parsing produces Slices INTO the connection's read buffer,
//          which is what makes command parsing zero-copy. The cost of that choice is a lifetime
//          rule, stated here because it is the one that bites: a Slice is only valid while the
//          buffer it points into is pinned. See Rob/Conn — the read buffer stays pinned until every
//          in-flight Op referencing it has retired.
// Buf    : an owned, growable byte buffer used for replies and for anything that must outlive the
//          read buffer.
#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <string_view>

namespace tomo {

// ---- key byte equality ------------------------------------------------------------------------
// The store's key comparison. Every FlatStore probe run ends here, so it is the hottest comparison
// in the server, and the shipped build reached it through `memcmp@plt`. What that call costs is
// NOT mainly the PLT hop: glibc's vector memcmp is about 22 instructions end to end for a key this
// short. It is the CALL — four caller-saved registers spilled and reloaded around it because the
// probe loop holds live state across the comparison. Removing the call is what pays, and what it
// pays is about 17 instructions on a GET hit with a 24-byte key (-1.0%) -- not the 5.6% the
// nallocx PLT removal bought. The full before/after table is in the commit message.
//
// Contract, and the two properties that make it SAFE:
//   - EQUALITY ONLY. This never yields memcmp's three-way order. Ordering comparisons (ZRANGEBYLEX,
//     SORT, ACL selector order, the cross-shard merge) still call memcmp and must keep doing so.
//   - It reads at most `n` bytes from each side and assumes no NUL terminator. Slices point INTO
//     the connection read buffer and into KvObj key slices a foreign fused reader may be scanning;
//     glibc's vector memcmp may read past `n` within a page, this never does. That also keeps the
//     ASAN build clean.
//
// Shape: overlapping word pairs, not a loop and not a per-word branch ladder. A probe that reaches
// the byte compare has already matched the 15-bit tag AND the length, so a mismatch is rare and an
// early exit buys nothing — OR the differences together and test once. The tail word is re-read at
// [n-8, n) rather than masked. Below 8 bytes that overlap would leave the buffer, so 4..7 uses two
// overlapping 4-byte loads and 1..3 compares {first, middle, last}, which at those lengths is
// every byte. Above the ceiling the vector memcmp wins outright and gets the work back.
inline constexpr uint32_t kInlineByteEqualMax = 32;

__attribute__((always_inline)) inline bool bytes_equal(const char* a, const char* b, uint32_t n) {
    auto ld8 = [](const char* q) { uint64_t v; std::memcpy(&v, q, 8); return v; };
    auto ld4 = [](const char* q) { uint32_t v; std::memcpy(&v, q, 4); return v; };
    if (__builtin_expect(n >= 8, 1)) {
        if (__builtin_expect(n > kInlineByteEqualMax, false)) return std::memcmp(a, b, n) == 0;
        uint64_t d = (ld8(a) ^ ld8(b)) | (ld8(a + n - 8) ^ ld8(b + n - 8));
        if (n > 16) d |= (ld8(a + 8) ^ ld8(b + 8)) | (ld8(a + n - 16) ^ ld8(b + n - 16));
        return d == 0;
    }
    if (n >= 4) return ((ld4(a) ^ ld4(b)) | (ld4(a + n - 4) ^ ld4(b + n - 4))) == 0;
    if (n == 0) return true;
    return a[0] == b[0] && a[n >> 1] == b[n >> 1] && a[n - 1] == b[n - 1];
}

// ---- short byte copy --------------------------------------------------------------------------
// The reply path's counterpart to bytes_equal above. Counted per operation with an LD_PRELOAD
// interposer on the binary's PLT: a steady-state GET pays two memcpy calls and a SET three, versus
// the ONE memcmp the lane before this one removed. The tax is the same one: not the PLT hop, but
// the call -- Op::Sink::append is an out-of-line body whose whole job is a bounds check plus a copy
// of five to forty bytes, and it spills around a library call to move them.
//
// Contract:
//   - EXACTLY memcpy's contract. Source and destination must NOT overlap; use std::memmove (or the
//     library memcpy the fallback reaches) where they can. Every site converted here was checked.
//   - Writes at most n bytes to `d` and reads at most n from `s`, which glibc's memcpy does not
//     promise. Op::Sink::reserve hands back exactly n writable bytes, so a single byte past the end
//     is a heap overflow; the ASAN battery in the commit message is what proves this.
//
// Shape mirrors bytes_equal: overlapping blocks, no loop and no per-word ladder -- 32..64 is four
// 16-byte moves (two leading, two trailing), 16..31 two 16-byte, 8..15 two 8-byte, 4..7 two 4-byte,
// and 1..3 the three bytes {first, middle, last}, which at those lengths is every byte. A narrower
// 8-byte-only ladder was built first and is WORSE than the library call at 20..32 (16 vs 15); the
// vector blocks are what make this work at all.
//
// The ceiling is 64, NOT the 32 the compare settled on, and that difference is measured rather
// than inherited: a copy is a pair of vector moves where a compare is a pair of loads plus an XOR
// tree, so the inline form stays ahead further. Instructions per call, isolated harness, runtime
// length, the copy as the whole out-of-line body (scratchpad cpbench.cc):
//     len          3     5     8    16    24    32    39    48    64    72   128
//     memcpy      22    19    17    15    15    13    13    13    13    13    13
//     inline      14     8    12    12    12    14    14    14    14    17    17
// Above the ceiling the inline form pays +4 for the two length tests before it hands back. That is
// the price of the win below it, and it is why only sites with a SHORT bounded n are converted --
// see the note on SmallBuf::append below, which measured the alternative and kept the library call.
inline constexpr uint32_t kInlineByteCopyMax = 64;

// SIXTEEN BYTES IS THE WIDEST BLOCK, and that is the load-bearing detail. A 32-byte block would
// make 32..64 one move instead of two, and in isolation that is three instructions cheaper -- but
// a ymm operation anywhere in a function makes GCC realign that function's whole frame (push rbp /
// and rsp,-32, and a lea on the way out). Every function that inlines this pays those four
// instructions on every call, including calls that hand straight back to the library. That cost is
// what a 32-byte-block build actually measured: while bytes_copy was still inside the once-per-
// operation SmallBuf::append, a GET returning a 128-byte value came out +9.7 instructions against
// base. The ABI already guarantees 16, so xmm blocks cost nothing to enter.
namespace detail {
inline void copy4 (char* d, const char* s) { __builtin_memcpy(d, s, 4); }
inline void copy8 (char* d, const char* s) { __builtin_memcpy(d, s, 8); }
inline void copy16(char* d, const char* s) { __builtin_memcpy(d, s, 16); }
}  // namespace detail

__attribute__((always_inline)) inline void bytes_copy(char* d, const char* s, size_t n) {
    if (__builtin_expect(n >= 8, 1)) {
        if (__builtin_expect(n > kInlineByteCopyMax, false)) { std::memcpy(d, s, n); return; }
        if (n >= 32) {
            detail::copy16(d, s);
            detail::copy16(d + 16, s + 16);
            detail::copy16(d + n - 32, s + n - 32);
            detail::copy16(d + n - 16, s + n - 16);
            return;
        }
        if (n >= 16) { detail::copy16(d, s); detail::copy16(d + n - 16, s + n - 16); return; }
        detail::copy8(d, s); detail::copy8(d + n - 8, s + n - 8);
        return;
    }
    if (n >= 4) { detail::copy4(d, s); detail::copy4(d + n - 4, s + n - 4); return; }
    if (n == 0) return;
    d[0] = s[0];
    d[n >> 1] = s[n >> 1];
    d[n - 1] = s[n - 1];
}

struct Slice {
    const char* p = nullptr;
    uint32_t    n = 0;

    Slice() = default;
    Slice(const char* p_, uint32_t n_) : p(p_), n(n_) {}
    explicit Slice(std::string_view s) : p(s.data()), n(static_cast<uint32_t>(s.size())) {}

    bool empty() const { return n == 0; }
    const char* begin() const { return p; }
    const char* end() const { return p + n; }
    std::string_view sv() const { return {p, n}; }

    // General slice equality: values, members, fields, patterns. Lengths vary widely here and
    // glibc's vector memcmp is the right tool, so this stays a library call.
    bool operator==(const Slice& o) const {
        return n == o.n && (n == 0 || std::memcmp(p, o.p, n) == 0);
    }

    // KEY equality. Length first (in a probe run a length mismatch is the common rejection, and it
    // is one register compare), then the inline byte compare. Every key-identity LOOKUP in the
    // store goes through this one member -- FlatStore's probes, the fused read-local probes, the
    // atomic entry and script-intent scans -- so those paths cannot drift apart. The one deliberate
    // exception is FlatStore::insert_into(), which keeps operator== for a measured reason stated
    // there; both are exact byte equality, so the answer is the same either way.
    bool key_eq(const Slice& o) const { return n == o.n && bytes_equal(p, o.p, n); }

    // Case-insensitive compare against a literal — command names arrive in any case. CONTRACT:
    // the LITERAL must be lowercase. Only the left side is folded (one fold per byte on the verb
    // path); a capitalised literal never matches. The free eq_icase(Slice, const char*) helpers
    // in the command files fold both sides and have no such requirement.
    bool eq_icase(std::string_view lit) const {
        if (n != lit.size()) return false;
        for (uint32_t i = 0; i < n; i++) {
            char a = p[i], b = lit[i];
            if (a >= 'A' && a <= 'Z') a = static_cast<char>(a - 'A' + 'a');
            if (a != b) return false;
        }
        return true;
    }
};

// Owned growable buffer. Deliberately not std::vector<char>: replies are written by appending small
// pieces in a hot loop, and we want an inline capacity so the common small reply never allocates.
template <size_t Inline>
class SmallBuf {
public:
    SmallBuf() : data_(inline_), cap_(Inline) {}
    ~SmallBuf() { if (data_ != inline_) std::free(data_); }
    SmallBuf(const SmallBuf&) = delete;
    SmallBuf& operator=(const SmallBuf&) = delete;

    char*  data()       { return data_; }
    const char* data() const { return data_; }
    size_t size() const { return len_; }
    bool   empty() const { return len_ == 0; }
    void   clear() { len_ = 0; }          // keeps the allocation for reuse
    size_t cap() const { return cap_; }

    // Publish n bytes that a WORKER already wrote past len_ (the direct-reply path). Only the
    // owning sender calls this, at in-order retire; the writer honored cap(), so no grow here.
    void commit_raw(size_t n) { len_ += n; }

    // Drops any heap growth and returns to the inline buffer. Called when a slot is recycled after
    // an unusually large reply, so one big reply does not permanently inflate every ring slot.
    void shrink_to_inline() {
        if (data_ != inline_) { std::free(data_); data_ = inline_; cap_ = Inline; }
        len_ = 0;
    }

    // ONE call per operation on the retire path: WbEngine stages the whole finished reply here
    // with conn.fill_buf().append(op.reply.data(), op.reply.size()). It KEEPS the library call, and
    // that is a measured decision, not an oversight. `n` here is a whole reply, so it is five bytes
    // for +OK and value-length plus seven for a GET -- unbounded, and set by the caller's data
    // rather than by this code. Routing it through bytes_copy was built and benched three ways
    // (test inside the helper, test hoisted with the short case predicted, test hoisted with the
    // long case predicted). All three win about ten instructions per op on the five-byte replies
    // and all three LOSE on a GET whose reply passes the ceiling: +2 at 47 bytes rising to +9 at
    // 87. A gain that changes sign with the user's value size is not a gain, so this line stays.
    void append(const char* src, size_t n) {
        if (len_ + n > cap_) grow(len_ + n);
        std::memcpy(data_ + len_, src, n);
        len_ += n;
    }
    void append(std::string_view s) { append(s.data(), s.size()); }
    void append(Slice s)            { append(s.p, s.n); }
    // Literal overload, matching Op::Sink::append -- same contract, NUL excluded. It exists so the
    // resp.h reply helpers can be written once and compile to a store on whichever sink they are
    // instantiated with.
    template <size_t N>
    void append(const char (&lit)[N]) {
        static_assert(N >= 1, "append() takes a string literal");
        if constexpr (N - 1 <= 16) {
            if (len_ + (N - 1) > cap_) grow(len_ + (N - 1));
            __builtin_memcpy(data_ + len_, lit, N - 1);
            len_ += N - 1;
        } else {
            append(static_cast<const char*>(lit), N - 1);
        }
    }
    void push_back(char c) {
        if (len_ + 1 > cap_) grow(len_ + 1);
        data_[len_++] = c;
    }

    // Reserve n writable bytes and return the cursor; caller commits with advance(). Lets a RESP
    // integer be formatted straight into the buffer instead of via a temporary.
    char* reserve(size_t n) {
        if (len_ + n > cap_) grow(len_ + n);
        return data_ + len_;
    }
    void advance(size_t n) { len_ += n; }

private:
    void grow(size_t need) {
        size_t ncap = cap_ * 2;
        while (ncap < need) ncap *= 2;
        char* nd = static_cast<char*>(std::malloc(ncap));
        std::memcpy(nd, data_, len_);
        if (data_ != inline_) std::free(data_);
        data_ = nd;
        cap_  = ncap;
    }
    char*  data_;
    size_t len_ = 0;
    size_t cap_;
    char   inline_[Inline];
};

}  // namespace tomo
