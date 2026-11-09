# MEASURE-REQUEST blockrace

## blockrace

S1 fix for the two pre-existing blocking-completion offer races flagged in
`round6-read/blocking-completion-races-analysis.md` and the aofblock report's
"Open for the owner: blocking completion offer races". Both are reproduced
deterministically on the PRE code and then fixed. No throughput benchmark, ABBA,
NIC cell or full gate iteration was run.

Base `fdbb19ba8e` (aofblock tip). CPUs 20-39, ports 26600-26699, `LC_ALL=C`.
All edits are in `src/cmd/blocking.inc` (cold blocking code); no `src/` comment
outside the changed lines was touched.

### The two races

- **(a)** `blocking_publish_completion` does `phase.store(Completed)` then
  `active_tasks.load()`; `blocking_task_done` does `active_tasks.fetch_sub()`
  then `phase.load()`. Two atomics, no fence, no shared RMW -- an SB/Dekker
  store->load pair. **Two offers**: a late second offer completes whatever
  `rob().at(op_id)` now names on the recycled slot with the pop's reply (wrong
  reply to a later pipelined command). **No offer**: the popped element is never
  published and the client hangs. `honour_cancel` has the same shape.
- **(b)** `blocking_publish_completion`, `blocking_task_done` and
  `blocking_finish_cancelled` read `*state.server` / `state.client` AFTER
  `op.state.exchange(Done)`. In 2s the IO thread can retire the op and free the
  `BlockingState` in between -> heap use-after-free read.

### Fix

- **(a)** `blocking_publish_completion` now `active_tasks.fetch_add(1)` before
  storing `Completed`, then finishes through `blocking_task_done`, exactly as
  `blocking_request_move` does for `MovePending`; `honour_cancel` does the same
  `fetch_add(1)` before its `Cancelled` hand-off through `blocking_task_done`. The
  single final `fetch_sub` selects exactly one publisher. **Plain counts, no
  sticky high bit**, so `active_tasks` still returns to 0 and
  `flip_liveness.inc:189` / `blocking_namespace_quiesced` are unchanged (unlike
  the reverted WIP `6a84de0e69`, whose `kReady` bit wedged FLIP drain).
- **(b)** `blocking_task_done`'s Completed branch and `blocking_finish_cancelled`
  capture `server`/`client` into locals before the Done exchange, as the
  `MovePending` branch and the scatter engine already do.

### Reproduced first (each schedule FAILs on PRE, PASSes on the fix)

| Finding | Reproduced on PRE | Fixed |
|---|---|---|
| (a) two-offer | YES: `blockrace-unit two-offer` FAILs 4/4 (1s/2s x normal/db0). The second offerer publishes the pop; the recycled later command is force-completed with the pop's reply. | YES: PASS 4/4 |
| (a) no-offer | YES: `blockrace-unit no-offer` FAILs 4/4. phase=Completed and the reply is composed, but the op is never set Done (hang). | YES: PASS 4/4 |
| (b) read-after-Done UAF | YES: ASAN `heap-use-after-free READ of size 8` at `blocking_publish_completion` (blocking.inc), freed by thread T1 via `blocking_state_release -> operator delete(BlockingState)`, read by thread T2. | YES: ASAN clean, `PASS BLOCKRACE-UAF-NO-READ-AFTER-FREE`, 0 ASAN errors |

Deterministic hooks (both compile out of production):
- `TOMO_BLOCKING_COMPLETION_UNIT` -- a function pointer called between the phase
  store and the participant decision in `blocking_publish_completion`
  (`tests/blockrace_unit.cc`).
- `TOMO_BLOCKING_UAF_UNIT` -- a function pointer called after the Done exchange
  and before the post-Done read; a two-thread witness frees the state there
  (`tests/blockrace_uaf_unit.cc`, ASAN, JE=0).

`calib/binary-neutral.sh` reports **IDENTICAL (11167504 bytes after stripping)**
between `build/tomokv` built with the hook source (macros undefined) and the
pristine base build -- the hooks add zero bytes to production.

### Hot paths (task 5)

Symbol-level audit `tools/aofblock_artifacts.py audit PRE POST`. The
GET/SET/MGET/MSET/INCR path is unchanged:
- The core plain dispatch -- `xshard_plain_prepare`, `xshard_plain_finish`,
  `exec_batch_prefetched`, `xshard_execute`, `multi_plain_write_committed`,
  `parse_mpop`, `read_local`, `FlatStore::find` -- is **instruction-identical**
  PRE==POST.
- GET/SET/MGET/MSET/INCR handlers live in `t_string.o`, which this change does
  not touch.

The fold net-shrinks the xshard IPA unit (normal 137236->137180, db0
136936->136873), so the pinned `large-unit-insns` budgets were re-derived to keep
the PRE headroom: **normal 168554->168498, db0 172028->171965** (Makefile). A
five-point db0 budget scan confirmed 171965 is best: it keeps the hot dispatch
identical, whereas 171981 disturbs `xshard_plain_prepare` and 171933 disturbs
`FlatStore::find`.

Residual content changes beyond the blocking functions after the re-derivation
(cold inlining ripple from the unit-size change, not source edits; **none on the
GET/SET/MGET/MSET/INCR path**): `prepare_sort_deref` (SORT), `txn_blind_scan`
(EXEC/WATCH), `notify_reserve_chain` (keyspace notify), `xshard_multi_child_complete`
+ `multi_owner_pass_entry_impl` (MULTI), and in db0 only `classify_keys` (+1,
multi-key classify), `atomic_tripwire_ticket`, `flip_immovable_refused`.
Inventoried for merit review, as the Makefile budget notes do for prior lanes.

### Rows / row delta

New counted job `blockrace` (`job_blockrace`, built via `tools/blockrace.mk`):
**2 rows** -- `blockrace BLOCK-COMPLETION-two-offer` and
`blockrace BLOCK-COMPLETION-no-offer` -- each run across 1s/2s and both
namespaces. **Row delta: DQ=+2, DF=+2.** `EXPECT_QUICK`/`EXPECT_FULL` and the
label fixture were NOT edited (maintainer-owned). With the aofblock +36 pending,
they land at EXPECT_QUICK 1250 / EXPECT_FULL 1267. The (b) ASAN use-after-free
witness runs outside counted rows (as aofblock's shim checks do).

Label-fixture unittest (`python3 -m unittest gate_ledger_fixture`, PYTHONPATH=tests):
refuses as designed -- **12 tests, 2 failures, 1 error**; it reports source
declarations **1268** vs fixture/EXPECT_FULL **1229**, and lists exactly
`'blockrace BLOCK-COMPLETION-no-offer' (x1)` and
`'blockrace BLOCK-COMPLETION-two-offer' (x1)` as the lane's missing labels
(alongside the 36 pending aofblock labels and a pre-existing writeback label). No
EXPECT or fixture edit was made.

`python3 tests/gates_test.py`: run (serverless stubs); result in the gate-rows
section below.

### Merit arms (`/home/user/Projects/bins/`)

| Arm | Path | SHA-256 | Notes |
|---|---|---|---|
| PRE | `/home/user/Projects/bins/blockrace-PRE-edc443e7` | `edc443e745b253c4de5a1a37aa615a7f2f33a3d5fe0b199651f1d11cf81386d3` | base fdbb19ba8e, clean |
| POST | `/home/user/Projects/bins/blockrace-POST-37ad4491` | `37ad44915194172079813b660bab036a263fc4f241457a4bb591467d79f0c064` | fix, budgets 168498/171965, clean |
| PAD-A | `/home/user/Projects/bins/blockrace-PADA-3b8605a8` | `3b8605a8b8421134a7f0d087a8aaa23a5a040f337a9ed7dc6264a7d23a656ed6` | PRE blocking behaviour in the POST build (see below); binary-neutral DIFFERENT from both PRE and POST |

PAD-A note: an aofblock-style exact-layout byte-twin is **not constructible** for
this fix, because it restructures the blocking functions
(`blocking_publish_completion` 61->3 instructions), so there is no
byte-length-preserving PRE->POST behaviour patch. PAD-A is therefore built from
the POST worktree with `blocking.inc` reverted to PRE behaviour (POST budgets),
isolating the (a) behaviour change within the POST build family. It is also not
needed to separate layout from behaviour on the headline commands:
GET/SET/MGET/MSET/INCR never call the blocking functions and are proven
instruction-identical PRE==POST, so a PRE-vs-POST delta on those commands is a
pure layout effect with no behaviour confound.

### Gate rows run (job interface, `GATE_PROOF_NO_RATES=1`, epoll, CPUs 20-39)

| Check | Result |
|---|---|
| `python3 tests/gates_test.py` | **83/83 OK** (610 s; serverless stubs), incl. the nested 14/14 persistfix identity tests |
| Label-fixture unittest | refuses as designed (12 tests, 2 failures, 1 error); the 2 blockrace labels are the lane's declared delta |
| `blockrace BLOCK-COMPLETION-two-offer` / `-no-offer` (via `job_blockrace`, final POST objects) | **ok** (8/8 sub-runs: 1s/2s x normal/db0, both schedules). Run before the fix: FAIL 8/8. |
| `flipfix7_blocked` (FLIP blocked-connection liveness, the active_tasks==0 drain gate) | **PASS** 4/4 configs (db 1/16 x read-local 0/1); "PASS flipfix7 post 12" each (blocked/blocked-stay/blmove-stay x uring/epoll x atomic 0/1). The `blocked` case refuses FLIP at `flip_immovable_refused` (the `active_tasks==0` gate); the `-stay` cases complete FLIP and drain the blocked connection (`flip_completed=1`, `flip_skipped_blocked=1`), `flip_conservation_violations=0`. Confirms the plain-count fix does NOT wedge FLIP drain (the failure the reverted WIP's `kReady` bit caused). |

Harness note: `GATE_ONLY_JOBS="blockrace flipfix7_blocked" tests/gate.sh quick --candidate-binary
build/tomokv` planned correctly (blockrace is wired into JOB_NAMES/collect_job/production-units),
but its `production_units` prerequisite rebuilds the entire unit suite (incl. ASAN object trees) and
was disproportionately slow on this shared, heavily-loaded box. The two rows above were therefore run
through the exact `job_blockrace` / `job_flipfix7_blocked` invocations directly against the POST
binary, not the full prerequisite pipeline.

Build hygiene: `make all` (rc 0) then `make -q all` **rc 0** (up to date); `build/tomokv`
is binary-neutral IDENTICAL to the staged POST arm.

### NOT RUN
- No throughput benchmark, ABBA, NIC cell, perf gate, or full gate iteration
  (maintainer-owned), and no EXPECT/label-fixture edits.
- The exhaustive "every blocking/multi/flip/lb/persistence row in every declared
  mode" sweep was not run under box contention; a decisive subset was (above).
