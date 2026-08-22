// commands.cc — the v1 command table and its handlers.
//
// A handler runs on the worker that owns the key, with exclusive access to that shard's store. It
// never locks, never yields, and writes its reply as RESP bytes into op.reply. Adding a type later
// adds rows here; it does not change the machinery.
#include "command.h"
#include "../core/shard.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include "../store/kvobj.h"

#include <cstdlib>
#include <cstring>

namespace tomo {

// ---- helpers ------------------------------------------------------------------------------------
static bool parse_ll(Slice s, long long& out) {
    if (s.n == 0 || s.n > 20) return false;
    char tmp[24];
    std::memcpy(tmp, s.p, s.n);
    tmp[s.n] = '\0';
    char* end = nullptr;
    out = std::strtoll(tmp, &end, 10);
    return end == tmp + s.n;
}

// ---- handlers -----------------------------------------------------------------------------------
static void cmd_get(Shard& sh, Op& op) {
    KvObj* o = sh.store().find(op.hash, op.key());
    if (!o) { sh.stats().misses++; reply_nil(op.reply); return; }
    sh.stats().hits++;
    if (o->is_int()) { reply_int(op.reply, o->int_value()); return; }
    reply_bulk(op.reply, o->str_value());
}

static void cmd_set(Shard& sh, Op& op) {
    // v1 accepts SET key value only. The option surface (EX/PX/NX/XX/KEEPTTL/GET) is next, and it
    // stays single-shard — an expiry option that escapes into a multi-shard path was a real bug in
    // the fork.
    KvObj* o = kvobj_new_string(op.key(), op.arg(2));
    if (!o) { reply_err(op.reply, "ERR out of memory"); return; }
    if (!sh.store().insert(op.hash, o)) {
        kvobj_free(o);
        reply_err(op.reply, "ERR keyspace insert failed");
        return;
    }
    reply_ok(op.reply);
}

static void cmd_del(Shard& sh, Op& op) {
    // Single-key in v1. Multi-key DEL is class C — independent per key, fan out and count — and
    // needs the scatter-gather path, not a loop here.
    reply_int(op.reply, sh.store().erase(op.hash, op.key()) ? 1 : 0);
}

static void cmd_exists(Shard& sh, Op& op) {
    reply_int(op.reply, sh.store().find(op.hash, op.key()) ? 1 : 0);
}

static void cmd_incr(Shard& sh, Op& op) {
    KvObj* o = sh.store().find(op.hash, op.key());
    long long v = 0;
    if (o) {
        if (o->is_int()) v = o->int_value();
        else if (!parse_ll(o->str_value(), v)) {
            reply_err(op.reply, "ERR value is not an integer or out of range");
            return;
        }
    }
    v++;
    // TODO(int-encoding): store back as Enc::Int in place when the existing object already is one,
    // which makes a counter a pure in-place write with no allocation at all. Requires the in-place
    // update path; for now this reallocates and is the honest slow version.
    char buf[24];
    int n = std::snprintf(buf, sizeof(buf), "%lld", v);
    KvObj* no = kvobj_new_string(op.key(), Slice(buf, static_cast<uint32_t>(n)));
    if (!no) { reply_err(op.reply, "ERR out of memory"); return; }
    sh.store().insert(op.hash, no);
    reply_int(op.reply, v);
}

// Connection-local: never dispatched to a worker, so `sh` is unused.
static void cmd_ping(Shard&, Op& op) {
    if (op.argc() == 2) reply_bulk(op.reply, op.arg(1));
    else                reply_pong(op.reply);
}
static void cmd_echo(Shard&, Op& op)    { reply_bulk(op.reply, op.arg(1)); }
static void cmd_command(Shard&, Op& op) { op.reply.append("*0\r\n", 4); }

// ---- the table ----------------------------------------------------------------------------------
// arity: exact count including the command name; negative means "at least |arity|".
static const CommandSpec kTable[] = {
    // name       arity  flags                                      handler       first last step
    {"get",         2,   CmdFlags::Readonly,                        cmd_get,        1,  1,  1},
    {"set",         3,   CmdFlags::Write,                           cmd_set,        1,  1,  1},
    {"del",         2,   CmdFlags::Write,                           cmd_del,        1,  1,  1},
    {"exists",      2,   CmdFlags::Readonly,                        cmd_exists,     1,  1,  1},
    {"incr",        2,   CmdFlags::Write,                           cmd_incr,       1,  1,  1},
    {"ping",       -1,   CmdFlags::ConnLocal,                       cmd_ping,       0,  0,  0},
    {"echo",        2,   CmdFlags::ConnLocal,                       cmd_echo,       0,  0,  0},
    {"command",    -1,   CmdFlags::ConnLocal | CmdFlags::Admin,     cmd_command,    0,  0,  0},
};

const CommandSpec* command_lookup(Slice name) {
    // Linear scan over a tiny table. A perfect hash is a later optimisation and only if it shows up
    // in a profile — guessing that it matters is how you end up maintaining a hash for eight rows.
    for (const auto& c : kTable)
        if (name.eq_icase(c.name)) return &c;
    return nullptr;
}

}  // namespace tomo
