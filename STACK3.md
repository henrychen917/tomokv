# CX-stack3

Cumulative product source: `147ac24b70b6917e9e544027fc406b56f24ac17c`.
Base `118487882` preserves v3 `5d567adf5` and the two gate-instrument updates already
present in this worktree. The three mechanism commits are independent:

| Mechanism | Commit | Implementation |
| --- | --- | --- |
| L1 | `063eda6be` | Move the 16-byte argv header before inline argument slots, from `191f41be4` via stack arm 1 `fc25f79ae`. |
| O1 | `912fbc19a` | Use POST-t01's stage-interleaved split schedule and ordinary fused loop, via `935aea2d5`. Includes the null-sidecar INFO repair. |
| O6 | `147ac24b7` | Whole-batch bucket prefetch from `92b704897`, with measured mode policy from `abcbd9409`. |

Eligible batches prefetch unconditionally in fused mode; split mode requires
`overlap=1`. Singletons and exact slowlog escalation retain the measured exclusions.
There is no O6 A/B execution split, new knob, O1 POST2s early-notification change,
R7 scheduler, or R7 witness repair. The pre-existing reorder scheduler, flip
controller, `tests/abba_workloads.py` and `tests/gate.sh` are byte-identical to base.
Overlap tests assert the actual whole-batch prefetch witness in fused mode and
stage interleaving in split mode; missing activity must still fail.

## Accepted incoming measurement evidence

These are the maintainer's supplied winner measurements, not new measurements
from this integration. The iteration gate's separate cumulative comparison is
reported below when complete.

| PRE -> POST mechanism | Supplied rate gain |
| --- | --- |
| Prior floor -> L1 | +2.3..3.4%, both modes |
| L1 -> L1+O1 | +12.6% on h07; O1 alone +8.8/+10.2% on 1s p32 |
| L1+O1 -> L1+O1+O6 prefetch | +4.3/+5.9% |
| Fused overlap=0 -> always-on fused prefetch | co3b +4.5/+3.5% |

No fresh cycles/op, IPC, instruction-count or tail claim is inferred from that table.

## Build and serverless validation

Release and every unit program built with `taskset -c 112-127 make -j8`.
The supplemental recipe is `build/stack3/checks.mk`; logs are
`build/stack3/build-PRE.log` and `build/stack3/build-POST-units.log`.
Core and overlap TSAN binaries compile all linked implementation TUs with the same
instrumentation; waits and storage have their dedicated TSAN builds. All eleven
TSAN selections pass with `halt_on_error=1`, no suppressions and process-local
`setarch x86_64 -R`. GCC emits its existing atomic_thread_fence instrumentation warnings.

All unit programs ran: 75/77 named selections pass. The four owner-arena selections
require exactly eight allowed CPUs; after the fixture rejected the initial 16-CPU
invocation, all four pass on CPUs 112-119. The two remaining failures are explicitly
documented nongating diagnostics already present in base, and both reproduce
identically on freshly built PRE unit binaries at that same eight-core geometry:

- `atomic-survivors-unit post_apply_probe`: the manual first-owner script APPLY
  interleaving and an APPEND have an illegal serial outcome (`:2`, `:2`, final `BW`).
  See `tests/atomic_survivors_unit.cc:290`; this existing probe is deliberately
  outside the passing gate rows.
- `netcmd-unit collection-oom`: allocation failure in the second replacement of
  a multi-field HSET retains the changed first field and old TTL (OPEN F05).
  See `tests/netcmd_unit.cc:286`; this existing diagnostic is also outside the gate.

Receipts: `build/stack3/units/results-corrected.json`,
`build/stack3/pre-existing-probes.json`, and their per-selection logs.
No diagnostic was removed, turned into a pass, or given a wider tolerance.
The modified Python gate self-tests pass 54/54 (`build/stack3/gates-selftest.log`).

GDB reads the completed binaries' DWARF without starting them. All locks remain:
Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192,
AtomicEntry 144, Config 624. Argv offsets change from heap/cap/argc/inline
320/328/332/192 to 192/200/204/208. IoLoop follows O1's 8384 -> 7136-byte reduction.
Both executor variants contain real bucket-prefetch instructions in the release
binary. Receipts: `build/stack3/layout-{PRE,POST}.txt`, `source-proof.json`, and
`prefetch-codegen.json`.

## Binary arms

`build/tomokv` is byte-identical to `build/stack3/tomokv-POST`.
PRE, POST and PAD-B paths, full digests and .text sizes are in `MEASURE-REQUEST`
and `build/stack3/arms.json`. PAD-B is a kind-B inverse control: candidate behavior
plus unreachable padding restores PRE's total .text size. It does not restore
PRE function addresses or object-field placement. The zero-padding relink has
exactly POST's .text bytes; ELF properties are unchanged.

## Iteration gate

Pending a quiet box window. Command:

```sh
GATE_LEDGER="$PWD/build/stack3/gate-iteration.tsv" tests/gate.sh iteration --server-cores 0-83 --load-cores 84-111
```

No rows are added or retired on either side of the quick-tier exit:
EXPECT_QUICK=419 and EXPECT_FULL=436 remain unchanged. The initial invocation
was refused before boot because the active tailbigkeys measurement owned port
7899; `build/stack3/gate-preboot-blocked.{log,tsv}` preserves that refusal.
