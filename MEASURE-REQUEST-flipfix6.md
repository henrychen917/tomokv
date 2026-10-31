# FLIP transaction-session handover

## flipfix6

Branch `cx-flipfix6`, base `e32b04a445b056976abb308aa598e356fcbaae74`. No push.
Witness/diagnosis only so far; **no production change**. D18.1 and D18.2 were
approved on 2026-10-31. A further, explicit requirement conflicts with active
WATCH transfer and needs an owner ruling before implementation.

### Additional blocker: durable WATCH references

The brief requires every other readiness clause, including watched references,
to stay unchanged. `Client::migration_protocol_idle()` at `src/net/conn.h:768`
requires `watched_refs_ == 0`. That count includes **durable WATCH registrations**,
not just in-flight work:

* `Shard::watch_add` (`src/cmd/multi.inc:3431-3455`) installs a
  `(Client*, generation, db, expiry)` entry and calls `client->watch_ref()`.
* `Shard::watch_remove` (`:3458-3474`) releases that pin. Normal WATCH retirement
  leaves it installed; otherwise a subsequent foreign write could not invalidate
  EXEC. The registry names the Client, not its IO thread.
* `multi_handle_io` (`:2205-2260`) installs one alias per physical namespace for
  each watched logical key. One active WATCH therefore retains 1 pin with
  `--databases 1`, or 16 pins with `--databases 16`.
* `flip_drain_idle()` deliberately omits the watched-reference check. IoDrain
  finishes, but ClientPrepare cannot accept a live WATCH with the stipulated
  zero-reference clause, even if the session clause is changed to `!pending`.

First diagnostic active-WATCH witness, uring/atomic 0/databases 1, fresh 6:2 boot:

```text
planned epoch=1 io=5 session=1 pending=0 drain=1 migration=0 watched_refs=1 watched_keys=1
planned epoch=1 io=4 session=1 pending=0 drain=1 migration=0 watched_refs=1 watched_keys=1
failure epoch=1 stage=5 deadline=1 error=ERR FLIP cannot quiesce a connection: connection ROB, reply, borrow, or owner-local protocol state is busy
```

Stage 5 is ClientPrepare in the db1 namespace (stage 8 in the multi-DB namespace).
The diagnostic source is generated inside this worktree's ignored build tree by
`tools/flipfix6_diag.py`; production source and PRE remain untouched.

**Proposed additional ruling (not implemented):** after IoDrain/ExDrain, the
FLIP-only readiness check may retain durable WATCH registry pins on the same
Client. Preserve the shared LB check and the destruction/lifetime checks. A
conservative implementation can require no S2 and require the reference count
to equal the number of session-owned installed WATCH aliases, rather than zero;
any transient/excess pins still refuse readiness. This needs a proof that the
session's alias count is exact after completed WATCH, repeated WATCH, UNWATCH,
RESET, EXECABORT, database boundaries and allocation failure. Simply deleting
the watched-reference guard is not the proposal.

This is outside the explicit "every other clause stays" instruction, despite
being consistent with the intended D18.1 behaviour. Implementation is paused
pending that narrow ruling; the requested witness and reader audit continue.

### Witness status

`tests/flipfix6.py` adapts the EXEC partner's exact pipelined MULTI/INCR/INCR/EXEC
sequence, verifies equal replies and exact final values, and places a session on
every IO. It covers P1 (one EXEC then only GET), P2 (WATCH/UNWATCH then GET), P3
(serial same-owner transactions), and active WATCH. An independent PING worker
records its largest wait. The PRE expectation requires a deadline refusal and
a real >=4 s stall; an unopened window fails.

The first epoll/atomic 0/db1 run confirmed all five cases, with PING waits
5.0001-5.0007 s. The all-leg diagnostic matrix and the unchanged flipfix5 EXEC
driver are running; final counts and evidence will be appended here.

### Owner rulings

| Ruling | Status |
|---|---|
| D18.1: FLIP transfers session state without S2 | Approved; implementation paused on the durable WATCH pin contradiction |
| D18.2: S2 stays on surviving source / immediate refusal on converting source | Approved; not implemented yet |
| Every other readiness clause, including watched references | Untouched; the zero-reference clause needs the additional decision above |
| SPSC masked monolith, block masks, ExDrain -> ExInstall re-mask, truth tables | Untouched |
| Global FLIP dispatch pause | Untouched |
| Listener handover 2026-10-22, IO4.3/NT4.4 option (a) | Untouched |
| Five-second deadline; no new time constant | Untouched |
| txnorder claims, wound-wait, versions, FIFO hand-off | Untouched |
| LB client mover and shared readiness predicate | Untouched |
| Single-owner writes, immutable replacement/QSBR, no reader retries/seqlocks, RYOW | Untouched |
| Layout locks; both thread modes; main-command instruction cost | No production change |

### Gate counts and artifacts

No gate row is registered yet: **DQ=0, DF=0**, counted by `collect_job` lines
relative to the quick exit. `EXPECT_QUICK=977` and `EXPECT_FULL=994` are untouched.

PRE: `build/flipfix6/PRE`, SHA-256
`89f2fa028dbe7f05e2a4d9b0f799c6819a391debf8cf4de5506f57397621cf77`.
POST and PAD-A do not exist: production implementation is paused as above.
There is no throughput claim.

After the additional ruling and implementation, the maintainer's request remains
the 14 generic cells plus 2s GET/SET p1/p32 null cells, and FLIP episode latency
for PRE/POST/PAD-A with/without session clients (PRE refusal durations).
PAD-A must be labelled **A: behaviour twin**, POST's ELF with the FLIP-only
session clause restored to PRE, preserving text size/layout. No performance run
has been started by this lane.
