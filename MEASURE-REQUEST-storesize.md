ST2 — storesize resume receipts and measurement handoff

**Resume verification is complete; full ST2 acceptance is not met.** Committed
POST accelerates `databases 1`. With `databases > 1` it retains the legacy
census. The separate multi-DB proposal implements published per-database
counts, but requires ordinary multi-DB mutation accounting and therefore an
exception to the requested hot-path byte identity. That exception has not
been received; the proposal remains unapplied. The committed default image
also fails strict byte identity: nine selected hot bodies differ, and a wider
handler audit finds changes to SCAN's helper and RANDOMKEY. These are reported
failures, not a claim of zero regression or completed multi-DB ST2.

Worktree/branch: `/home/user/Projects/cx-storesize`, `cx-storesize`. The already
merged origin/cpp baseline is `b38916d8884e3d620a9cda85e0a2fec4363173bf`, newer
than the requested `f769efcdd`. This resume preserved the four existing commits
through `411d3276a`; `e9c19e00e` commits the remaining witnesses and audit
receipts. Round-3 ST2 at `/home/user/Projects/round3-read/store.md` and the
routing/scatter/census files it names were re-read. No server, load generator,
benchmark, or gate was run. Builds and executable checks used CPUs 112–127.

The frozen production arms are in [SHA256SUMS](docs/storesize/SHA256SUMS):

| Arm | File | SHA-256 |
| --- | --- | --- |
| PRE: origin/cpp | `build/storesize-pre/tomokv` | `47b0c843d59a275a7aaa515c733d3fdcee3db8bf9a5525684ac2f7209394e9bc` |
| POST: committed db0 change | `build/tomokv` | `d79fa16a49fb4855de698fa5229d799b2ec15722ff1ebbb5e5cfff7386ce1aa7` |
| PAD-A: PRE census routes, POST layout | `build/storesize-pad` | `362c21518a7b630f608e5e3ac5a22d789d7a93785828f3151cfff819e187e9de` |
| PROPOSAL: unapplied multi-DB accounting | `build/storesize-proposal/source/build/tomokv` | `b205f77fa01900a47934df7cd16c01b6c0ac55bf4e5585d4a6ef7dd518e39f7a` |

PRE was built in-tree before editing sources with
`taskset -c 112-127 make -j8 BUILD_ROOT=build/storesize-pre`; its log and source
archive are `build/storesize-pre/build.log` and `build/storesize-pre/source`.
Do not rebuild PRE against candidate sources. The resumed
`taskset -c 112-127 make -j8 build/tomokv build/storesize-unit` found both
outputs up to date (`build/storesize-resume-build.log`). Hashes were rechecked
after verification. Production arms contain no walk instrumentation.

PAD is **kind A: behaviour twin**. It changes the return immediate in the two
`storesize_published_route()` functions from 1 to 0: exactly two bytes, with
identical section sizes, symbols, and addresses. It restores PRE's monitoring
census routes, while retaining POST's cold TTL sampler. It isolates routing
and placement, not the sampler's producer cost. See [pad.json](docs/storesize/pad.json).
ELF `.text` sizes are PRE 7,781,132, POST/PAD 7,784,748, and PROPOSAL 7,789,020
bytes. No kind-B control is supplied. PAD passes the legacy behaviour checks
and fails the positive monitor-route assertion as required.

The routing table describes actual work. “Census” is an all-shard owner
scatter; “published” does not scatter. The PROPOSAL column applies only to
the separate patched build.

| Command/section | PRE, either image | POST, databases 1 | POST, databases > 1 | PROPOSAL, either image |
| --- | --- | --- | --- | --- |
| Plain `DBSIZE` | Census: `DbsizeExact` | Published shard sum | Census: `DbsizeExact` | Published selected-DB sum |
| `DBSIZE NOW` (case insensitive) | Census: `DbsizeExact` | Same | Same | Same |
| Invalid DBSIZE option | Local error | Same | Same | Same |
| Bare `INFO`, `INFO DEFAULT` | Census: `DatabaseInfo` | Published keyspace | Census: `DatabaseInfo` | Published keyspace |
| `INFO KEYSPACE`, any list including KEYSPACE | Census: `DatabaseInfo` | Published keyspace | Census: `DatabaseInfo` | Published keyspace |
| `INFO ALL`, `INFO EVERYTHING` | Census: `DatabaseInfo` | Published keyspace | Census: `DatabaseInfo` | Published keyspace |
| `INFO SERVER` | Local | Local | Local | Local |
| `INFO CLIENTS` | Local | Local | Local | Local |
| `INFO MEMORY` | Local | Local | Local | Local |
| `INFO PERSISTENCE` | Local | Local | Local | Local |
| `INFO STATS` | Local | Local | Local | Local |
| `INFO COMMANDSTATS` | Local | Local | Local | Local |
| `INFO FLIPCTL` | Local | Local | Local | Local |
| `INFO WRITEBACK` | Local | Local | Local | Local |
| `INFO LB` | Local | Local | Local | Local |
| Unknown INFO section alone | Local; no matching section | Same | Same | Same |

**No implemented INFO section intrinsically needs owner-thread work once
KEYSPACE uses published counters.** SERVER reads configuration/topology/clocks;
CLIENTS reads existing connection counters; MEMORY reads published sizes/bytes
and memory gauges; PERSISTENCE uses manager reports; STATS uses existing
shard/thread/network gauges; COMMANDSTATS uses command counters; FLIPCTL and
WRITEBACK use their reports; LB uses signal snapshots. Their existing sampling
and synchronization are unchanged. Committed multi-DB KEYSPACE still needs
owners because its legacy `multidb_stats()` walks the stores.

Published size/expiry freshness is **one owner batch boundary**, not a fixed
wall-clock deadline. A read before publication may see the preceding batch.
Shards are observed independently; the report is not a global MVCC snapshot.
The fixture writes without publication, observes old plain DBSIZE and new
DBSIZE NOW, publishes, then requires equality with the shard sum. After
quiescence it requires plain == NOW == published sum. Neither mode reaps
elapsed-but-resident keys merely to count them. See
[CONFIGURATION.md](docs/CONFIGURATION.md) and [INFO.md](docs/INFO.md).

The default image already had aggregate `published_size()` and
`published_expires()`. No per-operation publication write was added. The new
TTL sampler visits at most 16 expiry-index slots at publication, using a cursor
separate from active expiry, and publishes a mean deadline. INFO reads the
sample and ages it using wall time. An empty sample retains the prior estimate;
no sample or no expiring keys yields zero. It is not an exact all-key average.
The sampler may inspect objects at the boundary; **the monitoring command
itself never runs it or walks the keyspace**. Its producer cost is bounded by
the sampling budget and remains unmeasured.

Redis compatibility is selected-logical-database DBSIZE and nonempty
`dbN:keys=K,expires=E,avg_ttl=T` lines, with a nonnegative millisecond TTL
estimate. Redis 7.4 [DBSIZE](https://github.com/redis/redis/blob/7.4.0/src/db.c#L1236-L1238)
counts the selected database without expiry collection. Its
[INFO keyspace output](https://github.com/redis/redis/blob/7.4.0/src/server.c#L5663-L5677)
also includes `subexpiry`; this lane keeps TomoKV's pre-existing omission and
does not claim complete field parity. `DBSIZE NOW` is a TomoKV extension.
No Redis server was started for these checks.

Committed multi-DB uses operation namespace stamping and exact walks, so
selected-database correctness is retained; **it has no published per-database
counters**. The separate [proposal patch](docs/storesize/multidb-accounting.patch)
indexes 256 counter rows per shard by physical namespace. DBSIZE reads
`op.physical_db`; INFO takes one immutable `DatabaseMap::Read` and maps each
logical dbN to its physical row. SWAPDB relabels rows without moving keys;
MOVE accounts for source and destination; FLUSHDB changes only that namespace;
FLUSHALL clears every row. Sidecar state belongs to FlatStore and follows its
Shard through owner migration, rather than naming a per-thread structure.

The proposal adds owner-private key/expiry/deadline accounting to insert,
replace, erase, TTL mutation, clear, and atomic physical exchange. This changes
ordinary multi-DB write paths. Observer-visible packed key/expiry counts and
mean deadlines are stored only at the size-publication boundary; readers take
atomic loads without locks or retries. INFO costs O(shards × configured DBs),
with the existing 256-DB limit, independent of key count. The patch applies
cleanly (`git apply --check docs/storesize/multidb-accounting.patch`); SHA-256
`f26d677230e4a6008cd2e0afcd015476e490e2002fd44acc0b6e433b3217147e`.
It is built and reviewable, but is not applied to production sources.

The cost fixture increments an object counter inside each callback of the two
census walks, `multidb_size()` and `multidb_stats()`. It charges a walk's full
shard capacity as visited slots. Instrumentation is emitted under `build/`
and linked into serverless units only. Each fixture has 16 shards and an
eight-thread 6 IO + 2 EX split configuration, and also checks fused configuration.
It starts no worker, listener, or io_uring queue. Read-local cases arm the
production owner storage path; they do not prove concurrent-reader or live
transport behaviour.

| Keys | Capacity | PRE plain DBSIZE / bare INFO / INFO KEYSPACE: slots; objects | POST db0: slots; objects | PROPOSAL both images: slots; objects |
| ---: | ---: | --- | --- | --- |
| 128 | 16,384 | 16,384; 128 | 0; 0 | 0; 0 |
| 4,096 | 16,384 | 16,384; 4,096 | 0; 0 | 0; 0 |
| 16,384 | 32,768 | 32,768; 16,384 | 0; 0 | 0; 0 |

All observations repeat in split/fused × read-local off/on. DBSIZE NOW keeps
the PRE slot/object counts in every arm; INFO SERVER visits zero census slots
and objects everywhere. Committed POST multi-DB retains PRE's counts. Plain
db0 DBSIZE instead loads 16 shard counters; INFO's keyspace work uses a fixed
number of shard passes. These are work counts, not timing or performance
measurements.

| Resumed check | Result / receipt |
| --- | --- |
| Frozen PRE objects, instrumented census, current fixture | 8 mode/image/read-local cases; 120 walk observations; [pre-checks.log](docs/storesize/pre-checks.log) |
| Committed POST db0 | 4 cases; 60 walk observations; [db0-checks.log](docs/storesize/db0-checks.log) |
| Gate row body: positive db0, PAD legacy, reject PAD as POST | Pass; [controls.log](docs/storesize/controls.log) |
| Committed POST full multi-DB positive suite | **Fails** at multi-DB monitor routing, exit 1; [multi-blocker.log](docs/storesize/multi-blocker.log) |
| Separate PROPOSAL both images | 8 cases; 120 walk observations; [proposal-checks.log](docs/storesize/proposal-checks.log) |
| PROPOSAL positive + PAD legacy + rejected positive control | Pass; [proposal-controls.log](docs/storesize/proposal-controls.log) |
| Shell syntax, Python compilation, patch applicability, whitespace | Pass |

The fixture requires exact expected counts and plain == NOW == published sum
after publication. It exercises distinct per-DB populations, SELECT,
PX/PEXPIRE, PERSIST, replacement removing expiry, active expiry, SWAPDB both
ways, MOVE of a volatile key, scoped FLUSHDB, FLUSHALL, omitted empty rows,
and TTL units/range. Routing tests cover every implemented section and the
aliases. The restored-route control must exit 1 with
`FAIL storesize: monitor route`; it cannot skip the assertion. Multi-DB
positive coverage is claimed only for the separate proposal, not committed
POST. Unit source is identical in the committed and proposal fixtures.

Reproduction commands are serverless:

```sh
taskset -c 112-127 ./build/storesize-pre/unit --legacy
taskset -c 112-127 ./build/storesize-unit --db0-only
taskset -c 112-127 python3 tests/storesize_checks.py check build/storesize-unit
taskset -c 112-127 ./build/storesize-proposal/source/build/storesize-unit
taskset -c 112-127 python3 tests/storesize_checks.py check-all build/storesize-proposal/source/build/storesize-unit
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare build/storesize-pre/db0/src build/db0/src docs/storesize/db0-hot.json
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare build/storesize-pre/src build/src docs/storesize/multi-hot.json
taskset -c 112-127 python3 tools/storesize_artifacts.py handlers build/storesize-pre/db0/src build/db0/src docs/storesize/db0-handlers.json
taskset -c 112-127 python3 tools/storesize_artifacts.py handlers build/storesize-pre/src build/src docs/storesize/multi-handlers.json
```

The compare tool returns nonzero when bodies differ. The resumed wider audit
needed support for `R_X86_64_TPOFF32` (23), a four-byte TLS relocation in some
handlers. The fix retains its symbol/addend in the comparison and does not
mask changed callees.

| PRE versus arm/image | Hot bodies | Raw equal | Equal with resolved relocation targets | Receipts |
| --- | ---: | ---: | ---: | --- |
| POST db0 | 741 | 716 | 732 | [log](docs/storesize/db0-hot.log), [JSON](docs/storesize/db0-hot.json) |
| POST multi-DB | 741 | 741 | 741 | [log](docs/storesize/multi-hot.log), [JSON](docs/storesize/multi-hot.json) |
| PROPOSAL db0 | 741 | 716 | 732 | [log](docs/storesize/proposal-db0-hot.log) |
| PROPOSAL multi-DB | 741 | 623 | 630 | [log](docs/storesize/proposal-multi-hot.log), [JSON](docs/storesize/proposal-multi-hot.json) |

All nine changed default-image hot bodies are in `tomo_db0`:

| Object | Body | PRE → POST bytes |
| --- | --- | --- |
| `core/rl2s.o` | `IoLoop::parse_and_dispatch<true,32,false,true>` callback wrappers #1 and #4 | 772 → 852 each |
| `core/rl2s.o` | `IoLoop::parse_and_dispatch<false,0,true,true>` callback wrappers #1 and #4 | 772 → 852 each |
| `core/rl2s.o` | `IoLoop::parse_and_dispatch<true,32,false,false>` callback wrappers #1 and #4 | 852 → 772 each |
| `core/rl2s.o` | `IoLoop::parse_and_dispatch<false,32,false,false>` callback wrappers #1 and #4 | 852 → 772 each |
| `main.o` | `WbEngine::serve_impl<false,true,true,false,false,false>` lambda #1 | 824 → 537 |

The wider handler/publication comparison is 609/622 equal in db0 and 622/623
in multi-DB. Additional db0 differences are
`FlatStore::scan_home<cmd_scan::lambda>` (1567 → 1535), `cmd_randomkey`
(653 → 663), expected `cmd_info` and its cold clone, the routing helper, and
eight emitted `Shard::publish_size()` copies (216 → 303). The multi-DB handler
difference is only `cmd_info` (same 16,215-byte size). Exact names/objects are
in [db0-handlers.log](docs/storesize/db0-handlers.log) and
[multi-handlers.log](docs/storesize/multi-handlers.log) and companion JSON.
The proposal's 111 multi-DB hot differences are fully listed in its log,
including insert/erase/find helpers and affected executor/parser bodies.
Compiler inline-budget adjustments already in the lane did not eliminate
all differences. Unchanged source spelling is not byte-identity evidence.

Layout assertions pass in both fixture images: Op 336, Client 1984,
ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144,
Config 624. The committed sampler sidecar is 16 bytes per store; its pointer
occupies bytes 4..11 of the existing read/owner gap and is written only during
construction. No locked structure grows and no key-path publication write is
added. The separate proposal adds per-DB owner and published sidecar rows;
its ordinary write cost is the unresolved exception described above.

Exactly **one gate row** was added by the existing lane commits:
`storesize db0 published monitoring` at `tests/gate.sh:1587`, inside
`job_core_units`, collected at line 3108. The quick-tier exit starts at line
3257, so the row is **quick +1, full +1**. Relative to this baseline the
maintainer should change EXPECT_QUICK **496 → 497** and EXPECT_FULL
**513 → 514**. Neither constant was edited. The proposal renames/widens the
same row and adds no second row. The body
`tests/storesize_checks.py check build/storesize-unit` was rerun directly;
the gate was not run.

Mainline measurements are pending. They can characterize the candidate but
cannot substitute for the disclosed implementation/audit acceptance failures.
Use the gate's instrument and a contemporaneous same-binary null. Record rate,
p50/p99/p99.9, cycles/op, instructions/op, and IPC. Rate/tails and cycles/op at
matched offered load decide; instruction totals alone do not.

The requested 14-cell null is exactly `tests/wbland_merit_cells.txt`, SHA-256
`de0e56e4696f780543c5adea21aa7d7283c12fa22110be6064370a69a2a68dc6`:
`h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`.
Run PRE/POST in the instrument's ABBA order and PRE/PAD-A for the placement
control. Preserve the cells' modes, pipeline depths, mixes, connections,
and current pin/calibration geometry. The baseline headline setup is 32
physical server cores 0–31, loader cores 32–111, 512 connections, 2M keys,
64-byte values except v1g, uring, atomic=1, overlap=1, reorder=0, default
balancers, and disabled save. Keep the instrument's shard/ratio derivation.
These cells are distinct from the correctness fixture's 16-shard geometry.

For INFO interference, use the h05 GET p32 shape (1s, read-local=0) with
**40M resident keys**, 64-byte values and 512 connections. Recalibrate for
that dataset, then keep identical populations and one matched offered rate
across all arms. The four required arms are PRE/no poller, PRE/1 Hz bare INFO,
POST/no poller, POST/1 Hz bare INFO. Repeat the poller pair with PAD-A to
isolate routing from placement. Schedule one poll each second during the
measured window; unrelated harness INFO polls invalidate a no-poller arm.
Run [storesize_poller.py](tools/storesize_poller.py) only on mainline, against
an already-running arm, on an otherwise unused load CPU:

```sh
# Maintainer only: these variables come from the instrument's measured window.
taskset -c "$POLLER_CPU" python3 tools/storesize_poller.py "$HOST" "$PORT" \
  --seconds "$SECONDS" --output "$CELL_DIR/info-polls.json"
```

The helper records INFO latency, schedule lag, reply size and completion. It
fails on a missed whole period, wrong reply, connection error, or short poll
count. Reject those cells rather than treating fewer polls as an improvement.
The lane syntax-checked the helper but never connected it to a server.
Compare each binary's poller penalty against its own no-poller arm, then
compare the PRE and POST penalties. Acceptance requires a resolved reduction
in INFO interference and no ordinary-cell regression outside the unchanged
contemporaneous null. PAD-A should retain the census penalty. Populate the
rate/cycles/IPC PRE/POST table from MEASURE-RESULT; no measured performance
win is claimed here.
