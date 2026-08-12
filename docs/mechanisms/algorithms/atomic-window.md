# tomokv-atomic-window: the atomic-write admission window

`tomokv-atomic-window` bounds the number of **admitted in-flight atomic-write groups**.
It is the last gate before a command takes a fake-ring slot: a refused command parks
its client and waits for a slot to open instead of dispatching. The window exists
because the read-your-own-write pile a reader must scan is ~window-deep under saturated
atomic writes, so an unbounded window craters throughput on write-heavy mixes.

Verified against `src/server.c`, `src/config.c`, `src/server.h`. Line numbers are that
tree's. Only consulted when `tomokv-atomic != 0`.

> **Scope correction (trust the code).** The window bounds a **server-global** admitted
> count, not a per-connection one. `tomo_atomic_inflight` is a single
> cache-line-isolated global atomic that every IO thread CAS-increments per admitted
> group (`src/server.c:313-315`). The parking *lists* are per-IO-thread
> (`clients_atomic_window_parked[iotid]`), but the bound they enforce is global. Any
> description of a "per-connection in-flight bound" is imprecise relative to the code.

---

## 1. The knob and the counter

```c
/* src/config.c:3183-3184 */
createBoolConfig("tomokv-atomic",        NULL, MODIFIABLE_CONFIG, server.tomo_atomic, 0, ...);
createIntConfig ("tomokv-atomic-window", NULL, MODIFIABLE_CONFIG, 0, INT_MAX,
                 server.tomo_atomic_window, 64, INTEGER_CONFIG, NULL, applyTomoAtomicAdmission);
```

- `tomokv-atomic-window`: `MODIFIABLE`, range `0..INT_MAX`, **default 64**.
- Window `0` = **unlimited** (never refuses) but still counted for observability /
  exactly-once auditing (`src/server.c:457-465`).

```c
/* src/server.c:313-315 — own cache line, CAS'd by every IO thread per group */
static struct { _Atomic int v; char pad[CACHE_LINE_SIZE - sizeof(_Atomic int)]; }
    tomo_atomic_inflight_line __attribute__((aligned(CACHE_LINE_SIZE)));
#define tomo_atomic_inflight (tomo_atomic_inflight_line.v)
```

A companion global `tomo_atomic_unsealed` (`src/server.c:340-342`) is reserved beside
`tomo_atomic_inflight` at admission but retired earlier (see §5).

---

## 2. Admission — the CAS below the bound

`tomoAtomicMsetTryReserve(window)` (`src/server.c:460-477`):

```c
if (window == 0) {                                         /* unlimited */
    atomic_fetch_add_explicit(&tomo_atomic_inflight, 1, relaxed);
    atomic_fetch_add_explicit(&tomo_atomic_unsealed, 1, seq_cst);
    return 1;
}
int cur = atomic_load_explicit(&tomo_atomic_inflight, relaxed);
while (cur < window) {                                     /* finite: CAS strictly below bound */
    if (atomic_compare_exchange_weak_explicit(&tomo_atomic_inflight, &cur, cur + 1,
                                              relaxed, relaxed)) {
        atomic_fetch_add_explicit(&tomo_atomic_unsealed, 1, seq_cst);
        return 1;
    }
    /* failed CAS refreshed cur; do not race past the bound */
}
return 0;                                                  /* refused */
```

Using the counter itself as the CAS word makes the bound **strict** across concurrent
IO producers — a load-then-increment could overshoot by up to the IO-thread count
(`src/server.c:303-310`). Every successful reserve seq-cst-increments
`tomo_atomic_unsealed` (`:463`, `:471`).

### Where it sits in dispatch

The admission block is nested under `server.tomo_atomic != 0` and is the last gate
before fake-ring allocation (`src/server.c:8338-8387`). For an atomic-write shape:

```c
if (window == 0) {
    if (atomic_write) { tomoAtomicMsetTryReserve(0); ... atomic_write_admission = 1; }
} else if (atomic_write) {
    if (!tomoAtomicMsetTryReserve(window)) {
        tomoAtomicParkWindowClient(c);          /* refused → park :8379 */
        return C_OK;
    }
    ... atomic_write_admission = 1;             /* :8383-8384 */
}
```

On refusal nothing is allocated: no group/sub exists, `dispatchid` is unchanged, and
the decoded pending command stays the executable input head for a later retry
(`src/server.c:8338-8343`). Only an **atomic-write** shape is gated; atomic *reads*
draw a snapshot but are never window-refused (`src/server.c:8358-8362`).

The cutover gate (reshard) is checked seq-cst before the reserve and re-checked after
via `tomoAtomicCutoverRaceAfterReserve`, a Dekker-style handshake that backs out both
counters if it loses (`src/server.c:8365-8385`, `529-539`).

---

## 3. Parking a refused command

`tomoAtomicParkWindowClient` (`src/server.c:508-515`) enrolls the client and marks it:

```c
tomoAtomicEnrollWaiter(c);   /* → clients_atomic_window_parked[iotid], tomo_atomic_waiters++ */
c->flags |= CLIENT_ATOMIC_WINDOW_STALLED | CLIENT_PIPELINE_STALLED;   /* :510 */
tomoAtomicWakeProducer(iotid);   /* close retire-vs-park missed-wakeup race :514 */
```

| Flag | Value | Meaning |
| --- | --- | --- |
| `CLIENT_PIPELINE_STALLED` | `1ULL << 56` (`src/server.h:443`) | Suppresses `commandProcessed`, keeping the pending head executable. |
| `CLIENT_ATOMIC_WINDOW_STALLED` | `1ULL << 58` (`src/server.h:451`) | Marks this client as window-parked. |

Per-client parking state (`clientExecTail`, `src/server.h:1794`, `1857`):
`atomic_window_parked_node` (list node) and `atomic_window_parked_tid` (owning IO id).
`tomo_atomic_waiters` (`src/server.c:317`) is the global waiter count that gates the
retry walk.

---

## 4. The retry walk

`tomoAtomicReleaseStalledClients` runs in a **later** event-loop frame from
`beforeSleep`/`beforeSleepIO`, after reply drain (`src/server.c:547-586`):

```c
if (tomo_atomic_waiters == 0) return;                       /* :556 fast out */
list *l = server.clients_atomic_window_parked[iotid];       /* this owner's list only */
while (l && listLength(l) != 0) {
    int window = server.tomo_atomic ? server.tomo_atomic_window : 0;
    int window_open = window <= 0 ||
        atomic_load_explicit(&tomo_atomic_inflight, relaxed) < window;   /* :561-562 */
    int cutover_open = atomic_load_explicit(&tomo_atomic_cutover_gate, seq_cst) == 0;
    /* pick first STALLED candidate while window_open && cutover_open :570-577 */
    if (!c) return;
    tomoAtomicDropWaiter(c);
    c->flags &= ~(CLIENT_ATOMIC_WINDOW_STALLED | CLIENT_PIPELINE_STALLED);
    processInputBuffer(c);          /* may free c — do not touch after :584 */
}
```

The walk re-evaluates the shared list after every client, because a released command
can immediately re-park if another producer consumes the opened slot first
(`src/server.c:547-550`). A parked client re-admitted *outside* this walk (chunked
`readQueryFromClient` re-running admission on the parked head) is un-parked at the top
of dispatch to avoid a stale `PIPELINE_STALLED` (`src/server.c:8389-8400`).

Config changes wake the walk: `applyTomoAtomicAdmission` calls `tomoAtomicWindowChanged`
on any enable/disable/window change, which `WakeAll`s producer loops if waiters exist
(`src/config.c:3141-3149`, `src/server.c:452-455`).

---

## 5. Retirement — where the slot is released

Admission and retirement are asymmetric:

- **`tomo_atomic_inflight`** is decremented at the group's single terminal reassembly
  (`csReassemble`), not at commit (`src/server.c:15313-15325`):

  ```c
  if (g->versioned_write) {
      atomic_fetch_sub_explicit(&tomo_atomic_inflight, 1, relaxed);   /* :15314 */
      atomic_thread_fence(memory_order_seq_cst);                      /* :15322 */
      if (tomo_atomic_waiters != 0) tomoAtomicWakeAll();              /* :15323-15324 */
  }
  ```

  The seq-cst fence closes a Dekker pair with the park side: both relaxed would
  legalize a lost wakeup (last-group retire skips the wake while the parker's release
  pass saw the pre-decrement count) (`src/server.c:15316-15321`). The park side
  self-wakes unconditionally after enrolling, so it needs no fence.

- **`tomo_atomic_unsealed`** is decremented **earlier**, in commit loop 2 at
  `tomoAtomicLifecycleGroupSealed` (`src/server.c:10389`, `541-544`), once all
  owner-affine jobs are materialized. This is the census the reshard cutover waits on,
  not client reply reassembly (`src/server.c:338-342`,
  `CORRECTNESS_REGISTER.md` §H5).

So the finite window counts admitted groups all the way through IO-side group teardown,
while the cutover census (`unsealed`) stops counting as soon as a group's jobs exist.

---

## 6. The crater / 64-vs-512 finding

The default of **64** is a tuned value, not arbitrary. The project's benchmarks found a
**superlinear "crater"** on write-heavy overlapping mixes (notably 1:1 MGET:MSET) when
the window was large: a deep admitted pile makes every own-read scan the pile, and the
arrival-order frontier convoy collapses window throughput. Narrowing the window from
**512 → 64** gave roughly a **4.8× improvement** on the 1:1 crater while leaving disjoint
traffic unaffected.

> The 512→64 / ~4.8× numbers are **measured benchmark findings** from the atomic-path
> evaluation (recorded in the project's ownread-wedge / atomic-window work), not
> constants in the pinned code. The code's contribution is the mechanism: the strict
> CAS bound (`src/server.c:460-477`) and the Stage-1 own-scan relevance gate that makes
> the per-read pile cost `O(0)` when a reader has no pending install
> (`src/server.c:10215-10240`; [own-read-widening.md](own-read-widening.md)). The
> default itself is set at `src/config.c:3184`.

## 7. Memory orderings

| Operation | Order | Site |
| --- | --- | --- |
| `tomo_atomic_inflight` reserve (finite) | relaxed CAS | `src/server.c:468` |
| `tomo_atomic_inflight` reserve (window 0) | relaxed fetch-add | `src/server.c:462` |
| `tomo_atomic_unsealed` reserve | seq-cst fetch-add | `src/server.c:463`, `471` |
| `tomo_atomic_inflight` retire | relaxed fetch-sub + seq-cst fence | `src/server.c:15314-15322` |
| `tomo_atomic_waiters` | relaxed inc/dec, relaxed read | `src/server.c:504`, `486`, `556` |
| cutover gate | seq-cst load | `src/server.c:8366`, `564` |

## 8. Invariants

1. A finite window admits only via a successful CAS strictly below the bound; window 0
   never refuses but still participates in census and teardown.
   (`src/server.c:457-476`, `15306-15324`)
2. A refused command allocates nothing and leaves its pending head executable for retry.
   (`src/server.c:8338-8343`)
3. Every `versioned_write` group has exactly one `tomo_atomic_inflight` increment
   (admission) and one decrement (`csReassemble`); no non-atomic group touches the
   counter. (`src/server.c:15306-15315`)
4. Retire-then-check-waiters and enroll-then-check-inflight are a seq-cst Dekker pair;
   no parked client is left un-woken on an idle thread. (`src/server.c:15316-15324`,
   `508-515`)

## File:line map

| Area | Site |
| --- | --- |
| Knob + default | `src/config.c:3183-3184` |
| `tomo_atomic_inflight` / `tomo_atomic_unsealed` lines | `src/server.c:313-315`, `340-342` |
| `tomoAtomicMsetTryReserve` | `src/server.c:457-477` |
| Admission gate in dispatch | `src/server.c:8338-8387` |
| Park / enroll / flags | `src/server.c:497-524`, `src/server.h:443`, `451` |
| Retry walk | `src/server.c:547-586` |
| Terminal retirement | `src/server.c:15306-15325` |
| Own-scan relevance gate (crater mitigation) | `src/server.c:10215-10240` |
| Config apply + wake | `src/config.c:3141-3149`, `src/server.c:452-455` |
