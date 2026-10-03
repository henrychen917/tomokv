atomfix3 — correct the SADD reply expectation

Worktree/branch: `/home/user/Projects/cx-atomfix` / `cx-atomfix`.
Launch HEAD: `68973875b324de69ff541c70b8e6e9114fd4b2cd`.
First operation fetched and merged `origin/cpp` at
`068fdb816d63d9adf4bbfd2aa5a11d57cd7c4615`; merge commit `ee2516276`.
The only conflict was EXPECT_QUICK/EXPECT_FULL; their launch values, 458/475,
were preserved. The mandatory merge imports the upstream ktlsfix source, gate,
and label-fixture changes. This lane made no further edits to those files.
Harness correction: `bd448e68b`. Nothing pushed.

The live assertion now expects SADD to return 1 and RPUSH to return 2. All eight
serverless harness tests pass. Live validation remains with mainline: no server,
live battery, benchmark, or gate was run, and no build was needed for this Python
correction. Every executed check was pinned to CPUs 112–127.

Diagnosis and reply audit

The supplied `atomfix-gate2-atomic-plain-0.txt` records the successful production
unit followed by `racing destination write acknowledged: got 1, wanted 2` at
`tests/atomic_plain.py:181`. SADD reports newly added members
(`src/cmd/t_set.cc:751`, `:779`), whereas RPUSH reports the resulting list length
(`src/cmd/t_list.cc:430`, `:437`). The destination already contains `base` and the
competing command adds `kept`, so the respective replies are 1 and 2.

The change is one live line at `tests/atomic_plain.py:181` plus its existing
serverless fixture at `:439`, which had duplicated the erroneous SADD reply.
The AT1 data assertion at `:185` is unchanged: sorted destination members must
equal `[base, kept, move]`.

| Path | Reviewed expectation |
|---|---|
| Mover seed / destination EXEC (`:163`, `:168`) | One element in a fresh key: 1 / `[1]` for both SADD and RPUSH. |
| Source-removal probe (`:176`) | SISMEMBER returns 0 after `move` is removed; LLEN returns 0 after the only list element is moved. Handlers: `t_set.cc:803`, `t_list.cc:513`. |
| Mover reply (`:183`) | SMOVE returns 1; LMOVE and RPOPLPUSH return `b"move"`. |
| Blocking seed / wake (`:199`, `:216`) | Seed EXEC returns `[1]`; after seed removal, RPUSH of two elements returns length 2 and ZADD of two new members returns added count 2 (`t_zset.cc:1234`). |
| Blocking result (`:224`) | BLPOP/BRPOP return key/member; BLMPOP returns key/member-array; BZPOPMIN/BZPOPMAX return key/member/score; BZMPOP returns key/array of member-score pairs. |
| Blocking survivor (`:228`) | Exactly the unconsumed element remains, including the reversed choice for BRPOP/BZPOPMAX. |

No other instance of the added-count versus cardinality mistake was found in
these mover/blocking paths. Boot verification remains CONFIG GET only. No
mutability, server behavior, layout, or performance change is introduced by the
correction. The lane's diff after the merge contains no `src/` changes, and does
not touch io_loop.h, wb.h, or reorder.cc; no writeback witness is triggered.

Proof and negative controls

```text
taskset -c 112-127 python3 tests/atomic_plain.py --self-test
Ran 8 tests in 0.036s
OK
```

Transcript: `build/atomfix3-self-test.log`. The existing test suite exercises nine
positive race fixtures and 24 missing-witness cases, in addition to boot, cleanup,
fatal-error and retry controls. `test_unentered_window_fails_after_four_fresh_attempts`
still requires failure after four fresh attempts and forbids a PASS. A missing
probe, pending-operation witness, held-EXEC witness, or commit-window counter
cannot be skipped or accepted. Data/reply/counter failures are never retried.

Two throwaway copies under ignored `build/` were run only with `--self-test`, on
112–127, with socket creation forbidden by the harness:

```text
build/atomfix3-old-reply.py: exit 1
AssertionError: racing destination write acknowledged: got 1, wanted 2

build/atomfix3-lost-member.py: exit 1
AssertionError: AT1: SMOVE preserves the acknowledged destination write: [b'base', b'move']
```

The first restores only the old live expectation while keeping the corrected
fixture. The second keeps the correct acknowledgement and removes `kept` only
from the simulated final members. Logs: `build/atomfix3-old-reply.log` and
`build/atomfix3-lost-member.log`. These are harness negative controls, not runs
of an old server. The real old-code AT1 oracle is the membership assertion, not
the acknowledgement count: an acknowledged write may return 1 correctly and
still be destroyed by the later stale clone. A PRE run failing on setup or a
never-entered window is not a valid lost-update control. The frozen production
negative-control results remain documented in `MEASURE-REQUEST-atomfix2.md`;
they were not rerun here. The supplied atomic-1 live PASS is prior mainline
evidence, not a fresh result from this lane.

`git diff --check` passes. No requested data assertion, stale-cut check, window
requirement, or retry bound was weakened.

Gate budget and exact mainline commands

This correction adds/removes zero rows and changes no labels. The two existing
`plain-write lost updates (atomic 0/1)` rows are emitted by `job_debug` at
`tests/gate.sh:1698` and collected at `:2905`, before the quick exit at `:2980`.
The incoming three NET2 rows are collected by `collect_job tls` at `:2930`, also
before that exit. Therefore the merged tree needs **461 quick / 478 full**:
launch 458/475 plus the three upstream NET2 rows, equivalently upstream 459/476
plus the two existing atomfix rows. The merged label fixture contains 478 labels;
it was only auto-merged, not edited by this correction. EXPECT_* remains at the
launch values **458/475** for the maintainer to reconcile.

Mainline only, on its scheduled quiet box, after reconciling that row budget:

```bash
cd /home/user/Projects/cx-atomfix
GATE_CORES=0-7 GATE_RATIO=6:2 tests/gate.sh iteration
```

The gate's two debug boots use `--shards 16 --ratio 6:2 --atomic 0|1
--enable-debug-command yes --key-lb 0 --client-lb 0 --flip-auto 0`. For an already
running isolated boot with those flags, these are the exact battery invocations
(run only the invocation matching the boot's atomic mode and port):

```bash
taskset -c 112-127 python3 tests/atomic_plain.py 127.0.0.1 16399 --atomic 0
taskset -c 112-127 python3 tests/atomic_plain.py 127.0.0.1 16399 --atomic 1
```

Require nine witnessed races at atomic 0 and six at atomic 1. The standalone
boot/cleanup and frozen PRE commands in `MEASURE-REQUEST-atomfix2.md` still apply;
use this corrected script and the current row budget. No performance measurement
or PAD arm is requested.

`git diff 68973875b324de69ff541c70b8e6e9114fd4b2cd --stat` (includes the required
upstream merge):

```text
 MEASURE-REQUEST-atomfix3.md                   | 140 ++++++++++++
 MEASURE-REQUEST-ktlsfix.md                    | 244 +++++++++++++++++++++
 Makefile                                      |   9 +-
 docs/CONFIGURATION.md                         |  29 ++-
 src/cmd/t_server.cc                           |   3 +
 src/net/tls.cc                                | 142 +++++++++----
 src/net/tls.h                                 |  15 +-
 tests/atomic_plain.py                         |   4 +-
 tests/fixtures/nullrefresh-ledger-labels.json |  20 +-
 tests/gate.sh                                 |  39 +++-
 tests/gate_measurements.json                  |   8 +-
 tests/ktls_keyupdate.cc                       |  90 ++++++--
 tests/ktls_keyupdate_unit.cc                  | 294 ++++++++++++++++++++++++++
 tests/tls.py                                  |  28 +--
 14 files changed, 966 insertions(+), 99 deletions(-)
```
