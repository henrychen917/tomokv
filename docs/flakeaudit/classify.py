#!/usr/bin/env python3
"""Reviewed stimulus classifications. Source inventory only, never run a battery."""
from collections import Counter
import json
from pathlib import Path
import re
import build_inventory
import differ_reviews

ROOT = build_inventory.ROOT
REVIEWS = {}
D, B, L = "DETERMINISTIC", "BOUNDED-WITNESSED", "LOTTERY"


def review(files, kind, marker, mechanism):
    for name in files.split():
        path = "tests/" + name
        lines = (ROOT / path).read_text().splitlines()
        line = next((i for i, text in enumerate(lines, 1) if marker and marker in text), 1)
        if marker and line == 1 and marker not in lines[0]:
            raise ValueError((path, marker))
        assert path not in REVIEWS, path
        REVIEWS[path] = dict(kind=kind, line=line, mechanism=mechanism)


review("parbuild.sh docs_drift.py acl_categories.py cmdmeta_coverage.py", D, "",
       "Build/generated-table equality; no concurrent stimulus or sampled clock oracle.")
review("config_parser_test.cc flipctl_unit.cc foreign_read_safety_test.cc "
       "read_local_write_ring_unit.cc climon_mask_unit.cc rlfence_unit.cc shutdown_unit.cc "
       "core_concurrency_unit.cc rltopo_unit.cc store_regression.cc",
       D, "", "Serverless directed states, synthetic time or held interleavings; exact state assertions.")
review("multidb_unit.cc multidb_boundary_unit.cc at15_unit.cc execabort_watch_unit.cc "
       "atomic_survivors_unit.cc netcmd_unit.cc netcap_unit.cc waits_unit.cc rehash_waits_unit.cc "
       "ktls_keyupdate_unit.cc", D, "",
       "Serverless dispatch/state driver; failure states and required witnesses are constructed.")
review("connreset_harness_test.py lbplanner_checks.py persistfix_checks.py exbatch_checks.py "
       "wb_rule_checks.py wbland_checks.py r7shadow_sync.py r7shadow_sync_test.py reorder_receipt.py "
       "splitlocal_checks.py flushfix_checks.py mdbqsbr_checks.py storesize_checks.py "
       "aof_frame_order_test.py", D, "",
       "Directed unit/static identity checks with explicit negative controls; no live sampling race.")
review("abba_instrument.py abbagate.py background_environment_test.py gate_history.py "
       "gate_measurements.py gate_process_test.py gate_quiet.py gate_receipt.py gate_subset_test.py gates_test.py",
       D, "", "Gate invokes serverless self-tests/fixtures here, including rejected measurements and process controls.")
review("bitfield.py resp3.py lua_scripting.py zsetops.py geo.py lcs.py arity.py cmdgap.py "
       "contarity.py netcmd.py execfix.py knobs.py respcompat.py globcase.py", D, "",
       "Ordered command/reply or constructed geometry/value oracle; randomized inputs do not require a lucky interleave.")
review("sort.py scriptatomic.py", D, "",
       "Owner placement is queried; ordered operations force the asserted scatter/effect counters and exact data.")
review("wb_policy.py", D, "", "Gate's 22 standard trace fixtures force policy clauses; this row is serverless.")
review("atomfix.py", D, "ATOMIC-DIRECT-DEFER",
       "Owner-pass defer forces scan/order overlap; positive hold counter and unarmed control are mandatory.")
review("ryow.py", L, "def hammer():",
       "Background writers use rk* while the foreground uses own*, have no progress witness, and swallow errors. The advertised same-key contention never occurs. Needs an explicit conflict schedule with a valid RYOW oracle, since conflicting overwrites are allowed.")
review("pipeorder.py", L, "", "400 pipeline rolls do not prove the hazardous owner order occurred. Needs a held predecessor plus a window witness, preserving every value assertion.")
review("shutdown_persist.py", B, "",
       "Owned process, acknowledged writes, exact snapshot recovery and bounded shutdown witnesses.")
review("exbatch.py", B, "", "Polls publication/lifecycle state under a bound; missing publication fails.")
review("lb_stationary.py", B, "", "Fresh stationarity attempts use actual assigned owners and bounded counter witnesses; absent stable baseline fails.")
review("flipctl.py", B, "", "Dual-anchor complete stationary windows and fresh attempts; losing either anchor rejects the window.")
review("rehash_readonly.py", B, "", "Constructs an unfinished resize, then requires read-only progress to drain before the bound.")
review("pubsub.py streamgroups.py auth.py", B, "", "Subscription/blocked-state/EOF acknowledgements and bounded delivery waits; absent required state fails.")
review("netcap.py", B, "", "Directed inline/query caps, known connection owner and bounded EOF/reclamation witnesses.")
review("scriptsurf.py", B, "", "Busy-script state is observed before kill; exact script replies and bounded completion.")
review("climon.py", B, "", "CLIENT scatter acknowledgements and bounded EOF; MAXAGE sleep establishes a minimum age, not a narrow live window.")
review("edgeproto.py", D, "", "Exact parser/reply sequences; disconnect pause precedes health checks without a narrow positive-state requirement.")
review("dumprestore.py", D, "", "Exact serialized values, ordered SAVE and restart; live deadlines are distant and expired deadlines are already past.")
review("edgeenc.py", B, "debug_load", "Representation boundaries are constructed; successful reload waits for stable placement with the existing bounded helper.")
review("infofix.py", B, "", "Polls ops-rate idle/active witnesses; RESETSTAT's own assertions use a new baseline.")
review("lbsignals.py", B, "", "Owner-published counter progress is polled; shutdown selection checks a completed drain report.")
review("bplus.py atomic_plain.py read_local_lane.py session_monotonic.py multirace.py xscript.py",
       B, "", "Directed defer/hold plus required counters; missed arming is bounded and retried on fresh state, never accepted as success.")
review("evict_battery.py", B, "", "Gate selects lfu/lruclock only: real hot-touch metadata and bounded steady ranking/decay witnesses (GT18 fixes retained).")
review("multidb.py", B, "debug_load", "Namespace/value checks plus placement-idle reload/LOADAOF; each restore keeps its exact reply oracle.")
review("multidb_serial.py", D, "", "Serializability checker uses invocation/response intervals and exact data; self-test uses synthetic histories.")
review("mdbqsbr_live.py", B, "", "Owns its processes, observes parked/disconnected clients and load progress, and requires shutdown/SWAPDB completion under liveness bounds.")
review("debug_load.py", B, "debug_load", "Existing wait_flip_idle and exact FLIP-only refusal retry; all other errors fail.")
review("acl.py", L, "time.sleep(0.25)", "Restricted BLPOP is denied before parking: acl_check_keys treats its timeout as a key. The same NOPERM passes the supposed post-wake recheck. Strict witness patch and two failure logs retained; requires production ACL key-range correction outside this lane.")
review("aclsel.py", D, "", "TomoKV rejects selectors and returns before Redis-only selector blocking cases; no live blocking window selected on this server.")
review("aof.py", B, "def expect_loadaof", "Waits for placement idle before raw LOADAOF; only exact FLIP refusal is retried; success/corruption bytes remain exact.")
review("aof_fsync.py", B, "def wait_idle_sync", "Everysec retains 1.25s policy age then requires actual fsync progress before a deadline; always/no use exact counter controls.")
review("aof_rewrite_matrix.sh", B, "debug_load.py", "Published rewrite pause files force every interruption stage; LOADAOF admission uses the common placement witness.")
review("aof_rewrite_trigger_matrix.sh aof_rewrite_triggers.py", B, "", "DEBUG AOF-REWRITE-PAUSE and published rewrite state; bounded trigger/completion observation.")
review("aof_torn_group.py", D, "", "Directed group interruption plus exact replay/order checks; interruption is explicitly armed.")
review("persistfix.py", B, "", "Published held AOF stage and exact owned PID precede kill/term; missing marker fails.")
review("aof_frame_order.py", D, "", "Forced multi-chunk record and ordered control frames; exact parser and path counters reject vacuous execution.")
review("snap_typed_roundtrip.py", D, "", "Ordered typed seed/SAVE/reload; exact values and long-lived TTLs.")
review("snap_typed_race.py", B, "", "Published snapshot cut ticket establishes ordering; required preimage/capture witnesses and bounded save completion.")
review("snap_cut_battery.py", L, "time.sleep(0.6)",
       "Atomic-group submodes rely on fixed writer warmup, N saves and positive cut/read/write counts. Concurrent-cut save mode is fixed separately. Group overlap needs a held pending group at the cut.")
review("ktls_keyupdate.cc", B, "", "Complete SSL command/reply and explicit KeyUpdate path counters; bounded drain/handshake progress.")
review("feature_gate.py", B, "for attempt", "Fresh workload attempts require every configured path's counter; absent engagement fails. Invalid fused/flip-auto cells are deterministic refusals.")
review("replyoff_xshard.py", D, "", "Owner-spanning large MGET borrows are constructed; PING fences the exact silent wire stream and counters prove the path.")
review("zc.py", B, "", "Large borrowed reply/backpressure by construction; positive send/completion witnesses and exact data.")
review("tailgen_stall.py", B, "", "Held fake-server responses and outstanding-work witnesses; missing stalled client fails.")
review("s6.py", L, "RANDOMKEY", "20,000 random draws must cover all 200 keys; no finite sample guarantees that coverage. Needs a controllable sampler/traversal witness, not more draws.")
review("multi_exec.py", L, "time.sleep(seconds)", "Fixed-duration concurrent writer/readers must exceed count/cut floors. Needs a directed held atomic cut and acknowledged writer/reader progress.")
review("blocking.py", L, "time.sleep", "Finite blocker deadlines and config-propagation sleep are setup assumptions; elapsed upper bounds also remain. Needs owner config acknowledgement and explicit blocker lifecycle controls.")
review("blockmulti.py", L, "time.monotonic", "Immediate WAIT/EXEC checks include 100/250ms elapsed ceilings. Needs a completion-state oracle separating liveness from performance.")
review("stream.py", L, "started = time.monotonic()", "Fixed sampled stream cost/latency limits remain despite witnessed blocking. Needs matched performance instrumentation or a constructed work-count oracle.")
review("limits.py", L, "time.sleep(0.4)", "CLIENT close admission is now witnessed; idle-timeout heartbeats and soft-output limits still depend on timed pauses. Needs controlled timeout/owner-state progression.")
review("climon2.py", L, "read_ms < 250", "CLIENT UNBLOCK now observes the exact parked client; CLIENT PAUSE arms still use short elapsed deadlines/latency bounds. Needs a published pause latch.")
review("tracking.py", L, '"400"', "Redirect disconnect now witnesses removal; 400ms TTL followed by a 300ms drain must leave the key alive for tracking registration. Needs fresh-state bounded TTL arming and an exact delivery fence.")
review("hexpire.py", L, '"250"', "Short live field TTL must survive setup/counter sampling before expiry. Needs bounded fresh-field arming or a controllable expiry clock; do not widen tolerances.")
review("servertail.py", L, "time.sleep(0.05)", "Live maxmemory-policy publication is assumed after 50ms before OBJECT metadata checks; also wall-clock TIME allowance. Needs per-owner config acknowledgement/clock bracketing.")
review("concur.py", L, "time.sleep(0.05)", "Fixed SCAN/churn runs require a growth/interleave to have happened. Needs held scan cursor plus witnessed concurrent growth on the same state.")
review("edgetime.py", L, "time.sleep", "Small TTL live-before/expired-after setup and time windows depend on scheduling. Needs fresh-state arming with server deadline evidence.")
review("expwide.py", L, "time.sleep", "Deadline-crossing batches and elapsed-time bounds require the intended expiry window. Needs a held dispatch/cut or controllable clock.")
review("pushtear.py", L, "time.sleep(0.15)", "A finite BLPOP is assumed parked after 150ms before a push; null/push ordering depends on the remaining deadline. Needs exact parking plus bounded fresh-state timeout arming.")
review("netio.py", L, "25", "Blocked-reader setup now witnesses CLIENT ID; the unchanged 25ms wake-latency assertion remains a scheduler/performance threshold.")
review("debug.py", L, "time.sleep", "Reload admission is fixed; independent progress during DEBUG SLEEP still has 300ms timing windows. Needs a published sleep-stage latch and release control.")
review("atomic_torn.py", L, "time.sleep(seconds)", "Directed GT14 RENAME hold is retained; other fixed-duration negative hammers/cut counters and the release promotion budget remain timing stimuli. Needs directed controls for those separate windows.")
review("atomic_ryow.py", L, "pipelined_elapsed", "24-command pipeline/serial timing comparison and fixed-duration positive worker floors. Needs a held/acknowledged overlap plus independent performance instrument.")
review("atomic_hazards.py", L, "unarmed control was slow", "Unarmed XREAD control must finish inside half the configured delay; other arms infer an open window from elapsed time. Needs a published command-stage witness.")
review("execatomic.py execiso.py", L, "time.sleep(0.05)", "50ms lead-fragment wait inside a finite defer plus fixed-duration cut/read/commit floors. Needs a held fragment and positive stage/cut witness.")
review("multires.py", L, "window_holds == 0", "Atomic-on requires at least one ordering hold among fixed pipeline probes; no bounded fresh-state arming. Needs a forced undecided predecessor.")
review("slowlog.py", L, "time.sleep(0.2)", "Assumes every executor sees live-config changes after 200ms before recorder/latency assertions. Needs per-owner configuration acknowledgement.")
review("aclreply.py", L, "time.sleep(0.6)", "One-second blockers must remain parked through sleep/drain/revocation; coded-timeout reply is the actual regression oracle. Needs exact parking plus fresh timeout-window arming.")
review("notify.py", L, '"expire:lazy"', "Lazy-expiry key has 20ms TTL while notification config is being changed; it can expire while notifications are disabled. Needs expiry/config arming with an actual deadline witness.")
review("flip.py", B, "", "FLIP command/report conservation and placement checks; transition completion is witnessed.")
review("flip_under_load.py", L, "time.sleep(SECONDS)", "Fixed-duration worker/flipper run requires at least one accepted flip, without a witnessed load/flip interval. Needs a bounded until-witnessed phase preserving all data checks.")
review("flip_ttl.py", L, '"PX", str(TTL_MS)', "Fixed TTL must span all key setup and the owner move, but no witness proves expiry occurred after migration. Needs a held expiry/migration boundary.")
review("rlcache_churn.py", B, "while time.time() < deadline", "Bounded observation of cache/hit/move counters; hot keys are re-armed after owner movement and missing movement fails (GT13 retained).")
review("spinprobe.py", L, "LAND_SECONDS", "200ms assumes partial frame reached parser; one-second counter ceilings and three sampled attempts can race wakes. Needs parser-park publication plus bounded stationary counter windows.")
review("torture.py", L, "time.sleep(1)", "RST churn sends unacknowledged writes then requires at least one landed key after a fixed sleep. Needs a witness that the intended in-flight workload reached execution before disconnect.")
review("tls.py", L, "time.sleep", "Full partial-handshake/teardown legs assume progress after sleeps; auth-only selections are classified separately. Needs explicit handshake/teardown witnesses.")
review("xacct.py", L, "stream_ratio <", "Median stream/EXEC elapsed ratios are correctness-row thresholds; DEBUG reload itself is safe with all placement controllers disabled in debug jobs. Needs matched performance/work instrumentation.")
review("xmove.py", L, "time.sleep(0.0005)", "Atomic-off assumes a 500k-entry LREM stays in flight across two 500us sleeps, plus size-ratio timing. Reuse ATOMIC-OFF-HOP-HOLD for the LMOVE family after checking hook coverage; preserve the edge oracle.")
review("expireindex.py borrow_registry.py xshard_dispatch_scale.sh", L, "", "Size-scaling decisions use sampled elapsed-time ratios/rates. Needs a matched workload/stationarity measurement protocol without relaxing existing bounds.")
review("differ_gate.sh", L, "", "44-suite matrix retains s6fix random-key coverage, WAIT deadline sampling, stream auto-ID wall-clock allowance and climon push idle delimiters; see differential expansion below. Landed TTL windows, RESETSTAT rebasing and both-peer SAVE barriers are retained.")


def classify(row):
    site, name = row["gate_line"], row["name"]
    if site == 2823:
        return D, "Serverless ABBA/receipt/quietness/stall negative controls; these imports are not live batteries."
    if site == 2800 and re.search(r"feature 1s-\d-\d-\d-1$", name):
        return D, "Invalid fused plus flip-auto combination is rejected at boot by construction."
    if site in (2185, 2195):
        return L, "Save acceptance/completion now require witnesses, but capture may finish before the first post-cut mutation; the log claims overlap without proving it. Reload inherits that stimulus. Needs a held capture stage plus a required concurrent-mutation witness."
    if site in (2663, 2717, 2729):
        return D, "Certificate generation or complete auth handshakes; full partial-handshake timing legs are not selected."
    if site == 1287:
        return D, "Serverless fence state driver plus synthetic live-harness negative controls."
    if site in (1579,):
        return D, "Serverless namespace-boundary driver plus synthetic serial-history checker."
    if site == 1847:
        return D, "No-file ACL LOAD/SAVE error selection returns before blocked revocation cases."
    if site in (2443, 2465, 2500, 2510, 2521, 2609, 2622):
        return D, "Acknowledged persistence workload/recovery or completed shutdown counters; no background-admission timing assumption."
    if site == 816:
        return L, "Final read-local hit counter follows batteries containing RESETSTAT; later incidental local hits must repopulate it. Needs per-battery high-water witness as in differ_gate.sh."
    if site == 2736:
        return L, "Single recv after 400ms must contain the complete INFO field; TCP fragmentation can hide the gauge. Needs a framed RESP read, preserving the positive gauge assertion."
    if site == 2337:
        return L, "Sleep 3s assumes saturated producer, then sleep 1s assumes each requested FLIP landed. Needs witnessed offered-load stationarity and actual split completion."
    if site == 2387:
        return L, "Fixed 8s warmup/6s sample and 120k/s floor assume stable producer; elapsed sample is divided by a constant. Needs the gate's matched-load instrument."
    if row["scripts"]:
        candidates = [REVIEWS[path] for path in row["scripts"]]
        worst = max(candidates, key=lambda r: {D: 0, B: 1, L: 2}[r["kind"]])
        return worst["kind"], worst["mechanism"]
    static = {1191, 1751, 1761, 1763, 1765, 1767, 1769, 1772, 1775,
              2135, 2138, 2407, 2679, 2683, 2688}
    if site in static:
        return D, "Build/generated metadata, explicit grammar refusal, or synchronous DEBUG arm/disarm replies."
    lifecycle = {782, 796, 1862, 1865, 1886, 1894, 1917, 2127, 2304,
                 2368, 2722, 2765, 2780, 2783, 2786, 2793, 2870,
                 2913, 2920, 2962}
    if site in lifecycle:
        return B, "Observed boot/drain/transport state and required positive counters; bounded process completion, no sleep-only acceptance."
    raise ValueError(("unreviewed shell row", row))


def main():
    rows = build_inventory.rows()
    for ordinal, row in enumerate(rows, 1):
        row["ordinal"] = ordinal
        row["class"], row["mechanism"] = classify(row)
        row["sites"] = [f"{path}:{REVIEWS[path]['line']}" for path in row["scripts"]]
        selected_arms = {
            2663: ("tests/tls.py", "def generate("),
            2717: ("tests/tls.py", "def auth_matrix("),
            2729: ("tests/tls.py", "def auth_matrix("),
            2185: ("tests/snap_cut_battery.py", 'if MODE == "save":'),
            2195: ("tests/snap_cut_battery.py", 'elif MODE == "verify_cut":'),
        }
        if row["gate_line"] in selected_arms:
            path, marker = selected_arms[row["gate_line"]]
            line = next(i for i, text in enumerate((ROOT / path).read_text().splitlines(), 1)
                        if text.startswith(marker))
            row["sites"] = [f"{path}:{line}" if site.startswith(path + ":") else site
                            for site in row["sites"]]
        row["sites"].append("tests/gate.sh:" + str(row["gate_line"]))
    counts = Counter(row["class"] for row in rows)
    output = ["# Gate stimulus inventory", "",
              "Source baseline: origin/cpp f053e5930; test-only flakeaudit changes included. "
              "This is a source audit, not a full-gate execution receipt.", "",
              "The 517 public row occurrences below match the independently maintained ledger fixture "
              "in order and multiplicity (500 before the quick exit, 17 after). Duplicate labels are "
              "retained. Each battery takes its worst remaining stimulus class. A fixed polling interval "
              "or a watchdog alone is not a lottery: the required state must be observed before success. "
              "A finite race/coverage attempt without a forced or freshly re-armed witness is a lottery, "
              "including tests that can pass without entering their intended window.", "",
              "DETERMINISTIC: forced by hook/construction. BOUNDED-WITNESSED: requires the actual state "
              "before a finite bound. LOTTERY: residual timing, probabilistic coverage, or sampled "
              "performance/clock stimulus; see the mechanism and remaining-work register.", "",
              "; ".join(f"{key}: **{counts[key]}**" for key in (D, B, L)) + ". Total: **517**.", "",
              "| # | Row | Script:line (and gate declaration) | Class | Stimulus / residual mechanism |",
              "|---:|---|---|---|---|"]
    for row in rows:
        cells = [str(row["ordinal"]), row["name"], "; ".join(row["sites"]),
                 row["class"], row["mechanism"]]
        output.append("| " + " | ".join(cell.replace("|", "\\|") for cell in cells) + " |")
    differential = differ_reviews.reviews(ROOT)
    output += ["", "## Differential expansion (inside rows 515 and 516)", "",
               "These are the 44 discovered suites, one per line, not additional public gate rows. "
               "The gate runs each selected seed in RESP2 and RESP3, both atomic settings. "
               "The split-only mode-equivalence child uses exact streams across 32 configurations "
               "and the bounded feature witnesses (tests/mode_equivalence.py:294). "
               "Differential RESETSTAT high-water sampling is at tests/differ_gate.sh:259; "
               "the multidb stream returns to DB 0 and flushes data before its publication witness. "
               "Ordinary namespace cleanup does not restore arbitrary server configuration; "
               "the fanout wrapper explicitly carries the intended intset limit into the next atomic part.", "",
               "| Suite | Source | Class | Stimulus / residual mechanism |",
               "|---|---|---|---|"]
    for suite in differential:
        output.append("| " + " | ".join(suite[k].replace("|", "\\|")
                                       for k in ("name", "site", "kind", "mechanism")) + " |")
    (ROOT / "docs/flakeaudit/inventory.md").write_text("\n".join(output) + "\n")
    (ROOT / "docs/flakeaudit/rows.json").write_text(json.dumps(rows, indent=2) + "\n")
    (ROOT / "docs/flakeaudit/source-reviews.json").write_text(json.dumps(REVIEWS, indent=2, sort_keys=True) + "\n")
    (ROOT / "docs/flakeaudit/differ-reviews.json").write_text(json.dumps(differential, indent=2) + "\n")
    print(dict(counts))


if __name__ == "__main__":
    main()
