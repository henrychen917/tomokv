# Redis 7.4.10 external Tcl survey

Source baseline: `3700b51d7`; no production changes. Both servers used fresh per-file data directories,
16 databases, `--singledb`, and the supplied upstream tests. TomoKV used 16 shards;
2s used eight CPUs at ratio 6:2. All processes were confined to CPUs 32–47 and listener ports 45800–45899.
The suite driver copies upstream into this worktree; assertion bodies remain unchanged. An event observer
records test packets, and includes `unit/moduleapi` in discovery. Native Redis is the 7.4.10 oracle.

The supplied tree has **206 Tcl files total, 135 executable unit/integration inputs**.
The remaining 71 files are support/other harness inputs (including the separate cluster harness),
listed individually in [the machine summary](redis-tcl-summary.json). They are not 71 silently skipped unit tests.

| Server | Passed | Failed events | Explicit skips | Files attempted | Files interrupted |
|---|---:|---:|---:|---:|---:|
| 2s | 1423 | 459 | 228 | 135 | 11 |
| 1s | 1420 | 462 | 228 | 135 | 11 |
| redis | 2252 | 78 | 251 | 135 | 4 |

These are observations, **not counts of independent defects or a compatibility percentage**.
External mode skips process-owning tests. A setup error or blocked test can prevent later assertions from running;
unreached assertions are not counted as passes or skips. The 240 s per-file and 60 s upstream idle deadlines
bound the survey. Ordinary post-`done` controller EOF exceptions also occur on Redis and are retained separately.
Every assertion failure and pre-completion exception remains in the table and machine evidence.

Raw receipts: [2s](redis-tcl-2s.json.gz), [1s](redis-tcl-1s.json.gz),
[Redis](redis-tcl-redis.json.gz), [fresh exact-name comparisons](redis-tcl-isolated.json.gz).
The receipts contain the executable SHA-256, exact argv, every event and per-file elapsed time.

## Reproducing the real compatibility differences

Each `R` entry in [redis-tcl-real-cases.json](redis-tcl-real-cases.json) names the failing test, suspected subsystem,
both-server evidence and the smallest upstream selection used in the fresh-server check. Error-message differences
are included as compatibility differences; they do not imply corrupted stored values. Related tests can share one cause.
Selections with prerequisite names retain that context; they are not claimed to be irreducible protocol transcripts.

To rerun one entry, write its `reproduction` array inside a JSON list and invoke:

```sh
taskset -c 32-39 python3 docs/harness5/isolate_tcl.py --cases build/one-case.json \
  --output build/one-case --cores 32-39 --port 45820 --baseport 45853
```

This boots TomoKV and Redis in turn and uses `./runtest --host 127.0.0.1 --port 45820 --singledb
--single FILE --only EXACT_TEST_NAME` (plus explicit prerequisite names when present).
The helper retains both selected-test results and command/reply traces. Full-file results cover both TomoKV modes.

| ID | Upstream file / test | Suspected subsystem |
|---|---|---|
| R001 | unit/dump: RESTORE can set LRU | src/store/object_idle.h / RESTORE |
| R002 | unit/dump: RESTORE can set LFU | src/store/object_idle.h / RESTORE |
| R003 | unit/expire: SET - use KEEPTTL option, TTL should not be removed after loadaof | CONFIG / persistence |
| R004 | unit/expire: GETEX use of PERSIST option should remove TTL after loadaof | CONFIG / persistence |
| R005 | unit/functions: FUNCTION - Load with unknown argument | src/cmd/functions.cc |
| R006 | unit/functions: FUNCTION - test function case insensitive | src/cmd/functions.cc |
| R007 | unit/functions: FUNCTION - test function restore with wrong number of arguments | src/cmd/functions.cc |
| R008 | unit/functions: FUNCTION - test function kill | src/cmd/functions.cc |
| R009 | unit/functions: FUNCTION - test script kill not working on function | src/cmd/functions.cc |
| R010 | unit/functions: FUNCTION - test function kill not working on eval | src/cmd/functions.cc |
| R011 | unit/functions: LIBRARIES - test shared function can access default globals | src/cmd/functions.cc |
| R012 | unit/functions: LIBRARIES - test registration failure revert the entire load | src/cmd/functions.cc |
| R013 | unit/functions: LIBRARIES - test registration with no string name | src/cmd/functions.cc |
| R014 | unit/functions: LIBRARIES - test registration with wrong name format | src/cmd/functions.cc |
| R015 | unit/functions: LIBRARIES - test registration with empty name | src/cmd/functions.cc |
| R016 | unit/functions: LIBRARIES - math.random from function load | src/cmd/functions.cc |
| R017 | unit/functions: LIBRARIES - malicious access test | src/cmd/functions.cc |
| R018 | unit/functions: LIBRARIES - delete removed all functions on library | src/cmd/functions.cc |
| R019 | unit/functions: LIBRARIES - load timeout | src/cmd/functions.cc |
| R020 | unit/functions: FUNCTION - test function list withcode multiple times | src/cmd/functions.cc |
| R021 | unit/functions: FUNCTION - test function list libraryname multiple times | src/cmd/functions.cc |
| R022 | unit/functions: FUNCTION - verify OOM on function load and function restore | src/cmd/functions.cc |
| R023 | unit/functions: FUNCTION - test function list with CRLF injection attempt | src/cmd/functions.cc |
| R024 | unit/functions: FUNCTION - deny oom | src/cmd/functions.cc |
| R025 | unit/functions: FUNCTION - redis version api | src/cmd/functions.cc |
| R026 | unit/functions: FUNCTION - function test multiple names | src/cmd/functions.cc |
| R027 | unit/functions: FUNCTION - function test name with quotes | src/cmd/functions.cc |
| R028 | unit/functions: FUNCTION - test getmetatable on script load | src/cmd/functions.cc |
| R029 | unit/info-command: info command with one sub-section | INFO section selection |
| R030 | unit/info-command: info command with multiple sub-sections | INFO section selection |
| R031 | unit/introspection-2: TTL, TYPE and EXISTS do not alter the last access time of a key | command statistics / scripting |
| R032 | unit/introspection-2: errors stats for GEOADD | command statistics / scripting |
| R033 | unit/introspection-2: command stats for scripts | command statistics / scripting |
| R034 | unit/introspection: CLIENT KILL SKIPME YES/NO will kill all clients | CLIENT / INFO accounting |
| R035 | unit/latency-monitor: LATENCY HISTOGRAM with empty histogram | LATENCY / command histogram accounting |
| R036 | unit/latency-monitor: LATENCY HISTOGRAM all commands | LATENCY / command histogram accounting |
| R037 | unit/latency-monitor: LATENCY HISTOGRAM sub commands | LATENCY / command histogram accounting |
| R038 | unit/latency-monitor: LATENCY HISTOGRAM with a subset of commands | LATENCY / command histogram accounting |
| R039 | unit/latency-monitor: LATENCY HISTOGRAM command | LATENCY / command histogram accounting |
| R040 | unit/latency-monitor: LATENCY HISTOGRAM with wrong command name skips the invalid one | LATENCY / command histogram accounting |
| R041 | unit/multi: EXEC fails if there are errors while queueing commands #2 | src/cmd/multi.inc / multi_admin.cc |
| R042 | unit/multi: DISCARD should not fail during OOM | src/cmd/multi.inc / multi_admin.cc |
| R043 | unit/multi: MULTI and script timeout | src/cmd/multi.inc / multi_admin.cc |
| R044 | unit/multi: EXEC and script timeout | src/cmd/multi.inc / multi_admin.cc |
| R045 | unit/multi: MULTI-EXEC body and script timeout | src/cmd/multi.inc / multi_admin.cc |
| R046 | unit/multi: just EXEC and script timeout | src/cmd/multi.inc / multi_admin.cc |
| R047 | unit/multi: EXEC with at least one use-memory command should fail | src/cmd/multi.inc / multi_admin.cc |
| R048 | unit/other: EXPIRES after AOF reload (without rewrite) | src/net (RESET/connection state) |
| R049 | unit/other: RESET clears MONITOR state | src/net (RESET/connection state) |
| R050 | unit/other: RESET clears and discards MULTI state | src/net (RESET/connection state) |
| R051 | unit/pause: Test old pause-all takes precedence over new pause-write (less restrictive) | src/net (CLIENT PAUSE) |
| R052 | unit/pause: Test new pause time is smaller than old one, then old time preserved | src/net (CLIENT PAUSE) |
| R053 | unit/pause: Test write commands are paused by RO | src/net (CLIENT PAUSE) |
| R054 | unit/pause: Test special commands are paused by RO | src/net (CLIENT PAUSE) |
| R055 | unit/scripting: EVAL - Lua number -> Redis integer conversion | src/cmd/scripting.cc |
| R056 | unit/scripting: EVAL - Scripts do not block on blpop command | src/cmd/scripting.cc |
| R057 | unit/scripting: EVAL - Scripts do not block on brpop command | src/cmd/scripting.cc |
| R058 | unit/scripting: EVAL - Scripts do not block on brpoplpush command | src/cmd/scripting.cc |
| R059 | unit/scripting: EVAL - Scripts do not block on blmove command | src/cmd/scripting.cc |
| R060 | unit/scripting: EVAL - Scripts do not block on bzpopmin command | src/cmd/scripting.cc |
| R061 | unit/scripting: EVAL - Scripts do not block on bzpopmax command | src/cmd/scripting.cc |
| R062 | unit/scripting: EVAL - Scripts do not block on XREAD with BLOCK option | src/cmd/scripting.cc |
| R063 | unit/scripting: EVAL - Scripts do not block on XREADGROUP with BLOCK option | src/cmd/scripting.cc |
| R064 | unit/scripting: EVAL - Scripts do not block on XREAD with BLOCK option -- non empty stream | src/cmd/scripting.cc |
| R065 | unit/scripting: EVAL - Scripts do not block on XREADGROUP with BLOCK option -- non empty stream | src/cmd/scripting.cc |
| R066 | unit/scripting: EVAL - No arguments to redis.call/pcall is considered an error | src/cmd/scripting.cc |
| R067 | unit/scripting: EVAL - redis.call variant raises a Lua error on Redis cmd error (1) | src/cmd/scripting.cc |
| R068 | unit/scripting: EVAL - JSON numeric decoding | src/cmd/scripting.cc |
| R069 | unit/scripting: EVAL - JSON string decoding | src/cmd/scripting.cc |
| R070 | unit/scripting: EVAL - JSON smoke test | src/cmd/scripting.cc |
| R071 | unit/scripting: EVAL - cmsgpack can pack double? | src/cmd/scripting.cc |
| R072 | unit/scripting: EVAL - cmsgpack can pack negative int64? | src/cmd/scripting.cc |
| R073 | unit/scripting: EVAL - cmsgpack pack/unpack smoke test | src/cmd/scripting.cc |
| R074 | unit/scripting: EVAL - cmsgpack can pack and unpack circular references? | src/cmd/scripting.cc |
| R075 | unit/scripting: EVAL - Verify minimal bitop functionality | src/cmd/scripting.cc |
| R076 | unit/scripting: redis.sha1hex() implementation | src/cmd/scripting.cc |
| R077 | unit/scripting: Measures elapsed time os.clock() | src/cmd/scripting.cc |
| R078 | unit/scripting: Prohibit dangerous lua methods in sandbox | src/cmd/scripting.cc |
| R079 | unit/scripting: Verify execution of prohibit dangerous Lua methods will fail | src/cmd/scripting.cc |
| R080 | unit/scripting: lua bit.tohex bug | src/cmd/scripting.cc |
| R081 | unit/scripting: Number conversion precision test (issue #1118) | src/cmd/scripting.cc |
| R082 | unit/scripting: Scripts can handle commands with incorrect arity | src/cmd/scripting.cc |
| R083 | unit/scripting: Correct handling of reused argv (issue #1939) | src/cmd/scripting.cc |
| R084 | unit/scripting: Functions in the Redis namespace are able to report errors | src/cmd/scripting.cc |
| R085 | unit/scripting: Script return recursive object | src/cmd/scripting.cc |
| R086 | unit/scripting: Script ACL check | src/cmd/scripting.cc |
| R087 | unit/scripting: Binary code loading failed | src/cmd/scripting.cc |
| R088 | unit/scripting: Try trick readonly table on json table | src/cmd/scripting.cc |
| R089 | unit/scripting: Try trick readonly table on cmsgpack table | src/cmd/scripting.cc |
| R090 | unit/scripting: Try trick readonly table on bit table | src/cmd/scripting.cc |
| R091 | unit/scripting: Try trick readonly table on basic types metatable | src/cmd/scripting.cc |
| R092 | unit/scripting: Timedout read-only scripts can be killed by SCRIPT KILL | src/cmd/scripting.cc |
| R093 | unit/scripting: Timedout read-only scripts can be killed by SCRIPT KILL even when use pcall | src/cmd/scripting.cc |
| R094 | unit/scripting: Timedout script does not cause a false dead client | src/cmd/scripting.cc |
| R095 | unit/scripting: Timedout script link is still usable after Lua returns | src/cmd/scripting.cc |
| R096 | unit/scripting: Script - disallow write on OOM | src/cmd/scripting.cc |
| R097 | unit/scripting: SORT is normally not alpha re-ordered for the scripting engine | src/cmd/scripting.cc |
| R098 | unit/scripting: SORT BY <constant> output gets ordered for scripting | src/cmd/scripting.cc |
| R099 | unit/scripting: SORT BY <constant> with GET gets ordered for scripting | src/cmd/scripting.cc |
| R100 | unit/scripting: random numbers are random now | src/cmd/scripting.cc |
| R101 | unit/scripting: Scripting engine PRNG can be seeded correctly | src/cmd/scripting.cc |
| R102 | unit/scripting: Shebang support for lua engine | src/cmd/scripting.cc |
| R103 | unit/scripting: Unknown shebang option | src/cmd/scripting.cc |
| R104 | unit/scripting: Unknown shebang flag | src/cmd/scripting.cc |
| R105 | unit/scripting: allow-oom shebang flag | src/cmd/scripting.cc |
| R106 | unit/scripting: no-writes shebang flag | src/cmd/scripting.cc |
| R107 | unit/scripting: reject script do not cause a Lua stack leak | src/cmd/scripting.cc |
| R108 | unit/scripting: Consistent eval error reporting | src/cmd/scripting.cc |
| R109 | unit/scripting: LUA redis.error_reply API | src/cmd/scripting.cc |
| R110 | unit/scripting: LUA redis.error_reply API with empty string | src/cmd/scripting.cc |
| R111 | unit/scripting: LUA redis.error_reply API with CRLF injection attempt | src/cmd/scripting.cc |
| R112 | unit/scripting: LUA redis.status_reply API | src/cmd/scripting.cc |
| R113 | unit/scripting: LUA test pcall with non string/integer arg | src/cmd/scripting.cc |
| R114 | unit/scripting: EVAL - explicit error() call handling | src/cmd/scripting.cc |
| R115 | unit/slowlog: SLOWLOG - GET optional argument to limit output len works | src/cmd/slowlog.cc |
| R116 | unit/slowlog: SLOWLOG - Rewritten commands are logged as their original command | src/cmd/slowlog.cc |
| R117 | unit/slowlog: SLOWLOG - EXEC is not logged, just executed commands | src/cmd/slowlog.cc |
| R118 | unit/slowlog: SLOWLOG - get all slow logs | src/cmd/slowlog.cc |
| R119 | unit/slowlog: SLOWLOG - blocking command is reported only after unblocked | src/cmd/slowlog.cc |
| R120 | unit/sort: SORT sorted set BY nosort works as expected from scripts | src/cmd/scripting.cc |
| R121 | unit/tracking: The connection gets invalidation messages about all the keys | src/net (client tracking) |
| R122 | unit/tracking: Clients can enable the BCAST mode with prefixes | src/net (client tracking) |
| R123 | unit/tracking: Invalidations of previous keys can be redirected after switching to RESP3 | src/net (client tracking) |
| R124 | unit/tracking: Invalidations of new keys can be redirected after switching to RESP3 | src/net (client tracking) |
| R125 | unit/tracking: Tracking only occurs for scripts when a command calls a read-only command | src/net (client tracking) |
| R126 | unit/tracking: RESP3 Client gets tracking-redir-broken push message after cached key changed when rediretion client is terminated | src/net (client tracking) |
| R127 | unit/tracking: Different clients using different protocols can track the same key | src/net (client tracking) |
| R128 | unit/type/stream-cgroups: PEL NACK reassignment after XGROUP SETID event | src/cmd/t_stream_groups.cc |
| R129 | unit/type/stream: XRANGE exclusive ranges | src/cmd/t_stream.cc |
| R130 | unit/type/stream: XREAD last element from non-empty stream | src/cmd/t_stream.cc |
| R131 | unit/type/stream: XREAD last element from empty stream | src/cmd/t_stream.cc |
| R132 | unit/type/stream: XREAD last element blocking from empty stream | src/cmd/t_stream.cc |
| R133 | unit/type/stream: XREAD last element blocking from non-empty stream | src/cmd/t_stream.cc |
| R134 | unit/type/stream: XREAD last element from multiple streams | src/cmd/t_stream.cc |
| R135 | unit/type/stream: XREAD last element with count > 1 | src/cmd/t_stream.cc |
| R136 | unit/type/stream: XREAD: read last element after XDEL (issue #13628) | src/cmd/t_stream.cc |
| R137 | unit/type/zset: ZMPOP with illegal argument | src/cmd/t_zset.cc |
| R138 | unit/type/zset: BZMPOP with illegal argument | src/cmd/t_zset.cc |
| R139 | unit/type/zset: BZMPOP with multiple blocked clients | src/cmd/t_zset.cc |

## Classification of every observed TomoKV failure

Repeated parameterized instances and both modes are grouped only for display. The exact mode, event index, stack,
classification and reproduction are retained for every occurrence in [redis-tcl-failures.json.gz](redis-tcl-failures.json.gz).
A failure that passes in isolation is recorded as a test-state/cleanup assumption, not counted again as an independent defect.

| File / test | Mode(s); occurrences | Class | Evidence / limitation |
|---|---|---|---|
| integration/redis-cli: Non-interactive non-TTY CLI: ASK redirect test | 1s,2s; 2 | Redis-internal assumption | Fresh exact-name case also fails on Redis: prerequisite/test-state assumption; full-file evidence retained. |
| integration/redis-cli: Non-interactive non-TTY CLI: Test command-line hinting - latest server | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| integration/redis-cli: Dumping an RDB - functions only: no | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| integration/redis-cli: Dumping an RDB - functions only: yes | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| integration/redis-cli: Connecting as a replica | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/bitops: SETBIT/BITFIELD only increase dirty when the value changed | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/dump: RESTORE with ABSTTL in the past | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/dump: RESTORE can set LRU | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/dump: RESTORE can set LFU | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/dump: RESTORE should not store key that are already expired, with REPLACE will propagate it as DEL or UNLINK | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/dump: RESTORE fail with invalid payload size | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/dump: MIGRATE cached connections are released after some time | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/expire: All TTL in commands are propagated as absolute timestamp in replication stream | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/expire: SET - use KEEPTTL option, TTL should not be removed after loadaof | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/expire: GETEX use of PERSIST option should remove TTL after loadaof | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/expire: GETEX propagate as to replica as PERSIST, DEL, or nothing | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/expire: Redis should not propagate the read command on lazy expire | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/expire: SCAN: Lazy-expire should not be wrapped in MULTI/EXEC | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/expire: RANDOMKEY: Lazy-expire should not be wrapped in MULTI/EXEC | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/functions: FUNCTION - Load with unknown argument | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - test function case insensitive | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - test debug reload different options | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/functions: FUNCTION - test debug reload with nosave and noflush | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/functions: FUNCTION - test function restore with wrong number of arguments | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - test function kill | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - test script kill not working on function | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - test function kill not working on eval | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - async function flush rebuilds Lua VM without causing race condition between main and lazyfree thread | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/functions: FUNCTION - test function wrong argument | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/functions: LIBRARIES - test shared function can access default globals | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: LIBRARIES - test registration failure revert the entire load | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: LIBRARIES - test registration with no string name | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: LIBRARIES - test registration with wrong name format | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: LIBRARIES - test registration with empty name | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: LIBRARIES - math.random from function load | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: LIBRARIES - malicious access test | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: LIBRARIES - delete removed all functions on library | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: LIBRARIES - load timeout | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - test function list withcode multiple times | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - test function list libraryname multiple times | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - verify OOM on function load and function restore | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - verify allow-omm allows running any command | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/functions: FUNCTION - test function list with CRLF injection attempt | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - deny oom | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - redis version api | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - function test multiple names | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - function test name with quotes | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/functions: FUNCTION - test getmetatable on script load | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/hyperloglog: HyperLogLogs are promote from sparse to dense | 1s,2s; 2 | Redis-internal assumption | Redis storage layout, compression, encoding threshold, or internal save-delay control. |
| unit/hyperloglog: Change hll-sparse-max-bytes | 1s,2s; 2 | Redis-internal assumption | Redis storage layout, compression, encoding threshold, or internal save-delay control. |
| unit/hyperloglog: Hyperloglog promote to dense well in different hll-sparse-max-bytes | 1s,2s; 2 | Redis-internal assumption | Redis storage layout, compression, encoding threshold, or internal save-delay control. |
| unit/info-command: info command with at most one sub command | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/info-command: info command with one sub-section | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/info-command: info command with multiple sub-sections | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/introspection-2: TTL, TYPE and EXISTS do not alter the last access time of a key | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/introspection-2: Operations in no-touch mode do not alter the last access time of a key | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/introspection-2: errors stats for GEOADD | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/introspection-2: command stats for scripts | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/introspection-2: COMMAND LIST FILTERBY PATTERN - list all commands/subcommands | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/introspection-2: MIGRATE command is marked with movablekeys | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/introspection: CLIENT LIST | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/introspection: CLIENT LIST with IDs | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/introspection: CLIENT INFO | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/introspection: CLIENT KILL SKIPME YES/NO will kill all clients | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/introspection: CLIENT KILL close the client connection during bgsave | 1s,2s; 2 | Redis-internal assumption | Redis storage layout, compression, encoding threshold, or internal save-delay control. |
| unit/keyspace: COPY basic usage for list - quicklist | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/keyspace: COPY basic usage for list - listpack | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/keyspace: COPY basic usage for $type set | 1s,2s; 6 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/keyspace: COPY basic usage for listpack sorted set | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/keyspace: COPY basic usage for skiplist sorted set | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/keyspace: COPY basic usage for listpack hash | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/keyspace: COPY basic usage for hashtable hash | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/keyspace: COPY basic usage for stream | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/latency-monitor: LATENCY HISTOGRAM with empty histogram | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/latency-monitor: LATENCY HISTOGRAM all commands | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/latency-monitor: LATENCY HISTOGRAM sub commands | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/latency-monitor: LATENCY HISTOGRAM with a subset of commands | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/latency-monitor: LATENCY HISTOGRAM command | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/latency-monitor: LATENCY HISTOGRAM with wrong command name skips the invalid one | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/latency-monitor: LATENCY of expire events are correctly collected | 1s,2s; 2 | Redis-internal assumption | Artificial timing workload exceeds TomoKV’s script instruction budget. |
| unit/lazyfree: UNLINK can reclaim memory in background | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/lazyfree: FLUSHDB ASYNC can reclaim memory in background | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/lazyfree: lazy free a stream with all types of metadata | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/lazyfree: lazy free a stream with deleted cgroup | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/lazyfree: FLUSHALL SYNC optimized to run in bg as blocking FLUSHALL ASYNC | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/lazyfree: Run consecutive blocking FLUSHALL ASYNC successfully | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/lazyfree: FLUSHALL SYNC in MULTI not optimized to run as blocking FLUSHALL ASYNC | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/lazyfree: Client closed in the middle of blocking FLUSHALL ASYNC | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/lazyfree: Pending commands in querybuf processed once unblocking FLUSHALL ASYNC | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/moduleapi/aclcheck: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/aclcheck: test existing users to have access to module commands loaded on runtime | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/aclcheck: test existing users without permissions, do not have access to module commands loaded on runtime. | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/aclcheck: test users without permissions, do not have access to module commands. | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/aclcheck: test if foocategory acl categories is added | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/aclcheck: test permission compaction and simplification for categories added by a module | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/aclcheck: test module load fails if exceeds the maximum number of adding acl categories | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/async_rm_call: <file setup/teardown> | 1s,2s; 8 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/auth: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/basics: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/blockedclient: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/blockonbackground: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/blockonkeys: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/cluster: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/cmdintrospection: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/commandfilter: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/commandfilter: RM_CommandFilterArgInsert and script argv caching | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/commandfilter: Blocking Commands don't run through command filter when reprocessed | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/commandfilter: Filtering based on client id | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/crash: <file setup/teardown> | 1s,2s; 4 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/datatype: DataType: test loadex with invalid config | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/datatype: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/datatype2: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/defrag: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/eventloop: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/fork: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/getchannels: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/getkeys: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/hash: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/hooks: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/infotest: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/infra: modules config rewrite | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/keyspace_events: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/keyspecs: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/list: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/mallocsize: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/misc: <file setup/teardown> | 1s,2s; 4 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/moduleauth: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/moduleconfigs: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/postnotifications: <file setup/teardown> | 1s,2s; 4 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/propagate: Modules can propagate in async and threaded contexts | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/propagate: Modules RM_Replicate replicates MULTI/EXEC correctly: AOF-load type debug_cmd | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/propagate: Modules RM_Call does not update stats during aof load: AOF-load type debug_cmd | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/propagate: Modules RM_Replicate replicates MULTI/EXEC correctly: AOF-load type startup | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/propagate: Modules RM_Call does not update stats during aof load: AOF-load type startup | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/propagate: Replicas that was marked as CLIENT_CLOSE_ASAP should not keep the replication backlog from been trimmed | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/publish: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/rdbloadsave: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/reply: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/scan: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/stream: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/subcommands: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/test_lazyfree: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/testrdb: modules are able to persist types | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/testrdb: modules global are lost without aux | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/testrdb: aux that saves no data are not saved to the rdb when aux_save2 is used | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/testrdb: aux that saves no data are saved to the rdb when aux_save is used | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/testrdb: modules are able to persist globals before and after | 1s,2s; 4 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/testrdb: modules are able to persist globals just after | 1s,2s; 4 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/testrdb: Verify module options info | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/testrdb: diskless loading short read with module | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/timer: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/usercall: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/moduleapi/zset: <file setup/teardown> | 1s,2s; 2 | unsupported by design | Module API surface is deliberately absent; module tests also need native test .so fixtures. |
| unit/multi: EXEC fails if there are errors while queueing commands #2 | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/multi: MULTI / EXEC is not propagated (single write command) | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/multi: MULTI / EXEC is propagated correctly (multiple commands) | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/multi: MULTI / EXEC is propagated correctly (empty transaction) | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/multi: MULTI / EXEC is propagated correctly (read-only commands) | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/multi: MULTI / EXEC is propagated correctly (write command, no effect) | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/multi: MULTI / EXEC with REPLICAOF | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/multi: DISCARD should not fail during OOM | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/multi: MULTI and script timeout | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/multi: EXEC and script timeout | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/multi: MULTI-EXEC body and script timeout | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/multi: just EXEC and script timeout | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/multi: exec with write commands and state change | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/multi: exec with read commands and stale replica state change | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/multi: EXEC with only read commands should not be rejected when OOM | 1s,2s; 2 | Redis-internal assumption | Upstream external-server test lifecycle/controller assumption; not a command-semantic verdict. |
| unit/multi: EXEC with at least one use-memory command should fail | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/multi: Blocking commands ignores the timeout | 1s,2s; 2 | Redis-internal assumption | Upstream external-server test lifecycle/controller assumption; not a command-semantic verdict. |
| unit/multi: MULTI propagation of PUBLISH | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/multi: MULTI propagation of SCRIPT LOAD | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/multi: MULTI propagation of EVAL | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/multi: MULTI propagation of SCRIPT FLUSH | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/multi: MULTI propagation of XREADGROUP | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/multi: MULTI with SAVE | 1s,2s; 2 | Redis-internal assumption | Upstream external-server test lifecycle/controller assumption; not a command-semantic verdict. |
| unit/multi: MULTI with SHUTDOWN | 1s,2s; 2 | Redis-internal assumption | Upstream external-server test lifecycle/controller assumption; not a command-semantic verdict. |
| unit/multi: MULTI with config error | 1s,2s; 2 | Redis-internal assumption | Upstream external-server test lifecycle/controller assumption; not a command-semantic verdict. |
| unit/multi: Flushall while watching several keys by one client | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/other: Coverage: HELP commands | 1s,2s; 2 | unsupported by design | Requires MODULE HELP or Redis DEBUG PROTOCOL; deliberately unsupported internals/surface. |
| unit/other: Check consistency of different data types after a reload | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/other: Same dataset digest if saving/reloading as AOF? | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/other: EXPIRES after a reload (snapshot + append only file rewrite) | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/other: EXPIRES after AOF reload (without rewrite) | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/other: RESET clears MONITOR state | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/other: RESET clears and discards MULTI state | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/pause: Test old pause-all takes precedence over new pause-write (less restrictive) | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/pause: Test new pause time is smaller than old one, then old time preserved | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/pause: Test write commands are paused by RO | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/pause: Test special commands are paused by RO | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/printver: <file setup/teardown> | 1s,2s; 2 | Redis-internal assumption | File setup/teardown failed outside a named assertion; raw exception and unreached coverage retained. |
| unit/protocol: RESP3 attributes | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/protocol: RESP3 attributes readraw | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/protocol: RESP3 attributes on RESP2 | 1s,2s; 2 | unsupported by design | Requires MODULE HELP or Redis DEBUG PROTOCOL; deliberately unsupported internals/surface. |
| unit/protocol: test big number parsing | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/protocol: test bool parsing | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/protocol: test verbatim str parsing | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/protocol: test large number of args | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/protocol: test argument rewriting - issue 9598 | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/querybuf: query buffer resized correctly | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/querybuf: query buffer resized correctly when not idle | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/querybuf: query buffer resized correctly with fat argv | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/replybufsize: verify reply buffer limits | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/scripting: EVAL - Lua number -> Redis integer conversion | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - Scripts do not block on blpop command | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - Scripts do not block on brpop command | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - Scripts do not block on brpoplpush command | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - Scripts do not block on blmove command | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - Scripts do not block on bzpopmin command | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - Scripts do not block on bzpopmax command | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - Scripts do not block on wait | 1s,2s; 4 | unsupported by design | WAIT/WAITAOF replication acknowledgement surface is deliberately absent. |
| unit/scripting: EVAL - Scripts do not block on waitaof | 1s,2s; 4 | unsupported by design | WAIT/WAITAOF replication acknowledgement surface is deliberately absent. |
| unit/scripting: EVAL - Scripts do not block on XREAD with BLOCK option | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - Scripts do not block on XREADGROUP with BLOCK option | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - Scripts do not block on XREAD with BLOCK option -- non empty stream | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - Scripts do not block on XREADGROUP with BLOCK option -- non empty stream | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - No arguments to redis.call/pcall is considered an error | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - redis.call variant raises a Lua error on Redis cmd error (1) | 1s,2s; 6 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - JSON numeric decoding | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - JSON string decoding | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - JSON smoke test | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - cmsgpack can pack double? | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - cmsgpack can pack negative int64? | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - cmsgpack pack/unpack smoke test | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - cmsgpack can pack and unpack circular references? | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - Verify minimal bitop functionality | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: redis.sha1hex() implementation | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Measures elapsed time os.clock() | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Prohibit dangerous lua methods in sandbox | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Verify execution of prohibit dangerous Lua methods will fail | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: lua bit.tohex bug | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Number conversion precision test (issue #1118) | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Scripts can handle commands with incorrect arity | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Correct handling of reused argv (issue #1939) | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Functions in the Redis namespace are able to report errors | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: CLUSTER RESET can not be invoke from within a script | 1s,2s; 4 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/scripting: Script return recursive object | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Script check unpack with massive arguments | 1s,2s; 4 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: Script read key with expiration set | 1s,2s; 4 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: Script del key with expiration set | 1s,2s; 4 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: Script ACL check | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Binary code loading failed | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Try trick global protection 1 | 1s,2s; 4 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: Try trick global protection 2 | 1s,2s; 4 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: Try trick global protection 3 | 1s,2s; 4 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: Try trick global protection 4 | 1s,2s; 4 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: Try trick readonly table on redis table | 1s,2s; 4 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: Try trick readonly table on json table | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Try trick readonly table on cmsgpack table | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Try trick readonly table on bit table | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Try trick readonly table on basic types metatable | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Test loadfile are not available | 1s,2s; 4 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: Test dofile are not available | 1s,2s; 4 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: Test print are not available | 1s,2s; 4 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: Timedout read-only scripts can be killed by SCRIPT KILL | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Timedout read-only scripts can be killed by SCRIPT KILL even when use pcall | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Timedout script does not cause a false dead client | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Timedout script link is still usable after Lua returns | 1s,2s; 4 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: <file setup/teardown> | 1s,2s; 4 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/scripting: Test script flush will not leak memory - script:0 | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/scripting: Script - disallow write on OOM | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - is Lua able to call Redis API? | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: EVALSHA - Can we call a SHA1 if already defined? | 1s,2s; 2 | Redis-internal assumption | Fresh exact-name case also fails on Redis: prerequisite/test-state assumption; full-file evidence retained. |
| unit/scripting: EVALSHA_RO - Can we call a SHA1 if already defined? | 1s,2s; 2 | Redis-internal assumption | Fresh exact-name case also fails on Redis: prerequisite/test-state assumption; full-file evidence retained. |
| unit/scripting: EVALSHA - Can we call a SHA1 in uppercase? | 1s,2s; 2 | Redis-internal assumption | Fresh exact-name case also fails on Redis: prerequisite/test-state assumption; full-file evidence retained. |
| unit/scripting: EVAL - Redis integer -> Lua type conversion | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: EVAL - Redis bulk -> Lua type conversion | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: EVAL - Redis multi bulk -> Lua type conversion | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: EVAL - Redis status reply -> Lua type conversion | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: EVAL - Redis error reply -> Lua type conversion | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: EVAL - Scripts can run non-deterministic commands | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: EVAL_RO - Successful case | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: EVAL_RO - Cannot run write commands | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: SCRIPTING FLUSH - is able to clear the scripts cache? | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: SCRIPTING FLUSH ASYNC | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: SORT is normally not alpha re-ordered for the scripting engine | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: SORT BY <constant> output gets ordered for scripting | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: SORT BY <constant> with GET gets ordered for scripting | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Test an example script DECR_IF_GT | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: random numbers are random now | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Scripting engine PRNG can be seeded correctly | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL does not leak in the Lua stack | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: SPOP: We can call scripts rewriting client->argv from Lua | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/scripting: MGET: mget shouldn't be propagated in Lua | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/scripting: EXPIRE: We can call scripts rewriting client->argv from Lua | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/scripting: INCRBYFLOAT: We can call scripts expanding client->argv from Lua | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/scripting: Call Redis command with many args from Lua (issue #1764) | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: String containing number precision test (regression of issue #1118) | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: Script with RESP3 map | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: Test script flush will not leak memory - script:1 | 1s,2s; 2 | Redis-internal assumption | Redis allocator/buffer/dirty/lazyfree accounting assumption; no independent value-loss claim. |
| unit/scripting: Shebang support for lua engine | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Unknown shebang option | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Unknown shebang flag | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: allow-oom shebang flag | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: no-writes shebang flag | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: not enough good replicas | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/scripting: reject script do not cause a Lua stack leak | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: Consistent eval error reporting | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: LUA redis.error_reply API | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: LUA redis.error_reply API with empty string | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: LUA redis.error_reply API with CRLF injection attempt | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: LUA redis.status_reply API | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: LUA test pcall | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: LUA test pcall with error | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/scripting: LUA test pcall with non string/integer arg | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/scripting: EVAL - explicit error() call handling | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/slowlog: SLOWLOG - max entries is correctly handled | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/slowlog: SLOWLOG - GET optional argument to limit output len works | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/slowlog: SLOWLOG - Certain commands are omitted that contain sensitive information | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/slowlog: SLOWLOG - Some commands can redact sensitive fields | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/slowlog: SLOWLOG - Rewritten commands are logged as their original command | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/slowlog: SLOWLOG - EXEC is not logged, just executed commands | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/slowlog: SLOWLOG - get all slow logs | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/slowlog: SLOWLOG - blocking command is reported only after unblocked | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/sort: SORT sorted set BY nosort works as expected from scripts | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/sort: SORT STORE quicklist with the right options | 1s,2s; 2 | Redis-internal assumption | Redis storage layout, compression, encoding threshold, or internal save-delay control. |
| unit/tracking: The connection gets invalidation messages about all the keys | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/tracking: Clients can enable the BCAST mode with prefixes | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/tracking: Adding prefixes to BCAST mode works | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/tracking: Tracking NOLOOP mode in standard mode works | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/tracking: Tracking NOLOOP mode in BCAST mode works | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/tracking: Tracking gets notification of expired keys | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/tracking: Tracking gets notification of lazy expired keys | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/tracking: RESP3 tracking redirection | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/tracking: Invalidations of previous keys can be redirected after switching to RESP3 | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/tracking: Invalidations of new keys can be redirected after switching to RESP3 | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/tracking: Tracking only occurs for scripts when a command calls a read-only command | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/tracking: RESP3 Client gets tracking-redir-broken push message after cached key changed when rediretion client is terminated | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/tracking: Different clients can redirect to the same connection | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/tracking: Different clients using different protocols can track the same key | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/tracking: No invalidation message when using OPTIN option | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/type/hash: Is a ziplist encoded Hash promoted on big payload? | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/type/incr: INCR uses shared objects in the 0-9999 range | 1s,2s; 2 | Redis-internal assumption | Redis storage layout, compression, encoding threshold, or internal save-delay control. |
| unit/type/incr: INCR can modify objects in-place | 1s,2s; 2 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/type/list-3: Check compression with recompress | 1s,2s; 2 | Redis-internal assumption | Redis storage layout, compression, encoding threshold, or internal save-delay control. |
| unit/type/list-3: Crash due to wrongly recompress after lrem | 1s,2s; 2 | Redis-internal assumption | Redis storage layout, compression, encoding threshold, or internal save-delay control. |
| unit/type/list-3: LINSERT correctly recompress full quicklistNode after inserting a element before it | 1s,2s; 2 | Redis-internal assumption | Redis storage layout, compression, encoding threshold, or internal save-delay control. |
| unit/type/list-3: LINSERT correctly recompress full quicklistNode after inserting a element after it | 1s,2s; 2 | Redis-internal assumption | Redis storage layout, compression, encoding threshold, or internal save-delay control. |
| unit/type/list-3: <file setup/teardown> | 1s,2s; 2 | Redis-internal assumption | Redis storage layout, compression, encoding threshold, or internal save-delay control. |
| unit/type/list: <file setup/teardown> | 1s,2s; 2 | Redis-internal assumption | Redis storage layout, compression, encoding threshold, or internal save-delay control. |
| unit/type/list: Test LPUSH and LPOP on plain nodes | 1s,2s; 4 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/type/list: Test LINDEX and LINSERT on plain nodes | 1s,2s; 4 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/type/list: Test LTRIM on plain nodes | 1s,2s; 4 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/type/list: Test LREM on plain nodes | 1s,2s; 4 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/type/list: Test LPOS on plain nodes | 1s,2s; 4 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/type/list: Test LMOVE on plain nodes | 1s,2s; 4 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/type/list: Test LSET with packed / plain combinations | 1s,2s; 4 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/type/list: Test LSET with packed is split in the middle | 1s,2s; 4 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/type/list: Test LSET with packed consist only one item | 1s,2s; 4 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/type/list: Crash due to delete entry from a compress quicklist node | 1s,2s; 4 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/type/list: Crash due to split quicklist node wrongly | 1s,2s; 4 | unsupported by design | Test requires a Redis DEBUG implementation/internal representation. |
| unit/type/set: SPOP new implementation: code path #1 propagate as DEL or UNLINK | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/type/set: SRANDMEMBER with a dict containing long chain | 1s,2s; 2 | Redis-internal assumption | Redis storage layout, compression, encoding threshold, or internal save-delay control. |
| unit/type/set: SMOVE basics - from regular set to intset | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/type/set: SMOVE basics - from intset to regular set | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/type/set: SMOVE non existing key | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/type/set: SMOVE non existing src set | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/type/set: SMOVE from regular set to non existing destination set | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/type/set: SMOVE from intset to non existing destination set | 1s,2s; 2 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/type/stream-cgroups: PEL NACK reassignment after XGROUP SETID event | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/type/stream: XADD with MAXLEN option and the '~' argument | 1s,2s; 2 | Redis-internal assumption | Approximate stream trimming asserts Redis radix-node packing/granularity. |
| unit/type/stream: XADD with LIMIT delete entries no more than limit | 1s,2s; 2 | Redis-internal assumption | Approximate stream trimming asserts Redis radix-node packing/granularity. |
| unit/type/stream: XRANGE exclusive ranges | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/type/stream: XREAD last element from non-empty stream | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/type/stream: XREAD last element from empty stream | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/type/stream: XREAD last element blocking from empty stream | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/type/stream: XREAD last element blocking from non-empty stream | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/type/stream: XREAD last element from multiple streams | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/type/stream: XREAD last element with count > 1 | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/type/stream: XREAD: read last element after XDEL (issue #13628) | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/type/stream: XTRIM with MAXLEN option basic test | 1s,2s; 2 | Redis-internal assumption | Approximate stream trimming asserts Redis radix-node packing/granularity. |
| unit/type/stream: XADD with LIMIT consecutive calls | 1s,2s; 2 | Redis-internal assumption | Approximate stream trimming asserts Redis radix-node packing/granularity. |
| unit/type/stream: XTRIM with ~ is limited | 1s,2s; 2 | Redis-internal assumption | Approximate stream trimming asserts Redis radix-node packing/granularity. |
| unit/type/stream: XTRIM with LIMIT delete entries no more than limit | 1s,2s; 2 | Redis-internal assumption | Approximate stream trimming asserts Redis radix-node packing/granularity. |
| unit/type/stream: <file setup/teardown> | 1s,2s; 2 | Redis-internal assumption | File setup/teardown failed outside a named assertion; raw exception and unreached coverage retained. |
| unit/type/string: GETDEL propagate as DEL command to replica | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/type/string: GETEX without argument does not propagate to replica | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/type/zset: ZMPOP with illegal argument | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/type/zset: ZMPOP propagate as pop with count command to replica | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/type/zset: BZMPOP with illegal argument | 1s,2s; 2 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/type/zset: BZMPOP propagate as pop with count command to replica | 1s,2s; 2 | unsupported by design | Replication, cluster, or cross-server migration surface; outside the single-node target. |
| unit/type/zset: BZMPOP with multiple blocked clients | 1s; 1 | REAL compatibility defect | Same selected upstream case fails on TomoKV and passes on Redis 7.4.10. |
| unit/type/zset: BZMPOP should not blocks on non key arguments - #10762 | 1s; 1 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |
| unit/type/zset: ZRANDMEMBER - listpack | 1s; 1 | Redis-internal assumption | Passes on a fresh isolated server; failure depends on earlier test state/cleanup (not an additional proved defect). |

## Regression job

`GATE_ONLY_JOBS=redis_tcl` runs seven complete passing files, **115 assertions in each mode**.
The frozen manifest binds upstream file/support hashes and the complete nonempty multiset of passing assertion names.
A failure, missing assertion, rename, duplicate, skip replacing a pass, timeout, or changed upstream input fails the job.
The gate job uses exactly its server port and one controller port; it cannot scan into another slot.
UTF-8 decoding is explicit because the gate otherwise uses `LC_ALL=C`.

The two private rows are prerequisites of the existing `compat2 autharity` public row, before the quick exit.
Missing or failed completion makes that existing row red; serverless controls exercise the missing-completion path.
**DQ=0, DF=0.** No `EXPECT_*` constant or public row count changes.
This subset is a regression guard, not certification of the failing, skipped, or unreached remainder.
Gate results: [passing selected job](tcl-gate/final/gate.log). The first attempt’s locale refusal is retained alongside it.
