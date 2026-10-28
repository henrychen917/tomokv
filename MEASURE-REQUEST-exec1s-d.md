# Wave 9 EXEC refinement lane

## exec1s-d

The branch integrates exec1s-c with wave 9 and repairs the repeated-key reuse
walk, per-EXEC allocation, and ordinary-command instruction drift. This is **not
a green landing request**: X3's idle rotation remains +7 instructions against a
budget of +2, and the historical seed-22 SAVE admission rejection has not yet
been reproduced or classified. Correctness also retains a slowlog failure reproduced
on headline PRE. No throughput measurement or claim is made here.

The final production source is `cf3bdaa9e`;
later commits contain evidence, build/proof tools, and this request. The frozen
POST is `build/exec1s-d/POST`. The complete hashes and source identities are in
[arms.json](docs/exec1s-d/arms.json) and [SHA256SUMS](docs/exec1s-d/SHA256SUMS).

### Integration and changes

`670dc9f19` is the required no-ff merge, with parents `393d6ceb1` and
`0dcc10f9b`. `d602c8c36` restores immediate RESET dispatch while preserving
wave 9's PAUSE, slowlog and repeated-key semantics. All headline and exec1s
gate collectors remain. `tools/trackfix_schedule.py` keeps the headline's
tomokv-target dry run; its contents match the headline.

The follow-up changes are:

- Read the pending version list newest first and stop at the first matching
  key when deciding whether a parent-owned private version can be reused.
  This is equivalent to multifix's full oldest-to-newest scan. On the hot-key
  shape, the matching record is the tail, so older versions add no visits to
  this check. Unrelated newer records can still require a scan; this is not a
  general constant-time key index. The existing exec1s row now checks the
  complete-scan oracle, depths 0/16/64, foreign newer records and unrelated keys.
- Allocate the scatter arena, scatter stage masks and saved database map only
  for transactions that need them. Local/SCAN children use a single completion
  byte; dynamic scatter waves retain their physical-shard indexing.
- Hoist X3's per-owner bell address in both fused loop variants. Both fresh
  observations and the guarded owner passes remain.
- Use function-local jump/loop alignment settings for normal-namespace
  `xshard_execute`. This removes executed padding introduced by the changed
  EXEC helpers in the same translation unit. The full ordinary matrix, not an
  instruction estimate from source, validates this change.
- Initialize the lazy database map on watched EXECABORT as well as ordinary
  preparation. The existing directed WATCH row exposed this missing error path
  in the first final candidate; the crashing receipt is retained and the
  production fix leaves all of that row's assertions unchanged.
- Update the at412, woundfix and blocking test fixtures to construct the new
  sparse transaction storage correctly. These repair fixture crashes, not
  production exceptions or weakened assertions.

D1–D10, amend1 and D4′ are unchanged. No execfifo mechanism is included.
REGISTER contains no `exec1s D5` owner authorization; X4 remains disabled in
POST and every merit arm below. The layout locks still compile.

### Serverless PRE/POST evidence

[count-comparison.json](docs/exec1s-d/count-comparison.json) contains the full
matrices and binds final POST by SHA-256. Counts include executed NOPs and all
selected linked production routines. Fixture glue and external library bodies
are excluded consistently. Each scope must produce exact replies; failed
assertions cannot produce a passing count receipt. Probe hashes, build commands
and retirement receipts are retained; large step traces and probe binaries are
retired after the count is recorded.

The ordinary matrix is GET/SET/INCR/MGET/MSET, batch 1 and 32, both modes and
both namespaces; MSET covers atomic 0 and 1. All 48 comparisons add **zero or
fewer** instructions. Deltas below hold in both modes:

| Command / namespace | Batch 1 delta | Batch 32 delta |
| --- | ---: | ---: |
| GET, SET, MGET / both | 0 | 0 |
| INCR / normal | -11 | -352 |
| INCR / db0 | 0 | 0 |
| MSET atomic 0 / both | 0 | 0 |
| MSET atomic 1 / normal | -24 | -768 |
| MSET atomic 1 / db0 | -8 | -8 |

Read-local GET is exactly equal in all four armed fused scopes:

| Namespace | Batch | PRE = POST instructions |
| --- | ---: | ---: |
| normal | 1 | 2,428 |
| normal | 32 | 49,231 |
| db0 | 1 | 2,340 |
| db0 | 32 | 45,949 |

The allocation scope includes `allocate_state` **and** `prepare_commands` for
two local INCR children on two shards. Both namespaces give the same result:

| Scope | Before | Final POST | Ratio | Budget |
| --- | ---: | ---: | ---: | ---: |
| 1s, 64 shards, allocated bytes | C-PRE 13,514 | 3,348 | 0.247743 | <=0.25 |
| POST 1s/64 versus POST 2s/16 | 2s 3,269 | 1s 3,348 | 1.024166 | <=1.2 |

Here C-PRE is the original design's `83e0b809d`, not the wave 9 PRE. The
[allocation receipts](docs/exec1s-d/POST-allocation-normal.json) identify the
scope, production binary and independently built allocator-counting fixture.

X3 idle still fails its budget:

| Namespace | X12 (no X3) | Merged X3 | Final POST | Final delta |
| --- | ---: | ---: | ---: | ---: |
| normal | 3,679 | 3,695 | 3,686 | +7 |
| db0 | 3,643 | 3,661 | 3,650 | +7 |

At each of the two observation sites GCC emits a stack reload of the bell
pointer, a byte load, a test and a conditional branch. The loop as a whole
adds seven instructions because the surrounding generated code also changes.
Two fresh memory observations plus two branches already require at least four
instructions on this target even if addressing and testing can be combined.
The lane does not drop an observation or count only branches to report +2.
The final disassembly is `build/exec1s-d/evidence/idle-final.asm`.

### WAVE9-EXEC-DEPTH and X3/X5 attribution

Each EXEC arm has 72 scopes: the 48 combinations of 1/2/4 children, same/cross
shard, atomic 0/1, mode and namespace, plus 24 two-child depth scopes with
0/16/64 older pending versions. Complete per-arm matrices are named
`docs/exec1s-d/EXEC-<ARM>-counts.json`.
The children in this matrix are INCRs. Same-shard repeats one key; cross-shard
uses one key per child on distinct shards. Consequently the one-child cross
label is the same single-shard control, not a scatter child. The separate
`SCAT-<ARM>-counts.json` matrix adds MSET children: each writes two distinct
keys, on one shard or two shards owned by different threads. It includes
1/2/4 children in both modes, atomic settings and namespaces. PRE, POST, X12, X3, X5 and MERGE
have passed all 48 scopes each. [scatter-comparison.json](docs/exec1s-d/scatter-comparison.json)
contains their complete attribution deltas.
Rebuilt probe inputs must match every allocated section of the frozen binary
except the build-id note, including bytes, addresses and sizes. This permits
debug-only rebuild differences without substituting different production code.

The normal-namespace 2s, atomic-0 two-child depth counts are:

| Pending versions | Wave 9 PRE | REUSE, without X2 | Merge | Final POST |
| --- | ---: | ---: | ---: | ---: |
| 0 | 16,686 | 16,702 | 14,537 | 14,452 |
| 16 | 29,212 | 26,924 | 26,688 | 24,301 |
| 64 | 66,460 | 57,068 | 62,832 | 53,341 |

Atomic 1 gives the same counts for these cells. REUSE removes the full-chain
reuse check independently of X2: -2,288 instructions at depth 16 and -9,392
at depth 64, with +16 at depth zero. Other version processing remains linear.
The fixture calls `multi_execute_task` directly; X2's later executor cleanup
is outside this depth window. These numbers establish the removed walk, not
an eager-reclamation throughput result.

For attribution, these are representative normal-namespace 2s/atomic-0 scopes:

| Shape / children | X12 | X12+X3 | X12+X5 | Merge (X3+X5) | POST |
| --- | ---: | ---: | ---: | ---: | ---: |
| same / 1 | 13,951 | 13,969 | 12,185 | 12,203 | 12,067 |
| same / 2 | 18,918 | 18,942 | 16,544 | 16,568 | 16,431 |
| same / 4 | 28,823 | 28,859 | 25,226 | 25,262 | 25,119 |
| cross / 1 | 13,951 | 13,969 | 12,185 | 12,203 | 12,067 |
| cross / 2 | 23,354 | 23,390 | 21,333 | 21,369 | 21,256 |
| cross / 4 | 42,029 | 42,089 | 39,360 | 39,420 | 39,349 |

X5 removes command-scope work; X3 adds its hint publication/check work. X3's
extra owner passes run only in fused mode, although shared EXEC helpers publish
hints in split mode too. Neither these counts nor the allocation reduction
attributes the measured 1s gain or the 2s hot-key loss in rate: scheduling,
cache effects and IPC still require the isolated build arms below.

The added normal-namespace 2s/atomic-0 MSET-child scopes are:

| Child placement / children | PRE | X12 | X3 | X5 | MERGE | POST |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| same / 1 | 21,826 | 21,624 | 21,642 | 19,771 | 19,789 | 19,665 |
| same / 2 | 31,700 | 31,333 | 31,357 | 28,830 | 28,854 | 28,721 |
| same / 4 | 51,366 | 50,669 | 50,705 | 46,855 | 46,891 | 46,736 |
| cross / 1 | 23,389 | 23,287 | 23,324 | 21,742 | 21,779 | 21,682 |
| cross / 2 | 33,427 | 33,325 | 33,375 | 31,075 | 31,125 | 31,042 |
| cross / 4 | 53,370 | 53,268 | 53,344 | 49,597 | 49,673 | 49,614 |

### SAVE admission investigation

The original failure is preserved in
[epoll-psfix-failure.json](docs/exec1s/epoll-psfix-failure.json). It is epoll,
split 6:2 on eight cores, 16 shards, atomic 0, psfix seed 22, after the standard
preceding suites. The original full seed/suite plan is copied unchanged to
[epoll-seed22-plan.json](docs/exec1s-d/epoll-seed22-plan.json).

The full split-0 replay passed on MERGE and C-PRE with an admission-result
observer: all 15 SAVE/BGSAVE starts returned Started in each arm. The observer
does change timing. Native full-plan replays on C-PRE and MERGE also passed all 235 legs each.
The harness bytes match exec1s-c and the oracle is Redis 7.4.10; see
[save-reproduction-environment.json](docs/exec1s-d/save-reproduction-environment.json).
Both the earlier POST (`22d10835…`, before the watched-EXECABORT repair)
and final POST (`4111f5c6…`) also passed 235/235. The final native replay retained
the original seed-22 plan and used no debugger; see
[save-full-native-POST-final.json](docs/exec1s-d/save-full-native-POST-final.json).
These successful replays do not prove the historical failure fixed or pre-existing.

A further full-plan replay used breakpoints only on the **taken Busy reply
branch**, resolved from each frozen binary's disassembly. Both C-PRE and MERGE
passed 235/235 again, with two breakpoint locations armed and zero Busy hits.
Successful admissions never execute those breakpoints; debugger attachment
still changes initial timing. These runs also leave the cause unclassified:
[C-PRE receipt](docs/exec1s-d/save-full-busy-only-C-PRE.json),
[MERGE receipt](docs/exec1s-d/save-full-busy-only-MERGE.json).

Bounded native repeats of unchanged `tests/differ.py ... psfix 22` reproduce a
different failure on both C-PRE and MERGE: repeats 0–5 pass, then repeat 6
times out waiting for SAVE. The two failure logs have the same SHA-256. This
is a timeout reproduced on older code under that repeated schedule, **not** the original
Busy rejection. GDB snapshots are diagnostic only; no persistence fix or
root-cause claim is based on optimized variables. An overlapped observer
attempt is explicitly invalidated in its receipt and is not proof.

A passive kernel admission observer was **NOT RUN**: an owned-child uprobe
was denied with EACCES, and passwordless elevated tracing was unavailable. No
system setting was changed; [the capability receipt](docs/exec1s-d/save-passive-observer.json)
distinguishes this from the GDB-observed replays.

No differential assertion, seed, idle barrier or SAVE timeout is suppressed or
changed. The original admission failure remains an open acceptance item until
the same failure is captured on PRE or its cause is fixed and tested.

### Correctness and build proof

Final proof status is recorded in
[live-proof.json](docs/exec1s-d/live-proof.json), including failed and interrupted
attempts. Only receipts bound to final POST count as final production proof.
The driver uses the gate's own selected-job interface, retaining internal
engine/mode/atomic/namespace legs and the normal 16-shard, 6:2 geometry.

`make -j32 all` completed. All 51 literal `job_production_units` targets and
the additional MDBQSBR, blockfix-cost/binding and blockfix2 checks are fresh:
57/57 `make -q` checks passed on corrected POST. See
[freshness.json](docs/exec1s-d/freshness.json).

The targeted gate invocation passed 32/32 rows, including all 27
`atomic_units` rows and all four exec1s rows (plus its release prerequisite).
The watched-EXECABORT row passes unchanged. Lottery, POST-layout and PAD-A
each passed the gate's execfair smoke, which covers both modes and engines.

The final-binary `redis_tcl` job failed its fused isolated upstream assertion
`SLOWLOG - Rewritten commands are logged as their original command`: after
EXEC pushes to a blocked list and resets the slowlog, the newest entry was
`slowlog reset`, not `blpop l 0`. The same unchanged assertion and gate geometry
reproduce this on frozen headline PRE: 5 failures in 64 fresh-server fused
attempts, after an initial 8/8 pass. POST failed 2/8 fused attempts; both arms
passed their eight split attempts. These are bounded correctness attempts, not
failure-rate estimates. See [slowlog-replay.json](docs/exec1s-d/slowlog-replay.json)
and [slowlog-pre-replay.json](docs/exec1s-d/slowlog-pre-replay.json).

The source ordering explains the exposed window: owner commit makes the list
visible and marks its blocked registry dirty; queued connection-local
`SLOWLOG RESET` and child log records execute later in `multi_retire`. A blocked
client can complete and log in between, then have its entry cleared. That
ordering exists on PRE. This defect is **pre-existing and unfixed**, and the
failed gate row remains red. The frozen Tcl manifest, assertions and retry
policy are unchanged. The five unnamed setup errors printed elsewhere in the
Tcl log exactly match its existing manifest entries; they are not new failures.

The final selected-job index contains **251 completed job/variant entries,
1,083 passing rows and two failing rows**. Both failing rows come from the
pre-existing slowlog assertion described above: `redis_tcl`, and its propagated
`compat2` prerequisite result. These are selected-job totals; no full iteration
or EXPECT tally was run. [proof-summary.json](docs/exec1s-d/proof-summary.json)
provides a compact index; the complete history remains in `live-proof.json`.

The broad final invocation reported 832 passing rows and eight failures. Six were
zero-copy boots refused by the idle-core preflight during concurrent lane work.
All **24 zero-copy rows** then passed in an isolated rerun: release/ASAN,
split/fused, io_uring/epoll, with that preflight unchanged. The fused supplement
passed 215/215 rows, and the two atomic-0 script supplements passed 3/3 each.
The AOF CQ-observed jobs passed 57/57 in each mode, with positive completion
samples and fused-executor ring observations; both recorded zero overflow and
dropped completions.

Both standard differential plans completed unchanged against Redis 7.4.10:

| Engine | Standard seeds | split a0 | split a1 | armed a0 | armed a1 | Equivalence |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| io_uring | 7,19,20,23,21 | 235/235 | 239/239 | 230/230 | 234/234 | 16/16 |
| epoll | 7,19,20,23,22 | 235/235 | 239/239 | 230/230 | 234/234 | 16/16 |

`python3 tests/gates_test.py` passed **73/73**, plus its 14 persistence helper
checks, on an isolated invocation. The earlier two attempts exceeded the
unchanged 45-second synthetic scheduler deadline during overlapping work;
those failure artifacts remain. No watchdog, assertion or suite count changed.


The inventory includes txnorder, execfair, multirace/WATCH/blocking batteries,
scripting/xscript/scriptatomic, atomics, FLIP, read-local, notifications,
persistence/SAVE, writeback, execindex oracle/complexity, all at412 stages and
woundfix. It includes copied-source trackfix_order, aoforder, notifycompat,
publishfix and racefix. Lottery has no `tests/gate.sh` job; its copied witness
build and bounded gate smoke are recorded separately from its nightly campaign.
Its seven existing EXEC occurrence cases also passed on their first fresh
attempt, each with a positive W16 witness. This covers split/fused, atomic 0/1,
armed read-local and notification shapes. The attempts use the existing driver
and process-group cleanup with lane CPU/port arguments; no assertion changed.
[lottery-witness.json](docs/exec1s-d/lottery-witness.json) records each command,
binary identity and required counters. This is a witness smoke, not the nightly
campaign's statistical verdict.

NOT RUN: full `iteration`, performance/load generators, `flip_saturated`,
`atomic_floor`, and the rate assertion in `atomic_ryow`. Those are reserved for
the maintainer. `GATE_PROOF_NO_RATES=1` is the existing partial-job interface;
finite atomic correctness schedules still run. The full lottery nightly campaign includes a memtier-driven row, and its runner
also restricts CPUs to 112–127 and ports to 253xx. The seven bounded EXEC
attempts use its separate attempt interface on this lane's authorized resources.

**DQ=+4, DF=+4 relative to headline; this continuation adds no new aggregate
row.** `collect_job exec1s` is line 6008, before the quick exit at line 6119.
The maintainer-owned constants remain 881/898; they should become **885/902**
for this merge. No EXPECT constant was edited.

### Frozen arms and PAD semantics

| Arm | Binary in `build/exec1s-d/` | SHA-256 |
| --- | --- | --- |
| MERGE | `MERGE` | `462c49e4806e9c208162f0ac9ef688077f3dc909edc7592cc7a88be747292f1c` |
| C-PRE | `C-PRE` | `47c4cc498a212922433220c57efca3b7e249e3c23889623a0c7de0e0feeb043b` |
| X12 | `X12` | `20d40ac975b49935500a75b9b2959d7058c03f54ededcb3b4131e27ef8edbec6` |
| X3 | `X3` | `9bf432e191a5fed09f6bbc76b50c07281155ed802093bfc0a9578068b78ad4e1` |
| X5 | `X5` | `7381c44a183471f9a11521e0eb2ae0ce42201d6adf4b3805e8f3af1c98254cba` |
| PRE | `PRE` | `5347cbd4d66c2bfd9a60c802388f3b04015e2bb2801cd37f7fc49a55f6b0932d` |
| REUSE | `REUSE` | `196fa795a956afd6bd0aa5e0d8980e9fcc4ec1e849d1d866317dc87d93039d53` |
| POST | `POST` | `4111f5c6ad1784fc6b95fceedc9efe361cf715dbad97f912e130811ab7544f18` |
| POST-layout | `POST-layout` | `9d99271b801d51d2331b8a686172a98e72099f752a9fae5ef604f741cac7d591` |
| PAD-A | `PAD-A` | `1b1a7372db7a27a10ba0adce157541e5b5805fc5ed4bcff9ddea8aa0587d23b9` |

X12 is headline plus X0/X1/X2. X3 and X5 add the respective original lever in
isolation to X12; MERGE combines both, before this lane's allocation, reuse and
idle repairs. REUSE is headline with only the newest-match reuse change and
does **not** contain X2. Source manifests and patches for isolated arms live
beside their count receipts. The build tool reconstructs X12/X3/X5 directly
from those committed patches and checks every source hash.

**PAD-A is type (A), a behaviour twin.** POST-layout and PAD-A contain the same
combined image, with POST code first and isolated PRE code second. Only the
five-byte entry jump changes the selected behavior. Section sizes, symbols
and their addresses are equal; see [pad-a.json](docs/exec1s-d/pad-a.json).
The pair is larger than release POST. It controls the common-image comparison;
it is not an exact-size twin of the smaller standalone release POST. Measure
release POST/PRE as well as POST-layout/PAD-A.

### Maintainer measurement request

Use the frozen hashes. All measurements below remain **NOT RUN by this lane**.
Keep the existing matched offered-load plans, cell-level null rules and all
options identical between arms. A one-block attribution result cannot replace
the three-block acceptance comparison.

1. `exec-merit.py`: POST/PRE, **64 connections, 3 blocks**, all eight cells:
   `x1s_a0_unc,x1s_a0_hot,x1s_a1_unc,x1s_a1_hot,x2s_a0_unc,x2s_a0_hot,x2s_a1_unc,x2s_a1_hot`.
   Use `/home/user/Projects/calib/exec-merit.py`, `--conns 64 --threads 16
   --cells all --blocks 3 --secs 20`. Keep pipeline 4, four plain INCR writers
   on hot cells, databases=1, 1s read-local=1/64 shards, 2s ratio=6:2/16 shards,
   and disabled key/client balancing and automatic FLIP from the harness.
2. Same cells, **1 block per attribution pair**: X12/PRE, X3/X12, X5/X12,
   MERGE/X3 (X5 conditional on X3), MERGE/X5 (X3 conditional on X5), POST/MERGE,
   and POST-layout/PAD-A. First arm is candidate, second reference. Inspect
   the 2s hot EXEC rate and the competing plain INCR rate separately; report
   where the original 2s loss and 1s gain appear, including interactions.
3. `/home/user/Projects/calib/exec-depth-sweep.py`: PRE, REUSE and POST in both
   modes and atomic 0/1; placements `cross,same-owner,same-shard`; depths
   `16x1,16x4,32x4,64x4,128x4`; **3 blocks**, `--secs 10`. Add X12 for the X2
   comparison against PRE. REUSE is the required no-X2 candidate: same-shard
   2s 64x4 and 128x4 must recover at least the historical wave 8+8b levels
   (about 410k/400k EXEC/s), and the X2-enabled candidate must improve further.
   These are acceptance thresholds, not achieved results. X2's design also
   requires same-shard 64x4/16x4 >=0.95 in each mode; >=0.90 alone is insufficient.
4. The 14 generic cells plus 2s GET/SET p1/p32, union
   `h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h49,h50,h63,h64`, using the
   files in `docs/exec1s/`. Run POST/PRE, an independent byte-identical null,
   and POST-layout/PAD-A. No failing cell is averaged away.
5. Record rate, cycles/op, instructions/op, IPC and latency, plus
   `atomic_txn_*`, EXEC and plain-writer counts, WB sends/retired operations,
   placement, IO/EX kernel entries, owner passes, eager collapses and extra
   passes. Atomic order violations must remain zero. Require actual eager
   collapses and extra passes where those mechanisms are being judged. For
   X1, check <=1.05 kernel entries per idle-EX rotation with a kernel-side
   count as well as counters. X3 rotations are fused IO `iterations`.

Explicit lane-safe resource arguments for both external drivers are
`--server-cores 64-71 --load-cores 72-95 --port 20000`. Supply `--candidate`
and `--reference` for merit, or `--binary` for depth, plus
`--benchtxn /home/user/Projects/cx-exec1s-d/build/benchtxn` and a distinct
`--output` per arm/comparison. The client was built but never executed; its
hash is in [benchtxn-build.json](docs/exec1s-d/benchtxn-build.json). The maintainer schedules the quiet box.

### Reproduction and storage

All lane commands run under `taskset -c 64-95`; builds use `make -j32`.
`tools/exec1sd_proof.py` runs only selected correctness jobs, on server CPUs
64–87 and test CPUs 88–95, ports 20010–20097. Native SAVE replay reserves
20000/20001; gates_test uses 20098; the serverless idle fixture uses 20099.

```sh
taskset -c 64-95 python3 tools/exec1sd_proof.py families
taskset -c 64-95 python3 tools/exec1sd_proof.py supplement
taskset -c 64-95 python3 tools/exec1sd_proof.py differ
taskset -c 64-95 python3 tools/exec1sd_proof.py harness
taskset -c 64-95 python3 tools/exec1sd_proof.py zc
taskset -c 64-95 python3 tools/exec1sd_proof.py freshness
taskset -c 64-95 python3 tools/exec1sd_receipts.py
```

For a fresh copy of an attribution arm use `tools/exec1sd_arms.py ARM`; the
builder compiles one source tree, records the binary and bounded counts, then
retires its source/objects and large traces. PRE objects are kept only until
the common-image PAD link. Frozen production binaries, compact receipts and
failure logs remain reviewable. `build/` occupies about 27 GiB; no arm source
trees or large instruction traces remain. No push was performed.
