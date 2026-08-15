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
- `N > 0`: an exact process-wide byte limit.

Each atomic install is still charged to its immutable install owner for exact skew telemetry. At
group completion, the shared commit record sums those charges and performs one process-pool RMW.
The conservative group charge remains until the last version metadata from that group retires.
This avoids one contended global RMW per key while allowing a skewed hot worker to borrow unused
capacity from other workers.

The exact per-version owner charge survives while the version is linked, while its pre-unlink or
post-unlink QSBR grace is pinned, and while the value waits in a retire batch. It is released once:

- when a still-versioned value is physically freed (including resize discard), or
- when the sole surviving live value is promoted back to the raw representation.

Owner counters are lazily allocated only for atomic mode with backpressure enabled and are
separated by cache lines. The pooled counter is separately cache-line-isolated. The ordinary
`tomokv-atomic no` path neither allocates nor touches this state.

When the pooled charge exceeds its limit, a pressure edge is published. New atomic writes park at
the same pre-ring gate as a full group window. Reads, already-admitted groups, owner stamp/prune
jobs, and worker QSBR reclaim continue to run. Releasing the last metadata reference of a charged
group decrements the pool, refreshes pressure, and wakes parked IO loops once it is within budget.
A charge rechecks the pool after publishing pressure: if a concurrent final release crossed below
the cap before seeing that store, the existing clear-and-rescan protocol removes the otherwise
stale gate without losing a racing new charge.

## Why there is no membership probe

The former own-read gate hashed written keys into 64 bits, then carried exact vectors and a
per-connection publishing ring to settle filter hits. Eight-key groups alias heavily in a 64-bit
signature, and the machinery continued to allocate and copy state even after own-read visibility
moved to the owner-local `origin_client_id` resolver.

That probe and all of its allocations are removed. Same-connection reads select their own live
version exactly on the key owner; other readers use the commit clock. No key-signature test
participates in visibility, ordering, or writer admission.

## Ordering and wake invariants

1. Commit-time sequencing publishes one shared timestamp only after the last owner stamp; there is
   no per-connection registration FIFO or incomplete-group frontier.
2. Reshard cutover still fences on `tomo_atomic_unsealed` plus install-owner lifecycle references;
   the reclaim budget does not alter the flip controller.
3. A parked command owns no fake/group state. Its IO owner alone removes it from the parked list and
   retries it.
4. A pressure clear and concurrent pooled charge cannot lose the pressure edge: clear happens
   before a sequentially-consistent pool check, while a later charge republishes pressure.
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

Together these distinguish group-window saturation from memory backpressure and show that retained
bytes drain after writer throttling engages.
