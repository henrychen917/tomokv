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
