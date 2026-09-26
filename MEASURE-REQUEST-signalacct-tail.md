# signalacct-tail: windowed IO accounting publication

2026-09-26, branch `cx-signalacct`. Fast-forwarded this worktree to the requested
`ea45968a9` before editing. Production change: `5b65ad5f4`; serverless controls:
`8d081367c`; private measurement cells: `ddd5a91f9`.

The candidate removes checked accounting and its shared busy-counter store from
ordinary passes, retaining one existing pass clock. It publishes the **complete
elapsed interval** once per 100 us and flushes the remainder at every IO exit.
Serverless conservation and negative controls pass. **Tail recovery and the
always-on <=3% cost rule remain unmeasured. This is a candidate for mainline's
verdict, not evidence that the reported latency regression has been eliminated.**

All lane builds and executed checks were pinned to **112-127**. No server,
benchmark, load generator, gate, push, or other-worktree edit was performed.
The requested finite serverless retired-instruction witness was executed.

## Diagnosis and cut inventory

The supplied mainline evidence consistently implicates the signalacct landing:
the two rechecks report t03 +15.8% / +9.6%, with t04 +8.4% in the recorded round,
and candidate spreads substantially wider than the reference. No performance
numbers were reproduced in this lane. The archived `36d1e875e` and `ea45968a9`
executables have **the same SHA-256** (below), so their supplied t03 +6.4% / high
spread control is an identical-byte comparison, not a tests-only code effect.

The source does **not** contain an accounting cut per connection or per command.
It also does not show an increased number of accounting clocks after landing.
`76ef4beae` paid two busy-Span clocks per work pass; `36d1e875e` pays one pass
clock. BITCOUNT runs on EX in these read-local-off 2s cells. Its long service
time changes the number and duration of IO passes/parks, not the cuts per pass.

| Site in the merged source | Position relative to recv -> dispatch -> send | Count |
|---|---|---:|
| `src/core/io_loop.h:529`, generated copy `src/core/reorder.cc:822`; helper `src/core/signalacct.h:65-71` | Before CQ processing / recv, at every outer pass boundary | 1 CLOCK_MONOTONIC per pass |
| `src/core/io_loop.h:586-590`, generated `src/core/reorder.cc:879-883` | Existing depth/CPU beat, before recv | 0 or 1 CLOCK_THREAD_CPUTIME_ID per pass; at most one per 100 us |
| `src/core/io_loop.h:724`, generated `src/core/reorder.cc:1017`; `src/core/signal.h:205-207` | After both productive and sweep-submit continues; brackets publication/recheck/wait/resume, including existing epoll callbacks | 2 CLOCK_MONOTONIC reads per idle-span visit, even if the recheck avoids sleeping |
| `src/core/signalacct.h:55-60` | Cold IO role entry, before loop/prologue | 2 CLOCK_MONOTONIC reads per tenure |
| `src/core/io_loop.h:776`, generated `src/core/reorder.cc:1069`; helper `src/core/signalacct.h:74-85` | Cold exit, after the last idle destructor and before read-local teardown | 2 CLOCK_MONOTONIC reads per tenure |
| `src/core/io_loop.h:679-718`, generated `src/core/reorder.cc:972-1012` | Productive or sweep submit/reap and continue | **0 extra accounting clocks**; witness-only edge increments compile out of release |

For **p8, GET:BITCOUNT=8:2**, a productive or sweep-submit pass therefore pays
**1 monotonic read**, or **3** if it reaches the idle span, plus the independent
0/1 CPU-time beat. For P passes and I idle-span visits, the accounting total is
**P + 2I + 4** monotonic reads over a tenure, versus **2P + 2I** for the old work
Spans. The fixed candidate leaves these clock counts unchanged from the landing.
There are no eight-per-pipeline or ten-per-mix cuts. A command may span several
passes while the owner is doing BITCOUNT; source alone cannot determine P/I or
clocks per completed command. Slowlog/other explicitly armed instrumentation is
outside this accounting inventory.

The new per-pass work in the landing was `IoTenure::account`: counter loads,
monotonicity/idle/overflow checks, subtraction/addition, and **three stores**:
`sig_.busy_ns`, `idle_cut_`, and `cut_`. The last two are IO-stack-only state.
The busy store moved from the old Span's end to the next pass's beginning;
relative to `76ef4beae` it was not a newly introduced per-pass shared store.

DWARF layout inspection in both namespaces gives `ThreadCtx::sig_ = 960`, so
`busy_ns` is at **976**, on cache line **[960,1023]**. That same existing line
holds ops, iterations, idle, CPU time, depth sum/sample count and full-events.
It is read cross-thread by INFO (`src/cmd/lbsignals.cc:37-57`) and the LB/physical
FLIP fold (`src/core/server.h:599-605`). These are executor/controller readers,
but this is **not a newly shared transport line**: normal EX task/ready-mask
handoffs use other fields, and IO already stores ops/iterations in this line.
Fewer busy stores do not prove removal of all RFO traffic on that line. No new
ThreadCtx field or line split was introduced by either the landing or this fix.

Tenure histories append only at exit (`src/core/io_loop.h:787`,
`src/core/server.h:469-474`) after the read-local park. Shutdown consumes them
after join (`src/core/shutdown_report.h:172`). INFO/controller never consume
these histories. Existing `lb_controller_tick` does run on the designated IO
cron thread at its one-second beat (`src/core/io_loop.h:654-660`,
`src/core/weighted_lb.h:26`), but the landing added no per-pass report emission or
new consumer call. Flip demand remains ops/wall/idle, explicitly independent of
busy (`src/core/flipctl.cc:764-784`); physical victim occupancy does use busy.

**Code-supported target:** eager checked accounting plus its enlarged inlined
IO envelope. Extra interior clocks and per-pass report allocation are ruled out
by source. A new executor-read line is also ruled out by layout. Instruction
counts support reducing eager accounting work; they do not identify which
microarchitectural effect caused the mainline tails. PMU/rate/tail comparisons
below must resolve that remaining attribution.

## Fix and serverless evidence

Only `src/core/signalacct.h` changes production behavior. `pass()` still returns
the current monotonic timestamp for cron/WAIT and depth/age sampling. It compares
that timestamp with an owner-local publication deadline. On the first pass and
then the first boundary at least 100 us after the last publication, an outlined
`account()` executes the unchanged checked wall-minus-idle calculation. The
100 us interval comes from the existing depth-signal beat, not a workload knob.
Effective passes per publication adapt to elapsed pass lengths; no sampled turn
is multiplied by N and no BITCOUNT interval is dropped. `finish()` unconditionally
accounts the final partial interval, including zero-pass and stop-during-park
tenures. Idle classification, teardown ordering and EX accounting are unchanged.

Publication can lag by the window plus an in-flight pass/wait; the old accounting
also waited until the next boundary for in-flight work. Live busy/idle snapshots
remain asynchronous. Completed-tenure conservation is still exact to the last
nanosecond, with the same independently measured endpoint bracket. No locks,
atomics, reader retries, ownership changes or per-client allocation were added.

The new checks include a long idle spanning multiple windows, uneven passes,
burst passes after a long interval, exact final flush, and suppressed intermediate
busy publications. The existing deterministic pass-by-pass arithmetic cases use
the explicit zero-window test specialization; the new window cases exercise the
production default. Existing role/zero/invalid-state cases also use that default.

`tools/signalacct_tail_artifacts.py controls` compiles the exact header from
**36d1e875e** as the no-fix negative control. It must fail the publication-count
proof and restore extra instructions. Both happened. This is stronger than
checking for a symbol or timing a loop. No server binary is executed by it.

| Finite synthetic trace, 20,000 passes | PRE: landed header | POST: fixed header | Delta |
|---|---:|---:|---:|
| Uniform 1 us boundaries, instructions/pass | 35.00295 | 16.29315 | -18.70980 (-53.45%) |
| Uneven boundaries/parks, instructions/pass | 35.00290 | 18.35505 | -16.64785 (-47.56%) |
| Uniform busy publications | 20,000 | 200 | -99.00% |
| Uneven busy publications | 20,000 | 1,622 | -91.89% |
| Clock calls, either trace including endpoints | 20,004 | 20,004 | 0 |
| Completed interval residual, either trace | 0 ns | 0 ns | 0 |

The uneven fixture uses eight 1 us intervals and two 41 us intervals per group,
plus a 250 us idle every 37 passes. **These are adversarial synthetic intervals,
not measured p8 passes.** Hardware counts cover the actual production `pass()`
helper with an injected clock, the common finite driver/clock stub and small
counter-boundary user-space overhead. Kernel instructions are excluded; counts
were not multiplexed or scaled. They exclude command execution/networking and
are not server instructions/op, cycles/op, IPC, throughput or latency results.
Raw JSON, disassembly and the failed negative-control log are in
`build/signalacct-tail/{instructions.json,*-unit.asm,nofix-unit.log}`.

Completed checks, all serverless on 112-127:

- Default release, off, pair and witness builds; GCC 13.3.0, default Makefile
  `-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, jemalloc and existing
  per-TU budgets. No compiler warning/error was found in these build logs.
- `build/flipctl-unit`: window proof, accounting proofs and controller model pass.
- `build/signalacct-core-unit signalacct`: actual physical picker exclusions and
  model trace pass. Its 1s/2s synthetic shutdown reports both pass the unchanged
  `tests/shutdown_report.py ... io` conservation checker.
- `tests/signalacct_controls.py`: all 29 parser/helper/invalid-state controls
  rejected; positive helper including the new default window passed.
- `tests/signalacct_live_test.py`: all five serverless driver/parser tests pass.
  **The live `tests/signalacct_live.py` boots remain mainline-only and pending.**
- Strict idle-token, unchanged EX/WB source and generated R7 parity checks pass;
  deliberate idle-timeout and stale-generated-envelope controls reject. The
  checker now accepts an explicit reference directory. Its old default was a
  stale pre-wbrule tree and correctly failed; the new run uses the frozen
  76ef4beae envelopes in `build/signalacct-tail/off`. EX/WB/ThreadCtx sources were
  separately verified byte-for-byte against that commit.
- Layouts in both namespaces remain Op336, Client1984, ThreadCtx1408, Shard1440,
  FlatStore944, Rob192, AtomicEntry144, Config624; IoLoop stays 7136. Only the
  stack-local accounting helper gains a publication-deadline word.

No gate rows were added or retired. Window checks run in the existing flip-model
row defined at `tests/gate.sh:1205` and collected at **2701**, before the quick
exit at **2838**. Delta **0 quick / 0 full**, counts remain **441 / 457**.
Neither EXPECT constant was edited. The private cell file emits no gate rows.

## Arms and byte controls

All arm paths below are relative to this worktree. Built release bytes correspond
to production commit `5b65ad5f4`; subsequent commits add only proofs/reporting.

| Arm | Purpose | .text bytes | SHA-256 |
|---|---|---:|---|
| `build/tomokv` | Fixed release accounting | 7,565,553 | `5eb2363894c4e119797f98711dcc7123617c6aaa3e296fde5bf4b3ac69f2222e` |
| `build/tomokv-off` | New tenure accounting compiled out; exact frozen 76ef4beae work-Span source envelopes | 7,554,956 | `df79e7a2b94d10ef45410a007be974932225f3c11fb011967943a92489669a88` |
| `build/tomokv-pair-post` | Fixed behavior in the paired envelope build | 7,769,968 | `f96942463a121ba5811255622fcda3e657dbf15e4481122be65e83a9d2fc6e04` |
| `build/tomokv-pad-a` | **PAD kind (A): behavior twin**, 76ef4beae work-Span behavior in PAIR-POST's identical text size/layout | 7,769,968 | `742f45fc01cfcff49e5f84f7530fd259889019735cf7e528df62849e743947b6` |
| `build/tomokv-tail-witness` | Correctness-only edge witness; actual first sweep forced as in the existing witness | 7,571,983 | `65d867d8ea6cbf6e74cdcccca1906e9b89979e7cd8a050aa728ef0b11c482904` |

The PAD is **not** a byte twin of the smaller release `build/tomokv`. It pairs
with `tomokv-pair-post`: two cold role-entry selector immediates differ, at file
offsets **422389** and **4187157**, one per database namespace. All other bytes,
sections, symbols and relocations match. A separate executable-byte corruption
is rejected and never executed. Both pair arms retain the closing-client fix;
legacy behavior has four cold endpoint clocks for the conservation counterexample.
The larger pair has **204,415** more text bytes than release POST, making the
release-vs-pair bridge below necessary. Release POST shrinks **7,099** text bytes
relative to the landed archive; same-layout behavior controls matter here.

Strict ordinary-path disassembly audit (unchanged address normalizer; not a
claim that relocated call/address bytes occupy the same file offsets):

| Scope | Landed 36d1e875e -> fixed | Historical 76ef4beae -> off |
|---|---:|---:|
| GET/SET handlers | 16/16 equal | 16/16 equal |
| Multi-key commands | 32/32 | 32/32 |
| Dispatch | 56/56 | 56/56 |
| Retirement | 16/16 | 16/16 |
| Scheduler | 60/64 | 62/64 |
| IO envelopes | 104/184 | 161/184 |
| Total | **284/368; strict no-op FAIL** | **343/368; strict no-op FAIL** |

Fixed changes all 80 intended IO run-loop bodies. The other four differences are
db0 split `execute<false,false>`, the two fused EX `run` bodies, and tomo's fused
`fused_pass_impl<32,true,false,false,true,void>` (`017/031/080/123.diff`). They are
compiler code-generation changes, not source scheduler edits, and are retained
as collateral differences requiring measurement. Do not describe the build as
otherwise byte-identical or infer rate parity from the matching handlers.

OFF's plain TCP/io_uring **2s overlap1 run-loop body passes that strict byte audit
against 76ef4beae in both namespaces**, as do its audited dispatch/retire/command paths.
The whole binary/path family is not: there are 23 other envelope differences
and two EX-run differences. Thus the explicit PAD pair is provided as the
fallback control. Audit receipts and every diff are under
`build/signalacct-tail/audit-{landed,off}/`; no difference was normalized away.

Archived references, read-only from `/home/user/Projects/bench-bins/`:

| Reference | .text bytes | SHA-256 |
|---|---:|---|
| `tomokv-headline-36d1e875e` | 7,572,652 | `b11a3f87d84b4ce60e6e504a914e00535d51cc2677fdab748e33de1f2930ae4a` |
| `tomokv-headline-76ef4beae` | 7,550,988 | `acf2ce338c6df41c5fa3032f0f4d06c9727318f35f287fb24624d966251dcc5e` |
| `tomokv-headline-ea45968a9` | 7,572,652 | Same full SHA-256 as 36d1e875e |

## Mainline measurement request — not run here

Use `tests/abbagate.py`, with **two separate ABBA blocks per comparison** for
**t03 and t04**, first against archived **36d1e875e**, then **76ef4beae**. Each
block retains A/B/B/A samples, medians, per-arm spreads, short GET p99.9, long
BITCOUNT p99.9/starvation evidence and achieved rates. Do not combine the two
rounds into a best-repeat result. No wide headline threshold or reported-only
PASS establishes recovery: fixed must improve over the landed regression and
return to historical parity within matched identical-byte spread in both cells
and rounds. If its spread remains elevated or intervals overlap ambiguously,
retain the result as unresolved.

`tests/signalacct_tail_cells.txt` has these exact cells plus **h05/h06**, their
split counterparts **h21/h22**, and **signalacct_get8/signalacct_set8** (2s,
rl0/overlap1/reorder0, GET/SET p8, 512 total connections). In this checkout h05
and h06 are **1s p32**, so they are retained as the requested unaffected-mode
guards rather than silently relabeled as 2s.

Collect fresh identical-byte **fixed-vs-fixed** nulls for all eight cells,
including the p8 split throughput cells. Also collect the historical references'
matched nulls. Pure throughput must stay within matched null/PAD spread and
must not breach the <=3% always-on cost limit against OFF. Keep the offered-load
plan identical across arms; a load-floor search/confirmation is allowed by the
existing instrument for the new p8 cells, not candidate-specific load tuning.

Required comparisons after the headline historical comparisons:

| A -> B | What it decides |
|---|---|
| OFF -> fixed release | Accounting overhead, including p8 2s throughput |
| PAD-A -> PAIR-POST | Fixed-vs-legacy accounting at identical text/data layout |
| Fixed release -> PAIR-POST | Pair transport/code-layout bridge; expect null parity |
| Archived 76ef4beae -> OFF, and -> PAD-A | Both legacy controls must remain at historical parity |

Use the gate's reviewed ABBA geometry: **server 0-31, no SMT, split16:16,
128 split shards**; fused cells use 256 shards. The committed measurement
registry contains only this 32-core ABBA shape. This is distinct from the
**8-core, shards16, split6:2** geometry required for the live correctness proof.
Record actual boot argv/geometry and retain the geometry of the mainline launch
evidence when comparing results; do not substitute a default server or invent
an unqualified eight-core ABBA configuration.

Concrete mainline commands for the headline request and nulls (quiet box only):

```bash
TAIL_COMMON=(--build-reference 0 --subset full --only t03,t04 \
  --cells tests/signalacct_tail_cells.txt \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --ports 7933-7940 --max-instances 16)
for ref in 36d1e875e 76ef4beae; do
  before="/home/user/Projects/bench-bins/tomokv-headline-$ref"
  rc=0
  taskset -c 0-111 python3 tests/abbagate.py "${TAIL_COMMON[@]}" \
    --candidate-binary "$before" --collect-null 1 \
    --output "build/signalacct-tail-mainline/null-$ref" || rc=$?
  if [ "$rc" -ne 3 ]; then exit 1; fi
  for round in 1 2; do
    rc=0
    taskset -c 0-111 python3 tests/abbagate.py "${TAIL_COMMON[@]}" \
      --reference-binary "$before" --candidate-binary build/tomokv \
      --null-result "build/signalacct-tail-mainline/null-$ref/results.json" \
      --output "build/signalacct-tail-mainline/tail-$ref-r$round" || rc=$?
    if [ "$rc" -ne 3 ]; then exit 1; fi
  done
done

ALL_IDS=t03,t04,h05,h06,h21,h22,signalacct_get8,signalacct_set8
rc=0
taskset -c 0-111 python3 tests/abbagate.py "${TAIL_COMMON[@]}" --only "$ALL_IDS" \
  --candidate-binary build/tomokv --collect-null 1 \
  --output build/signalacct-tail-mainline/null-fixed-all || rc=$?
if [ "$rc" -ne 3 ]; then exit 1; fi
```

Repeat the five control comparisons in the table for all eight IDs and two
blocks, with a fresh same-A null per reference. Partial selections/nulls return
exit3; inspect the actual validity/null/cell records, not just that exit code.
Retain short histograms and the separate long-command starvation guard. Report
cycles/op, IPC and instructions/op using mainline's qualified instrument for
each version. This checkout's optional `abba_profile` counters have a wider
window than central command counts: if used, retain its explicit
`approx_*_per_central_command` labels and interval offsets. Such profiles explain
the result; they cannot replace matched-load rate and tail verdicts.

| Mainline PRE vs POST table to fill | PRE | POST | PAD/null | Current status |
|---|---|---|---|---|
| t03/t04, two rounds vs 36d1e875e | pending | pending | pending | Not measured |
| t03/t04, two rounds vs 76ef4beae | pending | pending | pending | Not measured |
| h05/h06, split p32 and split p8 GET/SET | pending | pending | pending | Not measured |
| <=3% accounting cost vs OFF | pending | pending | pending | Not established |
| Live tenure conservation / explicit edge witness | legacy must fail conservation | pending | witness pending | Serverless checks pass |

Mainline live confirmation: run `tests/signalacct_live.py` against `build/tomokv`
and `build/tomokv-tail-witness` (the latter with `--edges`) across the existing
1s/2s, rl0/1, overlap0/1, reorder0/1, databases1/16 matrix, with shards16 and
split6:2 as enforced by the driver. Also retain the four existing epoll witnesses.
Use `build/tomokv-pad-a --legacy-control` for the four 1s/2s x db1/16 negative
controls: the failure must be completed-interval conservation, not a boot failure.
Do not use OFF for that live negative control; its compiled-out tenure rows
cannot prove a completed-interval failure. Missing windows must still reroll
fresh state, bounded by the unchanged driver's three attempts, then fail.

Serverless reproduction/build entry points:

```bash
taskset -c 112-127 make -j16 all build/flipctl-unit build/signalacct-core-unit
taskset -c 112-127 ./build/flipctl-unit
taskset -c 112-127 ./build/signalacct-core-unit signalacct
taskset -c 112-127 python3 tests/signalacct_controls.py
taskset -c 112-127 python3 tests/signalacct_live_test.py
taskset -c 112-127 python3 tools/signalacct_tail_artifacts.py controls
taskset -c 112-127 python3 tools/signalacct_tail_artifacts.py prepare
for arm in off pair witness; do
  taskset -c 112-127 make -C "build/signalacct-tail/$arm" -j16 all || exit 1
done
cp build/signalacct-tail/off/build/tomokv build/tomokv-off
cp build/signalacct-tail/pair/build/tomokv build/tomokv-pair-post
cp build/signalacct-tail/witness/build/tomokv build/tomokv-tail-witness
taskset -c 112-127 python3 tools/signalacct_tail_artifacts.py pair
taskset -c 112-127 python3 tools/signalacct_tail_artifacts.py manifest
taskset -c 112-127 python3 tests/signalacct_source_checks.py \
  --reference build/signalacct-tail/off --output build/signalacct-tail/source-proof
```

No performance win, live boot/gate result, or merge recommendation is inferred
from the serverless evidence. Mainline owns the requested measurement and live
conservation verdict. Stop point is this committed report and the built arms.
