# STOP: unconditional signal-save fallback during an irreversible FLIP

PRE is 9d6ab5526. This is a stopped subitem of item 2, not a completed fix.

`IoLoop::run_loop` gates the save cron on `!flip_dispatch_paused()`.
Bypassing that gate does not meet the requested clean-save guarantee:

* `Server::shutdown` in src/cmd/server_tail.cc calls `SnapshotManager::start`
  for a required save before publishing any stop flag.
* `SnapshotManager::start` in src/snapshot/snapshot.cc takes the shape admission
  mutex and returns Busy whenever `placement_transition_active()` is true.
  Its comment explicitly requires FLIP and snapshot start to be mutually exclusive.
* `Server::shutdown_from_cron` turns Busy after `kShutdownSaveWaitNs` into Failed,
  clears the pending request and leaves the process running. The existing
  `tests/shutdown_unit.cc::busy_snapshot` asserts this behavior.
* After ExDrain, owner work is frozen until ExInstall, including snapshot work.
  ClientCommit cannot roll back, and RoleReady can contain different old/new
  role tenures while shard ownership and masks are being installed.

The live PRE T01d-style witnesses retain an actual ClientInstall snapshot,
SIGTERM, a forced exit after twelve seconds, no dump.tomo, and restart showing
0/1000 acknowledged keys. Snapshot fields and raw GDB output accompany each run.

The connection-output fix can remove this particular post-commit wedge and
allow normal signal shutdown after FLIP finishes. That is not a universal
post-commit deadline guarantee. Merely bypassing the cron gate, forcing stop
flags, or claiming a save succeeded would be incorrect.

Smallest proposed owner change: a shutdown-only completion/abort handshake with
an explicit stable shard-ownership cut, reusing kShutdownSaveWaitNs. Reversible
stages first roll back; irreversible stages finish the existing role/mask
installation, then admit the final save with IO admission still paused. A hard
fallback for an installation which itself cannot finish needs the owner-frozen
snapshot capture protocol to run at that cut. That changes the frozen FLIP
owner safe-point/truth table, so this lane does not implement it.
