# snapfix evidence

Base: `a214652ec` on branch `cx-snapfix`. All commands use CPUs 16–31;
correctness servers use 16–23, drivers 24–31, and ports 20200–20299.
There are no performance measurements in this lane.

`tests/at412.py` and `tests/at412_diagnostics.py` are copied unchanged from
`cx-at412c`, whose resolved commit is in `provenance/at412c-commit.txt`.
The historical shutdown stack, snapshot-storm results and diagnostic README
are copied from that same commit. The upstream report's section 6 and the
2026-10-27 REGISTER addendum assign XS-SHUT-1 and SNAP-STORM-1 to this lane.
These diagnostics remain separate from the directed gate assertions.

`tools/snapfix_reproduce.py` runs the diagnostics under an outer process-group
watchdog and records every command, return code and binary SHA-256. Geometry:
eight physical CPUs, 16 shards, databases 16, atomic 1, balancing and auto-FLIP
off; 1s has read-local 1, 2s has ratio 6:2 and read-local 0. Both engines run.
Zero means NOT REPRODUCED at the recorded geometry and attempt count, not proof
of absence. Failures retain the original exception and process exit.
