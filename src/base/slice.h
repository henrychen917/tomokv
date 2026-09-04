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

    void append(const char* src, size_t n) {
        if (len_ + n > cap_) grow(len_ + n);
        std::memcpy(data_ + len_, src, n);
        len_ += n;
    }
    void append(std::string_view s) { append(s.data(), s.size()); }
    void append(Slice s)            { append(s.p, s.n); }
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
