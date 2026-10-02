nullrefresh5 — campaign binary storage and disk preflight

Implemented on `cx-nullrefresh` in `/home/user/Projects/cx-nullrefresh`. Requested mainline **`9c4717da03b9340377926277f8eb99cea9f5ab5a`** was merged first in **`5613afa1db3ddb99ef2bdd0eb8cbcb471c79c910`**. Instrument implementation: **`64fec17603a5a3f9c69c95dfd5efc8e4204caf6d`**. Server, third-party, Makefile and tailgen sources match the requested mainline exactly. All builds, executable self-tests and preflight checks used **cores 112–127**. No server, benchmark, gate, measurement or push was run. Live controls, calibration, null and holdout remain **PENDING MAINLINE**.

**Failure and copy audit.** The maintainer identified the deletion as the mainline age-prune acting on preserved source mtimes; this report does not attribute it to the disk guard. The retained calibration started `2026-09-28T22:42:56Z`, lasted 7,749.994 seconds, and contains 181 rows. t04 and t06 report `taskset` exit 127 for the same missing `calibration/binary-B`; t05 reports that same path missing while checking the control. Its results SHA-256 is `6a930644ddd4689e8a92c782d3c0bd4c410365fe0cf3a605d30d11fe940630c8`. Existing campaign artifacts were only read.

One correction matters for the footprint claim: the inspected launch code did **not** copy inside each cell loop. `abbagate.main` copied A/B once per invocation; `load_calibration.main` copied B once per invocation. The old report's controls → calibration → null → holdout script therefore made six payload copies, while nested per-cell `--pin` invocations could multiply copies. The stated 181 × two-arm scenario is reported separately below; it is not presented as an observed 60 GB allocation in this retained run. Both paths now share the campaign store.

| Binary payload / campaign budget | Bytes | Basis |
|---|---:|---|
| Before: stated 181 cells × two old 177,039,904-byte arms | 64,088,445,248 | 64.09 GB / 59.69 GiB scenario |
| Before: inspected four-phase script, six old payload copies | 1,062,239,424 | Source-derived full-script allocation |
| After: identical arms, all phases and cells | **177,057,184** | One new snapshot inode, two arm names; hard-link aliases |
| Nonbinary artifact reserve | 1,610,612,736 | 1,536 MiB, including promotion/receipt copies |
| **After: complete campaign preflight budget** | **1,787,669,920** | **1.788 GB / 1.665 GiB; under 2 GB** |
| Disk guard floor | 42,949,672,960 | 40 GiB, read from both project disk-guard scripts |
| Required available bytes before staging | **greater than 44,737,342,880** | Footprint plus floor; equality refuses |

`build/nullrefresh5-footprint.json` retains the calculation and source hashes. The artifact estimate uses the retained full calibration (223,952,725 bytes), a retained full null (527,212,808 bytes, also used as the holdout proxy), controls (19,179,012 bytes), and raw/compact promotion copies. That projects **1,546,210,991 nonbinary bytes**, below the 1,536 MiB reserve. This is a budget derived from prior artifacts, not a measured new-campaign total or a hard cap on logs. Other writers and longer runs can consume more space; the instrument also checks the 40 GiB floor before each cell. Frozen build products and compiler objects already on disk are reflected in available space, rather than charged again as new campaign allocation. Different A/B input inodes are each charged once.

**Implementation.** `tests/abba_binaries.py` owns the feature. The campaign preflight streams external binary bytes once into `RUN/binary-A`, creating a fresh mtime without `copy2`/`cp -p`. Identical sources produce `RUN/binary-B` as a hard link. `RUN/binaries.json` records each arm's original source, SHA-256, device, inode, size, mode and timestamp. It is never refreshed or rewritten during the campaign. Controls, calibration, null and holdout pass `--binary-store "$RUN"`; their receipt-compatible `binary-A`/`binary-B` paths are hard links. Nested pin runs inherit the same store. A cross-filesystem link failure stops the run; there is no copying fallback.

Each cell verifies its arm's inode and SHA-256 before any directed control or measured boot. Subsequent boots/rungs and the end of each window recheck the manifest, inode and metadata; completion rechecks full digests. The receipt's existing executable-byte checks continue to work on the hard links. A missing canonical snapshot, alias or manifest raises an **ABBA binary guard** error naming the missing path and the prune/disk-guard retention requirement. The affected cell fails; the instrument does not restore the file or retry the cell. Boot passes an already-open verified descriptor through `taskset`, closing the check/exec unlink window; a concurrent unlink is still rejected by the post-window guard. Recorded `server_argv` retains the logical snapshot path, and `executable_launch` identifies descriptor launch. The mainline's separate live-run retention repair remains necessary; this lane did not edit either external prune/guard script.

The preflight uses filesystem available bytes and refuses **before binary staging or any control/calibration workload** if the projected remainder reaches 40 GiB. It prints available bytes, binary bytes, artifact reserve, total footprint, projected remainder and floor. Its actual serverless check observed 61,350,191,104 available bytes and a projected remainder of 59,562,521,184 bytes. That observation is not a reservation or a promise about availability when mainline launches.

**Refreeze.** Frozen at `2026-09-29T05:57:14.451463+00:00`. The instrument has **23 dependencies**: `tests/abba_binaries.py` was added; only `tests/abbagate.py` and `tests/load_calibration.py` changed among its prior dependencies. Interpreter identity and roots are unchanged. The prior fingerprint was `fc74133ba150adab5cc16d06b577b343f183a4e0f4c9ae666c3393ec1973c86f`; the file-level comparison is `build/nullrefresh5-instrument-diff.json`.

| Artifact / identity | SHA-256 |
|---|---|
| `Instrument fingerprint (canonical payload)` | `cc6c06bde1ce7939b7f001489fde7287476c4086929f51badf774811d087dd36` |
| `build/tomokv-nullrefresh5-POST` | `ef52de792f72ab8dae240fcd8194e1f14aa94b3828dc7e512eea7256b50c1133` |
| `build/memtier-nullrefresh5-frozen` | `9b6ee614dae154c64b17a067a10236b3e6532f7ca52c43b547b87101556dd7d4` |
| `build/tailgen-nullrefresh5-frozen` | `613a6a7e115ba522753a37015a2dbb799325e915030a9f8c3ae95c3a8f4a2d05` |
| `build/nullrefresh5-POST.instrument.json` | `ce0967f2e8b932367c3da15f276eec21b561cb8d7ddc11ca31b954671378f683` |
| `build/nullrefresh5-build-inputs.json` | `edff42eb44a0a15d52b54c0a20d8d343cf730e7b6300d4438fe7f12669584dec` |
| `tests/headline_cells.txt` | `d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350` |
| `tests/gate_measurements.json` | `2e5fce980873056bc5da0a0b7e27a7e197ed2cc40ae61dd261408c5542746e1b` |
| `build/nullrefresh5-freeze.json` | `0a190d81984cb27ee896145601b73f1ad10bec517e21db1d6275cc0cf3866fbe` |
| `build/nullrefresh5-campaign.sh` | `2eb0c2b02411d2bfaf2b0e542d2d26f517d71a9c891a40eb36db9bf409c0fd31` |
| `build/nullrefresh5-campaign.sha256` | `198950f5af7ed4bc700752d36149b7311d385b88f5e3c97849a97f783edcae41` |
| `build/nullrefresh5-footprint.json` | `fad4af884330772164a17cbe9a27584fdaa1f582ef2059da2f4acfc7d46227b6` |
| `build/nullrefresh5-instrument-diff.json` | `f674c3a5bad1d025e88c61422dcc87fc4ad52ffdcb789c21b0cfb73d4a740655` |

| `build/nullrefresh5-checks.json` | `ea5a1af0d5c1a76343fff8ecb64721801e6503341e4a70ea10be651290390db3` |

`taskset -c 112-127 make -j8 build/tomokv build/tailgen` passed without warnings; log: `build/nullrefresh5-build.log`. Frozen POST equals the rebuilt `build/tomokv`, frozen tailgen equals `build/tailgen`, and memtier was copied from `/usr/bin/memtier_benchmark`. These three programs were hashed and compared, never executed by this lane. There is no server optimization, server layout change, PRE/POST performance claim or PAD arm. Both null and holdout arms use the new frozen POST.

**Serverless validation.** **205 tests passed**, including the final receipt replay on the frozen tree. `build/nullrefresh5-checks.json` records their log digests and counts. The initial receipt run was invalidated by concurrent instrument edits; it was rerun after the final source freeze.

| Check | Result | Log under `build/` |
|---|---|---|
| ABBA / saturation / calibration | 100 / 10 / 9 PASS | `nullrefresh5-abba-final.log` |
| Campaign storage and space guards | 16 PASS | Included in `nullrefresh5-abba-final.log` |
| Receipt / full campaign controls | 17 / 19 PASS | `nullrefresh5-receipt-final.log` |
| Calibration importer | 11 PASS | `nullrefresh5-measurements-test.log` |
| Instrument fingerprints | 5 PASS | `nullrefresh5-instrument-final.log` |
| Directed reorder witness | 11 PASS | `nullrefresh5-reorder-final.log` |
| Exact shell preflight diagnostic and fail-stop | 7 PASS | `nullrefresh5-preflight-controls.log` |

The 16 new tests cover 181 cells across all four phases sharing one payload; distinct arms; fresh mtime and isolation from a later source rewrite; rejecting byte-identical copies in place of links; cross-filesystem failure without a copy; deleted canonical files, aliases and manifests; inode replacement; content corruption with restored mtime; changed source/manifest; the exact disk-space boundary; no staging on refusal; cell failure before any child launch; descriptor lifetime on failed launch; and per-cell digest checks. A harmless `/usr/bin/true` fixture exercises the real child launcher and `taskset`: deleting the pathname during launch returns 0 through the open descriptor, after which the binary guard rejects the missing path. No server or load generator is involved. These tests are part of the existing `abbagate.py --self-test` battery.

Only the generated script's **preflight prefix** was executed (`build/nullrefresh5-preflight.log`); it stopped at `PREFLIGHT-COMPLETE` before the first control. Substituting the previous instrument manifest failed with the three-file diagnostic, before staging or any continuation (`build/nullrefresh5-stale-preflight.log`). The complete campaign passes `bash -n`. Its single fence below is byte-identical to `build/nullrefresh5-campaign.sh`. Artifact checksums and `git diff --check` pass. Gate rows added/retired by this lane: **zero**; neither `EXPECT_QUICK` nor `EXPECT_FULL` was edited, and no count change is requested.

**Maintainer campaign.** Extract this entire single bash fence, or use its identical ready-to-run copy at `build/nullrefresh5-campaign.sh`. Start a fresh run on the scheduled quiet box. This preserves the existing full 181-cell controls → calibration → import → freeze → identical-arm null → promotion → independent holdout protocol, its workload/proof checks, fixed statistical bounds and age rules. Default ceiling is 16; set `NULLREFRESH_MAX_INSTANCES=24` before launch for a fresh ceiling-24 campaign. No old campaign is salvaged or promoted, no threshold is widened, and any refusal stops this script. The measurement verdict remains the existing full null/holdout verdict; no new performance result is claimed here.

```bash
set -euo pipefail
cd /home/user/Projects/cx-nullrefresh
# Set NULLREFRESH_MAX_INSTANCES=24 explicitly BEFORE a fresh campaign, if desired.
MAX_INSTANCES="${NULLREFRESH_MAX_INSTANCES:-16}"
case "$MAX_INSTANCES" in 16|24) ;; *) echo 'Choose 16 or 24 instances' >&2; exit 2;; esac
RUN="$PWD/build/nullrefresh5-mainline-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$RUN"
STABLE="$PWD/build/tomokv-nullrefresh5-POST"
GEN="$PWD/build/memtier-nullrefresh5-frozen"
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
  64fec17603a5a3f9c69c95dfd5efc8e4204caf6d "$(git rev-parse HEAD)"
printf '%s\n' "$MAX_INSTANCES" > "$RUN/max-instances"
cp build/nullrefresh5-freeze.json "$RUN/instrument-freeze.json"
cp tests/gate_measurements.json "$RUN/before-calibration-inputs.json"
# Do not exit on a checksum failure until the file-level diagnostic has run.
artifact_rc=0
sha256sum -c build/nullrefresh5-campaign.sha256 || artifact_rc=$?
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/instrument.json"
check_instrument build/nullrefresh5-POST.instrument.json "$RUN/instrument.json"
if test "$artifact_rc" -ne 0; then
  echo 'Frozen artifact or initial input checksum mismatch; stop before calibration.' >&2
  exit 1
fi
if test -n "$(git status --porcelain --untracked-files=normal)"; then
  echo 'Worktree changed since freeze; review these paths before a fresh campaign:' >&2
  git status --short >&2
  exit 1
fi
git merge-base --is-ancestor 64fec17603a5a3f9c69c95dfd5efc8e4204caf6d HEAD
# This freeze must retain the server/tailgen build inputs of the launch merge.
git diff --exit-code 64fec17603a5a3f9c69c95dfd5efc8e4204caf6d -- src third_party Makefile tools/tailgen
cmp build/tomokv "$STABLE"
cmp build/tailgen build/tailgen-nullrefresh5-frozen
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
  git commit -m "Import nullrefresh5 measured floors and ceiling observations"
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
expect_rc 0 python3 tests/abbagate.py "${COMMON[@]}" \
  --reference-binary "$STABLE" --null-result "$RUN/promoted-null.json" --output "$RUN/holdout"
taskset -c 112-127 python3 tests/gate_receipt.py verify-null-holdout \
  --campaign "$RUN/frozen-campaign.json" --null-result "$RUN/promoted-null.json" \
  --comparison "$RUN/holdout/results.json" --output "$RUN/holdout-resolution.json"
sha256sum -c "$RUN/before-calibration.sha256"
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/after-holdout-instrument.json"
check_instrument "$RUN/instrument.json" "$RUN/after-holdout-instrument.json"
sha256sum -c "$RUN/reorder-control-receipt.sha256"
sha256sum -c "$RUN/binary-manifest.sha256"
# Stop after holdout. No subset salvage, tolerance changes, gate, or push.
```
