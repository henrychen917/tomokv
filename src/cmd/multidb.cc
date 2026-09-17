#include "multidb.h"
#include <charconv>
#include "cmdmeta.h"
#include "command.h"
#include "../core/server.h"
#include "../core/shard.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include "../base/numeric.h"

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
    if (first == second) return true;
    std::lock_guard lock(writer_);
    try {
        auto next = std::make_unique<Map>();
        if (live_) *next = *live_;
        else for (unsigned i = 0; i < next->size(); ++i) (*next)[i] = i;
        std::swap((*next)[first], (*next)[second]);
        if (first != second) { ++next->versions[first]; ++next->versions[second]; }
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
        map[i] = read[i]; map.versions[i] = read.version(i);
    }
    return map;
}

bool DatabaseMap::restore(const uint8_t* bytes) {
    std::lock_guard lock(writer_);
    bool identity = true;
    for (unsigned i = 0; i < 256; ++i) identity &= bytes[i] == i;
    if (identity && !live_) return true;
    try {
        auto next = std::make_unique<Map>();
        bool seen[256]{};
        for (unsigned i = 0; i < next->size(); ++i) {
            if (seen[bytes[i]]) return false;
            seen[bytes[i]] = true; (*next)[i] = bytes[i];
            next->versions[i] = live_ ? live_->versions[i] + 1 : 0;
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

// The noipa boundary is also the kind-A artifact's patch point: force this
// function to return zero without changing any linked text addresses or sizes.
__attribute__((noipa)) uint8_t multidb_namespace(uint8_t physical) { return physical; }

void multidb_stamp(Server& server, Op& op, uint8_t logical) {
    DatabaseMap::Read map(server.databases());
    op.db = logical;
    op.physical_db = multidb_namespace(map[logical]);
    op.target_db = logical;
    op.secondary_db = op.physical_db;
    if (op.cmd_name().eq_icase("move") && op.argc() == 3)
        multidb_parse_index(op.arg(2), server.cfg().databases, op.target_db);
    if (op.cmd_name().eq_icase("copy"))
        for (uint32_t i = 3; i + 1 < op.argc(); ++i)
            if (op.arg(i).eq_icase("db"))
                multidb_parse_index(op.arg(++i), server.cfg().databases, op.target_db);
    op.secondary_db = multidb_namespace(map[op.target_db]);
    std::vector<CommandKeyMetadata> keys;
    if (const auto* metadata = command_metadata_resolve(op, 0)) {
        command_metadata_collect_keys(op, 0, *metadata, keys);
        for (const auto& key : keys) op.set_arg_namespace(key.argument, op.physical_db);
    }
    if (op.cmd_name().eq_icase("copy") && op.argc() >= 3)
        op.set_arg_namespace(2, op.secondary_db);
}

void multidb_select(Server* server, Client* client, Op& op) {
    int64_t parsed = 0;
    if (!parse_i64_canonical(op.arg(1), parsed)) {
        reply_err(op.sink(), "ERR invalid DB index"); return;
    }
    if (parsed < 0 || uint64_t(parsed) >= (server ? server->cfg().databases : 16)) {
        reply_err(op.sink(), "ERR DB index is out of range"); return;
    }
    if (client) {
        client->session().db_index = parsed;
        if (parsed != 0) client->arm_multidb();
    }
    reply_ok(op.sink());
}

uint64_t multidb_size(Shard& shard, uint8_t physical, uint64_t cut) {
    uint64_t size = 0, cursor = 0;
    do {
        cursor = shard.store().scan(cursor, 256, [&](KvObj* object) {
            Slice key = object->key();
            if (key.ns == physical && shard.store().atomic_physical_key_visible(
                    FlatStore::hash_key(key), key, cut)) ++size;
        });
    } while (cursor);
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
    if (db < 0 || uint64_t(db) >= server.cfg().databases) {
        reply_err(op.sink(), "ERR DB index is out of range"); return false;
    }
    if (db == op.db) {
        reply_err(op.sink(), "ERR source and destination objects are the same"); return false;
    }
    multidb_stamp(server, op, op.db);
    Slice destination = op.arg(1);
    destination.ns = op.secondary_db;
    op.replace_arg(2, destination);
    return true;
}

bool multidb_validate_swap(Server& server, Op& op) {
    uint8_t first, second;
    if (!multidb_parse_index(op.arg(1), server.cfg().databases, first) ||
        !multidb_parse_index(op.arg(2), server.cfg().databases, second)) {
        reply_err(op.sink(), "ERR invalid DB index"); return false;
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
    uint64_t cursor = 0;
    do {
        cursor = shard.store().scan(cursor, 256, [&](KvObj* object) {
            auto& row = stats[object->key_namespace()];
            ++row.keys;
            const int64_t deadline = object->expire_at_ms();
            if (deadline >= 0) {
                ++row.expires;
                row.ttl += std::max<int64_t>(0, deadline - shard.now_ms());
            }
        });
    } while (cursor);
}
} // namespace tomo
