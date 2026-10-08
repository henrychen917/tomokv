// LB admission/gather/search has one writer: the main monitor thread.
// The existing stage word publishes a finished immutable slot to its IO coordinator.
#include "server.h"
#include "signal_doorbell.h"
#include "io_loop.h"
#include "../cmd/info_stats.h"
#include <tuple>

namespace tomo {
// One offline PAD-A patch point: returning zero restores PRE policy on this exact
// layout. Production returns the configured level; no ordinary operation calls it.
__attribute__((noipa)) int32_t lbosc3_level(int32_t configured) { return configured; }

void Server::lb_key_damping_init() {
    if (lbosc3_level(cfg_.key_lb_damping) && !lb_policy_->key_damping)
        lb_policy_->key_damping = std::make_unique<LbAutotune::KeyDamping>();
}

void Server::lb_key_damping_info(std::string& out) const {
    const auto* state = lb_policy_ ? lb_policy_->key_damping.get() : nullptr;
    out += "tomokv_keylb_damping_band_pct:" + std::to_string(state ? state->base_band.load() : 0) + "\r\n";
    out += "tomokv_keylb_damping_fire_pct:" + std::to_string(state ? state->fire_band.load() : 0) + "\r\n";
    out += "tomokv_keylb_damping_ticks:" + std::to_string(state ? state->required_ticks.load() : 0) + "\r\n";
}

bool LbAutotune::KeyDamping::update(double ratio, QuietJitter& noise, uint32_t& streak,
                                   uint32_t owners, int32_t level, uint64_t now_ms,
                                   uint64_t completed, uint64_t epoch) {
    const bool learned = noise.observe(ratio);
    const double band = noise.band(owners);
    // A full owner's load contains ceil(100/band) independently resolvable steps.
    // Retain move pressure for that many decision windows, using the existing tick.
    const double horizon = kDecisionTicks * std::ceil(100.0 / band);
    if (topology != epoch || completed < moves || now_ms < last_ms) {
        recent = 0;
        moves = completed;
        topology = epoch;
        streak = 0;
    } else if (last_ms) {
        // A skipped controller tick cannot count as a consecutive crossing.
        if (now_ms - last_ms >= 2 * kTickMs) streak = 0;
        recent *= std::exp2(-double(now_ms - last_ms) / (horizon * kTickMs));
    }
    if (completed != moves) {
        recent += completed - moves;
        streak = 0; // a completed plan always needs a fresh run of crossed ticks
    }
    if (recent < 1.0 / kSamplesPerDecision) recent = 0;
    moves = completed;
    last_ms = now_ms;
    // Auto charges one decision window per recent move. Explicit N scales that
    // charge. Both K and widening saturate at a horizon; arithmetic stays bounded
    // even at INT32_MAX. The 1.5 ceiling is the owner's allowed accuracy budget.
    const double extra_cap = std::max(1.0, horizon - kDecisionTicks);
    const double pressure = std::min(extra_cap, recent * (level < 0 ? kDecisionTicks : level));
    const uint32_t ticks = kDecisionTicks + static_cast<uint32_t>(std::ceil(pressure));
    const double fire = band * (1.0 + 0.5 * pressure / extra_cap);
    base_band.store(band, std::memory_order_relaxed);
    fire_band.store(fire, std::memory_order_relaxed);
    required_ticks.store(ticks, std::memory_order_relaxed);
    if (!learned) return false;
    if (ratio > fire) streak = std::min(streak + 1, ticks);
    else if (recent > 0 || ratio < 0.8 * fire) streak = 0;
    return streak >= ticks;
}

// The key objective lives in the cold planner TU. The shared PRE search remains
// unchanged for clients, FLIP, and the behaviour twin.
bool lbosc3_best_incremental_move(const std::vector<WeightedLbItem>& items,
                                              const std::vector<uint32_t>& targets,
                                              bool demand_hot, bool secondary_hot,
                                              WeightedLbMoveChoice& choice, double band) {
    choice = {};
    if (targets.size() < 2 || (!demand_hot && !secondary_hot)) return false;
    std::vector<double> load(targets.size(), 0);
    std::vector<double> secondary_load(targets.size(), 0);
    std::vector<uint32_t> count(targets.size(), 0);
    auto target_index = [&](uint32_t tid) {
        for (uint32_t i = 0; i < targets.size(); i++) if (targets[i] == tid) return i;
        return UINT32_MAX;
    };
    for (const WeightedLbItem& item : items) {
        const uint32_t owner = target_index(item.owner);
        if (owner == UINT32_MAX) return false;
        load[owner] += std::max(0.0, item.weight);
        secondary_load[owner] += std::max(0.0, item.secondary);
        count[owner]++;
    }
    double total = 0, secondary_total = 0;
    for (double value : load) total += value;
    for (double value : secondary_load) secondary_total += value;
    const double weight_band = total / targets.size() * band / 100.0;
    const double secondary_band = secondary_total / targets.size() * band / 100.0;
    auto spread = [](const auto& values) {
        const auto [lo, hi] = std::minmax_element(values.begin(), values.end());
        return values.empty() ? 0.0 : static_cast<double>(*hi - *lo);
    };
    const double old_weight = spread(load);
    const double old_secondary = spread(secondary_load);
    choice.before_weight_spread = old_weight;
    choice.before_secondary_spread = old_secondary;
    // All residuals inside the band have the same objective. Among those moves,
    // transfer the least load: correcting a resolvable imbalance is enough.
    // Outside the band the first component is strictly ordered by raw residual.
    using Score = std::tuple<double, double, double, double, uint32_t, uint64_t, uint32_t>;
    Score best{};
    for (uint32_t item_index = 0; item_index < items.size(); item_index++) {
        const WeightedLbItem& item = items[item_index];
        if (item.pinned) continue;
        const uint32_t source = target_index(item.owner);
        for (uint32_t destination = 0; destination < targets.size(); destination++) {
            if (destination == source) continue;
            load[source] -= std::max(0.0, item.weight);
            load[destination] += std::max(0.0, item.weight);
            secondary_load[source] -= std::max(0.0, item.secondary);
            secondary_load[destination] += std::max(0.0, item.secondary);
            count[source]--;
            count[destination]++;
            const double next_weight = spread(load);
            const double next_secondary = spread(secondary_load);
            const auto [count_lo, count_hi] = std::minmax_element(count.begin(), count.end());
            const uint32_t next_count = *count_hi - *count_lo;
            count[destination]--;
            count[source]++;
            secondary_load[destination] -= std::max(0.0, item.secondary);
            secondary_load[source] += std::max(0.0, item.secondary);
            load[destination] -= std::max(0.0, item.weight);
            load[source] += std::max(0.0, item.weight);

            const bool improves = demand_hot
                ? next_weight + 1e-9 < old_weight
                : next_weight <= old_weight + 1e-9 &&
                  next_secondary + 1e-9 < old_secondary;
            if (!improves) continue;
            const Score score{
                std::max(0.0, next_weight - weight_band),
                std::max(0.0, next_secondary - secondary_band),
                demand_hot ? item.weight : item.secondary,
                demand_hot ? item.secondary : item.weight,
                next_count, item.id, targets[destination]};
            if (choice.item_index == UINT32_MAX || score < best) {
                choice.item_index = item_index;
                choice.source = item.owner;
                choice.destination = targets[destination];
                choice.after_weight_spread = next_weight;
                choice.after_secondary_spread = next_secondary;
                best = score;
            }
        }
    }
    return choice.item_index != UINT32_MAX;
}

bool Server::lb_controller_tick(uint32_t coordinator, uint64_t now_ms) {
    if (!lb_controller_enabled() || coordinator >= nthreads()) return false;
    const int32_t damping = lbosc3_level(cfg_.key_lb_damping);
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
            else if (ratio < release) streak = 0;
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
            // LBOSC3 BEGIN admission: only the key planner sees damping.
            bool key_admitted;
            if (damping && lb_policy_->key_damping) {
                key_admitted = lb_policy_->key_damping->update(
                    std::max(weight_ratio, byte_ratio), lb_policy_->key_jitter,
                    lb_bucket_hot_streak_, executors.size(), damping, now_ms,
                    lb_bucket_moves(), plan_flip_epoch);
                if (!key_admitted)
                    lb_hysteresis_refused_.fetch_add(1, std::memory_order_relaxed);
            } else {
                key_admitted = update_streak(std::max(weight_ratio, byte_ratio),
                    lb_policy_->key_jitter, lb_bucket_hot_streak_, executors.size());
            }
            // LBOSC3 END admission
            if (key_admitted) {
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
                const double band = damping && lb_policy_->key_damping
                    ? lb_policy_->key_damping->fire_band.load(std::memory_order_relaxed)
                    : lb_policy_->key_jitter.band(executors.size());
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
                        const bool found = damping
                            ? lbosc3_best_incremental_move(shard_items, executors,
                                  demand_hot, memory_hot, choice, band)
                            : weighted_lb_best_incremental_move(shard_items, executors,
                                  demand_hot, memory_hot, choice);
                        if (!found) {
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
        // SC orders late ClientDrain readers against the record-reuse check below.
        lb_stage_.store(LbStage::PlanReady, std::memory_order_seq_cst);
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
    // A cancelled drain may still have a reader in its source/destination tail. Keep
    // the new plan unconsumed, without pausing traffic, until that immutable read ends.
    // Never wait while holding the shape mutex: an old reader may need it to refuse.
    if (plan.client_readers.load(std::memory_order_seq_cst) != 0) return false;
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
    // INFO sampling also needs this existing cold thread when both controllers are off.
    uint64_t next_lb_ms = 0, next_flip_ms = 0, next_info_ms = 0;
    for (;;) {
        if (shutting_down().load(std::memory_order_relaxed)) break;
        // Also covers a worker's boot failure, before it could publish normal shutdown.
        bool stopped = false;
        for (uint32_t tid = 0; tid < nthreads(); ++tid)
            stopped |= thread(tid).stop_flag().load(std::memory_order_relaxed);
        if (stopped) break;
        databases().monitor(*this);
        const uint64_t now_ms = now_ns() / 1000000;
        if (now_ms >= next_info_ms) {
            info_stats_tick(*this);
            next_info_ms = now_ms + 100;
        }
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
        wait_ms = std::min<uint64_t>(wait_ms, next_info_ms > finished_ms ? next_info_ms - finished_ms : 0);
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
            else if (ratio < release) streak = 0;
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

// PRE had no per-pass pause snapshot; its live per-connection gate is restored in PAD.
// In particular, do not overwrite the same eight bytes that PAD uses as its cron deadline.
void IoLoop::lb_pass_begin_pad() {}

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
