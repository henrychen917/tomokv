// Final connection ownership, after every physical worker (including former IO
// owners) has joined. This file is never entered by a request or a role change.
#include "io_loop.h"

namespace tomo {

void IoLoop::shutdown_on_issuer() {
    if (!initialized_) return;
    // SINGLE_ISSUER applies to synchronous cancellation too. This guard runs on
    // the physical issuer, after its snapshot/AOF lifetime guards have drained;
    // it is never run on an IO-to-executor role change.
    if (!epoll_ && !ring_.shutdown_complete()) {
        (void)ring_.submit_and_reap();
        io_uring_sync_cancel_reg cancel{};
        cancel.flags = IORING_ASYNC_CANCEL_ANY | IORING_ASYNC_CANCEL_ALL;
        cancel.timeout.tv_sec = 5;
        int rc;
        do { rc = io_uring_register_sync_cancel(ring_.raw(), &cancel); } while (rc == -EINTR);
        if (rc < 0 && rc != -ENOENT) {
            std::fprintf(stderr, "shutdown: ring cancellation failed: %s\n", std::strerror(-rc));
            std::abort(); // Never free a buffer without its kernel lifetime fence.
        }
        (void)ring_.submit_and_reap();
    }
}

void IoLoop::shutdown_release_abandoned_script_pins(Server& srv) {
    for (uint32_t sid = 0; sid < srv.nshards(); ++sid)
        srv.shard(static_cast<int32_t>(sid)).store().atomic_release_abandoned_script_pins();
}

void IoLoop::shutdown_clients_after_join() {
    // Serverless fixtures may borrow stack Clients. Only init() creates an owning
    // IO lifetime; partial initialization cannot have admitted a connection.
    if (!initialized_) return;

    // Normal WB callbacks post releases, tracking and notifications to live
    // owners. All owners have joined: complete only the already-issued reply
    // here, return borrows directly, and discard undeliverable notifications.
    // Rebinding preserves WB accounting and its existing staged output. The
    // transaction arm sees only multi_shutdown_retirable() states (see below).
    // Static: wb_ keeps this pointer after the destructor's last use.
    static const std::atomic<bool> no_limits{false};
    auto release_joined = [](void* context, int32_t shard, const char* ptr) {
        auto* loop = static_cast<IoLoop*>(context);
        loop->srv_->shard(shard).store().unborrow(ptr);
    };
    wb_.bind(&ring_, this, release_joined, this,
        [](void* context, Client& client, Op& op) {
            auto* loop = static_cast<IoLoop*>(context);
            NotifyBatch* notifications = nullptr;
            if (op.has_scatter_state()) {
                notifications = notify_take_batch(op);
                xshard_retire(*loop->srv_, *loop->self_, loop->ring_, client, op,
                    loop->scatter_pool_, loop->self_->id(), loop,
                    [](void* ctx, int32_t shard, const char* ptr) {
                        static_cast<IoLoop*>(ctx)->srv_->shard(shard).store().unborrow(ptr);
                    }, [](void* ctx) { static_cast<IoLoop*>(ctx)->wb_.note_zc_suppressed_tls(); });
            } else if (op.has_blocking_state()) {
                notifications = notify_take_batch(op);
                blocking_retire(*loop->srv_, client, op, *loop->self_);
            } else if (op.has_multi_state()) {
                notifications = notify_take_batch(op);
                multi_retire_entry(*loop, client, op);
            } else if (op.has_notify_state()) {
                notifications = notify_take_batch(op);
            }
            notify_discard_batch(notifications);
        }, &no_limits, nullptr, [](void*, Client&) { return false; },
        &cached_now_s_, &self_->sig());

    // The issuer has cancelled network requests after draining persistence. Its
    // CQEs remain available here; successful accepts own fds without Clients.
    if (!ring_.shutdown_complete()) {
        ring_.for_each_cqe([&](io_uring_cqe* cqe) {
            const UrKind kind = ur_kind(cqe->user_data);
            if (kind == UrKind::Accept || kind == UrKind::TlsAccept ||
                kind == UrKind::UnixAccept || kind == static_cast<UrKind>(18)) {
                if (cqe->res >= 0) ::close(cqe->res);
            } else if (kind == UrKind::Send) {
                (void)wb_.on_send_complete<false>(*ur_ptr<Client>(cqe->user_data), cqe->res);
            } else if (kind == UrKind::TlsSend) {
                Client* c = ur_ptr<Client>(cqe->user_data);
                if (TlsConn* tls = tls_engine(c))
                    (void)wb_.on_tls_send_complete<false>(*c, *tls, cqe->res);
            }
        });
    }

    std::vector<Client*> clients;
    auto keep = [&](Client* c) { if (c) clients.push_back(c); };
    for (Client* c : self_->clients()) keep(c);
    for (Client* c : active_.v) keep(c);
    for (Client* c : dead_ready_) keep(c);
    for (Client* c : dead_next_) keep(c);
    for (Client* c : pending_serve_) keep(c);
    for (Client* c : pending_handoffs_) keep(c);
    // Closing clients leave clients() before their final recv/send CQE. The WB
    // slot and active set continue owning them until close_client reaches Dead.
    for (uint32_t i = 0; i < self_->wb_slot_words() * 64; ++i)
        keep(self_->wb_slot_client(i));
    self_->drain_clients_unmasked(keep);
    self_->drain_client_transfers_unmasked([&](const ClientTransfer& transfer) {
        keep(transfer.client);
        command_client_migration_discard(transfer.catalog);
        client_routing_discard(transfer.routing);
    });
    for (auto& migration : client_migrations_) {
        keep(migration.client);
        if (migration.source_backup_fd >= 0) ::close(migration.source_backup_fd);
        command_client_migration_discard(migration.catalog);
        client_routing_discard(migration.routing);
    }
    std::sort(clients.begin(), clients.end(), std::less<Client*>{});
    clients.erase(std::unique(clients.begin(), clients.end()), clients.end());

    // A completion already owed may have reached Done during the last IO pass.
    // Retire that prefix and perform the existing nonblocking send path once;
    // never parse more requests, run commands, wait on peers, or restart a save.
    // An EXEC retires by running its queued connection-local commands on this
    // IO owner, so one that still has them is not an owed reply: end the
    // ordered prefix before it (no later reply may overtake it) and discard it
    // after the ring fence below.
    std::vector<Op*> withheld;
    for (Client* c : clients) {
        c->set_recv_armed(false);
        c->set_send_inflight(false);
        if (!c->dead()) {
            for (uint64_t id = c->rob().flush_id(); id != c->rob().dispatch_id(); ++id) {
                Op& op = c->rob().at(id);
                if (op.state.load(std::memory_order_acquire) != OpState::Done) break;
                if (op.has_multi_state() && !multi_shutdown_retirable(*srv_, wb_, *c, op)) {
                    op.state.store(OpState::Issued, std::memory_order_relaxed); // drain stops
                    withheld.push_back(&op);
                    break;
                }
            }
            bool submit = true;
            if (TlsConn* tls = tls_engine(c)) {
                wb_.prepare_tls<true>(*c, *tls, submit);
                if (submit) wb_.pump_tls<true>(*c, *tls);
            } else {
                wb_.prepare<true>(*c, submit);
                if (submit) wb_.pump<true>(*c);
            }
        }
    }
    for (Op* op : withheld) op->state.store(OpState::Done, std::memory_order_relaxed);
    // No callbacks below may submit work. Queue exit is the final fence for raw
    // Client/buffer pointers, independent of whether their original CQE arrived.
    ring_.shutdown();
    auto release = [&](int32_t shard, const char* ptr) {
        srv_->shard(shard).store().unborrow(ptr);
    };
    for (Client* c : clients) {
        c->set_serve_pending(false);
        c->release_all_segments(release);
        if (!c->dead()) {
            for (uint64_t id = c->rob().flush_id(); id != c->rob().dispatch_id(); ++id) {
                Op& op = c->rob().at(id);
                if (op.has_blocking_state()) blocking_retire(*srv_, *c, op, *self_);
                else if (op.has_multi_state()) {
                    // A withheld EXEC, or a Done one behind an unfinished older op
                    // (EXEC's barrier admits nothing after it). An unfinished
                    // transaction keeps its existing shutdown ownership.
                    if (op.state.load(std::memory_order_acquire) == OpState::Done)
                        multi_shutdown_discard(*srv_, wb_, *c, op, scatter_pool_, self_->id(),
                                               multi_deferred_);
                } else if (op.has_scatter_state()) {
                    auto* state = op.scatter_state();
                    op.detach_scatter_state();
                    xshard_destroy(state, scatter_pool_, self_->id());
                } else if (op.has_notify_state()) notify_discard_batch(notify_take_batch(op));
                else if (op.zc_ptr && op.zc_shard >= 0) release(op.zc_shard, op.zc_ptr);
            }
            command_client_disconnected(c);
            ::close(c->fd());
            srv_->client_released();
        }
        release_tls(c);
        latency_tracking_forget_client(*c);
        delete c;
    }
    // No producer remains. Dropping these references is a real join fence, not
    // a relaxation of the normal reaper's serve_pending/recv/send conditions.
    self_->clients().clear();
    active_.v.clear();
    dead_ready_.clear();
    dead_next_.clear();
    pending_serve_.clear();
    pending_handoffs_.clear();
    client_migrations_.clear();
    while (!pending_releases_.empty()) {
        auto r = pending_releases_.front(); pending_releases_.pop_front();
        release(r.shard, r.ptr);
    }
    // TLS MULTI retirement and pre-join send completions can already have
    // published releases. Drain every inbox here, including owners whose IO
    // destructor ran earlier; no worker remains to consume these channels.
    for (uint32_t tid = 0; tid < srv_->nthreads(); ++tid)
        srv_->thread(tid).drain_releases_unmasked(
            [&](const BorrowRelease& r) { release(r.shard, r.ptr); });
    // A completed transaction can contain connection-local publication work.
    // Its finalization must not leave newly allocated delivery events behind
    // an owner whose destructor has already drained its inbox.
    pubsub_shutdown_events();
    for (uint32_t tid = 0; tid < srv_->nthreads(); ++tid) {
        std::deque<PubSubEvent*> events;
        srv_->thread(tid).take_pubsub_events(events);
        for (PubSubEvent* event : events) pubsub_delete_event(event);
    }
    initialized_ = false;
}
} // namespace tomo
