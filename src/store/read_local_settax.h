// read_local_settax.h -- internal bake-off selector for armed plain-SET allocation tax.
//
// This is deliberately compile-time rather than a CONFIG/command-line knob: production and every
// unqualified build retain the immutable read-local path (0), while an owner bake-off can select
// exactly one experimental implementation with
//   -DTOMO_READ_LOCAL_SET_TAX_VARIANT=1   (shard-sequence in-place overwrite)
//   -DTOMO_READ_LOCAL_SET_TAX_VARIANT=2   (post-QSBR same-class recycling)
#pragma once
#include <cstdint>

#ifndef TOMO_READ_LOCAL_SET_TAX_VARIANT
#define TOMO_READ_LOCAL_SET_TAX_VARIANT 0
#endif

namespace tomo {

enum class ReadLocalSetTaxVariant : uint8_t {
    Off = 0,
    SequenceOverwrite = 1,
    QsbrRecycle = 2,
};

static_assert(TOMO_READ_LOCAL_SET_TAX_VARIANT >= 0 &&
              TOMO_READ_LOCAL_SET_TAX_VARIANT <= 2,
              "TOMO_READ_LOCAL_SET_TAX_VARIANT must be 0 (off), 1 (sequence), or 2 (recycle)");

inline constexpr ReadLocalSetTaxVariant kReadLocalSetTaxVariant =
    static_cast<ReadLocalSetTaxVariant>(TOMO_READ_LOCAL_SET_TAX_VARIANT);

}  // namespace tomo
