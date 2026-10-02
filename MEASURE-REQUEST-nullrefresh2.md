# nullrefresh2 — instrument fix; measurements pending mainline

Reference `32d27ee7562ed5a17ff889c0fe5cf250f3fdc63c` was merged first in `98b8f0ef8`; implementation is committed in `9c33a7c8c` and formatter regression fix `cc95cbaf0`. Worktree `/home/user/Projects/cx-nullrefresh`, branch `cx-nullrefresh`. No push. No server, benchmark, load generator or gate was run. All builds and serverless tests were restricted to cores 112–127 (the final instrument recheck used 120–127 while shell fixtures occupied 112–115). Server sources and Makefile match `origin/cpp` exactly.

**Verdicts and scope.** Calibration now finishes with rc=3 when every cell has valid PIN, EXEMPT, LOADGEN-BOUND or CEILING-UNCONFIRMED evidence. A campaign containing either ceiling class says `CEILING-LIMITED`, remains `measurement_valid=false`, `comparison_trusted=false`, and `normal_gate_eligible=false`. Invalid/incomplete observations, broken workload/occupancy evidence, shortened windows, interference and unreaped children still fail with rc=1. The ordinary 95% productive-role floor, 5pp run margin, 1% plateau tolerance, 2% integrity boundary, windows and holdout bounds were not widened.

| Cell class | Required evidence | Imported result |
|---|---|---|
| PIN | Existing saturated rung plus higher-worker plateau confirmation | Saturated floor in `load_floors` |
| EXEMPT | Canonical depth=1 or p999; raw evidence still required | No floor; existing latency load plan retained |
| LOADGEN-BOUND | Complete permitted ladder through the ceiling; final rate gain >1%, final worker count increases, final productive-role occupancy <90%, and no observed rung reaches 95% | Separate `ceiling_loads` observation; saturation UNPROVEN |
| CEILING-UNCONFIRMED | Complete permitted ladder through the ceiling with at least two observations, no qualifying PIN, and insufficient evidence for LOADGEN-BOUND | Separate `ceiling_loads` observation, reason `occupied-without-confirmation` or `underfilled-flat-or-confounded`; saturation UNPROVEN |

LOADGEN-BOUND is an operational classification supported by the rate/occupancy ladder, not a PMU attribution to memtier internals. A flat or falling underfilled cell is not silently called loadgen-bound. At least two observations are required to record a slope; a one-rung unconfirmed search still fails. The classifier uses the existing 95%-5pp boundary for <90%; it does not alter the saturation floor. Slope is the final adjacent rate change (percent and ops/s per additional instance); the record includes both instance/worker counts, achieved rate and central-window server occupancy.

Raw calibration replay authorizes import. Ceiling observations never populate `load_floors`, remove any superseded floor for that cell, and carry shape, CPU geometry, full instrument identity, calibrated binary digest, calibration source path/SHA, timestamp and the ceiling evidence. Import remains atomic across the campaign. A forged cached verdict, skipped ladder rung or changed observation is rejected.

**Standing null and holdout.** Freeze binds the post-import plans and their provenance. Every ceiling cell runs one full ABBA block at exactly its calibrated ceiling, on the same binary as calibration, with byte-identical arms. `saturation_exempt` remains false and the assessment explicitly says `capacity_claim=ceiling-load-only`. Raw occupancy, workload, completion, layout and quiet checks still run; rate/latency spreads and fixed two-sided null/holdout bounds still apply. The held-out resolution artifact lists ceiling-only cells. These comparisons establish instrument behavior at that fixed offered load; they cannot certify a saturated peak or compare different server binaries under a claimed saturation waiver. Different binaries, changed ceilings/geometry, missing provenance or a forged saturated-capacity claim are rejected. Cycles/op remains UNPROVEN, as before.

**Historical evidence; no salvage/import of the failed run.** Source: `build/nullrefresh-mainline-20260924T195834Z/calibration/results.json`. Original campaign: 181 cells, 103 PIN, 75 canonical EXEMPT, three FAIL; overall rc=1. EXEMPT confirmation=None is intentional. Log: `/tmp/claude-1000/nullrefresh-campaign.log`, failure lines 434, 494, 862 and 944. The new read-only diagnosis is `build/nullrefresh2-historical-evidence.json`; it replays raw same-window occupancy through `saturation_score`, not the whole-run busy scalar.

Original results SHA-256: `3ef1c1a1575867539034554dfd26e08780545cb2366be4219fab259f446cd73c`.

| Cell / new diagnostic verdict | Rate at 12 → 16 instances (cmd/s) | Final slope | Central server occupancy at 16 | Workers at 12 → 16 | Decision |
|---|---:|---:|---:|---:|---|
| m09 / CEILING-UNCONFIRMED | 1,696,747.646 → 1,669,104.475 | -1.6292% | 84.834501% | 192 → 128 | Underfilled, falling; not a demonstrated rising loadgen ceiling. Flat/capped-load behavior is plausible, but server saturation is unproven. |
| m21 / CEILING-UNCONFIRMED | 1,638,065.208 → 1,767,515.362 | +7.9026% | 90.940262% | 192 → 128 | Underfilled relative to 95%, non-monotonic; final rise accompanies fewer workers. Loadgen bottleneck not proven. |
| x05 / CEILING-UNCONFIRMED | 1,849,252.577 → 1,857,622.213 | +0.4526% | 99.995685% | 192 → 128 | Server occupied, confirmation missing. Final +0.45% is within existing 1% plateau tolerance, but fewer workers cannot confirm capacity. |

The complete ladders show why a binary diagnosis would overclaim:

| Instances | Workers | m09 cmd/s / occupancy | m21 cmd/s / occupancy | x05 cmd/s / occupancy |
|---:|---:|---:|---:|---:|
| 1 | 16 | 1,728,351 / 89.697% | 1,712,530 / 89.187% | 1,481,435 / 99.986% |
| 2 | 32 | 1,691,574 / 87.880% | 1,712,658 / 89.186% | 1,662,021 / 99.997% |
| 4 | 64 | 1,741,204 / 89.989% | 1,757,395 / 90.798% | 1,749,575 / 99.993% |
| 8 | 128 | 1,760,625 / 90.025% | 1,719,746 / 88.765% | 1,783,044 / 99.994% |
| 12 | 192 | 1,696,748 / 87.116% | 1,638,065 / 84.860% | 1,849,253 / 99.997% |
| 16 | 128 | 1,669,104 / 84.835% | 1,767,515 / 90.940% | 1,857,622 / 99.996% |

m09 ranges around 1.67–1.76M across instances; m21 dips at n12 and recovers at n16. Their final occupancies are 84.83% and 90.94%, respectively: neither proves a saturated peak, and neither has a monotonic rate rise under increasing worker capacity. The known command-mode generator cap is consistent with underfilled flat behavior but does not prove the bottleneck in these particular observations. x05 remains >99.98% occupied throughout; calling it loadgen-bound would contradict the evidence. It is an occupied server with a missing valid confirmation, not permission to relax the worker-capacity rule.

**Geometry and the 24 option.** Keep the default at 16. Load cores 32–127 are 96 physical cores; 160–255 provide their 96 SMT siblings, for 192 logical CPU slots. Actual layouts at n8/n12/n16 use 128/192/128 workers. n24 fits without sharing an assigned CPU between instances: four physical cores plus their four siblings per instance, eight workers each, 192 workers total and exactly 512 connections (16 or 24 per instance). It increases capacity over n16, but not over n12. The low m09/m21 occupancy supports trying more generator instances as a separate experiment; x05's >99.98% occupancy does not justify claiming it needs more load. No n24 rate was measured. `--max-instances 24` is accepted explicitly; calibration includes its actual ceiling in the ladder. Choose `NULLREFRESH_MAX_INSTANCES=24` before starting the fresh full campaign, never midway through a failed one.

**Frozen artifacts.** Previous `build/nullrefresh-PRE/` and `build/nullrefresh-POST-instrument/` snapshots remain intact. New reference PRE is `build/nullrefresh2-reference-PRE/`, archived directly from 32d27ee75 before edits; `build/nullrefresh2-old-path/` preserves the merged pre-fix instrument. POST is the committed standalone snapshot `build/nullrefresh2-POST-instrument/`. No PAD: server text/layout/behavior did not change in this lane; PRE and POST server files are byte-identical copies of the build matching the new reference.

Frozen at `2026-09-25T02:09:59.306830+00:00` before new live data. `build/nullrefresh2-POST.instrument.json` records 21 transitive Python entries plus interpreter identity:

- Instrument fingerprint SHA-256: **`eda18a6f5a2a5ebc75025cfc5c4acb6ed468c8f7dd3db02306949d3524a6a134`**.
- Manifest file SHA-256: `4f84dd81bd9ff2af85c2f3c1f9a3449bb2e8e62aa2bdfe4e28e8e738c967b162`.
- New reference PRE fingerprint: `a3ae63c61e908a696235a364c8068e7b046b457f382e2c107c20593ccefef7af`.
- Merged old-path fingerprint: `beaa4bdfdaaf2c33ea110badf9fa06b9a1e2fa33f1d98604d655a0462d867bb0`.
- Inventory SHA-256 (181 cells): `d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350`.
- Initial measured inputs, before new calibration: `37bf3f583b4f236c43653f053ef9361139243f5796deb6aac87e7370c326e540`.

| Binary under build/ | SHA-256 |
|---|---|
| tomokv-nullrefresh2-PRE | `9b8beff78d01d6bec8dfac74a223c823212d1af2dea0d121313706abdd17201c` |
| tomokv-nullrefresh2-POST | `9b8beff78d01d6bec8dfac74a223c823212d1af2dea0d121313706abdd17201c` |
| memtier-nullrefresh2-frozen | `9b6ee614dae154c64b17a067a10236b3e6532f7ca52c43b547b87101556dd7d4` |
| tailgen-nullrefresh2-frozen | `613a6a7e115ba522753a37015a2dbb799325e915030a9f8c3ae95c3a8f4a2d05` |

`build/nullrefresh2-freeze.json` binds the reference, source commit, geometry/windows and artifact hashes; `build/nullrefresh2-POST.dependencies.json` retains the import graph. Instrument and imported DATA are frozen separately: calibration is the only phase permitted to change `tests/gate_measurements.json`, and `freeze-null` then binds those bytes. Any instrument or policy change invalidates the freeze and requires a new campaign. The earlier preflight freeze is retained with `.before-formatter-fix` suffixes and is superseded: final static review found the old printer assumed plateau-confirmation fields for a ceiling-only result; `cc95cbaf0` fixes it and adds a test. No live data preceded either freeze.

**Serverless proofs.** `build/nullrefresh2-calibration.log`: nine tests pass, including the ceiling-only ABBA output path. The synthetic rising/70%-occupancy fixture finishes LOADGEN-BOUND at its ceiling, calibration rc=3; the campaign's exact `set -euo pipefail` / `expect_rc 3` contract reaches its continuation marker. Removing the new ceiling classification restores the previous UNPROVEN → row FAIL → campaign FAIL path; rc=1 and the shell exits before that marker. The frozen pre-fix source contains those same two fatal guards. PIN selection and failure/quiet/cleanup controls remain active.

`build/nullrefresh2-ceiling-integration.log`: the full 181-cell fixture with one synthetic LOADGEN-BOUND cell imports its separate plan, freezes, promotes a standing null and passes an independent holdout at low occupancy. Controls reject changed bytes, changed ceiling, missing provenance, forged ceiling evidence and a claimed saturated floor. All fixture data is labeled synthetic and never used as live calibration.

| Check | Result | Log under build/ |
|---|---|---|
| Unchanged server + tailgen build | PASS, no warnings; cores 112–127 | nullrefresh2-build.log |
| ABBA / saturation / calibration self-tests, final freeze | 98 / 10 / 9 PASS | nullrefresh2-abba-refreeze.log |
| Measurement importer, final freeze | 11 PASS | nullrefresh2-measurements-refreeze.log |
| Receipt core + full campaign controls | 17 + 12 PASS | nullrefresh2-receipt-final.log |
| Full 181-cell ceiling import/freeze/promotion/holdout fixture, final freeze | 1 PASS | nullrefresh2-ceiling-integration-refreeze.log |
| Instrument fingerprint controls, final freeze | 5 PASS | nullrefresh2-instrument-refreeze.log |
| Shell fixtures, isolated rerun | 56 PASS | nullrefresh2-gates-isolated.log |
| History / process / quiet / background / tailgen controls | 55 / 12 / 8 / 11 / 3 PASS | nullrefresh2-{history,process,quiet,background,tailgen}-final.log |

The 17+12 receipt suite passed before the final formatter-only fix; the final instrument was then rechecked through the full ceiling import/freeze/promotion/holdout fixture, importer, ABBA/calibration and fingerprint suites. The initial concurrent shell-fixture sweep hit two fixed 45-second scheduler deadlines; failure artifacts remain in `build/scheduler-failure-{wkzgais_,u61oagbx}/`. With competing checks completed, the same 56 tests passed on rerun without changing their code, deadline, assertions or tolerances. The earlier development logs retain the corrected fixture/schema failures and the instrument-change refusals encountered while editing; the table names the completed passing checks.

`git diff --check`, `bash -n tests/gate.sh`, and `bash -n build/nullrefresh2-campaign.sh` pass. Both report bash blocks are identical, the current instrument equals its frozen snapshot, PRE/POST binary bytes match, and the binary/inventory SHA preflight passes. No live correctness or performance result is inferred from these serverless checks.

Gate rows added or removed: zero. The merge preserved upstream wbrule constants quick=441/full=457 verbatim. Its three existing policy/phase/stages labels were added to the serverless expected-label fixture with source provenance, not fabricated execution evidence. No EXPECT constant was independently edited. This instrument change remains inside the existing ABBA negative-control row (`tests/gate.sh:2365`), before the quick-tier exit (`:2845`). Quick 441+0=441; full 457+0=457.

**Mainline campaign.** This is the sole bash block, byte-identical to the regenerated block in `MEASURE-REQUEST-nullrefresh.md`. It deliberately ends after independent holdout; correctness gating and any full source receipt remain separate maintainer work. Promotion alone does not certify holdout resolution. On any failure retain the complete run and stop; no subset salvage, tolerance edits or reuse of the old failed calibration. No performance improvement is claimed by this instrument change.

```bash
cd /home/user/Projects/cx-nullrefresh
set -euo pipefail
test -z "$(git status --porcelain --untracked-files=normal)"
git merge-base --is-ancestor 32d27ee7562ed5a17ff889c0fe5cf250f3fdc63c HEAD
# Set NULLREFRESH_MAX_INSTANCES=24 explicitly BEFORE starting a fresh campaign.
MAX_INSTANCES="${NULLREFRESH_MAX_INSTANCES:-16}"
case "$MAX_INSTANCES" in 16|24) ;; *) echo 'Choose 16 or 24 instances' >&2; exit 2;; esac
RUN="$PWD/build/nullrefresh2-mainline-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$RUN"
STABLE="$PWD/build/tomokv-nullrefresh2-POST"
GEN="$PWD/build/memtier-nullrefresh2-frozen"
CELLS="$PWD/tests/headline_cells.txt"
NULL="$PWD/.gate-history/receipts/baselines/full-null.json"
expect_rc() {
  local expected=$1 actual=0
  shift
  "$@" || actual=$?
  if test "$actual" -ne "$expected"; then
    echo "Expected rc=$expected, got rc=$actual: $*" >&2
    return 1
  fi
}
COMMON=(--subset full --cells "$CELLS" --candidate "$STABLE"
        --memtier "$GEN" --server-cores 0-31 --server-smt ''
        --load-cores 32-127 --load-smt 160-255 --max-instances "$MAX_INSTANCES"
        --ports 8700-8799 --port 8700 --build-reference 0)
# Preflight binds exact 32d27ee75 server bytes and both generator binaries.
sha256sum -c build/nullrefresh2-campaign.sha256
cmp build/tomokv "$STABLE"
cmp build/tailgen build/tailgen-nullrefresh2-frozen
printf '%s\n' "$MAX_INSTANCES" > "$RUN/max-instances"
cp build/nullrefresh2-freeze.json "$RUN/instrument-freeze.json"
cp tests/gate_measurements.json "$RUN/before-calibration-inputs.json"
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/instrument.json"
cmp build/nullrefresh2-POST.instrument.json "$RUN/instrument.json"
sha256sum "$STABLE" "$GEN" "$CELLS" build/tailgen > "$RUN/before-calibration.sha256"

# All 181 cells, fresh measurements. PIN, EXEMPT and CEILING-LIMITED use rc=3.
# Invalid/incomplete evidence still returns rc=1 and stops this strict script.
expect_rc 3 python3 tests/abbagate.py "${COMMON[@]}" --calibrate --output "$RUN/calibration"
# Replay raw evidence atomically: PIN -> load_floors; ceiling -> ceiling_loads.
taskset -c 112-127 python3 tests/gate_measurements.py \
  --import-calibration "$RUN/calibration/results.json" --cells "$CELLS"
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/after-import-instrument.json"
cmp "$RUN/instrument.json" "$RUN/after-import-instrument.json"
sha256sum -c "$RUN/before-calibration.sha256"
cp tests/gate_measurements.json "$RUN/imported-inputs.json"
if ! git diff --quiet -- tests/gate_measurements.json; then
  git add tests/gate_measurements.json
  git commit -m "Import nullrefresh2 measured floors and ceiling observations"
fi
test -z "$(git status --porcelain --untracked-files=normal)"
taskset -c 112-127 python3 tests/gate_receipt.py freeze-null \
  --calibration "$RUN/calibration/results.json" --output "$RUN/frozen-campaign.json"

# Explicit ceiling controls retain raw occupancy and workload checks. Saturation
# remains UNPROVEN; only calibrated byte-identical arms may use these load plans.
expect_rc 3 python3 tests/abbagate.py "${COMMON[@]}" --collect-null 1 --output "$RUN/null"
sha256sum "$RUN/null/binary-A" "$RUN/null/binary-B" "$STABLE"
taskset -c 112-127 python3 tests/gate_receipt.py promote-null \
  --campaign "$RUN/frozen-campaign.json" --null-result "$RUN/null/results.json"
cp "$NULL" "$RUN/promoted-null.json"

# Independent full holdout at the same frozen load, with fixed two-sided bounds.
expect_rc 0 python3 tests/abbagate.py "${COMMON[@]}" \
  --reference-binary "$STABLE" --null-result "$RUN/promoted-null.json" --output "$RUN/holdout"
taskset -c 112-127 python3 tests/gate_receipt.py verify-null-holdout \
  --campaign "$RUN/frozen-campaign.json" --null-result "$RUN/promoted-null.json" \
  --comparison "$RUN/holdout/results.json" --output "$RUN/holdout-resolution.json"
sha256sum -c "$RUN/before-calibration.sha256"
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/after-holdout-instrument.json"
cmp "$RUN/instrument.json" "$RUN/after-holdout-instrument.json"
# Stop here. Failed holdouts stop earlier; no subset salvage, changed tolerance,
# gate invocation, saturation certification, or push is part of this campaign.
```
