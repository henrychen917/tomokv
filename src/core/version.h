// Product and protocol version constants shared by the entry wrapper, configuration
// diagnostics and INFO consumers. Immutable string spellings are part of external output;
// this header owns no mutable state and has no fixed inclusion point.
#pragma once

namespace tomo {

// Product identity and Redis protocol compatibility are separate contracts.
// Clients parse the latter numerically when negotiating supported features.
inline constexpr const char* kTomoVersion = "1.0-cpp";
inline constexpr const char* kRedisCompatVersion = "7.4.10";

}  // namespace tomo
