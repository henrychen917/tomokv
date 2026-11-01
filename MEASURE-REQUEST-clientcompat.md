## clientcompat

Work in progress on `cx-clientcompat`, PRE `7d2f8a205`. No push. Correctness
servers and builds use CPUs 64–79, ports 20400–20499, and `LC_ALL=C`.
No performance benchmark, load generator, or full iteration gate is run.

### PRE witnesses

The five `clientcompat-*` jobs use gate.sh's own job interface. Each declares
both modes, both engines, databases 1/16, atomic 0/1, and read-local 0/1 (32
candidate legs), plus the Redis 7.4.10 oracle. The MULTI read witness reuses
the four schedules in round4-read/repro-tracking/t2_multitrack.py and checks
both early invalidations and the mandatory invalidation after EXEC.

* D13: Redis passes; PRE fails the ALL/CLIENT ID postponement assertion.
* D14: Redis passes; PRE intermittently retains disconnected clients in INFO
  immediately after a completed CLIENT KILL. Ownership reclamation remains
  separate from the new display count.
* D16 / TRACK-MULTI-READS-UNTRACKED: Redis passes; PRE sends the invalidation
  while the read is only QUEUED. The existing owner reproduction independently
  established the missing post-EXEC invalidation in all eight geometries.
* 68d-5: Redis queues ACL; PRE refuses it. Redis queues SSUBSCRIBE but returns
  `ERR SSUBSCRIBE isn't allowed for a DENY BLOCKING client` for that EXEC child.
* TRACKING-ENABLE-RACE: the initial 200-round ordinary enable/write search did
  not reproduce it. The stronger finite LPOS occupation schedule, using the
  maxmemrace observed-owner geometry, **does reproduce missing invalidations
  on PRE after TRACKING ON's +OK**; Redis passes. Full counts are pending.

Raw gate directories currently retained under build/: `gate-run.EMDfcI`
(initial PRE), `gate-run.4JEEF9` (corrected oracle subscription expectation),
`gate-run.cTSPsL` (directed enable race). PRE binary identity is recorded in
`docs/clientcompat/pre-sha256.txt`.

### Scope decisions and validation still in progress

FLUSHALL/FLUSHDB remain refused inside MULTI. `xshard_prepare_flush` owns its
group placement, WATCH reservations, independent epoch, AOF group and phase-two
collapse. `execute_flush` requires `txn_group_ready`; `flush_after_decision`
uses `state.group_attempt()->retry`. EXEC children instead share the parent's
decision and finish through `xshard_multi_child_complete`. Simply admitting
the existing FLUSH unit would not compose these lifetimes or order later
transaction reads/writes. Child-aware lowering is an algorithm change and is
outside the approved conditional scope. DEBUG RELOAD/LOADAOF remain refused,
awaiting the database-boundary design B.

The Tcl inventory is `docs/clientcompat/tcl-inventory.json`. The manifest
promotes the old ALL-pause precedence assertion and CLIENT KILL SKIPME's
immediate connected-client count assertion, subject to the final Tcl run.
The already-passing tracking transaction response-order assertion remains.
The tracking #11715 skip also requires tracking-table eviction/cron behavior;
it is not a direct QUEUED-read enrolment assertion. The FLUSHDB-in-MULTI skip
remains for the design reason above.

All new rows are collected at the `clientcompat-*` loop before the quick-tier
exit. **DQ=+5, DF=+5** over 999/1016: maintainer counts should become **1004/1021**.
EXPECT_QUICK and EXPECT_FULL have not been edited. Tcl promotions add no
public gate rows.

Final POST/PAD-A identities, instruction counts, complete correctness receipts,
and the maintainer measurement request will be appended after validation.
