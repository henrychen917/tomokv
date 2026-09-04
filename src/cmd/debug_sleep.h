// debug_sleep.h -- cold connection-timer lowering for DEBUG SLEEP.
//
// DEBUG SLEEP is connection-local: parking its owning IO/executor thread would stop unrelated
// clients (and, in 1s, every shard owned by that fused thread). The IO dispatcher asks this helper
// for a bounded timer plan and retains the unfinished Op in the connection's ROB until deadline.
// No ordinary command enters this path.
#pragma once
#include <cstdint>

namespace tomo {

class Client;
class Op;
class Server;

enum class DebugSleepResult : uint8_t { NotSleep, Handled, Deferred };

// Returns NotSleep for every DEBUG form except exact `DEBUG SLEEP seconds`. Handled means the
// helper wrote an immediate reply (permission/validation/zero); Deferred returns a positive,
// millisecond-rounded-up delay. The live client timeout supplies the safety ceiling; timeout=0
// uses the fixed one-second minimum ceiling rather than making every positive sleep invalid.
DebugSleepResult debug_sleep_prepare(Server& server, Client& client, Op& op,
                                     uint64_t& delay_ms);

}  // namespace tomo
