# Flip throughput judge: `getNumCommands()` vs per-worker `ops_total`

Every flip verdict (keep a climb, coast, overshoot-walk-back, KEEP/REVERT an episode) is decided by a
throughput comparison. The quantity fed into that comparison — the node's ops/sec — is measured
differently for single-node and multi-node topologies, and the reason is a measurement bias in the
per-worker counter. In `tomoFlipController()`, `src/server.c:25652-25677`.

## The two throughput sources

```c
int s0 = (nnodes == 1) ? 0 : node * server.ex_per_node;
int s1 = (nnodes == 1) ? server.num_workers : (node + 1) * server.ex_per_node;
uint64_t node_ops = 0;
if (nnodes == 1) {
    node_ops = (uint64_t)getNumCommands();                                   /* 25673 */
} else {
    for (int w = s0; w < s1 && w < server.num_workers; w++)
        node_ops += tomoRelaxedRead(server.exThreads[w].ops_total);          /* 25675-25676 */
}
```

- **Single node** (`nnodes == 1`, the default and the 1-simnode bench): `getNumCommands()` — a
  server-wide count of **client-visible commands**.
- **Multi node**: the sum of relaxed `ops_total` over the node's provisioned worker slots.

`node_ops` then feeds the instantaneous rate and the throughput EWMA
(`inst = (node_ops - ops_prev)*1000/(now - ops_prev_ms)`, `src/server.c:25790-25791`).

## `getNumCommands()` — client-visible commands (`src/server.c:3184-3188`)

```c
long long getNumCommands(void) {
    long long s = server.stat_numcommands;
    for (int i = 0; i < TOMO_STAT_SLOTS; i++) s += tomoRelaxedRead(server.cmdstat[i].n);
    return s;
}
```

It folds the legacy scalar `server.stat_numcommands` plus the per-thread command-stat shards
`server.cmdstat[i].n` (relaxed reads). Under the cmdstat COUNTING RULE this increments **exactly once
per client command wherever it completes** (ee451 #B1 folded worker execution into it). It is a
server-wide fold, so it is legal as a node signal precisely when the node **is** the server — i.e.
`nnodes == 1`.

## `ops_total` — per-worker dispatch groups (`src/server.h:2594`, bumped `src/server.c:22053`)

`exThread.ops_total` is `_Atomic uint64_t`, single-writer (the owning worker), bumped by the number of
**popped queue entries** on each work pass, before the loop even distinguishes ordinary commands from
cross-shard sub-fakes and sentinels:

```c
tomoRelaxedBump(worker->ops_total, (uint64_t)n);   /* n = entries popped this pass ; src/server.c:22053 */
```

So `ops_total` counts **per-worker dispatch groups**, not client commands.

## Why the two differ: the mget8 dispatch-group-count bias (`src/server.c:25661-25671`)

For a multi-key command, `ops_total`'s group count **scales with the worker count**. The controller
comment records the measurement:

> ops_total counts per-worker dispatch groups, and for multi-key commands that count SCALES WITH THE
> WORKER COUNT: an 8-key MGET scatters into ~min(8, workers) coalesced groups, so io4→io5 (4 workers →
> 3) deflates the counter ~17% while true MGET throughput RISES ~18%.

Concretely, on the `mget8` park cell:

- baseline read `io4 = 1.66M "ops"` **>** `io5 = 1.63M` (from `ops_total`);
- memtier measured `io4 = 486k` **<** `io5 = 576k` (true client throughput).

Fed `ops_total`, the judge vetoed every correct grow-front (twice), and the same bias stopped the
`io2/io3` walks at `io5`. Single-key workloads divide out (one group per command), which is why `get`
and `zrange` landings were never wrong. `getNumCommands()` counts once per client command wherever it
completes, so it removes the bias — legal as a node signal only when the node is the whole server.

For `nnodes > 1` the group sum is kept until a per-node client-command counter exists; that judge
still carries this bias there (`src/server.c:25671`).

## Consumers of the judge

The `node_ops`-derived rate is the reference for:

- the momentum climb's `significant`/`improved`/`coast`/`overshoot` verdicts (`src/server.c:26679-26736`);
- the episode's per-candidate verdict and KEEP/REVERT (`src/server.c:26608-26677`,
  `flip-anchor-and-episode.md`);
- the anchor rate-band drop (`flip-drops.md`);
- the `FLIP_LOAD_SHIFT^k` re-baseline test (`src/server.c:26566-26596`).

## State variables

| Field | Type | Meaning |
| --- | --- | --- |
| `server.stat_numcommands` | `long long` | legacy scalar baseline (folded, resets on RESETSTAT) |
| `server.cmdstat[i].n` | atomic (relaxed) | per-thread command-stat shard, `TOMO_STAT_SLOTS` of them |
| `exThread.ops_total` | `_Atomic uint64_t` | per-worker popped-entry (dispatch-group) counter |
| `fc->ops_prev` | `uint64_t` | previous `node_ops` snapshot |
| `fc->ops_prev_ms` | `mstime_t` | timestamp of that snapshot |

## Invariants

- Single-node throughput is client-visible commands (`getNumCommands()`), a per-command count immune
  to the multi-key group-scaling bias (`src/server.c:25661-25673`).
- Multi-node throughput sums `ops_total` over provisioned worker slots (a converted-to-IO worker's
  counter freezes ⇒ contributes a 0 delta; the workers that absorbed its buckets show the load) and is
  explicitly acknowledged to carry the worker-count bias for scattered multi-key commands
  (`src/server.c:25652-25677`).
- `ops_total` is bumped by the whole pop batch `n`, so it includes cross-shard sub-fakes and drain/
  flush sentinels, whereas the coarse/fine LB counters are incremented only for ordinary `argc >= 2`
  fakes after the sub-fake `continue` (`src/server.c:22053`, `:22144-22230` — see `key-lb.md`).

## Note vs the brief / `loadbalance-flip.md`

The task frames this as "`getNumCommands()` client-visible-command judge vs per-worker `ops_total`."
The code confirms exactly that split, gated on `nnodes == 1`. This matches `loadbalance-flip.md`'s
"Entry gates and sample scope" note that "single-node throughput uses `getNumCommands()` … multi-node
throughput sums relaxed `ops_total` … explicitly worker-count-biased for scattered multi-key
commands."
