// Runtime entry points called by main.cc and read-local diagnostics called by
// cmd/t_server.cc. Boot functions borrow the initialized Server and recovery
// plans through worker join; they transfer a bound Unix fd to its selected IO
// owner. Fused instantiations live outside main.cc to isolate compiler budgets.
#pragma once

#include <memory>
#include <string>
#include <vector>

namespace tomo {

class AofReplayPlan;
class LateUnixListener;
class Server;
class ShutdownReportFinalLine;
class SnapshotLoadPlan;
class TlsContext;

// Main-thread fused lifecycle in genthread.cc; reorder.cc supplies its generated
// counterpart. Recovery precedes listener activation and readiness publication.
int run_fused_server(Server& server, const SnapshotLoadPlan* aof_base_plan,
                     const std::vector<std::unique_ptr<AofReplayPlan>>& aof_plans,
                     const SnapshotLoadPlan* load_plan, TlsContext* tls_context,
                     LateUnixListener& unix_listener, ShutdownReportFinalLine& final_report);

// Selects the fused boot in reorder.cc before workers start. Keeping this choice
// outside genthread.cc isolates the FIFO hot loops from priority instantiations.
int run_fused_server_selected(Server& server, const SnapshotLoadPlan* aof_base_plan,
                              const std::vector<std::unique_ptr<AofReplayPlan>>& aof_plans,
                              const SnapshotLoadPlan* load_plan, TlsContext* tls_context,
                              LateUnixListener& unix_listener,
                              ShutdownReportFinalLine& final_report);

// Main-thread lifecycle in rl2s.cc: split placement with shard-less read-local IO
// and the ordinary owner loop. The read-local lane must already be armed.
int run_split_read_local_server(Server& server, const SnapshotLoadPlan* aof_base_plan,
                                const std::vector<std::unique_ptr<AofReplayPlan>>& aof_plans,
                                const SnapshotLoadPlan* load_plan, TlsContext* tls_context,
                                LateUnixListener& unix_listener,
                                ShutdownReportFinalLine& final_report);

// INFO-only diagnostics. The caller must test read_local_enabled() before this call.
void append_read_local_thread_info(std::string& body, const Server& server);

}  // namespace tomo
