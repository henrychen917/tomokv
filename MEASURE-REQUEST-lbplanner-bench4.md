Lane lbplanner-bench4 — controller-specific stationarity and spread scoring

Delivered on `cx-lbplanner-bench3` in
`/home/user/Projects/cx-lbplanner-bench3`, starting at `7cde71dcf`.
Implementation commits: `318e1b9c7`, `cf95ea914`, `422c9f509`.
Handoff date: 2026-10-05 (Asia/Taipei); replay inputs are the October 4 campaigns.
Read bench3's request first. Only `tools/lb_episodes.py` (including its embedded
self-tests) and this request change. No server changes, rebuilt measurement
binaries, gate rows, EXPECT edits, fixture edits, or push. All lane CPU work ran
on 112–127. No server, memtier, benchmark, or gate was started.

The 21:00 addendum supersedes the old client-skew quiescence comparison.
Key-skew retains its convergence clock and frozen PRE rebound limit. Client-skew
uses end spread, with continuing successful balancing distinguished from moves
after improvement stopped.

The baseline rule is now:

| Episode | Whole balanced window | Final decision window | Placement |
|---|---|---|---|
| key-skew | Zero KEY moves; CLIENT moves reported as baseline_client_moves | Stage Idle for three seconds and three ticks; CLIENT moves allowed | Same shard owners as frozen PRE calibration |
| client-skew | Zero KEY moves; earlier CLIENT moves reported | Zero CLIENT moves and stage Idle for three seconds and three ticks | Same shard owners as frozen PRE calibration |

The observation immediately before the final decision window brackets counter
changes, so a client move on the first in-window poll cannot escape the check.
JSON retains baseline_key_moves, baseline_client_moves,
baseline_earlier_client_moves, decision_client_moves, and the window start.
The existing minimum baseline duration/beat checks and raw-sample spread maxima
remain. Calibrations follow the campaign kind; a combined campaign uses the
key-skew calibration rule and still checks each client episode's own final window.

For key-skew, t_converge remains the first observation of the LAST KEY move,
relative to stimulus_t, with its preceding/current poll interval retained.
An admitted gather and an actual key move remain mandatory. It must fit
--max-converge, then the first closed beat after that move must leave at least
--suffix seconds and three tick advances, with stage Idle. The primary-spread
rebound rule is unchanged: that fixed beat's level plus the frozen PRE width;
no later favourable level or candidate baseline widens the limit.

suffix_moves now counts only moves of the REQUIRED kind. suffix_other_moves
counts the other controller's moves from the last required move through the
fixed endpoint, including the interval before the refreshed closed beat. Client
moves in a key suffix are reported and paired against PRE, never an automatic
episode failure. A key move during a client suffix still fails because it changes
placement.

Every episode row appends:

```text
baseline_client_moves=<n> suffix_other=<n> spread=base:<n>,peak:<n>,end:<n>,min:<n> reduction=<pct>% thrash_moves=<n>
```

Unavailable post-stimulus evidence stays NA. The existing row prefix and fields
through attempts remain in the same order. The spread metric is bucket weight
for key-skew (diagnostic only), client weight for client-skew:

- base: the last poll at or before stimulus_t.
- peak: the maximum in (stimulus_t, stimulus_t + 6 seconds].
- end: the arithmetic mean of raw polls in the fixed endpoint's last three seconds.
- min: the minimum of all post-stimulus polls, including the rising edge.
- reduction: 1 - end / peak; NA if peak is zero.

Thrash accounting starts from that fixed peak. At each closed controller beat
after the six-second peak window, take its trailing three-second mean. Each new
level at least 5% below the previous improvement level records a new milestone.
thrash_moves is required-kind moves AFTER the last milestone; if none exists,
all required moves are reported. A new higher peak cannot reset this clock.
The 5% band defines the counter, not a minimum reduction required to recognize
ongoing improvement.

For client-skew, "still converging" requires positive peak-to-end reduction,
a required move in the final --suffix window, and a negative least-squares
spread slope across closed beats in that window (at least three observations).
spread_tail_slope and spread_tail_seconds are retained in JSON. This uses the
already declared observation window, not a fitted timing knob or a single
three-second noise fluctuation. Such a trace can PASS its episode beyond
--max-converge without a quiet suffix; final-decision stage Idle and the
key-movement exclusion still apply. Once a refreshed closed-beat level exists,
subsequent samples must also obey the same frozen PRE-width rebound bound.
t_converge remains reported.

No end-spread improvement fails. A nonzero thrash_moves count fails when the
trace is no longer still converging. During continued improvement that count can
include moves toward the next incomplete 5% milestone and is reported without
automatically failing. Settled client traces retain the existing suffix,
time-limit, Idle and rebound checks. A flat trace with continuing moves fails;
a monotonically falling trace with late moves passes.

The paired rule is:

- Key-skew: POST's last required move converges no slower than PRE, with no more
  required moves, other-kind moves, or suffix_other moves.
- Client-skew: POST spread_end <= paired PRE spread_end + the max-minus-min range
  of valid PRE spread_end rounds in the same mode. The range uses PRE only,
  including valid stalled controls, never POST/PAD. Completed moves and
  t_converge are reported; they are not independent penalties for client balancing.
  PRE/PAD controls need valid stationarity, telemetry and accounting evidence;
  their failure to reduce spread is retained as an episode verdict, not a veto
  on a candidate that does better. POST must pass its own progress/thrash checks.
- Both: no aggregate or hot/cold cohort rate/p99 loss; POST actuator mix matches
  both PRE and PAD-A within the unchanged Fisher counting-noise test;
  **PassLimit == PRE exactly**. Every scheduled paired comparison must pass.

The Fisher implementation, denominators, reasons, 5% family error budget and
Bonferroni division are unchanged: alpha 0.05/96 for one episode kind, 0.05/192
for both. Probe admission/refusal, --arms identity and SHA checks, --hot-pipeline
accounting, topology, fixed durations, actuator deltas/high-water reporting and
envelope diagnostics are unchanged. PAD-A is **kind A (behaviour twin):
PRE behaviour with candidate text size/layout**; run 4/5's receipt maps this label
to PAD-A2 and POST to POST2.

Sampler lifetime now nests inside boot's server lifetime on success and failure.
A body failure is classified before sampler close; stop/join completes before
boot closes connections or reaps children. The sampler socket retains its
two-second timeout, but join never returns with a live sampler. Secondary sampler
or teardown errors are recorded separately and cannot replace a baseline or
convergence failure. A live sampler failure still invalidates an otherwise
passing measurement.

Read-only replay used the original run.json, telemetry.jsonl, manifest config
and frozen criterion/diagnostic envelope. It did not re-fit PRE from a newly
admissible calibration or manufacture missing stimulus data. Rate and merged
HDR p99 below are the saved, accounted measurements. Recomputed last-move times,
key/client/gather counts, actuator reasons, attempts and PassLimit match every
completed saved episode exactly. Re-read telemetry digests were unchanged.

Run 4 (`build/lbplanner-episodes-mainline-04`): all 23 saved baselines pass the
new rule, including all 18 matrix baselines. The three calibrations have
baseline_client_moves 0 (1s r1), 1 (2s r1), 0 (2s r2); the replay retains the
original chosen 2s r2 criterion. All eight completed traces pass their
convergence check: two probes and six matrix episodes. Five matrix FAILs become
PASS; 2s POST r2 was already PASS. Probes remain ARMED and are not scored rounds.

| Completed key-skew trace | Old → new episode verdict | t_converge s | KEY / CLIENT | suffix_other | Rate Mops/s | p99 ms |
|---|---|---:|---:|---:|---:|---:|
| 1s-PAD-A-r1 | FAIL → PASS | 14.859 | 11 / 4 | 3 | 11.70793 | 2.047 |
| 1s-POST-r1 | FAIL → PASS | 14.959 | 11 / 3 | 3 | 11.29396 | 2.143 |
| 1s-PRE-probe | ARMED → ARMED (convergence PASS) | 11.859 | 8 / 7 | 7 | 11.52406 | 2.095 |
| 2s-PAD-A-r2 | FAIL → PASS | 9.909 | 3 / 5 | 5 | 11.66199 | 2.063 |
| 2s-PAD-A-r3 | FAIL → PASS | 6.909 | 1 / 1 | 1 | 11.55190 | 2.095 |
| 2s-POST-r2 | PASS → PASS | 10.011 | 3 / 0 | 0 | 11.54641 | 2.095 |
| 2s-POST-r3 | FAIL → PASS | 6.959 | 1 / 2 | 2 | 11.27485 | 2.127 |
| 2s-PRE-probe | ARMED → ARMED (convergence PASS) | 6.910 | 1 / 1 | 1 | 11.64050 | 2.063 |

All completed run-4 suffix_moves are zero; all their thrash_moves diagnostics are
zero. Their primary spread diagnostics, rounded to whole spread units, are:

| Trace | base | peak | end (3s mean) | min | Reduction |
|---|---:|---:|---:|---:|---:|
| 1s-PAD-A-r1 | 17298 | 304980 | 54515 | 17298 | 82.12% |
| 1s-POST-r1 | 17576 | 300706 | 51230 | 17576 | 82.96% |
| 1s-PRE-probe | 17704 | 299374 | 49280 | 17704 | 83.54% |
| 2s-PAD-A-r2 | 28921 | 274704 | 93114 | 28921 | 66.10% |
| 2s-PAD-A-r3 | 29183 | 274583 | 92491 | 29183 | 66.32% |
| 2s-POST-r2 | 28628 | 274602 | 93241 | 27913 | 66.04% |
| 2s-POST-r3 | 29219 | 265437 | 93991 | 29219 | 64.59% |
| 2s-PRE-probe | 29843 | 276476 | 94702 | 29843 | 65.75% |

The twelve matrix traces below become baseline-admissible, but are **not
scorable retrospectively**: their old rejection stopped the run before stimulus.
There is no t_converge, rate or post-stimulus p99 to recover. Each has zero KEY
moves, the PRE placement, and Idle in the final decision window.

| Key-skew trace | baseline_client_moves | New baseline | Post-stimulus result |
|---|---:|---|---|
| 1s-PAD-A-r2 | 1 | PASS | NA — no stimulus |
| 1s-PAD-A-r3 | 1 | PASS | NA — no stimulus |
| 1s-POST-r2 | 1 | PASS | NA — no stimulus |
| 1s-POST-r3 | 1 | PASS | NA — no stimulus |
| 1s-PRE-r1 | 1 | PASS | NA — no stimulus |
| 1s-PRE-r2 | 2 | PASS | NA — no stimulus |
| 1s-PRE-r3 | 1 | PASS | NA — no stimulus |
| 2s-PAD-A-r1 | 1 | PASS | NA — no stimulus |
| 2s-POST-r1 | 1 | PASS | NA — no stimulus |
| 2s-PRE-r1 | 1 | PASS | NA — no stimulus |
| 2s-PRE-r2 | 2 | PASS | NA — no stimulus |
| 2s-PRE-r3 | 1 | PASS | NA — no stimulus |

In particular, 2s PRE r3 contains 931 samples. Its old persisted primary reason
was "sampler failed: [Errno 104] Connection reset by peer"; its saved baseline
verdict charged one client move. The new baseline passes and that teardown error
is not substituted for a stationarity verdict. The missing stimulus cannot be
reconstructed. No PRE matrix episode completed in run 4, so these individual
recoveries do not establish a paired PRE/PAD/POST campaign verdict.

Run 3 replay is **blocked by missing input**. Neither this worktree's build/
directory nor searches under /home/user contain
lbplanner-episodes-mainline-03 or matching archived inputs. The older
/home/user/Projects/cx-lbplanner worktree is also absent. A request for its local
path was sent during this lane; no path has been supplied. Bench3's request
records a previous 34/36 baseline replay and eight unarmed 1s key traces, but
those are prior reported results, not a bench4 replay. The new Idle/placement
checks and per-row numbers cannot be claimed without those files.

| Requested replay | Available evidence | Bench4 result |
|---|---|---|
| Run 3 | Prior prose summary only; no telemetry.jsonl/run.json pairs located | Not replayed; per-episode numbers unavailable |

Run 5 (`build/lbplanner-episodes-mainline-05`) was additionally replayed to
check the 21:00 counterexample. All 20 saved baselines pass the client rule;
the twelve matrix traces that stopped pre-stimulus remain unscorable. The six
completed traces have zero KEY moves and suffix_other=0:

| Client-skew trace | Old → new episode verdict | t_converge s | CLIENT | thrash_moves | Rate Mops/s | p99 ms |
|---|---|---:|---:|---:|---:|---:|
| 1s-PAD-A-r1 | PASS → FAIL | 35.858 | 2 | 2 | 6.26057 | 2.415 |
| 1s-PAD-A-r2 | FAIL → FAIL | 189.859 | 7 | 5 | 6.29323 | 2.367 |
| 1s-PAD-A-r3 | PASS → FAIL | 121.858 | 5 | 1 | 6.33941 | 2.367 |
| 1s-POST-r2 | FAIL → PASS (still converging) | 210.159 | 7 | 1 | 6.41570 | 2.319 |
| 2s-PRE-r1 | FAIL → FAIL | 205.909 | 10 | 1 | 6.80000 | 2.079 |
| 2s-PRE-r2 | FAIL → PASS (still converging) | 211.908 | 10 | 3 | 6.68446 | 2.095 |

| Client-skew trace | base | peak | end (3s mean) | min | Reduction | Final 30s slope (spread/s) |
|---|---:|---:|---:|---:|---:|---:|
| 1s-PAD-A-r1 | 131691 | 249178 | 260248 | 131691 | -4.44% | -93.89 |
| 1s-PAD-A-r2 | 123640 | 490377 | 214135 | 123640 | 56.33% | 313.27 |
| 1s-PAD-A-r3 | 143202 | 246585 | 208302 | 143202 | 15.53% | -12.48 |
| 1s-POST-r2 | 135516 | 244143 | 200334 | 135516 | 17.94% | -405.88 |
| 2s-PRE-r1 | 127865 | 818769 | 69287 | 29757 | 91.54% | 912.68 |
| 2s-PRE-r2 | 79458 | 795723 | 59507 | 34074 | 92.52% | -1004.46 |

PAD-A2 1s r1 fails for no spread reduction. PAD-A2 1s r2/r3 and PRE 2s r1
report moves after their last 5% improvement and fail the progress/thrash rule.
POST2 1s r2 and PRE 2s r2 pass as still converging. POST2 r2's final three-second
mean is 200334, versus 197873 in the preceding three seconds, while the final
30-second trend is falling at 405.88 spread units/s. This is why a single
three-second difference must not invert its convergence classification. No 1s
PRE completed, and 2s PAD/POST did not reach stimulus, so run 5 also cannot
establish a complete paired verdict.

For provenance, the SHA256 of the sorted JSON mapping each episode name to its
run.json and telemetry.jsonl SHA256 is below. The inner keys are `run` and
`telemetry`; serialization is Python `json.dumps(mapping, sort_keys=True)`.

| Saved campaign | Evidence manifest SHA256 |
|---|---|
| 04 | ca85b3dafbcaed06cd38e2a0d09bc6429301cb6ce51843ec04cfe0b2346f8999 |
| 05 | c15613153ec968ec2f31138ba31db1a0f402159500ad9c73f2fc6e18b0ac5561 |

Mainline invocations are the run-4/run-5 command shapes with fresh output
directories 06/07 and the same fixed-arm receipt. Run these from the mainline
worktree containing this harness after integration, on the maintainer's exclusive
measurement slot:

```sh
HOTMAX=256 taskset -c 0-111 python3 tools/lb_episodes.py --episodes key-skew --arms /home/user/Projects/bench-bins/lbplanner/arms-fixed.json --output build/lbplanner-episodes-mainline-06
taskset -c 0-111 python3 tools/lb_episodes.py --episodes client-skew --hot-pipeline 4 --arms /home/user/Projects/bench-bins/lbplanner/arms-fixed.json --output build/lbplanner-episodes-mainline-07
```

Both balancers remain enabled. Server affinity remains 0–15, loader affinity
64–95, baseline 60 seconds, default server shards, and max-converge/suffix
180/30 seconds. Key hot depth is 128; client hot depth is 4, cold/balanced depth
128. The episode duration remains 216 seconds with a fixed 213-second scored
endpoint. Nominal load time remains 6366 seconds (run 6, about 110–120 minutes
wall) and 5748 seconds (run 7, about 100–110 minutes wall). No PAD-B is requested.

Serverless validation: **37/37 self-tests pass** on CPUs 112–127. Tests include
controller-specific baseline movement (including the first final-window poll),
reported suffix_other and client-suffix key rejection, continuing monotone spread
improvement, late endpoint noise, flat/plateau thrash, exact spread windows and
zero peak, PRE-only paired tolerance and stalled controls, and both unit and
run_episode orchestration checks for joining the sampler before teardown without
masking the primary failure. Existing arming, receipt, geometry, accounting,
Fisher/PassLimit, rebound (including ongoing client convergence), missing-endpoint
and dry-run tests still pass. The reproduction script below was executed with
process creation, sockets and Path.write_text blocked: it reproduced all 43
accepted baselines and 14 completed episode verdicts across runs 4 and 5.

Default/both, key-skew HOTMAX=256, and client-skew hot-pipeline=4 dry-run output
is byte-for-byte identical to 7cde71dcf. Frozen ARMS and selector C are identical;
AST checks also confirm unchanged probe, CLI, command construction, scheduling,
receipt/SHA validation, topology, metrics, actuator/Fisher comparison, and
diagnostic-envelope functions. git diff --check passes. No gate count changes.

The following serverless command reproduces the run-4/run-5 numerical rows
without writing to the saved campaigns. Add run 3's directory once it is restored;
its saved schema/criteria must be checked before claiming that replay.

```sh
taskset -c 112-127 python3 - <<'PY'
import json
import sys
from pathlib import Path
sys.path.insert(0, "tools")
import lb_episodes as h

for number in ("04", "05"):
    root = Path("build/lbplanner-episodes-mainline-" + number)
    cfg = json.loads((root / "manifest.json").read_text())["config"]
    criteria = json.loads((root / "criteria.json").read_text())
    for path in sorted(root.glob("*/run.json")):
        saved = json.loads(path.read_text())
        with path.with_name("telemetry.jsonl").open() as stream:
            samples = [json.loads(line) for line in stream]
        kind = saved["episode"]
        calibration = kind == "balanced"
        if calibration:
            kind = cfg["episodes"]
        criterion = saved.get("criterion") or criteria[saved["mode"]]
        start = saved["baseline"]["start"] + cfg["warm"]
        balanced = [s for s in samples if start <= s["t"] <= start + cfg["baseline"]]
        baseline = h.baseline_stationarity(
            balanced, None if calibration else criterion["shard_owners"], kind)
        print(number, path.parent.name, "baseline", baseline["status"],
              "baseline_client_moves", baseline.get("baseline_client_moves"))
        if saved.get("stimulus_t") is None:
            print("NA: no stimulus")
            continue
        stimulus = saved["stimulus_t"]
        end = stimulus + cfg["max_converge"] + h.DECISION_SECONDS + cfg["suffix"]
        result = h.convergence(
            samples, stimulus, end, criterion, kind,
            cfg["max_converge"], cfg["suffix"],
            h.diagnostic_envelope(criterion, baseline["spread_maxima"]))
        print(h.episode_row(dict(saved, **result,
                                 baseline_client_moves=baseline["baseline_client_moves"])))
        print(result["status"], result["reason"],
              "measurement_valid", saved.get("measurement_valid", False))
PY
```
