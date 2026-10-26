# execindex measurement and proof record

## execindex

Worktree `/home/user/Projects/cx-execindex`, branch `cx-execindex`, PRE
`3700b51d7fb3074f32330dd81f138efbf1ddd980`. No push. All lane execution is
restricted to CPUs 96–111 and ports 46800–46899. Throughput measurements are
maintainer-owned; this report makes no throughput claim.

A1–A5 are implemented and committed. Production code is frozen at `30f8cfa44`;
subsequent commits contain proof tooling, evidence, and the partial-job interface.
The extended runtime suite matrix is still in progress; this record will be
updated with every outcome, including failed attempts. No merge/push was done.

### Design corrections and boundaries

- Writer marks cannot assume append order equals stamp order: a multi-key episode
  reuses an earlier stamp when it acquires another key. The index orders marks
  by stamp and tests out-of-order stamp insertion against the frozen predicate.
- Existing tests additionally lock `WatchReservation` at 88 bytes. The held-entry
  handle lives in a wrapper, preserving that lock and all Shard offsets/stride.
- A shard can move before an old owner forwards its queued fragment. Intrusive
  promotion must check the node's atomic lane identity before touching links;
  a foreign lane does nothing, matching PRE's unsuccessful local deque search.
- Duplicate finalize probes can be removed only for exact claim keys. Capped
  whole-shard claims and inactive WATCH aliases retain their cold cleanup probes.
- Random events obey production phase transitions: a unit cannot re-enter PLACE
  after it starts execution. An initial unrestricted generator violated this
  precondition and manufactured a dirty waiter. The corrected generator covers
  arrival, placement, wounds, abort, decision/finish, validation, dirty deferral,
  writer mark/unmark/forget, readiness/all-units, and promotion.

### Implementation and current evidence

- PRE release build SHA-256:
  `957d19eafa7beb151bfae017ea6675fca1da40b334a100602fa3fd38764029f4`.
- A1: debug-only `registry_visits`; release INFO `atomic_txn_*` unchanged.
- A2: frozen linear registry and 10,000,000-operation controls, both namespaces,
  zero mismatches. See `docs/execindex/a2-oracle-{multi,db0}.log`.
- A3: 10,000,000 operations in each namespace, zero mismatches. See
  `docs/execindex/a3-oracle-{multi,db0}.log`.
- Final oracle: 10,000,000 operations per namespace, zero mismatches; the gate
  runs this in every 1s/2s × atomic 0/1 × uring/epoll cell. The frozen PRE
  implementation is selected only with `TOMO_TXN_ORACLE`. INFO is unchanged.
- Final entry visits at N=16/256/4096: place=3, finish=5, promote=1,
  key_ready=2 in every size. All N4096/N16 ratios are **1.00**. PRE controls:
  place=241.00, finish=248.273, promote=241.00, key_ready=227.667.
- PRE fails the new complexity bound. A throwaway copy with the older-waiter
  refusal removed fails the oracle at step 512. Both negative controls are
  recorded in `docs/execindex/negative-controls.json`; neither mutation is in
  production.
- Retry scheduling: 1,000,000 events, 651,458 polls, 333,333 explicit promotions,
  zero PRE-deque ordering mismatches. Foreign-lane promotion and handoff checks
  pass.
- Directed checks cover nonmonotone arrivals, an aborted node in the middle,
  exact lifetime-pin release, connection close retaining a published waiting
  EXEC, and shutdown unlinking before destruction. Both unit kinds are covered.
  Shard/other footprint locks and the additional 88-byte reservation lock pass.
- These are bounded-work claims for the tested contended queue, not universal
  worst-case O(1): out-of-order insertion can search backward, lazy dead-node
  pruning is amortized, and held/mark sets are still scanned. Whole-registry
  FLUSH/SWAPDB/wildcard paths deliberately retain their cold walks.

### Instruction checks and identity

All **48** final command-scope pairs are exactly PRE-equal: GET, SET, INCR,
MGET, MSET; batch 1/32; 1s/2s; both namespaces. MSET includes atomic 0 and 1.
`docs/execindex/instructions/comparison.json` contains the complete table.
Scopes execute linked production objects, validate exact replies/data, count
named Tomo routines, and exclude fixture/library callees. A deterministic clock
stub avoids timing-dependent control flow. These are instruction counts, not
throughput or an IPC verdict. Full trace logs stay under `build/execindex/`,
with SHA-256 and final log excerpts in the committed evidence.

The first build had MGET/MSET instruction increases from compiler spillover.
Per-unit IPA headroom was re-derived using compile-only PRE/POST controls,
then the full final matrix was repeated. Initial results and trial receipts
are retained, rather than mixed into the final table. The larger batch-32
fixture needed a 2-million-step trace ceiling instead of the inherited
1-million-step ceiling; exact reply assertions and scope boundaries are unchanged.

The requested 10-million-call `perf stat -e instructions:u` plain-writer
fixture also uses an inner hardware counter around only the call loop, so
serverless initialization/destruction does not decide the null. Both whole
process perf output and inner counts are in `docs/execindex/plain-cost/`.

| Case | PRE instructions/call | POST instructions/call | Verdict |
| --- | ---: | ---: | --- |
| a: has_watches false | 38 | 38 | equal |
| b: key absent from registry | 621 | 497 | lower |
| c: group-write reservation + foreign mark | 801 | 665 | lower |
| d: hot list, N=64 | 4466 | 1195 | lower |

The loop uses the real source implementation with the namespace's compiler
budget and no debug visit instrumentation. Counts include loop/call overhead;
the fixed counter-bracketing tail contributes approximately 90 instructions.

Identity audit: 1,414 selected bodies, 127 changed shared/enclosing bodies;
**zero direct command-handler differences**, including INCR and MGET/MSET's
`cmd_xshard_only` implementations. Shared `xshard_execute` bodies do change,
so this is not a claim that the entire executed graph is byte-identical. Every
changed body and its reason is listed in `docs/execindex/changed-bodies.json`;
resolved relocation targets are checked, not merely instruction mnemonics.
The maintainer's generic/main-command null remains required.

### Artifacts and PAD semantics

All paths below are under `build/execindex/`. Exact digests and sizes are in
`docs/execindex/artifacts.json`.

- `PRE`: `957d19eafa7beb151bfae017ea6675fca1da40b334a100602fa3fd38764029f4`.
- `POST`: `aee048859f6f8d84d5aa4e0b30767ad1e8dac4595d383ff634a8226027d1566a`.
- `POST-layout`: `f697182c2ae572f27dca7db51bc0d9babf7f0388c682a6294e6f36be051a63b1`.
- `PAD-A`: `660409393444a5b6c1f6442a6bb281fcc4cb9437f8fd8141c9177eb4c7468e52`.

PAD-A is explicitly **type A (behaviour twin)**. The exact-layout pair is
**POST-layout vs PAD-A**: both link POST plus a symbol-isolated PRE image,
with identical sections, function addresses and data. PAD-A changes only
five bytes at the program entry to execute PRE. POST-layout executes POST.
The production release `POST` is smaller and is a separate merit arm; do not
call PAD-A its exact-layout twin. Use release PRE vs POST for merit, and the
matched common-image pair as the layout control. The link/object/patch proof
is `docs/execindex/pad-a.json`. Both images pass 16 bounded correctness boots
(1s/2s × both engines × db1/db16), including EXEC, WATCH abort and zero order
violations. No rates were measured.

`PRE-visits` and `POST-visits` are separate debug counter images, built from
the A1-only PRE and final source respectively. `debug-artifacts.json` records
objects, commands and digests; `debug-smoke.json` proves counters fire in all
16 mode/engine/namespace boots. Use `DEBUG TXN-REGISTRY-VISITS` deltas divided
by completed EXECs for the requested depth test. Do not compare debug timing
with release throughput.

### Gate bookkeeping and runtime proof

The new oracle and complexity aggregate rows are collected at
`tests/gate.sh:5550`, before the quick-tier exit at line 5653. DQ=+2, DF=+2. **Maintainer must change 798/815 to 800/817.**
Neither EXPECT constant was edited. The independent label inventory agrees
with all 817 declarations and has no missing/extra label; its count check
intentionally refuses the unchanged EXPECT_FULL=815.

`python3 tests/gates_test.py` passed all 72 tests after the final gate edits.
`make all` passed; every production-unit target and both live-control builds
passed `make -q`, including the blockfix release digest binding: 49 freshness
checks, zero failures (`docs/execindex/freshness.json`).

Initial gate evidence: 25 passing rows, no failures in `build/gate-run.BWdImp`.
The final-index rerun passed 3/3 rows in `build/gate-run.NzvzPo`. Runtime
matrix results below will distinguish final-code runs from earlier evidence.
One subsequent fused/atomic-0 txnorder run failed the unchanged 40 ms writer
bound at 49.894 ms while this lane also ran compilers/GDB traces; values
were correct and order violations stayed zero. The failed ledger is retained
(`build/gate-run.aiaiHU`). Further launches were paused until compilation
and tracing finished; unchanged-bound idle-CPU repetitions are required.

The fused/uring `debug-0` job subsequently recorded one bare RENAMENX error
(`ERR no such key`, iteration 2877) while MGET showed the losing source still
present. Its preceding transactional race passed. The earlier batteries had
left `atomic=1`, which the RENAMENX driver recorded explicitly. This is an
unresolved correctness failure, not classified as noise or attributed to PRE.
Clean-server controls on both release arms each passed 16 repetitions of the
unmodified test: 131,072 transactional and 131,072 bare race iterations per
arm, with zero order violations. Full debug-sequence PRE/POST controls are in
progress; `docs/execindex/nx-control/` retains the clean controls.

Three epoll feature cells failed only their servertail throwaway boots with
`bind: Address already in use` on port 46802. The socket inspection observed
TIME_WAIT client connections from 46802 to another lane's ports 47800/47801
(`docs/execindex/port-46802-collision.log`). No foreign process or system
network setting was changed. These failed attempts remain in the archive;
the affected complete jobs will be rerun within the allocated port range.

The atomic RYOW battery's existing speed comparison is excluded only in
selected diagnostic jobs through `GATE_PROOF_NO_RATES=1`, which passes its
existing `--no-rate-assertions` flag. Every correctness check still runs and
the driver explicitly prints SKIP for the rate claim. Full gate/receipt
behavior is unchanged. `flip_saturated`, `atomic_floor`, performance arms
and full iteration are NOT RUN under the lane's runtime restriction.

### Maintainer measurements required

NOT RUN in this lane: performance/load generators and full gate iteration.

- `calib/exec-merit.py`: `--conns 16`, `32`, `64`, `128`; all eight cells
  (1s/2s × atomic 0/1 × hot/uncontended), ABBA against PRE. Capture the unchanged
  `atomic_txn_*` deltas, including `atomic_txn_order_violations=0`.
- `calib/exec-depth-sweep.py` in BOTH `--mode 2s` and `--mode 1s`, cross-owner,
  same-owner/different-shard, and same-shard; 16x1, 16x4, 32x4, 64x4, 128x4,
  three blocks per cell. Binding cross-owner/same-owner criteria:
  median(64x4)/median(16x4) >= 0.90 and
  median(128x4)/median(16x4) >= 0.85.
- Exact-layout control: add ABBA POST-layout vs PAD-A to the same merit/depth
  cells; compare the direction of the matched-image difference separately
  from release PRE vs POST. PAD-A is type A, as defined above.
- Debug visit depth check: visits/completed EXEC at 128x4 <= 1.25 times 16x4;
  place_waits/EXEC flat within ±20%. Debug timing is not release throughput.
- Redis 7.4.10 context: merit-grade 3 blocks, 64 conns × pipe 4, four plain
  clients, io-threads 4 and io-threads-do-reads yes. Verify that the current
  driver actually supplies the Redis hot keys and plain clients (the design
  documented a defect in an older driver). Do not compare a private-key Redis
  cell with a hot-key TomoKV cell.
- Main-command null: the 14 generic cells plus 2s GET/SET at p1/p32. Use matched
  offered load, cycles/op, instructions/op and IPC; ex_loop.h changes require
  this null even when command bodies and serverless counts agree.

Single-shard write EXEC uses the same registry (`execute_watch_phase` calls
`watch_place_unit` even with one shard; only the arrival barrier is skipped).
From the owner's supplied single-shard probes, relative to 541k at 16x4,
64x4 is 0.776–0.815 and 128x4 is 0.782–0.786. These are supplied baseline
ratios, not measurements of this candidate. Same-shard POST ratios remain
NOT RUN pending the maintainer sweep.

Both modes share the indexed registry and intrusive owner lanes. In 1s the
same scan removal applies, while parsing/reply work remains in the fused
owner pass. The previous design's 2s constant-cost estimate does not establish
1s performance; report 1s depth ratios, visit counts, poll counts, and owner
profiles separately. No 1s throughput improvement is claimed here.

The supplied `exec-profile/SWEEP.txt` identifies its headline as `05a5e01a9`;
those probe rates are context, not measurements of the requested PRE commit
`3700b51d7`. Re-establish the latter with the supplied PRE artifact.
