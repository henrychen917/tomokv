# Additional live-state counterexample: hash-field expiry under an undecided group

This is **not fixed** by the F3 candidate. It prevents the broader blanket guarantee in the task from being claimed. The final probe asserts the correct live group result and fails on all six cells; these are expected defect witnesses, not successful conformance tests.

| Arm | Mode | AOF | Live after MSET commits | LOADAOF / restart |
|---|---|---|---|---|
| PRE | 1s, 2s | always | `[null, "1"]` | `[null, "1"]` |
| POST | 1s, 2s | always | `[null, "1"]` | `["1", "1"]` |
| PRE | 1s, 2s | off | `[null, "1"]` | not applicable |

All cells use 16 shards, server CPUs 96–103, client CPUs 105–107, port 25740, atomic=1, databases=16; split is 6:2. AOF-off PRE cells establish that the live tear precedes and does not depend on this persistence change.

Reproduction (`probe.py`; exact argv and digests are in the receipts):

1. Choose `a` and `b` on different owners. Choose a second hash `h` on a's shard to keep that shard's field-expiry gate armed.
2. Disable active expiry. Set `a[f]=old` with a field deadline one second ahead; give `h[f]` a longer deadline.
3. Hold atomic commits and send `MSET a 1 b 1` from another connection. Require two installed entries and witness `HGET a f = old` before its field deadline.
4. After that deadline, `HGET a f` returns null. Release the commit latch and require MSET's OK reply.
5. Observe `MGET a b = [null, "1"]`: the implicit expiry erased a live group's candidate. Compare LOADAOF and distinct-process restart, then assert the correct `["1", "1"]` live result. The assertion must fail.

Source evidence, unchanged since PRE:

- `src/cmd/t_hash.cc:1467` classifies HGET as Readonly. `hash_lookup` at line 811 resolves the read and calls `hash_ttl_on_access` when the shard has any tracked field expiry.
- `src/cmd/atomics_glue.inc:1015` gives a read context to operations without Write/SnapshotWrite, so HGET does not install a plain MVCC clone.
- `src/store/flatstore_atomic.inc:1112` skips the foreign undecided group and returns the parked predecessor.
- `src/cmd/t_hash_ttl.cc:431` reaps fields in that predecessor in place; when the last field disappears, lines 439–441 emit an unversioned AOF delete and erase by key.
- `src/store/flatstore.h:2686` erases the current physical object at that key, which is the MSET candidate, not the predecessor hash being read. The later group ticket therefore resolves a missing physical value. This violates the immutable-read and untorn-group laws.

The F3 sorter ranks this unticketed expiry delete below the later group and replays the intact serialized group. That exposes a live/replay mismatch even though all directed F3 plain-write/group regressions pass. Restoring staging order for this case could reproduce the torn live pair; it would not repair the live-state law and is not an acceptable substitute.

Owner options:

1. Repair hash-field reads so they filter expired fields without modifying parked versions, with physical expiry left to safe owner maintenance. This needs hash read/expiry changes beyond this task's AOF/group-resolution-only body constraint. Re-run these cells and the F3 proof afterward.
2. Assign that repair to a separate lane and retain this F3 branch for integration after it. No merge/push is performed here.
3. Defer this candidate and keep the PRE reproductions until the owner selects the broader algorithm/scope.

No reader retry, seqlock, plain-command wait, or format change is proposed. Production changes stop at the committed F3 repair; this additional finding is a reproduction and report only.
