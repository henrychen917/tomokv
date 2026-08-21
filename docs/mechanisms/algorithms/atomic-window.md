# Atomic-write admission and reclaim backpressure

`tomokv-atomic` has two writer-only admission limits. Neither is consulted while atomic mode is
off, and neither can stall a read.

## Group window

`tomokv-atomic-window` is modifiable and accepts:

- `-1` (default): `live writer slots * tomokv-pipeline-depth`.
- `0`: unlimited group admission.
- `N > 0`: an exact process-wide in-flight group limit.

The auto rule is structural: the writer population changes with a role flip, while pipeline depth
is already the bound on resident commands per producer. It replaces the fixed 64-group default,
which was calibrated on a much smaller writer pool and became a completion-frontier bottleneck at
64-core concurrency.

`tomo_atomic_inflight` is a cache-line-isolated global counter. A finite window reserves with a CAS
strictly below its effective limit; the unlimited arm still increments it for lifecycle accounting.
The counter is decremented exactly once at terminal group reassembly.

Refusal occurs before a fake-ring slot or group is allocated. The client remains on its owning IO
thread's parked list with `CLIENT_ATOMIC_WINDOW_STALLED | CLIENT_PIPELINE_STALLED`, so its decoded
pending command can be retried by a later event-loop pass.

Each IO owner publishes an atomic waiter count without exposing its owner-only list. Terminal
reassembly consumes a local free slot in the same before-sleep pass when possible; otherwise it
round-robins to one remote owner and coalesces an already-pending notifier edge. It never broadcasts
one retirement to the entire IO pool. Enroll-then-recheck and retire-then-check are separated by
sequentially consistent fences, so a slot freed across the park edge is either assigned by the
retirer or observed by the parker's one self-wake.

## Process-wide reclaim pool

`tomokv-atomic-reclaim-limit` is modifiable and accepts:

- `-1` (default): one sixteenth of maxmemory, or physical RAM when maxmemory is zero.
- `0`: disabled; no reclaim-counter table is allocated at boot.
- `N > 0`: the process-wide folded-byte admission target.

Each atomic install is charged to its immutable install owner. One owner record publishes its
already-summed bytes to that owner's cache-line-isolated slot with a local load/store. The main
controller folds all owner slots once per completed `serverCron` tick and release-replaces the
process-wide snapshot; group publish and final commit release do not modify the global value.
This removes both process-global RMWs per group while allowing a skewed hot worker to borrow unused
capacity from other workers.

The exact per-version owner charge survives while the version is linked, while its pre-unlink or
post-unlink QSBR grace is pinned, and while the value waits in a retire batch. It is released once:

- when a still-versioned value is physically freed (including resize discard), or
- when the sole surviving live value is promoted back to the raw representation.

Owner counters are lazily allocated only for atomic mode with backpressure enabled and are
separated by cache lines. The folded snapshot is separately cache-line-isolated. The ordinary
`tomokv-atomic no` path neither allocates nor touches the owner table.

When the folded snapshot exceeds its limit, new atomic writes park at the same pre-ring gate as a
full group window. Reads, already-admitted groups, owner-local publish/retirement, and worker QSBR
reclaim continue to run. Each version release immediately lowers its exact owner slot; the next
controller fold which observes the total within budget clears the pressure mirror and wakes parked
IO loops.

The accounting staleness bound is one controller sampling interval: in an on-time loop the
published value is at most `1000/server.hz` milliseconds old, and an update racing a fold is included
by the next completed tick. If the event loop itself is delayed, the bound is correspondingly “the
next completed controller tick,” like the other `serverCron` controllers. Admission can therefore
temporarily undershoot or overshoot by bytes published/released during one interval. The limit is a
soft backpressure target with process-memory hysteresis headroom (auto mode uses only 1/16 of the
memory source), while `tomo_atomic_inflight` remains the exact simultaneous-group semaphore.

## Why there is no membership probe

The former own-read gate hashed written keys into 64 bits, then carried exact vectors and a
per-connection publishing ring to settle filter hits. Eight-key groups alias heavily in a 64-bit
signature, and the machinery continued to allocate and copy state even after own-read visibility
moved to the owner-local `origin_client_id` resolver.

That probe and all of its allocations are removed. Same-connection reads select their own live
version exactly on the key owner; other readers use the commit clock. No key-signature test
participates in visibility, ordering, or writer admission.

## Ordering and wake invariants

1. Commit-time sequencing publishes one shared timestamp only after the last owner-local publish; there is
   no per-connection registration FIFO or incomplete-group frontier.
2. Reshard cutover still fences on the unsealed admission census plus install-owner lifecycle
   references. The census is cache-line-sharded by originating IO/WB producer; after closing the
   cutover gate, the coordinator folds every slot before consulting lifecycle references. The
   reclaim budget does not alter the flip controller.
3. A parked command owns no fake/group state. Its IO owner alone removes it from the parked list and
   retries it.
4. Admission reads the release-published folded byte snapshot directly. The pressure byte is only
   its controller-published mirror for reclaim boosting and INFO, so it cannot create a divergent
   admission decision.
5. Disabling atomic mode makes the retry walk ignore both atomic gates, allowing parked commands to
   resume through the ordinary path.
6. One group retirement creates at most one remote admission wake; a producer with an outstanding
   wake consumes every currently open slot it can before handing residual capacity onward.

## Observability

INFO exposes:

- `tomokv_atomic_window_effective`
- `tomokv_atomic_reclaim_limit`
- `tomokv_atomic_reclaim_bytes`
- `tomokv_atomic_reclaim_worker_bytes`
- `tomokv_atomic_reclaim_worker_max`
- `tomokv_atomic_reclaim_pressure`
- `tomokv_atomic_reclaim_stalls`
- `tomokv_atomic_reclaim_folds`
- `tomokv_atomic_admission_census_folds`

Together these distinguish group-window saturation from memory backpressure and show that retained
bytes drain after writer throttling engages. The admission-census witness advances only when a
coordinator fold actually observes at least one admitted, unsealed group; an empty cutover does not
satisfy the anti-vacuous check.
