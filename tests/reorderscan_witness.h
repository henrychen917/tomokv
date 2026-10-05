// Force-included only in serverless witness builds, never in release objects.
#pragma once
#include <cstdint>
namespace r7_scan_witness {
inline uint64_t visits = 0;
inline uint64_t constructions = 0;
}
#define TOMO_R7_SCAN_VISIT() (++::r7_scan_witness::visits)
#define TOMO_R7_SCAN_CONSTRUCT() (++::r7_scan_witness::constructions)
