# encodingfix — Redis 7.4 parity and mainline measurement request

The missing `set-max-intset-entries` control is implemented, defaulting to **512**.
The supplied oracle reports **hash-max-listpack-entries = 512**, not 128, so the
hash default remains 512. Changing it to 128 would violate the requested oracle
parity. All seven existing listpack defaults already matched this Redis binary.
This is an explicit correction to the task's proposed defaults, not an omitted
hash edit. A 100-field hash is below both 128 and 512 and would not establish the
proposed hash conversion in either case.

Production sources and build budgets are committed in `ea0663450` and its three
lane predecessors. `origin/cpp` was merged before implementation and checked/
merged again before the final build and byte proof; it remained
`5efc5414d3d6107b5e7e29f2404e585806c823ec`, also the PRE merge-base. See
[final merge receipt](docs/encodingfix/final-merge.txt).

The lane ran builds, static checks, serverless production-handler fixtures and
the explicitly authorized Redis oracle on CPUs 120–127. It did **not** boot a
TomoKV server, run a load generator, run the gate, or make a throughput claim.
Live dispatch, both thread-mode boots, full correctness and ABBA remain mainline
work. No push was made.

## Oracle defaults and CONFIG semantics

Oracle: `/home/user/Projects/redis74/src/redis-server`, Redis **7.4.10**, source
identity `f103d127`, SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.
The lane selected free loopback ports, bound the process to CPUs 120–127, disabled
save/AOF, and terminated each process it started. The actual `CONFIG GET *max-*`
response, INFO identity and argv are in [oracle-defaults.json](docs/encodingfix/oracle-defaults.json).

| Canonical knob | PRE | Redis 7.4.10 | POST |
|---|---:|---:|---:|
| hash-max-listpack-entries | 512 | 512 | 512 |
| hash-max-listpack-value | 64 | 64 | 64 |
| list-max-listpack-size | -2 | -2 | -2 |
| set-max-intset-entries | missing; internal constant 128 | 512 | 512 |
| set-max-listpack-entries | 128 | 128 | 128 |
| set-max-listpack-value | 64 | 64 | 64 |
| zset-max-listpack-entries | 128 | 128 | 128 |
| zset-max-listpack-value | 64 | 64 | 64 |

The new control uses the canonical Redis name, boot/config-file parsing, CONFIG
GET/SET, live owner propagation and CONFIG REWRITE. No Tomo alias is invented:
the existing alias table has no set aliases, and the old set compact spellings
are deliberately retired. Its grammar is a canonical decimal integer in
`[0, 9223372036854775807]`; `0` prevents creation of intset storage, `-1` is invalid,
and there is no memory-unit suffix. GET preserves the full public value; the
effective internal limit saturates at Redis's 1G-entry cap. Case-insensitive
lookup and requested-case error text, invalid syntax/range errors, duplicate
arguments and an embedded NUL are compared against the oracle byte for byte.
Invalid SET preserves the previous value. Existing sets are not eagerly rebuilt
when the control changes.

## Precedence proof, including both atomic settings

`tests/encodingfix.py` emits **5,433 commands**, including **2,677 OBJECT ENCODING
checks**, with an encoding check immediately after each directed collection
mutation. The exact same RESP stream was sent to Redis and to real TomoKV handlers
in the serverless fixture with `atomic=0` and `atomic=1`.

| Phase/type | Boundary and returned encoding | atomic=0 | atomic=1 |
|---|---|---|---|
| Default hash | 512 fields: listpack; 513: hashtable | exact match | exact match |
| Default integer set | 512 members: intset; incremental member 513: hashtable | exact match | exact match |
| Default string set | 128 members: listpack; 129: hashtable | exact match | exact match |
| Default zset | 128 members: listpack; 129: skiplist | exact match | exact match |
| Custom hash | CONFIG entries 4/value 8; field 5 promotes | exact match | exact match |
| Custom set | CONFIG intset 3/listpack 5/value 8; creation and incremental rules below | exact match | exact match |
| Custom zset | CONFIG entries 4/value 8; member 5 promotes | exact match | exact match |
| Removal/value crossings | HDEL/SREM/ZREM down through each count boundary to deletion; value length 64/65 and 8/9 | exact match | exact match |

Oracle behavior is more specific than a universal intset → listpack → hashtable
ladder. A fresh numeric multi-add uses its argument-count hint to select intset,
then listpack if eligible, then hashtable. With limits 3/5, a fresh four-integer
SADD selects listpack; adding a fourth integer to an existing three-member intset
selects **hashtable directly**. An oversized argument-count hint can promote an
existing set even if all arguments are duplicates. Adding text to an intset uses
the existing integer text lengths and listpack bounds. SREM does not demote a
listpack or hashtable. Zero-intset and zero-both-compact cases are covered.

The new test also caught a pre-existing stale-maximum bug: after SREM removes a
wide integer, intset-to-text conversion must inspect the remaining extrema.
Both positive and negative 64-bit extremes now match Redis under value limit 8.
The fix reads the actual extrema at conversion time; it adds no reader retry or
in-place-write exception.

Each atomic leg has **zero differing replies**. Exact recorded replies and the
stream digest are in [oracle-replies.json.gz](docs/encodingfix/oracle-replies.json.gz),
[precedence-a0.json.gz](docs/encodingfix/precedence-a0.json.gz) and
[precedence-a1.json.gz](docs/encodingfix/precedence-a1.json.gz).
The command stream SHA-256 is
`b2e1277a41289a0dc671b4edb4c0c25c366cb755412526cc05b1e063459c1e4d`.

The existing hash/set/zset generators also passed four fixed seeds (7, 19, 20,
23), each in both atomic settings: **24 legs, 84,800 replies, zero differences**.
These use the existing `differ.py` generators and normalization unchanged; see
[collections-summary.json](docs/encodingfix/collections-summary.json).

The fixture calls registered handlers on one private shard. It starts no worker,
listener or ring; successful owner CONFIG fragments are folded to `+OK` as the
coordinator would do. Setting `atomic=1` here exercises handler configuration,
**not concurrent MVCC, live scatter/fanout or thread-mode dispatch**. The same
directed stream is registered as the live `encodingfix` differential generator
for the maintainer's gate. Mainline must validate those remaining dimensions.

Negative controls failed as required: PRE fails the new knob witness; a throwaway
ignored-knob body fails the incremental threshold check; a throwaway fresh-HT
body fails the fresh-listpack check; the saved pre-extrema-fix candidate fails
the two removed-wide-integer cases. These controls are build artifacts only.
Their failure logs are under `docs/encodingfix/negative-*.log`.

## Memory: actual INFO accounting, not a rate or RSS estimate

For each shape, create 256 keys and report
`(INFO used_memory after − before) / 256`. Keys are `efm:00000000` etc. (12 bytes),
hash fields/string-set members are four-byte `m000` etc., hash values are `v`,
and integer members are decimal 0–299. Every collection is created with one
multi-argument command. The script calls the existing production INFO MEMORY
and object-size accounting; TomoKV uses the serverless owner, while Redis uses
the pinned oracle. Redis figures are finite-batch INFO deltas and include its
allocator/global accounting. They are not allocator/RSS-normalized comparisons.

| Shape | PRE bytes/key | POST bytes/key | Delta | PAD A bytes/key | Redis bytes/key | PRE → POST encoding |
|---|---:|---:|---:|---:|---:|---|
| 100-field hash | 1,484 | 1,484 | 0 | 1,484 | 1,103.84375 | listpack → listpack |
| 300-field hash, additional check | 4,556 | 4,556 | 0 | 4,556 | 3,092.09375 | listpack → listpack |
| 300-member integer set | 30,512 | 2,796 | −27,716 | 30,512 | 718.09375 | hashtable → intset |
| 64-member string set | 876 | 876 | 0 | 876 | 526.09375 | listpack → listpack |

The accepted Redis-parity change saves accounted memory for the integer set in
this shape. There is no hash-memory trade at the verified defaults. Raw before/
after counters are in [memory-pre.json](docs/encodingfix/memory-pre.json),
[memory-post.json](docs/encodingfix/memory-post.json),
[memory-pad.json](docs/encodingfix/memory-pad.json) and
[memory-redis.json](docs/encodingfix/memory-redis.json). A live multi-owner INFO
repeat is left to mainline; these are explicitly one-owner accounting witnesses.

## Hot bodies, other changes and layout

`tools/lbstall_artifacts.py compare build/encodingfix/PRE build ...` passes:
**1,492/1,492 raw hot bodies identical; 1,492/1,492 identical including resolved
relocation targets**. This is the tool's GET/SET/MGET/MSET, lookup/mutation,
parser/dispatch, executor execute, fused pass and writeback/TLS inventory in both
compiled namespaces. Evidence: [hot.log](docs/encodingfix/hot.log) and
[hot.json.gz](docs/encodingfix/hot.json.gz).

The full emitted-body scan covers 94 object pairs and 17,066 functions; **131
bodies differ**. Every changed body, including added/removed signatures and cold
clones, is listed with its reason in [changed-bodies.md](docs/encodingfix/changed-bodies.md).
Hash and zset command object bodies do not change. Set changes include SADD,
`add_member`, snapshot loading and cross-shard insertion; GCC also changes SPOP
and some set-helper emissions. Stream XADD/externalization uses relocated cold
stream limits. CONFIG, boot, blocking helpers and compiler inlining side effects
account for the remaining entries.

Do not read the hot result as full-program byte identity: the broader
`infofields_artifacts.py` ordinary category is 4,803/4,828 equal, and linked
ordinary provenance is 2,989/3,013 proven. Its INFO-only pass/fail policy fails on
this collection/layout change. In particular, the DB0 executor outer loop,
read-local cleanup helpers, HELLO and client-migration extraction have emitted
changes outside the requested hot inventory. The complete list and broader
machine evidence are committed; the null and correctness gate must judge these
effects. No assertion or tolerance in either audit tool was changed.

All locked sizes remain identical in both namespaces:

| Type | PRE = POST bytes |
|---|---:|
| Op | 336 |
| Client | 1984 |
| ThreadCtx | 1408 |
| Shard | 1440 |
| FlatStore | 944 |
| Rob&lt;64&gt; | 192 |
| AtomicEntry | 144 |
| Config | 624 |

`TypeLimits` grows 32 → 36 bytes. In Shard, only `blocking_dirty_` moves
1208 → 1188 and `stream_limits_` 1184 → 1208; the store, registry, waiter count,
watch maps and all other named offsets stay fixed. In Config, `stream_limits`
moves 408 → 560 into reserved storage, and the reserved tail begins at 568
instead of 560. Existing threshold positions stay fixed. The extra owner limit
travels as part of the existing Shard/TypeLimits object and copy operations;
there is no separate owner-side allocation to migrate. Exact GDB member offsets
are in [layouts.json](docs/encodingfix/layouts.json).

Compiler-budget changes are limited to affected translation units: normal
`t_set.o` 23440 → 23568; DB0 `t_set.o` 23300 → 23428; normal `main.o` 146401 →
146409 because its included Config/Shard initialization changed. DB0 main retains
146203. No string-command TU budget or runtime branch was added for this work.

## Gate rows, fixtures and documentation

Rows **+2 quick / +2 full**: `encodingfix knob` and `encodingfix precedence` are
emitted by the loop at `tests/gate.sh:1680–1686`, before the quick-tier exit at
line 3397. Accordingly EXPECT_QUICK is **502** (was 500) and EXPECT_FULL is
**519** (was 517). Counts and the complete ledger fixture were updated in the
same commit as the rows, under the task's explicit authorization. The new live
differential generator runs inside existing aggregate rows and adds zero rows.

This checkout's knob matrix lives in `tests/netcmd_config_unit.cc`; it now has a
canonical knob/alias-free GET/SET row and REWRITE check. `tests/knobs.py` tests
owner fanout at a non-default threshold and restores 512. The old differential
oracle override forcing intset 128 was removed in both atomic modes. Searches
of threshold literals and OBJECT ENCODING fixtures are retained in
`docs/encodingfix/*fixture-search*` and `encoding-fixtures-final.txt.gz`.
Hash fixtures retaining 512 agree with the measured oracle and were not weakened.

`docs/CONFIGURATION.md` was regenerated by `python3 tests/docs_drift.py --write`.
The existing drift guard now generates/checks encoding rows, defaults, aliases
and source anchors directly from `config.h`; its new negative control catches a
changed documented default. `tomokv.conf` now documents the actual set control
and one-way conversion behavior.

Passing serverless/static checks: config parser; CONFIG knob matrix/REWRITE;
both new rows; exact boundary replay; existing collection replay; docs drift and
negative controls; ledger inventory's 10 tests; differential fanout assertions;
shell syntax; `git diff --check`. Logs are committed in `docs/encodingfix/`.
No full-gate-green claim is made.

Live differential suites for mainline, one per line:

```text
hash
set
zset
edgeenc
servertail
encodingfix
```

Run them at the gate geometry (`--shards 16`, its `GATE_RATIO`, default CPUs 0–7
with 6 io + 2 ex for split), both atomic modes, and both 1s/2s boots including
armed read-local coverage. Run `tests/gate.sh iteration` on the quiet scheduled
box. No fixture may gain a tolerance or drop an assertion to pass.

## PRE, POST and PAD artifacts

PRE was built from a clean archive of the merged base into `build/encodingfix/PRE`.
POST is the ordinary build; `build/encodingfix/POST/tomokv` is byte-for-byte equal
to `build/tomokv`. Both use the repository's production compiler flags and both
database namespaces. The exact ELF checksums are:

| Arm | SHA-256 |
|---|---|
| PRE | `ed92bcd7089ee56e846f319b54cbfce20a4096b9e35f7e763427fa6f11f1fa8b` |
| POST | `ff3b73795e045cf7593f4081e7d6237585f077975d8429737ff4cf42a9c20ae3` |
| PAD A | `6f75b3a193545530151d21f4f9f78bae87016beebadaa806eadc95f02bb0d9f6` |

All binary/fixture checksums are in [SHA256SUMS](docs/encodingfix/SHA256SUMS).
PRE `.text` is 7,817,349 bytes; POST/PAD `.text` is 7,820,053 bytes, a +2,704-byte
change. No inverse-control B is supplied: A already holds POST text exactly.

**PAD kind A — behavior twin for the specified default-threshold collection
workloads:** PRE's intset default 128 with candidate code and layout. The offline
`tools/encodingfix_pad.py` patches only the last int64 of the emitted defaults in
each namespace. Four read-only-data bytes differ from POST; all **7,830,109
executable-section bytes**, section addresses/sizes and symbol tables are exact
POST twins. Constructor disassembly must prove it consumes each patched default
table, or the script fails. The serverless twin returns the PRE memory/encoding
results in the table above. See [pad.json](docs/encodingfix/pad.json) and
[pad-unit.json](docs/encodingfix/pad-unit.json).

This control is scoped to default-threshold workloads. The new CONFIG surface
and non-default precedence fixes remain present; it is not a PRE emulator for
arbitrary CONFIG changes. Do not use custom intset/listpack thresholds on the
PAD measurement arms. No wrapper or special server arguments are needed.

## Quiet-box request to mainline

Use the gate's existing instrument and the unchanged **14-cell** inventory in
`tests/wbland_merit_cells.txt` (SHA-256
`de0e56e4696f780543c5adea21aa7d7283c12fa22110be6064370a69a2a68dc6`).
Measure the same-binary null first, then PRE/POST, PRE/PAD A and PAD A/POST with
the gate's ABBA ordering and per-cell cycles/op, instructions/op and IPC. Keep
the file's server/load geometry, connection counts and knobs. IDs/shapes are:

| Cell | Shape |
|---|---|
| h05 | GET p32, read-local 0 |
| h06 | SET p32, read-local 0 |
| p8g | GET p8, read-local 0 |
| p8s | SET p8, read-local 0 |
| d1g_l0 | GET p1 latency, read-local 0 |
| d1s_l0 | SET p1 latency, read-local 0 |
| m8g_l0 | MGET p8, read-local 0 |
| v1g_l0 | GET 1024-byte values p32, read-local 0 |
| d128g_l0 | GET p128, read-local 0 |
| d32g_l1 | GET p32, read-local 1 |
| d8s_l1 | SET p8, read-local 1 |
| d32s_l1 | SET p32, read-local 1 |
| x9_32_l1 | MIX 9:1 p32, read-local 1 |
| x9_32_l0 | MIX 9:1 p32, read-local 0 |

The existing headline inventory and ABBA workload implementation have **no
HSET/HGET or SADD/SISMEMBER cells**. The `h` prefix denotes headline cells, not
hash workloads. No collection-throughput number is supplied or implied here;
adding a collection instrument remains an owner decision. The memory witnesses
above cover the requested collection shapes without inventing rate measurements.

Verdict: retain ordinary-command performance within the gate's existing null/
regression policy at matched offered load; rate (and the designated p1 latency
score) decides, with cycles/op, instructions/op and IPC explaining it. This is
a parity change, not a claimed speedup. PRE/PAD tests code/layout effects while
PAD/POST isolates the default threshold in identical executable code. Keep all
existing tolerances. Record the measured PRE/POST table, both thread-mode gate
results and any collection instrument added by the owner in
`MEASURE-RESULT-encodingfix.md` before merge.
