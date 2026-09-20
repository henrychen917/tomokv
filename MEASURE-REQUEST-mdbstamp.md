**mdbstamp — implementation, serverless proof, and mainline measurement request**

Status: implementation and serverless controls complete; live correctness, ABBA and acceptance **PENDING**. No throughput, cycles/op, instructions/op, IPC or latency result is claimed. No server, load generator, gate or performance measurement was run. Nothing was pushed.

**Launch and scope**

Assigned branch/worktree: `cx-mdbstamp`, `/home/user/Projects/cx-mdbstamp`. The clean launch HEAD was `9f5ec71ede25e7b7e4d44776bf47693d9a0c175e`, one manifest-only commit above `7cc0607dad2d9cc9398a47a772de261812015740`. `git diff 7cc0607da..9f5ec71ed --stat` showed only 8 changed lines in `tests/gate_measurements.json` (4 insertions, 4 deletions). All production source was identical to the assigned reference. PRE was built from that launch source before the production edit; it is not a reconstruction of the September baseline. PRE's entire `.text` is byte-identical to the launch-designated stable binary.

Implementation commit: `677a84c00` (`Stamp exact ordinary command ranges before metadata discovery`). Proof/build tooling commit: `306872ee8` (`Prove direct stamping and preserve dynamic namespace extraction serverlessly`). The lane's sole production edit is 26 added lines in `src/cmd/multidb.cc`. The inherited gate reference record is not a lane change.

**Re-verified diagnosis and change**

At launch, `multidb.cc:110-128` set the DB fields and then did MOVE/COPY name comparisons, COPY option scanning, vector construction, metadata resolution and extraction for every stamp. `cmdmeta.cc:258-279` scans the generated metadata names and builds `argv[0] + '|' + argv[1]`, including for GET. `cmdmeta.cc:313-418` performs dynamic extraction, including SORT tests and vector pushes. The throwaway bypass control actually observed **two allocation calls for this fixture's 24-byte GET**, plus one resolve and one collect call. That is not a claim of exactly two allocations or a fixed comparison count for every command, nor evidence that this cost explains most historical loss.

The parsers select/store the spec before stamping (`io_loop.h:3105-3127`, `reorder.cc:2659-2681`); registry shadow rows copy flags, ranges and dense ids (`commands.cc:171-205`). The new `stamp_regular_range` uses that selected spec, with no handler-pointer or command-spelling specialization. The class decision and successful return precede every cold name comparison, COPY option scan, vector and metadata call. Positive first/step and signed `argc + last_key` bound the loop; `last_key == -1` ends at `argc - 1`. Neither reply generation nor validation is added. Missing/excess arguments and dangling MSET keys are checked against explicit expectations and, for fixed ranges, the previous extractor.

Both overloads still call the same `stamp` template. It sets `db`, `physical_db`, `target_db` and `secondary_db` before the direct return, including for keyless commands. The live overload retains its original `DatabaseMap::Read` lifetime; the supplied overload uses EXEC's private map. All keys/endpoints in one stamp use that one map. COPY and MOVE remain entirely on the old endpoint/extraction path, including MOVE lowering and its saved display argument.

The 229-byte generated helper contains no call, heap operation, string access/comparison, table walk, atomic operation or shared-state store. It reads the selected spec and writes only the operation's key namespace fields. Disassembly: [direct-disassembly.txt](build/mdbstamp-logs/direct-disassembly.txt). Existing map-reader RMWs remain; this lane removes **zero producer RFOs on shared ownership/publication lines** by design. Allocation-related coherence effects are unmeasured. No telemetry, counter initialization, runtime switch, registry metadata or new per-operation state was added.

**Exact direct and cold classes**

The launch registry actually has 245 rows: 197 direct and 48 cold. This is the observed launch inventory, rather than the older shared-context count of 243. The admission rule excludes `ScriptRoute | StreamRoute | Blocking | SubcmdRoute`. All remaining non-MultiShard rows have exact singleton/empty ranges, except WATCH's exact whole-key tail. Their admitted families are ordinary string/bit/expiry, hash and hash-field TTL, list, set, zset, geo point, stream point/group point, RESTORE/PFDEBUG, and keyless control/admin/pubsub rows. Pubsub channels remain nonkeys. WATCH stamps its whole key tail.

For MultiShard, admission is deliberately narrower: `first_key == 1`, `last_key == -1`, `min_arity <= 3`, after the dynamic flags above are excluded. At this registry this admits exactly DEL/UNLINK/EXISTS/TOUCH, MGET, MSET/MSETNX (stride 2), PFCOUNT/PFMERGE, and SINTER/SUNION/SDIFF plus their STORE variants. Each family has only keys in the specified positions; MSET values are skipped. Z*STORE and GEORADIUS have superficially similar ranges but higher minimum arity and remain cold. The independent explicit cold inventory test fails if a registry change alters class membership. The proof also audits every direct row for argc 1 through 12 against the old extractor; dynamic grammar has a separate explicit oracle.

All direct commands, exactly:

```text
GET SET APPEND STRLEN GETRANGE SUBSTR SETRANGE SETBIT GETBIT BITFIELD BITFIELD_RO BITCOUNT BITPOS
GETSET SETNX SETEX PSETEX GETEX GETDEL DEL UNLINK EXISTS TOUCH MGET MSET MSETNX INCR DECR INCRBY
DECRBY INCRBYFLOAT PFADD PFCOUNT PFMERGE EXPIRE PEXPIRE EXPIREAT PEXPIREAT TTL PTTL PERSIST
EXPIRETIME PEXPIRETIME TYPE DUMP RESTORE HSET HMSET HSETNX HGET HMGET HDEL HLEN HEXISTS HSTRLEN
HINCRBY HINCRBYFLOAT HGETALL HKEYS HVALS HRANDFIELD HSCAN HEXPIRE HPEXPIRE HEXPIREAT HPEXPIREAT HTTL
HPTTL HEXPIRETIME HPEXPIRETIME HPERSIST LPUSH RPUSH LPUSHX RPUSHX LPOP RPOP LLEN LRANGE LINDEX LSET
LINSERT LREM LTRIM LPOS SADD SREM SISMEMBER SMISMEMBER SCARD SMEMBERS SPOP SRANDMEMBER SSCAN SINTER
SUNION SDIFF SINTERSTORE SUNIONSTORE SDIFFSTORE ZADD ZSCORE ZMSCORE ZINCRBY ZCARD ZCOUNT ZRANGE
ZRANGEBYSCORE ZREVRANGEBYSCORE ZRANGEBYLEX ZREVRANGEBYLEX ZREVRANGE ZRANK ZREVRANK ZREM
ZREMRANGEBYRANK ZREMRANGEBYSCORE ZREMRANGEBYLEX ZLEXCOUNT ZPOPMIN ZPOPMAX ZRANDMEMBER ZSCAN GEOADD
GEOPOS GEODIST GEOHASH GEOSEARCH XADD XLEN XRANGE XREVRANGE XDEL XTRIM XACK XPENDING XCLAIM
XAUTOCLAIM XSETID PING ACL SAVE BGSAVE BGREWRITEAOF LASTSAVE ECHO AUTH HELLO RESET QUIT SUBSCRIBE
UNSUBSCRIBE PSUBSCRIBE PUNSUBSCRIBE SSUBSCRIBE SUNSUBSCRIBE PUBLISH SPUBLISH PUBSUB CLIENT MONITOR
COMMAND CONFIG DEBUG FLIP INFO SELECT SWAPDB DBSIZE FLUSHALL FLUSHDB RANDOMKEY SCAN MULTI EXEC
DISCARD WATCH UNWATCH SCRIPT FUNCTION TIME LOLWUT ROLE WAIT WAITAOF FAILOVER REPLICAOF SLAVEOF
PFSELFTEST SHUTDOWN SLOWLOG LATENCY ASKING READONLY READWRITE RESTORE-ASKING PFDEBUG
```
All commands still reaching metadata extraction, exactly (also null-spec callers):

```text
BITOP RENAME RENAMENX COPY BLPOP BRPOP BLMPOP BLMOVE BRPOPLPUSH LMPOP LMOVE RPOPLPUSH SMOVE
SINTERCARD BZPOPMIN BZPOPMAX BZMPOP ZMPOP ZRANGESTORE ZUNION ZINTER ZDIFF ZUNIONSTORE ZINTERSTORE
ZDIFFSTORE ZINTERCARD GEOSEARCHSTORE GEORADIUS GEORADIUSBYMEMBER GEORADIUS_RO GEORADIUSBYMEMBER_RO
XREAD XGROUP XREADGROUP XINFO MOVE KEYS SORT EVAL EVALSHA EVAL_RO EVALSHA_RO FCALL FCALL_RO SORT_RO
OBJECT MEMORY LCS
```
This intentionally retains some exact scatter ranges on the cold path (BITOP, RENAME/RENAMENX, LMOVE/RPOPLPUSH, SMOVE, ZRANGESTORE/GEOSEARCHSTORE, LCS, read-only geo/SORT aliases and keyless KEYS). It does not claim every MultiShard row is irregular or optimize every possible exact range. COPY/MOVE endpoint semantics, scripts' key counts, stream key halves, blocking/count-based pops, zset counts/options, optional geo/SORT destinations, and keyed/keyless container children retain the old implementation. SORT BY/GET patterns remain pattern bytes, not indiscriminately stamped argv words; the pre-existing literal-STORE exception is reported separately below.

**Builds, layouts and artifacts**

PRE/POST and test-target builds used `taskset -c 112-127 make -j16`; standalone fixture/control compilers inherited that same affinity. Compiler: `g++ (Ubuntu 13.3.0-6ubuntu2~24.04.1) 13.3.0`. Release flags on both arms: `-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread`, jemalloc (`-DTOMO_JEMALLOC`, `-ljemalloc`), normal dual-runtime Makefile definitions and identical existing per-TU compiler budgets. No release flag differs between PRE and POST. Eight-core serverless fixtures ran on **112-119**, with 16 shards and 6:2 split where applicable. They instantiate owner/parser state but start no listener, ring or worker loop. `make test` was not run.

Commands actually run, all exit 0 after fixture development:

```bash
taskset -c 112-127 make -j16 all
# PRE saved before the edit as build/tomokv-mdbstamp-pre.
taskset -c 112-127 make -j16 all build/multidb-unit build/multidb-boundary-unit
taskset -c 112-119 ./build/multidb-unit
taskset -c 112-119 ./build/multidb-boundary-unit
taskset -c 112-127 python3 tests/multidb_serial.py --self-test
taskset -c 112-127 python3 tests/mdbstamp_controls.py
taskset -c 112-127 python3 tools/mdbstamp_artifacts.py build/tomokv-mdbstamp-post build/tomokv-mdbstamp-pad-a
taskset -c 112-127 python3 tools/mdbstamp_artifacts.py build/multidb-unit build/multidb-unit-pad-a
taskset -c 112-119 ./build/multidb-unit-pad-a --owners-only
```

Build logs: [PRE](build/mdbstamp-logs/build-pre.log), [POST](build/mdbstamp-logs/build-post.log), [test/release rebuild](build/mdbstamp-logs/build-tests.log), [final owner build](build/mdbstamp-logs/build-owner-final.log). All builds are release builds; test-only link wrappers count C++ new/array/aligned and C malloc/calloc/realloc/aligned calls and both metadata entry points only inside the stamp interval, after argv/spec/map/registry preparation.

Both runtime variants retain Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144 and Config 624. All layout-defining headers are unchanged, preserving offsets/cache-line sharing as well as sizes. Existing layout assertions passed; [compiled layout probe](build/mdbstamp-logs/layout.json) also records the Server member offsets in both variants. Offline object audit: all 27 executable sections and relocation records of the DB-0 multidb object are byte-identical; 71/73 common multi-runtime function bodies/targets are identical, with only the two stamping overloads changed plus the new helper. [Audit](build/mdbstamp-logs/object-audit.json).

| Arm | File bytes | .text bytes | SHA-256 |
|---|---:|---:|---|
| `build/tomokv-mdbstamp-pre` | 185312440 | 8215789 | `69b9a4aff76388481afe6d8b7d4e000b9292bd512a19d9133624b806eaea6437` |
| `build/tomokv-mdbstamp-post` | 185313176 | 8215997 | `5ea26d5b5caace59ad9b7b69caa65a1991d3a0d70d7960f993eb56dc69408d6b` |
| `build/tomokv-mdbstamp-pad-a` | 185313176 | 8215997 | `40e6b331d0607d3ab798e38b33bd80234d0939c22777bae96d606d58dc49f3e2` |
| `/home/user/Projects/bench-bins/tomokv-headline-7cc0607da` | 185312440 | 8215789 | `ca5eaa8cc8bec719fdd2017ffeb668b501c71ab8feeb4e954f1a70ed699073c5` |

`sha256sum build/tomokv`:

```text
5ea26d5b5caace59ad9b7b69caa65a1991d3a0d70d7960f993eb56dc69408d6b  build/tomokv
```

`build/tomokv` identifies POST. PRE/stable `.text` SHA-256 is `a5d5c9eae6e2790d1974784149ee91271de2a6c6d8c3fa9c62986c9138a3798b`. Full [artifact manifest](build/mdbstamp-logs/artifacts.json).

PAD is **(A) behaviour twin**, PRE stamping behavior in the exact POST text size/layout. The offline tool checks there is one outlined helper and exactly two callers, then replaces its first three bytes at file offset 7681792 with `31 c0 c3` (`xor eax,eax; ret`). Every command falls through to the old stamp body. All ELF sections, symbols, addresses and remaining bytes are unchanged. It does not select the DB-0 runtime; `--databases 16` still uses the multi-DB runtime. Limitation: PAD retains the extra helper call/return and its return-value branch versus PRE, so it is a layout control, not cycle-exact PRE. POST must improve while PAD is flat against PRE within identical-arm null bounds. Total `.text` grows only **208 bytes**, so no kind-B inverse control was built. [PAD construction record](build/mdbstamp-logs/pad-a.json).

**Observed serverless results and controls**

The existing owner row passed, including DB-0 identity/layout checks, armed/unarmed stores and TTL transitions, owner/scatter phases, MOVE/COPY, WATCH, native snapshot/AOF replay, SELECT and the untorn EXEC/SWAPDB array. It now also reports:

```text
PASS mdbstamp registry: 197 direct, 48 cold; fixed-range argc 1..12
PASS mdbstamp regular: 384 stamps, clean/notify/TLS/TLS-notify, live/private, repeat; zero allocations and metadata entries
```

The 384 stamps cover mixed-case GET/SET with short, 24-byte, embedded-NUL/high-byte and 4096-byte binary keys, and 17-key MGET/MSET/MSETNX and regular multi-key/WATCH requests beyond the 8-slot inline argv capacity. Every shadow has the same id and a distinct selected row. Namespace/byte/pointer checks together with zero metadata entries prove the keyed direct path executed. Test data construction and shadow selection are outside the allocation interval.

61 explicit semantic cases each pass four states: live map, repeated live stamp, a supplied private map differing from live, then reselect to a different logical DB with the private map. Each checks all four DB fields, every key/nonkey namespace, byte content/pointer, and absence of a stamp-generated reply. COPY DB/REPLACE and malformed options, MOVE, SORT STORE/BY/GET, all EVAL/FCALL variants, XREAD/GROUP halves, zset/pop key counts, container HELP/keyed/unknown arms and invalid arities/counts are represented. No dynamic case uses the old extractor as its oracle. [Owner output](build/mdbstamp-logs/owners-post.log).

The unchanged boundary test passed both 1s/2s stale-stamp schedules, each with a forced swap and intervening read; four acceptance fixtures (mode x read-local) each armed six windows; and both serial schedules (4 writers x p32 x 32 epochs, 32 delayed windows). [Boundary output](build/mdbstamp-logs/boundary-post.log). The unchanged serial oracle self-test passed its legal histories and rejected its stale-stamp counterexample. [Output](build/mdbstamp-logs/serial-self-test.log).

The negative-control driver built six independent throwaway implementations under `build/mdbstamp-controls`, linked them with the same test objects, and verified **77 expected exit-1 assertion failures**, with 12 successful compile/link commands. It verifies the named assertion text as well as status, so a crash or unrelated failure does not count. Exact source mutations and commands are in [the driver](tests/mdbstamp_controls.py), [results manifest](build/mdbstamp-controls/results.json), and each log. No mutation is in production source.

| Mutation | Exact substitution / purpose |
|---|---|
| no-direct | `if (stamp_regular_range(op)) return;` becomes `if (false && stamp_regular_range(op)) return;`; restore old cold body behavior |
| stride-one | `key += spec->key_step` becomes `key += 1`; stamps MSET values |
| no-fallback | unconditional return immediately after the direct-path check |
| no-copy-override | disable the final COPY destination namespace override |
| ignore-private | supplied-map overload calls the live-map overload instead |
| wrong-physical | `op.physical_db = map[logical]` becomes `op.physical_db = logical`; makes every semantic assertion sensitive to nonidentity maps, including keyless/invalid requests |

For the following table, exact invocation is `taskset -c 112-119 /home/user/Projects/cx-mdbstamp/build/mdbstamp-controls/<command>`. All listed failures were actually observed, not predicted. Their positive assertions pass in the final owner run.

| Throwaway command | Same assertion that failed | Status | Log |
|---|---|---:|---|
| `no-direct --stamp-check regular-alloc` | `FAIL mdbstamp: regular-zero-allocation` | 1 | [output](build/mdbstamp-controls/no-direct-regular-alloc.log) |
| `no-direct --stamp-check regular-metadata` | `FAIL mdbstamp: regular-no-metadata-entry` | 1 | [output](build/mdbstamp-controls/no-direct-regular-metadata.log) |
| `no-direct --stamp-check registry` | `FAIL mdbstamp: registry-classification` | 1 | [output](build/mdbstamp-controls/no-direct-registry.log) |
| `stride-one --stamp-check mset-stride` | `FAIL mdbstamp: mset-stride` | 1 | [output](build/mdbstamp-controls/stride-one-mset-stride.log) |
| `stride-one --stamp-check msetnx-stride` | `FAIL mdbstamp: msetnx-stride` | 1 | [output](build/mdbstamp-controls/stride-one-msetnx-stride.log) |
| `no-fallback --stamp-check sort-store` | `FAIL mdbstamp: sort-store` | 1 | [output](build/mdbstamp-controls/no-fallback-sort-store.log) |
| `no-fallback --stamp-check eval` | `FAIL mdbstamp: eval` | 1 | [output](build/mdbstamp-controls/no-fallback-eval.log) |
| `no-fallback --stamp-check xread` | `FAIL mdbstamp: xread` | 1 | [output](build/mdbstamp-controls/no-fallback-xread.log) |
| `no-fallback --stamp-check zunionstore` | `FAIL mdbstamp: zunionstore` | 1 | [output](build/mdbstamp-controls/no-fallback-zunionstore.log) |
| `no-copy-override --stamp-check copy-db-replace` | `FAIL mdbstamp: copy-db-replace` | 1 | [output](build/mdbstamp-controls/no-copy-override-copy-db-replace.log) |
| `ignore-private --stamp-check get24` | `FAIL mdbstamp: get24` | 1 | [output](build/mdbstamp-controls/ignore-private-get24.log) |
| `ignore-private --stamp-check copy-db-replace` | `FAIL mdbstamp: copy-db-replace` | 1 | [output](build/mdbstamp-controls/ignore-private-copy-db-replace.log) |
| `ignore-private --stamp-check move` | `FAIL mdbstamp: move` | 1 | [output](build/mdbstamp-controls/ignore-private-move.log) |
| `wrong-physical --stamp-check regular` | `FAIL mdbstamp: regular-shadow-namespaces` | 1 | [output](build/mdbstamp-controls/wrong-physical-regular.log) |
| `wrong-physical --stamp-check registry` | `FAIL mdbstamp: registry-range-equivalence` | 1 | [output](build/mdbstamp-controls/wrong-physical-registry.log) |
| `ignore-private --owners-only` | `SWAPDB/SELECT/MOVE share one untorn EXEC array` | 1 | [output](build/mdbstamp-controls/ignore-private-exec.log) |

Selected actual failure output:

```text
GET variant=0 bytes=24 allocations=2
FAIL mdbstamp: regular-zero-allocation
GET resolve=1 collect=1
FAIL mdbstamp: regular-no-metadata-entry
mset-stride argv[2]: ns=9 expected=0, bytes/pointer=same
FAIL mdbstamp: mset-stride
sort-store argv[9]: ns=0 expected=9, bytes/pointer=same
FAIL mdbstamp: sort-store
copy-db-replace argv[2]: ns=9 expected=10, bytes/pointer=same
FAIL mdbstamp: copy-db-replace
get24 argv[1]: ns=9 expected=10, bytes/pointer=same
FAIL mdbstamp: get24
FAIL multidb: SWAPDB/SELECT/MOVE share one untorn EXEC array
```

Each explicit semantic assertion below has its own `wrong-physical` run. Exact positive command is `taskset -c 112-119 ./build/multidb-unit --stamp-check NAME`; the same positive assertions also ran in the combined owner test. Exact negative command is `taskset -c 112-119 ./build/mdbstamp-controls/wrong-physical --stamp-check NAME`. Each log contains `FAIL mdbstamp: NAME` and `STATUS 1`. The more specific stride/fallback/COPY/private-map controls above additionally verify the requested mechanisms.

| NAME / semantic assertion | Positive | Negative status | Negative log |
|---|---|---:|---|
| `get24` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-get24.log) |
| `mset-stride` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-mset-stride.log) |
| `msetnx-stride` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-msetnx-stride.log) |
| `mset-dangling` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-mset-dangling.log) |
| `get-missing` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-get-missing.log) |
| `get-extra` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-get-extra.log) |
| `set-options` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-set-options.log) |
| `ping-keyless` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-ping-keyless.log) |
| `select-keyless` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-select-keyless.log) |
| `copy-db-replace` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-copy-db-replace.log) |
| `copy-default` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-copy-default.log) |
| `copy-repeat-db` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-copy-repeat-db.log) |
| `copy-invalid-db` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-copy-invalid-db.log) |
| `copy-missing-db` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-copy-missing-db.log) |
| `copy-invalid-option` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-copy-invalid-option.log) |
| `move` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-move.log) |
| `move-invalid-db` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-move-invalid-db.log) |
| `move-invalid-arity` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-move-invalid-arity.log) |
| `sort-store` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-sort-store.log) |
| `sort-patterns` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-sort-patterns.log) |
| `sort-ro` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-sort-ro.log) |
| `sort-invalid-store` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-sort-invalid-store.log) |
| `eval` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-eval.log) |
| `eval-ro` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-eval-ro.log) |
| `evalsha` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-evalsha.log) |
| `evalsha-ro` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-evalsha-ro.log) |
| `fcall` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-fcall.log) |
| `fcall-ro` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-fcall-ro.log) |
| `eval-zero` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-eval-zero.log) |
| `eval-overcount` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-eval-overcount.log) |
| `eval-bad-count` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-eval-bad-count.log) |
| `xread` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-xread.log) |
| `xreadgroup` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-xreadgroup.log) |
| `xread-no-streams` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-xread-no-streams.log) |
| `xread-odd-tail` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-xread-odd-tail.log) |
| `zunionstore` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-zunionstore.log) |
| `zinterstore` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-zinterstore.log) |
| `zdiffstore` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-zdiffstore.log) |
| `zunion` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-zunion.log) |
| `zintercard` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-zintercard.log) |
| `sintercard` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-sintercard.log) |
| `zstore-bad-count` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-zstore-bad-count.log) |
| `zmpop` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-zmpop.log) |
| `lmpop` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-lmpop.log) |
| `bzmpop` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-bzmpop.log) |
| `blmpop` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-blmpop.log) |
| `blpop` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-blpop.log) |
| `brpop` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-brpop.log) |
| `bzpopmin` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-bzpopmin.log) |
| `bzpopmax` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-bzpopmax.log) |
| `georadius` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-georadius.log) |
| `georadius-member` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-georadius-member.log) |
| `object-help` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-object-help.log) |
| `object-invalid` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-object-invalid.log) |
| `object-key` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-object-key.log) |
| `memory-help` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-memory-help.log) |
| `memory-key` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-memory-key.log) |
| `xgroup-help` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-xgroup-help.log) |
| `xgroup-key` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-xgroup-key.log) |
| `xinfo-help` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-xinfo-help.log) |
| `xinfo-key` | PASS | 1 | [output](build/mdbstamp-controls/wrong-physical-xinfo-key.log) |

Fixture preparation failures (allocation/setup, registered command, valid test selector) are fatal setup checks, not evidence of a namespace property. All behavioral assertion labels above have a recorded negative. No unarmed window is skipped. The existing owner EXEC test is the explicit SELECT/SWAPDB-before-later-child witness; its unchanged exact reply assertion fails under `ignore-private --owners-only`.

All 61 explicit semantic cases also passed on both the bypassed-direct-path binary and the kind-A PAD unit (122 positive runs, each exit 0). The PAD unit's two regular allocation/metadata selections each returned 1 with the same named failure; this verifies that PAD restores the removed work. [Commands/statuses](build/mdbstamp-logs/pad-a-semantics.json), [output](build/mdbstamp-logs/pad-a-semantics.log). PAD's original owner/EXEC scenarios passed with `--owners-only` (exit 0), [output](build/mdbstamp-logs/pad-a-owners.log).

**Uncovered defect — retained, outside this optimization**

The existing SORT special case in `cmdmeta.cc:327-336` scans all argv words for STORE without skipping BY/GET patterns. The execution parser in `xshard_commands.inc:233-283` skips those pattern arguments. For valid `SORT src STORE dst BY STORE LIMIT 0 2`, logical DB 1 mapped to physical 9, stamping incorrectly leaves actual destination argv[3] at namespace 0 and stamps nonkey LIMIT argv[6] with 9. A throwaway explicit oracle expecting only argv[1] and argv[3] to be keys was linked once with the saved PRE object and once with POST. The oracle adds this one `Case` to the test-only semantic list: `{"sort-pattern-store-word", {"SORT", "src", "STORE", "dst", "BY", "STORE", "LIMIT", "0", "2"}, {1,3}}`. Both actually returned 1:

```text
sort-pattern-store-word argv[3]: ns=0 expected=9, bytes/pointer=same
sort-pattern-store-word argv[6]: ns=9 expected=0, bytes/pointer=same
FAIL mdbstamp: sort-pattern-store-word
```

Reproduction commands: `taskset -c 112-119 ./build/mdbstamp-controls/sort-oracle-pre --stamp-check sort-pattern-store-word` and the identical command with `sort-oracle-post`. Generated test source: `build/mdbstamp-controls/sort-oracle.cc`; compile/link commands, actual outputs/statuses: [sort-existing-defect.log](build/mdbstamp-controls/sort-existing-defect.log). This is a pre-existing namespace correctness defect, potentially writing a SORT destination into physical DB 0 and breaking selected-DB RYOW. The stamp mismatch is confirmed; full-command/live impact remains mainline-only PENDING. The source is unchanged because generic COMMAND metadata and unrelated fixes are out of scope. It must not be mistaken for a new POST regression or for a passing correctness proof of that input.

**Mainline-only correctness and gate arithmetic — PENDING**

Retain and run `multidb serverless owners`, `multidb global namespace boundary`, all eight `multidb ($mode, read-local $rl, atomic $at)` and all eight corresponding `SWAPDB serial order` rows. Live geometry is **eight physical cores, `--shards 16 --ratio 6:2 --databases 16`, modes 1s/2s x read-local 0/1 x atomic 0/1**. A default boot or one client is not this geometry. Retain COMMAND GETKEYS*/GETKEYSANDFLAGS and ACL, SORT, script, stream, blocking, multi_exec and Redis 7.4 differential coverage. Both modes' real boots/live batteries are PENDING; serverless parser/owner fixtures do not substitute for them.

Only existing owner-row coverage was extended. `tests/gate.sh` is byte-identical: owner emission/collection lines 1298-1302, boundary 1303-1308, live emission 2573-2593 and collection 2783-2786 all precede quick exit at 2808-2812. Added/retired public rows = **0**. Required counts remain **438 quick / 454 full**, i.e. 438+0 / 454+0; `EXPECT_QUICK` and `EXPECT_FULL` were not edited.

`tests/multidb_db0_unit.cc`, `tests/multidb_boundary_unit.cc`, map Read/publication code, both parser files, `multi.inc`, and `cmdmeta.cc` are unchanged. `tests/multidb_serial.py` is unchanged in full, including lines 20-57 byte-for-byte (SHA-256 of those lines `36e182fa3889e4b02db2efee52fe2a966c7050c7120eb6eb2bcd7c9a006d9af0`). [Unchanged-file evidence](build/mdbstamp-logs/unchanged.json). SWAPDB Database* stages, reclamation memory orders, pause-before-stamp, blocking remap, WATCH and atomic visibility are untouched. No law is relaxed to make a test pass.

**Measurement request — all results PENDING**

Use the gate's ABBA instrument. First pair PRE(A) / POST(B); then stable(A) / POST(B), using the exact stable file and digest above. Also pair PRE(A) / PAD-A(B) and compare POST/PAD at the same configuration. Collect paired identical-arm controls before scoring, with matching code/configuration/workload/placement. All arms within a pair must use the same `--databases` value; changing database runtime between arms is invalid. Keep load rungs and per-generator placements fixed across arms, record server argv and workload bytes, and never recalibrate between arms.

Headline performance geometry is the recorded **server cores 0-31, load cores 32-111, no SMT**, split ratio **16:16**. The current instrument computes **256 shards in 1s and 128 shards in 2s** at this placement. This differs from the required eight-core live-correctness geometry above. Preserve that performance geometry and the instrument's `load_layout` distribution of **512 total connections**. Preserve atomic=1 and the exact read-local/overlap/reorder flags below. At p1 and p32 require saturation evidence at matched offered load; one connection, a single-reader loop, or instruction counts alone is not the verdict. The ordinary population is two million keys and 64-byte values; MGET/MSET use eight independently generated keys per operation. No SWAPDB in any stamp-cost cell.

Required headline definitions copied from launch `tests/headline_cells.txt`:

```text
h05 | 1s | rl=0 | ov=1 | ro=0 | GET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
h06 | 1s | rl=0 | ov=1 | ro=0 | SET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
h07 | 1s | rl=0 | ov=1 | ro=1 | GET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=1
h08 | 1s | rl=0 | ov=1 | ro=1 | SET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
h13 | 1s | rl=1 | ov=1 | ro=0 | GET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
h14 | 1s | rl=1 | ov=1 | ro=0 | SET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
h15 | 1s | rl=1 | ov=1 | ro=1 | GET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=1
h16 | 1s | rl=1 | ov=1 | ro=1 | SET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
h21 | 2s | rl=0 | ov=1 | ro=0 | GET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
h22 | 2s | rl=0 | ov=1 | ro=0 | SET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
h23 | 2s | rl=0 | ov=1 | ro=1 | GET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=1
h24 | 2s | rl=0 | ov=1 | ro=1 | SET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
h29 | 2s | rl=1 | ov=1 | ro=0 | GET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
h30 | 2s | rl=1 | ov=1 | ro=0 | SET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
h31 | 2s | rl=1 | ov=1 | ro=1 | GET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=1
h32 | 2s | rl=1 | ov=1 | ro=1 | SET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
h37 | 1s | rl=0 | ov=1 | ro=0 | GET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h38 | 1s | rl=0 | ov=1 | ro=0 | SET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h39 | 1s | rl=0 | ov=1 | ro=1 | GET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h40 | 1s | rl=0 | ov=1 | ro=1 | SET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h45 | 1s | rl=1 | ov=1 | ro=0 | GET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h46 | 1s | rl=1 | ov=1 | ro=0 | SET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h47 | 1s | rl=1 | ov=1 | ro=1 | GET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h48 | 1s | rl=1 | ov=1 | ro=1 | SET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=1
h53 | 2s | rl=0 | ov=1 | ro=0 | GET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h54 | 2s | rl=0 | ov=1 | ro=0 | SET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h55 | 2s | rl=0 | ov=1 | ro=1 | GET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h56 | 2s | rl=0 | ov=1 | ro=1 | SET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h61 | 2s | rl=1 | ov=1 | ro=0 | GET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h62 | 2s | rl=1 | ov=1 | ro=0 | SET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h63 | 2s | rl=1 | ov=1 | ro=1 | GET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
h64 | 2s | rl=1 | ov=1 | ro=1 | SET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
```

Regular multi-key traffic uses the following existing definitions (both modes/read-local states, p1/p32, eight-key MGET/MSET):

```text
m13 | 1s | rl=0 | ov=1 | ro=0 | MGET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
m15 | 1s | rl=0 | ov=1 | ro=0 | MGET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
m16 | 1s | rl=0 | ov=1 | ro=0 | MSET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
m18 | 1s | rl=0 | ov=1 | ro=0 | MSET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
m37 | 1s | rl=1 | ov=1 | ro=0 | MGET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
m39 | 1s | rl=1 | ov=1 | ro=0 | MGET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
m40 | 1s | rl=1 | ov=1 | ro=0 | MSET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
m42 | 1s | rl=1 | ov=1 | ro=0 | MSET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
m61 | 2s | rl=0 | ov=1 | ro=0 | MGET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
m63 | 2s | rl=0 | ov=1 | ro=0 | MGET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
m64 | 2s | rl=0 | ov=1 | ro=0 | MSET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
m66 | 2s | rl=0 | ov=1 | ro=0 | MSET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
m85 | 2s | rl=1 | ov=1 | ro=0 | MGET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
m87 | 2s | rl=1 | ov=1 | ro=0 | MGET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
m88 | 2s | rl=1 | ov=1 | ro=0 | MSET | p1 | 512 | - | - | - | atomic=1 | score=latency | mix=- | smoke=0
m90 | 2s | rl=1 | ov=1 | ro=0 | MSET | p32 | 512 | - | - | - | atomic=1 | score=rate | mix=- | smoke=0
```

Historical p8 definitions, copied verbatim from `/home/user/Projects/calib/p8-cells.txt`:

```text
p8g1 | 2s | rl=0 | ov=1 | ro=0 | GET | p8 | 512 | - | - | 2 | atomic=1 | score=rate | mix=- | smoke=0
p8s0 | 2s | rl=0 | ov=0 | ro=0 | SET | p8 | 512 | - | - | 2 | atomic=1 | score=rate | mix=- | smoke=0
p8s1 | 2s | rl=0 | ov=1 | ro=0 | SET | p8 | 512 | - | - | 2 | atomic=1 | score=rate | mix=- | smoke=0
f8g1 | 1s | rl=0 | ov=1 | ro=0 | GET | p8 | 512 | - | - | 12 | atomic=1 | score=rate | mix=- | smoke=0
```

Provenance is the mainline round-2 launch in `/home/user/Projects/endgame.log:4037`: `CELLS_FILE=/home/user/Projects/calib/p8-cells.txt ... lane-measure.sh mdb2_p8 ... POST=/home/user/Projects/bench-bins/tomokv-multidb2-42bed6ec2`. It used that actual file and the server/load placement above. The legacy column pins 2 generators for p8g1/p8s0/p8s1 and 12 for f8g1; these are not reinterpreted as headline IDs. Historical p8g0 is outside the four requested carry-forward cells. The copied p8 file SHA-256 is `bf9c7e1157ebc6c579dcc2cc032c93273acbba32ff319b14e20ecb4c2789cc1a`; launch `headline_cells.txt` is `d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350` and `gate_measurements.json` is `53d3960c56681db539ead49781b7a768df8e963463efe9cdebf90b70bd843655`.

Launch load-floor inventory (historical-unverified numbers are recorded data, **not validated pins**):

| Cell | Stored instances | Launch status |
|---|---:|---|
| h05 | 12 | calibrated |
| h06 | 4 | historical-unverified |
| h07 | 12 | calibrated |
| h08 | 3 | historical-unverified |
| h13 | 3 | historical-unverified |
| h14 | 3 | historical-unverified |
| h15 | 12 | calibrated |
| h16 | 3 | historical-unverified |
| h21 | 2 | calibrated |
| h22 | 2 | historical-unverified |
| h23 | 2 | calibrated |
| h24 | 2 | historical-unverified |
| h29 | 2 | historical-unverified |
| h30 | 2 | historical-unverified |
| h31 | 12 | calibrated |
| h32 | 2 | historical-unverified |
| h37 | — | no recorded pin |
| h38 | — | no recorded pin |
| h39 | — | no recorded pin |
| h40 | — | no recorded pin |
| h45 | — | no recorded pin |
| h46 | — | no recorded pin |
| h47 | — | no recorded pin |
| h48 | — | no recorded pin |
| h53 | — | no recorded pin |
| h54 | — | no recorded pin |
| h55 | — | no recorded pin |
| h56 | — | no recorded pin |
| h61 | — | no recorded pin |
| h62 | — | no recorded pin |
| h63 | — | no recorded pin |
| h64 | — | no recorded pin |
| m13 | — | no recorded pin |
| m15 | — | no recorded pin |
| m16 | — | no recorded pin |
| m18 | — | no recorded pin |
| m37 | — | no recorded pin |
| m39 | — | no recorded pin |
| m40 | — | no recorded pin |
| m42 | — | no recorded pin |
| m61 | — | no recorded pin |
| m63 | — | no recorded pin |
| m64 | — | no recorded pin |
| m66 | — | no recorded pin |
| m85 | — | no recorded pin |
| m87 | — | no recorded pin |
| m88 | — | no recorded pin |
| m90 | — | no recorded pin |

Three regimes must be reported separately for every ordinary cell above, with frozen generator input and identical arms:

| Regime | DB configuration | Key bytes / traffic | Scoring |
|---|---|---|---|
| Benefit B | `--databases 16` | exactly 24-byte keys; ordinary GET/SET and eight-key MGET/MSET | lower cycles/op required; rate >= PRE and stable per cell |
| Neutral N | `--databases 1` | identical 24-byte keys, values, traffic, population and placements as B | paired null; no higher cycles/op or worse scored latency; rate parity per cell |
| Deficit D-short | `--databases 16` | exactly 8-byte short keys, same cardinality/values/cells | no higher cycles/op or worse scored latency; rate parity per cell |

Specify key generation by bytes, not an assumed memtier default: use an eight-digit decimal index for short keys and a fixed 16-byte prefix plus the identical eight-digit index for 24-byte keys (two million indices, e.g. 10000000..11999999). All population, sampled hit checks and measured commands must agree on that mapping; record actual key lengths. This is a requested workload setting, not a claim that the stock instrument currently emits 24-byte keys.

The possible-deficit irregular rows below are separate named requests, **not invented headline IDs**. Use databases=16, no swaps, both modes, read-local 0/1, atomic=1, overlap=1, reorder=0, p1/p32, 512 connections and the same physical placements. Freeze a common valid load rung before any arm comparisons; it is currently PENDING. Use an immutable prepopulated source set (16384 source keys; 24-byte and 8-byte variants), per-key destinations where applicable, and reinitialize the same dataset before each arm. Avoid source exhaustion so the steady-state request remains the specified operation.

| Row | Exact request template | Initial state / steady-state behavior |
|---|---|---|
| D-COPY | `COPY src(i) dst(i) REPLACE` | 64-byte source strings and existing destination keys, same logical DB; replacement each time |
| D-SORT | `SORT src(i) BY nosort GET # STORE dst(i)` | eight-element source lists and existing destination lists; no external pattern dereferences |
| D-EVAL | `EVAL_RO "return redis.call('GET',KEYS[1])" 1 src(i) argv` | source strings; one actual key and one ARGV value |
| D-FCALL | `FCALL_RO mdbstamp_read 1 src(i) argv` | preloaded function returns `redis.call('GET', keys[1])`; same source strings |
| D-XREAD | `XREAD COUNT 1 STREAMS src(i) 0-0` | immutable streams with one fixed entry; key/ID halves always present |

The owner should retain separate raw cells for each row x key width x mode x read-local x depth, never average them together. These nominated deficit fixtures require mainline instrument support; no lane execution or calibration occurred. COPY DB overrides, SORT external BY/GET, FCALL/EVAL counts and XREADGROUP/blocking semantics are covered by the serverless/live correctness requests independently of this steady-state performance matrix.

**Instrument gaps and strict acceptance**

At launch, many required h/m cells have no validated pin (table above), and p1 has no stored pin and is explicitly saturation-exempt in `abbagate.py:108-119`. `read_cells` admits GET/SET/MGET/MSET/MSETNX/MIX/REORDER, not the irregular requests above; stock runner argv has no database-count/key-length selection. Mainline must supply its pinned driver definitions or a reviewed instrument adapter for these requested regimes before measurements can count. Do not run the stock default database runtime and label it the databases=16 benefit arm. This lane adds no general harness change or production knob.

Also, current `abbagate.py:625-629` can apply a **5% read-local threshold floor**, and its null-bound logic can raise the spread limit. Those generic PASS labels are insufficient for this lane's explicit bar: **spread >2% invalidates a run; it never widens acceptance**, databases=1 must be a paired null, and there is no 3% or 5% loss allowance. Preserve the existing instrument's valid identical-arm null resolution and load placement, but inspect raw rows against the stricter user-specified conditions. Missing pins, missing saturated p1 evidence, unsupported workload settings or unstable controls remain PENDING/INVALID, never silently replaced by a guessed cell, a calibration between arms, or a relaxed threshold.

For every arm and every cell, record raw rate, cycles/op, instructions/op, IPC, and tail (p50/p99/p99.9 plus the cell's scored latency), at matched offered load. Check `cycles/op = instructions/op / IPC` on consistently normalized counters. Pass requires lower cycles/op in intended benefit cells; POST rate >= PRE **and** stable in every scored cell; no higher cycles/op or worse scored latency in neutral/deficit cells. The weakest cell decides. Instruction reduction, averaged rates, sub-saturation timing and apparent allocator savings are not acceptance. PAD must stay flat while POST improves before attributing a gain to the stamp change. All these checks remain mainline-only PENDING.

PRE/POST ledger below: every metric entry is `(rate, cycles/op, instr/op, IPC, scored latency + tail)`. Each row expands into **B, N and D-short as separately scored records**, with the exact definitions above; no entry is an average. The stable and PAD comparisons use the same expanded records.

| Cell | PRE metrics | POST metrics | Stable/PAD comparison | Verdict |
|---|---|---|---|---|
| h05 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h06 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h07 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h08 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h13 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h14 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h15 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h16 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h21 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h22 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h23 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h24 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h29 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h30 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h31 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h32 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h37 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h38 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h39 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h40 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h45 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h46 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h47 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h48 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h53 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h54 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h55 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h56 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h61 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h62 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h63 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| h64 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m13 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m15 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m16 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m18 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m37 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m39 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m40 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m42 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m61 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m63 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m64 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m66 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m85 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m87 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m88 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| m90 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| p8g1 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| p8s0 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| p8s1 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| f8g1 [B/N/D-short separately] | PENDING | PENDING | PENDING | PENDING |
| D-COPY [each width/mode/rl/depth separately] | PENDING | PENDING | PENDING | PENDING |
| D-SORT [each width/mode/rl/depth separately] | PENDING | PENDING | PENDING | PENDING |
| D-EVAL [each width/mode/rl/depth separately] | PENDING | PENDING | PENDING | PENDING |
| D-FCALL [each width/mode/rl/depth separately] | PENDING | PENDING | PENDING | PENDING |
| D-XREAD [each width/mode/rl/depth separately] | PENDING | PENDING | PENDING | PENDING |

The measured gain hypothesis is unresolved. No MEASURE-RESULT has been supplied. The report stops at a committed, reviewable change and explicit pending requests.

**Diff from assigned base**

The following `git diff 7cc0607da --stat` includes this report and the inherited launch reference record. No other worktree was edited.

```text
 MEASURE-REQUEST-mdbstamp.md  | 489 +++++++++++++++++++++++++++++++++++++++++++
 Makefile                     |  10 +-
 src/cmd/multidb.cc           |  26 +++
 tests/gate_measurements.json |   8 +-
 tests/mdbstamp_checks.cc     | 308 +++++++++++++++++++++++++++
 tests/mdbstamp_controls.py   |  91 ++++++++
 tests/multidb_unit.cc        |  13 +-
 tools/mdbstamp_artifacts.py  |  48 +++++
 8 files changed, 986 insertions(+), 7 deletions(-)
```
