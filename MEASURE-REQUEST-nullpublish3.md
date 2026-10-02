# nullpublish3 — receipt duration and reproducible campaign re-freeze

The exact `job_abba_selftest` command chain passes in **199.21 s**, against the unchanged 900 s no-history budget and the requested 300 s target. The standalone `python3 tests/gate_receipt.py --self-test` passes in **85.32 s wall time**, below 90 s. In the exact chain, the two main receipt suites take **29.364 + 49.268 = 78.632 s**; ledger-fixture and re-freeze controls add 6.696 s. All **373 serverless tests** pass, with zero skips: 355 in the exact chain plus 11 directed-reorder and 7 existing campaign-diagnostic controls. The historical replay is now in the counted receipt suite.

Worktree `/home/user/Projects/cx-nullrefresh`, branch `cx-nullrefresh`. Launch HEAD: `6eade240dde0c8a79c2c3f3f2b333b3d77d5ea25`. The first repository mutation was `git fetch origin cpp` followed by `git merge --no-edit origin/cpp`, producing `955107d649c227314ac9388c8349152636f1e4dc` from upstream `2a9e484035960b0ba5925824cc581148c359c0f8`. Every build/test process in this lane used cores **112–127**. No real server build, server, benchmark, load generator, campaign, gate invocation, or push was run. The re-freeze integration test uses a disposable repository whose Makefile copies identity strings into executable artifacts; none of those artifacts is executed.

The merge brought upstream changes to `src/core/ex_loop.h`, `tests/rltopo_unit.cc`, measurement inputs, and the readreply report/tool. There are **no authored changes** to `src`, `third_party`, `Makefile`, `tools/tailgen`, or `tests/gate.sh` relative to the merge. Both EXPECT constants, the row list, the row identity/context and the row budget remain unchanged: **446 quick / 463 full**. All added controls run inside the existing ABBA negative-control row, collected before the quick-tier exit. No count change is requested. No PAD or server-performance claim is involved.

**Profile and diagnosis.** I first ran `taskset -c 112-127 python3 -m cProfile -o build/nullpublish3-before.prof tests/gate_receipt.py --self-test`. The prefix profile recorded 338,385,354 calls in 393.680 s: `instrument_fingerprint` accounted for 314.793 s over 108 calls; AST walking took 139.648 s and parsing 71.810 s, nested inside that total. This diagnostic was interrupted after cProfile's execution namespace broke a test that patches `__main__`; it is not counted as a passing run or used as the timing baseline. The complete baseline instead uses an import-safe per-test timer, retaining all tests and real validators.

That full profile found two different costs. Receipt tests repeatedly parsed the same Python source and resolved duplicate imports. The campaign mutation test took **240.879 s** by itself: JSON decode 104.804 s, fingerprinting 67.133 s, JSON encode 25.789 s; mock recording on every scalar validation amplified the decode cost. Independent-holdout validation took 40.697 s, including 17.396 s of JSON encoding. `fsync` was negligible (0.088 s across the mutation test). No receipt test needed a real 20-second window or injected sleep. The historical source available here is **83,048,481 bytes**, rather than the estimated 900 MB.

**Changes by file.**

- `tests/abba_instrument.py`: bounded, byte-keyed cache of parsed import syntax, plus import-resolution reuse within one fingerprint. Every fingerprint still rereads/hashes file bytes, checks modes and symlinks, and resolves modules afresh. The two added controls catch newly created local modules and same-size edits with the original mtime restored. Runtime identity, scope, roots and manifest validation remain mandatory; no fingerprint result or acceptance decision is cached.
- `tests/_nullrefresh_test.py`: keep the full 181-cell inventory and every ABBA/repeat block, using the minimum two server threads needed for both split roles. Disposable configs explicitly declare a synthetic 1:1 geometry; 32 load CPUs retain the real higher-capacity plateau confirmation. Ceiling controls retain their 24-instance ladder. Guard-removal patches use plain functions plus their original explicit hit witnesses, avoiding a Mock call object for every valid scalar. The real ratio, saturation, workload, import, freeze, promotion and holdout validators still run. Independent per-test receipt Git repositories remain independent.
- `tests/gate_receipt.py`: replay reads historical bytes once and hashes those same parsed bytes, retaining duplicate-key/nonfinite rejection. Add the re-freeze integration control to `--self-test`; no publication/status/threshold policy changes. An added test rejects a second read and checks the returned digest.
- `tests/fixtures/nullpublish-campaign6-compact.json`: **95,796-byte** reporting-only derivative containing every original raw metric block and all 188 independent expected CSV rows. A single read of the original, whose SHA-256 is `501cefeeba9d1f3bb9a2d07ddfd8e6a9f641c422f1758c24f6d0d4fcadfecbb5`, checked exact equality of `null_resolution(original)` and `null_resolution(compact)` before saving it. Fixture SHA-256: `c1d94b53a501e782224ed2a6fa5dfc90bee5b54c114930baad8f6dc3d72c7168`. The test replays the compact data, checks every expected status/spread/delta and exact counts, refuses it as promotion evidence, and detects classification removal. Derivation: `build/nullpublish3-save-replay.py`; proof: `build/nullpublish3-replay-derivation.log`.
- `tests/gates_test.py`: prepare independent full-inventory scheduler fixtures in at most four disjoint groups of at most four inherited CPUs. Each scenario still runs the real scheduler and every source-declared family; identical scenarios share a class fixture. All original per-family assertions remain. The open-before-write publication hook now directly checks that the public `done` name is absent after redirection opened the private file and before any record byte is written. Every family's hook must fire exactly once. A direct-publication mutant must hit that exact refusal. The former artificial 0.6 s pause per family remains opt-in via `TOMO_GATE_SLOW_PUBLICATION=1 python3 tests/gates_test.py`; the gate does not set it. Existing bounded process/watchdog integration controls remain intact.
- `tools/nullpublish_refreeze.py` and `tests/nullpublish_refreeze_test.py`: the one-command mainline workflow and real-command serverless controls described below. These are committed with the report/fence, so the next mainline re-freeze needs no new lane.

Static assertion inventory (`build/nullpublish3-static-proof.log`) retains all original test methods and assertion calls in the four changed test modules: receipt **18 / 59**, campaign **25 / 126**, fingerprint **5 / 13**, scheduler **57 / 213** (methods / assertion calls). The comparison normalizes only the synthetic `fixture_measurements()` factory back to the old `measurements.load()` call. Runtime negative controls independently verify the assertions still reject the intended failures.

**Before/after suite timings, cores 112–127.** The PRE snapshot is the merged launch tree under `build/nullpublish3-PRE`; it completed successfully in **1218.67 s** without applying the gate timeout. Its receipt suite used lightweight per-test timing hooks around the real functions. POST below is the unmodified direct CLI command chain. The matched POST diagnostic wrapper also passed: receipt 29.517 s, campaign/sampling 49.980 s (versus direct CLI 29.364 / 49.268 s). The complete chain's external wall timer is independent of these unittest-reported suite times.

| Suite | Tests PRE → POST | PRE s | POST s |
|---|---:|---:|---:|
| ABBA comparison | 100 → 100 | 170.106 | 22.193 |
| Saturation | 10 → 10 | 0.008 | 0.008 |
| Load calibration | 9 → 9 | 2.265 | 0.458 |
| Binary storage | 16 → 16 | 0.418 | 0.397 |
| Quiet observer | 8 → 8 | 0.023 | 0.023 |
| Calibration importer | 11 → 11 | 23.424 | 2.412 |
| Ledger fixture | 10 → 10 | 0.267 | 0.267 |
| Receipt Controls | 18 → 18 | 250.185 | 29.364 |
| Campaign / sampling / replay | 25 → 27 | 470.398 | 49.268 |
| Re-freeze preflight | new → 1 | — | 6.429 |
| Instrument fingerprint | 5 → 7 | 5.447 | 0.699 |
| Background environment | 11 → 11 | 0.001 | 0.001 |
| History / watchdog | 55 → 55 | 21.254 | 21.236 |
| Process ownership | 12 → 12 | 0.476 | 0.475 |
| Shell gate / scheduler | 57 → 57 | 272.089 | 64.700 |
| Tailgen instrument | 3 → 3 | 0.008 | 0.008 |

**Exact command chain.** `build/nullpublish3-exact-chain.sh` copies this list from `tests/gate.sh`, along with the real `py`, `quiet_ok` and `quiet_wait` functions. The wrapper invokes no enclosing gate runner or row watchdog; watchdog processes belong to the serverless ownership/scheduler fixtures. No server or measurement is launched. The opt-in cooperative quiet file is unset, matching the gate's default. Invoked as `taskset -c 112-127 /usr/bin/time -f '%e' -o build/nullpublish3-exact-chain.seconds bash build/nullpublish3-exact-chain.sh`. It ended with `ALL-SUITES-OK`; wall time **199.21 s**. The unchanged gate budget was never edited or used to hide a failure.

```sh
py tests/abbagate.py --self-test > $TMPDIR/gate-abbagate-unit.txt 2>&1 \
    && py tests/gate_quiet.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 \
    && py tests/gate_measurements.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 \
    && py tests/gate_receipt.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 \
    && py tests/abba_instrument.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 \
    && py tests/background_environment_test.py >> $TMPDIR/gate-abbagate-unit.txt 2>&1 \
    && py tests/gate_history.py self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1 \
    && py tests/gate_process_test.py >> $TMPDIR/gate-abbagate-unit.txt 2>&1 \
    && py tests/gates_test.py >> $TMPDIR/gate-abbagate-unit.txt 2>&1 \
    && py tests/tailgen_stall.py --self-test >> $TMPDIR/gate-abbagate-unit.txt 2>&1
```

`abbagate.py --self-test` itself invokes saturation, calibration and binary-storage controls; they are not separate invented rows. The exact chain ran 355 tests. Additional commands were `python3 tests/legacy_reorder_witness.py --self-test` (11) and `python3 build/nullpublish-preflight-controls.py` (7), both pinned to 112–127. The latter exercises the report's exact instrument diagnostic, including missing/reformatted manifests and diagnostic/exit removal. `build/nullpublish3-checks.json` records timings, counts, CPU allocation and SHA-256 hashes of the evidence logs.

**Required negative proofs, on the fast path.**

- Unresolved-as-PASS: the full 181-cell campaign promotes 180 resolving cells and one reporting-only `h01`. A forged PASS coordinator cannot mint a receipt; changing the assessor to label unresolved non-loss as PASS fails the exact assertion. Loss beyond the independently frozen floor still fails.
- Veto restoration: reinstating the removed magnitude veto makes that otherwise valid unresolved publication fail. The original rejection/removal assertion detects the restored veto. No tolerance was widened.
- Truncated repeats: deleting a repeat refuses with `incomplete fixed null sampling plan`. Removing validation makes the rejection oracle fail. A high-CV pilot still needs 25 samples/arm, stops at the frozen cap of 8 samples/arm / 4 blocks, and stays UNRESOLVED; the maximum raw spread remains 20%.
- Historical replay: **188 rows / 141 RESOLVING / 47 UNRESOLVED**, `t00/p999_ms` reference spread **11.68%**. Every CSV row also matches at its recorded three-decimal precision. Classification removal fails the count/map oracle; no PASS evidence or promotable identity is acquired.
- Re-freeze: after a changed synthetic server is rebuilt and committed, the exact campaign preflight prefix accepts the new artifacts. Restoring the prior checksum manifest produces both `build/tomokv-nullpublish-POST: FAILED` and `stale artifact manifest differs from freeze`, with no preflight-complete marker. Dirty tracked/untracked trees, an unlanded HEAD, a stale script/fence and an immediate unlanded re-freeze commit all refuse.

**One-command re-freeze after wbhybrid3 lands.** From a clean mainline branch whose HEAD is an ancestor of or equal to `origin/cpp`, run **`tools/nullpublish_refreeze.py`**. `--memtier /path/to/memtier_benchmark` can select the generator; the default is the installed `memtier_benchmark`. No server or load generator is executed by this command. All children inherit cores 112–127.

The command forces `make -B -j16 build/tomokv build/tailgen`, stages independent POST/tailgen/memtier copies, regenerates the instrument snapshot and schema-3 freeze JSON, records SHA-256/size/mode identities, writes the checksum manifest, updates the fence's single frozen-commit anchor, and regenerates `build/nullpublish-campaign.sh` byte-for-byte from this report. It validates the result and commits the managed report block/fence with message **`refreeze on <full source sha>`**. Binary artifacts and build-side JSON/checksums remain in ignored `build/`; their identities are committed in this report. It never pushes.

No-op idempotence follows the ancestry rule: once a generated re-freeze commit has landed, a rerun with unchanged inputs/artifacts preserves the commit, report and freeze bytes and skips rebuilding. An immediate rerun while that generated commit is still ahead of `origin/cpp` refuses without mutation, preserving the explicit upstream guard. A changed server or instrument requires a rebuild and a new anchor. A failed build leaves previously frozen copies unpublished. `--check` performs only the serverless preflight.

The real server has **not** been re-frozen in this lane: campaign 7 is for the maintainer after the writeback constant lands. The managed block below is deliberately pending; the campaign preflight requires the new schema-3 freeze and rejects the old artifacts. The current provisional fence equals `build/nullpublish-campaign.sh`, and both pass `bash -n`. After the mainline command runs, the same equality is checked again before commit. Both campaign arms use the newly frozen POST; the calibration, controls, bounded null collection, promotion and independent holdout contracts below are retained.

<!-- nullpublish-freeze:start -->
```json
{
  "artifacts": [
    {
      "bytes": 177015840,
      "mode": 509,
      "path": "build/tomokv-nullpublish-POST",
      "sha256": "9a2015290b396e69095d2b909404c981810ce4c8ab92370a3f5fcf95b39b94f9"
    },
    {
      "bytes": 2911008,
      "mode": 509,
      "path": "build/tailgen-nullpublish-frozen",
      "sha256": "613a6a7e115ba522753a37015a2dbb799325e915030a9f8c3ae95c3a8f4a2d05"
    },
    {
      "bytes": 616272,
      "mode": 493,
      "path": "build/memtier-nullpublish-frozen",
      "sha256": "9b6ee614dae154c64b17a067a10236b3e6532f7ca52c43b547b87101556dd7d4"
    },
    {
      "bytes": 4575,
      "mode": 436,
      "path": "build/nullpublish-POST.instrument.json",
      "sha256": "c0bfe33b3173fb300658b15afcd726a077f092a84aa6a7ee55c65c612bd07527"
    },
    {
      "bytes": 22584,
      "mode": 436,
      "path": "tests/headline_cells.txt",
      "sha256": "d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350"
    },
    {
      "bytes": 504953,
      "mode": 436,
      "path": "tests/gate_measurements.json",
      "sha256": "de8a1076e86cb04d946f8f55118158dbfd0260dc9dba9069d966d3632c8aab5b"
    }
  ],
  "build_command": "make -B -j16 build/tomokv build/tailgen",
  "build_cpus": "112-127",
  "campaign_arms": {
    "A": "build/tomokv-nullpublish-POST",
    "B": "build/tomokv-nullpublish-POST"
  },
  "inputs": {
    "build_tree": "3a896c6d2860353c9b256fa915667ac9a39c5692b8e32067771fc836f588e9e8",
    "cells_sha256": "d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350",
    "instrument_sha256": "c0bfe33b3173fb300658b15afcd726a077f092a84aa6a7ee55c65c612bd07527",
    "measurements_sha256": "de8a1076e86cb04d946f8f55118158dbfd0260dc9dba9069d966d3632c8aab5b",
    "memtier_sha256": "9b6ee614dae154c64b17a067a10236b3e6532f7ca52c43b547b87101556dd7d4",
    "refreeze_sha256": "9984dd07ac9cc537691175956f96980deb734fd2082ad9968f67fac1f97cfc52"
  },
  "kind": "nullpublish-build-freeze",
  "measurements_run": false,
  "schema": 3,
  "source_commit": "6fd07a0aab77cab00787195221c34909ac34806d"
}
```
<!-- nullpublish-freeze:end -->

**Per-test profile detail.** PRE and POST here use the same import-safe timer (`build/nullpublish3-receipt-timing.py`) and CPU allocation. Each duration includes setup, body and cleanup. The final column lists the largest instrumented PRE categories, not an additive decomposition: fingerprinting contains some JSON encoding, and untimed residual work includes deepcopy, validators, subprocesses and cleanup. The separate suite table includes class setup and the new re-freeze subprocess. Raw per-test data is in `build/nullpublish3-before.per-test.json` and `build/nullpublish3-after.per-test.json`.

| Test | PRE s | POST s | Largest timed PRE sinks |
|---|---:|---:|---|
| `FixtureControls.test_count_only_drift_is_actionable` | 0.026 | 0.026 | JSON decode 0.000s |
| `FixtureControls.test_current_inventory_and_duplicate_occurrences` | 0.025 | 0.025 | JSON decode 0.000s; JSON encode 0.000s |
| `FixtureControls.test_future_literal_row_names_missing_label` | 0.025 | 0.025 | JSON decode 0.000s; JSON encode 0.000s |
| `FixtureControls.test_future_loop_row_names_missing_label` | 0.025 | 0.025 | JSON decode 0.000s; JSON encode 0.000s |
| `FixtureControls.test_partial_fixture_cannot_redefine_inventory_via_count` | 0.026 | 0.026 | JSON decode 0.000s; JSON encode 0.000s |
| `FixtureControls.test_receipt_refuses_once_before_control_setup` | 0.026 | 0.026 | JSON decode 0.000s; JSON encode 0.000s |
| `FixtureControls.test_retired_row_names_extra_label` | 0.025 | 0.025 | JSON decode 0.000s; JSON encode 0.000s |
| `FixtureControls.test_same_count_substitution_and_duplicate_loss_are_rejected` | 0.049 | 0.051 | JSON decode 0.000s; JSON encode 0.000s |
| `FixtureControls.test_stale_wbland_fixture_names_both_missing_labels` | 0.025 | 0.025 | JSON decode 0.000s; JSON encode 0.000s |
| `FixtureControls.test_unsupported_label_expression_refuses_without_evaluation` | 0.013 | 0.013 | JSON decode 0.000s; JSON encode 0.000s |
| `Receipt.test_actual_begin_reads_explicit_previous_ledger_before_rotation` | 3.968 | 1.376 | fingerprint 2.673s; JSON encode 0.101s |
| `Receipt.test_actual_git_refs_hook_and_commit_after_validation` | 6.605 | 2.448 | fingerprint 4.261s; JSON encode 0.471s |
| `Receipt.test_actual_history_recorder_matches_context_and_unscored_prerequisites` | 5.087 | 1.407 | fingerprint 3.860s; JSON encode 0.250s |
| `Receipt.test_actual_shell_receipt_blocks_do_not_short_circuit_work_or_certify_iteration` | 7.924 | 3.077 | fingerprint 2.797s; JSON encode 0.101s |
| `Receipt.test_explicit_unscored_dependencies_and_context_do_not_change_counts` | 4.922 | 1.262 | fingerprint 3.887s; JSON encode 0.378s |
| `Receipt.test_full_inventory_cannot_retire_a_multikey_geometry` | 3.766 | 0.505 | fingerprint 3.433s; JSON encode 0.103s |
| `Receipt.test_future_full_row_count_needs_new_baseline_and_actual_observation` | 10.809 | 1.514 | fingerprint 9.519s; JSON encode 0.431s |
| `Receipt.test_ignored_generated_outputs_preserve_fingerprint_but_tracked_ignored_files_count` | 6.482 | 1.242 | fingerprint 5.403s; JSON encode 0.360s |
| `Receipt.test_ledger_and_comparison_guards_have_individual_removal_controls` | 35.370 | 3.311 | fingerprint 23.228s; JSON decode 7.241s |
| `Receipt.test_missing_baseline_retains_start_binding_and_completed_work_without_receipt` | 17.741 | 0.684 | fingerprint 16.791s; JSON encode 0.211s |
| `Receipt.test_missing_rows_cannot_pass_by_count_or_exit_zero` | 15.502 | 0.746 | fingerprint 14.310s; JSON encode 0.241s |
| `Receipt.test_prior_null_may_have_other_correctness_harness_but_comparison_cannot` | 16.655 | 1.246 | fingerprint 13.890s; JSON encode 1.052s |
| `Receipt.test_selected_core_quiet_evidence_and_diagnostic_poison_controls` | 53.794 | 2.910 | fingerprint 47.398s; JSON decode 2.059s |
| `Receipt.test_smoke_partial_failed_unreached_quiet_and_null_controls` | 36.692 | 4.173 | fingerprint 30.853s; JSON encode 1.256s |
| `Receipt.test_standing_null_replays_saturation_instead_of_cached_pass` | 4.319 | 0.719 | fingerprint 3.691s; JSON encode 0.108s |
| `Receipt.test_start_end_and_push_source_binary_mode_and_symlink_identity` | 9.622 | 1.328 | fingerprint 7.824s; JSON encode 0.575s |
| `Receipt.test_unresolved_cell_names_withhold_receipt_even_with_forged_pass_coordinator` | 7.058 | 1.029 | fingerprint 6.233s; JSON encode 0.269s |
| `Receipt.test_worktree_hook_config_is_reversible_without_common_changes` | 3.771 | 0.487 | fingerprint 3.424s; JSON encode 0.104s |
| `PromotionControls.test_absent_and_stale_prior_null_bootstrap_without_receipt` | 15.130 | 2.034 | fingerprint 5.414s; JSON encode 3.543s |
| `PromotionControls.test_age_ladder_window_and_fixed_resolution_checks_cannot_be_bypassed` | 22.950 | 2.304 | JSON decode 7.579s; fingerprint 7.234s |
| `PromotionControls.test_ceiling_import_freeze_promotion_holdout_and_forgery_controls` | 27.248 | 4.394 | JSON encode 8.837s; fingerprint 5.252s |
| `PromotionControls.test_current_instrument_config_generator_and_inventory_cannot_change` | 4.398 | 0.624 | fingerprint 2.745s; JSON decode 1.031s |
| `PromotionControls.test_freeze_requires_full_replayed_import_and_is_immutable` | 10.213 | 1.174 | fingerprint 6.377s; JSON encode 1.373s |
| `PromotionControls.test_independent_holdout_cannot_use_its_own_error_to_widen_resolution` | 40.697 | 5.705 | JSON encode 17.396s; fingerprint 1.511s |
| `PromotionControls.test_interrupted_atomic_replace_and_executable_byte_mutation` | 13.791 | 1.694 | fingerprint 4.714s; JSON encode 3.642s |
| `PromotionControls.test_mutations_reject_before_replacing_previous_default` | 240.879 | 18.449 | JSON decode 104.804s; fingerprint 67.133s |
| `PromotionControls.test_read_local_campaign_missing_or_supplementary_proof_cannot_repair_collection` | 2.463 | 0.478 | JSON encode 0.918s; JSON decode 0.292s |
| `PromotionControls.test_read_local_collection_uses_real_workload_path_once_and_retains_failures` | 2.483 | 0.266 | fingerprint 0.819s; JSON decode 0.652s |
| `PromotionControls.test_read_local_freeze_binds_precalibration_receipt_and_requires_it` | 7.561 | 0.926 | fingerprint 4.436s; JSON encode 1.101s |
| `PromotionControls.test_read_local_raw_proof_replay_and_per_guard_removal` | 2.138 | 0.399 | JSON encode 0.913s; JSON decode 0.272s |
| `PromotionControls.test_read_local_receipt_inventory_time_geometry_and_artifact_guards` | 0.748 | 0.177 | JSON encode 0.330s; JSON decode 0.203s |
| `PromotionControls.test_read_local_receipt_reused_without_rerunning_directed_controls` | 2.152 | 0.386 | JSON encode 0.916s; JSON decode 0.290s |
| `PromotionControls.test_read_local_zero_permutations_promote_and_holdout_with_frozen_control` | 22.985 | 3.368 | JSON encode 8.991s; fingerprint 2.397s |
| `PromotionControls.test_removed_promotion_validation_is_detected_per_mechanism` | 11.603 | 1.784 | fingerprint 3.799s; JSON encode 2.786s |
| `PromotionControls.test_unresolved_complete_campaign_freezes_promotes_and_cannot_earn_pass` | 33.792 | 4.950 | JSON encode 12.480s; fingerprint 4.582s |
| `NullpublishControls.test_cv_permits_fixed_repeats_and_all_signed_deltas_pool_to_resolving` | 0.012 | 0.004 | JSON encode 0.004s; fsync 0.000s |
| `NullpublishControls.test_repeat_plan_cannot_be_missing_truncated_reordered_or_refitted` | 0.032 | 0.007 | JSON encode 0.005s; fsync 0.000s |
| `NullpublishControls.test_replay_is_reporting_only_and_rejects_nonfinite_nonpositive_or_incomplete_blocks` | 0.012 | 0.004 | JSON decode 0.002s; JSON encode 0.001s |
| `NullpublishControls.test_unattainable_cv_stops_at_frozen_budget_and_raw_maximum_never_shrinks` | 0.034 | 0.008 | JSON encode 0.012s; fsync 0.000s |
| `NullpublishControls.test_unresolved_nonloss_is_reporting_only_and_beyond_floor_still_fails` | 0.019 | 0.006 | JSON encode 0.007s; fsync 0.000s |
| `ExemptionControls.test_each_depth_only_branch_restoration_breaks_its_exempt_fixture` | 3.612 | 0.246 | fingerprint 3.537s; JSON decode 0.019s |
| `ExemptionControls.test_p999_depth32_and_p1_mixed_and_all_exempt_import_replay` | 2.579 | 0.219 | fingerprint 2.359s; JSON encode 0.064s |
| `ExemptionControls.test_unsaturated_depth32_rate_cannot_claim_exempt_even_when_predicate_removed` | 0.003 | 0.001 | JSON encode 0.001s; fsync 0.000s |

**Campaign 7 fence.** Re-freeze on landed mainline first using the command above.

```bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
FROZEN_COMMIT=6fd07a0aab77cab00787195221c34909ac34806d
# Set NULLREFRESH_MAX_INSTANCES=24 explicitly BEFORE a fresh campaign, if desired.
MAX_INSTANCES="${NULLREFRESH_MAX_INSTANCES:-16}"
case "$MAX_INSTANCES" in 16|24) ;; *) echo 'Choose 16 or 24 instances' >&2; exit 2;; esac
RUN=$(mktemp -d "$PWD/build/nullpublish-mainline-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
STABLE="$PWD/build/tomokv-nullpublish-POST"
GEN="$PWD/build/memtier-nullpublish-frozen"
CELLS="$PWD/tests/headline_cells.txt"
NULL="$PWD/.gate-history/receipts/baselines/full-null.json"
CONTROL="$RUN/reorder-controls/receipt.json"
expect_rc() {
  local expected=$1 actual=0
  shift
  "$@" || actual=$?
  if test "$actual" -ne "$expected"; then
    echo "Expected rc=$expected, got rc=$actual: $*" >&2
    return 1
  fi
}
check_instrument() {
  taskset -c 112-127 python3 - "$1" "$2" <<'PY'
import difflib
import json
from pathlib import Path
import sys

paths = [Path(name) for name in sys.argv[1:]]
try:
    raw = [path.read_bytes() for path in paths]
    manifests = [json.loads(value) for value in raw]
    entries = [sorted(f"{row['path']}\t{row['mode']}\t{row['sha256']}\n"
                      for row in manifest['entries']) for manifest in manifests]
    metadata = [json.dumps({key: value for key, value in manifest.items()
                           if key != 'entries'}, sort_keys=True, indent=2).splitlines(True)
                for manifest in manifests]
except (OSError, ValueError, KeyError, TypeError) as error:
    print(f"Invalid instrument manifest: {error}", file=sys.stderr)
    raise SystemExit(1)
if raw[0] == raw[1]:
    print(f"Instrument matches frozen manifest: {manifests[0]['sha256']}")
    raise SystemExit(0)
print("INSTRUMENT MISMATCH; no measurement may continue.", file=sys.stderr)
print("File entries: path, Git mode, SHA-256 (- frozen; + current):", file=sys.stderr)
changes = list(difflib.unified_diff(*entries, fromfile=str(paths[0]),
                                  tofile=str(paths[1]), n=1))
sys.stderr.writelines(changes)
if not changes:
    print("File lists, modes and hashes are identical; inspect metadata below.", file=sys.stderr)
print("Metadata (scope, roots, Python identity, aggregate digest):", file=sys.stderr)
sys.stderr.writelines(difflib.unified_diff(*metadata, fromfile=str(paths[0]),
                                        tofile=str(paths[1]), n=1))
if manifests[0] == manifests[1]:
    print("Only JSON serialization differs; exact frozen bytes are required.", file=sys.stderr)
print("Use the artifact checksum results and frozen/current commits above to distinguish "
      "a moved tree from changed frozen artifacts. Preserve this run and re-freeze "
      "deliberately; do not overwrite the expected manifest to bypass this check.", file=sys.stderr)
raise SystemExit(1)
PY
}
COMMON=(--subset full --cells "$CELLS" --candidate "$STABLE"
        --memtier "$GEN" --server-cores 0-31 --server-smt ''
        --load-cores 32-127 --load-smt 160-255 --max-instances "$MAX_INSTANCES"
        --ports 8700-8799 --port 8700 --build-reference 0 --binary-store "$RUN")

# Diagnose instrument drift before the clean-tree/ancestry guards can stop us.
printf 'Frozen source commit: %s\nCurrent HEAD: %s\n' \
  "$FROZEN_COMMIT" "$(git rev-parse HEAD)"
printf '%s\n' "$MAX_INSTANCES" > "$RUN/max-instances"
cp build/nullpublish-freeze.json "$RUN/instrument-freeze.json"
cp tests/gate_measurements.json "$RUN/before-calibration-inputs.json"
# Do not exit on a checksum failure until the file-level diagnostic has run.
artifact_rc=0
sha256sum -c build/nullpublish-campaign.sha256 || artifact_rc=$?
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/instrument.json"
check_instrument build/nullpublish-POST.instrument.json "$RUN/instrument.json"
taskset -c 112-127 python3 tools/nullpublish_refreeze.py --check
if test "$artifact_rc" -ne 0; then
  echo 'Frozen artifact or initial input checksum mismatch; stop before calibration.' >&2
  exit 1
fi
if test -n "$(git status --porcelain --untracked-files=normal)"; then
  echo 'Worktree changed since freeze; review these paths before a fresh campaign:' >&2
  git status --short >&2
  exit 1
fi
git merge-base --is-ancestor "$FROZEN_COMMIT" HEAD
# Retain the server/tailgen build inputs recorded by this committed re-freeze.
git diff --exit-code "$FROZEN_COMMIT" -- src third_party Makefile tools/tailgen
cmp build/tomokv "$STABLE"
cmp build/tailgen build/tailgen-nullpublish-frozen
sha256sum "$STABLE" "$GEN" "$CELLS" build/tailgen > "$RUN/before-calibration.sha256"

# Preflight BEFORE any control, calibration, server or generator. Reserve the
# 40 GiB disk-guard floor plus 1536 MiB of artifacts and one copy per unique arm.
# Identical null arms occupy one inode. Every phase below only adds hard links.
# A refusal here creates no binary snapshot; never prune an active run to proceed.
taskset -c 112-127 python3 tests/abba_binaries.py --run "$RUN" --candidate "$STABLE"
sha256sum "$RUN/binaries.json" > "$RUN/binary-manifest.sha256"

# Once per campaign, BEFORE calibration/freeze/null: dynamically select every
# rl=1 REORDER cell (currently t05 and t06), run its workload with --read-local
# 0 and 1, and retain the armed directed reorder 0/1 proof required by t05.
# These are unscored controls at the campaign geometry, on the same frozen bytes.
# A missing window, zero ON counter, failed workload or unreaped child stops here.
expect_rc 0 python3 tests/abbagate.py "${COMMON[@]}" \
  --collect-reorder-controls --output "$RUN/reorder-controls"
sha256sum "$CONTROL" > "$RUN/reorder-control-receipt.sha256"
sha256sum -c "$RUN/before-calibration.sha256"
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/after-controls-instrument.json"
check_instrument "$RUN/instrument.json" "$RUN/after-controls-instrument.json"
COMMON+=(--reorder-controls "$CONTROL")

# Fresh full inventory: 181 cells. Valid PIN/EXEMPT/CEILING-LIMITED => rc=3.
# Classify all fresh evidence; no historical per-cell verdict is an allowlist.
# Invalid/incomplete evidence (including a broken t05 witness) => rc=1, stop.
expect_rc 3 python3 tests/abbagate.py "${COMMON[@]}" --calibrate --output "$RUN/calibration"
taskset -c 112-127 python3 tests/gate_measurements.py \
  --import-calibration "$RUN/calibration/results.json" --cells "$CELLS"
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/after-import-instrument.json"
check_instrument "$RUN/instrument.json" "$RUN/after-import-instrument.json"
sha256sum -c "$RUN/before-calibration.sha256"
cp tests/gate_measurements.json "$RUN/imported-inputs.json"
if ! git diff --quiet -- tests/gate_measurements.json; then
  git add tests/gate_measurements.json
  git commit -m "Import nullpublish measured floors and ceiling observations"
fi
test -z "$(git status --porcelain --untracked-files=normal)"
taskset -c 112-127 python3 tests/gate_receipt.py freeze-null \
  --calibration "$RUN/calibration/results.json" --reorder-controls "$CONTROL" \
  --output "$RUN/frozen-campaign.json"

# Ceiling plans retain occupancy/workload checks and certify only fixed offered
# load on these byte-identical arms. No ceiling cell acquires a saturated floor.
expect_rc 3 python3 tests/abbagate.py "${COMMON[@]}" --collect-null 1 --output "$RUN/null"
test "$RUN/binary-A" -ef "$RUN/null/binary-A"
test "$RUN/binary-B" -ef "$RUN/null/binary-B"
sha256sum -c "$RUN/binary-manifest.sha256"
sha256sum "$RUN/null/binary-A" "$RUN/null/binary-B" "$STABLE"
taskset -c 112-127 python3 tests/gate_receipt.py promote-null \
  --campaign "$RUN/frozen-campaign.json" --null-result "$RUN/null/results.json"
cp "$NULL" "$RUN/promoted-null.json"
sha256sum -c "$RUN/reorder-control-receipt.sha256"

# Independent full holdout at the same frozen load and fixed two-sided bounds.
HOLDOUT_RC=$(taskset -c 112-127 python3 - "$RUN/promoted-null.json" <<'PYEXPECTED'
import json
import sys
report = json.load(open(sys.argv[1]))
print(3 if any(row['status'] == 'UNRESOLVED' for row in report['null_control']['resolution']) else 0)
PYEXPECTED
)
# UNRESOLVED/rc=3 is reporting-only. A regression/invalid measurement (rc=1)
# still stops here; no successful receipt or push is inferred from this holdout.
expect_rc "$HOLDOUT_RC" python3 tests/abbagate.py "${COMMON[@]}" \
  --reference-binary "$STABLE" --null-result "$RUN/promoted-null.json" --output "$RUN/holdout"
taskset -c 112-127 python3 tests/gate_receipt.py verify-null-holdout \
  --campaign "$RUN/frozen-campaign.json" --null-result "$RUN/promoted-null.json" \
  --comparison "$RUN/holdout/results.json" --output "$RUN/holdout-resolution.json"
sha256sum -c "$RUN/before-calibration.sha256"
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/after-holdout-instrument.json"
check_instrument "$RUN/instrument.json" "$RUN/after-holdout-instrument.json"
sha256sum -c "$RUN/reorder-control-receipt.sha256"
sha256sum -c "$RUN/binary-manifest.sha256"
# Stop after holdout. Preserve any UNRESOLVED status; no gate or push.
```

**Diff at lane handoff against launch.** `git diff 6eade240dde0c8a79c2c3f3f2b333b3d77d5ea25 --stat` (includes the required upstream merge):

```text
 MEASURE-REQUEST-cleanup-readreply.md              | 371 +++++++++++++++++++++
 MEASURE-REQUEST-nullpublish3.md                   | 328 ++++++++++++++++++
 src/core/ex_loop.h                                |  63 ++--
 tests/_nullrefresh_test.py                        | 108 +++++-
 tests/abba_instrument.py                          |  94 ++++--
 tests/fixtures/nullpublish-campaign6-compact.json | 383 ++++++++++++++++++++++
 tests/gate_measurements.json                      |   6 +-
 tests/gate_receipt.py                             |  14 +-
 tests/gates_test.py                               |  78 ++++-
 tests/nullpublish_refreeze_test.py                | 153 +++++++++
 tests/rltopo_unit.cc                              | 148 ++++++++-
 tools/nullpublish_refreeze.py                     | 197 +++++++++++
 tools/readreply_proof.py                          | 369 +++++++++++++++++++++
 13 files changed, 2211 insertions(+), 101 deletions(-)
```
