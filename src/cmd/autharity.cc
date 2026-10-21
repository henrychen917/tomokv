// Redis's advertised arity precedes AUTH; handler grammar follows it. Cold only.
#include "auth.h"
#include "command.h"
#include "cmdmeta.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include <string>

namespace tomo {

bool auth_arity_reply(Op& op, const CommandSpec& spec, bool unauthenticated,
                      bool outer_rejected) {
    // Owner-defined TomoKV extension, not an invalid Redis request. Its normal
    // authorization gate still applies; preserve the authenticated exact census.
    if (op.cmd_name().eq_icase("dbsize") && op.argc() == 2 &&
        op.arg(1).eq_icase("now")) return false;
    const CommandMetadata* metadata = command_metadata_resolve(op, 0);
    if (!metadata) {
        // A recognized container with an unknown child fails command lookup,
        // before either arity or AUTH (Redis processCommand).
        if (op.argc() > 1 && command_metadata_for(spec)) {
            std::string message = "ERR unknown subcommand '";
            message.append(op.arg(1).p, op.arg(1).n);
            message += "'. Try ";
            message += spec.name;
            message += " HELP.";
            reply_err(op.sink(), message.c_str());
            return true;
        }
        return false;
    }
    if (!command_metadata_arity_ok(*metadata, op.argc())) {
        const Slice name = command_metadata_name(*metadata);
        std::string message = op.cmd_name().eq_icase("exec")
            ? "EXECABORT Transaction discarded because of: wrong number of arguments for '"
            : "ERR wrong number of arguments for '";
        message.append(name.p, name.n);
        message += "' command";
        reply_err(op.sink(), message.c_str());
        return true;
    }
    const Slice name = op.cmd_name();
    if (outer_rejected && unauthenticated && !name.eq_icase("auth") && !name.eq_icase("hello") &&
        !name.eq_icase("reset") && !name.eq_icase("quit")) {
        reply_err(op.sink(), "NOAUTH Authentication required.");
        return true;
    }
    if (outer_rejected && name.eq_icase("auth")) {
        reply_syntax(op.sink());
        return true;
    }
    return false;
}

const char* auth_noauth_error(const Op& op) {
    return op.cmd_name().eq_icase("exec")
        ? "EXECABORT Transaction discarded because of: NOAUTH Authentication required."
        : "NOAUTH Authentication required.";
}

}  // namespace tomo
