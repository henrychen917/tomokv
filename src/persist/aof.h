// aof.h -- single-file AOF with owner-private logical shard streams.
//
// Executors serialize objects they own and post chunks; they never open or write files. One fixed
// IO thread drains all producer channels into one physical stream. appendonly=no leaves no channel,
// chunk, or producer allocation behind.
#pragma once

#include <atomic>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include "../core/signal.h"
#include "../snapshot/format.h"

namespace tomo {

class Config;
class FlatStore;
class Op;
class Ring;
class Server;
class Shard;
class ThreadCtx;

inline constexpr uint32_t kAofChunkBytes = 64 * 1024;

enum AofFrameFlags : uint32_t {
    AofFrameLargeBegin = 1u << 0,
    AofFrameLargeEnd = 1u << 1,
};

enum class AofRecordKind : uint8_t {
    Put = 1,
    Del = 2,
    Flush = 3,
    Timestamp = 4,
    GroupPut = 5,
    GroupDel = 6,
    GroupCommit = 7,
};

struct AofChunk {
    int32_t sid = -1;
    uint32_t sequence = 0;
    uint32_t flags = 0;
    uint32_t records = 0;
    std::vector<uint8_t> bytes;
};

class AofReplayPlan {
public:
    uint32_t shard_count = 0;
    uint32_t hash_kind = 0;
    uint64_t hash_seed = 0;
    uint64_t sip_k0 = 0;
    uint64_t sip_k1 = 0;
    uint64_t replayed_records = 0;
    uint64_t groups_skipped = 0;
    uint64_t valid_file_bytes = 0;
    std::vector<uint32_t> next_sequence;
    std::vector<std::vector<uint8_t>> sections;
};

struct AofOwnerContext {
    uint32_t producer = 0;
    Ring* ring = nullptr;
    LoopSignals* signals = nullptr;
};

class AofManager;

class AofProducer {
public:
    void init(AofManager* manager, int32_t sid, uint32_t next_sequence);
    bool enabled() const;
    int32_t sid() const { return sid_; }

    bool record_post_image(FlatStore& store, uint64_t hash, Slice key,
                           AofOwnerContext& context, uint64_t group = 0);
    bool record_post_image_buffered(FlatStore& store, uint64_t hash, Slice key,
                                    uint64_t group = 0);
    bool record_delete(Slice key, uint64_t group = 0);
    bool record_flush();
    bool flush(AofOwnerContext& context);
    bool has_pending() const { return build_ || !ready_.empty(); }

private:
    bool record_post_image_impl(FlatStore& store, uint64_t hash, Slice key,
                                AofOwnerContext* context, uint64_t group);
    bool record_bytes(AofRecordKind kind, uint8_t type, uint8_t encoding, Slice key,
                      int64_t expire_at_ms, uint64_t group, const uint8_t* payload,
                      uint64_t payload_len, const SnapshotTypeHooks* hooks,
                      SnapshotSaveCursor* cursor, AofOwnerContext* context);
    bool emit(const uint8_t* bytes, uint64_t length, bool large, AofOwnerContext* context);
    bool seal(uint32_t flags, AofOwnerContext* context);
    bool post_ready(AofOwnerContext& context);
    bool maybe_timestamp(int64_t now_ms, AofOwnerContext* context);
    std::unique_ptr<AofChunk> make_chunk(uint32_t flags = 0);

    AofManager* manager_ = nullptr;
    int32_t sid_ = -1;
    uint32_t sequence_ = 0;
    int64_t timestamp_second_ = -1;
    std::unique_ptr<AofChunk> build_;
    std::vector<std::unique_ptr<AofChunk>> ready_;
};

class AofManager {
public:
    AofManager() = default;
    ~AofManager();
    AofManager(const AofManager&) = delete;
    AofManager& operator=(const AofManager&) = delete;

    void init(const Config& config, uint32_t nthreads, uint32_t nshards,
              uint32_t writer_tid, const AofReplayPlan* replay);
    bool bind_writer(ThreadCtx& writer, Ring& ring, std::string& error);
    void writer_shutdown(ThreadCtx& writer, Ring& ring);
    uint32_t writer_pass(ThreadCtx& writer, Ring& ring, bool drain_all = false);
    bool post_chunk(uint32_t producer, std::unique_ptr<AofChunk>& chunk,
                    Ring& producer_ring, LoopSignals& signals);

    bool configured() const { return configured_; }
    bool recording() const { return recording_.load(std::memory_order_acquire); }
    bool writer_is(uint32_t tid) const { return configured_ && tid == writer_tid_; }
    bool timestamp_enabled() const { return timestamp_enabled_.load(std::memory_order_relaxed); }
    void set_timestamp_enabled(bool enabled) {
        timestamp_enabled_.store(enabled, std::memory_order_relaxed);
    }
    bool failed() const { return failed_.load(std::memory_order_acquire); }
    const std::string& file_path() const { return file_path_; }
    const std::string& directory_path() const { return directory_path_; }
    uint64_t records_written() const { return records_written_.load(std::memory_order_relaxed); }
    uint64_t replayed_records() const { return replayed_records_.load(std::memory_order_relaxed); }
    uint64_t groups_committed() const { return groups_committed_.load(std::memory_order_relaxed); }
    uint64_t groups_skipped() const { return groups_skipped_.load(std::memory_order_relaxed); }
    uint64_t current_size() const { return current_size_.load(std::memory_order_relaxed); }
    uint64_t pending_chunks() const { return pending_chunks_.load(std::memory_order_acquire); }
    const std::string& last_error() const { return last_error_; }

    void fail(const char* message);
    bool wait_until_drained(uint32_t timeout_ms);

private:
    using ChunkChan = Channel<AofChunk*, 64>;
    bool write_header();
    bool write_frame(const AofChunk& chunk);
    bool drain_producer(uint32_t producer, uint32_t& budget, uint32_t& consumed);
    void discard_chunks();

    bool configured_ = false;
    uint32_t nthreads_ = 0;
    uint32_t nshards_ = 0;
    uint32_t writer_tid_ = UINT32_MAX;
    std::unique_ptr<ChunkChan[]> chunk_in_;
    NotifyMask chunk_notify_;
    std::atomic<Ring*> writer_ring_{nullptr};
    std::atomic<bool> recording_{false};
    std::atomic<bool> failed_{false};
    std::atomic<bool> writer_ready_{false};
    std::atomic<uint64_t> pending_chunks_{0};
    std::atomic<uint64_t> records_written_{0};
    std::atomic<uint64_t> replayed_records_{0};
    std::atomic<uint64_t> groups_committed_{0};
    std::atomic<uint64_t> groups_skipped_{0};
    std::atomic<uint64_t> current_size_{0};
    std::atomic<bool> timestamp_enabled_{false};
    std::string directory_path_;
    std::string file_path_;
    std::string last_error_;
    int fd_ = -1;
    uint64_t file_offset_ = 0;
    uint64_t last_good_offset_ = 0;
    uint64_t large_record_offset_ = 0;
    uint32_t locked_producer_ = UINT32_MAX;
    uint32_t writer_cursor_ = 0;
    std::vector<uint32_t> next_sequence_;
};

std::string aof_directory_path(const Config& config);
std::string aof_file_path(const Config& config);
std::unique_ptr<AofReplayPlan> aof_read_plan(const char* path, uint32_t expected_shards,
                                             bool truncate_tail, bool& exists,
                                             std::string& warning, std::string& error);
bool aof_load_owned(const AofReplayPlan& plan, Server& server, ThreadCtx& owner,
                    std::string& error);
bool aof_load_shard(const AofReplayPlan& plan, Server& server, Shard& shard,
                    std::string& error);

bool aof_record_local_op(Shard& shard, Op& op, AofOwnerContext& context);

}  // namespace tomo
