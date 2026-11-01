# Execution provenance

These are the lane-local orchestration scripts used for the retained proof.
They were run from the worktree root under `taskset -c 32-47`; builds use -j16,
servers use 32-39, and clients/oracles use 40-47. Listen ports are 20300-20399 and
server environments pin LC_ALL=C. They are retained for inspection, not wired
into the product or gate.

`remaining-proof.py` selects correctness jobs only, validates differential
inventory folds, then runs the negative controls and gate self-tests. Its first
epoll regression phase retains an actual failure; later phases continue so
independent evidence is not lost. It does not change a failed exit to success.

`txnorder-recheck.py` launches unchanged PRE/POST arms under GDB without
breakpoints or stepping, using the original row-d battery and effective gate
geometry. It sends normal SIGTERM when the battery exits and records a server
abort if the server itself raises one. Native repetitions are separate gate
jobs, recorded in txnorder-native-recheck.json.

`archive-gate.py` records source hashes/counts before retiring completed run
directories. Repetitive tenure timing lines and large per-tenure arrays are
reduced in the derived logs; source hashes and counts remain in the manifest.
