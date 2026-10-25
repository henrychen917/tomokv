# AT4.13 — logical WATCH key count

Fixed in `multi_session_watch_size`: each logical (database, key) contributes
its one physical-namespace-zero alias. Single-database code keeps its original
constant-time size query. No layout or WATCH reservation semantics change.

Redis source: `/home/user/Projects/redis/src/networking.c:2896` reports the length
of the client's watched-key list; `multi.c:288` deduplicates by database and key.
The actual oracle is `/home/user/Projects/redis74/src/redis-server` (7.4.10).

`atomfix5_watch`, through `GATE_ONLY_JOBS` and the gate's normal job lifecycle,
runs 16 legs: 1s/2s × uring/epoll × atomic 0/1 × databases 1/16. Eight server
cores 48–55, load/coordinator 56–63, shards 16, split ratio 6:2, fused read-local
1, key/client LB and auto FLIP off. Ports 34800–34801. Every leg runs on PRE
`ef5204b2e` and POST, and compares CLIENT INFO and CLIENT LIST with Redis.

PRE: all eight databases-16 legs fail with 32 for two watched keys and 48 for
three; all eight databases-1 controls pass. POST: 16/16 pass. Duplicate WATCH,
same name in another logical database, SWAPDB, UNWATCH, EXEC and DISCARD are
included. Compressed complete battery logs and the partial ledgers are adjacent.
Initial harness runs exposed two fixture errors (Redis uses a different ready
banner; fused rejects `--ratio`); both were corrected before these receipts.

One new gate row, collected before the quick-tier exit: DQ=+1, DF=+1. Protected
EXPECT constants are unchanged. Source inventory is checked again after all
lane rows are complete. Runtime proof of broader families and merit remain in
the lane report; this directed pass does not substitute for them.
