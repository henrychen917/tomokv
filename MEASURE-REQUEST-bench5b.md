Lane bench5b — preserve the connreset witness's primary cause (2026-10-06)

The serverless gate row now passes. Implementation is committed as `847ace4e9`
on `cx-bench5` in `/home/user/Projects/cx-bench5`. First merged `origin/cpp` at
`649116c91` (which includes `8e360152f`) in `efc968403`; the prior bench5 work
through `4d16fe1e4` is retained. Nothing was pushed.

`run_episode` keeps the first failure reason exact. Later workload, sampler,
teardown and owner-tracking failures are recorded as `{source, message}` entries
in `diagnostics[]`; the existing `sampler_error`, `teardown_error` and
`owner_tracking_error` fields remain available. An owner-tracking failure also
has a structured `owner_tracking` record. A rejected baseline does not invoke
owner tracking, so it cannot acquire a spurious missing-telemetry finding.
Missing owner telemetry after an accepted baseline still fails the run and
invalidates its measurement; if it is the first failure, it supplies the reason.

Baseline maxima remain in `baseline_stationarity.summary` / `spread_maxima`
and are reported through `diagnostics[]`, never appended to `reason`. Replay
uses the same separation for secondary scoring/accounting findings and absent
stimulus evidence. The primary baseline rejection remains exactly:

```text
balanced total_moves=1, limit=0 (key=0, client=1)
```

The connreset test needed three setup lines: its fake sampler now supplies one
synthetic owner-map snapshot covering its 64 fake shards. Its fake thread never
captures telemetry, but bench5 validates owner maps after a successful baseline.
This lets that success case exercise the real owner-tracking function. Every
existing assertion and the throwaway cleanup negative control are unchanged.
The embedded tests separately cover empty telemetry on accepted and rejected
baselines, simultaneous monitor/teardown failures, exact persisted reasons,
structured diagnostics, and replay precedence.

All checks below ran serverless under `taskset -c 112-127`.

| Check | PRE (`efc968403`) | POST (`847ace4e9`) |
|---|---|---|
| Connreset witness | 2/4 pass; exit 1; reproduced both reported failures | 4/4 pass; exit 0 |
| Cleanup negative control | Not rerun | Expected exit 1; three assertion failures, including the required baseline-cause witness |
| Complete connreset row predicate | Fails at positive witness | PASS, including negative-control exit and failure-label checks |
| `tools/lb_episodes.py --self-test` | 49/49 pass; exit 0 | 50/50 pass; exit 0 |

The exact row predicate from `job_lbplanner_units` was executed with its Python
commands and negative-control label check, without invoking the gate:

```sh
taskset -c 112-127 bash -c '
python3 tests/connreset_harness_test.py >build/bench5b/connreset-harness.log 2>&1 \
  && { python3 tests/connreset_harness_test.py --negative-control >build/bench5b/connreset-negative.log 2>&1; test "$?" -eq 1; } \
  && grep -q "FAIL: test_baseline_failure_joins_monitor_before_server_and_preserves_cause" build/bench5b/connreset-negative.log
'
taskset -c 112-127 python3 tools/lb_episodes.py --self-test
```

The negative control replaces the expected baseline reason with
`sampler failed: [Errno 104] Connection reset by peer`; its success path also
fails the exactly-once join assertion. This confirms the cleanup witness still
detects the original defect. Local logs are in `build/bench5b/`:
`pre-connreset-harness.log`, `pre-lb-selftest.log`, `connreset-harness.log`,
`connreset-negative.log`, `row-body.log`, and `lb-selftest.log`.
`git diff --check efc968403 HEAD` passed.

Gate accounting is **0 added/retired rows: delta 0 quick / 0 full**. The existing
row begins at `tests/gate.sh:1319`, is collected at line 3115, and remains before
the quick-tier exit at line 3276. The merged maintainer counts remain **497/514**.
`tests/gate.sh`, `tests/fixtures/` and `tests/flipctl.py` are unchanged against
the merged `origin/cpp`; inherited mainline count/fixture changes were not edited
by this lane. GT16 is outside this change.

No performance measurement or new binary arm is requested: this is a Python
harness/reporting fix with no server or layout changes. No server, load generator,
benchmark or gate was started, and no binaries were built. The maintainer retains
the full gate and merge. The implementation and this report are committed for
review.
