# Dead and Redundant Code Review

## Scope and method

This is a static review only. I did not build the tree, run tests, or start a server. I read `ARCH_BRIEF.md` first and treated its conclusions as premises rather than re-deriving them.

For each reachability claim I checked these supported shapes:

- one execution worker per node: private, DICT-backed keyspace;
- two or more execution workers per node: shared, FLATSTORE-backed keyspace;
- `tomokv-thread-mode static` and `auto`, including the single-node auto remap that can change the effective provisioned worker count after parsing the requested split (`src/server.c:4192-4202`);
- single- and multi-node topology where the code is topology-sensitive.

The storage fork is explicit: `shared_node_dbs` is derived from effective workers per node, and only that arm adds `KVSTORE_FLAT`; the expires kvstore deliberately has the flat flag removed (`src/server.c:4507-4518`). The source also documents the important ex=1 DICT versus ex>=2 FLAT distinction at the prefetch gate (`src/server.h:2222-2231`). Tomo sharding itself is mandatory (`src/server.c:4131-4154`, `src/server.c:4218-4228`), and both supported thread modes set `poly_threads` to one (`src/server.c:4064-4075`).

“No caller/reader” below means an exact-identifier search across the repository found only the cited definition or initialization. That is necessarily a static inference: an exported C symbol could in theory be invoked by a debugger or by code not in this repository. This tree rejects external module loading, so a dynamically loaded module is not a supported counterexample (`src/server.c:4117-4125`, `src/module.c:14572-14577`).

## Summary

| Confidence | Finding | Concrete extent |
|---|---|---:|
| Certain | Auto-mode latency sampler has no consumer | 8,448 write-only ring bytes, 8 bytes per client/fake, two timestamp reads per sampled completion |
| Certain | `poly_threads == 0` execution model is unreachable | 2 dead thread mains (50 lines), 8 wholly dead guards, 3 redundant guard terms |
| Certain | Dynamic module loading implementation sits behind unconditional refusals | at least 112 unreachable lines plus an unusable shipped config |
| Certain | Retired copy-engine residue remains in the reshard state machine | 1 dead enum value, 1 dead timeout arm, 2 copy-era pass-through turns |
| Certain | Retired next-op prefetch body cannot execute | 4-line body; six other width predicates are tautologies |
| Certain | Retired-knob initializer is an unconditional no-op | 0 loop iterations on every boot |
| Certain | Server state contains fields with no reader | 6 fields, including as many as 33 unused heap lists |
| High | Ordinary functions/inlines have no repository caller | 16 symbols |
| Certain | Client-eviction bucket success paths require an unsupported ex=0 regime | 3 substantial true-path bodies |
| Certain | Cluster-positive server hooks require a boot-rejected regime | 6 explicit dead blocks; 4 cluster objects still linked |
| Certain | Bucket hashing is duplicated | 5 spellings of the same hash-and-mask primitive |
| Certain | Migration validation and user documentation describe removed interfaces | 6 guaranteed-stale validations; multiple documented boot failures |

## Findings

### 1. Certain — the auto-mode latency sampler is write-only but still charges dispatch and retirement

`tmIoSignal` contains a 64-entry `lat_ring` and cursor explicitly marked write-only (`src/server.c:157-190`), and 33 signal slots are allocated statically (`src/server.c:197-201`). `tmLatMaybeStamp` increments a TLS counter on every eligible dispatch and takes a monotonic timestamp once every 1,024 dispatches (`src/server.c:454-470`); both the express and general worker routes call it before queueing (`src/server.c:6555-6562`, `src/server.c:6580-6594`). Retirement takes a second timestamp and stores the delta into the ring (`src/server.c:2801-2813`). There is no read of either `lat_ring` or `lat_idx` elsewhere in the repository; the source itself says the sole p99-veto consumer was deleted (`src/server.c:460-466`).

The concrete dead state is 33 × 64 × 4 = **8,448 bytes** of write-only ring storage, plus 33 cursors and the 8-byte `client.tm_lat_stamp` on every real and fake client (`src/server.h:1689-1691`). The runtime cost is one increment/mask/conditional store per eligible dispatched fake in auto mode, plus two `getMonotonicUs()` calls and one ring write per completed 1/1,024 sample (`src/server.c:467-470`, `src/server.c:2807-2813`).

Configuration check: static mode exits before stamping; auto mode pays this in both ex=1/DICT and ex>=2/FLAT because the calls are in the common producer dispatch path, before storage lookup (`src/server.c:6555-6562`, `src/server.c:6580-6594`). Multi-node topology only changes which signal slot owns the write. The result is dead in every configuration; the cost is confined to auto mode.

Removal confidence is lower than deadness confidence: the comment says deleting `tm_lat_stamp` changes a performance-sensitive `client` layout and requires an A/B measurement (`src/server.c:460-466`). The consumer is certainly absent, but deleting the client field should be measured rather than treated as a layout-neutral cleanup.

### 2. Certain — the non-poly execution model can never be selected

Initialization assigns `server.poly_threads = 1` unconditionally for both `static` and `auto` modes (`src/server.c:4064-4075`). Nevertheless:

- `initExThreads` retains an `else` that starts `exThreadMain` (`src/server.c:17255-17301`), while the 29-line legacy main remains defined at `src/server.c:16769-16797`.
- `initIOThreads` retains an `else` that starts `ioThreadMain` (`src/server.c:17391-17415`), while the 21-line legacy main remains defined at `src/server.c:17449-17469`.
- Eight complete `!server.poly_threads` refusal/no-op arms are unreachable (`src/server.c:17803`, `src/server.c:17867`, `src/server.c:18396`, `src/server.c:18580`, `src/server.c:18631`, `src/server.c:18650`, `src/server.c:19325`, `src/server.c:19335`).
- Three compound guards still have other live terms, but their `!server.poly_threads` terms are redundant (`src/server.c:17198`, `src/server.c:18174`, `src/server.c:18845`).

That is **50 lines across two no-longer-callable thread entrypoints**, eight wholly dead guards, and three redundant predicates. The field itself is read often, so this is not a “zero reader” field; it is a constant masquerading as runtime state.

Configuration check: the assignment precedes topology and storage construction, so ex=1/DICT, ex>=2/FLAT, static, auto, single-node, and multi-node all have the same result (`src/server.c:4064-4075`). Static means an inert controller, not the old non-poly execution model.

### 3. Certain — dynamic module loading has at least 112 unreachable implementation lines

Startup exits if the parsed `loadmodule` queue is non-empty (`src/server.c:4117-4125`). Runtime `MODULE LOAD` and `LOADEX` return from a common refusal before command dispatch can reach their old implementations (`src/module.c:14565-14577`), but the old LOAD and LOADEX arms remain immediately below (`src/module.c:14593-14624`).

The unreachable surface is at least:

- 14 lines iterating and loading the startup queue (`src/module.c:13019-13032`); `moduleLoadFromQueue` is called only after `initServer` has already rejected a non-empty queue (`src/server.c:19626-19640`);
- 37 lines parsing LOADEX arguments (`src/module.c:13159-13195`);
- 29 lines implementing `dlopen`/`dlsym` module loading (`src/module.c:13212-13240`);
- 32 lines in the shadowed runtime LOAD/LOADEX arms (`src/module.c:14593-14624`).

Those ranges total **112 lines**. The three callers of `moduleLoad` are the dead startup loop and the two shadowed runtime arms (`src/module.c:13019-13023`, `src/module.c:14602`, `src/module.c:14617-14618`).

This does **not** make the whole module system dead. The default build compiles Vector Sets as an internal module (`src/Makefile:340-343`) and loads it by calling `moduleOnLoad` directly, bypassing `moduleLoad` (`src/module.c:12997-13003`). Consequently, the nearby comment that MODULE LIST is empty because “nothing can be loaded” is false for the default build (`src/module.c:14557-14564`).

Configuration check: module refusal occurs before the DICT/FLATSTORE split, so it applies to ex=1, ex>=2, static, auto, and every topology (`src/server.c:4117-4125`). Internal Vector Sets is the same exception in each configuration; it does not use the dynamic loader.

Concrete shipped failure: `redis-full.conf` contains four active `loadmodule` directives (`redis-full.conf:1-6`), so using that repository-supplied configuration necessarily hits the boot fatal before storage initialization.

### 4. Certain — copy-engine residue remains after cross-node key migration was deleted

`reshardArm` now unconditionally rejects any source/destination pair whose workers do not alias the same physical DB (`src/server.c:10763-10775`). Therefore every successfully armed migration has shared physical storage. Yet the drain-timeout handler still branches on `shared_node_dbs`; its `else` describes copy mode, logs, resets the timeout, and keeps waiting (`src/server.c:11114-11149`). That **9-line else body** (`src/server.c:11140-11149`) is unreachable after any successful arm.

`MIG_CLEANUP` is also a dead enum member. Its declaration explicitly says it is unused and retained only to preserve historical DEBUG phase integers (`src/server.h:2120-2127`), and no expression in the repository stores or compares it. If source compatibility is desired, preserve numeric value 4 as a reserved hole rather than retaining a semantic phase name that no state machine can enter.

Two coordinator states are still live but redundant pass-through scheduling boundaries left by the copy engine:

- after the real drain completes, `CO_WAIT_APPLIED` consumes a separate main-loop turn solely to perform the ownership flip; its former replay wait is gone (`src/server.c:11153-11195`);
- `CO_WAIT_REFS` consumes another turn solely to store `MIG_DONE`; its reference fence and CLEANUP handoff are gone (`src/server.c:11198-11206`).

Collapsing those stores into the preceding state would remove **two event-loop turns per successful cutover**. This is certain as a count, but see the speculative section before changing scheduling boundaries.

Configuration check: in the ex=1/DICT shape, workers have private physical DBs, so a cross-worker arm is rejected by the physical-DB check and none of the coordinator states can be reached (`src/server.c:4507-4537`, `src/server.c:10770-10775`). In ex>=2/FLAT, a same-node arm succeeds because workers alias one node DB; `shared_node_dbs` is necessarily true, so only the timeout-abort arm can run (`src/server.c:4508-4518`, `src/server.c:11117-11139`). Auto mode may remap the effective worker count, but the physical-DB equality check still proves the same dichotomy. Multi-node moves are rejected; same-node moves use shared storage.

### 5. Certain — next-op prefetch is dead in both storage modes; the DICT hash stage is not

The retired setting hardwires `TOMO_PF_W_NEXTOP` to AUTO, whose distance is the current batch occupancy `n` (`src/server.h:2195-2237`). The execution loop computes `la = j + n` while `j` ranges over `[0,n)`, then requires `la < n` (`src/server.c:16539-16560`). The four-line body at `src/server.c:16556-16559` is therefore unreachable for every iteration. A compiler should eliminate it, so this is source residue rather than a measured runtime cost.

Six width predicates are also tautologies because every retired stage width equals `n` and the cursor always indexes `[0,n)` (`src/server.c:15975-15984`, `src/server.c:16027-16045`): the tests at `src/server.c:16052`, `src/server.c:16062`, `src/server.c:16068`, `src/server.c:16075`, `src/server.c:16105`, and `src/server.c:16107` have constant-true width terms. Other terms in the compound predicates remain live.

Mandatory sharding leaves four nearby zero-worker fallbacks dead as well: `calculateKeySlot`'s `: 0` arm (`src/db.c:494-500`), `getKeySlot`'s `ex_threads <= 0` return (`src/db.c:503-507`), the prefetch gate's one-worker fallback divisor (`src/server.c:15923-15927`), and PFS_HASH's legacy `fake->slot` arm (`src/server.c:16086-16092`). Startup has already guaranteed effective `ex_threads >= 1` and assigned `num_workers = ex_threads` before commands run (`src/server.c:4218-4228`, `src/server.c:4427-4432`).

Configuration check:

- ex=1/DICT: `PFS_HASH` can obtain a dict and populate `prefetch_key_hash_valid`, `prefetch_dict`, and `prefetch_bucket_idx` (`src/server.c:16081-16098`), but `la < n` is still false.
- ex>=2/FLAT: the flat keyspace has no populated backing dict for this path, so `PFS_HASH` retires at the null-dict guard (`src/server.c:16086-16092`), and independently `la < n` is still false.
- static/auto and topology do not change the arithmetic.

This distinction matters: deleting `PFS_HASH` as “dead under FLATSTORE” would break the supported ex=1 DICT path. Only the final next-op look-ahead body is dead in all configurations.

### 6. Certain — `tomoInitRetiredKnobDefaults` always performs zero iterations

The function's only data is `static const char *const seeded[] = { NULL }`; its loop condition is false on the first check (`src/config.c:3650-3665`). It is nevertheless called on every configuration initialization (`src/config.c:3667-3684`). The executable behavior is exactly **zero loop iterations per boot**.

The preceding 42-line comment explains historic retirement failures and says the block remains for an invariant (`src/config.c:3607-3649`), but an empty seed list means the current call checks nothing. If the policy documentation is valuable, keep it near the config table or in documentation; the current function adds no runtime or static validation.

Configuration check: this runs before thread topology and storage construction and is identical for ex=1/DICT, ex>=2/FLAT, static, auto, and multi-node.

### 7. Certain — six server fields have no live reader, including recurring unused allocations

A repository-wide exact-identifier scan found:

| Field | Only non-declaration occurrence | Consequence |
|---|---|---|
| `ioThreadsNum` (`src/server.h:2912`) | assigned once (`src/server.c:17331`) | write-only scalar |
| `io_threads_do_reads` (`src/server.h:3215`) | none | declaration-only scalar |
| `pipeline_ring_mask` (`src/server.h:3081-3083`) | derived once (`src/server.c:4276-4280`) | write-only scalar; comments already say it is never read (`src/server.h:1463-1466`) |
| `tm_rebalance_now` (`src/server.h:3019-3020`) | only a stale comment names it (`src/server.c:11949-11955`) | declaration-only scalar |
| `rr_cursor` (`src/server.h:2877-2881`) | reset once (`src/server.c:18631-18640`) | write-only scalar |
| `clients_pending_read` (`src/server.h:3170-3175`) | each producer slot receives `listCreate()` (`src/server.c:4353-4368`) | heap objects with no reader or release |

`clients_pending_read` is the material case. `listCreate` allocates and initializes a six-word `list` (`src/adlist.c:22-33`, `src/adlist.h:27-34`). The initialization loop includes every base and growth producer slot (`src/server.c:4353-4368`); the compile-time IO maximum is 32 (`src/server.h:1470-1472`), so as many as **33 unused lists** are allocated. On an LP64 build, I infer a 48-byte payload per list, or **1,584 bytes** at the maximum, excluding allocator overhead. That byte count is an inference from the cited layout, not a measured `sizeof`.

Configuration check: all six fields are storage-independent. `clients_pending_read` allocations occur for ex=1/DICT and ex>=2/FLAT; static versus auto changes the number of growth slots but never creates a reader. `tm_rebalance_now` was superseded by EWMA transfer and the ordinary balancer path (`src/server.c:11965-11968`, `src/server.c:12254-12269`) in every supported mode.

### 8. High — 16 ordinary functions/inlines have no repository caller

Exact-identifier scanning found only each cited definition, with no call, address-taking expression, prototype use, test use, or registration elsewhere in the repository:

| Symbol | Definition |
|---|---|
| `ACLCountCategoryBitsForSelector` | `src/acl.c:738-750` |
| `addReplyBulkLen` | `src/networking.c:1634-1639` |
| `anetUnixGenericConnect` | `src/anet.c:474-485` |
| `dictCStrHash` | `src/server.c:868-871` |
| `getStringObjectFromListPosition` | `src/t_list.c:1199-1206` |
| `hashSdsFromListpackEntry` | `src/t_hash.c:1830-1833` |
| `hashReplyFromListpackEntry` | `src/t_hash.c:1835-1841` |
| `isModuleConfigNameRegistered` | `src/module.c:13490-13498` |
| `printBits` | `src/bitops.c:669-681` |
| `streamLogListpackContent` | `src/t_stream.c:431-442` |
| `zuiLongLongFromValue` | `src/t_zset.c:2531-2547` |
| `zuiBufferFromValue` | `src/t_zset.c:2579-2589` |
| `connSyncRead` | `src/connection.h:248-254` |
| `rioTell` | `src/rio.h:136-138` |
| `rioGetWriteError` | `src/rio.h:157-160` |
| `rioClearErrors` | `src/rio.h:162-164` |

`printBits` is explicitly retained as a debugger convenience (`src/bitops.c:669-670`), and `streamLogListpackContent` is likewise a development helper (`src/t_stream.c:431-433`). Those are intentionally callable by a developer even though they have no live program caller; classify them as debugger utilities or remove them, rather than pretending they participate in normal execution.

Configuration check: none of these symbols is selected by DICT versus FLATSTORE, thread mode, or topology. This is “no caller in this tree,” not a control-flow proof about hypothetical external code, which is why confidence is High rather than Certain.

### 9. Certain — client-eviction bucket code requires the deleted sharding-off regime

`clientMemBucketsExclusive` returns true only when there is at most one custom IO thread, `num_workers <= 0`, and poly threads are disabled (`src/server.c:1488-1501`). Supported startup guarantees at least one worker (`src/server.c:4137-4154`, `src/server.c:4218-4228`) and forces poly threads on (`src/server.c:4064-4071`). Therefore the predicate is always false.

Three substantial success paths are consequently unreachable:

- the real accounting/bucket body after `updateClientMemUsageAndBucket`'s early return (`src/server.c:1580-1609`);
- the bucket array and per-bucket list allocation (`src/server.c:3365-3386`);
- the client eviction walk after its null/exclusivity guards (`src/networking.c:6120-6137`).

Boot also rejects nonzero `maxmemory-clients` under mandatory sharding (`src/server.c:4461-4480`), and runtime CONFIG SET rejects it when exclusivity is absent (`src/config.c:3125-3137`). The false/no-op guards remain live; the true bodies belong to an ex=0/non-poly regime that this fork explicitly removed.

Configuration check: ex=1 is still `num_workers == 1`, so DICT does not revive the path. Ex>=2/FLAT, static, auto, and every topology also fail the predicate.

### 10. Certain for the hooks, not the whole subsystem — cluster-positive blocks cannot run

`cluster-enabled yes` exits during `initServer` because cluster slot geometry conflicts with mandatory Tomo bucket geometry (`src/server.c:4077-4098`). Six later positive-mode blocks are therefore dead:

1. cluster slot-geometry selection (`src/server.c:4392-4398`);
2. `clusterCommonInit`/`clusterInit` (`src/server.c:19633-19636`);
3. `clusterInitLast` (`src/server.c:19644-19646`);
4. post-load cluster verification (`src/server.c:19660-19662`);
5. cluster cron (`src/server.c:2277-2283`);
6. cluster before-sleep work (`src/server.c:3012-3015`).

The cleanup boundary is large: the server still links four cluster objects (`src/Makefile:383-385`) whose C sources total **12,835 lines** (their final lines are `src/cluster.c:2277`, `src/cluster_legacy.c:6581`, `src/cluster_asm.c:3604`, and `src/cluster_slot_stats.c:373`). The config table still registers **21 `cluster-*` entries**—a repository count of the registrations spanning `cluster-require-full-coverage` through `cluster-link-sendbuf-limit` (`src/config.c:3367-3395`, `src/config.c:3405-3408`, `src/config.c:3443-3495`, `src/config.c:3531`).

Configuration check: the fatal occurs before the ex=1/DICT versus ex>=2/FLAT storage split, so every supported topology and thread mode makes those six positive-mode blocks unreachable.

I am **not** claiming all 12,835 lines are dead. Hash-slot helpers, disabled-mode error replies, config callbacks, CLI-facing compatibility, and shared utilities still have non-cluster callers. Whole-object removal needs a separate callgraph/pruning pass; only the cited `cluster_enabled` positive hooks are proven dead here.

### 11. Certain — the key-to-bucket primitive is duplicated five times

The canonical exported helper is `tomoKeyBucket`, which computes `xxh64(key,len) & TOMO_BUCKET_MASK` (`src/server.c:7345-7349`). The same primitive is independently spelled in:

1. `exIndexForKey`, before its table lookup (`src/server.c:7338-7343`);
2. `tomoBktBucket` (`src/server.c:7384-7388`);
3. `migKeyBucket` (`src/server.c:10709-10713`);
4. DEBUG RESHARD FIND (`src/server.c:12364-12371`).

That is **five implementations** of the same hash-and-mask rule. All live consumers are in `server.c` except the existing exported users in `db.c` (`src/db.c:494-500`, `src/db.c:503-516`), so the local wrappers and direct expressions can call `tomoKeyBucket`; `exIndexForKey` can index the ownership table with its result. There is no present semantic divergence, but any future hash or bucket-width change currently has five synchronization points.

Configuration check: the bucket ID is the common routing currency in both DICT and FLATSTORE. This duplication is live in both storage modes and independent of static/auto or topology; it is redundant logic, not dead logic.

## Stale comments, documentation, configurations, and validations

### A. Certain — six migration validations poll copy-engine fields that STATUS no longer emits

Current `DEBUG RESHARD STATUS` emits only `active`, `phase`, `lo`, `hi`, `src`, and `dst`, and explicitly says `issued`, `applied`, `scan_done`, checksums, and `converged` were removed with the copy engine (`src/server.c:12372-12382`).

Six validation programs still wait for or assert removed fields:

- `harness/mig/mig_ringwrap_test.sh:34-51`;
- `harness/mig/reshard_arm_validation.sh:56-72`;
- `harness/mig/xshard_mig_test.sh:93-109`;
- `harness/mig/xshard_migsafe_gather_test.sh:36`;
- `harness/mig/xshard_migsafe_test.sh:38`;
- `harness/validation/cmd_pre_post_migration.py:126-128`.

These are not merely stale descriptions: their polling predicates can never become true. For example, ringwrap performs up to **600 half-second polls** for `scan_done` and then requires `issued > 65536` and `converged=1` (`harness/mig/mig_ringwrap_test.sh:34-51`). It is a validation of a deleted 64K effect-log wrap bug, not of the current ownership-flip engine (`harness/mig/mig_ringwrap_test.sh:2-7`).

Three shell tests also boot with the retired, unaliased `--tomokv-reshard-min-ops` name (`harness/mig/xshard_mig_test.sh:20-22`, `harness/mig/xshard_migsafe_gather_test.sh:13`, `harness/mig/xshard_migsafe_test.sh:15`); the current knob is `tomokv-key-lb` (`src/config.c:3294`). The unresolved-config path aborts startup when no module claims such a name (`src/module.c:13033-13044`), so those tests fail before reaching their stale polls unless the obsolete argument is removed.

Configuration check: the missing STATUS fields are independent of storage shape. Ex=1 cannot arm a cross-worker migration after the copy-engine deletion; ex>=2 can arm the ownership flip but emits the same six-field STATUS. Static/auto affects who initiates a move, not the response schema.

### B. Certain — active README instructions contradict the current config surface

README itself admits seven retired names “do not exist in `config.c` and will not boot” (`README.md:345-348`), but active sections still:

- advertise `tomokv-ex-queue-depth` in the threading table (`README.md:306-318`);
- advertise `tomokv-num-cdb` and the deleted operand pool (`README.md:396-403`);
- give a run command containing `--tomokv-ex-queue-depth 2048` (`README.md:413-426`);
- name the deleted `tomokv-xshard-guard` as the SAFE-GATE control (`README.md:433-443`).

The documented run command is therefore a concrete boot failure, not cosmetic terminology. The current source derives queue depth internally (`src/server.c:4270-4280`), derives common-data-bus count from L3 topology (`src/server.c:4488-4495`), and says the xshard knob fields were deleted and the behavior made unconditional (`src/server.h:3811-3813`).

README also says multi-key SCAN is outside scope (`README.md:439-440`), while top-level SCAN is explicitly dispatched to a worker in the shared-FLAT shape (`src/server.c:6668-6672`) and uses `flatScanDbs` (`src/db.c:2155-2181`). The statement remains true for ex=1/DICT, where SCAN keeps the inline handling, but it is false as a blanket description of ex>=2.

### C. Certain — README-NUMA describes an old opt-in FLATSTORE implementation

README-NUMA labels FLATSTORE “Stage 0, opt-in (default off),” says it has no online resize, says delete leaks, and calls the dict store the default (`README-NUMA.md:94-112`). Current code says FLATSTORE is unconditional for shared node DBs (`src/server.h:3027-3029`), enables it whenever effective workers-per-node exceeds one (`src/server.c:4507-4518`), and runs reclaim plus resize coordination from the main loop (`src/server.c:2980-2986`). The same document says an old copy engine is merely “bypassed in shared mode” (`README-NUMA.md:126-144`), but the current arm rejects the only regime that required copying (`src/server.c:10763-10775`).

Configuration check: the old “dict default” happens to describe the ex=1 DICT shape, but the document presents FLATSTORE as an operator toggle for the multi-worker NUMA design. That toggle and its opt-in/leaking implementation no longer exist for ex>=2.

### D. Certain — source comments still describe deleted migration, expiry, and threading behavior

At least five migration comments are materially false:

- the drain hold says it waits for `issued_seq` and prevents late log replay (`src/server.c:10814-10817`);
- lazy-expiry suppression says active expiry walks the empty decoy, B owns another copy, and A's copy dies in CLEANUP (`src/server.c:10945-10951`);
- the revived worker is said to have drained an effect log (`src/server.c:11178-11183`);
- the grow-front tail says CLEANUP deleted source copies (`src/server.c:11251-11254`);
- `reshardBeginCutover` is introduced as spawning a detached coordinator that waits for cold-copy convergence (`src/server.c:11269-11276`).

The current design says no key copy, effect log, or CLEANUP exists (`src/server.c:10695-10707`), and the coordinator is a main-thread tick state machine (`src/server.c:10965-10975`). Worker active expiry is live in `exSlice` (`src/server.c:16434-16466`) and walks each worker's own buckets (`src/expire.c:166-171`, `src/expire.c:231-235`).

A separate whitelist comment still says TTL commands are excluded because expiration cron walks only `server.db` (`src/server.c:6649-6655`). Whatever the current routing decision for those commands, that stated reason is obsolete in both DICT and FLATSTORE because worker-owned active expiry is now implemented.

Two comments also say upstream `io-threads` is parse-only/inert, `server.io_threads_num` is never read, and the stock threads were removed (`src/server.h:1440-1446`, `src/config.c:3451-3454`). In fact `InitServerLast` still calls `initThreadedIO` (`src/server.c:4731-4739`), and any configured value greater than one enters a loop that allocates and creates stock IO threads (`src/iothread.c:868-920`). Thus `io-threads 2` concretely creates **one additional stock IO thread** alongside the custom Tomo pool; the code is live and the comments are false.

### E. High — preflight design documents still prescribe deleted knobs and pools

The feature-sweep README lists old cells for `tomokv-flat-store`, `mcmd-lock`, `xshard-guard`, `xshard-pipeline`, `express-slim`, `num-cdb`, operand pool, the retired prefetch widths, and other retired controls (`tools/preflight/feature_sweep_README.md:112-125`). The controller-sweep README still budgets and tests an `OPERAND_POOL_CAP 256` pool (`tools/preflight/controller_sweep.README.md:152-163`, `tools/preflight/controller_sweep.README.md:243-248`), although the sizing policy later says that pool was deleted (`docs/sizing-policy.md:160-171`). The same sizing document still lists `OPERAND_POOL_CAP` in its earlier “current state” table (`docs/sizing-policy.md:52-59`).

These are documentation files rather than executed tests, so the concrete failure is procedural: following them produces cells for absent configuration names and a memory envelope for a nonexistent pool. They should be marked historical or regenerated from the live config table.

Configuration check: the stale names are absent regardless of DICT/FLATSTORE or thread mode. Some described mechanisms remain live but unconditional; that is precisely why the old toggle matrix is misleading.

## Speculative or change-risk items

These did not meet the same “safe, all-config dead” bar and should not be promoted into deletion work without an explicit decision.

1. **`RM_Scan`/`dbScan` appear dead in the current supported module set, but are an internal-module ABI.** `RM_Scan`'s only direct call is to `dbScan` (`src/module.c:11871-11884`), and `dbScan` exists specifically for that API (`src/db.c:3418-3445`). External modules cannot load, and repository search found no Vector Sets call to the scan API; however, core module APIs are registered by function pointer (`src/module.c:12869-12875`) and a future built-in module could use it. I would remove these two only if “supported internal modules” is deliberately frozen to the current set.

2. **Merging `CO_WAIT_APPLIED` and `CO_WAIT_REFS` is logically redundant, but may alter intentional yielding.** The old waits are gone and the states only perform flip/DONE work (`src/server.c:11153-11206`), so they add two event-loop turns. I found no comment requiring those yields. Still, changing cutover scheduling is more than dead-symbol deletion and deserves a focused concurrency review.

3. **The cluster source files are not proven wholly dead.** Cluster-enabled startup, cron, and before-sleep paths are impossible (`src/server.c:4077-4098`, `src/server.c:2277-2283`, `src/server.c:3012-3015`), but the linked objects contain compatibility/error/helper code with non-cluster callers (`src/Makefile:383-385`). The 12,835-line total is a cleanup boundary, not a proposed deletion count.

4. **The README's 3-Stage/WB-thread family entry may describe a different edition rather than this tree.** It clearly labels this tree 2-Stage and describes 3-Stage as another family member (`README.md:447-455`). No WB-thread mode is present here, but I cannot prove from this repository alone that the other edition no longer exists. I therefore did not count that passage as a stale current-behavior claim.

5. **Debugger-only helpers are not live production code, but may be intentionally retained.** `printBits` and `streamLogListpackContent` have no repository callers and say they are for debugging (`src/bitops.c:669-681`, `src/t_stream.c:431-442`). Removing them is safe for the program callgraph but removes ad-hoc debugger convenience.

## Explicitly not classified as dead

- The DICT-backed `PFS_HASH` path at one worker per node is live and populates the carried hash/dict/index state (`src/server.c:16081-16098`). It is only inert under shared FLATSTORE.
- Top-level SCAN has a live FLATSTORE implementation at ex>=2 (`src/server.c:6668-6672`, `src/db.c:2155-2181`); the ex=1 inline behavior must be evaluated separately.
- The expires kvstore is DICT-backed in both keyspace modes by design (`src/server.c:4517-4518`); code using expires dictionaries is not dead merely because the keyspace kvstore is flat.
- `MIG_COPYING` is still the live armed/pre-cutover phase even though no copying occurs: arm stores it and cutover requires it (`src/server.c:10778-10793`, `src/server.c:11271-11276`). Its name is stale, not its state.
- The module core/API is not globally dead because the default build loads internal Vector Sets through `moduleOnLoad` (`src/Makefile:340-343`, `src/module.c:12997-13003`). Only the dynamic loading routes are proven unreachable.
- Stock `iothread.c` is not dead: `io-threads > 1` still reaches `initThreadedIO` and spawns those threads (`src/server.c:4731-4739`, `src/iothread.c:868-920`), despite comments claiming otherwise.
