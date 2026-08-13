# Single-node flip compatibility fix

## Result

`nnodes==1` now follows the flip decision and actuation ordering from base
`57df9cd44`. The per-node controller partition, peer admission serialization,
deferred main-thread tail, and reserved migration mailbox remain enabled only
where they are needed for `nnodes>1`.

## Root cause

The suspected main-tail deferral was not the single-node regression.
`tmFlipUsesMainTail()` was already false for node 0 because its semi-main is the
real main (`iotid==0`). A one-node flip therefore completed its live-count
accounting, client rebalance, EWMA transfer/rebase, relevel publication, and
claim release inline in `tmFlipTick`, before another 4 Hz controller sample.

The real divergence was that multi-node concurrency protocols had also been
applied to the historically single-owner path:

- `tmFlipTryClaim()` acquired the migration admission lock and rejected flush,
  migration, or active-resize state before publishing the flip claim. Base used
  only the flip-context CAS.
- A flip arm tested `flatResizeAnyActive()` and the new flip-action polarity,
  while base tested `flatResizePending()`. A resize that was pending but had not
  become active could therefore lose priority to a flip in the fork. Conversely,
  `flatResizeCoordinate()` newly refused to advance while a flip claim existed.
  Those changes alter which 4 Hz pressure sample becomes an applied probe and
  where its settle/anchor window starts.
- Post-flip relevel, fine-window placement, diffusion, and outlier planning
  acquired the new peer-controller admission lock before planning. Base planned
  first, tried `reshardArm()` at the publication edge, continued past refused
  relevel arms, and cleared the relevel one-shot after a fully refused pass.
  The fork could retain relevel and postpone ordinary EWMA convergence.
- Connection-migration requests used the new EMPTY/RESERVED/READY protocol on
  one node. Base used a direct EMPTY/READY publication edge, including its
  original watchdog overwrite and owner-clear ordering.

Together these were controller/actuator ordering changes, not throughput or
thermal changes, and they explain why the static curve remained unchanged while
AUTO applied extra probes and settled at a different configuration.

## Fix

The compatibility split is explicit:

- On one node, a flip claim is the base CAS-only claim. Multi-node claims retain
  the shared migration/resize admission lock and all peer safety checks.
- On one node, reshard admission restores the base flush, pending-resize, range,
  and flip-action ordering; flat resize no longer gains a flip-context veto.
  Multi-node flip arms retain the pending-vs-active rule and polarity checks that
  prevent peer deadlocks.
- The one-node flush gate remains the base boolean `0/1` edge; `WAITING/FROZEN`
  staging is confined to the multi-node drain protocol.
- Node 0 never enters or pumps the multi-node main-tail handoff. Flip completion
  remains inline, including the base grow-front action publication timing and
  grow-back EWMA/relevel call contract.
- Row zero remains the storage backing for the one-node controller, but its
  relevel, fine-window, diffusion, and outlier paths use the base plan-then-arm
  cadence and base relevel clear semantics. Per-node rows keep their locked
  snapshot/arm protocol for `nnodes>1`.
- Node 0 uses the base EMPTY/READY request mailbox, including direct publication,
  cancellation ordering, request clearing, and retry publication. Multiple
  nodes retain EMPTY/RESERVED/READY so competing controllers cannot overwrite a
  request.

## Validation boundary

No build, server, test, or benchmark was run, as required. Validation is the
external `controller_sweep` A/B against `57df9cd44`; the local check was limited
to source/diff inspection and whitespace validation.
