nullpublish — publication, resolution status and bounded null sampling

Implemented on `cx-nullrefresh` in `/home/user/Projects/cx-nullrefresh`. The requested `37eeb5e90be9997805cfe2456021ad07dc0c18f9` was merged first as `f66331825`; `origin/cpp` had already advanced at launch, so the exact requested revision was used. Implementation commits: `9fbd5423b`, `400b6bad5`, `04ac7af4b`. No server, load generator, campaign, benchmark, gate or push was run. Builds and serverless checks ran on cores **112–127**. Server sources, third-party sources, Makefile and tailgen sources match `37eeb5e90` exactly.

**Verified diagnosis and baseline anchors.** At `37eeb5e90`, `tests/abba_evidence.py:238` already records both signs of null error, `tests/abbagate.py:448` inherits per-metric errors, `:470` floors stability with MAX_SPREAD, `:611` assesses loss, and `:1972–1990` selects the single pinned block. MAX_SPREAD is 2.0 at `tests/abbagate.py:146`; the existing repeat policy is PIN_NULL_BLOCKS=2 at `:148`. The 24-hour match is `tests/abba_evidence.py:312`.

There are two provenance corrections to the launch diagnosis. The magnitude publication veto is **not present at 37eeb5e90**: it is in the continuing nullrefresh5 lane, `de0d9e6f6:tests/abba_evidence.py:374–381` (unchanged at merge `f66331825`). The strict campaign replay is at `:339`, and the collecting resolution table at `:246`. Its callers include `de0d9e6f6:tests/gate_receipt.py:363–370` (`promote_null`) and promoted-null matching/holdout. `freeze_null` at `:297` validates calibration and freezes the pre-null plan; it does not call that magnitude veto. Campaign 6 already contains `frozen-campaign.json`. The observed “null exceeds spread/integrity guard” is therefore a publication/promotion failure, not the calibration freeze function. The contradiction itself is confirmed: recording a floor above 2% and then forbidding publication prevents item 7 from engaging.

The preserved `build/nullrefresh5-mainline-20260929T224208Z/null/results.json` and `resolution-map.csv` were read only. Replay reproduces **188 rows, 141 RESOLVING, 47 UNRESOLVED across 41 cells**; t00/p999_ms reference spread is **11.67883211678831%**, displayed as **11.68%**. Every row also matches the mainline CSV at its three-decimal precision. Its elapsed time is 22,624.118 seconds. These are campaign-6 observations, not fresh measurements.

**Changes by file.**

| File | Change and reason |
|---|---|
| `tests/abba_evidence.py` | Re-derive and persist each scored row's status; replace the magnitude veto with raw-data/status consistency. Include every repeat in ORDER, positive-finite, workload, occupancy and time-span replay. Preserve each maximum spread; pool signed delta at the same frozen load. Count/name resolving and unresolved cells, exclude unresolved cells from PASS evidence, and withhold comparison certification. An independent holdout can be UNRESOLVED and cannot certify a receipt. |
| `tests/abba_null_sampling.py` | One module owns the deterministic pilot-CV budget, immutable repeat count, live repeat loop and replay of that schedule. No new numeric constants or knobs. |
| `tests/abbagate.py` | Carry status with null floors; return UNRESOLVED/rc=3 for a valid comparison lacking resolution and FAIL for loss beyond its threshold. Invoke bounded repeats only for ordinary null collection; the separate variance-pin protocol keeps its existing block schedule. Persist policy/count before repeats, retain unique sample artifact names, print status counts and names. |
| `tests/gate_receipt.py` | Bind the sampling policy into freeze; publish complete noisy nulls with their statuses. Refuse receipt issuance for unresolved cells even if a coordinator claims PASS. Add `replay-null RESULTS` for historical reporting, and `resolution-summary RESULTS` for gate output. |
| `tests/gate.sh` | Name UNRESOLVED/PARTIAL rather than describing rc=3 as “did not run”; print the resolution summary. Emit no extra scored row. |
| `tests/_nullrefresh_test.py` | Add synthetic publication/comparison, sampling and replay proofs with mechanism-removal controls; replace the obsolete magnitude-veto assertion with raw-status-integrity checks. |
| `tests/fixtures/nullrefresh-ledger-labels.json` | Add the two already-upstream rltopo labels to the serverless fixture (459 → 461); this is expected-label data, not claimed execution or a gate-constant edit. |

The existing disk preflight, shared content store, hard links, inode/open-descriptor guards and reorder witnesses are unchanged. `tests/gates_test.py` retains the merged nine core/topology expectations and its no-rg fixture. All searches and gate checks used grep; the gate retains `grep -Fxq` for rltopo. The larger diff against 37eeb5e90 also contains the requested continuing nullrefresh1–5 work; the new implementation diff starts at f66331825.

**Status and certification semantics.** Let S be max(reference spread, candidate spread, |pooled delta|) for one scored metric. Spreads and deltas can legitimately be zero; the underlying observations must be finite and strictly positive.

| Evidence/state | Reported result | Receipt / push consequence |
|---|---|---|
| Complete identical-byte null, S ≤ MAX_SPREAD | Row RESOLVING, measured floors retained | Publishable calibration evidence; null collection itself remains PARTIAL/rc=3, never a code PASS |
| Complete identical-byte null, S > MAX_SPREAD | Row UNRESOLVED, measured floors retained | Publishable; cannot contribute PASS evidence |
| RESOLVING scored metrics; valid comparison within threshold | PASS, existing arithmetic unchanged | Eligible evidence, subject to all existing full-receipt checks |
| Any scored metric UNRESOLVED; valid comparison within threshold | UNRESOLVED, rc=3, comparison_trusted=false | Reporting only; count/name the cell; withhold full receipt/push |
| Loss above the comparison threshold, either status | FAIL, rc=1 | Refuse certification |
| Non-identical arms, incomplete/reordered blocks, nonpositive/nonfinite observations, missing witnesses, changed instrument or geometry, stale control | REFUSED / FAIL | No publication or certification |

The primary loss threshold still uses max(current reference spread, standing-null |delta|, the existing applicable read-local floor); the long-command tail retains its own metric threshold. Stability still uses max(MAX_SPREAD, standing-null arm spreads). The new status does not increase either threshold. The unchanged floor assertions still require a 1.5% loss to fail against a 1% null error when the reference repeats more tightly. Their expected outputs were not edited. The status-free miniature fixtures in that arithmetic test remain supported by the low-level helper; a real standing null must match raw re-derivation, including status, and the instrument fingerprint.

A cell's summary status is UNRESOLVED if either scored tail metric is unresolved. Row counts therefore differ from cell counts. The receipt lists actual PASS-evidence cell IDs separately. A same-binary non-loss over unresolved cells cannot be called a full PASS. The holdout retains the existing independent two-sided bounds; an excess still refuses verification, and an unresolved holdout remains explicitly UNRESOLVED.

**Sampling rule and its limit.** The campaign freeze contains the policy before sampling. The first planned ABBA block is a pilot. Its data determine one exact repeat count, saved before the first repeat; that count is never re-fit or shortened. This is a precommitted two-stage design, not a promise that the numeric sample size can be known before seeing the pilot. An exact data-dependent count before *any* sampling would require independent prior CV evidence. No block is dropped, re-rolled, selected for favorable noise, or replaced.

For the pilot's two arms, pooled within-arm sample variance is `s² = sum_arm sum_sample (x - arm_mean)² / sum_arm (sample_count - 1)`. The pooled per-sample `CV% = 100*s/grand_mean`. For each scored metric, `n = max(2, ceil((CV%/MAX_SPREAD)²))` samples per arm; required blocks are `ceil(n/ORDER.count('A'))`. If all pilot rows resolve, take the original one block. Otherwise take `min(PIN_NULL_BLOCKS * ORDER.count('A'), max(PIN_NULL_BLOCKS, required_blocks))`, i.e. 2–4 total blocks today. The worst scored metric sets the cell's plan. The cap reuses the existing replication count twice, once per within-block arm sample; it is a bounded research budget, not an inferred confidence level. No new machine constant is introduced.

This n is a one-standard-error scale for an arm mean, **not a confidence interval or a guarantee of resolution**. At CV=10%, `(10/2)²=25` samples per arm means 13 complete ABBA blocks; the existing-policy cap permits four blocks/eight samples per arm and stops UNRESOLVED. A low-CV pilot with +3% arm bias can pool with its required confirming block to +1.5%, resolving only after both blocks finish. A persistent bias cannot disappear through this rule.

There is an unavoidable limit in the requested rules: with raw spreads retained as maxima, an initial spread above 2% can never become RESOLVING after more samples. The implementation preserves that specified law. Repeats refine the signed arm delta, but do not divide raw spreads by sqrt(n), widen MAX_SPREAD, or silently certify a CV-based bound. The synthetic resolving proof consequently exercises a **delta-only** unresolved pilot; the excessive-spread proof stays unresolved even after perfectly quiet extra blocks. A guarantee that CV alone makes high-spread pilots resolve would conflict with the required status formula and needs an owner ruling.

For repeated blocks at one load, `delta% = 100 * sum_blocks[(B1-A1)+(B2-A2)] / sum_blocks(A1+A2)`; |delta| is taken after pooling. This is the reference-sum-weighted signed paired difference over all equal-duration windows, including the pilot. Taking the mean of absolute deltas would estimate noise magnitude rather than arm bias. Both arm spreads remain maxima over all blocks. Distinct offered-load probes retain separate rows; no averaging across loads hides a noisy rung. Repeats are kept in `null_repeats` so the original measured load ladder, and match_null's exact load/geometry keys, do not change. Unique sequence offsets preserve every artifact instead of overwriting the pilot.

**Campaign-6 budget replay.** `build/nullpublish-escalation-map.json` records every pilot CV and schedule; it is an estimate based on old observations, never an importable campaign-7 plan.

| Total blocks for an escalating cell | Cells | Additional blocks | Cell IDs |
|---|---:|---:|---|
| 2 | 30 | 30 | h03, h05, h06, h07, h08, h09, h11, h13, h15, h25, h27, h29, h41, h53, m03, m10, m14, m15, m21, m33, m39, m40, m50, m56, m75, m93, x05, a03, t02, t04 |
| 3 | 2 | 4 | m52, m69 |
| 4 | 9 | 27 | t00, m09, m51, m57, m63, t01, t03, t05, t06 |

The other 140 cells retain one block. Total: **41 escalating cells, 61 extra blocks, 242 blocks instead of 181**. All seven tail cells have at least one already-excessive spread, so all seven stay UNRESOLVED on this historical pilot replay regardless of how quiet later blocks might be.

The simple equal-cost estimate is `61/181 * 22624.118 = 7624.703 s` extra, **2.118 h / 1.337×**. Weighting by each escalating cell's actual campaign-6 `wall_seconds` gives **8722.519 s** extra. Those wall times already include population (do not add populate_seconds again). The unaccounted campaign overhead is `(22624.118 - 22386.574)/181 = 1.312398 s/block`; allocating it to 61 repeats gives **8802.575 s**, **2.445 h** extra and **8.730 h total ABBA / 1.389×**. This is below 1.5×; it is not a wall-clock guarantee for a changed workload. The worst case if every cell were noisy is bounded at four blocks per cell. Calibration, controls and independent holdout are separate from the 6.284 h ABBA baseline.

**Instrument identity.** ROOTS is unchanged:

- `tests/abba_instrument.py`
- `tests/abbagate.py`
- `tests/abba_experiments.py`
- `tests/gate_history.py`
- `tests/legacy_reorder_witness.py`

The exact changed fingerprint entries relative to campaign 6 are `tests/_nullrefresh_test.py`, `tests/abba_evidence.py`, **new** `tests/abba_null_sampling.py`, `tests/abbagate.py`, and `tests/gate_receipt.py`. The imported test module is intentionally included by the existing dormant-import traversal. `tests/gate.sh`, the JSON label fixture and this report do not change the scoped instrument; they remain part of broader release/source identity. The complete current transitive file list is:

- `tests/_abba_test_fixtures.py`
- `tests/_gate_process.py`
- `tests/_lib.py`
- `tests/_nullrefresh_test.py`
- `tests/abba_binaries.py`
- `tests/abba_ceiling.py`
- `tests/abba_evidence.py`
- `tests/abba_experiments.py`
- `tests/abba_instrument.py`
- `tests/abba_null_sampling.py`
- `tests/abba_profile.py`
- `tests/abba_reorder_control.py`
- `tests/abba_saturation.py`
- `tests/abba_simple.py`
- `tests/abba_worker_affinity.py`
- `tests/abba_workloads.py`
- `tests/abbagate.py`
- `tests/gate_history.py`
- `tests/gate_measurements.py`
- `tests/gate_quiet.py`
- `tests/gate_receipt.py`
- `tests/gateplan.py`
- `tests/legacy_reorder_witness.py`
- `tests/load_calibration.py`

The current instrument SHA-256 is `183bcb6585b545a2e0e168451c143e6098978024b3367353af9f02ac7cbfdf1c`. Python implementation, full version/build and executable digest are also fingerprinted. `build/nullpublish-PRE.instrument.json` was verified against every instrument file at f66331825 and matches campaign 6. **Campaign 6 cannot be promoted under this instrument**; editing its manifest or cached status is not migration. `taskset -c 112-127 python3 tests/gate_receipt.py replay-null build/nullrefresh5-mainline-20260929T224208Z/null/results.json` emits a `null-resolution-replay` object marked reporting_only=true/promotable=false, without campaign identity or promotion evidence.

**Validity policy left to the owner.** NULL_MAX_AGE remains 24 hours and match_null's validity keys are unchanged: exact instrument/runtime fingerprint, cell source SHA/count and exact cell parameters, window, binary/population identities where applicable, measurement environment/geometry, and original offered-load ladder. Repeats do not alter that ladder. A durable validity rule would need at least an explicit boot epoch, instrument fingerprint, topology/geometry and cell-source SHA, together with the existing generator, runtime-input, workload/window and immutable evidence bindings. Boot epoch is not currently captured. Wall-clock age limits reuse across unrecorded temporal changes in temperature, clocks, host state, resource pressure and other nonstationarity; it neither detects these conditions nor proves 24 hours is statistically special. No age waiver or alternate validity rule was implemented.

**Build artifacts and checks.** PRE and POST are the same server build from unchanged 37eeb5e90 server inputs, sharing one frozen inode; their difference is measurement Python, not server behavior. There is no layout change and no PAD arm. `taskset -c 112-127 make -j16 build/tomokv build/tailgen` passed. No built server or generator was executed.

| Frozen artifact | Bytes | SHA-256 |
|---|---:|---|
| `build/tomokv-nullpublish-PRE` | 177052936 | `206421de905a2337ba70bad495913e6cd471370747b62f9769a2e4edd4b342af` |
| `build/tomokv-nullpublish-POST` | 177052936 | `206421de905a2337ba70bad495913e6cd471370747b62f9769a2e4edd4b342af` |
| `build/tailgen-nullpublish-frozen` | 2911008 | `613a6a7e115ba522753a37015a2dbb799325e915030a9f8c3ae95c3a8f4a2d05` |
| `build/memtier-nullpublish-frozen` | 616272 | `9b6ee614dae154c64b17a067a10236b3e6532f7ca52c43b547b87101556dd7d4` |

SERVERLESS_CHECKS_PENDING

The final serverless assertions name their exercised state and exact failure. Mutation/removal controls use disposable fixtures or in-memory function replacements and never execute a production server:

| Proof | Positive evidence and exact failure control |
|---|---|
| (a) Complete noisy null | Full synthetic calibration imports and freezes; h01's complete noisy null promotes with exactly one UNRESOLVED cell. Restoring the old magnitude veto prevents that successful publication. |
| (b) Non-loss on unresolved cell | Main driver and assessment report UNRESOLVED/rc=3; h01 is excluded from 180 other PASS-evidence cells. Removing status propagation produces PASS and fails the assertion. Receipt-specific guard removal changes the exact “receipt withheld” refusal even though the deeper comparison guard still refuses. |
| (c) Beyond-floor loss | 1.5% latency loss against a 1% null error is FAIL with the exact paired-regression reason. Removing the loss predicate breaks that oracle. |
| (d) Invalid null | Existing full-campaign mutations still refuse changed binary identity, missing/reordered measurements, missing workload proof, stale/foreign instrument and invalid raw observations before replacing the standing default. Each mechanism-removal test checks the precise rejection or successful alternate publication in its throwaway fixture. |
| (e) Resolving floor behavior | Existing floor arithmetic tests retain their expected dictionaries/verdicts; real low-noise null/control/comparison fixtures still pass. |
| (f) Fixed escalation | Low-CV +3% delta pilot runs exactly one additional block, pools to +1.5% and resolves. CV=10% pilot needs 25 samples/arm, executes the four-block cap, and retains its 20% raw spread as UNRESOLVED even with quiet repeats. Removing pooling, truncating the plan, or replacing the maximum by the last block fails the exact assertion. Missing/refitted/reordered plans refuse. |
| (g) Historical replay | 188/141/47 and every mainline CSV row match; t00 rounds to 11.68%. Removing status classification fails the exact count assertion. Historical source SHA is unchanged. |

No scored gate rows were added or retired. `EXPECT_QUICK=441` and `EXPECT_FULL=461` are unchanged from 37eeb5e90. The two label-fixture additions already emit at **37eeb5e90 tests/gate.sh:1270**, once per 1s/2s mode, before the quick-tier exit (at baseline :2858). The headline status output is after the quick exit and remains unscored. No gate count change is requested.

**Campaign 7 — maintainer only.** Extract the following single bash fence, or use its byte-identical `build/nullpublish-campaign.sh`. It retains the nullrefresh5 fence/variables/preflight contract and shared binary store, using a fresh directory. The frozen source guard permits later report-only commits but refuses changed source/build inputs or instrument bytes. Default instance ceiling remains 16, matching campaign 6. Recalibration and a fresh null are required; no old result is promoted. Holdout rc=3 is expected only when the newly promoted null contains unresolved rows; rc=1 still stops the script. A successful command that writes an UNRESOLVED holdout is reporting, not receipt or push approval.

```bash
set -euo pipefail
cd /home/user/Projects/cx-nullrefresh
# Set NULLREFRESH_MAX_INSTANCES=24 explicitly BEFORE a fresh campaign, if desired.
MAX_INSTANCES="${NULLREFRESH_MAX_INSTANCES:-16}"
case "$MAX_INSTANCES" in 16|24) ;; *) echo 'Choose 16 or 24 instances' >&2; exit 2;; esac
RUN="$PWD/build/nullpublish-mainline-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$RUN"
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
  04ac7af4b210a6a232ecedb046071453388e20f6 "$(git rev-parse HEAD)"
printf '%s\n' "$MAX_INSTANCES" > "$RUN/max-instances"
cp build/nullpublish-freeze.json "$RUN/instrument-freeze.json"
cp tests/gate_measurements.json "$RUN/before-calibration-inputs.json"
# Do not exit on a checksum failure until the file-level diagnostic has run.
artifact_rc=0
sha256sum -c build/nullpublish-campaign.sha256 || artifact_rc=$?
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/instrument.json"
check_instrument build/nullpublish-POST.instrument.json "$RUN/instrument.json"
if test "$artifact_rc" -ne 0; then
  echo 'Frozen artifact or initial input checksum mismatch; stop before calibration.' >&2
  exit 1
fi
if test -n "$(git status --porcelain --untracked-files=normal)"; then
  echo 'Worktree changed since freeze; review these paths before a fresh campaign:' >&2
  git status --short >&2
  exit 1
fi
git merge-base --is-ancestor 04ac7af4b210a6a232ecedb046071453388e20f6 HEAD
# This freeze must retain the server/tailgen build inputs of the launch merge.
git diff --exit-code 04ac7af4b210a6a232ecedb046071453388e20f6 -- src third_party Makefile tools/tailgen
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

**Requested diff against 37eeb5e90 (including the continuing lane).**

DIFF_STAT_PENDING
