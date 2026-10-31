# FLIP transaction-session handover

## flipfix6

Branch `cx-flipfix6`, PRE `e32b04a445b056976abb308aa598e356fcbaae74`.
Resumed from `fe0f82542` under resume addendum 2. No push.

The conservative implementation is now applied. D18.1 carries the session and
accepts exactly its installed WATCH aliases. S2 on **any** source refuses at
IoDrain, leaving its state and original admission untouched. A pinned close
refuses a reversible FLIP before preparing cleanup. If the ownership commit
has already won, the existing pin holds cleanup until Idle; that edge cannot
be rolled back. The refusal and commit edge share the existing error mutex.
The active-close retry revisits the same idempotent cleanup before the unchanged
zero-pin lifetime check, so deferral cannot leak a watched connection.

The preserved executor readiness predicate has no credit discount. **D18.4
(not implemented, owner decision after the freeze)** is the receipt alternative
in [s2-exdrain-review.md](docs/flipfix6/s2-exdrain-review.md). The earlier draft and
witnesses below remain historical evidence. Current validation: release build,
fast core session/S2/close units, existing planned-close lifetime units, WATCH
allocation rollback (db1/db16), and `make -q` PASS. Gate/sanitizer/live/counting
proof and final POST/PAD-A arms are in progress; no landing claim yet.

### What the resume established

| Proof | Result |
|---|---|
| Original directed PRE witness | Existing 40/40 failures retained; every deadline refusal's ClientPrepare clauses recorded |
| Extended diagnostic, unchanged flipfix5 EXEC partner | 16 fresh boots over all eight legs; 24 refusals: 8 ClientPrepare and 16 IoDrain |
| IoDrain reference classification | All 16 captured IoDrain failures held retired, published, finalized EXEC states with only MVCC record references remaining; no S2 |
| Owner cleanup diagnostic | Four further IoDrain refusals; executor control passes continue but the idle cleanup sweep is starved by FLIP wake completions |
| Draft EXEC/P1/P2/P3/active-WATCH storms | 40/40 fresh-boot cases passed over all eight legs; 316,801 FLIPs, 633,722 moved-session counter increments |
| Draft semantics after an actual move | 8/8 fresh boots, six subcases each: WATCH clean/dirty, split queue, queue error, DISCARD, RESET |
| Draft WATCH core units | Exact aliases and lifetime checks pass with databases 1 and 16 |
| Draft WATCH allocation-failure sweep | PASS for databases 1 and 16, including rollback after alias append and successful retry |
| PRE-compatible S2 executor-fence witness | 8/8 cases prove ExDrain obstruction; abandoning the same state opens the fence |
| Draft close-after-ExDrain core witness | Both database configurations publish new cleanup tasks into acknowledged owner inboxes; rollback releases the pins |

The live draft checks every EXEC reply for an equal pair and exact final values,
requires all FLIPs to succeed, and requires the moved-session counter to rise.
The largest unrelated PING wait was **25.080 ms**; the largest transaction/read
reply gap was **28.427 ms**. Every fresh boot exited cleanly. These are bounded
correctness/stall checks, **not throughput or performance claims**. Runs used
3 seconds per storm and a minimum of 50 completed FLIPs; actual counts are in
[draft-live-summary.json](docs/flipfix6/draft-live-summary.json). Complete reply,
FLIP and worker records are compressed in `draft-live-results.json.gz`; owned
server logs, argv and exit receipts are in `draft-live-logs.tar.gz`.

All work and builds used CPUs 32-47 only (`-j16` builds). Runtime servers used
32-39 / port 20300, plus a separate diagnostic on 40-47 / port 20310. The
harness socket self-tests used port 20390. Every server boot had `LC_ALL=C`,
16 shards and ratio 6:2, with read-local, key/client LB and automatic FLIP off.

### WATCH pins: approved exception and proof

The draft's FLIP-only predicate requires `session->pending == nullptr`, the
unchanged connection drain predicates, and `watched_refs_ == session->watched.size()`
(or zero with no session). This counts **physical aliases**, not the public
logical watch count. LB still calls the original `migration_protocol_idle()`;
`safe_to_release()` still requires zero references. Both transfer preflight and
`finish_client_transfer` select the FLIP predicate through `hold_for_commit`.
No Client, Op, ThreadCtx, Shard, FlatStore, ROB, AtomicEntry or Config field moves.

The core fixture completes WATCH through real preparation, owner fragments and
retirement. It proves the exact count by temporarily removing the expected
number of pins in its single-threaded state fixture, checking the unchanged
zero-pin lifetime fence, and restoring them. One excess pin and one missing pin
both refuse FLIP readiness. Cases cover completed/repeated WATCH, UNWATCH,
DISCARD, EXEC success, dirty-WATCH nil, EXECABORT, and RESET/close's common
cleanup entry, at 1 and 16 aliases per logical key. The existing allocator-fault
fixture sweeps failures through WATCH preparation and alias-vector append,
requires rollback, retries installation, and checks FLIP equality and cleanup.
There is no claim of exhaustive failure injection into every allocator site.

Live semantic cases force the session connection off IO 5 using `FLIP 1 7`,
require exactly one moved-session increment, and verify IO 0 after completion.
A foreign write after movement dirties WATCH and makes EXEC nil; without the
write EXEC runs. Queued INCRs straddling the move return `[1,1]`; a queue error
still returns EXECABORT without writes; DISCARD and RESET remove the old WATCH.
The registry continues to find the unchanged `Client*`.

Session readers remain audited in [session-audit.md](docs/flipfix6/session-audit.md)
and `session-readers.txt` (all 64 PRE matches). The queue/specs, queue error,
monitor queue, watched aliases and ROB sequence belong to the Client. Pending
attempts, admission, retry nodes and snapshot pools are IO-bound. The new cold
predicate reads only that session and Client state; it adds no IO identity.

### IoDrain: retired records, not S2

Diagnostic v3 adds atomic owner-thread snapshots of deferred-state count,
record refs, watch refs, child debt, retired/published/kind, tasks, registered
read cuts, finalization, commit epoch, pending sessions and global floor/cutoff.
Every IO's last snapshot is dumped, including already-acknowledged IOs.

All 16 v3 IoDrain failures had the same classification: a finalized, published,
retired EXEC, zero tasks, zero WATCH refs, zero child debt, no registered cut,
no `session->pending`, and one or two retained MVCC owner references. The global
read floor was UINT64_MAX and the commit cutoff allowed reclamation. These are
**not prepared unpublished EXECs** and do not qualify for the S2 skip policy.

Diagnostic v4 identifies starvation: the coordinator calls `flip_wake_all()` on
every FLIP pass (`io_loop.h:2430` in the draft; PRE's matching tail), and those
CQ/mailbox completions count as work on each executor. `idle_spins` keeps
resetting before `sweep()` can perform atomic cleanup. One five-second episode
recorded 33,314,892 / 33,867,572 executor control passes but only seven total
cleanup calls per owner, all before the outstanding committed records became
reclaimable. The IO therefore waits for reclamation that its own FLIP wakes
prevent. The four v4 refusals retain their exact clauses and owner snapshots.

The draft runs the existing `atomic_cleanup_cycle(64)` from a live, owed IoDrain
executor control pass. This is bounded by the existing cleanup budget and runs
strictly before ExDrain acknowledgement. It changes no MVCC rule, time constant,
SPSC mask, wake policy, global pause or executor safe point. The complete draft
storm above finishes without a five-second gap. A final candidate must still
carry the gate and sanitizer proof before landing.

The two v2 IoDrain events with no unacknowledged IO at the dump remain **NOT
CAPTURED historically**; no corresponding late-ack event recurred in v3. The
v3/v4 diagnostic retains all IO snapshots if it recurs. Neither those two nor
the earlier two v1 events are retrospectively assigned a clause.

### Remaining blocker 1: S2 cannot reach ClientPrepare

`tests/flipfix6_s2_scope.cc` links against e32b04a44 production objects in both
namespaces, atomic 0/1, with surviving and converting sources. It prepares a
real MULTI/INCR/EXEC and deliberately stops before publication; the same pending
state is returned on re-entry, with no owner tasks and an empty ROB.

All eight cases report:

```
IoDrain=1  atomic_inflight=1  atomic_apply_inflight=1  ExDrain=0
```

EXEC force-admits and opens apply before publishing. The preserved
`ExLoopT::flip_quiesced()` checks those global counts for zero, so both owners
refuse ExDrain and ClientPrepare is unreachable. As a control, abandoning that
same pending state on its admitting IO makes both counts zero and both actual
executor passes acknowledge. A test that skips directly to ClientPrepare would
hide this blocker. No DEBUG hook or added EXEC instruction is needed for this
witness. Logs and build/link/SHA receipts: `s2-fence-witness.log`, `s2-scope/`.

Proposed extension: refuse converting S2 during IoDrain; on a surviving source,
retain its state and publish an exact FLIP receipt of unpublished admission/apply
credits. Only the FLIP ExDrain test may discount those credits. All published
work, other queues and lifetime fences still drain; LB remains unchanged. Close
handling must keep the receipt exact. **Not implemented; approval pending.**

### Remaining blocker 2: closing WATCH after the owner safe point

The core fixture completes WATCH and acknowledges the real ExDrain on both
owners. It then closes the connection while the existing FLIP close pin holds.
`close_client` calls `multi_close_entry` **before** consulting that pin. The next
ordinary IO cleanup pass publishes WATCH-removal tasks into one owner inbox for
db1 and two for db16, although those owners have already acknowledged ExDrain.
The Client's WATCH pins remain live. Rollback and normal owner drain remove them.

This is an actual state-machine witness, not a claim of a live crash. It violates
the frozen-owner producer assumption if the partial session fix is allowed to
commit. We must not weaken the re-mask or lifetime checks to accommodate it.

Proposed extension: defer session close cleanup while the FLIP pin holds; keep
it on a surviving IO, and immediately roll back before commitment if a converting
IO would retain it. Pair this with the S2 receipt above. **Not implemented.**
TLS, BLPOP 0 and non-draining connections remain outside this lane (D18.3).

### Owner rulings

| Ruling | Status |
|---|---|
| D18.1: queue, queue error and watched keys move with Client | Approved; implemented and proved in the retained draft |
| Resume ruling: exact durable WATCH aliases may remain pinned | Implemented in draft; shared LB and destruction checks unchanged |
| D18.2: surviving S2 stays; converting S2 refuses immediately | Approved policy; implementation blocked earlier by ExDrain's global admission/apply counts |
| Other readiness clauses, atomic groups, barriers, ROB/output/retire state, executor fences | Untouched in production and in draft, except the expressly approved session/WATCH predicate; proposed ExDrain exception awaits approval |
| SPSC masked monolith, block masks, ExDrain -> ExInstall re-mask and truth tables | Untouched; close witness exposes a producer after the safe point, requiring cleanup scheduling to be settled |
| Global FLIP dispatch pause | Untouched; no publication or reparse through it proposed |
| Listener handover 2026-10-22, IO4.3/NT4.4 option (a) | Untouched |
| Five-second deadline; no added time constant | Untouched |
| txnorder claims, wound-wait, versions and FIFO hand-off | Untouched; no cancel/reprepare of retained S2 proposed |
| LB mover and shared readiness predicate | Untouched |
| Single-owner writes, immutable replacement/QSBR, no reader retries/seqlocks, RYOW | Untouched |
| Layout locks and both thread modes | Locked fields untouched; draft release build compiles all assertions; new live proof is 2s only |
| D18.3: TLS, blocked and non-draining connections | No implementation changes |

### Proof status and gate accounting

No `collect_job` line was added before or after the quick-tier exit:
**DQ=0, DF=0**. `EXPECT_QUICK=977` and `EXPECT_FULL=994` are untouched.
The following unfinished proof is explicit, not replaced by standalone evidence:

| Requested proof | Status |
|---|---|
| Draft `make -j16 all`, release core fixture and allocator fixture; `make -q` | PASS before draft withdrawal; logs archived; source is now restored to PRE production |
| Python syntax and draft patch apply check | PASS |
| `python3 tests/gates_test.py` | PASS: 76 tests, 143.009 s; `LC_ALL=C`, CPUs 32-47, socket test port 20390; `gates-test-resume.log.gz` |
| New gate jobs and ASAN/UBSAN/TSAN core fixture | NOT RUN: no safe complete candidate until executor-fence/close decision |
| `flip`, `fliplisten`, `flipctl`, `flip_unit`, `flipfix_units`, `flipfix5`, `flipfix5_units`, `core_units` via gate job interface | NOT RUN in resumed work: same blocker |
| LB `lb_stationary`, `lbplanner_units`, `moverfix` | NOT RUN: same blocker |
| txnorder, txnorder2, txnorder_index, txnorder_wake, txnorder_wound, txn_group_fused/split | NOT RUN: same blocker |
| multifix, blockmulti, execfair, multirace, debug batteries | NOT RUN: same blocker |
| atomfix5_watch, datafix2_watch, atomics, multidb, snapfix_bgsave_exec | NOT RUN: same blocker |
| tls, netfix_tls and unchanged BLPOP-held IoDrain row | NOT RUN: same blocker; no sibling behaviour changed |
| Redis 7.4 oracle; `differ_gate.sh` standard seeds on both engines | NOT RUN: same blocker |
| Every `job_production_units` target and freshness | NOT RUN: same blocker; only release, fast core and allocator fixtures built |
| Main-command/MULTI command scopes and ClientPrepare instruction counts | NOT RUN: no complete POST; no zero-instruction claim made |
| GDB attachment for an extra diagnostic | Attempted, unavailable (`ptrace: Inappropriate ioctl for device`); atomic owner snapshots supplied the diagnosis instead |
| Performance benchmarks/load generators/full iteration/ABBA | NOT RUN: reserved for maintainer |

### Arms and measurement request

PRE remains `build/flipfix6/PRE`, SHA-256
`89f2fa028dbe7f05e2a4d9b0f799c6819a391debf8cf4de5506f57397621cf77`.

The provisional, **unsafe to land** draft remains `build/flipfix6/DRAFT`, SHA-256
`578b243efe3807ea392be41928397403ec9f2f516c00249a3e0bcbe7dbb072c6`.
Its patch SHA-256 is
`41bd6c6db0a50b7576a8fc5ba9471ed52676f125524bcbb28ad81bf12c7327da`.
The patch contains the approved readiness work, INFO counters, bounded IoDrain
cleanup and its core units. Its ClientPrepare-only S2 handling is deliberately
identified as incomplete by the separate PRE-compatible witness. Diagnostic
hashes and retention status are in `docs/flipfix6/artifacts.json`.
The duplicate `build/tomokv` draft was removed after preserving `DRAFT`, so a
subsequent ordinary build cannot accidentally use it with restored source.
The retained unit binaries also belong to the draft, not to the restored source.

**POST and PAD-A: NOT BUILT.** Completing their behaviour requires the decision
above. The draft is not substituted for either requested arm. Once complete,
PAD-A must be labelled **A: behaviour twin**: POST's ELF with only the FLIP-only
session predicate restored to PRE, preserving POST text size and layout.

The pending maintainer merit request is unchanged: PRE/POST/PAD-A on the gate's
14 generic cells plus 2s GET/SET p1/p32 (expected null, to be verified); also FLIP
episode latency for all three arms, both with and without a session client,
with PRE refusals reported as refusal durations. Use matched offered loads;
rates decide merit and cycles/op, instructions/op and IPC explain differences.
No throughput claim is made here and none of these measurements was started.

### Reproduce the independent draft evidence

Apply the saved patch only in an isolated review checkout; it is not a complete
candidate. Build with:

```sh
taskset -c 32-47 env LC_ALL=C make -j16 all \
  build/signalacct-core-unit build/atomic-survivors-unit
```

The fixture build/link receipts retain full argv. The live draft command was:

```sh
taskset -c 32-47 env LC_ALL=C python3 tests/flipfix6.py \
  --binary build/flipfix6/DRAFT --cores 32-39 --port 20300 --expect post \
  --cases exec p1 p2 p3 watch semantics --seconds 3 --min-flips 50 \
  --output build/flipfix6/reproduce-draft
```

`--expect post` selects the witness acceptance assertions; it does not certify
the incomplete binary as a POST arm. Original PRE witness/audit details remain
in [witness-report.md](docs/flipfix6/witness-report.md). Superseded diagnostic
sources/logs are removed after hashes, counts and compressed evidence are saved.
