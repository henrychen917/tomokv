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

// The io loop's generator (IoLoop::next_random), so the rows below draw what the server draws.
struct XorShift {
    uint64_t state = 0x9E3779B97F4A7C15ull;
    uint64_t next() {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        return state;
    }
};

// The EXHAUSTIVE writer as it shipped before DESIGN-flipfp (every frame fingerprinted, a window
// published once partial_.commands >= W). It is the oracle for the W = 1 equivalence row: the
// sampled writer at W = 1 must publish the same cumulative counters for the same frame stream.
class LegacyWriter {
public:
    void configure(uint32_t commands_per_window) {
        work_window_ = commands_per_window;
        partial_ = {};
        published_ = {};
        pass_frames_ = 0;
    }
    void note_command(FlipFingerprintClass command_class, uint32_t keys, uint64_t value_bytes) {
        partial_.command_class[static_cast<size_t>(command_class)]++;
        partial_.commands++;
        if (keys > 1) {
            partial_.multikey_keys += keys;
            partial_.multikey_ops++;
        }
        partial_.value_bytes += value_bytes;
        pass_frames_++;
    }
    void finish_parse_pass() {
        const uint32_t frames = pass_frames_;
        pass_frames_ = 0;
        if (!frames) return;
        const size_t bucket = frames == 1 ? 0 : frames <= 4 ? 1 : frames <= 16 ? 2 : 3;
        partial_.pass_depth[bucket]++;
        if (partial_.commands < work_window_) return;
        for (size_t i = 0; i < published_.pass_depth.size(); i++)
            published_.pass_depth[i] += partial_.pass_depth[i];
        for (size_t i = 0; i < published_.command_class.size(); i++)
            published_.command_class[i] += partial_.command_class[i];
        published_.commands += partial_.commands;
        published_.multikey_keys += partial_.multikey_keys;
        published_.multikey_ops += partial_.multikey_ops;
        published_.value_bytes += partial_.value_bytes;
        published_.closed_windows++;
        partial_ = {};
    }
    // Flush the open window (no phantom pass) so the cumulative totals are comparable at a cut.
    void flush() {
        for (size_t i = 0; i < published_.pass_depth.size(); i++)
            published_.pass_depth[i] += partial_.pass_depth[i];
        for (size_t i = 0; i < published_.command_class.size(); i++)
            published_.command_class[i] += partial_.command_class[i];
        published_.commands += partial_.commands;
        published_.multikey_keys += partial_.multikey_keys;
        published_.multikey_ops += partial_.multikey_ops;
        published_.value_bytes += partial_.value_bytes;
        partial_ = {};
    }
    const FlipFingerprintWindow& published() const { return published_; }

private:
    uint32_t work_window_ = 0;
    uint32_t pass_frames_ = 0;
    FlipFingerprintWindow partial_{};
    FlipFingerprintWindow published_{};
};

// One frame of a scripted stream: (class, keys, bytes) chosen by a cheap hash of its index so the
// stream has every class, single and multi key, and a spread of value sizes.
struct Frame {
    FlipFingerprintClass cls;
    uint32_t keys;
    uint64_t bytes;
};
Frame scripted_frame(uint64_t index) {
    const uint64_t h = index * 0x9E3779B97F4A7C15ull;
    const uint32_t which = static_cast<uint32_t>((h >> 40) % 7);
    Frame f{static_cast<FlipFingerprintClass>(which), 1, (h >> 20) % 300};
    if (which == 2 || which == 3 || which == 4) f.keys = 2 + static_cast<uint32_t>((h >> 12) % 8);
    return f;
}

bool same_counters(const FlipFingerprintWindow& a, const FlipFingerprintWindow& b) {
    for (size_t i = 0; i < a.pass_depth.size(); i++)
        if (a.pass_depth[i] != b.pass_depth[i]) return false;
    for (size_t i = 0; i < a.command_class.size(); i++)
        if (a.command_class[i] != b.command_class[i]) return false;
    return a.commands == b.commands && a.multikey_keys == b.multikey_keys &&
           a.multikey_ops == b.multikey_ops && a.value_bytes == b.value_bytes;
}

// Drive the sampled writer through `passes` passes of `depth` frames each; `frame_of(pass, i)`
// supplies the frame. Returns the number of sampled passes.
template <class FrameFn>
uint64_t drive(FlipFingerprintWriter& writer, XorShift& rng, uint64_t passes, uint32_t depth,
               FrameFn frame_of) {
    uint64_t sampled = 0;
    for (uint64_t p = 0; p < passes; p++) {
        const bool sampled_pass = writer.pass_sampled();
        for (uint32_t i = 0; i < depth; i++) {
            // The io loop's shell: the body runs only when the gate word says so.
            if (writer.pass_sampled()) {
                const Frame f = frame_of(p, i);
                writer.note_command(f.cls, f.keys, f.bytes);
            }
        }
        if (writer.finish_parse_pass()) {
            if (!sampled_pass) fail("finish_parse_pass reported a sample on an unsampled pass");
            writer.arm(rng.next());
            sampled++;
        } else if (sampled_pass) {
            fail("finish_parse_pass did not report the sampled pass");
        }
    }
    return sampled;
}

}  // namespace

int main() {
    // ---- detector rows (unchanged) --------------------------------------------------------------
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

    // ---- writer: a sampled pass publishes what the exhaustive writer accumulated for it ---------
    FlipFingerprintWriter writer;
    writer.configure(4);
    if (!writer.enabled() || !writer.pass_sampled())
        fail("an armed writer must sample its first pass");
    for (unsigned i = 0; i < 4; i++)
        writer.note_command(FlipFingerprintClass::Read, 1, 0);
    if (!writer.finish_parse_pass()) fail("the sampled first pass did not report itself");
    {
        const FlipFingerprintWindow& published = writer.published();
        if (published.closed_windows != 1 || published.commands != 4 ||
            published.pass_depth[1] != 1)
            fail("sampled pass did not publish its frames and depth bucket");
    }
    // Depth buckets: 1 / <=4 / <=16 / more, exactly the exhaustive writer's.
    {
        FlipFingerprintWriter w;
        const uint32_t depths[4] = {1, 4, 16, 17};
        for (size_t b = 0; b < 4; b++) {
            w.configure(1);
            for (uint32_t i = 0; i < depths[b]; i++) w.note_command(FlipFingerprintClass::Write, 1, 8);
            w.finish_parse_pass();
            for (size_t k = 0; k < 4; k++)
                if (w.published().pass_depth[k] != (k == b ? 1u : 0u)) fail("depth bucket mismatch");
        }
    }
    // An empty sampled pass publishes nothing but still spends its sample.
    {
        FlipFingerprintWriter w;
        w.configure(3);
        if (!w.finish_parse_pass()) fail("empty sampled pass did not report itself");
        if (w.published().closed_windows != 0) fail("empty sampled pass published a window");
        w.arm(0);
        if (!w.pass_sampled()) fail("arm(0) must make the next pass sampled");
    }

    // ---- writer: dark ---------------------------------------------------------------------------
    writer.configure(0);
    if (writer.enabled()) fail("zero work window did not disable sampling");
    if (writer.pass_sampled()) fail("a dark writer's gate word must never read sampled");

    // ---- gap arithmetic: uniform over [0, 2W-2] unsampled passes, mean gap W, W = 1 exhaustive --
    for (uint32_t w : {1u, 2u, 3u, 100u, 1000u}) {
        const uint64_t span = 2ull * w - 1;
        long double sum = 0;
        for (uint64_t r = 0; r < span; r++) {
            const uint32_t gap = FlipFingerprintWriter::gap_for(r, w);
            if (gap > 2 * w - 2) fail("gap outside [0, 2W-2]");
            sum += gap + 1;   // passes between sampled passes, inclusive of the sampled one
        }
        if (std::fabs(static_cast<double>(sum / span) - static_cast<double>(w)) > 1e-9)
            fail("mean distance between sampled passes is not W");
        if (w == 1 && FlipFingerprintWriter::gap_for(0xDEADBEEFull, 1) != 0)
            fail("W = 1 must sample every pass");
    }

    // ---- sampling fraction: 1 in W passes, so 1 in W frames at any depth -----------------------
    {
        XorShift rng;
        for (uint32_t depth : {1u, 32u}) {
            FlipFingerprintWriter w;
            w.configure(100);
            const uint64_t passes = 1'000'000;
            const uint64_t sampled = drive(w, rng, passes, depth,
                                           [](uint64_t, uint32_t) { return Frame{FlipFingerprintClass::Read, 1, 0}; });
            // Renewal count over P passes with gap mean W and gap sd ~57.4: sd ~ sqrt(P) * 57.4 /
            // W^1.5 = 57 sampled passes; accept +-4 sd around P/W.
            if (sampled < 9'770 || sampled > 10'230) fail("sampled pass count is not 1/W of the passes");
            if (w.published().commands != sampled * depth)
                fail("a sampled pass must contribute all of its frames");
            if (w.published().closed_windows != sampled)
                fail("every non-empty sampled pass publishes exactly once");
        }
    }

    // ---- aliasing: classes alternating by pass are sampled in proportion (a stride of W would
    //      see one class only) ------------------------------------------------------------------
    {
        XorShift rng;
        FlipFingerprintWriter w;
        w.configure(2);
        const uint64_t passes = 400'000;
        drive(w, rng, passes, 4, [](uint64_t p, uint32_t) {
            return Frame{p % 2 == 0 ? FlipFingerprintClass::Read : FlipFingerprintClass::Write, 1, 0};
        });
        const FlipFingerprintWindow& pub = w.published();
        const double reads = static_cast<double>(pub.command_class[static_cast<size_t>(FlipFingerprintClass::Read)]);
        const double writes = static_cast<double>(pub.command_class[static_cast<size_t>(FlipFingerprintClass::Write)]);
        const double share = reads / (reads + writes);
        if (share < 0.47 || share > 0.53) fail("period-2 workload was not sampled in proportion");
        // The counter-example the uniform gap exists to avoid: a fixed stride of exactly W.
        uint64_t strided_reads = 0, strided_writes = 0;
        for (uint64_t p = 0; p < passes; p += 2) (p % 2 == 0 ? strided_reads : strided_writes) += 4;
        if (strided_writes != 0) fail("stride model is wrong");
    }

    // ---- W = 1 is the exhaustive writer: identical cumulative counters for the same stream -----
    {
        XorShift rng;
        FlipFingerprintWriter sampled;
        LegacyWriter legacy;
        sampled.configure(1);
        legacy.configure(100);
        uint64_t index = 0;
        for (uint64_t p = 0; p < 20'000; p++) {
            const uint32_t depth = 1 + static_cast<uint32_t>((p * 7919) % 40);
            if (!sampled.pass_sampled()) fail("W = 1 left a pass unsampled");
            for (uint32_t i = 0; i < depth; i++, index++) {
                const Frame f = scripted_frame(index);
                sampled.note_command(f.cls, f.keys, f.bytes);
                legacy.note_command(f.cls, f.keys, f.bytes);
            }
            if (!sampled.finish_parse_pass()) fail("W = 1 pass did not publish");
            sampled.arm(rng.next());
            legacy.finish_parse_pass();
        }
        legacy.flush();
        if (!same_counters(sampled.published(), legacy.published()))
            fail("W = 1 sampled writer diverged from the exhaustive writer");
        if (sampled.published().closed_windows != 20'000)
            fail("W = 1 must publish once per pass");
    }

    // ---- the signature is scale-free; only the quantum floor 4/K moves with the sample count ---
    {
        const FlipSignature full = flip_signature(quiet(80, 20));
        const FlipSignature sampled = flip_signature(quiet(8, 2));
        if (flip_signature_distance(full, sampled) != 0)
            fail("a 1/W sample of a stationary window changed the signature");
        FlipShiftDetector k100(-1), k10(-1);
        k100.observe(quiet(80, 20)); k100.anchor();
        k10.observe(quiet(8, 2)); k10.anchor();
        // jitter is zero after one window, so band = 2 * 4 / K exactly.
        if (std::fabs(k100.band() - 0.08) > 1e-12 || std::fabs(k10.band() - 0.8) > 1e-12)
            fail("quantum floor is not 2 * 4 / commands");
    }
    std::puts("flipctl unit: ok");
    return 0;
}
