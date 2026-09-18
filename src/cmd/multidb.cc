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

bool DatabaseMap::swap(uint8_t first, uint8_t second, AofProducer* journal) {
    if constexpr (kSingleDatabase) return first == 0 && second == 0;
    if (first == second) return true;
    std::lock_guard lock(writer_);
    try {
        auto next = std::make_unique<Map>();
        if (live_) *next = *live_;
        else for (unsigned i = 0; i < next->size(); ++i) (*next)[i] = i;
        std::swap((*next)[first], (*next)[second]);
        ++next->epoch;
        if (live_) retired_.reserve(retired_.size() + 1);
        if (journal && !journal->record_database_map(next->data())) return false;
        current_.store(next.get(), std::memory_order_seq_cst);
        if (live_) retired_.push_back(std::move(live_));
        live_ = std::move(next);
        if (readers_.load(std::memory_order_seq_cst) == 0) retired_.clear();
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
    std::lock_guard lock(writer_);
    try {
        prepared = std::make_unique<Map>(map);
        if (live_) retired_.reserve(retired_.size() + 1);
        return true;
    } catch (const std::bad_alloc&) { return false; }
}

void DatabaseMap::publish_prepared(std::unique_ptr<Map> prepared) {
    // Only the globally fenced transaction can publish between prepare and here.
    // All allocation happened before owner work; this commit arm cannot fail.
    std::lock_guard lock(writer_);
    if (!prepared || (live_ && retired_.size() == retired_.capacity())) std::abort();
    current_.store(prepared.get(), std::memory_order_seq_cst);
    if (live_) retired_.push_back(std::move(live_));
    live_ = std::move(prepared);
    if (readers_.load(std::memory_order_seq_cst) == 0) retired_.clear();
}

bool DatabaseMap::restore(const uint8_t* bytes) {
    std::lock_guard lock(writer_);
    bool identity = true;
    for (unsigned i = 0; i < 256; ++i) identity &= bytes[i] == i;
    if constexpr (kSingleDatabase) return identity;
    if (identity && !live_) return true;
    try {
        auto next = std::make_unique<Map>();
        next->epoch = live_ ? live_->epoch + 1 : 1;
        bool seen[256]{};
        for (unsigned i = 0; i < next->size(); ++i) {
            if (seen[bytes[i]]) return false;
            seen[bytes[i]] = true; (*next)[i] = bytes[i];
        }
        if (live_) retired_.reserve(retired_.size() + 1);
        current_.store(next.get(), std::memory_order_seq_cst);
        if (live_) retired_.push_back(std::move(live_));
        live_ = std::move(next);
        if (readers_.load(std::memory_order_seq_cst) == 0) retired_.clear();
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

template <typename Map>
static void stamp(Server& server, Op& op, uint8_t logical, const Map& map) {
    op.db = logical;
    op.physical_db = map[logical];
    op.target_db = logical;
    op.secondary_db = op.physical_db;
    if (op.cmd_name().eq_icase("move") && op.argc() == 3)
        multidb_parse_index(op.arg(2), server.cfg().databases, op.target_db);
    if (op.cmd_name().eq_icase("copy"))
        for (uint32_t i = 3; i + 1 < op.argc(); ++i)
            if (op.arg(i).eq_icase("db"))
                multidb_parse_index(op.arg(++i), server.cfg().databases, op.target_db);
    op.secondary_db = map[op.target_db];
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
