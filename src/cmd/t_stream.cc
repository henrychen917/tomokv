// t_stream.cc -- Redis-compatible phase-1 streams.
//
// Small streams are a header record plus packed records in the KvObj tail. Expanded streams are
// Compact macro nodes indexed by a sorted {base ID,node} vector. There is one record codec and one
// range emitter for XRANGE/XREVRANGE/XREAD; neither representation leaks into command semantics.
#include "command.h"
#include "blocking.h"
#include "notify.h"
#include "t_stream.h"
#include "../core/shard.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include "../snapshot/format.h"
#include "../store/kvobj.h"

#include <algorithm>
#include <charconv>
#include <cstdint>
#include <cstring>
#include <limits>
#include <new>
#include <string>
#include <utility>
#include <vector>

namespace tomo {

void reply_maxmemory_oom(Op& op);

namespace {

constexpr uint8_t kDeleted = 1u << 0;
constexpr uint8_t kSameFields = 1u << 1;
constexpr uint32_t kHeaderBytes = sizeof(StreamHeader);
constexpr uint32_t kMaxIdText = 128;

int id_compare(const StreamID& a, const StreamID& b) {
    if (a.ms != b.ms) return a.ms < b.ms ? -1 : 1;
    if (a.seq != b.seq) return a.seq < b.seq ? -1 : 1;
    return 0;
}
bool id_equal(const StreamID& a, const StreamID& b) { return id_compare(a, b) == 0; }
bool id_zero(const StreamID& id) { return id.ms == 0 && id.seq == 0; }

bool id_increment(StreamID& id) {
    if (id.seq != UINT64_MAX) { id.seq++; return true; }
    if (id.ms == UINT64_MAX) return false;
    id.ms++; id.seq = 0; return true;
}

bool id_decrement(StreamID& id) {
    if (id.seq) { id.seq--; return true; }
    if (!id.ms) return false;
    id.ms--; id.seq = UINT64_MAX; return true;
}

bool parse_u64_exact(Slice input, uint64_t& value) {
    if (!input.n) return false;
    const char* end = input.p + input.n;
    const auto result = std::from_chars(input.p, end, value);
    return result.ec == std::errc{} && result.ptr == end;
}

bool parse_id_numeric(Slice input, StreamID& id, uint64_t missing_seq,
                      bool allow_sentinels) {
    if (!input.n || input.n > kMaxIdText) return false;
    if (allow_sentinels && input.n == 1 && input.p[0] == '-') {
        id = {}; return true;
    }
    if (allow_sentinels && input.n == 1 && input.p[0] == '+') {
        id = {UINT64_MAX, UINT64_MAX}; return true;
    }
    const char* dash = static_cast<const char*>(std::memchr(input.p, '-', input.n));
    if (!dash) {
        if (!parse_u64_exact(input, id.ms)) return false;
        id.seq = missing_seq;
        return true;
    }
    const uint32_t first = static_cast<uint32_t>(dash - input.p);
    if (!first || first + 1 >= input.n ||
        std::memchr(dash + 1, '-', input.n - first - 1)) return false;
    return parse_u64_exact(Slice(input.p, first), id.ms) &&
           parse_u64_exact(Slice(dash + 1, input.n - first - 1), id.seq);
}

void reply_invalid_stream_id(Op& op) {
    reply_err(op.sink(), "ERR Invalid stream ID specified as stream command argument");
}

template <typename Buf>
void reply_id_to(Buf& sink, const StreamID& id) {
    char text[41];
    uint32_t length = u64_to_dec(text, id.ms);
    text[length++] = '-';
    length += u64_to_dec(text + length, id.seq);
    reply_bulk(sink, Slice(text, length));
}

void reply_id(Op& op, const StreamID& id) {
    auto sink = op.sink();
    reply_id_to(sink, id);
}

void encode_uleb(std::string& out, uint64_t value) {
    while (value >= 0x80) {
        out.push_back(static_cast<char>((value & 0x7f) | 0x80)); value >>= 7;
    }
    out.push_back(static_cast<char>(value));
}

bool decode_uleb(Slice input, uint32_t& pos, uint64_t& value) {
    value = 0;
    for (uint32_t count = 0, shift = 0; count < 10 && pos < input.n; count++, shift += 7) {
        const uint8_t byte = static_cast<uint8_t>(input.p[pos++]);
        if (shift == 63 && (byte & 0xfe)) return false;
        value |= static_cast<uint64_t>(byte & 0x7f) << shift;
        if (!(byte & 0x80)) return true;
    }
    return false;
}

struct RecordView {
    StreamID id{};
    uint8_t flags = 0;
    uint32_t flags_offset = 0;
    std::vector<Slice> fields;
    std::vector<Slice> values;
};

struct OwnedRecord {
    StreamID id{};
    bool deleted = false;
    std::vector<std::string> fields;
    std::vector<std::string> values;
};

bool decode_record(Slice payload, const StreamID& previous_id,
                   const std::vector<Slice>& previous_fields, RecordView& out) {
    uint32_t pos = 0;
    uint64_t ms_delta = 0, seq_delta = 0, nfields = 0;
    if (!decode_uleb(payload, pos, ms_delta) || !decode_uleb(payload, pos, seq_delta) ||
        pos >= payload.n) return false;
    if (ms_delta > UINT64_MAX - previous_id.ms) return false;
    out.id.ms = previous_id.ms + ms_delta;
    if (ms_delta == 0) {
        if (seq_delta > UINT64_MAX - previous_id.seq) return false;
        out.id.seq = previous_id.seq + seq_delta;
    } else {
        out.id.seq = seq_delta;
    }
    out.flags_offset = pos;
    out.flags = static_cast<uint8_t>(payload.p[pos++]);
    if (out.flags & ~(kDeleted | kSameFields)) return false;
    if (!decode_uleb(payload, pos, nfields) || nfields > UINT32_MAX) return false;
    out.fields.clear(); out.values.clear();
    try {
        out.fields.reserve(static_cast<size_t>(nfields));
        out.values.reserve(static_cast<size_t>(nfields));
        if (out.flags & kSameFields) {
            if (previous_fields.size() != nfields) return false;
            out.fields.assign(previous_fields.begin(), previous_fields.end());
        } else {
            for (uint64_t i = 0; i < nfields; i++) {
                uint64_t len = 0;
                if (!decode_uleb(payload, pos, len) || len > payload.n - pos) return false;
                out.fields.push_back(Slice(payload.p + pos, static_cast<uint32_t>(len)));
                pos += static_cast<uint32_t>(len);
            }
        }
        for (uint64_t i = 0; i < nfields; i++) {
            uint64_t len = 0;
            if (!decode_uleb(payload, pos, len) || len > payload.n - pos) return false;
            out.values.push_back(Slice(payload.p + pos, static_cast<uint32_t>(len)));
            pos += static_cast<uint32_t>(len);
        }
    } catch (const std::bad_alloc&) {
        return false;
    }
    return pos == payload.n;
}

bool fields_equal(const std::vector<std::string>& prior, Op& op, uint32_t first_field) {
    const uint32_t count = (op.argc() - first_field) / 2;
    if (prior.size() != count) return false;
    for (uint32_t i = 0; i < count; i++)
        if (!(Slice(prior[i].data(), static_cast<uint32_t>(prior[i].size())) ==
              op.arg(first_field + i * 2))) return false;
    return true;
}

bool encode_record_from_op(const StreamID& id, const StreamID& previous_id,
                           Op& op, uint32_t first_field,
                           const std::vector<std::string>& previous_fields,
                           bool first_in_node, std::string& out) {
    out.clear();
    const uint64_t ms_delta = id.ms - previous_id.ms;
    const uint64_t seq_delta = ms_delta ? id.seq : id.seq - previous_id.seq;
    encode_uleb(out, ms_delta); encode_uleb(out, seq_delta);
    const bool same = !first_in_node && fields_equal(previous_fields, op, first_field);
    out.push_back(static_cast<char>(same ? kSameFields : 0));
    const uint32_t nfields = (op.argc() - first_field) / 2;
    encode_uleb(out, nfields);
    if (!same) for (uint32_t i = 0; i < nfields; i++) {
        const Slice field = op.arg(first_field + i * 2);
        encode_uleb(out, field.n); out.append(field.p, field.n);
    }
    for (uint32_t i = 0; i < nfields; i++) {
        const Slice value = op.arg(first_field + i * 2 + 1);
        encode_uleb(out, value.n); out.append(value.p, value.n);
    }
    return out.size() <= UINT32_MAX;
}

bool encode_owned_record(const OwnedRecord& record, const StreamID& previous_id,
                         const std::vector<std::string>& previous_fields, bool first_in_node,
                         std::string& out) {
    out.clear();
    const uint64_t ms_delta = record.id.ms - previous_id.ms;
    const uint64_t seq_delta = ms_delta ? record.id.seq : record.id.seq - previous_id.seq;
    encode_uleb(out, ms_delta); encode_uleb(out, seq_delta);
    const bool same = !first_in_node && record.fields == previous_fields;
    out.push_back(static_cast<char>((record.deleted ? kDeleted : 0) |
                                    (same ? kSameFields : 0)));
    encode_uleb(out, record.fields.size());
    if (!same) for (const std::string& field : record.fields) {
        encode_uleb(out, field.size()); out.append(field);
    }
    for (const std::string& value : record.values) {
        encode_uleb(out, value.size()); out.append(value);
    }
    return out.size() <= UINT32_MAX;
}

std::string header_bytes(const StreamHeader& header) {
    std::string bytes(sizeof(StreamHeader), '\0');
    auto* out = reinterpret_cast<uint8_t*>(bytes.data());
    snapshot_put_u64(out, header.base_id.ms);
    snapshot_put_u64(out + 8, header.base_id.seq);
    snapshot_put_u64(out + 16, header.last_id.ms);
    snapshot_put_u64(out + 24, header.last_id.seq);
    snapshot_put_u64(out + 32, header.max_deleted_entry_id.ms);
    snapshot_put_u64(out + 40, header.max_deleted_entry_id.seq);
    snapshot_put_u64(out + 48, header.entries_added);
    return bytes;
}

bool compact_header(CompactView compact, StreamHeader& header) {
    Compact::Entry entry;
    if (!compact.at(0, entry) || entry.value.n != kHeaderBytes) return false;
    const auto* in = reinterpret_cast<const uint8_t*>(entry.value.p);
    header.base_id = {snapshot_get_u64(in), snapshot_get_u64(in + 8)};
    header.last_id = {snapshot_get_u64(in + 16), snapshot_get_u64(in + 24)};
    header.max_deleted_entry_id = {snapshot_get_u64(in + 32), snapshot_get_u64(in + 40)};
    header.entries_added = snapshot_get_u64(in + 48);
    return true;
}

bool object_header(KvObj* object, StreamHeader& header) {
    if (!object || static_cast<Type>(object->type) != Type::Stream) return false;
    CollectionRef stream(object);
    if (stream.is_embedded()) return compact_header(stream.compact(), header);
    header = stream.external_as<StreamVal>()->header;
    return true;
}

bool update_object_header(KvObj* object, const StreamHeader& header) {
    CollectionRef stream(object);
    if (!stream.is_embedded()) {
        stream.external_as<StreamVal>()->header = header;
        return true;
    }
    Compact::Entry entry;
    if (!stream.compact().at(0, entry)) return false;
    const std::string bytes = header_bytes(header);
    if (!stream.replace(entry, Slice(bytes.data(), static_cast<uint32_t>(bytes.size())))) return false;
    stream.set_aux0(header.last_id.ms);
    stream.set_aux1(header.last_id.seq);
    return true;
}

template <typename Fn>
bool scan_compact(CompactView compact, const StreamID& base, Fn&& fn,
                  const std::vector<std::string>* base_fields = nullptr) {
    std::vector<Slice> previous_fields;
    if (base_fields) {
        try {
            previous_fields.reserve(base_fields->size());
            for (const std::string& field : *base_fields)
                previous_fields.emplace_back(field.data(), static_cast<uint32_t>(field.size()));
        } catch (const std::bad_alloc&) { return false; }
    }
    RecordView record;
    StreamID previous = base;
    for (uint32_t i = 1; i < compact.size(); i++) {
        Compact::Entry raw;
        if (!compact.at(i, raw) || !decode_record(raw.value, previous, previous_fields, record))
            return false;
        if (!fn(raw, record)) return true;
        previous = record.id;
        previous_fields = record.fields;
    }
    return true;
}

template <typename Fn>
bool scan_object(KvObj* object, Fn&& fn) {
    CollectionRef stream(object);
    if (stream.encoding() == CollectionEncoding::Compact) {
        StreamHeader header;
        if (!compact_header(stream.compact(), header)) return false;
        return scan_compact(stream.compact(), header.base_id,
                            [&](const Compact::Entry&, const RecordView& record) {
                                return fn(record);
                            });
    }
    StreamVal* value = stream.external_as<StreamVal>();
    bool keep_scanning = true;
    for (uint32_t i = 0; i < value->nodes.size(); i++) {
        StreamNode& node = value->nodes[i];
        if (!scan_compact(CompactView(&node.log), node.base_id,
                          [&](const Compact::Entry&, const RecordView& record) {
                              keep_scanning = fn(record);
                              return keep_scanning;
                          }, i == 0 && !value->head_fields.empty()
                                 ? &value->head_fields : nullptr)) return false;
        if (!keep_scanning) break;
    }
    return true;
}

// Expanded streams seek through the sorted macro-node index, then decode at most one node's
// prefix before reaching start. Embedded streams are deliberately bounded and scan directly.
template <typename Fn>
bool scan_object_from(KvObj* object, const StreamID& start, Fn&& fn) {
    CollectionRef stream(object);
    if (stream.encoding() == CollectionEncoding::Compact) {
        StreamHeader header;
        if (!compact_header(stream.compact(), header)) return false;
        return scan_compact(stream.compact(), header.base_id,
                            [&](const Compact::Entry&, const RecordView& record) {
                                return fn(record);
                            });
    }
    StreamVal* value = stream.external_as<StreamVal>();
    if (value->index.empty()) return value->nodes.empty();
    auto it = std::upper_bound(value->index.begin(), value->index.end(), start,
        [](const StreamID& id, const StreamNodeIndex& index) {
            return id_compare(id, index.base_id) < 0;
        });
    uint32_t first_node = 0;
    if (it != value->index.begin()) first_node = (--it)->node;
    bool keep_scanning = true;
    for (uint32_t i = first_node; i < value->nodes.size(); i++) {
        StreamNode& node = value->nodes[i];
        if (!scan_compact(CompactView(&node.log), node.base_id,
                          [&](const Compact::Entry&, const RecordView& record) {
                              keep_scanning = fn(record);
                              return keep_scanning;
                          }, i == 0 && !value->head_fields.empty()
                                 ? &value->head_fields : nullptr)) return false;
        if (!keep_scanning) break;
    }
    return true;
}

bool own_record(const RecordView& view, OwnedRecord& out) {
    try {
        out = OwnedRecord{}; out.id = view.id; out.deleted = (view.flags & kDeleted) != 0;
        out.fields.reserve(view.fields.size()); out.values.reserve(view.values.size());
        for (Slice field : view.fields) out.fields.emplace_back(field.p, field.n);
        for (Slice value : view.values) out.values.emplace_back(value.p, value.n);
    } catch (const std::bad_alloc&) { return false; }
    return true;
}

bool collect_compact(CompactView compact, const StreamID& base,
                     std::vector<OwnedRecord>& records,
                     const std::vector<std::string>* base_fields = nullptr) {
    records.clear();
    bool oom = false;
    const bool ok = scan_compact(compact, base, [&](const Compact::Entry&, const RecordView& view) {
        try { records.emplace_back(); }
        catch (const std::bad_alloc&) { oom = true; return false; }
        if (!own_record(view, records.back())) { records.pop_back(); oom = true; return false; }
        return true;
    }, base_fields);
    return ok && !oom;
}

template <typename Fn>
bool scan_object_reverse(KvObj* object, const StreamID& end, Fn&& fn) {
    CollectionRef stream(object);
    std::vector<OwnedRecord> records;
    if (stream.encoding() == CollectionEncoding::Compact) {
        StreamHeader header;
        if (!compact_header(stream.compact(), header) ||
            !collect_compact(stream.compact(), header.base_id, records)) return false;
        for (auto it = records.rbegin(); it != records.rend(); ++it)
            if (!fn(*it)) break;
        return true;
    }
    StreamVal* value = stream.external_as<StreamVal>();
    if (value->index.empty()) return value->nodes.empty();
    auto at = std::upper_bound(value->index.begin(), value->index.end(), end,
        [](const StreamID& id, const StreamNodeIndex& index) {
            return id_compare(id, index.base_id) < 0;
        });
    if (at == value->index.begin()) return true;
    uint32_t node_index = (--at)->node;
    bool keep_scanning = true;
    for (;;) {
        StreamNode& node = value->nodes[node_index];
        if (!collect_compact(CompactView(&node.log), node.base_id, records,
                             node_index == 0 && !value->head_fields.empty()
                                 ? &value->head_fields : nullptr)) return false;
        for (auto it = records.rbegin(); it != records.rend(); ++it) {
            keep_scanning = fn(*it);
            if (!keep_scanning) break;
        }
        if (!keep_scanning || node_index == 0) break;
        node_index--;
    }
    return true;
}

uint64_t stream_live_length(KvObj* object) {
    CollectionRef stream(object);
    if (stream.encoding() != CollectionEncoding::Compact)
        return stream.external_as<StreamVal>()->entries();
    uint64_t live = 0;
    if (!scan_object(object, [&](const RecordView& record) {
            live += (record.flags & kDeleted) == 0; return true;
        })) return 0;
    return live;
}

bool first_live_id(KvObj* object, StreamID& id) {
    bool found = false;
    if (!scan_object(object, [&](const RecordView& record) {
            if (!(record.flags & kDeleted)) { id = record.id; found = true; return false; }
            return true;
        })) return false;
    if (!found) id = {};
    return true;
}

bool last_live_id(KvObj* object, StreamID& id) {
    bool found = false;
    if (!scan_object(object, [&](const RecordView& record) {
            if (!(record.flags & kDeleted)) { id = record.id; found = true; }
            return true;
        })) return false;
    if (!found) id = {};
    return true;
}

uint64_t tail_field_bytes(const StreamVal& value) {
    uint64_t bytes = static_cast<uint64_t>(value.head_fields.capacity() +
                                           value.tail_fields.capacity()) * sizeof(std::string);
    for (const std::string& field : value.head_fields) bytes += field.capacity();
    for (const std::string& field : value.tail_fields) bytes += field.capacity();
    return bytes;
}

uint64_t measure_node_allocation(const StreamVal& value) {
    uint64_t bytes = static_cast<uint64_t>(value.nodes.size()) * sizeof(StreamNode) +
                     static_cast<uint64_t>(value.index.capacity()) * sizeof(StreamNodeIndex) +
                     tail_field_bytes(value);
    for (const StreamNode& node : value.nodes) bytes += node.log.capacity_bytes();
    return bytes;
}

void refresh_allocation(StreamVal& value) {
    value.node_allocation_bytes = measure_node_allocation(value);
    value.note_expanded_allocation(value.node_allocation_bytes);
}

bool write_node_header(StreamNode& node, const StreamHeader& outer) {
    StreamHeader local = outer;
    local.base_id = node.base_id;
    local.last_id = node.last_id;
    local.entries_added = node.physical_entries;
    Compact::Entry entry;
    if (!node.log.at(0, entry)) return false;
    const std::string bytes = header_bytes(local);
    return node.log.replace(entry, Slice(bytes.data(), static_cast<uint32_t>(bytes.size())));
}

bool start_node(StreamVal& value, const OwnedRecord& record) {
    StreamNode node;
    node.base_id = node.last_id = record.id;
    node.physical_entries = 1;
    node.live_entries = record.deleted ? 0 : 1;
    StreamHeader local = value.header;
    local.base_id = local.last_id = record.id;
    local.entries_added = 1;
    const std::string hdr = header_bytes(local);
    std::string encoded;
    if (!node.log.append(Slice(hdr.data(), hdr.size())) ||
        !encode_owned_record(record, record.id, {}, true, encoded) ||
        !node.log.append(Slice(encoded.data(), encoded.size()))) return false;
    try {
        value.nodes.push_back(std::move(node));
        value.index.push_back(StreamNodeIndex{record.id,
                                              static_cast<uint32_t>(value.nodes.size() - 1)});
        value.tail_fields = record.fields;
    } catch (const std::bad_alloc&) {
        if (!value.nodes.empty() && value.nodes.back().base_id.ms == record.id.ms &&
            value.nodes.back().base_id.seq == record.id.seq) value.nodes.pop_back();
        return false;
    }
    return true;
}

bool append_owned_external(StreamVal& value, const OwnedRecord& record,
                           const StreamLimits& limits) {
    if (value.nodes.empty()) return start_node(value, record);
    StreamNode& tail = value.nodes.back();
    std::string encoded;
    if (!encode_owned_record(record, tail.last_id, value.tail_fields, false, encoded)) return false;
    const uint64_t resulting = tail.log.encoded_bytes() + Compact::entry_encoded_size(encoded.size());
    const bool roll_bytes = limits.node_max_bytes && resulting > limits.node_max_bytes;
    const bool roll_entries = limits.node_max_entries &&
                              tail.physical_entries >= limits.node_max_entries;
    if (roll_bytes || roll_entries) return start_node(value, record);
    if (!tail.log.append(Slice(encoded.data(), encoded.size()))) return false;
    tail.last_id = record.id;
    tail.physical_entries++;
    tail.live_entries += !record.deleted;
    value.tail_fields = record.fields;
    return write_node_header(tail, value.header);
}

bool build_external(StreamVal& destination, const StreamHeader& header,
                    const std::vector<OwnedRecord>& records, const StreamLimits& limits) {
    destination.header = header;
    uint32_t live = 0;
    uint64_t payload = 0;
    for (const OwnedRecord& record : records) {
        if (!append_owned_external(destination, record, limits)) return false;
        if (!record.deleted) live++;
        for (const std::string& field : record.fields) payload += field.size();
        for (const std::string& value : record.values) payload += value.size();
    }
    destination.first_id = {};
    for (const OwnedRecord& record : records)
        if (!record.deleted) { destination.first_id = record.id; break; }
    destination.node_allocation_bytes = measure_node_allocation(destination);
    destination.promote(CollectionEncoding::Deque, destination.node_allocation_bytes,
                        live, payload);
    return true;
}

template <bool kNotify>
bool externalize_stream(Shard& shard, Op& op, KvObj*& object) {
    CollectionRef source(object);
    if (!source.is_embedded()) return true;
    StreamHeader header;
    std::vector<OwnedRecord> records;
    if (!compact_header(source.compact(), header) ||
        !collect_compact(source.compact(), header.base_id, records)) {
        reply_err(op.sink(), "ERR out of memory"); return false;
    }
    auto* value = new (std::nothrow) StreamVal;
    if (!value || !build_external(*value, header, records, shard.stream_limits())) {
        delete value; reply_err(op.sink(), "ERR out of memory"); return false;
    }
    KvObj* replacement = kvobj_new_stream(object->key(), value, object->expire_at_ms());
    if (!replacement) { delete value; reply_err(op.sink(), "ERR out of memory"); return false; }
    replacement->set_eviction_meta(object->eviction_meta());
    const FlatStore::InsertResult inserted = shard.store_insert<kNotify>(op.hash, replacement);
    if (inserted != FlatStore::InsertResult::Inserted) {
        kvobj_free(replacement);
        if (inserted == FlatStore::InsertResult::MaxmemoryOom) reply_maxmemory_oom(op);
        else reply_err(op.sink(), "ERR keyspace insert failed");
        return false;
    }
    object = replacement;
    return true;
}

void update_tail_fields_from_op(StreamVal& value, Op& op, uint32_t first_field) {
    value.tail_fields.clear();
    const uint32_t nfields = (op.argc() - first_field) / 2;
    value.tail_fields.reserve(nfields);
    for (uint32_t i = 0; i < nfields; i++) {
        const Slice field = op.arg(first_field + i * 2);
        value.tail_fields.emplace_back(field.p, field.n);
    }
}

bool append_op_external(StreamVal& value, const StreamID& id, Op& op, uint32_t first_field,
                        const StreamLimits& limits) {
    if (value.nodes.empty()) {
        OwnedRecord owned; owned.id = id;
        const uint32_t nfields = (op.argc() - first_field) / 2;
        try {
            for (uint32_t i = 0; i < nfields; i++) {
                const Slice f = op.arg(first_field + i * 2);
                const Slice v = op.arg(first_field + i * 2 + 1);
                owned.fields.emplace_back(f.p, f.n); owned.values.emplace_back(v.p, v.n);
            }
        } catch (const std::bad_alloc&) { return false; }
        return start_node(value, owned);
    }
    StreamNode& tail = value.nodes.back();
    std::string encoded;
    if (!encode_record_from_op(id, tail.last_id, op, first_field, value.tail_fields, false,
                               encoded)) return false;
    const uint64_t resulting = tail.log.encoded_bytes() + Compact::entry_encoded_size(encoded.size());
    if ((limits.node_max_bytes && resulting > limits.node_max_bytes) ||
        (limits.node_max_entries && tail.physical_entries >= limits.node_max_entries)) {
        OwnedRecord owned; owned.id = id;
        const uint32_t nfields = (op.argc() - first_field) / 2;
        try {
            for (uint32_t i = 0; i < nfields; i++) {
                const Slice f = op.arg(first_field + i * 2);
                const Slice v = op.arg(first_field + i * 2 + 1);
                owned.fields.emplace_back(f.p, f.n); owned.values.emplace_back(v.p, v.n);
            }
        } catch (const std::bad_alloc&) { return false; }
        return start_node(value, owned);
    }
    if (!tail.log.append(Slice(encoded.data(), encoded.size()))) return false;
    tail.last_id = id; tail.physical_entries++; tail.live_entries++;
    update_tail_fields_from_op(value, op, first_field);
    return write_node_header(tail, value.header);
}

enum class AddIdKind : uint8_t { Auto, MillisAuto, Explicit };
struct AddId { AddIdKind kind = AddIdKind::Explicit; StreamID id{}; };

bool parse_add_id(Slice input, AddId& parsed) {
    if (input.n == 1 && input.p[0] == '*') { parsed.kind = AddIdKind::Auto; return true; }
    if (input.n >= 3 && input.p[input.n - 2] == '-' && input.p[input.n - 1] == '*') {
        parsed.kind = AddIdKind::MillisAuto;
        return parse_u64_exact(Slice(input.p, input.n - 2), parsed.id.ms);
    }
    parsed.kind = AddIdKind::Explicit;
    return parse_id_numeric(input, parsed.id, 0, false);
}

bool resolve_add_id(Shard& shard, const StreamHeader& header, const AddId& requested,
                    StreamID& result, Op& op) {
    if (header.last_id.ms == UINT64_MAX && header.last_id.seq == UINT64_MAX) {
        reply_err(op.sink(), "ERR The stream has exhausted the last possible ID, unable to add more items");
        return false;
    }
    if (requested.kind == AddIdKind::Auto) {
        const uint64_t now = shard.now_ms() < 0 ? 0 : static_cast<uint64_t>(shard.now_ms());
        if (now > header.last_id.ms) result = {now, 0};
        else { result = header.last_id; if (!id_increment(result)) return false; }
        if (id_zero(result)) result.seq = 1;
        return true;
    }
    if (requested.kind == AddIdKind::MillisAuto) {
        result.ms = requested.id.ms;
        if (result.ms < header.last_id.ms) {
            reply_err(op.sink(), "ERR The ID specified in XADD is equal or smaller than the target stream top item");
            return false;
        }
        if (result.ms == header.last_id.ms) {
            if (header.last_id.seq == UINT64_MAX) {
                reply_err(op.sink(), "ERR The ID specified in XADD is equal or smaller than the target stream top item");
                return false;
            }
            result.seq = header.last_id.seq + 1;
        } else result.seq = result.ms == 0 ? 1 : 0;
        return true;
    }
    result = requested.id;
    if (id_zero(result)) {
        reply_err(op.sink(), "ERR The ID specified in XADD must be greater than 0-0");
        return false;
    }
    if (id_compare(result, header.last_id) <= 0) {
        reply_err(op.sink(), "ERR The ID specified in XADD is equal or smaller than the target stream top item");
        return false;
    }
    return true;
}

enum class TrimKind : uint8_t { None, MaxLen, MinId };
struct TrimSpec {
    TrimKind kind = TrimKind::None;
    uint64_t maxlen = 0;
    StreamID minid{};
    bool approximate = false;
    uint64_t limit = 0;
};

bool parse_trim_threshold(Op& op, uint32_t& pos, TrimSpec& trim) {
    if (pos >= op.argc()) { reply_syntax(op.sink()); return false; }
    if (op.arg(pos).eq_icase("maxlen")) trim.kind = TrimKind::MaxLen;
    else if (op.arg(pos).eq_icase("minid")) trim.kind = TrimKind::MinId;
    else { reply_syntax(op.sink()); return false; }
    pos++;
    if (pos < op.argc() && (op.arg(pos).eq_icase("~") || op.arg(pos).eq_icase("="))) {
        trim.approximate = op.arg(pos).eq_icase("~"); pos++;
    }
    if (pos >= op.argc()) { reply_syntax(op.sink()); return false; }
    if (trim.kind == TrimKind::MaxLen) {
        if (!parse_u64_exact(op.arg(pos++), trim.maxlen)) {
            reply_err(op.sink(), "ERR value is not an integer or out of range"); return false;
        }
    } else if (!parse_id_numeric(op.arg(pos++), trim.minid, 0, false)) {
        reply_invalid_stream_id(op); return false;
    }
    if (pos < op.argc() && op.arg(pos).eq_icase("limit")) {
        if (!trim.approximate) {
            reply_err(op.sink(), "ERR syntax error, LIMIT cannot be used without the special ~ option");
            return false;
        }
        if (pos + 1 >= op.argc() || !parse_u64_exact(op.arg(pos + 1), trim.limit)) {
            reply_syntax(op.sink()); return false;
        }
        pos += 2;
    }
    return true;
}

bool rebuild_compact(Compact& compact, StreamHeader header,
                     const std::vector<OwnedRecord>& records) {
    Compact replacement;
    if (!records.empty()) header.base_id = records.front().id;
    else header.base_id = {};
    const std::string hdr = header_bytes(header);
    if (!replacement.append(Slice(hdr.data(), hdr.size()))) return false;
    StreamID previous = header.base_id;
    std::vector<std::string> fields;
    for (size_t i = 0; i < records.size(); i++) {
        std::string encoded;
        if (!encode_owned_record(records[i], previous, fields, i == 0, encoded) ||
            !replacement.append(Slice(encoded.data(), encoded.size()))) return false;
        previous = records[i].id; fields = records[i].fields;
    }
    compact = std::move(replacement);
    return true;
}

struct TrimCut { size_t physical = 0; uint64_t live = 0; };

TrimCut trim_cut(const std::vector<OwnedRecord>& records, TrimSpec trim, uint64_t live) {
    uint64_t remove_live = trim.kind == TrimKind::MaxLen && live > trim.maxlen
        ? live - trim.maxlen : 0;
    TrimCut cut;
    if (trim.kind == TrimKind::MaxLen) {
        while (cut.physical < records.size() && cut.live < remove_live) {
            cut.live += !records[cut.physical].deleted; cut.physical++;
        }
        while (cut.physical < records.size() && records[cut.physical].deleted)
            cut.physical++;
    } else {
        while (cut.physical < records.size() &&
               id_compare(records[cut.physical].id, trim.minid) < 0) {
            cut.live += !records[cut.physical].deleted; cut.physical++;
        }
    }
    return cut;
}

uint64_t trim_records(std::vector<OwnedRecord>& records, TrimSpec trim, uint64_t live) {
    const TrimCut cut = trim_cut(records, trim, live);
    records.erase(records.begin(), records.begin() + static_cast<ptrdiff_t>(cut.physical));
    return cut.live;
}

bool trim_stream(KvObj* object, const TrimSpec& trim, uint64_t& removed) {
    removed = 0;
    if (trim.kind == TrimKind::None) return true;
    CollectionRef stream(object);
    StreamHeader header;
    if (!object_header(object, header)) return false;
    const uint64_t live = stream_live_length(object);
    if ((trim.kind == TrimKind::MaxLen && live <= trim.maxlen) ||
        (trim.kind == TrimKind::MinId && live == 0)) return true;

    if (stream.encoding() == CollectionEncoding::Compact) {
        std::vector<OwnedRecord> records;
        if (!collect_compact(stream.compact(), header.base_id, records)) return false;
        removed = trim_records(records, trim, live);
        Compact replacement;
        if (!rebuild_compact(replacement, header, records) ||
            !stream.replace_compact(std::move(replacement))) return false;
        if (!records.empty()) header.base_id = records.front().id; else header.base_id = {};
        return update_object_header(object, header);
    }

    StreamVal* value = stream.external_as<StreamVal>();
    uint64_t remaining_live = live;
    while (!value->nodes.empty()) {
        StreamNode& node = value->nodes.front();
        StreamHeader local;
        std::vector<OwnedRecord> records;
        if (!compact_header(CompactView(&node.log), local) ||
            !collect_compact(CompactView(&node.log), node.base_id, records,
                             value->head_fields.empty() ? nullptr : &value->head_fields))
            return false;
        const TrimCut cut = trim_cut(records, trim, remaining_live);
        if (!cut.physical) break;
        removed += cut.live; remaining_live -= cut.live;
        if (cut.physical == records.size()) {
            value->nodes.pop_front();
            value->index.erase(value->index.begin());
            for (uint32_t i = 0; i < value->index.size(); i++) value->index[i].node = i;
            value->head_fields.clear();
            continue;
        }
        try { value->head_fields = records[cut.physical - 1].fields; }
        catch (const std::bad_alloc&) { return false; }
        node.base_id = records[cut.physical - 1].id;
        // Entry zero is the node header. Temporarily remove it, advance the front gap across the
        // exact trimmed prefix, then put the fixed header back into the reclaimed front space.
        if (!node.log.pop_front()) return false;
        for (size_t i = 0; i < cut.physical; i++)
            if (!node.log.pop_front()) return false;
        node.physical_entries -= static_cast<uint32_t>(cut.physical);
        node.live_entries -= static_cast<uint32_t>(cut.live);
        local.base_id = node.base_id;
        local.last_id = node.last_id;
        local.entries_added = node.physical_entries;
        const std::string local_header = header_bytes(local);
        if (!node.log.prepend(Slice(local_header.data(), local_header.size()))) return false;
        value->index.front().base_id = node.base_id;
        break;
    }
    value->note_expanded_delete_many(static_cast<uint32_t>(removed), 0,
                                     value->node_allocation_bytes);
    if (!value->nodes.empty()) header.base_id = value->nodes.front().base_id;
    else header.base_id = {};
    value->header = header;
    first_live_id(object, value->first_id);
    if (!value->nodes.empty()) {
        std::vector<OwnedRecord> tail;
        StreamNode& node = value->nodes.back();
        if (!collect_compact(CompactView(&node.log), node.base_id, tail,
                             value->nodes.size() == 1 && !value->head_fields.empty()
                                 ? &value->head_fields : nullptr)) return false;
        value->tail_fields = tail.empty() ? std::vector<std::string>{} : tail.back().fields;
    } else { value->head_fields.clear(); value->tail_fields.clear(); }
    refresh_allocation(*value);
    return true;
}

template <typename Buf>
void reply_record_to(Buf& sink, const RecordView& record) {
    reply_array_header(sink, 2);
    reply_id_to(sink, record.id);
    reply_array_header(sink, static_cast<uint64_t>(record.fields.size()) * 2);
    for (size_t i = 0; i < record.fields.size(); i++) {
        reply_bulk(sink, record.fields[i]);
        reply_bulk(sink, record.values[i]);
    }
}

class VectorReplyBuf {
public:
    explicit VectorReplyBuf(std::vector<uint8_t>& bytes) : bytes_(bytes) {}
    char* reserve(size_t n) {
        base_ = bytes_.size();
        bytes_.resize(base_ + n);
        return reinterpret_cast<char*>(bytes_.data() + base_);
    }
    void advance(size_t n) { bytes_.resize(base_ + n); }
    void append(const char* source, size_t n) {
        char* destination = reserve(n);
        if (n) std::memcpy(destination, source, n);
        advance(n);
    }
    void push_back(char value) { append(&value, 1); }
private:
    std::vector<uint8_t>& bytes_;
    size_t base_ = 0;
};

bool emit_range_payload(KvObj* object, StreamID start, StreamID end, uint64_t count,
                        bool reverse, std::vector<uint8_t>& payload) {
    payload.clear();
    if (count) {
        const uint64_t hint = std::min<uint64_t>(count, 4096) * 64 + 4;
        payload.reserve(static_cast<size_t>(hint));
    }
    payload.resize(4);
    VectorReplyBuf body(payload);
    uint32_t emitted = 0;
    try {
        if (!reverse) {
            if (!scan_object_from(object, start, [&](const RecordView& record) {
                    if (record.flags & kDeleted) return true;
                    if (id_compare(record.id, start) < 0) return true;
                    if (id_compare(record.id, end) > 0 || (count && emitted >= count)) return false;
                    reply_record_to(body, record); emitted++; return true;
                })) return false;
        } else {
            if (!scan_object_reverse(object, end, [&](const OwnedRecord& record) {
                if (record.deleted || id_compare(record.id, end) > 0) return true;
                if (id_compare(record.id, start) < 0 || (count && emitted >= count)) return false;
                RecordView view; view.id = record.id;
                for (const std::string& field : record.fields)
                    view.fields.emplace_back(field.data(), static_cast<uint32_t>(field.size()));
                for (const std::string& value : record.values)
                    view.values.emplace_back(value.data(), static_cast<uint32_t>(value.size()));
                reply_record_to(body, view); emitted++;
                return true;
            })) return false;
        }
    } catch (const std::bad_alloc&) { payload.clear(); return false; }
    snapshot_put_u32(payload.data(), emitted);
    return true;
}

bool emit_range_reply(Op& op, KvObj* object, StreamID start, StreamID end,
                      uint64_t count, bool reverse) {
    SmallBuf<256> body;
    uint32_t emitted = 0;
    try {
        if (!reverse) {
            if (!scan_object_from(object, start, [&](const RecordView& record) {
                    if (record.flags & kDeleted) return true;
                    if (id_compare(record.id, start) < 0) return true;
                    if (id_compare(record.id, end) > 0 || (count && emitted >= count))
                        return false;
                    reply_record_to(body, record);
                    emitted++;
                    return true;
                })) return false;
        } else {
            if (!scan_object_reverse(object, end, [&](const OwnedRecord& record) {
                if (record.deleted || id_compare(record.id, end) > 0) return true;
                if (id_compare(record.id, start) < 0 || (count && emitted >= count)) return false;
                RecordView view;
                view.id = record.id;
                view.fields.reserve(record.fields.size());
                view.values.reserve(record.values.size());
                for (const std::string& field : record.fields)
                    view.fields.emplace_back(field.data(), static_cast<uint32_t>(field.size()));
                for (const std::string& value : record.values)
                    view.values.emplace_back(value.data(), static_cast<uint32_t>(value.size()));
                reply_record_to(body, view);
                emitted++;
                return true;
            })) return false;
        }
    } catch (const std::bad_alloc&) {
        return false;
    }
    auto sink = op.sink();
    reply_array_header(sink, emitted);
    sink.append(body.data(), body.size());
    return true;
}

bool reply_range_payload(Op& op, const std::vector<uint8_t>& payload) {
    if (payload.size() < 4) return false;
    auto sink = op.sink();
    reply_array_header(sink, snapshot_get_u32(payload.data()));
    sink.append(reinterpret_cast<const char*>(payload.data() + 4), payload.size() - 4);
    return true;
}

struct RangeSpec { StreamID start{}, end{}; bool empty = false; };
bool parse_range_bound(Op& op, Slice input, bool start, StreamID& id) {
    bool exclusive = input.n && input.p[0] == '(';
    if (exclusive) { input.p++; input.n--; }
    if (!parse_id_numeric(input, id, start ? 0 : UINT64_MAX, true)) {
        reply_invalid_stream_id(op); return false;
    }
    if (exclusive && !(start ? id_increment(id) : id_decrement(id))) {
        reply_err(op.sink(), start ? "ERR invalid start ID for the interval"
                                   : "ERR invalid end ID for the interval");
        return false;
    }
    return true;
}

template <bool kNotify>
void range_generic(Shard& shard, Op& op, bool reverse) {
    uint64_t count = 0;
    if (op.argc() != 4 && op.argc() != 6) { reply_syntax(op.sink()); return; }
    if (op.argc() == 6) {
        if (!op.arg(4).eq_icase("count") || !parse_u64_exact(op.arg(5), count)) {
            if (op.arg(4).eq_icase("count"))
                reply_err(op.sink(), "ERR value is not an integer or out of range");
            else reply_syntax(op.sink());
            return;
        }
        if (count == 0) { reply_null_array(op.sink()); return; }
    }
    StreamID start, end;
    if (!reverse) {
        if (!parse_range_bound(op, op.arg(2), true, start) ||
            !parse_range_bound(op, op.arg(3), false, end)) return;
    } else {
        if (!parse_range_bound(op, op.arg(3), true, start) ||
            !parse_range_bound(op, op.arg(2), false, end)) return;
    }
    KvObj* object = shard.store_find<kNotify>(op.hash, op.key());
    if (!object) { reply_array_header(op.sink(), 0); return; }
    if (!obj_type_check(object, Type::Stream, op.sink())) return;
    if (!emit_range_reply(op, object, start, end, count, reverse))
        reply_err(op.sink(), "ERR corrupt stream encoding");
}

struct AddOptions {
    bool nomkstream = false;
    TrimSpec trim;
    uint32_t id_arg = 0;
    AddId id;
};

bool parse_add_options(Op& op, AddOptions& options) {
    uint32_t pos = 2;
    bool trim_seen = false;
    while (pos < op.argc()) {
        if (op.arg(pos).eq_icase("nomkstream")) {
            if (options.nomkstream) { reply_syntax(op.sink()); return false; }
            options.nomkstream = true; pos++; continue;
        }
        if (op.arg(pos).eq_icase("maxlen") || op.arg(pos).eq_icase("minid")) {
            if (trim_seen) { reply_syntax(op.sink()); return false; }
            trim_seen = true;
            if (!parse_trim_threshold(op, pos, options.trim)) return false;
            continue;
        }
        break;
    }
    options.id_arg = pos;
    if (pos >= op.argc() || !parse_add_id(op.arg(pos), options.id)) {
        reply_invalid_stream_id(op); return false;
    }
    pos++;
    if (op.argc() - pos < 2 || ((op.argc() - pos) & 1u)) {
        reply_err(op.sink(), "ERR wrong number of arguments for 'xadd' command"); return false;
    }
    return true;
}

template <bool kNotify>
void cmd_xadd(Shard& shard, Op& op) {
    AddOptions options;
    if (!parse_add_options(op, options)) return;
    if (options.id.kind == AddIdKind::Explicit && id_zero(options.id.id)) {
        reply_err(op.sink(), "ERR The ID specified in XADD must be greater than 0-0"); return;
    }
    KvObj* object = shard.store_find<kNotify>(op.hash, op.key());
    if (!obj_type_check(object, Type::Stream, op.sink())) return;
    if (!object && options.nomkstream) { reply_nil(op.sink()); return; }

    StreamHeader header;
    if (object && !object_header(object, header)) {
        reply_err(op.sink(), "ERR corrupt stream encoding"); return;
    }
    StreamID id;
    if (!resolve_add_id(shard, header, options.id, id, op)) return;
    const uint32_t first_field = options.id_arg + 1;

    if (!object) {
        auto* value = new (std::nothrow) StreamVal;
        if (!value) { reply_err(op.sink(), "ERR out of memory"); return; }
        value->header.base_id = value->header.last_id = id;
        value->header.entries_added = 1;
        value->first_id = id;
        const std::string hdr = header_bytes(value->header);
        std::string encoded;
        if (!value->append(Slice(hdr.data(), hdr.size())) ||
            !encode_record_from_op(id, id, op, first_field, {}, true, encoded) ||
            !value->append(Slice(encoded.data(), encoded.size()))) {
            delete value; reply_err(op.sink(), "ERR out of memory"); return;
        }
        // A first entry can itself exceed the embedded ceiling. Do not leave an external KvObj
        // wrapping an ever-growing Compact log: tier 1 is the macro-node representation.
        if (value->compact().encoded_bytes() > kCollectionEmbedMax) {
            std::vector<OwnedRecord> records;
            if (!collect_compact(CompactView(&value->mutable_compact()),
                                 value->header.base_id, records) ||
                !build_external(*value, value->header, records, shard.stream_limits())) {
                delete value; reply_err(op.sink(), "ERR out of memory"); return;
            }
        }
        KvObj* fresh = kvobj_adopt_stream(op.key(), value);
        if (!fresh) { delete value; reply_err(op.sink(), "ERR out of memory"); return; }
        const FlatStore::InsertResult inserted = shard.store_insert<kNotify>(op.hash, fresh);
        if (inserted != FlatStore::InsertResult::Inserted) {
            kvobj_free(fresh);
            if (inserted == FlatStore::InsertResult::MaxmemoryOom) reply_maxmemory_oom(op);
            else reply_err(op.sink(), "ERR keyspace insert failed");
            return;
        }
        object = fresh;
    } else {
        CollectionRef before(object);
        std::vector<std::string> previous_fields;
        StreamID previous = header.base_id;
        if (before.encoding() == CollectionEncoding::Compact) {
            if (!scan_compact(before.compact(), header.base_id,
                              [&](const Compact::Entry&, const RecordView& record) {
                                  previous = record.id;
                                  previous_fields.clear();
                                  for (Slice field : record.fields)
                                      previous_fields.emplace_back(field.p, field.n);
                                  return true;
                              })) { reply_err(op.sink(), "ERR corrupt stream encoding"); return; }
            if (before.compact().size() == 1) {
                previous = id;
                header.base_id = id;
            }
            std::string encoded;
            if (!encode_record_from_op(id, previous, op, first_field, previous_fields,
                                       before.compact().size() == 1, encoded)) {
                reply_err(op.sink(), "ERR out of memory"); return;
            }
            const uint64_t next = before.compact().encoded_bytes() +
                                  Compact::entry_encoded_size(encoded.size());
            if (before.is_embedded() && !before.embedded_bytes_fit(next)) {
                if (!externalize_stream<kNotify>(shard, op, object)) return;
            }
        }

        CollectionRef stream(object);
        ObjectSizeTracker tracker(shard.store(), object);
        header.last_id = id; header.entries_added++;
        if (stream.encoding() == CollectionEncoding::Compact) {
            std::string encoded;
            if (!encode_record_from_op(id, previous, op, first_field, previous_fields,
                                       stream.compact().size() == 1, encoded) ||
                !stream.append(Slice(encoded.data(), encoded.size())) ||
                !update_object_header(object, header)) {
                reply_err(op.sink(), "ERR out of memory"); return;
            }
        } else {
            StreamVal* value = stream.external_as<StreamVal>();
            if (value->nodes.empty()) header.base_id = id;
            value->header = header;
            const size_t old_nodes = value->nodes.size();
            const uint64_t old_tail_capacity = value->nodes.empty()
                ? 0 : value->nodes.back().log.capacity_bytes();
            const uint64_t old_field_bytes = tail_field_bytes(*value);
            if (!append_op_external(*value, id, op, first_field, shard.stream_limits())) {
                reply_err(op.sink(), "ERR out of memory"); return;
            }
            if (value->nodes.size() == old_nodes) {
                value->node_allocation_bytes = value->node_allocation_bytes -
                    old_tail_capacity - old_field_bytes +
                    value->nodes.back().log.capacity_bytes() + tail_field_bytes(*value);
            } else {
                value->node_allocation_bytes = measure_node_allocation(*value);
            }
            value->note_expanded_insert(0, value->node_allocation_bytes);
            if (id_zero(value->first_id)) value->first_id = id;
        }
    }

    uint64_t trimmed = 0;
    {
        // The append bracket above accounts the transient tail/node growth. Inline trimming can
        // immediately release a head node, so bracket that second mutation as well.
        ObjectSizeTracker trim_tracker(shard.store(), object);
        if (options.trim.kind != TrimKind::None && !trim_stream(object, options.trim, trimmed)) {
            reply_err(op.sink(), "ERR out of memory"); return;
        }
    }
    if constexpr (kNotify) {
        notify_record(shard, op, NOTIFY_STREAM, NotifyEventId::Xadd, op.key());
        if (trimmed) notify_record(shard, op, NOTIFY_STREAM, NotifyEventId::Xtrim, op.key());
    }
    reply_id(op, id);
    if (shard.has_blocking_waiters())
        blocking_publish_key(shard, op.hash, op.key().p, op.key().n);
}

template <bool kNotify>
void cmd_xlen(Shard& shard, Op& op) {
    KvObj* object = shard.store_find<kNotify>(op.hash, op.key());
    if (!obj_type_check(object, Type::Stream, op.sink())) return;
    reply_int(op.sink(), object ? static_cast<long long>(stream_live_length(object)) : 0);
}

template <bool kNotify>
void cmd_xrange(Shard& shard, Op& op) { range_generic<kNotify>(shard, op, false); }
template <bool kNotify>
void cmd_xrevrange(Shard& shard, Op& op) { range_generic<kNotify>(shard, op, true); }

bool delete_one(KvObj* object, const StreamID& wanted) {
    CollectionRef stream(object);
    if (stream.encoding() == CollectionEncoding::Compact) {
        StreamHeader header;
        if (!compact_header(stream.compact(), header)) return false;
        bool deleted = false;
        std::vector<Slice> previous_fields; StreamID previous = header.base_id;
        for (uint32_t i = 1; i < stream.compact().size(); i++) {
            Compact::Entry raw; RecordView record;
            if (!stream.compact().at(i, raw) ||
                !decode_record(raw.value, previous, previous_fields, record)) return false;
            if (id_equal(record.id, wanted)) {
                if (record.flags & kDeleted) return false;
                std::string replacement(raw.value.p, raw.value.n);
                replacement[record.flags_offset] = static_cast<char>(record.flags | kDeleted);
                deleted = stream.replace(raw, Slice(replacement.data(), replacement.size()));
                return deleted;
            }
            if (id_compare(record.id, wanted) > 0) return false;
            previous = record.id; previous_fields = record.fields;
        }
        return false;
    }
    StreamVal* value = stream.external_as<StreamVal>();
    if (value->index.empty()) return false;
    auto it = std::upper_bound(value->index.begin(), value->index.end(), wanted,
        [](const StreamID& id, const StreamNodeIndex& index) {
            return id_compare(id, index.base_id) < 0;
        });
    if (it == value->index.begin()) return false;
    const uint32_t node_index = (--it)->node;
    StreamNode& node = value->nodes[node_index];
    std::vector<Slice> previous_fields;
    if (node_index == 0 && !value->head_fields.empty()) {
        try {
            previous_fields.reserve(value->head_fields.size());
            for (const std::string& field : value->head_fields)
                previous_fields.emplace_back(field.data(), static_cast<uint32_t>(field.size()));
        } catch (const std::bad_alloc&) { return false; }
    }
    StreamID previous = node.base_id;
    for (uint32_t i = 1; i < node.log.size(); i++) {
        Compact::Entry raw; RecordView record;
        if (!node.log.at(i, raw) || !decode_record(raw.value, previous, previous_fields, record))
            return false;
        if (id_equal(record.id, wanted)) {
            if (record.flags & kDeleted) return false;
            std::string replacement(raw.value.p, raw.value.n);
            replacement[record.flags_offset] = static_cast<char>(record.flags | kDeleted);
            if (!node.log.replace(raw, Slice(replacement.data(), replacement.size()))) return false;
            node.live_entries--;
            value->note_expanded_delete(0, value->node_allocation_bytes);
            return true;
        }
        if (id_compare(record.id, wanted) > 0) return false;
        previous = record.id; previous_fields = record.fields;
    }
    return false;
}

template <bool kNotify>
void cmd_xdel(Shard& shard, Op& op) {
    std::vector<StreamID> ids;
    try { ids.resize(op.argc() - 2); }
    catch (const std::bad_alloc&) { reply_err(op.sink(), "ERR out of memory"); return; }
    for (uint32_t i = 2; i < op.argc(); i++)
        if (!parse_id_numeric(op.arg(i), ids[i - 2], 0, false)) {
            reply_invalid_stream_id(op); return;
        }
    KvObj* object = shard.store_find<kNotify>(op.hash, op.key());
    if (!object) { reply_int(op.sink(), 0); return; }
    if (!obj_type_check(object, Type::Stream, op.sink())) return;
    ObjectSizeTracker tracker(shard.store(), object);
    StreamHeader header;
    if (!object_header(object, header)) { reply_err(op.sink(), "ERR corrupt stream encoding"); return; }
    uint64_t removed = 0;
    for (const StreamID& id : ids) if (delete_one(object, id)) {
        removed++;
        if (id_compare(id, header.max_deleted_entry_id) > 0) header.max_deleted_entry_id = id;
    }
    if (removed) {
        if (!update_object_header(object, header)) {
            reply_err(op.sink(), "ERR corrupt stream encoding"); return;
        }
        CollectionRef stream(object);
        if (stream.encoding() != CollectionEncoding::Compact)
            first_live_id(object, stream.external_as<StreamVal>()->first_id);
        if constexpr (kNotify)
            notify_record(shard, op, NOTIFY_STREAM, NotifyEventId::Xdel, op.key());
    }
    reply_int(op.sink(), static_cast<long long>(removed));
}

template <bool kNotify>
void cmd_xtrim(Shard& shard, Op& op) {
    TrimSpec trim; uint32_t pos = 2;
    if (!parse_trim_threshold(op, pos, trim) || pos != op.argc()) {
        if (op.reply.empty()) reply_syntax(op.sink());
        return;
    }
    KvObj* object = shard.store_find<kNotify>(op.hash, op.key());
    if (!object) { reply_int(op.sink(), 0); return; }
    if (!obj_type_check(object, Type::Stream, op.sink())) return;
    ObjectSizeTracker tracker(shard.store(), object);
    uint64_t removed = 0;
    if (!trim_stream(object, trim, removed)) {
        reply_err(op.sink(), "ERR out of memory"); return;
    }
    if constexpr (kNotify) if (removed)
        notify_record(shard, op, NOTIFY_STREAM, NotifyEventId::Xtrim, op.key());
    reply_int(op.sink(), static_cast<long long>(removed));
}

#define TOMO_HANDLER_PAIR(fn) fn<false>, 1, 1, 1, notify_handler<fn<true>>

static const CommandSpec kTable[] = {
    {"XADD",       5, -1, CmdFlags::Write | CmdFlags::DenyOom, TOMO_HANDLER_PAIR(cmd_xadd)},
    {"XLEN",       2,  2, CmdFlags::Readonly, TOMO_HANDLER_PAIR(cmd_xlen)},
    {"XRANGE",     4,  6, CmdFlags::Readonly, TOMO_HANDLER_PAIR(cmd_xrange)},
    {"XREVRANGE",  4,  6, CmdFlags::Readonly, TOMO_HANDLER_PAIR(cmd_xrevrange)},
    {"XDEL",       3, -1, CmdFlags::Write, TOMO_HANDLER_PAIR(cmd_xdel)},
    {"XTRIM",      4, -1, CmdFlags::Write, TOMO_HANDLER_PAIR(cmd_xtrim)},
    {"XREAD",      4, -1, CmdFlags::Readonly | CmdFlags::CursorShard | CmdFlags::Blocking |
                         CmdFlags::MultiShard | CmdFlags::StreamRoute,
                         cmd_xshard_only, 0, 0, 0},
};

#undef TOMO_HANDLER_PAIR

}  // namespace

bool stream_parse_xread_id(Slice input, StreamID& id, bool& latest) {
    latest = input.n == 1 && input.p[0] == '$';
    if (latest) { id = {}; return true; }
    return parse_id_numeric(input, id, 0, false);
}

bool stream_parse_xread(Op& op, StreamXreadArgs& parsed) {
    parsed = {};
    uint32_t pos = 1;
    bool count_seen = false, block_seen = false;
    while (pos < op.argc() && !op.arg(pos).eq_icase("streams")) {
        if (op.arg(pos).eq_icase("count") && !count_seen && pos + 1 < op.argc()) {
            if (!parse_u64_exact(op.arg(pos + 1), parsed.count)) {
                reply_err(op.sink(), "ERR value is not an integer or out of range"); return false;
            }
            count_seen = true; pos += 2;
        } else if (op.arg(pos).eq_icase("block") && !block_seen && pos + 1 < op.argc()) {
            if (!parse_u64_exact(op.arg(pos + 1), parsed.block_ms)) {
                reply_err(op.sink(), "ERR timeout is not an integer or out of range"); return false;
            }
            parsed.block = true; block_seen = true; pos += 2;
        } else { reply_syntax(op.sink()); return false; }
    }
    if (pos >= op.argc()) { reply_syntax(op.sink()); return false; }
    parsed.first_key = ++pos;
    const uint32_t remaining = op.argc() - pos;
    if (!remaining || (remaining & 1u)) {
        reply_err(op.sink(), "ERR Unbalanced XREAD list of streams: for each stream key an ID or '$' must be specified");
        return false;
    }
    parsed.key_count = remaining / 2;
    parsed.first_id = parsed.first_key + parsed.key_count;
    for (uint32_t i = 0; i < parsed.key_count; i++) {
        StreamID id; bool latest;
        if (!stream_parse_xread_id(op.arg(parsed.first_id + i), id, latest)) {
            reply_invalid_stream_id(op); return false;
        }
    }
    return true;
}

bool stream_xread_has_block_option(const Op& op) {
    if (!op.cmd_name().eq_icase("xread")) return false;
    for (uint32_t i = 1; i < op.argc() && !op.arg(i).eq_icase("streams"); i++)
        if (op.arg(i).eq_icase("block")) return true;
    return false;
}

bool stream_object_last_id(const KvObj* object, StreamID& id) {
    if (!object || static_cast<Type>(object->type) != Type::Stream) return false;
    if (static_cast<Enc>(object->enc) == Enc::Compact) {
        const EmbeddedCompact* embedded = embedded_compact(object);
        id = {embedded->aux0(), embedded->aux1()};
        return true;
    }
    id = static_cast<const StreamVal*>(object->external_ptr())->header.last_id;
    return true;
}

bool stream_object_has_live_after(const KvObj* object, const StreamID& cursor) {
    if (!object || static_cast<Type>(object->type) != Type::Stream) return false;
    StreamID last;
    if (!last_live_id(const_cast<KvObj*>(object), last) || id_zero(last)) return false;
    return id_compare(last, cursor) > 0;
}

StreamReadResult stream_xread_gather(Shard& shard, Slice key, uint64_t hash,
                                     const StreamID& cursor, bool latest, uint64_t count,
                                     std::vector<uint8_t>& payload,
                                     const StreamID* upper_bound) {
    KvObj* object = shard.notify_carrier() ? shard.store_find<true>(hash, key)
                                           : shard.store().find(hash, key);
    if (!object) { payload.clear(); return StreamReadResult::Missing; }
    if (static_cast<Type>(object->type) != Type::Stream) return StreamReadResult::WrongType;
    StreamID start = cursor;
    if (latest) {
        if (!stream_object_last_id(object, start)) return StreamReadResult::Corrupt;
    }
    if (!id_increment(start)) { payload.clear(); return StreamReadResult::Empty; }
    const StreamID end = upper_bound ? *upper_bound : StreamID{UINT64_MAX, UINT64_MAX};
    if (!emit_range_payload(object, start, end, count, false, payload))
        return StreamReadResult::Oom;
    return payload.size() >= 4 && snapshot_get_u32(payload.data())
        ? StreamReadResult::Ready : StreamReadResult::Empty;
}

bool stream_reply_xread_payload(Op& op, Slice key, const std::vector<uint8_t>& payload) {
    reply_array_header(op.sink(), 2);
    reply_bulk(op.sink(), key);
    return reply_range_payload(op, payload);
}

namespace {

// Snapshot format v1: [u32 version][56-byte header][u32 physical count], followed by physical
// records [u64 ms][u64 seq][u8 deleted][u32 fields] ([u32 flen][field][u32 vlen][value])... .
uint64_t stream_snapshot_size(KvObj* object, uint32_t& physical) {
    uint64_t total = 4 + sizeof(StreamHeader) + 4; physical = 0;
    if (!scan_object(object, [&](const RecordView& record) {
            total += 16 + 1 + 4;
            for (size_t i = 0; i < record.fields.size(); i++)
                total += 8ull + record.fields[i].n + record.values[i].n;
            physical++; return true;
        })) return UINT64_MAX;
    return total;
}

SnapshotHookStatus stream_snapshot_begin(const KvObj& object, SnapshotSaveCursor& cursor,
                                         uint8_t& encoding) {
    if (static_cast<Type>(object.type) != Type::Stream) return SnapshotHookStatus::Corrupt;
    cursor = {}; cursor.object = &object;
    encoding = CollectionRef(const_cast<KvObj*>(&object)).encoding() ==
                       CollectionEncoding::Compact ? 1 : 2;
    uint32_t physical = 0;
    cursor.total = stream_snapshot_size(const_cast<KvObj*>(&object), physical);
    cursor.lane[2] = physical;
    return cursor.total == UINT64_MAX ? SnapshotHookStatus::Corrupt : SnapshotHookStatus::Ok;
}

SnapshotHookStatus stream_snapshot_read(SnapshotSaveCursor& cursor, uint8_t* destination,
                                        size_t capacity, size_t& written) {
    written = 0;
    if (!cursor.object) return SnapshotHookStatus::Corrupt;
    KvObj* object = const_cast<KvObj*>(cursor.object);
    SnapshotElementEmitter emitter{destination, capacity};
    uint64_t index = cursor.lane[0];
    if (index == 0) {
        uint8_t meta[64]{};
        snapshot_put_u32(meta, 1);
        StreamHeader header;
        if (!object_header(object, header)) return SnapshotHookStatus::Corrupt;
        const std::string encoded_header = header_bytes(header);
        std::memcpy(meta + 4, encoded_header.data(), encoded_header.size());
        snapshot_put_u32(meta + 60, static_cast<uint32_t>(cursor.lane[2]));
        emitter.resume = cursor.lane[1];
        if (!emitter.put(meta, sizeof(meta))) {
            cursor.lane[1] = emitter.pos;
            cursor.offset += emitter.out; written = emitter.out;
            return SnapshotHookStatus::Ok;
        }
        index = 1; cursor.lane[1] = 0;
    }
    uint64_t physical = 0;
    bool stopped = false, corrupt = false;
    if (!scan_object(object, [&](const RecordView& record) {
            physical++;
            if (physical + 0 < index) return true;
            emitter.pos = 0; emitter.resume = physical + 0 == index ? cursor.lane[1] : 0;
            uint8_t fixed[21];
            snapshot_put_u64(fixed, record.id.ms); snapshot_put_u64(fixed + 8, record.id.seq);
            fixed[16] = (record.flags & kDeleted) != 0;
            snapshot_put_u32(fixed + 17, static_cast<uint32_t>(record.fields.size()));
            if (!emitter.put(fixed, sizeof(fixed))) { stopped = true; return false; }
            for (size_t i = 0; i < record.fields.size(); i++) {
                if (!emitter.put_u32(record.fields[i].n) ||
                    !emitter.put(record.fields[i].p, record.fields[i].n) ||
                    !emitter.put_u32(record.values[i].n) ||
                    !emitter.put(record.values[i].p, record.values[i].n)) {
                    stopped = true; return false;
                }
            }
            index = physical + 1; cursor.lane[1] = 0; return true;
        })) corrupt = true;
    if (corrupt) return SnapshotHookStatus::Corrupt;
    cursor.lane[0] = stopped ? physical : static_cast<uint64_t>(cursor.lane[2]) + 1;
    cursor.lane[1] = stopped ? emitter.pos : 0;
    cursor.offset += emitter.out; written = emitter.out;
    return SnapshotHookStatus::Ok;
}

SnapshotHookStatus stream_snapshot_load(Slice key, uint8_t encoding, int64_t expire_at_ms,
                                        Slice payload, const TypeLimits&, KvObj*& result) {
    result = nullptr;
    if ((encoding != 1 && encoding != 2) || payload.n < 64)
        return SnapshotHookStatus::Corrupt;
    const uint8_t* p = reinterpret_cast<const uint8_t*>(payload.p);
    size_t left = payload.n;
    if (snapshot_get_u32(p) != 1) return SnapshotHookStatus::Corrupt;
    StreamHeader header;
    header.base_id = {snapshot_get_u64(p + 4), snapshot_get_u64(p + 12)};
    header.last_id = {snapshot_get_u64(p + 20), snapshot_get_u64(p + 28)};
    header.max_deleted_entry_id = {snapshot_get_u64(p + 36), snapshot_get_u64(p + 44)};
    header.entries_added = snapshot_get_u64(p + 52);
    const uint32_t count = snapshot_get_u32(p + 60); p += 64; left -= 64;
    std::vector<OwnedRecord> records;
    try { records.reserve(count); }
    catch (const std::bad_alloc&) { return SnapshotHookStatus::Oom; }
    for (uint32_t n = 0; n < count; n++) {
        if (left < 21) return SnapshotHookStatus::Corrupt;
        OwnedRecord record;
        record.id = {snapshot_get_u64(p), snapshot_get_u64(p + 8)};
        record.deleted = p[16] != 0;
        const uint32_t fields = snapshot_get_u32(p + 17); p += 21; left -= 21;
        try {
            record.fields.reserve(fields); record.values.reserve(fields);
            for (uint32_t i = 0; i < fields; i++) {
                if (left < 4) return SnapshotHookStatus::Corrupt;
                uint32_t len = snapshot_get_u32(p); p += 4; left -= 4;
                if (left < len) return SnapshotHookStatus::Corrupt;
                record.fields.emplace_back(reinterpret_cast<const char*>(p), len);
                p += len; left -= len;
                if (left < 4) return SnapshotHookStatus::Corrupt;
                len = snapshot_get_u32(p); p += 4; left -= 4;
                if (left < len) return SnapshotHookStatus::Corrupt;
                record.values.emplace_back(reinterpret_cast<const char*>(p), len);
                p += len; left -= len;
            }
            records.push_back(std::move(record));
        } catch (const std::bad_alloc&) { return SnapshotHookStatus::Oom; }
    }
    if (left) return SnapshotHookStatus::Corrupt;
    auto* value = new (std::nothrow) StreamVal;
    if (!value) return SnapshotHookStatus::Oom;
    value->header = header;
    Compact compact;
    if (!rebuild_compact(compact, header, records)) { delete value; return SnapshotHookStatus::Oom; }
    if (encoding == 1 && compact.encoded_bytes() <= kCollectionEmbedMax) {
        value->replace_compact(std::move(compact));
    } else if (!build_external(*value, header, records, StreamLimits{})) {
        delete value; return SnapshotHookStatus::Oom;
    }
    result = kvobj_adopt_stream(key, value, expire_at_ms);
    if (!result) { delete value; return SnapshotHookStatus::Oom; }
    return SnapshotHookStatus::Ok;
}

}  // namespace

SnapshotTypeHooks stream_snapshot_hooks() {
    return {stream_snapshot_begin, stream_snapshot_read, stream_snapshot_load};
}

CommandTable stream_command_table() {
    return {kTable, sizeof(kTable) / sizeof(kTable[0])};
}

}  // namespace tomo
