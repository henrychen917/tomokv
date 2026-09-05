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

## 2026-09-05 20:2x — armed and waiting on the marker

The owner accounted for all three foreign occupants (the 60-63/188-191 pair was the reply-code lane,
handed those cores by mistake and since finished; the parked `tkv-base` was the killed cycle-map
lane's leftover, since killed), so the lane is back on its **whole allocation**:

    server 58-60      load generators 61-63      siblings 186-191 idle      ports 8300-8309

`run_when_clear.sh expwide null rate ovf conn mset slope mem probe` is armed (pid 1874323) behind
the three gates and starts itself when `quiet.done` returns and is three minutes old. Where each
answer will appear:

| phase | file | the question it settles |
|---|---|---|
| `expwide` | `expwide_bisect.txt`, `s1repro-<arm>-<geom>.txt` | is the red row t-rlbatch's regression, or a coverage hole that opens only when read-local is armed? Three arms × two geometries, one tree, identical flags |
| `null` | `ab_null.txt` | what this rate instrument calls zero |
| `rate` | `ab_triad.txt` | w41 / w55 / w70 + pure SET + pure GET, rate, instr/op, cyc/op, IPC, hit share, srv cores |
| `ovf` | `ab_ovf.txt` | ring overflows per arm, both arms instrumented by one patch |
| `conn` | `regimes_conn.txt` | 512 vs 2048 connections with **DRAM fills/op** — does the +960 B footprint cost more than the demotion fix earns? |
| `mset` | `regimes_mset.txt` | MSET 8 vs 32 keys at p8 — what the OTHER fixed sixteen costs |
| `slope` | `triad.txt` | instr/op at matched work, the column that survives a co-tenanted box |
| `mem` | `mem.txt` | measured RSS per armed connection (section 3's `MEASURED_RSS_TABLE`) |

Pre-repin measurements are quarantined in `void-old-pin/` and must not be quoted: their load
generators sat on another lane's SMT siblings. Their **counters** are still indicative, because
core contention does not change whether a read was demoted — at 59% writes PRE demoted 4,621,326
reads (13.6% of them) and POST demoted 2,718 (~0.0%), and at 39% writes both demoted ~2,500. That
is the defect and the fix; it is not a verdict, because it never covered 70% writes and the rate
and IPC columns from that run are void.

**Nothing merges while the expwide row is red** — that is the owner's rule and this lane holds to it.

## The expwide row is NOT this lane's, and no longer gates it (owner ruling, 2026-09-05)

The owner reproduced it on the frozen train-9 mainline binary **e902c67d5**: under
`--thread-mode fused --read-local 1` it fails identically — `FAIL S1 MGET: the hook really widened
the fan-out (elapsed=0.000s)`, 1 of 101 checks — and passes with read-local off and in split mode.
Running all 32 gate feature batteries under fused+armed on mainline gives **30 pass, expwide and
climon2 fail**. The cause is exactly the coverage hole the static diagnosis predicted: the gate's
feature loop only ever boots split, and its fused section runs four batteries with read-local off,
so the fused+armed combination was never covered by anything.

Consequences for this lane, and they are narrow:

* **t-rlbatch is exonerated.** The row predates it; the base lane did not regress it.
* **A separate lane** off `t-merge14` adds the fused+armed feature leg to the gate and fixes both
  holes. **This lane does not write that fix** — duplicate work, by the owner's instruction.
* The `expwide` phase here still runs and still reports, because its counter columns are the
  evidence for *why* the hook cannot see the command. It is evidence, not a gate.
* **Merge bar for this lane:** `expwide` under fused+armed is excused until that lane lands.
  **Every other row must be green.**

Also noted: the connection regime reaches 512 and 2048 connections as **8 threads x 64** and
**8 threads x 256**, not the owner's rig shape of 32 x 16 and 32 x 64. Totals are what the
footprint term depends on, and the owner has accepted the shape; it is recorded in the table's own
row labels so nobody has to take that on trust.

## expwide S1: REPRODUCED, and it is mainline's — not this lane's, not t-rlbatch's

Three arms, two geometries, one tree, identical flags, same box, same minute
(`expwide_bisect.sh`, `s1_mget_repro.py`). `m14` is every src file that differs from t-merge14,
taken from t-merge14 (md5 33ba9bc3…).

| arm | geometry | MGET elapsed | mget_local_hits | verdict | S1 |
|---|---|---|---|---|---|
| m14 | fused + read-local 1 | **0.000 s** | **1** | SERVED LOCALLY, hook bypassed | **FAIL** |
| m14 | 2s + read-local 0 | 0.400 s | 0 | entered the deferred fan-out | pass |
| pre (t-rlbatch) | fused + read-local 1 | **0.000 s** | **1** | SERVED LOCALLY, hook bypassed | **FAIL** |
| pre | 2s + read-local 0 | 0.400 s | 0 | entered the deferred fan-out | pass |
| post (this lane) | fused + read-local 1 | **0.000 s** | **1** | SERVED LOCALLY, hook bypassed | **FAIL** |
| post | 2s + read-local 0 | 0.400 s | 0 | entered the deferred fan-out | pass |

EXISTS is the in-test control and enters the deferred fan-out in **every** row, both geometries,
all three arms — so the hook itself works and the 400 ms window really opens.

The counter settles what elapsed time alone could not: `read_local_mget_local_hits` moves by
exactly **1** on the MGET in fused+armed and by **0** in split. The command is served by the
read-local path, which the scatter engine's `ATOMIC-FANOUT-DEFER` hook does not cover, so S1 cannot
widen the window it is asked to prove opened — and it fails rather than pass vacuously, which is the
test being right. **All three arms behave identically**, which exonerates t-rlbatch and this lane
both. Matches the owner's independent finding on e902c67d5 exactly.

## The first null FAILED ITS OWN CONTROL, and the geometry is why

Same binary against itself (PRE vs PRE), 3 server / 3 load cores:

| cell | rate delta (same binary!) | server cores burned (of 3) |
|---|---|---|
| 41% writes | **−4.60%** | 1.83 / 1.96 |
| 55% writes | **−12.14%** | 1.88 / 2.00 |
| 70% writes | **−5.62%** | 2.02 / 1.99 |
| pure SET | −2.52% | 2.01 / 2.04 |
| pure GET | +0.32% | 1.54 / 1.41 |

Per-visit at 55% writes: 3.60 → 2.88 → 3.50 → 3.66. A twelve percent "delta" between two runs of
one binary is not a measurement, and the reason is in the last column: **the server burned about
two of the three cores it was given in every cell**, so it was never the bottleneck. The rate was
the load generator's limit, and the swing is that limit moving — eight generator threads on three
physical cores is nearly three to a core.

Corrected, from the data rather than by guess: **server 58-59** (two cores, two shards — which is
what this workload actually delivers), **load generators 60-63** (four cores, so eight threads sit
two to a core). Siblings 186-191 stay idle. No rate from the 3/3 geometry is quoted anywhere.


## 2026-09-06 00:30 — the instrument, rebuilt: what the corrected geometry actually showed

The 2/4 re-pin ran, and it half-worked. Its medians came back honest where the 3/3 pin's had not
(PRE against PRE: −0.03% at 41% writes, +0.14% at 55%, +0.57% at 70%, +0.01% pure SET), but two
things in the same output say the instrument was still not fit to answer a 2-4% question:

* **the read-only control swung 14.17% visit to visit** — 2.42, 2.77, 2.45, 2.66 M ops/s on one
  binary — so a −3.4% at 70% writes had no floor to be measured against;
* **the server burned 1.75 of its 2 cores in every cell of every visit**, at rates ranging from
  2.48M to 3.95M. A duty cycle that does not move when the work per operation moves by 50% is not
  a saturated server, and core burn alone cannot say which way.

### The cycles column was 1/rate wearing a disguise

`perf stat -C 58-59` counts every cycle those two cpus spend in C0 — the idle task's included. Read
the null's raw cycle counts across cells whose rates differ by half:

    92,418,280,288   92,501,115,865   92,536,430,971   92,489,865,776   …

Sixteen visits, five cells, four rounds, and the count is the same to a fifth of a percent every
time, because it is wall time × frequency × two cores and nothing else. **Cycles/op computed from
it is algebraically 1/rate, and IPC is instructions divided by a constant.** Three of the four
reported columns were two independent quantities, and one of them silently restated the column it
existed to explain. Every cycles/op and IPC number taken before this fix is withdrawn; rate,
instructions/op and the counters stand.

`perf` now attaches to the **server process** (`-p $SRV`), so cycles/op is work per operation and
IPC is the server's own occupancy. perf refuses to take a pid and a command together — it counts
the command and reports `<not counted>` for the pid, *silently* — so the window is opened by
attaching before load and closed with SIGINT when the generator exits.

**DRAM fills now ride in every window, not only the connection regime.** Instructions and cycles
cannot tell a bigger working set from more work, and a bigger working set is precisely what this
lane spends: +960 bytes on every armed connection. Fills per operation is the column that prices it.
This is the lesson the connection-side allocation lane paid for tonight — 57 instructions saved per
armed SET and 0.6% rate lost, because the record then migrated between cores twice per lifecycle.

### The generator was rationed by the scheduler, not by the hardware

Eight memtier threads were pinned to **four logical cpus** (60-63) while 188-191 — the other
hardware thread of those same four physical cores, inside this lane's own allocation — sat idle by
a choice that had been made for the server's siblings and copied to the generator's without the
reason coming with it. The reason is a law only for the server: nothing may run on 186-187, because
a server sharing execution units reports an IPC that belongs to its co-tenant. Nobody reports
generator IPC. The generator now gets one hardware thread per memtier thread.

### And the saturation claim is now tested rather than asserted

`satcheck.sh` holds the server fixed and grows the generator — 8 threads on 4 logical cpus, then on
8, then 12 threads, then 16, connections held at 512 — and watches the rate. The first rung on
which the rate stops climbing while the generator is still growing is the first rung on which the
server is the bottleneck, and no rate A/B runs below it. It prints per-thread server cpu beside
each rung, so a shard imbalance cannot hide inside a plausible total.

`ab_triad_report.py` now states the floor **per cell and per column** rather than borrowing the
read-only cell's rate spread for everything: instructions/op is a far quieter quantity than rate on
the same runs, and holding it to the rate's floor would discard the one column able to resolve this.


## What the 2/4 run already settled, once the right column is read

Three runs exist on the 2/4 pin — a same-binary null, a three-round A/B and a one-round A/B on the
overflow-instrumented pair. Their cycles/op and IPC columns are withdrawn (see above: they were
1/rate). Their **instructions per operation** and their **counters** are not, and read per visit
rather than as a median they answer more than the rate ever did.

### The instrument is quiet in instructions and loud in rate — by a factor of ten

Max-to-min spread across every visit of the SAME-BINARY null:

| cell | instr/op spread | rate spread |
|---|---|---|
| 41% writes | **0.59%** | 1.98% |
| 55% writes | **0.61%** | 3.47% |
| 70% writes | **0.37%** | 5.25% |
| pure SET | **0.08%** | 3.66% |
| pure GET | 11.40% | 14.17% |

Four of the five cells resolve instructions per operation to better than a percent while their rate
is three to five times noisier. That is the ordinary shape of this instrument
(`thredis-instr-per-op-spin-inflation` warns about the opposite failure, and the matched-rate phase
exists for it) — and it means the verdict has to be argued in instructions and cycles, with rate as
corroboration, not the other way round.

**The pure-GET cell is broken and is not usable as a null.** An 11.4% swing in instructions per
operation on one binary is not scheduling noise; the server is doing materially different amounts of
work per GET from visit to visit, at a local hit share of 60.7% and a p99 of 51 ms. It is re-run on
the new geometry before anything is claimed from it.

### And in instructions, the A/B does not overlap at all

The A/B's visits run PRE POST POST PRE inside each round. At 70% writes, three rounds:

    PRE 4317   POST 4422   POST 4431   PRE 4335
    PRE 4336   POST 4425   POST 4429   PRE 4313
    PRE 4328   POST 4428   POST 4433   PRE 4320

Six PRE visits span 4313-4336, six POST visits span 4422-4433, and **no PRE visit is within
eighty-six instructions of any POST visit** against a null floor of 0.37%. The same clean
separation holds at 55% writes and at pure SET. This is a result, and its sign is the wrong one:

| cell | PRE instr/op | POST instr/op | delta | null floor |
|---|---|---|---|---|
| 41% writes | 4695 | 4718 | **+23  (+0.5%)** | 0.59% |
| 55% writes | 4675 | 4768 | **+94  (+2.0%)** | 0.61% |
| 70% writes | 4324 | 4429 | **+105 (+2.4%)** | 0.37% |
| pure SET | 3395 | 3438 | **+43  (+1.3%)** | 0.08% |
| pure GET | — | — | unusable | 11.40% |

Solve the two-term model (`w` per write, `r` per read) against the pure-write cell: `w = +43`
instructions per write, and then `r` is **+9 at 41% writes, +156 at 55%, +249 at 70%**. The read-side
term is not a constant probe cost — it climbs with how many writes are live, which is what the ring
was built to do.

### Why the old ring is cheap, and it is the same reason it is wrong

`read_local_resolve_pending_body` sets `write_head = 0; write_count = 0` when it enters a
conservative generation. **A ring that has given up does no work at all**: nothing to insert into,
nothing to tag, nothing to prune, and every read short-circuits to a demotion without walking
anything. PRE spends most of its time there at 55% writes and above, so the machinery this lane
grew is machinery PRE was mostly not running. Sizing the ring to the window does not add a walk to
a server that was doing a shorter walk — it adds a walk to a server that had stopped walking.

**PRE's defect is also PRE's optimisation, and that is the whole trade this lane has to price.**

### The premise that 41% writes never overflows is false, and the arithmetic says so

The cell was chosen as the one where a sixteen-slot ring is never full. At a pipeline depth of 32,
a connection's live writes are a binomial draw from its in-flight window, so:

| write fraction | P(16 or more of 32 in flight are writes) | measured overflow entries | cadence |
|---|---|---|---|
| 41% | **0.196** | 393,732 | 1 per 39 writes |
| 55% | 0.773 | 618,788 | 1 per 33 writes |
| 70% | 0.995 | 765,228 | 1 per 36 writes |
| 100% | 1.000 | 1,852,068 | 1 per 31 writes |

A one-in-five window is not "never". **The sixteen-slot ring overflows in every regime this lane
measured, including the control**, and the near-constant cadence of one entry per thirty-odd writes
across four very different write fractions is the signature of a connection that re-enters a
conservative generation about as often as one pipeline window drains. POST records **zero** in every
cell of every run.

**The binomial column above is the wrong model, and the connection regime is what says so.** On the
same arm, the same 512 connections and the same depth, `--ratio=1:1` demoted **902** reads for an
in-flight write and served 99.9% of its reads locally, while `--ratio=55:45` demoted **3,007,793**
and served 82.1%. Five points of write fraction cannot do that. A change in the SHAPE of the stream
can: a ring overflows on a RUN of writes, not on their long-run average, and a load generator that
emits its ratio as repeating blocks makes "55:45" a fifty-five-write run while "1:1" is an
alternation that never puts more than sixteen writes in a thirty-two-deep window. Read that way the
observed cadence fits far better than the binomial does — a block longer than the window re-enters
conservatism about once per window, which is one entry per ~32 writes against the 33 and 36
measured at 55% and 70%, where the binomial predicts one per 55 and one per 70.

`ratio_shape.sh` decides it, by holding the fraction constant and moving the block: **1:1 against
50:50** (both 50% writes, block 1 against 50) and **11:9 against 55:45** (both 55% writes, block ~11
against 55). If the demotions track the fraction, the matrix's labels are right. If they track the
block, this lane's matrix is a write RUN-LENGTH sweep wearing a write-fraction label, and every row
of the verdict has to say so. Until that phase reports, the overflow-probability column above is
withdrawn and only the measured counts stand.

Zero in POST is also what proves the counter is measuring capacity. `read_local_write_enter_overflow`
has two callers — a capacity-full ring, and a write that can never refine (a wide multi-key write, a
point write under an evicting maxmemory policy). Both increment the graft. POST reads zero, so the
second door never fired in these workloads; therefore every one of PRE's counts came through the
first. The claim that capacity overflow is unreachable at the full window is not merely un-falsified
here, it is measured against a counter that fires 3.6 million times in the arm that can reach it.

### RSS per armed connection, measured

    PRE   2000 connections   delta 20,224 kB   10,354.7 B/connection
    POST  2000 connections   delta 22,124 kB   11,327.5 B/connection
    ---------------------------------------------------------------
    POST - PRE                                    +972.8 B/connection

Against +960 predicted from `good_size(1216) - good_size(296)` = 1280 - 320. The allocator table and
the resident cost agree to 1.3%, so the footprint term is exactly the size the layout lock says.


## The cost splits in two, and only one half is about the ring's SIZE

This matters for what the verdict can recommend, so it is worth stating before the numbers land.

**The bookkeeping term is a function of LIVE writes, not of capacity.** The sweep walks live groups
only — the lowest set bit of `live` names the first group holding a live slot and clearing that
group's mask walks straight to the next — so a connection carrying nine live writes pays for one
group whether the ring has sixteen slots or sixty-four (section 2). Insert, tag write and prune are
each per write. At a pipeline depth of 32 a connection can hold at most 31 live writes, which is two
groups, **and a 32-slot ring would execute exactly the same instructions as the 64-slot one.**

**The footprint term is a function of capacity, and only of capacity**: +972.8 measured bytes on
every armed connection, whether it writes or not, because the sidecar is allocated at accept.

So the two candidate redesigns fix different halves and neither fixes both:

| | bookkeeping (+43/write, +9…249/read) | footprint (+973 B/conn) | overflow at deep pipes |
|---|---|---|---|
| ring 64 = window (this lane) | paid in full | paid in full | impossible by construction |
| ring 32 (a policy cap at p32) | **paid in full, unchanged** | +320 B instead of +973 | returns above p32 |
| grow on demand from live writes | **paid in full, plus the growth check** | ~0 for light connections | impossible, if it grows to 64 |
| ring 16 (base) | not paid — it gives up | not paid | constant, in every regime measured |

**The only design that avoids the bookkeeping is the one that gives up**, because the bookkeeping IS
the tracking. That is the shape of the decision the connection cell now has to settle:

* if POST's DRAM fills per operation grow with connection count — worse at 2048 than at 512 — the
  regression is the footprint, and **grow-on-demand is the recommendation**: it keeps the whole
  demotion fix and returns almost all of the memory;
* if the regression is the same size at 512 and 2048, the footprint is not the lever, the cost is
  bookkeeping, and no amount of re-sizing recovers it. The question is then whether a precise local
  read is worth what it costs to know it is safe — a question about the read-local design, not about
  this lane's constant, and the honest answer to it may be to shelve.


## The probe-cost phase had been dead since the derivation landed, and printed errors where rows go

`probe_cost.sh` built its `base16` arm by swapping **only** `src/net/rob.h` for the base branch's
copy. That worked until this lane moved `kRobWindow` out of `src/net/conn.h` into `src/net/rob.h`:
after that, a base `rob.h` beside this tree's `conn.h` defines the constant nowhere, and the arm
stopped compiling. The 22:02 run produced **no rows at all** — sixty lines of compiler error into
the results file, and the script carried on to the next arm without a word.

Two fixes, and both are lessons this tree had already learned somewhere else:

* the file list is **computed from the diff** (`git diff --name-only $BASE -- src/`), exactly as
  `build_arms.sh` does and for exactly the reason its comment gives — a hand-written list goes stale
  when the tree changes shape, which is the one moment it matters;
* **a failed build fails the phase.** A build error is not a table row, and a script that prints one
  where a measurement belongs has published a result it does not have.

Consequence for section 2: its instructions-per-rejected-probe table is **not currently backed by a
file in this run's output directory**. The `void-old-pin/` copy contains an older sweep shape
(the always-four-groups form, 68.1/84.1/100.1/116.1) rather than the shipped live-group walk. The
phase is re-run on this pin before the table is quoted; the argument it supports — that the walk is
bounded by live writes and not by capacity — is separately visible in the disassembly
(`codegen.txt`) and in the shipped code, but the numbers need their own run.


## MEASURED: the matrix is a write RUN-LENGTH sweep, not a write-fraction sweep

`ratio_shape.sh`, one binary, one boot, four cells, 512 connections at depth 32:

| memtier ratio | write fraction | block | read-local share | reads demoted for an in-flight write | M ops/s |
|---|---|---|---|---|---|
| `1:1` | 0.500 | 1 | **99.9%** | **738** | 2.456 |
| `50:50` | 0.500 | 50 | 85.7% | **2,072,492** | 2.555 |
| `11:9` | 0.550 | 11 | 79.4% | 2,385,758 | 2.156 |
| `55:45` | 0.550 | 55 | 81.8% | 2,428,006 | 2.528 |

**At the identical 50% write fraction, alternating writes demote 738 reads and blocked writes demote
2,072,492 — a factor of two thousand eight hundred.** At 55%, a block of eleven demotes as much as a
block of fifty-five. The write fraction is not the variable; the run length is, and it has a
threshold rather than a slope.

The threshold is the ring, and the arithmetic is exact. A connection's live writes are those
published and unretired inside its 32-deep pipeline window. Alternating puts at most sixteen writes
in that window — the capacity, never past it. A block of eleven can put twenty-two there (two blocks
with nine reads between them), which is over. A block of fifty puts thirty-one. So:

* `1:1` — **the only cell in this entire run in which the sixteen-slot ring does not overflow**, and
  the fit is exact rather than approximate: alternating tops out at fifteen live writes plus the one
  being committed, because the committing write holds a window position no ring entry can (the same
  arithmetic section 1 measured as "one short of the window"). Fifteen is under sixteen, so the ring
  never fills, and the 738 demotions that remain are genuine same-key conflicts rather than
  conservative generations;
* every other cell, including the control chosen as the one that would not overflow, is over the
  threshold and stays there.

### What that does to this lane's labels, and to its case

The three-regime matrix's cells all sit **above** the threshold, so they are three samples of one
regime rather than three points on a curve — which is exactly why their overflow cadence was
near-constant at one entry per thirty-odd writes and why their instructions/op deltas cluster. The
label "41% writes (under the cliff)" was wrong twice over: it is not under the cliff, and the cliff
is not made of write fraction.

**And the 1:1 connection regime is the most useful cell in the run precisely because nothing
happens in it.** Both arms serve 99.9% of reads locally there and neither ring overflows, so its
deltas — +1.01% instructions/op at 512 connections and +1.76% at 2048 — are the **pure price of
carrying the bigger ring where it buys nothing at all**. That is the number a workload of
alternating readers and writers pays for this change, and it is the number that decides whether the
change may be default-on.

The question the verdict has to answer is therefore not "is 64 better than 16 at 70% writes" but
**"how much of the world writes in runs longer than sixteen per connection-window, and what does the
rest pay for it?"**


## Correctness, as it stands on this tree (unchanged by tonight's instrument work)

| instrument | result |
|---|---|
| `tests/read_local_write_ring_unit.cc` | **14 of 14 ok**, including three 200k-frame soaks |
| layout locks | `Rob<64>` 192, sidecar 1216 / align 64, ring 64, keyset bound 16 — all held |
| mutation table | control **passes**; M1, M1b refused at compile time; M1c, M2, M2b, M3, **M4** each fail their named cases |
| **D1 derivation** | shrinking `kRobWindow` to 32 does not compile: **both** the sidecar `sizeof` lock and the Rob's structural assert fire |
| codegen | shipped sweep 54 instructions with **1 vector compare**; the flat form 36 instructions with **0** |
| battery 1s (fused, armed) | 9 pass, 1 fail — `expwide`, which is mainline's (owner-confirmed on e902c67d5) and excused |
| battery 2s | **11 pass, 0 fail** |
| differ canonical | every matrix reached passed with **0 diffs** (string, list, set, zset, hash, hexpire, edgetime, xshard, xmove, bitmap) before the phase was deliberately stopped |
| `expwide` attribution | m14, PRE and POST all fail identically under fused+armed and all pass in split — not this lane's, not t-rlbatch's |

The soak line worth keeping: at the full ROB window the precise ring **hoisted 50,691 of 87,251
reads** where the conservative regime hoists 0. The mechanism works. Everything below is about what
it costs.


## Refinement: at a saturated server with fixed duty, cycles/op IS the rate column

Switching perf to the server process fixed a real defect — `-C` was counting the idle task's cycles
too — but it did not make cycles/op a second measurement, and the corrected run says so plainly.
Six same-binary rows, cells whose rates range from 2.51 to 4.02 M ops/s:

| cell | rate M/s | instr/op | cyc/op | fills/op | srv cores | Gcycles/s |
|---|---|---|---|---|---|---|
| 41% writes | 2.515 | 4675 | 2452 | 8.65 | 1.85 | **5.750** |
| 55% writes | 2.506 | 4680 | 2464 | 8.99 | 1.86 | **5.758** |
| 70% writes | 2.728 | 4295 | 2264 | 8.75 | 1.86 | **5.754** |
| pure SET | 4.017 | 3395 | 1531 | 8.36 | 1.85 | **5.741** |
| pure GET | 2.577 | 4829 | 2394 | 6.75 | 1.86 | **5.752** |

**The last column is flat to three tenths of a percent** while the workload changes completely,
because the server sits at 1.85-1.86 cores of its two at 3.09-3.11 GHz whatever it is doing. Cycles
per second is therefore a constant of this geometry, and

    cycles/op = 5.75e9 / rate

exactly. IPC = instructions / cycles is then instructions-per-op times rate over the same constant,
so it is derived twice over. **Three of the four columns in the original table were one measurement
wearing three hats**, and correcting the perf target changed which constant they share rather than
making them independent.

What is genuinely independent, and what this lane's verdict must therefore be argued from:

* **rate** — and cycles/op is the same number, so the owner's "judge by cycles/op" is satisfied by
  judging by rate here, not violated by it. Cycles/op only becomes a second measurement when the
  two arms sit at DIFFERENT duty, and the srv-cores column is what says whether they do;
* **instructions per operation** — the quiet column, 0.08-0.61% null floor against rate's 2-5%;
* **DRAM fills per operation** — now real rather than a cpu-window artifact, and the only column
  that can tell a bigger working set from more work. It runs 8.4-9.0 per operation on the write
  cells and 6.75 on pure GET, which is a great deal of memory traffic and exactly the term the
  +972.8 bytes per armed connection could move.


## THE NULL, on the corrected instrument — it passes, and it says which column may be read

Same binary in both arms (`tomokv-pre` against itself), server 58-59 with two shards, eight
generator threads on 60-63,188-191 one per hardware thread, 512 connections at depth 32, nine to ten
visits per cell.

| cell | rate delta | instr/op delta | **rate floor** | **instr/op floor** | fills/op floor |
|---|---|---|---|---|---|
| 41% writes | **−0.05%** | **−0.06%** | 4.21% | **0.24%** | 8.99% |
| 55% writes | **+1.34%** | **−0.11%** | 2.84% | **0.34%** | 6.89% |
| 70% writes | **+0.45%** | **+0.13%** | 3.49% | **0.30%** | 6.87% |
| pure SET | **+0.56%** | **+0.01%** | 3.23% | **0.06%** | 8.98% |
| pure GET | +2.78% | −1.05% | 12.68% | 9.11% | 23.90% |

("floor" is that cell's max-to-min spread across every visit of the run — what the instrument does
to one binary measured against itself.)

**Four of five cells come back inside a tenth of a percent on instructions per operation and inside
1.4% on rate.** The instrument works, and the stated floors for the rest of this lane are:

* **instructions per operation: 0.34%** — the worst of the four usable cells;
* **rate: 4.2%** — so a rate delta under four percent is not a result here, however many rounds it
  is averaged over;
* **DRAM fills per operation: 9.0%** — real now, but far too coarse to price a working-set change
  of the size this lane makes.

**The pure-GET cell is excluded, on its own evidence rather than on inconvenience**: 12.68% rate and
**9.11% instructions per operation** on one binary against itself. A cell that cannot reproduce its
own instruction count to a tenth of that of its neighbours is not measuring the server, and nothing
is claimed from it in either direction.

And cycles/op mirrors rate exactly, as the fixed-duty arithmetic said it must: −0.05/+1.34/+0.45/
+0.56/+2.78 against +0.05/−1.35/−0.46/−0.58/−2.72. It is the same column with its sign flipped.

**Consequence for the verdict**: this lane's effect must be argued in instructions per operation,
where the floor is 0.34% and the earlier A/B measured +0.48%, +2.00%, +2.41% and +1.28% — every one
of them resolvable. It cannot be argued in rate, where the floor is 4.2% and the largest effect
measured was −3.4%.


## THE MATRIX, on the corrected instrument (3 rounds, 6 visits per arm)

| cell | rate | **instr/op** | fills/op | local share PRE → POST | reads demoted PRE → POST |
|---|---|---|---|---|---|
| 41% writes | +0.31% | **+0.43%** | −0.65% | 86.5% → **94.6%** | 2,041,627 → **0** |
| 55% writes | −0.17% | **+1.44%** | −3.94% | 81.9% → **98.9%** | 2,870,423 → **168** |
| 70% writes | −2.13% | **+1.96%** | +1.97% | 86.6% → **100.0%** | 1,543,562 → **217** |
| pure SET | −0.84% | **+1.27%** | +4.28% | — | 0 → 0 |
| pure GET | +1.01% | −0.66% | −0.63% | 60.6% → 60.6% | 0 → 0 |
| *null floor* | *4.21%* | ***0.34%*** | *8.99%* | | |

**Every instructions-per-operation delta on the four usable cells is above the floor, and every rate
delta is below it.** The earlier run on the same pin measured +0.48%, +2.00%, +2.41% and +1.28% for
the same four cells: two independent runs, same signs, same magnitudes.

**The mechanism is not in doubt and never was.** Write-demotions go from two to three million to
between zero and 217, the read-local hit share goes from 82-87% to 95-100%, and the ring-overflow
counter reads zero in POST in every cell of every run against 393,732 to 1,852,068 in PRE.

Solving the two-term model against the pure-write cell again: **+43 instructions per write**
(identical to the first run), and a read-side term of **+4, +97, +180** instructions as the write
fraction rises. The lane costs what it costs because the ring now does work the old one had
stopped doing.

## THE CONNECTION CELL — and it answers the grow-on-demand question with a No

1:1 alternating at depth 32, which the ratio-shape phase established is **the one shape where the
sixteen-slot ring never fills**. Both arms serve 99.9-100.0% of reads locally and demote fewer than a
thousand; nothing this lane built is doing anything here.

| cell | rate | instr/op | **fills/op** | local share | demoted PRE / POST |
|---|---|---|---|---|---|
| 512 connections (8 × 64) | +0.40% | −0.44% | −3.60% | 99.9% / 99.9% | 907 / 934 |
| 2048 connections (8 × 256) | +0.04% | −0.63% | +0.25% | 100.0% / 100.0% | 27 / 14 |

**and this cell cannot resolve instructions per operation at all.** Its own per-visit spread is
**5.8-8.2%**, twenty times the matrix's 0.34% floor — 4951, 5186, 5009, 5115, 5370 for the identical
PRE configuration. The one-round render of this same phase said +2.77% at 512 connections; three
rounds later it says −0.44%. **A number that changes sign when the data doubles is noise, and the
+2.77% is withdrawn.**

The pattern in which cells are quiet is worth keeping: the four cells that resolve to a tenth of a
percent (41/55/70% writes, pure SET) are the ones where reads are mostly *demoted* or absent, and
the two that will not resolve at all are **pure GET (60.6% local, 9.11% spread)** and **1:1
alternating (99.9% local, 5.8-8.2% spread)** — the two cells where the read-local path carries the
most traffic. Whatever varies from boot to boot in that path — most likely how a connection's keys
fall across the two shards — varies the instruction count with it. That is a property of read-local,
not of this lane, and it is the reason the pure-cost question below cannot be answered as sharply as
the benefit question.

**DRAM fills per operation do not grow with connection count** — POST is 0.366 fills/op *below* PRE
at 512 and 0.466 below at 2048, both inside the 9% fills floor, and the delta does not widen when
the connection footprint quadruples. The +972.8 bytes on every armed connection is real memory and
it is **not** what limits this server at 2048 connections.

That is the answer to the question the cell was built for: **the ring does not need to grow on
demand.** Static sizing to the ROB window is not the problem, because the footprint is not the cost.
The cost is the bookkeeping, which as section "the cost splits in two" argues is a function of live
writes and not of capacity — so no re-sizing, dynamic or static, recovers any of it.

What the cell can say about the pure cost is bounded rather than sharp: **at 1:1, where neither ring
overflows, the rate moves +0.40% and +0.04% and the instructions move less than this cell can
resolve.** So the change is not visibly expensive where it does nothing — but "not visibly" means
against a 6-8% instruction floor, and that is the honest statement rather than a claim of free.


## What read-local ITSELF is worth in this geometry — and it is the whole explanation

One binary (`tomokv-pre`), one geometry, one knob. `--read-local 0` against `--read-local 1`:

| shape | read-local | M ops/s | instr/op | p99 ms | p99.9 ms | local share |
|---|---|---|---|---|---|---|
| 1:1 alternating (ring never fills) | **off** | **4.602** | **2446** | 4.09 | 8.2 | 0% |
| 1:1 alternating | on | 2.491 | 4980 | 35.33 | 614 | 99.9% |
| | **on vs off** | **−45.9%** | **+103.6%** | | | |
| 55:45 blocked (ring gives up) | **off** | **4.619** | **2451** | 4.05 | 7.8 | 0% |
| 55:45 blocked | on | 2.579 | 4678 | 41.98 | 83 | 81.9% |
| | **on vs off** | **−44.2%** | **+90.8%** | | | |

Checked before believing: both arms report **zero misses**, the preload pins dbsize to keymax, and
the blocked cell's SET/GET split is 2,465,241 / 2,016,293 — exactly 55:45. The workload is the same
in both arms. Writes speed up as much as reads, because `--read-local 0` takes the whole apparatus
away: no sidecar, no write ring, no RYOW tracking, not merely no local reads.

**This explains every number this lane has produced, and it does so without any of them being
wrong.** In this geometry a read served locally costs about twice a read demoted to its owner. PRE's
overflowing ring demotes two to three million reads per cell; POST's correctly sized ring converts
almost every one of them into a local read. So POST does more of the expensive thing and less of the
cheap thing, and its instruction count rises by exactly the shape the two-term model found:
**+43 per write (ring bookkeeping) and +4, +97, +180 per read as more reads get converted.**

The lane did what it set out to do. What it bought is worth less than nothing here.

### The caveat that has to travel with this, and it is a large one

**Two shards on two cores is a small geometry**, and read-local's cost is a coherence cost: an io
thread serving a read locally pulls the owning shard's lines into its own cache. With two shards
that is a coin flip per read, and the two cores fight over one working set. The owner's box runs
sixteen. **This lane's every cell was measured at two shards, because that is the geometry in which
the null passes on the cores this lane owns**, and the read-local tax may be a different size, or a
different sign, at sixteen. That is the first thing to check on a bigger box, and it is a question
about read-local rather than about the ring.

What does NOT depend on shard count: the ring's own bookkeeping (+43 instructions per write, from
the pure-write cell), the overflow arithmetic (a 32-deep pipeline cannot put more than 31 writes in
a window, and 16 slots cannot hold them), the RSS (+972.8 bytes per armed connection) and the whole
correctness column.


## The overflow counter, on the instrumented pair (2 rounds) — the falsifiable claim, tested

| cell | **PRE ring overflows** | **POST** | PRE reads demoted | POST | local share PRE → POST | instr/op |
|---|---|---|---|---|---|---|
| 41% writes | 388,594 | **0** | 2,075,766 | **0** | 86.6% → 94.3% | +0.49% |
| 55% writes | 618,816 | **0** | 3,012,506 | 162 | 82.0% → 98.9% | +1.40% |
| 70% writes | 750,156 | **0** | 1,621,672 | 188 | 86.6% → 100.0% | +2.08% |
| pure SET | 1,902,381 | **0** | 0 | 0 | — | +1.26% |
| pure GET | 0 | 0 | 0 | 0 | 60.4% → 60.2% | (excluded cell) |

Against the earlier instrumented run's 393,732 / 618,788 / 765,228 / 1,852,068 — the counters
reproduce to within 2%. **POST's assertion that capacity overflow is unreachable at the full window
survives a counter that fires 3.66 million times in the arm that can reach it**, across three
separate runs.

And the instructions column agrees with itself across three independent runs: +0.43/+1.44/+1.96/
+1.27 (clean pair), +0.49/+1.40/+2.08/+1.26 (instrumented pair), +0.48/+2.00/+2.41/+1.28 (the
earlier pin). This is not a noisy measurement.

## At MATCHED delivered load — where the cost is largest, and where it reaches cells the ring never touches

Both arms rate-limited to 3,991 ops/s per connection; delivered rate matched to **0.03%** in every
cell, so cycles per operation is a work measure and not a restatement of the rate, and the server
runs at about half of its two cores rather than at saturation.

| cell | rate | **server CPU per unit work** | instr/op | cyc/op | **fills/op** |
|---|---|---|---|---|---|
| 41% writes | +0.03% | 1.200 → 1.265 cores **(+5.4%)** | +3.69% | +5.15% | **+9.96%** |
| 55% writes | +0.00% | 1.110 → 1.185 **(+6.8%)** | +5.82% | +6.70% | **+8.29%** |
| 70% writes | +0.00% | 1.075 → 1.140 **(+6.1%)** | +3.90% | +6.13% | **+5.74%** |
| pure SET | −0.00% | 0.950 → 0.970 **(+2.1%)** | +0.79% | +1.95% | **+7.79%** |
| pure GET | +0.01% | 0.990 → 1.065 **(+7.6%)** | +5.69% | +7.54% | **+3.09%** |

**The pure-GET row is the one to read twice.** A connection that never writes never touches the ring
— and it still costs 7.6% more CPU per operation, with fills up 3.1%. Whatever that is, it is not
the ring logic; it is the **+972.8 bytes allocated on every armed connection at accept**, paid by
connections that will never use them.

So the footprint does cost, but only where there is slack to see it. At saturation (the conn cell at
2048 connections) fills per operation did not grow at all; at half load every cell's fills rise
3-10%. A saturated server is already missing on everything; a half-loaded one is not, and that is
where an extra fifteen cache lines per connection shows up.

**This is the cell that most nearly rescues the grow-on-demand design** — and it still does not,
because grow-on-demand would only help connections that write little, while the pure-GET row shows
the cost landing on connections that write *nothing* and would therefore never grow their ring.
A ring that grows on demand from zero would help exactly this row; a ring that grows on demand from
the base sixteen would not. That is a different change from the one this lane built, and it is worth
one measurement before it is worth any code.


## Two facts about the knob that frame everything above

**`--read-local` defaults to 0** (`src/core/config.h:317`). Everything this lane changes lives
behind an opt-in flag, so every cost measured here is paid only by a server that has switched the
feature on — and the +972.8 bytes per connection are allocated only on such a server. That is the
difference between a regression and a tuning choice, and it is worth stating plainly before the
verdict.

**`--read-local 0` is a fair control.** `src/main.cc:183` shows the flag selecting between the local
read lane and "the ordinary owner-task path" — the same path split mode uses — rather than
disabling a correctness guarantee or short-cutting the workload. The 2x measured above is the price
of the feature against the ordinary path, in this geometry, not an artefact of comparing two
different servers.


## The MSET bound, measured rather than flagged

1:1 MSET-against-GET at depth 8, 8 keys against 32, `kMaxPreciseKeysetKeys = 16`:

| arm | 8 keys | 32 keys | local share 8 → 32 | reads demoted 8 → 32 |
|---|---|---|---|---|
| PRE | 0.868 M/s | 0.484 M/s | 99.9% → **0.0%** | 795 → **3,632,340** |
| POST | 0.874 M/s | 0.491 M/s | 99.9% → **0.0%** | 757 → **3,681,176** |
| PRE vs POST | +0.70% | +1.34% | identical | identical |

**Crossing the bound costs the entire read-local hit share** — 99.9% to zero — and fences 3.6 million
reads. It is the largest single effect this lane has measured, and this lane's change does nothing
about it in either direction, exactly as the code says it must: a blind MSET naming more than sixteen
keys never refines in either arm.

**Recommendation: the literal 16 stays**, and now for a measured reason rather than a cautious one.
Raising it to the ring capacity would convert those 3.6 million demotions into local reads — and the
read-local comparison above says a local read costs about twice a demoted one in this geometry, so
recovering that share would make this cell *slower*, not faster. It is the same question as the
read-local tax and it must be answered on a bigger box before the bound is touched.

---

# VERDICT (SUPERSEDED 2026-09-06 by the owner's 16-shard control — see the section after it)

# ~~SHELVE~~, with the grow-on-demand redesign answered No

**The change works completely and costs consistently more than it earns in every regime this lane
could measure.**

| | |
|---|---|
| does it fix the defect | **yes, totally** — ring overflows 388,594 / 618,816 / 750,156 / 1,902,381 → **0**, in every cell of three separate runs; write-demotions 1.5-3.0 M → 0-217; read-local hit share 82-87% → 94-100% |
| is it correct | **yes** — 14/14 unit including three 200k soaks, every layout lock, the full mutation table with a passing control, the D1 derivation refusing to compile when the window moves, 2s batteries 11/11, differ 0 diffs |
| what it costs, saturated | **+0.43% / +1.44% / +1.96%** instructions per operation on the three regimes and **+1.27%** on pure SET, against a **0.34%** null floor. Rate moves less than its own 4.2% floor |
| what it costs, at matched load | **+5.4% / +6.8% / +6.1%** server CPU for the same delivered work, **+2.1%** pure SET, **+7.6% pure GET**, fills/op +3-10% |
| what it costs, in memory | **+972.8 bytes** on every armed connection, measured at 2000 connections against +960 predicted |
| is it a consistent win | **no.** It is a consistent, resolvable cost with a benefit that never appears in throughput |

**Hardcode-or-delete says shelve.** The branch `t-ringsize` keeps the work and the notes; nothing
merges.

### Why it costs, in one line each — all three measured, none inferred

1. **The old ring is cheap because it gives up.** Entering a conservative generation zeroes
   `write_head` and `write_count`: no inserts, no tags, no pruning, and every read short-circuits.
   PRE lives there above 55% writes. The ring bookkeeping this lane restores is **+43 instructions
   per write**, identical across three runs.
2. **A local read costs about twice a demoted one here.** `--read-local 0` against `1` on one
   binary: **−45.9% rate, +103.6% instructions** for turning the feature on. PRE demotes millions of
   reads; POST converts them into local reads; POST therefore does more of the expensive thing.
3. **The footprint is paid by connections that never use it.** At matched load, pure GET — which
   never touches the ring — costs **+7.6% CPU per operation**. That is the sidecar allocated at
   accept, not the ring logic.

### The redesign question, answered No

**The ring should not grow on demand.** DRAM fills per operation do not grow with connection count
(−0.371 fills/op at 512 connections, +0.045 at 2048), so static sizing to the ROB window is not what
costs. And the bookkeeping term is a function of **live writes**, not of capacity — the sweep walks
live groups only, so a 32-slot ring at depth 32 executes exactly the same instructions as a 64-slot
one. No re-sizing, dynamic or static, recovers a single instruction of the cost.

The one variant the data would support is different from the one that was asked about: **allocate
the sidecar lazily, on a connection's first write rather than at accept.** That is what the pure-GET
row is asking for, and it is one measurement, not a design.

### The caveat that governs the verdict, and the acceptance cells that could overturn it

**Every cell here was measured at two shards on two cores**, because that is the geometry in which
the null passes on the six cores this lane owns. It is also a geometry in which **read-local itself
is a 45% rate loss** — an io thread serving a read locally pulls the owning shard's lines into its
own cache, and with two shards that is a coin flip per read with two cores fighting over one working
set. The owner's box runs sixteen. If read-local wins at sixteen shards (and it must, or the feature
would not exist), then converting demoted reads into local reads is converting cheap work into
*cheaper* work, and **this lane's sign could flip**.

So the verdict is: **shelve on this evidence**, and one bigger-box measurement decides whether to
reopen it.


---

# THE VERDICT IS WITHDRAWN. The owner ran the governing control at sixteen shards and the sign flipped.

Mainline t9final, 32 cores, **16 shards**, fused, 512 connections, p32, ABBA, 2 reps per arm:

| shape | read-local 0 | read-local 1 | | instr/op | IPC |
|---|---|---|---|---|---|
| **1:1 alternating** | 21.42 / 20.99 → **21.21 M** | 24.46 / 23.88 → **24.17 M** | **read-local WINS +14.0%** | 3201 → 3657 (**+14%**) | 0.705 → **0.906 (+28%)** |
| **5:5 blocked** | 20.99 / 21.20 → **21.10 M** | 20.32 / 20.09 → **20.21 M** | **read-local LOSES 4.2%** | | |

On this lane's two-core rig the same control read **−45.9%** for the alternating shape. The caveat
was the right one and it was load-bearing: **two shards on two cores inverted the sign of the very
quantity the verdict rested on.**

### What the owner's two rows actually say about this lane

They say the defect is real and expensive, and they locate it exactly where this lane aimed:

* on the shape where **the ring never fills**, arming read-local is worth **+14.0%**;
* on the shape where **the ring fills and the connection disarms**, it is worth **−4.2%**.

That gap is not read-local being bad at blocked writes. It is a connection that has **paid the armed
cost and been denied the benefit** — which is the sentence this lane was written to delete. If POST
keeps the ring from filling at 5:5, the blocked shape should stop behaving like the −4.2% row and
start behaving like the +14.0% one. **That is a falsifiable prediction with a wide target**: POST at
5:5 should clear RL0's 21.10M, and its ceiling is the alternating shape's +14% line.

### And the methodological finding, which is the reason my verdict cannot stand

**Instructions per operation has the wrong sign here.** Read-local ON at sixteen shards costs
**14% MORE instructions** and delivers **14% MORE throughput**, because IPC rises 28%. My matrix
leaned on instructions/op precisely because it was the only column whose null floor (0.34%) was
tight enough to resolve anything — the rate floor was 4.21% — and the owner's control shows that
column pointing the opposite way to throughput across exactly the knob this lane makes fire more
often. An instruction-diet argument would have condemned read-local itself at sixteen shards, and it
would have been wrong.

So the honest status of every cost number in this document is: **the +43 instructions per write of
ring bookkeeping is geometry-independent and stands. The read-side conversion term (+4, +97, +180
instructions) was priced where a local read costs twice a demoted one, and at sixteen shards a local
read is *cheaper per unit of throughput*, so the same conversion should pay rather than cost.** The
memory figure (+972.8 bytes per armed connection) and the whole correctness column are unaffected.

### Status: VERDICT DEFERRED, not shelved

`t-ringsize` still merges into nothing and the branch keeps the work. The decision now rests on one
cell, specified and scripted at `scratchpad/ringsize/owner_cell.py`, to be run on the owner's box.

## The correction to the program's memory, since it is now more than this lane's business

**A memtier `--ratio` is a write RUN LENGTH, not a write fraction.** At the identical 50% write
fraction, `--ratio=1:1` demoted 738 reads and `--ratio=50:50` demoted 2,072,492 — a factor of 2,800
from the shape of the stream alone; and at 55%, a block of eleven demotes as much as a block of
fifty-five. The threshold is exact rather than statistical: alternating tops out at fifteen live
writes in a 32-deep window (the committing write holds a window position no ring entry can), which
is under a sixteen-slot ring, while a block of five puts about seventeen there and a block of ten
about twenty-two.

Anything that labelled a `--ratio` sweep a "write-fraction sweep" — the amortization study and the
earlier overflow finding among them — was sweeping run length. The consequence is not cosmetic: a
cell chosen as "41% writes, safely under the cliff" is **over** it, and a cell chosen as "50% writes"
is on one side or the other depending only on how the generator was spelled.
