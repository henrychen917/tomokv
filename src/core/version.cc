// Keep version presentation outside every execution-loop translation unit.
// The release link wraps only the C runtime's main reference; main.o and its
// include graph retain their original source and compiler settings.
#include "version.h"

#include <cstdio>
#include <cstring>

#if TOMO_SINGLE_DATABASE
extern "C" int __real_main(int argc, char** argv);

extern "C" [[gnu::cold, gnu::noinline]]
int __wrap_main(int argc, char** argv) {
    // Like Redis, --version/-v is an entry option (argv[1]), not a config
    // directive. Do not interpret option values or a config file's contents.
    const bool version = argc > 1 &&
        (!std::strcmp(argv[1], "--version") || !std::strcmp(argv[1], "-v"));
    std::printf("TomoKV %s (Redis %s compatible)\n",
                tomo::kTomoVersion, tomo::kRedisCompatVersion);
    if (version) return 0;
    return __real_main(argc, argv);
}
#endif

#if !TOMO_SINGLE_DATABASE
// PRE -> stable assertions shrinks the linked, suffix-merged .rodata by 1152
// bytes. Preserve the following sections' addresses; this is measured ELF size,
// not the sum of the removed literals. Only the last-linked variant owns it.
[[gnu::used, gnu::aligned(1)]] static const unsigned char assertion_rodata_pad[1152] = {};
#endif
