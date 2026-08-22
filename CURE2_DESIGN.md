# CURE2 design: completion-order ticketing with an order-independent per-key structure

## Why cure v1 died (all four failures were ONE structural mistake)
Completion-order seqs are the right idea (proved 712-765k/s vs the 12k arrival-order crater), but
cure v1 kept the per-key version chain SEQ-SORTED, so every install-order-vs-seq-order divergence
demanded a chain REPAIR (re-splice/relocate/head-swap) at stamp time — and every repair spawned a new
bug class: operand-vs-store stamping, sentinel splices that can't sort, dup-key same-seq siblings
(assert db.c:1069), cross-key committed-above-unstamped (assert db.c:1166), and finally the
relocation+head-swap that crashed and broke writer atomicity. The repair IS the bug surface.

## The redesign in one line
**Never reorder the chain. The chain is an append-only, install-ordered BAG; correctness moves to a
read-side resolve rule: value(k, S) = argmax-seq over committed versions with seq <= S.**

## Invariants
- I1 (chain): per-key chain is append-only at head in INSTALL order; only the owner mutates it.
  Installs never inspect seq. (Kept from base; all relocation code deleted.)
- I2 (resolve): a version is visible at snapshot S iff stamped (seq != UNCOMMITTED) and seq <= S.
  value(k,S) = the visible version with max (seq, install_order) — install_order breaks dup-key
  same-seq ties (later install wins, matching same-group argument order). Absent if none or if the
  winner is a tombstone.
- I3 (happens-before, kept verbatim from cure fix-2): stamps are owner-queue ops enqueued BEFORE
  commit_seq advances to their seq; any reader dispatched with S >= seq therefore finds the stamp
  applied when its sub executes on that owner. UNCOMMITTED versions a reader meets are > S. The
  coalesced-MGET path uses the same owner queues (verified in cure v1).
- I4 (retire, kept from cure fix-3): only committed versions with seq strictly below the key's
  committed max retire (after QSBR grace); never a version with a pending stamp op.
- I5 (R1, kept): same-real-client atomic groups draw seqs in dispatch order (per-client FIFO +
  CAS latch) — required for same-conn same-key final state.
- I6 (promotion, NEW — bounds the read cost): when retirement leaves exactly one committed version
  and no uncommitted siblings, the owner strips its vmeta/flag and restores the raw fast path.
  So the resolve walk is TRANSIENT: only keys with in-grace atomic writes pay it; steady-state
  keys are byte-identical to base.
- I7 (plain reads): plain GET (and every raw-head consumer on the read path) must resolve through
  I2 when the head carries vmeta — the head pointer is an entry point to the bag, NOT "the value".
  Heads without vmeta (the common case, and everything when the knob is off) are untouched.

## Why each night failure is now impossible by construction
- Operand-vs-store stamps: fix-1 (record the RETURNED kvobj) retained unchanged.
- Seq-inverted chains: readers compute max — chain order is irrelevant, nothing to invert.
- Dup-key same-seq: no relocation walker to assert; I2's install_order tiebreak decides.
- Committed-above-unstamped / head-swap: no relocation, no head swap — the code paths don't exist.

## What carries over from the frozen cure branch (2s-atomic-cure)
Port: completion-time seq draw + UNCOMMITTED sentinel (506b7b0dc), store-object install records
(fb5dfd249), owner stamp-op plumbing + happens-before (264d6ce5b), retire-pending guard + install
ordinals (2dc017a51). DELETE: every re-splice/relocation/head-update path (the fix-4 commit
1f09c6694 is fully superseded). Base the new branch on the SHIPPED head 8ea5b3b60 so the admission
window composes (it stays as a memory/backpressure valve; with the convoy dead the throughput cap
should lift toward the measured 712-765k ceiling — re-tune the default window on the new curve).

## Acceptance (same gauntlet + hammer + 40s asserted soak, plus)
- p32 HOT 200c pure atomic MSET8 >= 600k/s (target: beat shipped 618k; ceiling ~765k).
- torn 0.000% x8, RYOW 0 (historical direct/permutation/churn arms), 1:9 mix >= shipped (309k/2.78M), OFF parity, no
  crash/wedge in 40s, plain-GET-vs-snapshot-MGET agreement spot-check (I7), promotion verified
  (a hammered key returns to vmeta-free fast path after quiesce — expose a DEBUG/INFO counter).
