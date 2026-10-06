ST2 / storesize2 — routing finished; body-identity acceptance remains open

**WIP, not ready to merge.** Published monitoring now passes the full serverless
positive suite in both database images. The nine original ordinary db0 body
differences are explained below, but not eliminated. The merged tree has two
additional lane-induced db0 hot-body differences and the wider audit still
finds SCAN/RANDOMKEY changes. Requirement (2) is not satisfied. PAD-A is built;
it does not waive that requirement. No new performance result is claimed.

Worktree `/home/user/Projects/cx-storesize`, branch `cx-storesize`. Before editing,
merged `origin/cpp` at `649116c91` in `2c0c62e47`. This includes the intervening
R7/reorderscan and EXECABORT work. `7e715b478` implements multi-DB publication;
`168340a48` updates the existing multi-DB unit driver to follow the new routes.
All executable checks and builds used CPUs 112–127. No server, benchmark,
load generator, gate, or push was run. The historical
[storesize report](MEASURE-REQUEST-storesize.md) describes the previous arms;
the previously unapplied accounting proposal is now implemented in this tree.

| Acceptance item | Current result |
| --- | --- |
| Multi-DB monitor routing, counts, expiry counts, SELECT/SWAPDB/MOVE/FLUSHDB | PASS in serverless fixtures |
| Original db0 witnesses, split/fused, read-local off/on | PASS |
| Nine original ordinary bodies explained | Complete, table below and compiler evidence |
| All incidental ordinary-body changes restored | **FAIL / unfinished** |
| PAD-A when identity is not achieved | Built, exact two-byte routing control |
| Exactly one gate row, both images, equality and visited bound | Present; +1 quick / +1 full; EXPECT untouched by lane |
| Rebuilt frozen PRE, rebuilt POST, SHA-256 receipts | Complete |

The frozen production arms are:

| Arm | File | SHA-256 |
| --- | --- | --- |
| PRE, unchanged original source | `build/storesize2/PRE` | `47b0c843d59a275a7aaa515c733d3fdcee3db8bf9a5525684ac2f7209394e9bc` |
| POST, both-image published monitoring | `build/storesize2/POST` | `f5195d4ac6e6f70f36907d70a809b1cdee17115973ea26f98e69b92e27a5f614` |
| PAD-A, census monitoring with POST layout | `build/storesize2/PAD-A` | `1858a825dfd3a17e23fd37598b4e28531de811c4a5883b9b2d42a021af2f7313` |

[SHA256SUMS](docs/storesize2/SHA256SUMS) is the machine-readable receipt.
PRE was fully recompiled from `build/storesize-pre/source`, into
`build/storesize2/pre-rebuild`, using the original Makefile and a
`-fdebug-prefix-map` to reproduce the original DWARF paths. The rebuilt binary
matches the required original SHA exactly; this is not merely a relink of
old objects. The command and result are in
[pre-rebuild.log](docs/storesize2/pre-rebuild.log); the full build transcript is
`build/storesize2/pre-full-rebuild.log`. POST's build log is
`build/storesize2/final-build.log`. Production binaries contain no visited-object
instrumentation.

PAD is **kind A: behaviour twin**: PRE monitoring census routes, POST text
size/layout. It changes only the return immediate of each image's
`storesize_published_route()` from one to zero. Exactly two bytes differ;
section headers, symbol tables, text size, and addresses are identical to POST.
It retains POST's producer accounting and TTL sampler, so it controls routing
and placement, not the cost of those producer additions. The instrumented
unit's equivalent twin passes all legacy cases and fails the positive routing
assertion. See [pad-final.json](docs/storesize2/pad-final.json).
ELF `.text`: PRE 7,781,132 bytes; POST/PAD-A 7,790,220 bytes. No kind-B arm is
supplied. The PRE/POST text delta also contains the required mainline merge.

“Census” below means an all-shard owner scatter and physical-object walk.
“Published” means atomic loads without an owner scatter or key walk.

| Command / INFO section | Frozen PRE, either image | Prior committed POST db0 / multi | Current POST db0 / multi |
| --- | --- | --- | --- |
| Plain `DBSIZE` | `DbsizeExact` census | Published / census | Published selected-DB sum / published selected-DB sum |
| `DBSIZE NOW`, case insensitive | Exact census | Exact census / exact census | Exact census / exact census |
| Invalid DBSIZE option | Local error | Same / same | Same / same |
| Bare `INFO`, `INFO DEFAULT` | `DatabaseInfo` census | Published / census | Published / published |
| `INFO KEYSPACE`, any section list containing KEYSPACE | `DatabaseInfo` census | Published / census | Published / published |
| `INFO ALL`, `INFO EVERYTHING` | `DatabaseInfo` census | Published / census | Published / published |
| `INFO SERVER` | Local | Local / local | Local / local |
| `INFO CLIENTS` | Local | Local / local | Local / local |
| `INFO MEMORY` | Local | Local / local | Local / local |
| `INFO PERSISTENCE` | Local | Local / local | Local / local |
| `INFO STATS` | Local | Local / local | Local / local |
| `INFO COMMANDSTATS` | Local | Local / local | Local / local |
| `INFO FLIPCTL` | Local | Local / local | Local / local |
| `INFO WRITEBACK` | Local | Local / local | Local / local |
| `INFO LB` | Local | Local / local | Local / local |
| Unknown INFO section alone | Local, no matching section | Same / same | Same / same |

No implemented INFO section now needs owner execution merely to report
keyspace. SERVER uses configuration/topology/clocks; CLIENTS existing connection
counters; MEMORY published sizes/bytes and existing gauges; PERSISTENCE manager
reports; STATS existing shard/thread/network gauges; COMMANDSTATS existing
command counters; FLIPCTL/WRITEBACK reports; LB signal snapshots. Their existing
sampling and synchronization are unchanged.

Each multi-DB store now owns 256 physical-namespace rows. Plain DBSIZE reads
the operation's already-stamped `physical_db`; INFO acquires one immutable
`DatabaseMap::Read` and translates each logical dbN to its physical row. SELECT
selects a different row without changing counts. SWAPDB changes the mapping
without moving or recounting keys. MOVE debits the source and credits the
destination, including its TTL; FLUSHDB clears only its physical namespace;
FLUSHALL clears all rows. Insert, replacement, erase, TTL transitions, snapshot
clear, and atomic physical exchange maintain owner-private counts. No observer
reads these producer rows. The state belongs to FlatStore and follows its Shard
through ownership migration; it does not name a per-thread allocation.

Keys and expires are packed into one atomic 64-bit word per physical database,
so the pair comes from the same publication. Dirty rows publish at the existing
size batch boundary, with unchanged stores suppressed. Owner rows and the
observer-visible rows start on separate cache lines. The single-database image
keeps its existing aggregate publication and bounded TTL sampler; multi-only
INFO code is explicitly compiled out of that image.

The freshness bound is **one owner batch publication**, not a wall-clock bound.
An observer before that boundary may see the preceding batch. Shards are loaded
independently; INFO and plain DBSIZE are not a global atomic/MVCC snapshot.
Published counters describe physical resident objects, including during pending
transaction transitions. `DBSIZE NOW` retains the existing exact owner census
and its existing logical atomic visibility. The fixtures require plain == NOW
after quiescence/publication, and explicitly witness stale plain versus updated
NOW before publication. Neither route collects elapsed-but-resident keys merely
to count them.

In db0, the existing candidate's sampler visits at most 16 expiry-index slots
at publication, on its own cursor; an empty sample retains the previous mean
deadline. In multi-DB, owner-private expiry counts and a 128-bit sum of deadlines
maintain the mean without a census. Publication stores that mean beside the
packed counts at the same boundary. The separate mean atomic is an estimate,
not a coherent snapshot with the packed word. INFO ages it as
`max(mean_deadline - now, 0)` and combines shards weighted by expiring count.
This is not the exact mean of individually clamped remaining TTLs. No monitoring
command invokes a sampler or object walk. Cold producer work and the new
multi-DB mutation-accounting cost still need measurement.

The visible compatibility contract remains selected-logical-database DBSIZE,
nonempty `dbN:keys=K,expires=E,avg_ttl=T` lines, and nonnegative millisecond
TTL estimates. `DBSIZE NOW` remains a TomoKV extension. The pre-existing omission
of Redis's `subexpiry` INFO field remains; full Redis INFO field parity is not
claimed. No reference server was run. The compatibility references and exact
versions are preserved in the previous report.

The census instrumentation charges full shard capacity as visited slots and
increments the object counter inside `multidb_size()` / `multidb_stats()`'s
actual callbacks. It exists only in serverless unit objects. Each case uses
16 shards and an eight-thread 6 IO + 2 EX split configuration, also checking
fused configuration. It starts no workers, socket listener, or io_uring queue.

| Resident keys | Capacity | PRE plain DBSIZE / bare INFO / INFO KEYSPACE: slots; objects | POST db0: slots; objects | POST multi: slots; objects |
| ---: | ---: | --- | --- | --- |
| 128 | 16,384 | 16,384; 128 | 0; 0 | 0; 0 |
| 4,096 | 16,384 | 16,384; 4,096 | 0; 0 | 0; 0 |
| 16,384 | 32,768 | 32,768; 16,384 | 0; 0 | 0; 0 |

Every observation repeats in split/fused × read-local off/on, both images.
DBSIZE NOW retains the PRE visits; INFO SERVER visits zero in every arm.
Plain DBSIZE instead loads one counter per shard. Multi-DB INFO costs
O(shards × configured databases), bounded by the existing 256-database limit
and independent of resident-key count. These are work counts, not rates.

| Serverless check | Result / receipt |
| --- | --- |
| Frozen PRE with instrumented census | 8 cases / 120 observations; [pre-checks.log](docs/storesize2/pre-checks.log) |
| Current POST positive suite | 8 cases / 120 observations; [controls-final.log](docs/storesize2/controls-final.log) |
| PAD legacy suite and rejection as POST | 8 legacy cases; rejection exits 1 at `FAIL storesize: monitor route`; same receipt |
| Existing broader multi-DB unit | PASS; [multidb-unit-final.log](docs/storesize2/multidb-unit-final.log) |

The positive suite covers distinct per-DB populations, SELECT, PX/PEXPIRE,
PERSIST, replacement removing expiry, active expiry, SWAPDB both ways, volatile
MOVE, scoped FLUSHDB, FLUSHALL, empty-row omission and TTL bounds. The broader
multi-DB unit also covers owner phases, WATCH, atomic operations, native
snapshots and AOF namespace/map replay. Its old helper unconditionally invoked
scatter for monitoring; it now follows ConfigRoute and explicitly performs
publication in the serverless driver. Existing reply/count assertions remain.
This is a driver correction, not a fixture or expected-result change. These
checks do not substitute for live gate/transport or concurrent-reader tests.

The body audit uses `tools/lbstall_artifacts.py` unchanged in this turn: it
normalizes relocation encoding while retaining resolved target identities,
addends, strings and constants. A call to a different helper remains a
difference. A separate all-command/publication audit catches bodies outside
the 741 selected hot copies. Missing bodies fail identity. Counts include
emitted weak/COMDAT copies, not just the linker's selected copy.

| Baseline → POST | Image | Hot copies | Raw equal | Equal after resolved relocations | Handler/publication equal |
| --- | --- | ---: | ---: | ---: | ---: |
| Frozen PRE | db0 | 741 | 707 | 723 | 609 / 622 |
| Merged mainline `649116c91` | db0 | 741 | 714 | 730 | 609 / 622 |
| Frozen PRE | multi | 741 | 617 | 626 | 506 / 623 |
| Merged mainline `649116c91` | multi | 741 | 619 | 626 | 506 / 623 |

All final logs and full symbol-by-symbol JSON tables are under
[docs/storesize2](docs/storesize2), named
`{db0,multi}-{hot,handlers}-vs-{pre,mainline}-final.{log,json}`.
The merged-mainline comparison is an additional control, not a replacement
for the requested frozen PRE. Seven db0 differences against frozen PRE are
inherited mainline R7 changes and disappear against merged mainline. The other
eleven selected differences remain lane-induced.

The **nine original bodies** are all in `tomo_db0`. Each row below is one emitted
body; the full mangled/demangled names remain in the JSON. “High” and “low” mean
the two `inspect` calls in `Rob::read_local_owner_conflicts_before`, at
`src/net/rob.h:496` and `:497`. GCC's actual inline reports prove the call-site
switches; see [nine-inline-evidence.txt](docs/storesize2/nine-inline-evidence.txt).

| # | Object and body | PRE → POST bytes | Specific cause; disposition |
| ---: | --- | --- | --- |
| 1 | `core/rl2s.o`, `parse_and_dispatch<true,32,false,true>`, generic callback #1 | 772 → 852 | PRE inlines high, POST low; incidental compiler choice, unresolved |
| 2 | Same specialization, generic callback #4 | 772 → 852 | Alias of #1 in each object; same high-to-low switch, unresolved |
| 3 | `core/rl2s.o`, `parse_and_dispatch<false,0,true,true>`, generic callback #1 | 772 → 852 | PRE inlines high, POST low; incidental compiler choice, unresolved |
| 4 | Same specialization, generic callback #4 | 772 → 852 | Alias of #3 in each object; same high-to-low switch, unresolved |
| 5 | `core/rl2s.o`, `parse_and_dispatch<true,32,false,false>`, generic callback #1 | 852 → 772 | PRE inlines low, POST high; incidental compiler choice, unresolved |
| 6 | Same specialization, generic callback #4 | 852 → 772 | Alias of #5 in each object; same low-to-high switch, unresolved |
| 7 | `core/rl2s.o`, `parse_and_dispatch<false,32,false,false>`, generic callback #1 | 852 → 772 | PRE inlines low, POST high; incidental compiler choice, unresolved |
| 8 | Same specialization, generic callback #4 | 852 → 772 | Alias of #7 in each object; same low-to-high switch, unresolved |
| 9 | `main.o`, `WbEngine::serve_impl<false,true,true,false,false,false>`, lambda #1 | 824 → 537 | PRE inlines `Client::append_static_segment` including its allocation/copy fallback; POST calls it out of line, unresolved |

These are not justified monitoring changes. They are compiler graph/budget
effects of the cold state/sampler addition. Matching sets of inlined callees
alone missed rows 1–8: the *call site* chosen for the same callee changed.
Rows 5–8 also have unchanged weak copies in earlier-linked genthread.o, but
that does not make the requested emitted-body identity pass.

The two additional lane-induced selected db0 changes after merging are
`core/reorder.o: FlatStore::erase_in_read_local` (1257 → 1208), which newly
outlines `FlatStore::deadline`, and ordinary
`parse_and_dispatch<false,32,false,false>` (18363 → 18411), which inlines one
additional `Rob::extend_current_read_local_owner` call. See
[reorder-inline-evidence.txt](docs/storesize2/reorder-inline-evidence.txt).
The wider audit finds SCAN's `scan_home<cmd_scan::lambda>` (1567 → 1535), with
a newly outlined `KvObj::key()` before `atomic_key_pending`, and RANDOMKEY
(653 → 663), with a newly outlined `Op::Sink::advance` clone. Both are
incidental and unresolved. Expected differences are INFO and its cold clone,
the monitor-routing helper, and the eight emitted `Shard::publish_size` copies.

Multi-DB intentionally adds owner-private accounting to store mutation helpers,
including insert/erase, TTL updates and physical atomic replacement. Those
changes also affect callers via GCC inlining. The multi audit reports all
115 selected differences and 117 handler/publication differences, including
unwanted execute/parser/writeback/TLS-loop changes; it does not label them all
as expected. All three emitted GET handler copies and both SET handler copies
remain identical in each image's handler audit. This audit contains no standalone
MGET/MSET handler bodies, so it cannot establish their complete scatter paths.
Unchanged GET/SET handlers also do not prove their entire called paths identical.
No zero-regression claim is made for the new multi-DB producer work.

Compiler-boundary trials were confined to ignored build copies. They included
out-of-line/pure sampler splits, noinline/noipa/cold construction/destruction,
sampler/index-helper boundaries and compiler optimization attributes, and
small per-unit inline-budget sweeps. Some restore individual bodies while
changing others. None achieved the required complete identity, so none of
those experimental attributes or budgets is in POST. The trial receipts and
source copies remain in `build/storesize2`; they are not measurement arms.

All locked layouts remain: Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. Both fixture images
assert them. The existing db0 sampler sidecar remains 16 bytes; the multi
sidecar is 12,416 bytes per shard before allocator rounding. Its pointer uses
bytes 4–11 of the existing read/owner gap and is initialized at construction.
No reader retries, seqlocks, in-place read-local overwrite, or ownership
handoff mechanism was introduced.

Exactly **one** ST2 gate row remains, now named
`storesize published monitoring`, at `tests/gate.sh:1587`, inside core_units.
It runs `tests/storesize_checks.py check-all build/storesize-unit`, including
both namespaces, equality, visited bounds and the rejected control. Collection
is at line 3130, before the quick-tier exit at line 3279: **+1 quick / +1 full**.
The merged baseline constants remain 497 / 514. The maintainer should change
them to **498 / 515** for this lane's one row. The lane did not edit either
EXPECT constant or any fixture. The gate was not run.

Reproduction, all serverless:

```sh
taskset -c 112-127 make -j8 build/tomokv build/storesize-unit build/multidb-unit
taskset -c 112-127 ./build/storesize-pre/unit --legacy
taskset -c 112-127 python3 tests/storesize_checks.py check-all build/storesize-unit
taskset -c 112-127 ./build/multidb-unit
taskset -c 112-127 sha256sum -c docs/storesize2/SHA256SUMS
taskset -c 112-127 python3 tools/lbstall_artifacts.py compare build/storesize-pre/db0/src build/db0/src docs/storesize2/db0-hot-vs-pre-final.json
taskset -c 112-127 python3 tools/storesize_artifacts.py handlers build/storesize-pre/db0/src build/db0/src docs/storesize2/db0-handlers-vs-pre-final.json
```

The hot compare currently exits nonzero as it should. A future successful
restoration must rerun both-image hot and wider-handler audits and regenerate
the frozen POST/control hashes. Do not substitute copied PRE machine bodies
or weaken relocation normalization to obtain a passing audit.

Mainline's supplied 2026-10-06 01:55 addendum reports the *previous* db0 POST
`d79fa16a49fb` versus headline `b38916d88` within band on all 14 cells, quiet
cells within 1.2%. That result supports the old db0 routing change; it does
not measure this merged POST or the new multi-DB accounting. It does not
resolve the explicit body-identity requirement.

For the maintainer's measurement queue, use PRE/POST/PAD-A with the gate's own
instrument and a contemporaneous same-binary null. The 14 cells are exactly
`tests/wbland_merit_cells.txt`:
`h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`.
Use the instrument's ABBA order, cell geometry, modes, pipeline depths,
connections, offered rates, and shard/ratio derivation. The headline geometry
is 32 physical server cores 0–31, loaders 32–111, 512 connections, 2M keys,
64-byte values except v1g, uring, atomic=1, overlap=1, reorder=0, default
balancers and disabled save. Repeat a matched namespace exercise with
`databases > 1` and nonzero selected databases to expose producer accounting
cost; do not infer its cost from db0.

For INFO interference, keep the prior h05 GET p32 shape, 1s/read-local=0,
**40M resident keys**, 64-byte values and 512 connections. Recalibrate for that
dataset, then use the same matched offered load for PRE/no poller, PRE/1 Hz
bare INFO, POST/no poller, POST/1 Hz bare INFO, and PAD-A's two corresponding
arms. Repeat with more than one populated database for the new route. Use
`tools/storesize_poller.py` only on mainline; reject missed periods, bad replies
or incomplete poll counts. Unrelated harness INFO polls invalidate no-poller
arms. Record rate, p50/p99/p99.9, cycles/op, instructions/op, IPC and INFO
latency. Compare each binary's poll penalty against its own no-poller arm;
PAD-A should retain the census penalty. Rate/tails and cycles/op at matched
load decide, with no ordinary-cell regression beyond the contemporaneous
null. Instruction counts alone do not decide. Append actual PRE/POST tables
to MEASURE-RESULT; measurement acceptance and body-identity acceptance remain
separate, and both are still required before landing.
