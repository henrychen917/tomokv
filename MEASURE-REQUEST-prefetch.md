# Executor batch prefetch — EX4.1

## prefetch

Candidate on `cx-prefetch`, based on `ef5204b2e9650693228cc105b34625516898b82d`. Production change: `a3e90a3ea`, nine added lines in `src/core/ex_loop.h`; no runtime knob, allocation, field, command handler, execution-order change, or push. The maintainer's **hardcode-or-delete rule applies**: prefetch survival is established, performance merit is PENDING. If the matched-load merit does not show a gain, the next step is to delete this fallback walk, using the supplied DELETE arm as the candidate. Keep the fused owner-batch prefetch.

Read the entire `/home/user/Projects/round4-read/REGISTER.md` and its `ex-path.md` report. Re-established the EX4.1 anchors on this PRE instead of using the audit's old line numbers or twelve-body census. All builds and proof processes use CPUs 80–95; TomoKV/Redis correctness servers use 80–87 and ports 23800–23899, protocol clients 89–95. The early socket-only self-test port exception is recorded below. The serverless PMU fixture pins itself to spare CPU 88 after constructing its eight-core topology. Other lanes are active; none of these receipts is a quiet-box performance result.

### What changed and why

PRE `src/core/ex_loop.h:2274–2287` is the fallback inline walk. Its ordinary caller is `exec_batch` at PRE line 2377; R7's other caller is `src/core/reorder.cc:68`. `FlatStore::prefetch` at `src/store/flatstore.h:1959–1962` requests the primary and rehash-table bucket slots. The fused owner walk begins at PRE line 2297 and survives already.

POST keeps `prefetch_exec_batch` as a tiny inline guard at `src/core/ex_loop.h:2274`: only `n > 1` calls the new `noinline, flatten` `prefetch_exec_slots` at line 2283. The original loop body, route resolution, owner comparison, scatter/cursor/random exclusions and forward walk order are unchanged. A singleton has no out-of-line call, table touch or loop. Tasks still execute through the original `exec_batch_prefetched`, with the original slowlog, completion, deferred suffix and ownership behavior. The fused owner's method and policy are untouched. No store pointer survives the prefetch call; no reader retry, seqlock or overwrite is added. The release build still enforces its existing structure-size locks.

### Disassembly proof and falsifier

[All addresses and body names](docs/prefetch/disassembly.md), [PRE machine-readable evidence](docs/prefetch/pre-disassembly.json), [POST evidence](docs/prefetch/post-disassembly.json). `objdump -dwlC` enumerates **26 bodies containing the inlined PRE fallback**, thirteen in each of `tomo` and `tomo_db0`. Every one contains **zero prefetch instructions**. Per namespace:

| Embedded fallback location | Bodies | PRE bucket hints |
|---|---:|---:|
| plain 2s masked/unmasked transport drains, outer drain, embedded run | 4 | 0 |
| capable executor masked/unmasked drains, outer drain, interleaved producer and outer drain | 5 | 0 |
| R7 two emit closures and two queue submissions | 4 | 0 |

`ExLoopT<false>` is ordinary 2s; `ExLoopT<true>` serves 1s and the read-local-capable 2s executor. Snapshot drains have a separate per-task path and no fallback call. The audit's count of twelve is stale on this tree.

For example, PRE db0 `drain_tasks<32,false>` at `0xd4c30` retains the loop at `0xd4d90–0xd4dfd`: `0xd4dfa: mov (%rcx,%rsi,4),%ecx` loads the owner word, then `0xd4dfd: jmp 0xd4d97` discards it. No owner comparison or bucket instruction remains. The [source-annotated excerpt](docs/prefetch/pre-drain-excerpt.txt) is retained, alongside the [POST singleton branch](docs/prefetch/post-singleton-disassembly.txt).

POST has **two prefetcht0 instructions in each of four 333-byte `prefetch_exec_slots` bodies**, for both capabilities in both namespaces. The [complete db0/plain helper](docs/prefetch/post-walk-disassembly.txt) also shows the ownership comparison at `0xca212` and rejection branch at `0xca215`, before the first table-pointer load at `0xca232`. The two fused `prefetch_owner_batch` bodies retain two hints each and are identical in the linked body audit. The offline checker `python3 tools/prefetch_artifacts.py inspect ... --expect post` passes POST and **fails both PRE and PAD-A** with `missing bucket hints`. Missing symbols are failures too. DELETE and PAD-A separately confirm that fused hints remain. This is a standalone structural witness, not a new gate row: **DQ/DF = 0/0**. `EXPECT_QUICK` and `EXPECT_FULL` were not edited.

### Frozen arms

| Arm | Path relative to this worktree | SHA-256 |
|---|---|---|
| PRE | `build/tomokv-pre-prefetch` | `fc4a9fa7eb91ef6748aa03662b62eab600892a2f835521ea06ad21fb39871460` |
| POST | `build/tomokv` | `2361590f215dc452078b758223a77a826ec93821c7958da53e3aa2456f5587d9` |
| PAD-A | `build/tomokv-pad-a-prefetch` | `8523bfbe50cc0e61f3d1474fc5c2e89e9e6e5a0194e44656a68514037ed4be33` |
| DELETE | `build/tomokv-delete-prefetch` | `b90cff5ede08b5c6c30e832cb44afaf4fcaed6dac5a3238805fda33dd39d4aff` |

All four binaries are present. [Build information and fixture hashes](docs/prefetch/build-info.json), [arm manifest](docs/prefetch/arms.json).

* **PRE**: built from ef5204b2e before editing production source, normal `taskset -c 80-95 make -j16 all`; matching objects retained in `build/prefetch/pre-objects` and headers in `build/prefetch/pre-source`.
* **POST**: ordinary `build/tomokv`, unchanged Makefile flags and IPA budgets, GCC 13.3, jemalloc, both database namespaces.
* **PAD-A — behaviour twin**: an offline copy of POST with exactly eight fallback `prefetcht0` instructions changed to same-length architectural NOPs. All other bytes, sections, symbols and addresses stay identical; fused hints remain. [Every patched byte and address](docs/prefetch/pad-a.json). This restores PRE's absence of fallback hints, while retaining POST's caller guard, out-of-line call and address-generation loads; it is not a PRE instruction-path twin. Attribute POST vs PAD-A to the hints, and use PRE/DELETE to judge the whole mechanism. The ELF build-id is inherited from POST; SHA-256 identifies this arm.
* **DELETE**: rebuilt from a private source copy inside this worktree with the fallback helper/wrapper and both call sites removed; everything else in the source is identical to POST, including fused owner prefetch. [Exact control diff](docs/prefetch/delete.patch). Source and objects are at `build/prefetch/delete-source`, binary copied to `build/tomokv-delete-prefetch`.

`.text` bytes: PRE 8,124,983; POST/PAD-A 8,125,831; DELETE 8,122,791. POST is +848 bytes. No object layout changes. No PAD-B is needed to establish the requested exact POST-layout hint control; the labelled PAD-A is the comparison to use here.

### Serverless executed-batch counts

[All 36 PRE/POST rows](docs/prefetch/batch-counts.md), with raw counter totals in the four `docs/prefetch/counts-*.jsonl` files. `docs/prefetch/batch_counts.cc` invokes the actual release `exec_batch` and handlers, checks every Done state and exact reply, and retires outside the counted interval. It opens no socket or io_uring ring and starts no workers or load generator. Each row counts 512 batches with `perf_event_open` instructions and generic hardware cache-misses in one non-multiplexed user-space group. Empty-bracket overhead is subtracted; initialization, preparation, checks and retirement are excluded. Resident 32-key table, 16 shards, atomic/read-local/slowlog off, default balancers; the capable 2s type is exercised separately.

Representative plain-2s, multi-DB runtime rows:

| Command | Tasks/batch | PRE instructions/batch | POST instructions/batch | PRE cache-misses/batch | POST cache-misses/batch |
|---|---:|---:|---:|---:|---:|
| GET | 1 | 1612.090 | 1584.000 | 0.171875 | 0.181641 |
| GET | 8 | 5749.016 | 5999.002 | 0.052734 | 0.041016 |
| GET | 32 | 19933.041 | 20903.012 | 0.125000 | 0.060547 |
| SET | 1 | 1783.023 | 1755.002 | 0.031250 | 0.025391 |
| SET | 8 | 7117.055 | 7367.004 | 0.113281 | 0.058594 |
| SET | 32 | 25405.039 | 26375.055 | 0.050781 | 0.132812 |

Singletons save roughly 28 instructions in ordinary 2s, 29 in capable 2s, 31 in 1s. Ordinary 2s adds about 250/970 instructions at 8/32; capable 2s adds 243/939. Eligible fused multi-task batches retain the baseline instruction count. This quantifies work, not throughput: the tiny resident-data miss counts establish no cold-data benefit and no sign of a rate change. Instructions and IPC are complementary; the maintainer's matched-load rate is the verdict.

Rebuild the fixtures with `taskset -c 80-95 make -j16 -f Makefile -f docs/prefetch/counts.mk prefetch-counts`; run each `build/prefetch/counts-{pre,post,pre-db0,post-db0}` under `taskset -c 80-95`. Production is not instrumented.

### Identity (proxy, not a merit verdict)

The unchanged tools ran against frozen PRE; identity differences did not stop the work. [Every changed emitted body, with reason](docs/prefetch/object-changed-bodies.md); [every changed linked group, with reason](docs/prefetch/linked-changed-bodies.md). Complete emitted inventory and strict linked diffs are retained compressed under `docs/prefetch/`.

* `tools/ccfix_audit.py`: 17,951 / 18,048 emitted bodies equal; 97 changed/added/removed. **1,213 / 1,213 command handlers equal.** Its strict hot-body assertion fails (1,248 / 1,316 equal), including the intended executor drains; recorded, not suppressed.
* Complete linked audit through `tests/reorder_noop.py`'s unchanged literal-aware normalizer: 9,059 identical groups, 56 different/added/removed. Fused owner walks and GET/SET handlers are equal.
* `python3 tests/reorder_noop.py --report-only --literal-pools --expected-functions 333`: self-checks pass; 333 selected bodies; scheduler 46/66, envelope 118/120, dispatch 79/92, retire 8/8, commands 16/16, multi-key commands 31/31 identical. `strict_noop=False`, as expected for changed drains. The first invocation's historical default of 169 rejected the current 333-body inventory; the second uses the observed complete inventory, without changing any identity comparison.

The residual unedited parser/IO-loop inlining and register allocation changes are a **cost risk**, not a claimed identity pass. The db0 R7 sweep now inlines a tombstone-compaction call. The tiny `watch_flush` cold difference names an assembler study-label ordinal; an epoll difference names a literal-pool label. All are listed rather than excused by the intended GET/SET batch-path change. No compiler-budget sweep or unrelated source change was hidden in the candidate.

### Correctness and freshness

`make all` passed. All **45 make -q checks passed**: all, the 42 targets named by `job_production_units`, and the two concrete server builds behind its phony `mdbqsbr-live-arms` recipe. [Exact target/exit inventory](docs/prefetch/freshness.json). A phony aggregate cannot be fresh by definition, so the two recursive `all` targets are checked with their original flags. `build/owner-prefetch-unit` passed 1s/2s × read-local 0/1, including actual WATCH blockers and ordered suffix release.

The gate command is `GATE_ONLY_JOBS='core_units exbatch_units exbatch_live perfex_units perfex_live ntnew4_live reorder_sync reorder_engagement reorder_identity splitlocal_units fused-0 fused-1 dbdefault' REDIS74_ROOT=/tmp/claude-1000/redis74 taskset -c 80-95 tests/gate.sh quick --server-cores 80-88 --server-smt '' --load-cores 89-95 --load-smt '' --ports 23820-23899`. The planner allocates only 80–87 to the actual server slot; 88 supplies the sixteenth physical CPU for its build budget. This is PARTIAL through the unmodified job/dependency/timeout/finalizer interface, not a full quick or iteration gate. Final result: **45 rows passed, zero failed, exit 0**. [Ledger](docs/prefetch/gate-ledger.tsv), [summary](docs/prefetch/gate-summary.json), and compressed job/build receipts in `docs/prefetch/gate-proof.json.gz`; full artifacts: `build/gate-run.D0MIef`.

`GATE_TEST_PORT=23898 TMPDIR="$PWD/build/prefetch/selftest-tmp" taskset -c 89-95 python3 tests/gates_test.py` **passed all 70 tests, exit 0** ([final output](docs/prefetch/gates-test-port-bound.log)). No test source was changed. The initial attempt had two 45-second fake-scheduler timeouts while compilation was active; the first retry passed 70 tests. Those two early invocations omitted `GATE_TEST_PORT`, so two socket-only listener fixtures used default ephemeral ports instead of the lane range. This was a port-isolation mistake; TomoKV and Redis listeners stayed in the assigned range. The final receipt uses port 23898. Failed output is retained in `initial-proof-logs.json.gz`, and the first retry in `gates-test-retry.log`.

Initial job setup tried the nonexistent unsuffixed `fused` job, then the manifest's binary-only Redis path; both were corrected. Overlapping abandoned prerequisite builds were stopped and their unit objects removed before the final gate rebuilt them and passed all freshness checks. No failed run is counted as green.

The standard differential matrices run via [the exec-only engine wrappers](docs/prefetch/run-differ.sh), preserving `differ_gate.sh`'s suite and seed inventory, ownership checks and finalizers. Both engines and split/armed-fused geometries use target/oracle ports 23800/23801, CPUs 80–87, clients 89–95, 16 shards, ratio 6:2 for split, databases 16, atomic 0/1. Standard seeds selected at launch: 7, 19, 20, 23, 21 (permanent/discovered corpus plus rotating seed), 47 suites. The [uring/split matrix](docs/prefetch/differ-uring-split.json.gz) **passed 475 rows, zero failed**, with 474 differential legs, 2,149,691 recorded comparison witnesses and all 32 mode-equivalence combinations. The [uring/armed-fused matrix](docs/prefetch/differ-uring-armed-fused.json.gz) **passed 466 rows, zero failed**, with 464 differential legs, 2,098,740 recorded comparison witnesses and both read-local engagement checks. Both epoll matrices remain in progress. The stock armed-fused harness marks the ten SORT legs **NOT RUN: SORT requires split 6:2 geometry**; these are not counted as passes and are covered by the split matrix.

Full iteration and performance generators remain **NOT RUN: reserved to the maintainer**, as instructed.

### Maintainer merit request

**No throughput claim has been made and no performance benchmark/load generator was run.** Use the gate's own instrument on the scheduled quiet box, all four frozen arms, identical geometry/offered load, its null/confirmation rules, and per-cell cycles/op, instructions/op, IPC, rates, tails, batching and spreads. No averaged-away regression. Keep default key/client balancing, 2M keys, 512 connections, 20-second windows, atomic=1, reorder=0 and save disabled, as supplied by the instrument. Overlap is removed; the legacy cell field remains `ov=0` only.

1. The exact **generic 14 cells** are copied unchanged to [generic-cells.txt](docs/prefetch/generic-cells.txt): `h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`.
2. The direct mechanism matrix in [targeted-cells.txt](docs/prefetch/targeted-cells.txt) includes **2s GET/SET p8/p32**, read-local 0 and 1, both network engines and both database runtimes. It also repeats these corners in **1s** so both thread modes are explicit controls. 64 targeted cells; all clients access DB 0, with `--databases 1` vs `16` choosing the compiled runtime. The first mandatory mechanism comparison is the eight 2s/uring/db1 rows (GET/SET × p8/p32 × read-local 0/1); the other rows guard the same mechanism and fused baseline.
3. The lane CPU/port limits remain 80–95 and 23800–23899. An executable request within them is `taskset -c 80-95 python3 tests/abbagate.py --subset full --build-reference 0 --reference-binary build/tomokv-pre-prefetch --candidate-binary build/tomokv --cells docs/prefetch/generic-cells.txt --server-cores 80-87 --server-smt '' --load-cores 89-95 --load-smt '' --ports 23840-23849 --port 23840 --output build/prefetch/merit-post`. Run it from this worktree; repeat the generic file for PAD-A and DELETE. This is a request only. **The targeted 2s file cannot currently run at this lane geometry:** the unchanged instrument has a reviewed ABBA split only at 32 server threads, 16:16. Its pure geometry resolver rejects eight-thread split cells ([serverless preflight](docs/prefetch/merit-geometry.json)). The maintainer must schedule the targeted matrix at that reviewed larger geometry under a separate CPU allocation, or record a reviewed eight-thread ABBA geometry before using the lane allocation. The correctness ratio 6:2 is not silently promoted into a performance calibration. Use matching null/load-headroom certification in either case; an under-driven cell is invalid, never merit. No measurement configuration was edited.
4. Judge POST vs PRE for the entire change, POST vs PAD-A for the emitted hints at exactly the same layout, and POST vs DELETE for whether the walk earns its work. Depth-1 cells must retain the singleton saving without a rate/tail regression; fused multi-task controls must preserve baseline performance. The instrument's matched offered-load rate decides; instructions and IPC explain it. Require the gain to survive the standing null and confirmation policy with no main-command regression.
5. **If POST does not earn a gain, delete the fallback walk.** Do not ship a configurable experiment or justify it by disassembly alone. The DELETE binary is already built and hashed. Append the measured verdict and arm hashes in `MEASURE-RESULT-prefetch.md`; this lane has not pushed or merged.

Both cell files were parsed with `python3 tests/abbagate.py --list-cells` (serverless). The full iteration gate, all merit/ABBA/NIC traffic, cold-cache rate and load-generator experiments are **NOT RUN: reserved to the maintainer by the task**.
