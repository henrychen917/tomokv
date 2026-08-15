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

## Per-worker reclaim budget

`tomokv-atomic-reclaim-limit` is modifiable and accepts:

- `-1` (default): one sixteenth of maxmemory, or physical RAM when maxmemory is zero, divided by
  the configured worker count.
- `0`: disabled; no reclaim-counter table is allocated at boot.
- `N > 0`: an exact byte limit for each worker.

Each successful atomic install is charged to its immutable install owner. The charge is the full
allocation size of the versioned key/value and metadata introduced by the atomic pipeline. It
survives while the version is linked, while its pre-unlink or post-unlink QSBR grace is pinned, and
while the value waits in a retire batch. It is released exactly once:

- when a still-versioned value is physically freed (including resize discard), or
- when the sole surviving live value is promoted back to the raw representation.

Counters are lazily allocated only for atomic mode with backpressure enabled and are separated by
cache lines, so install owners do not false-share. The ordinary `tomokv-atomic no` path neither
allocates nor touches this state.

When any worker exceeds its limit, a global pressure edge is published. New atomic writes park at
the same pre-ring gate as a full group window. Reads, already-admitted groups, owner stamp/prune
jobs, and worker QSBR reclaim continue to run. The worker that crosses back under its limit
rechecks all owners, clears pressure only when all are within budget, and wakes parked IO loops.
This converts a pinned-grace memory runaway into bounded writer throttling.

## Why there is no membership probe

The former own-read gate hashed written keys into 64 bits, then carried exact vectors and a
per-connection publishing ring to settle filter hits. Eight-key groups alias heavily in a 64-bit
signature, and the machinery continued to allocate and copy state even after own-read visibility
moved to the owner-local `origin_client_id` resolver.

That probe and all of its allocations are removed. Same-connection reads select their own live
version exactly on the key owner; other readers use the committed sequence. No key-signature test
participates in visibility, ordering, or writer admission.

## Ordering and wake invariants

1. The global commit sequence and per-connection registration FIFO are unchanged; readers still
   cannot observe a torn multi-key group.
2. Reshard cutover still fences on `tomo_atomic_unsealed` plus install-owner lifecycle references;
   the reclaim budget does not alter the flip controller.
3. A parked command owns no fake/group state. Its IO owner alone removes it from the parked list and
   retries it.
4. A pressure clear and a concurrent charge cannot lose the pressure edge: clear happens before a
   sequentially-consistent per-worker rescan, while a later charge republishes pressure.
5. Disabling atomic mode makes the retry walk ignore both atomic gates, allowing parked commands to
   resume through the ordinary path.

## Observability

INFO exposes:

- `tomokv_atomic_window_effective`
- `tomokv_atomic_reclaim_limit_per_worker`
- `tomokv_atomic_reclaim_bytes`
- `tomokv_atomic_reclaim_worker_max`
- `tomokv_atomic_reclaim_pressure`
- `tomokv_atomic_reclaim_stalls`

Together these distinguish group-window saturation from memory backpressure and show that retained
bytes drain after writer throttling engages.
