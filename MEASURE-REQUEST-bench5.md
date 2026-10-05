Lane bench5 — cumulative thrash, owner cycles and read-only replay

Delivered on `cx-bench5` in `/home/user/Projects/cx-bench5`, based on
`f769efcdd`. Read bench3/bench4's measurement requests and PLAN-SERIAL's
2026-10-05 14:35/15:05 entries before implementation. The implementation
commits start with `351f28157` and `a7d675235`; the final handoff commit includes
this request. Changes are confined to `tools/lb_episodes.py`, its embedded
self-tests, and this document. No server, memtier, benchmark or gate was run.
All Python checks/replays ran on CPUs 112–127. Nothing was pushed. There are no
server/layout/binary changes and no new measurement arms. Gate rows and
EXPECT_QUICK/EXPECT_FULL are unchanged: **count delta 0/0**. No fixtures changed.

PAD-A everywhere below is **kind A, behaviour twin: PRE behaviour with the
candidate's text size/layout**. No PAD-B is requested.

The rule changes are:

1. `thrash_moves` is cumulative. Partition the scored stimulus interval into
   disjoint three-second windows anchored at `stimulus_t`. At each endpoint,
   compare the trailing three-second raw-sample spread mean with the running
   best; charge that window's required-kind counter delta unless the mean is
   at least 5% lower. Each move is charged at most once. The first six seconds
   retain the existing fixed-peak reference to avoid establishing a low record
   on the rising edge; subsequent windows update `best = min(best, mean)`, even
   for improvements smaller than 5%. A partial final window charges only its
   new moves, using its trailing three-second mean. Later improvements never
   subtract prior charges. `thrash_windows` records every decision and its
   counter delta. `milestone_moves` preserves the previous last-milestone
   quantity. Key-skew still reports thrash diagnostically; the existing client
   stalled-thrash check now uses the cumulative count, retaining the existing
   exception for continued spread improvement.

2. `shard_moves`, `returns`, `exchanges`, and `distinct_shards` come from
   consecutive sampled DEBUG LBSIGNALS owner maps over the **entire captured
   episode**, including warmup and final guards. This is the scope used by the
   owner's run-8 totals. A return visits any owner previously held by that shard,
   including its initial owner. An exchange counts one unordered owner pair
   per sample interval containing both A→B and B→A moves of distinct shards;
   several shards travelling in either direction still count as one pair.
   `distinct_shards` counts shards with at least one observed move. These are
   observed transitions; multiple hidden moves between polls cannot be inferred.
   Changed/incomplete shard maps and sampling gaps over 500 ms fail validation.
   `owner_tracking` records the scope, endpoints and moved shard IDs. Every
   paired round now requires **POST <= PRE and POST <= PAD-A for all four
   quantities**, for both episode kinds. Comparisons remain visible even when
   convergence fails. Missing owner evidence fails the paired rule.

3. Every balanced cohort and the cold stimulus cohort uses an explicit
   64-entry round-robin connection-index plan over sorted boot IO/fused owners;
   the client-skew hot cohort uses the first two such owners. All pass through
   the existing owner-select preload. `run.json.cohort_owners` records the
   requested map, and the existing `baseline.owners` / `owners` receipts must
   verify every selected connection index against it. Executor-only IDs remain
   excluded. The selector C source is unchanged.

   **Placement finding:** `f769efcdd` already used owner-select for both balanced
   cohorts and the cold cohort. Run 7's archived receipts show exactly four
   connections per fused owner per baseline cohort in every 1s round, and eight
   per IO owner in every 2s round. Their complete index→owner maps are identical
   within each mode. Expanding the previous cyclic owner list to an explicit
   64-entry plan preserves those choices and makes them directly reviewable.
   This evidence does not establish a placement explanation for the bimodal
   peaks; **no claim that the bimodality is fixed** is supported by this replay.

4. A client-skew baseline may contain at most one client move in its final
   decision window if the full 60-second baseline has zero key moves and the
   last nine sampled controller ticks are Idle. The accepted sampled span must
   be at least 59.5 seconds, allowing the existing 500 ms sampling bound. Two
   final-window moves, an active plan within the last nine ticks, a key move,
   or a shorter baseline still fails. The observation preceding the final
   window still brackets its first counter change. The count is reported as
   `baseline_decision_client_moves`, retaining `decision_client_moves` in the
   nested baseline record for compatibility. Zero-move baselines retain the
   existing stationarity rule.

5. Optional post-stimulus deltas are recorded for
   `tomokv_keylb_{reversal_refused,recent_move_refused,owner_pair_refused,history_escapes}`
   in `history_counters`. `refused` is `reversal_refused`, the aggregate refusal
   counter; recent-move and owner-pair reasons can overlap. `escapes` is
   `history_escapes`. Any absent counter is NA, including partial availability;
   observed resets fail. Old telemetry containing string-valued optional INFO
   fields is supported. A read-only check of run 9's 1s POST r1 produced
   150 aggregate refusals, 128 recent-move reasons, 36 owner-pair reasons and
   one escape, confirming that the reasons must not be summed.

6. `--replay RUNDIR` accepts a campaign, a single episode, or an archive
   collection. It reads saved configuration and each run's frozen PRE criterion
   (falling back to `criteria.json`), rescoring baselines, convergence, thrash,
   owner histories and optional counters. It never refits PRE, checks current
   arm binaries, starts a process/socket, changes affinity, or writes into the
   run directory. Rate, HDR p99 and accounting remain explicitly labelled saved
   measurements. Previously invalid workload evidence cannot become valid by
   rescoring. Missing telemetry clears old scores to NA; missing configuration,
   frozen criteria, scheduled runs, and stimulus evidence are reported. A newly
   admissible baseline cannot manufacture a stimulus that was never run.
   Exit 0 requires a complete passing paired campaign; failures or incomplete
   evidence return 1. Archived boot receipts are preserved; replay cannot apply
   a new connection plan to an old workload.

Rows append `moves=<n> returns=<n> exchanges=<n> shards=<n>` for the four owner
metrics and `refused=<n> escapes=<n>` for key-skew. The baseline decision count
is also printed. To give `shards` one unambiguous meaning, the earlier topology
field is now printed as `shard_count`; `run.json.shards` still records the boot
shard count, while `run.json.distinct_shards` is the observed moved-shard count.

Run 8 was replayed from
`/home/user/Projects/cx-final/build/lbosc-episodes-08`. All 22 telemetry files
are present: two calibrations, two admission probes and 18 scored episodes.
All baselines pass, both probes remain ARMED, and the matrix retains 13 episode
PASS / 5 FAIL. Every saved convergence time, key/client/gather count, spread
base/peak/end/min, rate and p99 matches the replay exactly. Cumulative thrash
and the additional owner comparisons change the reported evidence. In
particular, 1s POST r2 now reports **thrash_moves=21**, versus the old zero;
its 32 observed moves, one return, two exchanges and 19 moved shards are retained.

The table shows matrix episodes only. `decision` means
`baseline_decision_client_moves`; `shards` means `distinct_shards`. NA counters
are absent in these older binaries, not measured zeros.

| Mode | Arm | Round | Episode | Thrash old → new | moves | returns | exchanges | shards | decision | refused | escapes |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1s | PRE | 1 | PASS | 1 → 7 | 20 | 0 | 2 | 14 | 0 | NA | NA |
| 1s | PAD-A | 1 | PASS | 0 → 8 | 14 | 0 | 1 | 12 | 0 | NA | NA |
| 1s | POST | 1 | PASS | 0 → 7 | 17 | 0 | 1 | 13 | 0 | NA | NA |
| 1s | PRE | 2 | PASS | 0 → 5 | 12 | 0 | 1 | 11 | 0 | NA | NA |
| 1s | PAD-A | 2 | PASS | 0 → 10 | 17 | 0 | 1 | 15 | 0 | NA | NA |
| 1s | POST | 2 | FAIL | 0 → 21 | 32 | 1 | 2 | 19 | 0 | NA | NA |
| 1s | PRE | 3 | FAIL | 29 → 32 | 42 | 20 | 1 | 13 | 0 | NA | NA |
| 1s | PAD-A | 3 | PASS | 0 → 8 | 16 | 1 | 1 | 12 | 0 | NA | NA |
| 1s | POST | 3 | PASS | 0 → 3 | 18 | 0 | 0 | 14 | 0 | NA | NA |
| 2s | PRE | 1 | FAIL | 14 → 22 | 27 | 17 | 4 | 6 | 0 | NA | NA |
| 2s | PAD-A | 1 | PASS | 0 → 0 | 8 | 0 | 1 | 7 | 0 | NA | NA |
| 2s | POST | 1 | PASS | 1 → 1 | 10 | 0 | 2 | 8 | 0 | NA | NA |
| 2s | PRE | 2 | PASS | 0 → 0 | 7 | 0 | 1 | 7 | 0 | NA | NA |
| 2s | PAD-A | 2 | PASS | 1 → 1 | 6 | 0 | 0 | 5 | 0 | NA | NA |
| 2s | POST | 2 | FAIL | 14 → 14 | 22 | 8 | 2 | 7 | 0 | NA | NA |
| 2s | PRE | 3 | FAIL | 14 → 21 | 28 | 17 | 2 | 7 | 0 | NA | NA |
| 2s | PAD-A | 3 | PASS | 1 → 0 | 9 | 1 | 1 | 7 | 0 | NA | NA |
| 2s | POST | 3 | PASS | 0 → 1 | 5 | 0 | 1 | 5 | 0 | NA | NA |

Totals below sum the three matrix rounds; spread is the mean of their unchanged
saved three-second endpoints. Paired decisions are still per round.

| Mode | Arm | Cumulative thrash | Observed moves | Returns | Exchanges | Mean spread_end |
|---|---|---:|---:|---:|---:|---:|
| 1s | PRE | 44 | 74 | 20 | 4 | 54381.474 |
| 1s | PAD-A | 26 | 47 | 1 | 3 | 47626.762 |
| 1s | POST | 31 | 67 | 1 | 3 | 45833.874 |
| 2s | PRE | 43 | 62 | 34 | 7 | 104871.554 |
| 2s | PAD-A | 1 | 23 | 1 | 2 | 91593.303 |
| 2s | POST | 16 | 37 | 8 | 5 | 102095.900 |

The moves/returns/exchanges totals reproduce PLAN-SERIAL's 15:05 accounting.
The full capture includes one additional move/return in 1s PRE r3 and two in
2s PRE r3 after the fixed scored endpoint. INFO `key_moves` and thrash remain
bounded by that endpoint, explaining their different counts. Five of six
rounds fail at least one new owner comparison; 2s r3 passes those comparisons
but its PRE control fails convergence. The overall paired verdict is **FAIL**
in all six rounds, consistent with the recorded NO-GO. The existing strict
rate/p99, actuator-mix, PassLimit and convergence rules remain in force.

Run 6/7 evidence is available under
`/tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/evidence-1005/lbplanner-episodes/`.
Their live telemetry directories were not found in the project worktrees.

| Campaign | Saved run.json | Present telemetry | Replay outcome |
|---|---:|---:|---|
| run-06 | 22 | 0 | All current-rule scores NA; each missing telemetry path reported |
| run-07 | 20 | 0 | All current-rule scores NA; each missing telemetry path reported |

Run 7's `client-skew-2s-POST-r1/run.json` records one final-window client move,
zero baseline key moves, and no `stimulus_t`. The archive cannot prove the new
nine-Idle-tick condition without telemetry, and no post-stimulus result exists
to recover. The acceptance/reporting rule is covered by the synthetic test.

Input SHA256 maps were identical before and after replay. Each receipt below
hashes `json.dumps(mapping, sort_keys=True).encode()`, where the mapping binds
relative paths to file SHA256s for manifest.json, criteria.json, every run.json,
and every telemetry.jsonl present in that campaign.

| Campaign | Files | SHA256 of evidence map |
|---|---:|---|
| 08 | 46 | `5a4f8533db571370a233e9541482a3218d0d433821106a4102a817922ef7072c` |
| 06 | 24 | `20df57d3f3ebe4dee5d1d2147485a363231104b4c96faae08be64fb6f3ef3c9f` |
| 07 | 22 | `a3dddcd7af9032275295bb52e32f0be16df846ebf86b3d52cceb310d9016f51e` |

Serverless verification: **49/49 self-tests pass** on CPUs 112–127. New coverage
includes cumulative late-drop thrash for both controllers, the exact 5% boundary
and partial windows, 3-cycles, repeated owner visits, simultaneous and separate
exchanges, incomplete maps, both-control comparisons for both episode kinds,
full-length one-move baselines with Idle/KEY/two-move negative controls,
optional-counter absence/reset/string decoding, deterministic selector plans
and persisted run receipts, and read-only replay with process/socket/file-write
paths blocked. Replay tests check frozen criteria, old invalid accounting,
missing telemetry/configuration/pairs, guard-window owner moves, and newly
admissible baselines that lack stimulus. `git diff --check` passes.

Reproduction from this worktree (the real campaigns return exit 1 for the
documented FAIL/incomplete evidence):

```sh
taskset -c 112-127 python3 -B tools/lb_episodes.py --self-test
taskset -c 112-127 python3 -B tools/lb_episodes.py --replay /home/user/Projects/cx-final/build/lbosc-episodes-08
taskset -c 112-127 python3 -B tools/lb_episodes.py --replay /tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/evidence-1005/lbplanner-episodes/run-06
taskset -c 112-127 python3 -B tools/lb_episodes.py --replay /tmp/claude-1000/-home-user-Projects/ee6eb242-5302-49cf-b767-1a2d8d8f0f61/scratchpad/evidence-1005/lbplanner-episodes/run-07
```

For the maintainer's next scheduled client-skew campaign, use the integrated
harness, a fresh output directory and the intended matched receipt:

```sh
taskset -c 0-111 python3 tools/lb_episodes.py --episodes client-skew --hot-pipeline 4 --arms <matched-arms.json> --output build/lbplanner-episodes-bench5-client
```

This retains the existing 30s warm / 60s baseline / 180s max-converge / 30s suffix
and both modes with three paired rounds. Check that every same-mode cohort map
matches across arms and rounds, then inspect spread_peak clustering and the
current per-round pass rule. The placement receipts decide whether the stimulus
placement contract held; peak spread still needs measurement. No gain or removal
of bimodality is claimed without that new campaign. No server A/B is needed to
validate the scoring changes; the saved telemetry and serverless tests supply
their PRE-versus-current comparison above.
