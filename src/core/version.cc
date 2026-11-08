// Server-only entry wrapper and fixed read-only-data padding. The link wraps the C
// runtime main reference; only the single-database variant defines __wrap_main.
// The other, last-linked variant owns the padding that fixes following section addresses.
// Keep version presentation here, outside every execution-loop translation unit;
// wrapping main leaves main.o and its include graph unchanged.
#include "version.h"

#include <cstdio>
#include <cstring>

#if TOMO_SINGLE_DATABASE
extern "C" int __real_main(int argc, char** argv);

extern "C" [[gnu::cold, gnu::noinline]]
int __wrap_main(int argc, char** argv) {
    // Like Redis, --version/-v is an entry option (argv[1]), not a config
    // directive. Do not interpret option values or a config file's contents.
    const bool version =
        argc > 1 && (!std::strcmp(argv[1], "--version") || !std::strcmp(argv[1], "-v"));
    std::printf("TomoKV %s (Redis %s compatible)\n", tomo::kTomoVersion, tomo::kRedisCompatVersion);
    if (version) return 0;
    return __real_main(argc, argv);
}
#endif

#if !TOMO_SINGLE_DATABASE
// The stable-assertion conversion shrank suffix-merged linked .rodata by 1152 bytes.
// This padding restores that size so following sections keep their addresses. This is
// a measured linked-section difference, not a sum of source literal sizes; re-measure
// if .rodata contents change. Only the last-linked variant owns the padding.
[[gnu::used, gnu::aligned(1)]] static const unsigned char assertion_rodata_pad[1152] = {};
#endif
