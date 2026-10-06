# storesize5 — landed at15 composition and DBSIZE differential contract

Work in progress: implementation committed; live receipts and arm audit pending.
Worktree `/home/user/Projects/cx-storesize`, branch `cx-storesize`.
Started from `c55d4a370`, merged `origin/cpp` = `9d957b9fb` (landed at15)
in `600063010`. The two-mode differential repair is `647f277c7`.
No push. All builds and verification use CPUs 112–127.

## Merge and production behavior

| File | Resolution |
| --- | --- |
| `Makefile` | Keep `storesize.cc` and `multi_admin.cc`, both sets of unit recipes, and storesize4's storage-regression link input. |
| `src/cmd/t_server.cc` | Keep one census formatter and the published db0/multidb formatters; all emit one `subexpiry` member. Ordinary INFO with keyspace uses published counters unless the published field-TTL attention flag requests an exact census. |
| `src/cmd/multidb.cc` | Keep at15's single `slot && *slot && !(*slot)->empty()` increment using `hash_ttl_slot()`. No duplicate count. |
| `tests/gate.sh` | Keep both unit lists and rows; preserve origin/cpp's EXPECT assignments verbatim. |
| `tests/fixtures/nullrefresh-ledger-labels.json` | Resolve to origin/cpp verbatim; no fixture regeneration. Maintainer must carry forward the existing storesize label. |
| `MEASURE-REQUEST` | Retain both lane notes. |

Keeping the INFO formatters alone is insufficient: MULTI classification and
scatter preparation both call the ordinary route selector. The selector now
accepts an explicit execution-boundary context, passed by MULTI classification
and forced-atomic child preparation. INFO containing keyspace at EXEC always
uses at15's exact transaction-visible census, including its private SWAPDB map.
Its ordinary and transaction censuses both read `hash_ttl_slot()` and count
hash keys with at least one TTL, not fields. at15's `multi_admin.cc` and its
admission/owner-reference initialization are unchanged from origin/cpp.
`merge-source-audit.json` records that the sole `multi.inc` difference is the
route-selector argument; all admission/initialization code is byte-identical
source. Locked layouts remain enforced by the normal build assertions.

Plain DBSIZE remains published; DBSIZE NOW remains exact. Field-TTL attention
is only a routing hint, never the `subexpiry` count. Ordinary INFO with possible
field TTLs retains the documented O(resident keys) exception. The owner batch
publishes its shard counts in `src/core/ex_loop.h:2289` in this merged tree.
No per-operation publication, reader retry, seqlock, or ownership change.

## Differential contract and falsification

`gen_edgetime` already excludes DBSIZE and INFO because they are batch-published
(`tests/differ.py:1192`, formerly the cited line 1056). `gen_multidb` now emits
DBSIZE NOW at every former plain-DBSIZE position, including its final per-DB
checks. The target receives NOW; the oracle receives plain DBSIZE in the same
pipeline position. Both replies must be nonnegative RESP integers and equal
exactly, with no TTL tolerance. Every remaining generated operation and every
512-command chunk boundary is preserved; the generator audit covers all six
seeds. This merged generator uses 512-command chunks, not 64.

| Seed | Exact positions |
| --- | ---: |
| 7 | 290 |
| 19 | 290 |
| 20 | 291 |
| 23 | 321 |
| 21 | 287 |
| 22 | 321 |

Total: 1,800 per geometry/atomic matrix, 7,200 for all four parts.
After the original terminal cleanup, one SET leaves a known nonzero witness.
After the final stream reply, NOW and Redis DBSIZE must both report exactly 1.
Plain target DBSIZE is then polled every 1 ms, with a 100 ms monotonic deadline
and socket timeout bounded by the remaining time. Its observed count must
converge to NOW; a publisher stuck at zero cannot pass on an empty final DB.
The log records checked positions, poll count, elapsed milliseconds and counts.

The generator search found no other plain DBSIZE or ordinary INFO-keyspace
byte comparisons. `multi` and `multidb` INFO-in-EXEC remain byte-exact; infofix
telemetry is already property-checked. The existing differential self-test now
rejects a wrong exact count independently of stalled publication, plus equal
noninteger count replies. Nine serverless controls pass without any comparison
relaxation. No gate row was added by this round.

## Evidence still to collect

- Complete split and armed-fused differential folds, both atomic modes and all
  frozen landing seeds, including historical MULTI repeats and mode equivalence.
- All 40 landed AT15b proof invocations; existing storesize and multidb checks.
- Twelve storage rows and the published-monitoring row through GATE_ONLY_JOBS.
- Rebuilt origin/cpp PRE, POST and PAD-A SHA-256; both-image hot-body audit.

The replay runner invokes the unchanged `docs/at15b/replay.sh` for atomic-zero
parts and `tests/differ_gate.sh` for atomic-one/equivalence parts. All use target
112–119, Redis oracle 120 and clients 121–127, 16 shards, split ratio 6:2 or
fused/read-local=1. It folds actual subprocess completion and every comparison
artifact with the gate's unchanged strict `fold()` function. These serial lane
receipts do not apply the parallel full gate's elapsed-time budget.

## Counts and measurement handoff

The existing `storesize published monitoring` row remains before the quick-tier
exit. This round adds zero rows; the lane's existing contribution is +1 quick /
+1 full relative to origin/cpp. Origin EXPECT remains 499/516; the combined tree
requires maintainer-owned 500/517 and the existing storesize fixture label.

PAD-A is kind A, a behavior twin: PRE monitoring routes at POST text size and
symbol layout, built by the unchanged storesize3 builder. It keeps POST's
producer accounting and field-TTL attention; it isolates monitoring routing,
not the full feature's producer cost. No inverse-control arm is requested.

No performance measurements are run by this lane. The previously accepted
storesize measurements remain the owner-supplied acceptance context. If the
new merged hashes need another quiet-box check, use PRE/POST/PAD-A and a
same-binary null with the exact 14 cells in `tests/wbland_merit_cells.txt`:
h05,h06,p8g,p8s,d1g_l0,d1s_l0,m8g_l0,v1g_l0,d128g_l0,d32g_l1,d8s_l1,d32s_l1,
x9_32_l1,x9_32_l0. Keep the instrument's matched offered loads and geometry;
rate/tails and cycles/op decide, with instructions/op and IPC explaining them.
No regression outside the contemporaneous null is acceptable. For monitoring
interference, use storesize3's 40M-key, 1 Hz INFO shape, including its separate
field-TTL census case. Append measurements to MEASURE-RESULT.

The session's higher-priority search instruction requires rg; the grep-only
request could not be followed and was disclosed before searching.
