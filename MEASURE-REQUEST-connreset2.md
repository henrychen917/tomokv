# connreset2 reconciliation — 2026-10-05

Ready for maintainer review. Bench4 has landed, and `tools/lb_episodes.py` is
byte-for-byte identical to its copy on both `origin/cpp` and
`cx-lbplanner-bench3`. No connreset sampler patch or additional hook remains.
No new performance measurement is requested.

Started from the clean, already-reconciled commit `468778be0`; its work was not
redone. Fetched `origin cpp` and merged `origin/cpp` at
`1055409c25af1c8d95906f2f4e4e03648b059458` in commit `f427710c4`.
The only merge conflict was `MEASURE-REQUEST`: its mainline exbatch request was
preserved, with a pointer to this report and the original connreset evidence.

## Duplicate implementation dropped

The independent connreset implementation of sampler lifetime, join ordering and
secondary-error handling was already replaced wholesale in `468778be0`.
Bench4's `sampled_episode` owns all three: the sampler stays inside `boot`'s server
lifetime, body failure is classified before close, and a secondary sampler error
is recorded without masking the original cause. Its per-kind stationarity,
spread scoring, rebound checks and `suffix_other` accounting are retained intact.
Nothing was reapplied to `tools/lb_episodes.py` in this continuation.

The prescribed `suffix_other` check returns **11** for the landed file.
Commits `318e1b9c7`, `cf95ea914` and `422c9f509` are ancestors of `origin/cpp`.
The local bench4 branch is `cbb07d1d1` (newer than `fbed05ea7`); the landing-order
dependency is therefore already satisfied.

Shared Git blob: `b5568d12210865594a7c31016eb4a9ee02e30cab`.
SHA256: `59995cc0e13a160ac6ddf7b9a4ba846eab57d454fbcd4f9e29a7fc5f6b118a40`.

## Kept

- `tests/connreset_repro.py` and `tests/connreset_harness_test.py`.
- Every existing `docs/connreset/*` artifact and `MEASURE-REQUEST-connreset.md`,
  including the original 0/300 PRE observation and archived POST/TRACE evidence.
- The `connreset-trace` Makefile target and its conditional diagnostic support.
- Exactly one connreset row in `job_lbplanner_units`.

The witness already uses bench4's join signature and secondary-error fields.
Its negative control removes the inner sampler lifetime from a throwaway
`run_episode` function, restores the old success-path close and late exceptional
close, and executes the same assertions. Neither the landed harness nor its
scoring is edited by the control. The witness, reproducer and existing evidence
are unchanged from `468778be0`.

## Checks rerun after the merge

| Check | Result |
|---|---|
| `python3 tests/connreset_harness_test.py` | PASS, 4/4 tests; exit 0 |
| Same witness with `--negative-control` | Expected exit 1; 3 assertion failures, including the required baseline-cause witness |
| `python3 tools/lb_episodes.py --self-test` | PASS, 37/37 tests; exit 0 |
| `bash -n tests/gate.sh` | PASS; exit 0 |
| `python3 tests/gateplan.py --json iteration >/dev/null` | PASS; exit 0, with the affinity-probe setup below |
| Whole-file comparison against mainline and bench4 | PASS; identical bytes and Git blob |
| `git diff --check origin/cpp` | PASS |

The negative control specifically replaces the baseline reason
`balanced total_moves=1, limit=0 (key=0, client=1)` with
`sampler failed: [Errno 104] Connection reset by peer`. Its output contains
`FAIL: test_baseline_failure_joins_monitor_before_server_and_preserves_cause`,
as required by the gate row. A real observer failure still fails a successful
episode in the positive witness.

All command execution was pinned with `taskset -c 112-127`. The planner normally
widens its own affinity while discovering available CPUs, so taskset alone would
not preserve that restriction. For this check only, a temporary `sitecustomize`
under `build/connreset2/affinity-probe/` redirected its affinity get/set calls to a
stopped helper process. The real kernel performed all six probes; the executing
parent stayed on 112-127, and the helper's mask was restored to 112-127 before
termination. Planner source, topology, measurement configuration and fixtures
were unchanged. The invocation was:

```sh
taskset -c 112-127 env PYTHONPATH="$PWD/build/connreset2/affinity-probe" \
  python3 tests/gateplan.py --json iteration >/dev/null
```

Fresh local outputs are in `build/connreset2/{harness-test,harness-negative,lb-selftest,gate-syntax,gateplan}.log`;
`build/connreset2/gateplan-affinity.json` records the affinity checks. These are
local verification artifacts; existing committed campaign receipts were preserved.
No server, load generator, benchmark or gate was run, and no binaries were rebuilt.

## Gate accounting and landing

The row begins at `tests/gate.sh:1319`; `collect_job lbplanner_units` is at line
3093, before the quick-tier exit at line 3250. It contributes **+1 quick and +1
full**.

The fetched mainline already includes exbatch's five rows and its maintainer-owned
EXPECT/fixture updates. Its counts are now **495/512**, so landing connreset on
this base requires the maintainer to set **496/513**. The earlier **491/508**
request was relative to the older 490/507 base. This lane has no EXPECT or fixture
diff against current `origin/cpp`; those files' mainline updates were only inherited
through the required merge.

The original measurement report and binary receipts describe their original
campaign, not newly built binaries from this merged tree. This continuation adds
no new server behavior or measurement arm. Changes are committed on
`cx-connreset`; nothing was pushed.
