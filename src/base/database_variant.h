// Compile-time database identity shared by both server images. Makefile compiles the single-DB
// image with TOMO_SINGLE_DATABASE=1 and the tomo_db0 namespace; main.cc selects it at startup.
// KeyIdentity carries length alone there, and length plus namespace in the ordinary image.
#pragma once
#include <cstdint>
#include <type_traits>

// The single-keyspace runtime is compiled separately and selected once at boot.
// No mutable flag, thread-local load, or per-operation database test is involved.
#ifndef TOMO_SINGLE_DATABASE
#define TOMO_SINGLE_DATABASE 0
#endif

namespace tomo {
inline constexpr bool kSingleDatabase = TOMO_SINGLE_DATABASE != 0;
using KeyIdentity = std::conditional_t<kSingleDatabase, uint32_t, uint64_t>;
}
