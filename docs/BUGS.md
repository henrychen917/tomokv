# Bug ledger — 2026-07-26/27 session

Every defect found in this session: pre-existing ones, ones I introduced, and false conclusions I
drew and had to retract. Each entry gives the **mechanism**, the **evidence**, the **fix**, and the
**verification that discriminates** (a test shown to fail on a build that still has the defect).

Commits referenced are on `2s-numa-wave-dev`.

---

## A. Pre-existing defects — FOUND AND FIXED

### A1. `EXPIRE` on any collection key kills the server — `7205d6350`
**Reach:** two commands. `SADD s m1` then `EXPIRE s 100` → `Guru Meditation: Not implemented
#object.c:362`, process dies. Any TTL on any list/set/hash/zset/stream under FLATSTORE (the
default whenever a node has >1 worker). Strings unaffected.

**Mechanism:** `setExpireByLink` takes a FLATSTORE lifetime pin (`incrRefCount`) so the old kvobj
allocation outlives a concurrent lock-free reader before QSBR retires it. That pin makes
`val->refcount == 2` inside `kvobjSetEx()`, which dispatches purely on refcount: `refcount==1`
steals the pointer, `STRING+INT` copies, `STRING+RAW` `sdsdup`s — and **anything else panics**.
Crashing stack: `kvobjSetEx ← setExpireByLink ← expireGenericCommand ← exThreadMain`.

**Fix:** `kvobjSetEx`'s 4th argument became a `KVOBJ_SET_*` flag mask; the new
`KVOBJ_SET_MOVE_VALUE` **moves** the value (adopt pointer, NULL the source) instead of panicking,
and `setExpireByLink` passes it exactly when it holds the pin. With `ptr == NULL` the QSBR reclaim's
`decrRefCount` then frees only the shell, which is what the pin existed for.
*Rejected:* duplicating the object (the panic's own comment suggests it) — `EXPIRE bigzset 3600`
would become an O(n) deep copy with 2× transient memory.

**Discriminating test:** the suite's existing `expire-realloc-then-read` stores only **string**
values, so it PASSED the crashing binary — structurally incapable of catching this. Added
`expire-realloc-nonstring`, proven to FAIL on the pre-fix binary and PASS after.

### A2. Same-shard `RENAME` of a collection kills the server — `4172812af`
**Reach:** three commands, both keys in the same 14-bit bucket.

**Mechanism:** identical class to A1 — `renameGenericCommand` pins with `incrRefCount`, but under
FLATSTORE `dbDelete` retires via QSBR instead of dropping the ref synchronously, so
`dbAddInternal` reaches the multi-ref non-string branch.

**Fix:** pass `KVOBJ_SET_MOVE_VALUE` when `kvstoreIsFlat`. The audit of lock-free readers found one
case the A1 argument never enumerated — `objectTypeCompare`'s `OBJ_MODULE` arm, reachable via
`SCAN … TYPE`, the only non-string `ptr` deref in the tree — closed with a NULL guard.

**Discriminating test:** `rename-nonstring-sameshard` *derives* a same-bucket key group from xxh64
rather than hoping for one; FAILs on pristine HEAD and on `pushed_d`, PASSes after. ASAN: 334,400
round-trips + 138,344 concurrent `SCAN … TYPE`, 0 reports — and proven non-vacuous (the same binary
with one live key at exit *does* emit a LeakSanitizer report).

### A3. Cross-shard multi-hop breaks same-client pipeline ordering — `6e9a31304`
**Reach:** 424,867 / 424,867 wrong under load.

**Mechanism:** the fork's ordering rests on *same key ⇒ same owner queue ⇒ FIFO*, which holds only
because subs are pushed from the dispatch loop in client order. Three paths broke it: multi-hop
groups push HOP2's subs **from the drain thread**, after the client's following commands are
already queued; the merge-execution stage chain does the same per stage; and the node-local borrow
had one executor read keys it does not own. Observable result: two pipelined `MSETNX` both returned
1 and a trailing `EXISTS` saw **0 of 6 keys** — a state no serial execution can produce.

SMOVE was never wrong: the same seeded stream at `--batch 1` gives 0 diffs, at `--batch 400` gives
39–41.

**Fix:** `client.cs_barrier`, armed at the three sites; the next command stalls until the ring
drains. The borrow additionally requires an empty ring at dispatch.

**Verification:** phase-A opdiffs **41 → 0**, stable over 4 runs, 8 knob variants, 5 topologies.
Three new checks FAIL on both `pushed_d` and pristine HEAD, PASS only on the fix.

### A4. Scatter-path `EXISTS` bumps LRU/LFU where stock does not — `22713766a`
Stock uses `LOOKUP_NOTOUCH`; the scatter sub used `LOOKUP_NONE` while sharing `ctype=CS_EXISTS`
with `TOUCH`, which legitimately wants the touch. Fixed with a per-row `.notouch` registry bit.
**Test note:** the obvious probe (`OBJECT IDLETIME`) is unusable here — it runs inline against the
empty decoy db and answers nil for every sharded key. LRU was read through the RDB instead
(fork emits `RDB_OPCODE_IDLE`; a stock oracle loads and reports it). Pre-fix **144/160** wrongly
reset → post-fix **0**, with the 16 survivors matching P(4 keys on one of 2 workers) = 1/8, and a
TOUCH control still resetting 160/160.

### A5. `cs_barrier` re-drive storm — `22713766a`
The wake condition was `(dispatchid - flushid) < ring_size` while the barrier releases at
`dispatchid == flushid`, so a barriered client was woken and re-stalled **once per retiring slot** —
O(depth) spurious `processInputBuffer` entries per barrier. ~2 lines.

### A6. The prefetch gate had never opened — `652deda9b`
`auto_min` compared a **per-worker** footprint against the **whole** shared L3, making the real
criterion `8·W × L3` rather than the documented "dimensionless 8×". On 4 workers that is 32× L3:
threshold ~2.24M keys/worker against ~500k in every benchmark on disk = ratio **0.22, gate shut**.
Counters added in the same commit proved it: at 500k keys, **100% of batches gated, 0 prefetches
issued**. Corroboration that it was an oversight: the value-chase budget on the following lines
already divides by `num_workers`.

### A7. `CONFIG SET maxmemory-clients` accepted-and-unenforced — `f2e6c6aee`
`initServerClientMemUsageBuckets()` refuses to build the buckets in multi-threaded configs, but
silently, so runtime `CONFIG SET` returned `+OK` with client eviction inert (boot refuses FATAL;
runtime did not). Now refuses explicitly.

### A8. S2 owner lock keyed on a non-key `argv[1]` — `f2e6c6aee`
`exExecFake` hashed `argv[1]` unconditionally, but top-level SCAN is worker-routed and its `argv[1]`
is a **cursor** — taking an arbitrary worker's lock around a cross-node scan, protecting nothing and
risking lock-order inversion. Gated on `legacy_range_key_spec.bs.index.pos == 1`.

### A9. Shared propagation constants refcounted from worker threads — P0, server kill
`shared.del`, `shared.unlink`, `shared.srem`, `shared.pexpireat`, `shared.persist`, `shared.pxat`,
`shared.hpersist`, `shared.hpexpireat`, `shared.fields`, `shared.xclaim` … are process-global `robj`s
holding command names, used to build propagation/rewrite argv. `robj.refcount` is a 23-bit bitfield
packed with `type:4/encoding:4/iskvobj:1` into **one 32-bit word**, so `++`/`--` is a whole-word
load-modify-store. Stock Redis is safe because commands run on one thread; here the propagating
commands are **worker-whitelisted**, so N workers perform that RMW on the same word concurrently.
Balanced incr/decr pairs then perform an unbiased random walk with an absorbing barrier at 0:
reaching it frees the global, and the next toucher panics
`illegal decrRefCount for object with: type 0, encoding 8, refcount 0` (OBJ_STRING/EMBSTR — `"DEL"`
is 3 bytes, so embstr; fingerprint matches exactly).

**Why grep missed it for so long.** `grep 'incrRefCount(shared\.'` finds only the three `t_hash.c`
sites. `propagateDeletion` reaches it through an *indirection* — `argv[0] = lazy ? shared.unlink :
shared.del;` then `incrRefCount(argv[0])` — which no search for the constant's name will surface.

**Fix — pin the CLASS, not the reachable subset.** `makeObjectShared()` on all 47 command-name and
command-argument constants. My first pass pinned only the ten verbs I could trace, which was the
wrong instinct: `SPOP`(→SREM), `XCLAIM`, `GETEX`(→PERSIST/PEXPIREAT), `SET..EX`(→PXAT), `HGETEX`,
`LPOP`/`RPOP`, `ZPOPMIN`/`MAX` are *all* whitelisted, each propagating through a different constant,
and the whitelist grows — a per-verb fix silently reopens the hole on the next command added.
Pinning is uniformly safe: no verb constant is ever mutated or freed, and every `refcount == 1` test
in the tree (`object.c:904/980`, `db.c:720/1141`, `defrag.c:1062/1134`) is a **conservative** guard
("mutate/defrag in place only if sole owner"), so a pinned object takes the safe branch. It removes
the shared mutable state rather than adding a lock to it. Deliberately **not** pinned: the pubsub
*bulk reply* constants, which are `addReply` targets (addReply copies bytes, does not refcount) and
are unreachable from a worker.

**The test-design lesson, which generalises.** My first probe was one long high-load run. It caught
the panic once, then two later runs of the *same unfixed binary* sailed through 18.4M and 26.6M ops
untouched. The reason is the bug's physics: refcount starts at **1**, and the absorbing barrier is
only reachable while the count is still near 1 — the walk is equally likely to drift *upward*, and
once it does, that boot can never free the object and is immune for life. Crash probability is
concentrated in the first seconds after boot, so **a long soak is the worst possible shape** and
would have been a false negative. `shared_refcount_race.sh` now runs N short trials with a fresh
process each, making every trial an independent draw. Generally: when a defect has an absorbing
state, soak time buys nothing and restart count is the only thing that matters.

**Why this class is now closed, and why it was the ONLY exposed one.** Every other `robj` in the
system has exactly one owner: a key maps to a bucket and `ex_bucket_table[bucket]` names a single
owner worker (`server.c:6924/6935`), so two workers never refcount the same *value* concurrently on
the normal path. The one place that invariant is deliberately relaxed — scatter/lock-borrow for
multi-key reads — is guarded by `tomo_wkr_lock` (`server.c:6975`). The `shared.*` constants were the
sole robjs with **no owner at all**: global by construction, reachable from every worker, guarded by
nothing. Pinning them removes the last unowned mutable refcount in the tree. `shared.integers` was
already `makeObjectShared` upstream, which is why the `XCLAIM` argv (`t_stream.c:1858`) was never
exposed despite being built on a worker.

### A10. A migration armed in the cutover teardown window is armed FOREVER — P0, server kill — `af9d6b590`

`reshardCoordinatorTick`'s teardown published `migration_active = 0` and only **then**
`co_state = CO_IDLE`, with a `serverLog()` (open/write/fflush/close) between the two stores.
`reshardArm` gated on `migration_active` alone; `reshardBeginCutover` gates on a CAS of
`co_state IDLE -> WAIT_CONVERGE`. `DEBUG RESHARD START` runs on an **IO thread** — and
`tools/preflight/reshard_order.py` drives START/CUTOVER in a tight loop for 180 s in the shipped
preflight — so an arm can land inside that window: START succeeds, the following CUTOVER's CAS
fails, and the migration is left **armed with no coordinator**. Nothing ever starts one, so
`migration_active` is stuck at 1 for the life of the process.

That one stuck flag is not a stalled reshard, it is a delayed server kill:

- every later `reshardArm` is refused ⇒ the load balancer is dead;
- `flatResizeCoordinate()` returns at its own `migration_active` check ⇒ **the FLATSTORE table can
  never resize again**. Under a write workload it fills to capacity and `flatInsert` ends in
  `serverPanic("flatstore INSERT: table full")`.

**Fixed by the store reorder alone**: teardown publishes `co_state = CO_IDLE` **before**
`migration_active = 0`, and the trailing `co_state` store at the end of the function is deleted —
once `active` is 0 a new migration may already have CASed it to `CO_WAIT_CONVERGE`, and a trailing
store would strand *that* one the same way. Because `active = 0` is a release store, any armer that
acquire-observes `active == 0` necessarily also observes `co_state == CO_IDLE`, so its cutover's CAS
cannot fail.

I first shipped a second half — `reshardArm` additionally requiring `co_state == CO_IDLE` — as
"defence in depth". It was removed: see §B4. Two successive reviews found that each guard added to
protect this invariant opened a wider hole than the one it closed. The reorder needs no guard.

**Not vacuous, in both directions.** `INFO stats` exposes `tomokv_reshard_cutover_no_coord` (the
defect firing). `tools/preflight/reshard_arm_race.py` requires *both* `cutover_no_coord == 0` *and*
continued cutover progress, and reports **SKIP, not PASS**, below 200 completed cutovers so a run
that never raced cannot pass. Acceptance runs it against a **defect-reintroduced** build (this file's
fix backed out, everything else identical) as well as the fixed one.

#### The 2026-07-29 audit: this section described a fix that was not in the tree, and a test that could not fail

Two things had to be repaired before any of the above was true of the shipped branch.

**The fix was gone.** The store reorder was reverted with `823c33ad0` (`Revert "Merge commit
'af9d6b590'"`). `67b5844ba` was meant to re-ship it *alone* — its message even says "what ships is 2
moved stores" — but its `src/server.c` diff contains **only deletions** (the arm guard, the rollback,
the `beforeSleep` self-heal). The reorder was never re-applied. `2s-numa-stable-dev` carried the
original defective order (`migration_active = 0` → `serverLog()` → `co_state = CO_IDLE`) for eleven
commits while this section claimed it fixed, and while §B4 below explained at length why the reorder
was the right minimal fix.

**The test could not fail.** `mig_arm_seq` was declared and never incremented. It stays 0 for the
life of the process, so `reshardBeginCutover`'s "is the running coordinator servicing MY arm?" latch
(`co_serving_arm == mig_arm_seq`) is `0 == 0` — **true for every caller**. The CAS-failure path
therefore returned `+OK` for a migration that got no coordinator and never reached the
`cutover_no_coord` increment: the counter was unreachable and both of the test's assertions were
dead. Measured before the fix: the arm-race test passed **3/3** on the defective `HEAD`, and passed
**2/2** on a build with `usleep(200)` inserted into the teardown window — a 200 µs window, ~50 k arm
attempts/s, and still zero counts. That is the shape of a dead assertion, not of a healthy server.
With the increment restored the same test fails **2/2** on the defect-reintroduced build
(`cutover_no_coord=1`, orphan visible in `server.log` as an `ARM` line logged *before* the `DONE` it
raced) and passes **2/2 + 1** on the fixed one.

**Lesson (the same one as §A7, one level down).** A guard whose input never changes is not a guard,
and a counter that cannot count certifies nothing. `mig_arm_seq` was introduced *by the fix for this
bug*, specifically to keep the acceptance counter honest, and it was introduced already broken — so
the very mechanism added to prevent a vacuous validation produced one. Before trusting a green
acceptance, prove the assertion is *reachable*: reintroduce the defect and watch it go red.

**Found while classifying something else, which turned out not to be a server defect at all** — see
§J.

---

## B. Defects I INTRODUCED — found and fixed

### B1. `inflight_writes` counter leak — introduced `9f75c922c`, fixed `f2e6c6aee`
Incremented on every write dispatch but decremented **only** in the CLOSE_ASAP teardown branch, so
on a healthy connection it only grew and the `inflight_writes == 0` gate was permanently false after
the first write. Also **never initialized** (per-field init, no memset → heap garbage), and the
`CLIENT_TOMO_WRITE` mark was stamped *after* the fake was published to a worker (a non-atomic RMW
racing the owner).

**This made my own acceptance number vacuous**: "0/6000 stale reads" is what a permanently-closed
gate produces. Fixed with `tomoRetireFakeWrite()` at every retire site (which also *clears* the mark
— a reused ring slot would otherwise decrement on a later non-write), init at both creation sites,
and the stamp moved before every publish.

### B4. My reshard arm guard turned a benign TOCTOU into a permanent balancer death — `af9d6b590`, fixed `088f8da9b`

Caught by an independent review of A10 **before** it was validated, and it is the more instructive
half of that fix.

`reshardBeginCutover` checks `migration_active` and `phase == MIG_COPYING`, *then* CASes
`co_state IDLE -> WAIT_CONVERGE`. Those are not atomic together: a `DEBUG RESHARD CUTOVER` on an IO
thread can be preempted between them, the migration it checked can complete meanwhile (teardown
publishes `co_state = CO_IDLE`, then `migration_active = 0`), and the CAS then **succeeds with no
migration in flight** — a phantom coordinator. `beforeSleep` drives `reshardCoordinatorTick` only
under `migration_active`, so `co_state` sits at `CO_WAIT_CONVERGE` forever.

On its own that was harmless: arms were still allowed, the next one set `active = 1`, and the stale
coordinator simply serviced it. **A10's arm-side `co_state` guard is what makes it fatal** — every
future arm is refused, `active` can never become 1 again, and the load balancer, every thread-mode
flip and `DEBUG RESHARD START` are dead for the life of the process. A guard that closes one wedge
by opening a wider one.

Fixed by making the guard ship with its rollback: `reshardBeginCutover` re-validates after winning
the CAS and rolls `co_state` back (by CAS, never a bare store); a *losing* CAS that sees `co_state`
return to `CO_IDLE` retries instead of counting `cutover_no_coord` (that race is normal, and a false
positive there would make the acceptance test lie on a healthy build); and `beforeSleep` gains a
counted, logged self-heal (`tomokv_reshard_phantom_coord`) that **resets** `co_state` rather than
running the tick — the tick assumes a live migration and would raise a `DRAINING` fence for one that
does not exist, holding every producer.

Then the **fix for that** was itself wrong. Re-review found that the rollback (a CAS on `co_state`
with `expected == CO_WAIT_CONVERGE`) and the `beforeSleep` self-heal net form an **ABA**: the net is
a second writer that can drive `co_state` non-IDLE → `CO_IDLE` while a rollback is in flight, a new
migration M2 then arms and installs a legitimate coordinator, and the stale rollback's CAS still
matches and knocks `co_state` back to `CO_IDLE` — leaving M2 armed with no coordinator. That is the
original P0, re-created *silently and uncounted* (`cutover_no_coord` is not bumped, because M2's own
cutover returned success). The window is a few instructions, but it needs only microseconds of delay
— less than the millisecond-scale stall the original TOCTOU required.

**Resolution: all of it was deleted and the fix reduced to the store reorder alone.** No arm guard,
no rollback, no retry, no self-heal net — therefore no second writer of `co_state`, no ABA, and no
phantom wedge (without the arm guard a phantom coordinator is benign again: the next arm sets
`active = 1` and the stale coordinator simply services it, exactly as before). What ships is the
2-line ordering change plus the counter and the idempotency latch the test needs.

**Lesson:** the guard and the invariant it assumes have to be reviewed together. I checked that the
guard closed the window; I did not check what the guard did to every *other* path that could leave
`co_state` non-IDLE — and then did the same thing again one level down. Three iterations, two new
defects, both caught by review rather than by any test. When a fix keeps needing another guard to
make the previous guard safe, the fix is wrong: go back to the smallest change that closes the
original window. Also: `bins/pre` must keep `mig_arm_seq`/`co_serving_arm` and the 1024-spin (not
just the counter) or a duplicate CUTOVER makes it fail for the wrong reason, and it must NOT carry
the retry branch — on the broken build `co_state` returns to `CO_IDLE` within the spin, so the retry
would heal the defect and the acceptance test would PASS on the broken build.

### B2. Sub-wave arity bug — `20cdae804`
Capped `nw` at 8 but advanced `base += 32`, so `MGET(10)` emitted an 8-element body under a
10-element header.

### B3. Retire-scheduling dropped fakes and wedged the server — `0703b1732`
The predicate was re-evaluated per pass against a concurrently-advancing `flushid`, so fakes were
dropped or duplicated: server alive, PING fine, zero ops, then death. Fixed with a single-snapshot
bitmask plus `serverAssert(w == n)`. The whole reordering feature was later deleted (`d2a526e98`)
after measuring **exactly zero** benefit.

---

## C. False conclusions I drew and retracted

| claim | why it was wrong | correction |
|---|---|---|
| "TASK#43 fixed: 0/6000 stale" | the gate was wedged shut; a closed gate produces 0 stale trivially | B1 |
| "warning-free build" (`65e2382b4`) | came from an **incremental** build that never recompiled `kvstore.c`; one pre-existing warning exists | noted in `22713766a` |
| "`tomoFlatMWaveProbe` is used by the scatter path" | CS_MSET has its own inline wave; the probe's only callers were the deleted flat routes | `867d79648` |
| "RENAME hypothesis disproved" | my test used `rename k k2` without controlling shard placement, so it took the cross-shard path and never reached the panic | A2 |
| "the borrow is an unmeasured optimization" | worse — its "SINTER +40–51%" exists **only in prose comments**, with no backing data anywhere in the tree, contradicted by the one committed cell (`sinter 1.04`) | `22713766a` |
| "node-local pools worth 500–1200 cycles/op" | conflated cross-CCD (coherence) with cross-NUMA (locality); under NPS1 it is ≈ a no-op | recorded in the prefetch report |
| "expect flat pre/post" (SET came out +20%) | the range also contained RAW-embed, a *performance* commit I'd forgotten | discriminator: +18.4% at 64B, −0.3% at 240B |
| "workers read a **frozen** clock — `cmd_time_snapshot` is only refreshed by main-thread `call()`" | half right. Workers really do bypass `call()`/`enterExecutionUnit` (they invoke `cmd->proc()` directly), but `afterSleep()` rewrites `server.cmd_time_snapshot` on **every** main-thread loop iteration (`server.c:2869`), so it advances regardless of worker traffic. The defect is that it is COARSE and SHARED, not frozen — see F-clock below. Had I "fixed" the frozen-clock story I'd have solved a problem that does not exist | F-clock |
| "`server.mstime` is fresh whenever there is traffic, because `afterSleepIO()` refreshes it per IO-thread loop iteration" (the F-clock filing's proposed fix) | `afterSleepIO` is registered but never called — `aeProcessEventsIO()` has no `aftersleep` invocation; only the main loop's `aeProcessEvents()` does (`ae.c:426`). `server.mstime` measured p50 77ms / max 84ms stale, identical to `cmd_time_snapshot`. Latching it would have been a no-op wearing a fix's clothes | A-F.0 |
| "run the expiry probe under worker load; an idle server hides the defect" | inverted. The clock is rewritten by the MAIN loop, so load makes it FRESHER (~2ms under 8 loaders vs 70–90ms idle). The stated regime hides the very defect being measured | A-F.0 |
| "the flaky `short-ttl-lazy-expire` cell is the coarse clock" | it is not: the cell allows a 1s margin on a 100ms-coarse clock. It was `moduleNotifyKeyUnlink` racing `server.allow_access_expired`, which kills lazy expiry outright | A-F.1 |

---

## D. Design defect — DELETED rather than fixed

**Flat-native / work-stealing M-read path** — `867d79648`. One executor read keys it did not own,
breaking same-client ordering **1547/4000 = 39%** of the time. The probe reported `taken=4000
gated=0`, proving the route ran with the gate open. The `inflight_writes` gate could never fix it:
it closes write→read but is structurally blind to read→write. Deleted; scatter is correct by
construction.

---

## E. Harness defects — the gate was lying

| # | defect | fix |
|---|---|---|
| E1 | **5 of 9 preflight suites ignored `TOMO_BIN`** and booted hardcoded binaries, while the GO stamp is keyed to the sha of the binary passed in — certifying a build the suites never ran | `f2e6c6aee` |
| E2 | `run_suite` graded a **missing/aborted** result file as PASS | `f2e6c6aee` |
| E3 | quickbench tagged arms by `basename(dirname(bin))`, collapsing two `<tree>/src/redis-server` arms into one pooled median reporting **+0.0% against itself** | `f2e6c6aee` |
| E4 | quickbench claimed to exclude ordering-failing arms but benchmarked them anyway behind a hidden warning | `f2e6c6aee` |
| E5 | quickbench killed servers with `pkill -x`, violating the rule documented in the same tree | `f2e6c6aee` |
| E6 | `controller_sweep.sh` died on `local`/`set -u`: `local a=$1 n=$((t*2))` expands **all** arguments before assigning, so `t` was unset | `652deda9b`-era |
| E7 | `ord_test.sh` and `controller_sweep.sh` were untracked scratch-dir dependencies | `f2e6c6aee` |
| E8 | `command_sweep` mixes **two load generators** under one floor scale (16 redis-benchmark conns vs one `redis-cli --pipe`), making its 4 FAILs method artifacts | open |
| E9 | `ablate32` compared prefetch-**off** against prefetch-**off** (the gate was already shut) and reported "+1% from disabling prefetch" | A6's counters make it impossible |
| E10 | my own ship gate hardcoded `bins/armC_d` — gating the **stale** binary | fixed in-session |

---

## F. Known-open defects (filed, not yet fixed)

| task | defect | note |
|---|---|---|
| #19 | reshard cutover fence — see the corrected breakdown in §H below | H1 = not a hazard, H2 **FIXED 2026-07-28**, H3 fixed. The "auto-reshard is defaulted OFF so the exposure is removed" note in this row was **stale and load-bearing**: the knob had been renamed `tomokv-key-lb` with default `20000`, i.e. ON. A mitigation recorded as a reason not to fix something must be re-checked against the config, not remembered. |
| #44 | fence `qb_pos == 0` assert under slow-script + SCRIPT KILL, ~20–30%/run, reproduces on pushed production | root cause unconfirmed |

### #44 investigation notes (2026-07-28) — NARROWED, NOT DIAGNOSED

Recorded so the next attempt does not repeat the eliminations. **No fix is proposed yet; this is a
lead, not a diagnosis.**

Ruled OUT:
- *Not a missing trim.* `processInputBuffer` has exactly two exits: one `return C_ERR` (the client is
  freed and the caller nulls `c`, so the assert is skipped) and the final `return C_OK`, which is
  preceded by the unconditional `else if (c->qb_pos) { sdsrange(...); c->qb_pos = 0; }`. Every
  `break` in the parse loop — including the fork-added `CLIENT_PIPELINE_STALLED` and
  `CLIENT_IO_PENDING_COMMAND` ones — falls through to that trim.
- *Not a diverged reusable-buffer guard.* The adoption block and `resetReusableQueryBuf` are
  byte-identical to stock, and the assert itself is stock (`redis/src/networking.c:3982`).
- *Not the caller/callee inconsistency it looks like.* `resetReusableQueryBuf` explicitly tolerates
  `sdslen(querybuf) > qb_pos` while its caller asserts `qb_pos == 0` first — but that asymmetry
  exists in stock too (the tolerance serves the other, `freeClient`-side call site).

The surviving lead: the assert is reached via one of the three early `goto done` paths in
`readQueryFromClient` (all read-failure: `EAGAIN` while still connected, or disconnect), which skip
`processInputBuffer` entirely and therefore assert on whatever `qb_pos` a *previous* frame left
behind. Stock's own comment on the reusable buffer says the contended case "only occurs when
commands are executed nested via `processEventsWhileBlocked()`" — which is exactly the crashing
regime (a slow script yields there to serve `-BUSY` and `SCRIPT KILL`). So the shape to test is
**re-entrant `readQueryFromClient` on a client whose outer `processInputBuffer` frame is mid-buffer**.
What makes this fork-specific is unproven: candidates are the extra parse-loop breaks and the fact
that `c->running_tid` migrates between an IO thread and main (`iothread.c:152/236`) while
`thread_reusable_qb`/`thread_reusable_qb_used` are `__thread` — so a buffer adopted on one thread can
be reset on another, clearing the wrong thread's flag.

**Next step is a reliable repro, not a patch.** `fence_suite.sh` reproduces at ~20–30%/run, so any
candidate fix must be judged over many runs — a single green fence run is luck, not evidence.
| #48 | reshard read-straddle (part of #19) | |
| #49 | pipelined **cross-key** non-serialisation — owner ruled *not guaranteed*, so **document, don't fix** | |
| #50 | HASH-FIELD TTLs were never actively reclaimed — `activeSubexpiresCycle()` walks the `server.db` decoy's `subexpires`, exactly bug #42 one level down. Silent unbounded leak; lazy expiry keeps every read correct so no functional test could see it | **FIXED** — worker-side `exActiveSubexpiresCycle()`, `tools/preflight/active_subexpiry_probe.sh` |
| — | `SCAN` returns 0 keys when `!(flat_store && shared_node_dbs)` | config-derived |
| F-clock | workers share ONE coarse `cmd_time_snapshot` | **FIXED** 2026-07-28 — see §A-F below |

### F-clock. Worker commands have no per-command clock

Workers execute `cmd->proc()` directly (`server.c` CS_LOCAL + the two fake-exec sites) and so never
call `enterExecutionUnit()`, which is where a command normally latches its time. They therefore read
the single global `server.cmd_time_snapshot`. That global is **not frozen** — `afterSleep()` rewrites
it every main-thread loop iteration — so the original "workers read a stale clock" filing overstated
it (§C). Two real problems remain:

1. **Cadence is the main thread's, not the command's.** Under worker-dominated load the main thread
   has little to do and sleeps until the cron timer, so the snapshot advances in steps of up to
   `1/hz` (100ms at default `hz=10`) instead of continuously. Lazy-expire decisions on workers
   quantise to that step, which is what makes repeated identical runs disagree on how many
   short-TTL keys are gone.
2. **It can change underneath a running command.** The main thread rewrites the global while workers
   read it, so a command that looks a key up twice can see it live and then expired — precisely the
   invariant the upstream comment on `commandTimeSnapshot()` exists to protect ("a key can expire
   only the first time it is accessed and not in the middle"). It is also a formal data race on a
   non-atomic 64-bit global.

**Intended fix (cheap):** latch a `__thread` snapshot from `server.mstime` at worker command entry
and have `commandTimeSnapshot()` prefer it. `server.mstime` is refreshed by `afterSleepIO()` on every
IO-thread loop iteration, so it is fresh whenever there is traffic — no `clock_gettime` per command.
There is ample `__thread` precedent in this file. Measurement harness:
`tools/preflight/expiry_clock_lag.py` reports p50/p95/max client-observed expiry lag under worker
load (an idle server has a busy main loop and hides the defect).

> **Two things in the paragraph above are wrong.** `server.mstime` is *not* fresher than
> `cmd_time_snapshot`, and the regime advice is inverted. Both are corrected in §A-F.

---

## A-F. F-clock — fixed 2026-07-28, and the defect hiding behind it

### A-F.0 Two corrections to the filing above

**`server.mstime` is exactly as stale as `cmd_time_snapshot`.** The filing's premise was that
`afterSleepIO()` refreshes it on every IO-thread loop iteration. `afterSleepIO` is registered
(`aeSetAfterSleepProc`, three sites in `server.c`) but **never invoked**: `aeProcessEventsIO()` —
the only loop IO threads run — has no `aftersleep` call. Only the generic `aeProcessEvents()`
(`ae.c:426`), which only the main loop runs, calls it. Measured side by side on the unfixed build,
one client issuing a command every 50ms: `real − cmd_time_snapshot` = p50 77ms / max 84ms, and
`real − server.mstime` = p50 77ms / max 84ms. Bit-identical. **Latching `server.mstime` would have
been a no-op that looked like a fix** — the same shape of error as §C's retracted "frozen clock".

**The regime advice is backwards.** The filing (and `expiry_clock_lag.py`'s original docstring)
said to run the probe *under worker load* because "an idle server has a busy main loop and hides
the defect". The opposite is true: the clock is rewritten by the main loop, so the **busier** the
server the more often that loop turns and the **fresher** the clock. Under 8 loader connections
the worker-visible clock lags real time by ~2ms; with the server nearly idle it lags 70–90ms. The
defect lives in the low-rate regime.

### A-F.1 The defect that was actually causing the flaky `short-ttl-lazy-expire` cell

The F-clock filing cited the nondeterministic `feature_sweep` cell as its evidence. That cell's
failure is **not** explained by a 100ms-coarse clock — the cell waits 3s for a 2s TTL, a 1s margin.
The real cause is a second, worse defect in the same family:

`moduleNotifyKeyUnlink()` (`module.c`) raises `server.allow_access_expired` /
`.allow_access_trimmed` around its callbacks and lowers them after. It is called from
`setKey()` on every **overwrite** and from `dbGenericDelete()` on every **delete** (`db.c:684`,
`db.c:1010`) — i.e. on every worker thread's hot path — and those two are plain non-atomic `int`s
in `struct redisServer`. N workers doing `++`/`--` on one shared word lose updates, so the counter
walks off zero and **stays** there. `keyIsExpired()` opens with
`if (server.loading || server.allow_access_expired) return 0;`, so from that moment **lazy expiry
is dead process-wide** — for every key, on every thread, until restart.

**Evidence** (instrumented build, `io4/ex4`, 8 loader connections): `moduleNotifyKeyUnlink` fires
on iotids 33–36 — exactly the four workers (`TOMO_IO_THREADS_MAX+1+wid`). The counter reached
**+7227 after ~2.4M unlinks in about 4 seconds** and never came back. A `SET k v PX 60` key was
still returned by `GET` **25 seconds** later. The give-away signature in a black-box probe is
`GET k` → value while `PTTL k` → `0`: a contradiction unless `keyIsExpired()` short-circuits
before it ever looks at the clock.

Note this defect *masks* F-clock: with lazy expiry dead, no expiry-timing measurement means
anything. Any "F-clock fix" validated on the unfixed build would have been vacuous (§G).

**Fix:** both guards became `__thread` (`tomo_access_expired` / `tomo_access_trimmed`, defined in
`server.c`, declared with the reasoning in `server.h`). The guard only ever meant "on THIS thread,
inside a module callback", so thread-local is both race-free and semantically exact. The
`server.*` fields stay, now solely as the `DEBUG SET-ALLOW-ACCESS-EXPIRED` operator override that
`tests/unit/type/hash*.tcl` uses; readers go through `accessExpiredAllowed()` /
`accessTrimmedAllowed()`, which OR the two.
*Rejected:* making the counters atomic. It removes the lost updates but not the defect — the
guard would still be observably raised on one thread while a sibling worker reads it, which is the
same "expired key reads as live" bug at lower probability.

### A-F.2 The F-clock fix

A `__thread` latch (`tomo_cmd_time`) taken at the two worker command entry points —
`exExecFake()` (covering both `cmd->proc` sites: the HFE all-node-locks branch and the ordinary
one) and `csSubExec()` (the scatter subs, incl. `CS_LOCAL`) — with `commandTimeSnapshot()`
preferring it whenever the thread's depth counter is nonzero. Non-worker threads never raise the
depth, so the main-thread path is byte-for-byte unchanged. The depth counter also gives the
nesting semantics upstream requires: a re-entering command keeps the OUTER instant.

The latch is sampled with `getMonotonicUs()` (RDTSC-class, the same read `call()` already does per
command) and only re-reads the wall clock when the monotonic delta says the latch could be 500µs
old — so accuracy is well inside the millisecond the value is measured in, at a few thousand
`gettimeofday`s per second per worker instead of one per command.

`exExecFake`'s release is placed **after** `migCaptureEffect`, so the resharding effect capture
re-reads the key it just wrote at the same logical instant the proc saw.

### A-F.3 The discriminating evidence

Three binaries, distinguished by directory (never by name — `pkill -x redis-server` cannot see a
binary called `unfixed`), ABBA-interleaved inside **one** hold of the shared box lock:
`unfixed` = HEAD, `cfix` = the §A-F.1 guard fix only, `fixed` = both. `cfix` exists so the F-clock
fix cannot take credit for the guard fix's improvement.

`tools/preflight/expiry_clock_ab.sh` runs `expiry_clock_lag.py` in the two regimes the two defects
need — they are opposite regimes, so **no single cell can discriminate both**:

| cell | arm | p50 | p95 | never |
|---|---|---|---|---|
| **D1** guard: 8 loaders, poll flat out | unfixed | 5000ms | 5000ms | **20/20** |
| | cfix | 0.8ms | 1.3ms | 0 |
| | fixed | 0.8ms | 1.5ms | 0 |
| **D2** clock: idle, 5ms poll, active-expire OFF | unfixed | 42.0ms | 42.7ms | 0 |
| | cfix | **41.9ms** | 42.2ms | 0 |
| | fixed | **1.2ms** | 1.7ms | 0 |

D1: on `unfixed` the key is *never* expired, in every one of 20 samples. D2: `cfix` still sits at
~42ms — the guard fix moves it not at all — and only the clock latch takes it to ~1.2ms, a **35×**
reduction. Reproduced across independent rounds; the ~42ms is tight rather than spread over
[0,100] because the probe's next sample is phase-locked to the cron tick that ended the last one.

**Two ways this cell could have been vacuous, both closed:**
- *The active expire cycle is a second way a key can vanish, and it does not read
  `commandTimeSnapshot()`* — it takes its own fresh `ustime()`. Its fast pass runs from
  `beforeSleep`, so on an idle server with a near-empty keyspace it deletes the probe's key within
  ~1ms **however broken the lazy clock is**. That is how an early run scored `unfixed` D2 at
  p50=1.0ms — a perfect number from a build whose lazy expiry was entirely dead. D2 now disables it
  (`DEBUG SET-ACTIVE-EXPIRE 0`) and *prints whether the DEBUG was accepted*, so a silently refused
  one cannot restore the confound unnoticed.
- *"How long past its deadline did the key stay readable" is trivially ~0 if the key was never
  readable* — a rejected `SET`, a desynced reply stream, or a shard-routing miss would all score
  perfectly while measuring nothing. Every sample now proves the key is live before its deadline
  and reports `early=`; nonzero marks the cell **invalid**, not good.

`correctness_suite.sh` against `fixed`: **15 passed, 0 failed.**

### A-F.4 Found, not fixed — `server.execution_nesting` is raced the same way

Same instrumented run: `enterExecutionUnit`/`exitExecutionUnit` fire from iotids 0–3 (main **and**
the IO threads, which run `call()` for every inline command), all mutating the one global
`server.execution_nesting`. Observed values include **−1** and **2** at moments when nothing was
nested. Two consequences, neither yet demonstrated in the wild:
- `enterExecutionUnit` only refreshes `server.cmd_time_snapshot` when the counter reads 0, so drift
  makes `call()` stop refreshing the global clock (`afterSleep` still does, at 1/hz).
- `confAllowsExpireDel()` (`db.c`) dereferences `server.executing_client[iotid].p->cmd` **only**
  when `execution_nesting > 1` — reachable by drift alone, with no null guard.

The correct fix is to make execution nesting thread-local, which is a wider change than this one
(module.c has `serverAssert`s on its exact value) and is left filed rather than attempted.
The F-clock fix does insulate workers from it: they no longer read the global clock at all.

---

## G. The recurring pattern

Six of this session's defects were shielded by a check that **could not fail**: a gated feature
measured with its gate wedged shut; a TTL test that stores only strings; a flaky suite judged by
single green runs; a reshard `converged` where source and destination are the same kvstore; a ref
fence whose counter has no incrementer; a prefetch A/B that was off-vs-off.

**The rule adopted as a result:** every new regression check must be run against a build that still
contains the defect and **observed to fail there**. Every A/B must print, in both arms, a counter
proving which path executed. A test that cannot fail is not evidence.

---

## H. Reshard fence — corrected breakdown

An adversarial audit reported **three fail-open holes** in the cutover fence. On inspection one of
the three was **over-called**, and I nearly shipped a fix for a non-problem. Recording both the
corrected finding and my own error, because the error is the more instructive part.

### H1. "The ref fence is vacuous" — TRUE, but NOT a hazard. Do not 'fix' it.

`migration.outstanding_a_refs` has exactly three references tree-wide: the declaration, a
store-of-0 at arm, and the wait-for-0 at cutover. **There is no incrementer**, so the wait always
passes. The audit called this fail-open. It is not:

- The field guards zero-copy reply refs pointing into A's range against A's copy being **freed at
  CLEANUP** — and under `shared_node_dbs`, `CLEANUP IS SKIPPED ENTIRELY`. The tree says so at the
  phase store: *"nothing to clean — the flipped range's data lives in the SAME dict[b] the new
  owner now serves; there is no stale source copy."* Nothing is freed by a flip, so no ref can
  dangle.
- And the copy path this fence was written for is **unreachable**: `shared_node_dbs =
  (workers_per_node > 1)`, while a reshard moves a range between two workers **of one node** — with
  one worker per node there is no valid `(src,dst)` pair. So reshard only ever runs in the mode
  where the fence is unnecessary.

**My error:** I first "fixed" this by refusing to arm whenever zero-copy was enabled. Since
`tomokv-zerocopy-min-value` defaults to **1024**, that would have disabled *every* reshard —
including manual ones used for testing — to guard against a dangling ref that cannot occur.
Reverted before it shipped; the wait is left in place as a documented no-op, with a note that
reviving the copy engine would require a real incrementer *plus* a counter proving it fires.

**Lesson:** an audit finding is a hypothesis about the code, not a fact about it. This one was
mechanically correct ("no incrementer exists") and operationally wrong ("therefore the guarantee is
missing") — the guarantee was unnecessary, not missing.

### H2. The drain check reads EMPTY mid-batch — REAL, **FIXED 2026-07-28**

The coordinator acked a producer slot after ~2 ms of apparent queue emptiness (the idle-ack), but
`exQueuePopBatch` publishes `head` **before** executing the batch. A worker actively running 16 jobs
therefore reads as empty and gets acked while range primaries are still executing — the steady state
of a busy worker, not a rare race.

The filing said the exposure was mitigated because auto-reshard defaulted off. **That mitigation was
already gone**: the knob was renamed `tomokv-key-lb` and defaults to `20000`, so the balancer arms
cutovers on any shard doing >20k ops/s. The fix is the fence, not the default.

**The repro.** `reshard_order.py` cannot catch this and never could: its GET/SET pairs finish in
microseconds, so the worker is never busy for the 2 ms the idle-ack required. The window is not rare,
it is just *narrow in wall-clock*, and a probe made of fast commands cannot sit inside it. The new
`tools/preflight/reshard_midbatch.py` holds it open on purpose — it pipelines `LINSERT k BEFORE
<tail marker>` against a 2M-element list, so worker A pops one batch and then executes for hundreds
of milliseconds with an empty queue, and cuts the range over while A is in there. `LINSERT` returns
the post-insert length, so `LLEN` issued later **on the same connection** must not be smaller. It is:

**The first repro attempt was wrong, and the reason is the interesting part.** The obvious shape is
"make the worker busy for hundreds of ms and cut over while it is inside the batch". It reproduces
nothing — 0 violations over 5 runs x 12 cutovers — and the server log says why:

```
17:29:56.679  reshard DRAINING: fence raised, nprod=7
17:29:56.800  reshard fence drained          <- 121 ms later, against a 135 ms batch
17:29:56.810  reshard FLIP
```

The fence is *also* gated on the main thread's sentinel; main pushes one every `beforeSleep`, and
worker A cannot reach that sentinel until it has finished the batch it is already running. So a
BUSY producer is not the hole: it publishes a sentinel within one event-loop iteration, and the
fence then waits the batch out by accident. The idle-ack only fires for a producer whose loop has
been stalled for >2 ms — and the danger is that such a producer has range work for A that the
coordinator cannot see, because `exQueuePush` only STAGES (the release-store of `tail` happens at
the end of `processInputBuffer`).

`reshard_midbatch.py` manufactures exactly that, from one connection and one pipeline: N range
writes, then `DEBUG SLEEP` — which is not worker-dispatchable, so it runs INLINE on the io thread,
*inside* `processInputBuffer`, before the `flushExQueues` that would publish those pushes — then the
read. The io thread publishes nothing and pushes no sentinel for the whole sleep, the old owner's
queue reads empty and is idle-acked, and ownership moves while N range writes are still un-executed.

**The fix** (`server.c`, `server.h`):

1. **`exQueue.retired`** — a consumer-published execution frontier, stored once per batch *after* the
   batch has executed. `head == tail` answers "nothing left to pop"; `retired == tail` answers the
   question the fence was actually asking. One relaxed load + one release store per batch, on a line
   the worker already owns.
2. **The idle-ack is deleted.** A slot is acked only when worker A *executes* that slot's sentinel —
   which is sound in both directions, because the sentinel is pushed by the producer only after it
   has acquire-observed `phase == DRAINING` (so everything it pushes afterwards is held) and sits
   behind everything it pushed before (so reaching it proves those retired).
3. **Idle producers are woken** (`tm_mig_mbox[slot].notifier`, the notifier the connection-migration
   control plane already uses) so a producer asleep in `epoll_wait` still pushes its sentinel.
4. **Slots with no thread behind them** — a parked spare, an unconverted growth io slot, an io thread
   that parked — can never push a sentinel, so they take the quiescence ack (`retired == tail`)
   instead. Both transition races are safe: a thread entering IO mode after we acked it must
   acquire-load `phase` before its first dispatch and therefore holds; a thread leaving IO mode is
   simply re-evaluated on the next tick.
5. **A watchdog abort** (`tomokv-reshard-fence-timeout`, default 10 s) — the filing's warning that a
   wrong wake path *deadlocks* a cutover is correct, and a deadlock is worse than the bug. On
   timeout the cutover is abandoned **without flipping**: under `shared_node_dbs` nothing has been
   copied, so an abort is a no-op on the keyspace and the range simply stays where it is. INFO
   exports `tomokv_reshard_fence_aborts`; the suite fails on any nonzero value, because an abort
   means a producer stopped answering, not that the timeout is tight.

**A second-order fix the rewrite forced.** The fence now genuinely waits for worker A to make
progress, so anything that can stall A now stalls the whole cutover — including a pending flat-table
resize, which parks A in `exSlice` until the *main thread* clears `flat_resize_active`. The
main-thread hold spins (`migHoldIfDraining` / `migHoldKeyIfDraining`) only pumped
`reshardCoordinatorTick`, so main could spin forever waiting for a fence it was itself blocking.
They now pump `tmFlipTick` and `flatResizeCoordinate` too, matching the flush-gate spin that already
had this right. Under the old idle-ack this could not deadlock — because the old fence completed
whether or not A was making progress, which is exactly what made it unsound.

**Also corrected: the documented contract was fiction.** `server.h` said worker A "decrements
`*drain_ack`". There is no counter and nothing is decremented — the field is a non-null marker
(deliberately pointed at `fence_acked[0]` so it is never dangling) and the ack is a store of 1 into
`fence_acked[queue index]`. Comment rewritten to describe the code.

### H2b. The HOLD was range-scoped in what it tested and thread-scoped in what it stopped

Owner's protocol for a cutover: the old owner finishes the commands it already has for the migrating
range; commands arriving for that range wait until it has; then they run under the new owner. **The
only thing that may wait is the contended range** — both workers keep executing their other buckets
at full rate, and neither may stop popping its queue.

The tree's hold (`migHoldIfDraining`, from the H3 fix) tested the right thing — per command, bucket
in `[lo,hi)` — but stopped the wrong thing: it **spun the io thread**. Every other client on that
thread stopped being served, including clients touching buckets nowhere near the migration, so both
workers lost the traffic those clients would have generated. That is a throughput cliff on a worker
that is 1/N of capacity, and the H2 fence fix made it worse by making the DRAINING window a real
drain instead of a 2 ms guess.

Replaced with a **client park**: `migHoldClientIfDraining` marks the one client `CLIENT_PIPELINE_STALLED`
and returns — the same idiom the stateful-command and `cs_barrier` gates already use, evaluated at
the same place, *before* a pipeline ring slot is taken. Because the command was never dispatched
there is nothing to lose and nothing to re-order; the client's own FIFO is untouched. The io thread
goes straight back to its event loop; worker A drains its range as a side effect of executing its
queue and never waits for anything; worker B keeps popping its own buckets throughout.

Details that matter:
- **Every key, not just `argv[1]`.** `migAnyKeyInRange` keeps the single-key fast path but falls
  back to the real key spec, so a coalesced `MSET`/`DEL` whose *third* key is in range parks too.
  This is what makes the old per-key cross-shard spin (`migHoldKeyIfDraining`) unreachable in
  practice rather than merely rarer.
- **Waking a parked client.** A parked client has an EMPTY ring by construction, so the reply-drain
  re-drive — which only walks clients that have in-flight fakes — can never reach it. The release
  sweep runs from `beforeSleep`/`beforeSleepIO`, and the coordinator wakes every io thread while the
  fence is open **and once more at the flip**, unconditionally and not rate-limited, because that is
  the one wake that must not be missed. The abort path wakes them too, or an abort would trade a
  stalled range for a stalled client.
- **Dying while parked.** A parked client is referenced by nothing else in the system, so
  `unlinkClient` drops it from the park list; otherwise the list holds a freed pointer until the next
  cutover.
- **Deleting the spin is not a hole.** The park gate and `migPushFenceIfNeeded` read the same
  acquire-loaded, monotone `phase`. If the gate did not park, this producer has not observed
  DRAINING, so it has not pushed its sentinel either — anything it dispatches to the old owner now
  lands *ahead* of that sentinel in the same FIFO queue, which is exactly what the fence proves has
  retired. Reaching the old owner *behind* its own sentinel requires having already seen DRAINING,
  and such a producer parks.

**Deliberately NOT done:** no change to `migration.outstanding_a_refs` (see H1 — it is a documented
no-op guarding an unreachable path, and "fixing" it once already nearly disabled every reshard), and
no change to the auto-reshard default, which stays ON.

### H3. The fence gated `CMD_WRITE` only — REAL, FIXED

`migHoldIfDraining` held only writes, so during DRAINING **reads kept routing to the old owner A**
while the same client's next command routed to the new owner C after the flip — a same-client
read/write pair on two workers with nothing ordering them. Same class as A3, triggered by ownership
movement rather than a non-owner read. The tree's own comment admitted the behaviour ("READS keep
flowing to worker A until the flip") but not its consequence.

Fixed: hold range reads as well, using the `legacy_range_key_spec.bs.index.pos == 1` predicate
rather than a bare `argc >= 2` (SCAN's `argv[1]` is a cursor). Held producers still push their
sentinel every spin and the `iotid == 0` coordinator pump still runs, so widening the held
population does not deadlock — it only widens who waits.

**Coverage added:** `tools/preflight/reshard_order.py` + `reshard_suite.sh`. Before this,
`grep -rn RESHARD tools/preflight/` returned **nothing** — which is how three holes accumulated
unnoticed. The probe pipelines `GET k / SET k NEW / GET k` on one connection while driving real
cutovers, and a violation is the first GET returning NEW. It **reports SKIP, not PASS, if no
cutover completed**, so it cannot pass by never entering the window.

---

## I. Allocation ownership — audit result (2026-07-27)

Whole-codebase sweep (18 agents, 124 sites, 81 confirmed asymmetric after independent
re-verification). Stock Redis executes commands on one thread, so every upstream allocation site
assumes alloc and free happen on the same thread; this fork splits ingress from execution and
silently invalidates that.

**Only three shapes fire per command on the default config, and they are three forms of ONE
object** — the SET-family value operand, allocated by an IO thread at parse and destroyed on a
worker inside `kvobjSetEx`:

1. value sds 45B..(169−keylen)B — freed at `object.c:382` in the embed branch (worker)
2. value robj shell — freed at `object.c:423` → `object.c:736` (worker)
3. value sds above the embed limit, **adopted** into the keyspace — freed a write-generation later
   via `db.c:790` → `flatstore.c:118` → `server.c:6560` (worker)

Plus, in the other direction: the 16KB `clientReplyBlock` + its `listNode`, allocated on the worker
and freed on the IO drain, **per command for every worker-executed multi-element read**
(HGETALL/LRANGE/SMEMBERS/ZRANGE*/SCAN/XRANGE); and `mget_vals`, one sds per key.

### I1. The operand pool's documented invariant is false

`networking.c` states: *"The refcount==1 operands … are alloc'd at parse and freed at
`freePendingCommand`, **both on the SAME IO thread**, so a per-thread freelist needs no cross-thread
ring."* That holds for keys and ordinary args. It does **not** hold for the SET **value** operand,
which `kvobjSetEx` consumes on the worker and which therefore never reaches `freePendingCommand`.
The pool cannot recycle it, which is consistent with the recorded result that the tiered pool is
"flat on 64B 1:9" while paying off on write-heavy large-value traffic. `tomokv-opt-operand-pool`
defaults to 0.

### I2. Two corrections to my own reasoning, recorded because they were wrong

- **I mis-attributed the profile evidence.** I claimed `52200d263`'s "10.2% of EX cycles in the
  allocator under flat vs 4.4% dict, `je_tcache_bin_flush_small` only under flat" supported the
  asymmetry hypothesis. It does not: `flatstore.c:72-82` claims that same profile for a *different*
  mechanism (`flatRetire`'s per-overwrite alloc/free, then freed on main), both halves since fixed.
  Decisively — a 64B SET overwrite frees **2 IO-origin blocks on the worker under flat *and* under
  dict**, so the flat-vs-dict *delta* cannot be this asymmetry. The asymmetry is real; it has simply
  **never been measured**. Do not cite that figure for it.
- **Zero-copy effectively fires at ≥16KB, not ≥1KB.** `tomokv-zerocopy-min-value` defaults to 1024,
  but `isCopyAvoidPreferred` also requires `io_threads_num >= 7`, and upstream `io-threads` is
  `IMMUTABLE_CONFIG` default 1 and never assigned in the fork — so the live branch requires
  `len >= COPY_AVOID_MIN_STRING_SIZE` = 16384.

**Next step is measurement, not code.** Nothing here has been measured; the fix direction
(free-on-owner, same-arena, or eliminate the transfer) should be chosen only after instrumenting
per-thread tcache flush behaviour, and the instrument must be able to come back negative.

### E-extra. Renamed A/B binaries defeat every suite's own cleanup (2026-07-28)

`NIGHT_PLAN.md` rule 2b records that an agent's *renamed* binary defeats a foreign `pkill -x`. The
same trap fired from the opposite direction here, against my own harness. I built the two arms of
the refcount A/B as `$J/bins/rc/fixed` and `.../unfixed`, then handed them to the suites via
`TOMO_BIN`. Every suite tears down with `pkill -9 -x redis-server`, which matches on `comm` — so
neither arm was ever reaped. A server from the correctness run stayed alive for **25 minutes**,
holding its port and its RSS, and was discovered only because `cp` onto the running binary failed
with `Text file busy`. Anything measured in that window was measured against a polluted box.

**Rule:** A/B arms are distinguished by **directory**, never by filename — `bins/<arm>/redis-server`.
Applied in `shared_refcount_race.sh`. The generalisation: any script that both *names* a binary and
*relies on `pkill -x`* to clean it up contains a silent contradiction. `Text file busy` on a `cp`
over a binary is a useful tell that a process you thought was dead is still running.

### E-extra2. I contaminated another agent's A/B, then accepted its wrong explanation (2026-07-28)

**The box's real noise floor is ±2%, not 15–30%.** It is a Ryzen 7700X desktop (8C/16T, single CCD,
32 MiB L3, 1 NUMA node). The "drifts 15–30%" figure repeated throughout this project's notes belongs
to the **laptop**. Owner's correction.

Two failures follow from the wrong figure, and the second is worse than the first:

1. **I ran benchmarks on top of a concurrent agent's A/B.** Timestamps: my `rc_gate` ran 21:36–21:47,
   inside that agent's `ad`/`ae` cells (21:19–21:57). I had been checking `boxfree.sh` before each
   run and believed that was sufficient. It is not — it answers "is the box busy *right now*", so
   two agents polling it both see FREE in the gaps between the other's cells and both start.
2. **The agent explained its own contaminated result as thermal drift** — HEAD's median moving −9%
   between runs *on identical code* — and I accepted it, because a 15–30% noise band makes −9%
   sound ordinary. At ±2% it is impossible, and it should have been an immediate stop-and-look.
   Consequences: that agent's verdict ("−0.6%/−0.7%/+1.7%, all noise, revert both") is not
   supportable — at ±2% the **+1.7% may be real signal** — and its cells were contaminated anyway.
   Both changes must be re-measured on an exclusively-locked box before any keep/drop decision.

**The general hazard:** an overstated noise floor is an all-purpose excuse. It does not make
conclusions conservative — it makes every inconvenient result dismissible, which is strictly worse
than having no number at all. Widening error bars is not the safe direction.

**Fix:** `$J/withbox.sh` takes a **shared** `flock` on `/tmp/tomo_box.lock` for the whole duration of
a measuring command; waiting becomes automatic rather than polite. Verified by construction (a second
caller blocks until the first releases). Note a *private* per-script lock — which `rc_gate` had —
provides no mutual exclusion whatsoever; the point is that everything contends on one path.
Rule recorded as NIGHT_PLAN 6b. On this box, **>5% between identical arms is contention or a bug,
never drift.**

### E-extra3. `while read` silently drops a file's last line without a trailing newline (2026-07-28)

Found by a subagent during the knob retirement, and it had already produced a false ALL-CLEAR — in
my own verification, not just theirs.

`while read k; do ...; done < list.txt` executes the body **once per newline**. `read` returns
non-zero at EOF when the final line has no terminator, so the loop body never runs for it. A
generated list written with `'\n'.join(...)` has no trailing newline, so **the last entry is never
checked** — and the loop still exits 0, so nothing looks wrong.

Concretely: `/tmp/retire_list.txt` held 44 retired knob names; every `while read`-based sweep over it
verified only 43. `tomokv-zerocopy-min-value` was never checked. It happened to be clean, so the
outcome was luck, not method.

**Rules:**
- Generators: end the file with a newline (`'\n'.join(x) + '\n'`).
- Consumers: `while read k || [ -n "$k" ]; do` — the `|| [ -n "$k" ]` runs the body for a final
  unterminated line. Or avoid the shell entirely and iterate in Python.
- Verification loops especially: a checker that silently skips an item reports success it did not
  establish. Same family as the vacuous-validation ledger above — the check ran, passed, and proved
  nothing about the one item it skipped.

### F-pipeline. Cross-shard INTER double-counts LRU/LFU and keyspace stats (A4-class, UNFIXED)

Found 2026-07-28 while gathering hardwire evidence for `tomokv-xshard-pipeline`. Not previously
filed, and there is no test for it.

**Mechanism.** All three merge-execution pipeline stages look keys up with `LOOKUP_NONE` —
`server.c:8710` (SIZES), `:8724` (GATHER1), `:8783` (PROBE) — and **every key is looked up twice**:
once in SIZES to read its cardinality, then again in GATHER1 or PROBE to read its contents.
`db.c:325-338` shows `LOOKUP_NONE` bumps LRU/LFU and increments `keyspace_hits`/`misses`. Stock
`SINTER`, and this fork's own gather arm, look each key up **once**.

**Consequence.** For every cross-shard INTER, `INFO keyspace_hits` is roughly double-counted and LFU
counters are bumped twice, which perturbs eviction decisions.

**This is exactly the A4 class**, which the project already judged a real defect and fixed with a
per-row `.notouch` registry bit — a bit the gather sub-exec honours (`server.c:7894`) and the
pipeline stages ignore entirely. That the same defect recurred in a sibling path is the interesting
part: the fix was applied to one route rather than to the lookup discipline.

**Fix:** pass `LOOKUP_NOTOUCH|LOOKUP_NOSTATS` on the SIZES stage — it is a metadata probe, not a
read — leaving GATHER1/PROBE as the single accounted lookup. Needs an RDB-idle-time-style
discriminating probe as A4 used, because `OBJECT IDLETIME` is unusable on sharded keys (it answers
against the empty decoy db).

### F-pipeline-2. The pipeline gate has no size or skew threshold (unmeasured regression regime)

Same review. `server.c:8980` gates the merge-execution pipeline on `nkeys >= 2` and nothing else, so
**every** cross-shard INTER takes it — including two 32-element sets. In that regime the pipeline
converts one parallel 1-hop gather into `2 + (nshard-1)` **sequential** drain-driven hops and arms
`cs_barrier`, stalling that client's next pipelined command until the ring drains (plus the A5
re-drive cost).

Both benchmarks behind the "measured win" used **sequential `redis-cli`**, where a barrier is free.
So the win is real in the regime that was measured and the cost regime was never measured at all.
Per the three-regime rule (NIGHT_PLAN 13) this is a predicted-deficit case that needs testing before
the gate is considered correct: small sets + pipelined client is exactly where it should lose.

### F-doublehash. Every single-key command hashes its key TWICE (OPEN, real per-command saving)

Found 2026-07-28 by the deprecated-gate audit, while establishing that the dict hash-carry was dead.

`tomoKeyBucket()` (`server.c:7026`) computes `xxh64(key,len) & TOMO_BUCKET_MASK` at dispatch and
keeps **14 bits** for the ownership bucket. The flat lookup then calls `tomoKeyHash(key,len)`
(`kvstore.c:1015` `flatGet`, `:1052` `flatFindForWrite`) — and `tomoKeyHash` **is** `xxh64`
(`server.c:6579`). So the identical hash over the identical bytes is computed twice per single-key
command, and 50 bits of the first one are discarded.

**Why it was invisible:** the mechanism that was *supposed* to avoid this — `prefetch_key_hash` →
`dictArmHashHint` → the one-shot hint in `dictGetHash` — only ever served the DICT path, and its
sole setter was `PFS_HASH`, which cannot fire on a flat keyspace. So the codebase carried a
hash-carry mechanism that was dead, while the live path recomputed the hash. The dead half is now
removed; this is the live half.

**Fix (not done):** carry the full 64-bit hash from dispatch to the flat probe. The vehicle already
exists in shape — the fake already carries `tomo_bkt`/`tomo_bkt_ptr` with a pointer-match guard, so
the same idiom extends to the hash.

**Why not tonight:** it threads a value through the `db.c`/`kvstore.c` lookup signatures, and a
stale or mismatched carried hash does not fail loudly — it silently looks up the WRONG key. That
needs a discriminating test (seed distinct keys whose hashes collide in the low 14 bits, verify each
resolves to its own value) before the change, not after. Estimated worth ~1-2% on small-value
GET/SET, where xxh64 over a ~20-byte key is a meaningful slice of a ~500ns/worker command budget.

### A10. #44 `qb_pos == 0` assert — DIAGNOSED AND FIXED (server kill, pre-existing)

`processCommandAndResetClient()` signals "my client was freed underneath me" by testing
`server.current_client[iotid].p` for NULL. Upstream documents that this is sound *only* because
nested frames restore what they found. This fork's `processInputBuffer()` — where stock does not
touch the slot at all — hard-wrote `= NULL` after every command.

`processEventsWhileBlocked` re-enters `processInputBuffer` on the same thread, so a nested frame's
trailing NULL is what the **outer** frame reads → false `C_ERR` → `readQueryFromClient` does
`c = NULL` → skips the entire `done:` epilogue (the querybuf trim **and** `resetReusableQueryBuf`)
→ a live client keeps `qb_pos != 0` *and* the thread's reusable buffer → the next read that leaves
by an early `goto done` (EAGAIN, or `nread == 0` on close) trips the assert.

**The assert was right and is untouched.** Fix: save/restore the slot instead of blanking it, and
do not restore a pointer to a genuinely freed client. The outermost saved value is NULL, so
non-nested behaviour is byte-identical.

Same root cause also silently DROPPED clients at `iothread.c:623`
(`processPendingCommandAndInputBuffer` → false `C_ERR` → `continue`, client unlinked from every
list and never returned to its io thread).

**Repro: 20/20 before, 0/20 after**, both arms counter-instrumented and differing only by the patch.
The un-fixed server dies on its FIRST window entry; the fixed one enters the window ~half a million
times per run and survives. correctness_suite 15 passed, 0 failed.

### F-fenceblind. The fence suite cannot reach the #44 window — its "~25% flake" was a different path

Shipped `INFO tomokv_nested_cmd_frames` (frames executing while another frame is live on the same
thread) to settle why `fence_suite` scored 0/4 on a build that reproduces 20/20 under a targeted
repro. Measured on the fence's own config: `busy-reply-threshold` is **5000ms** and the fence's
"slow" EVAL takes **401ms** — it never crosses the threshold. Across the whole 20-iteration
crash-repro block: `Slow script detected` = 0, nested frames = **0**.

Its later 900M-iteration step does cross, but only nests when that script lands on the MAIN thread —
this fork restricts `processEventsWhileBlocked` to `iotid == 0`. One long script per run at ~1-in-4
io threads reproduces the historically reported "~20–30%/run", and P(0 hits in 4 runs) ≈ 0.32,
which is why single green fence runs looked like luck: they were.

**Rule: any future #44 regression check must assert `tomokv_nested_cmd_frames > 0` before it may
report a pass.** Otherwise it is testing a window it never entered.

### F-clientlb-node. Client LB is node-scoped for no structural reason (design note, 2026-07-28)

`tmClientBalanceCron` loops `for (int node ...)` and filters candidates with
`tmNodeOfIoSlot(all[i]) == node`, so a connection can only move between io threads **on its own
node**. On a single-node box the `nnodes == 1` shortcut makes this inert; on multi-node hardware it
would leave an idle node's io threads unusable while another node's saturate.

**Three objections to lifting it were raised and all three are wrong**, each because the mechanism
already exists:

1. *"Cross-node clients make the reply path cross-node."* It already is. `ex_bucket_table[b] =
   b * W / TOMO_BUCKETS` with W = **total** workers and no node partitioning, so a key maps to any
   worker on any node. A client already dispatches cross-node and gets replies back. This has been
   true by design since the bucket table existed.
2. *"The client struct can't change owner."* It already does — `iothread.c` assigns `c->tid`
   (`c->tid = min_id`), which is exactly the migration this would reuse.
3. *"The client's buffers are pinned to the original node."* They are not. `thread_reusable_qb` is
   `__thread` and `resetReusableQueryBuf` returns the buffer to the thread pool (`c->querybuf =
   NULL`), so between commands a client usually owns no querybuf at all — after a migration it
   borrows the NEW thread's, allocated on the new node. Reply-list blocks are allocated per reply by
   whoever writes them. Only the client struct (with its inline `buf[]`) is pinned, from accept().

**So the node filter is a conservative default, not a constraint.** The change is to drop the filter
and prefer local moves with a self-derived margin, so a cross-node move happens only when the
node-level imbalance is large enough to pay for re-homing one struct.

**Cannot be measured on this box** — one NUMA node, so `nnodes == 1` makes it structurally a no-op.
Gate it on the Threadripper.

**Process note, recorded because it recurred three times in one session:** each objection above was
a physically plausible story about NUMA locality that I produced *instead of* checking the
mechanism. Plausibility is not evidence; in every case one grep settled it. Check the mechanism
first.

---

## J. Verification sweep 2026-08-02 — "fix everything found and not confirmed fixed"

Every row below was re-tested against the tree at `f3ed56c50`, not trusted from an earlier filing.
Two rows changed status in the direction nobody wants: one "highest-priority open defect" turned out
to be already fixed, and one attempted fix turned out to be a worse bug than the one it fixed.

### J1. Set-op position-map leak — CONFIRMED FIXED

`HANDOFF_NEXT.md` §1 called this "the single highest-priority item": `SINTER`/`SINTERCARD`/`ZINTER`
leaking one spilled `setop_pos` row per request, because the SIZES stage owns two rows while
`g->nsub` is reused as the *current* stage's sub-count, so the free loop misses the spilled row.

Fixed by capturing the row count at build time in `csGroup.posmap_nsub` (`src/server.h:2023`,
built at `src/server.c:8962`, consumed by all four free sites: `:10148`, `:10149`, `:10533`, `:10540`).

Confirmed by measurement, with the preconditions **asserted** so the test cannot pass vacuously —
the first attempt built empty sets via `EVAL` and reported a clean result while exercising nothing:

    ex=2 (cross-shard), 24 sets x 200 members, scard=200 asserted, SINTER cardinality=200 asserted
    SINTER     used_memory deltas over 3 x 5000 requests: 24688, 0, 24688
    SINTERCARD used_memory deltas over 3 x 5000 requests: 0, 24688, 0

Non-monotonic and out of phase between the two commands: that is jemalloc bin stepping. A live
one-row-per-request leak is >=16 B x 5000 = >=80 KB per window and strictly increasing. It is not.

### J2. Active expiry on shard dbs (#42) — CONFIRMED FIXED

Was real: `activeExpireCycle()` walks `server.db`, which under sharding is the empty DECOY, so
`kvstoreSize(db->expires)` was 0 on every pass and **nothing was ever actively expired**. Lazy
expiry hid it from every observable read — only the memory of keys nobody reads leaked. Fixed by
`ee451` (`src/expire.c`), which runs the cycle on each worker over its own buckets, cadence
published by main via `server.tomo_expire_gen`.

Confirmed on both engines, clean dir, no stale RDB, 100000 keys at `EX 10`:

    ex=1 (DICT keyspace)  seeded 100000 -> dbsize 0 at t=20s, expired_keys_active=100000
    ex=4 (FLATSTORE)      seeded 100000 -> dbsize 0 at t=20s, expired_keys_active=100000

Minor open discrepancy, not chased: at ex=4 `expired_keys_active=100000` but `expired_keys=99996`.
Four keys are counted by one counter and not the other.

### J3. `DEBUG RELOAD` under concurrent write load kills the server — OPEN, fix reverted

Reproduces 8/8: `Guru Meditation: Duplicated key found in RDB file #rdb.c:4016`.

Corrected diagnosis (the earlier filing blamed a FLATSTORE residual, which sent the previous
investigation the wrong way):
 * **load-dependent, engine-INDEPENDENT** — FLAT idle OK / FLAT under load FAIL; DICT idle OK /
   DICT under load FAIL;
 * the duplicate key always carries the *concurrent writer's* prefix, never the seeded prefix, so
   it is **post-flush re-insertion**, not a save-side double-emit;
 * `SAVE` and `BGSAVE` are both clean under the same load (RDB loads, restart OK, dbsize preserved)
   — there is **no durability bug** here.

The invariant that is actually violated: between `emptyData()` and the end of `rdbLoad()` no other
writer may insert, and `dbAddRDBLoad` is a non-worker writer racing live workers.

**A stop-the-world fix was implemented and then REVERTED — it is strictly worse than the crash.**
It parked workers at their pop point on a new `tomo_stw_active` flag. It stopped the crash (reload
completed, `keys loaded: 300001`, no Guru) and then wedged the whole server. Cause: it parked
workers without first waiting out an armed resize, and without pumping the coordinators while
waiting — neither guard, both of which the existing flush path has. See J4, which is the general
defect it exposed. Do not re-attempt this shape without J4 addressed.

### J4. P0-class: the FLATSTORE resize unpark had a single driver and no watchdog — **FIXED `4754a73a5`**

Found while diagnosing J3, but **independent of `DEBUG RELOAD`** and shipping-relevant.

`flat_resize_active = 1` parks every worker. It can only be cleared by `flatResizeCoordinate()`,
which at every spin site runs `if (iotid == 0)` — and main *is* IO slot 0. So:

    resize arms -> all workers park -> main blocks for any reason
      -> nobody calls flatResizeCoordinate() -> flag never clears -> workers parked forever

The `FLAT_RZ_QUIESCE_DEADLINE_US` (200 ms) escape added as "fix #6" **cannot save this**, because it
is evaluated *inside the same coordinator* — the deadline is driven by exactly the thread whose
blocking caused the wedge. `FLAT_RZ_COPYING` has no deadline at all.

Observed state of the wedged process (pid 1345529), 18 minutes after the reload returned:

    tomokv_flat_resize_active:1      tomokv_ex_queue_full:0
    main  (= IO slot 0)  state=S  wchan=futex_do_wait    <-- the single driver, blocked
    4 workers            state=R  ~100% CPU              <-- spinning in the park loop
    1 IO thread          state=R  ~100% CPU              <-- spinning on a parked worker
    2 IO threads         state=S  wchan=ep_poll
    PING/DBSIZE answer intermittently (IO-thread work); every worker-routed command hangs forever.

Zero `FLATSTORE resize:` lines in the log — neither the "rebuilt" completion nor the "quiesce
deadline" warning — which is the proof the coordinator stopped being *called* while armed, rather
than looping.

This is the same class as A10 (`af9d6b590`): one stuck coordinator flag is a delayed server kill.

**FIXED in `4754a73a5`.** `flat_rz_state` became atomic and the QUIESCING exit became a **CAS**,
shared between the coordinator's `QUIESCING -> COPYING` transition and a new
`flatResizeAbortQuiesce()`. Exactly one caller can win, so a watchdog can never race a copy into
existence, and two concurrent aborters can never both release `mig_arm_lock` (which would hand a
migration that armed in between a lock it does not hold). `flatResizeWatchdog()` is called only from
the two sites where a thread ALREADY SPINS waiting out a resize — the worker park loop (throttled to
1 per 1024 yields) and the io-thread resize wait — so it costs nothing on any path that is not
already stalled, and a running server never calls it at all.

Safe because in QUIESCING the coordinator has allocated nothing and mutated nothing: undoing it is
exactly what its own deadline path already does. The resize is not lost — `resize_needed` stays set
and the next pass re-arms. Aborting in COPYING would be the use-after-free the mutual exclusion
exists to prevent, which is why the CAS refuses any state that is not QUIESCING.

Proven to ENGAGE, not merely to compile — the first attempt (stall io threads with `DEBUG SLEEP`)
reported `WATCHDOG_ABORTS=0` and was discarded rather than written up as a pass:

    deadlines inverted (watchdog 1ms, coordinator 60s) so the watchdog must win every quiesce:
      WATCHDOG_ABORTS=278, matching log lines, dbsize=3000004 intact, no crash, no wedge
      -> 278 forced aborts are non-destructive
    shipped constants (watchdog 2s, coordinator 200ms):
      WATCHDOG_ABORTS=0, resizes complete normally, no spurious fires

New INFO field `tomokv_flat_resize_watchdog_aborts` — 0 on a healthy server; any non-zero value is a
real incident, not noise.

Note this does NOT fix J3: the watchdog converts "server dead forever" into "server recovers", which
is what a watchdog is for, but a `DEBUG RELOAD` that unparks workers mid-load still re-admits the
concurrent writes that cause the duplicate-key crash.

### J5. 13 of 41 bigstress cases certify nothing — harness debt, not a server defect

The full gate reads `PASS=28 FAIL=0 INCONCLUSIVE=13`. **All 13 are `ENGAGED=NO`**, and all 13 are
the LB/reshard/handoff cases — the riskiest subsystem in the tree:

    roles=1/1->none->1/1   completed-flips=0   controller-conversions=0
    moves=0/1              moves=0/0           normalized-decisions=0
    accepted=0             moved-survivors=0   qualifying-traffic-range=NO

Cause: the harness selects the DICT engine by dropping to **one EX worker**
(`dict_auto OWNERSHIP-MOVE-DICT-AUTO 1 1 auto DICT`), because `shared_node_dbs = (workers_per_node > 1)`.
But FLATSTORE has been **unconditional since 2026-07-28** — the knob was deleted — so "DICT" no
longer names an engine choice, it names "ex=1, single worker". With one worker there is nowhere for
a bucket to move and nothing for the controller to convert. These cases cannot ever engage.

Coverage is **not** actually missing: every FLAT counterpart engages and passes, with evidence —
`moved-canaries=694`, `coverage=COMPLETE`, `aborts=0`, `completed-flips=5`, `accepted=2
moved-survivors=31 disconnects=0`, digests identical across arms.

Fix is to the harness, not the server: the DICT arms should be relabelled as what they now are
(single-worker functional-equivalence checks) and the engine-equivalence pair renamed to
worker-count equivalence, so `INCONCLUSIVE` stops meaning "we never tested it" in a report that
otherwise reads as healthy.

### J6. RETRACTED — `DEBUG RELOAD` does NOT orphans client sockets. I filed this on bad evidence.

**The original filing was wrong and is retracted in full.** Recording it rather than deleting it,
because the way it went wrong is the reusable lesson.

What I claimed: after a reload the server showed `connected_clients:1` while `ss` still showed 15
ESTABLISHED sockets with `recvq=2262`, so the reload must have detached clients from the census and
their event loop without closing the fds.

Why that was wrong — **`connected_clients` is per-io-thread**:

    "connected_clients:%lu\r\n", listLength(server.clients[iotid]) - listLength(server.slaves),

`server.clients` is an array indexed by io thread. `connected_clients:1` meant "one client on the io
thread that happened to answer this INFO" — the `redis-cli` asking the question, which `CLIENT LIST`
showed on `io-thread=3`. `CLIENT LIST` is scoped identically, which is why it also showed one entry.
The other connections were on the other three io threads, alive and being served. And `recvq=2262`
spread over 15 connections is ~150 B each: ordinary in-flight pipelining, not an unread backlog.

A second attempt to prove it was also invalid, in a different way: the probe encoded `k%06d`
(7 bytes) behind a `$8` length header, so the server correctly closed every connection on a protocol
error and the probe reported 12/12 "stalled". The tell was that it measured **1 op per connection in
3 seconds**, which is nonsense for a local Redis — the plausibility check caught it, the result did
not.

**What actually happens, measured with a correct probe** (16 connections, pipeline depth 4, reading
exactly as many replies as requests sent so a lost reply shows up as a read timeout):

    pre-reload total ops: 628672
    DEBUG RELOAD -> OK
    LOADING replies seen: 836
    post-reload progress/conn: [104348, 103556, 104504, ... , 104308]   (all 16)
    HUNG conns: []          VERDICT: ALL LIVE

Every connection survives. The 836 `-LOADING` responses are *valid replies* delivered during the
load window, not lost ones. `loading` returns to 0 as soon as the reload completes (measured every
3 s for 36 s: `loading=0 SET=OK` throughout). There is no lost reply, no desync, no orphaned socket.

**The residual is in the load generator, not the server.** `memtier_benchmark` treats `-LOADING` as
an error response, logs it (94 KB of `handle error response: -LOADING ...` in one run) and then never
terminates the run — which is what produced the "memtier hung for 22 minutes" observation that
started this. A `--test-time=15` run was still resident 36 s later while a concurrently-connected
`redis-cli` was served normally the whole time.

Consequence for J3: with `ALLOW_DUP` in place, `DEBUG RELOAD` under concurrent load is **correct** —
the server survives, clients are served, and clients that speak Redis properly (retry on `-LOADING`,
as any client must during any load) see only a brief error window. What it is not is *transparent*,
and a benchmark tool that cannot tolerate `-LOADING` will appear to hang against it.

**Lesson, twice over in one session: check a counter\'s SCOPE before reasoning from it, and
plausibility-check a probe\'s own baseline before trusting its verdict.** Both wrong filings would
have been caught by asking "is this number physically sensible?" first.

---

## K. stress_validation — the ~2h soak, and what building it found

`tools/preflight/stress_validation.sh` + `stress_validation.py`. ONE long-lived server per NUMA
topology (1 node, then 2), each driven ~55 minutes without a restart, while every command family,
connection churn, keyspace growth/shrink, thread-mode flips, key-balancer reshards and FLATSTORE
resizes all happen concurrently on that same process. Restarting between cases hides exactly the
defects it is looking for.

Run it after every big change. It stops on the first failure by design: a soak resumed after a fix
has not soaked.

### K1. `OBJECT` / `MEMORY USAGE` answered from the empty decoy db — FIXED

Found by the new suite's first self-test. `OBJECT ENCODING key` returned **nil** for a key that
plainly existed; so did `OBJECT REFCOUNT`, `OBJECT FREQ` and `MEMORY USAGE`. `TYPE`, `TTL`,
`STRLEN`, `LLEN`, `DUMP`, `LPOS` and ~20 others were all correct, so the blast radius was exactly
the commands whose key is **not at argv[1]**.

Mechanism, and it is the same class already fixed once for SCAN: `getWorkerForCommand` hashes
`argv[1]`, but `OBJECT ENCODING key` carries the SUBCOMMAND there. They were also absent from
`canDispatchToWorker`, so they never reached a worker at all — they ran INLINE on the io thread,
where the only db in scope is the deliberately-empty `server.db` decoy. Silent: a caller cannot
distinguish "no such key" from "asked the wrong shard".

Fixed by routing them on `argv[2]` via a single `tomoKeyAtArgv2()` predicate shared by the dispatch
decision and the shard hash — kept as one predicate precisely so the two can never disagree about
which argument is the key, which would route to one worker and look up on another. Verified:

    OBJECT ENCODING -> embstr     OBJECT REFCOUNT -> 1     MEMORY USAGE -> 40
    OBJECT FREQ     -> the correct upstream "LFU policy not selected" error, not a silent nil

`DEBUG OBJECT` still reports `ERR no such key` — DEBUG runs inline by design, and a loud error is
not the silent-wrong-answer class. Left alone.

### K2. `handoff_missed` is a RATE, not a must-be-zero invariant — filing corrected, no code change

The sparse-handoff merge shipped `tomokv_handoff_missed` with "MUST be 0" in its comment, and the
new soak promptly measured 2–5 per 4-minute phase on a healthy server.

It is not the flip controller. A/B, same load:

    static (0 flips) -> 5        auto (5 flips) -> 0        static (0 flips) -> 2

The reason it cannot be zero: a producer must store its item **before** OR-ing its summary bit.
Advertising first would let a consumer drain the lane, clear the bit, and only then have the item
land — which is the genuine strand this protocol exists to prevent. So there is an inherent
store-to-advertise window in which a lane legitimately holds work with no bit set anywhere, and the
existing live-word check cannot exclude it (it only excludes producers that published after the
consumer's exchange).

**An attempted fix was written and then reverted before shipping.** It only counted a lane that was
unadvertised-with-work on two consecutive dense sweeps. That looked right and measured 0/0 on a
healthy server — but `residual` is OR'd back into `q_summary` at the end of every pass, so a suspect
lane is *always* advertised again by the next dense sweep. The refined oracle would therefore have
read ~0 even with `exHandoffAdvertise()` completely broken: a vacuous counter, strictly worse than
the over-strict one. It was reverted rather than shipped on the strength of a green run.

Current disposition: the counter is unchanged, and `stress_validation` judges it as a ceiling of
5 misses per million commands (healthy measures ~0.1/M) instead of zero. A systematically broken
publish site is orders of magnitude above that. A properly discriminating oracle — one that survives
a defect-injection test against a build with the advertise call removed — is still open work.

### K3. A gate must not be perturbable by a file in the working directory — FIXED

The full gate failed `ROLE-CONTROLLER-GATE` with `seed materialized DBSIZE=2000001, expected
2000000`, in both flip directions, deterministically. Not a server regression: `flipcmp.sh` booted
its server with **no `--dir`**, so it inherited the caller's CWD and silently loaded a `dump.rdb`
that an unrelated `DEBUG RELOAD` test had left in the repo root. That RDB held 300001 keys; the 2M
seed overwrote all of them except **`memtier-0`** — written by a `--key-pattern=R:R` run, index 0
being outside the 1..2000000 seed range — leaving exactly one extra key.

`flipcmp.sh` now boots with an explicit, emptied `--dir`. `stress_validation.sh` does the same, and
says why.

### K4. FULL mode: `NA` is now distinct from `SKIP`

J5 made structurally-impossible cases report `SKIP NOT-APPLICABLE`, which then tripped
`FULL-COVERAGE` ("full mode emits even one SKIP row") — correctly, because SKIP means "we chose not
to run this" and in FULL mode that is a coverage gap. Added a separate `NA` class: SKIP still fails
FULL coverage, NA does not, and the summary reports both.

---

## L. A3 acceptance — the back-pressure path no test had ever entered (2026-08-02)

### L1. The gap

`exDispatchPush()` and `csPushSpin()` each contain a spin loop taken only when a worker's SPSC ring
is full, and A3 changed both (publish *every* staged ring, not just the one being waited on).
Neither loop was ever entered by any test in this tree: `INFO tomokv_ex_queue_full` read **0**
across a full `bigstress` run *and* across the first complete `stress_validation` soak
(`cycle 1 ... qfull=0`). A fix to a path no test enters is indistinguishable from no fix — the
vacuous-validation class already recorded in §E and §J5.

### L2. One counter could not attribute the path — SPLIT

Both sites bumped the same `q_full_events`, so a probe that drove the total above zero could not
say *which* loop it had entered, and could have "passed" while leaving one site untouched. Added
`q_full_cs_events` (owner-written, on an already-spinning path) and `INFO
tomokv_ex_queue_full_xshard`. The original field keeps its meaning as the combined total, so this
is additive; it is recorded as the pending intentional diff in
`tools/preflight/surface_baseline.sha`.

### L3. `csPushSpin`'s stated justification was obsolete — CORRECTED

Its docstring justified the immediate-publish design with *"a single MGET may stage more subs than
the queue depth ... so the push would deadlock."* That has not been true since xshard OPT-1: the
coalesced scatter builds **one sub per worker**, not one per key, so a single command stages at
most `nw` ≤ 64 subs into 64 *distinct* rings — one each — against a depth of 2048. The other two
call sites (set-op `GATHER1`, `PROBE`) push exactly one sub. **No single command can overflow a
ring.**

This matters beyond tidiness: anyone sizing the ring or reasoning about scatter deadlock from that
comment would be reasoning from a condition that no longer exists, and the acceptance probe would
have been built to reproduce the wrong thing (one wide MGET). Back-pressure is reachable only via
**many concurrent** commands from one io thread to one worker. The immediate publish is still
required, for a different reason now stated in the comment: the scatter's caller is blocked on
these subs, so leaving one staged defers it to the next `beforeSleep`.

### L4. `queues[]` was indexable out of bounds by construction — ASSERTED

`exThread.queues[]` has `TOMO_IO_THREADS_MAX + 1` = 33 lanes and is indexed by `iotid`, but a
**worker's** `iotid` is `TOMO_IO_THREADS_MAX + 1 + ex_slot` — always ≥ 33. A worker-side call would
therefore be a silent OOB write into the next `exThread`'s ring, not a benign mistake. It was
correct only because every call site happened to be IO-side, which nothing enforced. A2 had already
funnelled all staging through `exQueueFor()`, so one `debugServerAssert` there covers every site;
`debugServerAssert` rather than `serverAssert` because the property is structural (which thread
calls it) and cannot first fail under production load.

### L5. The probe — `tools/preflight/ex_backpressure.sh`

Four arms on **one** server: two negative controls at low concurrency that must leave both counters
at **0**, and two saturation arms that must drive their own counter above 0 — `S1` a deep pipeline
on a single key (one bucket ⇒ one worker ⇒ one ring) for `exDispatchPush`, `S2` deeply pipelined
multi-key `MGET`s for `csPushSpin`. Every reply is verified, so it also asserts correctness *while*
an io thread is spinning inside the loop. The control arms are what make the result attributable:
without them, "counter > 0" would not distinguish induced saturation from a counter that climbs
under any load.

**What it does not prove:** A3's *benefit*. The counter increments with or without A3, which
changed only what is published inside the spin — i.e. drain latency. Demonstrating that needs an
A/B against an A3-reverted build. This probe establishes reachability and correctness under
back-pressure, and must not be cited for more.

### L6. `SURFACE-GATE` was comparing the binary against itself — BASELINE PINNED

The one remaining `INCONCLUSIVE` was honest: with no `SURFACE_BASE`, `bigstress` passed `$STAGED`
as both base and candidate, and "byte-identical" is vacuous against yourself. Added
`surface_baseline.sha` (a deliberately-lagging pinned commit, with the rules for moving it) and
`surface_baseline.sh` (builds it once into a SHA-keyed cache, in a throwaway worktree so the
caller's tree is never touched). `bigstress` now defaults to it, and falls back to the old
self-compare — staying `INCONCLUSIVE` — if the pin cannot be built, because failing a run over a
missing baseline would be wrong and passing it would be a lie.

### L7. `withbox.sh` was not in the repo

`stress_validation.sh` documents its own invocation as `tools/preflight/withbox.sh`, which did not
exist — the shared box lock lived only in a job scratch directory. The mandatory gate was therefore
not reproducible from a clone. Copied in verbatim.

---

## M. DEBUG RELOAD silently LOSES replies for in-flight commands (2026-08-02) — OPEN

**Found by `stress_validation`, on its first run that got far enough to find anything.** Phase
numa1, cycle 2. This is the defect class the soak was built for: no crash, no log marker, only a
client that waits forever.

### M1. Evidence

Soak, verbatim:

    20:37:17.332  DB saved on disk
    20:37:17.620  DB reloaded by DEBUG RELOAD     <- 288 ms, clean, +OK
    20:37:47.445  FAIL [bulk-conn] TimeoutError   <- exactly 30 s later = the CLIENT's own timeout

`SOAK-numa1-SURVIVAL PASS` (server answered PING after 1242 s) and `CLEAN-LOG PASS markers=0` — the
server was entirely healthy. Only pre-existing connections were affected.

Reduced to `tools/preflight/reload_client_wedge.py`, which reproduces it in ~90 s, 3 runs of 3:

    control: fresh conn under load, BEFORE reload  -> PONG in 0.005s     PASSES
    DEBUG RELOAD                                   -> OK in 0.687s
    fresh conn after reload / idle conn            -> fine
    in-flight lanes                                -> 2 of 8 wedged, 480 replies missing
    late replies once the load stopped             -> 0

**`late = 0` is the finding.** With the load stopped and 3 s of grace per wedged lane, not one of
the 480 replies ever arrived. They are **lost, not late**. The socket stays open and the server
stays healthy, so the client is permanently desynchronised from its own reply stream — it can never
resynchronise, because RESP has no reply framing to resynchronise to.

The control is what makes this attributable, and it is not optional: a fresh connection served in
5 ms under the identical load immediately before the reload rules out "the server was just busy".
J6 was filed and retracted twice for want of exactly that control.

### M2. Root cause is already on the record

`src/debug.c` (the J3 fix) states it outright:

> *emptyData() and rdbLoad() are not atomic with respect to the workers: the workers keep going ...
> This does NOT make the reload atomic — rdbLoad remains a non-owner writer of the shared node dbs.
> It removes the kill.*

J3 fixed the **crash** (duplicate keys ⇒ Guru) and knowingly left the **non-atomicity**. M is that
residue: the keyspace is swapped underneath commands already dispatched to workers, and their
replies are never published. J3's scope was correct — it just was not the whole defect, and nothing
recorded that the remainder was still live until the soak hit it.

### M3. The fix, and the trap in front of it

The shape is a **drain fence**: quiesce in-flight worker dispatches and publish their replies before
`emptyData()`, and hold new dispatches until `rdbLoad()` completes. The machinery exists — the
FLATSTORE resize quiesce (hardened in J4 with a CAS'd state and a watchdog) and the migration
drain-fence are both this primitive.

**Do not reach for a naive stop-the-world.** One was already written and reverted this session
because it converted a crash into a whole-server wedge: it parked the workers without waiting out an
armed resize and without pumping the coordinators, both of which the flush path does. Any fix here
must satisfy the same two obligations, and `flatResizeWatchdog()` is the precedent for making the
quiesce recoverable rather than trusting it.

### M4. Status

**OPEN.** Reproducer committed and green-as-in-reproduces. Not yet fixed. `stress_validation` cannot
pass until it is, because the soak exercises `DEBUG RELOAD` under load on every even cycle — which
is precisely why it was written that way.
