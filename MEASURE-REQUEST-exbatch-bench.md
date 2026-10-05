# exbatch-bench: mainline directed measurement runner

Delivered `tools/exbatch_directed.py` on `cx-exbatch`. `git fetch origin cpp` and
`git merge --no-edit origin/cpp` completed first; the merge was already up to
date at synchronized PRE `cd02ecbab1502775f1c170e806971d1f7bbc3ee9`. No push.

This lane ran **no server, memtier workload, perf session, benchmark, or gate**.
The only memtier invocation was the expressly requested `/usr/bin/memtier_benchmark
--help` grammar check. Its SHA256 remains
`9b6ee614dae154c64b17a067a10236b3e6532f7ca52c43b547b87101556dd7d4`.
Both dry-run and normal execution reject missing required options, missing
same-key transaction/per-connection rate documentation, or a changed executable.
This installed help exits 2; complete grammar and SHA, rather than that exit
status, determine acceptance.

The runner consumes and validates the 15 `custom` entries in
[measurement-cells.json](docs/exbatch/measurement-cells.json). The 14 generic
and nine supplement cells stay with the gate's existing ABBA instrument. No gate
rows or `EXPECT_QUICK` / `EXPECT_FULL` constants changed; count delta **0 / 0**.

## Exact mainline invocations

Run these **sequentially**, from this worktree, on the scheduled quiet box.
Each output directory must be new; existing results are never overwritten.
These commands require the existing arm files, or their frozen source/patch
receipts, a C compiler for the small receive checker, and working system-wide
perf permissions. The inspected box has `perf_event_paranoid=-1`; no perf
command was executed to test it.

```bash
cd /home/user/Projects/cx-exbatch

taskset -c 0-111 python3 tools/exbatch_directed.py --regime f0 --blocks 1 --output build/exbatch-directed/mainline-f0
taskset -c 0-111 python3 tools/exbatch_directed.py --regime f1 --blocks 1 --output build/exbatch-directed/mainline-f1
taskset -c 0-111 python3 tools/exbatch_directed.py --regime s0 --blocks 1 --output build/exbatch-directed/mainline-s0
```

The serverless check and complete command plan are:

```bash
python3 tools/exbatch_directed.py --self-test
python3 tools/exbatch_directed.py --dry-run --blocks 1 --output build/exbatch-directed/plan
```

`--dry-run` executes only memtier `--help` and reads/hashes existing artifacts.
It prints build commands when needed, frozen executable paths, every server,
worker, memtier and perf command, the observer, preflight wire probes, the
native checker's build/controls, warm recipes, and the timed sequence. It creates
no run directory and opens no server connection. Matched commands contain the
explicit symbolic `Q_<cell>` because q requires a measured plateau. The printed
formula specifies its substitution. `--cell` can select a base ID or full
ID, and `--regime` is repeatable; omitting both runs all 15 directed cells.

At one block there are **200 fresh-server samples per regime**, or **600 total**:
five base IDs × two passes × five ABBA blocks × four samples. Each pass starts
with a PRE/PRE null block, then PRE/POST, PRE/PAD-A, PAD-A/POST, and the applicable
partial/POST block. The null is recorded before candidate samples in that pass.

**Expected wall time: budget 4–6 hours per regime, 12–18 hours for all three**, plus
any missing PRE/POST build. This is a planning estimate, not a timing measurement.
The fixed portion is exactly `200 × (20 s quiet preflight + 28 s generator
lifetime) = 2 h 40 min` per regime, before fresh population/readback, boot, wire
proofs, compilation/copying and teardown. The estimate allows approximately
24–60 seconds of those additional costs per sample. Actual sample and total
elapsed times are recorded. Increasing `--blocks` scales the sample count
linearly. A rejected block stops the run and remains in the artifacts; recollect
on a quiet box into a fresh directory.

## Recipes and arms

The inventory supplies the literal server/memtier argv arrays, key ranges and
warm recipes. The runner checks all 15 cells before doing work: 16 shards;
server CPUs 0–7; port 18179; fused f0/f1 with no ratio argument; split s0 with
6:2; all recorded explicit flags; eight instances with 8 threads × 8 clients;
pipeline 32; 28 seconds; literal key affixes; ratio 1 and P on **each** arbitrary
command. It rejects native `--key-pattern` in these recipes. Instance i uses
`8+13i..20+13i`, except the polling cell's instance 7 uses 99–110.

All six artifacts are SHA-bound against `docs/exbatch/binaries.json`. Each run
freezes executable copies under its own `arms/`, verifies their hashes before
launch and after the sample, and verifies the running server through
`/proc/<owned-pid>/exe`. The output retains source paths, frozen paths and full
SHA256 values, with the source commit and instrument hashes.

| Arm | Source binary | SHA256 prefix |
| --- | --- | --- |
| PRE | `build/exbatch/PRE/build/tomokv` | `5c2a0626ed3b3c73` |
| PAD-A | `build/exbatch/PAD-A/tomokv` | `1a8411f96fbb3ff4` |
| POST | `build/tomokv` | `410da97a4e6f8516` |
| EX1-OLD | `build/exbatch/EX1-OLD/tomokv` | `2068ea2dafa5fa60` |
| EX3-OLD | `build/exbatch/EX3-OLD/tomokv` | `d9cb457aab8f95f5` |
| EX6-OLD | `build/exbatch/EX6-OLD/tomokv` | `f27303fd5ee26542` |

**PAD-A is kind A: PRE behaviour at POST text/function/data layout.** The three
partial arms are also kind A for their respective item. No inverse control is
used. Missing PAD/partial binaries are reconstructed from the existing
`docs/exbatch/{pad-a,ex1-old,ex3-old,ex6-old}/planned-retargets.json`, after checking
the POST source SHA and every expected NOP; the reconstructed whole-file SHA must
match its frozen receipt. This neither runs nor modifies POST.

If PRE is absent, the runner can archive the synchronized PRE commit into an
empty `build/exbatch/PRE` and build it. A nonempty archive without its binary is
rejected to prevent a mixed-source build. A rebuilt PRE with different build
metadata must retain the report's exact `.text` SHA and complete function
address/size table; its new whole-file SHA is recorded. POST can be built when
absent, but candidate/control receipt mismatches always stop the run. Regenerate
receipts intentionally if changing the candidate; no silent baseline substitution.

| Directed base | Partial comparison |
| --- | --- |
| `exbatch_watch_w32` | EX3-OLD → POST |
| `exbatch_hz32` | EX3-OLD → POST |
| `exbatch_object32` | EX6-OLD → POST |
| `exbatch_xgroup32` | EX6-OLD → POST |
| `exbatch_publish_poll32` | EX1-OLD → POST |

The generic GET/SET partial comparisons remain outside this directed harness.

## Accounting and correctness guards

Every sample boots empty state, proves the owned listener PID and effective
configuration, populates every physical key with the recorded type/recipe, and
reads back every key. Eight warm workers use the same disjoint instance ranges.
Creation replies, physical key counts, hash field count/value, sorted-set
cardinality/score, stream length/group/consumer state, and OBJECT encoding are
checked as applicable. Hashes, zsets and streams are never warmed with SET.

WATCH setup uses two fresh-key deterministic witnesses. Each waits for the WATCH
ACK and the foreign SET ACK before EXEC; EXEC must return null and preserve the
foreign value. The nonconflicting six-frame rotation must commit exactly one
queued SET and return `[OK]`. Missing either witness fails setup. An unscored
two-rotation **real memtier** probe is captured by MONITOR for every sample;
the emitted command order, literal affixes, 64-byte data and WATCH/SET same
suffix are checked. Probe and MONITOR connections are closed before scoring.

Scored WATCH requires exact EXEC hit/abort counters, **zero aborts**, zero
connection errors, no server error log, and successful EXEC payload byte counts.
Rounded `Aborts/sec=0` alone cannot pass. It accounts six top-level frames and
two SET frames per rotation; QUEUED is not another write. Whole-run committed
transactions and central EXEC counts are separate fields. Central cycles and
instructions per committed transaction are included alongside cycles/frame.

XGROUP needs an additional guard because stock memtier does not export each
integer reply's value. The Python file embeds a small C receive checker, built
once by mainline and SHA-bound in the output. It is loaded **only into XGROUP
memtier processes**, identically across null/PRE/PAD/POST/partial arms, through
recorded `LD_PRELOAD` / `EXBATCH_ZERO_RECEIPT` environment entries. The exact
memtier argv and direct connection to port 18179 remain as specified. The checker
handles fragmented/coalesced read/recv/readv/recvmsg replies and requires every
byte on those sockets to form `:0\r\n`. Its verified response count must equal
memtier's drained XGROUP HDR count exactly, with 64 connections per instance.
Missing interposition, a `:1`, error, truncated reply, or missing receipt fails.
All 65,536 existing consumers are also checked directly before and after load.
The checker runs on generator CPUs and is outside the server PMU numerator;
its client cost is part of this frozen XGROUP instrument, including its nulls.

Mainline's checker build runs one positive and four negative memory-only native
controls before measurement: all fragmentation widths plus an iovec boundary,
nonzero reply, error reply, truncated reply and no coverage. These open no socket
and run no server. Each expected negative must exit through the guard's own
diagnostic. Source, shared library, unit binary and control receipts are retained
under the run's `guard/` directory.

The polling cell has one persistent observer connection on CPU 111. It sends
MEMORY STATS at absolute 100 Hz deadlines, logs send/completion/deadline times,
and records successful polls and missed slots. Any missed slot rejects the run.
The central count must agree with 100 Hz and the server's MEMORY counter within
the two endpoint polls; across a block counts must differ by no more than two.
Observer commands are excluded from workload frames, while their server CPU
cost remains in the same PMU numerator on every arm.

The central denominator is the sum of **named workload command counters**,
excluding INFO/DEBUG/MEMORY/setup traffic. Full drained per-command HDR counts
must equal whole-run server command counts exactly. Memtier's printed Count
snapshot may differ from drained HDR only by its finite outstanding bound,
`64 × 32 = 2048` frames per instance; no percentage allowance is used. Central
counter boundaries retain the `2 × 512 × 32` frame bound. Exact abort counters
and the native XGROUP checker use completed replies, including the drain.
The [memtier 2.5.1 statistics implementation](https://raw.githubusercontent.com/redis/memtier_benchmark/2.5.1/run_stats.cpp)
is the schema reference; the gate's existing HDR decoder is reused and hashed.

## Windows, load matching and PMU scope

The gate's normal server boot allowance is **30 seconds**, with **zero additional
diagnostic load-startup allowance**. The inventory's `--test-time=28` remains
literal. Three seconds of load warmup precede the common 20-second central
window; the remaining lifetime is the tail. Launch and endpoint timestamps are
recorded, all 512 workload connections must be present at both boundaries, and
premature child exits or excessive setup/skew fail. The diagnostic gate mode's
extra five seconds is not silently added.

The first pass has unlimited offered rate. Each comparison uses A/B/B/A order,
with fresh boot/population for each sample. The gate's productive-role occupancy
rule is checked per block (95% mean and no sample below 90%), along with a 2%
same-arm repeatability ceiling. The requested fixed generator geometry is kept;
this tool does not assert a higher-generator-capacity plateau proof from occupancy
alone. Mainline's capacity calibration and frozen regression bands still decide
whether a performance claim is justified. Same-binary null evidence is collected
before candidates; it never widens a band around a candidate loss.

After the three primary plateau comparisons, q is:

```text
floor(0.8 × min(mean PRE frames/s, mean PAD-A frames/s, mean POST frames/s) / 512)
```

Each mean uses that arm's equal-length primary-comparison samples; nulls and
partial-arm comparisons do not enter q. The matched pass appends the **same**
`--rate-limiting=q` to all eight instances and all compared arms, including the
partial. Each achieved central rate must be within **2% of 512q**. The report's
additional instruction-receipt rule is also enforced: paired arm means must
agree within **0.5%**. Failure rejects the block rather than comparing unmatched
instruction receipts or silently reducing one arm's rate.

Both passes collect grouped cycles and instructions with `perf stat -a -A -C
0-7`, no scaling, and FIFO enable/disable acknowledgements. The
[perf stat control interface](https://man7.org/linux/man-pages/man1/perf-stat.1.html)
allows the counters to start disabled and acknowledge each boundary. Missing,
duplicate, unsupported, or multiplexed events are rejected. The actual running
perf executable is hashed. IPC is calculated from the same grouped counters;
cycles/frame is `(instructions/frame) / IPC`. Total and per-role numerators are
recorded, with roles mapped through INFO's `thread_cpus` and DEBUG LBSIGNALS.
LBSIGNALS' `cpu` field is CPU time, not a placement ID.

PMU enable and disable bracket the command-counter requests. Their measured
prefix/suffix offsets are retained and each is limited to 50 ms; the central
interval must be 20–20.05 seconds. These finite endpoint offsets are explicit,
not a claim of atomic PMU/Redis counter sampling. CPU scope and logical-frame
denominator are the same on every arm. Polling's server cost stays included.

p50/p99/p99.9 come from pooling the actual completed-response HDR histograms
across instances and repetitions, never averaging percentiles. As with the gate,
those histograms span the **full 28-second load**, including warmup/tail. Their
scope is recorded separately from central rate/PMU accounting.

Every sample uses the gate's `QuietMonitor` on CPUs 0–111 and intended port
18179, including its 20-second preflight and unchanged selected-core CPU budget.
`GATE_QUIET_FILE` / `GATE_QUIET_MINUTES` are honored if set. A lost quiet-file
condition aborts the block; it is not averaged away. Runtime CPU samples are
retained as observations, without claiming they distinguish foreign work from
owned work. Only owned subprocess groups are terminated/reaped, including on
interrupt; an existing listener is never adopted or killed.

## Output and validation

Each invocation produces `results.json` and `endgame.txt`; every sample also has
`sample.json`, raw memtier JSON/logs, server log, perf CSV/control artifacts,
quiet CPU samples, warm and wire witnesses, LBSIGNALS endpoints, and applicable
observer/checker receipts. Incomplete samples and rejected block paths remain
visible, and a failed run exits nonzero. Null blocks do not emit candidate rows.
There is one endgame row per cell/comparison/**pass**, hence 40 rows per regime:

```text
EXBATCH-DIRECTED <cell> <regime> <A>-><B> rate=<ops/s A>/<ops/s B> (<+x%>) p50=<ms>/<ms> p99=<ms>/<ms> cyc/op=<A>/<B> (<+x%>) instr/op=<A>/<B> ipc=<A>/<B> matched=<q or plateau>
```

No measured rate, improvement, regression verdict, or iteration-gate result is
claimed by this lane. Mainline owns live validation, null-band/capacity judgment,
the iteration gate, and merge.

Completed offline checks:

- `python3 tools/exbatch_directed.py --self-test`: **19 tests passed**, including
  all 15 cells × six arms, synthetic memtier/HDR files, single hidden EXEC abort,
  finite drain bounds, malformed PMU data, 2% target and 0.5% paired checks,
  missing grammar, partial-arm reconstruction, native zero-reply receipts, wire
  affixes, and a mocked full sample/failure cleanup. The self-test traps process
  launches and network connections.
- Embedded native checker built with `-Wall -Wextra -Werror`; its positive and
  four negative memory-only controls passed. Mainline repeats these controls
  before using the checker.
- Complete dry-run plan audited: **600 server samples, 4,800 scored memtier
  commands, 600 unscored wire probes, 600 perf commands**, exactly half the scored
  commands rate-limited; all server paths frozen; no native key-pattern flag;
  no run directory created.
- Python compilation and `git diff --check` pass. No live commands were run and
  nothing was pushed.
