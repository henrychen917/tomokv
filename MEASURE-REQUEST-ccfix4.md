# ccfix4 — composition and compiler budget audit

**Committed WIP; not an acceptance receipt.** The required upstream merge,
exhaustive compiler search, rebuilt arms, source/body audits, unit controls,
eight Redis differential legs, selected gate and cmdmeta drift check are complete.
No tested budget matches every selected db0 main.o body. The retained minimum is
146203 (one selected-body difference), for the owner's explicit null decision.
The separate required instruction-equality proof **fails: 0/11 complete runs
match exactly**. All readouts are retained; no tolerance or counter correction
was introduced. No push or throughput measurement was performed.

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

[Search result](docs/ccfix4/budget-result.json): **501/501 numeric values plus
no override were compiled and audited; zero full matches** across all 129 selected
db0 main.o bodies. There are 32 one-body, 129 two-body, 183 three-body, 119 four-body
and 38 five-body numeric outcomes. No override changes seven selected bodies.

**Chosen value: 146203.** The minimum score (one changed body, 785 differing
canonical byte positions including length difference) occurs at 146203–146210,
146212–146219, 146311–146318 and 146320–146327. The lowest numeric tie wins.
146202 changes two selected bodies; 146215 changes one; upstream's 146270 changes two.
The full [search index](docs/ccfix4/budget-search.json) and every per-value diff
remain committed, including the no-override result.

The wider search **does restore both historical ccfix3 lambdas at 146305–146600**,
but then other selected hot bodies differ. Thus it would be incorrect to say
neither lambda pair can ever match. No value makes the whole selected inventory
match. At 146203 the sole selected difference is:

```text
tomo_db0::WbEngine::serve_impl<false, true, false, true, false, false>
  (tomo_db0::Client&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()
  (tomo_db0::Op&) const: 824 -> 537 bytes
```

PRE inlines Client::append_static_segment; POST has its explicit call relocation
at byte offset 264. This is an instruction difference. The alternative minimum
ranges above 146305 move the remaining difference to another specialization;
they do not provide full equality.

The inherited 31520 db0 t_server budget changes RANDOMKEY and HELLO on merged
psfix. 31582 restores all selected ordinary handlers; 31581 fails. Coarse and
step-one refinement receipts are in [server-budgets](docs/ccfix4/server-budgets).
There is one override each for db0/main.o and db0/t_server.o; the inherited
31520/31320 duplication was removed. The normal main.o budget remains round 1's
146401; other landed budgets are preserved.

## Builds, audits and proofs

Fresh GCC 13.3.0 repository builds are recorded in
[build-manifest.json](docs/ccfix4/build-manifest.json), including all 90 production
objects per arm. POST production/Makefile commit is `a04f9a188`.

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | build/ccfix4/PRE/tomokv | `656565bf27674df5d05d612c680dd903baf34b35091b78e68f9b80588e497a94` |
| POST | build/ccfix4/POST/tomokv | `b9ff988dff0eb7224c0668f3b946ef0e6e61838e130b6cb34e2d6ca72446f212` |
| Review | build/tomokv | `b9ff988dff0eb7224c0668f3b946ef0e6e61838e130b6cb34e2d6ca72446f212` |

POST and the review copy compare equal. GNU size text is 8,826,957 → 8,828,497
(+1,540); .text is 7,807,404 → 7,808,380 (+976); data stays 86,600; BSS is
1,146,456 → 1,146,584 (+128). These are size counts, not throughput results.

The unchanged ccfix_audit.py, without --error-callees, reports 16,910/16,991
identical function occurrences and **1,493/1,494 selected hot bodies**. It exits 1
on the one ordinary writeback difference, retained with both disassemblies,
canonical bytes and targets in [main-diffs](docs/ccfix4/main-diffs).
All **1,199/1,199 nonadministrative handler occurrences match**; 1,207/1,213
handler occurrences match overall, with six CONFIG/INFO root/cold differences.
All [81 changes and reasons](docs/ccfix4/changed-bodies-with-reasons.json) remain
visible, including compiler changes outside the selected hot inventory.

Unmodified r7shadow_noop.py --inventory splitlocal exits 1, **391/396**, with
strict_noop=False. The existing ccfix_tables.py passes: its five differences have
identical switch bytes or in-function case destinations. The complete linked
[inventory](docs/ccfix4/splitlocal.json.gz), [diffs](docs/ccfix4/splitlocal-diffs),
and [exact data proof](docs/ccfix4/linked-data-proof.json) are retained. This
supplement does not waive the separate writeback instruction change.
[Release/debug parity](docs/ccfix4/final-debug-parity.json) also confirms every
function at the selected main and server budgets matches the -g0 search object.
Compiler processes, body auditors and runtime proofs use CPUs 112–127. Correctness server
geometry is eight cores 112–119, sixteen shards, split 6:2 or armed fused;
clients use 120–127. No throughput/ABBA/NIC measurement is requested of the lane.

The initial audit failure is retained under [initial-audit](docs/ccfix4/initial-audit):
1492/1494 selected hot bodies and 1204/1213 handler occurrences match at
main=146270, db0 t_server=31520. It identifies both writeback differences and
all ordinary emitter-unit differences without --error-callees.

- `tools/ccfix4_prove.py units`: ccfix unit, PRE flag negative control, POST flag
  control, both pending-state mode fixtures and no-arm control pass. The adapter
  reuses the unchanged ccfix3 checks against the ccfix4 arms. Final logs are
  [units-final.log](docs/ccfix4/units-final.log) and the individual unit logs.
- `tools/ccfix4_prove.py layouts`: all exported layouts equal PRE in both
  namespaces; locked sizes remain 336/1984/1408/1440/944/192/144/624.
- The unchanged `tools/ccfix3_wire.sh` imports the harness boot/ownership helpers.
  All eight final-binary legs pass: split and armed fused, atomic 0/1, seeds 7/19;
  each atomic-zero leg has 210 exact comparisons, each atomic-one leg 222.
  Both oracles identify as Redis 7.4.10. CC18 compares calls/rejected_calls and
  asserts the exact two-field target shape; documented expected deviations remain.
  [Wire manifest](docs/ccfix4/wire-manifest.json), [split](docs/ccfix4/wire-split)
  and [fused](docs/ccfix4/wire-fused) retain all logs and coverage files.
- `GATE_ONLY_JOBS=netcmd_units` passes **13/13, zero failures**, including release
  verification and the twelve selected unit rows. The shared build prerequisites
  ran under the unmodified harness. This is a partial ledger, not a full receipt:
  [plan](docs/ccfix4/gate-netcmd/plan.sh), [ledger](docs/ccfix4/gate-netcmd/ledger.partial),
  [output](docs/ccfix4/gate-netcmd.log), and individual unit logs are retained.
- Landed gen_cmdmeta drift check passes, exit 0, with the pinned Redis source:
  [command and result](docs/ccfix4/cmdmeta-drift.json).

### Required instruction witness: FAIL

The initial complete five-interval run matched in the normal namespace but
reported db0 POST note_command=700,039 versus PRE=700,038. A complete rerun of the
same binaries moved +1 differences to other intervals; note_command then matched.
A third complete run on CPU 127 also failed. Eight additional bounded complete
serial runs on CPU 112 all failed exact equality. No lane compile, server, gate or load
generator overlapped these counted runs. All witness binaries are unchanged
between repetitions; their hashes are recorded in the stability receipt.

[Instruction status](docs/ccfix4/instruction-status.json) retains every full
readout and the observed values. The first two complete attempts are under
instructions-attempt1/2, the CPU-127 attempt under instructions-attempt3, and all
eight further runs under instructions-stability. Top-level CSVs and
instruction-comparison.json represent the last complete run, without mixing rows.

| 100,000-call interval | PRE | POST | db0 PRE | db0 POST |
|---|---:|---:|---:|---:|
| off/keymiss | 1,800,053–1,800,054 | 1,800,053–1,800,054 | 1,800,053–1,800,054 | 1,800,053–1,800,054 |
| off/string | 1,800,053–1,800,054 | 1,800,053–1,800,054 | 1,800,053–1,800,054 | 1,800,053–1,800,054 |
| save-only/keymiss | 2,000,053–2,000,054 | 2,000,053–2,000,054 | 2,000,053–2,000,054 | 2,000,053–2,000,054 |
| save-only/string | 2,400,053–2,400,054 | 2,400,053–2,400,054 | 2,400,053–2,400,054 | 2,400,053–2,400,054 |
| note_command | 700,038–700,039 | 700,038 | 700,038 | 700,038–700,039 |

These are observed ranges across the eleven runs, not an equality pass. Variation
also occurs within repeated PRE executions. The witness calls/notifications loop
assembly matches after resolving addresses to symbols in both namespaces
([assembly and comparison](docs/ccfix4/instruction-code)); that does not satisfy
the dynamic counter requirement or prove the cause of the differing readouts.
The witness source, 100,000-call loops, comparison, tolerances and production code
were not changed. Exact instruction equality remains outstanding.

Gate rows are +0 quick / +0 full. EXPECT_QUICK=500 and EXPECT_FULL=517 are exactly
upstream's landed values. No gate or fixture edits are made by ccfix4. The
netcmd_units collection is line 3225, before the quick-tier exit at 3359;
existing differential rows are lines 3387 and 3398, after it. No count change
is requested.

## Maintainer measurement

First resolve/reproduce the failed exact instruction witness on these frozen arms;
this lane supplies no passing instruction receipt. Then the maintainer decides
whether the one remaining selected hot-body change may enter the storesize3-style
null acceptance. Use PRE versus POST on the gate's fourteen
unchanged generic cells h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h63,h64,
notifications off, at matched offered load. Keep each cell's rate, cycles/op,
instructions/op and IPC, and apply the existing per-cell band without averaging
away a failing cell. If ordinary main.o differences remain, this is the owner's
explicit null decision under the storesize3 precedent, not strict byte acceptance.
There is no PAD arm: no locked instance layout changes. A throughput verdict is
pending the maintainer's quiet-box run.

## Reproduction and commits

```sh
# PRE: archive the landed base into an empty directory, then build freshly.
git archive 08a68fcba20e3b33015f19e9157818083a6e6519 | tar -x -C build/ccfix4/pre-src
taskset -c 112-119 make -C build/ccfix4/pre-src -j8 BUILD_ROOT="$PWD/build/ccfix4/PRE" all
taskset -c 112-127 make -j8 BUILD_ROOT=build/ccfix4/POST all

# Search, with -g0/release parity separately proved in the linked receipts.
taskset -c 112-127 python3 tools/ccfix4_budget.py 146270 146271 146215 146100 146600 none 146100:146600 --jobs 16

# Final audits: both strict tools exit 1; retain their reported differences.
taskset -c 112-127 python3 tools/ccfix_audit.py build/ccfix4/PRE build/ccfix4/POST docs/ccfix4/final-audit
taskset -c 112-127 python3 tests/r7shadow_noop.py build/ccfix4/PRE/tomokv build/ccfix4/POST/tomokv build/ccfix4/splitlocal --inventory splitlocal

# Runtime proofs; instructions is currently a failed exact-equality check.
taskset -c 112-127 python3 tools/ccfix4_prove.py units
taskset -c 112-127 python3 tools/ccfix4_prove.py instructions
GATE_DIFFER_GEOMETRY=split GATE_DIFFER_OUT="$PWD/build/ccfix4/wire-split" taskset -c 112-127 tools/ccfix3_wire.sh "$PWD/build/ccfix4/POST/tomokv" 18079 18080
GATE_DIFFER_GEOMETRY=armed-fused GATE_DIFFER_OUT="$PWD/build/ccfix4/wire-fused" taskset -c 112-127 tools/ccfix3_wire.sh "$PWD/build/ccfix4/POST/tomokv" 18079 18080
REDIS74_ROOT=/home/user/Projects/redis GATE_ONLY_JOBS=netcmd_units taskset -c 112-127 tests/gate.sh quick --server-cores 112-119 --load-cores 120-127 --load-smt '' --ports 18039-18060 --candidate-binary "$PWD/build/ccfix4/POST/tomokv"
```

Production is fixed at `a04f9a188f3790eaa0123233e479f8f1d2f3dc2a`; later commits
only retain tools, documentation and receipts. Integration is `adcd6c34f`;
`155446819` and `a95049ecc` preserve source proofs/search setup and initial failures;
`192e339f8` freezes release identities and final body audits. The final WIP receipt
commit carries the exhaustive search, wire/gate passes and failed instruction runs.
Nothing was pushed.
