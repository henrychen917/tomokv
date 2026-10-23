# wave5 landing request

## wave5 integration

Base: `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`. Worktree and branch:
`/home/user/Projects/cx-wave5`, `cx-wave5`. No push. Builds and correctness
execution are confined to CPUs 64–95 and ports 26800–26899. Performance
measurements and the full iteration remain reserved to the maintainer.

All seven lane reports were read before their merges, including txnorder2b's
final additions and trackfix2's superseding design. The final reviewed WIP
states are preserved. Seven separate `--no-ff` merges retain this order:

| Lane | Frozen branch tip | DQ | DF |
| --- | --- | ---: | ---: |
| txnfix | 8dd5b8166 | 31 | 31 |
| bugs5 | 46221fd29 | 3 | 3 |
| compat3 | 751c3b586 | 6 | 6 |
| trackfix | ba03711ea | 2 | 2 |
| fliplisten | 4661b0c46 | 4 | 4 |
| netfix | c98b92959 | 5 | 5 |
| iofix | fcb52cd49 | 4 | 4 |
| Total | | 55 | 55 |

Required landing counts are **740 quick / 757 full**, from **685/702**.
Both protected assignments are unchanged. The independent label fixture was
composed from the seven lane inventories, including compat3's six declared
labels missing from its fixture. The merged source and fixture both contain
757 labels, and their multisets equal baseline plus every lane delta exactly.
No row is added by the directed integration subchecks.

### Merge resolutions and interaction review

- FUNCTION memory admission wraps txnorder2's script APPLY on the actual
  execution owner. The transaction's phase/preparation checks and admitted
  callback scope are both retained. The new EXEC subcheck exercises one-key admitted callbacks on both owners, including partial writes before a Lua error and cap restoration; validation is recorded below.
- The owner cron retains netfix's reclaim/purge calls and uses iofix's effective
  hz for both visit share and deadline. Empty-client passes still purge already
  reclaimed pages. Runtime proof is pending.
- FLIP listener state, transaction owner counters/retry lanes, and the hz/sleep
  coordinators all remain present in Server's cold tail. Locked layout assertions
  pass in the first merged production build.
- CONFIG duplicate-parameter detection retains the union of the network,
  encoding, hz and dynamic-hz rules.
- The initial additive inlining budgets were followed by 29 PRE/POST IPA trials,
  a neighborhood scan and linked-body selection. The generated audit retains
  every changed body and every residual hot group’s call sites against all eight
  references. Source attributes restore owner predecessor checks, WATCH predicates,
  FLIP pause checks, deferred retries and commit-flush call boundaries that shifted
  after composition. Final identity and counts are recorded below.

### Validation in progress

The initial merged `make -j32 all` passes. The slowlog completion repair,
directed checks, full requested partial-job matrices, instruction counts,
identity inventories, production-unit freshness and final SHA are in progress.
No correctness or merit completion is claimed by this checkpoint.

### Slowlog repair and directed control

The armed exact-operation path no longer calls `slowlog_capture` before execution.
A stack timing scope completes before Done (and before AOF owns completion); the
recorder checks the measured threshold before copying argv or retaining the immutable
client identity. Blocking and deferred scatter completion use the same scope.
The ordinary executor specialization contains no timing-scope test. Exact timing
has a separate cold helper so batch-average timing does not inherit its frame.

The directed core fixture forces elapsed time above the default 10ms threshold
without a workload or sleep, checks that the entry already exists at the Done hook,
then renames and removes the client directory entry. It covers disabled logging,
fast armed logging and threshold crossing in both modes. The negative control
publishes Done first; it must fail the before-Done assertion. Both controls are
part of the existing core lifetime row, so DQ/DF does not change.

### Interaction findings

* Writer episodes retain their owner-side ready/commit brackets before tracking
  certificates and Done. Tracking observation happens after predecessor parking;
  retrying fragments cannot certify an unexecuted read. Blocking serves retain
  their writer/WATCH brackets and notification execution scope. Async transaction
  notification batches are sealed only after joined publication at retirement.
  The tracking clock is global, so no new owner-local state can be stranded by migration.
* FLIP keeps retained listener descriptors in the server handover state. Client
  recv cancellation/reclaim and listener cancellation have separate tags. IO stops
  dispatch and cron during handover; DEBUG SLEEP polls through the worker membership
  scope on both IO and executor tenures and uses the registered wake path.
* TLS session cache state stays on the shared SSL context, not a listener owner.
  Handover retains that context; idle reclaim requires empty buffers and does not
  free pending TLS, send or ROB data. The existing listener and TLS matrices cover
  both successful and rollback handovers plus cipher/session behavior.
* Effective hz sets cron cadence and the per-pass client share. Reclaim’s idle age
  remains elapsed-time based; empty passes still purge previously reclaimed pages.
  Dynamic hz therefore changes visit frequency without changing the idle predicate.
* FUNCTION admission wraps script APPLY on its actual owner after txnorder2’s
  phase tests. The supported EXEC check dispatches independent one-key callbacks
  to both owners. A single cross-shard FCALL inside EXEC retains its existing
  CROSSSLOT limitation; the integration does not claim to add that command surface.

### First diagnostic attempts (retained, not passing evidence)

The first new-lane cohort found that the supplied Redis 7.4 binary has no TLS
support. Its TLS oracle legs failed loudly. An unmodified TLS build of the same
`f103d127` source was made inside `build/wave5/redis74-tls` with `BUILD_TLS=yes`;
TCP still uses the supplied binary. Oracle hashes and build provenance are retained.
That cohort also overlapped a relink: one boot saw a non-executable output and one
GDB listener-control boot saw changed addresses. Its `binary_stable=false` receipt
invalidates it as final evidence. Later cohorts use immutable SHA-named binary copies.
No failed leg is counted as a pass or removed from the final inventories.

### Directed integration defect: FUNCTION memory flags in EXEC

The new flags leg exposed `EXECABORT` under maxmemory even for admitted
`allow-oom` functions. EXEC cloned the declared write key before entering the
FCALL handler, so `atomic_admit` rejected the clone before FUNCTION's memory
scope could apply. The repair resolves the function/flags once and runs EXEC's
owner-version preparation inside that admission scope, before invoking the same
resolved callback. A second registry lookup is avoided so a concurrent library
update cannot change the flags between admission and invocation. A parked
preparation clears the Lua stack and restores the cap before retry.

The directed check uses callbacks on both owners, both uncapped and over-cap,
requires successful admitted writes and writes retained before a Lua error,
verifies subsequent reads within EXEC, rejects an ordinary non-admitted function
without changing its key, and checks that a following ordinary SET still sees
OOM. It remains a subcheck of compat3's flags row, with every original leg.

### R7 additive link inventory

The frozen headline has **146 normal / 147 db0** off-path physical bodies.
Six lane POSTs have the same inventory. FLIP listener handover's new translation
unit contributes exactly **six additional bodies in each namespace**: NoBorrow
parser clones (hot/cold at batch 0 and 32) and two owner-conflict closures.
The merged link has **152 / 153**, exactly the sum, with no other name/count delta.
The frozen fliplisten POST itself has 152/153 even though its branch retained the
older checker constants. `docs/wave5/r7-inventory/` contains all nine links' full
name/multiplicity inventories and the 12-entry merged delta.

The `wave5` checker inventory explicitly requires every added clone/closure and
retains all prior instruction/encoding comparisons. It does not mask or discard
any body. The FIFO behaviour twin compares all **305** physical bodies; the row
also requires missing policy, missing split-local parser, missing fliplisten clone,
and changed-opcode controls to fail. Legacy inventory selections remain available
for frozen historical binaries. This changes no public gate row count.
