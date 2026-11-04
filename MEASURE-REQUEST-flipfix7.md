# FLIP connection liveness

## flipfix7

Branch `cx-flipfix7`, PRE `9d6ab5526f8fff0c8617e94cf20fa837e15ab0f8`.
Production source through `bcbe1650fd`; no push. **The connection fixes are
implemented. The universal signal-save deadline subitem is STOPPED, not fixed.**
The native, epoll, supplementary and standard differential selections,
PAD-A negative controls, and delivery closeout are complete. This is a
selected-job correctness receipt, not a full gate or iteration result.

| Item | PRE witness | POST result | Mechanism changed | Residual |
|---|---|---|---|---|
| IO5.1 late owned output | All 16 legs stuck in ClientInstall; releasing the subscriber releases FLIP | Final-source 16-leg campaign passed | Postcommit drain fences executor/ROB/borrow/barrier state; unsent owned output stays with its IO or travels under the existing serve pin | Universal deadline is not claimed |
| IO5.1 coordinator deferred frame | Real WB-owned invalidation waits behind the unfinished FLIP ROB slot | Deterministic fixture passes in both database configurations | Retained WB frames need not empty; a movable client's WB map still must drain | Both sanitizer engines passed the twelve new state witnesses |
| D18.3 blocked BLPOP 0 | 16/16 five-second IoDrain refusals; Blocking barrier and parked ROB | Final all-leg campaign passed | Retain on surviving IO; immediate precise refusal on converting IO; defer late blocking continuation publication until Idle | Blocked connections never migrate |
| D18.3 TLS | 16/16 five-second ClientPrepare refusals; owner-local TLS slot | Final all-leg campaign passed | Retain on surviving IO; immediate precise refusal on converting IO | TLS connections never migrate |
| D18.3 non-draining output | Socket output/send clause prevents initial or postcommit drain | Final all-leg campaign passed | Poll socket readiness only in FLIP control; retain full sockets on survivors, refuse converters, preserve actual borrowed output/release routing | No peer-drain deadline is added |
| SIGTERM/SIGINT during FLIP | SIGTERM ignored for 12 seconds after commit in all 16 legs; forced-stop restart recovered 0/1000 ACKs | All 32 final SIGTERM/single-SIGINT legs saved and reloaded 1000/1000 acknowledged keys | Particular output wedge removed; save cron and snapshot admission remain unchanged | **STOP: unconditional clean save after kShutdownSaveWaitNs needs a frozen handshake change** |

The complete PRE stage/clause table and raw snapshots are in
[pre-witness.md](docs/flipfix7/pre-witness.md) and its linked evidence. No production
change preceded those 64 fresh-boot witnesses. The directed runner adapts T01c
(late DEL notifications), T01d (signal/save loss), controllers T2 (BLPOP 0),
and net T10b (TLS) to the assigned eight-core gate geometry and all sixteen
2s legs; it does not run the audit scripts at their original ports/CPU sets.
Late-window retries use fresh
state, are bounded, and fail when the window never opens. PRE holds include
intentional witness/debugger time and are not performance measurements.

The stopped subitem is explained in
[shutdown-stop.md](docs/flipfix7/shutdown-stop.md). Merely running the save cron
during FLIP cannot guarantee a save: snapshot admission returns Busy during a
placement transition, owner capture is frozen after ExDrain, and ClientCommit
cannot roll back. The smallest proposed owner change is a shutdown-only stable
ownership cut: roll back reversible stages or finish the irreversible install,
then admit final capture with IO admission paused. A universally stuck install
needs owner-frozen capture at that cut, changing the frozen safe-point protocol.
This lane does not implement or claim that change.

### Connection ownership and controls

`src/cmd/flip_liveness.inc` owns the new cold decisions. Initial IoDrain still
waits for work touching executors. A clean movable client acquires its existing
serve pin immediately before that IO acknowledges drain; late owned replies can be retired
without pumping the old ring. Planning releases pins for non-movers. Transfer
preserves buffers and the frontier, removes any late source active pointer, and
only the installed destination resumes sending. A newly activated destination
refreshes its cached clock before enforcing inherited output timestamps.

Blocked, TLS and non-draining clients remain on surviving source IOs. Converting
sources refuse at IoDrain with an exact class-specific error before commit. The
existing plan's dropped-client accounting retains those survivor clients without
changing the placement algorithm. Parked blocking registries migrate with their
shards; a continuation arriving after the IO ACK cannot publish owner work until
Idle. Borrow releases from retained output are temporarily collected by the
existing indirect WB release callback, then routed by the installed owner map
only after all executors acknowledge ExInstall. Both the SPSC masks and their
ExDrain-to-ExInstall re-mask remain unchanged.

INFO exposes `flip_skipped_blocked`, `flip_refused_blocked`, `flip_skipped_tls`,
`flip_refused_tls`, `flip_skipped_output`, `flip_refused_output`,
`flip_late_output`, and `flip_output_transferred`. Skip counters count retained
class members when an IO acknowledges drain, including members the final plan
would not have selected. Refusal counters count the winning reason once per
episode. Directed rows require the
relevant counters, exact payloads and unchanged retained ownership. A late-output
row rejects initial-output skips as an unarmed window. Borrow rows require a
real outstanding borrow and its eventual release, including after shard moves.

The global dispatch pause, listener handover operations/order, five-second
precommit deadline, flipfix6 session semantics, txnorder and LB mover are
unchanged. No production time constant or runtime knob was added. All locked
layouts retain their existing static assertions. Both thread modes build.

### Proof and accounting

Directed witnesses disable key/client LB to keep their IO placement fixed;
existing LB and ordinary gate jobs retain their own settings. Candidate correctness
servers use CPUs 48-55, differential oracles 56-57, drivers 56-60, builds at most `-j13` on
48-60, and only ports 21000-21099. Every server/oracle boot has `LC_ALL=C`.
The selected-job planner accepts the assigned 13 physical cores for its existing
8-server/2-driver minimum; full/performance planning retains its 16-core minimum.
The gate job interface, geometry, row verdicts and expectation constants remain.

The final source passed 21 selected sanitizer/core/FLIP/LB/persistence rows.
The final candidate passed all three new live rows (plus release): **208 armed episodes from 219 fresh boots** (eleven bounded fresh-state retries) over all
16 two-stage configurations. Non-signal PING replies were exact PONGs; the
maximum observed PING wait was 53.270 ms and FLIP wait was 53.327 ms. All 32
signal episodes saved and reloaded every acknowledged key. These are bounded
correctness observations, not rate measurements. The gates harness passed
77 tests again on the final sources; all 61 make-q/identity checks passed.

The first sanitizer selection recorded 20 pass / 1 fail: the historical
state-only close fixture had never bound WB callbacks. The fixture now binds
that policy and drains the actual rollback FIFO before its original lifetime
checks; the corrected 21-row selection passed. The first strengthened live
campaign recorded 3 pass / 1 fail because read-local GET copies and never arms
a borrow. The corrected row uses the existing WATCH owner fallback, retaining
strict BORROWCOUNT assertions, and all legs passed. Both failures are retained
in their archived ledgers; no failed run is relabelled green.

The final 208-episode repeat passed. The first complete native regression selection
recorded 476 passed / 2 failed: stale writeback source anchors and the old reorder
body inventory. Both were corrected without changing POST. The follow-up gate
selection passed 144/144 rows, including all 326 required reorder bodies, 95/95
writeback clause outcomes, 16/16 path outcomes and four new failing source
mutants. It also repeats the four feature batteries with all twelve stream
memory assertions enabled; the earlier proof-only exclusion of those non-timing
assertions was removed. See [regression-controls.md](docs/flipfix7/regression-controls.md).
Epoll regression passed 195/195 rows; supplementary selections passed 82/82
(io_uring) and 69/69 (epoll). The final harness repeated 77/77 successfully.
[Verification inventory](docs/flipfix7/verification.md) links each receipt.
Both standard differential plans passed: **1,876 suite/seed legs and 32
mode-equivalence cells** total (938 + 16 per engine), with permanent seeds
7, 19, 20, 23 and rotating seeds 21/22 for io_uring/epoll. Final target freshness
passed 61/61 with all delivery identities unchanged. The existing borrow
capability job passed all eight mode/engine/lane legs plus release (9/9).
PAD-A reproduced all twelve required failures from seventeen fresh attempts,
with BLPOP in IoDrain, TLS in ClientPrepare and late output in ClientInstall.
Five unarmed late windows were retried on fresh state; raw snapshots and every
attempt are retained in the [PAD-A evidence](docs/flipfix7/pad-a-evidence.json).
The readiness-cut race and its deterministic negative/positive core witnesses are
documented in [readiness-cut.md](docs/flipfix7/readiness-cut.md). A peer becoming
writable between drain and hold preserves the original stationary decision.
The interrupted `gate-run.2J6phd` build was superseded by the coordinator fix and
is not counted as a completed proof run.

New rows: `collect_job flipfix7_units` at line 6556 and the three live collectors
at lines 6787-6789, all before the quick-tier exit at line 6853.
**DQ=+4, DF=+4.** `EXPECT_QUICK=1046` / `EXPECT_FULL=1063` are untouched;
owner values should become **1050 / 1067**. The existing signal row changes its
arming method because BLPOP no longer holds IoDrain; its saved-data and second
SIGINT assertions remain, with bounded fresh-state retry if no active FLIP is
observed. No row is retired.

All **80/80** production-linked GET/SET/INCR/MGET/MSET command-scope comparisons
add zero instructions (maximum delta 0, minimum -3744). They cover batch 1/32,
1s/2s, atomic 0/1 and both namespaces. The fixture counts owner/scatter execution,
with read-local disarmed, not network parsing or library code. See the full
[PRE/POST table](docs/flipfix7/command-counts.md). Source-derived GCC inline
budgets keep added cold control code from increasing these hot scopes; rejected
trials are retained. Negative instruction deltas are not throughput claims.

### Delivered arms and maintainer measurement request

| Arm | Path | SHA-256 |
|---|---|---|
| PRE 9d6ab5526 | `build/flipfix7/PRE` | `f8116b72a37b6a1200dc5681b7eec43d88828a07175f23202afc6d104907ef0c` |
| POST | `build/flipfix7/POST` | `d443b95831da51c41d8095a529d4e1d3db8ec3fd7dd802c1a3ef34926c47fd21` |
| PAD-A | `build/flipfix7/PAD-A` | `2037a766880f9e94b9bbfac5ba58e2fde9bfe564322f9e764cbb31bc5bd0daad` |

PAD-A is **(A) behaviour twin**: PRE liveness decisions with POST's exact ELF
text size/layout. Only one immediate byte per namespace changes in the cold
selector; all section layouts and symbol addresses remain identical. It disables
the candidate output holds, stationary exceptions, refusal classes and deferred
release/continuation guards. [pad-a.json](docs/flipfix7/pad-a.json) records the
patches; `tools/flipfix7_artifacts.py` regenerates and verifies them.

Maintainer-only measurement: PRE, POST and PAD-A using the gate's instrument on
the quiet box, normal ABBA/null controls and matched offered load. Run the
[14 generic cells plus explicit 2s GET/SET p1/p32 cells](docs/flipfix7/merit-cells.txt).
The p32 shapes deliberately overlap the generic set to preserve explicit null
labels. Rate at matched load decides regression; cycles/op, instructions/op and
IPC explain it. Judge repeatable differences against matched-null spread.

**No throughput claims.** Performance cells, `flip_saturated` (memtier load
generator), `atomic_floor`, ABBA and full iteration are **NOT RUN: maintainer-owned
by instruction**. `GATE_PROOF_NO_RATES=1` is set only on selected correctness jobs.
The LMOVE size-ratio timing subtest is also **NOT RUN** under this flag because
it is a performance measurement. Stream memory assertions remain enabled.
Correctness stall limits are not merit measurements. The standard differential
plan excludes SORT in armed fused mode because its fixture requires split 6:2;
these excluded legs are **NOT RUN**, not passes. Every standard seed/atomic SORT leg
passed in split mode on both engines. The upstream Tcl job uses its unchanged
passing-subset manifest; the whole upstream suite is **NOT RUN**.

Final `build/`: **14,933,804,855 bytes (13.908 GiB)**. An observed transient
peak of **18,528,082,510 bytes (17.256 GiB)** during earlier parallel unit links
exceeded the requested approximate limit. Completed proof data and redundant
derived binaries were pruned only after their hashes/results were retained.
Completed non-delivery unit debug sections were compressed with every allocated
section byte/address checked unchanged; delivery arms were never compressed.
All 61 target freshness checks pass, all arm identities match, the source diff
passes whitespace checks, and there are no remaining owned servers or listeners
on ports 21000-21099. See [delivery closeout](docs/flipfix7/delivery-closeout.json).
No push was performed.
