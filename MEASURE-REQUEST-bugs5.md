## bugs5

Base `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`, branch `cx-bugs5`. No push,
performance benchmark, measurement load generator, or full iteration gate.
Correctness geometry: server CPUs 96–103, Redis 7.4.10 on 104, clients 105–111;
builds restricted to 96–111 with `-j16`; ports 24800–24899. The gate planner
needs 16 declared physical CPUs: its server allocation includes unused CPU 104,
but each actual server slot remains exactly 96–103, 16 shards, ratio 6:2.

Implemented: CD4.2, SV4.3, RL4.1. IO4.3 is reproduced and requires the owner’s
protocol decision described below. DIFF-TRK-1 reproduces on both reference commits;
its causal-ordering mechanism is reported without a partial fix.
This is a correctness change; no throughput claim.

### Re-verification and fixes

The full finding rows were checked in `round4-read/REGISTER.md` and their
`cmd-data.md`, `cmd-server.md`, `read-local.md`, and `io-loop.md` reports.
The absent external `cx-wave4` path is replaced by its retained tracked receipt
at `docs/wave4/differ/epoll-armed-fused/climon-a0-s19-failure.txt` and the tracking
section of `MEASURE-REQUEST-wave4.md` in this checkout.

* CD4.2: `src/cmd/t_hash.cc::cmd_hscan` still used a compact array offset on PRE.
  Deletion skips `f3`; promotion skips multiple surviving fields. Return the
  complete compact hash with cursor zero, as Redis does, preserving MATCH and
  NOVALUES. SSCAN and ZSCAN already finish their compact forms in one call;
  both compact set forms and zsets are included in the new oracle witness.
* SV4.3: PRE `cmd_slowlog` looked up the current directory entry during GET.
  Entries now retain an immutable address/name version. Executor timing takes
  that reference before execution publishes Done, so subsequent rename or
  disconnect cannot race historical attribution. The cold stack owns the
  reference; every pre-existing loop/layout assertion remains unchanged.
* RL4.1: assignment of `(thread_id + 1) * odd_constant` replaces XOR with the
  same initial constant. Multiplication is a bijection modulo 2^64: all supported
  thread IDs receive distinct, nonzero states. The increment law is unchanged.
  The task summary says increments never fire; the audit and reproduction show
  the opposite: zero modulo every denominator makes **every increment fire**.
  PRE thread zero reaches 31 on all 64 keys after 300 lane reads each.
  The Redis logarithmic Markov model predicts mean 12.98748 and standard error
  0.20117 over 64 keys; the oracle run measured 12.96875. The witness requires
  every GET/MGET key read to be lane-served and visits every live IO lane.

`bugs5` is a new gate job with three rows, each containing all eight declared
1s/2s × uring/epoll × atomic 0/1 legs. Each new witness is followed by its existing
`concur`, `slowlog`, or `read_local_lane` control on a fresh boot. Every leg runs
even when the witness fails. Final own-interface receipts:

| Arm | Gate run | New witnesses | Existing controls |
|---|---|---|---|
| PRE | `build/gate-run.RmTd20` | 24/24 intended assertions fail | 24/24 pass |
| POST | `build/gate-run.WRc5qZ` | 24/24 pass | 24/24 pass |
| PAD-A | `build/gate-run.l7opBL` | 24/24 intended assertions fail | 24/24 pass |

Durable ledgers, server logs and per-leg output are in
`docs/bugs5/gate-receipts/verified-{PRE,POST,PAD-A}.{json,tar.gz}`.
All three witnesses also pass on the pinned Redis 7.4.10 oracle; see
`docs/bugs5/controls/oracle-*.log`. The LFU oracle uses the test's explicit
single-reader oracle arm, without TomoKV-only lane counters.

Collection is at `tests/gate.sh:4237`, before the quick-tier exit at line 4351:
**DQ=+3, DF=+3**, so the maintainer's constants should become **688/705** from
685/702. Neither EXPECT constant was edited. The independent label fixture and
source each contain 705 labels with identical multisets (including duplicates).
The full fixture guard remains red solely because EXPECT_FULL is still 702;
`docs/bugs5/label-fixture-source.json` records the exact diagnostic. Do not waive
that guard; the owner updates the counts.

Initial harness errors are retained separately and are not evidence of a server
defect. In particular, running the old slowlog battery immediately after the
threshold-zero identity witness consumed its new-escalation observation; the
final job uses the original fresh-boot precondition, with no assertion weakened.
No existing reply expectation was changed.

### IO4.3 — reproduced; protocol design for the owner

`docs/bugs5/controls/results.json` records both engines and atomic settings at
2s/6:2/16 shards. A BLPOP holds the existing IoDrain window; the report form of
FLIP must report moving before 24 new connections send PING. Closing the blocker
permits completion; retaining it forces the existing five-second rollback.
1s attempts record the explicit unsupported-FLIP error, both engines/atomics.

Uring drops all 24 arriving connections in both completion and rollback cases.
Epoll completion resets connections queued on a converting IO’s listener;
rollback on the original listeners serves them. Epoll completion lost 10/24
connections with atomic 0 and 5/24 with atomic 1 in the retained attempts. The
established PING resumes when quiescence ends; an additional stall beyond that
quiesce was NOT REPRODUCED in these eight completion/rollback cases (plus the
four unsupported 1s legs). The rollback quiesce itself lasts about five seconds. The old audit’s retry-on-dead-client mechanism has already
been changed by flipfix: `flip_candidate_clients_ready` skips closing pinned
clients and `flip_drop_closing_planned` removes them. Do not reintroduce that fix.

Current anchors: `accepts_paused`, `on_accept`, `admit_fd`,
`quiesce_accepts_for_conversion`, `deactivate`, and
`cancel_prepared_activation` in `src/core/io_loop.h`. Merely retaining positive
CQEs fixes only one loss: closing a SO_REUSEPORT listener also destroys its
kernel accept/SYN queues. Draining to EAGAIN then closing leaves an arrival race.
New EX→IO listeners created in reversible IoPrepare have the symmetric rollback
problem. Admitting directly into Client lists breaks the frozen plan/quota checks.

A complete design needs a listener ownership transfer in the FLIP protocol:

1. Retain accepted descriptors outside the planned Client set while dispatch is
   quiesced, including successful old-generation CQEs arriving during cancel.
2. Reserve surviving IO ownership of every listener that would otherwise close,
   including its kernel queues and TLS identity. Register that listener on the
   destination ring/epoll before acknowledging installation. Keep it open until
   process shutdown or a later acknowledged transfer; never close a listener as
   an ownership handoff. Multiple listeners per IO need independent accept tags,
   cancellation accounting, and bounded allocation prepared before commit.
3. Extend existing prepare/install/rollback acknowledgements to cover those
   resources and pending descriptors. On completion or rollback, admit deferred
   descriptors exactly once on the resulting IO owners, after quota validation
   and before ordinary dispatch resumes. Prepared listeners also need a rollback
   destination. Preserve the unique UNIX listener’s pinned-owner rule.

This can reuse existing phases and physical threads, but **changes what the
protocol transfers and acknowledges**. Under the instruction to keep the FLIP
protocol unchanged and stop at design when a change is required, no partial
accept-side patch is shipped. IO4.3 remains open; owner review of this resource
transfer extension is required. No IO4.3 passing gate row is claimed.

### DIFF-TRK-1 — reproduced on both commits; causal ordering remains open

Ten fresh epoll/1s/read-local=1/atomic=0 boots per commit, 16 shards, eight server
threads on CPUs 96–103, the unchanged `climon` seed-19 differential against Redis
7.4.10 on CPU 104, clients 105–111, ports 24800/24801. Each invocation compares
4,318 operations. These are correctness samples, not quiet-box measurements.

| Build | Runs with duplicate invalidations | Wilson 95% interval | Exact ck:10 / round 21 / mode 1 |
|---|---:|---:|---:|
| a7dfb9d23 PRE | 2/10 (20%) | 5.7–51.0% | 1/10 |
| 8656f9fa9 HEADLINE | 3/10 (30%) | 10.8–60.3% | 1/10 |

Raw failures and successes are in `docs/bugs5/tracking-controls/`, with the
summary in `tracking-statistics.json`. This small sample establishes recurrence
on both commits; the overlapping intervals do not establish a rate difference.
It is not solely a notifyorder regression.

A throwaway instrumented PRE (no production tracking source changes) reproduces
the exact mark on its first traced run. `docs/bugs5/trace/transitions.txt` and
`trace-1-server.log` show this order:

1. GET registers a pending read for ck:10.
2. An older SET's delayed notification arrives while that read is pending
   (already Done but not retired); the pending-read invalidation path emits.
3. GET retirement enrolls ck:10 again in the completed-key tracking table.
4. DEL invalidates that completed entry, producing the second frame.

The mode-1 test issues SET, GET, then DEL; it has no expiry command. Thus the
specific duplicate is **pending-read enrollment across a delayed older write
notification**, not demonstrated lazy-expiry plus command-write duplication.
Current anchors are `src/cmd/tracking.cc:98` (pending registration), `:175`
(retirement enrolls the read), and `:369` (completed and pending invalidation).
The pending path does not consume the read's registration; retirement re-enrolls
it. Redis emits one invalidation for this transcript.

Blindly erasing the pending registration after the first frame would also erase
needed protection when a write actually overlaps the read. Correct handling
needs a causal distinction between pre-read notifications and concurrent/newer
writes. That is not a clear small deduplication change, so DIFF-TRK-1 is reported
with its reproduction rate and mechanism, as permitted by the task; no tracking
fix or passing gate row is claimed. The unmodified standard differential remains
a required, unwaived check and its failures are retained below.

### Binary identity and PAD-A

| Arm | Path | SHA-256 | .text bytes |
|---|---|---|---:|
| PRE | `build/tomokv-PRE` | `994f0e00be7db703746611046778145ae53dbf8a988c00bfaa600b2378e7a919` | 7,747,526 |
| POST | `build/tomokv` | `e514a979201f2d748e947c007ce5f8411794bb2d007f2ad6a832c6c2b141c588` | 7,760,246 |
| PAD-A | `build/tomokv-PAD-A` | `232c149b0f42f468837cf1a3fbd5b08aa7e6b527f5564d5307931aad8168a5ba` | 7,760,246 |
| HEADLINE | `build/tomokv-HEADLINE` | `676370c86990a4d0e99e1539500bd4346eb4a319a9d9f45ff11f3734504fa441` | diagnostic reference |

**PAD type A: PRE behaviour with POST's total text size.** `docs/bugs5/pad.py`
links rebuilt PRE objects with 12,720 unreachable tail NOP bytes. This controls
aggregate text growth; it does **not** reproduce each POST function's address or
size. All PRE .text function addresses and sizes and GNU properties are preserved.
Do not interpret a flat PAD result as proof against every internal layout effect.
PRE rebuilt from its archived source has 8,641/8,641 identical normalized groups
to the original PRE; its different debug-path hash is retained in `pad-identity.json`.

The strict PAD comparison retains six residual groups (8,635/8,641 identical).
The separate `verify_pad_relocations.py` proof checks all six: four branches to
relocated `.rlfence` trampolines return to the identical instruction, and three
relative jump tables in two functions retain every resolved destination. Exact
normalized instruction/encoding differences and the independent proof are kept
in `pad-differences.*` and `pad-relocations.json`; the strict result is not masked.
The initial four-residual proof assumption failed and is retained separately.

POST has 162 changed groups among 8,665 in the union inventory. Every group has a
reason in `docs/bugs5/identity/changed-bodies.{json,md}`, and full strict instruction
and encoding differences are in `instruction-differences.txt.gz`. Twelve general
hot groups differ; **zero selected GET/SET/MGET/MSET command groups differ**.
All existing layout assertions pass; `SlowlogCapture` and the executor/fused loop
sizes are unchanged. The discarded attempt to enlarge the capture was caught by
the build's existing assertions and corrected to a cold stack reference.

Per-unit IPA budget re-derivation was tried in both namespaces for t_hash,
genthread, rl2s and main: 16 PRE/POST baselines plus three derived candidates for each of the eight units,
40 trials total. `docs/bugs5/budget-trials.json` records
every compile and identity result. Hash candidates worsened differences and
introduced hot differences; main candidates tied; rl2s and genthread candidates
sometimes reduced one non-command difference while others worsened. Existing
budgets are retained because the common command bodies already match and an
identity improvement alone is not a merit result. No identity mismatch is treated
as a reason to stop or to claim a performance outcome.

The slowlog change intentionally adds immutable identity ownership on connection
registration/rename and a directory lookup/reference on armed per-op executor
capture. Threshold zero and the armed timing path may therefore cost more. The
maintainer should judge this along with compiler/layout effects; correctness
proof does not establish zero performance regression.

### Validation receipts

Final results of the remaining broad jobs and standard differential matrix will
be recorded here when those runs finish. Completed so far: broad uring 245/245
rows, final `python3 tests/gates_test.py` 67/67 tests, and all 37 production unit
targets plus `all` and `mdbqsbr-live-arms` fresh under `make -q`.

### Maintainer merit request — generic 14 cells

Use the exact checked-in `docs/bugs5/generic14-cells.txt` (copied unchanged from
`docs/lbplanner/generic-cells.txt`) with the gate's existing ABBA instrument and
normal acceptance rules. Schedule on the maintainer's quiet box after correctness
review; this lane did not run those cells.

Arms: frozen PRE, POST and the explicitly labelled PAD-A above. Run PRE/PRE null,
then PRE/POST and PRE/PAD-A with identical affinity, engines, offered load, warmup,
client geometry, data and run order rules. Retain raw per-cell cycles/op,
instructions/op, IPC, rate at matched offered load, and the existing depth-one
latency score. The 14 cells cover GET/SET at p32/p8/p1, MGET p8, 1-KiB GET p32,
GET p128, armed GET p32, armed SET p8/p32, and both read-local settings of the
9:1 mix. Do not substitute instruction count for the rate/latency verdict.

The deciding result is no main-command regression under the existing merit rule,
with PAD-A used only within its aggregate-size scope. A candidate-only change
with flat PAD supports an effect beyond total text growth; equal POST/PAD motion
needs further layout investigation. Record PRE and POST values and deltas for
all cells. Also inspect armed slowlog timing separately if the owner needs to
quantify its correctness cost. There is no throughput claim in this lane.
