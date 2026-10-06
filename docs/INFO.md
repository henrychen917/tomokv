# INFO monitoring fields (ST2)

`INFO`, `INFO DEFAULT`, `INFO ALL`, `INFO EVERYTHING`, and any section list
containing `KEYSPACE` include the keyspace section. Section names are insensitive
to ASCII case. Empty databases have no `dbN` line. The requested field grammar is
`dbN:keys=K,expires=E,avg_ttl=T`.

| Field | Meaning | Freshness in the published path |
| --- | --- | --- |
| `keys` | Resident keys in logical database N, including elapsed keys pending collection | One owner batch boundary |
| `expires` | Keys with a logical key deadline; a persisted object retaining TTL storage is not volatile | One owner batch boundary |
| `avg_ttl` | Nonnegative millisecond TTL estimate; zero with no deadlines or no recorded sample | Published sample from the owner boundary, aged using wall time at INFO; empty samples retain the prior estimate; sampling error has no exactness guarantee |

Counters are independently sampled across shards; INFO is not a global MVCC
snapshot. The bound is an owner progress boundary, not a millisecond deadline.
`DBSIZE NOW` retains the exact owner scatter when callers need a census.

The published path is enabled in both database images. Multi-DB counters are
indexed by **physical namespace** within each shard. DBSIZE uses the operation's
stamped namespace; INFO captures one immutable logical-to-physical map, so SWAPDB
relabels counts without walking or moving keys. MOVE accounts for both source and
destination; FLUSHDB changes only its namespace, and FLUSHALL clears every row.

Single-DB keeps its bounded TTL sampler. Multi-DB keeps owner-private key/expiry
counts and deadline sums; publication visits only dirty database rows, at most
256 per shard, and stores the key/expiry pair atomically once per boundary.
Its TTL estimate ages the mean deadline from that boundary and clamps at zero;
it does not compute an exact mean of individually clamped remaining TTLs.
Observer-visible state is separate from owner-private counters and follows the
store on shard migration. See [the ST2 completion report](../MEASURE-REQUEST-storesize2.md).

| Section | Owner scatter needed by its implementation? | Data read |
| --- | --- | --- |
| SERVER | No | Configuration, topology, clocks |
| CLIENTS | No | Existing connection catalog/counters |
| MEMORY | No | Published sizes/bytes and existing memory gauges |
| PERSISTENCE | No | Persistence manager reports/counters |
| STATS | No | Existing shard/thread/network gauges |
| COMMANDSTATS | No | Existing command call counters |
| FLIPCTL | No | Controller report |
| WRITEBACK | No | Writeback policy report |
| LB | No | Load-balancing signal snapshots |
| KEYSPACE | No | Published counters, mapped to logical database names |

No INFO section requests a mutating owner operation. This change does not alter
the pre-existing sampling/synchronization of other INFO gauges.

Compatibility references: Redis's [DBSIZE implementation](https://github.com/redis/redis/blob/7.4.0/src/db.c)
counts the selected database without expiry collection; its [INFO implementation](https://github.com/redis/redis/blob/7.4.0/src/server.c)
emits nonempty logical databases, and [active expiry](https://github.com/redis/redis/blob/7.4.0/src/expire.c)
maintains a sampled TTL estimate. Redis 7.4 also emits `subexpiry`; TomoKV's
pre-existing omission of that fourth field is unchanged by this requested
three-field change. `DBSIZE NOW` is an existing TomoKV extension, not Redis grammar.
