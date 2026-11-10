# Redis compatibility

TomoKV v1.0 targets Redis 7.4 command semantics on a single node and supports
RESP2 and RESP3, including `HELLO 3`. Use Redis client libraries or `redis-cli`
to connect. A supported command name does not imply support for every Redis
subcommand, option, encoding, or operational feature.

## Supported surface

The release registers 245 top-level names, including aliases, standalone error
handlers, and TomoKV's `FLIP`. `COMMAND`, `COMMAND INFO`, and `COMMAND DOCS`
expose the registry and metadata.

| Family | Examples and facilities |
| --- | --- |
| Strings and keys | GET/SET, multi-key operations, counters, bitmaps, expiration, scanning |
| Collections | Hashes and hash-field expiration, lists, sets, sorted sets |
| Streams | Streams, consumer groups, blocking reads |
| Probabilistic and geographic | HyperLogLog and geospatial operations |
| Transactions and scripting | MULTI/EXEC, WATCH, Lua scripts, Lua functions |
| Messaging and clients | Pub/sub, keyspace notifications, tracking, client administration |
| Administration | ACLs, CONFIG, INFO, slowlog, latency tracking, memory limits |
| Persistence | Native snapshots and append-only logs; DUMP/RESTORE value serialization |

## Absent and limited facilities

Cluster management, replication, Sentinel, loadable modules, and cross-server
key migration are outside the single-node scope.

- `CLUSTER`, `MIGRATE`, `MODULE`, `PSYNC`, `REPLCONF`, `SENTINEL`, and `SYNC`
  have no registry entries.
- `REPLICAOF` and `SLAVEOF` reject replication. `ASKING`, `READONLY`, and
  `READWRITE` return the cluster-disabled error.
- `WAIT` cannot obtain replica acknowledgements. `WAITAOF` with a positive
  local-fsync count is unimplemented.

Logical databases **are** supported. `databases` defaults to `1` and accepts
`1` through `256`; `SELECT`, `MOVE`, `COPY ... DB`, and `SWAPDB` preserve database
identity through pipelines and transactions. One executable includes both a
single-keyspace runtime and a namespace-aware runtime, selected at startup.

## Atomicity and scripts

With the default `atomic 0`, ordinary multi-shard mutations can expose
intermediate states. `atomic 1` enables grouped epoch-MVCC. Transactions and
staged cross-shard scripts have their own group admission even at `atomic 0`.
Read cuts select retained MVCC versions; they are not a general snapshot
promise against unversioned plain writes.

Scripts use a VM-instruction budget rather than Redis's wall-clock busy
threshold. Cross-shard scripts stage declared keys in a bounded private
workbench and can fail on resource limits or repeated conflicts. See
[ordering and atomicity](ARCHITECTURE.md#ordering-and-atomicity) and
[configuration](configuration.md#threads-placement-and-execution) for details
and limits of the concurrency contract.

## Persistence and memory

Snapshot and AOF files use TomoKV's own formats. Whole Redis RDB/AOF files
cannot be loaded as native persistence. `DUMP`/`RESTORE` provide a Redis RDB
value codec for supported encodings; this does not provide whole-file
interchange. Native recovery preserves logical database mappings.

Eviction accounting, compact representations, and some diagnostic fields differ
from Redis. `maxmemory` divides a data budget among shards and is not a process
RSS cap. INFO values and their accounting boundaries are documented in the
[INFO reference](info.md).

## Configuration round-tripping

Start with [tomokv.conf](../tomokv.conf), not an unmodified Redis configuration.
Unknown boot options cause startup to fail. The runtime CONFIG table is a
subset of boot options; some settings are immutable and must be supplied at
startup. See the [configuration reference](configuration.md) for the accepted
names, values, defaults, and mutability.

`CONFIG REWRITE` requires a startup configuration file. It quotes values and
preserves original directives outside the runtime table, but it does not
export CLI-only placement overrides such as `--ratio`. Encoding aliases share
their canonical setting. Several count and byte thresholds use 32-bit bounds;
acceptance of a Redis spelling does not imply Redis's full numeric range.

## Verification

The [publication gates](gates.md) include differential tests against a pinned
Redis 7.4 source tree and server, along with protocol, persistence, transaction,
and concurrency batteries. Their oracle and fixture files remain in `tests/`.
