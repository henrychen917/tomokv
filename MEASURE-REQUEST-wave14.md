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
