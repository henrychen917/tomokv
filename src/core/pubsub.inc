// Owns IO-side pub/sub indexes, subscription continuations, fanout, and cleanup.
// Included in IoLoop's private section by core/io_loop.h, hence compiled in its including
// server/command translation units in both database namespaces. Channel indexes belong
// to their home IO; client catalogs belong to the connection IO and migrate with it.
// Publish ROB slots before remote requests and queue deliveries before publish replies.
// Mailbox handoff transfers events; blob references survive until delivery or shutdown.
// Throwing container allocations have no general local recovery contract in these helpers.

enum class PubSubPendingKind : uint8_t { Modify, Publish, Channels, Numsub, Numpat, Reset };
enum class PubSubStartResult : uint8_t { Async, Sync };

// Home-IO outbox for one destination. Owns a blob reference per delivery until flush
// moves it into an event or consumes it locally; results are value records. The home
// fills it during publication and flushes it at the pass boundary. No atomics are needed
// until pubsub_post transfers the event. Allocation failure is not handled by this struct.
struct PubSubOutbox {
    std::vector<PubSubDelivery> deliveries;
    std::vector<PubSubResult> results;
};

// Home-index identity for a remote subscriber: an IO number plus process-unique ID,
// never a borrowed Client pointer. The channel home owns mutations; migration rebinds
// against the live directory, and consumers recheck ownership before delivery.
struct PubSubRef {
    uint32_t io = 0;
    uint64_t conn = 0;
    bool operator==(const PubSubRef& other) const { return io == other.io && conn == other.conn; }
};

// Home-owned pattern text and subscriber identity, replicated across channel homes.
// No connection pointer crosses IO threads; the home removes or rebinds the value record.
struct PubSubPatternRef {
    std::string pattern;
    PubSubRef ref;
};

// Connection-IO subscription catalog. Owns the sets and cleanup counters, borrows client,
// and migrates with the connection at the ownership commit. Pending replies/cleanup
// keep that client alive; teardown waits for every home acknowledgement before erasing
// this record. Container allocation failures are not translated here.
struct PubSubLocalConn {
    Client* client = nullptr;
    std::unordered_set<std::string> channels;
    std::unordered_set<std::string> patterns;
    std::unordered_set<std::string> shard_channels;
    uint32_t pending = 0;
    uint32_t cleanup_remaining = 0;
    bool cleanup_started = false;
    bool cleanup_done = false;
};

// Connection-IO command continuation. Owns copied arguments, home results, and deferred
// push bytes; borrows a live ROB slot or committed EXEC child/state. Home replies arrive
// through the mailbox before completion release-stores Done. The pending count/barrier
// keeps the connection alive. No allocation rollback guarantee is established here.
struct PubSubPending {
    PubSubPendingKind kind = PubSubPendingKind::Modify;
    uint64_t op_id = 0;
    uint32_t remaining = 0;
    bool pattern = false;
    bool shard = false;
    bool subscribe = false;
    std::vector<std::string> items;
    std::vector<int8_t> changes;
    std::vector<uint64_t> counts;
    std::vector<std::string> channels;
    uint64_t count = 0;
    std::string deferred;
    Op* exec_child = nullptr;
    void* exec_state = nullptr;
};

static std::string pubsub_string(Slice value) { return std::string(value.p, value.n); }

PubSubEvent* pubsub_new_event(PubSubEventKind kind) {
    PubSubEvent* event = new PubSubEvent;
    event->kind = kind;
    srv_->pubsub_event_created();
    return event;
}

void pubsub_delete_event(PubSubEvent* event) {
    // A batch that never reached its destination (shutdown) still owns one blob reference per
    // undelivered item.  Releasing here is what keeps the blob gauge honest on every path.
    for (PubSubDelivery& item : event->deliveries) pubsub_blob_unref(item.blob);
    delete event;
    srv_->pubsub_event_retired();
}

// ---- encode-once delivery blobs --------------------------------------------------------------
PubSubBlob* pubsub_blob_new(const std::string& channel, const std::string& message, bool shard) {
    PubSubBlob* blob = new PubSubBlob;
    blob->refs.store(1, std::memory_order_relaxed);  // the builder's own reference
    blob->shard = shard;
    SmallBuf<256> frame;
    reply_array_header(frame, 3);
    if (shard)
        reply_bulk(frame, Slice("smessage", 8));
    else
        reply_bulk(frame, Slice("message", 7));
    blob->body_off = static_cast<uint32_t>(frame.size());
    reply_bulk(frame, Slice(channel.data(), channel.size()));
    reply_bulk(frame, Slice(message.data(), message.size()));
    blob->frame.assign(frame.data(), frame.size());
    srv_->pubsub_blob_created();
    return blob;
}

void pubsub_blob_unref(PubSubBlob* blob) {
    if (blob->refs.fetch_sub(1, std::memory_order_acq_rel) != 1) return;
    delete blob;
    srv_->pubsub_blob_retired();
}

// Transfer event ownership from the calling IO to its local queue or the target's
// mutex-protected inbox. Requires a valid target IO and a heap event counted as created.
// Only the first event of a remote burst posts a wake marker; a full client channel
// spins until that marker lands. Allocation failure is not handled locally. Consumers
// own deletion and any delivery-blob references after a successful enqueue.
void pubsub_post(uint32_t target_io, PubSubEvent* event) {
    if (target_io == self_->id()) {
        pubsub_local_events_.push_back(event);
        pubsub_pass_pending_ = true;
        return;
    }
    ThreadCtx& target = srv_->thread(target_io);
    if (!target.post_pubsub_event(event)) return;

    // One nullptr marker wakes one whole inbox burst. This uses the established IO-to-IO
    // client channel, including its notify-mask/park protocol. The producer channel is an IO
    // channel, so ordinary executor completion traffic cannot fill this SPSC lane.
    while (!target.post_client(self_->id(), nullptr, ring_, self_->sig())) __builtin_ia32_pause();
}

uint32_t pubsub_home_for(Slice channel) const {
    const auto& ios = srv_->placement().ifid_threads();
    const uint64_t hash = FlatStore::hash_key(channel);
    return ios[hash % ios.size()];
}

uint32_t pubsub_home_for(const std::string& channel) const {
    return pubsub_home_for(Slice(channel.data(), channel.size()));
}

static bool pubsub_has_ref(const std::vector<PubSubRef>& refs, const PubSubRef& wanted) {
    return std::find(refs.begin(), refs.end(), wanted) != refs.end();
}

bool pubsub_home_add_channel(const std::string& channel, const PubSubRef& ref, bool shard) {
    auto& index = shard ? pubsub_shard_channels_ : pubsub_channels_;
    auto [it, inserted] = index.try_emplace(channel);
    std::vector<PubSubRef>& refs = it->second;
    if (pubsub_has_ref(refs, ref)) return false;
    if (inserted || refs.empty()) srv_->pubsub_active_channel_added(shard);
    refs.push_back(ref);
    srv_->pubsub_home_entry_added();
    return true;
}

bool pubsub_home_remove_channel(const std::string& channel, const PubSubRef& ref, bool shard) {
    auto& index = shard ? pubsub_shard_channels_ : pubsub_channels_;
    auto it = index.find(channel);
    if (it == index.end()) return false;
    std::vector<PubSubRef>& refs = it->second;
    auto found = std::find(refs.begin(), refs.end(), ref);
    if (found == refs.end()) return false;
    *found = refs.back();
    refs.pop_back();
    srv_->pubsub_home_entry_removed();
    if (refs.empty()) {
        index.erase(it);
        srv_->pubsub_active_channel_removed(shard);
    }
    return true;
}

bool pubsub_home_add_pattern(const std::string& pattern, const PubSubRef& ref) {
    for (const PubSubPatternRef& entry : pubsub_patterns_)
        if (entry.ref == ref && entry.pattern == pattern) return false;
    pubsub_patterns_.push_back(PubSubPatternRef{pattern, ref});
    srv_->pubsub_home_entry_added();
    return true;
}

bool pubsub_home_remove_pattern(const std::string& pattern, const PubSubRef& ref) {
    for (size_t i = 0; i < pubsub_patterns_.size(); i++) {
        if (!(pubsub_patterns_[i].ref == ref) || pubsub_patterns_[i].pattern != pattern) continue;
        pubsub_patterns_[i] = std::move(pubsub_patterns_.back());
        pubsub_patterns_.pop_back();
        srv_->pubsub_home_entry_removed();
        return true;
    }
    return false;
}

// A ModifyRequest with `rebind` set updates the existing registration in place.  It never
// creates a subscription: if an unsubscribe raced an old migration event, absence wins.  The
// live directory read also makes repeated migrations converge even when requests from two
// former owners reach this home in the opposite order.
void pubsub_home_rebind_channel(const std::string& channel, uint64_t conn, bool shard) {
    uint32_t live_io = 0;
    if (!command_client_directory_find(conn, live_io)) return;
    auto& index = shard ? pubsub_shard_channels_ : pubsub_channels_;
    auto found = index.find(channel);
    if (found == index.end()) return;
    std::vector<PubSubRef>& refs = found->second;
    bool kept = false;
    size_t out = 0;
    for (const PubSubRef& ref : refs) {
        if (ref.conn != conn) {
            refs[out++] = ref;
            continue;
        }
        if (!kept) {
            refs[out++] = PubSubRef{live_io, conn};
            kept = true;
        } else {
            srv_->pubsub_home_entry_removed();
        }
    }
    refs.resize(out);
}

void pubsub_home_rebind_pattern(const std::string& pattern, uint64_t conn) {
    uint32_t live_io = 0;
    if (!command_client_directory_find(conn, live_io)) return;
    bool kept = false;
    size_t out = 0;
    for (size_t i = 0; i < pubsub_patterns_.size(); i++) {
        PubSubPatternRef& entry = pubsub_patterns_[i];
        if (entry.ref.conn != conn || entry.pattern != pattern) {
            if (out != i) pubsub_patterns_[out] = std::move(entry);
            out++;
            continue;
        }
        if (!kept) {
            entry.ref.io = live_io;
            if (out != i) pubsub_patterns_[out] = std::move(entry);
            out++;
            kept = true;
        } else {
            srv_->pubsub_home_entry_removed();
        }
    }
    pubsub_patterns_.resize(out);
}

void pubsub_home_ensure_channel(const std::string& channel, uint64_t conn, bool shard) {
    uint32_t live_io = 0;
    if (!command_client_directory_find(conn, live_io)) return;
    const PubSubRef ref{live_io, conn};
    auto& index = shard ? pubsub_shard_channels_ : pubsub_channels_;
    auto found = index.find(channel);
    if (found != index.end()) {
        for (PubSubRef& current : found->second) {
            if (current.conn != conn) continue;
            current.io = live_io;
            return;
        }
    }
    (void)pubsub_home_add_channel(channel, ref, shard);
}

void pubsub_home_ensure_pattern(const std::string& pattern, uint64_t conn) {
    uint32_t live_io = 0;
    if (!command_client_directory_find(conn, live_io)) return;
    for (PubSubPatternRef& entry : pubsub_patterns_) {
        if (entry.ref.conn != conn || entry.pattern != pattern) continue;
        entry.ref.io = live_io;
        return;
    }
    (void)pubsub_home_add_pattern(pattern, PubSubRef{live_io, conn});
}

void pubsub_clear_home_indexes() {
    for (const auto& entry : pubsub_channels_) {
        for (size_t i = 0; i < entry.second.size(); i++) srv_->pubsub_home_entry_removed();
        srv_->pubsub_active_channel_removed(false);
    }
    for (const auto& entry : pubsub_shard_channels_) {
        for (size_t i = 0; i < entry.second.size(); i++) srv_->pubsub_home_entry_removed();
        srv_->pubsub_active_channel_removed(true);
    }
    for (size_t i = 0; i < pubsub_patterns_.size(); i++) srv_->pubsub_home_entry_removed();
    pubsub_channels_.clear();
    pubsub_shard_channels_.clear();
    pubsub_patterns_.clear();
}

void pubsub_begin_rehome_epoch(uint64_t epoch) {
    if (!epoch || pubsub_rehome_epoch_ == epoch) return;
    pubsub_clear_home_indexes();
    pubsub_rehome_epoch_ = epoch;
}

void pubsub_home_cleanup_channels(std::unordered_map<std::string, std::vector<PubSubRef>>& index,
                                  const PubSubRef& ref, bool shard) {
    for (auto it = index.begin(); it != index.end();) {
        std::vector<PubSubRef>& refs = it->second;
        size_t out = 0;
        for (size_t i = 0; i < refs.size(); i++) {
            if (refs[i] == ref)
                srv_->pubsub_home_entry_removed();
            else
                refs[out++] = refs[i];
        }
        refs.resize(out);
        if (refs.empty()) {
            it = index.erase(it);
            srv_->pubsub_active_channel_removed(shard);
        } else {
            ++it;
        }
    }
}

void pubsub_home_cleanup(const PubSubRef& ref) {
    pubsub_home_cleanup_channels(pubsub_channels_, ref, false);
    pubsub_home_cleanup_channels(pubsub_shard_channels_, ref, true);
    size_t out = 0;
    for (size_t i = 0; i < pubsub_patterns_.size(); i++) {
        if (pubsub_patterns_[i].ref == ref)
            srv_->pubsub_home_entry_removed();
        else {
            if (out != i) pubsub_patterns_[out] = std::move(pubsub_patterns_[i]);
            out++;
        }
    }
    pubsub_patterns_.resize(out);
}

// Appends one already-encoded frame to a subscriber.  RESP3 subscribers get the same bytes
// with the leading array byte swapped for the push byte, appended as two pieces so the payload
// is never copied a second time.
void pubsub_emit(Client* client, const char* p, size_t n, bool resp3) {
    static constexpr char kPush = '>';
    auto pending_it =
        pubsub_pending_.empty() ? pubsub_pending_.end() : pubsub_pending_.find(client->id());
    if (pending_it != pubsub_pending_.end()) {
        // A subscription control is mid-flight on this connection: park the push behind it so
        // the acknowledgement it is waiting for still lands in the Redis-mandated order.
        std::string& deferred = pending_it->second.deferred;
        if (resp3) {
            deferred.push_back(kPush);
            deferred.append(p + 1, n - 1);
        } else
            deferred.append(p, n);
        return;
    }
    // Append a complete frame at a frame boundary. A borrowed Op reply has a separate
    // header and body, so appending to its reply buffer could split that frame.
    // Client::append_oob chooses a channel that preserves framing and live direct-reply
    // regions. The send engine defers behind the observed dispatch frontier so a delivery
    // cannot overtake an earlier reply, including its own SSUBSCRIBE acknowledgement.
    // A parked blocking head is the latency-bounded exception.
    const bool deferred =
        resp3 ? wb_.defer_oob(*client, &kPush, 1, p + 1, n - 1) : wb_.defer_oob(*client, p, n);
    if (__builtin_expect(deferred, false)) {
        srv_->note_oob_frame_deferred();
    } else {
        const bool segmented =
            resp3 ? client->append_oob(&kPush, 1, p + 1, n - 1) : client->append_oob(p, n);
        if (__builtin_expect(segmented, false)) srv_->note_oob_frame_segmented();
    }
    enqueue_serve(client);
    mark_active(client);
}

void /* TOMO_TOOL_BIND pubsub_deliver_one */ pubsub_deliver_one(const PubSubDelivery& item) {
    auto local_it = pubsub_local_.find(item.conn);
    if (local_it == pubsub_local_.end()) return;
    Client* client = local_it->second.client;
    if (!client || client->closing() || client->dead()) return;
    const bool resp3 = client->resp3();
    const PubSubBlob& blob = *item.blob;
    if (!item.is_pattern) {
        pubsub_emit(client, blob.frame.data(), blob.frame.size(), resp3);
        return;
    }
    // `pmessage` reuses the blob's channel+payload tail verbatim behind its own header.
    SmallBuf<128> head;
    if (resp3)
        reply_push_header(head, 4);
    else
        reply_array_header(head, 4);
    reply_bulk(head, Slice("pmessage", 8));
    reply_bulk(head, Slice(item.pattern.data(), item.pattern.size()));
    head.append(blob.frame.data() + blob.body_off, blob.frame.size() - blob.body_off);
    pubsub_emit(client, head.data(), head.size(), false);
}

void pubsub_deliver_batch(std::vector<PubSubDelivery>& items) {
    for (PubSubDelivery& item : items) {
        Client* client = nullptr;
        auto local = pubsub_local_.find(item.conn);
        if (local != pubsub_local_.end()) client = local->second.client;
        uint32_t live_io = self_->id();
        const bool live = client ? ((live_io = client->ifid_thread()), true)
                                 : command_client_directory_find(item.conn, live_io);
        if (live && live_io != self_->id()) {
            // Transfer the item's existing blob reference to the forwarded outbox. No ref/unref
            // pair is needed, and the next final owner repeats this same live check.
            pubsub_outbox_for(live_io).deliveries.push_back(std::move(item));
            item.blob = nullptr;
            srv_->pubsub_forwarded_stale_added();
            continue;
        }
        if (live) pubsub_deliver_one(item);
        if (item.blob) pubsub_blob_unref(item.blob);
    }
    srv_->pubsub_deliveries_added(items.size());
    items.clear();
}

PubSubOutbox& pubsub_outbox_for(uint32_t io) {
    if (pubsub_outbox_.empty()) pubsub_outbox_.resize(kMaxThreads);  // first pub/sub use only
    PubSubOutbox& box = pubsub_outbox_[io];
    if (box.deliveries.empty() && box.results.empty()) pubsub_outbox_dirty_.push_back(io);
    pubsub_pass_pending_ = true;
    return box;
}

void pubsub_queue_delivery(const PubSubRef& ref, PubSubBlob* blob, const std::string* pattern) {
    blob->refs.fetch_add(1, std::memory_order_relaxed);
    PubSubOutbox& box = pubsub_outbox_for(ref.io);
    if (pattern)
        box.deliveries.push_back(PubSubDelivery{blob, ref.conn, *pattern, true});
    else
        box.deliveries.push_back(PubSubDelivery{blob, ref.conn, std::string()});
}

void pubsub_queue_result(uint32_t io, uint64_t conn_id, uint64_t op_id, uint64_t count) {
    pubsub_outbox_for(io).results.push_back(PubSubResult{conn_id, op_id, count});
}

uint64_t /* TOMO_TOOL_BIND pubsub_home_publish */ pubsub_home_publish(
    PubSubEvent& request, bool reply_to_publisher = true) {
    auto& index = request.shard ? pubsub_shard_channels_ : pubsub_channels_;
    auto exact = index.find(request.channel);
    const bool has_exact = exact != index.end();
    // Shard pub/sub is an exact-only namespace. Redis returns before its pattern walk too.
    const bool walk_patterns = !request.shard && !pubsub_patterns_.empty();
    if (!has_exact && !walk_patterns) {
        if (reply_to_publisher)
            pubsub_queue_result(request.origin_io, request.conn_id, request.op_id, 0);
        return 0;
    }

    uint64_t receivers = 0;
    PubSubBlob* blob = pubsub_blob_new(request.channel, request.message, request.shard);
    if (has_exact) {
        for (const PubSubRef& ref : exact->second) {
            pubsub_queue_delivery(ref, blob, nullptr);
            receivers++;
        }
    }
    if (walk_patterns) {
        const Slice channel(request.channel.data(), request.channel.size());
        for (const PubSubPatternRef& entry : pubsub_patterns_) {
            if (!command_glob_match(Slice(entry.pattern.data(), entry.pattern.size()), channel))
                continue;
            pubsub_queue_delivery(entry.ref, blob, &entry.pattern);
            receivers++;
        }
    }
    pubsub_blob_unref(blob);  // drop the builder reference; zero receivers frees it right here
    if (reply_to_publisher)
        pubsub_queue_result(request.origin_io, request.conn_id, request.op_id, receivers);
    return receivers;
}

// Flush this home's resolved fanout once per destination IO and pass. Each receiving
// owner appends the burst before serving its clients, allowing output coalescing.
uint32_t pubsub_flush_outboxes() {
    uint32_t work = 0;
    std::vector<uint32_t> dirty;
    dirty.swap(pubsub_outbox_dirty_);

    // Queue deliveries before any publish reply leaves this home. A publisher that waits
    // for its reply before publishing again cannot have a later message overtake the first
    // at a shared subscriber, even across channel homes. Posting into the ordered inbox is
    // sufficient; processing need not have finished. Pipelined publishing across different
    // homes has no cross-channel ordering guarantee; each home orders its own channel.
    for (uint32_t io : dirty) {
        PubSubOutbox& box = pubsub_outbox_[io];
        if (box.deliveries.empty()) continue;
        work++;
        if (io == self_->id()) {
            pubsub_deliver_batch(box.deliveries);
            continue;
        }
        PubSubEvent* event = pubsub_new_event(PubSubEventKind::DeliveryBatch);
        event->origin_io = self_->id();
        event->target_io = io;
        event->deliveries.swap(box.deliveries);
        srv_->pubsub_delivery_batch_posted();
        pubsub_post(io, event);
    }

    // PASS B -- publish replies, strictly after every delivery above is queued.
    for (uint32_t io : dirty) {
        PubSubOutbox& box = pubsub_outbox_[io];
        if (box.results.empty()) continue;
        work++;
        if (io == self_->id()) {
            for (const PubSubResult& result : box.results) pubsub_finish_publish(result);
            box.results.clear();
            continue;
        }
        PubSubEvent* event = pubsub_new_event(PubSubEventKind::DeliveryBatch);
        event->origin_io = self_->id();
        event->target_io = io;
        event->results.swap(box.results);
        pubsub_post(io, event);
    }
    return work;
}

void pubsub_handle_delivery_batch(PubSubEvent& event) {
    pubsub_deliver_batch(event.deliveries);
    for (const PubSubResult& result : event.results) pubsub_finish_publish(result);
}

void pubsub_notification_send(const std::shared_ptr<PubSubNotificationChain>& chain) {
    if (!chain || chain->index >= chain->items.size()) std::abort();
    PubSubNotificationItem& item = chain->items[chain->index];
    PubSubEvent* request = pubsub_new_event(PubSubEventKind::NotificationRequest);
    request->origin_io = chain->coordinator_io;
    request->channel = std::move(item.channel);
    request->message = std::move(item.message);
    request->shard = item.shard;
    request->notification = chain;
    pubsub_post(pubsub_home_for(request->channel), request);
}

void pubsub_notification_enqueue(std::shared_ptr<PubSubNotificationChain> chain) {
    if (!chain || chain->items.empty()) return;
    chain->coordinator_io = self_->id();
    const bool start = pubsub_notification_chains_.empty();
    pubsub_notification_chains_.push_back(std::move(chain));
    if (start) pubsub_notification_send(pubsub_notification_chains_.front());
}

void pubsub_notification_continue(PubSubEvent& event) {
    const std::shared_ptr<PubSubNotificationChain> chain = std::move(event.notification);
    if (!chain || pubsub_notification_chains_.empty() ||
        pubsub_notification_chains_.front() != chain)
        std::abort();
    if (Op* reply = chain->items[chain->index].reply) reply_int(reply->sink(), event.count);
    if (++chain->index < chain->items.size()) {
        pubsub_notification_send(chain);
        return;
    }
    pubsub_notification_chains_.pop_front();
    if (!pubsub_notification_chains_.empty())
        pubsub_notification_send(pubsub_notification_chains_.front());
    if (chain->completed) chain->completed(chain->completion);
}

// Handle a borrowed mailbox request on its channel/pattern home IO. Only that home
// mutates its indexes; connection identities cross threads without Client pointers.
// Transfer newly built result events through pubsub_post; notification continuations
// follow flushed deliveries so the coordinator cannot reorder links. Unknown kinds do
// nothing. Container/event allocation exceptions propagate; pubsub_post may spin for
// the burst wake marker when its client channel is full.
void pubsub_handle_home_request(PubSubEvent& event) {
    const PubSubRef ref{event.origin_io, event.conn_id};
    switch (event.kind) {
        case PubSubEventKind::ModifyRequest: {
            if (event.rebind) {
                if (event.op_id) pubsub_begin_rehome_epoch(event.op_id);
                for (const PubSubEventItem& item : event.items) {
                    if (event.op_id && event.subscribe) {
                        if (event.pattern)
                            pubsub_home_ensure_pattern(item.value, event.conn_id);
                        else
                            pubsub_home_ensure_channel(item.value, event.conn_id, event.shard);
                    } else if (event.pattern) {
                        pubsub_home_rebind_pattern(item.value, event.conn_id);
                    } else {
                        pubsub_home_rebind_channel(item.value, event.conn_id, event.shard);
                    }
                }
                break;
            }
            PubSubEvent* result = pubsub_new_event(PubSubEventKind::ModifyResult);
            result->conn_id = event.conn_id;
            result->op_id = event.op_id;
            result->pattern = event.pattern;
            result->shard = event.shard;
            result->subscribe = event.subscribe;
            result->items = event.items;
            for (PubSubEventItem& item : result->items) {
                item.changed =
                    event.pattern
                        ? (event.subscribe ? pubsub_home_add_pattern(item.value, ref)
                                           : pubsub_home_remove_pattern(item.value, ref))
                        : (event.subscribe
                               ? pubsub_home_add_channel(item.value, ref, event.shard)
                               : pubsub_home_remove_channel(item.value, ref, event.shard));
            }
            pubsub_post(event.origin_io, result);
            break;
        }
        case PubSubEventKind::PublishRequest:
            pubsub_home_publish(event);
            break;
        case PubSubEventKind::NotificationRequest:
            event.count = pubsub_home_publish(event, false);
            // Keyspace notifications are a serialized chain across homes: this home's
            // deliveries must reach their owners BEFORE the coordinator is allowed to send the
            // next link, or two homes could race the same subscriber out of order. Flushing
            // here costs nothing extra -- the chain is one event deep by construction.
            pubsub_flush_outboxes();
            {
                PubSubEvent* continuation = pubsub_new_event(PubSubEventKind::NotificationContinue);
                continuation->count = event.count;
                continuation->notification = std::move(event.notification);
                pubsub_post(continuation->notification->coordinator_io, continuation);
            }
            break;
        case PubSubEventKind::ChannelsRequest: {
            PubSubEvent* result = pubsub_new_event(PubSubEventKind::ChannelsResult);
            result->conn_id = event.conn_id;
            result->op_id = event.op_id;
            const bool filtered = event.pattern;
            const auto& index = event.shard ? pubsub_shard_channels_ : pubsub_channels_;
            for (const auto& item : index) {
                if (filtered &&
                    !command_glob_match(Slice(event.pattern_text.data(), event.pattern_text.size()),
                                        Slice(item.first.data(), item.first.size())))
                    continue;
                result->items.push_back(PubSubEventItem{0, false, 0, item.first});
            }
            pubsub_post(event.origin_io, result);
            break;
        }
        case PubSubEventKind::NumsubRequest: {
            PubSubEvent* result = pubsub_new_event(PubSubEventKind::NumsubResult);
            result->conn_id = event.conn_id;
            result->op_id = event.op_id;
            result->items = event.items;
            const auto& index = event.shard ? pubsub_shard_channels_ : pubsub_channels_;
            for (PubSubEventItem& item : result->items) {
                auto found = index.find(item.value);
                item.count = found == index.end() ? 0 : found->second.size();
            }
            pubsub_post(event.origin_io, result);
            break;
        }
        case PubSubEventKind::NumpatRequest: {
            PubSubEvent* result = pubsub_new_event(PubSubEventKind::NumpatResult);
            result->conn_id = event.conn_id;
            result->op_id = event.op_id;
            // Count distinct patterns with at least one subscriber, not subscriptions: two clients
            // on the same pattern contribute one. Patterns are replicated to every home, so this
            // home's list covers the full pattern set.
            std::unordered_set<std::string> distinct;
            distinct.reserve(pubsub_patterns_.size());
            for (const PubSubPatternRef& entry : pubsub_patterns_) distinct.insert(entry.pattern);
            result->count = distinct.size();
            pubsub_post(event.origin_io, result);
            break;
        }
        case PubSubEventKind::ResetRequest: {
            pubsub_home_cleanup(ref);
            PubSubEvent* result = pubsub_new_event(PubSubEventKind::ResetResult);
            result->conn_id = event.conn_id;
            result->op_id = event.op_id;
            pubsub_post(event.origin_io, result);
            break;
        }
        case PubSubEventKind::CleanupRequest: {
            pubsub_home_cleanup(ref);
            PubSubEvent* result = pubsub_new_event(PubSubEventKind::CleanupResult);
            result->conn_id = event.conn_id;
            pubsub_post(event.origin_io, result);
            break;
        }
        default:
            std::abort();
    }
}

void pubsub_account_local_change(PubSubLocalConn& local, bool pattern, bool shard, bool subscribe,
                                 const std::string& value) {
    auto& values = shard ? local.shard_channels : (pattern ? local.patterns : local.channels);
    if (subscribe) {
        if (values.insert(value).second) srv_->pubsub_subscription_added(pattern, shard);
    } else {
        if (values.erase(value)) srv_->pubsub_subscription_removed(pattern, shard);
    }
    if (local.client)
        command_client_set_subscriptions(local.client, static_cast<uint32_t>(local.channels.size()),
                                         static_cast<uint32_t>(local.patterns.size()),
                                         static_cast<uint32_t>(local.shard_channels.size()));
}

static uint64_t pubsub_subscription_count(const PubSubLocalConn& local) {
    return local.channels.size() + local.patterns.size();
}

static uint64_t pubsub_shard_subscription_count(const PubSubLocalConn& local) {
    return local.shard_channels.size();
}

static uint64_t pubsub_total_subscription_count(const PubSubLocalConn& local) {
    return pubsub_subscription_count(local) + pubsub_shard_subscription_count(local);
}

void pubsub_append_ack(Op::Sink& sink, bool pattern, bool shard, bool subscribe,
                       const std::string* value, uint64_t count, bool resp3) {
    const char* label = nullptr;
    uint32_t label_len = 0;
    if (shard) {
        label = subscribe ? "ssubscribe" : "sunsubscribe";
        label_len = subscribe ? 10 : 12;
    } else if (pattern) {
        label = subscribe ? "psubscribe" : "punsubscribe";
        label_len = subscribe ? 10 : 12;
    } else {
        label = subscribe ? "subscribe" : "unsubscribe";
        label_len = subscribe ? 9 : 11;
    }
    if (resp3)
        reply_push_header(sink, 3);
    else
        reply_array_header(sink, 3);
    reply_bulk(sink, Slice(label, label_len));
    if (value)
        reply_bulk(sink, Slice(value->data(), value->size()));
    else
        reply_null(sink, resp3);
    reply_int(sink, static_cast<long long>(count));
}

void pubsub_clear_local_subscriptions(PubSubLocalConn& local) {
    for (size_t i = 0; i < local.channels.size(); i++) srv_->pubsub_subscription_removed(false);
    for (size_t i = 0; i < local.patterns.size(); i++) srv_->pubsub_subscription_removed(true);
    for (size_t i = 0; i < local.shard_channels.size(); i++)
        srv_->pubsub_subscription_removed(false, true);
    local.channels.clear();
    local.patterns.clear();
    local.shard_channels.clear();
    if (local.client) command_client_set_subscriptions(local.client, 0, 0, 0);
    if (local.client) local.client->set_subscriber_mode(false);
}

// Finish a fully collected command on its connection IO owner. The caller establishes
// remaining == 0 and keeps the client/ROB or EXEC child alive. Assemble acknowledgements
// and deferred pushes in protocol order, release-store Done, then remove pending state.
// Absent pending/local entries return harmlessly; zero local pending count aborts.
// Allocation exceptions are not recovered here; serving/completion continues through
// the IO FIFO or the borrowed EXEC coordinator after this method returns.
void pubsub_finish_pending(uint64_t conn_id) {
    auto pending_it = pubsub_pending_.find(conn_id);
    auto local_it = pubsub_local_.find(conn_id);
    if (pending_it == pubsub_pending_.end() || local_it == pubsub_local_.end()) return;
    PubSubPending& pending = pending_it->second;
    PubSubLocalConn& local = local_it->second;
    Client* client = local.client;
    Op& op = pending.exec_child ? *pending.exec_child : client->rob().at(pending.op_id);
    auto sink = op.sink();

    // Subscription confirmations are pushes, including their RESP2 carriage.
    // CLIENT REPLY has already consumed SKIP; it cannot discard these frames.
    if (pending.kind == PubSubPendingKind::Modify) op.clear_reply_skip();

    // Publications are independent frames. Suppression may discard only the command reply.
    if (op.reply_skip() && !pending.deferred.empty()) {
        wb_.defer_oob(*client, pending.deferred.data(), pending.deferred.size());
        pending.deferred.clear();
    }
    switch (pending.kind) {
        case PubSubPendingKind::Modify:
            if (!pending.subscribe && !pending.deferred.empty())
                sink.append(pending.deferred.data(), pending.deferred.size());
            for (const std::string& item : pending.items) {
                pubsub_account_local_change(local, pending.pattern, pending.shard,
                                            pending.subscribe, item);
                pubsub_append_ack(sink, pending.pattern, pending.shard, pending.subscribe, &item,
                                  pending.shard ? pubsub_shard_subscription_count(local)
                                                : pubsub_subscription_count(local),
                                  op.resp3());
            }
            if (pending.subscribe && !pending.deferred.empty())
                sink.append(pending.deferred.data(), pending.deferred.size());
            client->set_subscriber_mode(pubsub_total_subscription_count(local) != 0);
            break;
        case PubSubPendingKind::Publish:
            reply_int(sink, static_cast<long long>(pending.count));
            break;
        case PubSubPendingKind::Channels:
            std::sort(pending.channels.begin(), pending.channels.end());
            pending.channels.erase(std::unique(pending.channels.begin(), pending.channels.end()),
                                   pending.channels.end());
            reply_array_header(sink, pending.channels.size());
            for (const std::string& channel : pending.channels)
                reply_bulk(sink, Slice(channel.data(), channel.size()));
            break;
        case PubSubPendingKind::Numsub:
            reply_array_header(sink, pending.items.size() * 2);
            for (size_t i = 0; i < pending.items.size(); i++) {
                reply_bulk(sink, Slice(pending.items[i].data(), pending.items[i].size()));
                reply_int(sink, static_cast<long long>(pending.counts[i]));
            }
            break;
        case PubSubPendingKind::Numpat:
            reply_int(sink, static_cast<long long>(pending.count));
            break;
        case PubSubPendingKind::Reset:
            if (!pending.deferred.empty())
                sink.append(pending.deferred.data(), pending.deferred.size());
            pubsub_clear_local_subscriptions(local);
            command_set_local_context(client, self_);
            op.spec->handler(srv_->shard(0), op);
            command_set_local_context(nullptr, nullptr);
            break;
    }

    if (pending.kind != PubSubPendingKind::Modify && pending.kind != PubSubPendingKind::Reset &&
        !pending.deferred.empty())
        sink.append(pending.deferred.data(), pending.deferred.size());
    void* exec_state = pending.exec_state;
    op.state.store(OpState::Done, std::memory_order_release);
    if (!exec_state) {
        enqueue_serve(client);
        mark_active(client);
    }
    if (!local.pending) std::abort();
    local.pending--;
    srv_->pubsub_pending_finished();
    pubsub_pending_.erase(pending_it);
    if (!client->closing() && !local.pending && local.channels.empty() && local.patterns.empty() &&
        local.shard_channels.empty() && !local.cleanup_started)
        pubsub_local_.erase(local_it);
    if (exec_state) multi_io_child_completed(exec_state);
}

void pubsub_finish_publish(const PubSubResult& result) {
    auto local_it = pubsub_local_.find(result.conn_id);
    if (local_it == pubsub_local_.end()) return;
    PubSubLocalConn& local = local_it->second;
    Client* client = local.client;
    if (!client || !local.pending) return;

    Op& op = client->rob().at(result.op_id);
    reply_int(op.sink(), static_cast<long long>(result.count));
    op.state.store(OpState::Done, std::memory_order_release);
    enqueue_serve(client);
    mark_active(client);
    local.pending--;
    srv_->pubsub_pending_finished();
    if (!client->closing() && !local.pending && local.channels.empty() && local.patterns.empty() &&
        local.shard_channels.empty() && !local.cleanup_started)
        pubsub_local_.erase(local_it);
}

void pubsub_handle_result(PubSubEvent& event) {
    auto pending_it = pubsub_pending_.find(event.conn_id);
    if (pending_it == pubsub_pending_.end() || pending_it->second.op_id != event.op_id) return;
    PubSubPending& pending = pending_it->second;
    switch (event.kind) {
        case PubSubEventKind::ModifyResult:
            for (const PubSubEventItem& item : event.items)
                if (item.index < pending.changes.size() && pending.changes[item.index] < 0)
                    pending.changes[item.index] = item.changed ? 1 : 0;
            break;
        case PubSubEventKind::ChannelsResult:
            for (const PubSubEventItem& item : event.items) pending.channels.push_back(item.value);
            break;
        case PubSubEventKind::NumsubResult:
            for (const PubSubEventItem& item : event.items)
                if (item.index < pending.counts.size()) pending.counts[item.index] = item.count;
            break;
        case PubSubEventKind::NumpatResult:
            pending.count = event.count;
            break;
        case PubSubEventKind::ResetResult:
            break;
        default:
            std::abort();
    }
    if (!pending.remaining) std::abort();
    if (--pending.remaining == 0) pubsub_finish_pending(event.conn_id);
}

void pubsub_handle_cleanup_result(PubSubEvent& event) {
    auto it = pubsub_local_.find(event.conn_id);
    if (it == pubsub_local_.end() || !it->second.cleanup_started || !it->second.cleanup_remaining)
        return;
    PubSubLocalConn& local = it->second;
    if (--local.cleanup_remaining == 0) {
        pubsub_clear_local_subscriptions(local);
        local.cleanup_done = true;
        if (local.client && !local.client->dead()) mark_active(local.client);
    }
}

void pubsub_handle_acl_event(PubSubEvent& event) {
    const auto* permissions = static_cast<const AclPerm*>(event.acl_permissions);
    const bool kill_all = event.kind == PubSubEventKind::AclUserDeleted;
    std::vector<Client*> targets;
    for (Client* client : self_->clients()) {
        if (!client || client->dead() || client->closing() ||
            client->acl_user_idx() != event.acl_user_index)
            continue;
        bool subscribed = false;
        bool violating = kill_all;
        auto found = pubsub_local_.find(client->id());
        if (found != pubsub_local_.end()) {
            const PubSubLocalConn& local = found->second;
            subscribed = pubsub_total_subscription_count(local) != 0;
            if (!kill_all && permissions) {
                for (const std::string& pattern : local.patterns) {
                    const Slice value(pattern.data(), static_cast<uint32_t>(pattern.size()));
                    violating |= !acl_channel_allowed_any(*permissions, value, true);
                }
                for (const std::string& channel : local.channels) {
                    const Slice value(channel.data(), static_cast<uint32_t>(channel.size()));
                    violating |= !acl_channel_allowed_any(*permissions, value, false);
                }
                for (const std::string& channel : local.shard_channels) {
                    const Slice value(channel.data(), static_cast<uint32_t>(channel.size()));
                    violating |= !acl_channel_allowed_any(*permissions, value, false);
                }
            }
        }
        if (!violating) continue;
        targets.push_back(client);
        if (subscribed) srv_->acl_pubsub_client_killed();
    }
    for (Client* client : targets) close_client(client);
    if (kill_all) srv_->acl_kill_broadcast_finished();
}

void acl_broadcast_user_change(uint32_t user_index, const AclPerm* permissions, bool deleted) {
    if (deleted) srv_->acl_kill_broadcast_started(srv_->placement().ifid_threads().size());
    for (uint32_t io : srv_->placement().ifid_threads()) {
        PubSubEvent* event = pubsub_new_event(deleted ? PubSubEventKind::AclUserDeleted
                                                      : PubSubEventKind::AclPermissionsChanged);
        event->acl_user_index = user_index;
        event->acl_permissions = permissions;
        pubsub_post(io, event);
    }
    // Remote IOs are woken through their client-in channel. The local event has no wake
    // marker, so consume it before returning or a same-IO client can retain revoked access.
    pubsub_drain_events();
}

void pubsub_handle_event(PubSubEvent& event) {
    if (climon_handle_event(event)) return;
    switch (event.kind) {
        case PubSubEventKind::NotificationEnqueue:
            pubsub_notification_enqueue(std::move(event.notification));
            break;
        case PubSubEventKind::NotificationContinue:
            pubsub_notification_continue(event);
            break;
        case PubSubEventKind::ModifyRequest:
        case PubSubEventKind::PublishRequest:
        case PubSubEventKind::NotificationRequest:
        case PubSubEventKind::ChannelsRequest:
        case PubSubEventKind::NumsubRequest:
        case PubSubEventKind::NumpatRequest:
        case PubSubEventKind::ResetRequest:
        case PubSubEventKind::CleanupRequest:
            pubsub_handle_home_request(event);
            break;
        case PubSubEventKind::AclPermissionsChanged:
        case PubSubEventKind::AclUserDeleted:
            pubsub_handle_acl_event(event);
            break;
        case PubSubEventKind::DeliveryBatch:
            pubsub_handle_delivery_batch(event);
            break;
        case PubSubEventKind::CleanupResult:
            pubsub_handle_cleanup_result(event);
            break;
        default:
            pubsub_handle_result(event);
            break;
    }
}

uint32_t pubsub_drain_events() {
    std::deque<PubSubEvent*> events;
    self_->take_pubsub_events(events);
    uint32_t count = 0;
    for (;;) {
        while (!events.empty()) {
            PubSubEvent* event = events.front();
            events.pop_front();
            pubsub_handle_event(*event);
            pubsub_delete_event(event);
            count++;
        }
        if (pubsub_local_events_.empty()) break;
        events.swap(pubsub_local_events_);
    }
    return count;
}

// THE pass boundary for pub/sub, called once per IO loop pass from flush_ready behind a single
// predicted branch. Everything a pass parsed, resolved and owes is settled here in one go:
// that batching window is what a pipelined publisher's coalescing is made of. Out-of-line and
// cold, so a server with no subscribers pays one bool test per pass and nothing else.
__attribute__((noinline)) uint32_t pubsub_pass_flush() {
    uint32_t work = 0;
    for (int guard = 0; guard < 8; guard++) {
        if (!pubsub_local_events_.empty()) work += pubsub_drain_events();
        if (pubsub_outbox_dirty_.empty()) break;
        work += pubsub_flush_outboxes();
        if (pubsub_local_events_.empty()) break;
    }
    // Draining notifications can enroll BCAST keys in this same pass. Flush
    // them after the drain, before clearing the shared pending bit below.
    work += tracking_bcast_flush();
    pubsub_pass_pending_ = !pubsub_local_events_.empty() || !pubsub_outbox_dirty_.empty();
    return work;
}

PubSubLocalConn& pubsub_track(Client* client) {
    auto [it, inserted] = pubsub_local_.try_emplace(client->id());
    if (inserted) it->second.client = client;
    return it->second;
}

bool pubsub_prepare_rebind_events(const PubSubLocalConn& local, uint64_t client_id,
                                  uint32_t destination, std::vector<PubSubEvent*>& events) {
    auto make = [&](uint32_t target, bool pattern, bool shard) -> PubSubEvent* {
        auto* event = new (std::nothrow) PubSubEvent;
        if (!event) return nullptr;
        event->kind = PubSubEventKind::ModifyRequest;
        event->target_io = target;
        event->origin_io = destination;
        event->conn_id = client_id;
        event->pattern = pattern;
        event->shard = shard;
        event->rebind = true;
        events.push_back(event);
        return event;
    };
    auto exact = [&](const auto& values, bool shard) {
        std::unordered_map<uint32_t, PubSubEvent*> homes;
        for (const std::string& value : values) {
            const uint32_t home = pubsub_home_for(value);
            PubSubEvent*& event = homes[home];
            if (!event && !(event = make(home, false, shard))) return false;
            event->items.push_back(PubSubEventItem{0, false, 0, value});
        }
        return true;
    };
    if (!exact(local.channels, false) || !exact(local.shard_channels, true)) return false;
    for (uint32_t io : srv_->placement().ifid_threads()) {
        if (local.patterns.empty()) break;
        PubSubEvent* event = make(io, true, false);
        if (!event) return false;
        for (const std::string& pattern : local.patterns)
            event->items.push_back(PubSubEventItem{0, false, 0, pattern});
    }
    return true;
}

void pubsub_rehome_local(uint64_t epoch) {
    pubsub_begin_rehome_epoch(epoch);
    for (const auto& local_entry : pubsub_local_) {
        const uint64_t client_id = local_entry.first;
        const PubSubLocalConn& local = local_entry.second;
        auto post_exact = [&](const auto& values, bool shard) {
            std::unordered_map<uint32_t, PubSubEvent*> homes;
            for (const std::string& value : values) {
                const uint32_t home = pubsub_home_for(value);
                PubSubEvent*& event = homes[home];
                if (!event) {
                    event = pubsub_new_event(PubSubEventKind::ModifyRequest);
                    event->target_io = home;
                    event->origin_io = self_->id();
                    event->conn_id = client_id;
                    event->op_id = epoch;
                    event->subscribe = true;
                    event->shard = shard;
                    event->rebind = true;
                }
                event->items.push_back(PubSubEventItem{0, false, 0, value});
            }
            for (auto& entry : homes) pubsub_post(entry.first, entry.second);
        };
        post_exact(local.channels, false);
        post_exact(local.shard_channels, true);
        if (!local.patterns.empty()) {
            for (uint32_t io : srv_->placement().ifid_threads()) {
                PubSubEvent* event = pubsub_new_event(PubSubEventKind::ModifyRequest);
                event->target_io = io;
                event->origin_io = self_->id();
                event->conn_id = client_id;
                event->op_id = epoch;
                event->pattern = true;
                event->subscribe = true;
                event->rebind = true;
                for (const std::string& pattern : local.patterns)
                    event->items.push_back(PubSubEventItem{0, false, 0, pattern});
                pubsub_post(io, event);
            }
        }
    }
}

__attribute__((noinline)) PubSubStartResult
pubsub_begin_pending(Client* client, PubSubPending&& pending, std::vector<PubSubEvent*>& events) {
    if (events.empty()) std::abort();
    const uint64_t conn_id = client->id();
    PubSubLocalConn& local = pubsub_track(client);
    local.pending++;
    pending.remaining = events.size();
    const uint64_t op_id = pending.op_id;
    const bool exec_child = pending.exec_child != nullptr;
    if (!pubsub_pending_.emplace(conn_id, std::move(pending)).second) std::abort();
    srv_->pubsub_pending_started();

    // Publish the ROB slot before any home can answer it. The response event may race all the
    // way back to this IO, but it can never complete an operation absent from dispatch_.
    if (!exec_child) client->rob().publish();
    // Released by the quiescence backstop in flush_ready: the transition's parked lifetime is
    // its ROB slot, which retires only once every channel home has answered.
    if (!exec_child) barrier_arm(client, BarrierOwner::PubSub);
    for (PubSubEvent* event : events) {
        event->origin_io = self_->id();
        event->conn_id = conn_id;
        event->op_id = op_id;
    }
    for (PubSubEvent* event : events) pubsub_post(event->target_io, event);
    pubsub_drain_events();
    return PubSubStartResult::Async;
}

// Begin a validated subscription change on the connection IO worker. Copy arguments
// before handing requests to channel homes (all homes for patterns). Empty unsubscribe
// returns a synchronous acknowledgement; otherwise pubsub_begin_pending owns the
// continuation/events and publishes the ROB slot before requests can answer. An EXEC
// caller supplies a live child and coordinator state instead. Throwing allocations have
// no local recovery path; async completion waits for every home result.
PubSubStartResult pubsub_start_modify(Client* client, Op& op, bool pattern, bool subscribe,
                                      bool shard = false, void* exec_state = nullptr,
                                      uint64_t exec_id = 0) {
    PubSubPending pending;
    pending.kind = PubSubPendingKind::Modify;
    pending.op_id = exec_state ? exec_id : client->rob().dispatch_id();
    pending.exec_child = exec_state ? &op : nullptr;
    pending.exec_state = exec_state;
    pending.pattern = pattern;
    pending.shard = shard;
    pending.subscribe = subscribe;

    if (subscribe || op.argc() > 1) {
        pending.items.reserve(op.argc() - 1);
        for (uint32_t i = 1; i < op.argc(); i++) pending.items.push_back(pubsub_string(op.arg(i)));
    } else {
        auto local_it = pubsub_local_.find(client->id());
        if (local_it != pubsub_local_.end()) {
            const auto& values =
                shard ? local_it->second.shard_channels
                      : (pattern ? local_it->second.patterns : local_it->second.channels);
            pending.items.assign(values.begin(), values.end());
        }
        if (pending.items.empty()) {
            op.clear_reply_skip();
            auto sink = op.sink();
            pubsub_append_ack(sink, pattern, shard, false, nullptr,
                              local_it == pubsub_local_.end()
                                  ? 0
                                  : (shard ? pubsub_shard_subscription_count(local_it->second)
                                           : pubsub_subscription_count(local_it->second)),
                              op.resp3());
            return PubSubStartResult::Sync;
        }
    }
    pending.changes.assign(pending.items.size(), -1);

    const auto& ios = srv_->placement().ifid_threads();
    std::vector<PubSubEvent*> events;
    if (pattern) {
        events.reserve(ios.size());
        for (uint32_t io : ios) {
            PubSubEvent* event = pubsub_new_event(PubSubEventKind::ModifyRequest);
            event->pattern = true;
            event->shard = false;
            event->subscribe = subscribe;
            event->target_io = io;
            for (uint32_t i = 0; i < pending.items.size(); i++)
                event->items.push_back(PubSubEventItem{i, false, 0, pending.items[i]});
            events.push_back(event);
        }
    } else {
        std::unordered_map<uint32_t, PubSubEvent*> homes;
        for (uint32_t i = 0; i < pending.items.size(); i++) {
            const uint32_t home = pubsub_home_for(pending.items[i]);
            PubSubEvent*& event = homes[home];
            if (!event) {
                event = pubsub_new_event(PubSubEventKind::ModifyRequest);
                event->shard = shard;
                event->subscribe = subscribe;
                event->target_io = home;
                events.push_back(event);
            }
            event->items.push_back(PubSubEventItem{i, false, 0, pending.items[i]});
        }
    }
    return pubsub_begin_pending(client, std::move(pending), events);
}

PubSubStartResult pubsub_start_publish(Client* client, Op& op, bool shard = false) {
    const bool subscribers =
        shard ? srv_->pubsub_any_shard_subscribers() : srv_->pubsub_any_subscribers();
    if (!subscribers) {
        reply_int(op.sink(), 0);
        return PubSubStartResult::Sync;
    }
    std::string channel = pubsub_string(op.arg(1));
    std::string message = pubsub_string(op.arg(2));
    const uint32_t home = pubsub_home_for(channel);

    PubSubEvent* event = pubsub_new_event(PubSubEventKind::PublishRequest);
    event->origin_io = self_->id();
    event->conn_id = client->id();
    event->op_id = client->rob().dispatch_id();
    event->shard = shard;
    event->channel = std::move(channel);
    event->message = std::move(message);
    event->target_io = home;

    PubSubLocalConn& local = pubsub_track(client);
    local.pending++;
    srv_->pubsub_pending_started();
    // Publish requests from one producer enter each channel home's FIFO in parse order. They
    // therefore need no per-connection scatter barrier: results can complete arbitrary ROB
    // slots while the channel home remains the sole delivery-order authority.
    client->rob().publish();
    // The ROB window bounds this connection's in-flight publishes, and subscriber output
    // limits bound buffered deliveries. Defer draining to the pass boundary so a pipeline
    // can coalesce into one batch per destination without a separate publish cap.
    pubsub_post(event->target_io, event);
    return PubSubStartResult::Async;
}

// PUBSUB syntax errors echo the subcommand token as the client spelled it;
// command_reply_subcommand_error supplies that protocol grammar.
void pubsub_reply_bad_subcommand(Op& op, bool unknown) {
    command_reply_subcommand_error(op, "PUBSUB", unknown);
}

void pubsub_reply_bad_arity(Op& op, const char* arm) {
    std::string message = "ERR wrong number of arguments for 'pubsub|";
    message += arm;
    message += "' command";
    reply_err(op.sink(), message.c_str());
}

PubSubStartResult pubsub_start_channels(Client* client, Op& op, bool shard = false) {
    if (op.argc() > 3) {
        pubsub_reply_bad_subcommand(op, false);
        return PubSubStartResult::Sync;
    }
    PubSubPending pending;
    pending.kind = PubSubPendingKind::Channels;
    pending.op_id = client->rob().dispatch_id();
    const std::string pattern = op.argc() == 3 ? pubsub_string(op.arg(2)) : std::string();
    std::vector<PubSubEvent*> events;
    for (uint32_t io : srv_->placement().ifid_threads()) {
        PubSubEvent* event = pubsub_new_event(PubSubEventKind::ChannelsRequest);
        event->shard = shard;
        event->pattern_text = pattern;
        event->pattern = op.argc() == 3;
        event->target_io = io;
        events.push_back(event);
    }
    return pubsub_begin_pending(client, std::move(pending), events);
}

PubSubStartResult pubsub_start_numsub(Client* client, Op& op, bool shard = false) {
    if (op.argc() == 2) {
        reply_array_header(op.sink(), 0);
        return PubSubStartResult::Sync;
    }
    PubSubPending pending;
    pending.kind = PubSubPendingKind::Numsub;
    pending.op_id = client->rob().dispatch_id();
    for (uint32_t i = 2; i < op.argc(); i++) pending.items.push_back(pubsub_string(op.arg(i)));
    pending.counts.resize(pending.items.size());
    std::unordered_map<uint32_t, PubSubEvent*> homes;
    std::vector<PubSubEvent*> events;
    for (uint32_t i = 0; i < pending.items.size(); i++) {
        const uint32_t home = pubsub_home_for(pending.items[i]);
        PubSubEvent*& event = homes[home];
        if (!event) {
            event = pubsub_new_event(PubSubEventKind::NumsubRequest);
            event->shard = shard;
            event->target_io = home;
            events.push_back(event);
        }
        event->items.push_back(PubSubEventItem{i, false, 0, pending.items[i]});
    }
    return pubsub_begin_pending(client, std::move(pending), events);
}

PubSubStartResult pubsub_start_numpat(Client* client, Op& op) {
    if (op.argc() != 2) {
        pubsub_reply_bad_arity(op, "numpat");
        return PubSubStartResult::Sync;
    }
    PubSubPending pending;
    pending.kind = PubSubPendingKind::Numpat;
    pending.op_id = client->rob().dispatch_id();
    PubSubEvent* event = pubsub_new_event(PubSubEventKind::NumpatRequest);
    event->target_io = srv_->placement().ifid_threads().front();
    std::vector<PubSubEvent*> events{event};
    return pubsub_begin_pending(client, std::move(pending), events);
}

PubSubStartResult pubsub_start_reset(Client* client, Op&) {
    PubSubPending pending;
    pending.kind = PubSubPendingKind::Reset;
    pending.op_id = client->rob().dispatch_id();
    std::vector<PubSubEvent*> events;
    for (uint32_t io : srv_->placement().ifid_threads()) {
        PubSubEvent* event = pubsub_new_event(PubSubEventKind::ResetRequest);
        event->target_io = io;
        events.push_back(event);
    }
    return pubsub_begin_pending(client, std::move(pending), events);
}

PubSubStartResult pubsub_start_help(Op& op) {
    static constexpr const char* kHelp[] = {
        "PUBSUB <subcommand> [<arg> [value] [opt] ...]. Subcommands are:",
        "CHANNELS [<pattern>]",
        "    Return the currently active channels matching a <pattern> (default: '*').",
        "NUMPAT",
        "    Return number of subscriptions to patterns.",
        "NUMSUB [<channel> ...]",
        "    Return the number of subscribers for the specified channels, excluding",
        "    pattern subscriptions(default: no channels).",
        "SHARDCHANNELS [<pattern>]",
        "    Return the currently active shard level channels matching a <pattern> (default: '*').",
        "SHARDNUMSUB [<shardchannel> ...]",
        "    Return the number of subscribers for the specified shard level channel(s)",
        "HELP",
        "    Print this help.",
    };
    auto sink = op.sink();
    reply_array_header(sink, sizeof(kHelp) / sizeof(kHelp[0]));
    for (const char* line : kHelp) reply_simple(sink, line);
    return PubSubStartResult::Sync;
}

// Route a registry/arity-validated pub/sub or CLIENT/MONITOR command on its IO owner.
// Check channel ACLs before publication. Sync leaves reply bytes for caller completion;
// Async delegates ownership to the pending/home-event protocol, which publishes before
// posting and later release-stores Done. Errors produce synchronous protocol replies;
// allocation failure is not translated into a reply in this dispatcher.
__attribute__((noinline, noipa)) PubSubStartResult pubsub_start_command(Client* client, Op& op) {
    LatencyTrackingScope latency(self_->id(), op);
    if (op.cmd_name().eq_icase("client") || op.cmd_name().eq_icase("monitor")) {
        const ClimonStartResult scatter = climon_start_client_command(client, op);
        return scatter == ClimonStartResult::Async ? PubSubStartResult::Async
                                                   : PubSubStartResult::Sync;
    }
    if (op.cmd_name().eq_icase("subscribe")) {
        if (srv_->acl_active() && !acl_pubsub_channel_entry(*client, op, false, *self_))
            return PubSubStartResult::Sync;
        return pubsub_start_modify(client, op, false, true);
    }
    if (op.cmd_name().eq_icase("unsubscribe")) return pubsub_start_modify(client, op, false, false);
    if (op.cmd_name().eq_icase("psubscribe")) {
        if (srv_->acl_active() && !acl_pubsub_channel_entry(*client, op, true, *self_))
            return PubSubStartResult::Sync;
        return pubsub_start_modify(client, op, true, true);
    }
    if (op.cmd_name().eq_icase("punsubscribe")) return pubsub_start_modify(client, op, true, false);
    if (op.cmd_name().eq_icase("ssubscribe")) {
        if (srv_->acl_active() && !acl_pubsub_channel_entry(*client, op, false, *self_))
            return PubSubStartResult::Sync;
        return pubsub_start_modify(client, op, false, true, true);
    }
    if (op.cmd_name().eq_icase("sunsubscribe"))
        return pubsub_start_modify(client, op, false, false, true);
    if (op.cmd_name().eq_icase("publish")) {
        if (srv_->acl_active() && !acl_pubsub_channel_entry(*client, op, false, *self_))
            return PubSubStartResult::Sync;
        return pubsub_start_publish(client, op);
    }
    if (op.cmd_name().eq_icase("spublish")) {
        if (srv_->acl_active() && !acl_pubsub_channel_entry(*client, op, false, *self_))
            return PubSubStartResult::Sync;
        return pubsub_start_publish(client, op, true);
    }
    if (!op.cmd_name().eq_icase("pubsub")) {
        reply_err(op.sink(), "ERR internal pubsub command error");
        return PubSubStartResult::Sync;
    }
    if (op.arg(1).eq_icase("help")) {
        if (op.argc() != 2) {
            pubsub_reply_bad_arity(op, "help");
            return PubSubStartResult::Sync;
        }
        return pubsub_start_help(op);
    }
    if (op.arg(1).eq_icase("channels")) return pubsub_start_channels(client, op);
    if (op.arg(1).eq_icase("numsub")) return pubsub_start_numsub(client, op);
    if (op.arg(1).eq_icase("numpat")) return pubsub_start_numpat(client, op);
    if (op.arg(1).eq_icase("shardchannels")) return pubsub_start_channels(client, op, true);
    if (op.arg(1).eq_icase("shardnumsub")) return pubsub_start_numsub(client, op, true);
    pubsub_reply_bad_subcommand(op, true);
    return PubSubStartResult::Sync;
}

void pubsub_reply_ping(Op& op) {
    auto sink = op.sink();
    reply_array_header(sink, 2);
    reply_bulk(sink, Slice("pong", 4));
    if (op.argc() == 2)
        reply_bulk(sink, op.arg(1));
    else
        reply_bulk(sink, Slice("", 0));
}

void pubsub_reply_restricted(Op& op) {
    std::string command(op.cmd_name().p, op.cmd_name().n);
    for (char& ch : command)
        if (ch >= 'A' && ch <= 'Z') ch = static_cast<char>(ch + ('a' - 'A'));
    if (op.cmd_name().eq_icase("pubsub")) {
        const bool known = op.arg(1).eq_icase("help") || op.arg(1).eq_icase("channels") ||
                           op.arg(1).eq_icase("numsub") || op.arg(1).eq_icase("numpat") ||
                           op.arg(1).eq_icase("shardchannels") || op.arg(1).eq_icase("shardnumsub");
        if (!known) {
            pubsub_reply_bad_subcommand(op, true);
            return;
        }
        if ((op.arg(1).eq_icase("help") || op.arg(1).eq_icase("numpat")) && op.argc() != 2) {
            pubsub_reply_bad_arity(op, op.arg(1).eq_icase("help") ? "help" : "numpat");
            return;
        }
        command += '|';
        const size_t subcommand = command.size();
        command.append(op.arg(1).p, op.arg(1).n);
        for (size_t index = subcommand; index < command.size(); index++)
            if (command[index] >= 'A' && command[index] <= 'Z')
                command[index] = static_cast<char>(command[index] + ('a' - 'A'));
    }
    std::string message = "ERR Can't execute '";
    message += command;
    message +=
        "': only (P|S)SUBSCRIBE / (P|S)UNSUBSCRIBE / PING / QUIT / RESET are allowed in this context";
    reply_err(op.sink(), message.c_str());
}

bool pubsub_disconnect_ready(Client* client) {
    // A committed EXEC may still be applying subscription children on IO.
    // Wait for its ROB retirement before the one cleanup sweep, otherwise
    // a later child can install a home entry after that sweep has passed.
    if (client->multi_session() && !client->rob().quiesced()) return false;
    // FLIP pin: both teardown paths pass this gate before the connection leaves
    // ThreadCtx::clients and before cleanup reads Placement. While a FLIP holds this IO's
    // connection set, the close waits here (still owned, counted and allocated).
    if (__builtin_expect(flip_close_pin_, false) && flip_close_held()) return false;
    auto it = pubsub_local_.find(client->id());
    if (it == pubsub_local_.end()) return true;
    PubSubLocalConn& local = it->second;
    if (!local.cleanup_started) {
        if (!local.pending && local.channels.empty() && local.patterns.empty() &&
            local.shard_channels.empty()) {
            pubsub_local_.erase(it);
            return true;
        }
        local.cleanup_started = true;
        local.cleanup_remaining = srv_->placement().ifid_threads().size();
        for (uint32_t io : srv_->placement().ifid_threads()) {
            PubSubEvent* event = pubsub_new_event(PubSubEventKind::CleanupRequest);
            event->origin_io = self_->id();
            event->conn_id = client->id();
            pubsub_post(io, event);
        }
        pubsub_drain_events();
        return false;
    }
    if (!local.cleanup_done) return false;
    pubsub_local_.erase(it);
    return true;
}

void pubsub_shutdown_events() {
    std::deque<PubSubEvent*> events;
    self_->take_pubsub_events(events);
    events.insert(events.end(), pubsub_local_events_.begin(), pubsub_local_events_.end());
    pubsub_local_events_.clear();
    for (PubSubEvent* event : events) pubsub_delete_event(event);
    // Un-flushed outbox items still hold one blob reference each; the gauge must reach zero.
    for (uint32_t io : pubsub_outbox_dirty_) {
        PubSubOutbox& box = pubsub_outbox_[io];
        for (PubSubDelivery& item : box.deliveries) pubsub_blob_unref(item.blob);
        box.deliveries.clear();
        box.results.clear();
    }
    pubsub_outbox_dirty_.clear();
    pubsub_pass_pending_ = false;
    pubsub_notification_chains_.clear();
}

std::unordered_map<std::string, std::vector<PubSubRef>> pubsub_channels_;
std::unordered_map<std::string, std::vector<PubSubRef>> pubsub_shard_channels_;
std::vector<PubSubPatternRef> pubsub_patterns_;
std::unordered_map<uint64_t, PubSubLocalConn> pubsub_local_;
std::unordered_map<uint64_t, PubSubPending> pubsub_pending_;
std::deque<PubSubEvent*> pubsub_local_events_;
std::vector<PubSubOutbox> pubsub_outbox_;  // sized on first pub/sub use, never before
std::vector<uint32_t> pubsub_outbox_dirty_;
bool pubsub_pass_pending_ = false;  // the one hot-path bit flush_ready tests
uint64_t pubsub_rehome_epoch_ = 0;
