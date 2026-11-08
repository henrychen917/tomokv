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
#include "database_variant.h"

namespace tomo {

// Shared by Buf and Op::Sink: literal bytes excluding the terminating NUL.
inline constexpr size_t kInlineLiteralMax = 16;

// ---- key byte equality ------------------------------------------------------------------------
// Key equality for FlatStore probes and other key-identity lookups. Inlining short comparisons
// avoids a library call and caller-saved register spills while the probe keeps its state live.
// This returns equality, not memcmp's ordering: lexicographic zset, SORT, ACL selector and
// cross-shard ordering comparisons use memcmp separately.
//
// The inline paths read within [0,n), without requiring a terminator. They support connection
// buffer slices and keys inspected by foreign readers. A probe has matched tag and length before
// comparing bytes, so the word differences are combined before testing. Lengths 8..32 use
// overlapping 8-byte words, including the tail [n-8,n); 4..7 use overlapping 4-byte words;
// 1..3 compare first, middle and last, covering every byte. Larger inputs use memcmp.
inline constexpr uint32_t kInlineByteEqualMax = 32;

__attribute__((always_inline)) inline bool bytes_equal(const char* a, const char* b, uint32_t n) {
    auto ld8 = [](const char* q) {
        uint64_t v;
        std::memcpy(&v, q, 8);
        return v;
    };
    auto ld4 = [](const char* q) {
        uint32_t v;
        std::memcpy(&v, q, 4);
        return v;
    };
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
// Short-copy counterpart to bytes_equal for reply fragments and object keys. Source and
// destination must not overlap, including on the library fallback; use memmove for overlap.
// The inline paths stay within n readable source bytes and n writable destination bytes, as
// required when Op::Sink::reserve supplies exactly n bytes.
//
// Lengths 32..64 use four overlapping 16-byte moves (two leading, two trailing); 16..31 use two
// 16-byte moves; 8..15 use two 8-byte moves; 4..7 use two 4-byte moves; 1..3 copy first, middle and
// last. The copy ceiling is 64 rather than bytes_equal's 32: vector moves have different costs
// from compare loads and XORs. Above the ceiling two length tests lead to memcpy. Use this helper
// for short fragments; SmallBuf::append accepts whole replies and calls memcpy directly.
inline constexpr uint32_t kInlineByteCopyMax = 64;

// Sixteen-byte blocks fit the ABI's stack alignment. Wider vector operations can require GCC
// to realign the caller's entire frame, including calls that take the library fallback. Keep the
// widest explicit copy at 16 bytes; the measurements behind this choice live in the decision log.
namespace detail {
inline void copy4(char* d, const char* s) { __builtin_memcpy(d, s, 4); }
inline void copy8(char* d, const char* s) { __builtin_memcpy(d, s, 8); }
inline void copy16(char* d, const char* s) { __builtin_memcpy(d, s, 16); }
}  // namespace detail

__attribute__((always_inline)) inline void bytes_copy(char* d, const char* s, size_t n) {
    if (__builtin_expect(n >= 8, 1)) {
        if (__builtin_expect(n > kInlineByteCopyMax, false)) {
            std::memcpy(d, s, n);
            return;
        }
        if (n >= 32) {
            detail::copy16(d, s);
            detail::copy16(d + 16, s + 16);
            detail::copy16(d + n - 32, s + n - 32);
            detail::copy16(d + n - 16, s + n - 16);
            return;
        }
        if (n >= 16) {
            detail::copy16(d, s);
            detail::copy16(d + n - 16, s + n - 16);
            return;
        }
        detail::copy8(d, s);
        detail::copy8(d + n - 8, s + n - 8);
        return;
    }
    if (n >= 4) {
        detail::copy4(d, s);
        detail::copy4(d + n - 4, s + n - 4);
        return;
    }
    if (n == 0) return;
    d[0] = s[0];
    d[n >> 1] = s[n >> 1];
    d[n - 1] = s[n - 1];
}

// Borrows n bytes from its caller; copying a Slice does not extend that lifetime. Any role may
// use a view whose backing bytes remain valid; synchronization belongs to the buffer/store owner.
// General equality ignores namespace, while key equality includes it. No allocation or failure
// channel is provided; methods that read bytes require a valid span.
struct Slice {
    const char* p = nullptr;
    uint32_t n = 0;
    // Namespace shares the word containing length for key identity. Values compare bytewise.
    // Namespace zero leaves the high identity bits zero.
#if TOMO_SINGLE_DATABASE
    static constexpr uint32_t ns = 0;
#else
    uint32_t ns = 0;
#endif

    Slice() = default;
    Slice(const char* p_, uint32_t n_) : p(p_), n(n_) {}
    Slice(const char* p_, uint32_t n_, uint32_t ns_) : p(p_), n(n_) { set_namespace(ns_); }
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
    // exception is FlatStore::insert_into(), which uses memcmp for its insertion comparison; key_mem_eq includes the same namespace/length identity before comparing bytes.
    void set_namespace(uint32_t value) {
#if TOMO_SINGLE_DATABASE
        (void)value;
#else
        ns = value;
#endif
    }
    KeyIdentity identity() const {
#if TOMO_SINGLE_DATABASE
        return n;
#else
        uint64_t value;
        std::memcpy(&value, &n, sizeof(value));
        return value;
#endif
    }
    bool key_eq(const Slice& o) const {
        return identity() == o.identity() && bytes_equal(p, o.p, n);
    }
    bool key_mem_eq(const Slice& o) const {
        return identity() == o.identity() && (n == 0 || std::memcmp(p, o.p, n) == 0);
    }

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

// Owns Inline bytes plus any heap growth; destruction frees the heap block. The buffer's caller
// serializes writes and length changes. Direct-reply writers may fill reserved bytes before the
// sender commits them through its completion protocol; this class supplies no atomic publication.
// Inline must be positive. reserve/advance and commit_raw require caller-maintained bounds, and
// append requires non-overlapping source storage. Allocation failure and size overflow are not
// handled here; growth can invalidate borrowed pointers. clear retains capacity for reuse.
template <size_t Inline>
class SmallBuf {
    friend class IdleBuffers;

public:
    SmallBuf() : data_(inline_), cap_(Inline) {}
    ~SmallBuf() {
        if (data_ != inline_) std::free(data_);
    }
    SmallBuf(const SmallBuf&) = delete;
    SmallBuf& operator=(const SmallBuf&) = delete;

    char* data() { return data_; }
    const char* data() const { return data_; }
    size_t size() const { return len_; }
    bool empty() const { return len_ == 0; }
    void clear() { len_ = 0; }  // keeps the allocation for reuse
    size_t cap() const { return cap_; }

    // Advance length over n bytes already written past len_. Direct replies reach this through
    // sender retirement; Conn's append and WbEngine copy paths also use it. Capacity must already
    // cover the bytes. This plain length update supplies no cross-thread publication barrier.
    void commit_raw(size_t n) { len_ += n; }

    // Drops any heap growth and returns to the inline buffer. Called when a slot is recycled after
    // an unusually large reply, so one big reply does not permanently inflate every ring slot.
    void shrink_to_inline() {
        if (data_ != inline_) {
            std::free(data_);
            data_ = inline_;
            cap_ = Inline;
        }
        len_ = 0;
    }

    // WbEngine stages completed replies with conn.fill_buf().append(op.reply.data(),
    // op.reply.size()). A whole reply can be five bytes for +OK or value length plus RESP framing
    // for GET; it is not bounded by bytes_copy's short-copy ceiling. Keep the library copy here
    // so large replies do not pay that helper's length tests.
    void append(const char* src, size_t n) {
        if (len_ + n > cap_) grow(len_ + n);
        std::memcpy(data_ + len_, src, n);
        len_ += n;
    }
    void append(std::string_view s) { append(s.data(), s.size()); }
    void append(Slice s) { append(s.p, s.n); }
    // Literal overload, matching Op::Sink::append -- same contract, NUL excluded. It exists so the
    // resp.h reply helpers can be written once and compile to a store on whichever sink they are
    // instantiated with.
    template <size_t N>
    void append(const char (&lit)[N]) {
        static_assert(N >= 1, "append() takes a string literal");
        if constexpr (N - 1 <= kInlineLiteralMax) {
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
        cap_ = ncap;
    }
    char* data_;
    size_t len_ = 0;
    size_t cap_;
    char inline_[Inline];
};

}  // namespace tomo
