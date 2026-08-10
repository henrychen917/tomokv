# EX/worker cache-residency audit

Date: 2026-08-09  
Branch: `2s-audit-cacheex`  
Scope: source audit only. No build, server, benchmark, or test was run for this audit.

## Bottom line

The EX working set is not cache-resident, even in the 2M-key cell. That fact alone does **not** show
that misses limit throughput. Conversely, the existing evidence does **not** establish the skeptical
claim that storage misses are irrelevant:

1. At 2M keys over eight workers, the lower-bound index plus object footprint is about **23.1 MiB per
   worker** after online population, versus 1 MiB private L2 and a nominal 4 MiB share of L3. An RDB
   load makes it about **27.1 MiB per worker**. The 2M cell is already a DRAM-capable baseline, not a
   resident baseline.
2. Growing an already-nonresident random working set by 21x need not add misses per operation. A
   random GET can pay approximately the same one table/object chain at 2M and 48M keys. The measured
   3.5% loss rules out a growing capacity/bandwidth cliff, but not a fixed serialized miss on every
   GET.
3. The gate-open prefetch A/B did not prefetch a FLAT slot, stored `kvobj`, or value. In FLAT mode,
   `exPrefetchBatch()` reaches `PFS_HASH`, gets `NULL` from `kvstoreGetDict()`, and retires. Its live
   hints are request-side `fake`/`argv`/key-object hints (`src/server.c:20038-20321`). The recorded
   352-356M `pf_issued` per 15-second 8M-key arm is almost exactly three counted stages per GET, which
   is the reachable `STRUCT`, `ARGV`, and `KEYOBJ` sequence. The wash therefore says there is no
   useful request-operand-prefetch headroom; it does not test storage residency.

The correct present verdict is therefore **unproven, with a skeptical prior**. Do not merge a cache
policy or a larger prefetch pipeline on this evidence. First collect per-worker IPC plus the working
AMD demand-fill counters below. A clean result in which DRAM fills change but cycles/op do not is the
desired, useful “there is no residency headroom” result.

Two changes have value independent of that verdict:

* reuse the full XXH64 already carried from dispatch instead of hashing the key again in the FLAT
  lookup; and
* stop RDB pre-sizing from turning a 2M-key table into 64 MiB when the same live set produced online
  uses 32 MiB.

## Hardware facts that affect interpretation

The verified LLC is 32 MiB, 64-byte lines, 32,768 sets, 16 ways. One way is therefore nominally 2
MiB. All eight physical cores share it. L2 is 1 MiB/2,048 sets/8 ways and private per physical core;
L1d is 32 KiB/64 sets/8 ways.

There is an important topology confound in the stated placement. Linux reports CPUs `0,8` as SMT
siblings, likewise `1,9`, and so on. A server on logical CPUs 0-7 and a local generator on 8-15 share
the same eight physical cores, including L1d, L2, and execution resources. That placement is useful
for saturation, but it cannot distinguish EX issue pressure from sibling issue/cache interference.
Use a remote generator for the decisive counter run. If the generator must remain local, physical
cores must be divided between the two roles; there is no placement that gives both roles eight
separate physical cores on this CPU.

The “4 MiB per worker” number below is only `32 MiB / 8`. It is not enforced, and it is optimistic:
IO threads, network buffers, code, and the local load-generator siblings all use the same LLC.

## 1. FLAT table

### Slot and tag

`flatSlot` is exactly one atomic 64-bit word (`src/flatstore.h:22-52`):

```
63                         49 48 47                                  0
+----------------------------+--+-------------------------------------+
|       XXH64 high tag (15)  | T| masked kvobj pointer / encoding (48)|
+----------------------------+--+-------------------------------------+
```

Eight slots fit in a cache line. Empty is the all-zero word; a tomb is nonzero with no pointer.
Lookup starts at `h & (size-1)` and linearly probes until an empty slot
(`src/flatstore.c:185-215`).

The tag check is effective; the layout does not defeat it. The tag and pointer arrive in the same
slot-word load. A nonmatching tag never dereferences the `kvobj`. Only a live, matching 15-bit tag
does `dictGetKV()`, `kvobjGetKey()`, `sdslen()`, and `memcmp()`
(`src/flatstore.c:177-194`). With a uniform hash, an unrelated live probe becomes a false candidate
with probability 1/32,768. At the 2M online load, that is on the order of 1e-5 false `kvobj`
dereferences per operation; even at 70% load it remains negligible. A wider tag or separate control
array cannot repay another load or more slot bytes.

The ordinary GET path does not call `flatGet()`. `dbFindByLink()` calls
`kvstoreDictFindLink()`, whose FLAT arm calls `flatFindForWrite()` and returns a pointer to the slot
word (`src/db.c:4091-4102`, `src/kvstore.c:1060-1069`). On a hit, `flatFindForWrite()` has already
loaded and decoded the word to compare the key, and `dbFindByLink()` loads the same warm word again
through `*link`. This adds an instruction/load, not another cache line.

### Table sizes and probe lengths

`FLAT_MIN_SIZE` is 262,144 slots. At 8 bytes/slot that is **2 MiB**, not the 4 MiB claimed by the
comment at `src/flatstore.h:34`. The creation comment that still says `256K * 16B = 4MB` is stale for
the same reason.

For 2,000,000 live keys:

| construction | slots | bytes | live load |
|---|---:|---:|---:|
| normal online growth | 4,194,304 | 32 MiB | 47.68% |
| RDB `kvstoreExpand(newsize * 3)` | 8,388,608 | 64 MiB | 23.84% |
| resize trigger, for reference | n/a | n/a | 70% used+tombs |

The RDB difference comes directly from `src/kvstore.c:528-542`: 2M is multiplied by three, then
rounded up to the next power of two. Online growth instead arrives at 4M slots.

For uniform hashing and no tombs, the standard linear-probing expectations are
`0.5*(1 + 1/(1-a))` probes for a hit and `0.5*(1 + 1/(1-a)^2)` for an unsuccessful lookup. Averaging
the starting slot within an eight-slot line gives approximately `1 + (probes-1)/8` cache lines:

| load | hit probes / slot lines | miss probes / slot lines |
|---:|---:|---:|
| 23.84% (current RDB) | 1.16 / 1.02 | 1.36 / 1.05 |
| 47.68% (online 2M) | 1.46 / 1.06 | 2.33 / 1.17 |
| 70% trigger | 2.17 / 1.15 | 6.06 / 1.63 |

Tombs lengthen unsuccessful searches, so `used`, `tombs`, and observed probe tails must be reported
with any measurement. The source currently exposes batch/resize counters but not table size, load,
probe distributions, or tag candidates.

### Cache lines for a GET

There is no honest single count for the whole command without declaring which control structures
are assumed warm. The fake client alone spans many lines, and stats, clocks, queue words, reply
metadata, and code are additional fixed work. The useful source-counted lower bounds are:

* **FLAT storage lookup, hit, 32-byte value:** three key-dependent data lines after the table header
  is warm: one home/probe line and two lines of the stored `kvobj` allocation for a normal key. The
  theoretical smallest key/value pair can fit the `kvobj` in one line, making two storage lines, but
  the 32-byte benchmark value plus a key of at least two bytes exceeds 64 bytes in this layout.
* **FLAT storage lookup, miss:** one slot line in the minimum case and about 1.17 at the 2M online
  load. It normally touches no stored object at all. This is exactly what the tag buys.
* **Payload path, hit:** add one request-key object/byte line and one reply-buffer destination line,
  giving a five-line lower bound for the 32-byte cell. These five are the lines whose residency can
  vary by key.
* **Full worker path:** also touches the `argv` vector, at least two fake-client lines (the current
  prefetcher explicitly names both), the padded per-worker owner-lock line, and the `redisDb`,
  `kvstore`, and `flatTable` control allocations. Those are normally L1/L2-hot fixed overhead. Thus
  the full routine touches at least roughly a dozen data lines, plus stats/clock/queue lines; calling
  all of those “cache misses” would be wrong.

The semantically unavoidable variable lines are the request key bytes (hash and exact comparison),
one slot line, enough of the stored key to reject a 15-bit collision, the returned value bytes, and
the reply destination. The second stored-object line is unavoidable in the current 24-byte-header
layout for the 32-byte cell, but not fundamental to a KVS. The owner-lock and control lines are
unavoidable only under this implementation and should remain hot.

On a hit, the dependency chain is:

```
fake -> argv -> request robj -> key bytes -> hash
     -> db -> kvstore -> flatTable -> slot word -> kvobj/header+stored key
     -> kvobj->ptr -> embedded or separate SDS/value -> reply buffer
```

The stored-value pointer is still a dependent load even when it points back inside the same
allocation. A RAW/nonembedded value adds a separate dependent allocation. The hit path also writes
`val->lru` under the normal policy (`src/db.c:308-323`), so the header line is acquired writable,
not merely read.

## 2. `kvobj` / `robj` / SDS layout

On LP64, `struct redisObject` is now **24 bytes**, by layout:

| offset | bytes | contents |
|---:|---:|---|
| 0 | 8 | two 32-bit bitfield words: type/encoding/refcount/`iskvobj`, then metadata/LRU |
| 8 | 8 | `ptr` |
| 16 | 8 | `vmeta` |

The examples in `src/object.c:157-164` and `:215-223` still label it 16 bytes and are stale. The
unconditional `vmeta` pointer was added for lazily allocated atomic version state
(`src/object.h:151-167`), but it occupies space even when `tomokv-atomic` is off.

A stored embedded string is laid out as:

```
24B redisObject | 1B key-SDS-header-size | key SDS | value SDS_TYPE_8
```

For a short SDS5 key of length `K` and value length `V`, with no expiry/module metadata, the exact
requested size is:

```
24 + (K + 3) + (V + 4) = 31 + K + V bytes
```

For `V=32`, that is 71 bytes at `K=8`, 72 at `K=9`, 78 at `K=15`, and 80 at `K=17`. Under the normal
jemalloc size classes, all of those use an 80-byte allocation. Removing the eight-byte `vmeta`
field would make the request `23 + K + V`; this changes the allocator class only for particular key
length bands. For `V=32`, keys `K<=9` fall from 80 to 64 bytes, while `K=10..17` remain in the
80-byte class. Therefore “remove `vmeta` saves 32 MiB” is only a best case, not a valid estimate
without the key-length/usable-size histogram:

* logical saving: 8 bytes/key = 16 MB over 2M keys;
* allocator-resident saving: 16 bytes/key = 32 MB only when the request crosses a size-class edge;
* allocator-resident saving for `K=10..17`, `V=32`: approximately zero, though fields move eight
  bytes earlier.

The 64-71 byte boundary is an allocator/cache-line boundary, not the current embedding cutoff. The
fork raised stored-string embedding to 192 requested bytes and guards the one-byte value length
(`src/object.c:291-303`). `SET`/MSET can also copy a RAW parsed value into the stored object. The
current no-metadata condition is `31 + K + V <= 192`, so the maximum embedded value is
`V <= 161-K`. A 32-byte value is embedded for every relevant short key. Request `robj` strings still
use the normal 44-byte EMBSTR threshold.

For an embedded GET, the first stored-object line supplies type, encoding, `ptr`, null `vmeta`, and
at least part/all of the stored key. The reply then consumes the value, which extends into the
second line for the benchmark layout. For a RAW value, the `ptr` leads to another allocation and at
least one more dependent line.

## 3. Per-worker footprint at 2M keys / eight workers

Assume uniform ownership, 250,000 keys/worker, short keys that keep `31+K+32 <= 80`, no key metadata,
and the normal 80-byte usable allocation. These are lower bounds, excluding allocator slab/page
overhead, transient request objects, queues, fake clients, reply/network buffers, code, expires,
and collections.

| component | online population | RDB population |
|---|---:|---:|
| stored objects (`250k * 80`) | 19.07 MiB | 19.07 MiB |
| worker's 1/8 home-table region | 4.00 MiB | 8.00 MiB |
| retained QSBR node pool | up to 0.0625 MiB | up to 0.0625 MiB |
| lower-bound total | **23.13 MiB** | **27.13 MiB** |
| private L2 multiple | 23.1x | 27.1x |
| nominal 4 MiB L3-share multiple | 5.8x | 6.8x |

Across the node, the objects alone are about 152.6 MiB (160 MB decimal); adding the online/RDB
table gives about 184.6/216.6 MiB before overhead. The recorded 243 MB RSS at 2M is therefore
credible. If attributed evenly across the requested eight-owner model, it is about 30.4 MB/owner,
or 7.6 nominal L3 shares; RSS also contains IO/network state, so that division is context rather than
an object-residency measurement. In an io4/ex4 run there are only four EX owners, and the key/table
portion per EX owner is roughly twice the eight-owner numbers above even though IO still competes
for LLC.

This proves nonresidency, not miss criticality. It also explains why 2M-to-48M scaling is a weak
latency discriminator: the small endpoint was already far outside LLC. At two 64-byte DRAM fills per
GET, 2M GET/s is only about 256 MB/s per worker, or about 2 GB/s for eight workers. That can be
latency-limited while remaining far from a system bandwidth cliff, so flat throughput versus dataset
size is not surprising either way.

## 4. Power-of-two indexing and conflict misses

Globally, XXH64's low bits are well avalanched, and `h & mask` distributes home slots across the
whole power-of-two table. The power of two does **not** by itself concentrate the node's accesses on
a subset of logical lines.

There is a per-worker correlation. Ownership is `h & ((1<<14)-1)`, while the home slot also uses low
hash bits. With eight equal, aligned ownership ranges, each worker owns 2,048 consecutive buckets,
so hash bits 11-13 are fixed for that worker. A table cache-line index consumes hash bits 3 upward.
Under a simple, un-hashed mapping from table-line number to LLC set, those three fixed bits mean one
worker addresses 4,096 of 32,768 sets:

| table | logical lines/worker | selected sets | table aliases/selected set |
|---|---:|---:|---:|
| 32 MiB | 65,536 | 4,096 | **16** |
| 64 MiB | 131,072 | 4,096 | **32** |

The 32 MiB table has 524,288 lines total, exactly the LLC's `32,768 sets * 16 ways`; the 64 MiB table
has twice that. At 47.7% independent slot occupancy, about
`1-(1-.477)^8 = 99.4%` of slot lines contain at least one live slot, and uniformly distributed home
lookups can address the whole table anyway. Thus the table has a real **capacity/way pressure**
problem: 16 or 32 logical table lines per set before objects and network buffers.

That arithmetic is not proof of physical set conflicts. The LLC is physically indexed and AMD may
hash address bits; normal malloc pages are not guaranteed physically contiguous. Across all eight
workers, the logical table traffic also covers all 32,768 sets and still totals 16 or 32 lines/set.
Rotating/selecting different hash bits would spread each worker over more sets but would not reduce
the aggregate table lines or aliases per set. It may merely replace “16 lines from one worker” with
“two lines from each of eight workers.”

Therefore a bit-selection change is not justified. A temporary rotated-index A/B is useful only if
PMU/IBS first shows slot-line misses are material and it keeps table bytes/load identical. A shipped
rotate adds work and forces a rebuild but has no quantitative aggregate-capacity win. A 16-byte slot
is strictly worse: it doubles the 2M online/RDB tables to 64/128 MiB. A four-byte base-relative slot
could halve the table and the lines/set, but it requires a constrained object arena/pointer scheme
and is far too invasive before a slot-miss result exists.

## 5. QSBR retirement and atomic version bags

### Ordinary FLAT QSBR

`flatRetireNode` is 16 bytes and the worker-local recycled pool is capped at 4,096 nodes, exactly 64
KiB/worker (`src/flatstore.h:54-77`). That retained maximum is 512 KiB over eight workers.

The flexible `flatBatch` header is 24 bytes plus
`(2 * flat_batch_slots + flat_batch_mask_words) * 8`, where
`flat_batch_slots = io_threads + workers + 1`. For an io4/ex4 process this is 176 bytes. Up to eight
headers are retained per worker, about 1.4 KiB/worker in that example
(`src/flatstore.h:80-96`, `src/server.c:8178-8220`).

An overwrite/delete temporarily retains one 16-byte node plus the old object. For the common
80-byte object that is about **96 bytes per outstanding retirement**, plus amortized batch headers,
until the grace passes. On the worker path the node is pushed onto a private list with no atomic RMW
(`src/flatstore.c:148-162`). Reclamation later walks/frees those cold old objects on the same worker.

A pure GET allocates and retires nothing. With no pending batches, `flatWorkerReclaim()` only checks
worker-private pointers; it does not walk cold retirement memory (`src/server.c:8312-8337`). QSBR
does impose fixed per-slice work: a release `loop_seq` update and seq_cst
`in_flat_section` enter/exit (`src/server.c:20634-20683`, `:21176-21179`). Those stores are amortized
over the popped batch, not inherently per command. On a write pass, closing a batch snapshots worker
sequences and any pinned IO epochs, and readiness reads other workers' lines; that is not on the
minimum GET path.

Existing INFO reports batches closed/freed/pending, but a batch count is not a byte count. For churn,
the missing observables are pending retire-node/object bytes, pool high-water, and oldest grace age.
Collect them per batch or on INFO, not with an atomic counter on every retire.

### `tomokv-atomic`

`tomokv-atomic` defaults off (`src/config.c:3186-3187`), but every object still pays the header
pointer described above. When enabled, each physical version gets a separately allocated
`tomoVerMeta` (`src/db.c:443-464`). LP64 layout makes it 120 requested bytes, normally 128 usable:

* 16 bytes for sequence and committed-head atomics;
* 16 bytes for order/state/owner-pending plus padding;
* five pointers (40 bytes); and
* two 24-byte `tomoOwnerOp` records.

The direct incremental storage is therefore about **128 bytes metadata + the new object** per live
version, before old objects, retire nodes, group records, and grace lag. As a scale example, a full
512-group admission window of MSET8 can represent 4,096 installed versions: about 512 KiB of metadata
and 320 KiB of 80-byte objects, roughly 0.8 MiB direct before group/QSBR overhead. This is an example,
not a hard bound; group width is variable.

An ordinary read sees null `vmeta` in the already-required object header and adds no metadata line.
A read that lands on a transient bag adds a dependent metadata line, a committed/version predecessor
load, and potentially another version object's header/value for each step
(`src/object.h:188-245`). Retirement ultimately goes through the same QSBR machinery. The transient
bag is not the dominant 2M-key resident set; the unconditional eight-byte pointer can be, but only
when it changes allocator classes.

## 6. What 500 ns/op can plausibly contain

At 2.0M ops/s, a worker has about 500 ns/op. The exact cycles/op must come from the PMU because boost
frequency varies. At roughly 5.0-5.5 GHz, the budget is about 2,500-2,750 cycles. One fully exposed
70-100 ns dependent DRAM access would consume roughly 350-550 cycles, or 14-22% of that budget. A
slot miss followed by a `kvobj` miss can therefore matter; batching/MLP and out-of-order execution can
hide some or all of it. Miss counts alone cannot be multiplied by nominal latency and called stalls.

There is also substantial fixed work: a padded uncontended atomic owner lock per command
(`src/server.c:8755-8772`), fake/argv/reply bookkeeping, two command timing/stat paths, LRU/header
writes, branches, and the redundant XXH64. Repository notes put a prior short-key hash optimization
at only about 40 of roughly 5,100 instructions/op (`NUMA_SHARED_KV_PLAN.md:228-237`). That makes an
issue-bound result entirely plausible. It does not distinguish it from one overlapped or serialized
miss; IPC plus source-qualified fills does.

Do **not** use or propose `stalled-cycles-backend` on this Zen part. It is unsupported and, even where
available, is too coarse for this question.

## 7. Measurement that works without resctrl

This is a future measurement design; none of it was run during this audit.

### Experimental controls

1. Use a remote load generator. Pin the server as before and record each EX TID.
2. Measure a genuinely resident endpoint, not only 2M versus 48M. About 32K total short-key/32-byte
   items gives each of eight EX owners roughly 305 KiB of objects plus 256 KiB of the 2 MiB minimum
   table, a defensible sub-L2 working set. For io4/ex4 use 16K or less for the same property. In
   general choose `N` so `N/W * object_usable_bytes + FLAT_MIN_SIZE*8/W < 1 MiB`. Use that endpoint,
   then 2M, 8M, and 48M uniform-hit cells.
3. Add a uniform negative-GET cell. It exercises request/hash/table/reply but normally no `kvobj`;
   hit-minus-miss counter deltas help identify object/value fills. Keep key lengths and reply mode
   controlled.
4. Fix `tomokv-prefetch-ex=0` for the base residency comparison. Report table slots/used/tombs and
   seed method. Alternate arms, discard warm-up, and use equal-duration saturated windows.
5. Poll `DEBUG RESHARD PERWORKER` before and after each window and normalize every event by that
   worker's own `ops_total` delta (`src/server.c:16195-16206`). Do not divide a process-wide event by
   aggregate throughput.

### PMU event groups

Attach `perf stat` to one worker TID at a time. Run separate repeat windows if the group would
multiplex; require `time_running/time_enabled` near one.

An attachment template is `perf stat -t EX_TID -e EVENT_LIST -- sleep WINDOW`; take the worker's
`ops_total` snapshots outside the timed interval and replace the placeholders explicitly. Do not
launch the server under `perf`, because that mixes initialization/RDB load with the command window.

Instruction/issue group:

```
cycles,instructions,branches,branch-misses
```

Demand-data group available in this machine's `perf list`:

```
l2_request_g1.all_dc
l2_cache_req_stat.dc_hit_in_l2
l2_cache_req_stat.ls_rd_blk_c
ls_dmnd_fills_from_sys.local_l2
ls_dmnd_fills_from_sys.local_ccx
ls_dmnd_fills_from_sys.dram_io_near
ls_dmnd_fills_from_sys.all
```

Use subsets in repeated windows rather than silently multiplexing. On this one-CCD/single-NUMA box,
`local_ccx` means the shared L3 or another L2 in the same CCX, while `dram_io_near` is the relevant
DRAM/MMIO source. Also run `ls_l1_d_tlb_miss.all` and
`ls_l1_d_tlb_miss.all_l2_miss` in a separate TLB window for the 48M case.

Do not label generic `cache-misses` as LLC misses here: sysfs maps it to raw
`cpu/event=0x64,umask=0x09/`, in the L2 request-status family. Use the named demand-fill events.

If permissions allow, sample the same worker with `ibs_op/l3missonly/`. The installed IBS PMU
exposes `l3missonly`, `cnt_ctl`, `swfilt`, and Zen4 extensions. Use symbolized sampled IP/data-source
and latency/weight fields provided by this kernel to determine whether long-latency operations land
in `flatFindForWrite`/`flatKeyMatch`, value/reply copy, or unrelated queue/bookkeeping code. IBS is
attribution; the normalized counting events remain the quantitative total.

### Decision rule

Compare per-worker instructions/op, cycles/op, IPC, L2 misses/op, `local_ccx` fills/op, and near-DRAM
fills/op:

* **No cache headroom:** 32K -> 2M/48M materially raises DRAM fills/op, but cycles/op and IPC stay
  flat within paired noise; or DRAM fills/op are already very low. Misses are overlapped/noncritical.
  Stop cache-layout/prefetch work.
* **Latency evidence:** instructions/op stays flat, cycles/op rises, IPC falls, near-DRAM fills/op
  rise, and IBS assigns the long-latency samples to slot/`kvobj`/value loads. Then test a causal
  footprint or storage-prefetch change.
* **Issue evidence:** cycles/op tracks instructions/op while DRAM fills/op and IBS latency remain
  flat/low. Work on hash, lock/timing, fake/reply, and instruction count instead.
* **TLB evidence:** only the very large datasets raise page walks/cycles. That explains the 3.5%
  tail without making FLAT/object LLC residency the lever.

The strongest no-resctrl causal comparison already available is the same 2M live set built online
(32 MiB table) versus loaded through RDB (64 MiB table). It changes table capacity by one whole LLC.
Seed-path allocator differences must be recorded, but if it changes table/DRAM fills and not
cycles/op, table residency has no throughput headroom.

## 8. What resctrl adds after a root-assisted mount

Without a mount, RDT feature flags do not provide measurements. With root mounting resctrl:

* CQM monitoring groups can assign RMIDs to EX TIDs and IO TIDs separately and read
  `llc_occupancy`, `mbm_total_bytes`, and `mbm_local_bytes`. This measures role/worker occupancy and
  bandwidth without source instrumentation. On one NUMA node, local and total MBM should nearly
  agree.
* CAT can make capacity causal. The LLC has 16 nominal 2 MiB ways. Keep IO in a fixed disjoint mask
  and sweep EX through, for example, 4/8/12 ways (8/16/24 MiB), with warm-up after each change. Pair
  throughput with the same PMU fills. If EX misses fall from 4 to 12 ways but cycles/op do not, that
  is a direct no-headroom result.
* A uTPS-style role experiment can compare shared `ffff` masks against disjoint masks such as 12
  ways for EX and four for IO, then an 8/8 split. It tests network-buffer/index interference on this
  one shared LLC. Thread separation alone does not provide it.

CQM occupancy is not a hit-rate or stall counter, CAT partitions can hurt either role, and neither
identifies a source line. Keep PMU/IBS in the experiment. CAT also cannot conjure eight private 4 MiB
worker slices plus IO space from 16 ways; role-level partitions are the sensible first test.

## 9. Ranked proposals

### Rank 1 — reuse the dispatch-carried full hash

**Mechanism.** `getWorkerForCommand()` computes XXH64 and stores both the bucket and full
`tomo_key_h` on the fake (`src/server.c:8684-8706`, `src/server.h:2003-2011`). `getKeySlot()` reuses
the bucket, but the FLAT arm of `kvstoreDictFindLink()` recomputes full XXH64
(`src/kvstore.c:1060-1066`). Pass a guarded full hash through `dbFindByLink`, or add a FLAT
find-with-hash API. Guard it with the same exact SDS-pointer match used for the bucket so multi-key
and non-dispatch callers fall back safely.

**Estimated size.** Zero new persistent bytes and no new client field. Saves one short-key XXH64 per
single-key lookup; likely tens of instructions, not hundreds.

**Confirm/refute.** A/B instructions/op, cycles/op, and throughput with the PMU group above. Success
is lower instructions/op with a repeatable cycles/op/rate improvement; unchanged rate with lower
instructions still documents spare issue headroom.

**Cost when it does not help.** One pointer guard/API branch and maintenance of two call forms. Keep
the fallback; do not introduce a TLS hash table or another cache line. Expected throughput gain is
small, but this is the highest-EV code change under the overhead-bound prior.

### Rank 2 — compact RDB pre-sizing to the online table class

**Mechanism.** Replace the `newsize * 3` policy with a target that leaves the final load safely below
70% but selects 4M, not 8M, slots for 2M keys. A 2x target gives at most 50% final load before
power-of-two rounding and matches the online table class. Preserve overflow checks and report the
chosen table size.

**Estimated size.** Saves exactly **32 MiB node-wide / 4 MiB per worker** at 2M keys loaded through
RDB. It saves 8 bytes for every eliminated slot and one full LLC of table capacity. It does nothing
for an already-online-built 32 MiB table.

**Confirm/refute.** Compare same-data RDB arms at 64 versus 32 MiB using hit/miss probe counters,
IPC, fills/op, cycles/op, RSS, and load time. Expected ideal hit probes rise only from about 1.16 to
1.46 and usually remain in one line; negative misses rise from 1.36 to 2.33 slots.

**Cost when it does not help.** Slightly more probe/branch work, most visible for negative GETs or
tomb-heavy churn. Throughput may be neutral under the prior, but the 32 MiB RSS saving is real. Do
not apply the change without a miss/tomb regression arm.

### Rank 3 — add low-cost residency observability before policy

**Mechanism.** Expose FLAT slots/used/tombs/bytes in INFO at no lookup cost. For a measurement build,
add worker-private, sampled probe counts: hit/miss probes, crossed slot lines, tag candidates, exact
candidates, and tail maximum. Add pending retire objects/bytes and oldest grace age per batch. Split
prefetch issue counts by stage; the aggregate `pf_issued` cannot say whether storage was touched.

**Estimated size.** Existing table fields need no extra storage. A compact worker-private counter
block is about one or two 64-byte lines per worker. Sampled probe state can be one counter/branch per
1,024 operations; keep exact per-probe counting out of production.

**Confirm/refute.** Cross-check sampled mean/p99 probes against the ideal table above and correlate
stage counts with PMU fills. A high tag-candidate count would falsify the hash assumption; expected
result is approximately 1e-5 false candidates/op.

**Cost when it does not help.** Even a predictable sampling branch matters on a ~500 ns path. Measure
its instructions/op and compile it out or default it off after the campaign. INFO-only fields have
no command-path cost.

### Rank 4 — conditionally remove `vmeta` from ordinary object headers

**Mechanism.** Keep a 16-byte ordinary `redisObject` and represent version metadata only on
versioned `kvobj`s, for example as a flagged prefix/metadata word allocated with the versioned
object. Atomic install already creates a new physical version; ordinary GET should need only a bit
test. Avoid a side hash lookup on every GET.

**Estimated size.** Guaranteed logical reduction is 8 bytes/object (16 MB over 2M), but usable RSS
falls only at allocator-class boundaries. Best case in the 32-byte cell is 16 usable bytes/key = 32
MB / 4 MB per worker; for keys `K=10..17`, it is approximately **zero usable bytes**. Measure the key
and `zmalloc_size` histogram first. Versioned objects retain the pointer/prefix cost; transient
request `robj`s may also shrink in favorable classes.

**Confirm/refute.** First predict class transitions from the live key-length/allocation histogram.
Then A/B RSS, fills/op, IPC/cycles/op, and GET rate with atomic off. Separately run atomic MSET8
admission, old-snapshot/bag traversal, cancellation, and QSBR-grace performance/correctness.

**Cost when it does not help.** High code and correctness risk across object allocation, metadata
prefix recovery, defrag/free, atomic install, and retirement. If the live keys remain in the same
size class, it buys almost no residency. This will **not pay for the common 32-byte cell if its keys
are predominantly 10-17 bytes**; do not implement from the 16 MB logical number alone.

### Rank 5 — only after PMU evidence, add FLAT storage stages to the batch prefetcher

**Mechanism.** In the FLAT arm, reuse guarded `tomo_key_h`, prefetch
`&table->slots[h & mask]`, rotate across the worker batch, then optionally inspect a matching home
tag and prefetch the candidate `kvobj`/value. The enclosing flat section already prevents table
free/resize. Keep collision tails on the normal probe. This is distinct from the measured operand
prefetch wash.

**Estimated size.** At a 32-command batch, home slots introduce up to 32 lines/2 KiB in flight;
candidate headers add up to another 2 KiB. Scratch hashes/pointers are a few hundred stack bytes.
Runtime cost is one or two prefetch instructions and FSM visits per hit.

**Confirm/refute.** Do it only if baseline near-DRAM fills and IBS identify the slot/object chain.
Run level-0 versus storage-stage arms on one live dataset, report per-stage issues, fills/op,
instructions/op, cycles/op, and rate. A useful arm must reduce cycles/op, not merely demand misses.

**Cost when it does not help.** Issue bandwidth, front-loaded batch latency, line-fill-buffer use,
and cache pollution. The existing request-side arm is already a wash; absent PMU evidence this is
speculation and likely worth at most a few percent. Do not build candidate/value chasing first.

### Rank 6 — use CAT as an experiment, not a default partition

**Mechanism.** With a root-mounted resctrl filesystem, compare shared ways with role-disjoint and EX
capacity-sweep masks while CQM/MBM and PMU run.

**Estimated size.** Each allocated way is 2 MiB. A 12/4 EX/IO split gives 24/8 MiB; an 8/8 split
gives 16/16 MiB. This reserves capacity rather than reducing memory.

**Confirm/refute.** A throughput/cycles improvement from disjoint masks at equal offered load is
direct evidence of role interference. Occupancy changes without cycles/op changes refute useful
headroom.

**Cost when it does not help.** Root/operational complexity and forced under-capacity for one role.
On a single 16-way LLC, a permanent partition can easily be worse than shared replacement. Do not
ship a mask based only on the uTPS result from different software/hardware.

## 10. Proposals that will not pay on present evidence

* **Different FLAT index bits:** no aggregate lines/set or byte reduction, physical set mapping is
  unproven, and it adds/rebuilds work. Use only as a temporary conflict diagnostic after PMU evidence.
* **A 16-byte slot or a separate wide tag array:** doubles/expands the dominant table to save a false
  `kvobj` dereference that occurs on the order of 1e-5 per positive lookup in the 2M online table. It
  will not pay.
* **More request-side prefetch:** this is what the gate-open wash measured. It will not pay on this
  box.
* **A software per-worker hot-item cache for uniform GET:** a 256 KiB cache with 16-byte entries holds
  16,384 of 250,000 keys, a maximum uniform hit rate of 6.6%, while every command pays another lookup
  and invalidation/versioning logic. The direct FLAT probe is already one dense line. It will not pay
  for the uniform cells; Zipf/tree workloads are a separate experiment, and uTPS's reported hot-set
  separation was only 1.08x on a tree.
* **Permanent CAT partitioning without the capacity curve:** thread separation is not way
  separation, but the one-CCD result cannot be imported from uTPS. Measure; otherwise shared ways are
  the safer default.

## Final assessment

The code establishes a large resident-set mismatch and a plausible two-stage slot-to-object demand
chain. It does not establish that those misses consume the worker's 500 ns budget. The prior evidence
that was supposed to establish “overhead-bound” is incomplete: both dataset endpoints are already
nonresident, and the engaged prefetch counter proves request-side activity, not FLAT storage
prefetching.

The next decision should be made from normalized per-worker IPC and AMD demand-fill sources, with a
truly resident 32K endpoint and a remote generator. If cycles/op stays flat while fills/op changes,
stop: there is no cache-residency headroom on this box. If cycles/op rises with near-DRAM fills and IBS
lands in the FLAT/`kvobj` chain, start with the zero-footprint hash reuse and the one-LLC RDB table
reduction before considering storage prefetch or object-layout surgery.
