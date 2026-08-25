// pubsub_event.h -- heap-owned messages carried between IO threads.
//
// This is transport data only.  Subscriber indexes and connection state stay in IoLoop, so this
// header does not give executors (or shards) a path to either.  Events name a connection by its
// process-unique id and owning IO; no cross-thread Client pointer is retained.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace tomo {

enum class PubSubEventKind : uint8_t {
    ModifyRequest,
    ModifyResult,
    PublishRequest,
    PublishResult,
    Delivery,
    ChannelsRequest,
    ChannelsResult,
    NumsubRequest,
    NumsubResult,
    NumpatRequest,
    NumpatResult,
    ResetRequest,
    ResetResult,
    CleanupRequest,
    CleanupResult,
};

struct PubSubEventItem {
    uint32_t index = 0;
    bool changed = false;
    uint64_t count = 0;
    std::string value;
};

struct PubSubEvent {
    PubSubEventKind kind = PubSubEventKind::Delivery;
    uint32_t origin_io = 0;
    uint32_t target_io = 0;
    uint64_t conn_id = 0;
    uint64_t op_id = 0;
    bool pattern = false;
    bool subscribe = false;
    uint64_t count = 0;
    std::string channel;
    std::string message;
    std::string pattern_text;
    std::vector<PubSubEventItem> items;
};

}  // namespace tomo
