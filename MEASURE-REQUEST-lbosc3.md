# lbosc3 — residual-band objective and recent-move damping

Status: **UNTUNED / measurement pending; do not land on this report alone.**
No server, load generator, benchmark, or gate was started by this lane. The shared
measurement rule assigns those runs to the maintainer. Consequently the measured
accuracy loss, pooled-move merit, rate/p99 changes, <=3% always-on cost, live boot
checks, and stationary-hold gate rows are not yet proved. The default-duration
six-round episode matrix needs 198.8 nominal load minutes plus setup, longer than
the lane's two-hour coding limit.

Base: `5efc5414d3d6107b5e7e29f2404e585806c823ec` (the final merge-base).
The lane merged `origin/cpp` on entry and again before the final build/proof.
The second merge was already up to date. No push.

## Policy

Implementation is in `src/core/lbplanner.cc`; header/config/INFO edits are wiring.
The shared `weighted_lb_best_incremental_move` is unchanged. Client balancing,
FLIP, ownership publication, draining, and migration critical sections retain
PRE behavior. No per-owner structure was added, and no request-path branch,
lock, retry, timestamp, or store was added.

For candidate shard weight `w`, predict the new owner vector by subtracting `w`
from its source and adding `w` to the destination. The key objective orders
candidates by `max(0, predicted_spread - band_in_weight_units)`. Thus any candidate
inside the band wins over every candidate outside; when none fits, the smallest
predicted residual wins. The bytes objective is independently banded and remains
secondary. Once both objectives tie inside their bands, prefer less transferred
load, then the existing count/ID tie breaks. Strict raw improvement and pinning
remain mandatory. This changes the objective; there is no recent-shard,
owner-pair, reversal, or below-band gain refusal.

A deterministic example distinguishes the objective from PRE: owner loads
1200/800 with movable weights 200 and 160, and a 100-unit band. PRE moves 200
(residual 0); POST moves 160 (residual 80). The witness also tests a unique in-band
candidate, two outside-band candidates, and pinned candidates. The PRE-policy
PAD-A must fail the POST oracle, and POST must fail the PRE oracle.

The boot-only knob is `key-lb-damping` (CLI `--key-lb-damping`), canonical signed
decimal, range -1..2147483647:

| Value | Behavior | Dedicated damping allocation |
| --- | --- | --- |
| 0 | PRE objective and PRE Schmitt admission | none |
| -1 (default candidate) | band objective, automatic damping level | one cold sidecar when key-lb=1 |
| N > 0 | band objective, explicit damping level N | one cold sidecar when key-lb=1 |

`key-lb=0` allocates no sidecar. The knob consumes four reserved Config bytes;
Config remains 624 bytes and all previous non-reserved offsets remain fixed.
The CONFIGURATION.md and README knob matrices, the config example, parser tests, and `tests/knobs.py` cover
its default, grammar, file/CLI override, and immutable CONFIG GET/SET surface.

Damping derives from the existing quantities. Write `D=kDecisionTicks=3`,
`T=kTickMs=1000`, `S=kSamplesPerDecision=4096`, and
`B=max(2*quiet_jitter, sampling_floor(owner_count))` in percentage points.

- Horizon `H = D * ceil(100/B)` ticks: one decision window per resolvable step in
  an owner's full load.
- Recent movement `R` counts **completed admitted shard moves**, not selected
  candidates or refused plans. Between observations, multiply R by
  `2^(-elapsed_ms/(H*T))`; discard R below `1/S`.
- Level `L = D` in auto, otherwise the explicit positive integer.
  `P = min(max(1,H-D), R*L)`; `K = D + ceil(P)`.
- Effective fire band `F = B*(1 + 0.5*P/max(1,H-D))`, so `B <= F <= 1.5B`.
- After movement, require K **consecutive** ticks above F. A tick in the Schmitt
  gap breaks the streak. A skipped controller tick also breaks it. Quiet time
  removes pressure, and topology/counter/clock resets clear stale pressure.
  Without recent movement, the original 0.8*fire release rule is retained.

INFO LB publishes `tomokv_keylb_damping_band_pct`,
`tomokv_keylb_damping_fire_pct`, and `tomokv_keylb_damping_ticks`. These are cold
atomic snapshots; zero means that the damping sidecar is absent. Both new arms
retain the existing hysteresis_refused and no_candidate counters.

The 1.5 cap bounds the admission band, **not** the final spread analytically:
indivisibility, sampling, and different trajectories still require measurement.

## Accuracy and merit rule (declared before measurement)

Judge each mode separately over at least six complete rounds per arm. Pool
owner-tracked moves, returns to any earlier owner, and owner-pair exchanges.
Use **mean** end spread to judge accuracy; also report the maximum round endpoint.
Do not select only converged/PASS rounds, and do not substitute medians for pooled
moves or the mean endpoint.

Required accuracy: mean POST end spread minus mean PAD-A end spread <= 1.5 times
the admission band. `tools/lbosc3_report.py` uses the sampling floor as a
conservative band, scaled by measured per-owner visits/second over the fixed
endpoint's last three seconds. It reports the absolute allowance and measured
loss in band units. The floor is 7.216114583% for eight owners (1s in the requested
geometry), 6.085137720% for four owners (2s); allowances are respectively
10.824171874 and 9.127706579 percentage points of mean owner demand. Actual quiet
jitter can only widen the admission band. The raw-unit conversion is derived from
sampled cumulative visit counters; inspect telemetry if the result is close to
the accuracy limit.

**Measured accuracy loss: not available (n=0). Status remains UNTUNED.**

Pooled POST moves must be strictly below **both PRE and PAD-A in both modes**.
If this fails after a valid complete campaign, **SHELVE**, retain the evidence,
and stop. If accuracy fails, tune or report UNTUNED. Mean episode rate must not
fall >2%, and mean per-episode p99 must not rise >2%, against either control.
Report per-round values as well as aggregates. The mainline 14-cell null must
also meet its own bands and the <=3% always-on cost ceiling.

The two shelved rules were read before implementation: PLAN-SERIAL run 8
(one-step reversal -> longer rotations/exchanges) and run 9 (recent move/pair
history -> parked residual, no pooled win). This candidate adds neither rule.

## Arms and byte proof

Final SHA-256 receipts, layout proof, complete hot-inventory audit, and serverless
checks are recorded below. PAD-A is **type A: PRE placement
behavior with POST's exact text size/layout**. `tools/lbosc3_pad.py` changes only
the two namespaces' out-of-line configured-level returns to zero in a copy of
POST. It checks PRE controller/search source closure, identical section/function
tables, every unpatched byte, and missing-patch/moved-symbol/unrelated-byte
negative controls. The older lbplanner PAD is not this lane's behavior twin.

PRE is `build/lbosc3/PRE/tomokv`, independently built from the merge-base archive.
POST is `build/lbosc3/POST/tomokv`, required byte-identical to `build/tomokv`.
PAD-A is `build/lbosc3/PAD-A/tomokv`. `docs/lbosc3/arms.json` pins all three paths
and full digests. Compile-budget changes are restricted to the two main objects
that include the changed boot parser/policy initialization; no unaffected TU's
budget changes.

## Maintainer measurement commands

Run only when the box is scheduled. The requested CPU partition keeps server and
load disjoint within 112-127: server 112-119, load 120-127. Leave `--shards` omitted:
expect 64 shards/8 owners in 1s and 32 shards/4 owners in default 2s. Record and
verify actual geometry; both have shards > owners. HOTMAX=256 retains the proven
small hot subset. Before accepting a campaign, inspect the PRE probe's seed hot
key map and spread excursion: the stimulus must be well above the admission band
(three band widths of peak spread is the declared margin), not merely one move.
If unarmed or below that margin, refuse the campaign and predeclare a stronger
HOTMAX on fresh state; do not mix geometries or choose favorable rounds.

```sh
python3 tools/lb_episodes.py --dry-run --episodes key-skew --rounds 6 \
  --server-cores 112-119 --load-cores 120-127 --hotmax 256 \
  --arms docs/lbosc3/arms.json --output build/lbosc3/episodes

python3 tools/lb_episodes.py --episodes key-skew --rounds 6 \
  --server-cores 112-119 --load-cores 120-127 --hotmax 256 \
  --arms docs/lbosc3/arms.json --output build/lbosc3/episodes

python3 tools/lb_episodes.py --replay build/lbosc3/episodes
python3 /home/user/Projects/calib/lbplanner-judge.py build/lbosc3/episodes
python3 tools/lbosc3_report.py build/lbosc3/episodes \
  --json build/lbosc3/episode-judgment.json
```

The existing harness and old judge may report FAIL on their stricter old
per-round convergence rules. Their flags do not decide this lane. Preserve all
raw rows/telemetry and use the declared pooled comparison above. The new reader
requires >=6 distinct complete rounds per arm, matching round sets, valid workload
accounting, continuous owner maps, and equality between observed transitions and
the independent completed-move counter. A missed cycle is invalid evidence.
Quiescence is the last observed admitted shard movement relative to stimulus;
report its per-round value and arm mean/max even when the old harness rejects
convergence. Rate is ops/s; p99 is ms (mean of per-episode quantiles, not a merged
campaign quantile).

| Mode | Arm | n | Pooled moves | Returns | Exchanges | Last move mean/max s | End spread mean/max | Rate | p99 ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1s | PRE | 0 | pending | pending | pending | pending | pending | pending | pending |
| 1s | PAD-A | 0 | pending | pending | pending | pending | pending | pending | pending |
| 1s | POST | 0 | pending | pending | pending | pending | pending | pending | pending |
| 2s | PRE | 0 | pending | pending | pending | pending | pending | pending | pending |
| 2s | PAD-A | 0 | pending | pending | pending | pending | pending | pending | pending |
| 2s | POST | 0 | pending | pending | pending | pending | pending | pending | pending |

The mainline runs the 14-cell null and live LB/stationary hold rows, then the
iteration gate before landing. No EXPECT constant was edited. **Row delta +0/+0**:
the existing `LB monitor plan handoff + negative controls` row (gate.sh:1348,
collected at line 3227 before the quick exit at line 3393) now also checks the new objective,
damping, PRE twin, and both opposite-policy negative controls. Existing config
parser and knob-matrix rows are extended; no new row emission is introduced.
Stationary-hold jobs remain `lb-stationary-1s` and `lb-stationary-2s`.

Relevant differ suites, one per line (unchanged tests; maintainer runs them):

```text
compatintro
infofix
psfix
```

Text-encoding searches across tests are retained in `docs/lbosc3/test-text-before.txt`,
`info-text-search.txt`, and `test-text-after.txt`. Searches used grep, not rg.

## Final offline receipts

| Arm | SHA-256 | .text bytes |
| --- | --- | ---: |
| PRE | `c1978243f4910d317747341dd71b983d2e84d18009466942a2d63cff501b61c3` | 7817349 |
| PAD-A | `56345222b517cb2bc8afdbbc127c4afae05e908cb0a0f038f0eb6e7a6be17a2f` | 7841621 |
| POST | `8010210528069bd7c1fe0e1dab23b8b121cb64d221c955995a006405e43dd101` | 7841621 |

POST equals `build/tomokv` byte for byte. Text delta vs PRE is +24,272 bytes;
PAD-A has POST's exact text size, section table, function addresses/sizes, and
all bytes except the two leaf policy returns. The PAD verifier rejects all four
production artifact negative controls. No inverse (type B) arm is requested.

`tools/lbstall_artifacts.py compare` (complete inventory, both namespaces):

| Inventory | Bodies | Raw equal | Instructions + resolved relocation targets equal |
| --- | ---: | ---: | ---: |
| multi-DB | 746 | 746 | 746 |
| db0 | 746 | 742 | 746 |
| Total | 1492 | 1488 | 1492 |

The four raw differences are address displacements with identical resolved
instruction targets. No ordinary hot body is excepted. Receipts:
`docs/lbosc3/final-hot-*.json.gz`, matching logs, and `body-summary.json`.
The winning affected-TU budgets are recorded with compile commands in
`main-budget.json` and `db0-main-budget.json`; all other TU budgets are unchanged.

`layout.json` compares each namespace to its own PRE: Op 336, Client 1984,
ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624.
All inventoried Server offsets/sizes also match within each namespace. The compile
of `tests/mdbqsbr_probe.cc` passed its independent locked-layout static assertions.

Final verification on CPUs 112-127, without a server:

- Full release build plus both namespaces, config parser, LB planner/control units,
  and core ASAN/UBSAN unit build: success. The existing custom allocation wrapper
  in the LB test emits GCC's mismatched-new-delete warning; no build errors.
- 14 LB planner check groups pass, including POST/PAD-A and both opposite-policy
  negative controls, real moves in both modes, consecutive streak/skip/expiry
  checks, stale plan rejection, record lifetime, and zero-allocation IO handoff.
- All 11 selected ASAN/UBSAN checks pass: lbfix, floor, stationary, hot, clearable,
  sampling, gather, no-move, step, read-only fold, and lbstall. These initialize
  in-memory fixtures; they do not boot a server or start worker loops.
- Config parser passes; documentation drift check passes with 86 spellings and
  all its negative controls. Episode harness: 51 self-tests pass. Pooled judge:
  three self-tests pass, including raw owner maps, missed-cycle rejection, strict
  twin comparison, incomplete rounds, accuracy, and rate/p99 rejection.
- Six-round episode dry-run succeeds and records the 36 scored jobs plus the
  unchanged calibration/probe prerequisites. It starts nothing.

Logs and control results are in `docs/lbosc3/`; the full build and dry-run logs
are compressed there. Live gate/boot/episode/null results remain pending, with
n=0 in every live arm. **No measured performance or accuracy claim is made.**

## 2026-10-08 — lbosc3b

This section supersedes the old base, binary receipts, and HOTMAX recommendation
above. The old section remains the predecessor's historical record.

Merged `origin/cpp` at `db86e5b4a051929c68108d33b1dc358428c59bca`.
The config conflict keeps encodingfix's `stream_limits` at byte 560, places
`key_lb_damping` at byte 568, and starts `layout_reserved[52]` at byte 572.
Config stays 624 bytes. All mainline non-reserved fields and both namespaces'
locked layouts match; the new damping field necessarily moves from its old
candidate-only byte 560. Both MEASURE-REQUEST texts are retained. No planner or
damping source was changed. The affected main.cc compiler budgets and final
byte/SHA receipts were re-derived against the new PRE; the completed proof is below.

### Stimulus predeclaration (before any new live probe)

Use **2s HOTMAX=64**, the largest requested prefix whose modeled **total** owner
spread reaches three sampling-floor bands. Model uniform visits within each
cohort, equal hot/cold rates, equal SET costs, and the recorded seed ownership.
For N owners, H hot keys, and hot counts c_i, owner load share is
`0.5/N + 0.5*c_i/H`; ratio is `100*N*(max(share)-min(share))`.
The recorded rates were almost exactly equal: hot fractions 0.499932072 (1s)
and 0.497537447 (2s). Replacing 0.5 with those fractions preserves the selection.
The actual band is max(sampling floor, twice learned jitter), so this model is
not evidence that a fresh runtime band or key move has armed.

**The requested 1s=256 three-band confirmation is false for this workload.**
It has 3.8975 bands considering hot traffic alone, but only 1.9488 after cold
traffic. The old probe ARMED, which is a weaker condition. The largest 1s prefix
that meets the same model rule is 128. Commands will include the requested
256/64 configuration and the margin-compliant 128/64 variant, explicitly labeled;
there is no silent stimulus substitution or favorable-round selection.

Model: equal-rate hot/cold SET cohorts; ratio = 100 * owners * (max(load)-min(load))/sum(load).
Three-band margin applies to total demand. Hot-only ratios are shown to expose the cold-cohort dilution.

1s: owners [0, 1, 2, 3, 4, 5, 6, 7], 64 shards; band 7.216114583%; 3 bands 21.648343748%.

| HOTMAX | Hot keys per owner | Hot-only % | Total % | Total / band | Recorded-rate % | Recorded-rate + seed-cold % | Improves with one shard |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 4 | 1,0,0,1,1,0,1,0 | 200.0000 | 100.0000 | 13.8579 | 99.9864 | 100.4881 | no |
| 8 | 1,0,0,2,3,0,1,1 | 300.0000 | 150.0000 | 20.7868 | 149.9796 | 150.2357 | yes |
| 16 | 5,1,1,2,3,1,1,2 | 200.0000 | 100.0000 | 13.8579 | 99.9864 | 100.3329 | yes |
| 32 | 8,4,3,5,5,2,2,3 | 150.0000 | 75.0000 | 10.3934 | 74.9898 | 75.0002 | yes |
| 64 | 12,10,8,9,8,5,7,5 | 87.5000 | 43.7500 | 6.0628 | 43.7441 | 43.8201 | yes |
| 128 | 20,21,15,14,16,12,17,13 | 56.2500 | 28.1250 | 3.8975 | 28.1212 | 28.1468 | yes |
| 256 | 35,32,36,29,31,28,37,28 | 28.1250 | 14.0625 | 1.9488 | 14.0606 | 14.2879 | yes |

Largest HOTMAX with >=3 bands: 128; recorded hot fraction 0.499932072.

2s: owners [4, 5, 6, 7], 32 shards; band 6.085137720%; 3 bands 18.255413159%.

| HOTMAX | Hot keys per owner | Hot-only % | Total % | Total / band | Recorded-rate % | Recorded-rate + seed-cold % | Improves with one shard |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 4 | 1,0,1,2 | 200.0000 | 100.0000 | 16.4335 | 99.5075 | 99.4709 | yes |
| 8 | 1,3,2,2 | 100.0000 | 50.0000 | 8.2167 | 49.7537 | 49.9616 | yes |
| 16 | 4,4,4,4 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.2231 | no |
| 32 | 10,6,6,10 | 50.0000 | 25.0000 | 4.1084 | 24.8769 | 24.8395 | no |
| 64 | 20,14,15,15 | 37.5000 | 18.7500 | 3.0813 | 18.6577 | 18.4466 | yes |
| 128 | 36,33,29,30 | 21.8750 | 10.9375 | 1.7974 | 10.8836 | 10.6577 | yes |
| 256 | 65,65,65,61 | 6.2500 | 3.1250 | 0.5135 | 3.1096 | 3.1583 | no |

Largest HOTMAX with >=3 bands: 64; recorded hot fraction 0.497537447.

Predeclare 2s HOTMAX=64. 1s HOTMAX=256 arms but does NOT retain the declared three-band margin once cold traffic is counted; the largest model-compliant 1s value is 128. No favourable round selection or automatic stimulus change.

The final sensitivity column also uses the seed's actual 500,000-key shard
population from the first saved telemetry poll: cold mass per shard is
`(seed_shard_keys - prefix_hot_keys)/(500000 - HOTMAX)`. It retains the same
64/128 selections. The 2s margin is narrow; the runtime probe must still be
inspected against the actual band. Input hashes, per-owner load shares and
modeled best single-shard moves are in `docs/lbosc3/lbosc3b/hotmax-model.json`;
`model.py` beside it reproduces the tables without starting a process.

### Why 2s gathers stayed at zero

`Server::lb_controller_tick` folds the cheap per-shard demand signal, computes
`100*(max_owner_load-min_owner_load)/mean_owner_load`, and updates the key
Schmitt streak **before** `lb_gather_key_evidence`. Three admitted ticks are
required. Candidate search happens **after** that gather, so an absent candidate
cannot itself explain a zero gather count. There is no special 2s gather gate.
At the end, an empty key plan and empty client plan increment `no_candidate`
regardless of whether either search ran.

The 2s deltas fit this path exactly: 213 ticks, 426 hysteresis refusals (key plus
client), 213 empty-plan `no_candidate` increments, zero transition refusals,
gathers, attempts, or moves. HOTMAX=256 yields counts 65/65/65/61: its total-load
model is only 3.125%, below the 6.085% sampling floor. It also has no improving
single-shard move in this model, but the recorded run stopped earlier at
admission. Thus the hypothesis is supported as a geometry/stimulus problem;
reading `no_candidate` as proof of 213 failed shard searches would be incorrect.
The 1s model at 256 is 14.0625%, above its 7.216% floor, explaining why it can
admit gathers (70 observed) despite missing the separately declared three-band
margin. Ratios estimated from visits in the three seconds preceding the saved
peak are about 15.57% (1s) and 3.04% (2s), consistent with that distinction.

### Final merge, compiler, byte and layout receipts

Merged `origin/cpp` again immediately before the final proof; already up to date
at `db86e5b4a`. PRE was rebuilt from an archive of that commit in
`build/lbosc3/PRE/source`, not from the old 5efc5414d tree. The old binaries remain
under `build/lbosc3/{PRE,POST,PAD-A}-5efc5414d` for the refused run's historical
receipts. POST is a fresh merged-tree build and equals `build/tomokv` byte for byte.
PAD-A is **type A: PRE placement behavior with POST's exact text size/layout**,
regenerated by `tools/lbosc3_pad.py` with the new source baseline.

| Affected object | New PRE large-unit-insns | Merged POST large-unit-insns | POST max-inline-insns-auto | Hot bodies equal |
| --- | ---: | ---: | ---: | ---: |
| src/main.o | 146409 | 146503 | compiler default (15) | 127/127 |
| db0/src/main.o | 146203 | 146540 | 18 | 128/128 |

`inline-unit-growth=0` remains unchanged. No other TU's budget was modified.
The old db0 146340/14 pairing matched only 126/128 bodies on the new base;
82 offline trials are retained in `docs/lbosc3/lbosc3b/budget-trials.json`.
Budgets 146540, 146560 and 146580 at auto=18 matched; the first was selected.
Reproduce the selected trials (compilation only):

```sh
python3 docs/lbosc3/lbosc3b/rederive.py 146503
python3 docs/lbosc3/lbosc3b/rederive.py --db0 --auto 18 146540
```

| Inventory | Bodies | Raw equal | Instructions + resolved relocation targets equal |
| --- | ---: | ---: | ---: |
| multi-DB | 746 | 746 | 746 |
| db0 | 746 | 742 | 746 |
| Total | 1492 | 1488 | 1492 |

The four raw differences resolve to the same instruction targets; no ordinary
hot body was excepted. `final-hot-{multi,db0}.json.gz`, the corresponding logs and
`body-summary.json` are refreshed. PAD-A's section/function tables match POST
exactly, every unplanned byte matches, both namespaces have a policy bypass, and
all four missing-patch/moved-symbol/unrelated-byte controls are rejected. The
serverless POST/PAD-A policy oracles and both opposite-policy controls also pass.

The DWARF proof in `docs/lbosc3/lbosc3b/layouts.json` compares the rebuilt PRE to
`origin/cpp`'s `docs/encodingfix/layouts.json` POST, then compares every existing
non-reserved field against merged POST in both namespaces. All match. The
exported Server sizes/offsets also equal the earlier `docs/lbosc3/layout.json`.
Locked sizes remain Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944,
Rob<64> 192, AtomicEntry 144 and Config 624. `layouts.py` reproduces this offline.

| Arm | SHA-256 | .text bytes |
| --- | --- | ---: |
| PRE | `26335d4df6753409a35c81b13e62b7c600be6467b27307e1421e4a1bc20291d8` | 7820053 |
| PAD-A (type A) | `e753a0131d1ccafd4b2316e0bb20de9d206f5bdddad103ac3785a39941834220` | 7845285 |
| POST | `ace49e7b1ccac5b37d65402644d244dadb2f9d1c69ae85b7e4486feb0eb1c849` | 7845285 |

Text delta is +25,232 bytes, controlled by the exact-layout type-A twin.
`docs/lbosc3/arms.json` and `SHA256SUMS` bind these artifacts.

### Harness and rerun commands

`--hotmax-2s` overrides only 2s; omitted, it inherits `--hotmax`. Seed mapping,
verification, hot/cold ranges and each run.json's existing `hotmax` field use the
effective value. `--probe-only 2s` keeps PRE seed population and bounded fresh
calibration, runs one PRE key-skew probe, then stops. Invalid telemetry stays
FAIL; zero moves stays REFUSED with exit 3. No scoring assertion or threshold was
relaxed. The replay functions and `tools/lbosc3_report.py` are unchanged; replay
of the original run still says 1s ARMED and 2s REFUSED. Replaying a probe-only run
continues to report the absent full matrix as incomplete, as intended.

Mainline's requested geometry, probe alone:

```sh
python3 tools/lb_episodes.py --dry-run --probe-only 2s --episodes key-skew \
  --server-cores 0-7 --load-cores 8-15 --hotmax 256 --hotmax-2s 64 \
  --arms docs/lbosc3/arms.json --output build/lbosc3/probe-lbosc3b-mainline

python3 tools/lb_episodes.py --probe-only 2s --episodes key-skew \
  --server-cores 0-7 --load-cores 8-15 --hotmax 256 --hotmax-2s 64 \
  --arms docs/lbosc3/arms.json --output build/lbosc3/probe-lbosc3b-mainline
```

The 112–127 variant, after a successful quiet preflight:

```sh
PYTHONPATH=tests python3 -c 'from gate_quiet import assert_quiet; assert_quiet(range(112,120), range(120,128), ports=(7931,))' && \
python3 tools/lb_episodes.py --probe-only 2s --episodes key-skew \
  --server-cores 112-119 --load-cores 120-127 --hotmax 256 --hotmax-2s 64 \
  --arms docs/lbosc3/arms.json --output build/lbosc3/probe-lbosc3b-2s
```

Requested one-invocation matrix at 1s=256, 2s=64 (1s **does not** meet the old
three-band margin; do not present it as satisfying that declaration):

```sh
python3 tools/lb_episodes.py --dry-run --episodes key-skew --rounds 6 \
  --server-cores 0-7 --load-cores 8-15 --hotmax 256 --hotmax-2s 64 \
  --arms docs/lbosc3/arms.json --output build/lbosc3/episodes-lbosc3b-256-64

python3 tools/lb_episodes.py --episodes key-skew --rounds 6 \
  --server-cores 0-7 --load-cores 8-15 --hotmax 256 --hotmax-2s 64 \
  --arms docs/lbosc3/arms.json --output build/lbosc3/episodes-lbosc3b-256-64
```

Model-compliant matrix at 1s=128, 2s=64, predeclared here and subject to fresh PRE
probes and actual-band inspection (no automatic change from 256):

```sh
python3 tools/lb_episodes.py --episodes key-skew --rounds 6 \
  --server-cores 0-7 --load-cores 8-15 --hotmax 128 --hotmax-2s 64 \
  --arms docs/lbosc3/arms.json --output build/lbosc3/episodes-lbosc3b-128-64

python3 tools/lb_episodes.py --episodes key-skew --rounds 6 \
  --server-cores 112-119 --load-cores 120-127 --hotmax 128 --hotmax-2s 64 \
  --arms docs/lbosc3/arms.json --output build/lbosc3/episodes-lbosc3b-128-64-reserved

python3 tools/lb_episodes.py --replay build/lbosc3/episodes-lbosc3b-128-64
python3 tools/lbosc3_report.py build/lbosc3/episodes-lbosc3b-128-64 \
  --json build/lbosc3/episode-judgment-lbosc3b.json
```

All recorded offline checks pass: both release namespaces, config parser, 14 LB
check groups with negative controls, 55 episode self-tests, three report tests,
87-spelling documentation check, six-round matrix and probe-only dry-runs,
layouts, complete hot inventory, and PAD-A source/ELF/negative-control proofs.
Logs and input/model/compile receipts are under `docs/lbosc3/lbosc3b`.
**Rows +0/+0; EXPECT remains 502/519, untouched by this lane.** The existing
LB monitor row is emitted at gate.sh:1353, collected at line 3240, before the
quick-tier exit at line 3402. No new row emitter was added. No push.
