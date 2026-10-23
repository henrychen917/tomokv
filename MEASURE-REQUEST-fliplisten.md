## fliplisten

Branch `cx-fliplisten`, based on `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`.
No push. Correctness work uses CPUs 48–63 only (servers 48–55, clients
56–63), ports 21800–21899, and builds with `-j16`. No throughput claim.

### Change and invariants

`src/core/fliplisten.cc` contains the listener protocol. The hooks in
`io_loop.h`, `server.h`, and `thread.h` use the existing FLIP stages and
role hooks. Generated R7 admission/control bodies are synchronized by
`tools/reorder_sync.py`.

* Before Planning, reserve fixed per-owner/listener storage and one pending
  descriptor slot per current RLIMIT_NOFILE value. Allocation failure refuses
  the request before a plan or connection ownership changes. No sidecar is
  allocated before the first FLIP.
* IoDrain initializes cancellation once per FLIP epoch, independently of the
  borrowed-listener SQ retry flag, and cancels every native/transferred accept,
  including UNIX. Terminal
  accept CQEs and cancel CQEs are separate fences. Successful paused or
  old-generation accepts become retained descriptors, outside the frozen Client
  set. They are never closed merely because the FLIP is live.
* The existing IoPrepare barrier registers each destination's actual kernel
  reference: epoll interest or an io_uring registered-file entry. A new listener
  for EX→IO has a surviving rollback owner registered **before listen(2)**.
  A failure before a socket starts listening can close that unused socket;
  an established listener never closes as a handover.
* ClientPrepare's existing ACK barrier precedes listener ownership publication.
  ClientCommit installs native views and drops obsolete epoll registrations.
  The same listening socket, accept/SYN queues and TLS context survive. Listeners
  return to their physical home when it becomes IO again; the fixed table
  bounds growth across repeated FLIPs. Each transferred listener has independent
  tags, armed state and cancel accounting.
* ExInstall first runs the original exact frozen quota checks. An admission
  epoch then lets every resulting IO consume its retained list exactly once,
  rearm listeners, and acknowledge completion before Idle/ordinary dispatch.
  Rollback uses the existing rollback ACK barrier followed by the same admission
  handshake. No new FLIP phase or thread is introduced.
* The unique UNIX listener stays on its pinned owner. Existing TLS Client engine
  state remains pinned by the original plan/readiness checks. The fixture uses
  its established TLS connection as the FLIP issuer, whose owner is already
  pinned; an arbitrary TLS connection can correctly refuse a migration plan.
* Client/shard transfer, block-mask remasking, read-local replacement/QSBR,
  transaction ordering and the five-second precommit rollback deadline are
  unchanged. `flip_candidate_clients_ready` and `flip_drop_closing_planned`
  retain the flipfix closing-client protocol.

The state owns at most three slots per physical thread (384 fixed slots), and
retained descriptors reuse a bounded fd-indexed list. The shared pointer occupies
old Server tail padding: every existing field offset and all relevant sizes are
unchanged. `docs/fliplisten/layout.json` checks Server (108736), IoLoop (7144),
Op (336), Client (1984), ThreadCtx (1408), Shard (1440), FlatStore (944),
Rob<64> (192), AtomicEntry (144), and Config (624) directly from both binaries'
DWARF.

### PRE reproduction and new gate rows

Read in full: bugs5's IO4.3 design, control results and reproduction driver,
and its wave4 process driver. Rechecked `accepts_paused`, `on_accept`,
`admit_fd`, `quiesce_accepts_for_conversion`, `deactivate`, and
`cancel_prepared_activation` against this tree.

The original bugs5 BLPOP-held IoDrain experiment was reproduced on the frozen
PRE for both engines, atomic 0/1, both directions and completion/rollback.
All eight uring cases served **0/24** arriving connections. Epoll IO→EX completion
served **15/24** (atomic 0) and **18/24** (atomic 1); the other epoll IoDrain
cases served 24/24. That early hold does not reach the newly prepared EX→IO
listeners, so it cannot detect their rollback loss. Receipts and exact argv:
`docs/fliplisten/pre-controls/`, `reproduce-pre.log`,
`reproduce_pre.py`. Both 1s engines/atomic settings also reject unsupported
FLIP reshaping as before.

`tests/fliplisten.py` supplies four rows: each direction × outcome, each
containing **all four engine/atomic legs even on failure**. The production
binary is scheduled with gdb non-stop mode at the existing ExDrain publication,
after all listener preparation ACKs. Epoll arrivals must fill every real listener
queue; failure to open that window fails the test. EX→IO must expose exactly
the expected new listening sockets. Rollback is induced by expiring the existing
deadline before the irreversible commit.

Each row checks new TCP connections, TLS ClientHello arrivals, UNIX arrivals,
existing plain/TLS/UNIX clients, unique CLIENT IDs, exact INCR/ECHO execution,
exact accepted-connection deltas, PING replies, no unsolicited duplicate replies,
and bounded retirement. The established TLS client issues FLIP, respecting its
existing owner pin. All cohorts are freshly booted; bounded queue arming never
turns a missing window into a skip.

The existing two `FLIP close during FLIP` rows now also run strict connection
churn with `--flip-auto 1`, retaining both legs even if PRE fails one. A connector
waits through the existing FLIP deadline; EOF/reset/refusal is a failure.
The existing signal row now runs both SIGTERM and SIGINT in both engines,
with all four legs present even after a failure. The grep audit is `docs/fliplisten/test-assertion-search.txt`.

**DQ=+4, DF=+4.** `collect_job fliplisten` is line 4280, before the quick exit
at line 4343. Existing rows are strengthened without adding rows.
**Owner must change EXPECT_QUICK 685→689 and EXPECT_FULL 702→706.**
Neither constant was edited. The explicit label fixture equals all 706 source
declarations, with no missing or extra label. Its stock check currently refuses
only the owner-owned EXPECT_FULL mismatch; see `label-fixture.log` and
`label-fixture-source.json`.

### Verification receipts

The final production binary is the POST SHA recorded below. Its scored gate
receipts are archived under `docs/fliplisten/gate-receipts/`, with the exact
commands, selected jobs, per-leg output and partial ledgers in `proof/`.

| Gate job selection | Passed | Failed | Meaning |
|---|---:|---:|---|
| PRE new listener rows | 1 | 4 | Build prerequisite passed; all four scored rows detect loss |
| PRE existing FLIP jobs, uring default | 8 | 2 | Both strengthened arrival-churn rows detect loss |
| PRE existing FLIP jobs, epoll default | 8 | 2 | Both strengthened arrival-churn rows detect loss |
| POST broad uring selection | 375 | 0 | FLIP, feature batteries, TLS/UNIX, quota, churn, shutdown, persistence and units |
| POST broad epoll selection | 205 | 0 | FLIP, feature batteries, TLS/UNIX, quota, churn and shutdown |
| POST final touched FLIP job | 10 | 0 | Includes both signals in both engines and both close/churn legs |
| PRE R7 synchronization job | 1 | 0 | Generator check against the touched synchronization fixture |

All 16 direction/outcome/engine/atomic legs were executed on both PRE and POST.
POST served **914/914** arrivals with exact accepted deltas, unique client IDs,
PING, INCR/ECHO and no duplicate replies. Four individual epoll PRE legs already
pass (IO→EX rollback and EX→IO completion, each atomic setting); the four scored
rows each fail on their failing legs. PRE is not claimed to fail every leg.
The maximum established-client PING delay measured after FLIP replied was
0.002342 seconds in this debugger-controlled correctness run; this is a stall
witness, not a latency benchmark.

The final broad selections cover all FLIP jobs and production/sanitizer models,
both split/armed atomic feature batteries, both-mode network jobs, TLS and UNIX
listeners, client/quota/churn/shutdown jobs, and both-engine AOF/snapshot jobs.
The signal row was subsequently rerun through the final gate job on PRE and POST
with all four signal/engine legs present. Earlier fixture failures (an arbitrary
TLS owner pin and an asynchronous listener teardown between fresh boots) were
fixed and superseded; the final fixtures retain their live deadlines and
foreign-listener refusal. The separate cancellation-epoch defect found during
this work has its own failing-before/passing-after control below.

`tests/differ_gate.sh` ran its standard seeds **7, 19, 20, 23, 21**, both atomic
settings, against Redis 7.4.10. The oracle path and SHA-256 are in
`docs/fliplisten/oracle.json`. All four geometry/engine runs passed:

| Differential geometry | uring | epoll |
|---|---:|---:|
| Split 6:2 | 475 pass / 0 fail | 475 pass / 0 fail |
| Fused, read-local armed | 466 pass / 0 fail | 466 pass / 0 fail |

The stock script's ten SORT legs per fused run are **NOT RUN in fused mode:
the suite requires split 6:2**. They passed in both split runs. The split runs
also pass the standard 32-combination mode-equivalence check. No suite, seed,
assertion, watchdog or comparison tolerance was relaxed. Exact commands,
coverage and text traces are archived in `docs/fliplisten/differ/`.

`soak.py` ran for at least 120 seconds per engine with atomic=1, flip-auto=1,
concurrent value-verified MSET/MGET and fresh-client churn. Uring served
35,709 connections; epoll served 35,682. Each completed 480 manual FLIPs,
with no connection loss, duplicate client ID, value mismatch or shutdown error.
The automatic controller was enabled; no additional automatic FLIP completion
was observed. Detailed progress and accepted-count conservation are in `soak/`.

`make -j16 all` and every `job_production_units` target built successfully.
All **40 real outputs** passed `make -q`, including both outputs behind the
phony `mdbqsbr-live-arms` wrapper. See `production-final-build.log` and
`freshness.json`. All 40 outputs remain fresh after cleanup; see
`freshness-after-cleanup.json`.

The original bugs5 POST reproduction passes all 16 split direction/outcome/
engine/atomic cases: **384/384** arrivals answer PING, and established clients
answer after retirement. Four fused controls retain the documented unsupported
FLIP response. `post-controls/` retains exact commands and server logs. A prior
rerun collided with an old output directory; the driver now gives each run its
own directory. The failure is preserved in `post-repro-output-collision.log`.

`python3 tests/gates_test.py` passes **67 tests**, plus its nested **14-test**
battery. `gates-test-final.log` and its return-code file are the final receipts.
The final diagnostic-only gate edit was rerun as `pre-final-diagnostics` and
`post-final-diagnostics`: PRE is 8 pass / 2 expected churn failures, POST is
10 pass / 0 failures, with both signal/engine pairs present. The machine-readable
`docs/fliplisten/proof-summary.json` ties the final receipts to the frozen arms.

Every scored run uses `tests/gate.sh` with `GATE_ONLY_JOBS`, its own prerequisites,
slot allocator and row watchdogs. These are **partial job results**, not a full
gate receipt. No `iteration`, ABBA or NIC measurement was run.

The forced retry-flag/next-epoch control is `retry_epoch.py`. A real first FLIP
creates transferred listeners and old cancellation fences; the debugger then
schedules the shared retry flag at the second IoDrain entry. The previous POST
binary exceeds an eight-second client deadline in both atomic modes. The final
fix initializes cancellation by epoch, independent of this flag. This control
does not claim to fill the kernel SQ. Receipts: `retry-epoch/`.

Supplementary `stale_accepts.py` stops a real native accept callback only when
another successful accept CQE already follows it in the same kernel CQ. An
administrator on another IO initiates FLIP. The debugger reads and requires
IoDrain before releasing the held callback; ordinary retention cancels the old
generation, and the next real CQE enters the stale path. No descriptor, CQE,
generation or listener state is fabricated. Rollback uses the same existing
deadline control as the scored rows.

Both completion and rollback pass in atomic 0 and 1, observing **403 positive
old-generation CQEs**. All **1,376** sockets across the five fresh attempts are
served with unique IDs and exact accepted deltas. One attempt did not contain
the required batch and reran on fresh state; the maximum is four fresh attempts
per atomic/outcome pair, and absence of the witness fails. These observations
supplement the scored gate rows; they do not replace them.

The earlier ordinary-churn and pre-cancel-hold attempts observed no positive
stale CQE and failed their witness requirement. Holding every quiesce callback
also obstructed the debugger-driven run. Their receipts are preserved under
`stale-unwitnessed-epoch/`, `stale-held-before-cancel/`, and
`stale-held-every-pass/`; they are not counted as proof. Superseded candidate
receipts remain byte-for-byte in `stale-v1/`. The final batch control retains
the 6.5-second elapsed FLIP assertion.

### Binary identity and cost scope

`identity/` retains every changed linked body and its reason, full strict
instruction/encoding differences, the IO-only diffs, and the unmodified gate
normalizer's union inventory. Current POST: **609 changed groups / 8728 union
groups**, including 63 general hot groups. **All 12 selected GET/SET/MGET/MSET
groups are identical to PRE.** No identity difference is treated as a pass or
as a performance result. Compile-only per-unit budget trials and the selected
budgets are in `docs/fliplisten/budgets/`.

The native `arm_accept` bodies in both namespaces are strictly identical.
All **64** emitted loop variants have identical steady-pass instructions:
32 epoll variants are strictly identical; the other 32 differ only in the
callee of the pre-existing `accept_pending_` branch, with identical offsets,
widths, branch, argument setup, and all other instructions. No new sidecar load
or per-pass probe is executed on the ordinary path. `normal_paths.py` traces
72 successful native accept paths (namespace/template × kind × MORE);
none adds instructions. Cold paused/stale/default dispatch paths implement
retention and transferred listeners.

**Unmet literal cost requirement:** the exceptional native SQ-starvation retry
uses the existing cold pending branch but now calls a helper even with no FLIP.
It is not byte-identical or cost-free. The ordinary-path proof does not satisfy
a blanket zero-new-instructions claim for every exceptional no-FLIP path.
Transferred listeners also use the new accept dispatch after the FLIP retires;
that work is outside the proved native path. Retained admission runs within the
existing completion/rollback barriers. The source and
path audit establish the ordinary-path claim, not a latency/throughput result
and not equality of every exceptional path.

| Arm | Path | SHA-256 | .text bytes |
|---|---|---|---:|
| PRE | `/home/user/Projects/cx-fliplisten/build/tomokv-PRE` | `8958622f4591130d66fcf88df0e7787891e80bd4170694505ff9b641f7c5266c` | 7,747,526 |
| POST | `/home/user/Projects/cx-fliplisten/build/tomokv` | `191a4d962bf97c72a57c32c29324f5de6ed1e9a9ed6c788a6520d366247e5f29` | 7,885,353 |
| PAD-A | `/home/user/Projects/cx-fliplisten/build/tomokv-PAD-A` | `49a12a2ec184348e84cc4856cd71f62bb6a3357280d0740e65fab66808631966` | 7,885,353 |

**PAD type A — behaviour twin:** PRE objects plus unreachable tail NOP padding
match POST's aggregate .text size. Every PRE .text function address/size and GNU
property remains unchanged. It does **not** reproduce each POST function's
address or layout. This is an aggregate text-size control, not proof against all
layout effects. `pad.py`, `arms.json`, and `pad-relocations.json` describe it.
The strict PAD inventory keeps six residual groups (8635/8641 identical):
four relocated .rlfence trampolines and three relative jump tables in two other
functions. The separate relocation proof checks every resolved destination and
return address without weakening the strict comparison.

### Maintainer merit request: generic 14 cells

Run the exact `docs/fliplisten/generic14-cells.txt`, copied unchanged from
`docs/lbplanner/generic-cells.txt`, with the gate's own ABBA instrument on the
maintainer's quiet box. Arms are PRE, POST and the explicitly labelled PAD-A.
Run PRE/PRE null, PRE/POST, and PRE/PAD-A with identical geometry, engine,
offered load, data, warmup and run-order rules.

Keep a PRE/POST table for every cell with rate at matched offered load, cycles/op,
instructions/op, IPC, and the existing depth-one latency score. The cells cover
GET/SET p32/p8/p1, MGET p8, 1-KiB GET p32, GET p128, armed GET p32, armed SET p8/p32,
and both read-local settings of the 9:1 mix. The deciding result is no
main-command regression under the existing merit rule. Instructions and IPC
explain the rate/latency verdict; they cannot replace it. PAD-A controls only
aggregate text growth. These measurements are **NOT RUN: maintainer-owned**.

The full `tests/gate.sh iteration` is **NOT RUN: maintainer-owned**.

Completed uncommitted build intermediates were removed after preserving text
receipts (`cleanup.json`). PRE, POST and PAD-A remain in `build/`; final SHA-256
checks match the table above, and no lane server or listener remains running
(`final-state.json`).

Readable GDB logs have prompt-only trailing whitespace removed; their original
bytes and before/after hashes are preserved in `raw-gdb-logs.tar.gz` and
`receipt-normalization.json`.
