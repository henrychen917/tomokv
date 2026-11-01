# Tcl named-skip and promotion audit

Each entry has three isolated attempts per mode. Original per-attempt receipts are retained; only manifest-declared setup errors are classified separately from the target assertion.

| File / assertion | 1s attempts | 2s attempts | Disposition |
|---|---|---|---|
| unit/introspection / CLIENT KILL SKIPME YES/NO will kill all clients | PPP | PPP | Retain lane promotion |
| unit/introspection / MONITOR log blocked command only once | PPP | PPP | Keep named skip: MONITOR-BLOCKED-ONCE: cross-connection completion ordering remains unresolved; V17 removes the one-fresh-server retry. Named known difference, not regression evidence. |
| unit/multi / DISCARD should not fail during OOM | FFF | FFF | Keep named skip: did not pass all six attempts |
| unit/multi / EXEC with at least one use-memory command should fail | FFF | FFF | Keep named skip: did not pass all six attempts |
| unit/pause / Test old pause-all takes precedence over new pause-write (less restrictive) | PPP | PPP | Retain lane promotion |
| unit/pubsub / PUBLISH/SUBSCRIBE after UNSUBSCRIBE without arguments | PPP | PPP | Keep named skip: PUBSUB-DISCONNECT-LAG (D14): intermittent cross-owner disconnect lag observed on PRE and POST; no retry and no compatible-pass claim. |
| unit/pubsub / unsubscribe inside multi, and publish to self | PPP | PPP | Retain lane promotion |
| unit/scripting / LUA redis.error_reply API | FFF | FFF | Keep named skip: did not pass all six attempts |
| unit/scripting / LUA redis.error_reply API with empty string | FFF | FFF | Keep named skip: did not pass all six attempts |
| unit/slowlog / SLOWLOG - GET optional argument to limit output len works | FFF | FFF | Keep named skip: did not pass all six attempts |
| unit/slowlog / SLOWLOG - Rewritten commands are logged as their original command | FPP | FPP | Keep named skip: did not pass all six attempts |
| unit/slowlog / SLOWLOG - can clean older entries | FFF | FFF | Keep named skip: did not pass all six attempts |
| unit/slowlog / SLOWLOG - get all slow logs | FFF | FFF | Keep named skip: did not pass all six attempts |
| unit/slowlog / SLOWLOG - logged entry sanity check | FFF | FFF | Keep named skip: did not pass all six attempts |
| unit/slowlog / SLOWLOG - max entries is correctly handled | PFF | PPP | Keep named skip: did not pass all six attempts |
| unit/type/list / BLMPOP with multiple blocked clients | FFF | PPF | Keep named skip: did not pass all six attempts |
| unit/type/list / BRPOPLPUSH does not affect WATCH while still blocked | PPP | PPP | Keep named skip: BRPOPLPUSH-WATCH-ORDER / D11: cross-connection completion ordering remains unresolved; V17 removes the one-fresh-server retry. Named known difference, not regression evidence. |
| unit/type/list / Circular BRPOPLPUSH | FPP | FFF | Keep named skip: did not pass all six attempts |
| unit/type/list / Command being unblocked cause another command to get unblocked execution order test | FFF | FFF | Keep named skip: did not pass all six attempts |
| unit/type/list / Linked LMOVEs | PFF | PPP | Keep named skip: did not pass all six attempts |
| unit/type/list / PUSH resulting from BRPOPLPUSH affect WATCH | PPP | PPP | Keep named skip: BRPOPLPUSH-WATCH-ORDER / D11: cross-connection completion ordering remains unresolved; V17 removes the one-fresh-server retry. Named known difference, not regression evidence. |
| unit/type/stream-cgroups / XGROUP DESTROY should unblock XREADGROUP with -NOGROUP | FFF | FFF | Keep named skip: did not pass all six attempts |
