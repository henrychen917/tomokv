# Remaining dispatcher compositions

The 20 remaining hot mismatches contain N3/N4 and the headline's mkfix2 `Op::has_scatter_state` change. The latter accepts both `kScatterStateMarker = -2` and `kScatterReplyMarker = -6` (`src/exec/op.h:393`); `IoLoop::release_op` uses it at `src/core/io_loop.h:112`, and GCC inlines that release in these dispatchers. The ntfix3 body cannot already contain this headline behaviour.

The retained representative is db0 genthread `parse_and_dispatch<true,32,false>`, whose size stays 18,561 bytes. At relative +14,244 the old direct comparison against -2 becomes a load, mask by -5, and comparison against -6, accepting both marker values. The two `scatter-marker-*.asm` files show the exact old and merged instructions. Other differences include shifted control flow and GCC inlining; db0 R7's false dispatcher now inlines `RespFrontier::finish` (`free` replaces the named helper call). All 20 bodies, their sizes, and both-reference comparisons remain in `residual-hot-bodies.md` and `dual-reference.json.gz`. No opcode or member offset is normalized away to call these bodies equal.

This is an explained remaining identity difference, not a performance verdict. The maintainer's merged/headline null and landing gate decide acceptance.
