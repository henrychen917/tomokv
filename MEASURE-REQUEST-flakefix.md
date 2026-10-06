# flakefix — directed witnesses for GT14 / GT17

**WIP — not ready to merge.** The implementation and serverless checks are
complete, but the strict every-ordinary-body byte audit still fails for
three emitted symbols (two destructor aliases and DB0 AOF initialization).
Fresh live six-run proof and the null measurement are also pending. This
handoff preserves the failures within the requested 75-minute lane limit.

Branch/worktree: `cx-flakefix`, `/home/user/Projects/cx-flakefix`.
Fetched and merged `origin/cpp` before editing; the branch was already at
`9d957b9fbb7a6eadace068b9615eef81b0dd6686` (PRE). No push.
Final production/test source commit: `c7921b8cb`; the initial schedule was
committed separately as `21dce3b45`. Subsequent report-only commits do not
change the frozen binaries.

## Per-row disposition

| Gate row / job selector | Original lottery | Directed stimulus in this delivery | Fresh six-run proof |
| --- | --- | --- | --- |
| atomic torn/window battery / `atomic_batteries` | OFF RENAME and MGET had to overlap by chance; 76,437 reads could miss | Preserve the already-landed `ATOMIC-OFF-HOP-HOLD` schedule, exact held OFF/ON images, and topology-aware fresh-state rearming | **Pending: 0/6 run by this lane** |
| xscript battery (atomic 1) / `debug-1` | Two scripts had to collide by chance; retries could remain zero | Preserve the already-landed `SCRIPT-STAGE-DEFER` schedule: witness the first script parked, commit the rival, release, require an OCC restart | **Pending: 0/6 run by this lane** |
| AOF control frame never inside a large record (atomic 1) / `aof_frame` | 128 groups and large SETs per round had to overlap; the 512 MiB cap ended the campaign before a witness | Use `AOF-REWRITE-PAUSE after-manifest`, witness an entire group queued, then witness LargeBegin queued behind its last producer before release | **Pending: 0/6 run by this lane** |

`round3-read/REGISTER.md` records GT14 and its addendum as closed by the
`gt14fix`/`gt14fix2` merge `464704b07`. Both directed tests and their hooks are
already in PRE. This lane makes no change to `atomic_torn.py`, `xscript.py`,
or their production hooks. Historical proofs in `MEASURE-REQUEST-gt14fix*.md`
are not counted as new six-run receipts for this delivery.

GT14 RENAME still requires status 2 before and after MGET, the exact OFF
image `[None, None]`, the exact ON image `[b"rename-value", None]`, and final
destination-only state. Only a proved ownership convergence permits bounded
rearming on fresh state. GT14 scripting still requires parked-stage/run
counters, the rival commit, at least one retry, exact final increments, and
drain. Neither assertion is made optional.

## GT17 schedule and invariant

The existing DEBUG rewrite pause now atomically publishes
`appendonlydir/debug-aof-frame-state` containing the writer thread ID,
pending chunk count, and posted sequence. Publication happens only inside
the explicitly armed pause loop. The file is removed on release. The helper
is isolated in `src/persist/aof_frame_debug.cc`; no configuration knob,
layout field, producer hook, or writer-pass branch is added. The existing
DEBUG command grammar and access checks are unchanged.

The purpose boot disables key/client balancing, automatic flips, timestamp
records and automatic rewrites. Tests discover real owners and select two
distinct owners, excluding the AOF writer, in ascending producer order.
The control connection excludes both the writer and the large-record
producer, so fused-mode channel backpressure cannot strand the observer.

1. Forty cross-owner script groups must all commit with no large record and
   no increase in the deferral counter (the negative pairing).
2. Arm the existing after-manifest pause, schedule a rewrite, and witness
   its exact stage file and a drained old increment (`pending=0`). Verify
   the actual writer ID before queuing anything.
3. Complete one cross-owner EVAL. Require exactly three new chunks: two
   fragments plus GCMT. With the writer paused, these observations persist.
4. Send one 17 MiB SET on the final producer. Require a fourth posted chunk
   while the same writer pause is still held. This is LargeBegin behind
   the group. All waits are bounded by 60 seconds; absent evidence fails.
5. Release the pause, require SET/rewrite/group completion, and require
   `aof_control_frames_deferred` to increase. The record spans 273 frames,
   exceeding both the ordinary 16-frame and drain-all 256-frame budgets.
   The real writer must see ready GCMT while the large record is OPEN.
6. Check the written values and walk every increment. Large records and
   control frames must both exist, with zero interleaves and no truncation.

The required witness is a **ready GCMT held out of** the open record; a
physical GCMT inside it remains a failure. The final bullet in the task is
read in that sense, consistent with its row name and reported defect.
There is no random stress-loop fallback, sleep used as evidence, skipped
witness, tolerance widening, or retry after corrupt data. Cleanup releases
the DEBUG arm even when a witness or reply fails.

## Offline validation

Release and serverless-unit builds passed with GCC 13.3.0, the default
jemalloc release flags and unchanged compiler budgets. All builds and native
units were pinned to CPUs 112–127. No server, load generator, benchmark, or
gate was started.

| Check | Result |
| --- | --- |
| `tests/aof_frame_order_test.py` | 9/9 pass; absent stage/group/LargeBegin, missing deferral, bad replies, malformed state and stale state cannot pass; cleanup and placement covered |
| `build/persistfix-unit frameorder` | Actual DEBUG pause unarmed/armed/released; exact zero/queued/full-width counters; atomic publication and failed publication; four actual writer schedules (16/256 budget × both commit producers) pass |
| `frameorder-no-guard` | Expected exit 1 at `ready GCMT MUST stay outside the open large record`; the guard bypass never ships in a server binary |
| `tests/persistfix_checks.py` | Four existing persistence schedules and three named broken controls pass, plus report-schema rejection checks |
| `tests/atomic_plain.py --self-test` | 8/8 pass |
| Shell/Python syntax and `git diff --check` | Pass |
| Existing selected-hot-body audit | **1,488/1,488 raw bytes and resolved relocation targets equal** |
| Strict whole-production-object audit | **FAIL**, details below; not waived |

Receipts: `docs/flakefix/`, with full build logs and compiler investigations
under `build/flakefix/`. Native units instantiate the existing serverless
fixture but open no listener or io_uring instance.

### Exact audit limitation

`python3 docs/flakefix/audit_bodies.py` compares all 88 PRE production
objects in both database namespaces. 86 complete object files are identical.
Of 16,934 emitted function symbols, 16,858 have raw-identical body bytes and
16,927 match bytes plus resolved relocation/direct-call targets. Address
displacements are resolved rather than treated as instruction changes; no
opcode or ordinary immediate is masked. The only permitted changed bodies
are the existing DEBUG pause and its cold clone in each namespace (four).

The **three remaining ordinary mismatches** make the audit exit 1:

| Symbol | PRE bytes | POST bytes |
| --- | ---: | ---: |
| `tomo_db0::AofManager::init(...)` | 6,408 | 6,424 |
| `tomo::AofManager::~AofManager()` D1 alias | 1,467 | 1,483 |
| `tomo::AofManager::~AofManager()` D2 alias | 1,467 | 1,483 |

The added cold code changed GCC's inlining choices. No experimental
compiler-budget setting is committed. A sampled isolated DB0 budget of
32370–32374 eliminated DB0's mismatch; the multi-database destructor's
choice of which string destruction to inline remained different across
the sampled budgets. These experiments are not the released POST binary.
Do not claim that every ordinary body is byte-identical or that zero cost
is proved. The selected-hot-body pass does not discharge the stricter rule.
The new observer objects are additions; the 88-object count covers PRE's
object inventory. Linked addresses and total text placement can change.

### Frozen binaries

| Arm | `.text` bytes | SHA-256 |
| --- | ---: | --- |
| `build/flakefix/PRE/tomokv` | 7,797,900 | `c0b1a23c31c5a0f64c36d903d14788c6cba2522bfb19c35507d17d2ffd8932eb` |
| `build/flakefix/POST/tomokv` | 7,799,772 | `97c5595c0549973534f841a7b0d88650bb6a1325c98f7269d5602a14f96f0ca0` |
| `build/tomokv` | 7,799,772 | `97c5595c0549973534f841a7b0d88650bb6a1325c98f7269d5602a14f96f0ca0` |

Verify with `sha256sum -c docs/flakefix/binaries.sha256`.

## Requested six consecutive gates — maintainer action

The shared instructions reserve gate/server execution to the maintainer;
the task also asks this lane for six runs. A clarification was requested,
and no exception has been confirmed. The code, binaries, serverless tests,
and exact run request are delivered without claiming those runs happened.

Run these selected jobs **six times consecutively**, serially, on the
specified 16 CPUs. Keep each run directory, ledger, timings, shutdown logs,
and the three battery logs. Any failed run invalidates the clean sequence;
retain it and investigate before starting a new six-run sequence.

```bash
mkdir -p build/flakefix/gate-proof
for repetition in 1 2 3 4 5 6; do
  GATE_ONLY_JOBS='atomic_batteries debug-1 aof_frame' \
    tests/gate.sh iteration \
      --server-cores 112-119 --load-cores 120-127 \
      --server-smt '' --load-smt '' --ports 18340-18342 \
      >"build/flakefix/gate-proof/run-${repetition}.log" 2>&1 || break
done
```

Use the gate's own 16-shard / eight-server-core geometry. `aof_frame`
retains its atomic=0 and atomic=1 pairing. `GATE_ONLY_JOBS` selects whole
jobs and required builds; these are partial-job proofs, not a full gate
receipt. Record the six clean run IDs and exact witnesses in
`MEASURE-RESULT` or an appended results section here.

Gate row delta: **+0 quick / +0 full**. Existing RENAME, debug and AOF row
collection sites are above the quick-tier exit. The new serverless checks
run inside the existing AOF rows; no row is added or retired. Leave
`EXPECT_QUICK=499` and `EXPECT_FULL=516` unchanged. No fixture data changed.

## Requested 14-cell null — maintainer action

Arms: `build/flakefix/PRE/tomokv`, `build/flakefix/POST/tomokv`; the normal
`build/tomokv` is POST. Run the mainline 14-cell null with the gate's own
instrument, matching every offered-load, geometry, warmup and duration
setting across PRE/POST/POST/PRE. Both modes must pass correctness first.
The existing cell file is `tests/wbland_merit_cells.txt` (SHA-256
`de0e56e4696f780543c5adea21aa7d7283c12fa22110be6064370a69a2a68dc6`):
`h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`.
Preserve those cells' performance geometry; the 16-shard/eight-core setup
above is for correctness only. This null file covers fused mode, so retain
the normal gate's split-mode performance coverage as well.
Record per-cell matched-load rate, cycles/op, instructions/op and IPC,
paired spreads and binary/instrument hashes. Rate decides; instruction
counts and IPC explain it. No performance improvement is claimed by this
correctness-test change. A regression or spread over 2% needs investigation.
No PAD arm is supplied or requested, and byte identity is not a substitute
for the null measurement. Null results: **pending**.
