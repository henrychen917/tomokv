// Serverless command-accounting regression. A failed local read leaves a suffix for the owner;
// the successful prefix must count GET and MGET commands exactly once, including mixed chunks.
// Null suffix entries make selecting an uncompleted command a hard failure under ASAN/UBSAN.
// Negative control: passing the whole mask's MGET population instead of the prefix's count must
// fail this oracle. No listener, worker, ring, or command handler is started by this fixture.
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include "src/core/thread.h"

namespace {
using namespace tomo;

void require(bool ok, const char* message) {
    if (ok) return;
    std::fprintf(stderr, "coherence accounting: FAIL: %s\n", message);
    std::exit(1);
}
void unused_handler(Shard&, Op&) { require(false, "executed a command handler"); }

CommandSpec make_spec(const char* name, uint16_t id) {
    CommandSpec spec(name, 2, -1, CmdFlags::Readonly | CmdFlags::ReadLocalEligible,
                     unused_handler, 1, -1, 1, unused_handler);
    spec.id = id;
    return spec;
}

void check_prefix(uint32_t mask, uint32_t completed, uint32_t registry_size) {
    auto get = make_spec("GET", 3);
    auto mget = make_spec("MGET", 19);
    ThreadCtx counts;
    counts.init_command_counts(registry_size);
    // Nonzero prior state proves each publication adds instead of overwriting.
    counts.note_command(get.id);
    counts.note_command(get.id);
    counts.note_command(mget.id);
    std::array<Op, 32> ops;
    std::array<Op*, 32> prefix{};
    uint32_t gets = 0, mgets = 0;
    for (uint32_t i = 0; i < ops.size(); i++) {
        ops[i].spec = (mask & (uint32_t{1} << i)) ? &mget : &get;
        if (i >= completed) continue;
        prefix[i] = &ops[i];
        if (ops[i].spec->id == get.id) gets++;
        else mgets++;
    }
    counts.note_local_read_commands(prefix.data(), completed, mask, mgets);
    require(counts.total_commands() == 3 + completed, "prefix total");
    require(counts.command_calls(get.id) == (get.id < registry_size ? 2 + gets : 0),
            "GET prefix count");
    require(counts.command_calls(mget.id) == (mget.id < registry_size ? 1 + mgets : 0),
            "MGET prefix count counts commands, not keys");
    for (uint32_t id = 0; id < registry_size; id++)
        if (id != get.id && id != mget.id)
            require(counts.command_calls(id) == 0, "unrelated command changed");

    // Model the untouched owner-accounting path after demotion. The final histogram must equal
    // the original 32 commands, irrespective of where the local prefix ended.
    uint32_t all_gets = 0, all_mgets = 0;
    for (uint32_t i = 0; i < ops.size(); i++) {
        if (i >= completed) counts.note_command(ops[i].spec->id);
        if (ops[i].spec->id == get.id) all_gets++;
        else all_mgets++;
    }
    require(counts.total_commands() == 35, "suffix was lost or counted twice");
    require(counts.command_calls(get.id) == (get.id < registry_size ? 2 + all_gets : 0),
            "GET local plus owner count");
    require(counts.command_calls(mget.id) == (mget.id < registry_size ? 1 + all_mgets : 0),
            "MGET local plus owner count");
}
}  // namespace

int main() {
    std::vector<uint32_t> masks{0, UINT32_MAX, 0xaaaaaaaa, 0x55555555};
    for (uint32_t bit = 0; bit < 32; bit++) {
        masks.push_back(uint32_t{1} << bit);
        masks.push_back(~(uint32_t{1} << bit));
    }
    // Complete every possible prefix of pure, alternating, and isolated-class chunks. The two
    // short registries exercise note_command's existing invalid-ID/disabled-histogram semantics.
    uint32_t cases = 0;
    for (uint32_t registry_size : {0u, 4u, 32u})
        for (uint32_t mask : masks)
            for (uint32_t completed = 0; completed <= 32; completed++) {
                check_prefix(mask, completed, registry_size);
                cases++;
            }
    ThreadCtx empty;
    empty.note_local_read_commands(nullptr, 0, UINT32_MAX, 0);
    require(empty.total_commands() == 0, "empty prefix did work");
    std::printf("coherence accounting: PASS (%u prefix/demotion cases)\n", cases);
}
