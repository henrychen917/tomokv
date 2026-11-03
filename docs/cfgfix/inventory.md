# Redis 7.4.10 configuration inventory

Source: `/home/user/Projects/redis/src/config.c`, `standardConfig static_configs[]`. Every canonical row and alias is included, including conditional and hidden rows. Since is the first source spelling in history through PRE (parser or CONFIG registration); `cfgfix` means newly introduced here. Replies are explicit-name GET receipts from the gate job. Overridden defaults are compared from Config initializers and Redis initServerConfig/standardConfig: port 6379, maxclients 10000, save 3600/1 300/100 60/10000, appendonly no, protected-mode yes, debug no, dir current directory; bind differs (127.0.0.1 versus * -::*). A documented UNFIXED row is an outstanding requirement, not a claim of Redis parity.

| Redis name | Present / since | Mutable Redis / Tomo | Default equal | CONFIG GET equal | Hidden / protected equal | Difference or reason |
|---|---|---|---|---|---|---|
| `rdbchecksum` | no | no / — | no | no | no (Redis 0/0) | Native snapshot/AOF format and writer differ from Redis RDB/RESP persistence; this Redis control is not implemented. |
| `daemonize` | yes / cfgfix | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `io-threads-do-reads` | no | no / — | no | no | no (Redis 0/0) | TomoKV assigns shard owners and IO roles from inherited affinity and ratio/place; no Redis BIO/fork worker pools. |
| `always-show-logo` | no | no / — | no | no | no (Redis 0/0) | UNFIXED: Startup has a TomoKV banner, with no Redis-style conditional logo renderer. |
| `protected-mode` | yes / 1482e32774 | yes / yes | yes (source defaults) | yes | yes (Redis 0/0) | Captured value includes the gate harness override; boot default comparison needs the source defaults. |
| `rdbcompression` | no | yes / — | no | no | no (Redis 0/0) | Native snapshot/AOF format and writer differ from Redis RDB/RESP persistence; this Redis control is not implemented. |
| `rdb-del-sync-files` | no | yes / — | no | no | no (Redis 0/0) | Native snapshot/AOF format and writer differ from Redis RDB/RESP persistence; this Redis control is not implemented. |
| `activerehashing` | no | yes / — | no | no | no (Redis 0/0) | FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller. |
| `stop-writes-on-bgsave-error` | no | yes / — | no | no | no (Redis 0/0) | Native snapshot/AOF format and writer differ from Redis RDB/RESP persistence; this Redis control is not implemented. |
| `set-proc-title` | no | no / — | no | no | no (Redis 0/0) | UNFIXED: Worker names and the original argv remain intact; no process-title storage or renderer exists. |
| `dynamic-hz` | yes / 5a16250171 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `lazyfree-lazy-eviction` | no | yes / — | no | no | no (Redis 0/0) | FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller. |
| `lazyfree-lazy-expire` | no | yes / — | no | no | no (Redis 0/0) | FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller. |
| `lazyfree-lazy-server-del` | no | yes / — | no | no | no (Redis 0/0) | FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller. |
| `lazyfree-lazy-user-del` | no | yes / — | no | no | no (Redis 0/0) | FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller. |
| `lazyfree-lazy-user-flush` | no | yes / — | no | no | no (Redis 0/0) | FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller. |
| `repl-disable-tcp-nodelay` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `repl-diskless-sync` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `aof-rewrite-incremental-fsync` | no | yes / — | no | no | no (Redis 0/0) | Native snapshot/AOF format and writer differ from Redis RDB/RESP persistence; this Redis control is not implemented. |
| `no-appendfsync-on-rewrite` | no | yes / — | no | no | no (Redis 0/0) | Native snapshot/AOF format and writer differ from Redis RDB/RESP persistence; this Redis control is not implemented. |
| `cluster-require-full-coverage` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `rdb-save-incremental-fsync` | no | yes / — | no | no | no (Redis 0/0) | Native snapshot/AOF format and writer differ from Redis RDB/RESP persistence; this Redis control is not implemented. |
| `aof-load-truncated` | yes / 0939cecc57 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `aof-use-rdb-preamble` | yes / b9a5e89480 | yes / yes | yes | yes | yes (Redis 0/0) | Native AOF bases are TomoKV snapshots: yes is accepted, no is rejected explicitly. This format boundary now blocks stream-cgroups after appendonly setup succeeds. |
| `aof-timestamp-enabled` | yes / b9a5e89480 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `cluster-replica-no-failover` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `cluster-slave-no-failover` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `replica-lazy-flush` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `slave-lazy-flush` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `replica-serve-stale-data` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `slave-serve-stale-data` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `replica-read-only` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `slave-read-only` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `replica-ignore-maxmemory` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `slave-ignore-maxmemory` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `jemalloc-bg-thread` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: jemalloc policy is inherited from the allocator; its mallctl background-thread switch is not exposed. |
| `activedefrag` | no | yes / — | no | no | no (Redis 0/0) | FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller. |
| `syslog-enabled` | yes / cfgfix | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `cluster-enabled` | no | no / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `appendonly` | yes / f94726446d | yes / yes | yes (source defaults) | yes | yes (Redis 0/0) | Runtime ON starts an unpublished increment and initial rewrite; OFF drains, fsyncs and closes. Outstanding: switches refuse active atomic/snapshot/topology work instead of Redis cancellation/scheduling. |
| `cluster-allow-reads-when-down` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `cluster-allow-pubsubshard-when-down` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `crash-log-enabled` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: Native assert-map/core-dump diagnostics have no Redis crash-report signal handler to toggle. |
| `crash-memcheck-enabled` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: No crash-time memory checker exists for concurrently owned/QSBR-retired stores. |
| `use-exit-on-panic` | no | yes / — | no | no | no (Redis 1/0) | UNFIXED: Native assertion failures abort; no configurable panic exit policy exists. |
| `disable-thp` | no | no / — | no | no | no (Redis 0/0) | UNFIXED: Boot does not expose PR_SET_THP_DISABLE; this process setting still requires implementation. |
| `cluster-allow-replica-migration` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `replica-announced` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `latency-tracking` | yes / bffd6e6b5e | yes / yes | no | no | yes (Redis 0/0) | Default remains no (Redis yes): optional histogram observers are off in the measured baseline; changing this default requires a separately measured cost decision. |
| `aof-disable-auto-gc` | no | yes / — | no | no | no (Redis 1/0) | Native snapshot/AOF format and writer differ from Redis RDB/RESP persistence; this Redis control is not implemented. |
| `replica-ignore-disk-write-errors` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `hide-user-data-from-log` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: Existing diagnostics lack the data-classification metadata needed for a complete redaction policy. |
| `lua-enable-deprecated-api` | no | no / — | no | no | no (Redis 1/0) | UNFIXED: Lua API registration does not expose Redis deprecated-API gating. |
| `aclfile` | yes / e14d593062 | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `unixsocket` | yes / d82abe6cb9 | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `pidfile` | yes / cfgfix | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `replica-announce-ip` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `slave-announce-ip` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `masteruser` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `cluster-announce-ip` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `cluster-config-file` | no | no / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `cluster-announce-hostname` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `cluster-announce-human-nodename` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `syslog-ident` | yes / cfgfix | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `dbfilename` | yes / d82abe6cb9 | yes / no | no | no | yes (Redis 0/1) | Native snapshot files use dump.tomo rather than Redis dump.rdb. UNFIXED: the path is retained at boot and protected-config policy is not implemented. |
| `appendfilename` | yes / b9a5e89480 | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `appenddirname` | yes / b9a5e89480 | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `server-cpulist` | no | no / — | no | no | no (Redis 0/0) | TomoKV assigns shard owners and IO roles from inherited affinity and ratio/place; no Redis BIO/fork worker pools. |
| `server_cpulist` | no | no / — | no | no | no (Redis 0/0) | TomoKV assigns shard owners and IO roles from inherited affinity and ratio/place; no Redis BIO/fork worker pools. |
| `bio-cpulist` | no | no / — | no | no | no (Redis 0/0) | TomoKV assigns shard owners and IO roles from inherited affinity and ratio/place; no Redis BIO/fork worker pools. |
| `bio_cpulist` | no | no / — | no | no | no (Redis 0/0) | TomoKV assigns shard owners and IO roles from inherited affinity and ratio/place; no Redis BIO/fork worker pools. |
| `aof-rewrite-cpulist` | no | no / — | no | no | no (Redis 0/0) | Native snapshot/AOF format and writer differ from Redis RDB/RESP persistence; this Redis control is not implemented. |
| `aof_rewrite_cpulist` | no | no / — | no | no | no (Redis 0/0) | Native snapshot/AOF format and writer differ from Redis RDB/RESP persistence; this Redis control is not implemented. |
| `bgsave-cpulist` | no | no / — | no | no | no (Redis 0/0) | TomoKV assigns shard owners and IO roles from inherited affinity and ratio/place; no Redis BIO/fork worker pools. |
| `bgsave_cpulist` | no | no / — | no | no | no (Redis 0/0) | TomoKV assigns shard owners and IO roles from inherited affinity and ratio/place; no Redis BIO/fork worker pools. |
| `ignore-warnings` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: Boot diagnostics have no named warning registry or suppression parser. |
| `proc-title-template` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: No process-title storage/renderer or Redis title substitution grammar exists. |
| `bind-source-addr` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `logfile` | yes / cfgfix | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `req-res-logfile` | no | no / — | oracle absent | oracle absent | no (Redis 1/0) | Redis LOG_REQ_RES conditional build setting; absent in the supplied oracle. |
| `locale-collate` | yes / e5f4360dca | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `masterauth` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `requirepass` | yes / 1482e32774 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `supervised` | yes / cfgfix | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `syslog-facility` | yes / cfgfix | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `repl-diskless-load` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `loglevel` | yes / cfgfix | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `maxmemory-policy` | yes / f94726446d | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `appendfsync` | yes / b9a5e89480 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `oom-score-adj` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: The Linux OOM adjustment apply/restore mechanism has not been implemented. |
| `acl-pubsub-default` | yes / e14d593062 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `sanitize-dump-payload` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: DUMP/RESTORE uses native checksummed object images; Redis RDB sanitization policy does not apply. |
| `enable-protected-configs` | no | no / — | no | no | no (Redis 0/0) | UNFIXED: persistence paths are retained at boot; protected-config policy is not implemented. |
| `enable-debug-command` | yes / 1482e32774 | no / no | yes (source defaults) | no | yes (Redis 0/0) | Captured value includes the gate harness override; boot default comparison needs the source defaults. |
| `enable-module-command` | no | no / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `cluster-preferred-endpoint-type` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `propagation-error-behavior` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `shutdown-on-sigint` | yes / 102bfa8662 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `shutdown-on-sigterm` | yes / 102bfa8662 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `databases` | yes / f94726446d | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `port` | yes / d82abe6cb9 | yes / yes | yes (source defaults) | yes | yes (Redis 0/0) | Captured value includes the gate harness override; boot default comparison needs the source defaults. |
| `io-threads` | no | no / — | no | no | no (Redis 0/0) | TomoKV assigns shard owners and IO roles from inherited affinity and ratio/place; no Redis BIO/fork worker pools. |
| `auto-aof-rewrite-percentage` | yes / b9a5e89480 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `cluster-replica-validity-factor` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `cluster-slave-validity-factor` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `list-max-listpack-size` | yes / 0d8044b956 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `list-max-ziplist-size` | yes / 0d8044b956 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `tcp-keepalive` | yes / 8f3d0900ec | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `cluster-migration-barrier` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `active-defrag-cycle-min` | no | yes / — | no | no | no (Redis 0/0) | FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller. |
| `active-defrag-cycle-max` | no | yes / — | no | no | no (Redis 0/0) | FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller. |
| `active-defrag-threshold-lower` | no | yes / — | no | no | no (Redis 0/0) | FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller. |
| `active-defrag-threshold-upper` | no | yes / — | no | no | no (Redis 0/0) | FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller. |
| `lfu-log-factor` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: Native LFU admission/counter code uses fixed policy constants, without a live logarithmic-factor control. |
| `lfu-decay-time` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: Native LFU decay uses its existing clock policy, without Redis minute-based live reconfiguration. |
| `replica-priority` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `slave-priority` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `repl-diskless-sync-delay` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `maxmemory-samples` | yes / a1fb1f0072 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `maxmemory-eviction-tenacity` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: Owner-local eviction has a different bounded work budget; no Redis tenacity mapping has been implemented. |
| `timeout` | yes / f94726446d | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `replica-announce-port` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `slave-announce-port` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `tcp-backlog` | yes / 8f3d0900ec | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `cluster-port` | no | no / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `cluster-announce-bus-port` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `cluster-announce-port` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `cluster-announce-tls-port` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `repl-timeout` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `repl-ping-replica-period` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `repl-ping-slave-period` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `list-compress-depth` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: Native compact/quicklist storage has no Redis LZF interior-node compression; accepting this would be ineffective. |
| `rdb-key-save-delay` | no | yes / — | no | no | no (Redis 1/0) | Native snapshot/AOF format and writer differ from Redis RDB/RESP persistence; this Redis control is not implemented. |
| `key-load-delay` | yes / cfgfix | yes / yes | yes | yes | yes (Redis 1/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `active-expire-effort` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: Expiry uses owner-local incremental budgets; the Redis effort-to-budget mapping is absent. |
| `hz` | yes / 5a16250171 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `min-replicas-to-write` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `min-slaves-to-write` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `min-replicas-max-lag` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `min-slaves-max-lag` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `watchdog-period` | no | yes / — | no | no | no (Redis 1/0) | UNFIXED: No Redis-style watchdog signal/timer exists; native worker stall diagnostics use other mechanisms. |
| `shutdown-timeout` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: Redis waits for replica catch-up here; TomoKV has no replicas and uses its own final-save/drain deadlines. |
| `repl-diskless-sync-max-replicas` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `maxclients` | yes / 8f3d0900ec | yes / yes | yes (source defaults) | yes | yes (Redis 0/0) | Captured value includes the gate harness override; boot default comparison needs the source defaults. |
| `unixsocketperm` | yes / 0939cecc57 | no / no | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `socket-mark-id` | no | no / — | no | no | no (Redis 0/0) | UNFIXED: Listener creation does not apply SO_MARK; the immutable socket option remains absent. |
| `max-new-connections-per-cycle` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: Accept batching/multishot io_uring admission has no Redis per-cycle quota setting. |
| `max-new-tls-connections-per-cycle` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: TLS accept admission has no Redis per-cycle quota setting. |
| `client-default-resp` | no | no / — | oracle absent | oracle absent | no (Redis 1/0) | Redis LOG_REQ_RES conditional build setting; absent in the supplied oracle. |
| `active-defrag-max-scan-fields` | no | yes / — | no | no | no (Redis 0/0) | FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller. |
| `slowlog-max-len` | yes / 04a0eaba47 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `acllog-max-len` | yes / e14d593062 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `busy-reply-threshold` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: Script execution has native instruction/work budgets, without Redis elapsed-time busy-reply policy. |
| `lua-time-limit` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: Script execution has native instruction/work budgets, without Redis elapsed-time busy-reply policy. |
| `cluster-node-timeout` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `cluster-ping-interval` | no | yes / — | no | no | no (Redis 1/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `slowlog-log-slower-than` | yes / 04a0eaba47 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `latency-monitor-threshold` | yes / 04a0eaba47 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `proto-max-bulk-len` | yes / f94726446d | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `stream-node-max-entries` | yes / 871603d359 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `repl-backlog-size` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `maxmemory` | yes / f94726446d | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `cluster-link-sendbuf-limit` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `hash-max-listpack-entries` | yes / 0d8044b956 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `hash-max-ziplist-entries` | yes / 0d8044b956 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `set-max-intset-entries` | yes / ce31b6ad7d | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `set-max-listpack-entries` | yes / 0d8044b956 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `set-max-listpack-value` | yes / 0d8044b956 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `zset-max-listpack-entries` | yes / 0d8044b956 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `zset-max-ziplist-entries` | yes / 0d8044b956 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `active-defrag-ignore-bytes` | no | yes / — | no | no | no (Redis 0/0) | FlatStore uses QSBR reclamation and its own allocation/rehash policy; no Redis defrag/lazyfree controller. |
| `hash-max-listpack-value` | yes / 0d8044b956 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `hash-max-ziplist-value` | yes / 0d8044b956 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `stream-node-max-bytes` | yes / 871603d359 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `zset-max-listpack-value` | yes / 0d8044b956 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `zset-max-ziplist-value` | yes / 0d8044b956 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `hll-sparse-max-bytes` | yes / 0939cecc57 | yes / no | yes | yes | yes (Redis 0/0) | UNFIXED: captured in boot-owned HLL/tracking structures; no live migration is implemented. |
| `tracking-table-max-keys` | yes / f8a9a6f10d | yes / no | yes | yes | yes (Redis 0/0) | UNFIXED: captured in boot-owned HLL/tracking structures; no live migration is implemented. |
| `client-query-buffer-limit` | yes / 5a41b14964 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `maxmemory-clients` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: Client accounting exists, but Redis client-memory eviction and percentage limits are absent. |
| `repl-backlog-ttl` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `auto-aof-rewrite-min-size` | yes / b9a5e89480 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `loading-process-events-interval-bytes` | no | yes / — | no | no | no (Redis 1/0) | UNFIXED: Native loading is coordinated across owners; Redis single-thread event-pump byte intervals have no mapping. |
| `tls-port` | yes / 0f920a52d7 | yes / no | yes | yes | yes (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-session-cache-size` | no | yes / — | no | no | no (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-session-cache-timeout` | no | yes / — | no | no | no (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-cluster` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `tls-replication` | no | yes / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `tls-auth-clients` | yes / 0f920a52d7 | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `tls-prefer-server-ciphers` | yes / 0f920a52d7 | yes / no | yes | yes | yes (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-session-caching` | no | yes / — | no | no | no (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-cert-file` | yes / 0f920a52d7 | yes / no | yes | yes | yes (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-key-file` | yes / 0f920a52d7 | yes / no | yes | yes | yes (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-key-file-pass` | no | yes / — | no | no | no (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-client-cert-file` | no | yes / — | no | no | no (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-client-key-file` | no | yes / — | no | no | no (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-client-key-file-pass` | no | yes / — | no | no | no (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-dh-params-file` | no | yes / — | no | no | no (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-ca-cert-file` | yes / 0f920a52d7 | yes / no | yes | yes | yes (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-ca-cert-dir` | yes / 0f920a52d7 | yes / no | yes | yes | yes (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-protocols` | yes / 0f920a52d7 | yes / no | yes | yes | yes (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-ciphers` | yes / 0f920a52d7 | yes / no | yes | yes | yes (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `tls-ciphersuites` | yes / 0f920a52d7 | yes / no | yes | yes | yes (Redis 0/0) | TLS context/session settings are created at boot; live context replacement and additional client TLS settings are not implemented. |
| `dir` | yes / d82abe6cb9 | yes / no | yes (source defaults) | no | yes (Redis 0/1) | Captured GET paths differ because each test server owns a private directory; both default to the current directory. UNFIXED: the persistence path is retained at boot and protected-config policy is not implemented. |
| `save` | yes / f94726446d | yes / yes | yes (source defaults) | yes | yes (Redis 0/0) | Captured value includes the gate harness override; boot default comparison needs the source defaults. |
| `client-output-buffer-limit` | yes / 8f3d0900ec | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `oom-score-adj-values` | no | yes / — | no | no | no (Redis 0/0) | UNFIXED: No configurable OOM-score policy for process roles exists; native persistence uses owner threads, not Redis fork children. |
| `notify-keyspace-events` | yes / ded646a91f | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
| `bind` | yes / d82abe6cb9 | yes / yes | no (source defaults) | yes | yes (Redis 0/0) | Runtime rebind implemented; the AF_INET transport still accepts one IPv4 address and defaults to loopback. Redis defaults to * -::* and also accepts lists/IPv6/optional addresses. |
| `replicaof` | no | no / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `slaveof` | no | no / — | no | no | no (Redis 0/0) | Excluded surface: cluster, replication, or modules; no corresponding service. |
| `latency-tracking-info-percentiles` | yes / bffd6e6b5e | yes / yes | yes | yes | yes (Redis 0/0) | Present; values/flags below report the captured state. Any mismatch remains a compatibility limitation. |
