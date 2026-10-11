## aoforder

Lane `cx-aoforder`, base `991d48f651d3c6e1324c061bd9ea801ac085afe8`.
No push. Correctness work only; no benchmark or full gate. All commands and
children are confined to CPUs 96–111, listeners to ports 25700–25799.

**F3 is reproduced and repaired.** The three required shapes fail on PRE in all
24 cells and pass on POST in all 24 cells. Fix commits: `895623bff` and
`8a715d60c`; gate integration and AOF-only compiler budgets: `00f7382ef`,
`b63f5a07b`. The exact final-binary Redis differential is still running; results
will be added before handoff. This is not a full-gate receipt.

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

| Shape | PRE live | PRE LOADAOF / restart | POST LOADAOF / restart |
|---|---|---|---|
| MSET + plain SET | `1, 1` | `9, 1` (8/8 fail) | live state (8/8 pass) |
| Crossing MSET groups | one complete group | torn pair (8/8 fail) | live state (8/8 pass) |
| MSET + SET during rewrite | `1, 1` | `9, 1` (8/8 fail) | live state (8/8 pass) |

The suggested `SET -> OK` while the commit latch is held needs one correction:
PRE already holds the AOF completion behind unposted group bytes. The test
witnesses execution with `GET = 9`, records whether the reply is ready, and
asserts `OK` after releasing the latch. This is the existing reply fence, not
a wait introduced by this patch. POST evidence is in
[regression-final](docs/aoforder/post/regression-final/summary.json) and
[crossing-final](docs/aoforder/post/crossing-final/summary.json).

Additional directed cells reproduce PRE failures for MSETNX, DEL, UNLINK and
read-dependent RENAME in both modes; all eight pass on POST. The LMPOP guard
passes in both modes on POST and fails on a deliberately naive ticket-sort
prototype; the prototype failure is retained in
[exploration](docs/aoforder/exploration).

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

A terminal failure in ordering/publishing makes subsequent flush attempts stop
before traversing moved staging entries; shutdown may legitimately call flush
again after a failed allocation.

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

**Final artifacts.** All paths below are relative to the worktree.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/aoforder/pre/tomokv` | `97b29eda0c498dc471fa4f9cb91abc8f7e9e6dff45943dbdca1bf8edffe6e1f6` |
| POST | `build/tomokv` = `build/aoforder/final/tomokv` | `b06bdee777661fa5b547eae7a105ea77f41f6a9b6b28272b445e8c71c9451107` |
| PAD-A | `build/aoforder/pad-final/tomokv` | `d6ff937a046d7e5c4288bf8993b9c20fc8d12c029b5b9f7807f728c3dddd9afc` |

The disposable crossing controls are `build/aoforder/pre-scheduled-v2/tomokv`
and `build/aoforder/post-scheduled-guard/tomokv`; their per-cell digests and
exact build commands are retained with the receipts. The production-unit target
`build/aoforder-scheduled` builds the same hook from current sources. Never use
the scheduled binaries as performance arms.

**Completed proof against the final POST digest.**

| Check | Result | Receipt |
|---|---|---|
| Required three F3 shapes | 24/24 POST; 24/24 expected PRE failures | linked above |
| Other group operations and LMPOP control | 10/10 POST | [regression summary](docs/aoforder/post/regression-final/summary.json) |
| Primary AOF/restart/fsync/truncation/torn-group/multidb/framing | 16/16 cells | [primary](docs/aoforder/persistence-primary/summary.json) |
| Aoffix2, persistfix kill/term, acknowledgement, savefix rewrite | 70/70 cells | [drivers](docs/aoforder/persistence-drivers/summary.json) |
| Rewrite stage/corruption and automatic-trigger matrices | 16/16 cells | [rewrite](docs/aoforder/persistence-rewrite/summary.json) |
| Snapshot cut/group/typed roundtrip/race and shutdown/cancellation | 26/26 cells | [snapshot](docs/aoforder/persistence-snapshot-corrected/summary.json) |
| Persistence schedules plus three clause-deletion controls | pass | [unit proofs](docs/aoforder/persistfix-proofs.json) |
| Large-frame unit schedules and Python controls | pass; 9/9 Python | [unit](docs/aoforder/persistfix-frameorder.log.gz), [Python](docs/aoforder/frame-order-test.log.gz) |
| `make all`, every production-unit target, `mdbqsbr-live-arms` | pass; all 30 targets fresh | [build](docs/aoforder/production-units.json) |
| `python3 tests/gates_test.py` | 66/66 pass; no deadline failures | [log](docs/aoforder/gates-test.log.gz) |
| Ledger fixture self-test | 9/10; only owner EXPECT count mismatch | [log](docs/aoforder/ledger.log) |
| Redis differential, seeds 7/19/20/23, both modes and atomics | exact final-binary run in progress | final receipt pending |

Primary persistence covers 1s/2s × databases 1/16 × atomic 0/1 × uring/epoll,
with appendfsync everysec, always, and no. The fsync arms crash/recover; everysec
also checks the explicitly truncated tail warning. Database-16 cells invoke
the existing multidb persistence battery, including nonzero databases. The new
F3 cells use DB 0 in each binary namespace. Auxiliary drivers retain their
purpose boots (some specifically require atomic=1); rewrite matrices internally
cover both atomic settings. The snapshot ticket oracle explicitly requires
atomic=0 and runs only on that purpose boot; atomic=1 still runs the witnessed
MSET cut and typed roundtrip. Shutdown, AOF write error, remote fragments,
manifest failure and missing-file, resurrection, large records, and the existing
EXEC/private-overlay checks are included. The reproducible invocation driver is
[persist_proof.py](docs/aoforder/persist_proof.py), with exact commands and server
arguments in the compressed receipts.

The ledger fixture has exactly 645 declared and expected labels, with no missing
or extra labels. Its one failing assertion compares those against the untouched
EXPECT_FULL=642. Row emission is at `tests/gate.sh:2929`, collection at line
3690, and the quick-tier exit at line 3742. Therefore DQ=+3 and DF=+3; the
maintainer's required counts are 628 and 645. No test assertion was changed.

Earlier incorrect driver invocations, a missing job registration, and the
custom-BUILD_ROOT production-unit attempt are explained with retained receipts
in [harness corrections](docs/aoforder/exploration/persistence-harness-corrections.md).
Those superseded failures are not represented as successful proof.

**Hot-body and layout proof.** The unmodified `tools/ccfix_audit.py` method used
under `docs/ttlclean` compares PRE with `build/aoforder/final`. Of 16,479 union
bodies, 16,384 are equal and 95 differ (including added/removed compiler helpers).
All differences originate in the two AOF objects. All **1,211/1,211 handlers**
and **1,208/1,208 hot bodies** are identical; GET/SET/MGET/MSET ordinary paths
are included. Every other object is identical. The complete inventory, including
every changed function, is [changed-functions.md](docs/aoforder/changed-functions.md);
[summary](docs/aoforder/full/summary.json) and compressed full bodies accompany it.
Five changed ordinary helper copies emitted in AOF.o are discarded by the linker;
[map excerpts](docs/aoforder/discarded-weak.json) prove that their changed copies
do not enter the final executable. The map relink is byte-identical to POST.

Both namespace layouts remain Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. AofProducer remains 144
and AofChunk 96: no new fields. [Layout receipt](docs/aoforder/layouts.json).
Only AOF compilation budgets changed to preserve the ordinary helpers as the
cold ordering code grew; no command compilation flags changed.

**Owner measurement request — no performance measurements run by this lane.**

PAD kind **(A), behaviour twin**: unmodified PRE objects plus unreachable padding
place all 544 selected linked ordinary-hot function entries at POST's exact
addresses, with POST's `.text` start and size. `.text` is 7,646,972 bytes on PRE
and 7,672,684 bytes on POST/PAD (delta +25,712). This controls ordinary-path layout;
AOF function interiors necessarily differ. PAD reproduces the single-group F3
failure in both modes, confirming PRE behavior. [Layout evidence](docs/aoforder/pad-layout.json)
and [reproducible builder](docs/aoforder/build_pad.py). No PAD-B is claimed.

Run the gate's ABBA instrument on the 16 explicit cells in
[measure-cells.txt](docs/aoforder/measure-cells.txt): both modes; GET/SET at depth
1 and 32; eight-key MGET/MSET at depth 1 and 8; 512 connections; atomic=1,
read-local=0, reorder=0, appendonly=no. Preserve the instrument's population,
value sizes, measured load floors, null controls and rejection rules. Use only
server CPUs 96–103, load CPUs 105–111, ports 25760–25779, no SMT siblings; split
is 6:2 and fused is eight workers. Compare PRE/POST and PRE/PAD-A, then POST/PAD-A
for any moved cell. Report rate at matched offered load, latency for depth 1,
and cycles/op, instructions/op, IPC for every arm. A repeatable ordinary-command
regression outside the instrument's identical-arm envelope rejects this build.
No instruction-count-only verdict and no performance gain is claimed here.

For AOF cost, repeat the SET and MSET cells with appendonly=yes under everysec
and always, fresh persistence directories per arm, and the same offered load.
These are cost measurements of the correctness repair, not evidence for relaxing
its replay assertions. Keep rewrite disabled in those rate cells; the directed
rewrite correctness cells above supply the cut/replay proof. Record completed
commands and the persistence completion counters alongside performance numbers.
Append owner results as MEASURE-RESULT; this lane performs no load measurement.

