# txnfix work and measurement request

## txnfix

**WIP — not ready to merge or measure.** Stage A is implemented. The EXEC batteries pass and the additional WATCH reservation/inbox cycle is repaired. The empty IO retry hook is now outlined, but 27 hot bodies differ and TLS placement changed, so the strict main-command cost bar remains open. Stage B is unimplemented; the design requires Stage A to be green first. This is not an owner decision to omit AT4.2/AT4.3, nor a measured Stage B cost-bar failure.

PRE source: `5146b78ee89b64748dd46db970efa8086f653fa0`. Both the initial and repeat `git fetch origin cpp && git merge --no-edit origin/cpp` found the same base. No push.

PRE binary: `build/txnfix/pre/tomokv`, SHA-256 `34d805081806001bc7e29f4530e040034c935ae0209ca153a5eeed48d52d6c9e`. Earlier shutdown-repaired Stage A binary: SHA-256 `5b182b60806bc534dcb5f7c9f8347a9aaa46b3c179709c6a07c004a054332b32`, built from source `6ea8d4291`. The earlier watermark-repaired image was `98c16cab8fd0055575e07efd4412a22f6d7083dbc54ab142422dd83314b76cf1` at `e6da23f52`. Current POST `build/tomokv`: SHA-256 `2a0eefaafa8eb2ce4e249c0e812140baf77d206f21e0b6b7f89fe8843552d07c`, runtime source committed as `ace6d0c07b5abb8ccf65eae446856249ff65794f`. It was linked immediately before that commit, so its embedded Git version may name the preceding commit. This is a Stage A WIP receipt, not a completed lane.

### Findings and current evidence

| Finding | PRE | Stage A POST | Files / rows |
|---|---|---|---|
| AT4.1 EXEC isolation | T15: 22,273 / 22,763 of 32,000 increments; 9,237 duplicated INCR replies. D1/D1b/D2/D3/D5/S1 fail on data. Crossed WATCH timed out. | New txniso batteries pass split/fused, atomic 0/1, databases 1/16; V4 reload passes both modes/settings. The fused execfix timeout reproduced on diagnostic run 19; the Rule-P watermark repair passes its deterministic unit and 30 fresh-boot execfix repetitions. All eight new battery configurations pass again after the watermark repair and after the subsequent WATCH/IO-signal changes. | multi.inc/h, atomics_glue.inc, atomic_mvcc.h, flatstore_atomic.inc, server.h, blocking.inc, pubsub.inc/event.h, notify.inc, shard.h, t_server.cc, and IO-signal startup binding in main.cc/genthread.cc/reorder.cc/rl2s.cc; four txniso rows. |
| AT4.2 stale atomic group images | T03 loses concurrent SMOVE/LMOVE destination writes; PFMERGE 3 versus expected 6. | Bare group fix is not implemented. The repeated split RENAMENX probe found a Stage A NX-guard regression (PRE 0/4096; candidate 1 in 768). Its decision/read ordering repair is separate from the still-unimplemented bare group OCC fix; see nx-decision-order.md. | Stage B / txngroup rows pending. |
| AT4.3 MSETNX validation | T10 returns 1 and overwrites the acknowledged SET. | Not implemented; no POST success claim. | Stage B / txngroup rows pending. |

Initial PRE receipts: [initial.json](docs/txnfix/pre/initial.json). All four complete PRE EXEC rows fail: [complete rows](docs/txnfix/pre/complete-rows/rows.json). Corrected deterministic witness receipts are under `docs/txnfix/pre/`.

Stage A receipts: split configurations in [post-stage-a-2](docs/txnfix/post-stage-a-2/txniso.json); fused configurations in [post-stage-a-3](docs/txnfix/post-stage-a-3/txniso.json); [AOF reload](docs/txnfix/aof-stage-a/runs.json); [intent/helper units](docs/txnfix/unit-stage-a-2/result.json); [existing regressions](docs/txnfix/regression-stage-a/runs.json). Earlier failures are retained, including the collection-clone leak and the PUBLISH routing error.

### Gate accounting and test adaptations

Current Stage A: **DQ=+4, DF=+4**, emitted at tests/gate.sh lines 1970–1975 and 2112–2113, before the quick-tier exit at line 3443: `511+4=515`, `528+4=532`. The arithmetic comment is above EXPECT in tests/gate.sh; the maintainer-owned constants remain 511/528. AOF and unit checks are subchecks, not extra rows. Finishing Stage B as designed adds two more rows: DQ=+6, DF=+6 overall, EXPECT 517/534 if the merged base remains unchanged.

The label fixture contains the four Stage A additions with no missing or extra labels. `gate_ledger_fixture.py` currently fails because its source/fixture count 532 differs from protected EXPECT_FULL=528. Passing that check and obeying the instruction not to edit EXPECT are incompatible until the maintainer updates the constant; the checker was not weakened.

`execiso.py`: the racing writer is now a plain writer, with doom/retry assertions; serialization permits the holder to re-execute at the new committed state. `txniso` D3 adds an independent write marker on the lead shard so the old read is witnessed before the racing SET. W3 retains 500 repetitions and the 20 s deadline, uses one directed DEBUG SLEEP overlap, and asserts a wound/self-doom occurred; the other 499 repetitions avoid artificial sleep barriers. The first version repeated sleeps 500 times and timed out in fused mode, although an isolated run completed in 18.4 s. X1 re-arms on fresh keys at most four times within the original 15-second deadline when scheduling produces no exclusive witness; four misses still fail. Exact data and zero violation/timeout counters are checked on every arm. Other adaptations: differ.py/infofields_test.py validate the new INFO counters, multidb_unit.cc follows the moved decision member, and store_regression.cc supplies blind-fixture link stubs that abort if a unit intent unexpectedly reaches that fixture.

### Design reconciliations and owner decisions

- PUBLISH/SPUBLISH at existing retirement called a routing stub returning an internal error, contrary to section 3.9. The successful attempt now submits one serialized publication batch and collects receiver counts before retirement.
- Remote cancellation could redirect an already running collection handler from its clone to the predecessor. Per-owner abort latches retain the private image until that owner finishes; foreign readers see cancellation immediately through the decision epoch.
- A cancelled attempt must release its cleanup pin before allocating the next cut slot, or eight retries can exhaust all slots while waiting on their predecessors.
- Admission barrier plus apply-inflight zero has an IO admission/open race. Cold retry-inbox fence nodes acknowledge the barrier before exclusive drain completion.
- The exclusive fallback is isolated in commit `fa5b21d45`; owner decision (1) remains open. Later correctness changes in the same lane must be included when revising it.
- Constants are the owner-approved values; [ledger](docs/txnfix/constants-ledger.md). Stage B is in scope. DEL/UNLINK count at atomic 1 remains the stated residual constraint.
- Non-replayable CONFIG/DEBUG/SWAPDB runs exclusive from its first attempt. Hits/misses may count discarded attempts. The EXEC cut remains a cleanup pin. Whole-shard phantom protection stays on.
- The epoch CAS precedes the writer-cancel flag store. A separate release/acquire cause-ready flag now holds IO re-dispatch until the cause is published, preserving the strict writer-cancel bound even if the doomer is preempted after its CAS.
- WATCH liveness exposed a pre-existing dispatch/reservation cycle: an EXEC could claim on 14 shards while its last two tasks sat behind a writer blocked by those claims. S6 takes precedence over the design’s documented residual hazard. Watched and exclusive attempts now wait for all fragments to arrive before placing the first claim; the deterministic unit and 60 fresh-boot WATCH checks pass.
- The IO signal’s first build missed independent fused startup runners and timed out in fused retries. Binding every runner repaired it; all eight final txniso configurations pass.
- NX validation must inspect foreign decisions before looking up the destination. The initial cancellation-aware guard looked up absence first and could then observe a newly committed foreign ticket, incorrectly passing both tests. The check order is repaired; no retry loop or ordinary command path is added.
- Rule P exposed a conservative commit-watermark lag: A reads the sequence, B reserves/publishes, A decrements to zero and publishes its older sample. A cold helper samples the sequence before observing zero committers and advances only that proven-safe prefix. The existing commit publication function is unchanged; txn_help now forces this interleaving and checks the still-open-bracket negative control.

Every ConfigRoute/Admin family and the other side effects are classified in [side-effects.md](docs/txnfix/side-effects.md).

### Build and proof status

`make -j16 all` built PRE and the tested Stage A image. Every target in job_production_units built successfully, as did mdbqsbr-live-arms. A source edit invalidated the first freshness run. The repaired image was then rebuilt and all 28 production-unit targets passed make -q; [receipt](docs/txnfix/build-watermark/build.json). Both added unit cases pass, including the forced watermark interleaving. The shutdown image also rebuilt all 28 targets and mdbqsbr-live-arms, with every make -q check passing; [receipts](docs/txnfix/build-shutdown/corrected.json). An initial invocation used short unit names instead of build/ targets and failed with no-rule; the corrected command and its success are retained.

INFO-field tests: 10 passed. `gates_test.py`: the initial compile-concurrent run had 11 scheduler failures/timeouts; the quiet rerun passes all 66 tests. Ledger self-tests pass 9/10, with the current-inventory test failing only the protected count mismatch described above. Broad live regression receipts preserve all failures. atomic_plain was initially invoked without its required --atomic argument. Correct invocations then exposed an incompatible holder: it read the racing keys, so OCC correctly made younger EXEC writers wait. Its cleanup-cut holder now reads fresh unrelated keys on the same owners. All four mode/atomic combinations and its self-tests pass; the window witnesses, four-attempt bound and data assertions are unchanged. No full gate or benchmark was run. On the shutdown image, the requested Redis differential matrix passes 112/112 legs plus both armed-fused lane witnesses (7 suites × 4 seeds × 2 atomics × 2 geometries). The original-parameter EXEC audits T01/T02/T02b/T14/T15/T17 pass all 24 POST legs and fail all 24 PRE legs on data. T18 passes all four PRE and all four POST controls. Live shutdown with parked read intents passes both modes and exclusive settings after the repair; the prior Stage A image aborted in both modes. Dedicated watchlive_gate.sh subsequently found wedges in both modes; its controls pass, and a fresh PRE boot also wedges. Debugger evidence and the arrival-barrier repair are in [watch-arrival.md](docs/txnfix/watch-arrival.md). The current runtime source builds all 28 production units and mdbqsbr-live-arms, and every make -q check passes; both new units pass. The latest eight txniso configurations pass. [Build receipts](docs/txnfix/final-stage-a-build/runs.json), [freshness](docs/txnfix/final-stage-a-build/freshness.json), [latest batteries](docs/txnfix/post-io-signal-fixed/txniso.json). The current image passes all 14 additional writer/AOF/snapshot legs and the FLIP hold check (183 assertions). WATCH liveness passes all 60 fresh boots again. Serverless gates_test.py passes 66/66, INFO tests pass 10/10, and shell syntax passes; the ledger still fails only the protected count mismatch. [Remaining regressions](docs/txnfix/remaining-stage-a/runs.json), [final checks](docs/txnfix/final-stage-a-checks/runs.json). The final conditional diagnostic did find a candidate regression; its result tuple, not its old diagnostic process status, is the verdict. [Cause and repair](docs/txnfix/nx-decision-order.md). The corrected binary is being rebuilt; the full proof is not complete.

All executed commands were confined to CPUs 112-127; correctness servers used 112-119, clients 121-127, ports 22600-22699. The generic no-server rule was read with the task-specific focused PROOF authorization. No measurements were run while builds were active.

### Identity and layouts

| Check | PRE vs current Stage A |
|---|---|
| Locked sizes and every existing field offset, both namespaces | Equal |
| AtomicScriptIntent / AtomicPendingState | 32 / 1352, equal |
| Server prior offsets including barrier byte | Equal; cold tail grows by 24,640 bytes |
| ex_loop.h / io_loop.h / scatter_engine.inc source | Unchanged |
| atomic_has_records / atomic_needs_version / atomic_has_script_intent source | Byte-identical; their callers are not all identical |
| Hot object bodies (lbstall tool) | 1,177 / 1,204 equal; **27 differ** |
| Full canonical inventory (ccfix tool) | 15,667 / 16,472 equal; 805 changed |
| Command-handler inventory | 1,199 / 1,210 equal; all GET/SET handlers equal |
| xshard_execute (expected identical in Stage A) | Differs: tomo 21,176 → 21,439 bytes; tomo_db0 23,329 → 23,778 |
| Linked runtime sections | Differ; no byte-identity claim |
| Existing named TLS symbols | 27 of 35 move modulo a cache line; alignment 16 → 64 |

The coherent final inventory is [identity-final-stage-a](docs/txnfix/identity-final-stage-a/README.md). It lists all 27 changed hot bodies, with sizes. [Every changed body and its reason or unresolved attribution](docs/txnfix/identity-final-stage-a/full/changed-bodies-with-reasons.json) is retained. Shared cold additions changed compiler decisions in unchanged hot source; that explanation is an inference, not proof of zero new executed instructions. An offline xshard budget probe improved identity but did not eliminate the differences and was not adopted. The earlier identity-io-signal inventory overlapped a rebuild and is explicitly invalidated in its VALIDITY.md.

[Layouts](docs/txnfix/layouts-final-stage-a.json), [TLS placement](docs/txnfix/tls-layout-final-stage-a.json), [source identity](docs/txnfix/identity-final-stage-a/source-identity.json), [linked sections and digests](docs/txnfix/identity-final-stage-a/linked.json).

The initial retry hook failed the per-pass bar (+11 instructions). The revised hook uses one TLS notification load/test/branch and outlines the cold work; its empty prefix through the old cleanup check is 14 instructions versus 19 in PRE, with an 8-byte frame versus 0x238. Both namespaces agree. [Mechanism and disassembly](docs/txnfix/io-retry-signal.md). The flag occupies its own cache line, but adding it changed unrelated TLS placement. No layout PAD control or throughput result exists, and the main-command cost bar is **not accepted**.

### Measurement requested after correctness and identity work

No cost table has been measured. Do not interpret absent data as meeting the cost bar.

| Cell | PRE ops/s | POST ops/s | retries/s | exclusive/s |
|---|---|---|---|---|
| Uncontended EXEC, disjoint keys | pending | pending | pending | pending |
| Contended EXEC, 2 hot keys + 4 plain INCR clients | pending | pending | pending |
| GET/SET/MGET/MSET ABBA null | mainline | mainline | n/a | n/a |

The extended benchtxn exec driver accepts numeric INCR / KEYSPACE / PLAIN_CLIENTS arguments and optional explicit shared key names. It reports transaction ops/s separately from plain INCR ops/s, and retry/exclusive deltas and rates over an explicit counter interval. A missing PRE counter prints -1. It rejects error replies and broken connections; it has been compiled, not benchmarked. Use the same driver for both arms. Uncontended commands (owner only, fresh quiet boot per cell):

```sh
taskset -c 112-127 make build/benchtxn
taskset -c 121-127 build/benchtxn exec 127.0.0.1 22601 20 64 4 4 2 1 0 0
```


For the contended cell, choose two fresh names with different owners using DEBUG SHARDS on each boot, then pass them explicitly. Fixed names can hash to one owner because the boot seed changes. With those names in shell variables key0 and key1:

```sh
taskset -c 121-127 build/benchtxn exec 127.0.0.1 22601 20 64 4 4 2 1 2 4 "$key0" "$key1"
```

Full-box EXEC geometry for the owner: server on `0-7` with `--shards 16 --ratio 6:2` (2s), or `--thread-mode 1s --read-local 1` (1s); key/client balancing and automatic FLIP disabled. Use a fresh boot for each PRE/POST/POST/PRE arm, atomic 0 and 1. Uncontended client: `taskset -c 8-127 build/benchtxn exec 127.0.0.1 22601 20 64 16 4 2 1 0 0`. Contended client: `taskset -c 8-127 build/benchtxn exec 127.0.0.1 22601 20 64 16 4 2 1 2 4 "$key0" "$key1"`. Retain DEBUG SHARDS geometry alongside every arm. Matched cell ops/s is the verdict; retry and exclusive rates explain the contended cost.

Mainline full-geometry ABBA request (owner runs on the quiet full box, not this lane):

```sh
taskset -c 0-127 tests/gate.sh perf --subset full \
  --server-cores 0-31 --server-smt "" --load-cores 32-127 --load-smt "" \
  --ports 22600-22699 \
  --reference-binary "$PWD/build/txnfix/pre/tomokv" \
  --candidate-binary "$PWD/build/tomokv"
```

Compare matched-load ops/s, cycles/op, instructions/op and IPC for GET/SET/MGET/MSET in both thread modes; use the gate instrument and its standing null. Static hot-body differences are enumerated above, so main-command cost is not yet accepted. No PAD arm has been built or named in this request; an appropriate labelled control remains part of the unfinished cost work.

Latest focused receipts: [eight batteries](docs/txnfix/post-watermark/txniso.json), [30 fused execfix repetitions](docs/txnfix/execfix-watermark/runs.json), [atomic_plain guards](docs/txnfix/atomic-plain-guards/runs.json), [serverless checks](docs/txnfix/serverless-watermark/runs.json). Shutdown retry-inbox/token cleanup is covered by the extended txn_intents unit and four live parked-intent exits. Newer receipts: [original audits](docs/txnfix/original-audits/runs.json), [PRE originals](docs/txnfix/pre/original-audits/runs.json), [PRE WATCH controls](docs/txnfix/pre/watch-original/runs.json), [differential](docs/txnfix/differ-stage-a/runs.json), [shutdown](docs/txnfix/shutdown-intent-after/runs.json), [WATCH liveness failure](docs/txnfix/watchlive-stage-a/runs.json).

The external round-4 REGISTER.md is outside this lane's worktree and was not edited. The reviewable status addendum is [register-status.md](docs/txnfix/register-status.md).

## txnfix2

**NOT READY TO MERGE — Stage B stopped at its explicit cost bar.** Merged base
is `991d48f65`; the pre-final fetch/merge still resolves to that commit.
Housekeeping, NX and admission proofs are complete. The Stage A checkpoint
restores TLS placement and 1,208/1,208 selected ordinary hot bodies. Stage B
adds three executed instructions to ordinary MGET destruction and therefore
fails the zero-new-instruction rule. Its core and separately revisable fallback
commits are retained for review. The identity inventory and per-body status
are recorded, and all requested proof commands have completed. Failures remain:
the baseline atomic-0 control, Stage B's incompatible MSETNX-overlap witnesses,
a baseline armed-fused expected-old read assertion, and a baseline armed-fused
atomic-growth SIGABRT caused by a missing resize-retirement record.
No benchmark, full gate, or push has been run.

The six previously untracked evidence directories are preserved as historical
receipts. Inspection of every file (including ignored files) found no ELF
binaries, object files, or other build intermediates: the directories named
`build-intermediate` and `nx-parent-build` contain build logs and JSON receipts.
Compressed canonical disassembly inventories are evidence, not build products.
These receipts describe the previous session's binaries, not this merged tree.

The merge keeps the incoming blocking ACL checks ahead of transaction mutation
checks and resets the ACL witness when a waiter parks again. Both sets of gate
labels are retained. The merged base's protected EXPECT values are 625/642;
the four existing txniso rows require DQ=+4, DF=+4, hence 629/646 before any
txnfix2 rows. The arithmetic comment is updated; EXPECT assignments are the
incoming mainline values and have not been adjusted for this lane.

### NX result (merged Stage A)

The previous status was stale: the recovered `nx-decision-order/after` receipts
already show 0/16,384 bare atomic-1 races in each mode after `92a550b07` and
`3472dd90e`. The remaining cause was the decision/read order fixed by the first
commit, plus the child losing its parent overlay fixed by the second. No new
runtime NX change was warranted by the merged-tree reproductions.

`tests/txn_nx.py` preserves the protocol detector with exact reply and source
conservation checks. On the merged build, EXEC RENAMENX passes **0/8,192** in
all four mode/atomic cells. Bare atomic-1 RENAMENX passes **0/8,192** in each
mode. The original PRE passes both bare atomic-1 controls; the retained broken
Stage A binary fails both on data. Receipts: [merged NX](docs/txnfix/txnfix2/nx-merged/runs.json),
[PRE/broken controls](docs/txnfix/txnfix2/nx-controls/runs.json).

Bare `--atomic 0` cross-shard RENAMENX remains the pre-existing non-atomic
negative control: it produces two winners. The request for zero at both settings
is met by EXEC, whose isolation contract applies at both settings; it cannot be
claimed for bare atomic-0 commands. The diagnostic `--bare` reports these
failures with a nonzero exit status. The gate does not turn atomic on secretly.

Four new txn_nx rows (two per geometry) are before the quick exit. Including the
four txniso rows, **DQ=+8, DF=+8**, required EXPECT **633/650** from **625/642**.
The comments/label fixture are updated; the protected assignments are unchanged.

### Exclusive admission reproduction

The old report's admission paragraph describes the race and its existing repair,
not an unresolved failure in the current code. `multi_exclusive_ready` already
requires **all IO fences AND zero apply windows**. An IO fence acknowledges the
end of that IO's admission/open interval; it intentionally precedes completion
of the owner-side drain. It is not a drain-completion acknowledgement.

The new `txn_admission` case in `atomic-survivors-unit` suspends a foreign IO
after `atomic_try_admit` and before `atomic_apply_open`. It drives the real cold
IO inbox consumer, verifies the missing fence blocks exclusive dispatch, then
opens the apply window and consumes the last fence. Exclusive still must wait
until the owner closes that window. The current default unit passes. Two copied
source controls fail at the corresponding safety assertion: [without the IO
fence](docs/txnfix/txnfix2/admission-unfenced.log), [without the apply
drain](docs/txnfix/txnfix2/admission-undrained.log). The control builder is
`tools/txnfix_admission_control.py`; all copies/binaries stay under `build/`.
No server starts for this proof. The case is included in the existing txniso
row's unit subchecks, with no additional gate row.

This proof-only fallback commit stays separate from cost/Stage B changes, so
the owner's still-open fallback decision remains independently revisable.

### Main-command identity repair (in progress)

The retry notification byte now occupies the pre-existing TLS padding beside
`blocking_tls_defer_plain`. The transaction age is passed directly from the IO
dispatcher's cached time instead of adding a second TLS variable. Every prior
named TLS offset, the TLS segment size (0x2c0), and alignment (16) match merged
PRE; [linked audit](docs/txnfix/txnfix2/tls-linked.json). The notification is
written remotely only when an actual retry or admission fence is queued.

The Makefile's established per-object inlining budgets restore every selected
ordinary hot body in compile-only probes; [receipts](docs/txnfix/txnfix2/budget-controls).
The default build completed. Its full inventory is still running; no throughput
claim follows from these static checks. `xshard_execute` retains the intended
unit visitor and EXEC notification-field changes and needs the mainline null.

An intermediate TLS build passed six of eight txniso configurations. Under
concurrent compiler load, split atomic-0/db16 missed the D2 wait witness and
fused atomic-0/db16 hit W3's deadline. Both failures are retained in
[tls-batteries](docs/txnfix/txnfix2/tls-batteries/runs.json). The assertions were
not changed. All eight configurations are being rerun after compilation.

The shared fallback drain now uses the retry node as its typed ownership token,
with its IO owner in the node's existing padding. This prepares the same drain
for group retries without casting a group as MultiExecState at shutdown. The
node stays 32 bytes, the lane stays 64 bytes, and no locked layout changes.
Admission, intent/shutdown, and child-help units pass;
[receipts](docs/txnfix/txnfix2/shared-token-units.json). An intermediate missed
retry-held token conversion failed the admission unit and was corrected before
commit; that failing receipt is preserved. This fallback-only refactor is kept
in its own commit.

### Cost checkpoint and Stage B reproduction

The default `8318131e5` code build (binary SHA
`e50321a4272e45dc7c2af19ac1c98cbda60a68e019f036b009c4b62ca2f482fe`)
matches **1,208/1,208 selected hot bodies** in the ccfix audit and passes the
lbstall hot comparison. Full inventory: 16,112/16,590 equal, 478 changed;
handlers 1,205/1,211 equal, with only INFO/DEBUG handler changes.
[Default-build inventory](docs/txnfix/txnfix2/identity-cost/full/summary.json).
These selected hot sets do not include all scatter functions: xshard_execute,
xshard_prepare, xshard_plain_prepare, and xshard_task_should_defer still differ.
The final scatter identity attribution and mainline null remain required.

The quiet checkpoint txniso run passed six of eight configurations. Fused
atomic-0/db1 missed D2's wait witness; fused atomic-1/db1 missed X1's exclusive
witness after all four fresh arms. Neither was a data failure, but neither is a
passing row. [Receipts](docs/txnfix/txnfix2/cost-batteries/txniso.json). D2 now
re-arms a missing wait witness on fresh state within its existing four-attempt
bound, retaining every data assertion and failing if all four miss. Millisecond
admission ages can tie across IOs, whose tie-break can order the racing writer
first. X1's assertions and four-arm bound are unchanged.

The original Stage B audits were rerun with their original parameters against
merged PRE in both modes and atomic settings. All atomic-1 T03/T04/T05/T10 legs
fail on data; atomic-0 T03/T04/T05-SMOVE pass. **Atomic-0 T05-RPOPLPUSH fails
conservation on PRE in both modes**, contrary to the design's passing-control
assumption. [Original-parameter PRE receipts](docs/txnfix/txnfix2/stage-b-pre/runs.json).
The new txngroup battery likewise fails all G1-G4 checks on PRE data, passes G6,
and detects duplicate atomic-0 RPOPLPUSH delivery in G5 in both modes.
[Battery PRE receipts](docs/txnfix/txnfix2/txngroup-pre/runs.json). That baseline
defect is preserved as a failure, not suppressed or relabelled as a passing control.

The two txngroup rows are before the quick-tier exit, giving total lane
**DQ=+10, DF=+10**, required EXPECT **635/652** from **625/642**. The protected
assignments are unchanged. The new rows include an AOF reload companion boot.
Stage B currently uses the existing watch_refs lifetime pin for lazy read
intents: record_refs is reset at the phase-two owner wave, while watch_refs
already survives that wave and participates in every destruction predicate.
ScatterState's new pointer fits its existing pre-epoch padding; no epoch or
existing field is intentionally moved. Layout proof is pending.

The first Stage B core builds successfully and passes G1's five mover races,
G2 MSETNX, and G6 cleanup in both split and armed-fused mode, on db1.
[Core directed receipts](docs/txnfix/txnfix2/txngroup-core/runs.json). Each
atomic-1 race witnesses the required installed private records and no early
reply, then requires both doom/retry counters and exact legal data. The PRE
legs failed those same data assertions. Group fallback is not yet wired in at
this checkpoint and remains a separate, required follow-up.

Current row source lines: fused txngroup 2062, split txngroup 2237, both before
the quick exit at 3771. Thus each contributes +1 to each tier.

### Group fallback checkpoint (not yet accepted)

The first group fallback passes the directed forced-fallback battery (GX),
plus the new CAS/lifetime/reservation unit. G3 mixed SMOVE/SADD wedges in both
modes. The failing logs and two debugger captures are retained in
[group fallback receipts](docs/txnfix/txnfix2/txngroup-exclusive/runs.json) and
[group queue trace](docs/txnfix/txnfix2/group-exclusive-stress-trace2/gdb.log).
A plain writer waiting on an exclusive group enters `xshard_retries_`, which
stops draining the inbox containing that group's next apply wave.

The repair marks only a writer that has actually encountered a reservation.
Its next pass reaches the existing atomic-hazard seam and parks it in
`atomic_deferred_`, allowing the inbox to drain. Scatter reservation waits use
the same deferred queue. Ordinary GET/SET acquire no new path or check. A unit
asserts the initial writer has no hazard mark, the reservation wait adds it,
and the next dispatch parks. This is in the separate fallback commit; neither
executor nor IO loop source is edited. Live reproof is pending.

### Stage B cost stop

Default POST `e1609593d` (SHA
`e633058692653058efe5a546003bd474ebbe09cf4cc84183e14c74dc68a4d1b8`)
adds a load, test and branch for null `group_attempt` in `~ScatterState` on every
ordinary cross-shard MGET. This is an executed-path change even when no unit is
active. [Disassembly and finding](docs/txnfix/txnfix2/cost-body-check/finding.md).
It fails the design's explicit instruction bar; **Stage B implementation stops
here under the owner's stated exception**, with its commits retained. Changing
inlining budgets would not remove this lifetime check. No benchmark can turn
that static result into an instruction-identity pass.

The complete inventory is 15,941/16,639 equal, 698 changed, selected hot
1,196/1,208 equal. The 12 unintended hot differences remain rejected; the
individual table is part of final proof. Group fallback `e1609593d` removes the
reproduced inbox wedge. The first split G3 run reached its unchanged 30-second
deadline; final G1-G4/GX/G6 pass in both modes and database counts. The G5
baseline atomic-0 duplicate remains a failure.
[Initial parking receipts](docs/txnfix/txnfix2/txngroup-park/runs.json).
The four group/admission/intent/help unit cases pass.

### Review boundaries and current artifacts

- `993216d6a` is the last Stage A runtime checkpoint; `8318131e5` supplies
  the ordinary-body/TLS restoration. The Stage A cost binary predates only the
  shared typed fallback-token refactor. Its static inventory is retained and
  is not substituted for the final Stage B inventory.
- `21858278e` adds Stage B core OCC and txngroup rows. `e1609593d` is the
  separate group fallback/parking adjustment. Stage A fallback remains
  `fa5b21d45`, with the separate admission proof and `993216d6a` token adjustment.
  The owner's fallback decision remains open; no merge decision is inferred.
- PRE: `build/txnfix2/pre/tomokv`, SHA
  `5ba1240a65745fadec59d54551f9f1c1f25a6f9c8c3f9db5bba27c90031ceb20`.
  Rejected Stage B POST: `build/tomokv` and
  `build/txnfix2/group-park-tomokv`, SHA
  `e633058692653058efe5a546003bd474ebbe09cf4cc84183e14c74dc68a4d1b8`.
- PAD: **(A) PRE-behaviour aggregate-text-size twin**,
  `build/txnfix2/pad/tomokv`, SHA
  `92a6319747e7d7024396f705a0dbc7c4047ab9c42c1028f9e77010715e708f10`.
  It links unchanged merged PRE objects plus unreachable padding, matching
  POST .text exactly at 7,713,740 bytes (PRE 7,646,972). It controls aggregate
  text size only: it does **not** reproduce internal function placement or
  Server's appended cold tail, and is not a full layout twin. Build recipe and
  exact commands: [PAD receipt](docs/txnfix/txnfix2/pad/build.json),
  `tools/txnfix_pad.py`. No PAD performance inference is made.

[Every changed hot body and scatter/lifetime attribution](docs/txnfix/txnfix2/identity-group-park/README.md)
and the linked/full inventories describe the default build. All existing
locked-layout fields and sizes match PRE in both namespaces. Server alone
has the deliberate 24,640-byte cold append; every existing Server field offset
matches. [Layout comparison](docs/txnfix/txnfix2/layouts-compare.json).
A full Server-layout behaviour twin is still absent; the rejected Stage B arm
is **not ready for a performance acceptance run**.

No rate, cycles/op, IPC, instructions/op or EXEC retry-rate measurement was
run. The table in the original request remains **unmeasured**. After selecting
an acceptable candidate, the owner can run the exact full-geometry null below
on the quiet box; changing the protected CPU allocation for this owner-run
request is intentional, and the lane did not execute it:

```sh
taskset -c 0-127 tests/gate.sh perf --subset full \
  --server-cores 0-31 --server-smt "" --load-cores 32-127 --load-smt "" \
  --ports 22600-22699 \
  --reference-binary "$PWD/build/txnfix2/pre/tomokv" \
  --candidate-binary "$PWD/build/tomokv"
```

The required cells are plain GET, SET, MGET and MSET, both thread modes and
atomic settings, with the gate's existing value-size/pipeline/offered-load
cells. PRE/POST/POST/PRE per cell; matched-load rate decides zero regression,
with cycles/op, IPC and instructions/op explaining it. The PAD size-only
control is optional diagnostic evidence and cannot rescue the static cost
failure. EXEC uncontended and hot-two-key-plus-four-plain-INCR commands in the
original section still apply to the updated PRE path; counters missing on PRE
remain -1 rather than invented zeros.

Current line-based accounting: fused NX at 2049 (two atomic rows), fused
transaction isolation at 2056 (two), fused groups at 2232 (one); split NX in
the loop at 2215 (two), split transaction isolation at 2221 (two), split groups
at 2242 (one). Group jobs are collected at 3671/3700; every row is before
quick exit 3777: **DQ=10, DF=10**;
merged-base **625/642 → 635/652**. EXPECT assignments stay 625/642, so the
ledger checker must report that ten-row discrepancy until the maintainer
updates them. A Stage-A-only selection with NX but without groups is +8/+8,
requiring **633/650**; it must not retain the two rejected Stage B rows.

### Final build and proof

The frozen POST builds with `make -j16 all`; all **29** targets currently listed
in `job_production_units` build successfully, as does `mdbqsbr-live-arms`.
All 30 `make -q` freshness checks return zero. [Build receipts](docs/txnfix/txnfix2/final-build/runs.json),
[freshness](docs/txnfix/txnfix2/final-build/freshness.json). Live proof starts
only after this lane's compilation finishes. Final PRE/POST TLS offsets also
match for every prior named symbol: [TLS](docs/txnfix/txnfix2/tls-final.json).
ScatterState remains 896 bytes, WatchReservation remains 88 bytes, and their
prior offsets match in both namespaces. The executor/IO loop files and the
three required atomic fast predicates remain byte-identical source:
[source check](docs/txnfix/txnfix2/source-identity.json).

### Final live checkpoint and ledger repair

All eight txniso cells pass (split and armed-fused; atomic 0/1; databases 1/16),
as do all four V4 AOF reload companions. Final EXEC RENAMENX repeats again show
**0/8,192 in every mode/atomic cell**; bare atomic-1 RENAMENX again shows
0/8,192 in both modes. Full group rows pass their atomic-1 directed, mixed
writer, conservation, forced-exclusive and cleanup checks; their atomic-0 G5
control still detects the duplicate RPOPLPUSH delivery already reproduced on
merged PRE. This is retained as a failing row, not turned into a skip.

The first ledger invocation also exposed a wiring defect beyond the protected
count: its source projector counted each `if AT=1` group row twice inside jobs
collected at both atomic settings. Two dedicated group jobs now declare each
row exactly once, depend on release and production units, and are collected
before quick exit. No assertion or protected EXPECT assignment changed.
Source and fixture both have **652** rows, with no missing or extra labels;
only EXPECT_FULL=642 still disagrees. [Corrected ledger result](docs/txnfix/txnfix2/ledger-after-job-split.log).
The source-line table is recorded in [current row/collection lines](docs/txnfix/txnfix2/gate-row-lines.json);
DQ/DF remain +10/+10 and the required counts remain 635/652.

The fused txniso jobs now also depend on `production_units`: their unit
subchecks previously depended only on release readiness and could race the
unit build. The dependency change adds no row and the final serverless rerun
covers the corrected coordinator source.

The requested Redis 7.4 matrix passes **112/112 comparison legs**, plus both
armed-fused read-local witnesses (seven suites, four seeds, two atomic settings,
two geometries). The latest merged PRE original-parameter EXEC audits fail
all **24/24** expected negative legs on data, not counters; T18 WATCH passes
all four controls. POST passes all **28/28** corresponding audits. Stage B
original-parameter POST audits pass 16/18; the only two failures are atomic-0
T05 RPOPLPUSH, already failing on merged PRE. Receipts are under
[final proof](docs/txnfix/txnfix2/final-proof/runs.json).

The broad regression run exposes a design/test incompatibility: `multirace`
and `multires` demand an undecided same-connection MSETNX/EXEC overlap, while
Stage B deliberately adds a dispatch barrier to MSETNX. Both modes now pass
the data checks but fail that witness. Their assertions are unchanged. A
resumed Stage B must supply a falsifiable barrier witness before these can be
adapted; this cost-rejected candidate does not claim passing rows.

One armed-fused `execatomic` invocation also fails its expected-old MGET arm
at atomic 0: the logged answer is eight **new** values, not a mixture. All
its concurrent tear checks are zero. The script assumes its lead fragment ran
during a 50 ms sleep; late dispatch is a possible explanation, not a proven
baseline attribution at that checkpoint; the later controls below reproduce
it on PRE. The original failing receipt is retained. WATCH
liveness passes all 30 fresh boots in each mode. Armed-fused `atomic_torn`
passes the preceding data-consistency checks but loses its server with
SIGABRT (exit -6) during `atomicwindow.held_burst`. There is no diagnostic
text in the server log. This is an unresolved baseline correctness failure,
not a deadline exception; the completed controls and cause follow below.
[Failing test](docs/txnfix/txnfix2/final-proof/broad-1s/atomic_torn/test.log),
[server exit](docs/txnfix/txnfix2/final-proof/broad-1s/atomic_torn/shutdown.json).
The main proof driver completed 144 invocations (including deliberately
failing PRE controls); final companion and serverless results follow.

The remaining writer/AOF/snapshot/FLIP companions now pass **15/15**:
four original 60-second writer correctness runs, AOF prepare/reload/scan in
each mode, four concurrent snapshot arms, and the FLIP multi-key hold test
(183 assertions). The four merged-PRE txniso battery controls fail directed
data assertions as required, including lost updates and read skew; their
new-counter-dependent failures are not used as negative proof. PRE battery
receipts carry PRE's hash, independently of the POST companion hashes.
[Final companions](docs/txnfix/txnfix2/final-extras/runs.json).

The complete, sequential `tests/gates_test.py` rerun passes **66/66** in
93 seconds; the initial 300-second overall timeout is retained in the earlier
receipt. No assertions or internal deadlines changed. The ledger self-tests
pass 9/10: only current inventory fails, solely because the protected
EXPECT_FULL is 642 while both source and fixture contain 652 labels, with
no missing or extra labels. [Final serverless receipts](docs/txnfix/txnfix2/final-serverless/runs.json).

The original crossed-WATCH pattern hangs merged PRE at its unchanged
20-second deadline in **4/4** mode/atomic cells and completes on POST in
**4/4**. [Crossed-WATCH receipts](docs/txnfix/txnfix2/final-cross-watch/runs.json).

Fresh Stage A cost-checkpoint controls pass `multirace` and `multires` in
both modes (**4/4**); their missing-overlap failures therefore appear with
Stage B's MSETNX barrier. The unchanged armed-fused `execatomic` test fails
on merged PRE, Stage A and POST. Every failed MGET answer is uniformly new;
all six concurrent reader arms (three binaries, atomic 0/1) report zero
mixtures. This establishes the expected-old assertion failure on the baseline
as well, without treating it as a passing test or changing its assumptions.
[Targeted controls](docs/txnfix/txnfix2/final-controls/runs.json).

The armed-fused atomic-window crash also reproduces on PRE and Stage A
(exit -6). Two POST debugger runs stop in `rehash_step_read_local` while
atomic MSET grows a table. The resize callback is installed but its retirement
record is null. `atomic_prepare_capacity_read_local` omits the retirement
preparation used by ordinary growth; its source is unchanged from PRE.
The full battery reproduces this; a fresh-server window-only reduction does
not. [Cause, exact receipts and source anchors](docs/txnfix/txnfix2/read-local-atomic-resize.md).
It remains unfixed and must not be dismissed as CPU contention.

### Final handoff

| Proof family | Final result |
|---|---|
| Build / production units | `all`, all 29 production targets, `mdbqsbr-live-arms`, all 30 freshness checks pass |
| txniso / EXEC NX | 8/8 batteries; 4/4 AOF companions; zero failures in 8,192 NX repeats per mode/atomic cell |
| Admission guards | Correct unit passes; both independently broken guards fail their intended assertion |
| Redis 7.4 differential | 112/112 comparisons and both armed-fused witnesses pass |
| Original EXEC audits | 28/28 POST pass; 24 expected PRE data failures; four PRE WATCH controls pass |
| Stage B | All atomic-1 directed/stress checks and both AOF companions pass; all four full batteries fail G5's baseline atomic-0 duplicate |
| Broad / persistence / FLIP | 32/38 broad invocations pass; 15/15 companions and 60/60 fresh WATCH boots pass |
| Serverless / ledger | 66/66 coordinator tests; ledger source/fixture 652/652, protected EXPECT mismatch only |
| Cost | Stage A selected hot bodies 1,208/1,208 equal; Stage B rejected, 12 hot drifts plus extra ordinary MGET instructions |

The six nonzero broad invocations are four Stage B MSETNX overlap-witness
failures, one baseline expected-old MGET assertion and one baseline resize
abort. All are retained as failures. No benchmark or full gate ran; all rate,
cycles/op, IPC and EXEC-cost cells remain unmeasured. The limited aggregate
text-size PAD is not a full Server-layout twin.

Stop is under the prompt's explicit Stage B cost-bar exception. Stage B core
and fallback remain separate and reviewable; the fallback decision is still
the owner's. Stage A selection requires the owner-run main-command null and
the documented baseline failure decisions; the default branch is not merge
ready. DQ/DF stay **+10/+10** and full-branch counts **635/652**; a Stage-A-only
selection without group rows requires **633/650**. Neither protected EXPECT
assignment was edited. No work was pushed.

## txnfix3

Work resumes from `b452303fd`, after the required fetch/merge of `origin/cpp`
(`991d48f65`, already current). Proofs use only CPUs 112–127 and ports
22600–22699. No performance workload, full gate or push is authorized here.
The group fallback stays in its existing separate `e1609593d` commit; its
acceptance remains the owner's decision.

Fresh reproduction receipts are in `docs/txnfix/txnfix3/reproduce/`.
Original-parameter atomic-0 T05 RPOPLPUSH fails conservation in both modes.
Both existing MSETNX witness tests fail on the starting candidate. The first
G5 invocation omitted `--pre` and failed at a missing diagnostic; it is retained
as a harness failure, not as duplicate-delivery evidence. A corrected G5 PRE
invocation is required below.

The first cost repair removes `delete group_attempt` from `~ScatterState` and
removes ordinary initialization of that pointer. A group owns its cold attempt
through a high bit in the existing `watch_refs` lifetime predicate. The IO
reaper frees the attempt only after record and intent/reservation pins drain.
Group setup and the barrier assignment run under the existing atomic-group
prepare branch. Static instruction identity and the final proof are pending;
this checkpoint does not claim the cost bar is met.

The corrected PRE G5 legs fail **duplicate delivery** in both modes
(`cost-check/G5-pre-*`); no missing-counter failure is used as evidence.
The first mover candidate passes G5 in both modes, plus the new
`tests/txn_movers.py` coverage of RPOPLPUSH, all four LMOVE directions,
BRPOPLPUSH and all four BLMOVE directions after witnessed blocking registration,
LMPOP LEFT/RIGHT, ZMPOP MIN/MAX and same-member SMOVE races. The source owner
selects/removes the live value; a destination that arrives first defers until
that result is published. Missing source claims cannot push or return the old
phase-one value. Bare multi-pops now explicitly use the newest owner view;
EXEC children retain their parent overlay.

The first barrier-witness candidate passes both existing test batteries in
both modes. Its independently broken barrier control is still required.
The destructor now matches PRE canonically, **751 bytes in both namespaces**;
other scatter functions and selected hot bodies still require reconciliation.
The initial group-unit invocation used only seven client CPUs; a corrected
invocation exposed one remaining assertion that counted the new ownership bit
as a live owner pin. That assertion now distinguishes the ownership bit from
actual pins. Both failures are retained; the final unit rerun remains required.


### Final implementation and review boundaries

The final runtime source is `e904cd285` (later commits contain receipts and
analysis tools). PRE remains the merged `origin/cpp` image from `991d48f65`.
No push or performance run was performed.

1. **Group lifetime and ordinary scatter cost.** `276e3130e` removes the
   unconditional attempt-pointer initialization/deletion. The pointer occupies
   existing ScatterState padding at byte `0x310`; ownership is bit 31 of the
   existing `watch_refs` word at `0x18`. Only the existing nonzero-reference
   reaper arm can call the cold attempt destructor. The group lifetime unit
   accounts for this ownership bit in its exact pin counts and adds a check
   that release fails while an owner pin is live; no lifetime/data guard is
   removed. The constructor, destructor
   and `xshard_destroy` are canonically identical to PRE in both namespaces.
   `5eb7d4574` places group read/completion work behind existing atomic flags;
   `851a1ab4a` freezes the parsed kind after its address-taking parsers;
   `8d1be3901` keeps the existing group-prepare branch out of ordinary
   fallthrough. It adds no new predicate. The final **264 paired fixtures** (180 preparation, eight complete MGET,
   68 complete read/empty-write executions and eight scan continuation prefixes)
   have **zero named-function instruction increases** and enter no group helper.
   `e904cd285` also fixes the 18 normal set/zset/LCS execution counterexamples
   found after the preparation repair. The rejected receipts remain available.
   This removes the demonstrated destructor tax and every sampled increase.
   **It is not a proof of an identical executed sequence on every ordinary
   path. That literal, universal requirement remains open.** The full function
   list, disassemblies, sampled counts and limits are in
   [scatter-cost.md](docs/txnfix/txnfix3/scatter-cost.md). No zero-cost
   performance acceptance is inferred from fewer sampled instructions.

2. **Twelve selected hot drifts.** All are restored: ccfix selected hot
   **1208/1208**, lbstall **601/601 + 603/603**. `a3a1e7a4a` restores one cleanup
   call in place of a separate intent-release call plus free, repairing the
   three IO-template drifts without changing their compiler budgets.
   `97a55dd21` uses the established per-object convention (xshard large-unit-insns
   **138200 / 136800**) and PRE outlining boundaries for the nine store helpers.
   `d0932fbfb` uses DB0 t_server budget **31850** to retain SCAN, RANDOMKEY and
   every unrelated handler. The rejected 31800 trial is retained separately.
   [Every repaired function and full inventory](docs/txnfix/txnfix3/identity-final4/README.md).
   The unchanged full ccfix command exits 1 on the intentional DEBUG handler;
   its selected-hot check passes. The only changed handler bodies are DEBUG
   and INFO, including INFO cold clones, in both namespaces. The full inventory
   has **16656 bodies: 16077 equal, 579 changed**, with an attribution or an
   explicit unresolved compiler drift for each changed body.

3. **MSETNX witness.** `b1e461636`, `fd008220c` and `57afb93ac` change only the
   authorized ordering witness in multirace/multires. With
   `DEBUG TXN-BARRIER-WITNESS 1`, retirement counts an atomic MSETNX still owning
   the Scatter barrier with the following MULTI unparsed in that Client's
   input. Merely preparing a barrier or later owner parking cannot count.
   Both aborted and committing multirace arms must witness it; bounded fresh
   re-arming is retained. Multires still proves that entries are held,
   pending entries exist, and no early reply escaped. All reply, lost-write,
   stale-read and late-order assertions are unchanged. The barrier-removed
   control deliberately suppresses only MSETNX's barrier assignment; both
   batteries fail the new witness in both modes. The control is an isolated
   binary under build/, never production source.

4. **Atomic-0 movers.** `f7f3ce7a5` places the actual claim on the source owner
   in `xshard_movers.inc`: it reads and removes the current edge in the same
   owner turn, publishes that result, and lets the destination push/return
   only the claimed element. A destination that arrives first defers; a source
   miss cannot publish phase one's stale guess. LMPOP/ZMPOP phase two uses the
   current owner view. EXEC children retain their parent's private overlay.
   SMOVE publishes success only for the contender that actually removes the
   member. The original PRE T05 conservation failures and corrected PRE G5
   duplicate-delivery failures remain in
   [reproduce](docs/txnfix/txnfix3/reproduce/) and
   [cost-check](docs/txnfix/txnfix3/cost-check/). POST coverage includes all LMOVE
   directions, BRPOPLPUSH/all BLMOVE directions after all four waiters have
   registered, both LMPOP/ZMPOP ends with COUNT 3, and 100 four-way SMOVE races.
   Original T05 parameters and G5 assertions were not changed. The final
   controls reproduce PRE **duplicate delivery** in both modes and pass POST
   in both modes: [fresh paired G5 receipts](docs/txnfix/txnfix3/final4-controls/runs.json).

5. **Exclusive fallback.** The existing `e1609593d` fallback remains a separate
   commit from Stage B core `21858278e` and this lane's goals 1–4. Its policy is
   unchanged; the owner's acceptance decision remains open. The cost refactor
   moves its existing completion work into a cold group helper but introduces
   no new fallback policy. Stage A is not offered as a replacement selection
   here; the maintainer is landing that separately.

All locked sizes **and existing member offsets** match PRE in both namespaces:
Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144, Config 624. ScatterState remains 896, with every old offset
unchanged. Existing TLS offsets and sizes also match. The earlier Stage A
Server cold append remains 24640 bytes; no old Server field moves.
[Final layout receipt](docs/txnfix/txnfix3/layouts-final4-receipt.json),
[PRE comparison](docs/txnfix/txnfix3/layouts-compare.json),
[TLS comparison](docs/txnfix/txnfix3/tls-final4.json).


### Frozen binaries and owner measurement request

- PRE: `build/txnfix2/pre/tomokv`, SHA-256
  `5ba1240a65745fadec59d54551f9f1c1f25a6f9c8c3f9db5bba27c90031ceb20`.
- POST: `build/txnfix3/post-final4/tomokv` (a frozen copy of tested `build/tomokv`), SHA-256
  `1c808efda63159b31e45e7e960053052b8ac6cd3345049dc23e857bd3da845cc`.
- PAD **(A), limited PRE-behaviour aggregate-text-size control**:
  `build/txnfix3/pad-final4/tomokv`, SHA-256
  `34a0b1a80c587e25b09aae7eede6f12c39fa27ebbbe6c127cb270a011ff07c3a`.
  It links unchanged PRE objects plus unreachable padding. PRE .text is
  7646972 bytes; POST/PAD are 7740572. This is **not** a full internal-function
  or Server-cold-tail layout twin. No full layout twin was produced. This
  limited control is diagnostic only, cannot close the open universal
  instruction bar, and is not evidence of an accepted gain.
  [Exact build and limits](docs/txnfix/txnfix3/pad-final4/build.json),
  [frozen digests](docs/txnfix/txnfix3/final4-frozen.json).

| Cell family | PRE rate / cycles / IPC / instr per op | POST | Deciding evidence |
|---|---|---|---|
| GET, SET, MGET, MSET; 1s/2s; atomic 0/1; standing gate size/depth/load cells | Unmeasured | Unmeasured | Matched-offered-load rate against the standing null; cycles/op, IPC and instr/op explain it |
| Uncontended EXEC and hot two-key EXEC + four plain INCR clients | Unmeasured | Unmeasured | Matched-cell transaction rate with plain rate and retry/exclusive counters |
| PRE versus labelled PAD (A), if the owner uses this limited diagnostic | Unmeasured | Unmeasured | Aggregate-size sensitivity only; no internal-layout conclusion |

After resolving the remaining static requirement, mainline owns the quiet-box
null. This command is a request for the maintainer; the lane did not execute
it or run any workload on CPUs 0–111:

```sh
taskset -c 0-127 tests/gate.sh perf --subset full \
  --server-cores 0-31 --server-smt "" --load-cores 32-127 --load-smt "" \
  --ports 22600-22699 \
  --reference-binary "$PWD/build/txnfix2/pre/tomokv" \
  --candidate-binary "$PWD/build/txnfix3/post-final4/tomokv"
```

Use PRE/POST/POST/PRE and the gate's own existing offered-load cells.
[Exact frozen cell definitions and instrument hashes](docs/txnfix/txnfix3/owner-measurement-cells.json)
name all 181 headline cells plus 32 epoll twins; each arm retains the existing
3 s warmup, 20 s window and 5 s tail. The worst matched cell decides it. No local
instruction trace is substituted for that null. The EXEC commands and counter
intervals in the original request remain applicable with these frozen paths.

This lane adds no gate rows: **txnfix3 DQ=0, DF=0**. The full branch remains
**DQ=10, DF=10**, all before quick exit line **3777**: fused NX **2049** (two),
fused txniso **2056** (two), split NX loop **2215** (two), split txniso **2221**
(two), fused groups **2232** (one), split groups **2242** (one). Group jobs are
collected at **3671/3700**. The maintainer's full-branch counts would be
**635/652**, from protected **625/642**. Neither EXPECT assignment changed.
[Line-based receipt](docs/txnfix/txnfix3/gate-row-lines.json).

### Final proof and handoff

The final runtime source is `e904cd285`; every POST runtime proof below uses
SHA-256 `1c808efda63159b31e45e7e960053052b8ac6cd3345049dc23e857bd3da845cc`.
The checker validates receipt completeness and exact NX repeats in
[final4-summary.json](docs/txnfix/txnfix3/final4-summary.json).
TomoKV correctness servers use CPUs 112–119; the Redis oracle uses CPU 120;
clients use 121–127. Ports are 22600–22699, and compiles/serverless proof stay
within CPUs 112–127. No benchmark,
full gate, workload on cores 0–111, or push was performed.

| Proof family | Final result | Receipt |
|---|---|---|
| Build and production targets | `all`, all 29 job targets, `mdbqsbr-live-arms`; 30/30 freshness checks | [build](docs/txnfix/txnfix3/final4-build/runs.json) |
| txniso and AOF | 8/8 configurations; 4/4 AOF companions | [main proof](docs/txnfix/txnfix3/final4-proof/runs.json) |
| EXEC NX | Four cells, each 0 failures / 8192; two bare controls also 0/8192 | [main proof](docs/txnfix/txnfix3/final4-proof/runs.json) |
| Original EXEC audits | POST 28/28; PRE 23 data failures and five passes (four WATCH controls plus one counter stress leg) | [originals](docs/txnfix/txnfix3/final4-proof/original-post/) |
| Original-parameter Stage B | 20/20: T03/T04/T05 (SMOVE and RPOPLPUSH)/T10, both modes and atomic settings | [Stage B](docs/txnfix/txnfix3/final4-proof/stage-b/) |
| Group batteries | G1–G6 + GX in both modes × databases 1/16; AOF 2/2 | [main proof](docs/txnfix/txnfix3/final4-proof/runs.json) |
| Atomic-0 mover coverage | Both modes pass all mover variants; fresh G5 PRE fails duplicate delivery 2/2, POST passes 2/2 | [paired controls](docs/txnfix/txnfix3/final4-controls/runs.json) |
| Redis 7.4 | 112/112 focused matrix legs plus both armed-fused witnesses | [split](docs/txnfix/txnfix3/final4-proof/differ-split/test.log), [fused](docs/txnfix/txnfix3/final4-proof/differ-armed-fused/test.log) |
| Broad batteries | 36/38; two existing fused failures retained below | [main proof](docs/txnfix/txnfix3/final4-proof/runs.json) |
| Writer/AOF/snapshot/FLIP | 15/15, including four 60-second writer checks and 183 FLIP checks | [companions](docs/txnfix/txnfix3/final4-extras/runs.json) |
| WATCH liveness | 60/60 fresh boots; crossed-WATCH POST 4/4 while PRE times out 4/4 at the unchanged 20-second deadline | [crossed controls](docs/txnfix/txnfix3/final4-cross-watch/runs.json) |
| Directed transaction units | group, admission, intents, help all pass; independently unfenced/undrained controls fail their exact intended assertions | [controls](docs/txnfix/txnfix3/final4-controls/) |
| MSETNX barrier witness | Both tests pass in both modes; barrier-removed build fails the new witness 4/4 | [broken-barrier receipts](docs/txnfix/txnfix3/final4-barrier-control/proof/runs.json) |
| Serverless and ledger | 66/66 gates_test; INFO/shell checks pass; ledger source/fixture 652/652, protected EXPECT mismatch only (self-tests 9/10) | [serverless](docs/txnfix/txnfix3/final4-serverless/runs.json) |
| Identity/layout | selected hot 1208/1208; lbstall 601/601 + 603/603; locked sizes/old offsets and 35 existing TLS symbols preserved | [identity](docs/txnfix/txnfix3/identity-final4/README.md) |
| Scatter cost | Constructor/destructor/destroy canonical identity; 264 paired sampled cases have no per-function increase; universal sequence identity remains unproven | [disassembly review](docs/txnfix/txnfix3/scatter-cost.md) |

The two nonzero broad rows are **not waived**. Armed-fused `execatomic` expects
an old MGET value but receives uniformly new values; concurrent-read legs show
zero torn reads. Armed-fused `atomic_torn` aborts the server with SIGABRT (-6)
on the previously reported read-local resize path. Both failures reproduce on
the final PRE controls; the resize defect remains unfixed. Prior source/stack
analysis is in [the resize report](docs/txnfix/txnfix2/read-local-atomic-resize.md).
No assertion was changed to make either pass.

The missing universal ordinary-path instruction proof is still a failure to
complete **goal 1's literal acceptance requirement**. Preparation, execution
and completion have changed emitted bodies; bounded paths with fewer
instructions cannot certify all values, errors, snapshot interactions or
phase-two branches. The limited PAD is also not a full layout twin. The
quiet-box performance null remains unmeasured. **Stage B is not accepted or
merge ready on this handoff.** Goals 2–4 have their code and final receipts;
the existing fallback remains separately reviewable in `e1609593d`, with its
policy decision left to the owner.

All receipts, including rejected compiler/fixture trials and earlier complete
passes, are retained. Directory names such as `certified` are checkpoint
labels, not acceptance claims; [PROOF-REVISIONS.md](docs/txnfix/txnfix3/PROOF-REVISIONS.md)
identifies the binaries and compressed trace maps. Production source checks
pass `git diff --check`; raw receipts retain original whitespace. The branch
adds no txnfix3 gate row (DQ=0, DF=0), and neither protected EXPECT assignment
was edited. No push was performed.

## txnorder

**BLOCKED for acceptance: D10 plus retained writer marks has a confirmed wait
cycle.** The final source follows per-blocked-key marking in design §2.6.
[Reproduction and proposed amendment](docs/txnorder/writer-cycle/README.md)
records the owner-turn schedule and the final-tree result. The ranking patch
is an unapplied review artifact, not part of POST. It preserves validation-time
writer blocking and lets already-older placing units pass a writer mark while
newer units remain behind it. The owner decision on amending §2.4 is pending.

Base: `0291abe5d`, after the required `git fetch origin cpp && git merge --no-edit
origin/cpp` (already up to date). The implementation covers TO-A and TO-B:
claim modes/caps, arrival/placement, retained age and wound-wait, executing
immunity, writer parking, script APPLY yield, blind-placement restarts,
one-cut read-only EXEC, exclusive removal, and Stage B placement. It retains
txnfix3's watch_refs bit-31 lifetime/padding pointer, atomic-0 mover fix and
MSETNX barrier witness. F1/F2/F4/F5/F6/F8 have directed checks, and F7 uses
nanosecond first-attempt age retained across retries. F3 AOF staging is unchanged.
No ex_loop.h or io_loop.h changes. No push.

All commands for **this section** use only CPUs 48–63: server 48–55, Redis
oracle 56, clients 57–63, builds 48–63 (`-j16`). Ports 22600–22699 only.
Earlier sections retain historical allocations and are not instructions for
this lane. No server, benchmark, load generator, oracle or gate was started.

| Arm | Artifact | SHA-256 |
|---|---|---|
| PRE | `build/txnorder/pre/tomokv` | `1c808efda63159b31e45e7e960053052b8ac6cd3345049dc23e857bd3da845cc` |
| POST | `build/tomokv` | `b27bcd7085403577e46efcddb89e80d2a07fc4b1b28245b6913fb369b07138a0` |
| PAD A, limited size control | `build/txnorder/pad-a-size/tomokv` | `80f08455cfad2a06eb0cb78b7fd22c23c28bdd9ebb187d58dc42225c6d72ccd8` |

PAD is explicitly **(A) PRE behavior with matched aggregate POST .text size**,
7740572 → 7758140 bytes. It is a diagnostic size control: internal function
addresses and the changed cold Server layout do not match POST. It is **not a
complete layout twin**, so it cannot certify layout-independent merit. The
isolated MSETNX barrier-removed binary is also built; its digest is in
[the binary manifest](docs/txnorder/binaries.json).

Completed source/build evidence:

| Check | Result |
|---|---|
| `make all` + all 29 production-unit targets + `mdbqsbr-live-arms` | Exit 0; all 31 freshness checks exit 0 |
| `python3 tests/gates_test.py` | 66/66 pass |
| Directed serverless cases | 28/28 pass; separate wait-cycle falsifier reproduces the blocker |
| lbstall canonical bodies | 601/601 + 603/603 equal |
| ccfix selected hot bodies | 1208/1208 equal |
| Scatter constructor/destructor/destroy | All 12 bodies/clones identical in both namespaces |
| Locked layouts and TLS | Equal, including WatchReservation 88 and ScatterState 896 |
| Label source/fixture | 656/656; protected EXPECT_FULL=642 refusal only |

[PROOF.md](docs/txnorder/PROOF.md) links the raw receipts and every changed
function. The unchanged full ccfix checker exits 1 for intentional DEBUG
changes outside its whitelist; linked runtime sections differ. Neither is
reported as whole-binary identity. The trace guard saw the unused top-level
binary relink while tracing; all 200 linked object inputs stayed identical.
[Reconciliation](docs/txnorder/paths-final/relink-reconciliation.json) binds
those objects to the stable final identity audit and POST digest.

The 264 txnfix3 fixture pairs plus four atomic-1 MSET pairs complete. The main
samples below count named functions, including executed NOPs; they are neither
whole-operation instructions/op nor rates. Values are PRE → POST:

| Cell | Normal 2s / 1s | DB0 2s / 1s |
|---|---|---|
| MGET missing | 2995 → 2991 / 2995 → 2991 | 3017 → 3017 / 3017 → 3017 |
| MGET present | 3069 → 3065 / 3069 → 3065 | 3089 → 3089 / 3089 → 3089 |
| MSET atomic 0 | 2800 → 2800 / 2840 → 2840 | 2837 → 2837 / 2872 → 2872 |
| MSET atomic 1 including commit flush | 4101 → 4093 / 4141 → 4133 | 4153 → 4153 / 4188 → 4188 |

This is **not** a zero-increase result across every named function: normal
DEL/UNLINK add one sampled instruction per fragment (four pairs), and normal
KEYS/RANDOMKEY outline a scan loop into a new named helper (four pairs; aggregate
counts fall). Raw counts are retained. Universal ordinary-path instruction
identity remains unproved; main-body equality and sampled paths are narrower
evidence. No throughput gain or regression verdict is claimed.

The complete runtime handoff is [owner-proof-plan.json](docs/txnorder/owner-proof-plan.json):
215 pending parameter rows, with no copied historical verdicts. It includes
every txnfix2/txnfix3 proof family: all txniso configurations/AOF companions,
EXEC NX 0/8192 requirements and bare controls, original EXEC audits and PRE
controls, Stage B and atomic-0 movers, G1–G6 in both modes and databases 1/16,
Redis 7.4's 112-leg focused matrix plus armed read-local witnesses, broad
batteries, writer/AOF/snapshot/FLIP, fresh WATCH boots and crossed WATCH, and
new txnorder a–d PRE/POST controls. Missing new counters are not a valid PRE
failure; `--pre` retains the supported semantic checks. Original held-group
audits may need asynchronous writer sequencing under D1; retain exact data
assertions and a witnessed window, and never count a timeout as a pass.

The four new gate rows use four executor owners for the requested stress:
new split rows explicitly use 4:4, fused rows arm read-local, and fused atomic 1
uses databases=16. Existing batteries remain 6:2. This resolves the design's
four-owner stress versus two-executor boot conflict as a stated assumption;
the geometry question remains pending. New row declaration: gate.sh:2268;
collector:3735; quick exit:3816. **DQ=4, DF=4**, cumulative outstanding +14/+14.
The maintainer counts should be **639 quick / 656 full**. EXPECT_QUICK=625 and
EXPECT_FULL=642 are unchanged.

After the liveness amendment and its final proof, request these merit cells
with the gate's own ABBA instrument, on a quiet box and one cell at a time:

| Cells | Arms and fixed shape | Deciding numbers |
|---|---|---|
| Main-command null: GET, SET, MGET-2, MSET-2, DEL-2, UNLINK-2 | PRE/POST, both modes, atomic 0/1, DB 1/16, 16 shards, split 6:2, depths 1/16/128; same keys/values and offered load per arm | Matched-load rate is the verdict; retain cycles/op, instructions/op and IPC for each ABBA cell. A null regression blocks acceptance. |
| EXEC uncontended | PRE/POST; same geometry; disjoint per-client key pairs, MULTI;INCR a;INCR b;GET a;EXEC, depths 1/16 | Rate and p50/p99 at matched load; one committed execution per success, zero dooms/order violations |
| EXEC hot key | PRE/POST; a1/a2's exact 1 or 4 EXEC clients plus 16 plain writers, two executor owners, then the b1 four-owner shape | Exact final counts and completion deadlines first; attempts/EXEC, retries/wounds/blind restarts, writer waits; then matched-load rate, latency, cycles/op and IPC |
| Size diagnostic | PRE/PAD-A-SIZE alongside selected POST cells above | A size-only shift is diagnostic only; this limited PAD does not decide the layout claim |

Append actual results as MEASURE-RESULT. Active expiry/eviction versus read
claims remains the design §6 owner decision. The read-only implementation has
the existing MGET retained-version contract, not a stronger history guarantee
for unversioned plain writes. Neither issue is hidden by the liveness blocker.


## txnorder2

The approved A′ writer episodes replace the unconditional writer-mark wait.
D1–D10, including validation-time writer blocking, are retained. WATCH serves,
FLUSH presence/expiry semantics and the final read-only EXEC dirty check are
fixed. The busy fused-owner inbox hang is reproduced before `7b31fd15f` and
passes after it. This supersedes the preceding txnorder section's pending A′
decision; it does not assert performance acceptance.

Base is merged `origin/cpp` **a7dfb9d23**, merged by `73e35f754`. Final production
source is **9d6e99d0d**; subsequent commits preserve reports, harness inventory
and receipts. Every command in this continuation uses CPUs **64–95**, builds
`-j32`; correctness servers and Redis use ports **27800–27899**. The initial
serverless socket-control port exception is recorded below. Correctness servers, Redis 7.4 and individual
gate jobs were explicitly authorized. No performance benchmark or full gate
iteration was run. No push.

The step-by-step implementation and runtime proof is
[docs/txnorder2/PROOF.md](docs/txnorder2/PROOF.md). Prior completed requirements
are cited by commit and receipt there, rather than reclassified as new work.
[RESUME-REVIEW.md](docs/txnorder2/RESUME-REVIEW.md) reviews all 14 saved paths in
`397403586` and both paths in `bbcbb6252`: all were kept, with the runtime
owner-data path additionally isolated per run. No later capacity-stop WIP
commit existed at resume. The new gate wake label was added to the explicit
source fixture; neither EXPECT constant was edited.

| Requirement | Result / receipt |
|---|---|
| A′ and R1–R12 | One stamp per complete blocked episode/shard; full local key set, all-or-none failure cleanup, older placing units pass. `822d7f310`, `cc7813c32`; `controls/` and episode logs. PRE cycles, rank-only R3/R4 cycles, POST termination; invariant, allocation and leaked-mark falsifiers included. |
| WATCH items 4–6 | `48029f52d`, `6a56c5cc6`; exact Redis 7.4.10 serve/FLUSH oracle, both modes, both engines, DB1/16; real held CAS/final-read window. `watch-oracle-final2c/`, `origin-serve/`, gate WATCH logs. |
| Wake hang | Captured unconsumed inbox task with a clear summary bit while the fused owner remains busy. Exact `7b31fd15f^` fused control fails, split control passes; POST both pass. `wake-before-fix/` and `nx-progress-repro-owned-attach-third/3/`. The old `differ-hang-backtrace.log` is a failed attach, not a backtrace. |
| Original 215-row plan | All rows accounted for: selected POST 155 PASS; merged-origin PRE 11 PASS / 45 FAIL; four barrier-off controls FAIL the required mechanism witness. [runtime-coverage.json](docs/txnorder2/runtime-coverage.json) binds every row to command, binary and receipt. These are multiple explicitly identified runs, not 215 passes on one final binary. |
| Own gate-job proof | Final POST: 48 requested jobs / 51 with prerequisites, **355 PASS / 0 FAIL**, unchanged binary SHA. All 17 new rows and all 24 WATCH legs present. `gate-final2d/`, `resume/final-gate-coverage.json`. Exact-origin wake own-job control fails 1s and passes 2s as intended in `gate-wake-pre-final/`. |
| Builds / harness | `make all`, every production-unit target and mdbqsbr live arms complete; **44/44 freshness checks** pass. Unchanged `gates_test.py`: **67/67 PASS** in the final port-constrained own-job run. The first run's two scheduler timeouts during compilation are retained. INFO-field controls: 10/10 PASS. |
| Identity / layout | All locked sizes and old field offsets match in both namespaces. Every one of 727 differing bodies is listed with a reason/inference; 14 hot bodies differ. No checker weakening. [IDENTITY.md](docs/txnorder2/IDENTITY.md). |

The separate **abba_selftest gate row remains FAIL**. All completed suites
pass, including 121 ABBA decision tests and 67 gate tests; the source receipt
preflight refuses at unchanged `EXPECT_FULL=702` versus 733 matching
fixture/source labels. **NOT RUN:** the internal receipt controls beyond that
preflight, pending the maintainer's protected-count update. See
[harness-final-assessment.json](docs/txnorder2/resume/harness-final-assessment.json).

A port-scope exception is retained: earlier standalone harness runs and the
first additional own-job attempt used default ephemeral listening ports for
socket controls. I stopped the own-job attempt and reran with
`GATE_TEST_PORT=27899`; the final 67/67 result above is from that constrained
run. Correctness servers/oracle used assigned ports throughout. The initial
port numbers were not recorded; [the correction receipt](docs/txnorder2/resume/harness-port-correction.json)
identifies the affected runs. No performance load ran in these harness jobs.

The episode and readonly-window defects belong to the pre-amendment lane, so
the meaningful negative baseline is **73e35f754**, with its observational
stamp shim disclosed. The completed own-job PRE receipt in
[gate-pre-complete/preserved.json](docs/txnorder2/gate-pre-complete/preserved.json)
records all 16 scored failures and all declared legs. R8's retained D10 guard
itself passes PRE; its full episode-contract assertion fails. Literal origin
R-family/item-6 mechanism controls are **NOT RUN** because those mechanisms
and the post-CAS write window do not exist there. Origin is the actual PRE for
serve/FLUSH, wake, cost, identity and ordinary runtime controls. The PRE X1
DEBUG-hook semantic control is **NOT RUN** because origin lacks the hook;
unknown-command errors are not defect proof.

Harness changes keep exact data/replies and held-window witnesses. Under D1,
a writer blocked by a held unit must be released asynchronously with that
unit; waiting for that writer before releasing the holder creates a test
cycle. `execatomic.py` allows at most four fresh-state attempts only when the
data is correct but the window was absent, then fails if it never opens.
Missing PRE counters, interrupted ledgers and missing witnesses are explicitly
distinguished from semantic defect failures.

Instruction counts are in [COST.md](docs/txnorder2/COST.md), with every pair in
[instruction-summary.json](docs/txnorder2/instruction-summary.json). They are
serverless production-path debugger counts, not measured hardware performance.
The EXEC region includes preparation, owner turns, decision and retirement,
and excludes networking, prior command queueing and later reclamation. It
follows library/indirect calls, but excludes the vDSO clock body (PRE 0 calls,
POST 1) because single-stepping its sequence loop perturbs it; REP iterations
are disclosed. Atomic=1, two INCRs, first EXEC after seeding, no competitor:

| Namespace / mode | Single-shard steps/EXEC PRE → POST | Two-owner steps/EXEC PRE → POST |
|---|---:|---:|
| normal 1s | 21,945 → 26,705 | 22,640 → 27,972 |
| normal 2s | 25,908 → 30,653 | 26,657 → 31,959 |
| DB0 1s | 20,086 → 24,809 | 20,711 → 25,986 |
| DB0 2s | 24,012 → 28,724 | 24,695 → 29,948 |

Removed costs include eager clocks, redundant single-shard ARRIVE accounting,
duplicate key scans/storage and the one-key duplicate preflight. The latter
moves normal 2s named-routine counts 11,859 → 10,698 for one shard and
12,731 → 11,629 for two owners. Admission age, claims, cross-owner ARRIVE,
private versions and decision/lifetime joins remain required mechanisms;
this does not label every generated instruction irreducible.

Session-entry GET/SET is **202 → 202**, MGET/MSET **214 → 214**, in both modes
and namespaces with a MultiSession but no unit in flight. DB0 MGET's extra
instruction is removed: execute **322 → 322** over two fragments. DB0
DEL/UNLINK are **462 → 462**, normal **452 → 450**. KEYS/RANDOMKEY's skipped
scan-home helpers are canonical-identical, and caller totals fall.
Universal ordinary-path zero overhead is **not established**: normal atomic
MSET retains **+11 named instructions in 2s / +16 in 1s** in commit/completion
handling; DB0 plain MSET execute retains +1 per fragment while its aggregate
falls. These residuals and all compile-only budget trials remain visible for
merit review, rather than being called unavoidable or hidden in helper splits.

| Arm | Artifact | SHA-256 |
|---|---|---|
| PRE, a7dfb9d23 | `build/txnorder2/pre-source/build/tomokv` | `97ea4e0638863ac87b289290bd489d8ef93e5fc4808ad49bc71dfbd05a9c739e` |
| POST | `build/tomokv` | `5bfa95e74b42c78c0b70fa0e3983c89582b66dc8d4a1570262968ec84e5f447f` |
| PAD **(A), behaviour twin** | `build/txnorder2/pad-a-size-final2c/tomokv` | `52a0b831841e5b0960b604069bfb190651ed23723d36fcdce19027da2a8aaaef` |

PAD(A) preserves PRE behavior, adds an unused aligned 32,832-byte cold Server
tail matching POST's size/old offsets, and adds unreachable text padding to
match POST's **7,867,398-byte .text**. It is a limited aggregate size/allocation
control; individual function positions and all other sections do not match.
It cannot alone establish immunity to every layout/cache effect. No PAD(B)
was built. Build recipes and exact hashes are in
[final-artifacts.json](docs/txnorder2/resume/final-artifacts.json) and the PAD
receipts. Build artifacts stay under ignored `build/`.

Request the maintainer's quiet-box ABBA merit run with **PRE / POST / PAD(A)**:

| Cells | Fixed shape / instrument | Deciding evidence |
|---|---|---|
| Main-command null | GET, SET, MGET-2, MSET-2, DEL-2, UNLINK-2, KEYS, RANDOMKEY; both modes, atomic 0/1, DB1/16, depths 1/16/128; same keyspace/values and offered load; eight server cores, 16 shards, split 6:2. Gate's own ABBA instrument. | Matched-load rate decides; retain cycles/op, instructions/op, IPC and latency. Include normal atomic MSET and scan cells explicitly. |
| EXEC uncontended | `/home/user/Projects/calib/exec-merit.py` x2s/x1s × atomic 0/1 × unc; 64 connections, 16 client threads, pipeline 4, two INCRs/EXEC, private key pairs. Split: eight cores, 16 shards, ratio 6:2; fused: eight cores, 64 shards, read-local=1. DB1; balancing/flip off. | Completed EXEC/s and matched-load latency; hardware cycles/**EXEC**, instructions/**EXEC**, IPC; profiles for both arms explain the remaining overhead. Denominator is completed EXECs, not two INCR children or RESP command count. |
| EXEC hot | Same four mode/atomic cells with two shared keys on different owners and four plain INCR clients; same 20-second blocks, three ABBA repetitions as the merit driver. | Exact data and bounded completion first; then matched-load rate/latency, cycles/EXEC, instructions/EXEC, IPC, attempts, wounds/retries, blind restarts and writer waits. |
| PAD diagnosis | Repeat the same chosen cells with PRE/PAD(A) and POST, unchanged offered load. | POST movement with flat PAD supports a behavior effect within this control's stated limits; a PAD shift requires layout investigation. |

The current EXEC merit driver reports fixed-concurrency throughput; it does
not itself collect hardware counters or impose a matched offered-load cap.
Keep that result labeled accordingly and collect the requested matched-load
counter/latency profiles with the maintainer's instrument. The reproducible
throughput command from this worktree is below (request only, **NOT RUN**):

```sh
taskset -c 64-95 python3 /home/user/Projects/calib/exec-merit.py \
  --reference build/txnorder2/pre-source/build/tomokv \
  --candidate build/tomokv --benchtxn build/benchtxn \
  --output build/txnorder2/merit-post --cells all \
  --server-cores 64-71 --load-cores 72-95 --port 27890 \
  --conns 64 --threads 16 --blocks 3 --secs 20
```

For the type-A control, repeat with candidate
`build/txnorder2/pad-a-size-final2c/tomokv` and output
`build/txnorder2/merit-pad-a`. Driver/source/binary input hashes are in
[merit-request-inputs.json](docs/txnorder2/resume/merit-request-inputs.json).

Suggested allocation within this lane is server 64–71, clients 72–95 and port
27890, only when scheduled by the maintainer. Hardware counts, throughput,
full iteration and these merit cells are **NOT RUN**, reserved for that run.
Append the measured verdict as MEASURE-RESULT; this report makes no throughput
claim.

Gate arithmetic is by collector line: txnorder2 at 4420 and txnorder_wake at
4421 precede quick exit 4503. This continuation adds **17/17**; the complete
unmerged lane adds **DQ=DF=31** over a7dfb9d23. Required counts: **716 quick /
733 full**, from unchanged **685/702**. The source fixture matches all 733
labels, including duplicates; its count check correctly refuses until the
maintainer changes EXPECT. The four-owner txnorder stress explicitly uses
split 4:4; ordinary batteries retain 6:2 and 16 shards.

D3 blind restarts, finite older chains, monotonic-clock/FIFO assumptions and
the existing MGET retained-version contract remain the approved limits.
Active expiry/eviction versus read claims remains the design's owner decision;
the live-version eviction guards do not prove a blanket read-claim pin.
Artifact cleanup and final gate details are recorded in PROOF.md. No binary,
objdump or file over 1 MB is committed in this continuation.
