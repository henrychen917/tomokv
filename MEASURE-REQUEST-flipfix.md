## flipfix

FLIP now survives client disconnects and stop requests, and the FLIP state that threads read from
each other has explicit lifetime and ordering contracts (IO4.1, IO4.2, IO4.4, CT4.3). Stress runs on
the fixed build found one more IO4.1 wedge, which is also fixed: a connection transfer could sit in an
inbox with no notify bit while a FLIP was live.

Worktree `/home/user/Projects/cx-flipfix`, branch `cx-flipfix`. PRE is `5146b78ee` (origin/cpp,
unchanged during the lane) and the POST source is `813e1c024`. Nothing was pushed. The evidence is in
[docs/flipfix/](docs/flipfix/); its index, [proof.json](docs/flipfix/proof.json), is generated from
the logs by `build/flipfix/proof.py`. Every build, server and test ran under `taskset -c 112-127`
(servers on 112-119, clients on 120-127, ports 25084-25090). Sibling lanes shared these CPUs, so each
run records its `loadavg`.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/flipfix/pre/tomokv` (git archive of 5146b78ee, `make all`) | `551ec19429f506ef9d9e713b81ef095dbb8869edaa74aea97dbaee4eb5d16d5c` |
| POST | `build/tomokv` (source 813e1c024, `make all`) | `afe6bf3755cc087ee374cb2d3f8939df7d4df720b8fa91466361fb5df9f28f74` |
| PRE asan / tsan | `build/flipfix/pre-asan/tomokv`, `build/flipfix/pre-tsan/tomokv` | `3c367973…d89d9` / `1a8a4067…ca5ef` |
| POST asan / tsan | `build/tomokv-asan`, `build/tomokv-tsan` | `3a504782…02f1f` / `8b5cfb35…427fd` |

### Results per finding (PRE = negative control, POST = fixed build)

| Finding | PRE | POST | New gate row(s) |
|---|---|---|---|
| IO4.1 close during FLIP | `flipfix.py close`: 1500 idle and 24 subscribed peers, 10 closes right after each FLIP is sent, 30 FLIPs. uring fails at attempt 0 with `ERR FLIP coordinator connection left the ownership set`. epoll fails at attempt 0: the FLIP is held 5.00 s, then `ERR FLIP timed out before the ownership commit` (an earlier PRE run was held 5.01 s and failed with `ERR FLIP cannot quiesce a connection: connection is not live on the source IO thread`) | uring: 30 of 30 FLIPs OK; the longest wait after the closes is 0.007 s. epoll: 21 OK and 9 IO4.19 epoll-registration refusals; the longest wait is 0.011 s. All 300 closed peers are reaped | `FLIP close during FLIP (uring)` and `(epoll)`, in job_flip |
| IO4.1 abort branch | `flipfix_abort_probe.py`: a gdb breakpoint holds only the coordinator at `flip_complete_active` while 40 peers close. PRE gets SIGABRT: `abort()` ← `Server::flip_complete_active` ← `IoLoop::flip_control_pass<false>` | The FLIP answers OK, and the 40 held closes are reaped after it retires (161 of 161 clients) | Manual probe (needs gdb). The close rows cover this in the gate |
| IO4.1 late closes | `flipfix.py late`: PRE wedged in 5 of 6 runs; in the sixth, every FLIP was refused | 20 of 20 FLIPs OK | Probe only |
| IO4.1 stranded inbox (found by POST stress) | Not reachable: PRE fails earlier in the same runs | Before this fix, the close driver wedged POST epoll runs at ClientInstall. It was first seen in one run, then reproduced once in 132 recorded runs (`hunt` 40, `dhunt` 92). The capture in dhunt-92 shows a destination IO one connection short of its quota, with the transfer still in its inbox. After the fix: 1000 close runs (500 per engine) and 40 churn runs, with no wedge | The close rows (rate-limited; see Stress) |
| IO4.2 signal stop during FLIP | `flipfix.py sigterm` (`--save "3600 1"`, 1000 acknowledged SETs, the FLIP held live by a BLPOP client): still running 3.0 s after SIGTERM. `sigint`: the second, separately delivered SIGINT was absorbed (still running 0.75 s later) | SIGTERM: exit 0 after 1.01 s. The FLIP answered `ERR FLIP aborted: the server is shutting down`, and the restart recovered 1000 of 1000 keys. Second SIGINT: exit 1 after 0.001 s, printing `You insist... exiting now.` | `FLIP signal stop during FLIP + second SIGINT`, in job_flip |
| IO4.4a plan reads vs close | ASan churn: heap-use-after-free READ in `Server::flip_build_client_plan`, freed by `IoLoop::reap_dead` on another IO. TSan churn: `ThreadCtx::remove_client` (`vector::pop_back`) races `flip_build_client_plan` | ASan churn: uring 30 OK; epoll 17 OK and 13 IO4.19 refusals; no report. TSan churn: 30 OK and no report in plan, close, readiness, transfer, placement or fingerprint code (see the TSan table below) | `FLIP planned-connection close lifetime (ASAN+TSAN)`, in job_flipfix_units (core fixture `flipfix-plan`) |
| IO4.4b planned `Client*` reaped | Unit `flipfix-plan`: ASan reports a heap-use-after-free READ in `flip_candidate_clients_ready`; TSan reports a heap-use-after-free in `client_transfer_ready` | ASan and TSan PASS: both closes are held, dropped (destination quotas 0), then reaped | Same row |
| IO4.4c pub/sub cleanup vs role stores | Not observed on PRE | Closed by construction: a close that reaches the cleanup's Placement read happens either before its IO's IoDrain acknowledgement, or after Idle, or (on a converting IO) before its ClientInstall acknowledgement. Each of these is ordered with the role stores. Subscribed peers close in the close rows | Close rows |
| CT4.3 fingerprint publication | TSan `controllers` run: 7 races between `FlipController::sample_fingerprint` and the IO's write in `parse_and_dispatch`. Unit `flipfix-fingerprint` under TSan: data race | TSan `controllers`: no fingerprint report. Unit TSan PASS | `FLIP fingerprint publication (ASAN+TSAN)`, in job_flipfix_units |

Each new row passes on POST and fails on PRE. The live rows ran with the exact gate invocations (final
driver) against both binaries ([rows/](docs/flipfix/rows/)). The unit rows ran against PRE src plus
the new test sources under both sanitizers ([units/](docs/flipfix/units/)). On PRE the fingerprint unit
passes ASan, which has no race detector, but fails TSan, so the row fails.

TSan report classes (`tsan_classify.py`, same driver on both arms, uring). A report counts as
FLIP code when the top two frames of either access are FLIP plan, close, readiness, transfer,
placement or fingerprint code. It counts as a diagnostic counter when an accessor is a LoopSignals or
INFO counter (the owner decision below).

| Run | PRE: total / FLIP code / diagnostic counters / other | POST: total / FLIP code / diagnostic counters / other |
|---|---|---|
| churn, 30 FLIPs | 28 / 4 / 20 / 4 | 25 / 2 / 19 / 4 |
| controllers, 20 s with `--flip-auto 1` | 100 / 7 / 89 / 4 | 60 / 0 / 56 / 4 |

Three of the four PRE FLIP-code churn reports are IO4.4 races: the plan read against
`remove_client` (two stack variants) and the `client_transfer_ready` use-after-free. All three are
gone on POST. The fourth is `flip_coordinator_`, which is outside these findings (see the notes); it
accounts for both FLIP-code reports left on POST. The seven PRE controllers reports are the CT4.3
races, and they are gone on POST. The four "other" reports have the same signatures on both arms
(`admit_fd` and WbEngine send accounting against `parse_and_dispatch`).

### Mechanism (what changed)

* **Close pin (IO4.1, IO4.4a/b/c).** From an IO's IoDrain acknowledgement until the FLIP retires,
  the teardown gate (`pubsub_disconnect_ready`) holds every close. The close waits there before the
  connection leaves `ThreadCtx::clients` and before cleanup reads Placement. Both teardown paths
  (`close_client` and `flush_ready`'s closing branch) pass this gate first. An IO tenure activated
  inside a live FLIP (EX→IO) pins in `activate()`. The pin is stored in an existing IoLoop hole
  (offset 1411). As a result, the counts stay equal to the plan's quotas, a planned `Client*` cannot
  be reaped, and no close reads Placement while the coordinator stores roles. The FLIP's second drain
  (ClientInstall) skips held closes, because they stay owned and counted on a surviving IO. A stale
  pin is cleared at the next FLIP's IoDrain, before its drain check.
* **Drop, not wait (IO4.1).** At its ClientPrepare epoch claim, a source drops a planned connection
  that is closing, or whose detach lost the race with its EOF. A dropped connection never detaches.
  It is forgotten in the source's own plan row, and one quota unit moves off its destination
  (`Server::flip_drop_planned_client`). A surviving source keeps the connection. A converting source
  releases its pin only once every remaining planned connection has detached; its dropped closes then
  finish before ClientInstall. The RoleReady `count == quota` test and `flip_complete_active`'s exact
  checks stay exact. The completion audit counts drops: transfers + drops == planned, and client
  spread ≤ 1 + 2·drops.
* **Inbox re-flag while a FLIP is live (IO4.1, found by stress).** `NotifyMask::set` skips its RMW
  when it still sees its bit. On x86, the producer's load of the mask word can complete before its
  queue store is visible. The consumer can then take the bit, drain, and miss the item, which waits
  with no bit. The idle path recovers such an item with the unmasked sweep it runs before parking,
  but a live FLIP never parks. While a FLIP is live, each IO pass now flags every client or transfer
  inbox that holds an item (`ThreadCtx::flag_pending_io_inbound`: one depth check per producer, and
  the notify RMW only for a non-empty inbox). It is called out of line from `flip_control_pass`, and
  the loop's masked drains take the item on the next pass. The first version called the unmasked
  drains directly. That added call edges into the hot drain functions and moved GCC's inlining in
  `src/core/reorder.o`; the re-flag adds no such edge.
* **Plan read ordering (IO4.4a).** `flip_build_client_plan` still reads each IO's vector, but that
  vector is now frozen. Every IO acknowledged IoDrain after its own closes settled (with release), and
  the coordinator acquired every acknowledgement. IoDrain is also acknowledged only after an admitted
  LB connection move has left `ClientMoving` and the UNIX owner has acknowledged, so a straggler
  hand-off cannot land after the acknowledgement. The next write to any vector follows the plan's
  stage publication.
* **Stop during FLIP (IO4.2).** While `Server::signal_shutdown_pending()` (the existing
  `kSignalShutdown` bit) is set, the coordinator fails any pre-commit stage with
  `ERR FLIP aborted: the server is shutting down`. The FLIP then rolls back at once, and the save cron
  serves the stop. A FLIP issued while the stop is pending is withdrawn the same way. Post-commit
  stages complete, because they no longer depend on clients. In `on_signal` (main.cc:66-80), a SIGINT
  that arrives while a signal stop is pending, or while the server is already stopping, writes
  `You insist... exiting now.` and calls `_exit(1)`, as Redis 7.4 does. The savefix-owned shutdown
  sequence is unchanged.
* **Fingerprint publication (CT4.3).** The owner's cumulative fingerprint is now a
  `FlipFingerprintPublication`. It has the same size and alignment as `FlipFingerprintWindow`, so
  ThreadCtx stays 1408. Its fields are relaxed atomics, and `closed_windows` is stored last, with
  release. The monitor calls `published_since()`, which acquire-loads `closed_windows`, compares it
  with its last count, and only then copies the fields. There is no retry and no seqlock. The
  sampled-pass publish moved out of line and runs once per W passes. The per-frame gate is unchanged.

Files changed:
* `src/core/io_loop.h`: the FLIP stage machine, `flip_io_drained`, the
  `flip_candidate_clients_ready` region, `activate`, `flip_reflag_inbound`, and two members placed in
  holes.
* `src/core/server.h`: lines 1030-1110 (plan accessors, drop/forget, `signal_shutdown_pending`, plan
  quotas), lines 1707-1750 (`flip_complete_active`), the new `flip_dropped_client_transfers_` in a
  hole, and `flip_begin`'s existing reset line, which now stores to the atomic quota array.
* `src/core/thread.h`: one FLIP-only method, `flag_pending_io_inbound`, placed beside the park
  predicates. ThreadCtx's layout does not change.
* `src/core/pubsub.inc`: only the gate at the top of `pubsub_disconnect_ready`.
* `src/main.cc`: only `on_signal`.
* `src/core/flipctl.h` and `src/core/flipctl.cc`.
* `src/cmd/lbsignals.cc` and `src/core/lbsignals.h`: comment-only corrections that keep line numbers.
* `Makefile`: inlining budgets and test dependencies.

Not touched: clientfix's dispatch gate and FLIP-pause hold (3300-3345, now 3380-3425 after line
shifts), savefix's shutdown sequence (server.h 1797-1906, server_tail.cc, main.cc 364-376), and
aoffix2's park.

### Gate accounting

DQ **+5**, DF **+5**. Three live rows are added to `job_flip`, after its battery server stops. Each
one owns its boots on the slot's `$PORT` and uses its `--ratio $GATE_RATIO`. Two serverless rows are
in the new `job_flipfix_units`. That job depends on `production_units` and `core_tsan_build`. Like
`core_units`, it runs each selection first as an ASan/UBSan unit and then as the TSan unit
(`tsan_unit`). Both jobs are collected before the quick-tier exit, so the arithmetic comment above the
constants reads `511+5 = 516 quick, 528+5 = 533 full`: **EXPECT_QUICK=516, EXPECT_FULL=533**. The five
labels are added to `tests/fixtures/nullrefresh-ledger-labels.json` (`flipfix_supplement`).
`gate_ledger_fixture.py` reports that 533 source-declared rows agree, and its self-test passes 10 of
10. `core_units`' pinned row list is unchanged. At low load, each close row and the signal row take
about 1-2 s on POST, and each unit row takes under 1 s.

### Hot-body identity, default build PRE vs POST (docs/ttlclean method)

The FLIP, fingerprint and inbox code enlarges the initial GCC IPA unit of each translation unit that
instantiates it. From `-fdump-ipa-inline` ([inline-unit-sizes.json](docs/flipfix/identity/inline-unit-sizes.json)),
the growth is main +427, genthread/rl2s/reorder +359, and acl/xshard/climon +8. With
`inline-unit-growth=0`, `large-unit-insns` is the absolute budget, so the budget overrides were
re-derived. Each candidate was compiled offline and every body compared with PRE
([budget-trials-final.txt](docs/flipfix/identity/budget-trials-final.txt)):

| Object | large-unit-insns, PRE → POST |
|---|---|
| src/main.o / db0/src/main.o | 146503 → 146891 / 146540 → 146928 (max-inline-insns-auto=18 kept) |
| src/core/genthread.o / db0 | 128865 → 129025 / 128910 → 129370 |
| src/core/rl2s.o / db0 | 161715 → 162035 / 161680 → 162000 |
| db0/src/core/reorder.o | 147304 → 147752 |
| src/core/reorder.o | No override, as on PRE. An override also raises ipa-cp's budget; in trials it changed 57 hot bodies |
| src/cmd/acl.o / db0 | 34630 → 34638 / 34550 → 34574 |
| src/cmd/xshard.o, src/cmd/climon.o | 127791 → 127815, 25735 → 25743 |

| Check | PRE | POST | Result |
|---|---:|---:|---|
| Hot bodies (`lbstall_artifacts.py compare`) | 1204 | 1204 | 1189 identical, 15 changed (all `parse_and_dispatch`, below) |
| Full inventory (`ccfix_audit.py`) | 16354 | 16354 | 16111 identical, 243 changed |
| Command handlers | 1210 | 1210 | 1210 identical |
| Changed bodies by kind | | | 139 intended, 53 transitive (they inline a changed function), 19 reloc-only (same opcodes, a moved anonymous constant), 32 residual (none hot) |
| `.text` / `.rodata` bytes | 7,582,188 / 156,453 | 7,583,852 / 156,709 | +1,664 / +256 |
| Layout (psfix layout tool and gdb `ptype /o`) | | | The eight locks are unchanged: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. The Server size is unchanged (one field added in a hole). The IoLoop size is unchanged at 7144 (two fields added in holes, at 1411 and 1420); no other offset moved |

Changed **hot** bodies, with the reason:

| Hot body | Objects | Reason |
|---|---|---|
| `IoLoop::parse_and_dispatch<…>` (15 instantiations) | src/main.o ×2, db0/src/main.o ×2, src/core/rl2s.o ×5, db0/src/core/rl2s.o ×5, db0/src/core/genthread.o ×1 | CT4.3. The sampled-pass publish (AVX2 adds and a partial reset, previously inlined) left these bodies for a call to `FlipFingerprintWriter::publish_sampled_pass()`. That call runs once per W passes and only with `--flip-auto 1`; the per-frame gate is unchanged. The smaller bodies were laid out again. In the main and genthread copies, no call target changed apart from the fingerprint calls. In the rl2s copies (the read-local TU), one duplicated dispatch tail is gone, so there is one call site fewer for each of `Rob::publish`, `ThreadCtx::note_command`, `Op::cmd_name`, `Rob::in_flight` and `now_ns`. In two instantiations, one more `Rob::mark_current_write` call site (the read-local write-hazard path) is out of line. These call sites were the same at all 12 budgets tested and were already present before the inbox fix, so they come from the body change, not the unit budget |

No other hot body changed. Unchanged bodies include `run_loop`, `flush_ready`, `on_cqe`,
`collect_retire_work`, `pipeline_pass`, the executor `execute` and `drain_tasks` bodies, the WbEngine
serve bodies, the R7 sweeps, and every command handler. In the Idle stage the cost is still one
predicted-false snapshot test at the top of the out-of-line `flip_control_pass`, and `run_loop`'s call
to it is byte-identical. The close gate adds one predicted-false flag test inside the out-of-line
`pubsub_disconnect_ready`.

The residual changes are all non-hot (32; listed in [classified.log](docs/flipfix/identity/classified.log)):
* ACL command and sort helpers, and xshard MULTI and sort helpers.
* `FlatStore::atomic_collapse` (2 copies), a `FlatStore::hash_key` isra clone,
  `FlatStore::budget_admit` (same size), and `scan_home` (the LB scan).
* Pub/sub request plumbing.
* The R7 1s TLS/recv helpers (`r7_on_recv`, `r7_drive_tls`) and `adopt_client` in reorder.o.
* Cold boot code (`main`, `tomokv_multidb_main`, `Server::init`).

**The mainline must run its performance null**, because the hot `parse_and_dispatch` bodies changed
by design.

### Proof runs

1. **Builds.** `make -j16 all` passed for PRE and POST. All 28 `job_production_units` targets built
   (exit 0) and pass the gate's `make -q` freshness check. `mdbqsbr-live-arms`, `make asan`,
   `make tsan`, the gate-recipe core TSan unit and `tests/flipctl_unit.cc` (`flipctl unit: ok`) all
   passed. Compressed logs are in [builds/](docs/flipfix/builds/).
2. **Units.** All nine core selections (`watch lifetime drain route snapshot config notify
   flipfix-plan flipfix-fingerprint`) pass under ASan/UBSan and under the gate-recipe TSan unit, and
   each TSan witness line is present. `rltopo` 1s and 2s pass.
3. **Serverless checks.** `python3 tests/gates_test.py`: 66 of 66 OK (76 s).
   `python3 tests/wbland_checks.py check clauses`: 83 of 83. `bash -n tests/gate.sh`: ok.
4. **FLIP batteries on the final POST binary:**

   | Battery | uring | epoll |
   |---|---|---|
   | `flip.py` | 542 checks ok | 542 checks ok |
   | `flip_under_load.py 20` | ok | ok |
   | `flip_ttl.py` | 6 checks ok | 6 checks ok |
   | `spinprobe.py` | ok | ok |
   | `spscmask_flip.py` (64 threads at 63:1 via `--place` over 112-119) | PASS | PASS |

   * `flip_close_controls.py`: the positive control passes, and the negative control fails as
     required. Its guard text follows the new pin-gated drain.
   * `flipctl_test.py`: 21 of 21.
   * `flip_multikey_hold.py`: rc 0.
   * `reorder_flip.py --repetitions 1`: acceptance=True (129 s, load1 13.6).
5. **Differential vs Redis 7.4.10.** Suites pubsub, spubsub, fanout, string and list × seeds 7, 19, 20
   and 23 × atomic 0/1. Target on 112-119, oracle on 120, load on 121-127, ports 25087/25088.
   Results: **split 40/40** and **armed-fused 42/42**, with zero differences
   ([differ/](docs/flipfix/differ/)). To reproduce, run `build/flipfix/run-differ.sh` (the ttlclean
   recipe) with the suites and seeds from `docs/flipfix/differ-*.txt`.
6. **Stress (final POST binary, alternating uring and epoll).** Close: 1000 runs (40 + 160 in the
   verification script, then 800, at load1 6-45), 500 per engine, 0 failures. Churn: 40 runs, 0 failures.
   Each run makes 30 FLIP attempts, so about 31,000 FLIPs ran with closes in flight. Before the inbox
   fix, the same close driver wedged once in 132 recorded runs, after a first sighting
   ([stress/](docs/flipfix/stress/), with the pre-fix FLIPDIAG capture).
7. Every new row passes on POST and fails on PRE (the table above).
8. Identity: see the section above ([identity/](docs/flipfix/identity/)).

### Notes and decisions for the mainline

* **Owner decision (related to CT4.3): LoopSignals counters.** These counters (`iterations`, `ops`,
  `busy_ns`, …, read by `lbsignals_capture`, `lb_fold_signals`, `FlipController` sampling and INFO)
  remain plain owner writes that readers load with `__atomic_load_n`. TSan reports them on both PRE
  and POST; they are the "diagnostic counters" column above. A race-free contract needs relaxed-atomic
  writers on the per-pass and per-op hot path, a codegen change across many hot bodies. That conflicts
  with this lane's rule against hot-path work. The options are a relaxed-atomic counter type, or
  accepting the documented diagnostic race. The fingerprint, which feeds the controller, is fixed.
* **Flag (pre-existing, outside FLIP): the load-first notify skip.** `NotifyMask::set` and
  `ReadyMask::set` skip the RMW when the bit already reads as set. The comment says "our item is
  already in the queue by then", but on x86 the producer's relaxed load can complete before its queue
  or ROB store is visible to the consumer that takes the bit. The item then has no bit. Outside FLIP
  it is recovered by the producer's next post or by the consumer's unmasked sweep before parking. A
  consumer that stays busy and never parks can hold the last item of a burst until then. This is
  unmeasured. The options are a fence on the skip path (a cost paid only when the bit is already set),
  or a periodic unmasked sweep. FLIP no longer depends on either.
* **Flag (pre-existing): `flip_coordinator_`.** This field is a plain `uint32_t`. `flip_begin` writes
  it under `shape_transition_mutex`, and every IO reads it on each live pass (io_loop.h:2239). A read
  near the end of one FLIP races the next FLIP's write; TSan reports it on PRE and on POST. It is
  benign, because coordinator actions are gated by epoch-tagged acknowledgements. Fixing it means
  making the member atomic, which touches server.h outside this lane's ranges.
* **Merge order.**
  * The close gate sits at the top of `pubsub_disconnect_ready`. clientfix edits pubsub.inc 297-303,
    which is a different function.
  * clientfix's dispatch gate and the FLIP-pause hold were not changed.
  * savefix's shutdown sequence was not changed. This lane adds only
    `Server::signal_shutdown_pending()` (near the FLIP accessors) and the second-SIGINT branch in
    `on_signal`.
  * `thread.h` gains one method beside the park predicates.
  * **The inlining budgets above are relative to this branch.** After savefix and clientfix land in
    io_loop.h and server.h, the mainline must re-derive them with the same compile-only trial before
    claiming hot-body identity.
* **Interplay with out-of-scope findings.** A planned connection that closes is now dropped instead of
  holding the FLIP to its 5 s deadline. This removes the close-driven part of IO4.3's pre-commit stall.
  Accept-side drops are unchanged: the churn runs still see uring accept closes during FLIP. IO4.19's
  epoll registration collisions still refuse some epoll FLIPs quickly, and the close rows tolerate
  exactly those two messages.
* **Rollback after commit is still impossible by design.** Post-commit stages now depend only on
  transfers, role readiness and pub/sub quiescence, not on clients. A signal stop that arrives after
  the commit therefore waits for completion, which takes milliseconds.
* **PRE controls for the unit rows.** These are built from the PRE tree plus the new test sources
  (`tests/flipfix_checks.inc`, `tests/core_concurrency_unit.cc`), which use only APIs that PRE has.

No benchmark and no full gate was run: the mainline owns the performance null and the gate run.
