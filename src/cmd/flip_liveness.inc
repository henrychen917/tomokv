// FLIP connection liveness, output holds and deferred borrow releases. Included by multi.inc
// in cmd/xshard.cc after MultiSession and flip_session.inc, with BlockingState already defined.
// IO owners maintain client holds; blocking continuations consult the FLIP acknowledgement
// before
// publishing owner work. A surviving IO may retain blocked/TLS/non-draining clients, but a
// converting IO must refuse them. Borrow releases resume after final executor masks are
// installed.

// Offline behaviour-twin patch point in both namespaces. A copied ELF can select the comparison
// behavior by changing this immediate while retaining the candidate text layout; no runtime
// configuration selects it.
__attribute__((noinline, noipa)) int flip_liveness_enabled() {
    int enabled;
    asm volatile("mov $1, %0" : "=a"(enabled));
    return enabled;
}

bool Client::flip_execution_idle() const {
    return rob_.quiesced() && !retire_queued_.load(std::memory_order_acquire) &&
           barrier_owners_ == 0 && atomic_groups_io_ == 0 && !blocked() && !segments_.has_borrow();
}

bool Client::flip_held_output_idle() const {
    if (multi_session_ && multi_session_->pending) return false;
    const size_t aliases = multi_session_ ? multi_session_->watched.size() : 0;
    return watched_refs_.load(std::memory_order_acquire) == aliases && !send_inflight_ &&
           flip_execution_idle();
}

bool IoLoop::flip_post_drain() const {
    return flip_liveness_enabled() && srv_->flip_stage() == FlipStage::ClientInstall;
}

bool IoLoop::flip_output_held(const Client* client) const {
    return std::binary_search(flip_held_output_.begin(), flip_held_output_.end(), client,
                              std::less<const Client*>{});
}

// Contract: The source IO calls after IoDrain readiness and before acknowledging that drain.
// Reserve local vectors before setting serve_pending pins. Movable clients must have no send or
// serve outstanding; stationary clients retain their source, and borrowed output arms deferred
// releases. Allocation refusal reports FLIP failure without partially pinning clients. The
// caller's stage ACK publishes completion of this preparation.
bool IoLoop::flip_output_hold() {
    if (!flip_liveness_enabled()) return true;
    // IoDrain proved each possible mover has no socket send or serve outstanding.
    // Reserve before pinning; a failed allocation cannot leave a partially held IO.
    if (!flip_held_output_.empty()) std::abort();
    flip_stay_epoch_ = srv_->flip_epoch();
    flip_stayers_.clear();
    try {
        flip_held_output_.reserve(self_->clients().size());
        flip_stayers_.reserve(self_->clients().size());
    } catch (const std::bad_alloc&) {
        srv_->flip_note_failure("ERR FLIP could not reserve socket-output holds");
        return false;
    }
    for (Client* client : self_->clients()) {
        if (client->closing()) continue;
        auto kind = flip_immovable_kind(client);
        // POLLOUT can change when the peer reads, even within this control pass.
        // The IO-owned send/output state cannot: IoDrain accepted any remaining
        // bytes or kernel pointer only on a surviving source. Preserve that
        // stationary decision rather than pinning a newly writable socket.
        if (!kind && (client->send_inflight() || !client->nothing_to_write())) kind = 3;
        if (kind) {
            flip_stayers_.push_back(client);
            srv_->flip_skipped_class_[kind - 1].fetch_add(1, std::memory_order_relaxed);
            continue;
        }
        if (client == flip_client_) continue;
        if (client->send_inflight() || client->serve_pending()) std::abort();
        client->set_serve_pending(true);
        flip_held_output_.push_back(client);
    }
    std::sort(flip_held_output_.begin(), flip_held_output_.end(), std::less<Client*>{});
    std::sort(flip_stayers_.begin(), flip_stayers_.end(), std::less<Client*>{});
    for (const Client* client : flip_stayers_)
        if (client->flip_borrowed_output()) {
            flip_borrow_hold();
            break;
        }
    return true;
}

bool IoLoop::flip_output_plan() {
    if (!flip_liveness_enabled()) return true;
    std::vector<Client*> moving;
    try {
        const uint32_t planned = srv_->flip_source_clients(self_->id());
        moving.reserve(planned);
        for (uint32_t i = 0; i < planned; ++i)
            moving.push_back(srv_->flip_client_at(self_->id(), i));
        std::sort(moving.begin(), moving.end(), std::less<Client*>{});
    } catch (const std::bad_alloc&) {
        return false;
    }
    size_t keep = 0;
    for (Client* client : flip_held_output_) {
        if (std::binary_search(moving.begin(), moving.end(), client, std::less<Client*>{})) {
            flip_held_output_[keep++] = client;
        } else {
            client->set_serve_pending(false);
            enqueue_serve(client);
        }
    }
    flip_held_output_.resize(keep);
    return true;
}

void IoLoop::flip_output_release() {
    flip_borrow_release();
    for (Client* client : flip_held_output_) {
        // A pinned close dropped from the plan still belongs to this source.
        client->set_serve_pending(false);
        enqueue_serve(client);
    }
    flip_held_output_.clear();
}

void IoLoop::flip_output_adopt(Client* client) {
    if (!client->serve_pending()) return;  // LB does not supply a held serve.
    if (!flip_liveness_enabled() || srv_->flip_stage() < FlipStage::ClientCommit) std::abort();
    // A newly activated IO has not run its FLIP-gated cron yet. Its zero clock
    // would underflow the inherited output soft-limit timestamp on first serve.
    cached_now_ms_ = now_ns() / 1000000ull;
    cached_now_s_ = static_cast<uint32_t>(cached_now_ms_ / 1000);
    if (!client->nothing_to_write())
        srv_->flip_output_transferred_.fetch_add(1, std::memory_order_relaxed);
    // Source has published ownership and the destination catalog/WB slot is
    // installed. Only this IO may now send the same buffers/segment frontier.
    client->set_serve_pending(false);
    enqueue_serve(client);
}

void IoLoop::flip_output_detach(Client* client) {
    if (!flip_liveness_enabled()) return;
    // Late fan-out can mark a prepared connection active again after reversible
    // detach. No source-side active pointer may survive the ownership store.
    if (client->in_active()) {
        client->set_in_active(false);
        active_.erase(client);
    }
}

void IoLoop::flip_output_observe() {
    if (!flip_liveness_enabled()) return;
    for (const Client* client : self_->clients())
        if (!client->nothing_to_write() || client->send_inflight())
            srv_->flip_late_output_.fetch_add(1, std::memory_order_relaxed);
}

void IoLoop::flip_output_prepare() {
    // The parser can still retire local syntax errors and FLIP observations
    // behind the dispatch pause. Stage their replies without pumping.
    for (Client* client : flip_held_output_) {
        bool submit_allowed = true;
        if (climon_reply_suppressed(client))
            (void)climon_prepare_suppressed(client, submit_allowed);
        else if (epoll_)
            (void)wb_.prepare<true, true>(*client, submit_allowed);
        else
            (void)wb_.prepare<false, true>(*client, submit_allowed);
    }
}

void IoLoop::flip_output_unhold(Client* client) {
    auto at = std::lower_bound(flip_held_output_.begin(), flip_held_output_.end(), client,
                               std::less<Client*>{});
    if (at == flip_held_output_.end() || *at != client) return;
    flip_held_output_.erase(at);
    client->set_serve_pending(false);
    enqueue_serve(client);
}

bool Client::flip_borrowed_output() const { return segments_.has_borrow(); }

bool Client::flip_stationary_idle() const {
    if (!blocked())
        return rob_.quiesced() && !retire_queued_.load(std::memory_order_acquire) &&
               barrier_owners_ == 0 && atomic_groups_io_ == 0;
    if (retire_queued_.load(std::memory_order_acquire) || atomic_groups_io_ ||
        rob_.in_flight() != 1)
        return false;
    const Op& op = rob_.at(rob_.flush_id());
    // The blocking/WAIT dispatcher publishes its ROB range with the reset Free
    // marker; it does not use ordinary owner dispatch's Issued marker.
    const auto status = op.state.load(std::memory_order_acquire);
    if (status != OpState::Free && status != OpState::Issued) return false;
    if (barrier_owners_ == static_cast<uint8_t>(BarrierOwner::Wait)) return true;
    if (barrier_owners_ != static_cast<uint8_t>(BarrierOwner::Blocking)) return false;
    const BlockingState* state = op.blocking_state();
    if (!state) return false;
    const auto phase = state->phase.load(std::memory_order_acquire);
    // A parked registry moves with its Shard. A wake-up may hand a continuation
    // back after this IO acknowledged; that IO-owned continuation remains here
    // and cannot publish until Idle (flip_blocked_dispatch_allowed).
    return (phase == BlockingPhase::Parked || phase == BlockingPhase::MoveRequested) &&
           state->active_tasks.load(std::memory_order_acquire) == 0;
}

uint8_t IoLoop::flip_immovable_kind(const Client* client) const {
    if (client->closing()) return 0;
    if (client->blocked()) return 1;
    if (client->is_tls()) return 2;
    if (flip_output_held(client)) return 0;  // late owned output travels under its send hold
    if (client->send_inflight() || !client->nothing_to_write()) {
        pollfd socket{client->fd(), POLLOUT, 0};
        // A ready socket may complete its existing send during normal drain.
        // A full socket has no local progress condition: never wait for its peer.
        if (::poll(&socket, 1, 0) == 0) return 3;
    }
    return 0;
}

void Server::flip_note_immovable_refusal(unsigned kind, const char* reason) {
    std::lock_guard<std::mutex> lock(flip_error_mu_);
    const auto stage = flip_stage();
    if (stage < FlipStage::IoDrain || stage >= FlipStage::ClientCommit) return;
    bool expected = false;
    if (!flip_failed_.compare_exchange_strong(expected, true, std::memory_order_acq_rel)) return;
    flip_error_ = reason;
    flip_refused_class_[kind - 1].fetch_add(1, std::memory_order_relaxed);
}

bool IoLoop::flip_immovable_refused() {
    if (!flip_liveness_enabled()) return false;
    const bool converting = srv_->flip_candidate_target(self_->id()) == Role::Ex;
    for (const Client* client : self_->clients()) {
        // FIN may leave complete input behind a synchronous control or the
        // dispatch pause. Its EOF timer cannot drain until admission resumes.
        // Decide before commit instead of waiting on our own FLIP barrier.
        // An idle, fully consumed EOF closes during the drain instead.
        if (receive_eof_blocks_flip(client)) {
            srv_->flip_note_failure("ERR FLIP refused: a connection is draining its end of stream");
            return true;
        }
        const uint8_t kind = flip_immovable_kind(client);
        if (!kind) continue;
        if (!converting) continue;
        const char* error = kind == 1 ? "ERR FLIP refused: converting IO owns a blocked connection"
                            : kind == 2
                                ? "ERR FLIP refused: converting IO owns a TLS connection"
                                : "ERR FLIP refused: converting IO owns non-draining output";
        srv_->flip_note_immovable_refusal(kind, error);
        return true;
    }
    return false;
}

// Contract: The IO FLIP drain supplies its client and whether it is the coordinator client.
// Check WB migration state for possible movers; deliberately omit that check for stationary,
// post-install and coordinator paths because their deferred frames keep the installed IO.
// The coordinator keeps one FLIP op; other paths use stationary, execution or full drain
// predicates.
// False postpones acknowledgement without relaxing ROB, borrow or send lifetime requirements.
bool IoLoop::flip_client_drained(const Client* client, bool coordinator) const {
    const bool enabled = flip_liveness_enabled();
    const bool post = enabled && srv_->flip_stage() == FlipStage::ClientInstall;
    const bool stays = enabled && (flip_client_stays(client) ||
                                   (srv_->flip_stage() == FlipStage::IoDrain &&
                                    srv_->flip_candidate_target(self_->id()) != Role::Ex &&
                                    flip_immovable_kind(client)));
    // Deferred WB frames own their bytes and stay with this IO. In particular,
    // an invalidation behind the coordinator's unfinished FLIP cannot flush
    // until FLIP finishes. Only a possible transfer must empty that WB map;
    // ClientInstall is past every transfer and keeps the installed IO owner.
    if (!(enabled && (post || stays || coordinator)) && !wb_.migration_ready(*client)) return false;
    if (coordinator)
        return client->rob().in_flight() == 1 &&
               (stays || (post ? !client->flip_borrowed_output()
                               : !client->send_inflight() && !client->serve_pending() &&
                                     client->nothing_to_write()));
    if (stays) return client->flip_stationary_idle();
    return post ? client->flip_execution_idle() : client->flip_drain_idle();
}

bool IoLoop::flip_timers_drained() const {
    if (deferred_timers_.empty()) return true;
    if (!flip_liveness_enabled() || srv_->flip_candidate_target(self_->id()) == Role::Ex)
        return false;
    for (const auto& timer : deferred_timers_) {
        // A FIN can also arrive after commit on a retained IO. Once all owner
        // work has retired, its timer and buffered input stay with that Client
        // and resume at Idle. Neither is an outstanding executor obligation.
        if (flip_post_drain() &&
            (timer.kind == DeferredTimerKind::ReceiveFin ||
             timer.kind == DeferredTimerKind::ReceiveEof) &&
            timer.client->ifid_thread() == self_->id() && timer.client->flip_execution_idle())
            continue;
        if (timer.kind != DeferredTimerKind::WaitZero || !timer.client->flip_stationary_idle())
            return false;
    }
    return true;
}

void IoLoop::flip_skip_stayers() {
    if (!flip_liveness_enabled()) {
        flip_skipped_local_ = 0;
        return;
    }
    if (flip_skip_epoch_ == srv_->flip_epoch()) return;
    flip_skip_epoch_ = srv_->flip_epoch();
    flip_skipped_local_ = 0;
    for (uint32_t i = 0, n = srv_->flip_source_clients(self_->id()); i < n; ++i) {
        Client* client = srv_->flip_client_at(self_->id(), i);
        if (!std::binary_search(flip_stayers_.begin(), flip_stayers_.end(), client,
                                std::less<Client*>{}))
            continue;
        if (srv_->flip_candidate_target(self_->id()) == Role::Ex) std::abort();
        srv_->flip_drop_planned_client(self_->id(), srv_->flip_client_destination(self_->id(), i),
                                       true);
        srv_->flip_forget_planned_client(self_->id(), i);
        ++flip_skipped_local_;
    }
}

bool IoLoop::flip_client_stays(const Client* client) const {
    return flip_stay_epoch_ == srv_->flip_epoch() &&
           std::binary_search(flip_stayers_.begin(), flip_stayers_.end(), client,
                              std::less<const Client*>{});
}

bool Server::flip_blocked_dispatch_allowed(uint32_t tid) const {
    const auto stage = flip_stage();
    if (stage < FlipStage::IoDrain || !flip_liveness_enabled()) return true;
    return stage == FlipStage::IoDrain && !flip_acked(tid, stage);
}

void IoLoop::flip_borrow_hold() {
    if (flip_borrow_held_) std::abort();
    flip_borrow_held_ = true;
    wb_.bind_release(this, [](void* context, int32_t shard, const char* ptr) {
        static_cast<IoLoop*>(context)->flip_borrow_releases_.push_back({shard, ptr});
    });
}

void IoLoop::flip_borrow_release() {
    if (!flip_borrow_held_) return;
    wb_.bind_release(this, [](void* context, int32_t shard, const char* ptr) {
        static_cast<IoLoop*>(context)->queue_borrow_release(shard, ptr);
    });
    flip_borrow_held_ = false;
    for (const BorrowRelease& release : flip_borrow_releases_)
        queue_borrow_release(release.shard, release.ptr);
    flip_borrow_releases_.clear();
}

void IoLoop::flip_borrow_resume() {
    if (!flip_borrow_held_ || srv_->flip_stage() != FlipStage::ExInstall ||
        !srv_->flip_all_role_acked(Role::Ex, FlipStage::ExInstall))
        return;
    // All consumers have installed their final masks. This runs before the
    // listener-admission acknowledgement on every surviving IO, so
    // Idle (and the next FLIP) cannot overtake a deferred release callback.
    // Shard storage and its borrow metadata moved together; route by the new map.
    flip_borrow_release();
}
