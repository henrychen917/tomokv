# NOTES-BARRIER — the connection parse barrier is one bool with six owners

Lane `t-barrier`. Brief: `NOTES-STOREORDER.md` §9 handed on a found-but-not-fixed item —
`blocking_retire()` and `blocking_scatter_retire()` clear the connection's scatter barrier
unconditionally, with no test that the barrier is theirs. Verify it from the source, decide whether
it is live or latent, and harden it.

**Outcome: verified, corrected in two details, and hardened.** The single bool becomes an owner
**bitmask**; `blocking_retire` now releases only the bit it acquired. The item is confirmed
**latent, not live** — and the reason is sharper than §9 states: a blocking op is provably
**alone in its ROB**, so the barrier at its retirement can have no other owner. Because exactly one
owner can hold the barrier today, the mask is bit-identical to the bool on every reachable path;
the change is a **behaviour-preserving refactor** whose only effect is that the two stop being
identical the moment a seventh owner, or a relaxed guard, makes overlap reachable.

**No build, no server, no bench was run in this lane** (main session holds the box). Everything
below is static reading. §6 describes the check and its geometry rather than reporting it.

---

## 1. The set / clear table

Grep basis: `grep -rn scatter_barrier src/`, whole tree, plus every caller of the accessors.
Line numbers are this branch at `c0d7f27fd`. §9's numbers are off by 2–69 lines: they were taken
before the `t-merge14` merge train (`blocking.inc:1275/:1286` → `1277/1288`,
`multi.inc:1365` → `1434`).

### SET sites — 8 sites, 6 owner classes

| # | Owner class | Site | Guard at the moment of the set | What ends the parse pass |
|---|---|---|---|---|
| 1 | **Barriered scatter** (two-hop store / all-shards) | `src/core/io_loop.h:1530` (plain-scatter arm) | `scatter_dispatch.barrier && rob.in_flight() != 0` ⇒ `break` — **ROB empty required** (the `t-storeorder` fix, `io_loop.h:1478`) | `continue` → loop head `io_loop.h:1113` breaks |
| 2 | same, bundled atomic-write arm | `src/core/io_loop.h:1593` | same guard, same `if` | `continue` → loop head breaks |
| 3 | **Blocking command** (`BLPOP`/`BLMOVE`/`XREAD BLOCK`…) | `src/core/io_loop.h:1437` | `rob.in_flight() != 0` ⇒ `break` (`io_loop.h:1391`) — **ROB empty required** | explicit `break` |
| 4 | **Deferred `WAIT`** | `src/core/io_loop.h:1305` | `WAIT` is `ConnLocal｜OrderedLocal｜DeferredLocal` (`server_tail.cc:952`); the `OrderedLocal` gate at `io_loop.h:1288` is `rob.in_flight() != 0` ⇒ `break` — **ROB empty required** | explicit `break` |
| 5 | **`EXEC` fan-out** | `src/cmd/multi.inc:1434` | **none** — `multi_dispatch_entry` has no `in_flight` test | `return true` → `io_loop.h:1215` `continue` → loop head breaks |
| 6 | **Pub/sub transition** (`(P｜S)(UN)SUBSCRIBE`) | `src/core/pubsub.inc:850` (`pubsub_begin_pending`) | **none** | returns `Async` → `io_loop.h:1264` `if (scatter_barrier()) break` |
| 7 | **`CLIENT UNBLOCK`, remote owner** | `src/cmd/climon.cc:524` | **none** | `Async` → same `io_loop.h:1264` break |
| 8 | **`CLIENT LIST` / `CLIENT KILL` fan-out** | `src/cmd/climon.cc:680` (`climon_begin_client_scatter`) | **none** | `Async` → same `io_loop.h:1264` break |

### CLEAR sites — 3

| # | Site | Condition today | Scope |
|---|---|---|---|
| A | `src/core/io_loop.h:1849` (`flush_ready`) | `if (c->rob().quiesced())` | **all owners** — the correct backstop: with nothing in flight every production owner has completed by definition |
| B | `src/cmd/blocking.inc:1277` (`blocking_retire`) | **unconditional** | all owners ← **the reported defect** |
| C | `src/cmd/blocking.inc:1288` (`blocking_scatter_retire`) | **unconditional** | all owners ← **the reported defect** |

### Two corrections to §9

1. **`CLIENT PAUSE` does not set the barrier.** §9 names owner 6 as "CLIENT PAUSE/KILL". `climon.cc:524`
   is `CLIENT UNBLOCK` against a *remote* owner and `climon.cc:680` is the `CLIENT LIST`/`CLIENT KILL`
   fan-out. `CLIENT PAUSE` uses a **completely separate** mechanism — `climon_pause_holds()`
   (`climon.cc:369`) leaves the parsed frame at `rpos` and `flush_ready` declines to count it as work
   (`io_loop.h:1896`) so the ring parks instead of spinning. It never touches `scatter_barrier_`.
   Attributing it to the barrier would have sent the hardening after the wrong owner.
2. **The count of six is right, but there are eight sites**, and the two that matter for the
   reachability argument are the two that *do* carry a ROB-empty guard (#1/#2 and #3), which §9's
   phrasing ("a blocking command requires the ROB head to issue") gets right for #3 and silently
   generalises to the rest. Owners #5–#8 have **no** `in_flight` guard at all: `EXEC`, a subscribe,
   and `CLIENT KILL` can each set the barrier with older ops of the same connection still in flight.
   That is fine — but it means the invariant is *not* "the barrier is only ever set on an empty ROB",
   and any future reader who assumes that will be wrong.

---

## 2. Reachability verdict — LATENT, not live

**Verdict: not reachable today.** The reason §9 gives is directionally right but incomplete; the
airtight statement is:

> **A blocking op is always alone in its ROB.**

Both halves are enforced, at two sites 47 lines apart in a different file from the clear:

* **Nothing older.** `io_loop.h:1391` — `if (spec->flags & CmdFlags::Blocking) { … if (rob.in_flight() != 0) break; }`.
  The blocking op cannot even be *prepared* until every older op of the connection has retired.
* **Nothing younger.** The same dispatch sets the barrier (`io_loop.h:1437`) and `break`s; the parse
  loop's head (`io_loop.h:1113`) and `flush_ready`'s re-parse gate (`io_loop.h:1894`) both refuse to
  parse while it is set. No byte behind the blocking frame is even looked at.

Therefore, at the instant `blocking_retire` runs, `dispatch_id - flush_id == 1` and the single live
op *is* the blocking op. The barrier's only possible owner is the one being released. Clearing
all owners and clearing one owner are the same operation.

The same argument covers **`blocking_scatter_retire`**: `state->blocking_origin` is written at exactly
one site — `blocking.inc:1203`, inside `blocking_resume_move` — which converts an *already parked*
blocking op in place (`op.detach_blocking_state(); op.attach_scatter_state(...)`). It creates no new
ROB slot, so the "alone in its ROB" property is inherited unchanged.

And **`BlockingState` cannot reach the ROB by any other route**: `attach_blocking_state` has exactly
one caller, `io_loop.h:1418`, behind the guard above. In particular a blocking command lowered inside
`MULTI` never produces one — `EXEC` children are not ROB ops and the parent `EXEC` op carries
`multi_state`, not `blocking_state`.

### Interleavings I checked and rejected

| Candidate | Why it does not fire |
|---|---|
| Pipelined `EXEC` / `SUBSCRIBE` / `CLIENT KILL` **then** `BLPOP` in one write | The first command sets the barrier and ends the pass; the `BLPOP` bytes are never parsed until the barrier drops at quiescence, by which time the first owner is done |
| Pipelined `BLPOP` **then** `EXEC` | `BLPOP` sets the barrier; `EXEC` is never parsed |
| Second owner set from **outside** `parse_and_dispatch` while a blocking op is parked | There is no such path. `blocking_resume_move` (the only thing that runs on a barred connection, `io_loop.h:1845`) does **not** acquire the barrier — it inherits the one already held. Pub/sub and climon event delivery on the io thread only ever set the barrier on the *requesting* client, never on a victim; `CLIENT KILL`/`UNBLOCK` reach a victim through `mark_closing()` / `blocking_request_unblock()`, neither of which touches `scatter_barrier_` |
| Two connections | The barrier is per-`Client` and every site writes it through the connection's own io owner. No cross-connection write exists |
| A `Blocking`-flagged command that skips the guard | Only `XREAD` without `BLOCK`, which `goto nonblocking_dispatch`es before the guard and never attaches blocking state |
| Deferred `WAIT` coexisting with a blocking op | `WAIT` is `OrderedLocal`, so it too needs `in_flight()==0`, and it too ends the pass |

### Two things this audit found that make the item worse than "latent"

1. **The invariant that saves it lives nowhere near the code that depends on it.** The clear is in
   `src/cmd/blocking.inc`; the guard is in `src/core/io_loop.h`, in a different translation unit,
   behind a command-flag test, with a comment that explains it in terms of *program order* and never
   mentions the barrier's ownership. That is the exact shape of the defect `t-storeorder` fixed.
2. **`rob().quiesced()` is FALSE inside `blocking_retire`, always.** `Rob::drain` (`rob.h:88-103`)
   calls `sink(op)` for the op at `flush_id` and stores the advanced `flush_` **once, after the whole
   batch**. So the retire callback always observes `in_flight() >= 1`. This kills the second option
   §9 offers ("have `blocking_retire` clear it only when the ROB is quiescent") outright: written
   literally it would **never** clear the barrier and every blocking client would wedge until the
   `flush_ready` backstop ran. The only workable spelling of that alternative is
   `rob().in_flight() == 1` — a magic constant that silently encodes the drain's internal
   bookkeeping. See §4.

---

## 3. `blocked_` has the same shape (found, not fixed)

`client.set_blocked(false)` sits one line above the barrier clear in both retire functions and is
equally unconditional. `blocked_` is set by **two** owners — the blocking dispatch (`io_loop.h:1436`)
and deferred `WAIT` (`io_loop.h:1304`) — and is saved by the same "each requires `in_flight()==0`"
argument. Not converted here: unlike the barrier, `blocked_` is a `connection_flags_` bit with three
readers that mean different things by it (`blocking_resume_move`, `blocking_cancel_client`,
`blocking_request_unblock`, and `CLIENT UNBLOCK`'s 0/1 reply), and giving it owners changes the
`CLIENT UNBLOCK` reply surface. Recorded, deliberately untouched.

---
