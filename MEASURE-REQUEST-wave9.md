# Wave 9 landing request

## wave9 integration

Worktree `/home/user/Projects/cx-wave9`, branch `cx-wave9`, headline
`a214652ec262aa9a5eeaeadf129c0ef76ba6c99c`. No push. All integration builds
and correctness processes use CPUs 64–95; listeners use ports 20000–20099.
Performance measurements and the full landing iteration belong to the maintainer.
This report is updated as work completes; pending work is not a pass claim.

### Merge and row ledger

Branches are merged with `--no-ff` in the requested order. The expected net
delta is +74 quick / +74 full, from 807/824 to 881/898. The protected EXPECT
assignments are never edited in this worktree.

| Lane | Requested delta | Integration disposition |
| --- | ---: | --- |
| woundfix | +4/+4 | Merged; last-placement and independent OOM/NX wound gaps retained |
| gaterows5 | +11/+11 | Merged; inline job deferred to protofix; placement stays an explicit make target |
| protofix | +4/+4 | Merged; one four-leg inline job, with original test file |
| crlffix | +1/+1 | Merged; central builders retained; later error sites audited below |
| multifix | +24/+24 | Merged; slowlog hooks composed into wave8b timing-selected body |
| streamfix | +6/+6 | Merged; StreamNode accounting and six roots retained |
| blockfix2 | +6/+6 | Merged; six gate rows; stream-removal diagnostic and failing evidence retained |
| at412c | +18/+18 | Merged through wave8/8b; all eighteen rows retained |

### Integration findings

- Woundfix merged through wave8b's timing-selected EXEC finalizer without a
  textual conflict. Semantic checks with escalated scripts remain pending.
- Layout placement remains a non-gate diagnostic until the wave-10 lineshare
  fixes. Its original failing evidence is retained in the gaterows5 report.
- Blockfix2's stream delete/re-create boundary remains a non-gate diagnostic
  until blockfix3. Its lane evidence will remain visible rather than counted
  as a passing row.

- Multifix was based before wave8b extracted `multi_execute.inc`. Its slowlog
  hooks and commit-bracket PAUSE publication were transplanted into that shared
  body; the tracked/untracked instantiations remain intact. Retry transfers
  retain the outer latency-enabled guard; slowlog accumulation remains separate.
  Directed tracking-off/slowlog and instruction checks remain pending.

### Validation and measurement status

Pending: merged correctness matrix, placement-probe hardening, Tcl reconciliation
and planted regression, compile-only budgets, complete changed-body inventory,
serverless instruction counts, frozen PRE/POST/PAD-A arms and SHA-256s.
No throughput claims. The requested nulls, fixed-anchor race, contended-script
storm and full landing gate are NOT RUN here: maintainer-owned measurements.

### Load-sensitive correctness hardening

- MONITOR: upstream `unit/introspection` sends BLPOP on a deferred connection,
  then polls INFO on another connection. `climon_gate` feeds MONITOR at each
  connection's IO dispatch; feeds to a remote monitor owner are asynchronous.
  There is no cross-connection dispatch/delivery order establishing BLPOP before
  INFO. A global ordering mechanism would add synchronization to command dispatch.
  The runner retries **only** `MONITOR log blocked command only once` once, on a
  fresh server, only after a complete file run with that sole assertion failure.
  The original failed receipt remains `before-monitor-retry.json`. Missing,
  duplicate, timed-out, unrelated or repeated failures remain failures. Nine
  serverless runner controls pass, including planted failure and retry controls.
- Placement: `_lib.probe_keys` now brackets the complete key discovery with
  LBSIGNALS observations and repeats up to four whole probes before yielding any
  keys. Perpetual movement and malformed evidence fail. `tests/debug.py` uses the
  same helper. Atomic torn/window release and ASAN boots additionally disable
  key-LB and automatic flips; no torn-read or window assertion changes. Nine
  gaterows contract controls pass, including never-stable negative control.
- Variant builds: trackfix, notifycompat and aoforder now stage the selected
  source's `tools/assert_map.py`, including reference archives. The other three
  schedule/build consumers (publishfix, lottery, racefix) already copy it.

### Directed lane interactions (first merged build)

The whole `execfair` job passed all eight mode/atomic/engine legs on SHA-256
`b7618f4089cb88a1c0c921c9f13d342024065b3d1813cd5fc89f4403844d4c6c`.
`tests/wave9.py` joins that existing row (no row delta). It asserts exact replies
and state for repeated-key EXEC list publication, an actually conflicted and
escalated script's list publication, a fifth same-IO FIFO script held by PAUSE
WRITE, and stream-node trimming followed by sequential stream removal. The
removal uses CR/LF in the key and group name and requires one sanitized NOGROUP
reply followed by an intact PING frame. The first four FIFO occupants are
read-only scripts; they drain under PAUSE while the queued write stays pending.
Receipts: `docs/wave9/jobs/integration-first.{json,log,tsv.partial}`. This preliminary
build does not substitute for rerunning the job on the frozen landing POST.

### Compile-only and first cost pass

31 pinned units were surveyed PRE and POST; neighbour trials preserve command
bodies before other hot and cold bodies. `docs/wave9/budgets/selected.json` lists
all budgets and trials. The selected build has 9,999 canonical function groups:
8,423 headline-identical, 1,098 changed groups exactly matching a supplied lane
POST, and 478 composed/compiler residual groups. Every group is inventoried in
`docs/wave9/identity-selected2`; remaining command-body differences are under
review, not hidden by masking source lines or member offsets.

The first complete command-scope pass (48 paired cells) adds zero instructions
for GET/SET/INCR/MGET/MSET at batches 1/32 in both modes and namespaces (MSET also
atomic 0/1). These are bounded serverless instruction counts, not rates. Fixture
and final-body work continues, so final hashes/counts will supersede this pass.

The first lane matrix overlapped a binary relink: three RESET rows correctly
failed because the candidate was temporarily not executable. This is an
integration-run scheduling error, not a RESET result. That entire multifix
matrix will be rerun after binary publication has finished; failed evidence is
retained in `docs/wave9/jobs/lane-rows` and its recorded run directory.

- Wound publication and scripts: the generic last-placement path completes the
  cancelled epoch before publishing aborted; `script_group_read` additionally
  checks Wounded on both sides of generic preparation. The `at412-owner` row now
  carries that cancelled script through `script_escalate_handoff`, requiring a
  closed apply bracket, exactly one retry, and no final reply. The hand-off
  preserves cancellation; redispatch creates a new attempt with the old age.
- The woundfix copy-only builder searched for an unannotated function boundary.
  The headline marks `finalize_reservations` always_inline. Its bounded seam
  extraction now recognizes that function name without requiring a bare line
  prefix; all six exact publication insertion anchors still fail closed.

### Frozen command-scope counts

The final fixture covers 100 paired cells: 48 GET/SET/INCR/MGET/MSET, 48 EXEC,
and four read-local GET. Main commands add zero instructions (all deltas <= 0).
Read-local GET totals and every per-function count are exactly equal: normal
2428/49231 and db0 2340/45949 at batch 1/32. Cross-shard EXEC adds 83–333
instructions; repeated-key EXEC with 2/4 children removes 1793–7108. Full counts,
probe hashes, build commands and exact-data checks are in `docs/wave9/instructions`.
Attribution of EXEC's additions is recorded separately; these counts are not rates.

The first complete Tcl job failed both modes only at the newly promoted
`XGROUP DESTROY should unblock XREADGROUP with -NOGROUP`: its NOGROUP reply
arrives, but INFO errorstats does not expose its count. This is the pre-existing,
explicitly stopped INFO statistics dependency in `MEASURE-REQUEST-blockfix2.md`,
not a new merge interaction. The named assertion remains mandatory and red.
Unsupported file setup errors are still matched exactly by the frozen manifest;
they do not explain this failure. No assertion or known-failure name was hidden
to make the integration green. The full compatibility job and planted regression
will retain this limitation in their receipts.

- The gaterows5 R7 bounds row inherited the gate worker's two-CPU load affinity.
  Its real-parser fixture explicitly requires eight CPUs and correctly failed.
  The job now invokes that fixture on its own eight-CPU server slot, matching
  the existing R7 engagement job. Quadratic/eager negative controls are unchanged.
  `make -q` passes for all 55 enumerated production targets/aggregate targets;
  target commands and binary hashes are in `docs/wave9/build-freshness.json`.

- at412 T12 exposed a schedule gap: `script_escalations` increments before
  redispatch acquires claims. Sending the tenth writer at that counter can
  legally order it before the escalated script (`[1,11]`, rather than `[1,10]`).
  The common T1/T12/combined schedule now parks the non-lead APPLY owner with
  the existing hook, proves the lead APPLY ran while the commit remains pending,
  and requires the tenth writer's actual claim-wait counter before reading the
  script reply. Exact replies, nine conflicts, one escalation/commit and AOF
  reload assertions remain. An absent/expired window fails; no retry masks it.

- The old `atomic_survivors` APPLY-window fixture expected TRYAGAIN after a
  real foreign write. At412c intentionally hands that attempt to escalation.
  The fixture now verifies cancellation preserves the foreign write and exposes
  neither partial script result, then drives the real ROB redispatch and owner
  inboxes to one successful escalated commit with exact final values. Its first
  recheck caught a missing inbox initialization in the extended fixture; after
  repair the entire `atomic_units` plus `at412-owner` jobs pass (29 rows), receipt
  `docs/wave9/jobs/atomic-recheck2.json`. The unrelated commit-first arm remains.
- The WATCH no-finalize negative control now recognizes the first invariant
  that the broken implementation actually violates, rather than requiring its
  later redundant assertion. The whole exbatch unit job, with every negative
  control, passes in `repair-rechecks`; failure remains mandatory.
- Lottery's copied-source instrumentation needed current EXEC/epoch/IO anchors
  and a C++ guard around its forced include for Lua C helpers. Its release and
  ASAN variants compile, and all 17 evidence controls pass. The CAS trace marks
  a commit only after a successful decision. Publishfix's copy builder now
  inherits the caller allocation rather than asserting the old lane's CPUs.
  Variant hashes are in `docs/wave9/copied-builds.json`.
