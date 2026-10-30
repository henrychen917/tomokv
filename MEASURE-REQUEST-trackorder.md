# CLIENT TRACKING flush reply order

## trackorder

Lane `cx-trackorder`, based on `e32b04a445b056976abb308aa598e356fcbaae74`.
No push. No performance benchmark, load generator or full gate iteration.
All lane commands and children use CPUs 0–15; correctness server geometry is
CPUs 0–7, 16 shards, split 6:2 or eight fused threads. Listeners use
20100–20199 and every boot inherits `LC_ALL=C`.

### Oracle and change

The Redis 7.4.10 oracle distinguishes **SYNC/default** from **ASYNC**:
on a directly tracked RESP3 flushing connection, SYNC/default sends the null
invalidation before `+OK`; ASYNC sends `+OK` first. With an ECHO on each side,
the frames are respectively `before, invalidate(null), OK, after` and
`before, OK, invalidate(null), after`. BCAST, default, OPTIN/OPTOUT (both
remembering and nonremembering reads), and NOLOOP preserve that distinction.

The complete oracle/candidate streams are recorded as hexadecimal RESP frames,
per connection. A RESP2 REDIRECT receiver gets a `message` on
`__redis__:invalidate` with a null bulk; RESP3 direct/REDIRECT receivers get a
two-element `invalidate` push with RESP3 null. Other tracked clients receive
one null invalidation, even with no remembered key or NOLOOP. Separate TCP
streams have no total byte order; receipts do not invent one by ordering reads
in the harness. PING fences check each recipient's subsequent stream.

Production implementation lives in `src/cmd/tracking.cc`; `src/net/wb.h` adds
only a const accessor for its existing retirement pointer. A flush raised
during its recipient's own retirement can append at the established boundary
before reply assembly. The ROB publishes its cursor once per drain, so the
cold helper skips already-Free slots to find the actual retiring Op. SYNC and
default use this boundary; ASYNC, other recipients, and suppressed replies
retain ordinary OOB deferral. Suppressed replies have no `+OK` to precede, and
their push must remain outside reply segments that suppression discards.

There is no added per-thread, connection, shard or Op state, no allocation,
retry, seqlock, owner hand-off or layout change. Non-flush invalidations do not
call the helper. With tracking OFF this code is unreachable.

Porting to flushfix2/flushfix3: retain the existing completion-side call to
`climon_flush_completed` after **all** shard effects finish and before final
reply assembly, while the originating Op remains Done in its ROB. The fix
depends on that boundary, not the scatter kind or the implementation of
clearing stores. If an atomic FLUSH moves to another retirement branch, move
that same cold hook with it. Do not emit at dispatch or before owner completion.

### Frozen arms

| Arm | File | SHA-256 |
|---|---|---|
| PRE (`e32b04a44`) | `build/tomokv-PRE` | `414d439e4cb6c86bb963a08747b82b1f314566ce6107bdaa718a40e3d9389b46` |
| POST | `build/tomokv-POST` | `8a8a8e98796570592b1e05ceb0bea98ceac8b9afbc1b4248092839bfdc1d5193` |
| PAD-A | `build/tomokv-PAD-A` | `380a1d0368acca59a636f6c9dd732881503276ab053ad1bc321e365c65d317fd` |

**PAD type A — behaviour twin:** POST with each namespace's cold
`tracking_flush_before_reply` entry forced to return false. This restores
PRE's deferral while retaining POST's exact text size, every section and
symbol address, and all other file bytes. Only two bytes differ in the
compiled binaries. Construction/verification: `tools/trackorder_pad.py` and
`docs/trackorder/pad.json`. Text sizes: PRE 8,729,431; POST/PAD-A 8,733,271.

Oracle: `/home/user/Projects/redis/src/redis-server`, SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.

### Tracking OFF instruction proof

`tools/trackorder_counts.py` reuses the production command-scope fixture and
finite single-step tracer. All **80 paired cells have zero added instructions
and identical per-function counts**: GET/SET/INCR/MGET/MSET × batches 1/32 ×
1s/2s × atomic 0/1 × both database namespaces. Counts include executed NOPs in
the named TomoKV functions and exclude library callees/fixture glue. These are
serverless command scopes, not whole-operation or throughput measurements.

`docs/trackorder/counts/comparison.csv` contains every PRE/POST count; individual
JSON receipts retain the function attribution. The rebuilt headline used for
linking the probe has **byte-identical .text and .data** to delivered PRE;
the only .rodata differences are the two INFO git-SHA strings (14 bytes).
`headline-rebuild.json` records that check. The object comparison additionally
finds **1,587/1,587 hot bodies byte-identical**, including relocation targets
(`docs/trackorder/identity/objects.json`). No instruction budget was changed.

### Correctness receipts

Final whole-job runs are in progress. This section will be replaced with their
actual verdicts, failures and NOT RUN items before delivery. The final directed
matrix has 864 cases per boot across 24 boots: both database variants, modes,
engines and atomic settings, plus fused read-local 0/1. It records all cases
after failures and rejects a changed candidate binary.

Earlier evidence remains separate: the first harness launch failed because
the TomoKV readiness-banner check was applied to Redis. The initial PRE
matrix then found 1,152 expected SYNC ordering failures plus two BCAST setup
events that raced the next registration. The final harness explicitly turns
tracking OFF and requires zero live trackers before the next seed. An
intermediate POST run crossed a binary rebuild and is exploratory only;
final acceptance uses immutable arm paths and verifies their hashes.

### Row accounting

One new row, `tracking FLUSH reply order vs Redis 7.4`, is collected at
`tests/gate.sh:6310`, before the quick-tier branch at line 6380 and its exit.
**DQ=+1, DF=+1**. Maintainer-owned expectations should become **978/995** from
977/994. `EXPECT_QUICK` and `EXPECT_FULL` are unchanged.

### Maintainer merit request

Run the unchanged **14 generic cells** in
`docs/trackorder/generic14-cells.txt`, plus the **2s GET/SET p1/p32 null cells**
in `docs/trackorder/null-2s-cells.txt`, through the gate's own quiet-box ABBA
instrument. Arms: PRE/PRE null, PRE/POST, PRE/PAD-A. Use matched offered load,
warmup, dataset, affinity and geometry. Report rate, cycles/op,
instructions/op and IPC together, and the declared depth-one latency score.

Rate at matched load decides rate cells; the declared latency score decides
latency cells. Every main-command cell must show no reproducible regression
against the session's PRE/PRE control. The split GET/SET cells should remain
null; PAD-A is the exact-layout PRE-behavior control. Instruction counts alone
do not establish performance. **No throughput claim is made.**
