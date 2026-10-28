# WATCH finalizer negative control

The original `watch-no-finalize` control correctly failed, but at the later
OOM registry cleanup assertion. Its planned patch only removes the cached
WATCH-presence update in `watch_finalize_reservation`; indexed
`watch_write_ready` can retire the entry itself, bypassing that finalizer.

The lifecycle fixture now calls the targeted finalizer explicitly and asserts
refs reach zero and the gate clears. It then independently asserts write-ready.
The same specific expected diagnostic is retained. No production behavior,
negative-control patch or tolerance changed. `before.log` records the failure;
the dedicated `exbatch_units` gate rerun records the corrected witness.
