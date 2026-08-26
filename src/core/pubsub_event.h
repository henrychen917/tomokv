// pubsub_event.h -- heap-owned messages carried between IO threads.
//
// This is transport data only.  Subscriber indexes and connection state stay in IoLoop, so this
// header does not give executors (or shards) a path to either.  Events name a connection by its
// process-unique id and owning IO; no cross-thread Client pointer is retained.
#pragma once

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace tomo {

enum class PubSubEventKind : uint8_t {
    ModifyRequest,
    ModifyResult,
    PublishRequest,
    NotificationEnqueue,
    NotificationRequest,
    NotificationContinue,
    PublishResult,
    Delivery,
    DeliveryReply,
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
    AclPermissionsChanged,
    AclUserDeleted,
    ClientListRequest,
    ClientListResult,
    ClientKillRequest,
    ClientKillResult,
};

enum ClientFilterMask : uint32_t {
    ClientFilterId = 1u << 0,
    ClientFilterAddr = 1u << 1,
    ClientFilterLaddr = 1u << 2,
    ClientFilterType = 1u << 3,
    ClientFilterUser = 1u << 4,
    ClientFilterMaxAge = 1u << 5,
    ClientFilterIdList = 1u << 6,
};

enum class ClientTypeFilter : int8_t {
    Any = -1,
    Normal = 0,
    Master = 1,
    Replica = 2,
    Pubsub = 3,
};

struct PubSubEventItem {
    uint32_t index = 0;
    bool changed = false;
    uint64_t count = 0;
    std::string value;
};

struct PubSubNotificationItem {
    std::string channel;
    std::string message;
};

struct PubSubNotificationChain {
    uint32_t coordinator_io = 0;
    uint32_t index = 0;
    std::vector<PubSubNotificationItem> items;
};

struct PubSubEvent {
    PubSubEventKind kind = PubSubEventKind::Delivery;
    uint32_t origin_io = 0;
    uint32_t target_io = 0;
    uint64_t conn_id = 0;
    uint64_t op_id = 0;
    bool pattern = false;
    bool shard = false;
    bool subscribe = false;
    uint64_t count = 0;
    uint32_t acl_user_index = 0;
    const void* acl_permissions = nullptr;  // immutable AclPerm; intentionally transport-opaque
    uint32_t client_filter_mask = 0;
    ClientTypeFilter client_type = ClientTypeFilter::Any;
    uint64_t client_id = 0;
    uint64_t client_max_age = 0;
    uint64_t caller_id = 0;
    bool client_skipme = false;
    bool client_old_form = false;
    std::string client_addr;
    std::string client_laddr;
    std::string client_user;
    std::string channel;
    std::string message;
    std::string pattern_text;
    std::vector<PubSubEventItem> items;
    std::shared_ptr<PubSubNotificationChain> notification;
};

}  // namespace tomo
