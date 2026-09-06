// THE SWEEP'S CODEGEN, ISOLATED. read_local_write_tag_may_match is always_inline and disappears
// into the parser, so this file gives it one noinline caller at the server's own flags and lets
// objdump answer the only question that matters about its shape: does GCC vectorise it?
//
// The straight `for (i < 64) hits |= (tags[i] == tag) << i` that mirrored the sixteen-slot filter
// one-for-one does not: GCC 13.3 emits a scalar body sixty-four times, roughly 450 instructions on
// the path a disjoint read takes every time. The sixteen-lane grouped form does, through a
// vpcmpeqw against a constant bit-weight vector and an OR-reduction. The first draft of this lane
// shipped the scalar version into a rate A/B and read -8% at 61% reads before anyone disassembled
// it; this file is why that cannot happen silently again.
#include "src/net/conn.h"
#include "src/net/rob.h"
using namespace tomo;
namespace {
struct AlwaysTouches {
    bool operator()(const Op&, uint64_t) const { return true; }
};
}
// The whole probe, tag filter included, as the parser calls it.
extern "C" __attribute__((noinline)) bool ringsize_probe(Rob<kRobWindow>& r, uint64_t h) {
    return r.read_local_write_conflicts(h, AlwaysTouches{});
}
