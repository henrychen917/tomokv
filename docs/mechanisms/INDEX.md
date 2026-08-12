# TomoKV — Mechanism Index

## Navigation

- [README](../../README.md)
- [Thread-per-core execution](../execution-model.md)
- [FLATSTORE](../storage-flatstore.md)
- [QSBR reclamation](../reclamation-qsbr.md)
- [MVCC atomics](../atomics-mvcc.md)
- [Cross-shard scatter/gather](../crossshard.md)
- [Online resharding](../reshard-migration.md)
- [Load balancing](../loadbalance-flip.md)

Granular, code-derived docs for every named buffer, prefetch stage, communication channel, and
algorithm/calculation. Each file cites file:line and documents the real data structure + protocol.
Parent: the 7 subsystem docs in `../` link down to these; the top-level `../../README.md` is the hub.

## buffers
- [`buffers/cdb-completion-slots.md`](buffers/cdb-completion-slots.md) — `cdbSlots` — EX-to-IO reply-completion cache line
- [`buffers/fake-client-ring.md`](buffers/fake-client-ring.md) — `clientExecTail.fakeClients[]` — per-real-client fake-client pipeline ring
- [`buffers/freeback-ring.md`](buffers/freeback-ring.md) — `freebackRing` — IO-to-owner-worker object-reference return ring
- [`buffers/group-pin-slots.md`](buffers/group-pin-slots.md) — `flatGroupPinSlot`: generation-counted dispatch-lifetime pin slot
- [`buffers/pending-command-pool.md`](buffers/pending-command-pool.md) — `pendingCommand`, `pendingCommandList`, and `pendingCommandPool` — pending-com
- [`buffers/reply-buffer.md`](buffers/reply-buffer.md) — `client->buf`, `client->reply`, `clientReplyBlock`, and `replBufBlock`: reply bu
- [`buffers/spsc-dispatch-ring.md`](buffers/spsc-dispatch-ring.md) — `exQueue`: per-(IO, worker) SPSC dispatch ring
- [`buffers/version-bag.md`](buffers/version-bag.md) — `tomoVerMeta` — per-version metadata and the version bag

## prefetch
- [`prefetch/crossnode-prefetch.md`](prefetch/crossnode-prefetch.md) — `cross_node` mode 2 — topology-gated cross-node message/reply prefetch
- [`prefetch/exprefetchbatch.md`](prefetch/exprefetchbatch.md) — `exPrefetchBatch` — the worker-side batch storage-warm driver
- [`prefetch/l3-footprint-gate.md`](prefetch/l3-footprint-gate.md) — `pf_cached_min` — the L3-derived prefetch-footprint gate
- [`prefetch/message-carrier-prefetch.md`](prefetch/message-carrier-prefetch.md) — `tomoMessagePrefetch` — incoming ring-carrier prefetch
- [`prefetch/prefetch-engagement-counters.md`](prefetch/prefetch-engagement-counters.md) — `pf_batches`, `pf_gated`, `pf_issued`, `prefetch_ex_xnode_issued`, and `prefetch
- [`prefetch/prefetch-stages.md`](prefetch/prefetch-stages.md) — `PFS_*` — the worker lookup-prefetch scoreboard states

## communication
- [`communication/cdb-completion-bus.md`](communication/cdb-completion-bus.md) — `cdbSlotPublish` / `cdbSlotReady` / `cdbSlotClear` — EX-to-IO reply-ready comp
- [`communication/crossnode-topology-table.md`](communication/crossnode-topology-table.md) — `cross_node[][]` and `cross_node_any`: cross-node producer/consumer topology tab
- [`communication/migration-drain-fence.md`](communication/migration-drain-fence.md) — `migPushFenceIfNeeded` / `drain_ack` / `fence_acked` — migration cutover execu
- [`communication/owner-lock.md`](communication/owner-lock.md) — `tomoWkrLock` / `tomoWkrTrylock` / `tomoWkrUnlock` / `tomoWkrLockPub` / `tomoWkr
- [`communication/owner-op-stamp-lane.md`](communication/owner-op-stamp-lane.md) — `csStampLane` / `csStampPush` / `csStampRoute` / `csStampDrain` / `owner_ops_pen
- [`communication/ring-push-pop.md`](communication/ring-push-pop.md) — `exQueuePush` / `exQueuePopBatch` / `exQueuePopOrdered` / `staged_tail` — batc

## algorithms
- [`algorithms/atomic-window.md`](algorithms/atomic-window.md) — tomokv-atomic-window: the atomic-write admission window
- [`algorithms/bloom-signature.md`](algorithms/bloom-signature.md) — key_sig: the per-group key-set bloom signature
- [`algorithms/client-lb.md`](algorithms/client-lb.md) — Client-LB: continuous connection rebalance across IO threads
- [`algorithms/commit-seq-ordering.md`](algorithms/commit-seq-ordering.md) — commit_seq: the global commit-order counter
- [`algorithms/del-tombstone-versions.md`](algorithms/del-tombstone-versions.md) — DEL / UNLINK and tombstone versions
- [`algorithms/flat-hash-and-tag.md`](algorithms/flat-hash-and-tag.md) — FLATSTORE slot word: hash, tag, and pointer encoding
- [`algorithms/flat-load-factor-and-resize.md`](algorithms/flat-load-factor-and-resize.md) — FLATSTORE load factor, resize triggers, and grow/shrink sizing
- [`algorithms/flat-probe.md`](algorithms/flat-probe.md) — FLATSTORE linear probing: read, write-search, and the single-CAS insert claim
- [`algorithms/flip-anchor-and-episode.md`](algorithms/flip-anchor-and-episode.md) — Flip anchor and the directional in-floor episode
- [`algorithms/flip-drops.md`](algorithms/flip-drops.md) — Flip anchor drops: the three settled change-detectors and the REVERT damping
- [`algorithms/flip-judge.md`](algorithms/flip-judge.md) — Flip throughput judge: `getNumCommands()` vs per-worker `ops_total`
- [`algorithms/flip-signal.md`](algorithms/flip-signal.md) — Flip signal: the productive-work ratio `lr = ln(u_io/u_ex)`
- [`algorithms/flip-trigger-and-actuation.md`](algorithms/flip-trigger-and-actuation.md) — Flip trigger and actuation: the Schmitt gate, the granularity floor, and the k-j
- [`algorithms/install-commit-protocol.md`](algorithms/install-commit-protocol.md) — The two-phase install-then-commit protocol
- [`algorithms/key-lb.md`](algorithms/key-lb.md) — Key-LB: the hot-BUCKET detector and bucket-range cutover
- [`algorithms/key-to-worker-hash.md`](algorithms/key-to-worker-hash.md) — Key → bucket → worker routing (`ex_bucket_table`)
- [`algorithms/own-read-widening.md`](algorithms/own-read-widening.md) — Own-read: reading your own uncommitted / stamped writes
- [`algorithms/qsbr-grace.md`](algorithms/qsbr-grace.md) — FLATSTORE QSBR grace determination
- [`algorithms/reclaim-budget.md`](algorithms/reclaim-budget.md) — FLATSTORE budgeted reclaim, same-arena free, and the two-grace physical retire
- [`algorithms/version-resolve.md`](algorithms/version-resolve.md) — kvobjVersionAt: resolving a version bag at a snapshot

