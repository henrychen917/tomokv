# Reply and behaviour audit

The raw searches are `reply-behavior-users-*.txt`. The gate owns all runtime
tests; the candidate adapter only supplies a missing mode/engine, or overrides
an explicit engine in the separately identified epoll run. It execs the recorded
release ELF without replacing any test driver or assertion.

| Source/test surface | Gate jobs exercised |
| --- | --- |
| Writeback progress and negative controls | `wb_rule_units`, `wbland_units`, `wb_policy`, `netcmd_units`, `iofix-deferred` |
| hz config/cron, config syntax, client shares | `config_unit`, `boot_grammar`, `netcmd_units`, `iofix-hz` |
| Idle wait extraction/mutation and R7 generation | `splitlocal_units`, `reorder_sync`, `reorder_engagement`, `reorder_identity` |
| `tests/debug.py`, including global sleep and exact Redis replies | `auth`, `iofix-sleep` |
| `tests/slowlog.py` uses SLEEP to produce a slow command | `debug-0`, `debug-1` |
| `tests/at15.py`, `at15_unit.cc`, EXEC SLEEP 0/positive | `atomic_units`, standard differential jobs |
| `tests/differ.py` uses EXEC SLEEP 0 | all five standard differential jobs, both engines |
| `tests/pubsub.py` mentions SLEEP only in a comment explaining why it cannot expose the desired race | `notify`; comment corrected, executable assertions unchanged |
| `tests/lottery_calibration.py` names an aspirational SLEEP latch | no server call or assertion to change; metadata only |
| Signal/save/failed-save retry and existing shutdown semantics | `iofix-signal`, `climonfix`, `persistfix_units`, `snapshot-uring`, `snapshot-epoll`, `aof-uring`, `aof-epoll` |
| Worker role changes / FLIP shutdown and saturation | `flip_unit`, `flipfix_units`, `flip`, `flipctl`, `flip_saturated` |

Fused FLIP is deliberately unsupported. The FLIP batteries exercise split mode
and both engines; the fused sleep batteries additionally exercise read-local
and R7. Snapshot jobs normally select split mode; the extra adapter run supplies
fused mode while retaining their explicit engine choices. The AOF and shutdown
jobs already enumerate both thread modes.

The PRE gate tree contains archived PRE source and its own production units.
Current new batteries and the changed positive writeback assertion are overlaid.
The PRE `netcmd_unit.cc` call signature and splitlocal extractor are retained
because POST's new hz parameter and named wait deadline do not exist on PRE.
The writeback negative mutation targets PRE's old unconditional work expression.
These interface adaptations are recorded in `pre-harness.txt`; they do not
weaken the positive progress/park assertions or replace PRE server code.
