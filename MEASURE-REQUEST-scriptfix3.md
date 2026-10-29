## scriptfix3

Base PRE: `e2b237926`; instruction headline: `393d6ceb1`. Branch `cx-scriptfix3`; no push.

Work in progress: immutable original-source/SHA/shebang metadata, lazy separate EVAL and
FUNCTION interpreters, and normalized-name aliases inserted once. The original
scriptfix2 battery and all gate rows are unchanged. **DQ=0, DF=0**; EXPECT constants
remain unchanged. Final counts, correctness receipts and arm hashes will be added here.

Performance work is NOT RUN in this lane. Maintainer request: POST versus PRE,
three blocks of the contended-script storm; the EXEC cells; all fourteen generic
cells from `docs/compat3/merit-cells.txt`; and 2s GET/SET p1/p32 as null controls.
Use the gate instrument and retain each arm's cycles/op, IPC and instructions/op.
No throughput claim is made.

PAD-A is planned as an **A: behaviour twin**, unmodified PRE objects plus unreachable
padding matching POST's total .text size and start. This is a total-size control,
not an exact per-function-placement or data-layout twin; retain that limitation
when interpreting any PAD movement.
