exec1s-d final handoff (2026-10-29)

Production source: cf3bdaa9e. Frozen POST SHA-256:
4111f5c6ad1784fc6b95fceedc9efe361cf715dbad97f912e130811ab7544f18.
Subsequent commits contain fixtures, tooling and evidence. All sessions completed.
No push. See MEASURE-REQUEST-exec1s-d.md and docs/exec1s-d/proof-summary.json.

Acceptance remains red: historical seed-22 SAVE Busy rejection unresolved;
X3 idle +7 instructions in both namespaces versus <=+2; unchanged upstream
slowlog assertion fails on both POST and headline PRE. Rate attribution and
depth recovery remain pending the maintainer's measurements. No throughput claim.

Completed evidence:
- Ordinary48 scopes add no instructions; read-local4 exact. Allocation3348/13514
  =0.247743. INCR/depth72 per arm; genuine MSET-child48 per PRE/POST/X12/X3/X5/MERGE.
- Standard differentials pass on both engines: each split0 235, split1 239,
  armed0 230, armed1 234, equivalence16. Seeds7/19/20/23 plus21 uring,22 epoll.
- gates_test passed73 plus14 persistence helpers, isolated. Earlier unchanged
  45-second scheduler deadline failures remain in the receipts.
- All24 isolated zero-copy rows pass, both modes/engines with quiet preflight
  and ASAN unchanged. Broad family832pass8fail; six were preflight refusals,
  the other two are slowlog and its propagated compat2 prerequisite failure.
  Fused supplement215/0; atomic0 scripts3/0 each; AOF CQ57/0 each, positive
  samples including fused executor rings, zero overflow/dropped completions.
- Final selected-job index251 completed variants,1083 passing rows,2 failing
  rows (same slowlog and propagated compat2). This is not a full-gate tally.
-57/57 make-q checks pass: all, all51 literal production targets, MDBQSBR pair,
  cost/binding, blockfix2 pair. Frozen images verified against arms.json.
- Lottery copy and both PAD controls pass gate execfair smoke. Seven existing
  lottery EXEC occurrence cases pass on first attempt with positive W16.

SAVE investigation: unchanged full original split0/seed22 plan passes235 on
C-PRE, MERGE and final POST natively. Admission-entry observers also passed.
Failure-only observers at the actual taken Busy branch destinations passed235
on C-PRE and MERGE, both locations armed and no Busy events. Therefore the
historical rejection is not classified as fixed or pre-existing. Bare repeated
psfix fails repeat6 with a SAVE timeout on C-PRE and MERGE; that is a DIFFERENT
failure. Passive kernel observer was denied EACCES; no system settings changed.

Slowlog: exact unchanged assertion reproduces PRE5/64 fused after an initial
8 passes, POST2/8; both split8pass. Owner commit exposes the list/dirty wake
before IO retirement executes queued SLOWLOG RESET and logging; the blocked
BLPOP log can be cleared. Pre-existing, unfixed, no assertion/manifest weakening.

NOT RUN: full iteration, performance/load generators, flip_saturated,
atomic_floor, atomic_ryow's rate assertion, full lottery nightly campaign.
Reasons and exact maintainer requests are in the report. All work used CPUs64-95
and ports20000-20099. No FIFO; X4 remains disabled; D1-D10/amend1/D4' unchanged.
DQ=+4, DF=+4; EXPECT881/898 unchanged, owner should885/902. Collector6008 precedes
quick exit6119. PAD-A is PRE behavior in the exact POST-layout common image,
larger than standalone release POST; that limitation is explicit. build~27GiB,
all superseded arm sources/probes/large step traces retired, failures retained.
