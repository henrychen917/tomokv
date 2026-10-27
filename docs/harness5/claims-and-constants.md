# harness5: claims and constants corrections

This correction applies to source `3700b51d7`, before any harness5 change.
The original external ledger, portability inventory and memory notes are outside
this worktree. Their relevant text and whole-file hashes are retained in
[historical-claim-sources.json](historical-claim-sources.json); this in-tree
addendum supersedes the statements below for current-code descriptions.
Historical measurements keep their original scope.

## WB4.8 and WB4.9

The [wbknobs landing record](../../MEASURE-REQUEST-wbknobs.md) now contains the
maintainer's historical decision and numbers. Its 14-cell null covered 1s only;
the same-binary p8 comparison exited 3, PARTIAL, with an untrusted standing null.
It cannot certify current performance or 2s parity.

| Ledger / inventory item | Current disposition | Code and limits |
|---|---|---|
| S, `kSmallPipe=16`; ledger §13 “KEEP, hardcoded (FINAL)”; portability KEEP | Boot knob default, not a hardcoded rule input | `Config::wb_small_pipe` in `src/core/config.h`; `wb-small-pipe` accepts canonical decimal 0..64, bounded by `kRobWindow`. 0 and 1 use the half rule. |
| D, `kCompleteVisits=3`; ledger §13 “KEEP, hardcoded (DERIVED BY MEASUREMENT)”; portability KEEP | Boot knob default selected in the historical D-curve | `Config::wb_complete_visits`; `wb-complete-visits` accepts 0..255, bounded by `UINT8_MAX`. 0 removes the visit bound; it does not disable writeback. |
| Ledger §16 “pending wbknobs lane” | Landed `6b50f447f`, 2026-10-09 | The historical 1s results above support that decision only. |
| `wb_rule::Settings` defaults | `{1, kSmallPipe, kCompleteVisits}` | `src/core/wb_rule.h`: S/D reuse the named defaults; no separate literal 16/3 tuning choice. Settings are latched into each IO loop at initialization. |
| `kPolicyFraction` | Compiled 1/2, unchanged | S and D affect policy 1 only; D has no effect when S≤1. A visit bound is not a wall-clock latency bound. |

Neither the knob ranges nor the defaults establish portability or optimality on
other machines. No production code changes are part of these corrections.

## CL4.3

| Historical claim | Supported wording for the paper |
|---|---|
| TomoKV 109 B/key, Dragonfly 85, Redis 105 | Historical 2026-08-15 note, 40M keys × 32-byte values. The note says “our own upstream”; it supplies no current ground-up C++ executable binding. **Unsupported for the current binary.** |
| Eight cores is the node optimum; four-core nodes collapse | The note retracts the four-core result: 63 threads occupied 48 CPUs. It explicitly says finer than one CCX is “UNANSWERED”. Its verified older eight-versus-wide comparison remains historical. **No current binary optimum established.** |
| Dragonfly's full-scale baseline is already optimally tuned | The note's 16-server-core loopback tuning includes a +9.1% MSET exception and leaves the full-scale NIC follow-up open. **No 64-core NIC optimum established.** |

Publishing current numbers requires frozen executable hashes, complete commands,
allocator/build identity, placement and workload receipts for those experiments.
This lane performs no replacement performance measurements and makes no claim
that old numbers transfer to the rewrite.

## CL4.4

Ledger §9's “every other hot-path constant is either derived for free or inert
within ±1.7%” is **unsupported** as a universal statement. The retained evidence
describes a 45-arm GET/SET p32 screen; its 26-arm grouped row reports sign-mixed
changes within ±1.7%. Use those named screen operands as the limit of the result.

The screen does not demonstrate eviction, expiry, large-reply IOV, scatter or
wait-path engagement for every constant family. The 20M-key load-factor run
scored zero commands and establishes no throughput result. An inactive-path null
does not prove a free derivation, a portable optimum, or irrelevance under an
engaged workload. The original recommendations remain proposals where the code
has not adopted them; no new performance conclusion follows from this audit.
