#pragma once
#include "../base/slice.h"
#include <atomic>

namespace tomo {
class Shard;
class Op;
class Client;
// Lua's staging shard has no WATCH registrations. Capture command effects there
// and carry the bit with each installed key to its real owner.
class WatchEffectScope {
    friend void watch_record_modified(Shard&, Slice);
    Shard* shard_;
    bool* modified_;
    WatchEffectScope* previous_;
public:
    WatchEffectScope(Shard&, bool&);
    ~WatchEffectScope();
};
// Owner-local mutation reporting. Claims order a unit before it executes;
// only successful command effects mark those claims as mutating.
class WatchMutationScope {
    friend void watch_record_modified(Shard&, Slice);
    Shard* shard_ = nullptr;
    WatchMutationScope* previous_ = nullptr;
    const void* token_ = nullptr;
    std::atomic<uint64_t>* epoch_ = nullptr;
    std::atomic<bool>* aborted_ = nullptr;
    std::atomic<uint32_t>* refs_ = nullptr;
    Client* writer_ = nullptr;
public:
    explicit WatchMutationScope(Shard& shard, const void* token = nullptr,
        std::atomic<uint64_t>* epoch = nullptr, std::atomic<bool>* aborted = nullptr,
        std::atomic<uint32_t>* refs = nullptr, Client* writer = nullptr);
    ~WatchMutationScope();
};
void watch_record_modified(Shard& shard, Slice key);
void watch_execute_handler(Shard& shard, Op& op);
struct Task;
enum class ScatterTaskResult : uint8_t;
ScatterTaskResult watch_execute_scatter(const Task&, Shard&, Op&, uint32_t);
} // namespace tomo
