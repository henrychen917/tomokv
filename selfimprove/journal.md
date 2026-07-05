# Self-Improvement Journal
Deadline: 2026-07-06 12:30 UTC (20:30 TW). Start: after v1.6 connmig commits.

## Running tally (per-fork cumulative kept-edit delta)
- 2s static: (pending)
- 3s static: (pending)
- 2s auto:   (pending)
- 3s auto:   (pending)

---
## PASS 1 READERS | 2s-static | regions 1+2 (parse/dispatch) | 2026-07-05 ~11:30 UTC
Candidates stashed: pass1_candidates.json. Headliners (est=win):
 P1: per-io-thread pendingCommand FREELIST — shared pool hard-disabled w/ io threads => hot path
     pays 2 zmalloc + ~144B memset + 2 zfree PER COMMAND; freelist indexed by freeing iotid is
     race-free (deferred frees run on owner). 4 allocator calls/op removable.
 P2: intern table carries resolved redisCommand* — preprocessCommand's second identification
     (strcasecmp fast path / siphash dictFetchValue on reuse-miss) is 100% redundant post-intern.
     Guard: rebuild on rename-command/module reg; skip subcommand cmds.
 Others: querybuf_len reuse in memchr bound (oversight), opt_operand_pool+CLIENT_MASTER per-arg
 hoists, input_bytes accounting gated on cluster_enabled (dead work single-node), reploff base
 hoist, operand-pool demand-grow (speculative — verify exhaustion first).
APPLIER: pending (v1.6 owns box). PASS 2 READERS launched (regions 3+4 exec/drain).
## PASS 2 READERS | 2s-static | regions 3+4 (exec/drain) | 2026-07-05 ~11:45 UTC
Stashed: pass2_candidates.json. Headliners:
 E1 (win): STRUCT-stage prefetch coverage gap — prefetch fake->db identity line + write-intent
     bufpos/buf in PFS_STRUCT (cross-core S3-class, gate-open regime only; ride w1a width).
 E2: exExecFake release-loop reshape — hoist av/ac locals, REGISTER mask accumulation w/ single
     UNCONDITIONAL store (the safe shape learned from edit-1's mispredict lesson), skip a=0.
 D1: drain-specialized splice — hoist per-fake _prepareClientToWrite + obuf-limit checks to
     once-per-client-per-pass (dst=real fixed across the ring walk).
 Others: vsize EWMA per-batch not per-op, sentinel-test collapse to cold helper, nextop/migration
 per-batch hoists, current_client TLS store dedup (speculative).
Applier queue now ~10 items across regions 1-4. HOLDING further readers until applier catches up
(read-ahead beyond one pass risks stale candidates as edits land). v1.6 still owns box.
## WAVE 3 | broad (user: max token utilization) | 2026-07-05 ~12:00 UTC
Launched 7-agent box-free wave: readers regions 5(teardown)/6(serialize)/7(SPSC)/9(3s-wb) +
ADVERSARIAL VERIFIERS on the 3 win-class candidates (pcmd freelist / intern-cmd-ptr / STRUCT-pf gap)
so the serial applier only spends box time on verified mechanisms. v1.6 in VALIDATION phase (agent
active 04:52). Box-serial rule unchanged for benches.
## WAVE 3 RESULTS + v1.6 LANDED | 2026-07-05 ~13:10 UTC
- v1.6 conn-migration COMMITTED+PUSHED (2be20398d): ~864 live migrations + io-exit, 0 loss/order
  violations, 9/9 array audit. Auto improve worktrees created (2s/3s-auto-improve-dev).
- VERIFIER VERDICTS (all 3 win-class CONFIRMED): freelist TRUE (amend: tcache moderates, expect
  1-4% — A/B arbitrates); intern-cmd-ptr TRUE (amend: sentinel stale-ptr trap — second-pass fill;
  + 3 more mutation points); struct-pf TRUE (amend: prefetch_write(fake->buf) must stage the
  pointer load or it's a dependent-load no-op; offsets verified by gdb).
- NEW CANDIDATES: serialize rank-1 fused bulk-reply emission (WIN-class: 3 fragment passes -> 1,
  kills 2/3 per-reply fixed overhead); SPSC staged-dirty bitmap (flush skips clean workers);
  teardown extras (inline getKeysFreeResult, flag-chain collapse); 3s-wb idle early-out.
  All stashed: wave3_candidates.json.
- APPLIER (wvzh15oij) RUNNING on the box: pass-1+2 items, mechanicals first then structurals.
  Queue for applier-2: fused-bulk, SPSC bitmap, teardown extras (+ amendments from verifiers).
## WAVE 4 | auto control-plane + 3s portability | 2026-07-05 ~14:00 UTC
TWO REAL v1.6 BUGS found (correctness wins): (1) IO-exit inbox-wedge window (io_exiting cleared at
step-4 not at park-adoption; park guard misses mb->inbox; conn wedges in parked thread's mailbox);
(2) listener never re-bound post-IO-exit -> PARKED->IO re-entry listen(-1) refused + pending-gate
bricks the spare (test 1/5/1 cycle). Also: EWMA-reset single-writer violation (move before target
release-store), dead tm_work_slices/idle_episodes + lying balancer header (signal e), and the FULL
v1.5 EX->IO composition recipe (chained tm_mig_spare_action=3, shared tmExExitDrain, prereq=fix 2).
3s portability map stashed (wave4_findings.json). Fixer workflow launching on 2s-auto-threads-dev.
## APPLIER-1 VERDICTS | 2s-static | 2026-07-05 ~15:15 UTC (53min run, 0 discarded reps)
KEPT: P3 parse-loop hoists (flat+simpler; 68ad5d4d8, PUSHED).
REVERTED w/ evidence: P5 input-bytes gating (-0.78% MIX, branches>ALU on dispatch path); E2
release-reshape (flat, echoes edit-1 drop); E5 nextop hoist (-1.0% GET consistent — live-value
spill across opaque proc calls); P1 pcmd FREELIST (flat standard, -0.87% write-heavy — verifier's
tcache amendment EXACTLY right); P2 intern-cmd-ptr (dead flat even on alternating 1:1 — command ID
is off the critical path; revisit io-thread-bound topologies); E1 STRUCT-pf (+0.47% ALL reps
positive but < +1.5% bar; single-CCD mutes cross-core mechanism -> THREADRIPPER LIST).
CROSS-CUTTING LESSON (redirects loop): 32B io4ex4 = dispatch/express-lane bound; allocator lever
gone under jemalloc; worker-side + teardown shaves can't measure there. New targeting: (a) io-side
work in the dispatch path itself (SPSC flush = io-side! dirty bitmap candidate), (b) 3s fork
(different constraints: wb/send), (c) non-32B regimes for reply-path candidates, (d) correctness/
simplify work (bench-independent).
SIDE-FINDING (pre-existing BUG): MULTI/EXEC does not commit under io4ex4 — EXEC keys never appear,
reproduced on frozen baseline. Investigation queued.
THREADRIPPER LIST (started): E1 struct-pf; P2 intern-cmd-ptr (io-bound topologies); decref-bounce.
## v1.6 BUGFIXES LANDED | 2s-auto-threads-dev | 2026-07-05 ~15:50 UTC
5 commits pushed (654a5125c tip): inbox-wedge closed (io_exiting atomic, held through park adoption,
inbox_n in park guard, tmMigExpelInbox for stranded conns); THIRD wedge found+fixed by the fixer
itself (exiting thread blocked in epoll_wait -> park checkpoint never ran -> "transition pending"
brick; fix: self-kick own mailbox notifier — exit+park now land same millisecond); listener re-bind
on PARKED->IO re-entry (the 1/5/1 brick, with rollback-not-wedge on bind failure); EWMA-reset
single-writer fix; dead signal fields deleted + balancer header doc corrected.
Smoke: 3 full exit/park cycles, 0 conn errors. IN FLIGHT: applier-2 + MULTI/EXEC investigation.
## WAVE 5 | ae/boot readers + SPSC verify | 2026-07-05 ~16:45 UTC
Stashed wave5_findings.json. HEADLINERS:
 AE-1 (win): ADAPTIVE DRAIN — fixed 100us poll while replyWorking>0 is THE low-pipeline latency
   floor (workers finish in 1-5us); zero-timeout drain passes w/ numeric spin knob. Target: P1 cell.
 AE-2 (win): LAZY EPOLLOUT REMOVAL — send-bound streaming pays 2 epoll_ctl/reply; lazy delete on
   first spurious event = 0 syscalls steady-state. Target: 16KB GET cell. SYSCALL-class (proven).
 BOOT-1 (BUG, mine): exBindNumaLocal gate says pin_mode!=1 return — my pin remap flipped comments
   to auto(==2) but MISSED the function gate. NUMA bind currently manual-only. Zero impact 1-node;
   wrong on Threadripper. Fix on improve branches; NOTE FOR USER: canonical cherry-pick decision
   (it's in shipped stable/3-stage via the config-overhaul commit).
 Also: beforeSleepIO early-out bundle + dead aftersleep registration delete; per-client cdb set
 (multi-cdb only); timer-walk cache (iotid0). Applier-3 queue: AE-1 (P1 cell), AE-2 (16KB cell),
 beforeSleep bundle (GET32), SPSC bitmap per verify verdict.
## APPLIER-2 PARTIAL + MULTIBUG REPORT | 2026-07-05 ~17:25 UTC
Applier-2 HUNG mid-fused-bulk (Bash call never returned, 55min; workflow TaskStop'd; tree reset to
last keep). KEPT (pushed): W3-T2 inline getKeysFreeResult; W3-T3 flag-chain collapse. SPSC bitmap:
no commit (assume reverted or unattempted — RE-QUEUE with verify-confirmed ordering argument).
MULTIBUG REPORT (selfimprove/multibug_report.md): CRITICAL — MULTI/EXEC acknowledged-then-lost
writes + broken WATCH CAS under sharding. USER DECISION NEEDED on fix option at return.
Applier-3 queue: fused-bulk (retry w/ hard timeouts), SPSC bitmap, AE-1 adaptive drain (P1 cell),
AE-2 lazy EPOLLOUT (16KB cell), beforeSleep bundle, pin-gate fix (mine), then 3s pass.
## APPLIER-3 VERDICTS | 2s-improve-dev | 2026-07-05 ~08:45 UTC (hard-timeout protocol, 0 hangs)
KEPT (3 commits, tip 516dcc58d, NOT pushed):
 AE-1 ADAPTIVE DRAIN (d9602d936): P1 cell +2.61% ops median (lat 0.0707->0.0687ms), GET32 -0.12%/
   MIX32 +0.97% flat. Knob tomokv-io-drain-spin (default 32, 0=off), ae.c global mirror (redis-cli
   links ae.o). The 100us floor WAS real — first P-cell win of the loop.
 W5-B1 PIN-GATE BUGFIX (fae4fb4de): exBindNumaLocal gate !=1 -> !=2 + sched_getcpu() node (smart-map
   only as fallback). Auto mode now actually NUMA-binds; manual no longer mis-binds. USER: same bug
   shipped in canonical stable/3-stage (config-overhaul commit) — cherry-pick decision pending.
 MULTI/WATCH GATE (516dcc58d, FLAGGED user decision option 1/3): num_workers>0 rejects MULTI/WATCH
   loudly (RP-1 style). io4ex0 transactions still work. Pre-existing CONFIRMED on frozen base:
   io4/ex0 EXISTS SEGFAULTS (finding-B express-lane, worse than the known GET/SET wedge).
REVERTED w/ evidence:
 AE-2 LAZY EPOLLOUT: 16KB target -0.41% (tight reps) — loopback 16KB is memcpy-bound (~8.6GB/s),
   epoll_ctl pair not on critical path. Full safety audit done (unbind/protect/barrier/CAR all safe)
   — cheap to resurrect on real NIC. THREADRIPPER LIST.
 SPSC DIRTY BITMAP: GET32 +0.54%/MIX32 -0.64% wash at nw=4 (walk is 4 queues; early-out scales with
   nw). Mechanism verify-confirmed + MGET/FLUSHALL/burst smoke clean. THREADRIPPER LIST (nw>=16).
 FUSED BULK-REPLY: GET32 +0.68%/MIX +0.25%/GET512 -0.04% — wire-format proven byte-exact (raw RESP
   compare), but reply serialization runs on WORKERS: io4ex4 is dispatch-bound, worker-side shaves
   unmeasurable (applier-1 lesson re-confirmed). Try on io-bound topologies / 3s WB path.
 BEFORESLEEP BUNDLE: behavior-neutral by construction, but MIX32 -2.35%/-2.41% in TWO independent
   3-rep windows (GET32 +0.7 both) incl. a branch-free reshape — can't certify the -1% floor; MIX32
   cell shows ~4.6%% cand-side spread today (noisiest cell; candidates for it need bigger effects or
   more reps). Bundle parts are trivially safe to fold into a future measured win.
SIDE-FINDING (pre-existing, base reproduces): OBJECT ENCODING returns EMPTY (not error) under io4ex4
 — decoy/inline family, adjacent to multibug finding A.
## APPLIER-3 VERDICTS | 2026-07-05 ~18:40 UTC (69min, 0 hangs, 0 discards)
KEPT: AE-1 adaptive drain (+2.61% P1, lat 0.0707->0.0687ms; knob tomokv-io-drain-spin d9602d936);
pin-gate bugfix (fae4fb4de — USER NOTE: same inverted gate in shipped stable/3-stage, cherry-pick
decision); MULTI/WATCH gate (516dcc58d FLAGGED user-decision, option 1/3).
REVERTED (all evidence-backed, mechanisms preserved for other regimes): AE-2 lazy-epollout (-0.41%
16KB — loopback memcpy-bound; audit passed; REAL-NIC/Threadripper); SPSC bitmap (wash at nw=4;
scales w/ workers — Threadripper nw>=16); fused-bulk (wire-format byte-exact proven; worker-side =
unmeasurable at dispatch-bound io4ex4; candidate for 3s WB); beforeSleep bundle (-2.35% MIX twice —
implausible but protocol wins; parts foldable later).
NEW PRE-EXISTING BUGS (both reproduce on frozen baseline): (1) io4/ex0 EXISTS SEGFAULT — express
lane pushes with zero workers; the documented sharding-off mode CRASHES (my config-overhaul made
ex=0 legal without gating the express lane — in shipped stable!); (2) OBJECT ENCODING returns empty
under io4ex4 (decoy/inline family).
THREADRIPPER LIST NOW: E1 struct-pf, P2 intern-ptr, decref-bounce, AE-2 lazy-epollout, SPSC bitmap
(nw>=16), fused-bulk (WB/io-bound).
## EX0 FIX + 3S PORTS | 2026-07-05 ~20:10 UTC
EX0 BUGFIX (d5a7e4351, pushed): TWO defects one root cause — config overhaul made ex=0 reachable
but (1) dispatch still pushed to nonexistent workers (express=wedge+heap scribble; cross-shard
EXISTS=SEGV in nw=0 coalesce) -> fixed w/ num_workers>0 gates (routing byte ignored at runtime);
(2) all-inline then raced 4 io threads on shared db (rehash assert <5s) -> tomoEx0Lock global
execute mutex ONLY when num_workers==0 (upstream io-threads model: parallel parse, serial execute).
Full smoke both modes. OBJECT ENCODING diagnosed (needs key-position-aware dispatch; documented not
fixed — argv[2] key vs dispatch hashing argv[1]). Residual ex=0 caveats documented (BGSAVE fork,
BLPOP untested). USER NOTES accumulating: shipped stable carries ex0 bug + pin-gate bug (cherry-pick
decisions on return).
3S APPLIER mid-run: P3/W3-T2/W3-T3 ports committed (e8645728b/03f9ee001/4d8657117); wb early-out +
AE-1 port + gates remaining.
## APPLIER-3S VERDICTS | 3s-improve-dev | 2026-07-05 ~09:25 UTC (hard-timeout protocol, 0 hangs)
Tip 8b9636145 (6 commits on b113b836, NOT pushed), tree clean, port 6399 freed. Harness:
ab3s_lib/std/p1.sh (3s strict ifid3/ex3/wb2; baseline gate tightened after a pollution incident —
see below). Cells: MIX32 + GET512-wb (std), P1 t2c8.
KEPT (5 commits):
 P3 PARSE HOISTS port (e8645728b): querybuf_len memchr + is_master local; pool-knob hoist N/A
   (3s pool hardwired; stale comment fixed). Pooled 6-rep medians MIX -0.20% / GET512 +0.95% = flat
   +simpler (single windows swung -2.3%/+2.3% — this cell needs paired windows for small effects).
 W3-T2 inline getKeysFreeResult (03f9ee001) + W3-T3 flag-chain collapse (4d8657117): one combined
   window (disjoint files) MIX -1.40% / GET512 +0.49% = flat+simpler. REPLY SKIP wire bytes proven
   identical to frozen base (the +OK-under-SKIP quirk is PRE-EXISTING decoy-family behavior).
 AE-1 ADAPTIVE DRAIN port (640121eb8): P1 cell +4.66% ops median (lat 0.0680->0.0651ms), guards
   MIX -0.47% / GET512 +3.30% (all reps ahead). 3s note: strict ifid>=1 never bumps replyWorking
   (WB sends), so the drain covers the ifidx-0 legacy path + markStalled ring-full path — commented
   in ae.c. Bigger win than 2s (+2.61%).
 PIN-GATE bugfix port (66b256b6f): !=1 -> !=2 + sched_getcpu; smoke = 3 NUMA-local lines in auto.
 MULTI/WATCH gate port (8b9636145, FLAGGED user decision): loud -ERR verified; UNWATCH/EXEC-err/
   normal ops intact.
REVERTED w/ evidence:
 3S-WB IDLE EARLY-OUT (wave3 wb3s rank-1): MIX32 -3.03% median (2/3 reps behind), GET512 (target!)
   -0.92% mixed. Mechanism analysis: at t10c20 P16/P32 saturation every watched client almost always
   has in-flight work -> early-out rarely fires and adds reads on the active path; auto num_cdb=1 on
   this single-CCD box makes the skipped mask snapshot ONE load. THREADRIPPER LIST (multi-CDB
   num_cdb=num_workers + idle-heavy connection counts is where the O(conn x num_cdb) claim lives).
FINAL CUMULATIVE (tip vs frozen base): MIX32 -1.48% (mixed signs, in-noise), GET512 +3.65% (cand
ahead ALL 3 reps; third consecutive positive GET512 window post-AE-1 — the 3s differentiator cell
is the cumulative winner).
HARNESS INCIDENT (sanity-gate win): one window showed GET512 +23.18% — implausible for a parse
hoist; baseline g512 had drifted 1.41M->2.29M across reps (transient box pollution right after a
build; base runs first each rep). STOPPED, verified box idle, tightened ab3s_std gates to baseline
plausibility (MIX>=4.4e6, g512>=1.9e6), re-benched clean. Rule held: never reason from a bad number.
## 3S APPLIER VERDICTS | 2026-07-05 ~20:50 UTC (60min, 0 hangs)
KEPT: P3 port (e8645728b flat+simpler), W3-T2 (03f9ee001), W3-T3 (4d8657117), AE-1 DRAIN PORT
(640121eb8 — WIN: +4.66% P1 [236->247K, lat 0.0680->0.0651ms] AND +3.30% GET512 all-reps-ahead;
3s benefits MORE than 2s), pin-gate port (66b256b6f), MULTI gate port (tip 8b9636145).
REVERTED: 3s-wb idle early-out (-3.03% MIX; fires rarely at saturation + num_cdb=1 makes skip
worthless here; needs multi-CDB + idle-heavy conns -> THREADRIPPER).
NEXT: auto-fork baselines + auto applier (port all keeps; knob-off must equal static).
## AUTO PROPAGATION + STALL RECOVERY | 2026-07-05 ~21:45 UTC
Propagation agents stalled post-picks (idle box, 30+min silent) -> TaskStop'd; ALL pick chains had
landed: 2s-auto tip d6a039688 (canonical v1.6-fix merge + P3/W3T2/W3T3/AE-1/pin/MULTI/ex0 = 7 picks),
3s-auto tip 397ba796b (P3/W3T2/W3T3/AE-1/pin/MULTI = 6 picks). Both branches PUSHED; baselines
base_2s_auto/base_3s_auto frozen. Final validation workflow launched (wc8fafgus): 2s-auto knob-off
equivalence + P1 AE-1 check + knob-on shift smoke + ex0 mode; 3s-auto strict smoke + shift cycle.
After validation -> wind-down window (FINAL_REPORT.md + backup refresh) is authorized any time;
re-read waves only if validation lands cleanly with time to spare.
## WAVE 6 RESULTS + FIX BATCH LAUNCHED | 2026-07-06 ~00:00 UTC
NOT DRY — 6 win-class correctness items: (default-on) HFE whole-key deletes bypass effect capture
[tombstone hole]; DRAINING-window lazy-expire gap; RP-1 runtime arming bypass (CONFIG SET
appendonly/PSYNC evade boot gates); (3s) pool PUT files ANY >=64B alloc into top tier (512MB values
poolable = RSS hazard); (default-off uring) recv ownership-handshake bypass, uncancelled multishot
= silent byte loss on migration, EINTR CQE abandonment (reply wedge + UAF, AMPLIFIED by AE-1
drain). + AE-1 follow-on candidate (drain refresh on REPLY progress, P4-P16 mechanism) + ZC
real-NIC design flag for EPYC + dead-code sweep (ae_uring.c compiled nowhere; v12-K wds remnants
no-op) + drain-dilutes-io-busy% insight for the autothreads AE-1 port (signal interplay documented).
Fixer (6402, both forks) + AE-1 follow-on applier (6399) launched: w4aacaa9a.
