// CLIENT tracking integration with transaction execution and notification retirement.
// The connection IO owns receipt maps and the stack visitor contexts below; executor
// handlers borrow the selected receipt until completion. Keep receipt-table instantiations out
// of xshard.cc so transaction changes cannot replace ordinary-path COMDATs.
#include "../core/io_loop.h"
#include "acl.h"
#include "multi.h"
#include "notify_batch.h"

namespace tomo {

void tracking_execute_read(Shard& shard, Op& op) {
    // WATCH selects handler_notify even for a read. The tracking receipt uses
    // that slot as its tag, so forward to the original observed handler.
    const auto& read = *static_cast<const IoLoop::TrackingRead*>(op.spec);
    read.original->handler_notify(shard, op);
}

IoLoop::ClimonStartResult IoLoop::tracking_ack_enable(Client* client, Op& op) {
    // Owners may still be draining a pass whose notification mask predates ON.
    // For the current dispatch slot, defer acknowledgement until the owners'
    // config refresh applies this publication. The TrackingOn timer uses the
    // conditional deferred-timer service shared with WAIT; handlers and owner
    // passes with an unchanged config version do not poll tracking readiness.
    const uint64_t version = srv_->live_config_snapshot(self_->id()).version;
    if (clientcompat_post() && !srv_->tracking_config_ready(version) &&
        &op == &client->rob().at(client->rob().dispatch_id())) {
        try {
            deferred_timers_.push_back(DeferredTimer{client,
                                                     client->rob().dispatch_id(),
                                                     version,
                                                     0,
                                                     {},
                                                     DeferredTimerKind::TrackingOn});
        } catch (const std::bad_alloc&) {
            reply_err(op.sink(), "ERR out of memory");
            return ClimonStartResult::Sync;
        }
        client->rob().publish();
        barrier_arm(client, BarrierOwner::PubSub);
        mark_active(client);
        // An idle owner otherwise applies the publication only after its
        // periodic park timeout. Wake each physical owner once through the
        // ring doorbell; periodic refresh remains the backstop across role changes.
        std::array<bool, kMaxThreads> notified{};
        for (uint32_t sid = 0; sid < srv_->nshards(); ++sid) {
            const uint32_t owner = srv_->worker_of_shard(sid);
            if (owner == self_->id() || notified[owner]) continue;
            notified[owner] = true;
            if (Ring* target = srv_->thread(owner).ring())
                if (ring_.msg_to(*target, ur_tag(UrKind::Wake, nullptr))) self_->sig().wakes_sent++;
        }
        return ClimonStartResult::Async;
    }
    reply_ok(op.sink());
    return ClimonStartResult::Sync;
}

void IoLoop::tracking_prepare_multi(Client& client, MultiExecState& state) {
    if (!clientcompat_post()) return;
    auto* tracking = climon_conn_find(client.id());
    if (!tracking || !tracking->tracking_on) return;
    const auto view = multi_tracking_view(state);
    if (!view.execute) return;
    // Borrowed IO-local state for multi_tracking_children's synchronous visitor.
    // The visitor does not retain this stack context; snapshot/caching are values.
    struct Context {
        IoLoop* loop;
        Client* client;
        ClimonConn* tracking;
        uint64_t snapshot;
        bool caching;
    } context{this, &client, tracking, view.snapshot, tracking->caching_armed};
    const bool saved = tracking->caching_armed;
    multi_tracking_children(state, &context,
                            [](void* raw, Op& child, bool prebuilt, bool, bool, bool&, uint32_t) {
                                auto& c = *static_cast<Context*>(raw);
                                if (prebuilt) return;
                                if (child.cmd_name().eq_icase("client") && child.argc() == 3 &&
                                    child.arg(1).eq_icase("caching")) {
                                    if ((c.tracking->optin && child.arg(2).eq_icase("yes")) ||
                                        (c.tracking->optout && child.arg(2).eq_icase("no")))
                                        c.caching = true;
                                }
                                c.tracking->caching_armed = c.caching;
                                c.loop->tracking_register_read(c.client, *c.tracking, child);
                                auto receipt = c.tracking->tracking_reads.find(&child);
                                if (receipt != c.tracking->tracking_reads.end()) {
                                    receipt->second->flags |= CmdFlags::NotifySelected;
                                    if (c.snapshot != UINT64_MAX) child.set_read_cut(c.snapshot);
                                }
                            });
    tracking->caching_armed = saved;
}

void IoLoop::tracking_finish_multi(Client& client, MultiExecState& state, NotifyBatch* batch) {
    if (!clientcompat_post()) return;
    // Borrowed connection, loop and optional batch for the synchronous child visitor.
    // The calling IO retains them for the visit; this context publishes no pointers.
    struct Context {
        IoLoop* loop;
        Client* client;
        NotifyBatch* batch;
        bool committed;
    };
    const auto view = multi_tracking_view(state);
    Context context{this, &client, batch, view.committed};
    multi_tracking_children(
        state, &context,
        [](void* raw, Op& child, bool, bool io_local, bool acl, bool& effect_done, uint32_t order) {
            auto& c = *static_cast<Context*>(raw);
            if (c.committed) notify_tracking_multi_writes(*c.loop, c.batch, c.client->id(), order);
            if (c.committed && io_local && !effect_done && child.cmd_name().eq_icase("client") &&
                c.loop->tracking_client_subcommand(c.client, child) == ClimonStartResult::Sync)
                effect_done = true;
            if (c.committed && io_local && acl && !effect_done) {
                acl_command_entry(*c.loop, *c.client, child);
                effect_done = true;
            }
            c.loop->tracking_retire_exec_read(*c.client, child, c.batch, order, c.committed);
        });
    if (view.committed)
        if (auto* tracking = climon_conn_find(client.id())) tracking->caching_armed = false;
}

void IoLoop::tracking_retire_exec_read(Client& client, Op& op, NotifyBatch* batch, uint32_t order,
                                       bool committed) {
    auto* state = climon_conn_find(client.id());
    if (!state) return;
    auto found = state->tracking_reads.find(&op);
    if (found == state->tracking_reads.end()) return;
    TrackingRead& read = *found->second;
    if (!committed && !read.canceled) {
        // An internal EXEC retry abandons only this attempt's memberships.
        // OFF/RESET instead clear the entire table and mark receipts canceled.
        for (const auto& key : read.keys) {
            auto pending = state->tracking_pending.find(key);
            if (pending == state->tracking_pending.end()) std::abort();
            auto& members = pending->second.reads;
            auto member = std::find(members.begin(), members.end(), &op);
            if (member == members.end()) std::abort();
            members.erase(member);
            if (members.empty()) state->tracking_pending.erase(pending);
        }
    }
    read.canceled |= !committed;
    if (committed) {
        std::vector<uint64_t> observed;
        observed.reserve(read.keys.size());
        for (size_t i = 0; i < read.keys.size(); ++i) {
            const auto& key = read.keys[i];
            const uint64_t own = notify_tracking_read_stamp(
                batch, Slice(key.data(), static_cast<uint32_t>(key.size())), order);
            observed.push_back(own ? own : read.observed[read.shards[i]]);
        }
        read.observed.swap(observed);
        read.woken.clear();  // per-key stamps above; EXEC children never park
        for (size_t i = 0; i < read.keys.size(); ++i) read.shards[i] = i;
    }
    // The transaction still uses the child's registry spec while assembling
    // replies and recording timing; its tracking receipt ends here.
    op.spec = read.original;
    tracking_retire_read(client, op);
}

// Reserve ordered keyspace/keyevent publications before an EXEC subscription change.
// multi_exec_io_commands calls on the connection IO after owner completion; batch is
// borrowed from its acquire-loaded transaction pointer. Consume selected route bits,
// retaining tracking records/certificates for ordinary EXEC retirement. A null batch
// or no selected records yields no chain. Allocation failure or notification-budget
// exhaustion consumes those routes and counts drops without waiting. The returned
// shared_ptr owns a reservation accounted by Server's relaxed CAS/fetch_sub; it
// does not itself publish the chain to recipients.
[[gnu::noinline]] std::shared_ptr<PubSubNotificationChain> notify_multi_before(Server& server,
                                                                               NotifyBatch* batch,
                                                                               uint32_t order) {
    if (!batch) return {};
    constexpr uint32_t routes = NOTIFY_KEYSPACE | NOTIFY_KEYEVENT;
    const auto selected = [order](const NotifyRecordImpl& record) {
        return record.order < order && (record.routes & routes);
    };
    std::shared_ptr<PubSubNotificationChain> chain;
    try {
        std::vector<NotifyRecordImpl*> records;
        for (uint32_t i = 0; i < batch->inline_size; ++i)
            if (selected(batch->inline_records[i])) records.push_back(&batch->inline_records[i]);
        for (auto& record : batch->spill)
            if (selected(record)) records.push_back(&record);
        if (records.empty()) return {};
        std::stable_sort(records.begin(), records.end(), [](const auto* lhs, const auto* rhs) {
            return lhs->order < rhs->order ||
                   (lhs->order == rhs->order && lhs->sequence < rhs->sequence);
        });
        auto building = std::make_unique<PubSubNotificationChain>();
        building->items.reserve(records.size() * 2);
        for (const auto* record : records) {
            for (uint8_t route = 0; route < 2; ++route) {
                std::string channel, message;
                if (!notify_make_publication(record->db, record->routes, route, record->event,
                                             record->key, channel, message))
                    continue;
                building->items.push_back(
                    PubSubNotificationItem{std::move(channel), std::move(message)});
            }
        }
        chain = notify_reserve_chain(server, std::move(building), batch->expiry_completion);
    } catch (const std::bad_alloc&) {
        // Match normal notification retirement's bounded best-effort policy.
    }
    uint32_t count = 0;
    const auto consume = [&](NotifyRecordImpl& record) {
        if (!selected(record)) return;
        record.routes &= ~routes;
        ++count;
    };
    for (uint32_t i = 0; i < batch->inline_size; ++i) consume(batch->inline_records[i]);
    for (auto& record : batch->spill) consume(record);
    if (!chain) server.notify_event_dropped(count);
    return chain;
}

}  // namespace tomo
