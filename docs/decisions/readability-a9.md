# Store and base readability decisions

Entries dated 2026-11-08 record material extracted from comments at lane base
`7595a6705`. Earlier experiment dates are not established by those comments.
Numbers below are archived observations, not new measurements or claims about
this lane. The source retains the operational reasons and safety requirements.

## 2026-11-08 — allocation interface (`alloc_raw`, `free_sized`)

The original prototype tried and discarded a bespoke tiered size-class pool:
the reported gain came from fewer allocations. Its comments attributed
+30–54% to jemalloc. The interface exposes allocator classes and sized free;
specialized pools remain with their owners. Cross-thread frees are supported
by the allocator, so allocation and reclamation need not occur on the same
physical thread, particularly after migration or during shutdown.

## 2026-11-08 — arithmetic size classes (`good_size`)

The removed comment attributed 5.6% of SET-cell cycles to repeated `nallocx`
PLT calls from KvObj accounting. Arithmetic class calculation avoids these
calls. The startup comparison against `nallocx` checks sizes 1 through 65,536;
it is not evidence for every representable request size. Rounding arithmetic
requires inputs that do not overflow `size_t`.

## 2026-11-08 — short key equality (`bytes_equal`)

The historical comparison counted about 22 instructions in glibc's short-key
`memcmp` and four caller-saved register spills/reloads around the call. The
reported GET-hit change at 24-byte keys was about 17 instructions (1.0%),
contrasted there with the 5.6% `nallocx` result. The original comment points to
its introducing commit for the full table; that table was not reproduced in
the source. Inline equality is bounded to 32 bytes and has no three-way order.
The store's insertion comparison deliberately retains `key_mem_eq`; ordering
comparisons in zset lex ranges, SORT, ACL selectors and cross-shard merge retain
`memcmp`. Inline accesses stay within the span, including under ASAN; the
library fallback follows the library contract.

## 2026-11-08 — short byte copies (`bytes_copy`, `detail::copy16`)

An LD_PRELOAD PLT interposer reportedly counted two `memcpy` calls per steady
GET and three per SET, versus one key `memcmp`. `Op::Sink::append` copied
roughly 5–40 bytes and spilled registers around the library call. An 8-byte-only
copy ladder reportedly took 16 instructions versus the library's 15 at 20–32
bytes. The selected 16-byte blocks and 64-byte ceiling were accompanied by this
isolated runtime-length, out-of-line-body table (`cpbench.cc` in a scratchpad):

| Length | 3 | 5 | 8 | 16 | 24 | 32 | 39 | 48 | 64 | 72 | 128 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Library instructions | 22 | 19 | 17 | 15 | 15 | 13 | 13 | 13 | 13 | 13 | 13 |
| Inline instructions | 14 | 8 | 12 | 12 | 12 | 14 | 14 | 14 | 14 | 17 | 17 |

Above the ceiling the comment reported four extra instructions for length
tests. A 32-byte vector block saved three instructions in isolation but caused
GCC to realign the function frame (four entry/exit instructions, including
fallback calls). With that copy inside `SmallBuf::append`, a GET of a 128-byte
value reportedly gained 9.7 instructions. The 16-byte ABI alignment motivates
the explicit block width. Source/destination overlap requires `memmove`, even
when a helper would otherwise fall back to `memcpy`.

## 2026-11-08 — whole reply copies (`SmallBuf::append`)

Three short-copy variants were evaluated: the length test inside the helper,
hoisted with the short case predicted, and hoisted with the long case predicted.
All reportedly saved about ten instructions for five-byte replies and lost on
GET replies exceeding the ceiling (+2 at 47 bytes, rising to +9 at 87). Keep
`memcpy` for whole replies of user-dependent length. The direct-reply length
commit is also used by ordinary connection append and WbEngine copy paths;
it is not itself an atomic publication operation.

## 2026-11-08 — numeric compatibility (`grisu2_digits`, `redis_double_text`)

The source credits the published Grisu2 algorithm (Loitsch, PLDI 2010) and
observations of the Redis 7.4 executable, without reading reference source.
It reports roughly one digit/length difference per 700 doubles against the
standard-library shortest-round-trip formatting; the sample distribution is
not recorded. The example is `1e126`, rendered `9.999999999999999e+125`.
Both ends of the integral fast-path bound, ±2^62, were reportedly probed.
These are compatibility rationale, not a general statistical guarantee.

## 2026-11-08 — timeout rounding (`parse_timeout_ms`)

Reference-executable probes established the documented order: parse, scale to
milliseconds and take `ceil`, test positive overflow, then test the resulting
sign. `BLPOP k 1e-9` has a positive deadline; `BLPOP k -0.0004` becomes negative
zero and has no deadline; `BLPOP k -0.5` remains negative and is rejected.
The code retains those exact rounding and rejection rules.

## 2026-11-08 — L3 locality (`Topology`, `FlatStore::resident_estimate`)

The removed machine-specific narrative described NPS1, one NUMA node over
128 GB, a CCX-to-fabric link near 51 GB/s and a single core near 50 GB/s.
No date or measurement instrument was given. Moving shard ownership does not
move its memory; the destination refills its cache. Topology describes shared
L3 groups, while the store supplies the footprint used to price migration.
Worker/shard residency and operation counters are owned outside Topology.

## 2026-11-08 — batching patch sites (`TOMO_EXBATCH_TWIN`)

The five-byte NOP and non-allocated records support an offline kind A
**behaviour twin**: reference behaviour with candidate text size/layout.
`asm goto` preserves a compiler-visible control-flow edge and its register/stack
contract. Readability work leaves the macro, assembler literals and sites intact.
