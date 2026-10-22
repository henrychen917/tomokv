# ntfix3 compile-only inlining re-derivation

PRE is `567d3b8e3`, rebuilt byte-identically to frozen `5c8ca908` before any object comparison. Eight PRE recompiles also reproduce every emitted body. All trials use CPUs 80–95; at most sixteen compiler children run together. No trial executes a server or workload.

Eight PRE and 31 POST compiles cover all eight receive/dispatch translation units. The initial IPA unit deltas are +127 for main, +142 for genthread, and +172 for rl2s/reorder. The first budget candidates preserve PRE headroom; follow-up trials narrow the ranges restoring unedited bodies. Selection minimizes changed hot bodies outside directly edited receive/parser paths, then other changed bodies, then distance from preserved headroom. Every trial retains all differences, including directly edited bodies; the ranking does not waive them.

| Object | Initial budget | Selected | Initial → selected hot differences outside direct receive/parser edits |
|---|---:|---:|---:|
| `src/main.o` | 147428 | 147428 | 0 → 0 |
| `db0/src/main.o` | 147449 | 147449 | 0 → 0 |
| `src/core/genthread.o` | 129487 | 129557 | 3 → 0 |
| `db0/src/core/genthread.o` | 129744 | 129830 | 1 → 0 |
| `src/core/rl2s.o` | 162357 | 162357 | 0 → 0 |
| `db0/src/core/rl2s.o` | 162334 | 162334 | 0 → 0 |
| `src/core/reorder.o` | compiler default | compiler default | 3 → 3 |
| `db0/src/core/reorder.o` | 148398 | 148538 | 5 → 1 |

Only the two genthread budgets and db0 reorder change. Main and db0 rl2s have identical counts at the headroom-preserving alternative; src rl2s has more other differences there, so all three existing values remain. An explicit src reorder budget inferred from its default 40% growth changes 52 selected hot bodies and is rejected; its existing compiler default remains. This is a bounded compile-only attempt, not an identity stop.

`src/core/reorder.o` retains three unedited flush/sweep differences; db0 reorder retains the existing 796 → 729-byte fused sweep difference. The final full inventory also includes direct N1/N2/N3 changes, N4 cold refinement branches, and receive-helper outlining. It is produced with the unmodified strict identity tools after the final build.

`units/`, `round1/`, `reorder/`, and `round2/` contain exact compiler commands, source/object hashes, IPA unit sizes, and every changed emitted body. `selected.json` records the chosen trials. These compiler-budget values are not performance results.
