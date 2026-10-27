# Wave 8b latency off-path repair

## wave8b

**Correctness campaign in progress:** final offline counts, build/freshness,
negative controls and frozen arms are complete. Final live job receipts will be
listed below. Superseded v1 binaries remain available with `-v1` suffixes.

**Landing held:** disabled EXEC has no latency hooks/store scans, but exact
execindex instruction/body parity is not attained. POST remains +62..258 named
instructions per measured EXEC scope. Merit is NOT RUN; no throughput claim.

Base `83e0b809d`, branch `cx-wave8b`; no push. CPUs 64–79 only, builds -j16,
correctness listeners 20000–20099. Throughput measurements remain owner-owned.

### Before any production edit

All 144 serverless EXEC traces completed: headline `3700b51d7`, execindex
`7ae703778`, and PRE `83e0b809d`; both physical namespaces, both modes,
atomic 0/1, 1/2/4 INCR children, single-shard and cross-shard key placement.
Each trace checks exact replies and bounded completion. One INCR necessarily
has only one shard; the one-child cross case is intentionally the same geometry.

The scope starts at MULTI handling, queues every INCR, executes production
transaction fragments, retires EXEC on IO, reclaims owner records and destroys
the deferred state. It excludes protocol parsing, socket IO, idle loop passes,
fixture glue and library callees. It is a command-scope count, not a rate or
whole-process count. Traces use the production object order and fix clock values.

`docs/wave8b/baseline.json` contains all comparisons; individual function counts,
excluded callees, fixture binary digests and GDB completion receipts are in
`docs/wave8b/instructions/`. Reference source/objects are frozen under build/wave8b.

| Namespace | Shape | Children | Headline | Execindex | PRE | PRE − execindex |
|---|---|---:|---:|---:|---:|---:|
| normal | EXEC-single | 1 | 13598 | 13915 | 15749 | 1834 |
| normal | EXEC-single | 2 | 20713 | 20983 | 24597 | 3614 |
| normal | EXEC-single | 4 | 35988 | 36164 | 43338 | 7174 |
| normal | EXEC-cross | 1 | 13598 | 13915 | 15749 | 1834 |
| normal | EXEC-cross | 2 | 22984 | 23335 | 27145 | 3810 |
| normal | EXEC-cross | 4 | 41604 | 42020 | 49782 | 7762 |
| db0 | EXEC-single | 1 | 12396 | 12686 | 14520 | 1834 |
| db0 | EXEC-single | 2 | 19046 | 19279 | 22893 | 3614 |
| db0 | EXEC-single | 4 | 33277 | 33402 | 40576 | 7174 |
| db0 | EXEC-cross | 1 | 12396 | 12686 | 14520 | 1834 |
| db0 | EXEC-cross | 2 | 21267 | 21577 | 25389 | 3812 |
| db0 | EXEC-cross | 4 | 38833 | 39178 | 46946 | 7768 |

These are instruction counts only. The initial one-child normal trace enters
793 instructions in latency_tracking_retire and 915 in latency_tracking_forget,
despite tracking being off and all stores empty. The scope constructors,
destructors and explicit finish add 92 more instructions. Final attribution,
correctness, identities, artifacts and the owner's merit request follow below.

### Off-path repair and transition audit

The first scan-guard build passed `latencyfix_shape`, `latencyfix_off` and
`execfair` through the gate job interface (four public rows, all eight
mode/engine/atomic timing-interaction legs). Receipt: docs/wave8b/jobs/guards.json.
This is intermediate evidence, not final-source proof.

EXEC now has an untracked instantiation with no latency scope object. The
tracked instantiation retains the original nested active-slice boundaries,
logical-child retirement and retry transfer. One predicted feature branch selects
it at the fragment entry. Retirement and attempt destruction guard the entire
child walk. Blocking/script callers avoid constructing disabled scopes; blocking
completion still pauses any *already active* slice before releasing its Op,
including when CONFIG has just disabled tracking. This is necessary for lifetime
safety and must not be replaced by a check of the current global knob.

CONFIG no clears all pending slices and script children. A cold disable timestamp
rejects an old slice which finishes after no/yes; writers recheck the knob under
the store lock. Histogram retirement verifies its configuration generation before
publishing a combined sample. Bound slowlog callbacks carry the exact start,
instead of reconstructing it after a delayed callback. WAIT stores its initial
probe as a discardable slice; no/yes cannot resurrect an old timer duration.
An ordinary script parent rejected across no/yes consumes any post-enable nested
children before its ROB slot can be reused. Four throwaway broken builds verify
that the scan, stale-slice, delayed-callback and orphan-child checks all fail;
see [controls/receipts.json](docs/wave8b/controls/receipts.json).
No locked server layout grows. WB policy 0 skips
grace-window observation; fused instantiations omit that bookkeeping. Slowlog's
existing per-batch arm and readability assertions retain their semantics.

`wave8b_off` adds one serverless scan/sample/transition witness row. Its
`collect_job` is at gate line 5690, before the quick-tier exit at 5778:
**DQ=+1, DF=+1**. Wave 8 is
+8/+8, so total over headline 798/815 is **+9/+9 → 807/824**. Neither EXPECT
constant is edited. Landing count/label adjustments for abba_selftest are confined
to a throwaway source copy.

### Final command-scope counts and attribution

The full 48-cell EXEC comparison and exact per-function arithmetic are in
[exec-comparison.md](docs/wave8b/exec-comparison.md) and
[exec-attribution.json](docs/wave8b/exec-attribution.json). Every before/after
function delta sums exactly to its scope delta. These are named production
instructions; standard-library callees, IO parsing/dispatch wrappers and socket
work remain outside the scope. The uncontended scopes do not exercise retry
scheduling, blocking wakeup, Lua or IO idle grace. No rate inference is valid.

Representative 2s, atomic=1 cells (all modes/atomic values are in the linked table):

| Namespace | Shape | Children | Execindex | PRE | POST | POST − execindex |
|---|---|---:|---:|---:|---:|---:|
| normal | single | 1 | 13915 | 15749 | 13977 | 62 |
| normal | single | 2 | 20983 | 24597 | 21068 | 85 |
| normal | single | 4 | 36164 | 43338 | 36295 | 131 |
| normal | cross | 1 | 13915 | 15749 | 13977 | 62 |
| normal | cross | 2 | 23335 | 27145 | 23460 | 125 |
| normal | cross | 4 | 42020 | 49782 | 42271 | 251 |
| db0 | single | 1 | 12686 | 14520 | 12749 | 63 |
| db0 | single | 2 | 19279 | 22893 | 19364 | 85 |
| db0 | single | 4 | 33402 | 40576 | 33531 | 129 |
| db0 | cross | 1 | 12686 | 14520 | 12749 | 63 |
| db0 | cross | 2 | 21577 | 25389 | 21705 | 128 |
| db0 | cross | 4 | 39178 | 46946 | 39436 | 258 |

The initial PRE−execindex differences are entirely in eight timing-related
functions/call sites. `f57bc32ad` (latencyfix) introduced parent active slices and
child cleanup; `3577500ef` added child active slices and child retirement.
`4161f1b0c` (wave-8 integration) **moved an already unconditional child retire**
from executor completion to logical IO retirement, and added retry transfer.
Attributing the entire retire scan's instruction count as newly introduced by
4161 would be incorrect. `83fcbf636` adds script-child bookkeeping to existing
stores; those map operations are not reached in these initially empty-store,
non-script baseline scopes. Its compiler/layout effect is still part of the build.

For the normal four-child cross-shard scope, PRE−execindex = 7,762:

| Site / originating lane | Before | After |
|---|---:|---:|
| latencyfix scope ctor/finish/dtor (`f57bc32ad`, `3577500ef`) | 728 | 0 |
| latencyfix child forget (`f57bc32ad`; script erase `83fcbf636`) | 3,660 | 0 |
| latencyfix child retire (`3577500ef`), relocated by integration `4161f1b0c` | 3,172 | 0 |
| Scope call plumbing in multi_execute_task | 153 | see exact ledger |
| Forget-loop plumbing in state destruction | 20 | see exact ledger |
| Integration logical-retire loop plumbing (`4161f1b0c`) | 29 | see exact ledger |
| All POST residual instructions together | — | 251 |

Harness5 and lualibs add no executed code in this INCR-only scope; the successful
readability assertion paths add no baseline instructions here. Iofix3's idle
bookkeeping is outside this scope, so its whole-server cost is **not measured**
by these counts. Execindex's own headline delta is retained separately in every
row. This is source-origin attribution plus exact function accounting, not a
factorial causal estimate for each lane's rate or every compiler instruction.
The remaining POST helper/inlining changes cannot honestly be assigned to one
wave-8 source commit; the ledger explicitly identifies that limit.

[main-comparison.md](docs/wave8b/main-comparison.md) gives all 72 main-command
cases: batch 1/32, 1s/2s, both namespaces, atomic 0/1 for MSET, and slowlog
−1/10000 for GET/SET/INCR. **GET/SET/INCR have zero added instructions**
(deltas −512..−10); MGET/MSET deltas are exactly zero. These use the linked
production batch entries. EXEC uses slowlog −1 and the production transaction
handling/fragment/retirement routines described above.

### Hook audit, compile trials and remaining identities

- EXEC: no tracking scope construction, TLS timing stack, clock call, child
  scan or per-child feature test in the untracked body. A fragment-entry branch
  chooses the tracked body. Retirement/destruction/retry guard whole walks.
- Scatter: existing bound executor/retirer pointers select ordinary functions
  while disabled. Retire/forget/retry/script-begin also reject disabled calls
  directly, without scanning slots. Their checks protect stale bound callers.
- Resumed tasks: inline selection reaches ordinary execute without the old
  unconditional out-of-line timing wrapper. Tracked timing stays out of line.
- Blocking: optional timing scopes construct only while enabled. Pausing an
  already active scope remains unconditional before Op release, including a
  mid-call CONFIG disable; removing that pause would introduce a lifetime bug.
- Scripts: disabled nested calls invoke their handler directly; executor lookup,
  ScriptCall timing and attempt child cleanup are guarded. The final-activation
  child publication repair is retained.
- Slowlog: existing batch arms, escalation and recorder binding remain intact;
  no slowlog semantic change. Readability assertions remain enforced; no
  assertion was removed to improve the trace.
- Iofix3: WB policy 0 skips grace observation/activity/park bookkeeping; fused
  code omits it. Policy 1 retains the selected grace and requires null merit.

Every affected translation unit was re-derived: 14 pinned namespace variants
(main, xshard, acl, climon, genthread, rl2s, reorder) plus 14 default-budget
variants (scripting, latency_tracking, slowlog, tracking, fliplisten, shutdown,
lbplanner). Final pinned recipes, IPA starting sizes, linked scores and choices
are in [budgets-exact/selected.json](docs/wave8b/budgets-exact/selected.json).
[unpinned-budgets.json](docs/wave8b/unpinned-budgets.json) records the 42 default
budget trials (9992/10000/10008). Three variants had different bodies and were
scored explicitly in unpinned-exact-selected.json; 10000 remains selected.
After the final orphan-child correction, six fresh latency_tracking trials also
selected 10000 (budgets-orphan/selected.json). Earlier trials are retained.
Eight xshard candidates also have command-scope counts. Selection is compile-only
and does not establish merit.

| Pinned unit | normal | db0 |
|---|---:|---:|
| climon | 26265 | 26780 |
| xshard | 148585 | 147391 |
| acl | 35758 | 35705 |
| main | 147838 | 146080 |
| genthread | 131218 | 132012 |
| rl2s | 164621 | 167496 |
| reorder | 149103 | 150092 |

A throwaway single-body optional-RAII alternative was counted and rejected:
normal cross-shard four-child EXEC was 42,395 instructions versus selected
42,271 (execindex 42,020). Evidence: optional-counts.json and optional_trial.py.
No experimental implementation is compiled into POST.

The strict gate normalizer inventories **9,897 function groups**: 8,126 equal
headline, 1,007 additional groups equal an isolated lane, and 764 residual groups.
Among 280 EXEC/WATCH groups, 214 equal execindex. Of 78 GET/SET/MGET/MSET and
scatter hot groups, 64 equal headline, eight equal a lane, and six remain
composites. Thus the requested complete body identity is **not achieved**.
[changed-bodies.md](docs/wave8b/identity/changed-bodies.md) lists every remaining
headline difference and its reason; summary.json also lists EXEC/WATCH differences.
No operand/register/offset/assertion immediate was masked to obtain equality.
Identical instruction counts do not imply identical bodies or rates.

### Frozen arms and PAD semantics

- **PRE**: `/home/user/Projects/cx-wave8b/build/tomokv-wave8b-PRE`; SHA-256 `f94fbd1d57873ff32bdf279b796139e0dd94e8cd7f613d9a7f17832ef86af359`.
- **POST**: `/home/user/Projects/cx-wave8b/build/tomokv-wave8b-POST`; SHA-256 `4acdb9baab221726b46589a965802c4175439b9670077997690c20a0c37e040b`.
- **PAD-A**: `/home/user/Projects/cx-wave8b/build/tomokv-wave8b-PAD-A`; SHA-256 `af25884a6904fb0400e120fde7d88ee1976da20f421ca6fcda6b28ddf576aa24`.
- **headline**: `/home/user/Projects/bench-bins/tomokv-headline-3700b51d7`; SHA-256 `56ec64d13cf87d97d75ad955311a44c77ffc87a6798b548d5c4330b6713cd97c`.
- **execindex**: `/home/user/Projects/bins/execindex-post-aee04885`; SHA-256 `aee048859f6f8d84d5aa4e0b30767ad1e8dac4595d383ff634a8226027d1566a`.

**PAD-A is kind (A), a behaviour twin**: unmodified PRE behavior, with POST's
`.text` start (0x1f930) and total size (8,457,095 bytes). PRE's `.text` is
8,435,415 bytes. Padding is unreachable. Individual function positions and data/
TLS layout retain PRE, so this is an aggregate text-layout control, not a claim
of exact per-symbol layout identity. The full link and object hashes are in
pad-a.json. PRE/PAD has 9,758 strictly identical groups, four read-local fence
relocations verified instruction-for-instruction including the return target,
one pub/sub switch table whose seven destinations are verified, and one
unreachable padding symbol (pad-identity/provenance.json). The strict normalizer
misclassifies that relocated table's first two bytes, `p\0`, as a string; it is
unchanged, and the separate provenance check resolves the difference explicitly.

### Maintainer measurement request (NOT RUN in this lane)

Keep latency-tracking **no**, the original cell grammar/geometry and matched
offered load. Use the gate's own instrument on the quiet box. Report rate,
cycles/op, instructions/op, IPC and relevant latency; no instruction proxy
substitutes for rate. Include byte-identical controls in the same session.

1. `calib/exec-merit.py`: 64 connections × pipeline 4, two blocks, the four
   uncontended cells `x2s_a0_unc,x2s_a1_unc,x1s_a0_unc,x1s_a1_unc`. Compare POST
   independently with headline, execindex POST and PRE; compare PAD-A with PRE
   and POST with PAD-A. Then run all eight merit cells (both modes × atomic 0/1
   × unc/hot) with those reference arms.
2. `calib/exec-depth-sweep.py`: both modes and atomic 0/1, placements
   `cross,same-owner,same-shard`, depths `16x1,16x4,32x4,64x4,128x4`, three
   blocks per arm. Preserve the existing sweep shape and evidence. Examine
   64x4/16x4 and 128x4/16x4 alongside the historical 0.90/0.85 depth bounds.
3. Wave-8 nulls, POST versus headline and PAD-A versus PRE: use the unchanged
   28-cell [null-cells.txt](docs/wave8/null-cells.txt). Generic 14 are
   `h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`;
   TTL `ttls,ttlm` retain 20M keys and actual expiry; NOTIFY is `notify_exm`;
   split GET/SET are `h53,h54,h21,h22`; remaining p8 MGET/MSET cells are
   `m05,m26,m29,m50,m53,m74,m77` (`m8g_l0` is already in the generic set).

**Landing verdict:** 2s uncontended EXEC must be within execindex's own cost
(about 1%) of headline. Main-command null cells must not regress under the gate's
rules. POST movement with PAD-A flat supports a behavioral gain; shared movement
with PAD-A does not. Full iteration, performance benchmarks and load generators
are **NOT RUN — reserved to the maintainer**. Append results as MEASURE-RESULT.

### Correctness proof

Final individual gate jobs are running. Their argv, binary hashes, engine/mode,
exits and raw artifact directories are recorded under docs/wave8b/jobs. This is
not a completed full gate and does not produce a landing receipt.

`make all`, every job_production_units target, both live-arms builds and the
blockfix cost fixture built successfully; all 49 make-q freshness checks passed
with the release SHA unchanged (docs/wave8b/build/receipt.json). Final planted
scan and stale-generation controls both abort as required; controls.py records
the exact mutants and failure witnesses. Earlier failed attempts remain in the
job receipts: the unregistered-job attempt and three existing wave8 Lua TRYAGAIN
assertions during the intermediate compile-concurrent run are not hidden.
