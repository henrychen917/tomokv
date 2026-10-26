# AT4-WOUND-1 proof and measurement request

## woundfix

Worktree `/home/user/Projects/cx-woundfix`, branch `cx-woundfix`, base
`7ae703778e854a7b76945af5792a5ec5e88061a6` (cx-execindex). No push.
Every lane process is restricted to CPUs 32–47; correctness listeners use
20300–20399. Builds use `taskset -c 32-47 make -j16`. Performance benchmarks
and the full iteration gate belong to the maintainer. No throughput claim.

### Change

The last group or EXEC placer that observes `Wounded` now CASes its epoch
from zero to `kAtomicCancelledEpoch` before publishing `aborted`. Completion
therefore retries instead of returning an aborted command image with a commit
ticket. The successful wound phase CAS owns the wound count, even if the
victim wins the epoch CAS. Blind-restart publishers also finish abort/backoff
and accounting when cancellation has already been helped. Placement OOM
publishes a group `WorkError::Oom` before `aborted`; its wire reply is
`ERR out of memory`. EXEC's existing non-wound execution-error reply and the
ordinary failed MSETNX condition are unchanged.

`DEFECT.md` §6 fixes the reported last-placer path, but the directed review
found an additional legal overlap: an independent placement OOM or an NX veto
can publish `aborted` inside the wound's phase/epoch gap. That bypasses the
last-placer helper. The first POST still accepted a group ticket in this case;
`docs/woundfix/initial/abort-gap.log` records it. The combined regression was
committed before its correction (`407800086`, then `f90cfa1f3`).

To close that overlap, EXEC resolves its last-placement phase even when already
aborted. Before deciding an aborted group, `txn_group_decide` CASes Placing to
Executing: this closes placement against a delayed wound, without executing a
command. If Wounded already won, it finishes cancellation instead. Normal OOM,
WATCH failure and failed-NX replies are preserved; a pending wound wins and
retries. No new wait, layout, reader retry or in-place write permission was
introduced. Production source is frozen at `f90cfa1f3`.

### Deterministic negative controls and D2 proof

The first three rows were committed before the production fix. Gate partial
run `build/gate-run.KZiP2p` built PRE and recorded 1 build pass / 3 regression
failures. Each regression fails in both namespaces and both modes. Full fields
and the gate's own ledger are in `docs/woundfix/pre/`.

| Directed case | PRE | POST |
| --- | --- | --- |
| Group's last placement inside phase/epoch gap | aborted, epoch 0; accepted ticket, unmaterialized `NoSuchKey` | cancelled epoch; ticket rejected |
| EXEC finalizer inside phase/epoch gap | terminal EXEC abort, no retry | doomed, retry queued, no terminal reply |
| `watch_place_unit` allocation failure | no work error; unmaterialized reply | exact OOM wire reply |

The extended serverless fixture copies the production translation unit and
inserts six pause seams only into that test copy. Release sources contain no
pause hook. It suspends the foreign wound, group blind restart and EXEC blind
restart between phase/epoch and epoch/aborted publication, then runs bounded
owner turns. It asserts each gap opened exactly once. The `no-arm` negative
control must fail; no skipped window is counted as a pass.

The fixture runs the real completion/finalizer and group redispatch / EXEC
attempt rebuild. Both namespaces and both modes pass: cancelled work cannot
install a write, retry preserves all three original version components, and
every successful phase wound contributes exactly one counter increment even
when the publisher's epoch CAS loses. Seventy-two combinations cover both
requester/holder kinds, placing/executing, and older/equal/younger versions at
each lexicographic component. Only a strictly older unit wounds a placing
holder; an executing holder is immune. **Blind crossings are the explicit
§2.8 exception to the older-unit bound**, as already stated in D2's approved
design. A non-wound failed MSETNX still returns terminal integer zero with its
ordinary decision ticket; an NX veto overlapping a wound instead retries. Order violations are zero in these fixtures.

The published INFO field for group wounds is `atomic_group_wounds` (there is
no `atomic_txn_group_wounds` field). EXEC uses `atomic_txn_wounds`.

### Gate accounting

Four aggregate rows are added: `txnorder wound group`, `exec`, `oom`, `d2`.
Their `collect_job txnorder_wound` is at line 5589, before the quick-tier exit
at line 5692 in this diff, so this
lane is **DQ=+4, DF=+4**. No `EXPECT_QUICK` or `EXPECT_FULL` assignment is edited.
The inherited execindex rows already require +2/+2 against the literal
798/815: the resulting declaration totals should be **804 quick / 821 full**.
The maintainer owns that update.

### Artifacts and PAD semantics

All artifacts are under `build/woundfix/`; SHA-256s are recorded in
`docs/woundfix/binaries.sha256`, sizes in `binaries.size`.

| Arm | Path | SHA-256 |
| --- | --- | --- |
| PRE (frozen base source build) | `PRE/tomokv` | `5f8d8053475b4ca9fa9737f5323f591867790043d1b875949a5af3fe5cc0d877` |
| POST release | `POST` | `e50e343c32bca46cfd5d2856225c97b9d313968209262f00f97b847d840d8ec6` |
| POST-layout | `POST-layout` | `c22e5b3ba933e02058750b7089f28960edceecfad89481092273da8f1fbee178` |
| PAD-A | `PAD-A` | `9cbeebd37dc3feb5f8092c9301982e4e88904c4b6ebe30b7bb27c1c439813feb` |

PAD-A is **type A, behaviour twin**: PRE behaviour in the exact common image
of POST-layout. Both link POST first and a symbol-isolated PRE second; PAD-A
changes only five bytes at the entry to run PRE. Sections, function addresses,
and data match. It is the exact twin of **POST-layout**, not the smaller release
POST. The release text-size total shrinks by 196 bytes; the common-image pair is
an additional layout control, not a substitute for the release comparison.
`docs/woundfix/pad-a.json` records all objects, link commands, patch and identity
checks. Both common-image arms pass all 16 bounded boots (both modes, engines
and namespaces): exact EXEC data, WATCH abort, and zero order violations.

### Maintainer measurement request — NOT RUN in this lane

Use the gate's instrument on the quiet box, at matched offered load, with
PRE/POST ABBA and a standing identical-arm null. Record per-cell cycles/op,
instructions/op, IPC, and rate. Do not infer throughput from serverless counts.

- `/home/user/Projects/calib/exec-merit.py`: **64 connections**, all eight cells:
  `x2s_a0_unc`, `x2s_a0_hot`, `x2s_a1_unc`, `x2s_a1_hot`, `x1s_a0_unc`,
  `x1s_a0_hot`, `x1s_a1_unc`, `x1s_a1_hot`; standard cell-specific settings. Compare release PRE against release POST.
- All **14 generic cells**, verbatim in `docs/woundfix/generic14.cells.txt`:
  h05, h06, p8g, p8s, d1g_l0, d1s_l0, m8g_l0, v1g_l0, d128g_l0,
  d32g_l1, d8s_l1, d32s_l1, x9_32_l1, x9_32_l0. Preserve their rate/latency
  score types and exact geometry/settings.
- **2s GET and SET, p1 and p32**: h17, h18, h49, h50 from
  `tests/headline_cells.txt`, copied verbatim to `docs/woundfix/split4.cells.txt`.
  Keep the gate's standard split geometry and matched payload/client/load
  settings on both arms; retain p1 latency and p32 rate scores.
- Repeat those comparisons on **POST-layout vs PAD-A (type A)** to separate
  behaviour from the common image's layout. Interpret this control separately
  from the release binary sizes.

Correctness is mandatory: zero wrong replies and zero order violations. For
merit/nulls, rate at matched offered load is the verdict; cycles/op and its
instructions/IPC factors explain it. A tiny rate change is not a claim without
the gate's same-session spread and null. The fix is on cancellation/exception
paths; the uncontended-command instruction comparison is a separate required
proof below.

### Completed live and command-scope proof

The final binary passed 20 repetitions of `tests/txn_nx.py` in each of eight
cells: both modes × both engines × databases 1/16, always atomic 1, 16 shards,
eight server CPUs (split ratio 6:2). Each repetition runs 8,192 transactional
rounds plus 8,192 bare rounds. Four concurrent drivers use fresh disjoint keys;
each server CPU 32–39 also runs a 20 µs spin / 30 µs sleep injector. Clients
use CPUs 40–47. Zero wrong replies, errors, unfinished threads or order
violations occurred.

An additional fused/uring, databases-1 boot ran 572 bare-only repetitions:
4,685,824 rounds and **301,615 group wounds**, exceeding DEFECT §6's 300,000
exposure requirement in the original symptom's posture. Its order violations
and wrong replies are zero. Live INFO counts are exposure witnesses; the
serverless phase-gap fixture separately proves exact one-per-successful-CAS
accounting. Commands, all repetition logs, counter deltas and binary identity
are in `docs/woundfix/live/`.

| Cell | Full repetitions | Extra bare repetitions | Group wounds | EXEC wounds |
| --- | ---: | ---: | ---: | ---: |
| 1s-db1-uring | 20 | 0 | 6751 | 10831 |
| 1s-db1-epoll | 20 | 0 | 1795 | 2274 |
| 1s-db16-uring | 20 | 0 | 1876 | 1859 |
| 1s-db16-epoll | 20 | 0 | 2086 | 1433 |
| 2s-db1-uring | 20 | 0 | 4268 | 3109 |
| 2s-db1-epoll | 20 | 0 | 793 | 845 |
| 2s-db16-uring | 20 | 0 | 6495 | 2520 |
| 2s-db16-epoll | 20 | 0 | 1188 | 1958 |
| exposure-1s-db1-uring | 0 | 572 | 301615 | 0 |

All **48 command-scope instruction pairs are exactly equal**, including
per-function counts: GET/SET/INCR/MGET/MSET, batch 1/32, 1s/2s, normal/db0;
MSET additionally covers atomic 0. These are bounded serverless production
entry/completion traces with exact-data assertions and deterministic clocks.
Allocator/libc/kernel internals are outside the named production scope. There
are zero added instructions in the measured uncontended paths; this is not a
cycles or throughput claim. Full PRE/POST table, receipts and trace digests:
`docs/woundfix/instructions/comparison.md` and adjacent JSON/logs.

### Gate validation in progress

The serverless/unit group completed with 47 passed rows, including execindex's
16 × 10-million-operation oracle cases, complexity controls, owner episodes,
WATCH, wake and atomic units. Four new rows initially refused stale fixture
binaries after an assertion edit. On rebuilding, D2's assertions passed but
its `PASS D2` text did not satisfy the row's `PASS:` matcher. Normalizing that
success prefix produced **5/5 passed** (release + four new rows) through the
same gate interface. The failed runs are retained in `docs/woundfix/gate/`.

`make all` and all 47 targets named by `job_production_units` built. All **51
make -q checks pass**: release, the 47 targets, both nested mdbqsbr live arms,
and the blockfix-cost witness/receipt pair. The phony mdbqsbr wrapper is checked
through its two actual build roots. See `docs/woundfix/build/`.

`python3 tests/gates_test.py`: **72 passed**, plus its 14-test persistence
subsuite, pinned to 32–47 with port 20377. The earlier CPU-loaded run's 12
fixed-deadline scheduler failures are retained; the final run changed no
assertion or deadline. See `docs/woundfix/gates_test.log`.

The runtime, ASAN and standard differential matrix results will follow. No full iteration gate or performance benchmark
has been run. The partial-only `GATE_PROOF_NO_RATES=1` explicitly leaves the
atomic floor and RYOW rate assertions NOT RUN, while retaining their correctness
checks; default/full-gate semantics are unchanged.
