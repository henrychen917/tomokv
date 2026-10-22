// Reproduce a published task whose summary bit has already been consumed.
// The periodic depth sweep must recover it even while a fused owner is busy
// polling a conflicting transaction, so the idle audit is never reached.
#include "src/core/thread.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>

using namespace tomo;
static void require(bool condition, const char* message) {
    if (!condition) { std::fprintf(stderr, "FAIL: %s\n", message); std::exit(1); }
}
int main(int argc, char** argv) {
    require(argc == 2, "1s|2s");
    const bool fused = std::strcmp(argv[1], "1s") == 0;
    ThreadCtx owner;
    owner.init(1, fused ? Role::Ifid : Role::Ex, 2, 0, 0);
    require(owner.init_task_inbox_local_fused(), "inbox allocation");
    if (fused) owner.bind_fused_executor_hooks(&owner, nullptr, nullptr);
    Task task{nullptr, 193, 7, nullptr};
    LoopSignals signals;
    require(owner.post_task_quiet(0, task, signals), "task published without summary");
    unsigned visits = 0;
    auto visit = [&](const Task& value) {
        require(value.op_id == 193 && value.shard == 7, "task identity preserved");
        ++visits;
    };
    require(owner.drain_tasks(visit) == 0 && visits == 0, "missing-summary window witnessed");
    require(owner.sample_depth(1000), "real periodic sweep ran");
    require(owner.drain_tasks(visit) == 1 && visits == 1,
            "busy task consumer must republish the missing summary");
    require(owner.drain_tasks(visit) == 0, "task executes exactly once");
    std::printf("PASS %s busy owner recovered a queued task without an idle turn\n", argv[1]);
}
