// scatter_engine.inc — arena-backed scatter/gather state and execution engine.
//
// This file is textually included by xshard.cc. It deliberately remains part of that one
// translation unit and shares its anonymous namespace; there are no new external symbols or
// build-system inputs.

#line 34 "src/cmd/xshard.cc"

namespace tomo {
namespace {
enum class Kind : uint8_t {
    AllShards, DbsizeExact, Mget, Mset, Del, Unlink, Exists, Touch, Keys, Pfcount, Msetnx,
    Rename, Renamenx, Copy, Smove, Lmove, Rpoplpush,
    Sinter, Sunion, Sdiff, Sintercard, Sinterstore, Sunionstore, Sdiffstore,
    Bitop, Pfmerge,
    Lmpop, Zmpop, Zrangestore, Sort,
};

enum class BitOperation : uint8_t { And, Or, Xor, Not };

enum class WorkError : uint8_t {
    None, WrongType, BadHll, CorruptHll, Oom, Maxmemory, InsertFailed, Corrupt
};
enum class FinalReply : uint8_t {
    None, Ok, Integer, Nil, NullArray, Bulk, Array, Lmpop, Zmpop, SortConversion,
    Work, NoSuchKey, SameObject, QueueFull, Internal
};
enum class ValueKind : uint8_t { Nil, Inline, Borrow };

struct ObjectImage {
    bool present = false;
    Type type = Type::String;
    uint8_t encoding = 0;
    uint32_t entries = 0;
    int64_t expire_at_ms = -1;
    std::vector<uint8_t> payload;
};

// Integers are at most 20 bytes including the sign.  Tiny raw strings use the same inline lane;
// anything larger is cheaper to retain through FlatStore's existing borrow registry.
struct ValueSlot {
    // Inline-copy cutover for gathered values. 24 was sized for integers; at 64B-class values it
    // pushed EVERY gather through the borrow path, whose bookkeeping (registry entry + segment
    // iov + release round-trip through the owner channel) costs more than a small memcpy — the
    // fork copies once at reassembly for exactly this reason (its OPT-1 keeps refs, but its
    // values cross as one copy into the reply). Borrow now reserves for genuinely large values
    // where wire zero-copy pays, mirroring the zc-min philosophy on the single-shard path.
    static constexpr uint32_t kInline = 1024;
    const char* ptr = nullptr;
    uint32_t len = 0;
    int32_t shard = -1;
    ValueKind kind = ValueKind::Nil;
    // Deliberately UNINITIALIZED: placement-new value-init was zeroing kInline bytes per slot per
    // op (8KB of memset per MGET-8 at the 1KB slot -- measured -34% at 64B values). Only the first
    // `len` bytes are ever written and read.
    char small[kInline];
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
    uint64_t membership = 0;
    uint32_t snapshot_pos = 0;
    uint64_t scan_cursor = 0;
    WorkError error = WorkError::None;
    GroupAux* aux = nullptr;                 // KEYS / capture-safe FLUSH only
};

struct KeyRef {
    uint64_t hash = 0;
    uint32_t arg = 0;
    int32_t shard = -1;
    KvObj* stable_object = nullptr;          // entry key identity; never copied into the entry
    KvObj* key_anchor = nullptr;             // rare absent-DEL identity, freed with ScatterState
};

struct ResultHeap {
    std::string bulk;
    std::vector<std::string> members;
    std::vector<double> scores;
};

struct RouteKey {
    uint64_t hash = 0;
    uint32_t arg = 0;
    int32_t shard = -1;
};

constexpr uint32_t kRouteStack = 32;

enum class ImageRangeKind : uint8_t { Rank, Score, Lex };

struct ImageRangeOptions {
    ImageRangeKind kind = ImageRangeKind::Rank;
    bool reverse = false;
    bool limit_seen = false;
    int64_t offset = 0;
    int64_t limit = -1;
};

struct SortOptions {
    bool alpha = false;
    bool descending = false;
    bool store = false;
    uint32_t store_arg = 0;
    int64_t offset = 0;
    int64_t count = -1;
};

struct ImageScoreRange {
    double min = 0;
    double max = 0;
    bool min_exclusive = false;
    bool max_exclusive = false;
};

enum class ImageInfinity : int8_t { Minus = -1, Finite = 0, Plus = 1 };
struct ImageLexBound {
    ImageInfinity infinity = ImageInfinity::Finite;
    Slice value;
    bool exclusive = false;
};
struct ImageLexRange { ImageLexBound min, max; };

struct ImageRangeSpec {
    int64_t rank_start = 0;
    int64_t rank_stop = 0;
    ImageScoreRange score;
    ImageLexRange lex;
};

bool is_two_hop(Kind kind) { return kind >= Kind::Msetnx; }
bool is_store_setop(Kind kind) {
    return kind == Kind::Sinterstore || kind == Kind::Sunionstore ||
           kind == Kind::Sdiffstore;
}
bool is_plain_setop(Kind kind) {
    return kind == Kind::Sinter || kind == Kind::Sunion || kind == Kind::Sdiff;
}
bool is_atomic_write_kind(Kind kind) {
    return kind == Kind::Mset || kind == Kind::Msetnx || kind == Kind::Del ||
           kind == Kind::Unlink;
}

bool is_atomic_apply_kind(Kind kind, bool sort_store) {
    return kind == Kind::Bitop || kind == Kind::Pfmerge ||
           kind == Kind::Rename || kind == Kind::Renamenx || kind == Kind::Copy ||
           kind == Kind::Smove || kind == Kind::Lmove || kind == Kind::Rpoplpush ||
           is_store_setop(kind) || kind == Kind::Zrangestore ||
           (kind == Kind::Sort && sort_store);
}

bool is_atomic_pop_kind(Kind kind) {
    return kind == Kind::Lmpop || kind == Kind::Zmpop;
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
    if (image.type != Type::String) image.entries = CollectionRef(object).entries();
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
                        int64_t expire_at_ms = -1, bool integer_encode = true) {
    switch (xshard_store_string(shard, key, hash, value, expire_at_ms, integer_encode)) {
        case XshardStringStoreResult::Stored: return WorkError::None;
        case XshardStringStoreResult::Oom: return WorkError::Oom;
        case XshardStringStoreResult::Maxmemory: return WorkError::Maxmemory;
        case XshardStringStoreResult::InsertFailed: return WorkError::InsertFailed;
    }
    return WorkError::InsertFailed;
}

}  // namespace

struct alignas(64) OwnerRecordRefs {
    // A slot is touched only by its executor: every shard mapped to one owner is serialized there.
    // Cache-line spacing prevents cleanup on distinct owners from bouncing a shared counter line.
    uint32_t nodes = 0;
    uint32_t remaining = 0;
    uint32_t group_count = 0;
};

struct ScatterState {
    std::atomic<uint32_t> pending{0};
    // Zero means installs are still private. The last owner draws and release-publishes the ticket;
    // pending group entries may retain this state after reply retirement, hence record_refs.
    std::atomic<uint64_t> epoch{0};
    std::atomic<uint32_t> record_refs{0};
    std::atomic<bool> aborted{false};
    std::atomic<bool> conditional_failed{false};
    std::atomic<uint8_t> direct_ready{0};     // 0=source pending, 1=image ready, 2=terminal
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
    bool pop_edge = false;                 // RIGHT for LMPOP, MAX for ZMPOP
    bool atomic_write = false;
    bool atomic_apply = false;
    bool atomic_pop = false;
    bool atomic_group = false;
    bool atomic_direct = false;
    bool pop_missed = false;
    bool admitted = false;
    bool snapshot_registered = false;
    std::atomic<bool> snapshot_complete{false};
    bool contents_freed = false;
    bool retired = false;
    bool two_hop = false;
    uint32_t owner_io = 0;
    uint32_t owner_slots = 0;
    uint64_t admission_generation = 0;
    uint64_t origin_conn_id = 0;
    Server* server = nullptr;
    uint32_t arena_bytes = 0;
    uint32_t key_count = 0;
    uint32_t nsub = 0;
    uint32_t group_cap = 0;
    uint32_t shard_slots = 0;
    uint32_t phase1_first = 0;
    uint32_t set_first = 0;
    uint32_t set_count = 0;
    uint32_t hop2_count = 0;
    uint32_t selected = std::numeric_limits<uint32_t>::max();
    uint32_t pop_retries = 0;
    uint32_t snapshot_slot = std::numeric_limits<uint32_t>::max(); // owning IO's unresolved set
    uint64_t sinter_limit = 0;
    uint64_t pop_count = 1;
    uint64_t snapshot = UINT64_MAX;
    uint64_t pop_retry_snapshot = UINT64_MAX;
    long long final_integer = 0;
    ImageRangeOptions range_options;
    ImageRangeSpec range_spec;
    SortOptions sort_options;
    ShardGroup* groups = nullptr;
    KeyRef* keys = nullptr;
    uint32_t* key_order = nullptr;
    ValueSlot* values = nullptr;
    uint8_t* status = nullptr;
    ObjectImage* images = nullptr;
    ObjectImage* apply = nullptr;
    uint32_t* hop2 = nullptr;
    uint16_t* shard_groups = nullptr;
    OwnerRecordRefs* owner_record_refs = nullptr;
    ResultHeap* result = nullptr;
};

static_assert(sizeof(ScatterState) + 8 * (sizeof(ShardGroup) + sizeof(KeyRef) +
                                           sizeof(uint32_t) + sizeof(ValueSlot)) <= 16384,
              "MGET-8 ScatterState no longer fits ScatterArenaPool::kCommonBytes");

namespace {

ShardGroup* group_for(ScatterState& state, int32_t shard) {
    if (state.shard_groups) {
        if (shard < 0 || static_cast<uint32_t>(shard) >= state.shard_slots) return nullptr;
        const uint16_t index = state.shard_groups[static_cast<uint32_t>(shard)];
        return index == UINT16_MAX || index >= state.nsub ? nullptr : &state.groups[index];
    }
    for (uint32_t i = 0; i < state.nsub; i++)
        if (state.groups[i].shard == shard) return &state.groups[i];
    return nullptr;
}

ResultHeap* ensure_result(ScatterState& state) {
    if (!state.result) state.result = new (std::nothrow) ResultHeap;
    return state.result;
}

// Whole-function moves put the engine before command and atomic helpers in the concatenation.
// These internal declarations preserve the original signatures and anonymous-namespace linkage.
bool name_is(const Op& op, const char* name);
bool parse_u64(Slice s, uint64_t& value);
bool parse_mpop(Op& op, Kind kind, uint32_t& numkeys, bool& edge, uint64_t& count);
bool parse_zrangestore_options(Op& op, ImageRangeOptions& options);
bool parse_zrangestore_range(Op& op, const ImageRangeOptions& options, ImageRangeSpec& range);
bool parse_sort_options(Op& op, SortOptions& options);
void set_oom(Op& op);
bool classify(const Op& op, Kind& kind);
bool bitop_operation(Slice name, BitOperation& operation);
bool glob_match(const char* pattern, size_t pn, const char* text, size_t tn);
WorkError begin_plain_version(Server& server, Shard& shard, Slice key, uint64_t hash,
                              uint64_t snapshot, uint64_t origin_conn_id);
ScatterTaskResult execute_atomic_apply(const Task& task, Shard& shard, Op& op,
                                       uint32_t owner_thread_id);
ScatterTaskResult execute_atomic_direct_rename(const Task& task, Shard& shard, Op& op,
                                               uint32_t owner_thread_id);
void finish_pfcount(ScatterState& state);
bool finish_phase1(ScatterState& state, Op& op);
void finish_phase2(ScatterState& state);
void assemble_final(Client& client, Op& op, ScatterState& state);

bool first_error(const ScatterState& state, WorkError& error) {
    for (uint32_t gi = 0; gi < state.nsub; gi++) {
        const ShardGroup& group = state.groups[gi];
        if (group.error != WorkError::None) { error = group.error; return true; }
        if (!state.status || !(state.kind == Kind::Mset || state.kind == Kind::Pfcount ||
                               is_two_hop(state.kind))) continue;
        for (uint32_t i = 0; i < group.count; i++) {
            const WorkError value = static_cast<WorkError>(state.status[state.key_order[group.begin + i]]);
            if (value != WorkError::None) { error = value; return true; }
        }
    }
    return false;
}

uint32_t key_count_for(Kind kind, const Op& op, uint32_t sinter_count,
                       uint32_t mpop_count, bool sort_store) {
    if (kind == Kind::AllShards || kind == Kind::DbsizeExact || kind == Kind::Keys) return 0;
    if (kind == Kind::Mset || kind == Kind::Msetnx) return (op.argc() - 1) / 2;
    if (kind == Kind::Bitop) return op.argc() - 2;
    if (kind == Kind::Rename || kind == Kind::Renamenx || kind == Kind::Copy ||
        kind == Kind::Smove || kind == Kind::Lmove || kind == Kind::Rpoplpush) return 2;
    if (kind == Kind::Sintercard) return sinter_count;
    if (kind == Kind::Lmpop || kind == Kind::Zmpop) return mpop_count;
    if (kind == Kind::Zrangestore) return 2;
    if (kind == Kind::Sort) return sort_store ? 2 : 1;
    return op.argc() - 1;
}

uint32_t key_arg_for(Kind kind, uint32_t key, uint32_t, uint32_t sort_store_arg) {
    if (kind == Kind::Mset || kind == Kind::Msetnx) return 1 + key * 2;
    if (kind == Kind::Bitop) return 2 + key;
    if (kind == Kind::Sintercard) return 2 + key;
    if (kind == Kind::Lmpop || kind == Kind::Zmpop) return 2 + key;
    if (kind == Kind::Sort && sort_store_arg) return key == 0 ? sort_store_arg : 1;
    return 1 + key;
}

bool has_values(Kind kind, bool atomic_write) {
    return kind == Kind::Mget || (kind == Kind::Msetnx && !atomic_write);
}
bool has_status(Kind kind, bool atomic_write) {
    if (atomic_write && (kind == Kind::Mset || kind == Kind::Msetnx)) return false;
    return kind == Kind::Mset || kind == Kind::Del || kind == Kind::Unlink ||
           kind == Kind::Exists || kind == Kind::Touch || kind == Kind::Pfcount ||
           is_two_hop(kind);
}
bool has_images(Kind kind) {
    return kind == Kind::Pfcount || (is_two_hop(kind) && kind != Kind::Msetnx);
}

size_t arena_layout_bytes(Kind kind, uint32_t key_count, uint32_t group_cap,
                          uint32_t shard_slots, bool atomic_write, bool atomic_apply,
                          uint32_t owner_slots) {
    const bool atomic_install = atomic_write || atomic_apply;
    size_t off = sizeof(ScatterState);
    carve_size<ShardGroup>(off, group_cap);
    carve_size<KeyRef>(off, key_count);
    carve_size<uint32_t>(off, key_count);             // key_order
    if (has_values(kind, atomic_write)) carve_size<ValueSlot>(off, key_count);
    if (has_status(kind, atomic_write)) carve_size<uint8_t>(off, key_count);
    if (has_images(kind)) {
        carve_size<ObjectImage>(off, key_count);
        carve_size<ObjectImage>(off, key_count);
    }
    if (is_two_hop(kind) && !atomic_write)
        carve_size<uint32_t>(off, key_count);  // complete hop-2 plan
    if (atomic_install)
        carve_size<uint16_t>(off, shard_slots); // direct shard -> dense group lookup
    if (atomic_install) carve_size<OwnerRecordRefs>(off, owner_slots);
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
    if (has_values(state.kind, state.atomic_write))
        state.values = carve_at<ValueSlot>(base, off, state.key_count);
    if (has_status(state.kind, state.atomic_write))
        state.status = carve_at<uint8_t>(base, off, state.key_count);
    if (has_images(state.kind)) {
        state.images = carve_at<ObjectImage>(base, off, state.key_count);
        state.apply = carve_at<ObjectImage>(base, off, state.key_count);
    }
    if (state.two_hop) state.hop2 = carve_at<uint32_t>(base, off, state.key_count);
    if (state.atomic_write || state.atomic_apply)
        state.shard_groups = carve_at<uint16_t>(base, off, state.shard_slots);
    if (state.atomic_write || state.atomic_apply)
        state.owner_record_refs = carve_at<OwnerRecordRefs>(base, off, state.owner_slots);

    for (uint32_t i = 0; state.groups && i < state.group_cap; i++)
        new (&state.groups[i]) ShardGroup;
    for (uint32_t i = 0; state.keys && i < state.key_count; i++) new (&state.keys[i]) KeyRef;
    if (state.key_order) std::memset(state.key_order, 0, sizeof(uint32_t) * state.key_count);
    for (uint32_t i = 0; state.values && i < state.key_count; i++) new (&state.values[i]) ValueSlot;
    if (state.status) std::memset(state.status, 0, state.key_count);
    if (state.hop2) std::memset(state.hop2, 0, sizeof(uint32_t) * state.key_count);
    if (state.shard_groups)
        std::fill_n(state.shard_groups, state.shard_slots, UINT16_MAX);
    for (uint32_t i = 0; state.owner_record_refs && i < state.owner_slots; i++)
        new (&state.owner_record_refs[i]) OwnerRecordRefs;
    for (uint32_t i = 0; state.images && i < state.key_count; i++) new (&state.images[i]) ObjectImage;
    for (uint32_t i = 0; state.apply && i < state.key_count; i++) new (&state.apply[i]) ObjectImage;
}

void reset_groups(ScatterState& state) {
    for (uint32_t i = 0; i < state.group_cap; i++) {
        ShardGroup& group = state.groups[i];
        delete group.aux;
        group = ShardGroup{};
    }
    if (state.shard_groups)
        std::fill_n(state.shard_groups, state.shard_slots, UINT16_MAX);
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
        if (state.shard_groups)
            state.shard_groups[sid] = static_cast<uint16_t>(state.nsub - 1);
        cursor += counts[sid];
    }
    uint32_t fill[256] = {};
    for (uint32_t i = 0; i < count; i++) {
        const uint32_t pos = positions[i];
        ShardGroup* group = group_for(state, state.keys[pos].shard);
        if (state.atomic_apply)
            group->membership |= atomic_membership_bit(state.keys[pos].hash);
        state.key_order[group->begin + fill[group->shard]++] = pos;
    }
}

void build_initial_groups(ScatterState& state) {
    if (state.atomic_direct) {
        // Direct movers may defer the destination task until the source image is ready. Preserve
        // source-before-destination order on an executor that owns both shards so its retry queue
        // can never sit ahead of the task that satisfies the dependency.
        for (uint32_t pos = state.phase1_first; pos < state.key_count; pos++) {
            ShardGroup& group = state.groups[state.nsub];
            group.shard = state.keys[pos].shard;
            group.begin = pos - state.phase1_first;
            group.count = 1;
            group.membership = atomic_membership_bit(state.keys[pos].hash);
            state.key_order[group.begin] = pos;
            state.shard_groups[group.shard] = static_cast<uint16_t>(state.nsub++);
        }
        return;
    }
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
        if (state.shard_groups)
            state.shard_groups[sid] = static_cast<uint16_t>(state.nsub - 1);
        cursor += counts[sid];
    }
    uint32_t fill[256] = {};
    if (state.atomic_write) {
        for (uint32_t pos = state.phase1_first; pos < state.key_count; pos++) {
            ShardGroup* group = group_for(state, state.keys[pos].shard);
            group->membership |= atomic_membership_bit(state.keys[pos].hash);
            state.key_order[group->begin + fill[group->shard]++] = pos;
        }
    } else {
        for (uint32_t pos = state.phase1_first; pos < state.key_count; pos++) {
            ShardGroup* group = group_for(state, state.keys[pos].shard);
            state.key_order[group->begin + fill[group->shard]++] = pos;
        }
    }
}

uint32_t initialize_owner_completion(ScatterState& state) {
    if (!state.atomic_write && !(state.atomic_apply && state.phase == 2)) return state.nsub;
    uint32_t owners = 0;
    for (uint32_t i = 0; i < state.nsub; i++) {
        const uint32_t tid = state.server->worker_of_shard(state.groups[i].shard);
        const uint32_t slot = state.server->executor_slot(tid);
        if (slot >= state.owner_slots) std::abort();
        OwnerRecordRefs& progress = state.owner_record_refs[slot];
        if (progress.group_count++ == 0) owners++;
    }
    for (uint32_t slot = 0; slot < state.owner_slots; slot++)
        if (state.owner_record_refs[slot].group_count)
            state.owner_record_refs[slot].remaining =
                state.owner_record_refs[slot].group_count;
    return owners;
}

bool publish_phase2(Server& server, ThreadCtx& self, Ring& ring, const Task& task,
                    ScatterState& state) {
    reset_groups(state);
    build_groups(state, state.hop2, state.hop2_count);
    uint32_t needed[kMaxThreads] = {};
    uint32_t participants[kMaxThreads];
    uint16_t routed_owner[256];
    uint32_t nparticipants = 0;
    for (uint32_t i = 0; i < state.nsub; i++) {
        const uint32_t tid = server.worker_of_shard(state.groups[i].shard);
        routed_owner[i] = static_cast<uint16_t>(tid);
        if (needed[tid]++ == 0) participants[nparticipants++] = tid;
    }
    for (uint32_t p = 0; p < nparticipants; p++) {
        const uint32_t tid = participants[p];
        if (server.thread(tid).task_free_slots(self.id()) < needed[tid]) {
            state.final_reply = FinalReply::QueueFull;
            return false;
        }
    }
    state.phase = 2;
    state.pending.store(initialize_owner_completion(state), std::memory_order_release);
    Task posts[256];
    uint16_t participant_begin[kMaxThreads];
    uint32_t cursor = 0;
    for (uint32_t p = 0; p < nparticipants; p++) {
        const uint32_t tid = participants[p];
        participant_begin[p] = static_cast<uint16_t>(cursor);
        cursor += needed[tid];
        needed[tid] = participant_begin[p];
    }
    for (uint32_t i = 0; i < state.nsub; i++)
        posts[needed[routed_owner[i]]++] = Task{
            task.client, task.op_id, state.groups[i].shard, &state};
    if (cursor != state.nsub) std::abort();
    for (uint32_t p = 0; p < nparticipants; p++) {
        const uint32_t tid = participants[p];
        const uint32_t begin = participant_begin[p];
        const uint32_t end = p + 1 < nparticipants ? participant_begin[p + 1] : state.nsub;
        ThreadCtx& owner = server.thread(tid);
        if (!owner.post_tasks_quiet(self.id(), posts + begin, end - begin, self.sig()))
            std::abort();
        owner.flush_task_notify(self.id(), ring, self.sig());
    }
    return true;
}

bool publish_pop_retry(Server& server, ThreadCtx& self, Ring& ring, const Task& task,
                       ScatterState& state) {
    for (uint32_t i = 0; i < state.key_count; i++) {
        state.hop2[i] = i;
        state.images[i] = ObjectImage{};
    }
    if (state.status) std::memset(state.status, 0, state.key_count);
    if (state.result) {
        state.result->members.clear();
        state.result->scores.clear();
    }
    state.selected = std::numeric_limits<uint32_t>::max();
    state.pop_missed = false;
    reset_groups(state);
    build_groups(state, state.hop2, state.key_count);

    uint32_t needed[kMaxThreads] = {};
    uint32_t participants[kMaxThreads];
    uint16_t routed_owner[256];
    uint32_t nparticipants = 0;
    for (uint32_t i = 0; i < state.nsub; i++) {
        const uint32_t tid = server.worker_of_shard(state.groups[i].shard);
        routed_owner[i] = static_cast<uint16_t>(tid);
        if (needed[tid]++ == 0) participants[nparticipants++] = tid;
    }
    for (uint32_t p = 0; p < nparticipants; p++) {
        const uint32_t tid = participants[p];
        if (server.thread(tid).task_free_slots(self.id()) < needed[tid]) {
            state.final_reply = FinalReply::QueueFull;
            return false;
        }
    }

    state.phase = 1;
    state.pop_retry_snapshot = server.atomic_snapshot();
    state.pending.store(state.nsub, std::memory_order_release);
    Task posts[256];
    uint16_t participant_begin[kMaxThreads];
    uint32_t cursor = 0;
    for (uint32_t p = 0; p < nparticipants; p++) {
        const uint32_t tid = participants[p];
        participant_begin[p] = static_cast<uint16_t>(cursor);
        cursor += needed[tid];
        needed[tid] = participant_begin[p];
    }
    for (uint32_t i = 0; i < state.nsub; i++)
        posts[needed[routed_owner[i]]++] = Task{
            task.client, task.op_id, state.groups[i].shard, &state};
    if (cursor != state.nsub) std::abort();
    for (uint32_t p = 0; p < nparticipants; p++) {
        const uint32_t tid = participants[p];
        const uint32_t begin = participant_begin[p];
        const uint32_t end = p + 1 < nparticipants ? participant_begin[p + 1] : state.nsub;
        ThreadCtx& owner = server.thread(tid);
        if (!owner.post_tasks_quiet(self.id(), posts + begin, end - begin, self.sig()))
            std::abort();
        owner.flush_task_notify(self.id(), ring, self.sig());
    }
    return true;
}

void free_state_contents(ScatterState& state) {
    if (state.contents_freed) return;
    for (uint32_t i = 0; i < state.group_cap; i++) delete state.groups[i].aux;
    for (uint32_t i = 0; state.images && i < state.key_count; i++) state.images[i].~ObjectImage();
    for (uint32_t i = 0; state.apply && i < state.key_count; i++) state.apply[i].~ObjectImage();
    delete state.result;
    state.contents_freed = true;
}

void free_state_key_anchors(ScatterState& state) {
    for (uint32_t i = 0; i < state.key_count; i++) {
        if (!state.keys[i].key_anchor) continue;
        kvobj_free(state.keys[i].key_anchor);
        state.keys[i].key_anchor = nullptr;
        state.keys[i].stable_object = nullptr;
    }
}

}  // namespace

ScatterArenaPool::~ScatterArenaPool() {
    reap_deferred();
    for (uint32_t i = 0; i < count_; i++) std::free(cached_[i]);
}

void* ScatterArenaPool::acquire(size_t bytes, bool& pooled) {
    pooled = bytes <= kCommonBytes;
    if (pooled && count_) return cached_[--count_];
    void* memory = nullptr;
    if (::posix_memalign(&memory, alignof(OwnerRecordRefs), pooled ? kCommonBytes : bytes) != 0)
        return nullptr;
    return memory;
}

void ScatterArenaPool::release(void* ptr, bool pooled) {
    if (!ptr) return;
    if (pooled && count_ < kCached) cached_[count_++] = ptr;
    else std::free(ptr);
}

ScatterPrepare xshard_prepare(Server& server, Op& op, ScatterArenaPool& pool,
                              uint32_t owner_io, uint64_t origin_conn_id,
                              ScatterDispatch& dispatch) {
    const bool all_shards = (op.spec->flags & CmdFlags::AllShards) ||
                            ((op.spec->flags & CmdFlags::ConfigRoute) &&
                             command_config_routes_all_shards(op));
    Kind kind;
    if (all_shards)
        kind = op.cmd_name().eq_icase("dbsize") ? Kind::DbsizeExact : Kind::AllShards;
    else if (!(op.spec->flags & CmdFlags::MultiShard) || !classify(op, kind))
        return ScatterPrepare::NotScatter;

    const uint64_t atomic_mode = server.atomic_mode_state();
    const bool tracking = atomic_mode != 0;
    const bool atomic_enabled = atomic_mode & Server::kAtomicEnabledBit;
    const bool atomic_write = atomic_enabled && is_atomic_write_kind(kind);

    // The ordinary handlers are already the optimal one-key path.
    if ((kind == Kind::Del || kind == Kind::Unlink || kind == Kind::Exists ||
         kind == Kind::Touch) && op.argc() == 2) return ScatterPrepare::NotScatter;
    if (kind == Kind::Pfcount && op.argc() == 2) return ScatterPrepare::NotScatter;

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

    uint32_t mpop_count = 0;
    bool pop_edge = false;
    uint64_t pop_count = 1;
    if ((kind == Kind::Lmpop || kind == Kind::Zmpop) &&
        !parse_mpop(op, kind, mpop_count, pop_edge, pop_count))
        return ScatterPrepare::Error;

    ImageRangeOptions range_options;
    ImageRangeSpec range_spec;
    if (kind == Kind::Zrangestore &&
        (!parse_zrangestore_options(op, range_options) ||
         !parse_zrangestore_range(op, range_options, range_spec)))
        return ScatterPrepare::Error;

    SortOptions sort_options;
    if (kind == Kind::Sort && !parse_sort_options(op, sort_options))
        return ScatterPrepare::Error;
    const bool atomic_apply = atomic_enabled && is_atomic_apply_kind(kind, sort_options.store);
    const bool atomic_pop = atomic_enabled && is_atomic_pop_kind(kind);
    const bool atomic_group = atomic_write || atomic_apply || atomic_pop;
    const bool atomic_direct = atomic_apply && kind == Kind::Rename;

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

    const uint32_t key_count = key_count_for(kind, op, sinter_count, mpop_count,
                                             sort_options.store);
    RouteKey route_stack[kRouteStack];
    RouteKey* routes = route_stack;
    if (key_count > kRouteStack) {
        routes = new (std::nothrow) RouteKey[key_count];
        if (!routes) { set_oom(op); return ScatterPrepare::Error; }
    }
    for (uint32_t i = 0; i < key_count; i++) {
        const uint32_t arg = key_arg_for(kind, i, sinter_count, sort_options.store_arg);
        const uint64_t hash = FlatStore::hash_key(op.arg(arg));
        routes[i] = RouteKey{hash, arg, server.router().shard_of(hash)};
    }

    // Every explicit key, including a STORE destination, must agree before taking localfast.
    if (key_count) {
        bool same_owner = true;
        for (uint32_t i = 1; i < key_count; i++) same_owner &= routes[i].shard == routes[0].shard;
        // Common same-owner commands retain localfast. If an atomic window touches one of their
        // keys, the owner resolves it through the short pending-entry list and clones only writes.
        if (same_owner && kind != Kind::Pfcount && kind != Kind::Pfmerge) {
            op.shard = routes[0].shard;
            op.hash = routes[0].hash;
            op.mark_local_xshard();
            if (atomic_group) server.thread(owner_io).note_atomic_localfast();
            if (routes != route_stack) delete[] routes;
            return ScatterPrepare::NotScatter;
        }
    }

    uint32_t phase1_first = (is_store_setop(kind) || kind == Kind::Bitop ||
                             kind == Kind::Zrangestore ||
                             (kind == Kind::Sort && sort_options.store)) ? 1u : 0u;
    uint32_t group_cap = 0;
    if (kind == Kind::AllShards || kind == Kind::DbsizeExact || kind == Kind::Keys) {
        group_cap = server.nshards();
    } else if (atomic_write) {
        bool seen[256] = {};
        for (uint32_t i = phase1_first; i < key_count; i++)
            if (!seen[static_cast<uint32_t>(routes[i].shard)]) {
                seen[static_cast<uint32_t>(routes[i].shard)] = true;
                group_cap++;
            }
    } else {
        for (uint32_t i = phase1_first; i < key_count; i++) {
            bool first = true;
            for (uint32_t prior = phase1_first; prior < i; prior++)
                if (routes[prior].shard == routes[i].shard) {
                    first = false;
                    break;
                }
            group_cap += first;
        }
    }
    const bool needs_snapshot = tracking &&
        (key_count || kind == Kind::Keys || kind == Kind::DbsizeExact) &&
        !(atomic_write && kind == Kind::Mset);
    if (needs_snapshot && (atomic_mode & ~Server::kAtomicEnabledBit) &&
        !pool.can_register_snapshot()) {
        if (routes != route_stack) delete[] routes;
        return ScatterPrepare::Backpressure;
    }
    bool admitted = false;
    uint64_t admission_generation = 0;
    if (atomic_group) {
        if (!server.atomic_try_admit(owner_io, admission_generation)) {
            if (routes != route_stack) delete[] routes;
            return ScatterPrepare::Backpressure;
        }
        admitted = true;
    }
    const size_t bytes = arena_layout_bytes(
        kind, key_count, group_cap, server.nshards(), atomic_write, atomic_apply,
        static_cast<uint32_t>(server.placement().ex_threads().size()));
    if (bytes == std::numeric_limits<size_t>::max() || bytes > UINT32_MAX) {
        if (admitted) server.atomic_retire_group(owner_io, admission_generation);
        if (routes != route_stack) delete[] routes;
        set_oom(op);
        return ScatterPrepare::Error;
    }
    bool pooled = false;
    void* memory = pool.acquire(bytes, pooled);
    if (!memory) {
        if (admitted) server.atomic_retire_group(owner_io, admission_generation);
        if (routes != route_stack) delete[] routes;
        set_oom(op);
        return ScatterPrepare::Error;
    }
    auto* state = new (memory) ScatterState;
    state->kind = kind;
    state->atomic_write = atomic_write;
    state->atomic_apply = atomic_apply;
    state->atomic_pop = atomic_pop;
    state->atomic_group = atomic_group;
    state->atomic_direct = atomic_direct;
    state->phase = atomic_direct ? 2 : 1;
    state->two_hop = is_two_hop(kind) && !atomic_write && !atomic_direct;
    state->barrier = state->two_hop || all_shards;
    state->admitted = admitted;
    state->server = &server;
    state->pooled = pooled;
    state->owner_io = owner_io;
    state->owner_slots = static_cast<uint32_t>(server.placement().ex_threads().size());
    state->admission_generation = admission_generation;
    state->origin_conn_id = origin_conn_id;
    state->arena_bytes = static_cast<uint32_t>(bytes);
    state->key_count = key_count;
    state->group_cap = group_cap;
    state->shard_slots = (atomic_write || atomic_apply) ? server.nshards() : 0;
    state->phase1_first = phase1_first;
    state->copy_replace = copy_replace;
    state->from_left = from_left;
    state->to_left = to_left;
    state->pop_edge = pop_edge;
    state->pop_count = pop_count;
    state->sinter_limit = sinter_limit;
    state->range_options = range_options;
    state->range_spec = range_spec;
    state->sort_options = sort_options;
    // MSET is a blind replacement. Registering a read cut for it only pins predecessors across a
    // deep pipeline; MSETNX and delete still need their one dispatch snapshot for existence.
    if (needs_snapshot)
        state->snapshot = server.atomic_snapshot();
    if (kind == Kind::Sintercard) { state->set_first = 0; state->set_count = sinter_count; }
    else if (is_store_setop(kind)) { state->set_first = 1; state->set_count = key_count - 1; }
    else if (is_plain_setop(kind)) { state->set_first = 0; state->set_count = key_count; }
    init_arena_arrays(*state);
    for (uint32_t i = 0; i < key_count; i++)
        state->keys[i] = KeyRef{routes[i].hash, routes[i].arg, routes[i].shard};
    if (routes != route_stack) delete[] routes;

    // Blind string values belong to the op's IO thread until an owner links them. Allocation and
    // memcpy therefore run on the underutilized stage without touching a shard or shard metadata.
    // key_anchor is the ownership bit: an owner clears it only after atomic_install_group takes the
    // object; abandonment and prepare failures leave it for IO-side destruction.
    if (atomic_write && (kind == Kind::Mset || kind == Kind::Msetnx)) {
        for (uint32_t i = 0; i < key_count; i++) {
            KeyRef& key = state->keys[i];
            // Small/int objects already come from the shard owner's hot value pool. Moving those to
            // generic jemalloc regressed MSET-8 despite shifting cycles to IO. Large strings bypass
            // that pool in V3, so prebuild precisely the allocation+memcpy work that was already a
            // heap operation and preserve the allocation-free common cell.
            if (op.arg(key.arg + 1).n <= kEmbedThreshold) continue;
            KvObj* value = xshard_make_string(op.arg(key.arg), op.arg(key.arg + 1));
            if (!value) {
                set_oom(op);
                xshard_destroy(state, pool, owner_io);
                return ScatterPrepare::Error;
            }
            key.stable_object = value;
            key.key_anchor = value;
        }
    }

    if (state->snapshot != UINT64_MAX && !pool.register_snapshot(server, state)) {
        set_oom(op);
        xshard_destroy(state, pool, owner_io);
        return ScatterPrepare::Error;
    }

    if (kind == Kind::AllShards || kind == Kind::DbsizeExact || kind == Kind::Keys) {
        state->nsub = server.nshards();
        for (uint32_t sid = 0; sid < state->nsub; sid++) {
            state->groups[sid].shard = sid;
            if (state->shard_groups)
                state->shard_groups[sid] = static_cast<uint16_t>(sid);
        }
    } else {
        build_initial_groups(*state);
    }
    state->pending.store(initialize_owner_completion(*state), std::memory_order_relaxed);
    dispatch.state = state;
    dispatch.nshards = state->nsub;
    dispatch.barrier = state->barrier;
    dispatch.atomic_write = state->atomic_group;
    return ScatterPrepare::Ready;
}

int32_t xshard_dispatch_shard(const ScatterDispatch& dispatch, uint32_t index) {
    if (!dispatch.state) return -1;
    return index < dispatch.state->nsub ? dispatch.state->groups[index].shard : -1;
}

void xshard_destroy(ScatterState* state, ScatterArenaPool& pool, uint32_t owner_io) {
    if (!state) return;
    if (state->owner_io != owner_io) std::abort();
    if (state->snapshot_registered && state->server)
        pool.unregister_snapshot(*state->server, state);
    if (state->admitted && state->server) {
        state->server->atomic_retire_group(state->owner_io, state->admission_generation);
        state->admitted = false;
    }
    const bool pooled = state->pooled;
    free_state_contents(*state);
    state->retired = true;
    if (state->record_refs.load(std::memory_order_acquire) != 0) {
        pool.defer_destroy(state);
        return;
    }
    free_state_key_anchors(*state);
    state->~ScatterState();
    pool.release(state, pooled);
}

bool xshard_is_local(const Op& op) { return op.local_xshard(); }

ScatterTaskResult xshard_execute(const Task& task, Shard& shard, Op& op,
                                 uint32_t owner_thread_id) {
    ScatterState& state = *task.scatter;
    ShardGroup& group = *group_for(state, shard.id());
    if (!state.atomic_write && shard.store().atomic_has_records()) {
        const uint64_t cleanup_cutoff = state.server->atomic_snapshot();
        const uint64_t floor = state.server->atomic_read_floor();
        for (uint32_t i = 0; i < group.count; i++) {
            const uint32_t pos = state.key_order[group.begin + i];
            const KeyRef& key = state.keys[pos];
            shard.store().atomic_promote_key(
                key.hash, op.arg(key.arg), floor, cleanup_cutoff);
        }
    }
    struct ReadEpochGuard {
        FlatStore& store;
        bool bound;
        ReadEpochGuard(FlatStore& store_, uint64_t snapshot, uint64_t origin_conn_id)
            : store(store_), bound(snapshot != UINT64_MAX) {
            if (bound) store.atomic_set_read_context(snapshot, origin_conn_id);
        }
        ~ReadEpochGuard() { if (bound) store.atomic_clear_read_epoch(); }
    };
    const uint64_t read_snapshot = state.atomic_pop && state.phase == 1 &&
                                   state.pop_retry_snapshot != UINT64_MAX
        ? state.pop_retry_snapshot : state.snapshot;
    const bool read_latest = state.atomic_direct || (state.atomic_pop && state.phase == 2);
    ReadEpochGuard read_epoch(
        shard.store(), read_latest ? UINT64_MAX : read_snapshot, state.origin_conn_id);
    try {
        if (state.atomic_direct)
            return execute_atomic_direct_rename(task, shard, op, owner_thread_id);
        if (state.atomic_apply && state.phase == 2)
            return execute_atomic_apply(task, shard, op, owner_thread_id);
        if (state.atomic_write) {
            // One owner pass preflights the table, allocates one shard entry, and performs ordinary
            // physical replacements. Per key, the entry records only the displaced pointer.
            if (!shard.store().atomic_prepare_capacity(group.count)) {
                group.error = WorkError::InsertFailed;
                state.aborted.store(true, std::memory_order_release);
                return ScatterTaskResult::Complete;
            }
            const uint32_t owner_slot = state.server->executor_slot(owner_thread_id);
            if (owner_slot >= state.owner_slots) std::abort();
            auto* owner_refs = &state.owner_record_refs[owner_slot].nodes;
            void* pending_entry = shard.store().atomic_prepare_group(
                &state, group.begin, group.count, &state.epoch, &state.record_refs,
                &state.aborted, state.origin_conn_id, owner_refs, group.membership);
            if (!pending_entry) {
                group.error = WorkError::Oom;
                state.aborted.store(true, std::memory_order_release);
                return ScatterTaskResult::Complete;
            }
            uint32_t installed = 0;
            size_t parked_bytes = 0;
            size_t installed_bytes = 0;
            if (state.aborted.load(std::memory_order_acquire)) {
                shard.store().atomic_discard_group(pending_entry);
                return ScatterTaskResult::Complete;
            }
            // MSETNX tests the pre-command state. Duplicate keys in one command are not an
            // existence failure (Redis installs the last supplied value); probing after the first
            // physical exchange would see our own still-private candidate because the entry is
            // intentionally linked only after the complete shard pass. Preflight every local key
            // before any exchange, then materialize the whole candidate span.
            if (state.kind == Kind::Msetnx) {
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    if (shard.store().find(key.hash, op.arg(key.arg))) {
                        state.aborted.store(true, std::memory_order_release);
                        shard.store().atomic_discard_group(pending_entry);
                        return ScatterTaskResult::Complete;
                    }
                }
            }
            for (uint32_t i = 0; i < group.count; i++) {
                const uint32_t pos = state.key_order[group.begin + i];
                KeyRef& key = state.keys[pos];
                const Slice key_slice = op.arg(key.arg);
                KvObj* visible = (state.kind == Kind::Mset || state.kind == Kind::Msetnx)
                    ? nullptr : shard.store().find(key.hash, key_slice);
                if (state.kind == Kind::Del || state.kind == Kind::Unlink) {
                    bool duplicate = false;
                    for (uint32_t prior = 0; prior < i; prior++) {
                        const uint32_t p = state.key_order[group.begin + prior];
                        const Slice prior_key = op.arg(state.keys[p].arg);
                        duplicate = state.keys[p].hash == key.hash && prior_key == key_slice;
                        if (duplicate) break;
                    }
                    state.status[pos] = visible && !duplicate;
                    // DEL installs no object of its own. Keep key identity in the group arena's
                    // anchor rather than in its parked predecessor: prefix promotion may splice
                    // and retire that predecessor while a later DEL entry is still pending.
                    key.key_anchor = xshard_make_string(key_slice, Slice{});
                    if (!key.key_anchor) {
                        group.error = WorkError::Oom;
                        state.aborted.store(true, std::memory_order_release);
                        break;
                    }
                    key.stable_object = key.key_anchor;
                    KvObj* old = shard.store().atomic_install_group(
                        pending_entry, key.hash, key_slice, nullptr);
                    if (old) parked_bytes += kvobj_size(old);
                    installed++;
                    continue;
                }

                KvObj* value = key.key_anchor;
                const bool io_prebuilt = value != nullptr;
                if (io_prebuilt && key.stable_object != value) std::abort();
                if (!value) {
                    value = xshard_make_atomic_string(
                        shard, key_slice, op.arg(key.arg + 1));
                    if (!value) {
                        group.error = WorkError::Oom;
                        state.aborted.store(true, std::memory_order_release);
                        break;
                    }
                }
                if (!shard.store().atomic_admit(key_slice, value)) {
                    if (!io_prebuilt) shard.store().atomic_discard_value(value);
                    group.error = WorkError::Maxmemory;
                    state.aborted.store(true, std::memory_order_release);
                    break;
                }
                key.stable_object = value;
                KvObj* old = shard.store().atomic_install_group(
                    pending_entry, key.hash, key_slice, value);
                if (old) parked_bytes += kvobj_size(old);
                installed_bytes += kvobj_size(value);
                if (io_prebuilt) key.key_anchor = nullptr;
                installed++;
            }
            if (installed) {
                shard.store().atomic_finish_group_install(parked_bytes, installed_bytes);
                shard.store().atomic_publish_group(pending_entry);
                if (*owner_refs == 0)
                    state.record_refs.fetch_add(1, std::memory_order_release);
                (*owner_refs)++;
            } else {
                shard.store().atomic_discard_group(pending_entry);
            }
            return ScatterTaskResult::Complete;
        }

        const bool pending_reads = shard.store().atomic_has_records();
        auto find_value = [&](uint64_t hash, Slice key) {
            return pending_reads ? shard.store().atomic_find_tracked(hash, key)
                                 : shard.store().find(hash, key);
        };

        // MGET is the read-heavy matrix cell. Specialize its loop once per owner task so the
        // no-pending arm is byte-for-byte the ordinary FlatStore lookup, with no per-key selector.
        if (state.phase != 2 && state.kind == Kind::Mget) {
            auto gather = [&]<bool Tracked>() {
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    KvObj* object;
                    if constexpr (Tracked)
                        object = shard.store().atomic_find_tracked(key.hash, op.arg(key.arg));
                    else
                        object = shard.store().find(key.hash, op.arg(key.arg));
                    if (!object || static_cast<Type>(object->type) != Type::String) continue;
                    ValueSlot& slot = state.values[pos];
                    if (object->is_int()) {
                        slot.len = i64_to_dec(slot.small, object->int_value());
                        slot.kind = ValueKind::Inline;
                        continue;
                    }
                    const Slice value = object->str_value();
                    slot.len = value.n;
                    const uint32_t cutover =
                        std::min<uint32_t>(shard.zc_min(), ValueSlot::kInline);
                    if (value.n <= cutover) {
                        if (value.n) std::memcpy(slot.small, value.p, value.n);
                        slot.kind = ValueKind::Inline;
                    } else {
                        shard.store().borrow(value.p);
                        slot.ptr = value.p;
                        slot.shard = shard.id();
                        slot.kind = ValueKind::Borrow;
                    }
                }
            };
            if (pending_reads) gather.template operator()<true>();
            else gather.template operator()<false>();
            return ScatterTaskResult::Complete;
        }

        if (state.phase == 2) {
            if (state.kind == Kind::Lmpop || state.kind == Kind::Zmpop) {
                const uint32_t pos = state.key_order[group.begin];
                const KeyRef& key = state.keys[pos];
                bool plain_active = false;
                if (shard.store().atomic_has_record(key.hash, op.arg(key.arg))) {
                    const WorkError prepared = begin_plain_version(
                        *state.server, shard, op.arg(key.arg), key.hash,
                        state.atomic_pop ? UINT64_MAX : state.snapshot, state.origin_conn_id);
                    if (prepared != WorkError::None) {
                        state.status[pos] = static_cast<uint8_t>(prepared);
                        return ScatterTaskResult::Complete;
                    }
                    plain_active = true;
                }
                ResultHeap* result = ensure_result(state);
                if (!result) {
                    state.status[pos] = static_cast<uint8_t>(WorkError::Oom);
                    if (plain_active) shard.store().atomic_finish_plain();
                    return ScatterTaskResult::Complete;
                }
                const XshardPopResult popped = state.kind == Kind::Lmpop
                    ? xshard_pop_list(shard, op.arg(key.arg), key.hash, !state.pop_edge,
                                      state.pop_count, result->members)
                    : xshard_pop_zset(shard, op.arg(key.arg), key.hash, state.pop_edge,
                                      state.pop_count, result->members, result->scores);
                if (popped == XshardPopResult::WrongType)
                    state.status[pos] = static_cast<uint8_t>(WorkError::WrongType);
                else if (popped == XshardPopResult::Oom)
                    state.status[pos] = static_cast<uint8_t>(WorkError::Oom);
                else if (popped == XshardPopResult::Missing && state.atomic_pop)
                    state.pop_missed = true;
                if (plain_active) shard.store().atomic_finish_plain();
                return ScatterTaskResult::Complete;
            }
            for (uint32_t i = 0; i < group.count; i++) {
                const uint32_t pos = state.key_order[group.begin + i];
                const KeyRef& key = state.keys[pos];
                bool plain_active = false;
                if (shard.store().atomic_has_record(key.hash, op.arg(key.arg))) {
                    const WorkError prepared = begin_plain_version(
                        *state.server, shard, op.arg(key.arg), key.hash, state.snapshot,
                        state.origin_conn_id);
                    if (prepared != WorkError::None) {
                        state.status[pos] = static_cast<uint8_t>(prepared);
                        continue;
                    }
                    plain_active = true;
                }
                WorkError result;
                if (state.kind == Kind::Msetnx) {
                    result = store_xstring(shard, op.arg(key.arg), key.hash, op.arg(key.arg + 1));
                } else if (state.kind == Kind::Bitop) {
                    const ObjectImage& image = state.apply[pos];
                    if (!image.present) {
                        shard.store().erase(key.hash, op.arg(key.arg));
                        result = WorkError::None;
                    } else {
                        // BITOP overwrites the destination like SET: TTL cleared (-1), and the
                        // result must stay raw bytes -- never integer-encoded -- so GET
                        // round-trips exactly. Positional args: expire_at_ms BEFORE
                        // integer_encode (a bare `false` here lands in expire_at_ms as
                        // "expired at epoch 0" and stores a dead key).
                        result = store_xstring(
                            shard, op.arg(key.arg), key.hash,
                            Slice(reinterpret_cast<const char*>(image.payload.data()),
                                  static_cast<uint32_t>(image.payload.size())),
                            -1, false);
                    }
                } else if (state.kind == Kind::Pfmerge) {
                    const ObjectImage& image = state.apply[pos];
                    const Slice value(reinterpret_cast<const char*>(image.payload.data()),
                                      static_cast<uint32_t>(image.payload.size()));
                    // PFMERGE is a string command even though its bytes are structured. Hop two
                    // installs through the same string funnel as SET and preserves destination TTL.
                    result = store_xstring(shard, op.arg(key.arg), key.hash, value,
                                           image.expire_at_ms, false);
                } else {
                    result = apply_image(shard, op.arg(key.arg), key.hash, state.apply[pos]);
                }
                state.status[pos] = static_cast<uint8_t>(result);
                if (plain_active) shard.store().atomic_finish_plain();
            }
            return ScatterTaskResult::Complete;
        }

        switch (state.kind) {
            case Kind::AllShards:
                // FLUSH remains outside the atomic command set. On a recorded shard, install one
                // owner-local tombstone cut first so clear() cannot free a protected predecessor.
                // Allocation happens before the ticket or any relink; OOM retries are deferrable.
                if ((op.cmd_name().eq_icase("flushdb") || op.cmd_name().eq_icase("flushall")) &&
                    !shard.store().atomic_tombstone_all()) return ScatterTaskResult::Retry;
                op.spec->handler(shard, op);
                return ScatterTaskResult::Complete;
            case Kind::DbsizeExact:
                state.exact_sum.fetch_add(
                    shard.store().atomic_resolved_size(state.snapshot), std::memory_order_relaxed);
                return ScatterTaskResult::Complete;
            case Kind::Mget:
                std::abort(); // handled by the owner-hoisted arm above
            case Kind::Mset:
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    bool plain_active = false;
                    if (shard.store().atomic_has_record(key.hash, op.arg(key.arg))) {
                        const WorkError prepared = begin_plain_version(
                            *state.server, shard, op.arg(key.arg), key.hash, state.snapshot,
                            state.origin_conn_id);
                        if (prepared != WorkError::None) {
                            state.status[pos] = static_cast<uint8_t>(prepared);
                            continue;
                        }
                        plain_active = true;
                    }
                    state.status[pos] = static_cast<uint8_t>(
                        store_xstring(shard, op.arg(key.arg), key.hash, op.arg(key.arg + 1)));
                    if (plain_active) shard.store().atomic_finish_plain();
                }
                return ScatterTaskResult::Complete;
            case Kind::Del:
            case Kind::Unlink:
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    bool plain_active = false;
                    if (shard.store().atomic_has_record(key.hash, op.arg(key.arg))) {
                        const WorkError prepared = begin_plain_version(
                            *state.server, shard, op.arg(key.arg), key.hash, state.snapshot,
                            state.origin_conn_id);
                        if (prepared != WorkError::None) {
                            group.error = prepared;
                            continue;
                        }
                        plain_active = true;
                    }
                    state.status[pos] = shard.store().erase(key.hash, op.arg(key.arg));
                    if (plain_active) shard.store().atomic_finish_plain();
                }
                return ScatterTaskResult::Complete;
            case Kind::Exists:
            case Kind::Touch:
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    state.status[pos] = find_value(key.hash, op.arg(key.arg)) != nullptr;
                }
                return ScatterTaskResult::Complete;
            case Kind::Keys: {
                if (!group.aux) group.aux = new GroupAux;
                const Slice pattern = op.arg(1);
                group.scan_cursor = shard.store().scan(group.scan_cursor, 256, [&](KvObj* object) {
                    const Slice key = object->key();
                    const uint64_t hash = FlatStore::hash_key(key);
                    if (shard.store().atomic_physical_key_visible(hash, key, state.snapshot) &&
                        glob_match(pattern.p, pattern.n, key.p, key.n))
                        group.aux->keys_result.emplace_back(key.p, key.n);
                });
                if (group.scan_cursor) return ScatterTaskResult::Retry;
                shard.store().atomic_for_each_side_key(state.snapshot, [&](Slice key) {
                    if (glob_match(pattern.p, pattern.n, key.p, key.n))
                        group.aux->keys_result.emplace_back(key.p, key.n);
                });
                return ScatterTaskResult::Complete;
            }
            case Kind::Msetnx:
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    if (find_value(key.hash, op.arg(key.arg)))
                        state.values[pos].kind = ValueKind::Inline;
                }
                return ScatterTaskResult::Complete;
            case Kind::Lmpop:
            case Kind::Zmpop:
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    KvObj* object = find_value(key.hash, op.arg(key.arg));
                    ObjectImage& probe = state.images[pos];
                    if (!object) continue;
                    probe.present = true;
                    probe.type = static_cast<Type>(object->type);
                    const Type wanted = state.kind == Kind::Lmpop ? Type::List : Type::Zset;
                    if (probe.type == wanted) probe.entries = CollectionRef(object).entries();
                }
                return ScatterTaskResult::Complete;
            case Kind::Rename:
            case Kind::Renamenx:
            case Kind::Copy:
                if (state.atomic_apply) {
                    for (uint32_t i = 0; i < group.count; i++) {
                        const uint32_t pos = state.key_order[group.begin + i];
                        const KeyRef& key = state.keys[pos];
                        KvObj* object = find_value(key.hash, op.arg(key.arg));
                        ObjectImage& image = state.images[pos];
                        if (!object) continue;
                        image.present = true;
                        image.type = static_cast<Type>(object->type);
                        image.expire_at_ms = object->expire_at_ms();

                        // The destination image is needed only for its existence verdict. A
                        // string source can be cloned directly for the destination and carried as
                        // an unlinked object, while collections retain the generic image path.
                        if (pos != 0) continue;
                        if (image.type != Type::String) {
                            if (!serialize_object(object, image))
                                state.status[pos] = static_cast<uint8_t>(WorkError::Oom);
                            continue;
                        }
                        KeyRef& destination = state.keys[1];
                        KvObj* clone = object->is_int()
                            ? kvobj_new_int(op.arg(destination.arg), object->int_value(),
                                            image.expire_at_ms)
                            : xshard_make_string(op.arg(destination.arg), object->str_value(),
                                                 image.expire_at_ms, false);
                        if (!clone) {
                            state.status[pos] = static_cast<uint8_t>(WorkError::Oom);
                            continue;
                        }
                        destination.stable_object = clone;
                        destination.key_anchor = clone;
                    }
                    return ScatterTaskResult::Complete;
                }
                [[fallthrough]];
            default:
                for (uint32_t i = 0; i < group.count; i++) {
                    const uint32_t pos = state.key_order[group.begin + i];
                    const KeyRef& key = state.keys[pos];
                    KvObj* object = find_value(key.hash, op.arg(key.arg));
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
    if (state.atomic_write || (state.atomic_apply && state.phase == 2)) {
        const uint32_t slot = server.executor_slot(self.id());
        if (slot >= state.owner_slots) std::abort();
        uint32_t& remaining = state.owner_record_refs[slot].remaining;
        if (!remaining) std::abort();
        if (--remaining != 0) return ScatterFinish::Waiting;
    }
    if (state.pending.fetch_sub(1, std::memory_order_acq_rel) != 1)
        return ScatterFinish::Waiting;
    if (state.atomic_pop && state.phase == 2 && state.pop_missed) {
        static constexpr uint32_t kMaxPopRetries = 8;
        if (state.pop_retries++ < kMaxPopRetries &&
            publish_pop_retry(server, self, ring, task, state))
            return ScatterFinish::Waiting;
        if (state.final_reply == FinalReply::QueueFull) return ScatterFinish::Final;
        state.final_reply = FinalReply::NullArray;
        return ScatterFinish::Final;
    }
    // Once the last owner has materialized its result, this read cut protects no future
    // dereference. Value borrows have their own store lifetime pins. Tell the owning IO to advance
    // its floor even if ordered reply retirement is still behind a deep pipeline.
    if ((!state.two_hop || state.phase == 2) && state.snapshot_registered &&
        !state.snapshot_complete.exchange(true, std::memory_order_acq_rel))
        server.note_atomic_snapshot_complete(state.owner_io);
    if (state.atomic_write) {
        WorkError error;
        if (first_error(state, error)) {
            state.aborted.store(true, std::memory_order_release);
            state.final_reply = FinalReply::Work;
            state.final_error = error;
            return ScatterFinish::Final;
        }
        if (state.aborted.load(std::memory_order_acquire)) {
            // MSETNX existence is a normal failed condition, not a work error. Its installed
            // candidates (if another owner got that far) remain forever invisible at epoch zero.
            if (state.kind == Kind::Msetnx) {
                state.final_reply = FinalReply::Integer;
                state.final_integer = 0;
            } else {
                state.final_reply = FinalReply::Internal;
            }
            return ScatterFinish::Final;
        }
        const uint64_t ticket = server.atomic_commit();
        state.epoch.store(ticket, std::memory_order_release);
        if (state.kind == Kind::Msetnx) {
            state.final_reply = FinalReply::Integer;
            state.final_integer = 1;
        }
        return ScatterFinish::Final;
    }
    if (state.phase == 2) {
        finish_phase2(state);
        return ScatterFinish::Final;
    }
    if (state.kind == Kind::Pfcount) {
        finish_pfcount(state);
        return ScatterFinish::Final;
    }
    if (!state.two_hop) return ScatterFinish::Final;
    if (finish_phase1(state, op)) {
        return ScatterFinish::Final;
    }
    if (publish_phase2(server, self, ring, task, state)) return ScatterFinish::Waiting;
    return ScatterFinish::Final;
}

void xshard_retire(Server& server, ThreadCtx& self, Ring& ring, Client& client, Op& op,
                   ScatterArenaPool& pool, uint32_t owner_io,
                   void* release_ctx, void (*release_fn)(void*, int32_t, const char*)) {
    (void)self;
    (void)ring;
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
    if (state->atomic_group) {
        // Installed nodes retain only the compact group decision fields. Reclamation is batched by
        // each owner on later passes; retirement posts no per-group cleanup fan-out.
        free_state_contents(*state);
        if (state->snapshot_registered)
            pool.unregister_snapshot(server, state);
        client.atomic_group_finished();
    }
    op.detach_scatter_state();
    xshard_destroy(state, pool, owner_io);
}

}  // namespace tomo
