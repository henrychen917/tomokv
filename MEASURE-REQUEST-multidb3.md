# multidb3 — correctness status, DB-0 variant, and measurement request

Worktree `/home/user/Projects/cx-multidb`, branch `cx-multidb`, starting commit
`42bed6ec2`. Runtime changes are through `0bbfc025b`; the tracking negative
control is `de9c997f7`; offline artifact tools are `326f6164a`.

**Not ready to land. No performance result is claimed.** No server, gate, load
generator, benchmark, or hardware-counter measurement was run. Builds and
serverless correctness checks stayed on CPUs 0–15 during the authorized Codex
phase. Correctness must be green before the measurement request below is acted on.

Two requirements remain unresolved:

* The two concurrent-SWAP socket closures in the supplied gate logs have no
  established root cause or demonstrated fix. Command-level failure context was
  added to the existing battery; that is diagnostic coverage, not a correction.
* Map-only SWAPDB publication without an execution boundary contradicts the
  unchanged serial-order oracle. The existing execution boundary is retained.
  The requested removal of that boundary was not implemented.

## Correctness repairs

The supplied `build/gate-run.CuSoGc/jobs/` logs separate into these causes:

| Reported rows | Finding and change | Evidence available here |
|---|---|---|
| edgetime and expwide, four geometries each | `multidb_size` and INFO's census used expiry-on-visit `scan`. DBSIZE/INFO therefore physically reaped the record whose residence the tests were measuring. Both now walk physical slots without expiry; DBSIZE retains the atomic visibility adjustment. | Serverless unit leaves an elapsed key resident across DBSIZE and INFO, then proves GET reaps it. Read-local off/on pass. |
| cmdgap, four geometries | The shelved-command inventory still included MOVE and SWAPDB although both were implemented. | Removed those two stale inventory entries; no expected response or tolerance weakened. |
| atomic owner-local hazard S1 | The new all-owner INFO path acquired the 600 ms fanout delay intended to hold a data read. Polling its diagnostic counters consumed the arming window. | INFO and BORROWCOUNT are excluded from the hook. A unit prepares real INFO and DBSIZE scatters and asserts only DBSIZE receives the deadline. |
| execiso | Eight distinct shards could all belong to one executor at the 16-shard/6:2 geometry. | Key selection now requires the second shard to have a different actual owner. |
| six multidb persistence failures | The `md:wake` list popped by a parked BLPOP was resurrected by LOADAOF. Parked completion bypassed the ordinary executor AOF epilogue. | Journal the successful physical pop postimage. The analogous resumed XREADGROUP path journals each owned stream key. Native persistence units pass; the live parked-operation replay cases await the gate. |
| two differential matrix failures | After a swap, tracking registered the namespace hash, but invalidation transport and the tracking table used raw key bytes. The filter could discard the invalidation. | Registration now hashes raw bytes. The extended existing tracking row passes; restoring the old registration in a throwaway object fails at `raw invalidation reaches a physically stamped read`. |
| two concurrent multidb cases | EOF on a swapper in 1s/read-local 1/atomic 1 and 2s/read-local 0/atomic 1. | Still unresolved. The supplied server logs show neither send errors nor a crash explanation. |

These are patches and directed checks, not a claim that 22 or 24 gate failures
have been cleared. The gate has not been rerun.

The multidb battery now includes a mid-pipe SELECT/SET/SWAPDB/SELECT/GET sequence
that checks both moved-away and moved-to reads. Its concurrent MGET pair is
selected from observed ownership and must span different owners in both physical
namespaces; failure to find that geometry is fatal. Both swappers must finish
128 swaps and the read loop must run. `tests/multidb_serial.py` is unchanged.

## Why the requested map-only boundary is withheld

The existing oracle self-test rejects this concrete history:

1. SET in logical DB 0 starts and is stamped physical 0, but does not execute.
2. SWAPDB 0 1 publishes and replies.
3. GET in logical DB 1 starts after that reply and returns missing.
4. The old SET executes into physical 0 and replies.
5. A later GET in logical DB 1 returns the value.

Putting SET before SWAP requires step 3 to see its value. Putting SET after SWAP
requires it to write the physical namespace now named by logical DB 0, so step 5
cannot see that value in DB 1. Invocation overlap permits either serial position;
it does not make either inconsistent visibility history legal. One map snapshot
per operation prevents mixed namespace identification, but does not repair this
visibility problem. A different execution/visibility mechanism or a changed
contract would be necessary to remove the boundary. No oracle was weakened.

## Boot-selected representation

`databases` defaults to **1**. Startup selects one of two separately compiled C++
runtimes, with distinct namespaces to prevent inline/COMDAT binding across
representations. The default runtime is linked first. Lua's C implementation is
shared; database state and C++ callbacks are separate. The decision happens once
after configuration validation, before server initialization. Sanitizer/debug
build recipes also link both variants.

For the single-database runtime, Slice has no namespace member, key identity is
32-bit length, KvObj uses the original decoder/allocation geometry, and the hash
sees the original length. Parser stamping, map-reader RMWs, namespace arming, and
database boundary checks are compiled out of ordinary dispatch. It keeps the
original FLIP enum values. The mutable map is absent from Server's instance
layout; snapshot map fields are absent from SnapshotManager's instance layout.
The inert identity state requires no namespace heap allocation.

For configured multiple databases, parsing obtains one immutable map snapshot
and stamps every identified key's **physical** namespace before hashing, routing,
or RYOW accounting. MOVE/COPY lowering no longer takes a second snapshot. EXEC
uses its private routing map, including queued SELECT/MOVE/SWAPDB. The unused
numeric epoch stored in the command-name Slice was removed; physical key identity
is the carried stamp. Scoped commands, WATCH, notifications, persistence, and
the existing FLIP dispatch boundary remain. Parked logical waiters retain their
existing remap behavior. This runtime still pays namespace costs and needs a
separate measured result.

Only multidb boots and differential target boots explicitly select 16 databases.
Other gate boots exercise the new default runtime. No gate rows were removed or
added. **EXPECT_QUICK stays 438; EXPECT_FULL stays 454**, untouched. The modified
multidb collection at lines 2782–2787 and existing unit collections precede the
quick-tier exit at line 2813.

## GET p32 cost attribution: evidence and limits

The supplied round-2 PAD restored the round-1 decoder in round-2 layout. It kept
the other representation changes. PAD approximately matching POST therefore
rules out a useful decoder improvement; it does **not** uniquely distinguish
struct layout from Slice identity, parser materialization, or hashing. No new
instruction or IPC measurements were collected here, so a numerical allocation
of the loss among those causes would be invented.

| Candidate cause | Static evidence on the round-2 DB-0 path | Single-database candidate |
|---|---|---|
| (a) 64-bit identity compare | The identity witness changes operand width, not the number of equality comparisons. Equal function size does not prove equal surrounding register pressure or dependencies. | Restores the exact PRE 32-bit comparison body. |
| (b) KeyExt decoder | Round-2 standalone decoder is 149 bytes versus PRE's 69. The owner's decoder PAD did not recover rate. Short DB-0 records themselves retain the legacy allocation geometry. | Exact PRE decoder body, including original extended-length handling. |
| (c) parse stamp | On an unselected, never-swapped round-2 connection, `namespace_armed` is false: there is no per-op epoch-stamp call to charge. The pass still reads namespace arming state, and every parsed Slice materializes namespace identity. | Removes those arming reads and Slice namespace materialization. The actual RESP parser body matches PRE. |
| (d) hash fold/codegen | Mix64 folds packed identity through the existing multiply; namespace zero preserves the numeric hash. SipHash has explicit namespace arithmetic. The emitted standalone hash grows from 754 to 794 bytes. | Standalone hash and string-TU hash match PRE. Some surrounding TUs still make different compiler decisions. |
| (e) layout/codegen | Round 2 adds 120 bytes before Server's original fields and 264 bytes inside its snapshot manager. Locked headline object sizes alone missed this drift. | Audited Server and snapshot sizes/offsets match PRE, but the dual-runtime executable changes text placement and several loop bodies. |

Offline witnesses from the same instrument source, using archived `115da1721`,
archived `42bed6ec2`, and the single-database candidate:

| Emitted body, bytes (not instructions/op) | PRE | Round 2 | POST | POST instructions/targets equal PRE |
|---|---:|---:|---:|---|
| identity witness | 238 | 238 | 238 | yes |
| decoder witness | 69 | 149 | 69 | yes |
| hash witness | 754 | 794 | 754 | yes |
| actual RESP parser | 1554 | 1470 | 1554 | yes |

The production-object audit, including PRE main.o, finds **497/611** comparable
bodies equal after only C++ namespace normalization and address relocation
resolution. Clean GET/SET handlers are equal at 1072/2201 bytes; their string-TU
find/find_in bodies are equal at 699/446 bytes. The report also records every
mismatch: parse/execute loops and read-local store helpers are not all identical.
For example, main.o's hash clone is 797 bytes in PRE and 845 in POST. This is not
an assertion that the entire operation path is byte-identical.

| Layout witness | PRE | Namespaced runtime | Single-database POST |
|---|---:|---:|---:|
| sizeof(Server) | 105152 | 105536 | 105152 |
| sizeof(SnapshotManager) | 528 | 792 | 528 |
| Server.cfg_ offset | 0 | 120 | 0 |
| Server.threads_ offset | 66408 | 66528 | 66408 |
| Server.flipctl_ offset | 67936 | 68320 | 67936 |
| Server.shard_owner_ offset | 69688 | 70072 | 69688 |

All locked sizes remain Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624; Slice remains 16.
Evidence is in `build/multidb3-layout.json`, `multidb3-audit.json`,
`multidb3-primitives-{post,round2}.json`, and `multidb3-disassembly-*.txt`.

Rate at matched offered load remains decisive. Equal retired instruction counts
would still leave IPC, data-line placement, dependency stalls, and instruction
placement to explain. `cycles/op = instructions/op / IPC`; none of those hardware
quantities is inferred from the byte tables.

## Frozen arms and PAD meaning

All paths below are relative to this worktree; digests are SHA-256.

| Artifact | Digest |
|---|---|
| `build/tomokv-multidb3-pre` | `8f6da00365aced98eb925906ec2dfdb2ca9cf8995a40371ad48d7dfa5ff79034` |
| `build/tomokv-multidb3-post` | `81a7f413a66f593557d377166b0e4ebd7f0dfd66a4aee01324b59a9b1f727951` |
| `build/tomokv-multidb3-pad` | `77ae74ecfeb813d4ca2b163d22c2c61a7c1d6d2293712326deb6c17354e628c8` |
| `build/multidb3-cost-pre` | `46414a4834d6c95de587e9b9a3cd5eb7c7536a67d5718babe6278c0d931b3a9d` |
| `build/multidb3-cost-post` | `5892ed74c89b15c20618e9dd1cabb3de0588f0ba84ee98ece8c7e21cb89b4370` |
| `build/multidb3-cost-pad` | `5892ed74c89b15c20618e9dd1cabb3de0588f0ba84ee98ece8c7e21cb89b4370` |
| `build/multidb3-cost-multi` | `0911b1901c45d0e6f151e65860aea7880c49297acb72dcd2d0caf076de5ffeb4` |

PRE is the inherited v7/pre-multidb reference (`115da1721`). POST is the release
build of `0bbfc025b`; later commits only add tests/tools/reporting. The artifact
receipt is `build/multidb3-artifacts.json`. Server .text is 3,557,219 bytes in PRE
and 6,946,417 in POST/PAD; compiling two runtimes nearly doubles it. That layout
change is a material limitation, not evidence of a performance null.

**PAD kind A — behavior twin, scoped to DB-0 GET/SET traffic.** It forces the
legacy single-keyspace runtime in POST's exact ELF layout. The tool preserves
CET, all section/symbol layouts, and all other bytes, changing three bytes in the
cold boot selector. It is not a multi-database correctness binary.

Default POST already selects that same runtime. Thus this PAD is deliberately a
degenerate control: POST/PAD operation code is identical, and the instruction
PAD is a byte-identical copy of the POST instrument. It provides **no independent
mechanism-versus-layout separation**. A POST/PAD loss against v7 still rejects
the candidate; it cannot be explained away with this PAD. No inverse-control
claim is made.

Recreate the server control offline with:

```sh
python3 tools/multidb3_artifacts.py pad build/tomokv-multidb3-post build/tomokv-multidb3-pad
```

## Maintainer measurement request — after correctness is green

Use the existing gate ABBA instrument, pinned rungs and quiet-box placements
from round 2. Preserve offered load, key/value population and sizes, client count,
ratio, instrumentation and run durations across arms. Do not recalibrate between
arms or compare a rung-1 stop against another arm's summary rung. Retain raw
per-arm rate, instructions/op, cycles/op, IPC and spreads in `MEASURE-RESULT`.

1. Run v7/PRE versus POST and v7/PRE versus kind-A PAD for **h05, h07, h21, h23**.
   POST/PAD use `--databases 1`; PRE receives no new database option. Include the
   matched null and POST/PAD duplicate-control pair.
2. Run the owner's unchanged **p8g1, p8s0, p8s1, f8g1** definitions for both pairs.
   Reuse the actual round-2 definitions; do not infer workloads from their names.
3. Run the same cells on POST with **`--databases 16`, traffic still in DB 0**,
   versus v7 and versus POST/1. Report that configured-path cost separately.
4. Include SET p32 partners h06/h08/h22/h24 to cover the restored write
   representation. Do not substitute them for the required GET or p8 verdicts.

| Cell | Owner-supplied round-2 POST vs v7 | Round-3 POST/1 vs v7 | Kind-A PAD vs v7 | POST/16 vs v7 |
|---|---|---|---|---|
| h05 | -0.4%, ladder stopped at rung 1 | pending | pending | pending |
| h07 | -2.7% on every rung >=2 | pending | pending | pending |
| h21 | -1.3% at rung 2; -5.8% summary | pending | pending | pending |
| h23 | -0.2%, ladder stopped at rung 1 | pending | pending | pending |
| p8g1 | -3.4% | pending | pending | pending |
| p8s0 | -4.9% | pending | pending | pending |
| p8s1 | -2.4% | pending | pending | pending |
| f8g1 | -1.4% | pending | pending | pending |

The owner's round-2 decoder PAD rates were h05 -2.8%, h07 -2.6%, h21 -5.6%,
h23 -5.8%. They are historical inputs, not results produced by this lane.

**Decision: the default DB-0 path must be a null against v7 at the matched load
and rungs. Less loss, a generic -3% allowance, or fewer instructions does not
meet the bar.** Identical-arm spreads above 2% require resolving interference or
a defect, not widening tolerances. The configured multi-database cost remains
explicit even if the default passes.

For the serverless instruction unit, the maintainer runs these instruments on
one fixed quiet core, each with `--instructions GET` and `--instructions SET`,
using PRE/POST and PRE/PAD ABBA blocks (at least three), plus the namespaced arm:

```text
build/multidb3-cost-pre
build/multidb3-cost-post
build/multidb3-cost-pad
build/multidb3-cost-multi
```

The source is the same `tests/multidb_cost_unit.cc`: real RESP parsing, p32 ROB
publication/retirement, hash and handlers, 4096 resident 24-byte keys, 128-byte
values, 4,194,304 measured operations after correctness warm-up. The namespaced
arm additionally takes the physical stamp from the identity map per operation.
It opens no listener or ring. The counters form one non-multiplexed hardware
group; unsupported or multiplexed counters fail. This instrument excludes the
network and full IO/executor schedules, so it cannot establish the threaded null.

| Unit | PRE instr/op | POST instr/op | PAD instr/op | Namespaced instr/op |
|---|---|---|---|---|
| GET p32 | not collected | not collected | not collected | not collected |
| SET p32 | not collected | not collected | not collected | not collected |

## Completed validation and remaining work

Release binary and both variants build. The multidb unit passes five grouped
checks, including default representation, both read-local states, native
persistence, and owner/transaction behavior. Both deterministic boundary cases
pass: four p32 writers, 32 epochs each, every delayed window required to arm.
PRE/default/namespaced instruction instruments pass GET/SET `--self-test`, with
no counters opened. Another 34 existing serverless cases pass: 10 networking/
command cases, eight core concurrency cases (ASAN/UBSAN test TU), and 16 atomic
survivor cases. The new post-SWAP tracking check passes and its deliberately
broken registration fails. Python syntax, shell syntax, unchanged serial-oracle
self-test, and `git diff --check` pass.

Logs: `build/multidb3-build.log`, `multidb3-unit.log`, `multidb3-boundary.log`,
`multidb3-cost-*-self.log`, `multidb3-checks/summary.json`,
`multidb3-tracking.log`, and `multidb3-tracking-negative.log`. An initial netcmd
invocation without its required case argument was a usage failure; its log is
retained as `build/multidb3-netcmd.log`, and the named cases above were then run.

The maintainer still needs to resolve/reproduce the two EOF failures, decide the
SWAPDB visibility design, boot both modes, run all 454 gate rows and the live
persistence/serial-order cases, then collect the requested performance and
instruction measurements. No full-gate or performance acceptance is asserted.
