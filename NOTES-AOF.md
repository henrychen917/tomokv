# AOF continuation notes

## Banked work

- Step 1 is `477d5b3ec`: framed writer plus recovery replay.
- Step 2 is `407e3ddf8`: atomic-group bracketing. Its quick gate completed 30/30 checks.
  The directed interrupted-process arm recovered 10 committed groups, skipped two pre-commit
  fragments, verified every GCMT dependency at a lower file offset, and ended with clean shutdown
  invariants.

## Step 3 candidate results (not banked)

The sync-policy candidate implemented async `IORING_OP_FSYNC`, a contiguous posted/written/durable
chunk frontier, reply waiter wakes, live `CONFIG SET appendfsync`, and the three policy batteries.
It completed the expanded quick gate at 35/35 on `GATE_PORT=7955 GATE_CORES=224-231`, including:

- `always`: sync counter and reply gate fired; every acknowledged key recovered after an unclean
  stop.
- `everysec`: write gate and idle sync fired; a seven-byte-short final large frame was truncated
  with an explicit warning, while the older dataset replayed completely.
- `no`: zero sync submissions and zero reply-gate waits.

Matched local measurements used server CPUs 224-231, load CPUs 232-239, 16 shards, 4 IO + 4
executor roles, 64 connections, pipeline 32, one-million-key rotation, and 32-byte values.

| cell | run 1 | run 2 | run 3 | median |
| --- | ---: | ---: | ---: | ---: |
| pre-AOF binary, SET instructions/op | 4,302.40 | 4,055.89 | 4,036.47 | 4,055.89 |
| candidate, `appendonly no`, SET instructions/op | 4,321.21 | 4,006.37 | 4,031.25 | 4,031.25 |
| candidate, AOF everysec, SET/s | 496,771 | 606,428 | 499,750 | 499,750 |
| candidate, AOF everysec, GET/s | 1,672,241 | 1,522,070 | 1,470,588 | 1,522,070 |

The without-persistence control delta was -24.64 instructions/op, satisfying the requested <= +1
bar. The AOF everysec run wrote 3,000,000 records and observed 8 sync completions plus 21,769 reply
gate waits.

## Binding floor is unavailable

The mission requires `/home/user/Projects/wt-round-mainline` with `appendonly yes` and
`appendfsync everysec` as the matched floor. That reference is at `fe02301ac` and builds cleanly,
but its configuration deliberately makes the requested cell impossible:

1. On the assigned eight server CPUs, its default resolves to 5 IO + 3 executor roles. Boot then
   refuses `appendonly yes` because its AOF cannot see the per-worker shard databases.
2. An explicit `--tomokv-thread-io 1 --tomokv-thread-ex 0 --tomokv-cores-per-node 1` boot is also
   refused because the fork requires at least one IO and one executor role per topology node.
3. Enabling AOF by changing that reference gate would not create a valid floor: the reference's own
   diagnostic states that AOF would serialize only its empty decoy database, not the sharded
   dataset under test.

Reproduction:

```sh
taskset -c 224-231 ./src/redis-server --port 7955 --bind 127.0.0.1 \
  --protected-mode no --save "" --appendonly yes --appendfsync everysec \
  --auto-aof-rewrite-percentage 0 --dir /tmp/round-mainline-aof-floor

taskset -c 224-231 ./src/redis-server --port 7955 --bind 127.0.0.1 \
  --protected-mode no --save "" --appendonly yes --appendfsync everysec \
  --tomokv-nodes 1 --tomokv-cores-per-node 1 \
  --tomokv-thread-io 1 --tomokv-thread-ex 0 --tomokv-thread-mode static \
  --dir /tmp/round-mainline-aof-floor
```

The mission's stop clause therefore applies: step 3 candidate code is not banked, steps 4-5 are not
started, and the earlier green steps remain intact.
