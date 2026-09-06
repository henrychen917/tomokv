#include <cmath>
#include <cstdio>
#include <cstdlib>

#include "src/core/flipctl.h"

using namespace tomo;

namespace {

[[noreturn]] void fail(const char* message) {
    std::fprintf(stderr, "flipctl unit: %s\n", message);
    std::exit(1);
}

FlipFingerprintWindow quiet(uint64_t read, uint64_t write, uint64_t deep = 0) {
    FlipFingerprintWindow sample;
    sample.pass_depth = {read + write - deep, 0, deep, 0};
    sample.command_class[static_cast<size_t>(FlipFingerprintClass::Read)] = read;
    sample.command_class[static_cast<size_t>(FlipFingerprintClass::Write)] = write;
    sample.commands = read + write;
    sample.value_bytes = write * 32;
    sample.closed_windows = 1;
    return sample;
}

FlipFingerprintWindow multikey_mix() {
    FlipFingerprintWindow sample;
    sample.pass_depth = {0, 10, 90, 0};
    sample.command_class[static_cast<size_t>(FlipFingerprintClass::MultiRead)] = 80;
    sample.command_class[static_cast<size_t>(FlipFingerprintClass::MultiWrite)] = 20;
    sample.commands = 100;
    sample.multikey_ops = 100;
    sample.multikey_keys = 800;
    sample.value_bytes = 20 * 8 * 64;
    sample.closed_windows = 1;
    return sample;
}

}  // namespace

int main() {
    FlipShiftDetector detector(-1);
    if (detector.observe(quiet(80, 20)) ||
        detector.observe(quiet(79, 21, 1)) ||
        detector.observe(quiet(81, 19)))
        fail("learning windows fired before anchor");
    detector.anchor();
    if (!detector.anchored() || detector.band() <= 0)
        fail("auto band was not learned at anchor");
    const double anchored_band = detector.band();

    // Scripted quiet-state count noise stays inside the signature's own learned band.
    if (detector.observe(quiet(80, 20, 1)) || detector.observe(quiet(79, 21)))
        fail("quiet noise fired the shift detector");
    if (detector.band() != anchored_band)
        fail("post-anchor traffic changed the learned quiet-state band");

    // The same command count changes pipe-depth, command class, keys/op and value bytes together.
    if (!detector.observe(multikey_mix()))
        fail("scripted workload mix change did not fire");

    FlipFingerprintWriter writer;
    writer.configure(4);
    for (unsigned i = 0; i < 4; i++)
        writer.note_command(FlipFingerprintClass::Read, 1, 0);
    writer.finish_parse_pass();
    const FlipFingerprintWindow& published = writer.published();
    if (published.closed_windows != 1 || published.commands != 4 ||
        published.pass_depth[1] != 1)
        fail("work window did not close on commands or bucket its parse pass");

    writer.configure(0);
    if (writer.enabled()) fail("zero work window did not disable sampling");

    // ---- placement policy (flip_policy.h) -----------------------------------------------------
    // THE DEFECT, in the model's own arithmetic. The estimator then in use read io = 82% on 8-key
    // MGET/MSET at 5:3 of 8 threads; the old jump rounded 8 * 0.82 to 7 and overshot. Under work
    // conservation 7:1 is 0.69x the origin (ex saturates first) while 6:2 is +20%: the argmax must
    // be 6, never 7, and 7 must project as a LOSS against 5.
    if (flip_projected_gain(7, 5, 8, 0.82) >= 0) fail("7:1 did not project as a loss at io=0.82");
    {
        FlipDemandWindow w;
        w.add(0.82); w.add(0.82); w.add(0.82);
        const FlipPlacementChoice c = flip_choose_split(5, 8, w, 0.02, 3);
        if (!c.decided || !c.move || c.target_units != 6)
            fail("exact io=0.82 at 5:3 did not choose 6:2");
        if (std::abs(c.gain_mean - 0.2) > 0.01) fail("6:2 gain at io=0.82 is not +20%");
    }
    // A demand share that rounds to a different thread count is NOT a move when the live split
    // wins in throughput space: io=0.63 at 2:2 of 4 rounds to 3, but 3:1 leaves ex with a quarter
    // of the pool for 37% of the work (0.85x). Hold, decided.
    {
        FlipDemandWindow w;
        w.add(0.63); w.add(0.63); w.add(0.63);
        const FlipPlacementChoice c = flip_choose_split(2, 4, w, 0.02, 3);
        if (!c.decided || c.move || c.target_units != 2)
            fail("io=0.63 at 2:2 of 4 did not hold the live split");
    }
    // Single-key symmetry: one command is one task, so io=0.5 makes 4:4 the optimum of 8 and a
    // 5:3 origin a +33% move (8/6 - 1).
    if (std::abs(flip_projected_gain(4, 5, 8, 0.5) - 1.0 / 3.0) > 1e-9)
        fail("4:4 gain over 5:3 at io=0.5 is not 1/3");
    // WINDOW + VARIANCE, sequentially. Three draws spread across a thread's width of io share
    // straddle the bar: undecided, keep sampling. Draws that tighten around the mean resolve it.
    {
        FlipDemandWindow w;
        w.add(0.55); w.add(0.75); w.add(0.65);   // mean 0.65, half-width 0.115
        FlipPlacementChoice c = flip_choose_split(5, 8, w, 0.02, 3);
        if (c.decided) fail("a 0.20-wide window decided a one-thread move");
        for (int i = 0; i < 12; i++) w.add(0.65);
        c = flip_choose_split(5, 8, w, 0.02, 3);
        if (!c.decided) fail("a tightened window did not decide");
        // io=0.65 of 8: 5:3 projects 5/0.65=7.69 vs 3/0.35=8.57 -> io-bound at 7.69; 6:2 gives
        // 9.23 vs 5.71 -> 5.71 (worse). The live split IS the optimum: a hold, not a move.
        if (c.move || c.target_units != 5) fail("io=0.65 at 5:3 did not hold");
    }
    // Fewer than the minimum draws never decide, whatever they say.
    {
        FlipDemandWindow w;
        w.add(0.9); w.add(0.9);
        if (flip_choose_split(5, 8, w, 0.02, 3).decided) fail("two draws decided a move");
    }
    // The bar matters: a real +20% clears 2%, and a required gain above it holds.
    {
        FlipDemandWindow w;
        w.add(0.82); w.add(0.82); w.add(0.82);
        if (!flip_choose_split(5, 8, w, 0.19, 3).move) fail("+20% did not clear a 19% bar");
        const FlipPlacementChoice c = flip_choose_split(5, 8, w, 0.21, 3);
        if (!c.decided || c.move) fail("+20% cleared a 21% bar");
    }
    // BASELINE WANDER. The gate's ramping driver produced origin readings of 4899 and 6001 ops/s
    // at one split, and the boot maneuver then read a rail's +22% as "delivered" and anchored
    // there. Twice that 20% spread is the floor under the maneuver's bands, so the same +22%
    // cannot clear it and the seek reverts to the origin. A still baseline costs nothing.
    if (!(flip_baseline_band(4898.601, 6000.916) > 0.22))
        fail("a 20% baseline spread did not floor the band above the gain it produced");
    if (flip_baseline_band(500000, 500000) != 0) fail("a flat baseline moved the band");
    if (flip_baseline_band(0, 0) != 0) fail("an empty baseline moved the band");
    if (flip_baseline_band(500000, 505000) > 0.021)
        fail("a 1% baseline spread floored the band above 2%");
    // The estimator noise falls as 1/sqrt(n): the same three draws twice over halve nothing, but
    // the half-width shrinks by sqrt(2).
    {
        FlipDemandWindow a, b;
        for (double v : {0.6, 0.7, 0.65}) a.add(v);
        for (double v : {0.6, 0.7, 0.65, 0.6, 0.7, 0.65}) b.add(v);
        if (!(b.half_width() < a.half_width())) fail("more draws did not tighten the window");
    }
    // ---- REVISION 2026-09-06: signal, cost gate, verification window, outcome ------------------
    // THE SIGNAL DEFECT, in the guard's own numbers (single-key 1:1, 2:2 of 4, 40 s window). The
    // io thread booked 16.36 s busy + 0.17 s idle of 39.92 s on CPU; busy shares read io = 0.32 and
    // the model moved to 1:3, which measured 0.48x. Work = wall - idle reads 0.506 and holds.
    {
        const double wall = 40.0e9;
        const double io_work = flip_role_work(wall, 0.17e9) + flip_role_work(wall, 2.40e9);
        const double ex_work = flip_role_work(wall, 2.56e9) + flip_role_work(wall, 1.76e9);
        const double f = io_work / (io_work + ex_work);
        if (std::abs(f - 0.506) > 0.005) fail("wall-idle share of the sk1:1 window is not 0.506");
        FlipDemandWindow w;
        w.add(f); w.add(f); w.add(f);
        const FlipPlacementChoice c = flip_choose_split(2, 4, w, 0.012, 3);
        if (!c.decided || c.move || c.target_units != 2)
            fail("the wall-idle share did not hold 2:2 on the sk1:1 window");
        // The busy share the guard used projected +5.8% for 1:3 -- the round trip it took.
        FlipDemandWindow busy;
        busy.add(0.321); busy.add(0.321); busy.add(0.321);
        const FlipPlacementChoice b = flip_choose_split(2, 4, busy, 0.012, 3);
        if (!b.move || b.target_units != 1) fail("the busy share did not reproduce the 1:3 move");
        if (flip_role_work(0, 5) != 0 || flip_role_work(10, 12) != 0 || flip_role_work(10, -1) != 10)
            fail("flip_role_work bounds");
    }
    // The mk window: io 27.6+3.5 / 25.75+3.24 of 38.1 s, ex 38.7+1.2 / 37.5+1.45 of 40.0 s.
    {
        const double io_work = flip_role_work(38.1e9, 3.50e9) + flip_role_work(38.1e9, 3.24e9);
        const double ex_work = flip_role_work(40.0e9, 1.18e9) + flip_role_work(40.0e9, 1.45e9);
        const double f = io_work / (io_work + ex_work);
        if (std::abs(f - 0.472) > 0.005) fail("wall-idle share of the mk window is not 0.472");
        FlipDemandWindow w;
        w.add(f); w.add(f); w.add(f);
        if (flip_choose_split(2, 4, w, 0.02, 3).move) fail("mk at 2:2 moved on the work share");
    }
    // Naive transfers: every client of a converted thread when io shrinks, the new threads' share
    // when it grows (measured: 131 and 154 of 256 for 2->1 and 3->2 with the re-plan on top).
    if (flip_naive_transfers(256, 2, 1) != 128 || flip_naive_transfers(256, 1, 2) != 128)
        fail("naive transfers 2<->1 of 256 are not 128");
    if (std::abs(flip_naive_transfers(256, 3, 2) - 85.333) > 0.01)
        fail("naive transfers 3->2 of 256 are not 85.3");
    if (flip_naive_transfers(256, 2, 2) != 0 || flip_naive_transfers(0, 2, 1) != 0)
        fail("naive transfers of a no-op or an empty server are not zero");
    // VERIFICATION WINDOW from the origin's own noise: a big gain resolves in one reading, a small
    // one needs more, one too small against the origin's standard error cannot be verified yet,
    // and more origin readings shorten the target's window.
    if (flip_verify_window(0.01, 3, 0.20, 15) != 1) fail("+20% at 1% noise did not verify in one");
    {
        const uint32_t n3 = flip_verify_window(0.01, 3, 0.03, 15);   // (0.75)^2 - 1/3 = 0.229 -> 5
        const uint32_t n5 = flip_verify_window(0.01, 5, 0.03, 15);   // 0.5625 - 0.2 = 0.3625 -> 3
        if (n3 != 5) fail("+3% at 1% noise with 3 origin readings is not 5 target readings");
        if (n5 != 3) fail("+3% at 1% noise with 5 origin readings is not 3 target readings");
        if (!(n5 < n3)) fail("more origin readings did not shorten the target window");
    }
    if (flip_verify_window(0.05, 3, 0.03, 15) != 0)
        fail("a gain below the origin's own standard error verified");
    if (flip_verify_window(0.0, 3, 0.001, 15) != 1) fail("a noiseless origin needs more than one");
    if (flip_verify_window(0.01, 3, 0.0, 15) != 0) fail("a zero gain planned a window");
    // The threshold is two standard errors of the difference, floored.
    if (std::abs(flip_verify_threshold(0.01, 3, 1, 0) - 2 * 0.01 * std::sqrt(1.0 / 3 + 1)) > 1e-12)
        fail("verify threshold is not 2 sigma sqrt(1/n_o + 1/k)");
    if (flip_verify_threshold(0.01, 3, 1, 0.40) != 0.40) fail("threshold floor did not hold");
    // Sequential judgment: early accept, early reject, and the planned-count verdict.
    if (flip_judge(0.30, 0.10, 1, 5) != FlipOutcome::Hit) fail("a clear gain did not accept early");
    if (flip_judge(-0.30, 0.10, 1, 5) != FlipOutcome::Miss) fail("a clear loss did not reject early");
    if (flip_judge(0.05, 0.10, 1, 5) != FlipOutcome::Pending) fail("an unresolved reading decided");
    if (flip_judge(0.05, 0.10, 5, 5) != FlipOutcome::Miss) fail("the planned count did not reject");
    // COST GATE. Units: commands = gain x rate x seconds. The blackout risks the whole ORIGIN
    // throughput on a miss (R0 x T_black), NOT gain x R0 x T_black -- that is what makes the gate
    // asymmetric: benefit/cost ~ gain, so the stationarity a move needs falls as the gain rises.
    // The first flip has no transfer cost (it IS the measurement); it moves as soon as the credited
    // horizon covers the blackout risk. R0 = 236k/s (this rig at 3:1), gain +100%.
    {
        FlipCostModel m;
        if (m.client_cost() != 0 || m.kappa() != 1.0 || std::abs(m.miss_probability() - 0.5) > 1e-12)
            fail("fresh cost model priors");
        const FlipCostVerdict v = flip_cost_gate(1.0, 1.0, 236000, 12.0, 4.0, 0, m.miss_probability(), 1);
        // benefit 1.0 x 236k x (12-4) = 1.888M; cost 0.5 x 236k x 4 = 472k
        if (!v.pays || std::abs(v.benefit - 1.888e6) > 1 || std::abs(v.cost - 472000) > 1)
            fail("first-flip cost gate arithmetic");
        if (std::abs(v.payback_s - (4.0 + 472000.0 / 236000.0)) > 1e-9) fail("payback seconds");
    }
    // ASYMMETRY. A wildly wrong split (a 28:4 boot delivers ~0.53M against ~13M achievable, +2400%)
    // pays almost at the blackout floor: benefit 24 x 0.53M x (T-4), cost 0.5 x 0.53M x 4 = 1.06M,
    // so it pays once (T-4) > 1.06M/(24 x 0.53M) = 0.083 s -> T ~ 4.1 s, one blackout.
    {
        const FlipCostVerdict wrong = flip_cost_gate(24.0, 24.0, 530000, 4.1, 4.0, 0, 0.5, 1);
        if (!wrong.pays) fail("a +2400% wrong-split move did not pay within one blackout");
        if (!(wrong.payback_s < 4.5)) fail("the wrong-split move's payback was not ~one blackout");
    }
    // A marginal move on a HEALTHY split is refused for a long time: +5% off 500k risks the whole
    // 500k during the blackout. benefit 0.05 x 500k x (T-4); cost (first flip) 0.5 x 500k x 4 = 1M.
    // Pays only once (T-4) > 1M / 25k = 40 s -> T > 44 s.
    {
        const FlipCostVerdict no = flip_cost_gate(0.05, 0.05, 500000, 10.0, 4.0, 0, 0.5, 1);
        if (no.pays) fail("a +5% move off a healthy split paid at 10 s of stationarity");
        if (std::abs(no.cost - 1.0e6) > 1e-3) fail("the blackout cost did not risk the origin rate");
        const FlipCostVerdict yes = flip_cost_gate(0.05, 0.05, 500000, 45.0, 4.0, 0, 0.5, 1);
        if (!yes.pays) fail("the +5% move did not pay at 45 s of stationarity");
        // The bar doubles on a miss: at 45 s margin 1 pays, margin 2 does not.
        if (flip_cost_gate(0.05, 0.05, 500000, 45.0, 4.0, 0, 0.5, 2).pays)
            fail("a doubled margin did not refuse the marginal move");
    }
    // The measured transfer cost dominates once a flip has been priced (second move onward).
    {
        FlipCostModel m;
        const double naive = flip_naive_transfers(256, 3, 2);       // 85.33: the converted thread's share
        m.record_flip(250000, 154, naive, 1.0);     // lost 250k commands moving 154 clients
        if (std::abs(m.client_cost() - 250000.0 / 154) > 1e-6) fail("per-client cost");
        if (std::abs(m.reshuffle() - 154 / naive) > 1e-9) fail("re-plan ratio");
        const double transfers = m.predicted_transfers(256, 2, 3);   // naive 85.33 x 1.805 = 154
        if (std::abs(transfers - 154) > 1e-6) fail("predicted transfers did not reproduce the plan");
        const double xfer_cost = m.client_cost() * transfers;        // 250k commands
        // benefit 0.20 x 500k x (T-4); cost 250k x 1.5 + 0.5 x 500k x 4 = 375k + 1M = 1.375M.
        const FlipCostVerdict no = flip_cost_gate(0.20, 0.20, 500000, 10.0, 4.0, xfer_cost, 0.5, 1);
        if (no.pays || std::abs(no.cost - 1.375e6) > 1e-3) fail("+20% move priced with a measured flip");
        const FlipCostVerdict yes = flip_cost_gate(0.20, 0.20, 500000, 30.0, 4.0, xfer_cost, 0.5, 1);
        if (!yes.pays) fail("+20% move did not pay at 30 s with the measured flip cost");
    }
    // The pre-move wait is distance-derived: a huge, tight gain decides at the two-draw floor,
    // while a marginal one stays undecided until the interval tightens (flip_choose_split, above).
    {
        FlipDemandWindow w;
        w.add(0.11); w.add(0.13);   // 28:4-like: ex saturated, io idle -> move toward more ex
        const FlipPlacementChoice c = flip_choose_split(3, 4, w, 0.02, 2);
        if (!c.decided || !c.move) fail("a wildly wrong split did not decide at two draws");
        // A MARGINAL move: at mean io=0.72 of 8, 5:3 -> 6:2 is +2.9% (just over the 2% bar), but the
        // two-draw interval [0.68, 0.76] puts 6:2 at -15% at one end and +20% at the other, so its
        // pessimistic gain is below the bar -- keep sampling (undecided), the wait deriving from
        // how close the split is to the crossover, not from a fixed floor.
        FlipDemandWindow n;
        n.add(0.70); n.add(0.74);
        if (flip_choose_split(5, 8, n, 0.02, 2).decided)
            fail("a marginal two-draw window decided a one-thread move");
    }
    // OUTCOME LOOP. A miss halves the model's credence (kappa 1 -> 0.5: the bar doubles in
    // effect); a hit restores it; over-delivery never buys more than one; the miss rate follows
    // Laplace; an induced hypothesis with a non-positive prediction counts toward the rate only.
    {
        FlipCostModel m;
        m.record_outcome(0.20, 0.0, false);
        if (std::abs(m.kappa() - 0.5) > 1e-12) fail("one miss did not halve kappa");
        if (std::abs(m.miss_probability() - 2.0 / 3.0) > 1e-12) fail("Laplace after one miss");
        m.record_outcome(0.20, 0.20, true);
        if (std::abs(m.kappa() - 0.6667) > 1e-3) fail("hit after miss: kappa 2/3");
        FlipCostModel h;
        h.record_outcome(0.20, 0.50, true);
        if (h.kappa() != 1.0) fail("over-delivery bought credit above one");
        if (std::abs(h.miss_probability() - 1.0 / 3.0) > 1e-12) fail("Laplace after one hit");
        FlipCostModel partial;
        partial.record_outcome(0.20, 0.05, true);   // (0.05 + 0.2) / (0.2 + 0.2)
        if (std::abs(partial.kappa() - 0.625) > 1e-12) fail("partial delivery kappa");
        FlipCostModel induced;
        induced.record_outcome(-0.50, -0.60, false);
        if (induced.kappa() != 1.0 || induced.misses != 1 || induced.moves != 1)
            fail("an induced miss must count toward the rate, not the calibration");
    }
    // INVALIDATION. A miss is voided only when the baseline's own move during the excursion would
    // have turned the verdict: -48% delivered against a baseline that came back +2.2% is still
    // -49%; +5% delivered against a baseline that fell 10% is really +17% and the test was voided.
    if (!(flip_corrected_gain(-0.479, 0.022) < -0.48)) fail("a -48% miss survived a 2% wobble");
    if (!(flip_corrected_gain(0.05, -0.10) > 0.16)) fail("a fallen baseline did not void the miss");
    if (std::abs(flip_corrected_gain(0.10, 0.0) - 0.10) > 1e-12) fail("a still baseline changes the gain");
    // LONG-WINDOW NOISE. The gate driver's six-second triangle (issue intervals x 0.8,0.95,1.1,
    // 1.2,1.05,0.9) puts per-tick rates at 1.25,1.05,0.91,0.83,0.95,1.11 of the mean: sigma ~0.15.
    // Two adjacent readings inside one phase read ~0.05%; the target's +24% is that swing.
    {
        FlipEwVariance ew; ew.configure(30);
        for (int cycle = 0; cycle < 3; cycle++)
            for (double r : {6050.0, 5100.0, 4400.0, 4030.0, 4600.0, 5370.0}) ew.add(r);
        if (!(ew.sigma() > 0.10)) fail("the triangle's long-window sigma did not read the swing");
        // and the verification threshold it floors refuses the +24% that fooled the pair bands
        if (!(flip_verify_threshold(ew.sigma(), 2, 1, 0.02) > 0.24))
            fail("the long-window sigma did not floor the threshold above the driver's swing");
        FlipEwVariance still; still.configure(30);
        for (int k = 0; k < 40; k++) still.add(500000.0 * (1.0 + 0.01 * ((k % 3) - 1)));
        if (!(still.sigma() < 0.02)) fail("a still load read a large long-window sigma");
        if (FlipEwVariance{}.sigma() != 0) fail("an empty long window has a sigma");
    }
    // The rate window: mean, relative sigma and the bracket band the trend guard uses.
    {
        FlipRateWindow r;
        r.add(4898.601); r.add(6000.916);
        if (std::abs(r.mean - 5449.7585) > 1e-3) fail("rate window mean");
        if (!(r.bracket_band() > 0.22)) fail("rate window bracket did not floor the ramp");
        FlipRateWindow still;
        for (double v : {500000.0, 505000.0, 495000.0, 500000.0}) still.add(v);
        if (std::abs(still.sigma() - 0.00816) > 1e-4) fail("rate window relative sigma");
    }
    return 0;
}
