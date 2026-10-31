# Session reader audit at e32b04a44

`session-readers.txt` records every source match for `multi_session(`,
`MultiSession`, and `multi_session_` (64 lines). This audit also follows the
session fields and the WATCH reference producers. Line numbers below refer to
PRE. Production source has not changed.

| Readers / writers | IO assumption and transfer obligation |
|---|---|
| `conn.h:55-56,290,728-729,900` | Opaque declaration, Client-owned pointer, getter/setter, destruction. The pointer and address of the Client remain unchanged in a transfer. Destroying a pending session invokes its old owner's admission cleanup, so S2 must not move. |
| `conn.h:763-780` | Shared migration requires both no session and no WATCH references. FLIP drain omits both. **Two independent durable blockers** exist for an active WATCH. The shared LB/lifetime checks must remain unchanged. |
| `io_loop.h:865` | Query-buffer accounting is per Client. It reads `query_bytes`, with no IO index. |
| `io_loop.h:2051`, `lbplanner.cc:944` | Two LB selection paths deliberately decline any session. Both must retain their existing behaviour. |
| `io_loop.h:3474`, `reorder.cc:2210` | Fused read-local batch extension excludes any session. FLIP exists only in split mode. No migration-specific change is needed here. |
| `io_loop.h:3565-3569`, `reorder.cc:2301-2305` | Parser dispatches through MULTI handling after the global FLIP pause check. On resume it uses the destination loop and connection ROB. The current global pause must stay intact. |
| `read_local_parse.inc:216` | Armed read-local GET excludes active WATCH through the session's watch count; fused-only eligibility, no stored IO identity. |
| `multi.inc:173-186` | `MultiSession` owns active/error flags, next ROB operation id, last-attempt count, queued argv/specs, query bytes, watched aliases, and pending state. Only `pending` can own an admitted attempt and name an IO. Conditional `TOMO_EXEC1S_WB` ids also name the connection's own ROB; this audit proposes no WB change. |
| `multi.inc:484-489` | Allocates the session once; no normal EXEC/DISCARD/UNWATCH path frees the pointer. Allocation is connection-local. |
| `multi.inc:1306-1324` | `prepare_unwatch_state` moves watched aliases into a newly allocated IO-bound state. The resulting pending/published cleanup must stay or retire before transfer. |
| `multi.inc:2132-2147` | `multi_pause_writes` walks queued specs/argv; `multi_queueing` reads active. No stored IO identity. |
| `multi.inc:2153-2169` | Conditional `multi_wb_prefix_hold` reads connection ROB generations. It is not a FLIP transfer mechanism. |
| `multi.inc:2171-2419` | Queue-error mutation and `multi_handle_io`: already-pending state reuses its recorded IO; new WATCH/EXEC/unwatch states use the supplied current `owner_io`. Active queue/error/argv are connection-local. The pending fast return is why S2 cannot be re-homed by moving only Client. |
| `multi.inc:2570-2618` | Dispatch entry compares `next_queue_op_id` with the same Client ROB, handles RESET through owner-routed cleanup, and publishes tasks through the current loop. The S2 path is prepared before publication; successful dispatch clears pending. No unconsumed frame may bypass the FLIP pause. |
| `multi.inc:2787` | A closing in-flight attempt returns its watched aliases to the session before `multi_close_entry`. It belongs to the old IO retry lane; IoDrain's deferred/cleanup and ROB checks must finish it before handover. |
| `multi.inc:2970-2980` | `multi_dispatch_started` marks publication and clears the matching pending pointer. This does **not** mean the work is retired: the existing ROB, barrier, atomic-group and deferred-state clauses must still hold. |
| `multi.inc:3067` | Retirement records `last_attempts` in the session. Retirement also runs connection-local queued effects on its owner IO. IoDrain must complete that work before moving the Client. |
| `multi.inc:3133-3155` | Close abandons unpublished state, clears the queue, then prepares WATCH cleanup on the current IO. Destruction deletes the session. S2 policy must preserve the admitting IO for abandonment. |
| `multi.inc:3157-3194` | Active, queue size, watch size, memory, last attempts and query-byte accessors read per-Client values. Multi-DB watch size counts only `ns=0`; it is **not** the physical registry pin count. A proposed durable-pin check must use all aliases, not this public logical count. |
| `climon.cc:585` | Reparse restores a tracking spec only outside an active transaction. It reads the session on its owning IO. Existing climon transfer extracts/installs the connection's map node. |
| `climon.cc:815-827` | MONITOR buffers queued-command records until EXEC, indexed by queue order and the Client ROB. The entire `ClimonConn` node, including `monitor_pending`, moves in `client_routing_commit_extract`/`client_routing_install` (`:375-434`), with destination refresh flags restored. |
| `tracking.cc:169` | Queued commands retain the global registry spec rather than the temporary per-read tracking wrapper. Therefore the session's queued `CommandSpec*` is not a dangling pointer into the source IO's tracking state. |
| `t_server.cc:258,282-284,316-318` | CLIENT info reads session flags/counts/memory on the current owner. Client directory/catalog migration already exists; no session-owned IO identity. |
| `multi.h:29,215-220` | Forward declaration and accessor/destructor declarations only. |

WATCH registry and lifetime audit:

* `Shard::watch_add` (`multi.inc:3431-3455`) retains one Client reference per
  installed `(physical key, Client*, generation, logical DB)` entry. Completed
  WATCH keeps these references. `watch_remove` and `watch_prune_stale` release
  them (`:3408-3429,3458-3474`). The registry stays on its Shard during FLIP.
* `multi_handle_io` creates all physical aliases (`:2228-2244`), so logical
  `multi_session_watch_size()` cannot be used directly as the expected count in
  a multi-DB transfer check.
* Deferred database-swap invalidations temporarily add references
  (`:3687-3705`), released by `finalize_reservations` (`:2011-2021`) or the
  corresponding state cleanup (`:205`). These are not durable session pins.
* A multi-DB boundary holds a separate Client lifetime pin
  (`multidb.cc:580-603`). The boundary serializes with FLIP and releases its pin
  before Idle. The existing serialization must remain intact.
* `Client::safe_to_release()` must continue requiring zero references. Allowing
  movement with known durable pins would not permit destruction with those pins.

The original audit found that the stipulated `watched_refs_ == 0` clause was
incompatible with moving an active WATCH. The resume addendum approves an exact
physical-alias exception. The retained draft implements and tests it; production
source is restored while the additional executor-fence decision is pending.

Resume audit of the new readers in `session-handover-DRAFT.patch`:

| Reader | IO assumption |
|---|---|
| `Client::flip_session_pending()` | Reads only the Client-owned pending pointer on the current IO; does not dereference or move its IO-bound attempt. |
| `Client::flip_migration_protocol_idle()` | Reads pending and physical watched-alias count on the current IO, then the existing connection drain predicate. No stored IO identity. |
| Transfer accounting in `finish_client_transfer` | Captures whether the session exists before publishing the ownership move; no session dereference after publication. |
| S2 preflight/drop in ClientPrepare | Reads pending on the source IO and retains it there. Insufficient alone: the earlier global ExDrain credits block entry to this stage. |

The new deterministic witnesses narrow the original conclusion: session state
is transferable only when the earlier ExDrain and close scheduling obligations
are also met. See [s2-exdrain-review.md](s2-exdrain-review.md). Close can abandon
an unpublished attempt or publish WATCH-removal tasks after the safe point;
its lifetime must be reconciled with the proposed exact admission/apply receipt.

## Conservative implementation (resume addendum 2)

The earlier draft's ClientPrepare S2 skip is not present in the candidate.
`IoLoop::flip_session_drain_refused` scans only its own clients during an owed
IoDrain pass. A non-null `session->pending` refuses the episode before ExDrain,
regardless of the source's planned role. No attempt, age, credit, queued argv,
WATCH alias or owner identity is changed by this scan.

`Client::flip_migration_protocol_idle` is the distinct, out-of-line FLIP
predicate. It rejects pending attempts and requires exact physical alias/pin
equality plus the original drain predicate. The LB predicate and
`safe_to_release` are unchanged. The public transfer preflight, request and
finish recheck all select FLIP readiness via `hold_for_commit`.

`IoLoop::flip_session_close_held` uses the existing source pin, records the
reversible close refusal once, and defers `multi_close_entry` until Idle. The
active-close retry (`closing_client_ready`, in both IO engine bodies) revisits
the same idempotent cleanup before the original zero-pin lifetime test. This
is necessary for a durable WATCH close: waiting for zero pins before revisiting
cleanup would otherwise leak it. No new steady-state command or EXEC hook was
added. There is no stored destination or forwarded attempt in any helper.

The close-refusal decision and ClientPrepare -> ClientCommit edge use the
existing `flip_error_mu_`. A precommit close wins the lock and causes rollback;
after commitment, the existing pin defers cleanup until the bounded completion
reaches Idle. Existing listener handover operations keep their order. No
executor quiesce readiness, mask, re-mask or transaction mechanism changes.
