#!/usr/bin/env python3
"""Shared ABBA measurement and standing-null evidence; never changes an assessment threshold."""
from datetime import datetime, timezone
import hashlib
import json
import math
import re

from abba_instrument import validate_fingerprint
from abba_saturation import (replay_saturation, require_saturation_window, SATURATION_FLOOR,
                             RUN_SATURATION_MARGIN, saturation_exempt)

ORDER = ["A", "B", "B", "A"]
NULL_MAX_AGE = 24 * 60 * 60


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value, label, *, positive=False):
    require(type(value) in (int, float) and math.isfinite(value) and
            (value > 0 if positive else value >= 0), f"invalid {label}")
    return value


def signed_number(value, label):
    require(type(value) in (int, float) and math.isfinite(value), f"invalid {label}")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def utc_seconds(value):
    require(isinstance(value, str), "missing ABBA start timestamp")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()


def validate_quiet(quiet, environment, *, now, started, elapsed):
    """Replay scoped preflight evidence; never authenticate unrelated processes.

    The live observer reads only the requested /proc/stat CPU rows. During a
    benchmark those totals include our own load, so runtime samples are retained
    as observations and the CPU budget applies to the quiet preflight only.
    """
    require(isinstance(quiet, dict), "invalid quiet-box evidence")
    require(quiet.get("policy") == "selected-core-port-budget-v1",
            "missing or unsupported selected-core quiet-box policy")
    require(quiet.get("complete") is True and quiet.get("interference", "missing") is None,
            "quiet-box evidence missing, incomplete, or contended")
    qstart = number(quiet.get("started_at"), "quiet start", positive=True)
    qend = number(quiet.get("finished_at"), "quiet end", positive=True)
    number(quiet.get("sample_interval_seconds"), "quiet sample interval", positive=True)
    samples = quiet.get("samples")
    require(type(samples) is int and samples >= 2 and qstart < qend <= now + 1,
            "quiet observer did not complete its sampling interval")
    require(type(quiet.get("cpu_samples")) is int and quiet["cpu_samples"] == samples and
            isinstance(quiet.get("sample_artifact"), str) and quiet["sample_artifact"],
            "selected CPU observations did not cover every quiet sample")
    selected = set(environment["server_cpus"] + environment["load_cpus"])
    for field in ("cpus", "requested_cpus"):
        value = quiet.get(field)
        require(isinstance(value, list) and all(type(cpu) is int for cpu in value) and
                len(value) == len(set(value)) and set(value) == selected,
                "quiet observer did not watch exactly the measurement CPUs")
    ports = quiet.get("ports")
    require(isinstance(ports, list) and ports and
            all(type(port) is int and 0 < port <= 65535 for port in ports) and
            len(ports) == len(set(ports)) and ports == [environment.get("port")] and
            type(quiet.get("listener_checks")) is int and quiet["listener_checks"] >= 1,
            "quiet observer did not check its intended ports")
    screening = quiet.get("generic_cpu_screening")
    require(isinstance(screening, dict) and screening.get("scope") == "preflight",
            "quiet CPU screening must identify its preflight scope")
    require(screening.get("capacity_fraction") == .0015 and
            screening.get("server_physical_cores") == len(environment["server_physical"]),
            "quiet CPU screening policy or server core count changed")
    # The budget is denominated in the cores the guard actually SAMPLED. sample() sums busy ticks
    # over server AND load CPUs, so a server-only denominator judged 112 cores of idle noise against
    # a 32-core allowance and refused every run by ~1% (2026-09-11). A record that states its
    # sampled count must match server+load exactly; a legacy record without it is server-only.
    sampled = screening.get("sampled_physical_cores")
    if sampled is None:
        sampled = len(environment["server_physical"])
    else:
        require(sampled == len(environment["server_physical"]) + len(environment["load_physical"]),
                "quiet CPU screening sampled-core count differs from server+load")
    window = number(screening.get("window_seconds"), "quiet screening window", positive=True)
    budget = number(screening.get("cpu_budget_seconds"), "quiet CPU budget", positive=True)
    require(math.isclose(budget, .0015 * sampled * window,
                         rel_tol=1e-12, abs_tol=0), "quiet CPU budget differs from its fixed policy")
    peak = screening.get("peak_rolling")
    require(isinstance(peak, dict) and
            number(peak.get("cpu_seconds"), "quiet peak CPU seconds") <= budget,
            "quiet preflight exceeded its CPU budget")
    require(number(screening.get("preflight_seconds"), "quiet preflight duration", positive=True) >= window,
            "quiet preflight did not cover its screening window")
    # The final sample precedes complete. Count * interval is not an elapsed-time
    # bound because sampling itself takes time; timestamps and measured windows
    # independently prevent a preflight-only report from certifying a comparison.
    require(started <= qstart and qend <= started + elapsed + 1,
            "quiet timestamps are outside this ABBA run")
    return qstart, qend


def validate_measurements(report, *, now, expected_source=None, expected_cells=None, harness=None, candidate=None,
                          expected_instrument=None):
    require(isinstance(report, dict), "ABBA evidence must be a JSON object")
    holdout = report.get("run_kind") == "null-holdout"
    outcomes = (("PASS", "FAIL") if holdout else
                ("PASS", "UNRESOLVED") if report.get("run_kind") == "comparison" else ("PASS",))
    require(report.get("schema") == 1 and report.get("statistical_verdict") in outcomes and
            report.get("verdict") in (*outcomes, "PARTIAL"), "ABBA measurements did not all pass")
    require(report.get("measurement_valid") is True, "ABBA measurement validity was not certified")
    require(report.get("run_kind") in ("comparison", "null-control", "null-holdout") and
            report.get("normal_gate_eligible", True) is True,
            "diagnostic background qualification cannot certify ABBA measurements")
    require(re.fullmatch(r"[0-9a-f]{64}", report.get("receipt_harness_sha256", "")), "missing ABBA harness digest")
    require(harness is None or report["receipt_harness_sha256"] == harness, "ABBA harness differs")
    instrument_sha = validate_fingerprint(report.get("instrument_fingerprint"))
    require(expected_instrument is None or instrument_sha == validate_fingerprint(expected_instrument),
            "ABBA measurement instrument differs")
    require(report.get("order") == ORDER, "ABBA sequence changed")
    started = utc_seconds(report.get("started_utc"))
    elapsed = number(report.get("elapsed_seconds"), "ABBA elapsed seconds", positive=True)
    require(started <= now and started + elapsed <= now + 1, "ABBA timestamps are incomplete or in the future")
    number(report.get("window_seconds"), "ABBA window", positive=True)
    source = report.get("cell_source", {})
    require(isinstance(source, dict) and isinstance(source.get("text"), str), "invalid ABBA cell source")
    require(re.fullmatch(r"[0-9a-f]{64}", source.get("sha256", "")) and
            digest(source.get("text", "").encode()) == source["sha256"] and
            type(source.get("total_cells")) is int and source["total_cells"] > 0,
            "invalid ABBA inventory provenance")
    if expected_source is not None:
        require(source["sha256"] == expected_source["sha256"] and
                source["total_cells"] == expected_source.get("total_cells", expected_source.get("count")),
                "ABBA inventory does not match current cell file")
    rows = report.get("cells", [])
    require(isinstance(rows, list) and rows and all(isinstance(row, dict) for row in rows), "unreached ABBA cell set")
    cells = [row.get("cell", {}) for row in rows]
    require(all(isinstance(cell, dict) for cell in cells), "invalid ABBA cell parameters")
    ids = [cell.get("id") for cell in cells]
    require(all(isinstance(ident, str) and ident for ident in ids) and len(set(ids)) == len(ids),
            "missing/duplicate ABBA cell identity")
    require(expected_cells is None or cells == expected_cells, "ABBA parameters or selected cells differ")
    require(isinstance(report.get("coverage"), dict), "invalid ABBA coverage")
    require(report["coverage"].get("ids") == ids and report["coverage"].get("count") == len(ids) and
            len(ids) <= source["total_cells"], "ABBA coverage omits or repeats selected cells")
    if report.get("subset") == "full" and not report.get("only"):
        require(len(ids) == source["total_cells"], "full ABBA coverage is incomplete")
    require(not report["coverage"].get("pending_pins"), "ABBA still has unmeasured load floors")
    for arm in ("candidate", "reference"):
        require(isinstance(report.get(arm), dict), f"invalid {arm} identity")
        require(re.fullmatch(r"[0-9a-f]{64}", report.get(arm, {}).get("sha256", "")), f"missing {arm} binary digest")
    require(candidate is None or report["candidate"]["sha256"] == candidate["sha256"], "ABBA measured another candidate binary")
    environment = report.get("environment", {})
    require(isinstance(environment, dict), "invalid ABBA environment")
    require(environment.get("python_runtime") == report["instrument_fingerprint"]["python"],
            "Python measurement environment differs from the instrument identity")
    for key in ("server_cpus", "load_cpus", "server_physical", "load_physical"):
        value = environment.get(key)
        require(isinstance(value, list) and value and all(type(cpu) is int and cpu >= 0 for cpu in value)
                and len(value) == len(set(value)), f"invalid ABBA {key}")
    require(len(environment["server_physical"]) <= 32 and
            not set(environment["server_cpus"]) & set(environment["load_cpus"]), "invalid regression CPU allocation")
    for key in ("uname", "memtier_sha256", "memtier_version", "keys", "data_bytes", "key_pattern", "split_ratio", "population_by_arm"):
        require(environment.get(key), f"missing measurement environment: {key}")
    from abba_ceiling import validate_ceiling_controls
    validate_ceiling_controls(report, cells)
    qstart, qend = validate_quiet(report.get("quiet_box"), environment, now=now,
                                  started=started, elapsed=elapsed)
    windows = 0
    if holdout:
        from abba_holdout import validate_structure
        validate_structure(report)
    for cell, row in zip(cells, rows):
        if "null_sampling_policy" in report:
            require(report.get("run_kind") == "null-control", "comparison cannot borrow null repeats")
            from abba_null_sampling import validate
            validate(row, report["null_sampling_policy"])
        else:
            require(not row.get("null_repeats") and "null_sampling_plan" not in row,
                    "null repeats lack a frozen sampling policy")
        require(holdout or not row.get("holdout_repeats"), "comparison cannot borrow holdout repeats")
        require(row.get("verdict") in outcomes and row.get("instrument_valid", True) is True,
                f"nonpassing ABBA cell: {cell['id']}")
        assessment = row.get("assessment", {})
        require(isinstance(assessment, dict), "invalid ABBA assessment")
        require(assessment.get("verdict") == row["verdict"] and
                (holdout or assessment.get("reasons") == []),
                f"unassessed/failed ABBA cell: {cell['id']}")
        exempt = saturation_exempt(cell)
        require(assessment.get("saturation_exempt") is exempt, "invalid saturation exemption")
        ceiling_status = cell.get("ceiling_status", "")
        if ceiling_status:
            require(assessment.get("ceiling_status") == ceiling_status and
                    assessment.get("capacity_claim") == "ceiling-load-only" and
                    assessment.get("load_selection", {}).get("status") == "CEILING",
                    "ceiling control claimed a saturated peak")
        # A null-control run MEASURES the loss-vs-threshold discrepancy on identical bytes -- that
        # discrepancy is the instrument's resolution, and enforcing it here would make the null
        # unable to report the very thing it exists to report. Comparison runs store a threshold
        # already floored by the standing null, so the check stays exact for them.
        if report.get("run_kind") == "comparison":
            require(signed_number(assessment.get("loss_pct"), "loss") <=
                    number(assessment.get("threshold_pct"), "threshold"), "cell loss exceeds its threshold")
        judged_occupancy = []
        rounds = row.get("rounds", [])
        require(isinstance(rounds, list) and rounds and all(isinstance(block, dict) for block in rounds),
                f"unreached ABBA cell: {cell['id']}")
        require(sum(block.get("instances") == assessment.get("instances") for block in rounds) == 1,
                "assessment does not identify exactly one measured load block")
        for block in rounds + row.get("null_repeats", []) + row.get("holdout_repeats", []):
            runs = block.get("runs", [])
            require(isinstance(runs, list) and all(isinstance(run, dict) for run in runs), "invalid ABBA runs")
            require([run.get("arm") for run in runs] == ORDER, "incomplete or reordered ABBA measurements")
            for index, run in enumerate(runs, 1 + block.get("sample_offset", 0)):
                require(run.get("complete") is True and not run.get("error") and
                        run.get("artifacts") == f"{cell['id']}/n{block['instances']}-{index}-{run['arm']}",
                        f"incomplete measurement: {cell['id']}")
                for field in ("rate", "latency_ms", "window_seconds", "commands"):
                    number(run.get(field), "measurement " + field, positive=True)
                require(run["window_seconds"] >= report["window_seconds"], "shortened measurement window")
                # A standing null cannot borrow a cached PASS or scalar CPU reading.
                # Recompute the productive-role witness from the same raw deltas
                # used by the live driver, for both arms and all retained probes.
                saturation = replay_saturation(run.get("saturation"), floor_pct=SATURATION_FLOOR,
                    mode=cell["mode"], thread_count=len(environment["server_cpus"]))
                central_saturation = require_saturation_window(saturation, run)
                if not exempt and not ceiling_status and block["instances"] == assessment["instances"]:
                    # Per-RUN, so it reproduces the min() bias the assessment moved away from: a cell
                    # sitting near the floor fails whenever any one of four samples dips under. The
                    # occupancy of the judged block is collected here and checked once, against the
                    # BLOCK MEAN, exactly as assess() does (t01, 2026-09-12: 94.24/95.35/95.39/95.21
                    # on identical bytes, mean 95.05 vs a 95 floor).
                    judged_occupancy.append(central_saturation)
                require(type(run.get("pid")) is int and run["pid"] > 0, "measurement never booted a server")
                if cell["op"] == "REORDER":
                    number(run.get("p999_ms"), "short p99.9", positive=True)
                    number(run.get("long_p999_ms"), "long p99.9", positive=True)
                windows += run["window_seconds"]
        if judged_occupancy:
            scores = [number(x.get("score_pct"), "productive-role occupancy", positive=True)
                      for x in judged_occupancy]
            mean = sum(scores) / len(scores)
            require(mean >= SATURATION_FLOOR and min(scores) >= SATURATION_FLOOR - RUN_SATURATION_MARGIN,
                    f"{cell['id']}: judged block is below the productive-role floor "
                    f"(mean {mean:.2f}%, worst {min(scores):.2f}%, floor {SATURATION_FLOOR:g}%)")
    require(qend - qstart >= windows, "quiet observer did not span all measurement windows")
    return started, environment


def null_resolution(report):
    """A byte-identical gain is instrument error just as a loss is.

    Comparison assessments deliberately reject only regressions. A null records
    BOTH signs of the paired delta against the measured spreads of both arms. Recompute from every raw block, including unselected escalation probes:
    neither a cached PASS nor selecting another rung may hide a failed control.
    There is no new floor, multiplier, or change to a code comparison's threshold.
    The range of two reference samples is not a confidence or prediction bound:
    even small, zero-bias Gaussian noise can fail this check. Repeated all-cell
    certification still needs measured calibration with independent validation,
    or an improved instrument; passing one null does not establish its resolution.
    """
    from abbagate import MAX_SPREAD
    evidence = []
    for row in report["cells"]:
        cell = row["cell"]
        metric = {"auto": "latency_ms" if cell["depth"] == 1 else "rate",
                  "rate": "rate", "latency": "latency_ms", "p999": "p999_ms"}.get(cell.get("score", "auto"))
        require(metric is not None, f"unknown scored null metric: {cell['id']}")
        metrics = [metric] + (["long_p999_ms"] if metric == "p999_ms" else [])
        grouped = {}
        for block in row["rounds"] + row.get("null_repeats", []):
            grouped.setdefault(block["instances"], []).append(block)
        for instances, blocks in grouped.items():
            metrics_evidence = {scored: [] for scored in metrics}
            for block in blocks:
                runs = block["runs"]
                require([run.get("arm") for run in runs] == ORDER, "incomplete or reordered null block")
                for scored in metrics:
                    metrics_evidence[scored].append([
                        number(run.get(scored), "null " + scored, positive=True) for run in runs])
            for scored, samples in metrics_evidence.items():
                # Pool SIGNED paired differences, weighted by their reference sums.
                # Every equally long block contributes all four samples, including
                # the pilot. Absolute value is taken only after pooling: averaging
                # absolute errors estimates noise magnitude, not the arm bias.
                a1, b1, b2, a2 = [sum(values[index] for values in samples) for index in range(len(ORDER))]
                denominator = number(a1 + a2, "null reference sum", positive=True)
                delta = signed_number(100 * ((b1 - a1) + (b2 - a2)) / denominator, "null paired delta")
                threshold = number(max(200 * abs(a - d) / (a + d) for a, b, c, d in samples),
                                   "null reference spread")
                candidate_spread = number(max(200 * abs(b - c) / (b + c) for a, b, c, d in samples),
                                          "null candidate spread")
                evidence.append(dict(cell=cell["id"], instances=instances, metric=scored,
                                     delta_pct=delta, absolute_delta_pct=abs(delta),
                                     reference_spread_pct=threshold, candidate_spread_pct=candidate_spread,
                                     status="RESOLVING" if max(threshold, candidate_spread, abs(delta)) <= MAX_SPREAD
                                            else "UNRESOLVED",
                                     within_reference_spread=abs(delta) <= threshold))
    return evidence


def null_result(report, *, now):
    validate_measurements(report, now=now)
    require(report.get("run_kind") == "null-control" and report.get("comparison_trusted") is False and
            report.get("verdict") == "PARTIAL", "control collection is not a code-comparison PASS")
    require(report["candidate"]["sha256"] == report["reference"]["sha256"], "null arms are not byte-identical")
    population = report["environment"]["population_by_arm"]
    require(isinstance(population, dict) and set(population) == {"A", "B"} and
            all(isinstance(value, str) and value for value in population.values()) and
            population["A"] == population["B"], "null arms used different population methods")
    return {"verdict": "PASS", "binary_sha256": report["candidate"]["sha256"],
            "ids": report["coverage"]["ids"], "resolution": null_resolution(report)}


def validate_null(report, *, now):
    # Validate every collected cell before matching a requested subset. A failed full control
    # cannot donate just its passing smoke rows: that would hide the instrument's own failure.
    expected = null_result(report, now=now)
    require(report.get("null_control") == expected, "null control did not complete and pass")
    return utc_seconds(report["started_utc"]), report["environment"]


def instrument(environment):
    # Ports and executable pathnames do not alter the experiment. Every other current or future
    # field must match, including the generator digest and each arm's population method.
    return {key: value for key, value in environment.items()
            if key not in ("port", "permitted_ports", "memtier_path")}


def validate_workload_evidence(cell, run, *, report=None):
    from abba_workloads import require_workload_accounting, require_workload_witness
    from abba_reorder_control import validate_proof, refusal_hint
    require(run.get("data_bytes") == cell.data_bytes, f"{cell.id}: measured workload value size differs")
    raw = run.get("workload_raw")
    require(isinstance(raw, dict), f"{cell.id}: missing raw workload witness")
    try:
        proof = raw.get("read_local_control")
        if proof is not None:
            binary = (report["candidate" if run["arm"] == "B" else "reference"]["sha256"]
                      if report else None)
            validate_proof(proof, binary_sha256=binary)
        witness = require_workload_witness(cell, raw["before"], raw["after"],
            raw["mode_before"], raw["mode_after"], raw.get("legacy_control"), proof)
        accounting = require_workload_accounting(cell, run["whole_run_commandstats_before"],
            run["whole_run_commandstats_after"], run["memtier"])
    except (RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
        hint = refusal_hint(cell.id, report) if cell.op == "REORDER" and cell.read_local and cell.reorder else ""
        raise ValueError(f"{cell.id}: invalid raw workload: {error}{hint}") from error
    require(witness == run.get("workload_witness"), f"{cell.id}: workload witness differs")
    require(accounting == run.get("whole_run_accounting"), f"{cell.id}: workload accounting differs")


def validate_campaign_evidence(report):
    """Replay the completed frozen campaign, including raw workload witnesses.

    This is stricter than the historical diagnostic report reader. Promotions
    and their subsequent comparisons require this evidence, including exempt cells.
    No occupancy or plateau waiver can waive completion or the intended workload.
    """
    from abbagate import Cell, assess, NULL_MODE, load_layout
    require(report.get("complete") is True and report.get("process_cleanup") ==
            {"complete": True, "remaining": 0} and not report.get("error"),
            "campaign incomplete or owned processes unreaped")
    require(report.get("subset") == "full" and not report.get("only") and not report.get("escalate"),
            "campaign requires full coverage without only/subset/escalation salvage")
    layouts = {}
    for row in report["cells"]:
        cell = Cell(**row["cell"])
        plan = [cell.instances or 1]
        require([block["instances"] for block in row["rounds"]] == plan,
                f"{cell.id}: measured load ladder differs from frozen plan")
        if "null_sampling_policy" in report:
            require(report.get("run_kind") == "null-control", "comparison cannot borrow null repeats")
            from abba_null_sampling import validate
            validate(row, report["null_sampling_policy"])
        else:
            require(not row.get("null_repeats") and "null_sampling_plan" not in row,
                    "null repeats lack a frozen sampling policy")
        require(report.get("run_kind") == "null-holdout" or not row.get("holdout_repeats"),
                "comparison cannot borrow holdout repeats")
        for block in row["rounds"] + row.get("null_repeats", []) + row.get("holdout_repeats", []):
            key = (block["instances"], cell.conns)
            if key not in layouts:
                layouts[key] = load_layout(report["environment"]["load_cpus"], *key)
            for run in block["runs"]:
                require(run.get("instances") == block["instances"] and run.get("load_layout") ==
                        layouts[key],
                        f"{cell.id}: generator layout differs from frozen plan")
                validate_workload_evidence(cell, run, report=report)
            replay = assess(cell, [block], NULL_MODE)
            require(replay["measurement_valid"] and replay["verdict"] == "PASS",
                    f"{cell.id}: raw campaign block failed: {replay['reasons']}")
        # NULL_MODE replays saturation/load validity without applying a code-loss
        # threshold. Two-sided resolution/integrity is checked independently below.
        replay = assess(cell, row["rounds"], NULL_MODE)
        require(replay["measurement_valid"] and replay["verdict"] == "PASS",
                f"{cell.id}: raw campaign assessment failed: {replay['reasons']}")


def validate_null_integrity(report):
    # Integrity means complete, finite raw evidence, not a veto on the very
    # resolution this experiment measures. Publication also replays the campaign,
    # identities and workload witnesses. Large errors remain visible UNRESOLVED.
    rows = null_resolution(report)
    require(bool(rows), "empty null resolution")
    if report.get("run_kind") == "null-control":
        require(report.get("null_control", {}).get("resolution") == rows,
                "published null resolution/status differs from raw evidence")
    return rows


def resolution_summary(report, control=None):
    """Name every cell and scored row; unresolved observations never earn PASS."""
    source = control if control is not None else report
    rows = ((source.get("null_control") or {}).get("resolution", [])
            if isinstance(source, dict) else [])
    selected = {row["cell"]["id"] for row in report.get("cells", [])}
    statuses = {status: sorted({f"{row['cell']}/{row['metric']}" for row in rows
                if row["cell"] in selected and row.get("status") == status})
                for status in ("RESOLVING", "UNRESOLVED")}
    unresolved = sorted({name.split("/")[0] for name in statuses["UNRESOLVED"]})
    resolving = sorted({name.split("/")[0] for name in statuses["RESOLVING"]} - set(unresolved))
    passed = sorted(row["cell"]["id"] for row in report.get("cells", [])
                    if report.get("run_kind") == "comparison" and row.get("verdict") == "PASS" and
                    row["cell"]["id"] in resolving)
    return dict(resolving_cells=resolving, unresolved_cells=unresolved,
                resolving_rows=statuses["RESOLVING"], unresolved_rows=statuses["UNRESOLVED"],
                pass_evidence_cells=passed)


def resolution_text(summary):
    return "; ".join(f"{label}={len(summary[key])} [{','.join(summary[key])}]" for label, key in
                     (("RESOLVING", "resolving_cells"), ("UNRESOLVED", "unresolved_cells"),
                      ("PASS evidence", "pass_evidence_cells")))


def validate_holdout(comparison, control, *, now, historical=False):
    """Independent two-sided check against ONLY the already frozen null errors.

    This certifies observed rate/latency/tail resolution, never a prediction bound
    or cycles/op. The diagnostic PMU's wider window/central-command denominator
    cannot supply aligned cycles/op evidence for this instrument.
    """
    from abba_holdout import resolution
    require(comparison.get("run_kind") == "null-holdout" and comparison.get("comparison_trusted") is False,
            "holdout requires explicit identical-binary mode; never code-comparison certification")
    matched = match_null(comparison, control, now=now)
    require(comparison.get("standing_null") == matched, "holdout's matched null evidence differs")
    require(comparison["candidate"]["sha256"] == comparison["reference"]["sha256"] ==
            control["candidate"]["sha256"], "holdout requires the frozen byte-identical binary")
    require(comparison["coverage"] == control["coverage"], "holdout requires the complete frozen population")
    return resolution(comparison, control, historical=historical)


def match_null(comparison, control, *, now):
    from abba_standing_null import artifact_scope
    with artifact_scope(control):
        return _match_null(comparison, control, now=now)


def match_null_identity(comparison, control):
    """Reject a stale default before it can supply assessment floors."""
    require(isinstance(control, dict), "standing null must be a JSON object")
    require(comparison.get("instrument_fingerprint") == control.get("instrument_fingerprint"),
            "null instrument differs; recollect with the current fingerprint (archived null remains historical)")
    require(comparison["cell_source"]["sha256"] == control["cell_source"]["sha256"] and
            comparison["cell_source"]["total_cells"] == control["cell_source"]["total_cells"],
            "null inventory differs; publish a null covering the current inventory")


def _match_null(comparison, control, *, now):
    require(comparison.get("run_kind") in ("comparison", "null-holdout"),
            "a null collection cannot replace a regression comparison")
    match_null_identity(comparison, control)
    started, environment = validate_measurements(comparison, now=now)
    null_started, null_environment = validate_null(control, now=now)
    if "promotion" in control or comparison.get("run_kind") == "null-holdout":
        from abbagate import Cell, assess, resolution_bounds
        validate_campaign_evidence(control)
        validate_campaign_evidence(comparison)
        validate_null_integrity(control)
        for row in comparison["cells"]:
            if comparison.get("run_kind") == "null-holdout":
                from abba_holdout import assess as assess_holdout
                replay = assess_holdout(Cell(**row["cell"]), row, control)
            else:
                replay = assess(Cell(**row["cell"]), row["rounds"], resolution_bounds(control, row["cell"]["id"]))
            require(row["assessment"] == replay,
                    f"{row['cell']['id']}: cached comparison assessment differs from raw replay")
    require(0 <= started - null_started <= NULL_MAX_AGE,
            "standing null is from the future or more than 24 hours old")
    require(null_started + control["elapsed_seconds"] <= started + 1,
            "standing null did not finish before this comparison started")
    # Correctness tests/hooks may change between a null and a later comparison.
    # Both reports still carry the broad release hash; only the actual instrument
    # must match here. Old reports without scoped provenance fail validation above.
    require(comparison["instrument_fingerprint"] == control["instrument_fingerprint"], "null instrument differs")
    require(comparison["cell_source"]["sha256"] == control["cell_source"]["sha256"] and
            comparison["cell_source"]["total_cells"] == control["cell_source"]["total_cells"],
            "null inventory differs")
    require(comparison["window_seconds"] == control["window_seconds"], "null used another measurement window")
    require(instrument(environment) == instrument(null_environment), "null used another geometry or measurement environment")
    by_id = {row["cell"]["id"]: row["cell"] for row in control["cells"]}
    plans = {row["cell"]["id"]: [block["instances"] for block in row["rounds"]]
             for row in control["cells"]}
    for row in comparison["cells"]:
        require(by_id.get(row["cell"]["id"]) == row["cell"],
                f"null does not cover this exact cell: {row['cell']['id']}")
        require(plans[row["cell"]["id"]] == [block["instances"] for block in row["rounds"]],
                f"null used another measured load ladder: {row['cell']['id']}")
    return {"status": "MATCHED", "sha256": digest(canonical(control)),
            "control_binary_sha256": control["candidate"]["sha256"],
            "matched_ids": comparison["coverage"]["ids"], "age_seconds": started - null_started}


def validate_comparison(comparison, control, *, now):
    summary = resolution_summary(comparison, control)
    require(not summary["unresolved_cells"], "comparison reporting-only: " + resolution_text(summary))
    require(comparison.get("verdict") == "PASS" and comparison.get("comparison_trusted") is True and
            not comparison.get("only"), "comparison is partial or lacks standing-null certification")
    matched = match_null(comparison, control, now=now)
    require(comparison.get("standing_null") == matched, "comparison's matched null evidence differs")
    return utc_seconds(comparison["started_utc"]), comparison["environment"]
