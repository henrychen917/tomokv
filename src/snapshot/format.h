// format.h — versioned snapshot records and the per-type persistence hook contract.
//
// The physical file is a stream of checksummed frames.  Frames from different shards may be
// interleaved, but (sid, sequence) identifies one ordered logical shard section.  Executors only
// produce SnapshotChunk objects; the designated IO owner is the sole file writer.
#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>
#include <vector>
#include <cstring>
#include "../base/slice.h"

namespace tomo {

struct KvObj;
struct TypeLimits;
enum class Type : uint8_t;

inline constexpr uint32_t kSnapshotFormatVersion = 1;
inline constexpr uint32_t kSnapshotChunkBytes = 64 * 1024;

enum SnapshotFrameFlags : uint32_t {
    SnapshotFrameBegin = 1u << 0,
    SnapshotFrameEnd   = 1u << 1,
};

struct SnapshotChunk {
    int32_t sid = -1;
    uint32_t sequence = 0;
    uint32_t flags = 0;
    std::vector<uint8_t> bytes;
};

enum class SnapshotHookStatus : uint8_t {
    Ok,
    Unsupported,
    Corrupt,
    Oom,
};

// Fixed-size, lane-owned cursor.  A hook must not allocate a full encoded value merely to return
// it: begin_save announces the exact payload size and read_save emits at most `capacity` bytes.
// `offset` is maintained by the lane.  `lane[]` is opaque scratch for a collection iterator.
struct SnapshotSaveCursor {
    const KvObj* object = nullptr;
    uint64_t offset = 0;
    uint64_t total = 0;
    uintptr_t lane[4] = {};
};

using SnapshotBeginSaveHook = SnapshotHookStatus (*)(const KvObj&, SnapshotSaveCursor&,
                                                       uint8_t& encoding);
using SnapshotReadSaveHook = SnapshotHookStatus (*)(SnapshotSaveCursor&, uint8_t* destination,
                                                      size_t capacity, size_t& written);
using SnapshotLoadHook = SnapshotHookStatus (*)(Slice key, uint8_t encoding, int64_t expire_at_ms,
                                                 Slice payload, const TypeLimits& limits,
                                                 KvObj*& result);

struct SnapshotTypeHooks {
    SnapshotBeginSaveHook begin_save;
    SnapshotReadSaveHook read_save;
    SnapshotLoadHook load;
};

// Each type lane exports exactly one hook table.  String is complete.  The collection foundations
// deliberately return Unsupported until their concrete expanded representations land; a snapshot
// containing such a value fails instead of silently producing an unloadable file.
SnapshotTypeHooks string_snapshot_hooks();
SnapshotTypeHooks hash_snapshot_hooks();
SnapshotTypeHooks list_snapshot_hooks();
SnapshotTypeHooks set_snapshot_hooks();
SnapshotTypeHooks zset_snapshot_hooks();
const SnapshotTypeHooks& snapshot_type_hooks(Type type);

inline void snapshot_put_u32(uint8_t* p, uint32_t v) {
    p[0] = static_cast<uint8_t>(v);
    p[1] = static_cast<uint8_t>(v >> 8);
    p[2] = static_cast<uint8_t>(v >> 16);
    p[3] = static_cast<uint8_t>(v >> 24);
}
inline void snapshot_put_u64(uint8_t* p, uint64_t v) {
    for (uint32_t i = 0; i < 8; i++) p[i] = static_cast<uint8_t>(v >> (i * 8));
}
inline uint32_t snapshot_get_u32(const uint8_t* p) {
    return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}
inline uint64_t snapshot_get_u64(const uint8_t* p) {
    uint64_t v = 0;
    for (uint32_t i = 0; i < 8; i++) v |= static_cast<uint64_t>(p[i]) << (i * 8);
    return v;
}

inline uint64_t snapshot_checksum(const uint8_t* p, size_t n) {
    uint64_t h = 1469598103934665603ULL;
    for (size_t i = 0; i < n; i++) { h ^= p[i]; h *= 1099511628211ULL; }
    return h;
}


// Streams one element's bytes into a bounded destination with resume support.  A hook keeps the
// next element index in lane[0] and the byte position inside that element in lane[1]; per element
// it resets pos (and resume for the first resumed element) and calls put() for each byte range.
// put() returns false once the destination is full -- the walk must stop and record lane state.
struct SnapshotElementEmitter {
    uint8_t* dst;
    size_t cap;
    size_t out = 0;
    uint64_t pos = 0;
    uint64_t resume = 0;
    bool full = false;
    bool put(const void* p, size_t n) {
        if (full) return false;
        const uint64_t start = pos, end = pos + n;
        const uint64_t from = start < resume ? resume : start;
        if (from >= end) { pos = end; return true; }
        const size_t want = static_cast<size_t>(end - from);
        const size_t can = cap - out;
        const size_t take = want < can ? want : can;
        std::memcpy(dst + out, static_cast<const uint8_t*>(p) + (from - start), take);
        out += take;
        if (take < want) { full = true; pos = from + take; return false; }
        pos = end;
        return true;
    }
    bool put_u32(uint32_t v) { uint8_t b[4]; snapshot_put_u32(b, v); return put(b, 4); }
    bool put_u64(uint64_t v) { uint8_t b[8]; snapshot_put_u64(b, v); return put(b, 8); }
};

}  // namespace tomo
