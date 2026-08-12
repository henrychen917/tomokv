# Client-LB: continuous connection rebalance across IO threads

Client-LB moves whole client connections off a sustained busy-outlier IO thread onto the least-loaded
eligible IO thread — within a node, to a tolerance band, without changing sockets or protocol state.
It is the connection analog of the bucket balancer, and it shares the connection mailbox/handoff
machinery with grow-back evacuation. All in `src/server.c`.

Cron: `run_with_period(1000) tmClientBalanceCron()` — 1 Hz, main thread (`src/server.c:2948`).
Knob: `tomokv-client-lb` → `server.tm_client_lb` (`bool`, default 1; `config.c:3311`). There is a
separate one-shot flip-time backfill (`tmRebalanceOntoNewIo`) gated by the derived
`server.tm_flip_rebalance = server.thread_auto` (`src/server.c:5625`).

## The two per-thread signals

- **Busy weight** `tmIoThreadBusy(id)` = raw Q4 `tm_io_sig[id].busy_ewma_q4` (`int`), an
  events-per-event-loop-pass EWMA updated every `ioSlice()` as
  `B += ((events << 4) - B) >> 3` (Q4, alpha 1/8), returned **without** dividing by 16
  (`src/server.c:23142`, `:23951-23952`). It is a relative connection-placement weight, **not** a flip
  ratio input (`src/server.h:670-671`).
- **Connection count** `tmIoThreadLoad(id)` = `listLength(server.clients[id])` — the authoritative
  per-thread count maintained by `linkClient`/`unlinkClient` on the owning thread; read cross-thread
  racy but non-torn (`src/server.c:23943-23945`).

Both are heuristics, not synchronized snapshots (`src/server.c:23937-23952`).

## Eligible destinations (`tmGatherLiveDests`, `src/server.c:23920-23935`)

IO ids `1..io_threads + tm_ngrow_io` (excludes main = slot 0), skipping any with
`io_exiting` set or whose ctx `mode` is not `TOMO_MODE_IO` (acquire load). A grown slot serving EX is
excluded by the mode gate.

## The continuous trigger (`tmClientBalanceCron`, `src/server.c:24030-24083`)

Per logical node, on each 1 Hz invocation:

```c
if (!server.tm_client_lb) return;                                          /* 24034: its OWN knob */
/* gather live dests, filter to this node (numa==1 => unfiltered) */
if (n < 2) continue;                                                       /* need >= 2 measured ids */
double tot_busy; long tot_conns;  /* summed over the node's dests */
if (tot_conns < n) continue;                                               /* < 1 conn/thread: trivial */
int use_busy = tot_busy > (double)n;                                       /* prefer busy; else conn count */
double mean  = use_busy ? tot_busy / n : (double)tot_conns / n;
/* hot = first strict maximum of the chosen metric */
if (hot < 0 || hotv <= mean * 1.25) { if (hot>=0) cli_hot_streak[hot]=0; continue; }   /* 25% band */
if (++cli_hot_streak[hot] < 3) continue;                                   /* sustain 3 ticks */
cli_hot_streak[hot] = 0;
long nc = tmIoThreadLoad(hot);   if (nc < 2) continue;                      /* keep >= 2 to move */
int count = use_busy ? (int)((hotv - mean) / (hotv / nc))                   /* busy: excess / per-conn busy */
                     : (int)(hotv - mean);                                  /* count: excess directly */
count /= 2;                                                                 /* DAMP: half the excess */
{ int cap = (int)(nc / 3); if (cap < 1) cap = 1; if (count > cap) count = cap; }
if (count < 1) continue;
if (count > nc - 1) count = (int)(nc - 1);                                  /* leave >= 1 on the source */
int dst = tmPlaceConnDest(hot, NULL);                                       /* least-loaded live dest */
if (dst < 0 || dst == hot) continue;
/* skip if the source mailbox is busy (req_pending / migrating_out / io_exiting) */
tmMigPublishReq(mb, TM_MIGREQ_REBALANCE, dst, count, 0); triggerEventNotifier(mb->notifier);
```

Step by step (matching `loadbalance-flip.md` "Signal and continuous trigger"):

1. Return globally on `!tm_client_lb`; gather live ids; filter **source measurement** to the current
   node; skip a node with `< 2` measured ids (`src/server.c:24034-24042`).
2. Sum raw Q4 busy and connection counts; skip when `tot_conns < n`; use busy only when
   `tot_busy > n`, else use connection counts (`src/server.c:24043-24050`).
3. Select the first strict maximum; when `hotv <= 1.25·mean`, reset only that id's streak and stop the
   node (`src/server.c:24051-24056`).
4. Increment that id's streak; proceed when it reaches 3, resetting it immediately
   (`src/server.c:24056-24058`).
5. Require `>= 2` source connections. Busy mode estimates `int((hot-mean)/(hot/nc))`; count mode uses
   `int(hot-mean)`; **integer-divide by two** (half-excess damping), cap at `max(1, nc/3)`, reject
   zero, leave `>= 1` on the source (`src/server.c:24059-24071`). Because the halving is after
   truncation, a computed excess of one becomes zero.
6. Choose the globally least-loaded eligible destination (`tmPlaceConnDest`, excluding the source),
   reject a busy source mailbox / nonempty outgoing list / exiting source, publish one request
   (`src/server.c:24072-24079`).

`cli_hot_streak[TOMO_IO_THREADS_MAX+1]` is `int`; the 3-tick streak is **not** consecutive-per-source
(streaks for non-current maxima are not reset, and disabled/skipped invocations do not clear the static
array — `loadbalance-flip.md` discrepancy #14).

## Destination choice — least-loaded, load-aware (`tmPlaceConnDest`, `src/server.c:24106-24119`)

Re-gathers the live set, picks the dest with minimum `tmIoThreadLoad(d) + in_flight[d]` (in-flight
folds this batch's already-placed conns so a burst spreads by real load). `in_flight` may be `NULL` for
a one-shot placement.

## Request publication (one packed atomic word, `src/server.c:22766-22778`)

```c
static inline uint64_t tmMigReqPack(kind, dest, count, then_ex) {
    return ((uint64_t)(uint32_t)count   << 32) |   /* bits 32-63: count       */
           ((uint64_t)(uint16_t)(dest+1)<< 16) |   /* bits 16-31: dest+1 (0 encodes -1) */
           ((uint64_t)(then_ex != 0)    <<  8) |   /* bit 8:      then_ex     */
           (uint8_t)kind;                           /* bits 0-7:   kind        */
}
tmMigPublishReq: store req_data (relaxed), then release-store req_pending = 1;
```

The source acquire-loads `req_pending`, relaxed-loads the payload, release-clears pending. Packing
prevents a mixed request but is **not** a CAS/queue: two publishers may both see no pending and
overwrite (`src/server.c:22761-22778`).

## Migratability and the quiesce fence

A client is migratable (`tmClientMigratable`, `src/server.c:23878-23902`) only when it has a
connection; is not cutover/atomic-window parked; is TCP; has none of the closing/protected/MULTI/
blocked/pubsub/replication/tracking/ASM/internal flags; has no watched keys; and no subscription
dictionaries.

Handoff waits for exact quiescence (`tmClientQuiesced`, `src/server.c:23906-23916`): `dispatchid ==
flushid` (ring empty), no pending replies, no `CLIENT_PENDING_WRITE`, `sentlen == 0`, and io_uring
migration readiness when attached — a stricter fence than the stateful-command ring fence
(`loadbalance-flip.md` discrepancy #22).

The source then unbinds the fd, removes the client from its list/index, sets `c->tid = destination`,
appends it under the destination inbox mutex, release-updates `inbox_n`, and wakes the destination,
which re-registers the fd on its own loop and links the client (`src/server.c:24227-24259`,
`:24539-24582`).

## Flip-time one-shot backfill (`tmRebalanceOntoNewIo`, `src/server.c:23973-24021`)

Called by grow-front after the new IO role is published, only when `tm_flip_rebalance` is true
(`src/server.c:23705-23717`). Filters sources to the new IO id's node, requires `>= 2` ids and
`>= 1` conn/thread aggregate, and selects busy-vs-count with the same `tot_busy > n` rule. For every
non-new over-target source with `>= 2` conns and an idle mailbox:

```text
busy mode:  count = (busy - busy_target) / (busy / nc)
count mode: count = nc - floor(total_conns / n)
```

clamped to leave one source conn, posting a fixed-destination `TM_MIGREQ_REBALANCE` to the new id. This
backfill has **no half-excess damping** and is a one-shot completion action; later continuous
correction comes through `tmClientBalanceCron` (`src/server.c:23964-24020`).

## State variables

| Field | Type | Meaning |
| --- | --- | --- |
| `tm_io_sig[id].busy_ewma_q4` | `int` | Q4 events-per-pass EWMA (alpha 1/8); relative weight |
| `server.clients[id]` | list | per-IO-thread client list; `listLength` = conn count |
| `cli_hot_streak[TOMO_IO_THREADS_MAX+1]` | `int` | per-source sustain streak (non-consecutive) |
| `tm_mig_mbox[id]` (`tmMigMailbox`) | struct | mutex inbox, atomic `inbox_n`, `req_pending`, packed `req_data`, `migrating_out`, `io_exiting`, notifier |
| `server.tm_client_lb` | `int` (bool) | continuous-trigger gate (default 1) |
| `server.tm_flip_rebalance` | `int` (bool) | flip-time backfill gate (= `thread_auto`) |

## Invariants

- Only **source measurement** is node-filtered; destination choice and fallback gather globally, so a
  handoff can cross logical nodes despite "within-node" comments (`loadbalance-flip.md`
  discrepancy #11; `src/server.c:24037-24042`, `:24072-24083`).
- The half-excess damping + 3-tick sustain + 25 % band converge without chasing a single hot connection
  (`src/server.c:24064-24069`).
- A migration never strands the source at 0 conns (`count > nc-1 → nc-1`; the singleton `nc < 2` skip)
  and never moves a non-quiesced or non-migratable client (`src/server.c:24071`, `:23878-23916`).
- `tomokv-client-lb = false` gates only new continuous requests; the IO-loop migration service and the
  shared mailbox infrastructure keep running because grow-back evacuation needs them
  (`src/server.c:24029-24034`, `loadbalance-flip.md` discrepancy #12).
- Request publication is a single packed atomic word — coherent fields, but last-writer-wins, not a
  queue (`src/server.c:22761-22778`).
