# aclkeys4 — SWAPDB leaves XADD publishing to the wrong namespace

The missed wake is deterministic. A fresh server needs only `SWAPDB 0 1` before
parking `XREAD BLOCK 0 STREAMS block:aclkeys 0`. XADD inserts the correct stream,
but its old wake call supplies namespace **0** to a registry entry in physical
namespace **1**. The original MovePending handshake remains intact.

Worktree/branch: `/home/user/Projects/cx-aclkeys`, `cx-aclkeys`. Mainline was fetched
and merged before work and again before proof. PRE is merge-base
`dab740964`; merged aclkeys3 before this fix is `515411726`. Nothing is pushed.
All live correctness children use server CPUs **112–119**, client CPUs **120–127**,
16 shards and 16 databases. Split is **6:2**; armed-fused sets `--read-local 1`.

## Reproduction and minimization

The supplied two-suite standalone matrix (`multidb`, `aclkeys`; seeds 7, 19, 20,
23; atomic 0/1) reproduced **8/8 failed aclkeys legs**, with multidb **8/8 passing**.
[Original output](docs/aclkeys/aclkeys4/repro.log). This run used the original
aclkeys3 executable, SHA-256 `ac4ad0d764f38407ec1473fef5a019e8ee2df3166d2ddd3e2d2d7129cbae2506`.

[Fresh-state discrimination](docs/aclkeys/aclkeys4/minimization/forms.log):

| Arming commands | Original wake |
|---|---|
| None | Pass |
| `SWAPDB 0 1` | Timeout |
| `SWAPDB 0 1` twice | Pass |
| `SWAPDB 2 2` | Pass |
| Invalid swaps (`bad`, out-of-range 99) | Pass |
| One `SWAPDB 0 1` inside EXEC | Timeout |
| Two `SWAPDB 0 1` inside EXEC | Pass |
| `SWAPDB 0 1`, `FLUSHALL` | Timeout |
| Both clients select DB 1 on a fresh map | Timeout |

The random-swap-only arm also failed. Bisection of gen_multidb(seed=7)'s **276**
random swaps retained a failing half at each step and ended at the one command
`SWAPDB 0 1`; its empty-command control passed. Every trial used fresh server
state. [Commands/results](docs/aclkeys/aclkeys4/minimization/bisection.json),
[driver](docs/aclkeys/aclkeys4/minimize-swaps.py).
The earlier passing suites happen to leave the tested logical DB mapped to a
working physical namespace; invalid/self/EXEC forms are not separate causes.

The permanent reproducer is [tests/aclkeys_wake_state.py](tests/aclkeys_wake_state.py).
Its core sequence has ten statements: swap, delete, get client ID, send XREAD,
witness CLIENT LIST, witness completed owner registration, start deadline, XADD,
assert the exact nested reply, assert elapsed time under **2 seconds**. It takes a
fresh db16 listener and leaves server lifecycle to the caller. `blocked_clients=1`
and `blocking_waiters=1` are both required: CLIENT LIST's blocked flag alone can
precede registration and let the eager reprobe mask this bug. An absent window
fails instead of skipping. Existing differential assertions/timeouts are unchanged.

## Observed state

The original executable was run under a read-only GDB query. Threads are stopped
while inspecting the owner-only registry, avoiding an unsafe cross-owner DEBUG
reader and any production instrumentation changes. [Query](docs/aclkeys/aclkeys4/state/query.gdb),
[passing state](docs/aclkeys/aclkeys4/state/alone.json),
[failing state](docs/aclkeys/aclkeys4/state/swap.json), and complete debugger logs
in the same directory retain the raw observations.

| Observation | Alone | One swap |
|---|---|---|
| Logical DB of admin and blocked worker | 0 / 0 | 0 / 0 |
| Physical mapping of logical DB 0 | 0 | 1; map epoch 1 |
| Key shard/owner before arming | 14 / 6 | 10 / 6 |
| Key shard/owner at XADD | 14 / 6 | 5 / 7 |
| Registry namespace | 0 | **1** |
| XADD publication namespace | 0 | **0** |
| Registry hash versus publisher hash | Equal | Equal (`9540427374289458813`) |
| Registry phase / active tasks | Parked / 0 | Parked / 0 |
| Owning shard waiters before → after publication | 1 → 0 | **1 → 1** |
| Owning shard dirty flag before → after | false → false | false → false |
| notify-keyspace-events / timeout / maxmemory | empty / 0 / 0 | empty / 0 / 0 |
| Worker CLIENT LIST | flags=b, db=0, cmd=xread | flags=b, db=0, cmd=xread |
| Wake | Exact reply | Timeout |

Boot hashes vary, so shard numbers are observations of each particular boot.
All 16 shard-to-owner assignments remain identical within each observed run.
The failing key routes to another shard because its namespace changed; its
registry is on that correct shard and owner. The debugger records all 16 waiter
counters and dirty flags. Every other shard has zero waiters and a clear flag.

## Root cause and fix

`src/cmd/blocking.inc:1067` captures the key namespace in BlockingKey, and registry
lookup at `src/cmd/blocking.inc:842` compares **hash, namespace, and bytes**.
XADD's old call at `src/cmd/t_stream.cc:1224` omitted the namespace, invoking the
old `ns=0` default in blocking.h. The physical hash was correct, but the namespace
comparison rejected the waiter. No resume request was generated, so the preserved
MovePending protocol had nothing to deliver.

XADD now publishes its captured `op.physical_db` (constant zero in the compiled
DB0 variant). The two analogous list-push helper sites at `src/cmd/t_list.cc:1187`
and `:1228` now pass `key.ns`, covering both missing and existing destination lists.
The API declaration requires a namespace explicitly, making another omission a
compile error. All source and test call sites were searched. No new configuration
knob or harness server-flag hook is needed.

## Build and body proof

The fresh mainline PRE and POST are `build/aclkeys/{PRE,POST}/tomokv`;
POST is byte-for-byte `build/tomokv`. Both database namespaces are built.
The body audit resolves relocation targets and inventories the union of every
object's emitted functions, including cold clones and weak copies. The report
lists each changed body and its reason; inherited aclkeys/aclkeys3 changes are
separated from this fix. Validation of final merge-related compiler locks is in progress.

## Live proof and rows

The final-binary minimal regression has passed **6/6** in each of split/armed-fused
× atomic 0/1 (**24/24**). The merged broken arm fails **4/4** at the XREAD reply
assertion after completed registration. The blocking battery passes **4/4** on
those same settings, after an unmatched swap, with keyspace notifications enabled.
[Proof receipts](docs/aclkeys/aclkeys4/proof/positive.json).
The complete 42-suite prefix proofs are running; this draft does not claim them green.

The new gate row is emitted inside `job_multidb` at `tests/gate.sh:3144`, once for
each of mode 1s/2s × read-local 0/1 × atomic 0/1. Its eight collection sites are
above the quick-tier exit: **+8 quick / +8 full**, **502 → 510 / 519 → 527**.
The EXPECT changes are in the same commit as the regression, as this task requests.
The full gate was not run by this lane.

## Measurement request

This is a correctness repair. The maintainer may run the usual matched-load null
comparison on the final PRE/POST arms; no throughput or latency gain is claimed.
The lane's required instrument is the exact wake reply and the unchanged
correctness suites. Final SHA-256 and prefix receipts will be recorded here on completion.

## aclkeys5

Fixed `LedgerWiring.test_multidb_rows_fail_independently` in
`tests/gates_test.py`. Its shell stub now handles `tests/aclkeys_wake_state.py`
through `WAKE_RC`, and every expected result contains all three rows. All 14
existing sub-cases remain; wake-only failures with exit codes **1** and **3** in
both `1s` and `2s` add four sub-cases, for **18** total.

The third row starts a fresh boot and has no `unit_ready` dependency. The shared
`BOOT_RC` stub applies to both boots; the expected outcomes follow that wiring:

| Stub failure (all other exit codes zero) | multidb | serial order | XREAD wake |
|---|---|---|---|
| None | ok | ok | ok |
| `BOOT_RC=1` | FAIL | FAIL | FAIL |
| `MULTIDB_RC=1`, `LIVE_RC=1/3`, or `UNIT_RC=1` (separate cases) | FAIL | ok | ok |
| `SERIAL_RC=1` | ok | FAIL | ok |
| `WAKE_RC=1` or `WAKE_RC=3` (separate cases) | ok | ok | FAIL |

Validation used only the serverless harness, pinned to CPUs **112–127**:

```sh
taskset -c 112-127 python3 tests/gates_test.py
taskset -c 112-127 python3 tests/gates_test.py LedgerWiring.test_multidb_rows_fail_independently
```

The [full output](docs/aclkeys/aclkeys4/aclkeys5-gates-full.log) reports
**66 tests, OK**, exit 0 (76.829 seconds). The
[focused output](docs/aclkeys/aclkeys4/aclkeys5-gates-single.log) reports
**1 test, OK**, exit 0, including all 18 sub-cases.

For the negative control, one temporary mutation changed the fresh wake row's
failure handler from `bad` to `ok`. The focused test exited **1**, with **six
failing sub-cases**: boot failure and each of the two wake-script failures, in
both modes. This includes all four newly added cases. The original gate bytes
were restored in `finally` before the full run and before committing.
[Mutation output](docs/aclkeys/aclkeys4/aclkeys5-gates-mutation.log) and
[exact mutation/restoration hashes](docs/aclkeys/aclkeys4/aclkeys5-mutation.json)
record the control. No server, load generator, benchmark, or gate was run.

Merged fetched `origin/cpp` (`6b50f447f`) first, producing merge baseline
`c46dd73d2` from task-entry HEAD `ed648110e`. The test/evidence commit is
`f70b41c78`. Relative to that merge baseline, `tests/gate.sh` is byte-identical
and [production.diff](docs/aclkeys/aclkeys4/production.diff) is empty for `src/`.
The `job_multidb` body also matches task-entry HEAD.
[Proof metadata](docs/aclkeys/aclkeys4/aclkeys5-proof.json) records commands,
exit codes, source/output hashes, case preservation, and scope checks.

**Merge inventory note:** the required upstream merge independently imported
the `wb-small-pipe` and `wb-complete-visits` netcmd rows at `tests/gate.sh:1681`,
collected at line **3289**, before the quick-tier exit at line **3420**. Those
are **+2 quick / +2 full** on top of this branch's existing **510 / 527**, so
the combined inventory calls for **512 / 529**. `EXPECT_QUICK=510` and
`EXPECT_FULL=527` were preserved verbatim; the maintainer owns reconciliation.
This aclkeys5 self-test change adds **0 / 0** gate rows. The existing eight wake
rows are collected at line **3397**, also before the quick-tier exit.

No new measurement arms or PAD are required for this harness-only change.
