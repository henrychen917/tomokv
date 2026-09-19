# lbfix2: preserve sampling resolution as owner count grows

Branch/worktree: `cx-lbfix`, `/home/user/Projects/cx-lbfix`. No push.
Reference: `705cddec205e30ff5d4a163f38e5db7949207050` (production sources identical to
`197e3d598`; only the gate reference pointer differs). Rejected candidate: `2174a03fc`.
New source/proof/artifact commits: `7c8c4f4cc`, `00dbfaa15`, `e8106fb8e`.

**Built; runtime assertions, negative controls, gate and performance are pending mainline.**
All builds used `taskset -c 112-127 make -j16`; artifact generation and offline checks used
the same affinity. No server, load generator, gate, performance measurement or unit proof
was run by this lane. The mainline competition log records the previous candidate's
454/0 gate, seven passing assertions and eight correctly failing negative-control runs;
those results do not certify these rebuilt artifacts.

## Correction and derivation

Keep the range statistic `100 * (max_owner_load - min_owner_load) / mean_owner_load`.
The rejected derivation divided one sample budget among every owner. The correction gives
each owner the existing 4096-sample decision target, and changes the actual sampling-rate
calculation to use that same total budget. No fitted percentage, new numeric constant or
configuration knob is introduced.

Let `M >= 2` be the eligible owner count and `S = kSamplesPerDecision = 4096`.
For balanced multinomial sampling with total budget `N`, the difference between a fixed
pair of owner counts has variance `2*N/M`. Dividing by the mean count `N/M` gives
relative standard error `sqrt(2*M/N)`. Retain the previous two-error margin and the
pair-selection correction for `P = M*(M-1)/2`: `z² = 4 + 2*ln(P)`.

```text
N(M)      = S * M
N(M) / M  = S
floor_pct = 100 * sqrt((4 + 2*ln(P)) * 2*M/N(M))
          = 100 * sqrt((4 + 2*ln(P)) * 2/S)
band_pct  = max(2*jitter, floor_pct)
```

Per-owner resolution is now constant; only the logarithmic selection penalty grows.
The 25% witness below means one owner at 11250 visits, one at 8750, and all remaining
owners at 10000. Total load stays fixed. Moving a 1250-visit shard from the high owner
to the low owner makes every owner exactly 10000. This is a modest, achievable imbalance,
independent of M; its magnitude does not enter the production derivation.

| Owners M | Total target N per 3-tick decision | Target per owner | Rejected floor | New floor | Can the realistic 25% span clear it? |
| ---: | ---: | ---: | ---: | ---: | --- |
| 2 | 8192 | 4096 | 6.250000% | 4.419417% | Yes |
| 4 | 16384 | 4096 | 12.170275% | 6.085138% | Yes |
| 8 | 32768 | 4096 | 20.410254% | 7.216115% | Yes |
| 16 | 65536 | 4096 | 32.566019% | 8.141505% | Yes |
| 32 | 131072 | 4096 | 50.641435% | 8.952226% | Yes |
| 64 | 262144 | 4096 | 77.495446% | 9.686931% | Yes |

These are quiet-band floors. Measured jitter can widen the band. As before, this is a
sampling-resolution policy, not a confidence guarantee: samples can be correlated,
the cheap execution-count rate estimate is a proxy for key visits, integer rounding
changes the achieved count, and sparse traffic cannot supply the target. Sparse traffic
still samples every visit. Bytes and client load retain the same common policy band;
the derivation is not a claim that those publications are multinomial observations.

`lb_fold_signals` counts live owner-capable roles, including empty eligible destinations,
so split mode uses EX count rather than total thread count or a boot-time snapshot.
The total budget uses a 64-bit product. FLIP's separate sampler retains its existing
global budget through the default one-budget argument; its two call sites are unchanged.

There is a real sampling-cost tradeoff to measure. At 900K single-key visits/s and a
three-second window, the reference's target gives one sample every 660 visits. The new
32-owner target gives one every 21 (about 42857 samples/s); 64 owners gives one every 11
(about 81818/s). These are arithmetic predictions, not measurements. The existing
countdown and rate-weighted sample path are unchanged, but that path records more samples.
No performance gain follows from the formula alone.

The deferred evidence gather, consumed admission streak, minimum three-tick cooldown,
per-step floored band, dominant-bucket veto, read-only fold/census, owner installation and
all previous assertions/negative mutations are retained. No locked structure gains a
field. Compared with the rejected candidate, production changes are confined to the
sampling helpers in `weighted_lb.h` and the live owner-count argument in `server.h`.

## Assertions and negative controls for mainline

The fixtures start no workers or listeners. The split fixture keeps 16 shards and 6 IO + 2 EX.
Fused fixtures use two physical shards per logical owner. The 32/64-owner fixtures
map those logical contexts onto allowed CPUs without changing affinity; they do not need
32/64 running CPUs. This permits the existing eight-CPU gate row to cover the larger
controller state space. These assertions do not replace the live 32-thread measurement.

| Assertion / selector | Required positive behavior | Negative control and intended failure | Current result |
| --- | --- | --- | --- |
| `lbfix-hot` | Original large-hot-shard proofs at split 2/fused 8 retained. Additional fixed 25% cases at fused 8/32/64: plan within 9 ticks, commit a move, reduce actual owner spread to zero; after 96 settling ticks, 48 ticks with zero additional moves. | `no-hot` removes key admission: bounded-fire assertion fails. `fixed-budget` at 32 and 64 restores the rejected floor: the same bounded-fire assertion fails. | Built; all executions pending mainline |
| `lbfix-clearable` | At 2/4/8/16/32/64 owners, prime 96 balanced ticks, impose exactly the stated 25% span, and require admission/gather within 9 ticks. Also check the production observed ratio is 25% and the band is below it. | `fixed-budget`: fails `25% owner imbalance clears admission within nine ticks`, first at 16 owners. No skip or unbounded retry. | Built; executions pending mainline |
| `lbfix-stationary` | At split 2 and fused 2/4/8/16/32/64 owners, 96 ticks of a roughly 2% stationary residual: zero plans, zero moves, zero gathers; verify nonzero level and decayed jitter. | `no-floor`: a movable tiny shard makes the residual actionable; stationary no-move assertion fails. | Built; executions pending mainline |
| `lbfix-floor` | At all six counts, 256 steady observations preserve the independently calculated floor after jitter becomes zero. Full-window cooldown assertion retained. | `no-floor`: lower-bound assertion fails. This lower-bound test is now accompanied by clearability, not used as a liveness proof. | Built; executions pending mainline |
| `lbfix-sampling` | Feed 10000 visits per owner per second through the production fold: sample rate must be 8 at split 2 and all six fused counts; zero traffic must yield rate 1. Split has 8 total threads, testing the owner-count wiring. | `fixed-budget` removes budget scaling; `fixed-sampling` supplies one owner only to the live sampler while keeping the new floor. Both fail the per-owner-resolution assertion. | Built; both executions pending mainline |
| `lbfix-gather` | Original split 2/fused 8: 96 rejected ticks leave gather count and both history arrays unchanged; hot input must advance the witness and sample fold. | `eager-gather`: zero-gather/history-preservation assertion fails. | Built; executions pending mainline |
| `lbfix-no-move` | Original split 2/fused 8: an indivisible admitted attempt consumes its streak, waits two ticks, then reconsiders on tick three. | `no-reset`: consumed-streak assertion fails. | Built; executions pending mainline |
| `lbfix-step` | Original split 2/fused 8: admit cheap evidence, reach the detailed planner with a movable sub-floor residual, and move nothing. | `step-no-floor`: per-step no-move assertion fails. | Built; executions pending mainline |
| `lbfix-read-only` | Original split 2/fused 8: expired sentinel is visited by the census; fold preserves object, TTL, bytes and owner samples; normal owner lookup then expires it. | `census-expiry` fails the visited/preserved-sentinel assertions; independent `fold-expiry` fails preservation. | Built; both executions pending mainline |

Standalone `lbfix-hot-8`, `lbfix-hot-32`, `lbfix-hot-64` select the modest cases separately,
so a failure at one geometry cannot mask a missing run at another. The `no-hot` manifest
includes each of these as well as the combined `lbfix-hot` row. `fixed-budget` includes
both 32 and 64 separately, plus clearability and sampling. There are nine negative binaries
and sixteen listed negative invocations in `build/lbfix-controls.json`. Actual results are
explicitly `NOT RUN: mainline owns proof runs`; predicted failures above are not results.
Require exit 1 and the intended `FAIL core concurrency:` assertion, not a sanitizer startup
failure, crash, timeout or unrelated assertion.

All nine assertion families are in the existing `route` selection. Mainline commands:

```sh
taskset -c 112-127 ./build/config-parser-test
ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 taskset -c 112-127 ./build/core-concurrency-unit route
taskset -c 112-127 setarch x86_64 -R ./build/lbfix-tsan/unit route
```

Run all sixteen manifest negative invocations with ASAN/UBSAN, and retain the existing
`watch lifetime drain snapshot config notify` selections with both instruments. The config
unit now covers sample-budget invariance at all six counts and preserves FLIP's global
budget expectation. Mainline should also rerun the live `lbsignals` batteries and iteration
gate in both modes. Gate ledger unchanged: **quick 438 / full 454**. The existing core loop
is at `tests/gate.sh:1242`; `lbsignals` is at line 1615, both before the quick exit at 2812.
No row was added/retired; `EXPECT_QUICK` / `EXPECT_FULL` were not edited.

## Measurement request and verdict

Rerun the rejecting **tailgen geometry: 1s, 32 owner threads, 900K ops/s, reference versus
candidate, three rounds per arm**. Preserve the previous tailgen mix, key distribution,
shard count, connections, depth and all other options. Mainline owns scheduling, launches
and the instrument. Do not substitute the gate's 6:2 geometry for this reproduction.

| Arm | Binary | Purpose |
| --- | --- | --- |
| Reference | `build/lbfix-pre/tomokv` | Original mainline behavior, same reference as the rejected measurement |
| Candidate | `build/tomokv` | Corrected per-owner budget plus retained deferred gather |

For every round record completed rate, p99/p99.9, controller ticks, hysteresis refusals,
corrective moves, current/before/after owner weight and byte spreads, gathers and transition
refusals over matching intervals. Keep the offered load fixed and report cycles/op, IPC and
instructions/op with the gate's instrument. The increased sampling cost must be judged
alongside the recovered balancing and gather reduction.

Acceptance requires corrective moves to reappear **with owner spread collapsing**, gathers
far below the controller tick count, and **no tail loss** at the same completed rate versus
reference. A zero-gather round without planning/corrective moves is a failure, not evidence
of savings. The preserved three-tick streak limits key gathers to one per newly sustained
decision; measure the actual gather/tick ratio, including the corrective part of the run.
The reference has no `tomokv_keylb_bucket_gathers` field: its source does the full bucket fold
on each tick that reaches admission. Report its tick/transition counts as the per-tick
reference work, and candidate's actual gather counter separately; do not invent a reference
gather counter or treat a missing field as zero. Also retain the zero-plan/zero-gather
stationary suffix check. The deferred-gather benefit remains **unmeasured** until this run.

| Supplied previous mainline result, rounds 1 / 2 / 3 | Reference | Rejected candidate | lbfix2 |
| --- | --- | --- | --- |
| Corrective moves | 2 / 2 / 5 | 0 / 0 / 0 | Pending |
| Hysteresis refusals | 66 / 66 / 68 | 120 / 119 / 119 | Pending |
| Planned weight spread | 2317→366 / 2764→367 / 3861→628 | Never populated | Pending |
| p99.9 (ms) | 3.405 / 3.117 / 3.105 | 4.279 / 3.527 / 3.583 | Pending |
| Completed rate | 0.899–0.901M | 0.899–0.901M | Pending |
| Deferred-gather savings | Per eligible tick | Zero for the wrong reason | Unmeasured |

## Build identity and offline checks

Release/config builds: `build/lbfix2-release-build.log`. ASAN/UBSAN core unit, all nine
negative binaries and full-dependency TSan unit: `build/lbfix2-proof-build.log`. Both builds
completed without compiler/linker errors; TSan emitted its existing unsupported-fence
instrumentation warnings. Dependency freshness checks, Python syntax and `git diff --check`
passed. No runtime correctness or zero-regression claim is made.

The generator also built an offline **type B inverse control** at
`build/tomokv-lbfix-pad`: candidate behavior plus 208 NOP bytes restoring reference `.text`
size. It is **not requested as a measurement arm**: the reference-to-candidate text delta
is only -208 bytes, below the standing threshold for adding a B arm. The artifact is labelled
in `build/lbfix-pad.json`. Offline `build/lbfix2-pad-check.json` confirms identical candidate
text prefix, text base and CET properties, NOP-only tail, and reference text extent. It
does not reproduce reference internal function addresses. No structure layout changed.

```text
Reference .text: 8215997 bytes
Candidate .text: 8215789 bytes

$ sha256sum build/tomokv
1393125e8953cb2ac5c77f47c26db4f279235cfdc976cee775680c955d6305359  build/tomokv

$ sha256sum build/lbfix-pre/tomokv
9a5382cd6b5721c04f3320c07bdfa058d1b6b7a2dd00c74aebd528c8b76e9838  build/lbfix-pre/tomokv
```

PRE is the previously built reference artifact, retained unchanged and checksum-verified.
The report commit changes documentation only.

```text
$ git diff 705cddec205e30ff5d4a163f38e5db7949207050 --stat
 MEASURE-REQUEST-lbfix.md       | 281 +++++++++++++++++++++++++++++++++
 MEASURE-REQUEST-lbfix2.md      | 203 ++++++++++++++++++++++++
 src/cmd/lbsignals.cc           |   1 +
 src/core/lbstall.cc            |   7 +-
 src/core/server.h              | 308 +++++++++++++++++++++----------------
 src/core/weighted_lb.h         |  57 ++++++-
 tests/config_parser_test.cc    |  24 +--
 tests/core_concurrency_unit.cc | 341 +++++++++++++++++++++++++++++++++++++++--
 tests/lbsignals.py             |  10 ++
 tools/lbfix_artifacts.py       | 173 +++++++++++++++++++++
 10 files changed, 1239 insertions(+), 166 deletions(-)
```
