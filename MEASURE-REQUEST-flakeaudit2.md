# flakeaudit2 measurement and proof request

Test-side changes are committed on `cx-flakeaudit2`; no push. Production is unchanged relative to the final fetched/merged `origin/cpp`. **No live pass is claimed without the receipts below.**

The dated **flakeaudit2b** section below supersedes the multi_exec repair claim. Original flakeaudit2 campaign statuses are retained here as history.

Rows +0/+0; EXPECT remains **500 quick / 517 full**. Public names/order/multiplicity match the first audit exactly; [row-count receipt](docs/flakeaudit2/evidence/row-counts.txt). [Production diff receipt](docs/flakeaudit2/evidence/production.diff) is empty. [Final merge receipt](docs/flakeaudit2/evidence/final-merge.txt).

Selected proof: REFUSED (`selected-20261007T222606Z`, four quiet admissions; no gate run id). Run ids: none.
Full `tests/gate.sh iteration`: REFUSED (`full-20261007T223724Z`, four quiet admissions; no gate run id). Run id: none.

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
| 147, 181, 230, 265 | tracking: Fresh client/key and bounded TTL registration; the 300 ms negative drain occurs before arming the unchanged 400 ms TTL. Positive invalidation is read as a complete exact RESP frame; expired value must be absent. | Selected campaign above |
| 148, 182, 231, 266 | hexpire: Recreate only clock-invalid short-field setup; HPEXPIRE and HPEXPIRETIME share one EXEC cut so the actual installed deadline is captured before it can expire. TIME bounds subsequent counters/HLEN. Lazy arm disables active expiry and requires the exact reap delta; active baseline precedes TTL installation. Other numeric tolerances are unchanged. | Selected campaign above |
| 151, 185, 234, 269 | concur: Every churn batch is acknowledged while a nonzero SCAN cursor is open. Growth/cardinality/rehash and exact permanent-set assertions remain; callbacks no longer count mutation after cursor completion. | Selected campaign above |
| 154, 188, 237, 272 | edgetime: Fresh 70/80 ms absolute-deadline queue/WATCH setup must complete before that deadline; missed setups DISCARD/UNWATCH and recreate state within a budget. PEXPIRETIME must equal the armed deadline; wait for it before EXEC. Exact null/abort/reap and negative controls remain. | Selected campaign above |
| 161, 195, 244, 279 | pushtear: Exact CLIENT ID must be blocked before PUBLISH; require its ACK before the unchanged one-second deadline. Fresh connections only on missed arming. The two complete frames must retain push/null order and the segment-counter assertion. | Selected campaign above |
| 246, 281 | read-local high water: Per-battery INFO high water survives RESETSTAT, following differ_gate.sh. A malformed/missing counter latches failure; no synthetic local reads are added. Positive peak remains required at shutdown. | Selected campaign above |
| 294, 295 | aclreply: Exact blocked CLIENT ID, fresh finite timeout arms, acknowledged ACL revocation, and an ECHO reply fence. Compare the entire raw stream, including a duplicate coded null if present, to the original expected reply. | Selected campaign above |
| 306, 320 | multires: First positive atomic-on round holds a real undecided predecessor and requires atomic_exec_order_holds plus pending entries before release. Existing ACK/value/probe assertions, remaining rounds and negative/atomic-off controls stay. | Selected campaign above |
| 361 | notify: Keep notifications configured; disable active expiry before the lazy arm. TIME witnesses the unchanged 20 ms deadline, counter must stay flat before GET, then exact expired event and +1 counter are required. Restore active expiry in finally. | Selected campaign above |
| 364 | flip under load: Every worker acknowledges checked progress before FLIP; observe flip_completed advance, then every worker advances again. Original wrong-value, generation, BUSY, refusal and connection assertions stay; deadline expiry cannot pass. | Selected campaign above |
| 365 | flip TTL: Fresh 96-key cohorts share an absolute deadline 700 ms after arm, avoiding an inference about owners' relative clock cuts. DEBUG SHARDS proves an owner changed and TIME bounds the post-move live read. Every key must emit its expired event and be absent; only missed live windows re-arm under a 30 s budget. | Selected campaign above |
| 372 | pipeorder: Add a held cross-owner DEL before EXEC, require atomic_exec_order_holds/pending entries, release and compare all five exact replies. Keep all original 400 pipeline rolls and value assertions. | Selected campaign above |
| 439 | kTLS live INFO: Read the full RESP bulk length/body/trailer across arbitrary fragmentation. tls_ktls_active >=1 remains mandatory; the 400 ms sleep and single recv are gone. | Selected campaign above |
| 515, 516 (partial repair) | Differential WAIT: both exact clients parked, unchanged 200 ms deadline/50 ms silence arm; fresh connections on missed setup, exact :0 result | Selected differential jobs; aggregate rows remain B |

Serverless evidence: [GT16](docs/flakeaudit2/evidence/gt16-controls.txt), [15 fragmentation/high-water/expiry/atomic/WAIT controls](docs/flakeaudit2/evidence/test-side-controls.txt). The deliberate GT16 controls inject trigger, state and anchor-split movement during an otherwise valid hold, each failing immediately without a re-roll. Other controls reject missing atomic installation, disabled holds, private values, truncated frames, duplicate coded ACL replies, never-live TTL arms, absent/malformed lane counters, never-parked WAIT arms and in-window early replies. The four atomic simulations are retained against the rejected battery as historical controls only: they assumed a server mechanism that EXEC does not implement. They support no live held-EXEC claim. These are serverless mutation controls; no live mutant controller binary was run. Live six-run receipts remain pending after quiet refusal.

## Full triage

[remaining-v2.md](docs/flakeaudit2/remaining-v2.md) contains all 42 original mechanisms, the GT16 and PSFIX addenda, exact residual thresholds, and 44 differential suites one per line.

| Category | Mechanisms in original 42 | Row occurrences |
|---|---:|---:|
| A — FIXED-TEST-SIDE | 15 | 35 |
| B — NEEDS-WITNESS | 18 | 58 |
| C — PERF-THRESHOLD | 8 | 22 |
| D — PRODUCTION-DEFECT | 1 | 2 |

GT16 adds one A mechanism/occurrence: **36 A + 58 B + 22 C + 2 D = 118 distinct scoped occurrences**. PSFIX and the WAIT partial repair are within rows 515/516 and add zero occurrences. After withdrawing the seven multi_exec repairs, 38 distinct public occurrences remain edited (35 original A, GT16, and the two partially repaired differential rows), without adding public rows.

## Ranked class-B primitives

Counts overlap; implementing one primitive does not prove an entire mixed battery.

| Primitive | Occurrences | Exact row family | Ordinary body change |
|---|---:|---|---|
| W1 — Per-owner applied live-config version query | 11 | 132, 149, 166, 183, 215, 232, 250, 267, 300, 314, 358 | NO: return existing IO/ex cached versions by owner-local cold DEBUG work, avoiding an unsafe foreign read of a plain field. |
| W5 — Controlled timeout/cron stage with client identity and release | 9 | 132, 139, 166, 173, 215, 222, 250, 257, 358 | YES: deadline/cron progression while DEBUG armed; needed alongside W1 for blocking's config arm. |
| W3 — Controlled sampler traversal with completion witness | 8 | 130, 164, 199, 206, 213, 248, 515, 516 | YES: only when DEBUG armed; both peer oracles need a deterministic coverage construction, not extra random draws. |
| W2 — Held read cut / first fanout fragment / reader publication stage | 7 | 126, 128, 303, 304, 317, 318, 503 | YES: entered/release checks in the existing armed debug path; specify stage separately for fanout and hazard arms. |
| W16 — EXEC installed/predecision latch with identity, owner/key counts and explicit release | 7 | 131, 165, 200, 207, 214, 249, 357 | YES: park the transaction finalizer after all installs and before its direct atomic_commit_group call, without blocking owners. The scatter commit-queue latch does not cover EXEC. |
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

## 2026-10-08 — flakeaudit2b

The seven multi_exec occurrences (131/165/200/207/214/249/357) are **class B / NEEDS-WITNESS**, not repaired held-EXEC tests. The supplied mainline campaign recorded 226 ok and seven FAIL, all at `tests/multi_exec.py:332`. The first merge was `8f1fb3d49` over `origin/cpp` at `9b3cab67b`.

Root cause: `DEBUG ATOMIC-COMMIT-HOLD` (`src/cmd/t_server.cc:1096`) sets the latch checked only by `ExLoopT::flush_xshard_commits` (`src/core/ex_loop.h:2761`), retaining the owner-private scatter commit queue before ticket reservation. EXEC's all-owner join instead calls `Server::atomic_commit_group` directly (`src/cmd/multi.inc:2246-2255`, `src/core/server.h:2564`), bypassing that queue and latch. It installs and commits; the test's ten-second deadline misreports the missing held state as missing installation. `atomic_pending_entries` is the number of live linked entries (`src/store/flatstore_atomic.inc:40,591,1027`), not a commit-hold witness. `atomic_exec_order_holds` (`src/core/ex_loop.h:2360`) counts a younger transaction parked behind an earlier same-connection unit *before* installation; substituting it would prove a different mechanism. `_lib.owner_buckets` (`tests/_lib.py:481`) already checks real owners at key selection (without pinning placement afterward); the test selects four keys on each of two owners. The latch bypass applies regardless of 16-shard placement and explains the deterministic failure.

No existing hook provides the required nonblocking, explicitly released EXEC stage. COMMIT-DELAY is a finite stall; FANOUT-DEFER and EXEC's DEBUG SLEEP are finite parks. Missing primitive **W16**: hold the EXEC finalizer after every owner has installed and before its direct commit decision; expose transaction identity, installed owner/key counts, entered status and explicit release, while owners remain available for the independent reader. Adding it would require a production change, outside this lane.

Used the explicitly authorized fallback: `tests/multi_exec.py` is byte-identical to `5bf5b65e6:tests/multi_exec.py`, the predecessor of repair `ebb7c512d`. The original eight-key lottery, two-second stress, read/commit/cut floors, torn-read oracle, exact replies, WATCH assertions and public rows remain. No tolerance was widened and no original assertion was removed. The rejected implementation and its four fake-server controls are retained as historical evidence; those controls assumed the unsupported mechanism and are not live proof. The other eleven serverless controls are unchanged; all 15 pass.

Evidence directory: [flakeaudit2b-20261008T034854Z](docs/flakeaudit2/evidence/flakeaudit2b-20261008T034854Z/). `proof_b.py` reproduces all six mode/atomic boots using the saved rejected battery and contrasts EXEC with a held two-owner MSET. It then runs the six requested whole jobs six times serially, plus a separate full iteration; each gate records its revision, server SHA, raw ledger and logs. Failed runs stop the campaign and are retained. Quiet admission uses the unchanged 20-second / 0.48 CPU-second screen, initially plus three retries at 200-second spacing.

Final proof status: **REFUSED / NOT RUN**, not a green gate. Each phase exhausted its initial admission screen plus three retries over ten minutes. No compiler, server, load generator or gate job started. Gate rc and FAIL-row counts are unavailable because no new ledger exists; the wrapper admission rc is 3, not a gate verdict.

| Phase | Required / completed | CPU-seconds at the four refused screens (budget 0.48) | Result |
|---|---:|---|---|
| Original-battery reproduction across six boots | 6 / 0 | 1.06, 0.66, 1.19, 1.30 | REFUSED |
| Six selected jobs × six serial gate runs | 6 / 0 runs | 0.61, 0.92, 0.97, 0.55 | REFUSED; no ledgers |
| Full iteration | 1 / 0 | 0.63, 0.69, 0.79, 0.75 | REFUSED; no ledger |

[Machine-readable proof summary](docs/flakeaudit2/evidence/flakeaudit2b-20261008T034854Z/proof-summary.json), [reproduction log](docs/flakeaudit2/evidence/flakeaudit2b-20261008T034854Z/reproduce-driver.log), [selected log](docs/flakeaudit2/evidence/flakeaudit2b-20261008T034854Z/selected-driver.log), [full log](docs/flakeaudit2/evidence/flakeaudit2b-20261008T034854Z/full-driver.log). All 12 raw quiet-screen records are committed. Fresh live reproduction and the required six-run/full ledgers remain outstanding for the maintainer's quiet box; the supplied mainline seven-failure logs are the existing live evidence, not a new lane run.

Fetched and merged `origin/cpp` again before the selected proof and again before the full proof; both were already up to date at `9b3cab67b`. [Pre-full merge transcript](docs/flakeaudit2/evidence/flakeaudit2b-20261008T034854Z/pre-full-merge.txt). Static verification passed: byte-identical restored battery, 15 serverless controls, unchanged production and gate source, all 517 original public labels/order/multiplicity, Python syntax and `git diff --check`. The grep audit covered 89 changed-text encodings and 5,561 matching test-source lines. The test revert is commit `72cb9c060`.

The evidence driver requires fresh output directories so refusals cannot be overwritten. After merging mainline, re-proof on the assigned idle cores with fresh names:

```sh
python3 docs/flakeaudit2/proof_b.py reproduce docs/flakeaudit2/evidence/flakeaudit2b-20261008T034854Z/reproduce-idle
python3 docs/flakeaudit2/proof_b.py selected docs/flakeaudit2/evidence/flakeaudit2b-20261008T034854Z/selected-idle
python3 docs/flakeaudit2/proof_b.py full docs/flakeaudit2/evidence/flakeaudit2b-20261008T034854Z/full-idle
```


Rows **+0/+0**; `EXPECT_QUICK=500` / `EXPECT_FULL=517` untouched. No production edits, no throughput claim, no PRE/POST/PAD arms, no push.
