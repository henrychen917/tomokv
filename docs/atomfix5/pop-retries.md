# AT4.20 — NOT REPRODUCED at atomic 1

PRE ef5204b2e was exercised at both atomic values and thread modes. Each boot:
eight server cores 48–55, 16 shards, databases 16, uring, read-local 1 in fused,
6 IO + 2 owners in split, LB/auto-FLIP off, port 34810, driver cores 56–63.
DEBUG SHARDS proves the listed keys have different owners. Each LMPOP and ZMPOP
run uses 16 concurrent clients × 400 pops, with eight clients first adding a
unique item to the hot first key on every turn. The second key starts with
12,000 distinct items and remains populated throughout (only 6,400 pops total).

Atomic 1: both modes return 6,400 successful pops per command, zero nulls, with
8,800 items left in the fallback key. This did not reach eight consecutive
failed re-probes. It is not evidence that the source retry ceiling is safe.
Per instruction, no change is made to an item not reproduced under the tried
contention. The missing EXEC exclusive fallback is discussed in
script-escalation.md; an escalation must use an owner-approved mechanism.

Additional observed compatibility issue: at atomic 0, fused returns 53 null
LMPOPs and 42 null ZMPOPs, split returns four nulls for each, despite the fallback
remaining populated. That path lacks the atomic-1 re-probe rule; these are not
misreported as reproductions of the eight-retry atomic-1 ceiling. Exact results
and key-owner geometry are in reproductions-pre.json and its compressed log.

No fix or new gate row: DQ=0, DF=0. A next directed reproduction should schedule
a thief after each selected-key probe and before each of nine pops, preserving
the second key and proving each stolen probe rather than relying on timing.
