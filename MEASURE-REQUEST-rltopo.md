TomoKV rltopo measurement request, 2026-09-27

The lane implements the three owner rulings against `4329c26f083de480d9eb0b2a601c7b6a7328226c` on branch `cx-rltopo`. MGET now demotes after its first rejected local capture/window instead of retrying. Point GET already demoted on both Churn boundaries in PRE; its production instructions are preserved. The accepted arm transient is documented and tested without changing its policy. The INFO block-cache byte gauge is now a relaxed atomic.

Read-path semantics are committed in `70a4ae41c`, with PAD/code-generation follow-ups `0afbdfb6f` and `394cd0e7b`. Telemetry is a separate commit, `f01b61fd2`. Expanded controls and the instruction audit are `0d61e6038`; compiler settings preserving PRE read instructions are `fe3bce6851ed7bfe6295aee8062835779ade72cb`. This report is the final lane step. No server, benchmark, load generator, gate, push, or performance measurement was run. Mainline still owns both-mode boot, correctness gating, measurements, and merge.

All builds used CPUs 112–127 and `make -j16`. Serverless tests stayed inside that range; the owner-arena fixtures require eight CPUs and used 112–119 for 1s and 120–127 for 2s. Compiler: Ubuntu GCC 13.3.0-6ubuntu2~24.04.1, release `-O2 -g -march=native`, jemalloc. PRE was built from an archive of the baseline inside this worktree at `build/rltopo-pre-src`, with output under `build/rltopo-pre`.

**Frozen arms.** Paths are relative to `/home/user/Projects/cx-rltopo`.

| Arm | Binary | SHA-256 | `.text` bytes |
| --- | --- | --- | ---: |
| PRE | `build/rltopo-pre/tomokv` | `e4227538dcd4aa8d1a0e51ddfe1bf237f175aa65225b4ed1f7096073c4e7b799` | 7,584,364 |
| POST | `build/tomokv` | `7b9c6eec3293ab6026dade24e06c0222f1355eac541dec196e6f9b67ab328610` | 7,583,196 |
| POST frozen copy | `build/tomokv-rltopo-post` | `7b9c6eec3293ab6026dade24e06c0222f1355eac541dec196e6f9b67ab328610` | 7,583,196 |
| PAD-A | `build/tomokv-rltopo-pad` | `6598587852edde8e0e9f2492fc41c20926877e2462eeee1f081e930fc785d2dd` | 7,583,196 |

PAD is **kind A, a behaviour twin: PRE's MGET retry behaviour in POST's exact text size/layout**. It restores the old second local attempt by replacing only the cold unconditional demotion jump with a same-width NOP, in both database namespaces. It retains the separate telemetry fix. No runtime selector, branch, allocation, or load is added to a successful read. The receipt `build/tomokv-rltopo-pad.json` records the two five-byte patches at file offsets 3,164,546 and 6,889,496. All other bytes, sections, and symbol positions are identical to POST. POST's text is 1,168 bytes smaller than PRE; the size change itself is not a performance claim. This request uses the exact-layout A control, not an inverse B control.

Reproduce the offline PAD and instruction checks without executing a server:

```sh
taskset -c 112-127 python3 tools/rltopo_artifacts.py pad build/rltopo-pre/tomokv build/tomokv build/tomokv-rltopo-pad
taskset -c 112-127 python3 tools/rltopo_artifacts.py compare build/rltopo-pre/tomokv build/tomokv build/rltopo-codegen-locked
taskset -c 112-127 python3 tools/rltopo_artifacts.py cache build/rltopo-pre-src . build/rltopo-cache
```

**Every generation writer.** The production search covered `probe_sequence`, `ReadLocalTableGuard`, `read_local_table_guard`, and `read_local_table_mutation_begin/end` throughout `src/`. The following twelve guard sites reach the generation writer. Line numbers refer to the final lane source.

| Writer/guard site | What the bracket publishes |
| --- | --- |
| `src/store/flatstore.h:768`, `rebind_read_local_retire_sink` | New owner retirement sink/cache binding after the old owner's frontier is quiesced. |
| `src/store/flatstore.h:869`, `foreign_read_scope_open_span` | Publication of the scoped foreign-read safety filter. |
| `src/store/flatstore.h:2719`, `snapshot_mark_read_local` | Snapshot cut and current/old table role swap. |
| `src/store/flatstore.h:2885`, `insert_read_local` | Moving an existing object out of the old table; guard is active only when `moves_from_old`. |
| `src/store/flatstore.h:2917`, `clear_read_local` | Clear/FLUSH table withdrawal and retirement. |
| `src/store/flatstore.h:2954`, `clear_during_snapshot_read_local` | Clear while retaining snapshot lifetime. |
| `src/store/flatstore.h:3052`, `install_empty_table_read_local` | New table pointer/capacity/mask publication. |
| `src/store/flatstore.h:3183`, `start_rehash_read_local` | Rehash start and new/old table publication. |
| `src/store/flatstore.h:3195`, `rehash_step_read_local` | Incremental slot migration and eventual old-table withdrawal. |
| `src/store/flatstore.h:3464`, `foreign_read_poison_open` | Whole-shard foreign-read invalidation/filter publication. |
| `src/store/flatstore_atomic.inc:820`, `atomic_prepare_capacity_read_local` | Atomic capacity growth and table replacement. |
| `src/store/flatstore_atomic.inc:1269`, `atomic_exchange_physical_read_local` | Physical atomic object exchange/insertion. |

The ownership route is `Server::adopt_read_local_retire_sink` (`src/core/server.h:2136`) calling the rebind at `:2148`. `adopt_shard_owner_state` (`:2288`) invokes it for both `transfer_bucket_range_quiesced` (`:2191`, adoption at `:2238`) and `transfer_shard_quiesced` (`:2248`, adoption at `:2266`). Those critical sections and all ownership/LB mechanisms are unchanged.

`ReadLocalTableGuard` (`src/store/flatstore.h:640`) reaches the depth-coalesced begin/end at `:3381` / `:3388`. The only increment/store primitive is `read_local_advance_generation` at `:3399`: release odd-store before publication, release incremented even-store at the outer close, retaining the pending bit. Nested guards do not independently advance the generation. Initial construction is `probe_sequence{0}` at `:563`. The `read_local_table_guard()` factory at `:808` has no production caller outside this header; the witness uses it. The `fetch_or`/`fetch_and` sites at `:3441`, `:3445`, and `:3458` change only the pending bit, not the generation. Exhausted generations remain fail-closed as before.

Consequently, this generation is broader than a rehash counter: atomic physical exchanges and safety-filter publication also write it. Ordinary immutable replacement of an existing current-table SET slot does not. Do not attribute every SeqChurn/Generation fallback to a resize.

**Demotion and accounting.** Capture still performs its bounded topology walk and validation at `src/store/flatstore.h:946`. An ineligible/changing capture returns Churn. Point execution at `src/core/ex_loop.h:1315` already breaks directly to owner fallback for capture Churn or failed post-copy validation; `:1402` returns SeqChurn unless an explicit queried-key atomic conflict takes precedence. The legacy point string-copy loop remains in source solely to preserve GCC code generation: its helper at `:971` unconditionally returns true, so its `continue` is unreachable in both PRE and POST. No point topology retry was removed because PRE had none.

MGET's formerly reachable retry is removed at `src/core/ex_loop.h:1288`: after a failed capture or outer window close, clear the private reply and jump directly to `owner_demotion`. The original attempt structure/counter remains behind that unconditional machine jump only to support the exact-layout PAD and test negative control. There is no reachable production second attempt, spin, or retry. Queried-key epoch validation and wide-MGET generation validation retain their existing safety checks, including explicit atomic-conflict attribution. A successful attempt follows its old instruction path.

The existing route is `prepare_local_read` → `drain_local_reads_bounded_impl` (`src/core/ex_loop.h:1596`) → `demote_local_read_batch` (`:951`) → `IoLoop::fused_demote_local_read_batch` (`src/core/io_loop.h:2883`) → `ReadLocalDemotionPlan::commit_reads` (`:2730`). It posts through the ordinary owner route, converts the existing ROB read entry at `:2770`, and counts the fallback at `:2785`. Queue admission/ordering/QSBR behaviour is preserved. For a point read the cost is its normal owner hop when validation detects a changing topology. MGET uses the existing scatter route; one command demotion may involve several owners. The witness deliberately uses one shard to prove exactly one owner task, reply, and retirement.

Use the existing INFO family, not a new counter:

- `read_local_fallback_seq_churn` for ineligible/changed captures and point post-copy validation; `read_local_fallback_generation` also covers a closed wide-MGET generation change or changed queried-key epoch.
- `read_local_mget_fallback_seq_churn` and `read_local_mget_fallback_generation` are MGET subsets of those totals. Do not add a subset to the aggregate.
- `read_local_mget_generation_retries` must remain zero in POST, including the forced windows. PAD/PRE retain the retry mechanism.
- An explicit queried-key conflict may be attributed to `read_local_fallback_atomic_pending` instead; that precedence is unchanged.

Owner ruling 2 is documented at the decision in `src/net/rob.h:829`. Both an unarmed connection with earlier unrecorded writes and sidecar allocation refusal reach ArmFence and the existing `read_local_fallback_arm_transient` reason. The witness exercises a disjoint read in both cases and verifies that the fence ends after the earlier write retires. No arming policy changed.

**Witnesses and controls.** `tests/rltopo_unit.cc` runs without a listener, io_uring instance, load generator, or server worker loop. Each fresh fixture has 16 shards and eight logical threads: eight fused threads in 1s, or six IO/two owners in 2s. Reader and owner are distinct. It enqueues a real read-local ROB operation, forces a real `ReadLocalTableGuard` interleaving, drains the local lane, then consumes the real owner task queue. These are deterministic validation-boundary witnesses, not a concurrent stress measurement.

Each mode exercises ten topology cases: GET capture and post-copy boundaries; one-key MGET capture; MGET with `kMaxEpochKeys + 1` keys at outer close; each with the generation flipped and closed or held odd. GET and one-key MGET also start with an already-open bracket. The checks require the bracket to fire once, zero local retries, exactly one topology demotion, a cleared speculative reply, owner completion with exact RESP bytes, one ROB retirement, and a subsequent stable local hit. Every fixture is fresh; failure to open the window is a failure, never a skip.

Each mode also requires fifteen designated negative-control failures:

| Disabled/broken condition | Required failing assertion |
| --- | --- |
| Never open the generation bracket | Forced topology window fired exactly once. |
| Remove the cold demotion jump / restore PRE's second attempt | Zero Churn/SeqChurn retries; observed two captures, one retry, zero demotions. |
| Suppress the fallback increment | Exactly one topology demotion. |
| Retain speculative reply bytes at demotion | Private reply cleared before demotion. |
| Drop owner execution | Exactly one owner hop and completion. |
| Corrupt owner reply | Owner reply intact. |
| Omit ROB retirement | Single ROB retirement. |
| Keep a new bracket open for the recovery read | Next stable read stays local without another demotion. |
| Do not refuse the sidecar allocation | Sidecar allocation refusal fired. |
| Misclassify the accepted transient, separately for pre-arming and exhaustion | Accepted transient attributed to arm counter. |
| Remove the earlier write fence, separately for both arm cases | Disjoint read is fenced during accepted transient. |
| Supply a new conflicting write at recovery, separately for both arm cases | Arm transient ends at ROB retirement. |

Fixture setup checks fail closed as well. Negative children must exit with status 1 at the designated assertion; a crash or unrelated failure does not count. In addition to the embedded retry-restored control, the offline PAD patch was applied to the linked witness binary. Both `1s` and `2s` then failed at the retry assertion with `captures=2 retries=1 demotions=0`.

Local results: `build/rltopo-final-unit-{1s,2s}.log` pass under ASAN/UBSAN with leak detection enabled, including all fifteen controls per mode. `build/rltopo-unit-pad-{1s,2s}.log` contain the expected external control failures. Witness SHA-256 is `1d90f85626ccf8d21b3c23c1d2befcaa72017c35f5d1dfb8a7a8414337ee1470`; patched witness is `d5a377e0ba8aa45058a50873c400d6190aa90fac0d02eb1ea37f67896416df05`. Existing read-local ring and write-ring tests pass. Existing armed owner-arena tests pass in both modes, including cache census, recycling, release, migration, QSBR, and owner binding (`build/rltopo-owner-arena-{1s,2s}.log`). Gate shell syntax, artifact-tool Python syntax, debug-cache compilation, and the updated recycle `no-bytes` / `witness` mirror generation pass. All eight existing footprint locks compile unchanged.

The gate now emits two rows from the loop at `tests/gate.sh:1261`: `read-local topology demotion (1s)` and `(2s)`. They are collected with `core_units` at **line 2723**, before the quick-tier exit at **line 2854**. Therefore the maintainer should change **EXPECT_QUICK 441 → 443** and **EXPECT_FULL 459 → 461**. Neither constant was edited by this lane. Build readiness adds no row, and embedded negative controls add no separate rows.

**Instruction and telemetry evidence.** The final linked PRE/POST comparison passes **113/113 selected bodies**, in both `tomo` and `tomo_db0`: capture/prefetch/validation, point preparation/local drain, all emitted ordinary and R7 parser/fused-pass specializations, and GET handlers. `build/rltopo-codegen-locked/audit.json` binds the result to the hashes above. The normalizer retains instructions, registers, member offsets, immediates, instruction lengths, and internal branches; it masks verified relocations/literal addresses only. Its added-instruction/register/branch/offset negative controls pass. The script exits nonzero on any selected-body difference. This is a static argument for the common read path, not a throughput or whole-server PMU result.

GCC initially outlined an epoch load and two parser constructors after the header changes. The final Makefile uses the existing compiler-budget mechanism to recover the PRE bodies: ordinary `genthread.o` budget 128880 → 128865; the single-database R7 translation unit is pinned at 147380 with zero unit growth. These are build settings only. No runtime constant/knob was added, and no reorder, writeback, or LB algorithm source was changed. Mainline must retain the instruction audit and require the pure-GET measurement to be NULL; an instruction count alone is not a rate verdict.

Telemetry changes only `KvBlockCache::bytes` to `std::atomic<size_t>` (`src/store/kv_block_cache.h:259`) and uses relaxed owner loads/stores and the relaxed INFO load (`src/core/thread.h:993`, aggregated at `src/cmd/t_server.cc:2197`). Lists and class counters remain owner-private; there is no locked RMW. Cache test readers/instrumentation were adapted to read the atomic explicitly.

The owner's parenthetical “same machine code; zero cost” is supported for the INFO getter, but not literally for every cache method. The isolated GCC audit in `build/rltopo-cache/cache.json` reports:

| Wrapper | PRE → POST code bytes | PRE → POST static instructions | Exact body identity |
| --- | ---: | ---: | --- |
| INFO getter | 51 → 51 | 14 → 14 | Yes |
| Cache take | 180 → 180 | 46 → 46 | No: load scheduling changes |
| Cache put | 179 → 179 | 46 → 44 | No: class-count register/store scheduling changes |
| Cache release | 104 → 104 | 28 → 29 | No: separate load/test replaces memory comparison |

These are wrapper disassembly counts, not executed instructions/op. POST contains no locked update or memory exchange. An added sequentially consistent fence in the INFO control is detected. Do not claim an overall measured zero cost from this audit; the cells below must settle it.

**Mainline measurement request.** Use the gate's instrument and ABBA protocol on a quiet box, with the frozen PRE/POST/PAD-A binaries above. Keep geometry, placement, value sizes, clients, dataset, offered load, warmup, and all unrelated settings identical. Reproduce gate geometry first: `--shards 16`, eight cores, and the gate's `--ratio $GATE_RATIO` for 2s (six IO/two owners); 1s uses eight fused threads. Use the gate's existing client placement. Record all effective settings and both database variants selected by mainline's gate; the binary contains both. Keep key-LB/client-LB and all unrelated controls as in the paired mainline cell.

Obtain same-binary nulls first. Run capacity and matched-offered-load comparisons using the gate's calibrated instrument. For every arm/cell report completed read/write commands, achieved mix, rate, cycles/op, instructions/op, IPC, and latency, with the same completed-command denominator. Report both cache-resident and DRAM-resident footprints for GET and mixes. Use the gate's established null/parity criterion, not a new tolerance. An identical-arm spread above 2% invalidates the comparison as contention or a defect. Do not average a failing cell into a pass.

| Required cell | Modes / depths / settings | Deciding result |
| --- | --- | --- |
| Pure GET, armed | 1s `h09/h11/h13/h15`, 2s `h25/h27/h29/h31` in `tests/headline_cells.txt`, p32; copy those definitions at p8, preserving their other fields (512 connections, atomic=1, all overlap/reorder combinations). | **NULL** PRE/POST and PRE/PAD at the paired null floor, including matched-load rate and instructions/op. POST/PAD should also be NULL. A GET regression or new common-path instructions rejects the candidate. |
| SET:GET = 1:1, armed | Both modes, p32 and p8, all-on posture matching h15/h31 and the same data/client geometry. | Main-command parity at matched load; report cycles/op, IPC, instructions/op and read/write rates separately. |
| SET:GET = 1:9, armed | Both modes, p32 and p8, same settings as the 1:1 cell. | Same parity requirement; quantify fallback rates, not just aggregate throughput. |
| Growing-keyspace SET plus concurrent GET, armed | Both modes, p32 and p8, fresh state per arm/repetition; recipe below. | Actual resize engagement, measured GET rate/latency versus demotion fraction, and zero POST local retries. Account for the owner-hop cost during the changing topology. |

Ratio grammar matters: **memtier uses SET:GET**, so the requested mixes are `--ratio=1:1` and `--ratio=1:9`. The gate headline `MIX` field is **READ:WRITE**, so those same cells use `mix=1:1` and `mix=9:1`. Preserve the workload's actual connection mixing/order, and record achieved command fractions. No claim about connection homogeneity follows from a ratio alone.

For the rehash-heavy cell:

1. Start each arm from fresh state. Populate the same stable GET key range, establish the read-local lanes, and drain setup work before opening the scored interval. The GET connections remain active while a separate memtier SET-only stream (`--ratio=1:0`, sequential keys via `--key-pattern=S:S`) inserts previously absent keys.
2. Grow the SET range in phases. Set `--key-minimum` to the previous phase's maximum plus one and raise `--key-maximum` past successive table resize points. Derive the endpoints from actual table capacity/live counts and `FlatStore::kLoadPct`/`kMinCap` (`src/store/flatstore.h:584`); do not recycle a fixed key range and accidentally measure overwrites. Use enough distinct inserted keys to cross multiple capacity increases, with identical endpoints and seed in all arms. Keep GETs on the original populated keys. Establish distinct inserts from keyspace cardinality, not SET completion count; generator threads can repeat keys.
3. Between scored phases, use the existing owner-routed `DEBUG REHASH-STATE` to record shard 0's rehash starts, current/old capacities, cursor, old-live count, and key count (`src/cmd/t_server.cc:801`). It reports **shard 0 only**; do not present it as a census of all shards. Record total successful unique inserts as well. Collect INFO before/after the scored interval, not in a busy polling loop competing with GET.
4. Report GET offered/completed rate, latency, cycles/op, instructions/op and IPC; SET completion rate; actual resize progress; deltas of `read_local_hits`, `read_local_fallback_seq_churn`, `read_local_fallback_generation`, both MGET subsets, `read_local_mget_generation_retries`, and the arm-transient/inflight-write/atomic-pending reasons. With a GET-only reader stream the MGET counters should be zero. Normalize topology fallback totals by completed reads and report the raw counts too. The generation-writer table above limits any causal interpretation of the counter.
5. Require both a real resize and observed topology demotions for the churn-cost claim. If the window is missed, repeat with fresh state under the mainline harness's bounded attempt policy; exhaustion is an engagement failure, not a skipped/pass row or permission to widen a tolerance. Keep the deterministic witness result separate from this concurrent rate measurement.

The GET churn cell prices an existing owner-hop path: PRE point GET already demoted. The changed retry decision is exercised decisively by the MGET witness and its PAD control. After writers stop and rehash settles, require recovery to the steady GET null cell. A permanently poisoned generation or continuing migration is not a steady-state sample.

Mainline must also run `tests/gate.sh iteration` after adjusting the two expected counts, and retain the full main-command/both-mode regression requirements for merge. The source gate, performance instrument, and measurements were not run by this lane.

| PRE vs POST vs PAD result | Status |
| --- | --- |
| Selected read instruction bodies | PRE = POST, 113/113; PAD differs only in two cold MGET jumps |
| Forced topology / arm witnesses | POST passes in both modes; broken controls fail as designated |
| Pure GET armed p32 / p8 rate, PMU, latency | Pending mainline; must be NULL |
| Armed 1:1 and 1:9 mixed rate, PMU, latency | Pending mainline; must retain parity |
| Rehash-heavy demotion counts and read rate | Pending mainline; engagement and cost must be reported |
| Both-mode server boot and full gate | Pending mainline |

Append measured receipts/results as `MEASURE-RESULT` in this worktree. No performance acceptance or paper claim is made until those results exist.
