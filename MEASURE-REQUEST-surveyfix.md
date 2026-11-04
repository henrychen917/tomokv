# Breadth survey harness repair

## surveyfix

Harness-only lane `cx-surveyfix`, based on `105c5818cc`. `cx-surveytools` and
its `ad96fce786` ESRCH fix were already ancestors; no merge was necessary.
No production sources, Makefile, gate rows or EXPECT constants change. No push.
**DQ = 0, DF = 0.** Production PRE/POST/PAD arms do not apply.

The native client now schedules due cycles independently of previous replies.
Workers own contiguous connection-ID intervals, preserving every original global
deadline and per-connection key sequence, including uneven connection counts.
It uses high-resolution readiness waits instead of continuous zero-timeout
polling, sends immediately, and subscribes to EPOLLOUT only on backpressure.
Long reply batches service due sends every 32 completions. Timestamps immediately before the first successful send call for each command
include prior socket backpressure in lag; no deadline or observation is dropped.

Prepared key offsets, lazy error diagnostics and dense counters remove work
from the paced path. Dense counters preserve the previous HDR-equivalent bucket
boundaries and exact maxima. Every fixed-load observation is preallocated and
pre-touched before readiness, then written and checked after timed drain; failed
workers also retain their completed prefix. Temporary client RAM is 32 bytes
per scheduled primary operation. The 20 ms deadline, 2% capacity plateau,
95% calibration CPU boundary, exact INFO accounting, raw counts and full-drain
checks remain intact.

The Python audit covers every survey subprocess and `/proc` access. Optional
memtier CPU samples tolerate ENOENT/ESRCH both while enumerating tasks and while
reading a task's stat file; missing worker coverage still fails. Required RSS
fails explicitly if the server disappears. Owned-child signalling tolerates
exit races and always reaps with bounded waits. Version commands and the
BGSAVE callback have timeouts. Snapshot/AOF rename races remain transient;
other disk-watch errors invalidate the run. Post-exit native artifact reads
remain required evidence, not optional samples.

An INVALID summary now includes the cell, arm and escaped reason on one line,
including calibration and sidecar failures. A lag failure reports the actual
maximum and unchanged limit. Calibration failures report the planned visit
count even when no timed visits started.

## Verification

The successful survey campaigns used server CPUs **48–51**, with load/orchestration
work on **52–63**, port **20200**, under `taskset -c 48-63`. TomoKV used
`--ratio 3:1 --shards 256`; the supplied frozen binary is actually named
`/home/user/Projects/bench-bins/tomokv-headline-105c5818cc`. Redis was 7.4.10.
The short runs used one block, two-second windows, 512 connections, 1,024 keys,
three-second calibration windows at 256/512/1,024 connections, and the full
25%/50%/75% offered fractions. **No `--smoke` rate reduction was used.** Earlier
rejected allocation trials used server 48–55/load 56–63, also inside the lane.

| Check | Result |
| --- | --- |
| Native client and all six Python `--selftest` entry points | PASS |
| GET latency, Redis4 against 1s-rl0 and 2s-rl0 | **VALID 24/24** |
| LPUSH/RPOP latency, same fractions and arms | **VALID 24/24** |
| Eight string command cells at p1, both TomoKV modes against Redis4 | **VALID 64/64** |
| Every successful timed visit | Exact INFO reconciliation; latency campaigns retain and count every raw observation |
| Sidecars for the three successful campaigns | **0 raw reply differences** |
| `python3 tests/gates_test.py`, isolated on CPUs 48–63 | **PASS, 83 tests** |
| `make -q` after baseline build | **Exit 0** |
| Production sources, Makefile, gate.sh and EXPECT constants | Unchanged; quick 1046 / full 1063 |

Worst observed **generator send lag**, milliseconds (not server performance):

| Workload / fraction | Redis4 | 1s-rl0 | 2s-rl0 |
| --- | ---: | ---: | ---: |
| GET / 25% | 1.132 | 0.312 | 0.531 |
| GET / 50% | 0.352 | 0.412 | 0.334 |
| GET / 75% | 0.589 | 0.359 | 5.496 |
| LPUSH/RPOP / 25% | 1.752 | 0.233 | 0.342 |
| LPUSH/RPOP / 50% | 0.345 | 0.347 | 0.313 |
| LPUSH/RPOP / 75% | 0.356 | 0.409 | 0.363 |

The maximum was **5.50 ms**, against the unchanged 20 ms rejection limit.
The LPUSH/RPOP run also checks two primary observations per scheduled cycle.

Validity history, **not a performance A/B**; allocations and calibrations differ:

| Evidence | Server / load CPUs | Window | Outcome |
| --- | --- | --- | --- |
| PRE, maintainer's 2026-11-01 GET first run | 0–31 / 32–111 | 5 s | INVALID at 25%; roughly 5.4 s send lag |
| Final POST GET proof | 48–51 / 52–63 | 2 s | VALID at all fractions and arms; max 5.50 ms |
| Final POST coupled-cycle proof | 48–51 / 52–63 | 2 s | VALID at all fractions and arms; max 1.76 ms |

`calib/surveyfix-proof.json` contains exact arguments, binary and harness hashes,
per-visit verdicts/lag maxima, accounting and observation checks, sidecar flags,
self-test outputs, and **every rejected development campaign**. No rates or
ratios are quoted. The initial harness-suite attempt used eight CPUs alongside
compilation and hit its existing 45-second one-slot scheduler timeout; the
isolated full-allocation run passed without editing that test or its deadline.

The broader SET/HGET/LPUSH_RPOP/ZADD attempt **remained INVALID** at
`calibration/HGET/plateau`, arm `redis-4`, before timed cells. Other calibration
and generator-limited development failures are retained in the receipt. An
unrelated unrestricted test job and a 24% calibration-rung swing were observed
during development; there is no claim that every failure had the same cause.
The final proof does **not** establish a valid full five-workload calibration
at the maintainer's 32/80 geometry. Keep the 2% plateau check and inspect any
rejection there; no failed calibration was relabelled VALID.

The checkout initially lacked `build/` (`make -q` returned 1). A baseline was
built on the authorized CPUs; harness work leaves it fresh. Smoke/diagnostic
outputs are deleted after recording this receipt. Build artifacts remain under
1 GiB. The full gate and real paper measurements were not run.

The exact remaining maintainer commands and duration estimate are in
[calib/survey-plan.md](calib/survey-plan.md). Run commands and latency only;
memory, persistence and scale already completed VALID. Estimated remaining
first pass: 3.4–4.2 hours for commands, 20–35 minutes for latency. Mainline
32-server/80-load geometry and paper measurements remain with the maintainer.
