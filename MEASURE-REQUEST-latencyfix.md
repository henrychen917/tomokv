## latencyfix

Lane: `cx-latencyfix`, based on `3700b51d7fb3074f32330dd81f138efbf1ddd980`.
No push. Builds and correctness work use CPUs 80–95 only; builds use `-j16`.
Gate servers use 80–87, clients 88–95, 16 shards, split 6:2 or eight fused
threads. All listeners use 47800–47899. Oracle:
`/home/user/Projects/redis74/src/redis-server`; source reference:
`/home/user/Projects/redis/src`.

### Implementation

LAT-HIST-1 now has per-command HDR-compatible histograms: 1 ns–1 s, two
significant decimal digits, integral-microsecond execution samples, Redis's
logarithmic cumulative buckets, and metadata-resolved subcommand names.
The implementation is original C++; production links no Redis code. The
numeric witness alone links the reference HDR library and checks four
distributions, 400,004 percentile queries and exact cumulative bucket output.

`latency-tracking yes|no` deliberately defaults to `no`, documented beside
the config field and in `src/core/README.md` / `docs/CONFIGURATION.md`.
Redis defaults to `yes`. `latency-tracking-info-percentiles` defaults to
`50 99 99.9`, preserving order, duplicates and raw double precision.
Live CONFIG grammar, file/CLI list grammar, validation diagnostics, GET and
REWRITE are covered against the 7.4 oracle. RESP2/RESP3 HISTOGRAM, unknown
selectors, parent/subcommand selection, INFO percentile keys, RESETSTAT and
LATENCY RESET are covered in one directed battery, `tests/latencyfix.py`.

The existing slowlog batch predicate selects the timed arm. At configuration
publication, local-exec TLS callbacks select the exact per-command collector.
Tracked executor templates live in `src/cmd/latency_tracking.cc`, outside the
ordinary executor translation units. The disabled ordinary GET/SET/INCR
command scope adds no predicate or clock read. A small compile-only xshard
budget correction and explicit inlining retain the audited command bodies.

Histogram stores are lazy and cache-line separated by physical thread.
Ordinary histogram writes stay on that thread; queries merge under each store's
lock. Stores are independent of shard ownership, so shard migration has no
histogram pointer to transfer. Disabled fresh boots allocate no histogram store
or bins; previously collected histograms remain readable after disabling, as
in Redis. RESETSTAT clears histograms; LATENCY RESET leaves them intact.

Blocking and scatter commands accumulate active execution slices, excluding
parked/queue intervals, and join them once at retirement. Parallel fragments
contribute the sum of active execution time, not end-to-end wall time.
Transactions and scripts include child command samples. Enabling CONFIG SET
records itself; disabling CONFIG SET does not. Tracking diverts read-local
admission to owner execution while retaining immutable replacement and QSBR.

**Scope of the off-path proof:** the requested GET/SET/INCR command scopes are
measured below. Cold transaction, scripting, deferred-local and blocking paths
contain new timing helpers and disabled checks. This is not a proof of literally
zero added instructions for every registered command. Those cold-path additions
remain a limitation against the task's stronger all-command wording.

### Correctness receipts

The three new gate rows are before the quick-tier exit: **DQ=+3, DF=+3**.
`EXPECT_QUICK` and `EXPECT_FULL` were not edited. Their owner-maintained values
would become **801 / 818**, from 798 / 815.

Directed development proof: `docs/latencyfix/verification6.log` records
6 ok / 0 FAIL (release, two config rows, three new rows); every new row runs both
thread modes and both networking engines. PRE fails all three new rows in all
four legs: `docs/latencyfix/pre-negative.log`. The off-allocation row requires
a positive allocation control after enabling, so a broken tracer cannot pass.

`python3 tests/gates_test.py`: 72/72 passed on an idle lane; receipt:
`docs/latencyfix/gates-test-final.log`. Two earlier attempts collided with
compilation and hit the harness's scheduler-fixture deadlines; no timeout was
changed. Those failed attempts remain recorded.

Final broader job, differential, freshness, layout and binary receipts are
appended below when complete. Initial interrupted development runs are not
counted as proof. Port-collision-only startup rerolls use fresh processes on
the gate slot's three reserved ports; assertion failures are never retried.

### Maintainer merit request

Performance benchmarks and full `tests/gate.sh iteration`: **NOT RUN** here,
reserved to the maintainer. No throughput or latency improvement is claimed.

Use the gate's own ABBA instrument, matched offered load, on the quiet box.
Run the exact 14 generic cells in
`docs/latencyfix/generic14.cells.txt` with tracking **off**:
`h05 h06 p8g p8s d1g_l0 d1s_l0 m8g_l0 v1g_l0 d128g_l0 d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`.
Compare PRE vs POST and PRE vs PAD-A, with contemporaneous PRE/PRE controls.
PRE/PAD have no tracking knob; use their unchanged default. POST uses
`--latency-tracking no`. The required verdict is **null in every cell** under
the gate's normal controls; instruction counts alone are not that verdict.

Then run the eight quick-check cells in
`docs/latencyfix/armed8.cells.txt`:
`h01 h02 h17 h18 h33 h34 h49 h50`.
Use the same frozen POST in both arms, with `--latency-tracking no` versus
`--latency-tracking yes`, leaving percentiles at `50 99 99.9`.
These report armed cost for GET/SET, depth 1/32, both modes. They use read-local
off; the documented admission change when tracking is enabled with read-local
on is not quantified by these eight cells.

Report rate at matched offered load, cycles/op, instructions/op and IPC in each
cell; report the instrument's depth-1 latency result. Record every arm's hash
and configuration. The off cells must be null; the armed cells quantify cost,
with no invented acceptance threshold.

PAD is explicitly **kind A: behaviour twin**, unmodified PRE behavior plus
unreachable text padding to match POST's total .text size and start address.
It is a total-text-size control, not an exact per-symbol/data-layout twin.
That limitation must accompany its results.
