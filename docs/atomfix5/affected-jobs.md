# Gate proof map

All selected runs use tests/gate.sh with GATE_ONLY_JOBS. None runs a full gate,
ABBA, NIC measurements, or a receipt claim. CPUs 48–55 are the eight server
cores; 56–63 serve drivers. Builds use their union with -j16. Ports are restricted
to 34800–34899. Source oracle is /home/user/Projects/redis; the explicit
GATE_DIFFER_ORACLE_BIN is /home/user/Projects/redis74/src/redis-server. That binary-
only directory is not falsely claimed to be the source checkout.

| Changed surface / requested family | Gate jobs |
|---|---|
| WATCH logical count | atomfix5_watch; all 16 declared legs on PRE/POST/PAD-A |
| New exact accounting | atomfix5_accounting; all eight legs × four schedules on PRE/POST; eight rejected broken-control legs |
| multi.inc / scatter, script atomicity, EXEC | debug-0, debug-1, fused-0, fused-1, atomic_units, txn_group_fused, txn_group_split |
| EXEC version ordering | txnorder-fused-0/1, txnorder-split-0/1, txnorder2, txnorder_wake |
| Movers | moverfix; xmove is also in debug-0/1 |
| Client-list | climonfix, clientfix, feature-split-0/1, feature-armed-0/1 (climon/climon2) |
| Script bounds / function surface | script_bounds, scriptfix, feature-split-0/1, feature-armed-0/1 (lua_scripting/scriptsurf) |
| Atomic and blocking | atomic_batteries, atomic_units, debug/fused, feature-split-0/1 and feature-armed-0/1 (blocking/blockmulti) |
| Standard Redis differential seeds | differ-split and differ-armed aggregate selectors plus differ-equivalence; both engines run |

refusal-expectations.txt captures the exact grep. No TRYAGAIN/BUSY/queue-full
reply text or acceptance was changed: escalation remains a design handoff.
The two existing acceptance files are txnorder.py (txnorder jobs) and xscript.py
(debug jobs); mode_equivalence.py also has a refusal-text parser negative test.
Every run's actual result, including failures and unrun legs, belongs in the
final proof index rather than being inferred from this map of requested jobs.

Final results are recorded in MEASURE-REQUEST-atomfix5.md at the worktree root
and proof-runs.json here. Both standard differential runs passed. Initial
servertail bind failures remain in the first family ledgers; the four affected
jobs passed their gate-interface rechecks on ports 34860–34899 (uring) and
34880–34899 (epoll). The self-tests' final socket fixture used GATE_TEST_PORT=34811.
