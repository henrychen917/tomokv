# Client compatibility, INFO, and Unix sockets

This lane is RESP2-only. It implements the Redis discovery and bookkeeping surface used by common
clients and tools without moving sockets into executor threads or adding shared writes to the store
path. The command handlers and registry rows are in `src/cmd/t_server.cc`.

## Connection behavior studied

The Redis/Valkey behavior was checked in the read-only references, principally Redis
`src/networking.c` (`helloCommand`), `src/server.c` (`COMMAND` and `COMMAND DOCS`), `redis-cli.c`,
and `redis-benchmark.c`, with their Valkey counterparts as a second implementation. Current client
initialization was also checked in the official redis-py, go-redis, and Jedis repositories.

| Consumer | Connection/discovery calls relevant here | tomokv behavior |
| --- | --- | --- |
| redis-py | Optional `AUTH`, `CLIENT SETNAME`, `SELECT`, then best-effort `CLIENT SETINFO LIB-NAME` and `LIB-VER`; non-RESP2 configurations negotiate with `HELLO`. | Use `protocol=2`. `AUTH` reports the Redis no-password-configured error, db 0 is accepted, and both `SETINFO` forms are accepted. |
| go-redis | Negotiates with `HELLO <protocol>`; a Redis error permits its legacy RESP2 fallback, followed as configured by `AUTH`, `SELECT`, `CLIENT SETNAME`, and pipelined `CLIENT SETINFO`. | `HELLO 3` deliberately returns `-NOPROTO`, enabling the fallback. Setting `Protocol: 2` avoids the failed probe. Only db 0 is supported. |
| Jedis | Legacy/default-RESP2 configurations connect directly, then optionally issue `AUTH`, `SELECT`, and `CLIENT SETNAME`; configurations with protocol negotiation use `HELLO`. | Configure RESP2. The connection-local calls above are implemented; RESP3 negotiation is deliberately rejected. |
| redis-cli | Defaults to RESP2; current interactive help obtains `COMMAND DOCS`; explicit `-3` sends `HELLO 3`. Cluster discovery also probes `CONFIG GET databases`. | Normal CLI sessions and live help receive correctly shaped RESP2 arrays. `-3` fails with `NOPROTO` by design. |
| redis-benchmark | Before a run it probes `CONFIG GET save` and `CONFIG GET appendonly`; `-3` sends `HELLO 3`. | Both config keys exist. Use its default RESP2 mode. |
| YCSB Redis binding | Uses ordinary RESP2 data commands and may configure authentication/database selection, depending on the binding version. | Run without a password and with database 0. Its `SET`/`GET` workload needs no compatibility extension beyond this lane. |

`HELLO` and `HELLO 2` return the Redis RESP2 representation of the seven-field map: a 14-element
flat array containing `server`, `version`, `proto`, `id`, `mode`, `role`, and `modules`. The server
identity is `redis`, protocol is integer 2, mode is `standalone`, role is `master`, and modules is
an empty array. `HELLO 3` returns `-NOPROTO unsupported protocol version`.

`COMMAND` metadata is generated from the boot-built registry, including actual arity, flags, and
legacy key positions. `COMMAND DOCS` is deliberately minimal but is a well-formed RESP2 map-as-flat-
array with `summary`, `since`, `group`, and `complexity`, which is sufficient for current
`redis-cli` live-help parsing. `COMMAND INFO` preserves one nil entry per unknown requested name.

Client names and library metadata live in a cold process catalog keyed by `Client*`, preserving
`sizeof(Client) == 1984`. `CLIENT INFO` and `CLIENT LIST` expose at least `id`, `addr`, `name`, and
`db`, plus the recorded library fields. `RESET` restores db 0 and clears name/library metadata.

## CONFIG behavior

The typed table contains `save`, `appendonly`, `maxmemory`, `maxmemory-policy`, `timeout`,
`databases`, `proto-max-bulk-len`, `zc-min`, and all eight `*-max-compact-{entries,value}` settings.
`CONFIG GET` matches Redis-style case-insensitive globs and returns flat name/value pairs.
`CONFIG SET` accepts one or more pairs, normalizes booleans and byte suffixes, rejects unknown
settings, overflow, invalid policies, and malformed pair counts.

Changing `zc-min` or a compact threshold is scattered to every shard owner and updates its local
runtime setting. The remaining entries are compatibility/control-plane values: changing them does
not enable persistence, eviction, idle disconnects, a different request bulk limit, or additional
databases. The implementation remains a single-db, no-persistence server.

## Cross-shard SCAN cursor

The unsigned decimal cursor is encoded as:

```text
bits 63..56  shard id (0..255)
bits 55..0   owner-local FlatStore cursor
              bit 32     current rehash table (0 or 1)
              bits 31..0 next physical slot
```

Equivalently, `cursor = (shard_id << 56) | inner_cursor`. Cursor 0 begins shard 0. Finishing one
shard returns the next shard id with an inner cursor of zero; finishing the final shard returns 0.
Server boot already limits the shard count to 256.

`COUNT` is a work hint measured in physical hash slots examined, so sparse stores cannot turn one
pass into an unbounded table scan. `MATCH` and `TYPE` filter returned entries without expanding that
slot budget. For a stable keyspace a complete cursor cycle visits all live slots. As with Redis
`SCAN`/`HSCAN`, mutation during iteration may cause duplicates or omissions, and callers must not
treat `COUNT` as a requested result count. Expired entries encountered by the owner are removed and
not returned.

`RANDOMKEY` chooses a pseudo-random starting shard in IO, prefers a shard whose published count is
nonzero, then executes on that shard's owner and selects from a pseudo-random physical starting
slot. It never makes an IO thread inspect a `FlatStore`.

## INFO provenance

All request-path counters have one writer. Registry command ids index a plain counter array owned
by each IO or executor thread; one public scatter command is counted once by its IO thread. INFO is
the exceptional operation that sums those arrays.

| Field | Source |
| --- | --- |
| `used_memory`, `used_memory_dataset` | Sum of each shard's published logical `KvObj` bytes. |
| `allocator_allocated`, `allocator_resident`, `used_memory_rss` | jemalloc `mallctl` epoch/stat values when built with jemalloc; zero with the libc allocator. |
| `total_commands_processed`, `cmdstat_*:calls` | Sum of the per-thread registry-id arrays. |
| `keyspace_hits`, `keyspace_misses`, `expired_keys` | Sum of shard-owner counters. |
| `evicted_keys` | Zero placeholder; eviction is not implemented. |
| `total_connections_received`, `rejected_connections` | Sum of per-IO accept/accept-error counters, including the Unix acceptor. |
| `connected_clients` | Size of the cold client metadata catalog. |
| `db0:keys`, `expires` | Sum of shard counts published by owners at batch boundaries. |

The object byte/count/expiry publications occur at executor batch boundaries. INFO and DBSIZE can
therefore lag an in-progress batch, but neither reads an owner-only store. The instantaneous-rate
and network-byte fields are currently zero compatibility placeholders.

## FLUSH scatter/gather precedent

`FLUSHALL` and `FLUSHDB` validate `ASYNC|SYNC` on IO, preflight enough capacity in every target
SPSC task channel, publish one public `Op`, and enqueue one task for every shard. Each executor
clears only shards it owns. The tasks share a heap-side `ScatterState` completion count; after its
store work each owner decrements the count, and the last owner emits `+OK`, marks the original Op
done, and notifies its normal IO completion path. Thus reply ordering remains governed by the
existing ROB and executors never touch sockets. The coordination atomic is outside FlatStore work
and exists only for an invoked scatter command. `ASYNC` and `SYNC` are accepted aliases because
there is no persistence/freeing mode distinction in this server.

This is the intended precedent for later scatter/gather commands: one client-visible Op, complete
capacity preflight before publishing any task, owner-only shard work, and one normal-path final
completion. No partial fan-out is allowed.

## Unix socket design

`--unixsocket PATH` creates one filesystem `AF_UNIX` listener in addition to every IO thread's TCP
listener. A filesystem Unix pathname is a unique bind key on Linux; `SO_REUSEPORT` does not provide
the sound per-thread listener group used for TCP. The first IO thread therefore owns the Unix
multishot accept and round-robins accepted clients to all IO threads through the existing client
channels. The target IO thread assigns the ready-mask slot, owns recv/parse/retire/send for life,
and executors still see only tasks.

At boot, a non-socket path is never removed. An existing live Unix listener is detected with a
connect probe and rejected; only a stale socket that refuses connections is unlinked. The path is
unlinked after an orderly shutdown. When `--unixsocket` is absent, the IO loop selects a template
specialization with no handoff/channel discrimination or pending-handoff check in its hot pass.

## Suggested compile and manual tests

The implementation was verified with a compile-only `make -j`; the server was not executed. A
manual session can be run after starting a test instance separately:

```sh
PORT=6380
SOCK=/tmp/tomokv-compat.sock

redis-cli -2 -p "$PORT" PING
redis-cli -2 -p "$PORT" HELLO 2
redis-cli -2 -p "$PORT" CLIENT SETNAME compat-check
redis-cli -2 -p "$PORT" CLIENT GETNAME
redis-cli -2 -p "$PORT" CLIENT SETINFO LIB-NAME redis-cli
redis-cli -2 -p "$PORT" CLIENT SETINFO LIB-VER test
redis-cli -2 -p "$PORT" CLIENT INFO
redis-cli -2 -p "$PORT" COMMAND COUNT
redis-cli -2 -p "$PORT" COMMAND INFO GET SCAN not-a-command
redis-cli -2 -p "$PORT" COMMAND DOCS GET SCAN
redis-cli -2 -p "$PORT" CONFIG GET '*max*'
redis-cli -2 -p "$PORT" CONFIG GET save
redis-cli -2 -p "$PORT" CONFIG GET appendonly
redis-cli -2 -p "$PORT" CONFIG SET zc-min 32768 hash-max-compact-value 96
redis-cli -2 -p "$PORT" SET compat:key value
redis-cli -2 -p "$PORT" TYPE compat:key
redis-cli -2 -p "$PORT" DBSIZE
redis-cli -2 -p "$PORT" RANDOMKEY
redis-cli -2 -p "$PORT" --scan --pattern 'compat:*'
redis-cli -2 -p "$PORT" INFO server
redis-cli -2 -p "$PORT" INFO memory
redis-cli -2 -p "$PORT" INFO commandstats
redis-cli -2 -p "$PORT" INFO keyspace
redis-cli -2 -p "$PORT" FLUSHDB ASYNC
redis-cli -2 -p "$PORT" DBSIZE

redis-cli -2 -s "$SOCK" PING
redis-benchmark -p "$PORT" -t ping,set,get -n 10000
```

Use a persistent interactive `redis-cli -2` session to verify that `CLIENT SETNAME`, `GETNAME`,
`RESET`, and `CLIENT ID` apply to the same connection; separate one-shot invocations intentionally
create separate client ids. Also try interactive `HELP GET` to exercise `COMMAND DOCS`.

Edge cases worth checking:

- `HELLO nope`, `HELLO 1`, and `HELLO 3`; only `HELLO 2` succeeds.
- `AUTH secret` and `AUTH default secret`; both report that no password is configured.
- invalid CLIENT subcommands, whitespace/control characters in names, unknown SETINFO attributes,
  and `CLIENT NO-EVICT` without `ON|OFF`.
- `CONFIG SET unknown value`, missing value pairs, invalid booleans/policies, negative numerics,
  byte suffixes such as `64mb`, and numeric overflow.
- `SCAN nope`, a cursor whose top byte is outside the configured shard count, `COUNT 0`, a missing
  option value, an unknown option, and an invalid TYPE.
- `FLUSHDB LATER`, more than one mode argument, `SELECT -1`, and `SELECT 1`.
- Empty-keyspace `RANDOMKEY`, SCAN across a resize/expiry workload, and FLUSH while a large zero-copy
  GET reply is in flight (the existing borrow-retirement path keeps its bytes alive).
