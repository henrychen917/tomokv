# nullpublish3 — receipt duration and reproducible campaign freeze

Report in progress. Launch HEAD: `6eade240dde0c8a79c2c3f3f2b333b3d77d5ea25`.

Run `tools/nullpublish_refreeze.py` after wbhybrid3 lands on mainline. The command
refuses dirty/unlanded trees and pins the rebuild to cores 112–127. No campaign
may use this provisional fence until that command records a schema-3 freeze.

<!-- nullpublish-freeze:start -->
Pending re-freeze on landed mainline.
<!-- nullpublish-freeze:end -->

```bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
FROZEN_COMMIT=08d1dd2dbb1d549c83eeb5a8f4792c6b9bd6230b
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
