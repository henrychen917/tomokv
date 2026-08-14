---
name: thredis-xshard-universal
description: "Universal cross-shard executor on 2s fork — branch state, validated fixes (CLOSE_ASAP must launch HOP2), registry next, harness wait-bug lesson"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Branch `2s-crossshard-dev` in THredis-v13-2s (2s fork), work journal = overnight_sweep/selfimprove/journal2.md,
design = overnight_sweep/selfimprove/UNIVERSAL_XSHARD_PLAN.md (9 steps).

*** SHIPPED TO STABLE @ 2026-07-19: origin/stable == 2s-crossshard-dev == HEAD fb8bf05b9. ***
FINAL GATE (user "review bench stress if good then push") CLOSED @ fb8bf05b9. The three prior-
DEFERRED cleanup findings are now RESOLVED per user "implement 1 2, get rid of 3 nob thingy":
  #1 xxh64-once on migration dispatch — IMPLEMENTED (dispatchTwoHop computes src bucket once, re-
     reads ex_bucket_table[bkt] after the hold) @ 072a6ce40. Routing-regression risk mitigated by
     the full same-shard/migration edge battery; zero review findings on the routing change.
  #2 SINTERCARD/ZINTERCARD early-stop — IMPLEMENTED @ 072a6ce40, then review-refined @ fb8bf05b9:
     csInterCardLimited drives the outer scan off the SMALLEST gathered set (not setmem[0]) so scan
     is bounded by min|set| and LIMIT early-stop is maximal. Validated 25/25 count-correctness edges
     (full/limit</=/>|X|/0/disjoint/missing/big-vs-tiny/3-set), SINTER↔SINTERCARD consistent.
  #3 reshard-heat-aware inert knob — REMOVED (was never wired): dropped server.h field +
     config.c row (tomokv-reshard-heat-aware). Real heat-aware direct-move stays a future feature.
Codecov CI removed @ 8b5224bd2 (inherited workflow, can't pass on the sharded fork; make lcov/runtest).
STRESS/CORRUPTION VERDICT: 0/200 canary corruption under heavy cross-shard churn (RENAMENX/COPY/
SMOVE/LMOVE/SINTERCARD/ZINTERCARD) + concurrent memtier load, server PONG-alive, crash=0. The
earlier stress "canary md5 flip" was NOT corruption — it was GETs timing out DURING the wedge.
THE "WEDGE" = MISNAMED. CHARACTERIZED @ 2026-07-19 (stall_char.sh, 5 trials concurrent xshard churn
+ 80-conn kill-9 storm): it is a TRANSIENT mass-teardown STALL, not a permanent livelock — recovery
0s×4, 7s×1, NEVER permanent, crash=0, no client/dbsize leak. Root cause = synchronous back-pressured
dispatch: exDispatchPush (server.c:1981) spins the IO event loop when a worker's SPSC queue
saturates under the storm; workers sit on separate cores + reply via lock-free CDB bit-sets (never
block on the IO thread), so the spin ALWAYS terminates and the server ALWAYS recovers. NO circular
deadlock, NO O(n²) in teardown (freeClientsInAsyncFreeQueue clears CLOSE_ASAP before freeClient to
skip its redundant listSearchKey). freeClientsInAsyncFreeQueue is a single pass that `continue`s
past PROTECTED/EX_PENDING (not a spin) — the name "livelock" is wrong. The dropped-dispatch
permanent-wedge variant is ALREADY FIXED on 2s (exDispatchPush = ee451 2s-dispatch-fix port of
8a5b104515; no fake ever dropped). CONFIRMED orthogonal to #1/#2: A/B kill-storm (wedge_ab.sh) had
current tip == pre-#1 baseline (both RECOVERED). *** THE 43h "WEDGE" WAS THE HARNESS, NOT THE SERVER
*** — bare `wait` (no args) in a script that backgrounds the server waits on the server job forever;
that + orphaned memtier children (timeout wrapper killed, child left blocked on the stalled server)
froze the diagnostic 43h while the server itself was fine. Fixed the 3 repo harnesses that had the
bare-`wait` pattern @ 429861388 (hotkey_stress/setop_churn/bench/feature_sweep -> wait on explicit
PIDs). A PROPER server fix = non-blocking dispatch (stall the client instead of spinning the IO
thread) = hot-path architectural surgery on the reply-ordering-critical path; DEFERRED to the planned
big refactor rather than destabilize the base pre-fork. Prior "shipped @ 8643501da" history:
PLAN COMPLETE + MERGED @ 2026-07-17: auto-controllers 4dca38eb6 + reshard-better 809348bd1 merges
(one trivial union conflict; validate x2 green, controllers -1=auto ACTIVE; A/B vs premerge dead
wash -0.09%; reshard forced-test identical to branch record). The two source branches also pushed.
Older detail below.
STRESS CAMPAIGN (post-push, journal2 2026-07-17): auto-controllers + reshard both stress-clean
(canaries/kill-storms/ASAN zero findings incl. live migration under ASAN). KEY RESULTS: reshard
hardening PROVEN under real skew at reachable bar — legacy 3/2 fires w/ ping-pong vs new EXACTLY
1/round, equal-or-better tp; auto bar conservative (won't fire at 1.2x — by design); hot-KEY heat
can't be flattened by bucket moves (heat-aware direct move is the deferred fix). Controllers:
small-value neutral ±1% (8 paired); 16KB phase INCONCLUSIVE — fresh-boot variance 56-83k ops/s
sign-flips any knob effect (controlled fixed-op-count design needed; Threadripper list). Gotcha
for future harnesses: shard heat needs a TINY hot key set (gaussian ranges hash-spread to ~1.0x).
Harnesses: auto_stress.sh + reshard_stress.sh (both ASAN=1-capable).
REVIEW SESSION (2026-07-17, post-push) FOUND+FIXED+PUSHED a SILENT DATA-LOSS bug (commit 5bf1c912f,
19 ahead origin/stable): same-shard fast path of 2-hop conditional moves (RENAME/RENAMENX/COPY/SMOVE/
LMOVE/RPOPLPUSH) ran the real proc via csSubExec, bypassing exExecFake's migCaptureEffect(:12197) +
the DRAINING hold => in-range write during COPYING lost at CLEANUP. Fix: dispatchTwoHop gates the
fast path with !mig_in_range (migration_active && key-bucket-in-range) => forces the 2-hop path which
holds+captures. Validated migbug3 20/20 + ASAN clean + full battery. Harness now in repo:
harness/mig/xshard_migsafe_test.sh. CODE REVIEW (workflow, max, 26 agents) COMPLETED + FIXED + PUSHED (commit 0c52842bc, 20 ahead of
origin/stable): found 13 (7 correctness incl. 2 REGRESSIONS from my first mig-safety fix). All
reproduced then fixed. DESIGN PIVOT: force-same-shard->2-hop was WRONG (2-hop mishandles samekey);
correct fix = keep same-shard real-proc fast path + make it mig-safe (hold+capture via
csCaptureMoveKeys), gate `!(src_in^dst_in)` routes SPLIT pairs to 2-hop. Fixes: #0 SMOVE-samekey
data-loss, #1 pre-hold stale-shard routing, #2 COPY DB=current decoy-loss (copy_has_db forces
2-hop), #3 int16 key_argi->int32 (LMPOP crash), #4 COPY-samekey wrong-reply, #5 express-slim fixed
mode inert (fold gate ==-1 -> !=0), #6 RESETSTAT EWMA underflow (rebaseline guard). Validated:
migbug3 24/24 + gather 16/16 + full battery + ASAN(migbug3/step4/step8) all clean. 6 cleanup
findings DEFERRED (dead state #9/#10/#11, BITOP byte-loop #7, SINTERCARD materialize #8, heat-aware
inert-knob #12). REVIEW-SESSION LESSON: independent review caught 2 regressions my own validation
missed (I hadn't tested samekey SMOVE/COPY under migration) — samekey + migration is the sharp edge.
RE-REVIEW (focused, of the fix commit 0c52842bc) caught a THIRD regression => commit 1c8a7c660 (21
ahead of origin/stable): COPY k k DB <current> on the 2-hop path lacked the same-object guard
(replied :0, or REPLACE rewrote the key). Fix: detect same-object (same key AND dest-db==src-db) at
DISPATCH (pre-HOP1) => CS_ERR_SAMEOBJ; csH1DumpKey no longer clobbers a pre-set err (missing-key
same-object also errors); reassemble emits sameobjecterr. Can't fix via real proc: copyCommand with
a DB option captures src=c->db(shard) before selectDb, dst after (decoy) => src!=dst, its own guard
never fires. Validated 8 COPY edges + battery + ASAN. DEEPER LESSON: iterating fixes in this
migration/same-shard routing area is regression-prone (3 rounds of review each found a new edge);
each fix needs the FULL edge matrix (samekey × DB-option × missing-key × migration × split-fate).
Split-fate test = xshard_migsafe_split_test.sh (bucket-striping: src [0,512) migrates, dst
[512,1024) stays). 6 cleanup findings from the first review still DEFERRED (dead state, BITOP
byte-loop, SINTERCARD materialize, heat-aware inert knob) + re-review's redundant-xxh64-rehash. Bench-methodology review: merge-neutrality A/B is single-regime (64B, cache-
resident) — narrower than the DB-size-sweep+large-value standard, but merge only touches control-
plane so neutrality holds; flagged for Threadripper controlled re-measure (also the 16KB-controller
variance item). HARNESS TRAPS (recurring, now in journal2): inline compound Bash has set -e/pipefail
=> aborts before boot (looks like server crash); /tmp clobbered by parallel bg jobs => use
$CLAUDE_JOB_DIR/tmp; DEBUG RESHARD START instant w/o traffic (use scan_done+CUTOVER for windows);
migration tests must restart server per case (routing carryover). Session-2 commits: 7ab8fff6f fix batch | 0046aa149 registry+allowlist |
8db12728a s4 RENAMENX/COPY/SMOVE | e32a666cc s5 S*STORE+SINTERCARD | 3d864b972 s6 Z-family |
2f5b50324 s7 BITOP/PF (register-level stock parity: both 499 on identical seed) | 41a5bc479 s8
LMOVE/RPOPLPUSH/MSETNX+B (block_reject forces two-hop — real proc would PARK a worker fake) |
483299c3f s9 L/ZMPOP+B (HOP2 = REAL single-key proc on rewritten argv => byte-exact splice).
The ORIGINAL 21-cmd blocklist is FULLY PORTED. Permanent guard set (loud -ERR): geo, SORT
BY/GET/STORE, EVAL-with-keys, LCS, ZRANGESTORE, BLPOP/BRPOP, XREAD, MIGRATE, BZPOPMIN/MAX, MSETEX.
Reject-when-would-block converged 3x: would-block == empty == timed-out form (nil/nullarray) =>
zero special reassembly. Harnesses xshard_step{4..9}_test.sh all ASAN=1-capable; guard harness
sections A(permanent)/B2-B7. All numbers stock-verified or wire-verified per sanity-gate.
FOLLOW-UPS (not started): port to 3s/pool fork (canonical-forks rule: shared fixes -> BOTH);
cross-shard perf pass on Threadripper; step-4..9 cmds under migration/reshard stress (mig holds
wired but only RENAME migration-tested); EVAL keyless + XREADGROUP-via-xread audit note. Commits this session: 7ab8fff6f fix batch | 0046aa149 registry | 8db12728a step4
RENAMENX/COPY/SMOVE | e32a666cc step5 S*STORE+SINTERCARD (+2 latent bugs: gather h2_pexpireat=0
epoch-expire, posmap teardown bound) | 3d864b972 step6 Z-family (zscore parallel arrays, csZAggr
stock-NaN-exact: UNION zeroes every contribution, INTER only first; skiplist temp = stock reply
order; store dumps AFTER listpack-convert, proven by DUMP-parity vs ZADD ref; OBJECT ENCODING is
decoy-inline = unusable under sharding). Harnesses xshard_step{4,5,6}_test.sh (ASAN=1-capable,
alive-probe retries 15s — two "stress alive" flakes were the PRE-EXISTING freeClientsInAsyncFree-
Queue mass-teardown stall, server alive seconds later). 11 cmds guarded; NEXT step 7 = BITOP/
PFCOUNT-multi/PFMERGE (mget_vals string-gather reuse), then 8 LMOVE/MSETNX, 9 L/ZMPOP+blocking
(reject-when-would-block). NEW: 0046aa149 = per-command REGISTRY (Step R): csRegistry[] table drives classify/
dispatch/SAFE-GATE; gate INVERTED to allowlist (TOMO_R_XGUARD; caught MSETEX+bzpopmin/max as
unguarded strays); csLaunchHop2 generalized to row-stamped g->h2sub[] plan, csHopCommit holds the
pending->phase->bit-clear->push protocol; spec = selfimprove/XSHARD_REGISTRY_SPEC.md (steps 5-9
future rows pre-designed there). 8db12728a = STEP 4: RENAMENX (probe-NX, dump-without-delete H4) /
COPY (check-at-write NX; stock copyCommand derefs server.db+n for DB option ⇒ cross-db FORCED
two-hop, never raw proc on worker) / SMOVE (5-bit probe verdict, stock precedence) — 52-check
matrix ×2 (normal+ASAN) zero findings. New harness: selfimprove/xshard_step4_test.sh (ASAN=1 mode);
guard harness updated (3 cmds must-WORK now). 22 cmds still guarded (steps 5-9: *STORE/SINTERCARD,
Z-ops, BITOP/PF, LMOVE/MSETNX, L/ZMPOP).

Earlier state @ 2026-07-17 (session 1), 7ab8fff6f:
- DONE+validated: MGET coalesce (2.3x k=32), SAFE-GATE (21 unported multi-key cmds reject instead of
  silent decoy corruption; argc-dependent: SORT BY/GET/STORE + geo), SETOP coalesce, MSET-move (wash,
  default off), csBuildCoalescedSubs shared builder, 2-hop phase machine + cross-shard RENAME
  (DUMP+delete→RESTORE, HFE field-TTL + stream-IDMP re-registered on dst), CLOSE_ASAP-mid-2-hop fix.
- KEY RESOLUTION (supersedes plan's original): CLOSE_ASAP teardown MUST still launch HOP2 when a
  mutating HOP1 committed (RENAME src already deleted ⇒ skipping = half-applied write/data loss).
  Head stays in flight; later pass (phase!=HOP1) frees via csReassemble(NULL,...). Validated: 12k
  cross-shard RENAMEs under 64kb obuf ⇒ exact dbsize conservation.
- NEXT (user direction): formalize parse+gather into a per-command registry (allowlist inversion of
  SAFE-GATE, generalize csLaunchHop2 off head->argv[2] via g->h2_*), then steps 4-9 ports
  (RENAMENX/COPY/SMOVE, *STORE, Z-ops, BITOP/PF, LMOVE/MSETNX, L/ZMPOP reject-when-would-block).
- csSubExec + csReassemble stay switches (hot path + S8 audit locality) — resolved, don't relitigate.

Harness lessons (cost a session): bare `wait` in a script that backgrounds the server waits on the
server too ⇒ eternal hang that looks like a wedge. Wait on explicit pipe PIDs; timeout-wrap post-checks.
~400% idle CPU at io4ex4 = 4 ex workers spinning SPSC queues = NORMAL (IO threads 0%), not a wedge.
The full-validate "TOTAL FAIL indicators: 4" is a known grep false-positive (MGET GET-of-list-key
semantic lines); authoritative check is per-suite "A/B fails=0".

Related: [[thredis-v7-cross-shard]] [[thredis-s8-two-reply-release-paths]] [[thredis-v8d-migration-validated]]
[[thredis-canonical-forks-and-dfly-port]] [[thredis-sanity-gate-benching]]
