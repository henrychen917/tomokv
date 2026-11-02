## rlfix5

PRE is `ea48a6b272` (wave 14); branch `cx-rlfix5`. CPUs 24–31 only,
ports 21500–21599, `LC_ALL=C`. No performance measurements or push.

The PRE gate jobs `rlfix5-monotonic`, `rlfix5-yes-no`, and `rlfix5-no-yes`
fail in both modes (six failing rows). Production-linked schedules fail in
both namespaces: STRLEN 9 then GET old; SET OK then GET old across yes→no;
GET new-value before the younger SET across no→yes. Live T10 also fails.
Raw evidence: `docs/rlfix5/pre-gate/`.

RL5.7 adds six rows at the `collect_job rlfix5-*` lines, before the quick
exit: **DQ +6 / DF +6**. Maintainer totals should become **1052 / 1069**
from PRE's 1046 / 1063. Neither EXPECT constant is edited.

The gate's explicit `--shared-correctness-cpus` option permits this eight-CPU
allocation only with selected jobs and `GATE_PROOF_NO_RATES=1`. The server
retains eight threads, 16 shards and ratio 6:2. Full/performance execution
cannot use the option. Timing verdicts remain unavailable on shared CPUs.

POST/PAD, counts, complete validation, and measurement instructions follow
after the fixes and proof complete.
