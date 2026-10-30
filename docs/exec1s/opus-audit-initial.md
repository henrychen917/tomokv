# exec1s critical-path and struct audit (X1, X3, X5, with X2 interactions)

I'm Claude Opus 5.5 (`claude-opus-5-5`) at maximum reasoning effort. I only read files: nothing was compiled, run, delegated or modified.

## Verdict

**No confirmed correctness defect in X1, X3 or X5 in the default POST image.** I found six contingent or informational items (C1–C6 below). None of them changes the semantics of D1–D10, amend1 or D4′.

Two caveats limit what this verdict is worth:
- **No executed correctness receipt exists for the final image.** The families run's ledger reads `PARTIAL 0 … NOT A RECEIPT`.
- **The branch has moved since d8cbb6596.** `refs/heads/cx-exec1s` is now `7665399068`, an amend of the X6 commit (reflog `.git/worktrees/cx-exec1s/logs/HEAD:96-97`). Every production hunk in the supplied diff matches the files I read, but I can't prove the amend touched only tests and docs.

## Findings, ranked by severity

**C1 · Low · X1 · latent crash from a tag-value collision**
- **The collision:** X1's `UrKind::WakeSent = 19` (`uring.h:78`) is the same value fliplisten already uses privately for `kListenerCancel = static_cast<UrKind>(19)` (`fliplisten.cc:9`).
- **Failure path:** if a WakeSent completion ever reached `IoLoop::on_cqe` without being rewritten, its `default:` arm (`io_loop.h:1165,1217`; `reorder.cc:1788,1840`) would call `fliplisten_cqe`. That function treats kind 19 as a listener cancel and dereferences a null `Listener*` (`fliplisten.cc:204-207`).
- **Why it can't happen today:**
  - Only fused executor rings set `track_owned_` (`ex_loop.h:196-198`).
  - Their completions are dispatched by `ExLoop::on_cqe`, which ignores unknown kinds (`ex_loop.h:2798-2809`).
  - WakeSent is rewritten to Wake before any callback or deferral (`uring.h:333,374,419`).
- **Repair:** give WakeSent an unused value (20), and reserve 18/19 in the enum or add a `static_assert` that they stay distinct.

**C2 · Low · X2 interaction · formal data race with read-local readers**
- **Path:** `atomic_publish_group` now updates four bytes at offset 1316 in one read-modify-write (`flatstore_atomic.inc:529-534`). Byte 0 of that word is `read_local_extended`.
- **Concurrent reader:** IO threads read that same byte on every foreign read-local probe: `read_local_parse.inc:250-256` → `flatstore.h:760-761` → `flatstore_atomic.inc:1027-1029`.
- **What changed:** before X2 the owner wrote only byte 1 (`group_installing`), which is a separate memory location.
- **Effect:**
  - The byte's value never changes after `flatstore_atomic.inc:1062`.
  - On x86-64 this is benign.
  - Under the C++ memory model it is a data race, and TSAN would report it.
  - No reader retries or seqlocks were added.
- **Repair options:**
  - Have the foreign probes use `read_local_store_state_armed()`. The code already documents this accessor as valid under the boot latch, and it never loads byte 0 (`flatstore_atomic.inc:1038-1045`).
  - Or split the update into `group_installing=false; ++group_records;`. This adds one store, so the atomic-MSET instruction-count receipt would need to be re-run.

**C3 · Low · X2 interaction · statistics can go stale**
- **What changed:** `ex_execute.inc:64` now calls `publish_size()` only when the key count changed. But `publish_size()` also publishes object bytes, the expires count, field-TTL counts and the evicted count (`storesize.cc:10-30`).
- **Why retries miss it:** multi fragments that run on a retry pass (`ex_loop.h:2484-2500` → `latency_tracking.cc:441-442` → `execute`) never reach the per-batch publish at `ex_loop.h:2365`.
- **Example:** a cross-owner `MULTI; EXPIRE a; EXPIRE b; EXEC`. One owner runs its EXPIRE on a retry pass, so `expires_` changes (`flatstore.h:967`) but the key count doesn't.
- **Effect:** INFO keyspace and memory, MEMORY STATS and the LB byte loads stay stale until that owner runs another task batch. X3 raises the share of fragments that complete on retry passes.
- **Severity:** not a data defect. `expires_` is already an approximate attention set.
- **Repair:** call `publish_size()` unconditionally. It already skips unchanged stores internally (`storesize.cc:13-29`).

**C4 · Info · X5 · participant order changed**
- **What changed:** watched shards are now discovered first (`multi.inc:926`). Before X5 they were appended after the command participants.
- **Production impact:** none; only the order tasks are posted changes.
- **Test impact:** the DEBUG hooks that pick a lead shard (`shards.front()` at `multi.inc:1850`, `shards[0]` at `multi.inc:2402`) now pick a watched shard whenever WATCH is present.
- **Repair (if the old order matters):** move the watched-shard loop from line 926 to just before `multi.inc:1152`. It must stay before the `database_watch` resize and before `prepare_claims`.

**C5 · Info · X5 · two invariants that hold but aren't enforced**
- **`database_watch` sizing:** it is resized at `multi.inc:1153`, before `prepare_claims` adds claim-only slots (`883-887`), so it can end up shorter than `claims`. This is safe because only participant shards index it (`1687`, `1937`).
- **`covered()` (`911-919`):** it assumes every write-key shard already has a slot. That holds only because no kind without owner work (`1497-1504`) keeps Write key arguments today: DEBUG and FLIP have no key range (`t_server.cc:3266-3270`), and WATCH inside MULTI is rejected (`2101-2103`).
- **Hardening:** resize `database_watch` after `prepare_claims`, and call `ensure_state_slot` for write-key shards. Both preserve current semantics.

**C6 · Info · X1 scope note**
- **Finding:** in this base, AOF and snapshot I/O run on the bound IO writer ring, which is never tracked (`aof.cc:1172-1185`; `io_loop.h:640-643,4348-4350`).
- **Consequence:** in production, owed-completion tracking is live only for WakeSent (`ex_loop.h:808` → `msg_to`). The persistence half is exercised only by the NOP fixtures in `tests/exec1s_unit.cc`.
- **Effect on the docs:** the design's premise that persistence completions travel on the executor ring doesn't hold here, so the D9 line in `rules.md` is true but vacuous.

## Requested property checks (all passed)

- **Single-owner writes:**
  - Each slot maps to one shard, so the per-slot arrays are still written only by that shard's owner.
  - Bells are atomics, X1's counters are per issuer, and the X2 group count is owner-local.
- **Immutable / QSBR reader safety:**
  - `shard_slots` is written only by IO before publication (every `ensure_state_slot` and `add_state_shard` caller runs before dispatch).
  - The extra passes publish read-local ticks through the same `RotationBoundary` (`ex_loop.h:379-386`).
  - No retries or seqlocks were added. C2 is the one caveat.
- **Same-client RYOW:** the resolve and overlay code is unchanged. Eager reclaim collapses only the decided prefix. The directed RYOW check in `reclaim_check` passes, and so do the execfix-v2 live rows.
- **Shard migration:**
  - Bells hold only a per-thread flag (`exec1s.h:1062-1063`).
  - The slot is looked up from the shard id the task carries (`multi.inc:2901-2905`), so a forwarded stale task resolves to the same slot on the new owner.
  - `worker_of_shard` is an atomic load (`server.h:1987-1992`).
- **Incoming, deferred and overflow completions:**
  - TASKRUN and overflow bits are checked in the needs-service test (`uring.h:184-188`).
  - Completions are counted when first reaped: in the raw loop, in the filtered loop, and once when a callback takes over the ring mid-loop (`uring.h:330-381`).
  - The fallback setup drops all flags. In epoll mode `inited_` is false, so the check is a no-op.
  - I found no persistent condition that would keep an idle thread from parking.
- **Registration / unregistration:** both happen on the issuer, inside `run_loop` (`io_loop.h:527-528`; `reorder.cc:772-773`). Teardown happens after the loop exits (`genthread.cc:114,196`), and no `shutdown()` runs on the issuer while the fd is registered (`shutdown.cc:146`).
- **Owed-completion accounting:** every AofIo, SnapshotIo and WakeSent submission is counted (`aof.cc:103-117`, `snapshot.cc:97-98,787-788`, `uring.h:406-408`). There is no other reaping path.
- **Guards in the extra owner turns:** both extra turns run the complete pass, including the LB freeze and ack, snapshot gating, `flush_xshard_commits` and read-local publication (`ex_loop.h:428-479`; LB acks at `1589-1628`).
  - R7 routes both turns to `r7_fused_baseline_pass`, and the generator asserts there are exactly two sites (`r7shadow_sync.py:112-117`).
  - The state lifetime outlasts every bell call (`multi.inc:3199,3211`).
- **Compact-map bounds:** every compacted array access goes through `slot()` or `ensure_state_slot()`. A sweep of the whole tree found no other accessors.
- **Claim-only metadata shards:** they keep their historical claims and get no tasks, which matches pre-X5 behavior.
- **WATCH and close states:** WatchAdd, Unwatch and Close states are still identity-indexed (`multi.inc:1185-1191`).
- **256-shard sentinel:** slot 255 is assigned only when the 256th slot is created. If there are 255 shards or fewer, 255 is never a real slot.
- **Spec-id classification:**
  - The lookup table is sized to the registry, which `commands.cc:217-221` forces to equal the generated count.
  - There is one registry row per public command (`command.h:176-178`), so DEBUG RELOAD and ACL subcommands still classify as DEBUG and ACL.
  - The spec substitutes keep the id: tracking (`climon.inc:42-44`), l4prebuild, and the notify and TLS rows.
  - There is no rename-command.
  - Queued commands come only from `queued_copy` or the rebuild copy.
- **Locked layouts:** all eight are still `static_assert`ed (Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob64 192, AtomicEntry 144, Config 624). X1's new `Ring` fields fit existing padding, and the `ExLoop`/`FusedExLoop` size locks (`ex_loop.h:2931-2932`) would catch any growth.

## Rule preservation

| Rule | Status | Basis |
|---|---|---|
| D1 | Preserved | Extra turns run the complete pass. No reader retries or waits added. |
| D2 | Preserved | Phase, wound and CAS logic unchanged; only the indexing changed. |
| D3 | Preserved | Blind-scan visitor unchanged. The count is incremented only at the single group-publish site, decremented at unlink, and the fast exit also requires fewer than 65536 live records. |
| D4′ | Preserved | Same cleanup and intent predicates, just called more often. Bells only schedule passes. |
| D5 (txnorder) | Preserved | Read-cut and pin code untouched. |
| D6 | Preserved | Whole-shard claims are still made per participant. |
| D7 | Preserved | Eager reclaim runs before the notification flush; this affects latency only. |
| D8 | Preserved | New counters live only in the shutdown report, not INFO. |
| D9 | Preserved | AOF ordering unchanged; see C6. |
| D10 | Preserved | WATCH validation still happens in the same placement turn; identity indexing kept. |
| amend1 | Preserved | Promotion still targets the same retry node, now looked up by slot. |

## Coverage of the risky paths

**No family-run receipt exists for the final image.**
- **Attempt 3:** its ledger reads `PARTIAL 0 … NOT A RECEIPT`, and `build/gate-run.Ib3klB/phases.tsv` stops at `parallel-begin`. It started at epoch 1793108745, before the X6 amend.
- **Attempt 2:** it ran the superseded image `7818c120…` and exited with status 130.
- **Final differentials:** the final uring differential driver log and the regenerated-families driver log are empty.

**What has executed:**
- Unit `ring`, `incoming`, `participants`, `reclaim` and `floor` pass.
- The poll-only and no-incoming falsifiers fail, as intended.
- `ring-no-overflow` also passes, so the overflow bit is not independently tested (already acknowledged).
- The execfix-v2 live run passed on a pre-final image.

**Paths with no directed coverage even after the queued families finish:**
1. X3 extra turns during key-LB shard moves under cross-owner EXEC streams. The `exec1s` live job pins `--key-lb 0 --client-lb 0` (`gate.sh:3093-3094`).
2. An owner actually executing at slot 255. Only the unit identity-map test covers 256 shards.
3. Executor-ring service triggered by real production sources (the signal-doorbell and database-wake polls) on an otherwise idle thread.
4. X3 combined with read-local fairlane turns, BGSAVE or AOF, or BLPOP-during-EXEC (the design's H3 cases). These are covered only incidentally by the pending generic suites.
5. A TSAN leg for C2.

The X2 race detectors (`multires` and `multirace`) are in the pending debug loop (`gate.sh:2977`). `atomic_floor` is only a throughput floor, so excluding it costs no correctness coverage.

## Limitations

- I reasoned about kernel io_uring behavior (TASKRUN set/clear, the local-work retry list, remote msg_ring completion) from upstream semantics. I did not check it against this 7.0 kernel's source.
- Tree identity: see the verdict caveat about `7665399068` versus d8cbb6596.
- Out of scope: X4 (I only confirmed it is behind its macro), the owner policies D1–D4, throughput, and the two acknowledged acceptance misses. I reviewed X2 only where it interacts with X1, X3 or X5.
