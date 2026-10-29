## climonfix5

Candidate source: `e4a0e13ab` on `cx-climonfix5`, from `aaf658f85`.
PRE is `393d6ceb1`; C4 production is `c369ccc41`. No push.

The unarmed command-scope audit passes: **144/144 comparable script/transaction
triplets have POST <= PRE; all 92 retained hot-command triplets have
PRE = C4 = POST.** The 32 no-writes-header triplets have POST < C4; PRE rejects
that header, so their PRE error paths are explicitly not equivalent work.
These are finite instruction counts, not throughput, cycles/op, IPC or latency
claims. The equivalent no-writes FCALL cells are being added separately.
Correctness validation is in progress; the final evidence below will replace
this status before handoff.

### Changes and scope

* Registry initialization marks actual metadata containers with a private
  `ClientCommandName` bit. The existing parser mask records CLIENT/CONFIG/etc.
  child names, while PING/MULTI/EXEC/WATCH take their original paths. Ordinary
  `cmd=` names already come from the retained ROB spec. Container arguments
  cannot safely be recovered after their receive buffer retires, so their
  existing metadata pointer remains necessary. CLIENT LIST checks cover a
  container followed by PING, another client listing it, and ROB wraparound.
* Unarmed transaction dispatch/retirement no longer tests the command spelling,
  loads the abort decision for MONITOR, or looks up a monitor connection. The
  existing armed refresh branch consumes the final EXEC reply while its ROB
  generation remains available. It recognizes errors, materialized nulls, and
  both RESP2/RESP3 coded nulls. Pending child records are discarded on abort.
  The parser phase precedes retirement; retirement sends the loop back through
  armed refresh before another parse. Transaction sessions also pin their
  connection against ownership migration, so the final EXEC slot cannot move
  into a new parser pass before this consumption.
* EVAL header validation/compilation is confined to the existing compiled-chunk
  miss. A no-writes chunk is cached as a Lua closure that marks that activation
  read-only. Plain warm EVAL/EVALSHA perform no header work. Original source
  hashing and Lua source-line coordinates are preserved.
* Nested MONITOR ordering and execution run behind the pre-existing script
  notification-routing branch. Admission rejection still produces no nested
  MONITOR record. WATCH observation remains independent: a WATCH-selected
  handler with a clean spec does not activate notification-source routing.
  The existing error buffer is initialized only by the error-producing paths,
  each of which writes it completely before use.
* In the db0 namespace, the first complete audit found a remaining four
  instructions per committed two-INCR EXEC in vector exception cleanup.
  Single-key transaction preparation now returns before constructing the
  duplicate-key vector. It retains `prepare_write_key`'s complete preflight,
  retry and abort behavior; multi-key preflight still precedes every install.

No gate row is added or removed: **DQ=0, DF=0 over climonfix4's 909/926**.
`tests/gate.sh` and its maintainer-owned `EXPECT_QUICK` / `EXPECT_FULL` are
unchanged. The existing MONITOR row gains witnessed WATCH-abort assertions
for RESP2 and RESP3; its public row count and location before the quick exit
are unchanged.

### Instruction evidence

[Totals](docs/climonfix5/instruction-totals.csv) contain all **268 PRE/C4/POST
triplets**. [Sites](docs/climonfix5/instruction-sites.csv) report every changed
production symbol in each triplet. [Summary](docs/climonfix5/instruction-summary.json)
checks completeness, probe identities, no positive comparable session deltas,
and exact equality of all 92 original hot scopes. Detailed per-symbol counts,
probe build commands and PC-trace hashes are in `docs/climonfix5/scopes/`.

Representative absolute counts, normal namespace, split 6:2, batch 1:

| Scope | PRE | C4 | POST | POST−PRE |
|---|---:|---:|---:|---:|
| EVAL, two INCR, single shard | 27085 | 27224 | 27080 | -5 |
| EVAL, two INCR, cross shard | 47898 | 48036 | 47891 | -7 |
| EVALSHA, single shard | 11775 | 11926 | 11769 | -6 |
| EVALSHA, cross shard | 37804 | 37954 | 37796 | -8 |
| FCALL, single shard | 11390 | 11483 | 11386 | -4 |
| FCALL, cross shard | 37482 | 37574 | 37476 | -6 |
| MULTI + 2 INCR + EXEC, single shard | 21973 | 22319 | 21925 | -48 |
| MULTI + 2 INCR + EXEC, cross shard | 26221 | 26567 | 26173 | -48 |
| WATCH-aborted transaction, single shard | 64268 | 64827 | 64268 | 0 |
| WATCH | 30678 | 30865 | 30678 | 0 |
| PING | 930 | 1027 | 930 | 0 |

For the representative plain EVAL, C4's +139 instructions divide into
`eval_header` +36, `run_eval` +11, `redis_dispatch` +38, and
`notify_monitor_script` +54. POST enters neither added helper and is -5 overall.
For EVALSHA the same sites contribute +36/+23/+38/+54 in C4, versus POST -6.
For FCALL, C4 adds +38 nested-dispatch, +54 monitor-helper and +1
`script_execute`; POST is -4. The full CSV includes the compiler's secondary
changes, including the small flag-selection increases in WATCH-selected
handlers and larger decreases in their formerly unnecessary source routing.
No symbol delta is omitted from the site report.

For representative committed EXEC, C4 adds +45 in dispatch, +62 in retirement,
+39 in command-name comparison, +6 in armed refresh and +194 across parser /
CLIENT metadata work. All those additions are zero in POST; the separate
single-key preparation change saves 48. WATCH-aborted EXEC's entire +559 is
removed. PING's +97 and WATCH's +187 are removed. Both `multi_pause_writes`
and `command_pause_write` have **zero observed entries on every unpaused scope
in PRE, C4 and POST**; neither is an unarmed culprit.

Method: `tests/climonfix5_scope.cc` drives the real parsers, executor, Lua
callbacks, scatter/transaction lifecycle, retirement and reply checks without
listeners or worker threads. Both namespaces, both modes, batches 1/32 and
single/cross-shard scripts/transactions are included. Scripts/functions are
warmed before the bounded scope. WATCH-abort scopes perform the real WATCH,
then deterministically set the connection's dirty indication before EXEC;
a competing writer is not included in their count. Additional watched EVAL,
EVALSHA and FCALL scopes catch the watcher-only handler-selection path.

The tracer steps through the embedded Lua VM so indirect callbacks cannot
escape, and counts instructions in the selected production namespace, including
relevant C++ template instantiations and NOPs. Fixture glue, Lua VM internals
and external libraries are excluded equally; clock_gettime is frozen. Lua
exception unwinding is traversed rather than mistaken for a returning call.
The original 52 complete hot scopes plus 40 parser scopes are retained.
This instrument does not reproduce contention or provide a rate verdict.

PRE has no `#!lua flags=no-writes` support: its EVAL fails compilation and
EVALSHA returns NOSCRIPT. Those absolute counts remain in the CSV and are
marked `comparable_to_pre=false`; no zero-cost claim compares successful
POST execution to PRE's error. Against C4's successful read-only execution,
POST saves 1114–1138.0625 instructions per invocation across these cases.

### Correctness evidence

Completed on frozen POST: all 28 climonfix4 rows (224 directed configurations,
including the added RESP2/RESP3 WATCH-abort assertions); all seven isolated
regressions rejected their named Tcl assertion in both modes; and
`python3 tests/gates_test.py` passes 73/73. All 53 production-unit targets
built; all 58 independent build/freshness checks pass, including `make all`,
`make -q`, and the blockfix binding ([audit](docs/climonfix5/production-units.json)).
Both Tcl modes pass all 1,704 assertions and all 14 climonfix4 promotions
([named assertion audit](docs/climonfix5/full-tcl-promotions-in-campaign.json)).
The remaining whole-job campaigns are still running.
[Directed receipt](docs/climonfix5/jobs/directed-final-v11.json),
[seven isolated controls](docs/climonfix5/isolated-regressions.json),
[harness tests](docs/climonfix5/gates-test.json). Five controls raise named
assertion errors. PAUSE-SCRIPT-FLAGS and MONITOR-SCRIPT-CMDS reach the named
witness, never report it passing, and fail at the unchanged Tcl runner deadline
in both modes; their positive counterparts complete in the full-manifest 1s and 2s runs. The selected whole-job
inventory is [job-selection.json](docs/climonfix5/job-selection.json).
All server boots inherit `LC_ALL=C`; all lane processes are restricted to
CPUs 16–31, builds use `-j16`, and correctness ports are in 20200–20299.
The regular gate geometry is 16 shards on eight threads, split ratio 6:2;
individual gate jobs retain their own explicit geometry overrides.

NOT RUN: `flip_saturated`, because it starts `memtier_benchmark`, a load
generator explicitly reserved to the maintainer. Its two rows are not claimed
as passing. No full iteration, ABBA or performance benchmark was run.
AT4.12 T6/T10 run only as their unchanged correctness jobs, with exact-value,
progress and wound/FLIP assertions; their recorded command totals are not
used as a rate comparison or a merit result.

Development failures are retained rather than counted as successful proof:
a mutable-binary relink interrupted one initial boot; a first full Tcl run
passed 2s but failed the unchanged blocked-BRPOPLPUSH/WATCH assertion in 1s;
C4 subsequently passed that assertion in isolation. The new WATCH/MONITOR
assertion rejected the candidate that omitted coded nulls, in all four
mode/engine jobs, before the coded-reply fix. A superseded production-unit
build was cancelled after source changes invalidated its binary binding;
its partial link failures/freshness cannot count as final proof.

### Retained arms and layout control

All four binaries are in `build/climonfix5/`; exact sizes and oracle identities
are in [arms.json](docs/climonfix5/arms.json).

| Arm | SHA-256 |
|---|---|
| PRE (`tomokv-PRE`) | `dd16c698ec4316c548be0eaa1d4db3fd2928c07f18b1a599e51966ea336a874b` |
| C4 (`tomokv-C4`) | `81a33ef8cc968b5f044ce15e2c8db15b6d6ffc29b247b93af85e8525f035020e` |
| POST (`tomokv-POST`) | `5580e65fb3d5135ca6829d272cf4de89c2661715bc58247ad26a7163939a0f5f` |
| PAD-A (`tomokv-PAD-A`) | `c5b445290dbf6919c270bd85075c59fbf5a416a80a9e54a5b1dc419616af038c` |

**PAD-A is (A), a behaviour twin:** PRE behavior with inert candidate cold
member layouts and candidate `.text` origin/total size. It is not an inverse
control. [Construction and link hashes](docs/climonfix5/pad-a.json) specify
exactly what is padded. Individual function offsets and data-section addresses
retain PRE placement, so this control cannot exclude every alignment effect.
[Offline DWARF checks](docs/climonfix5/layouts.json) verify matching POST/PAD-A
ClientMeta, ClimonConn, NotifyBatch and ScriptContext layouts, plus every fixed
size in both namespaces on all four arms:
Op=336, Client=1984, ThreadCtx=1408, Shard=1440, FlatStore=944,
Rob<64>=192, AtomicEntry=144, Config=624.
Superseded arm source/object trees and completed probe executables are removed
after their hashes and counts are recorded.

### Maintainer measurement request

Use the gate's own instrument on a quiet box, with matched offered load and
unchanged cells. Preserve the supplied storm geometry: three blocks, twenty
clients on two hot keys (8 two-INCR EVAL, 4 MULTI, 4 WATCH+MULTI, 4 plain INCR),
with neither PAUSE nor MONITOR armed. Compare POST vs PRE and POST vs C4;
retain scripts/s, EXEC/s, plain INCR/s, WATCH aborts, cycles/op, IPC and instr/op.
Run the existing uncontended EXEC cells (64 connections, pipeline 4) in both
modes, and the same fourteen generic cells including the read-local mix.
Include PRE/PRE null checks and the labelled PAD-A behavior twin where the
layout comparison is needed.

The decision is the rate at matched offered load, with instructions and IPC
explaining it. POST must remove C4's consistent storm regression without a
main-command regression; the generic null must remain level. A real behavior
gain should move POST while PAD-A remains flat. Do not infer that verdict from
these serverless counts. Record the measured PRE/C4/POST/PAD table in
`MEASURE-RESULT`; no throughput outcome is asserted here.
