# Multi-database ABBA producer-accounting instrument

Lane: `/home/user/Projects/cx-mdbcells`, branch `cx-mdbcells`.
Base: `dbd01dd99`; fetched and merged `origin/cpp` before editing (already current).
Scope: harness and cell definitions only. No production code or binary changes.
**Live smoke proof remains outstanding: both quiet preflights refused before any server boot.**
Gate rows **+0 quick / +0 full**; `tests/gate.sh` and both EXPECT constants are untouched.

## Why these cells

The storesize landing `08a68fcba` added mutation accounting in the multi-database
image. The generic 14-cell suite boots db0-only. The storesize3 report explicitly
says the exact owner-private multi-DB counters require mutation hooks, and asks
for nonzero-database producer measurements separately from monitoring interference.
Storesize5 inherits the 40M-key / 1 Hz bare-INFO study. This instrument exposes
that workload; it does not establish a storesize performance verdict.

## Grammar and driver

The existing 11-field legacy and 15-field extended rows remain accepted. Append
optional pipe-separated fields after the original 15, in any order:

```text
... | atomic=1 | score=rate | mix=- | smoke=0 | srv=--databases 16 | dbs=16
```

| Field | Meaning |
| --- | --- |
| `srv=FLAGS` | Parse shell-style quoting into argv, without a shell or expansion; append identical arguments to **both** arms. Default empty. Harness-owned boot/geometry/workload flags cannot be overridden. |
| `dbs=N` | Assign logical connection `i` to database `i % N`. `0` preserves the existing db0 workload; `-1` derives N from explicit `srv=--databases N`. An explicit sufficient server database count is required. |
| `keys=N` | Total resident keys across all selected databases. `0` preserves the existing 2,000,000 total keys. |
| `poll=info1hz` | One additional persistent connection issues bare `INFO` at 1 Hz from generator launch through generator drain. `poll=0`/omission starts no poller. |

Unknown, duplicate, malformed, conflicting or unsupported options fail before
boot. Database count, key count, server flags and polling enter calibration shape
identity, so a db0/no-poller calibration cannot silently carry over.

Installed memtier 2.5.1 provides `--select-db=DB`, which selects one database for
every connection in that process. The harness therefore subdivides the existing
N CPU groups into `max(N, dbs)` fixed-DB memtier processes. The recorded logical
connection start/stride partitions exactly `range(conns)`; every logical index
selects its residue modulo N databases. No SELECT commands enter the timed
workload rotation, and no proxy or new load generator is used.

At the generic geometry (server 0–31, load 32–111, SMT reserved), N=8 gives
16 memtier processes, each four workers × eight clients: **512 total connections,
32 per DB, 64 total workers**. Each CPU group is subdivided without overlap.
The requested small smoke geometry has only eight load CPUs, so each CPU hosts
two one-worker processes. That minimum 16-worker arrangement is recorded and
validated explicitly; it is not evidence of generator headroom.

The default population is **2M total keys**, not 2M per database: db0–db15 each
hold 125,000 keys of 64 bytes. Sixteen unscored, one-client sequential memtier
population processes cover every key, including uneven key-count partitions.
Timed generators use the matching per-DB key maximum. `CONFIG GET databases`,
`SELECT`/`DBSIZE` before and after load, endpoint value lengths, every generator
argv and connection assignments are retained in `measurement.json`. Missing or
incorrect databases/SELECT assignments fail evidence validation.

## Cell files

`docs/lbplanner/multidb-cells.txt` has exactly eight cells. All retain the generic
atomic/overlap/reorder/scoring/mix/smoke fields, 512 connections and N=8.

| Cell | Mode | Read-local | Workload | Pipeline |
| --- | --- | --- | --- | --- |
| h05m | 1s | 0 | GET | 32 |
| h06m | 1s | 0 | SET | 32 |
| p8gm | 1s | 0 | GET | 8 |
| p8sm | 1s | 0 | SET | 8 |
| d32gm_l1 | 2s | 1 | GET | 32 |
| d32sm_l1 | 2s | 1 | SET | 32 |
| x9m_32_l0 | 1s | 0 | GET:SET 9:1 | 32 |
| m8gm_l0 | 1s | 0 | MGET, eight generated keys | 8 |

The d32 cells intentionally use **2s**, as requested; their generic namesakes
use 1s. Split ratio and shard count still come from the existing instrument.
N=8 is a retained offered-load configuration, not a new multi-DB saturation
calibration. Failed occupancy, spread, accounting or control checks remain red.

`docs/lbplanner/multidb-info-cells.txt` separately contains h06m and h06m_info
at 2M keys, plus h06m_40m and h06m_40m_info at **40M total keys** (2.5M per DB).
The eight-cell inventory is not expanded by these optional interference cells.
This is the requested SET analogue; storesize3's original INFO example uses GET.

The poller retains send/finish times, latency, reply bytes and completed counts.
Missed full periods, bad INFO replies, missing central-window polls or incomplete
coverage invalidate the observation. Its lock brackets both central stats
endpoints, so precisely the intervening completed INFO commands are subtracted
from workload throughput (and from any attached profile's command denominator).
The extra control connection is included in the connection witness. Ordinary
sectioned harness INFO snapshots still occur in both no-poller and poller cells;
only the latter adds periodic **bare** INFO and its keyspace census.

## Verification

- `python3 tests/abbagate.py --self-test`: exit 0, **141 checks passed**
  (106 harness + 10 saturation + 9 calibration + 16 binary-lifecycle checks).
  Receipt: [self-test.log](docs/mdbcells/self-test.log).
- `--list-cells` succeeds for the original generic file (14), new multi-DB file
  (8), and optional INFO file (4). The original generic JSON is byte-identical:
  `cmp` exits 0; both SHA-256 digests are
  `b1d9d706a0f404caf02bf17fd26dc9b8b45d6749333271d3cb4bc83e0f0721f7`.
  Receipts: [before](docs/mdbcells/generic-before.json),
  [after](docs/mdbcells/generic-after.json),
  [multi-DB](docs/mdbcells/multidb-list.json),
  [INFO](docs/mdbcells/multidb-info-list.json).
- Serverless negative checks reject a missing populated database, absent/wrong
  SELECT assignment, wrong configured database count (including 32 instead of
  requested 16), malformed options, missed INFO periods, bad replies, fabricated
  polling endpoints and INFO commands leaking into the throughput denominator.
- Both arms' actual boot-command construction is exercised with intercepted
  children. This verifies argv construction, **not a live server boot**.
- `git diff --check` passes. No gate row, EXPECT constant or production file changed.

### Requested live smoke: blocked, not passed

The specified CPUs and binaries were used in the invocation below. An initial
attempt stopped before preflight because the ledger has no eight-thread ABBA
split ratio. The harness now permits a purely fused selection without an unused
ratio, while still rejecting an unreviewed split geometry; a serverless negative
check covers both cases. No ledger ratio was invented or changed.

Two subsequent normal smoke attempts refused at the unchanged quiet preflight:

| Attempt (UTC 2026-10-07) | Observed CPU-seconds | Budget | Result |
| --- | ---: | ---: | --- |
| 02:09:19, `smoke-run` | 0.66 | 0.48 | rejected before boot |
| final attempt, `smoke-final` | 0.81 | 0.48 | rejected before boot |

The failed preflights remain in [smoke-preflight-failures.json](docs/mdbcells/smoke-preflight-failures.json),
with exact full reports archived alongside as gzip and selected-core samples
retained as JSONL. No server, memtier load, ABBA arm or gate started. No quiet
threshold was relaxed; no failed measured block was hidden or rerun.
**There are no observed per-DB counts and no PRE/POST rates.** Expected counts
are 125,000 in each of db0–db15, but these are workload specifications, not smoke
observations. Completing the four-arm boot/SELECT/DBSIZE proof is the remaining
mainline action once CPUs 112–127 pass the quiet screen.

The requested binary files were hashed, and their digests match MANIFEST.md:

| Arm | Binary commit | SHA-256 |
| --- | --- | --- |
| A / PRE | ca4eeb371 | f1cc55ade379a38accaa6fc76f4773a277d5f544833e3baeb58e7a2a2aa81a86 |
| B / POST | 08a68fcba | bdf7cf66f258a1c923f38fd54610eb8b405670d298ffe531c5cb84c320a54865 |

Exact pending smoke command (one h06m ABBA block, no reference build):

```sh
python3 tests/abbagate.py --subset full --build-reference 0 \
  --reference-binary /home/user/Projects/bench-bins/tomokv-headline-ca4eeb371 \
  --candidate-binary /home/user/Projects/bench-bins/tomokv-headline-08a68fcba \
  --cells docs/lbplanner/multidb-cells.txt --only h06m \
  --server-cores 112-119 --server-smt '' --load-cores 120-127 --load-smt '' \
  --port 8876 --output build/mdbcells-mainline-smoke
```

Require four complete `measurement.json` files in A/B/B/A order, exact
`configured_databases=16`, argv containing `--databases 16`, and
`database_counts_after` with **all sixteen entries equal to 125000**. Each
load argv must retain its `--select-db=0` through `--select-db=15`, with 32
connections apiece. Saturation/spread failures or absence of a matching null
must not turn this boot proof into a performance claim; `--only` is diagnostic.

The INFO poller has serverless cadence/accounting checks but was not live-tested
by this lane. The 40M interference rows and the full eight-cell comparison were
not run.

## Mainline commands (not executed by this lane)

Run from the merged worktree, one campaign at a time on the scheduled quiet box.
Use unique output directories. These are the same physical CPU axes as the
generic request: server **0–31**, load **32–111**, no SMT; 512 connections,
64-byte values, default balancers, atomic=1, overlap=1, reorder=0. Normal central
windows remain 20s, with 3s warmup and 5s tail.

First collect a contemporaneous identical-binary control for the exact new file:

```sh
python3 tests/abbagate.py --subset full --build-reference 0 \
  --collect-null 1 \
  --candidate-binary /home/user/Projects/bench-bins/tomokv-headline-ca4eeb371 \
  --cells docs/lbplanner/multidb-cells.txt \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --port 8876 --output build/mdbcells-mainline-null
```

`--collect-null` intentionally exits 3. Require `null_control.verdict=PASS` in
its results; an old generic/db0 null or a failed new null cannot certify this
workload. Then run the full eight-cell PRE/POST ABBA:

```sh
python3 tests/abbagate.py --subset full --build-reference 0 \
  --reference-binary /home/user/Projects/bench-bins/tomokv-headline-ca4eeb371 \
  --candidate-binary /home/user/Projects/bench-bins/tomokv-headline-08a68fcba \
  --cells docs/lbplanner/multidb-cells.txt \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --null-result build/mdbcells-mainline-null/results.json \
  --port 8876 --output build/mdbcells-mainline-storesize
```

For the 40M-key INFO pair, the exact diagnostic command is:

```sh
python3 tests/abbagate.py --subset full --build-reference 0 \
  --reference-binary /home/user/Projects/bench-bins/tomokv-headline-ca4eeb371 \
  --candidate-binary /home/user/Projects/bench-bins/tomokv-headline-08a68fcba \
  --cells docs/lbplanner/multidb-info-cells.txt \
  --only h06m_40m,h06m_40m_info \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --port 8876 --output build/mdbcells-mainline-info40m
```

Use `--only h06m,h06m_info` and another output directory for the 2M pair. These
`--only` comparisons are diagnostics, never full-tier passes. For a trusted
interference comparison, collect a separate same-binary null for the full INFO
cell file and supply its results with `--null-result`; retain all failed cells.
Re-establish occupancy at 40M and keep the selected load geometry matched across
arms and the polling pair. Compare the INFO penalty to each binary's own
no-poller baseline. Rate at matched load decides; obtain aligned cycles/op,
instructions/op and IPC with mainline's profiling instrument to explain it.
The ordinary ABBA CLI does not itself produce those PMU metrics, and this
patch does not claim otherwise. There is no production text/layout change and
no PAD arm in this request.
