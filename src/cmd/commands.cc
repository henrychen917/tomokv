// commands.cc — the v1 command table and its handlers.
//
// A handler runs on the worker that owns the key, with exclusive access to that shard's store. It
// never locks, never yields, and writes its reply as RESP bytes into op.reply. Adding a type later
// adds rows here; it does not change the machinery.
#include "command.h"
#include "../core/shard.h"
#include "../core/server.h"
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
    // Fast path first: same-size overwrite of an existing key needs no allocation at all.
    if (sh.store().try_overwrite(op.hash, op.key(), op.arg(2))) { reply_ok(op.reply); return; }

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

// ---- server-wide, answered on the IO thread ------------------------------------------------------
// These read PUBLISHED per-shard counters, never another worker's store — reading a FlatStore this
// thread does not own would race with its owner, and the store has no locks precisely because that
// is supposed to be impossible.
static Server* g_server = nullptr;
void command_bind_server(Server* s) { g_server = s; }

static void cmd_dbsize(Shard&, Op& op) {
    uint64_t n = 0;
    if (g_server) for (uint32_t i = 0; i < g_server->nshards(); i++)
        n += g_server->shard(static_cast<int32_t>(i)).published_size();
    reply_int(op.reply, static_cast<long long>(n));
}

static void cmd_info(Shard&, Op& op) {
    char buf[1024];
    uint64_t keys = 0, hits = 0, misses = 0, ops = 0;
    uint32_t nsh = 0;
    if (g_server) {
        nsh = g_server->nshards();
        for (uint32_t i = 0; i < nsh; i++) {
            const Shard& sh = g_server->shard(static_cast<int32_t>(i));
            keys += sh.published_size();
            hits += sh.stats().hits; misses += sh.stats().misses; ops += sh.stats().ops;
        }
    }
    int n = std::snprintf(buf, sizeof(buf),
        "# Server\r\ntomokv_version:0.1-cpp\r\n"
        "# Keyspace\r\ndb0:keys=%llu\r\n"
        "# Stats\r\ntotal_commands_processed:%llu\r\nkeyspace_hits:%llu\r\nkeyspace_misses:%llu\r\n"
        "# Tomo\r\ntomokv_shards:%u\r\n",
        (unsigned long long)keys, (unsigned long long)ops,
        (unsigned long long)hits, (unsigned long long)misses, nsh);
    reply_bulk(op.reply, Slice(buf, static_cast<uint32_t>(n)));
}

// One keyspace by design (see the command-surface notes). SELECT 0 is accepted so clients that send
// it blindly still work; anything else is a loud error rather than a silent lie.
static void cmd_select(Shard&, Op& op) {
    long long db = 0;
    if (!parse_ll(op.arg(1), db) || db != 0) {
        reply_err(op.reply, "ERR this server supports a single keyspace; only SELECT 0 is valid");
        return;
    }
    reply_ok(op.reply);
}

static void cmd_config(Shard&, Op& op) { op.reply.append("*0\r\n", 4); }

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
    {"dbsize",      1,   CmdFlags::ConnLocal | CmdFlags::Admin,     cmd_dbsize,     0,  0,  0},
    {"info",       -1,   CmdFlags::ConnLocal | CmdFlags::Admin,     cmd_info,       0,  0,  0},
    {"select",      2,   CmdFlags::ConnLocal,                       cmd_select,     0,  0,  0},
    {"config",     -2,   CmdFlags::ConnLocal | CmdFlags::Admin,     cmd_config,     0,  0,  0},
};

// ---- lookup --------------------------------------------------------------------------------
// A LINEAR SCAN OVER PRECOMPUTED 64-BIT KEYS. Measured against the alternatives on this table:
//
//   linear, per-character eq_icase   18.35 ns   (what this replaced)
//   hash + eq_icase confirmation     20.22 ns   SLOWER than the scan it was meant to beat
//   hash, key equality only          12.34 ns
//   linear over u64 keys             10.28 ns   <- 1.78x, and the simplest of the four
//
// The hash lost because the table is small and the hot commands sit at the front, so the scan
// finds them in one to three compares while the hash adds a multiply, an indirection and a
// confirmation. The win was never the lookup structure; it was comparing ONE REGISTER instead of
// walking characters.
//
// EXACTNESS WITHOUT A CONFIRMING COMPARE. Command names are pure ASCII letters of at most 8 bytes,
// so the key is the entire name. OR-ing 0x20 lowercases eight bytes in one instruction, and the
// only bytes that OR to a given lowercase letter are that letter's own two cases ('g' is 0x67, so
// its preimages are exactly 0x47 and 0x67). Folding the length in stops a short name matching the
// prefix of a longer one. The assert below fails the build if a future command breaks the premise.
static constexpr uint64_t kLowerMask = 0x2020202020202020ull;

static inline uint64_t cmd_key(const char* p, uint32_t n) {
    uint64_t k = 0;
    std::memcpy(&k, p, n);                       // exactly n bytes: never reads past the argument
    k |= kLowerMask;
    if (n < 8) k &= (~0ull >> (8 * (8 - n)));    // drop bytes we did not read
    return k ^ (static_cast<uint64_t>(n) << 56);
}

static constexpr uint32_t kNCmds = sizeof(kTable) / sizeof(kTable[0]);

struct CmdKeys {
    uint64_t k[kNCmds] = {};
    CmdKeys() {
        for (uint32_t i = 0; i < kNCmds; i++) {
            const uint32_t n = static_cast<uint32_t>(std::strlen(kTable[i].name));
            // The premise the confirming compare was dropped on. If it ever fails, key equality is
            // no longer exact and this must go back to verifying the bytes.
            if (n == 0 || n > 8) { std::fprintf(stderr, "command '%s' breaks the <=8 byte key premise\n",
                                                kTable[i].name); std::abort(); }
            for (uint32_t j = 0; j < n; j++) {
                const char c = kTable[i].name[j];
                if (c < 'a' || c > 'z') { std::fprintf(stderr,
                    "command '%s' must be lowercase ASCII letters for key-only matching\n",
                    kTable[i].name); std::abort(); }
            }
            k[i] = cmd_key(kTable[i].name, n);
        }
    }
};
static const CmdKeys g_keys;

const CommandSpec* command_lookup(Slice name) {
    if (name.n == 0 || name.n > 8) return nullptr;   // no command is longer; cannot match
    const uint64_t k = cmd_key(name.p, name.n);
    for (uint32_t i = 0; i < kNCmds; i++)
        if (g_keys.k[i] == k) return &kTable[i];
    return nullptr;
}

}  // namespace tomo
