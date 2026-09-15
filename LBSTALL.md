# Client-balancer stall fix on stack3

Base: `3baa74799` (`cx-stack3`, product source `147ac24b7`: v3 + L1 + O1 + O6).
The three cx-lbstall commits are replayed with their provenance:

| Original | Replay | Change |
| --- | --- | --- |
| `42d54d7e2` | `73301d7b2` | Directed serverless regression |
| `ad1542013` | `f3a6bf6a6` | Immediate busy-client refusal and bounded drains |
| `d0a565b32` | `86afed608` | Diagnostics, controls and verification helper |

The only textual cherry-pick conflict was the inherited `MEASURE-REQUEST`; it now
points to this lane's request. The source merged cleanly. The integration adapts
the test to O1's active-client parser and rechecks GCC's translation-unit budgets.
O1's stage window, O6's whole-batch prefetch and mode policy, L1's Op layout, and
the existing reorder scheduler remain stack3's implementations.

## Preserved movement semantics

- The source refuses a busy client's move on its first control tail, including
  before the destination acknowledges. Existing ROB, reply, borrow, protocol,
  executor-lifetime and kernel-pointer readiness fences retain their strength.
- A ready source waiting for destination acknowledgement has a three-tail bound.
- Shard `IoDrain` / `ExDrain` retain v4's publication and executor barriers and
  timeout guard. They do not consume the client pass budget. A fast IO cannot
  cancel a shard move before its peers finish publishing or executing queued work.
- Pending control tails report work, keeping drains progressing.
- Refusal, stage advancement, client-start and shard commit serialize on the
  existing shape-transition mutex. Dispatch cannot resume inside a shard move.
- Refused client moves increment `lb_client_refused`; refused candidates enter
  the existing cooldown. The five-second timeout remains the last guard.
- An already-started `ClientMoving` handoff cannot be revoked by this refusal.

The shard-bound correction confines `lb_drain_pass_expired` to `ClientDrain`;
the immediate busy-client refusal and destination bound retain cx-lbstall's
semantics. The watch lines and counters belong to the existing optional LB
policy. Both LB knobs at zero allocate none of this state. An idle control tail
returns before the new watch/counter calls. No runtime option was added or changed.
The bound counts IO passes: it cannot bound the cost of an operation already
executing inside one pass.

## Directed regression and its limits

The v3 self-hold is documented in the historical `LBSTALL-BRIEF.md`: its parser
hold requeued `pending_ifid_`, and that reference itself prevented client migration.
O1 removed this path and its readiness predicate. The maintainer observed no stall
in two stack3 tailgen runs. This integration does not claim that stack3 reproduces
v3's pending-IFID self-hold or that its live tails have improved.

The adapted test drives stack3's actual parser specialization for active-client
retries in both modes. It publishes and retires a real ROB completion while its
executor work scope remains open, proving an empty ROB plus a live Client lifetime
fence. It appends PING frames to the real input buffer and requires the parser to
leave them unconsumed while `ClientDrain` is active. The readiness error must name
the unfinished executor completion. Both acknowledged and unacknowledged destination
variants require refusal on the FIRST tail, then require that the same buffered
frames receive their correct ordered replies exactly once. The executor fence must
still reject migration immediately after refusal, until its scope ends.

Separate cases preserve the ready-destination three-tail check, both shard-owner
modes, stale epochs, commit/refusal races, and allocation-free LB-off control tails.
The shard regression withholds producer ACKs across eight IO tails (including a
non-coordinator), then holds a real queued SET through four executor-drain tails.
The same plan must commit after execution, preserve RYOW, and consume no client
budget or refusal cooldown. A fresh expired shard drain must still time out.
This regression fails on rejected v5 `29486b6a6` at the publication-drain assertion.
`TOMO_LB_STALL_DEBUG` checks the actual parked-byte and refusal INFO counters.
These are deterministic, serverless units; no listener, ring or server loop starts.

The PRE negative control uses frozen stack3 production headers and objects, with
only this directed test inserted. The PAD negative control disables the out-of-line
refusal helper in a copy of POST's unit executable. Their results, the complete unit
inventory and the exact byte comparison are recorded in `MEASURE-REQUEST.md`.

## Known correctness defects outside this integration

Both existing nongating diagnostics reproduce on freshly built stack3 PRE:

- `atomic-survivors-unit post_apply_probe`: two successful APPENDs both return 2
  after first-owner script APPLY, leaving `BW`, an illegal serial outcome.
- `netcmd-unit collection-oom`: failure in the second multi-field HSET replacement
  retains the changed prefix and its old TTL (OPEN F05).

The tests and their failure expectations remain intact. No gate source was edited.
The existing `core concurrency route` row is emitted at `tests/gate.sh:1233`,
collected at line 2640, before the quick exit at line 2747. No row was added or
retired: **419 quick / 436 full**, delta **0 / 0**.

## Verification receipts

See `MEASURE-REQUEST.md` for the final artifact digests, size locks, raw and
relocation-aware hot-body counts, any encoding/prologue exceptions, unit totals,
and the maintainer's requested measurement cells. Build and raw proof files live
under `build/lbstall-s3-repair/`; original integration receipts remain under
`build/lbstall-s3-proof/`. The owner's authorized churn battery passed **3/3**
on fresh fused debug servers pinned to **112–119**, with **16 / 10 / 18** shard
moves, all workers completed, and no ownership-assertion violation. The driver
ran on **120–127**. No full gate or performance measurement was run.

### Final code-generation result

The expanded strict checker finds **573/576** byte-identical bodies. It includes
O1 stages, executor sweeps and store helpers in addition to the inherited coverage.
Three TLS specializations in `rl2s.o` retain inlining/encoding differences; the
checker returns failure and `MEASURE-REQUEST.md` lists their sizes and exact scope.
Full byte identity versus stack3 remains unmet. No mismatch is waived.
All **576/576** hot bodies and six IO/EX LB control bodies are byte-identical to
rejected v5 `29486b6a6`; this repair adds no hot-body encoding or prologue difference.
The LB control tail also
has its intended body changes and a 0x268 → 0x278 stack reservation change.
All unit selections ran: **75/77 pass**, including **11/11 TSAN**. The two failures
are the existing PRE defects above; PRE and PAD both fail the directed drain bound.
The final compiler locks retain all compared parser, O1, executor/sweep, store and
GET/SET/MGET/MSET bodies, with no claim of a measured zero tax.

## Shard-bound gate correction

The maintainer's rejected v5 gate had **435/436** passes: the churn row saw zero
shard moves. The three-tail limit could cancel `IoDrain` / `ExDrain` before peer
IOs and executors finished their old-route work, then put that shard into cooldown.
This repair confines that limit to client migration. It retains all ownership
barriers and the shard timeout guard, and preserves immediate busy-client refusal.

Commits: `85059ae74` (non-vacuous shard regression), `73ddb263b` (client-only guard).
Corrected POST and its **kind-A behaviour twin** are rebuilt at
`build/tomokv-lbstall-s3` and `build/tomokv-lbstall-s3-pad`. The PAD disables only
the out-of-line refusal helper in a copy of POST, preserving every text address.
The four client witnesses pass in native/debug/TSAN route checks; PRE and PAD
still fail the client-stall assertion. The new shard test fails against rejected
v5 and passes on corrected POST in both modes. All **77** unit selections reran:
**75 pass**, including **11/11 TSAN**; only the two existing defects above remain.
Artifact hashes, churn commands and results, scope of the byte proof, and remaining
mainline measurements are in `MEASURE-REQUEST.md`.
