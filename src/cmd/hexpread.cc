// Reply-only hash reads while an atomic predecessor or foreign candidate is retained.
// Ordinary accesses keep t_hash.cc's eager reaping, notifications and accounting.
#include "t_hash_ttl.h"
#include "command.h"
#include "../core/shard.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include <algorithm>
#include <climits>
#include <cstring>
#include <ctime>
#include <limits>
#include <stdexcept>
#include <unordered_set>
#include <vector>

namespace tomo {
namespace hexpread {
// Reply-only field visibility for an immutable atomic predecessor. Storage is command-local;
// all table walks and random state changes stay in the cold expiry implementation.
struct HashReadView {
    const HashFieldTtl* ttls = nullptr;
    int64_t now_ms = 0;
    uint32_t expired = 0;
    uint64_t random_state = 0;
    bool field_live(Slice field) const;
    bool visible(Slice field) const {
        return __builtin_expect(ttls == nullptr, true) || field_live(field);
    }
    uint64_t random(uint64_t seed, uint64_t bound);
};
bool hash_ttl_read_view(Shard& shard, Op& op, KvObj*& object, HashReadView& view);

bool parse_i64(Slice text, int64_t& value) {
    if (text.n == 0 || text.n >= 21) return false;
    if (text.n == 1 && text.p[0] == '0') {
        value = 0;
        return true;
    }
    uint32_t pos = 0;
    bool negative = false;
    if (text.p[0] == '-') {
        negative = true;
        if (++pos == text.n) return false;
    }
    if (text.p[pos] < '1' || text.p[pos] > '9') return false;
    uint64_t magnitude = static_cast<uint64_t>(text.p[pos++] - '0');
    for (; pos < text.n; pos++) {
        const char ch = text.p[pos];
        if (ch < '0' || ch > '9') return false;
        const uint32_t digit = static_cast<uint32_t>(ch - '0');
        if (magnitude > (std::numeric_limits<uint64_t>::max() - digit) / 10) return false;
        magnitude = magnitude * 10 + digit;
    }
    const uint64_t limit = negative ? (uint64_t{1} << 63) : static_cast<uint64_t>(INT64_MAX);
    if (magnitude > limit) return false;
    if (negative)
        value = magnitude == (uint64_t{1} << 63) ? INT64_MIN : -static_cast<int64_t>(magnitude);
    else
        value = static_cast<int64_t>(magnitude);
    return true;
}

struct ScanOptions {
    Slice pattern;
    uint64_t count = 10;
    bool use_pattern = false;
    bool no_values = false;
};

bool parse_scan_options(Op& op, ScanOptions& options) {
    for (uint32_t i = 3; i < op.argc();) {
        const Slice option = op.arg(i);
        if (option.eq_icase("match") && i + 1 < op.argc()) {
            options.pattern = op.arg(i + 1);
            options.use_pattern = !(options.pattern.n == 1 && options.pattern.p[0] == '*');
            i += 2;
        } else if (option.eq_icase("count") && i + 1 < op.argc()) {
            int64_t count = 0;
            if (!parse_i64(op.arg(i + 1), count)) {
                reply_err(op.sink(), "ERR value is not an integer or out of range");
                return false;
            }
            if (count < 1) {
                reply_syntax(op.sink());
                return false;
            }
            options.count = static_cast<uint64_t>(count);
            i += 2;
        } else if (option.eq_icase("novalues")) {
            options.no_values = true;
            i++;
        } else {
            reply_syntax(op.sink());
            return false;
        }
    }
    return true;
}

struct ScanItem {
    Slice field;
    Slice value;
};

void reply_scan(Op& op, uint64_t cursor, const std::vector<ScanItem>& items, bool no_values) {
    char text[24];
    const uint32_t length = u64_to_dec(text, cursor);
    reply_array_header(op.sink(), 2);
    reply_bulk(op.sink(), Slice(text, length));
    reply_array_header(op.sink(), static_cast<uint64_t>(items.size()) * (no_values ? 1 : 2));
    for (const ScanItem& item : items) {
        reply_bulk(op.sink(), item.field);
        if (!no_values) reply_bulk(op.sink(), item.value);
    }
}

enum class GetAllMode : uint8_t { Fields, Values, Both };

bool filtered_select_unique(HashReadView& view, uint32_t population, uint32_t count,
                   std::vector<uint32_t>& selected) {
    try {
        selected.reserve(count);
        if (static_cast<uint64_t>(count) * 3 > population) {
            std::vector<uint32_t> all(population);
            for (uint32_t i = 0; i < population; i++) all[i] = i;
            for (uint32_t i = 0; i < count; i++) {
                const uint32_t chosen = i + static_cast<uint32_t>(
                    view.random(0, static_cast<uint64_t>(population - i)));
                std::swap(all[i], all[chosen]);
                selected.push_back(all[i]);
            }
            return true;
        }
        std::unordered_set<uint32_t> seen;
        seen.reserve(static_cast<size_t>(count) * 2);
        while (selected.size() < count) {
            const uint32_t candidate = static_cast<uint32_t>(view.random(0, population));
            if (seen.insert(candidate).second) selected.push_back(candidate);
        }
        return true;
    } catch (const std::bad_alloc&) {
        return false;
    } catch (const std::length_error&) {
        return false;
    }
}

void filtered_cmd_hget(Shard& shard, Op& op, KvObj* object, HashReadView& view) {
    (void)shard;
    Slice value;
    if (!object || !view.visible(op.arg(2)) || !hash_field_value_ro(object, op.arg(2), value))
        reply_null(op.sink(), op.resp3());
    else reply_bulk(op.sink(), value);
}

void filtered_cmd_hmget(Shard& shard, Op& op, KvObj* object, HashReadView& view) {
    (void)shard;
    reply_array_header(op.sink(), op.argc() - 2);
    for (uint32_t i = 2; i < op.argc(); i++) {
        Slice value;
        if (!object || !view.visible(op.arg(i)) || !hash_field_value_ro(object, op.arg(i), value))
            reply_null(op.sink(), op.resp3());
        else reply_bulk(op.sink(), value);
    }
}

void filtered_cmd_hlen(Shard& shard, Op& op, KvObj* object, HashReadView& view) {
    (void)shard;
    reply_int(op.sink(), object ? (hash_ttl_field_count(object) - view.expired) : 0);
}

void filtered_cmd_hexists(Shard& shard, Op& op, KvObj* object, HashReadView& view) {
    (void)shard;
    Slice value;
    reply_int(op.sink(), object && view.visible(op.arg(2)) &&
                        hash_field_value_ro(object, op.arg(2), value) ? 1 : 0);
}

void filtered_cmd_hstrlen(Shard& shard, Op& op, KvObj* object, HashReadView& view) {
    (void)shard;
    Slice value;
    reply_int(op.sink(), object && view.visible(op.arg(2)) &&
                        hash_field_value_ro(object, op.arg(2), value) ? value.n : 0);
}

void filtered_generic_getall(Shard& shard, Op& op, GetAllMode mode, KvObj* object, HashReadView& view) {
    (void)shard;
    if (!object) {
        if (mode == GetAllMode::Both) reply_map_header(op.sink(), 0, op.resp3());
        else reply_array_header(op.sink(), 0);
        return;
    }
    const uint32_t count = hash_ttl_field_count(object) - view.expired;
    if (mode == GetAllMode::Both) reply_map_header(op.sink(), count, op.resp3());
    else reply_array_header(op.sink(), count);
    struct Context { Op& op; HashReadView& view; GetAllMode mode; } context{op, view, mode};
    hash_read_visit(object, 0, 0, &context, [](void* raw, Slice field, Slice value) {
        auto& c = *static_cast<Context*>(raw);
        if (!c.view.visible(field)) return;
        if (c.mode != GetAllMode::Values) reply_bulk(c.op.sink(), field);
        if (c.mode != GetAllMode::Fields) reply_bulk(c.op.sink(), value);
    });
}

void filtered_cmd_hscan(Shard& shard, Op& op, KvObj* object, HashReadView& view) {
    uint64_t cursor = 0;
    if (!command_parse_scan_cursor(op.arg(2), cursor)) {
        reply_err(op.sink(), "ERR invalid cursor");
        return;
    }
    (void)shard;
    if (!object) {
        // Redis returns the empty scan reply before parsing trailing options for a missing key.
        reply_scan(op, 0, {}, false);
        return;
    }
    ScanOptions options;
    if (!parse_scan_options(op, options)) return;

    std::vector<ScanItem> items;
    try {
        struct Context { HashReadView& view; ScanOptions& options; std::vector<ScanItem>& items; }
            context{view, options, items};
        cursor = hash_read_visit(object, cursor, options.count, &context,
            [](void* raw, Slice field, Slice value) {
                auto& c = *static_cast<Context*>(raw);
                if (c.view.visible(field) && (!c.options.use_pattern ||
                    command_glob_match(c.options.pattern, field))) c.items.push_back({field, value});
            });
    } catch (const std::bad_alloc&) {
        reply_err(op.sink(), "ERR out of memory");
        return;
    } catch (const std::length_error&) {
        reply_err(op.sink(), "ERR out of memory");
        return;
    }
    reply_scan(op, cursor, items, options.no_values);
}

void filtered_cmd_hrandfield(Shard& shard, Op& op, KvObj* object, HashReadView& view) {
    int64_t signed_count = 0;
    bool with_values = false;
    if (op.argc() >= 3) {
        if (!parse_i64(op.arg(2), signed_count)) {
            reply_err(op.sink(), "ERR value is not an integer or out of range");
            return;
        }
        if (signed_count == INT64_MIN) {
            reply_outofrange(op.sink());
            return;
        }
        if (op.argc() > 4) {
            reply_syntax(op.sink());
            return;
        }
        if (op.argc() == 4) {
            if (!op.arg(3).eq_icase("withvalues")) {
                reply_syntax(op.sink());
                return;
            }
            with_values = true;
            if (signed_count < -INT64_MAX / 2 || signed_count > INT64_MAX / 2) {
                reply_outofrange(op.sink());
                return;
            }
        }
    }

    (void)shard;
    if (!object) {
        if (op.argc() == 2) reply_null(op.sink(), op.resp3());
        else reply_array_header(op.sink(), 0);
        return;
    }
    const uint32_t population = hash_ttl_field_count(object) - view.expired;
    if (!population) {
        if (op.argc() == 2) reply_null(op.sink(), op.resp3());
        else reply_array_header(op.sink(), 0);
        return;
    }
    std::vector<ScanItem> live;
    try {
        live.reserve(population);
        struct Context { HashReadView& view; std::vector<ScanItem>& live; } context{view, live};
        hash_read_visit(object, 0, 0, &context, [](void* raw, Slice field, Slice value) {
            auto& c = *static_cast<Context*>(raw);
            if (c.view.visible(field)) c.live.push_back({field, value});
        });
    } catch (const std::bad_alloc&) {
        reply_err(op.sink(), "ERR out of memory");
        return;
    } catch (const std::length_error&) {
        reply_err(op.sink(), "ERR out of memory");
        return;
    }
    auto pair_at = [&](uint32_t index) { return std::pair<Slice, Slice>{live[index].field, live[index].value}; };

    if (op.argc() == 2) {
        const auto pair = pair_at(static_cast<uint32_t>(view.random(op.hash, population)));
        reply_bulk(op.sink(), pair.first);
        return;
    }
    if (signed_count == 0) {
        reply_array_header(op.sink(), 0);
        return;
    }

    const bool unique = signed_count > 0;
    const uint64_t requested = unique ? static_cast<uint64_t>(signed_count)
                                      : static_cast<uint64_t>(-signed_count);
    if (!unique) {
        const bool pairs = with_values && op.resp3();
        reply_array_header(op.sink(), requested * (with_values && !pairs ? 2 : 1));
        for (uint64_t i = 0; i < requested; i++) {
            const auto pair = pair_at(static_cast<uint32_t>(view.random(op.hash, population)));
            if (pairs) reply_array_header(op.sink(), 2);
            reply_bulk(op.sink(), pair.first);
            if (with_values) reply_bulk(op.sink(), pair.second);
        }
        return;
    }

    const uint32_t count = requested >= population ? population : static_cast<uint32_t>(requested);
    if (count == population) {
        const bool pairs = with_values && op.resp3();
        reply_array_header(op.sink(), static_cast<uint64_t>(count) *
                                      (with_values && !pairs ? 2 : 1));
        for (uint32_t i = 0; i < count; i++) {
            const auto pair = pair_at(i);
            if (pairs) reply_array_header(op.sink(), 2);
            reply_bulk(op.sink(), pair.first);
            if (with_values) reply_bulk(op.sink(), pair.second);
        }
        return;
    }

    std::vector<uint32_t> selected;
    if (!filtered_select_unique(view, population, count, selected)) {
        reply_err(op.sink(), "ERR out of memory");
        return;
    }
    const bool pairs = with_values && op.resp3();
    reply_array_header(op.sink(), static_cast<uint64_t>(selected.size()) *
                                  (with_values && !pairs ? 2 : 1));
    for (uint32_t index : selected) {
        const auto pair = pair_at(index);
        if (pairs) reply_array_header(op.sink(), 2);
        reply_bulk(op.sink(), pair.first);
        if (with_values) reply_bulk(op.sink(), pair.second);
    }
}


bool HashReadView::field_live(Slice field) const {
    const int64_t at = ttls->get(field);
    return at < 0 || at > now_ms;
}

uint64_t HashReadView::random(uint64_t seed, uint64_t bound) {
    // Do not update the parked hash's PRNG. Only this reply's generator advances.
    if (!random_state) {
        timespec ts{};
        ::clock_gettime(CLOCK_MONOTONIC, &ts);
        random_state = seed ^ static_cast<uint64_t>(ts.tv_nsec) ^ static_cast<uint64_t>(ts.tv_sec);
        if (!random_state) random_state = 0x9e3779b97f4a7c15ULL;
    }
    random_state ^= random_state >> 12;
    random_state ^= random_state << 25;
    random_state ^= random_state >> 27;
    const uint64_t value = random_state * 0x2545f4914f6cdd1dULL;
    return static_cast<uint64_t>((static_cast<unsigned __int128>(value) * bound) >> 64);
}

bool hash_ttl_read_view(Shard& shard, Op& op, KvObj*& object, HashReadView& view) {
    if (shard.store().atomic_read_owns_value(op.hash, op.key(), object)) return false;
    HashFieldTtl** slot = hash_ttl_slot(object);
    view.ttls = slot ? *slot : nullptr;
    view.now_ms = shard.now_ms();
    if (view.ttls) {
        // Do not call min_expire_ms(): even its const accessor can update the stored cache.
        view.ttls->for_each([&](Slice field, int64_t at) {
            if (at <= view.now_ms && hash_ttl_field_exists(object, field)) ++view.expired;
        });
        if (view.expired == hash_ttl_field_count(object)) object = nullptr;
    }
    return true;
}

}  // namespace hexpread

bool hash_parked_reply(Shard& shard, Op& op) {
    using namespace hexpread;
    // Resolve without touching the physical candidate. Safe reads return to the ordinary lookup.
    KvObj* object = shard.store().atomic_resolve(op.hash, op.key(), shard.store().atomic_read_epoch());
    if (!object || !object->is_type(Type::Hash)) return false;
    KvObj* found = object;
    HashReadView view;
    if (!hash_ttl_read_view(shard, op, object, view)) return false;
    shard.note_keyspace_read(found);
    const char* name = op.spec->name;
    if (std::strcmp(name, "HGET") == 0) filtered_cmd_hget(shard, op, object, view);
    else if (std::strcmp(name, "HMGET") == 0) filtered_cmd_hmget(shard, op, object, view);
    else if (std::strcmp(name, "HLEN") == 0) filtered_cmd_hlen(shard, op, object, view);
    else if (std::strcmp(name, "HEXISTS") == 0) filtered_cmd_hexists(shard, op, object, view);
    else if (std::strcmp(name, "HSTRLEN") == 0) filtered_cmd_hstrlen(shard, op, object, view);
    else if (std::strcmp(name, "HSCAN") == 0) filtered_cmd_hscan(shard, op, object, view);
    else if (std::strcmp(name, "HRANDFIELD") == 0) filtered_cmd_hrandfield(shard, op, object, view);
    else if (std::strcmp(name, "HGETALL") == 0)
        filtered_generic_getall(shard, op, GetAllMode::Both, object, view);
    else if (std::strcmp(name, "HKEYS") == 0)
        filtered_generic_getall(shard, op, GetAllMode::Fields, object, view);
    else if (std::strcmp(name, "HVALS") == 0)
        filtered_generic_getall(shard, op, GetAllMode::Values, object, view);
    else return false;
    return true;
}

}  // namespace tomo
