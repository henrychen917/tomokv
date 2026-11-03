// End-of-stream admission and retirement. Ordinary receives never enter here.
#include "io_loop.h"

namespace tomo {
namespace {
// Only a peer which stops making progress is bounded: each retired command or
// change in pending output restarts this grace period, regardless of depth.
constexpr uint64_t kEofStallMs = 1000;
}

bool IoLoop::receive_eof_pending(const Client* client) const {
    for (const auto& timer : deferred_timers_)
        if (timer.client == client && (timer.kind == DeferredTimerKind::ReceiveFin ||
                                      timer.kind == DeferredTimerKind::ReceiveEof)) return true;
    return false;
}

// FLIP pauses dispatch before its IO drain acknowledges, and that drain waits for every
// end-of-stream timer. A connection with consumed input and idle work closes through its
// own timer pass during the drain (a ReceiveFin keeps reading, so late input is seen on a
// later pass), and a pinned close keeps its approved refusal. Unconsumed input, or work
// which may need the paused admission, cannot drain behind this FLIP: refuse before commit.
// Cold: only FLIP's precommit check calls it; keep it out of this unit's inline budget.
[[gnu::cold]] bool IoLoop::receive_eof_blocks_flip(const Client* client) const {
    return receive_eof_pending(client) &&
           (client->rpos() < client->rlen() || !client->flip_drain_idle());
}

void IoLoop::receive_fin(Client* client, bool input_ended) {
    if (client->dead() || client->closing()) return;
    for (auto& timer : deferred_timers_) {
        if (timer.client != client || (timer.kind != DeferredTimerKind::ReceiveFin &&
                                      timer.kind != DeferredTimerKind::ReceiveEof)) continue;
        if (input_ended) timer.kind = DeferredTimerKind::ReceiveEof;
        client->set_recv_armed(timer.kind == DeferredTimerKind::ReceiveEof);
        mark_active(client);
        return;
    }
    try {
        deferred_timers_.push_back(DeferredTimer{client, client->rob().flush_id(),
            now_ns() / 1000000ull + kEofStallMs, client->buffered_output_bytes(), {},
            input_ended ? DeferredTimerKind::ReceiveEof : DeferredTimerKind::ReceiveFin});
    } catch (const std::bad_alloc&) {
        // recv(0) already released the kernel pin. A handoff rollback may have
        // left a synthetic hold which cannot outlive this failed insertion.
        if (input_ended) client->set_recv_armed(false);
        // epoll receives can run inside the active-set walk.
        if (epoll_) epoll_request_close(client);
        else close_client(client);
        return;
    }
    client->set_recv_armed(input_ended);
    mark_active(client);
}

void IoLoop::receive_eof_forget(Client* client) {
    for (size_t i = 0; i < deferred_timers_.size();) {
        const auto& timer = deferred_timers_[i];
        if (timer.client != client || (timer.kind != DeferredTimerKind::ReceiveFin &&
                                      timer.kind != DeferredTimerKind::ReceiveEof)) { ++i; continue; }
        if (timer.kind == DeferredTimerKind::ReceiveEof) client->set_recv_armed(false);
        deferred_timers_[i] = deferred_timers_.back();
        deferred_timers_.pop_back();
    }
}

bool IoLoop::receive_eof_pass(size_t index, uint64_t now_ms) {
    auto& timer = deferred_timers_[index];
    Client* client = timer.client;
    const bool ended = timer.kind == DeferredTimerKind::ReceiveEof;
    const uint64_t flushed = client->rob().flush_id();
    const uint64_t output = client->buffered_output_bytes();
    if (timer.op_id != flushed || timer.slow_started_ns != output) {
        timer.op_id = flushed;
        timer.slow_started_ns = output;
        timer.deadline_ms = now_ms + kEofStallMs;
    }
    bool input_drained = client->rpos() == client->rlen();
    if (ended && !input_drained && client->rob().quiesced() &&
        !client->scatter_barrier() && !client->parse_backpressure()) {
        // A truncated final frame has no future producer. Inspect a temporary
        // parse, leaving the live continuation untouched. Complete frames still
        // pass through ordinary admission, including CLIENT PAUSE and FLIP.
        Op probe;
        probe.reset();
        uint32_t position = client->rpos();
        const char* error = nullptr;
        input_drained = resp_parse_limited(client->rbuf(), client->rlen(), position,
            probe, &error, 1024 * 1024, proto_max_bulk_len_) == ParseResult::Incomplete;
    }
    const bool drained = ended && input_drained && client->rob().quiesced() &&
        client->nothing_to_write() && !client->send_inflight() && !client->serve_pending();
    // A blocked command cannot consume future input after FIN. Cancel it using
    // the existing close path, just as Redis does. Incomplete final frames and
    // peers which no longer read replies cannot retain a connection forever.
    bool control_pending = false;
    if (client->blocked()) {
        for (const auto& pending : deferred_timers_)
            if (pending.client == client &&
                (pending.kind == DeferredTimerKind::DebugSleepOk ||
                 pending.kind == DeferredTimerKind::TrackingOn)) {
                control_pending = true;
                break;
            }
    }
    // These are synchronous commands whose owner acknowledgements use a timer,
    // not a blocked list/stream wait. EOF cannot cancel their buffered suffix.
    if (control_pending) timer.deadline_ms = now_ms + kEofStallMs;
    const bool stalled = now_ms >= timer.deadline_ms && output != 0;
    if (client->closing() || (client->blocked() && !control_pending) || drained || stalled) {
        receive_eof_forget(client);
        close_client(client);
        if (epoll_) (void)wb_.take_send_failure();
        return true;
    }
    // A FIN edge can contain a short positive read. Only an actual recv(0)
    // closes admission; until then force another attempt without needing an edge.
    client->set_recv_armed(ended);
    if (!ended || client->rpos() < client->rlen()) mark_active(client);
    return false;
}
} // namespace tomo
