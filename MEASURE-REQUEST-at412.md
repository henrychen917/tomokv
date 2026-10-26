# AT4.12 proof and measurement request

## at412

Branch `cx-at412`, PRE `7ae703778e854a7b76945af5792a5ec5e88061a6`.
All lane processes use CPUs 48-63, builds use `-j16`, correctness servers use
48-55 and drivers 56-63, ports 20200-20299. No push or performance run.

Specification: `round4-read/at412-escalation-review.md`, read in full with the
two txnorder design documents. The original proposal's external worktree no
longer exists; the tracked `docs/atomfix5/script-escalation.md` was read instead.
AT4-WOUND-1 remains owned by woundfix.

Initial directed rows: T1-T6, T11a/T11b and T12. They are collected before the
quick-tier exit, DQ=+9, DF=+9. EXPECT constants are unchanged. These are failing
specification tests until the implementation and witness hooks land.

D4′: optimistic scripts yield to units. After eight restages, or an APPLY
conflict, they hand off to a kind-2 unit with Write claims on declared keys.
The hand-off keeps the ROB identity, barrier and admission lease. It releases
PINs, certification, ticket bracket, cut, slot and apply window. Escalated
attempts use monotonic inherited ages and draw a ticket only at decision.

Results and remaining obligations will be recorded below as they run.
