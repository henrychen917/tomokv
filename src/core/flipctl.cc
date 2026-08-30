#include "flipctl.h"

#include <algorithm>
#include <cmath>
#include <cstdio>

#include "server.h"

namespace tomo {

namespace {

double relative_distance(double left, double right) {
    const double scale = std::max(std::abs(left), std::abs(right));
    return scale > 0 ? std::abs(left - right) / scale : 0;
}

double unit_normalized_distance(double left, double right) {
    // A one-byte/one-key measurement quantum keeps a zero anchor from turning one rare admin
    // command's infinitesimal average into distance 1. Large workload changes still approach 1.
    return std::abs(left - right) / (1.0 + std::max(std::abs(left), std::abs(right)));
}

template <size_t N>
void normalize(const std::array<uint64_t, N>& input, std::array<double, N>& output) {
    uint64_t total = 0;
    for (uint64_t value : input) total += value;
    if (!total) return;
    for (size_t i = 0; i < N; i++)
        output[i] = static_cast<double>(input[i]) / static_cast<double>(total);
}

void add_delta(uint64_t current, uint64_t previous, uint64_t& destination) {
    if (current >= previous) destination += current - previous;
}

}  // namespace

FlipSignature flip_signature(const FlipFingerprintWindow& sample) {
    FlipSignature signature;
    if (!sample.commands) return signature;
    normalize(sample.pass_depth, signature.pass_depth);
    normalize(sample.command_class, signature.command_class);
    signature.keys_per_multikey = sample.multikey_ops
        ? static_cast<double>(sample.multikey_keys) / sample.multikey_ops : 0;
    signature.value_bytes_per_command =
        static_cast<double>(sample.value_bytes) / sample.commands;
    signature.commands = sample.commands;
    signature.valid = true;
    return signature;
}

double flip_signature_distance(const FlipSignature& left, const FlipSignature& right) {
    if (!left.valid || !right.valid) return 0;
    double pass_l1 = 0, class_l1 = 0;
    for (size_t i = 0; i < left.pass_depth.size(); i++)
        pass_l1 += std::abs(left.pass_depth[i] - right.pass_depth[i]);
    for (size_t i = 0; i < left.command_class.size(); i++)
        class_l1 += std::abs(left.command_class[i] - right.command_class[i]);
    // Each probability-vector L1 is in [0,2], while each relative scalar distance is in [0,1].
    // Dividing by the four feature families keeps the complete distance normalized to [0,1].
    return (pass_l1 * 0.5 + class_l1 * 0.5 +
            unit_normalized_distance(left.keys_per_multikey, right.keys_per_multikey) +
            unit_normalized_distance(left.value_bytes_per_command,
                                     right.value_bytes_per_command)) * 0.25;
}

void FlipShiftDetector::reset() {
    smoothed_ = {};
    previous_ = {};
    learning_origin_ = {};
    anchored_signature_ = {};
    jitter_ = 0;
    band_ = 0;
    last_distance_ = 0;
    have_previous_ = false;
    have_jitter_ = false;
    anchored_ = false;
}

void FlipShiftDetector::update_band() {
    if (configured_band_ == 0) {
        band_ = 0;
        return;
    }
    if (configured_band_ > 0) {
        band_ = static_cast<double>(configured_band_) / 100.0;
        return;
    }
    // One rare command can move each of the four normalized feature families. Use that vector
    // dimensionality as the sampling quantum; otherwise an INFO poll amid a zero-value GET stream
    // is numerically larger than the one-command floor and the detector triggers on observability.
    const double quantum = smoothed_.commands
        ? 4.0 / static_cast<double>(smoothed_.commands) : 0;
    band_ = 2.0 * std::max(jitter_, quantum);
}

bool FlipShiftDetector::observe(const FlipFingerprintWindow& sample) {
    const FlipSignature incoming = flip_signature(sample);
    if (!incoming.valid) return false;
    if (!smoothed_.valid) {
        smoothed_ = incoming;
        learning_origin_ = incoming;
    } else {
        for (size_t i = 0; i < smoothed_.pass_depth.size(); i++)
            smoothed_.pass_depth[i] =
                (smoothed_.pass_depth[i] + incoming.pass_depth[i]) * 0.5;
        for (size_t i = 0; i < smoothed_.command_class.size(); i++)
            smoothed_.command_class[i] =
                (smoothed_.command_class[i] + incoming.command_class[i]) * 0.5;
        smoothed_.keys_per_multikey =
            (smoothed_.keys_per_multikey + incoming.keys_per_multikey) * 0.5;
        smoothed_.value_bytes_per_command =
            (smoothed_.value_bytes_per_command + incoming.value_bytes_per_command) * 0.5;
        smoothed_.commands = incoming.commands;
        smoothed_.valid = true;
    }

    const double adjacent = have_previous_
        ? flip_signature_distance(smoothed_, previous_) : 0;
    if (anchored_) {
        last_distance_ = flip_signature_distance(smoothed_, anchored_signature_);
        // The quiet-state band is an anchor property. Do not let later traffic widen its own
        // trigger threshold (or change the command-quantum floor) while being judged by it.
        previous_ = smoothed_;
        have_previous_ = true;
        return configured_band_ != 0 && last_distance_ > band_;
    }

    if (have_previous_) {
        // Quiet jitter is a band, not a trend estimate: retain the largest adjacent EWMA movement
        // observed at the anchor instead of letting one unusually quiet pair collapse the band.
        jitter_ = have_jitter_ ? std::max(jitter_, adjacent) : adjacent;
        have_jitter_ = true;
    }
    if (!anchored_ && learning_origin_.valid) {
        jitter_ = std::max(jitter_,
                           flip_signature_distance(smoothed_, learning_origin_));
        have_jitter_ = true;
    }
    previous_ = smoothed_;
    have_previous_ = true;
    update_band();
    return false;
}

void FlipShiftDetector::anchor() {
    if (!smoothed_.valid) return;
    anchored_signature_ = smoothed_;
    anchored_ = true;
    last_distance_ = 0;
    update_band();
}

bool FlipController::init(bool enabled, int32_t configured_band, uint32_t nthreads) {
    enabled_ = enabled;
    configured_band_ = configured_band;
    signature_learning_windows_ = std::max<uint32_t>(1, nthreads);
    maneuver_learning_windows_ = 0;
    for (uint32_t value = nthreads; value > 1; value >>= 1)
        maneuver_learning_windows_++;
    maneuver_learning_windows_ = std::max<uint32_t>(1, maneuver_learning_windows_);
    shift_detector_ = FlipShiftDetector(configured_band);
    if (!enabled) {
        phase_ = Phase::Disabled;
        return true;
    }
    try {
        fingerprint_last_.resize(nthreads);
        maneuver_start_.resize(nthreads);
        // At most one observation per split is needed for the seek itself, followed by up to one
        // thread-count-derived set of final anchor readings. Reserve both cold phases up front.
        readings_.reserve(static_cast<size_t>(nthreads) * 2);
    } catch (const std::bad_alloc&) {
        return false;
    }
    phase_ = Phase::BootPending;
    return true;
}

const char* FlipController::phase_name(Phase phase) {
    switch (phase) {
        case Phase::Disabled: return "disabled";
        case Phase::BootPending: return "boot-pending";
        case Phase::Measuring: return "measuring";
        case Phase::WaitingFlip: return "waiting-flip";
        case Phase::Seeking: return "seeking";
        case Phase::Settling: return "settling";
        case Phase::Anchored: return "anchored";
    }
    return "disabled";
}

const char* FlipController::reason_name(FlipctlTriggerReason reason) {
    switch (reason) {
        case FlipctlTriggerReason::None: return "none";
        case FlipctlTriggerReason::Boot: return "boot";
        case FlipctlTriggerReason::FingerprintShift: return "fingerprint-shift";
        case FlipctlTriggerReason::AnchorRateCollapse: return "anchor-rate-collapse";
        case FlipctlTriggerReason::Forced: return "forced";
    }
    return "none";
}

uint64_t FlipController::total_commands(const Server& server) const {
    uint64_t total = 0;
    for (uint32_t tid = 0; tid < server.nthreads(); tid++)
        total += server.thread(tid).total_commands();
    return total;
}

FlipController::MovementStamp FlipController::movement_stamp(const Server& server) const {
    return MovementStamp{
        server.flip_completed(), server.flip_refused(), server.flip_clients_transferred(),
        server.lb_bucket_moves(), server.lb_client_moves()};
}

bool FlipController::sample_fingerprint(Server& server) {
    if (!server.cfg().flip_work_window) return false;
    FlipFingerprintWindow aggregate;
    bool any = false;
    for (uint32_t tid = 0; tid < server.nthreads(); tid++) {
        const FlipFingerprintWindow current = server.thread(tid).flip_fingerprint().published();
        FlipFingerprintWindow& previous = fingerprint_last_[tid];
        if (current.closed_windows == previous.closed_windows) continue;
        add_delta(current.commands, previous.commands, aggregate.commands);
        add_delta(current.multikey_keys, previous.multikey_keys, aggregate.multikey_keys);
        add_delta(current.multikey_ops, previous.multikey_ops, aggregate.multikey_ops);
        add_delta(current.value_bytes, previous.value_bytes, aggregate.value_bytes);
        add_delta(current.closed_windows, previous.closed_windows, aggregate.closed_windows);
        for (size_t i = 0; i < aggregate.pass_depth.size(); i++)
            add_delta(current.pass_depth[i], previous.pass_depth[i], aggregate.pass_depth[i]);
        for (size_t i = 0; i < aggregate.command_class.size(); i++)
            add_delta(current.command_class[i], previous.command_class[i],
                      aggregate.command_class[i]);
        previous = current;
        any = true;
    }
    if (!any) return false;
    if (phase_ == Phase::Settling) anchor_signature_samples_++;
    const bool shifted = shift_detector_.observe(aggregate);
    if (phase_ != Phase::Anchored && phase_ != Phase::Disabled &&
        phase_ != Phase::BootPending && !shift_detector_.anchored()) {
        maneuver_signature_samples_++;
        const uint32_t learning_windows = phase_ == Phase::Settling
            ? signature_learning_windows_ : maneuver_learning_windows_;
        if (maneuver_signature_samples_ >= learning_windows)
            shift_detector_.anchor();
    }
    return shifted;
}

double FlipController::automatic_rate_band(double pair_delta, double rate) const {
    const double quantum = rate > 0 ? 1.0 / rate : 0;
    return 2.0 * std::max(pair_delta, quantum);
}

bool FlipController::sample_stabilized_rate(Server& server, uint64_t now_ms, double& rate) {
    const uint64_t commands = total_commands(server);
    const MovementStamp movement = movement_stamp(server);
    const bool quiescent = server.flip_stage() == FlipStage::Idle &&
                           server.lb_stage() == LbStage::Idle &&
                           !server.snapshot().in_progress() && !server.loading();
    if (!rate_window_ms_ || !quiescent || !(movement == rate_window_movement_)) {
        rate_window_ms_ = now_ms;
        rate_window_commands_ = commands;
        rate_window_movement_ = movement;
        previous_subwindow_valid_ = false;
        return false;
    }
    if (now_ms <= rate_window_ms_) return false;
    const uint64_t elapsed_ms = now_ms - rate_window_ms_;
    const uint64_t completed = commands - rate_window_commands_;
    rate = static_cast<double>(completed) * 1000.0 / static_cast<double>(elapsed_ms);
    rate_window_ms_ = now_ms;
    rate_window_commands_ = commands;
    rate_window_movement_ = movement;
    if (!previous_subwindow_valid_) {
        previous_subwindow_rate_ = rate;
        previous_subwindow_valid_ = true;
        return false;
    }
    const double prior_rate = previous_subwindow_rate_;
    stable_pair_delta_ = relative_distance(rate, prior_rate);
    previous_subwindow_rate_ = rate;
    double band = anchor_rate_band_;
    if (configured_band_ > 0) band = static_cast<double>(configured_band_) / 100.0;
    if (band <= 0) band = automatic_rate_band(stable_pair_delta_, rate);
    if (stable_pair_delta_ > band) return false;
    // A stabilized reading represents the pair, not whichever of its two subwindows happened to
    // come last. This avoids anchoring on one edge of otherwise accepted quiet jitter.
    rate = (rate + prior_rate) * 0.5;
    return true;
}

void FlipController::start_maneuver(Server& server, FlipctlTriggerReason reason,
                                    uint64_t now_ms) {
    last_trigger_ = reason;
    triggers_++;
    if (reason == FlipctlTriggerReason::Boot) boot_triggers_++;
    else if (reason == FlipctlTriggerReason::FingerprintShift) fingerprint_triggers_++;
    else if (reason == FlipctlTriggerReason::AnchorRateCollapse) collapse_triggers_++;
    else if (reason == FlipctlTriggerReason::Forced) forced_triggers_++;

    phase_ = Phase::Measuring;
    readings_.clear();
    direction_ = 0;
    step_units_ = 0;
    step_one_reversals_ = 0;
    collapse_streak_ = 0;
    shift_detector_.reset();
    anchor_signature_samples_ = 0;
    anchor_sampling_disabled_ = false;
    maneuver_signature_samples_ = 0;
    anchor_learning_rate_jitter_ = 0;
    anchor_learning_rate_sum_ = 0;
    anchor_learning_rate_min_ = 0;
    anchor_learning_rate_max_ = 0;
    anchor_learning_rate_samples_ = 0;
    retrigger_after_flip_ = false;
    pending_retrigger_ = FlipctlTriggerReason::None;
    // An explicit age rate remains the maneuver rate. Zero means automatic here, derived from the
    // provisioned pool rather than a machine constant. Every owner applies this value to itself.
    signal_sample_rate_.store(
        server.cfg().lb_age_sample_rate ? server.cfg().lb_age_sample_rate
                                        : std::max<uint32_t>(1, server.nthreads()),
        std::memory_order_release);
    for (uint32_t tid = 0; tid < server.nthreads(); tid++) {
        const LoopSignals& signal = server.thread(tid).sig();
        maneuver_start_[tid] = ThreadMeasure{
            signal.ops, signal.busy_ns, signal.iterations, signal.spins};
    }
    rate_window_ms_ = now_ms;
    rate_window_commands_ = total_commands(server);
    rate_window_movement_ = movement_stamp(server);
    previous_subwindow_valid_ = false;
}

void FlipController::record(uint32_t split, double rate) {
    // Preserve every stabilized observation. visited() deliberately treats this as a set when
    // testing termination, while settle() retains the complete evidence for its argmax.
    readings_.push_back(Reading{split, rate});
}

bool FlipController::visited(uint32_t split) const {
    for (const Reading& reading : readings_)
        if (reading.split == split) return true;
    return false;
}

bool FlipController::issue_flip(Server& server, uint32_t coordinator, uint32_t target_io,
                                Phase after_flip) {
    std::string error;
    pending_completed_ = server.flip_completed();
    pending_refused_ = server.flip_refused();
    pending_target_io_ = target_io;
    after_flip_ = after_flip;
    if (!server.flip_begin(target_io, server.nthreads() - target_io, coordinator, error))
        return false;
    phase_ = Phase::WaitingFlip;
    return server.flip_stage() != FlipStage::Idle;
}

bool FlipController::issue_initial_jump(Server& server, uint32_t coordinator, double rate) {
    double role_ops[2] = {};
    double role_busy[2] = {};
    double busiest[2] = {};
    for (uint32_t tid = 0; tid < server.nthreads(); tid++) {
        const LoopSignals& signal = server.thread(tid).sig();
        const ThreadMeasure& start = maneuver_start_[tid];
        const uint64_t ops = signal.ops - start.ops;
        const uint64_t busy = signal.busy_ns - start.busy_ns;
        const uint64_t iterations = signal.iterations - start.iterations;
        const uint64_t spins = signal.spins - start.spins;
        const double spin_fraction = iterations
            ? std::min(1.0, static_cast<double>(spins) / iterations) : 0;
        const double corrected_busy = static_cast<double>(busy) * (1.0 - spin_fraction);
        const Role role = server.thread(tid).role();
        if (role != Role::Ifid && role != Role::Ex) continue;
        const size_t index = role == Role::Ifid ? 0 : 1;
        role_ops[index] += static_cast<double>(ops);
        role_busy[index] += corrected_busy;
        busiest[index] = std::max(busiest[index], corrected_busy);
    }
    // Capacity is unidentifiable without observed work on both sides. Keep measuring instead of
    // inventing a workload prior. The constraint guard deliberately examines each role's busiest
    // thread; idle peers therefore cannot veto a move demanded by the loaded owner.
    if (role_ops[0] <= 0 || role_ops[1] <= 0 ||
        role_busy[0] <= 0 || role_busy[1] <= 0 ||
        busiest[0] <= 0 || busiest[1] <= 0) return false;

    const double cap_io = role_ops[0] / role_busy[0];
    const double cap_ex = role_ops[1] / role_busy[1];
    const double demand_io = 1.0 / cap_io;
    const double demand_ex = 1.0 / cap_ex;
    if (!std::isfinite(demand_io) || !std::isfinite(demand_ex) ||
        demand_io + demand_ex <= 0) return false;

    const uint32_t unit = server.cfg().smt_mode ? 2u : 1u;
    const uint32_t total_units = server.nthreads() / unit;
    const uint32_t now_units = server.role_count(Role::Ifid) / unit;
    uint32_t equal_units = static_cast<uint32_t>(std::llround(
        static_cast<double>(total_units) * demand_io / (demand_io + demand_ex)));
    equal_units = std::clamp(equal_units, 1u, total_units - 1);
    int direction = equal_units > now_units ? 1 : equal_units < now_units ? -1
                                                                    : demand_io >= demand_ex ? 1 : -1;
    if ((now_units == 1 && direction < 0) ||
        (now_units + 1 == total_units && direction > 0)) direction = -direction;
    const uint32_t move = equal_units > now_units ? equal_units - now_units
                                                   : now_units - equal_units;
    const uint32_t overshoot = std::max<uint32_t>(1, move / 2);
    int64_t target_units = static_cast<int64_t>(equal_units) + direction * overshoot;
    target_units = std::clamp<int64_t>(target_units, 1, total_units - 1);
    if (static_cast<uint32_t>(target_units) == now_units) {
        target_units = static_cast<int64_t>(now_units) + direction;
        target_units = std::clamp<int64_t>(target_units, 1, total_units - 1);
    }

    record(now_units * unit, rate);
    previous_rate_ = rate;
    direction_ = direction;
    step_units_ = overshoot;
    if (!issue_flip(server, coordinator, static_cast<uint32_t>(target_units) * unit,
                    Phase::Seeking)) {
        phase_ = Phase::Settling;
        shift_detector_.reset();
        anchor_signature_samples_ = 0;
        maneuver_signature_samples_ = 0;
        anchor_learning_rate_jitter_ = 0;
        anchor_learning_rate_sum_ = 0;
        anchor_learning_rate_min_ = 0;
        anchor_learning_rate_max_ = 0;
        anchor_learning_rate_samples_ = 0;
        rate_window_ms_ = 0;
        previous_subwindow_valid_ = false;
        return false;
    }
    return true;
}

bool FlipController::settle(Server& server, uint32_t coordinator) {
    if (readings_.empty()) {
        phase_ = Phase::Settling;
        shift_detector_.reset();
        anchor_signature_samples_ = 0;
        maneuver_signature_samples_ = 0;
        anchor_learning_rate_jitter_ = 0;
        anchor_learning_rate_sum_ = 0;
        anchor_learning_rate_min_ = 0;
        anchor_learning_rate_max_ = 0;
        anchor_learning_rate_samples_ = 0;
        rate_window_ms_ = 0;
        previous_subwindow_valid_ = false;
        return false;
    }
    const Reading* best = &readings_.front();
    for (const Reading& reading : readings_)
        if (reading.rate > best->rate) best = &reading;
    const uint32_t current = server.role_count(Role::Ifid);
    if (current != best->split) {
        if (issue_flip(server, coordinator, best->split, Phase::Settling)) return true;
    }
    phase_ = Phase::Settling;
    shift_detector_.reset();
    anchor_signature_samples_ = 0;
    maneuver_signature_samples_ = 0;
    anchor_learning_rate_jitter_ = 0;
    anchor_learning_rate_sum_ = 0;
    anchor_learning_rate_min_ = 0;
    anchor_learning_rate_max_ = 0;
    anchor_learning_rate_samples_ = 0;
    rate_window_ms_ = 0;
    previous_subwindow_valid_ = false;
    return false;
}

bool FlipController::seek_after_reading(Server& server, uint32_t coordinator, double rate) {
    const uint32_t unit = server.cfg().smt_mode ? 2u : 1u;
    const uint32_t total_units = server.nthreads() / unit;
    const uint32_t current = server.role_count(Role::Ifid);
    const uint32_t current_units = current / unit;
    record(current, rate);

    const bool improved = rate > previous_rate_;
    if (!improved) {
        direction_ = -direction_;
        if (step_units_ == 1) step_one_reversals_++;
    }
    step_units_ = std::max<uint32_t>(1, step_units_ / 2);
    if (step_units_ == 1 && step_one_reversals_ >= 2)
        return settle(server, coordinator);

    int64_t next_units = static_cast<int64_t>(current_units) + direction_ * step_units_;
    next_units = std::clamp<int64_t>(next_units, 1, total_units - 1);
    if (static_cast<uint32_t>(next_units) == current_units) {
        direction_ = -direction_;
        if (step_units_ == 1) step_one_reversals_++;
        next_units = static_cast<int64_t>(current_units) + direction_ * step_units_;
        next_units = std::clamp<int64_t>(next_units, 1, total_units - 1);
    }
    const uint32_t next = static_cast<uint32_t>(next_units) * unit;
    if (step_units_ == 1 && visited(next)) return settle(server, coordinator);

    previous_rate_ = rate;
    if (!issue_flip(server, coordinator, next, Phase::Seeking))
        return settle(server, coordinator);
    return true;
}

void FlipController::anchor(Server& server, double rate) {
    const uint32_t current = server.role_count(Role::Ifid);
    anchor_io_ = current;
    anchor_ex_ = server.nthreads() - current;
    anchor_rate_ = anchor_learning_rate_samples_
        ? anchor_learning_rate_sum_ / anchor_learning_rate_samples_ : rate;
    if (anchor_learning_rate_samples_ > 1) {
        anchor_learning_rate_jitter_ = std::max(
            anchor_learning_rate_jitter_,
            relative_distance(anchor_learning_rate_min_, anchor_learning_rate_max_));
    }
    anchor_rate_band_ = configured_band_ > 0
        ? static_cast<double>(configured_band_) / 100.0
        : automatic_rate_band(anchor_learning_rate_jitter_, anchor_rate_);
    shift_detector_.anchor();
    signal_sample_rate_.store(0, std::memory_order_release);
    collapse_streak_ = 0;
    phase_ = Phase::Anchored;
    rate_window_ms_ = 0;
    previous_subwindow_valid_ = false;
}

bool FlipController::tick(Server& server, uint64_t now_ms) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!enabled_) return false;

    const bool shifted = sample_fingerprint(server);
    const bool forced = force_requested_.exchange(false, std::memory_order_acq_rel);
    if (phase_ == Phase::BootPending) {
        start_maneuver(server, forced ? FlipctlTriggerReason::Forced
                                     : FlipctlTriggerReason::Boot, now_ms);
        return false;
    }
    if (phase_ == Phase::Anchored && forced) {
        start_maneuver(server, FlipctlTriggerReason::Forced, now_ms);
        return false;
    }
    if (phase_ == Phase::Anchored && shifted) {
        last_shift_distance_ = shift_detector_.last_distance();
        last_shift_band_ = shift_detector_.band();
        start_maneuver(server, FlipctlTriggerReason::FingerprintShift, now_ms);
        return false;
    }
    if (phase_ != Phase::Anchored && phase_ != Phase::BootPending && (forced || shifted)) {
        const FlipctlTriggerReason reason = forced ? FlipctlTriggerReason::Forced
                                                   : FlipctlTriggerReason::FingerprintShift;
        if (phase_ == Phase::WaitingFlip && server.flip_stage() != FlipStage::Idle) {
            // The committed ownership transaction must finish, but none of its throughput samples
            // survive. Restart measurement immediately after Idle instead of overlapping a flip.
            retrigger_after_flip_ = true;
            pending_retrigger_ = reason;
            return false;
        }
        start_maneuver(server, reason, now_ms);
        return false;
    }

    uint32_t coordinator = UINT32_MAX;
    for (uint32_t tid = 0; tid < server.nthreads(); tid++)
        if (server.thread(tid).role() == Role::Ifid) { coordinator = tid; break; }
    if (coordinator == UINT32_MAX) return false;

    if (phase_ == Phase::WaitingFlip) {
        if (server.flip_stage() != FlipStage::Idle) return false;
        if (retrigger_after_flip_) {
            const FlipctlTriggerReason reason = pending_retrigger_;
            start_maneuver(server, reason, now_ms);
            return false;
        }
        const bool completed = server.flip_completed() > pending_completed_ &&
                               server.role_count(Role::Ifid) == pending_target_io_;
        if (completed) {
            phase_ = after_flip_;
            if (phase_ == Phase::Settling) {
                shift_detector_.reset();
                anchor_signature_samples_ = 0;
                maneuver_signature_samples_ = 0;
                anchor_learning_rate_jitter_ = 0;
                anchor_learning_rate_sum_ = 0;
                anchor_learning_rate_min_ = 0;
                anchor_learning_rate_max_ = 0;
                anchor_learning_rate_samples_ = 0;
            }
            rate_window_ms_ = 0;
            previous_subwindow_valid_ = false;
            return false;
        }
        if (server.flip_refused() > pending_refused_) return settle(server, coordinator);
        return false;
    }

    double rate = 0;
    if (phase_ == Phase::Measuring) {
        if (!sample_stabilized_rate(server, now_ms, rate)) return false;
        return issue_initial_jump(server, coordinator, rate);
    }
    if (phase_ == Phase::Seeking) {
        if (!sample_stabilized_rate(server, now_ms, rate)) return false;
        return seek_after_reading(server, coordinator, rate);
    }
    if (phase_ == Phase::Settling) {
        if (!anchor_sampling_disabled_) {
            // Turning maneuver-only age sampling off changes the producer dispatch cost. Learn the
            // anchored fingerprint only after every owner has observed the dormant rate, otherwise
            // the controller detects its own disarm edge as a workload shift.
            signal_sample_rate_.store(0, std::memory_order_release);
            shift_detector_.reset();
            anchor_signature_samples_ = 0;
            maneuver_signature_samples_ = 0;
            anchor_learning_rate_jitter_ = 0;
            anchor_learning_rate_sum_ = 0;
            anchor_learning_rate_min_ = 0;
            anchor_learning_rate_max_ = 0;
            anchor_learning_rate_samples_ = 0;
            anchor_sampling_disabled_ = true;
            rate_window_ms_ = 0;
            previous_subwindow_valid_ = false;
            return false;
        }
        if (!sample_stabilized_rate(server, now_ms, rate)) return false;
        record(server.role_count(Role::Ifid), rate);
        anchor_learning_rate_jitter_ =
            std::max(anchor_learning_rate_jitter_, stable_pair_delta_);
        anchor_learning_rate_sum_ += rate;
        if (!anchor_learning_rate_samples_) {
            anchor_learning_rate_min_ = anchor_learning_rate_max_ = rate;
        } else {
            anchor_learning_rate_min_ = std::min(anchor_learning_rate_min_, rate);
            anchor_learning_rate_max_ = std::max(anchor_learning_rate_max_, rate);
        }
        anchor_learning_rate_samples_++;
        if (server.cfg().flip_work_window &&
            anchor_signature_samples_ < signature_learning_windows_) return false;
        anchor(server, rate);
        return false;
    }
    if (phase_ == Phase::Anchored) {
        if (!sample_stabilized_rate(server, now_ms, rate)) return false;
        if (configured_band_ == 0 || anchor_rate_ <= 0) return false;
        if (rate < anchor_rate_ * (1.0 - anchor_rate_band_)) collapse_streak_++;
        else collapse_streak_ = 0;
        // The same two-sub-window rule that makes a reading comparable supplies "sustained" here.
        if (collapse_streak_ >= 2) {
            start_maneuver(server, FlipctlTriggerReason::AnchorRateCollapse, now_ms);
            return false;
        }
    }
    return false;
}

FlipctlReport FlipController::report() const {
    std::lock_guard<std::mutex> lock(mutex_);
    FlipctlReport report;
    report.state = !enabled_ ? "disabled" : phase_ == Phase::Anchored
        ? "anchored" : "maneuvering";
    report.phase = phase_name(phase_);
    report.last_trigger = reason_name(last_trigger_);
    report.anchor_io = anchor_io_;
    report.anchor_ex = anchor_ex_;
    report.anchor_rate = anchor_rate_;
    report.signature_band = shift_detector_.band();
    report.rate_band = anchor_rate_band_;
    report.triggers = triggers_;
    report.boot_triggers = boot_triggers_;
    report.fingerprint_triggers = fingerprint_triggers_;
    report.collapse_triggers = collapse_triggers_;
    report.forced_triggers = forced_triggers_;
    return report;
}

std::string FlipController::debug_dump() const {
    std::lock_guard<std::mutex> lock(mutex_);
    char head[1024];
    const int n = std::snprintf(
        head, sizeof(head),
        "state=%s\nphase=%s\nanchor=%u:%u\nanchor_rate=%.3f\n"
        "signature_band=%.9f\nsignature_distance=%.9f\nsignature_jitter=%.9f\n"
        "rate_band=%.9f\nlast_shift_distance=%.9f\nlast_shift_band=%.9f\n"
        "last_trigger=%s\ntriggers=%llu boot=%llu fingerprint=%llu "
        "collapse=%llu forced=%llu\npending_io=%u direction=%d step_units=%u\nvisited=",
        !enabled_ ? "disabled" : phase_ == Phase::Anchored ? "anchored" : "maneuvering",
        phase_name(phase_), anchor_io_, anchor_ex_, anchor_rate_, shift_detector_.band(),
        shift_detector_.last_distance(), shift_detector_.jitter(), anchor_rate_band_,
        last_shift_distance_, last_shift_band_, reason_name(last_trigger_),
        static_cast<unsigned long long>(triggers_),
        static_cast<unsigned long long>(boot_triggers_),
        static_cast<unsigned long long>(fingerprint_triggers_),
        static_cast<unsigned long long>(collapse_triggers_),
        static_cast<unsigned long long>(forced_triggers_), pending_target_io_, direction_,
        step_units_);
    std::string out(head, n > 0 ? static_cast<size_t>(n) : 0);
    for (size_t i = 0; i < readings_.size(); i++) {
        if (i) out.push_back(',');
        out += std::to_string(readings_[i].split);
        out.push_back('@');
        out += std::to_string(readings_[i].rate);
    }
    out.push_back('\n');
    return out;
}

}  // namespace tomo
