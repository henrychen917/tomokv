"""Unsaturated ceiling observations: fixed-load controls, never capacity floors."""
import math


CEILING_STATUSES = ("LOADGEN-BOUND", "CEILING-UNCONFIRMED")


def ceiling_observation(rows, ceiling):
    from abbagate import BUSY_FLOOR, RUN_SATURATION_MARGIN, PLATEAU_TOLERANCE_PCT
    if ceiling is None or len(rows) < 2 or rows[-1]["instances"] != ceiling:
        return None
    before, last = rows[-2:]
    slope = 100 * (last["rate"] / before["rate"] - 1)
    more_workers = last["worker_threads"] > before["worker_threads"]
    # Low occupancy alone cannot identify a generator bottleneck. Require a
    # material rise under increased worker capacity, without an occupied rung.
    bound = (slope > PLATEAU_TOLERANCE_PCT and more_workers and
             last["saturation_pct"] < BUSY_FLOOR - RUN_SATURATION_MARGIN and
             max(row["saturation_pct"] for row in rows) < BUSY_FLOOR)
    return dict(status="LOADGEN-BOUND" if bound else "CEILING-UNCONFIRMED",
        instances=ceiling, achieved_rate=last["rate"], previous_instances=before["instances"],
        previous_rate=before["rate"], slope_pct=slope,
        slope_ops_per_instance=(last["rate"] - before["rate"]) / (ceiling - before["instances"]),
        server_occupancy_pct=last["saturation_pct"], worker_threads=last["worker_threads"],
        previous_worker_threads=before["worker_threads"], higher_worker_capacity=more_workers,
        reason="rising-load-underfilled-server" if bound else
               "occupied-without-confirmation" if last["saturation_pct"] >= BUSY_FLOOR else
               "underfilled-flat-or-confounded", saturated_peak_floor=None)


def campaign_verdict(rows):
    from abba_saturation import saturation_exempt
    if any(row["status"] in CEILING_STATUSES for row in rows):
        return "CEILING-LIMITED"
    return "EXEMPT" if all(saturation_exempt(row["cell"]) for row in rows) else "PIN"


def validate_ceiling_plan(plan):
    """Validate imported DATA; raw calibration replay authorizes its creation."""
    from gate_measurements import require, provenance, SHAPE, AXES
    import re
    require(set(plan) == {"instances", "shape", "geometry", "instrument_sha256", "status",
                         "evidence", "calibration_sha256", "binary_sha256", "provenance"},
            "invalid ceiling-only plan fields")
    require(plan["status"] in CEILING_STATUSES and type(plan["instances"]) is int and plan["instances"] > 0,
            "invalid ceiling-only plan status/instances")
    require(set(plan["shape"]) in (set(SHAPE), set(SHAPE) | {"data_bytes"}) and
            set(plan["geometry"]) == set(AXES), "invalid ceiling-only shape/geometry")
    for field in ("instrument_sha256", "calibration_sha256", "binary_sha256"):
        require(isinstance(plan[field], str) and re.fullmatch("[0-9a-f]{64}", plan[field]),
                "ceiling-only plan lacks provenance digest")
    ev = plan["evidence"]
    require(isinstance(ev, dict) and ev.get("status") == plan["status"] and
            ev.get("instances") == plan["instances"] and "saturated_peak_floor" in ev and
            ev["saturated_peak_floor"] is None, "ceiling observation cannot authorize a saturated floor")
    for field in ("achieved_rate", "previous_rate", "slope_pct", "slope_ops_per_instance", "server_occupancy_pct"):
        require(type(ev.get(field)) in (int, float) and math.isfinite(ev[field]),
                "invalid ceiling observation: " + field)
    require(ev["achieved_rate"] > 0 and ev["previous_rate"] > 0 and 0 <= ev["server_occupancy_pct"] <= 100,
            "invalid ceiling rate/occupancy")
    provenance(plan["provenance"], "ceiling-only plan")


def validate_ceiling_controls(report, cells):
    from gate_measurements import require, shape, geometry
    plans = report.get("ceiling_loads", {})
    expected = {cell["id"]: cell for cell in cells if cell.get("ceiling_status")}
    require(isinstance(plans, dict) and set(plans) == set(expected), "missing/extra ceiling-control provenance")
    for ident, cell in expected.items():
        plan = plans[ident]
        validate_ceiling_plan(plan)
        require(plan["status"] == cell["ceiling_status"] and plan["instances"] == cell["instances"] and
                plan["instances"] == min(report["environment"]["load_instance_ceiling"], cell["conns"],
                                         len(report["environment"]["load_physical"])) and
                plan["shape"] == shape(cell) and plan["geometry"] == geometry(report["environment"]) and
                plan["instrument_sha256"] == report["instrument_fingerprint"]["sha256"],
                f"{ident}: ceiling-control load/geometry/instrument changed")
        require(report["candidate"]["sha256"] == report["reference"]["sha256"] == plan["binary_sha256"],
                f"{ident}: ceiling-only controls require calibrated byte-identical arms; saturation UNPROVEN")
