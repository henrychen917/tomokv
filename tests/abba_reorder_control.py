"""Immutable, pre-campaign read-local controls; never a performance verdict.

Run the cell's GET/BITCOUNT workload with read-local OFF and ON. The armed
workload also runs the existing directed reorder OFF/ON witness: owner-executed
SETRANGE/INCR can prove engagement when clean GETs bypass the owner queue.
These two different axes must not be conflated. A zero natural permutation
count stays explicitly unobserved, backed by the directed control's counter.
"""
import copy
from dataclasses import asdict, replace
import json
from pathlib import Path
import re
import shlex
import time

from abba_evidence import require, digest, instrument, utc_seconds, NULL_MAX_AGE
from abba_instrument import instrument_fingerprint


def controlled(cell):
    return cell.op == "REORDER" and cell.read_local == 1


def needs_proof(cell):
    return controlled(cell) and cell.mode == "1s" and cell.reorder == 1


def identity(path):
    path = Path(path).resolve()
    return dict(path=str(path), sha256=digest(path.read_bytes()))


def read_bound(binding):
    from abba_standing_null import bound_bytes
    path = Path(binding["path"])
    raw = bound_bytes(binding)
    require(path.is_absolute() and digest(raw) == binding["sha256"],
            f"read-local control artifact changed: {path}")
    return json.loads(raw)


def validate_proof(proof, *, binary_sha256=None):
    """Replay both directed arms and bind the actual artifact, not just a PASS."""
    from legacy_reorder_witness import finish_control, unchanged
    require(isinstance(proof, dict) and proof.get("verdict") == "PASS" and
            proof.get("mode") == "1s" and proof.get("read_local") == 1 and
            proof.get("controls") == [0, 1] and
            type(proof.get("on_counter_delta")) is int and proof["on_counter_delta"] > 0,
            "missing passing read-local directed OFF/ON evidence or positive on_counter_delta")
    require(isinstance(proof.get("binary_sha256"), str) and
            re.fullmatch(r"[0-9a-f]{64}", proof["binary_sha256"]),
            "read-local control is missing its binary SHA-256")
    require(binary_sha256 is None or proof.get("binary_sha256") == binary_sha256,
            "read-local control binary SHA-256 differs from measured arm")
    rows = read_bound(dict(path=proof["artifact"], sha256=proof["artifact_sha256"]))
    require(isinstance(rows, list) and len(rows) == 2, "read-local control needs both directed arms")
    for reorder, row in enumerate(rows):
        require(row.get("verdict") == "PASS" and row.get("mode") == "1s" and
                row.get("reorder") == reorder and row.get("knobs", {}).get("read-local") == 1 and
                row["knobs"].get("reorder") == reorder and
                row.get("boot_info", {}).get("read_local") == "1",
                f"directed reorder={reorder} did not run with the lane armed")
        replay = finish_control(row["attempts"], reorder)
        require(all(row.get(key) == replay[key] for key in ("armed_attempts", "inversions")),
                "directed control attempt totals differ")
        for attempt in row["attempts"]:
            unchanged(attempt["before"], attempt["after"])
            require(all(attempt[name] and all(value == 0 for value in attempt[name].values())
                        for name in ("versions_before", "versions_after")),
                    "directed control has MVCC versions")
        delta = row.get("preparatory_counter_delta")
        require((type(delta) is int and delta > 0) if reorder else delta in (None, 0),
                f"directed reorder={reorder} permutation counter failed")
    require(rows[1]["preparatory_counter_delta"] == proof["on_counter_delta"],
            "directed on_counter_delta differs from artifact")
    return proof


def control_environment(environment):
    # Full calibration imports new floors AFTER these controls. The offered
    # workload here is separately fixed by each cell, including its instance count.
    return {key: value for key, value in instrument(environment).items()
            if key not in ("measurements_sha256", "population_by_arm", "data_bytes")}


def pair(cell):
    return [replace(cell, id=f"{cell.id}-rl{rl}", read_local=rl) for rl in (0, 1)]


def cell_line(cell):
    return (f"{cell.id} | {cell.mode} | rl={cell.read_local} | ov={cell.overlap} | ro={cell.reorder} | "
            f"{cell.op} | p{cell.depth} | {cell.conns} | - | - | {cell.instances or 1} | "
            f"atomic={cell.atomic} | score={cell.score} | mix={cell.mix} | smoke={int(cell.smoke)}\n")


def validate_binding(binding, *, cells, fingerprint, binary_sha256, environment, before):
    from gate_measurements import validate_fast_calibration
    receipt = read_bound(binding)
    require(receipt.get("schema") == 1 and receipt.get("kind") == "read-local-reorder-controls" and
            receipt.get("verdict") == "PASS", "missing passing campaign read-local control receipt")
    targets = [cell for cell in cells if controlled(cell)]
    require(receipt.get("cells") == [asdict(cell) for cell in targets],
            "read-local control cell inventory/shape/load differs")
    require(receipt.get("instrument") == fingerprint and receipt.get("binary_sha256") == binary_sha256,
            "read-local control instrument or frozen binary changed")
    finished = receipt.get("completed_at")
    require(type(finished) in (int, float) and 0 < finished <= before + 1 and
            0 <= time.time() - finished <= NULL_MAX_AGE,
            "read-local controls must finish before collection/freeze and be at most 24 hours old")
    workloads = read_bound(receipt["workloads"])
    validate_fast_calibration(workloads, fingerprint)
    require(workloads["candidate"]["sha256"] == binary_sha256 and
            control_environment(workloads["environment"]) == control_environment(environment),
            "read-local control workload binary/generator/geometry differs")
    require(utc_seconds(workloads["started_utc"]) + workloads["elapsed_seconds"] <= finished + 1,
            "read-local receipt predates completion of its workloads")
    expected = [variant for cell in targets for variant in pair(cell)]
    require([row["cell"] for row in workloads["cells"]] == [asdict(cell) for cell in expected] and
            workloads["cell_source"]["text"] == "".join(cell_line(cell) for cell in expected),
            "read-local OFF/ON workload pair differs from campaign cells")
    proofs = {}
    for cell, rows in zip(targets, zip(workloads["cells"][::2], workloads["cells"][1::2])):
        for rl, row in enumerate(rows):
            require(len(row["rounds"]) == 1 and row["rounds"][0]["instances"] == (cell.instances or 1),
                    f"{cell.id}: read-local={rl} must run once at the cell's offered load")
            run = row["rounds"][0]["runs"][0]
            require(run.get("population_reused") is False and
                    all(run["workload_raw"][name].get("read_local") == str(rl)
                        for name in ("mode_before", "mode_after")),
                    f"{cell.id}: read-local={rl} workload did not observe its boot mode")
            if rl and needs_proof(cell):
                proof = run["workload_raw"].get("read_local_control")
                proofs[cell.id] = validate_proof(proof, binary_sha256=binary_sha256)
    require(receipt.get("proofs") == proofs, "read-local receipt proofs differ from raw workloads")
    return proofs


def attach(runner, report, cells):
    path = getattr(runner.args, "reorder_controls", None)
    if path is None:
        return
    binding = identity(path)
    require(all(digest(Path(binary).read_bytes()) == report["candidate"]["sha256"]
                for binary in runner.binaries.values()),
            "campaign control reuse requires the same frozen binary in every arm")
    runner.campaign_reorder_controls = validate_binding(binding, cells=cells,
        fingerprint=report["instrument_fingerprint"], binary_sha256=report["candidate"]["sha256"],
        environment=report["environment"], before=utc_seconds(report["started_utc"]))
    report["reorder_controls"] = binding


def active_cells(report):
    from abbagate import Cell
    return [row["cell"]["id"] for row in report["cells"] if needs_proof(Cell(**row["cell"])) and
            any(run.get("workload_raw", {}).get("mode_before", {}).get("reorder_retired") != "1"
                for block in row["rounds"] for run in block["runs"])]


def validate_report(report, binding, *, before):
    from abbagate import Cell
    required = active_cells(report)
    if not binding:
        require(not required, f"{','.join(required)}: missing frozen read-local control receipt" +
                refusal_hint(','.join(required), report))
        return
    require(report.get("reorder_controls") == binding,
            "campaign read-local control receipt differs from collection provenance")
    try:
        proofs = validate_binding(binding, cells=[Cell(**row["cell"]) for row in report["cells"]],
            fingerprint=report["instrument_fingerprint"], binary_sha256=report["candidate"]["sha256"],
            environment=report["environment"], before=before)
    except (ValueError, RuntimeError, OSError, KeyError, TypeError) as error:
        raise ValueError(f"read-local control receipt invalid: {error}" +
                         refusal_hint(','.join(required), report)) from error
    for row in report["cells"]:
        if row["cell"]["id"] in required:
            for block in row["rounds"]:
                for run in block["runs"]:
                    require(run["workload_raw"].get("read_local_control") == proofs[row["cell"]["id"]],
                            f"{row['cell']['id']}: raw read-local evidence differs from frozen receipt" +
                            refusal_hint(row['cell']['id'], report))


def refusal_hint(cell_id, report=None):
    from gateplan import cpu_string
    report = report or {}
    env = report.get("environment", {})
    argv = ["python3", "tests/abbagate.py", "--collect-reorder-controls", "--subset", "full",
            "--candidate", report.get("candidate", {}).get("path", "<frozen-binary>"),
            "--cells", report.get("cell_source", {}).get("path", "tests/headline_cells.txt"),
            "--memtier", env.get("memtier_path", "<frozen-memtier>"), "--build-reference", "0"]
    for flag, key, default in (("server-cores", "server_physical", list(range(32))),
                               ("server-smt", "server_smt", []),
                               ("load-cores", "load_physical", list(range(32, 128))),
                               ("load-smt", "load_smt", list(range(160, 256)))):
        argv += ["--" + flag, cpu_string(env.get(key, default))]
    port = env.get("port", 8700)
    argv += ["--ports", f"{port}-{port}", "--port", str(port), "--max-instances",
             str(env.get("load_instance_ceiling", 16)), "--output", "build/reorder-controls-NEW"]
    return (f"\nMissing/invalid evidence for {cell_id}: workload_raw.read_local_control and its frozen receipt.\n"
            f"Prepare on the quiet campaign cores BEFORE a fresh collection:\n  {shlex.join(argv)}\n"
            "Pass --reorder-controls build/reorder-controls-NEW/receipt.json to calibration, "
            "freeze-null, null and holdout. Preserve the refused run; this command does not repair it.")


def collect(args):
    """Use the existing one-arm collector for matched workloads and all cleanup."""
    import abbagate as abba
    from load_calibration import main as calibration_main
    require(not any((args.collect_null, args.calibrate, args.pin, args.escalate, args.list_cells,
                     args.only, args.reorder_controls)) and args.subset == "full",
            "control collection requires full inventory without other collection/selection switches")
    out = (args.output or abba.ROOT / "build" / f"reorder-controls-{time.time_ns()}").resolve()
    out.mkdir(parents=True, exist_ok=False)
    targets = [cell for cell in abba.read_cells(args.cells) if controlled(cell)]
    require(targets, "no read-local REORDER cells in campaign inventory")
    variants = [variant for cell in targets for variant in pair(cell)]
    source = out / "workloads.cells"
    source.write_text("".join(cell_line(cell) for cell in variants))
    options = copy.copy(args)
    options.cells, options.output = source, out / "workloads"
    options.collect_reorder_controls, options.calibrate = False, True
    rc = calibration_main(options)
    require(rc == 3, f"campaign read-local OFF/ON control failed (rc={rc}); retain {out}")
    workload_path = options.output / "results.json"
    workloads = json.loads(workload_path.read_bytes())
    proofs = {cell.id: row["rounds"][0]["runs"][0]["workload_raw"].get("read_local_control")
              for cell, row in zip(targets, workloads["cells"][1::2]) if needs_proof(cell)}
    receipt = dict(schema=1, kind="read-local-reorder-controls", verdict="PASS", completed_at=time.time(),
        cells=[asdict(cell) for cell in targets], instrument=workloads["instrument_fingerprint"],
        binary_sha256=workloads["candidate"]["sha256"], workloads=identity(workload_path), proofs=proofs,
        scope="unscored read-local OFF/ON workloads plus armed directed reorder OFF/ON engagement")
    # Publish only after complete replay; a failed receipt never looks consumable.
    pending = out / "receipt.pending.json"
    pending.write_text(json.dumps(receipt, indent=2) + "\n")
    validate_binding(identity(pending), cells=targets, fingerprint=instrument_fingerprint(abba.ROOT),
        binary_sha256=abba.sha256(args.candidate), environment=workloads["environment"], before=time.time())
    pending.rename(out / "receipt.json")
    print(f"Campaign read-local controls PASS: {out / 'receipt.json'}", flush=True)
    return 0
