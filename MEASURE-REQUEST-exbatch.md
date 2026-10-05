Lane `cx-exbatch`: EX1, EX3, EX6 implemented; EX2 deliberately unchanged. Builds and serverless proofs pass. Performance, both live boots, and the iteration gate are **PENDING MAINLINE**. No server, load generator, benchmark, gate, or perf session was run by this lane. No result below is a measured cycles/op claim.

Launch HEAD was `12fe9f8ad`. The required first fetch/merge advanced it to `cd02ecbab1502775f1c170e806971d1f7bbc3ee9`; this synchronized revision is PRE. Commits through `d1687d34d` contain the implementation and proof tools. The final report commit adds this request and its measurement inventory. Nothing was pushed.

**What changed and why**

| Item | PRE mechanism and current anchors | Candidate |
| --- | --- | --- |
| EX1 | `src/core/ex_loop.h:2463` publishes every owned shard at the batch boundary. `src/core/shard.h:322` previously issued four relaxed stores unconditionally, at offsets 28/32/40/48. Consumers include `src/cmd/t_server.cc:1826` and `:2700`. | Compare each gauge with the single owner's current value and store only a changed value. Preserve every caller, the complete owned-shard walk, all four gauges, and relaxed ordering. No sidecar, allocation, new knob, or batch coverage reduction. |
| EX3 | The ordinary write guards in `src/core/ex_loop.h:2649` and `:2730` each inspected the two cold maps through `Shard::has_watches()`. The empty case reads map size words at 1240 and 1296 twice across the handler. | `src/core/shard.h:283` reads one cached byte at offset 8. `src/cmd/multi.inc:2411` and `:2523` arm it after successful insertion; `:2370`, `:2390`, `:2428` refresh it after last-entry removal. WATCH reservations alone keep it armed. |
| EX6 | `command_metadata_resolve` performed linear parent and child lookups over the 374-row table and constructed a `std::string`. Some callers repeat resolution. | `src/cmd/cmdmeta.cc:72` precomputes name lengths and child counts; `:294` binary-searches the sorted table; `:323` uses the existing registry ID index for an assigned `op.spec`, skips child resolution for ordinary commands, and constructs a qualified child name in a bounded 29-byte stack buffer. |

EX1 preserves publication after deletes, expiry changes, flushes, eviction/counter decreases, and changes on shards other than the last task's shard. The whole `ex_loop.h` file is byte-identical to synchronized PRE. The publisher now outlines in this build; added calls/returns and comparisons are part of the candidate cost, not excluded from the verdict.

EX3 uses the same physical Shard as its two registries. Ownership migration therefore transfers the cache and registries together through the existing shard handoff; there is no per-owner mirror to move separately. All mutations remain owner-only. Duplicate WATCH, stale pruning, committed/aborted reservations, UNWATCH/EXEC/DISCARD cleanup, SWAPDB, and failed allocations preserve the gate's truth. SWAPDB changes dirtiness without changing registry cardinality. The failure rollback paths need no extra cache write because they leave the preexisting map population unchanged.

The hot byte comes from packing the two route endpoints from uint32 to uint16. Their maximum inclusive endpoint is 16384; compile-time and initialization checks enforce the bound. `bucket_begin` stays at 4, `bucket_end` moves from 8 to 6, and WATCH occupies 8. `zc_min` remains 12; gauges, FlatStore, Stats, and both maps retain their offsets. The route-width instruction changes are included in the full PAD comparison; the PAD uses POST's data layout and the same legal endpoint values.

| Layout | PRE bytes | POST bytes |
| --- | ---: | ---: |
| Op | 336 | 336 |
| Client | 1984 | 1984 |
| ThreadCtx | 1408 | 1408 |
| Shard | 1440 | 1440 |
| FlatStore | 944 | 944 |
| Rob<64> | 192 | 192 |
| AtomicEntry | 144 | 144 |
| Config | 624 | 624 |

Added offset assertions retain `store=56`, `stats=1000`, `watchers=1216`, `reservations=1272`; the new WATCH byte is 8. No sizeof lock moved or was weakened. There are no new reader retries, seqlocks, waits, in-place overwrite permissions, ownership exceptions, or ordering changes.

EX6 uses the task's sorted-table option. It does **not** cache a resolved child in Op or remove repeated call sites. After `op.spec` exists, the parent uses the registry's existing ID lookup; the parser's earlier arity check still needs binary parent lookup. Nested `COMMAND GETKEYS`, orphan child parents, case-insensitive and binary names, unknown children, and length overflow avoidance remain covered. The index is 374 × 4 = 1496 static bytes per database namespace, with no per-request allocation. The compile-time sortedness assertion rejects a future unsorted generated table.

Two scope qualifications matter to attribution. HSET/ZADD are ordinary registered commands and do not take `SubcmdRoute` on their normal dispatch path. Their cell tests EX1/EX3 and placement, not EX6. Also, PRE's short qualified names fit this libstdc++ string's small buffer: OBJECT|ENCODING is 15 bytes and XINFO|STREAM is 12. The allocation removal is directly exercised by the 21-byte XGROUP|CREATECONSUMER name. Calling every container command a malloc would overstate the change.

**EX2 condition was not met**

`src/core/ex_loop.h:2524` retains the per-operation `ClientWorkScope`. Its epoch protects Client pointers even after a ROB slot reaches Done and executor notification continues (`src/core/server.h:146`). Some paths have an enclosing scope, but retries, forwarding, tagged teardown tasks, and direct execution entrances need a complete enclosing-scope proof. This lane supplies neither a new debug assertion proving all those entrances nor the required teardown-under-load gate row. Removing the nested load based only on the common batch path would not satisfy the stated condition. The entire executor source is unchanged, and no EX2 saving is claimed.

**Cycles/op argument and static receipts**

Let S be the number of owned shards visited by a publication and n the number of executed commands amortizing that visit. These are measured batch quantities; pipeline depth alone is not n. The source still has both batch and loop publication sites, so use their actual visit frequency when extrapolating.

For four unchanged gauges, EX1 removes `4S/n` producer stores and adds `4S/n` published-value loads, comparisons, and conditional branches. The existing seven source-value loads per shard remain. The out-of-line PRE publisher executes 13 instructions including ENDBR/RET; POST's unchanged path executes 23, including its control NOP. That is **+10 instructions per shard publication**, before caller changes. A separate noinline unit wrapper changes from 12 instructions including RET to a jump plus that 23-instruction body. Changed gauges still store and can add taken-branch/rejoin work. At S=8, n=32, the unchanged case removes one store/op but adds one load, comparison, and conditional branch/op plus roughly 2.5 publisher instructions/op and caller effects. At n=8 those terms quadruple.

Skipping four stores does not mean four RFOs saved: ownership is acquired per cache line. `now_ms`/LRU and changed gauges still write the header, so actively touched shards may save no ownership transfer at all. The strongest EX1 hypothesis is an unchanged owned shard whose publication lines are being read elsewhere. Additional loads/branches and outlining can lose when no transfer is avoided. The polling cells below exercise the consumer; the no-poll generic cells must also stay inside their bands.

For EX3, a normal unwatched write's two predicate evaluations change **four cold map loads to two hot byte loads**. The direct noinline predicate changes from six executed instructions on an empty registry to three including the control NOP; on a nonempty watcher map PRE already short-circuits after one map load. Production inline guards are also recorded: POST emits NOP / hot-byte compare / branch at each ordinary write guard. Do not multiply the noinline wrapper's instruction count into a claimed production instr/op result. Cache maintenance adds a hot-byte store on successful insertion and on empty-map removal, plus its control NOP and refresh loads. WATCH-heavy work must repay those additions; the necessary registry work remains.

| Workload/regime | EX1 | EX3 | EX6 | Verdict to request |
| --- | --- | --- | --- | --- |
| GET p32/p8, 2s or owner-executed 1s | Unchanged gauges skip stores; new loads/branches/calls can dominate without readers of the publication lines. | No write predicate to remove. | No normal resolver work. | Zero regression; lower cycles only if publication coherence benefit is observed. |
| GET p32/p8, 1s read-local | Only residual owner/publication activity can benefit; clean lane reads bypass owner execution. | None. | None. | Primarily a placement/overhead control. |
| SET p32/p8, 2s and both 1s postures | Same-size replacements can leave all gauges unchanged; growth/TTL/eviction may still publish. Header clock stores remain. | Four cold reads become two hot reads for the two empty-registry guards. | None. | Lower matched-rate cycles from EX3, subject to EX1/control overhead; no cell may regress beyond its band. |
| Writes while WATCH is armed, all three regimes | Same publication tradeoff. | Predicate becomes hot, but a populated PRE watcher map often needed only one load. Cache mutation stores are additional work; reservation/dirty semantics are unchanged. | None for the six-frame recipe. | Measure net WATCH cost; do not extrapolate unwatched savings. |
| HSET/ZADD p32, all three regimes | Same publication tradeoff; warmed bounded objects keep gauge changes controlled. | Owner write predicates use the hot bit. | No direct normal-dispatch saving. | Zero regression; attribute any saving to EX1/EX3 using partial controls. |
| OBJECT/XGROUP (also unit-tested XINFO), all three regimes | Residual publication tradeoff. | XGROUP can exercise a write predicate; OBJECT does not. | Bounded binary probes replace hundreds of row probes; long child names avoid allocation/free. Repeated resolver calls remain. | Lower matched-rate cycles in the EX6-directed cells against EX6-OLD as well as total PRE. |
| MGET/MSET | Per-owner visits and cross-shard accounting determine amortization. | MSET/scatter helpers also use the cached predicate; do not assume exactly two evaluations per wire command. | No ordinary resolver saving. | Count one wire command, not eight keys; no regression. |

Static algorithm counts for one successful resolution are in [metadata-probes.json](docs/exbatch/metadata-probes.json). OBJECT ENCODING goes from 217+218 parent/child row tests to 8+6 binary probes before `op.spec`, or an indexed parent plus 6 after it. XGROUP CREATECONSUMER goes from 323+325 to 8+9, or indexed+9; it removes one observed allocation per resolution. XINFO STREAM goes from 330+334 to 9+8, or indexed+8; its PRE allocation count is zero. Unknown-child counting changes a 374-row child scan to a constant index read. Each probe still has byte comparisons and loop branches; these are algorithm counts, not retired instructions.

[static-functions.json](docs/exbatch/static-functions.json) and compressed disassemblies in [static](docs/exbatch/static/) contain PRE/POST publisher, predicate, lookup, resolver, and production split/fused execute receipts. [execute-watch-sites.json](docs/exbatch/execute-watch-sites.json) records exact sites. The PAD NOPs and retained legacy blocks are part of production text and of every measurement. No runtime switch exposes them. Removing this control scaffolding later changes the measured artifact and requires fresh identity/measurement evidence.

**Proofs completed on CPUs 112–127**

All builds used `taskset -c 112-127 make -j16`. PRE was built from a git archive of the synchronized source inside this worktree. POST, the ordinary `build/tomokv`, both namespace units, and a unit linked against frozen PRE objects built successfully. [build-and-checks.json](docs/exbatch/build-and-checks.json), [pre-build.log.gz](docs/exbatch/pre-build.log.gz), [final-build.log.gz](docs/exbatch/final-build.log.gz), and [unit-final-build.log.gz](docs/exbatch/unit-final-build.log.gz) preserve commands/compiler/layout evidence. `bash -n tests/gate.sh`, Python compilation, and `git diff --check` pass.

| Proof | Positive witness | Required negative control |
| --- | --- | --- |
| EX1, both namespaces | Real Shard with plain and expiring keys; all four published gauges match increases/decreases; multiple owned shards included. Protect the already-published Shard page read-only and publish 64 times. | Retarget only publication to PRE's four stores. The protected-page child fails and the parent rejects it with the exact zero-stores diagnostic. Frozen PRE independently fails the same witness. |
| EX3 cold loads, both namespaces | Put the header on an accessible page and both maps on an inaccessible page. An empty predicate must return false 64 times without reading either map. | Restore the old predicate; it faults on the protected map page and the parent rejects it. Frozen PRE does too. |
| EX3 lifecycle, both namespaces | Add/duplicate/remove, remaining watcher, dirty write, reservation-only gate, decided commit/abort, stale prune, swap, and cleanup. Blocking wait, coexisting reservation, and conflicting precommit counters must each fire. Allocation budgets 0…7 cover 6 failed allocation arms and 10 successes. | Separately suppress WATCH-add, last removal, stale prune, reservation append, and reservation-finalize cache updates; each fails its intended assertion. Suppressing all updates also fails. Full EX3-old semantics still pass the lifecycle test. |
| EX6, both namespaces | All 374 rows, uppercase spellings, unknown/long/binary names, orphan parents, nested COMMAND GETKEYS, parser null-spec path, and RESP2/RESP3 metadata replies. Count allocations around production resolution. | Restore all EX6 legacy bodies; the long qualified-name case fails the zero-allocation assertion. The detector separately observes the actual legacy allocation, so a disarmed detector cannot pass. |
| PRE semantic closure | Frozen PRE and POST produce exactly the same 223557 output bytes for the complete length-prefixed metadata-reply corpus; WATCH lifecycle agrees. | Frozen PRE independently fails publication, cold-map-load, and allocation witnesses. |
| PAD/source verifier | Five legacy bodies match PRE tokens; executor and generated metadata files are byte-identical. All expected control sites are enumerated from the ELF. | Removing a real legacy publication store fails source closure. For each server PAD, missing a required patch, changing an unrelated instruction byte, or moving a function symbol is rejected; those malformed server copies are never executed. |

The three check groups contain **32 positive/negative process outcomes** across both database namespaces (4 publication, 20 WATCH, 8 metadata). Their receipts are [publication-unit.json](docs/exbatch/publication-unit.json), [watch-unit.json](docs/exbatch/watch-unit.json), [metadata-unit.json](docs/exbatch/metadata-unit.json); the six frozen-PRE outcomes are in [frozen-pre-unit.json](docs/exbatch/frozen-pre-unit.json). Expected child faults are contained and have core dumps disabled. Every witness fails when its mechanism is absent; no window is skipped or tolerance widened.

The new live harness `tests/exbatch.py` is **written but not run**. It requires a fresh 16-shard boot, discovers keys on all 16 shards with bounded DEBUG queries, checks SET/TTL/delete totals, then exercises WATCH abort, UNWATCH, DISCARD, EXEC commit, and SWAPDB. A socket pipeline is not a deterministic witness of a particular internal batch boundary; the unchanged all-shard loop and serverless publication checks provide that part of the proof. INFO keyspace can use materialized per-database statistics; it alone is not a proof that all four published atomics changed.

Gate additions are three serverless rows plus one live row per mode. Their `collect_job` lines are **2935–2936**, before the quick exit at **3078**, so the delta is **+5 quick / +5 full**. At the synchronized baseline this means **473→478 quick, 490→495 full**. Mainline must update the counts and ledger labels when landing, accounting for any later rows. This lane changed neither EXPECT constant nor `tests/fixtures/nullrefresh-ledger-labels.json`. The live 2s job inherits the gate's 6:2 ratio and 16 shards on 0–7; 1s uses the existing fused boot helper, with no illegal ratio argument. Both use atomic=1, read-local=1, databases=4, balancers/flip=0, debug enabled, save empty, AOF off. Teardown-under-load coverage was not added or claimed.

**Built arms and exact PAD-A identity**

All paths are relative to this worktree. Full hashes, byte lengths, and unit hashes are in [binaries.json](docs/exbatch/binaries.json).

| Arm | Binary | SHA256 prefix | Behaviour |
| --- | --- | --- | --- |
| PRE | `build/exbatch/PRE/build/tomokv` | `5c2a0626ed3b3c73` | Synchronized `cd02ecbab` source. |
| POST | `build/exbatch/POST/tomokv` | `410da97a4e6f8516` | All three changes; exactly equal to `build/tomokv`. |
| PAD-A | `build/exbatch/PAD-A/tomokv` | `1a8411f96fbb3ff4` | **Kind A: PRE behaviour with POST text size/function layout and data layout.** All EX1/EX3/EX6 legacy edges selected; new cache maintenance skipped. |
| EX1-OLD | `build/exbatch/EX1-OLD/tomokv` | `2068ea2dafa5fa60` | Kind A for EX1 only; other items stay POST. |
| EX3-OLD | `build/exbatch/EX3-OLD/tomokv` | `d9cb457aab8f95f5` | Kind A for EX3 only, including skipped cache maintenance; others stay POST. |
| EX6-OLD | `build/exbatch/EX6-OLD/tomokv` | `f27303fd5ee26542` | Kind A for EX6 only; others stay POST. |

Local PRE and `/home/user/Projects/bench-bins/tomokv-headline-cd02ecbab` have **identical `.text` bytes and complete function symbols**, despite different whole-file hashes from build metadata. The text SHA256 is `c44b7d6be8b1bdcb941002a569e7bf6f3cf9b0cce1f3c69064ee8d7f5771d9aa`; [PRE-mainline-identity.json](docs/exbatch/PRE-mainline-identity.json) records this comparison.

| Identity property | PRE | POST | Full PAD-A |
| --- | ---: | ---: | ---: |
| `.text` bytes | 7729345 | 7731025 | 7731025 |
| Defined sized function entries | 10240 | 10241 | 10241 |
| POST function addresses/sizes all equal | No | Reference | Yes, every entry |
| Changed five-byte control sites versus POST | n/a | 0 | 52 |

The +1680-byte `.text` movement is real. PRE→POST is not an identity exemption: [pre-post-identity/identity.json](docs/exbatch/pre-post-identity/identity.json) records 10136 differing address/size/byte entries, with the full inventory compressed alongside it. Many differences are placement/relocations, not 10136 rewritten algorithms.

`src/base/exbatch_control.h` emits compiler-visible asm-goto edges, initially five-byte NOPs, and a **non-allocated** `.exbatch_pad` record section. The full PAD replaces exactly 52 NOPs with equal-width rel32 jumps: 2 publication, 34 predicates, 6 metadata, 10 cache-update sites across both namespaces. The compiler establishes the register, stack, and exception contracts of the old targets. There is no guessed branch into a separately compiled function body. No per-request table lookup or allocation is added.

[pad-a/proof.json](docs/exbatch/pad-a/proof.json) proves equal entry point, mappings, sections, all symbols, all function addresses and sizes, and **every byte outside the frozen five-byte patch list**. Full function-table SHA256 is `e122e3d982b21c779c25f14ba0ee91405ea2981ebca5a801a5f5bc87d1088759` for POST and every PAD. Complete tables are the `.tsv.gz` files, hashed as decompressed TSV bytes. Partial-arm proofs and three verifier negatives each are under `ex1-old/`, `ex3-old/`, `ex6-old/`; unit-arm identities are under `unit-controls/`.

This is a behaviour twin, not a claim that PRE machine instructions run at PRE addresses. POST's route packing, outlining, register allocation, retained blocks, and five-byte control transfers remain potential costs. In particular, a patched PAD jump and a POST NOP have different execution costs. PRE→PAD measures layout/control overhead together; POST→PAD isolates candidate paths at fixed layout with that transfer caveat. PRE→POST and all-cell no-regression are still mandatory. No PAD-B is supplied; the exact kind-A comparison is the primary control for the 1680-byte growth.

Offline reproduction, with no server execution:

```sh
taskset -c 112-127 make -j16 all build/exbatch-unit build/exbatch-db0-unit build/exbatch/PRE/unit
taskset -c 112-127 python3 tests/exbatch_checks.py publication
taskset -c 112-127 python3 tests/exbatch_checks.py watch
taskset -c 112-127 python3 tests/exbatch_checks.py metadata
taskset -c 112-127 python3 tools/exbatch_source_proof.py --pre-unit build/exbatch/PRE/unit --post-unit build/exbatch-unit
taskset -c 112-127 python3 tools/exbatch_artifacts.py pad build/exbatch/POST/tomokv build/exbatch/PAD-A/tomokv docs/exbatch/pad-a --group all
```

The PRE unit target requires the archived source/objects already present here; it is not an ordinary gate dependency. Rebuild all PADs and refresh hashes if any production object changes. Gate unit controls are regenerated when their input binary or verifier changes.

**Mainline measurement request**

The request is **38 named cells**: the unchanged 14 generic cells, 9 generic supplements, and 15 directed cells. [generic-plus-cells.txt](docs/exbatch/generic-plus-cells.txt) is parseable by the gate ABBA instrument and contains the first 23. [measurement-cells.json](docs/exbatch/measurement-cells.json) gives explicit server argv, all eight memtier argv arrays, key ranges, warm commands, and observer settings for the remaining 15. It is a request document; it executes nothing. The current stock ABBA workload parser accepts the generic 23; the directed arbitrary-command recipes need mainline's instrument adapter with equivalent accounting and PMU boundaries.

Freeze the instrument and SHA-bound PRE/PAD-A/POST arms. For each cell collect PRE/POST, PRE/PAD-A, and PAD-A/POST ABBA blocks using the gate's 20-second central window, 3-second warmup, 5-second tail, identical startup allowance, quiet-box guard, calibration, workload accounting, and recorded cell band. No other lane runs during these measurements. Use the existing valid band for each canonical cell; establish same-binary nulls for new workloads/geometries before inspecting candidate results. Do not widen a band to accommodate a candidate loss.

The three execution regimes are **1s/read-local=0**, **1s/read-local=1**, and **2s/read-local=0**. Existing correctness coverage and the new live row also exercise 2s/read-local=1. The canonical 14 list is all 1s and contains MGET but no MSET; the supplements explicitly close those gaps rather than claiming the list already contains them.

| Canonical IDs | Workload | Instances / connections |
| --- | --- | --- |
| h05, h06 | GET, SET p32; read-local=0 | 8 / 512 |
| p8g, p8s | GET, SET p8; read-local=0 | 8 / 512 |
| d1g_l0, d1s_l0 | GET, SET p1; latency score | Existing exemption: 4 / 512 |
| m8g_l0 | 8-key MGET p8 | 8 / 512 |
| v1g_l0 | GET 1024-byte value p32 | 8 / 512 |
| d128g_l0 | GET p128 | 8 / 512 |
| d32g_l1, d8s_l1, d32s_l1 | Read-local GET p32, SET p8, SET p32 | 8 / 512 |
| x9_32_l1, x9_32_l0 | GET:SET 9:1 p32, read-local on/off | 8 / 512 |

Canonical source is `docs/rlfence2/generic-merit-cells.txt`, SHA256 `de0e56e4696f780543c5adea21aa7d7283c12fa22110be6064370a69a2a68dc6`. Preserve the gate geometry: server 0–31, generators 32–111, no SMT, 2M keys, 64-byte values except v1g, uring, atomic=1, overlap=1, reorder=0, key/client balancing on, empty save, AOF off. Fused has 256 shards. Split supplements use the recorded 16:16 ratio and 128 shards; flip is off. The gate calculates each instance's thread/client split while preserving 512 connections.

The nine supplement IDs encode their parameters: `exbatch_2s_rl0_{g32,s32,g8,s8,mg8,ms8}`, `exbatch_1s_rl0_ms8`, and `exbatch_1s_rl1_{mg8,ms8}`. All have 8 instances/512 connections. MGET/MSET use eight independent `__key__` placeholders, ratio 1, and `--command-key-pattern=P`; MSET pairs each with `__data__`. No `--transaction` on multi-key cells. GET/SET use the instrument's native ratios 0:1 / 1:0 and key pattern P:P. One MGET/MSET is one op, not eight.

Directed cells use gate-sized geometry to expose owner costs. For each base ID below, run suffixes `f0`, `f1`, `s0` for the three regimes. Server cores **0–7**, **16 shards**, port **18179**, 2s ratio **6:2**; omit ratio for 1s. Exact common server arguments:

```text
--bind 127.0.0.1 --port 18179 --net-io uring --shards 16
--atomic 1 --overlap 1 --reorder 0 --key-lb 1 --client-lb 1 --flip-auto 0
--save '' --appendonly no --enable-debug-command yes --databases 1
--thread-mode {1s|2s} --read-local {0|1} --dir {fresh RUN_DIR}
```

Each of the **8 instances** has **8 threads × 8 clients = 64 connections**, hence **512** workload connections total. Instance i (0…7) is pinned to cores `8+13i` through `20+13i`. Common memtier options:

```text
/usr/bin/memtier_benchmark -s 127.0.0.1 -p 18179 --protocol=redis -t 8 -c 8
--key-prefix=exbatch- --key-minimum={lo} --key-maximum={hi} -d 64
--distinct-client-seed --hide-histogram --pipeline=32 --test-time=28
--json-out-file={RUN_DIR}/load-{i}.json
```

All arbitrary commands below have **their own** `--command-ratio=1 --command-key-pattern=P`; never append the native `--key-pattern=P:P` to these argv arrays. The instance ranges partition the specified integer keyspace equally and do not overlap. The P pattern then partitions each instance's range among its clients. Warm every listed physical key to the specified type before measurement; never warm hash/zset/stream keys with SET. Reboot/repopulate identically for each arm.

| Directed base ID | Commands in one ratio-1 rotation | Numeric suffix range / physical keys / warm state |
| --- | --- | --- |
| `exbatch_watch_w32` | `WATCH w:__key__`; `SET plain:__key__ __data__`; `MULTI`; `SET w:__key__ __data__`; `EXEC`; `UNWATCH`. Append `--transaction`. | 1…1,000,000 / 2M keys. Warm `w:exbatch-N` and `plain:exbatch-N` with 64 x bytes. Instance i owns `[125000i+1,125000(i+1)]`. |
| `exbatch_hz32` | `HSET h:__key__ field __data__`; `ZADD z:__key__ 1 member`. HSET:ZADD **1:1**. | 1…1,000,000 / 2M keys. Warm one 64-byte hash field and one fixed sorted-set member at score 1. Bounded replacement/no-growth shape, including same-score ZADD. |
| `exbatch_object32` | `OBJECT ENCODING h:__key__`. | 1…1,000,000 / 1M hashes, each one 64-byte field. Short subcommand name; scan-removal cell without attributing a malloc saving. |
| `exbatch_xgroup32` | `XGROUP CREATECONSUMER s:__key__ g c`. | 1…65536 / 65536 streams; 8192 suffixes per instance. Warm `XADD s:exbatch-N 1-0 f <64 x bytes>`, `XGROUP CREATE s:exbatch-N g 0`, `XGROUP CREATECONSUMER s:exbatch-N g c`. Scored calls return existing-consumer 0, so stream/group/consumer cardinality does not grow. Long-name allocation-removal cell. |
| `exbatch_publish_poll32` | `GET __key__`; independent observer sends `MEMORY STATS` at 100 Hz. | 1…2M / 2M 64-byte strings. Instance i owns `[250000i+1,250000(i+1)]`. Observer uses one persistent connection on CPU 111; instance 7 uses 99–110 instead of 99–111. Keep all 512 workload connections and 8 instances. |

The installed memtier file was only hashed, never executed: SHA256 `9b6ee614dae154c64b17a067a10236b3e6532f7ca52c43b547b87101556dd7d4`. These recipes require the 2.5.1 transaction/key-affix grammar. The upstream [client implementation](https://raw.githubusercontent.com/redis/memtier_benchmark/2.5.1/client.cpp) reuses the generated key within a standalone `--transaction` rotation and applies literal affixes around it. The [CLI source](https://raw.githubusercontent.com/redis/memtier_benchmark/2.5.1/memtier_benchmark.cpp) defines explicit arbitrary-command rotations and per-connection rate limiting. Mainline must freeze the actual executable/version and validate the emitted rotation before scoring; do not silently substitute a loader that advances WATCH and SET to different suffixes.

WATCH's plain SET intentionally uses a different physical key, exercising writes while WATCH remains armed without invalidating its own transaction. With disjoint client ranges, require zero EXEC aborts/errors in the scored workload. Before scoring, on fresh state, prove that a foreign SET to the watched physical key produces a null EXEC and that the nonconflicting six-frame rotation commits. Fail the setup if either witness never opens. A rotation contains **six top-level frames and two successful SETs**, not six transactions. Pipeline=32 counts frames. Account both completed frames and committed EXECs, with bounded start/tail accounting; report cycles/frame and cycles/committed transaction with denominators named. Do not count QUEUED replies as extra completed writes or silently accept aborted transactions as equivalent work.

The polling cell includes the same observer CPU cost, connection, cadence, and replies on every arm. `reply_memory_stats` reads the gauges at `src/cmd/server_tail.cc:476`; MEMORY also uses the metadata resolver, so the EX1-OLD/POST comparison is required to separate publisher cost from observer EX6 savings. Record successful poll count and missed deadlines; fail/recollect a block if the target cadence differs. Exclude observer commands from workload op counts while retaining their server cost in the same PMU numerator across arms. A 100 Hz observer is an explicit coherence stimulus, not a claim about normal INFO frequency. The f1 cell is an expected low-engagement control when reads stay local.

Run the partial kind-A arms on their directed claims: EX1-OLD on GET/SET p32/p8 and polling; EX3-OLD on SET, WATCH, HSET/ZADD; EX6-OLD on OBJECT and XGROUP. Cross-check at fixed POST layout so a gain cannot be assigned to the wrong item. If an item loses, removing it changes the candidate and requires refreshed artifacts and the same no-regression check; no new tuning knob should be shipped to conceal it.

For instruction receipts, first establish sustainable plateaus with the gate's own instrument. Then append the same per-connection `--rate-limiting=q` to all eight instances, where `q=floor(0.8 × min(PRE,PAD-A,POST plateau frames/s) / 512)`. Collect separate matched-rate ABBA windows; verify achieved rates agree within **0.5%**, command mixes/hits/aborts and successful work agree, and record offered plus achieved load. If that check fails, recollect at a common sustainable target; do not compare instr/op from unmatched saturation windows. The 0.5% rule qualifies the instruction receipt, not the regression band. New directed cells require their own frozen null band.

Record total and per-role server cycles, instructions, IPC, completed operations, achieved rate, p50/p99/p999, and workload/engagement evidence. Compute `cycles/op = (instructions/op) / IPC` using the same numerator scope and denominator on each arm. Both halves matter: fewer instructions with worse IPC is not a win. Saturation rate and matched-offered-load latency remain the performance verdict; the matched-rate PMU receipt explains it.

Pass requires the iteration correctness gate with both thread modes, no main command cell worse than its frozen band, and lower matched-rate cycles on any directed regime claimed as a gain. Read-local GET and other unaffected cells must remain flat within their bands. PAD-A should stay near PRE if the observed gain is behavioural; if PAD-A moves similarly to POST, classify the effect as placement/control overhead and do not attribute it to EX1/EX3/EX6. A real loss, an unarmed witness, mismatched work, unsaturated claimed plateau, or invalid PMU window fails the claim. No numerical improvement is asserted until mainline supplies results.

| Requested comparison | Rate / latency | Cycles/op | Instr/op | IPC | Status |
| --- | --- | --- | --- | --- | --- |
| PRE → POST, all 38 cells | PENDING | PENDING | PENDING at matched rate | PENDING | Mainline |
| PRE → PAD-A, all 38 cells | PENDING | PENDING | PENDING at matched rate | PENDING | Layout/control attribution |
| PAD-A → POST, all 38 cells | PENDING | PENDING | PENDING at matched rate | PENDING | Fixed-layout candidate paths |
| Per-item OLD → POST, named directed cells | PENDING | PENDING | PENDING at matched rate | PENDING | Item attribution |

Write the result to `MEASURE-RESULT` in this worktree, including binary/instrument hashes, cell bands, rejected windows, and raw artifact paths. Lane work stops after this report; mainline measures, updates row counts/labels, gates, judges, and merges.

The requested `git diff 12fe9f8ad --stat` is preserved in [diff-from-launch.stat](docs/exbatch/diff-from-launch.stat). It includes the required upstream synchronization. The lane-only comparison against synchronized PRE is [diff-from-pre.stat](docs/exbatch/diff-from-pre.stat). Both include the final report and the two stat files themselves.
