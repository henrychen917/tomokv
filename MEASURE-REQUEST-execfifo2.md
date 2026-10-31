# FIFO hand-off on the current headline

## execfifo2

Base/PRE: `e32b04a445b056976abb308aa598e356fcbaae74`.
Approved source: `cx-execfifo-arm-c1` / `bd0cb9668` (B+C1 only, D6).
Lane: `cx-execfifo2`; no push. All builds and correctness work use CPUs 0–31,
ports 20100–20199, and `LC_ALL=C` for every server boot. Performance and the
full iteration remain maintainer work; no throughput claim is made.

Port sequence: B with unified EXEC/escalated-script key admission; then C1
owner-local chaining and H3 boundaries, preserving headline X1–X5, woundfix,
D1–D10/amend1/D4′ and FLIP stage obligations. C2/C3 are excluded.

Verification and release/PAD-A artifact identities will be recorded here.
`EXPECT_QUICK` and `EXPECT_FULL` remain unchanged; DQ/DF will be counted at the
collection lines relative to the quick exit.

### Implemented order and progress argument

For each owner/key, a plain writer W is refused by a live, **waiting EXEC**
whose monotonic age is <= W's saved writer-episode stamp. On first refusal the
existing A' episode marks every key touched on that owner. Repeated dispatch
probes preserve the stamp; only the final execution gate removes its marks.
A younger unit cannot place ahead of that stamp. The retiring EXEC promotes an
eligible writer to the front of the deferred queue, where the writer still
rechecks its complete key set and connection order. This is the D1 amendment.

EXEC and escalated scripts use the same `TxnKeyQueue::head`, comparator
`(age_ns, age_io, age_seq)`, monotonic clock and IO sequence. A script draws that
age at its **first escalated IO dispatch**, preserving it across retries. Its
optimistic-slot FIFO remains per IO and counts only optimistic activations;
escalated attempts use neither a slot nor a read cut (AT4.12 C8). No second
EXEC-versus-script priority queue or script age reset is introduced. F10 checks
both mixed arrival orders and a script younger than an existing writer mark.

D-F1/2/3 remain **no/no/no**: whole-shard waiters do not FIFO-block keyed
writers; kind-2 waiters (including escalated scripts) do not gain a new
plain-writer FIFO predicate; unstarted placed EXEC claims are not FIFO
waiters. Existing held/started/validation predicates still apply. FLUSH checks
all relevant queues. EXEC children, blind atomic groups, script APPLY,
blocking serves, WATCH/UNWATCH and committed dirtying retain their original
non-FIFO predicates (R-F2). Script placement still obeys the shared claim
order and writer marks; D4's execution immunity and cancellation rules stay.

For a fixed stamped writer, later EXECs cannot enlarge its predecessor set:
its finite older waiting/held units drain, and younger units wait on its mark.
The mark survives both readiness probes (R-F1), so a passing writer cannot
accidentally acquire a younger episode. Progress assumes the existing owner
scheduler and predecessor progress, rather than imposing a new reader wait.
F1/F2/F3 assert actual refusal, stamp persistence, and hand-off; F6 puts 1,000
younger units behind the mark. The live row requires all four plain clients to
progress in every one-second window of a continuous EXEC stream, with exact
data/counter checks and the inherited latency bounds.

C1 drains only owner-local runnable nodes, with a recursion guard. Siblings
released by arrival/phase/command/decision events and the next eligible EXEC
can run in the same turn. A refused markless operation leaves an H3 boundary
note; boundary service precedes another fresh EXEC, while already placed
siblings may complete. The note never becomes a placement dependency (B9).
Boundary notes live in existing shard padding and move with the shard. Runnable
nodes remain in the existing retry count, so the unchanged ExDrain quiescence
check includes them. `flip_stage_owed` and all FLIP acknowledgements are intact.

Port-specific adaptations retain compact participant slots, fused wake hints,
`execute_resumed` timing, the tracked/untracked `multi_execute.inc` variants,
repeated-key version reuse and X2 eager reclamation. No C2 event parking or C3
lone-claim shortcut is present.

### Gate accounting

Ten FIFO directed rows (including new mixed-script F10), one sustained FIFO
row, and four C1 rows (local, WATCH boundary, BLPOP boundary, hot hand-off) are
collected before the quick exit. **DQ=+15, DF=+15**. The source inventory is
994 -> 1009 full rows with no removed labels. The unchanged 977/994 constants
should become **992/1009**; only the maintainer changes them.

### Verification status

Verification is in progress. Completed-run identities and any failed attempts
will be retained under `docs/execfifo2/`. This is a selected-job proof, never a
full iteration receipt. The full iteration and all performance cells are
**NOT RUN** by this lane.
