// Logical databases are namespaces in the existing owner-sharded store.
#pragma once

#include <array>
#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <vector>
#ifdef TOMO_MDBQSBR_TEST
#include <optional>
#endif
#include "../base/slice.h"

namespace tomo {
class Server;
class Client;
class Op;
class Shard;
class AofProducer;
class ThreadCtx;

#ifdef TOMO_MDBQSBR_TEST
// Deterministic interleavings/faults; absent from production and measurement arms.
struct DatabaseMapTestHooks {
    enum Fault { None, ImmediateFree, NoReclaim, SampledEven, NestedAck,
                 OmitIo, GlobalIdle, CommitAllocation, JournalOrder, SecondLoad };
    inline static Fault fault = None;
    inline static Server* server = nullptr;
    inline static uint64_t sampled_even = 0;
    inline static void (*loaded)(const void*) = nullptr;
    inline static void (*deleting)(const void*) = nullptr;
    inline static void (*before_publish)() = nullptr;
    inline static void (*loop_pass)(Server&, ThreadCtx&, unsigned) = nullptr;
    inline static std::atomic<size_t> allocated{0}, freed{0}, scans{0};
};
#endif

// An immutable mapping gives readers a single, non-retrying snapshot, including
// both ends of COPY/MOVE. Readers belong to a coarse physical-worker scope, NOT
// to this object: Read does no registration or publication. Cold/unbound maps
// retain versions until destruction. See quiescent() for the worker grace proof.
// No Read may outlive its scope (or its cold domain's externally joined lifetime).
class DatabaseMap {
public:
    DatabaseMap() noexcept;
    ~DatabaseMap();
    struct Map : std::array<uint8_t, 256> {
        uint32_t epoch = 0;
        Map() { for (unsigned i = 0; i < size(); ++i) (*this)[i] = i; }
#ifdef TOMO_MDBQSBR_TEST
        static void* operator new(size_t n) {
            void* p = ::operator new(n);
            ++DatabaseMapTestHooks::allocated;
            return p;
        }
        static void operator delete(void* p) {
            if (DatabaseMapTestHooks::deleting) DatabaseMapTestHooks::deleting(p);
            ++DatabaseMapTestHooks::freed;
            ::operator delete(p);
        }
#endif
    };
    class Read {
    public:
        explicit Read(const DatabaseMap& owner)
#if defined(TOMO_MDBQSBR_PAD) && !TOMO_SINGLE_DATABASE
            : owner_(owner)
#endif
        {
            if constexpr (!kSingleDatabase) {
#ifdef TOMO_MDBQSBR_PAD
                owner.grace_work_.fetch_add(1, std::memory_order_seq_cst);
                map_ = owner.current_.load(std::memory_order_seq_cst);
#else
                map_ = owner.current_.load(std::memory_order_acquire);
#endif
#ifdef TOMO_MDBQSBR_TEST
                if (DatabaseMapTestHooks::loaded) DatabaseMapTestHooks::loaded(map_);
#endif
            }
        }
#if defined(TOMO_MDBQSBR_PAD) && !TOMO_SINGLE_DATABASE
        ~Read() { owner_.grace_work_.fetch_sub(1, std::memory_order_seq_cst); }
#endif
        uint8_t operator[](uint8_t db) const { return map_ ? (*map_)[db] : db; }
        uint32_t epoch() const { return map_ ? map_->epoch : 0; }
    private:
#if defined(TOMO_MDBQSBR_PAD) && !TOMO_SINGLE_DATABASE
        const DatabaseMap& owner_;
#endif
        const Map* map_ = nullptr;
    };
    bool remapped() const {
        if constexpr (kSingleDatabase) return false;
        return current_.load(std::memory_order_acquire) != nullptr;
    }
    bool swap(uint8_t first, uint8_t second, AofProducer* journal = nullptr);
    bool prepare_publish(const Map& map, std::unique_ptr<Map>& prepared);
    void publish_prepared(std::unique_ptr<Map> prepared);
    bool restore(const uint8_t* bytes);
    Map capture() const;
    uint8_t logical(uint8_t physical) const;
    // Called once, before workers/recovery start. An unbound standalone map never
    // reclaims early. Bound cold callers must finish before worker grace resumes.
    bool bind_workers(uint32_t count);
    bool reclamation_pending() const {
        if constexpr (kSingleDatabase) return false;
#ifdef TOMO_MDBQSBR_PAD
        return false; // type A control: PRE reclaims only at writer-observed zero
#else
        return grace_work_.load(std::memory_order_relaxed) != 0;
#endif
    }
    // Only the named physical worker may acknowledge; deterministic offline
    // fixtures may impersonate it only after stopping/joining that worker.
    void quiescent(Server& server, uint32_t tid);
    // Cold boundary state. The existing FLIP stage is the dispatch fence; these
    // fields are read only while that already-existing fence is taken.
    std::atomic<Client*> boundary_client{nullptr};
    std::atomic<uint64_t> boundary_op{0};
    std::atomic<uint32_t> boundary_owner{0};
    bool admit_swap(const void* token) {
        const void* empty = nullptr;
        return swapping_.compare_exchange_strong(empty, token, std::memory_order_acq_rel);
    }
    void release_swap(const void* token) {
        swapping_.compare_exchange_strong(token, nullptr, std::memory_order_acq_rel);
    }
private:
    friend struct DatabaseMapTest;
    struct State;
    State& state();
    void publish(std::unique_ptr<Map> next) noexcept;
    void reclaim(Server& server);
    std::atomic<const void*> swapping_{nullptr};
    mutable std::atomic<uint32_t> grace_work_{0};
    std::atomic<const Map*> current_{nullptr};
    std::mutex writer_;
    std::unique_ptr<State> state_;
    // Keep DatabaseMap's size AND current_'s offset; Server embeds this before
    // hot members. Reuse the old vector footprint without touching it per pass.
    std::byte layout_padding_[sizeof(std::vector<std::unique_ptr<Map>>)];
};
static_assert(sizeof(DatabaseMap) == 120);

#ifdef TOMO_MDBQSBR_TEST
struct DatabaseMapTest {
    static size_t backlog(const DatabaseMap& map);
    static uint64_t acknowledged(const DatabaseMap& map, uint32_t tid);
    static void maintenance(DatabaseMap& map, Server& server) { map.reclaim(server); }
};
#endif

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
void multidb_stamp(Server& server, Op& op, uint8_t logical, const DatabaseMap::Map& map);
bool multidb_dispatch_allowed(Server& server, const Client& client);
bool multidb_io_drained(ThreadCtx& thread);
void multidb_select(Server* server, Client* client, Op& op);
bool multidb_parse_index(Slice arg, uint32_t count, uint8_t& db);
void multidb_flush(Shard& shard, uint8_t physical);
uint64_t multidb_size(Shard& shard, uint8_t physical, uint64_t cut);
uint64_t multidb_random(uint64_t bound);
bool multidb_prepare_move(Server& server, Op& op);
Slice multidb_display_argument(const Op& op, uint32_t argument);
bool multidb_validate_swap(Server& server, Op& op);
bool multidb_commit_swap(Server& server, Shard& shard, Op& op);
struct DatabaseStats { uint64_t keys = 0, expires = 0, ttl = 0; };
using DatabaseStatsTable = std::array<DatabaseStats, 256>;
void multidb_stats(Shard& shard, DatabaseStatsTable& stats);
void command_info_with_databases(Server& server, Op& op, const DatabaseStatsTable& stats);
} // namespace tomo
