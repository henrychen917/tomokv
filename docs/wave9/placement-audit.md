# Placement observations in gate checks

Inventory is from `rg` over the gate-owned Python batteries and their shared
helpers. Owner identity comes from live shard rows, never shard ID arithmetic.
Migration tests keep their deliberate before/after changes and conservation checks.

| Check / callers | Observation pair | Disposition |
| --- | --- | --- |
| `_lib.probe_keys`, `owner_buckets`, `cross_owner_pair`, `same_shard_pair` | DEBUG SHARDS vs LBSIGNALS | Four complete bracketed passes, no keys yielded before a coherent pass; malformed/never-stable fails |
| atomicwindow `held_burst` | discovery vs arming | Existing four fresh-state arms; shared stable probe; release/ASAN boots now key-LB and auto-flip off |
| atomic_torn and atomic_hazards | shard ID discovery vs owner map; pre/post map in direct RENAME/EXEC geometry | Same pinned release/ASAN boots; existing fresh-arm rerolls and every torn/read/window assertion retained |
| debug batched ownership | SHARDS vs LBSIGNALS, then SHARD IDs | Shared stable probe; SHARD IDs remain exact checks |
| bplus | shard IDs/filter cells vs earlier owner map | Purpose boot now key/client LB and auto-flip off, throughout B+ and lane checks |
| atomic_plain | discovered keys vs exact SHARDS owner pairs | Existing CONFIG assertions require key/client LB and auto-flip off |
| mode_lane / splitlocal_live | discovery vs final ownership map | Existing CONFIG assertions pin placement; shared discovery now stable; final exact map check retained |
| orthog / rl2s | INFO thread shard counts vs LBSIGNALS | Existing CONFIG assertions pin key/client LB and auto-flip off; exact counts retained |
| xshard_dispatch_scale | INFO shard homes vs LBSIGNALS, final LBSIGNALS | Existing explicit home map and key/client LB/auto-flip-off assertions; performance row remains maintainer-owned |
| scriptatomic `cross_owner_pair`, txn_nx key selection | initial SHARDS vs selected-pair SHARDS | Existing bounded fresh candidate search, rejects moved pairs before issuing work |
| sort cross-owner geometry | discovered owner mapping vs SHARDS | Existing purpose boot key/client LB and auto-flip off |
| redisgap_atomic / wave7 | owner-bucket keys vs selected SHARDS | Shared bucket discovery now bracketed; existing purpose boots pin placement |
| rlcache_churn / legacy_reorder_witness | before/after owners during intended movement | Deliberate migration witnesses, not equality assumptions; retain actual changes and fail missing movement |

Shared discovery callers additionally include datafix2_watch, wb_mixed,
_differ_ccfix, compat3_lualibs, multirace, read_local_lane, wave7,
splitlocal_live, pipeorder, slotless, session_monotonic, rl2s, notifycompat,
mode_lane, rlfix, redisgap_atomic, notify_order, compat3_functions and orthog.
Single snapshots used only to report geometry or count threads are not paired
placement-equality checks. Key hash/shard-ID stability alone is not an owner
comparison. No torn-read tolerance, skip, or success condition was weakened.
