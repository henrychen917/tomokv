# IO-thread cache-residency audit

## Bottom line

The source does **not** support a claim that LLC capacity is the current ceiling.
It supports a narrower claim: at pipeline depth 32 and 200 connections, the IO
layer allocates substantially more than a private 1 MiB L2 per IO thread, and the
same fake-client lines move between IO and EX cores.  That makes residency and
coherence measurable concerns, but it does not make them throughput limiters.

For the reference `io4/ex4`, 200-connection, depth-32 GET workload, I derive:

* 50 real connections and 1,600 live fake clients per IO thread;
* **5,106,928 B (4.87 MiB)** of small-GET-path data-plane allocation per IO thread
  before event-loop scaffolding;
* about **5,279,104 B (5.03 MiB)** including the initially allocated epoll/event
  arrays;
* a source-derived **1.7--2.0 MiB central estimate of demand-touched data** during a
  full small-GET pipeline wave.  This is an estimate, not a measurement of resident
  cache lines.

The 5.03 MiB allocation envelope is 5.0 times a 1 MiB L2 and 1.26 times a nominal
4 MiB eighth of the 32 MiB L3.  The 4 MiB comparison is only a yardstick: without
CAT, this processor does not enforce equal L3 shares.  The estimated active set is
larger than L2 but smaller than that nominal L3 share, so the likely steady-state
failure mode is L2 cycling, L3 hits, and ownership transfers—not automatically
DRAM misses.

The dominant single allocation class is the 1,600 full `client` objects used as
fake clients: **2,048,000 B of jemalloc usable space per IO thread**.  The complete
fake ring (fake clients, their buffers, and reply-list headers) is 3,763,200 B,
about 71% of the 5.03 MiB envelope.

There is no cheap layout or buffer-size change that puts the aggregate hot set for
50 connections under 1 MiB while preserving depth 32.  Shrinking the 1 KiB fake
buffers would cut allocation by 1.37 MiB but generally not remove even one
demand-touched cache line per small reply.  Reducing effective depth to about 8, or
connections to about 25 per IO thread, could put the estimated hot set below L2,
but both remove concurrency that the current workload uses.  I do not expect those
changes to improve the reference result.

This agrees with the skeptical prior already measured in this tree:

* per-worker throughput remains about 2.0 Mops/s across `io4/ex4`, `io5/ex3`, and
  `io6/ex2` (`docs/ABCD_D_DESIGN.md:346-350`);
* increasing the dataset 21-fold costs only 3.5% (`docs/ABCD_D_DESIGN.md:339`);
* group prefetch is flat at 8M x 32 B even though its gate is open for 97.8% of
  batches (`docs/ABCD_D_DESIGN.md:267,297`).

My prior after this audit is therefore: **there is probably little or no LLC
capacity headroom in the current small-value workload**.  The one cheap source
change worth an A/B is worker-striped completion buses on this single-CCD machine,
because private L2 ownership—not L3 capacity—makes the current single shared bus
questionable.  Do not merge even that on source reasoning alone.

## Method and scope

I traced the default epoll receive, parse/dispatch, worker completion, reply splice,
and write paths.  I did not compile or run any program, test, server, or benchmark,
per the measurement exclusion in the task.  Structure sizes below are manual
AMD64 SysV ABI derivations from this checkout, under the tree's normal build
without `LOG_REQ_RES`.  Jemalloc usable sizes use the configured 8-byte quantum
(`deps/Makefile:148`) and its size classes.  A build-time option that changes a
structure must be re-accounted.

“Allocated,” “touched,” and “resident” are deliberately separate:

* **allocated envelope** is derivable from source and allocator classes;
* **demand-touched estimate** counts cache lines the normal small-GET path appears
  to read or write in a full pipeline wave;
* **resident bytes** are dynamic and cannot be derived from C declarations.  They
  require CQM or a controlled cache-counter experiment.

The arithmetic uses the requested 200 total connections, `io4`, depth 32, and the
roughly 20-byte keys documented for the reference memtier workload.  It covers
normal GET/SET data-plane state owned or touched by an IO thread.  It excludes the
database/index, worker-only state, allocator metadata/fragmentation beyond the
listed usable classes, page tables, stack, code, shared command definitions, and
variable rax/list registry overhead that is not in the per-command hot path.

## A hardware/topology confound that must be fixed first

On this exact box, Linux reports sibling pairs `0,8`, `1,9`, ..., `7,15`, and all
0--15 CPUs share the L3.  The stated pinning therefore places every load-generator
thread on the SMT sibling of a server core.  The reference harness also uses
loopback (`tools/preflight/postmerge.sh`), not a NIC receive path.

Consequences:

1. The load generator competes with the server for issue resources and the same
   32 KiB L1d and 1 MiB L2.  A server counter change cannot initially be called
   IO-vs-EX LLC eviction.
2. Loopback has kernel socket/skbuff work but no NIC DMA/DCA population.  The
   uTPS mechanism of protecting DCA-populated packet lines is not exercised by
   this harness.
3. A remote generator changes the path by adding the NIC, so use both a remote
   run and a local sibling-placement control described below.

This confound is higher expected value to resolve than any layout patch.

## Exact counts and sizes

### Live objects at depth 32

With four IO owners, the 200 connections distribute to about 50 per IO thread.
At a synchronized full ring each IO thread has:

* 50 real `client` objects;
* 50 `connection` objects;
* 1,600 fake `client` objects (50 x 32), lazily created and then reused;
* 1,600 live `pendingCommand` objects;
* 1,600 GET argv arrays with two pointers each;
* 1,600 parsed key objects; argv[0] is replaced with the shared/interned command
  object and does not remain a private allocation;
* 50 real 16 KiB output buffers and 1,600 fake 1 KiB output buffers;
* one reusable 16 KiB query SDS per IO thread on the normal complete-read path,
  not one such buffer per connection.

For SET, each pending command has a three-pointer argv array and another parsed
value object.  A 32-byte value adds about 64 B usable per live command.

The real/fake clients, reply buffers, list headers, CDBs, and dispatch queues are
long-lived.  Keys are allocated and released per command.  `pendingCommand` plus
its argv array can be reused, but the owning-IO pool holds only 128 pairs.  A fully
synchronized 1,600-command wave therefore has no more than 128 pool hits after an
idle drain; the remaining pairs pass through jemalloc allocation/free, while an
always-staggered workload may recycle the same pool entries more effectively.
This is allocation overhead, not proof of cache-capacity pressure.

### ABI-derived structure sizes

| Object | Requested size | jemalloc usable class | Source |
|---|---:|---:|---|
| `client` | 1,160 B | 1,280 B | `src/server.h:1775-2022` |
| `pendingCommand` | 152 B | 160 B | `src/server.h:4288-4307` |
| `connection` | 72 B | 80 B | `src/connection.h:100-113` |
| `list` | 48 B | 48 B | `src/adlist.h:27-34` |
| `listNode` | 24 B | 24 B | `src/adlist.h:16-20` |
| `cdbSlots` | 64 B, explicitly aligned | 160 B raw allocation for one bus | `src/server.h:1645-1658`, `src/networking.c:513-527` |
| `exQueue` | 16,512 B | part of a larger per-worker block | two header lines + 2,048 pointers; `src/server.h:2482-2522` |
| `robj` | 24 B | included below | `src/object.h:151-168` |

Some older notes in the tree assume a 16-byte `robj`; that is stale.  The current
object has the added `vmeta` pointer and is 24 bytes.  A small embstr request is
`24 + 3-byte sdshdr8 + payload + NUL = 28 + payload`.  Thus a roughly 20-byte key
requests exactly 48 B and uses the 48 B class.  A 32-byte value requests 60 B and
uses the 64 B class.

The one-CDB allocation requests `64 + 64 + sizeof(void*) = 136 B`; the extra space
aligns the live 64-byte bus and stores the raw pointer.  Its usable allocation is
160 B, although only one aligned line is operational state.

### Per-connection and per-IO allocation

For a GET with a roughly 20-byte key:

| Component | Count per connection | Usable bytes each | Bytes per connection |
|---|---:|---:|---:|
| real `client` | 1 | 1,280 | 1,280 |
| real output buffer | 1 | 16,384 | 16,384 |
| real reply-list header | 1 | 48 | 48 |
| one-CDB raw allocation | 1 | 160 | 160 |
| `connection` | 1 | 80 | 80 |
| `server.clients` list node | 1 | 24 | 24 |
| 32 fake `client`s | 32 | 1,280 | 40,960 |
| 32 fake output buffers | 32 | 1,024 | 32,768 |
| 32 fake reply-list headers | 32 | 48 | 1,536 |
| 32 live `pendingCommand`s | 32 | 160 | 5,120 |
| 32 two-pointer argv arrays | 32 | 16 | 512 |
| 32 parsed keys | 32 | 48 | 1,536 |
| **total** |  |  | **100,408 B** |

Therefore the connection-owned total is:

```text
50 x (17,976 fixed + 32 x 2,576 per live GET slot)
= 5,020,400 B
```

Per-IO shared data-plane additions are approximately:

* reusable query SDS: about 20,480 B usable.  A 16,384-byte SDS request includes
  its header and NUL, taking the next jemalloc class (`src/networking.c:4689`);
* four producer `exQueue`s at `io4/ex4`: 4 x 16,512 = 66,048 B.

That yields **5,106,928 B (4.87 MiB)**.  Initial event-loop storage adds about
172 KiB: 1,024 `aeFileEvent`s, 1,024 `aeFiredEvent`s, and the epoll result array
sized for the default 10,000 clients plus 128 reserved descriptors
(`src/ae.c:66-95`, `src/ae_epoll.c:19-24`, `src/server.c:5409,21753`).  The complete
scoped envelope is therefore about **5,279,104 B (5.03 MiB) per IO thread**.
Most of the epoll result array is allocated but not touched with only 50 owned
connections.

Each active IO lane also has one 8,320-byte `freebackRing` per worker, logically
33,280 B per IO thread.  It is preallocated in the same worker-owned block as the
queues but is untouched by ordinary copied 32-byte GET replies; it is used only
when a large zero-copy reply returns an object reference to its owning worker
(`src/server.h:2524-2538`, `src/server.c:21651-21668`).  Including this installed
but small-GET-inactive capacity makes the logical envelope **5,312,384 B (5.07
MiB)**.  Auto-mode also preallocates lanes for possible role conversion; those
unused lanes are server reserve, not a resident set attributable to an active IO
thread.

For 32-byte SET, changing argv from 16 to 24 B and adding a 64 B value object adds
72 B per live slot, or 115,200 B per IO thread.  The corresponding envelope is
about **5,394,304 B (5.14 MiB)**.  The persistent database value is worker/index
state and is not included.

IO slot 0 is also the Redis main/control thread, so its true footprint is larger
and noisier.  Report it separately rather than averaging it blindly with IO1--3.

### Capacity is not the active working set

For a 32-byte GET result the RESP2 reply is 39 B.  At full depth:

* each fake normally touches one 64-byte line of its 1 KiB buffer: about 102,400 B;
* the real buffer accumulates `32 x 39 = 1,248 B` per connection: about 62,400 B;
* the corresponding fake payload is also 62,400 B logically, but occupies the
  one-line-per-buffer 102,400 B above;
* a full request wave is only roughly 1--2 KiB in the reusable query SDS, depending
  on key formatting.

The buffers allocate about 2.36 MiB per IO thread, but their small-GET active
payload is only about 0.17 MiB.  Buffer capacity is therefore a poor proxy for LLC
occupancy.

The harder part is the full fake `client`.  Dispatch, worker execution, publication,
IO drain, reply splice, accounting, and reset touch approximately 11--12 distinct
lines in the 1,160-byte object.  Across 1,600 fakes that is roughly 1.1--1.2 MiB.
Adding fake reply/list lines, live command/argv/key objects, real-client hot fields,
real reply payloads, CDB lines, queue lines, connection/event state, and the query
window gives a central **1.7--2.0 MiB demand-touched estimate per IO owner**.

The estimate is reproducible from these rounded components:

| Demand-touched candidate | Estimated bytes per IO | Reasoning |
|---|---:|---|
| fake-client field lines | 1,126,400--1,228,800 | 1,600 x 11--12 x 64 B |
| first fake-reply buffer lines | 102,400 | 1,600 x one line |
| fake reply-list headers | 76,800 | 1,600 x 48 B headers; hot head/tail/len |
| live `pendingCommand` allocations | 256,000 | 1,600 x 160 B; acquire/reset clears the struct |
| GET argv arrays and key objects | 102,400 | 1,600 x (16 + 48 B) |
| real-client fields, active reply bytes, CDBs | about 100--130 KiB | 50 clients, 1,248 reply bytes/client, one CDB line/client |
| active queue/query/event/connection lines | about 80--130 KiB | queue slots cycle; epoll only visits ready entries |
| **rounded total** | **about 1.76--1.94 MiB** | reported as 1.7--2.0 MiB after alignment/path uncertainty |

That estimate deliberately does not count untouched allocation slack or every cold
line in every object.  Nor does it assert simultaneous residence: fields are
visited at different stages and may have been evicted by the next wave.  Only CQM
can give occupancy directly.

## Network buffers

### Default epoll path (`tomokv-io-uring=0`)

`PROTO_IOBUF_LEN` and the real reply buffer are both 16 KiB; fake reply buffers
start at 1 KiB and can grow to 64 KiB (`src/server.h:182-185`).

The receive side does **not** retain 50 x 16 KiB in the normal complete-request
case.  `thread_reusable_qb` is TLS (`src/networking.c:54-55`); a client borrows the
one per-thread SDS for a read, parsing consumes it, and the buffer is cleared and
returned.  A client gets its own retained SDS only for an incomplete request,
nested/re-entrant use, or a large/in-progress argument (`src/networking.c:4678-4704`).
Thus the normal receive allocation is about 20 KiB per IO thread, reused rather
than churned per request.

There is a meaningful backpressure bound: if parsing stops with unconsumed bytes,
the client keeps that SDS and the TLS slot obtains another.  If all 50 connections
simultaneously strand a 16 KiB-class query buffer, receive storage is about
`50 x 20,480 = 1,024,000 B` per IO thread instead of 20,480 B, adding about 0.96
MiB to the table above.  Exactly one p32 batch normally consumes cleanly; multiple
queued batches, partial large requests, or a full dispatch ring can reach the
retained case.  Count private querybufs and their `sdsalloc()` sizes in the eventual
run rather than assuming either bound.

The send side retains 50 real 16 KiB buffers = 819,200 B and, once the p32 rings
have filled, 1,600 fake 1 KiB buffers = 1,638,400 B.  Together with the receive SDS,
buffer *capacity* is about 2.36 MiB per IO thread.  It does not fit L2.  Per
connection, however, `16 KiB + 32 x 1 KiB = 48 KiB`, which easily fits; it is the
50-connection aggregate that does not.  These buffers are allocated with `zmalloc`
in `createClient()`/`createFakeClient()` and reused for the connection/ring-slot
lifetime.  Larger replies or socket backpressure can grow fake buffers up to 64
KiB and append/grow real reply storage; that conditional capacity is outside the
small-value total and should be measured from buffer peaks and reply-list bytes.

Kernel socket receive/send queues and skbuffs are separate kernel allocations and
cannot be sized from this tree.  Record them with `ss -tinm`/`ss -m` during the
eventual measurement.  With loopback there is no NIC-DCA packet footprint to
protect.

### Optional io_uring modes

These are not part of the default result and should not be mixed into it:

* mode 1 allocates 512 x 16 KiB provided receive buffers and 256 x 16 KiB registered
  send buffers per IO owner: **12 MiB per IO thread**, before ring metadata
  (`src/uring.c:27-30,1318-1377`).  Buffers are reused; only completed byte ranges
  need be cache-hot.
* mode 2 allocates one 16 KiB receive buffer per attached real client and lazily one
  16 KiB send scratch buffer (`src/uring2.c:506,1513`).  At 50 connections that is
  800 KiB receive and up to 800 KiB send, **1.6 MiB per IO thread**.  This mode also
  copies from its receive buffer into the query SDS and from the real reply buffer
  into send scratch.

Any residency experiment must record the mode and analyze it separately.

## Client layout, useful and accidental touches

The 1,160-byte `client` is an all-purpose Redis execution context.  A fake pays for
many fields it never needs in steady-state: the inline 32-pointer `fakeClients`
array, connection controller state, replication/module/blocking hooks (most of the
truly rare state has already moved to nullable `clientCold`), address/name strings,
three embedded list nodes, event-loop accounting, query parsing state, and uring
pointer.  Normal GET/SET leaves `clientCold == NULL`.

The layout has two different costs:

1. **capacity/RSS cost:** cold fields make every fake allocation land in the 1,280 B
   class;
2. **coherence cost:** the IO and EX threads intentionally alternate ownership of
   hot fake lines.  IO stamps command/connection/db/routing state, EX consumes that
   state and builds the reply, and IO reads and resets the reply state.

Some cold fields also share lines with hot fields.  In particular, `flags`, `conn`,
`tid`/`running_tid`, `resp`, and `db` lead into cold `name`, `lib_name`, and
`lib_ver`; reply/list state and real-client-only accounting share the latter half
of the object.  Merely relocating a cold pointer does not save a line if another
hot member still selects it.

There is direct in-tree evidence that line placement matters: the tail comment in
`client` records that inserting 24 B in the middle shifted reply-control fields,
added ownership transfers/RFOs, and regressed 2--5%; those fields were moved to the
tail (`src/server.h:1997-2015`).  This is evidence for a coherence/layout effect,
not evidence that the 32 MiB LLC is full.

The biggest apparently wasteful member is the inline 256-byte `fakeClients[32]`.
It is needed by real clients and dead weight in every fake.  Moving it out would
reduce a fake from 1,160 B to roughly 904 B, likely moving 1,600 fake allocations
from the 1,280 B to the 1,024 B class and saving **409,600 B per IO thread**.  But
those four lines are not touched on the steady fake path after initialization, so
this is mostly an allocation/RSS saving, not a residency saving; the real path
also gains an indirection.  Creation and cross-shard-pool reset do clear the array,
but a persistent normal ring fake is not recreated per request.  I do not expect
the change to pay in throughput.

The pending-EX and pending-write memberships are already embedded `listNode`s, so
there is no per-dispatch node allocation.  The per-IO `pendingCommand` pool retains
at most 128 structures and their argv arrays (`src/networking.c:3910-3916`).  For
GET-sized argv this is about 22,528 B when idle; at a simultaneous 1,600-command
wave those objects are live rather than additionally pooled.  The cross-shard
sub-fake pool can conditionally retain 96 fake clients per IO thread, about 225,792
B at the initial buffer size, but ordinary single-key GET/SET does not exercise it.

The obvious global reads are not a meaningful capacity target.  Dispatch reloads
the immutable `server.num_cdb` in `cdbIndexFor()` and tests atomic/cross-shard and
express-routing state; the drain tests the immutable `server.io_uring` mode before
writing.  These are a handful of shared scalar lines, not a per-connection set.
Hoisting immutable values into IO TLS might remove a load or address calculation,
but it would not shrink the resident footprint and would complicate role changes.
The dynamic express EWMA is updated at control-plane cadence, not per command by
another core.  Address sampling should precede any attempt to repack the enormous
global `redisServer`; its total struct size says nothing about the residency of the
few selected lines.

## Reply path and copies

For a small GET, the path is:

1. epoll/socket read copies kernel data into the reusable query SDS;
2. parsing creates an embstr key object;
3. EX executes with the fake client and constructs the 39-byte response in the
   fake's 1 KiB buffer;
4. EX release-stores the corresponding byte in the parent's CDB line;
5. IO acquire-loads it in `handleWorkerReplies()` and calls
   `AddReplyFromClient()` (`src/server.c:3545-3792`);
6. because the response is below the 8 KiB transfer threshold, IO copies it into
   the real client's 16 KiB buffer (`src/networking.c:1874,1923-1974`);
7. one socket write sends the approximately 1,248-byte p32 aggregate.

The small-reply fake-to-real copy is about 39 B/op, or roughly 312 MB/s at 8 Mops/s.
That sounds large as an operation rate but is modest for this memory hierarchy and
keeps the lifetime simple: the fake slot can be cleared immediately and the write
is contiguous.  Scatter/gather or direct fake-buffer sends would hold ring slots
until completion, create iovec work, and turn 32 tiny buffers into kernel-visible
fragments.  The existing 8 KiB threshold is sensible.  I do not expect eliminating
this copy to pay for the reference workload.

The worker assigns `fake->conn = real->conn`, but small reply construction mostly
needs the non-NULL connection/execution context rather than dereferencing socket
state.  The actual `connection` remains an IO-owned 72-byte object in the ordinary
path.

## Is there evidence of IO/EX eviction in shared L3?

Not yet.  Source inspection establishes shared data and an over-L2 candidate set.
The existing performance evidence argues against capacity misses being limiting.
A simultaneous observation that IO and EX both have L3/DRAM fills would show
coexistence, not that one role evicted the other.

The current single `cdbSlots` line per real client is a more concrete sharing
concern.  Different EX workers publish different ready bytes in the same line and
the IO owner clears them.  “One CCD” means a common L3, but the four worker cores
still have private L2s.  The line can bounce among worker L2s and the IO L2.  This
is coherence interference; it need not consume meaningful L3 capacity.

### Measurement without resctrl

Use static thread mode so role identities do not change.  Record PID/TID, `comm`,
current CPU, and affinity before and after each arm:

```sh
ps -L -p "$pid" -o pid,tid,psr,comm
for tid in $tids; do awk '/Cpus_allowed_list/ {print}' "/proc/$tid/status"; done
```

The custom names are `poly_ioN_exN`; IO0/main must be reported separately.  Do not
use auto mode for a per-role comparison because roles can flip.

This AMD PMU exposes demand-fill source events that are more useful here than a
generic cache-miss total:

```sh
perf stat --per-thread -x, -I 1000 -t "$tid_csv" \
  -e '{cycles,instructions,ls_dmnd_fills_from_sys.all,ls_dmnd_fills_from_sys.local_l2,ls_dmnd_fills_from_sys.local_ccx,ls_dmnd_fills_from_sys.dram_io_near}' \
  -- sleep 30
```

On this kernel the fill-source aliases map to event `0x43`, with umasks `0xff`
(all), `0x01` (local L2), `0x02` (local CCX), and `0x08` (near DRAM/MMIO).  Record
`perf list` with the result and use raw `cpu/event=0x43,umask=.../` forms only if
the named aliases disappear.  A split pass can add
`l2_cache_req_stat.ls_rd_blk_c` (event `0x64`, umask `0x08`) for L2 data-request
misses.

Run a second user-only pass (`:u` suffixes) to separate application activity from
loopback/kernel network work.  If the group multiplexes, split it into synchronized
passes; reject a pass whose time-running is below 95%.  Also capture
`backend_bound_memory`/`backend_bound_cpu` if `perf stat -M` validates them on the
running kernel.  Optional IBS samples (`ibs_op/l3missonly,cnt_ctl,swfilt/`) can
attribute miss PCs, but are not an occupancy measurement.

Normalize at least these quantities:

* instructions and cycles per operation;
* local-L2, local-CCX (L3 or peer L2), and local-DRAM fills per 1,000 instructions;
* DRAM fills/op and an approximate `64 x fills/op` demand-read bytes/op;
* throughput and p50/p99/p99.9 latency.

EX operations can use the per-worker command deltas exposed by
`DEBUG RESHARD PERWORKER`.  There is no equally clean public per-IO denominator;
use balanced connections and report TID counters directly, or expose the existing
per-IO dispatch count only in a cold debug/stat path.  Do not add a new hot atomic
counter just for this experiment.

Then use counterfactuals:

1. **Remove the SMT confound.**  Use a remote generator so all server cores are
   physically exclusive.  Separately, make a local four-server-thread control:
   compare generator CPUs 8--11 (SMT siblings of server 0--3) with generator CPUs
   4--7 (different physical cores), at the same open-loop offered rate and request
   trace.  A change there is sibling L1/L2/front-end interference, not IO/EX LLC
   eviction.
2. **Actual IO-footprint sweep.**  At an offered rate below the slowest arm, hold
   dataset, command mix, keys, connections, EX count, and affinity fixed; sweep
   pipeline depth 1/4/8/16/32.  Randomize/interleave arm order.  Pipeline also
   changes syscall/batching overhead, so require a monotonic, reversible increase
   in EX local-CCX or DRAM fills/op and EX cycles/op as the live fake footprint
   grows.  A throughput change without the victim-role counter change is not
   residency evidence.
3. **Susceptibility control.**  If needed, use a temporary IO-only cache ballast
   with one fixed cache-line touch per dispatch and sweep its footprint from 64 KiB
   to 16 MiB while keeping instruction/touch count constant.  A monotonic,
   reversible increase in EX DRAM fills/op and memory-bound cycles proves that an
   IO footprint *can* evict EX data.  It still does not prove the present fake-ring
   footprint does; the actual depth/layout A/B must reproduce the direction.
4. **CDB A/B.**  Force `num_cdb=1` versus one CDB per worker on the same CCD.  Look
   for lower IO and EX local-CCX/coherence fills and cycles/op with stable DRAM
   fills.  This isolates the likely private-L2 line-bounce mechanism from LLC
   capacity.

Evidence that would settle “interference” is a victim-role degradation that tracks
only the aggressor's footprint, reverses when the footprint is removed, and cannot
be explained by offered load, sibling placement, instruction count, or changed
batching.  Evidence for **no useful headroom** is equally clear: low/stable EX DRAM
fills and backend-memory fraction across the actual footprint sweep, no victim
cycles/op or tail-latency benefit, and any cache partition/reduction flat or worse
outside the run-to-run interval.

### What resctrl adds

After an administrator mounts resctrl, first read—not assume—`info/L3/cbm_mask`,
`min_cbm_bits`, `num_closids`, and `info/L3_MON/mon_features`.  Create IO and EX
control groups, place IO/main TIDs and EX TIDs explicitly, and use monitoring groups
to read:

* `llc_occupancy` by role or TID;
* deltas of `mbm_total_bytes` and `mbm_local_bytes`;
* CAT mask experiments with overlapping and non-overlapping ways.

CQM occupancy or MBM alone still does not prove eviction.  The strong experiment
is:

1. both roles on the full overlapping mask (grouping control);
2. non-overlapping IO/EX masks, despite reducing each role's usable LLC;
3. a directional mask sweep that gives ways back to the apparent victim;
4. the same perf, throughput, and tail-latency measurements in every arm.

The aggregate central IO hot estimate is roughly 7--8 MiB for four IO owners.  If
the hardware exposes, for example, 16 legal ways, about four ways is a reasonable
*starting point* for IO, not a conclusion; derive bytes/way from the reported mask
and sweep.  A non-overlapping partition that improves victim cycles/op, misses,
throughput, or tails even though total usable capacity fell is strong evidence of
cross-role interference.  Flat/negative legal partitions, occupancy below the
assigned capacity, and low stable DRAM traffic are strong evidence that residency
has no payoff here.

Keep the load generator off the server's physical cores.  If it remains local and
in the default CLOS, it can use all ways and defeat an otherwise clean IO/EX CAT
interpretation.

## Ranked proposals

### 1. Fix placement and run the per-role counterfactuals — highest expected value

**Mechanism.** Remove SMT sibling competition, hold offered load fixed, collect
per-TID fill sources, then sweep the real IO footprint.  Use CAT/CQM later when
root access is available.

**Estimated size/effect.** No product footprint change.  It separates a 1.7--2.0
MiB/IO demand-touched candidate from the 32 KiB/1 MiB sibling-cache confound and
from the EX dataset.

**Confirm/refute.** Confirmation requires a reversible victim-role change in
fills/op plus cycles/op/latency.  Refutation is stable low DRAM/backend-memory
behavior and no benefit when IO footprint or way ownership changes.

**Cost when it does not help.** Experiment time only; remote generation introduces
the NIC path, hence the paired local placement control.  This is the most valuable
work because it prevents optimizing an unproven mechanism.

### 2. A/B one completion bus per EX worker on the single CCD — cheap, plausible, low confidence

**Mechanism.** Change the topology policy experimentally from one shared CDB line
per real client to one line per worker.  Each worker then publishes into its own
line; IO still drains the exact `fake->cdb` and does not scan all buses.  This aims
at private-L2 ownership bouncing, not LLC capacity.

**Estimated size/effect.** One bus requests 136 B and uses a 160 B allocation.  Four
buses request 328 B and use about a 384 B class.  The delta is about **224 B per
connection = 11,200 B per IO thread = 44,800 B server-wide** at 200 connections;
the live aligned bus bytes increase by 9,600 B per IO thread.

**Confirm/refute.** Static `io4/ex4`, identical trace, interleaved `num_cdb=1` and
`num_cdb=4`.  Accept only a repeatable throughput/tail or cycles/op improvement
with reduced local-CCX/coherence fills and no compensating DRAM increase.

**Cost when it does not help.** About 44 KiB server-wide here, an extra routing
comparison on the general path, and more lines for IO to touch.  My expectation is
at most a small low-single-digit effect.  Measure before proposing a code patch.

### 3. CAT isolation as an experiment, not a default policy — high diagnostic value, low expected production value

**Mechanism.** Give IO and EX non-overlapping LLC ways and monitor role occupancy
and bandwidth.

**Estimated size/effect.** Four IO owners have a central 7--8 MiB active estimate;
the exact way count depends on `cbm_mask`.  Partitioning reduces the pool available
to EX and can also strand unused IO ways.

**Confirm/refute.** The overlapping-mask control versus non-overlap and a
directional way sweep described above.  Improvement despite less total usable LLC
is the useful signature.

**Cost when it does not help.** Requires root/setup and operational CLOS management;
can reduce throughput by artificially starving EX or IO.  Given the dataset and
prefetch evidence, I do **not** expect permanent CAT partitioning to pay on this
workload.

### 4. Reduce depth or connections only when the service-level objective permits it — likely not a win here

**Mechanism.** Fewer simultaneously live fake clients reduce both cache footprint
and outstanding work.  The GET allocation formula per connection is:

```text
17,976 + 2,576 x depth bytes
```

At depth 16, connection-owned data is 2,959,600 B per IO thread; at depth 8 it is
1,929,200 B, before approximately 259 KiB of active-path shared/event additions
(or about 292 KiB including the inactive freeback capacity).  The central
hot estimate approaches L2 around depth 16 and is plausibly below it around depth
8.  Roughly halving connections per IO has a similar hot-set effect.

**Confirm/refute.** Open-loop depth/connection sweeps with fixed offered rate,
per-role fills/op, queue stalls, throughput, and tail latency.  A win must persist
at the target offered load, not merely reduce work admitted.

**Cost when it does not help.** Less batching and concurrency, more ring-full
stalls, and possible throughput/tail regression.  Existing sweeps identify about
200 clients as useful for feeding the server.  I do **not** expect this to improve
the canonical peak-throughput point.

### 5. Build a compact fake-only execution context — large possible footprint reduction, poor risk/reward

**Mechanism.** Stop allocating the general-purpose 1,160-byte `client` for every
ring slot.  A compact context would contain only command, DB/user/connection
borrows, routing/publication, reply, and accounting fields.

**Estimated size/effect.** Saving even 640 usable bytes per fake would remove about
**1,024,000 B per IO thread** at 1,600 slots.  It is the only layout direction large
enough to approach L2 without reducing concurrency.

**Confirm/refute.** First use cache-line/address samples to identify which fake
lines actually transfer, then prototype and require fewer instructions *and*
local-CCX/DRAM fills per op at unchanged semantics and latency.

**Cost when it does not help.** Redis command procedures take `client *`; changing
that contract or maintaining a shadow-compatible client is invasive and creates a
large correctness surface across modules, blocking, scripts, errors, ACLs, and
cross-shard paths.  The skeptical prior makes this unjustified now.  I do **not**
recommend it without positive interference evidence.

### 6. Allocation-only micro-edits — do not pursue for cache residency

**Shrink fake buffers to 128 B.** This saves `(1,024 - 128) x 1,600 = 1,433,600 B`
per IO thread in allocation capacity.  A 39-byte reply already touches one line,
so it saves essentially no small-GET resident lines.  Replies of 129--1,024 B then
grow/reallocate every affected slot.  **Will not pay for residency.**

**Move `fakeClients[32]` out of `client`.** Likely saves 409,600 B per IO thread in
fake allocation classes, but its lines are cold in steady fake use and the real
client gains an allocation/indirection.  **Useful only if RSS is the objective;
unlikely to improve throughput.**

**Zero-copy/scatter tiny replies.** Avoids about 39 B copied per GET, but adds iovec
and lifetime work and delays fake-slot reuse.  The existing 8 KiB transfer threshold
already selects zero-copy where bytes can amortize ownership complexity.  **Will
not pay for 32-byte values.**

**Pack or TLS-cache global knobs.** At most a few shared cache lines are involved;
the likely benefit is an instruction/load shave, not a residency reduction.  A/B
with instructions/op and address samples if this ever appears in a profile.  The
no-win cost is duplicated state and more role-change/config invariants.  **Not a
cache-residency project.**

## Patch decision

This commit intentionally contains no product-code patch.  The only cheap code
candidate, worker-striped CDBs on a single CCD, targets a coherence hypothesis that
has not been measured; the larger layout changes mostly remove cold allocation or
carry disproportionate correctness risk.  A CDB forcing knob and the IO ballast
would be experiment-only patches after the current measurement finishes, not
changes to merge on the basis of this audit.

## Decision rule

Do not infer an LLC problem from “5 MiB allocated per IO thread.”  Proceed to a
residency optimization only if the experiments show all of the following:

1. server/loadgen SMT interference has been removed or separately quantified;
2. an IO-footprint change causes a reversible EX fill-source and cycles/op change;
3. the effect survives normalization for instructions and operations;
4. throughput or tail latency improves, not just a cache counter;
5. CAT isolation or a real layout A/B points in the same direction.

If per-role DRAM fills/backend-memory fraction stay low and stable and CAT/depth
controls are flat or negative, the correct finding is: **the IO allocation exceeds
L2, but cache residency is not limiting this server and there is no useful
headroom here.**  Based on the evidence presently in the tree, that is the more
likely outcome.
