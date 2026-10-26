# execindex measurement and proof record

## execindex

Worktree `/home/user/Projects/cx-execindex`, branch `cx-execindex`, PRE
`3700b51d7fb3074f32330dd81f138efbf1ddd980`. No push. All lane execution is
restricted to CPUs 96–111 and ports 46800–46899. Throughput measurements are
maintainer-owned; this report makes no throughput claim.

Implementation/proof work is in progress. The final revision of this file will
list the committed implementation, exact binaries and digests, gate results,
remaining limitations, and the requested measurement cells.

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

### Evidence obtained so far

- PRE release build SHA-256:
  `957d19eafa7beb151bfae017ea6675fca1da40b334a100602fa3fd38764029f4`.
- A1: debug-only `registry_visits`; release INFO `atomic_txn_*` unchanged.
- A2: frozen linear registry and 10,000,000-operation controls, both namespaces,
  zero mismatches. See `docs/execindex/a2-oracle-{multi,db0}.log`.
- A3: 10,000,000 operations in each namespace, zero mismatches. See
  `docs/execindex/a3-oracle-{multi,db0}.log`.
- A3 complexity: at N=16/256/4096, candidate visits are respectively constant
  at place=5, finish=5, promote=1, key_ready=4. Every N4096/N16 ratio is 1.00.
  PRE ratios are 241.00, 248.27, 241.00 and 227.67. This is an entry-visit
  count, not an instruction count or throughput measurement.
- A4 scheduling fixture: 1,000,000 events, 651,458 polls, 333,333 explicit
  promotions, zero deque-order mismatches; foreign-lane/handoff checks pass.

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
