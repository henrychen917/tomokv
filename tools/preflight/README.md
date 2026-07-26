# TomoKV Pre-Flight — the per-version stress bench

**Contract: every version runs this before it counts.** A push to the canonical branch, and any
full comparison benchmark, requires a `GO` from `preflight.sh` on the exact binary in question.
`comp_inter.sh` (and any future comparison harness) enforces it mechanically: no fresh sha-matched
`preflight.GO` stamp → refusal to start.

    tools/preflight/preflight.sh <path/to/redis-server>        # full (~2-4h)
    SMOKE=1 tools/preflight/preflight.sh <path/to/redis-server> # quick pass (~20 min)

Suites: knob matrix (−1/0/N semantics) · FLATSTORE/QSBR correctness · numa=2 · script-fence battery
· feature sweep (oracle equivalence vs stock Redis, toggle semantics, persistence, known-issues
ledger) · controller conformance (SHIFT / ENVELOPE / NOREG / AUTO==STATIC with settle-first
measurement and anti-thrash windows; client + key + flip LB families) · command sweep (every
dispatch class × {pipe 1, pipe 32} vs committed baselines, 75%/90% FAIL/SUSPECT) · bounded stress.

Verdicts: `FAIL` → NO-GO. `SUSPECT` → doesn't block, printed loudly (sanity-gate rule: stop and
look, never average a bad number away). `KNOWN` → expected-broken ledger; behavior changes in
either direction flip to FAIL. Every run is archived to `preflight_reports/<sha>_<ts>.txt` and
appended to `preflight_history.tsv` — the cross-version regression ledger.

Baselines (`command_baselines.tsv`) update only via `UPDATE_BASELINES=1`, never silently.
