# Wave 10 landing request

## wave10 integration

Worktree `/home/user/Projects/cx-wave10`, branch `cx-wave10`, headline
`393d6ceb129d8c99dffd70959d6a19267c525fe0`. No push. Builds and authorized
correctness work use CPUs 64–95 and ports 20000–20099. Performance runs and the
full gate iteration remain with the maintainer. This is an in-progress record;
unrecorded verification is not a pass.

Merge order: snapfix2, blockfix3, scriptfix2, exec1s-d, pubtrackfix, infofix,
rlfix4. Every lane is merged with `--no-ff`. The committed blockfix3 report is
the `## blockfix3` section of `MEASURE-REQUEST-blockfix2.md`; the separately
named `MEASURE-REQUEST-blockfix3.md` does not exist on that branch.

LAT-HIST-2 is included under the maintainer's 2026-10-29 ruling, with exact
individual command timing. The global slowlog ring is excluded. Protected
EXPECT assignments remain unchanged; final declared rows and their collector
positions will determine the requested landing counts.

### Semantic interactions

Pending source audit and directed checks: prepared snapshot capacity with eager
EXEC reclamation; shutdown/script apply brackets and EXEC retirement; eviction
with prepared/capturing snapshots and pinned versions; script escalation and
wound publication; NOGROUP accounting; disabled EXEC latency timing; read-local
readers with X2; central CR/LF error framing; and the Tcl promotion union and
planted regression.

### harness

The named slowlog ordering assertion will use the existing one-fresh-server
ORDER_TESTS mechanism, under REGISTER item `SLOWLOG-EXEC-BLOCKED-ORDER`.

### owner-visible

rlfix4 retains `no_stack_protector` on `FlatStore::hash_key`. This is an explicit
hardening relaxation. Its integrated-layout merit remains for the maintainer.
exec1s-d's historical seed-22 SAVE rejection and X3 idle rotation's seven extra
instructions remain open evidence, not claimed fixes.

### Delivery and measurement

Required arms: PRE, POST, POST-minus-rlfix4, and PAD-A (kind A, PRE behaviour with
candidate layout control). Final hashes, control limitations, instruction/body
receipts, correctness results, NOT RUN items and exact maintainer cells will be
recorded here before delivery. No throughput claim is made.

Snapshot merge resolution: retain wave 9’s stronger at412 APPLY-window witness.
Retain the existing `xshard_complete_script_final` close, omitting snapfix’s
redundant `script_snapshot_done` close; every Final still closes owner-side.
Initial Makefile choices are provisional until the compile-only budget trials.

### Exact declaration inventory

All seven lane merges are complete: snapfix2 `f146fdbca`, blockfix3 `047ccf869`,
scriptfix2 `8fe881fa2`, exec1s-d `30a83e4d7`, pubtrackfix `87e964b71`, infofix
`d47af69b2`, rlfix4 `d53549aa4`. The commit immediately before rlfix4 is
`ba2130b37`; its production source is identical to the built slowlog-exclusion
commit `e98831c81` (the intervening commit changes only the Tcl harness).

The full source declaration inventory is 963, exactly matching the explicit
fixture including duplicates. Required landing counts are **946/963**, from
881/898 plus **65/65**: snapshot 4, restored blocking row 1, scripting 48,
EXEC 4, pubsub/tracking 4, retained INFO/latency 4, read-local 0. Blockfix3 adds
zero on its lane base but restores one row parked on this headline; infofix
loses its global slowlog row. Neither exec1s-d nor pubtrackfix supplied their
four labels in the merged fixture; those eight declarations are now explicitly
listed. The interaction checks extend existing rows and add no public row.
Collector positions and final receipts will be recorded after harness edits.

### Interaction source findings and new witnesses

- Snapshot preparation reserves at least the old table capacity. X2 calls the
  existing bounded cleanup with the commit cutoff read before the reader floor;
  collapse refuses an active capture. New `exec1s` subcases hold actual pending
  EXEC versions, prepare/mark around eager cleanup, complete a real capture,
  and check exact final values. Both modes and atomic settings run the same
  cases, with ordinary and armed read-local retirement.
- Eviction rejects candidates requiring versions and returns immediately during
  capture. The new subcases require zero eviction while pins/capture are live,
  then require actual eviction after their release. Prepared capacity and the
  capture stream must remain usable throughout.
- The X2 armed collapse still selects `atomic_free_entry_read_local` and QSBR
  object retirement. rlfix4 changes admission/hash code and does not touch that
  selection. The existing concurrent word/byte-wrap TSan falsifier remains in
  every complete exec1s job; new snapshot subcases require deferred retirements.
- scriptfix2's new invocation environment stays inside each optimistic attempt;
  at412c's claim/wound/handoff machinery is retained. `tests/wave10.py`, attached
  to the existing eight-leg execfair job, adds the witnessed nine-conflict
  escalation schedule for a shebang script, uppercase EVALSHA, and uppercase
  FCALL using restricted library initialization and numeric child arguments.
  The existing at412 owner check still covers the wound-publication interval.
- Blockfix3 owns the NOGROUP increment at the actual XREADGROUP reply. INFO reads
  that counter and its RESETSTAT baseline. Infofix contains no generic formatter
  accounting hook, so the merged tree does not introduce double accounting.
- The new error sites retain central CR/LF builders; the complete supplement is
  `docs/crlffix/wave10-added-sites.json` and the wave10 section of its audit.

Harness changes so far: add the single named slowlog assertion to ORDER_TESTS
under `SLOWLOG-EXEC-BLOCKED-ORDER`; expand the existing retry falsification test
over every named map entry. All ten Tcl harness tests pass. No blanket retry,
new timeout or assertion tolerance is introduced. New snapshot/eviction/script
interaction checks and the two Lua reply-API CR/LF checks extend existing jobs.

Global slowlog exclusion: restore `src/cmd/slowlog.cc` byte-for-byte from
headline, dropping only that part of `7c50db206`. Omit the new `infofix_compat-slowlog`
row (infofix contributes +4, not +5). Restore these seven named Tcl skips with
their headline reasons:

- `SLOWLOG - GET optional argument to limit output len works`
- `SLOWLOG - can clean older entries`
- `SLOWLOG - commands with too many arguments are trimmed`
- `SLOWLOG - get all slow logs`
- `SLOWLOG - logged entry sanity check`
- `SLOWLOG - max entries is correctly handled`
- `SLOWLOG - too long arguments are trimmed`

### Compile-only budget selection

All 31 budgeted translation units were compiled at the inherited value and the
headline budget plus the measured IPA-size delta, with ±8 trials. Linked-body
scoring selected one further change: DB0 `t_server.o`, 33883 → 33911. All other
provisional merged budgets won or tied their trials. Full compiler commands,
IPA sizes, digests and scores are in `docs/wave10/budgets/`.

The new snapshot fixture initially tore down its sidecar before draining its
private QSBR queue; those eight read-local subcases crashed during test cleanup.
The fixture now drains before disarming and releasing the sidecar, matching
production teardown. The complete `exec1s` gate job then passed all four public
rows and their internal subcases, including the concurrent X2 reader falsifier.
This was a fixture repair, with no production-path change.
