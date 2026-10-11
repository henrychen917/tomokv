## mkfix

**No production optimization accepted.** PRE is `991d48f651d3c6e1324c061bd9ea801ac085afe8`; worktree `/home/user/Projects/cx-mkfix`, branch `cx-mkfix`. No push. C1 and C4 are skipped on their measured predictions; C2 and the first required part of C3 are stopped by the requested hot-path identity law. `src/`, `Makefile` and `tests/` are unchanged from PRE. The final executable has identical runtime sections and all 16,439 emitted bodies match.

### Decisions

| Item | Verdict and disposition |
|---|---|
| M1 / C4 | **REFUTED** in the declared count geometry: MGET batches rise with depth much like GET, rather than staying within the study tool’s 0.9–1.1 replies/send interval. Plain MSET also batches. Atomic MSET alone stays near one. **C4 skipped: refuted.** No reply-bound field, write-back constant or policy change. |
| M3a / C2 | **CONFIRMED**: warmed MGET-7 needs no reply/argv allocations; MGET-8 pays exactly three reply mallocs plus one argv realloc per command. The one-line reply-only retention candidate built, but changed 56 selected hot bodies. **C2 stopped and reverted** before a production commit. Argv handling was never changed. |
| M3b / C1 | The three reply mallocs are real, but the proposed growth-loop explanation and remedy are **REFUTED**: the existing doubling loop computes capacity before a single malloc. The requested rounded-need formula still makes 3 allocations for MGET-8 and the same allocation count at every swept key count. **C1 skipped: refuted remedy.** |
| M5 / C3 | **CONFIRMED** for longer individual sweeps and the study’s p32 symbol-share discriminator: median refresh share is 0.38–0.56%, above its approximately 0.3% refutation level and above p8. This does not establish the cause of the throughput collapse: visited entries/command actually fall with depth. The first required padding step changes ordinary Server member offsets and 189 selected hot bodies (193 with the full checker’s extra executor run bodies). **C3 stopped at that step**; the tombstone/prefix algorithm was not implemented, and the exact published floor remains PRE. |

### What was counted

All commands ran under `taskset -c 32-47`; servers used 32–39, count clients 40–47, and ports were within 25500–25599. Both modes used 16 shards; split used `--ratio 6:2`; `--read-local 0`, default load balancing, and `--wb-policy 1`. The task’s explicit count and correctness instructions were used; no throughput or latency measurement, full gate, push, or merge was performed.

The fixed-command client uses 64 persistent connections, eight client processes, 64-byte values, a repeated fixed key tuple (`mkfix:000000`, etc.), and full request/response batches at the requested depth. Each connection warms with 128 commands before 1,024 measured commands. Every reply is byte-checked, and measured INFO cmdstat deltas must equal 65,536. These are finite count cells at the gate geometry, not the original 32-core uniform-key workload, saturation or quiet-box merit evidence. In particular their send ratios must not be generalized to every offered-load shape.

WB totals come from unmodified PRE, six fresh boots per cell: `retired / sends_submitted` in the clean-shutdown JSON, including warm-up, population and three control commands. Allocation/floor counts use six separate scratch boots per cell, with an LD_PRELOAD interposer calling the real jemalloc entrypoints; its shared counters are enabled only for the measured command interval. Nested allocator entrypoints are not double counted. “Allocations” counts allocation requests, including realloc even if it grows in place. The snapshot counter adds one event after the existing sweep, recording initial length and removals; both instrumented namespaces were rebuilt. **The interposer and snapshot instrumentation stay under ignored `build/mkfix/scratch/`; no counter is committed to production or as a patch.**

The key sweep uses 512 measured commands/connection (32,768 commands), one exact allocation census per key-count/mode/atomic/depth combination. Main cells and symbol profiles each have six replicas. Every requested raw count and every replica are in [all-counts.csv](docs/mkfix/proof/all-counts.csv); the full INFO observations, allocator size bins, command argv, and shutdown totals are retained in the compressed JSONL receipts under [docs/mkfix/proof](docs/mkfix/proof). There are 180 uninstrumented WB rows, 180 scratch count rows, 112 key-sweep rows and 72 symbol profiles: **544 rows**.

### Main PRE counts

Medians of six boots. `heap/cmd` includes all intercepted allocation entrypoints. `scan avg` is entries visited/sweep per boot, `scan/cmd` is entries visited/measured commands, and `scan max` is the largest observed sweep across the six boots. Fanout ratio is from the scratch measurement interval. GET/MSET have no floor sweeps in these cells.

| Mode | Cmd | Atomic | P | Replies/send [min,max] | Heap/cmd | Scan avg | Scan/cmd | Scan max | Fanout cuts/cmd |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1s | GET | 0 | 8 | 7.898 [7.831,7.908] | 0.0000 | 0.00 | 0.000 | 0 | 0.000 |
| 1s | GET | 0 | 32 | 30.734 [30.430,30.889] | 0.0000 | 0.00 | 0.000 | 0 | 0.000 |
| 1s | GET | 0 | 128 | 41.122 [40.203,41.609] | 0.0010 | 0.00 | 0.000 | 0 | 0.000 |
| 1s | MGET | 0 | 8 | 7.761 [7.668,7.949] | 4.0436 | 45.88 | 1.567 | 104 | 1.000 |
| 1s | MGET | 0 | 32 | 30.321 [29.818,31.127] | 4.6588 | 192.46 | 1.396 | 480 | 1.000 |
| 1s | MGET | 0 | 128 | 40.346 [38.995,43.173] | 4.7392 | 218.70 | 1.231 | 766 | 1.073 |
| 1s | MGET | 1 | 8 | 7.710 [7.661,7.935] | 4.0475 | 44.16 | 1.614 | 106 | 0.000 |
| 1s | MGET | 1 | 32 | 31.100 [31.035,31.432] | 4.6515 | 190.28 | 1.446 | 480 | 0.000 |
| 1s | MGET | 1 | 128 | 39.830 [38.049,42.971] | 4.7383 | 224.69 | 1.268 | 601 | 0.000 |
| 1s | MSET | 0 | 8 | 6.900 [6.828,7.013] | 2.0182 | 0.00 | 0.000 | 0 | 0.000 |
| 1s | MSET | 0 | 32 | 18.393 [18.252,18.593] | 2.4838 | 0.00 | 0.000 | 0 | 0.000 |
| 1s | MSET | 0 | 128 | 26.501 [26.167,26.892] | 2.6802 | 0.00 | 0.000 | 0 | 0.000 |
| 1s | MSET | 1 | 8 | 1.002 [1.001,1.010] | 2.0126 | 0.00 | 0.000 | 0 | 0.000 |
| 1s | MSET | 1 | 32 | 1.002 [1.000,1.004] | 2.0362 | 0.00 | 0.000 | 0 | 0.000 |
| 1s | MSET | 1 | 128 | 1.001 [1.000,1.003] | 2.0362 | 0.00 | 0.000 | 0 | 0.000 |
| 2s | GET | 0 | 8 | 7.984 [7.981,7.988] | 0.0000 | 0.00 | 0.000 | 0 | 0.000 |
| 2s | GET | 0 | 32 | 30.967 [30.760,31.058] | 0.0000 | 0.00 | 0.000 | 0 | 0.000 |
| 2s | GET | 0 | 128 | 50.605 [49.352,51.561] | 0.0010 | 0.00 | 0.000 | 0 | 0.000 |
| 2s | MGET | 0 | 8 | 7.771 [7.753,7.796] | 4.1353 | 59.35 | 1.747 | 144 | 1.000 |
| 2s | MGET | 0 | 32 | 29.460 [28.350,30.712] | 4.6580 | 213.73 | 1.196 | 512 | 1.588 |
| 2s | MGET | 0 | 128 | 47.681 [42.161,49.291] | 4.7452 | 267.45 | 1.126 | 832 | 3.347 |
| 2s | MGET | 1 | 8 | 7.797 [7.786,7.815] | 4.1450 | 61.86 | 1.752 | 160 | 0.000 |
| 2s | MGET | 1 | 32 | 29.397 [28.703,30.308] | 4.6385 | 202.00 | 1.045 | 544 | 0.000 |
| 2s | MGET | 1 | 128 | 48.281 [45.972,49.192] | 4.7429 | 266.89 | 1.234 | 832 | 0.000 |
| 2s | MSET | 0 | 8 | 7.033 [6.984,7.065] | 2.1146 | 0.00 | 0.000 | 0 | 0.000 |
| 2s | MSET | 0 | 32 | 19.184 [18.462,20.415] | 2.5541 | 0.00 | 0.000 | 0 | 0.000 |
| 2s | MSET | 0 | 128 | 39.540 [31.022,40.583] | 2.7213 | 0.00 | 0.000 | 0 | 0.000 |
| 2s | MSET | 1 | 8 | 1.002 [1.002,1.002] | 2.0539 | 0.00 | 0.000 | 0 | 0.000 |
| 2s | MSET | 1 | 32 | 1.004 [1.002,1.005] | 2.0461 | 0.00 | 0.000 | 0 | 0.000 |
| 2s | MSET | 1 | 128 | 1.005 [1.005,1.007] | 2.0566 | 0.00 | 0.000 | 0 | 0.000 |

Atomic-0 MGET moves `atomic_fanout_cuts` exactly once per delivered command in the short main count cells; atomic-1 leaves it zero by construction. `atomic_read_cuts_held` is zero in these pure cells too: the current `atomics_glue.inc:844` increments it when a plain read’s retained cut differs from the current cut, **not** as a general count of MGET registrations. Nonzero scratch sweeps/removals prove the atomic-1 MGET registration path instead.

### Key-count allocation census

Each entry is total heap allocation requests per command. Exact per-entrypoint counts and command denominators are in the CSV/JSONL; the stable argv realloc sequence is MGET `[0,0,0,0,1,1,2]` and MSET `[0,0,1,1,2,2,3]` for the seven key counts. Warmed MGET reply mallocs are `[0,0,0,0,3,3,4]`. MGET-16 therefore has a second argv step (argc 17), contrary to the study’s no-further-cliff prediction.

| Mode | Cmd | Atomic | P | K2 | K3 | K4 | K7 | K8 | K9 | K16 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1s | MGET | 0 | 8 | 0.0627 | 0.0506 | 0.0680 | 0.0533 | 4.0785 | 4.0341 | 7.0000 |
| 1s | MGET | 0 | 32 | 0.5893 | 0.6286 | 0.6964 | 0.6183 | 4.6700 | 4.6654 | 7.0001 |
| 1s | MGET | 1 | 8 | 0.0513 | 0.0282 | 0.0198 | 0.0325 | 4.0789 | 4.0164 | 7.0000 |
| 1s | MGET | 1 | 32 | 0.6725 | 0.6737 | 0.6015 | 0.6783 | 4.6155 | 4.6236 | 7.0001 |
| 1s | MSET | 0 | 8 | 0.0250 | 0.0643 | 1.0237 | 1.0396 | 2.0168 | 2.0239 | 3.0134 |
| 1s | MSET | 0 | 32 | 0.6640 | 0.6203 | 1.5747 | 1.4829 | 2.4641 | 2.4506 | 3.2994 |
| 1s | MSET | 1 | 8 | 0.0065 | 0.0073 | 1.0067 | 1.0143 | 2.0148 | 2.0186 | 3.0151 |
| 1s | MSET | 1 | 32 | 0.0550 | 0.0915 | 1.0510 | 1.0547 | 2.0162 | 2.0436 | 3.0349 |
| 2s | MGET | 0 | 8 | 0.0337 | 0.0448 | 0.0720 | 0.1183 | 4.1186 | 4.1442 | 7.0000 |
| 2s | MGET | 0 | 32 | 0.6984 | 0.6750 | 0.6735 | 0.5861 | 4.6833 | 4.6307 | 9.5439 |
| 2s | MGET | 1 | 8 | 0.1441 | 0.0982 | 0.0602 | 0.0988 | 4.1487 | 4.1999 | 7.0000 |
| 2s | MGET | 1 | 32 | 0.6419 | 0.6352 | 0.6730 | 0.6429 | 4.6008 | 4.6155 | 8.4225 |
| 2s | MSET | 0 | 8 | 0.0000 | 0.0504 | 1.1558 | 1.1523 | 2.0934 | 2.0887 | 3.0652 |
| 2s | MSET | 0 | 32 | 0.6410 | 0.6417 | 1.6141 | 1.5822 | 2.5782 | 2.5359 | 3.4266 |
| 2s | MSET | 1 | 8 | 0.0095 | 0.0311 | 1.0217 | 1.0799 | 2.0711 | 2.1396 | 3.0288 |
| 2s | MSET | 1 | 32 | 0.2397 | 0.0495 | 1.1098 | 1.1212 | 2.0494 | 2.0633 | 3.0588 |

An additional prediction is refuted: the 64-block scatter pool is not allocation-free in the warmed deep-pipeline cells. For example, atomic-0 MGET in 1s requests about 0.04 arena allocations/command at p8 and 0.66–0.74 at p32/p128; those are 16 KiB `posix_memalign` requests. A bounded pool can free surplus completed arenas and later reacquire them even with a steady overall workload. This is recorded as evidence only; no arena/pool redesign was attempted.

### C1 isolated requested-formula check

A scratch program uses the actual `Op::Sink`, `reply_array_header` and `reply_bulk` helpers. A malloc link wrapper counts first-use reply growth. The sole control edit is `ncap = max(round_up_64(need), cap_*2)` in a copied header. Both replies and counts agree; the 1 KiB GET only changes allocated capacity. Receipts: [PRE](docs/mkfix/proof/c1-reply-pre.txt), [formula](docs/mkfix/proof/c1-reply-c1.txt).

| Reply | PRE mallocs | Formula mallocs | PRE capacity | Formula capacity |
|---|---:|---:|---:|---:|
| MGET-2 | 1 | 1 | 192 | 192 |
| MGET-3 | 2 | 2 | 384 | 384 |
| MGET-4 | 2 | 2 | 384 | 384 |
| MGET-7 | 3 | 3 | 768 | 768 |
| MGET-8 | 3 | 3 | 768 | 768 |
| MGET-9 | 3 | 3 | 768 | 768 |
| MGET-16 | 4 | 4 | 1536 | 1536 |
| GET-1024 | 1 | 1 | 1536 | 1088 |

### Snapshot symbol samples

Unmodified PRE, 1,048,576 checked commands per boot, six boots per cell, PID-attached `perf record -e cycles -F 199 --call-graph dwarf,8192`, enabled/disabled through acknowledged FIFOs around the measured interval. These are exclusive, period-weighted symbol shares, **not rate/cycles-per-op merit**. They were collected on the shared box and some overlapped this lane’s pinned compilation; do not infer quiet-box cycle savings from them. Full per-replica samples and shares are in the CSV and [profile receipt](docs/mkfix/proof/pre-profile.jsonl.gz).

| Mode | Atomic | P | Refresh share median % [min,max] | Total samples (6 boots) |
|---|---:|---:|---:|---:|
| 1s | 0 | 8 | 0.2223 [0.0000,0.4776] | 4943 |
| 1s | 0 | 32 | 0.5604 [0.2121,1.1496] | 6203 |
| 1s | 0 | 128 | 0.4562 [0.2499,0.5327] | 14427 |
| 1s | 1 | 8 | 0.3785 [0.2464,0.7094] | 5209 |
| 1s | 1 | 32 | 0.4031 [0.3373,0.5761] | 6907 |
| 1s | 1 | 128 | 0.4479 [0.2551,0.8365] | 16101 |
| 2s | 0 | 8 | 0.2528 [0.0000,0.8104] | 4878 |
| 2s | 0 | 32 | 0.5232 [0.0000,1.5867] | 6609 |
| 2s | 0 | 128 | 0.3440 [0.2778,0.4429] | 11747 |
| 2s | 1 | 8 | 0.2986 [0.1928,0.6069] | 5726 |
| 2s | 1 | 32 | 0.3847 [0.2137,0.8082] | 8844 |
| 2s | 1 | 128 | 0.2822 [0.1170,0.5797] | 11294 |

No `active_snapshot_floor` samples were observed; absence of samples is not proof of zero cost. In the longer profiled runs, atomic-0 fanout cuts/command reached **8.779**, so this counter is not always a fraction bounded by one: prepare can register/count a cut and then be abandoned by the later room check. The study’s ruled-out repeated-prepare explanation is therefore not established by these observations. This finding is not folded into an unauthorized optimization.

### Identity stops and artifacts

**C2** was exactly one source-line change: `if (reply.cap() > kShrinkKeep) reply.shrink_to_inline();` inside `Op::shrink()`. All 1,211 command handler bodies still matched, including GET/SET, but the law also covers ordinary parser/retirement/serve bodies. `lbstall_artifacts.py compare` rejected 56/1,204; `ccfix_audit.py` rejected 56/1,208 hot bodies, with 83 total changed emitted bodies. Examples include ordinary `WbEngine::serve<false,false,true>` (1,077 → 1,093 bytes) and a db0 parser body (9,714 → 9,762 bytes). All changes are listed in [C2 full inventory](docs/mkfix/proof/c2-full/changed-bodies.json), with [rejected diff](docs/mkfix/proof/c2-rejected.patch.gz). No compiler budget or identity-check exception was introduced.

**C3** was stopped at its minimal in-place slot padding prerequisite. Contrary to the older study’s “cold Server tail” premise, these arrays precede `read_local_state_`, `client_work_`, live query-buffer limits and other ordinary fields. Padding moves `tomo::client_work_` 97,152 → 111,552 and `read_local_state_` 96,088 → 110,472; Server grows 108,736 → 123,136 bytes. The db0 variant shifts likewise. All eight explicit locked sizes still hold. The full checker lists 1,030 changed emitted bodies, including 193 hot bodies; the narrower selector reports 189. [Changed functions](docs/mkfix/proof/c3-full/changed-bodies.json), [padding diff](docs/mkfix/proof/c3-padding-attempt.patch.gz), [layouts](docs/mkfix/proof/layouts.json). This does not claim that every possible broader implementation is impossible; it records why the requested minimal change was stopped under the identity rule. No tombstone queue, relaxed floor, or stale-cut allowance was introduced.

No C1/C2/C3/C4 production commit prefix survived. Accordingly, there are no `c1/`, `c123/` or `c1234/` POST arms and no POST prefix count/merit claims. The existing `c12/` executable is the **rejected C2-only attempt**, with C1 omitted. `c3-padding/` is a rejected padding candidate, **not a PAD control**. There is no accepted layout change requiring a PAD arm, and no quiet-box performance measurement is requested for these rejected candidates.

| Artifact | Path | SHA-256 |
|---|---|---|
| pre | `build/mkfix/pre/tomokv` | `330eb467062473b99c9913e024bbbcdc87a79108fcf2c3a783fced7f229fedef` |
| count | `build/mkfix/count/tomokv` | `06fdd64ff44459ee81af4b7e9ceb35b4d4b1cefb6482237608b1b154b43c5cb9` |
| c12 | `build/mkfix/c12/tomokv` | `7a8e31cbb6fb6b8a6dcb9b54c7c84defb785c52d206dad81aae55252e28914b8` |
| c3-padding | `build/mkfix/c3-padding/tomokv` | `00575d34ee6b71d18dc5c5b4a232cb5fde2d310d77e70ef824976ea446944e00` |
| final | `build/tomokv` | `330eb467062473b99c9913e024bbbcdc87a79108fcf2c3a783fced7f229fedef` |

Scratch instrumentation source/library digests are in [binaries.json](docs/mkfix/proof/binaries.json). These scratch sources are intentionally uncommitted. Every function delta of each rejected candidate is retained in its full inventory. The accepted branch changes only the count runner, supplied study, and evidence/report; **zero production functions change**.

### Proof and gate accounting

- `make -j16 all`: passed for PRE, rejected C2, rejected C3 padding, and the restored final tree. Normal GCC 13.3.0 Makefile/jemalloc flags; no compiler-budget changes.
- Every target in `job_production_units`: **29/29 built**, every target passed `make -q`, and `mdbqsbr-live-arms` built both controls. Exact target/command/exit inventory: [production-units.json](docs/mkfix/proof/production-units.json); compiler logs are retained compressed beside it. This is a build/freshness receipt, not a claim that every standalone unit binary was executed.
- Redis **7.4.10** differential: **64/64 legs passed, zero differences**, suites `string`, `xshard`, `multi`, `fanout`, seeds **7/19/20/23**, atomics **0/1**, both modes with read-local **0**. Split uses the gate’s 16-shard 6:2 geometry. The unchanged `differ_gate.sh` has only split/armed-fused presets, so a scratch exec wrapper removes the split ratio and supplies `--thread-mode 1s --read-local 0` for the fused run; it is preserved in [fused-rl0-wrapper.txt](docs/mkfix/proof/fused-rl0-wrapper.txt). Both target logs witness their actual mode and CPUs. [Split log](docs/mkfix/proof/differ-split.log.gz), [fused log](docs/mkfix/proof/differ-fused-rl0.log.gz), [all per-leg logs/coverage](docs/mkfix/proof/differ-raw.tar.gz). No source, seed, assertion or tolerance was changed.
- `python3 tests/wbland_checks.py check clauses`: **83/83 strict outcomes passed**, including negative controls. [Log](docs/mkfix/proof/wbland-clauses.log.gz), [receipt](docs/mkfix/proof/wbland-clauses.json).
- `python3 tests/gates_test.py`: final recheck **66/66 passed**, plus the nested **14/14** tests. The first run had six scheduler-fixture deadline failures (all exit **124**) while this lane was compiling/profiling. Both logs are retained: [initial failures](docs/mkfix/proof/gates-test.log.gz), [unchanged recheck](docs/mkfix/proof/gates-test-recheck.log.gz). No assertion/deadline was modified. The recheck ran after this lane’s builds and profiles finished.
- Final identity: `lbstall_artifacts.py compare` **1,204/1,204**; `ccfix_audit.py` **16,439/16,439** full bodies, **1,211/1,211** command handlers and **1,208/1,208** hot bodies. **Zero changed production functions**. `linked_bytes.py` reports **all runtime sections equal**, excluding only its standard build-ID-note allowance; `.text` is exactly **7,646,972 bytes** at the same address with SHA-256 `e14251dbe89e682f1d6a77dfb7bbbfcc3b167bea5558e56db3addd712b4fcd38`. [Full identity](docs/mkfix/proof/final-full/summary.json), [linked identity](docs/mkfix/proof/final-linked.json), [hot log](docs/mkfix/proof/final-hot.log.gz).
- All eight locks hold in both namespaces for every built arm: **Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624**. PRE/final Server fields and size also match. [Layouts](docs/mkfix/proof/layouts.json).
- No new floor algorithm or reply-bound candidate survived to need a regression row; the dedicated `xshard_plain_stale_cuts` gate row and throughput/latency merit remain unrun. No accepted prefix exists on which to repeat POST counts. This is the explicitly requested stop on identity failure, not a positive performance result. All owned listeners have been stopped.

DQ **+0**, DF **+0**: no gate row was added or removed, before or after the quick-tier exit at `tests/gate.sh:3700`. `EXPECT_QUICK=625` and `EXPECT_FULL=642` remain untouched and should remain 625 / 642.

### Reproduce count cells

```sh
# Run each command serially; output directories must be fresh.
taskset -c 32-47 python3 tools/mkfix_counts.py --binary build/mkfix/pre/tomokv --output build/mkfix/recheck-wb --replicas 6
taskset -c 32-47 python3 tools/mkfix_counts.py --binary build/mkfix/count/tomokv --shim build/mkfix/scratch/count.so --output build/mkfix/recheck-counts --replicas 6
taskset -c 32-47 python3 tools/mkfix_counts.py --binary build/mkfix/count/tomokv --shim build/mkfix/scratch/count.so --output build/mkfix/recheck-sweep --commands-list MGET MSET --depths 8 32 --keys 2 3 4 7 8 9 16 --commands 512
taskset -c 32-47 python3 tools/mkfix_counts.py --binary build/mkfix/pre/tomokv --output build/mkfix/recheck-profile --commands-list MGET --commands 16384 --replicas 6 --profile
```

Failed tool attempts were retained under `build/mkfix`: an initially invalid fused `--ratio`, preloading the jemalloc-only shim into taskset, short-lived bind-guard conflicts, one `io_uring init failed: -12` boot, and perf’s abbreviated `1K` sample-count header. The runner now omits split ratio for fused, loads the shim only into the server, guards live listeners with `ss`, and derives exact profile sample counts from perf’s capture log while preserving raw reports. Failed attempts have no successful row and are not counted as passes. Completed receipts were resumed only after the command/binary configuration check; no test assertion was weakened.

## mkfix2

PRE production source remains `991d48f651d3c6e1324c061bd9ea801ac085afe8`;
this lane starts from `33bb0bd8f` after the requested fetch/merge (already current).
The task-specific finite count and correctness runs use CPUs 32–47 and ports
25500–25599 only. No throughput/latency merit runs, full gate, or push.

The count runner now includes GET at **both** atomic settings. Scratch interposer
version 2 records ready prepares, unpublished abandonment (including registered
cuts), and common-arena hits/misses/overflow frees. Instrumentation sources,
libraries and instrumented objects remain ignored under `build/mkfix2/scratch`.
Uninstrumented reply/send counts are collected separately. Results and production
commit-prefix artifacts will be appended below; no new result is claimed here.
