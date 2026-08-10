HARNESS ONLY (#111): tools/preflight/knob_matrix.sh is the drift-guard that
boots the server once per knob setting and runs a smoke cell. Two LIVE knobs
are missing cells: tomokv-atomic (yes/no) and tomokv-atomic-window (0, 64,
512). ADD matrix cells for them following the file's existing cell pattern
exactly: for tomokv-atomic yes add a small MIXED multi-key smoke (MGET8/MSET8
via redis-cli pipelined loop or the file's existing load helper — match the
file's style; keymax small) plus the correctness assertion the file uses
(server alive, no crash in log, PING after). Also add one cell asserting
tomokv_atomic_inflight returns to 0 within a bounded wait after load stops
(the wedge class this tree just diagnosed — a pinned inflight is the failure
signature). Also grep the script for any knob cells that reference deleted
knobs (tomokv-mcmd-lock, tomokv-forwarding, operand-pool) and remove dead
cells. HARNESS CODE ONLY — do not touch src/.
