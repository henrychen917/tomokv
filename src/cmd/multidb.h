// Logical databases are namespaces in the existing owner-sharded store.
#pragma once

#include <array>
#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <vector>
#include "../base/slice.h"

namespace tomo {
class Server;
class Client;
class Op;
class Shard;
class AofProducer;

// An immutable mapping gives readers a single, non-retrying snapshot, including
// both ends of COPY/MOVE. Publication never waits for a reader. The counter only
// delays reclamation; it is absent until a database has actually been swapped.
class DatabaseMap {
public:
    struct Map : std::array<uint8_t, 256> {
        std::array<uint64_t, 256> versions{};
        Map() { for (unsigned i = 0; i < size(); ++i) (*this)[i] = i; }
    };
    class Read {
    public:
        explicit Read(const DatabaseMap& owner) : owner_(owner) {
            owner_.readers_.fetch_add(1, std::memory_order_seq_cst);
            map_ = owner_.current_.load(std::memory_order_seq_cst);
        }
        ~Read() { owner_.readers_.fetch_sub(1, std::memory_order_seq_cst); }
        uint8_t operator[](uint8_t db) const { return map_ ? (*map_)[db] : db; }
        uint64_t version(uint8_t db) const { return map_ ? map_->versions[db] : 0; }
    private:
        const DatabaseMap& owner_;
        const Map* map_;
    };
    bool remapped() const { return current_.load(std::memory_order_acquire) != nullptr; }
    bool swap(uint8_t first, uint8_t second, AofProducer* journal = nullptr);
    bool restore(const uint8_t* bytes);
    Map capture() const;
    uint8_t logical(uint8_t physical) const;
private:
    mutable std::atomic<uint32_t> readers_{0};
    std::atomic<const Map*> current_{nullptr};
    std::mutex writer_;
    std::unique_ptr<Map> live_;
    std::vector<std::unique_ptr<Map>> retired_;
};

// Cold, owning representations (WATCH, blocking registries) include the namespace
// explicitly; binary keys, including leading NULs, are never reserved or escaped.
inline std::string database_owned_key(Slice key) {
    std::string result(1, static_cast<char>(key.ns));
    result.append(key.p, key.n);
    return result;
}

struct DatabaseKey {
    std::string bytes;
    uint8_t ns;
    explicit DatabaseKey(Slice key) : bytes(key.p, key.n), ns(key.ns) {}
    Slice slice() const { return Slice(bytes.data(), bytes.size(), ns); }
};

void multidb_stamp(Server& server, Op& op, uint8_t logical);
void multidb_select(Server* server, Client* client, Op& op);
bool multidb_parse_index(Slice arg, uint32_t count, uint8_t& db);
void multidb_flush(Shard& shard, uint8_t physical);
uint64_t multidb_size(Shard& shard, uint8_t physical, uint64_t cut);
uint64_t multidb_random(uint64_t bound);
bool multidb_prepare_move(Server& server, Op& op);
bool multidb_validate_swap(Server& server, Op& op);
bool multidb_commit_swap(Server& server, Shard& shard, Op& op);
struct DatabaseStats { uint64_t keys = 0, expires = 0, ttl = 0; };
using DatabaseStatsTable = std::array<DatabaseStats, 256>;
void multidb_stats(Shard& shard, DatabaseStatsTable& stats);
void command_info_with_databases(Server& server, Op& op, const DatabaseStatsTable& stats);
} // namespace tomo
