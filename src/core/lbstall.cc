// LB may decline a move; it may never turn a readiness fence into a traffic timeout.
#include "server.h"

namespace tomo {
LbStallReason lb_stall_reason(const std::string& error) {
    // Classify the existing readiness diagnostics without changing that lifetime-fence body.
    if (error == "connection is held by a generalized-thread pipeline batch")
        return LbStallReason::Pipeline;
    if (error == "connection ROB, reply, borrow, or owner-local protocol state is busy")
        return LbStallReason::Protocol;
    if (error == "connection has a deferred out-of-band frame")
        return LbStallReason::DeferredOutput;
    if (error == "connection has transient CLIENT/MONITOR/TRACKING state" ||
        error == "TLS connection has owner-local engine state") return LbStallReason::ClientState;
    if (error == "connection has an unfinished executor completion") return LbStallReason::Executor;
    return LbStallReason::InvalidClient;
}
namespace {
void note_max(std::atomic<uint64_t>& counter, uint64_t value) {
    uint64_t old = counter.load(std::memory_order_relaxed);
    while (old < value && !counter.compare_exchange_weak(
               old, value, std::memory_order_relaxed)) {}
}
}

bool Server::lb_drain_pass_expired(uint32_t tid, LbStage stage) {
    if (!lb_policy_) return false;
    if (stage == LbStage::ClientDrain && lb_client_move_.source != tid) return false;
    auto& state = lb_policy_->stall;
    static_assert(std::tuple_size_v<decltype(state.owners)> == kMaxThreads);
    auto& watch = state.owners[tid]; // only this physical IO writes its own watch
    const uint64_t epoch = lb_epoch();
    if (watch.epoch != epoch) watch = {epoch, 0, 0};
    return ++watch.passes >= LbStallState::kPassLimit &&
           lb_refuse_stalled(epoch, LbStallReason::PassLimit);
}

// A separate body also supplies an exact-size negative control: the measurement helper can
// replace this function by `return false` in a COPY of the binary, retaining every text address.
bool Server::lb_refuse_stalled(uint64_t epoch, LbStallReason reason) {
    std::lock_guard<std::mutex> transition_lock(shape_transition_mu_);
    const LbStage stage = lb_stage();
    if (lb_epoch() != epoch || (stage != LbStage::ClientDrain &&
        stage != LbStage::IoDrain && stage != LbStage::ExDrain)) return false;
    const uint64_t now = now_ns();
    std::lock_guard<std::mutex> signal_lock(lb_signal_mu_);
    if (stage == LbStage::ClientDrain) {
        lb_client_refused_.fetch_add(1, std::memory_order_relaxed);
        const auto found = lb_clients_.find(lb_client_move_.id);
        if (found != lb_clients_.end()) found->second.last_move_ms = now / 1000000;
    } else {
        lb_transition_refused_.fetch_add(1, std::memory_order_relaxed);
        // The normal candidate filter sees this refusal as cooldown and can choose another shard.
        for (const LbShardMove& move : lb_shard_moves_) {
            const Shard& physical = shard(static_cast<int32_t>(move.sid));
            for (uint32_t bucket = physical.bucket_begin(); bucket < physical.bucket_end(); bucket++)
                lb_bucket_last_move_ms_[bucket] = now / 1000000;
        }
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
    static constexpr const char* reasons[] = {
        "pass_limit", "pipeline", "protocol", "deferred_output", "client_state", "executor",
        "invalid_client", "destination"
    };
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
} // namespace tomo
