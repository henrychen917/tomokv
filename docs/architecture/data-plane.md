# Data plane

The [architecture overview](../architecture.md) describes storage, execution,
and concurrency in detail. This guide follows a request through the server
and identifies the lifetimes that must remain distinct.

## Routing and ownership

TomoKV hashes the whole key, including braces, and routes it through a fixed
bucket-to-shard mapping. This is not Redis Cluster hash-tag routing. Shard
identity is stable; the executor owning a shard can change at runtime.

The connection thread parses commands from its receive buffer, resolves
command metadata and keys, and dispatches work to the shard owner. Tasks name
an operation in the connection's reorder buffer rather than copying the full
request. Ordinary requests use task lanes in both thread modes, including
self-owned work in fused mode. Eligible local reads are an explicit bypass.

Executors check ownership before accessing a store. Work carrying a stale
route is forwarded to the current owner. Shard migration quiesces affected
execution, adopts owner-local retirement and notification state, then publishes
the new route. See [shard.h](../../src/core/shard.h),
[server.h](../../src/core/server.h), and [ex_loop.h](../../src/core/ex_loop.h).

## Records and reads

[FlatStore](../../src/store/flatstore.h) uses an open-addressed table with
compact slot words, tags, and object pointers. A hash/tag match is a filter;
key length and bytes establish identity. Strings and collections have distinct
representations and command handlers.

With read-local armed, string replacement publishes immutable objects and
retains their predecessors through QSBR. Armed in-place overwrite is refused.
Eligible GET/MGET commands run on the connection thread; unsafe or conflicting
reads use owner execution. Capacity admission defers work when the local lane
is full. Production takes one local attempt and demotes on failed safety
validation. Topology and multi-key sequence validation remain on the operation
path; see [local reads](../architecture.md#local-reads) for the remaining
contract concern.

Cross-shard execution uses scatter/gather. Grouped MVCC controls logical
visibility separately from physical installation of candidate records. A
registered read cut selects visible versions; commit and abort cleanup retain
objects until no relevant reader can use them. See
[ordering and atomicity](../architecture.md#ordering-and-atomicity).

## Three completion boundaries

1. **Execution completes.** An owner publishes an operation's result. Operations
   for a connection can complete out of order.
2. **The reply retires.** The connection's reorder buffer exposes only the
   contiguous completed prefix. Reply bytes enter connection-owned writeback
   state; the operation slot can then be reused.
3. **The send completes.** Transport completion advances a separate byte
   frontier. Borrowed value storage must remain alive until its send lifetime
   ends, even after the original operation has retired.

Receive arguments also have a lifetime: buffer compaction and growth must wait
until no outstanding operation or kernel receive refers to the old storage.
See [conn.h](../../src/net/conn.h), [rob.h](../../src/net/rob.h),
[wb.h](../../src/net/wb.h), and [io_loop.h](../../src/core/io_loop.h).

## Transport and persistence

io_uring is the default network backend; epoll is explicitly selectable. The
connection thread parses and sends in both split and fused modes. TLS state
belongs to that connection, with kernel TLS attempted where supported.

Snapshots and append-only persistence coordinate with owner execution. AOF
ordering and durability receipts can affect reply eligibility; native file
formats remain separate from the Redis value codec used by DUMP/RESTORE. See
[persistence](../architecture.md#persistence-and-side-effects) and the
[configuration reference](../configuration.md#persistence-databases-and-memory).
