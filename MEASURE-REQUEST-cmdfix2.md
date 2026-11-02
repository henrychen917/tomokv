# Round-5 command fixes

## cmdfix2

All six requested fixes are implemented. Final directed oracle witnesses pass
**239,776 checks**. The 14 final selected gate invocations record **832 passes
and two failed rows**: the unchanged string-limit baseline and one FIFO latency
guard that did not recur in one serial PRE trial and one serial POST trial.
Both failed rows remain visible; this is not an all-green gate result.

Branch `cx-cmdfix2`, PRE `9d6ab5526f8fff0c8617e94cf20fa837e15ab0f8`.
The six initial production fixes end at `77c64b44ae`; `8f94e50a94` completes
the GEO port's unit-conversion and floating-point operation order. Other
commits contain proof, test integration and this report. No push. No layout
lock or ownership protocol changed. The GEO change is the explicitly
requested Redis 7.4 helper port.

Correctness work uses CPUs 100–111, servers 100–107, ports 21300–21399,
`LC_ALL=C`, 16 shards and split ratio 6:2. Builds use at most 12 jobs.
The oracle is the supplied Redis 7.4.10 binary/source tree.

### Defects and falsifiable witnesses

Each row below is one `tests/gate.sh` job. Each job executes 32 legs:
uring/epoll × 1s/2s × read-local 0/1 × atomic 0/1 × databases 1/16.
The multi-database legs SELECT database 7. All comparisons continue after a
failure, so PRE does not omit later legs. Full replies and placement evidence
are archived in `docs/cmdfix2/gate-receipts`; the exact totals and per-leg
failures are in `docs/cmdfix2/witnesses.json`.

| Item / job | PRE witness | POST result | Mechanism changed | Residual |
|---|---|---|---|---|
| CD5.1 / `cmdfix2-geo` | 679 differences in each of 32 legs; 21,728 total | 222,704 checks, zero differences | Redis WGS84 bounding box, step selection/decrease, neighbor exclusion/traversal, radius and rectangle predicates, retaining raw shape units and reference arithmetic | Pre-existing boundary-coordinate encoding differences, CD5.9, remain |
| CD5.2 / `cmdfix2-scores` | 35 differences per leg; 1,120 total | 5,008 checks, zero differences | Compare sorted scores as doubles; exclude values outside `[0, 2^52)` before decoding | GEOPOS/FROMMEMBER decoding of invalid scores, CD5.8, remains |
| CD5.7 / `cmdfix2-hll` | 14 differences per leg; 448 total | 4,656 checks, zero differences | Send PFMERGE and multi-key PFCOUNT through the existing EXEC scatter lowering, including same-shard placement | Existing script command restrictions are unchanged |
| CD2 / `cmdfix2-lcs` | 25 differences per leg; 800 total | 2,800 checks, zero differences | Redis dimension/overflow/bulk-limit checks before table allocation; read the raw live limit, preserving the separate string-size clamp | The quadratic LCS algorithm is unchanged |
| CC5.6 / `cmdfix2-channels` | 30 differences per leg; 960 total; original T40 also leaked three messages in both modes | 3,088 checks, zero differences; T40/T47 deliver no forbidden messages | Shared command/key/channel permission predicate at queue admission and EXEC recheck, including the ACL shadow | Existing ACL LOG presentation/context differences and selector compatibility remain |
| CC5.9 / `cmdfix2-xsetid` | 15 differences per leg; 480 total | 1,520 checks, zero differences | Redis option validation order, supplied/current tombstone checks, live top-entry check, entries-added validation, and ignore MAXDELETEDID 0-0 | Deleted-PEL delivery counters and extreme XCLAIM IDLE semantics remain CC5.11/CC5.12 |

GEO uses the auditors' high-latitude and pole witnesses, plus a fixed randomized
600-member dataset, latitude -85 through 85, both shapes, m/km/ft/mi,
ASC/DESC/COUNT/ANY, and GEOSEARCHSTORE with and without STOREDIST. Stored
member-to-score mappings must equal Redis's. Unsorted/ANY replies are compared
in traversal order. All legacy radius verbs and their STORE/STOREDIST forms
also have directed oracle comparisons. The ported helpers disable floating
point contraction to preserve the reference's arithmetic and exact STOREDIST
scores under this tree's compiler flags. Shape dimensions remain in their
original units until the same point as Redis's conversion. Dedicated km/ft/mi
box-step boundary cases catch premature conversion: the first POST fails
30 comparisons per leg, 960 total. Its receipts and instruction counts remain
explicitly superseded under `docs/cmdfix2/v1` and `instructions/POST-v1`.

HLL placement is observed with DEBUG SHARDS: same shard, different shards on
one owner, and different owners. LCS lowers the live bulk limit on PRE, making
the absent guard fail without allocating the original 3.6 GB table; exact
threshold and error precedence are checked. The original 30000-by-30000 audit
is rerun on POST. Channel witnesses include PUBLISH, SPUBLISH, SUBSCRIBE,
SSUBSCRIBE and PSUBSCRIBE, queue rejection/EXECABORT, permission revocation
before EXEC, and changes within EXEC. XSETID covers failure atomicity, option
order/repetition, empty/nonempty streams, pending ID reuse and lag.

The original PRE run preceded all six fixes. GEO's later expanded all-unit
STORE witness and the final channel witness are separately retained. The
earlier channel witness also exercised an unsupported selector grammar;
those five unrelated errors are not included in the final 30-error witness.

### Auditor reruns

`tools/cmdfix2_auditors.py` executes the original files read-only, adapting only
owned process lifecycle, CPU/port/path selection. Source digests, raw results
and comparisons are in `docs/cmdfix2/auditor-receipts` and `auditors.json`.

* G-T1: 360 polar + 210 mid-latitude queries per mode, **0 differing queries,
  0 missing members, 0 extra members**, matching Redis's own zero counts.
* G-T2: 13 radius and 8 box checks per mode, zero differences. T9/T10: 10
  checks per mode, zero differences, including database 7/read-local/atomic.
* G-T3b: seven score conditions × 60 queries = **420 queries per mode**,
  zero wrong replies or missing members. G-T3's wider script retains 17/96
  differences per mode for the out-of-scope invalid-score decode behavior.
  T8 retains 28/314 differences per mode for boundary/invalid-score behavior.
* S-T22–T24: `pfsame` 30/30 and `multilocal` 50/50 in both modes and both
  atomic settings. `pfmulti` retains 9/34 differences in each leg, all script
  restrictions; its EXEC HLL results now match.
* S-T6: original 30000-by-30000 POST case rejects with Redis's exact
  `ERR Insufficient memory, transient memory for LCS exceeds proto-max-bulk-len`
  in both modes; the oracle rejects identically. No 3.6 GB table is allocated.
* T40/T47: all 21 non-log result fields equal the oracle in both modes;
  forbidden deliveries are empty. Raw ACL LOG is retained separately,
  including its existing formatting/context and dynamic timestamp differences.
* T21: 39/43 result fields equal Redis per mode. The four remaining fields
  are deleted-PEL delivery counts (three fields) and extreme IDLE (one).
  The XSETID rejection, no ID reuse, watermarks and resulting message history
  match. T21b: all 5/5 fields equal per mode; MAXDELETEDID 0-0 preserves `5-0`
  and the unknown lag.

### Existing gate and Tcl proof

The final job inventory is `docs/cmdfix2/final-jobs.json`.
`docs/cmdfix2/gate-summary.json` retains the history, with original logs and
receipts for **every run, including failed controls and superseded arms**.
These are selected correctness jobs, not a full-gate receipt. Final totals
and build freshness are recorded below. The two deliberately stopped V1 broad
runs are marked as superseded and do not contribute to final totals.

Both engines complete the gate's standard differential seeds 7, 19, 20 and
23, plus the standard rotating seed (25 for uring, 24 for epoll). Each engine
has **941 passing rows, zero failures**, including mode equivalence. The eight
command matrices record **8,501,392 comparison witnesses** in total and each
observes 232 of the 245 registered commands. The exact observed/unobserved
inventory is retained in `docs/cmdfix2/differential.json` and the original
receipts; these counts do not claim universal command coverage.

The additional `rootcompat-stringlimit` job reports exactly the same 24
failures on PRE and final POST (SETRANGE/APPEND/SETBIT above the 32-bit representation,
three checks × eight mode/engine/namespace legs). The raw failure lines are
identical. This is the already documented CD5.20/NETFIX-POST-2 clamp, outside
this lane's S1 scope; its failing row remains visible. All 24 final failure
lines equal the archived PRE lines (`docs/cmdfix2/stringlimit-baseline.json`).

The final uring selection also has a `txnorder_fifo_live` failure:
the db1/2s/atomic=1/epoll leg exceeded the existing 20 ms plain-command p100
guard (34.3967 ms). Its saved final counters match, all 60 windows made
progress, FIFO waits occurred, and ordering violations are zero. The original
failure remains a failed row; the other 15 legs pass. After every selected
gate exited, one serial repetition of that unchanged 60-second test on PRE
and one on POST both passed, including clean shutdown. Their p100 values were
1.0541 ms and 4.8348 ms, respectively. These single trials do not explain or
clear the original failure and do not establish a performance regression or
gain. No threshold is changed. Exact boot/test arguments, semantic counters,
original failure and diagnostic receipts are in `fifo-summary.json` and
`fifo-receipts`. This remains a release caveat for the maintainer's quiet-box
performance verdict.

Tcl runs the gate's `redis_tcl` job in both modes against unchanged upstream
`unit/geo`, `unit/hyperloglog`, `unit/acl`, `unit/pubsub`, `unit/type/stream`,
and `unit/type/stream-cgroups` files. The first ACL block was previously
entirely excluded by `external:skip`; the adapter admits only that live-API
block and rejects changes to its setup. Later restart/config-file blocks
remain excluded. The exact required assertion inventory now includes the
channel-in-MULTI regression, which fails on PRE in both modes.

The new ACL subset requires 69 passing assertions. Ten named compatibility
failures remain excluded; five additional LOG assertions depend on setup in
one excluded test, so their dependencies are explicitly documented instead of
silently inventing setup. The unfiltered survey retains all 76 passes and 10
failures per mode. No existing required Tcl assertion was removed.

The existing pub/sub assertions reproduced the documented T61/D14
cross-connection ordering family on **both PRE and POST**. Seventeen
self-contained pub/sub assertions use the runner's existing fresh-listener
isolation, preserving every required pass. In addition, the upstream
no-argument PUNSUBSCRIBE helper consumes zero acknowledgments before another
connection publishes. Its adapter consumes and verifies all three actual
removal acknowledgments, including the final zero count, before the unchanged
assertion continues. A missing or duplicated acknowledgment-fence receipt
fails validation. These are explicit completion boundaries, without retries
or a sleep/tolerance. The original failures remain archived. Stream-cgroups'
pre-existing, exactly named appendonly CONFIG setup error remains explicit in
the manifest; it is not an assertion pass.

NOT RUN: the full iteration, ABBA/throughput benchmarks, performance load
generators and standalone latency benchmarks, reserved for the maintainer.
The existing latency guard within the required FIFO correctness job and its
two diagnostic trials are reported above. `GATE_PROOF_NO_RATES=1` is used only
with selected partial jobs. The stream job retains all 16 metadata cases and
prints NOT RUN for its separate latency benchmark; atomic floor/rate-only
parts retain their existing partial-proof omissions. No throughput claim is
made here.

### Command-scope instruction counts

`tools/cmdfix2_counts.py` links the frozen PRE production objects and the POST
production objects to the same finite serverless fixture. It traces executed
in-image instructions, including outlined C++ helpers, excluding the fixture
and shared-library internals. It uses deterministic clock returns and the
existing tracer's REP accounting. There is no socket, load generator or rate
measurement. Build recipes, object/probe/tracer digests, per-function counts
and instruction-site receipts are committed under `docs/cmdfix2/instructions`.

`instructions/table.csv` contains all **144 paired cases**: both namespaces,
both modes, atomic 0/1, batches 1/32. MGET/MSET use eight actual shards.

| Command | Paired cases | PRE total instruction range | POST | Added instructions |
|---|---:|---:|---|---:|
| GET | 16 | 783–18,482 | identical in every case | 0 |
| SET | 16 | 894–21,394 | identical in every case | 0 |
| INCR | 16 | 1,244–36,547 | identical in every case | 0 |
| MGET | 16 | 10,026–324,390 | identical in every case | 0 |
| MSET | 16 | 10,428–962,174 | identical in every case | 0 |
| PUBLISH, ACL off | 16 | 223–8,320 | identical in every case | 0 |
| PUBLISH, active default ACL, including admission | 16 | 710–23,872 | 718–24,128 | +8 per command (+256 per batch 32) |

The main-command scopes cover production owner execution and scatter
preparation/completion/retirement. They exclude socket parsing and IO admission.
PUBLISH measures ACL admission when active and the production pub/sub entry
with no subscribers; it excludes socket parsing and delivery fan-out.
GEOSEARCH returns the same sorted 64-member
result in both arms. EXEC is an uncontended MULTI/INCR/EXEC activation including
queueing, lowering and retirement; the first activation includes lazy verb
table initialization. Batch 32 means one transaction with 32 children.

| Namespace / scope | 1s PRE → POST, batch 1 | 2s PRE → POST, batch 1 | Batch 32 added instructions, either mode |
|---|---:|---:|---:|
| normal GEOSEARCH | 74,407 → 73,106 | 75,027 → 73,726 | -41,632 |
| db0 GEOSEARCH | 75,104 → 72,282 | 75,337 → 72,515 | -90,304 |
| normal EXEC | 23,968 → 24,520 | 23,923 → 24,475 | +986 |
| db0 EXEC | 22,588 → 23,144 | 22,530 → 23,086 | +1,114 |

Atomic 0 and 1 have identical values in this table. Instruction changes do
not establish rate or cycles/op changes.

### Arms and maintainer measurement request

Deliverables are `build/cmdfix2/PRE`, `POST`, `PAD-A`, and `PAD-B`; exact SHA-256s
are in `docs/cmdfix2/arms.sha256`. POST is the binary used by the final directed
witnesses and the broad jobs. All footprint locks retain their base values.

| Arm | SHA-256 |
|---|---|
| PRE | `79f8ca525f3a2050367d84ad74b6413087ed7a67e119b9eb23a47197c0d49f88` |
| POST | `204cc07b6b3da1d35e17d09aa5bbff4e9a26654a281cf46766e2162d66f30b7f` |
| PAD-A | `68431818fe79fff1fdfabde597922c898af41bc3cdc06d8e6bda77ee39cb6255` |
| PAD-B | `05a5f8e2853bb7734e313e5a9b62f5c8884e78ccbce017c2af2e25cf4492cb56` |

PRE `.text` is 9,021,623 bytes; POST is 9,019,927 bytes, **-1,696 bytes**.
Both begin at `0x2cad0`.

* **PAD-A, kind A: PRE behaviour with POST's total text extent.** Only PRE's
  GEO translation units are recompiled with alignment padding disabled; all
  other objects remain PRE. Unreachable text padding (12,320 bytes) brings
  `.text` to POST's address/size. A further 4,096 bytes of read-only padding
  matches POST's `.rodata`, `.data` and `.bss` start addresses (the `.rodata`
  sizes differ).
  It is an extent control, **not an exact individual-symbol layout twin**;
  GEO alignment/code generation may differ, so this arm cannot attribute a
  GEO rate difference to semantics alone. `pad-a.json` records this limitation,
  exact recipes, padding and section sizes. Its six witnesses retain PRE's
  failing behavior.
* **PAD-B, kind B: inverse control.** Unmodified POST objects plus unreachable
  padding (1,696 bytes) restore PRE's `.text` extent and `.rodata` start.
  Its `.data`/`.bss` starts remain 4,096 bytes later than PRE's; it does not
  control that placement. Included because the text-size change exceeds a
  few hundred bytes. All six witnesses pass, 32 legs each.

Maintainer: run the **14 generic cells plus 2s GET/SET at p1/p32** with the
gate's own instrument and these arms on the quiet scheduled box. Retain
matched offered load and the same geometry for every arm. Report PRE/POST/
PAD-A/PAD-B cycles/op, IPC, instructions/op, rate and the declared latency score.
`docs/cmdfix2/measure-cells.txt` preserves the 14 existing rows from
`tests/wbland_merit_cells.txt` and adds four split companions with the same
workload fields. The generic IDs are h05, h06, p8g, p8s, d1g_l0, d1s_l0,
m8g_l0, v1g_l0, d128g_l0, d32g_l1, d8s_l1, d32s_l1, x9_32_l1 and x9_32_l0.
Use eight server CPUs, 16 shards and split ratio 6:2; retain the instrument's
normal payloads, connections and load placement. Begin with a PRE/PRE null
and preserve the gate's ABBA ordering and acceptance bands per cell.
Rate at matched offered load, or the cell's declared latency score, decides
regression; instructions and IPC explain it. Ordinary-command
serverless counts above establish zero added instructions only. The requested
rate/latency measurements are NOT RUN by this lane.

### Gate row accounting

**DQ = +6; DF = +6.** `tests/gate.sh` collects the six `cmdfix2-*` rows at
line 6684, before the quick-tier exit block at line 6827. Each contributes exactly
one row regardless of its 32 internal legs. The line position, rather than
registration or function position, determines both increments. Starting at
the user's PRE counts, the owner should set **EXPECT_QUICK 1046 → 1052** and
**EXPECT_FULL 1063 → 1069**. This lane does not edit either constant. Tcl
promotions, bounded-resource planning and partial benchmark omissions add no
rows.

### Final validation ledger

* Final directed witnesses: **239,776 checks across 192 legs, zero failures**;
  the same six witnesses produce **25,536 differences on PRE**.
* Final Tcl receipts contain **311 required assertion occurrences per
  mode/engine leg**, **1,244 total**, with exactly one verified PUNSUBSCRIBE
  completion fence per leg. `tcl-summary.json` checks the exact assertion-name
  multiplicities, source receipt hashes and named setup errors against the
  manifest. The stream-group suite intentionally runs one XCLAIM assertion
  name twice; both occurrences are required.
* `python3 tests/gates_test.py`: **77 tests pass**. The Tcl runner's 14
  serverless controls and gate planner self-tests also pass.
* `make all` and every one of the **55 `job_production_units` targets** pass,
  along with the live control arms and blockfix supplemental targets. All
  **five `make -q` checks return 0**. The phony live-arm recipe is checked via
  its two concrete build roots. See `freshness.json`, the final repeated
  freshness check in `final-freshness.json`, and `local-checks`.
* The final epoll broad selection passes **202 rows, zero failures**. Its
  differential subjobs pass **941 rows** (235 split/atomic=0, 239 split/atomic=1,
  231 fused/atomic=0, 235 fused/atomic=1, one mode-equivalence row), with zero
  failures. The final uring broad selection has **348 passes and one FIFO
  latency-guard failure**. Its differential subjobs have the same 941 passing
  rows and zero failures. The failed FIFO row is retained despite both serial
  diagnostic trials passing.
* The final related selection passes **82 rows, zero failures**. Each of the
  four notification selections (uring/epoll × 1s/2s) passes **7 rows**, 28
  total, with zero failures.
* Supplemental fused uring/epoll selections pass **45 rows each**. The epoll
  mode/order selection passes **57 rows**. The extra selection has **12 passes
  and one unchanged baseline string-limit failure**, detailed above.
* `git diff 9d6ab5526 --check`, gate shell syntax, and Python syntax checks
  pass. Debug compression of unit artifacts preserves every allocated ELF
  section; it does not alter any delivered arm. `build/` is about 14 GiB.

All requested correctness selections have completed. The 18 requested
performance cells remain NOT RUN for the maintainer as specified above.
