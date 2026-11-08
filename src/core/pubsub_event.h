// Owns transport records posted by IO and executor threads to IO consumers; included by thread.h and io_loop.h's
// pub/sub implementation through server/thread declarations; t_server.cc also includes it.
// Subscriber indexes and connection state stay private to IoLoop; executors and shards
// only post heap events and never reach that state. Events identify clients by process-unique ID and IO
// owner; only notification reply slots carry a borrowed Op*, used on coordinator IO.
// Mailbox locking transfers event ownership; immutable blobs use reference counts.
#pragma once

#include "climon_mask.h"
#include <atomic>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace tomo {

class Op;

enum class PubSubEventKind : uint8_t {
    ModifyRequest,
    ModifyResult,
    PublishRequest,
    NotificationEnqueue,
    NotificationRequest,
    NotificationContinue,
    DeliveryBatch,
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
    // These four kinds (MonitorFeed, TrackingInvalidate, TrackingFlush, TrackingDeliver)
    // are produced only while the CLIENT/MONITOR armed word is nonzero.
    MonitorFeed,         // one pre-formatted feed line, encoded once and shared by every owner
    TrackingInvalidate,  // keys whose value changed; each owner filters against its own table
    TrackingFlush,       // FLUSHALL/FLUSHDB: deliver the null invalidation to every tracker
    TrackingDeliver,     // redirect hop: owner of the redirect target emits the frame
    ClientUnblockRequest,
    ClientUnblockResult,
    ClientRoutingInstalled,
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

// One publish, encoded ONCE at the channel home and shared by every owning IO thread that has a
// subscriber for it.  Refcounted because the owners retire independently: the last one frees it.
//
// `frame` holds the RESP2 delivery exactly as it goes on the wire.  The RESP3 push frame is
// byte-identical except for the leading '*' -> '>' (both element counts are single digits), so one
// encoding serves both protocols.  `body_off` is the offset of the `$<len>\r\n<channel>...` tail,
// which `pmessage` reuses verbatim behind its own 4-element header.
// The home builds immutable frame bytes before mailbox publication. Each queued delivery
// owns one reference: increments are relaxed before transfer, final release uses acq_rel.
// Only the last releaser deletes the blob; building/allocation failure has no local retry.
struct PubSubBlob {
    std::atomic<uint32_t> refs{0};
    bool shard = false;
    uint32_t body_off = 0;
    std::string frame;
};

// One (blob, destination connection) pair queued for an owning IO thread.  Connections are named
// by process-unique id, never by a cross-thread Client*. `is_pattern` selects the
// `pmessage` shape, including a valid empty pattern.  Each item holds ONE reference on `blob`.
// The source outbox transfers this reference through a mailbox to destination IO;
// forwarding transfers it again without incrementing. Delivery or event cleanup must
// unref exactly once. This value type has no automatic unref destructor.
struct PubSubDelivery {
    PubSubBlob* blob = nullptr;
    uint64_t conn = 0;
    std::string pattern;
    bool is_pattern = false;
};

// A finished PUBLISH/SPUBLISH, batched back to the publisher's own IO thread.
struct PubSubResult {
    uint64_t conn_id = 0;
    uint64_t op_id = 0;
    uint64_t count = 0;
};

// Chain-owned channel/message values; reply is a borrowed committed EXEC child slot.
// Only coordinator IO writes that reply, before the chain completion callback releases
// the parent continuation. The chain must outlive every home request/continuation.
struct PubSubNotificationItem {
    std::string channel;
    std::string message;
    Op* reply = nullptr;  // committed EXEC child, completed only on coordinator IO
    bool shard = false;
};

// Shared lifetime for a serialized notification sequence. Only coordinator IO accesses
// index, items and replies; it moves each item's channel/message into the NotificationRequest
// before posting. The home reads only that event and coordinator_io. Mailbox mutex handoffs
// order these accesses; shared_ptr alone
// does not synchronize mutation. Exactly one link is active; invalid continuation/index
// aborts, and allocation exceptions are not recovered by this record.
struct PubSubNotificationChain {
    uint32_t coordinator_io = 0;
    uint32_t index = 0;
    std::vector<PubSubNotificationItem> items;
    void (*completed)(void*) = nullptr;
    void* completion = nullptr;
};

// Heap message owned by its producer until enqueued: IO posts via pubsub_post, EX via
// ThreadCtx::post_pubsub_event_nonblocking. A refused post leaves ownership with the producer;
// after enqueue, the consuming IO owns it.
// Mailbox mutex handoff orders mutable fields. Deliveries own blob references released
// by delivery or pubsub_delete_event; notification/blob shared_ptrs own their payloads.
// ACL permissions and notification reply pointers are borrowed under their protocols.
// Local/remote queues may allocate; wake-marker pressure is handled by the posting path,
// not by this aggregate. Consumers must not retain a raw event pointer after deletion.
struct PubSubEvent {
    PubSubEventKind kind = PubSubEventKind::DeliveryBatch;
    uint32_t origin_io = 0;
    uint32_t target_io = 0;
    uint64_t conn_id = 0;
    uint64_t op_id = 0;
    bool pattern = false;
    bool shard = false;
    bool subscribe = false;
    bool rebind = false;
    uint64_t count = 0;
    // Snapshot of the IO destinations selected by a MONITOR/tracking broadcast.  A stale owner
    // forwards only when the target's live owner was absent from this mask, which makes the
    // migration backstop lossless without duplicating a delivery already posted to the new owner.
    ClimonIoMask route_mask;
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
    // DeliveryBatch payload: every publish this home resolved for ONE destination IO in one pass,
    // plus every publish reply owed to that same IO.  Both stay in publish order.
    std::vector<PubSubDelivery> deliveries;
    std::vector<PubSubResult> results;
    std::shared_ptr<PubSubNotificationChain> notification;
    // Encode-once MONITOR payload shared by receiving owners; other event kinds leave it null.
    std::shared_ptr<const std::string> blob;
};

}  // namespace tomo
