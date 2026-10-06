# ccfix4 — composition and compiler budget audit

Work in progress: exhaustive budget search and final proofs are running. No push.

## Integration and exact production scope

PRE is freshly built from `08a68fcba20e3b33015f19e9157818083a6e6519`, the
landed storesize merge on `origin/cpp`. Its history also contains the psfix merge
`603ce3e44` and cmdmeta merge `ca4eeb371`. The precondition passed without a fetch.
The lane started at `700f0759d` and integrated upstream in `adcd6c34f`.

Merge resolutions retain all differential suites (including ccfix, cmdmeta and
psfix), one name per line; retain both historical MEASURE-REQUEST index entries;
and retain exactly one db0/main.o override. The inherited t_server overrides
were also consolidated into one after comparing merged PRE bodies.

`git diff 08a68fcba..HEAD -- src` contains exactly acl.inc, auth.inc, notify.h,
notify.inc, t_server.cc and thread.h. `git diff adcd6c34f..HEAD -- src` is empty:
there are no production source edits after the integration merge. The complete
[production patch](docs/ccfix4/production.diff) and
[composition proof](docs/ccfix4/round1-composition.json) show all 154 production
files equal freshly archived upstream plus the exact round-1 patch
`git diff b1d931ee2 bd4a20ebf -- src`, with only the emitter/comment exception.
All five non-emitter mechanism files equal `bd4a20ebf` byte for byte.

The emitter remains `cmdstat_<name>:calls=<n>,rejected_calls=<n>\r\n`.
The ccfix3 executed-error and pending-source notification deviations remain;
this lane changes no mechanism and claims no new Redis coverage for those gaps.

## Compiler search

The main.o search compiles every integer in 146100–146600, plus no override,
using inline-unit-growth=0 for numeric trials. Every trial inventories the union
of function symbols and all selected hot bodies with the unchanged ccfix audit
normalization, including ExLoopT::run. The no-override trial omits both parameters.
It compares against the fresh merged PRE, whose own db0 main.o override is 146270.

`tools/ccfix4_budget.py` retains each command, object hash and complete changed
function list in [budgets](docs/ccfix4/budgets). Search objects use -g0; the
[debug parity check](docs/ccfix4/debug-parity.json) proves all 826 function bodies
match the release -g object at the same 146270 budget. The final release is built
with the repository Makefile's -g. Ranking is changed selected-body count, then
canonical differing byte count, then lower numeric budget. No production code
is edited to alter compiler decisions.

The inherited 31520 db0 t_server budget changes RANDOMKEY and HELLO on merged
psfix. 31582 restores all selected ordinary handlers; 31581 fails. Coarse and
step-one refinement receipts are in [server-budgets](docs/ccfix4/server-budgets).
The normal main.o budget remains round 1's 146401.

## Builds, audits and proofs

Final results and hashes will be recorded here when the running jobs finish.
All lane builds, static audits and proofs use CPUs 112–127. Correctness server
geometry is eight cores 112–119, sixteen shards, split 6:2 or armed fused;
clients use 120–127. No throughput/ABBA/NIC measurement is requested of the lane.

The initial audit failure is retained under [initial-audit](docs/ccfix4/initial-audit):
1492/1494 selected hot bodies and 1204/1213 handler occurrences match at
main=146270, db0 t_server=31520. It identifies both writeback differences and
all ordinary emitter-unit differences without --error-callees.

The ccfix unit, PRE flag negative control, POST flag control, both pending-state
mode fixtures and no-arm control passed. All exported layouts match PRE in both
namespaces, including the eight locked sizes. The landed gen_cmdmeta --check
passes. Final release-bound wire, instruction and selected-gate receipts follow.

Gate rows are +0 quick / +0 full. EXPECT_QUICK=500 and EXPECT_FULL=517 are exactly
upstream's landed values. No gate or fixture edits are made by ccfix4. The
netcmd_units collection is line 3225, before the quick-tier exit at 3359;
existing differential rows are lines 3387 and 3398, after it. No count change
is requested.

## Maintainer measurement

After the final receipts are recorded, use PRE versus POST on the gate's fourteen
unchanged generic cells h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h63,h64,
notifications off, at matched offered load. Keep each cell's rate, cycles/op,
instructions/op and IPC, and apply the existing per-cell band without averaging
away a failing cell. If ordinary main.o differences remain, this is the owner's
explicit null decision under the storesize3 precedent, not strict byte acceptance.
There is no PAD arm: no locked instance layout changes. A throughput verdict is
pending the maintainer's quiet-box run.
