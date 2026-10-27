# Final script scopes

16 PRE/POST pairs, both physical namespaces, both thread modes and atomic 0/1.
EVAL-ADMIT counts preparation; EVAL follows every dispatched wave through Final
and retirement. Fixture callbacks are followed but not counted, so the Final
release is now included. The old at412 report excluded those callbacks and its
activation totals did not cover the full script. Clocks are stubbed; Lua/library
callees outside named production routines are excluded. These are not rates.

The added FIFO routines execute 14 admission-check instructions, 27 admit
instructions and 14 Final-release instructions. Constant-kind specialization
and removal of script reload scaffolding offset them: whole preparation is
298–312 instructions below PRE; full activation is 76–88 below PRE. The
full-activation minus admission delta is +224 normal / +222 db0, including
the S1 Final close, FIFO release and other script-path changes.

| Namespace | Scope | Mode | Atomic | PRE | POST | Delta |
|---|---|---|---:|---:|---:|---:|
| normal | EVAL | 1s | 0 | 38,023 | 37,944 | -79 |
| normal | EVAL | 1s | 1 | 38,030 | 37,942 | -88 |
| normal | EVAL | 2s | 0 | 38,053 | 37,974 | -79 |
| normal | EVAL | 2s | 1 | 38,060 | 37,972 | -88 |
| normal | EVAL-ADMIT | 1s | 0 | 7,980 | 7,677 | -303 |
| normal | EVAL-ADMIT | 1s | 1 | 7,987 | 7,675 | -312 |
| normal | EVAL-ADMIT | 2s | 0 | 7,980 | 7,677 | -303 |
| normal | EVAL-ADMIT | 2s | 1 | 7,987 | 7,675 | -312 |
| db0 | EVAL | 1s | 0 | 35,422 | 35,346 | -76 |
| db0 | EVAL | 1s | 1 | 35,429 | 35,344 | -85 |
| db0 | EVAL | 2s | 0 | 35,452 | 35,376 | -76 |
| db0 | EVAL | 2s | 1 | 35,459 | 35,374 | -85 |
| db0 | EVAL-ADMIT | 1s | 0 | 7,984 | 7,686 | -298 |
| db0 | EVAL-ADMIT | 1s | 1 | 7,991 | 7,684 | -307 |
| db0 | EVAL-ADMIT | 2s | 0 | 7,984 | 7,686 | -298 |
| db0 | EVAL-ADMIT | 2s | 1 | 7,991 | 7,684 | -307 |
