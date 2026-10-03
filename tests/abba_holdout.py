"""Independent identical-binary checks against frozen, published metric floors.

This is a holdout contract, not a new null collector or a code-comparison rule.
No statistic from the holdout can enlarge its bounds or choose its sample count.
"""
import copy

from abba_evidence import (canonical, digest, null_resolution, number, require,
                           resolution_summary)

CONTRACT = "published-null-two-sided-v1"


def blocks(row):
    return row["rounds"] + row.get("holdout_repeats", [])


def plan(control):
    """Copy the null's completed per-cell schedule, including its budget cap."""
    from abbagate import ORDER
    result = {}
    for row in control["cells"]:
        sampling = row.get("null_sampling_plan")
        count = sampling["planned_blocks"] if sampling else 1
        policy = sampling["policy"] if sampling else dict(
            maximum_blocks=1, samples_per_arm_per_block=ORDER.count("A"))
        require(len(row["rounds"]) == 1 and len(row.get("null_repeats", [])) + 1 == count,
                "holdout requires the null's completed single-load block plan")
        require(policy["samples_per_arm_per_block"] == ORDER.count("A") and
                1 <= count <= policy["maximum_blocks"], "unsupported published sampling budget")
        result[row["cell"]["id"]] = dict(instances=row["rounds"][0]["instances"],
            planned_blocks=count, samples_per_arm_per_block=policy["samples_per_arm_per_block"],
            maximum_blocks=policy["maximum_blocks"],
            budget_limited=sampling["budget_limited"] if sampling else False)
    return result


def quantum(metric, runs):
    """One output quantum, derived only from the published samples.

    Rate uses integer commands in the central window. memtier reports mean
    latency to .001 ms. Its HDR v2 tails have lowest=10 us, precision=2:
    8 us buckets below 2048 us, doubling at each subsequent power of two.
    These are the existing instrument's units, not fitted noise tolerances.
    """
    if metric == "rate":
        return max(1 / number(run["window_seconds"], "published window", positive=True) for run in runs)
    if metric == "latency_ms":
        return .001
    require(metric in ("p999_ms", "long_p999_ms"), "unknown holdout metric quantum")
    return max((1 << max(3, int(round(number(run[metric], "published tail", positive=True) * 1000))
                         .bit_length() - 1 - 7)) / 1000 for run in runs)


def floors(control, cell_id):
    from abbagate import resolution_bounds
    bound = resolution_bounds(control, cell_id)
    require(bound is not None, f"{cell_id}: missing published metric floors")
    row = next(row for row in control["cells"] if row["cell"]["id"] == cell_id)
    runs = [run for block in row["rounds"] + row.get("null_repeats", []) for run in block["runs"]]
    result = {}
    for metric, values in bound.items():
        reference = [number(run[metric], "published reference", positive=True) for run in runs if run["arm"] == "A"]
        mean = sum(reference) / len(reference)
        unit = quantum(metric, runs)
        # Convert one representable metric step, not a rounded display percent.
        # In binary floats .454 - .453 is slightly greater than literal .001.
        # Use the same subtraction as paired(), entirely on published values.
        quantum_pct = 100 * max(unit, abs((mean + unit) - mean), abs((mean - unit) - mean)) / mean
        result[metric] = dict(**values, quantum=unit, quantum_pct=quantum_pct,
            reference_mean=mean, threshold_pct=max(values["abs_delta"], values["spread"], quantum_pct))
    return result


def metric_rows(row):
    # Reuse the collector's signed pooling and maximum-spread arithmetic without
    # changing what a null measures or reclassifying any published null row.
    return null_resolution({"cells": [dict(cell=row["cell"], rounds=blocks(row))]})


def assess(cell, row, control):
    from abbagate import assess as ordinary_assess, NULL_MODE
    raw = blocks(row)
    assessments = [ordinary_assess(cell, [block], NULL_MODE) for block in raw]
    result = copy.deepcopy(assessments[0])
    reasons = [f"block {index}: {reason}" for index, item in enumerate(assessments, 1)
               for reason in item["reasons"]]
    limits = floors(control, cell.id)
    measured = metric_rows(row)
    validity = all(item["measurement_valid"] for item in assessments)
    judged = []
    for metric in measured:
        limit = limits[metric["metric"]]
        threshold = limit["threshold_pct"]
        delta_ok = metric["absolute_delta_pct"] <= threshold
        spread_ok = max(metric["reference_spread_pct"], metric["candidate_spread_pct"]) <= threshold
        if not delta_ok:
            reasons.append(f"{metric['metric']}: holdout |pooled delta| exceeds published floor")
        if not spread_ok:
            reasons.append(f"{metric['metric']}: holdout spread exceeds published floor")
        validity = validity and spread_ok
        judged.append(dict(**metric, **{key: limit[key] for key in
            ("threshold_pct", "quantum", "quantum_pct")},
            published_abs_delta_pct=limit["abs_delta"], published_spread_pct=limit["spread"],
            within_floor=delta_ok and spread_ok))
    primary = next(metric for metric in judged if metric["metric"] == cell.metric)
    loss = -primary["delta_pct"] if cell.metric == "rate" else primary["delta_pct"]
    result.update({key: primary[key] for key in
                   ("delta_pct", "reference_spread_pct", "candidate_spread_pct", "threshold_pct")})
    for arm in ("reference", "candidate"):
        values = [run[cell.metric] for block in raw for run in block["runs"]
                  if run["arm"] == ("A" if arm == "reference" else "B")]
        result[arm], result[arm + "_mean"] = values, sum(values) / len(values)
    result.update(threshold_source=CONTRACT, holdout_metrics=judged,
                  loss_pct=loss, margin_pct=max(max(m["absolute_delta_pct"], m["reference_spread_pct"],
                      m["candidate_spread_pct"]) - m["threshold_pct"] for m in judged),
                  long_tail=next((m for m in judged if m["metric"] == "long_p999_ms"), None),
                  measurement_valid=validity, verdict="FAIL" if reasons else "PASS", reasons=reasons)
    return result


def validate_structure(report):
    from abbagate import ORDER
    require(report.get("holdout_contract") == CONTRACT, "missing fixed published-floor holdout contract")
    require(isinstance(report.get("holdout_plan"), dict), "missing published holdout block plan")
    for row in report["cells"]:
        expected = report["holdout_plan"].get(row["cell"]["id"])
        require(isinstance(expected, dict), "missing holdout cell plan")
        require(not row.get("null_repeats") and "null_sampling_plan" not in row,
                "holdout cannot borrow null samples")
        require(len(row["rounds"]) == 1, "holdout requires one frozen load")
        for ordinal, block in enumerate(blocks(row)):
            require(block["instances"] == expected["instances"] and
                    block.get("sample_offset", 0) == ordinal * len(ORDER) and
                    [run.get("arm") for run in block["runs"]] == list(ORDER),
                    "holdout repeat order/load differs from published plan")


def collect(cell, row, control, measure, persist):
    """Complete the precommitted schedule, even if an earlier block is outside."""
    from abbagate import ORDER
    expected = plan(control)[cell.id]
    row["holdout_repeats"] = []
    persist()
    for ordinal in range(1, expected["planned_blocks"]):
        block = dict(instances=expected["instances"], sample_offset=ordinal * len(ORDER), runs=[])
        row["holdout_repeats"].append(block)
        for sequence, arm in enumerate(ORDER, 1 + block["sample_offset"]):
            block["runs"].append(measure(arm, sequence, block["instances"]))
        persist()
    row["assessment"] = assess(cell, row, control)
    row["verdict"] = row["assessment"]["verdict"]


def rejudge(report, control):
    """Evaluate saved raw data; callers must retain its original identity/time."""
    from abbagate import Cell, overall
    report.update(run_kind="null-holdout", holdout_contract=CONTRACT, holdout_plan=plan(control),
                  comparison_trusted=False)
    for row in report["cells"]:
        row["assessment"] = assess(Cell(**row["cell"]), row, control)
        row["verdict"] = row["assessment"]["verdict"]
    report["statistical_verdict"], report["worst_cell"] = overall(report["cells"])
    report["verdict"] = report["statistical_verdict"]
    return report


def resolution(report, control, *, historical=False):
    """Retain every failure and sample deficit; a replay never certifies a run."""
    expected = plan(control)
    require(report["holdout_plan"] == expected, "holdout plan differs from published null")
    differences = [dict(cell=row["cell"]["id"], measured_blocks=len(blocks(row)),
                        **expected[row["cell"]["id"]]) for row in report["cells"]
                   if len(blocks(row)) != expected[row["cell"]["id"]]["planned_blocks"]]
    metrics = [metric for row in report["cells"] for metric in row["assessment"]["holdout_metrics"]]
    failures = [dict(cell=row["cell"]["id"], reasons=row["assessment"]["reasons"])
                for row in report["cells"] if row["verdict"] != "PASS"]
    verdict = "FAIL" if failures or differences else "PASS"
    return dict(kind="independent-null-holdout", contract=CONTRACT, verdict=verdict,
        floor_verdict="FAIL" if failures else "PASS", failures=failures, metrics=metrics,
        plan_matches=not differences, plan_differences=differences,
        independent_resolution="PASS" if verdict == "PASS" and not historical else "PENDING HOLDOUT",
        reporting_only=historical, resolution_summary=resolution_summary(report, control),
        control_sha256=digest(canonical(control)), comparison_sha256=digest(canonical(report)),
        ceiling_only_cells={row["cell"]["id"]: row["cell"]["ceiling_status"]
                            for row in control["cells"] if row["cell"].get("ceiling_status")},
        cycles_op_resolution="UNPROVEN", full_gate_receipt=False)
