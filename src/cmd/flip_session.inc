// D18.1: only ClientPrepare (after IoDrain/ExDrain) uses this exception. The
// session, queued argv/error and watched aliases belong to the stable Client,
// not its IO. An unpublished attempt still owns admission on its source IO.
bool Client::flip_session_pending() const { return multi_session_ && multi_session_->pending; }

// Keep a distinct cold predicate for the PAD-A behaviour twin and for the
// transfer finish recheck. No command-dispatch body calls this function.
__attribute__((noinline, noipa)) bool Client::flip_migration_protocol_idle() const {
    if (multi_session_ && multi_session_->pending) return false;
    // Completed WATCH has one installed pin per physical alias, including all
    // namespaces. pending/ROB/drain exclude partial installation and cleanup;
    // equality rejects excess transient pins. safe_to_release still needs zero.
    const size_t aliases = multi_session_ ? multi_session_->watched.size() : 0;
    return watched_refs_.load(std::memory_order_acquire) == aliases && flip_drain_idle();
}

// D18.2 conservative policy: S2 owns unpublished IO admission/apply credits.
// Reject on ANY source before ExDrain; leave the state and original IO intact.
// The global dispatch pause prevents it publishing until rollback reaches Idle.
bool IoLoop::flip_session_drain_refused() const {
    for (const Client* client : self_->clients())
        if (client->flip_session_pending()) {
            srv_->flip_note_session_refusal(true);
            return true;
        }
    return false;
}

bool IoLoop::flip_session_close_held() {
    if (!flip_close_held()) return false;
    srv_->flip_note_session_refusal(false);
    return true;
}

// The active close retry must revisit deferred WATCH cleanup before its unchanged
// zero-pin lifetime check. It runs only in the already-closing branch (both IO
// engines); live GET/SET/etc never call it. The original cleanup is idempotent.
bool IoLoop::closing_client_ready(Client* client) {
    multi_close_entry(*this, *client);
    return client->safe_to_release();
}
