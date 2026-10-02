# nullpublish2 — campaign 7 re-frozen on the landed server

Worktree `/home/user/Projects/cx-nullrefresh`, branch `cx-nullrefresh`. This report supersedes the campaign-7 fence in `MEASURE-REQUEST-nullpublish.md`. Launch HEAD was `1a6e84455e594ce5ba177506f9f5f9d2157fd669`. The first operation after inspection was `git fetch origin cpp` and `git merge --no-edit origin/cpp`: already up to date, with upstream at `90ba908d3aca61f2b1e79664e839a5b8093145a4`. The launch tree already contained the mainline merge and the two-label fixture repair.

**Re-freeze and source guard.** Frozen source commit: `08d1dd2dbb1d549c83eeb5a8f4792c6b9bd6230b`, the commit recording this build's artifact hashes and instrument snapshot. It replaces `04ac7af4b210a6a232ecedb046071453388e20f6`. The campaign prints both that frozen commit and the actual current `git rev-parse HEAD` before checking anything. Later report-only commits are descendants of the frozen commit; server inputs and instrument bytes remain identical to it. The prefix log at the freeze anchor printed both commits as `08d1dd2dbb1d549c83eeb5a8f4792c6b9bd6230b`; the final committed-tree prefix log is `build/nullpublish2-preflight-only.log`.

The forced rebuild, `taskset -c 112-127 make -B -j16 build/tomokv build/tailgen`, passed without warnings or errors (`build/nullpublish2-rebuild.log`). Both targets were actually recompiled. `build/tomokv-nullpublish-POST` is a separate copy of this build and compares byte-for-byte with `build/tomokv`; tailgen also compares with its new frozen copy. Memtier was retained and re-hashed. The old PRE server and PRE instrument are retained only as historical artifacts: both campaign arms use the **new POST**. No PAD is involved in this tests/instrument-only lane.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `build/tomokv-nullpublish-POST` | 176965512 | `49e69e30d1d3d46f46f8e5f96dad17885511e905c98fba4a3d530814885cf1a7` |
| `build/tailgen-nullpublish-frozen` | 2911008 | `613a6a7e115ba522753a37015a2dbb799325e915030a9f8c3ae95c3a8f4a2d05` |
| `build/memtier-nullpublish-frozen` | 616272 | `9b6ee614dae154c64b17a067a10236b3e6532f7ca52c43b547b87101556dd7d4` |
| `build/nullpublish-POST.instrument.json` | 4575 | `409e9ebbb74775454708663b712339789f0ea55d84ab3da2dabe4343b3084b9d` |
| `build/nullpublish-freeze.json` | 7074 | `84f47ee64377c559c5d2c68fb8e04c742267175ead181108263078dd65833cc2` |
| `build/nullpublish-campaign.sha256` | 880 | `4313b277e309764665e8729ad9e673f32b67889feb46e8df71e5198c0fdb53f6` |
| `build/nullpublish-campaign.sh` | 8952 | `1cc1b045a93f1c9e690003ed9799fb07f08fe12e6f322b1784eb1c72de8526df` |

The previous POST server was `206421de905a2337ba70bad495913e6cd471370747b62f9769a2e4edd4b342af` (177052936 bytes). Its replacement reflects the already-landed upstream server changes; this lane changes no `src`, `third_party`, `Makefile`, or `tools/tailgen` inputs. Tailgen and memtier hashes are unchanged. The merged initial `tests/gate_measurements.json` is now `1bcdd1b4da52c4008801a67c137d3278c8a48dc20b1e1535e815f58f5e6842a7`; the old freeze recorded `55a439801b4f607b4e59d355e77885fb26750d4c2593bd62e1c86ae9d7fae555`. The checksum manifest binds this current input as well. `tests/headline_cells.txt` remains `d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350`.

Instrument SHA-256 before: `183bcb6585b545a2e0e168451c143e6098978024b3367353af9f02ac7cbfdf1c`.

Instrument SHA-256 after: `ef5bb5a313f566a67f70b583708bc087da217c9ec5162a3974bb3483b61617dc`.

Only two scoped entries differ from the previous nullpublish instrument: changed `tests/gate_receipt.py` and new `tests/gate_ledger_fixture.py`. ROOTS, scope, Python implementation/version/executable identity, publication semantics, status arithmetic and bounded repeat policy are unchanged. The instrument manifest file's SHA-256 in the table is distinct from the aggregate instrument fingerprint above. `build/nullpublish-freeze.json` records both fingerprints, both source anchors, the current artifact hashes and the identical-POST arm binding. The old freeze, instrument, checksums, campaign script and check summary remain in `build/nullpublish2-prior-*`. Previous null/campaign evidence cannot be relabeled as evidence for this fingerprint.

**Fixture decision: retain the explicit reviewed fixture.** Its 463 labels are unchanged in this lane. `tests/gate_ledger_fixture.py` checks the full multiset, including repeated AOF labels, against both the source-declared inventory and `EXPECT_FULL`. `gate_receipt.py --self-test` validates it once before creating any receipt Controls fixtures, then runs the ten new controls. A stale fixture now produces one actionable refusal, not a series of `setUp` errors.

The source inventory is read from `tests/gate.sh`: the `collect_job` section from `start_workers` through the full correctness collector barrier, its referenced job declarations, literal finite `for` lists, `FEATURE_BATTERIES`, and public `job_label` declarations. This is a limited Python projection of those declarations, not shell execution. It counts the source-build/external-candidate release alternatives once and each differential group's public fold once. It includes the ABBA negative-control row; the subsequent unscored headline measurement and optional NIC section are outside the non-NIC inventory. Unsupported label expressions refuse and require a checker review. This maintenance check does not certify execution or replace the receipt's real baseline/completion checks.

No run ledger or fixture `source` pathname is read by this check. A partial run therefore cannot redefine its expected inventory. Even shortening both the fixture and `EXPECT_FULL` to one row still fails against the independently read declarations. The fixture remains explicit so source and expected data must be reviewed together instead of automatically accepting a newly observed partial ledger.

Reproducing the launch failure with just the two writeback labels removed reports `EXPECT_FULL=463, fixture=461, source declarations=463`, with these exact missing labels and `Extra fixture labels: none`:

- `writeback policy clauses witnesses + negative controls` (x1)
- `writeback policy paths witnesses + negative controls` (x1)

The diagnostic instructs the maintainer to review row additions/removals and update the fixture while preserving duplicate occurrences; it explicitly forbids changing the expected constants to hide the failure. The ten controls cover the current inventory, that 461-row reproduction, future literal and loop additions, a retired row, same-count substitution and duplicate loss, count-only drift, a shortened fixture plus forged count, unsupported substitutions, and the single pre-setup refusal. Evidence: `build/nullpublish2-stale-fixture-diagnostic.log` and the first suite in `build/nullpublish2-receipt-final.log`.

**Gate counts.** No row was added or retired. `EXPECT_QUICK=446` and `EXPECT_FULL=463` remain untouched. The added tests execute inside the existing `ABBA comparison + saturation negative controls` row, whose collection is before the quick-tier exit; they do not increment either gate count.

**Verification: 369 serverless tests passed, zero skips.** This is the entire prior 359-test set plus ten fixture controls. All builds and test processes were constrained to cores **112–127**. `build/nullpublish2-checks.json` records commands, per-suite counts and log hashes; `build/nullpublish2-serverless-run.log` records the sequential suite outcomes. The historical replay also rechecked campaign 6's unchanged source SHA-256 `501cefeeba9d1f3bb9a2d07ddfd8e6a9f641c422f1758c24f6d0d4fcadfecbb5`, its 188 rows / 141 RESOLVING / 47 UNRESOLVED and the classification-removal control.

| Serverless check | Passing counts | Log under `build/` |
|---|---:|---|
| ABBA / saturation / calibration / binary storage | 100 + 10 + 9 + 16 = 135 | `nullpublish2-abba-final.log` |
| Fixture / receipt / full campaign and sampling | 10 + 18 + 25 = 53 | `nullpublish2-receipt-final.log` |
| Calibration importer | 11 | `nullpublish2-measurements-final.log` |
| Instrument fingerprint | 5 | `nullpublish2-instrument-final.log` |
| Directed reorder witness | 11 | `nullpublish2-reorder-final.log` |
| Exact campaign preflight diagnostic controls | 7 | `nullpublish2-preflight-final.log` |
| Campaign-6 replay and classification-removal control | 1 | `nullpublish2-replay-final.log` |
| Quiet observer / background environment | 8 + 11 | `nullpublish2-quiet-final.log`, `nullpublish2-background-final.log` |
| History / process ownership / shell gate wiring | 55 + 12 + 57 | `nullpublish2-history-final.log`, `nullpublish2-process-final.log`, `nullpublish2-gates-final.log` |
| Tailgen instrument | 3 | `nullpublish2-tailgen-final.log` |

The actual campaign **preflight prefix only** passed at the committed freeze anchor on cores 112–127, including all artifact checksums, exact instrument match, clean worktree, ancestry, `git diff <frozen> -- src third_party Makefile tools/tailgen`, both build/frozen `cmp` guards and disk preflight. It stopped at `PREFLIGHT-COMPLETE` before the first reorder control, calibration, server or generator. Its artifacts remain in `build/nullpublish-mainline-20261001T034327Z/`; A and B share one binary inode. `build/nullpublish2-preflight-at-freeze.log` preserves that run. Both the campaign and extracted prefix pass `bash -n`. Final report/fence equality, artifact checksums and `git diff --check` are also checked.

No server, load generator, benchmark, campaign, or gate was run; no push was made. The prefix is not campaign 7 evidence. The maintainer still runs the following full campaign on the quiet box.

**Campaign 7 fence.** This is byte-identical to `build/nullpublish-campaign.sh`. Compared with the original nullpublish fence, only the three frozen-commit occurrences and their adjacent source-guard comment change. All other contracts remain: MAX_INSTANCES 16 or 24; server 0–31; load 32–127 plus SMT 160–255; ports 8700–8799; disk and binary store preflight; reorder controls; calibration import and commit; freeze-null; `--collect-null 1` with explicit statuses and frozen bounded repeats; promote-null; independent holdout and receipt withholding for UNRESOLVED.

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
  08d1dd2dbb1d549c83eeb5a8f4792c6b9bd6230b "$(git rev-parse HEAD)"
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
git merge-base --is-ancestor 08d1dd2dbb1d549c83eeb5a8f4792c6b9bd6230b HEAD
# Retain the server/tailgen build inputs recorded by this committed re-freeze.
git diff --exit-code 08d1dd2dbb1d549c83eeb5a8f4792c6b9bd6230b -- src third_party Makefile tools/tailgen
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

**Diff against launch.** `git diff 1a6e84455e594ce5ba177506f9f5f9d2157fd669 --stat`:

```text
 MEASURE-REQUEST-nullpublish2.md | 238 +++++++++++++++++++++++++++++++
 tests/gate_ledger_fixture.py    | 306 ++++++++++++++++++++++++++++++++++++++++
 tests/gate_receipt.py           |  12 +-
 3 files changed, 555 insertions(+), 1 deletion(-)
```
