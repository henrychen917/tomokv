# ST2 — published DBSIZE / INFO keyspace counters

Lane: `cx-storesize`. Baseline merged from `origin/cpp` at
`b38916d8884e3d620a9cda85e0a2fec4363173bf`.

PRE: `build/storesize-pre/tomokv`, built in this worktree before source edits,
with `taskset -c 112-127 make -j8 BUILD_ROOT=build/storesize-pre`.
SHA-256: `47b0c843d59a275a7aaa515c733d3fdcee3db8bf9a5525684ac2f7209394e9bc`.
Build log: `build/storesize-pre/build.log`. PRE is frozen; do not rebuild it
against the candidate sources.

Work in progress. No server, load generator, benchmark, or gate has run in this
lane. The maintainer owns the 14-cell null and INFO-poller interference runs.

The baseline has aggregate `published_size()` / `published_expires()` but no
per-physical-database counters or published TTL estimate. Exact per-database
accounting without a keyspace walk requires mutation accounting in the multi-DB
image; that conflicts with literal byte identity of every ordinary command path.
The owner has been asked to resolve that constraint. Default-image hot code will
be audited independently from multi-DB code, with all differences disclosed.

First implementation step restores the default single-DB route. Serverless
`taskset -c 112-127 ./build/storesize-unit --db0-only` passes: plain DBSIZE,
bare INFO and INFO KEYSPACE visit zero slots/objects at 128, 4096 and 16384 keys;
DBSIZE NOW still visits all 32768 slots / 16384 objects in the largest fixture.
It checks one-boundary staleness, equality with the published shard sum after
publication, expiry/PERSIST output and section routing. Receipt:
`docs/storesize/db0-checks.log`. Multi-DB still uses its legacy scatter at this
intermediate commit. No gate row has been added yet.
