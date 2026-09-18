# multidb2 — round-2 report and measurement request

Worktree: `/home/user/Projects/cx-multidb`; branch `cx-multidb`. Round-1 base: `651d997e8`. Runtime implementation through `ef645d5fd`; gate/test fixes through `a6a3d229d`. The final artifact-control commit is also recorded in the branch history.

**Ready for maintainer validation; not a performance acceptance.** No server, gate, load generator, DB benchmark, or hardware-counter measurement was run. The last mainline phase announcement was `CODEX PHASE START: cx-multidb cx-r7shadow` at 02:16:39 on 2026-09-18 Taipei time; work began after that announcement. Builds and executable checks used CPUs 112–127. Archived source builds and throwaway controls are under this worktree’s ignored `build/`.

## 0. DB-0 path and controls

Round 1 already compares the 64-bit `(length, namespace)` identity in one comparison, and its default hash folds that identity into the existing initial multiply. Namespace zero produces the pre-multidb hash; adding another namespace hash/fold is unnecessary. Packing the full 32-bit length and eight namespace bits into 32 bits would reduce the accepted key-length range.

The candidate changes the record decoder: a short key without KeyExt necessarily belongs to DB 0, so the probe returns a zero-extended length directly. Round 1 decoded pointer, length and namespace independently, including repeated flag loads in the owner path. Extended and nonzero-namespace keys retain the existing decoder. No fixed-layout structure changed; the unit asserts Slice 16, Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144 and Config 624.

The ordinary, unremapped DB-0 parse path gains no epoch counter, allocation, lock, or stamp operation. Armed namespace stamping writes the map epoch into the command-name Slice’s existing namespace word. The new scheduler work is behind the existing dispatch pause or in the owner control tail, which gains a namespace-stage comparison per pass. The script fix adds decision handling only in the existing MVCC/pending-conflict paths; WATCH changes use cold reservations. These are source observations, not a zero-cost result. The default hash is unchanged; optional SipHash retains round 1’s namespace arithmetic.

**PAD kind A — behaviour twin:** `build/tomokv-multidb2-pad` executes round 1’s independent key pointer/length/namespace decoder in the candidate’s exact layout. It changes 85 annotated JNZ branches into unconditional branches (381 branch-instruction bytes total). Every other byte, section size and symbol address matches POST. Long branches retain their six-byte footprint using an unreachable padding NOP after the unconditional jump; PAD executes no added NOP. The annotation is a local ELF symbol and allocates no bytes. The cold correctness fixes remain in both arms; on the requested unremapped DB-0 cells, this control isolates the decoder mechanism. It is not a rollback of SWAPDB or script correctness.

`tools/multidb2_artifacts.py` creates and verifies the twins offline. Receipts: `build/multidb2-pad.json`, `build/multidb2-cost-pad.json`, `build/multidb2-unit-pad.json`. POST .text is 15,344 bytes larger than round 1; POST and PAD .text are exactly equal.

### Frozen artifacts

| Arm / artifact | File bytes | .text bytes | SHA-256 |
|---|---:|---:|---|
| `build/tomokv-multidb-pre` | 79299344 | 3557219 | `8f6da00365aced98eb925906ec2dfdb2ca9cf8995a40371ad48d7dfa5ff79034` |
| `build/tomokv-multidb2-pre` | 80603928 | 3547569 | `1189c0f9c6ac80ee6da9edd4250507965655c91cb7fcc2695c0b7bf3e3bfa1bd` |
| `build/tomokv-multidb2-post` | 80930056 | 3562913 | `b6ffa7d0cdf82bb5e23007bbea0e1a4beab32021074128bfd6e60a1679738c5b` |
| `build/tomokv-multidb2-pad` | 80930056 | 3562913 | `23be1a2a67ea46127ea08ed175b953b63ddcf57a697ce2dfe0e0ce6ee837ff48` |
| `build/multidb2-baseline/build/multidb-cost-unit` | 63829016 | 3134861 | `c98b11ca9823e5aceafbd136d932ecb3148e2716e1e0b7034ea5d9f28934dec4` |
| `build/multidb2-round1/build/multidb-cost-unit` | 65169000 | 3130257 | `6f28e0cc73061844de422d3ebb2da13fb7fe67e78398889b8bc51169cf8d62ab` |
| `build/multidb-cost-unit` | 65530824 | 3147025 | `2515a5f32f2a4acfdcf657efa48901753ccc59feaf23d61716e6ab6b142e99cb` |
| `build/multidb-cost-unit-pad` | 65530824 | 3147025 | `3942c69e48a2cd73747bdf2086bea972de09ca2504a9af234b50e2cb520158db` |

`build/tomokv` is the default POST build. The pre-multidb reference is the inherited `115da1721` build identified by the round-1 report. The round-1 PRE executable was copied before edits. The instruction instruments use the same `tests/multidb_cost_unit.cc` source against archived `115da1721`, archived `651d997e8`, and current objects. Their correctness-only `--self-test` passes for GET and SET. Hardware counters have **not** been collected.

### Maintainer measurement request

Use the gate’s instrument, the same quiet-box geometry and fixed 12-instance pins as the supplied round-1 measurements. Preserve offered load, population, key/value sizes, server/load placement, ratio, and instrumentation. Do not recalibrate between arms. Preserve complete per-arm rates, cycles/op, instructions/op, IPC, spread and null evidence in MEASURE-RESULT.

Run paired ABBA blocks for (1) round-1 PRE versus POST, (2) pre-multidb/v7 reference versus POST, and (3) POST versus kind-A PAD. Primary cells are h05/h07 (1s GET p32) and h21/h23 (2s GET p32). Include SET p32 counterparts h06/h08/h22/h24, m51, and the owner’s existing p8g1/p8s0/p8s1/f8g1 definitions. The p8 identifiers are from the task’s measured instrument; reuse those definitions rather than infer a different workload from their names.

**Decision:** DB-0 throughput must be indistinguishable from the matched v7 null. Recovering only part of the round-1 loss, passing a generic -3% threshold, or lowering instructions alone does not meet the landing bar. A decoder mechanism result needs POST to move relative to PRE while the kind-A decoder control remains consistent with PRE; both controls must also retain narrow spreads. Reject a noisy cell instead of widening its tolerance.

| Cell | Supplied round-1 rate delta vs v7 | POST vs v7 | PAD vs v7 |
|---|---:|---|---|
| h05 | -3.0% | pending | pending |
| h07 | -1.2% | pending | pending |
| h21 | -5.7% | pending | pending |
| h23 | -5.3% | pending | pending |
| m51 | -2.4% | pending | pending |
| p8g1 | -2.7% | pending | pending |
| p8s0 | -4.7% | pending | pending |
| p8s1 | -2.6% | pending | pending |
| f8g1 | -2.0% | pending | pending |

The preceding PRE numbers are supplied owner measurements, not results collected by this lane.

For the requested instruction unit, on one maintainer-selected pinned core run each of these four instruments with `--instructions GET` and `--instructions SET`, in ABBA order for PRE/POST and PAD/POST, at least three complete blocks:

```text
build/multidb2-baseline/build/multidb-cost-unit
build/multidb2-round1/build/multidb-cost-unit
build/multidb-cost-unit
build/multidb-cost-unit-pad
```

This unit parses and retires p32 batches through the real RESP parser, ROB, hash and GET/SET handlers: 4096 resident 24-byte keys, 128-byte values, 4,194,304 measured operations after warm-up. It prints instructions/op, cycles/op and IPC from one non-multiplexed hardware group; unavailable or multiplexed counters fail. It opens no listener or ring. It isolates parser/store work and does not substitute for the threaded ABBA rate verdict.

## 1. Global SWAPDB boundary

SWAPDB starts an existing FLIP dispatch pause, serialized against FLIP/LB/snapshot admission. Each IO tail acknowledges only after its published ROB operations have executed, including closing clients still in its active set. Replies need not be sent or retired. Existing executor quiescence then drains inboxes, deferred fragments, MVCC/apply work, read-local debt, notifications and AOF debt. Only the initiating connection and exact ROB position may dispatch during the boundary’s run stage; the existing all-shard SWAPDB rendezvous publishes the map. Done releases the pause. A cold Client reference protects an initiating frame that disconnects before publication.

This fences every old dispatched operation, including operations parsed concurrently with fence initiation before their IO tail acknowledges. No operation can retain an old physical stamp and execute after the swap. New parses stamp the new map epoch. Parked blocking commands are quiescent exceptions: their wakeups are held during the boundary and existing remapping resumes them afterward without changing deadlines. No new operation-path lock, seqlock, or reader retry was added.

`tests/multidb_boundary_unit.cc` runs the real IO/executor control tails at 16 shards, 6 IO + 2 owners in split mode and eight fused owners. Four p32 writers run for 32 epochs in each mode: all 8192 operation stamps are checked, all 64 delayed-dispatch windows must open, and the map must remain unpublished until every old operation executes. It also checks disconnect cleanup. Disabling `multidb_io_drained` in a throwaway executable fails at `delayed stamped writes hold boundary` (exit 1).

`tests/multidb_serial.py` is the new live serial-order battery, for maintainer execution only. Four clients pipeline SET/GET in DBs 0/1 while an independent client loops SWAPDB. Each writer has a unique key; all sends precede any writer reply collection, allowing the key projections to share one swap order. Final probes inspect both databases. The oracle finds a legal epoch for every reply respecting connection order and invocation/response constraints, or fails. The JSON stores the full history and its serial epoch witness. These network epochs are inferred witnesses, not a new wire-visible server epoch. Sixteen overlapping rounds must arm within 64 fresh-state attempts; a missing window fails. Its serverless controls accept both legal orders and reject the supplied stale-stamp counterexample. Live IO execution remains a maintainer gate requirement.

## 2. SWAPDB inside EXEC

Queued swaps evolve a private routing map in transaction order. SELECT/MOVE and later keys use that map. Every swap joins all shard participants. The final prepared map is published in the same atomic commit bracket as the transaction/child MVCC decisions, before the safe watermark advances and before ordinary dispatch resumes. Aborted EXEC publishes neither map nor epoch. Native AOF GroupDatabaseMap records share the transaction’s group commit marker.

The unit checks an exact nine-element SET/SWAPDB/GET/SELECT/GET/SET/MOVE/SWAPDB/GET array, own writes across both swaps, map/decision ordering, and a WATCH-aborted swap. Additional regressions cover swap-in/delete/swap-back and SET/delete-before-swap: WATCH records command-time presence and write-time logical identity, applies invalidations only on commit, and leaves an untouched absent key’s WATCH clean. The first history failed before its fix (`build/multidb2-transient-before.log`). These cold WATCH changes preserve all locked layouts.

## 3. Script APPLY diagnostic

**Pre-existing before multidb:** the unchanged original `post_apply_probe` was rebuilt at `115da1721` in `build/multidb2-baseline` and exited 1. Both script APPEND and foreign APPEND returned 2, with final `BW`; the committed script suffix had been lost. Evidence: `build/multidb2-script-baseline.log`.

Root cause: a foreign RMW after the first owner APPLY cloned the committed predecessor while the script’s candidate was still undecided. The script subsequently activated its reserved older ticket, so the foreign version hid the script’s update. The fix arbitrates a conflicting writer against script activation using CAS on the existing group decision word. Writer-first cancels the script with TRYAGAIN and writes from the committed predecessor; commit-first makes the writer clone the committed script image. The abort sentinel is never a readable MVCC version or a committed WATCH mutation. Readers still resolve immutable predecessors without waiting or retrying.

The promoted diagnostic forces both outcomes through the production script completion function, checks an intervening foreign GET, and checks both keys for partial script activation. All 16 atomic-survivor cases pass.

## 4. Native persistence and limits

The native snapshot/AOF round-trip unit compares the complete logical dataset, types, binary keys and absolute TTLs after standalone and transactional swaps. It replays grouped data and map records together, rejects both without their commit marker, and ignores a later uncommitted map record. The live multidb battery now adds explicit standalone and EXEC swap history before DEBUG RELOAD and DEBUG LOADAOF comparisons. Native framing/checksum/producer end-to-end execution is still owned by the live gate.

`databases` defaults to 16 and remains capped at 256 (indexes 0–255). README now documents the supported logical-database surface and native-format boundary. No Redis RDB/AOF interchange is claimed.

## 5. Gate and validation

Round-1 rows remain. This round explicitly requests a count bump, so EXPECT_QUICK/EXPECT_FULL are updated to **438/454**, from 428/444:

* New boundary row at `tests/gate.sh:1303`, collected by atomic_units at line 2685: +1 in both tiers.
* `post_apply_probe` in the loop at line 1315: +1 in both tiers.
* Serial-order row at line 2589, collected in eight multidb jobs at line 2786: +8 in both tiers.
* All three collection sites precede the quick-tier exit at line 2809. Total: +10 quick, +10 full.

Completed C++ validation: 70 serverless cases covering multidb, global boundary, p32 instrument self-tests, config, flip, both read-local rings, waits/rehash, all atomic survivors, networking/commands, storage/sidecar, ASAN/UBSAN core concurrency, owner arena and L4 prebuild in both modes with read-local off/on, overlap, command lookup, foreign-read filter and tailgen. The WATCH disconnect test’s one-fragment assumption also failed on archived round 1; its updated test verifies the exact namespace-alias shard set and drains every real owner fragment before checking client lifetime.

One unmodified utility result needs its history preserved: the concurrent sweep was 69/70 because tailgen’s 2 ms pacing-gap assertion failed. Its separate isolated rerun passed unchanged. See `build/multidb2-unit-results/tailgen-unit-concurrent-failure.log` and `tailgen-unit-alone.log`; the failed first result is retained in `summary.txt`. This is not a DB throughput measurement or a waived assertion.

POST/PAD multidb correctness and instrument self-tests pass. The baseline and round-1 instrument self-tests pass. The disabled-drain negative control fails as intended. `bash -n tests/gate.sh`, Python syntax checks and `git diff --check` pass. Detailed C++ logs are under `build/multidb2-unit-results/`; default build log is `build/multidb2-final3-build.log`.

Python serverless batteries passed: differ (7), differ fanout (18), process ownership (12), background environment (11), instrumentation (5), ABBA (89 + 10 + 7), and the serial-order oracle. The gate ledger fixture initially failed because its feature/ABBA slice included round 1’s later multidb collectors; the corrected five-case LedgerWiring suite passes, including independent old/new multidb verdict failures. Ancillary controls also pass: quiet-box predicates (8), measurement receipt checks (10), gate history (55), and tailgen outstanding-bound self-tests (3). The full scheduler/ledger suite then passed all 55 tests; its final log is `build/multidb2-unit-results/gates-final.log`. The original failed log remains available as `gates_test.log`. No live network battery, default-server boot, full/iteration gate, rate comparison or instruction-counter run has been performed. Those remain the maintainer’s required next steps; no performance claim is made.
