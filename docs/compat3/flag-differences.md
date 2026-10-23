# Additional FUNCTION flag differences (inventory only)

The final oracle inventory ran 35 command/flag combinations in each thread mode,
plus admitted growth and restoration of the ordinary memory limit. Both modes
have the same 20 command differences: 40 observations in
[flags-audit-differences.json](flags-audit-differences.json). These are existing
script command-surface differences and were not fixed in this lane.

The five flag sets are `{}`, `{no-writes}`, `{allow-stale}`,
`{no-writes,allow-stale}`, and `{no-writes,allow-oom}`. Each runs GET, SET, DEL,
PUBLISH, SPUBLISH, PFCOUNT and PING from a registered function using redis.pcall.

| Command | Redis without no-writes | Redis with no-writes | TomoKV, all five flag sets |
|---|---|---|---|
| PUBLISH | Integer 0, no subscribers | `ERR Write commands are not allowed from read-only scripts.` | `ERR command 'PUBLISH' is not allowed from scripts` |
| SPUBLISH | Integer 0, no subscribers | Same read-only error | `ERR command 'SPUBLISH' is not allowed from scripts` |
| PFCOUNT | Integer 1 for the seeded HLL | Same read-only error (MAY_REPLICATE classification) | `ERR command 'PFCOUNT' is not allowed from scripts` |
| PING | `PONG` | `PONG` | `ERR command 'PING' is not allowed from scripts` |

GET/SET/DEL observations match the oracle for all five flag sets. A separately
registered unflagged function admitted below a 16 MiB cap successfully writes
32 MiB; the subsequent ordinary SET is rejected, proving that the function's
temporary permission ends after the callback. Those assertions passed on the
oracle and both target modes. This does not assert identical allocator accounting
or the same admission threshold between the two implementations.

Geometry: databases 1, atomic 0, io_uring, 16 shards, eight fused threads or
split 6:2; target CPUs 96–103/port 25890, oracle CPU 104/port 25891, clients
105–111. Exact startup/stop records are in
[resume-flags-audit.log](resume-flags-audit.log). The directed gate separately
covers FCALL/FCALL_RO and OOM precedence for both atomic modes and engines.

Replica/disconnected-stale behavior is NOT RUN: TomoKV has no corresponding
supported state. On the primary, allow-stale introduces no additional difference
beyond the command-surface inventory above.
