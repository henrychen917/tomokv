Lane lbplanner-bench — convergence instrument — 2026-10-04

Delivered `tools/lb_episodes.py` on branch `cx-lbplanner`, in
`/home/user/Projects/cx-lbplanner`. Mainline owns all live runs. No server,
memtier workload, benchmark, or gate was run by this lane. Nothing was pushed.

First fetched and merged `origin/cpp` at
`aee02e84748f5b5ccd301ba9c206214651cd4189`; merge commit `931090de7`.
The two conflicts retained both branches' Server tail additions and gate jobs.
The instrument's first implementation is committed as `5d8405482`.
The measurement binaries remain the original frozen lbplanner artifacts;
they were **not rebuilt from the merged source**. Their SHA-256 checks pass.

Mainline invocation, on its scheduled quiet box:

```sh
cd /home/user/Projects/cx-lbplanner
python3 tools/lb_episodes.py --self-test
python3 tools/lb_episodes.py --dry-run \
  --output build/lbplanner-episodes-mainline-01 \
  > build/lbplanner-episodes-mainline-01.commands.txt
taskset -c 0-111 python3 tools/lb_episodes.py \
  --output build/lbplanner-episodes-mainline-01
```

The output directory must be new. The default port is 7931, also used by the
stationary driver: schedule these instruments separately. The runner refuses
an occupied port, verifies INFO's process ID against its own child, and reaps
only its own process groups. It never uses `pkill` or kills a listener discovered
by name. Python and loader work run on 64–95; servers run on 0–15. No work is
scheduled on 112–127.

Expected wall time is **about 160–170 minutes**. Nominal load time is 158.1
minutes: two successful PRE calibration runs at 45 seconds, plus 36 scored
runs at 45 + 216 seconds. Population, SAVE, boot, connection selection, and
shutdown add overhead. PRE calibration can re-arm on at most three fresh
snapshot/server instances per mode, adding at most three minutes of load time.
Every failed calibration attempt remains recorded. A scored failure is never
retried or replaced with a better result.

The matched experiment

| Property | Setting |
|---|---|
| Server geometry | 0–15; 16 shards; key-lb 1; client-lb 1; flip-auto 0; io_uring |
| Modes | 1s: 16 fused; 2s: `--ratio 6:2`, hence 12 IO + 4 EX on 16 cores |
| Population | Same stationary-driver shape: 500000 keys, 64-byte values, memtier t8/c4, SET, P:P, 15625 requests/client |
| Episode load | 128 connections, pipeline 128, SET only, R:R, 64-byte values; two t4/c16 cohorts |
| Balanced prelude | Both cohorts use keys 1–500000, selected evenly across actual IO owners; 30 seconds warm + 12 seconds baseline + 3 seconds teardown guard |
| Key stimulus | Cold cohort uses HOTMAX+1–500000; hot cohort uses 1–HOTMAX; default HOTMAX=2000, as in `calib/lb-stationary.sh` |
| Client stimulus | Same broad key range for both cohorts; 64 cold connections distributed across IO owners, 64 hot connections selected onto the first two actual IO owners |
| Post-stimulus observation | Fixed 216-second loader runs: up to 180 seconds to return, a full 3-second/3-tick sustain, 30-second suffix, and 3 seconds of teardown guard |
| Telemetry | INFO LB + DEBUG LBSIGNALS every 100 ms; raw and parsed records retained |

The ordinary steady baseline uses two t4/c16 processes, matching the stationary
driver's hot/cold process shape, instead of its single t8/c16 uniform process.
Both arms and phases retain 8 loader threads, 128 connections, p128, SET/R:R,
64-byte values, the same affinity and the same deterministic memtier seeds.
The stationary driver has client-lb 0; this task explicitly requires client-lb 1.
This instrument extends that workload family; its episode totals are not the
stationary driver's single cold-cohort row.

Default offered work is the stationary driver's **closed loop**, with identical
generator geometry in every arm. This does not claim identical achieved ops/s
or an open-loop arrival schedule. Optional `--rate-per-client N` applies the
same positive memtier rate cap to all arms and phases; 0 omits the cap. There
is no per-arm retuning. `--hotmax N` (or HOTMAX) changes the physical stimulus
for the entire campaign and is recorded in its manifest.

One PRE population is saved before calibration. Every subsequent boot receives
a copy of that same SHA-bound snapshot, which restores the hash seed. The
runner verifies the hot keys' actual `DEBUG SHARDS` map on every boot. A new
random hash seed per arm would not be a matched physical-key experiment.
The pre-stimulus shard-owner map must also match PRE's calibrated placement.

`DEBUG IO-THREAD` identifies each connection's real owner. A small C helper,
embedded in the Python file and compiled into the output directory by mainline,
interposes only connection setup. It tries fresh TCP sockets until the requested
owner is observed, bounded at 512 attempts. It records owner, connection index,
attempt count and CLOCK_MONOTONIC timestamp. All arms and both baseline/post
cohorts use this same helper. After setup, traffic goes directly between memtier
and the server; no forwarding process or per-operation send/receive hook is
present. UNIX sockets are not used: TomoKV distributes them round-robin.

Each cohort must prove exactly 64 selected connections, without reconnects.
The client stimulus therefore creates a measured connection-count imbalance,
instead of hoping that a random TCP burst happens to land unevenly. The
coordinator is the first actual client-serving thread, matching the frozen
PRE/PAD cron election and POST monitor selection. It is included among the
two client-stimulus targets.

The stimulus timestamp is CLOCK_MONOTONIC immediately before launching the
post-stimulus cohorts. Baseline generators have exited. Each selected socket's
timestamp and the latest connection-ready timestamp are retained; startup must
complete in less than one decision window. Thus `t_converge` includes connection
startup and the controller's response, rather than starting after the first
move. This is a bounded launch transition, not an assertion that all memtier
requests begin simultaneously. The before/after command-count boundary covers
the entire post-stimulus loader lifetime.

Calibration and scoring

Before the scored schedule, PRE alone supplies one balanced calibration per
mode. At least nine closed controller beats, spanning three full decision
windows, must have no moves and no active plan; every owner must execute work.
The fixed envelope is [0, PRE observed maximum] for each current bucket-weight,
bucket-bytes and client-weight spread. No candidate, PAD, later round, or
imbalanced trace can widen it. Separate PRE thresholds are appropriate for the
different fused and split owner geometries.

Every scored run must establish a stationary pre-stimulus baseline inside that
same envelope for the final complete decision window. It must then exhibit an
excursion in its episode's primary spread and a real move of the corresponding
kind. Key episodes additionally require an admitted bucket gather. INFO stage
values are recorded, but a fast plan is not required to remain visible for a
100 ms poll: completed move counters supply the persistent engagement witness.
A no-excursion, no-admission, no-move, missing-field, reset, missed controller
tick or telemetry gap over 500 ms fails. It cannot become a zero-time success.

The convergence time is the start of the final uninterrupted return of all
three current spreads into the PRE envelope, after the required move, with
stage Idle. Return must hold for both three seconds and three tick advances.
The remaining stationary suffix must cover at least the configured 30 seconds
and a complete decision window. Any later excursion restarts the sustain;
any suffix move fails the stationary requirement. The reported start uses the
last poll of each closed beat, conservatively resolving the controller's
one-second updates; the 100 ms raw trace preserves the timing uncertainty.
Duplicate polls of one tick never count as multiple decision beats.

Counter differences are charged from the last pre-stimulus sample through the
fixed observation endpoint, including the whole suffix. Key and client moves,
their sum, gathers, cross-domain moves and all requested refusal counters are
separate JSON fields. Suffix key/client/total movements are retained separately.
Before/after/current spread fields, all owner busy/idle/CPU counters and raw
DEBUG output remain in `telemetry.jsonl`. Per-process and main/monitor-thread
CPU ticks are also sampled; monitor CPU is not relabeled as IO productive work.

Rate sums both post-stimulus cohorts. The combined p99 is computed by merging
their SET HDR histogram counts, never by averaging percentiles. Hot/cold rate
and p99 are also compared separately so an aggregate cannot conceal a cohort
loss. The gate's audited finite Count/HDR bound is used only alongside exact
server SET calls == completed HDR counts. Interrupted or shortened runtimes,
connection errors, unaccounted operations and malformed histograms fail.
Memtier totals cover the full fixed post-stimulus runs, not the balanced
prelude. Coordinator busy is the measured busy/(busy+idle) delta on its physical
worker. Aggregate memtier histograms cannot assign latency to migrated
connections; coordinator-specific latency is explicitly unavailable, not
inferred from the aggregate p99 or CPU.

For each of key-skew/client-skew × 1s/2s:

| Round | Arm order |
|---|---|
| 1 | PRE, PAD-A, POST |
| 2 | POST, PAD-A, PRE |
| 3 | PRE, PAD-A, POST |

All rounds use the same precomputed PRE envelope. Keeping calibration separate
allows POST to run before PRE in round 2 without fitting a future candidate.

**Pass rule: POST converges no slower than PRE and makes no more moves, with
no rate/tail loss.** The implementation requires this for every paired round,
for key moves, client moves and their total separately, and for aggregate and
cohort rate/p99. It does not average away a losing episode/mode/round, and it
adds no invented rate or tail tolerance. PAD-A must also produce valid engaged
episodes. Its comparisons remain available for mainline's placement control;
this instrument alone does not establish a same-binary null or replace the
original lbplanner stable-load/4096-connection/gate requirements.

Important interpretation of the requested geometry

With 16 shards and 16 fused owners, initial placement has one shard per owner.
A sustained hot subset generally cannot be equalized by moving whole shards:
moving a hot shard onto an already occupied owner does not split its demand.
Also, an ordinary 2000-key numeric subset may hash broadly enough to produce
no admission. The split mode has four owners and four shards per owner, so its
feasible movements differ. A bytes-spread increase can also prevent return to
the complete balanced envelope even if weight spread improves.

The runner preserves the requested geometry and fixed stimulus, records these
refusals, and **fails such an unarmed or nonconvergent episode**. It does not
silently add shards, remove the bytes criterion, turn the hot load off to fake
recovery, broaden the PRE envelope, or claim an unchanged/no-move run proves
planner convergence. Mainline must resolve any irreducible workload/geometry
finding before claiming the original measurement requirement has passed.

Artifacts and identities

| Arm | Artifact | Required SHA-256 |
|---|---|---|
| PRE | `build/lbplanner-pre/tomokv` | `33f07418205817e93d5d759d4cab78480f77c5aa9fa51618dc89aa3e3828f8a2` |
| PAD-A | `build/tomokv-lbplanner-pad` | `bdda99b8c96438cfa60637279c886827cc1a6d78370a5c9a5053e73a79d634c8` |
| POST | `build/tomokv` | `571fa4ab3e81f1d231941be82f22950644e0ed437a85d50d6111e5545354e0f1` |

PAD is **kind A: PRE behaviour with the candidate's text size/layout**. These
are the original lane's verified twins, not a newly fabricated padding arm.
Hashes are checked initially and again at each boot; altered artifacts require
a new reviewed measurement request, not an automatic hash refresh. The manifest
also binds memtier, the helper, this script and its two existing Python support
modules.

Each calibration/scored run has `run.json`, raw `telemetry.jsonl`, server and
loader logs, memtier JSON and connection-owner receipts. Campaign files include
`manifest.json`, the shared seed manifest, `criteria.json`, `results.json`,
`report.json` and `rows.txt`. Exit status is nonzero unless the complete schedule
passes. Every scored arm emits one line of the requested form:

```text
LBPLANNER-EPISODE <episode> <mode> <arm> r<N> t_converge=<s> key_moves=<n> client_moves=<n> gathers=<n> suffix_moves=<n> rate=<ops/s> p99=<ms> coord_busy=<pct>
```

An invalid/unavailable quantity is `NA`, never a made-up zero. Its accompanying
JSON and status line explain the failure. No measured PRE/POST table is claimed
in this report; only mainline can produce those numbers.

Serverless verification performed: 13 synthetic tests, dry-run command rendering
(including mocked process/socket creation that must never be called), C helper
`-fsyntax-only -Wall -Wextra -Werror`, frozen SHA checks, `bash -n tests/gate.sh`,
and `git diff --check`. Negative traces cover absent stimulus/motion, reset or
missing counters, missed beats, repeated polls, late excursions, active plans,
incomplete suffixes, suffix moves, truncated/erroneous memtier output, exact
operation accounting, merged histogram quantiles and a client-move regression
hidden by an unchanged total.

This instrument adds **zero gate rows**. The merge preserves lbplanner's existing
handoff row at collection line **3050**, before the quick-tier block at **3202**
and exit at **3206**. Relative to merged origin, that existing lane row still
requires +1 quick / +1 full: **489→490 and 506→507**. `EXPECT_QUICK` and
`EXPECT_FULL` match origin exactly; this lane did not edit their values. Mainline
owns count/ledger reconciliation and the live gate.
