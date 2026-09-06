# rlbatch — the interleaved-connection tax on the fused read-local lane

The question this lane opened with: a fused, read-local-armed server serves a given read/write mix
markedly slower when every client connection carries BOTH kinds than when reads and writes arrive on
separate connections — 26.29M vs 20.60M at 41% reads on the 64-shard/32-core box, and a profile
showing 3520 instructions per operation interleaved against 2909 separated, at flat IPC. Flat IPC
means the gap is work, not stalls, so instructions per operation is the instrument.

## The instrument

`build.sh` builds the driver. `replay.c` drives a byte-identical request stream in two connection
layouts at a chosen delivered read fraction:

* `mix` — reads and writes interleaved on ONE connection
* `sep` — the same stream, reads on connection A and writes on connection B

The read/write decision is error-diffused, so reads are spread as evenly as the fraction allows;
read keys come from the low half of the key ring and write keys from the high half, so the two key
sets are disjoint and a correct server serves every read locally. `measure.sh` takes each cell as a
SLOPE over 1M and 3M operations on a server pinned alone to one core, so boot, population and the
fused loop's idle spin cancel instead of being billed to the change. `ab.sh` alternates the arms.
`tax.py` prints the tax against that blend directly. Ports 8075-8078, cores 32-47/160-175.

**Use `instructions:u`.** The `sep` arm opens a second socket, which costs it ~600 more KERNEL
instructions per operation; the user-space count is the only fair column, and `report.py` prints
both (`ctr` = `u` / `all`).

### The reference the tax is measured against

`sep` on this instrument is NOT a clean ceiling: splitting a 32-deep batch across two sockets leaves
each socket shallower, which inflates its per-op cost for reasons that have nothing to do with the
ROB. The clean reference is the **homogeneous blend** — the same driver at 100% reads and at 0%
reads, each on one connection at the same depth, combined at the cell's read fraction. That is
literally "what a homogeneous connection pays", and every tax figure below uses it.

## The decomposition (PRE, pipeline 32)

Ablation arms, built with `ablate.py apply` + `-DTOMO_RLABL=<bits>` (1 = the read-side conflict
probe always says no, 2 = no write generation at all, 4 = no demotion planning). Each arm's blend is
recomputed from that arm's own controls; `abl.csv`.

| read % | tax (mix − blend) | of which: read-side conflict probe | demotion planning | residual |
|---|---|---|---|---|
| 71% | +169 | 98 (58%) | 8 (4%) | 49 (29%) |
| 61% | +183 | 101 (55%) | 9 (5%) | 56 (30%) |
| 41% | +349 | 31 (9%) | 142 (41%) | 56 (16%) |

The residual is the executor's scheduling difference (`drain_tasks_read_local_interleaved` and its
bounded local turns, in place of the pure-read tail drain) plus lane bookkeeping. It is the part no
ROB change reaches.

**The per-frame write-generation resolve is NOT the money.** Gating it away entirely is worth 5-13
instructions per operation (`s1.csv`), matching the independent finding that re-arranging a 32-deep
pipeline into 16-read/16-write blocks buys only 2-4%: pipelining keeps the previous block's writes
in flight, so the generation stays live no matter how the client arranges its frames.

**At 41% reads the connection falls off a cliff that has nothing to do with resolution.** 59% writes
at depth 32 keeps ~19 writes in flight, the 16-entry RYOW ring overflows, `refine_current_write_hash`
then refuses the hash, and the demotion planner — told "this write is not precise" — lowers EVERY
pending local read to the owner queue. Measured on PRE: `read_local_fallback_inflight_write` 164000
of 164000 reads, `read_local_hits` 0. At pipeline 24 and below the ring does not overflow and the
same cell reports zero fallbacks.

## What shipped, and what it bought

Three steps, `s7.csv` (3 interleaved reps, medians, `instructions:u` per operation):

| cell | PRE | POST | delta |
|---|---|---|---|
| mix 41% p32 | 2938.2 | 2754.2 | −184.0 (−6.26%) |
| mix 61% p32 | 2563.8 | 2474.4 | −89.4 (−3.49%) |
| mix 71% p32 | 2445.7 | 2357.6 | −88.1 (−3.60%) |
| mix 41% p8 | 3845.8 | 3816.4 | −29.4 (−0.76%) |
| mix 61% p8 | 3636.9 | 3596.4 | −40.4 (−1.11%) |
| mix 71% p8 | 3523.3 | 3480.1 | −43.2 (−1.23%) |
| write-only p32 (control) | 3010.8 | 3023.9 | +13.1 (+0.44%) |
| read-only p32 (control) | 1946.4 | 1948.7 | +2.3 (+0.12%) |

Against the homogeneous blend the interleave tax falls from +364/+202/+191 to +171/+106/+97 at
41/61/71% reads — roughly half, and 53% at 41%.

## Functional coverage

`batteries.sh <bin> 1s|2s` runs the required batteries, one boot per battery, port 8075, pgrep-
guarded, killing by PID. `differ_gate_fused.sh` is `tests/differ_gate.sh` with exactly two extra
target boot flags (`--thread-mode fused --read-local 1`) plus a non-vacuity row: the canonical gate
boots the target in the DEFAULT split / read-local-off geometry, which never reaches the parse arm
this lane changed, so a green canonical differ alone would prove nothing about it. The added row
reads `read_local_hits` out of INFO before the target is stopped and fails when it is zero.

## A PRE-EXISTING divergence this lane's extra differ run uncovered

Running the differential matrix in the fused + `--read-local 1` geometry turned up one red leg that
the standing gate cannot see, because its differ boots the target split with read-local off:

    differ multi (atomic=1 seed=7)   4260 ops, 5 diffs -> FAIL

The diffs are all EXEC replies in which the target returns a value the oracle has already
overwritten (op 1266 answers `-ERR value is not an integer` where the oracle answers `:-2`; ops
1275/1287/1387 return `hello` or nil where the oracle returns `-2`).

**It is not this lane's.** One leg, same geometry, alternating binaries, `/tmp/rlb-multileg.sh`:

| binary | `--read-local` | runs | failures |
|---|---|---|---|
| shipped head (PRE) | 1 | 6 | 2 |
| this branch (POST) | 1 | 6 | 1 |
| shipped head (PRE) | 0 | 8 | 0 |

Byte-identical diff text in every failure, on both binaries. So: a rare visibility race that needs
the armed read-local lane AND `--atomic 1` AND MULTI/EXEC, present on t-train9 before this branch,
at a rate the six-run sample cannot separate between the two binaries. It deserves its own lane;
what belongs here is that the geometry is untested by the gate and the leg reproduces it about one
run in three.

## What is still on the table

The 16-entry RYOW ring still overflows at 41% reads / depth 32, and the reads it fences at parse
time still fall back: 51250 of 410000 after the change, against 410000 of 410000 before. Sizing the
ring to the ROB window (64) would make overflow unreachable, at ~768 more bytes per armed
connection and a longer exact walk. Not attempted here; it is a separate lane with its own PRE/POST.
