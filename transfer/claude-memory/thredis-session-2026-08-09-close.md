---
name: thredis-session-2026-08-09-close
description: "Session close 2026-08-09: flip SHIPPED, prefetch SHIPPED, onever merged (dev @7eb7483ab); ownread+retdiet2 = rebase-replay jobs (architecture conflicts, aborted clean); SIX codex agents detached and working — harvest instructions here"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**Dev @7eb7483ab on both remotes, clean.** The day: flip controller shipped
([[thredis-flip-shipped]]), storage prefetch shipped + skip rejected ([[thredis-prefetch-truth]]),
onever merged with mechanism witness, #103 validated airtight, sweep-livelock stack
([[thredis-sweep-abandon-livelock]]), pool-loss = harness bash bug ([[thredis-flip-pool-broken-p0]]).

# TWO REBASE-REPLAY JOBS (both attempted as merges, both ABORTED CLEAN — deliberate)

Textual merges would blend incompatible architectures; both need commit-by-commit replay onto
current dev, reasoning each deletion:

1. **ownread → dev** (#101 has the full plan + my four already-worked-out resolutions). Replaces
   hold-and-park with a client-aware 3-arg kvobjVersionAt(kv, snapshot, client). Dev's post-fork
   refinements that must survive or transfer: sigexact exact-key test, bd1a449ba MSETNX/DEL hold
   expansion (transfers to the resolver's own-origin widening = 3f4cea426's purpose), cutover
   parking. Gate: full gauntlet_ownread + payoff cells vs the fork's own numbers + the soak with
   inflight sampled (the EMPTY/inflight-512 signal is STILL unexplained — reproduce with logs
   FIRST).
2. **retdiet2 (e32918583 "collapse version retirement waits", +3.8%) → dev**. Restructures
   retirement: TOMO_RETIRE_PRUNE_UNLINKED state, committed_next reverse links,
   tomoEnqueuePhysicalRetire batching, bare decrRefCount — vs dev's LIFECYCLE-PIN protocol
   (tomoAtomicLifecycleRelease / tomoVersionPruneFinish keeping vmeta valid through callbacks).
   QSBR/grace territory: a half-migrated state machine = UAF. Replay must map each retdiet2 site
   onto the pin protocol or consciously replace the protocol wholesale.

# SIX CODEX AGENTS running detached (setsid — they survive session end and commit autonomously)

Worktrees + branches (bases: first three ac8283bbb, last three 7eb7483ab):
  cxcache  codex-cxcache   reuse dispatch hash in EX — COMMITTED 8d2173d8e, agent was still refining
  cxexec   codex-cxexec    320B execution core
  cxmsg    codex-cxmsg     192B/3-line IO->EX message header
  cxpureio codex-cxpureio  RIG: in-thread fake RESP, IO stall-free IPC ceiling — ASYNC-BATCHED
                           shape mandated (real event-loop batch geometry, not scalar loops)
  cxpureex codex-cxpureex  RIG: in-thread fake dispatch, worker stall-free ceiling (decomposes the
                           ~2.0M ops/s/worker wall [[thredis-worker-overhead-bound]]) —
                           WORKER_POP_BATCH geometry + interleaved prefetch state machine mandated
  cxsim    codex-cxsim     RIG: tomokv-sim-hop-ns cross-L3 emulation — OWNER CORRECTION APPLIED
                           (relaunched): DELAYED VISIBILITY model (entries consumable at
                           publish+hop_ns, neither side ever waits — latency converts to occupancy),
                           NOT producer busy-waits (the system is fully async; a producer stall
                           fabricates sensitivity that does not exist). CLFLUSHOPT variant = the
                           hardware cross-check. Sweep 0/50/100/200/400ns at harvest.
  (Rig agents were killed+relaunched with these briefs; the exit-watch can no longer name-match
  them — COMMIT events, which are git-based, remain the harvest signal.)
All briefed: code-only (never build/test), rigs off-by-default zero-cost, notifyguard honored,
commit with invocation + expected-output docs.

# HARVEST RESULTS SO FAR (this session, post-close addendum)

- **cxcache MERGED** (dev @d60e8ad8f): instr/op −1.2/−1.8%, ops +0.2/+1.0%, witnessed via
  kstat flat_hash_reuses.
- **cxexec MERGED** (dev @2f80ef045): get_p32 +2.9% mean 3/3 concordant, IPC 1.119→1.149;
  clientExecTail union keeps the 320B core, reply_cdb pinned at offset 320; all 11 dev tail
  fields verified re-homed before take-incoming. Combined with cxcache: 7.80M get_p32 vs
  7.64-7.70 pre-merge band.
- **cxmsg HELD**: wash on single-CCD (physics — header compaction pays on cross-L3 only).
  Branch codex-cxmsg @78ddfc79e waits for a VALID hop-latency curve.
- **cxsim REJECTED AS-BUILT** (branch @34aa9eabd): built a BUSY-WAIT (tomoSimHopWait spin — the
  explicitly forbidden model) wired ONLY to `fake->is_flush` sentinel messages — normal traffic
  never touches it, so the 0/100/200/400ns sweep (flat: get_p32 7.63-7.67M, mget8 545-551K) is
  VACUOUS, not a tolerance result. The vacuous-validation rule caught it (no engagement witness).
  SALVAGE: its TSC calibration + RDTSCP migration-guard code is sound and reusable. REWORK BRIEF:
  the delayed-visibility gate must live at the WORKER POP visibility check (entry publish-stamp +
  hop_ticks vs now → skip to other visible work) and the IO-side CDB drain symmetrically, with an
  engagement counter (entries deferred at least once) so the sweep is witnessable.

# THE IPC CEILING ANSWER (owner's question, measured this session)

Rigs built+run (real code paths, batch shapes preserved, perf-attached externally):
  PURE-EX  (cxpureex @2bcc779e2, --pure-worker-rig):        IPC 3.294
  PURE-IO  (cxpureio final @57577018e, DEBUG TOMO-PURE-IO): IPC 2.285 (v1 4a447db2a: 2.298 —
           two rig versions concordant; final path RESP->parse->route->exQueuePush boundary)
  REAL     (same-family binary, get_p32 2M saturated):      IPC 1.132 (whole-process blend;
           per-role split blocked by shared thread comm names — cachetopo's naming patch unlocks)
=> The async architecture's stall-free best case is 2.0x (IO) to 2.9x (EX) today's operating
IPC. The ~2.0M ops/s/worker wall decomposes ≈1/3 instructions, ≈2/3 stalls — the owner's "reach
it with prefetch + async communication" has a 2.9x target; lvl3 prefetch's 1.10→1.20 recovery is
the first sliver of it. CAVEATS before quoting hard: (1) verify pureex's synthetic key-set SIZE —
if far below 2M keys, part of the 3.29 is data residency, not comm-stall absence; rerun the rig
at 2M-scale to split data-miss vs comm-stall; (2) per-role real IPC needs the thread-naming
patch. Rigs are measurement-only branches (not merged; off-by-default verified by normal boots).

# REAL-LOAD STALL MAP (measured, dev @2f80ef045, get_p32 2M saturated — the ceiling-gap answer)

Macro: IPC 1.14; frontend stalls 21.4% of cycles; ~32% of dispatch slots backend-stalled; fills
67% local_l2 / 29% local_ccx (2.08B cross-core fills ≈ 17% of cycles) / 3.5% DRAM.
DRAM-fill sites: REPLY PATH ≈32% (_addReplyToBufferOrList 21.5 + addReplyBulk 7.7 + part 3.1) —
the worker's reply-byte writes into lines ping-ponging with IO = the async-comm surface, THE
biggest attackable bucket (plus most of the CCX mass); flatFindForWrite 28% (storage probe —
lvl3 prefetch's territory, L2-warm at 2M so gate rightly shut); ull2string+ll2string 16%;
memmove 9%. Cycles: exSlice 17.3% (dispatch-loop instructions), flatFindForWrite 11.1%.
ATTACK ORDER for the 2.0-2.9x ceiling chase: (1) reply/CDB line locality (packing, batch
publication, cxmsg header when multi-CCD) — biggest bucket, untouched; (2) storage prefetch
already shipping; (3) frontend/icache (cxexec split started this class).
FOLLOW-UP before claiming: GET routes through flatFindForWrite — if the READ path takes a
write-variant probe that RFOs the slot line, that is a free win; read the source first.
Raw: stallmap_macro.txt, cyc.data, dram.data in $J.

# BEST-CONFIG PERFORMANCE TABLE (final dev @2f80ef045, t8 c25, 2M keys hit-pinned, owner-requested)

  GET  p1  io7/ex1   830,265        GET  p32  io4/ex4  8,093,350
  SET  p1  io7/ex1   815,946        SET  p32  io4/ex4  6,911,336
  MGET8 p1 io6/ex2   645,372        MGET8 p32 io4/ex4  1,148,184 (9.19M keys/s; io5: 888K)
  MSET8 p1 io5/ex3   559,823        MSET8 p32 io4/ex4    988,448 (7.91M keys/s; io5: 681K)
Reconciliation of earlier mismatches: merge-A/B cells pinned io4/ex4 (p1 understated ~40%);
the codex-A/B mget8 cells had UNQUOTED $MG8 word-splitting to single-key MGET (both arms equally
broken → no merge decision corrupted, but the cxmsg WASH VERDICT IS VACATED — retest with quoted
apparatus); some battery ops columns were transit-polluted. bestcfg.sh is the clean apparatus.

# HARVEST PROTOCOL (next session)

Per fork: build (quietbox first), notifyguard, control-armed boot test, THEN judge:
- cxcache/cxexec/cxmsg: quickcheck A/B vs dev binary (8 cells, instr/op verdict, saturated
  memtier per [[thredis-saturated-benching-rule]]); merge winners inline, revert losers, brief
  codex on potentials.
- cxpureio/cxpureex: run rig mode under perf stat → IPC/instr-op ceiling table vs the same path
  under real load = the owner's stall decomposition deliverable.
- cxsim: sweep hop-ns 0/50/100/200/400 on 2-3 workloads → the cross-L3 penalty curve.
Boot-test FIRST always — a fork can silently revert shipped fixes
([[thredis-codex-fork-integration-traps]]).

# Also open: #101 soak signal, #111 knob_matrix atomic cells, #115 uring u_io, flip residuals
(warmup A-B-A, modal landing read, zrange tie policy — [[thredis-flip-shipped]]).

# WAVE-2 CODEX AGENTS (launched end of session, from dev @2f80ef045 — the carrier campaign)

Owner ruling: the audit findings are UNIVERSAL (every command rides the dispatched-client
carrier) — act on cacheio/cacheex/execctx. Three agents, code-only, building ON the
clientExecTail split:
  cxcarrier   codex-cxcarrier   TOUCH DIET for the 1,336B/~13-line dispatch carrier (execctx+
                                msgpass convergent rank-1; lazy init, reset-only-dirty, keep the
                                GET/SET lane inside the 320B core)
  cxioclients codex-cxioclients IO-side: hot/cold split of the 1,600 REAL client objects
                                (cacheio rank-1, ~1.7-2 MiB/thread demand-touched)
  cxreply     codex-cxreply     the MEASURED #1 stall bucket: reply-write line locality
                                (~32% of DRAM fills + most cross-core fills; STALLMAP.md in tree)
Harvest identically: build, guard, boot-test-first, bestcfg.sh cells (the clean apparatus),
instr/op + per-line-touched witness. These compose with cxexec's +2.9% — same target, next bites.
Also: cxmsg retest (quoted apparatus) = +1.0% lean on real MGET-8, not a loss — hold stands
pending cross-L3 evidence; cachetopo thread-naming patch still a trivial pending merge.

# WAVE-2 HARVEST VERDICTS (2026-08-10 早, all three gates did their job)

0/3 merged; dev stays @2f80ef045. cxcarrier (8768e62d3 express-in-core): WASH, 3 discordant
pairs (+0.5/−0.5/+0.8%), added +0.9% instr for no net — cxexec's split already captured the
reachable client-line locality. cxioclients (9d6fdee71 bounded hot prefix): WASH (+1.7/−1.6/−1.4%
— the +1.7 was a noise draw). cxreply (997d9b187 one-line bulk overwrite): REJECTED AS-BUILT —
instr/op −2.7% REAL but IPC 1.137→1.099 (likely broke write-combining), ops −0.5%.
KEY INSIGHT: the 2M regime keeps reply/client lines L2/L3-warm — the stall map's "32% of DRAM
fills" was share-of-a-small-total there. NEXT-SESSION RETESTS: (1) cxreply at 40M DRAM-bound
(its instruction cut may pay where lines are cold); (2) cxcarrier redesign brief to codex
(express promotion added instructions); branches kept. All boot/guard/MGET-verified before cells.

# WAVE-3 + FOLLOW-UP RESOLUTIONS (2026-08-10)

- flatFindForWrite-on-GET: RESOLVED, no free win — no read-variant exists; the link-returning
  find must compute the insert position; on GET (no tombstones) probe length = read-find, no
  stores/RFO until a write through the link. Its 28% DRAM-fill share = the data misses any probe
  pays (prefetch territory). Minor potential only under tombstone-heavy deletes.
- cxreply @40M retest: POSITIVE LEAN, held — pairs +0.4/+3.2/-0.1 (mean +1.2%, 2/3), vs slightly
  negative at 2M. Regime story mirrors prefetch (pays where reply lines are cold) but below the
  3/3 bar; also its 2M IPC drop (1.137→1.099, suspected write-combining break) is not understood.
  HOLD beside cxmsg; both re-judge on multi-CCD or after the WC question is answered.
- WAVE-3 RUNNING (2 agents): cxsim REWORK (delayed-visibility at real pop/CDB sites + engagement
  counter — brief embeds the wave-2 failure), cxcarrier2 (touch diet by ELIMINATION only, with a
  distinct-lines-touched witness; PRIOR_ATTEMPT.md in tree explains why express-promotion washed).
  Harvest per the standard protocol when they commit.

# CROSS-L3 VERDICT (cxsim rework b94df930c — WITNESSED, the multi-CCD prediction)

Delayed-visibility rig at the real pop/CDB sites, engagement counters proving every arm:
  p32 sat:  hop 0=7.735M; 100/200/400ns = 7.10-7.14M FLAT while deferrals grow 51K->5.0M.
            The ~8% step is constant armed-rig tax (per-entry TSC stamp), NOT latency response.
  p1:       hop 0=603K vs 400ns=594K (-1.5%) with 13.3M deferrals (~90% of dispatches gated).
=> THE ASYNC ARCHITECTURE IS ESSENTIALLY IMMUNE TO CROSS-L3 VISIBILITY LATENCY — it converts to
occupancy as designed, at both depths. Multi-CCD's real tax will be LINE-TRANSFER BANDWIDTH (the
2.08B CCX fill mass), not hop latency. CONSEQUENCE: cxmsg + cxreply must be judged as BANDWIDTH
reducers — the rig's CLFLUSHOPT variant (not built by the agent) or the real Threadripper is
their judge; visibility-latency arguments for them are dead. ex->io deferrals were tiny (69-1.6K)
= the CDB drain naturally trails publish by more than 400ns — completion-side slack is large.
Rig branch codex-cxsim @b94df930c, measurement-only, off-by-default verified (hop=0: 0 deferrals).

# OWNER DESIGN: TOPOLOGY-SPLIT COMMUNICATION (2026-08-10) + validation agent cxxnode

In-node = current path byte-identical (fast path IS the status quo; refuse to tax the common
case); cross-node = prefetch-heavy (consumer-side batch prefetch of ring/CDB/header lines,
extending exPrefetchBatch — targets the consumer-touch cost that survives async absorption) +
the bandwidth reducers (cxmsg header, cxreply) gated by the same topology bit. WHY THIS ESCAPES
the failed fast-path pattern: the predicate is a static boot-time topology BIT (free, exact),
not a per-key guess (costly, blind — hot/recent-key both died on that). Agent cxxnode
(codex-cxxnode from 2f80ef045, DESIGN.md in tree) builds: (1) tomokv-sim-xnode producer-side
CLFLUSHOPT-after-publish = cross-CCX touch emulation on this box, (2) the topology-gated
consumer prefetch path (test mask knob marks workers remote). Validation A/B when it commits:
baseline vs flush (the emulated tax), flush vs flush+prefetch (does the design recover it) —
proves or kills the cross-node path BEFORE the Threadripper. cxcarrier2 still running.

# CARRIER TOUCH-DIET: CLOSED FOR THIS REGIME (cxcarrier2 aa14a7ff3 also WASH)

Second attempt (elimination-only, dirty-mask) also washed: +0.3/+0.9/-0.2% discordant, instr/op
+0.7% (mask bookkeeping > savings). ESTABLISHED PATTERN, two implementations deep: at 2M keys /
200 conns the client tail lines are CACHE-WARM, so eliminating touches to them saves ~nothing.
The touch-diet (and cxreply's reply-line work) belong to COLD-LINE regimes: very high connection
counts, 40M-class datasets (cxreply already leans +1.2% there), or multi-CCD. Single-CCD 2M
chapter of the stall campaign is COMPLETE: cxexec's +2.9% was the reachable win; the rest of the
gap is (a) data misses (prefetch, shipping), (b) frontend 21% (icache — untried), and (c) costs
that only exist in bigger regimes. Branch codex-cxcarrier2 kept for the high-conn/multi-CCD
retest. cxxnode (topology-split validation) is the bridge to the next regime — in flight.

# CROSS-NODE VALIDATION VERDICT (cxxnode 7fad862c2+4b3e8978a, four arms, all witnessed)

baseline 8.005M | TAX (flush-after-publish, 59.9M lines) 7.589M = -5.2% | TAX+CURE 5.726M
(-28.5%) | CURE-ONLY 5.895M (-26.4%, 72-75M payload prefetches = ~4.7 pf-ops per 1-line reply).
1. Cross-node TOUCH cost at p32 saturation is only -5.2% at full memory prices (real cross-CCX
   ~= -2-3%) — the async pipeline absorbs touch cost like it absorbed visibility latency.
2. The prefetch-heavy cross-node path is REJECTED WITH DATA: its machinery costs -26% with no
   tax to cure; no cure exceeding ~5% cost can ever pay here.
STRATEGY (owner's split re-scoped): in-node untouched stays RIGHT; cross-node treatment =
LINE-VOLUME REDUCTION (cxmsg header, cxreply compaction — the held bandwidth reducers are the
real cross-node content), NOT prefetch. Multi-CCD exposure = interconnect bandwidth, not per-op
latency. KEEP cxxnode's emulation half (tomokv-sim-xnode + lines_flushed witness) as the pricing
rig for any future cross-node candidate; prefetch half not merged. Branch codex-cxxnode kept.
