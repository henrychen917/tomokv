// xshard.cc -- arena-backed, owner-only cross-shard execution.
#include "xshard.h"

#include <algorithm>
#include <atomic>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <new>
#include <string>
#include <unordered_set>
#include <utility>
#include <vector>

#include "command.h"
#include "../core/server.h"
#include "../core/thread.h"
#include "../exec/op.h"
#include "../net/conn.h"
#include "../net/resp.h"
#include "../net/uring.h"
#include "../snapshot/format.h"
#include "../store/kvobj.h"

namespace tomo {
void reply_maxmemory_oom(Op& op);  // shared canonical spelling from t_string.cc
namespace {

enum class Kind : uint8_t {
    AllShards, DbsizeExact, Mget, Mset, Del, Unlink, Exists, Touch, Keys, Msetnx,
    Rename, Renamenx, Copy, Smove, Lmove, Rpoplpush,
    Sinter, Sunion, Sdiff, Sintercard, Sinterstore, Sunionstore, Sdiffstore,
    Bitop,
};

enum class BitOperation : uint8_t { And, Or, Xor, Not };

enum class WorkError : uint8_t { None, WrongType, Oom, Maxmemory, InsertFailed, Corrupt };
enum class FinalReply : uint8_t {
    None, Ok, Integer, Nil, Bulk, Array, Work, NoSuchKey, SameObject, QueueFull, Internal
};
enum class ValueKind : uint8_t { Nil, Inline, Borrow };

struct ObjectImage {
    bool present = false;
    Type type = Type::String;
    uint8_t encoding = 0;
    int64_t expire_at_ms = -1;
    std::vector<uint8_t> payload;
};

// Integers are at most 20 bytes including the sign.  Tiny raw strings use the same inline lane;
// anything larger is cheaper to retain through FlatStore's existing borrow registry.
struct ValueSlot {
    static constexpr uint32_t kInline = 24;
    const char* ptr = nullptr;
    uint32_t len = 0;
    int32_t shard = -1;
    ValueKind kind = ValueKind::Nil;
    char small[kInline] = {};
};

struct GroupAux {
    std::vector<std::string> flush_keys;
    std::vector<std::string> keys_result;
    bool flush_keys_built = false;
};

// Groups are dense (one record per touched shard), and each owns one range in key_order[].
// No per-group vector exists on the common path.
struct ShardGroup {
    int32_t shard = -1;
    uint32_t begin = 0;
    uint32_t count = 0;
    uint32_t snapshot_pos = 0;
    uint64_t scan_cursor = 0;
    WorkError error = WorkError::None;
    GroupAux* aux = nullptr;                 // KEYS / capture-safe FLUSH only
};

struct KeyRef {
    uint64_t hash = 0;
    uint32_t arg = 0;
    int32_t shard = -1;
};

struct ResultHeap {
    std::string bulk;
    std::vector<std::string> members;
};

struct RouteKey {
    uint64_t hash = 0;
    uint32_t arg = 0;
    int32_t shard = -1;
};

constexpr uint32_t kRouteStack = 32;

bool name_is(const Op& op, const char* name) { return std::strcmp(op.spec->name, name) == 0; }

bool parse_u64(Slice s, uint64_t& value) {
    if (!s.n) return false;
    uint64_t v = 0;
    for (uint32_t i = 0; i < s.n; i++) {
        const uint8_t c = static_cast<uint8_t>(s.p[i]);
        if (c < '0' || c > '9') return false;
        if (v > (std::numeric_limits<uint64_t>::max() - (c - '0')) / 10) return false;
        v = v * 10 + (c - '0');
    }
    value = v;
    return true;
}

void set_oom(Op& op) { reply_err(op.sink(), "ERR out of memory"); }

bool classify(const Op& op, Kind& kind) {
    struct Entry { const char* name; Kind kind; };
    static constexpr Entry entries[] = {
        {"MGET", Kind::Mget}, {"MSET", Kind::Mset}, {"DEL", Kind::Del},
        {"UNLINK", Kind::Unlink}, {"EXISTS", Kind::Exists}, {"TOUCH", Kind::Touch},
        {"KEYS", Kind::Keys}, {"MSETNX", Kind::Msetnx}, {"RENAME", Kind::Rename},
        {"RENAMENX", Kind::Renamenx}, {"COPY", Kind::Copy}, {"SMOVE", Kind::Smove},
        {"LMOVE", Kind::Lmove}, {"RPOPLPUSH", Kind::Rpoplpush},
        {"SINTER", Kind::Sinter}, {"SUNION", Kind::Sunion}, {"SDIFF", Kind::Sdiff},
        {"SINTERCARD", Kind::Sintercard}, {"SINTERSTORE", Kind::Sinterstore},
        {"SUNIONSTORE", Kind::Sunionstore}, {"SDIFFSTORE", Kind::Sdiffstore},
        {"BITOP", Kind::Bitop},
    };
    for (const Entry& entry : entries)
        if (name_is(op, entry.name)) { kind = entry.kind; return true; }
    return false;
}

bool is_two_hop(Kind kind) { return kind >= Kind::Msetnx; }
bool is_store_setop(Kind kind) {
    return kind == Kind::Sinterstore || kind == Kind::Sunionstore ||
           kind == Kind::Sdiffstore;
}
bool is_plain_setop(Kind kind) {
    return kind == Kind::Sinter || kind == Kind::Sunion || kind == Kind::Sdiff;
}

template <typename T>
size_t carve_size(size_t& offset, uint32_t count) {
    if (!count) return offset;
    const size_t align = alignof(T);
    offset = (offset + align - 1) & ~(align - 1);
    const size_t at = offset;
    if (count > (std::numeric_limits<size_t>::max() - offset) / sizeof(T)) {
        offset = std::numeric_limits<size_t>::max();
        return offset;
    }
    offset += sizeof(T) * static_cast<size_t>(count);
    return at;
}

bool serialize_object(KvObj* object, ObjectImage& image) {
    image = ObjectImage{};
    if (!object) return true;
    image.present = true;
    image.type = static_cast<Type>(object->type);
    image.expire_at_ms = object->expire_at_ms();
    const SnapshotTypeHooks& hooks = snapshot_type_hooks(image.type);
    SnapshotSaveCursor cursor;
    if (!hooks.begin_save || !hooks.read_save ||
        hooks.begin_save(*object, cursor, image.encoding) != SnapshotHookStatus::Ok ||
        cursor.total > UINT32_MAX) return false;
    try {
        image.payload.resize(static_cast<size_t>(cursor.total));
    } catch (const std::bad_alloc&) {
        return false;
    }
    while (cursor.offset < cursor.total) {
        size_t written = 0;
        if (hooks.read_save(cursor, image.payload.data() + cursor.offset,
                            image.payload.size() - static_cast<size_t>(cursor.offset), written) !=
                SnapshotHookStatus::Ok || !written) return false;
    }
    return true;
}

WorkError apply_image(Shard& shard, Slice key, uint64_t hash, const ObjectImage& image) {
    if (!image.present) { shard.store().erase(hash, key); return WorkError::None; }
    const SnapshotTypeHooks& hooks = snapshot_type_hooks(image.type);
    KvObj* object = nullptr;
    const Slice payload(reinterpret_cast<const char*>(image.payload.data()),
                        static_cast<uint32_t>(image.payload.size()));
    if (!hooks.load) return WorkError::Corrupt;
    const SnapshotHookStatus loaded = hooks.load(key, image.encoding, image.expire_at_ms, payload,
                                                 shard.type_limits(), object);
    if (loaded == SnapshotHookStatus::Oom) return WorkError::Oom;
    if (loaded != SnapshotHookStatus::Ok || !object) return WorkError::Corrupt;
    const FlatStore::InsertResult result = shard.store().insert(hash, object);
    if (result == FlatStore::InsertResult::Inserted) return WorkError::None;
    kvobj_free(object);
    return result == FlatStore::InsertResult::MaxmemoryOom ? WorkError::Maxmemory
                                                           : WorkError::InsertFailed;
}

WorkError store_xstring(Shard& shard, Slice key, uint64_t hash, Slice value,
                        bool integer_encode = true) {
    switch (xshard_store_string(shard, key, hash, value, integer_encode)) {
        case XshardStringStoreResult::Stored: return WorkError::None;
        case XshardStringStoreResult::Oom: return WorkError::Oom;
        case XshardStringStoreResult::Maxmemory: return WorkError::Maxmemory;
        case XshardStringStoreResult::InsertFailed: return WorkError::InsertFailed;
    }
    return WorkError::InsertFailed;
}

bool decode_elements(const ObjectImage& image, std::vector<std::string>& out) {
    out.clear();
    const uint8_t* p = image.payload.data();
    size_t left = image.payload.size();
    try {
        while (left) {
            if (left < 4) return false;
            const uint32_t len = snapshot_get_u32(p);
            p += 4; left -= 4;
            if (left < len) return false;
            out.emplace_back(reinterpret_cast<const char*>(p), len);
            p += len; left -= len;
        }
    } catch (const std::bad_alloc&) {
        return false;
    }
    return true;
}

bool encode_elements(const std::vector<std::string>& elements, ObjectImage& image, Type type,
                     int64_t expire_at_ms) {
    uint64_t total = 0;
    for (const std::string& element : elements) total += 4ull + element.size();
    if (total > UINT32_MAX) return false;
    try {
        image = ObjectImage{};
        image.present = true;
        image.type = type;
        image.encoding = 0;
        image.expire_at_ms = expire_at_ms;
        image.payload.resize(static_cast<size_t>(total));
    } catch (const std::bad_alloc&) {
        return false;
    }
    uint8_t* p = image.payload.data();
    for (const std::string& element : elements) {
        snapshot_put_u32(p, static_cast<uint32_t>(element.size())); p += 4;
        std::memcpy(p, element.data(), element.size()); p += element.size();
    }
    return true;
}

bool bitop_operation(Slice name, BitOperation& operation) {
    if (name.eq_icase("and")) operation = BitOperation::And;
    else if (name.eq_icase("or")) operation = BitOperation::Or;
    else if (name.eq_icase("xor")) operation = BitOperation::Xor;
    else if (name.eq_icase("not")) operation = BitOperation::Not;
    else return false;
    return true;
}

bool decode_string_image(const ObjectImage& image, std::string& value, WorkError& error) {
    value.clear();
    if (!image.present) return true;
    if (image.type != Type::String) { error = WorkError::WrongType; return false; }
    try {
        const Enc encoding = static_cast<Enc>(image.encoding);
        if (encoding == Enc::Int) {
            if (image.payload.size() != sizeof(int64_t)) {
                error = WorkError::Corrupt;
                return false;
            }
            char integer[24];
            const int64_t decoded = static_cast<int64_t>(snapshot_get_u64(image.payload.data()));
            value.assign(integer, i64_to_dec(integer, decoded));
        } else if (encoding == Enc::Raw || encoding == Enc::Extern) {
            if (!image.payload.empty())
                value.assign(reinterpret_cast<const char*>(image.payload.data()),
                             image.payload.size());
        } else {
            error = WorkError::Corrupt;
            return false;
        }
    } catch (const std::bad_alloc&) {
        error = WorkError::Oom;
        return false;
    }
    return true;
}

bool compute_bitop(const ObjectImage* images, uint32_t first, uint32_t count, Slice operation_name,
                   ObjectImage& output, long long& output_length, WorkError& error) {
    BitOperation operation;
    if (!bitop_operation(operation_name, operation)) {
        error = WorkError::Corrupt;
        return false;
    }
    std::vector<std::string> sources;
    try {
        sources.resize(count);
        size_t max_length = 0;
        for (uint32_t i = 0; i < count; i++) {
            if (!decode_string_image(images[first + i], sources[i], error)) return false;
            max_length = std::max(max_length, sources[i].size());
        }
        output = ObjectImage{};
        output_length = static_cast<long long>(max_length);
        if (!max_length) return true;

        output.present = true;
        output.type = Type::String;
        output.encoding = static_cast<uint8_t>(Enc::Raw);
        output.expire_at_ms = -1;
        output.payload.resize(max_length);
        for (size_t byte = 0; byte < max_length; byte++) {
            uint8_t result = byte < sources[0].size()
                ? static_cast<uint8_t>(sources[0][byte]) : 0;
            if (operation == BitOperation::Not) {
                result = static_cast<uint8_t>(~result);
            } else {
                for (uint32_t source = 1; source < count; source++) {
                    const uint8_t next = byte < sources[source].size()
                        ? static_cast<uint8_t>(sources[source][byte]) : 0;
                    if (operation == BitOperation::And) result &= next;
                    else if (operation == BitOperation::Or) result |= next;
                    else result ^= next;
                }
            }
            output.payload[byte] = result;
        }
    } catch (const std::bad_alloc&) {
        error = WorkError::Oom;
        return false;
    }
    return true;
}

bool glob_match(const char* pattern, size_t pn, const char* text, size_t tn) {
    while (pn) {
        const char c = *pattern++; pn--;
        if (c == '*') {
            while (pn && *pattern == '*') { pattern++; pn--; }
            if (!pn) return true;
            for (size_t i = 0; i <= tn; i++)
                if (glob_match(pattern, pn, text + i, tn - i)) return true;
            return false;
        }
        if (!tn) return false;
        if (c == '?') { text++; tn--; continue; }
        if (c == '\\' && pn) {
            const char literal = *pattern++; pn--;
            if (*text++ != literal) return false;
            tn--; continue;
        }
        if (c == '[') {
            bool negate = false, match = false;
            if (pn && (*pattern == '^' || *pattern == '!')) { negate = true; pattern++; pn--; }
            while (pn && *pattern != ']') {
                char lo = *pattern++; pn--;
                if (lo == '\\' && pn) { lo = *pattern++; pn--; }
                if (pn >= 2 && *pattern == '-' && pattern[1] != ']') {
                    pattern++; pn--; char hi = *pattern++; pn--;
                    if (hi == '\\' && pn) { hi = *pattern++; pn--; }
                    if (*text >= lo && *text <= hi) match = true;
                } else if (*text == lo) match = true;
            }
            if (pn && *pattern == ']') { pattern++; pn--; }
            if (match == negate) return false;
            text++; tn--; continue;
        }
        if (*text++ != c) return false;
        tn--;
    }
    return tn == 0;
}

bool same_key(const Op& op) {
    const Slice a = op.arg(1), b = op.arg(2);
    return a.n == b.n && (a.n == 0 || std::memcmp(a.p, b.p, a.n) == 0);
}

bool image_type(const ObjectImage& image, Type type) {
    return !image.present || image.type == type;
}

bool contains(const std::vector<std::string>& values, Slice wanted) {
    for (const std::string& value : values)
        if (value.size() == wanted.n &&
            (wanted.n == 0 || std::memcmp(value.data(), wanted.p, wanted.n) == 0)) return true;
    return false;
}

bool erase_member(std::vector<std::string>& values, Slice wanted) {
    for (auto it = values.begin(); it != values.end(); ++it)
        if (it->size() == wanted.n &&
            (wanted.n == 0 || std::memcmp(it->data(), wanted.p, wanted.n) == 0)) {
            values.erase(it); return true;
        }
    return false;
}

void reply_work_error(Op& op, WorkError error) {
    if (error == WorkError::WrongType) reply_wrongtype(op.sink());
    else if (error == WorkError::Maxmemory) reply_maxmemory_oom(op);
    else if (error == WorkError::Oom) reply_err(op.sink(), "ERR out of memory");
    else if (error == WorkError::InsertFailed) reply_err(op.sink(), "ERR keyspace insert failed");
    else reply_err(op.sink(), "ERR internal cross-shard value error");
}

}  // namespace

struct ScatterState {
    std::atomic<uint32_t> pending{0};
    // Reserved future epoch-MVCC attachment point.  This phase intentionally assigns no epochs,
    // read sets, versions or retries; validate/apply remain separate so those can land here later.
    uint64_t epoch = 0;
    std::atomic<uint64_t> exact_sum{0};
    Kind kind = Kind::AllShards;
    FinalReply final_reply = FinalReply::None;
    WorkError final_error = WorkError::None;
    uint8_t phase = 1;
    bool barrier = false;
    bool pooled = false;
    bool copy_replace = false;
    bool from_left = false;
    bool to_left = false;
    uint32_t owner_io = 0;
    uint32_t arena_bytes = 0;
    uint32_t key_count = 0;
    uint32_t nsub = 0;
    uint32_t group_cap = 0;
    uint32_t phase1_first = 0;
    uint32_t set_first = 0;
    uint32_t set_count = 0;
    uint32_t hop2_count = 0;
    uint64_t sinter_limit = 0;
    long long final_integer = 0;
    ShardGroup* groups = nullptr;
    KeyRef* keys = nullptr;
    uint32_t* key_order = nullptr;
    ValueSlot* values = nullptr;
    uint8_t* status = nullptr;
    ObjectImage* images = nullptr;
    ObjectImage* apply = nullptr;
    uint32_t* hop2 = nullptr;
    ResultHeap* result = nullptr;
};

namespace {

ShardGroup* group_for(ScatterState& state, int32_t shard) {
    for (uint32_t i = 0; i < state.nsub; i++)
        if (state.groups[i].shard == shard) return &state.groups[i];
    return nullptr;
}

ResultHeap* ensure_result(ScatterState& state) {
    if (!state.result) state.result = new (std::nothrow) ResultHeap;
    return state.result;
}

bool first_error(const ScatterState& state, WorkError& error) {
    for (uint32_t gi = 0; gi < state.nsub; gi++) {
        const ShardGroup& group = state.groups[gi];
        if (group.error != WorkError::None) { error = group.error; return true; }
        if (!state.status || !(state.kind == Kind::Mset || is_two_hop(state.kind))) continue;
        for (uint32_t i = 0; i < group.count; i++) {
            const WorkError value = static_cast<WorkError>(state.status[state.key_order[group.begin + i]]);
            if (value != WorkError::None) { error = value; return true; }
        }
    }
    return false;
}

uint32_t key_count_for(Kind kind, const Op& op, uint32_t sinter_count) {
    if (kind == Kind::AllShards || kind == Kind::DbsizeExact || kind == Kind::Keys) return 0;
    if (kind == Kind::Mset || kind == Kind::Msetnx) return (op.argc() - 1) / 2;
    if (kind == Kind::Bitop) return op.argc() - 2;
    if (kind == Kind::Rename || kind == Kind::Renamenx || kind == Kind::Copy ||
        kind == Kind::Smove || kind == Kind::Lmove || kind == Kind::Rpoplpush) return 2;
    if (kind == Kind::Sintercard) return sinter_count;
    return op.argc() - 1;
}

uint32_t key_arg_for(Kind kind, uint32_t key, uint32_t) {
    if (kind == Kind::Mset || kind == Kind::Msetnx) return 1 + key * 2;
    if (kind == Kind::Bitop) return 2 + key;
    if (kind == Kind::Sintercard) return 2 + key;
    return 1 + key;
}

bool has_values(Kind kind) { return kind == Kind::Mget || kind == Kind::Msetnx; }
bool has_status(Kind kind) {
    return kind == Kind::Mset || kind == Kind::Del || kind == Kind::Unlink ||
           kind == Kind::Exists || kind == Kind::Touch || is_two_hop(kind);
}
bool has_images(Kind kind) { return is_two_hop(kind) && kind != Kind::Msetnx; }

size_t arena_layout_bytes(Kind kind, uint32_t key_count, uint32_t group_cap) {
    size_t off = sizeof(ScatterState);
    carve_size<ShardGroup>(off, group_cap);
    carve_size<KeyRef>(off, key_count);
    carve_size<uint32_t>(off, key_count);             // key_order
    if (has_values(kind)) carve_size<ValueSlot>(off, key_count);
    if (has_status(kind)) carve_size<uint8_t>(off, key_count);
    if (has_images(kind)) {
        carve_size<ObjectImage>(off, key_count);
        carve_size<ObjectImage>(off, key_count);
    }
    if (is_two_hop(kind)) carve_size<uint32_t>(off, key_count);  // complete hop-2 plan
    return off;
}

template <typename T>
T* carve_at(char* base, size_t& off, uint32_t count) {
    if (!count) return nullptr;
    const size_t align = alignof(T);
    off = (off + align - 1) & ~(align - 1);
    T* result = reinterpret_cast<T*>(base + off);
    off += sizeof(T) * static_cast<size_t>(count);
    return result;
}

void init_arena_arrays(ScatterState& state) {
    char* base = reinterpret_cast<char*>(&state);
    size_t off = sizeof(ScatterState);
    state.groups = carve_at<ShardGroup>(base, off, state.group_cap);
    state.keys = carve_at<KeyRef>(base, off, state.key_count);
    state.key_order = carve_at<uint32_t>(base, off, state.key_count);
    if (has_values(state.kind)) state.values = carve_at<ValueSlot>(base, off, state.key_count);
    if (has_status(state.kind)) state.status = carve_at<uint8_t>(base, off, state.key_count);
    if (has_images(state.kind)) {
        state.images = carve_at<ObjectImage>(base, off, state.key_count);
        state.apply = carve_at<ObjectImage>(base, off, state.key_count);
    }
    if (is_two_hop(state.kind)) state.hop2 = carve_at<uint32_t>(base, off, state.key_count);

    for (uint32_t i = 0; state.groups && i < state.group_cap; i++)
        new (&state.groups[i]) ShardGroup;
    for (uint32_t i = 0; state.keys && i < state.key_count; i++) new (&state.keys[i]) KeyRef;
    if (state.key_order) std::memset(state.key_order, 0, sizeof(uint32_t) * state.key_count);
    for (uint32_t i = 0; state.values && i < state.key_count; i++) new (&state.values[i]) ValueSlot;
    if (state.status) std::memset(state.status, 0, state.key_count);
    if (state.hop2) std::memset(state.hop2, 0, sizeof(uint32_t) * state.key_count);
    for (uint32_t i = 0; state.images && i < state.key_count; i++) new (&state.images[i]) ObjectImage;
    for (uint32_t i = 0; state.apply && i < state.key_count; i++) new (&state.apply[i]) ObjectImage;
}

void reset_groups(ScatterState& state) {
    for (uint32_t i = 0; i < state.group_cap; i++) {
        ShardGroup& group = state.groups[i];
        delete group.aux;
        group = ShardGroup{};
    }
    state.nsub = 0;
}

void build_groups(ScatterState& state, const uint32_t* positions, uint32_t count) {
    uint32_t counts[256] = {};
    for (uint32_t i = 0; i < count; i++) counts[state.keys[positions[i]].shard]++;
    uint32_t cursor = 0;
    for (uint32_t sid = 0; sid < 256; sid++) {
        if (!counts[sid]) continue;
        ShardGroup& group = state.groups[state.nsub++];
        group.shard = static_cast<int32_t>(sid);
        group.begin = cursor;
        group.count = counts[sid];
        cursor += counts[sid];
    }
    uint32_t fill[256] = {};
    for (uint32_t i = 0; i < count; i++) {
        const uint32_t pos = positions[i];
        ShardGroup* group = group_for(state, state.keys[pos].shard);
        state.key_order[group->begin + fill[group->shard]++] = pos;
    }
}

void build_initial_groups(ScatterState& state) {
    uint32_t counts[256] = {};
    for (uint32_t pos = state.phase1_first; pos < state.key_count; pos++)
        counts[state.keys[pos].shard]++;
    uint32_t cursor = 0;
    for (uint32_t sid = 0; sid < 256; sid++) {
        if (!counts[sid]) continue;
        ShardGroup& group = state.groups[state.nsub++];
        group.shard = static_cast<int32_t>(sid);
        group.begin = cursor;
        group.count = counts[sid];
        cursor += counts[sid];
    }
    uint32_t fill[256] = {};
    for (uint32_t pos = state.phase1_first; pos < state.key_count; pos++) {
        ShardGroup* group = group_for(state, state.keys[pos].shard);
        state.key_order[group->begin + fill[group->shard]++] = pos;
    }
}

bool compute_setop(ScatterState& state) {
    ResultHeap* result_heap = ensure_result(state);
    if (!result_heap) { state.final_reply = FinalReply::Work; state.final_error = WorkError::Oom; return false; }
    std::vector<std::vector<std::string>> inputs;
    try {
        inputs.resize(state.set_count);
        for (uint32_t i = 0; i < state.set_count; i++) {
            const ObjectImage& image = state.images[state.set_first + i];
            if (!image_type(image, Type::Set)) {
                state.final_reply = FinalReply::Work;
                state.final_error = WorkError::WrongType;
                return false;
            }
            if (image.present && !decode_elements(image, inputs[i])) {
                state.final_reply = FinalReply::Work;
                state.final_error = WorkError::Oom;
                return false;
            }
        }
        std::unordered_set<std::string> result;
        if (state.kind == Kind::Sunion || state.kind == Kind::Sunionstore) {
            for (const auto& input : inputs) for (const std::string& member : input) result.insert(member);
        } else if (state.kind == Kind::Sdiff || state.kind == Kind::Sdiffstore) {
            if (!inputs.empty()) for (const std::string& member : inputs[0]) result.insert(member);
            for (size_t i = 1; i < inputs.size(); i++)
                for (const std::string& member : inputs[i]) result.erase(member);
        } else {
            if (!inputs.empty()) for (const std::string& member : inputs[0]) result.insert(member);
            for (size_t i = 1; i < inputs.size(); i++) {
                std::unordered_set<std::string> next(inputs[i].begin(), inputs[i].end());
                for (auto it = result.begin(); it != result.end();)
                    if (!next.count(*it)) it = result.erase(it); else ++it;
            }
        }
        result_heap->members.assign(result.begin(), result.end());
    } catch (const std::bad_alloc&) {
        state.final_reply = FinalReply::Work;
        state.final_error = WorkError::Oom;
        return false;
    }
    return true;
}

// True means phase one is terminal. False means hop2[] is complete and ready for one all-or-none
// capacity preflight/publication.
bool finish_phase1(ScatterState& state, Op& op) {
    WorkError error;
    if (first_error(state, error)) {
        state.final_reply = FinalReply::Work; state.final_error = error; return true;
    }

    switch (state.kind) {
        case Kind::Msetnx:
            for (uint32_t i = 0; i < state.key_count; i++)
                if (state.values[i].kind != ValueKind::Nil) {
                    state.final_reply = FinalReply::Integer; state.final_integer = 0; return true;
                }
            state.final_integer = 1;
            state.hop2_count = state.key_count;
            for (uint32_t i = 0; i < state.key_count; i++) state.hop2[i] = i;
            return false;
        case Kind::Rename:
        case Kind::Renamenx: {
            const ObjectImage& source = state.images[0];
            if (!source.present) { state.final_reply = FinalReply::NoSuchKey; return true; }
            if (same_key(op)) {
                state.final_reply = state.kind == Kind::Rename ? FinalReply::Ok : FinalReply::Integer;
                state.final_integer = 0;
                return true;
            }
            if (state.kind == Kind::Renamenx && state.images[1].present) {
                state.final_reply = FinalReply::Integer; state.final_integer = 0; return true;
            }
            try {
                state.apply[1] = source;
                state.apply[0] = ObjectImage{};
            } catch (const std::bad_alloc&) {
                state.final_reply = FinalReply::Work; state.final_error = WorkError::Oom; return true;
            }
            state.final_integer = state.kind == Kind::Renamenx ? 1 : -1;
            state.hop2[0] = 1; state.hop2[1] = 0; state.hop2_count = 2;
            return false;
        }
        case Kind::Copy:
            if (same_key(op)) { state.final_reply = FinalReply::SameObject; return true; }
            if (!state.images[0].present || (state.images[1].present && !state.copy_replace)) {
                state.final_reply = FinalReply::Integer; state.final_integer = 0; return true;
            }
            try { state.apply[1] = state.images[0]; }
            catch (const std::bad_alloc&) {
                state.final_reply = FinalReply::Work; state.final_error = WorkError::Oom; return true;
            }
            state.final_integer = 1; state.hop2[0] = 1; state.hop2_count = 1; return false;
        case Kind::Smove: {
            const ObjectImage& source = state.images[0];
            const ObjectImage& dest = state.images[1];
            if (!source.present) { state.final_reply = FinalReply::Integer; state.final_integer = 0; return true; }
            if (!image_type(source, Type::Set) || !image_type(dest, Type::Set)) {
                state.final_reply = FinalReply::Work; state.final_error = WorkError::WrongType; return true;
            }
            std::vector<std::string> src, dst;
            if (!decode_elements(source, src) || (dest.present && !decode_elements(dest, dst))) {
                state.final_reply = FinalReply::Work; state.final_error = WorkError::Oom; return true;
            }
            const Slice member = op.arg(3);
            if (!contains(src, member)) { state.final_reply = FinalReply::Integer; state.final_integer = 0; return true; }
            if (same_key(op)) { state.final_reply = FinalReply::Integer; state.final_integer = 1; return true; }
            try {
                erase_member(src, member);
                if (!contains(dst, member)) dst.emplace_back(member.p, member.n);
            } catch (const std::bad_alloc&) {
                state.final_reply = FinalReply::Work; state.final_error = WorkError::Oom; return true;
            }
            if (src.empty()) state.apply[0] = ObjectImage{};
            else if (!encode_elements(src, state.apply[0], Type::Set, source.expire_at_ms)) {
                state.final_reply = FinalReply::Work; state.final_error = WorkError::Oom; return true;
            }
            if (!encode_elements(dst, state.apply[1], Type::Set,
                                 dest.present ? dest.expire_at_ms : -1)) {
                state.final_reply = FinalReply::Work; state.final_error = WorkError::Oom; return true;
            }
            state.final_integer = 1; state.hop2[0] = 0; state.hop2[1] = 1; state.hop2_count = 2;
            return false;
        }
        case Kind::Lmove:
        case Kind::Rpoplpush: {
            const ObjectImage& source = state.images[0];
            const ObjectImage& dest = state.images[1];
            if (!source.present) { state.final_reply = FinalReply::Nil; return true; }
            if (!image_type(source, Type::List) || !image_type(dest, Type::List)) {
                state.final_reply = FinalReply::Work; state.final_error = WorkError::WrongType; return true;
            }
            std::vector<std::string> src, dst;
            if (!decode_elements(source, src) || (dest.present && !decode_elements(dest, dst))) {
                state.final_reply = FinalReply::Work; state.final_error = WorkError::Oom; return true;
            }
            if (src.empty()) { state.final_reply = FinalReply::Nil; return true; }
            ResultHeap* result_heap = ensure_result(state);
            if (!result_heap) { state.final_reply = FinalReply::Work; state.final_error = WorkError::Oom; return true; }
            try {
                result_heap->bulk = state.from_left ? src.front() : src.back();
                if (state.from_left) src.erase(src.begin()); else src.pop_back();
                if (same_key(op)) {
                    if (state.to_left) src.insert(src.begin(), result_heap->bulk);
                    else src.push_back(result_heap->bulk);
                    if (!encode_elements(src, state.apply[0], Type::List, source.expire_at_ms))
                        throw std::bad_alloc();
                    state.hop2[0] = 0; state.hop2_count = 1;
                } else {
                    if (state.to_left) dst.insert(dst.begin(), result_heap->bulk);
                    else dst.push_back(result_heap->bulk);
                    if (src.empty()) state.apply[0] = ObjectImage{};
                    else if (!encode_elements(src, state.apply[0], Type::List, source.expire_at_ms))
                        throw std::bad_alloc();
                    if (!encode_elements(dst, state.apply[1], Type::List,
                                         dest.present ? dest.expire_at_ms : -1))
                        throw std::bad_alloc();
                    state.hop2[0] = 0; state.hop2[1] = 1; state.hop2_count = 2;
                }
            } catch (const std::bad_alloc&) {
                state.final_reply = FinalReply::Work; state.final_error = WorkError::Oom; return true;
            }
            return false;
        }
        case Kind::Bitop:
            if (!compute_bitop(state.images, 1, state.key_count - 1, op.arg(1), state.apply[0],
                               state.final_integer, state.final_error)) {
                state.final_reply = FinalReply::Work;
                return true;
            }
            state.hop2[0] = 0;
            state.hop2_count = 1;
            return false;
        default:
            if (is_plain_setop(state.kind) || state.kind == Kind::Sintercard || is_store_setop(state.kind)) {
                if (!compute_setop(state)) return true;
                if (state.kind == Kind::Sintercard) {
                    uint64_t count = state.result->members.size();
                    if (state.sinter_limit && count > state.sinter_limit) count = state.sinter_limit;
                    state.final_reply = FinalReply::Integer;
                    state.final_integer = static_cast<long long>(count);
                    return true;
                }
                if (is_plain_setop(state.kind)) { state.final_reply = FinalReply::Array; return true; }
                if (state.result->members.empty()) state.apply[0] = ObjectImage{};
                else if (!encode_elements(state.result->members, state.apply[0], Type::Set, -1)) {
                    state.final_reply = FinalReply::Work; state.final_error = WorkError::Oom; return true;
                }
                state.final_integer = static_cast<long long>(state.result->members.size());
                state.hop2[0] = 0; state.hop2_count = 1;
                return false;
            }
            state.final_reply = FinalReply::Internal;
            return true;
    }
}

void finish_phase2(ScatterState& state) {
    WorkError error;
    if (first_error(state, error)) {
        state.final_reply = FinalReply::Work; state.final_error = error; return;
    }
    switch (state.kind) {
        case Kind::Msetnx: state.final_reply = FinalReply::Integer; state.final_integer = 1; break;
        case Kind::Rename: state.final_reply = FinalReply::Ok; break;
        case Kind::Renamenx:
        case Kind::Copy:
        case Kind::Smove:
        case Kind::Sinterstore:
        case Kind::Sunionstore:
        case Kind::Sdiffstore: state.final_reply = FinalReply::Integer; break;
        case Kind::Bitop: state.final_reply = FinalReply::Integer; break;
        case Kind::Lmove:
        case Kind::Rpoplpush: state.final_reply = FinalReply::Bulk; break;
        default: state.final_reply = FinalReply::Internal; break;
    }
}

bool publish_phase2(Server& server, ThreadCtx& self, Ring& ring, const Task& task,
                    ScatterState& state) {
    reset_groups(state);
    build_groups(state, state.hop2, state.hop2_count);
    uint32_t needed[kMaxThreads] = {};
    for (uint32_t i = 0; i < state.nsub; i++)
        needed[server.worker_of_shard(state.groups[i].shard)]++;
    for (uint32_t tid = 0; tid < server.nthreads(); tid++)
        if (needed[tid] && server.thread(tid).task_free_slots(self.id()) < needed[tid]) {
            state.final_reply = FinalReply::QueueFull;
            return false;
        }
    state.phase = 2;
    state.pending.store(state.nsub, std::memory_order_release);
    bool notified[kMaxThreads] = {};
    for (uint32_t i = 0; i < state.nsub; i++) {
        const int32_t sid = state.groups[i].shard;
        const uint32_t tid = server.worker_of_shard(sid);
        const Task next{task.client, task.op_id, sid, &state};
        if (!server.thread(tid).post_task_quiet(self.id(), next, self.sig())) std::abort();
        notified[tid] = true;
    }
    for (uint32_t tid = 0; tid < server.nthreads(); tid++)
        if (notified[tid]) server.thread(tid).flush_task_notify(self.id(), ring, self.sig());
    return true;
}

void free_state_contents(ScatterState& state) {
    for (uint32_t i = 0; i < state.group_cap; i++) delete state.groups[i].aux;
    for (uint32_t i = 0; state.images && i < state.key_count; i++) state.images[i].~ObjectImage();
    for (uint32_t i = 0; state.apply && i < state.key_count; i++) state.apply[i].~ObjectImage();
    delete state.result;
}

}  // namespace

ScatterArenaPool::~ScatterArenaPool() {
    for (uint32_t i = 0; i < count_; i++) std::free(cached_[i]);
}

void* ScatterArenaPool::acquire(size_t bytes, bool& pooled) {
    pooled = bytes <= kCommonBytes;
    if (pooled && count_) return cached_[--count_];
    return std::malloc(pooled ? kCommonBytes : bytes);
}

void ScatterArenaPool::release(void* ptr, bool pooled) {
    if (!ptr) return;
    if (pooled && count_ < kCached) cached_[count_++] = ptr;
    else std::free(ptr);
}

ScatterPrepare xshard_prepare(Server& server, Op& op, ScatterArenaPool& pool,
                              uint32_t owner_io, ScatterDispatch& dispatch) {
    const bool all_shards = (op.spec->flags & CmdFlags::AllShards) ||
                            ((op.spec->flags & CmdFlags::ConfigRoute) &&
                             command_config_routes_all_shards(op));
    Kind kind;
    if (all_shards)
        kind = op.cmd_name().eq_icase("dbsize") ? Kind::DbsizeExact : Kind::AllShards;
    else if (!(op.spec->flags & CmdFlags::MultiShard) || !classify(op, kind))
        return ScatterPrepare::NotScatter;

    // The ordinary handlers are already the optimal one-key path.
    if ((kind == Kind::Del || kind == Kind::Unlink || kind == Kind::Exists ||
         kind == Kind::Touch) && op.argc() == 2) return ScatterPrepare::NotScatter;

    if (all_shards) {
        const bool valid = (op.spec->flags & CmdFlags::ConfigRoute)
            ? command_validate_config_set(op) : command_validate_all_shards(op);
        if (!valid) return ScatterPrepare::Error;
    }
    if ((kind == Kind::Mset || kind == Kind::Msetnx) && (op.argc() & 1u) == 0) {
        reply_err(op.sink(), name_is(op, "MSET")
            ? "ERR wrong number of arguments for 'mset' command"
            : "ERR wrong number of arguments for 'msetnx' command");
        return ScatterPrepare::Error;
    }
    if (kind == Kind::Bitop) {
        BitOperation operation;
        if (!bitop_operation(op.arg(1), operation)) {
            reply_syntax(op.sink());
            return ScatterPrepare::Error;
        }
        if (operation == BitOperation::Not && op.argc() != 4) {
            reply_err(op.sink(), "ERR BITOP NOT must be called with a single source key.");
            return ScatterPrepare::Error;
        }
    }

    uint64_t sinter_limit = 0;
    uint32_t sinter_count = 0;
    if (kind == Kind::Sintercard) {
        uint64_t parsed = 0;
        if (!parse_u64(op.arg(1), parsed)) {
            reply_err(op.sink(), "ERR value is not an integer or out of range");
            return ScatterPrepare::Error;
        }
        if (parsed == 0) {
            reply_err(op.sink(), "ERR numkeys should be greater than 0");
            return ScatterPrepare::Error;
        }
        if (parsed > op.argc() - 2) {
            reply_err(op.sink(), "ERR Number of keys can't be greater than number of args");
            return ScatterPrepare::Error;
        }
        sinter_count = static_cast<uint32_t>(parsed);
        const uint32_t tail = 2 + sinter_count;
        if (tail < op.argc()) {
            if (tail + 2 != op.argc() || !op.arg(tail).eq_icase("limit") ||
                !parse_u64(op.arg(tail + 1), sinter_limit)) {
                reply_syntax(op.sink());
                return ScatterPrepare::Error;
            }
        }
    }

    bool copy_replace = false, from_left = false, to_left = false;
    if (kind == Kind::Copy) {
        for (uint32_t i = 3; i < op.argc();) {
            if (op.arg(i).eq_icase("replace")) { copy_replace = true; i++; }
            else if (op.arg(i).eq_icase("db") && i + 1 < op.argc()) {
                uint64_t db = 0;
                if (!parse_u64(op.arg(i + 1), db) || db != 0) {
                    reply_err(op.sink(), "ERR DB index is out of range");
                    return ScatterPrepare::Error;
                }
                i += 2;
            } else {
                reply_syntax(op.sink());
                return ScatterPrepare::Error;
            }
        }
    }
    if (kind == Kind::Lmove) {
        if (!(op.arg(3).eq_icase("left") || op.arg(3).eq_icase("right")) ||
            !(op.arg(4).eq_icase("left") || op.arg(4).eq_icase("right"))) {
            reply_syntax(op.sink());
            return ScatterPrepare::Error;
        }
        from_left = op.arg(3).eq_icase("left");
        to_left = op.arg(4).eq_icase("left");
    } else if (kind == Kind::Rpoplpush) {
        from_left = false; to_left = true;
    }

    const uint32_t key_count = key_count_for(kind, op, sinter_count);
    RouteKey route_stack[kRouteStack];
    RouteKey* routes = route_stack;
    if (key_count > kRouteStack) {
        routes = new (std::nothrow) RouteKey[key_count];
        if (!routes) { set_oom(op); return ScatterPrepare::Error; }
    }
    for (uint32_t i = 0; i < key_count; i++) {
        const uint32_t arg = key_arg_for(kind, i, sinter_count);
        const uint64_t hash = FlatStore::hash_key(op.arg(arg));
        routes[i] = RouteKey{hash, arg, server.router().shard_of(hash)};
    }

    // Every explicit key, including a STORE destination, must agree before taking localfast.
    if (key_count) {
        bool same_owner = true;
        for (uint32_t i = 1; i < key_count; i++) same_owner &= routes[i].shard == routes[0].shard;
        if (same_owner) {
            op.shard = routes[0].shard;
            op.hash = routes[0].hash;
            op.mark_local_xshard();
            if (routes != route_stack) delete[] routes;
            return ScatterPrepare::NotScatter;
        }
    }

    uint32_t phase1_first = (is_store_setop(kind) || kind == Kind::Bitop) ? 1u : 0u;
    uint32_t group_cap = 0;
    if (kind == Kind::AllShards || kind == Kind::DbsizeExact || kind == Kind::Keys) {
        group_cap = server.nshards();
    } else {
        uint8_t seen[256] = {};
        for (uint32_t i = phase1_first; i < key_count; i++)
            if (!seen[routes[i].shard]++) group_cap++;
    }
    const size_t bytes = arena_layout_bytes(kind, key_count, group_cap);
    if (bytes == std::numeric_limits<size_t>::max() || bytes > UINT32_MAX) {
        if (routes != route_stack) delete[] routes;
        set_oom(op);
        return ScatterPrepare::Error;
    }
    bool pooled = false;
    void* memory = pool.acquire(bytes, pooled);
    if (!memory) {
        if (routes != route_stack) delete[] routes;
        set_oom(op);
        return ScatterPrepare::Error;
    }
    auto* state = new (memory) ScatterState;
    state->kind = kind;
    state->barrier = is_two_hop(kind) || all_shards;
    state->pooled = pooled;
    state->owner_io = owner_io;
    state->arena_bytes = static_cast<uint32_t>(bytes);
    state->key_count = key_count;
    state->group_cap = group_cap;
    state->phase1_first = phase1_first;
    state->copy_replace = copy_replace;
    state->from_left = from_left;
    state->to_left = to_left;
    state->sinter_limit = sinter_limit;
    if (kind == Kind::Sintercard) { state->set_first = 0; state->set_count = sinter_count; }
    else if (is_store_setop(kind)) { state->set_first = 1; state->set_count = key_count - 1; }
    else if (is_plain_setop(kind)) { state->set_first = 0; state->set_count = key_count; }
    init_arena_arrays(*state);
    for (uint32_t i = 0; i < key_count; i++)
        state->keys[i] = KeyRef{routes[i].hash, routes[i].arg, routes[i].shard};
    if (routes != route_stack) delete[] routes;

    if (kind == Kind::AllShards || kind == Kind::DbsizeExact || kind == Kind::Keys) {
        state->nsub = server.nshards();
        for (uint32_t sid = 0; sid < state->nsub; sid++) state->groups[sid].shard = sid;
    } else {
        build_initial_groups(*state);
    }
    state->pending.store(state->nsub, std::memory_order_relaxed);
    dispatch.state = state;
    dispatch.nshards = state->nsub;
    dispatch.barrier = state->barrier;
    return ScatterPrepare::Ready;
}

int32_t xshard_dispatch_shard(const ScatterDispatch& dispatch, uint32_t index) {
    return dispatch.state && index < dispatch.state->nsub
        ? dispatch.state->groups[index].shard : -1;
}

void xshard_destroy(ScatterState* state, ScatterArenaPool& pool, uint32_t owner_io) {
    if (!state) return;
    if (state->owner_io != owner_io) std::abort();
    const bool pooled = state->pooled;
    free_state_contents(*state);
    state->~ScatterState();
    pool.release(state, pooled);
}

bool xshard_is_local(const Op& op) { return op.local_xshard(); }

FlatStore::SnapshotWriteResult xshard_local_snapshot_prepare(Op& op, Shard& shard) {
    Kind kind;
    if (!classify(op, kind)) return FlatStore::SnapshotWriteResult::Ready;
    uint32_t count = 0;
    auto arg_at = [&](uint32_t i) -> uint32_t {
        if (kind == Kind::Mset || kind == Kind::Msetnx) return 1 + i * 2;
        if (kind == Kind::Bitop) return 2;
        if (kind == Kind::Copy) return 2;
        if (is_store_setop(kind)) return 1;
        return 1 + i;
    };
    if (kind == Kind::Mset || kind == Kind::Msetnx) count = (op.argc() - 1) / 2;
    else if (kind == Kind::Del || kind == Kind::Unlink) count = op.argc() - 1;
    else if (kind == Kind::Copy || is_store_setop(kind) || kind == Kind::Bitop) count = 1;
    else if (kind == Kind::Rename || kind == Kind::Renamenx || kind == Kind::Smove ||
             kind == Kind::Lmove || kind == Kind::Rpoplpush) count = 2;
    else return FlatStore::SnapshotWriteResult::Ready;

    while (op.zc_len < count) {
        const uint32_t arg = arg_at(op.zc_len);
        const Slice key = op.arg(arg);
        const uint64_t hash = arg == 1 ? op.hash : FlatStore::hash_key(key);
        const auto result = shard.store().snapshot_prepare_write(hash, key);
        if (result != FlatStore::SnapshotWriteResult::Ready) return result;
        op.zc_len++;
    }
    return FlatStore::SnapshotWriteResult::Ready;
}

FlatStore::SnapshotWriteResult xshard_snapshot_prepare(const Task& task, Shard& shard) {
    ScatterState& state = *task.scatter;
    ShardGroup* group_ptr = group_for(state, shard.id());
    if (!group_ptr || !shard.store().snapshot_active()) return FlatStore::SnapshotWriteResult::Ready;
    ShardGroup& group = *group_ptr;

    if (state.phase == 1) {
        if (!(state.kind == Kind::Mset || state.kind == Kind::Del || state.kind == Kind::Unlink)) {
            if (state.kind == Kind::AllShards &&
                (task.client->rob().at(task.op_id).spec->flags & CmdFlags::Write)) {
                try {
                    if (!group.aux) group.aux = new GroupAux;
                    if (!group.aux->flush_keys_built) {
                        shard.store().for_each([&](KvObj* object) {
                            group.aux->flush_keys.emplace_back(object->key().p, object->key().n);
                        });
                        group.aux->flush_keys_built = true;
                    }
                    while (group.snapshot_pos < group.aux->flush_keys.size()) {
                        const std::string& key = group.aux->flush_keys[group.snapshot_pos];
                        const Slice slice(key.data(), static_cast<uint32_t>(key.size()));
                        const auto result = shard.store().snapshot_prepare_write(
                            FlatStore::hash_key(slice), slice);
                        if (result != FlatStore::SnapshotWriteResult::Ready) return result;
                        group.snapshot_pos++;
                    }
                    return FlatStore::SnapshotWriteResult::Ready;
                } catch (const std::bad_alloc&) {
                    return FlatStore::SnapshotWriteResult::Error;
                }
            }
            return FlatStore::SnapshotWriteResult::Ready;
        }
    }

    Op& op = task.client->rob().at(task.op_id);
    while (group.snapshot_pos < group.count) {
        const uint32_t pos = state.key_order[group.begin + group.snapshot_pos];
        const KeyRef& key = state.keys[pos];
        const auto result = shard.store().snapshot_prepare_write(key.hash, op.arg(key.arg));
        if (result != FlatStore::SnapshotWriteResult::Ready) return result;
        group.snapshot_pos++;
    }
    return FlatStore::SnapshotWriteResult::Ready;
}

ScatterTaskResult xshard_execute(const Task& task, Shard& shard, Op& op) {
    ScatterState& state = *task.scatter;
    ShardGroup& group = *group_for(state, shard.id());
    try {
        if (state.phase == 2) {
            for (uint32_t i = 0; i < group.count; i++) {
                const uint32_t pos = state.key_order[group.begin + i];
                const KeyRef& key = state.keys[pos];
                WorkError result;
                if (state.kind == Kind::Msetnx) {
                    result = store_xstring(shard, op.arg(key.arg), key.hash, op.arg(key.arg + 1));
                } else if (state.kind == Kind::Bitop) {
                    const ObjectImage& image = state.apply[pos];
                    if (!image.present) {
                        shard.store().erase(key.hash, op.arg(key.arg));
                        result = WorkError::None;
                    } else {
                        result = store_xstring(
                            shard, op.arg(key.arg), key.hash,
                            Slice(reinterpret_cast<const char*>(image.payload.data()),
                                  static_cast<uint32_t>(image.payload.size())),
                            false);
                    }
                } else {
                    result = apply_image(shard, op.arg(key.arg), key.hash, state.apply[pos]);
                }
                state.status[pos] = static_cast<uint8_t>(result);
            }
            return ScatterTaskResult::Complete;
        }

        switch (state.kind) {
            case Kind::AllShards:
                op.spec->handler(shard, op);
                return ScatterTaskResult::Complete;
            case Kind::DbsizeExact:
                state.exact_sum.fetch_add(shard.store().size(), std::memory_order_relaxed);
                return ScatterTaskResult::Complete;
            case Kind::Mget:
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    KvObj* object = shard.store().find(key.hash, op.arg(key.arg));
                    if (!object || static_cast<Type>(object->type) != Type::String) continue;
                    ValueSlot& slot = state.values[pos];
                    if (object->is_int()) {
                        slot.len = i64_to_dec(slot.small, object->int_value());
                        slot.kind = ValueKind::Inline;
                    } else {
                        const Slice value = object->str_value();
                        slot.len = value.n;
                        if (value.n <= ValueSlot::kInline) {
                            if (value.n) std::memcpy(slot.small, value.p, value.n);
                            slot.kind = ValueKind::Inline;
                        } else {
                            shard.store().borrow(value.p);
                            slot.ptr = value.p;
                            slot.shard = shard.id();
                            slot.kind = ValueKind::Borrow;
                        }
                    }
                }
                return ScatterTaskResult::Complete;
            case Kind::Mset:
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    state.status[pos] = static_cast<uint8_t>(
                        store_xstring(shard, op.arg(key.arg), key.hash, op.arg(key.arg + 1)));
                }
                return ScatterTaskResult::Complete;
            case Kind::Del:
            case Kind::Unlink:
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    state.status[pos] = shard.store().erase(key.hash, op.arg(key.arg));
                }
                return ScatterTaskResult::Complete;
            case Kind::Exists:
            case Kind::Touch:
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    state.status[pos] = shard.store().find(key.hash, op.arg(key.arg)) != nullptr;
                }
                return ScatterTaskResult::Complete;
            case Kind::Keys: {
                if (!group.aux) group.aux = new GroupAux;
                const Slice pattern = op.arg(1);
                group.scan_cursor = shard.store().scan(group.scan_cursor, 256, [&](KvObj* object) {
                    const Slice key = object->key();
                    if (glob_match(pattern.p, pattern.n, key.p, key.n))
                        group.aux->keys_result.emplace_back(key.p, key.n);
                });
                return group.scan_cursor ? ScatterTaskResult::Retry : ScatterTaskResult::Complete;
            }
            case Kind::Msetnx:
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    if (shard.store().find(key.hash, op.arg(key.arg)))
                        state.values[pos].kind = ValueKind::Inline;
                }
                return ScatterTaskResult::Complete;
            default:
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    KvObj* object = shard.store().find(key.hash, op.arg(key.arg));
                    if (!serialize_object(object, state.images[pos])) {
                        state.status[pos] = static_cast<uint8_t>(WorkError::Oom);
                        break;
                    }
                }
                return ScatterTaskResult::Complete;
        }
    } catch (const std::bad_alloc&) {
        group.error = WorkError::Oom;
        return ScatterTaskResult::Complete;
    }
}

ScatterFinish xshard_complete(Server& server, ThreadCtx& self, Ring& ring,
                              const Task& task, Op& op) {
    ScatterState& state = *task.scatter;
    if (state.pending.fetch_sub(1, std::memory_order_acq_rel) != 1)
        return ScatterFinish::Waiting;
    if (state.phase == 2) {
        finish_phase2(state);
        return ScatterFinish::Final;
    }
    if (!is_two_hop(state.kind)) return ScatterFinish::Final;
    if (finish_phase1(state, op)) return ScatterFinish::Final;
    return publish_phase2(server, self, ring, task, state)
        ? ScatterFinish::Waiting : ScatterFinish::Final;
}

namespace {

void assemble_mget(Client& client, Op& op, ScatterState& state) {
    bool borrowed = false;
    for (uint32_t i = 0; i < state.key_count; i++)
        borrowed |= state.values[i].kind == ValueKind::Borrow;
    if (!borrowed) {
        reply_array_header(op.sink(), state.key_count);
        for (uint32_t i = 0; i < state.key_count; i++) {
            const ValueSlot& slot = state.values[i];
            if (slot.kind == ValueKind::Nil) reply_nil(op.sink());
            else reply_bulk(op.sink(), Slice(slot.small, slot.len));
        }
        return;
    }

    client.seal_fill_segment();
    auto flush_bytes = [&] {
        client.append_buf_segment(op.direct, op.direct_len, op.reply.data(), op.reply.size());
        op.direct_len = 0;
        op.reply.clear();
    };
    reply_array_header(op.sink(), state.key_count);
    for (uint32_t i = 0; i < state.key_count; i++) {
        ValueSlot& slot = state.values[i];
        if (slot.kind == ValueKind::Nil) reply_nil(op.sink());
        else if (slot.kind == ValueKind::Inline) reply_bulk(op.sink(), Slice(slot.small, slot.len));
        else {
            reply_bulk_header(op.sink(), slot.len);
            flush_bytes();
            client.append_borrow_segment(slot.ptr, slot.len, slot.shard);
            static constexpr char crlf[2] = {'\r', '\n'};
            client.append_static_segment(crlf, sizeof(crlf));
            // Ownership moved to the connection queue. Arena teardown must not return it again.
            slot.kind = ValueKind::Nil;
        }
    }
}

void assemble_final(Client& client, Op& op, ScatterState& state) {
    if (state.final_reply != FinalReply::None) {
        switch (state.final_reply) {
            case FinalReply::Ok: reply_ok(op.sink()); break;
            case FinalReply::Integer: reply_int(op.sink(), state.final_integer); break;
            case FinalReply::Nil: reply_nil(op.sink()); break;
            case FinalReply::Bulk:
                reply_bulk(op.sink(), Slice(state.result->bulk.data(),
                                            static_cast<uint32_t>(state.result->bulk.size())));
                break;
            case FinalReply::Array:
                reply_array_header(op.sink(), state.result->members.size());
                for (const std::string& member : state.result->members)
                    reply_bulk(op.sink(), Slice(member.data(), static_cast<uint32_t>(member.size())));
                break;
            case FinalReply::Work: reply_work_error(op, state.final_error); break;
            case FinalReply::NoSuchKey: reply_err(op.sink(), "ERR no such key"); break;
            case FinalReply::SameObject:
                reply_err(op.sink(), "ERR source and destination objects are the same"); break;
            case FinalReply::QueueFull:
                reply_err(op.sink(), "ERR cross-shard second hop queue is full"); break;
            case FinalReply::Internal:
                reply_err(op.sink(), "ERR internal cross-shard completion error"); break;
            case FinalReply::None: break;
        }
        return;
    }

    WorkError error;
    if (first_error(state, error)) { reply_work_error(op, error); return; }
    switch (state.kind) {
        case Kind::AllShards: reply_ok(op.sink()); break;
        case Kind::DbsizeExact:
            reply_int(op.sink(), static_cast<long long>(state.exact_sum.load(std::memory_order_relaxed)));
            break;
        case Kind::Mget: assemble_mget(client, op, state); break;
        case Kind::Mset: reply_ok(op.sink()); break;
        case Kind::Del:
        case Kind::Unlink:
        case Kind::Exists:
        case Kind::Touch: {
            uint64_t count = 0;
            for (uint32_t i = 0; i < state.key_count; i++) count += state.status[i] != 0;
            reply_int(op.sink(), static_cast<long long>(count));
            break;
        }
        case Kind::Keys: {
            uint64_t count = 0;
            for (uint32_t i = 0; i < state.nsub; i++)
                if (state.groups[i].aux) count += state.groups[i].aux->keys_result.size();
            reply_array_header(op.sink(), count);
            for (uint32_t i = 0; i < state.nsub; i++)
                if (state.groups[i].aux)
                    for (const std::string& key : state.groups[i].aux->keys_result)
                        reply_bulk(op.sink(), Slice(key.data(), static_cast<uint32_t>(key.size())));
            break;
        }
        default: reply_err(op.sink(), "ERR internal cross-shard completion error"); break;
    }
}

}  // namespace

void xshard_retire(Client& client, Op& op, ScatterArenaPool& pool, uint32_t owner_io,
                   void* release_ctx, void (*release_fn)(void*, int32_t, const char*)) {
    ScatterState* state = op.scatter_state();
    if (!state) return;
    assemble_final(client, op, *state);
    // A terminal error can bypass normal MGET assembly. Return any already-gathered borrows through
    // the same IO->owner channel used by send completion and teardown.
    if (state->kind == Kind::Mget && state->values) {
        for (uint32_t i = 0; i < state->key_count; i++) {
            ValueSlot& slot = state->values[i];
            if (slot.kind == ValueKind::Borrow && release_fn) {
                release_fn(release_ctx, slot.shard, slot.ptr);
                slot.kind = ValueKind::Nil;
            }
        }
    }
    op.detach_scatter_state();
    xshard_destroy(state, pool, owner_io);
}

namespace {

bool compute_local_setop(Kind kind, const std::vector<ObjectImage>& images, uint32_t first,
                         uint32_t count, std::vector<std::string>& members, WorkError& error) {
    std::vector<std::vector<std::string>> inputs;
    try {
        inputs.resize(count);
        for (uint32_t i = 0; i < count; i++) {
            const ObjectImage& image = images[first + i];
            if (!image_type(image, Type::Set)) { error = WorkError::WrongType; return false; }
            if (image.present && !decode_elements(image, inputs[i])) { error = WorkError::Oom; return false; }
        }
        std::unordered_set<std::string> result;
        if (kind == Kind::Sunion || kind == Kind::Sunionstore) {
            for (const auto& input : inputs) for (const std::string& member : input) result.insert(member);
        } else if (kind == Kind::Sdiff || kind == Kind::Sdiffstore) {
            if (!inputs.empty()) for (const std::string& member : inputs[0]) result.insert(member);
            for (size_t i = 1; i < inputs.size(); i++)
                for (const std::string& member : inputs[i]) result.erase(member);
        } else {
            if (!inputs.empty()) for (const std::string& member : inputs[0]) result.insert(member);
            for (size_t i = 1; i < inputs.size(); i++) {
                std::unordered_set<std::string> next(inputs[i].begin(), inputs[i].end());
                for (auto it = result.begin(); it != result.end();)
                    if (!next.count(*it)) it = result.erase(it); else ++it;
            }
        }
        members.assign(result.begin(), result.end());
        return true;
    } catch (const std::bad_alloc&) {
        error = WorkError::Oom;
        return false;
    }
}

void local_apply(Shard& shard, Op& op, const std::vector<ObjectImage>& apply,
                 const std::vector<uint32_t>& args, WorkError& error) {
    for (uint32_t arg : args) {
        const WorkError result = apply_image(shard, op.arg(arg), FlatStore::hash_key(op.arg(arg)), apply[arg]);
        if (error == WorkError::None && result != WorkError::None) error = result;
    }
}

}  // namespace

void cmd_xshard_only(Shard& shard, Op& op) {
    if (!op.local_xshard()) {
        reply_err(op.sink(), "ERR internal cross-shard routing error");
        return;
    }
    Kind kind;
    if (!classify(op, kind)) { reply_err(op.sink(), "ERR internal cross-shard routing error"); return; }

    if (kind == Kind::Mget) {
        reply_array_header(op.sink(), op.argc() - 1);
        for (uint32_t arg = 1; arg < op.argc(); arg++) {
            const uint64_t hash = arg == 1 ? op.hash : FlatStore::hash_key(op.arg(arg));
            KvObj* object = shard.store().find(hash, op.arg(arg));
            if (!object || static_cast<Type>(object->type) != Type::String) { reply_nil(op.sink()); continue; }
            if (object->is_int()) {
                char integer[24];
                const uint32_t n = i64_to_dec(integer, object->int_value());
                reply_bulk(op.sink(), Slice(integer, n));
            } else reply_bulk(op.sink(), object->str_value());
        }
        return;
    }
    if (kind == Kind::Mset || kind == Kind::Msetnx) {
        if (kind == Kind::Msetnx) {
            for (uint32_t arg = 1; arg < op.argc(); arg += 2)
                if (shard.store().find(FlatStore::hash_key(op.arg(arg)), op.arg(arg))) {
                    reply_int(op.sink(), 0); return;
                }
        }
        WorkError error = WorkError::None;
        for (uint32_t arg = 1; arg < op.argc(); arg += 2) {
            const WorkError result = store_xstring(shard, op.arg(arg), FlatStore::hash_key(op.arg(arg)),
                                                   op.arg(arg + 1));
            if (error == WorkError::None && result != WorkError::None) error = result;
        }
        if (error != WorkError::None) reply_work_error(op, error);
        else if (kind == Kind::Mset) reply_ok(op.sink());
        else reply_int(op.sink(), 1);
        return;
    }

    std::vector<ObjectImage> images, apply;
    try { images.resize(op.argc()); apply.resize(op.argc()); }
    catch (const std::bad_alloc&) { set_oom(op); return; }
    uint32_t gather_first = kind == Kind::Bitop ? 3 :
                            is_store_setop(kind) ? 2 :
                            kind == Kind::Sintercard ? 2 : 1;
    uint32_t gather_end = op.argc();
    if (kind == Kind::Rename || kind == Kind::Renamenx || kind == Kind::Copy ||
        kind == Kind::Smove || kind == Kind::Lmove || kind == Kind::Rpoplpush)
        gather_end = 3;
    if (kind == Kind::Sintercard) {
        uint64_t n = 0; parse_u64(op.arg(1), n); gather_end = 2 + static_cast<uint32_t>(n);
    }
    for (uint32_t arg = gather_first; arg < gather_end; arg++) {
        KvObj* object = shard.store().find(FlatStore::hash_key(op.arg(arg)), op.arg(arg));
        if (!serialize_object(object, images[arg])) { set_oom(op); return; }
    }
    WorkError error = WorkError::None;
    if (kind == Kind::Rename || kind == Kind::Renamenx) {
        if (!images[1].present) { reply_err(op.sink(), "ERR no such key"); return; }
        if (same_key(op)) { if (kind == Kind::Rename) reply_ok(op.sink()); else reply_int(op.sink(), 0); return; }
        if (kind == Kind::Renamenx && images[2].present) { reply_int(op.sink(), 0); return; }
        try { apply[2] = images[1]; apply[1] = ObjectImage{}; }
        catch (const std::bad_alloc&) { set_oom(op); return; }
        local_apply(shard, op, apply, {2, 1}, error);
        if (error != WorkError::None) reply_work_error(op, error);
        else if (kind == Kind::Rename) reply_ok(op.sink()); else reply_int(op.sink(), 1);
        return;
    }
    if (kind == Kind::Copy) {
        if (same_key(op)) { reply_err(op.sink(), "ERR source and destination objects are the same"); return; }
        bool replace = false;
        for (uint32_t i = 3; i < op.argc(); i++) if (op.arg(i).eq_icase("replace")) replace = true;
        if (!images[1].present || (images[2].present && !replace)) { reply_int(op.sink(), 0); return; }
        try { apply[2] = images[1]; } catch (const std::bad_alloc&) { set_oom(op); return; }
        local_apply(shard, op, apply, {2}, error);
        if (error != WorkError::None) reply_work_error(op, error); else reply_int(op.sink(), 1);
        return;
    }
    if (kind == Kind::Smove) {
        if (!images[1].present) { reply_int(op.sink(), 0); return; }
        if (!image_type(images[1], Type::Set) || !image_type(images[2], Type::Set)) {
            reply_wrongtype(op.sink()); return;
        }
        std::vector<std::string> src, dst;
        if (!decode_elements(images[1], src) || (images[2].present && !decode_elements(images[2], dst))) {
            set_oom(op); return;
        }
        if (!contains(src, op.arg(3))) { reply_int(op.sink(), 0); return; }
        if (same_key(op)) { reply_int(op.sink(), 1); return; }
        try { erase_member(src, op.arg(3)); if (!contains(dst, op.arg(3))) dst.emplace_back(op.arg(3).p, op.arg(3).n); }
        catch (const std::bad_alloc&) { set_oom(op); return; }
        if (src.empty()) apply[1] = ObjectImage{};
        else if (!encode_elements(src, apply[1], Type::Set, images[1].expire_at_ms)) { set_oom(op); return; }
        if (!encode_elements(dst, apply[2], Type::Set, images[2].present ? images[2].expire_at_ms : -1)) {
            set_oom(op); return;
        }
        local_apply(shard, op, apply, {1, 2}, error);
        if (error != WorkError::None) reply_work_error(op, error); else reply_int(op.sink(), 1);
        return;
    }
    if (kind == Kind::Lmove || kind == Kind::Rpoplpush) {
        if (!images[1].present) { reply_nil(op.sink()); return; }
        if (!image_type(images[1], Type::List) || !image_type(images[2], Type::List)) {
            reply_wrongtype(op.sink()); return;
        }
        std::vector<std::string> src, dst;
        if (!decode_elements(images[1], src) || (images[2].present && !decode_elements(images[2], dst))) {
            set_oom(op); return;
        }
        if (src.empty()) { reply_nil(op.sink()); return; }
        const bool from_left = kind == Kind::Lmove ? op.arg(3).eq_icase("left") : false;
        const bool to_left = kind == Kind::Lmove ? op.arg(4).eq_icase("left") : true;
        std::string moved = from_left ? src.front() : src.back();
        if (from_left) src.erase(src.begin()); else src.pop_back();
        if (same_key(op)) {
            if (to_left) src.insert(src.begin(), moved); else src.push_back(moved);
            if (!encode_elements(src, apply[1], Type::List, images[1].expire_at_ms)) { set_oom(op); return; }
            local_apply(shard, op, apply, {1}, error);
        } else {
            if (to_left) dst.insert(dst.begin(), moved); else dst.push_back(moved);
            if (src.empty()) apply[1] = ObjectImage{};
            else if (!encode_elements(src, apply[1], Type::List, images[1].expire_at_ms)) { set_oom(op); return; }
            if (!encode_elements(dst, apply[2], Type::List, images[2].present ? images[2].expire_at_ms : -1)) {
                set_oom(op); return;
            }
            local_apply(shard, op, apply, {1, 2}, error);
        }
        if (error != WorkError::None) reply_work_error(op, error);
        else reply_bulk(op.sink(), Slice(moved.data(), static_cast<uint32_t>(moved.size())));
        return;
    }
    if (kind == Kind::Bitop) {
        ObjectImage output;
        long long output_length = 0;
        if (!compute_bitop(images.data(), 3, op.argc() - 3, op.arg(1), output,
                           output_length, error)) {
            reply_work_error(op, error);
            return;
        }
        const Slice destination = op.arg(2);
        const uint64_t hash = FlatStore::hash_key(destination);
        if (!output.present) {
            shard.store().erase(hash, destination);
        } else {
            error = store_xstring(
                shard, destination, hash,
                Slice(reinterpret_cast<const char*>(output.payload.data()),
                      static_cast<uint32_t>(output.payload.size())),
                false);
        }
        if (error != WorkError::None) reply_work_error(op, error);
        else reply_int(op.sink(), output_length);
        return;
    }
    if (is_plain_setop(kind) || kind == Kind::Sintercard || is_store_setop(kind)) {
        uint32_t first = is_store_setop(kind) ? 2 : kind == Kind::Sintercard ? 2 : 1;
        uint32_t count = 0;
        if (kind == Kind::Sintercard) { uint64_t parsed = 0; parse_u64(op.arg(1), parsed); count = parsed; }
        else count = op.argc() - first;
        std::vector<std::string> members;
        if (!compute_local_setop(kind, images, first, count, members, error)) {
            reply_work_error(op, error); return;
        }
        if (kind == Kind::Sintercard) {
            uint64_t limit = 0;
            const uint32_t tail = first + count;
            if (tail < op.argc()) parse_u64(op.arg(tail + 1), limit);
            uint64_t result = members.size();
            if (limit && result > limit) result = limit;
            reply_int(op.sink(), static_cast<long long>(result));
            return;
        }
        if (is_plain_setop(kind)) {
            reply_array_header(op.sink(), members.size());
            for (const std::string& member : members)
                reply_bulk(op.sink(), Slice(member.data(), static_cast<uint32_t>(member.size())));
            return;
        }
        if (members.empty()) apply[1] = ObjectImage{};
        else if (!encode_elements(members, apply[1], Type::Set, -1)) { set_oom(op); return; }
        local_apply(shard, op, apply, {1}, error);
        if (error != WorkError::None) reply_work_error(op, error);
        else reply_int(op.sink(), static_cast<long long>(members.size()));
        return;
    }
    reply_err(op.sink(), "ERR internal cross-shard completion error");
}

}  // namespace tomo
