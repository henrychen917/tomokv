# signalacct2 — merged arms, FLIP refusal, and mainline request

2026-09-25. Worktree `/home/user/Projects/cx-signalacct`, branch `cx-signalacct`.
First action was `git merge origin/cpp`; reference is
**`32d27ee7562ed5a17ff889c0fe5cf250f3fdc63c`**. Merge `6b25fef4b` retains both
lanes' includes/Makefile targets and the new physical-mode writeback dispatch.
All builds and executed serverless checks used **112-127 only**. No server,
benchmark, gate, or push was run by this lane.

**Status:** all requested arms rebuilt; deterministic FLIP defect reproduced,
fixed, and rejected by a removal control. Historical failure replies were lost
by the old harness, so attributing all eight live failures to this defect remains
**pending a mainline run with the new receipts**. Strict PRE/POST machine-code
identity remains **FAIL: 274/368**, including 14 collateral differences.
No performance or live-correctness acceptance is claimed.

## FLIP classification and evidence

The retained 2026-09-24 logs show `AssertionError: manual grow must finish` at the
comparison of the returned value. `_lib.Conn` returns `RespError` objects for
RESP errors; a socket timeout/EOF/parser exception would bypass that assertion.
Therefore those eight failures were **returned non-OK replies**, not observed
client timeouts beyond 15 seconds. Their exact bytes and elapsed times cannot be
recovered from those logs. A server's own five-second timeout error remains a
possible returned reply; the old assertion cannot distinguish it.

The saved failing `argv.json` explicitly has `--flip-auto 0`, unlike the manual
reproduction with auto=1. There is no auto/manual race in this harness's argv.
Productive traffic reads every reply and joins every worker before returning;
the remaining concurrency is **server-side disconnect cleanup**, not an unjoined
traffic producer. `wait_parked` proves at least four workers parked twice, not
that every client was reclaimed. It runs before shrink, and there is no park
between productive phase 1 and grow. FLIP's success path calls
`flip_complete_active()` (publishes Idle) before `finish_flip_command()` emits
OK, so waiting for the first reply already waits for that FLIP's convergence.
Neither another sleep nor retrying a refusal is a correction here.

**Confirmed category (a) mechanism:** `IoLoop::close_client` removes a closing
client from `ThreadCtx::clients()` before the captured client-work epochs allow
`client_released()` to decrement `live_clients`. It keeps the unreclaimed client
in `active_` for retry. The old `flip_io_drained()` checked the thread client list
and corpse queues, but missed this detached, still-live active entry. The planner
then observes owned=1/live=2 and returns exactly:

```
ERR FLIP connection ownership count is not conserved
```

Anchors: `src/core/io_loop.h:1718`, `:5477`, `:5555`;
`src/core/server.h:1023` and `:1035`. Multi-DB's `DatabaseWorkScope` extends the
client-work epoch across a whole IO pass, including park/callbacks, which makes
this window reachable with a peer IO. DB1 can reach it with an executor's
post-Done tail; its earlier live passes do not disprove that smaller window.
This concerns lifetime/drain accounting shared with the September multi-DB work,
not a database-count or 16-shard/6:2 restriction. No lost-FLIP P0 was established.

Fix commit **`c6dc98e3c`**, separate from harness commit **`b0379e266`**: the cold
FLIP drain waits for closing, non-dead clients in `active_`, then retains the
existing corpse/channel grace and ownership-count validation. No lifetime,
single-owner, RYOW, read-local, or namespace fence is weakened. Accounting and
the per-operation path gain no new guard. Test refinement **`e68662b49`** starts
at the settled 3:5 state and calls the actual `flip_begin(6,2,...)` and planner.

The serverless reproducer (`tests/flip_close_checks.inc`, row `flip-close`) holds
a real peer IO epoch at db16, closes a real in-memory Client, proves the exact
premature planner refusal, requires the drain to wait, releases the captured
epoch, starts a newer epoch, and requires normal close/grace followed by a
successful plan. It also covers db1's executor-tail window. No sockets, listener,
worker loops, or timing luck. Removing only the new guard produces:

```
ARMED flip-close db16: ERR FLIP connection ownership count is not conserved (FLIP 6 2, owned=1 live=2)
FAIL core concurrency: FLIP drain must wait for detached closing client
```

Positive exit 0; negative exit 1 at that exact assertion. Receipt:
`build/signalacct-proof/flip-close/results.json`. This proves the defect and fix;
it does not manufacture the missing historical wire replies.

Harness changes preserve traffic, FLIP ordering, timeouts, and fresh-state edge
rearming. `flips.json` records every FLIP's parsed reply/type, actual consumed
wire bytes (hex and repr), monotonic elapsed nanoseconds, and classification.
Every attempt failure additionally writes/prints `failure.json` with its phase,
all FLIP events, INFO `flip_*`/`flipctl_*` fields, role/client counts, and the last
16 KiB of combined server stdout/stderr. A fresh two-second diagnostic connection
is used after failure; if INFO cannot run, its exact error is retained instead.
That probe temporarily adds a client. Timeout receipts preserve any bytes already
returned by the reader; they do not pretend an incomplete reply was complete.
There is no FLIP retry or silent tolerance change.

## Accounting after wbrule

**No accounting cut moved in this merge.** Canonical anchors now are entry
`io_loop.h:506`, per-pass cut `:529` before `DatabaseWorkScope`, idle span `:724`,
and final cut `:776` before read-local teardown. Generated R7 retains the same
ordering. Relative to the old reference mechanism, signalacct still replaces the
work-Span cut after the prologue with a cut at pass entry and adds the final
partial-tenure flush; wbrule introduces no further cut.

Physical 1s now calls `wb_rule::Phase2::serve` at `io_loop.h:5203`, visits the
captured FIFO once, and uses the staged-byte/contiguous-Done eligibility rule.
There is no fixed fused connection budget. A deferred entry retains work so the
next pass revisits it. Both the longer walk and deferred passes lie between
consecutive accounting cuts; submit/reap, sweep, continue edges, and scope
destructors are included. Split and split read-local retain their prior budget;
the merged sweep forwards `SplitLocal` so only physical fused threads use c12.

For consecutive cuts, `busy += (next-cut) - (idle_next-idle_cut)`. Idle callback
classification is unchanged. Finish runs once after the last idle destructor,
and each IO invocation starts fresh, excluding intervening EX tenure. The exact
inner wall equality and independently bracketed outer wall remain the oracle.
There are no new clock calls inside the composite eligibility walk.

`tests/signalacct_source_checks.py` proves the merged `wb_rule.h` and complete
`flush_ready` envelope identical between frozen PRE and POST; EX source and all
five generated EX methods are identical; idle token/callback order is identical.
The stale-generator and changed-idle-timeout controls still reject. Commit
`54001b07b`; receipt `build/signalacct-proof/source-proof.json`.

Serverless checks passed: five live-driver tests (including actual RESP error
bytes, unexpected reply, partial timeout, failed INFO, and bounded rearming);
29 accounting/parser/invalid-state controls; flip controller unit; core lifetime,
route/model/physical-choice, and drain rows; actual 1s/2s shutdown report emitters
through both report parsers. Merged WB production-path checks passed for fused
full-FIFO service, FIFO rotation, deferred progress, split-local sweep, and R7
full-FIFO/FIFO paths. These are serverless results, not server boots or a gate.

The added regression belongs to the existing core **lifetime** emission at
`tests/gate.sh:1246`, before the quick exit at **2838**. Added rows: **0 quick,
0 full**. Inherited counts remain **441/457**; this lane did not edit either
EXPECT constant. Mainline owns live and instrumented gate validation.

## Rebuilt artifacts and strict code audit

All paths below are in `build/`. Production source commit is `c6dc98e3c`; later
commits affect proofs/reporting only. Default release compiler/flags/jemalloc and
per-TU compiler budgets are unchanged. Fresh PRE source was extracted from
32d27ee75, not the previous 3e734cf2e tree. Build logs:
`signalacct2-{final,pre,pair,witness}-build.log`.

| Arm | .text bytes | SHA-256 |
|---|---:|---|
| `tomokv-signalacct-pre` | 7,550,604 | `b8eaa1f508f3def9dcadc7c5d9471fa226a1cd08cbfd4f75ab611c61a199a6c5` |
| `tomokv` / `tomokv-signalacct-post` | 7,572,252 | `a619820eae254ebfecb0e7c081a0af47b2d4475fdc658e494f309e5a38ebed23` |
| `tomokv-signalacct-pair-post` | 7,770,041 | `be80d47d5c11ba0395f77a7653c618c9ca745c3c0bed309e58af72e3df6f6238` |
| `tomokv-signalacct-pad-a` | 7,770,041 | `dd8a34a9100b1949767ff2358e3596801db87b2f45e0a98cd758402ea6890add` |
| `tomokv-signalacct-witness` | 7,577,453 | `4bca648afabe543dcf1548e3c8a83c230adbae18769f2fd78a67d2176bfdee54` |

**PAD kind (A), behavior twin:** PRE IO work-Span behavior in **PAIR-POST's** text
and data layout, with the same construction as round 1. Canonical and generated
PRE envelopes are copied from 32d27ee75; reversing the cold endpoint additions
recovers both exactly. Both pair arms share the new closing-client drain fix,
cold histories, alternate envelopes, and role-entry selector. Two selector
immediates differ, at file offsets **422341** and **4183429**. Sections, symbols,
relocations, and all other bytes match; an additional executable-byte mutation
is rejected and never executed. `pair-source.json` and `pad-a.json` retain proof.
The pair is larger than release POST, so the POST/PAIR-POST transport comparison
below is mandatory. Witness is correctness-only; its deliberate sweep scheduling
does not ship or enter performance comparisons.

Locked layouts remain Op336, Client1984, ThreadCtx1408, Shard1440, FlatStore944,
Rob192, AtomicEntry144, Config624 in both namespaces. IoLoop remains 7136/align8,
with existing offsets unchanged. Cold Server history still adds 3072 bytes;
existing Server offsets and align64 remain unchanged (`layout.json`).

The original strict checker first stopped on its old **336-body inventory**.
Wbrule added 16 physical split-local `flush_ready` specializations per namespace.
`--inventory wbrule` requires all 32 exact names, raises the inventory to 368,
and compares every old and new body with the unchanged normalizer. It does not
exclude collateral differences, relax byte operands, or change the old default.

| Strict PRE 32d27ee75 vs POST scope | Identical / compared |
|---|---:|
| GET/SET handlers | 16/16 |
| Multi-key commands | 32/32 |
| Dispatch | 56/56 |
| Retire | 16/16 |
| Scheduler | 55/64 |
| IO envelopes | 99/184 |
| Total | **274/368 — FAIL** |

80 changed IO `run_loop` bodies are intended. The 14 collateral differences are
db0 split `execute`; four EX `run` bodies; two tomo fused pass bodies; five
`flush_ready` bodies; and two db0 fused sweeps. Full retained diffs:
`noop-merged/{017,022,031,071,080,122,123,141,161,163,165,167,201,202}.diff`.
Do not infer rate parity from the command-body matches. POST-self passes 368/368;
deliberate single-GET-byte corruption rejects exactly that handler (exit 1).
These separate checker controls are retained in `byte-controls/`.

Artifact bindings, compiler, ELF/disassembly dumps, current source patch, layout,
and all receipts are under `build/signalacct-proof/`. The previous round is kept
under `build/signalacct1-{pre,proof,arms}/`. The **old perf A/B is VOID** because
the reference changed under it; the reported -7/-11% is not a signalacct verdict.

## Mainline-only live commands — not executed by this lane

Run from this worktree on a scheduled quiet box. To recover the historical error
text, first use the new diagnostic driver on the preserved original POST bytes
(sha `60264c145bf849296b7d4590647d47debfce73b7e248589401ce655c391137eb`).
These ten fixed attempts retain failures and never turn an unexpected outcome
into PASS; use a new output prefix if repeating the campaign.

```bash
for trial in $(seq 1 10); do
  if taskset -c 8-111 python3 tests/signalacct_live.py \
    --binary build/signalacct1-arms/tomokv-signalacct-post \
    --output "build/signalacct2-mainline/original-$trial" \
    --cores 0-7 --mode 2s --read-local 0 --overlap 1 --reorder 0 \
    --databases 16 >"build/signalacct2-original-$trial.log" 2>&1; then
    rc=0
  else
    rc=$?
  fi
  printf 'original attempt %s exit %s\n' "$trial" "$rc"
done
```

If a failure records another reply, retain it as a different cause; this lane's
deterministic refusal does not authorize relabeling it. No reproduced failure
in ten attempts is **unreproduced**, not proof that the old defect never existed.

Re-run the original **72 live cells** with rebuilt arms (64 matrix + 4 PAD
controls + 4 epoll). Driver enforces shards16, split6:2, flip-auto0. Missing edge
windows still require a fresh process, at most three; wrong replies and
conservation errors fail immediately.

```bash
for arm in post witness; do
  edge=(); if [ "$arm" = witness ]; then edge=(--edges); fi
  for mode in 1s 2s; do
    for rl in 0 1; do for ov in 0 1; do for ro in 0 1; do for db in 1 16; do
      taskset -c 8-111 python3 tests/signalacct_live.py \
        --binary "build/tomokv-signalacct-$arm" \
        --output "build/signalacct2-mainline/live-$arm-$mode-$rl-$ov-$ro-db$db" \
        --cores 0-7 --mode "$mode" --read-local "$rl" --overlap "$ov" \
        --reorder "$ro" --databases "$db" --net-io uring "${edge[@]}" || exit 1
    done; done; done; done
  done
done
for mode in 1s 2s; do for db in 1 16; do
  taskset -c 8-111 python3 tests/signalacct_live.py \
    --binary build/tomokv-signalacct-pad-a \
    --output "build/signalacct2-mainline/legacy-$mode-db$db" \
    --cores 0-7 --mode "$mode" --read-local 1 --overlap 1 --reorder 1 \
    --databases "$db" --legacy-control || exit 1
done; done
for mode in 1s 2s; do for knobs in 0 1; do
  taskset -c 8-111 python3 tests/signalacct_live.py \
    --binary build/tomokv-signalacct-witness \
    --output "build/signalacct2-mainline/epoll-$mode-$knobs" \
    --cores 0-7 --mode "$mode" --read-local "$knobs" --overlap "$knobs" \
    --reorder "$knobs" --databases 16 --net-io epoll --edges || exit 1
done; done
```

## Mainline-only performance commands — not executed by this lane

Use explicit frozen arm paths, never a moving `cx-final/build/tomokv`. The
committed instrument still has only a reviewed **32-core / 16:16** ABBA geometry;
these commands therefore use server 0-31 and load 32-111, no SMT. This differs
from the mandatory eight-core live reproduction. An eight-core performance run
requires mainline to qualify its geometry/load plans in the existing instrument;
this lane has not invented that measurement. Default ABBA derives 256 fused or
128 split shards at this 32-core geometry; retain the actual boot argv.

Cells: **h01-h64**, GET/SET p1/p32 in both modes and every supported knob
combination, plus MGET/MSET p1/p32 guards **m01,m03,m04,m06,m49,m51,m52,m54**.
All 72 IDs parse against the frozen merged cell file. Original cell payloads,
512 total connections, atomic1, key pattern, load-plan and saturation/null rules
remain intact. P1 rows score latency; do not relabel them saturated capacity.

```bash
SIGNALACCT_IDS=$(cat build/signalacct-proof/mainline-ids.txt)
COMMON=(--build-reference 0 --subset full --only "$SIGNALACCT_IDS" \
  --cells build/signalacct-proof/headline_cells.merged.txt \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --ports 7933-7940 --max-instances 16)

# Four comparisons; each gets its own identical-byte reference null.
for pair in pre:post pad-a:pair-post post:pair-post pre:pad-a; do
  before=${pair%%:*}; after=${pair#*:}; tag=$before-$after
  rc=0
  taskset -c 0-111 python3 tests/abbagate.py "${COMMON[@]}" \
    --reference-binary "build/tomokv-signalacct-$before" \
    --candidate-binary "build/tomokv-signalacct-$before" --collect-null 1 \
    --output "build/signalacct2-mainline/null-$tag" || rc=$?
  if [ "$rc" -ne 3 ]; then exit 1; fi
  for block in 1 2 3; do
    rc=0
    taskset -c 0-111 python3 tests/abbagate.py "${COMMON[@]}" \
      --reference-binary "build/tomokv-signalacct-$before" \
      --candidate-binary "build/tomokv-signalacct-$after" \
      --null-result "build/signalacct2-mainline/null-$tag/results.json" \
      --output "build/signalacct2-mainline/perf-$tag-$block" || rc=$?
    if [ "$rc" -ne 3 ]; then exit 1; fi
  done
done
```

These selected campaigns return PARTIAL/exit3, not full-gate PASS. Inspect
`null_control`, validity/trust, and each cell decision; an exit code alone is not
acceptance. A newly invalid load floor requires a fresh reference qualification,
not a threshold edit or candidate-specific offer change.

The existing diagnostic PMU path can supply the complementary explanation with
the **same COMMON arguments** (repeat for the other three pairs as needed):

```bash
taskset -c 0-111 python3 -c '
import sys
sys.path.insert(0, "tests")
import abbagate as abba
raise SystemExit(abba.main(abba.parse_args(), diagnostic_monitor=abba.QuietMonitor,
                          diagnostic_profile=1))
' "${COMMON[@]}" \
  --reference-binary build/tomokv-signalacct-pre \
  --candidate-binary build/tomokv-signalacct-post \
  --null-result build/signalacct2-mainline/null-pre-post/results.json \
  --output build/signalacct2-mainline/profile-pre-post
```

That wrapper is explicitly untrusted for rate/null certification. Its CPU
counter interval is wider than the central completed-command window: retain
`approx_cycles_per_central_command`, `approx_instructions_per_central_command`,
IPC, and interval offsets as approximate. It does not establish aligned cycles/op.
Mainline's qualified aligned instrument, if used instead, must retain its identity
and the same arm hashes. Rate/tails at a matched plan decide regression; cycles,
instructions, and IPC explain it. Never accept instruction count alone.

| PRE/POST decision | PRE | POST | PAD-A / PAIR-POST | Verdict now |
|---|---|---|---|---|
| p1 GET benefit / other main-command parity | pending | pending | pending | unmeasured |
| p32 rate/tails | pending | pending | pending | unmeasured |
| release POST vs PAIR-POST bridge | — | pending | pending | unresolved layout effect |
| Exact live IO-tenure conservation | legacy expected to fail | pending | legacy expected to fail / witness pending | serverless proofs only |

Accept accounting benefit only if POST moves beyond the instrument's measured
resolution, PAD stays at reference parity, the release bridge holds, and there
is no rate/tail regression. Preserve the strict code-generation failure and the
unconfirmed historical FLIP attribution until independent evidence resolves them.

## Serverless reproduction commands

```bash
taskset -c 112-127 make -j16 all build/signalacct-core-unit build/flipctl-unit
taskset -c 112-127 python3 tests/flip_close_controls.py
taskset -c 112-127 python3 tests/signalacct_live_test.py
taskset -c 112-127 python3 tests/signalacct_controls.py
taskset -c 112-127 python3 tests/signalacct_source_checks.py
taskset -c 112-127 python3 tests/signalacct_byte_checks.py
# Expected exit 1; preserve the full failure report.
taskset -c 112-127 python3 tests/r7shadow_noop.py \
  build/tomokv-signalacct-pre build/tomokv-signalacct-post \
  build/signalacct-proof/noop-merged --inventory wbrule
```

Rebuild PRE with `taskset -c 112-127 make -C build/signalacct-pre -j16` and copy
its `build/tomokv` to `build/tomokv-signalacct-pre`. For pair/witness, run the
unchanged `tools/signalacct_artifacts.py prepare-pair` / `prepare-witness`, build
their subtrees with the same affinity, copy their binaries to the named root
arms, and run `pair build/tomokv-signalacct-pair-post build/tomokv-signalacct-pad-a`.
PRE was freshly extracted here; do not substitute the archived round-1 source.

Stop point: committed code, rebuilt artifacts and this report. Mainline owns
the pending live confirmation, performance, gate and merge.
