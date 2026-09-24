# signalacct: implementation and measurement request

Status: **CODE BUILT; SERVERLESS PROOFS PASS; LIVE/GATE/PERFORMANCE PENDING MAINLINE.**
The strict cross-revision machine-code no-op check is **NOT PASS**: 80 intended IO envelopes and 10 collateral bodies differ. No shipping/performance verdict is claimed. The other material limitations below are the expanded-layout PAD pair, unavailable reorder AUTO, and missing reviewed 8-core/cycles instrument support at launch.

Lane: `/home/user/Projects/cx-signalacct`, branch `cx-signalacct`, reference `3e734cf2e00c087604fcaf145459522e6fa81f05`. Production source and proof tools are committed through `036d42ac4`; this document is committed separately. No server, load generator, gate or performance measurement was run. All builds and executable serverless checks used CPUs **112-127**, builds with **make -j16**. No push.

## Verified diagnosis and scope

Anchors below were rechecked against the actual launch revision, rather than accepted from the older 705cddec audit. Frozen launch source is in `build/signalacct-pre/`.

| Launch/reference anchor | Verified fact | Candidate anchor/change |
|---|---|---|
| `src/core/io_loop.h:523`, `:563`, `:572`, `:582`, `:620` | Prologue precedes the busy Span; three consumers reuse its start cut. | `src/core/io_loop.h:504`, `:525`, `:527`, `:574`, `:584`, `:622`: tenure entry, one cut at each entered pass, reused by all three consumers. |
| `src/core/io_loop.h:670`, `:675`, `:687`, `:695` | Busy Span closes before did-submit and sweep-submit; both continues leave those intervals unbooked. | `:672`, `:678`, `:695`, `:706`: all elapsed time reaches the next cut or final flush. |
| `src/core/io_loop.h:702` through `:737` | Idle includes park publication/recheck, epoll dispatch or ring wait, resume and blocked-state clear. It is not just syscall sleep. | `:722` through `:772`: classification and ordering preserved. Token comparison against PRE passes; changing epoll timeout 50 to 0 is rejected. |
| `src/core/io_loop.h:739`, `:757` | Read-local teardown and AOF shutdown follow loop exit. A cut carried into a later IO role would charge EX time. | `:774` finishes once before teardown; history append follows QSBR park/disarm at `:785`. Each run-loop invocation constructs fresh state. |
| `src/core/signal.h:205-206` | Span constructor and destructor each read CLOCK_MONOTONIC. | IO busy Span removed; independent idle/features retain their clocks. `src/core/signalacct.h` is the single authoritative accounting implementation. |
| `src/core/flip_policy.h:38`, `src/core/flipctl.cc:752` | Historical 23.5 s missing out of 40 s and wall-minus-idle model rationale exist. | Historical evidence is labeled **2026-09-06**, explicitly not reproduced by this lane. Model remains wall-minus-idle. |
| `src/core/server.h:587`, `:597`, `:1721`, `:1738` occupancy fold and physical role planning | The old comment saying wall-idle was wrong: code uses busy/(busy+idle). Physical victims can change. | Corrected comment at `:595`; actual fold at `:599` and picker exclusions/ordering at `:1738` onward are unchanged. |
| `tests/r7shadow_sync.py:70`, `src/core/reorder.cc:783`, `:859`, `:998` | The active generator owns R7. The launch tree has already removed AUTO in `63117343f`. | Exact active sampling needle asserted at `tests/r7shadow_sync.py:76`; R7 regenerated with `--write`. IO cut at `src/core/reorder.cc:822`; original sampling site at `:879`. |

`tests/config_parser_test.cc:451` rejects `--reorder -1` at launch. The requested AUTO matrix cannot boot on this reference; it is **UNAVAILABLE AT REFERENCE**, not a skipped successful test. No AUTO/controller was restored. The active 100 us sampling gate and its call-site frequency are preserved; the timestamp moves earlier to the pass boundary as requested. Cached monotonic milliseconds move to that same cut. Realtime expiry clocks remain separate.

Only the IO accounting mechanism changes production behavior. No EX clock optimization, role-gate load change, cache-line repacking, counter cleanup, threshold changes, sampling-rate changes, new runtime knobs or controller resets were added. `src/core/ex_loop.h` is byte-identical as source; all five generated R7 EX methods are identical as source. The authoritative helper is in one file; canonical and generated call sites, cold reporting and tests use it.

The already-landed **lbfix** merge `7cc0607da` / lane `9818de570` is an ancestor of PRE. Its signal fold, key/client sampling windows, effective-sample rules, thresholds and guards are retained. This lane changes the IO busy input to that inherited occupancy fold and therefore can change its physical role choice. Key-load weights and model demand formulas are unchanged.

## Exact interval, clocks and independent evidence

`IoTenure` owns **[begin_ns,end_ns)** of one `IoLoop::run_loop` invocation (also its generated R7 invocation). Entry is before read-local setup, role-entry R7 binding and the first pass. Final cut is after the while condition detects stop/role exit and before read-local teardown, close draining, epoll teardown and persistence shutdown. Those explicit cold teardown operations and all EX tenures are outside this interval. Zero entered passes still have entry/final cuts and a record. A stop during park first destroys the unchanged idle Span, then books the final partial interval.

For consecutive accounting cuts C0,C1 and the owner's idle snapshots I0,I1 at those same cuts:

```
elapsed = C1 - C0
idle_delta = I1 - I0
busy_delta = elapsed - idle_delta
```

The next pass charges all work since the previous cut, including prologue, dispatch, submit/reap, sweeps, continue edges and non-idle empty-pass work. Shutdown/role exit takes one final cut and books the last partial interval exactly once. A later IO invocation snapshots fresh counters/cuts; no timestamp survives an EX tenure. The helper has no clock-reading destructor.

CLOCK_MONOTONIC must not go backwards; only the owner writes these counters. The helper rejects backwards cuts, idle resets/wrap, idle_delta > elapsed, busy accumulation overflow and double finish by aborting with `invalid IO accounting cuts/counters`. It never clamps a negative difference. 64-bit nanoseconds span roughly 584 years; this assumption is checked where deltas/additions occur. The preexisting Span's idle addition is unchanged; a wrap is detected at the following pass/final cut. Whole-tenure differences cannot overflow if the monotonic/no-wrap checks hold.

| Accounting clocks in a branch | PRE | POST | Independent feature clocks |
|---|---:|---:|---|
| Busy did-submit pass, including its continue | 2 | 1 | Unchanged |
| Sweep-work/submit pass, including its continue | 2 | 1 | Unchanged |
| No-work pass reaching idle Span, including recheck that avoids sleep | 4 (busy 2 + idle 2) | 3 (cut 1 + idle 2) | Unchanged |
| Actual parked pass, including epoll callbacks/resume | 4 | 3 | Unchanged |
| Zero-pass tenure | 0 | 4 cold endpoint cuts | No normal pass |
| Per nonempty IO tenure, in addition to the per-pass counts above | 0 | 4 (entry, begin, end, exit) | No carry across EX |

CPU sampling, realtime/deadline clocks, fused execution clocks and EX timers are outside this count and unchanged. Bookkeeping stores are **not reduced**: the owner still updates busy_ns once per pass (plus final flush), and the helper maintains local stack cuts. No claim of reduced producer RFO/coherence traffic follows from deleting one clock call. LoopSignals/ThreadCtx producer-consumer placement is unchanged.

Cold shutdown evidence is `threads[].io_tenures[]`, plus human `io_tenure tN/index ...` rows. Each record has raw uint64 busy/idle, independently read monotonic **entry_ns and exit_ns**, inner accounting cuts **begin_ns and end_ns**, role_exit/stopped flags and diagnostic edge counters. Neither denominator is obtained from busy+idle. Existing lifetime raw counters can include EX; only the per-tenure IO deltas are compared with IO wall. Final-role labels never supply an IO denominator.

The acceptance rule, fixed **before any live run**, is:

```
inner_wall = end_ns - begin_ns
outer_wall = exit_ns - entry_ns            # independent endpoint reads
endpoint_uncertainty = (begin_ns-entry_ns) + (exit_ns-end_ns)
busy_ns + idle_ns == inner_wall            # exact integer ns, no rounding
abs(outer_wall-busy_ns-idle_ns) <= endpoint_uncertainty
outer_wall-busy_ns-idle_ns == endpoint_uncertainty
```

Ordered/nonoverlapping endpoints and an actual exit reason are also required. There is no percentage allowance or widened tolerance. The outer check is evidence from extra endpoint clock calls, not from a fabricated wall counter; the inner equality catches a dropped window even if unrelated EX time exists in the lifetime row. Open/live DEBUG snapshots remain asynchronous approximations and are not used for exact conservation.

History is owner-appended at tenure exit **after** read-local QSBR disarm/park; shutdown copies it only after join. Cold history stores are appended to Server, aligned after all preexisting members. No normal pass touches those vectors. Release edge fields stay zero, with no per-pass diagnostic stores; the separate witness build enables them. The retained per-tenure history grows with role transitions (80-byte records plus vector capacity); it is not a bounded aggregate and its cold allocation/transition cost must be included in the frequent-transition campaign.

## Consumer-impact inventory

The tracked source/test/tool search and scratch parser search are saved as `build/signalacct-proof/full-time-consumer-inventory.txt`, `final-consumer-anchors.txt`, and `all-parser-uses.txt`. The table includes indirect consumers and historical scratch tools, not only field-name matches.

| Consumer / anchors in candidate | Dependency and expected effect |
|---|---|
| `src/core/io_loop.h:504`, `:527`, `:774`; generated `src/core/reorder.cc:790`, `:822`, `:1069` | Writers of corrected IO busy; idle boundaries unchanged. Later publication is at the next cut/final flush. |
| `src/core/io_loop.h:574`, `:584`, `:622`; R7 `:869`, `:879`, `:917` | Existing cached-time/depth/age consumers use pass_ns. Sampling cadence/site unchanged; cut moves to pass start. |
| `src/core/ex_loop.h:801`, `:824`, `:840`; R7 EX copies | Distinct productive/empty-pass accounting and idle writers unchanged. No assertion that EX busy+idle covers an IO denominator. |
| `src/cmd/lbsignals.cc:50`, `:81`, `:148`, `:168` | Copies per-thread raw values and role rollups. Corrected IO/fused busy increases for formerly dropped work. Prefix/column grammar unchanged. Lifetime rollups still classify by current role, so they are not per-tenure conservation evidence. |
| `src/core/lbsignals.h:105`, `:109`, `:143` | busy/(busy+idle), busy/ops and ratio_star change. With ops/idle fixed and missing IO work restored, IO busy fraction/ns-per-op rise and ratio_star generally shifts toward IO. ratio_star is telemetry, not the flip placement model. |
| `src/cmd/lbsignals.cc:201`, `:228`, `:273`, `:313` | DEBUG derived row and INFO loadbalance export changed busy fractions/ns-per-op/ratio_star; occupancy min/max also change. |
| `src/core/server.h:595` through `:610` | Actual EWMA occupancy fold uses busy/(busy+idle), alpha .25 after priming. Corrected IO occupancy can change. No new reset/masking. |
| `src/core/server.h:1738` through physical RoleUnit sort/selection | **Indirect controller effect:** chooses physical IO->EX or EX->IO threads from occupancy. Coordinator, AOF writer and Unix owner remain excluded (including SMT peer logic). Model target can stay the same while physical victims change. |
| `src/core/flipctl.cc:765`, `:775`, `:780`; `src/core/flip_policy.h:199` | Placement MODEL uses controller wall minus idle, with ops establishing progress. Holding ops, wall and idle fixed produces identical traces. Idle/headroom semantics unchanged; real physical feedback still needs live revalidation. |
| `src/core/flipctl.cc:653`, `:786`, `:1020`; `src/core/flipctl.h` ThreadMeasure | Stores busy_ns in currently unread ThreadMeasure fields. Not a demand input. No cleanup of those fields in this lane. |
| `src/core/shutdown_report.h:167`, `:289`, `:407` | Existing raw lifetime exports change; human lifetime values still round to milliseconds. |
| `src/core/shutdown_report.h:172`, `:294`, `:417` | New raw per-IO-tenure evidence and independent endpoints; JSON schema remains 1 with additive fields. |
| `tests/_lib.py:229`, `:239`, `:264` | Stable thread/rollup parser retains changed counters and derived fields. All callers keep the same grammar. Callers reading only routing/depth/feature counters are unaffected. |
| `tests/_gate_process.py:91`, `:204` | Parses busy/idle prefix; generic final JSON/stuck parser tolerates the additive fields. Dedicated conservation check is in shutdown_report/lbsignals below. |
| `tests/perf_gate.py:150` through `:165` | Derives raw busy fractions and saturation checks; affected signal must be revalidated. Do not compare stale busy-based pins as if unchanged. |
| `tests/abbagate.py:1137`, `:1153` | busy_between validates and computes raw fractions; busy_deltas retains raw deltas. Changed raw diagnostics, unchanged rate/tail score computation. |
| `tests/abba_saturation.py:28`, `:58`, `:102`, `:171`, `:226` | Parses raw times and retains busy deltas; saturation uses min(wall-idle, CPU), plus progress/ownership and central-window evidence. Numeric signal formula unchanged. Comments now label the historical hole. Not proof that the measurement instrument remains calibrated. |
| `tests/abba_instrument.py`, `tests/gate_measurements.py`, `tests/abba_evidence_test.py`, ABBA self-tests/fixtures | Transitive fingerprint/evidence replay includes saturation/runner bytes and retained counters. Re-freeze after this signal change; old nulls are not automatically valid. No numerical gate constants changed. |
| `tests/lbsignals.py:150`, `:158`, `:179`, `:199`; new `--shutdown` entry | Existing advancement/range/INFO checks remain; shutdown mode requires independent conservation using the common parser. Live advancement/idle battery is PENDING MAINLINE. |
| `tests/shutdown_report.py:33` / clean/io; `tests/gate.sh:1455` and all shutdown_clean callers | Existing clean checks now require IO evidence. Same gate emission rows; no new public row. `--edges` additionally requires entered submit/sweep/park and split-role reentry. |
| `tests/gates_test.py` | Synthetic fixed-prefix thread rows; no new runtime time formula. Existing fixtures keep grammar. |
| `tests/spinprobe.py:143` and _lib feature users | Parse LBSIGNALS but use wake/spin/iteration or feature fields, not busy-based demand. No semantic change to their selected counters. |
| `tests/r7shadow_sync.py:74`; `tools/reorder_sync.py` alias | Exact sampling needle now pass_ns, generator parity required. AUTO absent at launch. No alternate handwritten generated scheduler. |
| New `tests/signalacct_{checks,controls,core_checks,core_controls,live,live_test,source_checks,byte_checks}` and `tools/signalacct_artifacts.py` | Accounting, role, parser, source/ELF and arm mapping proof consumers; described below. |
| `scratch/spread.py:36` and fraction fold | Changed per-role occupancy/spread plots; role-change boundaries skipped. Historical scripts are not the acceptance instrument. |
| `scratch/model.py:34`, `scratch/spin.py:34`, `scratch/summ.py:36` | Raw busy/corrected busy/ns-op/CSV diagnostics change. Their old labels suggesting busy-based math is the currently shipped controller input are historical and must not support a new claim. No unrelated rewrite. |
| `scratch/flipfp/multi.sh:59`, `:86` | Fixed fields 8/9/10 and raw fraction/CPU-minus-busy diagnostics change; grammar stable. |
| `scratch/report2.py:317`, `:322` | Static historical report of the old missing window; not a new measurement or runtime parser. |
| `tools/lbfix_artifacts.py` | Source anchor for occupancy negative controls, not a runtime time parser. Inherited lbfix implementation/guards retained. |

## Serverless proof results and negative controls

All executions below were pinned to 112-127. Logs and mutants are under `build/signalacct-proof/`; defective builds are not production arms. The deliberately byte-corrupted artifacts are mode 0600 and **were never executed**.

| Positive proof | Exercised state / exact assertion | Result and control |
|---|---|---|
| Actual `IoTenure<Clock>` via `tests/signalacct_checks.h` | Entry/prologue, did-submit, sweep-submit, idle, no-work, final tail. Cuts 101,110,150,180,210,220,233; idle=10; busy=122; inner wall=132, outer=134, bracket=2. Five pass clocks plus four cold cuts. | PASS; corresponding omit/double/extra-clock mutants below fail named assertions. |
| Same helper IO->EX->IO | IO1=19 ns; intervening EX busy400/idle100; IO2=29 ns with busy14/idle15, stop during park. Fresh IO state excludes EX and sums each tenure once. | PASS; carry-ex and omitted park-final-flush fail. |
| Same helper zero-pass tenure | begin2001/end2007, busy6/idle0; role exit plus stop. | PASS; omit-zero-flush fails. |
| Invalid-state controls | Backward clock, idle reset, idle > elapsed, uint64 busy overflow, double finish. | All five abort as required; core dumps disabled. |
| Actual C++ ShutdownReport construction/emission | 1s eight IO histories; 2s final IO with IO->EX->IO, final EX with prior IO, pure EX with empty IO history. Real helper and real human/JSON emitters. | PASS through both shutdown_report clean and lbsignals --shutdown. `report-1s.log`, `report-2s.log`; synthetic clocks, no live claim. Parser mutations below reject altered evidence. |
| Actual `FlipController::sample_role_demand` + policy | Same ops/wall/idle sequence, different busy; stable 6:2 then real idle-share shift to 5:3. | PASS, PRE trace equals POST exactly. Busy-model mutant fails stable choice. |
| Actual Server fold and `flip_begin` picker | Independent 1000 ns cuts, known idle values; corrected occupancy ordering; coordinator/AOF/Unix exclusions armed. | PASS; legacy fold and each removed exclusion fail named assertions below. |
| Live-driver serverless mocks | Exact shards16/6:2 grammar; healthy and boot-failed legacy controls cannot be accepted; missing edge window gets exactly three fresh attempts, a conservation failure is immediate. | PASS, 3 unit tests. No actual Popen/socket server activity in mocks. Live results still pending. |
| Source/generator invariants | PRE idle tokens/callback order identical; EX header exact; five R7 EX methods identical; active IO sampler needle and generated envelopes match. | PASS; changed epoll timeout and stale generated /1001 sampling are rejected. |
| Layout probe, both namespaces | All locked sizes, IoLoop size/stride and listed hot/cold-existing offsets exactly match PRE. | PASS; copied offset inventory altered by eight bytes is rejected. |
| Existing strict ELF checker control | POST vs itself must be 336/336; flip one GET executable byte in a separate copy. | PASS identity; negative REJECTED exit1 at exactly cmd_get<false,true>. |
| Expanded pair all-byte/ELF check | Only the two named selector immediates may differ. | PASS sections/symbols/relocations and all other bytes; extra executable-byte corruption REJECTED. |
| Existing R7 scheduler mutants | no-shadow, no-clear, no-bound, no-successor-clear | All four REJECTED by their existing named state assertions. |

The assertion/control receipts below give the exact failure, not a generic nonzero exit. Parser controls use real role-separated records with busy112/idle20/inner132; helper controls use busy122/idle10/inner132. These are intentionally separate exact fixtures.

| Throwaway control / exercised state | Exact failed assertion or evidence | Result |
|---|---|---|
| `legacy-dropped-window` | shutdown report: t0/IO0: completed interval is not exact (busy+idle=92 inner_wall=132) | REJECTED |
| `unflushed-tail` | shutdown report: t0/IO1: completed interval is not exact (busy+idle=119 inner_wall=132) | REJECTED |
| `idle-subtracted-twice` | shutdown report: t0/IO0: completed interval is not exact (busy+idle=112 inner_wall=132) | REJECTED |
| `carry-ex-time` | shutdown report: t0/IO1: completed interval is not exact (busy+idle=400 inner_wall=132) | REJECTED |
| `missing-row` | shutdown report: t0: missing independent IO tenure row | REJECTED |
| `unentered-io` | shutdown report: t0: IO role never entered an accounted tenure | REJECTED |
| `overlapping-endpoints` | shutdown report: t0/IO1: non-monotonic/overlapping tenure endpoints | REJECTED |
| `no-exit-reason` | shutdown report: t0/IO0: neither role exit nor shutdown fired | REJECTED |
| `no-did-submit` | shutdown report: required did-submit/sweep-submit/park/IO->EX->IO window never opened: {'did_submit': 0, 'sweep_submit': 2, 'park': 2, 'role_exit': 1} mixed=True | REJECTED |
| `no-sweep-submit` | shutdown report: required did-submit/sweep-submit/park/IO->EX->IO window never opened: {'did_submit': 4, 'sweep_submit': 0, 'park': 2, 'role_exit': 1} mixed=True | REJECTED |
| `no-park` | shutdown report: required did-submit/sweep-submit/park/IO->EX->IO window never opened: {'did_submit': 4, 'sweep_submit': 2, 'park': 0, 'role_exit': 1} mixed=True | REJECTED |
| `no-role-edge` | shutdown report: required did-submit/sweep-submit/park/IO->EX->IO window never opened: {'did_submit': 4, 'sweep_submit': 2, 'park': 2, 'role_exit': 0} mixed=False | REJECTED |
| `mixed-lifetime-used-as-io` | shutdown report: t0/IO0: completed interval is not exact (busy+idle=644 inner_wall=132) | REJECTED |
| `lifetime-counter-reset` | shutdown report: t0: role-separated IO totals exceed lifetime counters | REJECTED |
| `omit-entry` | FAIL signalacct: entry/prologue cut | REJECTED |
| `omit-no-work` | FAIL signalacct: no-work non-idle prologue/sweep is booked | REJECTED |
| `omit-zero-flush` | FAIL signalacct: zero-pass tenure final flush | REJECTED |
| `omit-stop-park-flush` | FAIL signalacct: IO->EX->IO excludes EX and stop-during-park flushes | REJECTED |
| `omit-submit` | FAIL signalacct: did-submit elapsed is booked at next boundary | REJECTED |
| `omit-sweep` | FAIL signalacct: sweep-submit elapsed is booked at next boundary | REJECTED |
| `omit-final-flush` | FAIL signalacct: final partial interval flushed once | REJECTED |
| `double-idle` | FAIL signalacct: idle subtracted exactly once | REJECTED |
| `carry-ex` | FAIL signalacct: IO->EX->IO excludes EX and stop-during-park flushes | REJECTED |
| `extra-clock` | FAIL signalacct: five passes use five clocks plus four cold endpoint cuts | REJECTED |
| `invalid-clock` | invalid IO accounting cuts/counters; SIGABRT (core dumps disabled) | REJECTED |
| `invalid-idle-reset` | invalid IO accounting cuts/counters; SIGABRT (core dumps disabled) | REJECTED |
| `invalid-idle-excess` | invalid IO accounting cuts/counters; SIGABRT (core dumps disabled) | REJECTED |
| `invalid-busy-overflow` | invalid IO accounting cuts/counters; SIGABRT (core dumps disabled) | REJECTED |
| `invalid-double-finish` | invalid IO accounting cuts/counters; SIGABRT (core dumps disabled) | REJECTED |

| Core mechanism control / test state | Exact failed assertion | Result |
|---|---|---|
| `legacy-occupancy` / `signalacct-post` | corrected occupancy uses complete IO wall | REJECTED, exit 1 |
| `model-uses-busy` / `signalacct` | fixed model trace holds stable 6:2 | REJECTED, exit 1 |
| `no-coordinator-exclusion` / `signalacct-post` | coordinator excluded despite lowest occupancy | REJECTED, exit 1 |
| `no-aof-exclusion` / `signalacct-post` | AOF writer excluded despite lowest occupancy | REJECTED, exit 1 |
| `no-unix-exclusion` / `signalacct-post` | unix owner excluded despite lowest occupancy | REJECTED, exit 1 |

Receipts: `controls/results.json` (29 rejects), `core-controls/results.json` (5 rejects), `byte-controls/results.json`, `source-proof.json`, `layout.json`, `pad-a.json`. These are all serverless outcomes. Mechanism-edge checks in real processes, SET/GET traffic/RYOW checks, real role-transition completion and final parked shutdown remain **PENDING MAINLINE**. The built legacy PAD is the live negative control for dropped-window accounting; erasing each witness edge in a copied final JSON is the corresponding missing-window control, already rejected serverlessly. Never accept a boot error as the legacy accounting failure.

Reproduction commands (serverless only):

```bash
taskset -c 112-127 make -j16 all build/config-parser-test build/flipctl-unit build/signalacct-core-unit build/r7shadow-unit build/reorder-unit
taskset -c 112-127 build/config-parser-test
taskset -c 112-127 build/flipctl-unit
for row in signalacct route drain config; do taskset -c 112-127 build/signalacct-core-unit "$row"; done
taskset -c 112-127 build/r7shadow-unit
taskset -c 112-127 build/reorder-unit
taskset -c 112-127 python3 tests/signalacct_controls.py
taskset -c 112-127 python3 tests/signalacct_core_controls.py
taskset -c 112-127 python3 tests/signalacct_live_test.py
taskset -c 112-127 python3 tests/signalacct_source_checks.py
taskset -c 112-127 python3 tests/signalacct_byte_checks.py
taskset -c 112-127 python3 tests/r7shadow_mutants.py
taskset -c 112-127 python3 tests/abba_instrument.py --self-test
```

Completed: release, pair and witness builds; config/model/core route-drain-config/R7/reorder units; actual helper with ASAN+UBSAN; actual report emitters/parsers; all controls above; instrument self-tests (5); `git diff --check`. No compiler warning/error in final release build log. Full live ASAN/TSAN, server boots, batteries, gate and performance are **PENDING MAINLINE**. The core unit fixtures instantiate real classes without workers/listeners; they do not establish boot/network correctness.

### Fixed model and physical selection traces

```
signalacct model PRE phase=0: share=0.750000000 target=6 move=0
signalacct model PRE phase=1: share=0.625000000 target=5 move=1
signalacct model POST phase=0: share=0.750000000 target=6 move=0
signalacct model POST phase=1: share=0.625000000 target=5 move=1
signalacct physical PRE pinned=1: occ[1]=0.500000 occ[2]=0.600000 victim=1 excluded=coordinator,AOF,unix
signalacct physical POST pinned=1: occ[1]=0.900000 occ[2]=0.600000 victim=2 excluded=coordinator,AOF,unix
signalacct physical POST pinned=0: occ[1]=0.900000 occ[2]=0.600000 victim=5 excluded=coordinator
PASS core concurrency signalacct (state assertions fired)
```

Each phase has four 1-second samples, 1000 ops/thread/sample. Stable idle=.1 s on all eight threads gives IO work 5.4/total 7.2=.75. Shifted IO idle=.5 s (EX remains .1 s) gives IO work 3/total 4.8=.625. PRE IO busy is .1 s/sample; POST IO busy is wall-idle. The actual sampler returns identical demand/headroom sequences and the policy makes identical model choices.

Physical fixture idle=[999,100,400,200,999,999,100,100] ns, all independent walls 1000 ns. PRE drops 800 ns of tid1 work: occupancy1=100/(100+100)=.5, less than tid2=.6. POST occupancy1=.9, so eligible tid2 is chosen. Tid0 coordinator, tid5 AOF writer and tid4 Unix owner have deliberately lower occupancy and are excluded. Unpinning AOF/Unix yields tid5 by the existing reverse-id tie rule. `flip_begin` performs its own second fold; with no new deltas this applies the existing .75 decay to all occupancies, preserving ordering. Printed occupancies are the first known fold. No zero-delta behavior was changed to mask the result.

This is a PRE/POST **signal replay**, not an assertion that the separate PRE executable ran a controller campaign. Live stable-anchor, shift-convergence, steady-state oscillation and cost-gate traces are **PENDING MAINLINE**.

## Artifact identities, layouts and PAD meaning

GCC: `g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`. Default production flags `-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, jemalloc enabled, existing per-TU inlining budgets unchanged; both database namespaces linked. PRE was built before edits with `taskset -c 112-127 make -j16 BUILD_ROOT=build/signalacct-pre`. Full logs retain compile/link commands.

| Arm | .text bytes | SHA-256 |
|---|---:|---|
| `build/tomokv-signalacct-pre` | 7,445,436 | `f4d14845572ed808a802e6f8040d8025b43c3b3de0cd07d42770ab768301f014` |
| `build/tomokv-signalacct-post` | 7,468,364 | `60264c145bf849296b7d4590647d47debfce73b7e248589401ce655c391137eb` |
| `build/tomokv-signalacct-pair-post` | 7,678,569 | `022ca5bd10a706ad8fa490294b0cf4e0a81f9c335eaf3356cfd2c00098cb529f` |
| `build/tomokv-signalacct-pad-a` | 7,678,569 | `849351cfee2ae1d0077be3ea81c2be68d628684eb312125ef328f72d8d1aded9` |
| `build/tomokv-signalacct-witness` | 7,473,741 | `a898b574c7e72c89fcb5cdc75cff4c6a30b9699e9a858650985241b7d447d2b9` |

```
60264c145bf849296b7d4590647d47debfce73b7e248589401ce655c391137eb  build/tomokv
```

Arm preparation/build commands (already completed, pinned; these never run a server):

```bash
# PRE archive/objects were frozen at launch; do not rebuild PRE from the modified source tree.
taskset -c 112-127 python3 tools/signalacct_artifacts.py prepare-pair
taskset -c 112-127 make -C build/signalacct-pair -j16
cp build/signalacct-pair/build/tomokv build/tomokv-signalacct-pair-post
taskset -c 112-127 python3 tools/signalacct_artifacts.py pair \
  build/tomokv-signalacct-pair-post build/tomokv-signalacct-pad-a
taskset -c 112-127 python3 tools/signalacct_artifacts.py prepare-witness
taskset -c 112-127 make -C build/signalacct-witness -j16
cp build/signalacct-witness/build/tomokv build/tomokv-signalacct-witness
taskset -c 112-127 python3 tools/signalacct_artifacts.py dump \
  build/tomokv-signalacct-pre build/tomokv-signalacct-post \
  build/tomokv-signalacct-pair-post build/tomokv-signalacct-pad-a build/tomokv-signalacct-witness
```

`build/tomokv` and release POST are identical. Every arm has `build/signalacct-proof/<arm-basename>.sections-relocations.txt` (`readelf -WSr`) and `.disassembly.txt` (`objdump -drwC`). `arms.json`, `source-bindings.json`, `compiler.txt`, `reference.txt`, `pre-instrument.sha256` bind the source, compiler and artifacts. All binaries/dumps remain in this worktree's ignored build directory; hashes/recipe are in this committed request.

Locked layouts in PRE and POST, in both namespaces: **Op336, Client1984, ThreadCtx1408, Shard1440, FlatStore944, Rob<64>192, AtomicEntry144, Config624**. IoLoop remains 7136 bytes, align 8; its existing offsets remain srv392, self400, ring2760, wb6200, fused_executor7072, client_work_fences7080. Existing Server cfg/thread/shard-owner/signal/client-work/last-member offsets also match (`layout.json`). Only cold Server extent grows 3072 bytes: multidb 105536->108608, db0 105152->108224; align 64 unchanged. No hot per-thread word, per-operation store or normal-pass clearing was added.

**Kind-A behavior twin:** `tomokv-signalacct-pad-a` is PRE IO work-Span behavior in the **paired POST's** exact text/data layout. The pair contains canonical and generated PRE envelopes extracted verbatim from frozen PRE, plus current POST envelopes. A noinline cold role-entry selector chooses which to enter. Removing the four cold endpoint/readout additions from the legacy body reproduces the original PRE body exactly (`pair-source.json`). Legacy retains all old busy start consumers; `finish(...,false)` only records endpoints and never books the missing final interval. It therefore remains a live negative control.

Both pair arms include the same independent diagnostics/storage; their only differences are two `mov eax,1` -> `mov eax,0` immediates (one per database namespace). `pad-a.json` records offsets 422341 and 4139541. Sections, symbols, relocations and every other byte match. They are **not byte-identical to release POST**: the pair adds dormant alternate envelopes and a cold selector. Mandatory transport check: measure release POST vs PAIR-POST. No gain can be attributed solely to accounting if that bridge itself moves. Also compare frozen PRE vs release POST and PAD-A vs PAIR-POST; PAD-A should stay at stable-reference parity while POST moves in the claimed regime. The existing R7 PAD was not reused.

Release POST .text grows **22,928 bytes**. A requested kind-B “candidate behavior plus padding restoring PRE's text size” cannot be constructed by adding padding to this larger candidate: restoring PRE would require deleting code, not padding. **No kind-B arm is supplied or mislabeled.** The exact-layout expanded A pair and release transport check are the supplied controls; they do not erase the release-layout limitation or satisfy a demand for a separate valid B arm. This is an explicit remaining acceptance constraint for mainline.

Witness arm is correctness-only: it enables local did-submit/sweep-submit/park witnesses and defers ordinary ready service until a real sweep has serviced work. Witness counters follow actual submit_and_reap calls; park counts precede actual waits. Fresh boots bound rearming. It is never a performance arm and its forced scheduling does not ship.

### Strict no-op audit limitation

`tests/r7shadow_noop.py PRE POST ...` exits1: **246/336** selected normalized bodies identical. 80 changed ordinary IO-loop bodies are intended. The remaining **10 collateral bodies** are: db0 ExLoop<false>::execute<false,false>; tomo ExLoop<false>::run; tomo ExLoop<true>::run; db0 ExLoop<false>::run; tomo fused_pass_impl and fused_sweep_impl for `<32,true,false,false,true>`; three tomo flush_ready specializations; db0 drain_tasks_unmasked<false,...>. Exact diff files are `noop-final/{017,022,031,071,123,124,133,135,137,237}.diff`.

All selected command bodies 16/16, multikey 32/32, dispatch 56/56 and retire 16/16 are identical. This does **not** prove zero main-command performance regression. The collateral differences include inlining/register/layout changes and remain unresolved. The checker/whitelist was not weakened and compiler budgets were not retuned in the submitted diff. POST-self identity 336/336 plus the one-byte corruption control validates the audit itself; it does not turn this PRE/POST failure into a pass.

## Mainline live proof commands — NOT RUN BY LANE

Run on a scheduled quiet box after lane compilation has stopped. These commands start servers and therefore belong only to mainline. Driver fixes geometry to **8 cores 0-7, shards16, 2s ratio6:2**; 1s uses the same cores/shards. Both databases1 and16 are included. Each run is productive SET/GET traffic, observed kernel park, split manual6:2->3:5->6:2 with productive phases, then TERM during observed park. Exact argv and kernel park evidence are retained per attempt. Driver owns/cleans up only its own process.

```bash
# Clean release conservation, then directed witnesses, all supported cells.
for arm in post witness; do
  edge=()
  if [ "$arm" = witness ]; then edge=(--edges); fi
  for mode in 1s 2s; do
    for rl in 0 1; do for ov in 0 1; do for ro in 0 1; do for db in 1 16; do
      taskset -c 8-111 python3 tests/signalacct_live.py \
        --binary "build/tomokv-signalacct-$arm" \
        --output "build/signalacct-mainline/live-$arm-$mode-$rl-$ov-$ro-db$db" \
        --cores 0-7 --mode "$mode" --read-local "$rl" --overlap "$ov" \
        --reorder "$ro" --databases "$db" --net-io uring "${edge[@]}" || exit 1
    done; done; done; done
  done
done

# Legacy accounting must fail completed-interval equality, in both modes/runtime variants.
for mode in 1s 2s; do for db in 1 16; do
  taskset -c 8-111 python3 tests/signalacct_live.py \
    --binary build/tomokv-signalacct-pad-a \
    --output "build/signalacct-mainline/legacy-$mode-db$db" \
    --cores 0-7 --mode "$mode" --read-local 1 --overlap 1 --reorder 1 \
    --databases "$db" --legacy-control || exit 1
done; done

# Callback-in-idle guards: real epoll path, all-on and all-off, both modes.
for mode in 1s 2s; do for knobs in 0 1; do
  taskset -c 8-111 python3 tests/signalacct_live.py \
    --binary build/tomokv-signalacct-witness \
    --output "build/signalacct-mainline/epoll-$mode-$knobs" \
    --cores 0-7 --mode "$mode" --read-local "$knobs" --overlap "$knobs" \
    --reorder "$knobs" --databases 16 --net-io epoll --edges || exit 1
done; done
```

A missing did/sweep/park/role/reentry witness re-arms on a **fresh process**, at most three attempts, then fails. A conservation error, wrong SET/GET reply, failed FLIP or boot failure fails immediately. No SKIP and no tolerance widening. Both production and witness conservation must pass; witness success alone cannot certify release behavior. The legacy driver accepts only the exact completed-interval conservation failure. In addition to real-edge runs, mainline may pass each final server.log through `tests/lbsignals.py --shutdown LOG --edges` and `tests/shutdown_report.py LOG io --edges`.

Repeat `tests/flipctl.py` PRE and POST on independent fresh 8-core/shards16/6:2 servers, with the existing gate boot posture (`--atomic 0 --enable-debug-command yes --flip-auto 1`). Use the exact same workload inputs:

```bash
# Mainline starts one selected PRE or POST server, pinned 0-7, per campaign:
taskset -c 0-7 build/tomokv-signalacct-post --bind 127.0.0.1 --port 16740 \
  --shards 16 --ratio 6:2 --thread-mode 2s --atomic 0 \
  --read-local 0 --overlap 0 --reorder 0 --flip-auto 1 \
  --enable-debug-command yes --protected-mode no --save ''
# Separate mainline terminal while that server is alive:
taskset -c 8-111 python3 tests/flipctl.py --host 127.0.0.1 --port 16740 \
  --stable-seconds 60 --idle-seconds 4 --workers 9 --ramp-delay 1.1 \
  --think-time 0.0005 --surge-think-time 0.0004 --pace-burst 8
# Fresh server per arm for directed cost-gate check:
taskset -c 8-111 python3 tests/flip_cost_gate.py 127.0.0.1 16740 \
  --workers 6 --bitmap-mb 4 --boot-timeout 120 --maneuver-timeout 120
```

Replace only the arm path for PRE; retain stdout, INFO flip trace and shutdown report. Repeat all-on (`read-local1 overlap1 reorder1`) as a guard. Keep/compare the observed physical conversion TIDs as well as model target/anchor. Required: stable anchor holds; real mix/rate shifts converge and re-anchor; no extra settled oscillation; no losing maneuver admitted by the cost gate. Existing FLIP state/load/TTL rows and mode/feature equivalence must pass. These live results are **PENDING MAINLINE**.

## Measurement cells, instrument prerequisites and shipping bar

Frozen launch cell bytes: `build/signalacct-proof/headline_cells.pre.txt`, SHA-256 `d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350`. Frozen launch ledger `launch-gate_measurements.json`: `ceed40110ce6eff7db8533ea717ed1c532255a01f958b8d9df88c6efacc39618`. `mainline-plan.json` contains all 64 parsed rows and explicit arm/geometry/payload identities; `mainline-headline-ids.txt` contains exactly h01 through h64.

| Frozen headline group | Exact design |
|---|---|
| h01-h16 | 1s p32, GET/SET, all 8 combinations read-local/overlap/reorder0/1,512 connections |
| h17-h32 | 2s p32, same operations/knobs/connections |
| h33-h48 | 1s p1, same operations/knobs/connections |
| h49-h64 | 2s p1, same operations/knobs/connections |

All use atomic1, 2,000,000 keys,64-byte data, key pattern P:P,512 **total** connections shared among load instances. Do not reinterpret 512 as per generator. Gate runner uses warmup3 s, central window20 s, tail5 s, ABBA order. Freeze the per-cell generator count, thread/client distribution, payload and launch argv before comparing arms. No candidate-dependent offer/pin changes. If a load floor is invalid, qualify a fresh reference plan and collect a fresh null, rather than editing a threshold to pass.

First reproduce correctness at 0-7/shards16/6:2. Performance server geometry is also **physical 0-7, no SMT**, verified one L3 domain (`0-7,128-135`; full sibling list in geometry.json). Proposed mainline load reservation is physical 8-111, no SMT; keep 112-127 and all siblings quiet. Split6:2; current ABBA shard formula makes **2s16 shards, 1s64 shards**. Record this explicitly; it is different from the all-modes correctness 16-shard driver. If mainline instead chooses all-mode 16 shards for performance, that is a changed instrument requiring its own frozen null; do not silently reuse the64-shard fused pin.

**Launch instrument limitations, not hidden PASSes:**

1. `tests/gate_measurements.json:553` has a reviewed ABBA ratio only for 32 threads (16:16), not 8. `gate_measurements.ratio` correctly rejects 8. Mainline must record/review 8-thread6:2 geometry and establish its per-cell load plans/null before the command below can run. This lane did not invent measured provenance or copy32-core floors onto8 cores.
2. h33-h64 have `score=latency` and the existing p1 occupancy exemption. Their ordinary result is not by itself proof of a saturated p1 endpoint. The requested saturated p1 campaign additionally needs retained per-arm plateau/capacity evidence at increased producer capacity.
3. `tests/abba_profile.py:1` says grouped CPU counters have windows wider than the central command interval, so cycles/op and instructions/op from that path are approximate and **never gate/null evidence**. `abbagate.py:1785` restricts this to the untrusted diagnostic wrapper. There is no normal `--profile` CLI. Mainline must freeze/revalidate an aligned counter/completed-op instrument before certifying the requested cycles/op benefit. An instruction count alone or the diagnostic profile cannot satisfy it.
4. There is no reviewed 8-core matched-offer/low-offer plan at launch. Use PRE-only sustainable capacity R_ref per cell, then freeze offered rates **0.1,0.5,0.9 × R_ref** for matched-load comparison, plus the independently witnessed saturated endpoint. Preserve512 connections, original key/payload/cell flags, central intervals and instrument identity. Capture raw offered/achieved rates and tails; idle/low-offer and repeated6:2->3:5->6:2 transitions are deficit candidates. This is a requested mainline qualification, not measured lane data or an invented supported rate CLI.

PRE instrument fingerprint: `a3ae63c61e908a696235a364c8068e7b046b457f382e2c107c20593ccefef7af`.
Candidate instrument fingerprint: `16d354901dc42713dd7ff6bbddd859fbd22cabd3797500e4b0c4f5e1e433379d`.
The changed historical comments in runner/saturation files change this exact-byte fingerprint. `tests/abba_instrument.py --self-test` passes all 5 identity/dependency/negative tests. Mainline must re-freeze/revalidate the instrument after the signal change **before using it to certify cleanup nulls**. A historical ±0.15% box observation is not this cell's independently measured null resolution.

Once mainline has reviewed geometry and pinned the independently qualified per-cell plans, the current supported rate/tail command form is:

```bash
SIGNALACCT_IDS=$(cat build/signalacct-proof/mainline-headline-ids.txt)
COMMON=(--build-reference 0 --server-cores 0-7 --server-smt '' \
  --load-cores 8-111 --load-smt '' --port 16741 --ports 16741-16741 \
  --cells build/signalacct-proof/headline_cells.pre.txt --subset full --only "$SIGNALACCT_IDS")

# Identical PRE bytes first; output path must not already exist.
python3 tests/abbagate.py "${COMMON[@]}" \
  --reference-binary build/tomokv-signalacct-pre --candidate-binary build/tomokv-signalacct-pre \
  --collect-null 1 --output build/signalacct-mainline/null-pre

# Mainline uses the newly collected validated null result path:
python3 tests/abbagate.py "${COMMON[@]}" \
  --reference-binary build/tomokv-signalacct-pre --candidate-binary build/tomokv-signalacct-post \
  --null-result build/signalacct-mainline/null-pre/results.json \
  --output build/signalacct-mainline/pre-post
```

The h-only design is deliberately a partial campaign: `--only` and null collection return **PARTIAL/exit3**, not full-gate PASS. Inspect the validity/trust fields and per-cell decisions, not just shell status. Use the actual emitted result filename (current runner writes `results.json`). Collect independent identical-arm nulls and use the same frozen plans for **PAD-A vs PAIR-POST**, **release POST vs PAIR-POST**, and **PRE vs PAD-A**; do not reuse a null with mismatched binary/instrument/geometry provenance. Explicit arm paths/hashes are above. Witness and corrupted artifacts must never be measurement arms. Existing gate instrument remains the instrument; this lane supplies no replacement benchmark.

Required metric rows for **every cell/offer/arm**: achieved rate, offered rate, p50/p99/p99.9 and applicable starvation guard; cycles/op, instructions/op and IPC from compatible windows/counters; independent IO wall/busy/idle/endpoints and role histories; real model/physical-choice trace when flipping. cycles/op = instructions/op ÷ IPC. Pairing both halves is mandatory; one removed clock or a presumed vDSO cost proves no performance claim.

| Regime / verdict metric | PRE | POST | PAD-A / PAIR-POST / release bridge | Current verdict |
|---|---|---|---|---|
| IO-heavy p1 GET (claimed benefit), matched offer and saturated endpoint | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE | No gain claimed |
| p1 SET, all modes/knobs | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE | No regression verdict |
| p32 GET/SET (amortized-clock neutral regime) | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE | No neutral claim yet |
| Idle/low offered load, repeated role transitions (deficit candidates) | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE | Cold diagnostics/transition cost unresolved |
| Stable and abrupt-shift flip campaigns | PENDING MAINLINE | PENDING MAINLINE | Optional pair diagnosis | Model replay passes; real feedback pending |
| Live conservation/edge proof | Legacy must fail | PENDING MAINLINE | PAD legacy must fail; witness must pass | Only serverless exact equality proven |

**Exact shipping bar:** all requested cells at stable-reference parity within their independently frozen null resolution; cycles/op lower beyond that resolution in the claimed p1 GET benefit regime; no rate or tail regression at matched offered loads or valid saturated endpoints; unchanged idle classification; all live conservation/edge/decision proofs; stable holds and shift convergence with no extra steady-state oscillation or losing cost-gate admission. Always-on cost<=3% is a ceiling, not permission to accept a regression. If benefit is unresolved/no measurable gain, retain that verdict in the PRE/POST table and do not ship based on clock count alone. Resolve the collateral no-op/PAD limitations before acceptance.

## Gate rows, remaining scope and diff

`EXPECT_QUICK=438`, `EXPECT_FULL=454` at `tests/gate.sh:257-258` are unchanged. No rows added/retired: **quick +0, full +0**, therefore remain 438/454. Counting is by emission line, not boot group: model row begins 1202; core route/drain/config share the existing emission 1243; idle row 1448; shutdown row 1454 (same row now also calls lbsignals --shutdown); FLIP emissions 1882/1885/1888/1900/1931. These all precede the actual quick exit at **2819-2823**. Existing feature/multidb/mode-equivalence and generated/R7 checks remain in their original rows. Extending clean applies to other existing shutdown rows but emits no extra row. These numbers are row arithmetic, **not a gate run**.

Mainline must run its scheduled `tests/gate.sh iteration` and required full/mode-equivalence/R7 controls, using reviewed gate geometry first. Do not interpret the lane's units as a substitute. The strict PRE/POST no-op failure is retained verbatim; ordinary R7 source synchronization and scheduler controls pass.

No new ownership, shard-migration, immutable replacement/QSBR, no-retry/no-seqlock, read-local overwrite, RYOW, atomicity or reply-order mechanism was altered. No existing violation of those laws was identified in the accounting paths inspected; this was not a whole-tree law audit. Cold history allocation follows disarm/park so it does not hold a read-local grace-period publication active. Existing live signal snapshots can straddle pass/span publication and mixed role lifetimes; only completed role-separated diagnostics claim exact conservation. EX polling semantics, teardown/AOF timing, scratch controller labels and wider-window profiler limitations remain as described, without silent redesign.

Remaining acceptance work is explicit: live boots/batteries/gate, real edge controls, physical-feedback/controller campaigns, qualified 8-core/matched-offer/counter instrument, per-cell PRE/POST/PAD measurements, collateral code-generation audit, and the missing valid kind-B arm under its stated definition. All are **PENDING MAINLINE** or the stated unresolved artifact limitation, never PASS.

`git diff 3e734cf2e00c087604fcaf145459522e6fa81f05 --stat`:

```
 MEASURE-REQUEST-signalacct.md     | 427 ++++++++++++++++++++++++++++++++++++++
 Makefile                          |   8 +-
 src/core/flip_policy.h            |   6 +-
 src/core/flipctl.cc               |   7 +-
 src/core/flipctl.h                |   1 +
 src/core/io_loop.h                |  67 ++++--
 src/core/reorder.cc               |  76 +++++--
 src/core/server.h                 |  13 +-
 src/core/shutdown_report.h        |  35 +++-
 src/core/signal.h                 |  12 +-
 src/core/signalacct.h             | 116 +++++++++++
 tests/abba_saturation.py          |   5 +-
 tests/abbagate.py                 |   2 +-
 tests/core_concurrency_unit.cc    |   9 +-
 tests/flipctl_unit.cc             |   2 +
 tests/gate.sh                     |   2 +-
 tests/lbsignals.py                |   8 +
 tests/r7shadow_sync.py            |   7 +-
 tests/shutdown_report.py          | 158 +++++++++-----
 tests/signalacct_byte_checks.py   |  53 +++++
 tests/signalacct_checks.h         | 101 +++++++++
 tests/signalacct_controls.py      | 123 +++++++++++
 tests/signalacct_core_checks.inc  | 126 +++++++++++
 tests/signalacct_core_controls.py |  80 +++++++
 tests/signalacct_live.py          | 137 ++++++++++++
 tests/signalacct_live_test.py     |  85 ++++++++
 tests/signalacct_source_checks.py |  67 ++++++
 tests/signalacct_unit.cc          |   4 +
 tools/signalacct_artifacts.py     | 221 ++++++++++++++++++++
 29 files changed, 1859 insertions(+), 99 deletions(-)
```
