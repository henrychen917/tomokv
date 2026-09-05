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

---

## 2026-09-05 19:30 — resumed after the 19:20 usage-limit kill

**The pin changed, and every number taken under the old one is void.** The lane was on physical
48-55 with load generators reaching 184-191, which are the SMT siblings of physical 56-63 — another
lane's cores. Two lanes were sharing execution units. New allocation, and nothing outside it:

| | logical CPUs | physical | note |
|---|---|---|---|
| server | 58-61 | 58-61 | siblings 186-189 left IDLE, so server IPC has no co-tenant |
| load generators | 62-63,190-191 | 62-63 | may use its own siblings; nobody reports generator IPC |
| ports | 8300-8309 | | 8300 batteries/differ-A, 8301 differ-B, 8302 slope/instr |

Sections 1-3 above survive the re-pin: they are structural (in-flight histogram max = window − 1),
static (layout, size classes) or single-core (probe cost), and none of them is a shared-box rate.
Section 4 was never measured, and is measured on the new pin.

### The sizing policy now self-derives, by construction

`kWriteRingCapacity` was a literal `64` that happened to equal the window, with a one-way assert.
It is now `= kRobWindow`, and `kRobWindow` moved from `net/conn.h` into `net/rob.h` — the ROB's own
header, beside the ring sized from it, and re-exported to conn.h by inclusion. There is no second
number to forget and no knob: move the window and the ring follows.

`mutate.sh` gained **D1**, which is the check that the derivation is real rather than decorative:
shrink `kRobWindow` to 32 and the sidecar's `sizeof` lock and the Rob's structural assert must BOTH
fire. If the ring still carried its own literal, neither would.

`mutate.sh` also gained a vacuity guard. Three of its mutations used `str.replace` with no assert,
so when the capacity stopped being a literal they would have silently patched nothing, compiled the
unmutated tree, passed, and printed a row that reads as a survived mutation. Every mutation is now
digested before and after, and a patch that matched nothing says so.

### Ring overflows are counted in BOTH arms, from binaries that are not the measured ones

`ovf_patch.py` grafts a relaxed counter onto `read_local_write_enter_overflow()`; its three anchors
are textually identical in the base header and in this lane's, so one patch instruments both arms
and the counts are comparable (round-trip verified byte-identical on both). It is a separate pair of
binaries because PRE enters a conservative generation constantly at high write ratios — leaving the
counter in the measured build would put the diagnostic inside the arm it exists to describe.

### Cells are named by WRITE fraction now

w41 (41% writes, under the cliff — must not regress), w55 (the edge), w70 (over it — the target),
plus pure SET and pure GET nulls. `measure_triad.sh` follows with `READPCTS="59 45 30"`.

`ab_triad.sh` gained `RATELIMIT`: instructions/op at saturation is partly a spin measure, because
the faster arm polls less per operation. The `matched` phase rate-limits both arms to the same
delivered load, which is the geometry in which that column is a work measure.

### Order of the remaining work
`build → unit → sizes → mutate → codegen → probe → null → rate → matched → ovf → slope → mem →
batt → differ`, strictly sequential (`validate.sh`), gated on `laneguard.sh` and on the owner's
`quiet.done` being older than three minutes.

### 19:45-19:55 — two incidents worth keeping

**A neighbouring lane is parked on this lane's cores.** `wt-cyclemap/scratchpad/cyclemap/tkv-base`
(pid 1813128, up since 18:50, measured at 0.000 cores over three seconds) is pinned to 190-191,
which are the SMT siblings of physical 62-63 — this lane's own. It is idle, but idle is not a
guarantee, and the whole point of the re-pin was to stop two lanes sharing execution units. The
lane therefore uses only 58-61 and 186-189, where nothing foreign can run: **server 58-59, load
generators 60-61 plus siblings 188-189, two shards**. Every number in section 4 onward is taken on
that geometry; expanding it later would make the cells incomparable.

**Two runs shared one build tree for about three minutes.** A waiter was killed at 19:46 while the
`validate.sh` it had `setsid`'d kept running, and a second waiter started beside it. Two `make`s
then drove the same `build/` while `build_arms.sh` swapped `src/net/rob.h` under both — which can
compile an object from one arm's header into the other arm's binary, the exact shape of
`tomokv-pinned-source-is-not-pinned-binary`. `build/` was deleted rather than trusted and both arms
rebuilt from nothing. Two guards now exist: an `flock` held for the life of `run_when_clear.sh`, and
an EXIT trap so killing the waiter takes its run with it.

**And a self-match, twice.** `pgrep -f run_when_clear` and an `awk` over `ps` *args* both matched
this shell's own command line, which contains those strings; the kill that followed killed the tool
shell (exit 144) and, the second time, very nearly a neighbouring lane's compiler. Match on `comm`,
never on args, and confirm ownership with `readlink /proc/PID/cwd` before killing anything — the
`make` that looked like a leftover of ours was `wt-multirace`'s.

**19:52 — a second lane arrived on this lane's cores.** `./build/tomokv --port 8079 --thread-mode
2s --shards 4` (pid 1833363) is pinned to **60-63,188-191**, which overlaps the load-generator half
of even the reduced allocation. With `tkv-base` still on 190-191, the only part of 58-63/186-191
that no other lane can reach is **58-59 and 186-187** — two physical cores, which cannot hold a
server and a load generator on different physical cores at the same time.

Consequence, and it is the owner's to arbitrate: the correctness phases (unit, layout, mutation,
codegen, batteries, differ) are pass/fail and run anyway under `guard_soft`. The number phases
refuse under `guard`, and are held until the cores clear. Four arms are built and waiting:

    tomokv-pre      a5906e93547614a42067c7da9931f93b
    tomokv-post     5764edfb188073474bb613683af0b1fd
    tomokv-pre-ovf  4838b32eb2da3ce4bc50c0dc0b9709f5
    tomokv-post-ovf 5d0955230f641d3c8ba4ea47dce99af0

all four at zero warnings and zero errors, PRE and POST verified byte-different.

## Correctness, on the re-pinned tree (2026-09-05 19:47-20:04)

Four arms, all zero warnings and zero errors, PRE and POST verified byte-different:

    tomokv-pre      a5906e93547614a42067c7da9931f93b     (base 479922c0a)
    tomokv-post     5764edfb188073474bb613683af0b1fd     (this lane)
    tomokv-pre-ovf  4838b32eb2da3ce4bc50c0dc0b9709f5     (base + overflow counter)
    tomokv-post-ovf 5d0955230f641d3c8ba4ea47dce99af0     (lane + overflow counter)

| instrument | result |
|---|---|
| `tests/read_local_write_ring_unit.cc` | **14 of 14 ok**, including three 200k-frame soaks |
| layout locks | `Rob<64>` 192, sidecar 1216 / align 64, ring 64, keyset bound 16 — all held |
| mutation table | control **passes**; M1, M1b refused at compile time; M1c, M2, M2b, M3, M4 each fail their named cases |
| **D1 derivation** | window → 32 fires **both** the sidecar `sizeof` lock and the Rob structural assert |
| codegen | shipped sweep: 54 instructions, **1 vector compare**; flat form: 36 instructions, **0** |
| battery 1s (fused, armed) | **9 pass, 1 fail** — `expwide` |
| battery 2s | **11 pass, 0 fail** |
| `expwide` attribution | **PRE fails it identically** (`S1 MGET: the hook really widened the fan-out`, elapsed=0.000s, both arms, both reps) — the base branch's row, not this lane's, and it passes in 2s, so it is fused-mode-specific |
| differ canonical (partial) | every matrix reached passed with 0 diffs (hexpire, edgetime, xshard, xmove, bitmap …) before the phase was deliberately stopped |

The soak line worth keeping: at the full ROB window the precise ring **hoisted 50,691 of 87,251
reads** where the conservative regime hoists 0 — that is the mechanism this lane exists to buy.

**The 2s battery needed a harness fix, not a code fix.** It died at boot with "`--ratio`: 16 threads
but only 8 allowed cpus" because it still asked for the base lane's 6:10 after the pin shrank. The
ratio now scales that same shape to whatever mask it is given. The server was right to refuse.

**The owner reclaimed the box at 20:03:55** (`quiet.done` removed) and the watchdog stopped the run
before the measurement phases. Nothing was measured on top of the owner's own numbers. The
measurement phases -- `null rate ovf slope mem probe` -- are re-armed and will start on their own
once `quiet.done` is back and older than three minutes, this lane's cores are clear, and its ports
are free.

## The expwide S1 MGET row — static diagnosis, ahead of the reproduction

`DEBUG ATOMIC-FANOUT-DEFER` is implemented in the **scatter engine** (`src/cmd/scatter_engine.inc`
~2009) and the MULTI half (`src/cmd/multi.inc` ~1574). It widens a **cross-shard fan-out**. Under
`--thread-mode fused --read-local 1`, an MGET whose keys are all clean is served by the **read-local
path** instead — `enqueue_local_read` → the executor's local drain — which never enters the scatter
engine, so the hook cannot widen anything and S1's own vacuity guard fires: `elapsed=0.000s`.

Two facts already point at geometry rather than branch:

* this lane's batteries pass `expwide` under **2s** and fail it under **fused+armed**, on the same
  binary — the canonical gate boots split with read-local off, where MGET has no local path to take;
* `command_is_read_local_mget` is present in t-merge14, t-rlbatch and this lane alike, so the local
  MGET path is not something the base lane introduced.

**And the invariant itself appears to hold on the local path.** `src/core/ex_loop.h`:

```
1016:  const int64_t command_now_ms = cached_now_ms_;     // ONE snapshot, before the retry loop
1070:  if (deadline >= 0 && deadline <= command_now_ms)   // every key compared to that one instant
1212:  if (deadline >= 0 && deadline <= command_now_ms)
```

The snapshot is taken outside `for (attempt …)`, so it survives a generation retry, and a key found
past its deadline does not get served locally at all — it returns
`ReadLocalFallbackReason::Expired` and the command goes to the owner. So the local MGET is one
expiry cut per logical operation, which is exactly what S1 exists to police.

If the reproduction confirms this, the row is a **coverage hole, not a wrong answer**: the path that
now serves most MGETs is the one path S1 cannot widen, and the gate on t-merge14 never entered the
combination because it boots read-local off. The fix is then to make the invariant testable where
the command is actually served — a defer point inside the local MGET window — rather than to change
what the local path computes. **Confirmed by measurement before anything is written.**
