# GT13SPLIT — EXECABORT/WATCH fix and test readiness

Two independent extractions are committed on `cx-gt13split`, with serverless
proofs. **Live MULTI/WATCH batteries, both-mode live boot, the complete gate, and
the performance null are pending maintainer execution.** No live server,
benchmark, load generator, or gate was run. The task-specific CPU restriction and
the shared no-server rule conflict for live batteries; clarification was requested
asynchronously, with no answer received before this report. Nothing is claimed
passed on the strength of that unanswered question.

Worktree: `/home/user/Projects/cx-gt13split`. Fetched and merged `origin/cpp` first;
it remained `b38916d8884e3d620a9cda85e0a2fec4363173bf`. No push. Production extraction:
`8e72d32a6` (`Publish EXECABORT parent decision and add serverless WATCH witness`).
The following commit, `Harden shared test readiness and migrate owned boot helpers`,
contains tests and receipts only. The report ships with that second commit.

No `src/core/loading.cc`, listener/barrier changes, loading flag policy, or server
readiness-banner change is included. The **entire production-source diff is the
three-line GT13 fix in `src/cmd/multi.inc`**, identical to `cx-gt13`'s change from
`f769efcdd`/`b38916d88`. Layout assertions remain intact.

## EXECABORT mechanism and falsifier

Queue-time errors suppress command preparation, but EXEC still validates WATCH
and creates a blocking reservation pointing at its parent epoch and abort words.
PRE's error-finalization path only aborts children. The parent's epoch stays 0
and its abort flag false after the EXECABORT reply. The reservation keeps the
parent alive and blocks every later write to the watched key. The fix release-
publishes parent `aborted=true` before child aborts and owner finalization.

The serverless witness drives real production public interfaces and links the
**same witness object** to frozen PRE or POST production objects. Sequence:
WATCH, MULTI, queued SET, SAVE rejected at queue time, EXEC → EXECABORT, later SET.
It requires the WATCH arm, checks that the queued SET never applied, and bounds
ordinary write-dispatch attempts at 1,024. It starts no worker, ring, or listener.
Both variants configure 16 shards and eight workers; split is 6 IO + 2 EX.
Namespaced tests use 2 databases; DB0 uses 1. All runs are pinned to 112–119.

| Evidence | PRE | POST |
|---|---|---|
| Armed: 2 variants × 2 modes × atomic 0/1 | 8/8 reproduce the stall | 8/8 complete |
| Later SET dispatch denials | 1,024 per case | 0 |
| Reservation waits, before → after SET | 1 → 1,025 | 0 → 0 |
| Retained parent states | 1 | 0 |
| No-WATCH / no-queue-error controls | 16/16 pass | 16/16 pass |
| Missing-arm falsifier | 8/8 fail with exact arming diagnostic | 8/8 fail with exact arming diagnostic |

Total: **64 expected outcomes**. This is a deterministic serverless stall,
not a live latency measurement. Reproduce with:

```
make -j8 all build/execabort-watch-unit build/execabort-watch-db0-unit
python3 -B docs/gt13split/prove_execabort.py
```

The proof script relinks witnesses only; it never rebuilds the frozen PRE server.
See [mechanism and proof details](docs/gt13split/EXECABORT.md) and
[raw witness output](docs/gt13split/execabort-witness.log).

## Byte identity

The literal source port nudged GCC's namespaced xshard inliner and changed
ordinary code. A Makefile compiler budget (`inline-unit-growth=0`,
`large-unit-insns=127577`) restores the non-MULTI bodies. It applies only to the
namespaced xshard translation unit, with no runtime knob. Compiler:
`g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`.

The unmodified `tools/lbstall_artifacts.py compare` reports **1,482/1,482 raw-byte
and relocation-target matches**, including six GET, four SET and 240 parser/
dispatch bodies. **84/86 production objects are wholly byte-identical**. Auditing
all 854 DB0 + 859 namespaced functions in the two changed objects finds exactly:

| Changed body | PRE bytes | POST bytes |
|---|---:|---:|
| `tomo_db0::multi_execute_task` | 11737 | 11737 |
| `tomo::multi_execute_task` | 11880 | 11880 |
| `tomo::(anonymous namespace)::normalize_multi_blocking_pop` | 3356 | 3329 |

Symbol inventories match. No ordinary xshard, GET, SET, dispatch or cold clone is
excluded to obtain this result. The broader audit only extends the stock ELF
relocation-width table for `R_X86_64_TPOFF32` (23, four bytes), retaining the
symbol/addend/target checks. GNU size text: **8,796,237 → 8,796,217 (−20 bytes)**;
data 89,704 and BSS 1,146,456 unchanged. No structure layout changes; no PAD arm is
requested or claimed. No throughput neutrality claim follows from byte identity.

```
python3 tools/lbstall_artifacts.py compare build/gt13split-pre build build/gt13split-hot-bodies.json
python3 -B docs/gt13split/audit_bodies.py
```

[Hot-body receipts](docs/gt13split/hot-bodies.json),
[all changed bodies](docs/gt13split/changed-bodies.json).

## Test-only readiness extraction

The shared `wait_ready` has one monotonic deadline covering the fresh log's exact
banner line, connection, PING, and INFO SERVER PID check. Every unsuccessful
connection closes. It requires PONG and tolerates only startup transport failures
or the exact LOADING PING error. Other server errors, a near-match LOADING reply,
PID mismatch and non-transport OS failures stop immediately. Partial line/bulk
reads spend the same deadline; successful return restores application timeouts.
Application commands are never retried.

Migrated: `_gate_process`, `shutdown_persist`, `resizefix`, `wiredump`,
`mdbqsbr_live`, `connreset_repro`, `servertail`, `signalacct_live`,
`flushfix_checks`, `redisgap`, `reorder_flip`, `watchlive_gate`. Owned TomoKV
launchers pass fresh logs and child identities; watchlive verifies `$!` and the
socket owner. The wiredump Redis oracle uses PONG/PID without TomoKV's banner.
Persistfix retains its existing stronger checks. Today's server still never
replies LOADING; the compatibility cases are mocked. See
[readiness details](docs/gt13split/READINESS.md).

Executed proofs:

- Original readiness 8 + new deadline/identity controls 12: **20 passed**.
- Gate process **12**, signalacct **5**, connreset **4**, mdbqsbr **10**: **51 total**
  with readiness. [Receipt](docs/gt13split/readiness-tests.log).
- Existing persistfix self-test **14 passed**.
- Existing serverless WATCH/MULTI regressions: `watch_parent`, `watch_cycle`,
  `watch_oom`, `mset_arity`, `rename_overlay`: **5 passed**.
- New gate-row falsifiers **3 passed**; existing row/boot wiring **7 passed**.
- `multidb_serial.py --self-test`: both legal orders accepted, stale-stamp control
  rejected. This is not its live battery.
- Gateplan: **23 planning + 11 metadata tests passed**.
- Both release builds, layout assertions, Python syntax, `bash -n tests/gate.sh
  tests/watchlive_gate.sh`, and `git diff --check` pass.

## Rows and remaining mainline work

The existing `multi_exec.py` queue-error checks do not WATCH the key, so they
cannot catch this retained reservation. Add exactly one dedicated row:
`EXECABORT releases WATCH reservation` at `tests/gate.sh:1587`, collected by
`atomic_units` at line **3144**, before the quick exit at **3272**.
Delta **+1 quick / +1 full**; counts should become **497 / 514**.
The readiness commit adds **0 rows**. EXPECT constants and the ledger-label
fixture were deliberately not edited; the maintainer must update both before
requiring the complete gate's inventory check to pass.

On the scheduled box, run fresh owned POST servers on **112–119**, clients on
**120–127**, 16 shards, with 6:2 in split and no `--ratio` in fused. Require both
thread modes, DEBUG enabled, and the existing batteries without skips:
`tests/multi_exec.py`, `tests/multires.py`, `tests/multirace.py`,
`tests/watchlive.py --semantics-only`. Run `tests/multidb.py --read-local 0` and
`tests/multidb_serial.py` on a separate `--databases 16` boot in each mode, and
repeat that pair with `--read-local 1` / matching battery argument. Persistence
coverage remains the existing scheduled gate's responsibility. For liveness,
use `tests/watchlive_gate.sh PORT 112-119 6 /absolute/path/to/build/tomokv` with
fresh isolated repetitions; its historical standalone geometry differs from the
16-shard gate, so reproduce any failure at the gate geometry before attribution.
Live batteries are **not run here**, and live compatibility is **not asserted**.

Run the existing gate's correctness and performance instrument after the owner
updates counts. The requested PRE/POST null uses the unchanged 14-cell file
`tests/wbland_merit_cells.txt`, SHA-256
`de0e56e4696f780543c5adea21aa7d7283c12fa22110be6064370a69a2a68dc6`:
`h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`.
Use the frozen release arms below, existing calibration/payloads/pins, and the
contemporaneous two-sided same-binary null. Matched-offered-load rate and cycles/op
decide neutrality; IPC and instructions/op explain it, with the existing latency
tail guards. This file is fused-mode coverage; it does not replace split-mode
correctness or the gate's split performance coverage. No performance result was
produced by this lane.

## Frozen releases

| Arm | In-tree path | SHA-256 |
|---|---|---|
| PRE: origin/cpp | `build/gt13split-pre/tomokv` | `f89740c9fd8964fad603e0df9df434c4f83f9fa5e39c66bcd23d68f18880a717` |
| POST | `build/tomokv` | `494d4d1413cbda088761afe1ff25265c6133c53e13188360e9ee1bc3ac7e653b` |

PRE was built in this worktree before editing, via
`taskset -c 112-119 make -j8 BUILD_ROOT=build/gt13split-pre all`.
POST was rebuilt normally after the final compiler budget. The subsequent
readiness-only edits leave both binary hashes unchanged. Verify with
`sha256sum -c docs/gt13split/binaries.sha256`. All artifacts remain in this
worktree; source and proof receipts are committed, binaries are ignored.
