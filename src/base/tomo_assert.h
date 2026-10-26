// Stable assertion ids keep source locations out of the executable. Resolve a
// failure id with the matching build/tomokv.asserts.tsv (archive it with the ELF).
#pragma once
#include <cassert>
#include <cstdint>

namespace tomo::detail {
// Hash the unexpanded condition spelling. C++ macro stringification removes
// comments; ignoring whitespace also makes wrapping and indentation immaterial.
consteval uint32_t assert_site_id(const char* text, uint32_t salt = 0) {
    uint32_t hash = 2166136261u ^ salt;
    for (; *text; ++text) {
        const unsigned char c = static_cast<unsigned char>(*text);
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r' || c == '\f' || c == '\v') continue;
        hash = (hash ^ c) * 16777619u;
    }
    return hash | 0x80000000u;
}
}  // namespace tomo::detail

// Preserve glibc's C++ conditional and its noreturn, nothrow four-argument call.
// Like assert(), disabled assertions do not evaluate their condition or id.
#ifdef NDEBUG
#define TOMO_ASSERT_ID(cond, id) (static_cast<void>(0))
#else
#define TOMO_ASSERT_ID(cond, id)                                                   \
    (static_cast<bool>(cond) ? void(0)                                             \
                            : __assert_fail("see tomokv.asserts", "tomokv", (id), "site"))
#endif
#define TOMO_ASSERT(cond) TOMO_ASSERT_ID(cond, ::tomo::detail::assert_site_id(#cond))
#define TOMO_ASSERT_SALT(cond, salt) TOMO_ASSERT_ID(cond, ::tomo::detail::assert_site_id(#cond, salt))
