# CC4.6: one mutable state per library — owner decision

The reset fix is independent of the remaining executor split. Each executor
retains a function interpreter; library revision changes replace only that
library's closures, and SCRIPT FLUSH owns a separate EVAL interpreter. This is
not Redis's one process-wide function state. `tests/scriptfix.py functions
--single-state` is the executable failing witness, retained alongside the
passing reset row. No single-state candidate is enabled in production.

A shared `LibraryInstance { lua_State*, mutex, context_slot }` looks local to
functions.cc/scripting.cc. The caller could retain a shared pointer from the
registry, lock it, bind the current shard/op, invoke Lua, and unlock. Single-key
calls would still execute on their existing shard owner. This is insufficient:

1. `execute_script_phase`, ScriptPhase::Run, in
   `src/cmd/scatter_engine.inc` invokes the handler against a private workbench.
   The library upvalues change immediately; the staged key changes are not yet
   visible to their owners.
2. `finish_script`'s Run/Validate transitions can clear the attempt, restage,
   and call Lua again after certification or read-set conflicts. A counter can
   increment more than once for one successful FCALL. A failed attempt can
   also leave closure state modified without publishing its key writes.
3. Unlocking after Lua lets another activation observe the new upvalue with
   old keys. Example: A increments captured `n`, writes n to key K; before A's
   APPLY, B returns `{n, redis.call('GET', K)}`. The new n/old K pair has no
   Redis serial execution. This is a torn function-state/keyspace observation,
   not an objection to independent cross-client ordering.
4. Keeping the mutex through APPLY cannot be done with a stack-local guard.
   More importantly, an executor sleeping on that mutex can be the executor
   needed to execute the holder's remaining Validate/Apply/Unpin tasks.

These paths already prevent promising exact stateful-function transaction
semantics for the existing per-executor model. Merely moving Lua into a shared
object would not fix them and would add a blocking/deadlock path. The lane does
not change `io_loop.h`, `server.h`, executor loops, scatter scheduling, or the
single-owner/immutable-read laws to hide this limitation.

## Design retained for review

Use one ref-counted Lua engine per library revision. LOAD/RESTORE validate and
create the instance once; unrelated metadata operations retain it. DELETE and
REPLACE retire the registry reference; an activation retains its exact version
until completion. EVAL remains independent. A library's admission queue grants
one activation token **before its key snapshot**, and releases it only after
its key effects reach their final publication/abort disposition. Park waiting
FCALLs at dispatch; never block a shard-owner thread on a mutex.

The admission token alone does not solve retries against ordinary key writers.
The owner must choose a commit protocol that executes stateful Lua once, or a
transactional interpreter-state scheme that can discard speculative mutations
before retry, without discarding effects of a Lua error (Redis retains those).
General Lua closure/table graphs cannot be rolled back by copying just a
counter or serializing source. Admission, validation, retries, cancellation,
FUNCTION lifecycle, and shutdown need one protocol; this exceeds the two
scripting implementation files. The same owner must define consistency for
an in-flight library version during DELETE/REPLACE.

A possible execution model keeps the instance mobile: the admitted owning
executor binds the engine's stable context slot and runs it; it remains parked
at library level through final key publication. A fixed library executor would
instead require even formerly single-owner FCALLs to stage/apply through the
scatter workbench. Both need scheduling changes and a once-only state/effects
commit rule before implementation is correct.

## FCALL cost estimate (structural, not measured)

| Component | Reset-only implementation | Shared-state design lower bound |
|---|---|---|
| Uncontended cached invocation | generation load + thread-local registry lookups | library-instance reference + admission acquire/release + context binding |
| Same-library concurrency | one stream per touched executor | one global stream; throughput <= 1 / token hold time |
| Single-key call on existing owner | no extra handoff | mobile engine: none uncontended; queued activation: at least enqueue + wake |
| Fixed-home alternative, key on another owner | existing owner execution | staging request/reply plus apply request/reply; requires scatter integration |
| Cross-shard activation | current stage/run/validate/apply waves | token spans all waves; waiting time includes publication, not just Lua runtime |
| Engine memory | one engine per executor with functions | one engine per loaded library revision; less duplicate closures, more base interpreters for many libraries |

For E concurrent executors and one hot library, the best-case CPU-parallel
FCALL rate changes from approximately E/T to 1/T for Lua-only work; with a token
held across scatter, the bound is 1/(T + stage + validate + apply + scheduling).
These are bounds, not measured nanoseconds/cycles or a promised regression.
A numeric cycle estimate needs an authorized candidate and the gate's matched
load instrument. Suggested cells: Lua-only counter, GET and SET callbacks,
one-key and cross-owner keys, hot-library and many-library distributions,
1s/2s, atomic 0/1, depths 1 and 32. Decide correctness first; then report rate,
cycles/op, IPC and instructions/op against the reset-only branch.
