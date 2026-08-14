---
name: thredis-flip-overhead-decomposed
description: The p32 "flip machinery -14%" is really ~11% convergence TRANSIENT + ~3% steady; mcmd-lock false-sharing fixed; readme gap is unconditional shared-kv drift
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**2026-07-23 — p32 GET deficit fully decomposed (7700X, seeded 2M keys, medians).** Corrects the
earlier "thread-modes+balance = 14% machinery overhead" framing: the 14% is mostly the CONVERGENCE
TRANSIENT, not steady cost.

Decisive measurement (all seeded, same 4/4 boot):
- static 4io/4ex (knobs off): **7.38M**
- all-features CONVERGED & held (settles to 3io/4ex): **7.17M = −2.9%** (steady machinery, 0 flips in window)
- all-features fresh-boot 75s window (= the ablation C/D cell): **6.37M = −13.7%** (probe/reshard transient)
So −14% ≈ **~11% convergence transient + ~3% steady**. On a forever-running server only the 3% matters.
The transient matters for (a) short benchmarks and (b) workload-shift recovery latency ⇒ the real
optimization lever for benchmark optics is FASTER CONVERGENCE (fewer probes), not per-op instrumentation.

**CORRECTION (2026-07-23): `orig-w` is NOT the readme baseline.** Its checked-out commit is
`6ac38651a` (mcmd-lock round-2 review fixes) = a LATE numa-lineage build that ALREADY has
TOMO_BUCKETS=16384 + shared-kv + mcmd-lock. The prior "orig-w = physical-shard @ab5c9d40e" label was
wrong. The TRUE readme/paper baseline is tag/commit **`e39b355ba` (2s-paper-baseline: basic
architecture, defaults only)** = **TOMO_BUCKETS 4096, single-dict, NO shared-keyspace, NO flip
machinery** (2026-07-21); HEAD is **68 commits** past it. So "−4.6% vs orig-w" UNDER-states the true
regression vs the paper baseline (orig-w already carries most of the drift). The readme 7.92M ≈
paper-baseline; HEAD static-4/4 7.35M ⇒ true regression ~−7%, decomposing as ~2.3% SHARED_MT atomics
+ ~2-3% dict granularity (4096→16384, 4× more dict headers/indirection) + struct. Real HEAD-vs-
paper-baseline interleaved measurement PENDING (base-w worktree @e39b355ba).

Ablation decomposition of the −20% "all-features" gap (static 4/4, medians of 3):
- orig-w(6ac38651a, mislabeled) 7.66-7.70M; readme `io4ex4` 7.92M = the PAPER BASELINE (4096-bucket)
- HEAD knobs-OFF 7.29–7.38M = −3.6–4.8% vs orig = **unconditional shared-kv code drift** (16384 dicts,
  SHARED_MT atomics ~2% via wpn=1 cell, struct growth) — this is the "why static < readme 8M" answer
- +mcmd-lock PRE 6.98M → POST-pad 7.36M: **lock false-sharing FIXED**, was −5.4%, now ~1%
- +modes+balance 6.34M: the −14% (now known = transient+3%)

Verified-safe fixes (overhead-review workflows wf_c1b0a6bb / wf_3d0dd62d, gdb+disasm confirmed):
- **F1** exThread false sharing (server.h ~2108): `db` (IO reads per dispatched op) shared a 64B line
  with worker-dirtied w_ewma_vsize/ops_total/tm_*; relocate db to the boot-immutable head line
  (after `thread`). #1 unconditional lever, ~3-6%, trivial. db immutable post-initExThreads.
- **F8** ex_bucket_table uniform fast-path: `_Atomic int table_uniform` =1 at boot, cleared (release)
  in reshardArm before any FLIP write; while set, compute owner arithmetically vs 16KB table load.
- **F9** client-struct tail reorder (extends the staged shared-kv reloc): move off-default feature
  fields (arrival_us/tm_lat_stamp/drain_ack/flush_dbid/flush_async/cssub_idx) to the tail so the
  reply-control cluster refits one line.
- **F4** delete dead value-forwarding residue in lookupKeyReadWithFlags (readFwdMode, 0 live setters).
- **F3** CMD_HFE flag bit vs 10-proc-compare chain; **F5** fold drain_ack/is_flush/csparent → 1 u8 tag.
- REJECTED: F2 feature-mask (verifier: unsafe + ~0% on the target), F7 worker-live byte tables (not on
  the p32 path; helps KEYS/RANDOMKEY only).
Already built into current worktree binary: controller convergence fixes + lock-pad + carry-reuse +
partial struct reorder + prefetch-gate per-worker basis. See [[thredis-shared-kv-never-built]].

**BUCKET-COUNT A/B (2026-07-23, interleaved, 7700X): the regression is the bucketing, not the hot path.**
HEAD@495410d8c built with TOMO_BUCKETS=4096 vs 16384 vs paper-baseline(e39b355ba, 4096), static 4/4
knobs-off, seeded, medians. p32get: head16384 7.05M / head4096 7.37M / base 7.44M. HEAD-4096 vs
HEAD-16384 = +4.6% pure bucket-count win (identical code); head4096 ~= base (within ~1%) => shared-kv
machinery adds only ~1% once bucket count is controlled. p1 (ingress-bound) flat across all three.
CONCLUSION: ~5% p32 regression = ~4.5% bucket granularity (16384 dict headers don't fit L2) + ~1%
machinery; hot path clean. base-vs-readme(7.92M) residual is THERMAL: box heat-soaked (87C, cores
5.16GHz vs 5.4GHz max boost = -4.5%); base corrected to boost ~=7.8M ~= readme. All absolute numbers
today are ~4.5% clock-limited; interleaved/relative are valid.
DECISION: forked `2s-numa-flatstore-dev` @495410d8c to decouple ownership-granularity (fine, O(1)
reshard) from physical dict count (drives locality). Design #3 = ONE concurrent table per node + bucket
as per-entry ownership tag => fine ownership + one warm header + O(1) reshard. Design study wf_7af6b41d
running. Fallback quick win = make TOMO_BUCKETS a RUNTIME knob (banks ~4.5% now). NOTE: battery
(faststress all-types ASAN+normal, fastbench, numa=2, concurrent-all-types, 8h long stress/bench) was
PAUSED to run this bucket A/B; resume on 2s-numa-shared-kv-dev after flatstore direction is set.

**FLATSTORE DESIGN CHOSEN (2026-07-23): user prefers the table (hw-arch-inspired, understands it, fork
exploration).** Design study (wf_7af6b41d) picked GROUP-DICT as lowest-risk, but user chose the
concurrent table. Best table variant = FLATSTORE: ONE per-node open-addressing table replacing 16384
dicts. flatSlot{_Atomic u64 ctrl=[48b hashtag|14b bucket|TOMB|OCCUPIED]; _Atomic kvobj* kv} 16B/slot.
Lock-free GET (linear probe, hash already carried), CAS insert, tombstone+QSBR delete, drain-fence STW
resize (then cooperative). Reshard UNCHANGED O(1) (bucket tag independent of ownership). Attack verdict
VIABLE-WITH-FIXES/hotpath-clean; fixes: (1) loop_seq unconditional bump for QSBR liveness, (2) QSBR
domain must cover non-worker readers, (3) resize fence must quiesce prefetch pipeline. Fork
`2s-numa-flattable-dev` @a2441758e (off Stage 1 load-tracking). Prototype-plan workflow wf_06b94dcf
running. GROUP-DICT (2s-numa-flatstore-dev, Stage 1+2 done) = the fallback.

**GROUP-DICT LOCALITY CURVE (ncurve, p32 GET, static 4/4, interleaved) CONFIRMS the premise:** dict
count 16384->256 buys ~+4-5%: N=16384 7.35M, 4096 7.56M, 1024 7.62M, 256 7.69M, 16 7.72M. Knee ~256-1024.
Proves the regression IS dict-header locality (16384 headers don't fit L2); one-header FLATSTORE gets
>=this. Locality win is real + measured. Branches: 2s-numa-shared-kv-dev(stable, +Stage1 lb),
2s-numa-flatstore-dev(GROUP-DICT S1+S2), 2s-numa-flattable-dev(FLATSTORE, designing), base-w/orig-w(refs).

**FLATSTORE PROTOTYPE (2s-numa-flattable-dev): verified plan + Stage-0 foundation building.**
Design workflow wf_06b94dcf produced a SOUND-WITH-FIXES staged plan (4 fixes: A=delete nulls kv
before tombstone [data-loss], B=resize quiesces reads via worker-side pop gate, C=resize arms through
mig_arm_lock exclusive w/ reshard, D=loop_seq release-bump hoisted out of migration-only + '+3' grace
margin). Stages: 0=lock-free GET/CAS-insert/tomb-delete behind knob thredis-flat-store (default 0),
pre-sized, leak-on-delete; 1=QSBR reclaim (FIX D); 2=fence-rebuild STW resize (FIX B/C); 3=reshard
verify (O(1) flip is table-independent by construction); 4=SCAN/RANDOMKEY cursor; 5=cooperative resize
(EPYC). Kill-criteria: fall back to GROUP-DICT if it doesn't clear vs the mature fallback.
DONE (commit 61339f3cc): flatstore.{h,c} core — flatGet (lock-free probe, acquire ctrl/kv, dictGetKV
decode+key cmp), flatInsert (acq_rel CAS ctrl + release-store kv), flatDelete (FIX A order),
flatOverwrite/IterAll/RandomKeyInRange. ctrl=[48b tag|14b bucket|TOMB|OCCUPIED], 0=EMPTY. Compiles
clean, links. NEXT: kvstore wrappers (KVSTORE_FLAT flag + kvs->flat field + kvstoreDictFindLink/
SetAtLink/Find/Delete branches + kvstoreCreate + the knob) to route real GET/SET/DEL to the table.

**Client-lb unified + flip-correct (stable 7ebff657f, cherry-pickable to forks):** tmPlaceConnDest
replaces round-robin at both conn-distribution sites (IO-EXIT grow-back + inbox-expel) — least-loaded
+ per-batch in-flight, so grow-back spreads load-aware like grow-front's pull. Validated: 7 grow-fronts
+7 grow-backs, 0 errors/aborts, dbsize exact. DEBUG TOMO-IOLOAD added. Branch map: shared-kv-dev(stable:
+Stage1 lb +client-lb), flatstore-dev(GROUP-DICT S1+S2), flattable-dev(FLATSTORE core), base-w/orig-w.

**FLATSTORE STAGE 0 WORKING END-TO-END (2s-numa-flattable-dev, commits 61339f3..584ef9d).**
The lock-free per-node open-addressing table now serves the real path behind thredis-flat-store=1:
GET/SET/DEL/MGET/EXISTS/KEYS/RANDOMKEY all correct single-thread AND under concurrent 4-worker load;
tombstone-reuse works. Six kvstore choke-point wrappers branch to flat ops (Find/FindLink/SetAtLink/
TwoPhaseUnlink/Delete); public helpers dictEncodeStoredKey (masking) + tomoKeyHash; layering kept via
forward-decls. KEYS/RANDOMKEY use flatIterRange/flatRandomKeyInRange (per-worker bucket-range filter).
PERF: standalone GET 7.83M (ABOVE every dict build — head16k 7.05/head4k 7.37/base 7.44 — the one-warm-
header win fully realized), SET 6.0M, MIX 6.96M. ALL-FEATURES-ON (flat+modes+balance+mcmd-lock): 8
flips+28 reshards under load, 0 errors/aborts, dbsize exact => O(1) reshard flip is table-independent
(Stage 3 verified empirically); bench GET 7.30M/SET 5.60M. KNOWN GAPS (Stages 1-2): QSBR (Stage 0 frees
on delete immediately = UAF risk vs lock-free cross-worker readers — adversarial review wf_2474de63
checking), resize (pre-sized 8M slots), SCAN cursor. Adversarial review + full gate in progress.

**CLIENT-LB now triggers like key-lb (584ef9d23):** tmClientBalanceCron @1Hz from serverCron (beside
reshardAutoTune) — within-node, moves minimal conns off a sustained busy-outlier io thread to the
least-loaded, tolerance-band (mean+25%, 3-tick sustain). Plus the load-aware conn placement
(tmPlaceConnDest) cherry-picked from stable. Validated: fired live under load, all-features clean.
Branch map: shared-kv-dev(stable), flatstore-dev(GROUP-DICT), flattable-dev(FLATSTORE+client-lb, the
hw-inspired table the user chose), base-w/orig-w(refs).

**FLATSTORE ADVERSARIAL REVIEW (wf_2474de63) — 6 confirmed, 2 CRITICAL, all fixed (commit 6e920fcfe).**
Happy-path tests missed real crashes: (1) CRIT UNLINK NULL-deref — SetAtLink flat branch derefed kv
before the newItem check, async delete passes kv=NULL. (2) CRIT expires split-brain — expires kvstore
got KVSTORE_FLAT but AddRaw has no flat branch => SET EX + KEEPTTL crashed on assert; fix = expires
stays dict-path (shflags & ~KVSTORE_FLAT), keys-only flat. (3) HIGH unbounded probe loops => infinite
spin if table fills w/ tombstones; now bounded by t->size, insert-full panics. (4/5/6) delete freed old
kvobj inline via keyDestructor(kvs,..) = wrong-signature AND UAF vs lock-free cross-worker readers; now
honors Stage-0 LEAK-on-delete (Stage-1 QSBR reclaims). + async-delete double-count (SetAtLink(NULL) AND
TwoPhaseUnlinkFree both decremented => dbsize negative); SetAtLink(NULL) now null-only. VERIFIED: UNLINK/
DEL-lazyfree/expiry/EX+KEEPTTL/PERSIST correct, dbsize exact, concurrent SET+overwrite+UNLINK churn
survives, 0 errors. LESSON: lock-free + Redis delete/expire paths need adversarial review — the happy
path (SET/GET/sync-DEL) hides the async/TTL crashes.

**SHIP STATE:** flat-store stays OPT-IN (default 0) — Stage-0 leak-on-delete + no-resize + the
cross-worker-reader UAF window (Stage-1 QSBR) mean it's NOT the default execution path yet, but the
code + client-lb ship. Plan: merge flattable-dev -> stable (2s-numa-shared-kv-dev) as canonical (coexist
w/ GROUP-DICT, both opt-in knobs); README table (stable/flip/lb, flat off vs on) pending shipbench2.
Dict-path stable p32get 7.27M/set 4.69M/p1 ~800k; flat standalone GET 7.83M.

**SHIPPED TO STABLE (local, 2026-07-23): flattable merged -> 2s-numa-shared-kv-dev @1cda40221.**
`git merge -X theirs 2s-numa-flattable-dev` (clean, 0 conflicts, 568d31d6d) brought FLATSTORE +
continuous client-lb + all review fixes onto stable; flat-store default OFF (opt-in). README-NUMA
updated w/ FLATSTORE section + numbers + client-lb + storage knob (1cda40221). Merged stable builds,
flat-off+flat-on both correct, MIX 4.5M clean.
SHIP BENCH (7700X all-features converged, dict vs FLAT): p32get 7.39->7.73M (+4.5%), p32set
4.67->5.54M (+18.7%), during-flip 6.40->7.68M (flat holds), during-lb 6.87->7.44M; p1 ~flat/-few%.
REMOTE: origin=github.com:henrychen917/tomokv.git EXISTS -> the outward `git push` + default-branch
change was NOT auto-done (public distribution + repo-config + review found 2 CRITICAL bugs first);
awaiting user confirm on the push + which branch is 'default'. numa-shared-v1 tag is the last pushed.

**FLATSTORE STAGE 1 QSBR COMPLETE (stable @403a47d7c) — the cross-shard-reader safety gate.**
1a delete (704004d70): FIX D loop_seq bumped release EVERY exSlice pass (was migration-only) = the
quiescence signal; flatRetire (Treiber push) -> flatReclaimTable (beforeSleep, main) closes the
retire stack into a batch stamped w/ all workers' loop_seq, frees only after every worker passes
stamp+2. Delete-churn 1M deletes RSS flat ~172MB (was leaking). 1b overwrite (403a47d7c): in-place
overwrite (Path A mutates a LIVE object) DISABLED under flat (forced copy) + dbSetValue QSBR-retires
old. 2.5M overwrites + concurrent cross-shard MGET: RSS stable ~300MB, no crash. So no lock-free
reader can see a freed/mutated value -- delete+overwrite UAF windows closed. This is the correctness
gate for making flat the DEFAULT (deprecating dict), per user's plan.
REMAINING for default-on: Stage 2 online resize (today pre-sized 8M slots=128MB, panics if full) +
adversarial re-review of the QSBR/in-place code. Then flip default + push to origin (still on hold).
User plan: keep optimizing flat -> deprecate dict -> push to default numa branch. Public push NOT done.
