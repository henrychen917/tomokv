# TomoKV Pre-Flight — the per-version stress bench

**Contract: every version runs this before it counts.** A push to the canonical branch, and any
full comparison benchmark, requires a `GO` from `preflight.sh` on the exact binary in question.
`comp_inter.sh` (and any future comparison harness) enforces it mechanically: no fresh sha-matched
`preflight.GO` stamp → refusal to start.

    tools/preflight/preflight.sh <path/to/redis-server>        # full (~2-4h)
    SMOKE=1 tools/preflight/preflight.sh <path/to/redis-server> # quick pass (~20 min)

Suites: knob matrix (−1/0/N semantics) · FLATSTORE/QSBR correctness · numa=2 · script-fence battery
· atomic torn-read/P0/RSS discrimination · feature sweep (oracle equivalence vs stock Redis,
toggle semantics, persistence, known-issues ledger) · controller conformance (SHIFT / ENVELOPE /
NOREG / AUTO==STATIC with timestamp-based stabilization verdicts; client + key + flip LB
families) · flip landing/convergence against in-suite statics · bounded stress.

Verdicts: `FAIL` → NO-GO. `SUSPECT` → doesn't block, printed loudly (sanity-gate rule: stop and
look, never average a bad number away). Every run is archived to
`preflight_reports/<sha>_<ts>.txt` and appended to `preflight_history.tsv` — the cross-version
regression ledger.

## Certification geometry and stamp

The gate has one valid server shape: **2 TomoKV nodes × 16 physical cores per node**. Every fork
boot uses `--tomokv-nodes 2`, a 16-thread-per-node IO+EX budget, `--tomokv-pin-mode ccd`, and the
server CPU partition `0-31`. Load generators use `32-127,160-255`; `128-159` are the SMT siblings
of the server cores and are deliberately excluded.

Every successful boot must log one composed `L3 groups A+B` line for each TomoKV node and at least
32 role-thread pin records. The live task census must also show every server task wholly inside
CPUs 0-31. Missing composition records, an SMT fallback, a floating thread, or any affinity outside
0-31 is a harness-level blocking failure.

`preflight.GO` now has three fields:

```
<binary-sha16> <unix-epoch> 2x16c-v1
```

Consumers must require the exact third field `2x16c-v1` in addition to the existing SHA and age
checks. All two-field stamps and stamps from an older geometry are invalid and cannot authorize a
comparison run.

## Flip landing verdicts and references

Completed `GROW-FRONT` / `GROW-BACK` timestamps define the three outcomes. Search moves before
stabilization are not thrash:

- `STABILIZED_CLEAN`: terminal quiet is at least 45 seconds and no move followed a quiet gap of at
  least 30 seconds.
- `SETTLE_THEN_MOVED`: a completed move followed a quiet gap of at least 30 seconds. This is the
  only thrash failure.
- `STILL_SEARCHING`: the terminal quiet interval is too short. The harness retries once at twice
  the normal observation window, then reports `INCONCLUSIVE-lengthen`, not a controller failure.

P1 cells use a 120-second window; multi-key and p32-class cells use 240 seconds. Once a clean
landing is established, steady throughput comes from `INFO total_commands_processed` deltas while
the same workload remains live. Each cell freshly measures static references at every landed split
and its ±1 neighbors and passes at `>=0.95x` the best discovered reference. The measured split table
is only a starting hint and is never trusted as the verdict reference.

The 2x16c starting hints are `get_p1 io13/ex3`, `get_p16 io11/ex5`, `get_p32 io10/ex6`,
`set_p1 io14/ex2`, `set_p16 io9/ex7`, `set_p32 io8/ex8`, `mget8 io10/ex6`, `mset8 io8/ex8`,
`zrange io7/ex9`, and `mix19 io11/ex5`. Every one is remeasured in the cell that uses it.

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

All wired suites receive `TOMO_PREFLIGHT_DIR`, `TOMO_BIN`, `TOMO_RESULT_FILE`,
`TOMO_SERVER_CORES=0-31`, and `TOMO_LOADGEN_CORES=32-127,160-255`. The full-box landing and atomic
suites additionally receive `TOMO_PORT`; standalone callers must provide their required port.
CPU-set environment variables are accepted only when they exactly equal the certification
partitions above. Suites verify port exclusivity and terminate only child PIDs they started.

Baselines (`command_baselines.tsv`) update only via `UPDATE_BASELINES=1`, never silently.
