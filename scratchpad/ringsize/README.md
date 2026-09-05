# ringsize — size the RYOW write ring to the ROB window

The base lane (`t-rlbatch`, 479922c0a) stopped a full RYOW ring from turning every further write into
a demote-every-pending-read wave, and closed with one thing open: the ring still overflows, and the
reads it fences at parse time still fall back. This lane answers whether sizing the ring to the
reorder buffer is worth what it costs.

## 1. The ceiling, measured before anything was built

`-DTOMO_RLHIST` adds a histogram of PUBLISHED-AND-UNRETIRED writes on one connection, sampled at
every read probe and at every write commit. It keeps its own slot bitmap in the heap sidecar —
never in the Rob, so every layout lock still holds in that build — and masks it by the active
window, so it reports the true in-flight count on a build whose ring has already given up.

Server on cores 48-51, memtier on 184-191, 200k keys, dbsize pinned to keymax.

| cell | mean | p50 | p90 | p99 | **max** |
|---|---|---|---|---|---|
| 41% reads, depth 32 | 9.31 | 9 | 17 | 19 | **19** |
| 61% reads, depth 32 | 5.92 | 6 | 11 | 12 | **13** |
| 41% reads, depth 8 | 2.04 | 3 | 3 | 5 | **5** |
| 10% reads, depth 64 | 25.11 | 23 | 49 | 56 | **57** |
| write-only, depth 64 (at commit) | 27.60 | 26 | 54 | 62 | **63** |

The tail is not unbounded, and the bound is not a property of the workload: it is the reorder
buffer. A ring entry lives exactly while its op is in flight, so live entries name distinct ids in
a window at most `kRobWindow` wide. **A client pipelining 64 deep at 100% writes tops out at exactly
63 live writes** — one short of the window, which is the arithmetic the proof predicts, since the
write being committed holds a window position no ring entry can.

## 2. What was built

`kWriteRingCapacity` 16 → 64 = `kRobWindow`, with `static_assert(kWriteRingCapacity >= Capacity)` in
the Rob carrying the argument. Both capacity tests are **kept**, not deleted: they are unreachable,
but conservative is the only safe answer if the reasoning is ever wrong. Conservative generations
themselves stay ordinary traffic through the other door — any write that never refines (a wide
multi-key write, or a point write under an evicting maxmemory policy).

The tag mirror moved out of the Rob into the sidecar: sixty-four 16-bit tags are 128 bytes and the
Rob is locked at 192 with sixteen spare. `valid_`/`wide_` widened to 64-bit slot bitmaps and the
force-exact flag took its own word. **Rob<64> is still 192 bytes**; Client 1984, Op 336,
ThreadCtx 1408, Config 624, FlatStore 944, AtomicEntry 144 all unchanged.

### The sweep had to be rewritten, and the reason is codegen

The obvious `for (i < 64) hits |= (tags[i] == tag) << i` — the sixteen-slot filter's own shape —
leaves GCC 13.3 emitting a scalar seven-instruction body sixty-four times, about **450 instructions**
on the hot reject path. The sixteen-lane form it *does* vectorise (a `vpcmpeqw` against a constant
bit-weight vector, then an OR-reduction) costs about twenty. Grouping the sweep into four sixteen-
lane blocks restores that form; skipping blocks with no live slot then costs a live run only the
blocks it spans — one or two, since the FIFO keeps live entries contiguous. Verified by objdump.

The first draft of this lane shipped the scalar version into a rate A/B and read −8% at 61% reads
before the objdump was taken. That is what the instrument is for.

## 3. Memory

| | PRE | POST |
|---|---|---|
| `sizeof(ReadLocalRobState)` | 296 B | 1216 B |
| jemalloc size class | 320 B | 1280 B |
| **measured RSS per armed connection** (2000 idle connections, `mem.sh`) | **10676 B** | **11641 B** |

**+965 bytes per armed connection**, matching the size-class arithmetic, and paid by every connection
on a read-local server: the sidecar is allocated at accept (`io_loop.h`), not on first write. It is
about 9% of what an armed connection already costs.

## 4. Instructions per operation

`instr_ab.sh` / `instr_deep.sh` re-point the base lane's single-connection pinned replay at this
lane's port and cores, so the numbers are directly comparable to `../rlbatch`. Slope over 1M and 3M
operations, ABBA, 3 rounds, medians, `instructions:u`. Read keys and write keys are disjoint, so
every fallback the ring causes is a fallback it did not need to cause.

| cell | PRE | POST | delta | pct |
|---|---|---|---|---|
| mix 41% p64 | 2798.3 | 2586.1 | **−212.2** | **−7.58%** |
| mix 25% p64 | 2837.6 | 2745.4 | **−92.2** | **−3.25%** |
| mix 41% p32 | 2755.0 | 2709.2 | **−45.8** | **−1.66%** |
| mix 10% p64 | 2870.9 | 2882.4 | +11.5 | +0.40% |
| mix 41% p8 | 3821.2 | 3832.2 | +11.0 | +0.29% |
| mix 61% p8 | 3602.5 | 3621.0 | +18.5 | +0.51% |
| mix 61% p32 | 2475.3 | 2494.4 | +19.1 | +0.77% |
| mix 71% p8 | 3482.0 | 3503.7 | +21.7 | +0.62% |
| mix 71% p32 | 2358.4 | 2380.9 | +22.6 | +0.96% |
| **write-only p32 (deficit control)** | 3024.6 | 3067.3 | **+42.8** | **+1.41%** |
| **read-only p32 (null control)** | 1953.3 | 1953.4 | +0.1 | **+0.01%** |
| sep 10/25/41% p64 (write-only leg) | | | +30 to +50 | +1.2 to +1.8% |

The read-only null at +0.01% is what says the instrument is trustworthy: a connection that never
writes never activates the sidecar, and pays nothing.

### The counters, in the same geometry

| cell | PRE local | POST local |
|---|---|---|
| 41% reads p32 | 87.5% (153750 of 1230000 fenced) | **100.0%** (0 fenced) |
| 61% / 71% reads p32 | 100.0% | 100.0% |
| 41% reads p8 | 100.0% | 100.0% |
| 41% reads p64 | 43.8% (691875 fenced) | **100.0%** (0 fenced) |
| 10% reads p64 | 28.1% (215623 fenced) | **100.0%** (0 fenced) |

## 5. The shape of the trade

The change wins exactly where the sixteen-slot ring was the binding constraint and costs about one
percent where it was not. The cost has two sources, both inherent rather than incidental:

* **the write side (+43 instructions per op on a write-only connection).** Under a sixteen-slot ring
  a write-only connection at depth 32 lived permanently in overflow, where a write costs two
  comparisons because the ring has given up. Precise tracking costs a real insert and a real prune.
  A connection that never reads pays that for nothing — reported, not hidden.
* **the read probe (+19 to +23 at 61-71% reads).** Four sixteen-lane blocks with an empty-block skip
  instead of one, plus the sidecar dereference the inline mirror used to avoid.


## 6. Rate, and why it does not carry the verdict here

The ABBA rate A/B (`ab.sh`, server 48-51 / 8 shards, memtier on 184-191, 256 connections, depth 32,
15 s cells, 3 rounds) is reported for its COUNTERS, not for its rates. Its own null control — the
read-only cell, which this change provably cannot reach, and which the instructions/op instrument
measures at +0.01% — came back at **-13.06%**, and the same arm and cell swung between 5.76 and
8.10 M ops/s across visits. A co-tenant lane restarted 70 cores of load partway through the run
(load average 11 at launch, 60 at finish). A rate instrument whose null control moves thirteen
percent cannot resolve a one-percent effect, so no rate delta from this table is quoted as a result.

| cell | arm | rate M/s | read_local_hits | fallback_inflight_write | local % |
|---|---|---|---|---|---|
| 41% reads (3:2) | PRE | 4.564 | 16642666 | 10717522 | 60.8% |
| 41% reads (3:2) | POST | 4.189 | 25136365 | **1458** | **100.0%** |
| 61% reads (2:3) | PRE | 5.419 | 48535055 | 2017 | 100.0% |
| 61% reads (2:3) | POST | 5.006 | 44795534 | 1878 | 100.0% |
| write-only (1:0) | PRE | 6.162 | 0 | 0 | — |
| write-only (1:0) | POST | 5.428 | 0 | 0 | — |
| read-only (0:1) — NULL CONTROL | PRE | 7.887 | 109990899 | 0 | 100.0% |
| read-only (0:1) — NULL CONTROL | POST | 6.856 | 94546085 | 0 | 100.0% |

The counters are counts, not rates, and they are what the cell is here to show: at 41% reads and
depth 32 across 256 connections, **10.7 million of 27.4 million reads were lowered to the owner
queue by a ring that had run out of slots, and after the change 1458 were.**

## 7. Files

* `lib.sh` — boot/guard/stop for this lane. Ports 8091-8094, server 48-51 (48-55 for the gate),
  load generators 184-191. Every boot is ss-guarded, every stop kills by PID.
* `inflight.sh` + `histreport.py` — section 1, against a `-DTOMO_RLHIST` build.
* `mem.sh` + `holdconns.c` — section 3.
* `instr_ab.sh`, `instr_deep.sh` — section 4, re-pointing `../rlbatch/measure.sh`.
* `replay_counters.sh` — the counters in the instructions/op geometry.
* `ab.sh` + `report.py` — section 6.
* `mutate.sh` — the four falsification arms for `tests/read_local_write_ring_unit.cc`.
* `batteries.sh` — the 1s and 2s batteries on this lane's port and cores.
* `validate.sh` — runs everything that needs the box, in sequence, so nothing overlaps.
