# Constants ledger: round-3 IO11/IO12 addendum

The audit names `scratchpad/constants-ledger.html` as the authoritative ledger.
That file is absent from this worktree, all local Git history, and the accessible
home tree at this lane's launch. These rows use the audit's ledger columns and
are the reviewable addendum to incorporate into that ledger. Values below are
shipped values, not claims that the proposed derivations were applied or measured.

| Constant | File | Shipped value / unit | Ledger verdict | As shipped / derivation and evidence |
|---|---|---|---|---|
| `kIoPipeIfidBatchClients` | `src/core/iopipe_pipeline.h` | 64 clients | OPEN | Fixed split-IO parse batch cap. The source motivates shallow backlog and a 64-slot ROB, but a per-connection ROB does not derive a client count. No optimum claimed; unchanged. |
| `kIoPipeWbBatchClients` | same | 64 clients | OPEN | Fixed split-IO writeback connection batch cap. A ROB bounds ops per connection, not clients per batch. Unchanged pending measurement. |
| `kIoPipeWbPrefetchOpsPerClient` | same | 64 operations | DERIVE proposed; unapplied | Equals current `kRobWindow=64`. Unchanged literal; the prefetch walk also stops at the completed prefix. |
| `kIoPipeWbBorrowPrefetchBytes` | same | 512 bytes | OPEN | Caps borrowed-payload prefetch to eight current cache lines. Hint only; no lifetime extension. No measured optimum claimed. |
| `kIoPipeCacheLineBytes` | retired from same | formerly 64 bytes | DELETE duplicate; APPLIED | The prefetch stride now uses existing `tomo::kCacheLine` from `src/exec/exqueue.h` (64 on this build). No new hardware constant or runtime lookup. |
| `kIoPipeWbBackstopTurns` | `src/core/iopipe_pipeline.h` | 64 turns | KEEP cadence; duplicate tied | Names the existing mask-independent completion backstop. `IoLoop::kFlushBackstopEvery` now derives from this constant. Value unchanged; no cadence optimum claimed. |
| `kIoPipeDepthWindowPasses` | same | 4 passes | OPEN | Depth history length for natural-order selection. A fixed policy window, not a hardware fact; unchanged and not claimed optimal. |
| `kIoPipeNaturalEnterFramesPerPass` | same | 64 frames/pass | OPEN | Natural-order entry level. Multiplied by the 4-pass window. The ROB-depth rationale is qualitative, not an applied resource derivation. |
| `kIoPipeNaturalLeaveFramesPerPass` | same | 32 frames/pass | OPEN | Natural-order exit level provides hysteresis below 64. Unchanged fixed policy threshold; no measured optimum claimed. |
| epoll park timeout | `src/core/io_loop.h`, generated `src/core/reorder.cc` | 50 ms | DERIVE; APPLIED | Both park calls now use `Ring::kWaitTimeoutMs`, the same bound as ring waits. |
| client cron interval | same | 100 ms | DERIVE; APPLIED | Now `1000 / kClientCronBeatsPerSecond`; the shipped 10 beats/s gives the same 100 ms interval. |
| `IoTenure::WindowNs` default | `src/core/signalacct.h` | 100000 ns | KEEP shipped; derivation OPEN | Complete elapsed time is booked per signal window; `0` is the eager unit/control specialization. This lane changes neither cadence nor accounting. |

IO11 changes spellings only. The byte-audit receipt in the lane report decides
whether the compiled ordinary command, parse, and dispatch bodies are preserved.
