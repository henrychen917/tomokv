// t_sort.cc -- SORT's ordering core and its BY/GET dereference.  See t_sort.h for the admission
// rule and NOTES-SORT.md for the design that produced it.
#include "t_sort.h"

#include <algorithm>
#include <cctype>
#include <charconv>
#include <cmath>
#include <cstring>
#include <cstdlib>
#include <limits>
#include <new>

#include "../core/server.h"
#include "../core/shard.h"
#include "../store/kvobj.h"

namespace tomo {
namespace {

// Local copies of two three-line helpers that live in other translation units' anonymous
// namespaces.  Duplicating the bytes is cheaper than widening two unrelated headers, and both are
// pinned by the differ suite against the reference.
int sort_binary_compare(Slice a, Slice b) {
    const uint32_t common = std::min(a.n, b.n);
    const int cmp = common ? std::memcmp(a.p, b.p, common) : 0;
    if (cmp != 0) return cmp < 0 ? -1 : 1;
    if (a.n == b.n) return 0;
    return a.n < b.n ? -1 : 1;
}

bool sort_parse_double(Slice input, double& out) {
    if (!input.n) return false;
    bool negative = false;
    Slice word = input;
    if (word.p[0] == '+' || word.p[0] == '-') {
        negative = word.p[0] == '-';
        word.p++;
        word.n--;
    }
    if (word.eq_icase("inf") || word.eq_icase("infinity")) {
        out = negative ? -std::numeric_limits<double>::infinity()
                       : std::numeric_limits<double>::infinity();
        return true;
    }
    const char* begin = input.p + (input.p[0] == '+');
    const char* end = input.p + input.n;
    if (begin == end) return false;
    auto result = std::from_chars(begin, end, out, std::chars_format::general);
    return result.ec == std::errc{} && result.ptr == end && !std::isnan(out);
}

bool sort_number(const std::string& text, double& number) {
    if (text.empty() || std::isspace(static_cast<unsigned char>(text[0]))) return false;
    return sort_parse_double(Slice(text.data(), static_cast<uint32_t>(text.size())), number);
}

// One weighted row.  `weight_present` is the reference's NULL: a BY pattern whose key is missing,
// holds a non-string, or lacks the named hash field.
struct SortItem {
    uint32_t index = 0;          // position in the caller's `elements`, for stable ties
    double score = 0;
    std::string weight;
    bool weight_present = false;
};

// Builds the key a pattern names for one element.  Returns false when the pattern has no '*',
// which the reference treats as "no lookup at all" rather than "look up this literal".
bool sort_build_key(const SortPattern& pattern, Slice element, std::string& key) {
    if (!pattern.has_star) return false;
    key.assign(pattern.prefix.p, pattern.prefix.n);
    key.append(element.p, element.n);
    key.append(pattern.suffix.p, pattern.suffix.n);
    return true;
}

}  // namespace

void sort_pattern_parse(Slice pattern, SortPattern& out) {
    out = SortPattern{};
    out.raw = pattern;
    out.self = pattern.n == 1 && pattern.p[0] == '#';
    const char* star = pattern.n ? static_cast<const char*>(
                                       std::memchr(pattern.p, '*', pattern.n))
                                 : nullptr;
    if (!star) return;
    out.has_star = true;
    out.prefix = Slice(pattern.p, static_cast<uint32_t>(star - pattern.p));
    const char* tail = star + 1;
    const uint32_t tail_len = static_cast<uint32_t>(pattern.p + pattern.n - tail);
    // "->" is a field separator only when it begins AFTER the '*' and has a non-empty tail;
    // otherwise it is ordinary key bytes.  Verified against the reference in both directions.
    const char* arrow = nullptr;
    for (uint32_t i = 0; tail_len >= 2 && i + 2 < tail_len; i++)
        if (tail[i] == '-' && tail[i + 1] == '>') { arrow = tail + i; break; }
    if (arrow) {
        out.suffix = Slice(tail, static_cast<uint32_t>(arrow - tail));
        out.field = Slice(arrow + 2, static_cast<uint32_t>(pattern.p + pattern.n - (arrow + 2)));
    } else {
        out.suffix = Slice(tail, tail_len);
    }
}

bool sort_deref_local(Server& server) {
    return server.placement().ex_threads().size() == 1;
}

namespace {

// Installs the command's read cut and originating connection on one store for the length of a
// single lookup, then restores exactly what was there. A null `target` disables it entirely, which
// is what the negative-control build passes.
struct ForeignReadContext {
    FlatStore* target = nullptr;
    uint64_t epoch = 0;
    uint64_t conn = 0;
    ForeignReadContext(FlatStore* target_, uint64_t snapshot, uint64_t origin_conn_id)
        : target(target_) {
        if (!target) return;
        epoch = target->atomic_read_epoch();
        conn = target->atomic_read_origin_conn_id();
        target->atomic_set_read_context(snapshot, origin_conn_id);
    }
    ~ForeignReadContext() { if (target) target->atomic_set_read_context(epoch, conn); }
    ForeignReadContext(const ForeignReadContext&) = delete;
    ForeignReadContext& operator=(const ForeignReadContext&) = delete;
};

// Resolves one pattern for one element on whichever shard owns the derived key.  LEGALITY: the
// caller has already been admitted by sort_deref_local, so `owner`'s executor owns every shard and
// `target` below is one of its own.  The equality test is not a fast path -- it selects the
// notifying read only for the shard whose NotifyExecutionScope is actually open.
bool sort_lookup(Shard* owner, bool notify, const SortSpec& spec, const SortPattern& pattern,
                 Slice element, std::string& out) {
    std::string key;
    if (!owner || !sort_build_key(pattern, element, key)) return false;
    Server* server = owner->server();
    if (!server) return false;
    const Slice key_slice(key.data(), static_cast<uint32_t>(key.size()));
    const uint64_t hash = FlatStore::hash_key(key_slice);
    const int32_t shard_id = server->router().shard_of(hash);
    if (shard_id < 0 || static_cast<uint32_t>(shard_id) >= server->nshards()) return false;
    Shard& target = server->shard(shard_id);
    if (&target != owner && !sort_deref_local(*server)) {
        // THE LAW, ENFORCED RATHER THAN ARGUED. Structurally unreachable: a '*'-bearing pattern is
        // refused at parse unless one executor owns every shard, and without a '*' this function
        // has already returned. Kept so a future routing change cannot quietly turn an admission
        // bug into a foreign-shard read. INFO's sort_deref_escapes is its control and reads zero.
        server->note_sort_deref_escape();
        return false;
    }
    server->note_sort_deref_lookup();
    const bool foreign = &target != owner;
    // BIND EVERY DEREFERENCED READ, INCLUDING ONE THAT LANDS BACK ON THE SOURCE'S OWN SHARD.
    // The read cut and the originating connection are per-STORE state, and the surrounding
    // machinery binds them only on the shards it knows the command touches -- which for a
    // dereference is none of them, not even the source's when nothing else in the transaction
    // named it. Reading unbound means "latest, no connection", and atomic_resolve_internal hides a
    // group's still-private candidate from every reader but its own connection: outside a
    // transaction that lost a weight key the immediately preceding MSET had written, and inside one
    // it lost every weight the transaction had written. Restore exactly what was there afterwards.
#ifdef TOMO_SORT_NO_READCTX
    ForeignReadContext context(nullptr, 0, 0);           // negative control; see `make sortnoctx`
#else
    ForeignReadContext context(&target.store(), spec.read_snapshot, spec.origin_conn_id);
#endif
    // Notifications (lazy-expire / keymiss) are raised only for a derived key that lives on the
    // shard whose NotifyExecutionScope is open, i.e. the source's; see NOTES-SORT.md §8.
    KvObj* object = (!foreign && notify) ? target.store_find<true>(hash, key_slice)
                                         : target.store().find(hash, key_slice);
    if (!object) return false;
    if (pattern.field.n) {
        if (!object->is_type(Type::Hash)) return false;
        Slice value;
        if (!hash_field_value_ro(object, pattern.field, value)) return false;
        if (target.store().field_expire_count() &&
            hash_ttl_field_lapsed(object, pattern.field, target.now_ms())) return false;
        out.assign(value.p, value.n);
        return true;
    }
    if (!object->is_type(Type::String)) return false;
    if (object->is_int()) {
        char digits[24];
        const long long value = static_cast<long long>(object->int_value());
        const auto result = std::to_chars(digits, digits + sizeof(digits), value);
        out.assign(digits, static_cast<size_t>(result.ptr - digits));
        return true;
    }
    const Slice value = object->str_value();
    out.assign(value.p, value.n);
    return true;
}

}  // namespace

SortStatus sort_run(Shard* owner, bool notify, const SortSpec& spec,
                    std::vector<std::string>& elements,
                    std::vector<std::string>& values,
                    std::vector<uint8_t>& present) {
    values.clear();
    present.clear();
    try {
        // THE DETERMINISM RULE.  A set has no order of its own, so the reference refuses to let an
        // unordered dump become durable: BY <no-star> over a SET that is being STOREd is forced
        // back to an alphabetic sort.  (The reference applies the same rule to a SORT issued from
        // a script; SORT is not callable from scripts here, so that half has no site.)
        bool dontsort = spec.dontsort;
        bool alpha = spec.alpha;
        bool by_lookup = spec.by_given && spec.by.has_star;
        if (dontsort && spec.source_is_set && spec.store) {
            dontsort = false;
            alpha = true;
            by_lookup = false;
        }

        std::vector<SortItem> items;
        items.reserve(elements.size());
        for (uint32_t i = 0; i < elements.size(); i++) {
            SortItem item;
            item.index = i;
            if (!dontsort) {
                if (by_lookup) {
                    item.weight_present = sort_lookup(
                        owner, notify, spec, spec.by,
                        Slice(elements[i].data(), static_cast<uint32_t>(elements[i].size())),
                        item.weight);
                } else {
                    item.weight = elements[i];
                    item.weight_present = true;
                }
                if (!alpha) {
                    // A missing weight is zero, exactly as the reference leaves its initialised
                    // score untouched; only a PRESENT non-numeric weight is an error.
                    if (item.weight_present && !sort_number(item.weight, item.score))
                        return SortStatus::ConversionError;
                }
            }
            items.push_back(std::move(item));
        }

        if (!dontsort) {
            // Ties: the reference falls back to comparing the ELEMENTS for a numeric sort and
            // leaves alphabetic BY ties to its sort algorithm.  stable_sort makes the second case
            // reproducible (input order) instead of implementation-defined.
            auto compare = [&](const SortItem& a, const SortItem& b) {
                int cmp = 0;
                if (!alpha) {
                    if (a.score < b.score) cmp = -1;
                    else if (a.score > b.score) cmp = 1;
                    else cmp = sort_binary_compare(
                        Slice(elements[a.index].data(),
                              static_cast<uint32_t>(elements[a.index].size())),
                        Slice(elements[b.index].data(),
                              static_cast<uint32_t>(elements[b.index].size())));
                } else if (!a.weight_present || !b.weight_present) {
                    // NULL sorts before every present weight; two NULLs compare equal.
                    cmp = a.weight_present ? 1 : (b.weight_present ? -1 : 0);
                } else if (spec.store) {
                    cmp = sort_binary_compare(
                        Slice(a.weight.data(), static_cast<uint32_t>(a.weight.size())),
                        Slice(b.weight.data(), static_cast<uint32_t>(b.weight.size())));
                } else {
                    cmp = std::strcoll(a.weight.c_str(), b.weight.c_str());
                }
                return spec.descending ? cmp > 0 : cmp < 0;
            };
            std::stable_sort(items.begin(), items.end(), compare);
        } else if (spec.descending && !spec.source_is_set) {
            // With ordering suppressed the reference still honours DESC for the two types that
            // HAVE an order of their own (list insertion order, sorted-set score order) and
            // ignores it for a set.
            std::reverse(items.begin(), items.end());
        }

        const int64_t size = static_cast<int64_t>(items.size());
        const int64_t start = std::min<int64_t>(std::max<int64_t>(spec.offset, 0), size);
        const int64_t wanted = std::min<int64_t>(std::max<int64_t>(spec.count, -1), size);
        const int64_t end = wanted < 0 ? size : std::min<int64_t>(size, start + wanted);
        const size_t rows = static_cast<size_t>(std::max<int64_t>(end - start, 0));
        const size_t per_row = spec.gets.empty() ? 1 : spec.gets.size();
        values.reserve(rows * per_row);
        present.reserve(rows * per_row);
        for (int64_t i = start; i < end; i++) {
            std::string& element = elements[items[i].index];
            if (spec.gets.empty()) {
                values.push_back(std::move(element));
                present.push_back(1);
                continue;
            }
            const Slice slice(element.data(), static_cast<uint32_t>(element.size()));
            for (const SortPattern& pattern : spec.gets) {
                if (pattern.self) {
                    values.push_back(element);
                    present.push_back(1);
                    continue;
                }
                std::string value;
                const bool found = sort_lookup(owner, notify, spec, pattern, slice, value);
                values.push_back(std::move(value));
                present.push_back(found ? 1 : 0);
            }
        }
        return SortStatus::Ok;
    } catch (const std::bad_alloc&) {
        values.clear();
        present.clear();
        return SortStatus::Oom;
    }
}

}  // namespace tomo
