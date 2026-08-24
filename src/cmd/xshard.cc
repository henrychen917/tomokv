// xshard.cc -- coalesced cross-shard commands, deliberately without cross-shard atomicity.
#include "xshard.h"

#include <algorithm>
#include <atomic>
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
    AllShards, Mget, Mset, Del, Unlink, Exists, Touch, Keys, Msetnx,
    Rename, Renamenx, Copy, Smove, Lmove, Rpoplpush,
    Sinter, Sunion, Sdiff, Sintercard, Sinterstore, Sunionstore, Sdiffstore,
};

enum class WorkError : uint8_t { None, WrongType, Oom, Maxmemory, InsertFailed, Corrupt };

struct ObjectImage {
    bool present = false;
    Type type = Type::String;
    uint8_t encoding = 0;
    int64_t expire_at_ms = -1;
    std::vector<uint8_t> payload;
};

struct ValueSlot {
    bool present = false;
    std::string value;
};

struct ShardGroup {
    bool active = false;
    std::vector<uint32_t> args;       // request argv indices, coalesced once per touched shard
    uint64_t scan_cursor = 0;
    size_t snapshot_pos = 0;
    bool flush_keys_built = false;
    std::vector<std::string> flush_keys;
    std::vector<std::string> keys_result;
    uint64_t count = 0;
    WorkError error = WorkError::None;
};

}  // namespace

struct ScatterState {
    explicit ScatterState(uint32_t nshards, uint32_t argc)
        : groups(nshards), hashes(argc), values(argc), images(argc), apply(argc) {}

    std::atomic<uint32_t> pending{0};
    // Reserved future epoch-MVCC attachment point.  This phase intentionally assigns no epochs,
    // read sets, versions or retries; validate/apply remain separate so those can land here later.
    uint64_t epoch = 0;
    Kind kind = Kind::AllShards;
    uint8_t phase = 1;
    bool barrier = false;
    bool copy_replace = false;
    bool from_left = false;
    bool to_left = false;
    uint64_t sinter_limit = 0;
    uint32_t set_first = 1;
    uint32_t set_count = 0;
    long long final_integer = 0;
    std::string final_bulk;
    std::vector<std::string> final_members;
    std::vector<ShardGroup> groups;
    std::vector<uint64_t> hashes;
    std::vector<ValueSlot> values;
    std::vector<ObjectImage> images;
    std::vector<ObjectImage> apply;
};

namespace {

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
    };
    for (const Entry& entry : entries)
        if (name_is(op, entry.name)) { kind = entry.kind; return true; }
    return false;
}

bool is_two_hop(Kind kind) {
    return kind >= Kind::Msetnx;
}

bool is_store_setop(Kind kind) {
    return kind == Kind::Sinterstore || kind == Kind::Sunionstore ||
           kind == Kind::Sdiffstore;
}

bool is_plain_setop(Kind kind) {
    return kind == Kind::Sinter || kind == Kind::Sunion || kind == Kind::Sdiff;
}

void clear_groups(ScatterState& state) {
    for (ShardGroup& group : state.groups) group = ShardGroup{};
}

void add_arg(Server& server, Op& op, ScatterState& state, uint32_t arg,
             std::vector<int32_t>* touched = nullptr) {
    const uint64_t hash = FlatStore::hash_key(op.arg(arg));
    const int32_t sid = server.router().shard_of(hash);
    state.hashes[arg] = hash;
    ShardGroup& group = state.groups[static_cast<uint32_t>(sid)];
    if (!group.active) {
        group.active = true;
        if (touched) touched->push_back(sid);
    }
    group.args.push_back(arg);
}

void activate_all(Server& server, ScatterState& state, std::vector<int32_t>& touched) {
    for (uint32_t sid = 0; sid < server.nshards(); sid++) {
        state.groups[sid].active = true;
        touched.push_back(static_cast<int32_t>(sid));
    }
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

WorkError store_xstring(Shard& shard, Slice key, uint64_t hash, Slice value) {
    switch (xshard_store_string(shard, key, hash, value)) {
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

bool glob_match(const char* pattern, size_t pn, const char* text, size_t tn) {
    while (pn) {
        const char c = *pattern++;
        pn--;
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

bool first_error(const ScatterState& state, WorkError& error) {
    for (const ShardGroup& group : state.groups)
        if (group.error != WorkError::None) { error = group.error; return true; }
    return false;
}

void reply_work_error(Op& op, WorkError error) {
    if (error == WorkError::WrongType) reply_wrongtype(op.sink());
    else if (error == WorkError::Maxmemory) reply_maxmemory_oom(op);
    else if (error == WorkError::Oom) reply_err(op.sink(), "ERR out of memory");
    else if (error == WorkError::InsertFailed) reply_err(op.sink(), "ERR keyspace insert failed");
    else reply_err(op.sink(), "ERR internal cross-shard value error");
}

void set_phase2_arg(Server& server, Op& op, ScatterState& state, uint32_t arg,
                    std::vector<int32_t>& touched) {
    add_arg(server, op, state, arg, &touched);
}

bool publish_phase2(Server& server, ThreadCtx& self, Ring& ring, const Task& task, Op& op,
                    ScatterState& state, const std::vector<uint32_t>& args) {
    clear_groups(state);
    std::vector<int32_t> touched;
    try {
        for (uint32_t arg : args) set_phase2_arg(server, op, state, arg, touched);
    } catch (const std::bad_alloc&) {
        set_oom(op); return false;
    }
    uint32_t needed[kMaxThreads] = {};
    for (int32_t sid : touched) needed[server.worker_of_shard(sid)]++;
    for (uint32_t tid = 0; tid < server.nthreads(); tid++)
        if (needed[tid] && server.thread(tid).task_free_slots(self.id()) < needed[tid]) {
            reply_err(op.sink(), "ERR cross-shard second hop queue is full");
            return false;
        }
    state.phase = 2;
    state.pending.store(static_cast<uint32_t>(touched.size()), std::memory_order_release);
    bool notified[kMaxThreads] = {};
    for (int32_t sid : touched) {
        const uint32_t tid = server.worker_of_shard(sid);
        const Task next{task.client, task.op_id, sid, &state};
        if (!server.thread(tid).post_task_quiet(self.id(), next, self.sig())) std::abort();
        notified[tid] = true;
    }
    for (uint32_t tid = 0; tid < server.nthreads(); tid++)
        if (notified[tid]) server.thread(tid).flush_task_notify(self.id(), ring, self.sig());
    return true;
}

}  // namespace

void cmd_xshard_only(Shard&, Op& op) {
    reply_err(op.sink(), "ERR internal cross-shard routing error");
}

ScatterPrepare xshard_prepare(Server& server, Op& op, ScatterDispatch& dispatch) {
    const bool all_shards = (op.spec->flags & CmdFlags::AllShards) ||
                            ((op.spec->flags & CmdFlags::ConfigRoute) &&
                             command_config_routes_all_shards(op));
    Kind kind;
    if (all_shards) kind = Kind::AllShards;
    else if (!(op.spec->flags & CmdFlags::MultiShard) || !classify(op, kind))
        return ScatterPrepare::NotScatter;

    // DEL/UNLINK/EXISTS/TOUCH keep their one-key owner fast path.
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

    auto* state = new (std::nothrow) ScatterState(server.nshards(), op.argc());
    if (!state) { set_oom(op); return ScatterPrepare::Error; }
    state->kind = kind;
    state->barrier = is_two_hop(kind) || all_shards;
    dispatch.state = state;
    dispatch.barrier = state->barrier;

    try {
        if (kind == Kind::AllShards || kind == Kind::Keys) {
            activate_all(server, *state, dispatch.shards);
        } else if (kind == Kind::Mget || kind == Kind::Del || kind == Kind::Unlink ||
                   kind == Kind::Exists || kind == Kind::Touch) {
            for (uint32_t arg = 1; arg < op.argc(); arg++) add_arg(server, op, *state, arg, &dispatch.shards);
        } else if (kind == Kind::Mset || kind == Kind::Msetnx) {
            for (uint32_t arg = 1; arg < op.argc(); arg += 2) add_arg(server, op, *state, arg, &dispatch.shards);
        } else if (kind == Kind::Rename || kind == Kind::Renamenx || kind == Kind::Copy ||
                   kind == Kind::Smove || kind == Kind::Lmove || kind == Kind::Rpoplpush) {
            add_arg(server, op, *state, 1, &dispatch.shards);
            add_arg(server, op, *state, 2, &dispatch.shards);
        } else {
            uint32_t first = is_store_setop(kind) ? 2u : 1u;
            uint32_t count = op.argc() - first;
            if (kind == Kind::Sintercard) {
                uint64_t parsed = 0;
                if (!parse_u64(op.arg(1), parsed)) {
                    reply_err(op.sink(), "ERR value is not an integer or out of range");
                    xshard_destroy(state); dispatch.state = nullptr; return ScatterPrepare::Error;
                }
                if (parsed == 0) {
                    reply_err(op.sink(), "ERR numkeys should be greater than 0");
                    xshard_destroy(state); dispatch.state = nullptr; return ScatterPrepare::Error;
                }
                if (parsed > op.argc() - 2) {
                    reply_err(op.sink(), "ERR Number of keys can't be greater than number of args");
                    xshard_destroy(state); dispatch.state = nullptr; return ScatterPrepare::Error;
                }
                first = 2; count = static_cast<uint32_t>(parsed);
                const uint32_t tail = first + count;
                if (tail < op.argc()) {
                    uint64_t limit = 0;
                    if (tail + 2 != op.argc() || !op.arg(tail).eq_icase("LIMIT") ||
                        !parse_u64(op.arg(tail + 1), limit)) {
                        reply_syntax(op.sink());
                        xshard_destroy(state); dispatch.state = nullptr; return ScatterPrepare::Error;
                    }
                    state->sinter_limit = limit;
                }
            }
            state->set_first = first;
            state->set_count = count;
            for (uint32_t i = 0; i < count; i++) add_arg(server, op, *state, first + i, &dispatch.shards);
        }

        if (kind == Kind::Copy) {
            for (uint32_t i = 3; i < op.argc();) {
                if (op.arg(i).eq_icase("REPLACE")) { state->copy_replace = true; i++; }
                else if (op.arg(i).eq_icase("DB") && i + 1 < op.argc()) {
                    uint64_t db = 0;
                    if (!parse_u64(op.arg(i + 1), db) || db != 0) {
                        reply_err(op.sink(), "ERR DB index is out of range");
                        xshard_destroy(state); dispatch.state = nullptr; return ScatterPrepare::Error;
                    }
                    i += 2;
                } else {
                    reply_syntax(op.sink());
                    xshard_destroy(state); dispatch.state = nullptr; return ScatterPrepare::Error;
                }
            }
        }
        if (kind == Kind::Lmove) {
            if (!(op.arg(3).eq_icase("LEFT") || op.arg(3).eq_icase("RIGHT")) ||
                !(op.arg(4).eq_icase("LEFT") || op.arg(4).eq_icase("RIGHT"))) {
                reply_syntax(op.sink());
                xshard_destroy(state); dispatch.state = nullptr; return ScatterPrepare::Error;
            }
            state->from_left = op.arg(3).eq_icase("LEFT");
            state->to_left = op.arg(4).eq_icase("LEFT");
        } else if (kind == Kind::Rpoplpush) {
            state->from_left = false; state->to_left = true;
        }
    } catch (const std::bad_alloc&) {
        set_oom(op); xshard_destroy(state); dispatch.state = nullptr; dispatch.shards.clear();
        return ScatterPrepare::Error;
    }
    state->pending.store(static_cast<uint32_t>(dispatch.shards.size()), std::memory_order_relaxed);
    return ScatterPrepare::Ready;
}

void xshard_destroy(ScatterState* state) { delete state; }

FlatStore::SnapshotWriteResult xshard_snapshot_prepare(const Task& task, Shard& shard) {
    ScatterState& state = *task.scatter;
    ShardGroup& group = state.groups[static_cast<uint32_t>(shard.id())];
    if (!shard.store().snapshot_active()) return FlatStore::SnapshotWriteResult::Ready;

    // Phase-one validate/gather tasks are read-only.  Apply is a distinct phase precisely so a
    // later MVCC layer can validate at an epoch before reaching this mutation gate.
    std::vector<uint32_t> write_args;
    try {
        if (state.phase == 1) {
            if (state.kind == Kind::Mset || state.kind == Kind::Del ||
                state.kind == Kind::Unlink) {
                write_args = group.args;
            } else if (state.kind == Kind::AllShards && (task.client->rob().at(task.op_id).spec->flags &
                                                        CmdFlags::Write)) {
                if (!group.flush_keys_built) {
                    shard.store().for_each([&](KvObj* object) {
                        group.flush_keys.emplace_back(object->key().p, object->key().n);
                    });
                    group.flush_keys_built = true;
                }
                while (group.snapshot_pos < group.flush_keys.size()) {
                    const std::string& key = group.flush_keys[group.snapshot_pos];
                    const Slice slice(key.data(), static_cast<uint32_t>(key.size()));
                    const auto result = shard.store().snapshot_prepare_write(
                        FlatStore::hash_key(slice), slice);
                    if (result != FlatStore::SnapshotWriteResult::Ready) return result;
                    group.snapshot_pos++;
                }
                return FlatStore::SnapshotWriteResult::Ready;
            } else {
                return FlatStore::SnapshotWriteResult::Ready;
            }
        } else {
            write_args = group.args;
        }
    } catch (const std::bad_alloc&) {
        return FlatStore::SnapshotWriteResult::Error;
    }

    Op& op = task.client->rob().at(task.op_id);
    while (group.snapshot_pos < write_args.size()) {
        const uint32_t arg = write_args[group.snapshot_pos];
        const auto result = shard.store().snapshot_prepare_write(state.hashes[arg], op.arg(arg));
        if (result != FlatStore::SnapshotWriteResult::Ready) return result;
        group.snapshot_pos++;
    }
    return FlatStore::SnapshotWriteResult::Ready;
}

ScatterTaskResult xshard_execute(const Task& task, Shard& shard, Op& op) {
    ScatterState& state = *task.scatter;
    ShardGroup& group = state.groups[static_cast<uint32_t>(shard.id())];

    try {
        if (state.phase == 2) {
            if (state.kind == Kind::Msetnx) {
                for (uint32_t arg : group.args) {
                    const WorkError result = store_xstring(shard, op.arg(arg), state.hashes[arg],
                                                          op.arg(arg + 1));
                    if (result != WorkError::None && group.error == WorkError::None)
                        group.error = result;
                }
                return ScatterTaskResult::Complete;
            }
            for (uint32_t arg : group.args) {
                const WorkError result = apply_image(shard, op.arg(arg), state.hashes[arg],
                                                     state.apply[arg]);
                if (result != WorkError::None && group.error == WorkError::None)
                    group.error = result;
            }
            return ScatterTaskResult::Complete;
        }

        switch (state.kind) {
            case Kind::AllShards:
                op.spec->handler(shard, op);
                return ScatterTaskResult::Complete;
            case Kind::Mget:
                for (uint32_t arg : group.args) {
                    KvObj* object = shard.store().find(state.hashes[arg], op.arg(arg));
                    if (!object || static_cast<Type>(object->type) != Type::String) continue;
                    ValueSlot& slot = state.values[arg];
                    slot.present = true;
                    if (object->is_int()) {
                        char integer[24];
                        const uint32_t n = i64_to_dec(integer, object->int_value());
                        slot.value.assign(integer, n);
                    } else {
                        const Slice value = object->str_value();
                        slot.value.assign(value.p, value.n);  // cross-shard values are copied
                    }
                }
                return ScatterTaskResult::Complete;
            case Kind::Mset:
                for (uint32_t arg : group.args) {
                    const WorkError result = store_xstring(shard, op.arg(arg), state.hashes[arg],
                                                          op.arg(arg + 1));
                    if (result != WorkError::None && group.error == WorkError::None)
                        group.error = result;
                }
                return ScatterTaskResult::Complete;
            case Kind::Del:
            case Kind::Unlink:
                for (uint32_t arg : group.args)
                    if (shard.store().erase(state.hashes[arg], op.arg(arg))) group.count++;
                return ScatterTaskResult::Complete;
            case Kind::Exists:
            case Kind::Touch:
                for (uint32_t arg : group.args)
                    if (shard.store().find(state.hashes[arg], op.arg(arg))) group.count++;
                return ScatterTaskResult::Complete;
            case Kind::Keys: {
                const Slice pattern = op.arg(1);
                group.scan_cursor = shard.store().scan(group.scan_cursor, 256, [&](KvObj* object) {
                    const Slice key = object->key();
                    if (glob_match(pattern.p, pattern.n, key.p, key.n))
                        group.keys_result.emplace_back(key.p, key.n);
                });
                return group.scan_cursor ? ScatterTaskResult::Retry : ScatterTaskResult::Complete;
            }
            case Kind::Msetnx:
                for (uint32_t arg : group.args)
                    state.values[arg].present = shard.store().find(state.hashes[arg], op.arg(arg));
                return ScatterTaskResult::Complete;
            default:
                // Every two-hop object command gathers immutable logical images into disjoint
                // request-indexed slots.  No FlatStore allocation is shared across owners.
                for (uint32_t arg : group.args) {
                    KvObj* object = shard.store().find(state.hashes[arg], op.arg(arg));
                    if (!serialize_object(object, state.images[arg])) {
                        group.error = WorkError::Oom;
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

namespace {

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

bool compute_setop(ScatterState& state, Op& op) {
    std::vector<std::vector<std::string>> inputs;
    try {
        inputs.resize(state.set_count);
        for (uint32_t i = 0; i < state.set_count; i++) {
            const ObjectImage& image = state.images[state.set_first + i];
            if (!image_type(image, Type::Set)) { reply_wrongtype(op.sink()); return false; }
            if (image.present && !decode_elements(image, inputs[i])) {
                reply_err(op.sink(), "ERR out of memory"); return false;
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
        state.final_members.assign(result.begin(), result.end());
    } catch (const std::bad_alloc&) {
        reply_err(op.sink(), "ERR out of memory"); return false;
    }
    return true;
}

// Returns true when phase 1 produced a final reply.  False means phase 2 must be published, unless
// op already contains an error (signalled by an empty phase2 list at the call site).
bool finish_phase1(ScatterState& state, Op& op, std::vector<uint32_t>& phase2) {
    WorkError error;
    if (first_error(state, error)) { reply_work_error(op, error); return true; }

    switch (state.kind) {
        case Kind::Msetnx:
            for (uint32_t arg = 1; arg < op.argc(); arg += 2)
                if (state.values[arg].present) { reply_int(op.sink(), 0); return true; }
            state.final_integer = 1;
            for (uint32_t arg = 1; arg < op.argc(); arg += 2) phase2.push_back(arg);
            return false;
        case Kind::Rename:
        case Kind::Renamenx: {
            const ObjectImage& source = state.images[1];
            if (!source.present) { reply_err(op.sink(), "ERR no such key"); return true; }
            if (same_key(op)) {
                if (state.kind == Kind::Rename) reply_ok(op.sink()); else reply_int(op.sink(), 0);
                return true;
            }
            if (state.kind == Kind::Renamenx && state.images[2].present) {
                reply_int(op.sink(), 0); return true;
            }
            state.apply[2] = source;
            state.apply[1] = ObjectImage{};
            state.final_integer = state.kind == Kind::Renamenx ? 1 : -1;
            phase2 = {2, 1};                 // destination first when both keys share one owner
            return false;
        }
        case Kind::Copy:
            if (same_key(op)) {
                reply_err(op.sink(), "ERR source and destination objects are the same"); return true;
            }
            if (!state.images[1].present || (state.images[2].present && !state.copy_replace)) {
                reply_int(op.sink(), 0); return true;
            }
            state.apply[2] = state.images[1];
            state.final_integer = 1;
            phase2 = {2};
            return false;
        case Kind::Smove: {
            const ObjectImage& source = state.images[1];
            const ObjectImage& dest = state.images[2];
            if (!source.present) { reply_int(op.sink(), 0); return true; }
            if (!image_type(source, Type::Set) || !image_type(dest, Type::Set)) {
                reply_wrongtype(op.sink()); return true;
            }
            std::vector<std::string> src, dst;
            if (!decode_elements(source, src) || (dest.present && !decode_elements(dest, dst))) {
                reply_err(op.sink(), "ERR out of memory"); return true;
            }
            const Slice member = op.arg(3);
            if (!contains(src, member)) { reply_int(op.sink(), 0); return true; }
            if (same_key(op)) { reply_int(op.sink(), 1); return true; }
            erase_member(src, member);
            if (!contains(dst, member)) dst.emplace_back(member.p, member.n);
            if (src.empty()) state.apply[1] = ObjectImage{};
            else if (!encode_elements(src, state.apply[1], Type::Set, source.expire_at_ms)) {
                reply_err(op.sink(), "ERR out of memory"); return true;
            }
            if (!encode_elements(dst, state.apply[2], Type::Set,
                                 dest.present ? dest.expire_at_ms : -1)) {
                reply_err(op.sink(), "ERR out of memory"); return true;
            }
            state.final_integer = 1; phase2 = {1, 2}; return false;
        }
        case Kind::Lmove:
        case Kind::Rpoplpush: {
            const ObjectImage& source = state.images[1];
            const ObjectImage& dest = state.images[2];
            if (!source.present) { reply_nil(op.sink()); return true; }
            if (!image_type(source, Type::List) || !image_type(dest, Type::List)) {
                reply_wrongtype(op.sink()); return true;
            }
            std::vector<std::string> src, dst;
            if (!decode_elements(source, src) || (dest.present && !decode_elements(dest, dst))) {
                reply_err(op.sink(), "ERR out of memory"); return true;
            }
            if (src.empty()) { reply_nil(op.sink()); return true; }
            std::string moved = state.from_left ? src.front() : src.back();
            if (state.from_left) src.erase(src.begin()); else src.pop_back();
            if (same_key(op)) {
                if (state.to_left) src.insert(src.begin(), moved); else src.push_back(moved);
                if (!encode_elements(src, state.apply[1], Type::List, source.expire_at_ms)) {
                    reply_err(op.sink(), "ERR out of memory"); return true;
                }
                phase2 = {1};
            } else {
                if (state.to_left) dst.insert(dst.begin(), moved); else dst.push_back(moved);
                if (src.empty()) state.apply[1] = ObjectImage{};
                else if (!encode_elements(src, state.apply[1], Type::List, source.expire_at_ms)) {
                    reply_err(op.sink(), "ERR out of memory"); return true;
                }
                if (!encode_elements(dst, state.apply[2], Type::List,
                                     dest.present ? dest.expire_at_ms : -1)) {
                    reply_err(op.sink(), "ERR out of memory"); return true;
                }
                phase2 = {1, 2};
            }
            state.final_bulk = std::move(moved);
            return false;
        }
        default:
            if (is_plain_setop(state.kind) || state.kind == Kind::Sintercard ||
                is_store_setop(state.kind)) {
                if (!compute_setop(state, op)) return true;
                if (state.kind == Kind::Sintercard) {
                    uint64_t count = state.final_members.size();
                    if (state.sinter_limit && count > state.sinter_limit) count = state.sinter_limit;
                    reply_int(op.sink(), static_cast<long long>(count)); return true;
                }
                if (is_plain_setop(state.kind)) {
                    reply_array_header(op.sink(), state.final_members.size());
                    for (const std::string& member : state.final_members)
                        reply_bulk(op.sink(), Slice(member.data(), static_cast<uint32_t>(member.size())));
                    return true;
                }
                if (state.final_members.empty()) state.apply[1] = ObjectImage{};
                else if (!encode_elements(state.final_members, state.apply[1], Type::Set, -1)) {
                    reply_err(op.sink(), "ERR out of memory"); return true;
                }
                state.final_integer = static_cast<long long>(state.final_members.size());
                phase2 = {1}; return false;
            }
            reply_err(op.sink(), "ERR internal cross-shard phase error"); return true;
    }
}

void finish_phase2_reply(ScatterState& state, Op& op) {
    WorkError error;
    if (first_error(state, error)) { reply_work_error(op, error); return; }
    switch (state.kind) {
        case Kind::Msetnx: reply_int(op.sink(), 1); break;
        case Kind::Rename: reply_ok(op.sink()); break;
        case Kind::Renamenx:
        case Kind::Copy:
        case Kind::Smove:
        case Kind::Sinterstore:
        case Kind::Sunionstore:
        case Kind::Sdiffstore: reply_int(op.sink(), state.final_integer); break;
        case Kind::Lmove:
        case Kind::Rpoplpush:
            reply_bulk(op.sink(), Slice(state.final_bulk.data(),
                                        static_cast<uint32_t>(state.final_bulk.size()))); break;
        default: reply_err(op.sink(), "ERR internal cross-shard completion error"); break;
    }
}

}  // namespace

ScatterFinish xshard_complete(Server& server, ThreadCtx& self, Ring& ring,
                              const Task& task, Op& op) {
    ScatterState& state = *task.scatter;
    if (state.pending.fetch_sub(1, std::memory_order_acq_rel) != 1)
        return ScatterFinish::Waiting;

    if (state.phase == 2) {
        finish_phase2_reply(state, op);
        delete &state;
        return ScatterFinish::Final;
    }

    WorkError error;
    if (!is_two_hop(state.kind)) {
        if (first_error(state, error)) reply_work_error(op, error);
        else switch (state.kind) {
            case Kind::AllShards: reply_ok(op.sink()); break;
            case Kind::Mget:
                reply_array_header(op.sink(), op.argc() - 1);
                for (uint32_t arg = 1; arg < op.argc(); arg++) {
                    const ValueSlot& slot = state.values[arg];
                    if (!slot.present) reply_nil(op.sink());
                    else reply_bulk(op.sink(), Slice(slot.value.data(),
                                                     static_cast<uint32_t>(slot.value.size())));
                }
                break;
            case Kind::Mset: reply_ok(op.sink()); break;
            case Kind::Del:
            case Kind::Unlink:
            case Kind::Exists:
            case Kind::Touch: {
                uint64_t count = 0;
                for (const ShardGroup& group : state.groups) count += group.count;
                reply_int(op.sink(), static_cast<long long>(count)); break;
            }
            case Kind::Keys: {
                uint64_t count = 0;
                for (const ShardGroup& group : state.groups) count += group.keys_result.size();
                reply_array_header(op.sink(), count);
                for (const ShardGroup& group : state.groups)
                    for (const std::string& key : group.keys_result)
                        reply_bulk(op.sink(), Slice(key.data(), static_cast<uint32_t>(key.size())));
                break;
            }
            default: reply_err(op.sink(), "ERR internal cross-shard completion error"); break;
        }
        delete &state;
        return ScatterFinish::Final;
    }

    std::vector<uint32_t> phase2;
    try {
        if (finish_phase1(state, op, phase2)) {
            delete &state;
            return ScatterFinish::Final;
        }
    } catch (const std::bad_alloc&) {
        reply_err(op.sink(), "ERR out of memory");
        delete &state;
        return ScatterFinish::Final;
    }
    if (!publish_phase2(server, self, ring, task, op, state, phase2)) {
        delete &state;
        return ScatterFinish::Final;
    }
    return ScatterFinish::Waiting;
}

}  // namespace tomo
