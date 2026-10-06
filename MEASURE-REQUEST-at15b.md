# AT15b — repair the AT15 landing failures

Lane `cx-at15`, 2026-10-06. Merged `origin/cpp` at `7213a9405` before editing;
merge commit `61a9ab20f`. The source/Makefile at that point matches the supplied
AT15 baseline `bf0b65b38`; the merge adds mainline benchmark/harness work.
All builds and serverless work use CPUs 112–127. The explicitly requested
differential harness uses target 112–119 (16 shards, 6 IO + 2 EX), Redis on 120,
and clients on 121–127. No benchmark, full gate, or push was performed.

## Failures, fixes, proofs

| Landing failure | Cause | Repair | Proof |
| --- | --- | --- | --- |
| `differ multi`, atomic=0, seeds 7/19/20 | Queued INFO exposed the missing Redis 7.4 `subexpiry` field | Append the exact field and aggregate its actual hash count in ordinary and EXEC censuses | Split replay: all three named seeds pass, zero differences and zero clock tolerances; complete harness receipts below |
| `differ multidb`, same seeds | Same missing field, including INFO around a private SWAPDB mapping | Carry the count through physical-DB aggregation and the command-position map | Split replay: all three named seeds pass, zero differences and zero clock tolerances; nonzero MOVE/SWAPDB serverless witness passes |
| `DEBUG toggle/reload battery` | `tests/debug.py` required the retired unsupported-command EXEC element | Require `+OK` for MULTI, `+QUEUED` for DEBUG SLEEP `.01`, and exactly the array `[b'OK']` for EXEC | Python syntax check; real production serverless DEBUG SLEEP 0/positive witnesses pass, including an observed retry and full deadline. The DEBUG battery is **live**, so its whole body remains for the maintainer |
| `atomic survivor: rename_overlay` | Driver explicitly initializes owner references, then AT15's moved initializer initializes them again at dispatch | Production `multi_dispatch_started` initializes only unprepared references and rejects a second publication. The initializer's double-initialization assertion remains | PRE SIGABRT backtrace at `initialize_multi_owner_record_refs`; unchanged survivor driver passes POST |
| `atomic survivor: watch_parent` | Same double initialization | Same production repair | PRE SIGABRT backtrace; unchanged survivor driver passes POST |
| `multidb serverless owners` | Same double initialization in `transaction`, called by `owners`; buffered L4 output obscured the failing phase | Same production repair; update only two INFO string expectations for the new field | PRE SIGABRT backtrace; POST `multidb-unit` and `mdbqsbr_checks.py` both pass |

The aborts were caused by the owner-reference initialization move, **not** the
generated `no_multi` metadata or the dispatch `NoMulti` bit. Those admission
semantics remain intact. No survivor, multidb, or execfix driver was changed.
The existing execfix helper has the same explicit initialization pattern and is
covered by the production guard; no separate execfix binary target exists here.
Normal production dispatch still prepares references on its final publication
path, after backpressure checks and before the first owner task is posted.

Backtraces and complete serverless logs are under [docs/at15b](docs/at15b).
`pre-multidb-gdb.log` identifies `transaction` / `owners` after the L4 lines.
The three requested backtraces came from `taskset -c 112-127 gdb -batch -ex run
-ex bt --args ...`, before any production edit.

## Exact subexpiry source and storesize overlap

`DatabaseStats::subexpiry` counts **hash keys carrying at least one field TTL**,
not fields. For each owner-visible hash object, `hash_ttl_slot(object)` exposes
the existing `HashVal::ttls` table; a nonnull, nonempty `HashFieldTtl` adds one.
Embedded hashes have no slot and add zero. Ordinary `multidb_stats` checks the
physical objects it already visits. `multi_database_stats` checks the image
resolved at the transaction cut and connection overlay, including side-only
inserts and preceding TTL/persist/delete operations. Aggregation preserves the
physical namespace until INFO translates it to the appropriate logical DB.

The approximate `FlatStore::field_expire_count()` gate is deliberately not the
source: its attention index can retain deleted/persisted/replaced keys and a
sticky allocation-failure bit, and it is shard-wide rather than per database.
The count adds O(1) work per object to an existing owner census. This branch
still obtains both keys and expires through that census, so no new batch
publication mechanism or unsynchronized observer walk is needed.

Read coordination reference:
`/home/user/Projects/cx-storesize/MEASURE-REQUEST-storesize2.md`, the published
monitoring table and its discussion. **Land AT15b first; storesize3 should merge
it.** The overlap is the INFO formatter, `DatabaseStats`, ordinary count source,
and aggregation. Storesize3's owner-free INFO route must populate this field
from an exact per-physical-DB count published with its other monitoring data;
it must not silently leave the new member zero or read the attention-index gate.
Keep the EXEC census's transaction-visible count and private-SWAPDB mapping.

The eight locked structures retain their sizes; compilation includes their
existing assertions. The cold `DatabaseStats` row grows 24 → 32 bytes, and its
256-row scratch table grows 6,144 → 8,192 bytes. No per-owner migration state,
ordinary operation branch, retry/seqlock, or overwrite policy is added.

## Battery policy search and serverless verification

`grep` searches covered all Python/C++/include/shell batteries, including multiline
contexts selected by MULTI/EXEC and INFO/DEBUG/CONFIG. Receipts:
`admin-battery-search.log` and `multi-policy-search.log`.

- **Changed:** `tests/debug.py`, the sole old INFO/DEBUG/CONFIG refusal assertion.
- **Changed format expectations:** `tests/at15_unit.cc` and the two keyspace
  literals in `tests/multidb_unit.cc`; both still require exact Redis bytes.
- **Retained:** `tests/at15.py`'s unsupported INFO frame is a deliberately broken
  parser control, not an expected server reply. Its subscription refusal,
  `tests/at15_unit.cc`'s SAVE/subscription controls, `tests/execabort_watch_unit.cc`
  (SAVE), `tests/pubsub.py`, and `tests/flip.py` concern policies unchanged here.
  `tests/xscript.py` covers its separate script admission restriction.
- No other INFO/DEBUG/CONFIG MULTI-refusal expectations were found.

`docs/at15b/prove.py` reproduces 40 serverless invocations:

| Check | POST |
| --- | --- |
| All 16 named atomic-survivor gate cases, plus `plain_0` / `plain_1` | 18 pass |
| `multidb-unit` | Pass through owner phases, WATCH, namespace/map snapshot and AOF replay |
| `tests/mdbqsbr_checks.py build/mdbqsbr-unit` | All 20 positive/fault/deadline schedules accepted with their required witnesses |
| AT15 db0/namespaced × 1s/2s × atomic 0/1 × RESP2/3 | All 16 arms pass |
| Existing EXECABORT/WATCH row body | Both images/modes and no-watch/no-error controls pass; both no-arm controls fail with the required diagnostic |
| AT15 wire validator / shell-row unit | Five bad reply controls rejected; four shell-row tests pass |

The new `subexpiry` case remains in the existing AT15 row. It checks multiple
expiring fields on one hash, two hashes, partial/last HPERSIST, HDEL, rearming,
RENAME, MOVE, private SWAPDB, string replacement, and deletion. Ordinary and EXEC
INFO bytes are checked separately. Absolute future field deadlines avoid the
admission-only driver's unstamped dispatch clock; the namespace witness requires
the real SWAPDB boundary to arm before its serverless drain completion.

`docs/at15b/count_controls.py` builds two throwaway binaries, each deleting just
one census count increment. The transaction-zero control fails at the exact
private-transition reply, and the ordinary-zero control fails at ordinary INFO.
Both exit 1 with their specific witnesses. Neither control is a measurement arm.

## Live differential receipts

The unmodified `tests/differ_gate.sh` has no suite-only selector. It replays the
landing run's frozen inventory (seeds 7/19/20/23/21/22) and all discovered suites.
The requested multi/multidb rows are reported separately from unrelated suites.
Split completed: **249/252 suite legs pass**. All twelve multi/multidb legs pass
with zero differences and zero clock tolerances. The shell reports `fail=4`:
three failed suite legs plus its strict final fold rejecting that failed matrix.
Runtime 9m19s; both owned listeners stopped cleanly. Fused and the frozen PRE
control are pending; final totals will be appended here.

The first split seed also reported HPTTL/PTTL differences of 2 ms in `hexpire`
and `edgetime`, and one `wiredump` difference; these are preserved as failures,
not attributed to this repair or excused by wider tolerances. No whole-matrix
green claim is made. The original gate and DEBUG live battery remain maintainer
work regardless of the directed results.

## Byte audit and frozen arms

The unmodified `tools/lbstall_artifacts.py compare` was run separately on both
production object trees, against the frozen merged AT15 baseline:

| Image | Selected bodies | Raw identical | Identical with resolved relocation targets |
| --- | ---: | ---: | ---: |
| Namespaced | 742 | 742 | 742 |
| db0 | 741 | 741 | 741 |

GET/SET and parse/dispatch are raw-identical. `xshard_plain_prepare`, including
its cold clones, is also unchanged. `changed-bodies.json` inventories all 41
changed/added bodies in the eight modified production objects; it includes
incidental compiler changes to other emitted helpers, and does **not** claim
they are all semantically part of MULTI/INFO. The selected hot-body identity is
not a substitute for a rate regression check.

| Arm | Path | SHA-256 |
| --- | --- | --- |
| PRE, merged AT15 source | `build/at15b-pre/tomokv` | `ef4ff8935edf5d222b70299615e5f99a041e41f370594fc88e2cc691ecaad49a` |
| POST | `build/at15b-post` | `d3723e11796bbcd87b0156d4b1690a3008f7702bc27b6c42724c0b3ff7ee1487` |
| PAD-A | `build/at15b-pad-a` | `926e0e9c5f0405951746cc1c6d808de5a334fd3a5c0cc5ff87c0bfcde7d1da52` |

PAD is **kind A: behaviour twin**, PRE behavior with POST's aggregate `.text`
size. It links the unchanged PRE objects with 256 unreachable NOP bytes:
PRE `.text` 7,794,684; POST/PAD-A 7,794,940. It does not reproduce per-function
POST placement or the cold statistics-table layout. Thus it controls aggregate
text growth only. No inverse control is needed for this 256-byte delta.
Builder, full link receipt and SHA256SUMS are in `docs/at15b`.

For the maintainer's quiet-box regression check, use the gate ABBA instrument,
PRE/POST and PRE/PAD-A, at matched offered load and with a same-binary null.
Cells from `tests/wbland_merit_cells.txt`:
`h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,x9_32_l1,x9_32_l0`.
Retain each cell's geometry, pipeline, connections and read-local settings.
Report rate, cycles/op, instructions/op and IPC; zero rate/tail regression
outside the contemporaneous null is the acceptance criterion. This is a
correctness repair with no measured performance-gain claim.

## Gate accounting

No row was added or removed by AT15b. The original AT15 row remains at
`tests/gate.sh:1587`, collected at line 3155, before the quick exit at line 3285:
still **+1 quick / +1 full** relative to pre-AT15. Maintainer-owned constants
already read **498 / 515**, so no further count change is required. No EXPECT,
row-label fixture, or gate script was edited. Finish with the live DEBUG purpose
boot and `tests/gate.sh iteration` on mainline; do not infer a full gate result
from these directed proofs.
