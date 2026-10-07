#pragma once

#include <array>
#include <cstdint>

namespace tomo {

class Server;

// Only boot, the main monitor thread and cold INFO/RESETSTAT paths use this state.
// The three rates are commands/s, input bytes/s and output bytes/s.
void info_stats_init(Server* server);
void info_stats_tick(Server& server);
std::array<uint64_t, 3> info_stats_rates();
uint64_t info_stats_observe_memory(uint64_t used_memory);
void info_stats_reset(uint64_t operations, uint64_t used_memory,
                      uint64_t input_bytes = 0, uint64_t output_bytes = 0);
const char* info_run_id();
const char* info_executable();
const char* info_config_file();

}  // namespace tomo
