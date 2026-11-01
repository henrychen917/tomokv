Reused from `/home/user/Projects/round4-read/repro-blocking` (2026-10-31).

Witness algorithms and raw JSON logs are retained. Imports are relative; the boot helper takes binary, oracle, CPU, engine, database count and artifact directory from the gate wrapper. The wrapper turns observations into required assertions and fails if the risky window never opens. Wave14 includes RESTORE-stream: wave13's persistfmt supplies D9's stream image format, so the existing creator row now requires its parked XREAD waiter to wake with the oracle-exact image.

The lane also records target key names for exact reply comparisons and extends the existing FLUSH-plus-RENAME witness to FLUSHDB/FLUSHALL ASYNC. `witness.json` records the source and binary hashes used by each gate row.
