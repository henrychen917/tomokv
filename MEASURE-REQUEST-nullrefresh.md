# nullrefresh — PENDING MAINLINE

Reference: `3e734cf2e00c087604fcaf145459522e6fa81f05`, branch `cx-nullrefresh`, worktree `/home/user/Projects/cx-nullrefresh`. No push. Instrument only; no server implementation or EXPECT value changed. No server, benchmark, live battery, gate, or performance measurement was run. The build and serverless controls used `taskset -c 112-127`; the unchanged server build used `make -j16 all build/tailgen`.

**Outcome and certification boundaries.** `gate_receipt.py freeze-null` freezes the post-import full inventory, executable instrument, Python identity, generator/server bytes, measured-input bytes, environment, geometry and window. `promote-null` independently replays a completed full null and atomically publishes the standing file, without reading a prior null, start manifest or receipt. It retains the original source bytes, campaign and promotion provenance under `.gate-history/receipts/null-promotions/<source-sha>/`. The promoted artifact remains `run_kind=null-control`, `verdict=PARTIAL`, `comparison_trusted=false`. `finish()` no longer publishes standing nulls. `verify-null-holdout` checks a separate same-binary comparison against the first null's frozen two-sided errors and spreads. It never uses the holdout's own error to widen those bounds. A failed holdout leaves the null's resolution UNPROVEN, even after successful promotion. The commands below stop there on failure; promotion is not independent resolution certification.

A full/push/release receipt still requires exact complete correctness execution, a source/binary binding, a trusted full comparison, comparison rc=0 and completed process cleanup. Neither the promoted null itself nor calibration PIN/EXEMPT evidence can satisfy those validators. Iteration's headline reporting and full receipt certification remain distinct. No owner policy change to rc=3 or removal of abba_rc was made.

**Launch diagnosis, rechecked against the lane reference.**

- PRE `tests/gate_receipt.py:403-421,439,459` requires completed passing comparison evidence before its sole automatic standing-null publication; PRE `tests/abbagate.py:1858-1863,2084-2096` depends on that file to trust a comparison. This is the bootstrap cycle.
- PRE `tests/abbagate.py:1872-1881,2071-2079` already collects identical binary arms independently. PRE `tests/abba_evidence.py:280-298` correctly requires PARTIAL/false for null collection; collection rc=3 stays unchanged.
- PRE `tests/gate_measurements.py:234,268,310,318` disagrees with the existing p1/p999 saturation exemption, and PRE `tests/abba_evidence.py:215` still floors exempt tail occupancy. Fixing two status branches alone would still import or reject EXEMPT as a throughput PIN.
- PRE `tests/gate_receipt.py:27,284-285,483-484` requires the obsolete headline ledger label. Its 437-row/178-cell fixture also has wrong tail exemptions. The launch 181-cell inventory additionally differs from its handwritten parser: value size, implicit tail load=16, and current 8:2 tail mix. Receipt inventory now uses the authoritative `abbagate.read_cells` parser.
- Read-only check of `/home/user/Projects/cx-final/.gate-history/receipts/baselines/full-null.json` confirmed start `2026-09-12T06:45:29Z`, subset smoke, coverage 15, inventory 178. It was neither copied into a standing default nor edited. This lane had no standing file.
- The current mainline ledger label fixture came from `/home/user/Projects/cx-final/build/gate-ledger-iteration.txt`, SHA-256 `e79aaff554742c9b5f1dea7e11903ad92056203a9870a96758eb1fee88f75875`. It has 454 occurrences, 433 distinct labels, including legitimate repeated AOF labels. `tests/fixtures/nullrefresh-ledger-labels.json` contains labels and provenance only; it is not a lane execution receipt or an automatically authorized production baseline.

**Dependency graph and freeze timeline.**

```
PRE:
calibration -> EXEMPT -> PIN-only import refusal
collect full null (independent, PARTIAL) -> receipt-only publication
standing null -> trusted comparison rc=0 -> full gate receipt -> standing null
correctness ledger -> obsolete headline-row requirement -> receipt refusal

POST:
frozen executable instrument + binaries + inventory + geometry
  -> full calibration -> raw replay/import of ordinary rate floors
  -> freeze imported runtime inputs -> full identical-arm null
  -> explicit promotion (PARTIAL/false; resolution still unproven)
  -> independent full identical-arm comparison -> fixed-bound holdout verification
  -> ordinary full comparison + complete correctness ledger/observations -> full receipt
```

PRE was archived BEFORE editing in `build/nullrefresh-PRE/`; it is a standalone local Git snapshot of the reference so mainline can run its instrument without changing another worktree. The PRE code/Python manifest is `build/nullrefresh-PRE.instrument.json`, SHA `a3ae63c61e908a696235a364c8068e7b046b457f382e2c107c20593ccefef7af`; `build/nullrefresh-PRE.dependencies.json` records the transitive graph. A fresh fingerprint of that snapshot exactly matches the saved manifest. Commit `f23c0320f` records this pre-edit graph; `c296f2a4a` implements promotion/exemptions; `b19025f4e` completes raw workload/cleanup replay and mechanism-removal controls. Commit `fa0b1e871c9b112f9e55ec92ec41b87c3a3b33e7` finishes the existing-row helper fixtures and comments. No instrument logic changed afterward. Final executable instrument frozen at **2026-09-24T06:12:10.036918+00:00**, after those commits and BEFORE any mainline calibration:

- `build/nullrefresh-POST.instrument.json`: **beaa4bdfdaaf2c33ea110badf9fa06b9a1e2fa33f1d98604d655a0462d867bb0**, 20 transitive entries plus Python identity.
- `build/nullrefresh-POST.dependencies.json`: complete POST import graph; `build/nullrefresh-POST-instrument/`: committed source snapshot.
- `build/nullrefresh-freeze.json`: code/binary/inventory/geometry/window declaration.
- Full 181-cell inventory bytes: `d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350`.
- Initial measured-input bytes (will change only through the declared import phase): `ceed40110ce6eff7db8533ea717ed1c532255a01f958b8d9df88c6efacc39618`.
- `build/nullrefresh-report-final.instrument.json` matches the frozen POST manifest byte-for-byte after all report/proof work. The `gates_test.py` shell-fixture edit is outside this scoped manifest; the before/after manifests also matched.

The first whole serverless sweep found missing shell stubs for the two newly wired helpers (13 `gates_test.py` failures). The final code commit adds those stubs, and its complete 56-test rerun passes. This was fixture wiring, with no code/threshold edit prompted by a measured cell.

No calibration ran in this lane. Next is MAINLINE calibration DATA only. Importing measured floors does not change the executable instrument fingerprint. Those imported bytes must then be frozen before null and holdout collection. Any bound instrument/import/runtime/inventory/environment/geometry/window/ladder change invalidates reuse. A policy or code edit following a failed cell starts a fresh campaign; do not salvage subsets, retry until green, or increase a tolerance.

**Policy/schema decisions and remaining limits.**

The existing report schema stays 1; the new campaign/provenance kinds are explicit and require the current code fingerprint. Publication additionally requires explicit completed/reaped state, original executable arm files, full coverage without only/escalation salvage, current imported plans, raw saturation replay, raw command/workload/value-size/accounting replay, exact load layouts, age <=24h and complete quiet coverage. The artifact writer writes/fsyncs a temporary file, renames it, and fsyncs its directory. The interruption control stops immediately before replacement and preserves the previous valid file.

The existing `MAX_SPREAD=2`, occupancy floor, per-run margin, plateau tolerance and comparison threshold policy were not widened. Collection can record a large error; promotion refuses a null whose two-sided error or either arm's spread exceeds the existing 2% integrity boundary. Launch inventory comments describe tail spreads above 2% and call tails reporting-only. That is a remaining live obstacle, not permission to calibrate the discrepancy away. Ordinary assessment policy was not redesigned; publication and the held-out resolution check have the explicit stricter eligibility required by this task.

**Cycles/op remains UNPROVEN.** This instrument's null resolution covers the scored rate/latency/tail metrics, not PMU cycles/op, instructions/op or IPC. An injected cycles/op resolution label is rejected. The holdout receipt explicitly says cycles/op UNPROVEN. `tests/abba_profile.py:1-8,325-329` remains diagnostic: grouped-counter IPC uses its own common PMU window, while cycles/op and instructions/op divided by central commands are approximate because the windows are not aligned. No approximate counter was relabeled as aligned. Before using this cleanup as an owner-metric performance claim, mainline must bind and validate its actual qualified cycles/op instrument with separate same-binary calibration/holdout, pairing instr/op and IPC. There is no existing trusted cycles/op certification command in this tree; adding that instrument changes the fingerprint and requires a fresh campaign. No extra scoring policy was invented here.

No server laws, locks, offset assertions, thread modes or database implementations were edited. Both namespaced database builds completed as part of the unchanged server build; live 1s/2s and databases=1/>1 behavior remains PENDING MAINLINE.

**Current implementation anchors.** `tests/gate_receipt.py:198` delegates inventory parsing; `:254` derives the row count; `:260,284,326,338,377` check/freeze/replay/promote/verify the null campaign; `:388,429,504,588` retain begin/start/finish/receipt replay. The independent publication does not execute `finish()`. `tests/abba_evidence.py:308,324,359,369,395` replay workload/completion, enforce integrity, check holdout and match comparison evidence. `tests/abbagate.py:2041-2050` rechecks instrument/import/generator bytes at campaign completion; `tests/load_calibration.py:226-228` publishes explicit reaped and complete state.

**Canonical exemption inventory.** `tests/abba_saturation.py:saturation_exempt` is the sole implementation: depth=1 OR score=p999. `abbagate` imports/re-exports it for coverage, pending-pin selection, load selection, assessment, escalation bookkeeping and variance-pin eligibility. `load_calibration` uses it for selection, its preserved exempt load plan and the all-exempt result. `gate_measurements` uses it when applying floors, validating row/selection/campaign statuses, replaying import and skipping EXEMPT floor publication. `abba_evidence` uses it for exemption validation and occupancy replay. Receipt inventory/freeze also use it. Exemption removes only productive-role FLOOR/plateau requirements; it removes no raw evidence, workload, time, completion, provenance or quiet requirement. All-exempt campaigns validate successfully with no imported floors and unchanged config bytes/load plans. Ordinary depth>1 RATE cannot claim EXEMPT.

| Authoritative predicate / call site | Purpose |
|---|---|
| `tests/abba_saturation.py:22` | One p1/p999 predicate, accepting serialized or dataclass cells |
| `tests/abbagate.py:76,255,552,588,636,822,1827,2060` | Import, coverage, floor selection/status, assessment, pin eligibility, pending and escalation bookkeeping |
| `tests/load_calibration.py:72,89,187,227` | Exempt selection/status, preserve intended load, all-exempt campaign |
| `tests/gate_measurements.py:150,237,244,279,327,329,350` | Floor application, row/campaign/selection validation, replay then skip exempt imports, no-floor all-exempt result |
| `tests/abba_evidence.py:183,215` | Canonical exemption assertion; skip only exempt occupancy accumulation |
| `tests/gate_receipt.py:231,307` | Full inventory eligibility and imported-floor/frozen-geometry checks |

`gate_measurements.py:394` leaves configuration bytes intact when no floors are imported; its CLI at `:725` reports that case explicitly.

**Binary identity and build artifacts.**

```
77a5f58d5258544246bb3746ece88474c222368f068412f24dcb71a47eab925c  build/tomokv
77a5f58d5258544246bb3746ece88474c222368f068412f24dcb71a47eab925c  build/tomokv-nullrefresh-PRE
77a5f58d5258544246bb3746ece88474c222368f068412f24dcb71a47eab925c  build/tomokv-nullrefresh-POST
9b6ee614dae154c64b17a067a10236b3e6532f7ca52c43b547b87101556dd7d4  build/memtier-nullrefresh-frozen
613a6a7e115ba522753a37015a2dbb799325e915030a9f8c3ae95c3a8f4a2d05  build/tailgen-nullrefresh-frozen
```

PRE and POST server bytes, section dumps and relocation dumps are identical. PAD: not needed; no server behavior/layout/text-size change. No old R7 PAD is used. Artifacts: `build/nullrefresh-build.log`, `build/nullrefresh-binaries.sha256`, `build/nullrefresh-{PRE,POST}.sections`, `build/nullrefresh-{PRE,POST}.relocations`, `build/nullrefresh-generator.json`. The memtier copy was not executed. Section dump SHA is `7a35f34d6be1d141dc1361dd328c4ba73235539b58d004f95bab649af2a7e1a2`; relocation dump SHA is `06ff23867a4e0ae39d40f0516f1494447676799bd2fc457a88455514e0e8a0ed` for both arms.

`build/nullrefresh-byte-control.json` proves one executable `.text` byte of the actual PRE server copy was changed at file offset 120416 and rejected by the same file-identity comparison used in promotion/receipts. Corrupt SHA `8ec03df58da7949b717661b23cc6c1d42ec88d9ceeb81c63ee415ba97c174b14`; file `build/tomokv-nullrefresh-byte-corrupt-NEVER-RUN` was never run. The integrated promotion test separately corrupts an ELF arm and proves refusal before replacing its prior good file.

**Serverless proof artifacts.** All commands below used `taskset -c 112-127 python3 ...` and exited 0. Logs contain the test totals and successful results.

| Serverless command | Tests | Proof log |
|---|---|---|
| `tests/gate_measurements.py --self-test` | 11, PASS | `build/nullrefresh-measurements.log` |
| `tests/gate_receipt.py --self-test` | 17 receipt + 11 full-campaign controls, PASS | `build/nullrefresh-receipt.log` |
| `tests/abbagate.py --self-test` | 98 ABBA + 10 saturation + 7 calibration, PASS | `build/nullrefresh-abba.log` |
| `tests/abba_instrument.py --self-test` | 5, PASS | `build/nullrefresh-instrument.log` |
| `tests/gate_history.py self-test` | 55, PASS | `build/nullrefresh-history.log` |
| `tests/gate_process_test.py` | 12, PASS | `build/nullrefresh-process.log` |
| `tests/gates_test.py` | 56, PASS | `build/nullrefresh-gates.log` |
| `tests/gate_quiet.py --self-test` | 8, PASS | `build/nullrefresh-quiet.log` |
| `tests/background_environment_test.py` | 11, PASS | `build/nullrefresh-background.log` |
| `tests/tailgen_stall.py --self-test` | 3, PASS | `build/nullrefresh-tailgen.log` |
| `tests/load_calibration.py --self-test` | 7 standalone, PASS | `build/nullrefresh-calibration.log` |

`build/nullrefresh-checks.txt` and `build/nullrefresh-extra-checks.txt` record exit codes. `git diff --check`, `bash -n tests/gate.sh`, changed-Python compilation, and instrument/section/relocation equality checks passed. The unchanged server/tailgen build exited 0 with no warnings. These are build/serverless results only; neither a live gate row nor a performance cell was run.

PRE controls: `build/nullrefresh-PRE.receipt-controls.log` records the launch fixture failure (16 errors, invalid saturation exemption; exit 1); `build/nullrefresh-PRE.bootstrap.log` records rc=2 for its absent `promote-null` command. The PRE graph above establishes the receipt-only cycle; POST's bootstrap control fails when standalone publication is removed. These are serverless defects/control results, not live campaigns.

Benefit: complete 181-cell promotion without a prior receipt/null, followed by independent fixed-bound comparison replay. Neutral: ordinary already-valid rate PINs retain their selected floor; mixed and all-exempt fixtures preserve p1/p999 plans. Deficit controls: forged, incomplete, partial, unsaturated or mismatched evidence is refused. Every refusal preserves the prior valid standing file. The mutation table below records both the exact exercised rejection and its throwaway mechanism-removal outcome; where another guard still rejects, the original exact-reason assertion fails, and that redundancy is stated rather than presented as acceptance.

| Mutated state | Rejection matched by the test | Throwaway removal result |
|---|---|---|
| different arm hashes | `byte-identical`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| different population | `environment/geometry`; old file intact | Exact rejecting assertion failed; next guard: null arms used different population methods |
| missing cell | `parameters or selected cells`; old file intact | Exact rejecting assertion failed; next guard: ABBA coverage omits or repeats selected cells |
| duplicate cell | `duplicate ABBA cell`; old file intact | Exact rejecting assertion failed; next guard: ABBA parameters or selected cells differ |
| unreached cell | `unreached ABBA cell`; old file intact | Exact rejecting assertion failed; next guard: assessment does not identify exactly one measured load block |
| smoke salvage | `full coverage`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| only salvage | `full coverage`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| future | `timestamps`; old file intact | Exact rejecting assertion failed; next guard: quiet timestamps are outside this ABBA run |
| stale | `quiet timestamps`; old file intact | Exact rejecting assertion failed; next guard: campaign must start after freeze and be at most 24 hours old |
| incomplete timestamp | `timestamps`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| instrument | `fingerprint digest`; old file intact | Exact rejecting assertion failed; next guard: ABBA measurement instrument differs |
| imported inputs | `environment/geometry`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| generator runtime | `environment/geometry`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| inventory | `inventory provenance`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| geometry | `environment/geometry`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| ladder | `measured load block`; old file intact | Exact rejecting assertion failed; next guard: incomplete measurement: t00 |
| window | `shortened measurement`; old file intact | Exact rejecting assertion failed; next guard: campaign window differs |
| cached saturation PASS | `saturation`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| raw unsaturated rate | `productive-role`; old file intact | Exact rejecting assertion failed; next guard: h01: raw campaign assessment failed: ['pinned load level 1 no longer saturates this cell (productive |
| quiet missing | `quiet-box`; old file intact | Exact rejecting assertion failed; next guard: 'NoneType' object has no attribute 'get' |
| quiet span | `span all measurement windows`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| unreaped | `unreaped`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| unfinished | `unreaped`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| failed run | `incomplete measurement`; old file intact | Exact rejecting assertion failed; next guard: h01: raw campaign assessment failed: ['measurement n=1: incomplete or failed ABBA measurement', 'no  |
| missing workload | `missing raw workload`; old file intact | Exact rejecting assertion failed; next guard: h01: invalid raw workload: 'NoneType' object is not subscriptable |
| wrong workload | `did not execute`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| value size | `value size differs`; old file intact | Exact rejecting assertion failed; accepted in throwaway |
| spread integrity | `null control did not complete`; old file intact | Exact rejecting assertion failed; next guard: h01/rate: null exceeds spread/integrity guard |

Every primary mutation above was rejected before replacing the previous valid file. The table records exact test match expressions. “Next guard” means only the targeted exact-reason assertion was defeated; it does not claim the whole forged artifact became acceptable. The quiet-missing removal reaches malformed-input handling, not a valid quiet witness. No negative-control patch remains enabled.

Additional throwaway current-file, freeze and byte-identity controls use the same complete fixture/validators, without editing the frozen instrument: `build/nullrefresh-supplemental-controls.py` (SHA-256 `df9661fc23045c54071e4360deaf16bb33112db652ee7f17de113cd98baecf6b`), run as `taskset -c 112-127 python3 build/nullrefresh-supplemental-controls.py`; exit 0. Results: `build/nullrefresh-supplemental.log`.

| Exercised state | Exact initial failure | Removal result |
|---|---|---|
| current file tests/abba_evidence.py | `campaign instrument/runtime changed` | removal kills exact oracle; h01: unmeasured load floor; re-pin with --escalate before certification |
| current file tests/gate_measurements.json | `campaign imported runtime inputs changed` | removal kills exact oracle; accepted in throwaway |
| current file tests/headline_cells.txt | `campaign inventory/imported plans changed` | removal kills exact oracle; accepted in throwaway |
| current file build/frozen-server | `campaign binary bytes/mode changed` | removal kills exact oracle; campaign generator bytes/mode changed |
| separate generator bytes | `campaign generator bytes/mode changed` | removal kills exact oracle; accepted in throwaway |
| executable byte | `null binary-B bytes differ` | removal kills exact oracle; accepted in throwaway |
| freeze before replay/import | `freeze requires replay/import of this complete calibration first` | removal kills exact oracle; accepted in throwaway |
| frozen campaign overwrite | `FileExistsError` | removal kills oracle; accepted in throwaway |
| forged cycles/op scope | `null control did not complete and pass` | removal kills exact oracle; accepted in throwaway |

Additional controls: remove standalone standing publication -> bootstrap assertion fails; remove `validate_campaign`, `validate_null`, or `validate_null_integrity` -> the corresponding rejection assertion fails; remove atomic replacement -> interrupted-write preservation assertion fails; restore EACH depth-only branch (row status, selection status, import selection, import skip, replay occupancy) -> its p999 depth32 positive fixture fails. Change the common predicate to all-exempt -> the unsaturated depth32 RATE assertion fails. Remove the frozen two-sided holdout error check -> favorable same-binary drift is incorrectly accepted and the rejecting assertion fails. Frozen-before-collection age/ladder/window guards have separate consistent mutations/removal controls, beyond malformed cached summaries.

The complete current correctness label multiset starts and replays a receipt with no headline PASS. Removing the missing-row, duplicate-label, count, own-row-observation or trusted-comparison check fails its corresponding negative assertion. Legitimate repeated labels still require distinct execution observations. Helper failure/skip wiring includes the promotion/receipt and instrument self-tests within the extant ABBA negative-control row.

**Row arithmetic.** Constants remain quick=438/full=454. POST emission anchors: control `ok` at `tests/gate.sh:2345`, BEFORE the quick exit beginning `:2819` (exit command `:2823`); headline context `:2891`, AFTER that exit. The actual PRE launch also emits the control at `:2345` and exits quick at `:2819`; the task's 2808 audit anchor had shifted by launch, and was not used to classify rows. Headline emits zero ok/bad rows. Existing control-row expansion adds zero scored rows: quick 438+0=438; full 438+16+0=454. Optional NIC remains the existing +1. These are source/ledger counts, not a claimed gate run. Exact EXPECT_FULL from `gate.sh` and the caller's trusted label multiset replace the second 437 lower bound in begin/finish/replay. Mainline must review its baseline labels; the fixture is not authority to fabricate execution observations.

**MAINLINE ONLY: exact measurement sequence.** All live/measurement results below are PENDING MAINLINE. Schedule one quiet campaign; do not run these concurrently with builds or another lane. The geometry below matches the rechecked historical environment: server 0-31, no server SMT, load 32-127 plus 160-255 SMT, split 16:16, ceiling 16. Inventory is all 181 launch cells (64 h + 96 m + 6 x + 4 c + 4 a + 7 t), including p1, p32 and the current p8 p999 cells. The serverless p999 depth32 fixture separately attacks the former depth-only branches. Calibration uses the existing 10-second search window; null/holdout/comparison use unchanged 20-second central windows, ABBA order and original workload parameters.

```bash
cd /home/user/Projects/cx-nullrefresh
set -euo pipefail
test -z "$(git status --porcelain --untracked-files=normal)"
RUN="$PWD/build/nullrefresh-mainline-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir "$RUN"
STABLE="$PWD/build/tomokv-nullrefresh-POST"
GEN="$PWD/build/memtier-nullrefresh-frozen"
CELLS="$PWD/tests/headline_cells.txt"
NULL="$PWD/.gate-history/receipts/baselines/full-null.json"
expect_rc() {
  local expected=$1 actual=0
  shift
  "$@" || actual=$?
  test "$actual" -eq "$expected"
}
COMMON=(--subset full --cells "$CELLS" --candidate "$STABLE"
        --memtier "$GEN" --server-cores 0-31 --server-smt ''
        --load-cores 32-127 --load-smt 160-255 --max-instances 16
        --ports 8700-8799 --port 8700 --build-reference 0)
sha256sum "$STABLE" "$GEN" "$CELLS" > "$RUN/before-calibration.sha256"
cp tests/gate_measurements.json "$RUN/before-calibration-inputs.json"
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/instrument.json"
cmp build/nullrefresh-POST.instrument.json "$RUN/instrument.json"

# First collect ALL intended cells. PIN/EXEMPT is deliberately rc=3.
expect_rc 3 python3 tests/abbagate.py "${COMMON[@]}" --calibrate --output "$RUN/calibration"
# Replay all retained raw evidence before one atomic data import.
taskset -c 112-127 python3 tests/gate_measurements.py \
  --import-calibration "$RUN/calibration/results.json" --cells "$CELLS"
taskset -c 112-127 python3 tests/abba_instrument.py > "$RUN/after-import-instrument.json"
cmp "$RUN/instrument.json" "$RUN/after-import-instrument.json"
sha256sum -c "$RUN/before-calibration.sha256"
cp tests/gate_measurements.json "$RUN/imported-inputs.json"
# Only measured DATA may change. Commit it so the eventual receipt can certify HEAD.
if ! git diff --quiet -- tests/gate_measurements.json; then
  git add tests/gate_measurements.json
  git commit -m "Import nullrefresh measured load floors"
fi
test -z "$(git status --porcelain --untracked-files=normal)"
taskset -c 112-127 python3 tests/gate_receipt.py freeze-null \
  --calibration "$RUN/calibration/results.json" --output "$RUN/frozen-campaign.json"

# Freeze -> full identical-arm collection -> explicit local promotion.
expect_rc 3 python3 tests/abbagate.py "${COMMON[@]}" --collect-null 1 --output "$RUN/null"
sha256sum "$RUN/null/binary-A" "$RUN/null/binary-B" "$STABLE"
taskset -c 112-127 python3 tests/gate_receipt.py promote-null \
  --campaign "$RUN/frozen-campaign.json" --null-result "$RUN/null/results.json"
cp "$NULL" "$RUN/promoted-null.json"

# NEW measurements; no --collect-null, no --only, no reusing the first run.
expect_rc 0 python3 tests/abbagate.py "${COMMON[@]}" \
  --reference-binary "$STABLE" --null-result "$RUN/promoted-null.json" --output "$RUN/holdout"
taskset -c 112-127 python3 tests/gate_receipt.py verify-null-holdout \
  --campaign "$RUN/frozen-campaign.json" --null-result "$RUN/promoted-null.json" \
  --comparison "$RUN/holdout/results.json" --output "$RUN/holdout-resolution.json"
# A failed holdout STOPS here: no altered floor, interval, cell set or tolerance.

# Ordinary source-built candidate comparison; this lane's server bytes must still equal STABLE.
cmp build/tomokv "$STABLE"
expect_rc 0 python3 tests/abbagate.py "${COMMON[@]}" --candidate "$PWD/build/tomokv" \
  --reference-binary "$STABLE" --null-result "$RUN/promoted-null.json" --output "$RUN/comparison"

# Owner reviews the existing full correctness ledger before using it as an expectation.
cp /home/user/Projects/cx-final/build/gate-ledger-iteration.txt "$RUN/reviewed-correctness.tsv"
export GATE_RECEIPT_BASELINE="$RUN/reviewed-correctness.tsv"
export GATE_ABBA_MEMTIER="$GEN" GATE_ABBA_NULL="$RUN/promoted-null.json"
export GATE_RECEIPT_NULL="$RUN/promoted-null.json"
# Use the normal source build; an external --candidate-binary cannot certify this source tree.
bash tests/gate.sh push --server-cores 0-31 --server-smt '' \
  --load-cores 32-127 --load-smt 160-255 --reference-binary "$STABLE"
cmp build/tomokv "$STABLE"
# Replay the persisted full receipt for this exact committed tree; this does not push.
taskset -c 112-127 python3 tests/gate_receipt.py verify --ref HEAD > "$RUN/full-receipt-replay.txt"
# Mainline also replays iteration, after the full workflow, under the same quiet schedule.
bash tests/gate.sh iteration --server-cores 0-31 --server-smt '' \
  --load-cores 32-127 --load-smt 160-255 --reference-binary "$STABLE"
cmp build/tomokv "$STABLE"
```

The reviewed ledger path is an explicit owner input; verify its current 454-row multiset against the committed fixture/current source before starting the full gate. Never turn the label fixture into synthetic own-row observations. The push command's normal begin/bind/coordinator/finish workflow and receipt replay must complete; report that separately from iteration. If the null ages out, changes inputs, exceeds the integrity guard or fails holdout, stop and record failure. No live result above has been inferred from unit tests.

For the PRE instrument arm, use the same STABLE/GEN bytes and geometry in its frozen source directory, with a separate output directory and its own calibration evidence. Do not import POST's fingerprint-bound evidence into PRE:

```bash
PRE="$PWD/build/nullrefresh-PRE"
PRE_RUN="$RUN/PRE-instrument"
mkdir "$PRE_RUN"
(
  cd "$PRE"
  expect_rc 3 python3 tests/abbagate.py "${COMMON[@]}" \
    --cells "$PRE/tests/headline_cells.txt" --calibrate --output "$PRE_RUN/calibration"
  # Expected old full import refusal on valid EXEMPT tail evidence; record the exact reason.
  expect_rc 1 taskset -c 112-127 python3 tests/gate_measurements.py \
    --import-calibration "$PRE_RUN/calibration/results.json" --cells "$PRE/tests/headline_cells.txt"
  # The PRE command is absent: this serverless check returns argparse rc=2.
  expect_rc 2 taskset -c 112-127 python3 tests/gate_receipt.py promote-null
)
```

Run PRE and POST campaigns separately on the scheduled quiet box. If PRE calibration itself fails, retain that full failure rather than manufacturing EXEMPT/PIN evidence to reach the import step. The older calibrator's tail load-plan selection is part of the defect; do not describe rates from different load plans as matched performance. The code A/B keeps identical server bytes in EVERY arm; no PAD. The decisive benefit is closing the formerly blocked full campaign while maintaining negative-control refusals. POST success requires complete provenance/coverage, every held-out scored metric within the first null's fixed two-sided resolution, and no directional drift resolved by that fixed instrument. Promotion success alone is insufficient. The subsequent ordinary comparison must meet per-cell stable-reference parity. Owner metrics cycles/op with paired instr/op and IPC, plus rate/tails PRE/POST, are PENDING MAINLINE and require the PMU qualification above.

| Arm/result | Full null bootstrap/import | Independent fixed-bound holdout | Cycles/op, instr/op, IPC | Rate/tails |
|---|---|---|---|---|
| PRE live instrument | PENDING MAINLINE; old refusal expected | PENDING MAINLINE | PENDING MAINLINE | PENDING MAINLINE |
| POST live instrument | PENDING MAINLINE | PENDING MAINLINE | UNPROVEN/PENDING MAINLINE | PENDING MAINLINE |
| Serverless benefit/neutral/deficit fixtures | Validated separately as above | Synthetic replay only | No measurements | No measurements |

`sha256sum build/tomokv` is given above. `git diff 3e734cf2e00c087604fcaf145459522e6fa81f05 --stat`:

```text
 MEASURE-REQUEST-nullrefresh.md                | 289 ++++++++++++++
 tests/_abba_test_fixtures.py                  |  17 +
 tests/_nullrefresh_test.py                    | 551 ++++++++++++++++++++++++++
 tests/abba_evidence.py                        | 102 ++++-
 tests/abba_saturation.py                      |  11 +
 tests/abbagate.py                             |  53 +--
 tests/fixtures/nullrefresh-ledger-labels.json | 461 +++++++++++++++++++++
 tests/gate.sh                                 |  32 +-
 tests/gate_measurements.py                    |  44 +-
 tests/gate_receipt.py                         | 344 +++++++++++-----
 tests/gates_test.py                           |  11 +-
 tests/load_calibration.py                     |  19 +-
 12 files changed, 1771 insertions(+), 163 deletions(-)
```
