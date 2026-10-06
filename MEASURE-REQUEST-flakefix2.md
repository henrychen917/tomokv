# flakefix2 — frame-order proof on the merged PS7 INFO surface

**Complete: 6/6 consecutive merged-tree runs PASS, both atomic rows in every
run; 9/9 serverless tests PASS; the broken-guard negative control fails at
the required assertion.**

Worktree `/home/user/Projects/cx-flakefix`, branch `cx-flakefix`. No push.
`git merge origin/cpp` reported already up to date: merge commit
`9b7caa05438251c931cf3f27709afd80b37ee8d8` already contains mainline
`08a68fcba20e3b33015f19e9157818083a6e6519`. All validation below uses this
merged tree, with test fix `053052d47042352ef9124e031e34f24ea199baaa`.

## Rename and scope

Read `MEASURE-REQUEST-flakefix.md` and landed `MEASURE-REQUEST-psfix.md` PS7.
PS7 renamed `aof_rewrite_completions` to `aof_rewrites` and
`aof_rewrite_consecutive_failures` to `aof_rewrites_consecutive_failures`,
without aliases. The live completion wait in `tests/aof_frame_order.py` and
the serverless schedule's INFO response in `tests/aof_frame_order_test.py`
now use `aof_rewrites`. The lane has no consumer of the failure counter.
Direct dictionary indexing remains in place: a future missing/renamed field
fails loudly, with no fallback or alternate spelling accepted.

The requested grep of `tests/` and `docs/flakefix` found no other stale lane
consumer. The old names in `tests/psfix.py` and `tests/differ.py` are deliberate
PRE/no-alias assertions and are preserved. Generated Python bytecode is not
source evidence.

## Build and production identity

`taskset -c 112-127 make -j16` passed (the merged release build was already
up to date; [log](docs/flakefix2/make.log)). The required production comparison
is [empty](docs/flakefix2/production.diff):

```bash
git diff 9b7caa05438251c931cf3f27709afd80b37ee8d8..HEAD -- src Makefile
```

Only the two test lines change executable/test code after the merge.
`tests/gate.sh`, EXPECT constants and gate fixtures are unchanged.
The binary hash was checked before and after all six gates and is identical;
this lane changes no production source, compiler flags or layout after the merge.

SHA-256 of `build/tomokv`:

```text
3dce05d80c07d3b49633f319d24af49acda3a93660ef703639ceef90dcf050f5
```

## Fresh proof

`python3 tests/aof_frame_order_test.py`: **9/9 PASS** on the merged tree
([standalone log](docs/flakefix2/python-unit.log)); also 9/9 in each of the
twelve live row logs.

The exact live command, run six times consecutively:

```bash
GATE_ONLY_JOBS=aof_frame taskset -c 112-127 tests/gate.sh iteration \
  --server-cores 112-119 --load-cores 120-127 \
  --server-smt '' --load-smt '' --ports 18340-18342
```

The first attempt stopped at the port preflight before any build, boot or
test: an active `cx-cd13b` gate owned port 18340 and the same cores. Its process
was left running; the attempt is retained in
`build/flakefix2/preflight-port-busy.log` (`build/gate-run.kCUShs`). It is not
part of the subsequent clean sequence. Its retained
[preflight log](docs/flakefix2/preflight-port-busy.log) makes that interruption
explicit; no failed live row was discarded or retried.

The clean sequence ran on 2026-10-07, 04:45:28–04:46:07 (Asia/Taipei).
Each gate exited 0 with
**3 ok / 0 FAIL**: the release build row plus both existing frame-order rows.
The gate plan is eight server cores, 16 shards, ratio 6:2, with the exact
server/load allocation above. Table pairs are **atomic 0 / atomic 1**.

| Run | Gate artifact | Window deferrals | Window groups | Large records | Control frames | Interleaves | Negative groups | Negative deferrals |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `gate-run.lq2oDE` | 17 / 17 | 1 / 1 | 1 / 1 | 1 / 1 | 0 / 0 | 40 / 40 | 0 / 0 |
| 2 | `gate-run.rbIkK7` | 17 / 17 | 1 / 1 | 1 / 1 | 1 / 1 | 0 / 0 | 40 / 40 | 0 / 0 |
| 3 | `gate-run.7vjNnd` | 17 / 17 | 1 / 1 | 1 / 1 | 1 / 1 | 0 / 0 | 40 / 40 | 0 / 0 |
| 4 | `gate-run.XyqEDT` | 17 / 17 | 1 / 1 | 1 / 1 | 1 / 1 | 0 / 0 | 40 / 40 | 0 / 0 |
| 5 | `gate-run.qR9V09` | 17 / 17 | 1 / 1 | 1 / 1 | 1 / 1 | 0 / 0 | 40 / 40 | 0 / 0 |
| 6 | `gate-run.HLdQot` | 17 / 17 | 1 / 1 | 1 / 1 | 1 / 1 | 0 / 0 | 40 / 40 | 0 / 0 |

All twelve live logs prove that the window entered: GCMT was deferred while
one large record was open, then committed after its end. Each increment has
276 frames, including exactly one large record and one control frame, with
zero interleaves. The negative phase requires all 40 groups to commit without
a deferral. The existing arming, completion and physical-frame assertions
are unchanged.

Tracked evidence is in [docs/flakefix2](docs/flakefix2): `run-N.log`,
`run-N.ledger`, `run-N.plan.sh`, and `run-N-atomic-{0,1}.log`. The full artifact
directories remain under `build/`. [witnesses.json](docs/flakefix2/witnesses.json)
records every arm's counts, elapsed window time, frame count and byte count
parsed from its fresh frame-order log.

Each row also passed the four real-writer native schedules (both writer
budgets × both commit producers). After the six-run sequence,
`taskset -c 112-127 build/persistfix-unit frameorder-no-guard` exited **1**
as required, with `ready GCMT MUST stay outside the open large record`
([negative-control log](docs/flakefix2/frameorder-negative.log)). Thus a
deliberately bypassed guard remains red; no production binary was modified.

These selected jobs are a partial correctness proof, not a full gate receipt
or a performance measurement.

## Gate rows

**+0 quick / +0 full.** The existing `aof_frame` job is collected at
`tests/gate.sh:3308`, before the quick-tier exit at line 3364. Both atomic
rows already exist. EXPECT remains 500 quick / 517 full; no fixture changes.
