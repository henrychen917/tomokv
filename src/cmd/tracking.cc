// tracking.cc -- CLIENT TRACKING (RESP3 server-assisted client-side caching).
//
// OWNERSHIP, which is the whole design.
//
//   * The key -> interested-connections table is PER IO OWNER and holds only that owner's own
//     connections (IoLoop::climon_track_keys_). A connection is owned by exactly one io thread
//     at a time; migration extracts and installs its entries at the ownership commit edge. Thus
//     each table still has exactly one reader and one writer and NO LOCK EXISTS ON ANY ARMED PATH.
//     A single global table would have put a lock on the tracking-armed write path, which is
//     precisely where writes live.
//
//   * Read registration is io-side at in-order retirement. The armed dispatch gate records
//     only pending invalidation obligations: a foreign write between execution and retirement
//     must invalidate the pending result too. An earlier same-connection write cannot erase the
//     later read's completed registration, because that registration does not exist yet.
//     A read from a NON-tracking connection never reaches this file.
//
//   * The invalidation SOURCE is the executor-side keyspace-notification chassis: the armed write
//     handler variants already observe every mutation with its key, including the expiry and
//     eviction paths that no io thread can see. CLIENT TRACKING arms them through the synthetic
//     NOTIFY_TRACKING class, so a write is observed exactly once for both features and, when only
//     one of them is armed, the other produces nothing.
//
//   * Delivery is a broadcast of the changed KEY (never of client state) to the io owners that
//     actually have tracking connections, taken from Server::climon_tracking_io_mask(). Each
//     owner filters against its own table. A global monotonic key filter keeps writes to
//     un-tracked keys from posting anything at all.
//
// REDIRECT sends the invalidation to another connection, which may be owned by a different io
// thread; that is one extra hop through the same transport (TrackingDeliver).

#include "t_stream.h"
#include "../core/io_loop.h"

namespace tomo {

namespace {

// Monotonic membership filter over every key any owner has registered. Set-only; cleared when a
// tracking table is flushed. A false positive costs one broadcast that every owner then filters
// out, so it can only ever cost work, never correctness.
constexpr uint32_t kTrackFilterWords = 1024;   // 64 Kbit
std::atomic<uint64_t> g_track_filter[kTrackFilterWords];
// Number of registered BCAST prefixes across the process. Non-zero forces every changed key to
// broadcast, because prefix membership cannot be tested by the key filter.
std::atomic<uint64_t> g_track_bcast_prefixes{0};
// Release certificates follow actual publication, never speculative fire points.
// A separate line avoids false sharing with the membership filter and prefix counter.
alignas(64) std::atomic<uint64_t> g_tracking_clock{1};
void tracking_read_marker(Shard&, Op&) { std::abort(); }


inline void track_filter_add(uint64_t hash) {
    const uint32_t word = static_cast<uint32_t>((hash >> 6) % kTrackFilterWords);
    g_track_filter[word].fetch_or(1ull << (hash & 63), std::memory_order_relaxed);
}

inline bool track_filter_may_contain(uint64_t hash) {
    const uint32_t word = static_cast<uint32_t>((hash >> 6) % kTrackFilterWords);
    return (g_track_filter[word].load(std::memory_order_relaxed) >> (hash & 63)) & 1;
}

// Explicit BCAST prefixes cannot overlap; adding the implicit empty prefix later is Redis's
// exception, handled after validation below and with per-prefix delivery above.
bool track_prefix_overlaps(const std::string& a, const std::string& b) {
    const size_t shortest = std::min(a.size(), b.size());
    return std::memcmp(a.data(), b.data(), shortest) == 0;
}

}  // namespace

uint64_t tracking_clock_observe() {
    return g_tracking_clock.load(std::memory_order_acquire);
}

uint64_t tracking_clock_commit() {
    const uint64_t stamp = g_tracking_clock.fetch_add(1, std::memory_order_acq_rel) + 1;
    if (!stamp) std::abort();  // never reuse a certificate
    return stamp;
}

void tracking_observe_read(Shard& shard, Op& op) {
    if (!op.spec || op.spec->handler_notify != tracking_read_marker) return;
    auto& read = *static_cast<IoLoop::TrackingRead*>(const_cast<CommandSpec*>(op.spec));
    uint64_t stamp = tracking_clock_observe();
    const uint64_t epoch = shard.server()->atomic_snapshot();
    if (op.has_read_cut() && op.read_cut(epoch) < epoch) {
        // A pinned snapshot can precede execution. Certify only a world its cut includes.
        stamp = op.read_cut(epoch) >= read.dispatch_epoch ? read.dispatch_stamp : 0;
    }
    uint64_t& observed = read.observed[shard.id()];
    observed = std::min(observed, stamp); // each shard slot has exactly one writer
}

void tracking_observe_local(Server& server, Op& op) {
    (void)server;
    if (!op.spec || op.spec->handler_notify != tracking_read_marker) return;
    auto& read = *static_cast<IoLoop::TrackingRead*>(const_cast<CommandSpec*>(op.spec));
    const uint64_t stamp = tracking_clock_observe();
    for (uint32_t shard : read.shards)
        read.observed[shard] = std::min(read.observed[shard], stamp);
}

// ---- registration --------------------------------------------------------------------------

void IoLoop::tracking_note_prefix_registered(const std::string& prefix, bool added) {
    (void)prefix;
    if (added) {
        g_track_bcast_prefixes.fetch_add(1, std::memory_order_relaxed);
        srv_->climon_note_tracking_prefix_delta(1);
    } else {
        g_track_bcast_prefixes.fetch_sub(1, std::memory_order_relaxed);
        srv_->climon_note_tracking_prefix_delta(-1);
    }
}

// Called from climon_armed_gate for a connection whose tracking is ON. BCAST mode keeps no table
// at all -- its prefix registry is the whole subscription -- so only default (per-key
// remembering) mode registers here.
void IoLoop::tracking_register_read(Client* client, ClimonConn& state, Op& op) {
    // Redis preserves CACHING across every CLIENT command, including introspection and errors.
    // Consuming it before TRACKINGINFO both hides the flag and loses the following OPTIN read's
    // invalidation (or wrongly subscribes an exempted OPTOUT read). CLIENT has no keys to enroll.
    if (op.cmd_name().eq_icase("client")) return;
    const bool caching = state.caching_armed;
    state.caching_armed = false;   // CLIENT subcommands above do not consume the choice
    if (state.bcast) return;
    const CommandSpec* spec = op.spec;
    if (!spec) return;
    // Only genuine reads register. A write from the tracking connection is not a subscription.
    if (!(spec->flags & CmdFlags::Readonly) || (spec->flags & CmdFlags::Write)) return;
    // OPTIN: register only when the previous command was CLIENT CACHING yes.
    // OPTOUT: register unless the previous command was CLIENT CACHING no.
    if (state.optin && !caching) return;
    if (state.optout && caching) return;

    uint32_t first = spec->first_key > 0 ? static_cast<uint32_t>(spec->first_key) : 0;
    uint32_t end = spec->last_key < 0 ? op.argc()
        : std::min<uint32_t>(op.argc(), static_cast<uint32_t>(spec->last_key) + 1);
    if (spec->flags & CmdFlags::StreamRoute) {
        // Registration must not append a parser error to the real reply; dispatch owns that error.
        Op probe;
        for (uint32_t i = 0; i < op.argc(); ++i)
            if (!probe.push_arg(op.arg(i))) return;
        StreamXreadArgs parsed;
        if (!stream_parse_xread(probe, parsed)) return;
        first = parsed.first_key;
        end = first + parsed.key_count;
    }
    if (!first) return;
    (void)client;
    const int32_t step = spec->key_step > 0 ? spec->key_step : 1;
    const uint64_t stamp = tracking_clock_observe();
    auto read = std::make_unique<TrackingRead>(op.spec, stamp, srv_->atomic_snapshot(), srv_->nshards());
    auto& keys = read->keys;
    for (uint32_t i = first; i < end; i += static_cast<uint32_t>(step)) {
        const Slice key = op.arg(i);
        const std::string name(key.p, key.n);
        if (std::find(keys.begin(), keys.end(), name) != keys.end()) continue;
        keys.push_back(name);
        read->shards.push_back(srv_->router().shard_of(FlatStore::hash_key(key)));
        state.tracking_pending[keys.back()].reads.push_back(&op);
        // Publish interest before execution. A foreign write cannot pass the
        // monotonic filter just because this read has not retired yet.
        track_filter_add(FlatStore::hash_key(Slice(key.p, key.n)));
    }
    read->handler_notify = tracking_read_marker;
    // QUEUED stores the registry spec beyond this ROB slot's lifetime.
    if (!multi_session_active(*client)) op.spec = read.get();
    state.tracking_reads[&op] = std::move(read);
}

void IoLoop::tracking_register_key(uint64_t id, const std::string& name, uint64_t stamp) {
    const Slice key(name.data(), static_cast<uint32_t>(name.size()));
    if (srv_->cfg().tracking_table_max_keys &&
        climon_track_keys_.size() >= srv_->cfg().tracking_table_max_keys &&
        climon_track_keys_.find(name) == climon_track_keys_.end()) {
        // Keep the existing bounded-table policy: evicting a completed
        // registration sends an invalidation, never a silent removal.
        size_t bucket;
        do { bucket = next_random() % climon_track_keys_.bucket_count(); }
        while (climon_track_keys_.bucket_size(bucket) == 0);
        auto sampled = climon_track_keys_.begin(bucket);
        std::advance(sampled, next_random() % climon_track_keys_.bucket_size(bucket));
        auto victim = climon_track_keys_.find(sampled->first);
        if (victim != climon_track_keys_.end()) {
            const Slice vkey(victim->first.data(), static_cast<uint32_t>(victim->first.size()));
            for (uint64_t owner : victim->second) {
                ClimonConn* target = climon_conn_find(owner);
                if (target) {
                    tracking_deliver_frame(*target, owner, vkey, false);
                    target->tracking_enrolled.erase(victim->first);
                }
            }
            srv_->climon_note_tracking_item_delta(-static_cast<int64_t>(victim->second.size()));
            srv_->climon_note_tracking_key_delta(-1);
            climon_track_keys_.erase(victim);
        }
    }
    auto& owners = climon_track_keys_[name];
    if (owners.empty()) srv_->climon_note_tracking_key_delta(1);
    if (std::find(owners.begin(), owners.end(), id) == owners.end()) {
        owners.push_back(id);
        srv_->climon_note_tracking_item_delta(1);
    }
    if (auto* state = climon_conn_find(id)) state->tracking_enrolled[name] = stamp;
    track_filter_add(FlatStore::hash_key(key));
}

void IoLoop::tracking_retire_read(Client& client, Op& op) {
    ClimonConn* state = climon_conn_find(client.id());
    if (!state) return;
    auto read = state->tracking_reads.find(&op);
    if (read == state->tracking_reads.end()) return;
    auto& receipt = *read->second;
    for (size_t i = 0; i < receipt.keys.size(); ++i) {
        const std::string& key = receipt.keys[i];
        if (receipt.canceled) continue;
        uint64_t stamp = receipt.observed[receipt.shards[i]];
        if (stamp == UINT64_MAX) stamp = 0; // no successful observation certificate
        auto pending = state->tracking_pending.find(key);
        if (pending == state->tracking_pending.end()) std::abort();
        auto& obligation = pending->second;
        if (stamp < obligation.invalidated) {
            if (obligation.delivered < obligation.invalidated) {
                tracking_deliver_frame(*state, client.id(),
                    Slice(key.data(), static_cast<uint32_t>(key.size())), false);
                obligation.delivered = obligation.invalidated;
            }
        } else if (state->tracking_on) {
            tracking_register_key(client.id(), key, stamp);
        }
        auto member = std::find(obligation.reads.begin(), obligation.reads.end(), &op);
        if (member == obligation.reads.end()) std::abort();
        obligation.reads.erase(member);
        if (obligation.reads.empty()) state->tracking_pending.erase(pending);
    }
    op.spec = receipt.original;
    state->tracking_reads.erase(read);
    if (state->tracking_draining && state->tracking_reads.empty()) {
        state->tracking_draining = false;
        if (!climon_local_trackers_) std::abort();
        --climon_local_trackers_;
        if (!climon_local_trackers_) srv_->climon_set_tracking_io(self_->id(), false);
        srv_->climon_tracking_removed();
        climon_refresh_armed();
    }
}

// The cold suppressing drain's retire hook stays SPECIAL-only (zc_ptr state, as in the hot serve)
// for every connection except a tracking one, whose plain reads enroll at retirement (above).
// Decided per connection before each drain; an owner with no local tracker answers without a probe.
bool IoLoop::tracking_retire_plain(Client* client) {
    if (!climon_local_trackers_) return false;
    const ClimonConn* state = climon_conn_find(client->id());
    return state && (state->tracking_on || state->tracking_draining);
}

void IoLoop::tracking_forget_client(uint64_t id, ClimonConn& state) {
    // OFF/RESET can run with older reads still executing. Their spec copies live until
    // retirement; cancellation is IO-owned and never consulted by the executor.
    for (auto& read : state.tracking_reads) read.second->canceled = true;
    state.tracking_pending.clear();
    state.tracking_enrolled.clear();
    state.tracking_bcast_pending.clear();
    for (auto it = climon_track_keys_.begin(); it != climon_track_keys_.end();) {
        auto& owners = it->second;
        auto found = std::find(owners.begin(), owners.end(), id);
        if (found != owners.end()) {
            owners.erase(found);
            srv_->climon_note_tracking_item_delta(-1);
        }
        if (owners.empty()) {
            srv_->climon_note_tracking_key_delta(-1);
            it = climon_track_keys_.erase(it);
        } else {
            ++it;
        }
    }
    for (const std::string& prefix : state.prefixes) tracking_note_prefix_registered(prefix, false);
    state.prefixes.clear();
    if (state.tracking_on) {
        state.tracking_on = false;
        state.bcast = state.optin = state.optout = state.noloop = false;
        state.caching_armed = false;
        state.redirect = 0;
        state.tracking_draining = !state.tracking_reads.empty();
        if (!state.tracking_draining) {
            if (climon_local_trackers_) climon_local_trackers_--;
            if (!climon_local_trackers_) srv_->climon_set_tracking_io(self_->id(), false);
            srv_->climon_tracking_removed();
        }
        if (state.client) command_client_set_tracking_view(state.client, false, -1);
    }
}

void IoLoop::tracking_migration_snapshot(uint64_t id, std::vector<std::string>& keys) const {
    for (const auto& entry : climon_track_keys_)
        if (std::find(entry.second.begin(), entry.second.end(), id) != entry.second.end())
            keys.push_back(entry.first);
}

void IoLoop::tracking_migration_extract(uint64_t id, std::vector<std::string>& keys) {
    size_t out = 0;
    for (size_t i = 0; i < keys.size(); i++) {
        std::string& key = keys[i];
        auto entry = climon_track_keys_.find(key);
        if (entry == climon_track_keys_.end()) continue;  // invalidated since reversible prepare
        auto owner = std::find(entry->second.begin(), entry->second.end(), id);
        if (owner == entry->second.end()) continue;
        *owner = entry->second.back();
        entry->second.pop_back();
        srv_->climon_note_tracking_item_delta(-1);
        if (entry->second.empty()) {
            srv_->climon_note_tracking_key_delta(-1);
            climon_track_keys_.erase(entry);
        }
        if (out != i) keys[out] = std::move(key);
        out++;
    }
    keys.resize(out);
}

bool IoLoop::tracking_migration_install(uint64_t id, const std::vector<std::string>& keys) {
    try {
        climon_track_keys_.reserve(climon_track_keys_.size() + keys.size());
        for (const std::string& key : keys) {
            std::vector<uint64_t>& owners = climon_track_keys_[key];
            if (owners.empty()) srv_->climon_note_tracking_key_delta(1);
            if (std::find(owners.begin(), owners.end(), id) == owners.end()) {
                owners.push_back(id);
                srv_->climon_note_tracking_item_delta(1);
            }
            track_filter_add(FlatStore::hash_key(Slice(
                key.data(), static_cast<uint32_t>(key.size()))));
        }
    } catch (const std::bad_alloc&) {
        return false;
    }
    return true;
}

// ---- delivery ------------------------------------------------------------------------------

void IoLoop::tracking_emit_invalidation(Client* target, bool redirected, Slice key, bool flush,
                                       uint64_t source_id, uint64_t generation, bool batched) {
    const uint32_t live_io = target->ifid_thread();
    if (live_io != self_->id()) {
        PubSubEvent* event = pubsub_new_event(PubSubEventKind::TrackingDeliver);
        event->target_io = live_io;
        event->origin_io = self_->id();
        event->client_id = target->id();
        event->caller_id = source_id;
        event->op_id = generation;
        event->subscribe = redirected;
        event->pattern = batched;
        event->count = flush ? 1 : 0;
        event->channel.assign(key.p, key.n);
        pubsub_post(live_io, event);
        srv_->tracking_forwarded_stale_added();
        return;
    }
    // Redis decides after resolving REDIRECT. RESP3 always has a push channel; RESP2 only has a
    // valid carriage when another connection is the target and that connection is in pub/sub mode.
    const bool resp3_push = target->resp3();
    if (!resp3_push && (!redirected || !target->subscriber_mode())) return;

    SmallBuf<128> frame;
    if (resp3_push) {
        reply_push_header(frame, 2);
        reply_bulk(frame, Slice("invalidate", 10));
    } else {
        // RESP2 legacy carriage: the invalidation arrives as an ordinary pub/sub message on the
        // reserved __redis__:invalidate channel.
        reply_array_header(frame, 3);
        reply_bulk(frame, Slice("message", 7));
        reply_bulk(frame, Slice("__redis__:invalidate", 20));
    }
    if (flush) {
        // Oracle-confirmed: RESP3 null (`_`), RESP2 redirect path null BULK (`$-1`).
        if (resp3_push) frame.append("_\r\n", 3);
        else frame.append("$-1\r\n", 5);
    } else if (batched) {
        frame.append(key.p, key.n); // an already framed, sorted array of keys
    } else {
        reply_array_header(frame, 1);
        reply_bulk(frame, key);
    }
    climon_push_wire(target, std::string(frame.data(), frame.size()));
    srv_->climon_note_invalidation();
}

void IoLoop::tracking_redirect_broken(ClimonConn& state) {
    state.broken_redirect = true;
    Client* client = state.client;
    if (client && !client->dead() && !client->closing() && client->resp3()) {
        SmallBuf<64> frame;
        reply_push_header(frame, 2);
        reply_bulk(frame, Slice("tracking-redir-broken", 21));
        reply_int(frame, static_cast<long long>(state.redirect));
        climon_push_wire(client, std::string(frame.data(), frame.size()));
    }
}

// owner_id names the TRACKING connection. The frame goes to it, or to its REDIRECT target.
void IoLoop::tracking_deliver_frame(ClimonConn& state, uint64_t owner_id, Slice key, bool flush, bool batched) {
    if (!state.redirect) {
        Client* target = state.client;
        if (!target || target->dead() || target->closing()) return;
        tracking_emit_invalidation(target, false, key, flush, 0, 0, batched);
        return;
    }
    // REDIRECT: the target may be owned by another io thread.
    uint32_t owner_io = 0;
    if (!command_client_directory_find(state.redirect, owner_io)) {
        // Oracle-confirmed: detection is LAZY (nothing happens at the target's disconnect) and
        // tracking stays ON. A RESP3 tracking client is told with a `tracking-redir-broken` push
        // on EVERY subsequent invalidation attempt; a RESP2 one sees nothing on the wire and only
        // the TRACKINGINFO flag changes.
        tracking_redirect_broken(state);
        return;
    }
    if (owner_io == self_->id()) {
        ClimonConn* target_state = climon_conn_find(state.redirect);
        Client* target = target_state ? target_state->client : nullptr;
        if (!target) {
            for (Client* c : self_->clients())
                if (c && c->id() == state.redirect) { target = c; break; }
        }
        if (!target || target->dead() || target->closing()) {
            tracking_redirect_broken(state);
            return;
        }
        tracking_emit_invalidation(target, true, key, flush, owner_id, state.tracking_generation, batched);
        return;
    }
    PubSubEvent* event = pubsub_new_event(PubSubEventKind::TrackingDeliver);
    event->target_io = owner_io;
    event->origin_io = self_->id();
    event->client_id = state.redirect;
    event->caller_id = owner_id;
    event->op_id = state.tracking_generation;
    event->subscribe = true;
    event->pattern = batched;
    event->count = flush ? 1 : 0;
    event->channel.assign(key.p, key.n);
    pubsub_post(owner_io, event);
}

// One owner's local pass over a changed key.
void IoLoop::tracking_invalidate_local(Slice key, uint64_t writer_id, uint64_t stamp) {
    if (!stamp) std::abort(); // every transport must carry its publication certificate
    const std::string name(key.p, key.n);
    for (auto& entry : climon_conn_) {
        ClimonConn& state = entry.second;
        if (!state.tracking_on) continue;
        const bool suppressed = state.noloop && entry.first == writer_id;
        if (state.bcast) {
            for (const auto& prefix : state.prefixes) {
                if (!name.starts_with(prefix)) continue;
                auto& changed = state.tracking_bcast_pending[prefix][name];
                if (stamp >= changed.first) changed = {stamp, writer_id};
                pubsub_pass_pending_ = true;
            }
            continue;
        }
        auto pending = state.tracking_pending.find(name);
        if (pending != state.tracking_pending.end()) {
            pending->second.invalidated = std::max(pending->second.invalidated, stamp);
            if (suppressed) pending->second.delivered = std::max(pending->second.delivered, stamp);
        }
        auto enrolled = state.tracking_enrolled.find(name);
        if (enrolled == state.tracking_enrolled.end() || enrolled->second >= stamp) continue;
        state.tracking_enrolled.erase(enrolled);
        auto found = climon_track_keys_.find(name);
        if (found != climon_track_keys_.end()) {
            auto& owners = found->second;
            auto owner = std::find(owners.begin(), owners.end(), entry.first);
            if (owner != owners.end()) {
                owners.erase(owner);
                srv_->climon_note_tracking_item_delta(-1);
            }
            if (owners.empty()) {
                srv_->climon_note_tracking_key_delta(-1);
                climon_track_keys_.erase(found);
            }
        }
        if (!suppressed) tracking_deliver_frame(state, entry.first, key, false);
        if (pending != state.tracking_pending.end())
            pending->second.delivered = std::max(pending->second.delivered, stamp);
    }
}

// The existing cold pub/sub pass boundary runs after command retirement. One
// frame per prefix carries all keys observed in that pass. Remember suppressed
// writes too: Redis's NOLOOP decision uses the last writer of each key.
uint32_t IoLoop::tracking_bcast_flush() {
    uint32_t work = 0;
    for (auto& [id, state] : climon_conn_) {
        auto pending = std::move(state.tracking_bcast_pending);
        state.tracking_bcast_pending.clear();
        std::vector<std::string> prefixes;
        for (const auto& item : pending) prefixes.push_back(item.first);
        std::sort(prefixes.begin(), prefixes.end());
        for (const auto& prefix : prefixes) {
            std::vector<std::string> keys;
            for (const auto& [key, source] : pending.at(prefix))
                if (!state.noloop || source.second != id) keys.push_back(key);
            if (keys.empty()) continue;
            std::sort(keys.begin(), keys.end());
            SmallBuf<128> array;
            reply_array_header(array, keys.size());
            for (const auto& key : keys)
                reply_bulk(array, Slice(key.data(), static_cast<uint32_t>(key.size())));
            tracking_deliver_frame(state, id,
                Slice(array.data(), static_cast<uint32_t>(array.size())), false, true);
            ++work;
        }
    }
    return work;
}

void IoLoop::tracking_broadcast_keys(const std::vector<std::string>& keys, uint64_t writer_id, uint64_t stamp) {
    if (keys.empty()) return;
    const ClimonIoMask mask = srv_->climon_tracking_io_mask();
    if (!mask) return;
    const bool bcast_active = g_track_bcast_prefixes.load(std::memory_order_relaxed) != 0;
    std::vector<std::string> interesting;
    interesting.reserve(keys.size());
    for (const std::string& key : keys) {
        const Slice slice(key.data(), static_cast<uint32_t>(key.size()));
        if (!bcast_active && !track_filter_may_contain(FlatStore::hash_key(slice))) continue;
        // One command can fire more than one notification for the SAME key (a type change plus
        // a value change, a MULTI body touching it twice). A client must see one invalidation.
        if (std::find(interesting.begin(), interesting.end(), key) != interesting.end()) continue;
        interesting.push_back(key);
    }
    if (interesting.empty()) return;

    PubSubEvent local;
    local.kind = PubSubEventKind::TrackingInvalidate;
    local.route_mask = mask;
    local.caller_id = writer_id;
    local.items.reserve(interesting.size());
    for (const std::string& key : interesting)
        local.items.push_back(PubSubEventItem{0, false, stamp, key});
    if (mask.contains(self_->id())) tracking_handle_event(local);
    for (uint32_t io : srv_->placement().ifid_threads()) {
        if (io == self_->id()) continue;
        if (!mask.contains(io)) continue;
        PubSubEvent* event = pubsub_new_event(PubSubEventKind::TrackingInvalidate);
        event->target_io = io;
        event->origin_io = self_->id();
        event->caller_id = writer_id;
        event->route_mask = mask;
        event->items = local.items;
        pubsub_post(io, event);
    }
}

void IoLoop::tracking_broadcast_flush() {
    // Membership is monotonic for the process lifetime. Clearing here could erase
    // a remote registration that races the asynchronous flush delivery.
    const ClimonIoMask mask = srv_->climon_tracking_io_mask();
    if (!mask) return;
    PubSubEvent local;
    local.kind = PubSubEventKind::TrackingFlush;
    local.route_mask = mask;
    if (mask.contains(self_->id())) tracking_handle_event(local);
    for (uint32_t io : srv_->placement().ifid_threads()) {
        if (io == self_->id()) continue;
        if (!mask.contains(io)) continue;
        PubSubEvent* event = pubsub_new_event(PubSubEventKind::TrackingFlush);
        event->target_io = io;
        event->origin_io = self_->id();
        event->route_mask = mask;
        pubsub_post(io, event);
    }
}

void IoLoop::tracking_handle_event(PubSubEvent& event) {
    switch (event.kind) {
        case PubSubEventKind::TrackingInvalidate:
            for (const PubSubEventItem& item : event.items)
                tracking_invalidate_local(
                    Slice(item.value.data(), static_cast<uint32_t>(item.value.size())),
                    event.caller_id, item.count);
            tracking_forward_stale(event);
            break;
        case PubSubEventKind::TrackingFlush: {
            for (auto& entry : climon_conn_) {
                ClimonConn& state = entry.second;
                if (!state.tracking_on) continue;
                tracking_deliver_frame(state, entry.first, Slice(), true);
                state.tracking_enrolled.clear();
                state.tracking_bcast_pending.clear();
                for (auto& read : state.tracking_reads) read.second->canceled = true;
                state.tracking_pending.clear();
            }
            for (auto& entry : climon_track_keys_) {
                srv_->climon_note_tracking_item_delta(
                    -static_cast<int64_t>(entry.second.size()));
                srv_->climon_note_tracking_key_delta(-1);
            }
            climon_track_keys_.clear();
            tracking_forward_stale(event);
            break;
        }
        case PubSubEventKind::TrackingDeliver: {
            // A rejected delivery returns to the source's CURRENT owner. Keep
            // only process-unique IDs in transport; never retain a foreign Client.
            if (event.rebind) {
                uint32_t source_io = 0;
                if (!command_client_directory_find(event.caller_id, source_io)) break;
                if (source_io != self_->id()) {
                    PubSubEvent* forward = pubsub_new_event(PubSubEventKind::TrackingDeliver);
                    *forward = event;
                    forward->target_io = source_io;
                    pubsub_post(source_io, forward);
                    break;
                }
                ClimonConn* source = climon_conn_find(event.caller_id);
                if (source && source->tracking_on && source->redirect == event.client_id &&
                    source->tracking_generation == event.op_id)
                    tracking_redirect_broken(*source);
                break;
            }
            uint32_t live_io = 0;
            if (command_client_directory_find(event.client_id, live_io) &&
                live_io != self_->id()) {
                PubSubEvent* forward = pubsub_new_event(PubSubEventKind::TrackingDeliver);
                forward->target_io = live_io;
                forward->origin_io = self_->id();
                forward->client_id = event.client_id;
                forward->caller_id = event.caller_id;
                forward->op_id = event.op_id;
                forward->subscribe = event.subscribe;
                forward->pattern = event.pattern;
                forward->count = event.count;
                forward->channel = event.channel;
                pubsub_post(live_io, forward);
                srv_->tracking_forwarded_stale_added();
                break;
            }
            Client* target = nullptr;
            for (Client* c : self_->clients())
                if (c && c->id() == event.client_id) { target = c; break; }
            if (!target || target->dead() || target->closing()) {
                uint32_t source_io = 0;
                if (event.subscribe && event.caller_id &&
                    command_client_directory_find(event.caller_id, source_io)) {
                    PubSubEvent* rejected = pubsub_new_event(PubSubEventKind::TrackingDeliver);
                    rejected->target_io = source_io;
                    rejected->origin_io = self_->id();
                    rejected->client_id = event.client_id;
                    rejected->caller_id = event.caller_id;
                    rejected->op_id = event.op_id;
                    rejected->rebind = true;
                    pubsub_post(source_io, rejected);
                }
                break;
            }
            tracking_emit_invalidation(
                target, event.subscribe,
                Slice(event.channel.data(), static_cast<uint32_t>(event.channel.size())),
                event.count != 0, event.caller_id, event.op_id, event.pattern);
            break;
        }
        default:
            break;
    }
}

void IoLoop::tracking_forward_stale(const PubSubEvent& event) {
    if (routing_forward_.empty()) return;
    ClimonIoMask posted = event.route_mask;
    for (const auto& entry : routing_forward_) {
        if (!entry.second.tracking) continue;
        uint32_t live_io = 0;
        if (!command_client_directory_find(entry.first, live_io) || live_io == self_->id())
            continue;
        if (posted.contains(live_io)) continue;
        posted.add(live_io);
        PubSubEvent* forward = pubsub_new_event(event.kind);
        forward->target_io = live_io;
        forward->origin_io = self_->id();
        forward->caller_id = event.caller_id;
        forward->route_mask = posted;
        forward->items = event.items;
        pubsub_post(live_io, forward);
        srv_->tracking_forwarded_stale_added(
            event.kind == PubSubEventKind::TrackingFlush ? 1 : event.items.size());
    }
}

// ---- CLIENT TRACKING / CACHING / GETREDIR / TRACKINGINFO ------------------------------------

void IoLoop::tracking_reply_trackinginfo(Client* client, Op& op) {
    ClimonConn* state = climon_conn_find(client->id());
    auto sink = op.sink();
    // Redis 7.4 reports exactly three fields here; the table counters live in INFO instead.
    reply_map_header(sink, 3, op.resp3());

    reply_bulk(sink, Slice("flags", 5));
    std::vector<const char*> flags;
    if (!state || !state->tracking_on) {
        flags.push_back("off");
    } else {
        flags.push_back("on");
        if (state->bcast) flags.push_back("bcast");
        if (state->optin) flags.push_back("optin");
        if (state->optout) flags.push_back("optout");
        if (state->optin && state->caching_armed) flags.push_back("caching-yes");
        if (state->optout && state->caching_armed) flags.push_back("caching-no");
        if (state->noloop) flags.push_back("noloop");
    }
    if (state && state->broken_redirect) flags.push_back("broken_redirect");
    reply_set_header(sink, flags.size(), op.resp3());
    for (const char* flag : flags)
        reply_bulk(sink, Slice(flag, static_cast<uint32_t>(std::strlen(flag))));

    reply_bulk(sink, Slice("redirect", 8));
    // Tracking off reports -1; on reports the redirect id (0 when none was requested), and a
    // broken redirect keeps reporting the id of the connection that went away.
    if (!state || !state->tracking_on) reply_int(sink, -1);
    else reply_int(sink, static_cast<long long>(state->redirect));

    reply_bulk(sink, Slice("prefixes", 8));
    // Oracle-confirmed: `flags` is a SET in RESP3 but `prefixes` stays a plain array.
    const size_t nprefix = state ? state->prefixes.size() : 0;
    reply_array_header(sink, nprefix);
    if (state)
        for (const std::string& prefix : state->prefixes)
            reply_bulk(sink, Slice(prefix.data(), static_cast<uint32_t>(prefix.size())));
}

IoLoop::ClimonStartResult IoLoop::tracking_client_subcommand(Client* client, Op& op) {
    const Slice sub = op.arg(1);

    if (sub.eq_icase("getredir")) {
        if (op.argc() != 2) {
            climon_wrong_args(op, "getredir");
            return ClimonStartResult::Sync;
        }
        ClimonConn* state = climon_conn_find(client->id());
        reply_int(op.sink(), state && state->tracking_on
                                 ? static_cast<long long>(state->redirect) : -1);
        return ClimonStartResult::Sync;
    }

    if (sub.eq_icase("trackinginfo")) {
        if (op.argc() != 2) {
            climon_wrong_args(op, "trackinginfo");
            return ClimonStartResult::Sync;
        }
        tracking_reply_trackinginfo(client, op);
        return ClimonStartResult::Sync;
    }

    if (sub.eq_icase("caching")) {
        if (op.argc() != 3) {
            climon_wrong_args(op, "caching");
            return ClimonStartResult::Sync;
        }
        ClimonConn* state = climon_conn_find(client->id());
        // Oracle order: the tracking-state check comes FIRST, so `CLIENT CACHING maybe` on a
        // non-tracking connection reports the mode error, not a syntax error.
        if (!state || !state->tracking_on) {
            reply_err(op.sink(),
                "ERR CLIENT CACHING can be called only when the client is in tracking mode with "
                "OPTIN or OPTOUT mode enabled");
            return ClimonStartResult::Sync;
        }
        const bool yes = op.arg(2).eq_icase("yes");
        if (!yes && !op.arg(2).eq_icase("no")) {
            reply_err(op.sink(), "ERR syntax error");
            return ClimonStartResult::Sync;
        }
        if (yes && !state->optin) {
            reply_err(op.sink(),
                "ERR CLIENT CACHING YES is only valid when tracking is enabled in OPTIN mode.");
            return ClimonStartResult::Sync;
        }
        if (!yes && !state->optout) {
            reply_err(op.sink(),
                "ERR CLIENT CACHING NO is only valid when tracking is enabled in OPTOUT mode.");
            return ClimonStartResult::Sync;
        }
        state->caching_armed = true;
        reply_ok(op.sink());
        return ClimonStartResult::Sync;
    }

    if (!sub.eq_icase("tracking")) return ClimonStartResult::NotHandled;
    if (op.argc() < 3) {
        reply_err(op.sink(), "ERR wrong number of arguments for 'client|tracking' command");
        return ClimonStartResult::Sync;
    }

    bool enable = false;
    if (op.arg(2).eq_icase("on")) enable = true;
    else if (op.arg(2).eq_icase("off")) enable = false;
    else { reply_syntax(op.sink()); return ClimonStartResult::Sync; }

    bool bcast = false, optin = false, optout = false, noloop = false;
    uint64_t redirect = 0;
    std::vector<std::string> prefixes;
    for (uint32_t i = 3; i < op.argc(); i++) {
        const Slice token = op.arg(i);
        if (token.eq_icase("redirect")) {
            if (++i >= op.argc()) { reply_syntax(op.sink()); return ClimonStartResult::Sync; }
            int64_t id = 0;
            if (!climon_parse_i64(op.arg(i), id)) {
                reply_err(op.sink(), "ERR value is not an integer or out of range");
                return ClimonStartResult::Sync;
            }
            // A negative or zero id parses fine and then simply names no connection.
            uint32_t owner_io = 0;
            if (id <= 0 ||
                !command_client_directory_find(static_cast<uint64_t>(id), owner_io)) {
                reply_err(op.sink(),
                    "ERR The client ID you want redirect to does not exist");
                return ClimonStartResult::Sync;
            }
            redirect = static_cast<uint64_t>(id);
        } else if (token.eq_icase("bcast")) {
            bcast = true;
        } else if (token.eq_icase("prefix")) {
            if (++i >= op.argc()) { reply_syntax(op.sink()); return ClimonStartResult::Sync; }
            prefixes.emplace_back(op.arg(i).p, op.arg(i).n);
        } else if (token.eq_icase("optin")) {
            optin = true;
        } else if (token.eq_icase("optout")) {
            optout = true;
        } else if (token.eq_icase("noloop")) {
            noloop = true;
        } else {
            reply_syntax(op.sink());
            return ClimonStartResult::Sync;
        }
    }

    // Mode checks precede prefix validation; seed 20 pins prefix-collision precedence below.
    //   1 OPTIN+OPTOUT together        4 OPTIN/OPTOUT switch on an already-on client
    //   2 PREFIX without BCAST         5 BCAST combined with OPTIN/OPTOUT
    //   3 BCAST switch on an           6 for each supplied prefix, overlap with held prefixes,
    //     already-on client              then with later prefixes supplied by this command
    // `CLIENT TRACKING off <anything>` is accepted by redis, so every rule is enable-gated.
    ClimonConn* existing = climon_conn_find(client->id());
    const bool live = existing != nullptr && existing->tracking_on && enable;

    if (enable && optin && optout) {
        reply_err(op.sink(),
            "ERR You can't specify both OPTIN mode and OPTOUT mode");
        return ClimonStartResult::Sync;
    }
    if (enable && !prefixes.empty() && !bcast) {
        reply_err(op.sink(),
            "ERR PREFIX option requires BCAST mode to be enabled");
        return ClimonStartResult::Sync;
    }
    if (live && existing->bcast != bcast) {
        reply_err(op.sink(),
            "ERR You can't switch BCAST mode on/off before disabling tracking for this "
            "client, and then re-enabling it with a different mode.");
        return ClimonStartResult::Sync;
    }
    // Adding a mode the connection did not have is legal; CONTRADICTING the held one is not.
    if (live && ((existing->optin && optout) || (existing->optout && optin))) {
        reply_err(op.sink(),
            "ERR You can't switch OPTIN/OPTOUT mode before disabling tracking for this "
            "client, and then re-enabling it with a different mode.");
        return ClimonStartResult::Sync;
    }
    if (enable && bcast && (optin || optout)) {
        reply_err(op.sink(),
            "ERR OPTIN and OPTOUT are not compatible with BCAST");
        return ClimonStartResult::Sync;
    }
    // Validation is ordered by the supplied prefix, not by collision category: with held "a"
    // and supplied "b", "", Redis reports the supplied b/empty collision before empty/held a.
    for (size_t a = 0; enable && a < prefixes.size(); a++) {
        if (live)
            for (const std::string& held : existing->prefixes)
                if (track_prefix_overlaps(prefixes[a], held)) {
                    std::string error = "ERR Prefix '";
                    error += prefixes[a];
                    error += "' overlaps with an existing prefix '";
                    error += held;
                    error += "'. Prefixes for a single client must not overlap.";
                    reply_err(op.sink(), error.c_str());
                    return ClimonStartResult::Sync;
                }
        for (size_t b = a + 1; b < prefixes.size(); b++)
            if (track_prefix_overlaps(prefixes[a], prefixes[b])) {
                // Oracle wording: the FIRST-listed prefix is named first.
                std::string error = "ERR Prefix '";
                error += prefixes[a];
                error += "' overlaps with another provided prefix '";
                error += prefixes[b];
                error += "'. Prefixes for a single client must not overlap.";
                reply_err(op.sink(), error.c_str());
                return ClimonStartResult::Sync;
            }
    }

    if (!enable) {
        if (existing) {
            tracking_forget_client(client->id(), *existing);
            existing->broken_redirect = false;
            climon_conn_release(client->id());
            climon_refresh_armed();
        }
        reply_ok(op.sink());
        return ClimonStartResult::Sync;
    }

    ClimonConn& state = climon_conn_get(client);
    if (!state.tracking_on) {
        state.tracking_on = true;
        if (!state.tracking_draining) {
            climon_local_trackers_++;
            srv_->climon_set_tracking_io(self_->id(), true);
            srv_->climon_tracking_added();
        }
        state.tracking_draining = false;
    }
    // Redis REPLACES the per-call modifiers rather than accumulating them: a plain
    // `CLIENT TRACKING on` after `on OPTIN`/`on NOLOOP` clears optin/noloop (differ-pinned).
    // Only an explicit contradiction (OPTIN while OPTOUT is held) is refused, above.
    state.bcast = bcast;
    // Seed 23: omitting PREFIX adds the implicit empty prefix even to an existing explicit
    // prefix set. It bypasses the supplied-prefix collision checks above, is registered once,
    // and sorts first for TRACKINGINFO and later overlap errors. Repeated ON BCAST must not
    // duplicate either the subscription or its allocation/accounting.
    if (bcast && prefixes.empty() &&
        std::find(state.prefixes.begin(), state.prefixes.end(), std::string{}) == state.prefixes.end())
        prefixes.emplace_back();
    state.optin = optin;
    state.optout = optout;
    state.noloop = noloop;
    state.redirect = redirect;
    state.tracking_generation = tracking_clock_commit();
    state.broken_redirect = false;
    for (std::string& prefix : prefixes) {
        tracking_note_prefix_registered(prefix, true);
        state.prefixes.push_back(std::move(prefix));
    }
    std::sort(state.prefixes.begin(), state.prefixes.end());   // redis reports them sorted
    command_client_set_tracking_view(client, true, static_cast<int64_t>(redirect));
    climon_refresh_armed();
    reply_ok(op.sink());
    return ClimonStartResult::Sync;
}

}  // namespace tomo
