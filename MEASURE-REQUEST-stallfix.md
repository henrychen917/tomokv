# stallfix: request-stall repairs on the paper build

Base: `79ce7ee1320f48b26f0979a0ad3893cbc4e84843`; branch/worktree `cx-stallfix`.
No push or merge. Diagnosis read first: `/home/user/Projects/stallrepro/REPORT.md`.
This report separates correctness witnesses from the maintainer's pending performance verdict.

## Diff

* Plain scatter reads and freshly dispatched EXEC readers now use a per-IO FIFO with the script window's list/map
  pattern and `(Client*, ROB dispatch id)` identity. A new arrival cannot overtake a live head.
  The head remains queued until its frame is published/consumed, preserving its turn across
  later credit or allocation failure. Stale and closing heads are erased; a ClientDrain subject
  is bypassed as in the script FIFO. Existing close/migration cleanup forgets both memberships.
  Already-dispatched EXEC retries retain their progress rule; unrelated credit-blocked writes
  retain their existing resume rule. The FIFO controls admission to this shared cut window.
* `atomic_cut_window_refusals` counts actual full-window refusal attempts, including retries;
  it does not count a refusal solely because another connection is at the head. No new knob.
  The empty-queue/free-window path adds one predictable queue-present branch to snapshot
  preparation. No admission-finalizer branch was added. Single-key command paths do not call it.
* `Server::lb_observe` captures epoch, stage, and the previous acknowledgement together under
  existing control synchronization. IoDrain uses the transition **try-lock**; contention
  returns retry work without blocking. ClientDrain uses the existing immutable-record read
  guard, which prevents admission from advancing the epoch until the sample finishes and
  preserves first-tail readiness decisions even while the shape mutex is held. Stages which
  the IO cannot acknowledge need no guarded epoch sample.
  `lb_ack_observed` CASes the saved acknowledgement to the saved epoch/stage tag. IoDrain can
  publish only IoDrain; a ClientDrain destination can publish only its observed ClientDrain.
  No live stage is stored by either IO acknowledgement. A newer acknowledgement wins the CAS.
  The existing offline LB control twin follows the same acknowledgement rule.
* Shard-drain timeouts now increment `tomokv_lbstall_shard_timeouts`, update
  `tomokv_lbstall_shard_timeout_ns_max` and the existing `tomokv_lbstall_pending_ns_max`,
  and stamp every shard in the abandoned plan with the normal move cooldown. Timeout handling
  rechecks the live deadline under the transition lock before cancelling a plan.
* One `TOMO_CORE_CONCURRENCY_TEST` hook lies between the coherent IO observation and acknowledgement.
  It is absent from production. New Python and native regressions are exposed as gate jobs.

No GET/SET source body, owner execution law, immutable-read/QSBR path, epoch-MVCC decision,
shard transfer implementation, or runtime configuration grammar changes.

## Wait bound and limits

For a dispatchable read with **q live FIFO predecessors**, at most q predecessors
may obtain admission before it; continued arrivals join behind it. If L bounds the wait for
usable general-window capacity (including completion/retry of already-admitted units) and each eligible head is
revisited within D, a conservative admission bound is `(q + 1) * (L + D)`. With 16
connections there are at most 15 such predecessors.
This removes the active-vector-position starvation demonstrated by the diagnosis. It does
**not** claim an unconditional 500 ms service bound under arbitrary executor suspension,
allocation failure, or administrative pause. The 500 ms bound is the explicit regression
criterion for the prescribed four-second workload. Scripts retain their separate four-slot
admission protocol and already-admitted transaction work retains its existing progress rules.

The original latent commit risk is closed for this interleaving: a stale IO observation
cannot manufacture ExDrain in the fused slot, so it cannot release a shard move while that
executor still has parked work. A genuine executor ack still requires `flip_quiesced()`,
which checks atomic/multi/xshard/ordered deferred work, inbound tasks, notifications,
snapshot backlogs, and both atomic inflight counts. No readiness check was weakened.
This is a review of the reported false-IO-ack path, not a proof of every controller interleaving.

## Reproducer evidence

`tests/stallfix.py` is a Python-only translation of REPORT section 7. It uses four independent
client processes, 16 connections, P16, one contended eight-key group, 256-byte tagged values,
and four seconds of mixed MSET/MGET. It times **every** response from send through final drain,
checks exact MSET replies and untorn MGET values, and requires a positive refusal counter.
Only an otherwise clean but unarmed run may retry, on a fresh boot, at most three times.
The PRE-only `--allow-missing-counter` option isolates latency failure on the old binary;
the gate never passes that option.

| Mechanism / arm | Result | Evidence |
|---|---:|---|
| Cut window, paper binary, 1s / one core | FAIL: 4002.973 ms maximum | `docs/stallfix/paper-1s/result-0.json` |
| Cut window, paper binary, 2s / 1:1 | FAIL: 4000.637 ms maximum | `docs/stallfix/paper-2s/result-0.json` |
| Cut window, final POST, 1s | PASS: 17.108 ms; 51,649 refusals | `docs/stallfix/gate-final/cut-1s/result-0.json` |
| Cut window, final POST, 2s | PASS: 7.049 ms; 2,298 refusals | `docs/stallfix/gate-final/cut-2s/result-0.json` |
| LB, restored PRE acknowledgement, ASAN/UBSAN and TSAN | Expected FAIL at false ExDrain acknowledgement | `docs/stallfix/native-*-stallfix-planted.log` |
| LB, fixed acknowledgement | PASS; ASAN 1.548 ms; TSAN 2.211 ms | `docs/stallfix/native-*-stallfix.log` |

Paper path: `/home/user/Projects/bins/paper-final-b367057e`. These are latency/correctness
witnesses, not throughput comparisons. The native negative control restores exactly the old
`if (!lb_acked(tid)) lb_ack(tid)` operation after the forced coordinator transition; it exits
at the forbidden acknowledgement rather than sleeping for the five-second timeout. The
natural paper/release five-second episodes and live gdb evidence remain the prior diagnosis's
observations; this lane did not rerun its probabilistic full-sequence experiment.

The native fixture publishes a real cross-shard EVALSHA touching the held fused thread's
shard, leaves `atomic_inflight == 1`, and advances IoDrain to ExDrain on a coordinator thread
inside the hook. It verifies no EX ack before quiescence, then drives real owner work,
checks the exact script reply, and commits the same move in less than 100 ms with no timeout.
Additional assertions cover a stale ClientDrain destination epoch, CAS refusal of a newer
acknowledgement, nonblocking observation under a held transition lock, both shard timeout
stages and their cooldown/INFO fields, and rejection of a stale timeout against a fresh deadline.
FIFO assertions cover head priority, reparse/credit-failure position retention, stale dispatch
IDs, closing heads, fresh EXEC readers sharing the window, unrelated write retries, and
close/migration cleanup. The EXEC extension also has a PRE witness in
`docs/stallfix/exec-fifo-before.log`: without it the native test fails because a new EXEC
takes a free cut ahead of queued plain reads.

## Tests and gate accounting

Final source/binary revision: `0660106bb4` (later commits contain evidence only).
The selected job invocation is:

```sh
taskset -c 112-127 env LC_ALL=C \
  GATE_ONLY_JOBS='stallfix_cuts stallfix_units core_units atomic_units lbplanner_units atomic_batteries script_bounds scriptfix lb-stationary-1s lb-stationary-2s multifix-1s-uring multifix-2s-uring txn_group_fused txn_group_split' \
  GATE_PROOF_NO_RATES=1 \
  GATE_LEDGER=/home/user/Projects/cx-stallfix/build/stallfix/gate-verified-ledger.txt \
  tests/gate.sh quick --server-cores 112-119 --load-cores 120-127 --load-smt '' \
  --ports 26120-26299 --candidate-binary /home/user/Projects/cx-stallfix/build/tomokv
```

This is a selected partial run, not the full quick or landing gate. Existing rows use
16 shards on eight server cores, with a 6:2 split in 2s and eight fused threads in 1s; the new cut rows deliberately select the prescribed
one-IO / 64-shard geometry. Final ledger and per-job counts: `docs/stallfix/gate-final/`.
The initial run at `543cc4e3d4` had 71 passes and one failure: `lbplanner_units` could not
build its PAD because its frozen PRE source proof rejected the repaired acknowledgement.
The strict attributed source delta described below repairs that test artifact.
Initial ledger: `docs/stallfix/gate-initial/`. A second run at `d0a240da24` also had
71 passes and one failure: the existing client-drain timing witness correctly rejected
the try-lock added to ClientDrain observation. The fix reuses the immutable-record guard
there; the timing witness and all its negative controls are unchanged. Second ledger and
failing witness: `docs/stallfix/gate-before-client-guard/`.

| Gate job | Passed | Failed |
|---|---:|---:|
| `atomic_batteries` | 4 | 0 |
| `atomic_units` | 27 | 0 |
| `core_tsan_build` | 0 | 0 |
| `core_units` | 9 | 0 |
| `lb-stationary-1s` | 1 | 0 |
| `lb-stationary-2s` | 1 | 0 |
| `lbplanner_units` | 2 | 0 |
| `multifix-1s-uring` | 6 | 0 |
| `multifix-2s-uring` | 6 | 0 |
| `production_units` | 0 | 0 |
| `release` | 1 | 0 |
| `script_bounds` | 2 | 0 |
| `scriptfix` | 8 | 0 |
| `stallfix_cuts` | 2 | 0 |
| `stallfix_units` | 1 | 0 |
| `txn_group_fused` | 1 | 0 |
| `txn_group_split` | 1 | 0 |
| **Total** | **72** | **0** |

* `python3 tests/gates_test.py`: 83 tests passed (plus its invoked 14 identity controls).
* `make unit`: passed; no server or benchmark.
* Direct ASAN/UBSAN and TSAN selections: `stallfix`, `watch`, `lifetime`, `drain`, `route`,
  `snapshot`, `config`, `notify` passed;
  `stallfix-planted` failed with its required false-ack witness. Final TSAN runs use the
  gate's `setarch x86_64 -R` invocation. An earlier direct TSAN `watch` invocation without
  that address-map setting exited SIGSEGV with an empty log; all final selections pass
  with the documented gate invocation, with no sanitizer suppressions.
* `python3 tests/gate_ledger_fixture.py --self-test`: 11/12 passed; its inventory test
  correctly reports the protected count mismatch, with **no missing or extra labels**.
  A separately labelled in-memory projection to the required counts passes 12/12.
  Neither test file nor the real gate count constants were weakened.

New jobs: `stallfix_cuts` (two mode rows) and `stallfix_units` (one ASAN/TSAN row including
negative control). Their collection sites are lines **7347 and 7348**, before the quick-tier
exit at line **7699**. Delta is
**+3 quick / +3 full**, so the maintainer must change **1325/1342 to 1328/1345**.
`EXPECT_QUICK` and `EXPECT_FULL` are deliberately untouched. The explicit label fixture adds
exactly those three attributed rows.

## Inventory and binary identity

`docs/stallfix/binaries.json` binds PRE, POST, paper and both native sanitizer builds by SHA-256.
`make -q` returns zero for the production, ASAN, TSAN and LB-unit targets after the final gate.
The named R7 inventory remains **176 normal + 177 DB0 = 353 bodies**, with no additions or
removals: no stallfix inventory delta is needed in `r7shadow_noop.py` or `reorder_receipt.py`.
The strict PRE/POST comparison is **336/353 equal**, with 17 changes retained in the report.
The production-versus-FIFO R7 receipt remains **353/353 equal**, and every missing-body/extra-clone/
changed-opcode control passes. All **20 GET/SET handler bodies**, including notification variants
and cold clones, match after relocation normalization.

DWARF checks in `docs/stallfix/layout-{pre,post}.json` compare every existing field offset as
well as total sizes: **no existing field moves and no object grows**. Locks remain Op 336,
Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624.
Server remains 144960; MultiRetryLane remains 64; LbStallState remains 8320. New fields consume
previous padding. Consequently there is **no layout PAD arm** for this correctness change;
no stallfix performance PAD result is implied. Linked text changes are recorded in `binary-size.txt` and remain a
reason to run the requested performance controls.
The source bodies changed are:

* `xshard_prepare_body<false>`: fair read-cut admission and cold waiter call.
* `multi_dispatch_attempt`: fresh EXEC readers join the same FIFO; published retries retain
  their existing admission rule.
* `script_window_forget`, `script_window_resume`: queue cleanup and head-only resume;
  added `cut_window_erase`, `cut_window_head`, `cut_window_wait`, `cut_window_forget`.
* `cmd_info`: refusal counter output; added Server counter increment/read accessors.
* `IoLoop::lb_control_pass`, `IoLoop::lb_control_actuate_pad`: observed IO acknowledgements;
  added `Server::lb_observe`, `Server::lb_ack_observed`, `LbObservation::tag`.
* `Server::lb_stage_timed_out`: out-of-line timeout diagnostics/cooldown with deadline recheck;
  `Server::lb_stall_info`: the two new shard-timeout fields. The timeout body moves to
  `lbstall.cc` to access the private policy diagnostics beside the existing stall accounting.

The existing LB hosting PAD-A generator is type **A** for that earlier hosting change:
PRE hosting behaviour with current POST text/layout, sharing these correctness repairs.
It requires a separate, strict source delta for
`lb_control_actuate_pad`: four exact replacements on its frozen PRE reference, attributed
to stallfix. Its whole-body comparison still rejects unrelated edits and restoration of
the live-stage acknowledgement; both mutation witnesses are in
`docs/stallfix/lb-pad-source-proof.json`. This is maintenance of the existing LB control
twin, not an additional stallfix performance arm.

The strict PRE/POST R7 audit names **every** changed compiled body in
`docs/stallfix/audited-body-changes.json`, with exact normalized diffs in
`docs/stallfix/identity/`. It is not a strict-noop change: direct admission/control changes and
compiler inlining/register-allocation changes are retained in the audit, not excluded.
GET/SET command handlers, including cold clones in both database runtimes, are compared
separately in `docs/stallfix/get-set-identity.json`.

## Measurement request (maintainer; not run here)

Build arms: the source PRE from `79ce7ee13` under `build/stallfix/pre-src/build/tomokv`,
and the final POST `build/tomokv`. Preserve hashes with the results. Use the gate's ABBA
instrument, matched offered loads and per-cell cycles/op, instructions/op and IPC; compare
rates and tail latency, not instruction count alone. Use both 1s and 2s, `--atomic 1`, and the
normal eight-core / 16-shard geometry for the standard cells: 6:2 in 2s and eight fused
threads in 1s. Keep workload flags,
placement, warmup, connection counts, data and trial order matched. Use the NIC instrument
for send-path controls. This lane ran no ABBA, saturation or rate measurements.

| Required cells | Depths / existing definitions | Verdict |
|---|---|---|
| MGET-8 | P1, P8, P32; headline m01-m03 and m49-m51 | Matched-load rate and tails; cycle/IPC explanation |
| MSET-8 | P1, P8, P32; headline m04-m06 and m52-m54 | No regression; shared preparation/credit control |
| EXEC | Existing eight-command MULTI_EXEC cell, P16; also P1/P32 controls | Correct replies, no throughput/tail regression |
| EVALSHA | Existing eight-command EVALSHA cell, P16; also P1/P32 controls | No admission, script or LB regression |
| GET, SET | P1 and P32, both modes; read-local off and armed | No-regression controls |
| Contended mixed MSET-8/MGET-8 | Prescribed one-IO / 64-shard P16 witness | Max wait <=500 ms, refusals >0, no torn replies |

The original EXEC/EVALSHA workload definitions are
`/home/user/Projects/stallrepro/evidence-orig/{MULTI_EXEC,EVALSHA}.spec.json`.
Use the gate's corresponding workload instrumentation; do not assume respgen exists in gate jobs.
A real performance result must include a PRE/POST table and uncertainty from matched repeats.
There is no performance-win claim in this diff.

## Risks and work not run

* Queue bookkeeping allocates only on contention; allocation failure still leaves the frame
  unconsumed. The fairness bound assumes successful queue allocation and finite cut completion.
* New INFO counts are diagnostic, not an allocation/latency SLA. The refusal count can exceed
  the number of distinct requests because retry refusals are counted.
* Coherent LB observation is confined to the control tail; a busy transition lock returns
  runnable work for IoDrain, while ClientDrain retains its nonblocking record guard.
  The new CAS must never be replaced by a live-stage store.
* Full landing gate, probabilistic full-sequence five-second reproducer, rate/ABBA/NIC merit,
  and release deployment/merge/push are not run. The maintainer owns those decisions.
* All live runs use CPUs 112-127, owned PIDs, free-port guards and LC_ALL=C; server ports lie
  in 26100-26299. No stallrepro file was edited. Raw intermediate build/disassembly artifacts
  remain under ignored `build/`; committed evidence is under `docs/stallfix/`.
