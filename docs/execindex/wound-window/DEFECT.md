# AT4-WOUND-1: a wounded atomic group can commit before its cancellation is published

- **Status:** pre-existing on the headline `3700b51d7`. The execindex lane inherits it unchanged
  (production code frozen at `30f8cfa44`, release `POST` aee04885). This lane does **not** fix it.
  Fix lane: `woundfix` (register P9, `round4-read/REGISTER.md`, addendum 2026-10-26 11:28).
- **Class:** server-atomics, isolation (wrong reply). Data is not corrupted in the observed case.
- **Anchors:** `file:line` at `3700b51d7`. `txn_group.inc`, `scatter_engine.inc`,
  `xshard_commands.inc` and `server.h` are byte-identical in PRE and POST, so their line numbers
  hold for both. `multi.inc`, `multi.h` and `ex_execute.inc` give PRE numbers, with POST in
  brackets where they differ. `source-identity.json` records the file digests, the identical
  `txn_wound` body and the identical wound predicate.

## 1. Symptom

The fused/uring `debug-0` job (`build/gate-run.G2pyOc`, POST) ran `tests/txn_nx.py`. Earlier
batteries in the same boot had left `atomic=1`, so the bare (non-transactional) race also ran.
Two clients race `RENAMENX k0 k2` and `RENAMENX k1 k2`. `k0` and `k1` share one shard, and `k2`
lives on another owner (geometry `[[7,7],[7,7],[5,5]]`). Exactly one client must win (reply `1`).
The other must answer `0`, because the destination exists.

Iteration 2877 failed:

| | client A, `RENAMENX k0 k2` | client B, `RENAMENX k1 k2` |
|---|---|---|
| Reply | `ERR no such key` (wrong: `k0` existed throughout) | `1` |
| Data after the round | `k0 = winner-a` (still present) | `k1 = nil`, `k2 = winner-b` |

The data is conserved. Only A's reply is wrong: it reports a missing source that existed at every
ticket, so no serial order explains it.

## 2. Serverless reproduction (no server, no threads, no delays)

`tests/txnorder_wound_window.cc` drives the production phase functions on a two-shard RENAMENX
group. It applies the exact first step of a foreign `txn_wound` (the phase CAS, `multi.inc:3230`)
and stops before the second (the epoch CAS, `multi.inc:3233`). It then lets the source owner run
the group's phase one and the commit decision.

All eight cells fail identically (`results.json`; logs `{pre,post}-{multi,db0}-{1s,2s}.log`):

| Arm | Namespace | 1s | 2s | Fields (every cell) |
|---|---|---|---|---|
| PRE `3700b51d7` | multi | FAIL (exit 1) | FAIL (exit 1) | `read_done=1 pre_epoch=0 aborted=1 no_such_key=1 source_present=1 commit_accepted=1 final_epoch=1` |
| PRE `3700b51d7` | db0 | FAIL (exit 1) | FAIL (exit 1) | same |
| POST `30f8cfa44` | multi | FAIL (exit 1) | FAIL (exit 1) | same |
| POST `30f8cfa44` | db0 | FAIL (exit 1) | FAIL (exit 1) | same |

The diagnostic and the live sample share the same reply (`NoSuchKey`), the same data shape (the
source is present and the destination unchanged by A), and an accepted commit.

## 3. The interleaving

A is the younger group and B the older one. Both are bare `--atomic 1` RENAMENX groups. At
`--atomic 1` RENAMENX is an `atomic_apply`, two-hop kind and not `atomic_direct`
(`scatter_engine.inc:272-277, 1837-1841, 2058`). It therefore gets a `TxnGroupAttempt`
(`txn_group.inc:21-80`) and reads its sources in phase one through
`txn_group_read_prepare` (`scatter_engine.inc:2905`). S is the source shard (owner O_S), and D is
the destination shard (owner O_D, which is not O_S).

1. **O_D places A.** A's write claim on `k2` is appended (`txn_group.inc:178`). A now has 1 of its 2
   placements, and its phase stays `Placing`.
2. **O_D places B.** B finds A's claim: a younger holder that is still placing. B wounds it
   (`multi.inc:3291-3294` [POST `txn_key_queue.inc:132-134`]) by calling `txn_wound`
   (`multi.inc:3227` [POST 3252]):
   - `multi.inc:3230-3231` [3255-3256]: CAS A.phase from `Placing` to `Wounded`. **This succeeds.**
   - **O_D is delayed here, before `multi.inc:3233` [3258], the epoch CAS.**
3. **O_S runs A's source fragment.** `scatter_engine.inc:2905` calls `txn_group_ready`
   (`txn_group.inc:233`):
   - `txn_group.inc:178`: the claim on `k0` places (nothing conflicts). Line 181: placements reach
     the participant count.
   - `txn_group.inc:183-184`: CAS phase from `Placing` to `Executing`. **This fails** (the phase is
     `Wounded`).
   - `txn_group.inc:185`: `aborted = true`. **The epoch is still 0.** Line 186 returns false.
   - `txn_group.inc:234-235`: because aborted is set, the result is `TxnGroupRead::Done`.
   - `scatter_engine.inc:2906-2908`: `Done` becomes `ScatterTaskResult::Complete`, which skips the
     RENAMENX source read (`scatter_engine.inc:3512-3530`). `images[0].present` stays false.
4. **Same owner pass: completion.** The path runs `ex_execute.inc:177-184` →
   `scatter_engine.inc:3916-3917` → `txn_group_complete`:
   - `txn_group.inc:306`: pending reaches 0. A's D fragment completed in step 1.
   - `txn_group.inc:425`: `finish_phase1` sets `NoSuchKey`, because the source image is absent
     (`xshard_commands.inc:1285-1288`).
   - `txn_group.inc:427`: the epoch is not cancelled (it is still 0), so there is no
     `txn_group_retry`. Line 431 returns `CommitQueued`.
   - `ex_execute.inc:187-189` calls `xshard_queue_commit`, which accepts epoch 0
     (`scatter_engine.inc:4052-4055`).
5. **Commit flush.** Inside `atomic_commit_batch`, `txn_group_decide` (`scatter_engine.inc:4102`,
   `txn_group.inc:252-256`) CASes A.epoch from 0 to its ticket. **This succeeds: the commit is
   accepted.** Next, `scatter_engine.inc:4119-4129`: aborted is set, but the epoch is a ticket, not
   `kAtomicCancelledEpoch`, so the retry branch (4122-4127) is skipped. The flush runs
   `aof_abort_scatter_group` (4129) and replies from `final_reply = NoSuchKey`, which renders as
   `ERR no such key` (`xshard_commands.inc:1858`).
6. **O_D resumes.** `multi.inc:3233` [3258]: the epoch CAS fails, because the epoch now holds A's
   ticket. `GroupWounds` is not counted and the aborted store is skipped. `txn_wound` still returns
   true. A's entries are decided, so they are no longer live. B places and executes
   `RENAMENX k1 k2`, which returns 1.

The outcome is replies `[ERR no such key, 1]` with values `[winner-a, nil, winner-b]`: exactly the
live sample.

**Width.** Steps 3-5 must all happen between two adjacent atomic instructions of `txn_wound`
(`multi.inc:3230` and `3233`). O_D therefore has to be delayed exactly there, by an interrupt, an
IPI or preemption on its CPU. That is why the failure is rare:

| Arm | Bare `--atomic 1` RENAMENX iterations | Failures |
|---|---:|---:|
| POST | 229,376 | 1 |
| PRE | 163,840 | 0 |

The counts come from the debug-job batteries plus the `nx-control` clean boots (MEASURE-REQUEST).
At this rarity, 1 failure against 0 cannot distinguish the arms. The serverless diagnostic holds
the window open deterministically, and it fails on both.

The blind-crossing restart has the same two-step publication: phase at `txn_group.inc:147`, epoch
at `txn_group.inc:150`. Another owner of the same group running step 3 inside that gap gets the same
outcome.

## 4. Why D2's wound-wait guarantee is broken

`design-txnorder.md` states the protocol in three places:

- §2.5, the wound: "CAS the victim's phase from 0 to 2. If that succeeds, cancel the victim's
  decision: CAS the epoch from 0 to cancelled and store `aborted`". The wounded unit then restarts
  with its original version.
- §2.4 step 3: "If the CAS fails (phase 2, wounded), the attempt is cancelled and takes the
  aborted path."
- §3.1: "A wound before all placements are done discards only reads."

The implementation publishes the wound in two steps. The victim treats a failed Executing CAS as
"aborted" (`txn_group.inc:185`) but not as "cancelled": the epoch stays 0 until the wounder's second
CAS. Every later consumer distinguishes the two states:

- `txn_group_complete` retries only on `epoch == kAtomicCancelledEpoch` (`txn_group.inc:389, 397,
  427`).
- The commit flush retries only on a cancelled epoch (`scatter_engine.inc:4122-4123`). Otherwise
  it treats `aborted` as the command's own terminal result. That is right for a failed MSETNX
  condition (`txn_group.inc:372-380`), but not for a wound.
- `txn_group_decide` accepts epoch 0 (`txn_group.inc:254-256`). Its comment covers only the gap
  between the doomer's epoch CAS and its aborted store (`txn_group.inc:258-261`), not the earlier
  gap between the phase CAS and the epoch CAS.

So the wounded unit is decided with a ticket. It neither restarts, which D2 requires, nor
serializes: its reply describes a state that existed at no ticket. In addition, the wounder's
`GroupWounds` count is lost. D2's two properties ("a unit is restarted only by strictly older
units, and only before execution" and "a wound discards only reads") do not hold for a victim that
crosses this gap. Its discarded reads become its reply.

## 5. The same pattern elsewhere (not observed live)

- **EXEC units.** The last placement's failed Executing CAS also stores only `decision.aborted`
  (`multi.inc:1794-1798` [1813-1817]). The finalizer restarts only when the epoch is already
  cancelled: it computes `doomed` at `multi.inc:3026-3027` [3051-3052] and retries at
  `multi.inc:3046` [3071]. A wounded EXEC whose finalizer runs inside the same gap therefore
  returns `Final`, an aborted EXEC reply, instead of restarting. Its gap is much harder to hit,
  because every fragment must join first. The transactional half of `txn_nx` has never failed. The
  fix should still cover both sites.
- **Allocation failure.** A failure inside `watch_place_unit` (`multi.inc:3337-3339` [POST
  `txn_key_queue.inc:183-185`]) also sets `aborted` with no cancelled epoch and no `WorkError`. A
  bare group would then answer from an unmaterialized image instead of reporting OOM. This is not
  the live failure (there was no memory pressure), but it reaches the same terminal arm.

## 6. Smallest fix

The victim should complete the cancellation it has observed. In `txn_group_ready`, when the final
placement's phase CAS fails (`txn_group.inc:183-186`), cancel the epoch before publishing
`aborted`:

```cpp
TxnPhase placing = TxnPhase::Placing;
if (!attempt->phase.compare_exchange_strong(placing, TxnPhase::Executing,
                                            std::memory_order_acq_rel)) {
    // Only a wound or a blind restart leaves Placing here, and both publish Wounded
    // before cancelling. Finish that cancellation so txn_group_complete, the commit
    // flush and txn_group_decide all observe kAtomicCancelledEpoch and retry.
    uint64_t zero = 0;
    state.epoch.compare_exchange_strong(zero, kAtomicCancelledEpoch, std::memory_order_acq_rel);
    state.aborted.store(true, std::memory_order_release);
    return false;
}
```

Why this is enough for groups:

- `TxnPhase` has only `Placing`, `Executing` and `Wounded` (`multi.h:34` [37]). `Executing` is written
  only by the unique last placer, at this site. `Wounded` is written only by `txn_wound` and the
  blind restart, and both intend to cancel.
- At this point the epoch is either 0 or already cancelled. A commit ticket requires phase one to
  complete, which requires this CAS to succeed.
- After the helper CAS the epoch is cancelled whichever side wins. `txn_group.inc:427` or
  `scatter_engine.inc:4122-4123` then takes `txn_group_retry`, which restarts with the original
  version. `txn_group_decide` can no longer win.
- The wounder's own epoch CAS then fails harmlessly. Count `GroupWounds` when the phase CAS
  succeeds, not when the epoch CAS does, so the counter is kept.

The same helper at the EXEC site (`multi.inc:1798` [1817]) closes the EXEC variant.

This stays inside D2: it is D2's stated wound outcome, made atomic from the victim's point of view.
No wait is added or removed. A larger alternative is a single atomic word carrying (phase, epoch).

**Directed checks for the fix lane:**

- `tests/txnorder_wound_window.cc` must print `PASS: wounded group cannot escape through a terminal
  commit` in both namespaces and both modes on the fixed build. It must still fail on PRE, which is
  the negative control.
- An EXEC analogue that stops a wound between the same two CASes before the EXEC finalizer runs.
- `tests/txn_nx.py --bare` at `--atomic 1`, repeated with the server's CPUs oversubscribed so that
  the wounder is likely to be descheduled inside the gap.
- `atomic_txn_group_wounds` still counts every successful phase wound.

This lane registers the diagnostic as a documented PRE-and-POST failure. It is **not** a gate row.
