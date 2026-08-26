// debug.h -- boot-gated DEBUG command permission helpers.
#pragma once

namespace tomo {

class Client;
class Op;
class Server;
class Shard;

void cmd_debug(Shard& shard, Op& op);
bool debug_command_allowed(const Server& server, const Client* client);
void reply_debug_command_denied(Op& op);

}  // namespace tomo
