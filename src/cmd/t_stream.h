// t_stream.h -- narrow cross-shard/blocking surface for the stream owner lane.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

#include "../base/slice.h"
#include "../store/typeval.h"

namespace tomo {

class KvObj;
class Op;
class Shard;

struct StreamXreadArgs {
    uint32_t first_key = 0;
    uint32_t key_count = 0;
    uint32_t first_id = 0;
    uint64_t count = 0;                 // zero = unlimited
    uint64_t block_ms = 0;
    bool block = false;
};

struct StreamXreadGroupArgs {
    uint32_t group_arg = 0;
    uint32_t consumer_arg = 0;
    uint32_t key_arg = 0;
    uint32_t id_arg = 0;
    uint64_t count = 0;                  // zero = unlimited
    uint64_t block_ms = 0;
    bool block = false;
    bool noack = false;
    bool new_entries = false;
};

struct StreamOwnedEntry {
    StreamID id{};
    bool deleted = false;
    std::vector<std::string> fields;
    std::vector<std::string> values;
};

enum class StreamReadResult : uint8_t { Empty, Ready, Missing, WrongType, Oom, Corrupt };

bool stream_parse_xread(Op& op, StreamXreadArgs& parsed);
bool stream_parse_xreadgroup(Op& op, StreamXreadGroupArgs& parsed);
bool stream_xread_has_block_option(const Op& op);
bool stream_parse_xread_id(Slice input, StreamID& id, bool& latest);
bool stream_object_last_id(const KvObj* object, StreamID& id);
bool stream_object_has_live_after(const KvObj* object, const StreamID& cursor);
bool stream_object_header(KvObj* object, StreamHeader& header);
bool stream_object_update_header(KvObj* object, const StreamHeader& header);
uint64_t stream_object_live_length(KvObj* object);
uint64_t stream_object_physical_length(KvObj* object);
bool stream_object_first_live(KvObj* object, StreamID& id);
bool stream_object_last_live(KvObj* object, StreamID& id);
bool stream_object_collect(KvObj* object, const StreamID& start, bool exclusive,
                           uint64_t count, bool include_deleted,
                           std::vector<StreamOwnedEntry>& entries);
bool stream_object_find(KvObj* object, const StreamID& id, StreamOwnedEntry& entry,
                        bool& found);
bool stream_force_external(Shard& shard, Op& op, KvObj*& object, bool notify);
bool stream_create_empty_external(Shard& shard, Op& op, bool notify, KvObj*& object);

enum class StreamGroupProbe : uint8_t {
    Empty, Ready, MissingGroup, WrongType, Corrupt, Oom,
};
StreamGroupProbe stream_group_probe(Shard& shard, Slice key, uint64_t hash, Slice group);
StreamGroupProbe stream_group_prepare_waiter(Shard& shard, Slice key, uint64_t hash,
                                             Slice group, Slice consumer);
bool stream_xreadgroup_execute(Shard& shard, Op& op);
void stream_xreadgroup_reply_nogroup(Op& op);

uint64_t stream_groups_snapshot_size(const void* groups);
bool stream_groups_snapshot_read(const void* groups, uint64_t offset, uint8_t* destination,
                                 size_t capacity, size_t& written);
bool stream_groups_snapshot_load(StreamVal& stream, Slice payload);

// Payload is a lane-owned binary gather format. It is decoded only after every shard completes;
// no value bytes are borrowed across owner boundaries.
StreamReadResult stream_xread_gather(Shard& shard, Slice key, uint64_t hash,
                                     const StreamID& cursor, bool latest, uint64_t count,
                                     std::vector<uint8_t>& payload,
                                     const StreamID* upper_bound = nullptr);
bool stream_reply_xread_payload(Op& op, Slice key, const std::vector<uint8_t>& payload);

}  // namespace tomo
