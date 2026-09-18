TomoKV lane aoffix, branch `cx-aoffix`, worktree
`/home/user/Projects/cx-aoffix`. Launch reference:
`8a5c0ed0da868c8ae77b7402896b1bf86a03a02f`.

Both defects are confirmed and fixed. The new S3 assertion failed on the
unmodified launch binary and passes on the candidate. P15's disabled path
now skips the shared sequence load and reply-gate call. **P15 instr/op numbers
and the full gate are pending mainline.** This lane ran no benchmarks or
hardware-counter measurements, and did not run the gate. No performance gain,
non-regression verdict, or 454/454 result is claimed without those results.

Builds used `taskset -c 112-127 make -j16`. All unit/self-test commands inherited
`taskset -c 112-127`; owned self-test servers used 112-119, eight threads and
16 shards, with `--ratio 6:2` in split mode. Fused mode rejects `--ratio` and
uses all eight threads for both roles. No server ran outside these self tests.

**S3 diagnosis and change.** `record_bytes` already creates the first chunk
and sets `AofFrameLargeBegin`. A mid-record seal in `emit` empties `build_`;
the next loop iteration incorrectly set LargeBegin again. The writer rejects
that continuation and `fail()` turns recording off, while ordinary writes can
continue succeeding. `emit` now creates continuation chunks with `make_chunk(0)`;
the first-frame flag remains solely at the record boundary. No new state or
layout change is needed.

The trigger in the task needed a qualification: ordinary large SET **values**
use the separate type-hook serialization loop, whose continuation flags were
already correct. The existing 70,000-byte value test therefore did not expose
S3. The new regression also writes a **70,000-byte key with a 70,000-byte binary
value**, forcing the broken `emit` key path and crossing multiple frames. Both
large records are checked after DEBUG LOADAOF and fresh-process AOF replay.
`aof_last_write_status:ok` is mandatory while waiting for AOF completion and
after replay; exact value replies and lengths join the existing keyspace
probes and DBSIZE check. The fresh-process self test requires replayed records,
different process IDs, and no standalone snapshot in the data directory.

The production fix is commit `488cd77ba`; the regression was committed first
as `345f297bc`. Before any production edit, the release binary was built from
the launch reference and frozen as `build/tomokv-aoffix-pre`.

Actual failing transcript, exit 1 (full output:
`build/aoffix-s3-pre.log`; server log:
`build/aoffix-s3-pre/2s/write/server.log`):

```text
$ taskset -c 112-127 python3 tests/aof.py --self-test build/tomokv-aoffix-pre --output build/aoffix-s3-pre --modes 2s
AOF SELF-TEST: mode=2s net-io=uring databases=1
  File "/home/user/Projects/cx-aoffix/tests/aof.py", line 506, in wait_for_script_aof
    assert_write_status(stats)
  File "/home/user/Projects/cx-aoffix/tests/aof.py", line 207, in assert_write_status
    raise AssertionError("aof_last_write_status: expected ok, got %s" %
AssertionError: aof_last_write_status: expected ok, got err

# From the owned server's log:
AOF error: AOF frame ordering or write failed
```

With S3 alone fixed, the same assertions and fresh-process checks passed in
both modes (`build/aoffix-s3-post-geometry.log`). An earlier self-test wrapper
attempt supplied `--ratio` to fused mode and correctly failed at boot; the
wrapper was corrected before that successful run. No assertion was weakened.

Final candidate transcript, exit 0 (`build/aoffix-post-uring-db1.log`;
repeated recovery lines omitted here):

```text
$ taskset -c 112-127 python3 tests/aof.py --self-test build/tomokv --output build/aoffix-post-uring-db1
AOF SELF-TEST: mode=1s net-io=uring databases=1
AOF SEND GATE PASS: waits=0 -> 692
AOF LARGE RECORD PASS: key=70000 value=70000 aof_last_write_status:ok
AOF BYTE-EXACT PASS: 54 static replies + live monotonic PTTL
AOF FRESH-PROCESS PASS: mode=1s
AOF SELF-TEST: mode=2s net-io=uring databases=1
AOF SEND GATE PASS: waits=0 -> 702
AOF LARGE RECORD PASS: key=70000 value=70000 aof_last_write_status:ok
AOF BYTE-EXACT PASS: 54 static replies + live monotonic PTTL
AOF FRESH-PROCESS PASS: mode=2s
```

The final candidate also passed both modes with `--net-io epoll --databases 16`
(`build/aoffix-post-epoll-db16.log`). Its send-gate waits advanced from 0 to 688
in 1s and from 0 to 667 in 2s. These are correctness witnesses, not performance
measurements. `tests/aof.py` now explicitly requires a positive counter delta
when `appendfsync always` is selected; the self-test wrapper verifies that
policy actually armed before running the battery.

**P15 diagnosis and change.** Both IO probes evaluated `posted_sequence()`
before reaching `reply_gate_ready`'s recording-disabled fast return. That
accessor is an acquire load of the sequence incremented by producers when AOF
is active. With AOF disabled the counter remains zero, but the original IO
paths still loaded it and called the out-of-line gate on every eligible pass.
Both probes now test the immutable, boot-latched `configured()` flag first,
the same configuration decision used to initialize EX's optional AOF pointer.
The disabled case adds no allocations and touches no AOF sequence. Enabled
operation retains the existing target, durable/written frontier, waiter and
error behavior.

The landed reference also contains a generated `r7_flush_ready` copy in
`src/core/reorder.cc`. `tests/r7shadow_sync.py --write` propagated exactly the
same guard there; its source-sync check passes. Without this necessary copy,
reorder-enabled paths would retain the defect. Commit `365cd35a8` contains
P15 and this generated update.

**DB0 assessment: semantics and layouts unaffected, not byte-identical IO.**
P15 changes no fields, namespace mapping, parser, store, command implementation,
database selector or database configuration. Both compiled database variants
receive the intentional IO optimization. The existing `multidb-unit` passes
all five groups, including DB0 legacy identity/decoder/binary keys/layouts/
armed reads, namespace isolation, native persistence, SELECT, MOVE, COPY,
SWAPDB and WATCH (`build/aoffix-multidb-unit.log`). The live self tests above
exercise `databases=1` and `databases=16`. No claim is made that the entire DB0
executable code is byte-identical.

**Frozen artifacts and PAD definition.** POST is the production source at
`365cd35a8`; subsequent tooling/report commits do not change its runtime.
Use the S3-only binary as **P15 PRE**, so the P15 comparison holds persistence
code constant. The launch PRE is retained for S3's negative control and the
combined change comparison.

| Arm | Artifact | SHA-256 |
|---|---|---|
| Launch PRE, S3 broken | `build/tomokv-aoffix-pre` | `e0c36caeccd8c864e9eb3df0f1c189a95e8dbed5b5ef2c0743b691607c94d10d` |
| P15 PRE, S3 fixed | `build/tomokv-aoffix-s3` | `a2e286501876bcf3c3f2a13e58834c837deeb709b0a754b0d15f3f8c80f12fd6` |
| POST | `build/tomokv-aoffix-post` | `d445a97353eeceedc4faf57b3e16abb6f3938b57918d7718c8c557ceb66db11e` |
| PAD, kind A | `build/tomokv-aoffix-pad` | `e9308fced99ef391245bff42d0d64f4b8b86d735fd5170fa9a22367f66658e99` |

PAD is **(A) behaviour twin: P15 PRE behavior with POST text size and layout**;
S3 remains fixed. The offline tool replaces each new configured-check/branch
with one unconditional jump to the original probe and eight unreachable NOP
bytes. This restores the sequence load and reply-gate call even with AOF off.
It patches all 82 compiled sites (41 per database variant), including the
generated R7 bodies. It verifies field offsets, instruction patterns,
original probe loads/calls, unchanged sections and symbols, and byte identity
everywhere outside the recorded patch spans. No production PAD knob is added.
The control executes one unconditional jump per probe; it is a behavior twin,
not an assertion of identical instruction counts to PRE.

P15 PRE `.text` is 8,215,293 bytes; POST and PAD are both 8,214,349 bytes
(POST minus PRE: -944 bytes). Exact POST/PAD layout, rather than total byte
count alone, is the control. No kind-B inverse control is claimed. The static
audit establishes removal of the disabled sequence access and call; it does
not substitute static instruction counts for measured instructions/op.
Receipt: `build/aoffix-pad.json`; tool commit: `91cd51772`.

PAD also passes the same large-record/restart self test in both modes with
`databases=1`, io_uring and `appendfsync always`
(`build/aoffix-pad-uring-db1.log`): send-gate waits advance 0 to 694 in 1s and
0 to 695 in 2s. This checks that the offline control remains executable and
preserves enabled-AOF behavior.

```sh
taskset -c 112-127 python3 tools/aoffix_artifacts.py \
  build/tomokv-aoffix-s3 build/tomokv-aoffix-post build/tomokv-aoffix-pad \
  --receipt build/aoffix-pad.json
```

**Measurement request, mainline only.** Run GET cells h05, h17, h07 and h23
with the gate's instrument, `appendonly no`, `databases=1`, 16 shards and
eight server cores (0-7); use load cores 84-111, reserving server siblings.
Keep the cell definitions, 512 clients, depth 32, population, value size,
warmup and measurement windows from the existing instrument. Split mode uses
6:2. h05/h17 cover ordinary fused/split IO and h07/h23 cover reorder-enabled IO.
Use one fixed offered rate per cell, chosen from PRE before comparing the
arms; record that rate and require matched achieved rate across arms.

Compare P15 PRE/POST in ABBA order, P15 PRE/PAD in ABBA order, and PAD/POST
in ABBA order on the quiet box. Keep the instrument's identical-arm control
and all raw samples. Report rate, instr/op, cycles/op, IPC and arm spread.
The decision is no POST instr/op or matched-load performance regression
against PRE, plus reduced instr/op against PAD supporting the removed-load
mechanism. PRE/PAD exposes layout/control overhead; do not attribute their
difference to the removed acquire load. If the effect is below the measured
resolution, report that explicitly rather than claiming a gain. Append actual
results as `MEASURE-RESULT` in this worktree.

| GET cell | P15 PRE instr/op | POST instr/op | PAD A instr/op | Verdict |
|---|---|---|---|---|
| h05 | pending | pending | pending | not measured |
| h17 | pending | pending | pending | not measured |
| h07 | pending | pending | pending | not measured |
| h23 | pending | pending | pending | not measured |

**Gate accounting and remaining acceptance.** No gate row was added or
retired, and `tests/gate.sh` is byte-identical to the launch reference. The
new assertions execute inside the existing AOF population row at line 1998
and restart row at line 2017, before the quick-tier exit block at line 2808.
Counts remain **438 quick / 454 full**; neither EXPECT constant was edited.
Mainline must run the requested command and obtain 454 rows, 0 gating FAIL:

```sh
taskset -c 0-111 tests/gate.sh iteration --server-cores 0-83 --load-cores 84-111
```

Release builds, Python syntax checks, `multidb-unit`, R7 source sync, and
`git diff --check` passed. The final release build log is
`build/aoffix-post-sync-build.log`. Final binary checksum:

```text
$ sha256sum build/tomokv
d445a97353eeceedc4faf57b3e16abb6f3938b57918d7718c8c557ceb66db11e  build/tomokv
```

Diff against the launch reference (including this handoff report):

```text
$ git diff 8a5c0ed0da868c8ae77b7402896b1bf86a03a02f --stat
 MEASURE-REQUEST           |  22 ++---
 MEASURE-REQUEST-aoffix.md | 214 ++++++++++++++++++++++++++++++++++++++++++++++
 src/core/io_loop.h        |  21 +++--
 src/core/reorder.cc       |  10 ++-
 src/persist/aof.cc        |   4 +-
 tests/aof.py              |  80 +++++++++++++++++
 tools/aoffix_artifacts.py | 131 ++++++++++++++++++++++++++++
 7 files changed, 452 insertions(+), 30 deletions(-)
```
