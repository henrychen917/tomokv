// Cold notification batch internals shared with EXEC compatibility publication.
#pragma once
#include "notify.h"
#include <mutex>
#include <vector>

namespace tomo {

struct NotifyRecordImpl {
    uint32_t order = 0;
    uint32_t sequence = 0;
    // Widened from uint8_t for NOTIFY_TRACKING (bit 20). The record is heap batch state, not Op
    // storage; no footprint lock covers it.
    uint32_t routes = 0;
    NotifyEventId event = NotifyEventId::Set;
    uint8_t db = 0;
    bool physical = false;  // lazy deletion survives speculative abort/retry
    Slice key;
};

struct NotifyExpiryCompletion {
    std::vector<std::shared_ptr<std::atomic<bool>>> waiters;
    ~NotifyExpiryCompletion() {
        for (const auto& waiter : waiters) waiter->store(true, std::memory_order_release);
    }
};

struct NotifyBatch {
    uint64_t tracking_stamp = 0;
    std::mutex mutex;
    NotifyRecordImpl inline_records[8];
    uint32_t inline_size = 0;
    uint32_t total = 0;
    uint32_t next_sequence = 0;
    uint32_t physical = 0;
    std::vector<NotifyRecordImpl> spill;
    std::deque<std::string> owned_keys;
    std::shared_ptr<NotifyExpiryCompletion> expiry_completion;
    // Only scripts with MONITOR armed populate this cold, existing carrier.
    std::vector<MonitorScriptLine> monitor_lines;
};

bool notify_make_publication(uint8_t db, uint32_t routes, uint8_t route, NotifyEventId event,
                             Slice key, std::string& channel, std::string& message);
std::shared_ptr<PubSubNotificationChain> notify_reserve_chain(
    Server& server, std::unique_ptr<PubSubNotificationChain> chain,
    std::shared_ptr<NotifyExpiryCompletion> expiry_completion = {});

}  // namespace tomo
