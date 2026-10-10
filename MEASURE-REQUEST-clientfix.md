## clientfix

The six requested correctness fixes are implemented on `cx-clientfix`. All 14
new regression rows fail on PRE and pass on POST. The seven oracle probes and
all 12 requested existing battery runs pass. Production targets are built and
fresh; the remaining proof status is listed below. No push, full gate, or
performance measurement has been run.

Worktree: `/home/user/Projects/cx-clientfix`. PRE source:
`5146b78ee89b64748dd46db970efa8086f653fa0`; POST production source: `e6f6d01d8`
(later commits contain test fixtures, harnesses and proof receipts).

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/clientfix/pre/tomokv` | `839187cc59a9fdfe89040ae2630bd15bd4408bce23d038b3f9d0fa23c1092a5a` |
| POST | `build/tomokv` | `6fd0478024b5d564f51a81b834b6511e3183bf00c6324077435def7fd6a14fc2` |

PRE was built before any production source edits, using
`taskset -c 112-127 make -j16 BUILD_ROOT=build/clientfix/pre all`.
All proof commands stay within CPUs 112–127: candidates 112–119, Redis 7.4.10
oracle 120, clients 121–127. Ports are 25070–25083. The focused task's PROOF
instruction authorizes these correctness boots. Lifecycle receipts include box
load and clean server exits. Sibling lanes share these CPUs; these are
correctness results, not latency or performance claims.

**Finding receipts.** Raw negative controls are in [pre](docs/clientfix/pre/),
positive controls in [post](docs/clientfix/post/), and Redis controls in
[oracle](docs/clientfix/oracle/). Each label below has a separate `(1s)` and
`(2s)` row. Both tracking cases boot atomic/read-local axes 0/0, 1/0 and 1/1 in
each mode, with 16 shards and a 6:2 split in 2s.

| Finding | PRE result | POST result | Production files | New gate labels |
|---|---|---|---|---|
| CC4.1 | 1024/1100 invalidations in all six mode/axis combinations; 76 cached misses survive | 1100/1100 in all six combinations | `src/cmd/notify.inc` | `clientfix tracking-cap (1s)` / `(2s)` |
| CC4.2 | Missing foreign invalidation in 20/20 pipelines per axis | Exact `invalidate [key]` in 20/20 per axis; no own NOLOOP push | `src/cmd/tracking.cc`, `climon.inc`, `climon.cc`; `src/core/io_loop.h`, `wb_rule.h`, generated `reorder.cc`; `src/net/wb.h` | `clientfix tracking-pipeline (1s)` / `(2s)` |
| WB4.12, WB4.13 | 240 leaked replies out of 480 trials per mode; MONITOR WAIT 11/5 lines (1s/2s), BLPOP 2/2 | 480/480 exact reply sequences per mode; one WAIT and one BLPOP MONITOR line | `src/cmd/climon.cc`, `climon.inc`, `src/core/io_loop.h`, generated `reorder.cc` | `clientfix reply-skip (1s)` / `(2s)` |
| CC4.11 | keep:one reaches zero subscribers; empty channel reaches the corrupted keep subscriber | Exact `[pmessage, keep:*, keep:one, after]`; empty channel reaches zero | `src/core/pubsub.inc` | `clientfix pattern-cleanup (1s)` / `(2s)` |
| SV4.4 | SET returns at 111.868/115.457 ms (1s/2s) | Still pending at 300.672/304.413 ms; returns at 1021.701/1025.851 ms | `src/core/server.h` | `clientfix pause-deadline (1s)` / `(2s)` |
| CD4.1 | Wrong nearest-five selection at 20/20 centres in both modes | Correct selection at 20/20 for GEOSEARCH and GEORADIUS | `src/cmd/geo.cc` | `clientfix geo-count (1s)` / `(2s)` |
| CD4.1 STORE | Wrong stored nearest-five set at 20/20 centres in both modes | Correct sets at 20/20 for GEOSEARCHSTORE and GEORADIUS STORE | `src/cmd/geo.cc` | `clientfix geo-store (1s)` / `(2s)` |

`tests/clientfix.py` accepts binary/port/cores/mode/ratio arguments and owns its
boot. The SKIP row covers PING, GET, WAIT, SCRIPT, FUNCTION, BLPOP, XREAD BLOCK
and a FLIP error, in older-GET, pipelined-SKIP and separate-write shapes, with
20 repetitions each. Redis has seven targets because FLIP is Tomo-specific.
GEO rows also check explicit DESC and ANY controls. The PAUSE row requires an
observed window and completion no earlier than the full original 1000 ms
(minus the server's 1 ms clock flooring). If scheduling obscures the window,
it rearms on fresh state at most three times and then fails. The tightened
check was rerun on both PRE/POST modes and Redis; [receipt](docs/clientfix/pause-proof.json).
No assertion is skipped or tolerance widened.

**Changes at the cause.** The 1024-event collector limit strips only keyspace
publication routes; it retains tracking records. This adds constant work per
record. The existing argv scans and changed-key linear dedup remain unchanged,
so this lane does not claim to make the entire collector O(keys) or optimize
PFMESSAG.1.

Tracking captures the CACHING choice and pending read keys at dispatch, then
enrolls completed registrations at in-order retirement. Pending foreign-write
invalidation obligations cover the execution-to-retirement interval; the
existing OOB frontier orders pushes after replies. Earlier own writes cannot
erase the younger read's completed registration. Both pending maps live in the
existing `ClimonConn` migration node and move in its ownership commit section;
no owner-local map or IoLoop field was added. Tracked connections use the cold
writeback drain so even small replies receive the retirement callback.

The armed gate records the ROB dispatch number and reply suppression choice.
Reparse restores the mark without consuming SKIP or CACHING again or feeding
MONITOR again. A still-unpublished retried frame keeps SkipNow armed even when
older operations have quiesced. The FLIP hold precedes these stateful hooks.
This closes WB4.13's repeated MONITOR and tracking-registration hooks as well as
WB4.12. The unarmed dispatch path retains its predicted-false feature test;
writeback broadens an existing predicted-false per-connection mask, and the
retire hook has a predicted-false local-tracker test.

Pattern cleanup skips self-moves. PAUSE stores the latest action mode while a
CAS maximum prevents its deadline moving earlier. GEO COUNT selects ASC when
neither explicit order nor ANY was supplied.

CC4.4 is not fixed: a successfully delivered tracking-only batch still reaches
the existing empty-publication-chain drop accounting. Over-cap tracking records
now reach that accounting instead of the collector's cap-drop path. A
tracking-only 1100-record case therefore still counts all 1100 as dropped via
the old accounting (source analysis, not a new counter measurement). Mixed
notification/tracking batch counters can differ because retained tracking-only
records increase `batch->total`; do not read these counters as invalidation loss.
CC4.12 empty-pattern framing is untouched.

A separate pre-existing risk remains in `notify_record_keyless_slow`: its 4096
keyless-record cap returns before preserving NOTIFY_TRACKING, so that path can
still discard invalidations if it fills. Existing notification allocation
failure paths can also discard them. These were found during source review,
are outside the supplied CC4.1 per-operation-batch reproduction, and are not
claimed fixed by this lane.

**Build and correctness proof.**

| Check | Status / receipt |
|---|---|
| `make -j16 all` | PASS, [build log](docs/clientfix/post-build-final.log.gz) |
| All 28 `job_production_units` targets, including netcmd | PASS build and 28/28 `make -q`; [exact commands](docs/clientfix/production-units.json) |
| `build/climon-mask-unit` | PASS build, freshness and execution; [log](docs/clientfix/climon-mask-unit.log.gz) |
| `make -j16 mdbqsbr-live-arms` | PASS, both park/no-wake proof binaries; [log](docs/clientfix/mdbqsbr-live-arms-build.log.gz) |
| New rows on PRE / POST | 14 intended FAIL / 14 PASS; [POST receipt](docs/clientfix/post-proof.json) |
| Redis 7.4.10 focused probes | 7/7 PASS |
| tracking, pubsub, climon, climon2, geo, replyoff_xshard | 12/12 PASS across 1s and 2s; [logs](docs/clientfix/batteries/) |
| Differential matrix | Split 64/64 PASS; armed-fused running. 8 suites × 4 seeds × 2 atomics × 2 geometries |
| `python3 tests/gates_test.py` | Rerun on 124–127 in progress, serializing fixtures with every test/timeout unchanged; initial run on 112–127 hit scheduler-fixture timeouts |
| `python3 tests/wbland_checks.py check clauses` | PASS, 83/83 strict outcomes; [log](docs/clientfix/wbland-clauses.log) |
| `python3 tests/gate_ledger_fixture.py` | Refuses unchanged EXPECT_FULL=528 versus 542 declared labels; no missing/extra labels |
| Eight locked layouts and IoLoop field offsets, both namespaces | PASS, [layout receipt](docs/clientfix/layouts.json) |

Differential suites are notify, pubsub, fanout, spubsub, climon, monitor,
compatintro and geo, seeds 7/19/20/23, atomic 0/1, split 6:2/16 shards and
armed-fused. Full commands are in [post_checks.py](docs/clientfix/post_checks.py).
The production build recipe extracts and asserts the exact 28 target names
from the current job before building and checks each with `make -q`.
`tests/wb_rule_completion_unit.cc` adds the tracking bit to its fake server mask.
The core_units row list is unchanged.

DQ **+14**, DF **+14**. `collect_job clientfix` is at line 3279, above the quick-tier exit at line 3434;
all seven case names expand once per mode before that exit. The comment above
EXPECT gives **511 + 14 = 525** quick and **528 + 14 = 542** full. Assignments
remain **511/528**, as explicitly required. Fixture/source both have all 542
labels, counted with duplicates: [inventory](docs/clientfix/label-inventory.json).
The actual [ledger failure](docs/clientfix/ledger-check.log) is retained.
The maintainer must change EXPECT to 525/542 before that check can pass.

**Default binary identity.** The tools use relocation-normalized object-body
comparison; this is not a claim that the linked executable is byte-identical.

| Namespace | Production objects | All bodies equal / total | Hot bodies equal / total | GET/SET/MGET/MSET selection equal / total |
|---|---:|---:|---:|---:|
| tomo | 50 | 8238 / 8407 | 525 / 601 | 5 / 5 |
| tomo_db0 | 50 | 7749 / 7917 | 523 / 603 | 5 / 5 |
| Total | 100 | 15987 / 16324 | 1048 / 1204 | 10 / 10 |

`tools/lbstall_artifacts.py compare` reports 156 changed hot entries and exits
nonzero as expected for these changes. `tools/ccfix_audit.py`'s slightly wider
hot selection is 1052/1208 identical with the same 156 changes; its strict
all-hot-identity assertion also fails, openly. Its handler selection is
1206/1211 identical: the five extra changes are GEOADD sort helpers and GEOPOS
helpers whose source is unchanged but compiler inlining/order changes in the
edited GEO translation unit. [Full audit](docs/clientfix/full/summary.json).

Every changed hot entry, with object, namespace, sizes and reason, is listed
in [changed-hot.md](docs/clientfix/changed-hot.md) and its JSON twin. The groups
are 31 dispatch instantiations, 104 flush instantiations, 16 retire callback
entries, two cold tracking/suppression drains, and three compiler changes in
db0 `reorder.o`. The latter are two ordinary serve callbacks where GCC outlines
`Client::append_fill`, and one fused sweep whose local-read/tombstone control
flow changes despite unchanged source. Their PRE/POST disassembly is retained
in [codegen](docs/clientfix/codegen/). These are reasons for a mainline
performance null, not evidence that the changes are free.

`docs/deadswitch/linked_bytes.py` reports changed sections. `.text` is
7,582,188 → 7,593,452 bytes (**+11,264**). [Linked receipt](docs/clientfix/linked.json).
All eight locks remain Op 336 / Client 1984 / ThreadCtx 1408 / Shard 1440 /
FlatStore 944 / Rob<64> 192 / AtomicEntry 144 / Config 624. The armed heap
`ClimonConn` sidecar grows to hold receipts and pending reads; fixed/default
object layouts and all named IoLoop offsets are unchanged. No PAD arm is
named or performance gain claimed. The mainline performance null is pending.

**PFMESSAG.1 measurement handoff.** No optimization was made for this finding.
The standing competition-lane rule says not to run measurements; no exception
was received, so the table is explicitly pending the maintainer's quiet-box run.

| Cells | PRE p50/p99 | POST p50/p99 | Tomo ON/OFF ratios | Redis p50/p99 and ON/OFF ratios |
|---|---|---|---|---|
| Widths 1/32/256/1024 × 1s/2s × OFF/BCAST/default | Not measured | Not measured | Not measured | Not measured |

`tests/clientfix_widths.py` uses one open-loop MSET connection and one idle
RESP3 tracking observer, existing keys, widths 1/32/256/1024, OFF/unmatched
`BCAST PREFIX never:`/default-preread, PRE and POST in both modes, Redis 7.4.10,
three boots per arm and 1000 samples per cell at **100 MSET/s**. Tomo uses 16
shards, split ratio 6:2, atomic/read-local/reorder/key-lb/client-lb/flip-auto all
0; slowlog and latency monitoring are off for every arm. Disabling the two
balancers and reusing connections fixes writer and observer ownership within
each boot. The driver interleaves PRE/POST/Redis arms,
reverses arm order on alternating boots, and rotates cell order. Default mode
reads each cell's keys once before timed writes, as requested; it does not add
refresh reads to the timed workload.

Latency starts at the scheduled issue time; send-to-reply latency and sender
lag are also retained. Each cell records /proc/loadavg, CPU pressure and
CPU112–127 occupancy, so sibling load is visible beside the timings. A p99 at
or above the offered period flags an unsuitable under-capacity comparison.
Do not compile during this run. The command produces 180 cells / 180,000 samples
with the defaults (about 30 minutes of timed traffic).

```sh
taskset -c 112-127 taskset -c 121-127 python3 tests/clientfix_widths.py --pre build/clientfix/pre/tomokv --post build/tomokv --redis /tmp/claude-1000/redis74/src/redis-server --port 25080 --cores 112-119 --oracle-cores 120 --boots 3 --samples 1000 --rate 100 --output build/clientfix/widths.jsonl
taskset -c 112-127 python3 docs/clientfix/summarize_widths.py build/clientfix/widths.jsonl > MEASURE-RESULT-clientfix.md
```

The table generator refuses missing boots/cells, changing hashes, mixed rates,
and unequal sample counts. It reports pooled p50/p99, ON/OFF ratios beside
Redis's matching ratios, and every per-boot latency/load row. Its arithmetic and
missing-boot control were checked with synthetic data only. The deciding numbers
are the ON/OFF p50 and p99 ratios at matched offered load, plus POST/PRE by cell;
saturated/late-sender cells or changing sibling contention support no merit
claim. The supplied audit's saturation ratios are not substituted for this table.
