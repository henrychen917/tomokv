**Lane nullpublish4 — GT1–GT5 / TIER 5.** Worktree `/home/user/Projects/cx-nullpublish4`, branch `cx-nullpublish4`. Scope: `/home/user/Projects/round3-read/config-gate.md`, section C, and `REGISTER.md`, TIER 5. Launch HEAD was `e279aeb4cf08ae2c39f26be679388b872fed4667`; the required first fetch/merge fast-forwarded to `b47544aad6cb8a81f835f54145b2387beade0bc7`. Subsequent fetch/merges, including immediately before this report, were already up to date.

The fixed holdout contract, matching block plan, reachable verifier, tracked publication and campaign generator are implemented and committed. **The requested all-pass expectation is contradicted by the saved samples.** The exact requested rule yields **95 within-floor cells and 86 FAIL cells**. Of the original 38 FAILs, **11 become PASS and 27 remain FAIL**; 59 former PASS/UNRESOLVED cells are outside the fixed two-sided bounds. They are all listed below. No bounds were widened using holdout observations, no samples were invented, and no failure was relabelled as a successful independent holdout.

Campaign 7 is committed as **`independent_resolution: PENDING HOLDOUT`**. Its original null and promotion bytes are intact. The historical `cx-final` dry run says **TRUSTED** for its recorded fingerprint/inventory, but is explicitly reporting-only, with a FAIL floor verdict. A fresh gate at this lane's new fingerprint must reject the archived null. `cx-final` also has different current measured runtime inputs, discussed below.

**What was wrong and what changed.** Original anchors below are those in the auditor's scope report; current anchors identify the implementation.

| Finding | Original mechanism | Change |
|---|---|---|
| GT1 | `tests/abbagate.py:624-634` used the current reference spread and published pooled delta, omitting published spread. `:466-471` applied a different validity bound. | `tests/abba_holdout.py:55` freezes each metric's floor; `:81` applies that same floor to both signs of the pooled delta and each arm's maximum block spread. Ordinary code-comparison rules are unchanged. |
| GT2 | `tests/abba_null_sampling.py:19-22,46-49` planned 1–4 null blocks; holdout always measured one. | `tests/abba_holdout.py:18,139` copies the published count, instances, samples/arm/block, cap and budget-limited flag before requesting repeats. All scheduled blocks finish, including after an outside-floor block. No holdout pilot or adaptive refitting. |
| GT4 | A zero reference spread could produce a zero threshold. | The published floor includes one metric quantum (`tests/abba_holdout.py:38`). All 188 replayed metric rows have positive floors. A one-quantum mean-latency step has a passing branch; larger steps can still fail. |
| GT5 | `overall()` at `tests/abbagate.py:909-916` made FAIL pre-empt null matching at `:2171,2188`; the independent checker was unreachable. | Explicit numeric `--null-holdout 1` selects a separate run kind. The final holdout branch at `tests/abbagate.py:2204` matches and validates even after a statistical FAIL. `tests/gate_receipt.py:418` also offers `verify-null-holdout --replay 1` for historical samples. |
| GT3 | Ignored `.gate-history/receipts/baselines/full-null.json` never crossed worktrees. | `tests/abba_standing_null.py:45,60,117` selects and loads a tracked receipt, preserves compressed original bytes and archives the transitive read-local proof files. `match_null` resolves those proofs by digest. Gate-result retention copies the same proof closure. |
| Generator | The old campaign predicted rc=3 from the null's UNRESOLVED labels and stopped before verification on rc=1. | `MEASURE-REQUEST-nullpublish3.md`'s single bash fence now passes `--null-holdout 1`, always invokes the verifier after the measured holdout, and commits tracked publication with PASS only after independent verification; otherwise PENDING HOLDOUT. It retains a failing exit code. |

The holdout floor for each published `(cell, metric)` is:

```text
F = max(published |pooled signed delta|, published maximum arm spread, published metric quantum %)
PASS iff |holdout pooled signed delta| <= F and max(holdout arm spreads) <= F
```

The instrument's existing signed pooling and maximum-per-block spread arithmetic are reused; no null statistic changes. Timing, completed ABBA order, saturation, workload witnesses, geometry and binary identity are still validated. A within-floor holdout can PASS even when the null's original resolution label is UNRESOLVED. That PASS certifies this holdout contract only: `comparison_trusted` stays false, null classifications stay intact, and no cycles/op or push receipt is inferred.

Quanta come only from published samples: rate is one counted command per central window; memtier mean latency is 0.001 ms; HDR tails use the existing lowest=10 µs, precision=2 geometry (8 µs buckets below 2.048 ms, then powers of two). The campaign's raw `null/t00/n16-1-A/load-15.json` header confirms that HDR geometry. The fixed percentage uses the null's pooled reference mean. Its floating-point conversion represents an actual one-quantum subtraction, avoiding a false failure at `.454 - .453` without a fitted tolerance.

**Replay results and budget.** The new verifier wrote `build/nullpublish4-final/holdout-resolution.json` and returned **1**, correctly retaining FAIL. Its committed copy is `tests/standing-null/campaign7-holdout-resolution.json`. This is a historical reinterpretation with both measured and evaluator fingerprints, the original comparison byte digest, every metric/bound, and every sample deficit; it is not new measurement evidence.

| Evidence | PRE / saved run | POST / fixed-floor replay |
|---|---:|---:|
| Cells | 181 | 181 |
| PASS / within floor | 105 | 95 |
| FAIL | 38 | 86 |
| Holdout cells labelled UNRESOLVED | 38 | 0 (original null labels retained separately) |
| Original FAIL cells now within floor | — | 11 |
| Independent verifier output | Absent / unreachable | Written, FAIL, PENDING HOLDOUT |
| Null resolution labels | 135 RESOLVING, 46 UNRESOLVED | Unchanged |
| Observed holdout blocks | 181 | Still 181; never synthesized |
| Required matched plan | Null: 249 blocks | 249 blocks; 50 cells short by 68 blocks |

The published schedule is 131 cells × 1 block, 41 × 2, and 9 × 4: **249 ABBA blocks**, two samples per arm per block, **498 samples per arm**. The existing cap remains **4 blocks / 8 samples per arm per cell**. Eight cells are budget-limited overall (`t00,m57,m63,t01,t02,t03,t05,t06`); six are in the seven-cell tail family. The task's six budget-limited count refers to that tail subset. The holdout's actual one-block data cannot retrospectively meet this plan, so even an all-within-floor historical replay would remain PENDING HOLDOUT.

The 11 old failures now within floor are: h34, h39, h54, h64, m07, m52, m57, m62, m65, t00, t02.

`t02/p999_ms` now passes: |delta| 8.978676%, published floor 17.759839%, while the old applied reference spread was only 2.693603%. Its long-command tail also passes (12.075472% delta versus 12.782956% floor). `t03/long_p999_ms` still fails: reference spread 22.946545% exceeds the published 21.789883% floor. The zero-floor null cell `m25/latency_ms` gains a 0.220751% quantum floor, but the actual holdout delta is 0.767544%, so it still fails.

Every remaining/new failure is below. All numbers are percentages; “spread” is the larger arm spread. The previous result is retained so the original 27 remaining FAILs are distinguishable from the 59 newly caught two-sided failures. Values are displayed to six decimals; decisions use the raw saved floats.

| Cell | Previous result | Metric | Fixed floor | Absolute delta | Maximum spread | Exceeds |
|---|---|---|---:|---:|---:|---|
| h01 | FAIL | rate | 1.562309 | 0.901061 | 2.712197 | spread |
| h08 | FAIL | rate | 1.287620 | 1.851370 | 1.760153 | delta, spread |
| h12 | FAIL | rate | 0.558625 | 0.607444 | 2.526304 | delta, spread |
| h13 | UNRESOLVED | rate | 4.403228 | 6.436985 | 2.068539 | delta |
| h14 | FAIL | rate | 0.140226 | 0.555300 | 3.184391 | delta, spread |
| h15 | FAIL | rate | 1.368860 | 1.749283 | 5.212888 | delta, spread |
| h16 | PASS | rate | 1.144607 | 1.553273 | 0.756855 | delta |
| h17 | PASS | rate | 0.143994 | 0.430189 | 1.152398 | delta, spread |
| h19 | PASS | rate | 0.886099 | 0.279507 | 1.356701 | spread |
| h21 | PASS | rate | 0.696706 | 0.203602 | 1.259609 | spread |
| h24 | PASS | rate | 0.197752 | 0.021009 | 0.240271 | spread |
| h27 | FAIL | rate | 1.584242 | 1.905290 | 3.736302 | delta, spread |
| h32 | PASS | rate | 0.159081 | 0.127009 | 0.295734 | spread |
| h35 | PASS | latency_ms | 1.066667 | 0.935829 | 1.069519 | spread |
| h37 | PASS | latency_ms | 0.925926 | 0.934579 | 1.869159 | delta, spread |
| h40 | FAIL | latency_ms | 1.342282 | 0.133156 | 3.723404 | spread |
| h43 | PASS | latency_ms | 1.068091 | 0.133511 | 1.869159 | spread |
| h44 | FAIL | latency_ms | 0.536193 | 0.947226 | 1.072386 | delta, spread |
| h45 | PASS | latency_ms | 1.342282 | 0.536913 | 1.879195 | spread |
| h47 | PASS | latency_ms | 0.538358 | 1.331558 | 0.269906 | delta |
| h48 | PASS | latency_ms | 0.801068 | 0.266667 | 1.066667 | spread |
| h49 | FAIL | latency_ms | 0.805369 | 0.673854 | 1.338688 | spread |
| h50 | PASS | latency_ms | 1.349528 | 0.270636 | 1.894452 | spread |
| h52 | FAIL | latency_ms | 0.811908 | 1.086957 | 1.075269 | delta, spread |
| h53 | PASS | latency_ms | 0.268097 | 0.267380 | 1.072386 | spread |
| h55 | FAIL | latency_ms | 0.537634 | 0.672948 | 1.069519 | delta, spread |
| h56 | PASS | latency_ms | 0.943396 | 0.676590 | 1.075269 | spread |
| h57 | PASS | latency_ms | 0.540541 | 0.134409 | 1.345895 | spread |
| h58 | PASS | latency_ms | 0.675676 | 1.070950 | 1.353180 | delta, spread |
| h59 | PASS | latency_ms | 0.673854 | 0.675676 | 1.081081 | delta, spread |
| h60 | PASS | latency_ms | 0.406504 | 0.271739 | 1.626016 | spread |
| h62 | PASS | latency_ms | 0.810811 | 0.403769 | 1.345895 | spread |
| h63 | PASS | latency_ms | 1.084011 | 0.134590 | 1.617251 | spread |
| m01 | PASS | latency_ms | 0.436681 | 0.543478 | 0.655738 | delta, spread |
| m04 | PASS | latency_ms | 0.450450 | 0.111857 | 0.671892 | spread |
| m08 | FAIL | rate | 0.633052 | 0.560359 | 1.235570 | spread |
| m11 | PASS | rate | 0.627691 | 0.360456 | 0.898132 | spread |
| m15 | FAIL | rate | 0.941779 | 0.338903 | 2.617756 | spread |
| m16 | PASS | latency_ms | 0.561798 | 0.561798 | 1.564246 | spread |
| m17 | PASS | rate | 1.013134 | 0.432914 | 1.779791 | spread |
| m20 | FAIL | rate | 0.910766 | 0.834552 | 1.746131 | spread |
| m22 | FAIL | latency_ms | 1.200000 | 1.509054 | 1.783944 | delta, spread |
| m24 | PASS | rate | 0.235291 | 0.349632 | 0.322577 | delta, spread |
| m25 | PASS | latency_ms | 0.220751 | 0.767544 | 0.220994 | delta, spread |
| m26 | PASS | rate | 1.716172 | 1.035505 | 1.958784 | spread |
| m27 | FAIL | rate | 1.225713 | 0.006690 | 2.544002 | spread |
| m29 | PASS | rate | 0.601630 | 0.280194 | 0.998862 | spread |
| m30 | FAIL | rate | 2.140284 | 1.129233 | 2.174999 | spread |
| m41 | PASS | rate | 0.485654 | 1.045656 | 1.386164 | delta, spread |
| m43 | PASS | latency_ms | 0.551876 | 0.110254 | 1.102536 | spread |
| m44 | PASS | rate | 1.386148 | 0.483073 | 1.839277 | spread |
| m46 | FAIL | latency_ms | 0.947867 | 1.488372 | 3.534884 | delta, spread |
| m49 | PASS | latency_ms | 0.220022 | 0.547046 | 0.437637 | delta, spread |
| m53 | PASS | rate | 0.236574 | 0.384778 | 0.291095 | delta, spread |
| m58 | PASS | latency_ms | 0.802752 | 0.341686 | 1.142857 | spread |
| m59 | PASS | rate | 0.452957 | 0.762261 | 0.239811 | delta |
| m61 | PASS | latency_ms | 0.661521 | 0.109769 | 0.879121 | spread |
| m69 | FAIL | rate | 8.079531 | 3.901479 | 8.827525 | spread |
| m71 | FAIL | rate | 0.111603 | 1.305117 | 2.479297 | delta, spread |
| m72 | PASS | rate | 0.756436 | 0.135713 | 1.124905 | spread |
| m73 | FAIL | latency_ms | 0.442478 | 0.555556 | 0.220994 | delta |
| m76 | PASS | latency_ms | 0.453515 | 0.341686 | 0.685714 | spread |
| m77 | PASS | rate | 0.158061 | 0.292062 | 0.423974 | delta, spread |
| m78 | PASS | rate | 0.471212 | 0.501954 | 0.650585 | delta, spread |
| m79 | PASS | latency_ms | 0.884956 | 0.111235 | 0.888889 | spread |
| m80 | FAIL | rate | 2.599791 | 0.740297 | 4.195460 | spread |
| m82 | PASS | latency_ms | 0.682594 | 0.113507 | 1.135074 | spread |
| m84 | PASS | rate | 0.393451 | 0.528959 | 0.989740 | delta, spread |
| m85 | FAIL | latency_ms | 0.445434 | 0.663717 | 2.197802 | delta, spread |
| m86 | PASS | rate | 1.360331 | 1.838473 | 1.174592 | delta |
| m88 | PASS | latency_ms | 0.340909 | 0.228311 | 0.456621 | spread |
| m90 | PASS | rate | 0.141029 | 0.003600 | 0.764201 | spread |
| m91 | PASS | latency_ms | 0.443459 | 0.444444 | 0.888889 | delta, spread |
| m94 | PASS | latency_ms | 0.574053 | 0.114416 | 0.685714 | spread |
| m96 | FAIL | rate | 1.740667 | 1.095553 | 2.264504 | spread |
| x01 | PASS | latency_ms | 0.803213 | 0.533333 | 1.600000 | spread |
| x02 | PASS | latency_ms | 0.534759 | 0.404858 | 1.349528 | spread |
| x03 | PASS | latency_ms | 0.811908 | 0.934579 | 1.078167 | delta, spread |
| x04 | PASS | latency_ms | 0.537634 | 0.270270 | 0.540541 | spread |
| x05 | PASS | rate | 1.050629 | 3.978266 | 0.743769 | delta |
| c01 | PASS | rate | 0.431048 | 0.370476 | 0.708706 | spread |
| c04 | FAIL | rate | 1.110213 | 0.337775 | 2.783419 | spread |
| a01 | PASS | rate | 1.084550 | 0.486376 | 1.342344 | spread |
| a02 | FAIL | rate | 0.596278 | 2.379354 | 6.605132 | delta, spread |
| a03 | PASS | rate | 1.491844 | 0.444551 | 1.957657 | spread |
| t03 | FAIL | long_p999_ms | 21.789883 | 9.387223 | 22.946545 | spread |

**Publication and trust proof.** `tests/standing-null/current.json` selects the immutable campaign-7 receipt; explicitly supplied null paths/environment overrides still take precedence. The receipt binds the original collection, promoted report, frozen campaign, instrument manifest, inventory, and three read-local proof artifacts. Its storage is gzip only, with compressed and uncompressed SHA-256s; decompression restores exact original bytes.

```text
Promoted null: 61,966,838 bytes
SHA-256: 8149f97d7e9de4718100fe77606b28d5394d2c59b5dde92a6dddc6adffd31054
Original collection SHA-256: 71ae3cef2740d07acdc595208e8b55a561df3186b3692282daeb9e1dd49ddf2a
Canonical null_control SHA-256: 5ef786e67bfc740944c9553b391e7e4dc0558860e5bf3c1e3d7cd1bed2e69d61
Published fingerprint: 3dcdaa497a4f1e2a670342e17daa27bb9c36e9a2cbc633196d134d85b65efb9a
Evaluator fingerprint: 885e5991fb01dbc52b16215103166af1e5bb570ddbe32dd90de63f478fd2fad3
```

A byte comparison of the committed gzip payload against campaign 7's external `promoted-null.json` passed. AST comparisons against post-merge `b47544aad` confirmed `null_resolution`, `null_result`, `validate_null_integrity` and `promote_null` unchanged; `abba_null_sampling.py` is byte-identical. The null still measures exactly the same data and promotes through the same mechanism.

The saved `tests/standing-null/campaign7-cx-final-match.json` records:

```text
headline ABBA standing null TRUSTED (historical replay; reporting only)
matched IDs: 181; original relative age: 32900 seconds
statistical_verdict: FAIL
current_runtime_inputs_match: false
full_gate_receipt: false
```

That command used `/home/user/Projects/cx-final`'s real instrument/inventory without modifying that worktree. Its HEAD when checked was `b5f7c94520dd903c806c5791300c06110fb10c84`. The existing smoke null is refused with: `null instrument differs; recollect with the current fingerprint (archived null remains historical)`. Unit controls also reject a changed inventory and a null older than 24 hours relative to the comparison.

**Limit on that TRUSTED result:** the historical comparison supplies its recorded geometry and imported inputs. Current `cx-final/tests/gate_measurements.json` hashes to `e3b7168ec4aa3ec9d43c7879ffe6f103e40241ed28d5bad41df19c0615529f2e`, unlike campaign 7's frozen `2868074717bdae936fabd260ce747fc2119b4d2be3557e5439ba7383c726ad01`. Its calibrated h01 floor is bound to older instrument `cc6c06bd…`; a current inventory certification refused it as unmeasured. The archive fixes transport. It does not replace or relabel current calibration, rejuvenate a timestamp, or certify the new instrument. A claim that a fresh current gate is now TRUSTED would be false.

Exactly these instrument dependency entries changed (five edited, three added):

```text
tests/_nullrefresh_test.py
tests/abba_evidence.py
tests/abba_holdout.py                 (new)
tests/abba_reorder_control.py
tests/abba_standing_null.py           (new)
tests/abbagate.py
tests/gate_receipt.py
tests/nullpublish4_test.py           (new)
```

The generator, its subprocess test, Markdown reports and JSON/gzip artifacts are outside the instrument's Python dependency manifest. The generator's own freeze now separately binds the normalized campaign-template hash. The Python executable/runtime identity did not change. No fingerprint compatibility exception was added. The owner can retain the already committed PENDING HOLDOUT publication, or rerun the campaign at the new fingerprint. Re-running only a holdout against the old fingerprint is intentionally refused; re-stamping the old null would invalidate its provenance.

**Serverless proofs.** All commands ran under `taskset -c 112-127`. No server, load generator, benchmark or gate ran. Refreeze tests used disposable identity files and a Makefile that copies them; none was executed as a server. The lane made no C++/layout change and built no production server binaries; PRE/POST/PAD arms are not applicable to this instrument fix.

| Command | Result |
|---|---|
| `python3 tests/abbagate.py --self-test` | 100 ABBA + 10 saturation + 9 calibration + 16 binary-storage checks, all PASS (135) |
| `python3 tests/gate_receipt.py --self-test` | 10 ledger-fixture + 18 receipt + 27 null-promotion + 10 holdout/publication + 1 refreeze checks, all PASS (66) |
| `python3 tests/abba_instrument.py --self-test` | 7/7 PASS |
| `python3 tests/nullpublish_refreeze_test.py` | PASS; real generator and exact campaign preflight in a disposable repo |
| `python3 tools/nullpublish_refreeze.py --generate-script` and `bash -n build/nullpublish-campaign.sh` | PASS; regenerated script equals the report fence |
| Changed Python modules compiled with `python3 -m py_compile`; `git diff --check` | PASS |

The initial broad test exposed malformed null JSON aborting diagnostics before sampling; this was corrected. The final certification-boundary guard was ordered after the existing partial-result refusal so that the prior null-promotion refusal contract remains intact. The final ABBA run also covers an absent inventory. No failing self-test was waived. Detailed logs are in `build/{abbagate,receipt,instrument,refreeze}-tests.log` and `build/nullpublish4-final/` (the historical match is also in `build/nullpublish4-proof/`).

The fixtures now retain real nonconstant campaign-7 samples, raw saturation/window evidence, all 181 cells, every null repeat, and the original source hashes in `tests/fixtures/nullpublish-campaign7-samples.json.gz`. Named positive/negative controls:

- `HoldoutControls.test_published_spread_makes_real_t02_pass_and_removing_it_fails_assertion`: the real t02 holdout passes; removing `values["spread"]` from the fixed maximum fails the assertion **“t02 must be within its published floor.”**
- `HoldoutControls.test_two_sided_drift_and_spread_use_same_immutable_floor`: both signs beyond the floor fail. Replacing `metric["absolute_delta_pct"] <= threshold` with `True` fails **“both signs outside the published floor must FAIL.”** A widened current spread cannot widen the threshold.
- `HoldoutControls.test_all_planned_repeats_finish_even_after_an_outside_floor_block`: truncating the throwaway repeat loop to one extra block fails **“holdout must finish the published block count.”**
- `ABBA.test_real_null_collection_comparison_and_subset_controls` exercises `main()` with fake workload/clock/boot boundaries. Complete within-floor holdouts PASS, and outside-floor holdouts write a FAIL resolution. Removing the final holdout verification branch fails **“outside-floor holdout must reach its resolution artifact.”** The throwaway function uses the same mocked globals; it never invokes real boot or quiet-observer paths.
- `PublicationControls.test_archive_matches_without_access_to_campaign_worktree`: archived evidence validates while filesystem reads outside this worktree raise an assertion. Changed fingerprint, inventory, age and compressed bytes are refused separately; retained gate evidence includes the same proof closure.
- `PromotionControls.test_independent_holdout_cannot_use_its_own_error_to_widen_resolution` also forges `comparison_trusted: true` on a passing holdout. Code-comparison certification still rejects the run kind; removing that guard makes the named refusal assertion fail.
- The all-inside routing fixture reuses the null's real samples **only as a unit control**, then proves `overall == PASS`. It is never presented as independent measurement evidence.

`--check` is still fail-closed. In this lane, only script generation was requested/performed; no landed production freeze exists, so `tools/nullpublish_refreeze.py --check` correctly refuses the missing `build/nullpublish-freeze.json`. The disposable refreeze test proves a valid freeze passes `--check`, idempotent refreeze leaves it unchanged, source changes require rebuilding, and stale manifest/script bytes fail the actual preflight. The generated lane script must not be run before a landed refreeze.

**Exact replay commands, no live work.** Run from this worktree; the verifier's rc=1 is expected for these saved samples. `--output` paths must be new, preserving earlier proof artifacts.

```bash
CAMPAIGN=/home/user/Projects/cx-nullrefresh/build/nullpublish-mainline-20261002T090358Z-24ptsC
PROOF=$(mktemp -d "$PWD/build/nullpublish4-replay-XXXXXX")
rc=0
taskset -c 112-127 python3 tests/gate_receipt.py verify-null-holdout --replay 1 \
  --campaign "$CAMPAIGN/frozen-campaign.json" --null-result tests/standing-null/current.json \
  --comparison "$CAMPAIGN/holdout/results.json" --output "$PROOF/holdout-resolution.json" || rc=$?
test "$rc" -eq 1
taskset -c 112-127 python3 tests/gate_receipt.py match-standing-null --replay 1 \
  --worktree /home/user/Projects/cx-final --null-result tests/standing-null/current.json \
  --comparison "$CAMPAIGN/holdout/results.json" --output "$PROOF/cx-final-match.json"
rc=0
taskset -c 112-127 python3 tests/gate_receipt.py match-standing-null --replay 1 \
  --worktree /home/user/Projects/cx-final \
  --null-result /home/user/Projects/cx-final/.gate-history/receipts/baselines/full-null.json \
  --comparison "$CAMPAIGN/holdout/results.json" || rc=$?
test "$rc" -eq 1
```

The positive `cx-final` historical command requires that worktree to retain the measured instrument/inventory; after its instrument advances it must reject, and its committed dry-run artifact remains the point-in-time proof.

**Exact MAINLINE live commands — owner only, on the scheduled quiet box.** This is the fresh-campaign option; retaining PENDING HOLDOUT requires no new measurement. Land/review this lane first. The refreeze command enforces a clean tree and HEAD at/behind `origin/cpp`; it internally builds with `taskset -c 112-127 make -j16 -B build/tomokv build/tailgen` and commits the managed freeze.

```bash
cd /home/user/Projects/cx-final
git fetch origin cpp
git merge --no-edit origin/cpp
taskset -c 112-127 python3 tools/nullpublish_refreeze.py --memtier /usr/bin/memtier_benchmark
taskset -c 112-127 python3 tools/nullpublish_refreeze.py --check
NULLREFRESH_MAX_INSTANCES=24 bash build/nullpublish-campaign.sh
bash tests/gate.sh iteration
# Owner's full receipt check, still subject to GT6 and UNRESOLVED comparison rules:
bash tests/gate.sh push
```

Measurement cells: full `tests/headline_cells.txt` (181 at this handoff), both 1s/2s modes and all registered geometries. Arms A and B are exactly the same frozen `build/tomokv-nullpublish-POST`. Preserve campaign-7-style 32 server physical cores (0–31), load cores 32–127 and load SMT 160–255, 20-second windows, and the explicit 24-instance ceiling. The script runs existing reorder controls/calibration/import/freeze/null/promotion unchanged, then the new independent holdout with the copied per-cell plan. The decision is every metric inside its **published** fixed bound and every scheduled block present; an outside cell or incomplete plan remains FAIL. The campaign commits the publication plus proof closure; it never pushes.

**Gate row accounting and owner decisions.** No new/retired gate rows. The existing **“ABBA comparison + saturation negative controls”** row begins at `tests/gate.sh:2387`, invokes the extended receipt self-test at `:2391`, and scores at `:2398-2399`. It is **before** the quick-tier exit at `:2878`, so the extended assertions run in both quick and full tiers with **zero count change**. At merged HEAD the counts remain **EXPECT_QUICK=447, EXPECT_FULL=464** (plus existing optional NIC accounting). The one-row increase from launch's 446/463 belongs to the fetched hexpirefix landing, not this lane. Neither constant was edited by this lane.

**GT6 is unchanged:** `tests/gate_receipt.py:682` still requires `args.abba_rc == 0` in the coordinator's successful push-receipt condition. A holdout PASS is not a code-comparison PASS or a push receipt; this lane does not resolve the owner's ABBA/push policy decision. Original null UNRESOLVED labels, cycles/op UNPROVEN and ceiling-only limitations remain explicit.

Code commits: `48587fdfb` (holdout contract/plan/replay), `0e747fa43` (tracked null and proofs), `66818a244` (campaign generator), `a283ebfe4` (stale-input diagnostics and real driver reachability control), `01a6cad06` (holdout/code-comparison certification boundary). Nothing was pushed. The report/proof commit follows.

**Diff from launch HEAD**, including the required upstream hexpirefix merge and this report/proofs:

```text
 MEASURE-REQUEST-hexpirefix.md                      |  288 ++
 MEASURE-REQUEST-nullpublish3.md                    |   37 +-
 MEASURE-REQUEST-nullpublish4.md                    |  289 ++
 Makefile                                           |    2 +-
 src/cmd/t_hash_ttl.cc                              |   10 +-
 tests/_nullrefresh_test.py                         |   56 +-
 tests/abba_evidence.py                             |   84 +-
 tests/abba_holdout.py                              |  187 +
 tests/abba_reorder_control.py                      |    3 +-
 tests/abba_standing_null.py                        |  198 +
 tests/abbagate.py                                  |  109 +-
 .../fixtures/nullpublish-campaign7-samples.json.gz |  Bin 0 -> 2977489 bytes
 tests/fixtures/nullrefresh-ledger-labels.json      |   35 +-
 tests/gate.sh                                      |    7 +-
 tests/gate_measurements.json                       |    6 +-
 tests/gate_receipt.py                              |  105 +-
 tests/hexpire_oom_checks.inc                       |  162 +
 tests/netcmd_unit.cc                               |    8 +-
 tests/nullpublish4_test.py                         |  225 +
 tests/nullpublish_refreeze_test.py                 |   10 +
 ...06b28d5394d2c59b5dde92a6dddc6adffd31054.json.gz |  Bin 0 -> 10408117 bytes
 ...7954cf75e7992b3c37d0e03e735a099764.receipt.json |    1 +
 ...c36e9a2cbc633196d134d85b65efb9a.instrument.json |    1 +
 tests/standing-null/README.md                      |   26 +
 ...a37d109520c052e248651bb757185c5b6ef88d8.json.gz |  Bin 0 -> 84413 bytes
 ...e8b55a561df3186b3692282daeb9e1dd49ddf2a.json.gz |  Bin 0 -> 12652543 bytes
 ...bc35559f54e81ee45a2c5b9f76188d2c2af0ac4.json.gz |  Bin 0 -> 90338 bytes
 ...a633af0ae9aea466e862cacb17e4bf59cc24fe7.json.gz |  Bin 0 -> 5391 bytes
 ...52dd9c56cc0597bedad45f6973220f345187333.json.gz |  Bin 0 -> 2288 bytes
 tests/standing-null/campaign7-cx-final-match.json  |  199 +
 .../campaign7-holdout-resolution.json              | 4944 ++++++++++++++++++++
 tests/standing-null/current.json                   |    1 +
 tools/nullpublish_refreeze.py                      |   24 +-
 33 files changed, 6900 insertions(+), 117 deletions(-)
```
