#include "flipctl.h"

#include <algorithm>
#include <cmath>
#include <cstdio>

#include "server.h"

namespace tomo {

namespace {

// A real workload must not wait forever merely because its stationary noise never presents a
// quiet absolute-rate band. Thirty seconds is long enough to reject ordinary connection ramps but
// short enough to make automatic placement useful during a container/cell warm-up. The gate below
// converts this duration to controller ticks, so --lb-tick-ms keeps the same wall-clock bound.
constexpr uint64_t kBootMaxDeferralMs = 30'000;

// Anchored drift is deliberately much slower than both the half-weight maneuver EWMA and the
// two-observation surge detector. Only in-band readings reach this learner, and a 64-observation
// time constant lets it follow real long-lived drift without turning ordinary hold jitter into a
// new reference edge.
constexpr double kAnchorRateEwmaAlpha = 1.0 / 64.0;

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
    double class_l1 = 0;
    for (size_t i = 0; i < left.command_class.size(); i++)
        class_l1 += std::abs(left.command_class[i] - right.command_class[i]);
    // Three families, all of them properties of WHAT THE CLIENTS ASKED FOR: the command-class mix,
    // the keys each multi-key command names, and the value bytes each command carries. The
    // probability-vector L1 is in [0,2] and each relative scalar distance is in [0,1], so dividing
    // by the family count keeps the distance normalized to [0,1].
    //
    // pass_depth is NOT here. Measured on the multi-key regime this defect was found in: one
    // controller step from io=5 to io=7 moved the pass-depth distance by 0.0476 -- eight to forty
    // times its own learned trigger band -- while the three mix families moved by 4.2e-7, 0 and
    // 5.4e-7 across the same seconds. Parse-pass occupancy describes how the io threads happened
    // to batch arrivals, which is exactly what the actuator changes when it moves connections
    // between owners. Judging placement with it is the sweep-abandon livelock: the controller
    // re-fires on its own last move. Pipeline-depth changes that matter still reach the controller
    // through the rate detector, which owns volume.
    return (class_l1 * 0.5 +
            unit_normalized_distance(left.keys_per_multikey, right.keys_per_multikey) +
            unit_normalized_distance(left.value_bytes_per_command,
                                     right.value_bytes_per_command)) / 3.0;
}

double flip_signature_pass_distance(const FlipSignature& left, const FlipSignature& right) {
    if (!left.valid || !right.valid) return 0;
    double pass_l1 = 0;
    for (size_t i = 0; i < left.pass_depth.size(); i++)
        pass_l1 += std::abs(left.pass_depth[i] - right.pass_depth[i]);
    return pass_l1 * 0.5;
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
    // SAMPLING SCALE, not counting resolution. Every family in the distance is a proportion or a
    // per-command mean estimated from the N commands this window observed, so two windows drawn
    // from one stationary workload differ by the ESTIMATOR'S OWN NOISE, which falls as 1/sqrt(N)
    // -- never as 1/N. A Bernoulli proportion's standard error is at most 0.5/sqrt(N) and the
    // difference of two independent estimates at most sqrt(2) of that, so 1/sqrt(N) bounds the
    // per-family noise with room for the few terms an L1 sums. The old 1/N quantum understated it
    // by sqrt(N) -- twentyfold at 13.5k commands a window -- which is how a window that merely
    // drew 60 MSETs where the last one drew 50 could read as a workload change. A window that
    // observed no commands supplies no evidence: saturate at one command (quantum 1.0) instead of
    // collapsing to zero, or an anchor cut from an idle window freezes a zero band and judges the
    // first busy wobble as a mix shift. Rate triggers, not fingerprints, own idle->busy.
    const double quantum =
        1.0 / std::sqrt(static_cast<double>(std::max<uint64_t>(smoothed_.commands, 1)));
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
        maneuver_mark_.resize(nthreads);
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
        case FlipctlTriggerReason::AnchorRateSurge: return "anchor-rate-surge";
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
    fingerprint_sampled_this_tick_ = false;
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
    fingerprint_sampled_this_tick_ = true;
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

bool FlipController::sample_rate(Server& server, uint64_t now_ms, double& rate) {
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
    return true;
}

bool FlipController::sample_stabilized_rate(Server& server, uint64_t now_ms, double& rate) {
    if (!sample_rate(server, now_ms, rate)) return false;
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

bool FlipController::sample_anchored_rate(Server& server, uint64_t now_ms, double& rate) {
    if (!sample_rate(server, now_ms, rate)) return false;
    if (!previous_subwindow_valid_) {
        previous_subwindow_rate_ = rate;
        previous_subwindow_valid_ = true;
        return false;
    }
    const double prior_rate = previous_subwindow_rate_;
    previous_subwindow_rate_ = rate;
    stable_pair_delta_ = relative_distance(rate, prior_rate);
    rate = (rate + prior_rate) * 0.5;
    return true;
}

bool FlipController::boot_load_stable(Server& server, uint64_t now_ms) {
    const auto reset_learning = [this]() {
        boot_rate_ewma_ = 0;
        boot_rate_jitter_ = 0;
        boot_rate_slope_ = 0;
        boot_rate_slope_threshold_ = 0;
        boot_previous_ewma_change_ = 0;
        boot_rate_ewma_valid_ = false;
        boot_previous_ewma_change_valid_ = false;
        boot_rate_jitter_valid_ = false;
        boot_work_observed_ = false;
        boot_rate_history_.fill(0);
        boot_rate_samples_ = 0;
        boot_nonidle_ticks_ = 0;
    };
    double rate = 0;
    if (!sample_rate(server, now_ms, rate)) return false;
    const uint64_t tick_ms = std::max<uint32_t>(1, server.flipctl_tick_ms());
    // A health check or controller INFO poll is not a workload worth optimizing. One command per
    // provisioned thread per controller interval is the self-scaled near-idle floor.
    const double idle_rate = static_cast<double>(server.nthreads()) * 1000.0 /
                             static_cast<double>(tick_ms);
    if (rate <= idle_rate) {
        // Forget stale startup work so an idle interval cannot be joined to later traffic and
        // mistaken for either a flat trend or elapsed non-idle deferral.
        reset_learning();
        return false;
    }
    boot_nonidle_ticks_++;
    // A command-rate sample made only of controller observability is not enough when work
    // fingerprinting is available. Once real work closes a window, keep counting all non-idle
    // rate ticks: a workload below one fingerprint window per tick must still reach the cap.
    if (server.cfg().flip_work_window) {
        boot_work_observed_ = boot_work_observed_ || fingerprint_sampled_this_tick_;
        if (!boot_work_observed_) return false;
    }
    const uint64_t max_deferral_ticks = std::max<uint64_t>(
        1, (kBootMaxDeferralMs + tick_ms - 1) / tick_ms);
    if (boot_nonidle_ticks_ >= max_deferral_ticks) return true;

    if (!boot_rate_ewma_valid_) {
        boot_rate_ewma_ = rate;
        boot_rate_ewma_valid_ = true;
        boot_rate_history_[0] = rate;
        boot_rate_samples_ = 1;
        return false;
    }

    const double previous_ewma = boot_rate_ewma_;
    boot_rate_ewma_ = (boot_rate_ewma_ + rate) * 0.5;
    const double scale = std::max(std::abs(previous_ewma), std::abs(boot_rate_ewma_));
    const double ewma_change = scale > 0
        ? (boot_rate_ewma_ - previous_ewma) / scale : 0;
    if (!boot_previous_ewma_change_valid_) {
        boot_previous_ewma_change_ = ewma_change;
        boot_previous_ewma_change_valid_ = true;
        return false;
    }

    // Jitter is variation in the EWMA's adjacent movement. A monotone connection ramp therefore
    // remains directional drift instead of widening its own stability band and blessing itself.
    const double jitter_sample = std::abs(ewma_change - boot_previous_ewma_change_);
    boot_rate_jitter_ = boot_rate_jitter_valid_
        ? (boot_rate_jitter_ + jitter_sample) * 0.5 : jitter_sample;
    boot_rate_jitter_valid_ = true;
    boot_previous_ewma_change_ = ewma_change;

    const uint32_t history_slot = boot_rate_samples_ % kBootTrendTicks;
    const bool have_trend = boot_rate_samples_ >= kBootTrendTicks;
    const double trend_origin = boot_rate_history_[history_slot];
    boot_rate_history_[history_slot] = boot_rate_ewma_;
    boot_rate_samples_++;
    if (!have_trend) return false;

    const double trend_scale = std::max(std::abs(trend_origin), std::abs(boot_rate_ewma_));
    boot_rate_slope_ = trend_scale > 0
        ? std::abs(boot_rate_ewma_ - trend_origin) /
              (trend_scale * static_cast<double>(kBootTrendTicks))
        : 0;
    // Adjacent EWMA-change jitter estimates the noise in one slope observation. Its standard
    // error over the N-tick trend supplies a workload-derived threshold; one command per tick is
    // retained only as a measurement-quantum floor. A monotone ramp has slope but little change
    // jitter, while stationary rate noise cancels across the longer trend.
    const double command_rate_quantum = 1000.0 / static_cast<double>(tick_ms);
    const double relative_quantum = command_rate_quantum / boot_rate_ewma_;
    boot_rate_slope_threshold_ =
        2.0 * std::max(boot_rate_jitter_, relative_quantum) /
        std::sqrt(static_cast<double>(kBootTrendTicks));
    return boot_rate_slope_ <= boot_rate_slope_threshold_;
}

void FlipController::start_maneuver(Server& server, FlipctlTriggerReason reason,
                                    uint64_t now_ms) {
    last_trigger_ = reason;
    triggers_++;
    if (reason == FlipctlTriggerReason::Boot) boot_triggers_++;
    else if (reason == FlipctlTriggerReason::FingerprintShift) fingerprint_triggers_++;
    else if (reason == FlipctlTriggerReason::AnchorRateSurge) rate_surge_triggers_++;
    else if (reason == FlipctlTriggerReason::AnchorRateCollapse) rate_collapse_triggers_++;
    else if (reason == FlipctlTriggerReason::Forced) forced_triggers_++;

    phase_ = Phase::Measuring;
    // Where this maneuver started. If the search comes back here, the trigger that started it
    // demanded a move and the measurements refused one: that excursion carries no placement
    // information and anchor() turns it into a band floor.
    maneuver_origin_io_ = server.role_count(Role::Ifid);
    shift_streak_ = 0;
    readings_.clear();
    direction_ = 0;
    step_units_ = 0;
    step_one_reversals_ = 0;
    surge_streak_ = 0;
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
    model_io_frac_history_.fill(0);
    model_io_frac_samples_ = 0;
    model_io_frac_noise_ = 0;
    for (uint32_t tid = 0; tid < server.nthreads(); tid++) {
        const LoopSignals& signal = server.thread(tid).sig();
        maneuver_start_[tid] = ThreadMeasure{
            signal.ops, signal.busy_ns, signal.iterations, signal.spins};
        maneuver_mark_[tid] = maneuver_start_[tid];
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

// Every path that stops seeking lands here: leave the split alone, forget the maneuver's learning
// state, and let Settling cut a fresh anchor from wherever the server is now.
void FlipController::enter_settling() {
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
}

bool FlipController::issue_flip(Server& server, uint32_t coordinator, uint32_t target_io,
                                Phase after_flip) {
    // A flip onto the live split is a no-op that flip_begin nevertheless counts as completed, and
    // issue_flip would then report failure because the stage never left Idle -- an ownership
    // transaction in the counters that the controller does not believe it made. The seek arithmetic
    // does not produce one today (every wall case reverses direction first), so this is a guard,
    // not the cause of the multi-key thrash; but the controller must be structurally incapable of
    // spending a FLIP on the split it is already running.
    if (target_io == server.role_count(Role::Ifid)) return false;
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

// One windowed observation of how the two roles split the server's real work. Returns false while
// the window carries no evidence; the caller keeps measuring rather than inventing a prior.
bool FlipController::sample_role_demand(Server& server, double& io_frac) {
    double role_ops[2] = {};
    double role_busy[2] = {};
    double busiest[2] = {};
    for (uint32_t tid = 0; tid < server.nthreads(); tid++) {
        const LoopSignals& signal = server.thread(tid).sig();
        const ThreadMeasure& start = maneuver_mark_[tid];
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
    for (uint32_t tid = 0; tid < server.nthreads(); tid++) {
        const LoopSignals& signal = server.thread(tid).sig();
        maneuver_mark_[tid] = ThreadMeasure{
            signal.ops, signal.busy_ns, signal.iterations, signal.spins};
    }
    // Capacity is unidentifiable without observed work on both sides. Keep measuring instead of
    // inventing a workload prior. The constraint guard deliberately examines each role's busiest
    // thread; idle peers therefore cannot veto a move demanded by the loaded owner.
    if (role_ops[0] <= 0 || role_ops[1] <= 0 ||
        role_busy[0] <= 0 || role_busy[1] <= 0 ||
        busiest[0] <= 0 || busiest[1] <= 0) return false;

    // WORK CONSERVATION, WITH BOTH OPERANDS THE SAME QUANTITY. The throughput-optimal split gives
    // each role the thread fraction its PER-COMMAND service cost demands,
    //     n_io* / N = c_io / (c_io + c_ex),   c_role = (busy ns that role spent) / (commands run),
    // and the command count is the same divisor on both sides, so it cancels: the estimator is the
    // corrected busy-time share, and it never has to name what an "op" is.
    //
    // It used to divide each role's busy time by that role's OWN op counter, and an op is not the
    // same object on the two sides. The io loop counts one per parsed command -- io_loop.h says so
    // where it scatters: "one public command, not one count per shard task" -- while the ex loop
    // adds one per shard task it executes. Measured here on 8-key MGET/MSET at pipeline 32, live
    // split 5:3 on eight threads: the ex role logged 7.576 ops per command, so its per-op cost read
    // 397ns against io's 1762ns and the model concluded io deserved 82% of the pool. The same
    // window's per-COMMAND costs were io 1762ns and ex 3010ns -- ex does the MORE work -- so io
    // deserves 37%. The controller duly flipped 5:3 to 7:1, which measures 0.29M ops/s against
    // 0.95M at 5:3 and 1.32M at 4:4, found it worse, and walked back to the split it started from:
    // the round trip the operator saw as three flips, 993 moved connections and an unchanged
    // target. On single-key traffic both forms give 0.3293 to four decimals, because there one
    // command is exactly one ex task -- which is why this is a forty-fold multi-key defect and a
    // half-percent single-key one.
    const double demand_io = role_busy[0];
    const double demand_ex = role_busy[1];
    if (!std::isfinite(demand_io) || !std::isfinite(demand_ex) ||
        demand_io + demand_ex <= 0) return false;

    io_frac = demand_io / (demand_io + demand_ex);
    return true;
}

bool FlipController::issue_initial_jump(Server& server, uint32_t coordinator, double rate) {
    double io_frac = 0;
    if (!sample_role_demand(server, io_frac)) return false;
    // ACCURACY FROM THE WINDOW, NOT FROM ONE SAMPLE. One demand observation is not an estimate, it
    // is a draw, and a draw taken while connections are still arriving reads almost pure io. Hold a
    // sliding window of three and judge the mean against the window's own spread; the server keeps
    // serving at its current split while the window fills.
    model_io_frac_history_[model_io_frac_samples_ % kModelWindow] = io_frac;
    model_io_frac_samples_++;
    if (model_io_frac_samples_ < kModelWindow) return false;
    double sum = 0, low = model_io_frac_history_[0], high = model_io_frac_history_[0];
    for (double sample : model_io_frac_history_) {
        sum += sample;
        low = std::min(low, sample);
        high = std::max(high, sample);
    }
    const double mean_frac = sum / kModelWindow;
    const double noise = high - low;
    model_io_frac_ = mean_frac;
    model_io_frac_noise_ = noise;

    const uint32_t unit = server.cfg().smt_mode ? 2u : 1u;
    const uint32_t total_units = server.nthreads() / unit;
    const uint32_t now_units = server.role_count(Role::Ifid) / unit;
    const double now_frac = static_cast<double>(now_units) / total_units;
    uint32_t equal_units = static_cast<uint32_t>(std::llround(
        static_cast<double>(total_units) * mean_frac));
    equal_units = std::clamp(equal_units, 1u, total_units - 1);
    model_equal_io_ = equal_units * unit;
    // Move only when the windowed demand estimate separates from the live split by more than the
    // window's own spread. Six boots of one stationary 8-key workload measured single-draw io
    // fractions of 0.549, 0.579, 0.605, 0.613, 0.679 and 0.750 -- a 0.20 range where an eighth of
    // the pool is 0.125, so one draw can name three different splits, and a draw taken during the
    // connection ramp reads 0.95. Acting on one draw is how a controller pays two quiesces and a
    // full connection reshuffle for a difference it cannot resolve. This is the same evidence rule
    // the rate and mix triggers already use, applied to the placement model.
    if (equal_units == now_units || std::abs(mean_frac - now_frac) <= noise) {
        // The measured optimum IS the split we are running, or is indistinguishable from it. There
        // is nothing to search for, and the probe the seek would otherwise take is a guaranteed
        // round trip -- one flip out to a split the model has already rejected and one flip back.
        // Record the reading and anchor here; the rate and mix detectors keep watching.
        model_holds_++;
        record(now_units * unit, rate);
        enter_settling();
        return false;
    }
    // equal_units is inside the walls and differs from now_units, so the direction points from the
    // live split toward the measured optimum and every step below stays in range.
    const int direction = equal_units > now_units ? 1 : -1;
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
        enter_settling();
        return false;
    }
    return true;
}

bool FlipController::settle(Server& server, uint32_t coordinator) {
    if (readings_.empty()) {
        enter_settling();
        return false;
    }
    const Reading* best = &readings_.front();
    for (const Reading& reading : readings_)
        if (reading.rate > best->rate) best = &reading;
    const uint32_t current = server.role_count(Role::Ifid);
    if (current != best->split) {
        if (issue_flip(server, coordinator, best->split, Phase::Settling)) return true;
    }
    enter_settling();
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
    anchor_rate_jitter_ = anchor_learning_rate_jitter_;
    // THE NULL-MANEUVER RULE, CLOSED ON THE OUTCOME. A maneuver that ends on the split it started
    // from moved ownership, paid every quiesce and changed nothing -- thrash by this project's own
    // definition. The trigger that started it was therefore not wrong about the workload, it was
    // wrong that the workload's move was worth a maneuver, so what has to grow is the EVIDENCE the
    // next such excursion must present, not the size it must reach. Double the confirming control
    // passes the responsible detector needs; halve back toward the floor whenever a maneuver
    // actually moves the split, so a workload that really is drifting stays cheap to follow.
    //
    // The rejected alternative was widening that detector's band by twice the excursion it just
    // proved uninformative. Measured: a paced 8-key -> single-key change scores distance 0.630 on
    // a metric whose maximum is 1.0, so one null result set a floor of 1.26 and the fingerprint
    // detector could never fire again at any workload -- a self-inflicted `--flip-auto-band 0`.
    // A threshold learned from an excursion can exceed every excursion; a window cannot.
    const bool null_maneuver = current == maneuver_origin_io_ &&
        (last_trigger_ == FlipctlTriggerReason::FingerprintShift ||
         last_trigger_ == FlipctlTriggerReason::AnchorRateSurge ||
         last_trigger_ == FlipctlTriggerReason::AnchorRateCollapse);
    const bool moved_split = current != maneuver_origin_io_;
    const uint32_t confirmation_cap =
        std::max(kMinConfirmations, signature_learning_windows_);
    uint32_t* responsible = last_trigger_ == FlipctlTriggerReason::FingerprintShift
        ? &shift_confirmations_
        : (last_trigger_ == FlipctlTriggerReason::AnchorRateSurge ||
           last_trigger_ == FlipctlTriggerReason::AnchorRateCollapse)
              ? &rate_confirmations_ : nullptr;
    if (null_maneuver) null_maneuvers_++;
    if (responsible) {
        if (null_maneuver)
            *responsible = std::min(confirmation_cap, *responsible * 2);
        else if (moved_split)
            *responsible = std::max(kMinConfirmations, *responsible / 2);
    }
    anchor_rate_band_ = configured_band_ > 0
        ? static_cast<double>(configured_band_) / 100.0
        : automatic_rate_band(anchor_rate_jitter_, anchor_rate_);
    anchor_rate_band_floor_ = anchor_rate_band_;
    shift_streak_ = 0;
    shift_detector_.anchor();
    signal_sample_rate_.store(0, std::memory_order_release);
    surge_streak_ = 0;
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
        if (forced) start_maneuver(server, FlipctlTriggerReason::Forced, now_ms);
        else if (boot_load_stable(server, now_ms))
            start_maneuver(server, FlipctlTriggerReason::Boot, now_ms);
        return false;
    }
    if (phase_ == Phase::Anchored && forced) {
        start_maneuver(server, FlipctlTriggerReason::Forced, now_ms);
        return false;
    }
    // Mid-maneuver, ONLY a forced trigger may interrupt. The maneuver's own split changes move
    // the pass-depth signature, so honoring `shifted` here lets the actuator re-trigger itself
    // forever (the sweep-abandon law: a signal the actuator moves cannot police it). The
    // detector re-baselines at anchor; a real workload change re-fires from the anchored state.
    if (phase_ != Phase::Anchored && phase_ != Phase::BootPending && forced) {
        const FlipctlTriggerReason reason = FlipctlTriggerReason::Forced;
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
        // A fingerprint shift asks for the same evidence a rate trigger already asks for: TWO
        // consecutive out-of-band observations. One window can sit outside the band on ordinary
        // sampling luck; a workload that actually changed keeps presenting the new mix. Only
        // windows that closed real work vote -- a tick where no owner published is not evidence
        // either way, so it neither adds to the streak nor clears it.
        if (fingerprint_sampled_this_tick_) shift_streak_ = shifted ? shift_streak_ + 1 : 0;
        const bool sustained_shift = shift_streak_ >= shift_confirmations_;
        if (!sample_anchored_rate(server, now_ms, rate)) {
            if (sustained_shift) {
                last_shift_distance_ = shift_detector_.last_distance();
                last_shift_band_ = shift_detector_.band();
                start_maneuver(server, FlipctlTriggerReason::FingerprintShift, now_ms);
            }
            return false;
        }
        const double reference = anchor_rate_;
        const double band = anchor_rate_band_;
        if (configured_band_ != 0 && reference > 0 &&
            rate > reference * (1.0 + band)) {
            surge_streak_++;
            collapse_streak_ = 0;
        } else if (configured_band_ != 0 && reference > 0 &&
                   rate < reference * (1.0 - band)) {
            collapse_streak_++;
            surge_streak_ = 0;
        } else {
            surge_streak_ = 0;
            collapse_streak_ = 0;
        }
        // The same two-sub-window rule that makes a reading comparable supplies "sustained" here.
        if (surge_streak_ >= rate_confirmations_ ||
            collapse_streak_ >= rate_confirmations_) {
            const FlipctlTriggerReason reason = surge_streak_ >= 2
                ? FlipctlTriggerReason::AnchorRateSurge
                : FlipctlTriggerReason::AnchorRateCollapse;
            start_maneuver(server, reason, now_ms);
            return false;
        }

        // Pass-depth is rate-sensitive: a genuine volume step can cross both detectors on its
        // first tick. Preserve that first rate observation until the required second one instead
        // of letting the fingerprint preempt it and re-anchor at the new rate. A pure mix shift,
        // with no pending rate evidence, still starts immediately.
        if (sustained_shift && !surge_streak_ && !collapse_streak_) {
            last_shift_distance_ = shift_detector_.last_distance();
            last_shift_band_ = shift_detector_.band();
            start_maneuver(server, FlipctlTriggerReason::FingerprintShift, now_ms);
            return false;
        }

        // An out-of-band observation is trigger evidence, not baseline evidence. In particular,
        // do not let the first observation of the two-sample trigger pull the reference toward a
        // possible step or widen/narrow its band before the confirming observation arrives.
        if (surge_streak_ || collapse_streak_) return false;

        // This sample was wholly within an anchored, redistribution-free, in-band window. Fold its
        // innovation into a very slow live reference only after judging it against the prior
        // reference. Maneuver and pending-trigger windows never reach this branch.
        const double jitter_sample = relative_distance(rate, reference);
        anchor_rate_jitter_ +=
            (jitter_sample - anchor_rate_jitter_) * kAnchorRateEwmaAlpha;
        anchor_rate_ += (rate - anchor_rate_) * kAnchorRateEwmaAlpha;
        if (configured_band_ > 0) {
            anchor_rate_band_ = static_cast<double>(configured_band_) / 100.0;
        } else if (configured_band_ < 0) {
            // The final settling windows define the minimum quiet jitter that this anchor already
            // proved it needs. Live learning may widen the band, but must never erase that floor.
            anchor_rate_band_ = std::max(
                anchor_rate_band_floor_,
                automatic_rate_band(anchor_rate_jitter_, anchor_rate_));
        }
    }
    return false;
}

FlipctlReport FlipController::report() const {
    std::lock_guard<std::mutex> lock(mutex_);
    FlipctlReport report;
    report.state = !enabled_ ? "disabled" : phase_ == Phase::BootPending
        ? "awaiting-load-stability" : phase_ == Phase::Anchored ? "anchored" : "maneuvering";
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
    report.rate_surge_triggers = rate_surge_triggers_;
    report.rate_collapse_triggers = rate_collapse_triggers_;
    report.forced_triggers = forced_triggers_;
    report.null_maneuvers = null_maneuvers_;
    report.model_holds = model_holds_;
    report.shift_confirmations = shift_confirmations_;
    report.rate_confirmations = rate_confirmations_;
    return report;
}

std::string FlipController::debug_dump() const {
    std::lock_guard<std::mutex> lock(mutex_);
    char head[1024];
    const int n = std::snprintf(
        head, sizeof(head),
        "state=%s\nphase=%s\nanchor=%u:%u\nanchor_rate=%.3f\n"
        "signature_band=%.9f\nsignature_distance=%.9f\nsignature_jitter=%.9f\n"
        "rate_band=%.9f\nanchor_rate_jitter=%.9f\n"
        "last_shift_distance=%.9f\nlast_shift_band=%.9f\n"
        "boot_rate_ewma=%.3f\nboot_rate_jitter=%.9f\nboot_rate_slope=%.9f\n"
        "boot_rate_slope_threshold=%.9f\nboot_nonidle_ticks=%u\n"
        "model_io_frac=%.6f\nmodel_io_frac_noise=%.6f\nmodel_equal_io=%u\n"
        "model_holds=%llu\n"
        "shift_confirmations=%u rate_confirmations=%u\n"
        "shift_streak=%u null_maneuvers=%llu maneuver_origin_io=%u\n"
        "last_trigger=%s\ntriggers=%llu boot=%llu fingerprint=%llu "
        "rate_surge=%llu rate_collapse=%llu forced=%llu\n"
        "pending_io=%u direction=%d step_units=%u\n",
        !enabled_ ? "disabled" : phase_ == Phase::BootPending ? "awaiting-load-stability"
            : phase_ == Phase::Anchored ? "anchored" : "maneuvering",
        phase_name(phase_), anchor_io_, anchor_ex_, anchor_rate_, shift_detector_.band(),
        shift_detector_.last_distance(), shift_detector_.jitter(), anchor_rate_band_,
        anchor_rate_jitter_, last_shift_distance_, last_shift_band_, boot_rate_ewma_,
        boot_rate_jitter_, boot_rate_slope_, boot_rate_slope_threshold_, boot_nonidle_ticks_,
        model_io_frac_, model_io_frac_noise_, model_equal_io_,
        static_cast<unsigned long long>(model_holds_),
        shift_confirmations_, rate_confirmations_, shift_streak_,
        static_cast<unsigned long long>(null_maneuvers_), maneuver_origin_io_,
        reason_name(last_trigger_),
        static_cast<unsigned long long>(triggers_),
        static_cast<unsigned long long>(boot_triggers_),
        static_cast<unsigned long long>(fingerprint_triggers_),
        static_cast<unsigned long long>(rate_surge_triggers_),
        static_cast<unsigned long long>(rate_collapse_triggers_),
        static_cast<unsigned long long>(forced_triggers_), pending_target_io_, direction_,
        step_units_);
    std::string out(head, n > 0 ? static_cast<size_t>(n) : 0);
    // Cold signature detail. The scalar `signature_distance` above says a shift happened; these
    // two vectors and the four family contributions say WHICH input moved, which is the only way
    // to tell a real mix change from one feature family's own quantization noise.
    const auto emit_signature = [&out](const char* tag, const FlipSignature& sig) {
        char line[512];
        const int m = std::snprintf(
            line, sizeof(line),
            "%s valid=%d cmds=%llu pass=%.6f,%.6f,%.6f,%.6f "
            "class=%.6f,%.6f,%.6f,%.6f,%.6f,%.6f,%.6f kpm=%.6f vbpc=%.6f\n",
            tag, sig.valid ? 1 : 0, static_cast<unsigned long long>(sig.commands),
            sig.pass_depth[0], sig.pass_depth[1], sig.pass_depth[2], sig.pass_depth[3],
            sig.command_class[0], sig.command_class[1], sig.command_class[2],
            sig.command_class[3], sig.command_class[4], sig.command_class[5],
            sig.command_class[6], sig.keys_per_multikey, sig.value_bytes_per_command);
        out.append(line, m > 0 ? static_cast<size_t>(m) : 0);
    };
    emit_signature("sig_now", shift_detector_.smoothed());
    emit_signature("sig_anchor", shift_detector_.anchored_signature());
    {
        const FlipSignature& now = shift_detector_.smoothed();
        const FlipSignature& anc = shift_detector_.anchored_signature();
        double pass_l1 = 0, class_l1 = 0;
        if (now.valid && anc.valid) {
            for (size_t i = 0; i < now.pass_depth.size(); i++)
                pass_l1 += std::abs(now.pass_depth[i] - anc.pass_depth[i]);
            for (size_t i = 0; i < now.command_class.size(); i++)
                class_l1 += std::abs(now.command_class[i] - anc.command_class[i]);
        }
        const double kpm = (now.valid && anc.valid)
            ? unit_normalized_distance(now.keys_per_multikey, anc.keys_per_multikey) : 0;
        const double vbpc = (now.valid && anc.valid)
            ? unit_normalized_distance(now.value_bytes_per_command,
                                       anc.value_bytes_per_command) : 0;
        char line[256];
        const int m = std::snprintf(
            line, sizeof(line),
            "dist_parts pass=%.9f class=%.9f kpm=%.9f vbpc=%.9f\n",
            pass_l1 * 0.5, class_l1 * 0.5 / 3.0, kpm / 3.0, vbpc / 3.0);
        out.append(line, m > 0 ? static_cast<size_t>(m) : 0);
    }
    out += "visited=";
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
