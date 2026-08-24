// t_string.cc — string commands and type-agnostic keyspace commands.
//
// Handlers execute only on the shard owner and emit RESP through Op::Sink. The sole exceptions are
// rows marked ConnLocal: their handlers run on the connection's IO owner and touch only immutable
// server metadata or published shard counters.
#include "command.h"
#include "../core/shard.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include "../store/kvobj.h"

#include <climits>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace tomo {
namespace {

bool eq_icase(Slice s, const char* lit) {
    const size_t n = std::strlen(lit);
    if (s.n != n) return false;
    for (size_t i = 0; i < n; i++) {
        unsigned char a = static_cast<unsigned char>(s.p[i]);
        unsigned char b = static_cast<unsigned char>(lit[i]);
        if (a >= 'a' && a <= 'z') a = static_cast<unsigned char>(a - ('a' - 'A'));
        if (b >= 'a' && b <= 'z') b = static_cast<unsigned char>(b - ('a' - 'A'));
        if (a != b) return false;
    }
    return true;
}

// Kept for the existing INCR/SELECT behavior. Expiry parsing below is strict and overflow-aware.
bool parse_ll(Slice s, long long& out) {
    if (s.n == 0 || s.n > 20) return false;
    char tmp[24];
    std::memcpy(tmp, s.p, s.n);
    tmp[s.n] = '\0';
    char* end = nullptr;
    out = std::strtoll(tmp, &end, 10);
    return end == tmp + s.n;
}

bool parse_i64(Slice s, int64_t& out) {
    if (s.n == 0) return false;
    uint32_t pos = 0;
    bool negative = false;
    if (s.p[pos] == '-') {
        negative = true;
        if (++pos == s.n) return false;
    }
    uint64_t value = 0;
    const uint64_t limit = negative ? (uint64_t{1} << 63) : static_cast<uint64_t>(INT64_MAX);
    for (; pos < s.n; pos++) {
        const char ch = s.p[pos];
        if (ch < '0' || ch > '9') return false;
        const uint32_t digit = static_cast<uint32_t>(ch - '0');
        if (value > (limit - digit) / 10) return false;
        value = value * 10 + digit;
    }
    if (negative) {
        out = value == (uint64_t{1} << 63) ? INT64_MIN : -static_cast<int64_t>(value);
    } else {
        out = static_cast<int64_t>(value);
    }
    return true;
}

void reply_invalid_expire(Op& op, const char* command) {
    char msg[96];
    std::snprintf(msg, sizeof(msg), "ERR invalid expire time in '%s' command", command);
    reply_err(op.sink(), msg);
}

void clear_reply(Op& op) {
    op.direct_len = 0;
    op.reply.clear();
}

void reply_string_bulk(Op& op, const KvObj* o) {
    if (!o) { reply_nil(op.sink()); return; }
    if (o->is_int()) {
        char text[24];
        const uint32_t n = i64_to_dec(text, o->int_value());
        reply_bulk(op.sink(), Slice(text, n));
        return;
    }
    reply_bulk(op.sink(), o->str_value());
}

// GET alone may borrow FlatStore bytes. GETEX/GETDEL/SET GET copy before mutation; extending the
// borrow protocol to mutation replies would turn a string-only fast path into collection policy.
void cmd_get(Shard& sh, Op& op) {
    KvObj* o = sh.store().find(op.hash, op.key());
    if (!o) { sh.stats().misses++; reply_nil(op.sink()); return; }
    sh.stats().hits++;
    auto sink = op.sink();
    if (!obj_type_check(o, Type::String, sink)) return;
    if (o->is_int()) { reply_int(op.sink(), o->int_value()); return; }
    const Slice value = o->str_value();
    const uint32_t zc_min = sh.zc_min();
    if (zc_min && value.n >= zc_min) {
        reply_bulk_header(op.sink(), value.n);
        op.zc_ptr = value.p;
        op.zc_len = value.n;
        op.zc_shard = sh.id();
        sh.store().borrow(value.p);
        return;
    }
    reply_bulk(op.sink(), value);
}

enum class ExpireKind : uint8_t { None, Ex, Px, Exat, Pxat };

struct SetOptions {
    bool nx = false;
    bool xx = false;
    bool get = false;
    bool keep_ttl = false;
    ExpireKind expire_kind = ExpireKind::None;
    int64_t expire_at_ms = -1;
};

bool expiry_at(Shard& sh, Slice arg, ExpireKind kind, int64_t& out) {
    int64_t value = 0;
    if (!parse_i64(arg, value) || value <= 0) return false;
    const bool seconds = kind == ExpireKind::Ex || kind == ExpireKind::Exat;
    if (seconds) {
        if (value > INT64_MAX / 1000) return false;
        value *= 1000;
    }
    if (kind == ExpireKind::Ex || kind == ExpireKind::Px) {
        if (value > INT64_MAX - sh.now_ms()) return false;
        value += sh.now_ms();
    }
    if (value <= 0) return false;
    out = value;
    return true;
}

bool parse_set_options(Shard& sh, Op& op, SetOptions& options) {
    Slice expire_arg;
    for (uint32_t i = 3; i < op.argc(); i++) {
        const Slice arg = op.arg(i);
        if (eq_icase(arg, "NX") && !options.xx) {
            options.nx = true;
        } else if (eq_icase(arg, "XX") && !options.nx) {
            options.xx = true;
        } else if (eq_icase(arg, "GET")) {
            options.get = true;
        } else if (eq_icase(arg, "KEEPTTL") && options.expire_kind == ExpireKind::None) {
            options.keep_ttl = true;
        } else {
            ExpireKind kind = ExpireKind::None;
            if (eq_icase(arg, "EX")) kind = ExpireKind::Ex;
            else if (eq_icase(arg, "PX")) kind = ExpireKind::Px;
            else if (eq_icase(arg, "EXAT")) kind = ExpireKind::Exat;
            else if (eq_icase(arg, "PXAT")) kind = ExpireKind::Pxat;
            if (kind == ExpireKind::None || options.keep_ttl || i + 1 >= op.argc() ||
                (options.expire_kind != ExpireKind::None && options.expire_kind != kind)) {
                reply_syntax(op.sink());
                return false;
            }
            options.expire_kind = kind;
            expire_arg = op.arg(++i);
        }
    }
    if (options.expire_kind != ExpireKind::None &&
        !expiry_at(sh, expire_arg, options.expire_kind, options.expire_at_ms)) {
        reply_invalid_expire(op, "set");
        return false;
    }
    return true;
}

void cmd_set(Shard& sh, Op& op) {
    // Preserve the allocation-free, byte-identical v1 path for SET key value.
    if (op.argc() == 3) {
        if (sh.store().try_overwrite(op.hash, op.key(), op.arg(2))) {
            reply_ok(op.sink());
            return;
        }
        KvObj* o = kvobj_new_string(op.key(), op.arg(2));
        if (!o) { reply_err(op.sink(), "ERR out of memory"); return; }
        if (!sh.store().insert(op.hash, o)) {
            kvobj_free(o);
            reply_err(op.sink(), "ERR keyspace insert failed");
            return;
        }
        reply_ok(op.sink());
        return;
    }

    SetOptions options;
    if (!parse_set_options(sh, op, options)) return;
    KvObj* old = sh.store().find(op.hash, op.key());
    if (options.get) {
        auto sink = op.sink();
        if (!obj_type_check(old, Type::String, sink)) return;
        reply_string_bulk(op, old);
    }
    if ((options.nx && old) || (options.xx && !old)) {
        if (!options.get) reply_nil(op.sink());
        return;
    }

    int64_t expire = options.expire_at_ms;
    if (options.keep_ttl && old && (old->flags & KvObjFlags::HasTtl))
        expire = old->expire_at_ms();
    // Redis treats an already elapsed absolute SET deadline as set-then-expire: the old value is
    // removed, no dead replacement is left for DBSIZE/active expiry, and GET (if requested) keeps
    // the reply copied above. Relative EX/PX cannot reach here with a non-future deadline.
    if (expire != -1 && expire <= sh.now_ms()) {
        if (old) sh.store().erase(op.hash, op.key());
        if (!options.get) reply_ok(op.sink());
        return;
    }
    KvObj* replacement = kvobj_new_string(op.key(), op.arg(2), expire);
    if (!replacement) {
        if (options.get) clear_reply(op);
        reply_err(op.sink(), "ERR out of memory");
        return;
    }
    if (!sh.store().insert(op.hash, replacement)) {
        kvobj_free(replacement);
        if (options.get) clear_reply(op);
        reply_err(op.sink(), "ERR keyspace insert failed");
        return;
    }
    if (!options.get) reply_ok(op.sink());
}

bool parse_getex_options(Op& op, ExpireKind& kind, Slice& expire_arg, bool& persist) {
    if (op.argc() == 2) return true;
    if (op.argc() == 3 && eq_icase(op.arg(2), "PERSIST")) {
        persist = true;
        return true;
    }
    if (op.argc() != 4) { reply_syntax(op.sink()); return false; }
    if (eq_icase(op.arg(2), "EX")) kind = ExpireKind::Ex;
    else if (eq_icase(op.arg(2), "PX")) kind = ExpireKind::Px;
    else if (eq_icase(op.arg(2), "EXAT")) kind = ExpireKind::Exat;
    else if (eq_icase(op.arg(2), "PXAT")) kind = ExpireKind::Pxat;
    else { reply_syntax(op.sink()); return false; }
    expire_arg = op.arg(3);
    return true;
}

void cmd_getex(Shard& sh, Op& op) {
    ExpireKind kind = ExpireKind::None;
    Slice expire_arg;
    bool persist = false;
    if (!parse_getex_options(op, kind, expire_arg, persist)) return;

    KvObj* o = sh.store().find(op.hash, op.key());
    if (!o) { reply_nil(op.sink()); return; }
    auto sink = op.sink();
    if (!obj_type_check(o, Type::String, sink)) return;

    int64_t at = -1;
    if (kind != ExpireKind::None && !expiry_at(sh, expire_arg, kind, at)) {
        reply_invalid_expire(op, "getex");
        return;
    }
    reply_string_bulk(op, o);

    FlatStore::TtlResult result = FlatStore::TtlResult::NoChange;
    if (kind != ExpireKind::None && at <= sh.now_ms()) {
        sh.store().erase(op.hash, op.key());
        return;
    } else if (kind != ExpireKind::None) {
        result = sh.store().set_expire(op.hash, op.key(), at);
    } else if (persist) {
        result = sh.store().persist(op.hash, op.key());
    }
    if (result == FlatStore::TtlResult::Oom) {
        clear_reply(op);
        reply_err(op.sink(), "ERR out of memory");
    }
}

void cmd_getdel(Shard& sh, Op& op) {
    KvObj* o = sh.store().find(op.hash, op.key());
    if (!o) { reply_nil(op.sink()); return; }
    auto sink = op.sink();
    if (!obj_type_check(o, Type::String, sink)) return;
    reply_string_bulk(op, o);
    sh.store().erase(op.hash, op.key());
}

void cmd_del(Shard& sh, Op& op) {
    reply_int(op.sink(), sh.store().erase(op.hash, op.key()) ? 1 : 0);
}

void cmd_exists(Shard& sh, Op& op) {
    reply_int(op.sink(), sh.store().find(op.hash, op.key()) ? 1 : 0);
}

void cmd_incr(Shard& sh, Op& op) {
    KvObj* o = sh.store().find(op.hash, op.key());
    long long value = 0;
    int64_t expire = -1;
    if (o) {
        auto sink = op.sink();
        if (!obj_type_check(o, Type::String, sink)) return;
        if (o->is_int()) value = o->int_value();
        else if (!parse_ll(o->str_value(), value)) {
            reply_err(op.sink(), "ERR value is not an integer or out of range");
            return;
        }
        if (value == LLONG_MAX) {
            reply_err(op.sink(), "ERR increment or decrement would overflow");
            return;
        }
        expire = o->expire_at_ms();
    }
    value++;
    char buf[24];
    int n = std::snprintf(buf, sizeof(buf), "%lld", value);
    KvObj* replacement = kvobj_new_string(op.key(), Slice(buf, static_cast<uint32_t>(n)), expire);
    if (!replacement) { reply_err(op.sink(), "ERR out of memory"); return; }
    sh.store().insert(op.hash, replacement);
    reply_int(op.sink(), value);
}

enum class ExpireCondition : uint8_t { Always, Nx, Xx, Gt, Lt };

bool parse_expire_condition(Op& op, ExpireCondition& condition) {
    if (op.argc() == 3) return true;
    if (eq_icase(op.arg(3), "NX")) condition = ExpireCondition::Nx;
    else if (eq_icase(op.arg(3), "XX")) condition = ExpireCondition::Xx;
    else if (eq_icase(op.arg(3), "GT")) condition = ExpireCondition::Gt;
    else if (eq_icase(op.arg(3), "LT")) condition = ExpireCondition::Lt;
    else { reply_syntax(op.sink()); return false; }
    return true;
}

void expire_generic(Shard& sh, Op& op, bool absolute, bool seconds, const char* name) {
    ExpireCondition condition = ExpireCondition::Always;
    if (!parse_expire_condition(op, condition)) return;
    int64_t when = 0;
    if (!parse_i64(op.arg(2), when)) { reply_invalid_expire(op, name); return; }
    if (seconds) {
        if (when > INT64_MAX / 1000 || when < INT64_MIN / 1000) {
            reply_invalid_expire(op, name); return;
        }
        when *= 1000;
    }
    if (!absolute) {
        if (when > INT64_MAX - sh.now_ms()) { reply_invalid_expire(op, name); return; }
        when += sh.now_ms();
    }

    KvObj* o = sh.store().find(op.hash, op.key());
    if (!o) { reply_int(op.sink(), 0); return; }
    const int64_t current = o->expire_at_ms();
    if ((condition == ExpireCondition::Nx && current != -1) ||
        (condition == ExpireCondition::Xx && current == -1) ||
        (condition == ExpireCondition::Gt && (current == -1 || when <= current)) ||
        (condition == ExpireCondition::Lt && current != -1 && when >= current)) {
        reply_int(op.sink(), 0);
        return;
    }
    if (when <= sh.now_ms()) {
        sh.store().erase(op.hash, op.key());
        reply_int(op.sink(), 1);
        return;
    }
    const FlatStore::TtlResult result = sh.store().set_expire(op.hash, op.key(), when);
    if (result == FlatStore::TtlResult::Oom) {
        reply_err(op.sink(), "ERR out of memory");
        return;
    }
    reply_int(op.sink(), result == FlatStore::TtlResult::Updated ? 1 : 0);
}

void cmd_expire(Shard& sh, Op& op)    { expire_generic(sh, op, false, true,  "expire"); }
void cmd_pexpire(Shard& sh, Op& op)   { expire_generic(sh, op, false, false, "pexpire"); }
void cmd_expireat(Shard& sh, Op& op)  { expire_generic(sh, op, true,  true,  "expireat"); }
void cmd_pexpireat(Shard& sh, Op& op) { expire_generic(sh, op, true,  false, "pexpireat"); }

int64_t rounded_seconds(int64_t ms) {
    return ms / 1000 + ((ms % 1000) >= 500 ? 1 : 0);
}

void ttl_generic(Shard& sh, Op& op, bool milliseconds, bool absolute) {
    KvObj* o = sh.store().find(op.hash, op.key());
    if (!o) { reply_int(op.sink(), -2); return; }
    const int64_t expire = o->expire_at_ms();
    if (expire == -1) { reply_int(op.sink(), -1); return; }
    int64_t value = absolute ? expire : expire - sh.now_ms();
    if (value < 0) value = 0;
    reply_int(op.sink(), milliseconds ? value : rounded_seconds(value));
}

void cmd_ttl(Shard& sh, Op& op)         { ttl_generic(sh, op, false, false); }
void cmd_pttl(Shard& sh, Op& op)        { ttl_generic(sh, op, true,  false); }
void cmd_expiretime(Shard& sh, Op& op)  { ttl_generic(sh, op, false, true); }
void cmd_pexpiretime(Shard& sh, Op& op) { ttl_generic(sh, op, true,  true); }

void cmd_persist(Shard& sh, Op& op) {
    const FlatStore::TtlResult result = sh.store().persist(op.hash, op.key());
    if (result == FlatStore::TtlResult::Oom) {
        reply_err(op.sink(), "ERR out of memory");
        return;
    }
    reply_int(op.sink(), result == FlatStore::TtlResult::Updated ? 1 : 0);
}

const char* type_name(const KvObj* o) {
    if (!o) return "none";
    switch (static_cast<Type>(o->type)) {
        case Type::String: return "string";
        case Type::Hash:   return "hash";
        case Type::List:   return "list";
        case Type::Set:    return "set";
        case Type::Zset:   return "zset";
    }
    return "none";
}

void cmd_type(Shard& sh, Op& op) {
    reply_simple(op.sink(), type_name(sh.store().find(op.hash, op.key())));
}

const char* collection_encoding(const KvObj* o) {
    CollectionEncoding encoding = CollectionEncoding::Compact;
    switch (static_cast<Type>(o->type)) {
        case Type::Hash: encoding = static_cast<HashVal*>(o->external_ptr())->encoding(); break;
        case Type::List: encoding = static_cast<ListVal*>(o->external_ptr())->encoding(); break;
        case Type::Set:  encoding = static_cast<SetVal*>(o->external_ptr())->encoding(); break;
        case Type::Zset: encoding = static_cast<ZsetVal*>(o->external_ptr())->encoding(); break;
        case Type::String: return o->is_int() ? "int" : "raw";
    }
    switch (encoding) {
        case CollectionEncoding::Compact:   return "compact";
        case CollectionEncoding::Hashtable: return "hashtable";
        case CollectionEncoding::Deque:     return "deque";
        case CollectionEncoding::Btree:     return "btree";
    }
    return "unknown";
}

void cmd_object(Shard& sh, Op& op) {
    if (!eq_icase(op.arg(1), "ENCODING")) { reply_syntax(op.sink()); return; }
    KvObj* o = sh.store().find(op.hash, op.arg(2));
    if (!o) { reply_nil(op.sink()); return; }
    const char* name = collection_encoding(o);
    reply_bulk(op.sink(), Slice(name, static_cast<uint32_t>(std::strlen(name))));
}

static const CommandSpec kTable[] = {
    // name          min max flags                                  handler          first last step
    {"GET",           2,  2,  CmdFlags::Readonly,                    cmd_get,          1,  1,  1},
    {"SET",           3, -1,  CmdFlags::Write,                       cmd_set,          1,  1,  1},
    {"GETEX",         2,  4,  CmdFlags::Write,                       cmd_getex,        1,  1,  1},
    {"GETDEL",        2,  2,  CmdFlags::Write,                       cmd_getdel,       1,  1,  1},
    {"DEL",           2,  2,  CmdFlags::Write,                       cmd_del,          1,  1,  1},
    {"EXISTS",        2,  2,  CmdFlags::Readonly,                    cmd_exists,       1,  1,  1},
    {"INCR",          2,  2,  CmdFlags::Write,                       cmd_incr,         1,  1,  1},
    {"EXPIRE",        3,  4,  CmdFlags::Write,                       cmd_expire,       1,  1,  1},
    {"PEXPIRE",       3,  4,  CmdFlags::Write,                       cmd_pexpire,      1,  1,  1},
    {"EXPIREAT",      3,  4,  CmdFlags::Write,                       cmd_expireat,     1,  1,  1},
    {"PEXPIREAT",     3,  4,  CmdFlags::Write,                       cmd_pexpireat,    1,  1,  1},
    {"TTL",           2,  2,  CmdFlags::Readonly,                    cmd_ttl,          1,  1,  1},
    {"PTTL",          2,  2,  CmdFlags::Readonly,                    cmd_pttl,         1,  1,  1},
    {"PERSIST",       2,  2,  CmdFlags::Write,                       cmd_persist,      1,  1,  1},
    {"EXPIRETIME",    2,  2,  CmdFlags::Readonly,                    cmd_expiretime,   1,  1,  1},
    {"PEXPIRETIME",   2,  2,  CmdFlags::Readonly,                    cmd_pexpiretime,  1,  1,  1},
    {"TYPE",          2,  2,  CmdFlags::Readonly,                    cmd_type,         1,  1,  1},
    {"OBJECT",        3,  3,  CmdFlags::Readonly | CmdFlags::Admin,  cmd_object,       2,  2,  1},
};

}  // namespace

CommandTable string_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
