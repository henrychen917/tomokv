# Remaining mechanisms, third audit

Base: `origin/cpp` at `dab740964`; test-side repair `368f92df7`. This register preserves all 42 inherited mechanisms and adds GT16, CD13b GEO and PSFIX explicitly. A = test-side witness implemented; B = missing server witness; C = performance/resource threshold; D = production defect. An A classification is **not** a fresh live-proof claim. No production code or gate declaration changed.

**Proof status:** selected-job and full-iteration admission receipts are reported in [MEASURE-REQUEST-flakeaudit3.md](../../MEASURE-REQUEST-flakeaudit3.md). No past landing or serverless control is counted as a new live run.

Original-register occurrence counts stay **A=35, B=58, C=22, D=2 (117)**. Adding the distinct GT16 row gives **A=36, B=58, C=22, D=2 (118)**. GEO is an A submechanism inside the two B differential aggregate rows; PSFIX is a B submechanism there. They are not double-counted. Original mechanism counts: **A=15, B=18, C=8, D=1 (42)**; all 45 named entries, including overlapping addenda: **A=17, B=19, C=8, D=1**.

Ordinals on the left are the stable original audit IDs. The current ordinal column accounts for the two already-landed extra quick rows. [Full mapping](evidence/row-map.json). Gate counts by source line remain **502 quick / 519 full, +0/+0**; the quick exit is at line 3402 and both differential aggregate collection lines are below it. [Source receipt](evidence/row-counts.json).

| Mechanism | Original ordinals | Current ordinals | Class | Disposition / retained oracle |
|---|---|---|---|---|
| 1. netio | 47, 48 | 47, 48 | C | Wake latency <25 ms; exact blocked-client identity and delivered value remain correctness facts. |
| 2. torture | 118, 501 | 120, 503 | A | Unique churn keys; observer GET witnesses each SET before RST, with the writer reply unread and partial next frame retained. Final landed-key assertion and every transport error remain. |
| 3. ryow | 119, 502 | 121, 504 | A | All four background writers acknowledge progress and propagate errors. Added explicit same-key overwrites with an allowed-conflict value set, followed by exact uncontended RYOW; original own-key checks retained. |
| 4. spinprobe | 122, 203, 210, 366 | 124, 205, 212, 368 | B | W10: per-client parser-park state, observed before the counter interval; ordinary body change YES. Existing LBSIGNALS lacks this state. Counter budgets also need a separate performance instrument (see threshold appendix). |
| 5. atomic_torn | 126, 503 | 128, 505 | B | W2: held read-cut/lead-fragment stage with entered/released status; ordinary body change YES. The existing RENAME hold and commit latch do not force the other fanout/promotion windows. |
| 6. atomic_ryow | 127, 504 | 129, 506 | C | Pipeline rate >1.10 times serial rate (24 groups, release only). Exact ACKs, ordered reads, consistent-or-absent values and positive worker/cut counts remain. ASAN omits the rate assertion but still has finite stress floors; a held overlap is also needed before claiming those arms witnessed. |
| 7. atomic_hazards | 128 | 130 | B | W2: publish and hold the exact pinned-cut/reader and dispatch stages; ordinary body change YES. Finite delays plus elapsed observations cannot identify those stages; unarmed XREAD <100 ms is a performance control. |
| 8. s6 | 130, 164, 199, 206, 213, 248 | 132, 166, 201, 208, 215, 250 | B | W3: DEBUG-controlled sampler traversal/seed with a required traversal-complete witness; ordinary body change YES in the armed sampler branch. Keep exact all-200-key coverage; 20,000 random draws alone cannot guarantee it. |
| 9. multi_exec | 131, 165, 200, 207, 214, 249, 357 | 133, 167, 202, 209, 216, 251, 359 | B | flakeaudit2b reverted this battery exactly to pre-flakeaudit2 (5bf5b65e6); original lottery stress and all original assertions retained. W16: nonblocking EXEC latch after every owner installs and before atomic_commit_group, with transaction identity, installed-owner/key counts, entered status and explicit release. ATOMIC-COMMIT-HOLD only stops flush_xshard_commits (src/core/ex_loop.h:2761); EXEC commits directly (src/cmd/multi.inc:2255). Pending entries count installs, not a held stage; atomic_exec_order_holds witnesses a younger EXEC waiting before install. Finite COMMIT-DELAY/FANOUT-DEFER/SLEEP cannot provide explicit release. Ordinary body change YES; no production change authorized here. |
| 10. blocking | 132, 166, 215, 250, 358 | 134, 168, 217, 252, 360 | B | W1 plus W5: applied per-owner config epoch and controlled finite-blocker deadline/retirement; ordinary body changes NO for owner-local config query, YES for an armed clock/lifecycle latch. Exact null/data/gauges stay; two 0.10..0.75 s bounds also mix timing into correctness. |
| 11. blockmulti | 133, 167, 216, 251 | 135, 169, 218, 253 | C | EXEC completion <250 ms; satisfied WAIT <100 ms; WAIT 200 in 150..900 ms; pipeline WAIT 120 >=90 ms. Exact EXEC results, WAIT :0, younger PONG order, parked/drained gauges and timeout-zero silence remain. Deadline lower bounds express semantics; the upper ceilings are performance. |
| 12. stream | 134, 168, 217, 252 | 136, 170, 219, 254 | C | Current source gates footprint, not the old register's sampled latency: plateau growth <=8192 B, post-delete <=baseline+4096 B, 0<B/key<512, 128-entry usage<25,600 B. Exact last-100 payloads, all 128 migration entries, DBSIZE and positive allocation remain. Empty-stream timeout >=80 ms is separate deadline semantics. |
| 13. limits | 139, 173, 222, 257 | 141, 175, 224, 259 | B | W5: DEBUG-held cron/timeout progression with fired and retired client identity; ordinary body change YES. CLIENT LIST already witnesses admission/closure, but not the soft-limit/idle deadline crossing while the test's heartbeat was descheduled. |
| 14. climon2 | 146, 180, 229, 264 | 148, 182, 231, 266 | C | PAUSE WRITE read <250 ms, held write >300 ms, UNPAUSE elapsed <2000 ms. Exact GET/SET replies, positive client_pause_holds, ALL-mode silence and released reply remain. A held pause/deadline stage would separate the >300 ms mechanism claim from the clock. |
| 15. tracking | 147, 181, 230, 265 | 149, 183, 232, 267 | A | Fresh client/key and bounded TTL registration; the 300 ms negative drain occurs before arming the unchanged 400 ms TTL. Positive invalidation is read as a complete exact RESP frame; expired value must be absent. |
| 16. hexpire | 148, 182, 231, 266 | 150, 184, 233, 268 | A | Recreate only clock-invalid short-field setup; HPEXPIRE and HPEXPIRETIME share one EXEC cut so the actual installed deadline is captured before it can expire. TIME bounds subsequent counters/HLEN. Lazy arm disables active expiry and requires the exact reap delta; active baseline precedes TTL installation. Other numeric tolerances are unchanged. |
| 17. servertail | 149, 183, 232, 267 | 151, 185, 234, 269 | B | W1: query each owner's already-applied live-config version before OBJECT policy checks; ordinary body change NO if queried on that owner through cold DEBUG work. TIME's +/-60 s allowance is an additional clock oracle, not evidence of config publication. |
| 18. concur | 151, 185, 234, 269 | 153, 187, 236, 271 | A | Every churn batch is acknowledged while a nonzero SCAN cursor is open. Growth/cardinality/rehash and exact permanent-set assertions remain; callbacks no longer count mutation after cursor completion. |
| 19. edgetime | 154, 188, 237, 272 | 156, 190, 239, 274 | A | Fresh 70/80 ms absolute-deadline queue/WATCH setup must complete before that deadline; missed setups DISCARD/UNWATCH and recreate state within a budget. PEXPIRETIME must equal the armed deadline; wait for it before EXEC. Exact null/abort/reap and negative controls remain. |
| 20. expwide | 159, 193, 242, 277 | 161, 195, 244, 279 | B | W4: publish a pinned command/transaction expiry cut and hold before the later owner/read until explicit release (including read-local and script/EXEC variants); ordinary body change YES. Existing ATOMIC-FANOUT-DEFER is a finite duration with no entered-stage publication. |
| 21. pushtear | 161, 195, 244, 279 | 163, 197, 246, 281 | A | Exact CLIENT ID must be blocked before PUBLISH; require its ACK before the unchanged one-second deadline. Fresh connections only on missed arming. The two complete frames must retain push/null order and the segment-counter assertion. |
| 22. read-local high water | 246, 281 | 248, 283 | A | Per-battery INFO high water survives RESETSTAT, following differ_gate.sh. A malformed/missing counter latches failure; no synthetic local reads are added. Positive peak remains required at shutdown. |
| 23. aclreply | 294, 295 | 296, 297 | A | Exact blocked CLIENT ID, fresh finite timeout arms, acknowledged ACL revocation, and an ECHO reply fence. Compare the entire raw stream, including a duplicate coded null if present, to the original expected reply. |
| 24. slowlog | 300, 314 | 302, 316 | B | W1: applied config epoch on every IO/ex owner before recorder assertions; ordinary body change NO for cold owner-local queries. The existing 200 ms propagation sleep is not that acknowledgement. |
| 25. execatomic / execiso | 303, 304, 317, 318 | 305, 306, 319, 320 | B | W2: hold a published first fragment and pinned read cut until explicit release; ordinary body change YES. ATOMIC-COMMIT-HOLD covers installed records, not this read-fanout lead-fragment schedule. |
| 26. multires | 306, 320 | 308, 322 | A | First positive atomic-on round holds a real undecided predecessor and requires atomic_exec_order_holds plus pending entries before release. Existing ACK/value/probe assertions, remaining rounds and negative/atomic-off controls stay. |
| 27. xacct | 309, 323 | 311, 325 | C | Stream size-cost ratio <4.0; EXEC size-cost ratio <15.0. Exact accounting, command replies, persistence/reload state and negative controls remain. Debug jobs already disable placement controllers for reload. |
| 28. xmove | 310, 324 | 312, 326 | B | W6: LMOVE-family phase-one result held before phase-two targeted removal, with entered status and release; ordinary body change YES. ATOMIC-OFF-HOP-HOLD is Kind::Rename-only and after source mutation, so it cannot replace the 500k LREM schedule. Preserve both RPUSH and LPUSH edge oracles. Atomic-off size ratio <5.0 is also performance. |
| 29. efficiency | 328, 329, 330 | 330, 331, 332 | C | 328: trigger growth <=8x at 16x population and last-volatile DEL <=1.25x neighbour. 329: borrowed GET and plain control growth <=1.05. 330: best-of-two dispatch-excess ratio (128/4 threads) <=1.20. Exact key/TTL population, borrow/send/release counters and dispatch geometry controls remain; no threshold is relaxed. |
| 30. aclkeys | 337, 338 | 339, 340 | D | Known ACL admission/wake defects belong to aclkeys/aclkeys3 and are excluded from this lane. Retain D as the defect disposition, not a timing repair. No claim here that a branch fix is already in origin/cpp. |
| 31. debug | 339 | 341 | B | W7: DEBUG SLEEP entered/release latch with the sleeping client identity; ordinary body change NO outside the cold DEBUG SLEEP body. The existing blocked_clients gauge can miss the whole finite sleep, and does not hold same-owner progress open. |
| 32. snapshot capture/reload | 341, 342, 349, 350 | 343, 344, 351, 352 | B | W8: hold capture after its published cut and before completion, release after an acknowledged mutation; ordinary body change YES on the cold snapshot path. rdb_bgsave_in_progress alone can be missed or outlive actual capture. |
| 33. snapshot groups | 343, 344, 351, 352 | 345, 346, 353, 354 | B | W9: hold an APPLY fragment before all group fragments install, publish entry and snapshot waiting-for-apply, then release; ordinary body change YES. COMMIT-HOLD is too late: snapshot explicitly drains atomic_apply_inflight, not reply/commit latency. |
| 34. notify | 361 | 363 | A | Keep notifications configured; disable active expiry before the lazy arm. TIME witnesses the unchanged 20 ms deadline, counter must stay flat before GET, then exact expired event and +1 counter are required. Restore active expiry in finally. |
| 35. flip under load | 364 | 366 | A | Every worker acknowledges checked progress before FLIP; observe flip_completed advance, then every worker advances again. Original wrong-value, generation, BUSY, refusal and connection assertions stay; deadline expiry cannot pass. |
| 36. flip TTL | 365 | 367 | A | Fresh 96-key cohorts share an absolute deadline 700 ms after arm, avoiding an inference about owners' relative clock cuts. DEBUG SHARDS proves an owner changed and TIME bounds the post-move live read. Every key must emit its expired event and be absent; only missed live windows re-arm under a 30 s budget. |
| 37. flip saturated | 368 | 370 | B | W11: held admitted backlog spanning FLIP, with per-owner outstanding-work publication and explicit release; ordinary body change YES. Existing command totals/FLIP completion cannot prove a continuously saturated producer; cold queue queries alone would only prove sampled occupancy. |
| 38. atomic floor | 370 | 372 | C | >=120,000 MGET/MSET operations/s after 8 s warmup, delta divided by a constant 6 s. This public row has no independent key/value correctness assertion; rate and positive command activity are all it checks. |
| 39. pipeorder | 372 | 374 | A | Add a held cross-owner DEL before EXEC, require atomic_exec_order_holds/pending entries, release and compare all five exact replies. Keep all original 400 pipeline rolls and value assertions. |
| 40. kTLS live INFO | 439 | 441 | A | Read the full RESP bulk length/body/trailer across arbitrary fragmentation. tls_ktls_active >=1 remains mandatory; the 400 ms sleep and single recv are gone. |
| 41. TLS partial handshake/teardown | 443 | 445 | B | W12: per-connection received partial handshake/ciphertext/parser stage and retired state, held/released where needed; ordinary body change YES on armed TLS paths. Aggregate gauges can show admission, but cannot prove this connection reached its intended partial-record window. |
| 42. differential matrix | 515, 516 | 517, 518 | B | WAIT and CD13b GEO route windows have test-side witnesses. Aggregate remains B for W3 sampler, W13 notification fence, W14 SAVE/placement admission and W15 owner clock. Current suite inventory has 46 names; encodingfix and monitor were added after the v2 inventory. |
| 43. GT16 | 367 | 369 | A | Already landed: quiescence-gated hold and time-budgeted rerolls; unchanged in this lane. |
| 44. CD13b GEO route window | 515, 516 | 517, 518 | A | Changed: always check result count, exact members, listpack encoding and retained LFU. Only witnessed route movement or unarmed LFU/cross-owner setup re-arms fresh keys; shared 30-second per-side/per-verb failure budget. |
| 45. PSFIX SAVE admission | 515, 516 | 517, 518 | B | Reverified on current source: save-idle does not reserve placement or snapshot admission. Busy aliases a placement transition, non-Idle snapshot, and outstanding shutdown-snapshot holds; completion counters do not identify the rejected request. No generic error retry. |

## Live-observed dispositions

The archive scan includes **18 copied landing ledgers**, each with zero FAIL rows. Their logs retain historical FAIL transitions; those are distinct from the final landing verdicts. The two refused aclkeys gates add nine failed child/public ledger entries. [Landing summary](evidence/landing-summary.json), [landing excerpts](evidence/landing-ledger-excerpts.txt), [all 11,272 scanned text-file digests](evidence/landing-inputs.json.gz), [complete grep matches](evidence/landing-failures.txt.gz). Five embedded source-tree copies were excluded from the broad scan; their old documentation is not a new landing.

| Incident / retained history | Class and disposition |
|---|---|
| 2026-10-08 09:24, armed-fused geo a1 seed 23, source owner 0→6 during STORE | **A, repaired here.** CONFIG marks key-lb immutable, so runtime disabling is unavailable. Each executed STORE/STOREDIST/GEOSEARCHSTORE must preserve its exact count, listpack encoding and non-reset LFU; exact destination members are now checked too. Changed route invalidates only the route evidence and requires a fresh stable cross-owner arm. The maintainer supplied the exact incident; the copied mkprobe log retains gate-run.I4MSGw’s failed transition but not its original per-suite transcript. No transcript is fabricated. |
| 2026-10-08 05:08, split psfix a0 seed 91, Busy after idle barrier | **B/W14, unchanged.** Both-peer idle polling already exists. Current snapshot admission rejects placement transitions and other Busy states using the same wire error. INFO save completion neither identifies that reason nor reserves the next admission. A Busy-until-success loop would hide an admission defect. [Original transcript](evidence/psfix-a0-s91-original.txt), [current source evidence](evidence/psfix-admission-source.txt). |
| OPRDHt GT16 stable hold never completed within three arms; earlier cgG8qE controller hold history | **A, already repaired by flakeaudit2 / flakefix3.** Current stable_hold_attempt waits for anchored state, retains all eight pre-hold samples and checks the complete hold; re-arms share the wall budget. In-band trigger/state/split movement fails immediately. No second edit. [Refused gate log](evidence/aclkeys-failed-gates/OPRDHt/flipctl-battery.log), [21 current controls](evidence/gt16-controls.log). |
| OPRDHt/aifZYU ACL admitted wake timeouts (four differential children each) | **D, excluded by assignment.** Retained exact ledgers and all supplied per-seed logs in [aclkeys-failed-gates](evidence/aclkeys-failed-gates). aclkeys3 owns the production repair; no extra timeout or retry is added. |
| flakeaudit2 seven MULTI/EXEC held-record failures, gate-run.9MPk3h | **Withdrawn repair, excluded by assignment.** Battery was restored before this lane; existing mechanism 9 remains B/W16. A scatter commit latch is not an EXEC installed/predecision latch. |
| eviction lruclock armed a1, gate-run.cgG8qE | **A, already repaired by GT18.** All 50 touched keys must publish reset metadata; untouched controls remain old and the exact population/eviction/rejection identity holds. The real chooser has a directed serverless ordering test. Sampled survival is not silently made exact. [Landed explanation](../../MEASURE-REQUEST-flakefix3.md). |
| tracking atomic 0, gate-run.gJgZ63 | **A, retained existing repairs.** Current tracking.py witnesses redirect removal and uses fresh TTL arming plus complete invalidation frames. This archived log is a history label, not the failed assertion transcript; it does not establish which tracking arm failed. No assertion is loosened or new root cause inferred. |
| servertail split/armed both atomics, gate-run.EtkplO | **B/W1 current mechanism, unchanged.** CONFIG propagation lacks an owner-applied epoch witness. The copied history gives no assertion transcript, so the specific incident cause remains unidentified; a later green row is not a causal proof. |
| ACL battery off/on in flakeaudit’s strict-witness experiment (lh6XSg/oiQlj2) | **D, excluded production admission defect.** Timeout was interpreted as an ACL key, so BLPOP never parked. This is separate from the later admitted-wake defect. The original audit retained the witness patch and raw failure logs. |
| AOF control-frame rows, FKjO42/xSQLlF histories | **A after landed GT17 witness.** Current test uses the DEBUG writer-pause publication and exact queued-group/LargeBegin state before release, retaining no-interleave and actual deferral checks. Existing production instrumentation is not edited here. [Landed mechanism](../../MEASURE-REQUEST-flakefix.md). |
| storage regression build dependency and dependent rows, BTFBOD | **Lane build/dependency failure, excluded.** These deterministic serverless rows share a failed prerequisite in the historical storesize log; no scheduler witness is inferred from a cascading build failure. |
| Other differential aggregate/child history labels in storesize/ccfix | Aggregate remains **B**, with known lane PRE defects excluded. Copied PRE wire logs show real GEO LFU resets / ACLCAT errors; infofields PRE logs show missing fields and MONITOR differences. Those are the relevant lanes’ negative controls/defects. History-only aggregates without an assertion transcript are not assigned an invented lottery cause. |
| Nested flakefix3 live-mainline psfix timeout / shutdown dump | **Unresolved historical server/timeout evidence, no test-side retry.** It is not one of the final landing ledger rows. The log records a SAVE read timeout followed by a worker shutdown timeout, rather than the seed-91 Busy error. The current SAVE helper already derives its timeout from used memory; this lane does not claim to reproduce or cure that old shutdown. |

Negative-control failures, self-test expected rejections, body-byte audit failures, and source-text grep matches are retained in the broad scan but are not relabeled as live gate lotteries. No additional unresolved class-A mechanism with a supplied failing assertion was found beyond GEO. History-only limitations above remain explicit.

## GEO witness and falsification

Each side and verb has one 30-second monotonic failure budget. Fresh keys establish distinct shard IDs and owners plus an LFU increase of at least three. The 4096-touch priming ceiling, 4096-candidate search ceiling, stored :2 reply, integer FREQ, FREQ greater than the measured initial value and listpack encoding are retained. Every executed operation checks those semantics before any route re-arm; destination members must also be exactly a and b. Stable pre/post owner and migration-counter tuples are still required for acceptance. Owner-return/ABA migration counters invalidate the arm too. Deadline exhaustion fails, including an otherwise correct operation completed after its budget.

[Eight directed tests](evidence/geo-controls.log) cover pre-STORE movement, more than three invalid arms, source movement 0→6 during STORE, same-owner collapse, owner-return migration counters, perpetual movement, never-hot LFU, deadline exhaustion, malformed integer FREQ and bad semantic replies on stable/moved routes. The bad-result cases become healthy on a later arm deliberately; a retry would therefore fail the controls. Cleanup and CONFIG restoration are asserted.

[In-memory controls](evidence/control-results.json) run the actual wire property: the PRE owner assertion fails the migration scenario, and removing the route requirement, deadline, count, LFU, encoding or member guard fails its intended test with no unrelated exception. These are serverless controls, not live mutant-server proofs.

## Witness program and threshold limits

The ranked W1–W16 program and mixed-family limits are preserved from v2 below. No missing primitive was implemented in production. W14 was reverified against the current source; no reservation, distinct Busy reason, or SAVE admission latch became available after the persistence/multidatabase changes.

| Primitive | Rows potentially unblocked | Occurrences | Ordinary unarmed body |
|---|---|---:|---|
| W1 — Per-owner applied live-config version query | 132, 149, 166, 183, 215, 232, 250, 267, 300, 314, 358 | 11 | NO: return existing IO/ex cached versions by owner-local cold DEBUG work, avoiding an unsafe foreign read of a plain field. |
| W5 — Controlled timeout/cron stage with client identity and release | 132, 139, 166, 173, 215, 222, 250, 257, 358 | 9 | YES: deadline/cron progression while DEBUG armed; needed alongside W1 for blocking's config arm. |
| W3 — Controlled sampler traversal with completion witness | 130, 164, 199, 206, 213, 248, 515, 516 | 8 | YES: only when DEBUG armed; both peer oracles need a deterministic coverage construction, not extra random draws. |
| W2 — Held read cut / first fanout fragment / reader publication stage | 126, 128, 303, 304, 317, 318, 503 | 7 | YES: entered/release checks in the existing armed debug path; specify stage separately for fanout and hazard arms. |
| W16 — EXEC installed/predecision latch with identity, owner/key counts and explicit release | 131, 165, 200, 207, 214, 249, 357 | 7 | YES: park the transaction finalizer after all installs and before its direct atomic_commit_group call, without blocking owners. The scatter commit-queue latch does not cover EXEC. |
| W4 — Held command expiry cut, including local MGET, EXEC and script | 159, 193, 242, 277 | 4 | YES: stage publication and explicit release on the relevant read/transaction paths. |
| W8 — Snapshot capture-cut entered/hold/release | 341, 342, 349, 350 | 4 | YES, snapshot path only; independent mutation ACK must precede capture release. |
| W9 — Atomic APPLY-fragment hold plus snapshot apply-drain state | 343, 344, 351, 352 | 4 | YES: commit-decision hold is not equivalent to partial apply. |
| W10 — Per-client parser parked-on-partial-frame publication | 122, 203, 210, 366 | 4 | YES: publish the armed client's parser stage before starting the unchanged counter window. |
| W6 — LMOVE phase-one selected-value hold before phase-two removal | 310, 324 | 2 | YES: extend the correct LMOVE-family stage, not the RENAME mutation hold. |
| W13 — Producer-to-tracking-consumer delivery fence | 515, 516 | 2 | YES: a fence must cover the async notification path. Ordinary ECHO/PUBLISH alone can overtake that path and cannot prove a zero-event leg drained. |
| W14 — Snapshot/placement admission reservation with entered/release state | 515, 516 | 2 | YES on cold snapshot/placement admission; expose which Busy condition fired and hold admission until the intended SAVE is admitted. |
| W15 — Owner-local stream clock/cut observation | 515, 516 | 2 | NO outside a cold DEBUG query of the actual owner's cached clock. IO-side TIME need not bound an earlier owner pass; keep monotonic IDs and verify the command cut without an arbitrary clock tolerance. |
| W7 — DEBUG SLEEP entered/release latch | 339 | 1 | NO ordinary operation body change: all new work can remain inside the cold DEBUG SLEEP mechanism. |
| W11 — Admitted outstanding traffic spanning completed FLIP | 368 | 1 | YES for an armed admitted-backlog latch and release. The sustained-saturation claim still needs its own instrument; a cold queue query only proves sampled occupancy. |
| W12 — Per-TLS-connection partial input and teardown stage | 443 | 1 | YES on the armed TLS/parser path; global handshakes/ciphertext counters are insufficient. |

## Threshold and mixed-family limitations

C mechanisms remain untouched: no tolerance widening, assertion removal, row split or EXPECT edit. For mainline separation, keep each listed correctness assertion in the gate and report the threshold with matched-load/stationarity evidence. Resource-budget checks are listed explicitly rather than mislabeled as latency. Mixed B rows also retain their bounds:

- spinprobe: per one-second window, idle IO/fused iterations <=64, spins <=64, combined wakes <=64; split ex spins <=2048*(ceil(1000/50)+64+4)=180224 and iterations <=180288. Partial-frame excess iterations <=24, spins <=8, sent wakes <=8 and received wakes <=8. Exact completed partial-frame +OK and stable thread roles remain; parser publication alone does not prove these performance budgets.
- blocking: 0.10 <= elapsed <=0.75 s for both 150 ms timeout legs; nulls and untouched tail remain.
- atomic_hazards: unarmed XREAD must complete before half of the 200,000 us delay (100 ms); other elapsed lower bounds are attempts to infer an open stage, not a stage witness.
- xmove: atomic-off large/small LMOVE ratio <5.0 remains beside exact selected-edge preservation.
- atomic_torn's release promotion-drain ceiling is <=1.5 s with positive holds, predecessor reads and promotions plus an exact final group. The separate stage-count arms in atomic_torn/execatomic/execiso need W2 before their budgets can serve solely as failure deadlines.
- DEBUG SLEEP .5 currently requires same-owner progress and cancellation admission within .30 s, no reply before .40 s, and cancellation drain within .30 s. The parked gauge, exact OK/PONG order and restored gauge must remain when a latch separates its scheduling window.
- repaired HEXPIRE keeps its independent long-TTL rounding/range assertions; the registered short live-field race was repaired, not every possible clock dependence in that battery.

## Differential suite expansion

Each currently discovered suite is listed once. The previous 44 names remain; encodingfix and monitor bring the current total to 46. Whole selected gate jobs retain every seed and suite. No suite filter is used for live proof.

| Suite | Disposition |
|---|---|
| string | Unchanged; retain the prior audit assessment and exact assertions. |
| list | Unchanged; retain the prior audit assessment and exact assertions. |
| set | Unchanged; retain the prior audit assessment and exact assertions. |
| zset | Unchanged; retain the prior audit assessment and exact assertions. |
| hash | Unchanged; retain the prior audit assessment and exact assertions. |
| hexpire | Unchanged; retain the prior audit assessment and exact assertions. |
| edgetime | Unchanged; retain the prior audit assessment and exact assertions. |
| xshard | Unchanged; retain the prior audit assessment and exact assertions. |
| xmove | Unchanged; retain the prior audit assessment and exact assertions. |
| bitmap | Unchanged; retain the prior audit assessment and exact assertions. |
| hll | Unchanged; retain the prior audit assessment and exact assertions. |
| bitfield | Unchanged; retain the prior audit assessment and exact assertions. |
| cgaps | Unchanged; retain the prior audit assessment and exact assertions. |
| stream | B/W15 owner clock/cut witness still missing. |
| script | Unchanged; retain the prior audit assessment and exact assertions. |
| streamgrp | Unchanged; retain the prior audit assessment and exact assertions. |
| zsetops | Unchanged; retain the prior audit assessment and exact assertions. |
| geo | A submechanism repaired here: migration-aware route rearming with all destination semantics checked. |
| doubles | Unchanged; retain the prior audit assessment and exact assertions. |
| scan | Unchanged; retain the prior audit assessment and exact assertions. |
| multi | Unchanged; retain the prior audit assessment and exact assertions. |
| encodingfix | Unchanged landed encoding grammar/storage comparisons; additional suite since v2. |
| edgeenc | Unchanged; retain the prior audit assessment and exact assertions. |
| edgeproto | Unchanged; retain the prior audit assessment and exact assertions. |
| cmdgap | Unchanged; retain the prior audit assessment and exact assertions. |
| cmdgap2 | Unchanged; retain the prior audit assessment and exact assertions. |
| sort | Unchanged; retain the prior audit assessment and exact assertions. |
| servertail | Unchanged; retain the prior audit assessment and exact assertions. |
| arity | Unchanged; retain the prior audit assessment and exact assertions. |
| storeorder | Unchanged; retain the prior audit assessment and exact assertions. |
| infofix | Unchanged; retain the prior audit assessment and exact assertions. |
| multidb | Unchanged; retain the prior audit assessment and exact assertions. |
| blocking | Retain landed A WAIT parked-ID/deadline witnesses. |
| pubsub | Unchanged; retain the prior audit assessment and exact assertions. |
| fanout | Unchanged; retain the prior audit assessment and exact assertions. |
| spubsub | Unchanged; retain the prior audit assessment and exact assertions. |
| notify | Unchanged; retain the prior audit assessment and exact assertions. |
| wiredump | Unchanged; retain the prior audit assessment and exact assertions. |
| climon | B/W13 producer-to-consumer notification fence still missing. |
| compatintro | Unchanged; retain the prior audit assessment and exact assertions. |
| aclsel | Unchanged; retain the prior audit assessment and exact assertions. |
| cmdmeta | Unchanged; retain the prior audit assessment and exact assertions. |
| s6fix | B/W3 random sampler coverage still lacks controlled traversal. |
| ccfix | Unchanged; retain the prior audit assessment and exact assertions. |
| psfix | B/W14 reverified: idle/completion observation is not admission reservation. |
| monitor | Unchanged landed INFO/monitor semantics checks; additional suite since v2. |
