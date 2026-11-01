# Regression witness repairs

## witnessfix

Base: `7d2f8a2051961a1942735fb6dc9b507d778e09d1`; branch `cx-witnessfix`.
Test-side changes only. Correctness commands use CPUs 80-95, ports 20500-20599,
and `LC_ALL=C` for server boots. No performance measurements or full iteration.
Receipts are recorded under `docs/witnessfix/`; temporary controls live in `build/`.

### V1 — ACLKEYS3 last-owner-task wake

Added the `aclkeys_wake` gate job. It runs the existing production-body unit in
both database images, split/fused and atomic 0/1, across eleven schedules (88
invocations). The window cases require latch stages 1/2/3 and a renewed IO
notification after the last owner task leaves; missing arming is a failure.
Control builders/runners now accept the lane CPU allocation instead of forcing
the maintainer's CPUs.

Proof receipts: pending the baseline build and the no-wake/no-hold controls.
This is a serverless schedule, not a claim that a live listener hit the race.

DQ=+1, DF=+1: `collect_job aclkeys_wake` is before the quick-tier exit.
`EXPECT_QUICK`/`EXPECT_FULL` are unchanged and remain maintainer-owned.

### V2 — dead refusal counters

Removed all assertions/diagnostics based on `script_group_occ_giveups` and
`script_crossshard_window_refusals` from at412, wave8, mode_equivalence, differ
and xscript. Their existing exact replies, conservation and live wait/retry
counter checks remain the evidence. No new production counter is needed to
detect a refused reply. DQ=DF=0. Live and PRE receipts pending.

### V4 / TM4.1 — debug battery atomic drift

Before every `job_debug` battery, restore `atomic` and require `CONFIG GET`
to return the requested value. A failed restore fails that battery without
mislabeling its configuration. `*-atomic.txt` records each live assertion.
DQ=DF=0. Both split atomic settings and the explicit fused posture need runs.

### V14 — lottery campaign

`tests/gate.sh lottery` now exposes the existing nightly runner. CPU checks
require the assigned affinity, eight server CPUs and disjoint client CPUs;
ports must leave room for three listeners below 32768. The old hard-coded
112-127 / 25300 allocation could not run in this lane. Every boot inherits C
locale. The normal gate counts remain unchanged (DQ=DF=0).

Campaign command: `LC_ALL=C LOTTERY_CPUS=80-95 LOTTERY_JOBS=16 taskset -c 80-95
tests/gate.sh lottery --server-cpus 80-87 --client-cpus 88-95 --port 20590
--output build/witnessfix/lottery`. Results pending; no hit is inferred from
an attempted command or an empty trace.

### V17 — Tcl retries and root names

Removed the retry implementation, including its dead SLOWLOG entry. MONITOR
blocked-once and both BRPOPLPUSH/WATCH assertions become named known differences
(MONITOR-BLOCKED-ONCE, BRPOPLPUSH-WATCH-ORDER / D11). Failed receipts can no longer
be replaced with a later pass. The SLOWLOG skip now names EXEC retirement order,
not generic cross-connection order. Remaining OOM/block-chain skips name D10/D11.
Several survey cascades were already promoted between the audit and this base;
no historical promotion is inferred to be a new witness here.
DQ=DF=0; Tcl required assertions decrease by three per mode, with explicit skips.

### V18 — snapshot storms must reject refusal replies

Removed BUSY/TRYAGAIN tolerance. Script activations require two-element replies;
the shutdown worker now propagates assertion failures to the main test instead
of merely printing a thread exception. Unanswered work at shutdown is still
distinguished from an error reply already received. DQ=DF=0.

### V21 — accurate interaction-row identity

Renamed `job_execfair` and its ledger identity fixture to include the wave6-wave10
interaction batteries it actually runs. DQ=DF=0; one label is renamed, no row
is added or retired. This is reporting repair, not new concurrency evidence.

### Compat 4.2 — XPENDING exclusive bounds

The Redis 7.4.10 oracle rejects `(-` and `(+` with `ERR Invalid stream ID
specified as stream command argument`, and exclusive UINT64_MAX with `ERR
invalid start ID for the interval`. The battery now records those expectations.
The existing empty-array result is a named known difference under
XRANGE-EXCLUSIVE-SENTINEL / XPENDING; any other result fails. The ECHO/PING framing
fence remains strict. DQ=DF=0; the exclusion is not evidence of compatibility.

### Compat 4.1/4.3 — guarded XGROUP promotion

Returned the XGROUP DESTROY/NOGROUP accounting assertion to a named skip with
INFO-ERRORSTATS / INFO-CMDSTAT-FIELDS (D17a/D17b) and
BLOCK-STREAM-REMOVED-NO-UNBLOCK. Rootcompat must remove the generic accounting
guard before it is promoted again. This lane does not assume an unmerged fix.
DQ=DF=0; one fewer required Tcl assertion per mode, one explicit known skip.

### Compat 4.2 — ACL timeout after revocation

Timeout cases expect Redis null frames (RESP2 `*-1`, RESP3 `_`). The existing
retire-time NOPERM is explicitly ACL-REVOKED-TIMEOUT, a known difference listed
in the audit, rather than a compatible pass. The whole-frame ECHO fence still
rejects two replies, including the historical coded-null plus NOPERM defect.
DQ=DF=0. Woken/permitted arms retain exact replies.

### Compat 4.2 — ACL capacity

Overflow creations now expect Redis OK. The documented 65,535-user limit is
explicitly CC4.24 / ACL-LIVE-USER-CAP. Churn/reuse, stale handles and clean
shutdown remain strict regression assertions. DQ=DF=0.

### Compat 4.1/4.2 — SO4.5 full-walk anti-witness

Removed the requirement to route INFO through every shard and visit the hash.
The unit retains exact subexpiry/state assertions and reports any census walk
as known difference SO4.5. A correct constant-work implementation can now pass.
No timing or merit claim is made; TTL cost measurement stays with the maintainer.
DQ=DF=0.

### Compat 4.2 — BITFIELD above the string representation limit

Both servers now expect `[0]` for reads of a missing value at the large offset.
The 32-bit representation error is recorded as CD4.10 / NETFIX-POST-2 with Redis
and target replies in the receipt. No multi-gigabyte allocation is required.
DQ=DF=0.

### Compat 4.2 — string growth above 4 GiB

SETRANGE/SETBIT/BITFIELD now state Redis success values and label the documented
representation clamp NETFIX-POST-2. Exact clamp errors remain a bounded known
difference; different errors fail. An eventual compatible implementation is
accepted and cleaned up. Oracle allocations above 4 GiB: NOT RUN (the known
architectural difference is named, not presented as oracle-verified parity).
DQ=DF=0.

### Compat 4.3 — remaining integration demotions

Named PUBSUB-DISCONNECT-LAG (D14) replaces the intermittently promoted
UNSUBSCRIBE/PUBLISH assertion. The existing SLOWLOG capacity skips now identify
SLOWLOG-MAXLEN-PER-THREAD; the Redis CLI MIGRATE skip already names D17d.
The three withdrawn climonfix4 promotions remain withdrawn. No retry remains.
DQ=DF=0; one fewer required Tcl assertion per mode.

### Compat 4.1 — EX4.4 histogram stub

The dispatch-children row now also enables latency tracking in RESP2/RESP3,
executes exactly 32 GETs and requires their call count and nonempty cumulative
buckets. An empty histogram stub cannot pass. The default/off probes remain.
DQ=DF=0; PRE and current receipts pending.

### Compat 4.1 — INFO placeholders

INFO CPU must advance across eight acknowledged bounded Lua computations, not
merely format six zeros. Target git/build IDs must not be zero placeholders.
The standalone printver format check remains a format check; replication offset
semantics remain a separate gap, not implied by INFO field presence. DQ=DF=0.

### Compat 4.1 — CD4.9 local WATCH/SMOVE

Added ordinary and EXEC SMOVE no-op destination checks on a pair proved by
DEBUG geometry to share a shard. Require one successful move, consumed source,
unchanged destination and an un-aborted destination WATCH. The key discovery
fails if no such pair is found; it prints the shard and one armed hit. DQ=DF=0.

### V5 — blind transaction-order diagnostic

Removed zero-value `atomic_txn_order_violations` assertions from the six named
batteries and at412. Their exact data/reply/conservation assertions remain. A
zero from this counter is not atomicity evidence; the forced AT4-WOUND-1 window
in `job_txnorder_wound` is the relevant independent discriminator. This does
not claim the ordinary storms open that window. DQ=DF=0.

### V16 — FLIP stalls and refusals

Reduced the ordinary client deadline from 15 s to 4 s, so a five-second freeze
cannot pass. Valid computed FLIP shapes must not be refused. Existing per-worker
progress before/after an observed completed FLIP remains mandatory. This is a
liveness bound, not a throughput measurement. A planted freeze/PRE control is
required before treating this change as demonstrated regression evidence.
DQ=DF=0.

### Compat 4.2 — failed foreground SAVE telemetry

Redis 7.4.10 was forced to fail SAVE at rename: rdb_saves 0->1, background
status ok->ok, reply ERR. psfix now records those expectations and names the
known PS7 count/SV9 background-status differences. The gated INFO missing-field
battery also forces this error path with a directory at dbfilename and requires
an error plus one recorded hit. It never turns a successful SAVE into evidence
of an error path. DQ=DF=0.

### Compat 4.1 — CD4.6 locale coverage and boot discipline

All datafix1 servers now boot with LC_ALL=C, including direct invocation. The
locale battery proves explicit en_US.UTF-8 differs from inherited C and compares
Lua sorting/comparison with the oracle while changing locale-collate. Non-C
ambient server startup is NOT RUN because this task requires every boot in C.
DQ=DF=0.

### Compat 4.1 — ACL/auth default database runtime

Every authfix case now owns both database-runtime boots (1 and 16); aclfix's
existing rows aggregate both as well. Per-runtime argv and replies have distinct
receipt directories. This closes the db0-only setup gap without changing the
number of public rows (DQ=DF=0). Geometry coverage alone is not a new defect
negative control.

### Compat 4.2 — DBSIZE command substitution

The multidb differential now sends plain DBSIZE to both servers before the
separate NOW exact-count property. Nonnegative but unequal published counts
are explicitly DBSIZE-PUBLICATION-LAG (owner decision 12), excluded from parity
and counted. Invalid frames still fail; the existing final nonzero population
must converge within its bound. NOW no longer impersonates compatibility with
Redis DBSIZE. DQ=DF=0.

### V12 — IO4.19 refusal tolerance

Removed both stale-epoll-registration exceptions from flipfix close/churn.
A valid manual FLIP must succeed; the auto-controller collision remains a
separate valid concurrent-request outcome. This closes the obsolete tolerance,
not the missing IO4.1 latch. The existing moving observation does not establish
that a close occurred after detach/RoleReady. Late/abort producers still need a
production observable to make that claim; the ungated late probe lacks it too.
DQ=DF=0. Do not count a successful close storm as a forced late-close witness.

### Compat 4.1 — CONFIG allowlist errors

Boot-only settings no longer accept arbitrary ERR replies. Native controls
require their exact immutable error; Redis-backed settings first compare the
oracle's value and otherwise accept only the exact documented lifetime error,
with CONFIG-RUNTIME-IMMUTABLE / 68d-4 or TRACK-MAXKEYS-IMMUTABLE / D15 in the
receipt. Both retained values and transaction rollback remain checked. DQ=DF=0.

CD4.6 baseline result: the added strict Lua probe failed all twelve target legs.
Redis under explicit en_US.UTF-8 returns `[1,[a,A,b,B,é]]`; this base returns
`[0,[A,B,a,b,é]]`. The audit already documents that unfixed path (compat §6.12).
It is now named CD4.6-LUA-COLLATION, with both replies retained and excluded from
compatibility evidence. The oracle's non-C result must be witnessed; all other
locale legs remain exact. No claim of a production repair or negative-control
proof is made for this remaining difference.

### V10 — EXEC-child mover conservation

The existing moverfix job now attempts its previously omitted EXEC battery in
every mode/engine/database leg, alongside the donor controls. Exact delivery,
no duplicate or missing members and post-drain state are required; no blind
counter substitutes for those checks. DQ=DF=0. Baseline validation is pending;
a reproduced D2/EXEC loss will be reported rather than excused as timing.
