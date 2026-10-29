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
