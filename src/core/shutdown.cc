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

void IoLoop::shutdown_clients_after_join() {
    // Serverless fixtures may borrow stack Clients. Only init() creates an owning
    // IO lifetime; partial initialization cannot have admitted a connection.
    if (!initialized_) return;

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
    for (Client* c : clients) {
        c->set_recv_armed(false);
        c->set_send_inflight(false);
        if (!c->dead()) {
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
                else if (op.has_scatter_state()) {
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
    self_->drain_releases_unmasked([&](const BorrowRelease& r) { release(r.shard, r.ptr); });
    initialized_ = false;
}
} // namespace tomo
