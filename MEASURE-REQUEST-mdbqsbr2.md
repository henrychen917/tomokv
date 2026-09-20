# mdbqsbr2 — parked-worker progress and shutdown

Launch reference: `0dfac1b7c` on `cx-mdbqsbr`. Mainline performance reference:
`b8fe404e2`. This lane does not run servers, the gate, or benchmarks.

## Evidence read before code changes

`build/gate-run.qIAHOf/jobs/multidb-1s-0-0/multidb.log` records two
swappers `[128, 128]`, 87 read batches and `multidb PASS`. On that same boot,
`multidb-serial.log` breaks the client barrier at line 116 and `output.log`
records a 30-second shutdown timeout for PID 2598272. The 1s/0/1 boot similarly
passes 256 busy swaps (51 batches), then times out at serial order and shutdown
(PID 2629815). All eight serial-order rows fail. Five of the eight preceding
multidb rows pass; the others fail, including a blocked-waiter SWAPDB in 2s/0/1.

The four 1s recorded PIDs no longer exist in `/proc`. The `gate-srv-*` artifacts
are ordinary stdout logs, not directories or core dumps. They identify t0–t7
and their CPU placement, but contain no stacks, map tickets or drain-ack values.
**An exact historical non-acknowledging participant cannot be recovered from
these artifacts.** No live server was started to manufacture that evidence.

## Diagnosis audit (before implementation)

The missing *retirement* wake is verified: `DatabaseMap::publish` only stores
the map, request and pending bit. The acknowledgement runs at the next outer
`DatabaseWorkScope` entry. IO, reordered IO and EX keep that scope across their
idle network wait. Thus an idle physical worker, including physical t0 (the
only reaper), depends on a natural wait return to acknowledge/reap.

However, the supplied causal explanation is not established by this tree:
`reclaim` uses `try_to_lock` and returns without sufficient acknowledgements;
neither publication nor SWAPDB waits for map grace. The map destructor is
already defaulted and contains no final grace wait. `Ring::submit_and_wait`
already passes a 50 ms timeout to liburing. The SWAPDB **namespace drain** does
wait asynchronously for IO/EX acknowledgements and has no deadline; its initial
wake is conditional on a parked snapshot and later wakes use queued MSG_RING.
The new coarse scope also extends the existing Client lifetime epochs through
IO waits. These are separate mechanisms; a missing map ack must not be reported
as a verified explanation of the live SWAPDB/shutdown deadlock.

The implementation will make retirement and namespace-boundary wakes explicit,
diagnose both kinds of overdue participant independently, and move shutdown
progress supervision to the existing main thread. It must retain every map when
workers stop, then let destruction after joins supply the final grace.

Live PASS claims and the exact historical blocked participant remain unavailable
until mainline runs the supplied real-boot proof and serial-order battery.
