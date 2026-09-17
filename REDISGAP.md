# TomoKV Redis configuration gap — 2026-09-08

**TomoKV refuses to boot on unknown configuration names; the tested files are not silently accepted.** The original 155-name gap against Redis 7.4.10 consists of **64 DELIBERATE, 61 SHOULD EXIST, and 30 NOT APPLICABLE** names. This diff binds **11 Redis names to seven controls**, leaving **144 unbound names**, including **50 SHOULD EXIST**. Historical aliases count separately because `CONFIG GET *` reports them separately. These are configuration-name counts, not a count of independent features or a claim of complete Redis compatibility.

The checkout under test is `c8e61f64628655bf99acb91cd986684e5c608fde` (`cx-redisgap`), not the older `78c3e5391` context baseline. Its parser already accepts 73 names, rather than 65. The overlap with the 202 reference names remains 47. The current tree explicitly locks `Config` at 528 bytes following its knob-collapse wave; this patch preserves that lock and the other checked-in layout assertions. The three new fields consume existing alignment holes. Existing key/value algorithms, owner structures, reader protocols and default thresholds remain unchanged.

| Observed surface | PRE | POST |
|---|---:|---:|
| Redis 7.4.10 `CONFIG GET *` names | 202 | 202 |
| TomoKV startup parser names (excluding help / conf-file selector) | 73 | 84 |
| Redis names bound at startup | 47 | 58 |
| Redis names without a startup binding | 155 | 144 |
| TomoKV `CONFIG GET *` names, both modes | 63 | 77 |
| Redis names visible through TomoKV `CONFIG GET *` | 44 | 58 |
| Focused regression suite against each binary | FAIL at first new alias | PASS in 2s and 1s |
| Server-less existing config-parser test | not run on PRE | PASS |

`--conf` is handled by main before the parser; file-only `pin` and command-line help are also excluded from the 73/84 parser count. The inventory includes real `user`/placement/study parser names, so it is not identical to the runtime configuration table. `bind`, `port`, and `unixsocket` were startup bindings missing from the runtime table; this diff exposes their actual boot values and rejects runtime mutation. They are additional introspection fixes, not part of the original 155.

## Measurement and evidence

The reference binaries came from `/home/user/Projects/bench-bins/MANIFEST.md`. All build, server, reference, and Python processes were launched under `taskset -c 68-79`; the focused suite additionally checks every actual worker affinity mask. Probes used ports 8120–8127 only. The split-mode geometry was `--shards 16 --ratio 6:2`; fused mode used `--shards 16` on the 12 allowed cores. Traffic was bounded correctness/configuration commands, without a load generator, rate measurement, or full gate. Each harness stops only its own `Popen` PID and waits for exit; the regression harness also requires the kernel to release lingering io_uring listener references before the next arm. No pattern kill was used.

| Binary | Observed identity | SHA-256 |
|---|---|---|
| `/home/user/Projects/redis74/src/redis-server` | `Redis server v=7.4.10 sha=f103d127:0 malloc=jemalloc-5.3.0 bits=64 build=f39586913084a746` | `ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b` |
| `/home/user/Projects/redis-8.8.1/src/redis-server` | `Redis server v=8.8.1 sha=77b6c308:0 malloc=jemalloc-5.3.0 bits=64 build=a141229ebac5eecc` | `7818d7f71e7bb4574cd9b810f3f64e28dd48b36524de7608f2794fe7f236a390` |
| Preserved `build/redisgap/tomokv-pre` | current checkout before this diff | `8c50529e824249a73f3af7b3cc541df454ede73376934d8bd652d574553a49fc` |
| `build/tomokv` | this diff | `b53566f47f7565acc9a4adb8160d43e62ed804ea2bc15fcb036995fc01ecfc50` |

The local evidence directory is `build/redisgap/` (ignored build artifacts): reference and PRE/POST `CONFIG GET *` JSON, parser name sets, all-name runtime probes, startup command/stdout/stderr/exit captures, raw protocol replies, fixture files, compiler logs and binary identities. The full classification below is durable in this report; the build artifacts are supplementary. [The pinned Redis 7.4.10 example configuration](https://raw.githubusercontent.com/redis/redis/7.4.10/redis.conf) and [Redis CONFIG GET](https://redis.io/docs/latest/commands/config-get/) / [CONFIG SET](https://redis.io/docs/latest/commands/config-set/) documentation were consulted alongside the local source and the actual binaries. The 202/218 inventories are measured, not inferred from documentation.

## Unknown configuration file behavior

The realistic fixture is the complete upstream 7.4.10 `redis.conf`, including its comments and ordinary persistence, logging, replication, memory, and tuning directives. Four active lines were changed to confine the experiment: `bind 127.0.0.1` (the native parser only accepts one address), `port 8122`, `dir /home/user/Projects/cx-redisgap/build/redisgap/realistic-data`, and `pidfile /home/user/Projects/cx-redisgap/build/redisgap/realistic.pid`. Nothing was filtered out based on TomoKV support. Redis 7.4.10 accepted it and returned `PONG` and 202 configuration names; the reference launcher also overrode `save ""`, `appendonly no`, `daemonize no`, and its data directory for this disposable run.

Upstream fixture SHA-256: `528f53f3ffc6255bbc8a5281d5977e7aaad164233db7cf6b7896f096115fe900`. Adapted fixture SHA-256: `54a30dbaca93b6d2aa6c9b55d871c176938b722e5c36ae42664497c702a7b153`.

Exact TomoKV invocation:

```sh
taskset -c 68-79 /home/user/Projects/cx-redisgap/build/redisgap/tomokv-pre /home/user/Projects/cx-redisgap/build/redisgap/realistic-redis.conf --thread-mode 2s --shards 16 --ratio 6:2
```

Exit status **1**. stdout was **empty**. Complete stderr:

```text
unknown argument '--daemonize' (see --help)
(while parsing /home/user/Projects/cx-redisgap/build/redisgap/realistic-redis.conf)
```

A focused realistic cache fragment isolates a tuning parameter from process-management defaults:

```conf
bind 127.0.0.1
port 8123
save ""
maxmemory 256mb
maxmemory-policy allkeys-lru
loglevel notice
```

Exit status **1**, empty stdout, complete stderr:

```text
unknown argument '--loglevel' (see --help)
(while parsing /home/user/Projects/cx-redisgap/build/redisgap/focused-loglevel.conf)
```

Replacing that last line with the misspelling `maxmemroy 256mb` also exits **1**, with empty stdout and this complete stderr:

```text
unknown argument '--maxmemroy' (see --help)
(while parsing /home/user/Projects/cx-redisgap/build/redisgap/focused-typo.conf)
```

**Observed category: refuses to boot and names the unknown argument.** The diagnostic adds the config filename but not the directive line number. No fix to unknown-name rejection was necessary. The POST binary produced the identical complete stderr and exit status for the realistic fixture in both modes. This patch leaves that behavior in place; it does not make an arbitrary stock Redis file bootable.

## CONFIG GET and CONFIG SET behavior

All 155 missing names were individually probed against PRE in both 2s and 1s, using each reference value for SET. Every GET returned an empty result; every SET returned the unknown-option error naming that parameter. All 144 still-unbound names were checked the same way against POST, in both modes, with the same result. A representative exact wire capture follows (`\r\n` below denotes the actual CRLF bytes):

| Protocol | Command | Observed wire response |
|---|---|---|
| RESP2 | `CONFIG GET loglevel` | `*0\r\n` |
| RESP2 | `CONFIG SET loglevel notice` | `-ERR Unknown option or number of arguments for CONFIG SET - 'loglevel'\r\n` |
| RESP3 | `CONFIG GET loglevel` | `%0\r\n` |
| RESP3 | `CONFIG SET loglevel notice` | `-ERR Unknown option or number of arguments for CONFIG SET - 'loglevel'\r\n` |

Further observed RESP2 replies (the Python representation preserves the error text):

```text
CONFIG GET cluster-enabled => []
CONFIG SET cluster-enabled no => {"error": "ERR Unknown option or number of arguments for CONFIG SET - 'cluster-enabled'"}
CONFIG GET does-not-exist => []
CONFIG SET does-not-exist 1 => {"error": "ERR Unknown option or number of arguments for CONFIG SET - 'does-not-exist'"}
CONFIG GET timeout => ["timeout", "0"]
CONFIG SET timeout 17 does-not-exist 1 => {"error": "ERR Unknown option or number of arguments for CONFIG SET - 'does-not-exist'"}
CONFIG GET timeout => ["timeout", "0"]
```

An empty GET is Redis-compatible for an unknown name: tooling must treat absence as unsupported, not as a default or successful configuration. Redis itself returned the identical unknown-option SET error for `does-not-exist`. For names it actually implements, Redis returned `loglevel = notice` and `OK` on SET; its `cluster-enabled` SET failed as immutable instead of unknown. TomoKV rejects the whole mixed SET before applying the known timeout. The focused regression also covers this in RESP3.

## Implemented bindings and limits

| Redis names added | Existing behavior selected | Surfaces and limitations |
|---|---|---|
| `hash-max-listpack-entries`, `hash-max-ziplist-entries` | `TypeLimits::hash.max_entries` | File/CLI, live SET, GET, rewrite. Canonical decimal count. |
| `hash-max-listpack-value`, `hash-max-ziplist-value` | `TypeLimits::hash.max_value` | File/CLI, live SET, GET, rewrite. Redis byte-unit grammar. |
| `zset-max-listpack-entries`, `zset-max-ziplist-entries` | `TypeLimits::zset.max_entries` | File/CLI, live SET, GET, rewrite. Canonical decimal count. |
| `zset-max-listpack-value`, `zset-max-ziplist-value` | `TypeLimits::zset.max_value` | File/CLI, live SET, GET, rewrite. Redis byte-unit grammar. |
| `hll-sparse-max-bytes` | Existing sparse-HLL promotion cutoff in PFADD/PFMERGE | File/CLI memory units, GET and rewrite; boot-only SET error. Default 3000 unchanged, explicit uint32 ceiling. |
| `aof-load-truncated` | Existing strict/repair `aof_read_plan` decision | File/CLI yes/no; GET and rewrite. Boot-only here, so SET explicitly errors. Default yes unchanged. |
| `unixsocketperm` | Filesystem mode of the existing Unix listener | File/CLI octal 0..777; GET reports octal; immutable SET, like Redis. Mode applied before listen in both modes. Default 0 preserves umask. |

The eight collection names share four existing controls with the original `hash/zset-max-compact-*` names. There is one stored value per control: SET through any spelling updates all GET spellings, overlapping GET patterns produce no duplicate names, and rewrite emits only the canonical `listpack` spelling. Existing compact spellings retain their previous bare-uint32 grammar, including leading zeroes. The new Redis names reject noncanonical entry counts (`01`, `+1`, units), accept memory units for value thresholds, and reject embedded NULs at runtime. Repeating the same new spelling in one SET is rejected; canonical plus historical alias is accepted in order, matching the reference probe.

**These collection bindings support 0..4294967295, not Redis's 0..9223372036854775807.** The native representation uses 32-bit counts/lengths, and no layout was widened. `CONFIG SET hash-max-listpack-entries 4294967296` succeeds on Redis and explicitly errors on TomoKV; no value is truncated or silently stored without effect. The same ceiling applies to byte thresholds. Zero selects immediate expanded representation; it does not introduce a new side table or observer allocation. Defaults (hash 512/64, zset 128/64) and already-expanded object behavior stay as before. This is a documented range gap, not full grammar/range parity.

`hll-sparse-max-bytes` uses the existing sparse mutation threshold shared by PFADD and PFMERGE. The value is latched before any workers or replay handlers start and never written while they run. `1kb` preserves the tested small sparse image; `0` makes a growing sparse mutation dense, including a PFMERGE whose source was imported as sparse. No observer or mutable per-owner state is added. Like the collection thresholds, it rejects values beyond UINT32_MAX, and unlike Redis it is boot-only for now.

`aof-load-truncated no` reuses an existing strict parser branch and read-only file open. For manifest recovery, earlier increments remain strict even when the flag is yes; only the last increment can have a torn tail discarded. Both manifest and legacy single-increment paths are tested. This flag does not permit arbitrary frame/checksum corruption and does not change native AOF/snapshot formats. Redis allows runtime SET of this option; TomoKV honestly reports it as boot-only.

Implementation is in the existing configuration parser/table and the existing HLL/AOF/Unix-listener files; no parallel feature implementation was added. The Unix mode is passed by both `main.cc` and `genthread.cc` to the same listener owner. [The focused test](tests/redisgap.py) verifies actual file permissions and actual collection promotion, rather than GET echoes alone.

## Full 155-name classification

This table is the exact set difference: the measured Redis 7.4.10 names minus the PRE startup-parser names. Each name appears once and has exactly one category. DELIBERATE names identify the intentionally absent subsystem. SHOULD EXIST means an operator control for an existing capability; the reason explicitly identifies any additional policy/storage work needed before a truthful binding can exist. NOT APPLICABLE means there is no matching mechanism and explains why a superficially similar knob would control something else. P1/P2/P3 order remaining work; aliases remain separate rows.

Code evidence for the decisions: [configuration and TypeLimits](src/core/config.h), [runtime configuration and FLUSH](src/cmd/t_server.cc), [set promotion](src/cmd/t_set.cc), [list representation](src/store/typeval.h), [LFU and rehashing](src/store/flatstore.h), [owner expiration](src/core/ex_loop.h), [HLL sparse promotion](src/cmd/hll.cc), [SORT collation](src/cmd/t_sort.cc), [TLS context](src/net/tls.cc), [bounded slowlog capture](src/cmd/slowlog.h), [snapshot writer/validator](src/snapshot/snapshot.cc), and [AOF replay](src/persist/aof.cc). Classification is an architectural judgment from these implementations, separate from the empirical name/response inventory.

| # | Redis 7.4.10 name | Reference value in the isolated run | Classification | Binding, reason, or remaining work |
|---:|---|---|---|---|
| 1 | `active-defrag-cycle-max` | `25` | NOT APPLICABLE | No relocating Redis object-graph defragmenter. Immutable replacement/QSBR and allocator reclamation are different mechanisms; these fragmentation/work-cycle thresholds have no existing consumer. |
| 2 | `active-defrag-cycle-min` | `1` | NOT APPLICABLE | No relocating Redis object-graph defragmenter. Immutable replacement/QSBR and allocator reclamation are different mechanisms; these fragmentation/work-cycle thresholds have no existing consumer. |
| 3 | `active-defrag-ignore-bytes` | `104857600` | NOT APPLICABLE | No relocating Redis object-graph defragmenter. Immutable replacement/QSBR and allocator reclamation are different mechanisms; these fragmentation/work-cycle thresholds have no existing consumer. |
| 4 | `active-defrag-max-scan-fields` | `1000` | NOT APPLICABLE | No relocating Redis object-graph defragmenter. Immutable replacement/QSBR and allocator reclamation are different mechanisms; these fragmentation/work-cycle thresholds have no existing consumer. |
| 5 | `active-defrag-threshold-lower` | `10` | NOT APPLICABLE | No relocating Redis object-graph defragmenter. Immutable replacement/QSBR and allocator reclamation are different mechanisms; these fragmentation/work-cycle thresholds have no existing consumer. |
| 6 | `active-defrag-threshold-upper` | `100` | NOT APPLICABLE | No relocating Redis object-graph defragmenter. Immutable replacement/QSBR and allocator reclamation are different mechanisms; these fragmentation/work-cycle thresholds have no existing consumer. |
| 7 | `active-expire-effort` | `1` | SHOULD EXIST | P2: Control the existing owner active-expiration scan budget (kActiveExpireChecks); needs a defined 1..10 effort policy and owner propagation, not a guessed alias to a timer. |
| 8 | `activedefrag` | `no` | NOT APPLICABLE | No relocating Redis object-graph defragmenter. Immutable replacement/QSBR and allocator reclamation are different mechanisms; these fragmentation/work-cycle thresholds have no existing consumer. |
| 9 | `activerehashing` | `yes` | NOT APPLICABLE | Redis toggles idle-time dictionary rehashing. FlatStore advances its own resize on owner operations; there is no separate Redis cron rehash job to enable/disable. |
| 10 | `always-show-logo` | `no` | NOT APPLICABLE | No Redis ASCII-logo renderer; the TomoKV boot/topology summary is not that logo. |
| 11 | `aof-load-truncated` | `yes` | SHOULD EXIST | IMPLEMENTED: existing aof_read_plan truncate_tail choice, for legacy recovery and only the final manifest increment; yes repairs with warning, no rejects without modifying the file. Boot-only here. |
| 12 | `aof-rewrite-cpulist` | `""` | NOT APPLICABLE | No forked rewrite/save child or Redis BIO thread pool. Persistence runs on the existing io/ex owners and their configured placement; a separate CPU mask would move unrelated work. |
| 13 | `aof-rewrite-incremental-fsync` | `yes` | SHOULD EXIST | P3: Control periodic syncs during the existing snapshot-based AOF rewrite. Current writer syncs at completion; byte-progress sync scheduling must be added. |
| 14 | `aof_rewrite_cpulist` | `""` | NOT APPLICABLE | No forked rewrite/save child or Redis BIO thread pool. Persistence runs on the existing io/ex owners and their configured placement; a separate CPU mask would move unrelated work. |
| 15 | `bgsave-cpulist` | `""` | NOT APPLICABLE | No forked rewrite/save child or Redis BIO thread pool. Persistence runs on the existing io/ex owners and their configured placement; a separate CPU mask would move unrelated work. |
| 16 | `bgsave_cpulist` | `""` | NOT APPLICABLE | No forked rewrite/save child or Redis BIO thread pool. Persistence runs on the existing io/ex owners and their configured placement; a separate CPU mask would move unrelated work. |
| 17 | `bind-source-addr` | `""` | DELIBERATE | Replication/Cluster/Sentinel outgoing connections; TomoKV has no outgoing peer-control links to bind. |
| 18 | `bio-cpulist` | `""` | NOT APPLICABLE | No forked rewrite/save child or Redis BIO thread pool. Persistence runs on the existing io/ex owners and their configured placement; a separate CPU mask would move unrelated work. |
| 19 | `bio_cpulist` | `""` | NOT APPLICABLE | No forked rewrite/save child or Redis BIO thread pool. Persistence runs on the existing io/ex owners and their configured placement; a separate CPU mask would move unrelated work. |
| 20 | `busy-reply-threshold` | `5000` | NOT APPLICABLE | Redis wall-clock BUSY threshold keeps a script running while servicing other clients. TomoKV aborts at an instruction budget inside an owner task; mapping milliseconds to instructions would be false semantics. |
| 21 | `client-query-buffer-limit` | `1073741824` | SHOULD EXIST | P1: Bound total receive/query-buffer memory independently of proto-max-bulk-len; current receive cap derives from maximum frame size. Needs owner-safe limit publication and protocol tests. |
| 22 | `cluster-allow-pubsubshard-when-down` | `yes` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 23 | `cluster-allow-reads-when-down` | `no` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 24 | `cluster-allow-replica-migration` | `yes` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 25 | `cluster-announce-bus-port` | `0` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 26 | `cluster-announce-hostname` | `""` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 27 | `cluster-announce-human-nodename` | `""` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 28 | `cluster-announce-ip` | `""` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 29 | `cluster-announce-port` | `0` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 30 | `cluster-announce-tls-port` | `0` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 31 | `cluster-config-file` | `nodes.conf` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 32 | `cluster-enabled` | `no` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 33 | `cluster-link-sendbuf-limit` | `0` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 34 | `cluster-migration-barrier` | `1` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 35 | `cluster-node-timeout` | `15000` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 36 | `cluster-port` | `0` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 37 | `cluster-preferred-endpoint-type` | `ip` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 38 | `cluster-replica-no-failover` | `no` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 39 | `cluster-replica-validity-factor` | `10` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 40 | `cluster-require-full-coverage` | `yes` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 41 | `cluster-slave-no-failover` | `no` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 42 | `cluster-slave-validity-factor` | `10` | DELIBERATE | Redis Cluster: node membership, slot routing, failover, migration, or cluster-bus policy; TomoKV is single-node. |
| 43 | `crash-log-enabled` | `yes` | NOT APPLICABLE | No Redis fatal-signal crash reporter or destructive post-crash RAM test. Ordinary boot errors and SIGINT/SIGTERM draining are different paths. |
| 44 | `crash-memcheck-enabled` | `yes` | NOT APPLICABLE | No Redis fatal-signal crash reporter or destructive post-crash RAM test. Ordinary boot errors and SIGINT/SIGTERM draining are different paths. |
| 45 | `daemonize` | `no` | SHOULD EXIST | P3: Process startup/detachment policy. Current server stays in the foreground; honoring yes needs a daemon/PID-file lifecycle before worker creation, not acceptance of a no-op. |
| 46 | `disable-thp` | `yes` | SHOULD EXIST | P2: Process/allocator transparent-huge-page policy for existing memory allocations; needs explicit boot initialization, platform/error handling and allocator interaction checks. |
| 47 | `dynamic-hz` | `yes` | NOT APPLICABLE | No single Redis serverCron clock. io/ex owners have separate pass-driven maintenance, QSBR and timers; one frequency cannot honestly control all of them. |
| 48 | `enable-module-command` | `no` | DELIBERATE | Modules: no loadable module API or MODULE command to enable. |
| 49 | `enable-protected-configs` | `no` | SHOULD EXIST | P2: Control access to protected persistence paths (dir/dbfilename) for local/all clients. Current paths are always boot-latched; live path rebinding and the access check need implementation. |
| 50 | `hash-max-listpack-entries` | `512` | SHOULD EXIST | IMPLEMENTED: hash compact-to-expanded entry threshold; shares the existing max-compact-entries control. Redis decimal grammar, explicit uint32 ceiling. |
| 51 | `hash-max-listpack-value` | `64` | SHOULD EXIST | IMPLEMENTED: hash compact-to-expanded maximum element-byte threshold; shares max-compact-value. Redis memory-unit grammar, explicit uint32 ceiling. |
| 52 | `hash-max-ziplist-entries` | `512` | SHOULD EXIST | IMPLEMENTED: hash compact-to-expanded entry threshold; shares the existing max-compact-entries control. Redis decimal grammar, explicit uint32 ceiling. |
| 53 | `hash-max-ziplist-value` | `64` | SHOULD EXIST | IMPLEMENTED: hash compact-to-expanded maximum element-byte threshold; shares max-compact-value. Redis memory-unit grammar, explicit uint32 ceiling. |
| 54 | `hide-user-data-from-log` | `no` | SHOULD EXIST | P1: Control redaction of existing diagnostic/slow-command argument capture; requires a consistent redaction policy across logging sinks, not just hiding a config value. |
| 55 | `hll-sparse-max-bytes` | `3000` | SHOULD EXIST | IMPLEMENTED: existing sparse-HLL promotion cutoff, shared by PFADD and PFMERGE helpers; boot-latched before worker creation. Redis memory units, explicit uint32 ceiling; no runtime mutation or owner-layout change. |
| 56 | `hz` | `10` | NOT APPLICABLE | No single Redis serverCron clock. io/ex owners have separate pass-driven maintenance, QSBR and timers; one frequency cannot honestly control all of them. |
| 57 | `ignore-warnings` | `""` | NOT APPLICABLE | Redis-specific startup warning overrides (for its own environment checks); no matching warning registry or checks here. |
| 58 | `io-threads` | `1` | SHOULD EXIST | P2: Bind split-mode io owner count. Needs documented derivation of ex count from allowed CPUs and conflicts with ratio/place/1s; Redis total IO-thread semantics cannot be guessed. |
| 59 | `io-threads-do-reads` | `no` | NOT APPLICABLE | Parsing is always on the networking owner. Disabling it would require a new parse/execute boundary, not an alias for fused/split modes. |
| 60 | `jemalloc-bg-thread` | `yes` | SHOULD EXIST | P2: Control jemalloc background purging for the existing allocator; needs mallctl initialization/live failure handling and honest rejection on JE=0 builds. |
| 61 | `latency-tracking` | `yes` | SHOULD EXIST | P3: Select per-command latency distribution tracking alongside existing command timing. SLOWLOG/latency event monitoring is not a histogram collector; per-command distribution storage still needs building. |
| 62 | `latency-tracking-info-percentiles` | `50 99 99.9` | SHOULD EXIST | P3: Choose INFO per-command latency percentiles once latency distributions exist; current LATENCY event maxima cannot supply percentiles. |
| 63 | `lazyfree-lazy-eviction` | `no` | SHOULD EXIST | P3: Select deferred destructor scheduling for existing eviction/expiration/deletion/flush paths. QSBR already delays unsafe frees, but is not Redis optional BIO lazyfree. Any new queue must run only after reader quiescence and preserve owner/migration rules. |
| 64 | `lazyfree-lazy-expire` | `no` | SHOULD EXIST | P3: Select deferred destructor scheduling for existing eviction/expiration/deletion/flush paths. QSBR already delays unsafe frees, but is not Redis optional BIO lazyfree. Any new queue must run only after reader quiescence and preserve owner/migration rules. |
| 65 | `lazyfree-lazy-server-del` | `no` | SHOULD EXIST | P3: Select deferred destructor scheduling for existing eviction/expiration/deletion/flush paths. QSBR already delays unsafe frees, but is not Redis optional BIO lazyfree. Any new queue must run only after reader quiescence and preserve owner/migration rules. |
| 66 | `lazyfree-lazy-user-del` | `no` | SHOULD EXIST | P3: Select deferred destructor scheduling for existing eviction/expiration/deletion/flush paths. QSBR already delays unsafe frees, but is not Redis optional BIO lazyfree. Any new queue must run only after reader quiescence and preserve owner/migration rules. |
| 67 | `lazyfree-lazy-user-flush` | `no` | SHOULD EXIST | P3: Select deferred destructor scheduling for existing eviction/expiration/deletion/flush paths. QSBR already delays unsafe frees, but is not Redis optional BIO lazyfree. Any new queue must run only after reader quiescence and preserve owner/migration rules. |
| 68 | `lfu-decay-time` | `1` | SHOULD EXIST | P3: Age the advertised LFU policy. Current five-bit frequency has no Redis last-decay timestamp: this is a policy gap requiring metadata/decay work, not a binding to LRU clock granularity. |
| 69 | `lfu-log-factor` | `10` | SHOULD EXIST | P2: Control the existing logarithmic LFU increment denominator (hardcoded factor 10) in both ordinary and read-local metadata paths; requires coherent owner-local config. |
| 70 | `list-compress-depth` | `0` | NOT APPLICABLE | Expanded lists are deques, with no independently compressed quicklist nodes or uncompressed-end-depth setting. |
| 71 | `list-max-listpack-size` | `-2` | SHOULD EXIST | P3: Control list packing by signed Redis entry/byte-budget grammar. Existing small-list threshold is whole-list payload, while expanded lists are deques; honoring per-node budgets needs representation work. |
| 72 | `list-max-ziplist-size` | `-2` | SHOULD EXIST | P3: Control list packing by signed Redis entry/byte-budget grammar. Existing small-list threshold is whole-list payload, while expanded lists are deques; honoring per-node budgets needs representation work. |
| 73 | `locale-collate` | `""` | SHOULD EXIST | P2: Control SORT ALPHA strcoll collation. Needs validated locale setup and safe semantics for live changes across concurrent sort owners; a process-global setlocale during sorting is unsafe. |
| 74 | `logfile` | `""` | SHOULD EXIST | P1: Choose the destination of existing startup/runtime diagnostics; needs a shared logging sink and reopen/error behavior. |
| 75 | `loglevel` | `notice` | SHOULD EXIST | P1: Filter existing diagnostics by Redis severity names; current scattered printf/fprintf calls have no severity-aware logger. |
| 76 | `lua-time-limit` | `5000` | NOT APPLICABLE | Redis wall-clock BUSY threshold keeps a script running while servicing other clients. TomoKV aborts at an instruction budget inside an owner task; mapping milliseconds to instructions would be false semantics. |
| 77 | `masterauth` | `""` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 78 | `masteruser` | `""` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 79 | `max-new-connections-per-cycle` | `10` | NOT APPLICABLE | Redis accept/handshake batch limits have no matching cycle in the io_uring completion-driven listener and asynchronous TLS state machine; admission fairness would need a scheduler policy. |
| 80 | `max-new-tls-connections-per-cycle` | `1` | NOT APPLICABLE | Redis accept/handshake batch limits have no matching cycle in the io_uring completion-driven listener and asynchronous TLS state machine; admission fairness would need a scheduler policy. |
| 81 | `maxmemory-clients` | `0` | SHOULD EXIST | P1: Bound aggregate existing client input/output/tracking memory; requires complete accounting and a client eviction/admission policy beyond per-client output limits. |
| 82 | `maxmemory-eviction-tenacity` | `10` | SHOULD EXIST | P2: Control work spent in existing eviction attempts before yielding/failing; needs an effort policy integrated with owner scheduling and memory-pressure behavior. |
| 83 | `min-replicas-max-lag` | `10` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 84 | `min-replicas-to-write` | `0` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 85 | `min-slaves-max-lag` | `10` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 86 | `min-slaves-to-write` | `0` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 87 | `no-appendfsync-on-rewrite` | `no` | SHOULD EXIST | P3: Select whether the existing AOF writer postpones append fsync during snapshot rewrite; needs coordinated durable-frontier/ack behavior, especially appendfsync always. |
| 88 | `oom-score-adj` | `no` | SHOULD EXIST | P3: Select process OOM-killer adjustment policy. Requires boot/platform handling; Redis child/replica score classes do not map to io/ex threads. |
| 89 | `oom-score-adj-values` | `0 200 800` | NOT APPLICABLE | Redis three-slot normal/replica/background-child score vector has no matching role classes. io/ex are threads of one process; process OOM policy is a separate remaining item. |
| 90 | `pidfile` | `""` | SHOULD EXIST | P3: Publish/remove the existing process PID at a configured path; needs ownership, boot-failure cleanup and daemon/supervisor lifecycle integration. |
| 91 | `proc-title-template` | `{title} {listen-addr} {server-mode}` | SHOULD EXIST | P3: Control process identification visible to operators. Thread labels already exist, but process-title storage and Redis template expansion still need implementation. |
| 92 | `propagation-error-behavior` | `ignore` | SHOULD EXIST | P3: Choose AOF replay error policy for existing framed records (replication half is absent). Current recovery is strict; safe frame/group recovery boundaries must be specified before adding ignore/panic behavior. |
| 93 | `rdb-del-sync-files` | `no` | DELIBERATE | Disk-based replication synchronization files; local TomoKV snapshots are not disposable replication transfer files. |
| 94 | `rdb-save-incremental-fsync` | `yes` | SHOULD EXIST | P3: Control incremental sync during the existing native snapshot writer. The operational purpose applies despite a different file format; periodic byte-progress syncing is not currently scheduled. |
| 95 | `rdbchecksum` | `yes` | NOT APPLICABLE | No RDB writer. TomoKV snapshot frame/header/footer checksums are part of its own validated format; this Redis RDB checksum toggle has no existing format binding. |
| 96 | `rdbcompression` | `yes` | NOT APPLICABLE | No RDB/LZF encoder. The native snapshot format has no compression codec to toggle; adding native compression would be a format feature. |
| 97 | `repl-backlog-size` | `1048576` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 98 | `repl-backlog-ttl` | `3600` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 99 | `repl-disable-tcp-nodelay` | `no` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 100 | `repl-diskless-load` | `disabled` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 101 | `repl-diskless-sync` | `yes` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 102 | `repl-diskless-sync-delay` | `5` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 103 | `repl-diskless-sync-max-replicas` | `0` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 104 | `repl-ping-replica-period` | `10` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 105 | `repl-ping-slave-period` | `10` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 106 | `repl-timeout` | `60` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 107 | `replica-announce-ip` | `""` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 108 | `replica-announce-port` | `0` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 109 | `replica-announced` | `yes` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 110 | `replica-ignore-disk-write-errors` | `no` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 111 | `replica-ignore-maxmemory` | `yes` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 112 | `replica-lazy-flush` | `no` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 113 | `replica-priority` | `100` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 114 | `replica-read-only` | `yes` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 115 | `replica-serve-stale-data` | `yes` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 116 | `replicaof` | `""` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 117 | `sanitize-dump-payload` | `no` | NOT APPLICABLE | RESTORE/load perform mandatory native payload validation. No separate optional Redis deep-sanitization pass exists; accepting no must not disable structural safety checks. |
| 118 | `server-cpulist` | `""` | SHOULD EXIST | P2: Set the initial allowed CPU set used by existing topology/placement. Needs CPU-list validation and documented precedence with external taskset and --place; must never widen allowed CPUs. |
| 119 | `server_cpulist` | `""` | SHOULD EXIST | P2: Set the initial allowed CPU set used by existing topology/placement. Needs CPU-list validation and documented precedence with external taskset and --place; must never widen allowed CPUs. |
| 120 | `set-max-intset-entries` | `512` | SHOULD EXIST | P2: Control integer-set promotion separately (Redis default 512). Integer and generic compact sets currently share one 128/64 limit; add distinct owner state before exposing this. |
| 121 | `set-max-listpack-entries` | `128` | SHOULD EXIST | P2: Control generic-string set packing independently of integer sets. Current shared limits also affect integer sets, so direct aliases would silently tune the wrong representation. |
| 122 | `set-max-listpack-value` | `64` | SHOULD EXIST | P2: Control generic-string set packing independently of integer sets. Current shared limits also affect integer sets, so direct aliases would silently tune the wrong representation. |
| 123 | `set-proc-title` | `yes` | SHOULD EXIST | P3: Control process identification visible to operators. Thread labels already exist, but process-title storage and Redis template expansion still need implementation. |
| 124 | `shutdown-on-sigint` | `default` | SHOULD EXIST | P3: Choose save/nosave/now/force policy for existing signal shutdown. Current signal path drains owners; Redis option combinations need explicit snapshot/durability orchestration. |
| 125 | `shutdown-on-sigterm` | `default` | SHOULD EXIST | P3: Choose save/nosave/now/force policy for existing signal shutdown. Current signal path drains owners; Redis option combinations need explicit snapshot/durability orchestration. |
| 126 | `shutdown-timeout` | `10` | DELIBERATE | Replication: Redis grace period for replicas to catch up at shutdown, not a generic deadline for draining local work. |
| 127 | `slave-announce-ip` | `""` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 128 | `slave-announce-port` | `0` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 129 | `slave-ignore-maxmemory` | `yes` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 130 | `slave-lazy-flush` | `no` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 131 | `slave-priority` | `100` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 132 | `slave-read-only` | `yes` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 133 | `slave-serve-stale-data` | `yes` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 134 | `slaveof` | `""` | DELIBERATE | Replication (including legacy master/slave aliases): no upstream, replica links, replication backlog, or replica failover state. |
| 135 | `socket-mark-id` | `0` | SHOULD EXIST | P3: Apply an OS routing/filter mark to existing listeners. Needs boot socket-option setup, privilege errors and platform-specific behavior; no marking path currently exists. |
| 136 | `stop-writes-on-bgsave-error` | `yes` | SHOULD EXIST | P1: Gate writes using existing periodic snapshot failure state until a successful save. Requires admission changes across ordinary, script and multi-key paths; no silent alias to AOF error handling. |
| 137 | `supervised` | `no` | SHOULD EXIST | P3: Integrate the foreground process with systemd/upstart readiness notification. Needs a readiness/stop lifecycle after every owner/listener is ready. |
| 138 | `syslog-enabled` | `no` | SHOULD EXIST | P3: Route existing diagnostics to syslog with chosen facility/identity; requires a logging backend (currently stdout/stderr), not stored-but-unused strings. |
| 139 | `syslog-facility` | `local0` | SHOULD EXIST | P3: Route existing diagnostics to syslog with chosen facility/identity; requires a logging backend (currently stdout/stderr), not stored-but-unused strings. |
| 140 | `syslog-ident` | `redis` | SHOULD EXIST | P3: Route existing diagnostics to syslog with chosen facility/identity; requires a logging backend (currently stdout/stderr), not stored-but-unused strings. |
| 141 | `tls-client-cert-file` | `""` | DELIBERATE | Replication/Cluster TLS client identity for outgoing peer connections; incoming clients use the existing server TLS certificate. |
| 142 | `tls-client-key-file` | `""` | DELIBERATE | Replication/Cluster TLS client identity for outgoing peer connections; incoming clients use the existing server TLS certificate. |
| 143 | `tls-client-key-file-pass` | `""` | DELIBERATE | Replication/Cluster TLS client identity for outgoing peer connections; incoming clients use the existing server TLS certificate. |
| 144 | `tls-cluster` | `no` | DELIBERATE | Redis Cluster TLS bus; the cluster bus is absent. |
| 145 | `tls-dh-params-file` | `""` | SHOULD EXIST | P2: Select custom DH parameters for the existing TLS server context. Current OpenSSL path always chooses automatic parameters; an explicit file decoder/validation path is required (Redis also supports this on OpenSSL 3). |
| 146 | `tls-key-file-pass` | `""` | SHOULD EXIST | P1: Supply a passphrase to the existing TLS private-key loader; needs non-interactive password callback, secret handling, startup error tests and config reporting/redaction. |
| 147 | `tls-replication` | `no` | DELIBERATE | Replication TLS transport; replica connections are absent. |
| 148 | `tls-session-cache-size` | `20480` | SHOULD EXIST | P2: Control resumption for the existing SSL_CTX. Current code disables session cache/tickets; needs explicit session-id/ticket lifecycle, bounded cache setup and resumption tests before exposing these knobs. |
| 149 | `tls-session-cache-timeout` | `300` | SHOULD EXIST | P2: Control resumption for the existing SSL_CTX. Current code disables session cache/tickets; needs explicit session-id/ticket lifecycle, bounded cache setup and resumption tests before exposing these knobs. |
| 150 | `tls-session-caching` | `yes` | SHOULD EXIST | P2: Control resumption for the existing SSL_CTX. Current code disables session cache/tickets; needs explicit session-id/ticket lifecycle, bounded cache setup and resumption tests before exposing these knobs. |
| 151 | `unixsocketperm` | `0` | SHOULD EXIST | IMPLEMENTED: octal filesystem mode on the existing AF_UNIX listener, applied before listen in both thread modes; 0 preserves umask. Boot-only, matching Redis. |
| 152 | `zset-max-listpack-entries` | `128` | SHOULD EXIST | IMPLEMENTED: zset compact-to-expanded entry threshold; shares the existing max-compact-entries control. Redis decimal grammar, explicit uint32 ceiling. |
| 153 | `zset-max-listpack-value` | `64` | SHOULD EXIST | IMPLEMENTED: zset compact-to-expanded maximum element-byte threshold; shares max-compact-value. Redis memory-unit grammar, explicit uint32 ceiling. |
| 154 | `zset-max-ziplist-entries` | `128` | SHOULD EXIST | IMPLEMENTED: zset compact-to-expanded entry threshold; shares the existing max-compact-entries control. Redis decimal grammar, explicit uint32 ceiling. |
| 155 | `zset-max-ziplist-value` | `64` | SHOULD EXIST | IMPLEMENTED: zset compact-to-expanded maximum element-byte threshold; shares max-compact-value. Redis memory-unit grammar, explicit uint32 ceiling. |

The classifications total **64 DELIBERATE + 61 SHOULD EXIST + 30 NOT APPLICABLE = 155**. Eleven SHOULD EXIST rows are implemented, leaving **64 + 50 + 30 = 144** unbound names. The final review classifies custom TLS DH parameters as SHOULD EXIST: automatic OpenSSL 3 DH selection is the current default, but it does not make custom parameters inherently inapplicable.

## Redis 8.8.1 delta

The second catalogued reference reports **218** names: it adds the following **17** and removes `io-threads-do-reads`. None of these additions was accepted by the PRE parser. Thus the corresponding missing-name count is **171 PRE / 160 POST**; the union of the two reference missing-name sets has 172 names. Redis 8.8.1's additional data-type and stream features are called out separately, without retroactively declaring them part of the project's intentionally absent 7.4 subsystems.

| Additional 8.8.1 name | Reference value | Classification | Reason / remaining work |
|---|---|---|---|
| `aof-load-corrupt-tail-max-size` | `0` | SHOULD EXIST | Native AOF tail recovery already exists; allowing bounded corrupt (not merely truncated) tail repair needs frame/group-boundary rules and corruption fixtures. |
| `array-slice-size` | `4096` | NOT APPLICABLE | No Redis 8.8 ARRAY value representation or array slices; adding the data type is prerequisite work, not a config binding. |
| `array-sparse-kmax` | `10` | NOT APPLICABLE | No ARRAY sparse representation or sparse/dense conversion thresholds. This is an additional data-type gap beyond the 7.4 target. |
| `array-sparse-kmin` | `5` | NOT APPLICABLE | No ARRAY sparse representation or sparse/dense conversion thresholds. This is an additional data-type gap beyond the 7.4 target. |
| `cluster-compatibility-sample-ratio` | `0` | DELIBERATE | Redis Cluster command/slot compatibility sampling; no Cluster subsystem. |
| `cluster-slot-migration-handoff-max-lag-bytes` | `1048576` | DELIBERATE | Redis Cluster slot migration replication/handoff; local shard-owner movement is a different mechanism. |
| `cluster-slot-migration-write-pause-timeout` | `10000` | DELIBERATE | Redis Cluster slot migration write pausing; no inter-node slot handoff. |
| `cluster-slot-stats-enabled` | `no` | DELIBERATE | Redis Cluster slot statistics; TomoKV local shard statistics are not Redis Cluster slots. |
| `key-memory-histograms` | `no` | SHOULD EXIST | Existing key memory accounting could feed distributions; incremental per-owner histograms and reporting still need implementation. |
| `lookahead` | `16` | NOT APPLICABLE | Redis pipeline dictionary-prefetch lookahead has no equivalent control over TomoKV owner batching/local-read scheduling; not an alias for the ROB window or a reason to revive closed scheduling designs. |
| `replica-full-sync-buffer-limit` | `0` | DELIBERATE | Replication full synchronization buffers; no replicas. |
| `slowlog-entry-max-argc` | `32` | SHOULD EXIST | Existing argument capture uses a fixed 32-argument array. Exposing the full Redis range requires revisiting bounded capture storage, not just changing the loop bound. |
| `slowlog-entry-max-string-len` | `128` | SHOULD EXIST | Existing capture has a fixed 128-byte per-argument budget. Larger configurable limits need safe capture-storage sizing and truncation tests. |
| `stream-idmp-duration` | `100` | SHOULD EXIST | Existing stream ingestion could offer idempotent production, but producer/deduplication history and IDMP semantics are absent; build that behavior before exposing retention time. |
| `stream-idmp-maxsize` | `100` | SHOULD EXIST | Bound stream producer deduplication history once IDMP exists; current stream-node limits govern packing, not duplicate suppression. |
| `tls-auth-clients-user` | `off` | SHOULD EXIST | Existing TLS client authentication and ACL users need an explicit certificate-to-user binding with authorization tests. |
| `vset-force-single-threaded-execution` | `no` | NOT APPLICABLE | No vector-set value/search executor. Adding vector sets is prerequisite work, not a switch for TomoKV io/ex threading. |

## Prioritized remaining work

1. **P1 — controls whose absence defeats an operator policy:** implement severity/destination logging, diagnostic redaction, independent query-buffer and aggregate client-memory limits, write admission after snapshot failure, and non-interactive TLS private-key passphrases. These need observable behavior and failure tests, not acceptance of names.
2. **P2 — existing primitive with additional state or integration:** LFU increment factor, expiration/eviction effort, separate integer/generic set limits, safe SORT collation, io/CPU-placement grammar, allocator background-purge/THP setup, TLS resumption/custom DH, and protected-path rebinding. Respect current footprints, owner-local publication, and allowed CPU masks. TLS settings need actual handshake/resumption tests; allocator settings need a real JE=0 error path.
3. **P3 — mechanisms that must be built or substantially extended:** list node packing, LFU decay metadata, per-command latency distributions, optional lazyfree after QSBR, incremental snapshot/rewrite fsync, rewrite-time fsync suppression, replay error policies, signal-save choices, daemon/supervisor/PID/title/syslog support and socket/process OS policies. Accepting their defaults without implementation would recreate the silent-ignore problem.
4. **Compatibility depth beyond missing names:** retain an explicit range error for the 32-bit collection thresholds until a representation-compatible design exists; consider live setting of the boot-only AOF recovery and HLL cutoff policies with safe publication and clearly defined rewrite/restart semantics. Existing `bind` still lacks Redis multiple-address grammar. `include` and `rename-command` are Redis file directives absent from `CONFIG GET *`, so the 202-name inventory does not cover them; config includes and command renaming need separate parser/dispatch work. `loadmodule` and Sentinel-only directives belong to the deliberately absent subsystems. `databases` is already bound but accepts only 1. Existing native persistence formats and numerous boot-only SET restrictions remain separate semantic limitations.
5. **8.8 additions:** treat stream IDMP, memory histograms, configurable slowlog capture, certificate-to-ACL mapping, and bounded corrupt-tail repair as additional behavior work. Array/vector-set support would be new data types, outside this binding-only change.

## Validation and limits of the result

Commands run for the final implementation (all pinned; no gate rows were added or retired):

```sh
taskset -c 68-79 make -j4 all build/config-parser-test
taskset -c 68-79 build/config-parser-test
taskset -c 68-79 python3 tests/redisgap.py --binary build/tomokv --root build/redisgap-tests-hll
```

The full build completed without compiler warnings. The existing parser test exited 0. The existing `tests/knobs.py 127.0.0.1 8127 uring 0` check also passed on the pinned 6-io/2-ex, 16-shard server with its required `--enable-debug-command yes` (`configuration reduction and actual geometry verified`). Focused suite output:

```text
PASS 2s aliases, grammar, actual promotion, HLL cutoff, unknowns, Unix permissions, rewrite/restart
PASS 2s strict/permissive AOF recovery, manifest and legacy paths
PASS 1s aliases, grammar, actual promotion, HLL cutoff, unknowns, Unix permissions, rewrite/restart
PASS 1s strict/permissive AOF recovery, manifest and legacy paths
PASS redisgap configuration checks (no gate rows added)
```

The focused checks cover: file/CLI precedence; each Redis/legacy collection spelling; values at and over entry/element-size promotion thresholds; zero thresholds on fresh objects across many keys; invalid and overflow values; mixed SET failure with no partial update; duplicate GET pattern suppression; RESP2/RESP3 unknown replies; immutable listener/recovery settings; rewrite and restart; sparse/dense HLL cutoff in PFADD and PFMERGE (including a sparse imported source); filesystem mode 0600 and socket cleanup; strict truncated-tail refusal with byte-for-byte unchanged input; permissive recovery preserving the acknowledged key; both manifest and legacy AOF paths. The test asserts that a rewrite really produced a manifest before claiming that path was exercised.

Running the same regression against `build/redisgap/tomokv-pre` exits 1 immediately, with `unknown argument '--hash-max-ziplist-entries' (see --help)`. This is the retained negative control. During development the test also caught the fused startup call site initially omitting Unix permissions; that call is now mandatory at both startup sites. Early harness failures due to the native `.incr.tomo` filename and asynchronous kernel listener release were corrected; failed arms were not counted as passes.

`tests/gate.sh` and `EXPECT_QUICK` / `EXPECT_FULL` are untouched: expected row counts do not change. This is focused correctness verification, not full-gate certification or a performance result. No throughput, instruction-count, or IPC claim is made. Native key/value algorithms and owner transfer logic are unchanged; the existing all-shard CONFIG barrier applies the four thresholds. The full main-command gate remains for the maintainer.
