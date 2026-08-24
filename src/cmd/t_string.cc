// t_string.cc — string commands and type-agnostic keyspace commands.
//
// Handlers execute only on the shard owner and emit RESP through Op::Sink. The sole exceptions are
// rows marked ConnLocal: their handlers run on the connection's IO owner and touch only immutable
// server metadata or published shard counters.
#include "command.h"
#include "../core/shard.h"
#include "../core/server.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include "../store/kvobj.h"

#include <algorithm>
#include <cerrno>
#include <cctype>
#include <climits>
#include <cmath>
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

inline constexpr uint64_t kProtoMaxBulkLen = 512ull * 1024 * 1024;
inline constexpr size_t kLongDoubleChars = 5 * 1024;

// Kept for SELECT behavior. String integer commands use the strict Redis parser below.
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
    // Redis's string2ll accepts only the representation that formatting the resulting integer
    // produces again: no leading '+', leading zeroes, or negative zero.
    if (s.n == 0 || s.n >= 32) return false;
    uint32_t pos = 0;
    bool negative = false;
    if (s.p[pos] == '-') {
        negative = true;
        if (++pos == s.n) return false;
    }
    if (s.p[pos] == '0') {
        if (negative || pos + 1 != s.n) return false;
        out = 0;
        return true;
    }
    if (s.p[pos] < '1' || s.p[pos] > '9') return false;
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

bool parse_long_double(Slice s, long double& out) {
    if (s.n == 0 || s.n >= kLongDoubleChars) return false;
    char text[kLongDoubleChars];
    std::memcpy(text, s.p, s.n);
    text[s.n] = '\0';

    errno = 0;
    char* end = nullptr;
    const long double value = std::strtold(text, &end);
    if (std::isspace(static_cast<unsigned char>(text[0])) || end != text + s.n ||
        (errno == ERANGE && (std::isinf(value) || std::fpclassify(value) == FP_ZERO)) ||
        errno == EINVAL || std::isnan(value)) {
        return false;
    }
    out = value;
    return true;
}

uint32_t format_long_double(char* text, size_t capacity, long double value) {
    // Redis's LD_STR_HUMAN mode intentionally uses fixed notation with 17 fractional digits,
    // trims the fractional zero suffix, and canonicalizes negative zero.
    int n = std::snprintf(text, capacity, "%.17Lf", value);
    if (n < 0 || static_cast<size_t>(n) >= capacity) return 0;
    if (char* dot = static_cast<char*>(std::memchr(text, '.', static_cast<size_t>(n)))) {
        char* end = text + n;
        while (end > dot + 1 && end[-1] == '0') end--;
        if (end == dot + 1) end = dot;
        n = static_cast<int>(end - text);
    }
    if (n == 2 && text[0] == '-' && text[1] == '0') {
        text[0] = '0';
        n = 1;
    }
    text[n] = '\0';
    return static_cast<uint32_t>(n);
}

Slice string_bytes(const KvObj* o, char (&integer)[24]) {
    if (!o->is_int()) return o->str_value();
    return Slice(integer, i64_to_dec(integer, o->int_value()));
}

enum class StoreResult : uint8_t { Stored, Oom, InsertFailed };

void clear_reply(Op& op);

StoreResult store_string(Shard& sh, Slice key, uint64_t hash, Slice value, int64_t expire_at_ms,
                         bool integer_encode) {
    int64_t integer = 0;
    if (integer_encode && parse_i64(value, integer)) {
        KvObj* replacement = kvobj_new_int(key, integer, expire_at_ms);
        if (!replacement) return StoreResult::Oom;
        if (!sh.store().insert(hash, replacement)) {
            kvobj_free(replacement);
            return StoreResult::InsertFailed;
        }
        return StoreResult::Stored;
    }

    // try_overwrite is the only in-place raw mutation. It rejects TTL-bearing and borrowed values;
    // the replacement path below then lets FlatStore retain any borrowed old allocation.
    if (expire_at_ms == -1 && sh.store().try_overwrite(hash, key, value))
        return StoreResult::Stored;

    KvObj* replacement = kvobj_new_string(key, value, expire_at_ms);
    if (!replacement) return StoreResult::Oom;
    if (!sh.store().insert(hash, replacement)) {
        kvobj_free(replacement);
        return StoreResult::InsertFailed;
    }
    return StoreResult::Stored;
}

StoreResult store_integer(Shard& sh, Slice key, uint64_t hash, int64_t value,
                          int64_t expire_at_ms) {
    KvObj* replacement = kvobj_new_int(key, value, expire_at_ms);
    if (!replacement) return StoreResult::Oom;
    if (!sh.store().insert(hash, replacement)) {
        kvobj_free(replacement);
        return StoreResult::InsertFailed;
    }
    return StoreResult::Stored;
}

void reply_store_error(Op& op, StoreResult result, bool discard_existing_reply = false) {
    if (discard_existing_reply) clear_reply(op);
    if (result == StoreResult::Oom) reply_err(op.sink(), "ERR out of memory");
    else reply_err(op.sink(), "ERR keyspace insert failed");
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
    if (o->is_int()) { reply_string_bulk(op, o); return; }
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
    // Preserve the allocation-free raw fast path while still applying Redis integer encoding.
    if (op.argc() == 3) {
        const StoreResult result = store_string(sh, op.key(), op.hash, op.arg(2), -1, true);
        if (result != StoreResult::Stored) { reply_store_error(op, result); return; }
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
    const StoreResult result = store_string(sh, op.key(), op.hash, op.arg(2), expire, true);
    if (result != StoreResult::Stored) { reply_store_error(op, result, options.get); return; }
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

void cmd_append(Shard& sh, Op& op) {
    KvObj* o = sh.store().find(op.hash, op.key());
    if (!o) {
        const StoreResult result = store_string(sh, op.key(), op.hash, op.arg(2), -1, true);
        if (result != StoreResult::Stored) { reply_store_error(op, result); return; }
        reply_int(op.sink(), op.arg(2).n);
        return;
    }
    auto sink = op.sink();
    if (!obj_type_check(o, Type::String, sink)) return;

    char integer[24];
    const Slice old = string_bytes(o, integer);
    // A raw empty append changes no observable value or encoding. Integer encoding is the one
    // exception: Redis's append path materializes it even when the appended byte count is zero.
    if (op.arg(2).n == 0 && !o->is_int()) { reply_int(op.sink(), old.n); return; }
    const uint64_t total = static_cast<uint64_t>(old.n) + op.arg(2).n;
    if (total > kProtoMaxBulkLen) {
        reply_err(op.sink(), "ERR string exceeds maximum allowed size (proto-max-bulk-len)");
        return;
    }
    char* merged = static_cast<char*>(std::malloc(total ? static_cast<size_t>(total) : 1));
    if (!merged) { reply_err(op.sink(), "ERR out of memory"); return; }
    std::memcpy(merged, old.p, old.n);
    std::memcpy(merged + old.n, op.arg(2).p, op.arg(2).n);
    const int64_t expire = o->expire_at_ms();
    const StoreResult result = store_string(
        sh, op.key(), op.hash, Slice(merged, static_cast<uint32_t>(total)), expire, false);
    std::free(merged);
    if (result != StoreResult::Stored) { reply_store_error(op, result); return; }
    reply_int(op.sink(), static_cast<long long>(total));
}

void cmd_strlen(Shard& sh, Op& op) {
    KvObj* o = sh.store().find(op.hash, op.key());
    if (!o) { reply_int(op.sink(), 0); return; }
    auto sink = op.sink();
    if (!obj_type_check(o, Type::String, sink)) return;
    if (!o->is_int()) { reply_int(op.sink(), o->str_value().n); return; }
    char integer[24];
    reply_int(op.sink(), string_bytes(o, integer).n);
}

void cmd_getrange(Shard& sh, Op& op) {
    int64_t start = 0, end = 0;
    if (!parse_i64(op.arg(2), start) || !parse_i64(op.arg(3), end)) {
        reply_err(op.sink(), "ERR value is not an integer or out of range");
        return;
    }
    KvObj* o = sh.store().find(op.hash, op.key());
    if (!o) { reply_emptystr(op.sink()); return; }
    auto sink = op.sink();
    if (!obj_type_check(o, Type::String, sink)) return;

    char integer[24];
    const Slice value = string_bytes(o, integer);
    const int64_t length = value.n;
    if (start < 0 && end < 0 && start > end) { reply_emptystr(op.sink()); return; }
    if (start < 0) start = length + start;
    if (end < 0) end = length + end;
    if (start < 0) start = 0;
    if (end < 0) end = 0;
    if (end >= length) end = length - 1;
    if (start > end || length == 0) { reply_emptystr(op.sink()); return; }
    reply_bulk(op.sink(), Slice(value.p + start, static_cast<uint32_t>(end - start + 1)));
}

void cmd_setrange(Shard& sh, Op& op) {
    int64_t offset = 0;
    if (!parse_i64(op.arg(2), offset)) {
        reply_err(op.sink(), "ERR value is not an integer or out of range");
        return;
    }
    if (offset < 0) { reply_err(op.sink(), "ERR offset is out of range"); return; }

    KvObj* o = sh.store().find(op.hash, op.key());
    if (o) {
        auto sink = op.sink();
        if (!obj_type_check(o, Type::String, sink)) return;
    }
    if (op.arg(3).n == 0) {
        if (!o) { reply_int(op.sink(), 0); return; }
        char integer[24];
        reply_int(op.sink(), string_bytes(o, integer).n);
        return;
    }

    const uint64_t write_end = static_cast<uint64_t>(offset) + op.arg(3).n;
    if (write_end > kProtoMaxBulkLen) {
        reply_err(op.sink(), "ERR string exceeds maximum allowed size (proto-max-bulk-len)");
        return;
    }
    char integer[24];
    const Slice old = o ? string_bytes(o, integer) : Slice("", 0);
    const uint32_t new_length = static_cast<uint32_t>(std::max<uint64_t>(old.n, write_end));
    char* changed = static_cast<char*>(std::malloc(new_length));
    if (!changed) { reply_err(op.sink(), "ERR out of memory"); return; }
    std::memcpy(changed, old.p, old.n);
    if (new_length > old.n) std::memset(changed + old.n, 0, new_length - old.n);
    std::memcpy(changed + offset, op.arg(3).p, op.arg(3).n);
    const int64_t expire = o ? o->expire_at_ms() : -1;
    const StoreResult result =
        store_string(sh, op.key(), op.hash, Slice(changed, new_length), expire, false);
    std::free(changed);
    if (result != StoreResult::Stored) { reply_store_error(op, result); return; }
    reply_int(op.sink(), new_length);
}

void cmd_getset(Shard& sh, Op& op) {
    KvObj* old = sh.store().find(op.hash, op.key());
    auto sink = op.sink();
    if (!obj_type_check(old, Type::String, sink)) return;
    reply_string_bulk(op, old);
    const StoreResult result = store_string(sh, op.key(), op.hash, op.arg(2), -1, true);
    if (result != StoreResult::Stored) { reply_store_error(op, result, true); return; }
}

void cmd_setnx(Shard& sh, Op& op) {
    if (sh.store().find(op.hash, op.key())) { reply_int(op.sink(), 0); return; }
    const StoreResult result = store_string(sh, op.key(), op.hash, op.arg(2), -1, true);
    if (result != StoreResult::Stored) { reply_store_error(op, result); return; }
    reply_int(op.sink(), 1);
}

void setex_generic(Shard& sh, Op& op, ExpireKind kind, const char* command) {
    int64_t expire = -1;
    if (!expiry_at(sh, op.arg(2), kind, expire)) {
        reply_invalid_expire(op, command);
        return;
    }
    const StoreResult result = store_string(sh, op.key(), op.hash, op.arg(3), expire, true);
    if (result != StoreResult::Stored) { reply_store_error(op, result); return; }
    reply_ok(op.sink());
}

void cmd_setex(Shard& sh, Op& op)  { setex_generic(sh, op, ExpireKind::Ex, "setex"); }
void cmd_psetex(Shard& sh, Op& op) { setex_generic(sh, op, ExpireKind::Px, "psetex"); }

void incr_decr(Shard& sh, Op& op, int64_t increment) {
    KvObj* o = sh.store().find(op.hash, op.key());
    int64_t old = 0;
    int64_t expire = -1;
    if (o) {
        auto sink = op.sink();
        if (!obj_type_check(o, Type::String, sink)) return;
        if (o->is_int()) old = o->int_value();
        else if (!parse_i64(o->str_value(), old)) {
            reply_err(op.sink(), "ERR value is not an integer or out of range");
            return;
        }
        expire = o->expire_at_ms();
    }
    int64_t value = 0;
    if (__builtin_add_overflow(old, increment, &value)) {
        reply_err(op.sink(), "ERR increment or decrement would overflow");
        return;
    }
    const StoreResult result = store_integer(sh, op.key(), op.hash, value, expire);
    if (result != StoreResult::Stored) { reply_store_error(op, result); return; }
    reply_int(op.sink(), value);
}

void cmd_incr(Shard& sh, Op& op) { incr_decr(sh, op, 1); }
void cmd_decr(Shard& sh, Op& op) { incr_decr(sh, op, -1); }

void cmd_incrby(Shard& sh, Op& op) {
    int64_t increment = 0;
    if (!parse_i64(op.arg(2), increment)) {
        reply_err(op.sink(), "ERR value is not an integer or out of range");
        return;
    }
    incr_decr(sh, op, increment);
}

void cmd_decrby(Shard& sh, Op& op) {
    int64_t decrement = 0;
    if (!parse_i64(op.arg(2), decrement)) {
        reply_err(op.sink(), "ERR value is not an integer or out of range");
        return;
    }
    if (decrement == INT64_MIN) {
        reply_err(op.sink(), "ERR decrement would overflow");
        return;
    }
    incr_decr(sh, op, -decrement);
}

void cmd_incrbyfloat(Shard& sh, Op& op) {
    KvObj* o = sh.store().find(op.hash, op.key());
    if (o) {
        auto sink = op.sink();
        if (!obj_type_check(o, Type::String, sink)) return;
    }

    long double value = 0;
    if (o) {
        if (o->is_int()) value = static_cast<long double>(o->int_value());
        else if (!parse_long_double(o->str_value(), value)) {
            reply_err(op.sink(), "ERR value is not a valid float");
            return;
        }
    }
    long double increment = 0;
    if (!parse_long_double(op.arg(2), increment)) {
        reply_err(op.sink(), "ERR value is not a valid float");
        return;
    }
    value += increment;
    if (std::isnan(value) || std::isinf(value)) {
        reply_err(op.sink(), "ERR increment would produce NaN or Infinity");
        return;
    }

    char text[kLongDoubleChars];
    const uint32_t length = format_long_double(text, sizeof(text), value);
    if (length == 0) { reply_err(op.sink(), "ERR out of memory"); return; }
    const int64_t expire = o ? o->expire_at_ms() : -1;
    const StoreResult result =
        store_string(sh, op.key(), op.hash, Slice(text, length), expire, false);
    if (result != StoreResult::Stored) { reply_store_error(op, result); return; }
    reply_bulk(op.sink(), Slice(text, length));
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

// These read PUBLISHED counters only. An IO thread must never inspect a worker-owned FlatStore.
Server* g_server = nullptr;

void cmd_dbsize(Shard&, Op& op) {
    uint64_t n = 0;
    if (g_server) for (uint32_t i = 0; i < g_server->nshards(); i++)
        n += g_server->shard(static_cast<int32_t>(i)).published_size();
    reply_int(op.sink(), static_cast<long long>(n));
}

void cmd_info(Shard&, Op& op) {
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
    reply_bulk(op.sink(), Slice(buf, static_cast<uint32_t>(n)));
}

void cmd_select(Shard&, Op& op) {
    long long db = 0;
    if (!parse_ll(op.arg(1), db) || db != 0) {
        reply_err(op.sink(), "ERR this server supports a single keyspace; only SELECT 0 is valid");
        return;
    }
    reply_ok(op.sink());
}

void cmd_config(Shard&, Op& op)  { reply_array_header(op.sink(), 0); }
void cmd_ping(Shard&, Op& op)    { if (op.argc() == 2) reply_bulk(op.sink(), op.arg(1)); else reply_pong(op.sink()); }
void cmd_echo(Shard&, Op& op)    { reply_bulk(op.sink(), op.arg(1)); }
void cmd_command(Shard&, Op& op) { reply_array_header(op.sink(), 0); }

static const CommandSpec kTable[] = {
    // name          min max flags                                  handler          first last step
    {"GET",           2,  2,  CmdFlags::Readonly,                    cmd_get,          1,  1,  1},
    {"SET",           3, -1,  CmdFlags::Write,                       cmd_set,          1,  1,  1},
    {"APPEND",        3,  3,  CmdFlags::Write,                       cmd_append,       1,  1,  1},
    {"STRLEN",        2,  2,  CmdFlags::Readonly,                    cmd_strlen,       1,  1,  1},
    {"GETRANGE",      4,  4,  CmdFlags::Readonly,                    cmd_getrange,     1,  1,  1},
    {"SETRANGE",      4,  4,  CmdFlags::Write,                       cmd_setrange,     1,  1,  1},
    {"GETSET",        3,  3,  CmdFlags::Write,                       cmd_getset,       1,  1,  1},
    {"SETNX",         3,  3,  CmdFlags::Write,                       cmd_setnx,        1,  1,  1},
    {"SETEX",         4,  4,  CmdFlags::Write,                       cmd_setex,        1,  1,  1},
    {"PSETEX",        4,  4,  CmdFlags::Write,                       cmd_psetex,       1,  1,  1},
    {"GETEX",         2,  4,  CmdFlags::Write,                       cmd_getex,        1,  1,  1},
    {"GETDEL",        2,  2,  CmdFlags::Write,                       cmd_getdel,       1,  1,  1},
    {"DEL",           2,  2,  CmdFlags::Write,                       cmd_del,          1,  1,  1},
    {"EXISTS",        2,  2,  CmdFlags::Readonly,                    cmd_exists,       1,  1,  1},
    {"INCR",          2,  2,  CmdFlags::Write,                       cmd_incr,         1,  1,  1},
    {"DECR",          2,  2,  CmdFlags::Write,                       cmd_decr,         1,  1,  1},
    {"INCRBY",        3,  3,  CmdFlags::Write,                       cmd_incrby,       1,  1,  1},
    {"DECRBY",        3,  3,  CmdFlags::Write,                       cmd_decrby,       1,  1,  1},
    {"INCRBYFLOAT",   3,  3,  CmdFlags::Write,                       cmd_incrbyfloat,  1,  1,  1},
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
    {"PING",          1, -1,  CmdFlags::ConnLocal,                   cmd_ping,         0,  0,  0},
    {"ECHO",          2,  2,  CmdFlags::ConnLocal,                   cmd_echo,         0,  0,  0},
    {"COMMAND",       1, -1,  CmdFlags::ConnLocal | CmdFlags::Admin, cmd_command,      0,  0,  0},
    {"DBSIZE",        1,  1,  CmdFlags::ConnLocal | CmdFlags::Admin, cmd_dbsize,       0,  0,  0},
    {"INFO",          1, -1,  CmdFlags::ConnLocal | CmdFlags::Admin, cmd_info,         0,  0,  0},
    {"SELECT",        2,  2,  CmdFlags::ConnLocal,                   cmd_select,       0,  0,  0},
    {"CONFIG",        2, -1,  CmdFlags::ConnLocal | CmdFlags::Admin, cmd_config,       0,  0,  0},
};

}  // namespace

void command_bind_server(Server* server) { g_server = server; }

CommandTable string_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
