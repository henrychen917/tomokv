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
| write-only, depth 32 (at commit) | 13.43 | 13 | 26 | 30 | **31** |
| write-only, depth 64 (at commit) | 27.60 | 26 | 54 | 62 | **63** |

The tail is not unbounded, and the bound is not a property of the workload: it is the reorder
buffer. A ring entry lives exactly while its op is in flight, so live entries name distinct ids in
a window at most `kRobWindow` wide. **A client pipelining 64 deep at 100% writes tops out at exactly
63 live writes** — one short of the window, which is the arithmetic the proof predicts, since the
write being committed holds a window position no ring entry can. Every row lands one short of its
own pipeline depth for the same reason.

## 2. What was built

`kWriteRingCapacity` 16 → 64 = `kRobWindow`, with `static_assert(kWriteRingCapacity >= Capacity)` in
the Rob carrying the argument. Both capacity tests are **kept**, not deleted: they are unreachable,
but conservative is the only safe answer if the reasoning is ever wrong. Conservative generations
themselves stay ordinary traffic through the other door — any write that never refines (a wide
multi-key write, or a point write under an evicting maxmemory policy).

`kMaxPreciseKeysetKeys` was **decoupled** from the ring capacity and left at 16. It is a policy
bound on how many keys a blind MSET may name and still take a precise slot — every probe that hits
that slot walks the op's argv — and it has nothing to do with how many writes the ring can hold.
Growing it with the ring would have lengthened the exact walk for no stated reason.

The tag mirror moved out of the Rob into the sidecar: sixty-four 16-bit tags are 128 bytes and the
Rob is locked at 192 with sixteen spare. `valid_`/`wide_` widened to 64-bit slot bitmaps and the
force-exact flag took its own word.

### Layout locks, all verified by the build

`Rob<64>` **192**, `Op` 336, `Client` 1984, `ThreadCtx` 1408, `Shard` 1440, `FlatStore` 944,
`AtomicEntry` 144, `Config` 624 — each is a `static_assert` in its own header, so a clean build of
the server is the proof. The one size this lane does move is now locked too:

```
sizeof(ReadLocalRobState) = 1216      alignof = 64
  write_tags  128 B      write_ring  1024 B
sizeof(Rob<64>)           = 192       kWriteRingCapacity 64   kMaxPreciseKeysetKeys 16
```

`static_assert(sizeof(ReadLocalRobState) == 1216)` is new in this lane. The per-connection bill is
the thing this change spends, so it is locked exactly like every other layout in the tree: a later
field cannot quietly add another size class to every armed connection without someone re-measuring.

### The sweep is written the way it is because of codegen, and the walk is driven by `live`

The obvious `for (i < 64) hits |= (tags[i] == tag) << i` — the sixteen-slot filter's own shape —
leaves GCC 13.3 emitting a **scalar eight-instruction loop run sixty-four times**. `codegen_ab.sh`
disassembles both shapes: the shipped one contains a `vpcmpeqw` against a constant bit-weight
vector and an OR-reduction, the flat one contains no vector compare at all. Note that the flat form
is *smaller* in the listing (36 instructions against 54) because it is a compact loop — which is
exactly why a static count cannot price it, and why `probe_cost.sh` exists.

The group walk is then driven by `live` rather than by the capacity: the lowest set bit names the
first group holding a live slot, and clearing that group's whole mask walks straight to the next.
An empty group costs nothing, so a connection carrying nine live writes pays for one group whether
the ring has sixteen slots or sixty-four.

### Instructions per REJECTED probe — the cost this lane has to defend

`probe_cost.sh`, one connection, 20M probes of a key no live write touches, `instructions:u`:

| live writes | 1 | 4 | 9 | 15 | 19 | 40 | 63 |
|---|---|---|---|---|---|---|---|
| base16 (sixteen slots) instr | 32.1 | 32.1 | 32.1 | 32.1 | **88.1** ¹ | — | — |
| **shipped (64, live-group walk)** instr | 49.1 | 49.1 | 49.1 | 49.1 | **73.1** | 97.1 | 121.1 |
| flat 64-lane (rejected) instr | 599.1 | 599.1 | 599.1 | 599.1 | 599.1 | 599.1 | 599.1 |
| base16 cycles | 5.08 | 5.08 | 5.07 | 5.07 | **15.08** ¹ | — | — |
| **shipped cycles** | 8.08 | 8.08 | 8.08 | 8.09 | **11.70** | 16.17 | 19.53 |
| flat 64-lane cycles | 145.5 | 144.6 | 145.4 | 145.1 | 145.2 | 145.3 | 145.2 |

¹ the sixteen-slot ring is FULL here, so it is in a conservative generation: all 20,000,000 probes
returned **conflict** for a key no live write touches. Its 88 instructions do not buy a rejection,
they buy a false fence and the whole demotion behind it. The shipped ring returned 0 conflicts.

**That is the entire trade in two numbers: +17 instructions and +3 cycles per rejected probe while
the old ring could still hold the run, and −15 instructions and −3.4 cycles once it could not,
while returning the right answer instead of fencing every read.**

Three shapes of the sweep were built and measured; the shipped one is the third:

| sweep shape | live ≤ 15 | live 19 | live 40 | live 63 |
|---|---|---|---|---|
| all four groups, always | 68.1 / 13.2 | 84.1 / 16.5 | 100.1 / 20.1 | 116.1 / 22.6 |
| bounded by ctz/clz of `live` | 60.1 / 10.1 | 83.1 / 13.1 | 106.1 / 16.8 | 129.1 / 20.1 |
| **live groups only (shipped)** | **49.1 / 8.08** | **73.1 / 11.7** | **97.1 / 16.2** | **121.1 / 19.5** |

(instructions / cycles per probe.) The shipped shape is best on both factors at every live count
except 63, where it costs 5 more instructions than the always-four-groups form and 3.0 fewer cycles.

## 3. Memory

| ring capacity | `sizeof(ReadLocalRobState)` | jemalloc class | delta vs base |
|---|---|---|---|
| 16 (base) | 296 B | 320 B | — |
| 32 (hypothetical) | 624 B | 640 B | +320 B |
| **64 (shipped)** | **1216 B** | **1280 B** | **+960 B** |

Size classes are from the tree's own `good_size()` (`src/base/alloc.h`), which is byte-identical to
jemalloc's table and verified against `nallocx` at boot.

The parent brief estimated ~768 B, which is the ring alone (48 extra slots × 16 B). The other
192 B is the sixty-four-entry tag mirror (128 B) that had to move out of the `Rob` — locked at 192
bytes with only sixteen to spare — plus six bytes of widened bitmap and the padding to the
64-byte alignment the vector load wants. The allocator then rounds 1216 to 1280 against 296 to 320,
so what a connection actually costs is **+960 bytes**.

MEASURED_RSS_TABLE

**Every armed connection pays this, including one that never writes**: the sidecar is allocated at
accept (`io_loop.h`), not on first write, so that an allocation failure can reject the connection
before it is registered rather than half-arm it.

## 4. Rate, instructions/op, cycles/op and IPC

SLOPE_TABLE

RATE_TABLE

## 5. Correctness

UNIT_AND_MUTATION

## 6. Batteries and differ

BATT_DIFFER

## 7. Files

* `lib.sh` — boot/guard/stop for this lane. Ports 8091-8094, server 48-55, load generators 184-191.
  Every boot is ss-guarded, every stop kills by PID, and **every load generator's CPU mask is read
  back out of `/proc` and checked before load flows** (`assert_pinned`): a `taskset` prefix that
  silently did not apply looks exactly like one that did, and an unpinned generator corrupts a
  verdict at both ends — ours, and whoever owns the cores it wandered onto.
* `inflight.sh` + `histreport.py` — section 1, against a `-DTOMO_RLHIST` build.
* `sizes.cc` — section 2's layout block.
* `codegen_ab.sh` + `codegen.cc` — is the sweep vectorised, and what does the rejected shape emit.
* `probe_cost.sh` + `probe_cost.cc` — section 2's instructions-per-rejected-probe table.
* `mem.sh` + `holdconns.c` — section 3.
* `measure_triad.sh` + `triad_report.py` — section 4's slope instrument (instr/op, cycles/op, IPC).
* `ab_triad.sh` + `ab_triad_report.py` — section 4's saturated ABBA A/B, counters beside every rate.
* `mutate.sh` — the falsification table for `tests/read_local_write_ring_unit.cc`, control included.
* `batteries.sh`, `expwide_preexisting.sh` — section 6.
* `validate.sh` — runs everything that needs the box, in sequence, so nothing overlaps.
* `build_arms.sh` — both arms from one tree; nothing is ever stashed.
