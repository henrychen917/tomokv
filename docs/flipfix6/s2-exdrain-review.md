# S2 meets the preserved executor admission fence

The original design puts S2 handling in ClientPrepare. A PRE-compatible,
serverless fixture now proves that a prepared unpublished EXEC cannot reach
that stage. Eight cases passed: both namespaces, atomic 0/1, surviving and
converting source. See `s2-fence-witness.log` and the build receipts in
`s2-scope/`. No server, DEBUG hook or production modification is used.

1. `multi_handle_io(EXEC)` force-admits a group and opens its apply interval
   before it stores the state in `session->pending` (`multi.inc:2340-2355`).
2. No task is published; ROB and the source's IoDrain predicate are idle.
3. `ExLoopT::flip_quiesced()` requires both `atomic_inflight()==0` and
   `atomic_apply_inflight()==0` (`ex_loop.h:1510-1511`). Both are **1**.
4. Both actual executor control passes refuse to acknowledge ExDrain.
5. As a negative control, `multi_prepare_close` abandons that same unpublished
   state on its original IO. Both counters become zero and those same passes
   acknowledge, with no other readiness state changed.

The session-pointer/WATCH exception alone does not implement D18.2. A unit
which jumps directly from IoDrain to ClientPrepare hides this obstruction.

## Proposed narrow extension (not implemented)

Refuse a converting source's S2 during IoDrain, before the executor barrier.
For a surviving source, publish a FLIP-owned receipt of its exact unpublished
admission/apply credits at IoDrain. Only FLIP's ExDrain may discount those
receipted credits; all published work, queues, ROBs and lifetime fences still
drain. Keep LB's `flip_quiesced` behaviour unchanged. Leave pending state,
admission, age, queue and original IO intact; do not cancel/reprepare or publish
through the global dispatch pause. No added per-command work or time constant.

The receipt must remain exact while a peer can close. Before implementing it,
the same review must settle close cleanup during the frozen stages: today's
`close_client` calls `multi_close_entry` before consulting the FLIP close pin.
That can abandon S2 or prepare a new WATCH cleanup after the drain receipt.
The source-owned receipt and cleanup must have one coherent lifetime. The
conservative proposed policy is to defer that cleanup while the FLIP pin holds,
and promptly roll back a converting source which would otherwise retain it.
The serverless core fixture now confirms this close interaction for databases
1 and 16. It completes WATCH, checks the exact pin count, reaches and
acknowledges the real ExDrain on both executors, closes the client under the
FLIP pin, and runs the ordinary IO cleanup pass. One/two owner inboxes become
nonempty **after their ExDrain acknowledgements**, while the Client remains
pinned. Rollback and ordinary owner drain release every pin. The existing
SPSC safe point must not be weakened to accommodate this new producer.
See `draft-units.log` (`flipfix6-close-witness`); this is a state-only witness,
with no listener or schedule probability.

The permission boundary is the brief's explicit requirement to preserve every
other readiness clause, including atomic groups and executor fences. D18.1's
durable WATCH-pin exception has already been approved and is not being asked
again. No exemption to ExDrain's global admission/apply checks was included in
that ruling. No such exemption has been implemented.
