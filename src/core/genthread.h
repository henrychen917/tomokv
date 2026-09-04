// Boot-selected fused runtime. Kept out of main.cc so its template instantiations cannot perturb
// the split loop translation unit's optimizer decisions.
#pragma once

#include <memory>
#include <vector>

namespace tomo {

class AofReplayPlan;
class LateUnixListener;
class Server;
class SnapshotLoadPlan;
class TlsContext;

int run_fused_server(Server& server, const SnapshotLoadPlan* aof_base_plan,
                     const std::vector<std::unique_ptr<AofReplayPlan>>& aof_plans,
                     const SnapshotLoadPlan* load_plan, TlsContext* tls_context,
                     LateUnixListener& unix_listener);

}  // namespace tomo
