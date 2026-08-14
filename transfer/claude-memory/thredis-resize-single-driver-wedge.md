---
name: thredis-resize-single-driver-wedge
description: "P0-class — flat_resize_active parks all workers but only IO slot 0 (main) can clear it, and its 200ms deadline is evaluated by that same thread, so a blocked main wedges the server forever"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Found 2026-08-02 while diagnosing the `DEBUG RELOAD` crash. Filed as `docs/BUGS.md` J4. **Not fixed** —
the fix touches the resize state machine, which is on the owner's read-only list.

`flat_resize_active = 1` parks every worker. Only `flatResizeCoordinate()` clears it, and every spin
site calls it under `if (iotid == 0)` — and main *is* IO slot 0. So if main blocks for any reason
while a resize is armed, no thread can ever unpark the workers.

The `FLAT_RZ_QUIESCE_DEADLINE_US` (200 ms) escape added as "fix #6" **cannot save this**: it is
evaluated *inside the coordinator*, i.e. by exactly the thread whose blocking caused the wedge.
`FLAT_RZ_COPYING` has no deadline at all. This is the A10 class (`af9d6b590`): one stuck coordinator
flag is a delayed server kill.

Signature of the wedge (how to recognise it again):

    tomokv_flat_resize_active:1   tomokv_ex_queue_full:0
    main (IO slot 0)  S  wchan=futex_do_wait     <- the single driver, blocked
    N workers         R  ~100% CPU               <- spinning in the park loop
    1 IO thread       R  ~100% CPU               <- spinning on a parked worker
    PING/DBSIZE answer intermittently; every worker-routed command hangs forever

**Zero `FLATSTORE resize:` log lines** is the tell — neither "rebuilt" nor "quiesce deadline" means
the coordinator stopped being *called* while armed, rather than looping. Diagnose without gdb
(ptrace_scope=1 blocks attach): `/proc/PID/task/*/stat` for R-vs-S and CPU deltas, `wchan` for where
blocked, and read `tomokv_flat_resize_active` straight out of INFO.

Likely fix when the owner allows it: let ANY thread enforce the QUIESCING deadline. Safe precisely
because QUIESCING has not yet touched the table — aborting there is free. Requires making
`flat_rz_state` atomic for cross-thread read.

Related: [[thredis-3stage-churn-wedge]], [[thredis-preflight-contract]], [[thredis-vacuous-validation-trap]].
