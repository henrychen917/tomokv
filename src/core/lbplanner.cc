// LB admission/gather/search has one writer: the main monitor thread.
// The existing stage word publishes a finished immutable slot to its IO coordinator.
#include "server.h"
#include "signal_doorbell.h"
#include "io_loop.h"

namespace tomo {
bool Server::lb_controller_tick(uint32_t coordinator, uint64_t now_ms) {
    if (!lb_controller_enabled() || coordinator >= nthreads()) return false;
    const bool key_enabled = key_lb_signals_enabled();
    const bool client_enabled = client_lb_signals_enabled();
    lb_ticks_.fetch_add(1, std::memory_order_relaxed);
    try {
        uint64_t plan_flip_epoch, plan_lb_epoch;
        std::vector<uint32_t> executors;
        std::vector<uint32_t> ios;
        {
            std::lock_guard<std::mutex> transition_lock(shape_transition_mu_);
            if (lb_stage() != LbStage::Idle || flip_dispatch_paused() ||
                !serves_clients(coordinator) || snapshot_.in_progress() || loading()) {
                lb_transition_refused_.fetch_add(1, std::memory_order_relaxed);
                return false;
            }
            // FLIP folds the same windows while holding this admission mutex. Serialising the
            // fold prevents a losing concurrent planner from consuming and decaying its tick.
            lb_fold_signals(now_ms * 1000000);
            plan_flip_epoch = flip_epoch();
            plan_lb_epoch = lb_epoch();
            if (cfg_.thread_mode == ThreadMode::Fused) {
                if (key_enabled) executors = placement_.ex_threads();
                if (client_enabled) ios = placement_.ifid_threads();
            } else {
                for (uint32_t tid = 0; tid < nthreads(); tid++) {
                    const Role role = thread(tid).role();
                    if (key_enabled && role == Role::Ex) executors.push_back(tid);
                    else if (client_enabled && role == Role::Ifid) ios.push_back(tid);
                }
            }

        } // release topology snapshot before admission/search

        auto spread = [](const double* loads, const std::vector<uint32_t>& owners) {
            if (owners.empty()) return 0.0;
            double lo = loads[owners.front()], hi = lo;
            for (uint32_t tid : owners) {
                lo = std::min(lo, loads[tid]);
                hi = std::max(hi, loads[tid]);
            }
            return hi - lo;
        };
        auto ratio_pct = [&](double span, const double* loads,
                             const std::vector<uint32_t>& owners) {
            double total = 0;
            for (uint32_t tid : owners) total += loads[tid];
            return total > 0 && !owners.empty()
                ? span * 100.0 * owners.size() / total : 0.0;
        };
        const uint64_t cooldown_ms = lb_policy_->cooldown_ms();
        auto update_streak = [&](double ratio, LbAutotune::QuietJitter& noise,
                                 uint32_t& streak, uint32_t owners) {
            if (!noise.observe(ratio)) {
                lb_hysteresis_refused_.fetch_add(1, std::memory_order_relaxed);
                return false;
            }
            const double fire = noise.band(owners);
            const double release = fire * 0.8; // Schmitt release band
            if (ratio > fire) streak = std::min<uint32_t>(streak + 1, LbAutotune::kDecisionTicks);
            else if (ratio < release || ratio == 0) streak = 0;
            if (streak < LbAutotune::kDecisionTicks) {
                lb_hysteresis_refused_.fetch_add(1, std::memory_order_relaxed);
                return false;
            }
            return true;
        };

        std::vector<LbShardMove> shard_plan;
        double shard_before = 0, shard_after = 0;
        double bytes_before = 0, bytes_after = 0;
        if (key_enabled && executors.size() >= 2) {
            double loads[kMaxThreads] = {};
            double byte_loads[kMaxThreads] = {};
            {
                std::lock_guard<std::mutex> transition_lock(shape_transition_mu_);
                if (flip_dispatch_paused() || flip_epoch() != plan_flip_epoch ||
                    lb_stage() != LbStage::Idle || lb_epoch() != plan_lb_epoch) {
                    lb_transition_refused_.fetch_add(1, std::memory_order_relaxed);
                    return false;
                }
                std::lock_guard<std::mutex> lock(lb_signal_mu_);
                for (uint32_t sid = 0; sid < nshards(); sid++) {
                    const uint32_t owner = worker_of_shard(static_cast<int32_t>(sid));
                    loads[owner] += lb_policy_->shards[sid].weight;
                    byte_loads[owner] += shard(static_cast<int32_t>(sid)).published_obj_bytes();
                }
            }
            shard_before = spread(loads, executors);
            bytes_before = spread(byte_loads, executors);
            const double weight_ratio = ratio_pct(shard_before, loads, executors);
            const double byte_ratio = ratio_pct(bytes_before, byte_loads, executors);
            lb_bucket_weight_spread_current_.store(
                static_cast<uint64_t>(shard_before * 1024.0 + 0.5),
                std::memory_order_relaxed);
            lb_bucket_bytes_spread_current_.store(
                static_cast<uint64_t>(bytes_before + 0.5), std::memory_order_relaxed);
            if (update_streak(std::max(weight_ratio, byte_ratio), lb_policy_->key_jitter,
                              lb_bucket_hot_streak_, executors.size())) {
                // Consume admission even when cooldown, indivisibility, or a sampled
                // no-improvement plan produces no move. Such a plan needs fresh sustain.
                lb_bucket_hot_streak_ = 0;
                std::vector<WeightedLbItem> shard_items;
                bool dominant_bucket;
                {
                    // Match FLIP's fold/ownership admission lock order. Do not consume
                    // bucket history if another transition won after the cheap fold.
                    std::lock_guard<std::mutex> transition_lock(shape_transition_mu_);
                    if (lb_stage() != LbStage::Idle || flip_dispatch_paused() ||
                        flip_epoch() != plan_flip_epoch || lb_epoch() != plan_lb_epoch ||
                        snapshot_.in_progress() || loading()) {
                        lb_transition_refused_.fetch_add(1, std::memory_order_relaxed);
                        return false;
                    }
                    dominant_bucket = lb_gather_key_evidence(shard_items, now_ms, cooldown_ms);
                }
                std::fill_n(loads, kMaxThreads, 0.0);
                std::fill_n(byte_loads, kMaxThreads, 0.0);
                uint32_t cooldown_seen = 0;
                for (const WeightedLbItem& item : shard_items) {
                    loads[item.owner] += item.weight;
                    byte_loads[item.owner] += item.secondary;
                    cooldown_seen += item.pinned;
                }
                shard_before = spread(loads, executors);
                bytes_before = spread(byte_loads, executors);
                const double band = lb_policy_->key_jitter.band(executors.size());
                if (dominant_bucket && ratio_pct(shard_before, loads, executors) > band) {
                    // The single-owner actuator cannot decompose a dominant bucket.
                    lb_hot_bucket_refused_.fetch_add(1, std::memory_order_relaxed);
                    lb_no_candidate_.fetch_add(1, std::memory_order_relaxed);
                } else {
                    const uint32_t move_cap = lb_policy_->move_cap(nshards());
                    for (uint32_t step = 0; step < move_cap; step++) {
                        const double old_weight_span = spread(loads, executors);
                        const double old_byte_span = spread(byte_loads, executors);
                        const bool demand_hot = ratio_pct(old_weight_span, loads, executors) >
                                                band;
                        const bool memory_hot = ratio_pct(old_byte_span, byte_loads, executors) >
                                                band;
                        if (!demand_hot && !memory_hot) break;
                        WeightedLbMoveChoice choice;
                        if (!weighted_lb_best_incremental_move(
                                shard_items, executors, demand_hot, memory_hot, choice)) {
                            if (cooldown_seen)
                                lb_cooldown_refused_.fetch_add(1, std::memory_order_relaxed);
                            else
                                lb_no_candidate_.fetch_add(1, std::memory_order_relaxed);
                            break;
                        }
                        WeightedLbItem& item = shard_items[choice.item_index];
                        shard_plan.push_back({static_cast<uint32_t>(item.id), choice.source,
                                             choice.destination, item.weight,
                                             static_cast<uint64_t>(item.secondary)});
                        loads[choice.source] -= item.weight;
                        loads[choice.destination] += item.weight;
                        byte_loads[choice.source] -= item.secondary;
                        byte_loads[choice.destination] += item.secondary;
                        item.owner = choice.destination;
                        item.pinned = true;
                    }
                }
                shard_after = spread(loads, executors);
                bytes_after = spread(byte_loads, executors);
            }
        } else if (key_enabled) {
            lb_no_candidate_.fetch_add(1, std::memory_order_relaxed);
            lb_bucket_hot_streak_ = 0;
        }

        LbClientMove client_plan;
        double client_before = 0, client_after = 0;
        if (client_enabled && ios.size() >= 2) {
            double loads[kMaxThreads] = {};
            for (uint32_t tid : ios)
                loads[tid] = double(lb_client_owner_weight_[tid].load(std::memory_order_acquire)) /
                             1024.0;
            client_before = spread(loads, ios);
            lb_client_weight_spread_current_.store(
                static_cast<uint64_t>(client_before * 1024.0 + 0.5),
                std::memory_order_relaxed);
            const double client_ratio = ratio_pct(client_before, loads, ios);
            if (update_streak(client_ratio, lb_policy_->client_jitter, lb_client_hot_streak_,
                              ios.size())) {
                lb_client_hot_streak_ = 0;
                std::fill_n(loads, kMaxThreads, 0.0);
                std::vector<WeightedLbItem> clients;
                uint32_t cooldown_seen = 0;
                {
                    std::lock_guard<std::mutex> lock(lb_signal_mu_);
                    clients.reserve(lb_clients_.size());
                    for (const auto& entry : lb_clients_) {
                        const LbClientSignal& signal = entry.second;
                        if (signal.owner >= nthreads() ||
                            thread(signal.owner).role() != Role::Ifid) continue;
                        const bool cooling = signal.last_move_ms &&
                            now_ms - signal.last_move_ms < cooldown_ms;
                        if (cooling) cooldown_seen++;
                        clients.push_back(
                            {entry.first, signal.owner, signal.weight, cooling, 0.0});
                        loads[signal.owner] += signal.weight;
                    }
                }
                client_before = spread(loads, ios);
                WeightedLbMoveChoice choice;
                if (!weighted_lb_best_incremental_move(
                        clients, ios, true, false, choice)) {
                    if (cooldown_seen)
                        lb_cooldown_refused_.fetch_add(1, std::memory_order_relaxed);
                    else
                        lb_no_candidate_.fetch_add(1, std::memory_order_relaxed);
                } else {
                    const WeightedLbItem& client = clients[choice.item_index];
                    client_plan = {client.id, choice.source, choice.destination, client.weight};
                    client_after = choice.after_weight_spread;
                }
            }
        } else if (client_enabled) {
            lb_no_candidate_.fetch_add(1, std::memory_order_relaxed);
            lb_client_hot_streak_ = 0;
        }

        const bool have_bucket = !shard_plan.empty();
        const bool have_client = client_plan.id != 0;
        if (!have_bucket && !have_client) {
            lb_no_candidate_.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
        const bool choose_client = have_client && (!have_bucket || lb_prefer_client_);

        std::lock_guard<std::mutex> transition_lock(shape_transition_mu_);
        if (lb_stage() != LbStage::Idle || flip_dispatch_paused() ||
            snapshot_.in_progress() || loading()) {
            lb_transition_refused_.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
        if (flip_epoch() != plan_flip_epoch || lb_epoch() != plan_lb_epoch) {
            lb_transition_refused_.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
        auto& plan = *lb_plan_;
        plan.flip_epoch = plan_flip_epoch;
        plan.lb_epoch = plan_lb_epoch;
        plan.choose_client = choose_client;
        plan.client = client_plan;
        plan.shards.swap(shard_plan); // old storage is reclaimed here, on the monitor
        plan.shard_before = shard_before;
        plan.shard_after = shard_after;
        plan.bytes_before = bytes_before;
        plan.bytes_after = bytes_after;
        plan.client_before = client_before;
        plan.client_after = client_after;
        lb_coordinator_ = coordinator;
        lb_stage_.store(LbStage::PlanReady, std::memory_order_release);
        return true;
    } catch (const std::bad_alloc&) {
        lb_capacity_refused_.fetch_add(1, std::memory_order_relaxed);
        return false;
    }
}


bool Server::lb_consume_plan(uint32_t coordinator) {
    // Only an observed PlanReady reaches this cold path. Never wait behind a monitor gather.
    std::unique_lock lock(shape_transition_mu_, std::try_to_lock);
    if (!lock || lb_stage() != LbStage::PlanReady || coordinator != lb_coordinator_) return false;
    auto& plan = *lb_plan_;
    if (flip_dispatch_paused() || flip_epoch() != plan.flip_epoch || lb_epoch() != plan.lb_epoch ||
        snapshot_.in_progress() || loading() || !serves_clients(coordinator)) {
        lb_transition_refused_.fetch_add(1, std::memory_order_relaxed);
        lb_stage_.store(LbStage::Idle, std::memory_order_release);
        return false;
    }
    for (uint32_t tid = 0; tid < nthreads(); tid++)
        lb_ack_[tid].store(0, std::memory_order_relaxed);
    lb_epoch_.fetch_add(1, std::memory_order_acq_rel);
    lb_deadline_ns_.store(now_ns() + LbAutotune::kMoveTimeoutNs,
                          std::memory_order_release);
    if (plan.choose_client) {
        lb_client_move_ = plan.client;
        lb_client_weight_spread_before_.store(
            static_cast<uint64_t>(plan.client_before * 1024.0 + 0.5),
            std::memory_order_relaxed);
        lb_client_weight_spread_after_.store(
            static_cast<uint64_t>(plan.client_after * 1024.0 + 0.5),
            std::memory_order_relaxed);
        lb_stage_.store(LbStage::ClientDrain, std::memory_order_release);
    } else {
        lb_shard_moves_.swap(plan.shards); // no allocation or reclamation on IO
        lb_bucket_weight_spread_before_.store(
            static_cast<uint64_t>(plan.shard_before * 1024.0 + 0.5),
            std::memory_order_relaxed);
        lb_bucket_weight_spread_after_.store(
            static_cast<uint64_t>(plan.shard_after * 1024.0 + 0.5),
            std::memory_order_relaxed);
        lb_bucket_bytes_spread_before_.store(
            static_cast<uint64_t>(plan.bytes_before + 0.5), std::memory_order_relaxed);
        lb_bucket_bytes_spread_after_.store(
            static_cast<uint64_t>(plan.bytes_after + 0.5), std::memory_order_relaxed);
        lb_start_shard_drain();
    }
    lb_prefer_client_ = !plan.choose_client;
    return true;
}

void Server::monitor_controllers() {
    if (!lb_controller_enabled() && !flipctl_enabled()) return;
    uint64_t next_lb_ms = 0, next_flip_ms = 0;
    for (;;) {
        if (shutting_down().load(std::memory_order_relaxed)) break;
        // Also covers a worker's boot failure, before it could publish normal shutdown.
        bool stopped = false;
        for (uint32_t tid = 0; tid < nthreads(); ++tid)
            stopped |= thread(tid).stop_flag().load(std::memory_order_relaxed);
        if (stopped) break;
        databases().monitor(*this);
        const uint64_t now_ms = now_ns() / 1000000;
        if (lb_controller_enabled() && now_ms >= next_lb_ms) {
            next_lb_ms = now_ms + lb_tick_ms();
            for (uint32_t tid = 0; tid < nthreads(); ++tid) {
                if (thread(tid).role() != Role::Ifid) continue;
                (void)lb_controller_tick(tid, now_ms);
                break;
            }
        }
        const uint64_t flip_now_ms = now_ns() / 1000000;
        if (flipctl_enabled() && flip_now_ms >= next_flip_ms) {
            (void)flipctl_tick(flip_now_ms);
            next_flip_ms = now_ns() / 1000000 + flipctl_wait_ms();
        }
        if (shutting_down().load(std::memory_order_relaxed)) break;
        const uint64_t finished_ms = now_ns() / 1000000;
        uint32_t wait_ms = flipctl_enabled()
            ? (next_flip_ms > finished_ms ? next_flip_ms - finished_ms : 0) : lb_tick_ms();
        if (lb_controller_enabled())
            wait_ms = std::min<uint64_t>(wait_ms, next_lb_ms > finished_ms ? next_lb_ms - finished_ms : 0);
        // Preserve multi-DB reclamation supervision at the existing worker-wait cadence.
        if constexpr (!kSingleDatabase) wait_ms = std::min(wait_ms, Ring::kWaitTimeoutMs);
        (void)signal_doorbell_wait(wait_ms);
    }
}

// These PRE bodies are comparison material, not a runtime mode. PAD-A retargets
// the existing tail/monitor calls and each private gate load in a COPY of POST.
// Keep the admission body and actuator body mechanically equal to cd02ecbab;
// the artifact verifier compares them before allowing a twin to be built.
bool Server::lb_controller_tick_pad(uint32_t coordinator, uint64_t now_ms) {
    if (!lb_controller_enabled() || coordinator >= nthreads()) return false;
    const bool key_enabled = key_lb_signals_enabled();
    const bool client_enabled = client_lb_signals_enabled();
    lb_ticks_.fetch_add(1, std::memory_order_relaxed);
    try {
        {
            std::lock_guard<std::mutex> transition_lock(shape_transition_mu_);
            if (lb_stage() != LbStage::Idle || flip_dispatch_paused() ||
                snapshot_.in_progress() || loading()) {
                lb_transition_refused_.fetch_add(1, std::memory_order_relaxed);
                return false;
            }
            // FLIP folds the same windows while holding this admission mutex. Serialising the
            // fold prevents a losing concurrent planner from consuming and decaying its tick.
            lb_fold_signals(now_ms * 1000000);
        }
        std::vector<uint32_t> executors;
        std::vector<uint32_t> ios;
        if (cfg_.thread_mode == ThreadMode::Fused) {
            if (key_enabled) executors = placement_.ex_threads();
            if (client_enabled) ios = placement_.ifid_threads();
        } else {
            for (uint32_t tid = 0; tid < nthreads(); tid++) {
                const Role role = thread(tid).role();
                if (key_enabled && role == Role::Ex) executors.push_back(tid);
                else if (client_enabled && role == Role::Ifid) ios.push_back(tid);
            }
        }

        auto spread = [](const double* loads, const std::vector<uint32_t>& owners) {
            if (owners.empty()) return 0.0;
            double lo = loads[owners.front()], hi = lo;
            for (uint32_t tid : owners) {
                lo = std::min(lo, loads[tid]);
                hi = std::max(hi, loads[tid]);
            }
            return hi - lo;
        };
        auto ratio_pct = [&](double span, const double* loads,
                             const std::vector<uint32_t>& owners) {
            double total = 0;
            for (uint32_t tid : owners) total += loads[tid];
            return total > 0 && !owners.empty()
                ? span * 100.0 * owners.size() / total : 0.0;
        };
        const uint64_t cooldown_ms = lb_policy_->cooldown_ms();
        auto update_streak = [&](double ratio, LbAutotune::QuietJitter& noise,
                                 uint32_t& streak, uint32_t owners) {
            if (!noise.observe(ratio)) {
                lb_hysteresis_refused_.fetch_add(1, std::memory_order_relaxed);
                return false;
            }
            const double fire = noise.band(owners);
            const double release = fire * 0.8; // Schmitt release band
            if (ratio > fire) streak = std::min<uint32_t>(streak + 1, LbAutotune::kDecisionTicks);
            else if (ratio < release || ratio == 0) streak = 0;
            if (streak < LbAutotune::kDecisionTicks) {
                lb_hysteresis_refused_.fetch_add(1, std::memory_order_relaxed);
                return false;
            }
            return true;
        };

        std::vector<LbShardMove> shard_plan;
        double shard_before = 0, shard_after = 0;
        double bytes_before = 0, bytes_after = 0;
        if (key_enabled && executors.size() >= 2) {
            double loads[kMaxThreads] = {};
            double byte_loads[kMaxThreads] = {};
            {
                std::lock_guard<std::mutex> lock(lb_signal_mu_);
                for (uint32_t sid = 0; sid < nshards(); sid++) {
                    const uint32_t owner = worker_of_shard(static_cast<int32_t>(sid));
                    loads[owner] += lb_policy_->shards[sid].weight;
                    byte_loads[owner] += shard(static_cast<int32_t>(sid)).published_obj_bytes();
                }
            }
            shard_before = spread(loads, executors);
            bytes_before = spread(byte_loads, executors);
            const double weight_ratio = ratio_pct(shard_before, loads, executors);
            const double byte_ratio = ratio_pct(bytes_before, byte_loads, executors);
            lb_bucket_weight_spread_current_.store(
                static_cast<uint64_t>(shard_before * 1024.0 + 0.5),
                std::memory_order_relaxed);
            lb_bucket_bytes_spread_current_.store(
                static_cast<uint64_t>(bytes_before + 0.5), std::memory_order_relaxed);
            if (update_streak(std::max(weight_ratio, byte_ratio), lb_policy_->key_jitter,
                              lb_bucket_hot_streak_, executors.size())) {
                // Consume admission even when cooldown, indivisibility, or a sampled
                // no-improvement plan produces no move. Such a plan needs fresh sustain.
                lb_bucket_hot_streak_ = 0;
                std::vector<WeightedLbItem> shard_items;
                bool dominant_bucket;
                {
                    // Match FLIP's fold/ownership admission lock order. Do not consume
                    // bucket history if another transition won after the cheap fold.
                    std::lock_guard<std::mutex> transition_lock(shape_transition_mu_);
                    if (lb_stage() != LbStage::Idle || flip_dispatch_paused() ||
                        snapshot_.in_progress() || loading()) {
                        lb_transition_refused_.fetch_add(1, std::memory_order_relaxed);
                        return false;
                    }
                    dominant_bucket = lb_gather_key_evidence(shard_items, now_ms, cooldown_ms);
                }
                std::fill_n(loads, kMaxThreads, 0.0);
                std::fill_n(byte_loads, kMaxThreads, 0.0);
                uint32_t cooldown_seen = 0;
                for (const WeightedLbItem& item : shard_items) {
                    loads[item.owner] += item.weight;
                    byte_loads[item.owner] += item.secondary;
                    cooldown_seen += item.pinned;
                }
                shard_before = spread(loads, executors);
                bytes_before = spread(byte_loads, executors);
                const double band = lb_policy_->key_jitter.band(executors.size());
                if (dominant_bucket && ratio_pct(shard_before, loads, executors) > band) {
                    // The single-owner actuator cannot decompose a dominant bucket.
                    lb_hot_bucket_refused_.fetch_add(1, std::memory_order_relaxed);
                    lb_no_candidate_.fetch_add(1, std::memory_order_relaxed);
                } else {
                    for (uint32_t step = 0; step < lb_policy_->move_cap(nshards()); step++) {
                        const double old_weight_span = spread(loads, executors);
                        const double old_byte_span = spread(byte_loads, executors);
                        const bool demand_hot = ratio_pct(old_weight_span, loads, executors) >
                                                band;
                        const bool memory_hot = ratio_pct(old_byte_span, byte_loads, executors) >
                                                band;
                        if (!demand_hot && !memory_hot) break;
                        WeightedLbMoveChoice choice;
                        if (!weighted_lb_best_incremental_move(
                                shard_items, executors, demand_hot, memory_hot, choice)) {
                            if (cooldown_seen)
                                lb_cooldown_refused_.fetch_add(1, std::memory_order_relaxed);
                            else
                                lb_no_candidate_.fetch_add(1, std::memory_order_relaxed);
                            break;
                        }
                        WeightedLbItem& item = shard_items[choice.item_index];
                        shard_plan.push_back({static_cast<uint32_t>(item.id), choice.source,
                                             choice.destination, item.weight,
                                             static_cast<uint64_t>(item.secondary)});
                        loads[choice.source] -= item.weight;
                        loads[choice.destination] += item.weight;
                        byte_loads[choice.source] -= item.secondary;
                        byte_loads[choice.destination] += item.secondary;
                        item.owner = choice.destination;
                        item.pinned = true;
                    }
                }
                shard_after = spread(loads, executors);
                bytes_after = spread(byte_loads, executors);
            }
        } else if (key_enabled) {
            lb_no_candidate_.fetch_add(1, std::memory_order_relaxed);
            lb_bucket_hot_streak_ = 0;
        }

        LbClientMove client_plan;
        double client_before = 0, client_after = 0;
        if (client_enabled && ios.size() >= 2) {
            double loads[kMaxThreads] = {};
            for (uint32_t tid : ios)
                loads[tid] = double(lb_client_owner_weight_[tid].load(std::memory_order_acquire)) /
                             1024.0;
            client_before = spread(loads, ios);
            lb_client_weight_spread_current_.store(
                static_cast<uint64_t>(client_before * 1024.0 + 0.5),
                std::memory_order_relaxed);
            const double client_ratio = ratio_pct(client_before, loads, ios);
            if (update_streak(client_ratio, lb_policy_->client_jitter, lb_client_hot_streak_,
                              ios.size())) {
                lb_client_hot_streak_ = 0;
                std::fill_n(loads, kMaxThreads, 0.0);
                std::vector<WeightedLbItem> clients;
                uint32_t cooldown_seen = 0;
                {
                    std::lock_guard<std::mutex> lock(lb_signal_mu_);
                    clients.reserve(lb_clients_.size());
                    for (const auto& entry : lb_clients_) {
                        const LbClientSignal& signal = entry.second;
                        if (signal.owner >= nthreads() ||
                            thread(signal.owner).role() != Role::Ifid) continue;
                        const bool cooling = signal.last_move_ms &&
                            now_ms - signal.last_move_ms < cooldown_ms;
                        if (cooling) cooldown_seen++;
                        clients.push_back(
                            {entry.first, signal.owner, signal.weight, cooling, 0.0});
                        loads[signal.owner] += signal.weight;
                    }
                }
                client_before = spread(loads, ios);
                WeightedLbMoveChoice choice;
                if (!weighted_lb_best_incremental_move(
                        clients, ios, true, false, choice)) {
                    if (cooldown_seen)
                        lb_cooldown_refused_.fetch_add(1, std::memory_order_relaxed);
                    else
                        lb_no_candidate_.fetch_add(1, std::memory_order_relaxed);
                } else {
                    const WeightedLbItem& client = clients[choice.item_index];
                    client_plan = {client.id, choice.source, choice.destination, client.weight};
                    client_after = choice.after_weight_spread;
                }
            }
        } else if (client_enabled) {
            lb_no_candidate_.fetch_add(1, std::memory_order_relaxed);
            lb_client_hot_streak_ = 0;
        }

        const bool have_bucket = !shard_plan.empty();
        const bool have_client = client_plan.id != 0;
        if (!have_bucket && !have_client) {
            lb_no_candidate_.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
        const bool choose_client = have_client && (!have_bucket || lb_prefer_client_);

        std::lock_guard<std::mutex> transition_lock(shape_transition_mu_);
        if (lb_stage() != LbStage::Idle || flip_dispatch_paused() ||
            snapshot_.in_progress() || loading()) {
            lb_transition_refused_.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
        for (uint32_t tid = 0; tid < nthreads(); tid++)
            lb_ack_[tid].store(0, std::memory_order_relaxed);
        lb_coordinator_ = coordinator;
        lb_epoch_.fetch_add(1, std::memory_order_acq_rel);
        lb_deadline_ns_.store(now_ns() + LbAutotune::kMoveTimeoutNs,
                              std::memory_order_release);
        if (choose_client) {
            lb_client_move_ = client_plan;
            lb_client_weight_spread_before_.store(
                static_cast<uint64_t>(client_before * 1024.0 + 0.5),
                std::memory_order_relaxed);
            lb_client_weight_spread_after_.store(
                static_cast<uint64_t>(client_after * 1024.0 + 0.5),
                std::memory_order_relaxed);
            lb_client_hot_streak_ = 0; // consume sustain before touching a candidate
            lb_stage_.store(LbStage::ClientDrain, std::memory_order_release);
        } else {
            lb_shard_moves_ = std::move(shard_plan);
            lb_bucket_weight_spread_before_.store(
                static_cast<uint64_t>(shard_before * 1024.0 + 0.5),
                std::memory_order_relaxed);
            lb_bucket_weight_spread_after_.store(
                static_cast<uint64_t>(shard_after * 1024.0 + 0.5),
                std::memory_order_relaxed);
            lb_bucket_bytes_spread_before_.store(
                static_cast<uint64_t>(bytes_before + 0.5), std::memory_order_relaxed);
            lb_bucket_bytes_spread_after_.store(
                static_cast<uint64_t>(bytes_after + 0.5), std::memory_order_relaxed);
            lb_bucket_hot_streak_ = 0;
            lb_start_shard_drain();
        }
        lb_prefer_client_ = !choose_client;
        return true;
    } catch (const std::bad_alloc&) {
        lb_capacity_refused_.fetch_add(1, std::memory_order_relaxed);
        return false;
    }
}

__attribute__((always_inline)) inline uint32_t IoLoop::lb_control_actuate_pad() {
    if (!lb_controller_armed_) return 0;
    const LbStage stage = srv_->lb_stage();
    if (stage != LbStage::ClientDrain) lb_client_wake_pending_ = false;
    if (stage == LbStage::Idle || stage == LbStage::ClientMoving) return 0;
    if (srv_->lb_drain_pass_expired(self_->id(), stage)) {
        lb_schedule_wake_all();
        return 1;
    }
    if (stage == LbStage::IoDrain) {
        // This control tail is outside dispatch: all owner samples taken by this IO
        // have either been posted (including quiet batches) or abandoned for reparse.
        if (!srv_->lb_acked(self_->id())) {
            srv_->lb_ack(self_->id());
            lb_schedule_wake_all();
        }
        if (self_->id() == srv_->lb_coordinator()) {
            if (srv_->lb_begin_ex_drain()) {
                lb_schedule_wake_all();
                return 1;
            }
            if (srv_->lb_timed_out()) {
                srv_->lb_stage_timed_out();
                lb_schedule_wake_all();
                return 1;
            }
        }
        return 1; // keep servicing the bounded drain; do not park waiting for the guard
    }
    if (stage == LbStage::ExDrain) {
        if (self_->id() == srv_->lb_coordinator()) {
            if (srv_->lb_all_ex_acked()) {
                (void)srv_->lb_commit_shard_plan(cached_now_ms_);
                lb_schedule_wake_all();
                return 1;
            } else if (srv_->lb_timed_out()) {
                srv_->lb_stage_timed_out();
                lb_schedule_wake_all();
                return 1;
            }
        }
        return 1;
    }

    const LbClientMove move = srv_->lb_client_move_pad();
    auto wake_source = [&]() {
        Ring* source = srv_->thread(move.source).ring();
        if (source && ring_.msg_to(*source, ur_tag(UrKind::Wake, nullptr))) {
            self_->sig().wakes_sent++;
            lb_client_wake_pending_ = false;
        } else {
            self_->sig().sqe_starved++;
        }
        return 1u;
    };
    if (lb_client_wake_pending_) return wake_source();
    uint32_t work = 0;
    if (move.destination == self_->id() && !srv_->lb_acked(self_->id())) {
        if (!prepare_client_transfer_capacity(1)) {
            srv_->lb_refuse_client_request();
            lb_schedule_wake_all();
            return 1;
        }
        srv_->lb_ack(self_->id());
        lb_client_wake_pending_ = true;
        work += wake_source();
    }
    if (move.source == self_->id() && srv_->lb_stage() == LbStage::ClientDrain) {
        Client* selected = nullptr;
        for (Client* client : self_->clients())
            if (client->id() == move.id) { selected = client; break; }
        if (!selected || selected->ifid_thread() != self_->id()) {
            srv_->lb_refuse_client_request();
            lb_schedule_wake_all();
            return 1;
        }
        std::string error;
        if (client_transfer_ready(selected, move.destination, error)) {
            if (!srv_->lb_acked(move.destination)) return 1;
            if (!srv_->lb_client_move_started(move.id, cached_now_ms_)) return 1;
            const bool started = request_client_transfer(selected, move.destination, error);
            if (!started) srv_->lb_client_move_cancelled(move.id);
            lb_schedule_wake_all();
            return 1;
        }
        // Busy predicates may need more work than our drain budget allows. Decline this candidate
        // immediately; none of the lifetime, ROB, output, or protocol fences may be waived.
        if (srv_->lb_refuse_stalled(srv_->lb_epoch(), lb_stall_reason(error))) {
            lb_schedule_wake_all();
            return 1;
        }
        if (selected->is_tls() || selected->multi_session() != nullptr ||
            selected->blocked()) {
            srv_->lb_refuse_client_request();
            lb_schedule_wake_all();
            return 1;
        }
    }
    if (self_->id() == srv_->lb_coordinator() && srv_->lb_timed_out()) {
        srv_->lb_stage_timed_out();
        lb_schedule_wake_all();
        return 1;
    }
    return work + 1;
}

uint32_t IoLoop::lb_control_pass_pad() {
    uint32_t did = lb_control_actuate_pad();
    // The same eight bytes were the PRE per-IO cron deadline. PAD never writes
    // a cached pause ID; its parser reads the live stage, as PRE did.
    if (__builtin_expect(lb_controller_armed_ && cached_now_ms_ >= lb_pause_id_, false)) {
        lb_pause_id_ = cached_now_ms_ + srv_->lb_tick_ms();
        if (srv_->lb_cron_writer_pad(self_->id()) &&
            srv_->lb_controller_tick_pad(self_->id(), cached_now_ms_))
            lb_schedule_wake_all();
        did++;
    }
    return did;
}

void Server::monitor_controllers_pad() {
    if (cfg_.thread_mode == ThreadMode::Fused) return; // PRE fused boots joined workers directly.
    if (flipctl_enabled()) {
        while (!shutting_down().load(std::memory_order_relaxed)) {
            databases().monitor(*this);
            (void)flipctl_tick(now_ns() / 1000000ull);
            if (shutting_down().load(std::memory_order_relaxed)) break;
            (void)signal_doorbell_wait(flipctl_wait_ms());
        }
    }
}

} // namespace tomo
