Lane lbplanner-bench3 — armable convergence instrument — 2026-10-04

Delivered on `cx-lbplanner-bench3`, worktree
`/home/user/Projects/cx-lbplanner-bench3`. Read both previous measurement requests
before editing. Fetched and merged `origin/cpp` first: already up to date at
`241f8b8f62f8d18c761762df66ecf9803d725ff5`, an ancestor of this lane. Implementation
commits start with `c90678ca0` and `9cfb42a88`; subsequent commits complete the
validation and this handoff. Mainline owns all live runs. Nothing was pushed.

Only `tools/lb_episodes.py` and this request changed. There are no server changes,
new gate rows, EXPECT changes, fixture edits, or rebuilt measurement binaries.
The frozen ARMS table and embedded owner-select LD_PRELOAD C source were checked
against `6c9cb4b85` and are identical.

Implementation sites in `tools/lb_episodes.py`:

| Site | Change |
|---|---|
| 74 `bind_arms`, 108 `verify_arms` | Optional explicit receipt replaces the frozen table; binary and receipt SHA checks remain mandatory, including before each boot. |
| 181 `geometry`, 610 `server_command`, 646 `boot` | Default omits `--shards`; observe the contiguous DEBUG LBSIGNALS map, cross-check INFO, and validate any explicit count. |
| 234 `baseline_stationarity`, 276 `envelope` | Own-run quiescence; all raw-sample maxima; default balanced window is 60 seconds. |
| 296 `diagnostic_envelope`, 320 `convergence` | Diagnostic envelope return; last required move, stationary suffix and frozen PRE rebound width decide convergence. |
| 309 `actuator_mix`, 419 `metrics`, 623 `load_command` | Actuator deltas/high-water evidence; hot pipeline selection and its actual outstanding-operation accounting bound. |
| 699 `key_mapping`, 711 `prepare_seed`, 772 `run_episode` | Observed shard counts and matched per-mode snapshots, physical key maps, receipt identity and per-run evidence. |
| 742 `probe_verdict`, 751 `episode_row`, 1069 `main` | One PRE key admission probe per mode before the matrix; UNARMED receipt and exit 3. |
| 881 `schedule`, 934 `assess`, 984 `dry_run`, 1036 `wall_seconds`, 1045 `argument_parser` | Episode filtering, actuator comparison, probes printed first, revised runtime and CLI defaults. |
| 1151 `SelfTest` | Synthetic traces, receipt/CLI/orchestration tests, saved-log topology and unchanged accounting checks. |

The server default is `cfg_default_shards(executors)` in `src/core/config.h:465`:
8 shards per executor below 32 executors. On the existing 0–15 affinity this means
128 shards for 16 fused owners and 64 for the default eight split executors.
Counts are observed, not substituted by the harness. Each mode gets its own PRE
population/snapshot because its shard count differs. Every calibration, probe,
arm and round within that mode restores the same SHA-bound snapshot and verifies
the same physical hot-key map. `manifest.json.identity.shards` records both
observed counts; each `run.json` records `shards`, requested override, HOTMAX,
hot pipeline, binary SHA and receipt identity. Seed manifests also record shards.

`--episodes key-skew|client-skew|both` defaults to `both`. A single kind selects
18 matrix runs, retaining both modes, three rounds, and the existing alternating
PRE/PAD-A/POST order. Only the needed PRE mode calibrations run. HOTMAX still
defaults to 2000, with the same environment/CLI override and exact key ranges:
hot 1..HOTMAX, cold HOTMAX+1..500000. No automatic HOTMAX or shard changes occur.

For campaigns containing key-skew, after PRE calibration and before any matrix
run, one full key-skew probe runs on PRE in each mode. A valid probe with
`tomokv_keylb_bucket_moves` delta zero refuses the matrix, writes `probes.json`,
an empty `results.json`, and `report.json` with status REFUSED, and exits **3**.
It emits this receipt (with actuator fields appended):

```text
LBPLANNER-EPISODE key-skew <mode> PRE probe UNARMED hotmax=<n> shards=<n> hysteresis_refused=<n> no_candidate=<n> hot_bucket_refused=<n>
```

The probe only establishes admission, not convergence. A moved but nonconvergent
probe records its separate convergence result and admits the scored matrix.
Missing telemetry, a moving baseline, or failed workload accounting is a probe
FAIL, not evidence of an unarmed stimulus. Scored failures are never retried.
`--dry-run` prints the probe commands first as an explicitly labelled preview;
their seed/calibration prerequisites follow, then the scored commands. It opens
no sockets, starts no processes, and creates no output files.

Pre-stimulus stationarity now requires zero bucket plus client moves across the
run's own balanced window (at least nine closed beats and nine seconds), stage
Idle throughout the final decision window, and the same shard placement as PRE.
Every raw 100 ms sample contributes to the reported spread maxima, including
samples between closed-beat endpoints. Maxima and numeric failure details appear
in `run.json.baseline_stationarity` and reason text. A different boot's maxima
never gate stationarity. The former in-envelope fraction remains diagnostic.

Convergence requires an actual move of the episode's kind; key episodes also
require an admitted bucket gather. `t_converge` is the first telemetry observation
of the **last** required move minus `stimulus_t`, with the preceding/current poll
interval retained. It must not exceed `--max-converge`. All key/client/total moves
remain charged through the fixed endpoint. Any other move after that last
required move fails; it cannot restart a more favourable clock.

The first closed controller beat after the last move supplies the refreshed
primary spread level (current spreads are refreshed at ticks). From this fixed
beat through the endpoint, a suffix must cover at least `--suffix` seconds and
three actual controller tick advances, have stage Idle, and have zero total
moves. No subsequent primary spread sample may exceed that level plus the
**frozen PRE envelope width**. The retained PRE envelope is [0, raw-sample max],
so its width is that PRE maximum. Neither an arm nor its own baseline widens this
pass limit. Missing endpoint coverage, counter resets, missing fields, missed
ticks, active plans and telemetry gaps over 500 ms fail with numeric evidence.

`envelope_return_t` reports the final sustained return to the diagnostic envelope;
it may be NA on a passing episode. For each metric its diagnostic upper limit is
`max(PRE maximum * (1 + release margin), own baseline maximum)`. The margin is
`0.8 * sampling_floor(owner_count) / 100`, the controller's **minimum** Schmitt
release band. Existing telemetry does not export learned QuietJitter, so this is
explicitly labelled a floor, not a reconstruction of the possibly larger live
band. It affects only this diagnostic. No new sampler or server field was added.

The controller constants and limitation are grounded in `weighted_lb.h:27`
(`kDecisionTicks=3`), `:29` (4096 samples/owner), `:52` (`sampling_floor`) and
`:92` (QuietJitter update and `max(2*jitter, sampling_floor)` band). On this merged
branch the controller body is in `src/core/lbplanner.cc`: `:59`/`:401` contain
`update_streak`, `:66`/`:408` the 0.8 release factor, and `:135`/`:470` the
dominant-bucket refusal. These server files were read, not changed.

`--arms FILE` accepts exactly:

```json
{
  "PRE": {"path": "/absolute/path/to/pre", "sha256": "<64 lowercase hex digits>"},
  "PAD-A": {"path": "/absolute/path/to/pad-a2", "sha256": "<64 lowercase hex digits>"},
  "POST": {"path": "/absolute/path/to/post2", "sha256": "<64 lowercase hex digits>"}
}
```

Relative binary paths are resolved against the receipt's directory. Its absolute
path and its own SHA-256 are recorded in the campaign manifest and every run,
alongside the bound artifact SHA. Changing either the receipt or a binary after
binding fails before boot. Without `--arms`, the original frozen table and its
refusal text remain. **PAD-A is kind A: PRE behaviour with candidate text
size/layout.** A receipt binds identity; it does not establish the twin's validity.

`--hot-pipeline N` defaults to 128 and applies only to the hot stimulus cohort.
Cold and balanced cohorts keep pipeline 128; owner selection is unchanged.
The finite Count/HDR allowance uses each cohort's actual depth: at hot depth 4
the aggregate bound is 64*(128+4), while server SET calls must still equal drained
HDR counts exactly. Rates, merged HDR p99, cohort comparisons and coordinator
occupancy retain their existing meanings.

Every episode receipt appends:

```text
shards=<n> hotmax=<n> envelope_return_t=<s|NA> stall=exec:<n>,proto:<n>,passl:<n>,dest:<n>,pipe:<n>,defout:<n>,cstate:<n> pending_ms=<ms> attempts=<n>
```

The original matrix-row prefix and field order through `coord_busy` are retained.
Stall counts are post-stimulus INFO LB deltas; JSON also retains invalid-client
refusals. `attempts = client_refused delta + client_moves delta`. `pending_ms` is
the endpoint `tomokv_lbstall_pending_ns_max / 1e6`; JSON retains its pre-stimulus
value and explicitly identifies it as a lifetime high-water mark. Differences
between maxima are not misreported as durations. Unavailable values remain NA.

POST must converge no slower than PRE, make no more key/client/total moves, and
lose no aggregate or cohort rate/p99 in each paired round. Every arm must itself
converge. In addition, POST's reason proportions must match both PRE and PAD-A
within counting noise, and its **pass-limit refusal count must equal PRE's
exactly**. The proportion comparison is the two-sided exact conditional test of
two binomial counts (Fisher), with attempts as denominators. A fixed 5% family
error budget is Bonferroni-divided across the predeclared paired comparisons and
eight reasons: alpha 0.05/96 for one episode kind, 0.05/192 for both. A zero-attempt
pair with zero counts is unchanged; only one zero-attempt arm cannot establish
equality and fails. Report JSON retains counts, denominators, p-values and limits,
including available comparisons when convergence itself failed. This counting
model assumes binomial attempts; it is not a performance noise allowance or a
replacement for mainline's same-binary nulls.

After mainline integrates this harness and receives the reviewed fixed-arm
receipt, replace `<receipt>` below with that receipt's path. Keep output
directories new and schedule the box exclusively.

```sh
cd /home/user/Projects/cx-lbplanner
HOTMAX=256 taskset -c 0-111 python3 tools/lb_episodes.py --episodes key-skew --arms <receipt> --output build/lbplanner-episodes-mainline-04
taskset -c 0-111 python3 tools/lb_episodes.py --episodes client-skew --hot-pipeline 4 --arms <receipt> --output build/lbplanner-episodes-mainline-05
```

Both commands use default server shards and the default 60-second baseline.
Each baseline loader lasts 30 warm + 60 baseline + 3 guard = 93 seconds; each
stimulus lasts 180 max-converge + 3 decision + 30 suffix + 3 guard = 216 seconds.

| Campaign | Nominal load time | Expected wall time |
|---|---:|---:|
| Run 4: key-skew, 2 PRE calibrations + 2 probes + 18 scored episodes | 6366 s = 106.1 min | **110–120 min** |
| Run 5: client-skew, 2 PRE calibrations + 18 scored episodes | 5748 s = 95.8 min | **100–110 min** |
| Default both, 2 PRE calibrations + 2 probes + 36 scored episodes | 11928 s = 198.8 min | About 205–215 min |

Wall estimates include population, snapshot copying, boot, selection and teardown
overhead. Up to four extra fresh-state PRE calibration attempts add at most 6.2
minutes of load time. A refused key probe stops before all 18 scored runs.

Serverless verification on CPUs **112–127**: 29/29 `--self-test` cases passed;
both requested dry runs rendered successfully with no server shard override;
the default dry run rendered probes first and all 36 matrix entries. Synthetic
tests cover unarmed refusal/exit 3, quiescent convergence, suffix movement,
non-return with NA diagnostic, late rebound, missing endpoint/ticks, quiet spreads
20% above PRE, raw-sample maxima, receipt and binary tampering, hot-depth
accounting, and a 128-shard saved server.log excerpt. That excerpt was verified
against the original file; its 32-thread topology parses but correctly fails the
16-thread episode geometry, while the separate 16-fused/128-shard case passes.

Read-only replay of run 3's persisted telemetry reproduced the actuator deltas:
1s r1 PRE exec=46/proto=23/passl=0, PAD-A 30/40/0, POST 4/57/10, each with 71
attempts. The new own-baseline rule accepts 34/36 saved windows. The two retained
failures, key-skew 1s POST r2 and 2s POST r3, each contain one actual client move;
their spread maxima are no longer the rejection reason. All eight completed 1s
key-skew traces still have zero key moves and classify as UNARMED. This replay
is validation of the instrument, not a new measurement or a claim that old runs
meet the new default geometry. No server, memtier, benchmark or gate was run.
