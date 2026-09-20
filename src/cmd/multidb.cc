#include "multidb.h"
#include <charconv>
#include "cmdmeta.h"
#include "command.h"
#include "../core/server.h"
#include "../core/shard.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include "../base/numeric.h"
#include "blocking.h"

namespace tomo {
namespace {
bool parse_i64_canonical(Slice arg, int64_t& value) {
    if (!arg.n || arg.p[0] == '+' || (arg.n > 1 && arg.p[0] == '0') ||
        (arg.n > 1 && arg.p[0] == '-' && arg.p[1] == '0')) return false;
    auto result = std::from_chars(arg.p, arg.p + arg.n, value);
    return result.ec == std::errc{} && result.ptr == arg.p + arg.n;
}
}

// Acknowledgements are cold and cache-line separated just like client_work_.
// No epoch array is allocated per publication: one monotonic grace ticket covers
// all older versions. The vector and all commit storage are writer-owned.
struct DatabaseMap::State {
    struct alignas(64) Participant { std::atomic<uint64_t> acknowledged{0}; };
    struct Retired { std::unique_ptr<Map> map; uint64_t request; };
    std::unique_ptr<Map> live;
    std::vector<Retired> retired;
    std::unique_ptr<Participant[]> participants;
    uint32_t count = 0;  // immutable after bind_workers, before thread creation
    std::atomic<uint64_t> requested{0};
};

DatabaseMap::DatabaseMap() noexcept = default;
// Caller has stopped/joined all readers, including cold readers. No early free
// is attempted for participants that stopped without acknowledging the last swap.
DatabaseMap::~DatabaseMap() = default;

#ifdef TOMO_MDBQSBR_TEST
size_t DatabaseMapTest::backlog(const DatabaseMap& map) {
    return map.state_ ? map.state_->retired.size() : 0;
}
uint64_t DatabaseMapTest::acknowledged(const DatabaseMap& map, uint32_t tid) {
    return map.state_->participants[tid].acknowledged.load(std::memory_order_acquire);
}
#endif

DatabaseMap::State& DatabaseMap::state() {
    if (!state_) state_ = std::make_unique<State>();
    return *state_;
}

bool DatabaseMap::bind_workers(uint32_t count) {
    if constexpr (kSingleDatabase) return true;
    std::lock_guard lock(writer_);
    try {
        auto& s = state();
        if (!count || s.count) std::abort();
        auto participants = std::make_unique<State::Participant[]>(count);
        s.participants = std::move(participants);
        s.count = count;
        return true;
    } catch (const std::bad_alloc&) { return false; }
}

void DatabaseMap::publish(std::unique_ptr<Map> next) noexcept {
    auto& s = *state_;
    const bool retiring = bool(s.live);
    const uint64_t request = s.requested.load(std::memory_order_relaxed) + 1;
    if (!request || (retiring && s.retired.size() == s.retired.capacity())) std::abort();
#ifdef TOMO_MDBQSBR_TEST
    if (DatabaseMapTestHooks::fault == DatabaseMapTestHooks::SampledEven) {
        DatabaseMapTestHooks::sampled_even = 0;
        for (uint32_t tid = 0; tid < s.count; ++tid)
            if (!(DatabaseMapTestHooks::server->client_work_epoch(tid) & 1))
                DatabaseMapTestHooks::sampled_even |= uint64_t{1} << tid;
    }
    if (DatabaseMapTestHooks::before_publish) DatabaseMapTestHooks::before_publish();
#endif
    // Initialization -> release pointer -> release request. Every old reader,
    // including this stack and sampled-even/parked workers, owes an acquire of
    // this request at a subsequent true safe point. Do NOT exempt the publisher.
#ifdef TOMO_MDBQSBR_PAD
    // Measurement-only type A: the real PRE shared counter, at its original
    // offset/line, and writer-observed-global-zero reclamation. Never a knob.
    current_.store(next.get(), std::memory_order_seq_cst);
#else
    current_.store(next.get(), std::memory_order_release);
#endif
    if (retiring) s.retired.push_back({std::move(s.live), request});
    s.live = std::move(next);
#ifdef TOMO_MDBQSBR_PAD
    if (grace_work_.load(std::memory_order_seq_cst) == 0) s.retired.clear();
#else
    if (retiring) {
        s.requested.store(request, std::memory_order_release);
        grace_work_.store(1, std::memory_order_release);
    }
#endif
}

void DatabaseMap::quiescent(Server& server, uint32_t tid) {
    if constexpr (kSingleDatabase) return;
    // Gate before dereferencing cold state, reading epochs, or taking the mutex.
    if (!reclamation_pending()) return;
    auto& s = *state_;
    if (!s.count) return; // explicit unbound/cold lifetime: retain until destruction
    if (tid >= s.count) std::abort();
    // Same-thread nesting check, never an inference from a remote even snapshot.
    if (server.client_work_epoch(tid) & 1) {
#ifdef TOMO_MDBQSBR_TEST
        if (DatabaseMapTestHooks::fault != DatabaseMapTestHooks::NestedAck) return;
#else
        return;
#endif
    }
    const uint64_t request = s.requested.load(std::memory_order_acquire);
    auto& ack = s.participants[tid].acknowledged;
    if (ack.load(std::memory_order_relaxed) != request)
        ack.store(request, std::memory_order_release);
    // One fixed physical participant owns maintenance regardless of IO/EX role.
    // It polls only with actual retirement work. No per-idle-map thread scan.
    if (tid == 0) reclaim(server);
}

void DatabaseMap::reclaim([[maybe_unused]] Server& server) {
    if (!reclamation_pending()) return;
    std::unique_lock lock(writer_, std::try_to_lock);
    if (!lock.owns_lock()) return; // a reader's coarse pass never waits for a writer
    auto& s = *state_;
    if (s.retired.empty() || !s.count) return;
#ifdef TOMO_MDBQSBR_TEST
    ++DatabaseMapTestHooks::scans;
    if (DatabaseMapTestHooks::fault == DatabaseMapTestHooks::NoReclaim) return;
    if (DatabaseMapTestHooks::fault == DatabaseMapTestHooks::GlobalIdle)
        for (uint32_t tid = 0; tid < s.count; ++tid)
            if (server.client_work_epoch(tid) & 1) return;
#endif
    uint64_t through = s.requested.load(std::memory_order_relaxed);
    for (uint32_t tid = 0; tid < s.count; ++tid) {
#ifdef TOMO_MDBQSBR_TEST
        if (DatabaseMapTestHooks::fault == DatabaseMapTestHooks::ImmediateFree ||
            (DatabaseMapTestHooks::fault == DatabaseMapTestHooks::SampledEven &&
             (DatabaseMapTestHooks::sampled_even & (uint64_t{1} << tid)))) continue;
#endif
        through = std::min(through, s.participants[tid].acknowledged.load(std::memory_order_acquire));
    }
    // A newer odd scope is fine: its preceding request acquisition makes the
    // publication happen-before every map load in that scope. Conversely even,
    // parked, or a changed client epoch alone is NEVER sufficient evidence.
    auto end = s.retired.begin();
    while (end != s.retired.end() && end->request <= through) ++end;
    s.retired.erase(s.retired.begin(), end);
    if (s.retired.empty()) grace_work_.store(0, std::memory_order_relaxed);
}

bool DatabaseMap::swap(uint8_t first, uint8_t second, AofProducer* journal) {
    if constexpr (kSingleDatabase) return first == 0 && second == 0;
    if (first == second) return true;
    std::lock_guard lock(writer_);
    try {
        auto& s = state();
        auto next = std::make_unique<Map>();
        if (s.live) *next = *s.live;
        std::swap((*next)[first], (*next)[second]);
        ++next->epoch;
        if (s.live) s.retired.reserve(s.retired.size() + 1);
#ifdef TOMO_MDBQSBR_TEST
        if (journal && DatabaseMapTestHooks::fault == DatabaseMapTestHooks::JournalOrder) {
            const auto bytes = *next;
            publish(std::move(next));
            return journal->record_database_map(bytes.data());
        }
#endif
        if (journal && !journal->record_database_map(next->data())) return false;
        publish(std::move(next));
        return true;
    } catch (const std::bad_alloc&) { return false; }
}

DatabaseMap::Map DatabaseMap::capture() const {
    Read read(*this);
    Map map;
    for (unsigned i = 0; i < map.size(); ++i) {
        map[i] = read[i];
    }
    map.epoch = read.epoch();
    return map;
}

bool DatabaseMap::prepare_publish(const Map& map, std::unique_ptr<Map>& prepared) {
    if constexpr (kSingleDatabase) return false; // no publication/state in DB0
    std::lock_guard lock(writer_);
    prepared.reset();
    try {
        auto& s = state();
        auto next = std::make_unique<Map>(map);
        s.retired.reserve(s.retired.size() + 1);
        prepared = std::move(next);
        return true;
    } catch (const std::bad_alloc&) { return false; }
}

void DatabaseMap::publish_prepared(std::unique_ptr<Map> prepared) {
    if constexpr (kSingleDatabase) std::abort();
    // Only the globally fenced transaction can publish between prepare and here.
    // Record, map, participant array and queue capacity already exist. No scan,
    // allocation, or free is necessary in this non-failing commit arm.
    std::lock_guard lock(writer_);
    if (!prepared || !state_) std::abort();
#ifdef TOMO_MDBQSBR_TEST
    if (DatabaseMapTestHooks::fault == DatabaseMapTestHooks::CommitAllocation) {
        void* allocation = ::operator new(1);
        ::operator delete(allocation);
    }
#endif
    publish(std::move(prepared));
}

bool DatabaseMap::restore(const uint8_t* bytes) {
    std::lock_guard lock(writer_);
    bool identity = true;
    for (unsigned i = 0; i < 256; ++i) identity &= bytes[i] == i;
    if constexpr (kSingleDatabase) return identity;
    if (identity && (!state_ || !state_->live)) return true;
    try {
        auto& s = state();
        auto next = std::make_unique<Map>();
        next->epoch = s.live ? s.live->epoch + 1 : 1;
        bool seen[256]{};
        for (unsigned i = 0; i < next->size(); ++i) {
            if (seen[bytes[i]]) return false;
            seen[bytes[i]] = true; (*next)[i] = bytes[i];
        }
        if (s.live) s.retired.reserve(s.retired.size() + 1);
        publish(std::move(next));
        return true;
    } catch (const std::bad_alloc&) { return false; }
}

uint8_t DatabaseMap::logical(uint8_t physical) const {
    Read map(*this);
    for (unsigned i = 0; i < 256; ++i)
        if (map[i] == physical) return i;
    std::abort();
}

bool multidb_parse_index(Slice arg, uint32_t count, uint8_t& db) {
    int64_t value;
    if (!parse_i64_canonical(arg, value) || value < 0 || uint64_t(value) >= count) return false;
    db = static_cast<uint8_t>(value);
    return true;
}

static bool stamp_regular_range(Op& op) {
    const CommandSpec* spec = op.spec;
    if (!spec) return false;
    // These rows describe a routing hint, not an exact key range. In particular,
    // scripts include ARGV, streams include IDs, and containers have keyless arms.
    constexpr uint32_t dynamic = CmdFlags::ScriptRoute | CmdFlags::StreamRoute |
                                 CmdFlags::Blocking | CmdFlags::SubcmdRoute;
    if (spec->flags & dynamic) return false;
    // Admit only the audited whole-tail scatter families: DEL/UNLINK/EXISTS/TOUCH,
    // MGET/MSET/MSETNX, PFCOUNT/PFMERGE, and S{DIFF,INTER,UNION}[STORE]. Their
    // minimum arity is <= 3; the superficially identical Z*STORE and GEORADIUS
    // ranges need >= 4 and contain counts/options. Other scatter rows stay cold
    // (notably COPY/MOVE endpoints and SORT's optional destination).
    if ((spec->flags & CmdFlags::MultiShard) &&
        !(spec->first_key == 1 && spec->last_key == -1 && spec->min_arity <= 3))
        return false;
    if (spec->first_key > 0 && spec->key_step > 0) {
        const int64_t argc = op.argc();
        const int64_t last = spec->last_key < 0 ? argc + spec->last_key : spec->last_key;
        for (int64_t key = spec->first_key; key <= last && key < argc; key += spec->key_step)
            op.set_arg_namespace(static_cast<uint32_t>(key), op.physical_db);
    }
    return true;
}

template <typename Map>
static void stamp(Server& server, Op& op, uint8_t logical, const Map& map) {
    op.db = logical;
    op.physical_db = map[logical];
    op.target_db = logical;
    op.secondary_db = op.physical_db;
    if (stamp_regular_range(op)) return;
    if (op.cmd_name().eq_icase("move") && op.argc() == 3)
        multidb_parse_index(op.arg(2), server.cfg().databases, op.target_db);
    if (op.cmd_name().eq_icase("copy"))
        for (uint32_t i = 3; i + 1 < op.argc(); ++i)
            if (op.arg(i).eq_icase("db"))
                multidb_parse_index(op.arg(++i), server.cfg().databases, op.target_db);
    op.secondary_db = map[op.target_db];
#ifdef TOMO_MDBQSBR_TEST
    if constexpr (std::is_same_v<Map, DatabaseMap::Read>) {
        if (DatabaseMapTestHooks::fault == DatabaseMapTestHooks::SecondLoad) {
            DatabaseMap::Read second(server.databases());
            op.secondary_db = second[op.target_db];
        }
    }
#endif
    std::vector<CommandKeyMetadata> keys;
    if (const auto* metadata = command_metadata_resolve(op, 0)) {
        command_metadata_collect_keys(op, 0, *metadata, keys);
        for (const auto& key : keys) op.set_arg_namespace(key.argument, op.physical_db);
    }
    if (op.cmd_name().eq_icase("copy") && op.argc() >= 3)
        op.set_arg_namespace(2, op.secondary_db);
}

void multidb_stamp(Server& server, Op& op, uint8_t logical) {
    if constexpr (kSingleDatabase) return;
    const DatabaseMap::Read map(server.databases());
    stamp(server, op, logical, map);
}

void multidb_stamp(Server& server, Op& op, uint8_t logical, const DatabaseMap::Map& map) {
    if constexpr (kSingleDatabase) return;
    stamp(server, op, logical, map);
}

bool Server::database_boundary_begin(Client& client, uint32_t owner, uint64_t op_id) {
    if constexpr (kSingleDatabase) return true;
    std::lock_guard lock(shape_transition_mu_);
    if (database_boundary_active())
        return flip_stage() == FlipStage::DatabaseRun &&
               databases_.boundary_client.load() == &client && databases_.boundary_op.load() == op_id;
    if (flip_stage() != FlipStage::Idle || lb_stage() != LbStage::Idle ||
        snapshot_.in_progress() || loading()) return false;
    // Reuse the Client's existing cold lifetime reference while its initiating
    // frame is still unconsumed (including disconnect during either drain).
    client.watch_ref();
    databases_.boundary_client.store(&client);
    databases_.boundary_op.store(op_id);
    databases_.boundary_owner.store(owner);
    for (uint32_t tid = 0; tid < nthreads(); ++tid) flip_ack_[tid].store(0);
    flip_epoch_.fetch_add(1, std::memory_order_acq_rel);
    flip_stage_.store(FlipStage::DatabaseIoDrain, std::memory_order_release);
    if (Ring* ring = thread(owner).ring())
        for (uint32_t tid = 0; tid < nthreads(); ++tid)
            if (tid != owner) thread(tid).wake_if_parked(*ring, thread(owner).sig());
    return false;
}

void Server::database_boundary_end(Client& client, uint64_t op_id) {
    if constexpr (kSingleDatabase) return;
    std::lock_guard lock(shape_transition_mu_);
    if (!database_boundary_active() || databases_.boundary_client.load() != &client ||
        databases_.boundary_op.load() != op_id) return;
    databases_.boundary_client.store(nullptr);
    client.watch_unref();
    flip_stage_.store(FlipStage::Idle, std::memory_order_release);
}

bool multidb_dispatch_allowed(Server& server, const Client& client) {
    return server.flip_stage() == FlipStage::DatabaseRun &&
           server.databases().boundary_client.load() == &client &&
           server.databases().boundary_op.load() == client.rob().dispatch_id();
}

bool multidb_io_drained(ThreadCtx& thread) {
    for (Client* client : thread.clients()) {
        const auto& rob = client->rob();
        for (uint64_t id = rob.flush_id(); id != rob.dispatch_id(); ++id) {
            const Op& op = rob.at(id);
            if (op.state.load(std::memory_order_acquire) == OpState::Done) continue;
            if (op.has_blocking_state() && blocking_namespace_quiesced(op)) continue;
            return false;
        }
    }
    return true;
}

void multidb_select(Server* server, Client* client, Op& op) {
    int64_t parsed = 0;
    if (!parse_i64_canonical(op.arg(1), parsed)) {
        reply_err(op.sink(), "ERR invalid DB index"); return;
    }
    if (parsed < 0 || uint64_t(parsed) >= (server ? server->cfg().databases : 1)) {
        reply_err(op.sink(), "ERR DB index is out of range"); return;
    }
    if (client) {
        client->session().db_index = parsed;
    }
    reply_ok(op.sink());
}

uint64_t multidb_size(Shard& shard, uint8_t physical, uint64_t cut) {
    uint64_t size = 0;
    // Counts are physical: neither DBSIZE nor INFO may reap elapsed records.
    // This owner-local walk also counts each slot exactly once during rehash.
    shard.store().for_each([&](KvObj* object) {
        Slice key = object->key();
        if (key.ns == physical && shard.store().atomic_physical_key_visible(
                FlatStore::hash_key(key), key, cut)) ++size;
    });
    shard.store().atomic_for_each_side_key(cut, [&](Slice key) {
        if (key.ns == physical) ++size;
    });
    return size;
}

void multidb_flush(Shard& shard, uint8_t physical) {
    std::vector<std::string> keys;
    uint64_t cursor = 0;
    do {
        cursor = shard.store().scan(cursor, 256, [&](KvObj* object) {
            if (object->key_namespace() == physical)
                keys.emplace_back(object->key().sv());
        });
    } while (cursor);
    for (const auto& owned : keys) {
        Slice key(owned.data(), owned.size(), physical);
        shard.store().erase(FlatStore::hash_key(key), key);
    }
    shard.publish_size();
}

uint64_t multidb_random(uint64_t bound) {
    thread_local uint64_t state = 0xa0761d6478bd642fULL;
    state ^= state << 13; state ^= state >> 7; state ^= state << 17;
    return bound ? state % bound : 0;
}

bool multidb_prepare_move(Server& server, Op& op) {
    // Lowered MOVE retains argc=3; the destination aliases the source bytes with a new identity.
    if (op.arg(1).p == op.arg(2).p && op.arg(1).ns != op.arg(2).ns) return true;
    int64_t db;
    if (!parse_i64_canonical(op.arg(2), db)) {
        reply_err(op.sink(), "ERR value is not an integer or out of range"); return false;
    }
    if (db < INT32_MIN || db > INT32_MAX) {
        reply_err(op.sink(), "ERR value is out of range, value must between "
                             "-2147483648 and 2147483647"); return false;
    }
    if (db < 0 || uint64_t(db) >= server.cfg().databases) {
        reply_err(op.sink(), "ERR DB index is out of range"); return false;
    }
    if (db == op.db) {
        reply_err(op.sink(), "ERR source and destination objects are the same"); return false;
    }
    Slice destination = op.arg(1);
    destination.set_namespace(op.secondary_db);
    // MOVE has three arguments, leaving an unused inline slot for its original DB text.
    // Observability must print the original request after the transfer lowering.
    op.replace_arg(3, op.arg(2));
    op.replace_arg(2, destination);
    return true;
}

Slice multidb_display_argument(const Op& op, uint32_t argument) {
    if (argument == 2 && op.argc() == 3 && op.cmd_name().eq_icase("move") &&
        op.arg(1).p == op.arg(2).p && op.arg(1).ns != op.arg(2).ns)
        return op.arg(3);
    return op.arg(argument);
}

bool multidb_validate_swap(Server& server, Op& op) {
    int64_t indexes[2]{};
    for (unsigned i = 0; i < 2; ++i) {
        if (!parse_i64_canonical(op.arg(i + 1), indexes[i]) ||
            indexes[i] < INT32_MIN || indexes[i] > INT32_MAX) {
            reply_err(op.sink(), i == 0 ? "ERR invalid first DB index" : "ERR invalid second DB index");
            return false;
        }
    }
    for (const auto index : indexes) {
        if (index < 0 || uint64_t(index) >= server.cfg().databases) {
            reply_err(op.sink(), "ERR DB index is out of range"); return false;
        }
    }
    return true;
}

bool multidb_commit_swap(Server& server, Shard& shard, Op& op) {
    uint8_t first = 0, second = 0;
    if (!multidb_parse_index(op.arg(1), server.cfg().databases, first) ||
        !multidb_parse_index(op.arg(2), server.cfg().databases, second)) std::abort();
    return server.databases().swap(first, second, &shard.store().aof());
}

void multidb_stats(Shard& shard, DatabaseStatsTable& stats) {
    shard.store().for_each([&](KvObj* object) {
            auto& row = stats[object->key_namespace()];
            ++row.keys;
            const int64_t deadline = object->expire_at_ms();
            if (deadline >= 0) {
                ++row.expires;
                row.ttl += std::max<int64_t>(0, deadline - shard.now_ms());
            }
    });
}
} // namespace tomo
