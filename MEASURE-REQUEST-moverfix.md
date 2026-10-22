## moverfix

Lane `cx-moverfix`, based on `8656f9fa924fc06aa128504fca8aa99436aa9e41`.
Donor `f7f3ce7a5d2008c729822332f6cc1a14270ebe15` was read from `cx-txnfix`;
that worktree was not modified. No push. Correctness runs and build checks are complete;
the maintainer's performance/merit runs are NOT RUN here.

The isolated atomic-0 claim protocol is implemented. **A broader EXEC conservation
claim is false on the headline:** the supplemental four-client EXEC/RPOPLPUSH
check fails on both PRE and POST, in both thread modes. This is retained as a
separate failure, not weakened or included as a passing D2 claim. The requested
broader conserving EXEC proof/equivalent is therefore **NOT ESTABLISHED**. No EXEC
algorithm change is included in this isolated port. This is not a fully green
acceptance report.

### Runtime boundary

`src/cmd/xshard_movers.inc` contains the source-owner claim: read the current edge,
remove it in that same owner turn, then release-publish the outcome. A destination
that arrives first defers; it inserts only a successful claim. A source miss
returns nil, and SMOVE returns one only for a real removal. LMPOP/ZMPOP use the
current owner view at phase two. The existing `direct_ready` byte carries the
publication; no state field, per-owner structure, knob, reader retry, seqlock or
allocation-on-disabled-path was added.

Only the donor's four mover implementation files were ported. No EXEC isolation,
Stage B, intent arbitration, overlay or atomic-1 algorithm was ported.

The headline's `multi.inc` calls `xshard_prepare(..., true, state.client)` for
lowered children. `force_atomic` makes element movers `atomic_apply`, so they
never enter `execute_plain_element_mover`. Pop children already select the latest
read context and retain the parent's origin; `MoverLiveRead` leaves children
alone. Thus the donor's private-overlay helper is not a dependency of this port.
This is a reachability argument about the port, **not a claim that existing EXEC
is conserving**. The supplemental diagnostic and its PRE controls disprove that
stronger claim. Final POST delivers 2,341 replies in 2s and 2,711 in 1s from
2,000 unique source elements; `docs/moverfix/exec-final/runs.json` binds both
failures to the delivered POST SHA-256. PRE controls and the earlier POST build
are retained separately in `exec-controls/`. The own-parent
RPUSH/LMOVE/LMPOP sequence passes before the concurrent RPOPLPUSH failure.
Sending those children through the bare claim helper would
mutate outside their parent's atomic publication, so that is not a valid minimal
substitute. A live-view selection alone also cannot arbitrate two undecided
parents. The unlanded branch's parent arbitration/private overlays were expressly
excluded from this lane. Existing MULTI/EXEC batteries are run without assertion
edits; passing them cannot erase this counterexample. Exact routing anchors and
donor-helper identity are recorded in `docs/moverfix/runtime-anchors.json`.

### Controls and gate inventory

The original T05 assertions and parameters (N=2000, W=4), G5 atomic-0 mover
assertions, and all `txn_movers.py` assertions are preserved. Only connection and
headline-independent helper plumbing was adapted. `donor-test-parity.json`
records the comparison: the complete G5 method matches the current donor's AST
(including its later atomic-1-only counter assertions, unused by these rows),
and `txn_movers.py` matches f7f3ce7a5 except for the Battery import.
PRE reproduces T05 conservation
failure and G5 duplicate delivery in 2s/1s, databases 1/16, uring/epoll: eight cells,
all failing for the data assertion. Initial POST passes all eight cells, including
all LMOVE directions, BRPOPLPUSH and all BLMOVE directions after four waiters are
registered, LMPOP/ZMPOP both ends with COUNT 3, and 100 four-way SMOVE races.

`tests/moverfix_unit.cc` exercises real scatter code in a fixed owner-turn order:
both contenders probe the same source before either claims it, including a destination arriving first and
a fully depleted source. It runs against PRE and POST, in both compiled database
namespaces. The fixture has no server, worker, timing window or injected pause;
its HIT line is preceded by assertions on both nonempty source probes. The
live battery complements this deterministic schedule with the actual dispatch,
blocking/resumption and network paths. LMPOP/ZMPOP checks are coverage controls;
the headline's earlier AT1 fix already passes those schedules on PRE.

One `job_moverfix` owns eight rows, each with all seven mover families and T05/G5,
including every live leg even after an earlier failure. Both engines, both modes
and both database counts are explicit in each label. It is collected BEFORE the
quick-tier exit (`collect_job moverfix` at line 3979; exit at line 4094):
**DQ=+8, DF=+8; required EXPECT_QUICK=677, EXPECT_FULL=694** (from 669/686).
Neither constant has been edited. The explicit label fixture has no
missing/extra labels; its count comparison remains red until the maintainer
updates those constants.

Receipts: `docs/moverfix/pre-reproduce/`, `post-reproduce/`, `exec-controls/`,
`exec-final/`, `pad-controls/`. Initial harness errors (invalid boot option and fused
ratio) remain separately identified; the successful reproduction reruns use the
correct production grammar. No reproduction failure is counted as a successful
POST result.

### Gate results

Final POST ran through `tests/gate.sh quick` with `GATE_ONLY_JOBS`; this was not a
full quick gate or iteration. The selected jobs produced **146 PASS / 2 FAIL**.
All eight new mover rows passed, with all 128 leg logs present and 448 asserted
deterministic contention hits. Receipts: `gate-final-post/`,
`final-post-leg-inventory.json`, and `final-gate.log` under `docs/moverfix/`.
The failures were:

- ABBA serverless self-test: the existing receipt fixture guard stops at
  EXPECT_FULL=686 versus 694 declared/fixture labels, with no missing/extra label.
- R7 FIFO twin identity: its hard-coded off-path inventory expects 146 bodies in
  each namespace; the new linked inventory has 145 normal / 146 DB0. Its guard is
  unchanged. This is reported for merit review, not waived as a green row.

R7's unchanged negative-control function was also run against final POST after
the gate guard stopped its row: missing policy symbol, missing splitlocal parser,
and changed opcode are all rejected (`reorder-negative-post.json`). The row
itself remains red. The ten remaining top-level ABBA serverless checks all pass
when invoked unchanged after the count guard stopped their parent job; see
`remaining-runs.json` and `abba-tail-*`. `gate_receipt.py`'s own checks beyond its
entry fixture guard remain NOT RUN. Neither guard was bypassed to claim a pass.

`make -B -j16 all` succeeded. All 38 freshness checks are zero, including every
production-unit target. The phony `mdbqsbr-live-arms` target's two actual `all`
outputs were checked separately. The final repeat is `final-freshness.json`.

PRE then ran the same selected job list through the same gate interface:
**139 PASS / 9 FAIL**. Eight failures are the new mover rows and the ninth is the
same expected-count guard. R7 passes on PRE. All 128 PRE leg logs exist; each
unit fixture asserts its contention witness, and T05/G5 fail for conservation or
duplicate delivery in all eight geometries. `gate-final-pre/` and
`final-pre-leg-inventory.json` retain every leg, including passing PRE pop
coverage and occasional passing live races. The deterministic fixture is the
non-vacuous defect control, so no live lottery success is used as proof.

The gate's PRE candidate selects PRE servers and the separately compiled PRE
mover fixtures. Its other serverless jobs use the gate's normal current-worktree
unit outputs; they are not falsely presented as paired PRE production-unit builds.
Exact job invocation and sequencing are retained in `remaining.py` and gate logs.

The supplemental armed run completed 38 child invocations: 36 pass, including
all eight atomic-0 mover mode/engine/database cells; `execatomic.py` fails in both
read-local-armed modes on its deterministic MGET fan-out witness. Those runs
report zero cuts for that witness; all observations and failure lines are retained.
The recording driver exits zero after completing all invocations, so its wrapper
return code is not a battery verdict: `final-supplement/runs.json` contains the
individual child statuses. Matching PRE armed controls reproduce the same
`execatomic.py` witness failure in both modes: no mixed-value observation is
reported; the required fan-out cut never arms and the straddle sees all-new
values. The unchanged standard unarmed atomic checks (`atomic_torn`,
`atomic_ryow`, `atomic_hazards`, `execatomic`) pass on final POST in both modes,
eight of eight invocations. See `atomic-controls/runs.json` and its logs.
The armed 15-battery run includes the unchanged MULTI/EXEC, txn, and atomic
batteries; 28 of those 30 invocations pass. The other eight supplemental
invocations are the armed atomic-0 mover cells, all passing. These counts do not
turn the two armed witness failures into green results.

The standard differential gate is complete on both engines, using the unchanged
47-suite inventory, seeds 7, 19, 20, 23 and rotating seed 21, both atomic settings,
and the standard repeated MULTI legs:

| Engine | Geometry | PASS | FAIL | Harness-declared SORT skips |
|---|---|---:|---:|---:|
| io_uring | split 6:2 | 475 | 0 | 0 |
| io_uring | armed fused | 466 | 0 | 10 |
| epoll | split 6:2 | 475 | 0 | 0 |
| epoll | armed fused | 466 | 0 | 10 |

Both split invocations also pass all 32 mode-equivalence combinations. Each fused
invocation proves read-local hits in both atomic settings. SORT's fused legs are
NOT RUN by the unchanged harness because that suite requires split 6:2; its full
seed matrix ran in both split invocations. The harness's command-coverage reports
also remain intact; this is not a claim that every registered command was diffed.
See `final-differ/runs.json`, the four complete logs, and per-leg receipts:
**1,882 PASS / 0 FAIL**, with the 20 fused SORT legs explicitly skipped above.
The initial standalone
`gates_test.py` run retained 65 passes and two 45-second scheduler-fixture timeouts
while compilation was active; no deadline or assertion was changed. The quiet
rerun, without this lane's compilation or live workloads, passes **67/67** in
339.439 seconds (`gates-test-quiet.log`, return code 0).

All work stayed within CPUs 80-95: builds used -j16, servers 80-87, the Redis
7.4.10 oracle on 88, and clients 89-95. All listeners used ports 23800-23899.
`final-cleanup.json` records no remaining listeners or owned server/gate watcher
processes after the last diagnostic.

### Identity and layout

Locked sizes are unchanged on PRE and POST (no headers or fields changed):
Op 336, Client 1984,
ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144,
Config 624; ScatterState also remains 896. No header or member order changed.

Per-unit inlining budgets were re-derived from GCC IPA dumps and compile-only
trials. The selected budgets (xshard 128550 / DB0 127250) restore all 1,214
lbstall selected hot bodies, raw and canonical. ccfix reports 16,694 bodies:
16,617 equal, 77 changed; 1,211/1,211 command-handler bodies and 1,218/1,218
selected hot bodies equal. Every changed body and its reason is listed in
[identity-tuned/README.md](docs/moverfix/identity-tuned/README.md), with full JSON
and compressed disassemblies beside it. Unedited-source spillover is explicit,
including DB0 xshard_plain_prepare; whole scatter-path identity is not claimed.
The final forced `make -B -j16 all` output and both xshard objects match the audited
frozen build byte-for-byte: `docs/moverfix/final-identity-binding.json`.
Identity is a proxy; the merit run decides.

### Maintainer merit request — NOT RUN here

Use the gate's instrument and unchanged generic 14 cells in
`docs/moverfix/generic14-cells.txt` (copied from `docs/lbplanner/generic-cells.txt`).
The current `abbagate.read_cells` accepts all 14 cells; see
`generic14-validation.json`. The `ov=0` column is the parser's retired-knob
assertion, not a server flag.
Run a same-session PRE/PRE null, then PRE/POST and PRE/PAD-A comparisons with the
same cell geometry and matched offered load. Retain each arm's rate, cycles/op,
instructions/op and IPC plus the per-cell verdict. Use each cell's existing rate
or latency score; retain the standard latency quantiles for latency cells.
No average can hide a losing cell. The maintainer's merit verdict, not instruction
count or identity, decides.
No throughput claim is made. No mover-path dynamic instruction cost was measured
serverlessly; the deterministic owner fixture is a correctness instrument.

PAD-A means **(A) behaviour twin: POST text/layout with PRE mover behaviour**.
`docs/moverfix/pad_a.py` patches only copies, at checked instruction boundaries:
source refresh, claim-dependent destination branches, source outcome publication,
SMOVE actual-removal success and pop read-context selection. Every ELF section
header and every symbol address/size stays identical to POST. The control must
reproduce G5 duplicate delivery in both namespaces and modes before measurement.
All eight PAD T05/G5 controls fail for the data assertion (both modes and both
database namespaces). `pad-controls/runs.json` binds each running server's
`/proc/PID/exe` digest to the final frozen PAD before issuing commands.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/moverfix/pre/tomokv` | `7cc73003cf0e25aceb27016b24f66a1e877143a4416cd54470dd60a23c16f72a` |
| POST | `build/tomokv` | `82a44439ba38a5c27ea0c9962fcd02b51f3ae405fbf0d734f3eb327f1c75848f` |
| PAD-A | `build/moverfix/pad-a/tomokv` | `297f2dc1683de49b66c71d0ddba4fd728aa830e9f92339e8c4a1083d2094660b` |

All three digests were checked again after the final build and controls
(`final-arm-check.log`).

### NOT RUN and remaining limits

- Throughput benchmarks, full iteration, merit ABBA, and mover-path dynamic
  instruction measurement: reserved for the maintainer's quiet-box measurement.
- `atomic_ryow.py`'s rate assertions: its existing `--no-rate-assertions` flag
  retains correctness checks while leaving performance judgments to that run.
- Twenty fused differential SORT legs: excluded by the unchanged harness's
  split-6:2 requirement; all standard split seeds ran on both engines.
- `gate_receipt.py` self-tests beyond the entry fixture guard: blocked by the
  maintainer-owned EXPECT counts. Other ABBA top-level checks were run separately.
- Later concurrent EXEC LMOVE/LMPOP/ZMPOP diagnostic branches: the unchanged
  diagnostic stops at the first RPOPLPUSH duplicate assertion on PRE and POST.
  The complete bare-command mover families ran in all declared gate cells.
- Conserving EXEC proof/minimal equivalent: NOT ESTABLISHED. The parent conflict
  failure already exists on PRE, and this isolated port does not import the
  excluded EXEC arbitration/overlay redesign. Its counterexample remains open.


## moverfix2

Based on `c100f703f`, on `cx-moverfix`; no push. The existing R7 FIFO twin row is
now green. This is a harness inventory correction: production source, Makefile,
POST and PAD-A bytes are unchanged. Attribution and all compile-only trials are
in [docs/moverfix2/README.md](docs/moverfix2/README.md).

The normal namespace's 146 -> 145 is a net delta: `src/cmd/xshard.o` no longer
emits the KEYS/RANDOMKEY instantiation of
`FlatStore::atomic_for_each_unique_key<atomic_for_each_side_key<xshard_execute(...)...>...>`
`.isra.0` (2394 bytes) or its `.cold` fragment (5 bytes), but now emits the
`FlatStore::scan<xshard_execute(...)::{lambda(KvObj*)#1}>` `.constprop.0` clone
(1071 bytes). Exact mangled/demangled names and object/link digests are in
`docs/moverfix2/inventory.json`. GCC's late called-once pass inlines the first
helper through `atomic_for_each_side_key` into `xshard_execute`; this is not
linker merging or deleted KEYS code. The affected store source and scan calls
are unchanged from PRE. DB0's separate `TOMO_SINGLE_DATABASE=1` compilation and
127250 budget retain the 2219+5-byte unique-key bodies and inline scan, keeping
146. The compiler excerpts record both decisions and their different caller
sizes; the normal POST budget remains 128550.

Restoration was attempted with 17 normal-budget compilations, a DB0 baseline
compilation, and fresh PRE compiler dumps. Every changed object body is recorded.
None of the tested budgets restores the helpers while preserving all current
hot bodies. At the lowest tested value retaining them, 136000, 174 object bodies
change, including 10 selected hot bodies. A compile-only link confirms five hot
store bodies change (including `find`, `find_notify`, `insert`, `insert_notify`
and `erase_notify`); it also loses the `<false, false>` `xshard_execute` lambda,
leaving its total R7 count at 145/146 anyway. These are identity observations,
not throughput or cycle claims. The task's permitted fallback updates only
`expected['tomo']` in `tests/r7shadow_noop.py`, with the named delta explained in
the style of 13d6fabbc. DB0's count, every byte comparison, policy checks,
splitlocal checks and negative controls are unchanged.

Final POST verification used the gate's own interface:

```
taskset -c 80-95 env GATE_ONLY_JOBS='reorder_identity moverfix' \
  tests/gate.sh quick --server-cores 80-88 --server-smt '' \
  --load-cores 89-95 --load-smt '' --ports 23800-23877 \
  --candidate-binary /home/user/Projects/cx-moverfix/build/tomokv
```

The planner requires 16 advertised physical CPUs; the ninth advertised server
CPU (88) is unused by its single correctness slot. Actual servers use 80-87,
clients 89-95, shards 16 and split ratio 6:2. Builds use 80-95 with `-j16`.
Serverless self-test sockets use 23879 and the existing 23880-23899 bounded
port adapter. All work remains inside the authorized CPU/port allocation.

| Required check | Result |
|---|---|
| Gate job `reorder_identity` | PASS: 291/291 bodies, 145 normal + 146 DB0 |
| R7 negative controls, inside that job | PASS: missing policy symbol, missing splitlocal parser, changed opcode all rejected |
| Gate job `moverfix` | PASS: all 8 rows, 1s/2s x uring/epoll x databases 1/16 |
| Complete mover legs | 128/128 logs: 7 unit + 7 live families + T05/G5 per cell; 448 asserted unit contention hits |
| Selected gate ledger | 10 PASS / 0 FAIL, including release prerequisite; partial diagnostic, not a complete gate |
| `python3 tests/gates_test.py` | PASS: 67/67 in 330.320 s |
| `make -j16 all` + every `job_production_units` target | PASS |
| `make -q` freshness | PASS: 38/38, including both concrete outputs of phony `mdbqsbr-live-arms` |

The only touched gate job is R7 identity, included above. Receipts are in
`docs/moverfix2/gate/`, `gate.log`, `gates-test.log`, `freshness.json`,
`leg-inventory.json`, `receipt-inventory.json` and `runs.json`. `final-freshness.json` repeats all 38 checks, and
`cleanup.json` confirms no lane listeners or owned server/gate processes remain.
The untouched negative-control/normalizer sources and `gate.sh` are hash-bound in the receipt.
The full generated disassemblies/FIFO twin remain in the original build run
named by that receipt. No gate row was added or retired: **DQ=0, DF=0;
required counts remain 677/694**. Neither EXPECT constant was edited; their
existing maintainer-owned 669/686 values remain as inherited.

The entire delivered POST is byte-identical to the previous audited binary,
so all GET/SET/MGET/MSET hot bodies and locked layouts remain identical to that
POST. Rebuilding POST/PAD-A for a changed candidate is not needed. Final hashes:

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/moverfix/pre/tomokv` | `7cc73003cf0e25aceb27016b24f66a1e877143a4416cd54470dd60a23c16f72a` |
| POST | `build/tomokv` | `82a44439ba38a5c27ea0c9962fcd02b51f3ae405fbf0d734f3eb327f1c75848f` |
| PAD-A | `build/moverfix/pad-a/tomokv` | `297f2dc1683de49b66c71d0ddba4fd728aa830e9f92339e8c4a1083d2094660b` |

The maintainer should measure the same frozen PRE, POST and PAD-A arms from the
moverfix request: PRE/PRE null, PRE/POST and PRE/PAD-A, with the unchanged
14-cell `docs/moverfix/generic14-cells.txt` and the gate's instrument. PAD-A is
**(A) behaviour twin: PRE mover behaviour with POST text size/layout**. Retain
per-cell rate/latency verdicts at matched offered load, cycles/op, instructions/op
and IPC; an average must not conceal a losing cell. No new arm is required by
moverfix2, and no throughput claim is made.

**NOT RUN:** performance benchmarks, measurement load generators, merit ABBA
and full `tests/gate.sh iteration`, reserved for the maintainer. Rejected budget
trial binaries were inspected offline only. The prior moverfix report's separate
EXEC conservation and armed-witness limitations are unchanged; this green
selected job run makes no broader correctness claim.
