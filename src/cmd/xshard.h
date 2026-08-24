// xshard.h -- arena-backed scatter/gather lowering for multi-key commands.
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>
#include "../store/flatstore.h"

namespace tomo {

class Client;
class LoopSignals;
class Op;
class Ring;
class Server;
class Shard;
class ThreadCtx;
struct ScatterState;
struct Task;
struct ScatterDispatch;

enum class XshardStringStoreResult : uint8_t { Stored, Oom, InsertFailed, Maxmemory };
XshardStringStoreResult xshard_store_string(Shard& shard, Slice key, uint64_t hash, Slice value);

// Multi-key pops choose a key after their first-hop probes, then ask that key's live owner to do
// the mutation.  Keeping these helpers in the type lanes preserves their cursor/encoding rules and
// the ObjectSizeTracker finish-before-erase contract instead of replaying a stale whole-object
// image on hop two.
enum class XshardPopResult : uint8_t { Popped, Missing, WrongType, Oom };
XshardPopResult xshard_pop_list(Shard& shard, Slice key, uint64_t hash, bool left,
                                uint64_t count, std::vector<std::string>& elements);
XshardPopResult xshard_pop_zset(Shard& shard, Slice key, uint64_t hash, bool maximum,
                                uint64_t count, std::vector<std::string>& members,
                                std::vector<double>& scores);

enum class ScatterPrepare : uint8_t { NotScatter, Ready, Error };
enum class ScatterTaskResult : uint8_t { Complete, Retry };
enum class ScatterFinish : uint8_t { Waiting, Final };

// The common arena size is deliberately a size class, not a maximum command size.  The owning IO
// thread recycles these blocks after ROB retirement; larger shapes use exact-size heap blocks.
// Keeping the freelist here (rather than in ScatterState) makes cross-thread frees impossible by
// construction.
class ScatterArenaPool {
public:
    ScatterArenaPool() = default;
    ~ScatterArenaPool();
    ScatterArenaPool(const ScatterArenaPool&) = delete;
    ScatterArenaPool& operator=(const ScatterArenaPool&) = delete;

private:
    friend ScatterPrepare xshard_prepare(Server&, Op&, ScatterArenaPool&, uint32_t,
                                          ScatterDispatch&);
    friend void xshard_destroy(ScatterState*, ScatterArenaPool&, uint32_t);
    friend void xshard_retire(Client&, Op&, ScatterArenaPool&, uint32_t, void*,
                              void (*)(void*, int32_t, const char*));
    static constexpr uint32_t kCached = 64;
    static constexpr size_t kCommonBytes = 8192;
    void* acquire(size_t bytes, bool& pooled);
    void release(void* ptr, bool pooled);
    void* cached_[kCached] = {};
    uint32_t count_ = 0;
};

struct ScatterDispatch {
    ScatterState* state = nullptr;
    uint32_t nshards = 0;
    bool barrier = false;
};

// Parses command-specific options and coalesces request key positions by shard.  Error means a
// complete RESP error is already in op; Ready owns `state` until destroy or final completion.
ScatterPrepare xshard_prepare(Server& server, Op& op, ScatterArenaPool& pool,
                              uint32_t owner_io, ScatterDispatch& dispatch);
int32_t xshard_dispatch_shard(const ScatterDispatch& dispatch, uint32_t index);
void xshard_destroy(ScatterState* state, ScatterArenaPool& pool, uint32_t owner_io);

// Called by the connection-owning IO thread immediately before the ROB slot is staged.  It builds
// final RESP bytes/segments, transfers every gathered borrow to the connection segment queue, and
// then returns the arena to this IO thread's pool.
void xshard_retire(Client& client, Op& op, ScatterArenaPool& pool, uint32_t owner_io,
                   void* release_ctx, void (*release_fn)(void*, int32_t, const char*));

// Same-owner commands are ordinary tasks (Task::scatter == nullptr).  The marker and gate cursor
// reuse otherwise-idle zero-copy descriptor fields, preserving sizeof(Op).
bool xshard_is_local(const Op& op);
FlatStore::SnapshotWriteResult xshard_local_snapshot_prepare(Op& op, Shard& shard);

// Snapshot write gate.  A scatter task may name several mutation keys; progress is remembered in
// the heap group so Pending resumes at exactly the same key on the next owner pass.
FlatStore::SnapshotWriteResult xshard_snapshot_prepare(const Task& task, Shard& shard);

// Executes one bounded owner pass.  KEYS may return Retry; all other tasks complete in one pass.
ScatterTaskResult xshard_execute(const Task& task, Shard& shard, Op& op);

// Counts a completed owner and, for the last owner, either serializes the final reply or publishes
// a fully-preflighted second hop.  Final means the caller must publish OpState::Done and notify IO.
ScatterFinish xshard_complete(Server& server, ThreadCtx& self, Ring& ring,
                              const Task& task, Op& op);

}  // namespace tomo
