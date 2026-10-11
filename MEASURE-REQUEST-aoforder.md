## aoforder

Lane `cx-aoforder`, base `991d48f651d3c6e1324c061bd9ea801ac085afe8`.
No push. Correctness work only; no benchmark or full gate. All commands and
children are confined to CPUs 96–111, listeners to ports 25700–25799.

**Work in progress:** F3 is confirmed on PRE, and the fix is committed as
`895623bff`; test integration and AOF-only compiler budgets are `00f7382ef`.
The final proof results and exact changed-function inventory will be added here.
This draft is not a green gate receipt.

The read-only design source is
`/home/user/Projects/round4-read/design-txnorder.md`, section 7 F3 and decision D9.
The reviewed line numbers have moved in this base. Verified anchors:

- `begin_plain_version`, `src/cmd/atomics_glue.inc:34`: a foreign undecided
  candidate is skipped by logical lookup, then a plain clone draws its own ticket.
- `atomic_resolve_internal`, `src/store/flatstore_atomic.inc:1071`: committed
  candidates compete by maximum epoch, not physical install order. Its same-
  connection repair remains unchanged; dispatch already parks own predecessors.
- `xshard_aof_emit`, `src/cmd/scatter_engine.inc:2202`: group post-images enter
  their shard producer before completion allocates the group's ticket.
- PRE `AofProducer::resolve_groups`, `src/persist/aof.cc:673`: staged records
  drain in install order, with no comparison to the eventual group ticket.

PRE receipts are in [pre/matrix/summary.json](docs/aoforder/pre/matrix/summary.json).
All 24 cells witnessed the intended window and then failed on replay divergence:
three shapes × both thread modes × everysec/always × databases 1/16. Each cell
records DEBUG LOADAOF and a distinct-process restart, along with the native AOF,
process arguments, binary digest and console output. The single-group and rewrite
cells run the pristine PRE binary. The crossing-group cells use a disposable PRE
scheduler copy: group 1 installs on owner A first, group 2 on owner B first, then
both delayed fragments are released before commit. The hook only parks fragments;
production contains no scheduler hook. Every missed window fails, without skips.

| Shape | PRE live | PRE LOADAOF and restart |
|---|---|---|
| MSET + plain SET | `1, 1` | `9, 1` |
| Crossing MSET groups | one complete group | one key from each group |
| MSET + SET during rewrite | `1, 1` | `9, 1` |

The rewrite fixture observes `before-manifest` after the cut, installs the held
MSET and the plain write, then releases the writer before releasing the group.
The hook parks the writer thread; releasing the group first can make the DEBUG
reply wait for that same writer. Earlier fixture timeouts are retained under
`build/aoforder/pre-matrix-final`; the corrected eight-cell rewrite receipts are
in the committed matrix. No assertion or timeout was loosened.

The fix sorts each shard's retained staging window by mutation ticket once all
its AOF decisions exist. Plain records retain their actual MVCC ticket (or the
current frontier for unversioned keys) in owner-private chunk metadata. A chunk
is sealed at a ticket boundary, and large-record continuations retain that ticket.
Metadata is cleared before the existing transport ordinal is assigned. Group
fragments still use the existing group records and GCMT, with unchanged framing,
checksums, sequence validation, manifest, rewrite cut and recovery code.

A remote decision can publish between a plain handler and AOF serialization.
The plain ticket must be paired with its physical plain image, not a later group
winner returned by logical lookup. A rejected command that made no plain install
must not serialize a group's private physical image as an ungrouped write.

There is a second ticket distinction: LMPOP and local-script AOF groups can wrap
an already-visible plain mutation; their later GCMT ticket is an identity.
Those records retain their mutation rank. EXEC's explicitly selected private
view remains resolved logically, including aborted children. A directed LMPOP
control catches the naive alternative of sorting every AOF group by its GCMT id.

No dispatch, read, ownership, clone, cleanup or commit-allocation path changed.
The existing `ExLoopT::aof_flush_pass` completion fence already requires every
producer to have no pending bytes. Retaining the staging window therefore adds
no command wait rule. It allocates only while AOF is enabled; AOF-off paths and
all locked data layouts are unchanged.

**Baseline format discrepancy:** the current AOF is native `TOMOAOF` version 1,
not Redis RESP AOF. Redis 7.4.10's `redis-check-aof` rejects the captured PRE file
at byte 0; [receipt](docs/aoforder/pre/redis-check-aof.log). The ordering repair
preserves the native format exactly and cannot make that pre-existing Redis-tool
compatibility claim true. Converting to Redis AOF is a separate owner decision.
A clarification was requested; pending a correction, this lane follows the
explicit instruction to preserve the existing format. No format migration was
implemented.

**Gate accounting:** three new emitted rows, `AOF commit order single`,
`AOF commit order crossing`, and `AOF commit order rewrite`. The single row also
covers MSETNX, DEL, UNLINK, RENAME and the LMPOP guard in both modes. All three
are collected before the quick-tier exit: DQ **+3**, DF **+3**. The maintainer
must change EXPECT_QUICK **625 → 628** and EXPECT_FULL **642 → 645**. Both
constants remain untouched in this lane.

**Proof status:** final build, persistence, differential, Python gate tests and
full byte inventories are in progress. Earlier exploratory logs remain under
`build/aoforder`; they are not represented as final proof. The final table will
name the exact binary and every failure.
