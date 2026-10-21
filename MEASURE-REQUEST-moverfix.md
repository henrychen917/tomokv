## moverfix

Lane `cx-moverfix`, based on `8656f9fa924fc06aa128504fca8aa99436aa9e41`.
Donor `f7f3ce7a5d2008c729822332f6cc1a14270ebe15` was read from `cx-txnfix`;
that worktree was not modified. No push. This request is still being completed.

The isolated atomic-0 claim protocol is implemented. **A broader EXEC conservation
claim is false on the headline:** the supplemental four-client EXEC/RPOPLPUSH
check fails on both PRE and POST, in both thread modes. This is retained as a
separate failure, not weakened or included as a passing D2 claim. It is outside
this lane's permitted atomic-0 runtime changes.

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
stronger claim. Existing MULTI/EXEC batteries are run without assertion edits.

### Controls and gate inventory

The original T05 assertions and parameters (N=2000, W=4), G5 atomic-0 mover
assertions, and all `txn_movers.py` assertions are preserved. Only connection and
headline-independent helper plumbing was adapted. PRE reproduces T05 conservation
failure and G5 duplicate delivery in 2s/1s, databases 1/16, uring/epoll: eight cells,
all failing for the data assertion. Initial POST passes all eight cells, including
all LMOVE directions, BRPOPLPUSH and all BLMOVE directions after four waiters are
registered, LMPOP/ZMPOP both ends with COUNT 3, and 100 four-way SMOVE races.

`tests/moverfix_unit.cc` schedules actual owner turns: both contenders probe the
same source before either claims it, including a destination arriving first and
a fully depleted source. It runs against PRE and POST, in both compiled database
namespaces. The fixture has no server, worker, timing window or injected pause;
its HIT line is preceded by assertions on both nonempty source probes. The
live battery complements this deterministic schedule with the actual dispatch,
blocking/resumption and network paths. LMPOP/ZMPOP checks are coverage controls;
the headline's earlier AT1 fix already passes those schedules on PRE.

One `job_moverfix` owns eight rows, each with all seven mover families and T05/G5,
including every live leg even after an earlier failure. Both engines, both modes
and both database counts are explicit in each label. It is collected BEFORE the
quick-tier exit: **DQ=+8, DF=+8; required EXPECT_QUICK=677, EXPECT_FULL=694** (from
669/686). Neither constant has been edited. The explicit label fixture has no
missing/extra labels; its count comparison remains red until the maintainer
updates those constants.

Receipts: `docs/moverfix/pre-reproduce/`, `post-reproduce/`, `exec-controls/`,
`pad-controls/`. Initial harness errors (invalid boot option and fused
ratio) remain separately identified; the successful reproduction reruns use the
correct production grammar. No reproduction failure is counted as a successful
POST result.

### Identity and layout

Locked sizes are unchanged on PRE and POST (no headers or fields changed): Op 336, Client 1984,
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
Run a same-session PRE/PRE null, then PRE/POST and PRE/PAD-A comparisons with the
same cell geometry and matched offered load. Retain each arm's rate, cycles/op,
instructions/op and IPC plus the per-cell verdict; no average can hide a losing
cell. The maintainer's merit verdict, not instruction count or identity, decides.
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

No throughput benchmarks, full iteration, merit ABBA or mover-path instruction
measurement ran in this lane. These remain NOT RUN here by the owner's division
of measurement work.
