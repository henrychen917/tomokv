#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "../base/slice.h"

namespace tomo {

class Shard;

struct ZsetEntry {
    std::string member;
    double score = 0;
};

enum class ZsetOwnerResult : uint8_t {
    Ok,
    Missing,
    WrongType,
    Oom,
    Maxmemory,
    InsertFailed,
};

// Owner-thread-only bridge used by GEO. Entries are copied out so no pointer can escape the
// shard, and replacement is built completely before the live key is relinked.
ZsetOwnerResult zset_owner_read(Shard& shard, Slice key, uint64_t hash, bool notify,
                                std::vector<ZsetEntry>& entries, int64_t& expire_at_ms);
ZsetOwnerResult zset_owner_replace(Shard& shard, Slice key, uint64_t hash, bool notify,
                                   const std::vector<ZsetEntry>& entries, int64_t expire_at_ms);

}  // namespace tomo
