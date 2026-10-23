# Final identity, layout and control artifacts

Comparison base: merged `origin/cpp` **a7dfb9d23**, not the older pre-merge
lane. Production source: **9d6e99d0d**. `identity-final2c/commands.json` records
the unmodified checker commands, before/after object and binary SHA-256s,
exit codes, and stable inputs.

| Checker | Result |
|---|---|
| `tools/lbstall_artifacts.py compare` | 1,202 / 1,216 bodies equal; 14 differ; exit 1 |
| `tools/ccfix_audit.py` | 16,340 / 17,067 bodies equal; **727 differ**; exit 1 |
| ccfix hot subset | 1,206 / 1,220 equal |
| ccfix registered handlers | 1,203 / 1,211 equal |
| `docs/deadswitch/linked_bytes.py` | Runtime sections differ; exit 1 |
| `tools/txnfix_scatter_audit.py` | Inventory completed; exit 0 is not an identity claim |

**Every changed body** is listed, including added/deleted bodies and cold
clones, in `identity-final2c/changed-bodies-with-reasons.json`. The raw 727-row
checker inventory remains in `identity-final2c/full/changed-bodies.json`.
Each annotated row names its source mechanism or identifies compiler
spillover as an inference. No checker exclusions or normalizers were changed.
174 rows are marked inferred code generation rather than falsely called
intentional source changes. They remain subject to merit review.

The 14 hot differences are DB0 genthread parse (body/cold), DB0 reorder parse
(body/cold), DB0 reorder executor execution and two TLS reply lambdas; normal
xshard `FlatStore::erase_in`; two normal genthread task-drain lambdas; and four
normal rl2s parse bodies/clones. Exact symbols, sizes and reasons are in
`identity-final2c/review-summary.json`. The eight handler differences are
DEBUG and INFO (including INFO cold clones) in both namespaces, plus DB0
CONFIG and QUIT. DEBUG/INFO implement the new witnesses/counters; CONFIG and
QUIT are compiler spillover.

Compile-only budget trials are in `budgets/results.json`: four candidates
each for normal/DB0 xshard, normal genthread, normal rl2s and DB0 reorder.
The retained xshard budgets are 142249 / 141155; the trial's ordinary-store
subset has one / zero changed bodies respectively. Other units still differ.
The final DB0 MGET investigation also tried a cold call and budgets ±64 before
retaining stack residence for the unused-on-read owner argument. Final whole
inventories, rather than a selected trial's smaller subset, are reported above.
Instruction counts and residual MSET terms are in [COST.md](COST.md).

## Layout

`layout-final2c/result.json` checks both namespaces. All locked sizes and all
existing field offsets match PRE: Op 336, Client 1984, ThreadCtx 1408, Shard
1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. Additional
checks retain ScatterState 896, WatchReservation 88, AtomicScriptIntent 32,
AtomicPendingState 1352 and MultiWriteKey 48. New metadata uses old padding
where applicable. Existing TLS offsets/sizes are equal; the complete TLS
symbol set is **not** equal because transaction-only TLS was added.

Server grows only at its cold tail, with every existing field offset retained:
normal **108736 → 141568**, DB0 **108352 → 141184**, a 32832-byte increase for
owner transaction counters, retry lanes and the debug placement word. No
locked hot record grew.

## PRE / POST / PAD(A)

| Arm | Ignored build artifact | SHA-256 |
|---|---|---|
| PRE | `build/txnorder2/pre-source/build/tomokv` | `97ea4e0638863ac87b289290bd489d8ef93e5fc4808ad49bc71dfbd05a9c739e` |
| POST | `build/tomokv` | `5bfa95e74b42c78c0b70fa0e3983c89582b66dc8d4a1570262968ec84e5f447f` |
| PAD(A) | `build/txnorder2/pad-a-size-final2c/tomokv` | `52a0b831841e5b0960b604069bfb190651ed23723d36fcdce19027da2a8aaaef` |

**PAD kind A: behaviour twin.** It retains a7dfb9d23 behavior, adds an unused
32832-byte aligned cold Server tail, then adds unreachable text padding.
Server sizes and all old offsets match POST; aggregate `.text` is exactly
**7,867,398 bytes**, equal to POST. Recipes and hashes are in `pad-layout/`
and `pad-a-size-final2c/build.json`.

This is a **size/allocation control**, not an exact function-placement twin:
individual function addresses and all other sections are not matched. A flat
PAD with a moving POST supports a behavioral explanation, but cannot alone
rule out every layout/cache effect. No inverse-control PAD(B) or throughput
measurement was run. The maintainer's matched-load rate, cycles/EXEC,
instructions/EXEC and IPC decide merit; identity alone does not.
