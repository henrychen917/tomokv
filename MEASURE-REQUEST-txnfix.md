# txnfix work and measurement request

## txnfix

**WIP — not ready to merge or measure.** Stage A is implemented and committed; the new EXEC batteries pass, but broader regression and byte-identity proof are still open. Stage B has not started because the design requires Stage A to be green first. This is not an owner decision to omit AT4.2/AT4.3, nor a measured Stage B cost-bar failure.

PRE source: `5146b78ee89b64748dd46db970efa8086f653fa0`. Both the initial and repeat `git fetch origin cpp && git merge --no-edit origin/cpp` found the same base. No push.

PRE binary: `build/txnfix/pre/tomokv`, SHA-256 `34d805081806001bc7e29f4530e040034c935ae0209ca153a5eeed48d52d6c9e`. Tested Stage A binary: `build/tomokv`, SHA-256 `83cb85c8bcafeb27b2622a94bde8b9da1370cfb8812af6d325ff5c44ea60345d`. The subsequent publication-OOM ordering edit requires a fresh default build and final proof; these hashes are not a final source receipt.

### Findings and current evidence

| Finding | PRE | Stage A POST | Files / rows |
|---|---|---|---|
| AT4.1 EXEC isolation | T15: 22,273 / 22,763 of 32,000 increments; 9,237 duplicated INCR replies. D1/D1b/D2/D3/D5/S1 fail on data. Crossed WATCH timed out. | New txniso batteries pass split/fused, atomic 0/1, databases 1/16; V4 reload passes both modes/settings. The fused execfix timeout reproduced again on diagnostic run 19; a Rule-P watermark repair and deterministic unit are now implemented but await fresh proof. | multi.inc/h, atomics_glue.inc, atomic_mvcc.h, flatstore_atomic.inc, server.h, blocking.inc, pubsub.inc/event.h, notify.inc, shard.h, t_server.cc; four txniso rows. |
| AT4.2 stale atomic group images | T03 loses concurrent SMOVE/LMOVE destination writes; PFMERGE 3 versus expected 6. | Bare group fix is not implemented. One atomic_torn RENAMENX anomaly was observed in split mode; provenance against PRE is pending. | Stage B / txngroup rows pending. |
| AT4.3 MSETNX validation | T10 returns 1 and overwrites the acknowledged SET. | Not implemented; no POST success claim. | Stage B / txngroup rows pending. |

Initial PRE receipts: [initial.json](docs/txnfix/pre/initial.json). All four complete PRE EXEC rows fail: [complete rows](docs/txnfix/pre/complete-rows/rows.json). Corrected deterministic witness receipts are under `docs/txnfix/pre/`.

Stage A receipts: split configurations in [post-stage-a-2](docs/txnfix/post-stage-a-2/txniso.json); fused configurations in [post-stage-a-3](docs/txnfix/post-stage-a-3/txniso.json); [AOF reload](docs/txnfix/aof-stage-a/runs.json); [intent/helper units](docs/txnfix/unit-stage-a-2/result.json); [existing regressions](docs/txnfix/regression-stage-a/runs.json). Earlier failures are retained, including the collection-clone leak and the PUBLISH routing error.

### Gate accounting and test adaptations

Current Stage A: **DQ=+4, DF=+4**, all emitted before the quick-tier exit: `511+4=515`, `528+4=532`. The arithmetic comment is above EXPECT in tests/gate.sh; the maintainer-owned constants remain 511/528. AOF and unit checks are subchecks, not extra rows. Finishing Stage B as designed adds two more rows: DQ=+6, DF=+6 overall, EXPECT 517/534 if the merged base remains unchanged.

The label fixture contains the four Stage A additions with no missing or extra labels. `gate_ledger_fixture.py` currently fails because its source/fixture count 532 differs from protected EXPECT_FULL=528. Passing that check and obeying the instruction not to edit EXPECT are incompatible until the maintainer updates the constant; the checker was not weakened.

`execiso.py`: the racing writer is now a plain writer, with doom/retry assertions; serialization permits the holder to re-execute at the new committed state. `txniso` D3 adds an independent write marker on the lead shard so the old read is witnessed before the racing SET. W3 retains 500 repetitions and the 20 s deadline, uses one directed DEBUG SLEEP overlap, and asserts a wound/self-doom occurred; the other 499 repetitions avoid artificial sleep barriers. The first version repeated sleeps 500 times and timed out in fused mode, although an isolated run completed in 18.4 s.

### Design reconciliations and owner decisions

- PUBLISH/SPUBLISH at existing retirement called a routing stub returning an internal error, contrary to section 3.9. The successful attempt now submits one serialized publication batch and collects receiver counts before retirement.
- Remote cancellation could redirect an already running collection handler from its clone to the predecessor. Per-owner abort latches retain the private image until that owner finishes; foreign readers see cancellation immediately through the decision epoch.
- A cancelled attempt must release its cleanup pin before allocating the next cut slot, or eight retries can exhaust all slots while waiting on their predecessors.
- Admission barrier plus apply-inflight zero has an IO admission/open race. Cold retry-inbox fence nodes acknowledge the barrier before exclusive drain completion.
- The exclusive fallback is isolated in commit `fa5b21d45`; owner decision (1) remains open. Later correctness changes in the same lane must be included when revising it.
- Constants are the owner-approved values; [ledger](docs/txnfix/constants-ledger.md). Stage B is in scope. DEL/UNLINK count at atomic 1 remains the stated residual constraint.
- Non-replayable CONFIG/DEBUG/SWAPDB runs exclusive from its first attempt. Hits/misses may count discarded attempts. The EXEC cut remains a cleanup pin. Whole-shard phantom protection stays on.
- The epoch CAS precedes the writer-cancel flag store. A separate release/acquire cause-ready flag now holds IO re-dispatch until the cause is published, preserving the strict writer-cancel bound even if the doomer is preempted after its CAS.
- Rule P exposed a conservative commit-watermark lag: A reads the sequence, B reserves/publishes, A decrements to zero and publishes its older sample. A cold helper samples the sequence before observing zero committers and advances only that proven-safe prefix. The existing commit publication function is unchanged; txn_help now forces this interleaving and checks the still-open-bracket negative control.

Every ConfigRoute/Admin family and the other side effects are classified in [side-effects.md](docs/txnfix/side-effects.md).

### Build and proof status

`make -j16 all` built PRE and the tested Stage A image. Every target in job_production_units built successfully, as did mdbqsbr-live-arms. A source edit during that build invalidated most subsequent make -q checks; the full freshness proof must be repeated on the final source. The two added atomic-survivors cases pass, including cancellation between cloning and the collection handler.

INFO-field tests: 10 passed. `gates_test.py`: 11 scheduler failures/timeouts in the first run while compilation was active; not a pass, rerun pending. Broad live regression receipts preserve all failures. atomic_plain was initially invoked without its required --atomic argument; those two invocations are invalid and need rerunning. No full gate or benchmark was run. The Redis differential matrix, full original-parameter audit matrix, remaining shutdown/FLIP/persistence checks and final proof remain outstanding.

All executed commands were confined to CPUs 112-127; correctness servers used 112-119, clients 121-127, ports 22600-22699. The generic no-server rule was read with the task-specific focused PROOF authorization. No measurements were run while builds were active.

### Identity and layouts

| Check | PRE vs tested Stage A |
|---|---|
| Locked sizes and every existing field offset, both namespaces | Equal |
| AtomicScriptIntent / AtomicPendingState | 32 / 1352, equal |
| Server prior offsets including barrier byte | Equal; cold tail grows by 24,640 bytes |
| ex_loop.h / io_loop.h source | Unchanged |
| Hot object bodies (lbstall tool) | 1,178 / 1,204 equal; **26 differ** |
| Full canonical inventory (ccfix tool) | 15,723 / 16,441 equal |
| Command-handler inventory | 1,199 / 1,210 equal; all GET/SET handler bodies equal |
| Linked runtime sections | Differ; no byte-identity claim |

[Layouts](docs/txnfix/layouts-stage-a.json), [hot bodies](docs/txnfix/hot-stage-a.json), [full inventory](docs/txnfix/identity-stage-a/summary.json), [all changed bodies](docs/txnfix/identity-stage-a/changed-bodies.json), [linked sections and digests](docs/txnfix/linked-stage-a.json).

The following hot-body differences are unresolved. Cold transaction/pubsub/store additions changed GCC inlining decisions; that is an inference from identical hot source and the budget probe, not a proof of zero added executed instructions. An offline xshard budget probe improved identity but did not eliminate the differences and was not adopted.

| Object / body | Bytes PRE → POST |
|---|---|
| `db0/src/cmd/xshard.o` — `tomo_db0::FlatStore::find_in(int, unsigned long, tomo_db0::Slice) const` | 554 → 446 |
| `db0/src/cmd/xshard.o` — `tomo_db0::FlatStore::erase_in_read_local(int, unsigned long, tomo_db0::Slice, bool*)` | 732 → 606 |
| `db0/src/cmd/xshard.o` — `tomo_db0::FlatStore::insert_into_read_local(int, unsigned long, tomo_db0::KvObj*, bool)` | 1602 → 1493 |
| `db0/src/cmd/xshard.o` — `tomo_db0::FlatStore::insert_into(int, unsigned long, tomo_db0::KvObj*, bool)` | 975 → 899 |
| `db0/src/cmd/xshard.o` — `tomo_db0::FlatStore::erase_notify(unsigned long, tomo_db0::Slice, tomo_db0::FlatNotifySink*, tomo_db0::FlatStore::EraseEvent)` | 933 → 673 |
| `db0/src/cmd/xshard.o` — `tomo_db0::FlatStore::insert_notify(unsigned long, tomo_db0::KvObj*, tomo_db0::FlatNotifySink*)` | 941 → 737 |
| `db0/src/cmd/xshard.o` — `tomo_db0::FlatStore::find(unsigned long, tomo_db0::Slice)` | 1017 → 806 |
| `db0/src/cmd/xshard.o` — `tomo_db0::FlatStore::find_notify(unsigned long, tomo_db0::Slice, tomo_db0::FlatNotifySink*)` | 942 → 782 |
| `db0/src/core/reorder.o` — `tomo_db0::WbEngine::serve_impl<true, true, true, true, false, true>(tomo_db0::Client&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()(tomo_db0::Op&) const` | 1212 → 984 |
| `db0/src/core/reorder.o` — `tomo_db0::WbEngine::serve_impl<true, true, false, true, false, true>(tomo_db0::Client&, bool*)::{lambda(tomo_db0::Op&)#1}::operator()(tomo_db0::Op&) const` | 1212 → 984 |
| `db0/src/core/reorder.o` — `bool tomo_db0::ExLoopT<true>::execute<false, false>(tomo_db0::Task const&)` | 3623 → 3557 |
| `db0/src/core/reorder.o` — `tomo_db0::IoLoop::DispatchResult tomo_db0::IoLoop::parse_and_dispatch<false, 32u, false>(tomo_db0::Client*)` | 18353 → 18361 |
| `src/cmd/xshard.o` — `tomo::FlatStore::find_in(int, unsigned long, tomo::Slice) const` | 630 → 346 |
| `src/cmd/xshard.o` — `tomo::FlatStore::erase_in_read_local(int, unsigned long, tomo::Slice, bool*)` | 871 → 538 |
| `src/cmd/xshard.o` — `tomo::FlatStore::insert_into(int, unsigned long, tomo::KvObj*, bool)` | 1014 → 942 |
| `src/cmd/xshard.o` — `tomo::FlatStore::erase_in(int, unsigned long, tomo::Slice, bool*)` | 783 → 580 |
| `src/cmd/xshard.o` — `tomo::FlatStore::find_notify(unsigned long, tomo::Slice, tomo::FlatNotifySink*)` | 846 → 782 |
| `src/cmd/xshard.o` — `tomo::FlatStore::erase(unsigned long, tomo::Slice)` | 1109 → 543 |
| `src/cmd/xshard.o` — `tomo::FlatStore::insert_read_local(unsigned long, tomo::KvObj*)` | 1590 → 1287 |
| `src/cmd/xshard.o` — `tomo::FlatStore::erase_notify(unsigned long, tomo::Slice, tomo::FlatNotifySink*, tomo::FlatStore::EraseEvent)` | 812 → 673 |
| `src/core/reorder.o` — `tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 0u, false>(tomo::Client*) [clone .isra.0]` | 9880 → 9896 |
| `src/core/reorder.o` — `unsigned int tomo::ExLoopT<true>::sweep<32u, true, false, false>()` | 1536 → 1338 |
| `src/core/rl2s.o` — `tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<false, 32u, true>(tomo::Client*)` | 20932 → 20939 |
| `src/core/rl2s.o` — `tomo::IoLoop::DispatchResult tomo::IoLoop::parse_and_dispatch<true, 32u, true>(tomo::Client*)` | 20884 → 20932 |
| `src/snapshot/snapshot.o` — `tomo::FlatStore::find_in(int, unsigned long, tomo::Slice) const` | 540 → 346 |
| `src/snapshot/snapshot.o` — `tomo::FlatStore::erase_in(int, unsigned long, tomo::Slice, bool*)` | 621 → 580 |

### Measurement requested after correctness and identity work

No cost table has been measured. Do not interpret absent data as meeting the cost bar.

| Cell | PRE ops/s | POST ops/s | retries/s | exclusive/s |
|---|---|---|---|---|
| Uncontended EXEC, disjoint keys | pending | pending | pending | pending |
| Contended EXEC, 2 hot keys + 4 plain INCR clients | pending | pending | pending |
| GET/SET/MGET/MSET ABBA null | mainline | mainline | n/a | n/a |

The existing benchtxn exec driver only emits SETs to disjoint per-connection keys. It cannot express the requested contended cell; an explicit driver extension remains necessary. No fabricated contended command or rate is supplied. Existing uncontended command (owner only, after a quiet boot):

```sh
taskset -c 112-127 make build/benchtxn
taskset -c 121-127 build/benchtxn exec 127.0.0.1 22601 20 64 4 4 2
```

Mainline full-geometry ABBA request (owner runs on the quiet full box, not this lane):

```sh
taskset -c 0-127 tests/gate.sh perf --subset full \
  --server-cores 0-31 --server-smt "" --load-cores 32-127 --load-smt "" \
  --ports 22600-22699 \
  --reference-binary "$PWD/build/txnfix/pre/tomokv" \
  --candidate-binary "$PWD/build/tomokv"
```

Compare matched-load ops/s, cycles/op, instructions/op and IPC for GET/SET/MGET/MSET in both thread modes; use the gate instrument and its standing null. Static hot-body differences are enumerated above, so main-command cost is not yet accepted. No PAD arm has been built or named in this request; an appropriate labelled control remains part of the unfinished cost work.
