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

}  // namespace tomo
