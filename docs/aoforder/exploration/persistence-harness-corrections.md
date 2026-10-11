# Harness corrections, not product failures

The first primary driver put `state.json` above the AOF data directory. The unchanged `tests/aof.py` infers its appendonlydir from the state file's parent, so it rejected that invocation. The driver now uses `data/state.json`; all 16 primary cells pass. Original diagnostics remain in `build/aoforder/proof-primary`.

The first snapshot driver invoked `snap_typed_race.py` under atomic=1. The oracle explicitly asserts atomic=0 at line 192 because it tests forced EXEC admission. The gate uses a purpose boot with that default. The corrected driver runs that oracle only in the eight atomic=0 geometry/database/engine cells; the atomic=1 cells still run the MSET atomic cut, ordinary cut, and typed save/reload batteries. All 26 corrected snapshot/shutdown cells pass. No assertion was edited. The rejected invocation and full first summary are retained here.

The first Python gate wiring run exposed the new job being collected without registration in `plan_jobs`; commit `b63f5a07b` registers it. All 66 tests pass afterward. The earlier log is `../gates-test-before-job-registration.log.gz`.

A production-unit build using a custom BUILD_ROOT ran into pre-existing negative-control recipes that assume `build/` paths. The final proof uses the ordinary build root, rebuilds controls, and checks freshness of all 30 targets. The failed custom-root log remains in `build/aoforder/production-final`.

The first serverless shutdown-unit invocation inherited only CPUs 108–111; its fixture explicitly requires eight allowed CPUs for 6:2, so it refused before exercising the unit. The final invocation must use 96–103 after live proof finishes; no fixture changed.
