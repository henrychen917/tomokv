# Cross-shard scatter-gather (MGET/MSET/set-ops, cross-node)

This is an inventory of the current in-process cross-shard implementation for `MGET`, `MSET`, set algebra, and `RENAME`. (`src/server.c:10784-10816`) The data path hands work from an IO thread to owner-worker queues. (`src/server.c:12544-12586`)

The spanning-worker path is pure scatter-gather: every key is hashed, resolved through `server.ex_bucket_table`, placed in a sub bound to `server.exThreads[w].db[dbid]`, and pushed to worker `w`; that worker takes its own worker lock before calling `csSubExec`. (`src/server.c:12648-12705`, `src/server.c:22144-22170`) The active dispatch and execution chain contains no branch that reads a sub's keys through a different worker. (`src/server.c:12648-12705`, `src/server.c:22165-22170`)

Cross-node placement does not select a different execution protocol: `csPushSpin` still publishes the selected worker's queue. (`src/server.c:12552-12586`) The exact prefetch-only branch is `server.prefetch_io_level == 2 && tomoCrossNode(iotid,w) && sub->csparent`; it then requires `head && head->parent && head->parent->has_exec_tail` before OR-ing `1u << head->fake_slot` into `clientTail(head->parent)->prefetch_io_xnode_slots`. (`src/server.c:12544-12551`) `tomoCrossNode` itself acquire-loads `cross_node_any[io_slot]`, returns zero when it is clear, otherwise relaxed-loads the worker's bit-table word and extracts the worker bit. (`src/server.c:163-176`)

## Entry and route selection

The command table stores a `csCmdSpec *` and derives `TOMO_R_CROSS` only for a registry row whose `ported` value is `CS_PORT_OK`; `csClassify` then checks that row's argument-count, `numkeys`, and optional shape predicates for the current invocation. (`src/server.c:11052-11073`, `src/server.c:11161-11179`)

The `tomokv-atomic` configuration defaults to false; its enabled branch is therefore called out separately below wherever it changes MSET or RENAME semantics. (`src/config.c:3182-3184`, `src/server.h:4114-4115`)

The relevant registry rows are `MGET` as `CS_RT_GATHER` with coalescing gated at three keys, `MSET` as `CS_RT_GATHER` with key stride two and unconditional coalescing, `SINTER`/`SUNION`/`SDIFF` as gather rows tagged with their reduction kind, and `RENAME` as `CS_RT_TWOHOP`. (`src/server.c:10784-10816`)

There are no executable functions named `csScatter` or `csGather` in this worktree; the active route is `csClassify` to `csDispatch`, then `dispatchGather`, `dispatchTwoHop`, or `dispatchFanAll`. (`src/server.c:11161-11179`, `src/server.c:13742-13755`, `src/server.c:14368-14375`)

After the real client's execution state is moved into its pipeline-ring fake, a classified cross-shard command drains that connection's staged reorder work, increments `replyWorking`, and calls `csDispatch`; the route switch selects fan-all, two-hop, or gather dispatch from `csCmdSpec.route`. (`src/server.c:8423-8450`, `src/server.c:8565-8590`, `src/server.c:13742-13748`)

When the exact predicate `!s->cs_write && !s->has_hop2 && !atomic_snapshot && nkeys >= 1` holds, `dispatchGather` first resolves every key; if all keys have one owner it sends one full-argv `CS_LOCAL` sub that runs the stock command, while keys spanning more than one owner continue to the scatter or reduction pipeline. (`src/server.c:13490-13509`, `src/server.c:13523-13587`)

## Data structures

### Command description

`csCmdSpec` carries the executable routing description: `ctype` and `route`; classification gates; gather geometry (`firstkey_argi`, `numkeys_argi`, `nkeys_fixed`, `key_stride`, `per_key_extra`, and `gather_geom`); result and position-map selectors; the coalescing gate; HOP2 source/destination geometry and flags; and callbacks such as `append_extra`. (`src/server.h:4424-4479`)

### Head, sub-fakes, and group

The ring fake that represents the client command is the **group head**: `head->csgroup` points to its `csGroup`, `g->head` points back to the head, and the head's completion byte uses CDB zero on gather, pipeline, and two-hop groups. (`src/server.c:12945-12952`, `src/server.c:13629-13635`, `src/server.c:14405-14411`)

Each worker job is a pooled **sub-fake**: `sub->csparent` points to the group, `clientTail(sub)->cssub_idx` identifies its result/plan slot, `sub->cmd` retains the original command, and `sub->db` is the selected owner worker's database. (`src/server.c:12803-12814`)

The `client` execution core contains both relationship pointers—`csgroup` for a head and `csparent` for a sub—alongside the command, argv, reply buffers, key-hash cache, and snapshot fields that the handoff uses. (`src/server.h:1877-1913`)

The `csGroup` fields used by these protocols are declared together in `server.h`. (`src/server.h:2108-2277`)

| Field group | Implemented contents |
| --- | --- |
| Completion and identity | `pending`, `nsub`, `ctype`, `nkeys`, `subs`, and `head` describe the current worker wave and its ring head. (`src/server.h:2108-2115`) |
| Scalar and gathered results | `rcount` accumulates counts; `err` carries command errors; `mget_vals` and `mget_pos` carry position-indexed MGET copies; `setmem` and `setcnt` carry member-gather results, while `setop_pos` maps sub-local keys to original set-op positions for coalesced gather or the initial pipeline wave. (`src/server.h:2155-2176`, `src/server.c:12997-13003`) |
| Two-hop state | `phase`, `has_hop2`, `h2_op`, `spec`, `h2sub`, `h2_nsub`, `h2_dbid`, `h2_flags`, `h2_payload`, `h2_pexpireat`, and `cs2_kind` retain the next-wave plan and its private serialized value. (`src/server.h:2189-2202`) |
| Set-reduction pipeline | `pipe_stage`, `pipe_next`, `pipe_nshard`, `pipe_scard`, `pipe_order`, `pipe_cand`, `pipe_ncand`, `pipe_verdict`, `pipe_shard_of`, `pipe_smallest`, `pipe_cscore`, `pipe_probe_pos`, `pipe_probe_nk`, `pipe_npart`, `pipe_base_part`, `pipe_part`, `pipe_partcnt`, `pipe_partscore`, `pipe_midx`, `pipe_zraw`, `pipe_key_part`, and `cs2_intreply` carry the multi-stage INTER and local UNION/DIFF reductions. (`src/server.h:2203-2241`) |
| Atomic-write state | `version_seq`, `read_seq`, `commit_next`, `mset_client`, `mset_pending_prev`, `mset_pending_next`, `mset_complete`, `mset_install_count`, `mset_installs`, `mset_install_order_base`, `versioned_write`, `version_install_expected`, `version_commit_ready`, `version_abort`, `version_nx`, `version_nx_reserving`, `msetnx_retry`, `msetnx_state`, and `snapshot_pinned` carry a registered versioned write to publication. The `_atomic_probe_retired_*` words are zeroed layout reserves, not membership state. (`src/server.h`) |
| Accounting and allocation | Atomic `usec` and `had_err` accumulate sub work; `inl_cap`, `inl_used`, and flexible `inl[]` form the group's inline bump region. (`src/server.h:2244-2277`) |

`csGroupNew` allocates and zeroes the header plus an eight-byte-aligned inline region capped at 512 bytes; `csgAlloc` advances the monotone inline cursor and spills to `zmalloc`, while `csgFree` ignores inline addresses and frees only spills. (`src/server.c:12418-12425`, `src/server.c:12465-12492`, `src/server.h:2278-2283`)

`csH2Sub` is the two-field HOP2 plan element: `action` selects `CS_H2A_WRITE` or `CS_H2A_SRCOP`, and signed 32-bit `key_argi` selects the head argv key. (`src/server.h:2037-2040`, `src/server.h:2094-2100`) `csMsetInstall` is the three-field atomic-install record: `kv` is the exact installed store object, `owner` is the worker that applies its embedded operations, and `install_order` is the per-key duplicate-key tie break. (`src/server.h:2102-2106`)

The former publishing-ring pointer slot remains as an always-NULL layout reserve so `tomokv-atomic no` retains the same client/cache geometry. No publishing ring is allocated. (`src/server.h`, `src/networking.c`)

The adjacent `nsub` comment says “number of sub-fakes = nkeys,” but that is a legacy-shape description rather than a group invariant: the legacy arm sets `nsub=nkeys`, while the coalesced builder assigns the number of distinct workers with at least one key. (`src/server.h:2108-2113`, `src/server.c:12669-12674`, `src/server.c:13707-13722`)

## Common scatter/gather protocol

1. `dispatchGather` derives `first`, `nkeys`, and the DB from the registry geometry, computes the `atomic_write`, `atomic_bag`, `atomic_snapshot`, and `atomic_msetnx` flags, and selects local-fast, the set-reduction pipeline, the legacy per-key arm, or the coalesced builder. (`src/server.c:13511-13530`, `src/server.c:13588-13617`)

2. The legacy arm creates `nkeys` sub-fakes, each with `[CMD,key]`, stores `pending=nkeys` relaxed before pushing, and routes every sub with `exIndexForKey`. (`src/server.c:13707-13722`) This remains the spanning-worker path for a two-key `MGET`; although the registry also retains a three-key set-op coalescing threshold, the live `nkeys >= 2` set-algebra predicate intercepts those commands into `dispatchPipeline` before this arm. (`src/server.c:13588-13617`)

3. The coalesced builder hashes every key, reads its current owner from `server.ex_bucket_table[h & TOMO_BUCKET_MASK]`, counts keys per worker, and creates one sub per distinct worker—not one fake per key. (`src/server.c:12623-12695`) A sub argv is `[CMD,k,...]`, or `[CMD,k,v,...]` when the row supplies an extra value, and an optional per-sub position list maps each local argv key back to its original index. (`src/server.c:12689-12701`)

4. `g->pending` is initialized with a relaxed store before any sub is published. (`src/server.c:12669-12705`) `csPushSpin` retries a full queue while publishing staged tails, and after a successful push it release-stores the queue tail and advertises that worker. (`src/server.c:12544-12586`)

5. The worker locks `worker->id`, runs `csSubExec`, and unlocks. (`src/server.c:22144-22170`) A multi-sub wave decrements `pending` with `memory_order_acq_rel`; a singleton wave uses a relaxed zero store because it has no sibling writer. (`src/server.c:22171-22178`)

6. For a non-versioned wave, the last sub release-publishes the head's CDB ready byte. (`src/server.c:22196-22199`, `src/server.c:3162-3164`) For a versioned final wave, the last sub calls `csMsetInstallDone` instead; versioned intermediate stages merely publish readiness so the IO drain can launch the next stage. (`src/server.c:22179-22195`)

7. CDB publication is a release store and the IO drain polls it with an acquire load; the drain and drain-launched continuations clear it with a relaxed store before retirement or re-arm. (`src/server.c:3158-3168`, `src/server.c:4200-4204`, `src/server.c:4320-4337`, `src/server.c:14550-14561`) The drain walks ring slots in `flushid` order and stops at the first slot that is not ready. (`src/server.c:4236-4242`)

8. A completed pipeline stage may call `csPipeAdvance`, and a completed HOP1 may call `csLaunchHop2`; either continuation keeps the same ring head in flight and makes the drain stop before retiring later slots. (`src/server.c:4285-4303`) Only a terminal wave reaches `csReassemble`. (`src/server.c:4304-4308`)

9. With non-NULL `dst`, `csReassemble` builds the command's final reply on the real client; with `dst == NULL`, it skips reply emission during disconnect teardown. (`src/server.c:14361-14367`, `src/server.c:14864-14947`) Both forms record the logical command once, release command-specific payloads and every current sub, free spill allocations, free the group last, and clear `head->csgroup`. (`src/server.c:14867-14882`, `src/server.c:15245-15328`)

The older cross-shard overview says the mechanism is “Default OFF” and describes one single-key sub per key. (`src/server.c:10436-10464`) The live dispatch has no such feature-toggle branch: every invocation that `csClassify` accepts calls `csDispatch`, and its coalesced builder uses one sub per distinct worker; only the legacy arm remains one-per-key. (`src/server.c:8565-8590`, `src/server.c:12669-12705`, `src/server.c:13707-13722`)

## Command protocols

### MGET

The current cross-worker MGET has two physical forms: two keys use one `[CMD,key]` sub per key, while three or more keys use one sub per distinct worker plus `mget_pos`; same-owner, non-snapshot reads take the single-sub local-fast path before either form. (`src/server.c:10786-10788`, `src/server.c:13531-13587`, `src/server.c:13601-13617`)

On the coalesced path, each owner worker looks up all of its keys and writes a private `sds` copy into `mget_vals[original_position]`; missing and non-string keys leave a null slot. (`src/server.c:11625-11647`, `src/server.c:11653-11660`) On the legacy path, the one-key sub serializes its bulk-or-null element into its own reply buffer. (`src/server.c:11648-11652`, `src/server.c:11661-11665`)

Reassembly emits one array of `nkeys`; it consumes `mget_vals` in original key order when coalesced or splices the legacy sub buffers in sub/original-key order. (`src/server.c:14949-14961`)

The nearby legacy-MGET comment calls that arm the “knob off” path, but no coalescing knob participates in the branch: its live condition is `nkeys < 3`. (`src/server.h:2166-2175`, `src/server.c:13601-13617`)

### MSET and `csMsetInstallDone`

MSET is always coalesced by owner with stride two. (`src/server.c:10789-10791`, `src/server.c:13601-13617`) `csAppendMsetValue` gives each sub a private refcount-one value copy, and worker execution applies every local pair; after ownership transfers into the database, the worker nulls that argv value so IO-thread sub cleanup cannot decrement the stored object. (`src/server.c:12608-12613`, `src/server.c:11542-11600`, `src/server.c:11682-11759`)

Without atomic admission, workers apply their shards independently, the ordinary pending barrier publishes completion after all subs finish, and reassembly returns `+OK`. (`src/server.c:11706-11759`, `src/server.c:22171-22199`, `src/server.c:14963-14965`) The code does not add a cross-worker commit phase in this branch. (`src/server.c:11706-11759`, `src/server.c:22196-22199`)

Consequently, the non-atomic branch is not a cross-worker transaction: owner writes occur before the completion barrier, so another client can observe a partially applied MSET even though the issuing client receives `+OK` only after every sub completes. (`src/server.c:11706-11759`, `src/server.c:22171-22199`, `src/server.c:14963-14965`) This is an inference from the worker apply loop and the absence of a commit-publication branch before the ordinary pending barrier. (`src/server.c:11706-11759`, `src/server.c:22196-22199`)

With atomic admission, dispatch allocates one `csMsetInstall` per key, calls `csMsetRegister` before the coalesced routing pass's first owner-queue publication, and changes the worker case to `setKeyVersioned` plus `csMsetRecordInstall`. No written-key membership structure is built. (`src/server.c`)

`csMsetRegister` marks the group versioned and uncommitted, binds it to the real client, reserves a connection-global install-order range under `mset_pending_lock`, appends it to that connection's pending FIFO, and release-increments `mset_pending_count`. (`src/server.c:9914-9957`)

The final worker wave calls `csMsetInstallDone`, which release-stores `mset_complete`; an acquire CAS on the connection's `mset_drain_latch` permits one ready-stack entry, and an acquire CAS on the global drain-active word elects one sequencer. A losing completion worker returns to its EX slice. (`src/server.c`)

The sequencer pops only completed FIFO heads with an acquire read of `mset_complete`, allocates a sequence with a relaxed `next_seq` fetch-add for a non-canceled group, release-stores `version_canceled` and `owner_ops_pending`, fills the embedded owner operations, pushes each STAMP or CANCEL job, and appends the group to a sequencer-local per-client publish prefix. (`src/server.c`)

The same unique sequencer drains that prefix: it release-stores `commit_seq` for a non-canceled group, pushes PRUNE jobs, seals the group's atomic lifecycle, release-publishes the head ready byte, release-decrements the connection's pending count, and wakes the producer IO thread once for the prefix. (`src/server.c`)

Thus the generic “last sub signals the head” comment is not the complete atomic behavior: the executable versioned branch delays terminal head publication until `csMsetInstallDone` has performed the commit-publication sequence. (`src/server.h:1991-1995`, `src/server.c:22179-22199`, `src/server.c:10363-10413`)

### Set operations

For two or more source keys, `CS_SETOP`, `CS_SSTORE`, and `CS_SETCARD` enter `dispatchPipeline` (and the same predicate includes the corresponding sorted-set families); a single-input form can still use local-fast or the simpler gather path. (`src/server.c:13588-13600`)

`dispatchPipeline` records each key's owner, sets `cs_barrier`, selects `CS_PIPE_SIZES` for INTER, `CS_PIPE_LOCAL_UNION` for UNION, or `CS_PIPE_LOCAL_DIFF` for DIFF, and starts one coalesced sub per distinct source worker. (`src/server.c:12938-13003`)

For UNION, each worker builds and exports one distinct local partial. (`src/server.c:13192-13212`, `src/server.c:13240-13258`) For DIFF, the worker that owns original key zero subtracts its local right-hand inputs from that base, while other workers export the union of their local exclusion inputs. (`src/server.c:13214-13258`)

The coordinator materializes UNION by adding every shard partial. (`src/server.c:13943-13948`) It materializes DIFF from the key-zero shard's partial and removes every other shard's partial. (`src/server.c:13949-13959`)

INTER first gathers only per-key sizes, chooses the globally smallest input, orders distinct shard groups by their smallest key size, gathers the smallest input's members as candidates, then sends one probe wave at a time for the other keys grouped by shard and compacts survivors after each completion. (`src/server.c:13269-13342`, `src/server.c:13374-13487`)

The older member-gather reducer remains live for shapes that do not enter the `nkeys >= 2` pipeline, notably a single-source set `*STORE`: an owner copies each source's members into `setmem[original_position]`, missing keys contribute zero members, and a non-set stores WRONGTYPE in `err`. (`src/server.c:11912-11941`) `csSetOpResultSet` then deduplicates UNION, probes all inputs for INTER, or keeps input-zero members absent from later inputs for DIFF; the store launcher serializes that temporary result for HOP2. (`src/server.c:13802-13860`, `src/server.c:14640-14656`)

`csSetOpCompute` and its `CS_SETOP` reassembly call still exist. (`src/server.c:14171-14180`, `src/server.c:15002-15008`) Current classified `CS_SETOP` shapes do not reach them: one source takes owner-local `CS_LOCAL`, while two or more sources are intercepted by `dispatchPipeline`. (`src/server.c:13531-13599`)

The `csGroup` header comment that presents per-key `setmem` gathering and coordinator computation as the set-op design is therefore incomplete for the live multi-source route: classified set operations with at least two inputs use the reduction pipeline above. (`src/server.h:2155-2163`, `src/server.c:13588-13599`)

For read-only `CS_SETOP`, terminal pipeline reassembly emits WRONGTYPE when `err` is set; otherwise it materializes `pipe_cand` or the shard partials and emits the resulting set. (`src/server.c:14883-14945`) A `CS_SSTORE` pipeline instead serializes the reduced set before HOP2, where the destination owner restores it or deletes the destination for an empty result. (`src/server.c:14640-14656`, `src/server.c:11888-11910`)

Every pipeline raises the connection's `cs_barrier` because later stages are launched by the drain thread. (`src/server.c:12965-12977`) `processCommand` stalls subsequent commands from that client until the ring, including the multi-stage group, has retired. (`src/server.c:8283-8303`)

### Two-hop RENAME

RENAME's registry row names source argv 1, destination argv 2, route `CS_RT_TWOHOP`, and a plan-style HOP2. (`src/server.c:10814-10816`) Its one-owner branch requires `!atomic_admission`, `src_shard == dst_shard`, `!s->block_reject`, no COPY DB option, and `!(src_in ^ dst_in)`; for RENAME the last condition means that during an active migration both buckets have the same in-range fate. (`src/server.c:14380-14403`, `src/server.c:14471-14487`) That branch creates one full-argv sub and the owner runs `renameGenericCommand`; otherwise dispatch arms the two-hop group and same-client barrier. (`src/server.c:14497-14512`, `src/server.c:12120-12124`)

For a non-atomic cross-worker RENAME, HOP1 sends `[CMD,src]` to the source owner. (`src/server.c:14509-14547`) That worker looks up the source, stores `CS_ERR_NOKEY` if absent, otherwise serializes its RDB type/object into private `h2_payload`, stores the absolute expiration separately in `h2_pexpireat`, deletes the source, and emits `rename_from`. (`src/server.c:11187-11208`, `src/server.c:12124-12129`)

After the HOP1 ready byte is acquired, the IO drain calls `csLaunchHop2` only when `g->err == CS_ERR_NONE`; the launcher frees HOP1 subs, builds the registry-stamped destination sub, re-resolves its owner after any migration hold, then `csHopCommit` stores the new pending count, sets `CS_PH_HOP2`, clears the stale ready byte, and pushes the new wave in that order. (`src/server.c:4294-4303`, `src/server.c:14550-14581`, `src/server.c:14792-14860`)

The HOP2 destination worker loads the private RDB blob before modifying the destination, overwrites the destination, restores its absolute expiration and auxiliary indexes, emits `rename_to`, and marks the write dirty. (`src/server.c:11243-11274`, `src/server.c:12129-12138`) A blob-load failure sets `CS_ERR_EMPTY` and leaves the destination untouched. (`src/server.c:11275-11279`)

Reassembly returns `no such key` for `CS_ERR_NOKEY`, a generic cross-shard failure for another error, or `+OK` after successful HOP2. (`src/server.c:15010-15016`) If the client disconnects after mutating HOP1, the teardown drain still launches HOP2 before it permits the head to retire. (`src/server.c:4184-4200`)

With atomic admission, HOP1 reads/serializes without deleting, and the HOP2 plan contains both a source-tombstone sub and a destination-value sub. (`src/server.c:14443-14469`, `src/server.c:14514-14519`, `src/server.c:12124-12135`) The launcher marks the versioned wave commit-ready, so its last sub sends the final two installs through `csMsetInstallDone` as one registered group. (`src/server.c:14775-14790`, `src/server.c:22179-22195`, `src/server.c:10336-10413`)

The dispatcher comment that says RENAME HOP1 deletes the source is complete only for the non-atomic branch; the executable atomic branch passes `del=-1` and defers the source tombstone to HOP2. (`src/server.c:14368-14374`, `src/server.c:12124-12135`, `src/server.c:14514-14519`)

## Membership-probe removal

The old own-read HOLD design used one low hash bit per key in a 64-bit signature, with an exact-hash companion and a per-connection publishing ring. At eight keys the signature aliased heavily, creating needless apparent conflicts. After own-read visibility moved to immutable version identity, those structures had no correctness consumer but were still built, copied, and allocated.

The signature, exact vectors, publishing records, and write-side probe machinery are now removed. Routing still computes full key hashes for owner/bucket selection, but it does not derive membership state from them. (`src/server.c`, `src/server.h`)

The live read-your-own-write resolver uses version identity instead of signature disjointness. (`src/server.c:10133-10148`, `src/server.c:10206-10256`) For a real reader it starts with the own-version scan enabled; when `mset_pending_count == 0` in a worker context, it narrows that decision to whether that worker's `stamp_pending` is nonzero, while a non-worker context retains the scan. (`src/server.c:10206-10239`) The scan selects an uncommitted, non-canceled version whose `origin_client_id` equals the real client's ID, and the committed-chain walk accepts the first version at or below the snapshot or the first version from that same client ID. (`src/server.c:10133-10148`, `src/server.c:10242-10256`)

For a qualifying atomic cross-shard read, dispatch calls `flatGroupPinEnter(fake)` and acquire-loads `commit_seq` into `fake->tomo_read_snapshot`. Owner-side resolution obtains that captured snapshot from the group or its head, and the dispatch path explicitly performs no overlap hold. A pure MGET's last owner worker releases the pin after all values are serialized, before IO reassembly. (`src/server.c`, `src/server.h`)

Consequently there is no Bloom false-positive path in the active write or read protocol. The zeroed `_atomic_probe_retired_*` words preserve default-OFF layout only. (`src/server.h`)

## Consistency boundaries

A non-atomic cross-owner read has no shared read-version step: its owner jobs execute independently and the group joins only at the pending/CDB completion barrier. A mixed result across a concurrent write follows from those executable paths. (`src/server.c:12648-12705`, `src/server.c:22144-22199`)

Same-client ordering is narrower: if the connection's reorder scratch buffer is nonempty, `processCommand` calls `tomoReorderDrainConn` for this connection — draining only its own staged writes and compacting the rest — immediately before invoking `csDispatch`; the drain is surgical and asserts nothing, leaving co-located connections' staged entries intact. (`src/server.c:8584`, then `csDispatch` at `:8590`; drain at `:3859-3880`)

Non-atomic cross-worker RENAME has a real missing interval: HOP1 deletes the source before the IO drain can publish HOP2 to the destination owner. (`src/server.c:11187-11208`, `src/server.c:14564-14570`) `cs_barrier` prevents a later command from the same client from overtaking HOP2, but it does not make the two worker mutations one atomic event for other clients. (`src/server.c:14509-14519`, `src/server.c:8283-8303`) This is an inference from the HOP1 delete, drain-launched HOP2, and per-connection barrier. (`src/server.c:11187-11208`, `src/server.c:14564-14570`, `src/server.c:8283-8303`)

## Enforced invariants

- **Owner-only key access.** Routing chooses the bucket-table owner, binds the sub to that worker's DB, pushes to the same worker, and executes under that worker's lock. (`src/server.c:12648-12705`, `src/server.c:22144-22170`)

- **Publish after initialization.** The coalesced builder completes its position maps and argv vectors and stores `pending` before `csPushSpin` release-publishes queue tails; pipeline and HOP2 re-arms likewise set the next pending count before their first push. (`src/server.c:12669-12705`, `src/server.c:12584-12586`, `src/server.c:13420-13431`, `src/server.c:13463-13485`, `src/server.c:14550-14561`)

- **Gather visibility.** Multi-sub completion uses an acquire-release decrement; for a non-versioned wave the last sub release-publishes the head byte, and the drain acquire-loads that byte before reading results. A terminal versioned wave takes the separate `csMsetInstallDone` publication path described above. (`src/server.c:22171-22199`, `src/server.c:3158-3164`)

- **Original-position replies.** Coalesced MGET and coalesced gather/pipeline inputs use position maps keyed by the original argument order, and MGET reassembly walks original positions rather than completion order. (`src/server.c:12693-12701`, `src/server.c:12997-13003`, `src/server.c:14949-14961`)

- **No later-stage overtaking.** A pipeline or HOP2 group raises `cs_barrier`; the head remains the unretired first ring slot while the drain clears and re-arms that same completion byte. (`src/server.c:12965-12970`, `src/server.c:13694-13706`, `src/server.c:14509-14512`, `src/server.c:14550-14561`, `src/server.c:8283-8303`)

- **Atomic reply after commit publication.** A final versioned wave reaches CDB publication through `csMsetInstallDone`, after owner STAMP or CANCEL jobs have been enqueued and, for non-canceled groups, after `commit_seq` has been release-stored. (`src/server.c:10303-10334`, `src/server.c:10363-10400`, `src/server.c:22179-22199`)

- **Private cross-thread payloads.** Coalesced MGET and set-reduction stages export private `sds` copies, and two-hop value transfer uses a private serialized RDB blob; cleanup occurs after the pending/CDB barrier. (`src/server.c:11625-11647`, `src/server.c:13283-13342`, `src/server.c:11187-11203`, `src/server.c:15245-15269`)

- **One logical completion.** Continuations return before reassembly; terminal `csReassemble` accounts one command, frees the group once, and clears the head pointer. (`src/server.c:4285-4308`, `src/server.c:14864-14882`, `src/server.c:15306-15328`)

## File:line map

| Area | Current implementation |
| --- | --- |
| Cross-node predicate and reply-prefetch branch | `src/server.c:163-176`, `src/server.c:12544-12586` |
| CDB release/acquire completion byte | `src/server.c:3149-3168` |
| Ring-head dispatch and drain | `src/server.c:4236-4308`, `src/server.c:8423-8590` |
| Cross-shard registry and classifier | `src/server.c:10784-10816`, `src/server.c:11161-11179` |
| `csCmdSpec` | `src/server.h:4424-4479` |
| `client` head/sub relationship fields | `src/server.h:1877-1913` |
| `csGroup` | `src/server.h:2108-2277` |
| Group allocation and inline spill | `src/server.c:12418-12492` |
| Queue publication | `src/server.c:12544-12586` |
| Coalesced per-owner sub construction | `src/server.c:12623-12707` |
| Gather/local-fast/legacy route selection | `src/server.c:13490-13740` |
| MGET/MSET worker execution | `src/server.c:11625-11759` |
| Set-operation pipeline | `src/server.c:12938-13487`, `src/server.c:13934-13960` |
| Two-hop dispatch and launcher | `src/server.c:14368-14861` |
| RENAME worker operations | `src/server.c:11187-11279`, `src/server.c:12120-12139` |
| Versioned registration and completion | `src/server.c:9914-9957`, `src/server.c:10272-10413` |
| Identity-based own-read resolver | `src/server.c` |
| Worker pending barrier | `src/server.c:22144-22199` |
| Reply reassembly and teardown | `src/server.c:14864-15328` |

## Mechanisms

- [Owner-operation stamp lane](mechanisms/communication/owner-op-stamp-lane.md)
