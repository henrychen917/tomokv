# Store round-5 fixes

## storefix5

Worktree `/home/user/Projects/cx-storefix5`, branch `cx-storefix5`; PRE is
`ea48a6b2721a1d9e5964ab24a32e8b54df611bd5`. No push. The last item commit
contains idle-clock accounting and can be excluded independently. The preceding
commits contain RANDOMKEY, APPEND, and their zero-cost/harness controls.
Excluding the last item requires rebuilding and revalidating that two-item
variant: the combined POST instruction and footprint receipts do not apply to it.

All lane workloads and builds use CPUs 16–23, at most eight workers per make, and
ports 21600–21699. Server children inherit `LC_ALL=C`. Only finite correctness,
footprint and serverless instruction checks were run. No throughput result or
full iteration is claimed. Initial failed trials remain in the receipts.

The proof retains unresolved FIFO deadline failures, inherited Tcl/string-limit
failures and upstream Tcl maxmemory skips, detailed below. All eight standard
differential matrices pass (1,880 suite/seed runs), both engines' mode-equivalence
jobs pass, and all 96 maxmemory-off command scopes add zero instructions.

### Items and boundaries

| Item | PRE witness | POST result | Mechanism changed | Residual / freeze boundary |
|---|---|---|---|---|
| SO5.3 / SO5.7 RANDOMKEY | Gate witness reaps all 400 elapsed keys in one call despite a survivor on every shard; 1M-key footprint witness fails | Directed gate matrix checks empty/all-expired nil, expiry/PAUSE, uniform sampling, EXEC and namespace/SWAPDB images; 1M-key footprint passes | One shard selected by published namespace counts, bounded slot rejection, one retained key; dead handler removed and store tests call the executed sampler | The fast path uses at most 64 slot probes plus O(shards) routing. Probe-budget exhaustion (even on an ordinary image), sparse namespaces, pending MVCC records and EXEC retain resumable O(keys) scans. The pending side-key walk is inherited and not bounded by the physical-table budget. General O(1) over those images is **not delivered**. |
| SO5.6 APPEND | Production-linked malloc/copy spy detects one merged scratch allocation and fails | Same spy observes zero merged scratch allocations; live values, TTL, binary/integer input, encoding and errors pass | Allocate the final immutable external string and copy old bytes and suffix directly into it | Still O(old length), hence quadratic for repeated one-byte growth. No slack-space mutation or object-layout change. |
| ST5.3 / SO5.2 idle clock | Enabling maxmemory over 10k keys leaves INFO used_memory unchanged; footprint table below shows the hidden RSS | Exact node accounting, side-effect-free observations and deferred reclamation pass; all 16 limit/value/policy/mode cells pass | Charge each branch/leaf allocation to existing store accounting, reserve missing-path bytes before admission, subtract after clock destruction/grace | Nodes remain until maxmemory is disabled. Non-evictable retained metadata can eventually exhaust a budget under churn. Fixed process RSS, allocator retention and snapshot admission exceptions remain. This is not an RSS cap. |

RANDOMKEY counts are routing hints, never proof of emptiness. Empty candidates
visit each remaining shard at most once before nil. The sampler retains the
existing expiry notifications, snapshot pre-image handling, undecided/parked
visibility rules and CLIENT PAUSE expiry hold. It uses the existing store read
view; it does **not** add a new global RANDOMKEY snapshot guarantee. EXEC keeps
its fixed all-shard participant mask and a one-key reservoir per shard. A draft
that changed EXEC participants hung and was rejected (`randomkey-post-2s.log`).
The physical-table fallback yields every 256 scan homes; there is no vector of
all keys. It inherits SCAN's home/cluster traversal, so this is not a hard
wall-clock bound for an adversarial probe cluster. Making sparse namespaces or pending-only images uniformly sampleable
in expected O(1) would require a maintained visible-key sampling index and write
path work. A finite probe budget followed by a census does not establish an asymptotic expected-O(1) guarantee. That extension is stopped at the architecture/zero-cost boundary.

The final review also found a full-retirement-ring expiry stall in the shared
SCAN visitor, reached by RANDOMKEY's fallback. Its physical deletion could enter
`force_oldest_grace()`. The fast sampler could emit an expiry notification before
that deletion was possible. Both now check retirement capacity on the expired-key
branch: the key remains logically absent, its object remains resident, and the
event/AOF delete occurs once capacity returns. The shared visitor also protects
KEYS/SCAN from that same wait. No reader retries are introduced. The deterministic
store witness forces both sampler paths and asserts the capacity check actually
fires. PRE's original scan fails; removing either guard from POST independently
fails for its specific reason (`retirement-*.json`, `retirement/controls.json`).
The test helper now rejects a selected name that resolves to an invisible key,
instead of converting it to nil. A third negative control removes the sampler's
visibility filter: it passes with the old helper and fails with the strengthened
assertion (`retirement/masked-visibility-before.json`,
`retirement/no-visibility-guard.json`). The corrected storage job passes through
the gate interface (`gate-sampler-final.log`).

APPEND uses ordinary immutable insertion, retirement, metadata and publication
failure cleanup. Its allocation spy is the decisive PRE-failing witness:
external memcpy interception does not count compiler-inlined copies, so its
PRE byte total is not presented as a complete census. The smallest after-freeze
proposal is capacity-bearing raw storage with owner-only append eligibility:
read-local disarmed, no snapshot pre-image, no MVCC predecessor, no outstanding
borrow. Arming transitions must synchronize with eligible writers; checking a
flag once is insufficient. Otherwise retain COW; amortization with those readers armed needs an
immutable chunked/frozen-prefix design. Neither is implemented.

Idle nodes are allocated only while maxmemory is enabled. No node or clock is
allocated at maxmemory 0. Allocation estimates walk existing links without
installing nodes or updating stamps. Partial allocation failures retain charges
for the nodes actually installed. Runtime enable charges only after successful
construction; its existing bad_alloc error path is untouched (cfgfix2 owns it).
Disable keeps the retired tree charged until its owning store's QSBR reclaim
callback. Owner migration already drains/rebinds the retire sink. KV objects and
the listed locked structures retain their layouts. The cold scatter `GroupAux`
allocation grows from 80 to 136 bytes to hold RANDOMKEY's cursor and retained
key (`cold-layout.json`, `cold-layout-final.json`); KEYS and capture-safe FLUSH use that helper too.
Ordinary GET/SET/INCR/MGET/MSET do not allocate it.

### Arms

PAD-A is a **behaviour twin (A)**: PRE behaviour with POST's 136-byte cold
`GroupAux` layout and aggregate `.text` start and extent. A private PRE source
copy adds the unused cursor fields; both namespace builds assert the helper's
size. Unreachable trailing NOPs match the remaining text extent. Per-function
addresses are **not matched to POST**, so this control cannot isolate every
code-placement effect. No gain is inferred from it. The earlier extent-only
PAD is preserved as `build/storefix5/pad-a/extent-only-tomokv`, with receipts
named `pad-extent-only*`.

| Arm | Path (under this worktree) | SHA-256 |
|---|---|---|
| PRE | `build/storefix5/PRE` → `build/storefix5/pre-source/build/tomokv` | `59ad75c28b64f855dd5d80fafc39928386b55eaeb900016fe09da93b7dd902b2` |
| POST | `build/storefix5/POST` → `build/storefix5/arms/retirement168000/tomokv` | `d661aa5dc9cb2eeebb465ebc3a1d41ab2455dfeca5fb73254f448a5dc40eb6cd` |
| PAD-A | `build/storefix5/PAD-A` → `build/storefix5/pad-a/tomokv` | `013ac645dadf0674ab26c92a83a7c9409165838fead7810544951266644612eb` |

POST/PAD `.text`: 9,045,863 bytes at 182,992; PAD adds 24,080 bytes. Build/link commands and object choices: `budgets/retirement168000-link.json`, `pad-a.json`. Earlier footprint/control binary `55b996cc…` is preserved as `build/storefix5/arms/candidate/tomokv`; final POST is the `retirement168000` link. The preceding `09367b85…` arm remains available for the earlier receipts.

### RANDOMKEY: 1M keys and sampling

Five finite single calls, followed by four connections × 16 calls. These are
final samples run serially after this lane's builds completed on the assigned
CPUs. Whole-box quietness was not certified; these are **not quiet-box latency
or throughput verdicts**. The
non-timing mechanism witness and bounded memory assertion carry the proof.
Receipts: `curves-release/{pre,post}-*.json`, `curves-release/redis-2s.json`. Earlier contended observations remain in `curves` and `curves-release-before-retirement`.

| Arm | Single-call ms, min / median / max | RSS increase after singles, MiB | RSS increase after 4×16, MiB |
|---|---:|---:|---:|
| PRE 1s | 51.0835 / 52.5947 / 56.2912 | 80.070 | 207.891 |
| PRE 2s | 117.6997 / 121.8750 / 133.5686 | 66.398 | 49.477 |
| POST 1s | 0.0124 / 0.0238 / 0.0827 | 0.004 | 0.062 |
| POST 2s | 0.0123 / 0.0171 / 0.0333 | 0.047 | 0.664 |
| Redis 7.4 | 0.0127 / 0.0130 / 0.0274 | 0.000 | 0.000 |

Uniformity uses 32 named keys, 16,384 draws, chi-square with 31 degrees of freedom. The TomoKV assertion is chi-square < 100 and every key observed. All 32 final POST boots pass; observed ranges are 1s: 23.0195–40.7617; 2s: 24.0938–43.9492 (`randomkey-final-distribution.json`). Redis is measured without imposing that threshold: five fresh runs were 384.0234, 385.4492, 126.3477, 231.5938, 534.2734. These observations compare distribution quality; they do not prove exact uniformity for arbitrary evolving keyspaces.

### APPEND curve

Median SLOWLOG command duration in microseconds for five one-byte appends per
initial size; all resulting values and TTLs are checked. `0` means below the
one-microsecond timer resolution, not zero work. Host activity and allocation
coldness can affect these small samples. The maintainer must repeat on a quiet box
before using the curve in a paper. Raw individual observations are retained.

| Initial size | PRE 1s | POST 1s | PRE 2s | POST 2s | Redis 7.4 |
|---|---:|---:|---:|---:|---:|
| 16 B | 0 | 0 | 0 | 0 | 0 |
| 1 KiB | 0 | 0 | 0 | 0 | 0 |
| 64 KiB | 14 | 2 | 5 | 4 | 0 |
| 1 MiB | 79 | 30 | 57 | 29 | 0 |
| 4 MiB | 632 | 153 | 244 | 118 | 1 |

### Maxmemory footprint

16 shards, eight threads; split geometry is 6 io + 2 ex. Each cell boots fresh
with maxmemory already set, offers a bounded population, validates only expected
OOM replies, verifies used_memory near/below the accounting budget, records keys
and RSS, then flushes and removes its private data. Redis is single-threaded.
Values are 100 or 1000 bytes. Numbers below are RSS/maxmemory and retained keys;
raw used_memory, accepted/refused/evicted counts are in `memory/{pre,release,redis}`.

| Mode | MiB | Policy | Value B | PRE RSS/limit; keys | POST RSS/limit; keys | Redis RSS/limit; keys |
|---|---:|---|---:|---:|---:|---:|
| 1s | 30 | allkeys-lru | 100 | 2.860; 224,688 | 1.705; 115,856 | 1.136; 160,873 |
| 1s | 30 | allkeys-lru | 1000 | 2.006; 29,008 | 1.553; 20,338 | 1.136; 27,710 |
| 1s | 30 | noeviction | 100 | 2.526; 224,688 | 1.571; 115,913 | 1.136; 154,918 |
| 1s | 30 | noeviction | 1000 | 1.964; 29,008 | 1.528; 20,749 | 1.000; 27,710 |
| 1s | 100 | allkeys-lru | 100 | 2.311; 748,976 | 1.414; 388,176 | 1.040; 566,007 |
| 1s | 100 | allkeys-lru | 1000 | 1.597; 96,720 | 1.210; 69,112 | 1.061; 94,450 |
| 1s | 100 | noeviction | 100 | 2.324; 748,976 | 1.253; 388,390 | 1.040; 566,006 |
| 1s | 100 | noeviction | 1000 | 1.595; 96,720 | 1.188; 69,594 | 1.061; 94,451 |
| 2s | 30 | allkeys-lru | 100 | 5.693; 224,688 | 1.593; 45,048 | 1.136; 160,873 |
| 2s | 30 | allkeys-lru | 1000 | 1.782; 29,008 | 1.571; 23,936 | 1.136; 27,710 |
| 2s | 30 | noeviction | 100 | 5.370; 224,688 | 1.619; 47,479 | 1.136; 154,918 |
| 2s | 30 | noeviction | 1000 | 1.745; 29,008 | 1.603; 23,964 | 1.000; 27,710 |
| 2s | 100 | allkeys-lru | 100 | 5.210; 748,976 | 1.264; 151,424 | 1.040; 566,007 |
| 2s | 100 | allkeys-lru | 1000 | 1.399; 96,720 | 1.218; 80,496 | 1.061; 94,450 |
| 2s | 100 | noeviction | 100 | 5.175; 748,976 | 1.178; 159,841 | 1.040; 566,006 |
| 2s | 100 | noeviction | 1000 | 1.401; 96,720 | 1.177; 80,656 | 1.061; 94,451 |

Every final POST observation is at or below the configured used_memory limit; remaining headroom is 192–14,964 bytes across the 16 cells. This stronger check uses the raw observations, without the cross-server helper’s allowance.

Charging metadata reduces capacity; the formerly larger key count was not
free memory efficiency. Snapshot pre-images/retirement and allocator retention
still require headroom. Noeviction includes expected refused SETs. Allkeys-lru
cannot reclaim retained clock nodes without a structural change.

The historical eviction fixture assumed its 1 MiB setup budget retained 3000
keys; that became false once metadata was charged. Its setup now proves a full
unevicted cohort, then derives pressure from accounted bytes. LFU uses 1000-B
values so retained metadata does not consume the whole pressure budget; 100-B
values are covered above. Existing age, LFU-frequency, hot-survivor, touch/no-touch,
lane and conservation assertions remain. The initial eight red rows and the
fixture's subsequent integer-encoding error are retained, followed by eight
green corrected rows (`gate-eviction-final.log`). All eight eviction jobs also
pass on the final frozen POST in `gate-live-final.log`. No tolerance was widened.

The notification battery had a second fixed-budget assumption: it seeded 160
keys, lowered maxmemory to 16 KiB, and only then armed eviction notifications.
With the clock charged, that limit is below the retained metadata; the seeds can
be gone before arming, and all later SETs can return OOM. Both atomic settings
failed loudly in `gate-inventory-final.log`. The fixture now proves the full
unevicted cohort under a setup budget, arms delivery, then derives pressure from
observed used_memory. It retains the original bounded trigger attempts, event
name check and mandatory fired/evicted counter advances. Complete PRE and POST
job reruns in both modes are recorded as `gate-notify-*-final.log`.

### After-freeze structural alternatives

`tools/storefix5_clock_geometry.cc` allocates 50,000 actual jemalloc object-size
blocks with 16-byte keys using eight pinned allocator threads, then replays the
**same addresses** into unchanged clocks grouped per shard, per owner or once
per process. Assignment is synthetic deterministic round-robin, not the live
server's random key hashing. This measures allocated node bytes, not live-server RSS or concurrent
shared-tree correctness. `clock-geometry.csv` contains both 16- and 128-shard
cases and all four value sizes. The 128-shard cases below show the address-sharing
multiplier. A stamp column is the exact size-class delta for adding a 4-byte word
to these allocation requests; other key lengths/TTLs can cross other classes.

| Allocation source | Value B | Per-shard B/key | Per-owner B/key | Process-wide B/key | 4-B stamp class delta B/key |
|---|---:|---:|---:|---:|---:|
| owner | 2 | 298.86 | 18.68 | 17.04 | 0.00 |
| owner | 100 | 1067.60 | 66.85 | 65.13 | 0.00 |
| owner | 180 | 1834.37 | 114.69 | 112.97 | 0.00 |
| owner | 1000 | 331.63 | 20.73 | 19.01 | 16.00 |
| parser | 2 | 2163.36 | 135.66 | 16.96 | 0.00 |
| parser | 100 | 2163.36 | 521.01 | 65.13 | 0.00 |
| parser | 180 | 2173.85 | 904.40 | 113.05 | 0.00 |
| parser | 1000 | 2446.48 | 153.36 | 19.17 | 16.00 |

The audit's live-server measurements corroborate the mechanism: T1d measured
17.5 B/key with one shard per owner versus 144.8 B/key at eight; T1h found 410,
810, 6,370 and 31,714 leaves for 50k external values at 1/1, 2/2, 16/16 and
16/128 thread/shard geometries. T1f measured 549.5/880.3/1650.5 B/key RSS at
100/180/1000-byte values. These audit geometries are not substituted for this
lane's 16-shard matrix.

Expected hot-path costs, not measured timings: an object stamp replaces four
dependent radix-pointer loads with a direct stamp load and the existing rare
CAS/update, but changes header layout and cache-line sharing. A process-wide
tree retains the lookup chain, needs multi-writer CAS node publication and safe
lifetime management, and introduces shared-node contention. A per-owner tree
retains the chain and single-owner allocation, but parser-built headers still
share pages across owners; migration must transfer/rebind stamp ownership in the
same critical section as all other shard-owned structures. None is implemented.

### Command-scope zero-cost proof

The finite ptrace census links production objects and counts named production
functions/assembly only, excluding fixture, shared-library and syscall work.
No server/listener, load generator, PMU rate or wall-clock score is used.
PRE and POST receipts include both namespaces, 1s/2s, atomic 0/1, batch 1/32:
80 ordinary scopes plus 16 fresh-key SET scopes. **No positive delta in all 96.**
GET is a hit; ordinary SET replaces a value; the additional SET scopes insert.
`counts/pre`, `pre-insert`, `retirement168000-full`, `retirement168000-insert` retain totals,
per-function counts, trace sites and link receipts.

Cold-unit growth originally changed GCC inlining/register allocation. The bounded
compile controls are in `budgets/`: xshard 164393 / db0 168000, db0 t_string 14099.
The equivalent MOVE-name check now runs only after its Renamenx classification,
removing unrelated string decoding from MGET/MSET. A superseded control still
added one instruction to fresh db0 SET; the final 14099 control removes it. This
is instruction evidence only; cycles/IPC/rate remain the maintainer's verdict. The final retirement guards crossed the db0 inlining boundary again; the 168000 control restores the PRE find body and the complete census below.

| Namespace | Command | POST−PRE instructions/op range (all modes, batches, atomic settings) |
|---|---|---:|
| normal | GET | 0 … 0 |
| normal | SET replacement | -2 … -2 |
| normal | INCR | 0 … 0 |
| normal | MGET | -23 … -16 |
| normal | MSET | -282.75 … -47 |
| db0 | GET | 0 … 0 |
| db0 | SET replacement | 0 … 0 |
| db0 | INCR | -4 … -4 |
| db0 | MGET | -26 … -25 |
| db0 | MSET | -288.75 … -15 |
| normal | SET insert | 0 … 0 |
| db0 | SET insert | 0 … 0 |

With maxmemory = 1 GiB/allkeys-lru, GET-hit and SET-insert costs are quantified separately (32 scopes, atomic 0/1 give the same deltas). Cold first node creation is outside the warm command scope; finite admission/footprint checks above include it.

| Namespace | Command | Mode | Batch | PRE instructions/op | POST instructions/op | Delta/op |
|---|---|---|---:|---:|---:|---:|
| normal | GET | 1s | 1 | 1054 | 1056 | 2 |
| normal | GET | 1s | 32 | 683.938 | 684 | 0.0625 |
| normal | GET | 2s | 1 | 1672 | 1680 | 8 |
| normal | GET | 2s | 32 | 677.094 | 677.344 | 0.25 |
| normal | SET | 1s | 1 | 1735 | 1776 | 41 |
| normal | SET | 1s | 32 | 1366.88 | 1405.94 | 39.0625 |
| normal | SET | 2s | 1 | 2353 | 2400 | 47 |
| normal | SET | 2s | 32 | 1360.03 | 1399.28 | 39.25 |
| db0 | GET | 1s | 1 | 901 | 903 | 2 |
| db0 | GET | 1s | 32 | 655.906 | 655.969 | 0.0625 |
| db0 | GET | 2s | 1 | 1132 | 1140 | 8 |
| db0 | GET | 2s | 32 | 636.969 | 637.219 | 0.25 |
| db0 | SET | 1s | 1 | 1530 | 1584 | 54 |
| db0 | SET | 1s | 32 | 1286.84 | 1338.91 | 52.0625 |
| db0 | SET | 2s | 1 | 1761 | 1821 | 60 |
| db0 | SET | 2s | 32 | 1267.91 | 1320.16 | 52.25 |

### Gate and proof ledger

The selected-job interface normally requires eight server CPUs plus disjoint
client CPUs. This lane owns only eight. The explicit
`--shared-correctness-cpus` adapter requires selected quick/iteration jobs,
`GATE_PROOF_NO_RATES=1`, exactly the same eight physical CPUs, no SMT, and one
slot. Complete gate/ABBA/NIC/receipt modes still reject it. Planner rejection
controls and mode-equivalence geometry checks are recorded. This is a partial
correctness run, never an EXPECT/full-gate receipt.

Final proof status is recorded in `gate-summary.json` and the individual logs.
Native prerequisites are built before their gate jobs; the initial native run
hit the 900-second build watchdog and correctly failed rows lacking unit-ready
markers. Live AOF equality checks themselves passed in that run. The final
retry uses fresh prerequisites; no missing marker is waived. An initial final
quiet-job selection exited 2 before running any job because build-only TSAN
prerequisites must be selected through their consuming jobs. The consumers are
in the extra run, and the ASAN/quiet-core jobs have a separate serial retry.

Tcl `unit/keyspace` and `unit/type/string` use the existing named passing
manifest (37 + 80 assertions per mode). RANDOMKEY and APPEND semantics were
already required there; the new cost/accounting witnesses are promoted in the
storefix5 job. The unfiltered three-file Tcl job also runs in both modes and
reports its unsupported baseline failures. **unit/maxmemory assertion bodies:
NOT RUN**: all nine start_server blocks carry upstream `external:skip`; the
external runner reports zero assertions. The skips are not counted as passes.
The finite memory matrix, maxmemory/maxmemrace/eviction jobs supply the separate
executed coverage. No upstream assertion or tag was removed to manufacture a
Tcl pass.

`rootcompat-stringlimit` reports 24 failures above the 32-bit value representation
on both PRE and POST; normal configured-limit cases agree. Changing that
representation needs a layout change and is outside this lane. The failure is
reported, not hidden or weakened. Other proof failures are listed separately in
the final ledger.

DQ=+2 / DF=+2. `collect_job storefix5` at line 6507 is before the quick-tier exit
at line 6852 and emits
one 1s row and one 2s row, each covering both engines × atomic 0/1 × read-local
0/1 × databases 1/16. EXPECT constants remain 1046 / 1063. The maintainer's
new counts for this lane alone are **1048 / 1065**. No other public row was added.

NOT RUN: performance benchmarks, load generators, full iteration/ABBA and quiet
latency curves, by the lane's runtime boundary. Pending or failed correctness
checks are not represented as passes. Preloaded data is deleted after completed
runs; build artifacts and receipts remain under the lane worktree.

### Selected-job results and controls

`python3 tests/gates_test.py`: **77 tests PASS**, plus 14 embedded identity tests (`gates-test-final.log`). Planner checks: 25 PASS and 12 measurement-boundary checks PASS. `make all` plus every `job_production_units` target and its supplemental makefiles: **four build invocations PASS, 59 freshness checks PASS**. The freshly linked root executable and frozen POST have byte-identical `.text` and `.rlfence` sections (`production-units-release.json`, `release-code-identity.json`).

The table preserves failed and superseded attempts. Counts are public gate rows, not individual assertions or unique tests; repeated prerequisites are included. Each job’s original ledger and Tcl assertion names are in `gate-summary.json`; raw text artifacts are preserved in `gate-receipts.tar.gz` with a hashed inventory in `gate-receipts.json`.

| Gate log in `docs/storefix5/` | Arm SHA prefix | Result | Disposition |
|---|---|---|---|
| `gate-asan-release-before-retirement.log` | `09367b85f035` | 9 ok / 6 FAIL | Preserved copy of the pre-retirement-fix attempt, not another run; superseded. |
| `gate-asan-release.log` | `09367b85f035` | 9 ok / 6 FAIL | ASAN build/five batteries/replyoff passed; six zc rows failed quiet-core preflight; serial retry below. |
| `gate-differ-epoll-final.log` | `d661aa5dc9cb` | 6 ok / 0 FAIL | Four matrices passed: 231/235/235/239 rows (940 total), plus mode equivalence. |
| `gate-differ-epoll-release.log` | `09367b85f035` | INCOMPLETE | First leg hit the 900-second watchdog under competing lane work; stopped and repeated serially. |
| `gate-differ-epoll.log` | `55b996cce85e` | INCOMPLETE | Stopped after the POST compiler control changed; superseded. |
| `gate-differ-uring-before-retirement.log` | `09367b85f035` | INCOMPLETE | Preserved copy of the pre-retirement-fix attempt, not another run; superseded. |
| `gate-differ-uring-final.log` | `d661aa5dc9cb` | 5 ok / 1 FAIL | Four matrices passed: 231/235/235/239 rows (940 total); mode equivalence rejected shared CPUs before boot; corrected harness retry below. |
| `gate-differ-uring-release.log` | `09367b85f035` | INCOMPLETE | First leg hit the 900-second watchdog under competing lane work; stopped and repeated serially. |
| `gate-differ-uring-serial.log` | `09367b85f035` | INCOMPLETE | Superseded after the retirement-ring defect was found: first 235-leg matrix passed; next matrix was stopped. |
| `gate-differ-uring.log` | `55b996cce85e` | INCOMPLETE | Stopped after the POST compiler control changed; superseded. |
| `gate-equivalence-uring-final.log` | `d661aa5dc9cb` | 2 ok / 0 FAIL | Mode equivalence passes with the guarded shared-CPU affinity fix; ordinary/performance callers still reject overlap. |
| `gate-eviction-final.log` | `55b996cce85e` | 9 ok / 0 FAIL | Completed selected jobs. |
| `gate-extra-final.log` | `d661aa5dc9cb` | 208 ok / 19 FAIL | 16 missing paired-witness failures, FIFO p99, FLUSH deadline, inherited stringlimit; separate reruns/controls below. |
| `gate-feature-product-final.log` | `d661aa5dc9cb` | 36 ok / 0 FAIL | All 35 feature cells pass, including the documented fused/flip refusal controls. |
| `gate-fifo-pre-final.log` | `59ad75c28b64` | 1 ok / 1 FAIL | Complete PRE control reproduces the p99 failure class; crossed fused outcomes remain unresolved as detailed below. |
| `gate-flush-deadline-post-final.log` | `d661aa5dc9cb` | 3 ok / 0 FAIL | Isolated POST: same complete job passes; earlier overlapping-run misses remain recorded. |
| `gate-flush-deadline-pre-final.log` | `59ad75c28b64` | 3 ok / 0 FAIL | Isolated PRE: both namespace rows, all eight legs each, pass the unchanged deadline. |
| `gate-fused-final.log` | `d661aa5dc9cb` | 153 ok / 0 FAIL | Completed selected jobs. |
| `gate-inventory-final.log` | `d661aa5dc9cb` | 108 ok / 1 FAIL | All other related jobs pass; notification eviction fixture hit its obsolete 16 KiB setup assumption; complete reruns below. |
| `gate-inventory-fused-final.log` | `d661aa5dc9cb` | 47 ok / 0 FAIL | Fused debug, SORT, reply suppression, ASAN and zero-copy jobs pass. |
| `gate-lfu-final.log` | `55b996cce85e` | 5 ok / 0 FAIL | Completed selected jobs. |
| `gate-live-final.log` | `d661aa5dc9cb` | 320 ok / 0 FAIL | Completed selected jobs. |
| `gate-live-release-before-retirement.log` | `09367b85f035` | 312 ok / 0 FAIL | Preserved copy of the pre-retirement-fix attempt, not another run; superseded. |
| `gate-live-release.log` | `09367b85f035` | 312 ok / 0 FAIL | Completed on the preceding POST; superseded by final-arm runs. |
| `gate-live.log` | `48650cec8e0d` | 312 ok / 8 FAIL | Eight eviction setup failures; corrected fixture reruns retained below. |
| `gate-native-final.log` | `d661aa5dc9cb` | 120 ok / 0 FAIL | Native jobs passed; storage_units is repeated below after strengthening the sampler-result assertion. |
| `gate-native-release-before-retirement.log` | `09367b85f035` | 120 ok / 0 FAIL | Preserved copy of the pre-retirement-fix attempt, not another run; superseded. |
| `gate-native-release.log` | `09367b85f035` | 120 ok / 0 FAIL | Completed on the preceding POST; superseded by final-arm runs. |
| `gate-notify-post-1s-final.log` | `d661aa5dc9cb` | 7 ok / 0 FAIL | Complete POST notification job passes with the accounted-cohort fixture; both atomic settings execute. |
| `gate-notify-post-2s-final.log` | `d661aa5dc9cb` | 7 ok / 0 FAIL | Complete POST notification job passes with the accounted-cohort fixture; both atomic settings execute. |
| `gate-notify-pre-1s-final.log` | `59ad75c28b64` | 7 ok / 0 FAIL | Complete PRE notification job passes with the accounted-cohort fixture; both atomic settings execute. |
| `gate-notify-pre-2s-final.log` | `59ad75c28b64` | 7 ok / 0 FAIL | Complete PRE notification job passes with the accounted-cohort fixture; both atomic settings execute. |
| `gate-pre-witness.log` | `59ad75c28b64` | 1 ok / 2 FAIL | Expected PRE failures in both mode rows; release build passed. |
| `gate-quiet-final-retry.log` | `d661aa5dc9cb` | 12 ok / 0 FAIL | ASAN build and five batteries, zero-copy release/ASAN, and split-local units passed serially. |
| `gate-quiet-final.log` | `d661aa5dc9cb` | NOT RUN (selection exited 2) | Selection exited 2 before any jobs: build-only prerequisites require consuming jobs; serial retry below. |
| `gate-quiet-release-before-retirement.log` | `09367b85f035` | 7 ok / 0 FAIL | Preserved copy of the pre-retirement-fix attempt, not another run; superseded. |
| `gate-quiet-release.log` | `09367b85f035` | 7 ok / 0 FAIL | Completed on the preceding POST; superseded by final-arm runs. |
| `gate-sampler-final.log` | `d661aa5dc9cb` | 13 ok / 0 FAIL | All storage rows pass with the strengthened selected-key visibility assertion. |
| `gate-store-extra.log` | `55b996cce85e` | 78 ok / 1 FAIL | One inherited rootcompat-stringlimit row fails; 78 rows pass. |
| `gate-stringlimit-pre.log` | `59ad75c28b64` | 1 ok / 1 FAIL | Same 24 above-32-bit representation assertions fail on PRE. |
| `gate-tcl-unfiltered-final.log` | `d661aa5dc9cb` | 1 ok / 2 FAIL | Exact same 10 keyspace + 2 string failures per mode as PRE; maxmemory has zero executed assertions. |
| `gate-tcl-unfiltered-pre.log` | `59ad75c28b64` | 1 ok / 2 FAIL | Per mode: 10 COPY/DEBUG DIGEST and two replication failures; maxmemory has no executed assertion. |
| `gate-tcl-unfiltered.log` | `55b996cce85e` | 1 ok / 2 FAIL | Same inherited Tcl assertion failures and external skips as PRE. |
| `gate-txn-pairing-final.log` | `d661aa5dc9cb` | 18 ok / 0 FAIL | All 18 rows pass after pairing the fresh native witnesses beside the frozen candidate. |
| `gate-units.log` | `48650cec8e0d` | 68 ok / 27 FAIL | Initial production-build watchdog; dependent missing-marker failures; rerun below. |

The FIFO live job retains its original p99 ≤ three derived FIFO cycles assertion. PRE and POST both ran all 16 sixty-second legs on the assigned shared eight-core geometry. They share 9 failing legs; 1 fail only on PRE and 1 only on POST. This demonstrates the baseline failure class but does **not** establish no regression for the crossed fused results. The FIFO row remains red/unresolved; no deadline or duration was changed. A maintainer check on the gate’s reviewed disjoint CPU geometry is still required before a timing no-regression claim. Receipts: `fifo-pre-post-final.json` and the raw gate logs.

| FIFO leg: databases / mode / atomic / engine | PRE | POST |
|---|---|---|
| 1 / 1s / 0 / epoll | PASS | FAIL: 3.009 > 2.197 ms |
| 1 / 1s / 0 / uring | PASS | PASS |
| 1 / 1s / 1 / epoll | PASS | PASS |
| 1 / 1s / 1 / uring | FAIL: 3.003 > 2.289 ms | FAIL: 3.013 > 2.343 ms |
| 1 / 2s / 0 / epoll | FAIL: 2.774 > 1.672 ms | FAIL: 2.738 > 1.625 ms |
| 1 / 2s / 0 / uring | FAIL: 2.914 > 1.675 ms | FAIL: 2.892 > 1.639 ms |
| 1 / 2s / 1 / epoll | FAIL: 2.759 > 1.585 ms | FAIL: 2.693 > 1.539 ms |
| 1 / 2s / 1 / uring | FAIL: 2.870 > 1.633 ms | FAIL: 2.899 > 1.634 ms |
| 16 / 1s / 0 / epoll | FAIL: 2.993 > 2.242 ms | PASS |
| 16 / 1s / 0 / uring | PASS | PASS |
| 16 / 1s / 1 / epoll | PASS | PASS |
| 16 / 1s / 1 / uring | PASS | PASS |
| 16 / 2s / 0 / epoll | FAIL: 2.678 > 1.613 ms | FAIL: 2.706 > 1.653 ms |
| 16 / 2s / 0 / uring | FAIL: 2.900 > 1.694 ms | FAIL: 2.880 > 1.666 ms |
| 16 / 2s / 1 / epoll | FAIL: 2.751 > 1.648 ms | FAIL: 2.721 > 1.641 ms |
| 16 / 2s / 1 / uring | FAIL: 2.894 > 1.673 ms | FAIL: 2.877 > 1.667 ms |

Frozen PRE and PAD-A both fail the RANDOMKEY all-shard sweep and idle-clock visibility witnesses in both modes. The frozen production-linked APPEND witness fails PRE with one merged scratch allocation and passes POST with zero (`append/pre-frozen-result.json`, `append/post-retirement-result.json`, `pad-final-{1s,2s}.json`).

### Maintainer measurement request

Use PRE, POST and PAD-A above, on the quiet box, with the gate's instrument.
Run the 14 unchanged generic cells in `docs/lbplanner/generic-cells.txt`:
`h05 h06 p8g p8s d1g_l0 d1s_l0 m8g_l0 v1g_l0 d128g_l0 d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`.
Add split 2s GET and SET at p1 and p32, with maxmemory 0 and 1 GiB/allkeys-lru,
16 shards and ratio 6:2, at the same offered load for every arm. Use the same
key/value population and connection count for all three arms; maxmemory-on
population must fit in POST without eviction for the ordinary-cost cells.
Record cycles/op, instructions/op, IPC and the gate's rate/tail score. The
verdict is matched-load rate/tail regression, not instruction count alone.
PAD-A matches the cold helper layout and aggregate text extent described above;
it does not match individual function placement.

Repeat the finite RANDOMKEY check at 1M keys and the one-byte APPEND curve at
16 B / 1 KiB / 64 KiB / 1 MiB / 4 MiB on a quiet box against Redis 7.4. Record
individual command latency and RSS/high-water changes; do not infer flat APPEND
cost or universal O(1) RANDOMKEY from the restricted fast path. For maxmemory,
compare used_memory, RSS/limit, accepted/refused/evicted counts and keys retained
at 30/100 MiB × allkeys-lru/noeviction × 100/1000 B in both modes. The decisive
memory result is that clock nodes are charged and admission respects that total;
RSS still includes explicitly unaccounted process/allocator headroom.

Finite-check command templates (repeat with each arm and both modes; PRE's
RANDOMKEY footprint assertion is expected to fail):

```sh
LC_ALL=C taskset -c 16-23 python3 tools/storefix5_checks.py --binary build/storefix5/POST --mode 2s --port 21600 --cases randomkey_footprint,append --output build/storefix5/quiet-post-2s.json
LC_ALL=C taskset -c 16-23 python3 tools/storefix5_memory.py quiet-post --binary build/storefix5/POST --port 21630
LC_ALL=C taskset -c 16-23 python3 tools/storefix5_memory.py quiet-redis --binary /home/user/Projects/redis/src/redis-server --redis --port 21630
```

For Redis's curve, use the first command with the oracle binary and `--redis`.
The memory helper covers the complete limit/policy/value matrix and both TomoKV
modes; its Redis matrix runs once because Redis has no split/fused mode.
