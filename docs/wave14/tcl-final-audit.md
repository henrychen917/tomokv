# Final-binary Tcl named-skip and promotion audit

Each assertion has three fresh-server attempts per mode. Known block-setup errors use the unchanged manifest; no failed attempt is retried into a pass.

| File / assertion | 1s | 2s | Disposition |
|---|---|---|---|
| unit/introspection / CLIENT KILL SKIPME YES/NO will kill all clients | PPP | PPP | Retain lane promotion |
| unit/introspection / MONITOR log blocked command only once | PPP | PFP | Keep named skip: MONITOR-BLOCKED-ONCE: cross-connection completion ordering remains unresolved; V17 removes the one-fresh-server retry. Named known difference, not regression evidence. |
| unit/multi / DISCARD should not fail during OOM | FFF | FFF | Keep named skip: MULTI-OOM-QUEUE / MULTI-OOM-EXEC (D10): failed on TomoKV 2s in the survey |
| unit/multi / EXEC with at least one use-memory command should fail | FFF | FFF | Keep named skip: MULTI-OOM-QUEUE / MULTI-OOM-EXEC (D10): failed on TomoKV 2s in the survey |
| unit/pause / Test old pause-all takes precedence over new pause-write (less restrictive) | PPP | PPP | Retain lane promotion |
| unit/pubsub / PUBLISH/SUBSCRIBE after UNSUBSCRIBE without arguments | PPP | PPP | Keep named skip: PUBSUB-DISCONNECT-LAG (D14): intermittent cross-owner disconnect lag observed on PRE and POST; no retry and no compatible-pass claim. |
| unit/pubsub / unsubscribe inside multi, and publish to self | PPP | PPP | Retain lane promotion |
| unit/scripting / LUA redis.error_reply API | FFF | FFF | Keep named skip: rootcompat: generic errorstats prototype rejected by zero-cost proof; no command-specific counter remains. Wire replies are covered by scriptfix2. |
| unit/scripting / LUA redis.error_reply API with empty string | FFF | FFF | Keep named skip: rootcompat: generic errorstats prototype rejected by zero-cost proof; no command-specific counter remains. Wire replies are covered by scriptfix2. |
| unit/slowlog / SLOWLOG - GET optional argument to limit output len works | FFF | FFF | Keep named skip: SLOWLOG-MAXLEN-PER-THREAD: global ring was removed at integration (e98831c81); per-thread ring remains a documented difference. |
| unit/slowlog / SLOWLOG - Rewritten commands are logged as their original command | PPF | FFF | Keep named skip: SLOWLOG-EXEC-BLOCKED-ORDER (D11): EXEC retirement ordering can log its waking BLPOP before queued SLOWLOG RESET erases it. Real execution-order defect; no retry. |
| unit/slowlog / SLOWLOG - can clean older entries | FFF | FFF | Keep named skip: SLOWLOG-MAXLEN-PER-THREAD: global ring was removed at integration (e98831c81); per-thread ring remains a documented difference. |
| unit/slowlog / SLOWLOG - get all slow logs | FFF | FFF | Keep named skip: SLOWLOG-MAXLEN-PER-THREAD: global ring was removed at integration (e98831c81); per-thread ring remains a documented difference. |
| unit/slowlog / SLOWLOG - logged entry sanity check | FFF | FFF | Keep named skip: SLOWLOG-MAXLEN-PER-THREAD: global ring was removed at integration (e98831c81); per-thread ring remains a documented difference. |
| unit/slowlog / SLOWLOG - max entries is correctly handled | PFF | PPP | Keep named skip: SLOWLOG-MAXLEN-PER-THREAD: global ring was removed at integration (e98831c81); per-thread ring remains a documented difference. |
| unit/type/list / BLMPOP with multiple blocked clients | FFF | FFP | Keep named skip: BLOCK-WAKE-ORDER-MULTI / BLOCK-CHAIN-ASYNC (D11): failed on TomoKV 2s in the survey |
| unit/type/list / BRPOPLPUSH does not affect WATCH while still blocked | PPP | PPP | Keep named skip: BRPOPLPUSH-WATCH-ORDER / D11: cross-connection completion ordering remains unresolved; V17 removes the one-fresh-server retry. Named known difference, not regression evidence. |
| unit/type/list / Circular BRPOPLPUSH | FFP | FFF | Keep named skip: BLOCK-WAKE-ORDER-MULTI / BLOCK-CHAIN-ASYNC (D11): failed on TomoKV 2s in the survey |
| unit/type/list / Command being unblocked cause another command to get unblocked execution order test | FFF | FFF | Keep named skip: BLOCK-WAKE-ORDER-MULTI / BLOCK-CHAIN-ASYNC (D11): failed on TomoKV 2s in the survey |
| unit/type/list / Linked LMOVEs | PFF | PPP | Keep named skip: BLOCK-WAKE-ORDER-MULTI / BLOCK-CHAIN-ASYNC (D11): failed on TomoKV 2s in the survey |
| unit/type/list / PUSH resulting from BRPOPLPUSH affect WATCH | PPP | PPP | Keep named skip: BRPOPLPUSH-WATCH-ORDER / D11: cross-connection completion ordering remains unresolved; V17 removes the one-fresh-server retry. Named known difference, not regression evidence. |
| unit/type/stream-cgroups / XGROUP DESTROY should unblock XREADGROUP with -NOGROUP | FFF | FFF | Keep named skip: rootcompat: removed NOGROUP-only total_error_replies, errorstats and cmdstat timing/failed_calls. Generic error accounting remains unimplemented under the authorized zero-cost fallback. |
