# Snapshot table sizing and FLUSHALL isolation

## snapfix2

Worktree `/home/user/Projects/cx-snapfix2`, branch `cx-snapfix2`, PRE `a214652ec`,
BASE `5572e84cc`. All builds and correctness processes use CPUs 0–15; servers use
0–7 (16 shards, split ratio 6:2), drivers 8–15, ports 20100–20199. No push and no
performance measurement in this lane.

### Sizing review

The proposed `docs/snapfix/followup/table-sizing.patch` needs a correction.
`snapshot_prepare` runs before owners freeze. Both `insert` variants and both
`atomic_prepare_capacity` variants admit new keys up to the **current** capacity
while prepared. Sizing a sparse 1024-slot table's destination to 128 can therefore
accept 513 keys before Mark, then leave a destination too small for the merge.
The directed addition to `storage flush-prepared-capacity regression` exercises
that schedule with read-local both armed and disarmed and fails before a stuck
merge on the unfloored proposal.

POST chooses `max(old_capacity, 2 * min(live_capacity, old_capacity))`, where
`live_capacity` is the smallest power of two from `kMinCap=64` for which
`(live+1)*100 < capacity*kLoadPct` (`kLoadPct=70`). Tombstones are omitted from the
fresh destination's sizing because the merge drops them. The current-capacity
floor preserves every prepared insert/reservation's existing bound; the upper
bound is the old allocation rule. The post-cut gate still reserves space for all
current live keys, current tombstones and frozen live keys. No command admission,
read visibility, object layout, QSBR or retirement rule changes. Existing oversized
tables are retained until ordinary deletion-driven shrinking; future idle saves
do not compound them.

The sole production caller is `ExLoopT::snapshot_control_pass` in Preparing.
SAVE, BGSAVE, save-rule cron, shutdown-save, enabled-AOF rewrite and offline-AOF
rewrite all use `SnapshotManager::start` and that owner path. Read-local Mark uses
the same prepared allocation. Completion/cancellation leave it for the ordinary
bounded merge. FLIP creates no snapshot table; its transition mutex and snapshot
admission exclude simultaneous placement changes, and the shared atomic barrier
drains units before the snapshot cut.

### Rows and proof (in progress)

`snapfix2_tables` independently runs 12 idle BGSAVEs on 1s/2s × uring/epoll ×
atomic 0/1 and Redis 7.4. It is collected immediately after `snapfix_bgsave_exec`,
before the quick-tier exit: **DQ=+1, DF=+1 relative to BASE**. EXPECT constants are
unchanged. Including snapfix's inherited +3/+3, the maintainer's 807/824 becomes
811/828. PRE fails the RSS bound on all eight TomoKV legs; Redis passes.
Receipt: `docs/snapfix2/proof/rows-pre/record.json`.

The FLUSHALL neighbour already reproduces on PRE with BGSAVE disabled. Further
isolation, final budget/identity/scope evidence, POST correctness receipts and arm
digests will be recorded here when complete.

### Maintainer measurement request

Use the gate's own ABBA instrument for the 14 generic cells in
`docs/execfair/cells/generic14.txt` and 2s GET/SET p1/p32 (`tests/headline_cells.txt`
h17, h18, h49, h50). BASE vs POST is the sizing-fix comparison; retain PRE vs POST
for the combined snapfix change. PAD is **A, behaviour twin**: BASE behaviour in
the exact POST-layout common image. Compare POST-layout vs PAD-A separately from
the release binaries. Command counts are expected to be null; matched offered
load, cycles/op and IPC decide any performance effect. No throughput claim here.

On a quiet box, also record RSS and BGSAVE start latency for each of 16 consecutive
saves, BASE vs POST, idle one-key geometry, both modes/engines. Correctness RSS
checks in this lane do not establish a latency or throughput result.
