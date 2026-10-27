## multifix

Lane `cx-multifix`, baseline `83e0b809d` (wave 8). No push. No throughput measurements or full iteration gate are authorized in this lane; the maintainer owns those runs.

### Changes and owner decisions

| Root | PRE / Redis 7.4.10 | Candidate change |
| --- | --- | --- |
| RESET-IN-MULTI | PRE queues RESET; Redis immediately returns RESET and discards the transaction | Dispatch RESET through existing owner-routed WATCH cleanup and the connection-local handler |
| WATCH-SPURIOUS-INVALIDATION | Same-shard no-op SMOVE aborts a destination WATCH on PRE; Redis commits | Do not install or notify an unchanged destination; test same-shard and different-shard placements explicitly |
| PAUSE-IN-MULTI | PRE returns an error for queued CLIENT PAUSE | Publish PAUSE inside the winning commit bracket, with EXEC's frozen timeout; retain physically expired keys while paused, including RANDOMKEY semantics |
| PAUSE-EXEC-NOT-HELD | PRE executes a queued writer under PAUSE WRITE | Classify EXEC using queued command flags, including write-capable scripts; account held clients and release them on unpause |
| SLOWLOG-EXEC-BODY-NOT-LOGGED | PRE omits the inner DEBUG SLEEP; Redis logs it and excludes EXEC | Accumulate inner execution slices and log once at logical retirement, in EXEC order; include DEBUG SLEEP's deliberate delay without publishing wounded attempts |
| Repeated-key EXEC cost | PRE installs 128 / 512 / 4,000 versions for that many XADDs | Reuse the newest parent-owned private version, retaining its committed predecessor and preserving distinct child-scatter decisions |
| MULTI-OOM-QUEUE / MULTI-OOM-EXEC | Both reproduce in both modes | **Stopped for owner decision:** current maxmemory is per-shard object admission; Redis performs global allocator-memory admission and eviction before queuing / executing. Exact behavior needs a coordinated admission design. No approximation based on a stale shard sum or `maxmemory == 1` was added. These Tcl failures remain named. |
| MULTI-POLICY-REFUSAL | Existing intentional policy differs from Redis | Unchanged: no approving owner line was found in `/home/user/Projects/round4-read/REGISTER.md`. |

The OOM stop is a model change, not just a missing MULTI flag. `FlatStore` explicitly excludes table history and allocator metadata from its logical cache budget (`src/store/flatstore.h`, `kSlotOverheadPerKey`); executor configuration divides maxmemory by the shard count (`src/core/ex_loop.h`). Owner-local `budget_admit` can evict only on that owner. Redis's `processCommand` instead performs global eviction before its combined EXEC deny-oom check. Introducing a process-wide admission/eviction result that remains authoritative across owners needs the owner's design decision. The supplied maxmemory=1 reproductions remain different on POST, as recorded rather than hidden.

The literal `#!lua` header is accepted as a narrow prerequisite for the unchanged upstream pause-script assertion. Script flags and other shebang compatibility roots are not claimed fixed.

Baseline wire transcripts and the pinned oracle digest are in [pre/results.json](docs/multifix/pre/results.json). The supplied WATCH case needs a same-shard boot to expose PRE; the directed row chooses keys by DEBUG SHARD. The unchanged upstream Tcl case instead rerolls fresh boots, at most 128, until its fixed keys share a shard. It fails on PRE in both modes and passes on Redis; [pre-watch-upstream.json](docs/multifix/pre-watch-upstream.json) records those runs. Failure to arm fails the job. Its exhaustion control is in `tests/redis_tcl_test.py`.

The repeated-key result is a structural correctness witness, not a rate measurement:

| XADDs in one EXEC | PRE version records | Candidate version records |
| ---: | ---: | ---: |
| 128 | 128 | 1 |
| 512 | 512 | 1 |
| 4,000 | 4,000 | 1 |

Every reply, stream length, first entry and final entry is checked against the oracle. The linearity evidence covers parent-owned repeated writes, including the reported XADD case. A new child-scatter/foreign record still requires a new parent version; the optimization does not overwrite the committed predecessor.

### Gate accounting

Six roots × two modes × two engines add 24 public rows. Each row contains atomic 0/1 × read-local 0/1 × databases 1/16, with a fresh server for every leg. All new collection calls precede the quick-tier exit: **DQ = +24, DF = +24**.

The baseline source declares **806 quick / 823 full**, although its constants say 798/815. After this lane the source inventory is **830 quick / 847 full**. The maintainer should set those counts; this lane does not edit EXPECT_QUICK or EXPECT_FULL. The explicit label fixture is updated from declarations, not from a passing run. See [row-counts.json](docs/multifix/row-counts.json).

Eight unchanged upstream assertions were removed from named skips and made required passes; [tcl-promotions.json](docs/multifix/tcl-promotions.json) lists them. The EXEC slowlog assertion runs unchanged on its own fresh server: the retained zero-capacity assertion leaves slowlog-max-len=0, while skipped predecessor tests normally restore capacity. The harness requires both the existing assertions and the isolated assertion, and negative controls reject missing, failed or duplicate isolated receipts. The earlier whole-file failure is retained as evidence of this setup dependency. The performance defect had no failing Tcl assertion to promote, so its new version-record witness carries that proof. OOM and policy skips remain.

### Proof receipts

PRE is `83e0b809d`; production POST is `dbecac9ad` (later commits contain only tests and proof artifacts).

| Arm | Path | SHA-256 |
| --- | --- | --- |
| PRE | `build/multifix/tomokv-pre` | `75d75adb8907cd6c97f010dfd6337fe7f58806c17143b025795808ca06aefdc3` |
| POST | `build/multifix/tomokv-post` | `a0b3524f37e1cb287d479247849f034484b3a6fd383c8748666793a514b4c1d5` |
| PAD-A | `build/multifix/tomokv-pad-a` | `c17ad840d8a9125ee2610c41d506b42103f6a3dcf73ae7697a8383259616ae83` |
| Redis oracle | `/home/user/Projects/redis74/src/redis-server` | `ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b` |

All **72 matched serverless command-scope cases add zero instructions**. They cover both modes, normal/db0 compiled namespaces, batches 1/32, atomic 1 (also 0 for MSET), and slowlog -1/10000 for GET/SET/INCR. Read-local is 0. The scope includes linked production `exec_batch_prefetched` and named TomoKV routines; it excludes network parsing, the read-local lane, fixture glue, and out-of-scope library callees. Clock-call counts also match PRE in all 72 cases. The complete comparison and probe hashes are in [instructions/comparison.json](docs/multifix/instructions/comparison.json).

Representative normal-namespace counts, batch 1, atomic 1, slowlog -1 (MGET/MSET use eight keys):

| Command | 1s PRE | 1s POST | 2s PRE | 2s POST |
| --- | ---: | ---: | ---: | ---: |
| GET | 939 | 936 | 1,559 | 1,556 |
| SET | 1,068 | 1,054 | 1,688 | 1,674 |
| INCR | 1,531 | 1,528 | 2,151 | 2,148 |
| MGET | 10,243 | 10,219 | 10,243 | 10,219 |
| MSET | 17,080 | 17,064 | 16,726 | 16,710 |

The final binary passed all 24 directed public rows (192 fresh-server legs). PRE and the planted regression each failed all 24 rows. The scheduler controls passed all 73 tests (`python3 tests/gates_test.py`; [log](docs/multifix/gates-test.log)). `make all`, all 45 explicit production-unit targets, both recursive live-control builds, and the blockfix targets passed all 50 freshness checks; [freshness.json](docs/multifix/freshness.json) records every `make -q` result and artifact hash.

The corrected Tcl job passes all 1,651 required assertions in each mode (35 files per mode, 3,302 assertion results total), including all 16 promoted name/mode pairs; [final-tcl.json](docs/multifix/final-tcl.json) binds the receipts and arming evidence. All 16 promoted Tcl name/mode pairs fail on the planted regression using the corrected harness; [proof-summary.json](docs/multifix/proof-summary.json) records each failure. The mutant disables the original root mechanisms in an intermediate candidate, before the final retirement/timer refinements; it is not an exact final-source mutant. Its SHA-256 is `1e5222abadeadf68bcd878b084c11c9d5be094aaf6fb9aa8220898dbf7c71009`; [regression-build.json](docs/multifix/regression-build.json) records its build and patch.

The affected-job run recorded 143 passing rows and eight mover rows refused for missing sibling native binaries. Their live checks passed; after pairing the fresh native witnesses with the frozen POST binary, the whole mover job passed (9 rows including its release prerequisite). Both receipts are retained: [affected](docs/multifix/jobs/final-affected.json), [paired mover rerun](docs/multifix/jobs/final-moverfix-paired.json).

Both network engines passed all five standard differential jobs: split atomic 0/1, armed fused atomic 0/1, and mode equivalence. Each uses the permanent seeds 7/19/20/23 plus the selected rotating seed (24 for uring, 25 for epoll), the 47-suite plan, and four repeats. The stock split-only SORT exclusion is retained in armed fused mode. [final-differ.json](docs/multifix/final-differ.json) records each plan, terminal verdict and output hash.

**Remaining required-job failure:** `abba_selftest` ran through the gate interface and returned FAIL because `gate_receipt.py` refuses `EXPECT_FULL=815` against the matching fixture/source inventory of 847. It reports no missing or extra fixture labels. Other controls, including the 73 scheduler tests and eight Tcl-harness controls, passed; the receipt check remains red until the owner updates the constants. This is retained as a failure, not converted into a pass: [job receipt](docs/multifix/jobs/final-instrument-controls.json), [control output](docs/multifix/instrument-controls.log). EXPECT_QUICK and EXPECT_FULL remain untouched.

The atomic correctness job passed in all four mode/engine combinations, covering torn reads/window arming, read-your-own-writes, mixed writes, owner-local hazards and shutdown invariants. Each invocation records four passing battery rows plus its release prerequisite. The throughput experiment was disabled explicitly, and each RYOW output records that skip; [atomic-stages.json](docs/multifix/atomic-stages.json) lists the invocations and [proof-summary.json](docs/multifix/proof-summary.json) binds their output hashes.

The final literal wire reproductions match Redis in both modes for RESET, both PAUSE roots and EXEC slowlog. They continue to differ for the two stopped OOM roots and the unapproved policy root, as expected and recorded in [final-wire/results.json](docs/multifix/final-wire/results.json). WATCH and repeated-key EXEC retain their dedicated armed/structural proofs above. The final freshness rerun again reports all 50 checks fresh.

Earlier attempts are preserved under `docs/multifix/jobs` and the per-attempt directories. The early Tcl setup failure, stale native witnesses, and scheduler-fixture timeouts under concurrent build/probe work are superseded by the corrected/rebuilt/quiet runs above. Cancelled runs are not final proof. The gate is invoked only via `GATE_ONLY_JOBS`, never its iteration or measurement tiers. CPU allocation is 32–47, build parallelism 16, server geometry 16 shards and split ratio 6:2, ports 20500–20599.

**NOT RUN:** throughput measurements, performance ABBA, the full `tests/gate.sh iteration`, and the atomic battery's throughput comparison. Those runs belong to the maintainer; the atomic correctness run uses the gate's existing `GATE_PROOF_NO_RATES=1` switch, which skips the rate experiment entirely. OOM fixes and their Tcl promotion are **not implemented**, pending the admission architecture decision above. MULTI policy remains unchanged pending explicit owner approval.

### Maintainer measurement request

Use the gate's own ABBA instrument, on the scheduled quiet box, for PRE/PRE null, PRE/POST and PRE/PAD-A, with contemporary same-binary controls. [measure-cells.txt](docs/multifix/measure-cells.txt) contains the 14 generic cells, the four required 2s GET/SET p1/p32 null companions, and eight MGET/MSET p1/p32 companions across both modes. Parsing this file with `--list-cells` starts no workloads; [measure-cells-parsed.json](docs/multifix/measure-cells-parsed.json) records the coverage.

Also measure these cold paths in 1s and 2s, both engines, atomic 0/1, and read-local 0/1:

- One-key EXEC with 128, 512 and 4,000 XADDs; counterparts with the same commands outside MULTI and a transaction writing N distinct keys. Verify final stream data and collect execution cost per command, total EXEC latency, instructions/op, cycles/op and IPC. The deciding question is whether total transaction work grows linearly and the generic cells remain within qualified nulls.
- Ordinary INCR at p1/p32 in both modes, plus repeated-key SET/INCR and eight-key MSET transactions, including a child-scatter write between repeated parent writes, to expose version-layer costs.
- WATCH with same-shard and different-shard SMOVE, destination already containing versus newly receiving the member.
- MULTI/EXEC with slowlog disabled and a nonzero threshold; ordinary GET/SET at both thresholds to verify the cold logging path has no common-command cost.
- PAUSE/UNPAUSE and paused write EXEC, plus expired GET/RANDOMKEY before and after unpause. Score blocking/order/data correctness separately from service cost; do not count paused waiting time as completed service.

The current stock instrument has no EXEC/XADD/SMOVE/INCR workload grammar. These last scenarios require maintainer instrumentation; no ad-hoc throughput substitute was run here. Rate at matched offered load is the verdict for ordinary commands; instruction counts and IPC explain it. No throughput claim is made.

PAD-A is a **type A behaviour twin**: unmodified PRE production objects with padding matching POST's `.text` origin and total size. Individual function offsets and data sections retain PRE layout; it is not an exact per-symbol/data-layout twin. The linker/input receipts disclose this limit. Do not treat it as proof that every placement effect is excluded.
