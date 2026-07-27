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
| #19 | reshard cutover fence — see the corrected breakdown in §H below | auto-reshard now defaulted **OFF** (`331d305ee`), so the exposure is removed |
| #44 | fence `qb_pos == 0` assert under slow-script + SCRIPT KILL, ~20–30%/run, reproduces on pushed production | root cause unconfirmed |
| #48 | reshard read-straddle (part of #19) | |
| #49 | pipelined **cross-key** non-serialisation — owner ruled *not guaranteed*, so **document, don't fix** | |
| — | `SCAN` returns 0 keys when `!(flat_store && shared_node_dbs)` | config-derived |

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

### H2. The drain check reads EMPTY mid-batch — REAL, not yet fixed

The coordinator acks a producer slot after ~2 ms of apparent queue emptiness (the idle-ack), but
`exQueuePopBatch` publishes `head` **before** executing the batch. A worker actively running 16 jobs
therefore reads as empty and gets acked while range primaries are still executing — the steady state
of a busy worker, not a rare race.

The correct fix (sentinel-complete fence) deletes the idle-ack and instead **wakes** idle producers
so each pushes a real sentinel; the notifier machinery exists but is gated on `thread_modes`.
Deliberately NOT attempted unattended: getting the producer-wake path wrong deadlocks a cutover,
and with auto-reshard defaulted off the remaining exposure is manual/opt-in only.

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
