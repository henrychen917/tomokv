// flip_policy.h -- the FLIP controller's placement POLICY: when a role move is worth making.
//
// Pure arithmetic, no Server, so tests/flipctl_unit.cc can run it against scripted numbers. The
// controller (flipctl.cc) feeds it one demand observation per stabilized throughput reading and
// asks one question: is there a split whose PROJECTED gain over the live split clears the
// evidence bar? Three rules, one invariant -- a move must be able to pay for itself:
//
//   1. WINDOW + VARIANCE. One demand draw is not an estimate. Observations accumulate (Welford)
//      and every projection is evaluated across the window's own confidence interval; the
//      decision is SEQUENTIAL: move as soon as the pessimistic end of the interval clears the bar,
//      hold as soon as the optimistic end cannot, keep sampling in between. Accuracy comes from
//      the window, never from a denser sample (user-lb-never-inhibits-hot-path). The server keeps
//      serving at its current split for as long as that takes; sampling costs no throughput.
//
//   2. COST GATE, in throughput space. The old jump rounded N * io_frac to a thread count and
//      overshot it. Measured on 8-key MGET/MSET at 5:3 (8 threads) with the estimator then in
//      use (io 82%): round(8 * 0.82) = 7, overshoot to 8 clamped 7 -- a split this very model
//      rates at 0.69x the origin (ex, 1 of 8 threads, carries 18% of the work and saturates
//      first). The gate evaluates every split under work conservation,
//          R(s) ~ min(s / f, (N - s) / (1 - f)),   f = io share of busy time,
//      picks the argmax, and moves only if its gain over the live split -- at the PESSIMISTIC end
//      of the window's interval -- exceeds the required gain. The required gain is the
//      controller's own throughput noise band (a gain the seek could not verify cannot pay for
//      the flip it costs) scaled by the outcome margin below. No machine constants: N is the live
//      pool, f and its interval are measured, the band is learned.
//
//   3. OUTCOME LOOP. After the jump the controller measures the target against the origin's
//      stabilized rate; not better by the band => straight back to the origin, and the margin the
//      model must clear next time doubles (a projection that did not deliver was wrong about
//      the WORKLOAD, and more samples of a biased estimator only make it more confidently wrong
//      -- the bar has to rise, not the window). A move that delivered halves the margin back
//      toward one band. The margin is capped where required gain would exceed 100%: past that
//      the model could never fire again on any workload, which is a silent `--flip-auto 0`.
//
// REVISION 2026-09-06 (the actuator redesign). The three rules above were the placement policy's
// first cut; this revision gives each of them the quantity it was missing, in units:
//
//   SIGNAL. Role demand is measured as WORK = wall - idle per thread (flip_role_work), not as the
//      loops' busy_ns. The io loop closes its busy span before ring_.submit_and_reap(), so the
//      io_uring_enter syscall -- the kernel moving the bytes, which is io work -- was booked as
//      neither busy nor idle: 23.5 s of a 40 s window on one single-key io thread. The busy share
//      read io = 0.32 on a workload whose work share is 0.51, and the model moved 2:2 -> 1:3
//      (measured -52%) and came back. idle_ns is the one quantity both loops book faithfully.
//
//   COST GATE, in commands over the horizon the workload has demonstrated (flip_cost_gate). A move
//      must pay for itself: kappa g_low R0 (T_stat - T_black) > margin [C_xfer (1 + P_miss) +
//      P_miss kappa g_mean R0 T_black]. T_stat is how long the workload has held still, T_black
//      how long the controller is blind after the flip (flip + settle + planned readings), C_xfer
//      = measured commands lost per transferred client x predicted transfers, P_miss the model's
//      own miss rate (Laplace). First flip: the transfer cost is unknown and stays zero -- that
//      flip is the measurement.
//
//   WINDOW FROM VARIANCE (flip_verify_window / flip_verify_threshold). The post-move window is as
//      long as the origin's own noise says it has to be to resolve the predicted gain at two
//      standard errors, and no longer; verification is sequential (accept early, reject early).
//
//   OUTCOME LOOP (FlipCostModel::record_outcome). Every move is a hypothesis with a predicted
//      delta. A miss reverts and doubles the margin (sign); kappa = (sum delivered + gbar) /
//      (sum predicted + gbar) learns the model's MAGNITUDE bias with the credence of one delivered
//      move of average size as its only prior, and never exceeds one.

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

    void reset() { samples = 0; mean = 0; m2 = 0; last = 0; }
    void add(double io_frac) {
        last = io_frac;
        samples++;
        const double delta = io_frac - mean;
        mean += delta / samples;
        m2 += delta * (io_frac - mean);
    }
    double stdev() const {
        return samples > 1 ? std::sqrt(std::max(0.0, m2 / (samples - 1))) : 0;
    }
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
    bool decided = false;      // false: keep sampling
    bool move = false;         // decided && the target clears the bar at the pessimistic end
    uint32_t target_units = 0; // argmax of the mean projection (== now when nothing beats it)
    double gain_mean = 0;      // projected gain of target at the window mean
    double gain_low = 0;       // ... of target at the pessimistic end of the interval
    double gain_high = 0;      // best gain ANY split reaches anywhere in the interval
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
inline FlipPlacementChoice flip_choose_split(uint32_t now_units, uint32_t total_units,
                                             const FlipDemandWindow& window,
                                             double required_gain, uint32_t min_samples) {
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
        if (gain > best_mean) { best_mean = gain; choice.target_units = s; }
        for (double f : points)
            optimistic = std::max(optimistic, flip_projected_gain(s, now_units, total_units, f));
    }
    choice.gain_high = optimistic;
    if (choice.target_units != now_units) {
        choice.gain_mean = best_mean;
        choice.gain_low = best_mean;
        for (double f : points)
            choice.gain_low = std::min(
                choice.gain_low, flip_projected_gain(choice.target_units, now_units, total_units, f));
        if (choice.gain_low > required_gain) {
            choice.decided = true;
            choice.move = true;
            return choice;
        }
    }
    if (optimistic <= required_gain) choice.decided = true;  // no split could pay for a flip
    return choice;
}

// ---- REVISION 2026-09-06: signal, cost gate, verification window, outcome ---------------------

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

    void reset() { samples = 0; mean = 0; m2 = 0; lo = 0; hi = 0; }
    void add(double rate) {
        if (!samples) lo = hi = rate;
        else { lo = std::min(lo, rate); hi = std::max(hi, rate); }
        samples++;
        const double delta = rate - mean;
        mean += delta / samples;
        m2 += delta * (rate - mean);
    }
    double stdev() const {
        return samples > 1 ? std::sqrt(std::max(0.0, m2 / (samples - 1))) : 0;
    }
    // Relative noise of ONE reading.
    double sigma() const { return mean > 0 ? stdev() / mean : 0; }
    // Twice the observed spread: the trend guard (flip_baseline_band).
    double bracket_band() const { return flip_baseline_band(lo, hi); }
};

// Connections the flip planner must move for a role change, before its weighted re-plan
// reshuffles more: every client of a converted io thread when io shrinks, the new threads' share
// when it grows. Measured against the plan's real count through FlipCostModel::reshuffle().
inline double flip_naive_transfers(uint32_t clients, uint32_t io_before, uint32_t io_after) {
    if (!clients || !io_before || !io_after || io_before == io_after) return 0;
    const uint32_t delta = io_before > io_after ? io_before - io_after : io_after - io_before;
    return static_cast<double>(clients) * delta / static_cast<double>(std::max(io_before, io_after));
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
    if (n_origin && k && sigma > 0)
        two_se = 2.0 * sigma * std::sqrt(1.0 / n_origin + 1.0 / k);
    return std::max(two_se, std::max(0.0, floor));
}

enum class FlipOutcome : uint8_t { Pending = 0, Hit, Miss };

// Sequential verdict on a hypothesis after `k` of `planned` target readings.
inline FlipOutcome flip_judge(double delivered, double threshold, uint32_t k, uint32_t planned) {
    if (delivered > threshold) return FlipOutcome::Hit;
    if (delivered < -threshold) return FlipOutcome::Miss;   // clearly worse: do not sit here
    return k >= std::max<uint32_t>(1, planned) ? FlipOutcome::Miss : FlipOutcome::Pending;
}

// The cost model: what every flip so far cost and what every move so far delivered.
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

// THE COST GATE. Gains are kappa-scaled by the caller. A gain is credited only after the outcome
// can be judged (T_stat - T_black); the cost is the flip, the revert with probability P_miss, and
// the blackout at a wrong split -- during which a wrong move loses about what a right one would
// have gained -- all times the outcome margin.
inline FlipCostVerdict flip_cost_gate(double gain_low, double gain_mean, double rate,
                                      double stationary_s, double blackout_s,
                                      double transfer_cost, double p_miss, uint32_t margin) {
    FlipCostVerdict v;
    v.blackout_s = std::max(0.0, blackout_s);
    v.horizon_s = std::max(0.0, stationary_s);
    v.transfer_cost = std::max(0.0, transfer_cost);
    const double m = std::max<uint32_t>(1, margin);
    const double credited = std::max(0.0, v.horizon_s - v.blackout_s);
    v.benefit = std::max(0.0, gain_low) * std::max(0.0, rate) * credited;
    v.cost = m * (v.transfer_cost * (1.0 + p_miss) +
                  p_miss * std::max(0.0, gain_mean) * std::max(0.0, rate) * v.blackout_s);
    v.payback_s = (gain_low > 0 && rate > 0)
        ? v.blackout_s + v.cost / (gain_low * rate) : INFINITY;
    v.pays = gain_low > 0 && v.benefit > v.cost;
    return v;
}

}  // namespace tomo
