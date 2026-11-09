// Cold LB refusal and parked-input accounting for Server. shape_transition_mu_ serializes
// refusal with commit/stage changes; lb_signal_mu_ protects cooldown records. A release store
// of Idle resumes dispatch after refusal. Readiness and lifetime fences remain mandatory even
// when the controller gives up on a move.

#include "server.h"

namespace tomo {
LbStallReason lb_stall_reason(const std::string& error) {
    // Map client-transfer readiness diagnostics to refusal counters.
    if (error == "connection is held by a generalized-thread pipeline batch")
        return LbStallReason::Pipeline;
    if (error == "connection ROB, reply, borrow, or owner-local protocol state is busy")
        return LbStallReason::Protocol;
    if (error == "connection has a deferred out-of-band frame")
        return LbStallReason::DeferredOutput;
    if (error == "connection has transient CLIENT/MONITOR/TRACKING state" ||
        error == "TLS connection has owner-local engine state")
        return LbStallReason::ClientState;
    if (error == "connection has an unfinished executor completion") return LbStallReason::Executor;
    return LbStallReason::InvalidClient;
}
namespace {
void note_max(std::atomic<uint64_t>& counter, uint64_t value) {
    uint64_t old = counter.load(std::memory_order_relaxed);
    while (old < value && !counter.compare_exchange_weak(old, value, std::memory_order_relaxed)) {
    }
}
}

bool Server::lb_drain_pass_expired(uint32_t tid, LbStage stage) {
    if (!lb_policy_) return false;
    // Only client migration parks the selected connection behind its own readiness fence.
    // Shard drains must let every IO publish and every executor finish old-route work;
    // a fast IO exhausting three tails says nothing about those peers' progress.
    if (stage != LbStage::ClientDrain || lb_client_move_.source != tid) return false;
    auto& state = lb_policy_->stall;
    static_assert(std::tuple_size_v<decltype(state.owners)> == kMaxThreads);
    auto& watch = state.owners[tid];  // only this physical IO writes its own watch
    const uint64_t epoch = lb_epoch();
    if (watch.epoch != epoch) watch = {epoch, 0, 0};
    if (++watch.passes < LbStallState::kPassLimit) return false;
    const auto reason = stage == LbStage::ClientDrain && !lb_acked(lb_client_move_.destination)
                            ? LbStallReason::Destination
                            : LbStallReason::PassLimit;
    return lb_refuse_stalled(epoch, reason);
}

// This out-of-line body is also an offline negative-control patch point: a copied ELF can
// return false here while retaining every text address. Production refusal follows the protocol
// below.
// Contract: IO LB tails may request refusal for an observed epoch. Recheck epoch/stage under
// shape_transition_mu_, then update cooldowns under lb_signal_mu_ and release-store Idle after
// clearing the deadline. A stale or ineligible request returns false. No readiness fence is
// waived; the observe-only test build records evidence and returns false without cancelling the
// move.
__attribute__((noinline)) bool Server::lb_refuse_stalled(uint64_t epoch, LbStallReason reason) {
    std::lock_guard<std::mutex> transition_lock(shape_transition_mu_);
    const LbStage stage = lb_stage();
    if (lb_epoch() != epoch ||
        (stage != LbStage::ClientDrain && stage != LbStage::IoDrain && stage != LbStage::ExDrain))
        return false;
    const uint64_t now = now_ns();
#ifdef TOMO_LB_STALL_OBSERVE_ONLY
    // Diagnostic compile-time control: report the refusal predicate and pending duration while
    // leaving timeout-based refusal in charge. There is no runtime selector.
    if (lb_policy_) {
        auto& state = lb_policy_->stall;
        state.refused[static_cast<size_t>(reason)].fetch_add(1, std::memory_order_relaxed);
        const uint64_t deadline = lb_deadline_ns();
        if (deadline && now >= deadline - LbAutotune::kMoveTimeoutNs)
            note_max(state.pending_ns_max, now - (deadline - LbAutotune::kMoveTimeoutNs));
    }
    return false;
#endif
    std::lock_guard<std::mutex> signal_lock(lb_signal_mu_);
    if (stage == LbStage::ClientDrain) {
        lb_client_refused_.fetch_add(1, std::memory_order_relaxed);
        const auto found = lb_clients_.find(lb_client_move_.id);
        if (found != lb_clients_.end()) found->second.last_move_ms = now / 1000000;
    } else {
        lb_transition_refused_.fetch_add(1, std::memory_order_relaxed);
        // The normal candidate filter sees this refusal as cooldown and can choose another shard.
        for (const LbShardMove& move : lb_shard_moves_)
            lb_shard_last_move_ms_[move.sid] = now / 1000000;
    }
    if (lb_policy_) {
        auto& state = lb_policy_->stall;
        state.refused[static_cast<size_t>(reason)].fetch_add(1, std::memory_order_relaxed);
        const uint64_t deadline = lb_deadline_ns();
        if (deadline && now >= deadline - LbAutotune::kMoveTimeoutNs)
            note_max(state.pending_ns_max, now - (deadline - LbAutotune::kMoveTimeoutNs));
    }
    // This release is serialized against BOTH the commit and stage advancement. No peer may
    // resume dispatch while a coordinator is still transferring an acknowledged shard vector.
    lb_deadline_ns_.store(0, std::memory_order_release);
    lb_stage_.store(LbStage::Idle, std::memory_order_release);
    return true;
}

void Server::lb_stage_timed_out() {
    std::lock_guard<std::mutex> transition_lock(shape_transition_mu_);
    const LbStage stage = lb_stage();
    if (stage == LbStage::Idle || stage == LbStage::ClientMoving) return;
    const uint64_t now = now_ns();
    const uint64_t deadline = lb_deadline_ns();
    // A peer may have cancelled/replaced the observed plan before we took the lock.
    if (!deadline || now < deadline) return;
    std::lock_guard<std::mutex> signal_lock(lb_signal_mu_);
    if (stage == LbStage::ClientDrain) {
        lb_client_refused_.fetch_add(1, std::memory_order_relaxed);
        const auto found = lb_clients_.find(lb_client_move_.id);
        if (found != lb_clients_.end()) found->second.last_move_ms = now / 1000000;
    } else {
        lb_transition_refused_.fetch_add(1, std::memory_order_relaxed);
        if (stage == LbStage::IoDrain || stage == LbStage::ExDrain) {
            for (const LbShardMove& move : lb_shard_moves_)
                lb_shard_last_move_ms_[move.sid] = now / 1000000;
            if (lb_policy_) {
                auto& state = lb_policy_->stall;
                const uint64_t duration = now - (deadline - LbAutotune::kMoveTimeoutNs);
                state.shard_timeouts.fetch_add(1, std::memory_order_relaxed);
                note_max(state.shard_timeout_ns_max, duration);
                note_max(state.pending_ns_max, duration);
            }
        }
    }
    lb_deadline_ns_.store(0, std::memory_order_release);
    lb_stage_.store(LbStage::Idle, std::memory_order_release);
}

void Server::lb_debug_park(uint32_t tid, uint64_t bytes) {
    if (!lb_policy_) return;
    auto& state = lb_policy_->stall;
    auto& watch = state.owners[tid];
    const uint64_t epoch = lb_epoch(), now = now_ns();
    if (watch.epoch != epoch) watch = {epoch, 0, 0};
    if (!watch.first_park_ns) watch.first_park_ns = now;
    state.parked_passes.fetch_add(1, std::memory_order_relaxed);
    note_max(state.parked_bytes_max, bytes);
    note_max(state.parked_ns_max, now - watch.first_park_ns);
}

void Server::lb_stall_info(std::string& out) const {
    static constexpr const char* reasons[] = {"pass_limit",      "pipeline",     "protocol",
                                              "deferred_output", "client_state", "executor",
                                              "invalid_client",  "destination"};
    static_assert(std::size(reasons) == static_cast<size_t>(LbStallReason::Count));
    const auto* state = lb_policy_ ? &lb_policy_->stall : nullptr;
    auto append = [&](const char* name, uint64_t value) {
        out += "tomokv_lbstall_";
        out += name;
        out += ':';
        out += std::to_string(value);
        out += "\r\n";
    };
    for (size_t i = 0; i < std::size(reasons); i++)
        append(reasons[i], state ? state->refused[i].load(std::memory_order_relaxed) : 0);
    append("shard_timeouts", state ? state->shard_timeouts.load(std::memory_order_relaxed) : 0);
    append("shard_timeout_ns_max", state ? state->shard_timeout_ns_max.load(std::memory_order_relaxed) : 0);
    append("pending_ns_max", state ? state->pending_ns_max.load(std::memory_order_relaxed) : 0);
    append("parked_passes", state ? state->parked_passes.load(std::memory_order_relaxed) : 0);
    append("parked_bytes_max", state ? state->parked_bytes_max.load(std::memory_order_relaxed) : 0);
    append("parked_ns_max", state ? state->parked_ns_max.load(std::memory_order_relaxed) : 0);
#ifdef TOMO_LB_STALL_DEBUG
    append("debug", 1);
#else
    append("debug", 0);
#endif
}
}  // namespace tomo
