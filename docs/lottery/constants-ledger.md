# Lottery runner constants

| ID | Location | Value | Basis | Owner adjustment |
|---|---|---:|---|---|
| LOTTERY-K | `tests/lottery_runner.py:DEFAULT_HITS` | 20 | Owner-requested minimum number of fresh, witnessed attempts per row | `--hits K`; update this row when changing the default |
| LOTTERY-CONFIDENCE | `upper_bound` | 0.95 | Requested one-sided exact binomial confidence level | A reporting convention, not a failure tolerance |
| LOTTERY-CAP | `tests/lottery_runner.py --cap` | 600 s | Per-row campaign budget: no new attempt starts after it. Matches the calibration's "K within 10 minutes" question | `--cap S`; a cap never grants a pass |
| LOTTERY-ATTEMPT-TIMEOUT | `tests/lottery_runner.py --attempt-timeout` | 1800 s | Hard bound on one attempt (boots, battery, teardown); an expired attempt is incomplete, never a hit | `--attempt-timeout S` |
| LOTTERY-MAX-EVENTS | `tests/lottery_hooks.h:max_events` | 4,000,000 | Bounded trace storage per armed interval; overflow makes the attempt an evidence ERROR, never a miss or a hit | Edit the header; the witness build rebuilds every object |
| LOTTERY-CALIBRATION-BUDGET | `tests/lottery_calibration.py --budget` | 600 s | "Reaches K within 10 minutes" in the calibration table | `--budget S` |
| LOTTERY-CPUS | `tests/lottery_runner.py` | 112-119 server, 120-127 clients | This box's lane allocation (cores 0-111 are the benchmark box) | `--server-cpus/--client-cpus`, still inside 112-127 |
| LOTTERY-PORTS | `tests/lottery_runner.py --port` | 25300 (+1, +2) | Lane port range 25300-25399 | `--port P` with P+2 <= 25399 |

At K=20 and zero failures the upper bound is **13.91%** (rule of three: 3/K = 15%),
not 5% or proof of determinism. At K=100 it is 2.95%; at K=300 it is 0.994%.
The model assumes independent attempts with a stable per-hit failure
probability. Fresh processes and random server hash seeds reduce shared state;
they do not prove independence. No simultaneous confidence claim is made over
the 58 rows. A cap or timeout is a resource limit and never grants a pass.
