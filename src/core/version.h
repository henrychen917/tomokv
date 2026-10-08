#pragma once

namespace tomo {

// Product identity and Redis protocol compatibility are separate contracts.
// Clients parse the latter numerically when negotiating supported features.
inline constexpr const char* kTomoVersion = "1.0-cpp";
inline constexpr const char* kRedisCompatVersion = "7.4.10";

}  // namespace tomo
