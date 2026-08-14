# THredis thread-modes: 3-Stage port (steps 1-3 in one pass)

Commit 197269a91 on v13-3s-autothreads (mirrors 2s b95248733..848474d03; 2s balancer-spec commits 7ba942a62/6cc52c0d5 are docs-only, already in the shared design doc).

## Step-3 gate validation PASSED (2026-07-04, subagent run)
ASAN strict ifid3/ex3/wb2 knob-on: 3x EX flap cycles + PARKED->IO + PARKED->WB all under churn, DBSIZE 100300 exact + 300/300 sentinels after EVERY shift, full illegal matrix rejected from EX/IO/WB states, ZERO ASAN reports (runs A/B/C). WB join repartitioned wbq 2 (WB1->spare WB2) exactly as designed. Knob-off: 0 thread-modes log lines, legacy mains, knob rejected, ASAN clean. Tree left clean+built jemalloc+uring (sha=197269a9, text 4397455). NOTE this fork's knob is `tomokv-ifid-threads` (NOT tomokv-io-threads like 2s) and DEBUG RESHARD needs `enable-debug-command yes`.
- PRE-EXISTING (not the port): v8d cutover read race — a GET dispatched to src during DRAINING can execute after CLEANUP's range delete => rare transient miss (~1 GET per ~5-10 cutovers under 350k gets/s churn; data conserved). Reproduced KNOB-OFF with manual DEBUG RESHARD 2<->1 cutovers (3 misses/22 cutovers). Both forks share the engine — fix would be fencing reads too or deferring CLEANUP behind a second fence.
- LATENT flag: networking.c freeClientAsync WB-guard bounds use raw server.wb_threads (not resolved wbThreadCount) and exclude the spare-WB ifidx I+1+R; unreachable today (all WB error paths use ts_close_needed) but harden before any WB-side freeClientAsync appears.

## What differs from 2s
- polyThreadCtx has THREE real identity slots: ifid_slot / ex_slot / wb_slot (WB first-class). Spare's are all real: ifid_threads / num_workers / wbThreadCount.
- Slices: exSlice + ifidSlice + wbStrictSlice/wbUringSlice (from wbRun + non-strict wbThreadMain). WB queue selection through `wbOwnsQueue(rid,R,qi)`: knob-off = legacy `(qi-1)%R`, knob-on = live `tmWbqOwner[]` table; scan bound `tmWbQHi` (= ifid_threads+1 when spare exists).
- modeshift-test values: 1=PARKED->IO, 2=PARKED->EX, 3/0=EX->PARKED, 4=PARKED->WB. WB/IO spares cannot re-park (WB-exit = reverse handover + active-set drain, IFID-exit = conn drain — both deferred).
- PARKED->WB = fenced repartition of ONE wbq (control plane sets tmWbqNextOwner; old WB acks at next scan, release/acquire carries SPSC head cursor; ~10ms). JOIN-ONLY-FOR-NEW-RETIREMENTS at client granularity: keep-while-live watched clients stay on the old WB.
- 3s-extra audit sites beyond the 2s list: coordinator fence nprod+1 (spare ifid producer), freebackDrainAll `+tmWbSpareExtra` (spare-WB retirement slot; rings pre-inited by RP-1 full-array fix), WB drain-loop bound covers spare's wbq. dispatchSetOp/csReassemble need nothing (group-sized). db.c DBSIZE + rdb.c rdbSaveRio alloc-folds were nearly missed — caught by the sanity gate (DBSIZE dropped exactly S_final after FLIP).

## Validation (ifid3 ex3 wb2 strict, 16-core laptop)
Knob-off exact (0 thread-modes refs, 2.14M); knob-on 2.22M 15s memtier; EX cycle x2 DBSIZE-constant + marker conservation + empty-assert; shifts under live load; SAVE-while-spare-live reloads complete incl. across knob boundary; IO join 4.41M @48c + churn; WB join retiring at 2.11M. ASAN x3 runs clean (only pre-existing 17B slowlog exit leak).

## Pre-existing (NOT regressions)
- DEBUG RELOAD segfaults knob-off too (getClientMemoryUsage, in-process reload vs sharded design). Use SAVE + restart.
- wbq/resumeq memset AFTER ifid pthread_create in initIfidThreads (boot race, existed before).

## Next
Balancer v1 (pressure signals + quorum are spec'd in THREAD-MODES-DESIGN.md), IFID-exit/WB-exit, main-thread cron-token demotion.
