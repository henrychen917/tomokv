## latencyfix

Lane: `cx-latencyfix`, based on `3700b51d7fb3074f32330dd81f138efbf1ddd980`.
No push. Builds and correctness work use CPUs 80–95 only; builds use `-j16`.
Broader gate servers use 80–87 and clients 88–95. The epoll differential matrix
uses servers 88–95 / clients 80–87; the final uring matrix uses the first
allocation. Both use 16 shards, split 6:2
or eight fused threads. Only correctness traffic overlaps; instruction-count
witnesses were collected before these runs. All listeners use 47800–47899. Oracle:
`/home/user/Projects/redis74/src/redis-server`; source reference:
`/home/user/Projects/redis/src`.

### Implementation

LAT-HIST-1 now has per-command HDR-compatible histograms: 1 ns–1 s, two
significant decimal digits, integral-microsecond execution samples, Redis's
logarithmic cumulative buckets, and metadata-resolved subcommand names.
The implementation is original C++; production links no Redis code. The
numeric witness alone links the reference HDR library and checks four
distributions, 400,004 percentile queries and exact cumulative bucket output
(`docs/latencyfix/histogram-numeric-final.log`).

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
zero added instructions for every registered command. **The literal all-command
zero-added-instruction requirement is not met by this implementation.** In
particular, transaction child cleanup can scan the lazy store slots while off.
This is an acceptance gap, not a performance claim or a passing universal proof.

### Correctness receipts

The three new gate collectors are at lines **5552–5554**, before the quick-tier
exit at line **5642**: **DQ=+3, DF=+3**. The line/count witness is
`docs/latencyfix/row-accounting.json`.
`EXPECT_QUICK` and `EXPECT_FULL` were not edited. Their owner-maintained values
would become **801 / 818**, from 798 / 815.

Final directed proof: `docs/latencyfix/directed-final.log` records
4 ok / 0 FAIL (release and three new rows); every new row runs both
thread modes and both networking engines. PRE and PAD-A each fail all three
new rows in all four legs, while their oracle legs pass. See
`docs/latencyfix/directed-proof.json` and the complete checks/boot commands in
`docs/latencyfix/directed-receipts/`. The off-allocation row requires a positive
allocation control after enabling, so a broken tracer cannot pass.

The resolved broader job set has **336 passing scored rows across 57 jobs**
(including build prerequisites with no scored row). These are partial-job
results, not a full gate receipt. `docs/latencyfix/gate-proof-index.json` retains
each run, each historical failure and the latest result for each job.

The broad run's one failure was a serverless read-local fixture that manually
bound an IoLoop without adopting its live configuration. The fixture now calls
the same refresh used by production; its existing engagement assertions remain.
The analogous R7 fixtures needed the same initialization. R7's strict audit
also needed its explicit inventory extended from 312 to 326 physical bodies:
14 newly outlined bodies, none removed and no inherited clone-count changes.
Its final byte comparisons and missing-symbol/opcode negative controls pass.
These changes are confined to test setup and inventory; the production binary
hash did not change.

The required test search found the explicit INFO section list in
`tests/rlfix3_info.py`. It now includes `latencystats` in ALL/EVERYTHING and
excludes it from DEFAULT. All eight mode/engine/read-local legs pass, including
both native database-runtime witnesses. Legacy slowlog/latency, redaction,
CONFIG, COMMAND, arity, subcommand, INFO, transaction, blocking, scripting,
shutdown and concurrency jobs also pass. Search receipts are
`docs/latencyfix/{test-surface-search,info-latency-search-final,latency-reply-search-final}.log`;
the INFO parser unit tests additionally pass 10/10.

`python3 tests/gates_test.py`: 72/72 passed on an idle lane; receipt:
`docs/latencyfix/gates-test-final.log`. Two earlier attempts collided with
compilation and hit the harness's scheduler-fixture deadlines; no timeout was
changed. The first failed attempt remains in `docs/latencyfix/gates-test.log`.

Initial interrupted development runs are not counted as proof.
Port-collision-only startup rerolls in the directed battery use fresh processes
on the gate slot's three reserved ports; assertion failures are never retried.

The standard differential jobs are complete on both engines, including both
atomic settings, split and armed fused execution, the four additional seed-19
MULTI repetitions, and the mode-equivalence job:

| Engine | Comparison legs | Mode-equivalence cells | Failed comparisons in accepted runs |
|---|---:|---:|---:|
| uring | 1124 | 16 | 0 |
| epoll | 1124 | 16 | 0 |

Receipts: `docs/latencyfix/differ-proof.json` and `differ-receipts/` retain each
standard plan, seed list, completion artifact, command coverage and log.
The uring matrix used seeds `7 19 20 23 21 22`. The original epoll matrix used
`7 19 20 23 21 24`; its fused/atomic-1 replacement used the next standard plan,
`7 19 20 23 21 25`. Each engine's accepted jobs report 1127 passing checks,
including two read-local engagement checks and the aggregate equivalence check.

Two initial runs hit `EADDRINUSE` in climon's control listener: uring
split/atomic-0 seed 21, and epoll fused/atomic-1 seed 20. They recorded no
comparison witness and were retained as failures. The uring matrix was rerun
in full. For epoll, all already-passing jobs remain in the receipt and the
entire failed fused/atomic-1 job was rerun with standard seeds on ports
47891–47893. No test or time limit was relaxed. Standard fused SORT legs are
**NOT RUN** because that suite requires split 6:2 geometry; split SORT passes
in both engines and atomic settings.

### Maintainer merit request

Performance benchmarks and full `tests/gate.sh iteration`: **NOT RUN** here,
reserved to the maintainer. No throughput or latency improvement is claimed.

Use the gate's own ABBA instrument, matched offered load, on the quiet box.
Use the serverfix merit request's established generic selection from
`docs/lbplanner/generic-cells.txt`. Run those exact 14 cells in
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

### Frozen arms and serverless proof

| Arm | Local binary | SHA-256 |
|---|---|---|
| PRE | `build/latencyfix/pre/tomokv` | `5e708c7aa744e251f1c1005a06f03f1815c08c97cd965c1a95ad650844e4ea68` |
| POST | `build/latencyfix/post/tomokv` | `257d6ee619d33eeaffbb6fa55cd30b9880a37fc873f01d467c9469519dbf36d0` |
| PAD-A | `build/tomokv-latencyfix-pad-a` | `68cc2a8996d2924b692b490bbdb0bf2ecd10259816b04f6f6bcc440b668c764a` |

The source for PRE is an archive of the exact baseline commit. PAD-A adds
115,322 bytes of unreachable padding; POST/PAD-A .text starts at 0x1f8b0
and is 8,394,609 bytes. See `docs/latencyfix/arms.json` and `pad-a.json`.

The fixture calls the normal database runtime’s production-object
`exec_batch_prefetched` entry and returns, with no sockets or workers. Counts below are total user instructions
for a batch, the median of nine samples after four warmups; raw samples are
retained in `docs/latencyfix/counts-{pre,post}.jsonl`. All 24 comparisons have
no instruction-count increase (some decrease because of preserved/pinned inlining).
This establishes a command-scope count result, not a throughput result.

| Mode | Batch | slowlog µs | GET PRE → POST | SET PRE → POST | INCR PRE → POST |
|---|---:|---:|---:|---:|---:|
| 2s | 1 | -1 | 1718 → 1702 | 2301 → 2285 | 2433 → 2417 |
| 1s | 1 | -1 | 1173 → 1163 | 1756 → 1746 | 1888 → 1878 |
| 2s | 32 | -1 | 23790 → 23278 | 41764 → 41252 | 45988 → 45476 |
| 1s | 32 | -1 | 23834 → 23514 | 41808 → 41488 | 46032 → 45712 |
| 2s | 1 | 10000 | 2249 → 2233 | 2830 → 2814 | 2962 → 2946 |
| 1s | 1 | 10000 | 1720 → 1687 | 2301 → 2269 | 2433 → 2401 |
| 2s | 32 | 10000 | 23992 → 23480 | 41966 → 41454 | 46190 → 45678 |
| 1s | 32 | 10000 | 24036 → 23752 | 42010 → 41726 | 46234 → 45950 |

The actual GET/SET/MGET/MSET entry points and helpers pass **74/74** object
body comparisons using the existing CCFIX relocation normalizer, preserving
opcodes, internal branches and target identities. `docs/latencyfix/command-hot-identity.json`
records every body. A bounded compile-only search selected xshard budget
147327 to restore a GAS branch-encoding difference; no timing selected it.

The separate unchanged strict linked-binary normalizer reports **68/80** equal,
including all **10/10 GET/SET** bodies. The remaining 12 scatter bodies retain
instruction positions, widths and sizes but differ in TLS displacements and
relocated read-only data labels. Full diffs and classifications are retained in
`docs/latencyfix/linked-hot-identity.json`; strict linked MGET/MSET identity is
**not** claimed. TLS `.tdata` grows 224 → 384 bytes and `.tbss` 512 → 520 bytes.
`docs/latencyfix/section-layouts.json` also shows that PAD-A retains PRE's TLS
layout, so this PAD does not isolate the TLS-layout effect.

All 22 inspected namespace/type sizes match PRE. Every existing field offset
remains unchanged except the named Config tail reserve, which now contains the
percentile vector. The eight required layout locks remain intact. Full field
receipts are in `docs/latencyfix/layouts.json`.

All **42 job_production_units targets**, `make all`, both mdbqsbr live control
servers and the blockfix command-scope witness built. All **46 make -q
freshness queries returned zero**, including the supplemental witness hash
prerequisite and the two concrete mdbqsbr server targets. A separate query also
confirms both INFO native witnesses are fresh; both latencyfix native witnesses
also pass their freshness queries. See `docs/latencyfix/freshness.json`.
