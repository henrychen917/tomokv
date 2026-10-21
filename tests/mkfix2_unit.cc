// Completed MSET metadata must enter the unchanged WB rule and retain IO cleanup.
// No worker loops or sockets. Build with the same standalone dependencies as wbland_unit.
#include <cstdio>
#include <cstdlib>
#include "src/core/config.h"
using namespace tomo;
static void require(bool ok, const char* why) {
    if (!ok) { std::fprintf(stderr, "FAIL mkfix2: %s\n", why); std::exit(1); }
}
void tomo::multi_session_destroy(MultiSession* p) { require(!p, "unexpected MULTI session"); }
int main() {
    for (unsigned n : {8u, 32u, 64u}) for (bool coded : {false, true}) {
        Client c(-1);
        for (unsigned i = 0; i < n; ++i) {
            Op* op = c.rob().acquire<true>();
            require(op, "ROB capacity");
            c.rob().publish();
            op->reply_code_ok_ = coded;
            op->state.store(i ? OpState::Issued : OpState::Done);
        }
        Op& head = c.rob().at(0);
        auto* state = reinterpret_cast<ScatterState*>(uintptr_t{64});
        head.attach_scatter_state(state);
        require(!wb_rule::defer(c), "opaque scatter keeps its existing serve exit");
        reply_ok(head.sink());
        head.zc_shard = Op::kScatterReplyMarker;
        require(head.scatter_state() == state, "completed scatter keeps its retire hook");
        require(wb_rule::reply_bytes(head) == 5, "complete MSET exposes exactly five bytes");
        require(wb_rule::defer(c), "one completed MSET cannot open a deep batch");
        require(!wb_rule::defer(c, 0), "policy zero still serves immediately");
        for (unsigned i = 1; i < n / 2; ++i) c.rob().at(i).state.store(OpState::Done);
        c.wb_deferrals() = wb_rule::kCompleteVisits;
        require(!wb_rule::defer(c), "unchanged half rule opens the ready prefix");
        head.detach_scatter_state();
        require(!head.has_scatter_state(), "retirement detaches both scatter forms");
    }
    std::puts("PASS mkfix2 completed-scatter WB contract");
}
