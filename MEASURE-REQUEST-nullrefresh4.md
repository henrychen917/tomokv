# nullrefresh4 — frozen campaign read-local controls

Implemented and committed on `cx-nullrefresh` in `/home/user/Projects/cx-nullrefresh`. Launch merge: `8238ecacd8360405c2dc1fa6010356183adfdf21`, merging the requested `origin/cpp` commit `4329c26f083de480d9eb0b2a601c7b6a7328226c`. Instrument implementation: `0fc66951de2cc6153b4fc9e39dab6cebf972f3fe`. Server, third-party, Makefile and tailgen sources match that requested mainline commit exactly. All lane builds and self-tests used cores **112–127**. No server, benchmark, gate or push was run.

**Run 4 diagnosis.** The retained artifacts show that the armed control did run. Calibration ran it and passed with 16 admitted attempts, 16 inversions and counter delta 16. The null ran it and passed with 16 admitted attempts, 15 inversions and counter delta 15. The null's `read-local-reorder-A-1s/controls.json` SHA-256 is `a9c101fe4cb05cf134017c5eb9190cfae5026a9547494c72662b4ccb1f017449`; its retained proof binds the same `378407db49e8fa059840e70722fd0ef24cf58183b7982be69e4b5fa980849df2` frozen binary. Calibration’s scored t05 window observed one natural permutation. All four null t05 windows observed zero permutations and progressing reorder batches, exposing the missing replay argument at promotion. Their `workload_witness` contains the passing proof, but `Runner.measure` omitted it from `workload_raw`, and receipt replay did not pass it to `require_workload_witness`. Those are the two evidence-handoff defects. The old campaign also lacked a separate pre-collection read-local 0/1 workload pair and frozen control-receipt binding.

**Salvage answer: no promotion of run 4.** Supplying a supplementary control now cannot make this null admissible: replaying all 181 cells after repairing only the missing proof handoff **in memory** passes the raw-workload checks, but the existing `validate_null_integrity` guard rejects **50 cell/metric rows across 43 cells** at its unchanged 2% boundary. Its first rejection is t00 short-command p99.9, absolute delta **7.733620%**; t05 short p99.9 has absolute delta **20.360551%** and B spread **14.913449%**, and t01 long p99.9 has A spread **92.535306%**. Therefore even the already-retained passing control cannot justify promotion. The repair changes the instrument fingerprint, and the new protocol freezes controls before collection; it provides no post-hoc amendment of the old frozen plan or raw results. A fresh full campaign is required. No salvage/promotion command for run 4 is supplied because none satisfies these checks; the complete replacement campaign below preserves them.

The audit is `build/nullrefresh4-run4-audit.json`. It retains all 50 failed metric rows and the original t05 evidence. Its source is `build/nullrefresh3-mainline-20260926T145307Z/null/results.json`, SHA-256 `44af0cab70fdbdc1fd328961a7e8d011e07bfb1278317defbbb682073a52e188`. The source file and all run-4 artifacts remain unchanged. The audit did not publish a receipt or standing null. These are diagnoses of existing observations, not fresh measurements or a claim about their cause.

**Control specification and binding.** `tests/abba_reorder_control.py` owns the campaign control. `abbagate.py --collect-reorder-controls` dynamically selects every rl=1 REORDER cell from the full inventory; currently **t05 and t06**. It runs each cell once with `--read-local 0` and once with `--read-local 1`, using the same frozen server and generator, mode, overlap, reorder setting, atomic setting, GET:BITCOUNT **8:2** mix, depth **8**, **512 total connections**, **16 instances**, normal population and a **10-second central window**. Each workload starts from a fresh server/population. The control phase runs on the campaign geometry: server physical cores **0–31**, loaders **32–127** and their SMT siblings **160–255**, with server SMT reserved. A choice of 24 as the calibration ceiling does not change these cells' fixed 16-instance workload.

There are two separate OFF/ON axes. The workload pair toggles **read-local**. For t05, the existing directed proof keeps read-local armed and toggles **reorder 0/1**, using SETRANGE/INCR on owner queues. FIFO must open an admitted window with no inversion; ON must open a window, invert execution, and report a strictly positive permutation counter delta. Sixteen bounded fresh-state attempts remain unchanged. An unreached or failed control is fatal. This directed proof establishes scheduler engagement on those bytes; it does not invent permutations in the scored GET/BITCOUNT window. t06 is the disabled-reorder workload control and needs no positive ON permutation witness.

The control phase publishes `reorder-controls/receipt.json` only after replaying every workload and both directed arms. It binds the workload artifact SHA-256, instrument, cell shapes/loads, geometry, generator identity, completion time, and the proof fields expected by `require_workload_witness`: `verdict=PASS`, `mode=1s`, `read_local=1`, `controls=[0,1]`, positive `on_counter_delta`, `binary_sha256`, `artifact`, and `artifact_sha256`. Calibration, null and holdout reuse this receipt via `--reorder-controls`; the directed proof is not rerun in those phases. The raw proof is saved even if a scored window happens to observe positive permutations. `freeze-null --reorder-controls` binds the receipt's exact path/hash in `frozen-campaign.json`, before null collection. Promotion and holdout require the same receipt and raw proof, recheck its workload/artifact hashes and measured binary, and retain the existing command progress, batch progress, accounting, cleanup, quiet-box, saturation, integrity and age requirements. Control completion must precede collection/freeze, and controls must remain within 24 hours.

At receipt refusal, missing raw read-local evidence or a missing/invalid frozen receipt names the affected cell(s), identifies `workload_raw.read_local_control` and the frozen receipt, and prints an executable `--collect-reorder-controls` command using the report's binary, cell source, generator and CPU allocation. It explains passing `--reorder-controls .../receipt.json` to calibration, freeze-null, null and holdout before a fresh collection; it does not suggest overwriting the refused run.

**Refreeze.** Frozen at `2026-09-27T05:10:35.965144+00:00`. The instrument now has **22 dependencies**, including the new control module. Six existing Python dependencies changed, one was added, and interpreter identity and instrument roots stayed unchanged. `build/nullrefresh4-instrument-diff.json` contains every old/new entry. The former instrument fingerprint was `626762386e0e18019593522657ca1ab236b56312797a4a37c2eb935b357e6776`.

| Artifact / identity | SHA-256 |
|---|---|
| `Instrument fingerprint (canonical payload)` | `fc74133ba150adab5cc16d06b577b343f183a4e0f4c9ae666c3393ec1973c86f` |
| `build/nullrefresh4-POST.instrument.json` | `e7280f1ea80baf421e11a23b5f820e355a93eb0c087bf07e7cb6c8c479b0ec4d` |
| `build/tomokv-nullrefresh4-POST` | `7ae0f186986b050846ed5f4369829bf3668ea8ac09824e2478bed4752c272d0d` |
| `build/memtier-nullrefresh4-frozen` | `9b6ee614dae154c64b17a067a10236b3e6532f7ca52c43b547b87101556dd7d4` |
| `build/tailgen-nullrefresh4-frozen` | `613a6a7e115ba522753a37015a2dbb799325e915030a9f8c3ae95c3a8f4a2d05` |
| `tests/headline_cells.txt` | `d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350` |
| `tests/gate_measurements.json` | `f197162086450ec0d1d07ef7b5d8e8f43c278372098d80f760bc0ba95f628fb3` |
| `build/nullrefresh4-build-inputs.json` | `5beb30eae961cabde074f5bbdec8e66ea115804675844fece92ed36cb03d907e` |
| `build/nullrefresh4-freeze.json` | `0bf70822b2eeb5f2af1df5ec80445eebbc23848db313aabf2bca7384deb27a12` |
| `build/nullrefresh4-campaign.sh` | `220d556562a2665ef6f613433ad64ab26bfd1a0e11fbd9d67351edff23f7fc51` |
| `build/nullrefresh4-campaign.sha256` | `694fadfa65068bc03d913fe4d539193d5adc14b77b0e3b3c8e0719ed87b17f55` |
| `build/nullrefresh4-run4-audit.json` | `db0b77058f26fbb87848d73102371ba4e1b0f7dda68cacfce83bc338cd18f60c` |

The build `taskset -c 112-127 make -j8 build/tomokv build/tailgen` passed without warnings; log: `build/nullrefresh4-build.log`. Frozen POST equals `build/tomokv`; tailgen equals its frozen copy. Memtier was copied from `/usr/bin/memtier_benchmark`. These binaries were hashed and compared, never executed by the lane. There is no server optimization, layout change, PRE/POST performance claim or PAD arm. Both null arms and both holdout arms use this frozen POST.

**Serverless validation.** All commands used `taskset -c 112-127` and temporary directories under this worktree's `build/`. Synthetic artifacts never become campaign inputs.

| Check | Result | Log under `build/` |
|---|---|---|
| ABBA / saturation / calibration | 100 / 10 / 9 PASS | `nullrefresh4-abba-final.log` |
| Receipt / full campaign controls (7 new) | 17 / 19 PASS | `nullrefresh4-receipt-final.log` |
| Calibration importer | 11 PASS | `nullrefresh4-measurements-final.log` |
| Instrument fingerprints | 5 PASS | `nullrefresh4-instrument-final.log` |
| Directed reorder witness | 11 PASS | `nullrefresh4-reorder-witness-final.log` |
| Serverless shell/scheduler fixtures | 56 PASS | `nullrefresh4-gates-final.log` |
| Exact campaign preflight diagnostic / fail-stop | 7 PASS | `nullrefresh4-preflight-controls.log` |

**245 serverless tests passed.** `build/nullrefresh4-checks.json` records the final log digests and counts.

The seven added campaign tests cover the actual zero-permutation promotion/holdout path; pre-calibration receipt freezing; missing raw proof despite a valid summary; wrong binary/hash, missing command or batch progress; inactive/unreached directed controls; changed geometry, inventory, workload artifact or receipt; stale/post-collection controls; collector failure; and reuse across both arms without rerunning the directed witness. Removing the replay handoff makes the passing case fail. The existing mocked `Runner.measure` test now verifies that the real producer retains its pre-window proof in raw evidence. Fixture setup clears inherited ceiling observations before creating synthetic floors; the x05 observation from run 4 cannot leak into that unrelated synthetic setup.

The exact campaign preflight passed serverlessly, and substituting the previous frozen manifest failed with a changed-file diagnostic and never reached its continuation marker. Logs: `build/nullrefresh4-preflight.log` and `build/nullrefresh4-stale-preflight.log`. Only the preflight prefix was executed. The full script was checked with `bash -n`; the report's single fence equals `build/nullrefresh4-campaign.sh` byte for byte. All frozen checksum entries and `git diff --check` pass. Live control/calibration/null/holdout results remain **PENDING MAINLINE**; a new campaign is not promised to pass its statistical integrity checks.

Lane-added/retired gate rows: **zero**. Neither `EXPECT_*` constant was edited by this lane. The launch merge supplied two upstream writeback rows, `split-phase` and `split-overlap`; the serverless ledger fixture now contains those labels without claiming execution. There is an inherited count discrepancy for the maintainer: `job_wb_rule_units` emits both at line 1264 and is collected at line 2712, before the quick-tier exit at line 2841. Relative to the prior 441/457 counts, the line-based totals should be **443 quick / 459 full**. The merged constants currently say **441 / 459**; correcting `EXPECT_QUICK` remains maintainer work.

**Maintainer campaign.** This is the complete replacement for the nullrefresh3 block. Extract this entire single bash fence; its ready-to-run copy is `build/nullrefresh4-campaign.sh`. Control collection precedes full calibration, import, freeze, identical-arm null, promotion and independent holdout. Default ceiling is 16; setting `NULLREFRESH_MAX_INSTANCES=24` before starting selects a fresh campaign with ceiling 24. No cell is whitelisted, no threshold is widened, and no failed subset is salvaged. Control failure stops before the full campaign; any later failure retains the complete run. The maintainer schedules the live box and handles any subsequent gate or merge.

```bash
set -euo pipefail
cd /home/user/Projects/cx-nullrefresh
# Set NULLREFRESH_MAX_INSTANCES=24 explicitly BEFORE a fresh campaign, if desired.
MAX_INSTANCES="${NULLREFRESH_MAX_INSTANCES:-16}"
case "$MAX_INSTANCES" in 16|24) ;; *) echo 'Choose 16 or 24 instances' >&2; exit 2;; esac
RUN="$PWD/build/nullrefresh4-mainline-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$RUN"
STABLE="$PWD/build/tomokv-nullrefresh4-POST"
GEN="$PWD/build/memtier-nullrefresh4-frozen"
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
        --ports 8700-8799 --port 8700 --build-reference 0)

# Diagnose instrument drift before the clean-tree/ancestry guards can stop us.
printf 'Frozen source commit: %s\nCurrent HEAD: %s\n' \
  0fc66951de2cc6153b4fc9e39dab6cebf972f3fe "$(git rev-parse HEAD)"
printf '%s\n' "$MAX_INSTANCES" > "$RUN/max-instances"
cp build/nullrefresh4-freeze.json "$RUN/instrument-freeze.json"
cp tests/gate_measurements.json "$RUN/before-calibration-inputs.json"
# Do not exit on a checksum failure until the file-level diagnostic has run.
artifact_rc=0
sha256sum -c build/nullrefresh4-campaign.sha256 || artifact_rc=$?
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/instrument.json"
check_instrument build/nullrefresh4-POST.instrument.json "$RUN/instrument.json"
if test "$artifact_rc" -ne 0; then
  echo 'Frozen artifact or initial input checksum mismatch; stop before calibration.' >&2
  exit 1
fi
if test -n "$(git status --porcelain --untracked-files=normal)"; then
  echo 'Worktree changed since freeze; review these paths before a fresh campaign:' >&2
  git status --short >&2
  exit 1
fi
git merge-base --is-ancestor 0fc66951de2cc6153b4fc9e39dab6cebf972f3fe HEAD
# This freeze must retain the server/tailgen build inputs of the launch merge.
git diff --exit-code 0fc66951de2cc6153b4fc9e39dab6cebf972f3fe -- src third_party Makefile tools/tailgen
cmp build/tomokv "$STABLE"
cmp build/tailgen build/tailgen-nullrefresh4-frozen
sha256sum "$STABLE" "$GEN" "$CELLS" build/tailgen > "$RUN/before-calibration.sha256"

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
  git commit -m "Import nullrefresh4 measured floors and ceiling observations"
fi
test -z "$(git status --porcelain --untracked-files=normal)"
taskset -c 112-127 python3 tests/gate_receipt.py freeze-null \
  --calibration "$RUN/calibration/results.json" --reorder-controls "$CONTROL" \
  --output "$RUN/frozen-campaign.json"

# Ceiling plans retain occupancy/workload checks and certify only fixed offered
# load on these byte-identical arms. No ceiling cell acquires a saturated floor.
expect_rc 3 python3 tests/abbagate.py "${COMMON[@]}" --collect-null 1 --output "$RUN/null"
sha256sum "$RUN/null/binary-A" "$RUN/null/binary-B" "$STABLE"
taskset -c 112-127 python3 tests/gate_receipt.py promote-null \
  --campaign "$RUN/frozen-campaign.json" --null-result "$RUN/null/results.json"
cp "$NULL" "$RUN/promoted-null.json"
sha256sum -c "$RUN/reorder-control-receipt.sha256"

# Independent full holdout at the same frozen load and fixed two-sided bounds.
expect_rc 0 python3 tests/abbagate.py "${COMMON[@]}" \
  --reference-binary "$STABLE" --null-result "$RUN/promoted-null.json" --output "$RUN/holdout"
taskset -c 112-127 python3 tests/gate_receipt.py verify-null-holdout \
  --campaign "$RUN/frozen-campaign.json" --null-result "$RUN/promoted-null.json" \
  --comparison "$RUN/holdout/results.json" --output "$RUN/holdout-resolution.json"
sha256sum -c "$RUN/before-calibration.sha256"
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/after-holdout-instrument.json"
check_instrument "$RUN/instrument.json" "$RUN/after-holdout-instrument.json"
sha256sum -c "$RUN/reorder-control-receipt.sha256"
# Stop after holdout. No subset salvage, tolerance changes, gate, or push.
```
