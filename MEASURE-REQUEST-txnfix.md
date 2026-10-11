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

**WIP — not ready to merge or measure.** Merged `origin/cpp` at `991d48f65` in
`ee48b465e`. Housekeeping, the repeated NX proof, and the deterministic admission
proof are complete. TLS placement is restored and the per-object budget probes
match every selected ordinary hot body; the default-build inventory and quiet
txniso rerun are in progress. Stage B and the merged-base proof remain open. No benchmarks or full gate runs are authorized for this lane. No push.

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
