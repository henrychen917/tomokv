// FLIP session-readiness and closing-client cleanup predicates. Included by multi.inc in
// cmd/xshard.cc immediately after MultiSession, with BlockingState already defined. The
// session, queued argv/error and watched aliases belong to the stable Client. An unpublished
// attempt still owns admission on its source IO. The session-preserving migration exception is
// used during ClientPrepare after IoDrain/ExDrain; safe_to_release still requires zero pins.
bool Client::flip_session_pending() const { return multi_session_ && multi_session_->pending; }

// This cold predicate serves the offline behaviour twin and the
// transfer finish recheck. No command-dispatch body calls this function.
__attribute__((noinline, noipa)) bool Client::flip_migration_protocol_idle() const {
    if (multi_session_ && multi_session_->pending) return false;
    // Completed WATCH has one installed pin per physical alias, including all
    // namespaces. pending/ROB/drain exclude partial installation and cleanup;
    // equality rejects excess transient pins. safe_to_release still needs zero.
    const size_t aliases = multi_session_ ? multi_session_->watched.size() : 0;
    return watched_refs_.load(std::memory_order_acquire) == aliases && flip_drain_idle();
}

// Unpublished MULTI/EXEC attempts own IO admission/apply credits. Reject them on any source
// before ExDrain, preserving the session and source IO. Global dispatch pause prevents an
// attempt from publishing until rollback reaches Idle.
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

// The active close retry revisits idempotent WATCH cleanup before the zero-pin lifetime check.
// Both IO engines call it in their already-closing branch; ordinary GET/SET dispatch does not.
bool IoLoop::closing_client_ready(Client* client) {
    multi_close_entry(*this, *client);
    return client->safe_to_release();
}
