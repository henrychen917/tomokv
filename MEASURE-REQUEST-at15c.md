# AT15c — seed-7 edgetime PTTL investigation

Investigation in progress, 2026-10-06. This lane merged `origin/cpp` before editing
(merge `bfc13903f`).
Only this worktree is edited. No production change, test comparison relaxation,
EXPECT edit, benchmark, or push is part of this investigation.

## Reproduction and scheduling conditions

Three POST and three frozen PRE full armed-fused replays use the unchanged
`docs/at15b/replay.sh` and `tests/differ_gate.sh`, alternating arms, with fresh
output directories under `build/at15c/replay-*`. The wrapper requests 16 shards,
eight fused threads, read-local=1, databases=16, atomic=0; target CPUs 112–119,
Redis CPU 120, clients 121–127. All six frozen seeds and all discovered suites
remain in each replay. A failed matrix is retained as failed.

**Observed interference:** unrelated compiler jobs and another lane's server
were active. Although TomoKV's startup correctly discovered CPUs 112–119,
subsequent `/proc` readings showed TomoKV and Redis thread affinity masks
broadened to CPUs 112–127. `docs/at15c/host-conditions-1.json` preserves the
observed processes, working directories and per-thread masks. This lane did
not broaden those masks. These conditions limit performance attribution.

The POST-only premise has been disproved: frozen PRE fails the unchanged full
wrapper at operation 2910, and three separate timestamped PRE replays fail both
positions. Both rebuilt candidate binaries also pass three fresh focused
replays without a source change. This is not a monotonic commit predicate.
The final six-run reproduction table is pending; currently:

| Full wrapper run | edgetime seed 7 | PTTL delta at 1526 | PTTL delta at 2910 | Whole matrix |
| --- | --- | ---: | ---: | --- |
| POST 1 | FAIL | −5 ms | −5 ms | 238/246 suite legs pass; shell pass=239 fail=9, 15m02s |
| PRE 1 | FAIL | −1 ms (reported tolerance) | −2 ms | 233/246 legs pass; shell pass=234 fail=14, 9m11s |
| POST 2 | FAIL | −6 ms | −7 ms | Still running |

Full logs, exact operand bytes and matrix completion accounting are retained
under `docs/at15c`; `summarize_replays.py` regenerates `reproduction.json`.

## Exact stream and hypotheses

`docs/at15c/dump_stream.py` extracts the unchanged generator with seed 7 without
opening a socket. `edgetime-seed7.json` contains all 4,426 zero-based operations
and concrete illustrative deadlines; `edgetime-seed7-context.log` contains both
pipeline prefixes and all preceding references to the queried keys. Each live
trace separately preserves its actual generated deadlines.

| Operation | Command | Deadline source / nearby work |
| --- | --- | --- |
| 1526 | `PTTL et:s:28:37b3577a50660a7f7dc658feabe6c5fe53` | Batch 1472–1535; MSET 1491, EXPIREAT 1492 (`floor(future_ms/1000)` seconds); KEYS 1521 and seven-key EXISTS 1525 |
| 2910 | `PTTL et:s:23:2c57d06537cb90580459a716b6b8cb20c4` | Batch 2880–2943; GETEX PXAT 2766 installs `future_ms`; PEXPIREAT GT 2878 names the same deadline; KEYS 2882, SINTERSTORE 2896, MGET 2903 and RENAME 2908 precede it |

The deadlines are a month in the future, not crossing expiry at these queries.
Hash-field expirations at deadline 1 exist in the chunks, on other hash keys;
the queried objects are strings. Active expiry is disabled by operation 0.
The stream contains no INFO, MULTI, EXEC, WAIT, DEBUG SLEEP, or notification
configuration/subscription. It ends by restoring active expiry.

Static ranking before live timing:

1. Existing cross-shard/store-walk scheduling or external scheduling delay:
   reachable (`KEYS` uses bounded scans and retry queues).
2. Owner-reference initialization: no ordinary-dispatch route found. Parser
   calls `multi_dispatch_entry` only for transaction commands or an existing
   MULTI session (`src/core/io_loop.h:3744`). `multi_dispatch_started` is called
   on final EXEC publication, after the transaction's time cut; the guard adds
   no timer, sleep, retry or deadline.
3. `no_multi`: checked only after requiring an active MULTI session
   (`src/cmd/multi.inc:1715`); metadata and ordinary dispatch source are
   unchanged from frozen PRE.
4. Subexpiry census: ordinary census is selected only by `Kind::DatabaseInfo`
   (`src/cmd/scatter_engine.inc:3342`), as is the EXEC census
   (`src/cmd/multi.inc:2165`). It is not part of KEYS or hash expiry.

## Client timing and server profile

`docs/at15c/trace_differ.py` executes the unchanged harness AST and wraps only
`conn`/`read_reply`. It retains every send and top-level pipelined reply's
monotonic and realtime start/end timestamps and raw bytes. Generators, 64-op
batches, read order, equality comparisons and exit statuses stay unchanged.
Client read completion is not server execution time: replies are buffered and
the harness reads target before oracle. `deadline - PTTL` independently yields
each server's millisecond command time cut, which is compared with the send
and read bounds. No clock tolerance is widened.

The separate focused replay owns fresh listeners at the wrapper's geometry.
POST uses `perf record -C 112-119 -g --call-graph dwarf,8192 --switch-events
-e cycles:u -F 999`. The first capture used perf's default clock; its aggregate
report is usable, but it is not silently aligned with client CLOCK_MONOTONIC.
The second capture explicitly uses `--clockid mono`. A further warmed capture
also waits for perf's `enable` acknowledgment before sending the stream.

| Separate timestamped replay | delta 1526 | delta 2910 | Batch send → PTTL read 1526 / 2910 |
| --- | ---: | ---: | --- |
| POST trace 1 | −5 ms | −8 ms | 5.141 / 8.879 ms |
| POST trace 2 | −8 ms | −8 ms | 8.179 / 8.873 ms |
| POST trace 3 | −5 ms | −9 ms | 7.064 / 8.885 ms |
| PRE trace 1 | −4 ms | −6 ms | 4.148 / 5.923 ms |
| PRE trace 2 | −4 ms | −5 ms | 4.828 / 4.857 ms |
| PRE trace 3 | −2 ms | −2 ms | 3.510 / 3.905 ms |

Only operations **1526, 2910 and 3481** return a positive PTTL in this seed's
entire 4,426-command stream. The other PTTL replies are exact negative
sentinels. This explains why time-sensitive failures repeatedly select the same
two positions without demonstrating a commit-specific path.

Target/oracle batch-send skew in the six trace windows is only 11–44 µs.
The millisecond differences are real differences in the servers' command time
cuts, not milliseconds spent between the two client sends. Blocking client
reads accumulate around COPY 1507/2894, SINTERSTORE 1515/2896 and RENAME 2908,
before the PTTL queries. Both arms show that pattern. Buffered paired reads
mean the oracle's later client read timestamp does not imply later execution.

The first CPU profile is heavily contended: 89.13% of sampled cycles are in
compiler processes, 7.39% in assemblers, 2.47% in POST. POST's aggregate profile
contains ordinary scatter preparation/execution, bounded store scans and fused
scheduling. In the second profile all three unchanged POST legs pass, with
the two send-to-read windows between 0.346 and 0.534 ms. Aligned stacks and
switch records are in `profile-windows/profile-post-mono`. Detailed warmed
failure-window attribution is pending.

Separate diagnostic controls replace **only** those two PTTL requests with
PEXPIRETIME, retaining the generated stream and comparison machinery. All
three controls on each arm pass, and all twelve query pairs equal the exact
known deadlines (not merely each other). These are labelled controls, not
substitutes for any unchanged full replay or a change to the gate.

## Source-aware bisect

`docs/at15c/commit-inventory.json` inventories all sixteen lane commits by
`src`, Makefile and third-party tree identity. The frozen PRE is `61a9ab20f`.
AT15b has two production-changing commits: `bb5b461ee` and `76568a8fc`; all
seven later commits retain `76568a8fc`'s production tree. The first commit
names `hash_ttls_of`, while the follow-up uses the declared `hash_ttl_slot`.
The isolated builder links candidate trees under
`build/at15c/bisect-<sha>/tomokv` from frozen objects with per-input SHA receipts.

| Candidate | Build result | Three unchanged focused seed-7 replays |
| --- | --- | --- |
| `61a9ab20f` | Relinked; byte-identical SHA to frozen PRE | 3 PASS |
| `bb5b461ee` | SKIP: exact `multi_admin.cc` fails to compile, `hash_ttls_of` undeclared | Cannot run an unbuildable revision |
| `76568a8fc` | Relinked; byte-identical SHA to final POST | 3 PASS |

The intermediate skip is an observed compiler result, not a modified candidate.
The two valid candidate binaries are the same bytes that fail in the full or
contended traced replays. There is no stable good/bad boundary to label as the
first regressing at15b commit. No production patch was made.

## Outcome, validation and arms

The remaining work is completion of all six full wrappers and the warmed
profile. The evidence already disproves an AT15b-only PTTL defect; relative
PTTL comparison is sensitive to the real scheduling/execution time separation.
Absolute future deadlines prevent an expiry race but do not freeze relative
TTL, which each server correctly computes as `deadline - command_time_cut`.

All unchanged at15b directed proofs pass: multi/multidb seeds 7/19/20 in both
split and armed fused, live DEBUG in both modes, and all 40 invocations of
`docs/at15b/prove.py` (only its output directory is redirected). This includes
both formerly aborting survivor cases, multidb owners and required negative
controls. These are directed receipts, not a green whole-matrix claim.

The unmodified `tools/lbstall_artifacts.py compare` reports **742/742**
namespaced and **741/741** db0 selected bodies raw-identical and identical
after relocation resolution against frozen PRE. GET/SET/parse/dispatch remain
raw-identical. No production, harness, layout, or gate-count edit was made.

| Arm | Path | SHA-256 |
| --- | --- | --- |
| Frozen PRE | `build/at15b-pre/tomokv` | `ef4ff8935edf5d222b70299615e5f99a041e41f370594fc88e2cc691ecaad49a` |
| POST | `build/tomokv` and `build/at15c-post` | `d3723e11796bbcd87b0156d4b1690a3008f7702bc27b6c42724c0b3ff7ee1487` |
| PAD-A | `build/at15c-pad-a` | `926e0e9c5f0405951746cc1c6d808de5a334fd3a5c0cc5ff87c0bfcde7d1da52` |

PAD is **kind A: behaviour twin** using the same at15b builder and unchanged
PRE objects with 256 unreachable NOP bytes. PRE `.text` is 7,794,684 bytes;
POST and PAD-A are 7,794,940. This controls aggregate text size, not individual
function placement or the cold database statistics layout. The hashes remain
identical to the corresponding at15b arms.

No gate row was added or removed; EXPECT counts require no change.
