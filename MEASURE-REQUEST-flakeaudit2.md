# flakeaudit2 measurement and proof request

Test-side changes are committed on `cx-flakeaudit2`; no push. Production is unchanged relative to the final fetched/merged `origin/cpp`. **No live pass is claimed without the receipts below.**

Rows +0/+0; EXPECT remains **500 quick / 517 full**. Public names/order/multiplicity match the first audit exactly; [row-count receipt](docs/flakeaudit2/evidence/row-counts.txt). [Production diff receipt](docs/flakeaudit2/evidence/production.diff) is empty. [Final merge receipt](docs/flakeaudit2/evidence/final-merge.txt).

Selected proof: PENDING (`selected-20261007T222606Z`; 0/6 completed). Run ids: none.
Full `tests/gate.sh iteration`: NOT RUN. Run id: none.

The extension [proof.py](docs/flakeaudit2/proof.py) follows `docs/flakeaudit/repeat.sh`: whole jobs, six serial runs, fail on any failed run/FAIL row, compare server SHA before/after, preserve raw logs/ledgers and textual job artifacts in committed evidence. Selected runs are deliberately partial and never labeled full gate receipts. Each admission uses the unchanged quiet monitor, one initial screen plus at most three retries at 200-second spacing. Refusal is recorded and does not launch a compiler, server or load generator. Failed tests are never retried to obtain a pass. Server CPUs 112-119, load CPUs 120-127, build affinity 112-127, ports 18340-18342.

Re-proof on the maintainer's idle box (merge origin/cpp first):

```sh
python3 docs/flakeaudit2/proof.py selected
python3 docs/flakeaudit2/proof.py full
python3 docs/flakeaudit2/report.py
git add docs/flakeaudit2/evidence docs/flakeaudit2/remaining-v2.md docs/flakeaudit2/triage.json MEASURE-REQUEST-flakeaudit2.md
git commit -m 'Record flakeaudit2 idle-box proof'
```

No PRE/POST/PAD arm: this lane changes no production code or layout and makes no throughput claim. The instrument's verdict is six rc=0 selected runs with 0 FAIL across every changed battery, plus one full iteration with 0 gating FAIL. A refusal leaves this requirement pending.

## Implemented repairs

All entries below share the selected campaign status above; the row numbers are public ordinals, not Python assertion counts.

| Public rows | Mechanism | Proof |
|---|---|---|
| 367 | GT16: quiescent arm, time-budget invalid windows, full-length in-band hold; valid movement fails immediately | 21 serverless classifier/schedule controls; live campaign above |
| 118, 501 | torture: Unique churn keys; observer GET witnesses each SET before RST, with the writer reply unread and partial next frame retained. Final landed-key assertion and every transport error remain. | Selected campaign above |
| 119, 502 | ryow: All four background writers acknowledge progress and propagate errors. Added explicit same-key overwrites with an allowed-conflict value set, followed by exact uncontended RYOW; original own-key checks retained. | Selected campaign above |
| 131, 165, 200, 207, 214, 249, 357 | multi_exec: ATOMIC-COMMIT-HOLD forces an undecided EXEC on two real owners; MGET must read all eight predecessors and then all eight committed values. The remaining stress ends only after its original read/commit/cut floors, with a deadline that can only fail. | Selected campaign above |
| 147, 181, 230, 265 | tracking: Fresh client/key and bounded TTL registration; the 300 ms negative drain occurs before arming the unchanged 400 ms TTL. Positive invalidation is read as a complete exact RESP frame; expired value must be absent. | Selected campaign above |
| 148, 182, 231, 266 | hexpire: Recreate only clock-invalid short-field setup, with TIME/HPEXPIRETIME and pre-expiry counters/HLEN. Lazy arm explicitly disables active expiry, then requires the exact lazy reap delta; active arm takes its baseline before TTL installation. Numeric tolerances elsewhere in the battery are unchanged. | Selected campaign above |
| 151, 185, 234, 269 | concur: Every churn batch is acknowledged while a nonzero SCAN cursor is open. Growth/cardinality/rehash and exact permanent-set assertions remain; callbacks no longer count mutation after cursor completion. | Selected campaign above |
| 154, 188, 237, 272 | edgetime: Fresh 70/80 ms queue/WATCH setup must complete before the server deadline; missed setups DISCARD/UNWATCH and recreate state within a budget. Wait for the actual PEXPIRETIME before EXEC; exact null/abort/reap and negative controls remain. | Selected campaign above |
| 161, 195, 244, 279 | pushtear: Exact CLIENT ID must be blocked before PUBLISH; require its ACK before the unchanged one-second deadline. Fresh connections only on missed arming. The two complete frames must retain push/null order and the segment-counter assertion. | Selected campaign above |
| 246, 281 | read-local high water: Per-battery INFO high water survives RESETSTAT, following differ_gate.sh. A malformed/missing counter latches failure; no synthetic local reads are added. Positive peak remains required at shutdown. | Selected campaign above |
| 294, 295 | aclreply: Exact blocked CLIENT ID, fresh finite timeout arms, acknowledged ACL revocation, and an ECHO reply fence. Compare the entire raw stream, including a duplicate coded null if present, to the original expected reply. | Selected campaign above |
| 306, 320 | multires: First positive atomic-on round holds a real undecided predecessor and requires atomic_exec_order_holds plus pending entries before release. Existing ACK/value/probe assertions, remaining rounds and negative/atomic-off controls stay. | Selected campaign above |
| 361 | notify: Keep notifications configured; disable active expiry before the lazy arm. TIME witnesses the unchanged 20 ms deadline, counter must stay flat before GET, then exact expired event and +1 counter are required. Restore active expiry in finally. | Selected campaign above |
| 364 | flip under load: Every worker acknowledges checked progress before FLIP; observe flip_completed advance, then every worker advances again. Original wrong-value, generation, BUSY, refusal and connection assertions stay; deadline expiry cannot pass. | Selected campaign above |
| 365 | flip TTL: Fresh 96-key cohorts retain 700 ms TTL. DEBUG SHARDS proves at least one owner changed, TIME proves all keys remain alive after that move, then every cohort key must emit its expired event and be absent. Missed live windows alone re-arm under a 30 s budget. | Selected campaign above |
| 372 | pipeorder: Add a held cross-owner DEL before EXEC, require atomic_exec_order_holds/pending entries, release and compare all five exact replies. Keep all original 400 pipeline rolls and value assertions. | Selected campaign above |
| 439 | kTLS live INFO: Read the full RESP bulk length/body/trailer across arbitrary fragmentation. tls_ktls_active >=1 remains mandatory; the 400 ms sleep and single recv are gone. | Selected campaign above |
| 515, 516 (partial repair) | Differential WAIT: both exact clients parked, unchanged 200 ms deadline/50 ms silence arm; fresh connections on missed setup, exact :0 result | Selected differential jobs; aggregate rows remain B |

Serverless evidence: [GT16](docs/flakeaudit2/evidence/gt16-controls.txt), [11 fragmentation/high-water/expiry/atomic negative controls](docs/flakeaudit2/evidence/test-side-controls.txt). The deliberate GT16 controls inject trigger, state and anchor-split movement during an otherwise valid hold, each failing immediately without a re-roll. Other controls reject missing atomic installation, disabled holds, private values, truncated frames, duplicate coded ACL replies, never-live TTL arms and absent/malformed lane counters. They do not replace live six-run or broken-controller-binary receipts; quiet refusals prevent that claim.

## Full triage

[remaining-v2.md](docs/flakeaudit2/remaining-v2.md) contains all 42 original mechanisms, the GT16 and PSFIX addenda, exact residual thresholds, and 44 differential suites one per line.

| Category | Mechanisms in original 42 | Row occurrences |
|---|---:|---:|
| A — FIXED-TEST-SIDE | 16 | 42 |
| B — NEEDS-WITNESS | 17 | 51 |
| C — PERF-THRESHOLD | 8 | 22 |
| D — PRODUCTION-DEFECT | 1 | 2 |

GT16 adds one A mechanism/occurrence: **43 A + 51 B + 22 C + 2 D = 118 distinct scoped occurrences**. PSFIX and the WAIT partial repair are within rows 515/516 and add zero occurrences. 45 distinct public occurrences were edited (42 original A, GT16, and the two partially repaired differential rows), without adding public rows.

## Ranked class-B primitives

Counts overlap; implementing one primitive does not prove an entire mixed battery.

| Primitive | Occurrences | Exact row family | Ordinary body change |
|---|---:|---|---|
| W1 — Per-owner applied live-config version query | 11 | 132, 149, 166, 183, 215, 232, 250, 267, 300, 314, 358 | NO: return existing IO/ex cached versions by owner-local cold DEBUG work, avoiding an unsafe foreign read of a plain field. |
| W5 — Controlled timeout/cron stage with client identity and release | 9 | 132, 139, 166, 173, 215, 222, 250, 257, 358 | YES: deadline/cron progression while DEBUG armed; needed alongside W1 for blocking's config arm. |
| W3 — Controlled sampler traversal with completion witness | 8 | 130, 164, 199, 206, 213, 248, 515, 516 | YES: only when DEBUG armed; both peer oracles need a deterministic coverage construction, not extra random draws. |
| W2 — Held read cut / first fanout fragment / reader publication stage | 7 | 126, 128, 303, 304, 317, 318, 503 | YES: entered/release checks in the existing armed debug path; specify stage separately for fanout and hazard arms. |
| W4 — Held command expiry cut, including local MGET, EXEC and script | 4 | 159, 193, 242, 277 | YES: stage publication and explicit release on the relevant read/transaction paths. |
| W8 — Snapshot capture-cut entered/hold/release | 4 | 341, 342, 349, 350 | YES, snapshot path only; independent mutation ACK must precede capture release. |
| W9 — Atomic APPLY-fragment hold plus snapshot apply-drain state | 4 | 343, 344, 351, 352 | YES: commit-decision hold is not equivalent to partial apply. |
| W10 — Per-client parser parked-on-partial-frame publication | 4 | 122, 203, 210, 366 | YES: publish the armed client's parser stage before starting the unchanged counter window. |
| W6 — LMOVE phase-one selected-value hold before phase-two removal | 2 | 310, 324 | YES: extend the correct LMOVE-family stage, not the RENAME mutation hold. |
| W13 — Producer-to-tracking-consumer delivery fence | 2 | 515, 516 | YES: a fence must cover the async notification path. Ordinary ECHO/PUBLISH alone can overtake that path and cannot prove a zero-event leg drained. |
| W14 — Snapshot/placement admission reservation with entered/release state | 2 | 515, 516 | YES on cold snapshot/placement admission; expose which Busy condition fired and hold admission until the intended SAVE is admitted. |
| W15 — Owner-local stream clock/cut observation | 2 | 515, 516 | NO outside a cold DEBUG query of the actual owner's cached clock. IO-side TIME need not bound an earlier owner pass; keep monotonic IDs and verify the command cut without an arbitrary clock tolerance. |
| W7 — DEBUG SLEEP entered/release latch | 1 | 339 | NO ordinary operation body change: all new work can remain inside the cold DEBUG SLEEP mechanism. |
| W11 — Admitted outstanding traffic spanning completed FLIP | 1 | 368 | YES for an armed admitted-backlog latch and release. The sustained-saturation claim still needs its own instrument; a cold queue query only proves sampled occupancy. |
| W12 — Per-TLS-connection partial input and teardown stage | 1 | 443 | YES on the armed TLS/parser path; global handshakes/ciphertext counters are insufficient. |

**LMOVE hold coverage:** `arm_debug_off_hop_delay` only arms `Kind::Rename`, after its source mutation. Rows 310/324 need selected-source observation held *before* targeted phase-two removal, so reusing it would not test the edge oracle. No production/hook change or xmove assertion removal was made.

**PSFIX:** both-peer save-idle polling is already present. The Busy error also aliases placement admission, and idle observation cannot reserve admission. Retained [seed-91 failure](docs/flakeaudit2/evidence/psfix-a0-s91-original.txt); W14 is needed. No generic Busy retry was added.

**Snapshot groups:** the current snapshot capture drains `atomic_apply_inflight`; a commit latch after all installs cannot witness partial apply. W9 must hold the apply stage itself.

**Production defects:** only the already assigned 337/338 ACL defect is classified D. The new PSFIX evidence does not distinguish its admission race and is classified B. Production correctness laws and layouts were not changed. Threshold separation is a mainline decision; this lane neither deletes nor relaxes those assertions.
