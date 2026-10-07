# Remaining mechanisms, second audit

This table preserves all 42 mechanisms and 117 distinct public row occurrences from [remaining.md](../flakeaudit/remaining.md). That file and its original inventory are unchanged. The separate GT16 addendum is row 367; PSFIX is inside existing rows 515/516 and is not double-counted.

FIXED-TEST-SIDE means the test change is implemented, **not a live proof claim**. Each changed occurrence requires the selected campaign and its complete battery. The category is the disposition of the registered mechanism; other retained checks are called out, and no entire battery is claimed lottery-free without its proof.

Selected proof: REFUSED (`selected-20261007T222606Z`, four quiet admissions; no gate run id). Run ids: none.
Full iteration: REFUSED (`full-20261007T223724Z`, four quiet admissions; no gate run id). Run id: none.

Original-register occurrences: A=42, B=51, C=22, D=2 (117). Including GT16: A=43, B=51, C=22, D=2 (118).

| Mechanism | Public ordinals | New status | Mechanism, preserved oracle, or minimal primitive |
|---|---|---|---|
| 1. netio | 47, 48 | PERF-THRESHOLD | Wake latency <25 ms; exact blocked-client identity and delivered value remain correctness facts. |
| 2. torture | 118, 501 | FIXED-TEST-SIDE | Unique churn keys; observer GET witnesses each SET before RST, with the writer reply unread and partial next frame retained. Final landed-key assertion and every transport error remain. Proof: selected campaign above; serverless controls are separate evidence. |
| 3. ryow | 119, 502 | FIXED-TEST-SIDE | All four background writers acknowledge progress and propagate errors. Added explicit same-key overwrites with an allowed-conflict value set, followed by exact uncontended RYOW; original own-key checks retained. Proof: selected campaign above; serverless controls are separate evidence. |
| 4. spinprobe | 122, 203, 210, 366 | NEEDS-WITNESS | W10: per-client parser-park state, observed before the counter interval; ordinary body change YES. Existing LBSIGNALS lacks this state. Counter budgets also need a separate performance instrument (see threshold appendix). |
| 5. atomic_torn | 126, 503 | NEEDS-WITNESS | W2: held read-cut/lead-fragment stage with entered/released status; ordinary body change YES. The existing RENAME hold and commit latch do not force the other fanout/promotion windows. |
| 6. atomic_ryow | 127, 504 | PERF-THRESHOLD | Pipeline rate >1.10 times serial rate (24 groups, release only). Exact ACKs, ordered reads, consistent-or-absent values and positive worker/cut counts remain. ASAN omits the rate assertion but still has finite stress floors; a held overlap is also needed before claiming those arms witnessed. |
| 7. atomic_hazards | 128 | NEEDS-WITNESS | W2: publish and hold the exact pinned-cut/reader and dispatch stages; ordinary body change YES. Finite delays plus elapsed observations cannot identify those stages; unarmed XREAD <100 ms is a performance control. |
| 8. s6 | 130, 164, 199, 206, 213, 248 | NEEDS-WITNESS | W3: DEBUG-controlled sampler traversal/seed with a required traversal-complete witness; ordinary body change YES in the armed sampler branch. Keep exact all-200-key coverage; 20,000 random draws alone cannot guarantee it. |
| 9. multi_exec | 131, 165, 200, 207, 214, 249, 357 | FIXED-TEST-SIDE | ATOMIC-COMMIT-HOLD forces an undecided EXEC on two real owners; MGET must read all eight predecessors and then all eight committed values. The remaining stress ends only after its original read/commit/cut floors, with a deadline that can only fail. Proof: selected campaign above; serverless controls are separate evidence. |
| 10. blocking | 132, 166, 215, 250, 358 | NEEDS-WITNESS | W1 plus W5: applied per-owner config epoch and controlled finite-blocker deadline/retirement; ordinary body changes NO for owner-local config query, YES for an armed clock/lifecycle latch. Exact null/data/gauges stay; two 0.10..0.75 s bounds also mix timing into correctness. |
| 11. blockmulti | 133, 167, 216, 251 | PERF-THRESHOLD | EXEC completion <250 ms; satisfied WAIT <100 ms; WAIT 200 in 150..900 ms; pipeline WAIT 120 >=90 ms. Exact EXEC results, WAIT :0, younger PONG order, parked/drained gauges and timeout-zero silence remain. Deadline lower bounds express semantics; the upper ceilings are performance. |
| 12. stream | 134, 168, 217, 252 | PERF-THRESHOLD | Current source gates footprint, not the old register's sampled latency: plateau growth <=8192 B, post-delete <=baseline+4096 B, 0<B/key<512, 128-entry usage<25,600 B. Exact last-100 payloads, all 128 migration entries, DBSIZE and positive allocation remain. Empty-stream timeout >=80 ms is separate deadline semantics. |
| 13. limits | 139, 173, 222, 257 | NEEDS-WITNESS | W5: DEBUG-held cron/timeout progression with fired and retired client identity; ordinary body change YES. CLIENT LIST already witnesses admission/closure, but not the soft-limit/idle deadline crossing while the test's heartbeat was descheduled. |
| 14. climon2 | 146, 180, 229, 264 | PERF-THRESHOLD | PAUSE WRITE read <250 ms, held write >300 ms, UNPAUSE elapsed <2000 ms. Exact GET/SET replies, positive client_pause_holds, ALL-mode silence and released reply remain. A held pause/deadline stage would separate the >300 ms mechanism claim from the clock. |
| 15. tracking | 147, 181, 230, 265 | FIXED-TEST-SIDE | Fresh client/key and bounded TTL registration; the 300 ms negative drain occurs before arming the unchanged 400 ms TTL. Positive invalidation is read as a complete exact RESP frame; expired value must be absent. Proof: selected campaign above; serverless controls are separate evidence. |
| 16. hexpire | 148, 182, 231, 266 | FIXED-TEST-SIDE | Recreate only clock-invalid short-field setup; HPEXPIRE and HPEXPIRETIME share one EXEC cut so the actual installed deadline is captured before it can expire. TIME bounds subsequent counters/HLEN. Lazy arm disables active expiry and requires the exact reap delta; active baseline precedes TTL installation. Other numeric tolerances are unchanged. Proof: selected campaign above; serverless controls are separate evidence. |
| 17. servertail | 149, 183, 232, 267 | NEEDS-WITNESS | W1: query each owner's already-applied live-config version before OBJECT policy checks; ordinary body change NO if queried on that owner through cold DEBUG work. TIME's +/-60 s allowance is an additional clock oracle, not evidence of config publication. |
| 18. concur | 151, 185, 234, 269 | FIXED-TEST-SIDE | Every churn batch is acknowledged while a nonzero SCAN cursor is open. Growth/cardinality/rehash and exact permanent-set assertions remain; callbacks no longer count mutation after cursor completion. Proof: selected campaign above; serverless controls are separate evidence. |
| 19. edgetime | 154, 188, 237, 272 | FIXED-TEST-SIDE | Fresh 70/80 ms absolute-deadline queue/WATCH setup must complete before that deadline; missed setups DISCARD/UNWATCH and recreate state within a budget. PEXPIRETIME must equal the armed deadline; wait for it before EXEC. Exact null/abort/reap and negative controls remain. Proof: selected campaign above; serverless controls are separate evidence. |
| 20. expwide | 159, 193, 242, 277 | NEEDS-WITNESS | W4: publish a pinned command/transaction expiry cut and hold before the later owner/read until explicit release (including read-local and script/EXEC variants); ordinary body change YES. Existing ATOMIC-FANOUT-DEFER is a finite duration with no entered-stage publication. |
| 21. pushtear | 161, 195, 244, 279 | FIXED-TEST-SIDE | Exact CLIENT ID must be blocked before PUBLISH; require its ACK before the unchanged one-second deadline. Fresh connections only on missed arming. The two complete frames must retain push/null order and the segment-counter assertion. Proof: selected campaign above; serverless controls are separate evidence. |
| 22. read-local high water | 246, 281 | FIXED-TEST-SIDE | Per-battery INFO high water survives RESETSTAT, following differ_gate.sh. A malformed/missing counter latches failure; no synthetic local reads are added. Positive peak remains required at shutdown. Proof: selected campaign above; serverless controls are separate evidence. |
| 23. aclreply | 294, 295 | FIXED-TEST-SIDE | Exact blocked CLIENT ID, fresh finite timeout arms, acknowledged ACL revocation, and an ECHO reply fence. Compare the entire raw stream, including a duplicate coded null if present, to the original expected reply. Proof: selected campaign above; serverless controls are separate evidence. |
| 24. slowlog | 300, 314 | NEEDS-WITNESS | W1: applied config epoch on every IO/ex owner before recorder assertions; ordinary body change NO for cold owner-local queries. The existing 200 ms propagation sleep is not that acknowledgement. |
| 25. execatomic / execiso | 303, 304, 317, 318 | NEEDS-WITNESS | W2: hold a published first fragment and pinned read cut until explicit release; ordinary body change YES. ATOMIC-COMMIT-HOLD covers installed records, not this read-fanout lead-fragment schedule. |
| 26. multires | 306, 320 | FIXED-TEST-SIDE | First positive atomic-on round holds a real undecided predecessor and requires atomic_exec_order_holds plus pending entries before release. Existing ACK/value/probe assertions, remaining rounds and negative/atomic-off controls stay. Proof: selected campaign above; serverless controls are separate evidence. |
| 27. xacct | 309, 323 | PERF-THRESHOLD | Stream size-cost ratio <4.0; EXEC size-cost ratio <15.0. Exact accounting, command replies, persistence/reload state and negative controls remain. Debug jobs already disable placement controllers for reload. |
| 28. xmove | 310, 324 | NEEDS-WITNESS | W6: LMOVE-family phase-one result held before phase-two targeted removal, with entered status and release; ordinary body change YES. ATOMIC-OFF-HOP-HOLD is Kind::Rename-only and after source mutation, so it cannot replace the 500k LREM schedule. Preserve both RPUSH and LPUSH edge oracles. Atomic-off size ratio <5.0 is also performance. |
| 29. efficiency | 328, 329, 330 | PERF-THRESHOLD | 328: trigger growth <=8x at 16x population and last-volatile DEL <=1.25x neighbour. 329: borrowed GET and plain control growth <=1.05. 330: best-of-two dispatch-excess ratio (128/4 threads) <=1.20. Exact key/TTL population, borrow/send/release counters and dispatch geometry controls remain; no threshold is relaxed. |
| 30. aclkeys | 337, 338 | PRODUCTION-DEFECT | Restricted BLPOP timeout is treated as a key before parking. Leave 337/338 to aclkeys; retain the first audit's witness patch and failure logs, and require mainline's strict parked-client witness on the eventual production fix. |
| 31. debug | 339 | NEEDS-WITNESS | W7: DEBUG SLEEP entered/release latch with the sleeping client identity; ordinary body change NO outside the cold DEBUG SLEEP body. The existing blocked_clients gauge can miss the whole finite sleep, and does not hold same-owner progress open. |
| 32. snapshot capture/reload | 341, 342, 349, 350 | NEEDS-WITNESS | W8: hold capture after its published cut and before completion, release after an acknowledged mutation; ordinary body change YES on the cold snapshot path. rdb_bgsave_in_progress alone can be missed or outlive actual capture. |
| 33. snapshot groups | 343, 344, 351, 352 | NEEDS-WITNESS | W9: hold an APPLY fragment before all group fragments install, publish entry and snapshot waiting-for-apply, then release; ordinary body change YES. COMMIT-HOLD is too late: snapshot explicitly drains atomic_apply_inflight, not reply/commit latency. |
| 34. notify | 361 | FIXED-TEST-SIDE | Keep notifications configured; disable active expiry before the lazy arm. TIME witnesses the unchanged 20 ms deadline, counter must stay flat before GET, then exact expired event and +1 counter are required. Restore active expiry in finally. Proof: selected campaign above; serverless controls are separate evidence. |
| 35. flip under load | 364 | FIXED-TEST-SIDE | Every worker acknowledges checked progress before FLIP; observe flip_completed advance, then every worker advances again. Original wrong-value, generation, BUSY, refusal and connection assertions stay; deadline expiry cannot pass. Proof: selected campaign above; serverless controls are separate evidence. |
| 36. flip TTL | 365 | FIXED-TEST-SIDE | Fresh 96-key cohorts share an absolute deadline 700 ms after arm, avoiding an inference about owners' relative clock cuts. DEBUG SHARDS proves an owner changed and TIME bounds the post-move live read. Every key must emit its expired event and be absent; only missed live windows re-arm under a 30 s budget. Proof: selected campaign above; serverless controls are separate evidence. |
| 37. flip saturated | 368 | NEEDS-WITNESS | W11: held admitted backlog spanning FLIP, with per-owner outstanding-work publication and explicit release; ordinary body change YES. Existing command totals/FLIP completion cannot prove a continuously saturated producer; cold queue queries alone would only prove sampled occupancy. |
| 38. atomic floor | 370 | PERF-THRESHOLD | >=120,000 MGET/MSET operations/s after 8 s warmup, delta divided by a constant 6 s. This public row has no independent key/value correctness assertion; rate and positive command activity are all it checks. |
| 39. pipeorder | 372 | FIXED-TEST-SIDE | Add a held cross-owner DEL before EXEC, require atomic_exec_order_holds/pending entries, release and compare all five exact replies. Keep all original 400 pipeline rolls and value assertions. Proof: selected campaign above; serverless controls are separate evidence. |
| 40. kTLS live INFO | 439 | FIXED-TEST-SIDE | Read the full RESP bulk length/body/trailer across arbitrary fragmentation. tls_ktls_active >=1 remains mandatory; the 400 ms sleep and single recv are gone. Proof: selected campaign above; serverless controls are separate evidence. |
| 41. TLS partial handshake/teardown | 443 | NEEDS-WITNESS | W12: per-connection received partial handshake/ciphertext/parser stage and retired state, held/released where needed; ordinary body change YES on armed TLS paths. Aggregate gauges can show admission, but cannot prove this connection reached its intended partial-record window. |
| 42. differential matrix | 515, 516 | NEEDS-WITNESS | WAIT now uses exact parked IDs on both peers and fresh finite deadline arms. Remaining W3 sampler, W13 notification delivery fence, W14 SAVE/placement admission and W15 owner-clock witness block full reclassification. Ordinary body changes YES for W3/W13/W14, NO outside cold DEBUG for W15. Suite expansion below retains all 44 names. |

## Priority addenda

**GT16, row 367 — FIXED-TEST-SIDE (A).** `stable_hold_attempt` starts pre-hold sampling only after `flipctl_state=anchored`. It retains all eight pre-hold samples and the entire requested hold length. Driver excursions invalidate an arm; fresh arms share the existing `4*seconds+60` wall budget. There is no three-attempt cap. Every valid in-band hold sample checks trigger, state and anchor split; a move immediately fails and cannot be retried. Exhaustion is INVALID/failure, never PASS. Published bands and all thresholds are unchanged. The 21 serverless controls include deliberately moved trigger/state/split, a 90-second settle, more than three invalid windows and never-quiescent/short-budget controls. These mutate observed published state, not a live controller binary. Live six-run proof remains pending if admission was refused; no live mutant binary was run. [Original GT16 failure](evidence/gt16-OPRDHt-original.log).

**PSFIX seed 91, rows 515/516 — NEEDS-WITNESS (B), W14.** The suggested both-peer `rdb_bgsave_in_progress:0` poll already exists in `psfix_wait_idle` (10-second bounded loop). `SnapshotManager::start` also returns Busy when placement is transitioning; `snapshot_command` maps that Busy to the same `Background save already in progress` error. The retained failure does not identify which admission condition raced. Another idle poll does not reserve admission. No error-retry loop or weakened SAVE comparison was added; the original exact reply and +1 save count remain. [Original failing transcript](evidence/psfix-a0-s91-original.txt). W14 requires a placement/snapshot admission lease or stage latch, and a distinct reason/status; it changes the cold ordinary admission body. This is an instrumentation gap, not a claim that the transcript proves a production data defect.

## New witness program, ranked by affected occurrences

Counts are the union of row ordinals depending on each primitive, not additive landing counts. Some rows need multiple primitives or still contain a performance threshold. NO means no ordinary operation gains a new observation/check; cold DEBUG dispatch may change. A proposal must still pass the owner's layout/performance review; this lane implements none of them.

| Primitive | Rows potentially unblocked | Occurrences | Ordinary unarmed body |
|---|---|---:|---|
| W1 — Per-owner applied live-config version query | 132, 149, 166, 183, 215, 232, 250, 267, 300, 314, 358 | 11 | NO: return existing IO/ex cached versions by owner-local cold DEBUG work, avoiding an unsafe foreign read of a plain field. |
| W5 — Controlled timeout/cron stage with client identity and release | 132, 139, 166, 173, 215, 222, 250, 257, 358 | 9 | YES: deadline/cron progression while DEBUG armed; needed alongside W1 for blocking's config arm. |
| W3 — Controlled sampler traversal with completion witness | 130, 164, 199, 206, 213, 248, 515, 516 | 8 | YES: only when DEBUG armed; both peer oracles need a deterministic coverage construction, not extra random draws. |
| W2 — Held read cut / first fanout fragment / reader publication stage | 126, 128, 303, 304, 317, 318, 503 | 7 | YES: entered/release checks in the existing armed debug path; specify stage separately for fanout and hazard arms. |
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

One suite per line, no additional public rows. The original review remains available in [differ-reviews.json](../flakeaudit/differ-reviews.json). Only the WAIT submechanism changed here. All 44 suites are included through the selected differential jobs; their aggregate public rows remain B until the listed residuals are resolved.

| Suite | Disposition in this lane |
|---|---|
| string | Unchanged; retain first audit's DETERMINISTIC assessment. |
| list | Unchanged; retain first audit's DETERMINISTIC assessment. |
| set | Unchanged; retain first audit's DETERMINISTIC assessment. |
| zset | Unchanged; retain first audit's DETERMINISTIC assessment. |
| hash | Unchanged; retain first audit's DETERMINISTIC assessment. |
| hexpire | Unchanged; retain first audit's DETERMINISTIC assessment. |
| edgetime | Unchanged; retain first audit's DETERMINISTIC assessment. |
| xshard | Unchanged; retain first audit's DETERMINISTIC assessment. |
| xmove | Unchanged; retain first audit's DETERMINISTIC assessment. |
| bitmap | Unchanged; retain first audit's DETERMINISTIC assessment. |
| hll | Unchanged; retain first audit's DETERMINISTIC assessment. |
| bitfield | Unchanged; retain first audit's DETERMINISTIC assessment. |
| cgaps | Unchanged; retain first audit's DETERMINISTIC assessment. |
| stream | B / W15: owner-clock cut needed for auto IDs; existing +/-10 s wall allowance unchanged. |
| script | Unchanged; retain first audit's DETERMINISTIC assessment. |
| streamgrp | Unchanged; retain first audit's DETERMINISTIC assessment. |
| zsetops | Unchanged; retain first audit's DETERMINISTIC assessment. |
| geo | Unchanged; retain first audit's BOUNDED-WITNESSED assessment. |
| doubles | Unchanged; retain first audit's DETERMINISTIC assessment. |
| scan | Unchanged; retain first audit's DETERMINISTIC assessment. |
| multi | Unchanged; retain first audit's DETERMINISTIC assessment. |
| edgeenc | Unchanged; retain first audit's DETERMINISTIC assessment. |
| edgeproto | Unchanged; retain first audit's DETERMINISTIC assessment. |
| cmdgap | Unchanged; retain first audit's DETERMINISTIC assessment. |
| cmdgap2 | Unchanged; retain first audit's DETERMINISTIC assessment. |
| sort | Unchanged; retain first audit's DETERMINISTIC assessment. |
| servertail | Unchanged; retain first audit's DETERMINISTIC assessment. |
| arity | Unchanged; retain first audit's DETERMINISTIC assessment. |
| storeorder | Unchanged; retain first audit's DETERMINISTIC assessment. |
| infofix | Unchanged; retain first audit's BOUNDED-WITNESSED assessment. |
| multidb | Unchanged; retain first audit's BOUNDED-WITNESSED assessment. |
| blocking | WAIT finite/zero exact parked-client arms repaired (A submechanism); exact replies and silence preserved. |
| pubsub | Unchanged; retain first audit's BOUNDED-WITNESSED assessment. |
| fanout | Unchanged; retain first audit's BOUNDED-WITNESSED assessment. |
| spubsub | Unchanged; retain first audit's BOUNDED-WITNESSED assessment. |
| notify | Unchanged; retain first audit's BOUNDED-WITNESSED assessment. |
| wiredump | Unchanged; retain first audit's DETERMINISTIC assessment. |
| climon | B / W13: idle delimiters do not fence asynchronously produced tracking pushes. |
| compatintro | Unchanged; retain first audit's BOUNDED-WITNESSED assessment. |
| aclsel | Unchanged; retain first audit's DETERMINISTIC assessment. |
| cmdmeta | Unchanged; retain first audit's DETERMINISTIC assessment. |
| s6fix | B / W3: all-200-key RANDOMKEY coverage still probabilistic. |
| ccfix | Unchanged; retain first audit's BOUNDED-WITNESSED assessment. |
| psfix | B / W14: observed both-peer save idle does not reserve placement/snapshot admission. |
