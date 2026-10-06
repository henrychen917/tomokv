# respcompat3 — differential accounting repair (validation in progress)

Worktree `/home/user/Projects/cx-respcompat`, branch `cx-respcompat`.
Starting HEAD: `608064a27`. `git merge --no-edit origin/cpp` reported already up
to date; `origin/cpp` is `b1d931ee2a271f28c9c9c91e2556c8fa36000a4d`.
Implementation commit: `df35b22b4`.

## Defect and chosen integration

The landing run `build/gate-run.yib6ZD` completed every planned comparison but
counted an additional unplanned RESP leg in each atomic lifetime. For split-0,
`check_matrix()` counted 210 comparisons and the shell reported 211 passes. For
armed-0 it counted 205 comparisons; with the required read-local witness the
expected total was 206, while the shell reported 207. `finish()` correctly
rejected these totals. Both public folds then rejected worker completion
`[0, 0, 1]`. This was an accounting defect, not a reason to relax equality.

Chosen option: remove the entire 14-line RESP leg from `tests/differ_gate.sh`
and keep RESP coverage in the existing `RESP protocol error compatibility`
row. The differential script now matches `origin/cpp` exactly. The fan-out plan,
`check_matrix()`, `finish()`, and fold validation are unchanged.

The standalone row previously checked only the target. It now owns an isolated
vanilla Redis 7.4 oracle and runs the unchanged 311-case inventory against both
target and oracle in all four combinations: split / armed-fused, atomic 0 / 1.
The test verifies the oracle is vanilla Redis 7.4 and requires both arms to
match the explicit bytes and connection-lifetime expectations. Oracle boot,
listener ownership, bounded cleanup, and exit failures fail the existing row.
The gate's existing descendant cleanup also owns this oracle on interruption.

No production, EXPECT, or fixture file was edited. The existing row remains
before the quick-tier exit: `collect_job respcompat` at line 3213, quick exit
at line 3335. Counts remain **498 quick / 515 full**: the already-landed
**+1 quick / +1 full**, with zero additional rows in this revision.

## Binary identity

`taskset -c 112-127 make -j16` reported `Nothing to be done for 'all'`.
Before and after the implementation:

```text
f0cde7f0fa97532ed560fcfdb4d7a9114b0a97cde880454df41b5218e4ad7187  build/tomokv
```

## Validation so far

- Shell syntax and `git diff --check`: PASS.
- Unchanged `differ_fanout_test.py`: 18 tests, PASS, including missing,
  reordered, failed, unwitnessed, and unsuccessful-completion controls.
- Unchanged `respcompat_test.py`: 9 tests, PASS.
- Live gate: running in `build/gate-run.vnRVCd`; results pending.

```sh
taskset -c 112-127 env GATE_ONLY_JOBS='differ-split differ-armed respcompat' \
  tests/gate.sh iteration --server-cores 112-119 --load-cores 120-127 \
  --server-smt '' --load-smt '' --ports 18340-18342
```

This launches the full, unmodified differential matrix through the actual gate
worker path: split-0, split-1, armed-0, armed-1, and mode equivalence. Server and
oracle flags use 112–119; the differ's own load-core flag uses 120–127. There is
one correctness slot, ratio 6:2, 16 shards, no SMT. Public subset completion
alone does not publish the two outer folds; those will be checked separately
with the unchanged helper and original run metadata.

An earlier differential-only invocation (`build/gate-run.ENRqJc`) was stopped
when consolidating all three requested jobs into one invocation. It is not a
passing receipt. Before interruption, wiredump/atomic=0/seed=7 reported 10
differences; the log is retained at
`jobs/differ-split-0/differ/wiredump-a0-s7.txt`. The complete run replays that
seed under the unchanged durable failure corpus; nothing was removed or
relabelled. No clean final result is claimed while validation is pending.
