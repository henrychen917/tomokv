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
// back-length: the lanes emit forward ranges, and paying an extra suffix on every element would
// buy machinery they do not need. Cursor offsets are invalidated by every mutation.
class Compact {
public:
    struct Entry {
        Slice    value;
        uint32_t offset = 0;
        uint32_t span   = 0;   // varint + payload
    };

    class Iterator {
    public:
        Iterator() = default;
        Entry operator*() const { Entry e; owner_->decode(offset_, e); return e; }
        Iterator& operator++() {
            Entry e;
            if (owner_->decode(offset_, e)) offset_ += e.span;
            return *this;
        }
        bool operator==(const Iterator& rhs) const {
            return owner_ == rhs.owner_ && offset_ == rhs.offset_;
        }
        bool operator!=(const Iterator& rhs) const { return !(*this == rhs); }

    private:
        friend class Compact;
        Iterator(const Compact* owner, uint32_t offset) : owner_(owner), offset_(offset) {}
        const Compact* owner_ = nullptr;
        uint32_t       offset_ = 0;
    };

    uint32_t size()          const { return entries_; }
    uint64_t payload_bytes() const { return payload_bytes_; }
    size_t   encoded_bytes() const { return data_.size(); }
    size_t   capacity_bytes() const { return data_.capacity(); }
    bool     empty()         const { return entries_ == 0; }
    const uint8_t* data()    const { return data_.data(); }

    Iterator begin() const { return Iterator(this, 0); }
    Iterator end()   const { return Iterator(this, static_cast<uint32_t>(data_.size())); }

    bool first(Entry& out) const { return decode(0, out); }
    bool next(const Entry& cur, Entry& out) const {
        const uint64_t off = static_cast<uint64_t>(cur.offset) + cur.span;
        if (off > data_.size()) return false;
        return decode(static_cast<uint32_t>(off), out);
    }

    bool append(Slice value) {
        if (entries_ == std::numeric_limits<uint32_t>::max()) return false;
        const uint32_t hdr = varint_size(value.n);
        const size_t old = data_.size();
        if (old > std::numeric_limits<uint32_t>::max() - hdr - value.n) return false;
        try {
            data_.resize(old + hdr + value.n);
        } catch (const std::bad_alloc&) {
            return false;
        }
        encode_varint(data_.data() + old, value.n);
        if (value.n) std::memcpy(data_.data() + old + hdr, value.p, value.n);
        entries_++;
        payload_bytes_ += value.n;
        return true;
    }

    bool replace(const Entry& old_entry, Slice value) {
        Entry checked;
        if (!decode(old_entry.offset, checked) || checked.span != old_entry.span) return false;

        const uint32_t hdr = varint_size(value.n);
        const size_t new_span = static_cast<size_t>(hdr) + value.n;
        const size_t old_span = checked.span;
        const size_t old_size = data_.size();
        const size_t tail = old_size - checked.offset - old_span;
        if (new_span > old_span) {
            const size_t grow = new_span - old_span;
            if (old_size > std::numeric_limits<uint32_t>::max() - grow) return false;
            try {
                data_.resize(old_size + grow);
            } catch (const std::bad_alloc&) {
                return false;
            }
        }

        uint8_t* base = data_.data();
        if (new_span != old_span) {
            std::memmove(base + checked.offset + new_span,
                         base + checked.offset + old_span, tail);
        }
        encode_varint(base + checked.offset, value.n);
        if (value.n) std::memcpy(base + checked.offset + hdr, value.p, value.n);
        if (new_span < old_span) data_.resize(old_size - (old_span - new_span));
        payload_bytes_ = payload_bytes_ - checked.value.n + value.n;
        return true;
    }

    bool erase(const Entry& entry) {
        Entry checked;
        if (!decode(entry.offset, checked) || checked.span != entry.span) return false;
        const size_t tail = data_.size() - checked.offset - checked.span;
        std::memmove(data_.data() + checked.offset,
                     data_.data() + checked.offset + checked.span, tail);
        data_.resize(data_.size() - checked.span);
        entries_--;
        payload_bytes_ -= checked.value.n;
        return true;
    }

    void clear() {
        data_.clear();
        entries_ = 0;
        payload_bytes_ = 0;
    }

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

    bool decode(uint32_t offset, Entry& out) const {
        if (offset >= data_.size()) return false;
        uint32_t value = 0;
        uint32_t shift = 0;
        uint32_t pos = offset;
        for (uint32_t n = 0; n < 5 && pos < data_.size(); n++, pos++) {
            const uint8_t byte = data_[pos];
            if (shift == 28 && (byte & 0xf0)) return false;
            value |= static_cast<uint32_t>(byte & 0x7f) << shift;
            if (!(byte & 0x80)) {
                const uint32_t hdr = pos - offset + 1;
                const uint64_t end = static_cast<uint64_t>(offset) + hdr + value;
                if (end > data_.size()) return false;
                out = Entry{Slice(reinterpret_cast<const char*>(data_.data() + offset + hdr), value),
                            offset, hdr + value};
                return true;
            }
            shift += 7;
        }
        return false;
    }

    std::vector<uint8_t> data_;
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
    bool replace(const Compact::Entry& entry, Slice value) {
        return is_compact() && compact_.replace(entry, value);
    }
    bool erase(const Compact::Entry& entry) { return is_compact() && compact_.erase(entry); }

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

    // Hash Compact entries each hold one encoded field/value pair. The outer Compact entry count
    // is therefore already the logical hash length, but its payload includes the pair's small
    // field-length prefix. Let that lane install its maintained logical payload total without
    // teaching the type-independent container about a hash-specific inner format.
    void promote(CollectionEncoding to, uint64_t expanded_allocation_bytes,
                 uint32_t logical_entries, uint64_t logical_payload_bytes) {
        expanded_entries_ = logical_entries;
        expanded_payload_bytes_ = logical_payload_bytes;
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
    void note_expanded_replace(uint32_t old_bytes, uint32_t new_bytes,
                               uint64_t allocation_bytes) {
        expanded_payload_bytes_ = expanded_payload_bytes_ - old_bytes + new_bytes;
        expanded_allocation_bytes_ = allocation_bytes;
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
class HashFieldMap;

struct HashVal : CompactValue {
    explicit HashVal(uint64_t seed = 0);
    ~HashVal();
    HashVal(const HashVal&) = delete;
    HashVal& operator=(const HashVal&) = delete;

    uint32_t field_count() const { return entries(); }
    uint64_t random_bounded(uint64_t bound);

    // Exact field+value bytes for the packed-pair representation. Compact::payload_bytes() also
    // includes each pair's inner field-length prefix, so it cannot serve as the hash logical total.
    uint64_t compact_payload_bytes = 0;
    uint64_t random_state = 0;
    HashFieldMap* fields = nullptr;
};
struct ListVal : CompactValue {};
struct SetVal  : CompactValue {};
struct ZsetVal : CompactValue {};

}  // namespace tomo
