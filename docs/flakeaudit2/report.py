#!/usr/bin/env python3
"""Render the second audit without rewriting the first audit's inventory."""
from collections import Counter
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/flakeaudit2"

# One decision for each mechanism, in the original register's order. A decision
# applies to that mechanism, not to every possible clock/performance check in a battery.
DECISIONS = [
    ("C", "netio", "Wake latency <25 ms; exact blocked-client identity and delivered value remain correctness facts.", []),
    ("A", "torture", "Unique churn keys; observer GET witnesses each SET before RST, with the writer reply unread and partial next frame retained. Final landed-key assertion and every transport error remain.", []),
    ("A", "ryow", "All four background writers acknowledge progress and propagate errors. Added explicit same-key overwrites with an allowed-conflict value set, followed by exact uncontended RYOW; original own-key checks retained.", []),
    ("B", "spinprobe", "W10: per-client parser-park state, observed before the counter interval; ordinary body change YES. Existing LBSIGNALS lacks this state. Counter budgets also need a separate performance instrument (see threshold appendix).", ["W10"]),
    ("B", "atomic_torn", "W2: held read-cut/lead-fragment stage with entered/released status; ordinary body change YES. The existing RENAME hold and commit latch do not force the other fanout/promotion windows.", ["W2"]),
    ("C", "atomic_ryow", "Pipeline rate >1.10 times serial rate (24 groups, release only). Exact ACKs, ordered reads, consistent-or-absent values and positive worker/cut counts remain. ASAN omits the rate assertion but still has finite stress floors; a held overlap is also needed before claiming those arms witnessed.", []),
    ("B", "atomic_hazards", "W2: publish and hold the exact pinned-cut/reader and dispatch stages; ordinary body change YES. Finite delays plus elapsed observations cannot identify those stages; unarmed XREAD <100 ms is a performance control.", ["W2"]),
    ("B", "s6", "W3: DEBUG-controlled sampler traversal/seed with a required traversal-complete witness; ordinary body change YES in the armed sampler branch. Keep exact all-200-key coverage; 20,000 random draws alone cannot guarantee it.", ["W3"]),
    ("A", "multi_exec", "ATOMIC-COMMIT-HOLD forces an undecided EXEC on two real owners; MGET must read all eight predecessors and then all eight committed values. The remaining stress ends only after its original read/commit/cut floors, with a deadline that can only fail.", []),
    ("B", "blocking", "W1 plus W5: applied per-owner config epoch and controlled finite-blocker deadline/retirement; ordinary body changes NO for owner-local config query, YES for an armed clock/lifecycle latch. Exact null/data/gauges stay; two 0.10..0.75 s bounds also mix timing into correctness.", ["W1", "W5"]),
    ("C", "blockmulti", "EXEC completion <250 ms; satisfied WAIT <100 ms; WAIT 200 in 150..900 ms; pipeline WAIT 120 >=90 ms. Exact EXEC results, WAIT :0, younger PONG order, parked/drained gauges and timeout-zero silence remain. Deadline lower bounds express semantics; the upper ceilings are performance.", []),
    ("C", "stream", "Current source gates footprint, not the old register's sampled latency: plateau growth <=8192 B, post-delete <=baseline+4096 B, 0<B/key<512, 128-entry usage<25,600 B. Exact last-100 payloads, all 128 migration entries, DBSIZE and positive allocation remain. Empty-stream timeout >=80 ms is separate deadline semantics.", []),
    ("B", "limits", "W5: DEBUG-held cron/timeout progression with fired and retired client identity; ordinary body change YES. CLIENT LIST already witnesses admission/closure, but not the soft-limit/idle deadline crossing while the test's heartbeat was descheduled.", ["W5"]),
    ("C", "climon2", "PAUSE WRITE read <250 ms, held write >300 ms, UNPAUSE elapsed <2000 ms. Exact GET/SET replies, positive client_pause_holds, ALL-mode silence and released reply remain. A held pause/deadline stage would separate the >300 ms mechanism claim from the clock.", []),
    ("A", "tracking", "Fresh client/key and bounded TTL registration; the 300 ms negative drain occurs before arming the unchanged 400 ms TTL. Positive invalidation is read as a complete exact RESP frame; expired value must be absent.", []),
    ("A", "hexpire", "Recreate only clock-invalid short-field setup; HPEXPIRE and HPEXPIRETIME share one EXEC cut so the actual installed deadline is captured before it can expire. TIME bounds subsequent counters/HLEN. Lazy arm disables active expiry and requires the exact reap delta; active baseline precedes TTL installation. Other numeric tolerances are unchanged.", []),
    ("B", "servertail", "W1: query each owner's already-applied live-config version before OBJECT policy checks; ordinary body change NO if queried on that owner through cold DEBUG work. TIME's +/-60 s allowance is an additional clock oracle, not evidence of config publication.", ["W1"]),
    ("A", "concur", "Every churn batch is acknowledged while a nonzero SCAN cursor is open. Growth/cardinality/rehash and exact permanent-set assertions remain; callbacks no longer count mutation after cursor completion.", []),
    ("A", "edgetime", "Fresh 70/80 ms absolute-deadline queue/WATCH setup must complete before that deadline; missed setups DISCARD/UNWATCH and recreate state within a budget. PEXPIRETIME must equal the armed deadline; wait for it before EXEC. Exact null/abort/reap and negative controls remain.", []),
    ("B", "expwide", "W4: publish a pinned command/transaction expiry cut and hold before the later owner/read until explicit release (including read-local and script/EXEC variants); ordinary body change YES. Existing ATOMIC-FANOUT-DEFER is a finite duration with no entered-stage publication.", ["W4"]),
    ("A", "pushtear", "Exact CLIENT ID must be blocked before PUBLISH; require its ACK before the unchanged one-second deadline. Fresh connections only on missed arming. The two complete frames must retain push/null order and the segment-counter assertion.", []),
    ("A", "read-local high water", "Per-battery INFO high water survives RESETSTAT, following differ_gate.sh. A malformed/missing counter latches failure; no synthetic local reads are added. Positive peak remains required at shutdown.", []),
    ("A", "aclreply", "Exact blocked CLIENT ID, fresh finite timeout arms, acknowledged ACL revocation, and an ECHO reply fence. Compare the entire raw stream, including a duplicate coded null if present, to the original expected reply.", []),
    ("B", "slowlog", "W1: applied config epoch on every IO/ex owner before recorder assertions; ordinary body change NO for cold owner-local queries. The existing 200 ms propagation sleep is not that acknowledgement.", ["W1"]),
    ("B", "execatomic / execiso", "W2: hold a published first fragment and pinned read cut until explicit release; ordinary body change YES. ATOMIC-COMMIT-HOLD covers installed records, not this read-fanout lead-fragment schedule.", ["W2"]),
    ("A", "multires", "First positive atomic-on round holds a real undecided predecessor and requires atomic_exec_order_holds plus pending entries before release. Existing ACK/value/probe assertions, remaining rounds and negative/atomic-off controls stay.", []),
    ("C", "xacct", "Stream size-cost ratio <4.0; EXEC size-cost ratio <15.0. Exact accounting, command replies, persistence/reload state and negative controls remain. Debug jobs already disable placement controllers for reload.", []),
    ("B", "xmove", "W6: LMOVE-family phase-one result held before phase-two targeted removal, with entered status and release; ordinary body change YES. ATOMIC-OFF-HOP-HOLD is Kind::Rename-only and after source mutation, so it cannot replace the 500k LREM schedule. Preserve both RPUSH and LPUSH edge oracles. Atomic-off size ratio <5.0 is also performance.", ["W6"]),
    ("C", "efficiency", "328: trigger growth <=8x at 16x population and last-volatile DEL <=1.25x neighbour. 329: borrowed GET and plain control growth <=1.05. 330: best-of-two dispatch-excess ratio (128/4 threads) <=1.20. Exact key/TTL population, borrow/send/release counters and dispatch geometry controls remain; no threshold is relaxed.", []),
    ("D", "aclkeys", "Restricted BLPOP timeout is treated as a key before parking. Leave 337/338 to aclkeys; retain the first audit's witness patch and failure logs, and require mainline's strict parked-client witness on the eventual production fix.", []),
    ("B", "debug", "W7: DEBUG SLEEP entered/release latch with the sleeping client identity; ordinary body change NO outside the cold DEBUG SLEEP body. The existing blocked_clients gauge can miss the whole finite sleep, and does not hold same-owner progress open.", ["W7"]),
    ("B", "snapshot capture/reload", "W8: hold capture after its published cut and before completion, release after an acknowledged mutation; ordinary body change YES on the cold snapshot path. rdb_bgsave_in_progress alone can be missed or outlive actual capture.", ["W8"]),
    ("B", "snapshot groups", "W9: hold an APPLY fragment before all group fragments install, publish entry and snapshot waiting-for-apply, then release; ordinary body change YES. COMMIT-HOLD is too late: snapshot explicitly drains atomic_apply_inflight, not reply/commit latency.", ["W9"]),
    ("A", "notify", "Keep notifications configured; disable active expiry before the lazy arm. TIME witnesses the unchanged 20 ms deadline, counter must stay flat before GET, then exact expired event and +1 counter are required. Restore active expiry in finally.", []),
    ("A", "flip under load", "Every worker acknowledges checked progress before FLIP; observe flip_completed advance, then every worker advances again. Original wrong-value, generation, BUSY, refusal and connection assertions stay; deadline expiry cannot pass.", []),
    ("A", "flip TTL", "Fresh 96-key cohorts share an absolute deadline 700 ms after arm, avoiding an inference about owners' relative clock cuts. DEBUG SHARDS proves an owner changed and TIME bounds the post-move live read. Every key must emit its expired event and be absent; only missed live windows re-arm under a 30 s budget.", []),
    ("B", "flip saturated", "W11: held admitted backlog spanning FLIP, with per-owner outstanding-work publication and explicit release; ordinary body change YES. Existing command totals/FLIP completion cannot prove a continuously saturated producer; cold queue queries alone would only prove sampled occupancy.", ["W11"]),
    ("C", "atomic floor", ">=120,000 MGET/MSET operations/s after 8 s warmup, delta divided by a constant 6 s. This public row has no independent key/value correctness assertion; rate and positive command activity are all it checks.", []),
    ("A", "pipeorder", "Add a held cross-owner DEL before EXEC, require atomic_exec_order_holds/pending entries, release and compare all five exact replies. Keep all original 400 pipeline rolls and value assertions.", []),
    ("A", "kTLS live INFO", "Read the full RESP bulk length/body/trailer across arbitrary fragmentation. tls_ktls_active >=1 remains mandatory; the 400 ms sleep and single recv are gone.", []),
    ("B", "TLS partial handshake/teardown", "W12: per-connection received partial handshake/ciphertext/parser stage and retired state, held/released where needed; ordinary body change YES on armed TLS paths. Aggregate gauges can show admission, but cannot prove this connection reached its intended partial-record window.", ["W12"]),
    ("B", "differential matrix", "WAIT now uses exact parked IDs on both peers and fresh finite deadline arms. Remaining W3 sampler, W13 notification delivery fence, W14 SAVE/placement admission and W15 owner-clock witness block full reclassification. Ordinary body changes YES for W3/W13/W14, NO outside cold DEBUG for W15. Suite expansion below retains all 44 names.", ["W3", "W13", "W14", "W15"]),
]

PRIMITIVES = {
    "W1": ("Per-owner applied live-config version query", "NO: return existing IO/ex cached versions by owner-local cold DEBUG work, avoiding an unsafe foreign read of a plain field."),
    "W2": ("Held read cut / first fanout fragment / reader publication stage", "YES: entered/release checks in the existing armed debug path; specify stage separately for fanout and hazard arms."),
    "W3": ("Controlled sampler traversal with completion witness", "YES: only when DEBUG armed; both peer oracles need a deterministic coverage construction, not extra random draws."),
    "W4": ("Held command expiry cut, including local MGET, EXEC and script", "YES: stage publication and explicit release on the relevant read/transaction paths."),
    "W5": ("Controlled timeout/cron stage with client identity and release", "YES: deadline/cron progression while DEBUG armed; needed alongside W1 for blocking's config arm."),
    "W6": ("LMOVE phase-one selected-value hold before phase-two removal", "YES: extend the correct LMOVE-family stage, not the RENAME mutation hold."),
    "W7": ("DEBUG SLEEP entered/release latch", "NO ordinary operation body change: all new work can remain inside the cold DEBUG SLEEP mechanism."),
    "W8": ("Snapshot capture-cut entered/hold/release", "YES, snapshot path only; independent mutation ACK must precede capture release."),
    "W9": ("Atomic APPLY-fragment hold plus snapshot apply-drain state", "YES: commit-decision hold is not equivalent to partial apply."),
    "W10": ("Per-client parser parked-on-partial-frame publication", "YES: publish the armed client's parser stage before starting the unchanged counter window."),
    "W11": ("Admitted outstanding traffic spanning completed FLIP", "YES for an armed admitted-backlog latch and release. The sustained-saturation claim still needs its own instrument; a cold queue query only proves sampled occupancy."),
    "W12": ("Per-TLS-connection partial input and teardown stage", "YES on the armed TLS/parser path; global handshakes/ciphertext counters are insufficient."),
    "W13": ("Producer-to-tracking-consumer delivery fence", "YES: a fence must cover the async notification path. Ordinary ECHO/PUBLISH alone can overtake that path and cannot prove a zero-event leg drained."),
    "W14": ("Snapshot/placement admission reservation with entered/release state", "YES on cold snapshot/placement admission; expose which Busy condition fired and hold admission until the intended SAVE is admitted."),
    "W15": ("Owner-local stream clock/cut observation", "NO outside a cold DEBUG query of the actual owner's cached clock. IO-side TIME need not bound an earlier owner pass; keep monotonic IDs and verify the command cut without an arbitrary clock tolerance."),
}


def proof(stage):
    campaigns = sorted((OUT / "evidence").glob(stage + "-*"))
    campaigns = [p for p in campaigns if p.is_dir()]
    if not campaigns:
        return "NOT RUN", []
    campaign = campaigns[-1]
    results = [json.loads(p.read_text()) for p in sorted(campaign.glob("run-*/result.json"))]
    ids = [run for result in results for run in result["run_ids"]]
    if (campaign / "refusal.json").exists():
        return "REFUSED (`%s`, four quiet admissions; no gate run id)" % campaign.name, ids
    required = 6 if stage == "selected" else 1
    if len(results) == required and all(r["rc"] == 0 and not r["fail_rows"] for r in results):
        return "PASS (`%s`; %d runs rc=0, 0 FAIL)" % (campaign.name, required), ids
    if any(r["rc"] or r["fail_rows"] for r in results):
        return "FAILED (`%s`; see retained results)" % campaign.name, ids
    return "PENDING (`%s`; %d/%d completed)" % (campaign.name, len(results), required), ids


def main():
    source = (ROOT / "docs/flakeaudit/remaining.md").read_text()
    groups = [[int(n) for n in line.split("|")[1].split(",")]
              for line in source.splitlines() if re.match(r"\| \d", line)]
    assert len(groups) == len(DECISIONS) == 42
    assert sum(map(len, groups)) == len({r for group in groups for r in group}) == 117
    records = [dict(mechanism=i, rows=rows, category=d[0], name=d[1], detail=d[2], witnesses=d[3])
               for i, (rows, d) in enumerate(zip(groups, DECISIONS), 1)]
    counts = Counter()
    for record in records:
        counts[record["category"]] += len(record["rows"])
    selected, run_ids = proof("selected")
    full, full_ids = proof("full")
    status = dict(A="FIXED-TEST-SIDE", B="NEEDS-WITNESS", C="PERF-THRESHOLD", D="PRODUCTION-DEFECT")
    out = ["# Remaining mechanisms, second audit", "",
        "This table preserves all 42 mechanisms and 117 distinct public row occurrences from "
        "[remaining.md](../flakeaudit/remaining.md). That file and its original inventory are unchanged. "
        "The separate GT16 addendum is row 367; PSFIX is inside existing rows 515/516 and is not double-counted.", "",
        "FIXED-TEST-SIDE means the test change is implemented, **not a live proof claim**. "
        "Each changed occurrence requires the selected campaign and its complete battery. "
        "The category is the disposition of the registered mechanism; other retained checks are called out, "
        "and no entire battery is claimed lottery-free without its proof.", "",
        "Selected proof: " + selected + ". Run ids: " + (", ".join(run_ids) or "none") + ".",
        "Full iteration: " + full + ". Run id: " + (", ".join(full_ids) or "none") + ".", "",
        "Original-register occurrences: A=%d, B=%d, C=%d, D=%d (117). Including GT16: A=%d, "
        "B=%d, C=%d, D=%d (118)." % (counts['A'], counts['B'], counts['C'], counts['D'],
                                    counts['A'] + 1, counts['B'], counts['C'], counts['D']), "",
        "| Mechanism | Public ordinals | New status | Mechanism, preserved oracle, or minimal primitive |",
        "|---|---|---|---|"]
    for r in records:
        detail = r["detail"]
        if r["category"] == "A":
            detail += " Proof: selected campaign above; serverless controls are separate evidence."
        out.append("| %d. %s | %s | %s | %s |" % (r['mechanism'], r['name'],
            ", ".join(map(str, r['rows'])), status[r['category']], detail))
    out += ["", "## Priority addenda", "",
        "**GT16, row 367 — FIXED-TEST-SIDE (A).** `stable_hold_attempt` starts pre-hold sampling only "
        "after `flipctl_state=anchored`. It retains all eight pre-hold samples and the entire requested "
        "hold length. Driver excursions invalidate an arm; fresh arms share the existing `4*seconds+60` "
        "wall budget. There is no three-attempt cap. Every valid in-band hold sample checks trigger, state "
        "and anchor split; a move immediately fails and cannot be retried. Exhaustion is INVALID/failure, "
        "never PASS. Published bands and all thresholds are unchanged. The 21 serverless controls include "
        "deliberately moved trigger/state/split, a 90-second settle, more than three invalid windows and "
        "never-quiescent/short-budget controls. These mutate observed published state, not a live controller "
        "binary. Live six-run and broken-binary proof are still required if admission was refused.", "",
        "**PSFIX seed 91, rows 515/516 — NEEDS-WITNESS (B), W14.** The suggested both-peer "
        "`rdb_bgsave_in_progress:0` poll already exists in `psfix_wait_idle` (10-second bounded loop). "
        "`SnapshotManager::start` also returns Busy when placement is transitioning; `snapshot_command` "
        "maps that Busy to the same `Background save already in progress` error. The retained failure "
        "does not identify which admission condition raced. Another idle poll does not reserve admission. "
        "No error-retry loop or weakened SAVE comparison was added; the original exact reply and +1 save "
        "count remain. [Original failing transcript](evidence/psfix-a0-s91-original.txt). W14 requires a "
        "placement/snapshot admission lease or stage latch, and a distinct reason/status; it changes the "
        "cold ordinary admission body. This is an instrumentation gap, not a claim that the transcript "
        "proves a production data defect.", "",
        "## New witness program, ranked by affected occurrences", "",
        "Counts are the union of row ordinals depending on each primitive, not additive landing counts. "
        "Some rows need multiple primitives or still contain a performance threshold. NO means no "
        "ordinary operation gains a new observation/check; cold DEBUG dispatch may change. A proposal "
        "must still pass the owner's layout/performance review; this lane implements none of them.", "",
        "| Primitive | Rows potentially unblocked | Occurrences | Ordinary unarmed body |",
        "|---|---|---:|---|"]
    ranked = []
    for name, (description, body) in PRIMITIVES.items():
        rows = sorted({row for record in records if name in record['witnesses'] for row in record['rows']})
        ranked.append((len(rows), name, description, body, rows))
    ranked.sort(key=lambda p: (-p[0], int(p[1][1:])))
    for count, name, description, body, rows in ranked:
        out.append("| %s — %s | %s | %d | %s |" % (name, description, ", ".join(map(str, rows)), count, body))
    out += ["", "## Threshold and mixed-family limitations", "",
        "C mechanisms remain untouched: no tolerance widening, assertion removal, row split or EXPECT edit. "
        "For mainline separation, keep each listed correctness assertion in the gate and report the "
        "threshold with matched-load/stationarity evidence. Resource-budget checks are listed explicitly "
        "rather than mislabeled as latency. Mixed B rows also retain their bounds:", "",
        "- spinprobe: per one-second window, idle IO/fused iterations <=64, spins <=64, combined wakes "
        "<=64; split ex spins <=2048*(ceil(1000/50)+64+4)=180224 and iterations <=180288. Partial-frame "
        "excess iterations <=24, spins <=8, sent wakes <=8 and received wakes <=8. Exact completed "
        "partial-frame +OK and stable thread roles remain; parser publication alone does not prove "
        "these performance budgets.",
        "- blocking: 0.10 <= elapsed <=0.75 s for both 150 ms timeout legs; nulls and untouched tail remain.",
        "- atomic_hazards: unarmed XREAD must complete before half of the 200,000 us delay (100 ms); "
        "other elapsed lower bounds are attempts to infer an open stage, not a stage witness.",
        "- xmove: atomic-off large/small LMOVE ratio <5.0 remains beside exact selected-edge preservation.",
        "- atomic_torn's release promotion-drain ceiling is <=1.5 s with positive holds, predecessor "
        "reads and promotions plus an exact final group. The separate stage-count arms in "
        "atomic_torn/execatomic/execiso need W2 before their budgets can serve solely as failure deadlines.",
        "- DEBUG SLEEP .5 currently requires same-owner progress and cancellation admission within "
        ".30 s, no reply before .40 s, and cancellation drain within .30 s. The parked gauge, exact "
        "OK/PONG order and restored gauge must remain when a latch separates its scheduling window.",
        "- repaired HEXPIRE keeps its independent long-TTL rounding/range assertions; the registered "
        "short live-field race was repaired, not every possible clock dependence in that battery.", "",
        "## Differential suite expansion", "",
        "One suite per line, no additional public rows. The original review remains available in "
        "[differ-reviews.json](../flakeaudit/differ-reviews.json). Only the WAIT submechanism changed here. "
        "All 44 suites are included through the selected differential jobs; their aggregate public rows "
        "remain B until the listed residuals are resolved.", "",
        "| Suite | Disposition in this lane |", "|---|---|"]
    for suite in json.loads((ROOT / "docs/flakeaudit/differ-reviews.json").read_text()):
        detail = {"blocking": "WAIT finite/zero exact parked-client arms repaired (A submechanism); exact replies and silence preserved.",
                  "stream": "B / W15: owner-clock cut needed for auto IDs; existing +/-10 s wall allowance unchanged.",
                  "s6fix": "B / W3: all-200-key RANDOMKEY coverage still probabilistic.",
                  "climon": "B / W13: idle delimiters do not fence asynchronously produced tracking pushes.",
                  "psfix": "B / W14: observed both-peer save idle does not reserve placement/snapshot admission."}.get(
                      suite['name'], "Unchanged; retain first audit's %s assessment." % suite['kind'])
        out.append("| %s | %s |" % (suite['name'], detail))
    (OUT / "remaining-v2.md").write_text("\n".join(out) + "\n")
    (OUT / "triage.json").write_text(json.dumps(dict(counts=dict(counts), mechanisms=records,
        priority_addenda=[dict(row=367, category="A", name="GT16"),
                          dict(rows=[515, 516], category="B", name="PSFIX", witness="W14")]), indent=2) + "\n")

    report = ["# flakeaudit2 measurement and proof request", "",
        "Test-side changes are committed on `cx-flakeaudit2`; no push. Production is unchanged relative "
        "to the final fetched/merged `origin/cpp`. **No live pass is claimed without the receipts below.**", "",
        "Rows +0/+0; EXPECT remains **500 quick / 517 full**. Public names/order/multiplicity match the "
        "first audit exactly; [row-count receipt](docs/flakeaudit2/evidence/row-counts.txt). "
        "[Production diff receipt](docs/flakeaudit2/evidence/production.diff) is empty. "
        "[Final merge receipt](docs/flakeaudit2/evidence/final-merge.txt).", "",
        "Selected proof: " + selected + ". Run ids: " + (", ".join(run_ids) or "none") + ".",
        "Full `tests/gate.sh iteration`: " + full + ". Run id: " + (", ".join(full_ids) or "none") + ".", "",
        "The extension [proof.py](docs/flakeaudit2/proof.py) follows `docs/flakeaudit/repeat.sh`: whole jobs, "
        "six serial runs, fail on any failed run/FAIL row, compare server SHA before/after, preserve raw "
        "logs/ledgers and textual job artifacts in committed evidence. Selected runs are deliberately "
        "partial and never labeled full gate receipts. Each admission uses the unchanged quiet monitor, "
        "one initial screen plus at most three retries at 200-second spacing. Refusal is recorded and "
        "does not launch a compiler, server or load generator. Failed tests are never retried to obtain "
        "a pass. Server CPUs 112-119, load CPUs 120-127, build affinity 112-127, ports 18340-18342.", "",
        "Re-proof on the maintainer's idle box (merge origin/cpp first):", "", "```sh",
        "python3 docs/flakeaudit2/proof.py selected",
        "python3 docs/flakeaudit2/proof.py full",
        "python3 docs/flakeaudit2/report.py",
        "git add docs/flakeaudit2/evidence docs/flakeaudit2/remaining-v2.md docs/flakeaudit2/triage.json MEASURE-REQUEST-flakeaudit2.md",
        "git commit -m 'Record flakeaudit2 idle-box proof'", "```", "",
        "No PRE/POST/PAD arm: this lane changes no production code or layout and makes no throughput "
        "claim. The instrument's verdict is six rc=0 selected runs with 0 FAIL across every changed "
        "battery, plus one full iteration with 0 gating FAIL. A refusal leaves this requirement pending.", "",
        "## Implemented repairs", "",
        "All entries below share the selected campaign status above; the row numbers are public "
        "ordinals, not Python assertion counts.", "",
        "| Public rows | Mechanism | Proof |", "|---|---|---|"]
    report.append("| 367 | GT16: quiescent arm, time-budget invalid windows, full-length in-band hold; valid movement fails immediately | 21 serverless classifier/schedule controls; live campaign above |")
    for r in records:
        if r['category'] == 'A':
            report.append("| %s | %s: %s | Selected campaign above |" % (
                ", ".join(map(str, r['rows'])), r['name'], r['detail']))
    report += ["| 515, 516 (partial repair) | Differential WAIT: both exact clients parked, unchanged 200 ms deadline/50 ms silence arm; fresh connections on missed setup, exact :0 result | Selected differential jobs; aggregate rows remain B |", "",
        "Serverless evidence: [GT16](docs/flakeaudit2/evidence/gt16-controls.txt), "
        "[15 fragmentation/high-water/expiry/atomic/WAIT controls](docs/flakeaudit2/evidence/test-side-controls.txt). "
        "The deliberate GT16 controls inject trigger, state and anchor-split movement during an otherwise "
        "valid hold, each failing immediately without a re-roll. Other controls reject missing atomic "
        "installation, disabled holds, private values, truncated frames, duplicate coded ACL replies, "
        "never-live TTL arms, absent/malformed lane counters, never-parked WAIT arms and in-window early replies. They do not replace live six-run or "
        "broken-controller-binary receipts; quiet refusals prevent that claim.", "",
        "## Full triage", "",
        "[remaining-v2.md](docs/flakeaudit2/remaining-v2.md) contains all 42 original mechanisms, the "
        "GT16 and PSFIX addenda, exact residual thresholds, and 44 differential suites one per line.", "",
        "| Category | Mechanisms in original 42 | Row occurrences |", "|---|---:|---:|"]
    for cat in 'ABCD':
        report.append("| %s — %s | %d | %d |" % (cat, status[cat],
            sum(r['category'] == cat for r in records), counts[cat]))
    report += ["", "GT16 adds one A mechanism/occurrence: **43 A + 51 B + 22 C + 2 D = 118 distinct "
        "scoped occurrences**. PSFIX and the WAIT partial repair are within rows 515/516 and add zero "
        "occurrences. 45 distinct public occurrences were edited (42 original A, GT16, and the two "
        "partially repaired differential rows), without adding public rows.", "",
        "## Ranked class-B primitives", "",
        "Counts overlap; implementing one primitive does not prove an entire mixed battery.", "",
        "| Primitive | Occurrences | Exact row family | Ordinary body change |", "|---|---:|---|---|"]
    for count, name, description, body, rows in ranked:
        report.append("| %s — %s | %d | %s | %s |" % (
            name, description, count, ", ".join(map(str, rows)), body))
    report += ["", "**LMOVE hold coverage:** `arm_debug_off_hop_delay` only arms `Kind::Rename`, "
        "after its source mutation. Rows 310/324 need selected-source observation held *before* targeted "
        "phase-two removal, so reusing it would not test the edge oracle. No production/hook change or "
        "xmove assertion removal was made.", "",
        "**PSFIX:** both-peer save-idle polling is already present. The Busy error also aliases placement "
        "admission, and idle observation cannot reserve admission. Retained [seed-91 failure](docs/flakeaudit2/evidence/psfix-a0-s91-original.txt); "
        "W14 is needed. No generic Busy retry was added.", "",
        "**Snapshot groups:** the current snapshot capture drains `atomic_apply_inflight`; a commit "
        "latch after all installs cannot witness partial apply. W9 must hold the apply stage itself.", "",
        "**Production defects:** only the already assigned 337/338 ACL defect is classified D. The "
        "new PSFIX evidence does not distinguish its admission race and is classified B. Production "
        "correctness laws and layouts were not changed. Threshold separation is a mainline decision; "
        "this lane neither deletes nor relaxes those assertions."]
    (ROOT / "MEASURE-REQUEST-flakeaudit2.md").write_text("\n".join(report) + "\n")
    print("triage", dict(counts), "selected", selected, "full", full)


if __name__ == "__main__":
    main()
