// Arithmetic for FLIP demand, placement, verification and transfer-cost decisions. Included by
// flipctl.h; these helpers have no Server dependency. FlipController supplies serialized state
// and one demand observation per stabilized reading; tests can supply independent windows. The
// helpers do not publish shared state or perform ownership transfers.
//
// Demand windows use Welford mean/variance. The chooser tests each split under work
// conservation: R(s) ~ min(s/f, (N-s)/(1-f)), with f the IO share of wall-minus-idle work and
// SMT pairs counted as units. It moves when the chosen target's pessimistic gain clears the
// required bar, holds when no split's optimistic gain does, and samples otherwise. Current
// placement keeps serving during this observation; changing sample density is not part of the
// decision.
//
// The controller scales its learned throughput band by an outcome margin. Verification compares
// origin and target readings at two standard errors; a miss returns to the origin and increases
// the margin, while a delivered move reduces it. The caller bounds the required gain at 100%.
//
// The cost gate uses commands over the demonstrated stationary horizon: benefit = g_low * R0 *
// max(0, T_stat-T_black); cost = margin * [C_xfer * (1+P_miss) + P_miss * R0 * T_black]. Gains
// are calibrated before this call. T_black includes flip, settle and planned readings. C_xfer
// is the observed commands lost per transferred client times predicted transfers. Unknown
// transfer cost starts at zero so the first flip can measure it. P_miss uses Laplace's rule.
//
// FlipCostModel learns magnitude bias from raw predicted and delivered gains. Its kappa has the
// credence of one average-size delivered move and is clamped to [0,1]; a non-positive
// prediction counts toward miss frequency but supplies no calibration evidence.

#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>

namespace tomo {

// Running mean and variance of io-share observations (Welford).
struct FlipDemandWindow {
    uint32_t samples = 0;
    double mean = 0;
    double m2 = 0;
    double last = 0;

    void reset() {
        samples = 0;
        mean = 0;
        m2 = 0;
        last = 0;
    }
    void add(double io_frac) {
        last = io_frac;
        samples++;
        const double delta = io_frac - mean;
        mean += delta / samples;
        m2 += delta * (io_frac - mean);
    }
    double stdev() const { return samples > 1 ? std::sqrt(std::max(0.0, m2 / (samples - 1))) : 0; }
    // Two standard errors of the mean: the interval the projections are evaluated across.
    double half_width() const {
        return samples > 1 ? 2.0 * stdev() / std::sqrt(static_cast<double>(samples)) : 0;
    }
};

// The band a MEASURED gain has to beat before the outcome loop may believe it. A maneuver
// compares a rate window taken before its flip with one taken after, so the comparison can only
// resolve a difference larger than the baseline's own movement between those two windows: `lo`
// and `hi` bracket the stabilized readings the controller took at the origin split while it was
// deciding. Twice the spread, the same 2x-the-observed-jitter convention every other band in the
// controller uses. Zero readings, one reading, or a flat baseline give zero, and the caller's
// learned/typed band stands.
inline double flip_baseline_band(double lo, double hi) {
    if (!(lo > 0) || !(hi >= lo)) return 0;
    const double mid = 0.5 * (lo + hi);
    return mid > 0 ? 2.0 * (hi - lo) / mid : 0;
}

// Relative throughput of a split under work conservation. Units, not threads, so an SMT pair
// counts once. Zero for an impossible split.
inline double flip_projected_rate(uint32_t io_units, uint32_t total_units, double io_frac) {
    if (!io_units || io_units >= total_units) return 0;
    const double f = std::clamp(io_frac, 1e-9, 1.0 - 1e-9);
    const double io_side = static_cast<double>(io_units) / f;
    const double ex_side = static_cast<double>(total_units - io_units) / (1.0 - f);
    return std::min(io_side, ex_side);
}

// Projected relative gain of `candidate` over `now` at demand share `io_frac`.
inline double flip_projected_gain(uint32_t candidate, uint32_t now, uint32_t total_units,
                                  double io_frac) {
    const double base = flip_projected_rate(now, total_units, io_frac);
    if (base <= 0) return 0;
    return flip_projected_rate(candidate, total_units, io_frac) / base - 1.0;
}

struct FlipPlacementChoice {
    bool decided = false;       // false: keep sampling
    bool move = false;          // decided && the target clears the bar at the pessimistic end
    uint32_t target_units = 0;  // argmax of the mean projection (== now when nothing beats it)
    double gain_mean = 0;       // projected gain of target at the window mean
    double gain_low = 0;        // ... of target at the pessimistic end of the interval
    double gain_high = 0;       // best gain ANY split reaches anywhere in the interval
    double io_frac_low = 0;
    double io_frac_high = 0;
};

// The sequential decision. `required_gain` is the bar (band x margin, capped at 1.0 by the
// caller); `min_samples` is the fewest observations that give a variance at all.
//   MOVE  when the target's gain at the PESSIMISTIC end of the interval clears the bar;
//   HOLD  when NO split clears the bar even at the OPTIMISTIC end -- nothing left to learn;
//   else keep sampling: the interval still admits a split worth a flip, and a wider window costs
//   nothing while the server keeps serving at its live split. Note that "the live split is the
//   optimum at the mean" is NOT a hold on its own: three draws spread across a thread's width of
//   io share can put a +16% split at one end and a +20% split at the other.
//
// THE PRE-MOVE WAIT DERIVES FROM THE DISTANCE, with no separate rule. min_samples is the fewest
// draws that admit a variance (two); from there the sequential test decides as soon as the
// PESSIMISTIC end of the 2-SE interval clears the bar. A wildly wrong split reads a gain so far
// above the bar that even the pessimistic end of a two-draw interval clears it -- it moves at two
// readings. A marginal split's pessimistic end sits below the bar until the interval tightens over
// many draws. Same test, opposite waits, and the outcome loop (not a long pre-move window) is what
// catches a two-draw move that turns out wrong.
inline FlipPlacementChoice flip_choose_split(uint32_t now_units, uint32_t total_units,
                                             const FlipDemandWindow& window, double required_gain,
                                             uint32_t min_samples) {
    FlipPlacementChoice choice;
    choice.target_units = now_units;
    if (total_units < 2 || !now_units || now_units >= total_units) {
        choice.decided = true;  // nothing to choose between
        return choice;
    }
    if (window.samples < std::max<uint32_t>(2, min_samples)) return choice;
    const double hw = window.half_width();
    choice.io_frac_low = std::clamp(window.mean - hw, 1e-9, 1.0 - 1e-9);
    choice.io_frac_high = std::clamp(window.mean + hw, 1e-9, 1.0 - 1e-9);
    const double points[3] = {choice.io_frac_low, window.mean, choice.io_frac_high};

    double best_mean = 0;
    double optimistic = 0;  // the best any split does anywhere in the interval
    for (uint32_t s = 1; s < total_units; s++) {
        if (s == now_units) continue;
        const double gain = flip_projected_gain(s, now_units, total_units, window.mean);
        if (gain > best_mean) {
            best_mean = gain;
            choice.target_units = s;
        }
        for (double f : points)
            optimistic = std::max(optimistic, flip_projected_gain(s, now_units, total_units, f));
    }
    choice.gain_high = optimistic;
    if (choice.target_units != now_units) {
        choice.gain_mean = best_mean;
        choice.gain_low = best_mean;
        for (double f : points)
            choice.gain_low =
                std::min(choice.gain_low,
                         flip_projected_gain(choice.target_units, now_units, total_units, f));
        if (choice.gain_low > required_gain) {
            choice.decided = true;
            choice.move = true;
            return choice;
        }
    }
    if (optimistic <= required_gain) choice.decided = true;  // no split could pay for a flip
    return choice;
}

// Work accounting, transfer cost, verification windows and outcomes.

// Work a thread did over a window: everything it did not book as idle. `wall_ns` is the window the
// controller's own clock measured; `idle_ns` the loop's booked idle over that window.
inline double flip_role_work(double wall_ns, double idle_ns) {
    if (!(wall_ns > 0)) return 0;
    return std::max(0.0, wall_ns - std::max(0.0, idle_ns));
}

// Running mean/variance/bracket of throughput readings (Welford), the noise model behind the
// verification window and the outcome threshold.
struct FlipRateWindow {
    uint32_t samples = 0;
    double mean = 0;
    double m2 = 0;
    double lo = 0;
    double hi = 0;

    void reset() {
        samples = 0;
        mean = 0;
        m2 = 0;
        lo = 0;
        hi = 0;
    }
    void add(double rate) {
        if (!samples)
            lo = hi = rate;
        else {
            lo = std::min(lo, rate);
            hi = std::max(hi, rate);
        }
        samples++;
        const double delta = rate - mean;
        mean += delta / samples;
        m2 += delta * (rate - mean);
    }
    double stdev() const { return samples > 1 ? std::sqrt(std::max(0.0, m2 / (samples - 1))) : 0; }
    // Relative noise of ONE reading.
    double sigma() const { return mean > 0 ? stdev() / mean : 0; }
    // Twice the observed spread: the trend guard (flip_baseline_band).
    double bracket_band() const { return flip_baseline_band(lo, hi); }
};

// Rate-noise state owned by the caller; production accesses it under FlipController's mutex.
// The exponentially weighted variance uses every eligible tick's second relative difference,
// rel2 = (r_t - 2*r_{t-1} + r_{t-2}) / r_{t-1}. Stabilized pairs select quiet observations and
// can miss periodic movement. A linear ramp has zero second difference, a level shift leaves
// two decaying impulses, and a periodic swing keeps contributing. Samples at/below the caller's
// idle floor break the chain; a second difference above 100% resets the variance as a regime
// change. The configured time constant is the boot-deferral bound in ticks. Warm-up uses a
// running average to dilute early impulses. The controller resets this state when its measured
// flip completes.
struct FlipEwVariance {
    uint32_t samples = 0;  // second differences folded in
    double alpha = 0;
    double var = 0;    // of rel2
    double prev1 = 0;  // r_{t-1}, 0 = none
    double prev2 = 0;  // r_{t-2}, 0 = none

    void configure(uint32_t time_constant_ticks) {
        alpha = 1.0 / static_cast<double>(std::max<uint32_t>(1, time_constant_ticks));
    }
    void reset() {
        samples = 0;
        var = 0;
        prev1 = prev2 = 0;
    }
    // `floor` is the rate below which a tick is idle, not load (the caller's idle rate).
    void add(double rate, double floor = 0) {
        if (!(rate > floor)) {
            prev1 = prev2 = 0;
            return;
        }  // not evidence; the chain restarts
        if (prev1 > 0 && prev2 > 0) {
            const double rel2 = (rate - 2.0 * prev1 + prev2) / prev1;
            if (std::abs(rel2) > 1.0) {
                // A level change of more than the level itself: a new regime, not noise.
                samples = 0;
                var = 0;
            } else {
                const double a = alpha > 0 ? alpha : 1.0;
                const double w = std::max(a, 1.0 / static_cast<double>(samples + 1));
                var += w * (rel2 * rel2 - var);
                samples++;
            }
        }
        prev2 = prev1;
        prev1 = rate;
    }
    // Report the RMS second difference as the per-reading noise scale. For white noise it
    // overestimates sigma by sqrt(6); retaining that factor also covers periodic swings that
    // stabilized-pair bands can miss. Return zero until two differences contribute.
    double sigma() const { return samples > 1 ? std::sqrt(std::max(0.0, var)) : 0; }
};

// Caller-owned one-sided bound for nonnegative fingerprint distances. It combines a decaying
// peak with mean + 2 standard deviations; a distance is already a difference with no negative
// side or trend to remove. FlipShiftDetector supplies adjacent distances before anchoring and
// in-band anchor distances afterward, under its caller's serialization.
struct FlipEwBound {
    uint32_t samples = 0;
    double alpha = 0;
    double mean = 0;
    double var = 0;

    void configure(uint32_t time_constant_windows) {
        alpha = 1.0 / static_cast<double>(std::max<uint32_t>(1, time_constant_windows));
    }
    void reset() {
        samples = 0;
        mean = 0;
        var = 0;
        peak = 0;
    }
    void add(double value) {
        if (!(value >= 0)) return;
        const double a = alpha > 0 ? alpha : 1.0;
        const double w = std::max(a, 1.0 / static_cast<double>(samples + 1));
        const double delta = value - mean;
        mean += w * delta;
        var += w * (delta * delta - var);
        // Decay toward the mean first, then admit the new observation: a peak set by one window
        // fades over a time constant, a peak the signal keeps reaching does not.
        peak += a * (mean - peak);
        peak = std::max(peak, value);
        samples++;
    }
    // The smoothed signature's anchor-distance excursions are correlated and can persist across
    // windows. Preserve a peak that decays toward the mean, in addition to mean + 2 standard
    // deviations, so sustained excursions influence the band and quiet periods can lower it.
    double peak = 0;
    double bound() const {
        return samples > 1 ? std::max(peak, mean + 2.0 * std::sqrt(std::max(0.0, var))) : 0;
    }
};

// Connections the flip planner must move for a role change, before its weighted re-plan
// reshuffles more: every client of a converted io thread when io shrinks, the new threads' share
// when it grows. Measured against the plan's real count through FlipCostModel::reshuffle().
inline double flip_naive_transfers(uint32_t clients, uint32_t io_before, uint32_t io_after) {
    if (!clients || !io_before || !io_after || io_before == io_after) return 0;
    const uint32_t delta = io_before > io_after ? io_before - io_after : io_after - io_before;
    return static_cast<double>(clients) * delta /
           static_cast<double>(std::max(io_before, io_after));
}

// Readings the target needs so that a predicted gain is resolvable at two standard errors against
// an origin measured with `n_origin` readings of relative noise `sigma`:
//     2 sigma sqrt(1/n_o + 1/n_t) <= gain / 2   =>   1/n_t <= (gain / 4 sigma)^2 - 1/n_o.
// Zero means the origin itself is not yet measured precisely enough (or the window would exceed
// `cap`): keep sampling the origin, which is free. A noiseless origin resolves in one reading.
inline uint32_t flip_verify_window(double sigma, uint32_t n_origin, double gain, uint32_t cap) {
    if (!(gain > 0) || n_origin < 2 || !cap) return 0;
    if (!(sigma > 0)) return 1;
    const double quarter = gain / (4.0 * sigma);
    const double bracket = quarter * quarter - 1.0 / static_cast<double>(n_origin);
    if (bracket <= 0) return 0;
    const double n = std::ceil(1.0 / bracket);
    if (n > static_cast<double>(cap)) return 0;
    return static_cast<uint32_t>(std::max(1.0, n));
}

// The gain a target's mean over `k` readings must show over the origin's mean over `n_origin`
// readings: two standard errors of the difference, never below the caller's floor (the origin's
// own bracket, the learned band, a typed band).
inline double flip_verify_threshold(double sigma, uint32_t n_origin, uint32_t k, double floor) {
    double two_se = 0;
    if (n_origin && k && sigma > 0) two_se = 2.0 * sigma * std::sqrt(1.0 / n_origin + 1.0 / k);
    return std::max(two_se, std::max(0.0, floor));
}

// Re-express a target's delivered gain against the origin after the return flip, accounting for
// baseline_shift during the excursion. The caller invalidates a miss when this corrected gain
// would have cleared the threshold; baseline movement alone does not invalidate it. If the new
// baseline factor is nonpositive, return the uncorrected gain.
inline double flip_corrected_gain(double delivered, double baseline_shift) {
    if (!(1.0 + baseline_shift > 0)) return delivered;
    return (1.0 + delivered) / (1.0 + baseline_shift) - 1.0;
}

// A refinement step must exceed the previous projection's observed error as well as the noise
// bar. Return predicted minus delivered, floored at zero. The capacity model's sharp optimum
// need not match the real curve near its peak; an improvement smaller than this error does not
// justify another transfer or crossing that peak. The bar comes from the outcome, without a
// fixed margin.
inline double flip_refine_bar(double previous_predicted, double previous_delivered) {
    return std::max(0.0, previous_predicted - previous_delivered);
}

enum class FlipOutcome : uint8_t { Pending = 0, Hit, Miss };

// Sequential verdict on a hypothesis after `k` of `planned` target readings.
inline FlipOutcome flip_judge(double delivered, double threshold, uint32_t k, uint32_t planned) {
    if (delivered > threshold) return FlipOutcome::Hit;
    if (delivered < -threshold) return FlipOutcome::Miss;  // clearly worse: do not sit here
    return k >= std::max<uint32_t>(1, planned) ? FlipOutcome::Miss : FlipOutcome::Pending;
}

// The cost model: what every flip so far cost and what every move so far delivered.
// Contract: Caller-serialized cumulative cost and outcome state; FlipController owns the
// production instance under its mutex. Updates allocate nothing and publish nothing across
// threads. Negative cost inputs are floored, non-positive predictions omit calibration, and the
// accessors provide explicit zero-history defaults rather than waiting for samples.
struct FlipCostModel {
    // Every flip, out or back, measured by the controller: commands the server did not serve while
    // the flip was in flight, connections the planner moved, the naive count it had to move, and
    // how many controller ticks it took.
    uint64_t flips = 0;
    double lost_sum = 0;
    double moved_sum = 0;
    double naive_sum = 0;
    double ticks_sum = 0;
    // Every move's outcome: predicted gain, delivered gain (a miss delivers zero).
    uint32_t moves = 0;
    uint32_t misses = 0;
    double predicted_sum = 0;
    double delivered_sum = 0;
    // DEBUG FLIPCTL COST: a typed per-client cost stands in for the measured one (< 0 = none).
    double injected_client_cost = -1;

    void record_flip(double lost, double moved, double naive, double ticks) {
        flips++;
        lost_sum += std::max(0.0, lost);
        moved_sum += std::max(0.0, moved);
        naive_sum += std::max(0.0, naive);
        ticks_sum += std::max(1.0, ticks);
    }
    // `predicted` in the model's units (before kappa); a non-positive prediction (an induced
    // hypothesis) counts toward the miss rate but not toward the calibration.
    void record_outcome(double predicted, double delivered, bool hit) {
        moves++;
        if (!hit) misses++;
        if (predicted > 0) {
            predicted_sum += predicted;
            delivered_sum += std::clamp(hit ? delivered : 0.0, 0.0, predicted);
        }
    }
    // Commands lost per transferred client. Zero until a flip has been measured.
    double client_cost() const {
        if (injected_client_cost >= 0) return injected_client_cost;
        return moved_sum > 0 ? lost_sum / moved_sum : 0;
    }
    // How many more connections the weighted re-plan moves than the role change requires.
    double reshuffle() const {
        return (naive_sum > 0 && moved_sum > 0) ? moved_sum / naive_sum : 1.0;
    }
    // Controller ticks a flip keeps the server in transition. One tick until measured: the
    // controller cannot see a flip complete sooner than its next look.
    double flip_ticks() const { return flips ? ticks_sum / flips : 1.0; }
    // Laplace's rule: (misses + 1) / (moves + 2). One half before any move.
    double miss_probability() const {
        return (static_cast<double>(misses) + 1.0) / (static_cast<double>(moves) + 2.0);
    }
    // Calibration of the model's projected MAGNITUDE. The prior is one delivered move of the
    // model's own average predicted size; a miss halves the credence, a hit restores it; never
    // above one. Without any calibrated move the model is taken at its word.
    double kappa() const {
        if (predicted_sum <= 0) return 1.0;
        const double gbar = predicted_sum / static_cast<double>(std::max<uint32_t>(1, moves));
        return std::clamp((delivered_sum + gbar) / (predicted_sum + gbar), 0.0, 1.0);
    }
    double predicted_transfers(uint32_t clients, uint32_t io_before, uint32_t io_after) const {
        return flip_naive_transfers(clients, io_before, io_after) * reshuffle();
    }
};

struct FlipCostVerdict {
    double benefit = 0;        // commands gained over the credited part of the horizon
    double cost = 0;           // commands the move is expected to cost, margin applied
    double transfer_cost = 0;  // commands: client cost x predicted transfers (one flip)
    double blackout_s = 0;     // seconds the controller is blind after the flip
    double horizon_s = 0;      // seconds of stationarity the workload has demonstrated
    double payback_s = 0;      // stationarity at which this move would start paying
    bool pays = false;
};

// The cost gate credits kappa-scaled gain over the demonstrated stationary horizon minus blind
// time. Cost includes a flip, a possible revert and the entire origin rate at risk during a
// wrong split's blackout: a bad target can serve nothing. Pricing blackout as gain_mean*rate
// would scale cost and benefit together, erasing the intended dependence on gain. Larger
// projected gains therefore require less stationary time to pay for the move; no fixed wait is
// added.
inline FlipCostVerdict flip_cost_gate(double gain_low, double gain_mean, double rate,
                                      double stationary_s, double blackout_s, double transfer_cost,
                                      double p_miss, uint32_t margin) {
    (void)gain_mean;  // diagnostic input; blackout cost uses the full origin rate
    FlipCostVerdict v;
    v.blackout_s = std::max(0.0, blackout_s);
    v.horizon_s = std::max(0.0, stationary_s);
    v.transfer_cost = std::max(0.0, transfer_cost);
    const double m = std::max<uint32_t>(1, margin);
    const double r = std::max(0.0, rate);
    const double credited = std::max(0.0, v.horizon_s - v.blackout_s);
    v.benefit = std::max(0.0, gain_low) * r * credited;
    v.cost = m * (v.transfer_cost * (1.0 + p_miss) + p_miss * r * v.blackout_s);
    v.payback_s = (gain_low > 0 && r > 0) ? v.blackout_s + v.cost / (gain_low * r) : INFINITY;
    v.pays = gain_low > 0 && v.benefit > v.cost;
    return v;
}

}  // namespace tomo
