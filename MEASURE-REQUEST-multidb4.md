# multidb4 — concurrent SWAPDB connection resets

Worktree `/home/user/Projects/cx-multidb`, branch `cx-multidb`, base
`4460f0ad37c3f5692631ade7319eec7144b1e189`. Builds use CPUs 112–127;
serverless units use 112–119, preserving eight threads / 16 shards and the
split mode's 6 IO + 2 EX geometry. No server, listener, benchmark, gate, or
hardware-counter measurement was started. No performance result is claimed.

**Cause and correction.** `IoLoop::on_accept` closed successful accept CQEs
whenever `flip_dispatch_paused()` was true. `admit_fd` repeated the same close;
the epoll accept loop also used that pause. SWAPDB's three database stages use
this dispatch pause without changing any IO role. A first swapper could enter
the boundary while the second connection's accept completion was pending. The
second socket was then closed before Client allocation or command parsing. This
explains an EOF/reset without a send error, ROB failure, or server crash.

The round-3 failing log is
`build/gate-run.HOVgMq/jobs/multidb-1s-0-1/multidb.log`: reset at command #0 of
the concurrent two-SWAPDB pipeline. Its server shutdown report records zero
send errors and peer aborts. The older two EOF logs have the same externally
visible class; the live rerun remains the proof that all historical cases clear.

The admission predicate now samples one stage and admits during
`DatabaseIoDrain`, `DatabaseExDrain`, and `DatabaseRun`. Role-changing FLIP
stages and stale accept completions retain their rejection behavior. Newly
admitted clients hold their unconsumed commands behind the execution boundary.
There is no retry, timeout, dropped command, or changed battery tolerance used
to conceal a closure.

**Boundary safety found while validating admission.** The parser captured its
physical namespace before testing the dispatch pause. An IO that had already
acknowledged the drain could receive a new command, stamp the old map, and then
observe Idle after SWAPDB finished. Its later dispatch check admitted that old
stamp. The directed schedule demonstrates the serial-order violation: SWAPDB
publishes, a read of DB 1 finds no key, then the delayed SET writes physical DB 0
and makes the key appear in DB 1. That history permits neither serial position
of SET relative to SWAPDB.

The namespaced parser now checks the pause before capturing the map, as well
as at the existing dispatch sites. A parser admitted from Idle is protected by
the next boundary's IO-tail acknowledgement. A paused parser holds its frame
until it can capture the new map. The single-database specialization compiles
out this additional check. The settled design is retained: one physical-map
snapshot per admitted operation, SWAPDB under the execution boundary, and no
map-only publication. No object fields or layout locks change.

**Directed evidence.** The existing `multidb-boundary-unit` contains the new
checks; no public gate row was added.

* Before the admission fix, the socketpair/CQE test fails deterministically
  with `recv=-1 errno=104` and `SWAPDB must not close a newly accepted swapper`.
  Log: `build/multidb4-boundary-pre.log`. Test commit: `250259dbc`.
* The admission test forces all three database stages through both the accept
  CQE handler and direct fd admission, for 1s/2s and read-local 0/1 with atomic 1:
  24 windows. It verifies the socket remains open, both SWAPDB frames remain
  unconsumed/unpublished, and the new swapper can begin its own boundary after
  release. Disconnect cancellation and all role-changing FLIP stages are
  checked. Socketpair reads use epoll; no listener or io_uring queue is opened.
* With the admission fix alone (`c933ebdff`), the stamp/publication schedule
  fails at `SET must use the post-swap map after the intervening empty read`.
  Log: `build/multidb4-stamp-pre.log`. The test interposes the real stamp only
  in its own translation unit; it executes the real parser and owner SET.
  Both modes require exactly one swap release, one map capture, one dispatched
  and executed SET, and the intervening read. Missing arming is a failure.
* The prior four-writer/p32/32-epoch boundary schedules remain in the same unit.
  `tests/multidb.py` still requires both live swappers to complete 128 swaps and
  the concurrent reader to run. `tests/multidb_serial.py` is unchanged.

**Validation completed.** Release builds of both compiled database variants
pass with the existing Makefile and flags. The expanded boundary unit passes
all eight grouped checks, including all 24 admission windows, both forced
stamp/publication schedules, and both 32-epoch delayed-writer schedules. The
multidb unit passes its five groups (including both representations' locked
sizes, armed/unarmed records, ownership, and native persistence). All eight
core-concurrency cases pass: watch, lifetime, drain, route, lbshard, snapshot,
config, and notify. The core test translation unit uses its existing ASAN/UBSAN
recipe; its linked production objects are release objects. The unchanged
serial-order oracle self-test and `git diff --check` pass.

Logs and receipts: `build/multidb4-final-build.log`,
`build/multidb4-boundary-final-build.log`, `build/multidb4-boundary-post.log`,
`build/multidb4-multidb-unit.log`, `build/multidb4-checks.json`,
`build/multidb4-core-concurrency-unit-*.log`, and
`build/multidb4-serial-self.log`. The only sockets used were local socketpairs
in the directed admission unit. Live boots and the gate remain for mainline.

Code commits are `250259dbc` (accept regression), `c933ebdff` (admission fix),
and `495155a8f` (stamp/publication fix and directed schedule).

**Frozen arms (SHA-256).** Paths are relative to this worktree. POST was built
from runtime commit `495155a8fff6cf513bb71e2e4459c3f54916aeb2` and is byte-identical
to the default `build/tomokv`. PRE is the round-3 binary at the task base;
`make all` confirmed it was current before editing, and its digest matches the
frozen round-3 POST.

| Arm | Artifact | SHA-256 |
|---|---|---|
| PRE (round 3) | `build/tomokv-multidb4-pre` | `81a7f413a66f593557d377166b0e4ebd7f0dfd66a4aee01324b59a9b1f727951` |
| POST / default | `build/tomokv-multidb4-post` | `35135cde51d8de0bd4da4a798e0a8f9e8948ff758b1ecc944c1c432aad632f49` |
| PAD, kind A | `build/tomokv-multidb4-pad` | `59aa7da1829800fa126b05e9b544533370c27cb7c29918fcafd4439c867a9973` |

**PAD kind A: behaviour twin, scoped to default DB-0 traffic.** PRE's
single-keyspace behavior is selected in the candidate's exact ELF layout.
The established offline tool changes only three bytes in the cold boot
selector to force the single-database variant. It verifies identical sections,
symbols, and all other bytes; receipt: `build/multidb4-pad.json`.

POST with `--databases 1` already selects that same variant, so POST and PAD
have identical operation bodies and default behavior. This is a degenerate
control, not independent separation of mechanism and layout costs. It cannot
excuse a POST/PAD regression against the reference. Use POST for multidatabase
correctness; PAD is not a `--databases 16` correctness arm. No inverse-control
PAD is claimed. Recreate it without running a server:

```sh
taskset -c 112-127 python3 tools/multidb3_artifacts.py pad \
  build/tomokv-multidb4-post build/tomokv-multidb4-pad
```

**Gate accounting.** `tests/gate.sh` is unchanged. The expanded unit remains
the row at lines 1303–1308, collected at line 2685. The eight live multidb jobs
are collected at lines 2784–2788. Both are before the quick-tier exit at line
2813. No row is added or removed: **EXPECT_QUICK=438, EXPECT_FULL=454**.

**Maintainer handoff.** First rerun the live multidb and serial-order cases at
`--shards 16 --ratio 6:2`, eight cores, `--databases 16`, especially
1s/read-local 0/atomic 1, 1s/read-local 1/atomic 1, and 2s/read-local 0/atomic 1.
Keep the two 128-swap connections and concurrent MGET reader. Run the usual
`tests/gate.sh iteration` before accepting the candidate. No live-gate pass is
asserted here.

Recheck **h05 and h07 only**, using the gate's existing ABBA instrument, pins,
offered load, population, client count, durations, and rung decisions. Use the
same v7/reference arm as round 3 against POST and against PAD; the frozen
round-3 PRE is also available for a direct round-4 regression comparison. POST
and PAD use `--databases 1`. Retain the instrument's matched null/control,
rate, cycles/op, instructions/op, IPC, and spread diagnostics. The decision is
preserving the established DB-0 null at the matched load under the instrument's
existing acceptance rules, with no tolerance changes or new gain claim. Append
the results as `MEASURE-RESULT` in this worktree.
