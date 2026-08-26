# Keyspace notifications v2: stop-clause analysis

Date: 2026-08-26

Branch: `t-notify2`

Base: `b5f534522830`
v1 source: `d789aa9f2` (rebased form of `956358381`)

## Disposition

The v2 implementation is deliberately **not included in this commit**. Proof (a), correctness,
layout, and an affinity-constrained wire analogue pass, but the canonical proof-(b) geometry could
not be run without violating the assigned resource boundary:

- assigned/mandatory boundary: CPUs `240-243`, port `7951`, and all work inside that slice;
- canonical gate: server CPUs `0-31`, ratio `18:14`, load-generator CPUs `64-127`.

Those CPU sets are disjoint. No process was run outside `240-243`, so there is no valid canonical
`p128_32c_{set,get}` result to claim. Per the mission stop clause, the feature remains as uncommitted
working-tree changes for inspection rather than being shipped as a partially proved feature.

## V2 implementation evaluated

- Every write family has clean and armed `template<bool kNotify>` handlers.
- Registry rows carry `handler` and `handler_notify`; IO chooses the armed shadow row from one
  pass-local cached flag test per operation.
- Disabled executor handlers have no notification test or context setup.
- Plain FlatStore `find`/`erase`/`insert` entry points contain no notification sink checks. Armed
  handlers call separate aware entry points. Expiry/eviction checks remain only in slow paths.
- Notification context setup is confined to armed handler/scatter/blocking/MULTI variants.
- String armed instantiations live in `t_string_notify.cc`, isolating the clean translation unit's
  inlining budget.
- All new Shard state and the IO notification-chain deque are at true cold tails. The latter was
  initially inherited ahead of legacy IoLoop members; moving it to the tail restored all legacy
  `srv_`/`self_` offsets and moved constrained SET from outside to inside the one-percent band.

## Proof (a): disabled code generation

Base and v2 were built locally with the same compiler/options. Objdump was compared after removing
only linked addresses, RIP-relative displacements/comments, and the expected `cmd_set` symbol-name
difference. Instruction streams and counts are exact:

| Symbol | Base | v2 | Result |
|---|---:|---:|---|
| `store_string` | 603 | 603 | exact |
| `cmd_set` / `cmd_set<false>` | 673 | 673 | exact |
| `ExLoop::execute` | 394 | 394 | exact |
| `FlatStore::find` | 335 | 335 | exact |
| `FlatStore::erase` | 164 | 164 | exact |
| `FlatStore::insert` | 452 | 452 | exact |
| `FlatStore::insert_into` | 282 | 282 | exact |

The clean string object uses GCC `--param large-unit-insns=10400`. Splitting the armed
instantiations changed GCC's unit-size accounting even though they were not reachable from the
clean specialization: the default threshold produced a `cmd_set<false>` size of `0x83e`; `10400`
restores the base `0xae2` decision. `store_string` is `0x9fc` in both builds.

## Deliberate IO codegen difference

The disabled IO path is not byte-identical by design. `IoLoop::parse_and_dispatch` is `0x257b`
bytes in base and `0x2626` in v2. The disabled common-path additions are exactly:

1. once per parse pass, load `notify_armed_` and spill the pass-local boolean;
2. once per operation after lookup/arity validation, `cmpb $0,<cached>` plus a predicted-not-taken
   `jne` to `command_notify_variant`;
3. `CommandSpec` grows from 40 to 48 bytes for `handler_notify`.

The armed-only target calls `command_notify_variant`; the disabled fall-through stores the original
clean row in `op.spec`. No notify load/test reaches `cmd_set<false>`, `ExLoop::execute`, or plain
FlatStore operations. Before the final cold-tail correction, the v1 notification-chain deque also
shifted legacy IoLoop fields by 80 bytes; that placement divergence has been removed.

## Layout proof

- `sizeof(Op)`: base `336`, v2 `336`.
- `sizeof(Client)`: base `1984`, v2 `1984`.
- `sizeof(FlatStore)`: base `640`, v2 `640`; every pre-existing field offset is identical.
- `sizeof(Shard)`: base `968`, v2 `1040`; every pre-existing field through
  `watch_reservations_` (offset 912, size 56) is identical. New state starts at offset 968.
- `sizeof(ExLoop)`: base `912`, v2 `920`; new pending state is at the tail.
- `sizeof(IoLoop)`: base `2488`, v2 `2584`; new state is at the tail after the final relocation.

## Correctness

Final exact-binary results, pinned to CPUs `240-243` and port `7951`:

- `tests/gate.sh quick`: **27 ok, 0 FAIL** (release/footprint, ASAN build, torture, RYOW,
  atomic 0/1, multi, blocking, pubsub, Lua, auth, limits, and notification battery).
- Redis 7.4.2 differential, seed 7: **301 commands, 443 events, 0 diffs**.
- Shutdown: no live connections, non-quiesced ROBs, or pending unsent bytes.

The gate's RST torture sentinel was observed to be intrinsically nondeterministic: under its
immediate-start shape, untouched base lost the deliberately RST-aborted `churn7` write in 2/5
runs. Both base and v2 passed 5/5 after normal startup settling; the final integrated v2 run is the
27/27 result above.

## Proof (b) analogue inside the authorized slice

The closest permitted wire shape retained the requested wire, shards, database, pipeline, and
load-generator geometry but necessarily changed the server split:

- 25GbE namespaces, port `7951`;
- server and load generator both restricted to CPUs `240-243`;
- server ratio `2:2`, 64 shards;
- memtier `t64 c8`, pipeline 128, random keys, 64-byte values, key maximum 2,000,000;
- 15-second cells, ABBA ordering, fresh 2M-key fill, five-second teardown pauses.

| Cell | Base ops/s | v2 ops/s | v2 vs base |
|---|---:|---:|---:|
| p128 SET analogue | 1,883,834.14 | 1,898,280.11 | **+0.767%** |
| p128 GET analogue | 1,740,675.91 | 1,739,625.42 | **-0.060%** |

Both analogues are inside the requested plus/minus one-percent band, but they are not represented as
canonical proof because server and load-generator execution contend on the four authorized CPUs.

## Enabled-path information

On the same constrained p128 SET shape, with `notify-keyspace-events AE` and a live draining
`PSUBSCRIBE __keyevent@0__:*` subscriber:

- runs: 1,591,597.91 and 1,594,487.98 ops/s;
- mean: **1,593,042.94 ops/s**.

## Required next action

Run interleaved base/v2 SET and GET on an exclusive box or with explicit authority for server CPUs
`0-31` and load-generator CPUs `64-127`, using the mission's `18:14`, shards 64, `t64 c8`, p128,
kmax 2M geometry and four-to-five-second teardown pauses. If both canonical means are within
plus/minus one percent, the preserved working-tree implementation is eligible for a feature commit;
otherwise retain this stop and use the IO delta above as the next ablation boundary.
