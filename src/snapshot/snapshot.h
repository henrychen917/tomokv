// snapshot.h — process-wide epoch coordination, the one IO-side writer, and boot loading.
#pragma once

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>
#include <vector>
#include "format.h"
#include "../core/signal.h"

namespace tomo {

class Op;
class Ring;
class Server;
class ThreadCtx;

class SnapshotLoadPlan {
public:
    uint32_t shard_count = 0;
    uint32_t hash_kind = 0;
    uint64_t epoch = 0;
    int64_t cut_ms = 0;
    uint64_t hash_seed = 0;
    uint64_t sip_k0 = 0;
    uint64_t sip_k1 = 0;
    std::vector<std::vector<uint8_t>> sections;
};

std::unique_ptr<SnapshotLoadPlan> snapshot_read_plan(const char* path, uint32_t expected_shards,
                                                     std::string& error);
bool snapshot_load_owned(const SnapshotLoadPlan& plan, Server& server, ThreadCtx& owner,
                         std::string& error);

class SnapshotManager {
public:
    enum class Phase : uint8_t { Idle, Preparing, Freeze, Mark, Capture, Failed };
    enum class StartResult : uint8_t { Started, Busy, Failed };

    SnapshotManager() = default;
    ~SnapshotManager();
    SnapshotManager(const SnapshotManager&) = delete;
    SnapshotManager& operator=(const SnapshotManager&) = delete;

    void init(uint32_t nthreads, uint32_t nshards, uint32_t executor_count,
              const char* dir, const char* dbfilename);

    StartResult start(Server& server, ThreadCtx& writer, Ring& writer_ring, bool blocking,
                      std::string& error);
    uint32_t writer_pass(ThreadCtx& writer, Ring& writer_ring, bool drain_all = false);

    Phase phase() const { return phase_.load(std::memory_order_acquire); }
    uint64_t epoch() const { return epoch_.load(std::memory_order_acquire); }
    int64_t cut_ms() const { return cut_ms_.load(std::memory_order_acquire); }
    bool blocking() const { return blocking_.load(std::memory_order_relaxed); }
    uint32_t save_current_shard() const {
        return save_current_shard_.load(std::memory_order_acquire);
    }
    bool writer_is(uint32_t tid) const {
        return writer_tid_.load(std::memory_order_relaxed) == tid && phase() != Phase::Idle;
    }
    bool in_progress() const { return phase() != Phase::Idle; }
    int64_t last_save_time() const { return last_save_time_.load(std::memory_order_relaxed); }

    void owner_ready(uint64_t epoch);
    void owner_frozen(uint64_t epoch);
    void owner_marked(uint64_t epoch);
    void owner_cancelled(uint64_t epoch);
    void owner_finished(uint64_t epoch);
    void fail(uint64_t epoch, const char* reason);

    bool post_chunk(uint32_t producer, std::unique_ptr<SnapshotChunk>& chunk, Ring& producer_ring,
                    LoopSignals& signals);

    const std::string& dir() const { return dir_; }
    const std::string& dbfilename() const { return dbfilename_; }

private:
    using ChunkChan = Channel<SnapshotChunk*, 64>;
    bool write_header();
    bool write_frame(const SnapshotChunk& chunk);
    bool finish_file();
    void abort_file();
    void discard_chunks();
    void set_error(const char* text);

    std::unique_ptr<ChunkChan[]> chunk_in_;
    NotifyMask chunk_notify_;
    uint32_t nthreads_ = 0;
    uint32_t nshards_ = 0;
    uint32_t executor_count_ = 0;

    std::atomic<Phase> phase_{Phase::Idle};
    std::atomic<uint64_t> epoch_{0};
    std::atomic<int64_t> cut_ms_{0};
    std::atomic<uint32_t> ready_owners_{0};
    std::atomic<uint32_t> frozen_owners_{0};
    std::atomic<uint32_t> marked_owners_{0};
    std::atomic<uint32_t> cancelled_owners_{0};
    std::atomic<uint32_t> finished_owners_{0};
    std::atomic<uint32_t> writer_tid_{UINT32_MAX};
    std::atomic<bool> blocking_{false};
    std::atomic<uint32_t> save_current_shard_{0};
    std::atomic<int64_t> last_save_time_{0};
    std::atomic<bool> writer_failed_{false};
    std::atomic<Ring*> writer_ring_{nullptr};
    Server* server_ = nullptr;  // snapshot command lifetime; process-wide Server is stable

    std::string dir_;
    std::string dbfilename_;
    std::string final_path_;
    std::string temp_path_;
    std::string error_;
    std::mutex error_mu_;
    int fd_ = -1;                         // designated writer thread only
    uint64_t frame_count_ = 0;
    uint32_t ended_shards_ = 0;
    uint32_t writer_cursor_ = 0;
    std::vector<uint32_t> next_sequence_; // designated writer thread only
    std::vector<uint8_t> saw_begin_;
    std::vector<uint8_t> saw_end_;
};

struct SnapshotIoContext {
    ThreadCtx* thread = nullptr;
    Ring* ring = nullptr;
};
void snapshot_bind_io(ThreadCtx* thread, Ring* ring);
SnapshotIoContext snapshot_io_context();

}  // namespace tomo
