"""Precommitted, pilot-sized null repeats; raw spread failures are never erased.

The initial planned block is the pilot. Its pooled within-arm sample variance
estimates the per-sample CV. n = ceil((CV / MAX_SPREAD)**2) is the sample count
per arm for a mean's one-standard-error scale, NOT a confidence bound on a loss.
Complete ABBA blocks round n upwards. An unresolved pilot gets at least the
existing PIN_NULL_BLOCKS confirmation count; at most that many blocks per
within-block arm sample are affordable. This reuses the instrument's replication
policy and ORDER, with no new numeric threshold or machine tuning constant.

The policy is frozen before the campaign; the exact sample size is frozen after
the pilot, before repeats. All planned repeats must finish even if one looks good.
Pilot and repeats all contribute to the pooled delta and maximum raw spreads.
"""
import math
import statistics


def policy():
    from abbagate import ORDER, PIN_NULL_BLOCKS
    return dict(method="pilot-cv-fixed-repeats-v1", minimum_blocks=PIN_NULL_BLOCKS,
                maximum_blocks=PIN_NULL_BLOCKS * ORDER.count("A"),
                samples_per_arm_per_block=ORDER.count("A"))


def plan(row):
    from abbagate import MAX_SPREAD, ORDER
    from abba_evidence import null_resolution, number, require
    require(len(row["rounds"]) == 1, "null repeat pilot requires one frozen load block")
    pilot = {"cell": row["cell"], "rounds": row["rounds"]}
    resolution = null_resolution({"cells": [pilot]})
    runs = row["rounds"][0]["runs"]
    metrics = []
    for resolved in resolution:
        arms = [[number(run.get(resolved["metric"]), "null CV sample", positive=True)
                 for run in runs if run["arm"] == arm] for arm in dict.fromkeys(ORDER)]
        values = [value for arm in arms for value in arm]
        degrees = sum(len(arm) - 1 for arm in arms)
        variance = sum(sum((value - statistics.mean(arm))**2 for value in arm) for arm in arms) / degrees
        cv = number(100 * math.sqrt(variance) / statistics.mean(values), "null pooled CV")
        samples = max(len(arms[0]), math.ceil((cv / MAX_SPREAD)**2))
        metrics.append(dict(metric=resolved["metric"], pilot_cv_pct=cv, required_samples_per_arm=samples,
                            pilot_status=resolved["status"]))
    rule = policy()
    required = max(math.ceil(metric["required_samples_per_arm"] / rule["samples_per_arm_per_block"])
                   for metric in metrics)
    unresolved = any(metric["pilot_status"] == "UNRESOLVED" for metric in metrics)
    blocks = min(rule["maximum_blocks"], max(rule["minimum_blocks"], required)) if unresolved else 1
    return dict(policy=rule, metrics=metrics, required_blocks=required, planned_blocks=blocks,
                budget_limited=unresolved and required > rule["maximum_blocks"])


def collect(cell, row, measure, persist):
    """The live driver's only repeat loop; callbacks allow serverless proofs."""
    from abbagate import ORDER, assess, NULL_MODE
    from abba_evidence import require
    row["null_sampling_plan"] = plan(row)
    row["null_repeats"] = []
    persist()  # Exact count durable BEFORE any additional sample is requested.
    for ordinal in range(1, row["null_sampling_plan"]["planned_blocks"]):
        block = dict(instances=row["rounds"][0]["instances"], sample_offset=ordinal * len(ORDER), runs=[])
        row["null_repeats"].append(block)
        for sequence, arm in enumerate(ORDER, 1 + block["sample_offset"]):
            block["runs"].append(measure(arm, sequence, block["instances"]))
        result = assess(cell, [block], NULL_MODE)
        require(result["verdict"] == "PASS", f"{cell.id}: invalid null repeat: {result['reasons']}")
        persist()


def validate(row, frozen_policy):
    from abbagate import ORDER
    from abba_evidence import require
    require(frozen_policy == policy(), "null sampling policy differs from frozen instrument")
    expected = plan(row)
    require(row.get("null_sampling_plan") == expected, "null sampling plan differs from pilot")
    repeats = row.get("null_repeats")
    require(isinstance(repeats, list) and len(repeats) + 1 == expected["planned_blocks"],
            "incomplete fixed null sampling plan")
    for ordinal, block in enumerate(repeats, 1):
        require(block.get("instances") == row["rounds"][0]["instances"] and
                block.get("sample_offset") == ordinal * len(ORDER), "null repeat order/load differs from plan")
