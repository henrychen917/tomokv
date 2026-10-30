# Roots requiring an owner decision

All seven original harness5 scripts differ from Redis 7.4.10 on PRE in both
1s/2s and uring/epoll (`repro-pre.json`). The following three roots are stopped
under the task's deliberate-restriction/architecture rule. Their named Tcl
failures remain visible; this branch is not a complete seven-root fix.

## TRACK-MAXKEYS-IMMUTABLE

`src/cmd/t_server.cc` explicitly says the setting is boot-latched because IO
owners read `Config` directly. `src/core/config.h` further defines the bound
per IO owner, not globally. The harness row explicitly classifies this as
deliberate. A request for an owner decision is pending. Removing only the
immutable bit would not update the readers, reduce existing tables, or enforce
Redis's process-wide limit. No immutable flag or expected reply was weakened.

## TRACK-INVALIDATE-BEFORE-REPLY

This is not just an output queue placement bug. `tracking_register_read` runs
at the armed dispatch gate while a transaction is being queued. It deliberately
does not install its tracking spec on a MULTI child; the registry spec is copied
into the transaction. `tracking_retire_read` then enrolls that key when the
`+QUEUED` reply retires, with no observation certificate. The earlier writes
in EXEC invalidate that premature registration. The resulting push is already
queued before the later MGET; MGET's actual lazy expiry produces the second one.

A sound fix needs transaction-aware read enrollment: actual child execution,
child/write ordering, final decision, abort/retry lifetime, and transfer to the
IO owner's completed table. Suppressing the first push or guessing an EXEC
completion stamp would lose real invalidations or enroll aborted reads. The
current `MultiQueuedCommand`/`MultiCommand` records contain no tracking enrollment
state, and the tracking table is correctly IO-owned. This lane does not silently
add a transaction tracking architecture or weaken that ownership law.

## PUBSUB-SUBSCRIBE-NO-DENYOOM

The subscribe family is IO-local; the current DENYOOM check is in executor
command admission. Merely adding command metadata would never gate this path.
More substantially, the 12 Tcl tests include filling the budget with retained
subscription names and rejecting a large incoming channel argument. TomoKV's
`accounted_memory_bytes` and shard `budget_admit` deliberately account objects
and key-slot overhead, excluding client input buffers and pub/sub tables.
Subscriptions do not increase that budget. An IO-only `maxmemory == 1` special
case would pass the short repro while all the real allocation tests still fail.

Redis-compatible admission here requires an owner decision on unified client/
pubsub memory accounting, global admission, and interaction with per-shard
eviction budgets. Reading or mutating foreign FlatStores from an IO thread is
not a substitute. No arbitrary thresholds or special-case OOM replies were added.
