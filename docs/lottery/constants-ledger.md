# Lottery runner constants

| ID | Location | Value | Basis | Owner adjustment |
|---|---|---:|---|---|
| LOTTERY-K | `tests/lottery_runner.py:DEFAULT_HITS` | 20 | Owner-requested minimum number of fresh, witnessed attempts per row | `--hits K`; update this row when changing the default |
| LOTTERY-CONFIDENCE | `upper_bound` | 0.95 | Requested one-sided exact binomial confidence level | A reporting convention, not a failure tolerance |

At K=20 and zero failures the upper bound is **13.91%**, not 5% or proof of
determinism. At K=100 it is 2.95%; at K=300 it is 0.994%. The model assumes
independent attempts with a stable per-hit failure probability. Fresh processes
and random server hash seeds reduce shared state; they do not prove independence.
No simultaneous confidence claim is made over the 58 rows. The default 600-second
wall cap is a resource limit, includes boot and teardown, and never grants a pass.
