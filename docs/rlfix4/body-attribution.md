# Entered GET bodies: source and compiler history

This index covers all 45 entered-body/set changes in the four endpoint comparisons. The JSON retains exact names, digests, cases, source changes and every observed compiler rewrite. A newly entered existing helper is identified as a caller change. The final column is the last observed body rewrite in a selected translation unit; it is not a substitute for the source/caller attribution. First observations without a preceding compilation and differences in symbol selection are not treated as body changes.

| Transition | Namespace | Body | Source or caller event | Last observed compiled rewrite |
|---|---|---|---|---|
| anchor → wave6 | db0 | prepare_local_read | `3676d3cae` rlfix; `5cd136502` clockcut | `4c692daf4` Merge clockcut (0e594f293) into cx-wave4: command clock after dequeue, Redis exact-deadline liveness |
| anchor → wave6 | db0 | FlatStore::hash_key | compiler/inlining history | `f49beb99e` Merge cx-iofix park wake cron and global sleep repairs for wave5 |
| anchor → wave6 | db0 | ordinary parser | compiler/inlining history | `8a1ccffa1` Preserve integer reply selection and derive merged unit budgets |
| anchor → wave6 | db0 | R7 parser | compiler/inlining history | `3fd72af55` Merge cx-serverfix into wave6 |
| anchor → wave6 | db0 | IoLoop::flip_dispatch_paused | `323bbd770` wave5 integration | `323bbd770` Restore executor and IO call boundaries after merged slowlog growth |
| anchor → wave6 | db0 | IoLoop::query_buffer_exceeded | `24c828243` netfix | `c0be5394d` Merge cx-netfix network compatibility TLS and idle reclaim for wave5 |
| anchor → wave6 | db0 | RESP resumable parser | `873b71047` respresume | source/caller change above |
| anchor → wave6 | db0 | RESP original parser | `873b71047` respresume | source/caller change above |
| anchor → wave6 | db0 | multi_session_watch_size | `a400d1f23` txnorder | source/caller change above |
| anchor → wave6 | db0 | local drain | `c97c118a2` trackfix | `08d964975` Merge cx-trackfix causal tracking stamps and accounting for wave5 |
| anchor → wave6 | normal | prepare_local_read | `3676d3cae` rlfix; `5cd136502` clockcut | `4c692daf4` Merge clockcut (0e594f293) into cx-wave4: command clock after dequeue, Redis exact-deadline liveness |
| anchor → wave6 | normal | ordinary parser | compiler/inlining history | `98346c0f3` Keep EXEC promoter and AOF context off ordinary executor frames |
| anchor → wave6 | normal | R7 parser | compiler/inlining history | `3fd72af55` Merge cx-serverfix into wave6 |
| anchor → wave6 | normal | IoLoop::flip_dispatch_paused | `323bbd770` wave5 integration | `323bbd770` Restore executor and IO call boundaries after merged slowlog growth |
| anchor → wave6 | normal | IoLoop::query_buffer_exceeded | `24c828243` netfix | `c0be5394d` Merge cx-netfix network compatibility TLS and idle reclaim for wave5 |
| anchor → wave6 | normal | IoLoop::touch_worker | `f49beb99e` iofix integration | `f49beb99e` Merge cx-iofix park wake cron and global sleep repairs for wave5 |
| anchor → wave6 | normal | RESP resumable parser | `873b71047` respresume | source/caller change above |
| anchor → wave6 | normal | RESP original parser | `873b71047` respresume | source/caller change above |
| anchor → wave6 | normal | multi_session_watch_size | `a400d1f23` txnorder | source/caller change above |
| anchor → wave6 | normal | local drain | `c97c118a2` trackfix | `08d964975` Merge cx-trackfix causal tracking stamps and accounting for wave5 |
| wave6 → wave7 | db0 | ordinary parser | compiler/inlining history | `f0d647b37` Merge branch 'cx-persistfix2' into cx-wave7 |
| wave6 → wave7 | db0 | R7 parser | compiler/inlining history | `f0d647b37` Merge branch 'cx-persistfix2' into cx-wave7 |
| wave6 → wave7 | db0 | multi_session_watch_size | `d64accaca` atomfix5 | source/caller change above |
| wave6 → wave7 | normal | ordinary parser | compiler/inlining history | `f941716b1` Rebalance wave7 inlining budgets and keep GET key access inline |
| wave6 → wave7 | normal | R7 parser | compiler/inlining history | `f0d647b37` Merge branch 'cx-persistfix2' into cx-wave7 |
| wave6 → wave7 | normal | multi_session_watch_size | `d64accaca` atomfix5 | source/caller change above |
| wave7 → pre | db0 | completion closure | compiler/inlining history | `81a7ec066` Merge cx-latencyfix into wave8 |
| wave7 → pre | db0 | ExLoopT<true>::notify_sender | compiler/inlining history | `81a7ec066` Merge cx-latencyfix into wave8 |
| wave7 → pre | db0 | FlatStore::hash_key | compiler/inlining history | `81a7ec066` Merge cx-latencyfix into wave8 |
| wave7 → pre | db0 | ordinary parser | compiler/inlining history | `e42a75b6e` Discard orphan script timings when a pre-disable parent completes |
| wave7 → pre | db0 | R7 parser | compiler/inlining history | `f59e83610` Carry exact timing starts and discard parked WAIT slices on CONFIG no |
| wave7 → pre | db0 | IoLoop::touch_worker | `81a7ec066` latencyfix integration | source/caller change above |
| wave7 → pre | db0 | Op::cmd_name | `81a7ec066` latencyfix integration | source/caller change above |
| wave7 → pre | normal | R7 demotion storage destructor | `81a7ec066` latencyfix integration | source/caller change above |
| wave7 → pre | normal | completion closure | compiler/inlining history | `81a7ec066` Merge cx-latencyfix into wave8 |
| wave7 → pre | normal | ExLoopT<true>::notify_sender | compiler/inlining history | `81a7ec066` Merge cx-latencyfix into wave8 |
| wave7 → pre | normal | ordinary parser | compiler/inlining history | `e42a75b6e` Discard orphan script timings when a pre-disable parent completes |
| wave7 → pre | normal | R7 parser | compiler/inlining history | `f59e83610` Carry exact timing starts and discard parked WAIT slices on CONFIG no |
| pre → post | db0 | FlatStore::hash_key | compiler/inlining history | `18f0ceb8b` rlfix4 final registry guard and budget |
| pre → post | db0 | ordinary parser | compiler/inlining history | `18f0ceb8b` rlfix4 final registry guard and budget |
| pre → post | db0 | R7 parser | compiler/inlining history | `18f0ceb8b` rlfix4 final registry guard and budget |
| pre → post | db0 | Op::cmd_name | compiler/inlining history | `18f0ceb8b` rlfix4 final registry guard and budget |
| pre → post | normal | ordinary parser | compiler/inlining history | `18f0ceb8b` rlfix4 final registry guard and budget |
| pre → post | normal | R7 parser | compiler/inlining history | `18f0ceb8b` rlfix4 final registry guard and budget |
| pre → post | normal | Op::cmd_name | compiler/inlining history | `18f0ceb8b` rlfix4 final registry guard and budget |

The complete instruction ledgers are [function-deltas.json](function-deltas.json) and [source-origin-deltas.json](source-origin-deltas.json). The latter contains 72 exact endpoint deltas grouped by DWARF source origin. Repository origins carry their source commit. The sole changed toolchain-origin bucket is normal batch-32 R7 mix: six inline `unique_ptr` instructions become fifteen in its outlined helper, net +9, at latencyfix integration `81a7ec066`. The five anonymous ROB retirement instructions remain counted and unchanged.

Compile receipts: 82 snapshots through wave 7, plus the wave-8 merge/budget snapshots in [boundaries/](boundaries/). All eight normal/DB0 inlining-budget flag sets are preserved in [inlining-budget-history.json](inlining-budget-history.json). The compile-only snapshots use `-g0`; an explicit PRE control compares 88 selected bodies against the original `-g` objects and finds exact canonical-byte/relocation equality. Endpoint execution counts and linked-server bindings use the full release builds.
