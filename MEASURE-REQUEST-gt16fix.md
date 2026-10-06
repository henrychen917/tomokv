# gt16fix — require a stationary driver inside the stable hold

Worktree `/home/user/Projects/cx-gt16fix`, branch `cx-gt16fix`, 2026-10-06.
Merged `origin/cpp` first by fast-forward from `649116c91` to `7213a9405`.
Implementation and serverless tests: `f6180f501`.

## Change and judging rule

GT16 records a generator dip that the old whole-trace mean and consecutive-pair
rule missed. The new `classify_stable_hold` uses the driver's eight-second
pre-hold mean as a fixed anchor and the controller's published
`flipctl_rate_band` for that attempt. For **every hold sample**, it evaluates
`abs(rate / driver_anchor - 1) > band`. There is no new tolerance constant and
no averaging or recentering inside the assertion window. Driver counters exclude
the battery's INFO traffic, as before.

| Driver inside the hold | Controller | Verdict |
| --- | --- | --- |
| Every second in band | Moves | FAIL immediately |
| Any second outside the band | Moves or holds | INVALID; retry |
| Every second in band for the full window | Holds | PASS |

An invalid trace remains invalid after recovery. A quiet controller cannot turn
an invalid driver window into a pass. Stationary movement fails for every trigger
reason, including `fingerprint-shift`; the existing pre-hold arming logic remains
unchanged. Each attempt prints its per-second driver trace and verdict reason.
Movement diagnostics retain the controller's INFO state and DEBUG dump.

Rearming retains the existing `STABLE_HOLD_ATTEMPTS = 3` and wall budget; this
baseline does **not** have four stable-hold attempts. Every attempt reacquires
the anchor, trigger count, split and band, and starts fresh driver samples.
Exhaustion or a window that never opens remains a failure.

The ramp/boot assertions, retry loop, surge assertions, mix assertions, controller
state/trigger/split movement predicate, and production sources are unchanged.
`tests/gate.sh` and all fixtures are unchanged. **Row delta: 0 quick / 0 full.**
`collect_job flipctl` is at line 3213, before the quick-tier exit at line 3272;
counts remain **497 quick / 514 full**. The new unit is run separately, without
adding a gate row. No server layout, performance change, or PAD arm is involved.

## Serverless proof

`python3 tests/flipctl_test.py -v`: **11 tests passed**. Coverage includes the
three required outcomes, the reported `5977, 5847, 5697, 5774, 5866` dip, an
isolated first/middle/last-second dip, a surge, recovery, a sustained step,
published-band changes, inclusive boundaries, missing/nonfinite observations,
and a fresh anchor on retry.

The reported synthetic dip is missed by the original `rate_rule_fires` when
preceded by the eight 6000/s pre-hold samples; the new classifier reports
**INVALID at hold sample 3: 5697/s, deviation 0.050500 > band 0.036500**.

Three in-memory negative controls were rejected by those tests: restoring the
old rolling-mean classifier, accepting stationary movement, and accepting an
empty window. Their output is in `build/gt16fix-proof/negative-controls.log`.
`git diff --check` passed. Source comparison against `7213a9405` confirmed the
unchanged assertion blocks and absence of gate, fixture or production changes.

The original evidence path
`/home/user/Projects/cx-bench5/build/gate-run.XDjV8t/jobs/flipctl/battery.log`
is absent from this workspace. The regression uses the values supplied in the
task and corroborated by `/home/user/Projects/round3-read/REGISTER.md` GT16;
it is not represented as a replay of the unavailable complete log.

## Requested live proof

Run six consecutive selections, each on a fresh server. The lane-specific proof
request supplies correctness CPUs 112–127: server 112–119, load 120–127, no SMT,
16 shards, ratio 6:2. Only `release` and `flipctl` are selected; no ABBA runs.

```bash
python3 tests/flipctl_test.py -v
mkdir -p build/gt16fix-proof
for run in 1 2 3 4 5 6; do
  GATE_ONLY_JOBS=flipctl \
  GATE_LEDGER="$PWD/build/gt16fix-proof/run-${run}-ledger" \
  taskset -c 112-127 tests/gate.sh iteration \
    --server-cores 112-119 --load-cores 120-127 \
    --server-smt '' --load-smt '' --ports 18340-18342 \
    >"build/gt16fix-proof/run-${run}-gate.log" 2>&1 || break
done
```

Decision: all six must exit zero, complete the full stationary-driver hold and
the unchanged ramp, surge and mix assertions, and publish zero FAIL rows.
INVALID attempts are reported and retried within the original budget; exhaustion
is never a clean run. These are selected correctness checks, not a full gate
receipt or a performance claim.

Live validation is in progress. Run 1 (`build/gate-run.Emzv2w`) exited 0 with
**2 ok / 0 FAIL**, completing its hold on attempt 1 of 3, then the surge and mix
assertions. Runs 2–6 are executing sequentially; final receipts will be recorded
below.
