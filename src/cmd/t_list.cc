// t_list.cc — Redis-compatible single-key list commands.
//
// Small lists are one Compact. Expanded lists are a doubly linked list of Compact nodes; all
// ownership remains on the shard executor and no collection storage is borrowed by replies.
#include "command.h"
#include "../core/shard.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include "../snapshot/format.h"
#include "../store/kvobj.h"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <limits>
#include <new>
#include <vector>

namespace tomo {

void reply_maxmemory_oom(Op& op);
namespace {

// Redis/Valkey/our fork map list-max-listpack-size=-2 to 8 KiB. Dragonfly's QList uses the same
// default and the same 16-bit per-node count bound. An element larger than the byte limit lives in
// a one-element Compact node, matching quicklist's isolated plain-node policy while retaining this
// tree's one Compact node representation.
constexpr uint32_t kNodeMaxBytes = 8 * 1024;
constexpr uint32_t kNodeMaxEntries = std::numeric_limits<uint16_t>::max();

void reply_oom(Op& op) { reply_err(op.sink(), "ERR out of memory"); }
void reply_integer_error(Op& op) {
    reply_err(op.sink(), "ERR value is not an integer or out of range");
}
void reply_non_min_i64(Op& op) {
    reply_err(op.sink(), "ERR value is out of range, value must between -9223372036854775807 and 9223372036854775807");
}

bool parse_i64(Slice s, int64_t& out) {
    if (!s.n) return false;
    uint32_t pos = 0;
    bool negative = false;
    if (s.p[pos] == '-') {
        negative = true;
        if (++pos == s.n) return false;
    }
    uint64_t value = 0;
    const uint64_t limit = negative ? (uint64_t{1} << 63)
                                    : static_cast<uint64_t>(std::numeric_limits<int64_t>::max());
    for (; pos < s.n; pos++) {
        const char ch = s.p[pos];
        if (ch < '0' || ch > '9') return false;
        const uint32_t digit = static_cast<uint32_t>(ch - '0');
        if (value > (limit - digit) / 10) return false;
        value = value * 10 + digit;
    }
    out = negative ? (value == (uint64_t{1} << 63)
                          ? std::numeric_limits<int64_t>::min()
                          : -static_cast<int64_t>(value))
                   : static_cast<int64_t>(value);
    return true;
}

ListVal* list_value(KvObj* o) { return static_cast<ListVal*>(o->external_ptr()); }

// ObjectSizeTracker now lives in flatstore.h (shared by every family).

void clear_nodes(ListVal& list) {
    ListNode* node = list.head;
    while (node) {
        ListNode* next = node->next;
        delete node;
        node = next;
    }
    list.head = list.tail = nullptr;
    list.node_allocation_bytes = 0;
}

void adopt_nodes(ListVal& dst, ListVal& src) {
    clear_nodes(dst);
    dst.head = src.head;
    dst.tail = src.tail;
    dst.node_allocation_bytes = src.node_allocation_bytes;
    src.head = src.tail = nullptr;
    src.node_allocation_bytes = 0;
}

bool node_can_insert(const ListNode* node, Slice value) {
    if (!node || value.n > kNodeMaxBytes || node->values.size() >= kNodeMaxEntries) return false;
    const uint64_t bytes = node->values.encoded_bytes();
    return bytes + Compact::entry_encoded_size(value.n) <= kNodeMaxBytes;
}

bool expanded_push(ListVal& list, Slice value, bool left) {
    ListNode* node = left ? list.head : list.tail;
    if (node_can_insert(node, value)) {
        const size_t old_capacity = node->values.capacity_bytes();
        const bool ok = left ? node->values.prepend(value) : node->values.append(value);
        list.node_allocation_bytes += node->values.capacity_bytes() - old_capacity;
        if (list.encoding() == CollectionEncoding::Deque)
            list.note_expanded_allocation(list.node_allocation_bytes);
        if (!ok) return false;
        return true;
    }

    auto* fresh = new (std::nothrow) ListNode;
    if (!fresh) return false;
    if (!fresh->values.append(value)) {
        delete fresh;
        return false;
    }
    if (!list.head) {
        list.head = list.tail = fresh;
    } else if (left) {
        fresh->next = list.head;
        list.head->prev = fresh;
        list.head = fresh;
    } else {
        fresh->prev = list.tail;
        list.tail->next = fresh;
        list.tail = fresh;
    }
    list.node_allocation_bytes += sizeof(ListNode) + fresh->values.capacity_bytes();
    return true;
}

bool expanded_edge(const ListVal& list, bool left, Compact::Entry& out) {
    const ListNode* node = left ? list.head : list.tail;
    return node && (left ? node->values.first(out) : node->values.last(out));
}

bool expanded_pop(ListVal& list, bool left, uint32_t& payload_size) {
    ListNode* node = left ? list.head : list.tail;
    if (!node) return false;
    const bool ok = left ? node->values.pop_front(&payload_size)
                         : node->values.pop_back(&payload_size);
    if (!ok) return false;
    if (!node->values.empty()) return true;

    if (node->prev) node->prev->next = node->next;
    else list.head = node->next;
    if (node->next) node->next->prev = node->prev;
    else list.tail = node->prev;
    list.node_allocation_bytes -= sizeof(ListNode) + node->values.capacity_bytes();
    delete node;
    return true;
}

class ListCursor {
public:
    static ListCursor seek(const ListVal& list, uint32_t logical_index) {
        ListCursor cur;
        if (logical_index >= list.entries()) return cur;
        cur.list_ = &list;
        cur.global_ = logical_index;
        if (list.encoding() == CollectionEncoding::Compact) {
            cur.pack_ = &list.compact();
            cur.local_ = logical_index;
            cur.valid_ = true;
            return cur;
        }

        if (logical_index <= list.entries() / 2) {
            uint32_t remaining = logical_index;
            cur.node_ = list.head;
            while (cur.node_ && remaining >= cur.node_->values.size()) {
                remaining -= cur.node_->values.size();
                cur.node_ = cur.node_->next;
            }
            if (cur.node_) {
                cur.pack_ = &cur.node_->values;
                cur.local_ = remaining;
                cur.valid_ = true;
            }
        } else {
            uint32_t remaining = list.entries() - logical_index - 1;
            cur.node_ = list.tail;
            while (cur.node_ && remaining >= cur.node_->values.size()) {
                remaining -= cur.node_->values.size();
                cur.node_ = cur.node_->prev;
            }
            if (cur.node_) {
                cur.pack_ = &cur.node_->values;
                cur.local_ = cur.node_->values.size() - remaining - 1;
                cur.valid_ = true;
            }
        }
        return cur;
    }

    static ListCursor edge(const ListVal& list, bool reverse) {
        ListCursor cur = seek(list, reverse ? list.entries() - 1 : 0);
        cur.reverse_ = reverse;
        return cur;
    }

    bool valid() const { return valid_; }
    uint32_t position() const { return global_; }
    bool get(Compact::Entry& out) const { return valid_ && pack_->at(local_, out); }

    void next() {
        if (!valid_) return;
        if (!reverse_) {
            global_++;
            if (local_ + 1 < pack_->size()) {
                local_++;
                return;
            }
            if (!node_) {
                valid_ = false;
                return;
            }
            node_ = node_->next;
            if (!node_) {
                valid_ = false;
                return;
            }
            pack_ = &node_->values;
            local_ = 0;
        } else {
            if (global_) global_--;
            if (local_) {
                local_--;
                return;
            }
            if (!node_) {
                valid_ = false;
                return;
            }
            node_ = node_->prev;
            if (!node_) {
                valid_ = false;
                return;
            }
            pack_ = &node_->values;
            local_ = pack_->size() - 1;
        }
    }

private:
    const ListVal*  list_ = nullptr;
    const ListNode* node_ = nullptr;
    const Compact*  pack_ = nullptr;
    uint32_t        local_ = 0;
    uint32_t        global_ = 0;
    bool            reverse_ = false;
    bool            valid_ = false;
};

bool append_all_expanded(const ListVal& source, ListVal& destination) {
    for (ListCursor cur = ListCursor::edge(source, false); cur.valid(); cur.next()) {
        Compact::Entry entry;
        if (!cur.get(entry) || !expanded_push(destination, entry.value, false)) return false;
    }
    return true;
}

bool normalize_index(int64_t index, uint32_t size, uint32_t& normalized) {
    int64_t value = index;
    if (value < 0) value += static_cast<int64_t>(size);
    if (value < 0 || static_cast<uint64_t>(value) >= size) return false;
    normalized = static_cast<uint32_t>(value);
    return true;
}

bool normalize_range(int64_t start, int64_t stop, uint32_t size,
                     uint32_t& first, uint32_t& count) {
    if (!size) return false;
    if (start < 0) start += static_cast<int64_t>(size);
    if (stop < 0) stop += static_cast<int64_t>(size);
    if (start < 0) start = 0;
    if (start > stop || start >= static_cast<int64_t>(size) || stop < 0) return false;
    if (stop >= static_cast<int64_t>(size)) stop = static_cast<int64_t>(size) - 1;
    first = static_cast<uint32_t>(start);
    count = static_cast<uint32_t>(stop - start + 1);
    return true;
}

void push_generic(Shard& shard, Op& op, bool left, bool only_existing) {
    KvObj* object = shard.store().find(op.hash, op.key());
    if (!obj_type_check(object, Type::List, op.sink())) return;
    if (!object && only_existing) {
        reply_int(op.sink(), 0);
        return;
    }

    const uint32_t added = op.argc() - 2;
    uint64_t incoming_payload = 0;
    for (uint32_t i = 2; i < op.argc(); i++) incoming_payload += op.arg(i).n;

    if (!object) {
        auto* list = new (std::nothrow) ListVal;
        if (!list) { reply_oom(op); return; }
        const CompactLimit& limit = shard.type_limits().list;
        if (list->list_fits(limit, added, incoming_payload)) {
            for (uint32_t i = 2; i < op.argc(); i++) {
                const bool ok = left ? list->prepend(op.arg(i)) : list->append(op.arg(i));
                if (!ok) { delete list; reply_oom(op); return; }
            }
        } else {
            for (uint32_t i = 2; i < op.argc(); i++) {
                if (!expanded_push(*list, op.arg(i), left)) {
                    delete list;
                    reply_oom(op);
                    return;
                }
            }
            const uint64_t allocation = list->node_allocation_bytes;
            list->promote(CollectionEncoding::Deque, allocation);
            for (uint32_t i = 2; i < op.argc(); i++)
                list->note_expanded_insert(op.arg(i).n, allocation);
        }

        KvObj* fresh = kvobj_new_list(op.key(), list);
        if (!fresh) { delete list; reply_oom(op); return; }
        const FlatStore::InsertResult inserted_ = shard.store().insert(op.hash, fresh);
if (inserted_ != FlatStore::InsertResult::Inserted) {
    kvobj_free(fresh);
    if (inserted_ == FlatStore::InsertResult::MaxmemoryOom) reply_maxmemory_oom(op);
    else reply_err(op.sink(), "ERR keyspace insert failed");
    return;
        }
        reply_int(op.sink(), list->entries());
        return;
    }

    ListVal& list = *list_value(object);
    ObjectSizeTracker size_tracker(shard.store(), object);
    if (static_cast<uint64_t>(list.entries()) + added > std::numeric_limits<uint32_t>::max()) {
        reply_err(op.sink(), "ERR list exceeds maximum allowed size");
        return;
    }

    if (list.encoding() == CollectionEncoding::Compact) {
        const uint32_t resulting_entries = list.entries() + added;
        const uint64_t resulting_payload = list.payload_bytes() + incoming_payload;
        if (list.list_fits(shard.type_limits().list, resulting_entries, resulting_payload)) {
            for (uint32_t i = 2; i < op.argc(); i++) {
                const bool ok = left ? list.prepend(op.arg(i)) : list.append(op.arg(i));
                if (!ok) { reply_oom(op); return; }
            }
        } else {
            ListVal staging;
            if (!append_all_expanded(list, staging)) { reply_oom(op); return; }
            for (uint32_t i = 2; i < op.argc(); i++) {
                if (!expanded_push(staging, op.arg(i), left)) { reply_oom(op); return; }
            }
            adopt_nodes(list, staging);
            const uint64_t allocation = list.node_allocation_bytes;
            list.promote(CollectionEncoding::Deque, allocation);
            for (uint32_t i = 2; i < op.argc(); i++)
                list.note_expanded_insert(op.arg(i).n, allocation);
        }
    } else {
        for (uint32_t i = 2; i < op.argc(); i++) {
            if (!expanded_push(list, op.arg(i), left)) { reply_oom(op); return; }
            list.note_expanded_insert(op.arg(i).n, list.node_allocation_bytes);
        }
    }
    reply_int(op.sink(), list.entries());
}

void cmd_lpush(Shard& shard, Op& op)  { push_generic(shard, op, true, false); }
void cmd_rpush(Shard& shard, Op& op)  { push_generic(shard, op, false, false); }
void cmd_lpushx(Shard& shard, Op& op) { push_generic(shard, op, true, true); }
void cmd_rpushx(Shard& shard, Op& op) { push_generic(shard, op, false, true); }

void pop_generic(Shard& shard, Op& op, bool left) {
    const bool has_count = op.argc() == 3;
    int64_t requested = 1;
    if (has_count) {
        if (!parse_i64(op.arg(2), requested)) { reply_integer_error(op); return; }
        if (requested < 0) {
            reply_err(op.sink(), "ERR value is out of range, must be positive");
            return;
        }
    }

    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) {
        if (has_count) reply_null_array(op.sink());
        else reply_nil(op.sink());
        return;
    }
    if (!obj_type_check(object, Type::List, op.sink())) return;
    ListVal& list = *list_value(object);
    ObjectSizeTracker size_tracker(shard.store(), object);

    if (!list.entries()) {
        if (has_count) reply_null_array(op.sink());
        else reply_nil(op.sink());
        size_tracker.finish();
        shard.store().erase(op.hash, op.key());
        return;
    }

    const uint32_t amount = has_count
        ? static_cast<uint32_t>(std::min<uint64_t>(static_cast<uint64_t>(requested), list.entries()))
        : 1;
    if (has_count) reply_array_header(op.sink(), amount);
    if (!amount) return;

    for (uint32_t i = 0; i < amount; i++) {
        Compact::Entry edge;
        const bool found = list.encoding() == CollectionEncoding::Compact
            ? (left ? list.compact().first(edge) : list.compact().last(edge))
            : expanded_edge(list, left, edge);
        if (!found) break;
        reply_bulk(op.sink(), edge.value);

        uint32_t payload = 0;
        if (list.encoding() == CollectionEncoding::Compact) {
            if (left) list.pop_front(&payload);
            else list.pop_back(&payload);
        } else {
            expanded_pop(list, left, payload);
            list.note_expanded_delete(payload, list.node_allocation_bytes);
        }
    }
    if (!list.entries()) {
        size_tracker.finish();
        shard.store().erase(op.hash, op.key());
    }
}

void cmd_lpop(Shard& shard, Op& op) { pop_generic(shard, op, true); }
void cmd_rpop(Shard& shard, Op& op) { pop_generic(shard, op, false); }

void cmd_llen(Shard& shard, Op& op) {
    KvObj* object = shard.store().find(op.hash, op.key());
    if (!obj_type_check(object, Type::List, op.sink())) return;
    reply_int(op.sink(), object ? list_value(object)->entries() : 0);
}

void cmd_lindex(Shard& shard, Op& op) {
    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) { reply_nil(op.sink()); return; }
    if (!obj_type_check(object, Type::List, op.sink())) return;
    int64_t index = 0;
    if (!parse_i64(op.arg(2), index)) { reply_integer_error(op); return; }

    const ListVal& list = *list_value(object);
    uint32_t normalized = 0;
    if (!normalize_index(index, list.entries(), normalized)) { reply_nil(op.sink()); return; }
    ListCursor cur = ListCursor::seek(list, normalized);
    Compact::Entry entry;
    if (!cur.get(entry)) { reply_nil(op.sink()); return; }
    reply_bulk(op.sink(), entry.value);
}

void cmd_lrange(Shard& shard, Op& op) {
    int64_t start = 0, stop = 0;
    if (!parse_i64(op.arg(2), start) || !parse_i64(op.arg(3), stop)) {
        reply_integer_error(op);
        return;
    }
    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) { reply_array_header(op.sink(), 0); return; }
    if (!obj_type_check(object, Type::List, op.sink())) return;

    const ListVal& list = *list_value(object);
    uint32_t first = 0, count = 0;
    if (!normalize_range(start, stop, list.entries(), first, count)) {
        reply_array_header(op.sink(), 0);
        return;
    }
    reply_array_header(op.sink(), count);
    ListCursor cur = ListCursor::seek(list, first);
    for (uint32_t i = 0; i < count && cur.valid(); i++, cur.next()) {
        Compact::Entry entry;
        if (cur.get(entry)) reply_bulk(op.sink(), entry.value);
    }
}

bool build_replaced(const ListVal& source, uint32_t index, Slice value, ListVal& output) {
    for (ListCursor cur = ListCursor::edge(source, false); cur.valid(); cur.next()) {
        Compact::Entry entry;
        if (!cur.get(entry)) return false;
        if (!expanded_push(output, cur.position() == index ? value : entry.value, false)) return false;
    }
    return true;
}

void cmd_lset(Shard& shard, Op& op) {
    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) { reply_err(op.sink(), "ERR no such key"); return; }
    if (!obj_type_check(object, Type::List, op.sink())) return;
    int64_t index = 0;
    if (!parse_i64(op.arg(2), index)) { reply_integer_error(op); return; }

    ListVal& list = *list_value(object);
    ObjectSizeTracker size_tracker(shard.store(), object);
    uint32_t normalized = 0;
    if (!normalize_index(index, list.entries(), normalized)) {
        reply_err(op.sink(), "ERR index out of range");
        return;
    }
    ListCursor old_cursor = ListCursor::seek(list, normalized);
    Compact::Entry old_entry;
    if (!old_cursor.get(old_entry)) { reply_err(op.sink(), "ERR index out of range"); return; }
    const uint32_t old_payload = old_entry.value.n;
    const Slice replacement = op.arg(3);

    if (list.encoding() == CollectionEncoding::Compact &&
        list.list_fits(shard.type_limits().list, list.entries(),
                       list.payload_bytes() - old_payload + replacement.n)) {
        Compact::Entry direct;
        list.compact().at(normalized, direct);
        if (!list.replace(direct, replacement)) { reply_oom(op); return; }
    } else {
        ListVal staging;
        if (!build_replaced(list, normalized, replacement, staging)) { reply_oom(op); return; }
        adopt_nodes(list, staging);
        const uint64_t allocation = list.node_allocation_bytes;
        if (list.encoding() == CollectionEncoding::Compact)
            list.promote(CollectionEncoding::Deque, allocation);
        list.note_expanded_replace(old_payload, replacement.n, allocation);
    }
    reply_ok(op.sink());
}

void cmd_linsert(Shard& shard, Op& op) {
    bool before = false;
    if (op.arg(2).eq_icase("before")) before = true;
    else if (!op.arg(2).eq_icase("after")) { reply_syntax(op.sink()); return; }

    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) { reply_int(op.sink(), 0); return; }
    if (!obj_type_check(object, Type::List, op.sink())) return;
    ListVal& list = *list_value(object);
    ObjectSizeTracker size_tracker(shard.store(), object);

    // Redis performs the append-size conversion before seeking the pivot so it never has to keep
    // a compact iterator alive across promotion. Consequently, a missing pivot may still leave a
    // one-way encoding promotion behind; preserve that observable OBJECT ENCODING behavior.
    if (list.encoding() == CollectionEncoding::Compact &&
        (list.entries() == std::numeric_limits<uint32_t>::max() ||
         !list.list_fits(shard.type_limits().list, list.entries() + 1,
                         list.payload_bytes() + op.arg(4).n))) {
        ListVal staging;
        if (!append_all_expanded(list, staging)) { reply_oom(op); return; }
        adopt_nodes(list, staging);
        list.promote(CollectionEncoding::Deque, list.node_allocation_bytes);
    }

    uint32_t pivot_index = 0;
    bool found = false;
    for (ListCursor cur = ListCursor::edge(list, false); cur.valid(); cur.next()) {
        Compact::Entry entry;
        if (cur.get(entry) && entry.value == op.arg(3)) {
            pivot_index = cur.position();
            found = true;
            break;
        }
    }
    if (!found) { reply_int(op.sink(), -1); return; }
    if (list.entries() == std::numeric_limits<uint32_t>::max()) {
        reply_err(op.sink(), "ERR list exceeds maximum allowed size");
        return;
    }

    const Slice inserted = op.arg(4);
    if (list.encoding() == CollectionEncoding::Compact) {
        Compact::Entry pivot;
        list.compact().at(pivot_index, pivot);
        const bool ok = before ? list.insert_before(pivot, inserted)
                               : list.insert_after(pivot, inserted);
        if (!ok) { reply_oom(op); return; }
    } else {
        ListVal staging;
        for (ListCursor cur = ListCursor::edge(list, false); cur.valid(); cur.next()) {
            Compact::Entry entry;
            if (!cur.get(entry)) { reply_oom(op); return; }
            if (cur.position() == pivot_index && before &&
                !expanded_push(staging, inserted, false)) { reply_oom(op); return; }
            if (!expanded_push(staging, entry.value, false)) { reply_oom(op); return; }
            if (cur.position() == pivot_index && !before &&
                !expanded_push(staging, inserted, false)) { reply_oom(op); return; }
        }
        adopt_nodes(list, staging);
        const uint64_t allocation = list.node_allocation_bytes;
        if (list.encoding() == CollectionEncoding::Compact)
            list.promote(CollectionEncoding::Deque, allocation);
        list.note_expanded_insert(inserted.n, allocation);
    }
    reply_int(op.sink(), list.entries());
}

void cmd_lrem(Shard& shard, Op& op) {
    int64_t requested = 0;
    if (!parse_i64(op.arg(2), requested)) { reply_integer_error(op); return; }
    if (requested == std::numeric_limits<int64_t>::min()) {
        reply_non_min_i64(op);
        return;
    }

    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) { reply_int(op.sink(), 0); return; }
    if (!obj_type_check(object, Type::List, op.sink())) return;
    ListVal& list = *list_value(object);
    ObjectSizeTracker size_tracker(shard.store(), object);

    uint32_t matches = 0;
    for (ListCursor cur = ListCursor::edge(list, false); cur.valid(); cur.next()) {
        Compact::Entry entry;
        if (cur.get(entry) && entry.value == op.arg(3)) matches++;
    }
    const uint64_t limit = requested < 0 ? static_cast<uint64_t>(-requested)
                                         : static_cast<uint64_t>(requested);
    const uint32_t remove_count = requested == 0
        ? matches : static_cast<uint32_t>(std::min<uint64_t>(matches, limit));
    if (!remove_count) { reply_int(op.sink(), 0); return; }
    if (remove_count == list.entries()) {
        reply_int(op.sink(), remove_count);
        size_tracker.finish();
        shard.store().erase(op.hash, op.key());
        return;
    }

    const bool from_tail = requested < 0;
    const uint32_t first_removed_match = from_tail ? matches - remove_count + 1 : 1;
    uint32_t seen_matches = 0;
    uint64_t removed_payload = 0;
    Compact compact;
    ListVal staging;
    for (ListCursor cur = ListCursor::edge(list, false); cur.valid(); cur.next()) {
        Compact::Entry entry;
        if (!cur.get(entry)) { reply_oom(op); return; }
        bool remove = false;
        if (entry.value == op.arg(3)) {
            seen_matches++;
            remove = from_tail ? seen_matches >= first_removed_match
                               : seen_matches <= remove_count;
        }
        if (remove) {
            removed_payload += entry.value.n;
        } else {
            const bool ok = list.encoding() == CollectionEncoding::Compact
                ? compact.append(entry.value) : expanded_push(staging, entry.value, false);
            if (!ok) { reply_oom(op); return; }
        }
    }

    if (list.encoding() == CollectionEncoding::Compact) {
        list.replace_compact(std::move(compact));
    } else {
        adopt_nodes(list, staging);
        list.note_expanded_delete_many(remove_count, removed_payload,
                                       list.node_allocation_bytes);
    }
    reply_int(op.sink(), remove_count);
}

void cmd_ltrim(Shard& shard, Op& op) {
    int64_t start = 0, stop = 0;
    if (!parse_i64(op.arg(2), start) || !parse_i64(op.arg(3), stop)) {
        reply_integer_error(op);
        return;
    }
    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) { reply_ok(op.sink()); return; }
    if (!obj_type_check(object, Type::List, op.sink())) return;
    ListVal& list = *list_value(object);
    ObjectSizeTracker size_tracker(shard.store(), object);

    uint32_t first = 0, keep = 0;
    if (!normalize_range(start, stop, list.entries(), first, keep)) {
        size_tracker.finish();
        shard.store().erase(op.hash, op.key());
        reply_ok(op.sink());
        return;
    }
    if (first == 0 && keep == list.entries()) { reply_ok(op.sink()); return; }

    uint64_t retained_payload = 0;
    Compact compact;
    ListVal staging;
    ListCursor cur = ListCursor::seek(list, first);
    for (uint32_t i = 0; i < keep && cur.valid(); i++, cur.next()) {
        Compact::Entry entry;
        if (!cur.get(entry)) { reply_oom(op); return; }
        retained_payload += entry.value.n;
        const bool ok = list.encoding() == CollectionEncoding::Compact
            ? compact.append(entry.value) : expanded_push(staging, entry.value, false);
        if (!ok) { reply_oom(op); return; }
    }
    const uint32_t removed = list.entries() - keep;
    const uint64_t removed_payload = list.payload_bytes() - retained_payload;
    if (list.encoding() == CollectionEncoding::Compact) {
        list.replace_compact(std::move(compact));
    } else {
        adopt_nodes(list, staging);
        list.note_expanded_delete_many(removed, removed_payload, list.node_allocation_bytes);
    }
    reply_ok(op.sink());
}

struct LposOptions {
    int64_t rank = 1;
    int64_t count = -1;
    int64_t maxlen = 0;
    bool count_given = false;
};

bool parse_lpos_options(Op& op, LposOptions& options) {
    for (uint32_t i = 3; i < op.argc(); i++) {
        const Slice option = op.arg(i);
        const bool is_rank = option.eq_icase("rank");
        const bool is_count = option.eq_icase("count");
        const bool is_maxlen = option.eq_icase("maxlen");
        if (!is_rank && !is_count && !is_maxlen) {
            reply_syntax(op.sink());
            return false;
        }
        if (i + 1 >= op.argc()) { reply_syntax(op.sink()); return false; }
        int64_t value = 0;
        if (!parse_i64(op.arg(++i), value)) { reply_integer_error(op); return false; }
        if (is_rank) {
            if (value == std::numeric_limits<int64_t>::min()) {
                reply_non_min_i64(op);
                return false;
            }
            if (!value) {
                reply_err(op.sink(), "ERR RANK can't be zero: use 1 to start from the first match, 2 from the second ... or use negative to start from the end of the list");
                return false;
            }
            options.rank = value;
        } else if (is_count) {
            if (value < 0) { reply_err(op.sink(), "ERR COUNT can't be negative"); return false; }
            options.count = value;
            options.count_given = true;
        } else if (is_maxlen) {
            if (value < 0) { reply_err(op.sink(), "ERR MAXLEN can't be negative"); return false; }
            options.maxlen = value;
        }
    }
    return true;
}

void cmd_lpos(Shard& shard, Op& op) {
    LposOptions options;
    if (!parse_lpos_options(op, options)) return;

    KvObj* object = shard.store().find(op.hash, op.key());
    if (!object) {
        if (options.count_given) reply_array_header(op.sink(), 0);
        else reply_nil(op.sink());
        return;
    }
    if (!obj_type_check(object, Type::List, op.sink())) return;
    const ListVal& list = *list_value(object);
    const bool reverse = options.rank < 0;
    const uint64_t wanted_rank = reverse ? static_cast<uint64_t>(-options.rank)
                                         : static_cast<uint64_t>(options.rank);
    uint64_t scanned = 0;
    uint64_t matches = 0;

    if (!options.count_given) {
        for (ListCursor cur = ListCursor::edge(list, reverse); cur.valid(); cur.next()) {
            if (options.maxlen && scanned >= static_cast<uint64_t>(options.maxlen)) break;
            scanned++;
            Compact::Entry entry;
            if (cur.get(entry) && entry.value == op.arg(2) && ++matches >= wanted_rank) {
                reply_int(op.sink(), cur.position());
                return;
            }
        }
        reply_nil(op.sink());
        return;
    }

    std::vector<uint32_t> positions;
    for (ListCursor cur = ListCursor::edge(list, reverse); cur.valid(); cur.next()) {
        if (options.maxlen && scanned >= static_cast<uint64_t>(options.maxlen)) break;
        scanned++;
        Compact::Entry entry;
        if (!cur.get(entry) || !(entry.value == op.arg(2))) continue;
        matches++;
        if (matches < wanted_rank) continue;
        try {
            positions.push_back(cur.position());
        } catch (const std::bad_alloc&) {
            reply_oom(op);
            return;
        }
        if (options.count && positions.size() >= static_cast<uint64_t>(options.count)) break;
    }
    reply_array_header(op.sink(), positions.size());
    for (uint32_t position : positions) reply_int(op.sink(), position);
}

static const CommandSpec kTable[] = {
    // name       min max flags               handler       first last step
    {"LPUSH",      3, -1, CmdFlags::Write | CmdFlags::DenyOom,    cmd_lpush,      1,  1,  1},
    {"RPUSH",      3, -1, CmdFlags::Write | CmdFlags::DenyOom,    cmd_rpush,      1,  1,  1},
    {"LPUSHX",     3, -1, CmdFlags::Write | CmdFlags::DenyOom,    cmd_lpushx,     1,  1,  1},
    {"RPUSHX",     3, -1, CmdFlags::Write | CmdFlags::DenyOom,    cmd_rpushx,     1,  1,  1},
    {"LPOP",       2,  3, CmdFlags::Write,    cmd_lpop,       1,  1,  1},
    {"RPOP",       2,  3, CmdFlags::Write,    cmd_rpop,       1,  1,  1},
    {"LLEN",       2,  2, CmdFlags::Readonly, cmd_llen,       1,  1,  1},
    {"LRANGE",     4,  4, CmdFlags::Readonly, cmd_lrange,     1,  1,  1},
    {"LINDEX",     3,  3, CmdFlags::Readonly, cmd_lindex,     1,  1,  1},
    {"LSET",       4,  4, CmdFlags::Write | CmdFlags::DenyOom,    cmd_lset,       1,  1,  1},
    {"LINSERT",    5,  5, CmdFlags::Write | CmdFlags::DenyOom,    cmd_linsert,    1,  1,  1},
    {"LREM",       4,  4, CmdFlags::Write,    cmd_lrem,       1,  1,  1},
    {"LTRIM",      4,  4, CmdFlags::Write,    cmd_ltrim,      1,  1,  1},
    {"LPOS",       3, -1, CmdFlags::Readonly, cmd_lpos,       1,  1,  1},
};

}  // namespace


namespace {

// Logical list payload: per element [u32 len][bytes], front to back, encoding byte 0.  ListCursor
// resumes the walk at lane[0] in O(min(i, n-i)) instead of a front rescan per chunk.
SnapshotHookStatus list_snapshot_begin(const KvObj& object, SnapshotSaveCursor& cursor,
                                       uint8_t& encoding) {
    if (static_cast<Type>(object.type) != Type::List) return SnapshotHookStatus::Corrupt;
    cursor = {};
    cursor.object = &object;
    encoding = 0;
    const ListVal& list = *list_value(const_cast<KvObj*>(&object));
    cursor.total = 4ull * list.entries() + list.payload_bytes();
    return SnapshotHookStatus::Ok;
}

SnapshotHookStatus list_snapshot_read(SnapshotSaveCursor& cursor, uint8_t* destination,
                                      size_t capacity, size_t& written) {
    written = 0;
    if (!cursor.object) return SnapshotHookStatus::Corrupt;
    const ListVal& list = *list_value(const_cast<KvObj*>(cursor.object));
    SnapshotElementEmitter e{destination, capacity};
    uint64_t idx = cursor.lane[0];
    bool stopped = false;
    for (ListCursor cur = ListCursor::seek(list, static_cast<uint32_t>(idx)); cur.valid();
         cur.next(), idx++) {
        Compact::Entry entry;
        if (!cur.get(entry)) return SnapshotHookStatus::Corrupt;
        e.pos = 0;
        e.resume = idx == cursor.lane[0] ? cursor.lane[1] : 0;
        if (!(e.put_u32(entry.value.n) && e.put(entry.value.p, entry.value.n))) {
            cursor.lane[0] = idx;
            cursor.lane[1] = e.pos;
            stopped = true;
            break;
        }
    }
    if (!stopped) { cursor.lane[0] = idx; cursor.lane[1] = 0; }
    cursor.offset += e.out;
    written = e.out;
    return SnapshotHookStatus::Ok;
}

SnapshotHookStatus list_snapshot_load(Slice key, uint8_t encoding, int64_t expire_at_ms,
                                      Slice payload, const TypeLimits& limits, KvObj*& result) {
    result = nullptr;
    if (encoding != 0) return SnapshotHookStatus::Corrupt;
    auto* list = new (std::nothrow) ListVal;
    if (!list) return SnapshotHookStatus::Oom;
    // First pass: count and validate, so the compact-vs-deque decision mirrors a fresh RPUSH.
    const uint8_t* p = reinterpret_cast<const uint8_t*>(payload.p);
    uint64_t left = payload.n, count = 0, bytes = 0;
    while (left) {
        if (left < 4) { delete list; return SnapshotHookStatus::Corrupt; }
        const uint32_t len = snapshot_get_u32(p);
        if (left - 4 < len) { delete list; return SnapshotHookStatus::Corrupt; }
        count++; bytes += len;
        p += 4ull + len; left -= 4ull + len;
    }
    const bool compact = list->list_fits(limits.list, static_cast<uint32_t>(count), bytes);
    p = reinterpret_cast<const uint8_t*>(payload.p);
    left = payload.n;
    while (left) {
        const uint32_t len = snapshot_get_u32(p);
        const Slice value(reinterpret_cast<const char*>(p) + 4, len);
        p += 4ull + len; left -= 4ull + len;
        const bool ok = compact ? list->append(value) : expanded_push(*list, value, false);
        if (!ok) { delete list; return SnapshotHookStatus::Oom; }
    }
    if (!compact) {
        const uint64_t allocation = list->node_allocation_bytes;
        list->promote(CollectionEncoding::Deque, allocation);
        p = reinterpret_cast<const uint8_t*>(payload.p);
        left = payload.n;
        while (left) {
            const uint32_t len = snapshot_get_u32(p);
            list->note_expanded_insert(len, allocation);
            p += 4ull + len; left -= 4ull + len;
        }
    }
    result = kvobj_new_list(key, list, expire_at_ms);
    if (!result) { delete list; return SnapshotHookStatus::Oom; }
    return SnapshotHookStatus::Ok;
}

}  // namespace

SnapshotTypeHooks list_snapshot_hooks() {
    return {list_snapshot_begin, list_snapshot_read, list_snapshot_load};
}

CommandTable list_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
