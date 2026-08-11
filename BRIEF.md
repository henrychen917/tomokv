# Batch the CDB completion signal: one word per popped batch (census item 1)

CONTEXT: the EX->IO completion bus (cdbSlots, one packed status line per CDB, byte atomics,
release-store per completion / acquire-poll per drain step) transfers the status line
IO<->worker per completion. The Opus census identified batching as its top cross-core
transfer reduction: a worker finishing a popped batch of N fakes for one (real,cdb) makes N
separate release stores that each bounce the line; the drain acquire-polls per slot.

TASK: aggregate publication per pop batch WITHOUT changing per-slot semantics for anyone else:
after executing its batch, the worker writes all N status bytes with ORDINARY stores, then
makes ONE release store to a per-CDB generation/summary word (same packed line's pad space or
an adjacent owned line — justify placement vs false sharing in comments); the IO drain
acquire-loads the summary word first and only on change reads the status bytes (plain loads,
ordered by the summary acquire). Slot clear stays as-is. Preserve: one-completer/one-drainer
per slot, teardown-drain path, cross-shard heads, reuse-cannot-begin-until-cleared, and every
notifyguard invariant HONESTLY (update patterns only if the guarantee is truly preserved).
WITNESS: per-worker counter of batched-publish events + avg batch size (kstat line + INFO).
WRITE CODE ONLY. Never run make/compile/servers/benchmarks. If the current code already
amortizes this (check exSlice's sig loop carefully), SAY SO and change nothing. Commit clean.
