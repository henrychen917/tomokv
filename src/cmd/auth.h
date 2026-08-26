// auth.h -- narrow IO hook for requirepass's pre-dispatch connection gate.
#pragma once

#include <cstdint>

namespace tomo {

class Client;
class IoLoop;
class Op;
class Server;
struct Slice;

// Called only after command lookup and arity validation, and only while requirepass is enabled.
// True means a complete NOAUTH reply was published locally.
bool auth_dispatch_entry(IoLoop& loop, Client& client, Op& op, uint32_t consumed);
void auth_publish_requirepass(Server& server, Slice password);
bool auth_password_matches(const Server& server, Slice password,
                           bool* auth_required = nullptr);

}  // namespace tomo
