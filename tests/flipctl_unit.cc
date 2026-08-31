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
    return 0;
}
