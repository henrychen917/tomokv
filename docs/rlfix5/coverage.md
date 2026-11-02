The job lists in this directory are inputs to `tools/rlfix5_validate.py`, which
invokes `tests/gate.sh full` with `GATE_ONLY_JOBS`. This is selected correctness
work, not a full gate or iteration. All child processes inherit CPUs 24–31 and
`LC_ALL=C`; each run owns ports 21500–21599. The gate retains its eight-thread,
16-shard, 6:2 split geometry. Jobs with their own documented geometry retain it.

| Requested family | Selected jobs and contained batteries |
|---|---|
| read-local / readlocal / rlfix | `ring_unit`, `filter_unit`, `storage_units`, `atomic_units`, `core_units`, `splitlocal_units`, `rob_portable`, `bplus` (lane admission, MGET fences, RL4 miss/delete in both modes), `bugs5` (LFU all legs), `rlcache`, `rlfix3_info`, `rlfix3_zc`, `rlfix5-*`, armed feature and feature-matrix cells |
| RYOW / monotonic | `release_batteries`, `atomic_batteries`, `asan_batteries`, `debug-0/1` (session_monotonic), `atomic_floor` (program-order correctness only), `fused-0/1`, the new RL5 schedules |
| latency / INFO | `latencyfix_grammar`, `latencyfix_shape`, `latencyfix_off`, `wave8b_off`, `infofix_latency`, all three `infofix_compat-*`, `rlfix3_info`, `serverfix_scalar`, `serverfix_config`, `serverfix_slowlog`, `netfix_query_stats`, `persistfix2_lastsave`, `blockfix2` (blocking-key INFO), feature batteries' `infofix`, debug batteries' `slowlog` |
| tracking | `tracking_redirect`, `trackorder`, `trackfix_accounting`, `trackfix_order`, `pubtrackfix`, `notifycompat`, `notify_order`, `clientcompat-multi-tracking`, `clientcompat-enable-race`, `rootcompat`, `clientfix` (tracking-cap/pipeline), feature batteries' `tracking` |
| WATCH / MULTI | `atomfix5_watch`, `atomfix5_accounting`, `climonfix`, `racefix_climon`, `racefix_counters`, `datafix2_watch`, `exbatch_units`, `exbatch_live`, `atomic_units` (EXECABORT), `core_units`, all `multifix-*`, `climonfix4-*`, `multidb-*`, `clientcompat-multi-controls`, `txn_group_*`, `txnorder*`, `blockfix2` (MULTI/XREADGROUP), both snapshot jobs (MULTI/EXEC cuts in both modes), feature and debug batteries |
| FLIP / LB | `flip_unit`, `flipfix_units`, `flipfix5_units`, `flipfix6_units`, `flipfix5`, `flipfix6`, `fliplisten`, `flip`, `flipctl`, `lbplanner_units`, both `lb-stationary-*`, every feature-matrix cell, `rlcache`, `witness_contracts`; performance exclusions below |
| Parser/reorder dependencies | `reorder_bounds`, `reorder_sync`, `reorder_identity`, `reorder_engagement`, `inline_quoted`, `slotless`, `exec1s`, `execfair`, `ntfix_input`, `wb_rule_units`, `wbland_units` |
| Related owner reads | `readonly`, `datafix2_idle`, `notify`, every LFU/LRU-clock eviction cell, `datafix2_notouch`, `blockfix4` |
| Differential | All five `differ-*` parts, separately for uring and epoll, permanent seeds 7/19 plus the gate's rotating/durable corpus, four accumulated-state seed-19 MULTI repeats, and the complete equivalence inventory |

`jobs-broad-uring.txt` covers the common families and the first network-engine
leg. Jobs whose bodies already enumerate both engines retain all those legs.
`jobs-per-engine.txt` repeats the externally selected engine jobs with epoll.
`jobs-fused-extra.txt` repeats the mode-selectable release, atomic, ASAN,
WATCH, notification and debug batteries with `GATE_TXN_FUSED=1`, on both
engines. `jobs-additional.txt` also repeats splitlocal and RL5 after the R7
comment synchronization. The feature-matrix driver now verifies the requested
engine from INFO instead of silently ignoring the gate selector.
The planner exports its explicit shared-CPU mode to the feature/equivalence
drivers. Only those correctness callers can use it, with a selected job list,
rate assertions disabled, and identical sets of eight CPUs. Performance callers
retain the separate-CPU requirement. Serverless negative controls cover those
boundaries.

Every completed attempt has its own JSON receipt, raw archive and ledger under
`jobs/`. Failed attempts remain failed evidence. In particular, the first broad
run's splitlocal failure is the generated R7 comment-parity check; its C++ unit
passed. The source synchronization and rebuilt runtime-image comparison are
recorded separately before the retry.
The first broad run also records feature cells refused before boot because their
driver still required separate CPUs, and transaction episode/WATCH helpers that
were missing beside the frozen subdirectory candidate. The retry uses the
explicit correctness-only allocation and a byte-identical POST copy beside the
production helpers. Both failed attempts remain evidence. The FIFO live row's
latency-bound failures receive a complete matching PRE control; their status is
separate from exact-value and ordering-invariant checks.

| Exclusion | Status and reason |
|---|---|
| Full iteration, ABBA and requested performance cells | NOT RUN: maintainer owns performance measurements |
| `flip_saturated` and its saturation shutdown row | NOT RUN: invokes memtier saturation traffic |
| `tailgen client-lb outstanding bound` | NOT RUN: invokes the open-loop load generator |
| `efficiency`, `zc`, atomic MGET/MSET throughput floor | NOT RUN: performance measurements; the two correctness rows in `atomic_floor` are selected separately by its existing `GATE_PROOF_NO_RATES=1` branch |
| Release rate assertions in `atomic_ryow`, `stream`, `xmove`, `xacct` | NOT RUN: existing gate correctness-only selectors retain correctness checks without scoring their release rates |

The scope does not include unrelated persistence, protocol, ACL or command
feature families outside these selected jobs. Their appearances inside an
unchanged selected battery are retained.

`jobs-family-completion.txt` completes nested tracking, INFO and MULTI rows found
by a literal gate row-label audit, including the whole containing job.
`jobs-family-epoll.txt` supplies blockfix4's externally selected epoll leg;
`jobs-family-fused.txt` supplies both snapshot jobs in fused mode. The other
family jobs retain their built-in mode/engine matrices. `clientfix` declares
both modes on its existing default io_uring boot; no epoll result is inferred
from an environment setting that its boot helper does not consume. The
`rldbg` build is already an executed prerequisite of `rlcache`.
