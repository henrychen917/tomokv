#include "aof.h"

#include <cerrno>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <new>
#include <sys/stat.h>
#include <sys/types.h>
#include <thread>
#include <unistd.h>

#include "../cmd/command.h"
#include "../core/config.h"
#include "../core/server.h"
#include "../core/shard.h"
#include "../core/thread.h"
#include "../exec/op.h"
#include "../net/resp.h"
#include "../net/uring.h"
#include "../store/flatstore.h"

namespace tomo {
namespace {

constexpr uint8_t kFileMagic[8] = {'T','O','M','O','A','O','F','\0'};
constexpr uint32_t kFileVersion = 1;
constexpr uint32_t kFileHeaderBytes = 80;
constexpr uint32_t kFrameHeaderBytes = 40;
constexpr uint32_t kFrameTag = 0x4d524641;       // "AFRM"
constexpr uint32_t kRecordHeaderBytes = 40;
constexpr uint32_t kRecordTag = 0x43524f41;      // "AORC"
constexpr uint32_t kWriterFramesPerPass = 16;

int64_t realtime_ms() {
    timespec ts{};
    ::clock_gettime(CLOCK_REALTIME, &ts);
    return static_cast<int64_t>(ts.tv_sec) * 1000 + ts.tv_nsec / 1000000;
}

bool plain_name(const char* value) {
    return value && *value && !std::strchr(value, '/');
}

bool write_counted(int fd, const uint8_t* bytes, size_t length, uint64_t& offset) {
    while (length) {
        const ssize_t n = ::write(fd, bytes, length);
        if (n < 0) {
            if (errno == EINTR) continue;
            return false;
        }
        if (n == 0) return false;
        bytes += n;
        length -= static_cast<size_t>(n);
        offset += static_cast<uint64_t>(n);
    }
    return true;
}

bool read_file(int fd, std::vector<uint8_t>& out, std::string& error) {
    struct stat st{};
    if (::fstat(fd, &st) != 0 || st.st_size < 0) {
        error = "could not stat AOF";
        return false;
    }
    try {
        out.resize(static_cast<size_t>(st.st_size));
    } catch (const std::bad_alloc&) {
        error = "out of memory reading AOF";
        return false;
    }
    size_t offset = 0;
    while (offset < out.size()) {
        const ssize_t n = ::pread(fd, out.data() + offset, out.size() - offset,
                                  static_cast<off_t>(offset));
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) {
            error = "short AOF read";
            return false;
        }
        offset += static_cast<size_t>(n);
    }
    return true;
}

const char* hook_error(SnapshotHookStatus status) {
    switch (status) {
        case SnapshotHookStatus::Unsupported: return "AOF contains an unsupported value type";
        case SnapshotHookStatus::Corrupt: return "corrupt AOF type payload";
        case SnapshotHookStatus::Oom: return "out of memory loading AOF";
        case SnapshotHookStatus::Ok: break;
    }
    return "AOF type hook failed";
}

bool parse_record_bounds(const std::vector<uint8_t>& section, size_t pos,
                         AofRecordKind& kind, uint8_t& type, uint8_t& encoding,
                         uint32_t& key_len, uint64_t& payload_len, int64_t& expire,
                         uint64_t& group, size_t& next, std::string& error) {
    if (section.size() - pos < kRecordHeaderBytes) {
        error = "truncated AOF record";
        return false;
    }
    const uint8_t* h = section.data() + pos;
    if (snapshot_get_u32(h) != kRecordTag || h[7] != 1 ||
        snapshot_get_u32(h + 12) != kRecordHeaderBytes) {
        error = "invalid AOF record header";
        return false;
    }
    kind = static_cast<AofRecordKind>(h[4]);
    type = h[5];
    encoding = h[6];
    key_len = snapshot_get_u32(h + 8);
    payload_len = snapshot_get_u64(h + 16);
    expire = static_cast<int64_t>(snapshot_get_u64(h + 24));
    group = snapshot_get_u64(h + 32);
    const uint64_t remaining = static_cast<uint64_t>(section.size() - pos - kRecordHeaderBytes);
    if (payload_len > UINT32_MAX || remaining < static_cast<uint64_t>(key_len) + payload_len) {
        error = "invalid AOF record lengths";
        return false;
    }
    next = pos + kRecordHeaderBytes + key_len + static_cast<size_t>(payload_len);
    return true;
}

}  // namespace

std::string aof_directory_path(const Config& config) {
    const char* dir = config.dir && *config.dir ? config.dir : ".";
    const char* appenddir = plain_name(config.appenddirname) ? config.appenddirname : "appendonlydir";
    return std::string(dir) + "/" + appenddir;
}

std::string aof_file_path(const Config& config) {
    const char* filename = plain_name(config.appendfilename) ? config.appendfilename : "appendonly.aof";
    return aof_directory_path(config) + "/" + filename + ".1.incr.tomo";
}

void AofProducer::init(AofManager* manager, int32_t sid, uint32_t next_sequence) {
    manager_ = manager;
    sid_ = sid;
    sequence_ = next_sequence;
}

bool AofProducer::enabled() const { return manager_ && manager_->recording(); }

std::unique_ptr<AofChunk> AofProducer::make_chunk(uint32_t flags) {
    try {
        auto chunk = std::make_unique<AofChunk>();
        chunk->sid = sid_;
        chunk->sequence = sequence_++;
        chunk->flags = flags;
        chunk->bytes.reserve(kAofChunkBytes);
        return chunk;
    } catch (const std::bad_alloc&) {
        if (manager_) manager_->fail("out of memory allocating AOF chunk");
        return nullptr;
    }
}

bool AofProducer::post_ready(AofOwnerContext& context) {
    if (!manager_ || !context.ring || !context.signals) return false;
    while (!ready_.empty()) {
        std::unique_ptr<AofChunk>& chunk = ready_.front();
        if (!manager_->post_chunk(context.producer, chunk, *context.ring, *context.signals))
            return false;
        ready_.erase(ready_.begin());
    }
    return true;
}

bool AofProducer::seal(uint32_t flags, AofOwnerContext* context) {
    if (!build_) return true;
    build_->flags |= flags;
    ready_.push_back(std::move(build_));
    if (!context) return true;
    while (!post_ready(*context)) {
        if (!manager_ || manager_->failed()) return false;
        context->ring->submit_and_reap();
        std::this_thread::yield();
    }
    return true;
}

bool AofProducer::emit(const uint8_t* bytes, uint64_t length, bool large,
                       AofOwnerContext* context) {
    while (length) {
        if (!build_) {
            build_ = make_chunk(large ? AofFrameLargeBegin : 0);
            if (!build_) return false;
        }
        const size_t room = kAofChunkBytes - build_->bytes.size();
        if (!room) {
            if (!seal(0, context)) return false;
            build_ = make_chunk(0);
            if (!build_) return false;
            continue;
        }
        const size_t take = static_cast<size_t>(std::min<uint64_t>(length, room));
        try {
            build_->bytes.insert(build_->bytes.end(), bytes, bytes + take);
        } catch (const std::bad_alloc&) {
            if (manager_) manager_->fail("out of memory staging AOF bytes");
            return false;
        }
        bytes += take;
        length -= take;
        if (large && build_->bytes.size() == kAofChunkBytes && length)
            if (!seal(0, context)) return false;
    }
    return true;
}

bool AofProducer::maybe_timestamp(int64_t now_ms, AofOwnerContext* context) {
    if (!manager_ || !manager_->timestamp_enabled()) return true;
    const int64_t second = now_ms / 1000;
    if (second == timestamp_second_) return true;
    timestamp_second_ = second;
    return record_bytes(AofRecordKind::Timestamp, 0, 0, Slice(), -1,
                        static_cast<uint64_t>(second), nullptr, 0, nullptr, nullptr, context);
}

bool AofProducer::record_bytes(AofRecordKind kind, uint8_t type, uint8_t encoding, Slice key,
                               int64_t expire_at_ms, uint64_t group, const uint8_t* payload,
                               uint64_t payload_len, const SnapshotTypeHooks* hooks,
                               SnapshotSaveCursor* cursor, AofOwnerContext* context) {
    if (!manager_ || manager_->failed()) return false;
    if (kind != AofRecordKind::Timestamp && !maybe_timestamp(realtime_ms(), context)) return false;
    if (payload_len > UINT32_MAX ||
        payload_len > UINT64_MAX - kRecordHeaderBytes - key.n) {
        manager_->fail("AOF record is too large");
        return false;
    }
    const uint64_t total = kRecordHeaderBytes + static_cast<uint64_t>(key.n) + payload_len;
    const bool large = total > kAofChunkBytes;
    if (large) {
        if (!seal(0, context)) return false;
    } else if (build_ && build_->bytes.size() + total > kAofChunkBytes) {
        if (!seal(0, context)) return false;
    }
    if (!build_) {
        build_ = make_chunk(large ? AofFrameLargeBegin : 0);
        if (!build_) return false;
    }

    uint8_t header[kRecordHeaderBytes] = {};
    snapshot_put_u32(header, kRecordTag);
    header[4] = static_cast<uint8_t>(kind);
    header[5] = type;
    header[6] = encoding;
    header[7] = 1;
    snapshot_put_u32(header + 8, key.n);
    snapshot_put_u32(header + 12, kRecordHeaderBytes);
    snapshot_put_u64(header + 16, payload_len);
    snapshot_put_u64(header + 24, static_cast<uint64_t>(expire_at_ms));
    snapshot_put_u64(header + 32, group);
    if (!emit(header, sizeof(header), large, context) ||
        !emit(reinterpret_cast<const uint8_t*>(key.p), key.n, large, context)) return false;

    if (hooks && cursor) {
        while (cursor->offset < cursor->total) {
            if (!build_) {
                build_ = make_chunk(large ? 0 : 0);
                if (!build_) return false;
            }
            size_t room = kAofChunkBytes - build_->bytes.size();
            if (!room) {
                if (!seal(0, context)) return false;
                build_ = make_chunk(0);
                if (!build_) return false;
                room = kAofChunkBytes;
            }
            const size_t capacity = static_cast<size_t>(std::min<uint64_t>(
                room, cursor->total - cursor->offset));
            const size_t old_size = build_->bytes.size();
            try {
                build_->bytes.resize(old_size + capacity);
            } catch (const std::bad_alloc&) {
                manager_->fail("out of memory staging AOF value");
                return false;
            }
            size_t written = 0;
            const SnapshotHookStatus status = hooks->read_save(
                *cursor, build_->bytes.data() + old_size, capacity, written);
            if (status != SnapshotHookStatus::Ok || written > capacity ||
                (written == 0 && cursor->offset < cursor->total)) {
                build_->bytes.resize(old_size);
                manager_->fail("AOF type serialization failed");
                return false;
            }
            build_->bytes.resize(old_size + written);
        }
    } else if (payload_len && !emit(payload, payload_len, large, context)) {
        return false;
    }

    if (large) {
        if (!build_) return false;
        build_->records = 1;
        return seal(AofFrameLargeEnd, context);
    }
    build_->records++;
    return true;
}

bool AofProducer::record_post_image_impl(FlatStore& store, uint64_t hash, Slice key,
                                         AofOwnerContext* context, uint64_t group) {
    if (!enabled()) return true;
    KvObj* object = store.find(hash, key);
    if (!object) {
        const AofRecordKind kind = group ? AofRecordKind::GroupDel : AofRecordKind::Del;
        return record_bytes(kind, 0, 0, key, -1, group, nullptr, 0,
                            nullptr, nullptr, context);
    }
    const SnapshotTypeHooks& hooks = snapshot_type_hooks(static_cast<Type>(object->type));
    SnapshotSaveCursor cursor;
    uint8_t encoding = 0;
    if (!hooks.begin_save || !hooks.read_save ||
        hooks.begin_save(*object, cursor, encoding) != SnapshotHookStatus::Ok) {
        manager_->fail("AOF type serialization failed");
        return false;
    }
    const AofRecordKind kind = group ? AofRecordKind::GroupPut : AofRecordKind::Put;
    return record_bytes(kind, object->type, encoding, object->key(), object->expire_at_ms(),
                        group, nullptr, cursor.total, &hooks, &cursor, context);
}

bool AofProducer::record_post_image(FlatStore& store, uint64_t hash, Slice key,
                                    AofOwnerContext& context, uint64_t group) {
    return record_post_image_impl(store, hash, key, &context, group);
}

bool AofProducer::record_post_image_buffered(FlatStore& store, uint64_t hash, Slice key,
                                             uint64_t group) {
    return record_post_image_impl(store, hash, key, nullptr, group);
}

bool AofProducer::record_delete(Slice key, uint64_t group) {
    if (!enabled()) return true;
    const AofRecordKind kind = group ? AofRecordKind::GroupDel : AofRecordKind::Del;
    return record_bytes(kind, 0, 0, key, -1, group, nullptr, 0, nullptr, nullptr, nullptr);
}

bool AofProducer::record_flush() {
    if (!enabled()) return true;
    return record_bytes(AofRecordKind::Flush, 0, 0, Slice(), -1, 0,
                        nullptr, 0, nullptr, nullptr, nullptr);
}

bool AofProducer::flush(AofOwnerContext& context) {
    if (!manager_) return true;
    if (build_ && !seal(0, nullptr)) return false;
    return post_ready(context);
}

AofManager::~AofManager() {
    if (fd_ >= 0) ::close(fd_);
    discard_chunks();
}

void AofManager::init(const Config& config, uint32_t nthreads, uint32_t nshards,
                      uint32_t writer_tid, const AofReplayPlan* replay) {
    configured_ = config.appendonly;
    if (!configured_) return;
    nthreads_ = nthreads;
    nshards_ = nshards;
    writer_tid_ = writer_tid;
    directory_path_ = aof_directory_path(config);
    file_path_ = aof_file_path(config);
    timestamp_enabled_.store(config.aof_timestamp_enabled, std::memory_order_relaxed);
    chunk_in_ = std::make_unique<ChunkChan[]>(nthreads_);
    next_sequence_.assign(nshards_, 0);
    if (replay && replay->next_sequence.size() == nshards_)
        next_sequence_ = replay->next_sequence;
    if (replay) {
        replayed_records_.store(replay->replayed_records, std::memory_order_relaxed);
        groups_skipped_.store(replay->groups_skipped, std::memory_order_relaxed);
    }
}

void AofManager::fail(const char* message) {
    last_error_ = message ? message : "AOF failure";
    failed_.store(true, std::memory_order_release);
    recording_.store(false, std::memory_order_release);
    std::fprintf(stderr, "AOF error: %s\n", last_error_.c_str());
}

bool AofManager::write_header() {
    uint8_t header[kFileHeaderBytes] = {};
    std::memcpy(header, kFileMagic, sizeof(kFileMagic));
    snapshot_put_u32(header + 8, kFileVersion);
    snapshot_put_u32(header + 12, kFileHeaderBytes);
    snapshot_put_u32(header + 16, nshards_);
    snapshot_put_u32(header + 20, static_cast<uint32_t>(g_hash_kind));
    snapshot_put_u64(header + 24, static_cast<uint64_t>(realtime_ms()));
    snapshot_put_u64(header + 32, g_hash_seed);
    snapshot_put_u64(header + 40, g_sip_k0);
    snapshot_put_u64(header + 48, g_sip_k1);
    snapshot_put_u64(header + 64, snapshot_checksum(header, 64));
    return write_counted(fd_, header, sizeof(header), file_offset_);
}

bool AofManager::bind_writer(ThreadCtx& writer, Ring& ring, std::string& error) {
    if (!configured_) return true;
    if (writer.id() != writer_tid_) {
        while (!writer_ready_.load(std::memory_order_acquire) &&
               !failed_.load(std::memory_order_acquire)) std::this_thread::yield();
        if (failed()) error = last_error_;
        return !failed();
    }
    if (::mkdir(directory_path_.c_str(), 0755) != 0 && errno != EEXIST) {
        error = "could not create appenddirname";
        fail(error.c_str());
        return false;
    }
    struct stat directory{};
    if (::stat(directory_path_.c_str(), &directory) != 0 || !S_ISDIR(directory.st_mode)) {
        error = "appenddirname is not a directory";
        fail(error.c_str());
        return false;
    }
    fd_ = ::open(file_path_.c_str(), O_CREAT | O_RDWR | O_APPEND | O_CLOEXEC, 0600);
    if (fd_ < 0) {
        error = "could not open AOF file";
        fail(error.c_str());
        return false;
    }
    struct stat st{};
    if (::fstat(fd_, &st) != 0 || st.st_size < 0) {
        error = "could not stat AOF file";
        fail(error.c_str());
        return false;
    }
    file_offset_ = static_cast<uint64_t>(st.st_size);
    if (file_offset_ == 0 && !write_header()) {
        error = "could not write AOF header";
        fail(error.c_str());
        return false;
    }
    last_good_offset_ = file_offset_;
    current_size_.store(file_offset_, std::memory_order_relaxed);
    writer_ring_.store(&ring, std::memory_order_release);
    recording_.store(true, std::memory_order_release);
    writer_ready_.store(true, std::memory_order_release);
    return true;
}

bool AofManager::post_chunk(uint32_t producer, std::unique_ptr<AofChunk>& chunk,
                            Ring& producer_ring, LoopSignals& signals) {
    if (!recording() || !chunk || producer >= nthreads_) return false;
    AofChunk* raw = chunk.get();
    if (!chunk_in_[producer].push(raw, signals)) return false;
    chunk.release();
    pending_chunks_.fetch_add(1, std::memory_order_release);
    if (chunk_notify_.set(producer)) {
        Ring* target = writer_ring_.load(std::memory_order_acquire);
        chunk_in_[producer].wake(producer_ring, signals, target);
    }
    return true;
}

bool AofManager::write_frame(const AofChunk& chunk) {
    if (chunk.sid < 0 || static_cast<uint32_t>(chunk.sid) >= nshards_) return false;
    const uint32_t sid = static_cast<uint32_t>(chunk.sid);
    if (chunk.sequence != next_sequence_[sid]++) return false;
    uint8_t header[kFrameHeaderBytes] = {};
    snapshot_put_u32(header, kFrameTag);
    snapshot_put_u32(header + 4, sid);
    snapshot_put_u32(header + 8, chunk.sequence);
    snapshot_put_u32(header + 12, chunk.flags);
    snapshot_put_u32(header + 16, static_cast<uint32_t>(chunk.bytes.size()));
    snapshot_put_u32(header + 20, kFrameHeaderBytes);
    snapshot_put_u64(header + 24, snapshot_checksum(chunk.bytes.data(), chunk.bytes.size()));
    snapshot_put_u64(header + 32, snapshot_checksum(header, 32));
    const uint64_t frame_begin = file_offset_;
    if (!write_counted(fd_, header, sizeof(header), file_offset_) ||
        !write_counted(fd_, chunk.bytes.data(), chunk.bytes.size(), file_offset_)) {
        (void)::ftruncate(fd_, static_cast<off_t>(last_good_offset_));
        file_offset_ = last_good_offset_;
        return false;
    }
    if (chunk.flags & AofFrameLargeBegin) large_record_offset_ = frame_begin;
    if (chunk.flags & AofFrameLargeEnd) last_good_offset_ = file_offset_;
    else if (locked_producer_ == UINT32_MAX) last_good_offset_ = file_offset_;
    records_written_.fetch_add(chunk.records, std::memory_order_relaxed);
    current_size_.store(file_offset_, std::memory_order_relaxed);
    return true;
}

bool AofManager::drain_producer(uint32_t producer, uint32_t& budget, uint32_t& consumed) {
    AofChunk* chunk = nullptr;
    while (budget && chunk_in_[producer].recv(chunk)) {
        const uint32_t flags = chunk->flags;
        bool valid = true;
        if (locked_producer_ == UINT32_MAX) {
            if (flags & AofFrameLargeEnd) valid = false;
            if (flags & AofFrameLargeBegin) locked_producer_ = producer;
        } else {
            if (locked_producer_ != producer || (flags & AofFrameLargeBegin)) valid = false;
        }
        if (valid) valid = write_frame(*chunk);
        if (valid && (flags & AofFrameLargeEnd)) locked_producer_ = UINT32_MAX;
        delete chunk;
        chunk_in_[producer].retire();
        pending_chunks_.fetch_sub(1, std::memory_order_release);
        budget--;
        consumed++;
        if (!valid) {
            fail("AOF frame ordering or write failed");
            return false;
        }
    }
    if (chunk_in_[producer].depth()) chunk_notify_.set(producer);
    return true;
}

uint32_t AofManager::writer_pass(ThreadCtx& writer, Ring&, bool drain_all) {
    if (!configured_ || writer.id() != writer_tid_ || fd_ < 0 || failed()) return 0;
    uint32_t budget = drain_all ? 256 : kWriterFramesPerPass;
    uint32_t consumed = 0;
    if (locked_producer_ != UINT32_MAX) {
        drain_producer(locked_producer_, budget, consumed);
        return consumed;
    }
    for (uint32_t word = 0; word < NotifyMask::kWords && budget; word++) {
        uint64_t bits = chunk_notify_.take(word);
        while (bits && budget && locked_producer_ == UINT32_MAX) {
            const uint32_t bit = static_cast<uint32_t>(__builtin_ctzll(bits));
            bits &= bits - 1;
            const uint32_t producer = word * 64 + bit;
            if (producer < nthreads_) drain_producer(producer, budget, consumed);
        }
        while (bits) {
            const uint32_t bit = static_cast<uint32_t>(__builtin_ctzll(bits));
            bits &= bits - 1;
            chunk_notify_.set(word * 64 + bit);
        }
    }
    if (drain_all && consumed == 0 && locked_producer_ == UINT32_MAX) {
        for (uint32_t visited = 0; visited < nthreads_ && budget; visited++) {
            const uint32_t producer = writer_cursor_++ % nthreads_;
            drain_producer(producer, budget, consumed);
            if (locked_producer_ != UINT32_MAX) break;
        }
    }
    return consumed;
}

bool AofManager::wait_until_drained(uint32_t timeout_ms) {
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
    while (pending_chunks() && std::chrono::steady_clock::now() < deadline) {
        if (Ring* ring = writer_ring_.load(std::memory_order_acquire)) {
            (void)ring;
        }
        std::this_thread::yield();
    }
    return pending_chunks() == 0;
}

void AofManager::writer_shutdown(ThreadCtx& writer, Ring& ring) {
    if (!configured_ || writer.id() != writer_tid_ || fd_ < 0) return;
    for (uint32_t pass = 0; pending_chunks() && pass < 100000; pass++) {
        const uint32_t n = writer_pass(writer, ring, true);
        if (!n) std::this_thread::yield();
    }
    if (locked_producer_ != UINT32_MAX) {
        (void)::ftruncate(fd_, static_cast<off_t>(large_record_offset_));
        file_offset_ = large_record_offset_;
    }
    (void)::fdatasync(fd_);
    (void)::close(fd_);
    fd_ = -1;
    recording_.store(false, std::memory_order_release);
    writer_ring_.store(nullptr, std::memory_order_release);
}

void AofManager::discard_chunks() {
    if (!chunk_in_) return;
    for (uint32_t producer = 0; producer < nthreads_; producer++) {
        AofChunk* chunk = nullptr;
        while (chunk_in_[producer].recv(chunk)) {
            delete chunk;
            chunk_in_[producer].retire();
        }
    }
}

std::unique_ptr<AofReplayPlan> aof_read_plan(const char* path, uint32_t expected_shards,
                                             bool truncate_tail, bool& exists,
                                             std::string& warning, std::string& error) {
    exists = false;
    warning.clear();
    error.clear();
    const int fd = ::open(path, truncate_tail ? O_RDWR | O_CLOEXEC : O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        if (errno == ENOENT) return nullptr;
        error = "could not open AOF";
        return nullptr;
    }
    exists = true;
    std::vector<uint8_t> file;
    if (!read_file(fd, file, error)) { ::close(fd); return nullptr; }
    if (file.size() < kFileHeaderBytes ||
        std::memcmp(file.data(), kFileMagic, sizeof(kFileMagic)) != 0 ||
        snapshot_get_u32(file.data() + 8) != kFileVersion ||
        snapshot_get_u32(file.data() + 12) != kFileHeaderBytes ||
        snapshot_get_u64(file.data() + 64) != snapshot_checksum(file.data(), 64)) {
        error = "invalid AOF header";
        ::close(fd);
        return nullptr;
    }
    auto plan = std::make_unique<AofReplayPlan>();
    plan->shard_count = snapshot_get_u32(file.data() + 16);
    if (plan->shard_count != expected_shards) {
        error = "AOF shard count does not match --shards";
        ::close(fd);
        return nullptr;
    }
    plan->hash_kind = snapshot_get_u32(file.data() + 20);
    if (plan->hash_kind > static_cast<uint32_t>(HashKind::SipHash12)) {
        error = "AOF uses an unknown hash kind";
        ::close(fd);
        return nullptr;
    }
    plan->hash_seed = snapshot_get_u64(file.data() + 32);
    plan->sip_k0 = snapshot_get_u64(file.data() + 40);
    plan->sip_k1 = snapshot_get_u64(file.data() + 48);
    plan->sections.resize(plan->shard_count);
    plan->next_sequence.assign(plan->shard_count, 0);

    size_t pos = kFileHeaderBytes;
    size_t valid = kFileHeaderBytes;
    bool active_large = false;
    uint32_t large_sid = UINT32_MAX;
    size_t large_file_pos = 0;
    size_t large_section_size = 0;
    uint32_t large_sequence = 0;
    bool torn = false;
    while (pos < file.size()) {
        if (file.size() - pos < kFrameHeaderBytes) { torn = true; break; }
        const uint8_t* h = file.data() + pos;
        if (snapshot_get_u32(h) != kFrameTag ||
            snapshot_get_u32(h + 20) != kFrameHeaderBytes ||
            snapshot_get_u64(h + 32) != snapshot_checksum(h, 32)) {
            error = "invalid AOF frame header";
            ::close(fd);
            return nullptr;
        }
        const uint32_t sid = snapshot_get_u32(h + 4);
        const uint32_t sequence = snapshot_get_u32(h + 8);
        const uint32_t flags = snapshot_get_u32(h + 12);
        const uint32_t length = snapshot_get_u32(h + 16);
        const uint64_t checksum = snapshot_get_u64(h + 24);
        const size_t frame_pos = pos;
        pos += kFrameHeaderBytes;
        if (sid >= plan->shard_count || sequence != plan->next_sequence[sid]++) {
            error = "invalid AOF shard frame sequence";
            ::close(fd);
            return nullptr;
        }
        if (file.size() - pos < length) {
            plan->next_sequence[sid]--;
            torn = true;
            pos = frame_pos;
            break;
        }
        if (checksum != snapshot_checksum(file.data() + pos, length)) {
            error = "invalid AOF frame checksum";
            ::close(fd);
            return nullptr;
        }
        if (!active_large) {
            if (flags & AofFrameLargeEnd) {
                error = "AOF large record ends without a begin";
                ::close(fd);
                return nullptr;
            }
            if (flags & AofFrameLargeBegin) {
                active_large = true;
                large_sid = sid;
                large_file_pos = frame_pos;
                large_section_size = plan->sections[sid].size();
                large_sequence = sequence;
            }
        } else if (sid != large_sid || (flags & AofFrameLargeBegin)) {
            error = "interleaved AOF large record";
            ::close(fd);
            return nullptr;
        }
        try {
            plan->sections[sid].insert(plan->sections[sid].end(), file.data() + pos,
                                       file.data() + pos + length);
        } catch (const std::bad_alloc&) {
            error = "out of memory assembling AOF shard streams";
            ::close(fd);
            return nullptr;
        }
        pos += length;
        if (active_large && (flags & AofFrameLargeEnd)) {
            active_large = false;
            large_sid = UINT32_MAX;
        }
        if (!active_large) valid = pos;
    }
    if (active_large) {
        plan->sections[large_sid].resize(large_section_size);
        plan->next_sequence[large_sid] = large_sequence;
        valid = large_file_pos;
        torn = true;
    }
    if (torn) {
        if (!truncate_tail) {
            error = "truncated AOF tail";
            ::close(fd);
            return nullptr;
        }
        if (::ftruncate(fd, static_cast<off_t>(valid)) != 0) {
            error = "could not truncate torn AOF tail";
            ::close(fd);
            return nullptr;
        }
        warning = "truncated AOF tail from " + std::to_string(file.size()) + " to " +
                  std::to_string(valid) + " bytes";
    }
    plan->valid_file_bytes = valid;
    ::close(fd);

    for (uint32_t sid = 0; sid < plan->shard_count; sid++) {
        const auto& section = plan->sections[sid];
        size_t record_pos = 0;
        while (record_pos < section.size()) {
            AofRecordKind kind;
            uint8_t type = 0, encoding = 0;
            uint32_t key_len = 0;
            uint64_t payload_len = 0, group = 0;
            int64_t expire = -1;
            size_t next = 0;
            if (!parse_record_bounds(section, record_pos, kind, type, encoding, key_len,
                                     payload_len, expire, group, next, error)) return nullptr;
            (void)type; (void)encoding; (void)key_len; (void)payload_len; (void)expire;
            if (kind < AofRecordKind::Put || kind > AofRecordKind::GroupCommit) {
                error = "unknown AOF record kind";
                return nullptr;
            }
            if ((kind == AofRecordKind::GroupPut || kind == AofRecordKind::GroupDel) && !group)
                { error = "AOF group fragment has no ticket"; return nullptr; }
            plan->replayed_records++;
            record_pos = next;
        }
    }
    return plan;
}

bool aof_load_shard(const AofReplayPlan& plan, Server& server, Shard& shard,
                    std::string& error) {
    const uint32_t sid = static_cast<uint32_t>(shard.id());
    if (sid >= plan.sections.size()) { error = "AOF shard section is missing"; return false; }
    const int64_t now = realtime_ms();
    shard.set_cached_now_ms(now);
    const std::vector<uint8_t>& section = plan.sections[sid];
    size_t pos = 0;
    while (pos < section.size()) {
        AofRecordKind kind;
        uint8_t type = 0, encoding = 0;
        uint32_t key_len = 0;
        uint64_t payload_len = 0, group = 0;
        int64_t expire = -1;
        size_t next = 0;
        if (!parse_record_bounds(section, pos, kind, type, encoding, key_len, payload_len,
                                 expire, group, next, error)) return false;
        const size_t data = pos + kRecordHeaderBytes;
        const Slice key(reinterpret_cast<const char*>(section.data() + data), key_len);
        const Slice payload(reinterpret_cast<const char*>(section.data() + data + key_len),
                            static_cast<uint32_t>(payload_len));
        pos = next;
        if (kind == AofRecordKind::Timestamp || kind == AofRecordKind::GroupCommit) continue;
        if (kind == AofRecordKind::Flush) {
            shard.store().clear();
            continue;
        }
        if (kind == AofRecordKind::GroupPut || kind == AofRecordKind::GroupDel) {
            // Step 2 graduates this path by filtering fragments against GCMT tickets.
            continue;
        }
        const uint64_t hash = FlatStore::hash_key(key);
        if (server.router().shard_of(hash) != shard.id()) {
            error = "AOF key is in the wrong shard stream";
            return false;
        }
        if (kind == AofRecordKind::Del || (expire >= 0 && expire <= now)) {
            shard.store().erase(hash, key);
            continue;
        }
        if (kind != AofRecordKind::Put || type > static_cast<uint8_t>(Type::Zset)) {
            error = "invalid AOF value record";
            return false;
        }
        KvObj* object = nullptr;
        const SnapshotHookStatus status = snapshot_type_hooks(static_cast<Type>(type)).load(
            key, encoding, expire, payload, shard.type_limits(), object);
        if (status != SnapshotHookStatus::Ok || !object) {
            error = hook_error(status);
            return false;
        }
        if (shard.store().insert(hash, object) != FlatStore::InsertResult::Inserted) {
            kvobj_free(object);
            error = "could not insert AOF value";
            return false;
        }
    }
    shard.publish_size();
    return true;
}

bool aof_load_owned(const AofReplayPlan& plan, Server& server, ThreadCtx& owner,
                    std::string& error) {
    for (Shard* shard : owner.shards())
        if (!aof_load_shard(plan, server, *shard, error)) return false;
    return true;
}

bool aof_record_local_op(Shard& shard, Op& op, AofOwnerContext& context) {
    if (!(op.spec->flags & (CmdFlags::Write | CmdFlags::SnapshotWrite))) return true;
    if (op.spec->first_key <= 0) return true;
    uint32_t first = static_cast<uint32_t>(op.spec->first_key);
    uint32_t last = op.spec->last_key < 0 ? op.argc() - 1
                                          : static_cast<uint32_t>(op.spec->last_key);
    uint32_t step = static_cast<uint32_t>(op.spec->key_step);
    if (op.spec->flags & CmdFlags::ScriptRoute) {
        uint32_t count = 0;
        if (!command_script_key_range(op, first, count) || count == 0) return true;
        last = first + count - 1;
        step = 1;
    }
    if (!step || first >= op.argc()) return true;
    last = std::min(last, op.argc() - 1);
    bool ok = true;
    for (uint32_t arg = first; arg <= last; arg += step) {
        const Slice key = op.arg(arg);
        const uint64_t hash = arg == first && !op.local_xshard() ? op.hash
                                                                 : FlatStore::hash_key(key);
        ok &= shard.store().aof().record_post_image(shard.store(), hash, key, context);
        if (last - arg < step) break;
    }
    return ok;
}

}  // namespace tomo
