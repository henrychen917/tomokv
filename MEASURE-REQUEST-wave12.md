# Wave 12 integration and measurement request

## wave12 integration

Work in progress on `cx-wave12`, based on headline `e32b04a44`. No push.
Owner approval D12 authorizes design A. The three lane reports, including
flushfix2's inherited findings and the design review, were read before merging.

Merge order: `15acf5102` (cx-flushfix3), `83b29aaa5` (cx-trackorder),
`3adae5254` (cx-maxmemrace), all with two-parent `--no-ff` merges.
Only the FLUSH merge conflicted, in five Makefile inline budgets. Initial
resolution preserves both source changes and applies the additive budget
deltas pending compile-only re-derivation. Lane branches remain untouched.

All builds and authorized correctness work use CPUs 64–95 and ports
20000–20099. Performance measurements, load generators and the full iteration
are reserved for the maintainer. No throughput claim is made.

The remaining correctness campaign is in progress. The row census, named-skip
sweep, binary builds, compiler trials, instruction census and production-unit
freshness proof are complete. EXPECT_QUICK/EXPECT_FULL remain unchanged.

### Exact source-declared rows

The headline declares 977/994. The merged source declares **999/1016**, DQ=DF=+22,
with no removed label. `docs/wave12/row-inventory.json` records every row against
its collector LINE and the quick exit. Flushfix2 adds 14 directed + 2 lifecycle
rows, flushfix3 adds 4, trackorder +1, maxmemrace +1. All are before the quick exit.
The owner should set EXPECT_QUICK=999 and EXPECT_FULL=1016 at landing.

The initial source census falsely reported 1001/1018: gate_ledger_fixture ignored
conditional assignments in job_flushfix2, inventing ASYNC legs for three cases
and omitting FLUSHDB. The integration writes the same seven case/command/mode
combinations explicitly, extends the static parser's finite split grammar to
colon-separated cells, and adds a directed 14-label product check. Runtime
coverage and row count are unchanged; no test was removed. The checked-in label
fixture now matches the actual declarations, including FLUSHDB. The earlier
incorrect inventory remains visible in commit 787fd64ae.

### Semantic audit, before runtime proof

- R3 range conflict detection remains on the script validation path. Cached
  script metadata owns immutable source/flags; the persistent interpreter's
  activation context is rebound for each run. Neither cache substitutes for
  the current activation cut, so a retained compiled body cannot hide FLUSH.
  PAUSE classifies scripts from the same no-writes metadata before execution;
  FLUSH is classified as a write and its range does not mutate script flags.
- The FLUSH unit retains atomic admission through collapse. FLIP/LB drains
  therefore wait for its admission to retire. Wave11's stage actions still
  use flip_stage_owed; the FLUSH continuation wake remains unconditional.
  The live eight-leg witness remains required; this source argument is not
  an abort-free runtime result.
- climon_flush_completed still runs at ROB retirement after all shard effects
  finish, before reply assembly, with the originating Op still Done. Thus the
  trackorder helper sees the intended SYNC/default boundary; ASYNC retains
  deferred OOB emission. Separate REDIRECT streams have no total byte order.
- CONFIG remains an AllShards operation, separate from Kind::Flush. Every
  fragment applies the latest memory configuration on its current owner;
  configure_maxmemory changes admission/eviction settings, not range records,
  floor eligibility or poison lifetime. Existing MVCC guards keep eviction
  from destroying retained FLUSH preimages. No added fragment discriminator
  reaches ordinary GET/SET/INCR.
- The central reply-builder audit is extended in docs/crlffix/audit.md and
  wave12-added-sites.json. No new raw error/status writer was found.

### Delivered binaries and layout control

Production source is frozen at `5a9f38173`; subsequent changes are harness and
evidence only. `build/tomokv` equals the frozen POST. All three arms were built.

| Arm | Worktree path | SHA-256 |
|---|---|---|
| PRE, source e32b04a44 | `build/wave12/tomokv-PRE` | `02796cdccee7fd16ffaa0dff2633b0d5c30ecdf3c59d404b5a2bb6135a764e48` |
| POST | `build/wave12/tomokv-POST` | `bded27b18371edf7a43df171f042444d6c7f6d34c2fe2bd87f6b83b13c9356d4` |
| PAD-A | `build/wave12/tomokv-PAD-A` | `aee862288a87c0ea45eeb3f2b9ef5c367b0366fb3c88bc2849669583499fd647` |

The rebuilt PRE's `.text` and `.data` exactly equal the supplied headline.
Its `.rodata` differs only in the two eight-character INFO build identifiers;
[the binding](docs/wave12/pre-binding.json) records the supplied headline hash.

PAD is **(A) behaviour twin**: PRE behavior, inert POST `GroupAux` fields,
POST's `.text` origin/extent and `.tbss` size. PRE text is 8,729,431 bytes;
POST/PAD-A text is 8,850,599 bytes, both starting at 182,960. The TLS control
adds 32 unused bytes, accounting for both namespaces. Individual function and
data addresses are not matched. This is the same limited aggregate layout
control used by the lanes; it cannot isolate every cache-placement effect.
[PAD recipe and section receipts](docs/wave12/pad-a.json),
[final arm manifest](docs/wave12/arms.json).

### Compile-only budgets and body identity

There were 301 distinct compile trials across 59 pinned objects and 155 linked
candidate audits. The selected changes from the initial merge are normal
`t_server` 33583→33750 and normal `rl2s` 164680→164705. The db0 `t_server`
budget stays 34177 to preserve maxmemrace's CONFIG body; the generic residual
score alone preferred a budget that lost that identity.
[All trials and selection](docs/wave12/budgets/final-selected.json).

All 12 dedicated GET/SET and captured-local-MGET bodies equal the headline.
The explicit mechanism check finds 36 FLUSH/R3 bodies equal to flushfix3,
two invalidation-order helpers equal to trackorder, and 12 CONFIG/apply bodies
equal to maxmemrace. [Focused body proof](docs/wave12/identity/focused-bodies.json).

The strict whole-binary inventory is 10,279 groups: 9,292 headline-identical,
828 changed groups identical to a lane POST, and 159 residual groups. Twenty-five
residuals have identical encoded instructions and equal eight-byte constants;
only objdump's neighboring-symbol labels differ. The strict count is retained.

Exact identity is **not complete for shared bodies**. Of 88 command-hot groups,
54 equal the headline, 22 equal a lane and 12 are residual scatter/dispatch
groups. FLUSH's normal `flush_redispatch<false>` outlines `note_lane_full`;
db0 `execute_flush` outlines `atomic_read_floor`. These two lane bodies do not
equal the isolated FLUSH POST. FLIP bodies retain wave11's `flip_stage_owed`
and stage actions, which are absent from flushfix3's wave10 base. Shared
dispatch combines FLUSH routing, CONFIG owner binding and wave11 script/PAUSE
handling. No body was made identical by removing an approved behavior.

[Every changed body and its reason](docs/wave12/identity/changed-bodies.md),
[exact residual instruction diffs](docs/wave12/identity/residual-instruction-deltas.json.gz),
and [the full census](docs/wave12/identity/summary.json) retain these exceptions.
Identity remains a proxy; the maintainer's merit run decides acceptance.

### Serverless integration-cost proof

The production-object fixture counted 244 native cells and 96 Lua-inclusive
warm-script cells. It covers both modes/namespaces, atomic 0/1, batches 1/32,
read-local GET, EXEC with 1/2/4 children on one/cross shards, warm EVAL/EVALSHA
(plus FCALL), and empty/eight-key FLUSHALL. Every executed native body and
assembly stub binds to production: final native 696 and Lua 432 checks, zero
mismatches. PRE also binds to the supplied headline, including 87 FLUSH checks.

| Activation family | POST−PRE instruction range across requested cells |
|---|---:|
| GET | −1120 to 0 |
| SET | 0 |
| INCR | −1248 to 0 |
| Read-local GET | 0 |
| MGET | −11008 to −6 |
| MSET | −54824 to −9 |
| EXEC, one shard | −326 to −23 |
| EXEC, cross shard | −310 to −47 |
| Empty/small FLUSHALL | +36877 to +37762 |

These are totals per activation, including the batch, not cycles or rates.
GET/SET/INCR execute zero added instructions. The db0 GET/INCR reductions are
35/39 instructions per operation in these scopes. Native EVAL/EVALSHA can add
1–25 instructions versus wave11 in normal-namespace cells: the FLUSH kind
classification, range-aware scatter lifecycle and compiler outlining account
for the decomposed changes. Against the retained scriptfix3 reference, **all
EVAL/EVALSHA native and Lua-inclusive cells are no higher**. The extra FCALL
control has four small positive comparisons, at most 11 instructions; it is
reported rather than folded into the EVAL claim.

FLUSH's added work is the approved atomic range unit, epoch/participant
publication and collapse lifecycle. The census excludes shared-library
instructions, networking/syscalls and idle-loop work; its fixture uses no live
server. [Every cell](docs/wave12/instruction-comparison.md) and
[every delta's exact function decomposition](docs/wave12/instruction-comparison.json)
are retained. The scriptfix3 comparison uses wave11's bound historical receipts;
that reference was not rerun in this wave. No throughput conclusion follows.

### Tcl skip sweep and manifest interactions

All **259** original named skips received three fresh isolated attempts in
each mode: **1,554 attempts**, no missing-assertion passes. Forty-five names
(58 assertion occurrences) passed all six attempts and were promoted. The
manifest now requires **1,875** occurrences across 37 files and retains 214
named skips. The three lane merges themselves changed no manifest counts.
[Per-root retained failures](docs/wave12/tcl-skips/README.md),
[full sweep summary](docs/wave12/tcl-skips/summary.json.gz), and the numbered
compressed receipts retain every attempt.

Of the historical 23 SCRIPT-UNDECLARED-KEY names, three were already required
passes on the headline; 15 of the remaining 20 pass and are promoted. Five
still fail: the function MONITOR case, Lua-number conversion, trim-string,
write-on-OOM and script-tracking cases. Their current first failures are listed.

The first full manifest run exposed two harness interactions. The promoted
slowlog trimming assertions inherited `slowlog-max-len=0` from the retained
zero-capacity test while their restoring predecessors were skipped. Existing
`isolated_tests` support now requires both unchanged assertions on fresh servers.
The WATCH cross-connection ordering retry was also disabled by a separately
declared block-setup error. It now permits one fresh retry of either named
ordering assertion while preserving exact setup-error accounting. Seven
negative controls reject missing, duplicate, still-failing or unrelated
assertions, unknown setup errors, incomplete runs and timeouts. No assertion
was deleted and no tolerance widened.
[Initial failures and directed controls](docs/wave12/tcl-sequence-findings.json).

The final harness was also tested with the planted CLIENT-LIST-CMD-NAME
regression through the complete Tcl gate job in both modes. Both jobs failed;
only `unit/introspection` failed, including the intended CLIENT LIST command
name assertion. All other manifest files passed. The mutated source and binary
were confined to a throwaway build and removed after recording their hashes.
[Both negative-control attempts](docs/wave12/isolated-regressions.json).

### Correctness receipts completed so far

The primary whole-job invocation completed **269 jobs, 993 passing row
executions and zero failures**, on the frozen POST. It is a selected partial
invocation, not an iteration receipt. Production source and binary hashes were
stable throughout. Only the Tcl runner, manifest and Python harness tests
changed during it; the affected jobs were excluded from this invocation and
are replayed separately. [Primary receipt](docs/wave12/jobs/landing-main-2s-uring.json),
[exact harness delta](docs/wave12/primary-harness-delta.json).

The primary campaign has passed all 14 FLUSH rows: 112 target legs and 14 Redis
oracle legs. Every target leg also passed the directed cached-EVALSHA / retained
range / CONFIG interaction, with positive range-read, post-version, script
conflict, slow-collapse and chunk-cache-hit counters and final script result
`[1,1]`. Failed arming would exhaust bounded fresh attempts and fail the row.

Tracking order passed **20,736 target cases** (24 geometries × 864) against
864 Redis 7.4 oracle cases. This includes FLUSHALL/FLUSHDB, default/SYNC/ASYNC,
RESP3, RESP2 REDIRECT, RESP3 REDIRECT, pipelining, own/other connection,
NOLOOP and tracking modes. Complete per-stream bytes match the oracle;
independent REDIRECT streams are not assigned an artificial total order.

The maxmemory row passed all **48 target geometries** and the oracle, three
trials per case. Every target witnessed its required open window. No failed
OOM/admit/evict assertion was observed. The complete leg inventories, raw JSON
archives and hash bindings are retained in
[the primary interaction proof](docs/wave12/primary-semantic-runtime-proof.json).

`make all` and all production-unit builds/freshness queries passed: 64 checks,
including the 55 production-unit targets/arms, the two mdbqsbr live arms,
blockfix cost binding, blockfix2 and both namespaces of flushfix2/3. The complete
commands and `make -q` results are in
[production-units.json](docs/wave12/production-units.json).

The remaining whole-job matrix and final isolated reruns are still in progress.
The initial Tcl promotion run failed on the two manifest interactions above.
The next run passed all 1,875 required occurrences in 2s; 1s hit the unchanged
upstream Lua GC watchdog while other correctness stress jobs were active.
The first Python harness run likewise hit its unchanged one-slot watchdog
during concurrent compilation. These attempts are retained; quiet full-job
reruns, with unchanged deadlines, are required before reporting completion.

### Maintainer measurement request — NOT RUN here

Use the frozen arms above and the gate's existing matched-offered-load
instrument, acceptance rules and reviewed geometry. Retain contemporaneous
identical-arm nulls. Rate at matched offered load is the verdict; cycles/op,
instructions/op and IPC explain it. Require zero main-command regression.
PAD-A should remain flat when attributing an improvement to behavior. Scatter
above 2% on identical arms invalidates the run for investigation.

1. Wave null: POST versus supplied headline `e32b04a44`, the unchanged 28 cells
   in `docs/wave12/cells/null28.txt`. Use three blocks for p8g, h05 and h06;
   retain the standing three-block notify_exm control and other cell settings.
   Include the rebuilt PRE/PAD-A pair as the labelled layout control.
2. Fixed-anchor race: POST versus
   `/home/user/Projects/bench-bins/tomokv-headline-991d48f65`, with the generic
   fourteen and nine read-local cells in `docs/wave12/cells/`, plus EXEC below.
   Keep this three-block comparison separate from the wave null.
3. EXEC: `/home/user/Projects/calib/exec-merit.py`, PRE/POST,
   `--conns 64 --threads 16 --cells all --blocks 3 --secs 20`. Preserve all
   eight mode/atomic/uncontended-hot cells, pipeline four, two INCR children,
   four competing writers in hot cells, the driver's balancing/FLIP settings
   and one hashed benchtxn. Require zero order violations; keep EXEC and plain
   writer results separate.
4. Contended script: `/home/user/Projects/calib/script-storm-merit.py`, PRE/POST,
   `--blocks 3 --secs 30`. Preserve T6: 2s 6:2, 16 shards, atomic 0, databases=1,
   two owners, eight EVAL clients, four EXEC, four WATCH/EXEC and four plain
   writers. Require exact final values and zero refusals/order violations.
5. FLUSH latency: `calib/flush-latency-merit.py`, POST/PRE/PAD-A with
   `--third-kind behaviour-twin --blocks 3 --populations 0,1000000,10000000
   --trials 100 --empty-trials 1000`; retain both modes, namespaces, atomic
   settings and SYNC/ASYNC. Preserve RTT and RSS boundaries separately.
6. Writer wait: `calib/flush-writer-wait.py`, the same three arms and PAD kind,
   `--blocks 3 --population 1000000 --schedules same-key,disjoint-key,no-flush`.
   Preserve matched offered load, calibration, percentiles and the single
   worst stall. D12 accepts about 1.5–2× the old single worst populated-flush
   writer stall; it does not authorize percentile or main-command regression.
7. Landing gate: owner applies **999/1016**, retains the prepared label fixture,
   and runs `tests/gate.sh iteration`. Partial jobs here do not certify that gate.

For instruments above, explicitly select scheduled CPUs and ports; do not use
their defaults while other lanes run. `docs/wave12/measurement-inputs.json`
binds cell files, driver sources and anchors. No performance benchmark or full
iteration has been run by this lane.
