# nullrefresh3 — re-frozen after the reorderwb merge

The campaign is re-frozen at source commit `f6ac245cc2e574a1d9b7ea70bd123b8f98406fb7`, the launch merge on branch `cx-nullrefresh`, in `/home/user/Projects/cx-nullrefresh`. The server sources, third-party sources, Makefile and tailgen sources match mainline `ea45968a93a039fe8af1b5da315b1c8f351bd524` exactly. The frozen POST is a fresh build of those sources. This lane changes the campaign report only; it does not change the measurement policy or server implementation.

**Why run 3 stopped.** The old nullrefresh2 manifest was internally consistent but described the previous instrument. The merge changed four of its 21 dependencies: `tests/abba_saturation.py`, `tests/abba_workloads.py`, `tests/abbagate.py`, and `tests/legacy_reorder_witness.py`. The dependency list and Python identity stayed unchanged. The previous fingerprint was `eda18a6f5a2a5ebc75025cfc5c4acb6ed468c8f7dd3db02306949d3524a6a134`; the new fingerprint is below. `build/nullrefresh3-instrument-diff.json` records both versions of every changed entry. All earlier frozen artifacts and failed campaigns remain intact.

The new preflight prints frozen/current commits and checks the saved artifact hashes. It then prints a unified diff of manifest paths, Git modes and SHA-256 hashes on any instrument mismatch, followed by any scope/root/Python/digest changes, before exiting nonzero. An artifact-checksum failure is held until that diagnostic has run. Even metadata-only or JSON-format-only changes stop the script. The clean-tree and source checks follow the diagnostic, so an uncommitted instrument edit cannot disappear behind an unexplained clean-tree failure. The same diagnostic runs after import and holdout. These messages distinguish changed current inputs from a changed frozen artifact; they do not infer intent from a hash mismatch.

**Frozen artifacts.** Frozen at `2026-09-26T12:35:42.827154+00:00`, before any new live measurements. `build/nullrefresh3-freeze.json` binds source/reference commits, 21 instrument entries plus interpreter identity, build-input inventory, binaries, initial measured inputs, geometry and windows.

| Identity | SHA-256 |
|---|---|
| Instrument fingerprint, canonical payload | `626762386e0e18019593522657ca1ab236b56312797a4a37c2eb935b357e6776` |
| `build/nullrefresh3-POST.instrument.json`, file bytes | `dc5da6008305e88f570c80d2eb09eca854addb5a1929399c4d08f59bef88c817` |
| `build/tomokv-nullrefresh3-POST` | `378407db49e8fa059840e70722fd0ef24cf58183b7982be69e4b5fa980849df2` |
| `build/memtier-nullrefresh3-frozen` | `9b6ee614dae154c64b17a067a10236b3e6532f7ca52c43b547b87101556dd7d4` |
| `build/tailgen-nullrefresh3-frozen` | `613a6a7e115ba522753a37015a2dbb799325e915030a9f8c3ae95c3a8f4a2d05` |
| `tests/headline_cells.txt`, 181 cells | `d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350` |
| `tests/gate_measurements.json`, before calibration | `41ecca7dde04df7972bed3bb725dd386319bb0d0278891b46fd4af1249963be2` |
| `build/nullrefresh3-build-inputs.json` | `61a8884901f828dbe35eb59d727c39c7ee57a83a0bad37ac36d5d850be9a8e99` |
| `build/nullrefresh3-freeze.json` | `67b6c9e4668f940cd88e74baa5d06649b3ae744785561301a83a4c6f064973a5` |
| `build/nullrefresh3-campaign.sha256` | `20346815d7f1c2987ac416b0edc64de8efb68d9fa579a2dfbc2b383c0427be84` |

The server was built with `taskset -c 112-127 make -j8 build/tomokv build/tailgen`; the build passed without warnings. POST equals `build/tomokv` byte for byte. Memtier was copied from `/usr/bin/memtier_benchmark` and retains the previous frozen digest; the freshly built tailgen also retains its previous digest. `build/tailgen` is checked against its frozen copy because the instrument invokes that path. No server or load-generator binary was executed by this lane. No PRE/POST optimization or PAD measurement is requested; both standing-null arms and both holdout arms use the new frozen POST bytes.

**Expected verdicts at the default 16-instance ceiling.** These are diagnoses of run 1, not promises about new measurements. Source: `build/nullrefresh-mainline-20260924T195834Z/calibration/results.json`, SHA-256 `3ef1c1a1575867539034554dfd26e08780545cb2366be4219fab259f446cd73c`. Replaying its three failed ladders through the current classifier produces `build/nullrefresh3-historical-evidence.json`. This read-only replay does not import or salvage the failed campaign.

| Cell(s) | Expected classification from run 1 | Final 12 → 16 rate change | Central server occupancy at 16 | Explanation |
|---|---|---:|---:|---|
| `m09` — fused, rl=0, overlap=0, MGET p32 | **CEILING-UNCONFIRMED** | -1.629186% | 84.834501% | Underfilled and falling; reason `underfilled-flat-or-confounded`. |
| `m21` — fused, rl=0, overlap=1, MGET p32 | **CEILING-UNCONFIRMED** | +7.902625% | 90.940262% | Final rise accompanies fewer workers; reason `underfilled-flat-or-confounded`. |
| `x05` — fused, rl=1, overlap=1, MIX8 p128 | **CEILING-UNCONFIRMED** | +0.452596% | 99.995685% | Occupied, but no valid higher-worker confirmation; reason `occupied-without-confirmation`. |
| Other run-1 cells | 103 PIN + 75 EXEMPT | — | — | The 75 EXEMPT cells include `t05`; all still require complete raw evidence. |
| Cells supported as LOADGEN-BOUND by run 1 | **None** | — | — | Do not relabel any of the three cells above as LOADGEN-BOUND. |

For all three ladders, the worker count falls from 192 at 12 instances to 128 at 16. LOADGEN-BOUND requires a complete ladder to its ceiling, a final gain above 1% with **more** workers, final productive-role occupancy below 90%, and no observed rung reaching 95%. None meets those conditions. The 95% floor, 5pp run margin, 1% plateau tolerance and 2% integrity boundary remain unchanged. Ceiling observations populate `ceiling_loads`, never a saturated `load_floors` entry.

The later run-2 evidence already shows why this table cannot be an allowlist: `m09` and `m21` pinned there, `x05` remained CEILING-UNCONFIRMED, and `t05` failed its permutation witness. On the merged instrument, `t05` remains the canonical p999 EXEMPT cell; exemption does not waive its workload witness. The reorderwb fix allows zero naturally observed permutations only with the bound directed OFF/ON control and progressing live reorder batches. A missing/failed control, missing batch progress or absent commands must still fail. Its serverless positive and negative controls are included below; a new live `t05` result remains maintainer work.

| Phase / result | Expected exit | Meaning |
|---|---:|---|
| Complete calibration with any valid CEILING-UNCONFIRMED or LOADGEN-BOUND cell | **3** | Overall `CEILING-LIMITED`; normal continuation. All 181 rows must be valid and process cleanup complete. If the run-1 classifications repeat: 103 PIN, 75 EXEMPT, 3 CEILING-UNCONFIRMED, 0 LOADGEN-BOUND. |
| Complete calibration with only PIN/EXEMPT cells | **3** | Normal continuation; fresh evidence determined different classifications. |
| Invalid/incomplete calibration, broken `t05` witness, interference, short windows or unreaped children | **1** | Failure; stop and retain the whole run. A ceiling label cannot excuse invalid evidence. |
| Full identical-arm standing-null collection | **3** | `PARTIAL`, then explicit promotion; not a release receipt or holdout certification. |
| Independent full holdout | **0** | Continue to `verify-null-holdout`; fixed two-sided bounds must pass. |

Calibration remains `measurement_valid=false`, `comparison_trusted=false`, `normal_gate_eligible=false`, including a normal rc=3 ceiling-limited run. Ceiling-cell null/holdout evidence describes the calibrated fixed offered load on byte-identical binaries; saturated peak and cycles/op remain UNPROVEN. The campaign does not change any tolerance or hard-code an expected per-cell verdict.

**Serverless validation.** All build/test execution is restricted to cores 112–127. No server, benchmark, gate or push has run. The build log is `build/nullrefresh3-build.log`. The diagnostic tests execute only the exact `check_instrument` function extracted from the campaign, under `set -euo pipefail`, with a continuation marker; they never execute the measurement block.

| Check | Result | Log under `build/` |
|---|---|---|
| ABBA / saturation / calibration self-tests | 100 / 10 / 9 PASS | `nullrefresh3-abba.log` |
| Calibration importer | 11 PASS | `nullrefresh3-measurements.log` |
| Receipt + full campaign import/freeze/promotion/holdout controls | 17 + 12 PASS | `nullrefresh3-receipt.log` |
| Instrument fingerprint controls | 5 PASS | `nullrefresh3-instrument.log` |
| Directed reorder witness controls | 11 PASS | `nullrefresh3-reorder-witness.log` |
| History / process / quiet / background / tailgen controls | 55 / 12 / 8 / 11 / 3 PASS | `nullrefresh3-{history,process,quiet,background,tailgen}.log` |
| Serverless shell/scheduler fixtures | 56 PASS | `nullrefresh3-gates.log` |
| Diagnostic and fail-stop controls | 7 PASS | `nullrefresh3-preflight-controls.log` |

All 327 serverless tests passed. The receipt suite includes the full 181-cell synthetic ceiling import/freeze/promotion/holdout case and its forgery controls; none of that synthetic evidence is imported into the real campaign. The ABBA suite includes the merged `t05` zero-natural-permutation witness control and its invalid-proof/nonprogressing-batch failures. The diagnostic controls exercise the real nullrefresh2 → nullrefresh3 merge difference; additions, removals, mode/hash changes; Python-only changes; malformed/missing manifests; and serialization changes. Removing either the file-diff output or the mismatch failure causes the corresponding assertion to fail.

Exact current/frozen manifests and binary copies match, all entries in `nullrefresh3-campaign.sha256` pass, and shell syntax plus `git diff --check` pass. The report fence equals `build/nullrefresh3-campaign.sh` exactly. The exact campaign preflight also passed serverlessly with only its output-directory label changed; substituting the historical manifest returned rc=1, printed all four changed paths with both hashes and never reached the continuation marker. Logs: `build/nullrefresh3-preflight.log` and `build/nullrefresh3-stale-preflight.log`. The frozen manifest equals the current-tree manifest captured by the failed run 3 byte for byte. These checks establish build and serverless behavior only; the new live campaign remains pending mainline.

Gate rows added or retired: zero. `tests/gate.sh` is unchanged by this lane; quick=441 and full=457 remain unchanged. Neither EXPECT constant is edited.

**Maintainer campaign.** This report's single bash block is the authoritative replacement for the nullrefresh2 block. Its extracted copy is `build/nullrefresh3-campaign.sh`; regenerate any external `calib/nullrefresh-campaign.sh` from this complete fence, not the old line-number slice. All run output stays under `build/`. The maintainer schedules its live geometry: server physical cores 0–31, split ratio 16:16, load physical cores 32–127 plus SMT siblings 160–255. Lane validation used only 112–127. Calibration windows remain 10 seconds; ABBA central windows remain 20 seconds. `NULLREFRESH_MAX_INSTANCES` defaults to **16**; 24 is an explicit fresh-campaign choice whose outcomes are not predicted by the run-1 table.

Calibration is the only phase allowed to change the measured-input JSON, and `freeze-null` binds the imported bytes before null collection. A source, instrument, generator, inventory or initial-input mismatch requires review and a deliberate new freeze. On failure, retain the complete run and stop. This report requests fresh calibration, standing null and independent holdout only; the maintainer handles any later correctness gate or merge.

```bash
set -euo pipefail
cd /home/user/Projects/cx-nullrefresh
# Set NULLREFRESH_MAX_INSTANCES=24 explicitly BEFORE a fresh campaign, if desired.
MAX_INSTANCES="${NULLREFRESH_MAX_INSTANCES:-16}"
case "$MAX_INSTANCES" in 16|24) ;; *) echo 'Choose 16 or 24 instances' >&2; exit 2;; esac
RUN="$PWD/build/nullrefresh3-mainline-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$RUN"
STABLE="$PWD/build/tomokv-nullrefresh3-POST"
GEN="$PWD/build/memtier-nullrefresh3-frozen"
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
  f6ac245cc2e574a1d9b7ea70bd123b8f98406fb7 "$(git rev-parse HEAD)"
printf '%s\n' "$MAX_INSTANCES" > "$RUN/max-instances"
cp build/nullrefresh3-freeze.json "$RUN/instrument-freeze.json"
cp tests/gate_measurements.json "$RUN/before-calibration-inputs.json"
# Do not exit on a checksum failure until the file-level diagnostic has run.
artifact_rc=0
sha256sum -c build/nullrefresh3-campaign.sha256 || artifact_rc=$?
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/instrument.json"
check_instrument build/nullrefresh3-POST.instrument.json "$RUN/instrument.json"
if test "$artifact_rc" -ne 0; then
  echo 'Frozen artifact or initial input checksum mismatch; stop before calibration.' >&2
  exit 1
fi
if test -n "$(git status --porcelain --untracked-files=normal)"; then
  echo 'Worktree changed since freeze; review these paths before a fresh campaign:' >&2
  git status --short >&2
  exit 1
fi
git merge-base --is-ancestor f6ac245cc2e574a1d9b7ea70bd123b8f98406fb7 HEAD
# This freeze must retain the server/tailgen build inputs of the launch merge.
git diff --exit-code f6ac245cc2e574a1d9b7ea70bd123b8f98406fb7 -- src third_party Makefile tools/tailgen
cmp build/tomokv "$STABLE"
cmp build/tailgen build/tailgen-nullrefresh3-frozen
sha256sum "$STABLE" "$GEN" "$CELLS" build/tailgen > "$RUN/before-calibration.sha256"

# Fresh full inventory: 181 cells. Valid PIN/EXEMPT/CEILING-LIMITED => rc=3.
# Run-1 evidence predicts m09/m21/x05 CEILING-UNCONFIRMED, no LOADGEN-BOUND.
# This is an expectation, not an allowlist: classify the new raw evidence.
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
  git commit -m "Import nullrefresh3 measured floors and ceiling observations"
fi
test -z "$(git status --porcelain --untracked-files=normal)"
taskset -c 112-127 python3 tests/gate_receipt.py freeze-null \
  --calibration "$RUN/calibration/results.json" --output "$RUN/frozen-campaign.json"

# Ceiling plans retain occupancy/workload checks and certify only fixed offered
# load on these byte-identical arms. No ceiling cell acquires a saturated floor.
expect_rc 3 python3 tests/abbagate.py "${COMMON[@]}" --collect-null 1 --output "$RUN/null"
sha256sum "$RUN/null/binary-A" "$RUN/null/binary-B" "$STABLE"
taskset -c 112-127 python3 tests/gate_receipt.py promote-null \
  --campaign "$RUN/frozen-campaign.json" --null-result "$RUN/null/results.json"
cp "$NULL" "$RUN/promoted-null.json"

# Independent full holdout at the same frozen load and fixed two-sided bounds.
expect_rc 0 python3 tests/abbagate.py "${COMMON[@]}" \
  --reference-binary "$STABLE" --null-result "$RUN/promoted-null.json" --output "$RUN/holdout"
taskset -c 112-127 python3 tests/gate_receipt.py verify-null-holdout \
  --campaign "$RUN/frozen-campaign.json" --null-result "$RUN/promoted-null.json" \
  --comparison "$RUN/holdout/results.json" --output "$RUN/holdout-resolution.json"
sha256sum -c "$RUN/before-calibration.sha256"
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/after-holdout-instrument.json"
check_instrument "$RUN/instrument.json" "$RUN/after-holdout-instrument.json"
# Stop after holdout. No subset salvage, tolerance changes, gate, or push.
```
