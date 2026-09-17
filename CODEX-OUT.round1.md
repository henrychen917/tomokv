Five cumulative layout commits completed on `cx-cache-audit`, in the requested order. PRE is `e867f780a24294df59cc353c6462868b960af5a5`; `5ebf0dcaf` only saved the supplied audit document before commit 1. Exact arm commits are in `build/audit/arm-N/COMMIT`.

Commits: 1058bf23a (step 1), 70ee23a94 (step 2), 7d9f49ddb (step 3), 67ab98b0f (step 4), 3272eb536 (step 5).

All offsets below were checked first in a fresh release build with gdb `ptype /o` for ThreadCtx, Op, Client, Rob<64>, Shard and FlatStore, and checked again after each commit. The existing swap was verified: total_commands_=408, atomic_scan_holds_=120. Every release build used `taskset -c 112-127 make -j4`.

| Step / finding | Before → after | Added compile-time lock |
|---|---|---|
| 1 / #1 ThreadCtx | parked_ 688→7; ring_ stays 8; task_notify_ stays 696; all other field offsets retained | `ThreadCtxLayoutLock`: task_notify − parked_last ≥64 (689 bytes); parked_=7, task_notify_=696; alignof(ThreadCtx)≥64; parked_ and the last byte of ring_ share line 0. |
| 2 / #2 Op | state 184→31; reply_code_/reply_code_ok_ stay 29/30; argv_inline_ 192→32; reply 32→160 | `OpLayoutLock`: reply_first − completion_last ≥64 (129 bytes); completion bytes pinned at 29/30/31; argv=32 and reply=160; reply/direct/zc/integer result block kept contiguous. |
| 2 / #6 Op | parse spec/shard/read_cut/hash/rbuf/route fields stay at 0/8/12/16/24/28; reply leaves their line | `OpLayoutLock`: reply_first − parse_last ≥64 (132 bytes), for every base. The three completion bytes intentionally remain in the parse header. |
| 3 / #3 ThreadCtx | nchan_ 760→116; client/release/transfer masks remain 712/728/744; cold tail stays at its original offsets | `ThreadCtxLayoutLock`: task_notify − nchan_last ≥64 (577 bytes); nchan_=116 on the transport line; four-mask span remains 64 bytes. |
| 4 / #4 + #5 Client/Rob | detailed field table below; Rob alignment 64→32; Client alignment stays 64 | `RobLayoutLock`: frontier_first ≥io_last+64 (160−95=65), with all IO-private fields in 0..95. `ClientRobLayoutLock`: Rob starts at 96; private stores, chunk pointers, frontiers and following buffer headers cannot share lines for any valid Client base. |
| 5 / #7 Shard | no field offset changes; scalar allocation guarantee becomes 64 bytes; type alignment remains 8 | Matched aligned `operator new/delete`; `ShardLayoutLock` pins allocation alignment 64/type alignment 8, reader block to one aligned line, owner block to one other line, and both owner blocks away from the foreign-reader line. FlatStore's existing base-independent locks stay intact. |

The remaining moved Op fields are direct 152→280, direct_cap 160→288, direct_len 164→292, zc_ptr 168→296, zc_len 176→304, zc_shard 180→308, reply_ival_ 188→312. argv_heap_/argv_cap_/argc_ stay at 320/328/332. The separated executor result block is 160..315. Locks are in src/exec/op.h:471 and src/core/thread.h:1215.

The audit's proposed reply=64 does not satisfy its all-base guarantee: an Op at base residue 48 would put state=31 and reply=64 on the same line. Moving the existing 128-byte argv array ahead of reply instead supplies the required distance without growing Op. The guarantee covers the named fields within one Op; the fixed 336-byte array stride can still permit sharing with neighboring Ops.

ROB offsets in the next table are **absolute Client offsets**, matching the audit:

| Field | Before | After |
|---|---:|---:|
| rob_ | 128 | 96 |
| rob_.chunks_ | 128 | 192 |
| rob_.dispatch_ | 192 | 256 |
| rob_.flush_ | 256 | 264 |
| rob_.read_local_pending_slots_ | 264 | 272 |
| rob_.read_local_write_valid_ | 200 | 96 |
| rob_.read_local_write_wide_ | 208 | 104 |
| rob_.read_local_write_force_ | 216 | 112 |
| rob_.read_local_arm_state_ | 220 | 116 |
| rob_.read_local_unarmed_write_id_ | 224 | 120 |
| rob_.local_mget_fence_id_ | 232 | 128 |
| rob_.read_local_arm_stats_ | 240 | 136 |
| rob_.read_local_owner_slots_ | 272 | 144 |
| rob_.read_local_state_ | 280 | 152 |
| rob_.read_local_pending_filter_ | 288 | 160 |
| buf_ | 320 | 320 |

The 96 bytes of private ROB fields cannot fit on one 64-byte line. Consuming 32 bytes of Client's existing pre-ROB hole places private state at Client 96..191, chunk pointers at 192..255, and the frontier block at 256..279. Aligning only the Client buffer member preserves buf_=320 and every following field. No IO-private field was moved onto the frontier or chunk-pointer line, no sidecar was added, and no method logic changed. Locks are in src/net/rob.h:1062 and src/net/conn.h:867.

For #7, store_=56 and stats_=1000 remain unchanged. The foreign-reader block stays at Shard 256..296 (line 4), ordinary owner counters at 392..439 (line 6), and atomic owner accounting ends at 175 (line 2). Shard's scalar new/delete pair at src/core/shard.h:61 uses std::align_val_t{64}. The layout lock is at src/core/shard.h:529. Stack/embedded Shards still rely on FlatStore's all-base distance proof; no alignas was added to Shard.

All size locks hold after every step: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. No per-operation branch, memory order, ownership rule, retry, lock or allocation site changed. Finding #8 was left alone as requested.

Validation after every layout commit: release build, make unit (six existing programs plus the new cache layout test), and 48 regular extended unit invocations passed: **55 passes per arm**. The extended set covers cmdlookup, foreign-read safety, core concurrency with ASAN/UBSAN, atomic survivors, netcmd, store/sidecar regressions and rehash waits. All builds and runs were pinned to 112-127. Full gdb output, offsets, build logs and per-case logs are in build/audit/{pre,arm-1,...,arm-5}/.

Two extra, already-documented diagnostics were also run and remain **FAIL**, identically at branch point and after every step: atomic `post_apply_probe` (script/foreign APPEND serial outcome after first-owner APPLY) and netcmd `collection-oom` (a failed multi-field HSET leaves a changed prefix). Baseline reproductions were built from 5ebf0dcaf sources, verified identical to PRE for src/tests/Makefile/third_party. Their failure logs are in build/audit/pre/ and each arm's unit-logs/. They were not skipped, weakened, or counted green.

The cache layout test enumerates all 64 base residues for byte-distance guarantees and all legal Client alignments for embedded ROB boundaries. Its allocation spy checks Shard's actual aligned new/delete overloads, sizes, addresses and OOM propagation. Six negative controls in private header copies were detected: restoring #1, restoring #2/#6, restoring #3, restoring #4/#5, breaking the Shard new alignment, and breaking the delete alignment. Four fail compilation at the locks and two fail runtime allocation assertions. Results and reproducer: build/audit/negative-controls/results.json and build/audit/negative-controls.py.

| Arm | Executable (relative to this worktree) | .text bytes | SHA-256 |
|---|---|---:|---|
| pre | `build/audit/pre/tomokv` | 3,793,843 | `28580ac29c1c4a8807455ed423bee32af9427425efb531cf2147a96e478c7b9b` |
| arm-1 | `build/audit/arm-1/tomokv` | 3,793,747 | `62ce14b0dbb9e1127b1d2fa49893a008e2908120990c9ea2a81b8f317c110f1d` |
| arm-2 | `build/audit/arm-2/tomokv` | 3,798,051 | `dba022ff3add6794b471eec72ba6a948d261d687d213f20691966160fd468f27` |
| arm-3 | `build/audit/arm-3/tomokv` | 3,796,675 | `2e800263ac69fe8a9013eaf61a4621b39aac2e048cd4a960b1eff34d451a2392` |
| arm-4 | `build/audit/arm-4/tomokv` | 3,796,707 | `d760e1975753dc153bc1904d70fac39d11fd63740f249748448925e55ad2a329` |
| arm-5 | `build/audit/arm-5/tomokv` | 3,796,755 | `3bdeb8a7c6c35d0551b001cd85ee39ed0e36e5760dcd57d640ab0844fd02018c` |
| pad | `build/audit/pad/tomokv` | 3,796,755 | `d3d9b8e2941f44261de08e9fd82df6f22af6f0bb8d63c2091c04a89067d4ef13` |

ONE PAD twin was built from untouched PRE objects with 2,880 unreachable prefix NOPs plus 32 unreachable tail NOPs. Its .text exactly matches arm-5 (3,796,755 bytes); all gdb field layouts exactly match PRE. Padding metadata, assembly inputs and link command are retained in build/audit/pad/. Canonical cumulative arms contain no injected padding. Hash verification: `sha256sum -c build/audit/SHA256SUMS`.

MEASURE-REQUEST contains the ordered incremental comparisons, cumulative/PAD controls, exact cells and verdict rules. The IO/ex coherence claim is 2s only, with mandatory 1s regression controls; no performance result is claimed. No server, benchmark, load generator or gate was started. No gate rows or EXPECT_QUICK/EXPECT_FULL values changed. Mainline still owns boot/gate/measurement/merge.

CX-cache-audit-DONE
