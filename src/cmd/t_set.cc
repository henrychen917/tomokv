// t_set.cc — single-key Redis-compatible SET-family commands.
//
// Small integer sets keep sorted 2/4/8-byte signed values in Compact. Small mixed sets keep raw
// members in Compact plus entry offsets for O(1) random access. Both promote one-way to the
// open-addressed SetMemberTable. All objects and PRNG state are worker-local; no synchronization is
// needed on a shard-owned value.
#include "command.h"
#include "../core/shard.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include "../store/kvobj.h"

#include <algorithm>
#include <chrono>
#include <climits>
#include <cstdint>
#include <cstring>
#include <limits>
#include <new>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

namespace tomo {

void reply_maxmemory_oom(Op& op);

// ---- SetMemberTable --------------------------------------------------------------------------

uint32_t SetMemberTable::capacity_for(uint32_t entries) {
    uint32_t cap = 8;
    while (static_cast<uint64_t>(entries) * 10 >= static_cast<uint64_t>(cap) * 7) {
        if (cap > (uint32_t{1} << 30)) return 0;
        cap <<= 1;
    }
    return cap;
}

bool SetMemberTable::rehash(uint32_t capacity) {
    if (capacity < 8 || (capacity & (capacity - 1))) return false;
    std::vector<Slot> next;
    std::vector<uint32_t> next_live;
    try {
        next.resize(capacity);
        next_live.reserve(live_);
    } catch (const std::bad_alloc&) {
        return false;
    }

    const uint32_t mask = capacity - 1;
    for (uint32_t old_slot : live_slots_) {
        Slot& src = slots_[old_slot];
        uint32_t pos = static_cast<uint32_t>(mix64(src.hash)) & mask;
        while (next[pos].state == Live) pos = (pos + 1) & mask;
        Slot& dst = next[pos];
        dst.value = std::move(src.value);
        dst.hash = src.hash;
        dst.dense_pos = static_cast<uint32_t>(next_live.size());
        dst.state = Live;
        next_live.push_back(pos);
    }
    slots_ = std::move(next);
    live_slots_ = std::move(next_live);
    tombs_ = 0;
    if (++generation_ == 0) generation_ = 1;
    return true;
}

bool SetMemberTable::reserve(uint32_t entries) {
    const uint32_t wanted = capacity_for(entries);
    if (wanted == 0) return false;
    if (slots_.size() < wanted && !rehash(wanted)) return false;
    try {
        live_slots_.reserve(entries);
    } catch (const std::bad_alloc&) {
        return false;
    }
    return true;
}

uint32_t SetMemberTable::find(Slice value, uint64_t hash) const {
    if (slots_.empty()) return npos;
    const uint32_t mask = static_cast<uint32_t>(slots_.size() - 1);
    uint32_t pos = static_cast<uint32_t>(mix64(hash)) & mask;
    for (uint32_t probes = 0; probes < slots_.size(); probes++) {
        const Slot& slot = slots_[pos];
        if (slot.state == Empty) return npos;
        if (slot.state == Live && slot.hash == hash && slot.value.size() == value.n &&
            (value.n == 0 || std::memcmp(slot.value.data(), value.p, value.n) == 0))
            return pos;
        pos = (pos + 1) & mask;
    }
    return npos;
}

uint32_t SetMemberTable::find_insert_slot(Slice value, uint64_t hash, bool& exists) const {
    exists = false;
    if (slots_.empty()) return npos;
    const uint32_t mask = static_cast<uint32_t>(slots_.size() - 1);
    uint32_t pos = static_cast<uint32_t>(mix64(hash)) & mask;
    uint32_t first_tomb = npos;
    for (uint32_t probes = 0; probes < slots_.size(); probes++) {
        const Slot& slot = slots_[pos];
        if (slot.state == Empty) return first_tomb == npos ? pos : first_tomb;
        if (slot.state == Tomb) {
            if (first_tomb == npos) first_tomb = pos;
        } else if (slot.hash == hash && slot.value.size() == value.n &&
                   (value.n == 0 || std::memcmp(slot.value.data(), value.p, value.n) == 0)) {
            exists = true;
            return pos;
        }
        pos = (pos + 1) & mask;
    }
    return first_tomb;
}

bool SetMemberTable::ensure_insert_capacity() {
    if (slots_.empty()) return rehash(8);
    const uint64_t occupied = static_cast<uint64_t>(live_) + tombs_ + 1;
    if (occupied * 10 < static_cast<uint64_t>(slots_.size()) * 7) return true;
    const bool tomb_heavy = static_cast<uint64_t>(live_ + 1) * 2 < slots_.size();
    if (tomb_heavy) return rehash(static_cast<uint32_t>(slots_.size()));
    if (slots_.size() > (uint32_t{1} << 30)) return false;
    return rehash(static_cast<uint32_t>(slots_.size() * 2));
}

SetMemberTable::InsertResult SetMemberTable::insert(Slice value, uint64_t hash) {
    if (find(value, hash) != npos) return InsertResult::Exists;

    std::string copy;
    try {
        if (value.n) copy.assign(value.p, value.n);
    } catch (const std::bad_alloc&) {
        return InsertResult::Oom;
    }
    if (!ensure_insert_capacity()) return InsertResult::Oom;
    try {
        live_slots_.reserve(static_cast<size_t>(live_) + 1);
    } catch (const std::bad_alloc&) {
        return InsertResult::Oom;
    }

    bool exists = false;
    const uint32_t pos = find_insert_slot(value, hash, exists);
    if (exists) return InsertResult::Exists;
    if (pos == npos) return InsertResult::Oom;
    Slot& slot = slots_[pos];
    if (slot.state == Tomb) tombs_--;
    slot.value = std::move(copy);
    slot.hash = hash;
    slot.dense_pos = static_cast<uint32_t>(live_slots_.size());
    slot.state = Live;
    string_capacity_bytes_ += slot.value.capacity();
    live_slots_.push_back(pos);
    live_++;
    return InsertResult::Inserted;
}

bool SetMemberTable::erase_at(uint32_t slot_index, uint32_t& erased_bytes) {
    if (slot_index >= slots_.size() || slots_[slot_index].state != Live) return false;
    Slot& slot = slots_[slot_index];
    erased_bytes = static_cast<uint32_t>(slot.value.size());
    string_capacity_bytes_ -= slot.value.capacity();
    std::string().swap(slot.value);

    const uint32_t dense_pos = slot.dense_pos;
    const uint32_t moved_slot = live_slots_.back();
    live_slots_[dense_pos] = moved_slot;
    slots_[moved_slot].dense_pos = dense_pos;
    live_slots_.pop_back();
    slot.hash = 0;
    slot.dense_pos = 0;
    slot.state = Tomb;
    live_--;
    tombs_++;
    return true;
}

bool SetMemberTable::erase(Slice value, uint64_t hash, uint32_t& erased_bytes) {
    const uint32_t pos = find(value, hash);
    return pos != npos && erase_at(pos, erased_bytes);
}

uint32_t SetMemberTable::random_slot(uint64_t random) const {
    if (live_slots_.empty()) return npos;
    return live_slots_[static_cast<size_t>(random % live_slots_.size())];
}

uint32_t SetMemberTable::slot_for_dense(uint32_t dense_index) const {
    return dense_index < live_slots_.size() ? live_slots_[dense_index] : npos;
}

bool SetMemberTable::live_at(uint32_t slot) const {
    return slot < slots_.size() && slots_[slot].state == Live;
}

Slice SetMemberTable::value_at(uint32_t slot) const {
    if (!live_at(slot)) return {};
    const std::string& value = slots_[slot].value;
    return Slice(value.data(), static_cast<uint32_t>(value.size()));
}

namespace {

enum class AddResult : uint8_t { Added, Exists, Oom };

bool parse_i64_strict(Slice s, int64_t& out) {
    if (s.n == 0 || s.n >= 32) return false;
    uint32_t pos = 0;
    bool negative = false;
    if (s.p[0] == '-') {
        negative = true;
        if (++pos == s.n) return false;
    }
    if (s.n - pos == 1 && s.p[pos] == '0') {
        out = 0;
        return !negative;
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
    out = negative ? (value == (uint64_t{1} << 63) ? INT64_MIN
                                                    : -static_cast<int64_t>(value))
                   : static_cast<int64_t>(value);
    return true;
}

bool parse_cursor(Slice s, uint64_t& out) {
    uint32_t pos = 0;
    while (pos < s.n && (s.p[pos] == ' ' || (s.p[pos] >= '\t' && s.p[pos] <= '\r'))) pos++;
    if (pos < s.n && s.p[pos] == '+') pos++;
    if (pos == s.n || s.p[pos] == '-') return false;
    uint64_t value = 0;
    for (; pos < s.n; pos++) {
        const char ch = s.p[pos];
        if (ch < '0' || ch > '9') return false;
        const uint32_t digit = static_cast<uint32_t>(ch - '0');
        if (value > (std::numeric_limits<uint64_t>::max() - digit) / 10) return false;
        value = value * 10 + digit;
    }
    out = value;
    return true;
}

void reply_not_integer(Op& op) {
    reply_err(op.sink(), "ERR value is not an integer or out of range");
}

uint64_t random64() {
    static thread_local uint64_t state = 0;
    if (state == 0) {
        const uint64_t ticks = static_cast<uint64_t>(
            std::chrono::steady_clock::now().time_since_epoch().count());
        state = mix64(ticks ^ static_cast<uint64_t>(reinterpret_cast<uintptr_t>(&state)));
        if (state == 0) state = 0x9e3779b97f4a7c15ULL;
    }
    state ^= state >> 12;
    state ^= state << 25;
    state ^= state >> 27;
    return state * 0x2545f4914f6cdd1dULL;
}

uint64_t random_below(uint64_t bound) {
    if (bound <= 1) return 0;
    const uint64_t threshold = (uint64_t{0} - bound) % bound;
    uint64_t value;
    do { value = random64(); } while (value < threshold);
    return value % bound;
}

uint8_t width_for(int64_t value) {
    if (value >= INT16_MIN && value <= INT16_MAX) return 2;
    if (value >= INT32_MIN && value <= INT32_MAX) return 4;
    return 8;
}

void encode_integer(char* dst, uint8_t width, int64_t value) {
    if (width == 2) {
        const int16_t v = static_cast<int16_t>(value);
        std::memcpy(dst, &v, sizeof(v));
    } else if (width == 4) {
        const int32_t v = static_cast<int32_t>(value);
        std::memcpy(dst, &v, sizeof(v));
    } else {
        std::memcpy(dst, &value, sizeof(value));
    }
}

bool integer_at(const SetVal& set, uint32_t index, int64_t& out) {
    const uint32_t span = static_cast<uint32_t>(set.int_width) + 1;  // one-byte ULEB length
    Compact::Entry entry;
    if (!set.compact().at_offset(index * span, entry) || entry.value.n != set.int_width) return false;
    if (set.int_width == 2) {
        int16_t value;
        std::memcpy(&value, entry.value.p, sizeof(value));
        out = value;
    } else if (set.int_width == 4) {
        int32_t value;
        std::memcpy(&value, entry.value.p, sizeof(value));
        out = value;
    } else {
        std::memcpy(&out, entry.value.p, sizeof(out));
    }
    return true;
}

bool integer_search(const SetVal& set, int64_t wanted, uint32_t& position) {
    uint32_t lo = 0, hi = set.entries();
    while (lo < hi) {
        const uint32_t mid = lo + (hi - lo) / 2;
        int64_t value = 0;
        if (!integer_at(set, mid, value)) return false;
        if (value < wanted) lo = mid + 1;
        else hi = mid;
    }
    position = lo;
    if (lo == set.entries()) return false;
    int64_t value = 0;
    return integer_at(set, lo, value) && value == wanted;
}

uint32_t integer_text_length(int64_t value) {
    char text[24];
    return i64_to_dec(text, value);
}

bool insert_integer_compact(SetVal& set, int64_t value, uint32_t position) {
    const uint8_t needed_width = std::max(set.int_width, width_for(value));
    if (needed_width == set.int_width) {
        char bytes[8];
        encode_integer(bytes, set.int_width, value);
        return set.insert(position * (static_cast<uint32_t>(set.int_width) + 1),
                          Slice(bytes, set.int_width));
    }

    // Width upgrades rebuild once, just like Redis intset's 16->32->64 promotion. The new Compact
    // is complete before it replaces the old one, so OOM leaves the set unchanged.
    Compact replacement;
    const uint32_t old_entries = set.entries();
    for (uint32_t out_index = 0, old_index = 0; out_index <= old_entries; out_index++) {
        int64_t current = value;
        if (out_index != position) {
            if (!integer_at(set, old_index++, current)) return false;
        }
        char bytes[8];
        encode_integer(bytes, needed_width, current);
        if (!replacement.append(Slice(bytes, needed_width))) return false;
    }
    set.adopt_compact(std::move(replacement));
    set.int_width = needed_width;
    return true;
}

bool generic_find(const SetVal& set, Slice member, uint32_t& position,
                  Compact::Entry* found = nullptr) {
    for (uint32_t i = 0; i < set.offsets.size(); i++) {
        Compact::Entry entry;
        if (!set.compact().at_offset(set.offsets[i], entry)) return false;
        if (entry.value == member) {
            position = i;
            if (found) *found = entry;
            return true;
        }
    }
    return false;
}

bool convert_integer_to_generic_with(SetVal& set, Slice incoming) {
    Compact replacement;
    std::vector<uint32_t> offsets;
    try {
        offsets.reserve(static_cast<size_t>(set.entries()) + 1);
    } catch (const std::bad_alloc&) {
        return false;
    }
    for (uint32_t i = 0; i < set.entries(); i++) {
        int64_t value = 0;
        if (!integer_at(set, i, value)) return false;
        char text[24];
        const uint32_t len = i64_to_dec(text, value);
        offsets.push_back(static_cast<uint32_t>(replacement.encoded_bytes()));
        if (!replacement.append(Slice(text, len))) return false;
    }
    offsets.push_back(static_cast<uint32_t>(replacement.encoded_bytes()));
    if (!replacement.append(incoming)) return false;
    set.adopt_compact(std::move(replacement));
    set.offsets = std::move(offsets);
    set.small_encoding = SetSmallEncoding::Generic;
    return true;
}

bool promote_to_table(SetVal& set, uint32_t reserve_entries) {
    SetMemberTable replacement;
    if (!replacement.reserve(reserve_entries)) return false;
    uint64_t logical_payload = 0;

    if (set.small_encoding == SetSmallEncoding::Integer) {
        for (uint32_t i = 0; i < set.entries(); i++) {
            int64_t value = 0;
            if (!integer_at(set, i, value)) return false;
            char text[24];
            const uint32_t len = i64_to_dec(text, value);
            const Slice member(text, len);
            if (replacement.insert(member, FlatStore::hash_key(member)) !=
                SetMemberTable::InsertResult::Inserted)
                return false;
            logical_payload += len;
        }
    } else {
        for (auto entry : set.compact()) {
            if (replacement.insert(entry.value, FlatStore::hash_key(entry.value)) !=
                SetMemberTable::InsertResult::Inserted)
                return false;
            logical_payload += entry.value.n;
        }
    }
    set.table = std::move(replacement);
    set.finish_table_promotion(logical_payload);
    return true;
}

AddResult add_to_table(SetVal& set, Slice member) {
    const SetMemberTable::InsertResult result =
        set.table.insert(member, FlatStore::hash_key(member));
    if (result == SetMemberTable::InsertResult::Oom) return AddResult::Oom;
    if (result == SetMemberTable::InsertResult::Exists) return AddResult::Exists;
    set.note_expanded_insert(member.n, set.table.allocation_bytes());
    set.max_member_bytes = std::max(set.max_member_bytes, member.n);
    return AddResult::Added;
}

AddResult add_member(SetVal& set, Slice member, const CompactLimit& limit) {
    if (set.encoding() == CollectionEncoding::Hashtable) return add_to_table(set, member);
    if (set.entries() == std::numeric_limits<uint32_t>::max()) return AddResult::Oom;

    if (set.small_encoding == SetSmallEncoding::Integer) {
        int64_t integer = 0;
        if (parse_i64_strict(member, integer)) {
            uint32_t position = 0;
            if (integer_search(set, integer, position)) return AddResult::Exists;
            const uint32_t resulting = set.entries() + 1;
            if (!set.compact_fits(limit, resulting, integer_text_length(integer))) {
                if (!promote_to_table(set, resulting)) return AddResult::Oom;
                return add_to_table(set, member);
            }
            if (!insert_integer_compact(set, integer, position)) return AddResult::Oom;
            set.max_member_bytes = std::max(set.max_member_bytes, integer_text_length(integer));
            return AddResult::Added;
        }

        const uint32_t resulting = set.entries() + 1;
        const uint32_t incoming_max = std::max(set.max_member_bytes, member.n);
        if (set.compact_fits(limit, resulting, incoming_max)) {
            if (!convert_integer_to_generic_with(set, member)) return AddResult::Oom;
            set.max_member_bytes = incoming_max;
            return AddResult::Added;
        }
        if (!promote_to_table(set, resulting)) return AddResult::Oom;
        return add_to_table(set, member);
    }

    uint32_t position = 0;
    if (generic_find(set, member, position)) return AddResult::Exists;
    const uint32_t resulting = set.entries() + 1;
    if (!set.compact_fits(limit, resulting, member.n)) {
        if (!promote_to_table(set, resulting)) return AddResult::Oom;
        return add_to_table(set, member);
    }
    try {
        set.offsets.reserve(static_cast<size_t>(resulting));
    } catch (const std::bad_alloc&) {
        return AddResult::Oom;
    }
    const uint32_t offset = static_cast<uint32_t>(set.compact().encoded_bytes());
    if (!set.append(member)) return AddResult::Oom;
    set.offsets.push_back(offset);
    set.max_member_bytes = std::max(set.max_member_bytes, member.n);
    return AddResult::Added;
}

bool contains_member(const SetVal& set, Slice member) {
    if (set.encoding() == CollectionEncoding::Hashtable)
        return set.table.find(member, FlatStore::hash_key(member)) != SetMemberTable::npos;
    if (set.small_encoding == SetSmallEncoding::Generic) {
        uint32_t position = 0;
        return generic_find(set, member, position);
    }
    int64_t integer = 0;
    if (!parse_i64_strict(member, integer)) return false;
    uint32_t position = 0;
    return integer_search(set, integer, position);
}

bool remove_member(SetVal& set, Slice member) {
    if (set.encoding() == CollectionEncoding::Hashtable) {
        uint32_t erased_bytes = 0;
        if (!set.table.erase(member, FlatStore::hash_key(member), erased_bytes)) return false;
        set.note_expanded_delete(erased_bytes, set.table.allocation_bytes());
        return true;
    }

    if (set.small_encoding == SetSmallEncoding::Integer) {
        int64_t integer = 0;
        if (!parse_i64_strict(member, integer)) return false;
        uint32_t position = 0;
        if (!integer_search(set, integer, position)) return false;
        Compact::Entry entry;
        const uint32_t offset = position * (static_cast<uint32_t>(set.int_width) + 1);
        return set.compact().at_offset(offset, entry) && set.erase(entry);
    }

    uint32_t position = 0;
    Compact::Entry entry;
    if (!generic_find(set, member, position, &entry)) return false;
    const uint32_t removed_span = entry.span;
    if (!set.erase(entry)) return false;
    set.offsets.erase(set.offsets.begin() + position);
    for (uint32_t i = position; i < set.offsets.size(); i++) set.offsets[i] -= removed_span;
    return true;
}

template <typename Fn>
bool with_member_at(const SetVal& set, uint32_t index, Fn&& fn) {
    if (set.encoding() == CollectionEncoding::Hashtable) {
        const uint32_t slot = set.table.slot_for_dense(index);
        if (slot == SetMemberTable::npos) return false;
        fn(set.table.value_at(slot));
        return true;
    }
    if (set.small_encoding == SetSmallEncoding::Generic) {
        if (index >= set.offsets.size()) return false;
        Compact::Entry entry;
        if (!set.compact().at_offset(set.offsets[index], entry)) return false;
        fn(entry.value);
        return true;
    }
    int64_t integer = 0;
    if (!integer_at(set, index, integer)) return false;
    char text[24];
    const uint32_t len = i64_to_dec(text, integer);
    fn(Slice(text, len));
    return true;
}

template <typename Fn>
void for_each_member(const SetVal& set, Fn&& fn) {
    if (set.encoding() == CollectionEncoding::Hashtable) {
        for (uint32_t slot = 0; slot < set.table.slot_count(); slot++)
            if (set.table.live_at(slot)) fn(set.table.value_at(slot));
        return;
    }
    if (set.small_encoding == SetSmallEncoding::Generic) {
        for (auto entry : set.compact()) fn(entry.value);
        return;
    }
    for (uint32_t i = 0; i < set.entries(); i++) {
        int64_t integer = 0;
        if (!integer_at(set, i, integer)) continue;
        char text[24];
        const uint32_t len = i64_to_dec(text, integer);
        fn(Slice(text, len));
    }
}

bool glob_match_impl(const char* pattern, size_t pattern_len, const char* string,
                     size_t string_len, uint32_t nesting, bool& skip_longer) {
    if (nesting > 1000) return false;
    while (pattern_len && string_len) {
        switch (*pattern) {
            case '*': {
                while (pattern_len > 1 && pattern[1] == '*') {
                    pattern++;
                    pattern_len--;
                }
                if (pattern_len == 1) return true;
                while (string_len) {
                    if (glob_match_impl(pattern + 1, pattern_len - 1, string, string_len,
                                        nesting + 1, skip_longer))
                        return true;
                    if (skip_longer) return false;
                    string++;
                    string_len--;
                }
                skip_longer = true;
                return false;
            }
            case '?':
                string++;
                string_len--;
                break;
            case '[': {
                pattern++;
                pattern_len--;
                bool invert = pattern_len && pattern[0] == '^';
                if (invert) {
                    pattern++;
                    pattern_len--;
                }
                bool matched = false;
                while (true) {
                    if (pattern_len >= 2 && pattern[0] == '\\') {
                        pattern++;
                        pattern_len--;
                        if (pattern[0] == string[0]) matched = true;
                    } else if (pattern_len == 0) {
                        pattern--;
                        pattern_len++;
                        break;
                    } else if (pattern[0] == ']') {
                        break;
                    } else if (pattern_len >= 3 && pattern[1] == '-') {
                        unsigned char begin = static_cast<unsigned char>(pattern[0]);
                        unsigned char end = static_cast<unsigned char>(pattern[2]);
                        const unsigned char ch = static_cast<unsigned char>(string[0]);
                        if (begin > end) std::swap(begin, end);
                        if (ch >= begin && ch <= end) matched = true;
                        pattern += 2;
                        pattern_len -= 2;
                    } else if (pattern[0] == string[0]) {
                        matched = true;
                    }
                    pattern++;
                    pattern_len--;
                }
                if (invert) matched = !matched;
                if (!matched) return false;
                string++;
                string_len--;
                break;
            }
            case '\\':
                if (pattern_len >= 2) {
                    pattern++;
                    pattern_len--;
                }
                [[fallthrough]];
            default:
                if (pattern[0] != string[0]) return false;
                string++;
                string_len--;
                break;
        }
        pattern++;
        pattern_len--;
        if (string_len == 0) {
            while (pattern_len && pattern[0] == '*') {
                pattern++;
                pattern_len--;
            }
            break;
        }
    }
    return pattern_len == 0 && string_len == 0;
}

bool glob_match(Slice pattern, Slice value) {
    bool skip_longer = false;
    return glob_match_impl(pattern.p, pattern.n, value.p, value.n, 0, skip_longer);
}

void reply_scan(Op& op, uint64_t cursor, const std::vector<uint32_t>& slots,
                const SetMemberTable& table) {
    reply_array_header(op.sink(), 2);
    char text[24];
    const uint32_t len = u64_to_dec(text, cursor);
    reply_bulk(op.sink(), Slice(text, len));
    reply_array_header(op.sink(), slots.size());
    for (uint32_t slot : slots) reply_bulk(op.sink(), table.value_at(slot));
}

void reply_empty_scan(Op& op) {
    reply_array_header(op.sink(), 2);
    reply_bulk(op.sink(), Slice("0", 1));
    reply_array_header(op.sink(), 0);
}

SetVal* as_set(KvObj* object) {
    return static_cast<SetVal*>(object->external_ptr());
}

void cmd_sadd(Shard& shard, Op& op) {
    KvObj* object = shard.store().find(op.hash, op.key());
    if (object) {
        auto sink = op.sink();
        if (!obj_type_check(object, Type::Set, sink)) return;
    }

    SetVal* set = object ? as_set(object) : new (std::nothrow) SetVal;
    if (!set) {
        reply_err(op.sink(), "ERR out of memory");
        return;
    }

    const CompactLimit& limit = shard.type_limits().set;
    const uint32_t hint = op.argc() - 2;
    if (!object) {
        int64_t first_integer = 0;
        if (!parse_i64_strict(op.arg(2), first_integer)) {
            set->small_encoding = SetSmallEncoding::Generic;
            if (hint > limit.max_entries || op.arg(2).n > limit.max_value) {
                if (!set->table.reserve(hint)) {
                    delete set;
                    reply_err(op.sink(), "ERR out of memory");
                    return;
                }
                set->finish_table_promotion(0);
            }
        } else if (hint > limit.max_entries) {
            if (!set->table.reserve(hint)) {
                delete set;
                reply_err(op.sink(), "ERR out of memory");
                return;
            }
            set->finish_table_promotion(0);
        }
    } else if (set->encoding() == CollectionEncoding::Compact && hint > limit.max_entries) {
        // Redis/Valkey apply the multi-add size hint before looking for duplicates. Preserve that
        // observable upgrade rule while keeping the decision O(1).
        if (!promote_to_table(*set, std::max(set->entries(), hint))) {
            reply_err(op.sink(), "ERR out of memory");
            return;
        }
    }

    uint32_t added = 0;
    for (uint32_t i = 2; i < op.argc(); i++) {
        const AddResult result = add_member(*set, op.arg(i), limit);
        if (result == AddResult::Oom) {
            if (!object) delete set;
            reply_err(op.sink(), "ERR out of memory");
            return;
        }
        added += result == AddResult::Added;
    }

    if (!object) {
        object = kvobj_new_set(op.key(), set);
        if (!object) {
            delete set;
            reply_err(op.sink(), "ERR out of memory");
            return;
        }
        const FlatStore::InsertResult inserted_ = shard.store().insert(op.hash, object);
if (inserted_ != FlatStore::InsertResult::Inserted) {
    kvobj_free(object);
    if (inserted_ == FlatStore::InsertResult::MaxmemoryOom) reply_maxmemory_oom(op);
    else reply_err(op.sink(), "ERR keyspace insert failed");
    return;
        }
    }
    reply_int(op.sink(), added);
}

void cmd_srem(Shard& shard, Op& op) {
    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) {
        reply_int(op.sink(), 0);
        return;
    }
    auto sink = op.sink();
    if (!obj_type_check(object, Type::Set, sink)) return;
    SetVal* set = as_set(object);
    uint32_t removed = 0;
    for (uint32_t i = 2; i < op.argc(); i++) removed += remove_member(*set, op.arg(i));
    if (set->entries() == 0) shard.store().erase(op.hash, op.key());
    reply_int(op.sink(), removed);
}

void cmd_sismember(Shard& shard, Op& op) {
    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) {
        reply_int(op.sink(), 0);
        return;
    }
    auto sink = op.sink();
    if (!obj_type_check(object, Type::Set, sink)) return;
    reply_int(op.sink(), contains_member(*as_set(object), op.arg(2)) ? 1 : 0);
}

void cmd_smismember(Shard& shard, Op& op) {
    KvObj* object = shard.store().find(op.hash, op.key());
    if (object) {
        auto sink = op.sink();
        if (!obj_type_check(object, Type::Set, sink)) return;
    }
    reply_array_header(op.sink(), op.argc() - 2);
    const SetVal* set = object ? as_set(object) : nullptr;
    for (uint32_t i = 2; i < op.argc(); i++)
        reply_int(op.sink(), set && contains_member(*set, op.arg(i)) ? 1 : 0);
}

void cmd_scard(Shard& shard, Op& op) {
    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) {
        reply_int(op.sink(), 0);
        return;
    }
    auto sink = op.sink();
    if (!obj_type_check(object, Type::Set, sink)) return;
    reply_int(op.sink(), as_set(object)->entries());
}

void cmd_smembers(Shard& shard, Op& op) {
    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) {
        reply_array_header(op.sink(), 0);
        return;
    }
    auto sink = op.sink();
    if (!obj_type_check(object, Type::Set, sink)) return;
    const SetVal& set = *as_set(object);
    reply_array_header(op.sink(), set.entries());
    for_each_member(set, [&](Slice member) { reply_bulk(op.sink(), member); });
}

void cmd_spop(Shard& shard, Op& op) {
    const bool with_count = op.argc() == 3;
    int64_t signed_count = 1;
    if (with_count) {
        if (!parse_i64_strict(op.arg(2), signed_count)) {
            reply_not_integer(op);
            return;
        }
        if (signed_count < 0) {
            reply_err(op.sink(), "ERR value is out of range, must be positive");
            return;
        }
    }

    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) {
        if (with_count) reply_array_header(op.sink(), 0);
        else reply_nil(op.sink());
        return;
    }
    auto sink = op.sink();
    if (!obj_type_check(object, Type::Set, sink)) return;
    SetVal* set = as_set(object);
    const uint32_t size = set->entries();
    const uint64_t count = static_cast<uint64_t>(signed_count);
    if (count == 0) {
        reply_array_header(op.sink(), 0);
        return;
    }

    if (count >= size) {
        if (with_count) reply_array_header(op.sink(), size);
        for_each_member(*set, [&](Slice member) { reply_bulk(op.sink(), member); });
        shard.store().erase(op.hash, op.key());
        return;
    }

    // Compact deletion would move bytes proportional to the collection. Promote once (charged to
    // the preceding compact writes), then every random pick and tombstone delete is O(1).
    if (set->encoding() != CollectionEncoding::Hashtable &&
        !promote_to_table(*set, size)) {
        reply_err(op.sink(), "ERR out of memory");
        return;
    }
    if (with_count) reply_array_header(op.sink(), count);
    for (uint64_t i = 0; i < count; i++) {
        const uint32_t slot = set->table.random_slot(random64());
        const Slice member = set->table.value_at(slot);
        reply_bulk(op.sink(), member);
        uint32_t erased_bytes = 0;
        set->table.erase_at(slot, erased_bytes);
        set->note_expanded_delete(erased_bytes, set->table.allocation_bytes());
    }
}

bool select_unique(uint32_t population, uint32_t count, std::vector<uint32_t>& picks) {
    std::unordered_set<uint32_t> selected;
    try {
        selected.reserve(count);
        picks.reserve(count);
        for (uint64_t j = static_cast<uint64_t>(population) - count; j < population; j++) {
            const uint32_t candidate = static_cast<uint32_t>(random_below(j + 1));
            if (selected.insert(candidate).second) {
                picks.push_back(candidate);
            } else {
                const uint32_t fallback = static_cast<uint32_t>(j);
                selected.insert(fallback);
                picks.push_back(fallback);
            }
        }
    } catch (const std::bad_alloc&) {
        return false;
    }
    return true;
}

void cmd_srandmember(Shard& shard, Op& op) {
    const bool with_count = op.argc() == 3;
    int64_t count = 1;
    if (with_count) {
        if (!parse_i64_strict(op.arg(2), count)) {
            reply_not_integer(op);
            return;
        }
        if (count == INT64_MIN) {
            reply_outofrange(op.sink());
            return;
        }
    }

    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) {
        if (with_count) reply_array_header(op.sink(), 0);
        else reply_nil(op.sink());
        return;
    }
    auto sink = op.sink();
    if (!obj_type_check(object, Type::Set, sink)) return;
    const SetVal& set = *as_set(object);
    const uint32_t size = set.entries();

    if (!with_count) {
        const uint32_t pick = static_cast<uint32_t>(random_below(size));
        with_member_at(set, pick, [&](Slice member) { reply_bulk(op.sink(), member); });
        return;
    }
    if (count == 0) {
        reply_array_header(op.sink(), 0);
        return;
    }
    if (count < 0) {
        const uint64_t picks = static_cast<uint64_t>(-count);
        reply_array_header(op.sink(), picks);
        for (uint64_t i = 0; i < picks; i++) {
            const uint32_t pick = static_cast<uint32_t>(random_below(size));
            with_member_at(set, pick, [&](Slice member) { reply_bulk(op.sink(), member); });
        }
        return;
    }

    const uint32_t picks_count = static_cast<uint64_t>(count) >= size
                                     ? size
                                     : static_cast<uint32_t>(count);
    if (picks_count == size) {
        reply_array_header(op.sink(), size);
        for_each_member(set, [&](Slice member) { reply_bulk(op.sink(), member); });
        return;
    }
    std::vector<uint32_t> picks;
    if (!select_unique(size, picks_count, picks)) {
        reply_err(op.sink(), "ERR out of memory");
        return;
    }
    reply_array_header(op.sink(), picks.size());
    for (uint32_t pick : picks)
        with_member_at(set, pick, [&](Slice member) { reply_bulk(op.sink(), member); });
}

struct ScanOptions {
    uint64_t count = 10;
    Slice pattern;
    bool use_pattern = false;
};

bool parse_scan_options(Op& op, ScanOptions& options) {
    for (uint32_t i = 3; i < op.argc();) {
        if (op.arg(i).eq_icase("count") && i + 1 < op.argc()) {
            int64_t count = 0;
            if (!parse_i64_strict(op.arg(i + 1), count)) {
                reply_not_integer(op);
                return false;
            }
            if (count < 1) {
                reply_syntax(op.sink());
                return false;
            }
            options.count = static_cast<uint64_t>(count);
            i += 2;
        } else if (op.arg(i).eq_icase("match") && i + 1 < op.argc()) {
            options.pattern = op.arg(i + 1);
            options.use_pattern = !(options.pattern.n == 1 && options.pattern.p[0] == '*');
            i += 2;
        } else {
            reply_syntax(op.sink());
            return false;
        }
    }
    return true;
}

void cmd_sscan(Shard& shard, Op& op) {
    uint64_t cursor = 0;
    if (!parse_cursor(op.arg(2), cursor)) {
        reply_err(op.sink(), "ERR invalid cursor");
        return;
    }
    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) {
        reply_empty_scan(op);
        return;
    }
    auto sink = op.sink();
    if (!obj_type_check(object, Type::Set, sink)) return;
    ScanOptions options;
    if (!parse_scan_options(op, options)) return;
    const SetVal& set = *as_set(object);

    if (set.encoding() != CollectionEncoding::Hashtable) {
        uint64_t matches = 0;
        for_each_member(set, [&](Slice member) {
            if (!options.use_pattern || glob_match(options.pattern, member)) matches++;
        });
        reply_array_header(op.sink(), 2);
        reply_bulk(op.sink(), Slice("0", 1));
        reply_array_header(op.sink(), matches);
        for_each_member(set, [&](Slice member) {
            if (!options.use_pattern || glob_match(options.pattern, member))
                reply_bulk(op.sink(), member);
        });
        return;
    }

    const SetMemberTable& table = set.table;
    uint32_t position = 0;
    const uint32_t cursor_generation = static_cast<uint32_t>(cursor >> 32);
    if (cursor != 0 && cursor_generation == table.generation())
        position = static_cast<uint32_t>(cursor);
    if (position >= table.slot_count()) position = 0;

    std::vector<uint32_t> matches;
    try {
        matches.reserve(static_cast<size_t>(std::min<uint64_t>(options.count, table.size())));
    } catch (const std::bad_alloc&) {
        reply_err(op.sink(), "ERR out of memory");
        return;
    }
    const uint64_t max_probes = options.count > std::numeric_limits<uint64_t>::max() / 10
                                    ? std::numeric_limits<uint64_t>::max()
                                    : options.count * 10;
    uint64_t probes = 0, sampled = 0;
    while (position < table.slot_count() && probes < max_probes && sampled < options.count) {
        if (table.live_at(position)) {
            sampled++;
            const Slice member = table.value_at(position);
            if (!options.use_pattern || glob_match(options.pattern, member))
                matches.push_back(position);
        }
        position++;
        probes++;
    }
    const uint64_t next_cursor = position == table.slot_count()
                                     ? 0
                                     : (static_cast<uint64_t>(table.generation()) << 32) | position;
    reply_scan(op, next_cursor, matches, table);
}

static const CommandSpec kTable[] = {
    // name          min max flags                handler          first last step
    {"SADD",          3, -1, CmdFlags::Write,     cmd_sadd,          1,  1,  1},
    {"SREM",          3, -1, CmdFlags::Write,     cmd_srem,          1,  1,  1},
    {"SISMEMBER",     3,  3, CmdFlags::Readonly,  cmd_sismember,     1,  1,  1},
    {"SMISMEMBER",    3, -1, CmdFlags::Readonly,  cmd_smismember,    1,  1,  1},
    {"SCARD",         2,  2, CmdFlags::Readonly,  cmd_scard,         1,  1,  1},
    {"SMEMBERS",      2,  2, CmdFlags::Readonly,  cmd_smembers,      1,  1,  1},
    {"SPOP",          2,  3, CmdFlags::Write,     cmd_spop,          1,  1,  1},
    {"SRANDMEMBER",   2,  3, CmdFlags::Readonly,  cmd_srandmember,   1,  1,  1},
    {"SSCAN",         3, -1, CmdFlags::Readonly,  cmd_sscan,         1,  1,  1},
};

}  // namespace

CommandTable set_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
