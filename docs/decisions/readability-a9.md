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

## 2026-11-08 — object embedding (`KvObj`, `kvobj_alloc_size`)

The old prototype comment attributed +27% SET to embedding and reiterated that
allocation count, not a bespoke pool, was the useful change. The 192-byte embed
threshold was tested against the abandoned prototype's Redis-shaped allocation,
not this native layout; the comment explicitly called it a starting point for
measurement. An untested footprint aspiration was under 85 bytes for a 16-byte
key and 64-byte non-TTL value. The actual request is 8+16+64=88, rounded to 96;
no `bench/kvobj_footprint` or varint-header implementation backed the aspiration.
Small collections use a 32-byte metadata overlay with packed bytes in the same
object allocation. The former comments cited Redis/Valkey listpacks and
Dragonfly packed values as motivation; those comparisons are not proof here.

## 2026-11-08 — forced inlining (`kvobj_init_raw_string`)

The old construction comment says inline key copying pushed a factory just
over GCC's inlining cost limit at three call sites, adding roughly twenty
instructions on first insertion. The attribute stays untouched. The comment
was attached to the raw initializer, which actually takes caller-owned memory,
rejects values over 192 bytes and allocates nothing; it must not promise an
external-string allocation or unbounded raw payload.

## 2026-11-08 — rounded allocation requests (`kvobj_new_string`)

A historical ASAN RYOW check reportedly caught a three-byte heap overwrite when
an exact allocator received the raw request but overwrite used class slack.
Request `good_size(kvobj_alloc_size(...))` explicitly so that slack is allocated
under jemalloc, libc and ASAN. The reasoning remains beside the allocation.

## 2026-11-08 — namespace decoding control (`KvObj::probe_key`)

The local ELF patch symbol marks the KeyExt branch without allocating bytes.
The offline kind A behaviour twin changes JNZ to JMP so every probe uses the
general decoder. The empty register constraint prevents specializing that
block for KeyExt being set. No instruction, literal, symbol or patch site moves
in the retained readability change.

## 2026-11-08 — owner cache scope (`KvBlockCache`)

The removed narrative reports a per-shard variant losing 2–4% armed SET at
8/64 shards while winning at one shard: each shard carried a separate head
array and byte gauge, unlike the thread-local jemalloc alternative. A physical
owner's cache shares those structures among its shards. Shard migration
rebinds future allocation/reclamation submissions; queued retirements retain
their accepting physical queue. Main-thread post-join release is valid and was
previously contradicted by an unconditional “owner-thread only” comment.

## 2026-11-08 — cache capacity (`KvBlockCache::put`)

At 64 shards on one fused owner, a 32-node cap reportedly left 0.5001/0.3750
`mallocx` calls per operation at pipeline 64/256, versus zero with 4096 nodes
and 2–4 KiB more cached memory. `kMaxNodesPerClass` follows the 4096-entry retire
ring. The aggregate byte cap is 4096×192 = 768 KiB; it does not imply that an
eligible object allocation itself is at most 192 bytes. Rejecting a put does
not trim existing residents; the caller retains ownership and must free or
otherwise retain the rejected block.

## 2026-11-08 — cache diagnostics (`KvBlockCache::dbg_walk`, `put`)

The former comment says walking every list on each operation slowed
reclamation enough to hide the race under investigation. Debug walks sample
once per 1024 calls while residency checks remain per-operation. `put` aborts
an immediate duplicate at the class head before it creates a self-loop, rather
than relying on a later count discrepancy. Debug owner checks permit shutdown
release after joining workers; the implementation does not limit reports to
one crossing, despite the former wording.

## 2026-11-08 — compact coordinates (`Compact::insert`, `decode`)

The former comment describes an integration crash (SIGFPE in `offset_slot`
with an empty index) when sorted integer sets crossed the indexing threshold.
Insertion must handle an absent or newly created circular index and recompute
the splice after a buffer relocation. A separate history note described a
hang from treating absolute offsets as logical offsets. Public offset APIs
use logical coordinates; the private three-argument decode uses absolute
offsets with an explicit index. `logical()` is the conversion boundary.
Small collections defer the side index until entry 17; the old comparison to
peer packed formats is motivation, not a fresh result.

## 2026-11-08 — resolver ordering (`FlatStore::atomic_resolve_range`)

The removed comment reports that at 16 target cores cleanup masked the
same-connection stale-read window. At the gate's eight-core geometry,
collapse-only repair failed `tests/multires.py` in 3/8 runs, while repairing
read-time ordering yielded 0/8; it reports about 2% cost in the atomic-path A/B.
Retain the same-connection epoch floor before visibility filtering. A private
own version outranks committed versions even at epoch zero; otherwise repeated
RPUSH/APPEND/INCRBY can modify a parked predecessor and lose an acknowledged
write during collapse.

## 2026-11-08 — resolver diagnostic scope (`atomic_resolve_range`)

The old #77/seed-19 narrative describes a rare EXISTS overcount investigated
through a finite-cut predecessor answer with a smaller decided group ticket.
The code retains counters, a process-wide first-answer latch, an unfiltered
same-key rewalk and at most 4096 diagnostic ticket polls. The discriminators
separate membership masking, visible-version ranking and undecided publication
windows. These observations are not correctness verdicts, and they are gated
before extra walks/atomic loads. The operational distinctions remain in source.

## 2026-11-08 — foreign epoch limitation (`ForeignReadSafety::cell_epoch`)

The former comment called uint32_t epochs monotonic and asserted that a bounded
owner rate prevented a complete wrap inside a reader window. `touch_epoch`
wraps by ordinary unsigned addition; neither it nor the caller establishes a
maximum reader suspension. Equal epoch loads therefore rely on no full wrap,
and the store's other publication checks are still necessary. This is a
pre-existing proof limitation, not a code change or a demonstrated corruption.

## 2026-11-08 — ABI and publication separation (`AtomicPendingState`)

The read-local discriminator, installing flag, modulo-256 group count and
saturating range count share the four-byte gap before `cleanup_fast`. The
combined finish-install write covers only the two owner-local bytes; it must
not overwrite the discriminator read by foreign probes. The discriminator is
initialized before arming. `live` and script-intent count share a cache line
for `atomic_has_records`. Cold FLUSH clock/reference-release helpers remain
outside the scatter/unpin callers to preserve their compilation boundaries.

## 2026-11-08 — interface-first candidate (`Compact`)

Compact is the sole eligible A9 class (384 token-bearing function lines in the
inventory, including its small nested Iterator). Forty direct Compact member
bodies were moved, in order and without body-token changes, into a topic header
included immediately after the class inside namespace tomo. Nested Iterator
bodies stayed with Iterator. Definitions became explicitly inline, static stayed
on declarations, return-type qualification and default arguments were handled
at the interface/definition boundary. The formatted body proof and candidate
patch are retained under `docs/readability-a9/evidence/`.

The candidate built and the required frozen-release comparison reported:

```
IDENTICAL (11167504 bytes after stripping)
```

The lane also explicitly requires each edited file's preprocessing-token stream
to equal PRE, apart from allowed renames. Declarations and qualified definitions
cannot satisfy that literal per-file rule. No source-token exception is assumed:
the split is reverted to retain the exact per-file proof, and its successful
experiment is supplied as a small reviewable patch. This is not a binary
regression.

## 2026-11-08 — contract audit refinements (base and storage helpers)

The contract pass distinguishes raw string initialization from an allocating
factory; names the actual topology caller (`Server::prepare_boot`) and C helper
includers; records decision-path as well as owner-path FLUSH counter updates;
and qualifies duplicate/underflow checks by what their branches actually detect.
Numeric strict parsing accepts nonzero subnormal ERANGE results, and Grisu2's
weeding decrements a digit rather than reducing the number of digits. Sized frees
use the requested size, which object callers already round. None of these comment
corrections changes the implementation or establishes a new runtime guarantee.
