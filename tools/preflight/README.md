# TomoKV Pre-Flight — the per-version stress bench

**Contract: every version runs this before it counts.** A push to the canonical branch, and any
full comparison benchmark, requires a `GO` from `preflight.sh` on the exact binary in question.
`comp_inter.sh` (and any future comparison harness) enforces it mechanically: no fresh sha-matched
`preflight.GO` stamp → refusal to start.

    TOMO_WB0_BASELINE_BIN=/path/to/219ec74cc/redis-server \
      tools/preflight/preflight.sh <path/to/unified/redis-server>        # full (~2-4h)
    TOMO_WB0_BASELINE_BIN=/path/to/219ec74cc/redis-server SMOKE=1 \
      tools/preflight/preflight.sh <path/to/unified/redis-server>        # quick pass (~20 min)

Suites: knob matrix (−1/0/N semantics) · permanent WB=0 parity against the retained two-stage
artifact · FLATSTORE/QSBR correctness · numa=2 · script-fence battery
· atomic torn-read/P0/RSS discrimination · feature sweep (oracle equivalence vs stock Redis,
toggle semantics, persistence, known-issues ledger) · controller conformance (SHIFT / ENVELOPE /
NOREG / AUTO==STATIC with settle-first measurement and anti-thrash windows; client + key + flip LB
families) · flip landing/convergence against in-suite statics · bounded stress.

Verdicts: `FAIL` → NO-GO. `SUSPECT` → doesn't block, printed loudly (sanity-gate rule: stop and
look, never average a bad number away). Every run is archived to
`preflight_reports/<sha>_<ts>.txt` and appended to `preflight_history.tsv` — the cross-version
regression ledger.

## Expected-state annotations

`EXPECTED-FAIL-KNOWN <issue-class>` is a temporary, source-visible assertion about a cell's
current state, not a blanket exemption:

- A complete, valid measurement that still misses its acceptance predicate is emitted as
  `KNOWN-FAIL`. The gate driver prints and counts it, but it does not block GO.
- A valid measurement that passes while the annotation remains is an unexpected state change and
  is emitted as blocking `FAIL`. The controller-fix change must remove the annotation; the rerun
  then emits ordinary `PASS`.
- The annotation never excuses an invalid run. Boot failure, crash, missing reference, missing
  `Totals`, or an unreadable observable is always blocking `FAIL`.
- Without an annotation, a predicate miss is an ordinary blocking `FAIL`.

This makes removing the annotation part of claiming the fix and prevents a stale known-issue
entry from silently hiding either a harness failure or a behavior change.

## Harness environment

All wired suites receive `TOMO_PREFLIGHT_DIR`, `TOMO_BIN`, and `TOMO_RESULT_FILE`. The full-box
landing and atomic suites additionally receive `TOMO_PORT`, `TOMO_SERVER_CORES`, and
`TOMO_LOADGEN_CORES`; standalone callers must provide those three. `preflight.sh` accepts global
overrides and per-suite `TOMO_FLIP_LANDING_*` / `TOMO_ATOMIC_TORN_*` port and CPU-set overrides.
Both suites verify port exclusivity and terminate only child PIDs they started.

`wb0_parity.sh` requires `TOMO_WB0_BASELINE_BIN` to name the preserved binary built from
`219ec74cc`; full preflight fails closed when it is missing. It runs one thermal-balanced B,C,C,B
p16 GET cell and compares mean throughput, INFO keys (allowing only zero-valued `tomokv_wb_*`
additions), and idle/load RSS. Its port/CPU defaults can be overridden with
`TOMO_WB0_PARITY_PORT`, `TOMO_WB0_PARITY_SERVER_CORES`, and
`TOMO_WB0_PARITY_LOADGEN_CORES`; tolerances use `TOMO_WB0_OPS_TOL_PCT`,
`TOMO_WB0_RSS_TOL_PCT`, and `TOMO_WB0_RSS_TOL_KB`.

Baselines (`command_baselines.tsv`) update only via `UPDATE_BASELINES=1`, never silently.
