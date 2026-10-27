# exec1s preservation audit

This is a source audit of the refinements, separate from the executed gate receipts.
The baseline is 83e0b809d; the execfifo admission mechanism is absent.

| Rule | Preserved boundary |
| --- | --- |
| D1 | Writer readiness and started/validation predicates are unchanged. The extra fused opportunities call the complete guarded owner pass. No reader retry or reader wait is added. |
| D2 | No phase, version comparison, wound predicate, immunity point, decision CAS or retry inheritance rule changes. |
| D3 | The blind scan's visitor is unchanged. Its fast exit requires the owner-local group-record count to be zero and total live records below 256; modulo wrap cannot hide a group. Live MSET and script records are directed fixtures. |
| D4′ | Script admission, escalation, kind-2 identity, retained ages, certification and cleanup are unchanged. Scheduling hints are only for existing EXEC retry opportunities. |
| D5 (txnorder) | Read-only dispatch cuts, pin publication and unpin rules are unchanged. This rule is distinct from the exec1s owner's WB decision also called D5. |
| D6 | Whole-shard claims and wildcard expansion are unchanged. X5 changes storage indices, including claim-only metadata slots, without expanding or shrinking execution participants. |
| D7 | Notification batches and tracking still publish at retirement. X4 can delay only its own buffered block prefix; it changes no notification or commit ordering rule. |
| D8 | No retired exclusive fallback, knob or INFO counter is restored. New diagnostic counters are outside the locked hot layouts. |
| D9 | AOF ticket/group ordering is unchanged. Production AOF/snapshot writes use the bound IO writer ring, which remains entered; tracking persistence tags on an EX ring is covered by the directed ring fixture. |
| D10 | WATCH validation still happens in the same placement turn and holds the same writer-blocking claims. WATCH-only and close states keep identity indexing. |
| amend1 | Writer marks, episode stamps, first-poll same-connection parks, placement comparisons and promotion identities are unchanged. No FIFO writer hand-off is added. |

X2 calls the existing shard cleanup with the commit cutoff loaded before the
reader floor. It changes when decided records are reclaimed, not their visibility,
QSBR retirement or lifetime predicates. A pinned-reader fixture must retain its
records and then reclaim them after unpinning. Removing the eager helper call in
a throwaway unit makes the unchanged threshold assertion fail.

X3 bells hold no shard/client pointers. Migration therefore has no new per-owner
structure named by a shard to transfer. A stale hint only schedules a normal pass;
normal polling remains the liveness backstop. The two boundary passes retain
freeze, snapshot, read-local publication and cross-shard commit guards. The
generated R7 envelope uses the R7-specific full pass for both extra turns; the
generator and its stale-copy control require both sites.

X5 allocates and fills the map before publication. Owner execution only reads it.
The 255 sentinel is unused until all 256 physical shards have slots. The first
live breadth run exposed missing slots for metadata-only claim shards; the fix
retains those claims without adding owner tasks, and LMPOP now has a directed
regression witness. No locked footprint changed.

The separate Opus-max audit is retained in `opus-audit-initial.md` with model
and source provenance in `opus-audit-initial.json`. Its C2 overlapping-write race
and C3 publication omission required repair; the old x86 value-preserving write
was not acceptable under the C++ memory model. X1's private tag collision and
X5's incidental WATCH-first discovery order were also removed. A follow-up audit
and refreshed runtime receipts remain pending.
