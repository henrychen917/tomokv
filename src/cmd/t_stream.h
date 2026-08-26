// t_stream.h -- narrow cross-shard/blocking surface for the stream owner lane.
#pragma once

#include <cstdint>
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

enum class StreamReadResult : uint8_t { Empty, Ready, Missing, WrongType, Oom, Corrupt };

bool stream_parse_xread(Op& op, StreamXreadArgs& parsed);
bool stream_xread_has_block_option(const Op& op);
bool stream_parse_xread_id(Slice input, StreamID& id, bool& latest);
bool stream_object_last_id(const KvObj* object, StreamID& id);
bool stream_object_has_live_after(const KvObj* object, const StreamID& cursor);

// Payload is a lane-owned binary gather format. It is decoded only after every shard completes;
// no value bytes are borrowed across owner boundaries.
StreamReadResult stream_xread_gather(Shard& shard, Slice key, uint64_t hash,
                                     const StreamID& cursor, bool latest, uint64_t count,
                                     std::vector<uint8_t>& payload,
                                     const StreamID* upper_bound = nullptr);
bool stream_reply_xread_payload(Op& op, Slice key, const std::vector<uint8_t>& payload);

}  // namespace tomo
