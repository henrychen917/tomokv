# Regression witness repairs

## witnessfix

Base: `7d2f8a2051961a1942735fb6dc9b507d778e09d1`; branch `cx-witnessfix`.
Test-side changes only. Correctness commands use CPUs 80-95, ports 20500-20599,
and `LC_ALL=C` for server boots. No full iteration was run. The initial lottery
adapter unexpectedly invoked memtier in its saturated-FLIP row despite the
correctness-only setting; those attempts are explicitly excluded below and the
adapter now rejects that action. No rate result is accepted as performance evidence.
Receipts are recorded under `docs/witnessfix/`; temporary controls live in `build/`.

This is a partial repair, not an all-flags closeout. The unresolved flags are
listed individually below and excluded from proven regression coverage. The
CG4.1 config-user probe also reproduces a baseline password-truncation security
defect in both modes; its strict Redis assertion fails and is not converted
into a green known-difference row.

### V1 — ACLKEYS3 last-owner-task wake

Added the `aclkeys_wake` gate job. It runs the existing production-body unit in
both database images, split/fused and atomic 0/1, across eleven schedules (88
invocations). The window cases require latch stages 1/2/3 and a renewed IO
notification after the last owner task leaves; missing arming is a failure.
The stale unit dispatcher now uses the production WATCH-aware scatter route,
retains deferred owner turns, and flushes each owner's thread-local commit batch
before visiting another logical owner. Its bounded drain still requires actual
completion; the latch stages remain mandatory. Control builders/runners accept
the lane CPU allocation instead of forcing the maintainer's CPUs.

Baseline: 88/88 unit schedules passed through the gate. The no-wake/no-hold
controls fail all 16 selected mode/database/atomic legs; see aclkeys-controls.json.
This is a serverless schedule, not a claim that a live listener hit the race.

DQ=+1, DF=+1: `collect_job aclkeys_wake` is before the quick-tier exit.
`EXPECT_QUICK`/`EXPECT_FULL` are unchanged and remain maintainer-owned.

### V2 — dead refusal counters

Removed all assertions/diagnostics based on `script_group_occ_giveups` and
`script_crossshard_window_refusals` from at412, wave8, mode_equivalence, differ
and xscript. Their existing exact replies, conservation and live wait/retry
counter checks remain the evidence. No new production counter is needed to
detect a refused reply. DQ=DF=0. Exact replies remain asserted; the final validation inventory identifies
which containing jobs were run. No dead counter is credited as a negative control.

### V4 / TM4.1 — debug battery atomic drift

Before every `job_debug` battery, restore `atomic` and require `CONFIG GET`
to return the requested value. A failed restore fails that battery without
mislabeling its configuration. `*-atomic.txt` records each live assertion.
DQ=DF=0. The no-restore test copy fails all four mode/atomic live flag checks;
restoration passes all four. Full split and armed-fused jobs are listed below.

### V14 — lottery campaign

`tests/gate.sh lottery` now exposes the existing nightly runner. CPU checks
require the assigned affinity, eight server CPUs and disjoint client CPUs;
ports must leave room for three listeners below 32768. The old hard-coded
112-127 / 25300 allocation could not run in this lane. Every boot inherits C
locale. The normal gate counts remain unchanged (DQ=DF=0).

Campaign command: `LC_ALL=C LOTTERY_CPUS=80-95 LOTTERY_JOBS=16 taskset -c 80-95
tests/gate.sh lottery --server-cpus 80-87 --client-cpus 88-95 --port 20590
--output build/witnessfix/lottery`. The initial default-cap attempt was stopped
after row 122 passed, row 126 errored, and row 128 recorded zero hits after its
600-second cap. It is not a completed campaign.

The complete bounded sweep used the same gate interface with `--cap 30
--attempt-timeout 180 --output build/witnessfix/lottery-bounded`, retaining the
20-hit requirement: **6 PASS, 49 INSUFFICIENT, 1 FAIL, 2 ERROR** over 58 rows.
The PASS IDs are 122, 149, 183, 206, 232 and 267. Row 310 (atomic-0 xmove) failed
its obsolete same-edge detector despite W6 trace hits; its replacement is
described under TM4.1. Rows 515/516 errored at the obsolete differential-driver
adapter. The adapter now uses the matrix's focused-driver interface; separate
follow-up receipts retain those runs. Both corrected adapters completed all
40 focused comparison legs without a mismatch and recorded one compound hit
each (765.9s / 767.9s). Both remain INSUFFICIENT against the unchanged 20-hit
requirement; see `docs/witnessfix/lottery-followup/`. No attempted command or empty trace is
counted as a hit. Final-tree rows 310/324 explicitly fail before boot with
D2/V4: their retired live inter-hop cell cannot supply W6 evidence. The new
serverless mover unit is not substituted for a candidate-binary trace. The sweep used the intermediate test versions whose SHA256
is printed in each battery log, against baseline production code plus the
existing observation-only lottery instrumentation.

Scope exception: the old saturated-FLIP adapter (row 368) invoked memtier in
five bounded-sweep attempts (four hit, verdict INSUFFICIENT), despite
GATE_PROOF_NO_RATES=1. Those invocations should not have occurred under this
task's exclusion of load generators. The adapter now refuses that row in
correctness-only mode. Its rate/latency output is excluded from all claims.
NOT RUN: a completed 20-hit final-tree campaign; most bounded rows have not met
their required sample count. The missing hits remain red/unresolved.

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
DQ=DF=0. Baseline dispatch_children passes all four mode/engine legs; an
always-empty production histogram mutant fails all four at the new assertion.

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
liveness bound, not a throughput measurement. The planted five-second freeze reaches one pause per process: the old battery
passes and the repaired battery fails in both engines (freeze-control.json).
AT4.12 T10 now also keeps producers running, uses four-second client/FLIP
deadlines, and rejects a valid-shape refusal. Its actual completed-FLIP and
client-transfer counters remain required. The old T10 passes four target legs
with one witnessed five-second freeze each; the repaired gate rejects all 12
target legs of that same defect, while its three oracle legs pass. The mix
passes all 15 baseline legs through the gate, with 29 successful FLIPs per
target leg and a maximum observed FLIP duration of 49 ms. These are liveness
receipts, not performance measurements. The mix
still excludes clients that entered MULTI; this does not close the separate
FLIP-EXEC-TRANSFER-TIMEOUT production defect or the V15 coverage gap. DQ=DF=0.

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
counter substitutes for those checks. DQ=DF=0. Baseline passed all eight mode/engine/database legs. The available
woundfix PRE also passes the added EXEC sub-battery, despite other mover rows
failing; that PRE is not a negative control for this addition. A second control
removed the mover helper's private-read-context preservation, but all eight
EXEC sub-batteries still passed; that attempted control is also excluded.
**V10 remains coverage-only, not a closed regression witness.** Both attempted
controls are recorded; their temporary binaries/source copies were removed.

### V11 — both list-push namespace publishers

Added a serverless producer-contract unit that invokes the production helper's
new-object and existing-object branches, both list edges, in physical namespaces
1/15/255. A link-time observer checks the actual namespace passed to the registry,
requires exactly one publisher hit per push, and checks resulting list content.
It complements the live SWAPDB/XADD consumer test; it does not claim a live mover
wake or a particular thread interleaving. The helper is shared by both thread
modes; namespaces require the db16 image. Separate planted namespace-zero controls
fail at the corresponding new/existing publisher. The baseline unit passes. DQ=+1, DF=+1: list_namespace is collected
before the quick-tier exit. A separate test Makefile fragment owns this target; the production Makefile is unchanged.

TM4.1 follow-up: restoring atomic 0 exposed an obsolete xmove witness. The
current mover reselects and removes its live edge in one source-owner turn;
the old same-edge detector required a phase-one value to survive an intervening
push, which is no longer the command's linearization point. Retired that timing
cell rather than making its no-hit result green. Its replacement lives in the
already gated moverfix production-body unit: finish both movers' initial probes, require
both destinations to defer, push on either source edge, then execute both source
claims. Require two distinct non-null replies and exact conservation across both
lists, accepting every valid cross-client linearization. Each schedule
prints an actual probe/push/claim hit. A stale-selection mutant supplies the
negative control. This is serverless evidence; no live pause is inferred.

### V3 — forced script-cycle scope

The strict txnorder case-c storm remains a smoke test, not a forced-cycle
witness. The existing at412 owner fixture and T7/T8 reached their forced states
and passed through their gate jobs in this lane. No new live cycle detector was
implemented. NOT RUN: a planted-defect proof for case c; its 30-second duration
is not a hit counter. It must not be cited as evidence that this window opened.

DQ=DF=0. This section records a remaining limitation, not new passing evidence.

### V6 — producer-to-inbox race remains unproved

UNREPAIRED: the existing reflag/sweep and stranded-state fixtures do not
observe the producer store versus ready-bit take. No deterministic live
producer latch was added. A notification after reconstructing stranded state
is not proof of the original producer race. NOT RUN: a no-sweep live negative
control; the audit's roughly 1% detection rate is not accepted as closure.
A production observable or a separately scoped scheduler fixture is needed.

DQ=DF=0. This section records a remaining limitation, not new passing evidence.

### V7 — snapshot storm is still load-shaped

UNREPAIRED as a deterministic starvation witness. The baseline snapshot EXEC
and script jobs passed; the at412 PRE script job fails while waiting for BGSAVE,
which is not proof that this particular 5-second EXEC starvation assertion
discriminates on faster hardware. The existing bound was not widened. A count
of owner tasks drained between snapshot-control passes is still needed to
claim a bounded scheduler witness. No performance conclusion is drawn.

DQ=DF=0. This section records a remaining limitation, not new passing evidence.

### V8 — blocking producer gaps remain open

UNREPAIRED: the atomic-1 RENAME/move controls remain conservation smoke checks,
not negative-control evidence for the atomic-0 missing-wake fix. COPY, RESTORE,
Z*STORE and GEOSEARCHSTORE wake omissions are unfixed production paths; adding
an always-green assertion would hide the defect. The stream-removal boundary
still covers only DEL/UNLINK. NOT RUN: new producer and removal matrices or
planted-defect proofs for them. These remain blocking/hang inputs for rootcompat.

DQ=DF=0. This section records a remaining limitation, not new passing evidence.

### V9 — TO-W3 evidence is serverless

The discriminating TO-W3 evidence remains its existing production-body unit.
W1/W2/S5 live legs still do not prove that the TO-W3 window opened; their replies
are useful smoke checks only. No live latch or additional negative control was
added. NOT RUN: a shipped-binary TO-W3 window proof. Do not promote the live
successes to evidence of that race.

DQ=DF=0. This section records a remaining limitation, not new passing evidence.

### V13 — AOF crossing proof binary identity

UNREPAIRED: F3's scheduled crossing arm still uses a hook-patched copy. That
can prove the state-machine ordering under the forced schedule, but cannot be
reported as a witnessed crossing in the shipped binary. No candidate-side
crossing observable was added and no new AOF crossing run was performed here.
NOT RUN: a candidate-binary crossing negative control.

DQ=DF=0. This section records a remaining limitation, not new passing evidence.

### V15 — migration overlap remains unwitnessed

UNREPAIRED: the directed atomic and EXEC interaction rows still disable LB
and automatic FLIP. Merely enabling those knobs would not establish an
ownership change during the asserted interval. No migration-while-armed hit
counter or ASAN/FLIP schedule was added. NOT RUN: new migrated atomic windows
and ASAN under FLIP. Single-owner and same-critical-section ownership laws
are unchanged; this lane makes no claim that their missing coverage is closed.

DQ=DF=0. This section records a remaining limitation, not new passing evidence.

### V19 — pre-cleanup leak visibility

UNREPAIRED: unconditional PIN release and the post-join client sweep still
hide the distinction between legitimate cancellation cleanup and runtime leaks.
Test-only code has no pre-cleanup inventory that identifies those cases. No
weaker shutdown invariant was introduced. NOT RUN: planted PIN/client leaks
with a discriminating pre-cleanup observer. A production diagnostic is needed
before these cleanup passes can serve as leak evidence.

DQ=DF=0. This section records a remaining limitation, not new passing evidence.

### V20 — previously omitted geometries

The standalone savefix acknowledgement/capture/replay probe was run on the
frozen baseline with 16 databases, fused mode, read-local=1 and atomic=1. It
passed with an observed partial capture and no acknowledged writes lost after
restart. This does not establish that LARGE-MSET-DROP is fixed: the current
probe batches its seed frames below 1 MiB and no original failing PRE is in
bins/. No new permanent gate row is claimed for it. The armed debug posture is
selected by GATE_TXN_FUSED=1 in this base (the audit's =0 spelling selects split).
Its two atomic jobs are included in the final validation inventory. NOT RUN:
a reproduced original large-frame defect/negative control.

DQ=DF=0. This section records a remaining limitation, not new passing evidence.

### V22 — latency assertions retain their limits

These rows are load-sensitive, not vacuous. No bounds were relaxed and no
performance run was requested or accepted as evidence. NOT RUN: PS4.7 merit,
PFDATATY.1 merit, or a quiet-box rate comparison; those remain the maintainer's
instrument. Existing correctness jobs that contain latency assertions report
their ordinary pass/fail outcome only.

DQ=DF=0. This section records a remaining limitation, not new passing evidence.

### V23 — statistical RENAMENX remains insufficient

UNREPAIRED: txn_nx still runs 8,192 synchronized rounds without observing the
critical overlap. At independent probability 1e-5 per round, its chance of at
least one failure is only 1-(1-1e-5)^8192, approximately 7.87%. The existing
ATOMIC-CONDITIONAL-DEFER hook covers atomic-OFF destination validation, not
the atomic transaction window this test claims. Increasing the round count or
counting barrier rendezvous would not repair that witness. NOT RUN: a new
forced transaction-window negative control; a suitable production observable
or controlled production-body unit is still needed.

DQ=DF=0. This section records a remaining limitation, not new passing evidence.

### Compat 4.1 — complete disposition of the remaining flags

The following are **not repaired or proved** by this lane unless explicitly
identified otherwise. Existing green smoke rows are not offered as negative
controls. NOT RUN below means no new directed proof for that gap; it does not
mean every existing row in that family was skipped.

| Audit flag | Disposition / missing evidence |
|---|---|
| XGROUP NOGROUP-only accounting | Demoted with D17a/D17b and BLOCK-STREAM-REMOVED-NO-UNBLOCK. No unmerged rootcompat fix assumed. |
| INFO / printver constants | CPU advancement and nonzero candidate build identifiers are now required. The zero-CPU mutant fails. Replication fields beyond the existing offset and the separate Tcl printver fallback remain unproved. |
| BLOCK-WAKE producer subset | V8 remains open; atomic-1 successes are not discriminating evidence. |
| autharity | Current source already includes ACL-restricted command-denial probes. Authenticated local-maximum and MULTI precedence remain NOT RUN. |
| ktls_lifetime / trackfix_order / tracking_redirect / racefix_climon / cd13b/cdfix | Serverless/source-copy evidence only. NOT RUN: new candidate-binary windows. |
| HX-3 expire_notify | NOT RUN: unrelated expired keys during live versions. |
| SV4.1 redaction | Existing lane coverage is broader than four shapes, but the skipped replication/cluster Tcl surfaces remain absent by design. No new broad redaction proof. |
| CG4.1 config user lines | **Baseline security defect reproduced in both modes**: `user witness on ">foo\x00tail" ~* +@all` accepts truncated `foo` and rejects the full password; Redis does the reverse. `docs/witnessfix/userline_probe.py` asserts Redis semantics and exits nonzero on this base. This is an open failure, not a known-difference pass or a production fix. |
| authfix / aclfix db0-only | Both database runtimes now run in every existing row. Geometry expansion alone has no new planted defect. |
| CC4.2 tracking cap / pipeline | NOT RUN: the MULTI enrollment/cap shape. |
| CLIENT REPLY SKIP | NOT RUN: a witnessed parser retry. Sending partial input alone is not sufficient. |
| notifycompat setpast / writemiss | NOT RUN: long values through L4 prebuild and additional producers. Existing short-value checks cannot close NO-A1. |
| notify_aof | NOT RUN: cross-owner scripts or local multi-key command argument-range replay (NO-A5). Potential event/invalidation/AOF loss remains open. |
| CD4.2 compact HSCAN | NOT RUN: mutate between pages while another unit retains a version. |
| CD4.9 same-owner SMOVE WATCH | Repaired: actual same-shard geometry, ordinary and EXEC arms, exact WATCH result; PRE fails the added assertion. |
| CD4.5 / CD4.15 / CD4.6 | Current list tests already cover 4,085/4,086-byte boundaries and repeated 100-byte values. Lua locale difference is now explicit. NOT RUN: 45–192-byte encoding and RENAME/COPY/MOVE preservation; ambient non-C boot conflicts with this task's LC_ALL=C requirement. |
| CD4.1 / CD4.19 GEO COUNT | Repaired: 20 centers, all read forms and both store paths compare COUNT without ASC/DESC/ANY directly to Redis. Both missing-implicit-order and reversed-order controls fail every added matrix leg. |
| Stream trim / image rebuild | NOT RUN: non-default node limits across image round trips. Existing Tcl mutant pass remains non-evidence. |
| MPOP error prefixes | Repaired in the list gate job: 68 exact error replies per RESP version, all four verbs, 12 geometries. A prefix-preserving suffix mutant fails all 12 legs; the 144 divergent replies still satisfy the old Tcl prefix pattern. |
| EX4.4 histogram stub | Repaired: enabled histogram must contain 32 acknowledged GET samples in RESP2/RESP3; empty stub fails. |
| Histogram default | Default-off versus Redis default-on remains a documented difference; explicitly enabling both servers does not prove default parity. |
| racefix_counters TSan filtering | NOT RUN: unfiltered accepts/plain_accepts race proof. |
| WAITAOF | NOT RUN: enabled-AOF local durable acknowledgment. |
| CONFIG allowlist | Repaired: exact native immutable error, or exact Redis reply / named lifetime difference. Unrelated-error mutant fails. |
| HLL success stub | Tcl alone remains blind. The existing serverfix_hll row already has a broken-estimator binary control; no new HLL proof was added. |
| MONITOR refused / nested commands | NOT RUN: strict refused-command and nested trace matrix. SV6 remains a documented divergence. |
| psfix / infofix success-only | Forced failed SAVE now records one actual error-path hit and Redis expectations. NOT RUN: loading=1 during load. |
| SO4.5 storesize unit | Removed the demand that the full walk occur. It remains a serverless state test, not a constant-work merit proof. |
| Storesize TTL merit | NOT RUN: performance measurements are outside authorization. |
| N1 / 148-case inline | NOT RUN: full UDS and both-engine matrix; the existing seven-case epoll row is not equivalent coverage. |

### Compat 4.3 — integration status

No one-retry rule remains. Five previously required assertions per mode are now
named skips: MONITOR blocked-once, two BRPOPLPUSH/WATCH assertions, guarded
XGROUP DESTROY, and UNSUBSCRIBE/PUBLISH disconnect lag. Existing SLOWLOG rewrite
and capacity skips have their actual root names. The three withdrawn climonfix4
promotions stay withdrawn. The SLOWLOG rewrite skip still hides its independent
SPOP/GEOADD/GETSET/INCRBYFLOAT checks; extracting those is NOT RUN. No guard
removal from rootcompat was available in this branch.

### Compat 4.4 — S1 input for round 5 (inventory only)

No new fixtures or binaries were built for this inventory.

- `external:skip` suppresses all main server blocks in unit/info (26 tests),
  unit/wait (35), unit/shutdown, integration/shutdown, unit/acl (110),
  unit/acl-v2 (34), unit/auth, unit/networking and unit/limits. Relevant risks:
  wrong replies/accounting, false durability acknowledgments, shutdown loss or
  hangs, ACL/auth security failures, networking crashes/hangs and resource limits.
- unit/pubsubshard and unit/querybuf are absent from the manifest: missing or
  wrong pubsub delivery, query-buffer state loss, crashes/hangs and limit bypass.
- INFO, WAITAOF, SHUTDOWN, ACL and TLS therefore rely on lane rows; those rows
  need independent coverage of failure paths, loading, durability, revocation,
  handshake/teardown and resource limits.
- The audit counted 39 survey cascades among 144 real-deviation skips. Seventeen
  passed fresh: five MULTI-OOM-QUEUE / D10 cascades and twelve
  BLOCK-WAKE-ORDER-MULTI / D11 cascades, including timeout/fairness and the
  ZRANDMEMBER-listpack case contaminated by a prior BZMPOP. Risks are wrong
  replies, stranded waiters and unintended pops. Some manifest entries changed
  before this base; audit counts are historical, not a new live count.
- Only two of TRACK-BCAST-BATCH's 26 promoted assertions test batching; the
  other 24 cascades do not prove invalidation correctness. Use the pubtrackfix
  witness for the actual stale-cache risk.
- TRACK-MAXKEYS-IMMUTABLE / D15 blocks thirteen unrelated tracking assertions
  in setup/cleanup, including FLUSHALL/FLUSHDB invalidation, CLIENT REPLY OFF and
  redirection. TRACK-FLUSH-INVALIDATE-ORDER fixes on unmerged cx-trackorder are
  not evidence for this base; stale client caches remain the S1 concern.
- NT4.17 remains only partly covered; the smaller inline battery is not
  equivalent UDS/engine coverage. CD4.19's COUNT-without-order gap is now closed
  by the added direct Redis matrix; broader GEO grammar remains separate.

### Validation inventory and limits

Frozen candidate: `build/witnessfix/tomokv-7d2f8a205`; SHA256 is in
`docs/witnessfix/baseline.sha256`. Every live positive job below selected that
binary. Rebuilt production-body units and lottery instruments use the unchanged
baseline source. The requested Redis oracle and the historical redis74 path
have identical SHA256 (see `oracle-binaries.sha256`); TLS uses its existing
separate TLS-enabled oracle. All server boot commands inherited `LC_ALL=C`.

The gate's own partial interface was used with server cores 80-87, client cores
88-95 and dedicated three-port ranges inside 20500-20599. `GATE_PROOF_NO_RATES=1`
prevents optional rate checks in the selected jobs; no full iteration or gate
receipt is claimed. Gate logs explicitly identify partial execution. The
lottery memtier exception and fix are recorded under V14.

| Final positive run | Result / scope |
|---|---|
| tcl-full-gate / YyGVfV | Complete checked-in manifest passes in both modes: 39 file entries per mode, 1,870 reported passing assertions each. The unchanged runner accepts five named setup errors and records 437 skips and 40 teardown EOF exceptions per mode; these are not new compatible assertions. |
| V1-tcl-info-final-gate / KNbncV | 5 rows pass: ACLKEYS3 (88 schedules), touched Tcl files in both modes, INFO compatibility missing fields. |
| compat-corrections-gate / wnjTzl | 15 rows pass: ACL runtime/capacity, locale, exact CONFIG errors. |
| compat-rest-gate / PtFRDq | Auth's five rows and the remaining datafix1/netfix rows pass. Its initial locale and ACL capacity failures are preserved; corrected runs above supersede those two test states. |
| compat-strengthened-gate / fh6Dke | WATCH and histogram jobs pass. Its initial excessive Lua CPU-loop budget failed; corrected INFO runs use 10,000 iterations and pass. |
| core-gate / VrEKcy | Snapshot shutdown/script/EXEC and EXEC interaction rows pass. Its old atomic-0 xmove detector failed; final debug runs below supersede that test state. |
| remaining-core-gate / 9Xkxyg | 49 rows pass: atomic units including storesize, movers, txn groups in both modes, exec1s, wound controls and at412 owner/T7/T8. |
| debug-final-split / C8Qe5S | 33 rows pass, both atomic settings; every battery starts with an asserted live flag. |
| debug-final-fused / BUEmU9 | 33 rows pass with GATE_TXN_FUSED=1 and read-local armed, both atomic settings. |
| features-gate / O3MRN4 | 139 rows pass, split/armed-fused × atomic 0/1, including all netcmd legs. |
| flip-list-final / qaKgTE | 11 rows pass: strict FLIP checks in both engines and the new list namespace unit. |
| differ-gate / DFaQBX | Split atomic 1, armed-fused atomic 0/1 and mode equivalence pass. Split atomic 0 reached the unchanged 900s row deadline; its timeout is preserved. |
| differ-split0-final / tATR7A | Split atomic 0 passes all 235 legs in 8m57s under the original 900s deadline. Permanent seeds 7/19/20/23 plus the runner-selected rotating seed 22; the earlier run used rotating seed 21. |
| mpop-exact-positive / z6Bgep | List job passes all 12 geometries with 136 exact MPOP error comparisons per leg (RESP2/RESP3). |
| geo-count-positive / EEpVC2 | GEO job passes all 12 geometries with 20 direct-oracle COUNT centers per leg. |
| at412-rest-script-bounds / vxNJ6f | 18 rows pass: remaining AT4.12 cases and split script limit/window controls. Its T10 used the old pause behavior and is superseded by the strict T10 run below. T6 completes all 27 legs in 812.61s. |
| at412-strict-final / X3Xo6L | 2 rows pass: release and repaired T10. All 15 legs pass in 451.80s, covering Redis plus both target engines/atomics and EVAL/EVALSHA/FCALL; each target leg completes 29 FLIPs and asserts actual client transfers. |
| script-bounds-fused / lt8x49 | 3 rows pass: release plus the two controls with armed fused mode. |
| mover-conservation-gate / ntf5Ys | 9 rows pass (release plus eight geometry legs), including the final two-mover probe/push/claim unit and EXEC coverage. Earlier Q1ikt4 used the superseded, overstrict single-mover expectation and is not the final proof. |

Each archive in `docs/witnessfix/gates/` preserves the canonical partial ledger,
job ledgers and small stdout/JSON receipts. `gate-runs.json` retains earlier
failures and non-discriminating controls instead of presenting only the final
green runs. Reproduction entry point: `GATE_ONLY_JOBS='<job names>' LC_ALL=C
GATE_PROOF_NO_RATES=1 taskset -c 80-95 tests/gate.sh quick --server-cores 80-87
--load-cores 88-95 --load-smt '' --ports 20500-20502 --candidate-binary
"$PWD/build/witnessfix/tomokv-7d2f8a205"`. Differential jobs use `full` with the
same partial selector and `REDIS74_ROOT=/home/user/Projects/redis`; they do not
run the full tier's performance phases.

| Repaired witness | Discriminating result |
|---|---|
| ACLKEYS3 | No-wake and no-hold controls: 16/16 selected legs fail; baseline 88/88 pass. |
| TM4.1 restoration | Removed restore: four mode/atomic settings fail the live flag assertion; restoration passes all four. |
| Replacement mover push schedule | Stale phase-one selection: four unit legs fail distinct-claim conservation; baseline passes with 16 actual schedule hits. |
| List namespace publishers | Namespace zero at each of the two call sites fails exactly that branch; baseline reaches both branches/edges in namespaces 1/15/255. |
| FLIP five-second freeze | One witnessed pause per process: old battery passes in both engines, repaired battery fails with client 4s timeouts in both. |
| Snapshot script refusal | at412 PRE: all eight target shutdown legs fail on received TRYAGAIN; oracle and baseline legs pass. The PRE BGSAVE-script failures occur while arming BGSAVE and are not credited to the new refusal check. |
| Same-shard SMOVE WATCH | multifix PRE: 24/24 target legs fail the added unchanged-destination WATCH assertion; baseline passes. |
| Enabled histogram | Always-empty mutant fails all four mode/engine legs; baseline passes. |
| INFO CPU | Constant-zero mutant fails the new advancing-CPU assertions in all eight target geometry legs (both RESP versions); baseline passes. |
| CONFIG errors | Unrelated-error mutant fails the exact allowlist check; baseline passes all mode/engine legs. |
| AT4.12 T10 freeze | Old test passes all four engine/atomic EVAL controls despite one five-second freeze each. Repaired gate fails all 12 target command/engine/atomic legs on their four-second timeout, with exactly one freeze hit per process; oracle passes. |
| MPOP full errors | Prefix-preserving suffix mutation fails 12/12 geometry legs; all 144 changed replies would match the old Tcl pattern. |
| GEO COUNT | Missing implicit ASC and reversed shared ordering each fail 12/12 legs. The reversed comparator still passes both old self-comparison cases in 1s/2s (4/4), proving their blind spot. |

Anti-witness conversions, label repairs and deleted dead-counter checks are not
counted as new defect controls. Named known differences remain exclusions from
Redis compatibility evidence. Every unproved core/compatibility flag is listed
above; this lane does **not** claim that all audit flags are closed.

Row accounting: **DQ=+2, DF=+2**. `collect_job aclkeys_wake` and
`collect_job list_namespace` occur at lines 6253/6254 of this gate revision,
before the quick exit at line 6499. No row is retired. The execfair label changes
identity text only; expanded internal matrices add no public rows. The five Tcl
demotions affect assertion counts inside existing jobs, not gate rows.
`EXPECT_QUICK=999` and `EXPECT_FULL=1016` remain untouched; the maintainer should
set **1001 / 1018** after accepting these two additions.

Scheduler self-test resource correction: the fixed 45-second outer process cap
repeatedly expired in the complete-inventory one-slot fixture (the other 76
checks passed with compilation stopped). This is not a Redis latency or race
window assertion. The fixture now derives its outer resource budget as 45s
setup/teardown plus 0.5s per source-declared job per slot. It still executes the
entire inventory and all real budget/watchdog/history helpers, and every
failure-injection assertion remains. Real gate row deadlines, latency limits,
arming thresholds and retry policy are unchanged. Earlier timeout receipts are
retained. This correction is not offered as a production performance result.

Self-tests: `GATE_TEST_PORT=20599 python3 tests/gates_test.py` passes **77/77**
(final run 223.915s) with the inventory-derived
fixture budget. Tcl runner 10/10, differential 24/24, lottery runner 18/18,
lottery evidence reducer 17/17 and psfix 7/7 pass. Logs, including earlier
scheduler timeouts, are retained in `docs/witnessfix/`.

Resource notes: all correctness server binaries used the assigned CPU/port
ranges and C-locale boot commands. Earlier scheduler self-test socket-ownership
probes used their existing ephemeral-port default; the final run sets
`GATE_TEST_PORT=20599`. Those probes are Python test listeners, not server
binaries, but their earlier port selection was outside the requested range.
`build/` briefly reached approximately 19 GiB during unit/control rebuilds;
deleting copied controls and stripping unit debug sections reduced it below
15 GiB. No production source or production Makefile byte changed.
Final cleanup finds no owned correctness server and no listener on ports
20500-20599. All planted source/binary copies are deleted; the frozen positive
binary and small control recipes/receipts remain. `build/` is 12.97 GiB
(`docs/witnessfix/cleanup.json`).

Static verification: `make -q` returns 0; production-path diff is empty;
44 changed Python files parse; shell syntax and the implementation whitespace
check pass. Verbatim planted-defect patch receipts retain unified-diff blank
context lines. The untouched EXPECT values and frozen baseline hash are in
`docs/witnessfix/static-checks.json`.

### Compat 4.1 follow-up — MPOP errors and GEO COUNT

`MPOP-ARG-ERROR-TEXT`: the existing list gate job compares all four verbs' illegal-argument
and wrong-type replies byte-for-byte with Redis, in verified RESP2/RESP3. The
GEO job now compares every no-order COUNT query directly with Redis across 20
centers and checks stored membership as well as replies. Neither uses the
candidate's own explicit ASC as the oracle. The original MPOP prefix matcher
and GEO self-comparison controls accept the respective planted defects; the
repaired assertions fail. Both baseline jobs pass every declared geometry.
Known MPOP argument-precedence residue outside these Tcl shapes remains open;
this is not a claim that every grammar combination is compatible. DQ=DF=0.
