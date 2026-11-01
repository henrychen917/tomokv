# Breadth-survey instruments — maintainer measurement request

## surveytools

Harness-only lane on `cx-surveytools`, based on `origin/cpp` commit `e32b04a44`.
No production code, Makefile, gate rows, or EXPECT constants changed. No push.
**DQ = 0, DF = 0.** PRE/POST/PAD production arms do not apply to this lane.

The five entry points are `calib/survey-cmds.py`, `survey-latency.py`,
`survey-memory.py`, `survey-persist.py`, and `survey-scale.py`, with shared
`calib/survey.py` and the independent `calib/survey-client.cc` load driver.

Use [calib/survey-plan.md](calib/survey-plan.md) for the exact full-survey and
4–6-hour first-pass commands, client choice per command, workload definitions,
estimated durations, output schemas and disk budgeting. Maintainer geometry:
server cores **0–31**, load cores **32–111**, port **20400**. All actual lane
execution used `taskset -c 48-63`; smoke servers used 48–55 and load used 56–63.

The command matrix contains 43 command/shape combinations × p1/p32, four TomoKV
variants (1s/2s, read-local 0/1), and Redis io-threads 1/4. Every pair uses fresh
boots in ABBA order with identical deterministic preloads, connections and client
settings. Native and memtier HDR completions reconcile exactly with INFO command
counters. JSON retains per-visit latency distributions and per-block ratios.
Ratios with >2% arm spread or a busy generator are explicitly uninterpretable.

Latency fixes the offered rate at 25%, 50% and 75% of a short Redis4 capacity
calibration. Every scheduled/sent/completed observation is retained losslessly;
missed deadlines, missing observations and partial drains fail validity. Memory
uses the specified 1M/10M populations in real runs and reports both absolute and
empty-boot-subtracted memory/RSS, with N/2 as the post-DEL denominator.
Persistence retains BGSAVE activity evidence and computes loss against off.
Scaling includes the requested 50/500/5000/10000 connections and all four sizes.

Workload definitions matter when interpreting the survey: existing-member
SADD/ZADD/GEOADD/PFADD are no-change operations, APPEND/LPUSH grow during each
window, and list/stream reset or refill commands are explicitly counted as
auxiliary work. Native pipeline counts cycles for compound workloads. These
qualifications and exact commands are in the plan; no insertion-capacity or
steady-state stream claim should be inferred from those controlled shapes.

## Verification completed

Redis binary `/home/user/Projects/redis74/src/redis-server` reports **7.4.10**,
SHA `f103d127`, jemalloc 5.3.0. Binary digests, final harness digests, smoke
configurations and summaries are in
[calib/survey-smoke-proof.json](calib/survey-smoke-proof.json). This receipt
contains no measured performance rates.

| Check | Result |
| --- | --- |
| `python3 tests/gates_test.py` | PASS, 76 tests |
| All five tools' `--selftest` | PASS, including mocked replies and poisoned validity evidence |
| `build/survey-client --selftest` | PASS, serverless RESP/validator/histogram checks |
| Command `--smoke` | VALID, 32/32 visits, both servers; all families timed, entire command catalogue sampled by sidecar |
| Latency `--smoke` | VALID, 60/60 visits; all five workloads and three fractions |
| Memory `--smoke` | VALID, 64/64 visits; eight shapes at two tiny populations |
| Persistence `--smoke` | VALID, 32/32 visits; both workloads and all four modes |
| Scale `--smoke` | VALID, 64/64 visits; four tiny connection points and all four actual value sizes |
| Additional geometry `--smoke` | VALID, 32/32 GET visits; all four TomoKV variants × Redis io-threads 1/4 |
| Python compilation / `git diff --check` | PASS |
| `make -q` | Exit 0 after baseline build and after harness work |

The checkout initially had no `build/`, so its initial `make -q` was stale. A
local production baseline was built on the allowed CPUs. Harness changes leave
that build fresh. Build artifacts are approximately 0.9 GiB. No preload image is
stored on disk; each owned persistence data directory is removed on exit.
Smoke output was deleted after preserving the receipt and behaviour flags.

There were **three raw SINTER reply differences** in the command smoke: the
same ten members arrived in a different permitted order. Both RESP byte strings
are preserved in the proof receipt. No behaviour change was made. The other
final smoke sidecars reported no differences in their samples.

## Remaining maintainer work

**Real measurements: NOT RUN**, as requested; the maintainer schedules the
quiet box. **`tests/gate.sh iteration`: NOT RUN**, reserved for the maintainer.
All quoted smoke outcomes are functional validity results, not performance
evidence. Run the reduced pass first, review behaviour flags, generator limits
and unstable blocks, then expand the interesting cells using the full commands.

The deciding quantities are per-cell TomoKV/Redis throughput ratios, tails at
the identical offered rate, bytes per live key and post-delete RSS retention,
persistence loss against off, and the connection/value-size curves. Preserve
every failed/unstable visit; do not select the best rerun or promote a smoke rate
to a paper result.
