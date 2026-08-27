# Cross-shard script lane

## Status

Stage 0 is complete and separately committed. Stage 1 is blocked by a contradiction between the
binding proposal and the MVCC primitive present in this tree. No cross-shard execution code was
written after finding the contradiction, so the branch contains no knowingly weakened isolation
path.

## Stage 0 delivered

- `41ae3c191 fix: persist script writes as AOF groups`
  - Single-owner EVAL/EVALSHA/FCALL writes are emitted as one AOF post-image group.
  - Recovery coverage and ASAN evidence are in `NOTES-AOFSCRIPT.md`.
- `58b3d719a fix: watch only declared script keys`
  - WATCH invalidation walks the parsed ScriptRoute KEYS range rather than the registry's legacy
    `3..-1` range, so ARGV no longer produces a spurious EXEC abort.
- `870c8e52d test: exercise cross-owner script activations`
  - The `script` differ generator declares 2--8 keys, generates cross-key reads/writes, and uses a
    second connection for competing writes.
  - Against the current CROSSSLOT implementation it produced `5061 ops, 3305 diffs`, proving that
    the Stage 1 gate is not vacuous.
- `tests/xscript.py`
  - The feature-local Stage 0 battery contains a zero control (WATCH on ARGV does not fire) and a
    positive control (WATCH on the declared key does fire).

Exact directed battery tails, 8 shards:

```
$ taskset -c 8-15 build/tomokv ... --port 7110 --atomic 0
  ok   WATCH ignores script ARGV on the same owner owner=7 reply=[None]
  ok   WATCH detector fires for the script's declared key owner=7 reply=None
XSCRIPT stage0 directed battery passed

$ taskset -c 8-15 build/tomokv ... --port 7110 --atomic 1
  ok   WATCH ignores script ARGV on the same owner owner=5 reply=[None]
  ok   WATCH detector fires for the script's declared key owner=5 reply=None
XSCRIPT stage0 directed battery passed
```

## Stage 1 hard blocker

The proposal's STAGE wave requires, in this order, a cut chosen on IO, then on every owner:
`atomic_promote_key`, a read at that cut, and image serialization. It explicitly relies on
promotion making a declared key carry an MVCC record so a competing plain write creates a committed
version for OCC to detect.

That primitive does not have those semantics. `FlatStore::atomic_promote_key()` is:

```
if (!atomic_key_pending(hash, key)) return false;
return atomic_collapse(floor, cleanup_cutoff);
```

It only collapses an already-existing record. For an ordinary key it allocates nothing, installs
nothing, and creates no tripwire.

The resulting counterexample is deterministic at the mechanism level:

1. IO force-admits the script group and chooses cut C.
2. Before owner B executes its STAGE task, a foreign plain SET executes on a declared key on B.
3. B has no pending record for that key, so ExLoop's existing `atomic_has_records()` gate is false;
   SET mutates the physical value directly and draws no ticket.
4. STAGE's `atomic_promote_key()` returns false. `find()` sees no pending list and returns the
   post-SET physical value even though the store has been bound to cut C.
5. There is no committed version newer than C for APPLY to validate. OCC therefore accepts a
   value that did not exist at its advertised cut. Another owner can have serialized its pre-SET
   value, so the workbench can start from a state that has no serial history.

The pinned cut cannot reconstruct a predecessor that was overwritten before the owner installed
any record. APPLY-side validation also cannot detect a write that never received an epoch.

## Required design decision

At least one binding constraint must change. The two viable shapes found in the audit are:

1. Add an owner reservation sub-wave, wait for every declared key to be armed, then choose the cut
   and issue the gather sub-wave. This preserves zero cost while off and serializability, but changes
   the proposal's one-task STAGE and its IO-time cut.
2. Arm ordinary writes globally while any script cut is live, using an Op marker/dual path so writes
   create MVCC versions before touching a declared key. This preserves the two-wave outline but adds
   machinery to the GET/SET dispatch/execution path, contradicting the proposal's structural-zero
   claim and requiring a new race proof for writes already queued when the group is admitted.

Always-on per-key mutation generations or histories would also close the race, but violate the
lane's zero-cost-when-off contract and were not considered shippable.

Because the proposal is stated to be audited and binding, choosing one of these changes would be a
material design alteration rather than an implementation detail. Stage 2 (MULTI composition) and
Stage 3 (hash-tag co-location/efficiency) are consequently shelved behind Stage 1; they are not
silently omitted.

## Resource cleanup

All target and oracle processes started by this lane were stopped by the exact PID resolved from
their listening sockets. Ports 7110--7119 were confirmed free at handoff. Nothing was pushed.
