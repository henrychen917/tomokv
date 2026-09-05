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
    // The estimator noise falls as 1/sqrt(n): the same three draws twice over halve nothing, but
    // the half-width shrinks by sqrt(2).
    {
        FlipDemandWindow a, b;
        for (double v : {0.6, 0.7, 0.65}) a.add(v);
        for (double v : {0.6, 0.7, 0.65, 0.6, 0.7, 0.65}) b.add(v);
        if (!(b.half_width() < a.half_width())) fail("more draws did not tighten the window");
    }
    return 0;
}
