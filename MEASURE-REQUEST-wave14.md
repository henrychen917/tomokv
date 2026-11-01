# Wave 14 integration and measurement request

## wave14 integration

Work in progress on `cx-wave14`, based on `105c5818cc`. No push. All six
lane reports were read before integration. Merge order: witnessfix, rootcore,
blockfix4, rootcompat, clientcompat, execfifo3. The maintainer's two merit
addenda authorize every merge. Lane branches are read-only inputs.

Builds and correctness work use CPUs 0–31, builds at most `-j32`, ports
20000–20099, and `LC_ALL=C` on every boot. Only selected correctness jobs,
oracles, differential suites, and finite serverless instruction scopes run
here. Performance/load generators and the full iteration remain maintainer work.

The supplied headline path omits one hash character. The existing frozen image
is `/home/user/Projects/bench-bins/tomokv-headline-105c5818cc`.

Expected lane-only DQ=DF=43: witnessfix 2, rootcore 7, blockfix4 5,
rootcompat 9, clientcompat 5, execfifo3 15. This predicts 1089 quick / 1106
full against 1046/1063. Exact declarations, collector placement, and any
integration additions will be reconciled before delivery. EXPECT constants
remain untouched.

MISCONF recovery and the WAITAOF non-mutation receipt are known differences,
as required by the integration brief. Their directed checks will retain
arming and exact observed behavior instead of unconditionally failing or
accepting arbitrary errors. Other lane residuals remain explicit exclusions.

Validation, semantic interactions, compile trials, command-scope counts,
arm hashes, and maintainer measurement recipes are pending. No completed
proof or throughput claim is made by this initial record.

### FUNCTION rewrite interaction (confirmed and fixed)

The forced capture witness on the unmodified merge acknowledged library version 2,
then replayed version 1 after restart. It pauses immediately after the registry
image copy, replaces the library on another IO, and requires the window to open.
The old order copied libraries before `rewrite_mark()` drained the old increment;
the journaled replacement was therefore deleted with that increment. Library
capture now follows increment rotation while all shard owners remain frozen.
Every later mutation is journaled in the retained increment. Earlier duplicate
full-registry postimages replay in their original order. The scheduling wrapper
is linked only into the witness twin; the release binary contains no hook.
The negative receipt is `docs/wave14/jobs/function-capture-before.json`.

### Wake publication audit: release condition still fails

The directed single-observer test (`tests/wave14_order.py`, partial gate job
`wave14_order`) compares EVAL, EVALSHA and EXEC with a registered BLPOP waiter,
keyevents, invalidations, and slowlog. It verifies same-shard, same-owner and
cross-owner placement. The merged reply is correct (the script sees its item
before BLPOP consumes it), but the requested Redis publication order is **not
satisfied**. Invalidations are batched before events; same-shard Lua captures
wake events under the producer's notification context; deferred EXEC/staged
wakes omit pop events; slowlog may record BLPOP before the producer.

Controls used the frozen headline and the separate blockfix4/rootcompat POSTs,
with ordinary read enrolment because the headline lacks EXEC enrolment. They
reproduce these publication/slowlog differences before integration. The merged
sequence is the composition of those lane behaviours, not an additional merge
regression. This is the pre-existing D11 publication/retirement problem; it is
not promoted, tolerated as a Redis pass, or silently hidden in a new green row.
The red directed receipts are retained under `docs/wave14/jobs/order-*`.

### Initial command census and budget criterion

The rebuilt PRE matches all 718 headline hot bodies and all 88 headline command
bodies; its only two linked-body differences are the cold INFO git identity
strings from the archive build. All 216 PRE scopes completed. The first merged
census exposed +35 instructions per DB0 GET and +10 per DB0 INCR, attributable
to `FlatStore::find` outlining `Slice::key_eq`. That body happens to match the
older execfifo3 binary but regresses the newer headline. Budget selection
therefore prioritizes headline identity for hot bodies unchanged by every lane;
matching an older lane's incidental compiler output is not sufficient. Initial
and rejected counts are retained, not presented as the integration cost proof.

### Other semantic interactions

- `post_client` and `post_client_transfer` both publish the queue entry, execute
  the rootcore sequentially consistent fence, then set the notification mask.
  flipfix6's transfer still moves session ownership through the same queue. The
  fence does not replace its S2 or pinned-close refusal. The inbox fixture covers
  client, transfer, task, fused and FLUSH producers.
- Published, FIFO-placed EXEC is distinct from prepared/unpublished S2. A new
  core fixture stops actual fragments between placement and the execution
  barrier: it must hold IO/executor drain without taking an S2 refusal, then
  complete exactly once after FLIP rollback. The existing wave13 FLUSH/S2/close
  assertions and FIFO blocking/whole-shard FLUSH checks remain present.
- A keyless tracking overflow cancels outstanding read tokens and clears the
  cache; EXEC retirement respects the cancellation. The cap row now also
  enrols through EXEC, in every existing scan geometry. It retains fresh-state,
  bounded window arming and exact full-cache coverage; no tolerance is widened.
- New error sites were audited against crlffix. The new direct `reply_err` sites
  use static ACL/SORT, OOM, subscription and deleted-stream messages. XREADGROUP
  still uses the central NOGROUP builder; no new user-controlled error text
  bypasses the central CR/LF handling.
- The maxmemrace Redis oracle assumed `maxmemory 1` immediately implies OOM.
  Redis's eviction time slice may instead return `EVICT_RUNNING`, admitting a
  write before a later eviction attempt reports failure. Oracle setup now waits
  at most five seconds for the actual OOM, accepting only interim `+OK` and
  recording its count. All 48 TomoKV legs are unchanged.

### Tcl reconciliation and negative control

All 22 touched named assertions were attempted three times in each mode
(132 isolated attempts). `docs/wave14/tcl-audit.md` lists every result and the
exact reason for retaining a skip. Existing lane promotions all passed six
attempts. No guard-only promotion is restored merely because six attempts
happened to pass. Intermittent and consistently failing assertions remain named
skips. Original run receipts, including failures, are preserved.

The normal Tcl gate job rejects a throwaway binary that discards CLIENT's
subcommand name. Both modes fail the unchanged upstream `CLIENT LIST with IDs`
assertion: actual `cmd=client`, required `cmd=client|list`. This is an assertion
failure, not a timeout or missing window. See `tcl-planted-witness.json` and
`tcl-regression-build.json`. The first invocation was rejected by the gate's
16-physical-core resource preflight and booted nothing; the valid invocation
uses 16 of the authorized cores.
