// FLIP-only connection liveness. Included after MultiSession and BlockingState.
// No command, parse, retirement, or socket-send body calls these helpers.

// PAD-A patches only this immediate in each namespace. PRE behavior then runs
// with exactly the candidate's text/layout; this is not a runtime option.
__attribute__((noinline, noipa)) int flip_liveness_enabled() {
    int enabled;
    asm volatile("mov $1, %0" : "=a"(enabled));
    return enabled;
}

bool Client::flip_execution_idle() const {
    return rob_.quiesced() && !retire_queued_.load(std::memory_order_acquire) &&
           barrier_owners_ == 0 && atomic_groups_io_ == 0 && !blocked() &&
           !segments_.has_borrow();
}

bool Client::flip_held_output_idle() const {
    if (multi_session_ && multi_session_->pending) return false;
    const size_t aliases = multi_session_ ? multi_session_->watched.size() : 0;
    return watched_refs_.load(std::memory_order_acquire) == aliases &&
           !send_inflight_ && flip_execution_idle();
}

bool IoLoop::flip_post_drain() const {
    return flip_liveness_enabled() && srv_->flip_stage() == FlipStage::ClientInstall;
}

bool IoLoop::flip_output_held(const Client* client) const {
    return std::binary_search(flip_held_output_.begin(), flip_held_output_.end(),
                              client, std::less<const Client*>{});
}

bool IoLoop::flip_output_hold() {
    if (!flip_liveness_enabled()) return true;
    // IoDrain proved no socket send or serve is outstanding. Reserve before
    // installing any pin; a failed allocation cannot leave a partially held IO.
    if (!flip_held_output_.empty()) std::abort();
    try { flip_held_output_.reserve(self_->clients().size()); }
    catch (const std::bad_alloc&) {
        srv_->flip_note_failure("ERR FLIP could not reserve socket-output holds");
        return false;
    }
    for (Client* client : self_->clients()) {
        if (client == flip_client_ || client->closing() || client->is_tls()) continue;
        if (client->send_inflight() || client->serve_pending()) std::abort();
        client->set_serve_pending(true);
        flip_held_output_.push_back(client);
    }
    std::sort(flip_held_output_.begin(), flip_held_output_.end(), std::less<Client*>{});
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
    } catch (const std::bad_alloc&) { return false; }
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
    for (Client* client : flip_held_output_) {
        // A pinned close dropped from the plan still belongs to this source.
        client->set_serve_pending(false);
        enqueue_serve(client);
    }
    flip_held_output_.clear();
}

void IoLoop::flip_output_adopt(Client* client) {
    if (!client->serve_pending()) return; // LB has no held serve; unchanged behavior.
    if (!flip_liveness_enabled() || srv_->flip_stage() < FlipStage::ClientCommit)
        std::abort();
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
    // behind the unchanged dispatch pause. Stage their replies without pumping.
    for (Client* client : flip_held_output_) {
        bool submit_allowed = true;
        if (climon_reply_suppressed(client))
            (void)climon_prepare_suppressed(client, submit_allowed);
        else if (epoll_) (void)wb_.prepare<true, true>(*client, submit_allowed);
        else (void)wb_.prepare<false, true>(*client, submit_allowed);
    }
}

void IoLoop::flip_output_unhold(Client* client) {
    auto at = std::lower_bound(flip_held_output_.begin(), flip_held_output_.end(),
                                client, std::less<Client*>{});
    if (at == flip_held_output_.end() || *at != client) return;
    flip_held_output_.erase(at);
    client->set_serve_pending(false);
    enqueue_serve(client);
}
