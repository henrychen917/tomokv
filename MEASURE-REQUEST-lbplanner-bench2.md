Lane lbplanner-bench2 — split topology correction — 2026-10-04

Committed implementation: `212330a07` on `cx-lbplanner`, worktree
`/home/user/Projects/cx-lbplanner`. First fetched and merged `origin/cpp`:
already up to date at `241f8b8f62f8d18c761762df66ecf9803d725ff5`, which is an
ancestor of the lane's starting HEAD `3577f8c9e`.

The failed mainline run passed whole-server counts `--ratio 6:2`, producing
eight threads. Its saved log records IO IDs `0,1,2,4,5,6` and EX IDs `3,7`.
The instrument incorrectly required 12 IO + 4 EX and could never arm.

`tools/lb_episodes.py` now boots both modes without a server `--ratio`, matching
`/home/user/Projects/calib/lb-stationary.sh`. On cores 0–15, the default split is
8 IO + 8 EX. Geometry validation requires 16 IO/EX threads with at least two
IO threads, accepting the split actually reported by DEBUG LBSIGNALS. Fused
mode still requires exactly 16 fused threads. Geometry failures print the
observed role Counter, including the original `Counter({'io': 6, 'ex': 2})`.

Every live connection target comes from the sorted IO/fused IDs in the booted
DEBUG LBSIGNALS rows. Baseline and key-skew cohorts use that complete list;
the hot client-skew cohort uses its first two IDs. EX IDs cannot enter the
split-mode LD_PRELOAD target list. Dry-run prints explicit runtime owner
placeholders instead of inventing a contiguous owner range.

Mainline invocation on its scheduled quiet box, using a new output directory:

```sh
cd /home/user/Projects/cx-lbplanner
python3 -B tools/lb_episodes.py --self-test
python3 -B tools/lb_episodes.py --dry-run \
  --output build/lbplanner-episodes-mainline-02 \
  > build/lbplanner-episodes-mainline-02.commands.txt
taskset -c 0-111 python3 -B tools/lb_episodes.py \
  --output build/lbplanner-episodes-mainline-02
```

Expected full-campaign wall time: **160–170 minutes**. Nominal load time is
158.1 minutes: two 45-second PRE balanced calibrations and 36 scored runs of
45 + 216 seconds. Population, SAVE, boot and connection setup add overhead;
bounded fresh-state calibration retries can add up to three minutes of load.
The previous `mainline-01` output remains evidence of the failed attempt;
the rerun calibrates both modes afresh. Servers use cores 0–15, loaders and
the sampler use 64–95, with 16 shards and both balancers enabled.

Serverless verification completed:

- `--self-test`: 16/16 passed. The added parsing case embeds the exact eight
  startup rows from `build/lbplanner-episodes-mainline-01/balanced-2s-PRE-r1/server.log`,
  converts its displayed `ifid` roles to DEBUG LBSIGNALS `io` rows, and rejects
  that undersized topology with the observed counts. The excerpt was checked
  against the saved file. Tests also accept interleaved 8:8, 6:10 and 2:14
  topologies, check full/subset selector targets, retain the 1s requirement,
  and reject wrong counts or mixed fused/split roles.
- `--dry-run`: rendered all 43 possible server commands (including conditional
  calibration retries) without server `--ratio`. All 156 selector commands
  use boot-derived owner placeholders. Its self-test forbids process creation,
  sockets and directory creation. Local output: `build/lbplanner-bench2-dry-run.txt`.
- `git diff --check`: passed.

The PRE, PAD-A and POST paths and SHA pins, workload shapes, alternating rounds,
100 ms telemetry, convergence envelope and scoring are unchanged. PAD-A remains
kind A: PRE behaviour with candidate text size/layout. Pass rule: **POST
converges no slower than PRE and makes no more key/client/total moves, with no
rate or p99 loss**, in every paired round.

No server, memtier workload, benchmark or gate was run. No binaries were rebuilt,
no EXPECT constants or fixture files were edited, and zero gate rows were added.
Nothing was pushed. Live arming and convergence results remain mainline-owned.
