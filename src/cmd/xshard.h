// xshard.h -- heap-side scatter/gather lowering for multi-key commands.
#pragma once

#include <cstdint>
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

enum class XshardStringStoreResult : uint8_t { Stored, Oom, InsertFailed, Maxmemory };
XshardStringStoreResult xshard_store_string(Shard& shard, Slice key, uint64_t hash, Slice value);

enum class ScatterPrepare : uint8_t { NotScatter, Ready, Error };
enum class ScatterTaskResult : uint8_t { Complete, Retry };
enum class ScatterFinish : uint8_t { Waiting, Final };

struct ScatterDispatch {
    ScatterState* state = nullptr;
    std::vector<int32_t> shards;
    bool barrier = false;
};

// Parses command-specific options and coalesces request key positions by shard.  Error means a
// complete RESP error is already in op; Ready owns `state` until destroy or final completion.
ScatterPrepare xshard_prepare(Server& server, Op& op, ScatterDispatch& dispatch);
void xshard_destroy(ScatterState* state);

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
