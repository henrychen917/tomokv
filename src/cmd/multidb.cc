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

bool DatabaseMap::swap(uint8_t first, uint8_t second) {
    std::lock_guard lock(writer_);
    try {
        auto next = std::make_unique<Map>();
        if (live_) *next = *live_;
        else for (unsigned i = 0; i < next->size(); ++i) (*next)[i] = i;
        std::swap((*next)[first], (*next)[second]);
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
        client->arm_multidb();
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
} // namespace tomo
