// typeval.h — collection values and their compact encoding.
//
// A collection is one shard-owned object. KvObj holds only its pointer and type tag; the concrete
// per-type struct below owns the representation. There is deliberately no base-class vtable: the
// outer Type tag is already present, so destruction and accounting dispatch on that one byte.
#pragma once
#include <cstdint>
#include <cstring>
#include <limits>
#include <new>
#include <string>
#include <utility>
#include <vector>
#include "../base/slice.h"

namespace tomo {

// Redis-compatible starting points. Lists are the one intentional translation: Redis/Valkey's
// default -2 is an 8 KiB listpack NODE budget rather than an element-length limit. A single Compact
// is our whole small list, so list.max_value is its aggregate payload budget and max_entries is
// unlimited. The list lane must use CompactValue::list_fits(), not compact_fits().
struct CompactLimit {
    uint32_t max_entries;
    uint32_t max_value;
};

struct TypeLimits {
    CompactLimit hash{512, 64};
    CompactLimit list{std::numeric_limits<uint32_t>::max(), 8 * 1024};
    CompactLimit set {128, 64};
    CompactLimit zset{128, 64};
};

// [ULEB128 payload length][payload bytes], repeated to EOF. There is no container header and no
// back-length. The byte vector is a gap-at-the-ends buffer and offsets_ is a circular side index;
// together they let the list lane mutate either end in amortized O(1) without adding bytes to the
// wire/storage format. Interior mutations still move the affected suffix. Every mutation
// invalidates prior Entry slices and offsets.
class Compact {
public:
    struct Entry {
        Slice    value;
        uint32_t offset = 0;
        uint32_t span   = 0;   // varint + payload
        uint32_t index  = 0;
    };

    class Iterator {
    public:
        Iterator() = default;
        Entry operator*() const { Entry e; owner_->at(index_, e); return e; }
        Iterator& operator++() { index_++; return *this; }
        bool operator==(const Iterator& rhs) const {
            return owner_ == rhs.owner_ && index_ == rhs.index_;
        }
        bool operator!=(const Iterator& rhs) const { return !(*this == rhs); }

    private:
        friend class Compact;
        Iterator(const Compact* owner, uint32_t index) : owner_(owner), index_(index) {}
        const Compact* owner_ = nullptr;
        uint32_t       index_ = 0;
    };

    uint32_t size()          const { return entries_; }
    uint64_t payload_bytes() const { return payload_bytes_; }
    size_t   encoded_bytes() const { return end_ - begin_; }
    size_t   capacity_bytes() const {
        return data_.capacity() + offsets_.capacity() * sizeof(uint32_t);
    }
    bool     empty()         const { return entries_ == 0; }
    const uint8_t* data()    const { return data_.data() + begin_; }

    static uint32_t entry_encoded_size(uint32_t payload_size) {
        return varint_size(payload_size) + payload_size;
    }

    Iterator begin() const { return Iterator(this, 0); }
    Iterator end()   const { return Iterator(this, entries_); }

    bool at(uint32_t index, Entry& out) const {
        if (index >= entries_) return false;
        return decode(offset_at(index), index, out);
    }
    bool first(Entry& out) const { return at(0, out); }
    bool last(Entry& out) const { return entries_ && at(entries_ - 1, out); }
    bool next(const Entry& cur, Entry& out) const {
        return cur.index < entries_ && at(cur.index + 1, out);
    }

    bool append(Slice value) {
        if (entries_ == std::numeric_limits<uint32_t>::max()) return false;
        const uint32_t hdr = varint_size(value.n);
        const uint32_t span = hdr + value.n;
        if (!ensure_space(0, span) || !ensure_offset_space()) return false;
        encode_varint(data_.data() + end_, value.n);
        if (value.n) std::memcpy(data_.data() + end_ + hdr, value.p, value.n);
        offset_push_back(end_);
        end_ += span;
        entries_++;
        payload_bytes_ += value.n;
        return true;
    }

    bool prepend(Slice value) {
        if (entries_ == std::numeric_limits<uint32_t>::max()) return false;
        const uint32_t hdr = varint_size(value.n);
        const uint32_t span = hdr + value.n;
        if (!ensure_space(span, 0) || !ensure_offset_space()) return false;
        begin_ -= span;
        encode_varint(data_.data() + begin_, value.n);
        if (value.n) std::memcpy(data_.data() + begin_ + hdr, value.p, value.n);
        offset_push_front(begin_);
        entries_++;
        payload_bytes_ += value.n;
        return true;
    }

    // Insert at an entry boundary. Set's integer compact uses this to retain numeric order; the
    // offset is found with binary search over its fixed-width entries, so deciding where to insert
    // never rescans the collection. As with every Compact mutation, prior Entries are invalidated.
    bool insert(uint32_t offset, Slice value) {
        if (entries_ == std::numeric_limits<uint32_t>::max() || offset > data_.size()) return false;
        if (offset != data_.size()) {
            Entry boundary;
            if (!decode(offset, boundary)) return false;
        }
        const uint32_t hdr = varint_size(value.n);
        const size_t span = static_cast<size_t>(hdr) + value.n;
        const size_t old = data_.size();
        if (old > std::numeric_limits<uint32_t>::max() - span) return false;
        try {
            data_.resize(old + span);
        } catch (const std::bad_alloc&) {
            return false;
        }
        uint8_t* base = data_.data();
        std::memmove(base + offset + span, base + offset, old - offset);
        encode_varint(base + offset, value.n);
        if (value.n) std::memcpy(base + offset + hdr, value.p, value.n);
        entries_++;
        payload_bytes_ += value.n;
        return true;
    }

    bool replace(const Entry& old_entry, Slice value) {
        Entry checked;
        if (!at(old_entry.index, checked) || checked.offset != old_entry.offset ||
            checked.span != old_entry.span) return false;

        const uint32_t hdr = varint_size(value.n);
        const uint32_t new_span = hdr + value.n;
        const uint32_t old_span = checked.span;
        if (new_span > old_span) {
            if (!ensure_space(0, new_span - old_span)) return false;
            if (!at(old_entry.index, checked)) return false;  // ensure_space may relocate.
        }

        uint8_t* base = data_.data();
        const uint32_t tail = end_ - checked.offset - old_span;
        if (new_span != old_span) {
            std::memmove(base + checked.offset + new_span,
                         base + checked.offset + old_span, tail);
            const int64_t delta = static_cast<int64_t>(new_span) - old_span;
            for (uint32_t i = checked.index + 1; i < entries_; i++)
                offset_set(i, static_cast<uint32_t>(static_cast<int64_t>(offset_at(i)) + delta));
            end_ = static_cast<uint32_t>(static_cast<int64_t>(end_) + delta);
        }
        encode_varint(base + checked.offset, value.n);
        if (value.n) std::memcpy(base + checked.offset + hdr, value.p, value.n);
        payload_bytes_ = payload_bytes_ - checked.value.n + value.n;
        return true;
    }

    bool insert_before(const Entry& entry, Slice value) {
        return insert_at(entry.index, entry, value, false);
    }
    bool insert_after(const Entry& entry, Slice value) {
        return insert_at(entry.index + 1, entry, value, true);
    }

    bool erase(const Entry& entry) {
        Entry checked;
        if (!at(entry.index, checked) || checked.offset != entry.offset ||
            checked.span != entry.span) return false;
        const uint32_t tail = end_ - checked.offset - checked.span;
        std::memmove(data_.data() + checked.offset,
                     data_.data() + checked.offset + checked.span, tail);
        for (uint32_t i = checked.index + 1; i < entries_; i++)
            offset_set(i - 1, offset_at(i) - checked.span);
        end_ -= checked.span;
        entries_--;
        payload_bytes_ -= checked.value.n;
        return true;
    }

    bool pop_front(uint32_t* payload_size = nullptr) {
        Entry entry;
        if (!first(entry)) return false;
        if (payload_size) *payload_size = entry.value.n;
        begin_ += entry.span;
        offset_pop_front();
        entries_--;
        payload_bytes_ -= entry.value.n;
        if (!entries_) begin_ = end_;
        return true;
    }

    bool pop_back(uint32_t* payload_size = nullptr) {
        Entry entry;
        if (!last(entry)) return false;
        if (payload_size) *payload_size = entry.value.n;
        end_ = entry.offset;
        entries_--;
        payload_bytes_ -= entry.value.n;
        if (!entries_) begin_ = end_;
        return true;
    }

    void clear() {
        data_.clear();
        begin_ = end_ = 0;
        offset_head_ = 0;
        entries_ = 0;
        payload_bytes_ = 0;
    }

    bool at_offset(uint32_t offset, Entry& out) const { return decode(offset, out); }

private:
    static uint32_t varint_size(uint32_t value) {
        uint32_t n = 1;
        while (value >= 0x80) { value >>= 7; n++; }
        return n;
    }

    static void encode_varint(uint8_t* dst, uint32_t value) {
        while (value >= 0x80) {
            *dst++ = static_cast<uint8_t>((value & 0x7f) | 0x80);
            value >>= 7;
        }
        *dst = static_cast<uint8_t>(value);
    }

    uint32_t offset_slot(uint32_t index) const {
        return static_cast<uint32_t>((static_cast<uint64_t>(offset_head_) + index) % offsets_.size());
    }
    uint32_t offset_at(uint32_t index) const { return offsets_[offset_slot(index)]; }
    void offset_set(uint32_t index, uint32_t value) { offsets_[offset_slot(index)] = value; }

    bool ensure_offset_space() {
        if (entries_ < offsets_.size()) return true;
        uint64_t wanted = offsets_.empty() ? 8 : static_cast<uint64_t>(offsets_.size()) * 2;
        if (wanted <= entries_) wanted = static_cast<uint64_t>(entries_) + 1;
        if (wanted > std::numeric_limits<uint32_t>::max()) return false;
        std::vector<uint32_t> next_offsets;
        try {
            next_offsets.resize(static_cast<size_t>(wanted));
        } catch (const std::bad_alloc&) {
            return false;
        }
        for (uint32_t i = 0; i < entries_; i++) next_offsets[i] = offset_at(i);
        offsets_.swap(next_offsets);
        offset_head_ = 0;
        return true;
    }

    void offset_push_back(uint32_t value) { offset_set(entries_, value); }
    void offset_push_front(uint32_t value) {
        offset_head_ = offset_head_ ? offset_head_ - 1
                                    : static_cast<uint32_t>(offsets_.size() - 1);
        offsets_[offset_head_] = value;
    }
    void offset_pop_front() {
        offset_head_++;
        if (offset_head_ == offsets_.size()) offset_head_ = 0;
    }
    bool ensure_space(uint32_t front, uint32_t back) {
        if (front <= begin_ && static_cast<uint64_t>(end_) + back <= data_.size()) return true;
        const uint64_t active = end_ - begin_;
        const uint64_t required = active + front + back;
        if (required > std::numeric_limits<uint32_t>::max()) return false;
        uint64_t wanted = data_.size();
        if (wanted < required) {
            wanted = data_.empty() ? 64 : static_cast<uint64_t>(data_.size()) * 2;
            if (wanted < required) wanted = required;
        }
        if (wanted > std::numeric_limits<uint32_t>::max())
            wanted = std::numeric_limits<uint32_t>::max();

        uint64_t new_begin = (wanted - active) / 2;
        if (new_begin < front) new_begin = front;
        if (wanted - active - new_begin < back) new_begin = wanted - active - back;
        if (new_begin < front) return false;

        const int64_t delta = static_cast<int64_t>(new_begin) - begin_;
        if (wanted == data_.size()) {
            if (active) std::memmove(data_.data() + new_begin, data_.data() + begin_, active);
        } else {
            std::vector<uint8_t> next_data;
            try {
                next_data.resize(static_cast<size_t>(wanted));
            } catch (const std::bad_alloc&) {
                return false;
            }
            if (active) std::memcpy(next_data.data() + new_begin, data_.data() + begin_, active);
            data_.swap(next_data);
        }
        for (uint32_t i = 0; i < entries_; i++)
            offset_set(i, static_cast<uint32_t>(static_cast<int64_t>(offset_at(i)) + delta));
        begin_ = static_cast<uint32_t>(new_begin);
        end_ = static_cast<uint32_t>(new_begin + active);
        return true;
    }

    bool insert_at(uint32_t index, const Entry& old_entry, Slice value, bool after) {
        if (entries_ == std::numeric_limits<uint32_t>::max() || index > entries_) return false;
        Entry checked;
        if (!at(old_entry.index, checked) || checked.offset != old_entry.offset ||
            checked.span != old_entry.span) return false;
        const uint32_t span = entry_encoded_size(value.n);
        if (!ensure_space(0, span) || !ensure_offset_space()) return false;
        if (!at(old_entry.index, checked)) return false;
        const uint32_t pos = after ? checked.offset + checked.span : checked.offset;
        const uint32_t tail = end_ - pos;
        std::memmove(data_.data() + pos + span, data_.data() + pos, tail);
        for (uint32_t i = entries_; i > index; i--)
            offset_set(i, offset_at(i - 1) + span);
        offset_set(index, pos);
        end_ += span;
        const uint32_t hdr = varint_size(value.n);
        encode_varint(data_.data() + pos, value.n);
        if (value.n) std::memcpy(data_.data() + pos + hdr, value.p, value.n);
        entries_++;
        payload_bytes_ += value.n;
        return true;
    }

    bool decode(uint32_t offset, uint32_t index, Entry& out) const {
        if (offset < begin_ || offset >= end_) return false;
        uint32_t value = 0;
        uint32_t shift = 0;
        uint32_t pos = offset;
        for (uint32_t n = 0; n < 5 && pos < end_; n++, pos++) {
            const uint8_t byte = data_[pos];
            if (shift == 28 && (byte & 0xf0)) return false;
            value |= static_cast<uint32_t>(byte & 0x7f) << shift;
            if (!(byte & 0x80)) {
                const uint32_t hdr = pos - offset + 1;
                const uint64_t end = static_cast<uint64_t>(offset) + hdr + value;
                if (end > end_) return false;
                out = Entry{Slice(reinterpret_cast<const char*>(data_.data() + offset + hdr), value),
                            offset, hdr + value, index};
                return true;
            }
            shift += 7;
        }
        return false;
    }

    std::vector<uint8_t> data_;
    std::vector<uint32_t> offsets_;
    uint32_t              begin_ = 0;
    uint32_t              end_ = 0;
    uint32_t              offset_head_ = 0;
    uint32_t              entries_ = 0;
    uint64_t              payload_bytes_ = 0;
};

enum class CollectionEncoding : uint8_t {
    Compact   = 0,
    Hashtable = 1,
    Deque     = 2,
    Btree     = 3,
};

// Mutation funnels keep conversion inputs O(1). Promotion is one-way unless a lane explicitly
// proves a hysteretic demotion policy; after promotion, the lane updates the three expanded
// counters alongside its backing structure instead of inspecting that structure to make a choice.
class CompactValue {
public:
    CollectionEncoding encoding() const { return encoding_; }
    uint32_t entries() const {
        return encoding_ == CollectionEncoding::Compact ? compact_.size() : expanded_entries_;
    }
    uint64_t payload_bytes() const {
        return encoding_ == CollectionEncoding::Compact ? compact_.payload_bytes()
                                                        : expanded_payload_bytes_;
    }
    uint64_t allocation_bytes() const {
        return sizeof(*this) + compact_.capacity_bytes() + expanded_allocation_bytes_;
    }

    const Compact& compact() const { return compact_; }
    Compact::Iterator begin() const { return compact_.begin(); }
    Compact::Iterator end()   const { return compact_.end(); }

    bool append(Slice value) { return is_compact() && compact_.append(value); }
    bool insert(uint32_t offset, Slice value) {
        return is_compact() && compact_.insert(offset, value);
    }
    bool prepend(Slice value) { return is_compact() && compact_.prepend(value); }
    bool replace(const Compact::Entry& entry, Slice value) {
        return is_compact() && compact_.replace(entry, value);
    }
    bool insert_before(const Compact::Entry& entry, Slice value) {
        return is_compact() && compact_.insert_before(entry, value);
    }
    bool insert_after(const Compact::Entry& entry, Slice value) {
        return is_compact() && compact_.insert_after(entry, value);
    }
    bool erase(const Compact::Entry& entry) { return is_compact() && compact_.erase(entry); }
    bool pop_front(uint32_t* payload_size = nullptr) {
        return is_compact() && compact_.pop_front(payload_size);
    }
    bool pop_back(uint32_t* payload_size = nullptr) {
        return is_compact() && compact_.pop_back(payload_size);
    }
    bool replace_compact(Compact&& replacement) {
        if (!is_compact()) return false;
        compact_ = std::move(replacement);
        return true;
    }

    bool compact_fits(const CompactLimit& limit, uint32_t resulting_entries,
                      uint32_t incoming_max_value) const {
        return is_compact() && resulting_entries <= limit.max_entries &&
               incoming_max_value <= limit.max_value;
    }
    bool list_fits(const CompactLimit& limit, uint32_t resulting_entries,
                   uint64_t resulting_payload_bytes) const {
        return is_compact() && resulting_entries <= limit.max_entries &&
               resulting_payload_bytes <= limit.max_value;
    }

    void promote(CollectionEncoding to, uint64_t expanded_allocation_bytes) {
        // Call only AFTER the expanded structure owns copies of every compact entry.
        expanded_entries_ = compact_.size();
        expanded_payload_bytes_ = compact_.payload_bytes();
        expanded_allocation_bytes_ = expanded_allocation_bytes;
        compact_.clear();
        encoding_ = to;
    }

    void note_expanded_insert(uint32_t payload_bytes, uint64_t allocation_bytes) {
        expanded_entries_++;
        expanded_payload_bytes_ += payload_bytes;
        expanded_allocation_bytes_ = allocation_bytes;
    }
    void note_expanded_delete(uint32_t payload_bytes, uint64_t allocation_bytes) {
        expanded_entries_--;
        expanded_payload_bytes_ -= payload_bytes;
        expanded_allocation_bytes_ = allocation_bytes;
    }
    void note_expanded_delete_many(uint32_t entries, uint64_t payload_bytes,
                                   uint64_t allocation_bytes) {
        expanded_entries_ -= entries;
        expanded_payload_bytes_ -= payload_bytes;
        expanded_allocation_bytes_ = allocation_bytes;
    }
    void note_expanded_replace(uint32_t old_bytes, uint32_t new_bytes,
                               uint64_t allocation_bytes) {
        expanded_payload_bytes_ = expanded_payload_bytes_ - old_bytes + new_bytes;
        expanded_allocation_bytes_ = allocation_bytes;
    }
    void note_expanded_allocation(uint64_t allocation_bytes) {
        expanded_allocation_bytes_ = allocation_bytes;
    }

protected:
    // Set's sorted integer compact is binary (2/4/8-byte payloads), so its logical member byte
    // total differs from Compact::payload_bytes(). These two hooks keep the common representation
    // and promotion ordering while allowing that one type-specific distinction.
    void replace_compact(Compact&& replacement) {
        if (is_compact()) compact_ = std::move(replacement);
    }
    void promote_with_payload(CollectionEncoding to, uint64_t expanded_allocation_bytes,
                              uint64_t logical_payload_bytes) {
        expanded_entries_ = compact_.size();
        expanded_payload_bytes_ = logical_payload_bytes;
        expanded_allocation_bytes_ = expanded_allocation_bytes;
        compact_.clear();
        encoding_ = to;
    }

private:
    bool is_compact() const { return encoding_ == CollectionEncoding::Compact; }

    CollectionEncoding encoding_ = CollectionEncoding::Compact;
    Compact             compact_;
    uint32_t            expanded_entries_ = 0;
    uint64_t            expanded_payload_bytes_ = 0;
    uint64_t            expanded_allocation_bytes_ = 0;
};

// Separate concrete types make the outer destructor switch exhaustive and give each follow-up lane
// a stable place to add its expanded backing structure without changing KvObj or Op.
struct HashVal : CompactValue {};
struct ListNode {
    ListNode* prev = nullptr;
    ListNode* next = nullptr;
    Compact   values;
};

struct ListVal : CompactValue {
    ListVal() = default;
    ListVal(const ListVal&) = delete;
    ListVal& operator=(const ListVal&) = delete;
    ~ListVal() {
        ListNode* node = head;
        while (node) {
            ListNode* next = node->next;
            delete node;
            node = next;
        }
    }

    ListNode* head = nullptr;
    ListNode* tail = nullptr;
    uint64_t  node_allocation_bytes = 0;
};


// Expanded SET backing. Membership uses open addressing; live_slots_ is a dense side index used
// only for O(1) uniform random selection/removal. Slots never move on erase, which also makes a
// cursor stable between table rebuilds. A rebuild increments generation_ so SSCAN can restart and
// preserve its full-iteration guarantee (duplicates remain permitted, as in Redis).
class SetMemberTable {
public:
    enum class InsertResult : uint8_t { Inserted, Exists, Oom };
    static constexpr uint32_t npos = std::numeric_limits<uint32_t>::max();

    SetMemberTable() = default;
    SetMemberTable(const SetMemberTable&) = delete;
    SetMemberTable& operator=(const SetMemberTable&) = delete;
    SetMemberTable(SetMemberTable&&) noexcept = default;
    SetMemberTable& operator=(SetMemberTable&&) noexcept = default;

    uint32_t size() const { return live_; }
    uint32_t slot_count() const { return static_cast<uint32_t>(slots_.size()); }
    uint32_t generation() const { return generation_; }
    uint64_t allocation_bytes() const;

    bool reserve(uint32_t entries);
    uint32_t find(Slice value, uint64_t hash) const;
    InsertResult insert(Slice value, uint64_t hash);
    bool erase(Slice value, uint64_t hash, uint32_t& erased_bytes);
    bool erase_at(uint32_t slot, uint32_t& erased_bytes);
    uint32_t random_slot(uint64_t random) const;
    uint32_t slot_for_dense(uint32_t dense_index) const;
    bool live_at(uint32_t slot) const;
    Slice value_at(uint32_t slot) const;

private:
    enum : uint8_t { Empty = 0, Live = 1, Tomb = 2 };
    struct Slot {
        std::string value;
        uint64_t hash = 0;
        uint32_t dense_pos = 0;
        uint8_t state = Empty;
    };

    static uint32_t capacity_for(uint32_t entries);
    bool ensure_insert_capacity();
    bool rehash(uint32_t capacity);
    uint32_t find_insert_slot(Slice value, uint64_t hash, bool& exists) const;

    std::vector<Slot> slots_;
    std::vector<uint32_t> live_slots_;
    uint32_t live_ = 0;
    uint32_t tombs_ = 0;
    uint32_t generation_ = 1;
    uint64_t string_capacity_bytes_ = 0;
};

inline uint64_t SetMemberTable::allocation_bytes() const {
    return static_cast<uint64_t>(slots_.capacity()) * sizeof(Slot) +
           static_cast<uint64_t>(live_slots_.capacity()) * sizeof(uint32_t) +
           string_capacity_bytes_;
}

enum class SetSmallEncoding : uint8_t { Integer = 0, Generic = 1 };

struct SetVal : CompactValue {
    size_t allocation_bytes() const {
        return CompactValue::allocation_bytes() +
               static_cast<uint64_t>(offsets.capacity()) * sizeof(uint32_t);
    }
    void adopt_compact(Compact&& replacement) { replace_compact(std::move(replacement)); }
    void finish_table_promotion(uint64_t logical_payload_bytes) {
        std::vector<uint32_t>().swap(offsets);
        promote_with_payload(CollectionEncoding::Hashtable, table.allocation_bytes(),
                             logical_payload_bytes);
    }

    SetSmallEncoding small_encoding = SetSmallEncoding::Integer;
    uint8_t int_width = 2;
    uint32_t max_member_bytes = 0;  // conservative high-water mark; never requires a delete scan
    std::vector<uint32_t> offsets;  // generic Compact entry starts; integer starts are fixed-width
    SetMemberTable table;
};
struct ZsetVal : CompactValue {};

}  // namespace tomo
