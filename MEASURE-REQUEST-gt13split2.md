# gt13split2: readiness-hardening gate repair

2026-10-06; worktree `/home/user/Projects/cx-gt13split`, branch `cx-gt13split`.
Scope: `32ef635af` and test-harness fallout. The lane first merged `origin/cpp`
at `649116c91` in `07b3e604d`. The sole conflict was the EXECABORT fixture's
timestamp; the lane retained its existing fixture byte for byte.

**No production-source, gate-row, EXPECT, or fixture changes. Row delta: 0 before
the quick-tier exit and 0 after it; counts stay 497 quick / 514 full.** The two
existing `gate:` commits remain intact. Nothing was pushed. This is correctness
validation, with no performance measurements or PAD arms.

## Findings and repairs

The retained artifacts contradict two proposed argv diagnoses:

- `build/gate-feature.eKdZSr/1s-0-0-0-1/server.log` says exactly
  `--flip-auto is unavailable with --thread-mode 1s`. That is the cell's intended
  refusal. Its argv did not change. Replaying its saved `argv.json`, changing only
  CPU affinity from `16-23` to `112-119`, exits 1 with that same stderr. The
  readiness extraction discarded the diagnostic and exposed only the exit status.
- `32ef635af^:tests/gate.sh::job_rlcache` already passes `--shards 64`, and the
  failed run's `gate-srv-fused.Y8sKzT` confirms **8 unified threads / 64 shards**.
  The trailing `48` is the Python churn client's worker count, not server shards.
  No migrated helper dropped a shard argument. The original churn stimulus passed
  a diagnostic rerun with four moves, so the saved zero-move failure is intermittent.

| Failing gate row | Cause | Repair |
| --- | --- | --- |
| `feature 1s-0-0-0-1` | Intended refusal lost its stderr in `wait_ready`. | Include the owned boot log's final 2,000 characters in the exit exception. |
| `feature 1s-0-0-1-1` | Same diagnostic loss. | Same repair; documented-reason check retained. |
| `feature 1s-0-1-0-1` | Same diagnostic loss. | Same repair; documented-reason check retained. |
| `feature 1s-0-1-1-1` | Same diagnostic loss. | Same repair; documented-reason check retained. |
| `feature 1s-1-0-0-1` | Same diagnostic loss. | Same repair; documented-reason check retained. |
| `feature 1s-1-0-1-1` | Same diagnostic loss. | Same repair; documented-reason check retained. |
| `feature 1s-1-1-0-1` | Same diagnostic loss. | Same repair; documented-reason check retained. |
| `feature 1s-1-1-1-1` | Same diagnostic loss. | Same repair; documented-reason check retained. |
| `read-local MGET fence symmetry unit` | Its `SimpleNamespace` wire fake has neither `_read` nor `_read_deadline`. | Public `read()` falls back to `file.read`; `_line()` treats a missing deadline as inactive. Readiness still uses its bounded transport. |
| `armed block-cache churn battery` | No argv regression. Arbitrary hot keys rotated every 0.5 s, without proving a sustained owner imbalance across the controller's three one-second decision ticks. | Select distinct shards on one observed owner and hold their demand until movement completes; then rearm from current ownership. Preserve 64 shards, 48 clients, 25 s, all retire paths, and all five assertions. Observer errors now fail explicitly. |

The churn change repairs the missing workload precondition. The evidence does
**not** establish that `32ef635af` changed shard geometry or caused the zero-move
sample; attributing that failure to dropped argv would be incorrect.

Two related test-only repairs were necessary:

- `mdbqsbr_live` already owns a bounded 25-line log tail. It removes the duplicate
  shared-helper tail while retaining the exit status and its original diagnostic.
  Its existing tests remain unchanged and pass.
- `gateplan.py` required a reviewed eight-thread ABBA geometry even for
  `GATE_ONLY_JOBS`, which never runs ABBA. Selected correctness jobs now require
  only their existing reviewed 8-thread / 6:2 correctness geometry. Complete
  measurement runs still reject unreviewed ABBA shapes. No measurement record was
  edited; the reference-binary update came from the required upstream merge.

## PRE versus POST argv audit

PRE is `32ef635af^` (`8e72d32a6`); the extraction is `32ef635af`; repaired code is
`75ec84195`. All 12 migrated helpers' construction and launch blocks are identical
across those revisions. The machine-readable audit also compares the five gate
wrappers below: **21 identical blocks**, including separately defined builders.
`tests/feature_gate.py` is byte-identical across PRE and repaired code.
Exact compared source blocks and their hashes are retained in
[`boot-argv-audit.json`](docs/gt13split2/boot-argv-audit.json).

In the following table, `B`, `C`, `P`, `D`, and `M` denote each helper's existing
binary, CPUs, port, directory, and mode; `+ARGS` preserves the existing ordered
caller-supplied arguments. Optional clauses are unchanged. These are command
templates, not new launch commands. **Every row has an empty PRE → POST argv diff.**

| Migrated helper | Identical PRE / POST command |
| --- | --- |
| `_gate_process.server` | `taskset -c C abs(B) --port P --bind 127.0.0.1 --dir D/data --save '' --appendonly no --enable-debug-command yes +ARGS` |
| `connreset_repro.boot` / `command` | `taskset -c 112-127 B --bind 127.0.0.1 --port P --thread-mode M --client-lb CLIENT_LB --key-lb KEY_LB --flip-auto 0 --enable-debug-command yes --save '' --appendonly no --dir D`; append `--shards args.shards` only when supplied. |
| `flushfix_checks.live` | `taskset -c C B --port P --shards 16 --ratio ratio('correctness',8) --thread-mode M --databases DATABASES --save '' --appendonly no --maxmemory 0 --dir D` |
| `mdbqsbr_live.boot` / `build_command` | `taskset -c C B --bind 127.0.0.1 --port P --thread-mode M --shards 16`; append `--ratio 6:2` only in `2s`, then `--databases 16 --read-local READ_LOCAL --atomic ATOMIC --enable-debug-command yes --save '' --protected-mode no`; cwd `D`. |
| `redisgap.Harness.server` / `args` | `taskset -c 68-79 B [CONFIG] --bind 127.0.0.1 --port P --shards 16 --thread-mode M --save '' --dir D --enable-debug-command yes`; append `--ratio 6:2` only in `2s`, then `+ARGS`. |
| `reorder_flip.main` | `taskset -c 112-119 B --port P --shards 16 --ratio 6:2 --atomic 0 --enable-debug-command yes --flip-auto 1`; optional `--reorder REORDER`, then optional `--overlap OVERLAP`; cwd `D`. |
| `resizefix.main` | `taskset -c 8-15 B --bind 127.0.0.1 --port P --shards 16 --dir D --atomic 1 --read-local LOCAL --overlap 0 --flip-auto 0 --enable-debug-command yes`; append `--ratio 6:2` for split, otherwise `--thread-mode fused`. |
| `servertail.boot` | `taskset -c C abs(B) [CONFIG] --port P --bind HOST --enable-debug-command yes +ARGS` |
| `shutdown_persist.boot` / `boot_argv` | `taskset -c C B --bind 127.0.0.1 --port P --dir D --shards 16 --thread-mode M --net-io NET_IO --appendonly no`; optional `--ratio args.ratio` only in `2s`, then optional `--save SAVE`. |
| `signalacct_live.attempt` | `taskset -c C B --bind 127.0.0.1 --port P --thread-mode M --shards 16 --read-local READ_LOCAL --overlap OVERLAP --reorder REORDER --databases DATABASES --net-io NET_IO --flip-auto 0 --enable-debug-command yes --save '' --protected-mode no`; append `--ratio 6:2` only in `2s`; cwd `D`. |
| `watchlive_gate.boot` | `taskset -c C B --port P --enable-debug-command yes +ARGS` |
| `wiredump.boot_pair` | Target: `taskset -c 112-115 B --port TARGET_PORT --bind HOST --shards 2 --no-pin --atomic ATOMIC`. Oracle: `taskset -c 116-119 ORACLE --port ORACLE_PORT --bind HOST --protected-mode no --save '' --appendonly no`. |

The unchanged gate wrappers are `launch`, `boot`, `boot_fused`,
`feature_split_job`, and `job_rlcache`:

- `launch`: `taskset -c C B --port P --bind 127.0.0.1 --shards 16 --dir D --save '' +ARGS`.
- `boot`: supplies `--ratio 6:2` before its caller's arguments.
- `boot_fused`: supplies `--thread-mode fused`, with no ratio.
- `feature_split_job`: supplies `--atomic AT --enable-debug-command yes` to `boot`.
- `job_rlcache`: supplies `--shards 64 --atomic 1 --read-local 1 --enable-debug-command yes`
  to `boot_fused`; the later `--shards 64` overrides `launch`'s default 16 exactly
  as in PRE. Its separate driver remains `rlcache_churn.py 127.0.0.1 P 25 48`.

## Requested proof

All gate executions use only server CPUs `112-119`, load CPUs `120-127`, no SMT,
ratio `6:2`, one slot, ports `18320-18322`. Correctness jobs and their builds run
sequentially in that slot. Each repetition creates fresh server/data directories.

```bash
export GATE_ONLY_JOBS='feature-split-1 ring_unit rlcache feature-cell-1s-0-0-0-1 feature-cell-1s-0-0-1-1 feature-cell-1s-0-1-0-1 feature-cell-1s-0-1-1-1 feature-cell-1s-1-0-0-1 feature-cell-1s-1-0-1-1 feature-cell-1s-1-1-0-1 feature-cell-1s-1-1-1-1'
taskset -c 112-127 tests/gate.sh iteration \
  --server-cores 112-119 --load-cores 120-127 \
  --server-smt '' --load-smt '' --ports 18320-18322
```

The eight failing matrix rows belong to `feature-cell-*`, not `feature-split-1`.
The selection includes both those actual failing jobs and the explicitly requested
split battery, plus their normal release/debug-build prerequisites.

All three complete selections exited 0: **49/49 rows each, 147 passes, zero
failures**. Each includes `feature-split-1` (34 rows), `ring_unit` (3), `rlcache`
(2), the eight refusal cells, and two build rows.

| Repetition | Fresh run | Result | Churn shard moves | Local reads | Peak block cache |
| --- | --- | --- | ---: | ---: | ---: |
| 1 | `build/gate-run.m6ncQC` | [49 ok / 0 FAIL](docs/gt13split2/run-1/ledger.partial) | 11 | 3,676,795 | 514,848 B |
| 2 | `build/gate-run.3dA5hn` | [49 ok / 0 FAIL](docs/gt13split2/run-2/ledger.partial) | 62 | 3,947,675 | 337,216 B |
| 3 | `build/gate-run.BW0mFA` | [49 ok / 0 FAIL](docs/gt13split2/run-3/ledger.partial) | 69 | 3,837,832 | 342,080 B |

Per failing row, the proofs are:

| Row | Run 1 | Run 2 | Run 3 |
| --- | --- | --- | --- |
| `feature 1s-0-0-0-1` | PASS: exact refusal | PASS: exact refusal | PASS: exact refusal |
| `feature 1s-0-0-1-1` | PASS: exact refusal | PASS: exact refusal | PASS: exact refusal |
| `feature 1s-0-1-0-1` | PASS: exact refusal | PASS: exact refusal | PASS: exact refusal |
| `feature 1s-0-1-1-1` | PASS: exact refusal | PASS: exact refusal | PASS: exact refusal |
| `feature 1s-1-0-0-1` | PASS: exact refusal | PASS: exact refusal | PASS: exact refusal |
| `feature 1s-1-0-1-1` | PASS: exact refusal | PASS: exact refusal | PASS: exact refusal |
| `feature 1s-1-1-0-1` | PASS: exact refusal | PASS: exact refusal | PASS: exact refusal |
| `feature 1s-1-1-1-1` | PASS: exact refusal | PASS: exact refusal | PASS: exact refusal |
| `read-local MGET fence symmetry unit` | PASS: p8/p32 held-window hits + RYOW | PASS: p8/p32 held-window hits + RYOW | PASS: p8/p32 held-window hits + RYOW |
| `armed block-cache churn battery` | PASS: 11 moves, all 5 checks | PASS: 62 moves, all 5 checks | PASS: 69 moves, all 5 checks |

The durable `run-1`, `run-2`, and `run-3` directories retain each ledger, CPU plan,
gate output, MGET fence output, churn output/server log, and all eight cells'
argv, exact stderr, verdict, and exit status. Archived text logs trim only trailing
display whitespace; raw logs remain in the listed build directories. See
[`proof-summary.json`](docs/gt13split2/proof-summary.json) and
[`manifest.json`](docs/gt13split2/manifest.json) for paths and binary/source hashes.
The gate sequence began at `f9dfa3a03`; `75ec84195` changes only planner self-test
isolation. The planner's runtime functions and all exercised battery code are
unchanged between those revisions. The planner self-tests also pass with
`GATE_ONLY_JOBS` set. No listeners remain on the three allocated ports.

Serverless validation:

- Readiness and migrated harnesses plus churn controls: **57 tests passed**
  (`loading_ready_test`, `gate_process_test`, `signalacct_live_test`,
  `connreset_harness_test`, `mdbqsbr_live_test`, `rlcache_churn_test`).
- Planner and measurement-schema self-tests: **24 + 11 passed**.
- The MGET fence positive trace passes; `mget-fence-old`, `mget-fence-unarmed`, and
  `mget-fence-stale` each exit 1. The wire-fake repair does not weaken their verdicts.
- Churn's serverless control drives the actual battery to exit 1 with zero moves,
  despite successful workers, live server, reads, and cache activity. A movement
  control exits 0 and rearms only after the move counter advances.
- Wrong boot diagnostics remain failures; readiness's deadline, exact LOADING,
  PID identity, malformed reply, and resource-error controls remain green.
- Shell syntax and `git diff --check` pass.

Serverless logs are retained in [`docs/gt13split2`](docs/gt13split2/). The manual
refusal replay and the retained landing churn failure are included alongside the
positive and negative controls. Test changes were committed as `c2a3972db`,
`586822cef`, `379ef22bf`, `f9dfa3a03`, and `75ec84195` after the upstream merge.

These are partial correctness runs, not a complete 514-row gate receipt. The
maintainer still owns the complete landing gate; no performance claim is made.
