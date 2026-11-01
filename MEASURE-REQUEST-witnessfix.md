# Regression witness repairs

## witnessfix

Base: `7d2f8a2051961a1942735fb6dc9b507d778e09d1`; branch `cx-witnessfix`.
Test-side changes only. Correctness commands use CPUs 80-95, ports 20500-20599,
and `LC_ALL=C` for server boots. No full iteration was run. The initial lottery
adapter unexpectedly invoked memtier in its saturated-FLIP row despite the
correctness-only setting; those attempts are explicitly excluded below and the
adapter now rejects that action. No rate result is accepted as performance evidence.
Receipts are recorded under `docs/witnessfix/`; temporary controls live in `build/`.

### V1 — ACLKEYS3 last-owner-task wake

Added the `aclkeys_wake` gate job. It runs the existing production-body unit in
both database images, split/fused and atomic 0/1, across eleven schedules (88
invocations). The window cases require latch stages 1/2/3 and a renewed IO
notification after the last owner task leaves; missing arming is a failure.
Control builders/runners now accept the lane CPU allocation instead of forcing
the maintainer's CPUs.

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
follow-up receipts retain those runs. No attempted command or empty trace is
counted as a hit. The sweep used the intermediate test versions whose SHA256
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
counter substitutes for those checks. DQ=DF=0. Baseline passed all eight mode/engine/database legs. The available
woundfix PRE also passes the added EXEC sub-battery, despite other mover rows
failing; that PRE is not a negative control for this addition.

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

TM4.1 follow-up: restoring atomic 0 exposed xmove's obsolete witness. The current
mover removes its source at the first mutation turn; the old detector required a
push reply of 3 (source not yet removed), so it could count a before-first-hop
push and could never prove the same-edge case. Replaced the LREM/sleep timing
with the existing non-lead mutation delay, an observed source claim, and a
still-pending move after the intervening push. Each fresh attempt checks exact
lists and replies; missing arming still fails after 20 attempts. Timing/rate
checks remain disabled in this correctness-only run.

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
| CD4.1 / CD4.19 GEO COUNT | NOT RUN: unspecified-order COUNT form against Redis. |
| Stream trim / image rebuild | NOT RUN: non-default node limits across image round trips. Existing Tcl mutant pass remains non-evidence. |
| MPOP error prefixes | NOT RUN: full-string oracle matrix. Prefix-only checks remain weak. |
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
- CD4.19's GEO COUNT form and NT4.17 remain only partly covered. Round 5 should
  isolate their wrong-reply/protocol paths rather than treating neighboring
  forms or the smaller inline battery as equivalent coverage.
