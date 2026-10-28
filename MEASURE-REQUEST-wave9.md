# Wave 9 landing request

## wave9 integration

Worktree `/home/user/Projects/cx-wave9`, branch `cx-wave9`, from
`a214652ec262aa9a5eeaeadf129c0ef76ba6c99c`. All eight branches are merged in
order with `--no-ff`; no push. Builds and correctness processes use CPUs 64–95,
listeners 20000–20099. No performance benchmark or full iteration was run.

**The landing is not green:** the promoted Tcl XGROUP DESTROY assertion still
fails its INFO errorstats check in both modes. The first full Tcl compatibility
run also observed the cross-connection WATCH ordering failure described below.
Neither assertion was hidden. The remaining correctness campaign is recorded in
`docs/wave9/jobs`; its final index distinguishes failures, repaired rechecks and
work still running. Instruction/body proofs and all three requested arms are complete.

### Merges and exact row arithmetic

| Lane | Merge | DQ / DF | Collector line(s), before quick exit |
|---|---|---:|---|
| woundfix | cea648fa7 | +4 / +4 | 5969 |
| gaterows5 | 43210f0e3 | +11 / +11 | 5831–5833, 5835–5836 |
| protofix | 98a4c218e | +4 / +4 | 5834 |
| crlffix | 93f1f97dd | +1 / +1 | 5869 |
| multifix | 353b356f8 | +24 / +24 | 5899 (mode/engine loops) |
| streamfix | b73052087 | +6 / +6 | 5906 |
| blockfix2 | 43e549c4a | +6 / +6 | 5911 |
| at412c | 800b08ef8 | +18 / +18 | 5977 (eighteen cases) |

The quick-tier exit is line **6078**. Every added row is collected before it:
**807/824 + 74/74 = 881/898**, with no discrepancy. The protected assignments
remain **807/824** in the real tree. The maintainer must change them to 881/898
for landing. All 898 declared labels, including duplicate occurrences, exactly
match `tests/fixtures/nullrefresh-ledger-labels.json`. The declaration-only proof
and all 74 individual added labels are in `docs/wave9/{row-inventory,new-row-labels}.json`.
The count validator correctly fails against the protected real constants and
passes in the throwaway selftest copy containing the landing counts.

Gaterows5's duplicate four-leg inline job was omitted; protofix supplies the
single complete job. `layout_placement` remains an explicit native non-gate
diagnostic. Blockfix2's pipelined stream-removal row is likewise parked, with
its 24 failing lane legs preserved. See [diagnostics](docs/wave9/diagnostics.md)
for exact evidence and commands. No wave-10 or pending-owner lane was merged.

### Semantic integration findings and directed checks

1. **Wound publication and escalated scripts.** Woundfix completes cancellation
   before aborted visibility; at412c also checks Wounded on both sides of generic
   claim preparation. `at412-owner` now forces the interval before the wounder's
   epoch publication, then carries the cancelled script through the real hand-off:
   closed apply bracket, cancelled epoch, no final reply and exactly one retry.
   Redispatch preserves age and creates a fresh attempt. The whole owner job passes.
2. **EXEC slowlog, latency retirement and repeated versions.** Multifix predates
   the headline's extracted `multi_execute.inc`. Its slowlog and winning-commit
   PAUSE work was transplanted into the headline's tracked/untracked body.
   `Tracked=false` still erases timing scopes. The latency-enabled guard remains
   outside child retirement and retry-transfer loops. The one API adaptation
   (`21cd3acf7`) passes zero to the newer `slowlog_record` signature only on its
   enabled path. No latency recording callee or additional clock call occurs in
   any of the 48 OFF EXEC traces. Slowlog's own lane cost remains visible below.
3. **Blocking publication, version reuse and escalated commits.** Repeated RPUSH
   children and a cross-owner SET in EXEC wake one BLPOP waiter exactly once,
   leaving two list elements. A genuinely conflicted, escalated script performs
   INCR and two list pushes and publishes its blocked waiter only after commit.
   The headline already contains the ordinary EXEC publication sweep; it is
   retained, not double-added or charged as a new blockfix2 instruction path.
4. **CR/LF framing.** The original 966-site audit stays frozen. All 14 subsequently
   added/moved error calls are enumerated in
   [wave9-added-sites.json](docs/crlffix/wave9-added-sites.json): ten central
   `reply_err` calls and four script WorkError bridges. Protofix decoding, multifix,
   streamfix, blockfix2 and at412c are individually covered in
   [audit.md](docs/crlffix/audit.md). No added raw error/status writer remains.
5. **Stream accounting and removal signalling.** The directed check grows and
   trims 240 stream nodes, checks byte conservation, then removes a stream with a
   blocked group reader. CR/LF-containing key/group names must yield sanitized
   NOGROUP followed by a correctly framed PING. This tests sequential removal;
   the pipelined delete/re-create defect stays a documented wave-10 dependency.
6. **FIFO admission and PAUSE WRITE.** Four same-IO read-only scripts occupy the
   window; a fifth writing script queues. Read-only work drains under PAUSE,
   while the fifth frame remains pending until UNPAUSE. The test requires real
   window waits, exact replies and final values.
7. **Old APPLY-window fixture versus no-refusal semantics.** Its former expected
   TRYAGAIN is obsolete after at412c. It now proves the cancelled attempt leaves
   the foreign write intact and exposes no partial script, then drives the real
   ROB redispatch and initialized owner inboxes to one successful escalated
   commit. The commit-first control remains unchanged. The complete atomic and
   owner jobs pass: `docs/wave9/jobs/atomic-recheck2.json` (29 passing rows).

Items 3–6 are in `tests/wave9.py`, attached to the existing `execfair` row with
no count change. The final POST passes all eight mode/atomic/engine legs, both
normally and under four owned CPU burners sharing its server slot. Loaded
receipts are [loaded-execfair.json](docs/wave9/loaded-execfair.json) and
[jobs/execfair-loaded.json](docs/wave9/jobs/execfair-loaded.json). The earlier
pre-budget passing build is retained as preliminary evidence only.

### Load-sensitive and harness repairs

- **Snapshot-window refusal:** the loaded whole execfair job also runs wave8 and
  requires zero `script_crossshard_window_refusals`. Every reply must complete;
  BUSY/TRYAGAIN is forbidden. All eight legs pass on final POST. The bounded
  burners perform no server workload and produce no performance claim.
- **MONITOR order:** upstream sends BLPOP on one deferred connection, then polls
  INFO on another. TomoKV observes each connection at IO dispatch and forwards
  MONITOR feeds asynchronously; it provides no cross-connection order that makes
  BLPOP precede INFO. Enforcing that total order needs shared dispatch/delivery
  synchronization on the command path. No such hot-path cost was introduced.
  The runner retries **only** `MONITOR log blocked command only once` once on a
  fresh server, only after a complete file run whose sole failure is that exact
  assertion. Original evidence is retained as `before-monitor-retry.json`.
  Missing, duplicate, timed-out, unrelated and repeated failures stay failures.
  All nine runner controls pass; no blanket retry exists.
- **Placement probes:** discovery brackets every DEBUG SHARDS batch with complete
  LBSIGNALS snapshots, bounded to four fresh complete attempts. It yields no
  partial keys. Malformed and never-stable evidence fails. `debug.py` uses the
  same helper. Atomic torn/window release and ASAN boots additionally disable
  key-LB/automatic flips; B+ boots pin key/client LB and flips. No torn-read,
  resume or opened-window assertion was weakened. All paired placement probes
  and their disposition are listed in [placement-audit.md](docs/wave9/placement-audit.md).
- **At412 T12 schedule:** `script_escalations` increments before claims exist.
  A tenth writer sent at that counter can legally win first, yielding `[1,11]`.
  T1/T5/T12 now park the non-lead APPLY owner with the existing hook, prove the
  lead APPLY occurred without commit, and require the rival writer's actual
  claim-wait counter. Exact `[1,10]`, nine conflicts, one escalation/commit and
  AOF reload checks remain; an absent window fails. All complete jobs pass.
- **R7 and negative controls:** R7 bounds now runs its real-parser fixture on the
  declared eight server CPUs, rather than inheriting the gate worker's two load
  CPUs. Quadratic/eager controls remain. WATCH's missing-finalize control must
  fail at its first actual cache invariant, rather than a later redundant one.
  Whole R7 and exbatch jobs pass, including all negative controls.
- **Copied-source builds:** trackfix, notifycompat and aoforder stage
  `tools/assert_map.py`, including archived reference sources. Woundfix's exact
  seam finder recognizes the headline's always_inline finalizer. Lottery uses
  current EXEC/epoch/IO anchors and guards its forced C++ include from Lua C
  compilation; its CAS trace records commit only after a win. Release/ASAN
  lottery builds and 17 evidence controls pass. Publishfix inherits CPUs 64–95
  instead of asserting its old lane allocation. Variant hashes are in
  [copied-builds.json](docs/wave9/copied-builds.json); gate-owned copied-build
  jobs retain their own build/run logs.

### Tcl reconciliation and visible failures

The union of lane promotions is exact: crlffix 1, multifix 8, streamfix 21 and
blockfix2 18. All **48** removed skip names occur in the merged required-pass
lists. [tcl-promotions.json](docs/wave9/tcl-promotions.json) records each source
commit and name. No fixed name was restored to the known-failure list.

The whole Tcl compatibility job ran both modes. POST passes all 64 GEO assertions.
A throwaway binary with the kilometre conversion deliberately changed to miles
fails **16 GEO assertions in each mode**, and the whole job exits nonzero.
The exact names and binary digests are in [tcl-summary.json](docs/wave9/tcl-summary.json).

Two visible limitations remain:

- Both modes fail `XGROUP DESTROY should unblock XREADGROUP with -NOGROUP`:
  NOGROUP arrives, but INFO errorstats does not expose the expected count.
  This is blockfix2's explicitly stopped, pre-existing INFO dependency in its
  report. It remains mandatory and red, separate from the parked pipelined row.
- One final 1s run fails `BRPOPLPUSH does not affect WATCH while still blocked`.
  The Tcl test sends EXEC on the watching connection, then LPUSH on another
  connection before reading EXEC. LPUSH can execute first and validly invalidate
  WATCH; the observed reply is empty instead of `somevalue`. The first complete
  Tcl run and the planted-control runs do not show this failure. This is retained
  as a cross-connection scheduling result, not relabelled as a pass or granted
  another retry. Only the specifically authorized MONITOR assertion is retried.

Exact manifest-known setup errors (unsupported DEBUG/CONFIG setup commands) are
still separately accounted for and do not explain either required assertion.

### Compile-only budgets and remaining bodies

31 pinned units were surveyed, with 62 PRE/POST IPA reports and neighbouring
budget trials. [selected.json](docs/wave9/budgets/selected.json) records the
trials and selected Makefile budgets. Frozen POST has 9,999 canonical groups:
8,423 equal headline; 1,098 changed groups exactly match a supplied lane POST;
478 remain composed/compiler differences. Expanded hot selection includes every
body executed by the scopes: 1,139 groups, 873 headline-equal, 97 lane-equal,
169 residual. The command-hot subset is 86 groups: 47/19/20 respectively.

Every changed body, every clone, its reason, source and full instruction/call-site
comparison is in [reviewed-bodies.md](docs/wave9/identity/reviewed-bodies.md) and
its JSON companion. No opcode, register, branch or member displacement is masked.
The remaining GET specialization changes only its nil-reply tail (Sink::advance
inlining, 792 to 799 bytes); the successful body is unchanged. Shared scatter
bodies compose script admission with MGET/MSET dispatch. These are explicit
identity exceptions, not ignored differences. Merit remains with the null.

### Serverless integration-cost proof

All **100 paired cells** pass exact data/reply checks: 48 main-command scopes,
48 EXEC and four read-local GET. Full PRE/POST tables are in
[instruction-counts.md](docs/wave9/instruction-counts.md); raw counts, build
commands and probe hashes are in `docs/wave9/instructions`.

GET/SET/INCR execute **zero added instructions**, at batches 1/32 in both modes
and namespaces. MGET/MSET also have no positive delta. Read-local GET is exactly
equal in both totals and per-function counts: normal 2428/49231 and db0
2340/45949 at batch 1/32. These counts include production parse/admission/retirement
for read-local, not a substitute lookup implementation.

EXEC uses 1/2/4 INCR children, atomic 0/1, both modes and namespaces. The single-key
arm repeats one key; the cross-shard arm uses distinct shards. Cross-shard deltas
are +83 to +333 instructions; repeated-key 2/4-child deltas are -1793 to -7108.
Every signed function contribution sums exactly to its cell delta in
[exec-attribution.json](docs/wave9/exec-attribution.json). Positive contributions
come from multifix slowlog/PAUSE/version reuse and blockfix2 value accounting;
exact lane-body matches are identified. Shared caller compiler effects have
joint source attribution rather than a fictitious unique optimizer cause.
No integration-only runtime check was added. OFF latency callee/clock checks
remain exact; the 96 independent PC traces reproduce all EXEC counts and bind
each executed PC to its inline source stack. This is instruction evidence only.

### Frozen arms

| Arm | Path under this worktree | SHA-256 |
|---|---|---|
| PRE, a214652ec | build/tomokv-wave9-PRE | 26113ccef516179fd5dc06fda24fd12beff86579e1d7ba56819d2958f2bd4aff |
| POST | build/tomokv-wave9-POST | 2d1b626ac7ba7769d00bd5c0a16693fb928a9c2b3d0a488d41b3f7c8df51fb40 |
| PAD-A | build/tomokv-wave9-PAD-A | 6a6a581bb0b4f6478ac13e30d12a468b2317f282426f26f2b33d43d55b20601e |

Rebuilt PRE matches all **9,785** normalized headline groups; the supplied
headline digest is `5235008bfab65401b335b67b4aff93fbb8cb76e7496d32edd73216885616be4d`.
See [pre-headline-identity.json](docs/wave9/pre-headline-identity.json).

PAD is **(A) behaviour twin**: PRE behavior with inert candidate struct fields
and candidate aggregate text extent. All 30 audited types (both namespaces),
including the eight layout locks, match POST sizes and common old-member offsets.
POST/PAD `.text` address is 133488, size 8551031; unreachable padding is 94112 bytes.
**Limitation:** individual function spacing and data sections retain PRE placement;
this is not an all-cache-line control. Full link/input digests and layout proofs
are in `docs/wave9/{pad-a,layout-comparison}.json`. Copied arm source/objects and
superseded trials are removed after recording hashes, keeping build below 40G.

### Maintainer measurements — NOT RUN

Keep latency-tracking **no**, matched offered load and the existing instrument
cell grammar/geometry. Include contemporaneous identical-arm controls. Use final
POST, rebuilt PRE/headline, and the explicitly labelled **PAD-A behaviour twin**.

1. **Wave null against a214652ec:** unchanged 28 cells in
   [null-cells.txt](docs/wave9/null-cells.txt). Use three blocks for `notify_exm`.
   Generic 14, TTL 20M-key expiry witnesses, split GET/SET and p8 MGET/MSET retain
   their existing acceptance rules. Compare POST/headline and PAD-A/PRE.
2. **EXEC merit:** all eight 1s/2s × atomic 0/1 × uncontended/hot cells, 64
   connections, pipeline 4, 16 generator threads, **three** 20-second ABBA blocks.
   Compare POST/headline and PAD-A/PRE. Report completed EXEC/s, writer share,
   retries, claim visits, fast polls, cycles/op, IPC and instructions/op.
3. **Depth sweep:** both modes and atomic settings; cross-owner, same-owner/
   different-shard and same-shard; 16×1, 16×4, 32×4, 64×4, 128×4, three blocks.
   Retain the historical 64×4/16×4 >=0.90 and 128×4/16×4 >=0.85 cross/same-owner
   criteria and exact order-violation checks.
4. **Fixed-anchor race against 991d48f65:** generic 14, EXEC merit above, and
   read-local cells with three blocks. The explicit read-local selection is every
   `rl=1` cell in the 28-cell list: d32g_l1, d8s_l1, d32s_l1, x9_32_l1,
   notify_exm, m26, m29, m74, m77. Retain the anchor independently of the wave null.
5. **At412c contended-script storm:** T6 shape, PRE/POST, three 30-second ABBA
   blocks; successful scripts/s plus EXEC/plain-writer progress, refusals and
   WATCH aborts reported separately. Require exact final data, zero POST refusals
   and zero atomic_txn_order_violations; retain escalation/FIFO counters.
6. **Full landing `tests/gate.sh iteration`**, after the owner updates EXPECT to
   881/898 and resolves the visible mandatory Tcl failure.

Rate at matched offered load decides merit; cycles/op, IPC and instructions/op
explain it. Main-command cells must not regress under the gate's existing rules.
A POST movement shared by PAD-A is not evidence of a behavioral gain. No throughput
claim is made here. Append the maintainer result as MEASURE-RESULT.
