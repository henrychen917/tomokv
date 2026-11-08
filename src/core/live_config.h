// Immutable live-configuration values and their three-slot publication mailbox.
// Included by server.h and worker loops; no fixed inclusion point. A serialized CONFIG
// writer publishes to one physical consumer per mailbox without reader retries,
// allocation after initialization, or reclamation of slots.
#pragma once
#include <atomic>
#include <cstdint>
#include "config.h"

namespace tomo {

// Value-only worker configuration, copied from a committed mailbox slot. version is an
// even commit number; the struct owns no pointers and supplies no synchronization itself.
struct LiveConfigSnapshot {
    uint64_t version;
    uint64_t maxmemory;
    MaxmemoryPolicy policy;
    uint32_t samples;
    uint32_t notify_events;
    uint32_t debug_fanout_defer_us;
    int64_t slowlog_log_slower_than;
    uint32_t latency_monitor_threshold;
    bool save_armed;
    bool tracking_armed;
    bool latency_tracking;
    uint64_t proto_max_bulk_len;
    uint64_t client_query_buffer_limit;
};
static_assert(sizeof(LiveConfigSnapshot) == 64,
              "Live config must fit its existing mailbox footprint");

// Value-only IO limits for the same commit as LiveConfigSnapshot. The consuming physical
// worker copies them before its next mailbox read; no external storage is borrowed.
struct ClientLimitsConfigSnapshot {
    uint64_t version = 0;
    uint32_t timeout = 0;
    ClientBufferLimit normal{};
    ClientBufferLimit pubsub{};
};

// One commit's execution and client-limit values, copied as a unit by the serialized
// writer and single consumer. Coherence comes from LiveConfigMailbox, not these fields.
struct LiveConfigValues {
    LiveConfigSnapshot live{};
    ClientLimitsConfigSnapshot clients{};
};

// Owns three fixed slots shared by one serialized CONFIG producer and one physical
// consumer (a worker or the transfer coordinator). init runs before either participant.
// Each participant owns one slot; acq_rel exchange transfers the middle slot and orders
// its contents. The producer never touches the consumer's slot, even if it stops.
// read returns a borrowed reference valid until that consumer's next read; copy before
// then. Publication can supersede unread updates without waiting or allocating.
// The global odd/even version selects the last committed value; no reader retries,
// grace-period announcements or slot reclamation are required.
class LiveConfigMailbox {
public:
    void init(const LiveConfigValues& initial) {
        for (auto& slot : slots_) slot = {initial, initial};
    }

    void publish(const LiveConfigValues& previous, const LiveConfigValues& next) {
        slots_[back_] = {previous, next};
        back_ = middle_.exchange(back_ | kDirty, std::memory_order_acq_rel) & kIndex;
    }

    const LiveConfigValues& read(const std::atomic<uint64_t>& version) {
        if (middle_.load(std::memory_order_acquire) & kDirty)
            front_ = middle_.exchange(front_, std::memory_order_acq_rel) & kIndex;
        // CONFIG stages every mailbox before publishing the even version. During that staging
        // interval choose the preceding committed value, not the partly published new version.
        // Load AFTER acquiring the slot: its publication also orders CONFIG's odd version store,
        // so this load cannot precede the commit of slot.previous. Keep both values even if this
        // consumer acquires an uncommitted slot and the writer then stops before committing it.
        const uint64_t observed = version.load(std::memory_order_acquire);
        const auto& slot = slots_[front_];
        return observed == slot.next.live.version - 1 ? slot.previous : slot.next;
    }
    // The consumer release-publishes an applied version; TRACKING ON acknowledges it with
    // an acquire load. The acknowledgement occupies the consumer's cache line.
    // TRACKING ON acknowledgement. Fits the consumer line's existing padding.
    void applied(uint64_t version) { applied_.store(version, std::memory_order_release); }
    uint64_t applied() const { return applied_.load(std::memory_order_acquire); }

private:
    static constexpr uint32_t kDirty = 4;
    static constexpr uint32_t kIndex = 3;
    static_assert(std::atomic<uint32_t>::is_always_lock_free);
    // Both values belong to the slot's current holder. Keeping the preceding commit lets
    // a consumer use committed data even if the writer stops after staging the next value.
    struct alignas(64) Publication {
        LiveConfigValues previous;
        LiveConfigValues next;
    };
    Publication slots_[3]{};
    alignas(64) uint32_t front_ = 0;  // consumer only
    std::atomic<uint64_t> applied_{0};
    alignas(64) uint32_t back_ = 1;  // serialized producer only
    alignas(64) std::atomic<uint32_t> middle_{2};
};
static_assert(sizeof(LiveConfigMailbox) == 960, "Keep the existing mailbox allocation/layout");

}  // namespace tomo
