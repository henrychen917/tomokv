---
name: thredis-atomic-window
description: "atomic-write crater SOLVED via admission window (36x, torn=0); root cause = arrival-order frontier convoy; completion-ticketing cure frozen (proved 765k reachable, 4 bug classes)"
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Overnight campaign 2026-08-07 (owner mandate: fix high-write atomic, keep epoch). OUTCOME: SHIPPED on
mset_verepoch (2s-mset-atomicity-verepoch) @ **8ea5b3b60** — full chain now: epoch 4bd68e0b5 → reorder
fixes → knob 0c658c6b1 → +8B 7e1697874 → reclamation 909389964 → admission window ce24a8e65 → **default-256 8ea5b3b60**.

**Root cause of the ~100x atomic-MSET crater (proved by perf + knee sweep, NOT locks):** seqs were
drawn at DISPATCH (arrival order) but publish in-order ⇒ at 6400 in-flight groups the frontier
head-of-line-blocks on stragglers: server 53% IDLE in exSlice, p50 548ms. Frontier collapses
SUPERLINEARLY with window: 200 groups→494k msets/s p50 0.34ms; 800→344k; 1600→96k; 3200→26k;
6400→12k (OFF ~1.1M flat). Three lock fixes (reclamation-out-of-spinlock aside, which is kept) were
NEUTRAL — there was never lock contention (only ~8 server threads touch the commit lock).

**Shipped fix (ADMIS): `tomokv-atomic-window`** int knob, **default 256** (8ea5b3b60; sweep:
96-128 best pure ~690-714k but 256 best ALL-ROUNDER — same-server: pure 586k + mix 309k/2.78M vs
512's 363k/201k; final verify at default: **618k/s sustained 25s**, torn 0, inflight back to 0),
0=unlimited, live-settable,
read only when tomokv-atomic on. At admission ≥window: no group created, command left UNCONSUMED in
qb (no pump — avoids the fa9aca003 re-entrancy class), client marked stalled, retire wakes owners via
notifier FDs. CAS window reservation; single decrement in csReassemble (reply + disconnect paths);
`INFO Stats: tomokv_atomic_inflight` (0 when idle = leak check). GAUNTLET (all green): p32 HOT 200c
**431k/s p50 12.9ms (36x vs 12k)**, p1 572k, torn **0.000% x8**, RYOW 0 (reorder 0+3+churn), 1:9 mix
396k/3.56M, **40s saturated soak 380k/s zero crashes**, OFF GET parity +0.1%.

**Cure branch (2s-atomic-cure, HEAD 1f09c6694, 5 commits) = FROZEN future work.** Completion-order
ticketing (draw seq at install-completion; UNCOMMITTED sentinel; per-conn FIFO R1; owner-applied
stamps) PROVED 712-765k/s p32 with replies flowing and torn=0 at 6-8s scale — the perf thesis is
real. But per-key chains stack in INSTALL order while seqs are completion-order ⇒ inversion repairs
spawned 4 failure classes in sequence: (1) stamps landed on the OPERAND robj not the store kvobj
(embed/replace paths ⇒ torn at OFF-rate), (2) sentinel splice can't sort ⇒ seq-inverted chains ⇒
bimodal whole-rep torn, (3) dup-keys-in-one-MSET (~40%/cmd at ks=64!) same-seq sibling retire ⇒
assert db.c:1069, (4) cross-key completion inversion ⇒ committed-above-unstamped assert db.c:1166;
the relocation repair then crashed immediately + broke writer atomicity (final_state=MIXED). DO NOT
resume without redesigning the per-key version structure to be order-independent.

**Gauntlet lesson:** a liveness-only soak is VACUOUS for this class — the v4 binary "passed" 20s
liveness while a 25s run crashed (assert on a worker; PING can still answer). Soaks must ASSERT
THROUGHPUT (validate_candidate.sh + gauntlet5 pattern: 40s, floor 300k, crashlog grep).

Full narrative: tmp/CAMPAIGN_LOG.md (job fd085c8e). See [[thredis-mset-atomicity-bakeoff]],
[[thredis-reorder-ryow-fix]], [[thredis-vacuous-validation-trap]], [[user-hardcode-or-delete]].

**Dep/lock-aware scheduler verdict (2026-08-07, owner idea, measured):** NO TARGET on the atomic
path — perf cells (ON ks=8/64/100k + OFF ks=8, MSET8 200c p32): csPushSpin 0.14-0.29% ON (0.66%
OFF — window keeps ON queues shallow), sched_yield ~0.05%. Requeue-behind + window already provide
the interleave-while-waiting; execution threads never spin. Atomic throughput is SKEW-INSENSITIVE
(561k/580k/560k hot->cold = window-bound, not contention-bound). The real remaining cost is worker
IDLE 24-34% (the window throttling to protect the fragile frontier) = exactly the slice cure2
reclaims. Idea FILED with the Shinjuku wall ([[thredis-reorder-overhead-and-wall]]).

**CURE2 SHIPPED (2026-08-07 pm, ver @ 70f10ef9f):** the completion-order redesign LANDED on the
append-only-bag structure (CURE2_DESIGN.md invariants I1-I7): chains never reordered (zero
relocation code = cure-v1's 4 bug classes structurally absent); reads resolve argmax(seq,
install_order)<=S; owner stamp lane; promotion I6 strips vmeta on quiesce (INFO
tomokv_atomic_promotions); plain reads resolve via I7 with a DISPATCH READ-HOLD while the conn's own
atomic FIFO is pending (fixes plain-GET/MGET RYOW-after-own-atomic-MSET 100%->0 — a gap the old
tests never covered; shipped-v1 only "passed" via a raw-head dirty-read accident); per-read QSBR pin
made lazy (command-wide pin had collapsed the 1:9 mix 50x). GAUNTLET: p32 637k, **40s soak 672k**
crash-free, torn 0 x8, all RYOW 0, 1:9 306k/2.76M, plainGET 0 quiet+load. Window re-tuned for the
robust frontier: **default 512 -> 770k/s** (sweep 256:747k 512:770k 1024:766k; window=0 STILL
collapses to 85k — bag growth replaces the convoy as the large-window cost, valve stays). 770k =
the full cure ceiling, +25% over the window-only ship (618k), 64x the crater. Cure v1 branch
(2s-atomic-cure) now fully superseded. Broaden REDO running on this base (2s-atomic-broaden2):
tombstone=flagged version resolved absent, removal only inside promotion (no parallel retire feeds
— the class that killed 2s-atomic-broaden x3), MSETNX reservations+cancel via stamp lane.

**BROADEN SHIPPED on the bag structure (2026-08-07 eve, ver @ 5cfcdc38c):** MSETNX/DEL/UNLINK/
EXISTS/TOUCH all atomic under the one tomokv-atomic knob, sharing the window+R1 FIFO+read-hold.
Design that finally worked (after 2s-atomic-broaden died x3 on parallel retire feeds): tombstone =
flagged version the resolver reads as absent; physical removal ONLY inside promotion via stock
dbSyncDelete/flatDelete; MSETNX = flagged reservations + cancel via the stamp lane, CANCELED =
invisible + immediately prune-eligible (one fix-pass: cancel-created-key removal must NOT
SetAtLink(NULL) — kvstore.c:1106 guard — route through promotion like tombstones). GAUNTLET all
green: DEL-vs-MSET all-or-nothing 0/0 x3 (~175k reads/rep) + EXISTS in {0,N}; MSETNX torn 0 x3 +
serial semantics OK + both writers winning; OFF arms tear (gates open); core 628k p32 / 670k 40s
soak crash-free; OFF parity -0.6%. New testers: delmset_torn.py, msetnx_race.py, mset_getryow.py.
SEMANTICS (owner Q&A): per-client strict program order (owner-FIFO + R1 + read-hold); cross-client
ONE total order (commit_seq) respecting ack-before-send causality, concurrent ops ordered by
COMPLETION; visibility instant on ack; plain writes stay outside the frontier (per-key atomic,
batch-blind). Deferred: store-ops (SINTERSTORE family), 2-key RENAME/COPY/SMOVE/LMOVE; preflight
big-gate before any push.

**CURSOR SHIPPED + DEFINITIVE 5x3 MATRIX (2026-08-07 night, ver @ 1d579325a):** the mixed-hot-key
collapse (55% cycles in kvobjVersionAt: bag walk O(uncommitted-prefix)) is FIXED by the per-key
committed-head cursor (a0e52f8b3 O(1) current-snapshot resolve + 1d579325a max-advance/sorted-insert
— stamps can arrive per-key OUT OF ORDER across completing workers; the monotone-arrival assert was
wrong). Plus afa5b86a6 read-hold missed-wake closure. MATRIX (HOT ks=64, t8c25p32, 16B):
  workload      ON       OFF      dfly     ON-vs-dfly
  pure MGET     1.79M    1.80M    1.41M    +27% WIN
  pure MSET     709k     1.12M    866k     -18%
  1:1 MG:MS     167k     1.40M    869k     -81% (read-hold per-conn serialization; alternating = worst case)
  1:1:1:1       1.05M    2.80M    1.03M    +2% WIN
  9:1 MG:MS     868k     1.72M    900k     -4% parity
Correctness col: ON torn 0/RYOW 0/plainGET 0; OFF tears 1.465%; dfly tears 0.145%. Recovery from the
collapse: 1to1 9k->167k (18x), 1111 249k->1.05M (4.2x), 9to1 28k->868k (31x); 40s soak 721k clean.
ON at-or-above Dragonfly on 3/5 workloads WITH the strictly stronger guarantee. Weak spot = 1:1
alternating (future lever: key-overlap bloom filter on the read-hold). OPEN: #100 intermittent wedge
atomic x key-LB reshard cutover (gc_mix evidence, not repro'd clean; MUST resolve before push).
PORTALL (2b8bdcab0, store-family+RENAME/COPY): RENAME/RENAMENX/COPY/BITOP/SUNIONSTORE pass smoke;
SINTERSTORE returns 0 (intersect read path bug) + core ON-perf regression (628k->121k — reintroduced
pin/walk class); fix-pass + rebase onto ver queued.