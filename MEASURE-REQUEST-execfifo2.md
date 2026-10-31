# FIFO hand-off on the current headline

## execfifo2

Base/PRE: `e32b04a445b056976abb308aa598e356fcbaae74`.
Approved source: `cx-execfifo-arm-c1` / `bd0cb9668` (B+C1 only, D6).
Lane: `cx-execfifo2`; no push. All builds and correctness work use CPUs 0–31,
ports 20100–20199, and `LC_ALL=C` for every server boot. Performance and the
full iteration remain maintainer work; no throughput claim is made.

Port sequence: B with unified EXEC/escalated-script key admission; then C1
owner-local chaining and H3 boundaries, preserving headline X1–X5, woundfix,
D1–D10/amend1/D4′ and FLIP stage obligations. C2/C3 are excluded.

Verification and release/PAD-A artifact identities will be recorded here.
`EXPECT_QUICK` and `EXPECT_FULL` remain unchanged; DQ/DF will be counted at the
collection lines relative to the quick exit.
