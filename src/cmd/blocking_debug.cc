// Cold DEBUG parser for the blocked-XREAD schedule. No ordinary dispatch hooks.
#include "../base/numeric.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include <atomic>

namespace tomo {

std::atomic<uint32_t> debug_xread_hold{0};
std::atomic<uint32_t> debug_xread_stage{0};

// Entered through DEBUG's existing permission gate, after its established forms.
// Status: 1 = registration held, 2 = last Task held, 3 = IO refused that Task.
// Argument: 0 releases, 1 arms registration, 2 advances to the last-Task hold.
void debug_xread_registration_command(Op& op) {
    if (!op.arg(1).eq_icase("xread-registration-hold")) {
        reply_err(op.sink(), "ERR unknown subcommand or wrong number of arguments for 'debug' command");
        return;
    }
    if (op.argc() == 2) {
        reply_int(op.sink(), debug_xread_stage.load(std::memory_order_acquire));
        return;
    }
    int64_t stage = 0;
    if (op.argc() != 3 || !parse_i64(op.arg(2), stage) || stage < 0 || stage > 2) {
        reply_err(op.sink(), "ERR value is not an integer or out of range");
        return;
    }
    if (stage == 1) debug_xread_stage.store(0, std::memory_order_relaxed);
    debug_xread_hold.store(static_cast<uint32_t>(stage), std::memory_order_release);
    reply_ok(op.sink());
}

}  // namespace tomo
