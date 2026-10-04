Lane lbplanner-fix — 2026-10-04

**The serverless timing regression is reproduced and fixed. Mainline episode
measurements and the live gate remain pending.** Worktree/branch:
`/home/user/Projects/cx-lbplanner`, `cx-lbplanner`. Launch was `6c9cb4b85`.
The first fetch/merge of `origin/cpp` reported already up to date at
`241f8b8f62f8d18c761762df66ecf9803d725ff5`. Instrumentation was committed as
`726358e70`, before the fix; production code and receipts are in `06baef67b`.
Nothing was pushed. Builds, units, TSan and instruction tracing used CPUs 112–127.
No server, memtier, benchmark, or gate was started.

The three proposed timing mechanisms are verified

The fixture at `tests/lbplanner_unit.cc:72` starts with a real outstanding
executor completion, an empty ROB, and 128 buffered PINGs. The split geometry
is the gate's 16 shards / 6 IO + 2 EX; fused also has eight owners. A peer thread
holds the real shape mutex. Unit-only pthread wrappers count failed try-locks;
they release the holder when a tail reaches the existing commit/refusal mutex,
or after the requested number of undecided tails. Thus the test measures the
pass of the readiness decision, without pretending mutation can complete while
another thread permanently holds its mutex. It starts fresh for every case and
fails if the readiness condition or contention never arms.

These results are identical in 1s and 2s. Each table entry describes one drain.
PRE is compiled from frozen `cd02ecbab` source; POST1 is the launch mechanism.
The source/destination failure columns count actual failed mutex attempts.

| Arm / case | Source failures | Destination failures | ACK-wait passes | Decision pass | Reason / completed moves | Bytes parsed before first tail |
|---|---:|---:|---:|---:|---|---:|
| POST1, busy, one held tail | 1 | 0 | 0 | 2 | Protocol / 0 | 896 (64 PINGs) |
| POST1, busy, two held tails | 2 | 0 | 0 | 3 | PassLimit / 0 | 896 |
| POST1, ready, two held tails | 2 | 2 | 0 | 3 | Destination / 0 | 0 |
| PRE, busy, either schedule | 0 | 0 | 0 | 1 | Executor / 0 | 0 |
| PRE, ready | 0 | 0 | 1 | 2 | no refusal / 1 | 0 |
| POST2 and PAD-A2, busy, either schedule | 0 | 0 | 0 | 1 | Executor / 0 | 0 |
| POST2 and PAD-A2, ready | 0 | 0 | 1 | 2 | no refusal / 1 | 0 |

The original POST also fails the new strict witness. Independent controls
separate the causes: restoring just the try-lock produces an Executor decision
on pass 2; moving just the snapshot back to the tail produces Protocol on pass 1
after parsing 896 bytes; restoring the premature budget charge charges one pass
to a busy client that was refused immediately. All three controls fail their
named assertions. POST2 charges **zero** budget passes to the busy cases and
**one** to the ready case's actual ACK wait. PRE/PAD charge one and two,
respectively, because their original actuator charges before checking readiness.

Evidence: [original POST](docs/lbplanner/fix/timing-post1.json),
[original strict failure](docs/lbplanner/fix/timing-post1-negative.log),
[PRE](docs/lbplanner/fix/timing-pre-final.json),
[POST2](docs/lbplanner/fix/timing-post2.json),
[PAD-A2](docs/lbplanner/fix/timing-pad2.json), and
[all controls](docs/lbplanner/fix/lbplanner-checks.json).

The fix and its line sites

| Site | Behavior |
|---|---|
| `src/core/io_loop.h:540`, generated `src/core/reorder.cc:774`; helper at `io_loop.h:1849` | Snapshot the pause ID once at pass start, before CQ callbacks or parsing. Per-connection gates continue to read only the private cache. |
| `src/core/io_loop.h:1865,1914`; `src/core/server.h:851` | The tail independently acquires the stage so it also sees publication during the pass. Source and destination copy the published move without a shape try-lock. |
| `src/core/io_loop.h:1955`; `src/core/lbstall.h:17` | Call the unchanged pass-budget function only after a ready source actually finds its destination unacknowledged. Busy predicates still refuse immediately; no lifetime, ROB, output or protocol fence is waived. |
| `src/core/server.h:833`; `src/core/lbplanner.cc:262,285` | Protect record lifetime across cancellation/republication, as detailed below. |
| `src/core/server.h:825,3342` | Make the coordinator atomic at its existing size/offset, since a new plan can publish it while an old drain tail finishes. |
| `src/core/lbplanner.cc:730`; `tools/lbplanner_pad.py` | Retain an empty PRE pass-start target. PAD retargets every new pass-start call as well as the original tail, monitor and parser sites, preserving its PRE cron storage. |
| `tests/lbplanner_checks.py:47` | One additional witness within the existing gate row, covering both modes, POST2/PAD-A2 and the three timing controls. |

A publication-lifetime issue exposed by TSan

The stage release/acquire argument publishes a record correctly, but alone does
not protect a delayed reader across a complete cancellation and replacement.
A serverless TSan schedule acquired ClientDrain for epoch 1, parked the reader,
called the real timeout withdrawal and IO consumer to publish epoch 2, then
copied the record. The naive plain-copy fix produced a data race against
`Server::lb_consume_plan` and exited 66:
[counterexample](docs/lbplanner/fix/naive-copy-tsan-race.log).

POST2 therefore registers a reader only in the cold ClientDrain snapshot/tail.
It uses lock-free atomic increments/decrements and validates the stage; it takes
no mutex and performs no retry. A sequentially consistent PlanReady publication
orders late entrants against the consumer's reader check. An active old reader
keeps the record immutable until its scope ends; a late entrant either reads no
record or acquires the replacement drain. The consumer leaves PlanReady pending
while a reader remains, returns immediately, and starts the new drain only after
the reader exits. PlanReady permits traffic and has no charged drain budget.
Holding the tail's scope through its decision also prevents a new epoch from
reusing the record midway through its readiness check.

`tests/lbplanner_unit.cc:402` covers both schedules. An active reader defers
exactly one attempted consumption; consumption succeeds after its exit. A late
reader safely sees record 2. Removing the reuse check fails the named witness.
The same TSan run exercises the coordinator publication/read. The reader counter
extends the already allocated cold `LbPlan` from 120 to 128 bytes; there is no
additional allocation, and both balancers off still allocate no plan or policy.

This is additional cold actuation work: two RMWs and a phase validation per read
scope while ClientDrain is active. It adds nothing to a per-connection gate.
Admission, gather/search policy, cadence, cap, ownership transfer and readiness
predicates retain their existing behavior. The live cost of the read scopes
belongs in mainline's episode verdict.

Receipts and verification

The instruction fixture executes pass start, N production parse gates, then the
tail, with the stage pinned Idle. Counts include its noinline fixture boundaries;
they are **not command instructions/op or a cycles/IPC result**.

| Connections/pass | PRE instructions | POST2 instructions | PAD-A2 instructions | PRE shared stage loads | POST2 shared stage loads |
|---:|---:|---:|---:|---:|---:|
| 1 | 73 | 82 | 87 | 2 | 2 |
| 32 | 848 | 516 | 893 | 33 | 2 |
| 4096 | 102448 | 57412 | 106557 | 4097 | 2 |

POST2 has one shared stage acquire for the pass-start snapshot and one for the
tail, with N private parse-cache loads. The extra-load control reports 3/34/4098
shared stage loads. Cold ClientDrain phase validation is outside this Idle
receipt. [Instruction sites and counts](docs/lbplanner/instructions.json) were
regenerated with `tools/lbplanner_receipts.py` and `tools/lbplanner_trace.cc`;
the frozen PRE adapter was refreshed with `tools/lbplanner_pre_receipt.py`.

| Check actually run | Result |
|---|---|
| `tests/lbplanner_checks.py` | Pass: handoff, record lifetime, all six handoff/lifetime controls, timing witness and three timing controls, PAD behavior, POST rejection of PRE behavior |
| Fully instrumented `build/lbplanner-unit-tsan`, ordinary and `timing` selections | Both exit 0, no TSan report; all implementation objects are instrumented, not just the driver |
| `build/signalacct-core-unit route` | Pass, including existing LB stalls, missing-ACK bound, shard progress, ownership and controller regressions |
| Frozen PRE timing fixture | Six cases pass |
| R7 envelope and stale-envelope control | Pass |
| PAD-A2 production/unit proofs | Pass, including six rejected identity mutations each |
| Layouts, source policy, ptrace load controls, shell syntax, diff check | Pass |

Commands, return codes and the actual 112–127 affinity are in
[validation.json](docs/lbplanner/fix/lbplanner-fix-validation.json).
[TSan handoff/lifetime](docs/lbplanner/fix/tsan-handoff.log),
[TSan timing](docs/lbplanner/fix/tsan-timing.log),
[route log](docs/lbplanner/fix/route.log), and compressed build logs are adjacent.

All eight locked sizes hold: Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. IoLoop remains 7144.
Launch `6c9cb4b85` and POST2 have identical Server/IoLoop member-offset and size
inventories in both namespaces. Historical PRE already differs from launch:
Server grew 108672→108736 (`tomo`) and 108288→108352 (`tomo_db0`), with its
query-buffer-limit field shifted 64 bytes by intervening mainline changes.
The refreshed receipt records that difference instead of asserting historical
PRE/POST identity: [layout comparison](docs/lbplanner/layout-comparison.json).

The measurement arms

Paths are relative to `/home/user/Projects/cx-lbplanner`. Use these pins for the
bench3 rerun; the earlier `build/tomokv-lbplanner-post` artifact remains historical.

| Arm | Artifact | SHA-256 | .text bytes |
|---|---|---|---:|
| PRE | `build/lbplanner-pre/tomokv` | `33f07418205817e93d5d759d4cab78480f77c5aa9fa51618dc89aa3e3828f8a2` | 7729345 |
| POST2 | `build/tomokv` | `1319f1b24a3eee45f328cbd0da008b71bdc128e46cffcc20e1b0579e07e20b92` | 7796224 |
| PAD-A2 | `build/tomokv-lbplanner-pad` | `278ae4376b8f82982bb6766bac9f4e1af0666ee68201feb763352b2d3d31dac6` | 7796224 |

**PAD kind A: PRE LB behavior with the candidate's exact text size/layout.**
Production POST2/PAD-A2 have identical complete tables of 10,279 functions,
identical section tables, and every byte equal outside the 234 approved
retargets: 96 pass starts, 96 tails, eight monitor calls and 34 parser gates.
Exactly 1,000 bytes differ. Function-table SHA-256 in both is
`3044a71f67d35a2ca19626c0b3676d7dce0773940db7be8a8991272e56b3b080`.
The new missing-pass-start-retarget control fails along with missing tail,
monitor, parser, moved-symbol and unrelated-byte controls.

Proofs: [production](docs/lbplanner/pad-a/proof.json),
[retarget inventory](docs/lbplanner/pad-a/planned-retargets.json),
[PRE source bodies](docs/lbplanner/pad-a/closure-proof.json),
[unit twin](docs/lbplanner/pad-a-unit/proof.json), and
[all artifact hashes](docs/lbplanner/SHA256SUMS).
No PRE/POST function-byte identity is claimed. PAD restores the legacy PRE LB
actuator, including its original record-reading behavior; it is a comparison
arm, and the new record-lifetime TSan proof applies to POST2.

Mainline measurement request and remaining limits

Use the instrument on `cx-lbplanner-bench3` and the unchanged mainline-03
client-skew **1s** stimulus: 64 hot connections, pipeline 128, IO owners 0 and 1,
213-second scored episodes, matched geometry, offered load, telemetry baseline
and arm ordering. Rerun PRE / PAD-A2 / POST2 over the paired repetitions. The
deciding quantities remain the deltas of Executor, Protocol, PassLimit,
Destination, completed client moves and `pending_ns_max` in INFO LB.

Acceptance: refusal mix within counting noise of PRE/PAD-A2; PassLimit **0**;
pending maximum within one source pass; completed client moves no fewer. Preserve
the existing rate/p99 and convergence criteria and the quiet-box comparison
protocol. Mainline also owns the original stable-load checks and
`tests/gate.sh iteration` before landing. No live timing, rate, latency,
convergence, or full-gate success is claimed here.

A drain published after a pass-start snapshot can still encounter work parsed
during that pass; its tail now decides immediately using the current predicate.
The fixture proves the before-pass publication case and removal of mutex-induced
pass deferrals. The live refusal mix, cold reader-counter cost and wall-clock
pending bound require the requested rerun. Unit pass numbers do not establish
millisecond latency or a performance gain.

The existing gate row is defined at `tests/gate.sh:1318`, collected at **3050**,
before the quick-tier block at **3202** and exit at **3206**. This fix adds an
internal witness to that row, so its shell-row count delta is **0 quick / 0 full**.
The inherited 490/507 constants are unchanged. `tests/gate.sh`, `tests/fixtures/`
and `tools/lb_episodes.py` have no changes relative to launch. Mainline retains
count/fixture ownership.

Reproduce serverless proofs only:

```sh
taskset -c 112-127 make -j16 all build/lbplanner-units build/lbplanner-unit-tsan build/lbplanner-trace build/signalacct-core-unit build/tomokv-lbplanner-pad
taskset -c 112-127 python3 tests/lbplanner_checks.py
taskset -c 112-127 env TSAN_OPTIONS=halt_on_error=1:exitcode=66 setarch x86_64 -R build/lbplanner-unit-tsan
taskset -c 112-127 env TSAN_OPTIONS=halt_on_error=1:exitcode=66 setarch x86_64 -R build/lbplanner-unit-tsan timing
taskset -c 112-127 build/signalacct-core-unit route
taskset -c 112-127 python3 tools/lbplanner_pre_receipt.py
taskset -c 112-127 make -j4 -f build/lbplanner-extra.mk build/lbplanner-pre-pass build/lbplanner-pre-timing build/lbplanner-launch-layout.o build/lbplanner-launch-layout-db0.o
taskset -c 112-127 build/lbplanner-pre-timing
taskset -c 112-127 python3 tools/lbplanner_receipts.py
```

The PRE fixture build uses the existing frozen `cd02ecbab` PRE objects. The PAD
builder independently verifies its complete inventory and never executes a
server ELF. Timing-control overlays depend on all copied implementation sources
and headers so later core changes cannot silently leave a stale control fixture.
