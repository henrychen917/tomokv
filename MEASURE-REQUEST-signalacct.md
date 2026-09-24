# signalacct — work in progress, PENDING MAINLINE

Reference: `3e734cf2e00c087604fcaf145459522e6fa81f05`, branch `cx-signalacct`.
PRE: `build/tomokv-signalacct-pre`, SHA-256
`f4d14845572ed808a802e6f8040d8025b43c3b3de0cd07d42770ab768301f014`.
Built with `taskset -c 112-127 make -j16 BUILD_ROOT=build/signalacct-pre`.
No server, load generator, gate or measurement has been run by this lane.

Frozen source/instrument identities: `build/signalacct-proof/pre-instrument.sha256`.
Frozen launch-time cell bytes: `build/signalacct-proof/headline_cells.pre.txt`.
PRE section/relocation and disassembly dumps: `build/signalacct-proof/pre.*.txt`.
Reference source and objects remain in `build/signalacct-pre/`.

Launch recheck: the missing prologue, submit/reap, sweep and final tail are present.
Physical flip selection consumes busy/(busy+idle); its decisions can change.
The launch revision has already retired AUTO: `tests/config_parser_test.cc:451`
rejects `--reorder -1`, and `tests/r7shadow_sync.py` has no AUTO tick injection.
This lane will preserve the active graph and sampling beat, not restore retired AUTO.

Acceptance results and complete proof/consumer inventory will replace this draft.
