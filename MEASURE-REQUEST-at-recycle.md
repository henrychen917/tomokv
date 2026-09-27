# at-recycle: post-grace cache admission

Status: implementation and serverless proofs complete; **NOT READY TO LAND**. All live correctness,
performance, latency and RSS conclusions are **PENDING mainline**. No server, load generator, gate,
perf stat/record or performance measurement was run. `perf list --details` only inventoried capabilities.
Do not overlap other at-* or hp-flagkey/flagvalue/metatouch/slothome/incr/store-layout lanes.

## Frozen change and diagnosis

Branch/worktree: `cx-at-recycle`, `/home/user/Projects/cx-at-recycle`.
PRE/stable reference: `32d27ee7562ed5a17ff889c0fe5cf250f3fdc63c` (after wbrule).
POST production change: `22da33806`; proofs/artifact tooling: `160bf712c`, `f2f9e9ff1`, `fac463d14`.
Later commits contain no further production behavior change. Preserve the scored artifacts below.

The ONE change is `src/store/flatstore_atomic.inc:1455`: pass `obj_bytes_ ?
KvBlockCache::kMaxBytes : 0` to `cache->put`, replacing the per-shard byte magnitude.
Only this file owns the policy. The other two production-file changes correct policy comments.
No class indexing, node layout, capacity forwarding, accounting delta, prefetchw, metadata setter,
retire cadence, ownership protocol, read-local representation, knob or allocator change.

Re-found on this reference:

- `flatstore.h:1292-1331`: inline string/integer allocation uses exact-size take; a miss allocates;
  allocator refusal releases cache and retries. `:1338`: failed insertion frees directly.
- `flatstore.h:3159-3166`: retirement carries the existing capacity and subtracts logical bytes.
  `:3350-3364`: reclaim callbacks offer blocks only after grace, then use existing destruction/borrow retention.
- `flatstore_atomic.inc:1438-1448`: only Raw/Int String shapes, with the original borrow exclusion.
- `kv_block_cache.h:205-212`: the caller ceiling limits the entire owner's cached bytes, not just
  this shard's contribution. Previously a one-live-object shard could admit at most one same-class
  block from a completed wave. This is admission policy, not corruption of logical used_memory.
- `kv_block_cache.h:82-84`: 4,096 nodes per class and 786,432 cached bytes per owner. The overflow-safe
  subtraction, class cap, exact-size take and rejected-put free path remain intact.
- `flatstore.h:2416-2424,2936-2939`: refusal pressure and FLUSH release. Successful eviction does not
  promise release on every write. `read_local.h:339-353`: shutdown drains pending entries and cache.
- `server.h:2127,2280`: eager ownership-edge rebinding retained. The fixture checks context, cache,
  defer, capacity hook and resize hook immediately after transfer, before another owner operation.

Physical memory is deliberately outside live-object accounting. A nonempty shard with one live
class-C block may retain `min(4096*C,786432)` bytes of that class; heterogeneous classes share the
786,432-byte owner ceiling. For the unit's 32-byte live object, the single-class maximum is 128 KiB
(4,096 times its live bytes); observed controlled W=8/32/64 waves retain 256/1,024/2,048 bytes.
The general payload bound is 768 KiB per owner: 6 MiB for eight populated owner caches or 1.5 MiB
for two, excluding existing queue/allocator metadata. Empty shards refuse NEW puts; they do not
trim old contents. FLUSH/refusal/shutdown return blocks to jemalloc, which need not immediately
return pages to the OS. **RSS and maxmemory-pressure behavior must be measured**, including peaks.

## Builds and reproducibility

All builds used cores 112-127; parallel make used `-j16`. Eight-worker serverless fixtures used
112-119, a subset of those cores. No affinity outside the allocation was used for build/test.
GCC `13.3.0 (Ubuntu 13.3.0-6ubuntu2~24.04.1)`; `-march=native` resolves to `znver4`, tune `znver4`.
Production flags: `-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_JEMALLOC`, with the
unchanged per-TU GCC budgets and dual-database definitions in the frozen reference Makefile.
Link order: original SRC order, DB-0 objects first; `-ljemalloc -luring -pthread -lssl -lcrypto -lm`.
No LTO or counter flag added to scored arms.

Compiler SHA256: `1353e9bdd29a7295c7226bf6c63abccce056d8cac31f112e5cdbecc3f28c2769`.
Allocator `/lib/x86_64-linux-gnu/libjemalloc.so.2`, SHA256
`567efa52ecf445d5966025e1dcfd6b927a986472d272be3742f74a4a373baf12`.
Full environment/build identity: `build/at-recycle-build-manifest.json`,
`build/at-recycle-compiler-target.txt`. Native flags require this box; do not silently rebuild elsewhere.

Executed build recipes (PASS; logs under `build/at-recycle-*-build.log`):

```sh
git archive 32d27ee75 | tar -x -C build/at-recycle-pre-src
taskset -c 112-127 make -C build/at-recycle-pre-src -j16 \
  BUILD_ROOT=/home/user/Projects/cx-at-recycle/build/at-recycle-pre all
# At production commit 22da33806:
taskset -c 112-127 make -j16
cp build/at-recycle-pre/tomokv build/tomokv-at-recycle-pre
cp build/tomokv build/tomokv-at-recycle-post
python3 tools/at_recycle_artifacts.py twin build/tomokv-at-recycle-post \
  build/tomokv-at-recycle-pad-a --receipt build/at-recycle-pad-a.json
```

The source mirror tool only writes new directories below this worktree's `build/`. `mirror witness`
injects counters into that copy; no production include/branch/allocation refers to them. Compile
`tests/at_recycle_witness_alloc.cc` to `build/at-recycle-witness-alloc.o`, then build the mirror with
the same pinned make command and an absolute BUILD_ROOT. Its Makefile links mallocx/sdallocx wrappers.
POST mirror/build: `build/at-recycle-witness-src`, `build/at-recycle-witness`.
PRE witness: `build/at-recycle-witness-pre-src`, `build/at-recycle-witness-pre`; the sole additional
mirror edit restores `cache->put(..., obj_bytes_)`. Both unscored server binaries built successfully.

Negative mirrors use `mirror {cap,never-drain,eager,borrowed,no-class,no-bytes,never-release,gauge,stale-sink}`.
`build/at-recycle-controls.mk` records exact commands linking each serverless TU against release
objects, excluding main/xshard (the fixture includes xshard). Witness tests link the fully instrumented
witness objects instead. Builds used `taskset -c 112-127 make -f build/at-recycle-controls.mk -j16`.
The controls are deliberately broken **serverless test binaries**, never scoring arms.

## Serverless evidence and negative controls

`tests/owner_arena_unit.cc` includes `tests/at_recycle_checks.inc`; it still uses real pinned owner
workers, the real deferred queue/cache, actual QSBR participants, jemalloc and the existing snapshot
handoff. Normal invocation runs the added cases in both armed modes. Controlled writes use the
real string/integer store constructors; live SET/INCR command regression remains mainline's job.
Object-byte assertions use a live-table census plus jemalloc `sallocx`, independently of store size
arithmetic. Collection destruction is separately checked with a watched freed pointer.

All assertions below PASS on POST in 1s and 2s. Negative results are actual exit-1 assertions,
not timeouts, crashes or skipped windows. Negative binaries are
`build/owner-arena-at-recycle-<control>`; logs are `build/at-recycle-negative-<control>.log`.
`build/at-recycle-negative-results.json` contains exact diagnostics.

| Assertion / actual mechanism | Negative control | Expected and observed failure |
|---|---|---|
| One live key; W=kRobWindow/8,/2,full = 8/32/64; complete W-object grace; next W Raw/Int allocations all hit, zero mallocx | `cap`: restore shard-magnitude ceiling | `completed W-object wave is fully cached despite one live object` |
| Queue really holds W, and its drain reclaims W; no conditional skip | `never-drain` | `grace drain reclaims the complete eligible wave` |
| Pin old reader; pointer/bytes survive 64 replacements, absent from cache before grace, present only afterward | `eager`: callback on retirement instead of enqueue | `reader-held pointer cannot be handed out` |
| Borrow retained raw pointer across grace and repeated reuse; unborrow alone frees it | `borrowed`: remove cache borrow exclusion only | `retained borrowed pointer must not appear in cache` |
| Actual quiesced shard/range transfer, distinct caches, first destination allocation/reclaim, every sink member bound at edge | `stale-sink`: no eager adoption | `owner assertion: every sink binding names destination at the ownership edge` |
| 4,096-node class full, then W=64 additional deferred puts; exactly W baseline sdallocx frees | `no-class` | `class walk respects structural node bound` |
| Heterogeneous 512/1,024-byte classes fill 768 KiB; W extra puts free; oversize/undersize arithmetic rejects | `no-bytes` | `cache byte census and total bound` |
| Nonzero occupancy before FLUSH/refusal/OOM/shutdown; no refilling after empty FLUSH; failed insert frees directly | `never-release` | `release action returns occupied cache to allocator` |
| Logical object/accounted bytes agree after every directed insert/replacement/delete/clear/pressure action | `gauge`: subtract one byte too little on retirement | `logical object bytes agree with independent live-object census` |

Additional passing assertions: full 4,096-entry ring pins a reader until forced grace engages;
bounded three-attempt setup recreates fresh state and fails if the window never opens. Shutdown
starts with occupied cache AND a pending retirement and drains both. Empty-shard deletion refuses
the displaced object while preserving already cached blocks (no imaginary automatic trim).
Size oscillation covers 0/1/15/16/17/191/192/193/4096-byte values, Extern header+payload freeing,
collection rejection, integer reuse, huge keys outside all cache classes, and two shards sharing
one cache. Failed allocator allocation triggers the real release-and-retry path.

Executed validation:

- owner-arena full suite: 1s/2s × read-local-0/1 PASS; latest added shutdown case PASS in both modes.
  Logs: `build/at-recycle-owner-?s-?.log`, `build/at-recycle-owner-final-?s.log`,
  `build/at-recycle-shutdown-final.log`. No listener or io_uring instance starts.
- `read-local-ring-unit`: PASS (`build/at-recycle-ring.log`).
- Eleven ordinary store-regression cases PASS; deadline-sidecar PASS in its required sidecar build
  (`build/at-recycle-store.log`, `build/at-recycle-sidecar.log`). An initial attempt to run the deadline
  case in the ordinary build correctly refused; the properly configured sidecar run passed.
- Instrumented owner suite PASS in both modes; its attempts/hits/fresh/admissions are asserted against
  the wave census. Logs: `build/at-recycle-witness-unit-{1s,2s}.log`.
- Owner snapshot transport/analyzer PASS: eight participating queue snapshots at each ticket,
  eight takes/misses and seven admissions in a finite eight-write fixture. No public RESP metric is
  inferred from this. `build/at-recycle-witness-boundary.{log,json}`.
- Strict analyzer synthetic checks PASS: arithmetic; missing fallback field, missing server thread
  and growing backlog each cause ERROR. Synthetic inputs are not performance results.

NOT RUN — mainline live tests: both real boot modes, `tests/rlcache_churn.py` (including the existing
stale-sink debug negative), `read_local_lane`, snapshot/expiry/eviction/borrow batteries, all main-command
parity, and `tests/gate.sh iteration`. Reproduce live gate rows with `--shards 16 --ratio $GATE_RATIO`
on `$GATE_CORES` (default 0-7, 6 io + 2 ex), not an arbitrary default boot.

Gate delta **0 quick / 0 full**. This reference actually declares **441 / 457** at
`tests/gate.sh:260-261`; quick exits at `:2838`. `collect_job ring_unit` is `:2705`, storage `:2712`,
both before that exit. No collection line or loop was added, retired or changed. The owner-arena
Makefile target already has four invocations; it is not itself a collected gate.sh row here.
Run that extended target as an explicit mainline prerequisite. EXPECT_QUICK/EXPECT_FULL untouched.

## PAD-A and generated code

**Kind (A), BEHAVIOUR TWIN:** PRE admission behavior in exactly POST's ELF/text layout.
`tools/at_recycle_artifacts.py twin` audits and changes two fixed-width arithmetic sites in each
of four reclaim callbacks (ordinary/atomic × DB-0/multidb). No new runtime selector is shipped.

At selection, replace `neg rax; sbb rax,rax; and eax,786432` with
`mov ecx,786432; cmp rax,rcx; cmova eax,ecx`, computing `min(obj_bytes_,786432)`.
RCX is dead at that site and later overwritten by class arithmetic. Both sequences occupy 11 bytes.
GCC also constant-folded the later limit: replace its eight-byte constant-load/subtract with ONE
64-bit subtraction retaining the computed limit. Five redundant operand-size prefixes plus REX.W
keep that instruction eight bytes. No executed NOP/loop, extra load, stack slot or branch.
Admission still rejects cached_bytes >= limit before subtracting, preserving overflow safety.

The receipt `build/at-recycle-pad-a.json` contains every address/old/new byte and hashes; all other
file bytes, section and symbol records, callback sizes, branch addresses and targets are identical.
The copied ELF build-id is unchanged; distinguish arms by file and SHA256, not build-id.
Only four selector sequences exist in scored .text and all four are patched. Disassembly:
`build/at-recycle-disasm-{pre,post,pad-a}.txt`.

Serverless patched fixture: `build/owner-arena-at-recycle-pad-a`, receipt
`build/at-recycle-unit-pad-a.json`. Independent `pre-cap` oracle PASS at W=8/32/64:
**1 hit and W-1 misses**, matching the source cap mutant. POST fails that PRE oracle;
PAD-A fails POST's full-wave requirement. PAD-A pinned/borrow/shapes/release/migration cases PASS.
These prove PRE behavior, not PRE timing. **PAD-A must still stay inside PRE's measured null.**

`.text`: PRE 7,550,604 bytes; POST/PAD-A 7,550,748 (+144). GNU size's aggregate text/rodata figure
is 8,544,708 → 8,544,928 (+220). No PAD-B threshold is crossed. Padding cannot shrink the larger
POST to PRE's smaller text size; the exact common-envelope A control is retained.

Callback sizes per database variant: ordinary 682 → 664; atomic 694 → 640 bytes. The source
conditional compiles as branchless arithmetic, not an added conditional jump. Planning estimates
(25–80 cycles per affected write, 50–150 instructions per avoided allocator round trip) are **not
current measurements**, nor implied by the shrinking callbacks: total .text actually grows.

Off-path audit: `tools/lbstall_artifacts.py compare build/at-recycle-pre build
build/at-recycle-offpath.json` examined 1,442 selected object-file bodies: 1,432 raw-identical,
1,434 identical after resolving relocation targets. All inspected GET/SET handler variants match.
Eight compiler-collateral exceptions must not be called instruction nulls:

| Object / body | PRE bytes | POST bytes |
|---|---:|---:|
| db0 scripting / erase_in_read_local | 647 | 606 |
| db0 serialize / erase | 1093 | 1266 |
| db0 genthread / run_loop<true,false,true,true,0,false> | 4838 | 4810 |
| db0 rl2s / run_loop<false,false,true,true,0,true> | 5171 | 5179 |
| genthread / run_loop<false,false,false,true,0,false> | 4932 | 4951 |
| genthread / run_loop<false,true,true,true,0,false> | 5027 | 5016 |
| main / ifid_rx<false,false,true> | 997 | 974 |
| snapshot / insert_read_local | 1511 | 1527 |

These are object bodies, including weak definitions; not every copy is selected by the final link.
No adjacent GCC-budget tuning was bundled. PAD-A retains this collateral; mainline must demonstrate
both PRE/PAD-A null and pure-GET/unarmed-SET parity. Scored binaries have no witness symbols/strings.

Layout audit (`build/at-recycle-layout.json`): PRE=POST, including all exported offsets.
Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624.
Existing per-member static assertions compiled in both database variants. GCC's existing Server
offsetof audit emits its usual non-standard-layout warning; both emitted arrays are identical.

Stores/coherence: successful put still has five architectural stores (node.next, node.allocation,
head, class count, bytes); take still has three (head, class count, bytes). More successful puts/takes
replace allocator calls; they do not remove publication of the replacement. Owner address offsets
remain head=8*c, class_count=384+4*c, bytes=576: two to three owner cache lines, plus the reclaimed
node's line for put. No new shared RMW, lock, per-op epoch publication or reader-path store/load.
The existing grace-sealing RMW cadence is unchanged. Allocator internals/ownership transactions
are unmeasured; **no RFO-elimination claim** follows from this change.

## Mainline witness and scoring protocol

Scored arms: `build/tomokv-at-recycle-{pre,post,pad-a}`; `build/tomokv` is byte-identical POST.
Unscored arms: `build/tomokv-at-recycle-witness-{pre,post}`. Do not score these.
The latter alone installs SIGUSR2: a lock-free snapshot ticket is read on the owner's next queue
drain, and the owner emits one `AT_RECYCLE` JSON line. At each unscored boundary request one ticket,
wait for every active owner's matching record before proceeding, then run the finite frozen trace.
Missing owner/ticket is ERROR. Do not infer a boundary just because time passed.
`release-or-joined-shutdown` lines may be from main after join; their thread allocator counters
are not owner counters. The analyzer excludes them. No foreign plain cache read is used.

Fields: take attempts/hits/misses, outside-class takes, admitted puts; mutually exclusive first
rejection cause (collection, encoding including Extern, borrowed, undersize, outside_classes,
class_full, empty, bytes_full); fresh allocation attempts/failures; per-thread mallocx/sdallocx;
all 48 class occupancies/bytes and total bytes. `bytes_full` means the effective byte ceiling
`min(caller_ceiling,kMaxBytes)` (the tiny PRE shard ceiling is included). Eligible takes exclude
outside-class takes; Extern constructors and successful atomic-pool recycling never attempt this
cache. Fresh successes = fresh - fresh_failed. Allocator totals include all wrapped allocations on
that owner; report separately from cache-related fresh attempts. Non-owner IO-thread allocations
are not exported by queue snapshots, so these do not prove an all-server allocation total. Capture
live bytes and RSS too. Use finite, quiesced unscored trace boundaries and allow each owner a loop
pass to emit its ticket; signal handling alone does not wake an idle owner or establish quiescence.

Offline commands:

```sh
python3 tools/at_recycle_analyze.py witness witness.log BEFORE_TICKET AFTER_TICKET
python3 tools/at_recycle_analyze.py window before.info after.info metrics.json [--mget]
```

The window analyzer requires all current read_local fields from t_server.cc, every fallback detail,
arms, write-ring sidecars/records, keyspace hits/misses, and MGET fields when used. Aggregates and
details remain separate, never double-counted. Required missing fields are ERROR, not zero.
Its metrics input requires completed public/get/set counts, elapsed seconds, offered rate, backlog
endpoints, p50/p99/p999 in microseconds, RSS/live-byte endpoints, trace hash/run lengths, all server
thread IDs and each thread's cycles/instructions/running fraction, and frozen E_C/E_I/E_rate/E_tail.
It rejects missing threads, multiplexed PMU counts and growing backlog; reports C, I, IPC, rate,
achieved fractions and completions/offered. The collector must still prove provenance, exclude
setup/INFO and validate achieved-rate tracking against E_rate. It supplies no missing driver trace,
PC/role attribution, cache hit data, allocator data or causal RSS attribution by inference.

Before measuring, freeze server/driver argv, binary/library hashes, allocator environment,
topology/affinity, routing/shard count, key/value corpus, feature options, trace bytes/hash and
loader connection assignment. Preserve owner's 32-real-core, 512-connection, eight-loader argv;
its unspecified shard/key/value settings remain **PENDING mainline**, not invented here. Add one-core,
same-CCX and cross-CCX attribution. A single connection is not a saturation proof. Keep key-lb and
client-lb on in all judged cells. Off arms are diagnostic only. Send-path claims require the owner's
25GbE two-netns rig; loopback alone is inconclusive.

Directed trace specification, separately labeled from owner's frozen 32-core cells:

- Gate topology: 16 shards, GATE_CORES/GATE_RATIO; both 1s and 2s. The tiny one-key corpus is literal
  `r000000000000000` (16 bytes). For one/two/four keys per shard, enumerate `r%015x` in ascending
  index and retain the first requested count mapped to each shard by the frozen router/hash.
  Persist the resulting ordered key list/hash. Normal overwrite corpus: first 4,096 enumerated keys.
- Inline SET value lengths: 0,7,8,9,39,40,41,103,104,105,191,192; Extern deficits: 193 and 4096.
  These bracket good_size transitions for 16-byte keys and kEmbedThreshold. Bytes at logical
  generation g are ASCII `a + (g mod 26)`, repeated to the selected length. INCR starts from 0.
- Trace positions are per connection. Pure traces use SET, INCR or GET throughout. Mixed 1:1 is
  repeating SET,GET; 1:9 is SET followed by nine GETs; 59:41 chooses SET iff
  `floor((i+1)*59/100) != floor(i*59/100)`, otherwise GET. Persist run-length histograms and achieved
  completions by command. Also reproduce owner's original ordering, not just these directed traces.
- For normal shared-key traces, index `(connection_id + i) mod K`; one-key K=1. Include separately
  labeled disjoint read/write key corpora and actual-conflict corpora. Setup/arming completes before
  observation; startup fallback is separately reported. MGET/MSET each use eight consecutive corpus
  keys but count as ONE completed public RESP command. First-insert traces use disjoint increasing
  key indices. Churn cycles SET,DEL; a separate finite burst is SET*W,FLUSHALL with W from kRobWindow.
- Deficit size-oscillation trace alternates inline lengths 8/40/104/192 and Extern 193/4096; add huge
  keys outside cache classes, mixed classes, maxmemory noeviction/refusal and eviction/allocator/RSS
  pressure. Retain the frozen workload and memory settings in the cell manifest, not a new knob.

Cover benefit/neutral/deficit at cache-resident and DRAM-resident working footprints, saturation and
matched-load latency. A repeatedly accessed single small object itself fits cache: label a separate
DRAM background/large-working-set variant honestly; do not pretend its one hot object is DRAM
resident. Keep background keys out of the one-live-object shard when testing that diagnosis.
Report interference/admission changes from other shards; do not silently reclassify them as noise.

Required matrix, each at p32 AND p8 unless stated: armed 1s SET; SET:GET 1:1 and 1:9; 59%-writes
p32; pure armed GET hit (NULL); unarmed SET with SAME driver (instruction NULL, cycles NULL or better).
Add saturated p1 and GET/SET/MGET(8)/MSET(8) in 1s/2s × read-local 0/1 × atomic 0/1, shipped overlap/
reorder 1/1 plus isolated 0/0. Normal 4,096-key overwrite, already-near-100%-hit inline SET, first
inserts and pure GET are neutral controls; tiny-key SET/INCR are the directed benefit candidates.
Explicitly freeze flip and every other existing option; no inherited defaults in judged manifests.

Collect same-binary paired nulls FIRST. Freeze E_C/E_I/E_rate/E_tail for each session/geometry.
Establish saturated PRE/POST/PAD-A capacities; set `R=0.90*min(capacities)` and hold R across arms.
10 s warmup, 40 s scored windows, >=3 ABBA quartets for PRE/POST and >=3 for PAD-A/POST initially;
repeat unresolved noise without widening tolerances. Reject growing backlog or failed achieved-R
tracking. Report saturated rate separately. Sum hardware cycles/instructions over ALL server threads,
exclude drivers; N is completed PUBLIC RESP commands, excluding setup/INFO. C=cycles/N, I=instructions/N,
IPC=instructions/cycles; C=I/IPC. Neither CPU time nor inverse rate substitutes for cycles/op.

Benefit requires C_POST-C_PRE < -E_C AND C_POST-C_PAD-A < -E_C, with instruction savings beyond E_I
when claimed. PAD-A must stay inside PRE null. Every cell must meet reference rate/cycles/tail parity
within calibrated nulls; no averaging a deficit away. Pure armed GET must be NULL; unarmed SET must
be instruction NULL. Existing compiler collateral above makes that check especially material.
Always-on <=3% is a ceiling, not permission for a parity failure. Hardcode-or-delete: this candidate
is already fixed policy, with no shipped selector; if null/losing or any constraint fails, reject it.

PMU inventory only: `build/at-recycle-pmu-catalog.txt`, perf 7.0.12. This box lists `instructions` /
`ex_ret_instr`, cpu event 0xc0 (retired instructions), and `cpu-cycles` / `ls_not_halted_cyc`, event
0x76 (unhalted core cycles); `cycles` is the generic hardware alias. Do not substitute P0 reference
cycles. Mainline records actual selectors, privilege filters, enable/run ratios and thread coverage.
PC/role attribution remains PENDING in separate profiling runs. No RFO event or aggregate-fill
read/write decomposition is invented; supported extra events require their actual catalog units.

## PRE / POST / PAD-A result ledger

The tuple in every unmeasured cell is (C cycles/command, I instructions/command, IPC, commands/s,
p50/p99/p999, hits/eligible takes, puts by reason, mallocx/sdallocx per completed write,
live bytes/cache bytes/RSS). **Every value of those tuples is PENDING**, not zero.

| Regime | PRE | POST | PAD-A | Decision |
|---|---|---|---|---|
| Benefit: warm one-key/tiny-per-shard SET/INCR p32,p8, inline boundaries | PENDING | PENDING | PENDING | C outside both nulls + reuse engagement |
| Neutral: normal 4096-key/already-high-hit SET, first insert, pure GET | PENDING | PENDING | PENDING | all parity / specified instruction nulls |
| Deficit: mixed classes, huge keys/Extern, DEL/FLUSH, pressure/RSS | PENDING | PENDING | PENDING | every memory/parity constraint |
| Mandatory mixes, p1, all main-command feature/mode cells | PENDING | PENDING | PENDING | no losing cell averaged away |
| Cache vs DRAM footprints; same-/cross-CCX; 32-core owner reproduction | PENDING | PENDING | PENDING | frozen geometry/trace, profile-supported attribution |
| Same-binary nulls, offered R/backlog, all tails | PENDING | PENDING | PENDING | establish valid instrument first |

The controlled serverless result is separate: after a completed eligible wave, POST W/W hits and
zero fresh mallocx for the next W writes; PRE-policy mutant/PAD-A 1/W hits. No 100% live hit-rate
requirement is imposed while grace remains pinned. No MEASURE-RESULT has been received.

## Existing source-law discrepancies, kept separate

Unchanged topology capture at `flatstore.h:946-976` can return Churn during grow/rehash, and point
execution can return SeqChurn (`ex_loop.h:1362-1377`). MGET retains its two-attempt loop (`:1172`).
These pre-existing torn-topology guards conflict with the literal no-writer-fallback/retry scope;
they were neither removed nor broadened. `try_overwrite_read_local` (`flatstore.h:2704`) remains
NotPossible as purity requires. `read_local_reply_string` (`ex_loop.h:969`) still always succeeds,
leaving the old string retry edge intentionally unreachable.

Pre-arming writes/sidecar OOM can conservatively demote a disjoint first read (`rob.h:486,828`);
report fallback_arm_transient separately, not as an explicit key conflict. `ThreadCtx`'s foreign
plain cache-byte read (`thread.h:993-996`, INFO at `t_server.cc:2195`) is still a source-level telemetry
race; allowed staleness is not synchronization. The new unscored owner snapshots avoid relying on
it and do not repair it by taxing the scored path. These are the previously documented armedtax
discrepancies, not new optimizations or new findings attributed to this patch.

No task item was rejected on policy grounds. Live runs and scoring were intentionally left to
mainline as required. Do not merge until the controlled proof, live benefit and ALL parity/memory
constraints pass against these frozen binaries.

## Artifact SHA256 and final diff

| Artifact | SHA256 |
|---|---|
| `build/tomokv` | `beb3443d00eff4ec0697f886366bc77a8537ac8bc63d0a4ec5fcb6e0e7793f70` |
| `build/tomokv-at-recycle-pad-a` | `a7ff5f943dda87fa8164f3d6cd428d7ea5944ca3c0cb0410d5f69e222ffba06f` |
| `build/tomokv-at-recycle-post` | `beb3443d00eff4ec0697f886366bc77a8537ac8bc63d0a4ec5fcb6e0e7793f70` |
| `build/tomokv-at-recycle-pre` | `fb9e9e9c237c466971dde68b3246f0717a3f684b36a311cfcbbce9b446d153f8` |
| `build/tomokv-at-recycle-witness-post` | `1dee1eafdae4c092e0ca13d6579fb8cb2fa1a5a5554d41478b8250f5eb82dda6` |
| `build/tomokv-at-recycle-witness-pre` | `cca39e62e4842dd377a792fd050620f29c8ab176932918d5541e34842a271ebb` |
| `build/owner-arena-at-recycle-borrowed` | `2c097d31ca7d08b86de8e213b97abb147219e4f4f6361b97d5c8f40344334b72` |
| `build/owner-arena-at-recycle-cap` | `f706d03837a60ba83a217028dee19237ba6b94e365ed08a25175230d3652934c` |
| `build/owner-arena-at-recycle-eager` | `72941d9ffe5453edd2866795961354b75a9fe43d70d0842e9fce8f4a4bbbf375` |
| `build/owner-arena-at-recycle-gauge` | `0c1197a1a492886cc2014726e09d3bbb562b1abd28e69439d650eadd15cddebf` |
| `build/owner-arena-at-recycle-never-drain` | `311304881dc626955adc4dacd22b1aef31e2277d64ffe36cc499875b59e0d12b` |
| `build/owner-arena-at-recycle-never-release` | `3f89e8677d513d7fc1bd655e599182b274eb15bb2e251cc0e8031bbbdcb8c34e` |
| `build/owner-arena-at-recycle-no-bytes` | `994f8c579136f7bfdbff2b6dc4ccfd2c55bfade228c6557a6adb82cd80b84e41` |
| `build/owner-arena-at-recycle-no-class` | `b0c353f404c46b7744fafde1d5c44e425540aa0316e17ce91f407a42371b3226` |
| `build/owner-arena-at-recycle-pad-a` | `0d7cec73a17cf5de87d35b2909bb799a1e17393c53fc837e44c797bf0edb76fa` |
| `build/owner-arena-at-recycle-post` | `ea7046b32edad2927c465e6828e15a146a83a049ec8a6120da6d473e4d8dac6d` |
| `build/owner-arena-at-recycle-stale-sink` | `f6af34d176cfccdfe7e29dd89683db6c9024563dacf0a777e4de1ea2b016e958` |
| `build/owner-arena-at-recycle-witness` | `e5f71aa1c36a3ec6d935934eaa1f6dd7da7d9f1dd6ce3afcd12b03983d9c5465` |
| `build/owner-arena-unit` | `ea7046b32edad2927c465e6828e15a146a83a049ec8a6120da6d473e4d8dac6d` |

Full machine-readable receipts are retained in `build/`.

`git diff 32d27ee75 --stat` (including this report and scheduling entry):

```text
 MEASURE-REQUEST                   |  42 ++--
 MEASURE-REQUEST-at-recycle.md     | 408 ++++++++++++++++++++++++++++++++++++
 Makefile                          |   3 +-
 src/store/flatstore.h             |   2 +-
 src/store/flatstore_atomic.inc    |  11 +-
 src/store/kv_block_cache.h        |   5 +-
 tests/at_recycle_checks.inc       | 422 ++++++++++++++++++++++++++++++++++++++
 tests/at_recycle_witness.h        |  52 +++++
 tests/at_recycle_witness_alloc.cc |  23 +++
 tests/owner_arena_unit.cc         |  31 ++-
 tools/at_recycle_analyze.py       | 107 ++++++++++
 tools/at_recycle_artifacts.py     | 172 ++++++++++++++++
 12 files changed, 1248 insertions(+), 30 deletions(-)
```
